#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""三语搜索评测集扩容生成器：72 → 320 例（v2.0，seed=20261027）。

设计依据：`reports/who-inn-merge.md` §6（八类用例规则/配额/反循环论证原则）。
本脚本**只读** `data/drugs.db`，不调用 `lib/search.py`（期望全部来自 DB 结构关系与
规则表，避免「用检索输出反推期望」）；生成结果冻结为 `tests/trilingual/cases_v2.json`。

八类配额（合计 320）：
    en_typo 45 / es_typo 30 / zh_char_typo 25 / pinyin 40 / jianfan 30 /
    combo 55（40 trade + 15 joined 成分）/ salt 55（40 商品名 + 15 INN+salt）/
    zero_result 40

期望策略：
    must_hit    Top-5 内出现期望成分（CI 卡口统计）
    must_empty  0 结果（零结果误命中是硬伤）
    gap         当前基线预期 miss、作为改造目标（拼音 / 复方成分拼接）

依赖（均为仓库现有数据，无需联网安装）：
    拼音字表：site/build.py 内嵌 `_PINYIN_CHARS_TEXT`（1,582 字），缺失时回退
              `.tmp/search-bench/pinyin_chars.json`
    简繁表  ：etl/normalize_name.py `_T2S`（90 对；未覆盖字不生成简体→繁体例）
    WHO 西语：data/who_inn_names.csv（WHO INN 官方列表解析产物）

用法：
    python tests/trilingual/gen_cases.py                # 生成 cases_v2.json
    python tests/trilingual/gen_cases.py --dry-run      # 只统计不落盘
