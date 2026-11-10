# -*- coding: utf-8 -*-
"""荷兰 CBG-MEB 药品信息库（GIP `metadata.csv`）ETL 骨架 —— **只做干跑，不写库**。

许可状态（这一页最重要）
------------------------
CBG-MEB 的 GIP 数据文件**没有获得再发布许可**：`data.overheid.nl` 的 DCAT 记录把许可标为
`licentieonbekend`（许可未知），国家目录的许可口径页把「许可未知」定义为
「geen hergebruik licentie / Open Data? Nee」。评估结论见
`reports/2026-11-11-nl-license-assessment.md`、`docs/许可清单.md` §2.10。

因此本脚本**故意不提供 `--apply` / `--rollback`**：只有 `--fetch`（抓缓存）、`--dry-run`
（读缓存 → 解析 → 统计，只读开库）和 `--self-check`（离线断言）。任何写库路径都要等
书面许可（或数据方给出明确开放许可）落地后另开任务，届时再按 `etl/ingest_eu.py` 的
`--apply` / `--rollback` / `--manifest` 三段式补上写库与撤销清单。

数据源
------
`https://www.geneesmiddeleninformatiebank.nl/metadata.csv`
  - 约 16.4 MB、UTF-8、**竖线 `|` 分隔**、27 列、首行表头；每周更新，但**滞后两周**。
  - 一条 `REGISTRATIENUMMER` 可以对应多行（同一注册号下不同规格/剂型/包装，实测最多 31 行），
    所以**注册号不是主键**——产品身份仍是「名称 × 剂型 × 规格 × 活性成分」。
  - `SOORT`：`RVG`（ nationale 注册）/ `RVH`（handelsvergunning）/ 空（空的那 3,831 行
    全部是 `EU/…` 注册号，即欧盟集中审批产品，与本库 `region='EU'` 那一层重叠）。
  - `POTENTIE` 看起来像规格列，实测 **19,116/19,569 行为空，剩余 453 行全是顺势疗法稀释度**
    （`4 DH t/m 60 DH#2 CH t/m 200 CH#…`），**不是数值规格**；真正的规格写在 `PRODUCTNAAM`
    里（`Cisordinol 10 mg, filmomhulde tabletten`、`Kenacort-A 40 mg/ml`）。
  - `WERKZAMESTOFFEN`：活性成分，`#` 分隔，**荷兰语全大写、常把盐名连写**
    （`METFORMINEHYDROCHLORIDE`、`ERYTROMYCINELACTOBIONAAT`）。

复用（不另起一套）
------------------
- 规格：`etl/normalize_name.py:normalize()` 抽名称里的规格（吃荷兰语小数逗号 `0,5 mg`、
  `x mg/2 ml`），单位规范化用 `etl/normalize_strength.py:norm_unit()`，
  `POTENTIE` 一列交给 `etl/ingest_sg_hsa.py:parse_strength()`。本脚本只加「输入串预整形」
  （`IE`→`iu`、`microgram`→`mcg`、`200 mg/ml`→`200 mg/1 ml`），不写第二套数值解析。
- 成分映射：`etl/ingest_sg_hsa.py:SgMapper`（slug / inn / alias / BAN / 去盐四级规则），
  前面加一层荷兰语清洗（重音折叠、`(E 420)` 食品添加剂码、`x-water` 水合物、荷兰语盐名词、
  连写盐名切分、词尾 e 增删），只用来**生成候选写法**，命中与否仍由库里 `substance` 决定。
- variant 解析：`etl/ingest_ema_medicines.py:_variant_resolver()`（含 salt-orphan 兜底）。

CLI：
    python etl/markets/nl.py --fetch        # 抓快照到 data/raw/nl/（metadata.csv + fetch_meta.json）
    python etl/markets/nl.py --dry-run      # 默认：读缓存 → 解析 → 统计（只读开库，不写库）
    python etl/markets/nl.py --self-check   # 离线断言：27 列 / 竖线不串列 / 规格样例
    python etl/markets/nl.py --dry-run --db data/drugs.db

产物：`.tmp/nl-dry-run/nl_dry_run.json`（统计）+ 控制台摘要。`.tmp/`、`data/raw/` 都不入库。

注意（页面口径，写页面时必须照做）：荷兰语原文、数据滞后两周、`SOORT=RVH` 是
「handelsvergunning」不是集中审批（集中审批那批 `SOORT` 是空、注册号 `EU/…`）。
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import re
import sqlite3
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "etl"))

from ingest_ema_medicines import _variant_resolver  # noqa: E402
from ingest_openfda_ndc import form_base_of, slug  # noqa: E402
from ingest_sg_hsa import SgMapper, parse_strength  # noqa: E402
from normalize_name import normalize  # noqa: E402
from normalize_strength import norm_unit  # noqa: E402

# Windows 控制台默认 GBK，荷兰语原文里的 ï/ë/ü 会让 print 抛 UnicodeEncodeError。
try:  # pragma: no cover - 只影响终端显示
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    pass

URL = "https://www.geneesmiddeleninformatiebank.nl/metadata.csv"
INFO_URL = "https://www.geneesmiddeleninformatiebank.nl/"
RAW = ROOT / "data" / "raw" / "nl"
CSV_PATH = RAW / "metadata.csv"
FETCH_META = RAW / "fetch_meta.json"
DEFAULT_DB = ROOT / "data" / "drugs.db"
WORK = ROOT / ".tmp" / "nl-dry-run"
LICENCE_REPORT = "reports/2026-11-11-nl-license-assessment.md"
UA = ("drug-brand-crossref/0.1 (dry-run only; +https://github.com/fuarnos/drug-brand-crossref)")
COLUMNS = 27
DELIMITER = "|"
# 页面必须写明：数据每周更新但滞后两周（数据方自述）。
LAG_NOTE = "数据每周更新，但发布滞后两周（数据方自述）"
SOURCE_ID = "cbg_meb_nl"


# ---------------------------------------------------------------- 小工具
def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    """只读开库（`mode=ro`）：本脚本没有任何写库路径，连接也开不成写。"""
    db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=120)
    db.row_factory = sqlite3.Row
    return db


def _fold(text: str) -> str:
    """重音折叠 + 小写（`LIDOCAÏNE` → `lidocaine`）；只用于比较，不写库。"""
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return s


# ---------------------------------------------------------------- 抓取
def cmd_fetch(args: argparse.Namespace) -> int:
    """抓 `metadata.csv` 到 `data/raw/nl/`，并写 `fetch_meta.json`（url/bytes/sha256/时间/Last-Modified）。

    不用 `Invoke-WebRequest` / `curl.exe`：本机 schannel 会报 `SEC_E_NO_CREDENTIALS`，
    统一走 Python `urllib.request`（带 UA、`timeout=180`）。
    """
    target = args.src if args.src.is_absolute() else (ROOT / args.src)
    meta_path = args.meta if args.meta.is_absolute() else (ROOT / args.meta)
    target.parent.mkdir(parents=True, exist_ok=True)
    req = Request(URL, headers={"User-Agent": UA, "Accept": "text/csv,*/*"})
    t0 = time.perf_counter()
    print(f"=== NL GIP 抓取 ===\n  GET {URL}")
    with urlopen(req, timeout=180) as resp:  # noqa: S310 - 固定官方 URL
        status = getattr(resp, "status", None)
        headers = {k.lower(): v for k, v in resp.headers.items()}
        blob = resp.read()
    elapsed = round(time.perf_counter() - t0, 1)
    if not blob:
        raise SystemExit("抓取返回 0 字节，中止（不覆盖缓存）。")
    tmp = target.with_name(target.name + ".part")
    tmp.write_bytes(blob)
    tmp.replace(target)
    head_lines = blob.count(b"\n") + (0 if blob.endswith(b"\n") else 1)
    meta = {
        "source_id": SOURCE_ID,
        "url": URL,
        "info_url": INFO_URL,
        "bytes": len(blob),
        "sha256": _sha256_bytes(blob),
        "fetched_at": _now(),
        "last_modified": headers.get("last-modified"),
        "etag": headers.get("etag"),
        "content_type": headers.get("content-type"),
        "http_status": status,
        "lines": head_lines,
        "licence": {
            "status": "🟡 待确认（国家目录明标许可未知）：不得写库、不得上线",
            "report": LICENCE_REPORT,
        },
        "note": f"数据每周更新、滞后两周（数据方自述）；{LAG_NOTE}",
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  保存 {target.relative_to(ROOT)} · {meta['bytes']:,} B · {head_lines:,} 行"
          f" · sha256 {meta['sha256'][:16]}…")
    print(f"  Last-Modified: {meta['last_modified']} · HTTP {status} · 耗时 {elapsed}s")
    print(f"  元数据 {meta_path.relative_to(ROOT)}")
    return 0


# ---------------------------------------------------------------- 解析：行与列
def load_snapshot(path: Path = CSV_PATH) -> tuple[list[dict], dict]:
    """读竖线分隔的 CSV → (行列表, 统计)。

    `|` 不是常见分隔符，字段里也可能出现 `|`；这里按 `csv.reader` 逐行解析并**校验每行
    列数 = 表头列数**，列数不符的行单独计数、不入统计（串列会被静默污染，必须显式报出来）。
    """
    if not path.exists():
        raise SystemExit(f"缺快照：{path}（先跑 `python etl/markets/nl.py --fetch`）")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    reader = csv.reader(text.splitlines(), delimiter=DELIMITER)
    try:
        header = next(reader)
    except StopIteration:
        raise SystemExit(f"空文件：{path}")
    header = [h.strip() for h in header]
    stats: Counter = Counter()
    stats["header_columns"] = len(header)
    if len(header) != COLUMNS:
        raise SystemExit(f"表头列数 {len(header)} ≠ 预期 {COLUMNS}：{header}")
    rows: list[dict] = []
    for lineno, raw in enumerate(reader, start=2):
        if not raw:
            continue
        stats["lines"] += 1
        if len(raw) != len(header):
            stats["bad_column_count"] += 1
            stats[f"bad_columns:{len(raw)}"] += 1
            if stats["bad_sample_lines"] < 5:
                stats["bad_sample_lines"] += 1
                print(f"  !! 第 {lineno} 行列数 {len(raw)} ≠ {len(header)}，跳过")
            continue
        rows.append(dict(zip(header, raw)))
        stats["rows"] += 1
    return rows, dict(stats)


def _clean(value: str | None) -> str:
    return (value or "").strip()


# ---------------------------------------------------------------- 解析：成分
# 荷兰语盐名词 → 英文 INN 里常见的盐名（只用于生成候选写法，命中仍由库里 substance 决定）
NL_SALT_WORDS = {
    "dihydrochloride": "dihydrochloride", "waterstofchloride": "hydrochloride",
    "hydrochloride": "hydrochloride", "fumaraat": "fumarate", "maleaat": "maleate",
    "tartraat": "tartrate", "citraat": "citrate", "acetaat": "acetate",
    "sulfaat": "sulfate", "fosfaat": "phosphate", "nitraat": "nitrate",
    "bromide": "bromide", "jodide": "iodide", "chloride": "chloride",
    "mesylaat": "mesylate", "mesilaat": "mesilate", "besilaat": "besylate",
    "tosylaat": "tosylate", "lactobionaat": "lactobionate", "benzoaat": "benzoate",
    "succinaat": "succinate", "propionaat": "propionate", "valeraat": "valerate",
    "pamoaat": "pamoate", "embonaat": "embonate", "furoaat": "furoate",
    "xinafoaat": "xinafoate", "decanoaat": "decanoate", "undecanoaat": "undecanoate",
    "palmitaat": "palmitate", "stearaat": "stearate", "gluconaat": "gluconate",
    "aspartaat": "aspartate", "dipropionaat": "dipropionate",
    "acetonide": "acetonide", "valproaat": "valproate", "picosulfaat": "picosulfate",
    "carbonaat": "carbonate", "oxide": "oxide", "hydroxide": "hydroxide",
    "medoxomil": "medoxomil", "cilexetil": "cilexetil", "olamine": "olamine",
    "clavulanaat": "clavulanate", "trometamol": "tromethamine",
    "sodium": "sodium", "natrium": "sodium",
    "kalium": "potassium", "calcium": "calcium", "magnesium": "magnesium",
    "zink": "zinc", "ijzer": "iron", "hydrate": "hydrate",
}
# 荷兰语剂量/质量修饰词（`MAGNESIUMCARBONAAT, ZWAAR` 的重/轻），对成分名无意义
NL_NOISE = frozenset({"zwaar", "licht", "fijn", "grof", "watervrij", "anhydrous",
                      "gemalen", "poeder"})
# 连写词头的荷兰语元素名（`NATRIUMCHLORIDE` → `sodiumchloride`）
NL_PREFIX = {"natrium": "sodium", "kalium": "potassium", "waterstof": "hydrogen",
             "zink": "zinc", "ijzer": "iron"}
_RE_E_NUMBER = re.compile(r"\(e\s*\d+[^)]*\)", re.I)
_RE_HYDRATE = re.compile(r"\b(?:\d+|x)\s*-\s*water\b", re.I)


def _nl_clean_token(token: str) -> str:
    """荷兰语成分串 → 可比较的小写写法：去重音、去 `(E 420)`、水合物写成 hydrate、盐名英文化。"""
    s = _fold(token)
    s = _RE_E_NUMBER.sub(" ", s)
    s = _RE_HYDRATE.sub(" hydrate ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    words = [w for w in s.split() if w not in NL_NOISE]
    return " ".join(NL_SALT_WORDS.get(w, w) for w in words)


def _word_splits(word: str) -> list[str]:
    """单个连写词 → 切出「基名 + 盐/酯名」的几种写法（ERYTROMYCINELACTOBIONAAT …）。"""
    out: list[str] = []
    for nl, en in sorted(NL_SALT_WORDS.items(), key=lambda kv: len(kv[0]), reverse=True):
        if not word.endswith(nl) or len(word) - len(nl) < 4:
            continue
        prefix = word[: -len(nl)]
        prefix = NL_PREFIX.get(prefix, prefix)
        out.append(f"{prefix} {en}")     # 基名和盐名分开写（库里多半是这种）
        out.append(f"{prefix}{en}")      # 分开后仍连写
        out.append(prefix)               # 只要基名（库里可能只收了基名）
        if prefix.endswith("aat"):       # methotrexa‑aat → methotrexate
            out.append(prefix[:-3] + "ate")
    return out


def substance_variants(token: str) -> list[str]:
    """荷兰语成分 token → 候选写法（按优先级去重，最多 24 个）。

    只做**写法变换**，不做匹配：候选交给 `SgMapper.map_basic()`，能不能挂上由库里
    `substance` 说了算（不新增 substance、不做模糊匹配）。

    连写词要先「切盐名」再「改拼写」：`METFORMINEHYDROCHLORIDE` 只有切成
    `metformine hydrochloride` 之后再去尾 e 才能对上库里的 `Metformin Hydrochloride`。
    """
    base = _nl_clean_token(token)
    if not base:
        return []
    stems: list[str] = [base]
    words = base.split()
    # ① 逐词切「连写的盐/酯/水合物名」（VALACICLOVIRHYDROCHLORIDE → valaciclovir）
    for i, word in enumerate(words):
        for form in _word_splits(word):
            stems.append(" ".join(words[:i] + [form] + words[i + 1:]))
    # ② 逐词去尾部修饰词（最多 3 层）
    tail = words[:]
    for _ in range(3):
        if len(tail) <= 1:
            break
        tail = tail[:-1]
        stems.append(" ".join(tail))
    # ③ 每个切法上再套拼写变换：去尾/加尾 e、荷兰语 chloor→chloro、-aat→-ate
    out: list[str] = [base]
    for stem in stems:
        out.append(stem)
        for i, word in enumerate(stem.split()):
            if word in NL_SALT_WORDS or len(word) < 5:
                continue
            ws = stem.split()
            out.append(" ".join(ws[:i] + [word[:-1] if word.endswith("e") else word + "e"]
                                + ws[i + 1:]))
            if "chloor" in word:
                out.append(" ".join(ws[:i] + [word.replace("chloor", "chloro")] + ws[i + 1:]))
            if "f" in word:                       # 荷兰语 f ↔ 英语 ph（morfine→morphine）
                out.append(" ".join(ws[:i] + [word.replace("f", "ph")] + ws[i + 1:]))
            if word.endswith("aat"):
                out.append(" ".join(ws[:i] + [word[:-3] + "ate"] + ws[i + 1:]))
    return list(dict.fromkeys(x for x in out if x))[:24]


def split_substances(value: str) -> list[str]:
    """`WERKZAMESTOFFEN` → 成分 token 列表（`#` 分隔；空 / `GEEN` 归零）。"""
    text = _clean(value)
    if not text or text.upper() in {"GEEN", "GEEN WERKZAME STOFFEN", "-"}:
        return []
    return [t.strip() for t in text.split("#") if t.strip()]


def map_substance(mapper: SgMapper, token: str) -> tuple[str, str]:
    """token → (substance_id, method)；映射不上返回 ("", "unmapped")。"""
    for idx, cand in enumerate(substance_variants(token)):
        sid, _salt, method = mapper.map_basic(cand)
        if sid:
            return sid, ("raw" if idx == 0 else f"nl-{method}")
    return "", "unmapped"


# ---------------------------------------------------------------- 解析：规格
_RE_IE = re.compile(r"\b(IE|IU)\b", re.I)
_RE_MICRO = re.compile(r"\bmicrogram(?:s)?\b", re.I)
_RE_CONC_NO_DENOM = re.compile(
    r"(\d+(?:[.,]\d+)?\s*(?:mg|mcg|µg|μg|g|iu))(\s*/\s*)(ml|l)\b", re.I)


def _strength_input(name: str) -> str:
    """规格抽取前的输入整形（**不改任何数值**，只为让既有解析器认出荷兰语写法）。

    - `IE` / `IU` → `iu`（`etl/normalize_name.py` 的单位表只认 iu）；
    - `microgram` → `mcg`；
    - `200 mg/ml` → `200 mg/1 ml`：既有的浓度正则要求分母带数字，缺省分母按 1 补，
      这样 `per_volume_value=1` 是「每 1 ml」，不是换算。
    """
    s = _RE_IE.sub("iu", name or "")
    s = _RE_MICRO.sub("mcg", s)
    return _RE_CONC_NO_DENOM.sub(r"\g<1>\g<2>1 \g<3>", s)


def parse_name_strengths(name: str) -> list[dict]:
    """从 `PRODUCTNAAM` 抽规格 → [{value, unit, per_volume_value, per_volume_unit}]。

    数值与单位来自 `normalize()`（仓库统一的名称解析，吃 `0,5 mg` / `x mg/2 ml`），
    `/` 两侧的数字与单位只是**摆到 schema 的四列上**，不做任何换算；单位再走
    `norm_unit()` 规范成 `mg` / `mL` / `IU`。
    """
    out: list[dict] = []
    for raw_value, raw_unit in normalize(_strength_input(name)).strengths:
        values = str(raw_value).split("/")
        units = str(raw_unit).split("/")
        try:
            value = float(values[0])
        except ValueError:
            continue
        unit, _rule = norm_unit(units[0])
        per_v: float | None = None
        per_u: str | None = None
        if len(values) > 1 or len(units) > 1:
            try:
                per_v = float(values[1]) if len(values) > 1 else 1.0
            except ValueError:
                per_v = None
            if len(units) > 1:
                per_u, _ = norm_unit(units[1])
            if per_v is None:
                per_u = None
        out.append({"value": value, "unit": unit,
                    "per_volume_value": per_v, "per_volume_unit": per_u})
    return out


def parse_potentie(value: str) -> tuple[float | None, str | None, float | None, str | None]:
    """`POTENTIE` → 复用 `etl/ingest_sg_hsa.py:parse_strength` 的 (值, 单位, 每量, 每量单位)。

    实测这一列基本是顺势疗法稀释度（`4 DH t/m 60 DH#…`），解析不出数值——这是**结论**，
    不是 bug：NL 的数值规格只能从 `PRODUCTNAAM` 取。
    """
    return parse_strength(_clean(value))


# ---------------------------------------------------------------- dry-run
def _product_id(row: dict) -> str:
    reg = _clean(row.get("REGISTRATIENUMMER"))
    name = _clean(row.get("PRODUCTNAAM"))
    base = f"NL-{slug(reg) or 'urn'}"[:48]
    digest = hashlib.sha1(f"{reg}|{name}".encode()).hexdigest()[:8]
    return f"{base}-{digest}"


def _collect(rows: list[dict], mapper: SgMapper, resolve) -> dict:
    """逐行解析并统计（只读；不产生任何写库语句）。"""
    stats: Counter = Counter()
    soort = Counter()
    forms: Counter = Counter()
    routes: Counter = Counter()
    delivery: Counter = Counter()
    atc_top: Counter = Counter()
    units: Counter = Counter()
    unmapped: Counter = Counter()
    tokens_seen: set[str] = set()
    strength_tokens = 0
    products_with_strength = 0
    products_single_strength = 0
    products_multi_strength = 0
    products_all_mapped = 0
    products_partial = 0
    products_none = 0
    components_planned = 0
    components_no_variant = 0
    components_with_strength = 0
    name_keys_new: set[str] = set()
    name_variants_new: set[tuple[str, str]] = set()
    reg_numbers: Counter = Counter()
    reg_name_pairs: set[tuple[str, str]] = set()
    potentie_non_empty = 0
    potentie_parsed = 0
    regs = Counter()
    samples: list[dict] = []
    memo: dict[str, tuple[str, str]] = {}

    for row in rows:
        reg = _clean(row.get("REGISTRATIENUMMER"))
        name = _clean(row.get("PRODUCTNAAM"))
        form = _clean(row.get("FARMACEUTISCHEVORM"))
        route = _clean(row.get("TOEDIENINGSWEG"))
        atc = _clean(row.get("ATC"))
        stats["rows"] += 1
        reg_numbers[reg] += 1
        reg_name_pairs.add((reg, name))
        regs["eu_prefix" if reg.startswith("EU/") else "nl"] += 1

        soort[_clean(row.get("SOORT")) or "(空)"] += 1
        forms[form or "(空)"] += 1
        routes[route or "(空)"] += 1
        delivery[_clean(row.get("AFLEVERSTATUS")) or "(空)"] += 1
        if atc:
            stats["atc_present"] += 1
            atc_top[atc.split(" - ")[0].strip()] += 1
        else:
            stats["atc_missing"] += 1

        # POTENTIE
        pot = _clean(row.get("POTENTIE"))
        if pot:
            potentie_non_empty += 1
            if parse_potentie(pot)[0] is not None:
                potentie_parsed += 1

        # 规格（名称侧）
        found = parse_name_strengths(name)
        strength_tokens += len(found)
        if found:
            products_with_strength += 1
            if len(found) == 1:
                products_single_strength += 1
            else:
                products_multi_strength += 1
            for s in found:
                unit = s["unit"] or "(无单位)"
                units[f"{unit}" + (f"/{s['per_volume_unit']}" if s["per_volume_unit"] else "")] += 1

        # 成分（同一 token 只解析一次：29,764 次 token → 2,946 种写法）
        tokens = split_substances(row.get("WERKZAMESTOFFEN"))
        if not tokens:
            stats["rows_no_substance"] += 1
        mapped = []
        for t in tokens:
            hit = memo.get(t)
            if hit is None:
                hit = memo[t] = map_substance(mapper, t)
            mapped.append((t, *hit))
        tokens_seen.update(tokens)
        n_map = sum(1 for _t, sid, _m in mapped if sid)
        stats["ingredient_tokens"] += len(mapped)
        stats["ingredient_tokens_mapped"] += n_map
        for t, sid, method in mapped:
            if not sid:
                unmapped[t] += 1
                stats[f"map_method:{method}"] += 1
        # 与 EU 层同口径：复方**全部成分映射成功**才写 component，缺一个就整条不写
        write_components = bool(mapped) and n_map == len(mapped)
        if write_components:
            products_all_mapped += 1
        elif mapped and n_map:
            products_partial += 1
        elif mapped:
            products_none += 1
        chosen = found[0] if (len(found) == 1 and len(mapped) == 1) else None
        planned = []
        for _t, sid, method in mapped:
            if not write_components or not sid:
                continue
            vid = resolve(sid, _t)
            if not vid:
                components_no_variant += 1
                continue
            components_planned += 1
            if chosen:
                components_with_strength += 1
            planned.append({"token": _t, "substance_id": sid, "variant_id": vid,
                            "method": method,
                            "strength": chosen})
        if len(samples) < 5:
            samples.append({
                "registration": reg, "name": name, "soort": _clean(row.get("SOORT")),
                "form": form, "route": route, "atc": atc,
                "substances_raw": tokens,
                "substances": [f"{t} → {sid or '未映射'}" for t, sid, _m in mapped],
                "strengths": found,
                "components_planned": [f"{c['variant_id']}" for c in planned],
            })

        # 名称键（与库里 name_key 比对）
        nm = normalize(name)
        if not nm.is_empty:
            if nm.norm not in name_keys_new:
                name_keys_new.add(nm.norm)
                name_variants_new.add((nm.norm, name))

    stats["products_all_mapped"] = products_all_mapped
    stats["products_partial_mapped"] = products_partial
    stats["products_none_mapped"] = products_none
    stats["components_planned"] = components_planned
    stats["components_no_variant"] = components_no_variant
    stats["components_with_strength"] = components_with_strength
    stats["strength_tokens"] = strength_tokens
    stats["products_with_strength"] = products_with_strength
    stats["products_single_strength"] = products_single_strength
    stats["products_multi_strength"] = products_multi_strength
    stats["potentie_non_empty"] = potentie_non_empty
    stats["potentie_parsed"] = potentie_parsed
    stats["unique_registration"] = len(reg_numbers)
    stats["unique_tokens"] = len(tokens_seen)
    stats["dup_registration_rows"] = sum(n - 1 for n in reg_numbers.values() if n > 1)
    stats["dup_registration_max_rows"] = max(reg_numbers.values()) if reg_numbers else 0
    stats["unique_reg_name_pairs"] = len(reg_name_pairs)
    stats["eu_registration_rows"] = regs["eu_prefix"]
    return {
        "stats": stats, "soort": soort, "forms": forms, "routes": routes,
        "delivery": delivery, "atc_top": atc_top, "units": units,
        "unmapped": unmapped,
        "name_keys_new": name_keys_new, "name_variants_new": name_variants_new,
        "samples": samples,
    }


def cmd_dry_run(args: argparse.Namespace) -> int:
    """读缓存 → 解析 → 统计；**只读开库，不写任何库**。"""
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    src = args.src if args.src.is_absolute() else (ROOT / args.src)
    if not db_path.exists():
        raise SystemExit(f"库不存在：{db_path}（本脚本只读，不建库）")
    t0 = time.perf_counter()
    rows, load_stats = load_snapshot(src)
    db = _connect_ro(db_path)
    try:
        mapper = SgMapper(db)
        resolve = _variant_resolver(db)
        existing_keys = {r[0] for r in db.execute("SELECT key_id FROM name_key")}
        existing_pairs = {(r[0], r[1]) for r in db.execute("SELECT key_id, raw FROM name_variant")}
        db_products = db.execute("SELECT COUNT(*) FROM product").fetchone()[0]
        result = _collect(rows, mapper, resolve)
    finally:
        db.close()
    elapsed = round(time.perf_counter() - t0, 2)

    st = result["stats"]
    new_keys = sorted(result["name_keys_new"] - existing_keys)
    new_variants = sorted(p for p in result["name_variants_new"] if p not in existing_pairs)
    n_rows = max(1, st["rows"])
    n_tokens = max(1, st["ingredient_tokens"])
    units = result["units"]

    summary = {
        "generated_at": _now(),
        "tool": "etl/markets/nl.py",
        "mode": "dry-run（只读，不写库）",
        "licence": {
            "source_id": SOURCE_ID,
            "status": "🟡 待确认：国家目录明标「许可未知」，未获再发布许可",
            "can_ingest": False,
            "reason": "GIP 无许可声明；data.overheid.nl 该数据集 dct:license=licentieonbekend，"
                      "目录口径页定义为「geen hergebruik licentie / Open Data? Nee」",
            "report": LICENCE_REPORT,
            "apply_flag": "本脚本不提供 --apply（许可未获批）",
        },
        "db": {"path": str(db_path), "mode": "read-only(mode=ro)", "products": db_products},
        "snapshot": {
            "path": str(src.relative_to(ROOT)) if src.is_relative_to(ROOT) else str(src),
            "bytes": src.stat().st_size,
            "sha256": _sha256_file(src),
            "rows": load_stats["rows"],
            "header_columns": load_stats["header_columns"],
            "bad_column_count": load_stats.get("bad_column_count", 0),
            "delimiter": DELIMITER,
            "url": URL,
        },
        "rows": {
            "total": st["rows"],
            "unique_registration": st["unique_registration"],
            "dup_registration_rows": st["dup_registration_rows"],
            "dup_registration_max_rows": st["dup_registration_max_rows"],
            "unique_reg_name_pairs": st["unique_reg_name_pairs"],
            "eu_registration_rows": st["eu_registration_rows"],
        },
        "soort": {
            "RVG": result["soort"].get("RVG", 0),
            "RVH": result["soort"].get("RVH", 0),
            "empty_eu_centralised": result["soort"].get("(空)", 0),
            "note": "SOORT=RVH 是「handelsvergunning」，不是集中审批；集中审批那批 SOORT 为空、"
                    "注册号以 EU/ 开头（与本库 region='EU' 层重叠）",
        },
        "potentie": {
            "non_empty": st["potentie_non_empty"],
            "parsed": st["potentie_parsed"],
            "rate_pct": round(st["potentie_parsed"] / max(1, st["potentie_non_empty"]) * 100, 1),
            "note": "POTENTIE 是本列里唯一像规格的字段，但实测几乎全空，非空的 453 行是顺势疗法"
                    "稀释度（DH/CH/K/LM），不是数值规格 → 数值规格只能从 PRODUCTNAAM 取",
        },
        "strength": {
            "source": "PRODUCTNAAM（normalize() 抽取 + norm_unit() 规范单位）",
            "products_with_strength": st["products_with_strength"],
            "products_with_strength_pct": round(st["products_with_strength"] / n_rows * 100, 1),
            "products_single_strength": st["products_single_strength"],
            "products_multi_strength": st["products_multi_strength"],
            "tokens": st["strength_tokens"],
            "units_top": units.most_common(12),
            "components_with_strength": st["components_with_strength"],
            "rule": "只有「1 个成分 + 1 个规格」才把数值挂到 product_component；复方/多规格一律留空"
                    "（不猜哪段数值属于哪个成分）",
        },
        "substance": {
            "tokens": st["ingredient_tokens"],
            "tokens_mapped": st["ingredient_tokens_mapped"],
            "token_rate_pct": round(st["ingredient_tokens_mapped"] / n_tokens * 100, 1),
            "unique_tokens": st["unique_tokens"],
            "rows_no_substance": st["rows_no_substance"],
            "unmapped_unique": len(result["unmapped"]),
            "unmapped_top20": result["unmapped"].most_common(20),
            "products_all_mapped": st["products_all_mapped"],
            "products_partial_mapped": st["products_partial_mapped"],
            "products_none_mapped": st["products_none_mapped"],
        },
        "atc": {
            "present": st["atc_present"],
            "missing": st["atc_missing"],
            "coverage_pct": round(st["atc_present"] / n_rows * 100, 1),
            "top10": result["atc_top"].most_common(10),
        },
        "dosage_form": {
            "distinct": len(result["forms"]),
            "top15": result["forms"].most_common(15),
        },
        "route": {
            "distinct": len(result["routes"]),
            "all": result["routes"].most_common(),
        },
        "delivery_status": {
            "distinct": len(result["delivery"]),
            "top5": result["delivery"].most_common(5),
        },
        "would_write": {
            "products": st["rows"],
            "components": st["components_planned"],
            "components_with_strength": st["components_with_strength"],
            "components_no_variant": st["components_no_variant"],
            "products_without_component": st["rows"] - st["products_all_mapped"],
            "name_keys_new": len(new_keys),
            "name_variants_new": len(new_variants),
            "product_names": st["rows"],
            "note": "**只是预测**：本脚本没有任何写库路径；产品行按「一行 = 一个规格/剂型」计",
        },
        "page_wording": {
            "language": "荷兰语原文（PRODUCTNAAM / 剂型 / 给药途径均为荷兰语，不翻译）",
            "freshness": LAG_NOTE,
            "soort": "RVG = nationale registratie；RVH = handelsvergunning；SOORT 为空 = EU 集中审批"
                     "（注册号 EU/…），**不要**把 RVH 说成集中审批",
        },
        "samples": result["samples"],
        "elapsed_s": elapsed,
    }

    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / "nl_dry_run.json"
    out.write_text(json.dumps({k: v for k, v in summary.items() if k != "samples"},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    (WORK / "nl_samples.json").write_text(
        json.dumps(summary["samples"], ensure_ascii=False, indent=1), encoding="utf-8")

    print("=== NL GIP dry-run（只读，不写库）===")
    print(f"  许可: 🟡 待确认（{LICENCE_REPORT}）→ 本脚本没有 --apply")
    print(f"  快照: {summary['snapshot']['path']} · {summary['snapshot']['bytes']:,} B"
          f" · {load_stats['header_columns']} 列 · {st['rows']:,} 行"
          f"（列数异常行 {load_stats.get('bad_column_count', 0)}）")
    print(f"  注册号: 唯 {st['unique_registration']:,} 个 · 重复行 {st['dup_registration_rows']:,}"
          f"（同一注册号最多 {st['dup_registration_max_rows']} 行 = 不同规格/剂型）"
          f" · EU/ 集中审批 {st['eu_registration_rows']:,} 行")
    print(f"  SOORT : RVG {summary['soort']['RVG']:,} / RVH {summary['soort']['RVH']:,}"
          f" / 空（EU 集中审批）{summary['soort']['empty_eu_centralised']:,}")
    print(f"  POTENTIE: 非空 {st['potentie_non_empty']:,}，能解析出数值 "
          f"{st['potentie_parsed']:,}（→ 该列不是规格列）")
    print(f"  规格(名称侧): {st['products_with_strength']:,} 个产品有规格"
          f"（{summary['strength']['products_with_strength_pct']}%）· 单规格 "
          f"{st['products_single_strength']:,} / 多规格 {st['products_multi_strength']:,}"
          f" · 单位 top: {units.most_common(6)}")
    print(f"  成分映射: {st['ingredient_tokens_mapped']:,}/{st['ingredient_tokens']:,} = "
          f"{summary['substance']['token_rate_pct']}% · 未映射 {len(result['unmapped']):,} 种"
          f" · 未映射 top5: {[x[0] for x in result['unmapped'].most_common(5)]}")
    print(f"  ATC 覆盖: {summary['atc']['coverage_pct']}%（{st['atc_present']:,}/"
          f"{st['atc_present'] + st['atc_missing']:,}）")
    print(f"  剂型 top3: {[f'{k}({v})' for k, v in result['forms'].most_common(3)]}"
          f" · 共 {len(result['forms']):,} 种")
    print(f"  给药途径 top3: {[f'{k}({v})' for k, v in result['routes'].most_common(3)]}"
          f" · 共 {len(result['routes']):,} 种")
    print(f"  预计入库(仅预测): 产品 {st['rows']:,} · component {st['components_planned']:,}"
          f"（其中带规格 {st['components_with_strength']:,}）"
          f" · 无 variant {st['components_no_variant']:,}"
          f" · name_key 新建 {len(new_keys):,} · name_variant 新建 {len(new_variants):,}")
    print(f"  样例（首条）: {json.dumps(result['samples'][0], ensure_ascii=False)[:400]}")
    print(f"  耗时 {elapsed}s · 汇总 {out.relative_to(ROOT)}")
    return 0


# ---------------------------------------------------------------- 自测
def self_check(src: Path = CSV_PATH) -> int:
    """离线断言：表头 27 列 / 竖线分隔不串列 / 规格解析样例 / 无 --apply。

    不依赖库；快照存在时顺带核对真实文件的列数与行长度。
    """
    failures: list[str] = []

    def check(name: str, cond: bool, extra: str = "") -> None:
        print(f"  {'ok  ' if cond else 'FAIL'} {name}{('  ' + extra) if extra else ''}")
        if not cond:
            failures.append(name)

    # 1) 表头 27 列 + 竖线分隔不串列
    if src.exists():
        reader = csv.reader(src.read_text(encoding="utf-8-sig", errors="replace").splitlines(),
                            delimiter=DELIMITER)
        header = [h.strip() for h in next(reader)]
        check("表头 27 列", len(header) == COLUMNS, f"实测 {len(header)}")
        bad = 0
        n = 0
        for raw in reader:
            if not raw:
                continue
            n += 1
            if len(raw) != len(header):
                bad += 1
        check("竖线分隔不串列（每行列数 = 表头）", bad == 0, f"{n:,} 行 / 异常 {bad}")
        check("表头含关键列", {"REGISTRATIENUMMER", "PRODUCTNAAM", "SOORT", "POTENTIE",
                                "WERKZAMESTOFFEN", "ATC", "FARMACEUTISCHEVORM",
                                "TOEDIENINGSWEG"} <= set(header))
    else:
        check("表头 27 列", COLUMNS == 27, "快照不存在 → 只核对常量")
        print(f"  skip 竖线分隔实测（缺 {src}）")

    # 2) 合成一行：字段里带 | 时 csv 会当成列 → 说明必须靠列数校验兜住
    synth = DELIMITER.join(["x"] * COLUMNS)
    check("合成 27 列能被解析成 27 个字段", len(next(csv.reader([synth], delimiter=DELIMITER)))
          == COLUMNS)

    # 3) 规格解析样例（5 条真实 NL 名称 → 预期值）
    cases = [
        ("Cisordinol 10 mg, filmomhulde tabletten", [(10.0, "mg", None, None)]),
        ("Digoxine Eureco-Pharma, oplossing voor injectie 0,5 mg/2 ml",
         [(0.5, "mg", 2.0, "mL")]),
        ("Kenacort-A 40, suspensie voor injectie 40 mg/ml", [(40.0, "mg", 1.0, "mL")]),
        ("Progynova 1 mg, omhulde tabletten", [(1.0, "mg", None, None)]),
        ("ReFacto AF, 3000 IE poeder en oplossing voor injectie",
         [(3000.0, "IU", None, None)]),
    ]
    for name, expect in cases:
        got = [(s["value"], s["unit"], s["per_volume_value"], s["per_volume_unit"])
               for s in parse_name_strengths(name)]
        check(f"规格样例 {name[:34]!r}", got == expect, f"→ {got}")
    # 底层解析器（被复用的那个）本身的行为
    check("parse_strength('500 mg/5 ml')",
          parse_strength("500 mg/5 ml") == (500.0, "mg", 5.0, "ml"))
    check("POTENTIE 顺势疗法串解析不出数值",
          parse_potentie("4 DH t/m 60 DH#2 CH t/m 200 CH")[0] is None)
    # 成分切分
    check("成分串按 # 拆分",
          split_substances("NATRIUMLAURILSULFOACETAAT#SORBITOL (E 420)#TRINATRIUMCITRAAT 2-WATER")
          == ["NATRIUMLAURILSULFOACETAAT", "SORBITOL (E 420)", "TRINATRIUMCITRAAT 2-WATER"])
    check("空成分串归零", split_substances("") == [])
    check("荷兰语连写盐名切出候选",
          any(c == "erytromycine" for c in substance_variants("ERYTROMYCINELACTOBIONAAT")),
          str(substance_variants("ERYTROMYCINELACTOBIONAAT")[:4]))

    # 4) 不提供 --apply（许可未获批）
    try:
        with contextlib.redirect_stderr(io.StringIO()):   # 探针不该把 usage 噪音打到终端
            main(["--apply"])
    except SystemExit:
        pass
    else:
        failures.append("--apply 竟然被接受")
    try:
        ap = build_parser()
        flags = {opt for action in ap._actions for opt in action.option_strings}
        check("CLI 没有 --apply / --rollback", "--apply" not in flags and "--rollback" not in flags)
        check("CLI 有 --fetch / --dry-run / --self-check",
              {"--fetch", "--dry-run", "--self-check"} <= flags)
    except SystemExit:
        failures.append("build_parser 退出")

    print(f"\n=== self-check {'全部通过' if not failures else '有失败'}（{len(failures)} 项失败）===")
    return 0 if not failures else 1


def cmd_self_check(args: argparse.Namespace) -> int:
    src = args.src if args.src.is_absolute() else (ROOT / args.src)
    return self_check(src)


# ---------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="荷兰 CBG-MEB GIP（metadata.csv）ETL 骨架：只做干跑，**不写库**。"
                    f"许可未获批（见 {LICENCE_REPORT}），因此本脚本不提供 --apply。",
        epilog="例：--fetch 抓快照；--dry-run 出统计（默认）；--self-check 跑离线断言。")
    ap.add_argument("--fetch", action="store_true",
                    help="抓 https://www.geneesmiddeleninformatiebank.nl/metadata.csv 到 data/raw/nl/")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="读缓存 → 解析 → 统计（默认；只读开库，不写库）")
    mode.add_argument("--self-check", action="store_true",
                      help="离线断言：表头 27 列 / 竖线不串列 / 规格样例 / 无 --apply")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="只读打开的库（默认 data/drugs.db）")
    ap.add_argument("--src", type=Path, default=CSV_PATH, help="快照路径（默认 data/raw/nl/metadata.csv）")
    ap.add_argument("--meta", type=Path, default=FETCH_META, help="抓取元数据路径")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    # 本脚本刻意不实现 --apply / --rollback：NL 未获再发布许可，写库路径等许可落地后另开任务。
    if args.fetch:
        return cmd_fetch(args)
    if args.self_check:
        return cmd_self_check(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
