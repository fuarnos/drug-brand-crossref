"""R5 验收：把成分页「未公开规格」块上的数字跟 SQL 现查逐条对照。

用法（先跑探针渲染页面到 .tmp/r5-after20）：

    $py reports/2026-11-17-r5-undisclosed-probe.py .tmp/r5-after20 <sid...>
    $py reports/2026-11-17-r5-verify.py .tmp/r5-after20 <sid...>

口径（与 site/build.py 完全一致，不另立标准）：
  - 记录数：该市场**可见**记录（status='active'，或 status 空/unknown 且市场属 HK/AU/EU）
    里 `product_component.strength_value IS NULL`（= 页面「未公开规格」）的 distinct product_id；
  - 厂家数：上述记录里 `TRIM(COALESCE(product.mah,'')) <> ''` 的 distinct 原值；
  - 名字 ×N：未公开规格记录里「同一 name_key 的 distinct product_id」；
    「无商品名」桶 = 无 trade 名且无厂家的记录数；页面最多列 8 个名字 / 8 个厂家
    （超出打 cap：只比记录数与厂家数，multiset 不比）；
  - 块头：整块没有结构化规格时必须用 drug.spec_count_und，且 data-und = 记录数。
"""
from __future__ import annotations

import io
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VISIBLE = ("AND (p.status = 'active' OR (COALESCE(p.status, '') IN ('', 'unknown') "
           "AND COALESCE(p.country, p.region) IN ('HK', 'AU', 'EU')))")

WITH_U = """
WITH u AS (
  SELECT COALESCE(p.country, p.region) AS mk, p.product_id AS pid, p.mah AS mah,
         pc.strength_value AS sv
  FROM product p
  JOIN product_component pc ON pc.product_id = p.product_id
  JOIN variant v ON v.variant_id = pc.variant_id
  JOIN substance s ON s.substance_id = v.substance_id
  WHERE s.substance_id = ? {visible}
), und AS (SELECT DISTINCT pid, mk, mah FROM u WHERE sv IS NULL)
"""

REC_SQL = WITH_U + "SELECT mk, COUNT(DISTINCT pid) FROM und GROUP BY mk"
MAH_SQL = WITH_U + ("SELECT COUNT(DISTINCT mah) FROM und "
                    "WHERE mk = ? AND TRIM(COALESCE(mah, '')) <> ''")
NAME_SQL = WITH_U + (
    "SELECT pn.key_id, COUNT(DISTINCT pn.product_id) "
    "FROM und JOIN product_name pn ON pn.product_id = und.pid AND pn.name_type = 'trade' "
    "WHERE und.mk = ? GROUP BY pn.key_id ORDER BY pn.key_id")
MAH_BUCKET_SQL = WITH_U + (
    "SELECT TRIM(mah), COUNT(DISTINCT pid) FROM und "
    "WHERE mk = ? AND TRIM(COALESCE(mah, '')) <> '' "
    "AND NOT EXISTS (SELECT 1 FROM product_name pn "
    "                WHERE pn.product_id = und.pid AND pn.name_type = 'trade') "
    "GROUP BY TRIM(mah)")
NO_TRADE_SQL = WITH_U + (
    "SELECT COUNT(*) FROM und WHERE mk = ? AND TRIM(COALESCE(mah, '')) = '' "
    "AND NOT EXISTS (SELECT 1 FROM product_name pn "
    "                WHERE pn.product_id = und.pid AND pn.name_type = 'trade')")

CAP = 8          # 页面最多列 8 个名字 / 8 个厂家


def _q(db, sql: str, *args):
    return db.execute(sql.replace("{visible}", VISIBLE), args).fetchall()


def _attr(tag: str, name: str) -> str:
    m = re.search(name + r'="([^"]*)"', tag)
    return m.group(1) if m else ""


def block_facts(html: str) -> list[dict]:
    """从成分页 HTML 抽每个市场块的计数事实。"""
    out: list[dict] = []
    for m in re.finditer(r'<details class="mkblock".*?</details>', html, re.S):
        seg = m.group(0)
        mk = re.search(r'data-mk="([A-Z]+)"', seg)
        spec_tag = re.search(r'<span class="mkspec"[^>]*>', seg)
        spec = re.search(r'<span class="mkspec"[^>]*>(.*?)</span>', seg, re.S)
        und = re.search(r'<details class="undis">(.*?)</details>', seg, re.S)
        row = {"mk": mk.group(1) if mk else "?", "spec": "", "und_rec": None,
               "und_mah": None, "chips": [], "und_html": bool(und), "tpl": "",
               "data_und": ""}
        if spec:
            row["spec"] = " ".join(re.sub(r"<[^>]+>", " ", spec.group(1)).split())
        if spec_tag:
            row["tpl"] = _attr(spec_tag.group(0), "data-i18n-tpl")
            row["data_und"] = _attr(spec_tag.group(0), "data-und")
        if und:
            body = und.group(1)
            summ = re.search(r'<summary><span class="ln">(.*?)</span></summary>', body, re.S)
            txt = " ".join(re.sub(r"<[^>]+>", " ", summ.group(1)).split()) if summ else ""
            n1 = re.search(r"(\d[\d,]*)\s*(?:records|registros|个记录|個記錄)", txt)
            row["und_rec"] = int(n1.group(1).replace(",", "")) if n1 else None
            n2 = re.search(r"·\s*(\d[\d,]*)\s*(?:manufacturers|fabricantes|个厂家|個廠商)", txt)
            row["und_mah"] = int(n2.group(1)) if n2 else None
            # chip 计数：×N 的取 N，其余算 1（不解析标签文本，避免嵌套 span）
            total = len(re.findall(r'<span class="uname">', body))
            counted = [int(x) for x in re.findall(r'<span class="x">×(\d+)</span>', body)]
            row["chips"] = counted + [1] * (total - len(counted))
        out.append(row)
    return out


