# -*- coding: utf-8 -*-
"""Phase B 候选：CJK 主名 → INN（只读 `mode=ro`，不写库、不合并身份）。

背景
----
`substance.name_lang='zh'` 的 1,791 条成分，主名（`inn_en` 字段）与 `inn_zh` 都是中文，
ATC 全部只到第 4 级（5 位，如 `A02BX`）。本脚本为每一条产出「英文 INN 候选」，供 Phase B
后续人工/规则定案使用；定不了案的一律丢弃并计数，**不猜、不翻译、不音译、不改名**。

证据渠道
--------
按任务口径（①-④）在前，另有三条本地名字反查（否则 ② 的「中文名对得上」无从判定）：

  ① alias_group    `data/substance_aliases.csv` 同物异名组（`lib/aliases.py`）
  ② atc4_unique    同 ATC 前 5 位内唯一英文成分（结构证据；名字对不上时只记 low，不定案）
  ③ atc5_exact     同 ATC 第 5 级同码（7 位）——池内 ATC 全为 5 位，本渠道 0 命中，实现保留
  ④ nickname_term  `nickname` / `drug_term`（`alias_all` 视图）精确匹配
  db_inn_zh       库内英文成分的 `inn_zh` 反查（精确/归一/剥盐后 base 三档）
  cn_override     `data/cn_inn_overrides.csv` + 仓库既有 `CN2EN` 表 / WHO INN 中文名 /
                  中文旧称表 / `cn_name_map.json`（经 `etl/build_cross_market_candidates.py`
                  的加载器复用，不另起一套）
  wikidata_cache  `data/raw/wikidata/atc_p267.json` 本地缓存（zh label → en label + P267 ATC）

置信度
------
  high    唯一候选 + ATC 前 5 位同码 + 盐/酯/立体标记一致 + 有名字证据（非纯结构推断）
  medium  唯一候选 + 有名字证据，但 (a) 盐型只到 base / 候选多带盐，或 (b) ATC 只到前 4 位，
          或 (c) 候选名带剂型词（非单成分 INN 写法）
  low     不定案：≥2 个候选，或只有结构证据（ATC4 唯一，中文名对不上）
  none    判不了 → 丢弃并计数（丢弃原因写在「理由」列）

判定顺序
--------
  1. 复方/多成分（`cn_inn_overrides status=combination`，或候选名含 `/`、`+`）→ 丢弃
  2. 立体标记（右旋/左旋）在候选名里找不到 → 丢弃（不同立体异构体不是同一身份）
  3. ATC 冲突（前 4 位都不同）→ 丢弃；候选无 ATC 可校验 → 丢弃
  4. 盐/酯标记：`partial`/`diff` → 丢弃；`base_only`/`extra` → 最多 medium
  5. 唯一候选按上述给 high/medium；多候选只列不定案（low）

输出
----
  `data/sources/phaseb-candidates-20261031.csv`：1,791 行（池内每条一行，含丢弃行）
  终端 / `--summary` JSON：分类计数

边界：不改 `data/drugs.db`、不改 schema、不合并身份；只做身份对应候选，不给用药建议。

用法：
    & $py db/phaseb_candidates.py
    & $py db/phaseb_candidates.py --summary .tmp/phaseb/summary.json --show 20
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
DEFAULT_OUT = ROOT / "data" / "sources" / "phaseb-candidates-20261031.csv"
CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "etl") not in sys.path:
    sys.path.insert(0, str(ROOT / "etl"))

from lib.aliases import load as load_aliases  # noqa: E402  （异名表，task-141）

# 复用既有中文名归一 / 中文盐型词表 / 本地映射表加载器（不另起一套）
import build_cross_market_candidates as xm  # noqa: E402
from normalize_name import _FORM_TOKENS as FORM_TOKENS  # noqa: E402  （剂型词：判断候选名是否单成分）
from normalize_salts import SALT_ALIASES  # noqa: E402  （salt_base_fraction.csv 的 salt_code 词表）

CSV_FIELDS = ["substance_id", "inn_en(当前)", "inn_zh", "atc",
              "候选INN", "候选substance_id", "证据", "置信度", "理由"]

NAME_SOURCES = {
    "alias_group", "db_inn_zh", "db_inn_zh_base", "cn_inn_overrides", "cn2en",
    "who_inn", "cn_old_name", "cn_name_map", "nickname/drug_term", "wikidata_cache",
}
STRUCT_SOURCES = {"atc4_unique", "atc5_exact"}

# 中文盐/酯/离子/立体标记 → 英文标记 token（复用 etl/build_cross_market_candidates.py 的词表）
ZH_MARKERS: dict[str, str] = {**xm.ZH_SALT_EN, **xm.ZH_SALT_CATION, **xm.ZH_STEREO}
# 补：上表没有的常见酯（中文名带酯基、却映射到母体 INN 时，要能识别出「酯被丢掉」）
ZH_MARKERS.update({
    "苯丙酸": "phenylpropionate", "庚酸": "enanthate", "癸酸": "decanoate",
    "十一酸": "undecanoate", "环戊丙酸": "cypionate", "糠酸": "furoate",
    "醋丙酸": "aceponate", "丁丙酸": "buteprate", "特戊酸": "pivalate",
    "二丙酸": "dipropionate", "戊酸": "valerate", "丙酸": "propionate",
})

# 盐型 token 的等价写法（不同市场/药典写法指向同一盐型）
SALT_ALIAS = {"sulphate": "sulfate", "sulphide": "sulfide", "sulphite": "sulfite",
              "natrium": "sodium", "kalium": "potassium", "sodico": "sodium",
              "sodica": "sodium", "potasico": "potassium", "calcico": "calcium"}

# 任意写法 → canonical salt_code（hcl → hydrochloride、sulfato → sulfate…）
TOKEN_CODE: dict[str, str] = {code: code for code in SALT_ALIASES}
for _code, _aliases in SALT_ALIASES.items():
    for _a in _aliases:
        TOKEN_CODE.setdefault(xm.norm_latin(_a), _code)

# 立体标记：候选名里找不到即判为不同异构体（不是同一身份）
STEREO_STRICT = {"dex", "levo"}

# 只作说明、不算「判不了」的原因
INFO_CATS = {"异名组收敛", "盐型收敛"}


def norm_token(tok: str) -> str:
    tok = xm.norm_latin(tok)
    return SALT_ALIAS.get(tok) or TOKEN_CODE.get(tok) or tok


MARKER_VOCAB: set[str] = {norm_token(v) for v in ZH_MARKERS.values()}
MARKER_VOCAB |= {norm_token(k) for k in SALT_ALIASES}
MARKER_VOCAB |= {norm_token(a) for aliases in SALT_ALIASES.values() for a in aliases}
MARKER_VOCAB |= set(FORM_TOKENS)


def zh_markers(zh_name: str) -> tuple[set[str], set[str]]:
    """中文名里的盐/酯/离子标记与立体标记 → (markers, stereo)。长词优先，避免重复计数。"""
    s = unicodedata.normalize("NFKC", zh_name or "")
    salt: set[str] = set()
    stereo: set[str] = set()
    for zh in sorted(ZH_MARKERS, key=len, reverse=True):
        if zh and zh in s:
            tok = norm_token(ZH_MARKERS[zh])
            if tok in STEREO_STRICT or tok == "racemic":
                stereo.add(tok)
            else:
                salt.add(tok)
            s = s.replace(zh, "\u0000")
    return salt, stereo


def split_markers(inn: str, sid: str,
                  variant_markers: dict[str, set[str]]) -> tuple[set[str], set[str]]:
    """候选的 (INN 名里的标记, 该 substance 各 variant 的盐/酯标记)。"""
    toks = {norm_token(t) for t in xm.norm_latin(inn).split()}
    named = {t for t in toks if t in MARKER_VOCAB and t not in FORM_TOKENS}
    return named, set(variant_markers.get(sid, set()))


def marker_status(pool: set[str], named: set[str], variants: set[str]) -> str:
    """盐/酯标记比对：same / base_only / extra / partial / diff。

    - 候选 INN 名里带标记 → 直接按名字比（不同酸根/酯 = 不同身份）。
    - 候选是母体名（名字里无标记）→ 只问「它的 variant 里有没有中文名那个盐/酯」：
      有 → same；没有 → base_only（盐型要补到 `variant.salt`，Phase B 落库时处理）。
    """
    if named:
        if named == pool:
            return "same"
        if pool & named:
            return "partial"    # 只对上部分标记（很可能是另一个盐/酯）
        if not pool:
            return "extra"      # 候选名带盐/酯、中文名没带
        return "diff"           # 两边盐/酯完全不同
    if not pool:
        return "same"           # 中文名和候选名都不带盐/酯 → 同是母体
    return "same" if pool <= variants else "base_only"


def atc_level(pool_atc: str, cand_atc: str) -> str:
    """池内 ATC 与候选 ATC：L5 同码 / L4 前 5 位同 / L3 前 4 位同 / conflict / unknown。"""
    p = (pool_atc or "").strip().upper()
    c = (cand_atc or "").strip().upper()
    if not p or not c:
        return "unknown"
    if len(p) >= 7 and p[:7] == c[:7]:
        return "L5"
    if p[:5] == c[:5]:
        return "L4"
    if p[:4] == c[:4]:
        return "L3"
    return "conflict"


def is_combo_name(inn: str) -> bool:
    """候选名本身是不是复方写法（不是单一 INN）。"""
    low = (inn or "").lower()
    return "/" in low or "+" in low or " and " in low or "、" in (inn or "") or "；" in (inn or "")


def is_form_like(inn: str) -> bool:
    """候选名里带剂型词（syrup / tablets / solution…）→ 不是单成分 INN 写法。"""
    return bool(set(xm.norm_latin(inn).split()) & FORM_TOKENS)


def sid_of(inn: str, en_norm: dict[str, str], en_slug: dict[str, str]) -> str:
    n = xm.norm_latin(inn)
    if not n:
        return ""
    return en_norm.get(n) or en_slug.get(xm.slug(n)) or ""


@dataclass
class Cand:
    """一个候选 INN（同一 INN 的多条证据合并为一条）。"""

    inn: str
    sid: str = ""
    atc: str = ""
    sources: dict[str, str] = field(default_factory=dict)   # 来源标签 → 说明

    @property
    def has_name_evidence(self) -> bool:
        return bool(set(self.sources) & NAME_SOURCES)

    @property
    def structural_only(self) -> bool:
        return not self.has_name_evidence


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase B：CJK 主名 → INN 候选（只读）")
    ap.add_argument("--csv", default=str(DEFAULT_OUT), help="输出 CSV")
    ap.add_argument("--summary", default="", help="可选：分类计数写 JSON")
    ap.add_argument("--show", type=int, default=12, help="终端打印多少条带候选的行")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    if not DB.exists():
        print(f"[FAIL] 找不到库：{DB}")
        return 1

    # ---- 只读开库 --------------------------------------------------------
    uri = "file:" + str(DB.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=120)
    con.row_factory = sqlite3.Row
    subs: dict[str, dict] = {}
    for r in con.execute("SELECT substance_id, inn_en, inn_zh, atc, name_lang FROM substance"):
        subs[r["substance_id"]] = {
            "sid": r["substance_id"], "inn_en": r["inn_en"] or "", "inn_zh": r["inn_zh"] or "",
            "atc": (r["atc"] or "").strip(), "name_lang": r["name_lang"] or "",
        }
    variant_markers: dict[str, set[str]] = defaultdict(set)
    for sid, salt, ester in con.execute("SELECT substance_id, salt, ester FROM variant"):
        for raw in (salt or "", ester or ""):
            for tok in xm.norm_latin(raw).split():
                tok = norm_token(tok)
                if tok in MARKER_VOCAB:
                    variant_markers[sid].add(tok)
    alias_rows = [dict(r) for r in con.execute(
        "SELECT origin, substance_id, alias, alias_norm FROM alias_all WHERE substance_id IS NOT NULL")]
    con.close()

    pool = [s for s in subs.values() if s["name_lang"] == "zh"]
    en_subs = [s for s in subs.values()
               if s["name_lang"] == "en" and s["sid"] and not CJK.search(s["inn_en"])]

    # 英文成分索引：全名 / slug / ATC4 组 / 中文名（三级键）
    en_norm: dict[str, str] = {}
    en_slug: dict[str, str] = {}
    en_atc4: dict[str, list[str]] = defaultdict(list)
    zh_by_key: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for s in en_subs:
        n = xm.norm_latin(s["inn_en"])
        if n:
            en_norm.setdefault(n, s["sid"])
            en_slug.setdefault(xm.slug(n), s["sid"])
        if len(s["atc"]) >= 5:
            en_atc4[s["atc"][:5]].append(s["sid"])
        if s["inn_zh"]:
            keys = xm.zh_keys(s["inn_zh"])
            kinds = ("exact", "norm", "base") if len(keys) == 3 else ("exact", "norm")
            for k, kind in zip(keys, kinds):
                zh_by_key[k].append((s["sid"], kind))

    # ④ nickname / drug_term：别名（原写法 + alias_norm）→ 英文成分
    alias_by_key: dict[str, list[str]] = defaultdict(list)
    for a in alias_rows:
        sid = a["substance_id"]
        if not sid or sid not in subs or subs[sid]["name_lang"] != "en":
            continue
        for raw in (a.get("alias") or "", a.get("alias_norm") or ""):
            for k in xm.zh_keys(raw):
                alias_by_key[k].append(sid)

    # ① 异名表；本地映射表（复用既有加载函数）
    alias_map = load_aliases()
    cn2en = xm.load_cn2en()
    cn_name_map = xm.load_cn_name_map()
    cn_aliases = xm.load_cn_aliases()
    who = xm.load_who_inn()
    cn_ovr = {r["cn_substance_id"]: r for r in xm.read_csv(xm.CN_OVR) if r.get("cn_substance_id")}

    # wikidata 本地缓存：zh label → en label，en label → P267 ATC
    wd_zh: dict[str, list[str]] = defaultdict(list)
    wd_atc: dict[str, str] = {}
    wd_path = ROOT / "data" / "raw" / "wikidata" / "atc_p267.json"
    if wd_path.exists():
        wd = json.loads(wd_path.read_text(encoding="utf-8"))
        by_qid: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        atc_q: dict[str, str] = {}
        for r in wd.get("rows") or []:
            qid, lang, label = r.get("drug"), (r.get("lang") or "").lower(), (r.get("label") or "").strip()
            if not qid or not label:
                continue
            by_qid[qid][lang].append(label)
            if r.get("atc"):
                atc_q[qid] = (r["atc"] or "").strip()
        for qid, labels in by_qid.items():
            atc = atc_q.get(qid, "")
            for en in labels.get("en") or []:
                if en and not CJK.search(en) and atc:
                    wd_atc.setdefault(xm.norm_latin(en), atc)
            for zh in labels.get("zh") or []:
                for en in labels.get("en") or []:
                    if en and not CJK.search(en):
                        for k in xm.zh_keys(zh):
                            wd_zh[k].append(en)

    # ATC 第 5 级（7 位）→ 库内英文成分：用于把「写法对不上但 ATC 同码」的候选归到已有记录
    en_atc5: dict[str, list[str]] = defaultdict(list)
    for s in en_subs:
        if len(s["atc"]) >= 7:
            en_atc5[s["atc"][:7]].append(s["sid"])

    # ---- 逐条池内成分 ----------------------------------------------------
    rows: list[dict] = []
    stat_tier = Counter()
    stat_src = Counter()
    stat_drop = Counter()
    stat_low_kind = Counter()
    src_by_tier: dict[str, Counter] = defaultdict(Counter)

    for s in pool:
        name = (s["inn_zh"] or s["inn_en"]).strip()
        pool_atc = s["atc"]
        pool_markers, stereo = zh_markers(name)
        keys = xm.zh_keys(name)
        ovr = cn_ovr.get(s["sid"]) or {}
        cands: dict[str, Cand] = {}
        notes: list[tuple[str, str]] = []       # (类别, 说明)：被拒绝/收敛掉的候选
        combo = (ovr.get("status") or "").strip() == "combination"

        def add(inn: str, src: str, note: str = "") -> None:
            inn = (inn or "").strip()
            if not inn or CJK.search(inn) or is_combo_name(inn):
                return
            key = xm.norm_latin(inn)
            if not key:
                return
            c = cands.get(key)
            if c is None:
                sid = sid_of(inn, en_norm, en_slug)
                c = Cand(inn=subs[sid]["inn_en"] if sid else inn, sid=sid)
                c.atc = subs[sid]["atc"] if sid else wd_atc.get(key, "")
                if not sid:
                    # ③ 候选写法对不上库内记录时，用它的 ATC 第 5 级同码（7 位）归到已有成分
                    atc5 = wd_atc.get(key, "")
                    hits = en_atc5.get(atc5[:7], []) if len(atc5) >= 7 else []
                    if len(hits) == 1:
                        sid = hits[0]
                        c.sid = sid
                        c.atc = subs[sid]["atc"]
                        c.inn = inn          # 候选写法保留来源原样，库内记录见 候选substance_id
                        c.sources.setdefault(
                            "atc5_exact",
                            f"候选写法 {inn} 按 ATC 第 5 级同码 {atc5[:7]} 归到库内 "
                            f"{subs[sid]['inn_en']}")
                cands[key] = c
            c.sources.setdefault(src, note)

        if combo:
            notes.append(("复方/多成分", "cn_inn_overrides status=combination → 不映射"))
        else:
            # 库内英文成分的 inn_zh 反查（exact / norm / 剥盐 base）
            for k in keys:
                for sid, kind in zh_by_key.get(k, []):
                    add(subs[sid]["inn_en"],
                        "db_inn_zh" if kind in ("exact", "norm") else "db_inn_zh_base",
                        f"库内 inn_zh={subs[sid]['inn_zh']}（{kind}）")
            # ④ nickname / drug_term 精确匹配
            for k in keys:
                for sid in alias_by_key.get(k, []):
                    add(subs[sid]["inn_en"], "nickname/drug_term", "alias_all 精确匹配")
            # ① 异名表：池内名字命中组名
            for gid in alias_map.lookup_name(name):
                if gid in subs and subs[gid]["name_lang"] == "en":
                    add(subs[gid]["inn_en"], "alias_group", f"异名表组 {alias_map.canonical(gid)}")
            # cn_override：cn_inn_overrides / CN2EN / WHO / 中文旧称 / cn_name_map
            if (ovr.get("en_inn") or "").strip():
                add(ovr["en_inn"], "cn_inn_overrides",
                    f"status={ovr.get('status')} confidence={ovr.get('confidence')}")
            for k in keys:
                if k in cn2en:
                    add(cn2en[k], "cn2en", f"CN2EN 表 {k}")
                if k in who["zh"]:
                    add(who["zh"][k], "who_inn", f"WHO INN 中文名 {k}")
                if k in cn_name_map:
                    add(cn_name_map[k], "cn_name_map", f"cn_name_map {k}")
            alias_target = cn_aliases.get(xm.norm_zh(name))
            if alias_target:
                for k in xm.zh_keys(alias_target):
                    if k in cn2en:
                        add(cn2en[k], "cn_old_name", f"旧称→{alias_target}→CN2EN")
                        break
                    if k in who["zh"]:
                        add(who["zh"][k], "cn_old_name", f"旧称→{alias_target}→WHO")
                        break
            # wikidata 本地缓存
            for k in keys:
                for en in wd_zh.get(k, []):
                    add(en, "wikidata_cache", f"Wikidata 缓存 zh→en {en}")
            # ③ ATC 第 5 级同码（池内全 5 位 → 实际 0 命中；ATC 补到 7 位后可用）
            if len(pool_atc) >= 7:
                for sid in en_atc4.get(pool_atc[:7], []):
                    if subs[sid]["atc"][:7] == pool_atc[:7]:
                        add(subs[sid]["inn_en"], "atc5_exact", "ATC 第 5 级同码")

        # 同一 substance 的不同写法（异名表同组）合并成一个候选
        seen_group: dict[str, str] = {}
        for key in list(cands):
            c = cands[key]
            if not c.sid:
                continue
            gid = alias_map.canonical(c.sid)
            if gid in seen_group:
                keep = cands[seen_group[gid]]
                for src, note in c.sources.items():
                    keep.sources.setdefault(src, note)
                keep.sources.setdefault("alias_group", f"同组异名 {c.inn}")
                notes.append(("异名组收敛", f"{c.inn} 与 {keep.inn} 是同一成分的不同写法"))
                cands.pop(key)
            else:
                seen_group[gid] = key

        # ---- 逐个候选做 复方 / 立体标记 / ATC / 盐酯 校验 -----------------
        evaluated: list[tuple[Cand, str, str]] = []     # (候选, atc_level, marker_status)
        for c in cands.values():
            lvl = atc_level(pool_atc, c.atc)
            named, variants = split_markers(c.inn, c.sid, variant_markers)
            st = marker_status(pool_markers, named, variants)
            missing_stereo = sorted(m for m in stereo
                                    if m in STEREO_STRICT and m not in xm.norm_latin(c.inn))
            if is_combo_name(c.inn):
                notes.append(("复方/多成分", f"候选 {c.inn} 是复方写法"))
                continue
            if missing_stereo:
                notes.append(("立体异构", f"候选 {c.inn} 缺立体标记 {'/'.join(missing_stereo)}"))
                continue
            if lvl == "conflict":
                notes.append(("ATC 冲突", f"候选 {c.inn} ATC {c.atc} vs 池内 {pool_atc}"))
                continue
            if lvl == "unknown":
                why = "在库但无 ATC" if c.sid else "不在库且缓存无 ATC 出处"
                notes.append(("ATC 无法校验", f"候选 {c.inn} {why}"))
                continue
            if st in ("partial", "diff"):
                notes.append(("盐/酯不一致",
                              f"候选 {c.inn} 标记 {sorted(named or variants)} vs 中文名 {sorted(pool_markers)}"))
                continue
            evaluated.append((c, lvl, st))

        # 池内带盐/酯时，多候选中先按标记一致收敛（同一 base 的不同盐是不同身份）
        if len(evaluated) > 1 and pool_markers:
            same = [e for e in evaluated if e[2] == "same"]
            if len(same) == 1:
                notes.append(("盐型收敛", f"多候选中按盐/酯一致收敛到 {same[0][0].inn}"))
                evaluated = same

        row = {"substance_id": s["sid"], "inn_en(当前)": s["inn_en"], "inn_zh": s["inn_zh"],
               "atc": pool_atc, "候选INN": "", "候选substance_id": "", "证据": "",
               "置信度": "none", "理由": ""}

        if not evaluated and not combo and not notes:
            # ② 结构线索：同 ATC 前 5 位内唯一英文成分（中文名对不上 → 不猜，只留线索供下一阶段核）
            group = [sid for sid in en_atc4.get(pool_atc[:5], []) if sid in subs]
            if len(group) == 1:
                c_inn = subs[group[0]]["inn_en"]
                named, variants = split_markers(c_inn, group[0], variant_markers)
                st = marker_status(pool_markers, named, variants)
                missing_stereo = sorted(m for m in stereo
                                        if m in STEREO_STRICT and m not in xm.norm_latin(c_inn))
                if st in ("partial", "diff"):
                    notes.append(("盐/酯不一致",
                                  f"ATC4 唯一成分 {c_inn} 标记 {sorted(named or variants)} "
                                  f"vs 中文名 {sorted(pool_markers)}"))
                elif missing_stereo:
                    notes.append(("立体异构", f"ATC4 唯一成分 {c_inn} 缺立体标记"))
                else:
                    notes.append(("仅 ATC4 唯一",
                                  f"ATC 前 5 位 {pool_atc[:5]} 组内唯一英文成分 {c_inn}，"
                                  f"但中文名对不上（不猜，未定案）"))
            elif group:
                notes.append(("无名字证据",
                              f"无本地名字证据；ATC 前 5 位 {pool_atc[:5]} 组内英文成分 {len(group)} 个"))
            else:
                notes.append(("无名字证据",
                              f"无本地名字证据；ATC 前 5 位 {pool_atc[:5]} 组内无英文成分"))

        if not evaluated:
            if not notes:
                notes.append(("无名字证据", "无本地名字证据"))
            rejects = [(cat, text) for cat, text in notes if cat not in INFO_CATS]
            cat, _text = (rejects or notes)[0]
            texts = [t for _c, t in notes]
            row["理由"] = f"丢弃[{cat}]：" + "；".join(texts[:3]) + (
                f"（另有 {len(texts) - 3} 条线索）" if len(texts) > 3 else "")
            stat_drop[cat] += 1
            stat_tier["none"] += 1
            rows.append(row)
            continue

        if len(evaluated) > 1:
            evaluated.sort(key=lambda e: (e[1] != "L4", e[0].sid == "", e[0].inn))
            inns = [e[0].inn for e in evaluated]
            sids = [e[0].sid for e in evaluated if e[0].sid]
            srcs = sorted({k for e in evaluated for k in e[0].sources})
            row.update({
                "候选INN": " | ".join(inns),
                "候选substance_id": " | ".join(sids),
                "证据": "; ".join(srcs),
                "置信度": "low",
                "理由": "不定案：{} 个候选（ATC {}；盐/酯 {}）".format(
                    len(evaluated), pool_atc,
                    "/".join(f"{e[0].inn}:{e[2]}" for e in evaluated)),
            })
            for src in srcs:
                stat_src[src] += 1
                src_by_tier["low"][src] += 1
            stat_low_kind["多候选"] += 1
            stat_tier["low"] += 1
            rows.append(row)
            continue

        c, lvl, st = evaluated[0]
        if st == "same" and lvl in ("L4", "L5") and not is_form_like(c.inn):
            tier = "high"
        else:
            tier = "medium"

        bits = [f"ATC {pool_atc} vs {c.atc or '—'} → {lvl}", f"盐/酯 {st}"]
        if is_form_like(c.inn):
            bits.append("候选名含剂型词，非单成分 INN 写法")
        if not c.sid:
            bits.append("候选 INN 不在库（后续需新增 substance）")
        for _cat, _text in notes:
            bits.append(_text)
        row.update({
            "候选INN": c.inn,
            "候选substance_id": c.sid,
            "证据": "; ".join(sorted(c.sources)),
            "置信度": tier,
            "理由": "；".join(bits),
        })
        for src in c.sources:
            stat_src[src] += 1
            src_by_tier[tier][src] += 1
        stat_tier[tier] += 1
        rows.append(row)

    # ---- 输出 ------------------------------------------------------------
    out = Path(args.csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)

    summary = {
        "pool_total": len(pool),
        "csv_rows": len(rows),
        "tier": {k: stat_tier.get(k, 0) for k in ("high", "medium", "low", "none")},
        "low_kind": dict(stat_low_kind),
        "sources": dict(stat_src),
        "sources_by_tier": {k: dict(v) for k, v in src_by_tier.items()},
        "drop_reasons": dict(stat_drop),
        "en_substances": len(en_subs),
        "pool_atc_len": dict(Counter(len(s["atc"]) for s in pool)),
    }
    if args.summary:
        sp = Path(args.summary)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    if not args.quiet:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(f"池内 CJK 主名  : {len(pool)}")
        print(f"CSV             : {out}  rows={len(rows)}")
        print("置信度          : " + " / ".join(f"{k}={summary['tier'][k]}"
                                              for k in ("high", "medium", "low", "none")))
        print("low 细分        : " + " / ".join(f"{k}={v}" for k, v in stat_low_kind.most_common()))
        print("证据渠道        : " + " / ".join(f"{k}={v}" for k, v in sorted(stat_src.items())))
        print("丢弃原因        : " + " / ".join(f"{k}={v}" for k, v in stat_drop.most_common()))
        if args.show:
            print("\n-- 带候选样例 --")
            for r in [x for x in rows if x["置信度"] in ("high", "medium", "low")][: args.show]:
                print(f"  [{r['置信度']:<6}] {r['inn_en(当前)']:<18} {r['atc']:<6} -> "
                      f"{r['候选INN']:<28} {r['候选substance_id']:<24} {r['证据']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
