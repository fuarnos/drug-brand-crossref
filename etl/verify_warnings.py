"""dose_warning 来源核验（AI 自动定案）：对 41 条种子的 `source_url` 做 HTTP 核验，
按规则输出 promote / keep / drop，并可把结论写入 `dose_warning.status`。

背景（task-35）：/warn 页即将只显示 `status='published'`；种子 41 条是 AI 依据监管来源
写的，但此前只做了人工抽查。本脚本把「来源可不可达 + 域名是否权威 + 页面文本是否命中
关键药名」做成可复现的自动规则（**纯 AI，无人工复核**）：

    promote  → HTTP 2xx + 权威域名 + 页面文本命中 ≥1 关键药名（或完整查询短语）
    keep     → 可达(2xx)但文本不命中（JS 渲染/看不到正文）；或 403/429 反爬；或
               TLS 证书链异常但域名权威（浏览器可能仍可达）→ 保持 draft，不进 /warn
    drop     → 404/410、DNS/连接失败、最终域名不在白名单、其它 4xx/5xx → status='retracted'
               （schema 无 rejected；retracted 保留记录，/warn 不显示，符合「撤回不删」）

注意：本脚本只做**来源级**核验（页面还在、域名权威、药名出现），不等于逐句核对
warning 的临床表述；事实性结论仍以种子里的 evidence + 来源为准。

CLI：
    python etl/verify_warnings.py --dry-run                  # 默认：联网核验 + 写 CSV
    python etl/verify_warnings.py --apply --db PATH          # 写 dose_warning.status（先备份）
    python etl/verify_warnings.py --apply --db PATH --from-csv data/warning_verification.csv
    python etl/verify_warnings.py --rollback --db PATH
    python etl/verify_warnings.py --verify --db PATH         # 打印 status 分布

安全：真实库 data/drugs.db 上的 --apply/--rollback 必须加 --confirm-real-db；
本轮只在 .tmp/warn-verify/test.db 副本上验证，真实库由 Lead apply。
"""

from __future__ import annotations

import argparse
import csv
import html as html_lib
import json
import re
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data"))
from seed_warnings import WARNINGS  # noqa: E402

DEFAULT_DB = ROOT / "data" / "drugs.db"
DEFAULT_CSV = ROOT / "data" / "warning_verification.csv"
WORK = ROOT / ".tmp" / "warn-verify"
BACKUP_DIR = WORK / "backups"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 drug-brand-crossref/0.3 verification-bot")
CTX = ssl.create_default_context()
TIMEOUT = 25
MAX_BYTES = 800_000
RETRIES_TRANSIENT = 1

# 权威域名白名单：监管机构 / 官方标签库 / 政府开放数据（含子域）
WHITELIST = (
    "dailymed.nlm.nih.gov", "nlm.nih.gov", "fda.gov", "nih.gov", "medlineplus.gov",
    "ema.europa.eu", "who.int", "iris.who.int",
    "medicines.org.uk",          # MHRA 授权的英国 SmPC/PL 数据库
    "canada.ca", "health-products.canada.ca",
    "health.gov.au", "tga.gov.au", "nhsbsa.nhs.uk", "gov.uk",
    "nmpa.gov.cn",               # 国家药监局（CN 官方）
    "nhsa.gov.cn", "code.nhsa.gov.cn",
    "aemps.gob.es", "cima.aemps.es",
    "gob.mx", "datos.gob.mx", "cofepris.gob.mx",
)

# 少数 URL 无法从 query 推导关键药名（NMPA 是检索首页，没有 query 参数）
KEY_TERMS_OVERRIDE: dict[str, list[str]] = {
    "tainuo-vs-tainuolin": ["泰诺", "泰诺林", "对乙酰氨基酚", "paracetamol", "acetaminophen"],
}

STATUS_BY_DECISION = {"promote": "published", "keep": "draft", "drop": "retracted"}
DECISIONS = tuple(STATUS_BY_DECISION)

