"""检索层：把一个名字变成候选集，永不返回唯一答案。

打分（对应 docs/方案与数据模型.md §5）：
    score = 0.55*name_tier + 0.20*country + 0.15*strength + 0.10*form

匹配层级：
    exact 1.00 · compact 0.95 · prefix 0.80 · contains 0.70 · fuzzy 0.55
"""

from __future__ import annotations

import difflib
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from normalize_name import normalize  # noqa: E402

DB_DEFAULT = ROOT / "data" / "drugs.db"

TIER = {"exact": 1.00, "compact": 0.95, "prefix": 0.80, "contains": 0.70,
        "fuzzy": 0.55, "nickname": 1.00}
FUZZY_MIN = 0.75
MAX_KEYS = 60

# 俗称的类型 → 给人看的标签。昵称命中的提示里会写明是「网络俗称」还是「旧名」，
# 不让用户以为这是包装上的正式名字。
KIND_ZH = {
    "slang": "网络俗称",
    "legacy": "旧名",
    "translit": "音译旧名",
    "abbrev": "简称",
    "misnomer": "常见误称",
}


@dataclass
class Card:
    """一张结果卡 = 一个名字 + 一个国家 + 一种成分组合。"""

    key_id: str
    brand: str
    country: str
    substances: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    dosage_form: str = ""
    status: str = "active"
    n_products: int = 0
    collision: str = "info"
    score: float = 0.0
    tier: str = ""
    product_id: str = ""

    @property
    def composition(self) -> str:
        return " + ".join(self.substances)

    @property
    def strength_text(self) -> str:
        return " / ".join(s for s in self.strengths if s)


@dataclass
class SearchResult:
    query: str
    norm: str
    strengths: tuple = ()
    cards: list[Card] = field(default_factory=list)
    total_keys: int = 0
    note: str = ""
    # 俗称命中：aliases 是所有候选（同一个叫法可能对应多个成分），alias 是首条。
    alias: dict = field(default_factory=dict)
    aliases: list[dict] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.cards


def _strength_sort_key(text: str) -> tuple:
    """把 '10 mg' / '500 mg/5 ml' 排成数值顺序。"""
    import re as _re

    m = _re.match(r"([\d.]+)\s*(\w*)", text or "")
    try:
        return (float(m.group(1)) if m else 0.0, text or "")
    except ValueError:
        return (0.0, text or "")


def _fmt_strength(value, unit, per_v, per_u) -> str:
    if value is None:
        return ""
    v = f"{value:g}" if isinstance(value, float) else str(value)
    out = f"{v} {unit}" if unit else v
    if per_v:
        pv = f"{per_v:g}" if isinstance(per_v, float) else str(per_v)
        out += f"/{pv} {per_u or ''}".rstrip()
    return out


