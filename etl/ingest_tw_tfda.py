"""台湾 TFDA「全部藥品許可證資料集」→ 入库 ETL 骨架（**dry-run，不写 DB**）。

数据源
------
`data/raw/tw/tfda_36.csv`（`etl/fetch_tw_tfda.py` 抓取；data.gov.tw #9122，TFDA，
每 7 日更新，政府資料開放授權條款第 1 版，署名后可再发布；详见 reports/tw-tfda-audit.md）。

本脚本做什么
------------
1. 字段映射（TFDA 28 列 → 本站 product/product_name/product_component/variant/mah 方向）：
   - 許可證字號 → approval_id（去重后作为 product_id 的一部分）
   - 中文品名 / 英文品名 → product_name（trade，zh-Hant/en）
   - 主成分略述 → product_component（英文 token，`;;` / `;` / `、` 分隔）
   - 劑型 → dosage_form + form_base + release
   - 申請商名稱 → mah；製造商名稱/製造廠國別 → manufacturer / origin_country
   - 有效日期 + 註銷狀態 → status（active/discontinued）+ status_date
2. 状态判定：注销 → discontinued；未注销但过期 → discontinued（note=expired）；
   未注销且未过期 → active。
3. 产品类过滤（草案）：許可證種類 ∈ {製劑, 菌疫}；排除成藥/乙類成藥（草案）；
   排除中藥/植物药（拉丁名草稿名单，需人工复核）。
4. 成分解析：英文 token 优先；`(EQ TO …)` 括号清掉但保留备注；盐型按
   `ingest_openfda_ndc.split_salt` + `normalize_salts.classify_salt` 拆分；
   映射到现有 substance（只读 DB 的 inn_en + variant.salt；无 DB 时降级用
   `site/dist/data/index.json` 的英文成分名）。未匹配 token 单独输出，供下一轮补别名。
5. 规格：从中文/英文品名抽取（复用 `normalize_name.normalize().strengths`，
   中文单位先转英文：公絲/毫克→mg、公克→g、毫升→ml、微克→mcg、國際單位→IU），
   打分置信度 high/medium/low/none；多成分或品名多值时不猜，留 raw。
6. 去重：同一許可證字號多行（官方重复行/多包装变体）合并成一行，记录 variant_count。

边界
----
- **不写 `data/drugs.db`**；`--write-db` 只是占位（会报错提示先做 schema 迁移）。
- 前置阻塞：`product.country` 的 CHECK 枚举目前没有 'TW'（见 db/schema.sql 与
  db/init_db.py 的迁移逻辑），真正入库前必须先加 'TW'（下一任务）。
- `適應症`/`用法用量` 不进入输出（本站只存事实字段，不展示说明书正文）。
- 默认只处理 `--limit 2000` 条「产品类候选行」（扫描整表，取前 N 条候选），
  输出 `data/tw_ingest_dryrun.csv`；统计写 `.tmp/tw-ingest/stats.json`。

用法
----
    python etl/ingest_tw_tfda.py                      # dry-run，默认 2000 条候选
    python etl/ingest_tw_tfda.py --limit 0            # 全量 dry-run（不写 DB）
    python etl/ingest_tw_tfda.py --csv data/raw/tw/sample_active_500.csv --limit 500
    python etl/ingest_tw_tfda.py --write-db           # 占位：会报错（等 country 迁移）
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))

from ingest_openfda_ndc import slug  # noqa: E402
from normalize_name import normalize  # noqa: E402
from normalize_salts import classify_salt  # noqa: E402

try:  # 复用项目里的 BAN/USAN 别名表（可选）
    from ingest_pbs import EXTRA_ALIASES  # noqa: E402
except Exception:  # pragma: no cover - 别名表不可用时降级
    EXTRA_ALIASES = {}
try:
    from ingest_dmd import ALIASES  # noqa: E402
except Exception:  # pragma: no cover
    ALIASES = {}

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "raw" / "tw"
WORK = ROOT / ".tmp" / "tw-ingest"
DB = ROOT / "data" / "drugs.db"
INDEX = ROOT / "site" / "dist" / "data" / "index.json"
OUT_CSV = ROOT / "data" / "tw_ingest_dryrun.csv"
SOURCE_ID = "tw_tfda"
SOURCE_NAME = "衛生福利部食品藥物管理署（TFDA）全部藥品許可證資料集"
SOURCE_URL = "https://data.gov.tw/dataset/9122"
LICENSE_NAME = "政府資料開放授權條款－第1版 (OGDL v1.0)"
LICENSE_URL = "https://data.gov.tw/license"
TODAY = date.today().isoformat()

# 保留产品类；其余（原料藥/體外試劑/衛生材料/硬空膠囊）不入产品层
KEEP_KINDS = ("製劑", "菌疫")
# 草案排除：成藥/乙類成藥（下一轮可按产品策略放开）
OTC_DRAFT_EXCLUDE = ("成藥", "乙類成藥")
# 中藥/植物药草稿名单（拉丁名；SILYMARIN 等植物提取物是否排除待人工确认）
TCM_HERB_TOKENS = {
    "PHELLODENDRON", "GLYCYRRHIZA", "GINSENG", "PANAX", "CNIDIUM", "ANGELICA",
    "ASTRAGALUS", "REHMANNIA", "ATRACTYLODES", "PORIA", "CINNAMOMUM", "ZINGIBER",
    "SCHIZANDRA", "LYCIUM", "CHRYSANTHEMUM", "LONICERA", "FLOS", "RADIX", "HERBA",
    "RHIZOMA", "FRUCTUS", "SEMEN", "CORTEX", "EXSICCATED FRUCTUS",
}

# 输出列（dry-run 审阅用；DB 写入映射见 reports/tw-ingest-skeleton.md）
OUT_FIELDS = [
    "approval_id", "proposed_product_id", "kind", "category", "status", "status_date",
    "valid_until", "issued_date", "modified_date",
    "name_zh", "name_en", "form_raw", "form_base", "release",
    "mah", "manufacturer", "origin_country",
    "ingredients_raw", "ingredient_tokens", "components",
    "unmapped_tokens", "is_combo",
    "strength_raw", "strength_value", "strength_unit",
    "strength_per_volume_value", "strength_per_volume_unit", "strength_confidence",
    "variant_count", "row_hash", "source_id", "note",
]


# ---------------------------------------------------------------- 归一/映射工具
def nk(text: str) -> str:
    """成分名归一：NFKC → 大写 → 折叠空白/连字符。用于匹配现有 substance。"""
    s = unicodedata.normalize("NFKC", text or "").upper()
    s = re.sub(r"[®™©]", " ", s)
    s = re.sub(r"\s*\([^)]*\)", " ", s)      # 去 (EQ TO …) 等括号说明
    s = re.sub(r"[\u2010-\u2015\-]", "-", s)
    s = re.sub(r"[^A-Z0-9%./+\- ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def cn_units_to_en(text: str) -> str:
    """TW 剂型/规格里的中文单位先转英文，交给 normalize_name 的强度正则。"""
    repl = [
        ("公撮", "ml"), ("毫升", "ml"), ("公絲", "mg"), ("毫克", "mg"),
        ("微克", "mcg"), ("公克", "g"), ("國際單位", "IU"), ("国际单位", "IU"),
        ("萬單位", "IU"), ("万单位", "IU"),
    ]
    s = unicodedata.normalize("NFKC", text or "")
    for a, b in repl:
        s = s.replace(a, b)
    return s


def load_substance_map() -> tuple[dict[tuple[str, str], str], str]:
    """返回 {(归一成分, 盐): substance_id} 词典 + 来源标记。只读 DB（mode=ro）。"""
    mapping: dict[tuple[str, str], str] = {}
    source = "db"
    if DB.exists():
        try:
            db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
            db.row_factory = sqlite3.Row
            for r in db.execute(
                "SELECT s.substance_id, s.inn_en, COALESCE(v.salt,'') AS salt "
                "FROM substance s LEFT JOIN variant v ON v.substance_id = s.substance_id"
            ):
                inn = nk(r["inn_en"])
                if not inn:
                    continue
                salt = nk(r["salt"])
                mapping[(inn, salt)] = r["substance_id"]
                mapping.setdefault((inn, ""), r["substance_id"])
            db.close()
        except sqlite3.Error as e:  # pragma: no cover
            print(f"! 读 DB 词典失败（降级 index.json）: {e}")
            source = "index"
    if source == "index" or not mapping:
        source = "index"
        mapping = {}
        if INDEX.exists():
            idx = json.loads(INDEX.read_text(encoding="utf-8"))
            for e in idx:
                sid = e.get("v")
                if not sid:
                    continue
                for nm in str(e.get("x") or "").split(" + "):
                    nm = nk(nm)
                    if nm:
                        mapping.setdefault((nm, ""), sid)
                        mapping.setdefault((nm.split(" (")[0].strip(), ""), sid)
    return mapping, source


def alias_candidates(token: str) -> list[str]:
    """BAN/USAN 等历史别名 → 候选规范名（都可能命中）。"""
    out = []
    low = token.lower().strip()
    for table in (EXTRA_ALIASES, ALIASES):
        if not isinstance(table, dict):
            continue
        v = table.get(low)
        if isinstance(v, str) and v:
            out.append(v)
    return out


# TFDA 成分串里常见的写法差异：盐型缩写、拼写、剂型/描述词、同位素前缀
SALT_EXTRA = {
    "hbr": "hydrobromide", "hcl": "hydrochloride", "dihcl": "dihydrochloride",
    "2hcl": "dihydrochloride", "bisulfite": "bisulfite", "bisulphite": "bisulphite",
    "monohydate": "monohydrate", "sesquihydrate": "sesquihydrate",
    "mesilate": "mesylate", "napsylate": "napsylate", "xinafoate": "xinafoate",
}
SALT_TAIL = {
    "hydrochloride", "hydrobromide", "sodium", "potassium", "calcium", "magnesium",
    "besylate", "mesylate", "mesilate", "tosylate", "maleate", "tartrate", "succinate",
    "fumarate", "citrate", "sulfate", "sulphate", "phosphate", "nitrate", "acetate",
    "bromide", "chloride", "iodide", "hydrate", "dihydrate", "monohydrate",
    "trihydrate", "anhydrous", "disodium", "dipropionate", "propionate", "valerate",
    "pamoate", "embonate", "stearate", "palmitate", "decanoate", "enanthate",
    "cypionate", "undecanoate", "benzoate", "lactate", "gluconate", "aspartate",
    "tromethamine", "meglumine", "xinafoate", "furoate", "aceponate", "buteprate",
    "hbr", "hcl", "dihcl", "bisulfite", "bisulphite", "monohydate", "hydrate",
    "sesquihydrate", "hemihydrate", "ethanolate", "solvate",
}
DESCRIPTORS = {
    "ANHYDROUS", "DRIED", "STERILE", "MICRONIZED", "MICRONISED", "HP", "MEDICINAL",
    "PELLET", "PELLETS", "GRANULE", "GRANULES", "POWDER", "SOLUTION", "SUSPENSION",
    "INJECTION", "TABLET", "TABLETS", "CAPSULE", "CAPSULES", "OINTMENT", "CREAM",
    "GEL", "LOTION", "SPRAY", "DROPS", "SYRUP", "ELIXIR", "EMULSION", "CONCENTRATE",
    "EXTRACT", "EQ", "USP", "BP", "JP", "PH", "EUR", "TECHNICAL", "GRADE",
}


def _clean_variants(raw: str) -> list[str]:
    """同一成分串的可能写法（去括号/剂型词/描述词/同位素前缀/百分号）。"""
    base = nk(raw)
    if not base:
        return []
    variants = [base]
    s = re.sub(r"^\d+(\.\d+)?%\s*", "", base)
    s = re.sub(r"^C-\d+\s+", "", s)
    s = re.sub(r"\b(EQ|USP|BP|JP)\b", " ", s)
    variants.append(re.sub(r"\s+", " ", s).strip())
    words = [w for w in s.split() if w not in DESCRIPTORS]
    variants.append(" ".join(words))
    variants.append(" ".join(words[:2]) if len(words) > 2 else " ".join(words))
    out = []
    for v in variants:
        v = v.strip()
        if v and v not in out:
            out.append(v)
    return out


def _split_salt_local(base: str) -> tuple[str, str]:
    """拆尾部盐/水合物（补充 TFDA 常见缩写/拼写差异）。"""
    words = base.replace("-", " ").split()
    tail: list[str] = []
    while words:
        w = words[-1].lower()
        if w in SALT_TAIL or re.fullmatch(r"\d+(hcl|hbr)", w):
            tail.insert(0, words.pop())
        else:
            break
    return " ".join(words), " ".join(tail)


def match_component(raw: str, mapping: dict[tuple[str, str], str]) -> dict:
    """单个成分段 → {raw, norm, salt, salt_code, substance_id, note}。"""
    rec = {"raw": raw, "norm": nk(raw), "salt": "", "salt_code": "",
           "substance_id": None, "note": ""}
    if not rec["norm"]:
        rec["note"] = "empty"
        return rec
    # 括号里的盐型（"KANAMYCIN (SULFATE)"）在 nk 时被去掉，这里单独补回
    paren = " ".join(re.findall(r"\(([^)]*)\)", raw or ""))
    paren_salt = ""
    if paren and "EQ" not in paren.upper() and not re.search(r"\d", paren):
        cl = classify_salt(paren)
        if cl.kind == "salt" and cl.salt_code:
            paren_salt = paren

    def mark(sid: str, salt: str = "", note: str = "") -> dict:
        salt = salt or paren_salt
        salt_en = SALT_EXTRA.get(salt.lower(), salt)
        rec.update(substance_id=sid, salt=salt,
                   salt_code=classify_salt(salt_en).salt_code if salt_en else "",
                   note=note)
        return rec

    for base in _clean_variants(raw):
        # 1) 整段直接命中
        sid = mapping.get((base, ""))
        if sid:
            return mark(sid)
        # 2) 拆尾部盐/水合物 → 基础名
        b, salt = _split_salt_local(base)
        salt_en = SALT_EXTRA.get(salt.lower(), salt)
        sid = mapping.get((nk(b), nk(salt_en))) or mapping.get((nk(b), ""))
        if sid:
            return mark(sid, salt)
        # 3) 去前缀 DL-/L-/D-、连字符当空格、别名表
        cands = [base]
        for pre in ("DL-", "L-", "D-", "DL ", "L ", "D "):
            if base.startswith(pre):
                cands.append(base[len(pre):])
        cands.append(base.replace("-", " "))
        cands.extend(alias_candidates(base))
        cands.extend(alias_candidates(base.replace("-", " ")))
        for c in cands:
            c = nk(c)
            sid = mapping.get((c, ""))
            if sid:
                return mark(sid, salt, "alias/prefix")
            b2, s2 = _split_salt_local(c)
            s2_en = SALT_EXTRA.get(s2.lower(), s2)
            sid = mapping.get((nk(b2), nk(s2_en)))
            if sid:
                return mark(sid, s2, "alias/prefix")
    rec["note"] = "unmatched"
    return rec


# ---------------------------------------------------------------- 字段解析
def split_ingredients(raw: str) -> list[str]:
    """主成分略述 → 成分段列表。分隔符：;; ; 、（保留括号内容交给 nk 清理）。"""
    s = (raw or "").strip()
    if not s:
        return []
    parts = [p.strip() for p in re.split(r";;|;|、", s) if p.strip()]
    out = []
    for p in parts:
        # 极少数用 " + " 连接多成分
        if " + " in p:
            out.extend(x.strip() for x in p.split(" + ") if x.strip())
        else:
            out.append(p)
    return out


FORM_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tablet", ("口溶膜", "錠", "片")),
    ("capsule", ("膠囊", "胶囊")),
    ("injection", ("注射", "輸液", "输液", "點滴")),
    ("inhalation", ("吸入", "噴霧", "喷雾", "吸入劑")),
    ("suppository", ("栓", "灌腸", "灌肠", "浣腸")),
    ("topical", ("軟膏", "软膏", "乳膏", "凝膠", "凝胶", "貼", "贴", "藥膠布",
                 "洗劑", "洗剂", "擦劑", "擦剂", "泡沫", "外用", "口內膏", "點眼膏",
                 "洗髮", "洗发", "油劑", "油剂", "乳膠", "乳胶", "霜劑", "霜剂", "糊劑")),
    ("powder", ("粉", "顆粒", "颗粒", "散劑", "散剂", "細粒")),
    ("liquid", ("液", "糖漿", "糖浆", "酏", "乳劑", "乳剂", "滴劑", "滴剂",
                "口服液", "懸液", "悬液", "溶液", "漱口", "酊劑", "酊剂", "醑劑")),
    ("other", ("植入", "紗布", "敷料", "釋放系統", "避孕器", "醫用氣體", "卫生材料",
               "衛生材料")),
)


def tw_form_base(form: str) -> str:
    f = re.sub(r"\s+", "", form or "")
    for base, keys in FORM_MAP:
        if any(k in f for k in keys):
            return base
    return "unknown"


RELEASE_RE = re.compile(
    r"持續|持续|緩釋|缓释|控釋|控释|長效|长效|腸溶|肠溶|延釋|延释|"
    r"\b(ER|SR|XR|MR|CR|DR|IR)\b|extended|prolonged|sustained|modified|controlled|enteric",
    re.IGNORECASE)


def release_of(form: str, *texts: str) -> str:
    t = " ".join([form or ""] + list(texts)).lower()
    if re.search(r"腸溶|肠溶|enteric|delayed", t):
        return "DR"
    if re.search(r"持續|持续|緩釋|缓释|控釋|控释|長效|长效|延釋|延释|"
                 r"extended|prolonged|sustained|modified|controlled|"
                 r"(\b(ER|SR|XR|MR|CR)\b)", t):
        return "ER"
    return "none"


def parse_strengths(zh: str, en: str) -> tuple[list[tuple[str, str]], str]:
    """从中文/英文品名抽强度，返回 ([(value, unit)], 来源说明)。"""
    unit_map = {"ug": "mcg", "μg": "mcg", "µg": "mcg", "iu": "IU"}
    got: list[tuple[str, str]] = []
    src = []
    for tag, text in (("zh", zh), ("en", en)):
        if not text:
            continue
        for v, u in normalize(cn_units_to_en(text)).strengths:
            got.append((str(v), unit_map.get((u or "").lower(), (u or "").lower())))
            src.append(tag)
    # 去重：单位先规范化，数值按 float 比较（中文 1 mg 与英文 1.0MG 视为同一强度）
    seen: set[tuple] = set()
    uniq: list[tuple[str, str]] = []
    for v, u in got:
        try:
            key = (round(float(v), 6), u)
        except ValueError:
            key = (v, u)
        if key not in seen:
            seen.add(key)
            uniq.append((v, u))
    return uniq, "+".join(sorted(set(src)))


UNIT_CANON = {"ug": "mcg", "μg": "mcg", "µg": "mcg", "iu": "IU"}


def _canon_unit(u: str) -> str:
    return UNIT_CANON.get((u or "").lower(), (u or "").lower())


def decide_strength(strengths: list[tuple[str, str]], n_components: int,
                    raw_zh: str, raw_en: str
                    ) -> tuple[str, str, str, str, str, str]:
    """返回 (raw, value, unit, per_volume_value, per_volume_unit, confidence)。

    多成分 / 品名多个数值 → 不猜（none/low）；单成分浓度（x mg/y ml）→ 拆成
    strength + per_volume（schema 的 product_component 有 per_volume_* 列）。
    """
    raw = " | ".join(f"{v} {u}".strip() for v, u in strengths) if strengths else ""
    if not strengths:
        return "", "", "", "", "", "none"
    if n_components > 1:
        return raw, "", "", "", "", "none"   # 复方各成分强度不同，品名串无法归属
    entries = [(v, _canon_unit(u)) for v, u in strengths]
    if len(entries) > 1:
        # 常见：`20mg/ml` 被 normalize 拆成 20 mg + 1 ml 两条 → 合成 per_volume
        if len(entries) == 2:
            mass = [e for e in entries if e[1] in ("mg", "mcg", "g", "IU", "%")]
            vol = [e for e in entries if e[1] in ("ml", "l")]
            if mass and vol:
                return raw, mass[0][0], mass[0][1], vol[0][0], vol[0][1], "medium"
        return raw, "", "", "", "", "low"
    v, u = entries[0]
    if "/" in v and "/" in u:
        a, b = v.split("/", 1)
        u1, u2 = u.split("/", 1)
        if a.strip() and b.strip():
            return raw, a.strip(), _canon_unit(u1), b.strip(), _canon_unit(u2), "medium"
    return raw, v, u, "", "", "medium"


def status_of(row: dict) -> tuple[str, str, str]:
    """返回 (status, status_date, note)。"""
    cancel = (row["註銷狀態"] or "").strip()
    valid = (row["有效日期"] or "").strip().replace("/", "-")
    if cancel:
        return "discontinued", (row["註銷日期"] or "").strip().replace("/", "-"), f"cancelled:{cancel}"
    if valid and valid < TODAY:
        return "discontinued", valid, "expired"
    return "active", None, ""


def product_id_of(approval_id: str) -> str:
    """建议 product_id：TW-TFDA-<可读 slug 或 md5>（写入 DB 前与 ingest 脚本统一）。"""
    s = slug(approval_id)
    if s == "unknown" or len(s) < 4:
        s = hashlib.md5(approval_id.encode("utf-8")).hexdigest()[:10]
    return f"TW-TFDA-{s[:60]}"


# ---------------------------------------------------------------- 主流程
def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "big5", "cp950"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "replace")
    rows = [r for r in csv.DictReader(io.StringIO(text))]
    return list(rows[0].keys()) if rows else [], rows


def pick_csv(arg: str | None) -> Path:
    if arg:
        p = Path(arg)
        return p if p.is_absolute() else ROOT / p
    full = CACHE / "tfda_36.csv"
    if full.exists():
        return full
    sample = CACHE / "sample_active_500.csv"
    if sample.exists():
        return sample
    raise SystemExit(f"找不到 {full}（先跑 python etl/fetch_tw_tfda.py）")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="TW TFDA 入库 ETL 骨架（默认 dry-run，不写 DB）")
    ap.add_argument("--csv", default=None, help="输入 CSV（默认 data/raw/tw/tfda_36.csv）")
    ap.add_argument("--limit", type=int, default=2000, help="处理前 N 条产品类候选行（0=全量）")
    ap.add_argument("--out", default=None, help="dry-run CSV 输出路径")
    ap.add_argument("--write-db", action="store_true",
                    help="占位：真正写库需先扩展 schema 的 country 枚举（TW）")
    args = ap.parse_args(argv)
    if args.write_db:
        raise SystemExit(
            "写库尚未实现：先完成 db/schema.sql + db/init_db.py 的 country CHECK 迁移（新增 'TW'），"
            "再接 product/product_name/product_component 写入。本脚本只做 dry-run。")

    src = pick_csv(args.csv)
    header, rows = read_csv(src)
    print(f"输入：{src.relative_to(ROOT)}  {len(rows):,} 行 × {len(header)} 列")

    meta_path = CACHE / "meta_9122.json"
    data_as_of = ""
    if meta_path.exists():
        try:
            data_as_of = json.loads(meta_path.read_text(encoding="utf-8")).get("data_as_of", "")
        except ValueError:
            pass
    mapping, map_source = load_substance_map()
    print(f"成分词典：{len(mapping):,} 个 (名,盐) 组合（来源 {map_source}）；"
          f"data_as_of={data_as_of or '?'}")

    stats = {
        "source": SOURCE_ID, "source_name": SOURCE_NAME, "source_url": SOURCE_URL,
        "license": LICENSE_NAME, "license_url": LICENSE_URL,
        "data_as_of": data_as_of, "input": str(src.relative_to(ROOT)),
        "rows_total": len(rows), "map_source": map_source,
        "limit": args.limit, "today": TODAY,
        "reject": Counter(), "kept": 0, "scanned": 0, "eligible_seen": 0,
    }
    tokens_total = 0
    tokens_matched = 0
    unmatched = Counter()
    form_counter = Counter()
    form_raw_counter = Counter()
    release_counter = Counter()
    status_counter = Counter()
    strength_conf = Counter()
    kept_rows: list[dict] = []
    seen_license: dict[str, dict] = {}

    for r in rows:
        stats["scanned"] += 1
        kind = re.sub(r"\s+", "", r.get("許可證種類") or "")
        if kind not in KEEP_KINDS:
            stats["reject"]["non_product_kind"] += 1
            continue
        status, status_date, note = status_of(r)
        if status != "active":
            stats["reject"]["inactive_" + (note.split(":")[0] or "unknown")] += 1
            continue
        category = (r.get("藥品類別") or "").strip()
        if any(x in category for x in OTC_DRAFT_EXCLUDE):
            stats["reject"]["otc_draft_excluded"] += 1
            continue
        ing_raw = (r.get("主成分略述") or "").strip()
        ing_parts = split_ingredients(ing_raw)
        if not ing_parts:
            stats["reject"]["no_ingredient"] += 1
            continue
        upper_ing = nk(ing_raw)
        if any(t in upper_ing for t in TCM_HERB_TOKENS):
            stats["reject"]["tcm_herb_draft"] += 1
            continue
        if args.limit and stats["eligible_seen"] >= args.limit:
            break
        stats["eligible_seen"] += 1

        comps = [match_component(p, mapping) for p in ing_parts]
        for c in comps:
            tokens_total += 1
            if c["substance_id"]:
                tokens_matched += 1
            else:
                unmatched[c["norm"] or c["raw"]] += 1
        unmapped = [c["raw"] for c in comps if not c["substance_id"]]
        comp_str = "; ".join(
            f"{c['raw']} => {c['substance_id'] or '?'}"
            + (f" [{c['salt_code']}]" if c["salt_code"] else "") for c in comps)

        zh = (r.get("中文品名") or "").strip()
        en = (r.get("英文品名") or "").strip()
        if not zh and not en:
            stats["reject"]["no_name"] += 1
            continue
        form_raw = (r.get("劑型") or "").strip()
        form_base = tw_form_base(form_raw)
        rel = release_of(form_raw, zh, en, ing_raw)
        strengths, _src = parse_strengths(zh, en)
        s_raw, s_val, s_unit, s_per_val, s_per_unit, s_conf = decide_strength(
            strengths, len(comps), zh, en)
        n_comp = len(comps)
        is_combo = 1 if n_comp > 1 else 0

        approval = (r.get("許可證字號") or "").strip()
        row_hash = hashlib.md5(
            json.dumps(r, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:10]
        prev = seen_license.get(approval)
        if prev is not None:
            prev["variant_count"] += 1
            if prev["row_hash"] != row_hash:
                prev["note"] += "|multi_row_variant"
            continue
        out = {
            "approval_id": approval,
            "proposed_product_id": product_id_of(approval),
            "kind": kind,
            "category": category,
            "status": status,
            "status_date": status_date or "",
            "valid_until": (r.get("有效日期") or "").strip().replace("/", "-"),
            "issued_date": (r.get("發證日期") or "").strip().replace("/", "-"),
            "modified_date": (r.get("異動日期") or "").strip().replace("/", "-"),
            "name_zh": zh,
            "name_en": en,
            "form_raw": form_raw,
            "form_base": form_base,
            "release": rel,
            "mah": (r.get("申請商名稱") or "").strip(),
            "manufacturer": (r.get("製造商名稱") or "").strip(),
            "origin_country": (r.get("製造廠國別") or "").strip(),
            "ingredients_raw": ing_raw,
            "ingredient_tokens": "; ".join(p for p in ing_parts),
            "components": comp_str,
            "unmapped_tokens": "; ".join(dict.fromkeys(unmapped)),
            "is_combo": is_combo,
            "strength_raw": s_raw,
            "strength_value": s_val,
            "strength_unit": s_unit,
            "strength_per_volume_value": s_per_val,
            "strength_per_volume_unit": s_per_unit,
            "strength_confidence": s_conf,
            "variant_count": 1,
            "row_hash": row_hash,
            "source_id": SOURCE_ID,
            "note": note,
        }
        seen_license[approval] = out
        kept_rows.append(out)
        stats["kept"] += 1
        form_counter[form_base] += 1
        form_raw_counter[form_raw] += 1
        release_counter[rel] += 1
        status_counter[status] += 1
        strength_conf[s_conf] += 1

    out_path = Path(args.out) if args.out else OUT_CSV
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(kept_rows)

    WORK.mkdir(parents=True, exist_ok=True)
    stats.update({
        "rows_kept": len(kept_rows),
        "rows_rejected": stats["scanned"] - len(kept_rows),
        "reject": dict(stats["reject"]),
        "components": {
            "tokens_total": tokens_total,
            "tokens_matched": tokens_matched,
            "token_coverage_pct": round(100 * tokens_matched / max(1, tokens_total), 1),
            "rows_with_all_matched": sum(1 for x in kept_rows if not x["unmapped_tokens"]),
            "rows_with_any_unmapped": sum(1 for x in kept_rows if x["unmapped_tokens"]),
            "combo_rows": sum(1 for x in kept_rows if x["is_combo"]),
            "unmatched_distinct": len(unmatched),
            "unmatched_top": unmatched.most_common(30),
        },
        "forms": {"form_base": dict(form_counter), "form_raw_top": form_raw_counter.most_common(20),
                  "release": dict(release_counter)},
        "status": dict(status_counter),
        "strength": dict(strength_conf),
        "written_csv": str(out_path.relative_to(ROOT)),
    })
    # 默认样本 → stats.json；其它输出（全量/另选样本）→ <out Stem>-stats.json，互不覆盖
    default_out = out_path == OUT_CSV
    stem = "stats" if default_out else f"{out_path.stem}-stats"
    stats_path = WORK / f"{stem}.json"
    unmatched_path = WORK / ("unmatched_tokens.csv" if default_out
                             else f"{out_path.stem}-unmatched.csv")
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(unmatched_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["token", "count"])
        w.writerows(unmatched.most_common())
    form_map_path = WORK / ("form_map_draft.json" if default_out
                            else f"{out_path.stem}-forms.json")
    with open(form_map_path, "w", encoding="utf-8") as f:
        json.dump({"form_base": dict(form_counter),
                   "form_raw_top": form_raw_counter.most_common(50),
                   "release": dict(release_counter)}, f, ensure_ascii=False, indent=1)

    print(f"\nDRY RUN（未写 DB）")
    print(f"  扫描 {stats['scanned']:,} 行；产品类候选 {stats['eligible_seen']:,}；"
          f"输出 {len(kept_rows):,} 张证 → {out_path.relative_to(ROOT)}")
    print(f"  拒绝：{dict(stats['reject'])}")
    print(f"  成分 token 覆盖：{tokens_matched}/{tokens_total} "
          f"({stats['components']['token_coverage_pct']}%)；"
          f"未匹配 distinct {len(unmatched)}；多成分 {stats['components']['combo_rows']} 行")
    print(f"  剂型 base：{dict(form_counter)}；release：{dict(release_counter)}")
    print(f"  规格置信度：{dict(strength_conf)}")
    print(f"  统计：{(stats_path).relative_to(ROOT)}；"
          f"未匹配清单：{(unmatched_path).relative_to(ROOT)}")
    print("下一步：1) db/schema.sql + db/init_db.py 加 country 'TW' 迁移；"
          "2) 补未匹配 token 别名表；3) 写 product/name/component 插入。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