"""
from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import random
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "etl"))
from normalize_name import _T2S, normalize  # noqa: E402

DB = ROOT / "data" / "drugs.db"
OUT = ROOT / "tests" / "trilingual" / "cases_v2.json"
WHO = ROOT / "data" / "who_inn_names.csv"
BUILD_PY = ROOT / "site" / "build.py"
PINYIN_FALLBACK = ROOT / ".tmp" / "search-bench" / "pinyin_chars.json"
SEED = 20261027
QUOTAS = {
    "en_typo": 45,
    "es_typo": 30,
    "zh_char_typo": 25,
    "pinyin": 40,
    "jianfan": 30,
    "combo": 55,
    "salt": 55,
    "zero_result": 40,
}
TOTAL = sum(QUOTAS.values())

# 中文形近/音近混淆表（人工 curated；用于 zh_char_typo）
ZH_CONFUSIONS = [
    ("氨", "胺"), ("胺", "按"), ("氯", "禄"), ("唑", "坐"), ("嗪", "秦"),
    ("噻", "塞"), ("啶", "定"), ("哌", "派"), ("洛", "络"), ("坦", "担"),
    ("汀", "丁"), ("沙", "砂"), ("松", "淞"), ("泮", "判"), ("磺", "黄"),
    ("孢", "胞"), ("霉", "梅"), ("素", "苏"), ("酞", "太"), ("酯", "脂"),
    ("酮", "铜"), ("酚", "分"), ("醛", "全"), ("钠", "纳"), ("钾", "甲"),
    ("镁", "美"), ("钙", "丐"), ("锌", "辛"), ("铁", "贴"), ("林", "淋"),
    ("韦", "伟"), ("替", "梯"), ("卡", "咖"), ("吗", "马"), ("啡", "非"),
    ("因", "音"), ("仑", "伦"), ("硝", "消"), ("苯", "本"), ("胍", "瓜"),
    ("脲", "尿"), ("星", "兴"), ("特", "忒"), ("罗", "逻"), ("米", "咪"),
]
# QWERTY 键盘邻键表（用于拉丁错拼）
QWERTY_NEIGHBORS = {
    "q": "wa", "w": "qeas", "e": "wrsd", "r": "etdf", "t": "ryfg", "y": "tugh",
    "u": "yihj", "i": "uojk", "o": "ipkl", "p": "ol", "a": "qwsz", "s": "awedxz",
    "d": "serfxc", "f": "drtgvc", "g": "ftyhbv", "h": "gyujnb", "j": "huikmn",
    "k": "jiolm", "l": "kop", "z": "asx", "x": "zsdc", "c": "xdfv", "v": "cfgb",
    "b": "vghn", "n": "bhjm", "m": "njk",
}
NON_DRUG_QUERIES = ["hello", "tablet", "20 mg", "untitled", "qwerty", "zzzzzz",
                    "nothing here", "not a drug", "random text", "foo bar",
                    "药药药", "测试", "你好", "未知名称"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_pinyin() -> dict[str, str]:
    """汉字 → 无调拼音（site/build.py 内嵌字表，回退 .tmp 缓存）。"""
    m = re.search(r'_PINYIN_CHARS_TEXT\s*=\s*"([^"]+)"',
                  BUILD_PY.read_text(encoding="utf-8"))
    if m:
        out = {}
        for tok in m.group(1).split():
            if ":" in tok:
                ch, py = tok.split(":", 1)
                out[ch] = py
        if out:
            return out
    if PINYIN_FALLBACK.exists():
        return json.loads(PINYIN_FALLBACK.read_text(encoding="utf-8"))
    return {}


# ---------------------------------------------------------------------------
# DB（只读）快照
# ---------------------------------------------------------------------------
class Data:
    def __init__(self, db_path: Path):
        self.con = sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True)
        self.con.row_factory = sqlite3.Row
        self.sub_inn: dict[str, str] = {}
        self.prod_sub: dict[str, frozenset] = {}
        self.prod_country: dict[str, str] = {}
        self.key_meta: dict[str, dict] = {}
        self.key_raw: dict[str, str] = {}
        self.key_products: dict[str, set[str]] = defaultdict(set)
        self._load()

    def _load(self) -> None:
        cur = self.con.cursor()
        for sid, inn in cur.execute("SELECT substance_id, inn_en FROM substance"):
            self.sub_inn[sid] = inn or sid
        comp: dict[str, set[str]] = defaultdict(set)
        for pid, sid in cur.execute(
                """SELECT pc.product_id, s.substance_id
                   FROM product_component pc
                   JOIN variant v ON v.variant_id = pc.variant_id
                   JOIN substance s ON s.substance_id = v.substance_id"""):
            comp[pid].add(sid)
        self.prod_sub = {pid: frozenset(v) for pid, v in comp.items()}
        for pid, country in cur.execute(
                "SELECT product_id, country FROM product WHERE status='active'"):
            self.prod_country[pid] = country
        for row in cur.execute(
                """SELECT pn.key_id, p.product_id, pn.name_type
                   FROM product_name pn JOIN product p ON p.product_id = pn.product_id
                   WHERE p.status='active'"""):
            self.key_products[row["key_id"]].add(row["product_id"])
            self.key_meta.setdefault(row["key_id"], {})["name_type"] = row["name_type"]
        self.prod_keys: dict[str, set[str]] = defaultdict(set)
        for key_id, pids in self.key_products.items():
            for pid in pids:
                self.prod_keys[pid].add(key_id)
        for row in cur.execute("SELECT key_id, norm, compact, script, lang FROM name_key"):
            self.key_meta.setdefault(row["key_id"], {}).update(
                norm=row["norm"], compact=row["compact"],
                script=row["script"], lang=row["lang"])
        for key_id, raw in cur.execute("SELECT key_id, raw FROM name_variant"):
            self.key_raw.setdefault(key_id, raw)
        # 每个 key 的「一致成分集合」：该 key 下所有 active 产品成分集合相同才算稳定
        self.stable_keys: dict[str, dict] = {}
        for key_id, pids in self.key_products.items():
            if key_id not in self.key_meta:
                continue
            comps = {self.prod_sub.get(p) for p in pids}
            comps.discard(None)
            if not comps:
                continue
            if len(comps) != 1:
                continue
            subs = next(iter(comps))
            if not subs:
                continue
            countries = {self.prod_country.get(p) for p in pids}
            countries.discard(None)
            meta = self.key_meta[key_id]
            raw = self.key_raw.get(key_id) or meta.get("norm") or ""
            self.stable_keys[key_id] = dict(
                key_id=key_id, norm=meta.get("norm") or "", script=meta.get("script"),
                lang=meta.get("lang"), name_type=meta.get("name_type"),
                raw=raw, subs=sorted(subs), countries=sorted(countries),
                n_products=len(pids))
        # 盐型 variant → 产品（先取完 variant 行，避免嵌套游标打断外层迭代）
        self.salt_products: dict[str, list[tuple[str, str]]] = defaultdict(list)
        salt_variants = cur.execute(
            "SELECT variant_id, substance_id, salt FROM variant WHERE salt<>''").fetchall()
        active_products = set(self.prod_country)
        for vid, sid, salt in salt_variants:
            for (pid,) in cur.execute(
                    "SELECT DISTINCT product_id FROM product_component WHERE variant_id=?",
                    (vid,)):
                if pid in active_products:
                    self.salt_products[sid].append((pid, salt))

    def all_substance_norms(self) -> dict[str, str]:
        return {normalize(inn).norm: sid for sid, inn in self.sub_inn.items()}


# ---------------------------------------------------------------------------
# 查询构造工具
# ---------------------------------------------------------------------------
def mutate_latin(rng: random.Random, word: str) -> str | None:
    """拉丁串做 1 次编辑：换位 40% / 邻键替换 30% / 删 20% / 插 10%。"""
    letters = [c for c in word]
    op = rng.choices(["transpose", "neighbor", "delete", "insert"],
                     weights=[40, 30, 20, 10])[0]
    if op == "transpose":
        idx = [i for i in range(len(letters) - 1)
               if letters[i].isalpha() and letters[i + 1].isalpha()
               and letters[i] != letters[i + 1]]
        if not idx:
            return None
        i = rng.choice(idx)
        letters[i], letters[i + 1] = letters[i + 1], letters[i]
    elif op == "neighbor":
        idx = [i for i, c in enumerate(letters) if c.lower() in QWERTY_NEIGHBORS]
        if not idx:
            return None
        i = rng.choice(idx)
        letters[i] = rng.choice(QWERTY_NEIGHBORS[letters[i].lower()])
    elif op == "delete":
        idx = [i for i in range(len(letters)) if letters[i].isalpha()]
        if not idx or len(word) <= 6:
            return None
        del letters[rng.choice(idx)]
    else:
        idx = [i for i in range(len(letters) + 1) if i > 0]
        if not idx:
            return None
        i = rng.choice(idx)
        letters.insert(i, rng.choice("abcdefghijklmnopqrstuvwxyz"))
    out = "".join(letters)
    if out.lower() == word.lower() or len(out) < 5:
        return None
    ratio = difflib.SequenceMatcher(None, out.lower(), word.lower()).ratio()
    if ratio < 0.78:
        return None  # 当前 fuzzy 门槛 0.75 + 余量；太离谱的错拼不作为「应命中」
    return out


def strip_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if not unicodedata.combining(c))


def mutate_zh(rng: random.Random, name: str) -> str | None:
    pairs = [(a, b) for a, b in ZH_CONFUSIONS if a in name and b != a]
    if not pairs:
        return None
    a, b = rng.choice(pairs)
    idx = [i for i, c in enumerate(name) if c == a]
    i = rng.choice(idx)
    out = name[:i] + b + name[i + 1:]
    return out if out != name else None


def to_traditional(name: str) -> str:
    inv: dict[str, str] = {}
    for trad, simp in _T2S.items():
        if trad != simp and simp not in inv:
            inv[simp] = trad
    return "".join(inv.get(c, c) for c in name)


# ---------------------------------------------------------------------------
# 负例 SQL 二次验证
# ---------------------------------------------------------------------------
class NegativeChecker:
    def __init__(self, db_path: Path):
        self.con = sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True)
        self.cur = self.con.cursor()
        self.alias_norms = {r[0] for r in self.cur.execute(
            "SELECT alias_norm FROM alias_all") if r[0]}
        self.confusable = {r[0] for r in self.cur.execute(
            "SELECT norm_a FROM confusable_pair") if r[0]} | {
            r[0] for r in self.cur.execute(
                "SELECT norm_b FROM confusable_pair") if r[0]}
        # 拉丁 name_key（模糊匹配复核用：search 的 fuzzy 门槛 0.75）
        self.latin_norms = [(norm or "") for (norm,) in self.cur.execute(
            "SELECT norm FROM name_key WHERE script='latin'")]


    def is_free(self, query: str) -> tuple[bool, str]:
        n = normalize(query)
        if not n.norm or not n.compact:
            return False, "归一化为空"
        cur = self.cur
        if cur.execute("SELECT 1 FROM name_key WHERE norm=? OR compact=? LIMIT 1",
                       (n.norm, n.compact)).fetchone():
            return False, "name_key 精确命中"
        if n.norm in self.alias_norms or n.compact in self.alias_norms:
            return False, "alias 精确命中"
        if n.norm in self.confusable or n.compact in self.confusable:
            return False, "confusable 命中"
        if n.script == "han":
            like = f"%{n.norm}%"
            if cur.execute("SELECT 1 FROM name_key WHERE script='han' AND norm LIKE ?"
                           " LIMIT 1", (like,)).fetchone():
                return False, "中文 name_key 子串命中"
            if cur.execute(
                    "SELECT 1 FROM name_variant nv JOIN name_key nk"
                    " ON nk.key_id=nv.key_id WHERE nk.script='han' AND nv.raw LIKE ?"
                    " LIMIT 1", (like,)).fetchone():
                return False, "中文原始名子串命中"
            if cur.execute("SELECT 1 FROM alias_all WHERE alias LIKE ? LIMIT 1",
                           (like,)).fetchone():
                return False, "中文 alias 子串命中"
        else:
            if len(n.norm) >= 4:
                if cur.execute(
                        "SELECT 1 FROM name_key WHERE script='latin' AND"
                        " (norm LIKE ? OR compact LIKE ?) LIMIT 1",
                        (f"%{n.norm}%", f"%{n.compact}%")).fetchone():
                    return False, "拉丁 name_key 子串命中"
                if cur.execute("SELECT 1 FROM name_variant nv"
                               " LEFT JOIN name_key nk ON nk.key_id=nv.key_id"
                               " WHERE nv.raw LIKE ? LIMIT 1",
                               (f"%{query}%",)).fetchone():
                    return False, "拉丁原始名子串命中"
                # fuzzy（lib/search.py 对 len>=4 的查询会做 ratio>=0.75 的模糊扩展）
                q = n.norm
                qset = set(q.replace(" ", ""))
                need = max(2, len(qset) // 2)
                for norm in self.latin_norms:
                    if abs(len(norm) - len(q)) > 3:
                        continue
                    if len(qset & set(norm)) < need:
                        continue
                    if difflib.SequenceMatcher(None, q, norm).ratio() >= 0.75:
                        return False, f"拉丁 fuzzy 命中（{norm}）"
        return True, ""


# ---------------------------------------------------------------------------
# 生成器
# ---------------------------------------------------------------------------
class Generator:
    def __init__(self, data: Data, rng: random.Random, pinyin: dict[str, str],
                 checker: NegativeChecker, db_sha: str):
        self.d = data
        self.rng = rng
        self.pinyin = pinyin
        self.checker = checker
        self.db_sha = db_sha
        self.cases: list[dict] = []
        self.used_queries: set[str] = set()
        self.shortages: dict[str, str] = {}

    def _add(self, category: str, lang: str, query: str, substance_ids: list[str],
             policy: str, query_type: str, provenance: dict,
             tags: list[str], min_tier: str | None = "top5") -> bool:
        qkey = query.strip().lower()
        if not qkey or qkey in self.used_queries:
            return False
        self.used_queries.add(qkey)
        idx = len([c for c in self.cases if c["category"] == category]) + 1
        self.cases.append(dict(
            case_id=f"v2-{category.replace('_', '-')}-{idx:04d}",
            category=category, lang=lang, query=query, query_type=query_type,
            country=None,
            expected=dict(substance_ids=sorted(substance_ids),
                          policy=policy,
                          min_tier=min_tier if policy != "must_empty" else None),
            expect_empty=(policy == "must_empty"),
            provenance=dict(provenance, generator="tests/trilingual/gen_cases.py v2.0",
                            seed=SEED, db_sha256=self.db_sha),
            tags=tags,
        ))
        return True

    # -- 通用筛选 --------------------------------------------------------
    def _keys(self, script=None, min_len=0, samples=None, name_type=None,
              require_subs=1, max_subs=1) -> list[dict]:
        out = []
        for k in self.d.stable_keys.values():
            if script and k["script"] != script:
                continue
            if len(k["norm"]) < min_len:
                continue
            if not (require_subs <= len(k["subs"]) <= max_subs):
                continue
            if name_type and k["name_type"] != name_type:
                continue
            out.append(k)
        samples = samples if samples is not None else list(out)
        self.rng.shuffle(samples)
        return samples

    # -- 1. en 错拼 ------------------------------------------------------
    def gen_en_typo(self, n: int) -> None:
        pool = self._keys(script="latin", min_len=6, max_subs=1)
        # 优先贸易名（更贴近用户输入），不足时用 INN 名
        trade = [k for k in pool if k["name_type"] == "trade"]
        inn = [k for k in pool if k["name_type"] != "trade"]
        candidates = trade + inn
        made = 0
        for k in candidates:
            word = k["raw"] if re.fullmatch(r"[A-Za-z][A-Za-z \-]+", k["raw"]) else k["norm"]
            word = word.strip()
            if len(word) < 6:
                continue
            q = mutate_latin(self.rng, word)
            if not q:
                continue
            if self._add("en_typo", "en", q, k["subs"], "must_hit", "typo",
                         dict(source="name_key/name_variant", row_ids=[k["key_id"]],
                              detail=f"{k['name_type']} {k['norm']} -> {q}",
                              countries=k["countries"]),
                         ["latin", k["name_type"] or "", "edit_distance_1"]):
                made += 1
                if made >= n:
                    return
        self.shortages["en_typo"] = f"只生成 {made}/{n}"

    # -- 2. es 错拼 ------------------------------------------------------
    def gen_es_typo(self, n: int) -> None:
        made = 0
        # a) ES/MX 本地名（去重后长约 6+）
        pool = [k for k in self._keys(script="latin", min_len=6, max_subs=1)
                if any(c in ("ES", "MX") for c in k["countries"])]
        for k in pool:
            word = k["raw"] if re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ \-]+",
                                            k["raw"]) else k["norm"]
            word = word.strip()
            if len(word) < 6:
                continue
            variant = strip_accents(word) if self.rng.random() < 0.3 else word
            q = mutate_latin(self.rng, variant)
            if not q:
                continue
            if self._add("es_typo", "es", q, k["subs"], "must_hit", "typo",
                         dict(source="name_key/name_variant(ES/MX)",
                              row_ids=[k["key_id"]],
                              detail=f"{k['norm']} -> {q}", countries=k["countries"]),
                         ["latin", "es", "edit_distance_1"]):
                made += 1
                if made >= n - 10:
                    break
        # b) WHO 西语名：用 en 名反查 DB 成分（独立于检索）
        who = list(csv.DictReader(open(WHO, encoding="utf-8-sig"))) if WHO.exists() else []
        self.rng.shuffle(who)
        inn_norm = self.d.all_substance_norms()
        for r in who:
            es = (r.get("inn_es") or "").strip()
            en = (r.get("inn_en") or "").strip()
            if not es or not en or len(es) < 6:
                continue
            sid = inn_norm.get(normalize(en).norm)
            if not sid:
                continue
            q = mutate_latin(self.rng, strip_accents(es) if self.rng.random() < 0.3 else es)
            if not q:
                continue
            if self._add("es_typo", "es", q, [sid], "must_hit", "typo",
                         dict(source="data/who_inn_names.csv", row_ids=[r.get("inn_number", "")],
                              detail=f"WHO es {es} -> {q}; en={en}"),
                         ["latin", "es", "who_inn", "edit_distance_1"]):
                made += 1
                if made >= n:
                    return
        self.shortages["es_typo"] = f"只生成 {made}/{n}"

    # -- 3. zh 错字 ------------------------------------------------------
    def gen_zh_char_typo(self, n: int) -> None:
        pool = [k for k in self._keys(script="han", min_len=4, max_subs=1)
                if any(a in k["norm"] for a, _b in ZH_CONFUSIONS)]
        made = 0
        for k in pool:
            q = mutate_zh(self.rng, k["norm"])
            if not q or q == k["norm"]:
                continue
            if self._add("zh_char_typo", "zh", q, k["subs"], "must_hit", "char_typo",
                         dict(source="name_key(han)", row_ids=[k["key_id"]],
                              detail=f"{k['norm']} -> {q}"),
                         ["han", "zh", "char_confusion_1"]):
                made += 1
                if made >= n:
                    return
        self.shortages["zh_char_typo"] = f"只生成 {made}/{n}"

    # -- 4. 拼音 ---------------------------------------------------------
    def gen_pinyin(self, n: int) -> None:
        pool = [k for k in self._keys(script="han", min_len=2, max_subs=1)
                if 2 <= len(k["norm"]) <= 8 and all(c in self.pinyin for c in k["norm"])]
        # 全拼 20 / 首字母 20
        made = 0
        for k in pool:
            name = k["norm"]
            full = "".join(self.pinyin[c] for c in name)
            initials = "".join(self.pinyin[c][0] for c in name)
            for q, qtype in ((full, "pinyin_full"), (initials, "pinyin_initials")):
                if made >= n:
                    return
                if len(q) < 3:
                    continue
                if self._add("pinyin", "zh", q, k["subs"], "gap", qtype,
                             dict(source="site/build.py#_PINYIN_CHARS_TEXT",
                                  row_ids=[k["key_id"]],
                                  detail=f"{name} -> {q}"),
                             ["pinyin", "gap", "zh"]):
                    made += 1
                    if made >= n:
                        return
        self.shortages["pinyin"] = f"只生成 {made}/{n}"

    # -- 5. 简繁 ---------------------------------------------------------
    def gen_jianfan(self, n: int) -> None:
        inv: dict[str, str] = {}
        for trad, simp in _T2S.items():
            if trad != simp and simp not in inv:
                inv[simp] = trad
        pool = [k for k in self._keys(script="han", min_len=2, max_subs=1)
                if any(c in inv for c in k["norm"])]
        made = 0
        for k in pool:
            name = k["norm"]
            trad = to_traditional(name)
            if trad == name:
                continue
            if self._add("jianfan", "zh", trad, k["subs"], "must_hit", "traditional",
                         dict(source="etl/normalize_name.py#_T2S",
                              row_ids=[k["key_id"]], detail=f"{name} -> {trad}"),
                         ["han", "zh", "traditional"]):
                made += 1
                if made >= n:
                    return
        self.shortages["jianfan"] = f"只生成 {made}/{n}"

    # -- 6. 复方 ---------------------------------------------------------
    def gen_combo(self, n: int) -> None:
        pool = [k for k in self._keys(min_len=4, require_subs=2, max_subs=4)]
        made_trade = 0
        self.rng.shuffle(pool)
        for k in pool:
            if made_trade >= 40:
                break
            q = k["raw"] if k["raw"] else k["norm"]
            if len(q) < 4:
                continue
            if self._add("combo", "zh" if k["script"] == "han" else "en", q,
                         k["subs"], "must_hit", "combo_trade",
                         dict(source="product_component(>=2)", row_ids=[k["key_id"]],
                              detail=f"复方商品名 {k['norm']}"),
                         ["combo", "trade", "multi_component"]):
                made_trade += 1
        # 成分拼接查询：语言 en，policy=gap（当前无 query parser；改造目标）
        made_join = 0
        for k in pool:
            if made_join >= n - made_trade:
                break
            if len(k["subs"]) < 2:
                continue
            parts = [self.d.sub_inn.get(s, s) for s in k["subs"]]
            q = " + ".join(parts)
            if len(q) > 120:
                continue
            if self._add("combo", "en", q, k["subs"], "gap", "combo_components",
                         dict(source="substance.inn_en x product_component",
                              row_ids=[k["key_id"]],
                              detail=f"成分拼接 {parts}"),
                         ["combo", "components", "gap"]):
                made_join += 1
        if made_trade + made_join < n:
            self.shortages["combo"] = f"只生成 {made_trade}+{made_join}/{n}"

    # -- 7. 盐型 ---------------------------------------------------------
    def gen_salt(self, n: int) -> None:
        # a) 商品名：成分挂 salt variant 的 active 产品 → 其 name_key
        seen_keys: dict[str, dict] = {}
        for sid, entries in self.d.salt_products.items():
            for pid, salt in entries:
                for key_id in self.d.prod_keys.get(pid, ()):
                    k = self.d.stable_keys.get(key_id)
                    if (not k or len(k["subs"]) != 1 or k["script"] != "latin"
                            or len(k["norm"]) < 6):
                        continue
                    seen_keys.setdefault(key_id, dict(k, salt=salt, pid=pid))
        pool = list(seen_keys.values())
        self.rng.shuffle(pool)
        made = 0
        for k in pool:
            q = k["raw"] if k["raw"] else k["norm"]
            if self._add("salt", "en", q, k["subs"], "must_hit", "salt_product",
                         dict(source="variant.salt<>'' -> product_name",
                              row_ids=[k["key_id"], k["pid"]],
                              detail=f"盐型 {k['salt']} 商品名 {k['norm']}"),
                         ["salt", "variant", "latin"]):
                made += 1
                if made >= 40:
                    break
        # b) 构造「INN + salt」：要求该字符串在 name_key 里精确存在（DB 驱动）
        constructed = 0
        for sid, entries in self.d.salt_products.items():
            if constructed >= n - made:
                break
            base = self.d.sub_inn.get(sid, "")
            if not base:
                continue
            salt = entries[0][1]
            q = f"{base} {salt}"
            nq = normalize(q).norm
            k = self.d.stable_keys.get(nq)
            if not k or len(k["subs"]) != 1:
                continue
            if self._add("salt", "en", q, k["subs"], "must_hit", "salt_inn",
                         dict(source="substance.inn_en + variant.salt",
                              row_ids=[k["key_id"], entries[0][0]],
                              detail=f"{base} + {salt}"),
                         ["salt", "inn+salt", "latin"]):
                constructed += 1
        if made + constructed < n:
            self.shortages["salt"] = f"只生成 {made}+{constructed}/{n}"

    # -- 8. 零结果 -------------------------------------------------------
    def gen_zero(self, n: int) -> None:
        rng = self.rng
        made = 0
        tries = 0
        han_pool = list("氨氯地平阿托伐他汀布洛芬对乙酰氨基酚头孢曲松唑嗪啶噻孢霉酚酸納钾镁钙锌铁")
        while made < n and tries < 20000:
            tries += 1
            kind = made % 4
            if kind == 0:
                q = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz")
                            for _ in range(rng.randint(7, 12)))
            elif kind == 1:
                q = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz")
                            for _ in range(rng.randint(5, 6))) + str(rng.randint(10, 99))
            elif kind == 2:
                q = "".join(rng.choice(han_pool) for _ in range(rng.randint(2, 4)))
            else:
                q = rng.choice(NON_DRUG_QUERIES) if made < n - 4 else \
                    "".join(rng.choice(han_pool) for _ in range(3))
            ok, why = self.checker.is_free(q)
            if not ok:
                continue
            lang = "zh" if any("\u4e00" <= c <= "\u9fff" for c in q) else "en"
            if self._add("zero_result", lang, q, [], "must_empty", "negative",
                         dict(source="generator+SQL 二次验证",
                              row_ids=[], detail=f"SQL 验证通过（{why or '无命中'}）"),
                         ["negative", "must_empty"], min_tier=None):
                made += 1
        if made < n:
            self.shortages["zero_result"] = f"只生成 {made}/{n}（tries={tries}）"


def main() -> int:
    ap = argparse.ArgumentParser(description="生成三语评测集 cases_v2.json（320 例）")
    ap.add_argument("--dry-run", action="store_true", help="只统计不落盘")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--db", default=str(DB), help="只读 DB（建议用快照副本）")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"FATAL: DB 不存在: {db_path}", file=sys.stderr)
        return 2
    t0 = time.time()
    db_sha = sha256_file(db_path)
    db_stat = db_path.stat()
    data = Data(db_path)
    pinyin = load_pinyin()
    rng = random.Random(args.seed)
    checker = NegativeChecker(db_path)
    gen = Generator(data, rng, pinyin, checker, db_sha)

    plan = [
        ("en_typo", gen.gen_en_typo),
        ("es_typo", gen.gen_es_typo),
        ("zh_char_typo", gen.gen_zh_char_typo),
        ("pinyin", gen.gen_pinyin),
        ("jianfan", gen.gen_jianfan),
        ("combo", gen.gen_combo),
        ("salt", gen.gen_salt),
        ("zero_result", gen.gen_zero),
    ]
    for name, fn in plan:
        quota = QUOTAS[name]
        fn(quota)
        got = sum(1 for c in gen.cases if c["category"] == name)
        print(f"  {name:<14} {got:>3}/{quota}")

    counts = Counter(c["category"] for c in gen.cases)
    policies = Counter(c["expected"]["policy"] for c in gen.cases)
    meta = dict(
        version="2.0",
        generator="tests/trilingual/gen_cases.py",
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        seed=args.seed,
        db=dict(path=str(db_path), sha256=db_sha,
                size_bytes=db_stat.st_size,
                mtime=datetime.fromtimestamp(db_stat.st_mtime,
                                             timezone.utc).isoformat(timespec="seconds")),
        counts=dict(counts), total=len(gen.cases),
        policies=dict(policies),
        sql_verified_zero_cases=sum(1 for c in gen.cases
                                    if c["category"] == "zero_result"),
        shortages=gen.shortages,
        sources=["name_key/name_variant/product/product_component/variant/substance",
                 "site/build.py#_PINYIN_CHARS_TEXT", "etl/normalize_name.py#_T2S",
                 "data/who_inn_names.csv"],
        notes=("期望只来自 DB 结构关系与规则表；未调用 lib/search.py。"
               "零结果类全部经 SQL 二次验证（无 name_key 精确/子串、无 alias、无 confusable）。"),
    )
    payload = dict(meta=meta, cases=gen.cases)
    print(f"\n合计 {len(gen.cases)} 例（目标 {TOTAL}）  policy: {dict(policies)}")
    print(f"生成耗时 {time.time()-t0:.1f}s；DB sha256={db_sha[:16]}…")
    if gen.shortages:
        print("配额不足:", gen.shortages)
    if not args.dry_run:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        print(f"写入 {OUT}（{OUT.stat().st_size/1024:.0f} KB）")
    return 0 if len(gen.cases) >= TOTAL else 1


if __name__ == "__main__":
    raise SystemExit(main())
