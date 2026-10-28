#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CN 商品名/品牌名候选抓取与比对（task-85）。

只读 `data/drugs.db`；输出 `data/cn_brand_candidates.csv`（品牌名候选 + 与现有
product/product_name 的去重结果），不写库、不改 site/build.py。

来源（先审计再抓，见 reports/cn-brand-names.md）：
  1. **NHSA 医保药品分类与代码**（仓库已有 2024-01-05 / 2025-04-04 快照，
     `data/raw/nhsa/*.csv`）：含「商品名称」列（无商品名时字面值「无」）；
     本模式离线解析快照，不联网。许可：🔴 未找到再发布许可（政府公开信息），
     按 `docs/许可清单.md` 的既有口径只取事实字段、保留来源 URL。
  2. **NHSA 公示批次 API**（code.nhsa.gov.cn，见 `data/raw/nhsa/README.txt`）：
     `--source nhsa-public-batch` 小批量抓取（限速 2–3s、断点、缓存、许可记录）；
     实测 20220110 批次有数据，2023+ 批次返回 0 条（增量公示，非全库）。
  3. **NMPA 数据查询 / 说明书、集采目录、商业 API、公开数据集**：本轮只做许可审计
     （`--audit-sources`），不抓取 —— 理由见报告（无开放许可 / 反爬 / 付费商业授权）。

产物：
  data/cn_brand_candidates.csv   brand candidates（新品牌 + 缺失的品牌-批文关联）
  .tmp/cn-brands/stats.json      覆盖估算 / 候选统计 / 去重
  .tmp/cn-brands/source_audit.json  来源许可审计记录
  data/raw/cn_brands/            抓取缓存 + license.json（仅 public-batch 模式）

用法：
    python etl/fetch_cn_brand_names.py --source nhsa-snapshot
    python etl/fetch_cn_brand_names.py --source nhsa-public-batch --batch 20220110 --max-pages 3
    python etl/fetch_cn_brand_names.py --audit-sources
    python etl/fetch_cn_brand_names.py ... --dry-run   # 只统计，不写 CSV
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
OUT = ROOT / "data" / "cn_brand_candidates.csv"
TMP = ROOT / ".tmp" / "cn-brands"
RAW_DIR = ROOT / "data" / "raw" / "cn_brands"
SNAPSHOTS = [ROOT / "data" / "raw" / "nhsa" / "nhsa_codes_20250404.csv",
             ROOT / "data" / "raw" / "nhsa" / "nhsa_codes_20240105.csv"]
NHSA_BASE = "https://code.nhsa.gov.cn"
NHSA_PAGE = NHSA_BASE + "/yp/toPublicGoodsData.html?batchNumber={batch}"
NHSA_API = (NHSA_BASE + "/yp/getPublicGoodsDataInfo.html?"
            "page={page}&rows=1000&sidx=&sord=asc&batchNumber={batch}")
UA = "drug-brand-crossref/0.3 (research; contact: repo issues)"
RATE_LIMIT = 2.5  # 秒/请求

SOURCE_AUDIT = [
    dict(source="nhsa", name="国家医保局 医保药品分类与代码（公示快照）",
         url="https://code.nhsa.gov.cn/yp/toPublicGoodsData.html",
         license_status="🔴 未找到再发布许可（政府公开信息，非开放许可）",
         republish="仅事实字段 + 链接原文；不再发布原表/快照（沿用 docs/许可清单.md 口径）",
         bulk="✅ 已有 2024-01-05 / 2025-04-04 快照（data/raw/nhsa/），含商品名称列",
         used=True, note="商品名称有值时可直接做 trade name；无值时字面「无」"),
    dict(source="nhsa_public_batch", name="国家医保局 公示批次 API（增量）",
         url="https://code.nhsa.gov.cn/yp/getPublicGoodsDataInfo.html",
         license_status="🔴 同上（政府公开信息）",
         republish="仅事实字段 + 链接原文", bulk="⚠️ 仅部分历史批次有数据（20220110 有；2023+ 返回 0）",
         used=True, note="小批量增量补充；限速/断点/缓存"),
    dict(source="nmpa", name="国家药监局 数据查询 / 药品说明书页面",
         url="https://www.nmpa.gov.cn/datasearch/home-index.html",
         license_status="🔴 未见开放许可；网站声明页有 WAF（本轮 HTTP 412），无法确认转载条款",
         republish="事实字段需逐条核实；不批量转载", bulk="❌ 动态查询 + 反爬；无公开批量下载",
         used=False, note="可作为人工种子/逐条核对的依据，不作为批量来源"),
    dict(source="nmpa_instruction", name="药监局/省级局 药品说明书 PDF",
         url="https://www.nmpa.gov.cn/",
         license_status="🔴 未找到开放许可（政府公开信息）",
         republish="仅事实字段 + 原文链接", bulk="❌ 分散、非结构化、无批量接口",
         used=False, note="商品名在说明书【商品名称】栏，可作为人工核对来源"),
    dict(source="procurement", name="国家/省级药品集中采购中选结果",
         url="http://www.smpaa.cn/（联采办）/ 各省医保局公告",
         license_status="🟡 公告类政府信息，无开放许可声明",
         republish="事实字段 + 公告链接", bulk="⚠️ 可下载 PDF/Excel，但字段以通用名/企业为主，商品名少",
         used=False, note="对商品名扩充收益低；可做企业/规格核对的旁证"),
    dict(source="bcpmdata", name="摩熵数科开放平台「中国药品批文」API",
         url="https://open.bcpmdata.com/api/12.html",
         license_status="🔴 商业 API（需注册/API Key/询价），非开放许可",
         republish="需商业授权，不能免费再发布", bulk="✅ 23 万+ 批文，含商品名称/活性成分/说明书",
         used=False, note="若采购授权可一次性补齐；否则不用"),
    dict(source="open_datasets", name="公开数据集（GitHub/Kaggle/HuggingFace 等）",
         url="（本轮检索）",
         license_status="🟡 未找到「中文药品商品名 + 开放许可」的数据集；"
                        "命中的多为医院百科（MIT，但无商品名）或商业数据",
         republish="逐数据集判断", bulk="❌ 无可用批量",
         used=False, note="继续检索；优先 CC0/CC-BY 且含商品名的说明书数据集"),
]


