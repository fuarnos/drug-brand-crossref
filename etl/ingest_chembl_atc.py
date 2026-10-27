# -*- coding: utf-8 -*-
"""ChEMBL ATC 分类 → substance.atc 补全（默认 dry-run）。

来源与许可
----------
ChEMBL（EMBL-EBI）的 ATC 分类表（level5 7 位码 + who_name = WHO INN 名），
许可 **CC BY-SA 4.0**：可再发布/改编，需署名 + 相同方式共享；本站只取码值与
WHO INN 名做对齐，不复制 WHOCC 的 DDD 文本。缓存 `data/raw/chembl/atc_class.json`
（由 `etl/fetch_chembl_atc.py --download` 拉取，5,579 行）。

匹配策略（只补 substance.atc 为空的成分）
---------------------------------------
  1. name_exact    inn_en 归一后 = who_name
  2. name_paren    去掉括号注释（"Camphor (Synthetic)" → camphor）
  3. name_base     去掉盐/酯/水合物后缀（"Metformin Hydrochloride" → metformin）
  4. name_alias    常见 INN/USAN/BAN 拼写别名（lignocaine→lidocaine 等）
  5. name_spelling 英式/美式拼写归一（ae→e、oe→e、ph→f 等，仅用于唯一码）
  6. molecule_fallback（可选 `--molecule-check N`）：对未命中的高产品数成分，
     再查一次 ChEMBL `molecule.json?pref_name__iexact=`（任务要求的 molecule 路径）

歧义处理：同一名字命中多个 ATC 码时，**恰好一个 7 位完整码**才采用；否则只有
**唯一一个码**才采用；其余跳过（宁可缺，不可错）。

只读：dry-run 用 mode=ro。`--apply` 默认拒绝写 `data/drugs.db`（本任务要求
只在 `.tmp/atc/` 副本验证），必须显式 `--db .tmp/atc/drugs-test.db`。

用法：
    python etl/ingest_chembl_atc.py                       # dry-run
    python etl/ingest_chembl_atc.py --dry-run --sample 20
    python etl/ingest_chembl_atc.py --molecule-check 25   # 追加 molecule 端点查漏
    python etl/ingest_chembl_atc.py --apply --db .tmp/atc/drugs-test.db
    python etl/ingest_chembl_atc.py --rollback --db .tmp/atc/drugs-test.db
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import ssl
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
CACHE = ROOT / "data" / "raw" / "chembl" / "atc_class.json"
META = ROOT / "data" / "raw" / "chembl" / "meta.json"
ENTITY = ROOT / "data" / "entity_type.csv"
MOLCACHE = ROOT / "data" / "raw" / "chembl" / "molecule_lookup.json"
EVID = ROOT / ".tmp" / "atc"
APPLIED = EVID / "applied_chembl_atc.json"
TODAY = date.today().isoformat()
SOURCE_ID = "chembl_atc"
API = "https://www.ebi.ac.uk/chembl/api/data"
UA = ("drug-brand-crossref/0.3 (ATC coverage ETL; ChEMBL atc_class; "
      "contact: https://github.com/fuarnos/drug-brand-crossref)")

RE_ATC = re.compile(r"^[A-Z][0-9]{2}[A-Z]{2}[0-9]{2}$")
RE_NONALNUM = re.compile(r"[^a-z0-9]+")
ALLOWED_TYPES = {"inn_drug", "biologic", "food"}

EN_SALT_SUFFIX = {
    "hydrochloride", "hydrobromide", "sodium", "potassium", "calcium", "magnesium",
    "sulfate", "sulphate", "phosphate", "citrate", "maleate", "fumarate", "tartrate",
    "mesylate", "besylate", "tosylate", "acetate", "succinate", "lactate", "gluconate",
    "carbonate", "bicarbonate", "nitrate", "chloride", "bromide", "iodide",
    "hydrate", "dihydrate", "trihydrate", "monohydrate", "anhydrous", "salt",
    "hcl", "hbr", "base", "ester", "sodium salt", "potassium salt",
}

# INN / USAN / BAN 常见拼写差（键=DB 里的写法，值=ChEMBL who_name 更可能用的写法）
ALIASES = {
    "lignocaine": "lidocaine", "adrenaline": "epinephrine",
    "noradrenaline": "norepinephrine", "albuterol": "salbutamol",
    "acetaminophen": "paracetamol", "glyburide": "glibenclamide",
    "indomethacin": "indometacin", "amoxycillin": "amoxicillin",
    "frusemide": "furosemide", "oestradiol": "estradiol", "oestriol": "estriol",
    "haemophilus": "hemophilus", "sulpha": "sulfa", "sulphonamide": "sulfonamide",
    "chlorthalidone": "chlortalidone", "sodium cromoglycate": "cromoglicate sodium",
    "cromoglycate": "cromoglicate", "taurine": "taurine", "nicotine": "nicotine",
    "pethidine": "meperidine", "chlorphenamine": "chlorpheniramine",
    "methylphenobarbitone": "methylphenobarbital", "phenobarbitone": "phenobarbital",
    "thiopentone": "thiopental", "amylobarbitone": "amobarbital",
    "liquorice": "licorice", "sodium valproate": "valproate sodium",
}


def strip_acc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if not unicodedata.combining(c))


def norm(s: str) -> str:
    s = strip_acc(s or "").lower()
    s = RE_NONALNUM.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def strip_paren(name: str) -> str:
    return re.sub(r"\s*\([^)]*\)?", "", name or "").strip()


def strip_en_salt(name: str) -> str:
    toks = norm(name).split()
    while toks and toks[-1] in EN_SALT_SUFFIX:
        toks.pop()
    return " ".join(toks)


def spelling_variants(name: str) -> list[str]:
    n = norm(name)
    out = {n}
    repl = [(r"ae", "e"), (r"oe", "e"), (r"ph", "f"), (r"th", "t"), (r"c", "k")]
    for a, b in repl:
        if a in n:
            out.add(n.replace(a, b))
    return [x for x in out if x]


# --- 缓存 -------------------------------------------------------------------
def load_cache() -> tuple[dict, list[dict]]:
    if not CACHE.exists():
        raise SystemExit("缓存不存在：先运行 python etl/fetch_chembl_atc.py --download")
    payload = json.loads(CACHE.read_text(encoding="utf-8"))
    return payload.get("meta") or {}, payload.get("atc_class") or []


def load_entity_types() -> dict[str, str]:
    out: dict[str, str] = {}
    if ENTITY.exists():
        with ENTITY.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                out[r["substance_id"]] = r["entity_type"]
    return out


def build_index(rows: list[dict]) -> tuple[dict, dict[str, str]]:
    """who_name 归一 → {7 位 ATC 码}；另存 code→who_name。"""
    idx: dict[str, set[str]] = defaultdict(set)
    names: dict[str, str] = {}
    for r in rows:
        code = (r.get("level5") or "").strip().upper()
        who = (r.get("who_name") or "").strip()
        if not code or not RE_ATC.match(code) or not who:
            continue
        idx[norm(who)].add(code)
        names.setdefault(code, who)
    return dict(idx), names


def pick_atc(codes: set[str]) -> tuple[str | None, str]:
    full = {c for c in codes if len(c) == 7}
    if len(full) == 1:
        return next(iter(full)), "unique_full"
    if len(codes) == 1:
        return next(iter(codes)), "unique_only"
    return None, "ambiguous"


# --- 数据库 -----------------------------------------------------------------
def connect(db_path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = "file:" + str(db_path.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=60)
    else:
        con = sqlite3.connect(db_path, timeout=60)
    con.row_factory = sqlite3.Row
    return con


def load_candidates(con: sqlite3.Connection, entity_types: dict[str, str],
                    allowed: set[str]) -> tuple[list[dict], dict]:
    rows = [dict(r) for r in con.execute(
        "SELECT substance_id, inn_en, inn_zh, atc FROM substance")]
    missing = [r for r in rows if not (r["atc"] or "").strip()]
    for r in missing:
        r["entity_type"] = entity_types.get(r["substance_id"], "unknown")
    candidates = [r for r in missing if r["entity_type"] in allowed]
    stats = {
        "substances_total": len(rows),
        "with_atc": len(rows) - len(missing),
        "missing_atc": len(missing),
        "missing_drug_like": len(candidates),
        "missing_by_type": dict(Counter(r["entity_type"] for r in missing)),
    }
    return candidates, stats


# --- molecule 端点补漏（任务要求的「按 INN 查 molecule」路径） ------------------
def molecule_lookup(names: list[str]) -> dict[str, list[str]]:
    """对给定名字查 ChEMBL molecule，返回 name→{7 位 ATC 码}。结果落缓存。"""
    cache: dict[str, list[str]] = {}
    if MOLCACHE.exists():
        try:
            cache = json.loads(MOLCACHE.read_text(encoding="utf-8")).get("lookup") or {}
        except json.JSONDecodeError:
            cache = {}
    ctx = ssl.create_default_context()
    changed = 0
    for name in names:
        if name in cache:
            continue
        url = f"{API}/molecule.json?" + urllib.parse.urlencode(
            {"pref_name__iexact": name, "limit": 5})
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        codes: set[str] = set()
        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                data = json.loads(r.read().decode("utf-8"))
            for mol in data.get("molecules") or []:
                for code in mol.get("atc_classifications") or []:
                    code = (code or "").strip().upper()
                    if RE_ATC.match(code):
                        codes.add(code)
        except Exception as e:  # noqa: BLE001
            print(f"    molecule 查询失败 {name}: {type(e).__name__} {e}")
        cache[name] = sorted(codes)
        changed += 1
        time.sleep(0.2)
    if changed:
        MOLCACHE.parent.mkdir(parents=True, exist_ok=True)
        MOLCACHE.write_text(json.dumps(
            {"meta": {"source": "ChEMBL molecule.json（pref_name__iexact）",
                      "license": "CC BY-SA 4.0", "retrieved_at": TODAY,
                      "note": "仅对 atc_class 未命中的高产品数成分做二次查漏"},
             "lookup": cache}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: v for k, v in cache.items() if v}


# --- 匹配 -------------------------------------------------------------------
def match(candidates: list[dict], idx: dict[str, set[str]], names: dict[str, str],
          molecule_hits: dict[str, list[str]], np_by_sid: dict[str, int]) -> tuple[list[dict], dict, list[dict]]:
    hits: list[dict] = []
    stats: Counter = Counter()
    ambiguous: list[dict] = []
    for sub in candidates:
        inn = (sub["inn_en"] or "").strip()
        found = None  # (path, codes, matched)
        for path, name in (
            ("name_exact", inn),
            ("name_paren", strip_paren(inn)),
            ("name_base", strip_en_salt(inn)),
        ):
            n = norm(name)
            if n and n in idx:
                found = (path, idx[n], name)
                break
        if found is None:
            n = norm(inn)
            if n in ALIASES and norm(ALIASES[n]) in idx:
                found = ("name_alias", idx[norm(ALIASES[n])], ALIASES[n])
        if found is None:
            for v in spelling_variants(inn):
                if v in idx:
                    found = ("name_spelling", idx[v], v)
                    break
        if found is None and norm(inn) in molecule_hits:
            found = ("molecule_fallback", set(molecule_hits[norm(inn)]), inn)
        if found is None:
            stats["no_match"] += 1
            continue
        path, code_set, matched = found
        code, how = pick_atc(code_set)
        if code is None:
            stats["ambiguous"] += 1
            if len(ambiguous) < 30:
                ambiguous.append({"substance_id": sub["substance_id"], "inn_en": inn,
                                  "path": path, "codes": sorted(code_set)})
            continue
        stats[f"hit_{path}"] += 1
        hits.append({
            "substance_id": sub["substance_id"], "inn_en": inn,
            "entity_type": sub["entity_type"], "atc": code,
            "atc_name": names.get(code), "path": path, "matched_name": matched,
            "candidates": sorted(code_set), "pick": how,
            "n_products": np_by_sid.get(sub["substance_id"], 0),
        })
    hits.sort(key=lambda h: -h["n_products"])
    return hits, dict(stats), ambiguous


# --- 覆盖率 ----------------------------------------------------------------
def coverage(con: sqlite3.Connection, entity_types: dict[str, str], n_fill: int) -> dict:
    rows = [dict(r) for r in con.execute("SELECT substance_id, atc FROM substance")]
    def cov(sids):
        total = len(sids)
        with_atc = sum(1 for r in rows if r["substance_id"] in sids and (r["atc"] or "").strip())
        return {"total": total, "with_atc_before": with_atc,
                "with_atc_after": with_atc + n_fill,
                "coverage_before": round(100.0 * with_atc / max(1, total), 1),
                "coverage_after": round(100.0 * (with_atc + n_fill) / max(1, total), 1)}
    # 只统计「inn_drug / biologic / food」为分母（entity_type.csv 缺失时退化为全部）
    drug_like = {r["substance_id"] for r in rows
                 if entity_types.get(r["substance_id"], "unknown") in ALLOWED_TYPES}
    return {
        "all": cov({r["substance_id"] for r in rows}),
        "entity_drug_like": cov(drug_like if drug_like else {r["substance_id"] for r in rows}),
        "inn_drug_only": cov({r["substance_id"] for r in rows
                              if entity_types.get(r["substance_id"]) == "inn_drug"}),
    }


# --- 报告 -------------------------------------------------------------------
def write_report(result: dict) -> tuple[Path, Path]:
    EVID.mkdir(parents=True, exist_ok=True)
    js = EVID / "chembl_atc_dryrun.json"
    js.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    s = result["match_stats"]
    c = result["coverage"]
    lines = ["# ChEMBL ATC 补全 dry-run（etl/ingest_chembl_atc.py）",
             "",
             f"生成时间：{result['generated_at']}   数据库：{result['db']}   模式：{result['mode']}",
             f"缓存：{result['cache']['path']}  {result['cache']['rows']:,} 行 / "
             f"{result['cache']['distinct_atc']:,} ATC / {result['cache']['distinct_who_names']:,} WHO 名"
             f"  许可 {result['cache']['license']}",
             "",
             "## 缺口与匹配",
             f"- 成分 {result['gap']['substances_total']:,}，有 ATC {result['gap']['with_atc']:,}，"
             f"缺 {result['gap']['missing_atc']:,}；其中药物实体候选 "
             f"{result['gap']['missing_drug_like']:,}（inn_drug/biologic/food）",
             ]
    for k in ("name_exact", "name_paren", "name_base", "name_alias",
              "name_spelling", "molecule_fallback"):
        lines.append(f"- 命中 {k}: {s.get('hit_' + k, 0):,}")
    lines += [f"- 歧义跳过: {s.get('ambiguous', 0):,}",
              f"- 未匹配: {s.get('no_match', 0):,}",
              "",
              f"## 可补 **{result['totals']['fills']:,}** 个成分",
              "",
              "| 分母口径 | 补前 | 补后 |",
              "|---|---:|---:|",
              f"| 全部 substance | {c['all']['with_atc_before']:,}/{c['all']['total']:,}"
              f" = {c['all']['coverage_before']}% | {c['all']['with_atc_after']:,}/{c['all']['total']:,}"
              f" = {c['all']['coverage_after']}% |",
              f"| 药物实体（inn_drug+biologic+food） | {c['entity_drug_like']['with_atc_before']:,}/"
              f"{c['entity_drug_like']['total']:,} = {c['entity_drug_like']['coverage_before']}% | "
              f"{c['entity_drug_like']['with_atc_after']:,}/{c['entity_drug_like']['total']:,}"
              f" = {c['entity_drug_like']['coverage_after']}% |",
              f"| inn_drug only | {c['inn_drug_only']['with_atc_before']:,}/"
              f"{c['inn_drug_only']['total']:,} = {c['inn_drug_only']['coverage_before']}% | "
              f"{c['inn_drug_only']['with_atc_after']:,}/{c['inn_drug_only']['total']:,}"
              f" = {c['inn_drug_only']['coverage_after']}% |",
              "",
              "## 抽样 20 条（按产品数降序）",
              "",
              "| # | substance_id | inn_en | 类型 | 路径 | ATC | atc_name | 产品 |",
              "|---:|---|---|---|---|---|---|---:|"]
    for i, h in enumerate(result["samples"], 1):
        lines.append(f"| {i} | {h['substance_id']} | {h['inn_en'][:34]} | {h['entity_type']} | "
                     f"{h['path']} | {h['atc']} | {h['atc_name'] or ''} | {h['n_products']} |")
    lines += ["", "## 歧义样例（不写）"]
    for a in result["ambiguous"][:15]:
        lines.append(f"- {a['substance_id']} {a['inn_en'][:40]} → {', '.join(a['codes'])}（{a['path']}）")
    txt = EVID / "chembl_atc_dryrun.txt"
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return js, txt


# --- apply / rollback -------------------------------------------------------
def apply_hits(db: sqlite3.Connection, hits: list[dict], cache_meta: dict,
               match_stats: dict) -> dict:
    written = Counter()
    applied: list[dict] = []
    try:
        db.execute(
            "INSERT OR REPLACE INTO source (source_id, name, url, license, license_url,"
            " retrieved_at, notes) VALUES (?,?,?,?,?,?,?)",
            (SOURCE_ID, "ChEMBL — ATC classification (EMBL-EBI)",
             "https://www.ebi.ac.uk/chembl/api/data/atc_class.json",
             "CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/", TODAY,
             "只取 ATC 码与 WHO INN 名做对齐；不复制 WHOCC 的 ATC/DDD 文本。"
             "衍生映射按 CC BY-SA 4.0 署名并以相同方式共享。"))
        for h in hits:
            cur = db.execute(
                "UPDATE substance SET atc=?, atc_name=COALESCE(NULLIF(atc_name,''), ?)"
                " WHERE substance_id=? AND (atc IS NULL OR atc='')",
                (h["atc"], h["atc_name"], h["substance_id"]))
            if cur.rowcount == 1:
                written["substances"] += 1
                written[f"type_{h['entity_type']}"] += 1
                applied.append({"substance_id": h["substance_id"], "atc": h["atc"],
                                "atc_name": h["atc_name"], "entity_type": h["entity_type"]})
            else:
                written["skip_race"] += 1
        note = json.dumps({"fills": len(hits), "written": dict(written),
                           "match_stats": match_stats,
                           "cache_retrieved_at": cache_meta.get("retrieved_at")},
                          ensure_ascii=False)
        db.execute(
            "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
            " rows_in, rows_kept, rows_rejected, status, note) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"{SOURCE_ID}-{TODAY}", SOURCE_ID, TODAY, TODAY,
             cache_meta.get("rows", 0), written["substances"], 0, "ok", note))
        db.commit()
        APPLIED.parent.mkdir(parents=True, exist_ok=True)
        # 幂等重跑写入 0 时，不要清空上一轮的 apply 清单（否则 rollback 无从定位）
        prev: list[dict] = []
        if APPLIED.exists():
            try:
                prev = json.loads(APPLIED.read_text(encoding="utf-8")).get("entries") or []
            except json.JSONDecodeError:
                prev = []
        merged = {e["substance_id"]: e for e in prev + applied}
        APPLIED.write_text(json.dumps(
            {"applied_at": TODAY, "source_id": SOURCE_ID, "count": len(merged),
             "entries": list(merged.values())}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        db.rollback()
        raise
    return dict(written)


def rollback(db: sqlite3.Connection) -> dict:
    out = Counter()
    if not APPLIED.exists():
        raise SystemExit(f"找不到 {APPLIED.relative_to(ROOT)}：拒绝回滚（避免误伤库里原有 ATC）。")
    payload = json.loads(APPLIED.read_text(encoding="utf-8"))
    entries = payload.get("entries") or []
    try:
        for e in entries:
            cur = db.execute(
                "UPDATE substance SET atc=NULL, atc_name=CASE WHEN atc_name=? THEN NULL ELSE atc_name END"
                " WHERE substance_id=? AND atc=?", (e.get("atc_name"), e["substance_id"], e["atc"]))
            if cur.rowcount == 1:
                out["substances"] += 1
        db.execute("DELETE FROM ingest_run WHERE run_id=?", (f"{SOURCE_ID}-{TODAY}",))
        db.commit()
        APPLIED.write_text(json.dumps(
            {"applied_at": payload.get("applied_at"), "source_id": SOURCE_ID,
             "count": 0, "entries": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        db.rollback()
        raise
    out["listed"] = len(entries)
    return dict(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="ChEMBL ATC → substance.atc（默认 dry-run）")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--sample", type=int, default=20)
    ap.add_argument("--molecule-check", type=int, default=0,
                    help="对前 N 个未命中的高产品数成分再查 molecule 端点（默认 0）")
    ap.add_argument("--types", default=",".join(sorted(ALLOWED_TYPES)),
                    help="允许回填的 entity_type 列表（逗号分隔）")
    ap.add_argument("--allow-real-db", action="store_true",
                    help="Lead 复核后显式允许写 data/drugs.db（默认拒绝）")
    args = ap.parse_args()
    if sum([args.apply, args.dry_run, args.rollback]) > 1:
        ap.error("--apply / --dry-run / --rollback 互斥")
    allowed = {x.strip() for x in args.types.split(",") if x.strip()}

    # 写入真实库的保护：默认只允许副本；Lead 复核后加 --allow-real-db
    real = (ROOT / "data" / "drugs.db").resolve()
    if (args.apply or args.rollback) and args.db.resolve() == real and not args.allow_real_db:
        raise SystemExit("拒绝写 data/drugs.db：请先 dry-run 复核，确需写真实库时加 "
                         "--allow-real-db（并先备份）")

    cache_meta, rows = load_cache()
    idx, atc_names = build_index(rows)
    entity_types = load_entity_types()
    con = connect(args.db, readonly=not (args.apply or args.rollback))
    candidates, gap = load_candidates(con, entity_types, allowed)
    np_by_sid = {r["substance_id"]: r["n_products"] for r in
                 con.execute("""SELECT s.substance_id, COUNT(DISTINCT pc.product_id) n_products
                                FROM substance s
                                JOIN variant v ON v.substance_id=s.substance_id
                                JOIN product_component pc ON pc.variant_id=v.variant_id
                                GROUP BY s.substance_id""")}

    # 先跑一遍不含 molecule 的匹配，再用未命中的高价值成分查 molecule
    molecule_hits: dict[str, list[str]] = {}
    if args.molecule_check > 0:
        first_hits, _, _ = match(candidates, idx, atc_names, {}, np_by_sid)
        matched = {h["substance_id"] for h in first_hits}
        unmatched = [c for c in candidates if c["substance_id"] not in matched]
        unmatched.sort(key=lambda c: -np_by_sid.get(c["substance_id"], 0))
        todo = [c["inn_en"] for c in unmatched[: args.molecule_check] if c["inn_en"]]
        print(f"molecule 端点查漏：{len(todo)} 个高产品数未命中成分 ...")
        raw_hits = molecule_lookup(todo)
        for name, codes in raw_hits.items():
            if codes:
                molecule_hits[norm(name)] = codes
        print(f"molecule 端点命中 {len(molecule_hits)} / {len(todo)}")

    hits, match_stats, ambiguous = match(candidates, idx, atc_names, molecule_hits, np_by_sid)
    if args.rollback:
        out = rollback(con)
        print(f"已回滚：{out.get('substances', 0):,} 个成分（清单 {out.get('listed', 0):,} 条）")
        con.close()
        return 0

    cover = coverage(con, entity_types, len(hits))
    result = {
        "generated_at": TODAY, "db": str(args.db), "mode": "apply" if args.apply else "dry-run",
        "cache": {"path": str(CACHE.relative_to(ROOT)),
                  "rows": cache_meta.get("rows", len(rows)),
                  "distinct_atc": cache_meta.get("distinct_level5"),
                  "distinct_who_names": cache_meta.get("distinct_who_names"),
                  "license": cache_meta.get("license"),
                  "retrieved_at": cache_meta.get("retrieved_at")},
        "gap": gap, "match_stats": match_stats, "coverage": cover,
        "totals": {"fills": len(hits)},
        "samples": hits[: args.sample], "all_hits": hits, "ambiguous": ambiguous,
        "entity_types": {"file": str(ENTITY.relative_to(ROOT)) if ENTITY.exists() else None,
                         "allowed": sorted(allowed)},
    }
    print("=== ChEMBL ATC 补全 [%s] ===" % result["mode"])
    print(f"缓存：{result['cache']['rows']:,} 行 / {result['cache']['distinct_atc']:,} ATC / "
          f"{result['cache']['distinct_who_names']:,} WHO 名  [{result['cache']['license']}]")
    print(f"成分 {gap['substances_total']:,}，有 ATC {gap['with_atc']:,}，缺 {gap['missing_atc']:,}；"
          f"药物实体候选 {gap['missing_drug_like']:,}")
    for k, v in match_stats.items():
        print(f"  {k:<18}{v:>7,}")
    print(f"可补 {len(hits):,} 个成分")
    for label, c in cover.items():
        print(f"  {label:<18}{c['with_atc_before']:,}/{c['total']:,} = {c['coverage_before']}%"
              f"  →  {c['with_atc_after']:,} = {c['coverage_after']}%")
    print(f"抽样 {args.sample} 条：")
    for h in hits[: args.sample]:
        print(f"  {h['substance_id']:<34} {h['inn_en'][:32]:<34} {h['atc']:<8} "
              f"{h['atc_name'] or '':<26} [{h['entity_type']}/{h['path']}] np={h['n_products']}")

    if args.apply:
        written = apply_hits(con, hits, cache_meta, match_stats)
        print(f"已写库：{written.get('substances', 0):,} 个成分（事务提交）")
    else:
        js, txt = write_report(result)
        print(f"dry-run 报告：{js.relative_to(ROOT)}  {txt.relative_to(ROOT)}")
        print("（未写库；正式执行用 --apply --db <副本>）")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