FIELDS = ["warning_id", "current_status", "decision", "target_status", "reason",
          "http_status", "domain", "domain_ok", "key_terms", "text_hits",
          "phrase_hit", "final_url", "bytes", "elapsed_s", "snippet", "checked_at"]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _domain(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


_RE_SCRIPT = re.compile(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>",
                        re.I | re.S)
_RE_TAG = re.compile(r"<[^>]+>")


def visible_text(raw: str) -> str:
    """HTML → 可见文本（去脚本/样式/标签、还原实体、压空白）。命中判断只看可见文本。"""
    s = _RE_SCRIPT.sub(" ", raw or "")
    s = _RE_TAG.sub(" ", s)
    s = html_lib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def domain_ok(url: str) -> bool:
    host = _domain(url)
    return any(host == d or host.endswith("." + d) for d in WHITELIST)


def key_terms(warning: dict) -> list[str]:
    """从 URL query/q 提取药名 token；取不到就用 title_en 里的词兜底。"""
    if warning["warning_id"] in KEY_TERMS_OVERRIDE:
        return KEY_TERMS_OVERRIDE[warning["warning_id"]]
    q = None
    query = urllib.parse.urlsplit(warning["source_url"]).query
    params = urllib.parse.parse_qs(query)
    raw = (params.get("query") or params.get("q") or [""])[0]
    if raw:
        return [t.lower() for t in raw.replace("+", " ").split() if len(t) > 3]
    words = [w.strip(".,;:()").lower() for w in warning["title_en"].split()]
    return [w for w in words if len(w) > 4][:4]


def _fetch_once(url: str) -> dict:
    rec = {"http_status": None, "final_url": url, "bytes": 0, "text": "",
           "error": None, "elapsed_s": 0.0}
    t0 = time.time()
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as resp:
            body = resp.read(MAX_BYTES)
            rec.update(http_status=resp.status, final_url=resp.geturl(), bytes=len(body),
                       text=body.decode("utf-8", "ignore"))
    except urllib.error.HTTPError as exc:
        rec.update(http_status=exc.code, error=f"HTTPError {exc.code}")
        try:
            rec["text"] = exc.read(60_000).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            pass
    except ssl.SSLError as exc:
        rec["error"] = f"SSL: {exc}"
    except urllib.error.URLError as exc:
        reason = str(exc.reason)
        rec["error"] = f"URLerror: {reason}"
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"
    rec["elapsed_s"] = round(time.time() - t0, 2)
    return rec


def fetch(url: str) -> dict:
    """抓取；对超时/连接类错误重试一次（TLS/HTTP 错误不重试）。"""
    last = _fetch_once(url)
    for _ in range(RETRIES_TRANSIENT):
        if last["http_status"] is not None or (last["error"] or "").startswith(("SSL", "HTTPError")):
            break
        time.sleep(1.0)
        last = _fetch_once(url)
    return last


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def decide(warning: dict, rec: dict) -> tuple[str, str]:
    """→ (decision, reason)。规则见模块 docstring。"""
    terms = key_terms(warning)
    text = rec.get("_visible_low")
    if text is None:
        text = (rec.get("text") or "").lower()
    hits = [t for t in terms if t in text]
    phrase = " ".join(terms)
    phrase_hit = bool(phrase) and phrase in text
    rec["_keys"], rec["_hits"], rec["_phrase_hit"] = terms, hits, phrase_hit

    err = rec.get("error") or ""
    status = rec.get("http_status")

    if err.startswith("SSL") or "CERTIFICATE_VERIFY_FAILED" in err:
        return "keep", "TLS 证书链异常，程序化不可达但域名权威（浏览器可能可达）"
    if status in (404, 410):
        return "drop", f"来源已不存在（HTTP {status}）"
    if status in (403, 406, 429):
        return "keep", f"反爬/拒绝程序化访问（HTTP {status}），保留 draft 待人工浏览器复核"
    if status is not None and 400 <= status < 500:
        return "drop", f"客户端错误（HTTP {status}）"
    if status is not None and status >= 500:
        return "drop", f"服务端错误（HTTP {status}）"
    if status is None:
        return "drop", f"不可达：{err or 'unknown'}"
    # 2xx
    final = rec.get("final_url") or warning["source_url"]
    if not domain_ok(final):
        return "drop", f"最终域名非权威：{_domain(final)}"
    if hits:
        return "promote", f"可达 + 权威域名 + 命中关键药名 {hits}"
    if phrase_hit:
        return "promote", f"可达 + 权威域名 + 命中查询短语「{phrase}」"
    return "keep", "可达但页面正文未命中关键药名（可能 JS 渲染/检索页无结果）"


def verify_all(workers: int = 6) -> list[dict]:
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fetch, w["source_url"]): w for w in WARNINGS}
        for fut in as_completed(futs):
            warning = futs[fut]
            rec = fut.result()
            rec["_visible"] = visible_text(rec.get("text") or "")
            rec["_visible_low"] = rec["_visible"].lower()
            decision, reason = decide(warning, rec)
            final_url = rec.get("final_url") or warning["source_url"]
            snippet = ""
            visible = rec.get("_visible") or ""
            low = visible.lower()
            for term in rec["_hits"]:
                pos = low.find(term)
                if pos >= 0:
                    snippet = visible[max(0, pos - 80):pos + 140].strip()
                    break
            if not snippet and visible:
                snippet = visible[:200]
            rows[warning["warning_id"]] = {
                "warning_id": warning["warning_id"],
                "current_status": warning["status"],
                "decision": decision,
                "target_status": STATUS_BY_DECISION[decision],
                "reason": reason,
                "http_status": rec.get("http_status") or "",
                "domain": _domain(final_url),
                "domain_ok": int(domain_ok(final_url)),
                "key_terms": "|".join(rec["_keys"]),
                "text_hits": "|".join(rec["_hits"]),
                "phrase_hit": int(rec["_phrase_hit"]),
                "final_url": final_url,
                "bytes": rec.get("bytes") or 0,
                "elapsed_s": rec.get("elapsed_s") or 0,
                "snippet": snippet[:200],
                "checked_at": checked_at,
            }
    return [rows[w["warning_id"]] for w in WARNINGS]


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        if r["decision"] not in DECISIONS:
            raise SystemExit(f"CSV 中非法 decision：{r['warning_id']} {r['decision']}")
    return rows