def main() -> int:
    out = ROOT / (sys.argv[1] if len(sys.argv) > 1 else ".tmp/r5-after20")
    sids = [s for s in sys.argv[2:]]
    if not sids:
        print("需要 substance_id 列表")
        return 2
    db = sqlite3.connect(f"file:{ROOT / 'data' / 'drugs.db'}?mode=ro", uri=True)
    rows: list[dict] = []
    bad: list[str] = []
    for sid in sids:
        path = out / "drug" / f"{sid}.html"
        if not path.exists():
            bad.append(f"缺页 {sid}")
            continue
        html = io.open(path, encoding="utf-8").read()
        if re.search(r"\{(?:shown|n|u)\}", html):
            bad.append(f"{sid}: 页面残留模板占位符")
        if "0 shown of 0" in html:
            bad.append(f"{sid}: 仍有「0 shown of 0」")
        sql_rec = {mk: n for mk, n in _q(db, REC_SQL, sid)}
        for b in block_facts(html):
            if not b["und_html"]:
                continue
            mk = b["mk"]
            s_rec = sql_rec.get(mk)
            s_mah = _q(db, MAH_SQL, sid, mk)[0][0]
            name_counts = [n for _k, n in _q(db, NAME_SQL, sid, mk)]
            mah_bucket = [n for _l, n in _q(db, MAH_BUCKET_SQL, sid, mk)]
            n_notrade = _q(db, NO_TRADE_SQL, sid, mk)[0][0]
            name_group = name_counts + ([n_notrade] if n_notrade else [])
            sql_counts = name_group or mah_bucket
            capped = len(sql_counts) > CAP
            name_ok = "cap" if capped else (
                "ok" if Counter(b["chips"]) == Counter(sql_counts) else "DIFF")
            rec_ok = (b["und_rec"] == s_rec)
            mah_ok = (b["und_mah"] == s_mah)
            und_only = b["spec"].startswith("0 shown")
            rows.append({"sid": sid, "mk": mk, "rec_page": b["und_rec"], "rec_sql": s_rec,
                         "mah_page": b["und_mah"], "mah_sql": s_mah,
                         "names": name_ok, "n_chips": len(b["chips"]),
                         "tpl": b["tpl"], "data_und": b["data_und"], "spec": b["spec"],
                         "und_only": und_only})
            if not rec_ok:
                bad.append(f"{sid}/{mk}: 记录数 页面 {b['und_rec']} ≠ SQL {s_rec}")
            if not mah_ok:
                bad.append(f"{sid}/{mk}: 厂家数 页面 {b['und_mah']} ≠ SQL {s_mah}")
            if name_ok == "DIFF":
                bad.append(f"{sid}/{mk}: 名字 ×N 页面 {sorted(b['chips'])} "
                           f"≠ SQL {sorted(sql_counts)}")
            # R5：整块没有结构化规格时必须用 spec_count_und，且 data-und = 记录数
            if und_only:
                if b["tpl"] != "drug.spec_count_und":
                    bad.append(f"{sid}/{mk}: 块头模板 {b['tpl']} ≠ drug.spec_count_und")
                if str(b["und_rec"]) != b["data_und"]:
                    bad.append(f"{sid}/{mk}: data-und={b['data_und']} ≠ 记录数 {b['und_rec']}")
            elif b["tpl"] != "drug.spec_count" or b["data_und"]:
                bad.append(f"{sid}/{mk}: 有规格的块不该用 {b['tpl']}"
                           f"（data-und={b['data_und']!r}）")
    print(f"{'page':28}{'mk':5}{'记录 页/SQL':18}{'厂家 页/SQL':16}{'名字×N':8}"
          f"{'chips':6}块头模板")
    for r in rows:
        print(f"{r['sid']:28}{r['mk']:5}{r['rec_page']!s:>7} / {r['rec_sql']!s:<7}"
              f"{r['mah_page']!s:>7} / {r['mah_sql']!s:<6}{r['names']:8}"
              f"{r['n_chips']:<6}{r['tpl']}")
    print(f"\n块数 {len(rows)} · 页面 {len(sids)} · 不一致 {len(bad)}")
    for b in bad:
        print("  ✗", b)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
