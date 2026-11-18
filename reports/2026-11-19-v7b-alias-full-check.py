#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V7b 全量验证：`data/aliases.json` 1,438 条别名 → 成分 Top-1（服务端 + 客户端）。

口径（2026-11-18 Lead 定）
--------------------------
- 1,438 = `alias_all`（nickname 396 + drug_term 1,017 = 1,413）+ `data/substance_aliases.csv`
  同物异名 25（site/build.py `building nickname index` 的同一份口径）；
- 有效分母 = **有 substance 的 1,404 条**；34 条类别词/无成分（substance_id 为空）
  落不到成分页，单列、不算漏；
- 「Top-1 落到该成分页」：
  * nickname / drug_term：搜索结果的**首张别名卡**（服务端 `res.alias`）指向的 substance
    必须等于该行指向的成分，且首张结果卡的成分集合包含它（有在售产品时）；
  * substance_alias（CSV）：别名卡指向 canonical 成分（服务端由 `lib/aliases.py` 的
    异名并查集给出同一答案；客户端由 aliases.json 的 `v` 字段直接给出）；
- 多成分别名（同一叫法指向 2 个成分，如「P药」「美白丸」）：Top-1 只能落一个，
  另一条必须在候选集里（Top-3 别名卡 / `res.aliases`），按「候选命中」记，不算漏；
- 「两端同一口径」：逐条比对服务端与客户端的 resolved substance（1,404 行 CSV）。

客户端怎么跑
------------
- 不构建站点、不写 `site/dist`；用 `site/build.py::load_aliases()` +
  `load_substance_aliases()` 现算与构建产物同构的 aliases.json（只读 DB/CSV）；
- 从 `site/build.py` 的 APP_JS 源码里**原样抽取** `toSimp / norm / _flatAccents /
  aliasHits`（有 `aliasKey` 时一并抽取），在 Node 里对 1,438 条别名逐条跑
  `aliasHits(norm(alias))`，取首张有 `v` 的别名卡作为客户端结论；
- Node 不可用或抽取失败时退回 Python 复刻（报告里注明「模拟」）。

只读
----
sqlite3 一律 URI `mode=ro`；不写库、不改数据、不构建站点。

用法
----
    & $py reports/2026-11-19-v7b-alias-full-check.py --side both
    & $py reports/2026-11-19-v7b-alias-full-check.py --side server --csv .tmp/v7b-server.csv
    & $py reports/2026-11-19-v7b-alias-full-check.py --side client --client-mode python
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "drugs.db"
ALIAS_CSV = ROOT / "data" / "substance_aliases.csv"
TMP = ROOT / ".tmp" / "v7b"
NODE_CANDIDATES = (
    ROOT / "tools" / "node" / "node.exe",
    Path(r"C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"),
)

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "lib"))

_REAL_CONNECT = sqlite3.connect


def ro_connect(database, *args, **kwargs):
    s = str(database)
    if "mode=ro" not in s:
        return _REAL_CONNECT("file:" + s + "?mode=ro", uri=True, *args, **kwargs)
    return _REAL_CONNECT(database, *args, **kwargs)