def clean(s: str) -> str:
    return unicodedata.normalize("NFKC", (s or "").strip())


def nk(s: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", clean(s).lower())


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load_db() -> dict:
    con = sqlite3.connect("file:" + str(DB) + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    db = dict(products={}, appr_products=defaultdict(set),
              appr_trade=defaultdict(set), name_norms=set())
    for r in con.execute("SELECT product_id, approval_id FROM product WHERE country='CN'"):
        db["products"][r["product_id"]] = r["approval_id"] or ""
        if r["approval_id"]:
            db["appr_products"][r["approval_id"]].add(r["product_id"])
    for r in con.execute("""
        SELECT p.approval_id, nk.norm
        FROM product p JOIN product_name pn ON pn.product_id=p.product_id
        JOIN name_key nk ON nk.key_id=pn.key_id
        WHERE p.country='CN' AND pn.name_type='trade'"""):
        if r["approval_id"]:
            db["appr_trade"][r["approval_id"]].add(nk(r["norm"]))
    db["name_norms"] = {nk(r[0]) for r in con.execute(
        "SELECT norm FROM name_key") if r[0]}
    con.close()
    return db


def brand_ok(brand: str, generic: str) -> bool:
    b = clean(brand)
    if not b or b == "无":
        return False
    if len(b) < 2 or len(b) > 30:
        return False
    if not re.search(r"[\u4e00-\u9fffA-Za-z]", b):
        return False
    # 品牌名不应等于通用名（含去剂型后的写法）
    if nk(b) == nk(generic):
        return False
    # 明显非品牌词
    if any(w in b for w in ("无商品名", "不适用", "详见", "见说明书", "无。")):
        return False
    return True


def candidate_row(brand, generic, approval, company, form, spec, source, url,
                  license_note, data_as_of, db, confidence, note) -> dict:
    bnorm = nk(brand)
    pid_list = sorted(db["appr_products"].get(approval, ()))
    has_trade = bnorm in db["appr_trade"].get(approval, set()) if approval else False
    return dict(
        brand_name=clean(brand), brand_norm=bnorm, generic_name=clean(generic),
        approval_id=clean(approval), company=clean(company),
        dosage_form=clean(form), spec=clean(spec),
        source=source, source_url=url, license_note=license_note,
        data_as_of=data_as_of, confidence=confidence,
        is_new_brand="no" if bnorm in db["name_norms"] else "yes",
        already_attached="yes" if has_trade else "no",
        db_product_ids=";".join(pid_list[:10]),
        db_product_count=len(pid_list), note=note)


def mine_snapshot(db: dict, stats: dict) -> list[dict]:
    """解析 NHSA 快照：新品牌 + 未挂到该批文商品上的品牌关联。"""
    rows, seen = [], set()
    brand_rows = 0
    snap_rows = 0
    for path in SNAPSHOTS:
        if not path.exists():
            stats.setdefault("missing_snapshots", []).append(str(path))
            continue
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                snap_rows += 1
                brand = clean(row.get("商品名称") or "")
                generic = clean(row.get("注册名称") or row.get("药品名称") or "")
                approval = clean(row.get("批准文号") or "")
                if not brand_ok(brand, generic):
                    continue
                brand_rows += 1
                if approval and approval in db["appr_products"]:
                    if nk(brand) in db["appr_trade"].get(approval, set()):
                        stats["already_attached_rows"] = stats.get(
                            "already_attached_rows", 0) + 1
                        continue
                key = (nk(brand), approval, nk(generic), nk(row.get("药品企业") or ""))
                if key in seen:
                    continue
                seen.add(key)
                new = nk(brand) not in db["name_norms"]
                rows.append(candidate_row(
                    brand, generic, approval, row.get("药品企业"),
                    row.get("注册剂型") or row.get("剂型"), row.get("注册规格") or row.get("规格"),
                    "nhsa_snapshot", "https://code.nhsa.gov.cn/yp/toPublicGoodsData.html",
                    "政府公开信息；仅事实字段（docs/许可清单.md：nhsa 无开放许可）",
                    path.name.replace("nhsa_codes_", "").replace(".csv", ""),
                    db, "high" if new else "medium",
                    "新品牌（name_key 未收）" if new
                    else "品牌名已存在但未挂到该批准文号商品上"))
    stats["snapshot_rows"] = snap_rows
    stats["snapshot_brand_rows"] = brand_rows
    return rows


def validate_nhsa_ok(html: str) -> bool:
    return "药品分类" in html or "医保" in html


def fetch_public_batch(batch: str, max_pages: int, resume: bool, stats: dict) -> list[dict]:
    """NHSA 公示批次 API：限速 + 断点 + 缓存 + 许可记录。"""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    license_path = RAW_DIR / "license.json"
    lic = read_json(license_path, dict(sources=[]))
    if not any(s.get("source") == "nhsa_public_batch" for s in lic["sources"]):
        lic["sources"].append(dict(
            source="nhsa_public_batch", name="国家医保局 医保药品分类与代码 公示批次",
            url=NHSA_BASE + "/yp/toPublicGoodsData.html",
            license_status="🔴 未找到再发布许可（政府公开信息）",
            policy="仅事实字段 + 链接原文；不发布原表/快照",
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds")))
        write_json(license_path, lic)
    ckpt_path = TMP / "fetch_checkpoint.json"
    ckpt = read_json(ckpt_path, {}) if resume else {}
    state = ckpt.get(batch, dict(page=1, records=0, rows=[], done=False))
    opener = urllib.request.build_opener()
    # 先拿 JSESSIONID
    cookie = ""
    try:
        req = urllib.request.Request(NHSA_PAGE.format(batch=batch),
                                     headers={"User-Agent": UA})
        with opener.open(req, timeout=30) as resp:
            cookie = resp.headers.get("Set-Cookie", "")
            validate_nhsa_ok(resp.read(8000).decode("utf-8", "ignore"))
        time.sleep(RATE_LIMIT)
    except Exception as exc:  # noqa: BLE001
        stats.setdefault("fetch_errors", []).append(f"session: {exc}")
        return []
    rows = state.get("rows", []) if resume else []
    page = state.get("page", 1)
    while page <= max_pages and not state.get("done"):
        url = NHSA_API.format(page=page, batch=batch)
        headers = {"User-Agent": UA, "Referer": NHSA_PAGE.format(batch=batch),
                   "X-Requested-With": "XMLHttpRequest"}
        if cookie:
            headers["Cookie"] = cookie.split(";")[0]
        try:
            req = urllib.request.Request(url, headers=headers)
            with opener.open(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8", "ignore") or "{}")
        except Exception as exc:  # noqa: BLE001
            stats.setdefault("fetch_errors", []).append(f"page {page}: {exc}")
            break
        time.sleep(RATE_LIMIT)
        batch_rows = data.get("rows") or []
        total = int(data.get("records") or 0)
        raw_path = RAW_DIR / f"batch_{batch}_p{page}.json"
        write_json(raw_path, data)
        stats["fetched_pages"] = stats.get("fetched_pages", 0) + 1
        stats["fetched_records"] = stats.get("fetched_records", 0) + len(batch_rows)
        for r in batch_rows:
            rows.append(dict(brand=clean(r.get("goodsname") or ""),
                             generic=clean(r.get("registeredproductname")
                                           or r.get("productname") or ""),
                             approval=clean(r.get("approvalcode") or ""),
                             company=clean(r.get("companynamesc") or ""),
                             form=clean(r.get("registeredmedicinemodel") or ""),
                             spec=clean(r.get("registeredoutlook") or "")))
        state = dict(page=page + 1, records=total, rows=rows,
                     done=(not batch_rows or total <= page * 1000))
        ckpt[batch] = state
        write_json(ckpt_path, ckpt)
        page += 1
    stats["public_batch_records"] = len(rows)
    return rows




# ---------------------------------------------------------------------------
# task-101：省级挂网目录 PDF 扩量（非商业/公益定向；事实字段）
# ---------------------------------------------------------------------------
PROVINCE_DIR = ROOT / "data" / "raw" / "cn_provinces"
EXPAND_TMP = ROOT / ".tmp" / "cn-brand-expand"
NMPA_DIR = ROOT / "data" / "raw" / "nmpa_limited"

_PROV_SOURCES = {
    "beijing_yycg_202112": ("beijing_ybj", "北京市医保局 医药阳光采购挂网目录"),
    "jiangsu_": ("jiangsu_ybj", "江苏省医保局 药品阳光采购挂网产品公布表"),
    "zhejiang_guawang_oss": ("zhejiang_ybj", "浙江省医保局 挂网目录（OSS 附件）"),
    "qinghai_guawang_20260204": ("qinghai_ybj", "青海省医保局 挂网目录（2026-02）"),
    "qinghai_price_apply_3": ("qinghai_ybj", "青海省医保局 价格申报一览表（第三批）"),
    "hunan_": ("hunan_ybj", "湖南省医保局 挂网/价格联动目录"),
    "fujian_": ("fujian_ybj", "福建省医保局 挂网名单"),
}
_PROV_LICENSE = ("政府公开信息；非商业/公益定向采集（署名来源+可撤下）；"
                 "只取事实字段，不转载原文/整表")


def _prov_source(name: str):
    for pre, meta in _PROV_SOURCES.items():
        if name.startswith(pre):
            return meta
    return ("cn_province_guawang", "省级挂网目录")


def _parse_province_pdf(path: Path):
    try:
        sys.path.insert(0, str(ROOT / ".pylibs"))
        import pymupdf  # noqa: F401
    except Exception:  # noqa: BLE001
        return [], 0
    import pymupdf
    doc = pymupdf.open(path)
    rows, nrows = [], 0
    for page in doc:
        try:
            tabs = page.find_tables()
        except Exception:  # noqa: BLE001
            continue
        for table in tabs.tables:
            data = table.extract()
            if not data:
                continue
            hdr = [clean(c).replace("\n", "").replace("\r", "") for c in data[0]]
            idx = {h: i for i, h in enumerate(hdr)}

            def col(row, *keys):
                for k in keys:
                    for h, i in idx.items():
                        if k in h and i < len(row):
                            return clean(row[i]).replace("\n", "")
                return ""

            if not any(any(k in h for k in ("商品名", "商品名称", "商品通用名")) for h in hdr):
                continue
            for row in data[1:]:
                nrows += 1
                rows.append(dict(
                    brand=col(row, "商品名", "商品名称", "商品通用名"),
                    generic=col(row, "通用名", "药品名称", "产品名称", "注册名称"),
                    approval=col(row, "批准文号"),
                    company=col(row, "生产企业", "申报企业", "投标企业", "上市许可持有人"),
                    form=col(row, "剂型"),
                    spec=col(row, "规格", "目录规格", "包装规格", "规格名称"),
                    price=col(row, "挂网价", "价格")))
    return rows, nrows


def expand_provinces(merge: bool = True) -> dict:
    """扫描 data/raw/cn_provinces/*.pdf，抽含商品名列的表，合并进候选 CSV。"""
    db = load_db()
    all_rows, stats_all = [], []
    pdfs = sorted(PROVINCE_DIR.glob("*.pdf")) if PROVINCE_DIR.exists() else []
    for path in pdfs:
        src, name = _prov_source(path.name)
        st = dict(file=path.name, source=src)
        try:
            rows, nrows = _parse_province_pdf(path)
        except Exception as exc:  # noqa: BLE001
            stats_all.append(dict(st, error=f"{type(exc).__name__}: {exc}"))
            continue
        st["table_rows"] = nrows
        st["brand_rows"] = 0
        out = []
        for r in rows:
            brand, generic = clean(r["brand"]), clean(r["generic"])
            if not brand or brand in ("无", "/", "-", "\\") or not (2 <= len(brand) <= 30):
                continue
            bnorm = nk(brand)
            if bnorm == nk(generic):
                continue
            st["brand_rows"] += 1
            approval = clean(r["approval"])
            pids = sorted(db["appr_products"].get(approval, ())) if approval else []
            if approval and bnorm in db["appr_trade"].get(approval, set()):
                st["already_attached"] = st.get("already_attached", 0) + 1
                continue
            if pids:
                st["matched_approvals"] = st.get("matched_approvals", 0) + 1
            out.append(dict(
                brand_name=brand, brand_norm=bnorm, generic_name=generic,
                approval_id=approval, company=clean(r["company"]),
                dosage_form=clean(r["form"]), spec=clean(r["spec"]),
                source=src, source_url=("data/raw/cn_provinces/" + path.name),
                license_note=_PROV_LICENSE,
                data_as_of="2026-10-28 抓取（" + path.name + "）",
                confidence="high" if approval else "medium",
                is_new_brand="no" if bnorm in db["name_norms"] else "yes",
                already_attached="no",
                db_product_ids=";".join(pids[:10]), db_product_count=len(pids),
                note=name + "｜" + ("批准文号直连 DB" if pids else
                                    ("无批准文号，按通用名+企业核对" if not approval
                                     else "批准文号不在 DB"))))
        st["candidates"] = len(out)
        all_rows.extend(out)
        stats_all.append(st)
    agg = Counter()
    for st in stats_all:
        for k in ("table_rows", "brand_rows", "already_attached", "candidates"):
            agg[k] += st.get(k, 0)
    agg["pdfs"] = len(pdfs)
    agg["pdfs_with_brand_col"] = sum(1 for x in stats_all if x.get("brand_rows"))
    m = None
    if merge and all_rows:
        m = merge_candidates(all_rows)
    EXPAND_TMP.mkdir(parents=True, exist_ok=True)
    (EXPAND_TMP / "expand_stats.json").write_text(json.dumps(dict(
        aggregate=dict(agg), per_pdf=stats_all, merge=m), ensure_ascii=False, indent=1),
        encoding="utf-8")
    (NMPA_DIR / "README.md").write_text(
        "# NMPA 定向抓取（task-101）\n\n本环境访问 www.nmpa.gov.cn / datasearch / app1.nmpa.gov.cn "
        "均返回 HTTP 412（WAF）或不可达，按「遇 403/412 即停」规则**未采集**；\n"
        "NMPA 单条查询字段含商品名，可作为人工/浏览器兜底（top 500–1,000 通用名，≥3s/请求）。\n",
        encoding="utf-8")
    return dict(aggregate=dict(agg), merge=m, per_pdf=stats_all)


def merge_candidates(new_rows: list[dict]) -> dict:
    existing, cols = [], None
    if OUT.exists():
        with open(OUT, encoding="utf-8-sig", newline="") as fh:
            rd = csv.DictReader(fh)
            cols = rd.fieldnames
            existing = list(rd)
    seen = {(r.get("brand_norm", ""), r.get("approval_id", ""),
             nk(r.get("generic_name", ""))) for r in existing}
    added = 0
    for r in new_rows:
        key = (r["brand_norm"], r["approval_id"], nk(r["generic_name"]))
        if key in seen:
            continue
        seen.add(key)
        existing.append(r)
        added += 1
    with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(existing)
    return dict(total=len(existing), added=added,
                by_source=dict(Counter(r.get("source", "") for r in existing)),
                new_brand_rows=sum(1 for r in existing if r.get("is_new_brand") == "yes"))




# ---------------------------------------------------------------------------
# task-110：人工下载的省级 PDF/XLSX/CSV/HTML 采集包解析
# ---------------------------------------------------------------------------
MANUAL_DIR = ROOT / "data" / "raw" / "cn_provinces" / "manual"
MANUAL_TMP = ROOT / ".tmp" / "cn-manual"
MANUAL_LICENSE = ("人工下载的政府公开信息；非商业/公益使用（署名来源+可撤下）；"
                  "只取事实字段，不转载原文/整表")
_HDR_RULES = [
    ("brand", ("商品名", "商品名称", "商品通用名")),
    ("generic", ("通用名", "药品名称", "产品名称", "注册名称")),
    ("approval", ("批准文号",)),
    ("company", ("生产企业", "申报企业", "投标企业", "上市许可持有人")),
    ("form", ("剂型",)),
    ("spec", ("规格",)),
    ("price", ("挂网价", "价格")),
]


def _cell(v) -> str:
    return clean("" if v is None else str(v)).replace("\n", "").replace("\r", "")


def _detect_header(cells):
    """表头单元格 → {'brand': i, ...}；必须含商品名列。"""
    cols = {}
    for i, c in enumerate(cells):
        c = _cell(c)
        for key, kws in _HDR_RULES:
            if key in cols:
                continue
            if any(k in c for k in kws):
                cols[key] = i
                break
    return cols if ("brand" in cols and ("generic" in cols or "approval" in cols)) else None


def _rows_from_matrix(matrix, header_scan: int = 40):
    """二维表 → (行 dict, 是否找到商品名表头)。"""
    idx = None
    start = 0
    for i, row in enumerate(matrix[:header_scan]):
        cols = _detect_header(row)
        if cols:
            idx, start = cols, i + 1
            break
    if not idx:
        return [], False
    out = []
    for row in matrix[start:]:
        d = {k: (row[i] if i < len(row) else "") for k, i in idx.items()}
        if any(_cell(v) for v in d.values()):
            out.append(d)
    return out, True


def _parse_xlsx(path: Path):
    try:
        import openpyxl
    except Exception:  # noqa: BLE001
        return [], False, "openpyxl 不可用"
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        return [], False, f"openpyxl 打开失败: {type(exc).__name__}: {exc}"
    rows = []
    found = False
    for ws in wb.worksheets:
        try:
            matrix = [list(r) for r in ws.values]
        except Exception:  # noqa: BLE001
            continue
        r, f = _rows_from_matrix(matrix)
        rows.extend(r)
        found = found or f
    wb.close()
    return rows, found, ""


def _parse_csv(path: Path):
    import csv as _csv
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin1"):
        try:
            with open(path, encoding=enc, newline="") as fh:
                matrix = [row for row in _csv.reader(fh)]
            rows, found = _rows_from_matrix(matrix)
            if found:
                return rows, True, f"编码 {enc}"
        except Exception:  # noqa: BLE001
            continue
    return [], False, "CSV 无可识别商品名表头（尝试 utf-8/GB18030）"


def _parse_html(path: Path):
    try:
        import lxml.html as LH
    except Exception:  # noqa: BLE001
        return [], False, "lxml 不可用"
    try:
        doc = LH.fromstring(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:  # noqa: BLE001
        return [], False, f"HTML 解析失败: {type(exc).__name__}"
    rows, found = [], False
    for table in doc.xpath("//table"):
        matrix = []
        for tr in table.xpath(".//tr"):
            cells = tr.xpath("./td|./th")
            matrix.append([c.text_content() for c in cells])
        r, f = _rows_from_matrix(matrix)
        rows.extend(r)
        found = found or f
    return rows, found, ""


def _pdf_text_fallback(path: Path):
    """find_tables 失败时的文本行回退（近似列对齐）。"""
    import re as _re
    try:
        import pymupdf
    except Exception:  # noqa: BLE001
        return [], False
    try:
        doc = pymupdf.open(path)
    except Exception:  # noqa: BLE001
        return [], False
    lines = []
    for page in doc:
        lines.extend(page.get_text("text").splitlines())
    idx = None
    for i, line in enumerate(lines[:200]):
        cols = _detect_header(_re.split(r"\s{2,}|\t", line.strip()))
        if cols:
            idx = cols
            start = i + 1
            break
    if not idx:
        return [], False
    rows = []
    for line in lines[start:]:
        parts = [p.strip() for p in _re.split(r"\s{2,}|\t", line.strip()) if p.strip()]
        if len(parts) < 3:
            continue
        d = {k: (parts[i] if i < len(parts) else "") for k, i in idx.items()}
        if _cell(d.get("brand")):
            rows.append(d)
    return rows, True


def _parse_manual_file(path: Path):
    """→ (rows, found, note)。"""
    suf = path.suffix.lower()
    try:
        if suf == ".pdf":
            rows, nrows = _parse_province_pdf(path)
            if rows:
                return rows, True, "PyMuPDF find_tables"
            rows, found = _pdf_text_fallback(path)
            return rows, found, ("find_tables 无商品名表 → 文本行回退" if found
                                 else "PDF 无可识别商品名表（find_tables/文本回退均失败）")
        if suf in (".xlsx", ".xls"):
            if suf == ".xls":
                return [], False, "旧版 .xls 不支持，请另存为 .xlsx"
            return _parse_xlsx(path)
        if suf in (".csv", ".txt"):
            return _parse_csv(path)
        if suf in (".html", ".htm"):
            return _parse_html(path)
    except Exception as exc:  # noqa: BLE001
        return [], False, f"解析异常: {type(exc).__name__}: {exc}"
    return [], False, "不支持的文件类型"


def expand_manual(manual_dir: Path, merge: bool = True) -> dict:
    """扫描人工下载目录，解析/对齐/去重合并候选，输出每文件统计。"""
    db = load_db()
    MANUAL_TMP.mkdir(parents=True, exist_ok=True)
    manual_dir = manual_dir.resolve() if manual_dir.is_absolute() else (ROOT / manual_dir).resolve()
    files = []
    if manual_dir.exists():
        for path in sorted(manual_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in (
                    ".pdf", ".xlsx", ".xls", ".csv", ".txt", ".html", ".htm"):
                files.append(path)
    # 现有 CSV 去重键
    existing_keys = set()
    if OUT.exists():
        import csv as _csv
        with open(OUT, encoding="utf-8-sig", newline="") as fh:
            for r in _csv.DictReader(fh):
                existing_keys.add((r.get("brand_norm", ""), r.get("approval_id", ""),
                                   nk(r.get("generic_name", ""))))
    all_rows, stats_all = [], []
    seen_keys = set(existing_keys)
    for path in files:
        try:
            rel = str(path.resolve().relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            rel = str(path)
        st = dict(file=rel, type=path.suffix.lower(), rows=0, brand_rows=0,
                  candidates=0, added=0, note="")
        try:
            rows, found, note = _parse_manual_file(path)
        except Exception as exc:  # noqa: BLE001
            rows, found, note = [], False, f"解析异常: {type(exc).__name__}: {exc}"
        st["note"] = note
        if not found:
            stats_all.append(st)
            continue
        st["rows"] = len(rows)
        for r in rows:
            brand = _cell(r.get("brand"))
            generic = _cell(r.get("generic"))
            if not brand or brand in ("无", "/", "-", "\\") or not (2 <= len(brand) <= 30):
                continue
            bnorm = nk(brand)
            if bnorm == nk(generic):
                continue
            st["brand_rows"] += 1
            approval = _cell(r.get("approval"))
            pids = sorted(db["appr_products"].get(approval, ())) if approval else []
            if approval and bnorm in db["appr_trade"].get(approval, set()):
                continue
            key = (bnorm, approval, nk(generic))
            new_key = key not in seen_keys
            if new_key:
                st["added"] += 1
                seen_keys.add(key)
            st["candidates"] += 1
            all_rows.append(dict(
                brand_name=brand, brand_norm=bnorm, generic_name=generic,
                approval_id=approval, company=_cell(r.get("company")),
                dosage_form=_cell(r.get("form")), spec=_cell(r.get("spec")),
                source="cn_manual", source_url=rel,
                license_note=MANUAL_LICENSE,
                data_as_of="2026-10-28 人工采集（" + path.name + "）",
                confidence="high" if approval else "medium",
                is_new_brand="no" if bnorm in db["name_norms"] else "yes",
                already_attached="no",
                db_product_ids=";".join(pids[:10]), db_product_count=len(pids),
                note="人工采集包｜" + path.name + "｜" +
                     ("批准文号直连 DB" if pids else "无批准文号/未命中，按通用名+企业核对")))
        stats_all.append(st)
    m = merge_candidates(all_rows) if (merge and all_rows) else None
    (MANUAL_TMP / "manual_stats.json").write_text(json.dumps(dict(
        manual_dir=str(manual_dir), files=len(files), per_file=stats_all,
        total_candidates=len(all_rows), merge=m,
        expected="每省每批约 100–1,700 行、10–20% 有商品名；新增（相对现有 CSV）约 0–30%"),
        ensure_ascii=False, indent=1), encoding="utf-8")
    return dict(files=len(files), per_file=stats_all, candidates=len(all_rows), merge=m)



def main() -> int:
    ap = argparse.ArgumentParser(description="CN 商品名候选抓取/比对（只读 DB）")
    ap.add_argument("--source", choices=["all", "nhsa-snapshot", "nhsa-public-batch"],
                    default="all", help="默认合并快照+公示批次；单源调试可指定")
    ap.add_argument("--batch", default="20220110", help="NHSA 公示批次号")
    ap.add_argument("--max-pages", type=int, default=3)
    ap.add_argument("--resume", action="store_true", help="从断点继续 public-batch 抓取")
    ap.add_argument("--audit-sources", action="store_true", help="输出来源许可审计")
    ap.add_argument("--expand-provinces", action="store_true",
                    help="扫描 data/raw/cn_provinces/ PDF 并合并候选（task-101）")
    ap.add_argument("--expand-manual", action="store_true",
                    help="扫描 data/raw/cn_provinces/manual/ 的 PDF/XLSX/CSV/HTML（task-110）")
    ap.add_argument("--manual-dir", default=str(MANUAL_DIR),
                    help="人工采集包目录（默认 data/raw/cn_provinces/manual）")
    ap.add_argument("--dry-run", action="store_true", help="只打印统计，不写 CSV")
    args = ap.parse_args()

    if args.expand_manual:
        r = expand_manual(Path(args.manual_dir), merge=not args.dry_run)
        print(f"人工采集包：{r['files']} 个文件；候选 {r['candidates']} 行；"
              f"合并 {r['merge'] and r['merge'].get('added', 0)} 行（dry-run={args.dry_run}）")
        for st in r["per_file"]:
            print(f"  {st['file']:<70} rows={st['rows']:<5} brand={st['brand_rows']:<4} "
                  f"cand={st['candidates']:<4} added={st['added']:<4} {st['note']}")
        print("统计:", MANUAL_TMP / "manual_stats.json")
        return 0

    if args.expand_provinces:
        r = expand_provinces(merge=True)
        a = r["aggregate"]
        print(f"省级挂网 PDF：{a['pdfs']} 个，其中有商品名列 {a['pdfs_with_brand_col']} 个；"
              f"表格行 {a['table_rows']}，品牌行 {a['brand_rows']}，"
              f"已存在 {a.get('already_attached', 0)}，新增合并 {r['merge'] and r['merge'].get('added', 0)}")
        print("CSV:", OUT, "统计:", EXPAND_TMP / "expand_stats.json")
        return 0

    TMP.mkdir(parents=True, exist_ok=True)
    db = load_db()
    stats = dict(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        db=str(DB),
        db_cn_products=len(db["products"]),
        db_cn_approvals=len(db["appr_products"]),
        db_approvals_with_trade=len(db["appr_trade"]),
        db_products_with_trade=sum(len(v) for v in db["appr_trade"].values()),
        db_name_norms=len(db["name_norms"]),
    )
    # 当前覆盖
    con = sqlite3.connect("file:" + str(DB) + "?mode=ro", uri=True)
    stats["current_trade_product_rows"] = con.execute("""
        SELECT COUNT(DISTINCT p.product_id) FROM product p
        JOIN product_name pn ON pn.product_id=p.product_id
        WHERE p.country='CN' AND pn.name_type='trade'""").fetchone()[0]
    stats["current_brand_keys"] = con.execute("""
        SELECT COUNT(DISTINCT pn.key_id) FROM product p
        JOIN product_name pn ON pn.product_id=p.product_id
        WHERE p.country='CN' AND pn.name_type='trade'""").fetchone()[0]
    con.close()
    stats["current_trade_product_coverage"] = round(
        stats["current_trade_product_rows"] / stats["db_cn_products"], 4)
    stats["current_trade_approval_coverage"] = round(
        stats["db_approvals_with_trade"] / stats["db_cn_approvals"], 4)

    rows: list[dict] = []
    if args.audit_sources:
        write_json(TMP / "source_audit.json", dict(
            generated_at=stats["generated_at"], sources=SOURCE_AUDIT))
        print("来源审计:")
        for s in SOURCE_AUDIT:
            print(f"  [{'用' if s['used'] else '不用'}] {s['name']}: {s['license_status']}")
        return 0
    if args.source in ("all", "nhsa-snapshot"):
        rows = mine_snapshot(db, stats)
    if args.source in ("all", "nhsa-public-batch"):
        fetched = fetch_public_batch(args.batch, args.max_pages, args.resume, stats)
        seen = set()
        for r in fetched:
            if not brand_ok(r["brand"], r["generic"]):
                continue
            key = (nk(r["brand"]), r["approval"], nk(r["generic"]))
            if key in seen or (r["approval"] and nk(r["brand"]) in
                               db["appr_trade"].get(r["approval"], set())):
                continue
            if key in {(nk(x["brand_name"]), x["approval_id"], nk(x["generic_name"])) for x in rows}:
                continue
            seen.add(key)
            rows.append(candidate_row(
                r["brand"], r["generic"], r["approval"], r["company"], r["form"],
                r["spec"], "nhsa_public_batch",
                NHSA_BASE + "/yp/toPublicGoodsData.html?batchNumber=" + args.batch,
                "政府公开信息；仅事实字段（见 data/raw/cn_brands/license.json）",
                args.batch, db, "medium",
                "公示批次增量；非全库"))
    # 汇总
    new_brands = {r["brand_norm"] for r in rows if r["is_new_brand"] == "yes"}
    stats.update(
        candidates=len(rows),
        candidate_unique_brands=len({r["brand_norm"] for r in rows}),
        candidate_new_brands=len(new_brands),
        candidate_attached_gain=sum(1 for r in rows if r["already_attached"] == "no"),
        candidate_generic_coverage=len({nk(r["generic_name"]) for r in rows}),
        brand_keys_after_estimate=stats["current_brand_keys"] + len(new_brands),
        trade_products_after_estimate=stats["current_trade_product_rows"] + sum(
            1 for r in rows if r["already_attached"] == "no"),
        note="NHSA 快照已基本吸收：新品牌数≈品牌键口径上限；商品名缺失的大头（无商品名批文）"
             "来自无开放许可的 NMPA/集采/商业 API，本脚本不抓",
    )
    print(f"DB CN 产品 {stats['db_cn_products']:,}；已有 trade 名产品 "
          f"{stats['current_trade_product_rows']:,}"
          f"（{stats['current_trade_product_coverage']*100:.1f}%）；品牌键 "
          f"{stats['current_brand_keys']:,}")
    print(f"候选 {stats['candidates']} 行：唯一品牌 {stats['candidate_unique_brands']}，"
          f"其中新品牌 {stats['candidate_new_brands']}；可补挂产品 {stats['candidate_attached_gain']}")
    print(f"估算：品牌键 {stats['current_brand_keys']:,} → "
          f"{stats['brand_keys_after_estimate']:,}；trade 名产品 "
          f"{stats['current_trade_product_rows']:,} → "
          f"{stats['trade_products_after_estimate']:,}"
          f"（{stats['trade_products_after_estimate']/stats['db_cn_products']*100:.2f}%）")
    write_json(TMP / "stats.json", stats)
    if not args.dry_run and rows:
        cols = ["brand_name", "brand_norm", "generic_name", "approval_id", "company",
                "dosage_form", "spec", "source", "source_url", "license_note",
                "data_as_of", "confidence", "is_new_brand", "already_attached",
                "db_product_ids", "db_product_count", "note"]
        rows.sort(key=lambda r: (r["is_new_brand"] != "yes",
                                 r["already_attached"] != "no", r["brand_name"]))
        with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"写入 {OUT}（{len(rows)} 行）")
    elif args.dry_run:
        print("(dry-run，未写 CSV)")
    else:
        print("没有候选（NHSA 快照已全部吸收；其余源需许可/人工，见报告）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
