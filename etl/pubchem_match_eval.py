"""STR1 前置复测：PubChem 名称匹配率（原始 ``inn_en`` vs 规范化后）。

背景
----
STR1（药物化学结构图）已定「走 PubChem API、只下载命中集」，但需要先回答
「按名字能命中多少」才能定图张数与体积。本脚本对 ``substance.inn_en`` 做固定
种子的 300 条抽样，先测原始名，再按「去括号 / 去盐·酯后缀 / 去 ``(as …)`` /
拆分复方」逐档规范化后测同一批样本，输出 before / after、失败分类与外推。

只读与网络纪律
--------------
- 数据库只读：``sqlite3.connect("file:...?mode=ro", uri=True)``，不写库、不建表。
- 网络：单进程串行、固定 UA、每次请求后 ``sleep(MIN_INTERVAL)``（≈4.5 req/s，
  低于 PubChem 官方 5 req/s 上限）；404 不重试，429/5xx 指数退避 3 次。
- 缓存：``data/raw/pubchem-match-eval/cid-cache.jsonl``（JSONL，不入库）。
- 不做整库镜像、不做模糊匹配、不绕 WAF。

用法
----
::

    python etl/pubchem_match_eval.py --plan          # 只算样本 / 候选，不发请求
    python etl/pubchem_match_eval.py --run           # 默认：跑 300 条并写结果
    python etl/pubchem_match_eval.py --run --limit 50 --refresh

产物（均在 ``data/raw/pubchem-match-eval/``，已被 .gitignore 忽略）：

- ``cid-cache.jsonl``：查询 → 状态 / CID 缓存，可重复跑
- ``eval-300.json``：逐条样本、分档命中、失败分类、汇总与外推

口径说明
--------
- ``after_core`` = 原始 + 清理 + 去括号 + 去盐·酯 + 复方拆分（任务指定的四类规范化）
- ``after_extended`` = ``after_core`` + 共晶配体（L-proline 等）+ 数据脏前缀清理
- 复方拆分的命中只代表「复方里某一个成分有结构」，报告里单独标注，不当作复方整体结构。
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))

from normalize_salts import (  # noqa: E402
    ESTER_TOKENS,
    SALT_ALIASES,
    WATER_TOKENS,
)

DEFAULT_DB = ROOT / "data" / "drugs.db"
OUT_DIR = ROOT / "data" / "raw" / "pubchem-match-eval"
CACHE_PATH = OUT_DIR / "cid-cache.jsonl"
RESULT_PATH = OUT_DIR / "eval-300.json"

BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
UA = "drugcrossref-match-eval/1.0 (+https://drugcrossref.com/; contact via drugcrossref.com)"
SEED = 20261126
N_SAMPLE = 300
MIN_INTERVAL = 0.22          # 秒；≈4.5 req/s，低于 PubChem 的 5 req/s
RETRY_CODES = {429, 500, 502, 503, 504}
MAX_TRIES = 3

# 图片体积：沿用 2026-11-26 STR1 可行性报告实测的 50 张 PNG（300×300 / 200×200）
IMG300_AVG_B = 2865
IMG300_MIN_B = 1600
IMG300_MAX_B = 4100
IMG200_AVG_B = 1784

# --- 词表：盐 / 酯 / 水合物 / 通用限定词 -----------------------------------
SALT_STEMS: set[str] = {a for aliases in SALT_ALIASES.values() for a in aliases} | {
    "disodium", "dipotassium", "dicalcium", "monosodium", "monopotassium",
    "monohydrochloride", "dihydrochloride", "trihydrochloride",
}
ESTER_STEMS: set[str] = {a for aliases in ESTER_TOKENS.values() for a in aliases}
HYDRATE_STEMS: set[str] = set(WATER_TOKENS) | {
    "hydrate", "monohydrate", "dihydrate", "trihydrate", "tetrahydrate",
    "hemihydrate", "sesquihydrate", "pentahydrate", "hexahydrate",
    "heptahydrate", "octahydrate",
}
ELEMENT_STEMS: set[str] = {
    "sodium", "potassium", "calcium", "magnesium", "lithium", "iron", "zinc",
    "copper", "aluminium", "aluminum", "barium", "selenium", "silver", "gold",
}
QUALIFIER_STEMS: set[str] = {
    "complex", "complexes", "coordination", "anhydrous", "anhydrate", "base",
    "freebase", "micronized", "micronised", "crystalline", "amorphous",
    "hydrolysed", "hydrolyzed", "enzymatic", "derivative", "derivatives",
}
COFORMER_STEMS: set[str] = {
    "proline", "lysine", "arginine", "trometamol", "tromethamine",
    "meglumine", "betaine",
}
SALT_STRIP_STEMS: set[str] = (
    SALT_STEMS | ESTER_STEMS | ELEMENT_STEMS | QUALIFIER_STEMS | HYDRATE_STEMS
)
LIGHT_STRIP_STEMS: set[str] = QUALIFIER_STEMS | HYDRATE_STEMS
STOICH_WORDS: set[str] = {
    "bis", "tris", "hemi", "mono", "di", "tri", "tetra", "penta", "hexa",
    "sesqui", "l", "d", "dl",
}
METAL_ADJ: set[str] = {
    "cobaltous", "cobaltic", "ferrous", "ferric", "cuprous", "cupric",
    "mercurous", "mercuric", "stannous", "stannic", "plumbous", "plumbic",
    "aurous", "auric", "manganous", "manganic", "chromous", "chromic",
    "nickelous", "zincous", "thallous", "thallic", "antimonous", "antimonic",
    "arsenous", "bismuthous", "bismuthic",
}
STOP_SINGLE: set[str] = {
    "extract", "ext", "tincture", "tinc", "powder", "oil", "acid", "sodium",
    "potassium", "calcium", "magnesium", "complex", "vaccine", "toxoid",
    "immunoglobulin", "allergen", "flower", "leaf", "root", "whole", "seed",
    "bark", "wood", "herb", "fever", "juice", "water", "solution", "tablet",
    "capsule", "injection", "dried", "dry", "soft", "ethanol", "alcohol",
    "aqueous", "concentrate", "human", "bovine", "porcine", "equine",
    "recombinant", "inactivated", "activated", "antigen", "toxin", "serum",
    "plasma", "cell", "tissue", "protein", "peptide", "mixture", "gas",
    "sterile", "purified",
}
BAD_TAIL: set[str] = {
    "and", "with", "of", "from", "for", "in", "on", "to", "the", "a", "an",
    "et", "al", "or",
}
PAREN_QUALIFIER_WORDS: set[str] = {
    "as", "enteric", "coated", "hydrate", "anhydrous", "base", "free", "salt",
    "hydrochloride", "sodium", "potassium", "calcium", "magnesium",
    "sulfate", "sulphate", "citrate", "acetate", "succinate", "tartrate",
    "maleate", "fumarate", "mesylate", "besylate", "phosphate", "chloride",
    "bromide", "iodide", "nitrate", "oxide", "hydroxide", "carbonate",
    "complex", "micronized", "micronised", "crystalline", "amorphous",
    "solution", "suspension", "injection", "tablet", "capsule", "dried",
    "dry", "soft", "ethanol", "aqueous", "extract", "enzymatic", "coated",
    "release", "delayed", "extended", "film", "sustained",
}

CORE_STAGES: set[str] = {"raw", "clean", "paren", "salt", "combo"}
EXTENDED_STAGES: set[str] = CORE_STAGES | {"coformer", "dirty"}
STAGE_LABEL: dict[str, str] = {
    "raw": "原始 inn_en",
    "clean": "清理（NFKC/空白/标点）",
    "paren": "去括号 / 去 (as …)",
    "salt": "去盐·酯·水合物后缀",
    "combo": "复方拆分",
    "coformer": "去共晶配体（附加）",
    "dirty": "去数据脏前缀（附加）",
}

_TRADEMARK = re.compile(r"[®™©]")
_DASH = re.compile(r"[\u2010-\u2015\u2212]")
_PAREN = re.compile(r"\(([^()]*)\)")
_NUM = re.compile(r"^\d+(?:[.,]\d+)?$")
_COMBO_RE = re.compile(r"\s*(?:\+|&|;)\s*|\s+/\s+|\s+(?:and|with)\s+", re.IGNORECASE)
_CJK_SLASH = re.compile(r"(?<=[\u4e00-\u9fff])/|/(?=[\u4e00-\u9fff])")

_last_request: float = 0.0


def bj_now() -> str:
    """北京时间字符串（报告与缓存用）。"""
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S%z")


# ---------------------------------------------------------------------------
# 样本与只读 DB
# ---------------------------------------------------------------------------
def load_sample(db_path: Path, limit: int, seed: int) -> tuple[list[tuple[str, str, str]], dict[str, int]]:
    """按固定种子从 substance 抽样；返回 [(substance_id, inn_en, atc)] 与全表口径。"""
    uri = f"file:{db_path.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=60)
    try:
        rows = con.execute(
            "SELECT substance_id, inn_en, COALESCE(atc, '') FROM substance ORDER BY inn_en"
        ).fetchall()
        total = len(rows)
        ascii_total = sum(1 for r in rows if all(ord(ch) < 128 for ch in r[1]))
        han_total = sum(1 for r in rows if any("\u4e00" <= ch <= "\u9fff" for ch in r[1]))
        nonascii_total = sum(1 for r in rows if any(ord(ch) > 127 for ch in r[1]))
        atc_total = sum(1 for r in rows if r[2])
    finally:
        con.close()

    by_name = {r[1]: r for r in rows}
    names = sorted(by_name)
    if limit >= len(names):
        picked = names
    else:
        picked = random.Random(seed).sample(names, limit)
    sample = [by_name[n] for n in sorted(picked)]
    stats = {
        "substance_total": total,
        "ascii_total": ascii_total,
        "han_total": han_total,
        "nonascii_total": nonascii_total,
        "atc_total": atc_total,
    }
    return sample, stats


# ---------------------------------------------------------------------------
# 文本规范化（纯函数，便于单测 / 复现）
# ---------------------------------------------------------------------------
def clean_text(raw: str) -> str:
    """NFKC + 去商标符号 + 折叠空白 + 去尾部标点；不改大小写。"""
    s = unicodedata.normalize("NFKC", raw or "")
    s = _TRADEMARK.sub("", s)
    s = _DASH.sub("-", s)
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(" ,;.")


def _has_stereo_paren(text: str) -> bool:
    """括号里是 R/S/E/Z/D/L 等立体描述时不动，避免改掉立体化学。"""
    for content in _PAREN.findall(text):
        c = content.strip().lower()
        if c in {"r", "s", "e", "z", "d", "l", "dl", "±", "+", "-"}:
            return True
        if c.startswith("±") or c.startswith("+/-"):
            return True
    return False


def _is_qualifier_paren(content: str) -> bool:
    """括号内容是否只是盐型/晶型/同位素/编码/包装说明等限定语。"""
    lc = content.strip().lower()
    if not lc:
        return True
    if lc.startswith("as "):
        return True
    words = re.findall(r"[a-z]+", lc)
    if any(w in PAREN_QUALIFIER_WORDS for w in words):
        return True
    if re.search(r"[→%]", lc):
        return True
    if re.search(r"\b\d+(?:\.\d+)?\s*(?:mg|ml|g|mcg|μg|ug|iu)\b", lc):
        return True
    if re.fullmatch(r"\d+[a-z]?", lc):              # 18F
        return True
    if re.fullmatch(r"[a-z]{1,3}-?\d+", lc):        # cr-51
        return True
    if any(ord(ch) > 127 for ch in content):         # 韩文/中文包装说明
        return True
    if re.fullmatch(r"[A-Z0-9][A-Z0-9-]{2,}", content) and any(ch.isdigit() for ch in content):
        return True                                  # CKD-602
    return False


def paren_variant(text: str) -> str:
    """去括号：限定语括号删内容；化学分组括号只去括号、保留内容。"""
    if _has_stereo_paren(text):
        return text
    out = text
    for _ in range(2):
        out = _PAREN.sub(
            lambda m: " " if _is_qualifier_paren(m.group(1)) else f" {m.group(1)} ",
            out,
        )
    if "(" in out:                                   # 未闭合括号：多为包装说明，截断
        out = out[: out.rindex("(")]
    return re.sub(r"\s+", " ", out).strip(" ,;.-")


def split_combo(text: str) -> list[str]:
    """复方拆分：+ & ; / and with；中文 A/B 连写也拆。"""
    parts = [p.strip(" ,;.-") for p in _COMBO_RE.split(text) if p.strip(" ,;.-")]
    if len(parts) == 1 and "/" in text:
        alt = [p.strip() for p in _CJK_SLASH.split(text) if p.strip()]
        if len(alt) > 1:
            parts = alt
    return parts if len(parts) > 1 else []


def strip_tail_candidates(text: str, stems: set[str]) -> list[str]:
    """从尾部逐词剥 stems，返回由轻到重的候选串；处理化学计量数字与复合词。"""
    words = text.split()
    out: list[str] = []
    while words:
        last = words[-1].strip(".,;")
        low = last.lower()
        parts = [p for p in re.split(r"[-–—]", low) if p]
        # 复合盐词 "sulfate-iron" → ["sulfate", "iron"]，逐段剥并保留中间候选
        if len(parts) > 1 and all(p in stems for p in parts):
            words[-1:] = parts
            continue
        if low in stems or _NUM.fullmatch(low):
            words.pop()
            while words and words[-1].strip(".,;").lower() in STOICH_WORDS:
                words.pop()
            cand = " ".join(words).strip(" ,;.-")
            if cand and cand not in out:
                out.append(cand)
            continue
        break
    return out


def coformer_candidates(text: str) -> list[str]:
    """去共晶配体（如 dapagliflozin Bis L-proline → dapagliflozin）。"""
    words = text.split()
    out: list[str] = []
    while words:
        last = words[-1].strip(".,;").lower()
        parts = [p for p in re.split(r"[-–—]", last) if p]
        if (
            parts
            and any(p in COFORMER_STEMS for p in parts)
            and all(p in COFORMER_STEMS or p in {"l", "d", "dl"} for p in parts)
        ):
            words.pop()
            while words and words[-1].strip(".,;").lower() in STOICH_WORDS:
                words.pop()
            cand = " ".join(words).strip(" ,;.-")
            if cand and cand not in out:
                out.append(cand)
            continue
        break
    return out


def dirty_candidates(text: str) -> list[str]:
    """数据脏前缀/编码残留：``Equivalent:``、``.Mu.``。"""
    out: list[str] = []
    t = re.sub(r"^\s*equivalent\s*:\s*", "", text, flags=re.IGNORECASE)
    if t != text:
        out.append(t)
    t2 = re.sub(r"^\.?\s*mu\.?\s*", "Mu ", text, flags=re.IGNORECASE)
    t2 = re.sub(r"\.mu\.", "Mu ", t2, flags=re.IGNORECASE)
    t2 = re.sub(r"\s+", " ", t2).strip(" ,;.-")
    if t2 != text:
        out.append(t2)
    return out


def is_safe_candidate(name: str) -> tuple[bool, str]:
    """拦截会配错药的候选：只剩金属离子、只剩通用词、以连接词结尾等。"""
    if len(name) < 2:
        return False, "太短"
    low = name.lower().strip()
    tokens = re.findall(r"[a-z0-9]+", low)
    if not tokens:
        # 非拉丁名（中文等）按原样查询；至少 2 个字符
        return (len(name) >= 2), ("非拉丁名" if len(name) >= 2 else "太短")
    if tokens[-1] in BAD_TAIL:
        return False, f"以连接词 {tokens[-1]} 结尾"
    if len(tokens) == 1 and (
        tokens[0] in METAL_ADJ
        or tokens[0] in SALT_STEMS
        or tokens[0] in ELEMENT_STEMS
        or tokens[0] in STOP_SINGLE
    ):
        return False, "只剩盐/元素/通用词（会配成离子或泛称）"
    if all(t in STOP_SINGLE for t in tokens):
        return False, "只剩通用词"
    return True, ""


def build_candidates(raw: str) -> list[tuple[str, str]]:
    """按「轻 → 重」生成规范化候选；每档只生成语义等价的写法。"""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    def add(stage: str, text: str) -> None:
        q = re.sub(r"\s+", " ", (text or "")).strip(" ,;.-")
        if not q or q.casefold() == raw.casefold():
            return
        key = q.casefold()
        if key in seen:
            return
        ok, _reason = is_safe_candidate(q)
        if not ok:
            return
        seen.add(key)
        out.append((stage, q))

    base = clean_text(raw)
    add("clean", base)
    paren = paren_variant(base)
    add("paren", paren)

    for text in dict.fromkeys((base, paren)):
        for cand in strip_tail_candidates(text, LIGHT_STRIP_STEMS):
            add("salt", cand)
        for cand in strip_tail_candidates(text, SALT_STRIP_STEMS):
            add("salt", cand)

    for text in dict.fromkeys((base, paren)):
        for part in split_combo(text):
            add("combo", part)
            for cand in strip_tail_candidates(part, SALT_STRIP_STEMS):
                add("combo", cand)

    for text in dict.fromkeys((base, paren)):
        for cand in coformer_candidates(text):
            add("coformer", cand)

    for cand in dirty_candidates(base):
        add("dirty", cand)

    return out


# ---------------------------------------------------------------------------
# PubChem PUG-REST
# ---------------------------------------------------------------------------
def _throttle() -> None:
    global _last_request
    wait = MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


@dataclass
class QueryStats:
    """本轮请求计数（缓存命中也要算，报告里写清）。"""

    new_requests: int = 0
    cache_hits: int = 0
    http_200: int = 0
    http_404: int = 0
    http_other: int = 0
    retries: int = 0
    errors: int = 0


class CidCache:
    """查询 → 状态/CID 的 JSONL 缓存；同一查询不重复打网络。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rows: dict[str, dict] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                q = (rec.get("q") or "").strip()
                if q:
                    self.rows[q.casefold()] = rec

    def get(self, name: str) -> dict | None:
        return self.rows.get(name.strip().casefold())

    def put(self, rec: dict) -> None:
        key = rec["q"].strip().casefold()
        self.rows[key] = rec
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def query_cid(name: str, cache: CidCache, stats: QueryStats) -> dict:
    """查 ``/compound/name/<name>/cids/JSON``；404 不重试，429/5xx 退避重试。"""
    cached = cache.get(name)
    if cached is not None:
        stats.cache_hits += 1
        return cached

    url = f"{BASE}/compound/name/{urllib.parse.quote(name, safe='')}/cids/JSON"
    last_error = ""
    for attempt in range(MAX_TRIES):
        _throttle()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                data = json.loads(body)
                cids = [int(c) for c in data.get("IdentifierList", {}).get("CID", [])]
                rec = {
                    "q": name,
                    "status": 200 if cids else 404,
                    "cids": cids,
                    "elapsed_s": round(time.perf_counter() - t0, 3),
                    "bytes": len(body),
                    "ts": bj_now(),
                }
                stats.new_requests += 1
                if cids:
                    stats.http_200 += 1
                else:
                    stats.http_404 += 1
                cache.put(rec)
                return rec
        except urllib.error.HTTPError as exc:
            elapsed = round(time.perf_counter() - t0, 3)
            if exc.code == 404:
                rec = {"q": name, "status": 404, "cids": [], "elapsed_s": elapsed,
                       "bytes": 0, "ts": bj_now()}
                stats.new_requests += 1
                stats.http_404 += 1
                cache.put(rec)
                return rec
            if exc.code in RETRY_CODES and attempt < MAX_TRIES - 1:
                stats.retries += 1
                time.sleep(2.0 * (attempt + 1))
                continue
            rec = {"q": name, "status": exc.code, "cids": [], "elapsed_s": elapsed,
                   "bytes": 0, "ts": bj_now()}
            stats.new_requests += 1
            stats.http_other += 1
            cache.put(rec)
            return rec
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            last_error = str(exc)[:200]
            if attempt < MAX_TRIES - 1:
                stats.retries += 1
                time.sleep(2.0 * (attempt + 1))
                continue
    rec = {"q": name, "status": -1, "cids": [], "elapsed_s": 0.0, "bytes": 0,
           "error": last_error, "ts": bj_now()}
    stats.new_requests += 1
    stats.errors += 1
    cache.put(rec)
    return rec