def _load_build_module(src: Path | None = None):
    """以文件路径载入 site/build.py（模块名不能叫 site，stdlib 冲突）。"""
    path = src or (ROOT / "site" / "build.py")
    spec = importlib.util.spec_from_file_location("v7b_build", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def load_alias_rows(db: sqlite3.Connection) -> list[dict]:
    """按 site/build.py 的同一口径列出 1,438 条别名行（只读）。"""
    inn = {r[0]: (r[1] or "") for r in db.execute(
        "SELECT substance_id, inn_en FROM substance")}
    rows: list[dict] = []
    for r in db.execute(
            """SELECT a.alias_id, a.origin, a.substance_id, a.alias, a.alias_norm,
                      a.kind, a.label_zh, a.label_en, s.inn_en
               FROM alias_all a LEFT JOIN substance s ON s.substance_id = a.substance_id
               ORDER BY a.alias_id"""):
        rows.append({
            "key": f'{r["origin"]}:{r["alias_id"]}', "origin": r["origin"],
            "id": r["alias_id"], "sid": r["substance_id"], "alias": r["alias"],
            "stored_norm": r["alias_norm"], "kind": r["kind"],
            "label": r["label_zh"] or r["label_en"] or r["inn_en"] or r["alias"],
            "inn": r["inn_en"] or "", "csv_alias_id": "",
        })
    # CSV 同物异名：与 build.load_substance_aliases 同口径（去重 + 规范成分必须有产品页）
    page_sids = {r[0] for r in db.execute(
        """SELECT DISTINCT v.substance_id FROM product p
           JOIN product_component pc ON pc.product_id=p.product_id
           JOIN variant v ON v.variant_id=pc.variant_id""")}
    seen: set[str] = set()
    with ALIAS_CSV.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            csid = (row.get("canonical_id") or "").strip()
            asid = (row.get("alias_id") or "").strip()
            if not csid or not asid or csid == asid:
                continue
            cname = inn.get(csid) or (row.get("canonical_inn") or "").strip()
            aname = inn.get(asid) or (row.get("alias_inn") or "").strip()
            if not cname or not aname:
                continue
            from search import alias_key  # noqa: PLC0415
            norm = alias_key(aname)
            if csid not in page_sids or not norm or norm in seen:
                continue
            seen.add(norm)
            rows.append({
                "key": f"csv:{asid}", "origin": "substance_alias", "id": asid,
                "sid": csid, "alias": aname, "stored_norm": norm,
                "kind": "synonym", "label": cname, "inn": cname,
                "csv_alias_id": asid,
            })
    return rows


# --- 服务端：lib/search.py ----------------------------------------------------
def server_check(rows: list[dict]) -> dict[str, dict]:
    """每条唯一别名跑一次 SearchIndex.search()，返回 {alias: 结论}。"""
    import search as search_mod  # noqa: PLC0415

    sqlite3.connect = ro_connect
    idx = search_mod.SearchIndex(DB)
    # CSV 同物异名：服务端异名层（lib/aliases.py 并查集）给出的规范成分
    csv_canonical: dict[str, str] = {}
    for r in rows:
        if r["origin"] == "substance_alias" and r.get("csv_alias_id"):
            csv_canonical[r["alias"]] = idx.alias.canonical(r["csv_alias_id"])
    out: dict[str, dict] = {}
    for alias in dict.fromkeys(r["alias"] for r in rows):
        res = idx.search(alias, limit=25)
        alias_sids = {a.get("substance_id") for a in (res.aliases or [])}
        top1_subs = list(res.cards[0].substances) if res.cards else []
        all_subs = {s for c in res.cards for s in c.substances}
        meta = res.match_detail.get("inn_alias") or {}
        out[alias] = {
            "cards": len(res.cards),
            "alias_sids": sorted(s for s in alias_sids if s),
            "resolved": (res.alias or {}).get("substance_id") or "",
            "top1_subs": top1_subs,
            "all_subs": sorted(all_subs),
            "match_source": res.match_source,
            "inn_alias_targets": list(meta.get("targets") or []),
            "inn_alias_shown": meta.get("shown") or 0,
            "note": res.note,
            "csv_resolved": csv_canonical.get(alias, ""),
        }
    idx.close()
    return out


def server_row_conclusion(row: dict, srv: dict) -> tuple[str, bool, bool]:
    """(resolved_sid, target_in_candidates, target_in_top1)。"""
    alias = row["alias"]
    s = srv.get(alias) or {}
    target = row["sid"] or ""
    if row["origin"] == "substance_alias":
        # CSV 同物异名：服务端异名层的规范成分（lib/aliases.py 并查集）。
        # 这里的「Top-1」是别名卡指向（规范成分页），不是商品结果卡的首张——
        # 异名层按 task-141b 只追加、不替换按名字命中的主结果。
        resolved = s.get("csv_resolved") or ""
        return resolved, resolved == target, resolved == target
    resolved = s.get("resolved") or ""
    # 候选命中：目标在别名卡候选集里，或目标成分出现在结果卡里
    target_in = (target in s.get("alias_sids", [])) or (
        row["inn"] in s.get("all_subs", []))
    top1 = row["inn"] in s.get("top1_subs", [])
    return resolved, target_in, top1


# --- 客户端：构建产物 aliases.json + 页内 app.js 函数 -------------------------
def build_client_aliases(src: Path | None = None) -> list[dict]:
    """用 site/build.py 的两个函数现算 aliases.json（与构建产物同构，不写 dist）。"""
    B = _load_build_module(src)
    sqlite3.connect = ro_connect
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    aliases = B.load_aliases(db)
    _also, hits = B.load_substance_aliases(db)
    db.close()
    return aliases + hits


def _extract_js_fn(src: str, name: str) -> str | None:
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\(", src)
    if not m:
        return None
    start = src.rfind("\n", 0, m.start()) + 1
    brace = src.find("{", m.end())
    if brace < 0:
        return None
    depth = 0
    for i in range(brace, len(src)):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1].strip()
    return None


def _node_path() -> Path | None:
    import shutil  # noqa: PLC0415
    for p in NODE_CANDIDATES:
        if p.exists():
            return p
    found = shutil.which("node")
    return Path(found) if found else None


# 计划中的页内实现（BUILD-FREE 前用 --client-mode sim 预演；落地后以 build.py 抽取为准）
SIM_JS = r"""
function aliasKey(s){
  return toSimp(s||'').normalize('NFKC').toLowerCase()
    .replace(/[®™©]/g,' ')
    .replace(/[\u0300-\u036f]/g,'')
    .replace(/[\-–—_\/\\.,;:!?()\[\]{}'"’‘“”·•*&+]+/g,' ')
    .replace(/\s+/g,' ').trim();
}
function aliasHits(nq){
  const qk = aliasKey(nq);
  const fq = _flatAccents(qk);
  return NICKS.filter(function(a){
    const ak = aliasKey(a.n);
    return ak === qk || ak.replace(/ /g,'') === qk.replace(/ /g,'')
      || _flatAccents(ak).replace(/ /g,'') === fq.replace(/ /g,'');
  });
}
"""


def client_check(aliases: list[dict], queries: list[str],
                 mode: str = "auto", build_src: Path | None = None,
                 ) -> tuple[list[list[str]], str, int]:
    """返回 (每条查询匹配到的别名卡 v 列表, 实际使用的方式, JS/Python 键不一致数)。"""
    node = _node_path()
    src = (build_src or (ROOT / "site" / "build.py")).read_text(encoding="utf-8")
    fns = {name: _extract_js_fn(src, name)
           for name in ("toSimp", "norm", "_flatAccents", "aliasHits", "aliasKey")}
    sim = mode == "sim"
    use_node = mode in ("auto", "node", "sim") and node is not None and all(
        fns[k] for k in ("toSimp", "norm", "_flatAccents")) and (
            sim or fns["aliasHits"])
    if use_node:
        t2s = json.loads(
            (ROOT / "data" / "zh_hant_t2s.json").read_text(encoding="utf-8"))["map"]
        if sim:
            fn_src = "\n".join(
                fns[k] for k in ("toSimp", "norm", "_flatAccents")) + SIM_JS
        else:
            fn_src = "\n".join(
                fns[k] for k in ("toSimp", "norm", "_flatAccents", "aliasKey",
                                 "aliasHits") if fns[k])
        harness = "\n".join([
            "const T2S = " + json.dumps(t2s, ensure_ascii=False) + ";",
            fn_src,
            "const NICKS = " + json.dumps(aliases, ensure_ascii=False) + ";",
            "const QS = " + json.dumps(queries, ensure_ascii=False) + ";",
            "const out = {hits: QS.map(q => aliasHits(norm(q)).map(a => a.v || '')),",
            "             keys: QS.map(q => (typeof aliasKey === 'function')",
            "               ? aliasKey(norm(q)) : norm(q))};",
            "process.stdout.write(JSON.stringify(out));",
        ])
        TMP.mkdir(parents=True, exist_ok=True)
        js = TMP / "client_harness.js"
        js.write_text(harness, encoding="utf-8")
        try:
            proc = subprocess.run(
                [str(node), str(js)], capture_output=True, text=True,
                encoding="utf-8", timeout=300)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr[-500:])
            payload = json.loads(proc.stdout)
            hits = payload["hits"]
            from search import alias_key  # noqa: PLC0415
            py_keys = [alias_key(q) for q in queries]
            key_mismatch = sum(1 for a, b in zip(payload["keys"], py_keys) if a != b)
            if key_mismatch:
                bad = [(q, a, b) for q, a, b in zip(queries, payload["keys"], py_keys)
                       if a != b][:5]
                print(f"[warn] JS aliasKey 与 Python alias_key 不一致 "
                      f"{key_mismatch} 条，样例：{bad}", file=sys.stderr)
            return hits, f"node:{node.name}", key_mismatch
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"[warn] Node 客户端跑失败，退回 Python 模拟：{exc}", file=sys.stderr)
            if mode == "node":
                raise
    # Python 复刻：查询侧与构建产物 `n` 用同一 alias_key（旧产物 n 未重算时也照旧跑）
    import unicodedata  # noqa: PLC0415
    from search import alias_key  # noqa: PLC0415

    def _flat(s: str) -> str:
        return "".join(ch for ch in unicodedata.normalize("NFKD", s or "")
                       if not unicodedata.combining(ch))

    out: list[list[str]] = []
    for q in queries:
        nq = alias_key(q)
        hits: list[str] = []
        for a in aliases:
            stored = a.get("n") or ""
            if not stored:
                continue
            if (stored == nq
                    or stored.replace(" ", "") == nq.replace(" ", "")
                    or _flat(stored).replace(" ", "") == _flat(nq).replace(" ", "")):
                hits.append(a.get("v") or "")
        out.append(hits)
    return out, "python-sim", 0


