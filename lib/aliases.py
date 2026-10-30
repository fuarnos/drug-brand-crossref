"""同物异名（INN / USAN / 拼写 / 盐型写法）对照表加载器。

用途（task-141）：同一成分在不同市场可能有不同写法（Glucose / Dextrose、
Chlorphenamine / Chlorpheniramine、Povidone Iodine / Povidone-Iodine），
检索与对照需要知道「这两个 substance 指的是同一个药」。

边界：
- **只做对照，不做身份合并**：不修改 `drugs.db`、不动 `substance` 主键、不合并产品。
- 表是人工维护的小表（`data/substance_aliases.csv`），每行必须能说出处（source 列）。
- 判不了的**不写**，宁缺勿滥；新增行要有来源（说明书写法 / 药典 / 官方标签）。

用法：
    from lib.aliases import load
    am = load()
    am.canonical("dextrose")        # -> "glucose"
    am.aliases("glucose")           # -> frozenset({"dextrose", "anhydrous-dextrose"})
    am.lookup_name("Dextrose")      # -> frozenset({"glucose", "dextrose", "anhydrous-dextrose"})
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data" / "substance_aliases.csv"

RELATIONS = frozenset(
    {"synonym", "spelling", "hydrate_variant", "salt_variant", "synonym_salt", "editorial"}
)


@dataclass(frozen=True)
class AliasPair:
    """一行异名关系（canonical 与 alias 是同一成分的不同写法）。"""

    canonical_inn: str
    canonical_id: str
    alias_inn: str
    alias_id: str
    relation: str
    source: str
    note: str = ""


def norm(name: str) -> str:
    """名称归一：小写、标点转空格、压缩空白（Povidone-Iodine -> povidone iodine）。"""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", name.lower())).strip()


class AliasMap:
    """异名并查集：给出同一成分的所有写法。"""

    def __init__(self, pairs: list[AliasPair]) -> None:
        self.pairs = pairs
        self._parent: dict[str, str] = {}
        self._name_of: dict[str, str] = {}
        self._by_name: dict[str, set[str]] = {}
        for p in pairs:
            self._union(p.canonical_id, p.alias_id)
            self._name_of.setdefault(p.canonical_id, p.canonical_inn)
            self._name_of.setdefault(p.alias_id, p.alias_inn)
            self._by_name.setdefault(norm(p.canonical_inn), set()).add(p.canonical_id)
            self._by_name.setdefault(norm(p.alias_inn), set()).add(p.alias_id)

    # ── 并查集 ──────────────────────────────────────────────────────────
    def _find(self, sid: str) -> str:
        self._parent.setdefault(sid, sid)
        while self._parent[sid] != sid:
            self._parent[sid] = self._parent[self._parent[sid]]
            sid = self._parent[sid]
        return sid

    def _union(self, a: str, b: str) -> None:
        ra, rb = self._find(a), self._find(b)
        if ra != rb:
            self._parent[rb] = ra

    # ── 查询 ────────────────────────────────────────────────────────────
    def canonical(self, sid: str) -> str:
        """返回该 substance 所属组的代表 id（不在表内则返回自身）。"""
        return self._find(sid) if sid in self._parent else sid

    def group(self, sid: str) -> frozenset[str]:
        """同组全部 id（含自身）。"""
        if sid not in self._parent:
            return frozenset({sid})
        root = self._find(sid)
        return frozenset(s for s in self._parent if self._find(s) == root)

    def aliases(self, sid: str) -> frozenset[str]:
        """同组其他写法（不含自身）。"""
        return self.group(sid) - {sid}

    def name_of(self, sid: str) -> str:
        return self._name_of.get(sid, sid)

    def lookup_name(self, name: str) -> frozenset[str]:
        """按 INN 写法查同组 id（不区分大小写与标点）。"""
        ids = self._by_name.get(norm(name), set())
        if not ids:
            return frozenset()
        return frozenset().union(*(self.group(i) for i in ids))

    def same(self, a: str, b: str) -> bool:
        return self.canonical(a) == self.canonical(b)


def load(path: str | Path | None = None) -> AliasMap:
    """读取 CSV；文件不存在时返回空表（不抛错，保证只读脚本可跑）。"""
    p = Path(path) if path is not None else DEFAULT_PATH
    pairs: list[AliasPair] = []
    if not p.exists():
        return AliasMap(pairs)
    with p.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if not row.get("canonical_id") or not row.get("alias_id"):
                continue
            rel = (row.get("relation") or "editorial").strip()
            pairs.append(
                AliasPair(
                    canonical_inn=row["canonical_inn"].strip(),
                    canonical_id=row["canonical_id"].strip(),
                    alias_inn=row["alias_inn"].strip(),
                    alias_id=row["alias_id"].strip(),
                    relation=rel if rel in RELATIONS else "editorial",
                    source=(row.get("source") or "").strip(),
                    note=(row.get("note") or "").strip(),
                )
            )
    return AliasMap(pairs)