# ---------------------------------------------------------------------------
# 失败分类
# ---------------------------------------------------------------------------
_BIO_SUFFIXES = ("mab", "cept", "ase", "cog", "tide", "kin", "toxoid", "fab")
_BIO_WORDS = {
    "vaccine", "toxoid", "immunoglobulin", "antibody", "interferon", "insulin",
    "factor", "plasma", "serum", "cell", "culture", "recombinant", "antigen",
    "allergen", "blood", "human", "bovine", "porcine", "equine", "ovine",
    "collagen", "heparin", "danaparoid", "enzyme", "protein", "peptide",
    "bifidobacterium", "lactobacillus", "probiotic", "strain", "virus",
    "bacteria", "pneumococcal", "streptococcus", "polysaccharide", "conjugate",
    "conjugated", "cfu", "antitoxin", "venom", "dust", "pollen", "prick",
    "vaccinia", "papilloma", "hpv", "toxin", "fab",
}
_BOTANICAL_WORDS = {
    "extract", "ext", "tincture", "tinc", "powder", "oil", "root", "leaf",
    "leaves", "whole", "seed", "flower", "herb", "pollen", "fruit", "bark",
    "rhizome", "tuber", "wood", "plant", "cortex", "resin", "gum", "algae",
    "fungus", "mushroom", "yeast", "shell", "bone", "organ", "tissue",
    "placenta", "heart", "liver", "egg", "milk", "whey", "casein",
    # 植物/动物/真菌名（抽样里出现、常混在 inn_en 里）
    "agrimony", "arnica", "cocillana", "reishi", "rhubarb", "balsam",
    "quahog", "ononis", "lilium", "tigrinum", "senna", "nux", "vomica",
    "thistle", "cynara", "jujube", "polygala", "zanthoxylum", "bellis",
    "echinacea", "ginseng", "valerian", "passiflora", "melissa", "mentha",
    "salvia", "thymus", "oregano", "lavender", "rosemary", "fennel", "anise",
    "ginger", "turmeric", "garlic", "onion", "lemon", "orange", "grape",
    "apple", "beet", "carrot", "spinach", "alfalfa", "kelp", "spirulina",
    "chlorella", "pituitary", "sus", "scrofa",
}
_HOMEO_WORDS = {"homeopath", "homeopathica", "dilution", "dilutio"}
_DEVICE_WORDS = {"kit", "test", "reagent", "diagnostic", "device", "catheter", "strip"}
_FORM_WORDS = {
    "lotion", "cream", "ointment", "gel", "injection", "injections", "tablet",
    "tablets", "capsule", "capsules", "sachet", "sachets", "bag", "bags",
    "cylinder", "cylinders", "ampoule", "ampoules", "vial", "vials",
    "granules", "syrup", "drops", "spray", "inhaler", "suppository", "patch",
    "solution", "suspension", "powder", "conc", "concentrate", "liquid",
    "emulsion", "soluble", "sterile", "intravenous", "oral", "topical",
}
_GENERIC_RE = re.compile(r"^\s*generic\b", re.IGNORECASE)
_DOSE_RE = re.compile(r"\d+(?:[.,]\d+)?\s*%|\b\d+(?:[.,]\d+)?\s*(?:mg|ml|g|mcg|μg|iu)\b",
                      re.IGNORECASE)


