"""剂型 / 规格 / 释放机制 / 包装 四类字段的一致性审计（只读，可复跑）。

回答的问题是：「来源原文（`product.dosage_form` / `pack` / 成分强度）与归一化字段
（`form_base` / `release` / `strength_*`）自相矛盾」的记录到底有多少、集中在哪。

这不是一次性的排查脚本，而是一张**可复跑的检查表**：七条规则、每条给条数 / 样例 /
source 与市场分布 / 建议修法。规则判据写在 `FAMILIES` 与各 `rule_*` 函数里，
改判据就改这里，不要在报告里手写结论。

七条规则
--------
R1  剂型族 × form_base 矩阵：原文剂型关键词命中哪一族、当前被归成什么。
    判定分四档（见 `VERDICT_*`）：
      ok        原文族与 form_base 相符
      coarse    同族同相态的粗粒度（滴眼剂→liquid），不算错，可选细化
      gap       子类有实质差异但没有对应枚举（泡腾片→tablet、贴片剂→tablet），
                **建议新增 form_base 取值 + 归一化规则**
      conflict  跨族 / 跨相态 / 跨给药途径的硬矛盾（`injection, solution`→liquid、
                眼膏剂→liquid、颗粒剂→tablet），**这一档才是必须修的错**
      unmapped  form_base 为空 / unknown / other，或回退成了原文整串（归一化没命中）
R2  归一化回退：form_base 直接等于原文、或长度异常，按 source 统计 Top 值。
R3  释放机制：原文有缓释/控释/肠溶… 但 `release='none'`；反向 `release!='none'`
    但原文没有任何释放词。按市场分组。
R4  规格：值为空 / 0 / 负 / 量级离谱 / 单位缺失 / 同成分同国家 g 与 mg 并存 /
    液体缺 per_volume / 复方跨单位 / 无成分行的产品。
R5  包装：pack 与剂型矛盾（液体写「10片/盒」、片剂只写「100 mL」）、pack 只有数字
    没有单位、pack 空值率按市场。
R6  重复身份：同国家 + 同成分组合 + 同强度 + 同 form_base + 同 pack 的多行。
R7  空值族：form_base 空 / unknown / other 的条数（按市场、按 source）与 Top 30 原文。

只读：`file:data/drugs.db?mode=ro`，不写库、不建站、不改任何文件（除 --json 输出）。

用法：
    & $py db/consistency_audit_form.py
    & $py db/consistency_audit_form.py --json .tmp/form-audit.json --top 10
    & $py db/consistency_audit_form.py --only R1,R3
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"

# 判定档位（R1）
VERDICT_OK = "ok"
VERDICT_COARSE = "coarse"
VERDICT_GAP = "gap"
VERDICT_CONFLICT = "conflict"
VERDICT_UNMAPPED = "unmapped"

# 修法归类（每条规则四选一）
FIX_RULE = "归一化规则"      # 加进 etl 的 form_base_of / release_of 一类纯函数，可单测
FIX_MIGRATE = "迁移脚本"     # 需要一次性 UPDATE 存量行（幂等脚本 + 前后计数）
FIX_DISPLAY = "显示层"       # 数据不动，站点 / 检索按规则组合展示
FIX_SOURCE = "来源本身"      # 来源就没给，改不了；如实标注并计数


@dataclass(frozen=True)
class Family:
    """一个剂型族（矩阵的一行）。

    匹配顺序 = `FAMILIES` 列表顺序（越具体越靠前），命中即停。
    `group` 只用于矩阵聚合：同一族可以有多个细分条目（眼膏 / 滴眼）。
    """

    fam_id: str
    group: str
    zh: str
    patterns: tuple[re.Pattern[str], ...]
    ok: frozenset[str] = frozenset()
    coarse: frozenset[str] = frozenset()
    gap: frozenset[str] = frozenset()
    target: str | None = None          # 建议新增的 form_base 取值（gap 档的修法落点）


def _pat(*pairs: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p) for p in pairs)


# 顺序即优先级：具体子类 → 给药途径 → 粗剂型。
FAMILIES: tuple[Family, ...] = (
    Family("kit", "kit", "试剂盒 / 放射性药盒", _pat(
        r"\bkit\b", r"\bkits\b", r"试剂盒", r"試劑盒", r"radiopharmaceutical preparation",
        r"诊断试剂", r"診斷試劑", r"test kit", r"\bkit for\b", r"radiof[aá]rmac"),
        ok=frozenset({"kit", "radiofarmaco"}), gap=frozenset({"powder", "liquid", "injection"}),
        target="kit"),
    Family("implant", "implant", "植入剂 / 宫内·阴道装置", _pat(
        r"\bimplant", r"implante", r"植入", r"intrauterine", r"\biud\b", r"vaginal ring",
        r"vaginal delivery system", r"阴道环", r"陰道避孕環", r"宫内释放", r"宮內",
        r"避孕环", r"避孕環", r"dispositivo intrauterino", r"dispositivo vaginal"),
        ok=frozenset({"implant"}), coarse=frozenset({"injection", "other"}),
        gap=frozenset({"other", "device"}), target="implant"),
    Family("effervescent", "effervescent", "泡腾（片/颗粒）", _pat(
        r"effervescen", r"efervescen", r"泡腾", r"泡騰", r"發泡", r"发泡", r"fizzy"),
        ok=frozenset(), coarse=frozenset(), gap=frozenset({"powder"}),
        target="effervescent"),
    Family("chewable", "chewable", "咀嚼（片/胶）", _pat(
        r"chewable", r"chewing", r"咀嚼", r"口嚼", r"medicated chewing",
        r"masticable", r"masticables", r"\bchicle", r"goma masticable"),
        ok=frozenset(), coarse=frozenset(),
        gap=frozenset({"tablet", "gum", "gum, chewing"}),
        target="chewable"),
    Family("orodispersible", "orodispersible", "口崩 / 口溶（膜/片）", _pat(
        r"orodispers", r"disintegrating", r"lyophilisat", r"口崩", r"口腔崩",
        r"口溶", r"\bwafer", r"sublingual film", r"buccal film", r"口頰溶片", r"口颊溶片",
        r"bucodispers", r"liotab", r"dispersable"),
        ok=frozenset(), coarse=frozenset(), gap=frozenset({"tablet", "film"}),
        target="orodispersible"),
    Family("enteric", "enteric", "肠溶 / 胃溶 resistant", _pat(
        r"enteric", r"gastro-resist", r"gastro resist", r"gastrorresisten",
        r"肠溶", r"腸溶", r"resistente al jugo", r"capa ent[eé]rica", r"ent[eé]rica"),
        ok=frozenset({"tablet", "capsule", "powder", "pellet"}), gap=frozenset()),
    Family("ophth_ointment", "ophthalmic", "眼膏", _pat(
        r"眼膏", r"點眼膏", r"点眼膏", r"eye ointment", r"ophthalmic ointment",
        r"ocular ointment", r"pomada oft[aá]lm", r"ung[uü]ento oft[aá]lm"),
        ok=frozenset({"topical"}), gap=frozenset(), target="ophthalmic"),
    Family("ophthalmic", "ophthalmic", "眼用滴剂 / 眼用制剂", _pat(
        r"ophthalmic", r"ocular", r"intravitreal", r"\beye\b", r"eye drop",
        r"滴眼", r"点眼", r"點眼", r"眼用", r"眼膏", r"colirio", r"oft[aá]lm", r"ocular"),
        ok=frozenset({"liquid", "topical"}), coarse=frozenset(), gap=frozenset(),
        target="ophthalmic"),
    Family("otic", "otic", "耳用滴剂", _pat(
        r"\bear\b", r"ear drop", r"滴耳", r"點耳", r"耳用", r"auricular",
        r"\b[oó]tic[oa]s?\b", r"uso [oó]tico"),
        ok=frozenset({"liquid", "topical"}), gap=frozenset(), target="otic"),
    Family("nasal", "nasal", "鼻用", _pat(
        r"\bnasal\b", r"滴鼻", r"點鼻", r"鼻用", r"鼻喷", r"鼻內", r"鼻内", r"\bnostril",
        r"uso nasal"),
        ok=frozenset({"liquid", "topical", "inhalation", "nasal"}), gap=frozenset(),
        target="nasal"),
    Family("topical_aerosol", "topical", "外用气雾 / 泡沫（aerosol, spray/foam）", _pat(
        r"aerosol[^a-z]*(spray|foam|lotion)", r"aerosol\s*\(foam\)", r"aerosol.*foam"),
        ok=frozenset({"topical", "liquid"}), coarse=frozenset({"inhalation"}),
        gap=frozenset(), target="topical"),
    Family("inhalation", "inhalation", "吸入（气雾/粉雾/雾化）", _pat(
        r"inhal", r"nebul", r"spacer", r"aerosol", r"吸入", r"气雾", r"氣化噴霧", r"气化喷雾",
        r"雾化", r"霧化", r"粉雾", r"粉霧", r"口腔吸入", r"respimat", r"turbuhaler",
        r"diskus", r"rotahaler", r"accuhaler", r"inhalaci[oó]n", r"pulverizaci[oó]n"),
        ok=frozenset({"inhalation", "inhalant"}),
        coarse=frozenset({"liquid", "powder", "capsule"}),
        gap=frozenset({"gas"})),
    Family("injection", "injection", "注射（针/瓶/安瓿/预充）", _pat(
        r"injection", r"injectable", r"\bvial", r"ampoule", r"\bampul", r"prefilled",
        r"pre-filled", r"syringe", r"infusion", r"intravenous", r"parenteral",
        r"注射", r"静脉", r"靜脈", r"输注", r"輸注", r"点滴", r"滴注", r"粉针", r"粉針",
        r"inyect", r"ampolleta", r"intravesical", r"perfusi[oó]n"),
        ok=frozenset({"injection"}), gap=frozenset({"powder", "liquid_ampoule"}),
        target="injection"),
    Family("gas", "gas", "医用气体 / 气瓶", _pat(
        r"\bgas\b", r"medicinal gas", r"\boxygen\b", r"nitrous oxide", r"helium",
        r"carbon dioxide", r"气体", r"氣體", r"氧气", r"氧氣", r"cylinders", r"气瓶",
        r"gas medicinal"),
        ok=frozenset({"gas"}), coarse=frozenset({"liquid", "inhalant", "inhalation"}),
        target="gas"),
    Family("suppository", "suppository", "栓剂 / 直肠 / 阴道用", _pat(
        r"suppositor", r"pessar", r"enema", r"rectal", r"vaginal", r"栓", r"灌肠",
        r"浣腸", r"直肠", r"直腸", r"阴道", r"陰道", r"尿道", r"supositori",
        r"[oó]vulos?", r"uretral"),
        ok=frozenset({"suppository"}),
        coarse=frozenset({"tablet", "capsule", "topical", "liquid", "jelly"}),
        gap=frozenset(), target="suppository"),
    Family("mouthwash", "mouthwash", "含漱 / 漱口", _pat(
        r"mouthwash", r"gargle", r"含漱", r"漱口", r"漱液", r"洗口", r"enjuague",
        r"colutorio"),
        ok=frozenset({"mouthwash", "liquid"}), gap=frozenset(), target="mouthwash"),
    Family("topical_patch", "topical", "贴剂 / 胶布 / 经皮", _pat(
        r"\bpatch", r"plaster", r"transdermal", r"贴", r"貼", r"藥膠布", r"药胶布",
        r"胶布", r"膏药", r"膏藥", r"穿皮", r"敷料", r"dressing", r"sealant matrix",
        r"parche", r"ap[oó]sito", r"transd[eé]rmic"),
        ok=frozenset({"topical", "plaster", "aposito", "patch"}), gap=frozenset({"film"}),
        target="patch"),
    Family("topical", "topical", "外用半固体（膏/霜/凝胶/洗剂）", _pat(
        r"cream", r"ointment", r"\bgel\b", r"lotion", r"\bpaste\b", r"salve", r"balm",
        r"liniment", r"shampoo", r"\bfoam\b", r"collodion", r"\bpaint\b", r"application",
        r"spray", r"wash", r"lipstick", r"乳膏", r"软膏", r"軟膏", r"凝胶", r"凝膠",
        r"洗剂", r"洗劑", r"搽剂", r"搽劑", r"霜", r"糊剂", r"糊劑", r"涂剂", r"塗劑",
        r"涂膜", r"火棉胶", r"硬膏", r"泡沫", r"乳胶", r"乳膠", r"橡胶膏", r"橡膠膏",
        r"外用", r"crema", r"pomada", r"ung[uü]ento", r"loci[oó]n", r"\bpasta\b",
        r"espuma", r"champ[uú]", r"barniz", r"semis[oó]lido", r"jalea", r"\bgel\b",
        r"喷雾", r"噴霧", r"\bswab", r"\bcloth\b", r"sponge", r"\bsoap", r"\brinse\b",
        r"\boil\b", r"lipstick", r"jelly", r"膏", r"uso t[oó]pic", r"\bt[oó]pic",
        r"\bwipe", r"\bpad\b"),
        ok=frozenset({"topical", "plaster", "jelly", "salve", "soap", "soap bar",
                      "swab", "cloth", "sponge", "rinse", "oil", "lipstick", "liniment",
                      "wipe", "pad", "aposito"}),
        coarse=frozenset({"liquid", "powder", "inhalation"}),
        gap=frozenset(), target="topical"),
    Family("powder", "powder", "粉 / 颗粒 / 散", _pat(
        r"powder", r"granule", r"sachet", r"packet", r"散剂", r"散劑", r"\b散\b",
        r"颗粒", r"顆粒", r"细粒", r"細粒", r"粉剂", r"粉劑", r"干混悬", r"乾混懸",
        r"干糖浆", r"粉状", r"粉狀", r"polvo", r"granulad", r"\bsobres?\b", r"granulado"),
        ok=frozenset({"powder"}), coarse=frozenset(), gap=frozenset()),
    Family("capsule", "capsule", "胶囊 / 胶丸", _pat(
        r"capsule", r"gelcap", r"softgel", r"胶囊", r"膠囊", r"胶丸", r"膠丸",
        r"c[aá]psula", r"perlas"),
        ok=frozenset({"capsule", "pill"}), gap=frozenset({"tablet"})),
    Family("pellet", "pellet", "微丸 / 滴丸", _pat(
        r"pellet", r"微丸", r"滴丸", r"微粒"),
        ok=frozenset({"pellet", "pill", "capsule"}), gap=frozenset(), target="pellet"),
    Family("stick", "stick", "棒剂 / 尿道棒", _pat(
        r"\bstick", r"棒剂", r"棒劑", r"尿道棒"),
        ok=frozenset({"stick"}), gap=frozenset(), target="stick"),
    Family("tablet", "tablet", "片剂 / 锭 / 丸", _pat(
        r"tablet", r"caplet", r"lozenge", r"troche", r"pastille", r"\bpill\b",
        r"片", r"錠", r"锭", r"丸", r"comprimid", r"tableta", r"gragea", r"pastilla",
        r"trocisc", r"\boblea"),
        ok=frozenset({"tablet", "pill"}), coarse=frozenset({"pastille"}),
        gap=frozenset({"capsule"})),
    Family("liquid", "liquid", "液体（溶液/混悬/糖浆/滴剂）", _pat(
        r"solution", r"suspension", r"syrup", r"elixir", r"linctus", r"mixture",
        r"liquid", r"emulsion", r"concentrate", r"drop", r"溶液", r"混悬", r"混懸",
        r"糖浆", r"糖漿", r"合剂", r"合劑", r"口服液", r"酏", r"滴剂", r"滴劑",
        r"乳剂", r"乳劑", r"胶浆", r"膠漿", r"酊", r"醑", r"露剂", r"液体制剂",
        r"液劑", r"液剂", r"懸液", r"soluci[oó]n", r"suspensi[oó]n", r"jarabe",
        r"emulsi[oó]n", r"l[ií]quid", r"\bgotas\b"),
        ok=frozenset({"liquid"}), coarse=frozenset({"oil", "tincture", "globule",
                                                    "rinse", "mouthwash", "jelly"}),
        gap=frozenset()),
    Family("other_form", "other", "其他杂项剂型（纱布/海绵/试纸/丸粒）", _pat(
        r"\bglobule", r"\bstrip\b", r"\bfilm\b", r"\bcord\b", r"\btea\b", r"soap bar",
        r"cigarette", r"dressing", r"\bpatch\b"),
        ok=frozenset({"globule", "strip", "film", "cord", "tea (herbal)", "soap bar"}),
        coarse=frozenset({"topical", "liquid", "solid"}), gap=frozenset()),
)

FAMILY_BY_ID = {f.fam_id: f for f in FAMILIES}
GROUP_ORDER: list[str] = []
GROUP_ZH: dict[str, str] = {}
for _f in FAMILIES:
    if _f.group not in GROUP_ZH:
        GROUP_ORDER.append(_f.group)
        GROUP_ZH[_f.group] = _f.zh

# form_base 空值 / 占位值（R1 的 unmapped 档、R7 的口径）
PLACEHOLDER_BASES = frozenset({"", "unknown", "other", "n/a", "na", "-", "/", "----",
                               "\\", "none", "not stated", "不适用", "null"})

CANON_BASES = ("tablet", "capsule", "liquid", "injection", "topical", "inhalation",
               "suppository", "powder")

RE_DIGIT = re.compile(r"\d")

# 已知 form_base 取值（canonical + 各来源自己产生的细类）。
# 落在集合外、且整串等于原文的，判为「归一化回退」——不是归类错，是没归上。
KNOWN_BASES: frozenset[str] = frozenset(
    set(CANON_BASES)
    | {base for fam in FAMILIES for group in (fam.ok, fam.coarse, fam.gap) for base in group}
    | {"pill", "pellet", "stick", "pastille", "kit", "implant", "plaster", "gas",
       "mouthwash", "rinse", "oil", "tincture", "gum", "gum, chewing", "film", "jelly",
       "salve", "globule", "soap", "soap bar", "cloth", "swab", "sponge", "strip",
       "cord", "tea (herbal)", "nasal", "inhalant", "device", "radiofarmaco",
       "other", "unknown", "liquid_ampoule", "liniment", "wipe", "pad", "aposito"}
)


# ---------------------------------------------------------------- 数据加载

@dataclass
class Product:
    product_id: str
    country: str
    region: str
    dosage_form: str
    form_base: str
    release: str
    pack: str | None
    source_id: str
    route: str | None


def open_db(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"找不到数据库：{path}")
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def load_products(con: sqlite3.Connection) -> list[Product]:
    rows: list[Product] = []
    for pid, country, region, form, fbase, rel, pack, src, route in con.execute(
        "SELECT product_id, country, region, dosage_form, form_base, release, pack,"
        " source_id, route FROM product"
    ):
        rows.append(Product(pid, country or "", region or "", form or "",
                            fbase or "", rel or "none", pack, src or "", route))
    return rows


def market_key(p: Product) -> str:
    """市场口径：国别产品取 country，区域层（EU）取 region，与 coverage 视图一致。"""
    return p.country or p.region or "?"


def load_names(con: sqlite3.Connection, product_ids: Iterable[str]) -> dict[str, str]:
    """给样例补商品名（只查被抽样到的几十个 id，避免全表扫）。"""
    ids = sorted({i for i in product_ids})
    if not ids:
        return {}
    out: dict[str, str] = {}
    for chunk_start in range(0, len(ids), 200):
        chunk = ids[chunk_start:chunk_start + 200]
        q = ("SELECT pn.product_id, nk.norm FROM product_name pn"
             " JOIN name_key nk ON nk.key_id = pn.key_id"
             f" WHERE pn.product_id IN ({','.join('?' * len(chunk))})"
             " ORDER BY pn.is_primary DESC, nk.norm")
        for pid, name in con.execute(q, chunk):
            out.setdefault(pid, name)
    return out


def top(counter: Counter, n: int) -> dict[str, int]:
    return {str(k): v for k, v in counter.most_common(n)}


def sample(rows: Iterable[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    return list(rows)[:n]


# ---------------------------------------------------------------- R1 剂型族矩阵

def classify(text: str) -> Family | None:
    """原文 → 族（按 FAMILIES 顺序，命中即停）。"""
    t = text.lower()
    for fam in FAMILIES:
        for pat in fam.patterns:
            if pat.search(t):
                return fam
    return None


def is_unmapped(p: Product) -> bool:
    """form_base 是否等于「没归一成功」：空 / 占位 / 回退成原文整串。

    判据（任一命中）：
      - 空串或占位值（unknown / other / - / not stated / null …）
      - 长度 > 25 或含数字：canonical 取值既不含数字也不会这么长，
        出现即说明整串 VMP 名（带强度）被塞进了 form_base
      - 不在 `KNOWN_BASES`（认得的 form_base 词表）里：`form_base_of()` 没命中时
        `return f or 'unknown'`，把原文原样（或去重音/去标点后）存了下来，
        例如 `implante`、`perlas`、`chicle`、`barniz unas`、`dressing`
    """
    b = p.form_base.strip()
    if b == "" or b.lower() in PLACEHOLDER_BASES:
        return True
    if len(b) > 25 or RE_DIGIT.search(b):
        return True
    return b.lower() not in KNOWN_BASES


def rule_form_matrix(products: list[Product], n_sample: int) -> dict[str, Any]:
    cache: dict[str, Family | None] = {}
    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    cell_verdicts: Counter[tuple[str, str]] = Counter()
    verdicts: dict[str, Counter[str]] = defaultdict(Counter)
    fam_verdicts: dict[str, Counter[str]] = defaultdict(Counter)
    verdict_rows: Counter[str] = Counter()
    by_market: dict[str, Counter[str]] = defaultdict(Counter)
    by_source: dict[str, Counter[str]] = defaultdict(Counter)
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unmatched = Counter()
    unmatched_text = Counter()
    unmatched_sample: list[dict[str, Any]] = []

    for p in products:
        fam = cache.get(p.dosage_form)
        if fam is None and p.dosage_form not in cache:
            fam = classify(p.dosage_form)
            cache[p.dosage_form] = fam
        if fam is None:
            unmatched[p.form_base or "∅"] += 1
            unmatched_text[(p.dosage_form.strip() or "∅")] += 1
            if len(unmatched_sample) < n_sample:
                unmatched_sample.append(_row(p, "unmatched", None))
            continue
        base = p.form_base.strip().lower()
        if is_unmapped(p):
            verdict = VERDICT_UNMAPPED
            base_key = "∅" if p.form_base.strip() == "" else p.form_base.strip()
        elif base in fam.ok:
            verdict = VERDICT_OK
            base_key = base
        elif base in fam.coarse:
            verdict = VERDICT_COARSE
            base_key = base
        elif base in fam.gap:
            verdict = VERDICT_GAP
            base_key = base
        else:
            verdict = VERDICT_CONFLICT
            base_key = base
        matrix[fam.group][base_key] += 1
        cell_verdicts[(fam.group, base_key, verdict)] += 1
        verdicts[fam.group][verdict] += 1
        fam_verdicts[fam.fam_id][verdict] += 1
        verdict_rows[verdict] += 1
        if verdict in (VERDICT_CONFLICT, VERDICT_GAP, VERDICT_UNMAPPED):
            by_market[verdict][market_key(p)] += 1
            by_source[verdict][p.source_id] += 1
            bucket = samples[verdict]
            if len(bucket) < 400:
                bucket.append(_row(p, verdict, fam.fam_id))

    # 矩阵：列取 Top 10 + 其他，避免 800+ 列
    col_total: Counter[str] = Counter()
    for c in matrix.values():
        col_total.update(c)
    keep_cols = [c for c, _ in col_total.most_common(10)]

    def shrink(counter: Counter[str]) -> dict[str, int]:
        out = {c: counter[c] for c in keep_cols if counter[c]}
        rest = sum(v for c, v in counter.items() if c not in keep_cols)
        if rest:
            out["其他"] = rest
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    rows = []
    for group in GROUP_ORDER:
        if not matrix.get(group):
            continue
        rows.append({
            "group": group,
            "zh": GROUP_ZH.get(group, group),
            "label": " / ".join(sorted({f.zh for f in FAMILIES if f.group == group})),
            "n": sum(matrix[group].values()),
            "target": next((f.target for f in FAMILIES
                            if f.group == group and f.target), None),
            "verdicts": dict(verdicts[group]),
            "form_base": shrink(matrix[group]),
        })
    rows.sort(key=lambda r: -r["n"])

    # 最大几格：族 × 当前 form_base × 判定（同一格可能既有 ok 也有 conflict，
    # 只把非 ok 的那部分单独列出来，n 是该判定的条数，不是整格条数）
    cells = []
    for (group, base, verdict), cnt in cell_verdicts.items():
        if verdict == VERDICT_OK:
            continue
        cells.append({"group": group, "form_base": base, "verdict": verdict, "n": cnt,
                      "cell_total": matrix[group][base]})
    cells.sort(key=lambda c: -c["n"])

    n_conflict = verdict_rows[VERDICT_CONFLICT]
    n_gap = verdict_rows[VERDICT_GAP]
    n_unmapped = verdict_rows[VERDICT_UNMAPPED]
    cells_by_group: dict[str, list[dict[str, Any]]] = {}
    for group in matrix:
        items = [c for c in cells if c["group"] == group][:8]
        cells_by_group[group] = items
    return {
        "id": "R1",
        "title": "剂型族 × form_base：原文说的剂型与归一化归类不符",
        "count": n_conflict + n_gap + n_unmapped,
        "detail": {
            "verdicts": dict(verdict_rows),
            "conflict": n_conflict,
            "gap": n_gap,
            "unmapped": n_unmapped,
            "coarse": verdict_rows[VERDICT_COARSE],
            "ok": verdict_rows[VERDICT_OK],
            "unmatched_rows": sum(unmatched.values()),
            "unmatched_by_form_base": top(unmatched, 10),
            "unmatched_top_text": top(unmatched_text, 10),
            "unmatched_samples": unmatched_sample,
            "matrix": rows,
            "top_cells": cells[:25],
            "cells_by_group": cells_by_group,
            "by_family": {fid: dict(sorted(c.items(), key=lambda kv: -kv[1]))
                          for fid, c in sorted(fam_verdicts.items(),
                                               key=lambda kv: -sum(kv[1].values()))},
        },
        "by_market": {k: dict(sorted(v.items(), key=lambda kv: -kv[1]))
                      for k, v in by_market.items()},
        "by_source": {k: top(v, 12) for k, v in by_source.items()},
        "samples": {
            "conflict": _with_names(samples[VERDICT_CONFLICT], n_sample),
            "gap": _with_names(samples[VERDICT_GAP], n_sample),
            "unmapped": _with_names(samples[VERDICT_UNMAPPED], n_sample),
        },
        "fix": FIX_RULE,
        "note": ("conflict 档是「原文与 form_base 直接冲突」的错，可加归一化规则重算；"
                 "gap 档是子类没有对应枚举（泡腾/咀嚼/口崩/贴剂/试剂盒），需新增 form_base 取值；"
                 "unmapped 是归一化完全没命中，回退成了原文或 unknown。"),
    }


def _row(p: Product, verdict: str, fam_id: str | None) -> dict[str, Any]:
    return {
        "product_id": p.product_id,
        "market": market_key(p),
        "source_id": p.source_id,
        "dosage_form": p.dosage_form,
        "form_base": p.form_base,
        "release": p.release,
        "pack": p.pack,
        "family": fam_id,
        "verdict": verdict,
    }


def _with_names(rows: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    return rows[:n]


# ---------------------------------------------------------------- R2 归一化回退

def rule_form_fallback(products: list[Product], n_sample: int) -> dict[str, Any]:
    rows = [p for p in products
            if is_unmapped(p) and p.form_base.strip().lower() not in PLACEHOLDER_BASES
            and p.form_base.strip() != ""]
    by_source = Counter(p.source_id for p in rows)
    by_market = Counter(market_key(p) for p in rows)
    raw = Counter(p.form_base.strip() for p in rows)
    samples = [_row(p, "fallback", None) for p in rows[:400]]
    return {
        "id": "R2",
        "title": "form_base 回退成原文整串（归一化没命中，直接存了原文）",
        "count": len(rows),
        "detail": {
            "by_source": top(by_source, 12),
            "top_values": top(raw, 20),
            "length_gt60": sum(1 for p in rows if len(p.form_base) > 60),
        },
        "by_market": dict(sorted(by_market.items(), key=lambda kv: -kv[1])),
        "by_source": top(by_source, 12),
        "samples": samples,
        "fix": FIX_RULE,
        "note": ("`form_base_of()` 没命中关键词时 `return f or 'unknown'`，把整串原文当成了剂型值。"
                 "典型：GB 的 `suppositories`（复数，y→ies 不匹配 `suppository`）、`pessaries`、"
                 "`medicated plasters`。加词表/复数归一即可重算。"),
    }


# ---------------------------------------------------------------- R3 释放机制

RE_ER = re.compile(
    r"extended[- ]release|sustained[- ]release|prolonged[- ]release|controlled[- ]release|"
    r"modified[- ]release|slow[- ]release|\bretard\b|\bxr\b|\ber\b|\bsr\b|\bmr\b|\bcr\b|"
    r"long[- ]acting|\bl\.a\.\b|缓释|緩釋|控释|控釋|持续释放|持續釋放|持续性|持續性|"
    r"长效|長效|chrono|orops|ocas|gits")
RE_DR = re.compile(
    r"delayed[- ]release|enteric|gastro[- ]?resist|gastrorresisten|肠溶|腸溶|"
    r"resistente al jugo|resistente al jugo gástrico")
RE_ANY_RELEASE = re.compile(RE_ER.pattern + "|" + RE_DR.pattern)


def rule_release(products: list[Product], n_sample: int) -> dict[str, Any]:
    er_none: list[Product] = []
    dr_none: list[Product] = []
    any_none: list[Product] = []
    set_no_text: list[Product] = []
    cross: list[Product] = []      # 原文 DR 但 release=ER 之类

    for p in products:
        t = p.dosage_form.lower()
        has_er = bool(RE_ER.search(t))
        has_dr = bool(RE_DR.search(t))
        has_any = has_er or has_dr
        if has_er and not has_dr and p.release == "none":
            er_none.append(p)
        if has_dr and not has_er and p.release == "none":
            dr_none.append(p)
        if has_any and p.release == "none":
            any_none.append(p)
        if has_er and p.release == "DR" or has_dr and p.release == "ER":
            cross.append(p)
        if not has_any and p.release != "none":
            set_no_text.append(p)

    def dist(rows: list[Product]) -> dict[str, int]:
        c = Counter(market_key(p) for p in rows)
        return dict(sorted(c.items(), key=lambda kv: -kv[1]))

    return {
        "id": "R3",
        "title": "释放机制：原文写缓释/肠溶但 release='none'（及反向）",
        "count": len(any_none) + len(set_no_text),
        "detail": {
            "er_text_release_none": len(er_none),
            "dr_text_release_none": len(dr_none),
            "any_text_release_none": len(any_none),
            "release_set_no_text": len(set_no_text),
            "cross_class": len(cross),
            "er_by_market": dist(er_none),
            "dr_by_market": dist(dr_none),
            "set_no_text_by_market": dist(set_no_text),
            "set_no_text_by_release": top(Counter(p.release for p in set_no_text), 8),
            "dr_text_by_source": top(Counter(p.source_id for p in dr_none), 8),
            "er_text_by_source": top(Counter(p.source_id for p in er_none), 8),
        },
        "by_market": {
            "text_release_none": dist(any_none),
            "release_set_no_text": dist(set_no_text),
        },
        "by_source": {
            "text_release_none": top(Counter(p.source_id for p in any_none), 12),
            "release_set_no_text": top(Counter(p.source_id for p in set_no_text), 12),
        },
        "samples": {
            "er_text_release_none": [_row(p, "er_none", None) for p in er_none[:400]][:n_sample],
            "dr_text_release_none": [_row(p, "dr_none", None) for p in dr_none[:400]][:n_sample],
            "release_set_no_text": [_row(p, "set_no_text", None)
                                    for p in set_no_text[:400]][:n_sample],
        },
        "fix": FIX_RULE,
        "note": ("`release_of()` 只认 extended/sustained/, er/, delayed/, dr，且只看剂型字段。"
                 "缺 controlled/prolonged/modified/肠溶（AU/SG 的 `Tablet, enteric coated` 全落 none）。"
                 "反向（release 有值、原文无词）是入库时按商品名推的，属显示层要标注来源。"),
    }


# ---------------------------------------------------------------- R4 规格

MASS_SCALE = {"g": 1000.0, "mg": 1.0, "mcg": 0.001, "µg": 0.001, "microgram": 0.001,
              "ng": 0.000001, "nanogram": 0.000001, "kg": 1_000_000.0}
CONC_UNIT_RE = re.compile(r"/|per|%")


def rule_strength(con: sqlite3.Connection, n_sample: int) -> dict[str, Any]:
    comps: list[tuple] = list(con.execute(
        "SELECT pc.product_id, pc.ord, pc.strength_value, pc.strength_unit,"
        " pc.per_volume_value, pc.per_volume_unit, p.country, p.region, p.form_base,"
        " p.dosage_form, p.source_id, v.substance_id"
        " FROM product_component pc JOIN product p ON p.product_id = pc.product_id"
        " JOIN variant v ON v.variant_id = pc.variant_id"))

    no_value = 0
    value_no_unit = 0
    n_zero = 0
    n_huge = 0
    n_tiny = 0
    n_liquid_no_volume = 0
    zero_or_neg: list[dict] = []
    huge: list[tuple] = []
    tiny: list[tuple] = []
    liquid_no_volume: list[tuple] = []
    mass_by_sub_country: dict[tuple[str, str], list[tuple[float, str, str]]] = defaultdict(list)
    market_no_value = Counter()
    source_no_value = Counter()
    market_liquid_novol = Counter()
    source_liquid_novol = Counter()
    huge_by_market = Counter()
    tiny_by_market = Counter()
    combo_products: dict[str, set[str]] = defaultdict(set)

    for (pid, _ord, val, unit, pv, pu, country, region, fbase, form, src, sid) in comps:
        mkt = country or region or "?"
        u = (unit or "").strip()
        if val is None:
            no_value += 1
            market_no_value[mkt] += 1
            source_no_value[src] += 1
            continue
        if not u:
            value_no_unit += 1
        if val <= 0:
            n_zero += 1
            if len(zero_or_neg) < 400:
                zero_or_neg.append({"product_id": pid, "market": mkt, "value": val,
                                    "unit": u, "form_base": fbase, "dosage_form": form,
                                    "source_id": src})
            continue
        if MASS_SCALE.get(u) is not None:
            mass_by_sub_country[(sid, mkt)].append((val, u, pid))
            if val > 100000:
                n_huge += 1
                huge_by_market[mkt] += 1
                if len(huge) < 400:
                    huge.append((pid, mkt, val, u, fbase, form, src))
            if val < 0.0001:
                n_tiny += 1
                tiny_by_market[mkt] += 1
                if len(tiny) < 400:
                    tiny.append((pid, mkt, val, u, fbase, form, src))
        if u and not CONC_UNIT_RE.search(u) and pv is None and fbase in ("liquid", "injection"):
            n_liquid_no_volume += 1
            market_liquid_novol[mkt] += 1
            source_liquid_novol[src] += 1
            if len(liquid_no_volume) < 400:
                liquid_no_volume.append((pid, mkt, val, u, fbase, form, src))
        combo_products[pid].add(u if not CONC_UNIT_RE.search(u) else "conc")

    # 同成分 + 同国家：g / mg 并存，且数值等价（500 mg vs 0.5 g）→ 归一化没合并
    g_mg_pairs: list[dict] = []
    g_mg_coexist = 0
    n_g_mg_pairs = 0
    for (sid, mkt), vals in mass_by_sub_country.items():
        units = {u for _v, u, _p in vals}
        if "g" in units and "mg" in units:
            g_mg_coexist += 1
            g_vals = [(v, p) for v, u, p in vals if u == "g"]
            mg_vals = [(v, p) for v, u, p in vals if u == "mg"]
            for gv, gpid in g_vals:
                for mv, mpid in mg_vals:
                    if gpid == mpid:
                        continue
                    if abs(gv * 1000.0 - mv) <= max(0.01, mv * 0.001):
                        n_g_mg_pairs += 1
                        if len(g_mg_pairs) < 400:
                            g_mg_pairs.append({"substance_id": sid, "market": mkt,
                                               "g_product": gpid, "g_value": gv,
                                               "mg_product": mpid, "mg_value": mv})

    # 复方内单位尺度混用（不同成分天然量级不同，只作提示，全部计数）
    combo_scale_mix = Counter()
    for pid, units in combo_products.items():
        real = {u for u in units if u != "conc"}
        if len(real) > 1:
            combo_scale_mix[pid] = len(real)
    combo_scale_by_market: Counter[str] = Counter()
    pid_market = {r[0]: (r[6] or r[7] or "?") for r in comps}
    for pid in combo_scale_mix:
        combo_scale_by_market[pid_market.get(pid, "?")] += 1

    no_component = list(con.execute(
        "SELECT p.product_id, COALESCE(p.country, p.region), p.source_id, p.form_base"
        " FROM product p LEFT JOIN product_component pc ON pc.product_id = p.product_id"
        " WHERE pc.product_id IS NULL"))

    total_comp = len(comps)
    liquid_n = sum(1 for r in comps if r[8] in ("liquid", "injection"))
    return {
        "id": "R4",
        "title": "规格：单位缺失 / 值为 0 或负 / 量级离谱 / g 与 mg 并存 / 液体缺每容量 / 复方跨单位",
        "count": sum([
            no_value, value_no_unit, n_zero, n_huge, n_tiny,
            n_g_mg_pairs, n_liquid_no_volume, len(no_component),
        ]),
        "detail": {
            "components_total": total_comp,
            "value_null": no_value,
            "value_null_by_market": dict(sorted(market_no_value.items(), key=lambda kv: -kv[1])),
            "value_null_by_source": top(source_no_value, 12),
            "unit_empty_value_present": value_no_unit,
            "value_zero_or_negative": n_zero,
            "value_gt_100000_mass": n_huge,
            "value_gt_100000_mass_by_market": dict(sorted(huge_by_market.items(),
                                                          key=lambda kv: -kv[1])),
            "value_lt_0_0001_mass": n_tiny,
            "value_lt_0_0001_mass_by_market": dict(sorted(tiny_by_market.items(),
                                                          key=lambda kv: -kv[1])),
            "g_mg_coexist_substance_country": g_mg_coexist,
            "g_mg_equal_magnitude_pairs": n_g_mg_pairs,
            "liquid_no_per_volume": n_liquid_no_volume,
            "liquid_components_total": liquid_n,
            "combo_unit_scale_mix": len(combo_scale_mix),
            "combo_unit_scale_mix_by_market": dict(sorted(
                combo_scale_by_market.items(), key=lambda kv: -kv[1])),
            "products_without_component": len(no_component),
            "products_without_component_by_market": dict(sorted(
                Counter(r[1] or "?" for r in no_component).items(), key=lambda kv: -kv[1])),
            "products_without_component_samples": [
                {"product_id": r[0], "market": r[1], "source_id": r[2], "form_base": r[3]}
                for r in no_component[:n_sample * 2]],
        },
        "by_market": {
            "value_null": dict(sorted(market_no_value.items(), key=lambda kv: -kv[1])),
            "liquid_no_per_volume": dict(sorted(market_liquid_novol.items(),
                                                key=lambda kv: -kv[1])),
        },
        "by_source": {
            "value_null": top(source_no_value, 12),
            "liquid_no_per_volume": top(source_liquid_novol, 12),
        },
        "samples": {
            "value_zero_or_negative": zero_or_neg[:n_sample],
            "value_gt_100000_mass": [
                {"product_id": r[0], "market": r[1], "value": r[2], "unit": r[3],
                 "form_base": r[4], "dosage_form": r[5], "source_id": r[6]} for r in huge[:n_sample]],
            "value_lt_0_0001_mass": [
                {"product_id": r[0], "market": r[1], "value": r[2], "unit": r[3],
                 "form_base": r[4], "dosage_form": r[5], "source_id": r[6]} for r in tiny[:n_sample]],
            "g_mg_equal_magnitude": g_mg_pairs[:n_sample],
            "liquid_no_per_volume": [
                {"product_id": r[0], "market": r[1], "value": r[2], "unit": r[3],
                 "form_base": r[4], "dosage_form": r[5], "source_id": r[6]}
                for r in liquid_no_volume[:n_sample]],
        },
        "fix": FIX_MIGRATE,
        "note": ("值为空多为来源就没给（HK 名称层、TW、US 部分、MX 浓度七成空缺），属来源本身；"
                 "值为 0/负、单位空但值有、g 与 mg 等价并存、液体缺每容量属归一化/入库可修；"
                 "复方跨单位多数是不同成分天然量级不同（微克维生素 + 毫克主药），不算错。"),
    }


# ---------------------------------------------------------------- R5 包装

RE_VOLUME = re.compile(r"\d+(?:[.,]\d+)?\s*(?:ml|毫升|ml\.|l\b|litre|liter|ℓ)", re.I)
RE_COUNT = re.compile(
    r"\d+\s*(?:片|粒|錠|锭|枚|丸|袋|包|支|安瓿|胶囊|膠囊|tablets?|tabs?|caps?|capsules?|"
    r"sachets?|pcs?|pieces?)", re.I)
RE_COUNT_SOLID = re.compile(
    r"\d+\s*(?:片|粒|錠|锭|枚|丸|tablets?|tabs?|caps?|caplets?|lozenges?)", re.I)
SOLID_FORMS = frozenset({"tablet", "capsule", "pill", "pellet", "pastille",
                         "suppository", "powder"})
LIQUID_FORMS = frozenset({"liquid", "injection", "mouthwash", "rinse"})
NUMERIC_ONLY = re.compile(r"^[\d.,/\s]+$")


def rule_pack(products: list[Product], n_sample: int) -> dict[str, Any]:
    market_total = Counter()
    market_null = Counter()
    numeric_only: list[Product] = []
    solid_volume: list[Product] = []
    liquid_count: list[Product] = []
    emptyish: list[Product] = []
    n_numeric = 0
    n_solid_volume = 0
    n_liquid_count = 0
    n_emptyish = 0
    mkt_numeric = Counter()
    mkt_solid_volume = Counter()
    mkt_liquid_count = Counter()
    src_solid_volume = Counter()
    src_liquid_count = Counter()
    src_numeric = Counter()

    for p in products:
        mkt = market_key(p)
        market_total[mkt] += 1
        pack = (p.pack or "").strip()
        if not pack:
            market_null[mkt] += 1
            continue
        if pack.lower() in ("-", "—", "n/a", "na", "none", "not stated", "unknown"):
            n_emptyish += 1
            if len(emptyish) < 400:
                emptyish.append(p)
            continue
        if NUMERIC_ONLY.match(pack) and not RE_VOLUME.search(pack):
            n_numeric += 1
            mkt_numeric[mkt] += 1
            src_numeric[p.source_id] += 1
            if len(numeric_only) < 400:
                numeric_only.append(p)
            continue
        base = p.form_base.strip().lower()
        has_vol = bool(RE_VOLUME.search(pack))
        has_cnt = bool(RE_COUNT.search(pack))
        if base in SOLID_FORMS and has_vol and not has_cnt:
            n_solid_volume += 1
            mkt_solid_volume[mkt] += 1
            src_solid_volume[p.source_id] += 1
            if len(solid_volume) < 400:
                solid_volume.append(p)
        elif base in LIQUID_FORMS and RE_COUNT_SOLID.search(pack) and not has_vol:
            n_liquid_count += 1
            mkt_liquid_count[mkt] += 1
            src_liquid_count[p.source_id] += 1
            if len(liquid_count) < 400:
                liquid_count.append(p)

    null_rate = {m: round(100.0 * market_null[m] / market_total[m], 1)
                 for m in sorted(market_total, key=lambda m: -market_total[m])}
    return {
        "id": "R5",
        "title": "包装：pack 与剂型矛盾 / pack 只有数字没有单位 / 空值率",
        "count": n_solid_volume + n_liquid_count + n_numeric,
        "detail": {
            "pack_null_by_market": dict(sorted(market_null.items(), key=lambda kv: -kv[1])),
            "pack_total_by_market": dict(sorted(market_total.items(), key=lambda kv: -kv[1])),
            "pack_null_rate_pct": null_rate,
            "numeric_only_pack": n_numeric,
            "numeric_only_by_market": dict(sorted(mkt_numeric.items(), key=lambda kv: -kv[1])),
            "solid_form_with_volume_only": n_solid_volume,
            "liquid_form_with_count_only": n_liquid_count,
            "placeholder_pack": n_emptyish,
        },
        "by_market": {
            "solid_form_with_volume_only": dict(sorted(mkt_solid_volume.items(),
                                                       key=lambda kv: -kv[1])),
            "liquid_form_with_count_only": dict(sorted(mkt_liquid_count.items(),
                                                       key=lambda kv: -kv[1])),
            "numeric_only_pack": dict(sorted(mkt_numeric.items(), key=lambda kv: -kv[1])),
        },
        "by_source": {
            "solid_form_with_volume_only": top(src_solid_volume, 12),
            "liquid_form_with_count_only": top(src_liquid_count, 12),
            "numeric_only_pack": top(src_numeric, 12),
        },
        "samples": {
            "solid_form_with_volume_only": [_row(p, "solid_volume", None) for p in solid_volume[:n_sample]],
            "liquid_form_with_count_only": [_row(p, "liquid_count", None) for p in liquid_count[:n_sample]],
            "numeric_only_pack": [_row(p, "numeric_only", None) for p in numeric_only[:n_sample]],
            "placeholder_pack": [_row(p, "placeholder", None) for p in emptyish[:n_sample]],
        },
        "fix": FIX_DISPLAY,
        "note": ("pack 是来源原样字符串，五个市场（GB/ES/HK/MX/SG）根本没这个字段——"
                 "空值率是来源事实。矛盾判定要求「只出现另一类的量词」：CN 的"
                 "「160ml瓶…120片/盒」同时含两种，不算矛盾。pack 只有数字（CA「100」、AU「30」）"
                 "缺单位，属显示层要拼上剂型单位。"),
    }


# ---------------------------------------------------------------- R6 重复身份

def rule_duplicates(con: sqlite3.Connection, products: list[Product],
                    n_sample: int) -> dict[str, Any]:
    """重复身份：同一批文被写了两遍。

    键 = 国家 + 商品名（primary trade）+ MAH + 成分组合（variant + 强度）+ form_base + pack。
    刻意带上商品名与 MAH：同成分同规格同包装的两个**不同品牌**是两条合法产品
    （不同批文），不带名字会把所有仿制药全撞成一组。
    强度全空的行无法判断（GB/TW 大面积缺强度），单列为 undecidable，不进结论。
    """
    comps: dict[str, list[tuple]] = defaultdict(list)
    for pid, _ord, vid, val, unit, pv, pu in con.execute(
        "SELECT product_id, ord, variant_id, strength_value, strength_unit,"
        " per_volume_value, per_volume_unit FROM product_component ORDER BY product_id, ord"
    ):
        comps[pid].append((vid, val, unit, pv, pu))

    names: dict[str, str] = {}
    for pid, name in con.execute(
        "SELECT pn.product_id, nk.norm FROM product_name pn"
        " JOIN name_key nk ON nk.key_id = pn.key_id"
        " WHERE pn.is_primary = 1 AND pn.name_type IN ('trade', 'inn')"
    ):
        names.setdefault(pid, name)

    by_id = {p.product_id: p for p in products}
    mah_of: dict[str, str] = {}
    approval_of: dict[str, str] = {}
    for pid, mah, appr in con.execute("SELECT product_id, mah, approval_id FROM product"):
        mah_of[pid] = (mah or "").strip().lower()
        approval_of[pid] = (appr or "").strip().lower()

    groups: dict[tuple, list[str]] = defaultdict(list)
    undecidable_no_strength = 0
    undecidable_no_key = 0
    no_name = 0
    for p in products:
        sig_comps = tuple(comps.get(p.product_id, []))
        if not sig_comps:
            continue
        if all(v[1] is None for v in sig_comps):
            undecidable_no_strength += 1
            continue
        name = names.get(p.product_id, "")
        if not name:
            no_name += 1
        appr = approval_of.get(p.product_id, "")
        pack = (p.pack or "").strip().lower()
        if appr:
            # 有批文号：同一批文 + 同商品名 + 同强度 + 同包装出现两次 = 硬重复
            # （同一批文的不同包装是设计上不同的 product 行；AU/pbs 的 approval_id 是
            #  PBS item code，一个码下挂多个品牌，所以品牌名必须进键）
            key = ("same_approval", market_key(p), appr, name, pack, sig_comps)
        elif pack:
            key = ("same_name_pack", market_key(p), name, mah_of.get(p.product_id, ""),
                   p.form_base.strip().lower(), pack, sig_comps)
        else:
            # 既没批文号也没包装：无法判断是「同一批文写两遍」还是「同品牌不同包装」
            undecidable_no_key += 1
            continue
        groups[key].append(p.product_id)

    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    extra_rows = sum(len(v) - 1 for v in dup_groups.values())
    rows_involved = sum(len(v) for v in dup_groups.values())
    src_mix = sum(1 for v in dup_groups.values()
                  if len({by_id[i].source_id for i in v}) > 1)
    kind_rows = Counter()
    by_market = Counter()
    for k, v in dup_groups.items():
        kind_rows[k[0]] += len(v) - 1
        by_market[k[1]] += len(v) - 1
    by_source = Counter(by_id[i].source_id for v in dup_groups.values() for i in v)
    size_hist = Counter(len(v) for v in dup_groups.values())

    samples = []
    for key, pids in sorted(dup_groups.items(), key=lambda kv: -len(kv[1]))[:max(n_sample, 5)]:
        pids = sorted(pids)
        head = key[0]
        samples.append({
            "kind": head,
            "market": key[1],
            "approval_id": key[2] if head == "same_approval" else "",
            "name": key[3] if head == "same_approval" else key[2],
            "mah": "" if head == "same_approval" else key[3],
            "form_base": by_id[pids[0]].form_base,
            "pack": key[4] if head == "same_approval" else key[5],
            "n": len(pids),
            "products": [{"product_id": i, "source_id": by_id[i].source_id,
                          "dosage_form": by_id[i].dosage_form} for i in pids[:4]],
        })
    return {
        "id": "R6",
        "title": "重复身份：同国家同一批文/同品牌同包装的多行",
        "count": extra_rows,
        "detail": {
            "by_kind": dict(kind_rows),
            "duplicate_groups": len(dup_groups),
            "extra_rows": extra_rows,
            "rows_involved": rows_involved,
            "groups_spanning_multiple_sources": src_mix,
            "undecidable_no_strength": undecidable_no_strength,
            "undecidable_no_key": undecidable_no_key,
            "products_without_name": no_name,
            "group_size_histogram": {str(k): v for k, v in sorted(size_hist.items())},
            "by_market": dict(sorted(by_market.items(), key=lambda kv: -kv[1])),
            "by_source": top(by_source, 12),
        },
        "by_market": dict(sorted(by_market.items(), key=lambda kv: -kv[1])),
        "by_source": top(by_source, 12),
        "samples": samples[:n_sample],
        "fix": FIX_MIGRATE,
        "note": ("判据分两级：有批文号时「同一批文 + 同成分强度」出现多次 = 硬重复；"
                 "没批文号时要求「同商品名 + 同 MAH + 同 form_base + **同非空 pack** + 同成分强度」——"
                 "pack 为空的市场（ES/HK/SG 全部为空）里同一品牌的多个包装规格无法区分，"
                 "这类直接记为无法判定，不当重复报。"),
    }


# ---------------------------------------------------------------- R7 空值族

def rule_form_null(products: list[Product], n_sample: int) -> dict[str, Any]:
    null_rows = [p for p in products
                 if p.form_base.strip() == "" or p.form_base.strip().lower() in PLACEHOLDER_BASES]
    by_market = Counter(market_key(p) for p in null_rows)
    by_source = Counter(p.source_id for p in null_rows)
    by_value = Counter(p.form_base.strip() or "∅" for p in null_rows)
    raw = Counter(p.dosage_form.strip() or "∅" for p in null_rows)
    return {
        "id": "R7",
        "title": "空值族：form_base 为空 / unknown / other 的分布",
        "count": len(null_rows),
        "detail": {
            "by_market": dict(sorted(by_market.items(), key=lambda kv: -kv[1])),
            "by_source": top(by_source, 12),
            "by_value": top(by_value, 10),
            "top_raw_dosage_form": top(raw, 30),
        },
        "by_market": dict(sorted(by_market.items(), key=lambda kv: -kv[1])),
        "by_source": top(by_source, 12),
        "samples": [_row(p, "null", None) for p in null_rows[:n_sample]],
        "fix": FIX_SOURCE,
        "note": ("HK（hk_dh）是名称层来源，没有剂型字段，13935 行全空；"
                 "AU 的 tga_cmi 原文就是 `not stated`；这两部分占 93%，改不了。"
                 "剩下可归一的：AU artg_export 1002 行（`Stick`/`Wafer`/`Liniment`/"
                 "`Implant`/`Gum, chewing` 都有原文可映射）、CN nhsa 367 行"
                 "（`缓释制剂`/`控释制剂`/`体外诊断试剂`/`膜剂`/`植入剂`）。"),
    }


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="剂型/规格/释放/包装 一致性审计（只读）")
    ap.add_argument("--db", default=str(DB), help="数据库路径（只读打开）")
    ap.add_argument("--json", default="", help="把结果写成 JSON")
    ap.add_argument("--top", type=int, default=5, help="每条规则给几个样例（默认 5）")
    ap.add_argument("--only", default="", help="只跑指定规则，如 R1,R3")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    con = open_db(Path(args.db))
    products = load_products(con)
    only = {s.strip().upper() for s in args.only.split(",") if s.strip()}

    def want(rid: str) -> bool:
        return not only or rid in only

    rules: list[dict[str, Any]] = []
    if want("R1"):
        rules.append(rule_form_matrix(products, args.top))
    if want("R2"):
        rules.append(rule_form_fallback(products, args.top))
    if want("R3"):
        rules.append(rule_release(products, args.top))
    if want("R4"):
        rules.append(rule_strength(con, args.top))
    if want("R5"):
        rules.append(rule_pack(products, args.top))
    if want("R6"):
        rules.append(rule_duplicates(con, products, args.top))
    if want("R7"):
        rules.append(rule_form_null(products, args.top))

    # 样例补商品名
    ids = []
    for rule in rules:
        s = rule.get("samples")
        buckets = s.values() if isinstance(s, dict) else [s]
        for bucket in buckets:
            for row in bucket or []:
                if isinstance(row, dict) and row.get("products"):
                    ids.extend(x["product_id"] for x in row["products"] if x.get("product_id"))
                elif isinstance(row, dict) and row.get("product_id"):
                    ids.append(row["product_id"])
    names = load_names(con, ids)
    for rule in rules:
        s = rule.get("samples")
        buckets = s.values() if isinstance(s, dict) else [s]
        for bucket in buckets:
            for row in bucket or []:
                if isinstance(row, dict) and row.get("product_id") in names:
                    row["name"] = names[row["product_id"]]

    payload = {
        "script": "db/consistency_audit_form.py",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "db": str(Path(args.db).relative_to(ROOT)) if Path(args.db).is_relative_to(ROOT)
              else args.db,
        "readonly": True,
        "top": args.top,
        "totals": {
            "products": len(products),
            "markets": dict(sorted(Counter(market_key(p) for p in products).items(),
                                   key=lambda kv: -kv[1])),
        },
        "rules": rules,
    }

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.quiet:
        print_console(payload)
        if args.json:
            print(f"\nJSON: {args.json}")
    con.close()
    return 0


def print_console(payload: dict[str, Any]) -> None:
    t = payload["totals"]
    print(f"== 一致性审计（只读）  products={t['products']:,} ==")
    print("市场分布：" + " ".join(f"{k}={v:,}" for k, v in t["markets"].items()))
    for rule in payload["rules"]:
        print(f"\n--- {rule['id']} {rule['title']} ---")
        print(f"  条数: {rule['count']:,}   修法: {rule['fix']}")
        d = rule.get("detail", {})
        for key in ("verdicts", "conflict", "gap", "unmapped", "by_market", "by_source",
                    "er_text_release_none", "dr_text_release_none", "release_set_no_text",
                    "value_null", "unit_empty_value_present", "value_zero_or_negative",
                    "g_mg_equal_magnitude_pairs", "liquid_no_per_volume",
                    "numeric_only_pack", "solid_form_with_volume_only",
                    "liquid_form_with_count_only", "duplicate_groups", "extra_rows",
                    "top_raw_dosage_form"):
            if key in d and isinstance(d[key], (int, dict)):
                v = d[key]
                if isinstance(v, dict):
                    items = list(v.items())[:8]
                    print(f"    {key}: " + ", ".join(f"{k}={x}" for k, x in items))
                else:
                    print(f"    {key}: {v:,}")
        if rule["id"] == "R1":
            print("    矩阵（族 → form_base Top，前 8 族）:")
            for row in d["matrix"][:8]:
                cells = ", ".join(f"{k}={v}" for k, v in list(row["form_base"].items())[:6])
                print(f"      {row['group']:<14} n={row['n']:>7,}  {cells}")
            print("    最大几格（族 × form_base）:")
            for cell in d["top_cells"][:8]:
                print(f"      {cell['group']:<14} -> {cell['form_base']:<22}"
                      f" {cell['n']:>6,}  [{cell['verdict']}]")
        samples = rule.get("samples")
        if isinstance(samples, dict):
            for bucket, rows in samples.items():
                for row in rows[:3]:
                    print(f"    样例[{bucket}] {row}")
        elif isinstance(samples, list):
            for row in samples[:3]:
                print(f"    样例 {row}")


if __name__ == "__main__":
    raise SystemExit(main())