def client_row_conclusion(row: dict,
                          matched: dict[str, list[str]]) -> tuple[str, str, bool]:
    """(首张别名卡 v, 首张有成分的别名卡 v, 目标是否在别名卡候选里)。"""
    matches = matched.get(row["alias"], [])
    first_card = matches[0] if matches else ""
    first_mapped = next((v for v in matches if v), "")
    return first_card, first_mapped, (row["sid"] or "") in [v for v in matches if v]


# --- 主流程 -------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=("server", "client", "both"), default="both")
    ap.add_argument("--client-mode", choices=("auto", "node", "python", "sim"),
                    default="auto")
    ap.add_argument("--csv", default=str(TMP / "v7b_alias_full_check.csv"))
    ap.add_argument("--json", default=str(TMP / "v7b_alias_full_check.json"))
    ap.add_argument("--build-src", default="",
                    help="可选：用另一份 build.py（如 .tmp 预演副本）生成客户端索引/JS")
    args = ap.parse_args()
    build_src = Path(args.build_src) if args.build_src else None

    sqlite3.connect = ro_connect
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    rows = load_alias_rows(db)
    db.close()
    print(f"aliases.json 口径：{len(rows)} 条"
          f"（有成分 {sum(1 for r in rows if r['sid'])} / 无成分 "
          f"{sum(1 for r in rows if not r['sid'])}）")

    srv = server_check(rows) if args.side in ("server", "both") else {}
    aliases: list[dict] = []
    client_matched: dict[str, list[str]] = {}
    client_how = ""
    key_mismatch = 0
    if args.side in ("client", "both"):
        aliases = build_client_aliases(build_src)
        print(f"客户端 aliases.json：{len(aliases)} 条"
              f"（构建期 `n` 已重算：{sum(1 for a in aliases if a.get('n'))} 条）")
        queries = list(dict.fromkeys(r["alias"] for r in rows))
        got, client_how, key_mismatch = client_check(
            aliases, queries, args.client_mode, build_src)
        client_matched = dict(zip(queries, got))
        print(f"客户端匹配方式：{client_how}；JS/Python 匹配键不一致：{key_mismatch} 条")

    out_rows = []
    stats = Counter()
    agree = 0
    eff = 0
    for row in rows:
        if not row["sid"]:
            stats["unmapped"] += 1
            continue
        eff += 1
        resolved, target_in_candidates, target_in_top1 = server_row_conclusion(
            row, srv)
        crow = {
            "origin": row["origin"], "alias": row["alias"], "kind": row["kind"],
            "target_sid": row["sid"], "target_inn": row["inn"],
            "server_resolved": resolved,
            "server_target_in_candidates": target_in_candidates,
            "server_target_in_top1": target_in_top1,
        }
        if args.side in ("client", "both"):
            c_first, c_mapped, c_in = client_row_conclusion(row, client_matched)
            crow.update(client_first_card=c_first, client_first_mapped=c_mapped,
                        client_target_in_cards=c_in)
            crow["agreed_top1"] = bool(resolved) and resolved == c_first
            crow["agreed_mapped"] = bool(resolved) and resolved == c_mapped
            agree += 1 if crow["agreed_top1"] else 0
        out_rows.append(crow)
        # 服务端漏：目标不在候选（多成分别名允许 Top-1 只落一个）
        if not target_in_candidates:
            stats["server_miss"] += 1
        elif not target_in_top1:
            stats["server_candidate_only"] += 1
        if not resolved:
            stats["server_unresolved"] += 1
        if args.side in ("client", "both"):
            if not crow["client_first_mapped"]:
                stats["client_unresolved"] += 1
            elif not crow["client_target_in_cards"]:
                stats["client_miss"] += 1
            if crow["client_first_card"] != (row["sid"] or ""):
                stats["client_top1_strict_miss"] += 1
            if c_mapped != (row["sid"] or ""):
                stats["client_mapped_strict_miss"] += 1

    # 演示两条（Lead 指定）：猛健樂 / 替西帕肽
    demo = {}
    for q in ("猛健樂", "替西帕肽"):
        r = next((x for x in rows if x["alias"] == q), None)
        s = srv.get(q, {})
        c_first = ""
        if client_matched:
            c_first = next((v for v in client_matched.get(q, []) if v), "")
        demo[q] = {
            "target_sid": (r or {}).get("sid", ""),
            "server_resolved": s.get("resolved", ""),
            "server_top1_subs": s.get("top1_subs", []),
            "client_first_card": c_first,
        }

    summary = {
        "total": len(rows),
        "effective": eff,
        "unmapped": stats["unmapped"],
        "server_unresolved": stats["server_unresolved"],
        "server_miss": stats["server_miss"],
        "server_candidate_only_ambiguous": stats["server_candidate_only"],
        "client_unresolved": stats["client_unresolved"],
        "client_miss": stats["client_miss"],
        "client_top1_strict_miss": stats["client_top1_strict_miss"],
        "client_mapped_strict_miss": stats["client_mapped_strict_miss"],
        "agreed_top1": agree if args.side in ("client", "both") else None,
        "agreed_top1_pct": (round(100.0 * agree / eff, 1) if eff else 0)
                            if args.side in ("client", "both") else None,
        "client_how": client_how,
        "client_key_mismatch": key_mismatch if args.side in ("client", "both") else None,
        "demo": demo,
    }
    Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
    with open(args.csv, "w", encoding="utf-8-sig", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()) if out_rows else [])
        wr.writeheader()
        wr.writerows(out_rows)
    Path(args.json).write_text(
        json.dumps({"summary": summary, "rows": out_rows},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("CSV:", args.csv)
    print("JSON:", args.json)
    # 判定：漏 0（服务端/客户端）；两端 Top-1 substance 一致 1,404/1,404
    ok = (summary["server_miss"] == 0 and summary["server_unresolved"] == 0)
    if args.side in ("client", "both"):
        ok = ok and summary["client_miss"] == 0 and summary["client_unresolved"] == 0
        ok = ok and summary["agreed_top1"] == eff
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