def _looks_like_generic_or_form(low: str, tokens: list[str]) -> bool:
    """Generic 配方名 / 剂型浓度混合名：不是 INN，不应按名字硬配结构。"""
    if _GENERIC_RE.match(low):
        return True
    if _DOSE_RE.search(low):
        return True
    if tokens and tokens[-1] in _FORM_WORDS:
        return True
    if any(w in low for w in _FORM_WORDS) and len(tokens) <= 6:
        return True
    if low.strip(" .") in {"s.a.", "s a", "sa"}:
        return True
    return False


def structure_eligible(name: str) -> bool:
    """「值得/能够放一张小分子结构图」的粗筛（只用于外推，不改数据）。

    排除：非 ASCII（中文/本地文字）、生物制品、草药/动植物、顺势药、复方、
    剂型/浓度/Generic 配方名、数据脏名。剩下的才按小分子结构图看。
    """
    if not all(ord(ch) < 128 for ch in name):
        return False
    low = name.lower()
    tokens = re.findall(r"[a-z0-9]+", low)
    if name.startswith("Equivalent:") or ".mu." in low:
        return False
    if any(t.endswith(_BIO_SUFFIXES) for t in tokens) or any(w in low for w in _BIO_WORDS):
        return False
    if any(w in low for w in _BOTANICAL_WORDS):
        return False
    if any(w in low for w in _HOMEO_WORDS) or re.search(r"\b\d+\s*[cd]\b", low):
        return False
    if split_combo(name):
        return False
    if any(w in low for w in _DEVICE_WORDS):
        return False
    if _looks_like_generic_or_form(low, tokens):
        return False
    return True


