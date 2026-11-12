# -*- coding: utf-8 -*-
"""法国 BDPM（Base de données publique des médicaments）ETL 骨架 —— **只做干跑，不写库**。

许可（这是本文件最重要的一节）
------------------------------
法国 BDPM 是目前唯一**已确认 A 类**的成员国数据源：

- BDPM 下载页 `https://base-donnees-publique.medicaments.gouv.fr/telechargement` 自带的
  「Termes du contrat de licence」明写：依《社会保障法典》L.161-40-1 条（2011-2012 号法第 8 条
  修订）向公众开放，允许**复制、传播、再分发、利用**，条件是**不得篡改数据**、**注明来源**
  （`base-donnees-publique.medicaments.gouv.fr`）与**数据更新日期**（1978 年 7 月 17 日法
  CADA 第 12 条）；且不得暗示 ANSM / HAS / UNCAM 对再利用者有任何背书。
- data.gouv.fr 数据集 `base-de-donnees-publique-des-medicaments-base-officielle`
  （`id=53698f50a3a729239d2036f5`）元数据 `license = fr-lo`（Licence Ouverte / Open Licence 2.0）。

许可证据原样存在 `data/raw/fr_bdpm_20261112/license/`（页面 HTML + 正文摘录 + 数据集 JSON +
Licence Ouverte 原文），`fetch_meta.json` 记 URL / HTTP 头 / 字节 / sha256 / 数据更新日期。

**写库三段式（2026-11-13 task-54 补齐）**：`--apply`（事务写 `source` + product / component /
product_name / name_key / name_variant / ingest_run，幂等：同 source 先删后写）、`--manifest`
（撤销清单：本次新增行的全量快照 + 计数 + 库文件 sha256 before/after）、`--rollback`（按 manifest
只删本次写入的行，保护既有数据）。`--allow-real` 护栏沿用 `etl/ingest_eu.py`：没有它时 `--apply` /
`--rollback` 拒绝真库 `data/drugs.db`，只允许 `.tmp/` 副本。
**今天（v0.11.3→FR 上线前）仍不写真实库**：DB 窗口排下一会话；真库写入前必须先做
`product.country` CHECK 加 `FR` 的 schema 迁移（`db/schema.sql` + `db/init_db.py` 的幂等重建路径）。

数据源（整库文件，`https://base-donnees-publique.medicaments.gouv.fr/download/file/<name>`）
--------------------------------------------------------------------------------------------
- `CIS_bdpm.txt`：15,799 行，**12 列**（实测）= 一个 CIS（药品注册号）一行：商品名
  （dénomination）、剂型、给药途径、授权状态、授权程序、上市状态、AMM 日期、供应预警、
  **欧盟号**、MAH、加强监测。
- `CIS_COMPO_bdpm.txt`：32,449 行，**8 列** = 剂型 + 成分代码 + 成分名 + dosage + référence
  + nature（`SA` 活性成分 26,951 / `FT` 治疗分组分 5,498）+ 编号。
- `CIS_CIP_bdpm.txt`：20,908 行，**13 列** = 每个 CIS 的**包装**（CIP7/CIP13 + 包装描述 +
  展示状态 + 价格/报销列，价格列不入库）。
- `CIS_GENER_bdpm.txt`：10,614 行，**5 列** = 仿制药组（组号 / 组标签 / CIS / 类型 / 组内序号）。

前三个文件不是同一编码：`CIS_bdpm.txt` / `CIS_COMPO_bdpm.txt` / `CIS_GENER_bdpm.txt` 是
**cp1252（latin-1 超集）**，`CIS_CIP_bdpm.txt` 是 **UTF-8**（实测，见 `fetch_meta.json`
每文件的 `encoding`）。所以字段一律按**列序**写死映射，不猜表头；每行校验列数。

口径（页面写文案时必须照做）
----------------------------
- 商品名是法语原文，不翻译；`dénomination` 里带规格（`DOLIPRANE 500 mg, comprimé`），
  但**真正的剂量以 `CIS_COMPO` 的 dosage + référence 为准**，名称侧单独统计。
- BDPM 的「État de commercialisation」是**上市状态**（Commercialisée / Non commercialisée /
  …），不是「是否仍在授权」；两者分开存（`status` 只有 active / discontinued / withdrawn /
  unknown 四值，映射规则见 `map_status()`）。
- 集中审批产品在 BDPM 里是 `Type de procédure d'autorisation = Procédure centralisée`，
  **CIS 是法国本地编号，不是 EU 号**；与 `region='EU'` 层的去重只能靠「名称归一 + 成分」
  估算，不能靠注册号直接对齐。

CLI：
    python etl/markets/fr.py --fetch          # 抓快照 + 许可证据到 data/raw/fr_bdpm_20261112/
    python etl/markets/fr.py --prepare-copy   # 真库 → .tmp/fr-ingest/drugs_fr_copy.db（只拷一次）
    python etl/markets/fr.py --dry-run        # 默认：读缓存 → 解析 → 统计（只读开库副本）
    python etl/markets/fr.py --self-check     # 离线断言 + manifest / 护栏 / 预测一致性
    python etl/markets/fr.py --apply --allow-real --db <副本> --manifest <json>   # 写库（副本）
    python etl/markets/fr.py --rollback --allow-real --db <副本> --manifest <json>

产物：`.tmp/fr-ingest/fr_dry_run.json` + `fr_samples.json` + `fr_manifest*.json` + 控制台摘要。
`data/raw/`、`.tmp/` 都不入 git；真实库 `data/drugs.db` 只有在 `--apply --allow-real` 下才会写。
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import html
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

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "etl"))

from ingest_ema_medicines import _variant_resolver  # noqa: E402
from ingest_openfda_ndc import form_base_of, slug  # noqa: E402
from ingest_sg_hsa import SgMapper  # noqa: E402
from normalize_name import normalize  # noqa: E402
from normalize_strength import norm_unit  # noqa: E402

try:  # Windows 控制台默认 GBK，法语原文里的 é/è/à 会让 print 抛 UnicodeEncodeError
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    pass

SITE = "https://base-donnees-publique.medicaments.gouv.fr"
DOWNLOAD_PAGE = f"{SITE}/telechargement"
FILE_URL = f"{SITE}/download/file/{{name}}"
DATAGOUV_API = ("https://www.data.gouv.fr/api/1/datasets/"
                "base-de-donnees-publique-des-medicaments-base-officielle/")
DATAGOUV_PAGE = ("https://www.data.gouv.fr/datasets/"
                 "base-de-donnees-publique-des-medicaments-base-officielle")
LICENCE_URL = "https://www.etalab.gouv.fr/licence-ouverte-open-licence/"
LICENCE_TEXT_URL = "https://www.data.gouv.fr/fr/licences"
RAW = ROOT / "data" / "raw" / "fr_bdpm_20261112"
LICENSE_DIR = RAW / "license"
FETCH_META = RAW / "fetch_meta.json"
WORK = ROOT / ".tmp" / "fr-ingest"
REAL_DB = ROOT / "data" / "drugs.db"
DB_COPY = WORK / "drugs_fr_copy.db"
SOURCE_ID = "bdpm_fr"
COUNTRY = "FR"
UA = "drug-brand-crossref/0.1 (dry-run only; +https://github.com/fuarnos/drug-brand-crossref)"
TAB = "\t"
# 写库窗口用：source 行元数据（与 docs/许可清单.md §2.11 的 bdpm_fr 行一致）
SOURCE_META = {
    "name": "Base de données publique des médicaments (BDPM) — ANSM",
    "url": DOWNLOAD_PAGE,
    "license": "Licence Ouverte / Open Licence 2.0 (etalab-2.0)",
    "license_url": DOWNLOAD_PAGE,
    "data_as_of": "2026-11-03",
    "data_as_of_note": "BDPM 下载页「Dernière mise à jour le 03/11/2026」",
    "notes": "法国 BDPM 整库文件（CIS / CIS_COMPO / CIS_CIP / CIS_GENER）：商品名/剂型/途径/"
             "成分+剂量/包装；页面须署名 + 数据更新日期；不是「在售」记录",
}
MANIFEST = WORK / "fr_manifest.json"
TODAY = datetime.now(timezone.utc).date().isoformat()

# 文件 → 列数 / 角色（无表头，字段按列序写死；2026-11-12 实测列数）
FILES: dict[str, dict] = {
    "CIS_bdpm.txt": {"columns": 12, "role": "specialite"},
    "CIS_COMPO_bdpm.txt": {"columns": 8, "role": "composition"},
    "CIS_CIP_bdpm.txt": {"columns": 13, "role": "presentation"},
    "CIS_GENER_bdpm.txt": {"columns": 5, "role": "generic_group"},
}

# CIS_bdpm.txt 列序（实测 12 列；col9 = 欧盟号，只有「Procédure centralisée」那 2,261 行有值）
CIS_COLUMNS = [
    "cis", "denomination", "forme", "voies", "statut_autorisation", "procedure",
    "etat_commercialisation", "date_amm", "dispo_status", "eu_number", "titulaires",
    "surveillance_renforcee",
]
# CIS_COMPO_bdpm.txt 列序（实测 8 列；FT = 治疗分组分，单独计、不进 component）
COMPO_COLUMNS = [
    "cis", "forme", "code_substance", "designation", "dosage", "reference_dosage",
    "nature", "num_liaison",
]
# CIS_CIP_bdpm.txt 列序（实测 13 列；col9-13 是价格/报销备注，不入库，只记存在）
CIP_COLUMNS = [
    "cis", "cip7", "libelle", "statut_presentation", "etat_commercialisation",
    "date_declaration", "cip13", "agrement_collectivites", "taux_remboursement",
    "prix", "prix_honoraires", "frais", "note_remboursement",
]
# CIS_GENER_bdpm.txt 列序（实测 5 列；col4 语义未确认，只作组内序号参考，不用）
GENER_COLUMNS = ["groupe", "libelle_groupe", "cis", "type", "ordre"]

# 页面口径：BDPM 更新日期从下载页 "Dernière mise à jour le DD/MM/YYYY" 抽，解析时再核对一次
LAG_NOTE = "BDPM 整库文件随更新发布（下载页标注「Dernière mise à jour」日期）"


def _columns_for(name: str) -> list[str]:
    """文件名 → 列名表（无表头，字段按列序写死）。"""
    if name.startswith("CIS_bdpm"):
        return CIS_COLUMNS
    if name.startswith("CIS_COMPO"):
        return COMPO_COLUMNS
    if name.startswith("CIS_CIP"):
        return CIP_COLUMNS
    return GENER_COLUMNS


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
    """只读开库（`mode=ro`）：本脚本没有任何写库路径，连接也开不成写。"""
    db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=120)
    db.row_factory = sqlite3.Row
    return db


def _fold(text: str) -> str:
    """重音折叠 + 小写（`PARACÉTAMOL` → `paracetamol`）；只用于比较，不写库。"""
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _decode(blob: bytes) -> tuple[str, str, int]:
    """→ (文本, 编码, 替换字符数)。

    BDPM 各文件编码不统一：先试 UTF-8（严格），失败降级 cp1252（latin-1 超集，覆盖法语重音）。
    返回「替换字符数」是为了**显式报出来**——真的掉字时必须看得见，不能静默。
    """
    for enc in ("utf-8", "cp1252"):
        try:
            text = blob.decode(enc)
        except UnicodeDecodeError:
            continue
        return text, enc, text.count("\ufffd")
    return blob.decode("latin-1"), "latin-1", 0


def _http_get(url: str, timeout: int = 180) -> tuple[bytes, dict, int]:
    """GET → (字节, 小写键的响应头, HTTP 状态)。统一走 urllib（本机 schannel 会拒 curl）。"""
    req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定官方 URL
        return resp.read(), {k.lower(): v for k, v in resp.headers.items()}, resp.status


def _html_to_text(page: str) -> str:
    """HTML → 单行纯文本（去 script/style，保留段落空格），只用于摘录许可条款。"""
    page = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|br)>", "\n", page)
    page = re.sub(r"(?i)<br\s*/?>", "\n", page)
    page = re.sub(r"<[^>]+>", " ", page)
    text = html.unescape(page)
    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


# ---------------------------------------------------------------- 抓取
def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def fetch_license_evidence(force: bool = False) -> dict:
    """抓许可证据：BDPM 下载页 + 条款摘录 + data.gouv.fr 数据集 + Licence Ouverte 原文。

    任何一步失败都**记录失败、不中断**（证据缺口要在报告里看得见），但 BDPM 下载页与
    data.gouv.fr 元数据是「许可结论」的根证据，缺了就在 `ok` 里标 false。
    """
    LICENSE_DIR.mkdir(parents=True, exist_ok=True)
    evidence: dict = {"fetched_at": _now(), "items": [], "ok": False}
    page_target = LICENSE_DIR / "bdpm_telechargement.html"
    page_text_target = LICENSE_DIR / "bdpm_telechargement.txt"
    terms_target = LICENSE_DIR / "bdpm_licence_terms.txt"
    dataset_target = LICENSE_DIR / "data_gouv_dataset.json"
    licence_target = LICENSE_DIR / "licence_ouverte_2.0.html"
    licence_text_target = LICENSE_DIR / "licence_ouverte_2.0.txt"

    def record(name: str, url: str, target: Path, ok: bool, **extra) -> None:
        evidence["items"].append({"name": name, "url": url, "path": str(target),
                                  "ok": ok, **extra})

    # ① BDPM 下载页（含 "Termes du contrat de licence"）
    if page_target.exists() and not force:
        blob, headers, status = page_target.read_bytes(), {}, 0
        record("bdpm_download_page", DOWNLOAD_PAGE, page_target, True, cached=True,
               bytes=len(blob), sha256=_sha256_bytes(blob))
    else:
        try:
            blob, headers, status = _http_get(DOWNLOAD_PAGE)
            page_target.write_bytes(blob)
            record("bdpm_download_page", DOWNLOAD_PAGE, page_target, True, http_status=status,
                   bytes=len(blob), sha256=_sha256_bytes(blob), headers=headers)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            blob, headers = b"", {}
            record("bdpm_download_page", DOWNLOAD_PAGE, page_target, False,
                   error=f"{type(exc).__name__}: {exc}")
    if blob:
        plain = _html_to_text(blob.decode("utf-8", "replace"))
        page_text_target.write_text(plain, encoding="utf-8")
        evidence["page_text_sha256"] = _sha256_bytes(plain.encode("utf-8"))
        m = re.search(r"Derni[èe]re mise [àa] jour le (\d{2}/\d{2}/\d{4})", plain, re.I)
        evidence["page_last_update"] = m.group(1) if m else None
        # 条款段：从 "Termes du contrat de licence" 之后到「下载清单」前
        start = plain.find("Termes du contrat de licence")
        end = plain.find("Téléchargement des fichiers", start + 10)
        if start >= 0:
            section = plain[start:end if end > start else start + 4000]
            terms_target.write_text(section.strip() + "\n", encoding="utf-8")
            evidence["terms_sha256"] = _sha256_bytes(section.encode("utf-8"))
            evidence["terms_chars"] = len(section)
    # ② data.gouv.fr 数据集元数据（license=fr-lo 的出处）
    dataset_ok = False
    if dataset_target.exists() and not force:
        raw = dataset_target.read_bytes()
        record("data_gouv_dataset", DATAGOUV_API, dataset_target, True, cached=True,
               bytes=len(raw), sha256=_sha256_bytes(raw))
        dataset_ok = True
    else:
        try:
            raw, headers, status = _http_get(DATAGOUV_API)
            dataset_target.write_bytes(raw)
            record("data_gouv_dataset", DATAGOUV_API, dataset_target, True, http_status=status,
                   bytes=len(raw), sha256=_sha256_bytes(raw), headers=headers)
            dataset_ok = True
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raw = b""
            record("data_gouv_dataset", DATAGOUV_API, dataset_target, False,
                   error=f"{type(exc).__name__}: {exc}")
    if dataset_ok:
        try:
            meta = json.loads(dataset_target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            meta = {}
            evidence["dataset_error"] = f"JSONDecodeError: {exc}"
        evidence["dataset"] = {
            "id": meta.get("id"), "title": meta.get("title"),
            "page": meta.get("page") or DATAGOUV_PAGE,
            "license": meta.get("license"), "license_title": meta.get("license_title"),
            "last_update": meta.get("last_update"), "frequency": meta.get("frequency"),
            "organization": ((meta.get("organization") or {}) or {}).get("name"),
        }
    # ③ Licence Ouverte 原文（可选证据：允许复制/传播/再分发/利用的条文）
    for name, url, target in (
        ("licence_ouverte", LICENCE_URL, licence_target),
        ("licence_page", LICENCE_TEXT_URL, licence_text_target),
    ):
        if target.exists() and not force:
            record(name, url, target, True, cached=True, bytes=target.stat().st_size)
            continue
        try:
            raw, headers, status = _http_get(url, timeout=90)
            target.write_bytes(raw)
            record(name, url, target, True, http_status=status, bytes=len(raw),
                   sha256=_sha256_bytes(raw), headers=headers)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            record(name, url, target, False, error=f"{type(exc).__name__}: {exc}")

    evidence["ok"] = bool(evidence.get("terms_chars") and dataset_ok
                          and evidence.get("dataset", {}).get("license") == "fr-lo")
    return evidence


def fetch_file(name: str, force: bool = False) -> dict:
    """抓单个 BDPM 整库文件 → (元数据)；已有缓存且不 force 时复用（仍记 sha256/字节）。"""
    spec = FILES[name]
    target = RAW / name
    meta: dict = {"name": name, "url": FILE_URL.format(name=name), "role": spec["role"],
                  "expected_columns": spec["columns"]}
    if target.exists() and not force:
        blob = target.read_bytes()
        meta.update({"cached": True, "bytes": len(blob), "sha256": _sha256_bytes(blob)})
    else:
        blob, headers, status = _http_get(FILE_URL.format(name=name))
        if not blob:
            raise SystemExit(f"{name} 抓取返回 0 字节，中止（不覆盖缓存）")
        tmp = target.with_name(target.name + ".part")
        tmp.write_bytes(blob)
        tmp.replace(target)
        meta.update({"cached": False, "bytes": len(blob), "sha256": _sha256_bytes(blob),
                     "http_status": status, "headers": headers})
    text, encoding, replaced = _decode(blob)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    widths = Counter(len(ln.split(TAB)) for ln in lines)
    meta.update({
        "encoding": encoding,
        "lines": len(lines),
        "columns_observed": widths.most_common(3),
        "columns_ok": widths.get(spec["columns"], 0),
        "replacement_chars": replaced,
        "bytes": meta.get("bytes") or len(blob),
        "fetched_at": _now(),
    })
    return meta


def cmd_fetch(args: argparse.Namespace) -> int:
    """抓许可证据 + 4 个整库文件，写 `fetch_meta.json`（URL / HTTP 头 / 字节 / sha256 / 更新日期）。"""
    RAW.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    print("=== FR BDPM 抓取 ===")
    print(f"  下载页 {DOWNLOAD_PAGE}")
    evidence = fetch_license_evidence(force=args.force)
    page_update = evidence.get("page_last_update")
    dataset = evidence.get("dataset") or {}
    print(f"  许可: 下载页条款 {'✓' if evidence.get('terms_chars') else '✗'}"
          f"（{evidence.get('terms_chars', 0)} 字符）· data.gouv.fr license="
          f"{dataset.get('license')} · 页面更新日期 {page_update}")
    files: list[dict] = []
    for name in FILES:
        meta = fetch_file(name, force=args.force)
        files.append(meta)
        print(f"  {name:20s} {meta['bytes']:>12,} B · {meta['lines']:>7,} 行"
              f" · {meta['encoding']:6s} · 列数 {meta['expected_columns']}"
              f"（实测 top {meta['columns_observed'][:2]}）"
              f" · sha256 {meta['sha256'][:16]}…")
    payload = {
        "source_id": SOURCE_ID,
        "country": COUNTRY,
        "site": SITE,
        "download_page": DOWNLOAD_PAGE,
        "fetched_at": _now(),
        "page_last_update": page_update,
        "licence": {
            "id": dataset.get("license") or "fr-lo",
            "name": "Licence Ouverte / Open Licence 2.0（Etalab）",
            "url": LICENCE_URL,
            "can_redistribute": True,
            "obligations": ["不得篡改数据", "注明来源 base-donnees-publique.medicaments.gouv.fr",
                            "注明数据更新日期", "不得暗示 ANSM/HAS/UNCAM 背书"],
            "evidence_dir": str(LICENSE_DIR.relative_to(ROOT)),
            "evidence": evidence,
        },
        "files": files,
        "note": LAG_NOTE,
    }
    _write_json(FETCH_META, payload)
    print(f"  证据目录 {LICENSE_DIR.relative_to(ROOT)} · 元数据 {FETCH_META.relative_to(ROOT)}")
    print(f"  耗时 {round(time.perf_counter() - t0, 1)}s")
    return 0 if evidence.get("ok") else 1


# ---------------------------------------------------------------- 解析：读文件
def load_table(name: str, columns: list[str], raw: Path = RAW) -> tuple[list[dict], dict]:
    """读无表头 TSV → (行列表, 统计)；列数不符的行单独计数并跳过（不静默串列）。"""
    path = raw / name
    if not path.exists():
        raise SystemExit(f"缺快照：{path}（先跑 `python etl/markets/fr.py --fetch`）")
    text, encoding, replaced = _decode(path.read_bytes())
    stats: Counter = Counter()
    stats["encoding_replacements"] = replaced
    stats["encoding_ok"] = 1 if replaced == 0 else 0
    stats[f"encoding:{encoding}"] += 1
    rows: list[dict] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        stats["lines"] += 1
        parts = line.split(TAB)
        if len(parts) != len(columns):
            stats["bad_column_count"] += 1
            if stats["bad_column_count"] <= 5:
                print(f"  !! {name} 第 {lineno} 行列数 {len(parts)} ≠ {len(columns)}，跳过")
            continue
        rows.append(dict(zip(columns, (p.strip() for p in parts))))
        stats["rows"] += 1
    stats["encoding"] = encoding
    return rows, dict(stats)


def load_snapshot(raw: Path = RAW) -> dict:
    """读 4 个整库文件 → 结构化行 + 统计。"""
    cis, cis_stats = load_table("CIS_bdpm.txt", CIS_COLUMNS, raw)
    compo, compo_stats = load_table("CIS_COMPO_bdpm.txt", COMPO_COLUMNS, raw)
    cip, cip_stats = load_table("CIS_CIP_bdpm.txt", CIP_COLUMNS, raw)
    gener, gener_stats = load_table("CIS_GENER_bdpm.txt", GENER_COLUMNS, raw)
    return {"cis": cis, "compo": compo, "cip": cip, "gener": gener,
            "stats": {"CIS_bdpm.txt": cis_stats, "CIS_COMPO_bdpm.txt": compo_stats,
                      "CIS_CIP_bdpm.txt": cip_stats, "CIS_GENER_bdpm.txt": gener_stats}}


# ---------------------------------------------------------------- 解析：状态 / 剂型
def map_status(row: dict) -> tuple[str, str]:
    """BDPM 两个状态列 → (status, 说明)。

    `status` 只有 active / discontinued / withdrawn / unknown 四值：
    - `Statut administratif`（Autorisation active / inactive / archivée）优先；
    - 授权 active 但 `État de commercialisation = Non commercialisée` → `discontinued`
      （有授权、不在售，不是「未知」）；
    - 其余按原文兜底 `unknown`，不猜。
    """
    auth = _fold(row.get("statut_autorisation", ""))
    market = _fold(row.get("etat_commercialisation", ""))
    # 注意：`inactive` 里含子串 `active`，必须先判 inactive / 撤回类，再判 active
    if "archiv" in auth or "retir" in auth or "abrog" in auth:
        return "withdrawn", f"{row.get('statut_autorisation')} / {row.get('etat_commercialisation')}"
    if "inactive" in auth:
        return "discontinued", f"{row.get('statut_autorisation')} / {row.get('etat_commercialisation')}"
    if "active" in auth:
        if "non commercialis" in market or "arret" in market or "arrêt" in market:
            return "discontinued", f"{row.get('statut_autorisation')} / {row.get('etat_commercialisation')}"
        if "commercialis" in market:
            return "active", f"{row.get('statut_autorisation')} / {row.get('etat_commercialisation')}"
        return "unknown", f"{row.get('statut_autorisation')} / {row.get('etat_commercialisation')}"
    return "unknown", f"{row.get('statut_autorisation')} / {row.get('etat_commercialisation')}"


def split_routes(value: str) -> list[str]:
    """`Voies d'administration` → 途径列表（BDPM 用 `;` 分隔；`+` 也见过）。"""
    text = _clean(value)
    if not text:
        return []
    parts = re.split(r"\s*[;+]\s*", text)
    return [p.strip() for p in parts if p.strip()]


def fr_form_base(forme: str, voies: str = "") -> str:
    """法语剂型（+ 给药途径）→ 仓库已有 `form_base` 取值。

    2026-11-14（task-68）：优先用 BDPM 结构化字段 `forme pharmaceutique`，`voie` 只作兜底；
    目标值限定在库内已出现的词（`tablet / capsule / liquid / injection / topical / powder /
    inhalation / suppository / effervescent / gas / gum / pastille / mouthwash / pad / stick /
    kit / device / film / implant / radiofarmaco / tea (herbal)`），不新造枚举。
    """
    f = _fold(forme)
    v = _fold(voies)
    mapping = [
        ("comprime effervescent", "effervescent"), ("effervescent", "effervescent"),
        ("gastro-resistant", "tablet"), ("gastro resistant", "tablet"),
        ("comprime", "tablet"), ("gelule", "capsule"), ("capsule", "capsule"),
        ("suppositoire", "suppository"), ("ovule", "suppository"),
        ("injectable", "injection"), ("injection", "injection"), ("perfusion", "injection"),
        ("poudre", "powder"), ("granule", "powder"), ("lyophilisat", "powder"),
        ("sirop", "liquid"), ("solution", "liquid"), ("suspension", "liquid"),
        ("emulsion", "liquid"), ("buvable", "liquid"), ("collyre", "liquid"),
        ("pommade", "topical"), ("creme", "topical"), ("gel", "topical"),
        ("emplatre", "topical"), ("pansement", "pad"), ("patch", "topical"),
        ("implant", "implant"), ("inhal", "inhalation"), ("aerosol", "inhalation"),
        ("gaz", "gas"), ("gomme", "gum"), ("pastille", "pastille"), ("pate a sucer", "pastille"),
        ("collutoire", "mouthwash"), ("bain de bouche", "mouthwash"),
        ("pate dentifrice", "topical"), ("vernis", "topical"), ("mousse", "topical"),
        ("compresse", "pad"), ("baton", "stick"), ("plante", "tea (herbal)"),
        ("tisane", "tea (herbal)"), ("dispositif", "device"), ("trousse", "kit"),
        ("generateur", "radiofarmaco"), ("systeme", "device"), ("radiopharma", "radiofarmaco"),
        ("film", "film"),
    ]
    for needle, base in mapping:
        if needle in f:
            return base
    # `forme` 认不出时用结构化 `voie d'administration` 兜底（不是从品名猜）
    if v:
        if any(k in v for k in ("intraveineuse", "intramusculaire", "sous-cutanee",
                                "intraarterielle", "intraveineux", "injectable")):
            return "injection"
        if any(k in v for k in ("ophtalmique", "auriculaire")):
            return "liquid"
        if "inhalation" in v or "nasale" in v:
            return "inhalation"
        if "cutanee" in v or "transdermique" in v:
            return "topical"
        if "orale" in v or "buvable" in v:
            return "liquid"
        if "rectale" in v or "vaginale" in v:
            return "suppository"
    return form_base_of(forme) or "other"


def release_of(denomination: str, forme: str) -> str:
    """缓释/肠溶标记 → release 枚举（none / IR / ER / SR / DR / GITS / MR）。"""
    text = _fold(f"{denomination} {forme}")
    if "gastro-resistant" in text or "gastro resistant" in text or "entero" in text \
            or "intestinal" in text:
        return "DR"
    if "liberation prolongee" in text or "liberation modifiee" in text \
            or "prolonged" in text or "modifiee" in text:
        return "ER"
    return "none"


# ---------------------------------------------------------------- 解析：规格
_RE_DOSAGE = re.compile(
    r"^\s*(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>%|µg|μg|mcg|mg|g|kg|ml|l|UI|IU|IE|MIU|MUI|"
    r"mEq|mmol|mol|dose|unit[ée]s?|unit|UFC|GBq|MBq|kBq|Bq)\s*"
    r"(?P<rest>.*)$", re.I)
# 单位写成法语单词的情况（`100 microgrammes` / `10 000 unités`）：只换单位词，不动数值
_RE_UNIT_WORDS = re.compile(
    r"\b(microgrammes?|milligrammes?|grammes?|millilitres?|litres?|"
    r"unit[ée]s?\s+internationales?|unit[ée]s?)\b", re.I)
_UNIT_WORD_MAP = {
    "microgramme": "mcg", "microgrammes": "mcg", "milligramme": "mg", "milligrammes": "mg",
    "gramme": "g", "grammes": "g", "millilitre": "mL", "millilitres": "mL",
    "litre": "L", "litres": "L", "unite": "unit", "unites": "unit",
    "unite internationale": "IU", "unites internationales": "IU",
}
_FR_UNIT = {
    "%": "%", "µg": "mcg", "μg": "mcg", "mcg": "mcg", "mg": "mg", "g": "g", "kg": "kg",
    "ml": "mL", "l": "L", "ui": "IU", "iu": "IU", "ie": "IU", "mui": "MIU", "miu": "MIU",
    "meq": "mEq", "mmol": "mmol", "mol": "mol", "ufc": "CFU", "unit": "unit",
    "unités": "unit", "unité": "unit",
    "gbq": "GBq", "mbq": "MBq", "kbq": "kBq", "bq": "Bq",
}


def parse_dosage(dosage: str, reference: str = "") -> dict | None:
    """COMPO 的 `dosage` + `référence de dosage` → schema 四列（不换算）。

    BDPM 写法：`500 mg` + `pour 1 comprimé` / `0,5 g` + `pour 1 sachet` /
    `10 mg` + `pour 1 ml`。只把「数值 + 单位」摆到 `strength_*`，分母摆到 `per_volume_*`；
    分母是「1 comprimé」这类**计件单位**时只保留数字与单位原样（不折算、不猜密度）。
    """
    text = _clean(dosage)
    if not text:
        return None
    # 法语千位分隔符是空格 / 窄不换行空格（`1 000 mg`）：去掉分隔符，数值不变
    text = re.sub(r"(?<=\d)[ \u00a0\u202f](?=\d{3}(?!\d))", "", text)
    # 单位写成法语单词（`100 microgrammes`、`10 000 unités`）→ 缩写，再交给统一解析
    text = _RE_UNIT_WORDS.sub(lambda m: _UNIT_WORD_MAP.get(_fold(m.group(1)), m.group(1)), text)
    dash, sep, tail = text.partition(" ")
    m = _RE_DOSAGE.match(text)
    value: float | None = None
    unit = ""
    rest = ""
    if m:
        try:
            value = float(m.group("value").replace(",", "."))
        except ValueError:
            value = None
        raw_unit = m.group("unit")
        unit, _rule = norm_unit(raw_unit)
        unit = _FR_UNIT.get(raw_unit.lower(), unit or raw_unit)
        rest = m.group("rest").strip()
    # `500 mg/5 ml` 这种浓度直接写在 dosage 里
    per_v: float | None = None
    per_u: str | None = None
    if rest.startswith("/"):
        m2 = re.match(r"^/\s*(\d+(?:[.,]\d+)?)\s*([a-zA-Zµμ]+)", rest)
        if m2:
            try:
                per_v = float(m2.group(1).replace(",", "."))
            except ValueError:
                per_v = None
            raw_pu = m2.group(2)
            per_u, _ = norm_unit(raw_pu)
            per_u = _FR_UNIT.get(raw_pu.lower(), per_u or raw_pu)
    # 分母来自 référence de dosage（`pour 1 comprimé` / `pour 1 ml` / `pour 5 ml`）
    ref = _fold(reference)
    if per_v is None:
        m3 = re.search(r"(\d+(?:[.,]\d+)?)\s*(ml|l|g|mg)\b", ref)
        if m3:
            try:
                per_v = float(m3.group(1).replace(",", "."))
            except ValueError:
                per_v = None
            raw_pu = m3.group(2)
            per_u, _ = norm_unit(raw_pu)
            per_u = _FR_UNIT.get(raw_pu.lower(), per_u or raw_pu)
    if value is None:
        return None
    return {"value": value, "unit": unit or None, "per_volume_value": per_v,
            "per_volume_unit": per_u}


# ---------------------------------------------------------------- 解析：品名侧规格（补足用）
_RE_IE_FR = re.compile(r"\b(UI|U\.I\.?|IE|IU)\b", re.I)
_RE_MICRO_FR = re.compile(r"\b(?:microgrammes?|µg|μg)\b", re.I)
_RE_MILLIONS_UI = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:millions?|M)\s*(?:d['’]?\s*)?(?:UI|U\.I\.?)\b", re.I)


def _strength_input(name: str) -> str:
    """品名里的法语单位 → `normalize()` 认得的写法（只改单位词，不动数值）。"""
    s = _RE_IE_FR.sub("IU", name or "")
    s = _RE_MICRO_FR.sub("mcg", s)
    return _RE_MILLIONS_UI.sub(lambda m: m.group(1).replace(",", ".") + " MIU", s)


def parse_name_strengths(name: str) -> list[dict]:
    """品名（dénomination）侧抽规格 → schema 四列；只在 composition 没给剂量时**补足**用。

    复用法语写法整形（`UI`→`IU`、`microgrammes`→`mcg`、`millions d'UI`→`MIU`）+
    仓库统一 `normalize()`（吃 `0,5 mg`、`x mg/2 ml`）；只摆数值，不做换算。
    """
    out: list[dict] = []
    for raw_value, raw_unit in normalize(_strength_input(name)).strengths:
        values = str(raw_value).split("/")
        units = str(raw_unit).split("/")
        try:
            value = float(values[0].replace(",", "."))
        except ValueError:
            continue
        unit, _rule = norm_unit(units[0])
        unit = _FR_UNIT.get(units[0].lower(), unit or units[0])
        per_v: float | None = None
        per_u: str | None = None
        if len(values) > 1 or len(units) > 1:
            try:
                per_v = float(values[1].replace(",", ".")) if len(values) > 1 else 1.0
            except ValueError:
                per_v = None
            if len(units) > 1:
                per_u, _ = norm_unit(units[1])
                per_u = _FR_UNIT.get(units[1].lower(), per_u or units[1])
        out.append({"value": value, "unit": unit or None,
                    "per_volume_value": per_v, "per_volume_unit": per_u})
    return out


# ---------------------------------------------------------------- 解析：成分（法语 → INN）
# 法语盐名 / 水合物 / 修饰词 → 英文 INN 写法（只生成候选，命中仍由库里 substance 决定）
FR_SALT_WORDS = {
    "chlorhydrate": "hydrochloride", "dichlorhydrate": "dihydrochloride",
    "bromhydrate": "hydrobromide", "sulfate": "sulfate", "sulphate": "sulfate",
    "phosphate": "phosphate", "nitrate": "nitrate", "citrate": "citrate",
    "maleate": "maleate", "mesilate": "mesylate", "mesylate": "mesylate",
    "besilate": "besylate", "tosylate": "tosylate", "fumarate": "fumarate",
    "hemifumarate": "hemifumarate", "succinate": "succinate", "tartrate": "tartrate",
    "acetate": "acetate", "benzoate": "benzoate", "carbonate": "carbonate",
    "bicarbonate": "bicarbonate", "lactate": "lactate", "gluconate": "gluconate",
    "pamoate": "pamoate", "embonate": "embonate", "decanoate": "decanoate",
    "undecanoate": "undecanoate", "valerate": "valerate", "propionate": "propionate",
    "dipropionate": "dipropionate", "butyrate": "butyrate", "furoate": "furoate",
    "xinafoate": "xinafoate", "palmitate": "palmitate", "stearate": "stearate",
    "aspartate": "aspartate", "glutamate": "glutamate", "malate": "malate",
    "oxalate": "oxalate", "salicylate": "salicylate", "hyaluronate": "hyaluronate",
    "monohydrate": "monohydrate", "dihydrate": "dihydrate", "trihydrate": "trihydrate",
    "hemihydrate": "hemihydrate", "hydrate": "hydrate", "anhydre": "anhydrous",
    "sodium": "sodium", "potassium": "potassium", "calcium": "calcium",
    "magnesium": "magnesium", "zinc": "zinc", "fer": "iron", "ferreux": "ferrous",
    "aluminium": "aluminium", "trometamol": "tromethamine",
    "meglumine": "meglumine", "etanolamine": "ethanolamine", "olamine": "olamine",
    "chlorure": "chloride", "bromure": "bromide", "iodure": "iodide",
    "fluorure": "fluoride", "oxyde": "oxide", "hydroxyde": "hydroxide",
    "alginate": "alginate", "resinate": "resinate", "folinate": "folinate",
    "cromoglicate": "cromoglicate", "metasulfobenzoate": "metasulfobenzoate",
}
# 法语把阴离子写在前面（`CHLORURE DE SODIUM` = sodium chloride）：这些词要先挪到词尾再翻
FR_ANIONS = frozenset({"chlorure", "bromure", "iodure", "fluorure", "oxyde", "hydroxyde",
                       "alginate", "resinate", "folinate", "cromoglicate",
                       "metasulfobenzoate"})
FR_NOISE = frozenset({"anhydre", "monohydrate", "dihydrate", "trihydrate", "hemihydrate",
                      "hydrate"})
# 法语习惯名 → 英文 INN / 库内 canonical 名（只在候选阶段用）
FR_INN_SYNONYMS = {
    "paracetamol": "acetaminophen",
    "acide acetylsalicylique": "aspirin",
    "acetylsalicylate de lysine": "lysine acetylsalicylate",
    "acide folique": "folic acid",
    "acide ascorbique": "ascorbic acid",
    "acide valproique": "valproic acid",
    "acide tranexamique": "tranexamic acid",
    "acide ursodesoxycholique": "ursodeoxycholic acid",
    "acide fusidique": "fusidic acid",
    "acide clavulanique": "clavulanic acid",
    "acide lactique": "lactic acid",
    "acide borique": "boric acid",
    "acide citrique": "citric acid",
    "acide acetique": "acetic acid",
    "acide benzoique": "benzoic acid",
    "acide salicylique": "salicylic acid",
    "acide glycolique": "glycolic acid",
    "acide hyaluronique": "hyaluronic acid",
    "acide ursodiol": "ursodiol",
    "fluorouracile": "fluorouracil",
    "chlorure de sodium": "sodium chloride",
    "chlorure de potassium": "potassium chloride",
    "chlorure de calcium": "calcium chloride",
    # 法语习惯名（库里没有对应 INN 写法时需要显式桥接；命中后仍走库里 substance）
    "cafeine": "caffeine",
    "toxine botulinique type a": "botulinum toxin type a",
    "charbon active": "charcoal activated",
    "huile de soja raffinee": "soybean oil",
    "huile d olive raffinee": "olive oil",
    "protoxyde azote": "nitrous oxide",
    "vaseline": "petrolatum",
    "trinitrine": "nitroglycerin",
    "ascorbate sodium": "sodium ascorbate",
    "gluconate cuivre": "copper gluconate",
    "phosphate dipotassique": "potassium phosphate, dibasic",
    "eau pour preparations injectables": "water for injection",
    "facteur viii coagulation humain": "factor viii",
    "anatoxine diphterique": "diphtheria toxoid",
    "anatoxine tetanique": "tetanus toxoid",
    "acide zoledronique monohydrate": "zoledronic acid monohydrate",
    "glucose": "glucose",
    "sorbitol": "sorbitol",
    "mannitol": "mannitol",
    "glycerol": "glycerol",
    "ethanol": "ethanol",
    "lidocaine": "lidocaine",
    "prilocaine": "prilocaine",
}

# v0.11.5（task-68）质量提升：法语盐名/酯/水合物/载体词与常见同义词扩充。
# 键全部是 `_fold()` 之后的无重音写法（`hydrogénotartrate` → `hydrogenotartrate`）。
FR_SALT_WORDS.update({
    "hydrogenotartrate": "hydrogen tartrate", "hydrogentartrate": "hydrogen tartrate",
    "hydrogenosuccinate": "hydrogen succinate", "hydrogensuccinate": "hydrogen succinate",
    "hydrogenosulfate": "hydrogen sulfate", "hydrogensulfate": "hydrogen sulfate",
    "hydrogenophosphate": "hydrogen phosphate", "hydrogenphosphate": "hydrogen phosphate",
    "dihydrogenophosphate": "dihydrogen phosphate", "dihydrogenphosphate": "dihydrogen phosphate",
    "metasulfobenzoate": "metasulfobenzoate", "metasulphobenzoate": "metasulphobenzoate",
    "tetradecylsulfate": "tetradecyl sulfate", "hyclate": "hyclate", "lysinate": "lysinate",
    "ethanolate": "ethanolate", "ditartrate": "ditartrate",
    "hemisuccinate": "hemisuccinate", "hemifumarate": "hemifumarate",
    "pivalate": "pivalate", "propionate": "propionate", "undecylate": "undecylate",
    "benzoyle": "benzoyl", "sel": "", "cuivre": "copper", "tetrakis": "tetrakis",
    "tosilate": "tosylate", "tosylate": "tosylate", "besilate": "besylate",
    "sodique": "sodium", "potassique": "potassium", "calcique": "calcium",
    "magnesique": "magnesium", "monosodique": "monosodium", "disodique": "disodium",
    "dipotassique": "dipotassium", "ammonium": "ammonium", "ferrique": "ferric",
    "ferreux": "ferrous", "lanthane": "lanthanum", "titane": "titanium",
    "anhydre": "anhydrous", "monohydrate": "monohydrate", "dihydrate": "dihydrate",
    "trihydrate": "trihydrate", "hemihydrate": "hemihydrate",
})
FR_ANIONS = FR_ANIONS | {
    "digluconate", "gluconate", "hyaluronate", "metasulfobenzoate", "metasulphobenzoate",
    "tetradecylsulfate", "dihydrogenophosphate", "phosphate", "sulfate", "sulphate",
    "nitrate", "citrate", "tartrate", "maleate", "fumarate", "succinate", "acetate",
    "carbonate", "bicarbonate", "lactate", "benzoate", "salicylate", "mesilate",
    "tosylate", "tosilate", "besilate", "hyclate", "pivalate", "ethanolate", "lysinate",
}
# 金属/阳离子：需要翻译成英文，但**不参与**「盐名前置→后置」的词序旋转
FR_METALS = frozenset({"sodium", "potassium", "calcium", "magnesium", "zinc", "iron",
                       "ferrous", "aluminium", "ammonium", "lanthanum", "titanium"})
# 盐形容词：PHOSPHATE SODIQUE DE X 的 SODIQUE（只有这些词参与「阴离子+形容词」语序）
FR_SALT_ADJECTIVES = frozenset({"sodique", "potassique", "calcique", "magnesique",
                                "monosodique", "disodique", "dipotassique", "ammonium",
                                "ferrique", "ferreux"})
# 载体/剂型前缀词：`SOLUTION DE X` 里的 SOLUTION 不参与成分名匹配
FR_CARRIERS = frozenset({"solution", "suspension", "poudre", "emulsion", "sirop", "granules",
                         "comprimes", "gel", "creme", "pommade", "collyre", "extrait",
                         "concentrat", "complexe", "fraction", "sel", "ester", "co", "cristal"})
FR_INN_SYNONYMS.update({
    "acetylleucine": "levacetylleucine",
    "somatotropine": "somatropin",
    "fludesoxyglucose": "fludeoxyglucose",
    "monoxyde azote": "nitric oxide",
    "chlorure benzalkonium": "benzalkonium chloride",
    "lanthane carbonate hydrate": "lanthanum carbonate hydrate",
    "vitamine a synthetique forme huileuse": "retinol",
    "concentrat vitamine a synthetique forme huileuse": "retinol",
    "hyaluronate sodium": "sodium hyaluronate",
    "doxycycline hyclate": "doxycycline hyclate",
    "ibuprofene lysinate": "ibuprofen lysine",
    "diclofenac epolamine": "diclofenac epolamine",
    "testosterone enantate": "testosterone enanthate",
    "almotriptan hydrogenomalate": "almotriptan malate",
    "diacereine": "diacerein",
})
# 关键词级同义词（在 _fold 后的整串上匹配；用于植物/生物制品/特殊词序，逐条可解释）
FR_KEYWORD_SYNONYMS: list[tuple[str, str]] = [
    # 植物药（法国名 → 库内英文植物名；只做「同物异名」的事实对应）
    ("serenoa repens", "serenoa repens"), ("palmier de floride", "serenoa repens"),
    ("palmier nain", "serenoa repens"), ("saw palmetto", "saw palmetto"),
    ("aubepine", "hawthorn"), ("artichaut", "artichoke"),
    ("passiflore", "passiflora incarnata top"), ("thym", "thymus vulgaris leaf"),
    ("flavonoique", "bioflavonoids"), ("arachis hypogaea", "arachis hypogaea"),
    ("graine d arachis", "arachis hypogaea"), ("peroxyde de benzoele", "benzoyl peroxide"), ("peroxyde de benzole", "benzoyl peroxide"),
    ("niaouli", "niaouli oil"), ("sene de l inde", "senna pods"),
    ("sene de l inde", "senna pods"), ("sene", "senna leaf"), ("ispaghul", "ispaghula husk"),
    ("plantain", "plantago major"),
    # 生物制品 / 疫苗（法国描述 → 库内物质）
    ("virus de la grippe", "influenza virus vaccine"),
    ("antigene de surface de l hepatite b", "hepatitis b surface antigen"),
    ("antigene f du vrs", "recombinant respiratory syncytial virus pre-fusion f protein"),
    ("glycoproteine f", "recombinant respiratory syncytial virus pre-fusion f protein"),
    ("polyoside pneumococcique", "pneumococcal polysaccharide"),
    ("haemophilus type b", "haemophilus influenzae type b"),
    ("antithrombine humaine", "antithrombin iii"),
    ("adamts13", "radamts13"),
    ("venin d abeille", "apis mellifera venom"),
    ("venin d abeilles", "apis mellifera venom"),
    ("venin de guepe vespula", "vespula spp venom"),
    ("venin de guepe poliste", "polistes spp venom protein extract"),
    ("venin de guepe", "vespula spp venom"),
    ("abeille venin", "apis mellifera venom"),
    ("guepe poliste venin", "polistes spp venom protein extract"),
    ("guepe vespula venin", "vespula spp venom"),
    ("guepe venin", "vespula spp venom"),
    ("pelargonium", "pelargonium sidoides root"),
    ("pancreas poudre porcine", "sus scrofa pancreas"),
    ("pancreas porcine", "sus scrofa pancreas"),
    ("rifampicine", "rifampin"),
    ("ioflupane", "ioflupane i 123"),
    ("fluciclovine", "fluciclovine f 18"),
    ("phenoxymethylpenicilline", "phenoxymethylpenicillin benzathine"),
    ("benzathine phenoxymethylpenicilline", "phenoxymethylpenicillin benzathine"),
    ("venin de guepe polistes", "polistes annularis venom"),
    # 特殊词序 / 法语习惯名
    ("peroxyde de benzoyle", "benzoyl peroxide"),
    ("fludesoxyglucose", "fludeoxyglucose f 18"),
    ("monoxyde d azote", "nitric oxide"),
    ("chlorure de benzalkonium", "benzalkonium chloride"),
]
_RE_PAREN = re.compile(r"\([^)]*\)")
_RE_MULTI = re.compile(r"\s*[#;]\s*|\s+et\s+|\s*\+\s*", re.I)
# 法语冠词 / 介词：`CHLORHYDRATE DE METFORMINE` 里的 DE、`D'AMLODIPINE` 里的 D 对成分名无意义
FR_ARTICLES = frozenset({"d", "l", "de", "du", "des", "la", "le", "les"})


def french_clean_token(token: str) -> str:
    """法语成分串 → 可比较的小写写法：去括号注释/等效说明/剂量尾巴、盐名英文化、去冠词。

    2026-11-14（task-68）在原有基础上补：
    - **载体词**（`SOLUTION DE X`、`CO-CRISTAL D'X`）先剥掉，避免把剂型词当成分；
    - **阴离子 + 形容词** 语序（`PHOSPHATE SODIQUE DE DEXAMÉTHASONE` → `dexamethasone sodium phosphate`）；
    - 更多盐/酯/水合物词（`hydrogénotartrate`、`métasulfobenzoate`、`hyclate`、`pivalate`…）；
    - `dl-` 前缀与 `(SULFATE D')` 这类括号盐名保留。
    """
    s = _fold(token)
    paren_extra: list[str] = []
    paren_anions: list[str] = []
    paren_acid = False
    for group in _RE_PAREN.findall(s):
        if "acide" in group:
            paren_acid = True
        for word in re.findall(r"[a-z]+", group):
            hit = FR_SALT_WORDS.get(word) or (FR_SALT_WORDS.get(word[:-1])
                                              if word.endswith("e") else None)
            if hit:
                paren_extra.append(hit)
                if word in FR_ANIONS or (word.endswith("e") and word[:-1] in FR_ANIONS):
                    paren_anions.append(hit)
    s = _RE_PAREN.sub(" ", s)
    # 「... ÉQUIVALENT À ...」「... SOUS FORME DE ...」后面的说明不是成分名
    s = re.split(r"\bequivalent\b|\bsous forme\b|\bexprimee? en\b|\bcorrespondant\b"
                 r"|\brace\b|\bsoit\b", s)[0]
    s = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:mg|g|mcg|µg|ml|l|ui|iu|%)\b.*$", " ", s)
    s = re.sub(r"[^a-z0-9%]+", " ", s).strip()
    words = [w for w in s.split()
             if w not in FR_ARTICLES and w not in {"dl", "d", "sel"}]
    # PEROXYDE DE BENZOYLE → enzoyl peroxide
    if len(words) > 1 and words[0] in {"peroxyde", "oxyde", "hydroxyde"}:
        words = words[1:] + [words[0]]
    # 剥载体/剂型前缀（最多 3 层）：`solution de digluconate de chlorhexidine` → `digluconate chlorhexidine`
    for _ in range(3):
        if len(words) > 1 and words[0] in FR_CARRIERS:
            words = words[1:]
        else:
            break
    # 法语词序：`ACIDE X` → `X acid`
    if words and words[0] == "acide" and len(words) > 1:
        words = words[1:] + ["acid"]
    # `PHOSPHATE SODIQUE DE X` → `X sodium phosphate`（阴离子 + 形容词 一起后置）
    elif (len(words) >= 3 and words[0] in FR_ANIONS
          and words[1] in FR_SALT_ADJECTIVES):
        words = words[2:] + [words[1], words[0]]
    elif words and words[0] in FR_ANIONS and len(words) > 1:
        # 阴离子插在金属后面：`chlorure calcium dihydrate` → `calcium chloride dihydrate`
        words = [words[1], words[0]] + words[2:]
    elif words and words[0] in FR_SALT_WORDS and words[0] not in FR_METALS and len(words) > 1:
        words = words[1:] + [words[0]]
    words += [w for w in paren_extra if w not in words and w not in paren_anions]
    # `CALCIUM (CHLORURE DE) DIHYDRATÉ` → `calcium chloride dihydrate`：阴离子插到金属后面
    for anion in paren_anions:
        if words and anion not in words:
            words = [words[0], anion] + words[1:]
    if paren_acid and words and "acid" not in words:
        words = words + ["acid"]
    return " ".join(FR_SALT_WORDS.get(w, w) for w in words).strip()


def fr_substance_candidates(token: str) -> list[str]:
    """法语成分 token → 候选写法（按优先级去重，最多 64 个）。

    只做**写法变换**，不做匹配：候选交给 `SgMapper.map_basic()` / WHO INN 法语名桥接，
    能不能挂上由库里 `substance` 说了算（不新增 substance、不做模糊匹配）。

    2026-11-14（task-68）新增：
    - 逐词去载体词（最多 2 层），处理 `COMPLEXE … SACUBITRIL VALSARTAN` 这类前缀；
    - 法/西拼写桥（词尾 `e`↔`a`，DB 里有一部分成分主名是西语/葡语拼写）；
    - 辅音简化（`ff`→`f`、`ll`→`l`、`tt`→`t`…）与 `œ`→`oe`、`æ`→`ae`。
    """
    base = french_clean_token(token)
    if not base:
        return []
    out: list[str] = [base]
    if base in FR_INN_SYNONYMS:
        out.append(FR_INN_SYNONYMS[base])
    words = base.split()
    # 去尾部词（盐名/载体尾巴）最多 4 层；每层再查一次同义词
    tail = words[:]
    for _ in range(4):
        if len(tail) <= 1:
            break
        tail = tail[:-1]
        cand = " ".join(tail)
        out.append(cand)
        if cand in FR_INN_SYNONYMS:
            out.append(FR_INN_SYNONYMS[cand])
    # 去开头词（载体/复杂前缀）最多 2 层
    head = words[:]
    for _ in range(2):
        if len(head) <= 1:
            break
        head = head[1:]
        cand = " ".join(head)
        out.append(cand)
        if cand in FR_INN_SYNONYMS:
            out.append(FR_INN_SYNONYMS[cand])
    # 逐词拼写变换（法语 ↔ 英语/西语）
    for stem in list(dict.fromkeys(out)):
        ws = stem.split()
        for i, w in enumerate(ws):
            if len(w) < 5:
                continue
            alts = {w[:-1] if w.endswith("e") else w + "e",
                    w.replace("ph", "f"), w.replace("f", "ph"),
                    w.replace("y", "i"), w.replace("i", "y"),
                    w.replace("oe", "e"), w.replace("e", "oe"),
                    w.replace("ae", "e")}
            if w.endswith("e"):            # 西语/葡语主名桥（diacereine → diacereina）
                alts.add(w[:-1] + "a")
            if w.endswith("ique"):         # 法语形容词 → 英语：glutamique → glutamic
                alts.add(w[:-4] + "ic")
            for a, b in (("ff", "f"), ("ll", "l"), ("mm", "m"), ("nn", "n"),
                         ("pp", "p"), ("tt", "t"), ("ss", "s"), ("rr", "r")):
                if a in w:
                    alts.add(w.replace(a, b))
            for alt in alts:
                if alt and alt != w:
                    out.append(" ".join(ws[:i] + [alt] + ws[i + 1:]))
    # 药名里的 `acide` 前缀保留一份、去掉一份
    if base.startswith("acide "):
        out.append(base[len("acide "):])
        out.append(base[len("acide "):] + " acid")
    return list(dict.fromkeys(x for x in out if x))[:64]


def split_composition(value: str) -> list[str]:
    """成分串 → token 列表（BDPM 一列一个成分，分号/`et` 兜底切开）。"""
    text = _clean(value)
    if not text or _fold(text) in {"-", "aucun"}:
        return []
    return [t.strip() for t in _RE_MULTI.split(text) if t.strip()]


def is_homeopathic(designation: str) -> bool:
    """BDPM 顺势疗法成分（`… POUR PRÉPARATIONS HOMÉOPATHIQUES`）：没有 INN，单独统计。"""
    return "homeopathique" in _fold(designation)


# v0.11.5（task-6）：FR 层黑名单——「判不了的不写库，宁缺勿错」。
# 泛称离子物质（`Sodium`/`Calcium`/… 是盐名碎片，不是成分身份）与 `cn-*` 中文命名物质
# （中成药/生物制品专用 id，法语成分串不该落到那里）一律不予映射；只挡 FR，不动其它市场。
FR_BLOCKED_SUBSTANCES = ("sodium", "calcium", "potassium", "sulfate", "ferric", "sulfur", "water")

# 「无实词残串」词表：功能词 / 剂型 / 单位 / 顺势说明。候选串里一个实词都不剩时直接丢弃，
# 避免 `a 3 pour cent`、`b pour preparations homeopathiques` 这类截断残串进入低特异性匹配层。
_RESIDUAL_WORDS = frozenset({
    "a", "au", "aux", "de", "d", "du", "des", "la", "le", "les", "l", "un", "une",
    "et", "en", "pour", "par", "avec", "sans", "sur", "sous", "dans", "ou", "ou",
    "solution", "solutions", "sol", "suspension", "emulsion", "dispersion", "sirop",
    "preparation", "preparations", "homeopathique", "homeopathiques", "homeopathie",
    "cent", "pct", "vol", "volume", "volumes", "ml", "mg", "g", "kg", "ui", "iu",
    "degre", "dilution", "compris", "presentation",
})


def _is_residual_candidate(cand: str) -> bool:
    """候选串是否「一个实词都没有」（纯虚词/剂型/单位/百分比残串）。

    2026-11-15（task-6）：`fr_substance_candidates()` 的逐层截断会产生
    `a 3 pour cent` 这类残串，交给 `SgMapper.map_basic()` 的低特异性层后
    会命中首字母相同的泛称离子 / `cn-*` 物质，把「没判出来」伪装成「已映射」。
    这里在送进匹配层之前挡掉；长度 ≤2 的碎片（`b`、`mg`）同样算残串。
    """
    toks = [t for t in cand.split() if t]
    if not toks:
        return True
    if len("".join(toks)) < 3:
        return True
    meaningful = [t for t in toks
                  if len(t) > 2 and t not in _RESIDUAL_WORDS and not t.isdigit()]
    return not meaningful


class FrMapper:
    """法语成分 → substance_id：WHO INN 法语名桥接 + 写法候选 + 库里四级规则。

    不新增 substance：映射不上就返回空，产品照写（名称/剂型/状态仍在），只是没有 component。
    """

    def __init__(self, db: sqlite3.Connection, who_inn: Path | None = None):
        self.mapper = SgMapper(db)
        self.by_fr: dict[str, str] = {}
        self.by_fr_sid: dict[str, str] = {}
        self._cand_memo: dict[str, list[tuple[str, str, str]]] = {}
        # v0.11.5（task-6）：黑名单（泛称离子无条件挡 / cn-* 只挡残串命中）+ 丢弃计数
        self.blocked_generic, self.blocked_cn = self._load_blocked(db)
        self.stats: Counter = Counter()
        # 关键词去标点归一（法语撇号/连字符会切断朴素子串匹配）
        self._kw = [(re.sub(r"[^a-z0-9]+", " ", _fold(k)).strip(), v)
                    for k, v in FR_KEYWORD_SYNONYMS]
        # 同义词表按键也走同一套清洗（`ACIDE ASCORBIQUE` → `ascorbique acid`），否则查不到
        self.synonyms = {french_clean_token(k): v for k, v in FR_INN_SYNONYMS.items()}
        who = who_inn or (ROOT / "data" / "who_inn_names.csv")
        if who.exists():
            import csv
            with who.open(encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    fr = _fold(row.get("inn_fr") or "")
                    en = (row.get("inn_en") or "").strip()
                    if fr and en:
                        sid, _salt, _method = self.mapper.map_basic(en)
                        if sid:
                            self.by_fr.setdefault(fr, sid)
                            self.by_fr_sid.setdefault(fr, sid)

    @staticmethod
    def _load_blocked(db: sqlite3.Connection) -> tuple[frozenset[str], frozenset[str]]:
        """黑名单：(泛称离子物质, `cn-*` 物质)（task-6；只影响 FR 层映射）。

        泛称离子无条件挡（`Sodium`/`Calcium` 这类是盐名碎片，不是成分身份）；
        `cn-*` 只挡**截断残串**命中的情况（`a 3 pour cent` 之类），
        完整 token / 显式同义词直接命中时保留（如 `VALPROMIDE` → 库内 cn 行的丙戊酰胺），
        否则会丢掉本来正确的身份对应。
        """
        marks = ",".join("?" * len(FR_BLOCKED_SUBSTANCES))
        rows = db.execute(
            "SELECT substance_id, LOWER(inn_en) FROM substance"
            f" WHERE substance_id LIKE 'cn-%' OR LOWER(inn_en) IN ({marks})",
            [s.lower() for s in FR_BLOCKED_SUBSTANCES]).fetchall()
        generic = frozenset(r[0] for r in rows if (r[1] or "") in FR_BLOCKED_SUBSTANCES)
        cn = frozenset(r[0] for r in rows if (r[0] or "").startswith("cn-"))
        return generic, cn

    def map_candidates(self, token: str) -> list[tuple[str, str, str]]:
        """token → 有序候选 [(substance_id, method, 英文候选写法)]。

        2026-11-14（task-68）：库里有一部分 substance **没有 variant 行**（如
        `esomeprazole-magnesium-dihydrate`），直接返回它会让 component 被 `_variant_resolver`
        丢掉；所以这里返回整条候选链，由调用方挑第一个「有 variant」的（见 `_collect`）。
        另外先跑关键词级同义词（植物/生物制品/特殊词序），再跑 WHO INN 法语名与写法候选。

        2026-11-15（task-6）：**送入匹配层之前**先过两道闸——
        ① 整个 token 是残串（`a 3 pour cent`）直接判「没判出来」；
        ② 命中黑名单（泛称离子 / 残串命中 `cn-*`）的候选丢弃并计数，不再伪装成已映射。
        """
        if token in self._cand_memo:
            return self._cand_memo[token]
        out: list[tuple[str, str, str]] = []
        folded = _fold(token)

        def push(sid: str, method: str, cand: str, exact: bool = False) -> None:
            if not sid:
                return
            if sid in self.blocked_generic or (sid in self.blocked_cn and not exact):
                self.stats["blocked_substance_hits"] += 1
                return
            if all(sid != x[0] for x in out):
                out.append((sid, method, cand))

        folded_norm = re.sub(r"[^a-z0-9]+", " ", folded).strip()
        if not folded_norm or _is_residual_candidate(folded_norm):
            self.stats["residual_tokens"] += 1
            self._cand_memo[token] = []
            return []
        for needle, target in self._kw:
            if needle in folded_norm:
                sid, _salt, method = self.mapper.map_basic(target)
                push(sid, f"kw-{method}", target, exact=True)
        # 肺炎链球菌多糖：按血清型精确对应（库内是 serotype-N 的独立物质）
        m_sero = re.search(r"polyoside pneumococcique.*?serotype\s*([0-9]+[a-z]?)", folded_norm)
        if m_sero:
            target = f"pneumococcal polysaccharide serotype {m_sero.group(1)}"
            sid, _salt, method = self.mapper.map_basic(target)
            push(sid, f"kw-sero-{method}", target, exact=True)
        cleaned = french_clean_token(token)
        if cleaned and cleaned in self.by_fr:
            push(self.by_fr[cleaned], "who-inn-fr", cleaned, exact=True)
        if cleaned and cleaned in self.synonyms:
            sid, _salt, method = self.mapper.map_basic(self.synonyms[cleaned])
            push(sid, f"fr-synonym-{method}", self.synonyms[cleaned], exact=True)
        for idx, cand in enumerate(fr_substance_candidates(token)):
            if _is_residual_candidate(cand):
                self.stats["residual_candidates_dropped"] += 1
                continue
            if cand in self.by_fr:
                push(self.by_fr[cand], "who-inn-fr", cand, exact=True)
            sid, _salt, method = self.mapper.map_basic(cand)
            push(sid, ("raw" if idx == 0 else f"fr-{method}"), cand, exact=(idx == 0))
        self._cand_memo[token] = out
        return out

    def map(self, token: str) -> tuple[str, str]:
        """token → (substance_id, method)；未映射返回 ("", "unmapped")。"""
        if not french_clean_token(token):
            return "", "empty"
        cands = self.map_candidates(token)
        if not cands:
            return "", "unmapped"
        return cands[0][0], cands[0][1]


# ---------------------------------------------------------------- dry-run 统计
def _product_id(cis: str, denomination: str) -> str:
    """FR 产品 id：`FR-<CIS>`（与 ES-<nregistro> 同构；CIS 是官方注册号）。"""
    return f"{COUNTRY}-{slug(cis) or 'urn'}"


def _eu_overlap(db: sqlite3.Connection, products: list[dict]) -> dict:
    """与 `region='EU'` 层去重估计：**欧盟号精确对齐**（主）+ 名称 + 成分（辅）。

    CIS_bdpm 第 9 列就是欧盟号（`EU/1/01/185`，只有「Procédure centralisée」的 2,261 行有值），
    与 EU 层 `product.approval_id` 同一写法，可以直接等值比对；名称+成分只用于没有欧盟号的
    法国国别注册（它们是**法国本地审批**，本来就不该出现在 EU 层，命中要人工看一眼）。
    两层都保留（EU = 授权记录、FR = 上市记录），不合并、不去重入库。
    """
    eu_by_appr: dict[str, str] = {}
    eu_keys: dict[str, list[tuple[str, str]]] = {}
    for r in db.execute(
            "SELECT p.product_id, p.approval_id, nk.norm, "
            "       (SELECT GROUP_CONCAT(DISTINCT v.substance_id) FROM product_component pc "
            "        JOIN variant v ON v.variant_id = pc.variant_id "
            "        WHERE pc.product_id = p.product_id) AS subs "
            "FROM product p LEFT JOIN product_name pn ON pn.product_id = p.product_id "
            "LEFT JOIN name_key nk ON nk.key_id = pn.key_id "
            "WHERE p.region = 'EU'"):
        appr = (r["approval_id"] or "").strip()
        if appr:
            eu_by_appr.setdefault(appr, r["product_id"])
        if r["norm"]:
            eu_keys.setdefault(r["norm"], []).append((r["product_id"], r["subs"] or ""))
    eu_products = db.execute("SELECT COUNT(*) FROM product WHERE region='EU'").fetchone()[0]

    with_eu_no = [p for p in products if p["eu_number"]]
    matched = [p for p in with_eu_no if p["eu_number"] in eu_by_appr]
    unmatched_numbers = sorted({p["eu_number"] for p in with_eu_no
                                if p["eu_number"] not in eu_by_appr})
    # 名称同名的（用于看「同成分不同注册」的灰区，不合并）
    eu_names = set(eu_keys)
    name_hits = [p for p in products if p["name_norm"] and p["name_norm"] in eu_names]
    name_same_sub = 0
    for p in name_hits:
        subs = set(p["substance_ids"])
        if subs and any(set(s.split(",")) & subs for _pid, s in eu_keys[p["name_norm"]]):
            name_same_sub += 1
    # 去重估计：同一 EU 号在 FR 侧可能有多行（不同包装/历史 CIS）
    eu_numbers_in_fr = len({p["eu_number"] for p in with_eu_no})
    return {
        "eu_products": eu_products,
        "eu_layer_approval_ids": len(eu_by_appr),
        "fr_rows_with_eu_number": len(with_eu_no),
        "fr_distinct_eu_numbers": eu_numbers_in_fr,
        "fr_eu_number_matched_rows": len(matched),
        "fr_eu_number_matched_distinct": len({p["eu_number"] for p in matched}),
        "fr_eu_number_unmatched_distinct": len(unmatched_numbers),
        "fr_eu_number_unmatched_top10": unmatched_numbers[:10],
        "fr_eu_numbers_missing_in_fr": max(0, len(eu_by_appr) - eu_numbers_in_fr),
        "fr_products_name_in_eu": len(name_hits),
        "fr_products_name_and_substance_in_eu": name_same_sub,
        "rule": "欧盟号（CIS_bdpm col9）与 EU 层 approval_id 等值对齐；名称+成分仅作辅助核对。"
                "EU 层与 FR 层都保留（授权记录 vs 上市记录），不合并、不去重入库。",
        "samples": [{"fr": p["denomination"], "cis": p["cis"], "eu_number": p["eu_number"],
                     "eu_product_id": eu_by_appr.get(p["eu_number"])} for p in matched[:10]],
    }


def _dedupe_stats(products: list[dict]) -> dict:
    """FR 侧同身份多 CIS 的统计（名称归一 × 剂型 × 成分集合），只报告、不自动合并。

    同一个商品名在 BDPM 里常有多个 CIS（MAH 转移、历史注册、同品种不同申报）；
    产品身份按「国家 × 剂型 × 规格 × 活性成分」锁定，所以这些行在站上会落进同一个
    name_key 的候选集——这正是「商品名不是主键」的口径，不需要人为合并。
    """
    groups: dict[tuple[str, str, tuple[str, ...]], list[dict]] = {}
    for p in products:
        key = (p["name_norm"], p["form_base"], tuple(p["substance_ids"]))
        groups.setdefault(key, []).append(p)
    multi = {k: v for k, v in groups.items() if len(v) > 1}
    multi_active = {k: v for k, v in multi.items() if any(p["status"] == "active" for p in v)}
    return {
        "identity_groups": len(groups),
        "products": len(products),
        "groups_multi_cis": len(multi),
        "rows_in_multi_cis_groups": sum(len(v) for v in multi.values()),
        "groups_multi_cis_with_active": len(multi_active),
        "max_cis_per_group": max((len(v) for v in multi.values()), default=1),
        "top10": [{"name": v[0]["denomination"], "form_base": k[1], "n_cis": len(v),
                   "cis": [p["cis"] for p in v][:5]} for k, v in
                  sorted(multi.items(), key=lambda kv: len(kv[1]), reverse=True)[:10]],
        "note": "名称归一 + 剂型 + 成分集合相同但 CIS 不同的行**不合并**：CIS 是注册号，"
                "合并会丢注册事实；站上按 name_key 出候选集即可（§1.1 商品名不是主键）",
    }


def _collect(snap: dict, mapper: FrMapper, resolve) -> dict:
    """逐行解析并统计（只读；不产生任何写库语句）。"""
    st: Counter = Counter()
    forms: Counter = Counter()
    form_bases: Counter = Counter()
    routes: Counter = Counter()
    statuses: Counter = Counter()
    procedures: Counter = Counter()
    markets: Counter = Counter()
    units: Counter = Counter()
    unmapped: Counter = Counter()
    nature = Counter()
    refs: Counter = Counter()
    compo_by_cis: dict[str, list[dict]] = {}
    cip_by_cis: dict[str, list[dict]] = {}
    gener_by_cis: dict[str, dict] = {}
    for row in snap["compo"]:
        compo_by_cis.setdefault(row["cis"], []).append(row)
    for row in snap["cip"]:
        cip_by_cis.setdefault(row["cis"], []).append(row)
    for row in snap["gener"]:
        gener_by_cis.setdefault(_clean(row.get("cis")), row)

    products: list[dict] = []
    tokens_seen: set[str] = set()
    memo: dict[str, tuple[str, str, str]] = {}
    name_keys: set[str] = set()
    name_pairs: set[tuple[str, str]] = set()
    components_planned = 0
    components_with_strength = 0
    components_no_variant = 0
    products_all_mapped = 0
    products_partial = 0
    products_none = 0
    products_with_component = 0
    products_with_strength = 0
    packages_total = 0
    packages_multi = 0
    packages_active = 0
    forms_with_base = 0
    samples: list[dict] = []

    for row in snap["cis"]:
        cis = _clean(row["cis"])
        denom = _clean(row["denomination"])
        forme = _clean(row["forme"])
        st["rows"] += 1
        status, status_raw = map_status(row)
        statuses[status] += 1
        procedures[_clean(row["procedure"]) or "(空)"] += 1
        markets[_clean(row["etat_commercialisation"]) or "(空)"] += 1
        forms[forme or "(空)"] += 1
        base = fr_form_base(forme, row["voies"])
        form_bases[base] += 1
        if base not in {"other", "unknown", ""}:
            forms_with_base += 1
        else:
            st["form_other_or_unknown"] += 1
        for rt in split_routes(row["voies"]):
            routes[rt] += 1
        # 包装（CIP）
        packs = cip_by_cis.get(cis, [])
        packages_total += len(packs)
        if len(packs) > 1:
            packages_multi += 1
        packages_active += sum(1 for p in packs
                               if "active" in _fold(p.get("statut_presentation", "")))
        eu_number = _clean(row.get("eu_number", "")).rstrip("/").strip()
        if eu_number:
            st["rows_with_eu_number"] += 1
        procedure = _clean(row.get("procedure"))
        if "importation" in _fold(procedure):
            st["parallel_import_products"] += 1
        # 成分（COMPO）
        comps = compo_by_cis.get(cis, [])
        nat_rows = 0
        homeo_rows = 0
        mapped: list[tuple[str, str, str, dict | None]] = []
        for c in comps:
            nat = _clean(c.get("nature"))
            nature[nat or "(空)"] += 1
            if nat.upper().startswith("FT"):
                st["compo_ft_rows"] += 1
                continue          # 治疗分组分（复用的「分组」行）不进 product_component
            nat_rows += 1
            st["sa_rows"] += 1
            raw = _clean(c.get("designation"))
            is_homeo = is_homeopathic(raw)
            if is_homeo:
                homeo_rows += 1
            dosage = parse_dosage(c.get("dosage", ""), c.get("reference_dosage", ""))
            if dosage:
                units[dosage["unit"] or "(无单位)"] += 1
                if dosage["per_volume_unit"]:
                    refs[dosage["per_volume_unit"]] += 1
                st["sa_rows_with_dosage"] += 1
            elif _clean(c.get("dosage")):
                st["sa_rows_dosage_unparsed"] += 1
            else:
                st["sa_rows_dosage_empty"] += 1
            for token in split_composition(raw):
                tokens_seen.add(token)
                st["ingredient_tokens"] += 1
                if is_homeo:
                    st["homeo_tokens"] += 1
                hit = memo.get(token)
                if hit is None:
                    cands = mapper.map_candidates(token)
                    chosen = next(((csid, cmethod, ccand) for csid, cmethod, ccand in cands
                                   if resolve(csid, ccand)), None)
                    if chosen is None and cands:
                        # 有 substance 但没有 variant：token 映射上，component 写不进去
                        hit = (cands[0][0], cands[0][1] + "+no-variant", cands[0][2])
                    else:
                        hit = chosen or ("", "unmapped", "")
                    memo[token] = hit
                sid, method, cand_str = hit
                if sid:
                    st["ingredient_tokens_mapped"] += 1
                    if not is_homeo:
                        st["ingredient_tokens_mapped_nonhomeo"] += 1
                mapped.append((token, sid, method, dosage, cand_str))
        if homeo_rows:
            st["homeo_products"] += 1
        st["composition_rows"] += nat_rows
        n_map = sum(1 for row_ in mapped if row_[1] and "+no-variant" not in row_[2])
        if mapped and n_map == len(mapped):
            products_all_mapped += 1
        elif mapped and n_map:
            products_partial += 1
        elif mapped:
            products_none += 1
        planned = []
        for token, sid, method, dosage, cand_str in mapped:
            if not sid or "+no-variant" in method:
                unmapped[token] += 1
                st[f"map_method:{method}"] += 1
                continue
            vid = resolve(sid, cand_str or token)
            if not vid:
                components_no_variant += 1
                continue
            components_planned += 1
            if dosage:
                components_with_strength += 1
            planned.append({"token": token, "substance_id": sid, "variant_id": vid,
                            "method": method, "strength": dosage,
                            "strength_source": "composition" if dosage else ""})
        # v0.11.5（task-68）规格补足：composition 没给剂量、且只有 1 个 component 时，
        # 用品名里的规格补（BDPM 的 dosage 空值行 2,764 条，其中 2,400 个产品品名里有规格）。
        strength_fallback = False
        if planned and not any(c["strength"] for c in planned) and len(planned) == 1:
            name_strengths = parse_name_strengths(denom)
            if len(name_strengths) == 1:
                planned[0]["strength"] = name_strengths[0]
                planned[0]["strength_source"] = "name"
                components_with_strength += 1
                st["components_strength_from_name"] += 1
                strength_fallback = True
        if planned:
            products_with_component += 1
            st["products_with_component"] += 1
            if any(c["strength"] for c in planned):
                products_with_strength += 1
                st["products_with_strength"] += 1
                if strength_fallback:
                    st["products_strength_from_name"] += 1
                else:
                    st["products_strength_from_composition"] += 1
        # 名称键（与库里 name_key 比对；复用 normalize()，与其它市场同口径）
        nm = normalize(denom)
        if not nm.is_empty:
            name_keys.add(nm.norm)
            name_pairs.add((nm.norm, denom))
        gener = gener_by_cis.get(cis)
        row_routes = split_routes(row["voies"])
        pack_summary = ""
        if packs:
            first = _clean(packs[0]["libelle"])
            pack_summary = first[:200] + (f" (+{len(packs) - 1})" if len(packs) > 1 else "")
        products.append({
            "product_id": _product_id(cis, denom), "cis": cis, "denomination": denom,
            "name_norm": "" if nm.is_empty else nm.norm,
            "key_compact": "" if nm.is_empty else nm.compact,
            "key_script": "latin" if nm.is_empty else nm.script,
            "forme": forme, "form_base": base, "release": release_of(denom, forme),
            "routes": row_routes, "route": "; ".join(row_routes) if row_routes else None,
            "status": status, "status_raw": status_raw,
            "procedure": procedure, "mah": _clean(row["titulaires"]),
            "amm_date": _clean(row["date_amm"]), "surveillance": _clean(row["surveillance_renforcee"]),
            "dispo_status": _clean(row.get("dispo_status", "")), "eu_number": eu_number,
            "homeo": bool(homeo_rows),
            "parallel_import": "importation" in _fold(procedure),
            "pack": pack_summary or None,
            "packages": [{"cip7": p["cip7"], "libelle": p["libelle"],
                          "statut": p["statut_presentation"],
                          "cip13": p["cip13"]} for p in packs],
            "n_packages": len(packs),
            "generic_group": _clean(gener.get("groupe")) if gener else "",
            "generic_type": _clean(gener.get("type")) if gener else "",
            "generic_label": _clean(gener.get("libelle_groupe")) if gener else "",
            "components": planned,
            "substance_ids": sorted({c["substance_id"] for c in planned}),
            "unmapped_tokens": sorted({m[0] for m in mapped if not m[1]}),
        })
        if len(samples) < 6:
            samples.append({
                "cis": cis, "denomination": denom, "forme": forme, "form_base": base,
                "routes": split_routes(row["voies"]), "status": status,
                "etat_commercialisation": row["etat_commercialisation"],
                "procedure": _clean(row["procedure"]), "mah": _clean(row["titulaires"]),
                "n_packages": len(packs),
                "components": [{"token": c["token"], "sid": c["substance_id"] or "未映射",
                                "strength": c["strength"]} for c in planned],
                "unmapped": [m[0] for m in mapped if not m[1]],
            })

    st["products"] = len(products)
    st["packages_total"] = packages_total
    st["packages_multi_product"] = packages_multi
    st["packages_active"] = packages_active
    st["form_base_ok"] = forms_with_base
    st["components_planned"] = components_planned
    st["components_with_strength"] = components_with_strength
    st["components_no_variant"] = components_no_variant
    st["products_all_mapped"] = products_all_mapped
    st["products_partial_mapped"] = products_partial
    st["products_none_mapped"] = products_none
    st["unique_tokens"] = len(tokens_seen)
    st["ingredient_tokens_nonhomeo"] = st["ingredient_tokens"] - st["homeo_tokens"]
    cis_ids = {_clean(r["cis"]) for r in snap["cis"]}
    orphan_cip = [_clean(r["cis"]) for r in snap["cip"] if _clean(r["cis"]) not in cis_ids]
    st["cip_rows_orphan"] = len(orphan_cip)
    st["cip_cis_orphan"] = len(set(orphan_cip))
    st["compo_rows_orphan"] = sum(1 for r in snap["compo"] if _clean(r["cis"]) not in cis_ids)
    st["products_with_packages"] = sum(1 for p in products if p["n_packages"])
    st["products_with_eu_number"] = sum(1 for p in products if p["eu_number"])
    st["products_with_generic_group"] = sum(1 for p in products if p["generic_group"])
    st["generic_groups"] = len({p["generic_group"] for p in products if p["generic_group"]})
    st["products_active"] = sum(1 for p in products if p["status"] == "active")
    # v0.11.5（task-6）：黑名单 / 残串丢弃计数（「丢弃并计数」，进 dry-run JSON）
    for gkey in ("blocked_substance_hits", "residual_tokens", "residual_candidates_dropped"):
        st[f"fr_guard_{gkey}"] = mapper.stats.get(gkey, 0)
    gener_types = Counter(p["generic_type"] or "(空)" for p in products if p["generic_group"])
    return {
        "stats": st, "products": products, "forms": forms, "form_bases": form_bases,
        "routes": routes, "statuses": statuses, "procedures": procedures, "markets": markets,
        "units": units, "unmapped": unmapped, "nature": nature, "refs": refs,
        "gener_types": gener_types, "name_keys": name_keys, "name_pairs": name_pairs,
        "samples": samples,
    }


# ---------------------------------------------------------------- 写库 / 撤销（task-54）
def _connect(db_path: Path, write: bool = False) -> sqlite3.Connection:
    """写库连接开 `foreign_keys=ON`；只读用 `mode=ro`（本节之外一律只读）。"""
    if write:
        db = sqlite3.connect(db_path, timeout=180)
        db.execute("PRAGMA foreign_keys=ON")
    else:
        db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=120)
    db.row_factory = sqlite3.Row
    return db


def _guard_real(db_path: Path, action: str, allow_real: bool) -> None:
    """真实库写保护（沿用 `etl/ingest_eu.py`）：没有 `--allow-real` 只允许写 `.tmp/` 副本。"""
    try:
        is_real = db_path.resolve() == REAL_DB.resolve()
    except OSError:
        is_real = False
    if is_real and not allow_real:
        raise SystemExit(
            f"拒绝在真实库 {db_path} 执行 {action}：DB 窗口未开（排下一会话）。\n"
            "先在副本 `.tmp/fr-ingest/` 跑完整链路；确需写真实库时加 --allow-real，"
            "并先备份 data/drugs.db、按 reports/2026-11-13-fr-apply-ready.md 的清单执行。")
    if is_real:
        print(f"!! 警告：正在对真实库 {db_path} 执行 {action}（--allow-real），"
              "请确认已备份并持有 manifest。")


def _require_country_schema(db: sqlite3.Connection) -> None:
    """`product.country` 的 CHECK 必须包含 'FR'，否则产品行写不进去。"""
    row = db.execute("SELECT sql FROM sqlite_master WHERE name='product'").fetchone()
    sql = (row["sql"] if row else "") or ""
    if "'FR'" not in sql:
        raise SystemExit(
            "product.country 的 CHECK 枚举没有 'FR'：写库窗口第一步必须先做 schema 迁移"
            "（db/schema.sql 加 FR + db/init_db.py 幂等重建 product 表）。\n"
            "库副本上可先用 `.tmp/migrate_fr_copy.py` 演练同一迁移（本工位不改 db/）。")


def _table_counts(db: sqlite3.Connection) -> dict:
    """逐表计数（写前/写后/回滚后用同一口径）。"""
    return {
        "product": db.execute("SELECT COUNT(*) FROM product").fetchone()[0],
        "product_fr": db.execute(
            "SELECT COUNT(*) FROM product WHERE country=? AND source_id=?",
            (COUNTRY, SOURCE_ID)).fetchone()[0],
        "product_component": db.execute("SELECT COUNT(*) FROM product_component").fetchone()[0],
        "product_name": db.execute("SELECT COUNT(*) FROM product_name").fetchone()[0],
        "name_key": db.execute("SELECT COUNT(*) FROM name_key").fetchone()[0],
        "name_variant": db.execute("SELECT COUNT(*) FROM name_variant").fetchone()[0],
        "source": db.execute("SELECT COUNT(*) FROM source").fetchone()[0],
        "ingest_run": db.execute("SELECT COUNT(*) FROM ingest_run").fetchone()[0],
    }


def _insert_source(db: sqlite3.Connection) -> tuple[bool, dict | None]:
    """写/更新 `bdpm_fr` 的 source 行 → (写前是否存在, 写前行快照)。"""
    before = db.execute("SELECT * FROM source WHERE source_id=?", (SOURCE_ID,)).fetchone()
    db.execute(
        "INSERT INTO source (source_id, name, url, license, license_url, retrieved_at,"
        " data_as_of, data_as_of_note, notes) VALUES (?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(source_id) DO UPDATE SET name=excluded.name, url=excluded.url,"
        " license=excluded.license, license_url=excluded.license_url,"
        " retrieved_at=excluded.retrieved_at, data_as_of=excluded.data_as_of,"
        " data_as_of_note=excluded.data_as_of_note, notes=excluded.notes",
        (SOURCE_ID, SOURCE_META["name"], SOURCE_META["url"], SOURCE_META["license"],
         SOURCE_META["license_url"], TODAY, SOURCE_META["data_as_of"],
         SOURCE_META["data_as_of_note"], SOURCE_META["notes"]))
    return (before is not None), (dict(before) if before else None)


def _product_note(p: dict) -> str:
    bits = [
        "法国 BDPM（CIS=" + p["cis"] + "）；BDPM 的 État de commercialisation 是上市状态，"
        "不代表当前在售",
        f"procedure: {p['procedure']}" if p.get("procedure") else "",
        f"AMM: {p['amm_date']}" if p.get("amm_date") else "",
        f"EU: {p['eu_number']}" if p.get("eu_number") else "",
        f"MAH: {p['mah']}" if p.get("mah") else "",
        f"surveillance renforcée: {p['surveillance']}" if p.get("surveillance") else "",
        f"dispo: {p['dispo_status']}" if p.get("dispo_status") else "",
        "平行进口（Autorisation d'importation）" if p.get("parallel_import") else "",
        "顺势疗法（HOMÉOPATHIQUES）" if p.get("homeo") else "",
        f"packages: {p['n_packages']}" if p.get("n_packages") else "",
    ]
    return " · ".join(b for b in bits if b)[:500]


def _write_rows(db: sqlite3.Connection, products: list[dict], run_id: str,
                rows_in: int) -> dict:
    """把 FR 国别层写进正式表（调用方管事务）；返回按表统计的写入行数。"""
    written: Counter = Counter()
    for p in products:
        pid = p["product_id"]
        written["product"] += db.execute(
            "INSERT OR REPLACE INTO product (product_id, country, region, dosage_form,"
            " form_base, route, release, pack, mah, approval_id, category, is_branded,"
            " status, status_date, source_id, source_url, retrieved_at, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, COUNTRY, None, p["forme"] or "unknown", p["form_base"] or "other",
             p.get("route"), p["release"], p.get("pack"), p.get("mah") or None,
             p["cis"], p.get("procedure") or None, 1, p["status"], None,
             SOURCE_ID, DOWNLOAD_PAGE, TODAY, _product_note(p))).rowcount
        key = p["name_norm"]
        if key:
            written["name_key"] += db.execute(
                "INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                " VALUES (?,?,?,?)",
                (key, key, p.get("key_compact") or key.replace(" ", ""),
                 p.get("key_script") or "latin")).rowcount
            written["name_variant"] += db.execute(
                "INSERT OR IGNORE INTO name_variant (key_id, raw, source_id) VALUES (?,?,?)",
                (key, p["denomination"], SOURCE_ID)).rowcount
            written["product_name"] += db.execute(
                "INSERT OR IGNORE INTO product_name (product_id, key_id, name_type, is_primary)"
                " VALUES (?,?,?,?)", (pid, key, "trade", 1)).rowcount
        for ord_, comp in enumerate(p.get("components") or []):
            s = comp.get("strength") or {}
            written["product_component"] += db.execute(
                "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                " strength_value, strength_unit, per_volume_value, per_volume_unit)"
                " VALUES (?,?,?,?,?,?,?)",
                (pid, ord_, comp["variant_id"], s.get("value"), s.get("unit"),
                 s.get("per_volume_value"), s.get("per_volume_unit"))).rowcount
    written["ingest_run"] += db.execute(
        "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
        " rows_in, rows_kept, rows_rejected, status, note) VALUES (?,?,?,?,?,?,?,?,?)",
        (run_id, SOURCE_ID, TODAY, _now(), rows_in, len(products),
         max(0, rows_in - len(products)), "ok",
         json.dumps({"country": COUNTRY, "layer": "country", "source_id": SOURCE_ID,
                     "components": written.get("product_component", 0),
                     "note": "BDPM 医保/药价基准数据；不是上市注册库"}, ensure_ascii=False))
    ).rowcount
    return dict(written)


def _collect_for(db_path: Path, src: Path) -> tuple[dict, dict]:
    """只读打开 → 解析 → 统计；`--dry-run` 与 `--apply` 共用，保证「预测的就是要写的」。"""
    snap = load_snapshot(src)
    db = _connect_ro(db_path)
    try:
        mapper = FrMapper(db)
        resolve = _variant_resolver(db)
        existing_keys = {r[0] for r in db.execute("SELECT key_id FROM name_key")}
        existing_pairs = {(r[0], r[1]) for r in db.execute("SELECT key_id, raw FROM name_variant")}
        before_counts = _table_counts(db)
        result = _collect(snap, mapper, resolve)
        overlap = _eu_overlap(db, result["products"])
        result["before_counts"] = before_counts
        result["overlap"] = overlap
        result["existing_keys"] = existing_keys
        result["existing_pairs"] = existing_pairs
        result["db_products"] = before_counts["product"]
    finally:
        db.close()
    return result, snap


def cmd_apply(args: argparse.Namespace) -> int:
    """写库（默认只允许副本）：source + 产品/组件/名称 + ingest_run；幂等（同 source 先删后写）。"""
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    _guard_real(db_path, "apply", args.allow_real)
    if not db_path.exists():
        raise SystemExit(f"库不存在：{db_path}（先跑 --prepare-copy）")
    manifest_path = args.manifest if args.manifest.is_absolute() else (ROOT / args.manifest)
    src = args.src if args.src.is_absolute() else (ROOT / args.src)
    t0 = time.perf_counter()
    db_sha_before = _sha256_file(db_path)
    result, snap = _collect_for(db_path, src)
    products = result["products"]
    st = result["stats"]
    run_id = f"{SOURCE_ID}-{TODAY}"
    before = result["before_counts"]

    db = _connect(db_path, write=True)
    try:
        _require_country_schema(db)
        db.execute("BEGIN IMMEDIATE")
        source_existed, source_before = _insert_source(db)
        removed_products = db.execute(
            "DELETE FROM product WHERE country=? AND source_id=?",
            (COUNTRY, SOURCE_ID)).rowcount
        written = _write_rows(db, products, run_id, rows_in=len(snap["cis"]))
        db.commit()
        after = _table_counts(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    db_sha_after = _sha256_file(db_path)
    created_keys = sorted({p["name_norm"] for p in products if p["name_norm"]}
                          - result["existing_keys"])
    created_pairs = sorted({(p["name_norm"], p["denomination"])
                            for p in products if p["name_norm"]}
                           - result["existing_pairs"])
    manifest = {
        "tool": "etl/markets/fr.py",
        "db": str(db_path),
        "db_is_real": db_path.resolve() == REAL_DB.resolve(),
        "country": COUNTRY,
        "source_id": SOURCE_ID,
        "run_id": run_id,
        "created_at": _now(),
        "data_as_of": SOURCE_META["data_as_of"],
        "snapshot": {name: {"bytes": (src / name).stat().st_size,
                            "sha256": _sha256_file(src / name)} for name in FILES},
        "db_sha256_before": db_sha_before,
        "db_sha256_after": db_sha_after,
        "product_ids": [p["product_id"] for p in products],
        "created_name_keys": created_keys,
        "created_name_variants": [list(x) for x in created_pairs],
        "source_existed": source_existed,
        "source_before": source_before,
        "counts_before": before,
        "counts_after": after,
        "counts_planned": {
            "products": len(products), "components": st["components_planned"],
            "name_keys_new": len(created_keys), "name_variants_new": len(created_pairs),
            "substance_new": 0,
        },
        "written": written,
        "removed_products_before_write": removed_products,
        "rollback_hint": (
            "python etl/markets/fr.py --rollback --allow-real --db <同一个库> --manifest <本文件>；"
            "或从备份恢复 data/drugs.db（窗口前必做备份）。校验："
            "SELECT COUNT(*) FROM product WHERE country='FR' AND source_id='bdpm_fr' 应为 0，"
            "coverage 不应有 FR 行。"),
    }
    _write_json(manifest_path, manifest)
    elapsed = round(time.perf_counter() - t0, 2)
    print("=== FR（BDPM）写入完成 ===")
    print(json.dumps({"written": written, "counts_before": before, "counts_after": after},
                     ensure_ascii=False, indent=1))
    print(f"  旧 FR 行删除 {removed_products} · 撤销清单 {manifest_path}")
    print(f"  db sha256 {db_sha_before[:16]}… → {db_sha_after[:16]}… · 耗时 {elapsed}s")
    return 0


def _rollback_targets(manifest: dict) -> dict:
    """从 manifest 解析回滚目标（纯函数；`--rollback` 与 `--self-check` 共用）。"""
    if manifest.get("source_id") != SOURCE_ID or manifest.get("country") != COUNTRY:
        raise SystemExit("manifest 的 source_id/country 与 FR 不匹配，拒绝执行")
    return {
        "product_ids": list(manifest.get("product_ids") or []),
        "name_keys": list(manifest.get("created_name_keys") or []),
        "name_variants": [tuple(x) for x in (manifest.get("created_name_variants") or [])],
        "run_id": manifest.get("run_id") or "",
        "source_existed": bool(manifest.get("source_existed")),
        "source_before": manifest.get("source_before"),
        "counts_before": manifest.get("counts_before") or {},
    }


def cmd_rollback(args: argparse.Namespace) -> int:
    """按 manifest 只删本次写入的行（保护既有数据），并逐表核对是否回到写前计数。"""
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    _guard_real(db_path, "rollback", args.allow_real)
    manifest_path = args.manifest if args.manifest.is_absolute() else (ROOT / args.manifest)
    if not manifest_path.exists():
        raise SystemExit(f"找不到撤销清单：{manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    targets = _rollback_targets(data)
    db = _connect(db_path, write=True)
    removed = Counter()
    try:
        db.execute("BEGIN IMMEDIATE")
        for pid in targets["product_ids"]:
            removed["product"] += db.execute(
                "DELETE FROM product WHERE product_id=? AND country=? AND source_id=?",
                (pid, COUNTRY, SOURCE_ID)).rowcount
        removed["ingest_run"] += db.execute(
            "DELETE FROM ingest_run WHERE run_id=?", (targets["run_id"],)).rowcount
        for key, raw in targets["name_variants"]:
            removed["name_variant"] += db.execute(
                "DELETE FROM name_variant WHERE key_id=? AND raw=? AND source_id=?",
                (key, raw, SOURCE_ID)).rowcount
        for key in targets["name_keys"]:
            if not db.execute("SELECT 1 FROM product_name WHERE key_id=? LIMIT 1",
                              (key,)).fetchone():
                removed["name_variant"] += db.execute(
                    "DELETE FROM name_variant WHERE key_id=? AND source_id=?",
                    (key, SOURCE_ID)).rowcount
                removed["name_key"] += db.execute(
                    "DELETE FROM name_key WHERE key_id=?", (key,)).rowcount
        if targets["source_existed"]:
            before = targets["source_before"] or {}
            if before:
                db.execute(
                    "UPDATE source SET name=?, url=?, license=?, license_url=?, retrieved_at=?,"
                    " data_as_of=?, data_as_of_note=?, notes=? WHERE source_id=?",
                    (before.get("name"), before.get("url"), before.get("license"),
                     before.get("license_url"), before.get("retrieved_at"),
                     before.get("data_as_of"), before.get("data_as_of_note"),
                     before.get("notes"), SOURCE_ID))
        else:
            still = db.execute(
                "SELECT COUNT(*) FROM product WHERE source_id=? AND country=?",
                (SOURCE_ID, COUNTRY)).fetchone()[0]
            if not still:
                removed["source"] += db.execute(
                    "DELETE FROM source WHERE source_id=?", (SOURCE_ID,)).rowcount
        db.commit()
        after = _table_counts(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    expected = targets["counts_before"]
    diff = {k: after.get(k, 0) - int(expected.get(k, 0)) for k in after}
    nonzero = {k: v for k, v in diff.items() if v}
    print("=== FR（BDPM）回滚完成 ===")
    print(json.dumps({"removed": dict(removed), "counts_after": after,
                      "diff_vs_counts_before": diff}, ensure_ascii=False, indent=1))
    if nonzero:
        print(f"  !! 与写前计数不一致：{nonzero}")
        return 1
    print("  逐表差异 0（已回到写前基线）")
    return 0


def prepare_copy(real: Path, copy: Path, force: bool = False) -> dict:
    """真库 → `.tmp/fr-ingest/drugs_fr_copy.db`（只读复制；已存在且大小一致则复用）。"""
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
            "seconds": round(time.perf_counter() - t0, 1),
            "source": str(real), "source_mtime": datetime.fromtimestamp(
                real.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")}


def cmd_prepare_copy(args: argparse.Namespace) -> int:
    info = prepare_copy(REAL_DB, DB_COPY, force=args.force)
    print(f"拷贝就绪：{info['path']} · {info['bytes']:,} B"
          f" · {'新拷贝' if info.get('copied') else '复用现有副本'}"
          f"{f'（{info.get('seconds')}s）' if info.get('seconds') else ''}")
    return 0


def _db_fr_baseline(db: sqlite3.Connection) -> dict | None:
    """当前库里 FR 行的覆盖率（before 口径，与覆盖页 build.py 的 SQL 一致）。"""
    n = db.execute("SELECT COUNT(*) FROM product WHERE country=?", (COUNTRY,)).fetchone()[0]
    if not n:
        return None
    mapped = db.execute(
        "SELECT COUNT(DISTINCT p.product_id) FROM product p "
        "JOIN product_component pc ON pc.product_id=p.product_id WHERE p.country=?",
        (COUNTRY,)).fetchone()[0]
    spec = db.execute(
        "SELECT COUNT(DISTINCT p.product_id) FROM product p "
        "JOIN product_component pc ON pc.product_id=p.product_id "
        "WHERE p.country=? AND pc.strength_value IS NOT NULL", (COUNTRY,)).fetchone()[0]
    form = db.execute(
        "SELECT COUNT(*) FROM product WHERE country=? AND form_base IS NOT NULL "
        "AND form_base NOT IN ('other','unknown','')", (COUNTRY,)).fetchone()[0]
    return {
        "products": n,
        "products_with_component": mapped,
        "mapping_pct": round(mapped / n * 100, 1),
        "products_with_strength": spec,
        "strength_pct": round(spec / n * 100, 1),
        "form_mapped": form,
        "form_pct": round(form / n * 100, 1),
    }


def cmd_dry_run(args: argparse.Namespace) -> int:
    """读缓存 → 解析 → 统计；**只读**开库副本，真库不碰、不写任何库。"""
    src = args.src if args.src.is_absolute() else (ROOT / args.src)
    db_path = args.db if args.db.is_absolute() else (ROOT / args.db)
    real = REAL_DB.resolve()
    cand = db_path.resolve()
    if cand == real:
        raise SystemExit("拒绝在真库上干跑：请用 `.tmp/fr-ingest/` 的库副本"
                         "（先跑 `python etl/markets/fr.py --prepare-copy`，或加 --copy）")
    if not db_path.exists():
        if not args.copy:
            raise SystemExit(f"库副本不存在：{db_path}（加 --copy 先复制真库，或跑 --prepare-copy）")
        info = prepare_copy(REAL_DB, db_path)
        print(f"  已复制真库 → {db_path} · {info['bytes']:,} B")
    t0 = time.perf_counter()
    snap = load_snapshot(src)
    db = _connect_ro(db_path)
    try:
        mapper = FrMapper(db)
        resolve = _variant_resolver(db)
        existing_keys = {r[0] for r in db.execute("SELECT key_id FROM name_key")}
        existing_pairs = {(r[0], r[1]) for r in db.execute("SELECT key_id, raw FROM name_variant")}
        db_products = db.execute("SELECT COUNT(*) FROM product").fetchone()[0]
        result = _collect(snap, mapper, resolve)
        overlap = _eu_overlap(db, result["products"])
        before = _db_fr_baseline(db)
    finally:
        db.close()
    elapsed = round(time.perf_counter() - t0, 2)

    st = result["stats"]
    after = {
        "products": st["products"],
        "products_with_component": st["products_with_component"],
        "mapping_pct": round(st["products_with_component"] / n_rows * 100, 1)
        if (n_rows := max(1, st["products"])) else 0.0,
        "products_with_strength": st["products_with_strength"],
        "strength_pct": round(st["products_with_strength"] / max(1, st["products"]) * 100, 1),
        "form_mapped": st["form_base_ok"],
        "form_pct": round(st["form_base_ok"] / max(1, st["products"]) * 100, 1),
    }
    new_keys = sorted(result["name_keys"] - existing_keys)
    new_variants = sorted(p for p in result["name_pairs"] if p not in existing_pairs)
    n_rows = max(1, st["products"])
    n_tokens = max(1, st["ingredient_tokens"])
    unmapped_unique = len(result["unmapped"])

    summary = {
        "generated_at": _now(),
        "tool": "etl/markets/fr.py",
        "mode": "dry-run（只读；库副本，不写库）",
        "licence": {
            "source_id": SOURCE_ID,
            "status": "✅ A 类：Licence Ouverte 2.0（data.gouv.fr license=fr-lo）+ 下载页条款允许再分发",
            "can_ingest": True,
            "obligations": ["不得篡改数据", "注明来源 base-donnees-publique.medicaments.gouv.fr",
                            "注明数据更新日期", "不得暗示 ANSM/HAS/UNCAM 背书"],
            "apply_flag": "--apply 已可用（默认只允许 .tmp/ 副本；真库需 --allow-real + 备份）",
        },
        "db": {"path": str(db_path), "mode": "read-only(mode=ro)", "products": db_products,
               "is_real_db": False},
        "snapshot": {
            "dir": str(src.relative_to(ROOT)) if src.is_relative_to(ROOT) else str(src),
            "files": {name: {"bytes": (src / name).stat().st_size,
                             "sha256": _sha256_file(src / name),
                             "rows": s["rows"],
                             "encoding": s["encoding"],
                             "bad_column_count": s.get("bad_column_count", 0),
                             "columns": len(_columns_for(name))}
                      for name, s in snap["stats"].items()},
            "url": FILE_URL.format(name="CIS_bdpm.txt"),
        },
        "rows": {
            "specialites": st["products"],
            "composition_rows": st["composition_rows"],
            "composition_ft_rows": st["compo_ft_rows"],
            "sa_rows": st["sa_rows"],
            "sa_rows_with_dosage": st["sa_rows_with_dosage"],
            "sa_rows_dosage_unparsed": st["sa_rows_dosage_unparsed"],
            "sa_rows_dosage_empty": st["sa_rows_dosage_empty"],
            "presentations": st["packages_total"],
            "presentations_orphan": st["cip_rows_orphan"],
            "generic_group_rows": len(snap["gener"]),
        },
        "status": {
            "distinct": len(result["statuses"]),
            "counts": dict(result["statuses"]),
            "active": st["products_active"],
            "etat_commercialisation": result["markets"].most_common(8),
            "procedure": result["procedures"].most_common(8),
            "parallel_import_products": st["parallel_import_products"],
        },
        "dosage_form": {
            "source": "BDPM orme pharmaceutique（结构化字段）+ oie d'administration 兜底；不从品名猜",
            "distinct": len(result["forms"]),
            "top15": result["forms"].most_common(15),
            "form_base": result["form_bases"].most_common(18),
            "form_base_ok": st["form_base_ok"],
            "form_base_ok_pct": round(st["form_base_ok"] / n_rows * 100, 1),
            "form_other_or_unknown": st["form_other_or_unknown"],
            "form_other_pct": round(st["form_other_or_unknown"] / n_rows * 100, 1),
        },
        "route": {"distinct": len(result["routes"]), "top10": result["routes"].most_common(10)},
        "packages": {
            "total": st["packages_total"],
            "products_with_packages": st["products_with_packages"],
            "products_without_package": st["products"] - st["products_with_packages"],
            "products_multi_package": st["packages_multi_product"],
            "presentations_active": st["packages_active"],
            "note": "product 粒度 = 一个 CIS（与 ES 的 nregistro 同构）；包装只做展示，不拆成多产品",
        },
        "generics": {
            "rows": len(snap["gener"]),
            "groups": st["generic_groups"],
            "products_in_generic_group": st["products_with_generic_group"],
            "type_counts": result["gener_types"].most_common(8),
            "note": "BDPM 仿制药组：groupe / libellé / CIS / type（0=princeps 见口径待确认）；"
                    "只作「同组」事实，不做替代推荐（§1.3）",
        },
        "strength": {
            "source": "CIS_COMPO_bdpm dosage + référence de dosage（不换算、不猜）",
            "sa_rows": st["sa_rows"],
            "sa_rows_with_dosage": st["sa_rows_with_dosage"],
            "sa_rows_with_dosage_pct": round(
                st["sa_rows_with_dosage"] / max(1, st["sa_rows"]) * 100, 1),
            "sa_rows_dosage_empty": st["sa_rows_dosage_empty"],
            "sa_rows_dosage_unparsed": st["sa_rows_dosage_unparsed"],
            "components_with_strength": st["components_with_strength"],
            "components_total": st["components_planned"],
            "components_with_strength_pct": round(
                st["components_with_strength"] / max(1, st["components_planned"]) * 100, 1),
            "components_from_composition": st["components_with_strength"]
            - st["components_strength_from_name"],
            "components_from_name": st["components_strength_from_name"],
            "products_with_component": st["products_with_component"],
            "products_with_strength": st["products_with_strength"],
            "products_with_strength_pct": round(
                st["products_with_strength"] / n_rows * 100, 1),
            "products_strength_from_composition": st["products_strength_from_composition"],
            "products_strength_from_name": st["products_strength_from_name"],
            "units_top": result["units"].most_common(12),
            "per_volume_units": result["refs"].most_common(8),
            "note": "顺势疗法的 `2CH à 30CH …` 不是数值剂量（不解析）；空 dosage 保持 NULL，不猜。",
        },
        "substance": {
            "tokens": st["ingredient_tokens"],
            "tokens_mapped": st["ingredient_tokens_mapped"],
            "token_rate_pct": round(st["ingredient_tokens_mapped"] / n_tokens * 100, 1),
            "tokens_nonhomeo": st["ingredient_tokens_nonhomeo"],
            "tokens_mapped_nonhomeo": st["ingredient_tokens_mapped_nonhomeo"],
            "token_rate_nonhomeo_pct": round(
                st["ingredient_tokens_mapped_nonhomeo"]
                / max(1, st["ingredient_tokens_nonhomeo"]) * 100, 1),
            "unique_tokens": st["unique_tokens"],
            "unmapped_unique": unmapped_unique,
            "unmapped_top30": result["unmapped"].most_common(30),
            "products_all_mapped": st["products_all_mapped"],
            "products_partial_mapped": st["products_partial_mapped"],
            "products_none_mapped": st["products_none_mapped"],
            "nature": result["nature"].most_common(6),
            "bridge": "WHO INN 法语名（data/who_inn_names.csv inn_fr → inn_en）+ 法语拼写/盐名候选，"
                      "命中由库里 substance 决定；不新增 substance",
            "guard": {
                "blocked_substances": list(FR_BLOCKED_SUBSTANCES) + ["cn-*"],
                "blocked_substance_hits": st["fr_guard_blocked_substance_hits"],
                "residual_tokens": st["fr_guard_residual_tokens"],
                "residual_candidates_dropped": st["fr_guard_residual_candidates_dropped"],
                "note": "task-6：泛称离子 / cn-* 物质与无实词残串不映射（丢弃并计数），"
                        "宁可没有 component 也不写粗略成分",
            },
        },
        "homeopathy": {
            "products": st["homeo_products"],
            "sa_rows": st["homeo_tokens"],
            "token_share_pct": round(st["homeo_tokens"] / n_tokens * 100, 1),
            "note": "顺势疗法成分（`POUR PRÉPARATIONS HOMÉOPATHIQUES`）没有 INN/数值剂量；"
                    "单独统计，不硬映射、不入 component",
        },
        "data_quality": {
            "cip_rows_orphan": st["cip_rows_orphan"],
            "cip_cis_orphan": st["cip_cis_orphan"],
            "compo_rows_orphan": st["compo_rows_orphan"],
            "products_without_component": st["products"] - st["products_with_component"],
            "products_without_strength": st["products"] - st["products_with_strength"],
            "note": "CIP 里有、CIS_bdpm 里没有的包装行（旧注册残留）：只统计，不入库",
        },
        "eu_overlap": overlap,
        "dedupe": _dedupe_stats(result["products"]),
        "quality_before_after": {
            "before": before,
            "after": after,
            "note": "before = 当前库里的 FR 行（覆盖页口径：有 component / n；有 strength / n）；"
                    "after = 本次改进解析/映射后的预测；name_fallback = composition 无剂量时用品名补",
        },
        "would_write": {
            "products": st["products"],
            "components": st["components_planned"],
            "products_with_component": st["products_with_component"],
            "products_with_strength": st["products_with_strength"],
            "components_no_variant": st["components_no_variant"],
            "product_names": st["products"],
            "name_keys_new": len(new_keys),
            "name_variants_new": len(new_variants),
            "substance_new": 0,
            "substance_new_note": "本轮映射不上的一律空着（产品照写），不新增 substance；"
                                  "新增候选见 unmapped_top30，需人工/WHO INN 对照后另开任务",
            "note": "**只是预测**：本脚本没有任何写库路径",
        },
        "samples": result["samples"],
        "elapsed_s": elapsed,
    }

    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / "fr_dry_run.json"
    out.write_text(json.dumps({k: v for k, v in summary.items() if k != "samples"},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    (WORK / "fr_samples.json").write_text(
        json.dumps(summary["samples"], ensure_ascii=False, indent=1), encoding="utf-8")

    print("=== FR BDPM dry-run（只读；库副本，不写库）===")
    print(f"  许可: ✅ Licence Ouverte 2.0（fr-lo）+ 下载页条款；本脚本没有 --apply")
    print(f"  快照: {summary['snapshot']['dir']} · 制剂 {st['products']:,}"
          f" · 成分行 {st['composition_rows']:,} · 包装 {st['packages_total']:,}"
          f" · 仿制药组 {len(snap['gener']):,}")
    print(f"  列数异常行: {[ (n, s.get('bad_column_count', 0)) for n, s in snap['stats'].items()]}")
    print(f"  状态: {summary['status']['counts']}")
    print(f"  上市状态: {result['markets'].most_common(5)}")
    print(f"  授权程序: {result['procedures'].most_common(5)}")
    print(f"  剂型: {len(result['forms']):,} 种 · form_base 认出 {st['form_base_ok']:,}"
          f"（{summary['dosage_form']['form_base_ok_pct']}%）· other {st['form_other_or_unknown']:,}"
          f" · top {result['form_bases'].most_common(5)}")
    print(f"  给药途径: {len(result['routes']):,} 种 · top {result['routes'].most_common(5)}")
    print(f"  产品级: 有成分 {st['products_with_component']:,}/{st['products']:,}"
          f"（{summary['quality_before_after']['after']['mapping_pct']}%）· 有规格 "
          f"{st['products_with_strength']:,}/{st['products']:,}"
          f"（{summary['quality_before_after']['after']['strength_pct']}%"
          f"；其中品名补足 {st['products_strength_from_name']:,}）")
    if before:
        print(f"  before→after: 映射 {before['mapping_pct']}% → "
              f"{summary['quality_before_after']['after']['mapping_pct']}% · 规格 "
              f"{before['strength_pct']}% → {summary['quality_before_after']['after']['strength_pct']}%"
              f" · 剂型 {before['form_pct']}% → {summary['quality_before_after']['after']['form_pct']}%")
    print(f"  成分映射: 全部 {st['ingredient_tokens_mapped']:,}/{st['ingredient_tokens']:,} = "
          f"{summary['substance']['token_rate_pct']}%"
          f" · 非顺势 {st['ingredient_tokens_mapped_nonhomeo']:,}/"
          f"{st['ingredient_tokens_nonhomeo']:,} = "
          f"{summary['substance']['token_rate_nonhomeo_pct']}%"
          f" · 未映射 {unmapped_unique:,} 种 · top5 "
          f"{[x[0] for x in result['unmapped'].most_common(5)]}")
    print(f"  剂量: SA 行 {st['sa_rows']:,}（有数值 {st['sa_rows_with_dosage']:,} = "
          f"{summary['strength']['sa_rows_with_dosage_pct']}%；空 {st['sa_rows_dosage_empty']:,}"
          f"；解析不出 {st['sa_rows_dosage_unparsed']:,}）"
          f" · component 带剂量 {st['components_with_strength']:,}/{st['components_planned']:,}")
    print(f"  顺势疗法: 产品 {st['homeo_products']:,} · SA 行 {st['homeo_tokens']:,}"
          f"（占 token {summary['homeopathy']['token_share_pct']}%）· 不做 INN 映射")
    print(f"  丢弃并计数(task-6): 黑名单命中 {st['fr_guard_blocked_substance_hits']:,}"
          f" · 残串 token {st['fr_guard_residual_tokens']:,}"
          f" · 残串候选 {st['fr_guard_residual_candidates_dropped']:,}")
    print(f"  平行进口: {st['parallel_import_products']:,} 个 CIS（`Autorisation d'importation`）"
          f" · 数据质量: CIP 孤儿 {st['cip_rows_orphan']:,} 行 / {st['cip_cis_orphan']:,} 个 CIS")
    print(f"  EU 重叠: 带欧盟号 {overlap['fr_rows_with_eu_number']:,} 行"
          f"（{overlap['fr_distinct_eu_numbers']:,} 个号）· 对上 EU 层 "
          f"{overlap['fr_eu_number_matched_distinct']:,} 个")
    print(f"  同身份多 CIS: {summary['dedupe']['groups_multi_cis']:,} 组"
          f" / {summary['dedupe']['rows_in_multi_cis_groups']:,} 行（不合并）")
    print(f"  预计入库(仅预测): 产品 {st['products']:,} · component {st['components_planned']:,}"
          f" · name_key 新建 {len(new_keys):,} · name_variant 新建 {len(new_variants):,}"
          f" · substance 新增 0")
    print(f"  耗时 {elapsed}s · 汇总 {out.relative_to(ROOT)}")
    return 0


# ---------------------------------------------------------------- 自测
def self_check(raw: Path = RAW) -> int:
    """离线断言：许可证据 / 列数 / 编码 / 状态与剂型映射 / 剂量解析 / 法语成分候选 / 无 --apply。"""
    failures: list[str] = []

    def check(name: str, cond: bool, extra: str = "") -> None:
        print(f"  {'ok  ' if cond else 'FAIL'} {name}{('  ' + extra) if extra else ''}")
        if not cond:
            failures.append(name)

    # 1) 许可证据
    meta_path = raw / "fetch_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        check("fetch_meta 许可 id = fr-lo", meta.get("licence", {}).get("id") == "fr-lo")
        check("下载页条款原文已落盘", (raw / "license" / "bdpm_licence_terms.txt").exists())
        check("data.gouv.fr 数据集 JSON 已落盘",
              (raw / "license" / "data_gouv_dataset.json").exists())
        check("数据更新日期已记录", bool(meta.get("page_last_update")))
    else:
        check("fetch_meta.json 存在", False, f"缺 {meta_path}")

    # 2) 列数与编码
    for name, spec in FILES.items():
        path = raw / name
        if not path.exists():
            check(f"{name} 存在", False)
            continue
        text, encoding, replaced = _decode(path.read_bytes())
        lines = [ln for ln in text.splitlines() if ln.strip()]
        widths = Counter(len(ln.split(TAB)) for ln in lines)
        check(f"{name} 列数 = {spec['columns']}", widths.get(spec["columns"], 0) == len(lines),
              f"{len(lines):,} 行 / 异常 {len(lines) - widths.get(spec['columns'], 0)}")
        check(f"{name} 无替换字符", replaced == 0, f"encoding={encoding}")
    # 抽样真实行：CIS 61266250 = A 313 200 000 UI POUR CENT, pommade
    snap = None
    if all((raw / n).exists() for n in FILES):
        snap = load_snapshot(raw)
        first = snap["cis"][0]
        check("首行 CIS 按 12 列映射（无串列）",
              len(first) == len(CIS_COLUMNS) and bool(first["cis"].isdigit()))
        check("首行商品名非空", bool(first["denomination"]), first["denomination"][:40])
        check("CIS 全部解析成行（0 行 = 列数全错）", len(snap["cis"]) > 15000,
              f"{len(snap['cis']):,} 行")
        check("COMPO 行 cis 能对上制剂",
              snap["compo"][0]["cis"] in {r["cis"] for r in snap["cis"][:5000]})
        check("CIP 包装行有 libellé", bool(snap["cip"][0]["libelle"]))
        check("欧盟号列存在（Procédure centralisée 才有值）",
              any(r["eu_number"] for r in snap["cis"]))
        check("仿制药组列存在", bool(snap["gener"][0]["groupe"]))

    # 3) 状态映射
    check("授权 active + Commercialisée → active",
          map_status({"statut_autorisation": "Autorisation active",
                      "etat_commercialisation": "Commercialisée"})[0] == "active")
    check("授权 active + Non commercialisée → discontinued",
          map_status({"statut_autorisation": "Autorisation active",
                      "etat_commercialisation": "Non commercialisée"})[0] == "discontinued")
    check("授权 inactive → discontinued",
          map_status({"statut_autorisation": "Autorisation inactive",
                      "etat_commercialisation": ""})[0] == "discontinued")
    check("授权 archivée → withdrawn",
          map_status({"statut_autorisation": "Autorisation archivée",
                      "etat_commercialisation": ""})[0] == "withdrawn")
    check("空状态 → unknown",
          map_status({"statut_autorisation": "", "etat_commercialisation": ""})[0] == "unknown")

    # 4) 剂型归一
    cases = [("comprimé pelliculé", "tablet"), ("gélule", "capsule"),
             ("solution injectable", "injection"), ("pommade", "topical"),
             ("poudre pour suspension buvable", "powder"), ("suppositoire", "suppository")]
    for forme, expect in cases:
        got = fr_form_base(forme)
        check(f"剂型 {forme!r} → {expect}", got == expect, f"→ {got}")
    check("肠溶 → release=DR", release_of("X", "comprimé gastro-résistant") == "DR")

    # 5) 剂量解析
    d = parse_dosage("500 mg", "pour 1 comprimé")
    check("剂量 500 mg / 1 comprimé", d == {"value": 500.0, "unit": "mg",
                                            "per_volume_value": None, "per_volume_unit": None}, str(d))
    d = parse_dosage("0,5 g", "pour 1 sachet")
    check("剂量 0,5 g（法语小数点逗号）", d and d["value"] == 0.5 and d["unit"] == "g", str(d))
    d = parse_dosage("10 mg", "pour 1 ml")
    check("剂量 10 mg / 1 ml（浓度）", d and d["per_volume_value"] == 1.0
          and d["per_volume_unit"] == "mL", str(d))
    d = parse_dosage("500 mg/5 ml", "")
    check("剂量 500 mg/5 ml（写在 dosage 里）", d and d["per_volume_value"] == 5.0
          and d["per_volume_unit"] == "mL", str(d))
    check("空剂量 → None", parse_dosage("", "") is None)

    # 6) 法语成分候选
    cands = fr_substance_candidates("PARACÉTAMOL")
    check("PARACÉTAMOL 候选含 paracetamol", "paracetamol" in cands, str(cands[:5]))
    check("法语 INN 同义词 PARACÉTAMOL → acetaminophen",
          "acetaminophen" in cands, str(cands[:6]))
    check("盐名前置能翻成英文（CHLORHYDRATE DE METFORMINE）",
          "metformine hydrochloride" in fr_substance_candidates("CHLORHYDRATE DE METFORMINE"),
          str(fr_substance_candidates("CHLORHYDRATE DE METFORMINE")[:6]))
    check("去括号注释与剂量尾巴",
          french_clean_token("AMOXICILLINE (TRIHYDRATÉE) 500 mg") == "amoxicilline trihydrate",
          french_clean_token("AMOXICILLINE (TRIHYDRATÉE) 500 mg"))
    check("成分串不按分号误切单成分", split_composition("PARACÉTAMOL") == ["PARACÉTAMOL"])

    # 7) 三段式 CLI / 护栏 / manifest 可回滚性
    ap = build_parser()
    flags = {opt for action in ap._actions for opt in action.option_strings}
    check("CLI 有 --apply / --rollback / --manifest / --allow-real",
          {"--apply", "--rollback", "--manifest", "--allow-real"} <= flags)
    check("CLI 有 --fetch / --dry-run / --self-check / --prepare-copy",
          {"--fetch", "--dry-run", "--self-check", "--prepare-copy"} <= flags)
    check("默认库是 .tmp 副本，不是真库", ap.get_default("db") != REAL_DB,
          str(ap.get_default("db")))
    check("默认 manifest 在 .tmp/ 下", str(ap.get_default("manifest")).find(".tmp") >= 0,
          str(ap.get_default("manifest")))
    # 护栏：不允许写真实库时 _guard_real 必须抛 SystemExit；显式 allow_real 才放行
    try:
        _guard_real(REAL_DB, "apply", False)
    except SystemExit:
        guard_ok = True
    else:
        guard_ok = False
    check("--apply 无 --allow-real 时拒绝真库", guard_ok)
    try:
        with contextlib.redirect_stdout(io.StringIO()):   # 探针不该把「警告真实库」打到终端
            _guard_real(REAL_DB, "apply", True)
        allow_ok = True
    except SystemExit:
        allow_ok = False
    check("--allow-real 时放行（仅打印警告）", allow_ok)
    # 产品 id 确定性 + 唯一
    ids = [_product_id(c, "") for c in ("61266250", "62869109", "69103878")]
    check("product_id 形如 FR-<CIS> 且唯一",
          all(x.startswith("FR-") for x in ids) and len(set(ids)) == len(ids), str(ids))
    # manifest（如果已跑过 apply）：结构 + 可回滚 + 与 dry-run 预测一致
    manifest_path = WORK / "fr_manifest.json"
    dry_path = WORK / "fr_dry_run.json"
    if manifest_path.exists():
        man = json.loads(manifest_path.read_text(encoding="utf-8"))
        check("manifest 记录了 product_ids 全量",
              len(man.get("product_ids") or []) == (man.get("counts_planned") or {}).get("products"),
              f"{len(man.get('product_ids') or [])}")
        check("manifest 记录库文件 sha256 before/after",
              bool(man.get("db_sha256_before")) and bool(man.get("db_sha256_after")))
        targets = _rollback_targets(man)
        check("manifest 可回滚目标非空且只含 FR 产品",
              bool(targets["product_ids"]) and all(x.startswith("FR-") for x in targets["product_ids"]),
              f"{len(targets['product_ids'])} 产品")
        planned = man.get("counts_planned") or {}
        written = man.get("written") or {}
        check("manifest 的 planned 与 written 一致",
              planned.get("products") == written.get("product")
              and planned.get("components") == written.get("product_component"),
              f"planned={planned} · written={written}")
        check("manifest 的 name_key/name_variant 快照与计数一致",
              planned.get("name_keys_new") == len(man.get("created_name_keys") or [])
              and planned.get("name_variants_new") == len(man.get("created_name_variants") or []))
        check("manifest 不新增 substance", planned.get("substance_new") == 0)
    else:
        print("  skip manifest 检查（还没跑过 --apply；副本验证后会有 .tmp/fr-ingest/fr_manifest.json）")
    # 回滚目标解析（纯函数）
    sample = {"product_ids": ["FR-1"], "created_name_keys": ["a"], "created_name_variants": [["a", "A"]],
              "run_id": "bdpm_fr-x", "source_id": SOURCE_ID, "country": COUNTRY}
    t = _rollback_targets(sample)
    check("回滚计划只使用 manifest 里的键",
          t["product_ids"] == ["FR-1"] and t["name_keys"] == ["a"]
          and t["name_variants"] == [("a", "A")] and t["run_id"] == "bdpm_fr-x", str(t))

    print(f"\n=== self-check {'全部通过' if not failures else '有失败'}（{len(failures)} 项失败）===")
    return 0 if not failures else 1


def cmd_self_check(args: argparse.Namespace) -> int:
    src = args.src if args.src.is_absolute() else (ROOT / args.src)
    return self_check(src)


# ---------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="法国 BDPM 整库文件 ETL：默认 dry-run；--apply / --rollback 需 --allow-real 才写真实库。"
                    "许可 ✅ Licence Ouverte 2.0。",
        epilog="例：--fetch 抓快照与许可证据；--prepare-copy 复制库；--dry-run 出统计；"
               "--apply --allow-real --db <副本> 写库（并写 manifest）；--rollback 按 manifest 撤销。")
    ap.add_argument("--fetch", action="store_true",
                    help="抓 BDPM 下载页/许可证据 + 4 个整库文件到 data/raw/fr_bdpm_20261112/")
    ap.add_argument("--prepare-copy", action="store_true",
                    help="把 data/drugs.db 复制到 .tmp/fr-ingest/drugs_fr_copy.db（只读复制）")
    ap.add_argument("--force", action="store_true", help="--fetch 时强制重抓（默认复用缓存）")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="读缓存 → 解析 → 统计（默认；只读开库副本，不写库）")
    mode.add_argument("--self-check", action="store_true",
                      help="离线断言：许可 / 列数 / 编码 / 状态 / 剂量 / 成分 / manifest / 护栏")
    mode.add_argument("--apply", action="store_true",
                      help="事务写库（source + product/component/name + ingest_run；幂等）")
    mode.add_argument("--rollback", action="store_true", help="按 manifest 撤销本次写入")
    ap.add_argument("--db", type=Path, default=DB_COPY,
                    help="目标库（默认 .tmp/fr-ingest/drugs_fr_copy.db；写真实库需 --allow-real）")
    ap.add_argument("--src", type=Path, default=RAW, help="快照目录（默认 data/raw/fr_bdpm_20261112）")
    ap.add_argument("--manifest", type=Path, default=MANIFEST,
                    help="撤销清单路径（apply 时写、rollback 时读；默认 .tmp/fr-ingest/fr_manifest.json）")
    ap.add_argument("--allow-real", action="store_true",
                    help="允许对真实库 data/drugs.db 执行 apply/rollback（默认拒绝）")
    ap.add_argument("--copy", action="store_true",
                    help="库副本不存在时先复制真库（默认不自动复制，避免误碰真库）")
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
    if args.rollback:
        return cmd_rollback(args)
    if args.apply:
        return cmd_apply(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