def print_summary(rows: list[dict]) -> None:
    counts = {d: sum(1 for r in rows if r["decision"] == d) for d in DECISIONS}
    unreachable = [r for r in rows if str(r["http_status"]) in ("", "None")]
    nohit = [r for r in rows if r["decision"] == "keep"]
    print("=== verify_warnings 结果 ===")
    print(f"总数      : {len(rows)}")
    print(f"promote   : {counts['promote']}（→ published）")
    print(f"keep      : {counts['keep']}（→ draft）")
    print(f"drop      : {counts['drop']}（→ retracted）")
    print(f"不可达    : {len(unreachable)} → "
          f"{[(r['warning_id'], r['reason'][:40]) for r in unreachable] or '无'}")
    print(f"keep 明细 : {[(r['warning_id'], r['reason'][:48]) for r in nohit] or '无'}")
    domains = sorted({r["domain"] for r in rows})
    print(f"域名      : {domains}")


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
def _connect(db_path: Path, write: bool) -> sqlite3.Connection:
    if write:
        return sqlite3.connect(db_path, timeout=120)
    return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=120)


def _guard_target(db_path: Path, action: str, confirmed: bool) -> None:
    try:
        is_real = db_path.resolve() == DEFAULT_DB.resolve()
    except OSError:
        is_real = False
    if is_real and action in ("apply", "rollback") and not confirmed:
        raise SystemExit(
            f"拒绝在真实库 {db_path} 上执行 --{action}：本轮只做副本验证。\n"
            "确认要写时加 --confirm-real-db，并先备份 data/drugs.db。"
        )


