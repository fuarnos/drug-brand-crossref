# -*- coding: utf-8 -*-
"""药物互相对应审计 + 合并候选（task-40，只读 DB）。

产出
----
1. `data/cross_market_merge_candidates.csv`：单方/复方合并候选（每条带证据 + confidence
   + status）。只读 `data/drugs.db` 与 data/ 下既有映射表，不写库。
2. `.tmp/cross-market/audit.json`：成分×市场矩阵、跨市场链接率、重复成分对、
   复方成分集合分布，以及「应用候选后」的 before/after 复方同集合匹配率（模拟）。

候选来源（按证据优先级）
------------------------
  existing_override  data/cn_inn_overrides.csv / data/es_inn_overrides.csv 已有映射（未应用部分）
  who_inn            data/who_inn_names.csv（WHO INN 官方中文/西语名 → 英文 INN）
  cn_old_name        data/cn_aliases_final.csv（中文旧称/别名 → 现通用名）→ 再用上述表映射
  cn_name_map        data/cn_name_map.json（中文注册名 → 英文 INN，人工初判）
  cn2en              etl/ingest_nhsa.py 的 CN2EN 表（1,088 条）
  cima_vtm           CIMA 单方产品 vtm（西语名→库内 substance）反查表
  mx_inn_map         data/mx_inn_map.json（西语→英文 INN，COFEPRIS 表）
  atc4               成分 ATC 前 5 位（level-4）唯一命中英文成分（仅作弱证据）
  rule               西语构词规则（-ina→-ine、-prazol→prazole 等）
  duplicate           reports/substance_duplicates.csv（27 对重复成分，名称归一后同名）

状态
----
  mergeable   目标英文 substance 存在 + 证据足够 → 建议 Lead 走 merge_cn/es_substances.py
  uncertain   多候选/弱证据/ATC 不唯一 → 只记录，不自动 apply
  needs_target 英文 INN 已知但库内无独立英文 substance → 需先建英文成分再合并

用法：python etl/build_cross_market_candidates.py
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "etl"))
DB = ROOT / "data" / "drugs.db"
CAND = ROOT / "data" / "cross_market_merge_candidates.csv"
EVID = ROOT / ".tmp" / "cross-market"
TODAY = date.today().isoformat()

CN_OVR = ROOT / "data" / "cn_inn_overrides.csv"
ES_OVR = ROOT / "data" / "es_inn_overrides.csv"
WHO_INN = ROOT / "data" / "who_inn_names.csv"
CN_ALIAS = ROOT / "data" / "cn_aliases_final.csv"
CN_MAP = ROOT / "data" / "cn_name_map.json"
MX_MAP = ROOT / "data" / "mx_inn_map.json"
DUPS = ROOT / "reports" / "substance_duplicates.csv"
CN2EN_SRC = ROOT / "etl" / "ingest_nhsa.py"

MARKETS = ("US", "GB", "CN", "ES", "MX", "AU", "CA")

# 中文剂型/盐基/限定词（匹配前剥离；只用于「名字对名字」）
ZH_FORM_WORDS = [
    "注射液", "注射用", "片剂", "片", "胶囊", "颗粒", "口服液", "口服溶液", "滴眼液", "滴耳液",
    "眼膏", "软膏", "乳膏", "凝胶", "栓", "散", "丸", "糖浆", "喷雾剂", "吸入剂", "气雾剂",
    "缓释片", "缓释胶囊", "控释片", "肠溶片", "肠溶胶囊", "分散片", "咀嚼片", "泡腾片",
    "混悬液", "混悬剂", "干混悬剂", "滴剂", "酊", "贴剂", "贴膏", "乳剂", "洗剂", "搽剂",
    "复方", "氯化钠注射液", "葡萄糖注射液",
]
ZH_SALT_WORDS = [
    "盐酸", "硫酸", "醋酸", "枸橼酸", "柠檬酸", "马来酸", "富马酸", "琥珀酸", "甲苯磺酸",
    "苯磺酸", "氢溴酸", "磷酸", "酒石酸", "乳酸", "葡萄糖酸", "硬脂酸", "棕榈酸", "戊酸",
    "丙酸", "丁酸", "苯甲酸", "水杨酸", "烟酸", "硝酸", "碳酸", "氨甲环酸", "双羟萘酸",
    "钠", "钾", "钙", "镁", "铵", "二钠", "三钠", "二钾", "酯", "一水合物", "二水合物",
    "倍半水合物", "无水", "消旋", "左旋", "右旋",
]
ES_FILLER = {"de", "del", "la", "el", "los", "las", "y", "con", "para", "en"}

# 中文盐/酯/水合物标记 → 英文盐名（用于「目标必须带对应盐 variant」的安全检查）
ZH_SALT_EN = {
    "盐酸": "hydrochloride", "硫酸": "sulfate", "醋酸": "acetate", "乙酸": "acetate",
    "马来酸": "maleate", "富马酸": "fumarate", "琥珀酸": "succinate",
    "甲苯磺酸": "tosylate", "苯磺酸": "besylate", "氢溴酸": "hydrobromide",
    "磷酸": "phosphate", "酒石酸": "tartrate", "枸橼酸": "citrate", "柠檬酸": "citrate",
    "苯甲酸": "benzoate", "戊酸": "valerate", "丙酸": "propionate", "丁酸": "butyrate",
    "棕榈酸": "palmitate", "硬脂酸": "stearate", "硝酸": "nitrate", "碳酸": "carbonate",
    "葡萄糖酸": "gluconate", "乳酸": "lactate", "门冬氨酸": "aspartate",
    "天冬氨酸": "aspartate", "双羟萘酸": "pamoate", "氨甲环酸": "tranexamate",
    "甲磺酸": "mesylate", "溴化": "bromide", "氯化": "chloride", "碘化": "iodide",
    "氟化": "fluoride", "氢氧化": "hydroxide", "氧化": "oxide", "乙酰": "acetyl",
    "丙酰": "propionyl", "丁酰": "butyryl", "琥珀酰": "succinyl",
    "水杨酸": "salicylate", "山梨酸": "sorbate", "苯乙酸": "phenylacetate",
    "环丙酸": "cyclopropionate", "乙二磺酸": "edisylate",
}
ZH_SALT_CATION = {
    "钠": "sodium", "钾": "potassium", "钙": "calcium", "镁": "magnesium",
    "铵": "ammonium", "亚铁": "ferrous", "铁": "iron", "锌": "zinc",
}
ZH_STEREO = {"右旋": "dex", "左旋": "levo", "消旋": "racemic"}
ES_SALT_EN = {
    "clorhidrato": "hydrochloride", "hidrocloruro": "hydrochloride",
    "sodico": "sodium", "sodica": "sodium", "sodio": "sodium",
    "potasico": "potassium", "potasica": "potassium", "calcico": "calcium",
    "calcica": "calcium", "magnesico": "magnesium", "nitrato": "nitrate",
    "sulfato": "sulfate", "fosfato": "phosphate", "citrato": "citrate",
    "lactato": "lactate", "acetato": "acetate", "maleato": "maleate",
    "fumarato": "fumarate", "tartrato": "tartrate", "mesilato": "mesylate",
    "besilato": "besylate", "tosilato": "tosylate", "succinato": "succinate",
    "gluconato": "gluconate", "carbonato": "carbonate", "bicarbonato": "bicarbonate",
}


def deacc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c))


def norm_latin(s: str) -> str:
    s = deacc(s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_zh(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    s = re.sub(r"[\s・·,，;；/、。.]+", "", s)
    for w in ZH_FORM_WORDS:
        s = s.replace(w, "")
    return s


def strip_zh_salt(s: str) -> str:
    for w in sorted(ZH_SALT_WORDS, key=len, reverse=True):
        if s.startswith(w) and len(s) > len(w):
            s = s[len(w):]
    for w in sorted(ZH_SALT_WORDS, key=len, reverse=True):
        if s.endswith(w) and len(s) > len(w):
            s = s[: -len(w)]
    return s


def zh_keys(name: str) -> list[str]:
    """中文名的多级归一键：原样 → 去剂型 → 再剥盐基。"""
    out = []
    for cand in (name, norm_zh(name), strip_zh_salt(norm_zh(name))):
        if cand and cand not in out:
            out.append(cand)
    return out


def latin_keys(name: str) -> list[str]:
    out = []
    n = norm_latin(name)
    if n:
        out.append(n)
    # 去西语连接词后的紧凑形式
    toks = [t for t in n.split() if t not in ES_FILLER]
    c = " ".join(toks)
    if c and c not in out:
        out.append(c)
    return out


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", deacc(s or "").lower()).strip("-")


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return list(csv.DictReader(open(path, encoding="utf-8-sig")))


def connect_ro() -> sqlite3.Connection:
    uri = "file:" + str(DB.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------------------
# 索引
# ---------------------------------------------------------------------------
def load_substances(con: sqlite3.Connection) -> dict[str, dict]:
    subs = {}
    for r in con.execute("SELECT substance_id, inn_en, inn_zh, atc FROM substance"):
        subs[r["substance_id"]] = {"sid": r["substance_id"], "inn_en": r["inn_en"],
                                   "inn_zh": r["inn_zh"] or "", "atc": (r["atc"] or "").strip(),
                                   "markets": set(), "n_products": 0}
    for r in con.execute("""
        SELECT v.substance_id, p.country, COUNT(DISTINCT p.product_id) n
        FROM variant v JOIN product_component pc ON pc.variant_id=v.variant_id
        JOIN product p ON p.product_id=pc.product_id GROUP BY v.substance_id, p.country"""):
        s = subs.get(r["substance_id"])
        if s:
            s["markets"].add(r["country"])
            s["n_products"] += r["n"]
    return subs


def build_lookups(subs: dict[str, dict]) -> dict:
    """多个索引：英文名→id、slug→id、ATC→ids、中文名→ids、西语名→ids、WHO 表。"""
    en_by_norm: dict[str, str] = {}
    en_by_slug: dict[str, str] = {}
    en_by_atc: dict[str, list[str]] = defaultdict(list)
    zh_by_key: dict[str, list[str]] = defaultdict(list)
    es_by_key: dict[str, list[str]] = defaultdict(list)
    for sid, s in subs.items():
        if sid.startswith(("cn-", "mx-es-")):
            continue
        n = norm_latin(s["inn_en"])
        if n:
            en_by_norm.setdefault(n, sid)
            en_by_slug.setdefault(slug(n), sid)
        if s["atc"]:
            en_by_atc[s["atc"][:5]].append(sid)
        if s["inn_zh"]:
            for k in zh_keys(s["inn_zh"]):
                zh_by_key[k].append(sid)
        n2 = norm_latin(s["inn_en"])
        if n2:
            es_by_key[n2].append(sid)
    return {"en_norm": en_by_norm, "en_slug": en_by_slug, "en_atc": dict(en_by_atc),
            "zh": dict(zh_by_key), "es": dict(es_by_key)}


def load_who_inn() -> dict:
    """WHO INN 官方多语名 → 英文 INN。"""
    rows = read_csv(WHO_INN)
    zh_map: dict[str, str] = {}
    es_map: dict[str, str] = {}
    info: dict[str, dict] = {}
    for r in rows:
        en = (r.get("inn_en") or "").strip()
        if not en:
            continue
        info[norm_latin(en)] = r
        for k in zh_keys(r.get("inn_zh") or ""):
            zh_map.setdefault(k, en)
        for k in latin_keys(r.get("inn_es") or ""):
            es_map.setdefault(k, en)
    return {"zh": zh_map, "es": es_map, "info": info, "rows": len(rows)}


def load_variant_salts(con: sqlite3.Connection) -> dict[str, set[str]]:
    """substance → 其 variant 的 salt 名（英文小写）集合（盐型安全检查用）。"""
    out: dict[str, set[str]] = defaultdict(set)
    for sid, salt in con.execute("SELECT substance_id, salt FROM variant"):
        if salt:
            out[sid].add(norm_latin(salt))
    return dict(out)


def salt_mismatch(source_id: str, source_name: str, target_id: str, subs: dict,
                  salts: dict[str, set[str]]) -> str:
    """中文/西语名里的盐/酯标记，若目标英文名与 variant 都没有 → 返回不匹配说明。"""
    markers: list[str] = []
    if source_id.startswith("cn-") or re.search(r"[\u4e00-\u9fff]", source_name):
        n = unicodedata.normalize("NFKC", source_name or "")
        for zh, en in ZH_SALT_EN.items():
            if zh in n:
                markers.append(en)
        for zh, en in ZH_SALT_CATION.items():
            if zh in n:
                markers.append(en)
        for zh, en in ZH_STEREO.items():
            if zh in n:
                markers.append(en)
    else:
        toks = norm_latin(source_name).split()
        for es, en in ES_SALT_EN.items():
            if es in toks:
                markers.append(en)
    if not markers or target_id not in subs:
        return ""
    tgt = subs[target_id]
    have = set(norm_latin(tgt["inn_en"]).split()) | salts.get(target_id, set())
    norm_alias = {"sulphate": "sulfate", "sulphide": "sulfide", "dextro": "dex"}
    have = {norm_alias.get(x, x) for x in have}
    missing = [m for m in markers if norm_alias.get(m, m) not in have]
    if missing:
        return "目标 %s 不含盐型/立体标记 %s（源名有，需对应 variant/母体名才能安全合并）" % (
            target_id, "/".join(sorted(set(missing))))
    return ""


def load_cima_vtm(con: sqlite3.Connection) -> dict:
    """CIMA 单方产品 vtm（西语名）→ 库内 substance（ES ingest 的映射结果）。"""
    pages = sorted((ROOT / "data" / "raw" / "cima").glob("page-*.json"))
    rec2vtm = {}
    for f in pages:
        for r in json.load(open(f, encoding="utf-8")).get("resultados", []):
            nreg = str(r.get("nregistro") or "")
            vtm = ((r.get("vtm") or {}).get("nombre") or "").strip()
            if nreg and vtm and " + " not in vtm and vtm.lower() != "multicomponente":
                rec2vtm[nreg] = vtm
    out: dict[str, Counter] = defaultdict(Counter)
    pat = re.compile(r"nregistro=([^&]+)")
    for r in con.execute("""
        SELECT p.source_url, v.substance_id FROM product p
        JOIN product_component pc ON pc.product_id=p.product_id
        JOIN variant v ON v.variant_id=pc.variant_id WHERE p.country='ES'"""):
        m = pat.search(r["source_url"] or "")
        if not m:
            continue
        vtm = rec2vtm.get(m.group(1))
        if vtm:
            out[vtm][r["substance_id"]] += 1
    # 只留唯一 target
    return {k: v.most_common(1)[0][0] for k, v in out.items() if len(v) == 1}


def load_cn2en() -> dict:
    """ingest_nhsa.py 的 CN2EN 表（中文通用名→英文 INN）。用 ast 提取，不 import 整个模块。"""
    try:
        src = CN2EN_SRC.read_text(encoding="utf-8")
        i = src.find("CN2EN: dict[str, str] = {")
        j = src.find("\n}", i)
        body = src[i:j]
        pairs = re.findall(r'"([^"]+)":\s*"([^"]+)"', body)
        return {k: v for k, v in pairs}
    except Exception as e:  # noqa: BLE001
        print("  [warn] CN2EN 提取失败:", e)
        return {}


def load_cn_name_map() -> dict:
    d = json.load(open(CN_MAP, encoding="utf-8")).get("map") or {}
    out = {}
    for k, v in d.items():
        if v:
            out[k] = v[0] if isinstance(v, list) else v
    return out


def load_mx_inn_map() -> dict:
    d = json.load(open(MX_MAP, encoding="utf-8")).get("terms") or {}
    out = {}
    for es, rec in d.items():
        inn = (rec or {}).get("inn") or ""
        score = float((rec or {}).get("score") or 0)
        if inn and score >= 0.9 and (rec or {}).get("via") in ("manual", "exact", "rule"):
            for k in latin_keys(es):
                out.setdefault(k, inn)
    return out


def load_cn_aliases() -> dict:
    """中文旧称/别名 → 现通用名（同一中文体系）。"""
    out = {}
    for r in read_csv(CN_ALIAS):
        a = norm_zh(r.get("alias") or "")
        n = norm_zh(r.get("name") or "")
        if a and n:
            out.setdefault(a, n)
    return out


# ---------------------------------------------------------------------------
# 候选生成
# ---------------------------------------------------------------------------
def pick_target(en_inn: str, subs: dict, lk: dict) -> tuple[str | None, str]:
    if not en_inn:
        return None, ""
    cand = norm_latin(en_inn)
    if cand in lk["en_norm"]:
        return lk["en_norm"][cand], "en_exact"
    if slug(cand) in lk["en_slug"]:
        return lk["en_slug"][slug(cand)], "en_slug"
    return None, ""


def make_cand(kind: str, source: dict, target_id: str | None, target_name: str,
              et: str, evidence: str, confidence: str, status: str, subs: dict) -> dict:
    return {
        "candidate_type": kind, "source_id": source["sid"],
        "source_name": source.get("inn_zh") or source.get("inn_en") or "",
        "source_markets": ",".join(sorted(source.get("markets", []))),
        "target_id": target_id or "", "target_name": target_name or "",
        "evidence_type": et, "evidence": evidence[:400], "confidence": confidence,
        "status": status, "n_products": source.get("n_products", 0),
        "source_atc": source.get("atc", ""),
    }


def cn_candidates(subs: dict, lk: dict, who: dict, cn2en: dict, cn_map: dict,
                  cn_alias: dict) -> list[dict]:
    out = []
    # A) 已有 override（未应用部分）
    for r in read_csv(CN_OVR):
        sid = (r.get("cn_substance_id") or "").strip()
        if not sid or sid not in subs:
            continue
        status0 = (r.get("status") or "").strip()
        if status0 == "mergeable":       # 已 apply 或待 apply 的由 merge 脚本负责，不重复
            continue
        en = (r.get("en_inn") or "").strip()
        target, how = pick_target(en, subs, lk) if en else (None, "")
        if target:
            out.append(make_cand("substance_merge", subs[sid], target, "", "existing_override",
                                 f"cn_inn_overrides：{r.get('reason','')[:160]}；en_inn={en}",
                                 (r.get("confidence") or "medium"), "mergeable", subs))
            continue
        k = (r.get("zh_name") or "").strip()
        hit = None
        for key in zh_keys(k):
            if key in who["zh"]:
                hit = ("who_inn", who["zh"][key], "WHO INN 中文名 " + key)
                break
            if key in cn2en:
                hit = ("cn2en", cn2en[key], "CN2EN 表 " + key)
                break
            if key in cn_map:
                hit = ("cn_name_map", cn_map[key], "cn_name_map " + key)
                break
        if hit:
            target, how = pick_target(hit[1], subs, lk)
            if target:
                out.append(make_cand("substance_merge", subs[sid], target, "", hit[0],
                                     hit[2], "medium", "mergeable", subs))
            else:
                out.append(make_cand("substance_merge", subs[sid], "", hit[1], hit[0],
                                     hit[2] + "（库内无英文 substance）", "medium",
                                     "needs_target", subs))
        elif en:
            out.append(make_cand("substance_merge", subs[sid], "", en, "existing_override",
                                 f"已有英文 INN {en} 但库内无对应 substance",
                                 (r.get("confidence") or "medium"), "needs_target", subs))
    # B) 全部 cn- 成分：WHO 中文名 → 英文 INN
    seen = {c["source_id"] for c in out}
    for sid, s in subs.items():
        if not sid.startswith("cn-") or sid in seen:
            continue
        name = s["inn_zh"] or s["inn_en"]
        for key in zh_keys(name):
            if key in who["zh"]:
                target, _ = pick_target(who["zh"][key], subs, lk)
                if target:
                    out.append(make_cand("substance_merge", s, target, "", "who_inn",
                                         f"WHO INN inn_zh={key} → {who['zh'][key]}",
                                         "high", "mergeable", subs))
                else:
                    out.append(make_cand("substance_merge", s, "", who["zh"][key], "who_inn",
                                         f"WHO INN inn_zh={key}（库内无英文 substance）",
                                         "high", "needs_target", subs))
                break
    # C) 旧称/别名：别名 → 现通用名 → WHO/CN2EN/name_map
    seen = {c["source_id"] for c in out}
    for sid, s in subs.items():
        if not sid.startswith("cn-") or sid in seen:
            continue
        name = norm_zh(s["inn_zh"] or s["inn_en"])
        alias_target = cn_alias.get(name)
        if not alias_target:
            continue
        target = None
        et, ev = "cn_old_name", ""
        for key in zh_keys(alias_target):
            if key in who["zh"]:
                target, _ = pick_target(who["zh"][key], subs, lk)
                et, ev = "cn_old_name+who_inn", f"旧称→{alias_target}→WHO {who['zh'][key]}"
                break
            if key in cn2en:
                target, _ = pick_target(cn2en[key], subs, lk)
                et, ev = "cn_old_name+cn2en", f"旧称→{alias_target}→CN2EN {cn2en[key]}"
                break
            if key in cn_map:
                target, _ = pick_target(cn_map[key], subs, lk)
                et, ev = "cn_old_name+cn_name_map", f"旧称→{alias_target}→cn_name_map {cn_map[key]}"
                break
        if target:
            out.append(make_cand("substance_merge", s, target, "", et, ev, "medium",
                                 "mergeable", subs))
    # D) ATC level-4 唯一命中（弱证据，只对仍无候选的 cn-）
    seen = {c["source_id"] for c in out}
    for sid, s in subs.items():
        if not sid.startswith("cn-") or sid in seen:
            continue
        atc = s["atc"]
        if len(atc) < 5:
            continue
        hits = lk["en_atc"].get(atc[:5], [])
        if len(hits) == 1:
            t = hits[0]
            out.append(make_cand("substance_merge", s, t, "", "atc4",
                                 f"ATC level-4 {atc[:5]} 唯一命中 {t}（弱证据，需人工核）",
                                 "low", "uncertain", subs))
    return out


def es_candidates(subs: dict, lk: dict, who: dict, mx_map: dict, cima: dict) -> list[dict]:
    out = []
    # A) 已有 override 未应用部分
    for r in read_csv(ES_OVR):
        sid = (r.get("es_substance_id") or "").strip()
        if not sid or sid not in subs:
            continue
        status0 = (r.get("status") or "").strip()
        if status0 == "mergeable":
            continue
        en = (r.get("en_inn") or "").strip()
        target, how = pick_target(en, subs, lk) if en else (None, "")
        if target:
            out.append(make_cand("substance_merge", subs[sid], target, "", "existing_override",
                                 f"es_inn_overrides：{r.get('reason','')[:160]}；en_inn={en}",
                                 (r.get("confidence") or "medium"), "mergeable", subs))
        else:
            name = (r.get("es_name") or "").strip()
            target = None
            for key in latin_keys(name):
                if key in who["es"]:
                    target, _ = pick_target(who["es"][key], subs, lk)
                    if target:
                        out.append(make_cand("substance_merge", subs[sid], target, "",
                                             "who_inn", f"WHO INN inn_es={key} → {who['es'][key]}",
                                             "high", "mergeable", subs))
                    else:
                        out.append(make_cand("substance_merge", subs[sid], "", who["es"][key],
                                             "who_inn", f"WHO INN inn_es={key}（库内无英文 substance）",
                                             "high", "needs_target", subs))
                    break
                if key in mx_map:
                    target, _ = pick_target(mx_map[key], subs, lk)
                    if target:
                        out.append(make_cand("substance_merge", subs[sid], target, "", "mx_inn_map",
                                             f"mx_inn_map {key} → {mx_map[key]}", "medium",
                                             "mergeable", subs))
                        break
                if name in cima:
                    t = cima[name]
                    if t in subs and not t.startswith(("cn-", "mx-es-")) and t != sid:
                        out.append(make_cand("substance_merge", subs[sid], t, "", "cima_vtm",
                                             f"CIMA 单方 vtm={name} 在库内对应 {t}", "medium",
                                             "mergeable", subs))
                        break
    # B) 全部 mx-es：WHO 西语名 / mx_inn_map / CIMA vtm / ATC
    seen = {c["source_id"] for c in out}
    for sid, s in subs.items():
        if not sid.startswith("mx-es-") or sid in seen:
            continue
        name = s["inn_en"] or ""
        target = None
        # WHO 西语名
        for key in latin_keys(name):
            if key in who["es"]:
                target, _ = pick_target(who["es"][key], subs, lk)
                if target:
                    out.append(make_cand("substance_merge", s, target, "", "who_inn",
                                         f"WHO INN inn_es={key} → {who['es'][key]}", "high",
                                         "mergeable", subs))
                else:
                    out.append(make_cand("substance_merge", s, "", who["es"][key], "who_inn",
                                         f"WHO INN inn_es={key}（库内无英文 substance）", "high",
                                         "needs_target", subs))
                break
            if key in mx_map:
                target, _ = pick_target(mx_map[key], subs, lk)
                if target:
                    out.append(make_cand("substance_merge", s, target, "", "mx_inn_map",
                                         f"mx_inn_map {key} → {mx_map[key]}", "medium",
                                         "mergeable", subs))
                    break
            if name in cima and cima[name] != sid and not cima[name].startswith(("cn-", "mx-es-")):
                out.append(make_cand("substance_merge", s, cima[name], "", "cima_vtm",
                                     f"CIMA 单方 vtm={name} → {cima[name]}", "medium",
                                     "mergeable", subs))
                break
        if sid in {c["source_id"] for c in out}:
            continue
        # ATC 前缀唯一
        atc = s["atc"]
        if atc and len(atc) >= 5:
            hits = lk["en_atc"].get(atc[:5], [])
            if len(hits) == 1:
                out.append(make_cand("substance_merge", s, hits[0], "", "atc4",
                                     f"ATC level-4 {atc[:5]} 唯一命中 {hits[0]}（弱证据）",
                                     "low", "uncertain", subs))
    return out


def duplicate_candidates(subs: dict) -> list[dict]:
    out = []
    for r in read_csv(DUPS):
        target = (r.get("canonical") or "").strip()
        dup = (r.get("dup_id") or "").strip()
        if target not in subs or dup not in subs or target == dup:
            continue
        out.append({
            "candidate_type": "duplicate_merge", "source_id": dup,
            "source_name": subs[dup]["inn_zh"] or subs[dup]["inn_en"],
            "source_markets": ",".join(sorted(subs[dup]["markets"])),
            "target_id": target, "target_name": subs[target]["inn_zh"] or subs[target]["inn_en"],
            "evidence_type": "duplicate_name",
            "evidence": f"reports/substance_duplicates.csv：{r.get('dup_name','')} 与 canonical 同名"
                        f"（products={r.get('products','')}）",
            "confidence": "medium", "status": "mergeable",
            "n_products": subs[dup]["n_products"], "source_atc": subs[dup]["atc"],
        })
    return out


# ---------------------------------------------------------------------------
# 复方成分集合审计 + 合并后模拟
# ---------------------------------------------------------------------------
def combo_audit(con: sqlite3.Connection, subs: dict, repl: dict) -> dict:
    v2s = {r[0]: r[1] for r in con.execute("SELECT variant_id, substance_id FROM variant")}
    sig_products: Counter = Counter()
    sig_markets: dict[tuple, set] = defaultdict(set)
    sig_prod_ids: dict[tuple, set] = defaultdict(set)
    for r in con.execute("""
        SELECT p.product_id, p.country, pc.variant_id
        FROM product p JOIN product_component pc ON pc.product_id=p.product_id
        ORDER BY p.product_id"""):
        sig_markets.setdefault(("__row__",), set())
        sig_products[("__row__",)] += 1
    # 上面只是占位，真正实现用一次聚合
    sig_products = Counter()
    sig_markets = defaultdict(set)
    rows = con.execute("""
        SELECT p.product_id, p.country, group_concat(pc.variant_id) vars
        FROM product p JOIN product_component pc ON pc.product_id=p.product_id
        GROUP BY p.product_id HAVING COUNT(pc.ord) >= 2""")
    for r in rows:
        sids = []
        for v in (r["vars"] or "").split(","):
            sid = v2s.get(v)
            if not sid:
                continue
            sid = repl.get(sid, sid)      # 模拟合并
            sids.append(sid)
        sig = tuple(sorted(set(sids)))
        if len(sig) < 2:
            continue
        sig_products[sig] += 1
        sig_markets[sig].add(r["country"])
    n_sets = len(sig_products)
    matched = sum(1 for s, m in sig_markets.items() if len(m) >= 2)
    prod_total = sum(sig_products.values())
    matched_products = sum(n for s, n in sig_products.items() if len(sig_markets[s]) >= 2)
    prefix_sets = [s for s in sig_products if any(
        str(x).startswith(("cn-", "mx-es-")) for x in s)]
    return {
        "combo_products": prod_total, "combo_sets": n_sets,
        "combo_sets_multi_market": matched,
        "combo_set_match_rate": round(100.0 * matched / n_sets, 2) if n_sets else 0,
        "combo_products_multi_market": matched_products,
        "combo_product_match_rate": round(100.0 * matched_products / prod_total, 2) if prod_total else 0,
        "sets_with_prefix_components": len(prefix_sets),
        "sets_with_cn_market": sum(1 for s, m in sig_markets.items() if "CN" in m),
        "sets_with_es_market": sum(1 for s, m in sig_markets.items() if "ES" in m),
        "sets_with_mx_market": sum(1 for s, m in sig_markets.items() if "MX" in m),
        "cross_market_sets_with_cn_or_es": sum(
            1 for s, m in sig_markets.items() if len(m) >= 2 and ({"CN", "ES", "MX"} & m)),
        "market_count_dist": dict(sorted(Counter(len(m) for m in sig_markets.values()).items())),
        "top_sets": [
            {"n_components": len(s), "n_products": n, "markets": sorted(sig_markets[s]),
             "substances": list(s)[:8]}
            for s, n in sig_products.most_common(15)],
    }


def substance_audit(subs: dict) -> dict:
    dist = Counter(len(s["markets"]) for s in subs.values() if s["markets"])
    with_products = sum(1 for s in subs.values() if s["markets"])
    multi = sum(1 for s in subs.values() if len(s["markets"]) >= 2)
    per_market = Counter()
    for s in subs.values():
        for m in s["markets"]:
            per_market[m] += 1
    return {
        "substances_total": len(subs), "substances_with_products": with_products,
        "market_count_dist": dict(sorted(dist.items())),
        "substances_multi_market": multi,
        "cross_market_link_rate": round(100.0 * multi / with_products, 2) if with_products else 0,
        "substances_per_market": dict(per_market),
    }


# ---------------------------------------------------------------------------
def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    con = connect_ro()
    subs = load_substances(con)
    lk = build_lookups(subs)
    who = load_who_inn()
    cima = load_cima_vtm(con)
    cn2en = load_cn2en()
    cn_map = load_cn_name_map()
    cn_alias = load_cn_aliases()
    mx_map = load_mx_inn_map()
    print(f"substance {len(subs):,} | WHO INN {who['rows']:,} | CIMA vtm 词典 {len(cima):,}"
          f" | CN2EN {len(cn2en):,} | cn_name_map {len(cn_map):,} | mx_inn_map {len(mx_map):,}")

    cands = []
    cands += cn_candidates(subs, lk, who, cn2en, cn_map, cn_alias)
    cands += es_candidates(subs, lk, who, mx_map, cima)
    cands += duplicate_candidates(subs)

    # 去重：同一 source 只保留证据优先级最高的一条
    prio = {"existing_override": 0, "who_inn": 1, "cn_old_name": 2, "cn_old_name+who_inn": 2,
            "cn_old_name+cn2en": 3, "cn_old_name+cn_name_map": 3, "cn_name_map": 4,
            "cn2en": 5, "mx_inn_map": 6, "cima_vtm": 7, "duplicate_name": 0, "atc4": 9}
    stat_prio = {"mergeable": 0, "needs_target": 1, "uncertain": 2}
    best: dict[str, dict] = {}
    for c in cands:
        key = c["source_id"]
        cur = best.get(key)
        if cur is None:
            best[key] = c
            continue
        a = (stat_prio.get(c["status"], 9), prio.get(c["evidence_type"], 9))
        b = (stat_prio.get(cur["status"], 9), prio.get(cur["evidence_type"], 9))
        if a < b:
            best[key] = c
    cands = list(best.values())

    # 盐型/立体/复方安全检查：源名带盐/酯/立体标记但目标无对应 → 降级为 uncertain
    salt_index = load_variant_salts(con)
    demoted = 0
    for c in cands:
        if c["status"] != "mergeable" or not c["target_id"]:
            continue
        # 自匹配（mx_inn_map 把西语名映射成同名英文 id）：不是合并候选
        if norm_latin(subs[c["target_id"]]["inn_en"]) == norm_latin(c["source_name"]) \
                and c["candidate_type"] == "substance_merge":
            c["status"] = "uncertain"
            c["evidence"] = (c["evidence"] + "；自匹配（目标与源同名，无需合并）")[:400]
            demoted += 1
            continue
        why = salt_mismatch(c["source_id"], c["source_name"], c["target_id"], subs, salt_index)
        # 复方/多活性线索：源名含维生素 D3、或含（Ⅰ/Ⅱ/Ⅲ）等分型，而目标名不含 → 不能当同一成分
        n = unicodedata.normalize("NFKC", c["source_name"] or "")
        tgt_name = norm_latin(subs[c["target_id"]]["inn_en"])
        if "维生素" in n or "D3" in n.upper() or "D₃" in n:
            if "vitamin" not in tgt_name:
                why = (why + "；" if why else "") + "源名含维生素/复方标记，目标非对应成分"
        if why:
            c["status"] = "uncertain"
            c["evidence"] = (c["evidence"] + "；" + why)[:400]
            demoted += 1
    print(f"盐型/立体/复方安全复检：{demoted} 条 mergeable → uncertain")

    # 复方 before/after 模拟（只应用 mergeable 单方合并）
    repl = {c["source_id"]: c["target_id"] for c in cands
            if c["status"] == "mergeable" and c["target_id"]}
    before = combo_audit(con, subs, {})
    after = combo_audit(con, subs, repl)

    # 成分级 before/after：把 source 的市场并到 target，再算跨市场链接率
    sa = substance_audit(subs)
    merged_markets = {sid: set(s["markets"]) for sid, s in subs.items()}
    for src, tgt in repl.items():
        if tgt in merged_markets:
            merged_markets[tgt] |= merged_markets.get(src, set())
    remain = [sid for sid in merged_markets if sid not in repl]
    multi_after = sum(1 for sid in remain if len(merged_markets[sid]) >= 2)
    sa["after_merge"] = {
        "substances_after": len(remain),
        "substances_multi_market": multi_after,
        "cross_market_link_rate": round(100.0 * multi_after / max(1, len(remain)), 2),
    }

    audit = {
        "generated_at": TODAY, "db": str(DB),
        "substance": sa,
        "combo_before": before,
        "combo_after_simulated": after,
        "merge_simulation": {"replacement_pairs": len(repl),
                             "combo_sets_delta": after["combo_sets_multi_market"] - before["combo_sets_multi_market"],
                             "combo_products_delta": after["combo_products_multi_market"] - before["combo_products_multi_market"]},
        "candidates_total": len(cands),
        "candidates_by_status": dict(Counter(c["status"] for c in cands)),
        "candidates_by_evidence": dict(Counter(c["evidence_type"] for c in cands)),
        "candidates_by_type": dict(Counter(c["candidate_type"] for c in cands)),
        "cn_prefix": sum(1 for c in cands if c["source_id"].startswith("cn-")),
        "mx_es_prefix": sum(1 for c in cands if c["source_id"].startswith("mx-es-")),
        "who_inn_cov": {"rows": who["rows"], "zh_terms": len(who["zh"]), "es_terms": len(who["es"])},
        "cima_terms": len(cima),
    }
    EVID.mkdir(parents=True, exist_ok=True)
    (EVID / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    with CAND.open("w", newline="", encoding="utf-8-sig") as fh:
        cols = ["candidate_type", "source_id", "source_name", "source_markets", "target_id",
                "target_name", "evidence_type", "evidence", "confidence", "status",
                "n_products", "source_atc"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(cands, key=lambda c: ({"mergeable": 0, "needs_target": 1,
                                                  "uncertain": 2}[c["status"]],
                                                 c["candidate_type"], -int(c["n_products"]))))

    print("\n=== 成分×市场 ===")
    sa = audit["substance"]
    print("有产品成分:", sa["substances_with_products"], "| 市场数分布:", sa["market_count_dist"])
    print("≥2 市场:", sa["substances_multi_market"], "| 跨市场链接率:", sa["cross_market_link_rate"], "%")
    print("\n=== 复方同集合 ===")
    print("before：复方产品", before["combo_products"], "| 集合", before["combo_sets"],
          "| 跨市场集合", before["combo_sets_multi_market"], "| 匹配率", before["combo_set_match_rate"], "%")
    print("after（模拟合并", len(repl), "对）：跨市场集合", after["combo_sets_multi_market"],
          "| 匹配率", after["combo_set_match_rate"], "%",
          "| 产品", after["combo_products_multi_market"])
    print("\n=== 候选 ===")
    print("total:", len(cands), "| status:", audit["candidates_by_status"])
    print("type:", audit["candidates_by_type"], "| cn-:", audit["cn_prefix"],
          "| mx-es-:", audit["mx_es_prefix"])
    print("evidence:", audit["candidates_by_evidence"])
    print("→", CAND.relative_to(ROOT))
    print("→", (EVID / "audit.json").relative_to(ROOT))
    print("\nmergeable 前 20（按产品数）：")
    for c in [x for x in cands if x["status"] == "mergeable"][:20]:
        print(f"  {c['source_id']:<26} {c['source_name'][:22]:<24} → {c['target_id']:<30}"
              f" [{c['evidence_type']}/{c['confidence']}] np={c['n_products']}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
