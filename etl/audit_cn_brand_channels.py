#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CN 商品名渠道审计 + 非商业定向采集（task-90）。

背景：task-85 已确认 NHSA 商品名列基本吃干；本任务审计 CDE 目录集、省级公共数据开放
平台、省级药监局说明书备案、省级集采/挂网目录、NMPA 等渠道，并在「非盈利/公益、非商业
使用」授权范围内采集公开可访问的**事实字段**（商品名/通用名/批准文号/厂家/规格）。

边界（硬约束）：
  - 只取事实字段；不转载原文全表/PDF、不上传、不再分发原文件；
  - 限速 ≥2.5s/请求；遇 403/412（WAF）立即停，不绕验证码/登录/付费墙；
  - 每个来源记录 URL + 抓取日期 + 许可判断；站点将署名并可按要求撤下；
  - 不写 DB、不改 site/build.py、不 git/发布。

渠道（详见 reports/cn-brand-channels.md）：
  - CDE《中国上市药品目录集》：GET 202（WAF JS 挑战）→ 不可批量；
  - 北京医保局「医药阳光采购」挂网目录 PDF：✅ 含「商品名」列 + 批准文号，可解析；
  - 江苏「药品阳光采购挂网产品公布表」PDF：✅ 含「商品名」列（无批准文号，用通用名+企业匹配）；
  - 福建挂网 PDF：✅ 可访问但字段无商品名；
  - 北京/浙江/广东公共数据开放平台：可访问（北京法律声明允许免费使用/传播/注明来源），
    但本轮找到的药品数据集字段无商品名；下载需登录 → 未采集；
  - 上海/天津/山东等：403/连接失败；NMPA 412 → 不采集；
  - 商业 API/第三方聚合（摩熵、药厂云等）：需授权/ToS 不明 → 不采集。

产物：
  data/cn_brand_candidates.csv     在 task-85 的 471 行基础上追加本轮候选（去重）
  data/raw/cn_brand_channels/      抽样证据缓存（PDF/HTML/JSON）
  .tmp/cn-brand-channels/          解析文本、审计记录（channels.json）
  reports/cn-brand-channels.md     报告

用法：
    python etl/audit_cn_brand_channels.py --probe        # 渠道可达性/许可探测（限速）
    python etl/audit_cn_brand_channels.py --collect      # 解析已缓存 PDF → 候选
    python etl/audit_cn_brand_channels.py --merge        # 合并进 CSV（保留已有 471 行）
    python etl/audit_cn_brand_channels.py --collect --merge
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
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".pylibs"))
try:
    import pymupdf  # noqa: E402
except Exception:  # noqa: BLE001
    pymupdf = None

DB = ROOT / "data" / "drugs.db"
CAND = ROOT / "data" / "cn_brand_candidates.csv"
RAW = ROOT / "data" / "raw" / "cn_brand_channels"
TMP = ROOT / ".tmp" / "cn-brand-channels"
UA = "drug-brand-crossref/0.3 (non-commercial research; contact: repo issues)"
RATE = 2.5  # 秒/请求

