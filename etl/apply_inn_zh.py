#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 `data/inn_zh_backfill.csv` 的中文成分名回填到 `substance.inn_zh`。

安全设计
--------
- 默认 **dry-run**（只读打开 DB）：校验 CSV 与库内状态，打印将回填条数 / 覆盖率
  before-after / 按 confidence 分布；不写库。
- `--apply`：事务内 **只更新当前 inn_zh 为空的行**（绝不覆盖已有值），先写完整撤销清单
  （旧值 + 新值）再 commit；任一行更新 0 行或多行 → 中止回滚。
- `--rollback [manifest]`：把新值精确恢复为旧值（旧值为 NULL/空串时恢复为空串/NULL 原样）；
  只回滚「当前值 == 写入值」的行，已被别人改过的行记冲突、不覆盖；可重复执行（幂等）。
- `--min-confidence high|medium|low`：默认只回填 high；先跑 high、人工抽检后再放开 medium。

T17（v0.11.8 P0）新增「盐型名修正」模式，**不改**上面「只填空值」的保护逻辑：
- `--build-salt-fix-list`：只读 DB，重新生成 `data/sources/inn_zh_salt_forms_20261115.csv`
  （清单 + 丢弃明细，可复算）。
- `--fix-salt-forms [--apply]`：默认 dry-run；`--apply` 在事务内把**已写错的盐型中文名**
  改成基础成分名（如 枸橼酸咖啡因 → 咖啡因），并把旧名写进 `nickname` 表
  （kind='misnomer'，只做精确匹配别名，不碰 `product_name`）；同样写撤销清单，
  `--rollback` 会把 `inn_zh` 和新增的 nickname 一起撤销。

用法
----
    python etl/apply_inn_zh.py                      # dry-run（默认 high）
    python etl/apply_inn_zh.py --dry-run --min-confidence medium
    python etl/apply_inn_zh.py --db X.db --apply --min-confidence high
    python etl/apply_inn_zh.py --db X.db --rollback [manifest]
    python etl/apply_inn_zh.py --build-salt-fix-list          # 重新生成盐型清单（只读）
    python etl/apply_inn_zh.py --fix-salt-forms               # 盐型名修正 dry-run
    python etl/apply_inn_zh.py --db X.db --fix-salt-forms --apply

写库只在库副本上演练过、并留撤销清单；真实库什么时候写由 Lead 定。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_DEFAULT = ROOT / "data" / "inn_zh_backfill.csv"
DB_DEFAULT = ROOT / "data" / "drugs.db"
MANIFEST_DIR = ROOT / ".tmp" / "inn-zh"
CONF_RANK = {"high": 0, "medium": 1, "low": 2}
SALT_FIX_CSV = ROOT / "data" / "sources" / "inn_zh_salt_forms_20261115.csv"
SALT_FIX_FIELDS = ["substance_id", "inn_en", "inn_zh_old", "inn_zh_new",
                   "salt_word", "salt_variants", "method", "source",
                   "confidence", "verdict", "reason", "evidence"]