class SearchIndex:
    def __init__(self, db_path: Path | str = DB_DEFAULT):
        self.db = sqlite3.connect(str(db_path))
        self.db.row_factory = sqlite3.Row
        self._norms = [
            (r["key_id"], r["norm"], r["compact"])
            for r in self.db.execute("SELECT key_id, norm, compact FROM name_key")
        ]
        # 俗称表可能还不存在（老库没跑过 init_db），这时静默降级为「没有俗称」。
        try:
            self._nicknames = [
                dict(r) for r in self.db.execute(
                    """SELECT n.alias, n.alias_norm, n.substance_id, n.label_zh,
                              n.kind, n.confidence, n.source, n.note,
                              s.inn_en, s.inn_zh
                       FROM nickname n
                       JOIN substance s ON s.substance_id = n.substance_id
                       ORDER BY n.nickname_id""")
            ]
        except sqlite3.OperationalError:
            self._nicknames = []

    def close(self) -> None:
        self.db.close()

    # --- 候选名解析 -----------------------------------------------------
    def _resolve_keys(self, n) -> list[tuple[str, str]]:
        """返回 [(key_id, tier)]，按 tier 优先级排序、去重。"""
        if n.is_empty:
            return []
        hits: dict[str, str] = {}

        def add(key_id: str, tier: str) -> None:
            if key_id not in hits:
                hits[key_id] = tier

        add(n.norm, "exact")
        for key_id, norm, compact in self._norms:
            if key_id in hits:
                continue
            if compact == n.compact:
                add(key_id, "compact")
            elif norm.startswith(n.norm):
                add(key_id, "prefix")
            elif len(n.norm) >= 4 and n.norm in norm:
                add(key_id, "contains")

        if len(hits) < 5 and len(n.norm) >= 4:
            scored = []
            for key_id, norm, _compact in self._norms:
                if key_id in hits:
                    continue
                r = difflib.SequenceMatcher(None, n.norm, norm).ratio()
                if r >= FUZZY_MIN:
                    scored.append((r, key_id))
            scored.sort(reverse=True)
            for _r, key_id in scored[:20]:
                add(key_id, "fuzzy")

        order = {"exact": 0, "compact": 1, "prefix": 2, "contains": 3, "fuzzy": 4}
        keys = sorted(hits.items(), key=lambda kv: (order[kv[1]], kv[0]))
        return keys[:MAX_KEYS]

    # --- 俗称解析 ------------------------------------------------------
    def _alias_hits(self, n) -> list[dict]:
        """精确命中俗称。不做模糊——昵称差一个字往往就是另一个梗。"""
        compact = n.compact
        return [a for a in self._nicknames
                if a["alias_norm"] == n.norm
                or a["alias_norm"].replace(" ", "") == compact]

    @staticmethod
    def _alias_info(a: dict) -> dict:
        return {
            "alias": a["alias"],
            "substance_id": a["substance_id"],
            "inn_en": a["inn_en"],
            "inn_zh": a["inn_zh"],
            "label_zh": a["label_zh"],
            "kind": a["kind"],
            "confidence": a["confidence"],
            "source": a["source"],
            "note": a["note"],
        }

    def _search_alias(self, query: str, n, hits: list[dict],
                      country: str | None, limit: int,
                      include_status: tuple[str, ...]) -> SearchResult:
        """昵称 → 活性成分 → 这个成分在各国的商品名。

        不返回「某个商品名」的候选集，因为俗称呼唤的是分子，不是某一个包装。
        """
        res = SearchResult(query=query, norm=n.norm, strengths=n.strengths)
        res.aliases = [self._alias_info(a) for a in hits]
        res.alias = res.aliases[0]
        res.total_keys = len(hits)

        cards: list[Card] = []
        for a in hits[:3]:
            cards.extend(self._substance_cards(a["substance_id"], include_status))
        for c in cards:
            self._score_card(c, n, country)
        if country:
            cards = [c for c in cards if c.country == country]
        cards.sort(key=lambda c: (-c.score, -c.n_products, c.brand.lower()))
        res.cards = cards[:limit]

        label = res.alias["label_zh"] or res.alias["inn_zh"] or res.alias["inn_en"]
        kind = KIND_ZH.get(res.alias["kind"], "别名")
        if len(hits) == 1:
            res.note = (f"「{res.alias['alias']}」是 {label} 的{kind}；"
                        "下面按成分列出商品名")
        else:
            names = "、".join(x["label_zh"] or x["inn_en"] for x in res.aliases[:4])
            res.note = f"「{res.alias['alias']}」可能指：{names}；请按成分核对"
        if country and not res.cards:
            res.note = (f"「{res.alias['alias']}」对应的 {label} 在 {country} 没有收录 —— "
                        "查不到不代表该药不存在")
        return res

    def _substance_cards(self, substance_id: str,
                         include_status: tuple[str, ...] = ("active",)) -> list[Card]:
        """把一个成分的商品按「国家 × 剂型 × 释放 × 成分组合」折成结果卡。

        和按名字检索不同：这里不经过 name_key，所以复方里含有该成分的产品也会出现
        （组成会在成分列里写全），品牌名取该组里出现最多的商品名。
        """
        status_marks = ",".join("?" * len(include_status))
        member_sql = """SELECT pc2.product_id FROM product_component pc2
                        JOIN variant v2 ON v2.variant_id = pc2.variant_id
                        WHERE v2.substance_id = ?"""
        rows = self.db.execute(
            f"""SELECT p.product_id, p.country, p.form_base, p.dosage_form, p.release,
                       p.status, pc.ord, pc.strength_value, pc.strength_unit,
                       pc.per_volume_value, pc.per_volume_unit,
                       v.substance_id, s.inn_en
                FROM product p
                JOIN product_component pc ON pc.product_id = p.product_id
                JOIN variant v ON v.variant_id = pc.variant_id
                JOIN substance s ON s.substance_id = v.substance_id
                WHERE p.status IN ({status_marks}) AND p.product_id IN ({member_sql})
                ORDER BY p.product_id, pc.ord""",
            (*include_status, substance_id),
        ).fetchall()
        if not rows:
            return []

        names: dict[str, list[str]] = {}
        for r in self.db.execute(
            f"""SELECT pn.product_id, nv.raw
                FROM product_name pn
                JOIN name_variant nv ON nv.key_id = pn.key_id
                WHERE pn.name_type = 'trade' AND pn.product_id IN ({member_sql})""",
            (substance_id,),
        ):
            names.setdefault(r["product_id"], []).append(r["raw"])

        by_product: dict[str, list[sqlite3.Row]] = {}
        for r in rows:
            by_product.setdefault(r["product_id"], []).append(r)

        cards: dict[tuple, Card] = {}
        pools: dict[tuple, Counter] = {}
        for pid, parts in by_product.items():
            first = parts[0]
            sig = (first["country"], first["form_base"], first["release"],
                   tuple(sorted(p["substance_id"] for p in parts)))
            names_here = names.get(pid) or []
            inns = {p["inn_en"].casefold() for p in parts}
            # 「Metformin」「Metformin Hydrochloride」这类是成分名不是品牌名，
            # 能挑出真品牌（格华止 / Glucophage）就别把成分名当品牌显示。
            real = [x for x in names_here
                    if not any(x.casefold().startswith(i) for i in inns)]
            pool = pools.setdefault(sig, Counter())
            pool.update(real or names_here or [parts[0]["inn_en"]])
            card = cards.get(sig)
            if card is None:
                card = Card(
                    key_id="",
                    brand=parts[0]["inn_en"],
                    country=first["country"],
                    substances=[p["inn_en"] for p in parts],
                    dosage_form=first["form_base"] or first["dosage_form"],
                    status=first["status"],
                    collision="info",
                    tier="nickname",
                    product_id=pid,
                )
                cards[sig] = card
            card.n_products += 1
            if first["status"] == "active":
                card.status = "active"
            for p in parts:
                s = _fmt_strength(p["strength_value"], p["strength_unit"],
                                  p["per_volume_value"], p["per_volume_unit"])
                if s and s not in card.strengths:
                    card.strengths.append(s)
        for sig, card in cards.items():
            if pools.get(sig):
                card.brand = pools[sig].most_common(1)[0][0]
        out = list(cards.values())
        for c in out:
            c.strengths.sort(key=_strength_sort_key)
        return out

    def _score_card(self, c: Card, n, country: str | None) -> None:
        name_score = TIER.get(c.tier, 0.4)
        country_score = 1.0 if (country and c.country == country) else 0.5
        strength_score = 0.5
        if n.strengths:
            qs = {(v, u) for v, u in n.strengths}
            ps = set()
            for s in c.strengths:
                bits = s.split()
                if len(bits) >= 2:
                    ps.add((bits[0], bits[1]))
            strength_score = 1.0 if qs & ps else 0.2
        form_score = 0.5
        if n.form_hint:
            form_score = 1.0 if any(f in c.dosage_form for f in n.form_hint) else 0.3
        c.score = round(0.55 * name_score + 0.20 * country_score
                        + 0.15 * strength_score + 0.10 * form_score, 4)

    # --- 主查询 --------------------------------------------------------
    def search(
        self,
        query: str,
        country: str | None = None,
        limit: int = 25,
        include_status: tuple[str, ...] = ("active",),
    ) -> SearchResult:
        n = normalize(query)
        res = SearchResult(query=query, norm=n.norm, strengths=n.strengths)
        if n.is_empty:
            res.note = "只给了剂量，没有药名"
            return res

        alias_hits = self._alias_hits(n)
        if alias_hits:
            return self._search_alias(query, n, alias_hits, country, limit,
                                      include_status)

        keys = self._resolve_keys(n)
        res.total_keys = len(keys)
        if not keys:
            res.note = "没有匹配的名字"
            return res

        key_ids = [k for k, _ in keys]
        tier_of = dict(keys)
        marks = ",".join("?" * len(key_ids))
        status_marks = ",".join("?" * len(include_status))

        rows = self.db.execute(
            f"""SELECT pn.key_id, p.product_id, p.country, p.dosage_form, p.form_base,
                       p.release, p.status
                FROM product_name pn
                JOIN product p ON p.product_id = pn.product_id
                WHERE pn.key_id IN ({marks}) AND p.status IN ({status_marks})""",
            (*key_ids, *include_status),
        ).fetchall()
        if not rows:
            res.note = "名字对上了，但没有在售产品"
            return res

        by_product: dict[str, list[sqlite3.Row]] = {}
        for r in rows:
            by_product.setdefault(r["product_id"], []).append(r)

        comp: dict[str, list[sqlite3.Row]] = {}
        pmarks = ",".join("?" * len(by_product))
        for r in self.db.execute(
            f"""SELECT pc.product_id, pc.ord, pc.strength_value, pc.strength_unit,
                       pc.per_volume_value, pc.per_volume_unit,
                       v.variant_id, v.salt, s.substance_id, s.inn_en
                FROM product_component pc
                JOIN variant v ON v.variant_id = pc.variant_id
                JOIN substance s ON s.substance_id = v.substance_id
                WHERE pc.product_id IN ({pmarks})
                ORDER BY pc.product_id, pc.ord""",
            tuple(by_product),
        ):
            comp.setdefault(r["product_id"], []).append(r)

        coll = {
            r["key_id"]: r["level"]
            for r in self.db.execute(
                f"SELECT key_id, level FROM collision WHERE key_id IN ({marks})", tuple(key_ids)
            )
        }
        raw_names = {}
        for r in self.db.execute(
            f"""SELECT nv.key_id, nv.raw, COUNT(*) c FROM name_variant nv
                WHERE nv.key_id IN ({marks}) GROUP BY nv.key_id, nv.raw
                ORDER BY c DESC""",
            tuple(key_ids),
        ):
            raw_names.setdefault(r["key_id"], r["raw"])

        cards: dict[tuple, Card] = {}
        for product_id, group in by_product.items():
            first = group[0]
            parts = comp.get(product_id, [])
            if not parts:
                continue
            substances = [p["inn_en"] for p in parts]
            strengths = [
                _fmt_strength(p["strength_value"], p["strength_unit"],
                              p["per_volume_value"], p["per_volume_unit"])
                for p in parts
            ]
            sig = (first["key_id"], first["country"],
                   tuple(sorted(p["substance_id"] for p in parts)),
                   first["form_base"], first["release"])
            card = cards.get(sig)
            if card is None:
                form_base = first["form_base"] or first["dosage_form"]
                card = Card(
                    key_id=first["key_id"],
                    brand=raw_names.get(first["key_id"], first["key_id"]),
                    country=first["country"],
                    substances=substances,
                    strengths=[],
                    dosage_form=form_base,
                    status=first["status"],
                    collision=coll.get(first["key_id"], "info"),
                    tier=tier_of[first["key_id"]],
                    product_id=product_id,
                )
                cards[sig] = card
            for s in strengths:
                if s and s not in card.strengths:
                    card.strengths.append(s)
            card.n_products += 1

        result = list(cards.values())
        for c in result:
            c.strengths.sort(key=_strength_sort_key)
            self._score_card(c, n, country)

        if country:
            # 严格按国家过滤：给一个「该国没有」的明确答案，比回退到别国更诚实
            result = [c for c in result if c.country == country]
            if not result:
                res.note = f"在 {country} 没有收录到这个名字 —— 查不到不代表该药不存在"
                res.cards = []
                return res
        # 同层级里：产品多的品牌在前（"Tylenol Extra Strength" 比冷门变体更可能是用户要找的）
        result.sort(key=lambda c: (-c.score, -c.n_products, len(c.key_id), c.brand.lower()))
        res.cards = result[:limit]
        return res

    # --- 单页数据 ------------------------------------------------------
    def name_page(self, key_id: str) -> dict | None:
        """名字页：这个名字下挂的所有成分与国家。"""
        key = self.db.execute(
            "SELECT key_id, norm, script FROM name_key WHERE key_id = ?", (key_id,)
        ).fetchone()
        if not key:
            return None
        rows = self.db.execute(
            """SELECT p.country, p.dosage_form, p.status, p.mah,
                      pc.strength_value, pc.strength_unit,
                      pc.per_volume_value, pc.per_volume_unit,
                      s.substance_id, s.inn_en, v.salt
               FROM product_name pn
               JOIN product p ON p.product_id = pn.product_id
               JOIN product_component pc ON pc.product_id = p.product_id
               JOIN variant v ON v.variant_id = pc.variant_id
               JOIN substance s ON s.substance_id = v.substance_id
               WHERE pn.key_id = ?""",
            (key_id,),
        ).fetchall()
        level = self.db.execute(
            "SELECT level FROM collision WHERE key_id = ?", (key_id,)
        ).fetchone()
        variants = [
            r["raw"]
            for r in self.db.execute(
                "SELECT raw FROM name_variant WHERE key_id = ? ORDER BY v_id", (key_id,)
            )
        ]
        substances: dict[str, dict] = {}
        countries: dict[str, int] = {}
        for r in rows:
            s = substances.setdefault(
                r["substance_id"],
                {"substance_id": r["substance_id"], "inn_en": r["inn_en"],
                 "countries": set(), "strengths": set(), "forms": set()},
            )
            s["countries"].add(r["country"])
            st = _fmt_strength(r["strength_value"], r["strength_unit"],
                               r["per_volume_value"], r["per_volume_unit"])
            if st:
                s["strengths"].add(st)
            s["forms"].add(r["dosage_form"])
            countries[r["country"]] = countries.get(r["country"], 0) + 1
        for s in substances.values():
            s["countries"] = sorted(s["countries"])
            s["strengths"] = sorted(s["strengths"])
            s["forms"] = sorted(s["forms"])
        return {
            "key_id": key["key_id"],
            "norm": key["norm"],
            "script": key["script"],
            "variants": variants,
            "level": level["level"] if level else "info",
            "substances": list(substances.values()),
            "countries": countries,
        }

    def drug_page(self, substance_id: str) -> dict | None:
        """身份卡：一个成分在所有国家的商品名与规格。"""
        sub = self.db.execute(
            "SELECT * FROM substance WHERE substance_id = ?", (substance_id,)
        ).fetchone()
        if not sub:
            return None
        rows = self.db.execute(
            """SELECT p.product_id, p.country, p.dosage_form, p.release, p.status,
                      p.mah, pc.strength_value, pc.strength_unit,
                      pc.per_volume_value, pc.per_volume_unit
               FROM product p
               JOIN product_component pc ON pc.product_id = p.product_id
               JOIN variant v ON v.variant_id = pc.variant_id
               WHERE v.substance_id = ?
               ORDER BY p.country, pc.strength_value""",
            (substance_id,),
        ).fetchall()
        names: dict[str, list[str]] = {}
        for r in self.db.execute(
            """SELECT pn.product_id, nv.raw
               FROM product_name pn
               JOIN name_variant nv ON nv.key_id = pn.key_id
               JOIN product p ON p.product_id = pn.product_id
               JOIN product_component pc ON pc.product_id = p.product_id
               JOIN variant v ON v.variant_id = pc.variant_id
               WHERE v.substance_id = ? AND pn.name_type = 'trade'""",
            (substance_id,),
        ):
            names.setdefault(r["product_id"], []).append(r["raw"])

        by_country: dict[str, list[dict]] = {}
        brand_counter: dict[str, dict[str, int]] = {}
        for r in rows:
            brands = names.get(r["product_id"], [])
            for b in brands:
                brand_counter.setdefault(r["country"], {})
                brand_counter[r["country"]][b] = brand_counter[r["country"]].get(b, 0) + 1
            by_country.setdefault(r["country"], []).append(
                {
                    "brand": brands[0] if brands else "",
                    "strength": _fmt_strength(r["strength_value"], r["strength_unit"],
                                              r["per_volume_value"], r["per_volume_unit"]),
                    "form": r["dosage_form"],
                    "release": r["release"],
                    "status": r["status"],
                    "mah": r["mah"],
                    "product_id": r["product_id"],
                }
            )
        return {
            "substance": dict(sub),
            "by_country": by_country,
            "top_brands": {
                c: sorted(d.items(), key=lambda kv: -kv[1])[:12]
                for c, d in brand_counter.items()
            },
            "variants": [
                dict(r)
                for r in self.db.execute(
                    "SELECT * FROM variant WHERE substance_id = ?", (substance_id,)
                )
            ],
        }

    def coverage(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM coverage")]

    def stats(self) -> dict:
        return {
            "products": self.db.execute("SELECT COUNT(*) FROM product").fetchone()[0],
            "substances": self.db.execute("SELECT COUNT(*) FROM substance").fetchone()[0],
            "keys": self.db.execute("SELECT COUNT(*) FROM name_key").fetchone()[0],
            "severe": self.db.execute(
                "SELECT COUNT(*) FROM collision WHERE level='severe'").fetchone()[0],
        }