CHANNELS = [
    dict(id="cde_hymlj", name="CDE《中国上市药品目录集》",
         url="https://www.cde.org.cn/hymlj/index", kind="web_query",
         fields="药品名称/活性成分/剂型/规格/批准文号/上市许可持有人（查询页；未见商品名字段）",
         license="政府公开信息，无开放许可；站点有 WAF（GET 202 JS 挑战）",
         batch=False, used=False,
         note="查询页，无公开批量下载/Excel；反爬不可绕；不采集"),
    dict(id="beijing_ybj", name="北京市医保局 医药阳光采购 挂网目录（PDF）",
         url="https://ybj.beijing.gov.cn/zczxs/2020_zhgga/202112/P020240407353867989622.pdf",
         kind="pdf", fields="药品医保编码/通用名/**商品名**/剂型/规格/包装数量/生产企业/**批准文号**/价格",
         license="政府公开信息（非商业使用定向采集；署名来源+可撤下）",
         batch="单省 PDF，可整表解析（105 页）", used=True,
         note="✅ 同时有商品名+批准文号，可直接与 DB 产品对齐"),
    dict(id="jiangsu_ybj", name="江苏省医保局 药品阳光采购挂网产品公布表（PDF）",
         url="http://ybj.jiangsu.gov.cn/module/download/downfile.jsp?classid=0&filename=2bb4f0f3cd44404b88a915299b005724.pdf",
         kind="pdf", fields="序号/申报企业/产品编码/药品名称/**商品名**/剂型/规格/…/生产企业/挂网价/医保分类",
         license="政府公开信息（非商业使用定向采集；署名+可撤下）",
         batch="分批 PDF（单批 1–12 页），可枚举批次", used=True,
         note="✅ 含商品名；无批准文号 → 用「通用名+企业」匹配 DB"),
    dict(id="fujian_ybj", name="福建省医保局 挂网药品名单（PDF）",
         url="http://ybj.fj.gov.cn/ztzl/yxcg/ggtz/202402/P020240222416581619909.pdf",
         kind="pdf", fields="序号/产品名称/剂型/规格/包装/生产企业/申报企业/符合规则",
         license="政府公开信息（非商业使用定向采集）", batch="PDF 可解析",
         used=False, note="❌ 字段无商品名（已抽样 12 页确认）"),
    dict(id="beijing_odp", name="北京市公共数据开放平台",
         url="https://data.beijing.gov.cn/", kind="open_data",
         fields="医保药品目录（药品类别/分类/剂型/药品名称/医疗目录编码）、药品基本信息（通用名/批文/企业…）等",
         license="✅ 法律声明：免费获取、可自由利用/传播/分享，须注明「北京市公共数据开放平台」",
         batch="有 xlsx/csv/API；下载需注册登录", used=False,
         note="开放许可最好，但本轮找到的药品数据集字段无商品名；下载需登录，未采集"),
    dict(id="zj_odp", name="浙江数据开放平台", url="https://data.zjzwfw.gov.cn/",
         kind="open_data", fields="平台可访问；药品类数据集需 JS/登录检索（本轮未见商品名字段）",
         license="待核实（平台开放数据许可）", batch="未知", used=False,
         note="前端 JS，检索接口未公开；本轮未采集"),
    dict(id="gd_odp", name="广东省公共数据开放平台", url="https://gddata.gd.gov.cn/",
         kind="open_data", fields="平台首页可访问；药品商品名数据集未定位",
         license="待核实", batch="未知", used=False, note="未检索到可下载商品名数据集"),
    dict(id="sh_odp", name="上海市公共数据开放平台", url="https://data.sh.gov.cn/",
         kind="open_data", fields="—", license="—", batch=False,
         used=False, note="HTTP 412（WAF 拦截），无法审计"),
    dict(id="tj_ybj", name="天津市医保局 医保支付范围明细表（PDF，已知含商品名）",
         url="https://ylbz.tj.gov.cn/xwzx/tzgg/202108/W020210804708029907082.pdf",
         kind="pdf", fields="（据公开检索）序号/药品名称/商品名/规格/企业/批准文号等",
         license="政府公开信息（非商业使用）；未找到开放许可", batch="PDF 可解析",
         used=False, note="本机/服务端均 HTTP 403（WAF），不可采集；留作人工获取渠道"),
    dict(id="sd_odp", name="山东公共数据开放网", url="https://data.sd.gov.cn/portal/catalog/bb11c02053164acdb6e643bc15874223",
         kind="open_data", fields="国家/山东集采中选产品价格表、挂网清单目录页",
         license="开放数据平台（待核实许可）", batch="未知",
         used=False, note="连接失败（本环境不可达），未采集"),
    dict(id="nmpa", name="NMPA 数据查询（国产药品/说明书）",
         url="https://www.nmpa.gov.cn/datasearch/home-index.html", kind="web_query",
         fields="批准文号/产品名称/**商品名**/剂型/规格/生产单位（单条查询）",
         license="政府公开信息，无开放许可", batch=False,
         used=False, note="HTTP 412（WAF）；单条查询无批量，需浏览器/人工；不绕"),
    dict(id="bcpmdata", name="商业 API（摩熵数科 中国药品批文）", url="https://open.bcpmdata.com/api/12.html",
         kind="commercial", fields="23 万+ 批文：通用名/商品名/活性成分/说明书等",
         license="商业授权（付费），非开放许可", batch=True, used=False,
         note="需采购授权；非商业项目也应尊重商业条款 → 未采集"),
]


def clean(s: str) -> str:
    return unicodedata.normalize("NFKC", (s or "").replace("\n", "").strip())