def cmd_apply(args: argparse.Namespace, rows: list[dict]) -> int:
    db = _connect(args.db, write=True)
    try:
        table = db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='dose_warning'"
        ).fetchone()[0]
        if not table:
            print("dose_warning 表不存在：先跑 db/init_db.py 与 data/seed_warnings.py --apply",
                  file=sys.stderr)
            return 1
        current = {r[0]: r[1] for r in db.execute(
            "SELECT warning_id, status FROM dose_warning")}
        plan = [r for r in rows if r["warning_id"] in current
                and current[r["warning_id"]] != STATUS_BY_DECISION[r["decision"]]]
        missing = [r["warning_id"] for r in rows if r["warning_id"] not in current]
        print(f"库内 dose_warning : {len(current):,} 行；计划更新 {len(plan)} 行；"
              f"种子缺失 {len(missing):,} 行")
        if missing:
            print(f"  缺失（先跑 seed_warnings --apply）：{missing}", file=sys.stderr)
        if not plan:
            print("无需更新。")
            return 0
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = BACKUP_DIR / f"rollback_warning_status_{stamp}.csv"
        with backup.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["warning_id", "status_before", "status_after"])
            for r in plan:
                w.writerow([r["warning_id"], current[r["warning_id"]],
                            STATUS_BY_DECISION[r["decision"]]])
        (BACKUP_DIR / "rollback_warning_status_latest.csv").write_text(
            backup.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"回滚备份 : {backup}")
        with db:
            db.executemany(
                "UPDATE dose_warning SET status=?, updated_at=? WHERE warning_id=?",
                [(STATUS_BY_DECISION[r["decision"]], _now_iso(), r["warning_id"])
                 for r in plan])
        print(f"已更新 {len(plan)} 行 status。")
        return 0
    finally:
        db.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_rollback(args: argparse.Namespace) -> int:
    path = args.rollback_file
    if path is None:
        latest = BACKUP_DIR / "rollback_warning_status_latest.csv"
        path = latest if latest.exists() else None
    if path is None:
        print(f"找不到备份 CSV（{BACKUP_DIR}）", file=sys.stderr)
        return 1
    with Path(path).open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    db = _connect(args.db, write=True)
    try:
        current = {r[0]: r[1] for r in db.execute(
            "SELECT warning_id, status FROM dose_warning")}
        plan = []
        skipped = 0
        for r in rows:
            wid = r["warning_id"]
            if current.get(wid) == r["status_after"]:
                plan.append((r["status_before"], wid))
            else:
                skipped += 1
        with db:
            db.executemany(
                "UPDATE dose_warning SET status=? WHERE warning_id=?", plan)
        print(f"=== verify_warnings --rollback ===\n备份 {path}\n"
              f"还原 {len(plan)} 行（跳过已变更 {skipped}）")
        return 0
    finally:
        db.close()


def cmd_verify(args: argparse.Namespace) -> int:
    db = _connect(args.db, write=False)
    try:
        print("=== verify_warnings --verify ===")
        for status, n in db.execute(
                "SELECT status, COUNT(*) FROM dose_warning GROUP BY status ORDER BY status"):
            print(f"  {status:10} {n}")
        print(f"  合计       {db.execute('SELECT COUNT(*) FROM dose_warning').fetchone()[0]}")
        return 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="dose_warning 来源核验（AI 自动定案）")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="联网核验 + 写 CSV（默认）")
    mode.add_argument("--apply", action="store_true", help="按结论更新 dose_warning.status")
    mode.add_argument("--rollback", action="store_true", help="用备份 CSV 还原 status")
    mode.add_argument("--verify", action="store_true", help="打印库内 status 分布")
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="核验结果 CSV")
    ap.add_argument("--from-csv", type=Path, default=None,
                    help="--apply 时直接使用已有 CSV 结论，不联网")
    ap.add_argument("--rollback-file", type=Path, default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--confirm-real-db", action="store_true")
    args = ap.parse_args(argv)

    action = ("verify" if args.verify else "rollback" if args.rollback
              else "apply" if args.apply else "dry")
    if action in ("apply", "rollback"):
        _guard_target(args.db, action, args.confirm_real_db)
    if action in ("apply", "rollback") and not args.db.exists():
        print(f"数据库不存在：{args.db}", file=sys.stderr)
        return 1

    if action == "verify":
        return cmd_verify(args)
    if action == "rollback":
        return cmd_rollback(args)

    if args.from_csv and action == "apply":
        rows = read_csv(args.from_csv)
        print(f"从 CSV 读入核验结论：{args.from_csv}（{len(rows)} 行，不联网）")
    else:
        print(f"开始联网核验 {len(WARNINGS)} 条 source_url ...")
        rows = verify_all(workers=args.workers)
        write_csv(rows, args.csv)
        print(f"核验结果 CSV：{args.csv}")
        print_summary(rows)
    if action == "apply":
        return cmd_apply(args, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