# --- T17：中文名含盐型词 → 基础成分名 -------------------------------------
# 中文化学盐型词 → 英文盐型词（与 inn_en / variant 对照用，不做翻译）
SALT_ZH2EN: dict[str, tuple[str, ...]] = {
    # 酸根（成盐阴离子）：从前缀剥
    "盐酸": ("hydrochloride", "hcl"),
    "硫酸氢": ("bisulfate", "hydrogensulfate"),
    "硫酸": ("sulfate", "sulphate"),
    "磷酸二氢": ("dihydrogenphosphate", "dihydrogen phosphate"),
    "磷酸氢": ("hydrogenphosphate", "hydrogen phosphate"),
    "磷酸": ("phosphate",),
    "枸橼酸": ("citrate",),
    "柠檬酸": ("citrate",),
    "马来酸": ("maleate",),
    "富马酸": ("fumarate",),
    "琥珀酸": ("succinate",),
    "酒石酸": ("tartrate",),
    "甲磺酸": ("mesylate", "methanesulfonate"),
    "苯磺酸": ("besylate", "benzenesulfonate"),
    "苯磺": ("besylate",),
    "甲苯磺酸": ("tosylate",),
    "对甲苯磺酸": ("tosylate",),
    "甲硫酸": ("methylsulfate",),
    "单磷酸": ("phosphate",),
    "氢溴酸": ("hydrobromide",),
    "溴化": ("bromide",),
    "氯化": ("chloride",),
    "醋酸": ("acetate",),
    "乙酸": ("acetate",),
    "乳酸": ("lactate",),
    "硝酸": ("nitrate",),
    "亚硝酸": ("nitrite",),
    "棕榈酸": ("palmitate",),
    "硬脂酸": ("stearate",),
    "葡萄糖酸": ("gluconate",),
    "谷氨酸": ("glutamate",),
    "门冬氨酸": ("aspartate",),
    "天冬氨酸": ("aspartate",),
    "苹果酸": ("malate",),
    "苯甲酸": ("benzoate",),
    "丙酸": ("propionate",),
    "戊酸": ("valerate",),
    "癸酸": ("decanoate",),
    "环丙酸": ("cypionate",),
    "庚酸": ("enanthate",),
    "十一酸": ("undecanoate",),
    "氨丁三醇": ("tromethamine", "trometamol"),
    "二乙胺": ("diethylamine",),
    "三乙醇胺": ("trolamine", "triethanolamine"),
    "水杨酸": ("salicylate",),
    "依地酸": ("edetate",),
    "羟乙磺酸": ("isethionate",),
    "双羟萘酸": ("pamoate", "embonate"),
    "萘磺酸": ("napsylate",),
    "烟酸": ("nicotinate",),
    "丁酸": ("butyrate",),
    "碘化": ("iodide",),
}
# 阳离子 / 酯：从后缀剥（「铵」故意不进：季铵盐的「铵」属于基础名本身）
CATION_ZH2EN: dict[str, tuple[str, ...]] = {
    "磷酸氢钙": ("calcium", "phosphate"),
    "磷酸钙": ("calcium", "phosphate"),
    "磷酸钠": ("sodium", "phosphate"),
    "双钠": ("sodium",),
    "二钠": ("sodium",),
    "三钠": ("sodium",),
    "钠": ("sodium",),
    "钾": ("potassium",),
    "钙": ("calcium",),
    "镁": ("magnesium",),
    "锌": ("zinc",),
    "亚铁": ("ferrous", "iron"),
    "铁": ("ferrous", "ferric", "iron"),
    "铝": ("aluminum", "aluminium"),
    "铋": ("bismuth",),
    "铜": ("copper",),
    "锂": ("lithium",),
    "锶": ("strontium",),
    "钡": ("barium",),
    # 有机碱（结尾成盐）：也可出现在词尾
    "氨丁三醇": ("tromethamine", "trometamol"),
    "二乙胺": ("diethylamine",),
    "三乙醇胺": ("trolamine", "triethanolamine"),
}
ESTER_SUFFIX = ["磷酸酯", "棕榈酸酯", "癸酸酯", "丙酸酯", "戊酸酯", "环丙酸酯",
                "苯甲酸酯", "乙酸酯", "醋酸酯", "琥珀酸酯", "硬脂酸酯", "酸酯"]
# 英文侧盐型 / 金属词：出现在 inn_en 里 ⇒ 该成分本身就是这个盐，中文名不动
EN_SALT_WORDS = {
    "hydrochloride", "hcl", "sulfate", "sulphate", "phosphate", "citrate",
    "maleate", "fumarate", "succinate", "tartrate", "mesylate", "besylate",
    "tosylate", "nitrate", "bromide", "chloride", "iodide", "acetate", "lactate",
    "palmitate", "stearate", "gluconate", "glutamate", "aspartate", "malate",
    "benzoate", "propionate", "valerate", "decanoate", "enanthate",
    "undecanoate", "tromethamine", "salicylate", "edetate", "isethionate",
    "pamoate", "embonate", "napsylate", "nicotinate", "butyrate", "sodium",
    "potassium", "calcium", "magnesium", "zinc", "iron", "ferrous", "ferric",
    "aluminum", "aluminium", "bismuth", "ammonium", "lithium", "copper",
    "strontium", "barium", "silver", "gold", "mercury", "manganese",
}
# 检测口径（宽）：把「整名可能合法含盐型词」的写法也算进来，清单不漏
DETECT_ZH = sorted(set(SALT_ZH2EN) | set(CATION_ZH2EN) | {
    "铵", "氢氧化", "氧化", "碳酸", "碳酸氢", "碱式", "碘", "氯", "溴",
}, key=len, reverse=True)
SALT_PREFIXES = sorted(SALT_ZH2EN, key=len, reverse=True)
SALT_SUFFIXES = sorted(list(CATION_ZH2EN) + ESTER_SUFFIX, key=len, reverse=True)
BAD_RESIDUAL_TAIL = ("盐", "根", "离子")
BARE_ION = {"钠", "钾", "钙", "镁", "锌", "铁", "亚铁", "铵", "铝", "铋", "铜",
            "锂", "锶", "钡", "碘", "氯", "溴", "氢", "氧"}