def classify_miss(name: str, raw: str) -> str:
    """给最终未命中的样本归类（规则优先，允许一条同时符合多类）。"""
    low = name.lower()
    tokens = re.findall(r"[a-z0-9]+", low)
    if raw.startswith("Equivalent:") or ".mu." in low:
        return "数据脏（前缀/编码残留）"
    if any("\u4e00" <= ch <= "\u9fff" for ch in name):
        return "中文名（名字匹配无解，需翻译/映射）"
    if any(ord(ch) > 127 for ch in name):
        return "非英文/本地文字（重音、韩文残留等）"
    if _GENERIC_RE.match(low):
        return "非 INN（Generic/配方名）"
    if any(t.endswith(_BIO_SUFFIXES) for t in tokens) or any(w in low for w in _BIO_WORDS):
        return "生物制品/疫苗/抗体（无小分子 2D 结构）"
    if any(w in low for w in _BOTANICAL_WORDS):
        return "草药/提取物/动植物组织"
    if any(w in low for w in _HOMEO_WORDS) or re.search(r"\b\d+\s*c\b", low):
        return "顺势药/稀释液"
    if split_combo(name):
        return "复方（拆分后各段仍无命中）"
    if tokens and tokens[-1] in SALT_STRIP_STEMS:
        return "盐/酯形式（基名也无 PubChem 记录）"
    if any(w in low for w in _DEVICE_WORDS):
        return "诊断/器械/辅料"
    if _looks_like_generic_or_form(low, tokens):
        return "非 INN（剂型/浓度/混合物）"
    return "拼写/语言变体或非 INN（未归类）"


