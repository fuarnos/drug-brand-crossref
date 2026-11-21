# -*- coding: utf-8 -*-
"""韩国 KR（HIRA 약가마스터，data.go.kr 文件数据）→ SQLite 计划 / 入库。

许可（先看这一页）
------------------
data.go.kr 数据集 **15067462**（약가마스터_의약품표준코드）+ **15067461**（약가마스터_의약품주성분）
都标 **공공저작물 : 출처표시 (제1유형 / KOGL Type 1)**：可商用、可演绎，**须标明出处**。
页面明示「파일데이터는 로그인 없이 다운로드를 통해 이용하실 수 있습니다」——匿名可下，免账号。
评估与证据：`reports/2026-11-22-kr-license-assessment.md`（data-scout，2026-11-22）。
本站义务：署名 + 许可链接 + 数据基准日 + 标明本站已归一化；不转载说明书正文、不存价格、不做剂量换算。

**口径（页面文案必须按这个写，本脚本不写文案）**
--------------------------------------------------
- HIRA 약가마스터 是**医保药价清单（급여 목록）**，类似日本薬価基準；**不是**「韩国注册库全量」，
  也不是「全部上市/获批药品」。
- `취소일자` **只表示「不在药价表内」**，**不等于批文撤销**：本脚本里在表 → `status='active'`
  （note 写「HIRA 药价表在册」），有真实취소일자 → `status='unknown'`（note 写「不在表内 ≠ 撤销」），
  `status_date` 一律不写（避免被读成「撤销日」）。
- **无 허가번호（审批号）**：文件的 `품목기준코드` 是 MFDS 品目码（97,356 个唯一），本脚本存进
  `approval_id` 并在 note / `source.notes` 里写清「品目码，非 허가번호」；**没有在售状态字段**。
- **成分覆盖只有 52.0% 品目**（西药 63.7%）：`일반명코드` join 不上的品目**如实留空并计数**，不猜。

数据源与结构
------------
| 文件 | 行数 | 大小 | 结构 |
|---|---|---|---|
| `hira_yakga_stdcode_20260831.csv`（15067462，CP949，22 列） | 309,889 | 55,741,167 B | 一行 = 一个 **표준코드（包装条码）**：상품명 / 업체명 / 약품규격 / 제품총수량 / 제형구분（单位标签）/ 포장형태 / 품목기준코드 / 취소일자 / ATC / 일반명코드(성분명코드) |
| `hira_yakga_ingredient_20261105.csv`（15067461，CP949，8 列） | 60,750 | 3,836,693 B | 一行 = 某个 **일반명코드（配方码）** 里的一个成分：일반명 / 함량 + 단위 / 제형 / 투여 |

关键实测（2026-11-22 快照）：
- 品目 `품목기준코드` **97,356**（唯一）；商品名 **109,231** 种（9,634 个品目有多种写法）；
- `일반명코드` 是**配方码**（一个码对应 1–N 个成分行，复方同一码多行），不是单成分码；
- join：行级 137,567/309,889 = 44.4%；**品目级 50,595/97,356 = 52.0%**；
- 70 个配方码在成分表里找不到（128 行），如实计数；
- `취소일자`：真实注销 32,270 品目；9999-*/8999-* 是占位值（151 品目，视为在表）；
- 品目级多值：업체명 6,979（公司更名/合并）、剂型 28、途径 8；`전문일반구분` 与 ATC 品目内无冲突。

建模（一行 product = 一个品目）
-------------------------------
`품목기준코드` 是本站 L2 的「国家 × 剂型 × 规格 × 活性成分」单位：品目 = 一个品牌×规格，
其下多个 `표준코드` 是不同包装条码。所以：
- `product_id = KR-<품목기준코드>`（97,356 行；`approval_id` 同值，见上）；
- `product_name`：该品目所有 한글상품명 写法（trade，主名取出现最多的一种）；
- `pack`：该品目所有包装行的「약품규격 + 数量/单位标签 + 容器」去重后用 ` · ` 连接（截断 600 字符）；
- `dosage_form`：成分表 `제형`（结构化剂型，仅在 52% 品目可得）；`form_base` / `release` 由韩文剂型映射；
- `route`：成分表 `투여`（내복/주사/외용，多值取多数并计数）；
- `mah`：`업체명`（多值取多数，计数）；`category`：`전문일반구분`；
- `strength`：成分行 `함량 × 단위` 原样存（不换算）；复合单位（如 `mg(0.3mg/mL)`）原样保留并计数；
- ATC：品目级 `국제표준코드(ATC코드)`，只给**单一成分**且 7 位完整码时回填 `substance.atc`（空值才填）。

CLI
---
    python etl/ingest_kr.py --fetch          # 校验/补下两个 CSV + 写 data/raw/kr/fetch_meta.json
    python etl/ingest_kr.py --dry-run        # 解析 + 计划 + 统计（只读开库，不写）
    python etl/ingest_kr.py --self-check     # 离线断言（映射/状态/包装/名字，不联网不读库）
    python etl/ingest_kr.py --apply --db .tmp/kr_dryrun.db             # 干跑库演练
    python etl/ingest_kr.py --apply --allow-real --db data/drugs.db    # 写库窗口（Lead 开放后）

写库窗口前必须备份 `data/drugs.db`；同一时间只有本脚本可以写库。`--apply` 先 `require_country('KR')`
（v0.11.3 起枚举已含 KR，无需重建表）。重跑幂等：先删本 source 的 KR 行再写。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "etl" / "markets"))

from ingest_ema_medicines import _variant_resolver  # noqa: E402
from ingest_no import INN_ALIAS, name_candidates, norm_key, salt_base  # noqa: E402
from ingest_openfda_ndc import slug  # noqa: E402
from normalize_name import normalize  # noqa: E402
import _ingest_common as common  # noqa: E402

CODE = "KR"
SOURCE_ID = "hira_kr_medprice"
DATASET_STD = "https://www.data.go.kr/data/15067462/fileData.do"
DATASET_ING = "https://www.data.go.kr/data/15067461/fileData.do"
LICENSE_NAME = "공공누리 제1유형 (KOGL Type 1)"
LICENSE_URL = "https://www.kogl.or.kr/info/licenseType1.do"
UA = ("drug-brand-crossref/0.2 (public-data research; +https://drugcrossref.com/; "
      "HIRA medprice ingest, one download per DB window)")

RAW = ROOT / "data" / "raw" / "kr"
SNAPSHOT_SUBDIR = "20261122"          # data-scout 2026-11-22 的落盘目录（复用，不重复下载）
STD_NAME = "hira_yakga_stdcode_20260831.csv"
ING_NAME = "hira_yakga_ingredient_20261105.csv"
DATA_AS_OF = "2026-08-31"             # 标准码文件基准日（파일명 …20260831）
ING_DATA_AS_OF = "2026-11-05"         # 成分文件（연간）发布日期
RETRIEVED_AT = "2026-11-22"           # 北京时间抓取日（data-scout 落盘 2026-11-21 本地 / 11-22 北京）
FETCH_META = RAW / "fetch_meta.json"
WORK = ROOT / ".tmp" / "kr-ingest"
DB = ROOT / "data" / "drugs.db"
REAL_DB = DB
# 回滚清单 ~28 MB（97,356 个 product_id + 106k name_key + 109k name_variant），
# 超过 data/sources 的「小快照」口径 → 放 data/raw/kr/（gitignored，不入库）。
MANIFEST_DIR = RAW
STD_DOWNLOAD = ("https://www.data.go.kr/cmm/cmm/fileDownload.do"
                "?atchFileId=FILE_000000007666876&fileDetailSn=1")
ING_DOWNLOAD = ("https://www.data.go.kr/cmm/cmm/fileDownload.do"
                "?atchFileId=FILE_000000007759104&fileDetailSn=1")
ENCODING = "cp949"                    # 实测：UTF-8 解码会出替换字符

SOURCE_META = {
    "name": "HIRA 약가마스터 (의약품표준코드 + 의약품주성분) · data.go.kr 15067462/15067461",
    "url": f"{DATASET_STD} · {DATASET_ING}",
    "license": LICENSE_NAME,
    "license_url": LICENSE_URL,
    "data_as_of_note": f"표준코드 {DATA_AS_OF}（분기）/ 주성분 {ING_DATA_AS_OF}（연간）",
    "notes": ("医保药价清单（급여 약가표），不是注册库全量；취소일자 = 不在药价表内 ≠ 批文撤销；"
              "无 허가번호（approval_id 存 품목기준코드 = MFDS 品目码）；"
              "成分码覆盖 52.0% 品目，未映射留空并计数；本站已归一化"),
}

RE_NUM = re.compile(r"^\d+(?:\.\d+)?$")
RE_ATC5 = re.compile(r"^[A-Z]\d{2}[A-Z]{2}\d{2}$")
RE_SENTINEL = re.compile(r"^(9999|8999)")
RE_RATIO_UNIT = re.compile(
    r"^(mg|mcg|g|IU|unit|U)\s*/\s*(ml|mL|L|l|g)$", re.I)

# ---------------------------------------------------------------------------
# 单位：只归一「整串等于简单单位」的行；带括号/斜杠的复合单位原样保留（不换算、不猜）
# ---------------------------------------------------------------------------
UNIT_MAP = {
    "mg": "mg", "g": "g", "kg": "kg",
    "㎍": "mcg", "μg": "mcg", "ug": "mcg", "mcg": "mcg",
    "ml": "mL", "mL": "mL", "ML": "mL", "l": "L", "L": "L", "ℓ": "L",
    "I.U": "IU", "IU": "IU", "iu": "IU", "I.u": "IU",
    "KI.U": "kIU", "KIU": "kIU", "kiu": "kIU", "ku": "kIU",
    "MI.U": "MIU", "MU": "MIU", "MU/ml": "MIU/mL",
    "%": "%", "％": "%", "w/w％": "%w/w",
    "U": "unit", "unit": "unit", "Unit": "unit",
    "mCi": "mCi", "μCi": "µCi", "MBq": "MBq", "GBq": "GBq",
    "PFU": "PFU", "CFU": "CFU", "cells": "cells", "Cells": "cells",
    "단위": "unit", "개": "unit",
}
COMPOSITE_RE = re.compile(r"[()/]")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fold_kr(text: str) -> str:
    """韩文/英文统一小写 + 去拉丁重音 + 标点折空格（韩文音节保留，不拆成字母）。"""
    s = unicodedata.normalize("NFC", text or "").casefold()
    out: list[str] = []
    for ch in s:
        if "\uac00" <= ch <= "\ud7a3":          # 韩文音节：原样保留
            out.append(ch)
            continue
        out.append("".join(c for c in unicodedata.normalize("NFKD", ch)
                           if not unicodedata.combining(c)))
    s = "".join(out)
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z\uac00-\ud7a3]+", " ", s)).strip()


def unit_of_kr(raw: str | None) -> tuple[str | None, str]:
    """(规范单位, 规则)。简单单位归一；复合单位（含括号/斜杠）原样保留并标 composite。"""
    if raw is None or not str(raw).strip():
        return None, "empty"
    s = str(raw).strip()
    if s in UNIT_MAP:
        return UNIT_MAP[s], "exact"
    m = RE_RATIO_UNIT.match(s)
    if m:
        num = unit_of_kr(m.group(1))[0]
        den = "mL" if m.group(2).lower() == "ml" else (
            "L" if m.group(2).lower() == "l" else m.group(2).lower())
        if m.group(2).lower() == "g":
            den = "g"
        return f"{num}/{den}", "ratio"
    if COMPOSITE_RE.search(s):
        return s, "composite"
    low = s.lower()
    if low in UNIT_MAP:
        return UNIT_MAP[low], "exact"
    return s, "keep"


def strength_of(raw: str | None) -> float | None:
    """`함량` → float（原文是整数/小数；解析不了返回 None，不改写）。"""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 剂型（成分表 `제형`，韩文）→ form_base / release
# ---------------------------------------------------------------------------
# 只映射到站内既有 form_base；命不中落 other（不把韩文原文塞进 form_base）。
FORM_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tablet", ("정제", "저작정", "설하정", "구강정", "트로키", "확산정", "속붕정", "구강붕해정")),
    ("capsule", ("캡슐제",)),
    ("injection", ("주사제", "관류액")),
    ("inhalation", ("흡입제", "분무제", "에어로솔")),
    ("ophthalmic", ("점안제", "안연고")),
    ("suppository", ("좌제",)),
    ("implant", ("이식제",)),
    ("kit", ("검사용",)),
    ("topical", ("크림제", "겔제", "연고제", "카타플라스마", "첩부제", "경고제",
                 "로션제", "패취제", "페이스트제", "리니멘트제", "포말", "스폰지")),
    ("powder", ("과립제", "산제")),
    ("liquid", ("액제", "시럽제", "현탁액", "틴크제", "엘릭서제", "유제", "연조엑스")),
    ("pill", ("환제",)),
)
RELEASE_RULES = (("장용", "DR"), ("서방", "ER"))


def form_base_kr(form: str) -> str:
    f = (form or "").strip()
    if not f:
        return "unknown"
    for base, keys in FORM_RULES:
        if any(k in f for k in keys):
            return base
    return "other"


def release_kr(forms: list[str]) -> str:
    joined = " ".join(forms or [])
    for key, value in RELEASE_RULES:
        if key in joined:
            return value
    return "none"


ROUTE_MAP = {"내복": "oral", "주사": "injection", "외용": "topical"}


def route_kr(raw: str | None) -> str | None:
    if not raw:
        return None
    return ROUTE_MAP.get(str(raw).strip())


# ---------------------------------------------------------------------------
# 抓取（复用 data-scout 快照；缺失才补下）
# ---------------------------------------------------------------------------
def _locate(name: str) -> Path | None:
    for cand in (RAW / name, RAW / SNAPSHOT_SUBDIR / name):
        if cand.exists() and cand.stat().st_size > 0:
            return cand
    return None


def _download(url: str, dest: Path) -> None:
    req = Request(url, headers={"User-Agent": UA})
    t0 = time.time()
    with urlopen(req, timeout=600) as resp:
        body = resp.read()
        status, headers = resp.status, resp.headers
    tmp = dest.with_suffix(dest.suffix + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(body)
    tmp.replace(dest)
    print(f"  下载 {dest.name}: {len(body):,} B HTTP {status} ({time.time() - t0:.1f}s)")


def _csv_rows(path: Path) -> int:
    with path.open(encoding=ENCODING, newline="") as f:
        return sum(1 for _ in csv.reader(f)) - 1


def fetch(force: bool = False) -> dict:
    """校验/补下两个 CSV → 写 fetch_meta.json（复用 data-scout 已下载快照，不重复抓）。"""
    RAW.mkdir(parents=True, exist_ok=True)
    items = [(STD_NAME, STD_DOWNLOAD, DATASET_STD), (ING_NAME, ING_DOWNLOAD, DATASET_ING)]
    fetched = []
    for name, url, page in items:
        path = _locate(name)
        reused = path is not None and not force
        if not reused:
            path = RAW / name
            print(f"  快照缺失（或 --force），重新下载 {name}")
            _download(url, path)
        assert path is not None
        rows = _csv_rows(path)
        fetched.append({
            "name": name,
            "path": path.relative_to(ROOT).as_posix(),
            "dataset_page": page,
            "download_url": url,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "rows": rows,
            "encoding": ENCODING,
            "reused_data_scout_snapshot": reused,
        })
        print(f"  {name}: {path.relative_to(ROOT)} {fetched[-1]['bytes']:,} B / "
              f"{rows:,} 行 sha256={fetched[-1]['sha256'][:16]}…"
              f"{'（复用 scout 快照）' if reused else ''}")
    meta = {
        "source_id": SOURCE_ID,
        "license": LICENSE_NAME,
        "license_url": LICENSE_URL,
        "data_as_of": {"stdcode": DATA_AS_OF, "ingredient": ING_DATA_AS_OF},
        "retrieved_at_beijing": RETRIEVED_AT,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ua": UA,
        "note": "data.go.kr 文件数据官方明示免登录；一个写库窗口只下一次（复用 scout 2026-11-22 落盘）",
        "files": fetched,
    }
    FETCH_META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  fetch_meta → {FETCH_META.relative_to(ROOT)}")
    return meta


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def _std_path() -> Path:
    path = _locate(STD_NAME)
    if not path:
        raise SystemExit(f"没有快照：{RAW / STD_NAME}（先跑 python etl/ingest_kr.py --fetch）")
    return path


def _ing_path() -> Path:
    path = _locate(ING_NAME)
    if not path:
        raise SystemExit(f"没有快照：{RAW / ING_NAME}（先跑 python etl/ingest_kr.py --fetch）")
    return path


def load_ingredients(path: Path | None = None) -> dict[str, list[dict]]:
    """配方码 → 成分行列表（一行 = 一个成分：일반명 / 함량 / 단위 / 제형 / 투여）。"""
    out: dict[str, list[dict]] = defaultdict(list)
    with (path or _ing_path()).open(encoding=ENCODING, newline="") as f:
        for row in csv.DictReader(f):
            code = (row.get("일반명코드") or "").strip()
            if not code:
                continue
            out[code].append({
                "code": code,
                "name": (row.get("일반명") or "").strip(),
                "amount": (row.get("함량") or "").strip(),
                "unit": (row.get("단위") or "").strip(),
                "form": (row.get("제형") or "").strip(),
                "route": (row.get("투여") or "").strip(),
            })
    return out


def load_items(ingredients: dict[str, list[dict]] | None = None,
               path: Path | None = None) -> dict[str, dict]:
    """품목기준코드 → 品目聚合（名字/包装/状态/配方码/剂型/途径/MAH/category/ATC）。

    一行 = 一个 표준코드 包装；品目内多行聚合成一个 product。
    """
    ingredients = ingredients if ingredients is not None else load_ingredients()
    items: dict[str, dict] = {}
    with (path or _std_path()).open(encoding=ENCODING, newline="") as f:
        for row in csv.DictReader(f):
            item_code = (row.get("품목기준코드") or "").strip()
            if not item_code:
                continue
            name = (row.get("한글상품명") or "").strip()
            cancel = (row.get("취소일자") or "").strip()
            rec = items.get(item_code)
            if rec is None:
                rec = items[item_code] = {
                    "item_code": item_code,
                    "names": [], "name_counts": Counter(),
                    "mahs": Counter(), "categories": Counter(), "atcs": Counter(),
                    "packs": [], "codes": [], "rows": 0,
                    "real_cancel": False, "cancel_dates": [], "sentinel_cancel": False,
                    "specs": Counter(),
                }
            rec["rows"] += 1
            if name:
                rec["name_counts"][name] += 1
                if name not in rec["names"]:
                    rec["names"].append(name)
            mah = (row.get("업체명") or "").strip()
            if mah:
                rec["mahs"][mah] += 1
            cat = (row.get("전문일반구분") or "").strip()
            if cat:
                rec["categories"][cat] += 1
            atc = (row.get("국제표준코드(ATC코드)") or "").strip()
            if atc:
                rec["atcs"][atc] += 1
            code = (row.get("일반명코드(성분명코드)") or "").strip()
            if code and code not in rec["codes"]:
                rec["codes"].append(code)
            spec = (row.get("약품규격") or "").strip()
            if spec and spec != "없음":
                rec["specs"][spec] += 1
            pack = pack_row(row)
            if pack and pack not in rec["packs"]:
                rec["packs"].append(pack)
            if cancel:
                if RE_SENTINEL.match(cancel):
                    rec["sentinel_cancel"] = True
                else:
                    rec["real_cancel"] = True
                rec["cancel_dates"].append(cancel)
    # 补剂型/途径（来自配方码 → 成分行）
    for rec in items.values():
        forms: list[str] = []
        routes: Counter = Counter()
        comps: list[dict] = []
        seen: set[tuple] = set()
        for code in rec["codes"]:
            for ing in ingredients.get(code, []):
                if ing["form"] and ing["form"] not in forms:
                    forms.append(ing["form"])
                if ing["route"]:
                    routes[ing["route"]] += 1
                key = (norm_key(ing["name"]), ing["amount"], ing["unit"])
                if key not in seen:
                    seen.add(key)
                    comps.append(ing)
        rec["forms"] = forms
        rec["routes"] = routes
        rec["components"] = comps
        rec["missing_codes"] = [c for c in rec["codes"] if c not in ingredients]
    return items


def pack_row(row: dict) -> str:
    """一行包装 → 「약품규격 + 数量/单位标签 + 容器」描述（空值不写，不臆造）。"""
    spec = (row.get("약품규격") or "").strip()
    part_spec = spec if spec and spec != "없음" else ""
    total = (row.get("제품총수량") or "").strip()
    unit = (row.get("제형구분") or "").strip()
    container = (row.get("포장형태") or "").strip()
    parts: list[str] = []
    if part_spec:
        parts.append(part_spec)
    if total and total != "0":
        if unit and unit != "기타":
            parts.append(f"{total}{unit}")
        else:
            parts.append(total)
    if container and container != "기타" and container != unit:
        parts.append(container)
    return " ".join(parts)


def item_status(rec: dict) -> tuple[str, str | None, str]:
    """(status, status_date, note)。취소일자 ≠ 批文撤销；status_date 一律不写。"""
    if rec["real_cancel"]:
        dates = sorted(d for d in rec["cancel_dates"] if not RE_SENTINEL.match(d))
        return ("unknown", None,
                f"不在 HIRA 급여药价表（취소일자 {dates[-1] if dates else '?'}）；"
                "≠ 批文撤销，也≠停售")
    if rec["sentinel_cancel"]:
        return ("active", None, "HIRA 药价表在册（취소일자 为 9999 占位值，视为在表）")
    return ("active", None, "HIRA 药价表在册（在表 ≠ 批文有效/在售）")


def item_product_id(item_code: str) -> str:
    return f"{CODE}-{item_code}"


def item_name(rec: dict) -> str:
    """主名：品目内出现次数最多的商品名；同票取首次出现。"""
    if not rec["name_counts"]:
        return ""
    best = max(rec["name_counts"].items(), key=lambda kv: (kv[1], -rec["names"].index(kv[0])))
    return best[0]


# ---------------------------------------------------------------------------
# 计划（只读库）
# ---------------------------------------------------------------------------
def db_substances(db: sqlite3.Connection) -> dict[str, str]:
    """norm_key(inn_en) → sid；同时登记「词序无关」的 sorted-token 键（同词多序同物质）。"""
    out: dict[str, str] = {}
    for sid, inn_en in db.execute("SELECT substance_id, inn_en FROM substance"):
        if not inn_en:
            continue
        key = norm_key(inn_en)
        out.setdefault(key, sid)
        sorted_key = " ".join(sorted(key.split()))
        if sorted_key and sorted_key != key:
            out.setdefault(sorted_key, sid)
    return out


def is_ascii(text: str) -> bool:
    return all(ord(ch) < 128 for ch in text)


# 立体化学/希腊字母写法：DB canonical 多为不带前缀的通用名；这两条是同物质的不同官方写法。
# 只收「在库内可复核」的显式映射（L-menthol 在库内是 levomenthol，S-amlodipine 是 levamlodipine）。
KR_ALIAS = {
    "l-menthol": "levomenthol",
    "s-amlodipine": "levamlodipine",
    "s amlodipine": "levamlodipine",
    "alpha lipoic acid": "lipoic acid",
    "alpha amylase": "amylase",
}
GREEK = {"γ": "gamma", "β": "beta", "α": "alpha", "μ": "micro"}
STEREO_PREFIX = re.compile(r"^(?:dl|rs|levo|dextro|l|d|s|r)\s*[-\s]?")
RE_SPACE = re.compile(r"\s+")
HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]")
RE_PAREN_NO = re.compile(r"\([^()]*\)")


def has_hangul(text: str) -> bool:
    return bool(HANGUL_RE.search(text or ""))


def looks_english(name: str) -> bool:
    """括号外没有韩文就算「英文/拉丁名」（`γ-oryzanol`、`pancreatin (장용부)` 都算）。

    韩文只在括号里时（製剂部位说明）按括号外名字对齐母体主档；整名韩文才走 Korean 分支。
    """
    outside = RE_PAREN_NO.sub(" ", name or "")
    return not has_hangul(outside)


def kr_name_variants(name: str) -> list[str]:
    """成分名 → 候选写法（希腊字母展开 / 反复去立体化学前缀）。"""
    out: list[str] = []
    raw = (name or "").strip()

    def add(value: str) -> None:
        value = RE_SPACE.sub(" ", value).strip()
        if value and value not in out:
            out.append(value)

    add(raw)
    greek = raw
    for src, dst in GREEK.items():
        greek = greek.replace(src, dst)
    add(greek)
    # `dl-methylephedrine` 需要连剥两层（dl → l → 无），最多 3 轮
    for _round in range(3):
        before = len(out)
        for value in list(out):
            low = value.casefold()
            m = STEREO_PREFIX.match(low)
            if m and m.end() < len(low):
                add(low[m.end():].lstrip("- "))
        if len(out) == before:
            break
    return out


def kr_candidates(name: str) -> list[tuple[str, str]]:
    """成分名 → (候选键, 命中方式)：先显式别名，再逐写法走 ingest_no 的通用规则，最后词序。"""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(key: str, kind: str) -> None:
        key = RE_SPACE.sub(" ", key).strip()
        if key and key not in seen:
            seen.add(key)
            out.append((key, kind))

    for variant in kr_name_variants(name):
        low = variant.casefold().strip()
        if low in KR_ALIAS:
            add(norm_key(KR_ALIAS[low]), "kr_alias")
        for key, kind in name_candidates(variant):
            add(key, kind)
        add(" ".join(sorted(norm_key(variant).split())), "tokens")
    return out


def new_substance_id(name: str) -> str:
    """英文名用 slug；含非 ASCII（韩文/希腊字母）→ `kr-<sha1 前 10>`，避免 slug 丢字撞名。"""
    if is_ascii(name):
        base = slug(name)[:60]
        if base and base != "unknown":
            return base
    return "kr-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]


def resolve_substance(name: str, index: dict[str, str]) -> dict:
    """成分名（英/韩）→ {method, sid 或 new_key, is_ascii, lang}。"""
    text = (name or "").strip()
    if not text:
        return {"method": "empty", "sid": None, "name": text}
    if looks_english(text):
        for cand, kind in kr_candidates(text):
            sid = index.get(cand)
            if sid:
                return {"method": kind, "sid": sid, "name": text, "lang": "en"}
        return {"method": "new-en", "sid": None, "new_key": norm_key(text), "name": text,
                "lang": "en"}
    return {"method": "new-ko", "sid": None, "new_key": norm_key(text), "name": text,
            "lang": "other"}


def ensure_substance(db: sqlite3.Connection, inn: str, lang: str) -> tuple[str, str]:
    """建新 substance + base variant（source 可核；韩文名 name_lang='other'）。"""
    sid = new_substance_id(inn)
    row = db.execute("SELECT substance_id FROM substance WHERE substance_id=? OR inn_en=?",
                     (sid, inn)).fetchone()
    if row:
        sid = row[0]
    else:
        n = 1
        while db.execute("SELECT 1 FROM substance WHERE substance_id=?", (sid,)).fetchone():
            n += 1
            sid = f"{new_substance_id(inn)}-{n}"
        db.execute(
            "INSERT INTO substance (substance_id, inn_en, source_id, method, confidence,"
            " decided_at, name_lang) VALUES (?,?,?,'imported','high',?,?)",
            (sid, inn, SOURCE_ID, RETRIEVED_AT, lang))
    return sid, ensure_base_variant(db, sid)


def ensure_base_variant(db: sqlite3.Connection, sid: str) -> str:
    """给已有 substance 补一个 base variant（不猜盐型；只补缺失，不覆盖既有）。"""
    row = db.execute("SELECT variant_id FROM variant WHERE substance_id=?"
                     " ORDER BY variant_id LIMIT 1", (sid,)).fetchone()
    if row:
        return row[0]
    vid = sid
    n = 1
    while db.execute("SELECT 1 FROM variant WHERE variant_id=?", (vid,)).fetchone():
        n += 1
        vid = f"{sid}-base{n}"
    db.execute(
        "INSERT INTO variant (variant_id, substance_id, salt, hydrate, ester, base_fraction,"
        " interchange, interchange_note, salt_code, strength_basis)"
        " VALUES (?,?,'','','',1.0,'unknown',NULL,'','unknown')", (vid, sid))
    return vid


def build_plan(db: sqlite3.Connection, items: dict[str, dict],
               new_map: dict[str, list[str]] | None = None,
               new_variants: dict[str, str] | None = None,
               ingredients: dict[str, list[dict]] | None = None,
               limit: int = 0) -> dict:
    """品目 + 库内成分索引 → 待写产品/统计（只读，不写库）。"""
    new_map = new_map or {}
    new_variants = new_variants or {}
    index = db_substances(db)
    resolve_variant = _variant_resolver(db)
    stats: Counter = Counter()
    pending: dict[str, list[str]] = {}
    pending_variants: dict[str, int] = {}
    products: list[dict] = []

    item_list = list(items.values())
    if limit:
        item_list = item_list[:limit]
    for rec in item_list:
        item_code = rec["item_code"]
        name = item_name(rec)
        if not name:
            stats["skip_no_name"] += 1
            continue
        status, status_date, status_note = item_status(rec)
        stats[f"status_{status}"] += 1
        forms = rec["forms"]
        if forms:
            stats["form_present"] += 1
            if len(forms) > 1:
                stats["form_multi"] += 1
        dosage_form = " + ".join(forms) if forms else "unknown"
        form_base = form_base_kr(forms[0]) if forms else "unknown"
        if len(forms) > 1 and len({form_base_kr(f) for f in forms}) > 1:
            stats["form_base_conflict"] += 1
        route = None
        if rec["routes"]:
            route = route_kr(rec["routes"].most_common(1)[0][0])
            if len(rec["routes"]) > 1:
                stats["route_multi"] += 1
        mah = rec["mahs"].most_common(1)[0][0] if rec["mahs"] else None
        if len(rec["mahs"]) > 1:
            stats["mah_multi"] += 1
        category = rec["categories"].most_common(1)[0][0] if rec["categories"] else None
        atc = rec["atcs"].most_common(1)[0][0] if rec["atcs"] else ""
        pack = " · ".join(rec["packs"])
        if len(pack) > 600:
            pack = pack[:597].rstrip(" ·") + "…"

        # --- 成分 ---
        comps: list[dict] = []
        for ing in rec["components"]:
            res = resolve_substance(ing["name"], index)
            if res["method"] in ("empty",):
                stats["skip_empty_ingredient"] += 1
                continue
            if res["method"].startswith("new"):
                pending.setdefault(res["new_key"], [res["name"], res["lang"]])
                mapped = new_map.get(res["new_key"])
                if not mapped:
                    stats["pending_new_components"] += 1
                    continue
                vid = mapped[1]
                stats["method_" + res["method"].replace("-", "_")] += 1
            else:
                vid = resolve_variant(res["sid"], res["name"])
                if not vid:
                    # 少数 substance 行没有任何 variant（10 个 / 159 个成分）：
                    # apply 阶段补建 base variant（不猜盐型），plan 阶段先计数。
                    vid = new_variants.get(res["sid"])
                    if not vid:
                        pending_variants.setdefault(res["sid"], 0)
                        pending_variants[res["sid"]] += 1
                        stats["skip_pending_variant"] += 1
                        continue
                stats[f"method_{res['method']}"] += 1
            value = strength_of(ing["amount"])
            unit, rule = unit_of_kr(ing["unit"])
            stats[f"unit_{rule}"] += 1
            comps.append({"variant_id": vid, "strength_value": value, "strength_unit": unit,
                          "per_volume_value": None, "per_volume_unit": None,
                          "name": ing["name"], "sub_name": res["name"]})
        if not comps:
            stats["products_without_component"] += 1

        # --- 名字 ---
        # 只挂 상품명（trade，含品目内多写法）。**不挂 INN 名字**：KR 成分名大量带盐
        # （amikacin sulfate 等），而库内既有「母体 / 盐」两行 substance 已在别的市场
        # 挂了同名键；再挂会把 +8k 个同名键推成 severe（同名不同药）的假警示。
        # 跨市场对应走 substance 层；与 CZ / JP / FR 口径一致。
        names = [(raw, "trade", 1 if raw == name else 0) for raw in rec["names"]]

        notes = [status_note]
        if not rec["codes"]:
            notes.append("HIRA 无成分码（成分覆盖 52.0%，本品目未映射，留空不猜）")
        elif rec["missing_codes"]:
            notes.append(f"配方码 {len(rec['missing_codes'])} 个在成分表缺失")
        if len(rec["codes"]) > 1:
            notes.append(f"多配方码 {len(rec['codes'])} 个（成分按并集去重）")
        if len(forms) > 1:
            notes.append(f"多剂型 {len(forms)} 种")
        if rec["routes"] and len(rec["routes"]) > 1:
            notes.append(f"多途径 {len(rec['routes'])} 种")
        if len(rec["mahs"]) > 1:
            notes.append(f"업체명 多值 {len(rec['mahs'])} 个（取最多）")
        composite_units = sum(1 for ing in rec["components"]
                              if unit_of_kr(ing["unit"])[1] == "composite")
        if composite_units:
            notes.append(f"复合单位 {composite_units} 个原样保留（含括号浓度，未换算）")
        if category and category not in ("전문의약품", "일반의약품"):
            notes.append(f"전문일반구분: {category}")

        products.append({
            "product_id": item_product_id(item_code),
            "country": CODE,
            "dosage_form": dosage_form,
            "form_base": form_base,
            "route": route,
            "release": release_kr(forms),
            "pack": pack or None,
            "mah": mah,
            "approval_id": item_code,
            "category": category,
            "is_branded": 1,
            "status": status,
            "status_date": status_date,
            "source_id": SOURCE_ID,
            "source_url": DATASET_STD,
            "retrieved_at": "",
            "note": "; ".join(notes) or None,
            "names": names,
            "components": comps,
            "atc": atc if len({c["variant_id"] for c in comps}) == 1 else "",
            "item_code": item_code,
            "row_count": rec["rows"],
        })
        stats["products"] += 1
        stats["components"] += len(comps)
        stats["name_rows"] += len(names)
        if pack:
            stats["products_with_pack"] += 1
        if mah:
            stats["products_with_mah"] += 1
        if category:
            stats["products_with_category"] += 1
        if atc:
            stats["products_with_atc"] += 1
        if comps:
            stats["products_with_component"] += 1
            if any(c["strength_value"] is not None for c in comps):
                stats["products_with_strength"] += 1
            else:
                stats["products_strength_missing"] += 1
            if any(c["strength_unit"] for c in comps):
                stats["products_with_unit"] += 1

    stats["items_in_snapshot"] = len(items)
    stats["items_planned"] = len(products)
    stats["pending_new_substances"] = len(pending)
    return {"products": products, "stats": dict(stats), "pending_new": pending,
            "pending_variants": sorted(pending_variants)}


# ---------------------------------------------------------------------------
# 写库
# ---------------------------------------------------------------------------
def write_plan(db: sqlite3.Connection, plan: dict) -> dict:
    written: Counter = Counter()
    for p in plan["products"]:
        written["product"] += common.write_product(db, p)
        for raw, ntype, primary in p["names"]:
            for key, value in common.write_name(
                    db, p["product_id"], raw, ntype, primary, SOURCE_ID, normalize).items():
                written[key] += value
        for ord_, comp in enumerate(p["components"]):
            written["product_component"] += common.write_component(
                db, p["product_id"], ord_, comp["variant_id"],
                {"value": comp["strength_value"], "unit": comp["strength_unit"],
                 "per_volume_value": comp["per_volume_value"],
                 "per_volume_unit": comp["per_volume_unit"]})
        if p.get("atc") and RE_ATC5.match(p["atc"]):
            written["substance_atc"] += db.execute(
                "UPDATE substance SET atc=?, atc_name=COALESCE(NULLIF(atc_name,''), ?)"
                " WHERE substance_id=(SELECT v.substance_id FROM variant v"
                " WHERE v.variant_id=?) AND (atc IS NULL OR atc='')",
                (p["atc"], None, p["components"][0]["variant_id"])).rowcount
    return dict(written)


def _created_names(plan: dict, existing_keys: set[str],
                   existing_pairs: set[tuple[str, str]]) -> tuple[list[str], list[list[str]]]:
    keys: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for p in plan["products"]:
        for raw, _ntype, _primary in p["names"]:
            nm = normalize(raw)
            if not nm or not nm.norm:
                continue
            if nm.norm not in existing_keys:
                keys.add(nm.norm)
            if (nm.norm, raw) not in existing_pairs:
                pairs.add((nm.norm, raw))
    return sorted(keys), [list(x) for x in sorted(pairs)]


def _load_snapshot() -> tuple[dict[str, list[dict]], dict[str, dict]]:
    ingredients = load_ingredients()
    items = load_items(ingredients)
    return ingredients, items


def cmd_dry_run(args: argparse.Namespace) -> int:
    t0 = time.perf_counter()
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    ingredients, items = _load_snapshot()
    db = common.connect(db_path, write=False)
    try:
        first = build_plan(db, items, ingredients=ingredients)
        fake = {k: [f"sim-{i}", f"sim-{i}"] for i, k in enumerate(sorted(first["pending_new"]))}
        fake_vars = {sid: f"sim-var-{i}"
                     for i, sid in enumerate(first["pending_variants"])}
        plan = build_plan(db, items, fake, fake_vars, ingredients=ingredients)
        countries = db.execute("SELECT COUNT(*) FROM product WHERE country=?",
                               (CODE,)).fetchone()[0]
    finally:
        db.close()
    stats = plan["stats"]
    stats["pending_new_substances"] = len(first["pending_new"])
    stats["pending_variants"] = len(first["pending_variants"])
    forms = Counter(p["form_base"] for p in plan["products"])
    statuses = Counter(p["status"] for p in plan["products"])
    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / "kr_dry_run.json"
    out.write_text(json.dumps({"stats": stats, "form_base": dict(forms),
                               "statuses": dict(statuses),
                               "pending_new": first["pending_new"],
                               "pending_variants": first["pending_variants"]},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    comps = stats.get("components", 0)
    mapped = sum(v for k, v in stats.items() if k.startswith("method_")
                 and k not in ("method_new_en", "method_new_ko"))
    print("== 韩国 HIRA 약가마스터 干跑 ==")
    print(f"  상품명 rows={stats.get('name_rows', 0):,} / items={stats.get('items_in_snapshot', 0):,} "
          f"/ 计划产品 {stats.get('items_planned', 0):,} / 成分行（含含量）{comps:,}")
    if comps:
        print(f"  成分名对齐：既有主档 {mapped:,}/{comps:,} = {mapped / comps * 100:.1f}%；"
              f"新建 {stats.get('method_new_en', 0) + stats.get('method_new_ko', 0):,}"
              f"（英文 {stats.get('method_new_en', 0):,} / 韩文 {stats.get('method_new_ko', 0):,}）"
              f"；待建 substance {stats.get('pending_new_substances', 0):,}"
              f" / 待补 variant {stats.get('pending_variants', 0):,}")
    for key in ("status_active", "status_unknown", "products_with_component",
                "products_without_component", "products_with_strength",
                "products_strength_missing", "products_with_pack", "products_with_mah",
                "products_with_atc", "form_present", "form_multi", "mah_multi",
                "route_multi", "unit_exact", "unit_composite", "unit_keep", "unit_empty",
                "method_kr_alias", "method_tokens", "method_exact", "method_salt",
                "method_ion", "method_alias", "skip_pending_variant",
                "pending_new_components"):
        if stats.get(key):
            print(f"    {key:<26}{stats[key]:>10,}")
    print(f"  剂型 form_base：{dict(forms.most_common(8))}")
    print(f"  状态：{dict(statuses)}；明细 → {out.relative_to(ROOT)}"
          f"（{time.perf_counter() - t0:.1f}s）")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    common.guard_real(db_path, REAL_DB, "apply", args.allow_real)
    if not db_path.exists():
        raise SystemExit(f"库不存在：{db_path}（先复制一份副本演练）")
    manifest_path = args.manifest if args.manifest.is_absolute() else (ROOT / args.manifest)
    t0 = time.perf_counter()
    sha_before = common.sha256_file(db_path)
    ingredients, items = _load_snapshot()

    db = common.connect(db_path, write=False)
    try:
        common.require_country(db, CODE)
        before = common.table_counts(db, CODE, SOURCE_ID)
        existing_keys = {r[0] for r in db.execute("SELECT key_id FROM name_key")}
        existing_pairs = {(r[0], r[1]) for r in db.execute("SELECT key_id, raw FROM name_variant")}
        first = build_plan(db, items, ingredients=ingredients)
    finally:
        db.close()
    pending = first["pending_new"]
    pending_variants = first["pending_variants"]

    db = common.connect(db_path, write=True)
    created_substances: list[str] = []
    created_variants: list[str] = []
    new_map: dict[str, list[str]] = {}
    new_variants: dict[str, str] = {}
    try:
        db.execute("BEGIN IMMEDIATE")
        source_meta = dict(SOURCE_META, retrieved_at=RETRIEVED_AT, data_as_of=DATA_AS_OF)
        source_existed, source_before = common.insert_source(db, SOURCE_ID, source_meta)
        removed = db.execute("DELETE FROM product WHERE country=? AND source_id=?",
                             (CODE, SOURCE_ID)).rowcount
        for key, (name, lang) in sorted(pending.items()):
            sid, vid = ensure_substance(db, name, lang)
            new_map[key] = [sid, vid]
            created_substances.append(sid)
        for sid in pending_variants:
            vid = ensure_base_variant(db, sid)
            new_variants[sid] = vid
            created_variants.append(vid)
        plan = build_plan(db, items, new_map, new_variants, ingredients=ingredients)
        for p in plan["products"]:
            p["retrieved_at"] = RETRIEVED_AT
        written = write_plan(db, plan)
        common.write_ingest_run(
            db, f"{SOURCE_ID}-{RETRIEVED_AT}", SOURCE_ID, RETRIEVED_AT,
            plan["stats"].get("items_in_snapshot", 0), plan["stats"].get("products", 0),
            {"country": CODE, "layer": "country", "source_id": SOURCE_ID,
             "data_as_of": DATA_AS_OF, "ingredient_data_as_of": ING_DATA_AS_OF,
             "items": plan["stats"].get("items_in_snapshot"),
             "components": written.get("product_component", 0),
             "new_substances": len(created_substances),
             "note": "HIRA 급여 약가마스터；취소일자≠批文撤销；无 허가번호；成分覆盖 52%"})
        db.commit()
        after = common.table_counts(db, CODE, SOURCE_ID)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    created_keys, created_pairs = _created_names(plan, existing_keys, existing_pairs)
    std = _std_path()
    ing = _ing_path()
    manifest = {
        "tool": "etl/ingest_kr.py",
        "db": str(db_path),
        "country": CODE,
        "source_id": SOURCE_ID,
        "run_id": f"{SOURCE_ID}-{RETRIEVED_AT}",
        "created_at": common.now(),
        "data_as_of": DATA_AS_OF,
        "snapshot": {
            "stdcode": {"path": std.relative_to(ROOT).as_posix(), "bytes": std.stat().st_size,
                        "sha256": sha256_file(std), "rows": _csv_rows(std),
                        "data_as_of": DATA_AS_OF},
            "ingredient": {"path": ing.relative_to(ROOT).as_posix(), "bytes": ing.stat().st_size,
                           "sha256": sha256_file(ing), "rows": _csv_rows(ing),
                           "data_as_of": ING_DATA_AS_OF},
        },
        "db_sha256_before": sha_before,
        "db_sha256_after": common.sha256_file(db_path),
        "product_ids": [p["product_id"] for p in plan["products"]],
        "created_name_keys": created_keys,
        "created_name_variants": created_pairs,
        "created_substances": created_substances,
        "created_variants_for_existing_substances": created_variants,
        "source_existed": source_existed,
        "source_before": source_before,
        "counts_before": before,
        "counts_after": after,
        "counts_planned": plan["stats"],
        "counts_first_pass": first["stats"],
        "written": written,
        "removed_products_before_write": removed,
        "rollback_hint": (
            "python etl/ingest_kr.py --rollback --allow-real --db <同一个库> --manifest <本文件>；"
            "或从 data/backups/drugs-*-kr.db 恢复。校验：SELECT COUNT(*) FROM product"
            " WHERE country='KR' AND source_id='hira_kr_medprice' 应为 0。"),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== KR（HIRA 약가마스터）写入完成 ===")
    print(json.dumps({"written": written, "counts_before": before, "counts_after": after},
                     ensure_ascii=False, indent=1))
    print(f"  数据截止 {DATA_AS_OF}（成分文件 {ING_DATA_AS_OF}）· 新成分 {len(created_substances):,}"
          f" · 旧 KR 行删除 {removed}")
    print(f"  撤销清单 {manifest_path.relative_to(ROOT)}")
    print(f"  db sha256 {sha_before[:16]}… → {manifest['db_sha256_after'][:16]}… · "
          f"耗时 {time.perf_counter() - t0:.1f}s")
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    common.guard_real(db_path, REAL_DB, "rollback", args.allow_real)
    manifest_path = args.manifest if args.manifest.is_absolute() else (ROOT / args.manifest)
    if not manifest_path.exists():
        raise SystemExit(f"找不到撤销清单：{manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    removed, after, diff = common.rollback(db_path, manifest, CODE, SOURCE_ID)
    nonzero = {k: v for k, v in diff.items() if v}
    print("=== KR（HIRA）回滚完成 ===")
    print(json.dumps({"removed": removed, "counts_after": after,
                      "diff_vs_counts_before": diff}, ensure_ascii=False, indent=2))
    if nonzero:
        print(f"  !! 与写前计数不一致：{nonzero}")
        return 1
    print("  逐表差异 0（已回到写前基线）")
    return 0


# ---------------------------------------------------------------------------
# 自检（离线）
# ---------------------------------------------------------------------------
def self_check() -> int:
    checks: list[tuple[str, object, object]] = [
        ("fold_kr", fold_kr("아작탐주사500밀리그람(아즈트레오남)"),
         "아작탐주사500밀리그람 아즈트레오남"),
        ("unit mg", unit_of_kr("mg")[0], "mg"),
        ("unit ㎍", unit_of_kr("㎍")[0], "mcg"),
        ("unit μg", unit_of_kr("μg")[0], "mcg"),
        ("unit I.U", unit_of_kr("I.U")[0], "IU"),
        ("unit KI.U", unit_of_kr("KI.U")[0], "kIU"),
        ("unit composite kept", unit_of_kr("mg(0.3mg/mL)"), ("mg(0.3mg/mL)", "composite")),
        ("unit empty", unit_of_kr(""), (None, "empty")),
        ("strength dot", strength_of("0.5"), 0.5),
        ("strength junk", strength_of("n/a"), None),
        ("form 정제", form_base_kr("정제,저작정"), "tablet"),
        ("form 주사제", form_base_kr("주사제"), "injection"),
        ("form 캡슐", form_base_kr("경질캡슐제"), "capsule"),
        ("form 점안", form_base_kr("점안제(점안액)"), "ophthalmic"),
        ("form 크림", form_base_kr("크림제,겔제,젤리"), "topical"),
        ("form empty", form_base_kr(""), "unknown"),
        ("release 서방", release_kr(["서방형정제"]), "ER"),
        ("release 장용", release_kr(["장용정제"]), "DR"),
        ("release none", release_kr(["정제,저작정"]), "none"),
        ("route 내복", route_kr("내복"), "oral"),
        ("route 주사", route_kr("주사"), "injection"),
        ("route 외용", route_kr("외용"), "topical"),
        ("route 기타", route_kr("기타"), None),
        ("status 在表", item_status({"real_cancel": False, "sentinel_cancel": False,
                                     "cancel_dates": []})[0], "active"),
        ("status 占位", item_status({"real_cancel": False, "sentinel_cancel": True,
                                     "cancel_dates": ["9999-01-01"]})[0], "active"),
        ("status 不在表", item_status({"real_cancel": True, "sentinel_cancel": False,
                                       "cancel_dates": ["2020-01-01"]}), ("unknown", None,
                                       "不在 HIRA 급여药价表（취소일자 2020-01-01）；≠ 批文撤销，也≠停售")),
        ("pack tablet", pack_row({"약품규격": "250밀리그램", "제품총수량": "16",
                                  "제형구분": "정", "포장형태": "PTP"}),
         "250밀리그램 16정 PTP"),
        ("pack herbal", pack_row({"약품규격": "500그램", "제품총수량": "1",
                                  "제형구분": "기타", "포장형태": "기타"}), "500그램 1"),
        ("pack none", pack_row({"약품규격": "없음", "제품총수량": "0",
                                "제형구분": "", "포장형태": ""}), ""),
        ("product id", item_product_id("199905709"), "KR-199905709"),
        ("substance id korean", new_substance_id("아세트아미노펜").startswith("kr-"), True),
        ("substance id english", new_substance_id("Paracetamol"), "paracetamol"),
    ]
    failed = 0
    for label, got, want in checks:
        ok = got == want
        failed += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}")
    print(f"self-check：{len(checks) - failed}/{len(checks)} 通过")
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="韩国 HIRA 약가마스터 → data/drugs.db")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--fetch", action="store_true", help="校验/补下两个 CSV（幂等）")
    mode.add_argument("--dry-run", action="store_true", help="解析 + 计划，不写库（默认）")
    mode.add_argument("--apply", action="store_true", help="事务写库（真实库需 --allow-real）")
    mode.add_argument("--rollback", action="store_true", help="按 manifest 回滚")
    mode.add_argument("--self-check", action="store_true", help="离线断言，不联网不读库")
    ap.add_argument("--force", action="store_true", help="--fetch 时重下")
    ap.add_argument("--allow-real", action="store_true",
                    help="允许对 data/drugs.db 写入/回滚（写库窗口；先备份）")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--manifest", type=Path,
                    default=MANIFEST_DIR / f"kr_ingest_manifest_{RETRIEVED_AT.replace('-', '')}.json")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个品目（试跑用）")
    args = ap.parse_args(argv)

    if args.self_check:
        return self_check()
    if args.fetch:
        fetch(force=args.force)
        return 0
    if args.apply:
        return cmd_apply(args)
    if args.rollback:
        return cmd_rollback(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