# 人工复核后决定「不剥」的行：盐型词属于名称本身，剥完不是成分名
DROP_OVERRIDES: dict[str, str] = {
    "nitroglycerin": "硝酸甘油：硝酸是硝酸酯的一部分（不是成盐），剥完「甘油」是另一个成分",
    "lactasin": "乳酸菌素：整名就是 lactasin，剥完「菌素」不是成分名",
    "mesna": "美司钠：钠是 INN 自带（mesna = 美司钠），剥完「美司」不是成分名",
    "sucralfate": "硫糖铝：整名就是 sucralfate，剥完「硫糖」不是成分名",
    "nitroprusiato": "硝普钠：西语名 nitroprusside，剥完「硝普」不是成分名",
    "ytrio-citrato-90y": "枸橼酸钇[90Y]：放射性核素名，残形带同位素标记，不剥",
    "cefetamet": "盐酸头孢他美酯：酯属于衍生物（cefetamet pivoxil），"
                 "base 是头孢他美，剥到酯层反而写错",
}
# 人工复核后决定「要剥」的行：盐型词在词中/后缀复合，规则没法安全处理
KEEP_OVERRIDES: dict[str, tuple[str, str]] = {
    "methylprednisolone": ("甲泼尼龙",
                           "甲泼尼龙琥珀酸钠：酯盐复合后缀，base 是甲泼尼龙"),
    "adenosine-triphosphate": ("三磷酸腺苷",
                               "三磷酸腺苷二钠：磷酸在「三磷酸」结构里，base 名即三磷酸腺苷"),
    "cytidine-triphosphate": ("三磷酸胞苷",
                              "三磷酸胞苷二钠：同上，base 名即三磷酸胞苷"),
    "valproic-acid": ("丙戊酸",
                      "丙戊酸钠：残形里的「戊酸」是拼词巧合，base 名即丙戊酸"),
}
NICK_SOURCE = "T17 盐型名剥离：合并前 substance.inn_zh"
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ASCII_EN_RE = re.compile(r"^[A-Za-z0-9 \-,'()./]+$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True, timeout=60)
    else:
        con = sqlite3.connect(str(db_path), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def load_rows(csv_path: Path) -> list[dict]:
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
    out = []
    for r in rows:
        r = {k: (r.get(k) or "").strip() for k in
             ("substance_id", "inn_en", "zh_candidate", "confidence", "method",
              "count", "share", "variants", "evidence")}
        out.append(r)
    return out


def build_plan(con: sqlite3.Connection, rows: list[dict], min_conf: str) -> dict:
    accepted, skipped = [], []
    dist = Counter()
    min_rank = CONF_RANK[min_conf]
    for r in rows:
        conf = r["confidence"] or "low"
        if (CONF_RANK.get(conf, 9)) > min_rank:
            dist["低于置信度门槛"] += 1
            continue
        if not r["substance_id"] or not r["zh_candidate"]:
            skipped.append(dict(r, why="substance_id/候选为空"))
            continue
        row = con.execute("SELECT substance_id, inn_en, inn_zh FROM substance"
                          " WHERE substance_id=?", (r["substance_id"],)).fetchone()
        if row is None:
            skipped.append(dict(r, why="substance 不存在"))
            continue
        if (row["inn_en"] or "") != r["inn_en"]:
            skipped.append(dict(r, why=f"inn_en 不一致：库内 {row['inn_en']!r}"))
            continue
        cur = row["inn_zh"] or ""
        if cur.strip():
            skipped.append(dict(r, why=f"已有 inn_zh={cur!r}（不覆盖，幂等跳过）"))
            dist["已有值跳过"] += 1
            continue
        accepted.append(dict(r, old_inn_zh=(row["inn_zh"] if row["inn_zh"] is not None
                                            else None)))
        dist[f"confidence_{conf}"] += 1
    total_sub = con.execute("SELECT COUNT(*) FROM substance").fetchone()[0]
    existing = con.execute(
        "SELECT COUNT(*) FROM substance WHERE inn_zh IS NOT NULL"
        " AND trim(inn_zh)<>''").fetchone()[0]
    return dict(rows=rows, accepted=accepted, skipped=skipped, dist=dist,
                total_sub=total_sub, existing=existing)


def print_plan(p: dict, min_conf: str) -> None:
    print(f"DB: 共 {p['total_sub']} 个 substance；已有 inn_zh {p['existing']}")
    print(f"CSV 行数 {len(p['rows'])}；min-confidence={min_conf}")
    print(f"可回填：{len(p['accepted'])} 行；跳过：{len(p['skipped'])} 行")
    print("分布:", dict(p["dist"]))
    after = p["existing"] + len(p["accepted"])
    print(f"覆盖率: {p['existing']}/{p['total_sub']} → {after}/{p['total_sub']}"
          f"（{p['existing']/p['total_sub']*100:.1f}% → "
          f"{after/p['total_sub']*100:.1f}%）")
    if p["skipped"]:
        print("\n跳过明细（前 10）:")
        for s in p["skipped"][:10]:
            print(f"  {s['substance_id']} {s['inn_en']}: {s['why']}")
    print("\n样例（前 20）:")
    for r in p["accepted"][:20]:
        print(f"  {r['inn_en']:<28} -> {r['zh_candidate']:<10} {r['confidence']:<6}"
              f" {r['method']}")


def apply_plan(con: sqlite3.Connection, p: dict, db_path: Path, csv_path: Path,
               manifest_path: Path) -> int:
    accepted = p["accepted"]
    if not accepted:
        print("没有可回填的行（幂等或全部跳过），未写库。")
        return 0
    manifest = dict(tool="etl/apply_inn_zh.py", db=str(db_path.resolve()),
                    csv=str(csv_path.resolve()),
                    csv_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                    created_at=utc_now(), committed=False, rows=[])
    try:
        con.execute("BEGIN IMMEDIATE")
        for a in accepted:
            cur = con.execute(
                "UPDATE substance SET inn_zh=? WHERE substance_id=?"
                " AND (inn_zh IS NULL OR trim(inn_zh)='')",
                (a["zh_candidate"], a["substance_id"]))
            if cur.rowcount != 1:
                raise RuntimeError(f"更新 {a['substance_id']} 影响 {cur.rowcount} 行，中止")
            manifest["rows"].append(dict(
                substance_id=a["substance_id"], inn_en=a["inn_en"],
                old_inn_zh=a["old_inn_zh"], new_inn_zh=a["zh_candidate"],
                confidence=a["confidence"], method=a["method"],
                evidence=a["evidence"]))
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        con.commit()
        manifest["committed"] = True
        manifest["committed_at"] = utc_now()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    except Exception:
        con.rollback()
        print("!! 写库失败，已回滚事务", file=sys.stderr)
        raise
    print(f"已回填 {len(accepted)} 行；撤销清单: {manifest_path}")
    return len(accepted)


def rollback(con: sqlite3.Connection, manifest_path: Path) -> None:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not data.get("committed"):
        raise SystemExit(f"清单 {manifest_path} 未标记 committed，拒绝回滚")
    if data.get("rolled_back_at"):
        print(f"清单已于 {data['rolled_back_at']} 回滚过，继续幂等恢复")
    restored = 0
    skipped = 0
    conflicts = []
    con.execute("BEGIN IMMEDIATE")
    try:
        for rec in reversed(data.get("rows", [])):
            sid = rec["substance_id"]
            row = con.execute("SELECT inn_zh FROM substance WHERE substance_id=?",
                              (sid,)).fetchone()
            if row is None:
                conflicts.append(f"{sid}: substance 已不存在")
                continue
            cur = row["inn_zh"]
            if cur == rec["old_inn_zh"] or (cur is None and rec["old_inn_zh"] is None):
                skipped += 1
                continue
            if cur != rec["new_inn_zh"]:
                conflicts.append(f"{sid}: 当前值 {cur!r} 已被改动，跳过")
                continue
            con.execute("UPDATE substance SET inn_zh=? WHERE substance_id=?",
                        (rec["old_inn_zh"], sid))
            restored += 1
        data["rolled_back_at"] = utc_now()
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        con.commit()
    except Exception:
        con.rollback()
        raise
    print(f"已恢复 {restored} 行；已回滚/未改跳过 {skipped} 行")
    if conflicts:
        print(f"!! {len(conflicts)} 个冲突未恢复:")
        for c in conflicts[:20]:
            print("   " + c)
        raise SystemExit(2)


def _en_words(text: str) -> set[str]:
    """取英文词集合（小写），用于和盐型词表比对。"""
    return set(re.findall(r"[a-z]+", (text or "").lower()))


def _en_salt_hits(text: str) -> list[str]:
    """inn_en 里自带的盐型词（含 dinitrate / triphosphate 这类倍数前缀）。"""
    hits: set[str] = set()
    for tok in _en_words(text):
        if tok in EN_SALT_WORDS:
            hits.add(tok)
            continue
        for pre in ("di", "tri", "tetra", "mono", "hemi", "bi"):
            if tok.startswith(pre) and tok[len(pre):] in EN_SALT_WORDS:
                hits.add(tok)
                break
    return sorted(hits)


def _strip_salt_edges(zh: str) -> tuple[str, list[str], bool]:
    """只从**两端**剥盐型词；返回 (残形, 剥掉的词, 残形里是否还有盐型词)。

    · 先剥词尾（阳离子/有机碱），再剥词头（酸根）：依地酸钙钠 → 依地酸钙 → 依地酸；
    · 词中检查只用**多字**盐型词：钠/钾/铁 这类单字在成分名里常是名称的一部分
      （去铁胺、硫糖铝），不能当成「没剥干净」。
    """
    used: list[str] = []
    cur = zh
    for _ in range(4):
        changed = False
        for s in SALT_SUFFIXES:
            if cur.endswith(s) and len(cur) > len(s):
                cur, changed = cur[: -len(s)], True
                used.append(s)
                break
        for p in SALT_PREFIXES:
            if cur.startswith(p) and len(cur) > len(p):
                cur, changed = cur[len(p):], True
                used.append(p)
                break
        if not changed:
            break
    multi = [w for w in DETECT_ZH if len(w) >= 2]
    inside = any(w in cur for w in multi) and cur not in SALT_ZH2EN
    return cur, used, inside


def _classify_salt_row(inn_en: str, zh: str, variants: list[tuple[str, str]],
                       other_zh: dict[str, str]) -> dict:
    """判一条含盐型词的中文名：该剥 / 该丢 / 为什么。"""
    residual, used, inside = _strip_salt_edges(zh)
    out = dict(residual=residual, salt_word="+".join(used), verdict="",
               reason="", evidence="", confidence="")
    if not ASCII_EN_RE.match(inn_en or ""):
        return dict(out, verdict="discard",
                    reason="inn_en 本身不是英文（中文/西语等名），没有可对照的英文成分名")
    en_salt = _en_salt_hits(inn_en)
    if en_salt:
        return dict(out, verdict="discard",
                    reason=f"inn_en 自带盐型词（{','.join(en_salt)}），该成分本身就是这个盐")
    if not used:
        return dict(out, verdict="discard",
                    reason="盐型词在词中/词尾但剥不动，无法在不改原名的前提下得到成分名")
    if inside:
        return dict(out, verdict="discard", reason="残形里仍有盐型词，剥离不干净")
    if len(residual.strip()) < 2 or not CJK_RE.search(residual):
        return dict(out, verdict="discard", reason="残形过短/无中文，剥完不是成分名")
    if residual.endswith(BAD_RESIDUAL_TAIL):
        return dict(out, verdict="discard",
                    reason=f"残形以「{residual[-1]}」结尾，不是成分名"
                           "（酸/盐/酯是化学类别词）")
    if residual.endswith("酯") and any(w in CATION_ZH2EN for w in used):
        return dict(out, verdict="discard",
                    reason="剥掉阳离子后剩下的是酯名，base 在酯的前面，规则剥不到")
    if residual in BARE_ION:
        return dict(out, verdict="discard", reason="残形是金属/离子词，本身即盐")
    if (residual in SALT_ZH2EN or residual in CATION_ZH2EN) \
            and not residual.endswith("酸"):
        return dict(out, verdict="discard", reason="残形本身仍是盐型词（如「碘化」），不是成分名")
    if residual in other_zh:
        return dict(out, verdict="discard",
                    reason=f"残形与另一成分的中文名重名（{other_zh[residual]}），会撞名")
    want: set[str] = set()
    for w in used:
        want |= set(SALT_ZH2EN.get(w, ())) | set(CATION_ZH2EN.get(w, ()))
    variant_words: set[str] = set()
    for salt, code in variants:
        variant_words |= _en_words(salt) | _en_words(code)
    var_hit = sorted(want & variant_words)
    if var_hit:
        return dict(out, verdict="fix", confidence="high",
                    evidence=f"variant={','.join(var_hit)}",
                    reason=f"variant 层有这个盐型（{','.join(var_hit)}），"
                           "中文名抢用了盐型名")
    return dict(out, verdict="fix", confidence="medium", evidence="none",
                reason="variant 层没有该盐型，按构词剥离（已人工复核）")


def build_salt_fix_rows(con: sqlite3.Connection) -> list[dict]:
    """扫全库，给每条形如「盐酸X/硫酸X/X钠」的中文成分名定性（只读）。"""
    variants: dict[str, list[tuple[str, str]]] = {}
    for r in con.execute("SELECT substance_id, salt, salt_code FROM variant"):
        variants.setdefault(r["substance_id"], []).append(
            (r["salt"] or "", r["salt_code"] or ""))
    subs = con.execute(
        "SELECT substance_id, inn_en, inn_zh FROM substance"
        " WHERE trim(coalesce(inn_zh,''))<>'' ORDER BY substance_id").fetchall()
    other_zh: dict[str, str] = {}
    for r in subs:
        other_zh.setdefault(r["inn_zh"], r["substance_id"])
    pat = re.compile("|".join(map(re.escape, DETECT_ZH)))
    rows: list[dict] = []
    for r in subs:
        zh = r["inn_zh"]
        if not pat.search(zh):
            continue
        c = _classify_salt_row(r["inn_en"], zh, variants.get(r["substance_id"], []),
                              other_zh)
        sid = r["substance_id"]
        if sid in KEEP_OVERRIDES:
            new_zh, why = KEEP_OVERRIDES[sid]
            c = dict(c, residual=new_zh, verdict="fix", confidence="medium",
                     evidence="manual", reason="人工复核要剥：" + why)
        if sid in DROP_OVERRIDES and c["verdict"] == "fix":
            c = dict(c, verdict="discard", confidence="",
                     reason="人工复核不剥：" + DROP_OVERRIDES[sid])
        vs = variants.get(r["substance_id"], [])
        salt_variants = "; ".join(sorted({(s or c2 or "base").strip()
                                          for s, c2 in vs})) if vs else ""
        rows.append({
            "substance_id": r["substance_id"],
            "inn_en": r["inn_en"],
            "inn_zh_old": zh,
            "inn_zh_new": c["residual"] if c["verdict"] == "fix" else "",
            "salt_word": c["salt_word"],
            "salt_variants": salt_variants,
            "method": ("strip_salt_affix" if c["verdict"] == "fix" else "discard"),
            "source": ("variant 盐型对照" if c["evidence"].startswith("variant")
                       else ("仅构词剥离" if c["verdict"] == "fix" else "规则丢弃")),
            "confidence": c["confidence"],
            "verdict": c["verdict"],
            "reason": c["reason"],
            "evidence": c["evidence"],
        })
    rows.sort(key=lambda x: (x["verdict"] != "fix", x["substance_id"]))
    return rows


def write_salt_fix_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SALT_FIX_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def load_salt_fix_rows(path: Path) -> list[dict]:
    rows = []
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        rows.append({k: (r.get(k) or "").strip() for k in SALT_FIX_FIELDS})
    return rows


def build_salt_fix_plan(con: sqlite3.Connection, rows: list[dict]) -> dict:
    """把清单变成可执行计划：能改的、幂等跳过的、冲突的。"""
    accepted, conflicts, done = [], [], []
    dist: Counter = Counter()
    for r in rows:
        if r["verdict"] != "fix":
            dist["清单里判为丢弃"] += 1
            continue
        row = con.execute("SELECT substance_id, inn_en, inn_zh FROM substance"
                          " WHERE substance_id=?", (r["substance_id"],)).fetchone()
        if row is None:
            conflicts.append(dict(r, why="substance 已不存在"))
            continue
        if (row["inn_en"] or "") != r["inn_en"]:
            conflicts.append(dict(r, why=f"inn_en 不一致：库内 {row['inn_en']!r}"))
            continue
        cur = row["inn_zh"] or ""
        if cur == r["inn_zh_new"]:
            done.append(dict(r, why="已是修正后的名字（幂等跳过）"))
            continue
        if cur != r["inn_zh_old"]:
            conflicts.append(dict(r, why=f"当前 inn_zh {cur!r} 与清单旧值不一致"))
            continue
        accepted.append(r)
        dist[f"confidence_{r['confidence'] or 'unknown'}"] += 1
    return dict(rows=rows, accepted=accepted, conflicts=conflicts, done=done,
                dist=dist)


def print_salt_fix_plan(p: dict, db_path: Path) -> None:
    fix = [r for r in p["rows"] if r["verdict"] == "fix"]
    drop = [r for r in p["rows"] if r["verdict"] != "fix"]
    print(f"DB: {db_path}")
    print(f"清单 {len(p['rows'])} 行：可修正 {len(fix)} / 丢弃 {len(drop)}")
    print(f"本次将写库 {len(p['accepted'])} 行；冲突 {len(p['conflicts'])}；"
          f"幂等跳过 {len(p['done'])}")
    print("分布:", dict(p["dist"]))
    drop_why: Counter = Counter(r["reason"].split("（")[0].split("：")[0] for r in drop)
    if drop_why:
        print("\n丢弃原因（前 8）:")
        for why, n in drop_why.most_common(8):
            print(f"  {n:5d}  {why}")
    if p["conflicts"]:
        print("\n!! 冲突（前 10，未写入）:")
        for c in p["conflicts"][:10]:
            print(f"  {c['substance_id']}: {c['why']}")
    print("\n样例（前 20）:")
    for r in p["accepted"][:20]:
        print(f"  {r['inn_en']:<26} {r['inn_zh_old']:<16} -> {r['inn_zh_new']:<14}"
              f" {r['confidence']:<6} {r['evidence']}")


def _alias_norm(alias: str) -> str:
    """与 `data/seed_nicknames.py` 同一套归一化（nickname.alias_norm）。"""
    sys.path.insert(0, str(ROOT / "etl"))
    from normalize_name import normalize  # noqa: PLC0415
    return normalize(alias).norm


def apply_salt_fix(con: sqlite3.Connection, p: dict, db_path: Path,
                   csv_path: Path, manifest_path: Path) -> int:
    """事务内：inn_zh 改成基础成分名 + 旧盐型名进 nickname（一次写完）。"""
    accepted = p["accepted"]
    if not accepted:
        print("没有需要修正的行（幂等或全部跳过），未写库。")
        return 0
    today = datetime.now(timezone.utc).date().isoformat()
    manifest = dict(tool="etl/apply_inn_zh.py --fix-salt-forms",
                    mode="fix_salt_forms", db=str(db_path.resolve()),
                    csv=str(csv_path.resolve()),
                    csv_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                    created_at=utc_now(), committed=False, rows=[])
    try:
        con.execute("BEGIN IMMEDIATE")
        for a in accepted:
            sid, old, new = a["substance_id"], a["inn_zh_old"], a["inn_zh_new"]
            cur = con.execute(
                "UPDATE substance SET inn_zh=? WHERE substance_id=? AND inn_zh=?",
                (new, sid, old))
            if cur.rowcount != 1:
                raise RuntimeError(f"更新 {sid} 影响 {cur.rowcount} 行，中止")
            alias = old
            norm = _alias_norm(alias)
            nick_before = con.execute(
                "SELECT nickname_id FROM nickname WHERE alias_norm=? AND substance_id=?",
                (norm, sid)).fetchone()
            if nick_before is None:
                con.execute(
                    "INSERT INTO nickname (substance_id, alias, alias_norm, label_zh,"
                    " kind, confidence, source, note, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (sid, alias, norm, new, "misnomer", "community", NICK_SOURCE,
                     f"合并前 substance.inn_zh 的盐型写法；T17 规范化为「{new}」，"
                     f"盐型看 variant 层。", today))
            manifest["rows"].append(dict(
                substance_id=sid, inn_en=a["inn_en"], old_inn_zh=old,
                new_inn_zh=new, confidence=a["confidence"],
                evidence=a["evidence"], salt_word=a["salt_word"],
                nickname_alias=alias, nickname_alias_norm=norm,
                nickname_created=nick_before is None))
        manifest["updated"] = len(manifest["rows"])
        manifest["nicknames_created"] = sum(
            1 for r in manifest["rows"] if r["nickname_created"])
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        con.commit()
        manifest["committed"] = True
        manifest["committed_at"] = utc_now()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    except Exception:
        con.rollback()
        print("!! 写库失败，已回滚事务", file=sys.stderr)
        raise
    print(f"已修正 {len(accepted)} 行 inn_zh；新增 nickname "
          f"{manifest['nicknames_created']} 条；撤销清单: {manifest_path}")
    return len(accepted)


def rollback_salt_fix(con: sqlite3.Connection, data: dict,
                      manifest_path: Path) -> tuple[int, int, list[str]]:
    """撤销盐型修正：inn_zh 还原 + 删掉本清单新增的 nickname（幂等）。"""
    restored = nick_deleted = 0
    conflicts: list[str] = []
    con.execute("BEGIN IMMEDIATE")
    try:
        for rec in reversed(data.get("rows", [])):
            sid = rec["substance_id"]
            row = con.execute("SELECT inn_zh FROM substance WHERE substance_id=?",
                              (sid,)).fetchone()
            if row is None:
                conflicts.append(f"{sid}: substance 已不存在")
                continue
            cur = row["inn_zh"]
            if cur == rec["old_inn_zh"]:
                restored += 0  # 已经是旧值：之前回滚过，幂等跳过
            elif cur != rec["new_inn_zh"]:
                conflicts.append(f"{sid}: 当前值 {cur!r} 已被改动，跳过")
            else:
                con.execute("UPDATE substance SET inn_zh=? WHERE substance_id=?",
                            (rec["old_inn_zh"], sid))
                restored += 1
            norm = rec.get("nickname_alias_norm")
            if norm and rec.get("nickname_created"):
                d = con.execute(
                    "DELETE FROM nickname WHERE substance_id=? AND alias_norm=?"
                    " AND source=?", (sid, norm, NICK_SOURCE))
                nick_deleted += d.rowcount
        data["rolled_back_at"] = utc_now()
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        con.commit()
    except Exception:
        con.rollback()
        raise
    return restored, nick_deleted, conflicts


def sync_backfill_csv(salt_rows: list[dict], csv_path: Path,
                      apply: bool) -> tuple[int, int]:
    """把盐型清单的修正同步进 `data/inn_zh_backfill.csv` 的候选名。

    为什么：回填 CSV 是「重建后补 inn_zh」的数据源。如果它里面还写着盐型名
    （盐酸利多卡因），重建一次 apply 又会把盐型名写回 `substance.inn_zh`。
    只改「候选名 == 清单旧值」的行，其余行一动不动；证据栏追加 T17 标记。
    """
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
    fields = list(rows[0].keys()) if rows else []
    fix = {r["substance_id"]: r for r in salt_rows if r["verdict"] == "fix"}
    changed, touched = 0, 0
    for row in rows:
        sid = row["substance_id"]
        r = fix.get(sid)
        if not r or (row["zh_candidate"] or "") != r["inn_zh_old"]:
            continue
        touched += 1
        row["zh_candidate"] = r["inn_zh_new"]
        marker = (f"T17 2026-11-15 盐型名剥离：原候选「{r['inn_zh_old']}」→"
                  f"「{r['inn_zh_new']}」（{r['reason']}）")
        ev = row.get("evidence") or ""
        if "T17 2026-11-15" not in ev:
            row["evidence"] = f"{ev}；{marker}" if ev else marker
            changed += 1
    print(f"回填 CSV：命中 {touched} 行，改动 {changed} 行")
    if apply and changed:
        # 原文件没有 BOM，写回也保持无 BOM（读的时候用 utf-8-sig 容错）
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        print(f"已写回 {csv_path}")
    return touched, changed


def main() -> None:
    ap = argparse.ArgumentParser(description="把 inn_zh 回填 CSV 写入 substance.inn_zh"
                                             "（默认 dry-run）")
    ap.add_argument("--csv", default=str(CSV_DEFAULT))
    ap.add_argument("--db", default=str(DB_DEFAULT))
    ap.add_argument("--min-confidence", choices=["high", "medium", "low"],
                    default="high", help="最低置信度（默认 high）")
    ap.add_argument("--apply", action="store_true", help="事务写库 + 撤销清单")
    ap.add_argument("--dry-run", action="store_true", help="只出计划（默认）")
    ap.add_argument("--rollback", nargs="?", const="latest", default=None)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--build-salt-fix-list", action="store_true",
                    help="只读 DB，重新生成盐型名清单 CSV")
    ap.add_argument("--fix-salt-forms", action="store_true",
                    help="盐型名修正模式（默认 dry-run，配 --apply 写库）")
    ap.add_argument("--salt-fix-csv", default=str(SALT_FIX_CSV),
                    help="盐型名清单 CSV（默认 data/sources/）")
    ap.add_argument("--sync-backfill-csv", action="store_true",
                    help="把盐型修正同步进 data/inn_zh_backfill.csv 的候选名")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"数据库不存在: {db_path}")
    salt_csv = Path(args.salt_fix_csv)

    if args.sync_backfill_csv:
        if not salt_csv.exists():
            raise SystemExit(f"盐型清单不存在: {salt_csv}")
        sync_backfill_csv(load_salt_fix_rows(salt_csv), Path(args.csv), args.apply)
        return

    if args.build_salt_fix_list:
        con = connect(db_path, readonly=True)
        try:
            rows = build_salt_fix_rows(con)
            write_salt_fix_csv(rows, salt_csv)
        finally:
            con.close()
        fix = sum(1 for r in rows if r["verdict"] == "fix")
        print(f"清单 {len(rows)} 行：可修正 {fix} / 丢弃 {len(rows) - fix}")
        print(f"已写入 {salt_csv}（只读生成，未写库）")
        return

    if args.rollback is not None:
        con = connect(db_path, readonly=False)
        try:
            if args.rollback == "latest":
                cands = sorted(MANIFEST_DIR.glob("undo_*.json"),
                               key=lambda p: p.stat().st_mtime)
                if not cands:
                    raise SystemExit(f"{MANIFEST_DIR} 下没有 undo_*.json")
                mp = cands[-1]
            else:
                mp = Path(args.rollback)
            print(f"回滚清单: {mp}")
            data = json.loads(mp.read_text(encoding="utf-8"))
            if data.get("mode") == "fix_salt_forms":
                if not data.get("committed"):
                    raise SystemExit(f"清单 {mp} 未标记 committed，拒绝回滚")
                restored, nick_deleted, conflicts = rollback_salt_fix(con, data, mp)
                print(f"已恢复 inn_zh {restored} 行；删除 nickname {nick_deleted} 条")
                if conflicts:
                    print(f"!! {len(conflicts)} 个冲突未恢复:")
                    for c in conflicts[:20]:
                        print("   " + c)
                    raise SystemExit(2)
                return
            rollback(con, mp)
        finally:
            con.close()
        return

    if args.fix_salt_forms:
        if not salt_csv.exists():
            raise SystemExit(f"盐型清单不存在: {salt_csv}"
                             "（先跑 --build-salt-fix-list）")
        rows = load_salt_fix_rows(salt_csv)
        con = connect(db_path, readonly=not args.apply)
        try:
            p = build_salt_fix_plan(con, rows)
            print(f"清单: {salt_csv}")
            print()
            print_salt_fix_plan(p, db_path)
            if args.apply:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                manifest = Path(args.manifest) if args.manifest else (
                    MANIFEST_DIR / f"undo_saltfix_{stamp}.json")
                print()
                apply_salt_fix(con, p, db_path, salt_csv, manifest)
            else:
                print("\n(dry-run，未写库。核对后加 --apply 执行)")
        finally:
            con.close()
        return

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"回填 CSV 不存在: {csv_path}")

    rows = load_rows(csv_path)
    con = connect(db_path, readonly=not args.apply)
    try:
        p = build_plan(con, rows, args.min_confidence)
        print(f"DB: {db_path}  ({'只读' if not args.apply else '读写'})")
        print(f"CSV: {csv_path}")
        print()
        print_plan(p, args.min_confidence)
        if args.apply:
            if p["skipped"]:
                # 只提示：已有值/失效行跳过是幂等设计，不阻断
                print(f"\n（{len(p['skipped'])} 行跳过，见上）")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            manifest = Path(args.manifest) if args.manifest else (
                MANIFEST_DIR / f"undo_{stamp}.json")
            print()
            apply_plan(con, p, db_path, csv_path, manifest)
        else:
            print("\n(dry-run，未写库。Lead 审核后加 --apply 执行)")
    finally:
        con.close()


if __name__ == "__main__":
    main()