def count_eligible(db_path: Path) -> int:
    """全表按同一粗筛口径数「小分子可结构面」条数。"""
    uri = f"file:{db_path.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=60)
    try:
        return sum(1 for (name,) in con.execute("SELECT inn_en FROM substance")
                   if structure_eligible(name))
    finally:
        con.close()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def evaluate(sample: list[tuple[str, str, str]], cache: CidCache,
             stats: QueryStats) -> list[dict]:
    """逐条样本跑 raw → 规范化候选；命中即停，记录第一命中档位。"""
    rows: list[dict] = []
    for i, (sid, name, atc) in enumerate(sample, 1):
        raw_rec = query_cid(name, cache, stats)
        row: dict = {
            "substance_id": sid,
            "inn_en": name,
            "atc": atc,
            "ascii": all(ord(ch) < 128 for ch in name),
            "han": any("\u4e00" <= ch <= "\u9fff" for ch in name),
            "eligible": structure_eligible(name),
            "raw_status": raw_rec["status"],
            "raw_cids": raw_rec.get("cids", []),
            "raw_cid": (raw_rec.get("cids") or [None])[0],
            "hit_stage": None,
            "hit_query": None,
            "hit_cid": None,
            "hit_n_cids": 0,
            "tried": [],
        }
        tried: list[dict] = []
        if raw_rec.get("cids"):
            row["hit_stage"] = "raw"
            row["hit_query"] = name
            row["hit_cid"] = raw_rec["cids"][0]
            row["hit_n_cids"] = len(raw_rec["cids"])
        else:
            for stage, cand in build_candidates(name):
                rec = query_cid(cand, cache, stats)
                tried.append({
                    "stage": stage,
                    "q": cand,
                    "status": rec["status"],
                    "n_cids": len(rec.get("cids") or []),
                })
                if rec.get("cids"):
                    row["hit_stage"] = stage
                    row["hit_query"] = cand
                    row["hit_cid"] = rec["cids"][0]
                    row["hit_n_cids"] = len(rec["cids"])
                    break
        row["tried"] = tried
        if row["hit_stage"] is None:
            row["miss_class"] = classify_miss(name, name)
        rows.append(row)
        if i % 25 == 0:
            n_hit = sum(1 for r in rows if r["hit_stage"])
            print(f"[eval] {i}/{len(sample)} hits={n_hit} "
                  f"queries={stats.new_requests} cache={stats.cache_hits}", flush=True)
    return rows


