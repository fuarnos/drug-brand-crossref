# -*- coding: utf-8 -*-
"""日本 薬価基準収載品目リスト ETL 骨架 —— **只做干跑，不写库**。

口径红线（这一页最重要）
------------------------
厚生労働省「薬価基準収載品目リスト」是**医保收载/药价基准**（薬価基準に収載されている品目）清单，
**不是日本上市注册库**（不是 PMDA 的承認品目リスト，也不是「该国全部上市药品」）。页面文案必须写：

> 日本医保收载品目（薬価基準），不等于该国全部上市药品。

不得写成「日本上市药品」；「収載 ≠ 当前在售」也要写清。

许可（A 类）
------------
厚生労働省网站「利用規約・リンク・著作権等」写明：未特别标注的内容归厚生労働省所有，
依 **公共データ利用規約（第1.0版）(PDL1.0)** 使用；要求①注明出处（省名 + 页面 URL），
②编辑/加工后须注明「加工して作成」，且不得让人误以为是政府作成。证据存
`data/raw/jp_yakka_20261112/license/`（含 PDL1.0 原文与网站条款）。

数据源（4 个官方 Excel，2026-11-01 適用版）
-------------------------------------------
页面 `https://www.mhlw.go.jp/topics/2026/04/tp20260401-01.html`（令和8年11月1日適用）：
  - 内用薬 `xls/tp20261101-01_01.xlsx`（11月1日適用品目を反映）
  - 注射薬 `xls/tp20261101-01_02.xlsx`
  - 外用薬 `xls/tp20261014-01_03.xlsx`（10月14日現在品目を反映）
  - 歯科用薬剤 `xls/tp20260401-01_04.xlsx`
实测 **12,442 品目**（每行一个「薬価基準収載医薬品コード」）。列（无表头行外列名）：
`区分 / 薬価基準収載医薬品コード / 成分名 / 規格 / （空 3 列）/ 品名 / メーカー名 /
後発医薬品加算対象 / 先発医薬品 / 同一剤形・規格の後発医薬品がある先発医薬品 / 薬価 / 経過措置による使用期限 / 備考`。

字段特征（写页面/写库都要知道）：
- **全部是全角日文**（`１ｍｇ１錠`、`Ｔ’ｓ製薬`），解析前必须 **NFKC** 归一（`１ｇ`→`1 g`），
  否则规格抽取率会归零；本脚本对所有单元格做 NFKC。
- **没有独立剂型列**：剂型从 `品名` 尾缀/包含词派生（錠・カプセル・散・液・注射・軟膏…），
  派生不出来时按 `区分`（内用薬/注射薬/外用薬/歯科用薬剤）兜底；两个比率都报。
- **没有 ATC**：`成分名` 是日文片假名 INN（`ドネペジル塩酸塩`），用「片假名→罗马字→音韵骨架」
  对上库内 `substance.inn_en`，只接受**唯一候选**（多候选/未命中一律空着，不猜）。
- `薬価` 是**药价（日元）**，只做展示/事实，不做剂量换算、不做价格换算。

CLI：
    python etl/markets/jp.py --fetch          # 抓 4 个 Excel + 许可证据到 data/raw/jp_yakka_20261112/
    python etl/markets/jp.py --prepare-copy   # 真库 → .tmp/jp-ingest/drugs_jp_copy.db
    python etl/markets/jp.py --dry-run        # 默认：读缓存 → 解析 → 统计（只读库副本）
    python etl/markets/jp.py --self-check     # 离线断言：NFKC / 列数 / 规格 / 剂型 / 映射 / 无 --apply

产物：`.tmp/jp-ingest/jp_dry_run.json` + `jp_samples.json`；`data/raw/`、`.tmp/` 都不入 git；
`data/drugs.db` 全程只读（`mode=ro`）。**不提供 `--apply`**（站点还没有 ja 语言与 JP 市场）。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import sqlite3
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import openpyxl

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "etl"))

from ingest_ema_medicines import _variant_resolver  # noqa: E402
from normalize_name import normalize  # noqa: E402
from normalize_strength import norm_unit  # noqa: E402

try:  # Windows 控制台默认 GBK，日文假名会让 print 抛 UnicodeEncodeError
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    pass

BASE = "https://www.mhlw.go.jp"
LIST_PAGE = f"{BASE}/topics/2026/04/tp20260401-01.html"
FILE_URL = f"{BASE}/topics/2026/04/xls/{{name}}"
COPYRIGHT_PAGE = f"{BASE}/chosakuken/index.html"
PDL_URL = "https://www.digital.go.jp/resources/open_data/public_data_license_v1.0"
RAW = ROOT / "data" / "raw" / "jp_yakka_20261112"
LICENSE_DIR = RAW / "license"
FETCH_META = RAW / "fetch_meta.json"
WORK = ROOT / ".tmp" / "jp-ingest"
REAL_DB = ROOT / "data" / "drugs.db"
DB_COPY = WORK / "drugs_jp_copy.db"
SOURCE_ID = "jp_yakka"
COUNTRY = "JP"
UA = "drug-brand-crossref/0.1 (dry-run only; +https://github.com/fuarnos/drug-brand-crossref)"
LIST_DATE = "2026-11-01"

# 4 个官方 Excel：key → (文件名, 区分)
FILES: dict[str, dict] = {
    "naisho": {"name": "tp20261101-01_01.xlsx", "kubun": "内用薬"},
    "chusha": {"name": "tp20261101-01_02.xlsx", "kubun": "注射薬"},
    "gaiyo": {"name": "tp20261014-01_03.xlsx", "kubun": "外用薬"},
    "shika": {"name": "tp20260401-01_04.xlsx", "kubun": "歯科用薬剤"},
}
SHEET = "ＨＰ用"
COLUMNS = 15
# 列序（实测 15 列，字段名按表头；col4-6 为空列、col14 備考）
COL = {
    "kubun": 0, "code": 1, "ingredient": 2, "spec": 3, "name": 7, "maker": 8,
    "generic_addon": 9, "senpatsu": 10, "senpatsu2": 11, "price": 12, "expiry": 13,
    "note": 14,
}
PAGE_NOTE = "薬価基準収載品目リスト（医保收载/药价基准；不等于该国全部上市药品；収載 ≠ 当前在售）"


# ---------------------------------------------------------------- 小工具
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=120)
    db.row_factory = sqlite3.Row
    return db


_NFKC_EXTRA = {"’": "'", "‘": "'", "”": '"', "“": '"', "－": "-", "−": "-",
               "–": "-", "—": "-"}


def nfkc(value: object) -> str:
    """全角 → 半角（`１ｍｇ１錠` → `1mg1錠`，`Ｔ’ｓ製薬` → `T's製薬`）。"""
    s = unicodedata.normalize("NFKC", str(value or ""))
    for a, b in _NFKC_EXTRA.items():
        s = s.replace(a, b)
    return s.strip()


def _decode_page(blob: bytes) -> tuple[str, str]:
    """政府页面编码混用（薬価页 Shift_JIS、利用規約 UTF-8）：按 meta/实测兜底解码。"""
    head = blob[:4096].decode("ascii", "ignore").lower()
    for enc in (("sjis", "shift_jis") if ("shift_jis" in head or "x-sjis" in head) else ("utf-8",),
                ("utf-8",), ("cp932",)):
        try:
            return blob.decode(enc[0]), enc[0]
        except UnicodeDecodeError:
            continue
    return blob.decode("cp932", "replace"), "cp932"


def _html_to_text(page: str) -> str:
    import html as _html
    page = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|br|td|th)>", "\n", page)
    page = re.sub(r"(?i)<br\s*/?>", "\n", page)
    page = re.sub(r"<[^>]+>", " ", page)
    text = _html.unescape(page)
    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _http_get(url: str, timeout: int = 180) -> tuple[bytes, dict, int]:
    req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定官方 URL
        return resp.read(), {k.lower(): v for k, v in resp.headers.items()}, resp.status


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 抓取
def fetch_license_evidence(force: bool = False) -> dict:
    """许可证据：厚労省「利用規約・著作権」页 + PDL1.0 原文 + 薬価リスト页原文。"""
    LICENSE_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []

    def grab(name: str, url: str, target: Path) -> tuple[bytes, bool]:
        if target.exists() and not force:
            blob = target.read_bytes()
            items.append({"name": name, "url": url, "path": str(target), "cached": True,
                          "bytes": len(blob), "sha256": _sha256_bytes(blob)})
            return blob, True
        try:
            blob, headers, status = _http_get(url, timeout=120)
            target.write_bytes(blob)
            items.append({"name": name, "url": url, "path": str(target), "cached": False,
                          "bytes": len(blob), "sha256": _sha256_bytes(blob),
                          "http_status": status, "headers": headers})
            return blob, True
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            items.append({"name": name, "url": url, "path": str(target), "ok": False,
                          "error": f"{type(exc).__name__}: {exc}"})
            return b"", False

    copy_html = LICENSE_DIR / "mhlw_chosakuken.html"
    copy_txt = LICENSE_DIR / "mhlw_chosakuken.txt"
    copy_terms = LICENSE_DIR / "mhlw_terms_pdl.txt"
    blob, ok = grab("mhlw_copyright", COPYRIGHT_PAGE, copy_html)
    if ok and blob:
        page = blob.decode("utf-8", "replace")
        text = _html_to_text(page)
        copy_txt.write_text(text, encoding="utf-8")
        start = text.find("当ホームページで公開している情報")
        end = text.find("リンクについて", start + 10)
        section = text[start:end if end > start else start + 4000]
        copy_terms.write_text(section.strip() + "\n", encoding="utf-8")

    pdl_html = LICENSE_DIR / "pdl_1.0.html"
    pdl_txt = LICENSE_DIR / "pdl_1.0.txt"
    blob, ok = grab("pdl_1_0", PDL_URL, pdl_html)
    if ok and blob:
        page, enc = _decode_page(blob)
        pdl_txt.write_text(_html_to_text(page), encoding="utf-8")

    list_html = LICENSE_DIR / "yakka_list_page.html"
    list_txt = LICENSE_DIR / "yakka_list_page.txt"
    blob, ok = grab("yakka_list_page", LIST_PAGE, list_html)
    if ok and blob:
        page, enc = _decode_page(blob)
        text = _html_to_text(page)
        list_txt.write_text(text, encoding="utf-8")
        m = re.search(r"令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日", text)
        date_label = m.group(0) if m else ""
    else:
        date_label = ""
    has_terms = bool(copy_terms.exists() and "PDL1.0" in copy_terms.read_text(encoding="utf-8"))
    return {"items": items, "ok": has_terms and pdl_html.exists(), "date_label": date_label}


def fetch_file(key: str, force: bool = False) -> dict:
    spec = FILES[key]
    target = RAW / spec["name"]
    meta: dict = {"key": key, "name": spec["name"], "kubun": spec["kubun"],
                  "url": FILE_URL.format(name=spec["name"])}
    if target.exists() and not force:
        blob = target.read_bytes()
        meta.update({"cached": True, "bytes": len(blob), "sha256": _sha256_bytes(blob)})
    else:
        blob, headers, status = _http_get(FILE_URL.format(name=spec["name"]))
        if not blob:
            raise SystemExit(f"{spec['name']} 抓取返回 0 字节，中止（不覆盖缓存）")
        tmp = target.with_name(target.name + ".part")
        tmp.write_bytes(blob)
        tmp.replace(target)
        meta.update({"cached": False, "bytes": len(blob), "sha256": _sha256_bytes(blob),
                     "http_status": status, "headers": headers})
    wb = openpyxl.load_workbook(io.BytesIO(target.read_bytes()), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    it = ws.iter_rows(values_only=True)
    header = next(it)
    rows = [r for r in it if r and any(x not in (None, "") for x in r)]
    wb.close()
    meta.update({"sheet": wb.sheetnames[0], "header_columns": len(header),
                 "rows": len(rows), "fetched_at": _now()})
    if len(header) != COLUMNS:
        raise SystemExit(f"{spec['name']} 列数 {len(header)} ≠ 预期 {COLUMNS}")
    return meta


def cmd_fetch(args: argparse.Namespace) -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    print("=== JP 薬価基準収載品目リスト 抓取 ===")
    print(f"  列表页 {LIST_PAGE}")
    ev = fetch_license_evidence(force=args.force)
    print(f"  许可: 厚労省条款 {'✓' if ev['ok'] else '✗'} · 页面日期标记 {ev.get('date_label')!r}")
    files = []
    for key in FILES:
        meta = fetch_file(key, force=args.force)
        files.append(meta)
        print(f"  {key:7s} {meta['bytes']:>10,} B · {meta['rows']:>6,} 行 · "
              f"{meta['header_columns']} 列 · sha256 {meta['sha256'][:16]}…")
    total = sum(f["rows"] for f in files)
    payload = {
        "source_id": SOURCE_ID, "country": COUNTRY, "list_page": LIST_PAGE,
        "list_date": LIST_DATE, "fetched_at": _now(),
        "licence": {
            "id": "PDL1.0", "name": "公共データ利用規約（第1.0版）",
            "url": PDL_URL, "site_terms": COPYRIGHT_PAGE,
            "can_redistribute": True,
            "obligations": ["注明出处（厚生労働省 + 页面 URL）", "加工后注明「加工して作成」",
                            "不得让人误以为是政府作成", "logo/象征标记不在许可范围"],
            "evidence_dir": str(LICENSE_DIR.relative_to(ROOT)),
            "evidence": ev,
        },
        "files": files, "rows_total": total,
        "note": PAGE_NOTE + "；4 个 Excel 各自「現在品目を反映」日期不同，以 list_date 为准。",
    }
    _write_json(FETCH_META, payload)
    print(f"  合计 {total:,} 品目 · 证据 {LICENSE_DIR.relative_to(ROOT)} · 元数据 {FETCH_META.relative_to(ROOT)}")
    print(f"  耗时 {round(time.perf_counter() - t0, 1)}s")
    return 0 if ev["ok"] and total > 12000 else 1


# ---------------------------------------------------------------- 解析：Excel
def load_snapshot(raw: Path = RAW) -> dict:
    rows: list[dict] = []
    stats: Counter = Counter()
    for key, spec in FILES.items():
        path = raw / spec["name"]
        if not path.exists():
            raise SystemExit(f"缺快照：{path}（先跑 `python etl/markets/jp.py --fetch`）")
        wb = openpyxl.load_workbook(io.BytesIO(path.read_bytes()), read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        it = ws.iter_rows(values_only=True)
        header = next(it)
        if len(header) != COLUMNS:
            raise SystemExit(f"{spec['name']} 列数 {len(header)} ≠ {COLUMNS}")
        for lineno, r in enumerate(it, start=2):
            if not r or all(x in (None, "") for x in r):
                continue
            code = nfkc(r[COL["code"]])
            if not code:
                stats["rows_without_code"] += 1
                continue
            stats["rows"] += 1
            rows.append({
                "file": key, "kubun": nfkc(r[COL["kubun"]]), "code": code,
                "ingredient": nfkc(r[COL["ingredient"]]), "spec": nfkc(r[COL["spec"]]),
                "name": nfkc(r[COL["name"]]), "maker": nfkc(r[COL["maker"]]),
                "generic_addon": nfkc(r[COL["generic_addon"]]),
                "senpatsu": nfkc(r[COL["senpatsu"]]),
                "senpatsu2": nfkc(r[COL["senpatsu2"]]),
                "price_raw": r[COL["price"]], "expiry": nfkc(r[COL["expiry"]]),
                "note": nfkc(r[COL["note"]]),
                "lineno": lineno,
            })
        wb.close()
    stats["files"] = len(FILES)
    return {"rows": rows, "stats": dict(stats)}


# ---------------------------------------------------------------- 解析：規格
UNIT = (r"(?:mg|g|mcg|mL|L|%|IU|単位|国際単位|万単位|万IU|GBq|MBq|kBq|Bq|mol|mmol|mEq|"
        r"cm|mm|JAU|TBq|Ci)")
RE_STRENGTH = re.compile(r"^(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>" + UNIT + r")", re.I)
RE_SECOND = re.compile(r"^(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>mL|L|g)", re.I)
RE_PACK = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)?\s*(?P<unit>錠|カプセル|管|瓶|袋|包|枚|個|本|シート|キット|セット|"
    r"筒|バイアル|アンプル|回分|吸入|mL|g|L)$")
_UNIT_CANON = {
    "mg": "mg", "g": "g", "mcg": "mcg", "ml": "mL", "l": "L", "%": "%", "iu": "IU",
    "単位": "unit", "国際単位": "IU", "万単位": "10k unit", "万iu": "10k IU",
    "gbq": "GBq", "mbq": "MBq", "kbq": "kBq", "bq": "Bq", "mol": "mol", "mmol": "mmol",
    "meq": "mEq", "jau": "JAU", "tbq": "TBq", "ci": "Ci",
}


def parse_spec(spec: str) -> dict:
    """`規格` → {value, unit, per_volume_value, per_volume_unit, pack, pack_unit, dimension}。

    `10mg1錠` = 10 mg / 1 錠；`500mL1袋` = 500 mL / 1 袋；`100mg5mL1瓶` = 100 mg / 5 mL / 1 瓶；
    `10cm×14cm1枚` = 尺寸（不是剂量）；`1錠` = 只有包装数量（没有数值剂量）。
    """
    s = nfkc(spec).replace(",", "").replace("，", "")
    out = {"value": None, "unit": None, "per_volume_value": None, "per_volume_unit": None,
           "pack_value": None, "pack_unit": None, "dimension": False}
    m = RE_STRENGTH.match(s)
    if m:
        try:
            out["value"] = float(m.group("val"))
        except ValueError:
            out["value"] = None
        out["unit"] = _UNIT_CANON.get(m.group("unit").lower(), m.group("unit"))
        rest = s[m.end():]
        m2 = RE_SECOND.match(rest)
        if m2:
            try:
                out["per_volume_value"] = float(m2.group("val"))
            except ValueError:
                out["per_volume_value"] = None
            out["per_volume_unit"] = _UNIT_CANON.get(m2.group("unit").lower(), m2.group("unit"))
            rest = rest[m2.end():]
        # 尾部包装：`1錠` / `1瓶(溶解液付)` 等
        rest_clean = re.sub(r"\(.*?\)$", "", rest).strip()
        mp = RE_PACK.search(rest_clean)
        if mp:
            out["pack_unit"] = mp.group("unit")
            if mp.group("num"):
                try:
                    out["pack_value"] = float(mp.group("num"))
                except ValueError:
                    pass
    else:
        mp = RE_PACK.search(s)
        if mp:
            out["pack_unit"] = mp.group("unit")
            if mp.group("num"):
                try:
                    out["pack_value"] = float(mp.group("num"))
                except ValueError:
                    pass
    if re.search(r"\d+(?:\.\d+)?\s*(?:cm|mm)\s*[×x]\s*\d+(?:\.\d+)?\s*(?:cm|mm)", s):
        out["dimension"] = True
        out["value"], out["unit"] = None, None   # 尺寸不是剂量
    return out


# ---------------------------------------------------------------- 解析：剂型 / 途径
FORM_MAP = [
    ("口腔内崩壊錠", "tablet"), ("フィルムコーティング錠", "tablet"), ("腸溶錠", "tablet"),
    ("徐放錠", "tablet"), ("持続性錠", "tablet"), ("錠", "tablet"),
    ("カプセル", "capsule"), ("顆粒", "powder"), ("細粒", "powder"),
    ("ドライシロップ", "powder"), ("散", "powder"),
    ("シロップ", "liquid"), ("懸濁液", "liquid"), ("エリキシル", "liquid"),
    ("注射液", "injection"), ("注射", "injection"), ("点滴", "injection"), ("輸液", "injection"),
    ("シリンジ", "injection"), ("静注", "injection"), ("注", "injection"),
    ("軟膏", "topical"), ("クリーム", "topical"), ("ゲル", "topical"), ("ローション", "topical"),
    ("テープ", "transdermal"), ("貼付", "transdermal"), ("パップ", "topical"),
    ("組織接着用", "topical"),
    ("点眼", "ophthalmic"), ("点鼻", "nasal"),
    ("坐剤", "suppository"), ("浣腸", "rectal"),
    ("吸入", "inhalation"), ("エアロゾル", "inhalation"),
]
KUBUN_FALLBACK = {"内用薬": "other", "注射薬": "injection", "外用薬": "other", "歯科用薬剤": "other"}


def derive_form(name: str, kubun: str) -> tuple[str, str]:
    """品名 → (form_base, method)；method = name / kubun / none。"""
    for needle, base in FORM_MAP:
        if needle in name:
            return base, "name"
    base = KUBUN_FALLBACK.get(kubun)
    if base:
        return base, "kubun"
    return "other", "none"


# ---------------------------------------------------------------- 解析：成分（片假名 → INN）
KANA = {
    "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o", "カ": "ka", "キ": "ki", "ク": "ku",
    "ケ": "ke", "コ": "ko", "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so",
    "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to", "ナ": "na", "ニ": "ni",
    "ヌ": "nu", "ネ": "ne", "ノ": "no", "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he",
    "ホ": "ho", "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo", "ヤ": "ya",
    "ユ": "yu", "ヨ": "yo", "ラ": "ra", "リ": "ri", "ル": "ru", "レ": "re", "ロ": "ro",
    "ワ": "wa", "ヲ": "o", "ン": "n", "ガ": "ga", "ギ": "gi", "グ": "gu", "ゲ": "ge",
    "ゴ": "go", "ザ": "za", "ジ": "ji", "ズ": "zu", "ゼ": "ze", "ゾ": "zo", "ダ": "da",
    "ヂ": "ji", "ヅ": "zu", "デ": "de", "ド": "do", "バ": "ba", "ビ": "bi", "ブ": "bu",
    "ベ": "be", "ボ": "bo", "パ": "pa", "ピ": "pi", "プ": "pu", "ペ": "pe", "ポ": "po",
    "ヴ": "bu", "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o", "ャ": "ya",
    "ュ": "yu", "ョ": "yo", "ッ": "", "ー": "", "ヵ": "ka", "ヶ": "ke",
}
DIGRAPH = {"キャ": "kya", "キュ": "kyu", "キョ": "kyo", "シャ": "sha", "シュ": "shu", "ショ": "sho",
           "チャ": "cha", "チュ": "chu", "チョ": "cho", "ニャ": "nya", "ニュ": "nyu", "ニョ": "nyo",
           "ヒャ": "hya", "ヒュ": "hyu", "ヒョ": "hyo", "ミャ": "mya", "ミュ": "myu", "ミョ": "myo",
           "リャ": "rya", "リュ": "ryu", "リョ": "ryo", "ギャ": "gya", "ギュ": "gyu", "ギョ": "gyo",
           "ジャ": "ja", "ジュ": "ju", "ジョ": "jo", "ビャ": "bya", "ビュ": "byu", "ビョ": "byo",
           "ピャ": "pya", "ピュ": "pyu", "ピョ": "pyo", "ファ": "fa", "フィ": "fi", "フェ": "fe",
           "フォ": "fo", "ティ": "ti", "ディ": "di", "デュ": "du", "トゥ": "tu", "ドゥ": "du",
           "チェ": "che", "シェ": "she", "ジェ": "je", "ツィ": "ti", "ウィ": "ui", "ウェ": "ue",
           "ウォ": "uo"}
SALT_JP = ["塩酸塩", "硫酸塩", "硝酸塩", "リン酸塩", "酢酸塩", "コハク酸塩", "フマル酸塩",
           "酒石酸塩", "クエン酸塩", "マレイン酸塩", "メシル酸塩", "ベシル酸塩", "トシル酸塩",
           "水和物", "無水物", "ナトリウム", "カリウム", "カルシウム", "マグネシウム",
           "アンモニウム", "塩化物", "臭化物", "ヨウ化物", "エステル"]
JP_ACID = {"酸": "acid", "尿素": "urea", "糖": "sugar"}


def kata_to_romaji(text: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        two = text[i:i + 2]
        if two in DIGRAPH:
            out.append(DIGRAPH[two])
            i += 2
            continue
        out.append(KANA.get(text[i], text[i]))
        i += 1
    return "".join(out)


def phonetic_skeleton(text: str) -> str:
    """日式转写与英文 INN 的常见对应合并后取辅音骨架（只用于候选比较，不写库）。"""
    s = text.lower()
    for a, b in (("ph", "f"), ("sh", "s"), ("ch", "t"), ("ts", "t"), ("th", "t"),
                 ("wh", "b"), ("ck", "k"), ("qu", "k"), ("x", "ks"), ("q", "k")):
        s = s.replace(a, b)
    s = (s.replace("l", "r").replace("v", "b").replace("j", "d").replace("z", "s")
         .replace("c", "k").replace("g", "k").replace("y", "i").replace("w", "b")
         .replace("h", ""))
    s = re.sub(r"[^a-z]", "", s)
    return re.sub(r"[aeiou]", "", s)


# 辅音等价类：日文转写在一组内可互换（c/s、t/s、r/l、b/v、d/z/j、k/g、f/h 已在骨架里处理）
EQUIV = {"k": "ks", "s": "sk", "t": "ts", "r": "rl", "b": "bv", "d": "dzjs",
         "z": "dzjs", "j": "dzjs", "g": "kg", "f": "fh", "l": "rl", "v": "bv"}


def _skeleton_variants(skel: str) -> set[str]:
    """生成骨架的等价写法（用于宽松比较，仍要求整串一致）。"""
    out = {skel}
    for i, ch in enumerate(skel):
        opts = EQUIV.get(ch)
        if not opts:
            continue
        for alt in opts:
            if alt == ch:
                continue
            out.add(skel[:i] + alt + skel[i + 1:])
    return out


JP_KANJI_INGREDIENTS = {
    "ブドウ糖": "glucose", "葡萄糖": "glucose", "生理食塩液": "sodium chloride",
    "食塩": "sodium chloride", "塩化ナトリウム": "sodium chloride",
    "精製水": "water for injection", "注射用水": "water for injection",
}


def strip_jp_salts(text: str) -> str:
    s = nfkc(text)
    for salt in SALT_JP:
        s = s.replace(salt, "")
    for jp, en in JP_ACID.items():
        s = s.replace(jp, en)
    return s.strip(" ・,、")


def split_ingredients(text: str) -> list[str]:
    """`成分名` → token（复方用 `・` 分隔；空/`-` 归零）。"""
    t = nfkc(text)
    if not t or t in {"-", "－"}:
        return []
    return [x.strip() for x in re.split(r"[・･]", t) if x.strip()]


class JpMapper:
    """日文成分名 → substance_id：片假名→罗马字→音韵骨架，对库内 `inn_en` 唯一命中才接受。"""

    def __init__(self, db: sqlite3.Connection):
        self.by_skel: dict[str, list[tuple[str, str]]] = {}
        for sid, inn in db.execute("SELECT substance_id, inn_en FROM substance"):
            if not re.search(r"[A-Za-z]", inn or ""):
                continue          # 库里有一部分 inn_en 是中文（CN 市场主名），不能参与音韵匹配
            skel = phonetic_skeleton(inn)
            if len(skel) < 3:
                continue
            self.by_skel.setdefault(skel, []).append((sid, inn))
        self.memo: dict[str, tuple[str, str]] = {}

    @staticmethod
    def _pick(cands: list[tuple[str, str]]) -> tuple[str, str] | None:
        """多候选时只在「有一个基名是其余候选的前缀」（Donepezil / Donepezil Hydrochloride）
        这种安全情形下取基名；否则返回 None（不猜）。"""
        if len(cands) == 1:
            return cands[0]
        bases = [c for c in cands
                 if all(o[1].lower().startswith(c[1].lower() + " ") or o[1] == c[1]
                        for o in cands)]
        return bases[0] if len(bases) == 1 else None

    def map(self, token: str) -> tuple[str, str]:
        """token → (substance_id, method)；未映射返回 ("", "unmapped")。"""
        if token in self.memo:
            return self.memo[token]
        kanji = JP_KANJI_INGREDIENTS.get(nfkc(token))
        if kanji:
            picked = self._pick(self.by_skel.get(phonetic_skeleton(kanji)) or [])
            if picked:
                self.memo[token] = (picked[0], "jp-kanji-dict")
                return self.memo[token]
        core = strip_jp_salts(token)
        result = ("", "unmapped")
        if core:
            skel = phonetic_skeleton(kata_to_romaji(core))
            if skel:
                picked = self._pick(self.by_skel.get(skel) or [])
                if picked:
                    result = (picked[0], "katakana-skeleton")
                elif self.by_skel.get(skel):
                    result = ("", "ambiguous")
                else:
                    for alt in _skeleton_variants(skel):
                        picked = self._pick(self.by_skel.get(alt) or [])
                        if picked:
                            result = (picked[0], "katakana-skeleton-equiv")
                            break
                    else:
                        result = ("", "unmapped")
        self.memo[token] = result
        return result


# ---------------------------------------------------------------- dry-run
def _product_id(code: str) -> str:
    return f"{COUNTRY}-{re.sub(r'[^0-9A-Za-z]', '', code) or 'urn'}"


def _collect(snap: dict, mapper: JpMapper, resolve) -> dict:
    st: Counter = Counter()
    forms: Counter = Counter()
    routes: Counter = Counter()
    kubuns: Counter = Counter()
    forms_method: Counter = Counter()
    unmapped: Counter = Counter()
    unmapped_occ: Counter = Counter()
    units: Counter = Counter()
    pack_units: Counter = Counter()
    flags: Counter = Counter()
    makers: Counter = Counter()
    products: list[dict] = []
    name_keys: set[str] = set()
    name_pairs: set[tuple[str, str]] = set()
    components_planned = 0
    components_with_strength = 0
    products_all_mapped = 0
    products_partial = 0
    products_none = 0
    components_no_variant = 0
    spec_numeric = 0
    spec_dimension = 0
    status_by_expiry = 0
    samples: list[dict] = []
    seen_codes: set[str] = set()
    for row in snap["rows"]:
        code, name, kubun = row["code"], row["name"], row["kubun"]
        st["rows"] += 1
        if code in seen_codes:
            st["dup_code_rows"] += 1
        seen_codes.add(code)
        kubuns[kubun] += 1
        if row["maker"]:
            makers[row["maker"]] += 1
        form_base, form_method = derive_form(name, kubun)
        forms_method[form_method] += 1
        forms[form_base] += 1
        spec = parse_spec(row["spec"])
        if spec["value"] is not None:
            spec_numeric += 1
            units[spec["unit"] or "(无单位)"] += 1
            if spec["per_volume_unit"]:
                st["spec_with_per_volume"] += 1
        elif spec["dimension"]:
            spec_dimension += 1
        if spec["pack_unit"]:
            pack_units[spec["pack_unit"]] += 1
        # 状态：薬価基準収載 = 收载；経過措置非空 = 过渡期（将剔除）
        if row["expiry"]:
            status = "discontinued"
            status_by_expiry += 1
        else:
            status = "active"
        # 先発/後発
        if row["senpatsu"]:
            flags["senpatsu"] += 1
            is_branded = 1
        elif row["generic_addon"]:
            flags["generic_addon"] += 1
            is_branded = 0
        else:
            flags["unknown"] += 1
            is_branded = 1
        # 成分
        tokens = split_ingredients(row["ingredient"])
        mapped: list[tuple[str, str, str]] = []
        for token in tokens:
            sid, method = mapper.map(token)
            st["ingredient_tokens"] += 1
            if sid:
                st["ingredient_tokens_mapped"] += 1
            unmapped_occ[method] += 1
            mapped.append((token, sid, method))
        n_map = sum(1 for _t, sid, _m in mapped if sid)
        if mapped and n_map == len(mapped):
            products_all_mapped += 1
        elif mapped and n_map:
            products_partial += 1
        else:
            products_none += 1
        planned = []
        for token, sid, method in mapped:
            if not sid:
                if method not in {"ambiguous"}:
                    unmapped[token] += 1
                continue
            vid = resolve(sid, token)
            if not vid:
                components_no_variant += 1
                continue
            components_planned += 1
            strength = None
            if spec["value"] is not None:
                strength = {"value": spec["value"], "unit": spec["unit"],
                            "per_volume_value": spec["per_volume_value"],
                            "per_volume_unit": spec["per_volume_unit"]}
                components_with_strength += 1
            planned.append({"token": token, "substance_id": sid, "variant_id": vid,
                            "method": method, "strength": strength})
        nm = normalize(name)
        if not nm.is_empty:
            name_keys.add(nm.norm)
            name_pairs.add((nm.norm, name))
        pid = _product_id(code)
        price = row["price_raw"]
        try:
            price_val = float(price) if price is not None and str(price).strip() else None
        except (TypeError, ValueError):
            price_val = None
        products.append({
            "product_id": pid, "code": code, "name": name, "name_norm":
                "" if nm.is_empty else nm.norm, "kubun": kubun, "form_base": form_base,
            "form_method": form_method, "release": "none",
            "spec_raw": row["spec"], "spec": spec, "maker": row["maker"],
            "ingredient_raw": row["ingredient"], "ingredient_tokens": tokens,
            "price": price_val, "status": status, "expiry": row["expiry"],
            "is_branded": is_branded, "senpatsu": row["senpatsu"],
            "generic_addon": row["generic_addon"], "note": row["note"],
            "components": planned,
            "substance_ids": sorted({c["substance_id"] for c in planned}),
            "unmapped_tokens": [t for t, sid, _m in mapped if not sid],
        })
        if len(samples) < 8:
            samples.append({
                "code": code, "name": name, "kubun": kubun, "form_base": form_base,
                "form_method": form_method, "spec_raw": row["spec"], "spec": spec,
                "ingredient": row["ingredient"], "maker": row["maker"],
                "price": price_val, "status": status,
                "components": [{"token": c["token"], "sid": c["substance_id"],
                                "method": c["method"], "strength": c["strength"]}
                               for c in planned],
                "unmapped": [t for t, sid, _m in mapped if not sid],
            })

    st["products"] = len(products)
    st["spec_numeric"] = spec_numeric
    st["spec_dimension"] = spec_dimension
    st["components_planned"] = components_planned
    st["components_with_strength"] = components_with_strength
    st["components_no_variant"] = components_no_variant
    st["products_all_mapped"] = products_all_mapped
    st["products_partial_mapped"] = products_partial
    st["products_none_mapped"] = products_none
    st["status_discontinued_expiry"] = status_by_expiry
    st["unique_makers"] = len(makers)
    st["unique_ingredients"] = len({r["ingredient"] for r in snap["rows"]})
    return {
        "stats": st, "products": products, "forms": forms, "forms_method": forms_method,
        "routes": routes, "kubuns": kubuns, "unmapped": unmapped, "unmapped_method": unmapped_occ,
        "units": units, "pack_units": pack_units, "flags": flags, "makers": makers,
        "name_keys": name_keys, "name_pairs": name_pairs, "samples": samples,
    }


def prepare_copy(real: Path, copy: Path, force: bool = False) -> dict:
    if not real.exists():
        raise SystemExit(f"真库不存在：{real}")
    WORK.mkdir(parents=True, exist_ok=True)
    if copy.exists() and not force:
        if copy.stat().st_size == real.stat().st_size:
            return {"path": str(copy), "bytes": copy.stat().st_size, "copied": False}
        copy.unlink()
    t0 = time.perf_counter()
    tmp = copy.with_name(copy.name + ".part")
    shutil.copyfile(real, tmp)
    tmp.replace(copy)
    return {"path": str(copy), "bytes": copy.stat().st_size, "copied": True,
            "seconds": round(time.perf_counter() - t0, 1)}


def cmd_prepare_copy(args: argparse.Namespace) -> int:
    info = prepare_copy(REAL_DB, DB_COPY, force=args.force)
    print(f"拷贝就绪：{info['path']} · {info['bytes']:,} B · "
          f"{'新拷贝' if info.get('copied') else '复用现有副本'}")
    return 0


def _inn_overlap(db: sqlite3.Connection, products: list[dict]) -> dict:
    """与既有 10 国按 INN（substance）去重说明：日本新增了哪些成分、与哪些国家重叠。"""
    sids = {s for p in products for s in p["substance_ids"]}
    if not sids:
        return {"mapped_substances": 0}
    marks = [r[0] for r in db.execute(
        "SELECT DISTINCT COALESCE(p.country, p.region) FROM product p "
        "JOIN product_component pc ON pc.product_id = p.product_id "
        "JOIN variant v ON v.variant_id = pc.variant_id GROUP BY 1")]
    per_market: dict[str, int] = {}
    for m in marks:
        q = ", ".join("?" * len(sids))
        n = db.execute(
            f"SELECT COUNT(DISTINCT v.substance_id) FROM product p "
            f"JOIN product_component pc ON pc.product_id = p.product_id "
            f"JOIN variant v ON v.variant_id = pc.variant_id "
            f"WHERE COALESCE(p.country, p.region)=? AND v.substance_id IN ({q})",
            [m, *sids]).fetchone()[0]
        per_market[m] = n
    return {
        "mapped_substances": len(sids),
        "markets_seen": per_market,
        "note": "JP 与既有 10 国共享 INN 时才可能跨市场对上；日本非 EU，与 region='EU' 无直接关系。",
    }


def cmd_dry_run(args: argparse.Namespace) -> int:
    src = args.src if args.src.is_absolute() else (ROOT / args.src)
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    if db_path.resolve() == REAL_DB.resolve():
        raise SystemExit("拒绝在真库上干跑：请用 `.tmp/jp-ingest/` 的库副本（或加 --copy）")
    if not db_path.exists():
        if not args.copy:
            raise SystemExit(f"库副本不存在：{db_path}（加 --copy 先复制真库，或跑 --prepare-copy）")
        info = prepare_copy(REAL_DB, db_path)
        print(f"  已复制真库 → {db_path} · {info['bytes']:,} B")
    t0 = time.perf_counter()
    snap = load_snapshot(src)
    fetch_meta = {}
    if (src / "fetch_meta.json").exists():
        fetch_meta = json.loads((src / "fetch_meta.json").read_text(encoding="utf-8"))
    db = _connect_ro(db_path)
    try:
        mapper = JpMapper(db)
        resolve = _variant_resolver(db)
        existing_keys = {r[0] for r in db.execute("SELECT key_id FROM name_key")}
        existing_pairs = {(r[0], r[1]) for r in db.execute("SELECT key_id, raw FROM name_variant")}
        db_products = db.execute("SELECT COUNT(*) FROM product").fetchone()[0]
        result = _collect(snap, mapper, resolve)
        overlap = _inn_overlap(db, result["products"])
        # JP 独占成分：在库里没有任何产品用到的 substance
        sids = sorted({s for p in result["products"] for s in p["substance_ids"]})
        jp_only = []
        for sid in sids:
            n = db.execute(
                "SELECT COUNT(*) FROM product_component WHERE variant_id IN "
                "(SELECT variant_id FROM variant WHERE substance_id=?)", (sid,)).fetchone()[0]
            if n == 0:
                jp_only.append(sid)
    finally:
        db.close()
    elapsed = round(time.perf_counter() - t0, 2)

    st = result["stats"]
    new_keys = sorted(result["name_keys"] - existing_keys)
    new_variants = sorted(p for p in result["name_pairs"] if p not in existing_pairs)
    n_rows = max(1, st["products"])
    n_tok = max(1, st["ingredient_tokens"])

    summary = {
        "generated_at": _now(),
        "tool": "etl/markets/jp.py",
        "mode": "dry-run（只读；库副本，不写库）",
        "licence": {
            "source_id": SOURCE_ID,
            "status": "✅ A 类：厚労省站点条款 + 公共データ利用規約 1.0（PDL1.0），可再发布需署名",
            "can_ingest": True,
            "obligations": ["注明出处（厚生労働省 + 页面 URL）", "加工后注明「加工して作成」",
                            "不得让人误以为是政府作成"],
            "apply_flag": "本脚本不提供 --apply（ja 语言 / JP 市场尚未接入）",
        },
        "scope": {
            "what": "薬価基準収載品目リスト（医保收载/药价基准）",
            "not_what": "不是日本上市注册库；不等于该国全部上市药品；収載 ≠ 当前在售",
            "page_wording": PAGE_NOTE,
        },
        "db": {"path": str(db_path), "mode": "read-only(mode=ro)", "products": db_products,
               "is_real_db": False},
        "snapshot": {
            "dir": str(src.relative_to(ROOT)) if src.is_relative_to(ROOT) else str(src),
            "files": {f["key"]: {"name": f["name"], "bytes": f["bytes"],
                                   "sha256": f["sha256"], "rows": f["rows"]}
                      for f in (fetch_meta.get("files") or [])},
            "rows_total": st["rows"], "list_date": LIST_DATE,
        },
        "rows": {
            "items": st["products"],
            "unique_codes": len({p["code"] for p in result["products"]}),
            "dup_code_rows": st["dup_code_rows"],
            "unique_names": len({p["name"] for p in result["products"]}),
            "unique_ingredients": st["unique_ingredients"],
            "kubun": result["kubuns"].most_common(),
        },
        "dosage_form": {
            "form_base": result["forms"].most_common(15),
            "derived_from_name": result["forms_method"].get("name", 0),
            "derived_from_name_pct": round(result["forms_method"].get("name", 0) / n_rows * 100, 1),
            "fallback_kubun": result["forms_method"].get("kubun", 0),
            "fallback_kubun_pct": round(result["forms_method"].get("kubun", 0) / n_rows * 100, 1),
            "none": result["forms_method"].get("none", 0),
            "note": "BDPM 式「剂型列」不存在：品名尾缀派生优先，`区分` 兜底（注射薬→injection，其余→other）",
        },
        "strength": {
            "source": "`規格`（NFKC 后解析）；药剂单位 + 每包装数量分开存",
            "numeric": st["spec_numeric"],
            "numeric_pct": round(st["spec_numeric"] / n_rows * 100, 1),
            "with_per_volume": st["spec_with_per_volume"],
            "dimension_only": st["spec_dimension"],
            "units_top": result["units"].most_common(12),
            "pack_units_top": result["pack_units"].most_common(10),
            "components_with_strength": st["components_with_strength"],
            "components_total": st["components_planned"],
            "components_with_strength_pct": round(
                st["components_with_strength"] / max(1, st["components_planned"]) * 100, 1),
            "note": "`1錠` / `1瓶` / `10cm×14cm` 这类只有包装或尺寸的规格不当剂量（留空）",
        },
        "substance": {
            "tokens": st["ingredient_tokens"],
            "tokens_mapped": st["ingredient_tokens_mapped"],
            "token_rate_pct": round(st["ingredient_tokens_mapped"] / n_tok * 100, 1),
            "unique_unmapped": len(result["unmapped"]),
            "unmapped_top30": result["unmapped"].most_common(30),
            "method": result["unmapped_method"].most_common(8),
            "products_all_mapped": st["products_all_mapped"],
            "products_partial_mapped": st["products_partial_mapped"],
            "products_none_mapped": st["products_none_mapped"],
            "bridge": "日文片假名成分名 → 罗马字 → 音韵辅音骨架 → 库内 inn_en 唯一命中；"
                      "盐名（塩酸塩/ナトリウム…）先剥离；多候选/未命中一律空着（不猜）",
        },
        "status": {
            "active": st["products"] - st["status_discontinued_expiry"],
            "discontinued_expiry": st["status_discontinued_expiry"],
            "rule": "薬価基準収載 = 收载（全部行）；`経過措置による使用期限` 非空的 196 行是过渡期品目，"
                    "按 discontinued 记（不是「已撤市」的等价说法）",
        },
        "flags": {
            "senpatsu": result["flags"].get("senpatsu", 0),
            "generic_addon": result["flags"].get("generic_addon", 0),
            "unknown": result["flags"].get("unknown", 0),
            "is_branded_1": sum(1 for p in result["products"] if p["is_branded"] == 1),
        },
        "inn_overlap": overlap,
        "jp_only_substances": len(jp_only),
        "would_write": {
            "products": st["products"],
            "components": st["components_planned"],
            "components_no_variant": st["components_no_variant"],
            "product_names": st["products"],
            "name_keys_new": len(new_keys),
            "name_variants_new": len(new_variants),
            "substance_new": 0,
            "note": "**只是预测**：本脚本没有任何写库路径；不新增 substance",
        },
        "samples": result["samples"],
        "elapsed_s": elapsed,
    }
    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / "jp_dry_run.json"
    out.write_text(json.dumps({k: v for k, v in summary.items() if k != "samples"},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    (WORK / "jp_samples.json").write_text(
        json.dumps(summary["samples"], ensure_ascii=False, indent=1), encoding="utf-8")

    print("=== JP 薬価基準 dry-run（只读；库副本，不写库）===")
    print(f"  口径: {PAGE_NOTE}")
    print(f"  许可: ✅ PDL1.0（厚労省站点条款）；本脚本没有 --apply")
    print(f"  快照: {summary['snapshot']['dir']} · 品目 {st['products']:,}"
          f" · 区分 {result['kubuns'].most_common()}")
    print(f"  规格: 数值 {st['spec_numeric']:,}（{summary['strength']['numeric_pct']}%）"
          f" · 含每包装分母 {st['spec_with_per_volume']:,} · 仅尺寸 {st['spec_dimension']:,}"
          f" · 单位 top {result['units'].most_common(6)}")
    print(f"  剂型: 品名派生 {summary['dosage_form']['derived_from_name_pct']}%"
          f" · 区分兜底 {summary['dosage_form']['fallback_kubun_pct']}%"
          f" · 分布 {result['forms'].most_common(6)}")
    print(f"  成分映射: {st['ingredient_tokens_mapped']:,}/{st['ingredient_tokens']:,} = "
          f"{summary['substance']['token_rate_pct']}% · 未映射写法 {len(result['unmapped']):,}"
          f" · top5 {[x[0] for x in result['unmapped'].most_common(5)]}")
    print(f"  状态: active {summary['status']['active']:,} · 过渡期(経過措置) "
          f"{summary['status']['discontinued_expiry']:,}")
    print(f"  先発/後発: 先発品 {summary['flags']['senpatsu']:,} · 後発加算 {summary['flags']['generic_addon']:,}"
          f" · 未标注 {summary['flags']['unknown']:,}")
    print(f"  INN 重叠: 映射到 substance {overlap['mapped_substances']:,} 个"
          f" · JP 独占（库内无产品）{len(jp_only):,} 个")
    print(f"  预计入库(仅预测): 产品 {st['products']:,} · component {st['components_planned']:,}"
          f" · name_key 新建 {len(new_keys):,} · name_variant 新建 {len(new_variants):,}"
          f" · substance 新增 0")
    print(f"  耗时 {elapsed}s · 汇总 {out.relative_to(ROOT)}")
    return 0


# ---------------------------------------------------------------- 自测
def self_check(raw: Path = RAW) -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, extra: str = "") -> None:
        print(f"  {'ok  ' if cond else 'FAIL'} {name}{('  ' + extra) if extra else ''}")
        if not cond:
            failures.append(name)

    meta_path = raw / "fetch_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        check("许可 id = PDL1.0", meta.get("licence", {}).get("id") == "PDL1.0")
        check("厚労省条款原文已落盘", (raw / "license" / "mhlw_terms_pdl.txt").exists())
        check("PDL1.0 原文已落盘", (raw / "license" / "pdl_1.0.html").exists())
        check("列表页原文已落盘", (raw / "license" / "yakka_list_page.txt").exists())
        check("品目数 = 12,442", meta.get("rows_total") == 12442, str(meta.get("rows_total")))
    else:
        check("fetch_meta.json 存在", False, f"缺 {meta_path}")

    snap = None
    if all((raw / spec["name"]).exists() for spec in FILES.values()):
        snap = load_snapshot(raw)
        check("4 个 Excel 行数合计 12,442", len(snap["rows"]) == 12442, f"{len(snap['rows']):,}")
        check("列数 15 且全行有コード", all(r["code"] for r in snap["rows"]))
        nfkc_row = next((r for r in snap["rows"] if "１" not in r["spec"] and r["spec"]), None)
        check("已做 NFKC（原表全角 → 半角）", nfkc_row is not None,
              nfkc_row["spec"] if nfkc_row else "")
        check("区分 4 类齐全", set(r["kubun"] for r in snap["rows"])
              == {"内用薬", "注射薬", "外用薬", "歯科用薬剤"},
              str(sorted(set(r["kubun"] for r in snap["rows"]))))
        check("薬価数值列非空", sum(1 for r in snap["rows"] if isinstance(r["price_raw"], (int, float)))
              == len(snap["rows"]))

    # NFKC
    check("NFKC 全角数字/单位", nfkc("１２ｍｇ１錠") == "12mg1錠", nfkc("１２ｍｇ１錠"))
    check("NFKC 全角标点", nfkc("Ｔ’ｓ製薬") == "T's製薬", nfkc("Ｔ’ｓ製薬"))
    # 規格
    cases = [
        ("10mg1錠", 10.0, "mg", None, None, "錠"),
        ("1g", 1.0, "g", None, None, None),
        ("100mg5mL1瓶", 100.0, "mg", 5.0, "mL", "瓶"),
        ("5%500mL1袋", 5.0, "%", 500.0, "mL", "袋"),
        ("1錠", None, None, None, None, "錠"),
        ("10cm×14cm1枚", None, None, None, None, "枚"),
    ]
    for spec, val, unit, pv, pu, pocket in cases:
        got = parse_spec(spec)
        ok = (got["value"] == val and got["unit"] == unit
              and got["per_volume_value"] == pv and got["per_volume_unit"] == pu
              and got["pack_unit"] == pocket)
        check(f"規格 {spec!r}", ok, str(got))
    # 剂型
    check("品名尾缀派生（錠）", derive_form("ユーロジン1mg錠", "内用薬")[0] == "tablet")
    check("品名尾缀派生（注射液）", derive_form("ソリューゲンG注", "注射薬")[0] == "injection")
    check("剂型兜底（区分 注射薬）", derive_form("大塚生食注", "注射薬")[0] == "injection")
    # 成分
    check("片假名→罗马字（エスタゾラム）", kata_to_romaji("エスタゾラム") == "esutazoramu",
          kata_to_romaji("エスタゾラム"))
    check("盐名剥离（ドネペジル塩酸塩）", strip_jp_salts("ドネペジル塩酸塩") == "ドネペジル",
          strip_jp_salts("ドネペジル塩酸塩"))
    check("复方按 ・ 拆分", split_ingredients("リドカイン塩酸塩・アドレナリン") ==
          ["リドカイン塩酸塩", "アドレナリン"],
          str(split_ingredients("リドカイン塩酸塩・アドレナリン")))
    check("音韵骨架一致（エスタゾラム ↔ Estazolam）",
          phonetic_skeleton(kata_to_romaji("エスタゾラム")) == phonetic_skeleton("Estazolam"))
    # CLI
    ap = build_parser()
    flags = {opt for action in ap._actions for opt in action.option_strings}
    check("CLI 没有 --apply / --rollback", "--apply" not in flags and "--rollback" not in flags)
    check("CLI 有 --fetch / --dry-run / --self-check / --prepare-copy",
          {"--fetch", "--dry-run", "--self-check", "--prepare-copy"} <= flags)
    check("dry-run 默认库是 .tmp 副本，不是真库", ap.get_default("db") != REAL_DB,
          str(ap.get_default("db")))
    print(f"\n=== self-check {'全部通过' if not failures else '有失败'}（{len(failures)} 项失败）===")
    return 0 if not failures else 1


def cmd_self_check(args: argparse.Namespace) -> int:
    src = args.src if args.src.is_absolute() else (ROOT / args.src)
    return self_check(src)


# ---------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="日本 薬価基準収載品目リスト ETL 骨架：只做干跑，**不写库**。"
                    "口径=医保收载（薬価基準），不是日本上市注册库；不提供 --apply。",
        epilog="例：--fetch 抓快照与许可证据；--prepare-copy 复制库；--dry-run 出统计；"
               "--self-check 跑离线断言。")
    ap.add_argument("--fetch", action="store_true", help="抓 4 个 Excel + 许可证据")
    ap.add_argument("--prepare-copy", action="store_true", help="复制 data/drugs.db 到 .tmp/jp-ingest/")
    ap.add_argument("--force", action="store_true", help="--fetch 时强制重抓")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="读缓存 → 解析 → 统计（默认，只读）")
    mode.add_argument("--self-check", action="store_true", help="离线断言")
    ap.add_argument("--db", type=Path, default=DB_COPY, help="只读库副本（拒绝真库）")
    ap.add_argument("--src", type=Path, default=RAW, help="快照目录")
    ap.add_argument("--copy", action="store_true", help="库副本不存在时先复制真库")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.fetch:
        return cmd_fetch(args)
    if args.prepare_copy:
        return cmd_prepare_copy(args)
    if args.self_check:
        return cmd_self_check(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