def nk(s: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", clean(s).lower())


def load_db() -> dict:
    con = sqlite3.connect("file:" + str(DB) + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    db = dict(appr_products={}, appr_trade=set(), name_norms=set(), prod_info={})
    for r in con.execute("SELECT product_id, approval_id, country, mah FROM product WHERE country='CN'"):
        db["appr_products"].setdefault(r["approval_id"] or "", set()).add(r["product_id"])
        db["prod_info"][r["product_id"]] = (r["approval_id"] or "", r["mah"] or "")
    for r in con.execute("""
        SELECT p.approval_id, nk.norm FROM product p
        JOIN product_name pn ON pn.product_id=p.product_id
        JOIN name_key nk ON nk.key_id=pn.key_id
        WHERE p.country='CN' AND pn.name_type='trade'"""):
        if r["approval_id"]:
            db["appr_trade"].add((r["approval_id"], nk(r["norm"])))
    db["name_norms"] = {nk(r[0]) for r in con.execute("SELECT norm FROM name_key") if r[0]}
    con.close()
    return db


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def probe() -> None:
    """渠道可达性探测：限速、缓存 HTTP 头、遇 403/412 记 blocked 并停止该渠道。"""
    RAW.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    out = []
    for ch in CHANNELS:
        rec = dict(ch, probed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   http=None, bytes=0, blocked=False, sample=None)
        url = ch["url"]
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as resp:
                body = resp.read(50000)
                rec["http"] = resp.status
                rec["bytes"] = len(body)
                rec["content_type"] = resp.headers.get("Content-Type", "")
                rec["blocked"] = resp.status in (403, 412) or resp.status == 202
                if ch["kind"] == "pdf":
                    rec["sample"] = f"PDF header={body[:5]!r}"
                elif ch["kind"] == "open_data":
                    text = body.decode("utf-8", "ignore")
                    rec["sample"] = "开放平台页面可访问" if len(text) > 500 else ""
        except urllib.error.HTTPError as exc:
            rec["http"] = exc.code
            rec["blocked"] = exc.code in (403, 412)
        except Exception as exc:  # noqa: BLE001
            rec["http"] = f"error: {type(exc).__name__}"
        out.append(rec)
        print(f"  [{rec['http']}] {ch['id']}: {ch['name']}  blocked={rec['blocked']}")
        time.sleep(RATE)
    write_json(TMP / "channels.json", dict(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        authorisation="non-commercial/public-interest use authorised by owner; facts only; "
                      "rate limit 2.5s; no captcha/login/paywall bypass; take-down on request",
        channels=out))


def pdf_rows(path: Path, channel: str) -> list[dict]:
    """PyMuPDF find_tables 抽表 → [{brand, generic, approval, company, form, spec, extra}]"""
    if pymupdf is None or not path.exists():
        return []
    doc = pymupdf.open(path)
    rows = []
    for page in doc:
        try:
            tabs = page.find_tables()
        except Exception:  # noqa: BLE001
            continue
        for table in tabs.tables:
            data = table.extract()
            if not data:
                continue
            header = [clean(str(c)) for c in data[0]]
            idx = {name: i for i, name in enumerate(header)}
            def col(row, *names):
                for n in names:
                    for k, i in idx.items():
                        if n in k and i < len(row):
                            return clean(str(row[i] or ""))
                return ""
            for row in data[1:]:
                brand = col(row, "商品名")
                generic = col(row, "通用名", "药品名称", "产品名称")
                approval = col(row, "批准文号")
                company = col(row, "生产企业", "申报企业")
                form = col(row, "剂型")
                spec = col(row, "规格")
                if not brand and not generic:
                    continue
                rows.append(dict(brand=brand, generic=generic, approval=approval,
                                 company=company, form=form, spec=spec,
                                 price=col(row, "挂网价", "价格")))
    return rows


def build_candidates(db: dict, rows: list[dict], channel: dict, data_as_of: str,
                     out: list[dict]) -> dict:
    stats = Counter()
    for r in rows:
        brand = clean(r.get("brand"))
        generic = clean(r.get("generic"))
        approval = clean(r.get("approval"))
        stats["rows"] += 1
        if not brand or brand in ("无", "-", "/", "\\"):
            stats["no_brand"] += 1
            continue
        if len(brand) < 2 or len(brand) > 30:
            stats["bad_len"] += 1
            continue
        bnorm = nk(brand)
        if bnorm == nk(generic):
            stats["brand_equals_generic"] += 1
            continue
        stats["brand_rows"] += 1
        pids = sorted(db["appr_products"].get(approval, ())) if approval else []
        attached = approval and (approval, bnorm) in db["appr_trade"]
        if attached:
            stats["already_attached"] += 1
            continue  # 已有该关联，不重复
        conf = "high" if pids else "medium"
        note = ("批准文号直连 DB 产品" if pids else
                ("无批准文号：按通用名+企业人工核对" if not approval else "批准文号不在 DB"))
        out.append(dict(
            brand_name=brand, brand_norm=bnorm, generic_name=generic,
            approval_id=approval, company=clean(r.get("company")),
            dosage_form=clean(r.get("form")), spec=clean(r.get("spec")),
            source=channel["id"], source_url=channel["url"],
            license_note=channel["license"], data_as_of=data_as_of,
            confidence=conf,
            is_new_brand="no" if bnorm in db["name_norms"] else "yes",
            already_attached="no",
            db_product_ids=";".join(pids[:10]),
            db_product_count=len(pids),
            note=f"{channel['name']}；{note}；{channel['note']}"))
    return dict(stats)


def collect(db: dict) -> list[dict]:
    """解析已缓存的 PDF，返回候选行。"""
    sources = [
        (RAW / "beijing_yycg_202112.pdf", CHANNELS[1], "beijing_yycg_202112（2024-04 更新版）"),
        (RAW / "jiangsu_guawang_05.pdf", CHANNELS[2], "jiangsu_guawang_05"),
        (RAW / "jiangsu_guawang_18.pdf", CHANNELS[2], "jiangsu_guawang_18"),
        (RAW / "jiangsu_attachment_4736.pdf", CHANNELS[2], "jiangsu_guawang_20260201-0228"),
    ]
    TMP.mkdir(parents=True, exist_ok=True)
    cands: list[dict] = []
    stats_all = {}
    for path, ch, tag in sources:
        if not path.exists():
            continue
        rows = pdf_rows(path, ch["id"])
        # 解析文本存证（人工可复核）
        if pymupdf is not None:
            doc = pymupdf.open(path)
            (TMP / (path.stem + ".txt")).write_text(
                "\n".join(pg.get_text() for pg in doc), encoding="utf-8")
        # 覆盖统计：品牌行的批准文号是否命中 DB、是否属于「DB 里无 trade 名」的批文
        matched_appr = set()
        missing_trade_hit = set()
        for r in rows:
            appr = clean(r.get("approval"))
            if appr and appr in db["appr_products"]:
                matched_appr.add(appr)
                if not any(a == appr for a, _b in db["appr_trade"]):
                    missing_trade_hit.add(appr)
        st = build_candidates(db, rows, dict(ch, name=f"{ch['name']}（{tag}）"),
                              tag, cands)
        st = dict(st)
        st["matched_approvals"] = len(matched_appr)
        st["matched_approvals_without_trade"] = len(missing_trade_hit)
        stats_all[tag] = st
        print(f"  {tag}: rows={st['rows']} brand_rows={st['brand_rows']} "
              f"candidates+={st['brand_rows']-st.get('already_attached',0)}")
    write_json(TMP / "collect_stats.json", dict(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        per_source=stats_all, candidates=len(cands)))
    return cands


def merge(existing_path: Path, new_rows: list[dict]) -> dict:
    cols = None
    existing = []
    if existing_path.exists():
        with open(existing_path, encoding="utf-8-sig", newline="") as fh:
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
    cols = cols or list(new_rows[0].keys())
    with open(existing_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(existing)
    return dict(total=len(existing), added=added,
                by_source=dict(Counter(r.get("source", "") for r in existing)))


def main() -> int:
    ap = argparse.ArgumentParser(description="CN 商品名渠道审计/采集（只读 DB）")
    ap.add_argument("--probe", action="store_true", help="渠道可达性/许可探测")
    ap.add_argument("--collect", action="store_true", help="解析缓存 PDF → 候选")
    ap.add_argument("--merge", action="store_true", help="合并到 data/cn_brand_candidates.csv")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.probe or args.collect or args.merge):
        args.probe = args.collect = args.merge = True
    if args.probe:
        print("渠道探测（限速 2.5s/请求）:")
        probe()
    if args.collect or args.merge:
        db = load_db()
        new_rows = collect(db) if args.collect else []
        if args.merge and not args.dry_run:
            print("合并:", merge(CAND, new_rows))
        elif args.merge:
            print(f"(dry-run) 新候选 {len(new_rows)} 行，未写 CSV")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