def summarize(rows: list[dict], sample_stats: dict[str, int], stats: QueryStats,
              elapsed_s: float) -> dict:
    """汇总 before / after、分档增量、语言子集、失败分类与外推。"""
    n = len(rows)
    before = sum(1 for r in rows if r["hit_stage"] == "raw")
    after_core = sum(1 for r in rows if r["hit_stage"] in CORE_STAGES)
    after_ext = sum(1 for r in rows if r["hit_stage"] in EXTENDED_STAGES)
    stage_counts: Counter[str] = Counter(r["hit_stage"] for r in rows if r["hit_stage"])
    miss_counts: Counter[str] = Counter(r["miss_class"] for r in rows if not r["hit_stage"])

    ascii_rows = [r for r in rows if r["ascii"]]
    han_rows = [r for r in rows if r["han"]]
    atc_rows = [r for r in rows if r["atc"]]

    def rate(k: int, d: int) -> float:
        return round(k / d, 4) if d else 0.0

    def subset(rs: list[dict]) -> dict:
        b = sum(1 for r in rs if r["hit_stage"] == "raw")
        c = sum(1 for r in rs if r["hit_stage"] in CORE_STAGES)
        e = sum(1 for r in rs if r["hit_stage"] in EXTENDED_STAGES)
        return {
            "n": len(rs),
            "before": b,
            "before_rate": rate(b, len(rs)),
            "after_core": c,
            "after_core_rate": rate(c, len(rs)),
            "after_extended": e,
            "after_extended_rate": rate(e, len(rs)),
        }

    ascii_stats = subset(ascii_rows)
    han_stats = subset(han_rows)
    atc_stats = subset(atc_rows)
    eligible_stats = subset([r for r in rows if r.get("eligible")])

    # 外推：① 按样本整体比例；② 按「ASCII 名命中率 × 全表 ASCII 名」；
    # ③ 按「小分子可结构面命中率 × 全表同口径条数」
    total = sample_stats["substance_total"]
    est_simple = round(after_core / n * total) if n else 0
    est_ascii = round(rate(ascii_stats["after_core"], ascii_stats["n"])
                      * sample_stats["ascii_total"]) if ascii_stats["n"] else 0
    eligible_total = sample_stats.get("eligible_total", 0)
    est_eligible = round(rate(eligible_stats["after_core"], eligible_stats["n"])
                         * eligible_total) if eligible_stats["n"] else 0
    est_ext = round(after_ext / n * total) if n else 0

    def volume_mb(n_images: int, bytes_per: int) -> float:
        return round(n_images * bytes_per / 1024 / 1024, 2)

    # 原始命中在规范化阶段只会保留、不会丢；新增命中数 = 差值，可直接做 McNemar 精确检验
    new_core = after_core - before
    new_ext = after_ext - before
    mcnemar_core = min(1.0, 2 * 0.5 ** new_core) if new_core > 0 else 1.0
    mcnemar_ext = min(1.0, 2 * 0.5 ** new_ext) if new_ext > 0 else 1.0

    multi = [r for r in rows if r["hit_stage"] and r["hit_n_cids"] > 1]
    return {
        "n": n,
        "before_hits": before,
        "before_rate": rate(before, n),
        "after_core_hits": after_core,
        "after_core_rate": rate(after_core, n),
        "after_extended_hits": after_ext,
        "after_extended_rate": rate(after_ext, n),
        "lift_core": after_core - before,
        "lift_extended": after_ext - before,
        "mcnemar_p_core": round(mcnemar_core, 5),
        "mcnemar_p_extended": round(mcnemar_ext, 5),
        "stage_counts": dict(stage_counts),
        "miss_counts": dict(miss_counts.most_common()),
        "ascii": ascii_stats,
        "han": han_stats,
        "atc": atc_stats,
        "eligible": eligible_stats,
        "multi_cid_hits": len(multi),
        "multi_cid_examples": [
            {"inn_en": r["inn_en"], "cid": r["hit_cid"], "n_cids": r["hit_n_cids"]}
            for r in multi[:10]
        ],
        "query_stats": {
            "new_requests": stats.new_requests,
            "cache_hits": stats.cache_hits,
            "http_200": stats.http_200,
            "http_404": stats.http_404,
            "http_other": stats.http_other,
            "retries": stats.retries,
            "errors": stats.errors,
        },
        "elapsed_s": round(elapsed_s, 1),
        "estimate": {
            "substance_total": total,
            "ascii_total": sample_stats["ascii_total"],
            "han_total": sample_stats["han_total"],
            "nonascii_total": sample_stats["nonascii_total"],
            "atc_total": sample_stats["atc_total"],
            "eligible_total": eligible_total,
            "est_hits_simple": est_simple,
            "est_hits_ascii_adjusted": est_ascii,
            "est_hits_eligible": est_eligible,
            "est_hits_extended": est_ext,
            "img300_avg_bytes": IMG300_AVG_B,
            "img300_range_bytes": [IMG300_MIN_B, IMG300_MAX_B],
            "img200_avg_bytes": IMG200_AVG_B,
            "mb300_simple": volume_mb(est_simple, IMG300_AVG_B),
            "mb300_ascii_adjusted": volume_mb(est_ascii, IMG300_AVG_B),
            "mb300_eligible": volume_mb(est_eligible, IMG300_AVG_B),
            "mb300_eligible_min": volume_mb(est_eligible, IMG300_MIN_B),
            "mb300_eligible_max": volume_mb(est_eligible, IMG300_MAX_B),
            "mb200_eligible": volume_mb(est_eligible, IMG200_AVG_B),
            "mb300_min": volume_mb(est_ascii, IMG300_MIN_B),
            "mb300_max": volume_mb(est_ascii, IMG300_MAX_B),
            "mb200_ascii_adjusted": volume_mb(est_ascii, IMG200_AVG_B),
        },
    }


