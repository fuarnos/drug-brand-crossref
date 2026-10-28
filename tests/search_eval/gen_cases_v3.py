# -*- coding: utf-8 -*-
"""task-84：在 cases_v2（320 例）基础上生成 cases_v3.json（500+）。

新增类别（期望均来自 DB 结构 / 外部 oracle，不来自检索输出反推）：
  es_accent      西语重音：DB 里带 áéíóúñ 的商品名（有/去重音两种写法）→ 该产品成分
  brand_alias    品牌别名：US 品牌名经 RxNorm/RxNav oracle 映射到 IN 成分 → substance
  pinyin_polyphone 多音字拼音：substance.inn_zh 含多音字 → 默认读音拼音串
  jianfan_mixed  繁简混写：v2 中文查询逐字换繁体（normalize_name 的 _T2S 反表）
  combo_brand    复方品牌：DB 多成分产品品牌名 → 全部成分 substance
  who_inn_zh     WHO INN 中文官方名（DB substance.inn_zh）→ 该 substance
  zero_result    随机无意义串（DB 三字符组不存在）→ 空结果

用法：python tests/search_eval/gen_cases_v3.py
输出：tests/trilingual/cases_v3.json；oracle 快照 .tmp/search-eval3/rxnorm_oracle.json
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
WORK = ROOT / ".tmp" / "search-eval3"
CASES_V2 = ROOT / "tests" / "trilingual" / "cases_v2.json"
CASES_V3 = ROOT / "tests" / "trilingual" / "cases_v3.json"
DB = ROOT / "data" / "drugs.db"
WORK.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "drug-crossref-search-eval/1.0 (non-commercial research)"}
sys.path.insert(0, str(ROOT / "site"))
PINYIN: dict[str, str] = {}
try:
    import build as site_build  # noqa: E402  —— 复用拼音字表（只读）
    PINYIN = site_build._pinyin_dict()
except Exception:  # pragma: no cover
    PINYIN = {}
if not PINYIN:
    # build.py 正被并行任务编辑/导入失败时的兜底：从源码直接解析 _PINYIN_CHARS_TEXT
    try:
        txt = (ROOT / "site" / "build.py").read_text(encoding="utf-8")
        m = re.search(r'_PINYIN_CHARS_TEXT\s*=\s*"(.*?)"', txt, re.S)
        if m:
            for part in m.group(1).split():
                ch, _, py = part.partition(":")
                if ch and py:
                    PINYIN[ch] = py
    except Exception:
        pass
print(f"pinyin table: {len(PINYIN)} chars")
from etl.normalize_name import _T2S, normalize  # noqa: E402  —— 繁体→简体字表 / 归一化

S2T: dict[str, str] = {}
for t, s in _T2S.items():
    S2T.setdefault(s, t)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ro_db():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def rxnorm_get(path: str, params: dict | None = None, timeout: int = 25):
    url = "https://rxnav.nlm.nih.gov/REST/" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def rxnorm_brand_ingredients(name: str) -> dict | None:
    """品牌名 → {rxcui, ingredients:[{name,rxcui}]}；无 IN 关系返回 None。"""
    d = rxnorm_get("rxcui.json", {"name": name})
    ids = ((d.get("idGroup") or {}).get("rxnormId") or [])
    if not ids:
        return None
    rxcui = ids[0]
    rel = rxnorm_get(f"rxcui/{rxcui}/related.json", {"tty": "IN"})
    ings = []
    for grp in (rel.get("relatedGroup") or {}).get("conceptGroup") or []:
        for c in grp.get("conceptProperties") or []:
            if c.get("name"):
                ings.append({"name": c["name"], "rxcui": c.get("rxcui")})
    if not ings:
        return None
    return {"rxcui": rxcui, "ingredients": ings}


def main() -> int:
    v2 = json.loads(CASES_V2.read_text(encoding="utf-8"))
    cases = list(v2["cases"])
    used_ids = {c["case_id"] for c in cases}
    new_cases: list[dict] = []
    provenance_pool: dict[str, dict] = {}

    def add(cat: str, lang: str, query: str, sids: list[str], policy: str,
            qtype: str, source: str, detail: str, extra: dict | None = None) -> None:
        n = sum(1 for c in new_cases if c["category"] == cat) + 1
        cid = f"v3-{cat}-{n:04d}"
        assert cid not in used_ids
        used_ids.add(cid)
        prov = {"source": source, "detail": detail,
                "generator": "tests/search_eval/gen_cases_v3.py",
                "generated_at": now()}
        if extra:
            prov.update(extra)
        new_cases.append({
            "case_id": cid, "category": cat, "lang": lang, "query": query,
            "query_type": qtype, "country": None,
            "expected": {"substance_ids": sids, "policy": policy,
                         "min_tier": None if policy == "must_empty" else "top5"},
            "expect_empty": policy == "must_empty",
            "provenance": prov, "tags": ["v3", cat],
        })

    db = ro_db()
    db.row_factory = sqlite3.Row
    db_sha = hashlib.sha256(DB.read_bytes()).hexdigest()

    # ---- 公共映射：商品名 raw → product_id；product_id → 成分 substance 集合；
    #      substance_id → inn_en；name_key 集合（用于确认查询确实落在索引键上）
    pid_by_trade: dict[str, str] = {}
    for r in db.execute("""
        SELECT nv.raw AS name, pn.product_id AS pid
        FROM product_name pn JOIN name_variant nv ON nv.key_id = pn.key_id
        WHERE pn.name_type = 'trade'"""):
        pid_by_trade.setdefault((r["name"] or "").strip().casefold(), r["pid"])
    pid_sids: dict[str, list[str]] = defaultdict(list)
    for r in db.execute("""
        SELECT DISTINCT pc.product_id AS pid, v.substance_id AS sid
        FROM product_component pc JOIN variant v ON v.variant_id = pc.variant_id"""):
        if r["sid"]:
            pid_sids[r["pid"]].append(r["sid"])
    inn_of = {r["substance_id"]: r["inn_en"] for r in db.execute(
        "SELECT substance_id, inn_en FROM substance") if r["inn_en"]}
    name_keys = {r[0] for r in db.execute("SELECT key_id FROM name_key")}

    def ing_matches(ing: str, sids: list[str]) -> bool:
        """RxNorm IN 名是否落在这些 substance 之一（含盐型/前缀匹配）。"""
        i = ing.casefold().strip()
        for sid in sids:
            inn = inn_of.get(sid, sid).casefold()
            if i == inn or inn.startswith(i + " ") or i in inn:
                return True
        return False

    # ---------------------------------------------------------------- 1) es_accent
    # 取带重音的商品名，要求：长度适中、无化妆品/剂型长串、归一化后的 name_key 确实存在、
    # 产品为单成分。期望 = 该产品成分（DB 结构），重音只是写法差异。
    accents = ("áéíóúñüÁÉÍÓÚÑÜàèìòùâêîôûäëïöç")
    BAD = ("SPF", "TEINT", "CRÈME", "CREME", "FOUNDATION", "CLEANSER", "MOISTURIZER",
           "FLUID", "SERUM", "/", "+", "ÉCLAT", "ECLAT")
    rows = db.execute("""
        SELECT nv.raw AS name, pn.product_id AS pid
        FROM product_name pn JOIN name_variant nv ON nv.key_id = pn.key_id
        WHERE pn.name_type = 'trade'""").fetchall()
    acc_seen = set()
    for r in rows:
        name = (r["name"] or "").strip()
        if not name or not any(ch in accents for ch in name):
            continue
        if len(name) < 4 or len(name) > 42 or any(b in name.upper() for b in BAD):
            continue
        sids = sorted(set(pid_sids.get(r["pid"], [])))
        if len(sids) != 1:
            continue
        key = normalize(name).norm
        if not key or key not in name_keys:
            continue
        if (name.casefold(), sids[0]) in acc_seen:
            continue
        acc_seen.add((name.casefold(), sids[0]))
        if sum(1 for c in new_cases if c["category"] == "es_accent") >= 40:
            break
        add("es_accent", "es", name, sids, "must_hit", "accented_name",
            "DB product_name + name_key", f"{r['pid']} trade {name!r}",
            {"product_id": r["pid"], "normalized_key": key})
    print(f"es_accent: {sum(1 for c in new_cases if c['category']=='es_accent')}")

    # ---------------------------------------------------------------- 2) brand_alias（RxNorm oracle）
    # 取 US trade 名，逐个问 RxNav：品牌 → IN 成分；IN 映射到 DB substance.inn_en
    inn_map = {str(r["inn_en"]).casefold(): r["substance_id"]
               for r in db.execute("SELECT substance_id, inn_en FROM substance")
               if r["inn_en"]}
    brands = [r[0] for r in db.execute("""
        SELECT DISTINCT nv.raw FROM product_name pn
        JOIN name_variant nv ON nv.key_id = pn.key_id
        JOIN product p ON p.product_id = pn.product_id
        WHERE p.country = 'US' AND pn.name_type = 'trade'
          AND nv.raw GLOB '[A-Za-z]*' AND length(nv.raw) BETWEEN 4 AND 40
        ORDER BY length(nv.raw) LIMIT 140""")]
    oracle = {}
    used_brand = set()
    for b in brands:
        if sum(1 for c in new_cases if c["category"] == "brand_alias") >= 50:
            break
        try:
            res = rxnorm_brand_ingredients(b)
        except Exception as exc:  # 网络失败：记录并继续
            oracle[b] = {"error": repr(exc)[:160]}
            continue
        oracle[b] = res
        if not res:
            continue
        pid = pid_by_trade.get(b.casefold())
        if not pid:
            continue
        comps = sorted(set(pid_sids.get(pid, [])))
        if not comps or len(comps) > 3:
            continue
        # oracle 交叉验证：RxNorm 给出的 IN 必须能落到该产品的某个成分上
        if not all(ing_matches(i["name"], comps) for i in res["ingredients"]):
            continue
        key = (b.casefold(), tuple(comps))
        if key in used_brand:
            continue
        used_brand.add(key)
        add("brand_alias", "en", b, comps, "must_hit", "rxnorm_brand",
            "RxNorm/RxNav + DB 产品成分", f"brand {b!r} rxcui={res['rxcui']} IN="
            + ", ".join(i["name"] for i in res["ingredients"])
            + f"; DB {pid} components={comps}",
            {"rxcui": res["rxcui"], "db_product_id": pid,
             "oracle_url":
             f"https://rxnav.nlm.nih.gov/REST/rxcui/{res['rxcui']}/related.json?tty=IN"})
        time.sleep(0.2)
    (WORK / "rxnorm_oracle.json").write_text(
        json.dumps({"generated_at": now(), "brands_queried": len(oracle),
                    "oracle": oracle}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"brand_alias: {sum(1 for c in new_cases if c['category']=='brand_alias')} "
          f"(RxNorm queried {len(oracle)})")

    # 2b) RxNorm 反向：已知 INN → BN（品牌名）→ 只有该 BN 确实在 DB 商品名里、
    #     且该产品的成分与 IN 对得上时才作为用例（期望 = DB 产品成分）
    inn_list = [r for r in db.execute(
        "SELECT substance_id, inn_en FROM substance WHERE inn_en != '' ORDER BY length(inn_en)")]
    random.seed(20261028)
    random.shuffle(inn_list)
    bn_count = 0
    for r in inn_list:
        if bn_count >= 30 or sum(1 for c in new_cases if c["category"] == "brand_alias") >= 50:
            break
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 \-]{2,40}", r["inn_en"]):
            continue
        try:
            d = rxnorm_get("rxcui.json", {"name": r["inn_en"]})
            ids = ((d.get("idGroup") or {}).get("rxnormId") or [])
            if not ids:
                continue
            rel = rxnorm_get(f"rxcui/{ids[0]}/related.json", {"tty": "BN"})
            bns = []
            for grp in (rel.get("relatedGroup") or {}).get("conceptGroup") or []:
                for c in grp.get("conceptProperties") or []:
                    if c.get("name"):
                        bns.append(c["name"])
        except Exception:
            continue
        time.sleep(0.2)
        for bn in bns[:3]:
            if bn_count >= 30 or sum(1 for c in new_cases if c["category"] == "brand_alias") >= 50:
                break
            if len(bn) < 4 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 \-]{3,40}", bn):
                continue
            pid = pid_by_trade.get(bn.casefold())
            if not pid:
                continue
            comps = sorted(set(pid_sids.get(pid, [])))
            if not comps or not any(ing_matches(r["inn_en"], comps) for _ in [0]):
                continue
            if any(c["query"].casefold() == bn.casefold() for c in new_cases):
                continue
            add("brand_alias", "en", bn, comps, "must_hit", "rxnorm_bn",
                "RxNorm/RxNav IN→BN + DB 商品名/成分",
                f"IN {r['inn_en']!r} rxcui={ids[0]} BN={bn!r}; DB {pid} components={comps}",
                {"rxcui": ids[0], "db_product_id": pid,
                 "oracle_url":
                 f"https://rxnav.nlm.nih.gov/REST/rxcui/{ids[0]}/related.json?tty=BN"})
            bn_count += 1
    print(f"brand_alias total: {sum(1 for c in new_cases if c['category']=='brand_alias')} "
          f"(IN→BN added {bn_count})")

    # ---------------------------------------------------------------- 3) pinyin_polyphone（多音字）
    POLY = set("重长行乐参柏薄阿熟川芎枸藏血降调都干发差着和率哪卡曾单解")
    poly = [r for r in db.execute(
        "SELECT substance_id, inn_zh FROM substance WHERE inn_zh != ''")
        if any(ch in POLY for ch in r["inn_zh"])]
    random.seed(20261028)
    random.shuffle(poly)
    for r in poly:
        if sum(1 for c in new_cases if c["category"] == "pinyin_polyphone") >= 25:
            break
        zh = r["inn_zh"]
        pys = [PINYIN.get(ch, "") for ch in zh]
        if not all(pys):
            continue
        q = "".join(pys)
        if not re.fullmatch(r"[a-z]{6,}", q):
            continue
        add("pinyin_polyphone", "zh", q, [r["substance_id"]], "gap", "pinyin",
            "DB substance.inn_zh + build._pinyin_dict", f"{zh} -> {q}",
            {"polyphonic": True})
    print(f"pinyin_polyphone: {sum(1 for c in new_cases if c['category']=='pinyin_polyphone')}")

    # ---------------------------------------------------------------- 4) jianfan_mixed（繁简混写）
    v2_zh = [c for c in cases if c["lang"] == "zh" and c["expected"]["policy"] == "must_hit"
             and re.search(r"[\u4e00-\u9fff]", c["query"]) and len(c["query"]) <= 14]
    random.shuffle(v2_zh)
    for c in v2_zh:
        if sum(1 for c in new_cases if c["category"] == "jianfan_mixed") >= 25:
            break
        q = c["query"]
        out = []
        changed = 0
        for i, ch in enumerate(q):
            t = S2T.get(ch)
            if t and i % 2 == 0:      # 每隔一个字换繁体：混写
                out.append(t)
                changed += 1
            else:
                out.append(ch)
        if changed < 2:
            continue
        mixed = "".join(out)
        add("jianfan_mixed", "zh", mixed, c["expected"]["substance_ids"], "must_hit",
            "trad_mixed", "DB + cases_v2 + normalize_name._T2S 反表",
            f"{q} -> {mixed}", {"origin_case": c["case_id"]})
    print(f"jianfan_mixed: {sum(1 for c in new_cases if c['category']=='jianfan_mixed')}")

    # 4b) 从 substance.inn_zh（WHO INN 中文名）继续生成繁简混写（补齐到 25 例）
    zh_rows = [r for r in db.execute(
        "SELECT substance_id, inn_zh FROM substance WHERE inn_zh != '' ORDER BY length(inn_zh)")]
    random.shuffle(zh_rows)
    for r in zh_rows:
        if sum(1 for c in new_cases if c["category"] == "jianfan_mixed") >= 25:
            break
        q = r["inn_zh"]
        out = []
        changed = 0
        for i, ch in enumerate(q):
            t = S2T.get(ch)
            if t and i % 2 == 0:
                out.append(t)
                changed += 1
            else:
                out.append(ch)
        if changed < 2:
            continue
        mixed = "".join(out)
        if any(c["query"] == mixed for c in new_cases):
            continue
        add("jianfan_mixed", "zh", mixed, [r["substance_id"]], "must_hit", "trad_mixed",
            "DB substance.inn_zh + normalize_name._T2S 反表",
            f"{q} -> {mixed}", {"origin": "inn_zh", "origin_zh": q})
    print(f"jianfan_mixed total: {sum(1 for c in new_cases if c['category']=='jianfan_mixed')}")

    # ---------------------------------------------------------------- 5) combo_brand（复方品牌）
    combo_base = db.execute("""
        SELECT p.product_id, p.country
        FROM product p JOIN product_component pc ON pc.product_id = p.product_id
        WHERE p.country IN ('US','ES','GB','CA','AU')
        GROUP BY p.product_id
        HAVING COUNT(*) >= 2
        LIMIT 120
    """).fetchall()
    seen_combo = set()
    for base in combo_base:
        if sum(1 for c in new_cases if c["category"] == "combo_brand") >= 30:
            break
        pid = base["product_id"]
        sids = [r[0] for r in db.execute("""
            SELECT DISTINCT v.substance_id FROM product_component pc
            JOIN variant v ON v.variant_id = pc.variant_id WHERE pc.product_id = ?""",
            (pid,)) if r[0]]
        brand_row = db.execute("""
            SELECT nv.raw FROM product_name pn JOIN name_variant nv
            ON nv.key_id = pn.key_id WHERE pn.product_id = ? AND pn.name_type='trade'
            ORDER BY nv.raw LIMIT 1""", (pid,)).fetchone()
        brand = (brand_row[0] if brand_row else "").strip()
        if not brand or not (2 <= len(sids) <= 4):
            continue
        if brand.casefold() in seen_combo:
            continue
        seen_combo.add(brand.casefold())
        add("combo_brand", "en" if base["country"] in ("US", "GB", "CA", "AU") else "es",
            brand, sids, "must_hit", "combo_brand",
            "DB product_component", f"{pid} ({base['country']}) components={sids}",
            {"product_id": pid, "country": base["country"]})
    print(f"combo_brand: {sum(1 for c in new_cases if c['category']=='combo_brand')}")

    # ---------------------------------------------------------------- 6) who_inn_zh
    inn_zh_rows = [r for r in db.execute(
        "SELECT substance_id, inn_en, inn_zh FROM substance WHERE inn_zh != ''")
        if re.fullmatch(r"[\u4e00-\u9fff（）()\-]+", r["inn_zh"] or "")
        and not any(ch in POLY for ch in r["inn_zh"])]
    random.shuffle(inn_zh_rows)
    for r in inn_zh_rows:
        if sum(1 for c in new_cases if c["category"] == "who_inn_zh") >= 25:
            break
        add("who_inn_zh", "zh", r["inn_zh"], [r["substance_id"]], "must_hit",
            "who_inn_zh", "DB substance.inn_zh（WHO INN 中文官方名）",
            f"{r['inn_zh']} = {r['inn_en']}")
    print(f"who_inn_zh: {sum(1 for c in new_cases if c['category']=='who_inn_zh')}")

    # ---------------------------------------------------------------- 7) zero_result
    # 构造方法：随机 10–14 位小写串；要求其任意 3-gram 不出现在 name_key 名字里
    # （期望 = DB 结构里没有这个串，绝不来自检索输出）。
    names = [r[0].casefold() for r in db.execute("SELECT key_id FROM name_key")]
    trigrams = set()
    bigrams = set()
    for nm in names:
        for i in range(len(nm) - 2):
            trigrams.add(nm[i:i + 3])
        for i in range(len(nm) - 1):
            bigrams.add(nm[i:i + 2])

    def stale_zero(case: dict) -> bool:
        """v2 zero 用例是否因 DB 增长而失效：查询已被某个 name_key 包含/近邻。"""
        q = str(case["query"]).casefold()
        if not q:
            return True
        if any(q in nm for nm in names):
            return True
        if all(ord(ch) < 128 for ch in q):
            return any(q[i:i + 3] in trigrams for i in range(len(q) - 2))
        return any(q[i:i + 2] in bigrams for i in range(len(q) - 1))

    zero_cases = [c for c in cases if c["category"] == "zero_result"]
    v2_zero_stale = [c for c in zero_cases if stale_zero(c)]
    keep_zero = [c for c in zero_cases if not stale_zero(c)]
    cases = [c for c in cases if c["category"] != "zero_result"] + keep_zero
    print(f"v2 zero 保留 {len(keep_zero)}/{len(zero_cases)}（失效 {len(v2_zero_stale)}："
          f"{[c['query'] for c in v2_zero_stale][:8]}）")
    letters = "bcdfghjklmnpqrstvwxzqjxvz"
    zero_qs = set()
    tries = 0
    target_new = max(12, 40 - len(keep_zero) - 6)
    while len(zero_qs) < target_new and tries < 8000:
        tries += 1
        q = "".join(random.choice(letters) for _ in range(random.choice((10, 11, 12, 14))))
        grams = {q[i:i + 3] for i in range(len(q) - 2)}
        if any(g in trigrams for g in grams):
            continue
        if any(c["query"].casefold() == q for c in keep_zero):
            continue
        zero_qs.add(q)
    for q in sorted(zero_qs):
        add("zero_result", "en", q, [], "must_empty", "random_no_gram",
            "DB name_key 3-gram 反证", f"3-gram not in name_key: {q}")
    # 符号/罕见字符串：normalize 后为空或无法命中
    for q in ("§¶†‡", "☃☃", "ꙮꙮ", "ᚠᚡᚢ", "☂☃☄", "ℵℶℷ"):
        add("zero_result", "en", q, [], "must_empty", "symbols",
            "人工构造（不可能命中）", f"symbol-only query {q!r}")
    print(f"zero_result: {sum(1 for c in new_cases if c['category']=='zero_result')} 新增，"
          f"总计 {sum(1 for c in cases if c['category']=='zero_result') + sum(1 for c in new_cases if c['category']=='zero_result')}")

    db.close()
    cases.extend(new_cases)
    meta = {
        "version": "v3.0",
        "generated_at": now(),
        "base": {"file": "tests/trilingual/cases_v2.json",
                 "n": len(v2["cases"]), "meta": v2.get("meta")},
        "db_sha256": db_sha,
        "n_cases": len(cases),
        "categories": dict(Counter(c["category"] for c in cases)),
        "policies": dict(Counter(c["expected"]["policy"] for c in cases)),
        "new_categories": dict(Counter(c["category"] for c in new_cases)),
        "oracles": {
            "rxnorm": {"source": "RxNorm / RxNav (NLM, US public domain)",
                       "url": "https://rxnav.nlm.nih.gov/REST/",
                       "snapshot": ".tmp/search-eval3/rxnorm_oracle.json",
                       "brands_queried": len(oracle)},
            "who_inn": "DB substance.inn_zh（WHO INN 中文名，仅名称事实）",
            "db_structure": "DB product/product_name/product_component 关系",
            "normalize_t2s": "etl/normalize_name._T2S 反表（繁简混写）",
            "pinyin": "site/build.py _pinyin_dict（默认读音）",
        },
    }
    CASES_V3.write_text(json.dumps({"meta": meta, "cases": cases}, ensure_ascii=False,
                                   indent=1), encoding="utf-8")
    print(f"\nwritten {CASES_V3.relative_to(ROOT)}: {len(cases)} cases "
          f"(new {len(new_cases)}) categories={meta['new_categories']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
