# -*- coding: utf-8 -*-
"""数据源漂移告警（task-25）：只读扫描 10 个来源的原始缓存，生成/对比基线。

监控内容（每个来源 / 每个 part）
--------------------------------
- 记录行数（CSV/JSONL 流式计数；JSON 数组 len；XML 记录标签计数；大 JSON 用记录标记计数）
- 字段集合（CSV 表头 / JSON 记录键 / XML 首条记录的子标签）
- 关键枚举分布（配置的列/字段 → 值分布，取 top 20）
- 最近抓取时间（文件 mtime 最大值）+ 数据截止日（能解析的：HK `lastUpdate`、ARTG validation.json、NHSA 文件名）
- 文件 sha256（只对监控到的文件计算）

告警规则（对比基线）
--------------------
1. 行数变化 > **±10%**（基线 <20 行的来源改用「绝对变化 ≥5 行」）
2. 字段**增加/删除**
3. 枚举**出现新值**
4. 文件**缺失**（被监控文件不存在）
文件 sha256 变化只记「已更新」提示，不告警（正常刷新）。

输出
----
- 基线：`data/sources/drift-baseline.json`（入仓库；**更新需 Lead 批准** —— 默认已存在时拒绝写，需 `--force`）
- 告警：`reports/drift-YYYYMMDD.md`（仅在有告警时写；不自动改任何数据）
- 机器可读快照：`--json-out`（可选，默认不写）

用法
----
    python etl/drift_check.py --write-baseline        # 首次生成基线（已存在则拒绝）
    python etl/drift_check.py --write-baseline --force  # 覆盖基线（需 Lead 批准）
    python etl/drift_check.py                          # 对比基线，有告警则写 reports/drift-<date>.md
    python etl/drift_check.py --self-test              # 构造模拟漂移，验证告警逻辑
    python etl/drift_check.py --source hk_dh,us_ndc    # 只看部分来源
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "data" / "sources" / "drift-baseline.json"
REPORT_DIR = ROOT / "reports"
SCRIPT_VERSION = "2026-10-30"
ROW_PCT = 0.10
ROW_ABS_MIN = 5
ROW_SMALL = 20
ENUM_TOP = 20

# ---------------------------------------------------------------- 来源配置
# kind: csv | jsonl | json_list | json_marker | xml_tag | json_dir
SOURCES: list[dict] = [
    {
        "source_id": "us_ndc", "label": "US openFDA NDC",
        "parts": [
            {"part": "ndc_json", "kind": "json_marker", "glob": "data/raw/openfda/ndc-01.json",
             "marker": b'"product_ndc"', "fields_from_head": True},
        ],
        "extra_files": ["data/raw/openfda/download.json", "data/raw/openfda/ndc-01.zip"],
        "data_as_of_from": "data/raw/openfda/download.json",
        "note": "243 MB JSON 用 `\"product_ndc\"` 标记计数（rows 为记录数代理，非全量解析）；download.json/zip 只做文件哈希",
    },
    {
        "source_id": "gb_dmd", "label": "GB NHSBSA dm+d",
        "parts": [
            {"part": "amp", "kind": "xml_tag", "glob": "data/raw/dmd/extracted/f_amp2_*.xml", "tag": "AMP"},
            {"part": "ampp", "kind": "xml_tag", "glob": "data/raw/dmd/extracted/f_ampp2_*.xml", "tag": "AMPP"},
            {"part": "vmp", "kind": "xml_tag", "glob": "data/raw/dmd/extracted/f_vmp2_*.xml", "tag": "VMP"},
            {"part": "vmpp", "kind": "xml_tag", "glob": "data/raw/dmd/extracted/f_vmpp2_*.xml", "tag": "VMPP"},
            {"part": "vtm", "kind": "xml_tag", "glob": "data/raw/dmd/extracted/f_vtm2_*.xml", "tag": "VTM"},
        ],
    },
    {
        "source_id": "ca_dpd", "label": "CA Health Canada DPD",
        "parts": [
            {"part": "drugproduct", "kind": "json_list", "glob": "data/raw/ca/dpd/drugproduct.json",
             "enums": ["class_name"]},
            {"part": "status", "kind": "json_list", "glob": "data/raw/ca/dpd/status.json",
             "enums": ["status"]},
            {"part": "activeingredient", "kind": "json_list", "glob": "data/raw/ca/dpd/activeingredient.json",
             "fields": False},
            {"part": "packaging", "kind": "json_list", "glob": "data/raw/ca/dpd/packaging.json", "fields": False},
            {"part": "route", "kind": "json_list", "glob": "data/raw/ca/dpd/route.json", "fields": False},
        ],
    },
    {
        "source_id": "au_artg", "label": "AU TGA ARTG（导出 + 索引）",
        "parts": [
            {"part": "export_1991_2020", "kind": "csv", "glob": "data/raw/artg_20261028/ARTG_Medicines_1991-2020.csv",
             "enums": ["ARTG Category", "Product Type", "Therapeutic Type"]},
            {"part": "export_2021_2026", "kind": "csv", "glob": "data/raw/artg_20261028/ARTG_Medicines_2021-2026.csv",
             "enums": ["ARTG Category", "Product Type", "Therapeutic Type"]},
            {"part": "index_medicine", "kind": "jsonl", "glob": "data/raw/artg/medicine_index.jsonl"},
            {"part": "index_entries", "kind": "jsonl", "glob": "data/raw/artg/entries_with_unid.jsonl"},
            {"part": "index_details", "kind": "jsonl", "glob": "data/raw/artg/details.jsonl"},
        ],
        "data_as_of_from": "data/raw/artg_20261028/validation.json",
    },
    {
        "source_id": "es_cima", "label": "ES AEMPS CIMA",
        "parts": [
            {"part": "pages", "kind": "json_dir", "glob": "data/raw/cima/page-*.json",
             "list_key": "resultados", "enums": ["cpresc"]},
            {"part": "atc_files", "kind": "file_count", "glob": "data/raw/cima/atc/*.json"},
        ],
        "note": "1,937 个分页 JSON；rows = 各页 resultados 之和；首页 totalFilas 记入 meta",
    },
    {
        "source_id": "mx_cofepris", "label": "MX COFEPRIS（CSV + PDF）",
        "parts": [
            {"part": "alopaticos", "kind": "csv", "glob": "data/raw/mx/cofepris_alopaticos.csv"},
            {"part": "prorrogas", "kind": "csv", "glob": "data/raw/mx/cofepris_prorrogas.csv"},
            {"part": "status", "kind": "csv", "glob": "data/raw/mx/cofepris_status.csv"},
            {"part": "profeco", "kind": "csv", "glob": "data/raw/mx/profeco_medicamentos.csv"},
            {"part": "profeco_all", "kind": "csv", "glob": "data/raw/mx/profeco_all.csv"},
        ],
    },
    {
        "source_id": "cn_nhsa", "label": "CN 国家医保局 NHSA",
        "parts": [
            {"part": "codes_20250404", "kind": "csv", "glob": "data/raw/nhsa/nhsa_codes_20250404.csv",
             "enums": ["甲乙类"]},
            {"part": "codes_20240105", "kind": "csv", "glob": "data/raw/nhsa/nhsa_codes_20240105.csv"},
        ],
        "note": "rows 为医保代码行数；PDF 不进本监控（只做文件清单）",
    },
    {
        "source_id": "tw_tfda", "label": "TW TFDA 藥品許可證",
        "parts": [
            {"part": "tfda_36_csv", "kind": "csv", "glob": "data/raw/tw/tfda_36.csv",
             "enums": ["註銷狀態", "藥品類別"]},
        ],
        "note": "以 CSV 为计数口径（tfda_36.json 79 MB 只做文件哈希）",
    },
    {
        "source_id": "sg_hsa", "label": "SG HSA 注册治疗产品",
        "parts": [
            {"part": "registered", "kind": "json_list", "glob": "data/raw/sg/hsa_registered_therapeutic_products.json",
             "list_key": "result.records", "fields_key": "result.fields", "enums": ["Forensicclassification"]},
            {"part": "cpm_products", "kind": "json_list", "glob": "data/raw/sg/hsa_cpm_products.json",
             "list_key": "result.records", "fields_key": "result.fields"},
        ],
    },
    {
        "source_id": "hk_dh", "label": "HK 衞生署藥物辦公室 註冊藥劑製品",
        "parts": [
            {"part": "druglist", "kind": "xml_tag", "glob": "data/raw/hk_mo/hk_rpp_resource.xml",
             "tag": "drug", "fields_from_first": True},
        ],
        "data_as_of_from": "data/raw/hk_mo/hk_rpp_resource.xml",
    },
]


# ---------------------------------------------------------------- 工具
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")


def _get_path(obj, dotted: str):
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, list):
            return None
        cur = cur.get(part) if isinstance(cur, dict) else None
        if cur is None:
            return None
    return cur


def _json_head_fields(path: Path, limit: int = 1 << 20) -> list[str]:
    """从 JSON 头部猜字段（失败返回空）：先试首个对象，再试 results 数组首个元素。"""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            head = fh.read(limit)
        i = head.find("{")
        if i < 0:
            return []
        try:
            obj, _ = json.JSONDecoder().raw_decode(head[i:])
            return sorted(obj.keys())[:60]
        except json.JSONDecodeError:
            pass
        # 回退：找 "results" 之后第一个对象（openFDA NDC 这类 {"meta":..., "results":[...]}）
        j = head.find('"results"')
        k = head.find("{", j if j >= 0 else 0)
        if k < 0:
            return []
        try:
            rec, _ = json.JSONDecoder().raw_decode(head[k:])
            return sorted(rec.keys())[:60] if isinstance(rec, dict) else []
        except json.JSONDecodeError:
            return []
    except OSError:
        return []


def _xml_first_record_fields(path: Path, tag: str) -> list[str]:
    try:
        for _ev, el in ET.iterparse(str(path), events=("start",)):
            if el.tag == tag:
                return sorted({c.tag for c in el})
    except ET.ParseError:
        return []
    return []


def _xml_count_and_fields(path: Path, tag: str, want_fields: bool) -> tuple[int, list[str]]:
    """计数 XML 记录标签（regex，快）；字段用首条记录（iterparse 提前退出）。"""
    pat = re.compile(("<" + re.escape(tag) + r">").encode())
    n = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            n += len(pat.findall(chunk))
    fields = _xml_first_record_fields(path, tag) if want_fields else []
    return n, fields


# ---------------------------------------------------------------- 各 kind 快照
def snapshot_csv(path: Path, enums: list[str]) -> dict:
    counters = {e: Counter() for e in enums}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rd = csv.reader(fh)
        header = next(rd, [])
        idx = {e: header.index(e) for e in enums if e in header}
        rows = 0
        for row in rd:
            rows += 1
            for e, i in idx.items():
                if i < len(row):
                    counters[e][row[i].strip()] += 1
    return {"rows": rows, "fields": header,
            "enums": {e: dict(c.most_common(ENUM_TOP)) for e, c in counters.items() if c},
            "count_mode": "csv"}


def snapshot_jsonl(path: Path) -> dict:
    rows = 0
    fields: list[str] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows += 1
            if not fields:
                try:
                    fields = sorted(json.loads(line).keys())
                except json.JSONDecodeError:
                    fields = []
    return {"rows": rows, "fields": fields, "count_mode": "jsonl"}


def snapshot_json_list(path: Path, list_key: str | None, enums: list[str],
                       fields_key: str | None = None, want_fields: bool = True) -> dict:
    with path.open(encoding="utf-8", errors="replace") as fh:
        data = json.load(fh)
    arr = _get_path(data, list_key) if list_key else data
    if isinstance(arr, dict) and "records" in arr:
        arr = arr["records"]
    if not isinstance(arr, list):
        arr = []
    fields: list[str] = []
    if fields_key:
        fk = _get_path(data, fields_key) or []
        fields = [f.get("id") or f.get("name") or str(f) for f in fk] if isinstance(fk, list) else []
    elif want_fields and arr and isinstance(arr[0], dict):
        fields = sorted(arr[0].keys())
    counters = {e: Counter() for e in enums}
    for rec in arr:
        if not isinstance(rec, dict):
            continue
        for e in enums:
            v = rec.get(e)
            if v is None:
                continue
            counters[e][str(v)[:60]] += 1
    return {"rows": len(arr), "fields": fields,
            "enums": {e: dict(c.most_common(ENUM_TOP)) for e, c in counters.items() if c},
            "count_mode": "json_list"}


def snapshot_json_marker(path: Path, marker: bytes) -> dict:
    n = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            n += chunk.count(marker)
    return {"rows": n, "fields": _json_head_fields(path),
            "count_mode": f"marker:{marker.decode('utf-8', 'replace')}"}


def snapshot_json_dir(paths: list[Path], list_key: str | None, enums: list[str]) -> dict:
    rows = 0
    counters = {e: Counter() for e in enums}
    fields: list[str] = []
    total_meta = None
    for p in paths:
        try:
            with p.open(encoding="utf-8", errors="replace") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        arr = _get_path(data, list_key) if list_key else data
        if not isinstance(arr, list):
            continue
        rows += len(arr)
        if not fields and arr and isinstance(arr[0], dict):
            fields = sorted(arr[0].keys())
        if total_meta is None and isinstance(data, dict) and "totalFilas" in data:
            total_meta = data["totalFilas"]
        for rec in arr:
            if not isinstance(rec, dict):
                continue
            for e in enums:
                v = rec.get(e)
                if v is not None:
                    counters[e][str(v)[:60]] += 1
    out = {"rows": rows, "fields": fields,
           "enums": {e: dict(c.most_common(ENUM_TOP)) for e, c in counters.items() if c},
           "count_mode": f"json_dir:{len(paths)}files"}
    if total_meta is not None:
        out["meta"] = {"totalFilas": total_meta}
    return out


def snapshot_part(part: dict) -> tuple[dict | None, list[Path]]:
    paths = sorted(ROOT.glob(part["glob"])) if "*" in part["glob"] else (
        [ROOT / part["glob"]] if (ROOT / part["glob"]).exists() else [])
    paths = [p for p in paths if p.is_file()]
    if not paths:
        return None, []
    kind = part["kind"]
    if kind == "csv":
        snap = snapshot_csv(paths[0], part.get("enums") or [])
    elif kind == "jsonl":
        snap = snapshot_jsonl(paths[0]) if len(paths) == 1 else _merge_jsonl(paths)
    elif kind == "json_list":
        snap = snapshot_json_list(paths[0], part.get("list_key"), part.get("enums") or [],
                                  part.get("fields_key"), part.get("fields", True))
    elif kind == "json_marker":
        snap = snapshot_json_marker(paths[0], part["marker"])
    elif kind == "xml_tag":
        n, fields = _xml_count_and_fields(paths[0], part["tag"], part.get("fields_from_first", True))
        snap = {"rows": n, "fields": fields, "count_mode": f"xml_tag:{part['tag']}"}
    elif kind == "json_dir":
        snap = snapshot_json_dir(paths, part.get("list_key"), part.get("enums") or [])
    elif kind == "file_count":
        snap = {"rows": len(paths), "fields": [], "count_mode": "file_count"}
    else:
        raise SystemExit(f"未知 kind: {kind}")
    if not part.get("fields", True):
        snap.pop("fields", None)
    return snap, paths


def _merge_jsonl(paths: list[Path]) -> dict:
    total = 0
    fields: list[str] = []
    for p in paths:
        s = snapshot_jsonl(p)
        total += s["rows"]
        if not fields:
            fields = s["fields"]
    return {"rows": total, "fields": fields, "count_mode": "jsonl(merged)"}


def data_as_of_from(rel: str) -> str | None:
    p = ROOT / rel
    if not p.exists():
        return None
    name = p.name
    try:
        if name.endswith(".xml"):
            head = p.read_text(encoding="utf-8", errors="replace")[:4000]
            m = re.search(r"<lastUpdate>\s*([0-9-]+)\s*</lastUpdate>", head)
            return m.group(1) if m else None
        if name.endswith(".json"):
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list) and data and isinstance(data[0], dict):
                dates = [x for rec in data for x in (rec.get("DateSamples") or []) if x]
                return max(dates) if dates else None
            if isinstance(data, dict):
                if isinstance(data.get("meta"), dict) and data["meta"].get("last_updated"):
                    return data["meta"]["last_updated"]
                return data.get("data_as_of")
            return None
    except (OSError, json.JSONDecodeError):
        return None
    return None


# ---------------------------------------------------------------- 快照
def build_snapshot(only: set[str] | None = None) -> dict:
    out = {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
           "script_version": SCRIPT_VERSION, "sources": {}}
    for cfg in SOURCES:
        sid = cfg["source_id"]
        if only and sid not in only:
            continue
        parts: dict[str, dict] = {}
        files: list[dict] = []
        monitored: list[Path] = []
        for part in cfg["parts"]:
            snap, paths = snapshot_part(part)
            if part["kind"] != "file_count":
                monitored.extend(paths)
            if snap is None:
                parts[part["part"]] = {"skipped": True, "reason": "no files",
                                       "glob": part["glob"]}
                continue
            if part["kind"] != "file_count":
                snap["files"] = [str(p.relative_to(ROOT)).replace("\\", "/") for p in paths]
            parts[part["part"]] = snap
        for extra in cfg.get("extra_files") or []:
            p = ROOT / extra
            if p.exists():
                monitored.append(p)
        for p in sorted(set(monitored)):
            files.append({"path": str(p.relative_to(ROOT)).replace("\\", "/"),
                          "bytes": p.stat().st_size, "mtime": mtime_iso(p),
                          "sha256": sha256(p)})
        fetched_at = max((f["mtime"] for f in files), default=None)
        entry = {"label": cfg["label"], "parts": parts, "files": files,
                 "fetched_at": fetched_at}
        if cfg.get("data_as_of_from"):
            entry["data_as_of"] = data_as_of_from(cfg["data_as_of_from"])
        if cfg.get("note"):
            entry["note"] = cfg["note"]
        if not parts or all(v.get("skipped") for v in parts.values()):
            entry["skipped"] = True
        out["sources"][sid] = entry
    return out


# ---------------------------------------------------------------- 对比
def _row_alert(name: str, old: int, new: int) -> str | None:
    if old == new:
        return None
    if old >= ROW_SMALL:
        pct = (new - old) / old
        if abs(pct) > ROW_PCT:
            return (f"行数 {old:,} → {new:,}（{pct:+.1%}，阈值 ±{ROW_PCT:.0%}）")
        return None
    if abs(new - old) >= ROW_ABS_MIN:
        return f"行数 {old:,} → {new:,}（小来源绝对变化 ≥{ROW_ABS_MIN}）"
    return None


def compare(baseline: dict, current: dict) -> dict:
    alerts: list[dict] = []
    infos: list[str] = []
    skipped: list[str] = []
    for sid, cur in current["sources"].items():
        base = (baseline.get("sources") or {}).get(sid)
        if cur.get("skipped"):
            skipped.append(sid)
            continue
        if not base:
            infos.append(f"{sid}: 基线里没有该来源（新来源），建议更新基线")
            continue
        if (base.get("data_as_of") or None) != (cur.get("data_as_of") or None):
            infos.append(f"{sid}: data_as_of {base.get('data_as_of')} → {cur.get('data_as_of')}")
        base_parts = base.get("parts") or {}
        cur_parts = cur.get("parts") or {}
        for pname, cp in cur_parts.items():
            if cp.get("skipped"):
                alerts.append({"source": sid, "part": pname, "kind": "missing_files",
                               "detail": f"基线有、现在找不到文件（{cp.get('glob')}）"})
                continue
            bp = base_parts.get(pname)
            if not bp or bp.get("skipped"):
                infos.append(f"{sid}.{pname}: 新增 part（基线无）")
                continue
            ra = _row_alert(f"{sid}.{pname}", int(bp.get("rows", 0)), int(cp.get("rows", 0)))
            if ra:
                alerts.append({"source": sid, "part": pname, "kind": "rows", "detail": ra})
            bf, cf = set(bp.get("fields") or []), set(cp.get("fields") or [])
            if bf or cf:
                added, removed = sorted(cf - bf), sorted(bf - cf)
                if added:
                    alerts.append({"source": sid, "part": pname, "kind": "field_added",
                                   "detail": "新增字段：" + "、".join(added[:12])})
                if removed:
                    alerts.append({"source": sid, "part": pname, "kind": "field_removed",
                                   "detail": "字段消失：" + "、".join(removed[:12])})
            for ename, cvals in (cp.get("enums") or {}).items():
                bvals = (bp.get("enums") or {}).get(ename) or {}
                new_vals = [v for v in cvals if v not in bvals]
                if new_vals:
                    alerts.append({"source": sid, "part": pname, "kind": "enum_new",
                                   "detail": f"枚举 `{ename}` 新增值：" + "、".join(map(str, new_vals[:8]))})
        for pname in base_parts:
            if pname not in cur_parts:
                alerts.append({"source": sid, "part": pname, "kind": "missing_part",
                               "detail": "基线有该 part、现在没有"})
        bfiles = {f["path"]: f for f in base.get("files") or []}
        cfiles = {f["path"]: f for f in cur.get("files") or []}
        for path in bfiles:
            if path not in cfiles:
                alerts.append({"source": sid, "part": "-", "kind": "missing_file",
                               "detail": f"文件消失：{path}"})
        changed = [p for p in cfiles if p in bfiles and cfiles[p]["sha256"] != bfiles[p]["sha256"]]
        if changed:
            infos.append(f"{sid}: {len(changed)} 个文件 sha256 变化（正常刷新）")
    return {"alerts": alerts, "infos": infos, "skipped": skipped,
            "checked_at": current.get("generated_at")}


# ---------------------------------------------------------------- 报告
def render_report(result: dict, current: dict) -> str:
    lines = [f"# 数据源漂移告警 {date.today().isoformat()}", "",
             f"> 生成时间：{result.get('checked_at')} ｜ 脚本：`etl/drift_check.py` ｜ **只读，不改任何数据**",
             f"> 告警 {len(result['alerts'])} 条 / 提示 {len(result['infos'])} 条 / SKIP {len(result['skipped'])} 个来源", ""]
    if result["alerts"]:
        lines += ["## 告警", "", "| # | 来源 | part | 类型 | 明细 |", "|---:|---|---|---|---|"]
        for i, a in enumerate(result["alerts"], 1):
            lines.append(f"| {i} | `{a['source']}` | {a['part']} | {a['kind']} | {a['detail']} |")
        lines.append("")
    if result["infos"]:
        lines += ["## 提示（非告警）", ""]
        lines += [f"- {x}" for x in result["infos"]]
        lines.append("")
    if result["skipped"]:
        lines += ["## SKIP（缺原始缓存）", ""]
        lines += [f"- `{s}`：`data/raw/` 下没有匹配文件" for s in result["skipped"]]
        lines.append("")
    lines += ["## 处理流程（人工）", "",
              "1. 先判断是**数据源正常更新**还是**格式/字段变化**；",
              "2. 正常更新：Lead 批准后 `python etl/drift_check.py --write-baseline --force` 更新基线；",
              "3. 字段/枚举变化：先只读核对（`db/q.py` + 原始文件抽样），再决定是否改 ETL；",
              "4. 行数骤降/文件消失：确认缓存是否被清理或抓取失败，**不要**自动重跑 ingest；",
              "5. 本脚本不写 `data/drugs.db`、不自动改数据。", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- 自测
def self_test() -> int:
    base = build_snapshot()
    cur = json.loads(json.dumps(base))
    # 制造 3 类漂移
    sid1 = next(k for k, v in cur["sources"].items()
                if any((p or {}).get("rows", 0) > 50 for p in v["parts"].values()))
    p1 = next(p for p, v in cur["sources"][sid1]["parts"].items() if (v or {}).get("rows", 0) > 50)
    cur["sources"][sid1]["parts"][p1]["rows"] = int(
        cur["sources"][sid1]["parts"][p1]["rows"] * 1.25) + 1
    sid2 = next(k for k in cur["sources"] if k != sid1)
    p2 = next(iter(cur["sources"][sid2]["parts"]))
    cur["sources"][sid2]["parts"][p2]["fields"] = list(
        cur["sources"][sid2]["parts"][p2].get("fields") or []) + ["DRIFT_TEST_FIELD"]
    sid3 = next(k for k in cur["sources"] if k not in (sid1, sid2))
    p3 = next(p for p, v in cur["sources"][sid3]["parts"].items() if (v or {}).get("enums"))
    en = next(iter(cur["sources"][sid3]["parts"][p3]["enums"]))
    cur["sources"][sid3]["parts"][p3]["enums"][en]["DRIFT_TEST_VALUE"] = 1
    result = compare(base, cur)
    kinds = {a["kind"] for a in result["alerts"]}
    ok = {"rows", "field_added", "enum_new"} <= kinds
    out = Path(ROOT / ".tmp" / "drift-test")
    out.mkdir(parents=True, exist_ok=True)
    (out / "drift-test-report.md").write_text(render_report(result, cur), encoding="utf-8")
    (out / "drift-test-alerts.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[self-test] 基线来源 {len(base['sources'])} 个；模拟漂移：{sid1}.{p1} 行数、"
          f"{sid2}.{p2} 新字段、{sid3}.{p3}.{en} 新枚举")
    print(f"[self-test] 检出告警 {len(result['alerts'])} 条，类型 {sorted(kinds)} → "
          f"{'PASS' if ok else 'FAIL'}")
    print(f"[self-test] 输出：.tmp/drift-test/{{drift-test-report.md,drift-test-alerts.json}}")
    return 0 if ok else 1


# ---------------------------------------------------------------- 主流程
def print_summary(snap: dict) -> None:
    print(f"{'来源':<14} {'part':<20} {'行数':>10}  字段  枚举")
    for sid, s in snap["sources"].items():
        if s.get("skipped"):
            print(f"{sid:<14} {'-':<20} {'SKIP':>10}")
            continue
        for pname, p in s["parts"].items():
            if p.get("skipped"):
                print(f"{sid:<14} {pname:<20} {'SKIP':>10}")
                continue
            print(f"{sid:<14} {pname:<20} {p.get('rows', 0):>10,}  "
                  f"{len(p.get('fields') or []):>3}  {len(p.get('enums') or {}):>3}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="数据源漂移告警（只读）：生成/对比基线")
    ap.add_argument("--write-baseline", action="store_true", help="写基线到 data/sources/drift-baseline.json")
    ap.add_argument("--force", action="store_true", help="覆盖已有基线（需 Lead 批准）")
    ap.add_argument("--baseline", default=str(BASELINE))
    ap.add_argument("--source", default="", help="只处理这些 source_id（逗号分隔）")
    ap.add_argument("--json-out", default="", help="把当前快照写到该路径（可选）")
    ap.add_argument("--report-dir", default=str(REPORT_DIR))
    ap.add_argument("--always-report", action="store_true", help="无告警也写报告")
    ap.add_argument("--self-test", action="store_true", help="构造模拟漂移验证告警")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    only = {x.strip() for x in args.source.split(",") if x.strip()} or None
    snap = build_snapshot(only)
    if not args.quiet:
        print_summary(snap)
    if args.json_out:
        p = Path(args.json_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"快照：{p}")

    bpath = Path(args.baseline)
    if args.write_baseline:
        if bpath.exists() and not args.force:
            raise SystemExit(f"基线已存在：{bpath}；更新基线需 Lead 批准，加 --force 才覆盖。")
        bpath.parent.mkdir(parents=True, exist_ok=True)
        bpath.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"基线已写入：{bpath}（{len(snap['sources'])} 个来源）")
        return 0

    if not bpath.exists():
        raise SystemExit(f"没有基线：{bpath}；先跑 --write-baseline。")
    baseline = json.loads(bpath.read_text(encoding="utf-8"))
    result = compare(baseline, snap)
    print(f"\n告警 {len(result['alerts'])} 条；提示 {len(result['infos'])} 条；"
          f"SKIP {len(result['skipped'])} 个")
    for a in result["alerts"]:
        print(f"  ! [{a['kind']}] {a['source']}.{a['part']}: {a['detail']}")
    if result["alerts"] or args.always_report:
        rdir = Path(args.report_dir)
        rdir.mkdir(parents=True, exist_ok=True)
        rp = rdir / f"drift-{date.today().strftime('%Y%m%d')}.md"
        rp.write_text(render_report(result, snap), encoding="utf-8")
        print(f"报告：{rp}")
    else:
        print("无漂移（未写报告；加 --always-report 可强制写）")
    return 1 if result["alerts"] else 0


if __name__ == "__main__":
    sys.exit(main())