def plan_only(sample: list[tuple[str, str, str]], sample_stats: dict[str, int]) -> None:
    """不发请求，只打印样本构成与候选量（网络前自检）。"""
    cands = [build_candidates(r[1]) for r in sample]
    uniq = {c.casefold() for row in cands for _s, c in row}
    print("=== plan（不发请求） ===")
    print(f"样本               : {len(sample)} / 全表 {sample_stats['substance_total']:,}")
    print(f"全表 ASCII/中文/非ASCII/有ATC: "
          f"{sample_stats['ascii_total']:,} / {sample_stats['han_total']:,} / "
          f"{sample_stats['nonascii_total']:,} / {sample_stats['atc_total']:,}")
    print(f"全表小分子可结构面（粗筛）  : {sample_stats.get('eligible_total', 0):,}")
    print(f"样本 ASCII/中文/有ATC       : "
          f"{sum(1 for r in sample if all(ord(ch) < 128 for ch in r[1]))} / "
          f"{sum(1 for r in sample if any(chr(0x4e00) <= ch <= chr(0x9fff) for ch in r[1]))} / "
          f"{sum(1 for r in sample if r[2])}")
    print(f"候选总条数（逐样本）        : {sum(len(x) for x in cands):,}")
    print(f"候选去重后（含 raw 300）    : {len(uniq) + len(sample):,}")
    stage = Counter(s for row in cands for s, _q in row)
    print(f"按档位                     : {dict(stage.most_common())}")
    print("前 10 个样本的候选（示例）  :")
    for (sid, name, _atc), row in list(zip(sample, cands))[:10]:
        print(f"  - {name!r} -> {row[:4]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--limit", type=int, default=N_SAMPLE)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--run", action="store_true", help="真跑（默认）；--plan 时只算候选")
    ap.add_argument("--plan", action="store_true", help="只打印样本/候选，不发请求")
    ap.add_argument("--refresh", action="store_true", help="忽略旧缓存（仍会追加写）")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)

    if not args.db.exists():
        print(f"数据库不存在：{args.db}", file=sys.stderr)
        return 1

    sample, sample_stats = load_sample(args.db, args.limit, args.seed)
    sample_stats["eligible_total"] = count_eligible(args.db)
    if args.plan:
        plan_only(sample, sample_stats)
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    cache = CidCache(args.out_dir / "cid-cache.jsonl")
    if args.refresh:
        cache.rows.clear()
    stats = QueryStats()
    t0 = time.perf_counter()
    started_bj = bj_now()
    print(f"start {started_bj} seed={args.seed} n={len(sample)} "
          f"delay={MIN_INTERVAL}s", flush=True)
    rows = evaluate(sample, cache, stats)
    summary = summarize(rows, sample_stats, stats, time.perf_counter() - t0)
    result = {
        "meta": {
            "run_started_bj": started_bj,
            "run_finished_bj": bj_now(),
            "seed": args.seed,
            "limit": args.limit,
            "db": str(args.db),
            "endpoint": BASE + "/compound/name/<name>/cids/JSON",
            "user_agent": UA,
            "min_interval_s": MIN_INTERVAL,
            "cache": str(args.out_dir / "cid-cache.jsonl"),
            "stages": STAGE_LABEL,
            "core_stages": sorted(CORE_STAGES),
            "extended_stages": sorted(EXTENDED_STAGES),
        },
        "sample_stats": sample_stats,
        "summary": summary,
        "rows": rows,
    }
    result_path = args.out_dir / "eval-300.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    s = summary
    print("=== 结果 ===")
    print(f"before raw        : {s['before_hits']}/{s['n']} = {s['before_rate']:.1%}")
    print(f"after core        : {s['after_core_hits']}/{s['n']} = {s['after_core_rate']:.1%}"
          f"（+{s['lift_core']}）")
    print(f"after extended    : {s['after_extended_hits']}/{s['n']} = "
          f"{s['after_extended_rate']:.1%}（+{s['lift_extended']}）")
    print(f"分档命中          : {s['stage_counts']}")
    print(f"失败分类          : {s['miss_counts']}")
    print(f"McNemar 精确 p    : core={s['mcnemar_p_core']} / extended={s['mcnemar_p_extended']}")
    print(f"ASCII after core  : {s['ascii']['after_core']}/{s['ascii']['n']} = "
          f"{s['ascii']['after_core_rate']:.1%}")
    print(f"ATC   after core  : {s['atc']['after_core']}/{s['atc']['n']} = "
          f"{s['atc']['after_core_rate']:.1%}")
    print(f"可结构面 after    : {s['eligible']['after_core']}/{s['eligible']['n']} = "
          f"{s['eligible']['after_core_rate']:.1%}（全表同口径 "
          f"{s['estimate']['eligible_total']:,} 条）")
    print(f"全量外推（简单）  : {s['estimate']['est_hits_simple']:,} 张 / "
          f"{s['estimate']['mb300_simple']} MB（300px 均值）")
    print(f"全量外推（ASCII） : {s['estimate']['est_hits_ascii_adjusted']:,} 张 / "
          f"{s['estimate']['mb300_ascii_adjusted']} MB（300px 均值，"
          f"{s['estimate']['mb300_min']}–{s['estimate']['mb300_max']} MB @1.6–4.1 KB）")
    print(f"全量外推（可结构）: {s['estimate']['est_hits_eligible']:,} 张 / "
          f"{s['estimate']['mb300_eligible']} MB（300px 均值，"
          f"{s['estimate']['mb300_eligible_min']}–{s['estimate']['mb300_eligible_max']} MB）")
    print(f"请求              : 新增 {s['query_stats']['new_requests']} / 缓存 "
          f"{s['query_stats']['cache_hits']} / 200 {s['query_stats']['http_200']} / "
          f"404 {s['query_stats']['http_404']} / 其他 {s['query_stats']['http_other']} / "
          f"重试 {s['query_stats']['retries']} / 错误 {s['query_stats']['errors']}")
    print(f"耗时              : {s['elapsed_s']} s")
    print(f"结果              : {result_path}")
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
