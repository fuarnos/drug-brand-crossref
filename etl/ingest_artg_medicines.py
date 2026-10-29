# -*- coding: utf-8 -*-
"""AU ARTG Medicines 公开入库（task-11 数据侧）：TGA ARTG 导出 → product/component/name。

数据：`data/raw/artg_20261028/ARTG_Medicines_{1991-2020,2021-2026}.csv`（TGA ARTG Search
Visualisation Tool 导出，37,097 行 / 34,606 个 ARTG ID / 32 列）。许可：TGA 授权非商业使用，
本站只发布事实字段并署名 TGA / ARTG（见 docs/许可清单.md §2.6）。

口径
----
- 产品键 = `AU-ARTG-<ARTG ID>`（与既有 artg_detail/artg_enrich 一致，可合并身份）；
- 同一 ARTG ID 的多行（2,170 个 ID / 4,661 行）合并成一个产品：名称/sponsor/剂型/途径取首个非空，
  包装合并去重，成分按 (成分名, 规格) 并集；
- **`status='unknown'`**（导出无条目状态列，不推断在售）；`release='none'`；`strength` 只来自
  `Active Ingredients` 的 `Quantity`，不猜；
- 剂型保留 ARTG 原文（`dosage_form`），另算 canonical `form_base`；`category` 保留
  `Registered` / `Listed` / `Listed (Export Only)`（出口专用会在 note 标注）；
- 成分映射复用 TW/HK 的机制（DB inn_en + 盐 variant + TW 别名表 + BAN→INN）；**未匹配成分丢弃计数**，
  不硬造成分；单位用 Decimal 归一（g/kg/µg→mg、L/µL→mL）。
- 已存在的 ARTG-ID 产品（artg_detail 1,702 / artg_enrich 144）：**只补空字段**（route/pack/名称），
  不改 source、不改身份；撤销清单记录旧值。

用法
----
    python etl/ingest_artg_medicines.py                          # dry-run（默认只读）
    python etl/ingest_artg_medicines.py --limit 500              # 小样本 dry-run
    python etl/ingest_artg_medicines.py --apply --db <副本>       # 副本写入
    python etl/ingest_artg_medicines.py --apply --allow-real --db data/drugs.db \
        --manifest .tmp/artg-ingest/artg_write_manifest.json
    python etl/ingest_artg_medicines.py --rollback --allow-real --db data/drugs.db \
        --manifest .tmp/artg-ingest/artg_write_manifest.json
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
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))

from normalize_name import normalize  # noqa: E402
from ingest_tw_tfda import (  # noqa: E402  复用成分映射
    _split_salt_local,
    load_aliases,
    load_substance_map,
    match_component,
    nk,
)
from ingest_hk_druglist import HK_BAN_TO_INN  # noqa: E402  BAN→INN（澳洲/英国惯用名）

CSV_DIR = ROOT / "data" / "raw" / "artg_20261028"
CSV_FILES = ("ARTG_Medicines_1991-2020.csv", "ARTG_Medicines_2021-2026.csv")
WORK = ROOT / ".tmp" / "artg-ingest"
DEFAULT_MANIFEST = WORK / "artg_write_manifest.json"
DB_DEFAULT = ROOT / "data" / "drugs.db"
REAL_DB = DB_DEFAULT.resolve()
SOURCE_ID = "artg_export"
SOURCE_NAME = "TGA — Australian Register of Therapeutic Goods (ARTG Medicines export)"
SOURCE_URL = "https://compliance.health.gov.au/artg/"
LICENSE = "TGA 授权非商业使用（署名 TGA / ARTG；本站免费非商业）"
LICENSE_URL = "https://www.tga.gov.au/copyright"
DATA_AS_OF = "2026-10-28"
TODAY = date.today().isoformat()
SCRIPT_VERSION = "2026-10-30"

QTY_RE = re.compile(r"Quantity:\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-zµμ%/]+)?")
MASS = {"mg": Decimal(1), "g": Decimal(1000), "kg": Decimal(1_000_000),
        "mcg": Decimal("0.001"), "ug": Decimal("0.001"), "μg": Decimal("0.001"),
        "µg": Decimal("0.001"), "ng": Decimal("0.000001")}
VOLUME = {"ml": Decimal(1), "l": Decimal(1000), "ul": Decimal("0.001"),
          "mcl": Decimal("0.001"), "µl": Decimal("0.001")}
UNIT_CANON = {"iu": "IU", "unit": "unit", "units": "unit", "u": "unit",
              "meq": "mEq", "mci": "mCi", "uci": "µCi", "vg": "VG", "vp": "VP",
              "%": "%", "%w/v": "%w/v", "%w/w": "%w/w"}
FORM_BASE = (
    (("tablet", "caplet", "lozenge", "pastille"), "tablet"),
    (("capsule",), "capsule"),
    (("injection", "infusion", "vial", "ampoule", "syringe"), "injection"),
    (("cream", "ointment", "gel", "lotion", "paste", "patch", "plaster", "emulsion"), "topical"),
    (("liquid", "solution", "syrup", "suspension", "elixir", "drops", "mouthwash"), "liquid"),
    (("powder", "granule", "sachet"), "powder"),
    (("suppository", "pessary", "enema"), "suppository"),
    (("inhaler", "inhalation", "aerosol", "spray", "nebuliser", "nebulizer"), "inhalation"),
    (("pill",), "pill"),
)


def connect(db: Path, write: bool) -> sqlite3.Connection:
    if write:
        return sqlite3.connect(db, timeout=240)
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=240)


def _guard(db_path: Path, allow_real: bool) -> None:
    if db_path.resolve() == REAL_DB and not allow_real:
        raise SystemExit(f"拒绝写真实库 {REAL_DB}：先副本 dry-run；Lead 批准后加 --allow-real。")


def form_base_of(text: str) -> str:
    t = (text or "").lower()
    for keys, base in FORM_BASE:
        if any(k in t for k in keys):
            return base
    return "unknown"


def canon_unit(raw: str | None) -> tuple[Decimal | None, str]:
    """返回 (换算到 mg/mL 的因子, 规范单位)。未知/复合单位因子 None、单位保留原文。"""
    u = (raw or "").strip()
    if not u:
        return None, ""
    key = u.lower().rstrip(".")
    if key in MASS:
        return MASS[key], "mg"
    if key in VOLUME:
        return VOLUME[key], "mL"
    if key in UNIT_CANON:
        return Decimal(1), UNIT_CANON[key]
    return None, u


def split_ingredients(text: str) -> list[str]:
    """按分号切成分，但**忽略括号内**的分号（`(Equivalent: A, Qty x; Equivalent: B, Qty y)`）。"""
    out: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in text or "":
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == ";" and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [x.strip() for x in out if x.strip()]


def parse_ingredients(text: str) -> list[dict]:
    out = []
    for part in split_ingredients(text):
        name = part.split(",")[0].strip()
        if not name:
            continue
        m = QTY_RE.search(part)
        if m:
            factor, unit = canon_unit(m.group(2))
            value = Decimal(m.group(1)) * factor if factor is not None else Decimal(m.group(1))
            out.append({"name": name, "value": float(value), "unit": unit,
                        "raw_unit": (m.group(2) or "")})
        else:
            out.append({"name": name, "value": None, "unit": "", "raw_unit": ""})
    return out


def load_export(csv_dir: Path, limit: int = 0) -> tuple[dict, dict]:
    """读两个 CSV → 按 ARTG ID 合并。返回 (records, stats)。"""
    stats = {"rows": 0, "ids": 0, "skipped_rows": 0, "categories": Counter()}
    records: dict[str, dict] = {}
    for fn in CSV_FILES:
        path = csv_dir / fn
        if not path.exists():
            raise SystemExit(f"缺少 {path}（先把 ARTG 导出解压到 data/raw/artg_20261028/）")
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                if limit and stats["rows"] >= limit:
                    break
                stats["rows"] += 1
                aid = (row.get("ARTG ID") or "").strip()
                if not aid:
                    stats["skipped_rows"] += 1
                    continue
                rec = records.setdefault(aid, {
                    "artg_id": aid, "name": "", "sponsor": "", "form": "", "route": "",
                    "packs": [], "category": "", "start": "", "ings": [],
                })
                for field, col in (("name", "Product Name"), ("sponsor", "Sponsor Name"),
                                   ("form", "Dosage Form"), ("route", "Route of Administration"),
                                   ("category", "ARTG Category"), ("start", "Start Date")):
                    if not rec[field]:
                        rec[field] = (row.get(col) or "").strip()
                pack = (row.get("Pack Size") or "").strip()
                if pack and pack not in rec["packs"]:
                    rec["packs"].append(pack)
                rec["ings"].extend(parse_ingredients(row.get("Active Ingredients") or ""))
                stats["categories"][(row.get("ARTG Category") or "").strip()] += 1
    stats["ids"] = len(records)
    return records, stats


def match_ingredient(raw: str, mapping: dict, aliases: dict) -> dict:
    rec = match_component(raw, mapping, aliases)
    if rec.get("substance_id"):
        return rec
    base, salt = _split_salt_local(nk(raw))
    for cand in (nk(raw), base):
        inn = HK_BAN_TO_INN.get(cand.lower())
        if not inn:
            continue
        sid = mapping.get((nk(inn), nk(salt))) or mapping.get((nk(inn), ""))
        if sid:
            rec.update(substance_id=sid, salt=salt, salt_code="", status="matched",
                       note="ban_alias")
            return rec
    return rec


def build(records: dict, mapping: dict, aliases: dict, limit: int = 0,
          keep_name_only: bool = False) -> tuple[list[dict], dict]:
    kept: list[dict] = []
    stats = {"products": 0, "components": 0, "components_unmapped": 0,
             "tokens_total": 0, "tokens_matched": 0, "unmatched": {},
             "no_ingredient_products": 0, "name_only_kept": 0,
             "export_only": 0, "component_rows": 0}
    unmatched: Counter = Counter()
    for i, (aid, rec) in enumerate(sorted(records.items())):
        if limit and i >= limit:
            break
        seen: set[tuple[str, float | None, str]] = set()
        comps: list[dict] = []
        for ing in rec["ings"]:
            stats["tokens_total"] += 1
            c = match_ingredient(ing["name"], mapping, aliases)
            key = (c.get("substance_id") or "", ing["value"], ing["unit"])
            if not c.get("substance_id"):
                stats["components_unmapped"] += 1
                unmatched[nk(ing["name"])] += 1
                continue
            stats["tokens_matched"] += 1
            if key in seen:
                continue
            seen.add(key)
            c.update(value=ing["value"], unit=ing["unit"])
            comps.append(c)
        if not comps:
            stats["no_ingredient_products"] += 1
            if not keep_name_only:
                continue
            stats["name_only_kept"] += 1
        note_bits = ["ARTG 2026-10-28 导出", f"類別={rec['category'] or '?'}"]
        if "export only" in (rec["category"] or "").lower():
            stats["export_only"] += 1
            note_bits.append("Listed (Export Only)：僅供出口，非澳洲境內供應")
        if not comps:
            note_bits.append("無可用成分（僅名稱層）")
        if rec["start"]:
            note_bits.append(f"注冊起始={rec['start'][:10]}")
        kept.append({
            "product_id": f"AU-ARTG-{aid}", "artg_id": aid, "name": rec["name"],
            "sponsor": rec["sponsor"], "form": rec["form"], "form_base": form_base_of(rec["form"]),
            "route": rec["route"], "pack": " / ".join(rec["packs"])[:200] or None,
            "category": rec["category"] or None, "note": "；".join(note_bits)[:300],
            "components_detail": comps, "n_ingredients": len(rec["ings"]),
            "matched_components": len(comps),
        })
        stats["products"] += 1
        stats["components"] += len(comps)
        stats["component_rows"] += len(rec["ings"])
    stats["unmatched_top"] = dict(unmatched.most_common(15))
    stats["unmatched_distinct"] = len(unmatched)
    stats["token_coverage_pct"] = round(
        100 * stats["tokens_matched"] / max(1, stats["tokens_total"]), 1)
    return kept, stats


# ---------------------------------------------------------------- 写库
def _require_schema(db: sqlite3.Connection) -> None:
    row = db.execute("SELECT sql FROM sqlite_master WHERE name='product'").fetchone()
    if not row or "'AU'" not in (row[0] or ""):
        raise SystemExit("product.country CHECK 缺 AU？schema 异常，停止。")


def _ensure_source(db: sqlite3.Connection) -> None:
    if db.execute("SELECT 1 FROM source WHERE source_id=?", (SOURCE_ID,)).fetchone():
        db.execute("UPDATE source SET license=?, license_url=?, data_as_of=?,"
                   " license_url=? WHERE source_id=?", (LICENSE, LICENSE_URL, DATA_AS_OF,
                                                       LICENSE_URL, SOURCE_ID))
        return
    db.execute(
        "INSERT INTO source (source_id, name, url, license, license_url, retrieved_at,"
        " data_as_of, data_as_of_note, notes) VALUES (?,?,?,?,?,?,?,?,?)",
        (SOURCE_ID, SOURCE_NAME, SOURCE_URL, LICENSE, LICENSE_URL, TODAY, DATA_AS_OF,
         "single export（官方 XML/CSV 导出，date 由导出日期）",
         "TGA ARTG Search Visualisation Tool 导出；无条目状态列；Listed (Export Only) 单独标注。"))


def _resolve_variant(db: sqlite3.Connection) -> "callable":
    vidx: dict[tuple[str, str], str] = {}
    for r in db.execute("SELECT variant_id, substance_id, COALESCE(salt_code,'') sc FROM variant"):
        vidx[(r[1], r[2])] = r[0]
    by_sid: dict[str, list[tuple[str, str]]] = {}
    for (sid, sc), vid in vidx.items():
        by_sid.setdefault(sid, []).append((vid, sc))
    salt_codes = {sc for (_sid, sc) in vidx if sc}

    def resolve(sid: str, salt: str) -> str | None:
        salt_en = nk(salt)
        sc = ""
        if salt_en:
            try:
                from normalize_salts import classify_salt
                cl = classify_salt(salt_en)
                sc = cl.salt_code if cl.kind == "salt" else ""
            except Exception:  # noqa: BLE001
                sc = ""
        vid = vidx.get((sid, sc)) or vidx.get((sid, ""))
        if vid:
            return vid
        cands = by_sid.get(sid) or []
        if len(cands) == 1:
            return cands[0][0]
        for v, s in cands:
            if s and (s == sc or s in sid):
                return v
        if cands:
            return next((v for v, s in cands if s), cands[0][0])
        for one in sorted(salt_codes, key=len, reverse=True):
            if sid.endswith("-" + one):
                base = sid[: -len(one) - 1]
                bvid = vidx.get((base, one)) or vidx.get((base, ""))
                if bvid:
                    return bvid
                for v, _s in (by_sid.get(base) or []):
                    return v
        return None
    return resolve


def existing_artg_products(db: sqlite3.Connection) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in db.execute(
            "SELECT product_id, approval_id, source_id, route, pack FROM product"
            " WHERE country='AU' AND approval_id IS NOT NULL AND approval_id<>''"
            " AND source_id<>'artg_export'"):
        out.setdefault(r[1], {"product_id": r[0], "source_id": r[2],
                              "route": r[3], "pack": r[4]})
    return out


def write_db(db_path: Path, kept: list[dict], stats: dict, manifest_path: Path,
             allow_real: bool) -> dict:
    _guard(db_path, allow_real)
    t0 = time.perf_counter()
    db = sqlite3.connect(db_path, timeout=240)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    prev_keys: list[str] = []
    prev_variants: list[list[str]] = []
    prev_names: list[list[str]] = []
    prev_enriched: list[dict] = []
    if manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
            if old.get("source_id") == SOURCE_ID:
                prev_keys = list(old.get("created_name_keys") or [])
                prev_variants = [list(x) for x in (old.get("created_name_variants") or [])]
                prev_names = [list(x) for x in (old.get("added_product_names") or [])]
                prev_enriched = list(old.get("enriched") or [])
        except (OSError, ValueError):
            pass
    resolve = _resolve_variant(db)
    existing = existing_artg_products(db)
    try:
        _require_schema(db)
        _ensure_source(db)
        db.commit()
        db.execute("BEGIN IMMEDIATE")
        removed = db.execute("DELETE FROM product WHERE source_id=?", (SOURCE_ID,)).rowcount
        run_id = f"{SOURCE_ID}-{DATA_AS_OF}"
        created_keys: list[str] = []
        created_variants: list[list[str]] = []
        product_ids: list[str] = []
        enriched: list[dict] = []
        added_names: list[list[str]] = []
        comp_count = 0
        comp_dropped = 0
        for row in kept:
            pid = row["product_id"]
            if row["artg_id"] in existing:
                # 已有 ARTG-ID 产品：只补空字段 + 缺名，不改身份
                ex = existing[row["artg_id"]]
                if not (ex["route"] or "").strip() and row["route"]:
                    db.execute("UPDATE product SET route=? WHERE product_id=?",
                               (row["route"], ex["product_id"]))
                    enriched.append({"product_id": ex["product_id"], "field": "route",
                                     "old": None, "new": row["route"]})
                if not (ex["pack"] or "").strip() and row["pack"]:
                    db.execute("UPDATE product SET pack=? WHERE product_id=?",
                               (row["pack"], ex["product_id"]))
                    enriched.append({"product_id": ex["product_id"], "field": "pack",
                                     "old": None, "new": row["pack"]})
                if row["name"]:
                    nm = normalize(row["name"])
                    if nm.norm:
                        c1 = db.execute("INSERT OR IGNORE INTO name_key (key_id, norm, compact,"
                                        " script) VALUES (?,?,?,?)",
                                        (nm.norm, nm.norm, nm.norm.replace(" ", ""), nm.script
                                         if nm.script in ("latin", "cyrillic", "han", "kana",
                                                          "hangul") else "latin"))
                        if c1.rowcount:
                            created_keys.append(nm.norm)
                        c2 = db.execute("INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                                        " VALUES (?,?,?)", (nm.norm, row["name"], SOURCE_ID))
                        if c2.rowcount:
                            created_variants.append([nm.norm, row["name"]])
                        c3 = db.execute("INSERT OR IGNORE INTO product_name (product_id, key_id,"
                                        " name_type, is_primary) VALUES (?,?,'trade',0)",
                                        (ex["product_id"], nm.norm))
                        if c3.rowcount:
                            added_names.append([ex["product_id"], nm.norm, "trade"])
                continue
            db.execute(
                "INSERT OR REPLACE INTO product (product_id, country, dosage_form, form_base,"
                " route, release, pack, mah, approval_id, category, is_branded, status,"
                " status_date, source_id, source_url, retrieved_at, note)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, "AU", row["form"] or "not stated", row["form_base"], row["route"] or None,
                 "none", row["pack"], row["sponsor"] or None, row["artg_id"],
                 f"ARTG {row['category']}" if row["category"] else None, 1, "unknown", None,
                 SOURCE_ID, SOURCE_URL, TODAY, row["note"]))
            product_ids.append(pid)
            for i, c in enumerate(row["components_detail"]):
                vid = resolve(c["substance_id"], c.get("salt") or "")
                if not vid:
                    comp_dropped += 1
                    continue
                db.execute(
                    "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                    " strength_value, strength_unit, per_volume_value, per_volume_unit)"
                    " VALUES (?,?,?,?,?,NULL,NULL)",
                    (pid, i, vid, c.get("value"), c.get("unit") or None))
                comp_count += 1
            raw = (row["name"] or "").strip()
            if raw:
                nm = normalize(raw)
                if nm.norm:
                    cur = db.execute("INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                                     " VALUES (?,?,?,?)",
                                     (nm.norm, nm.norm, nm.norm.replace(" ", ""),
                                      nm.script if nm.script in ("latin", "cyrillic", "han",
                                                                 "kana", "hangul") else "latin"))
                    if cur.rowcount:
                        created_keys.append(nm.norm)
                    cur2 = db.execute("INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                                      " VALUES (?,?,?)", (nm.norm, raw, SOURCE_ID))
                    if cur2.rowcount:
                        created_variants.append([nm.norm, raw])
                    db.execute("INSERT OR IGNORE INTO product_name (product_id, key_id, name_type,"
                               " is_primary) VALUES (?,?,'trade',1)", (pid, nm.norm))
        db.execute(
            "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
            " rows_in, rows_kept, rows_rejected, status, note)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, SOURCE_ID, TODAY, datetime.now().isoformat(timespec="seconds"),
             stats["rows"], len(product_ids), stats["rows"] - len(product_ids), "ok",
             json.dumps({"mode": "apply", "version": SCRIPT_VERSION,
                         "components": comp_count, "enriched": len(enriched)},
                        ensure_ascii=False)))
        db.commit()
        manifest = {
            "source_id": SOURCE_ID, "version": SCRIPT_VERSION, "run_id": run_id,
            "db": str(db_path.resolve()), "data_as_of": DATA_AS_OF,
            "counts": {"rows_in": stats["rows"], "products": len(product_ids),
                       "components": comp_count, "components_dropped_no_variant": comp_dropped,
                       "enriched": len(enriched),
                       "created_name_keys": len(created_keys),
                       "created_name_variants": len(created_variants)},
            "product_ids": product_ids,
            "created_name_keys": sorted(set(created_keys) | set(prev_keys)),
            "created_name_variants": created_variants + prev_variants,
            "added_product_names": added_names + prev_names,
            "enriched": enriched + prev_enriched,
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return {"run_id": run_id, "removed_old_products": removed,
                "products": len(product_ids), "components": comp_count,
                "components_dropped_no_variant": comp_dropped,
                "enriched": len(enriched), "created_name_keys": len(created_keys),
                "created_name_variants": len(created_variants),
                "elapsed_s": round(time.perf_counter() - t0, 2)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def rollback(db_path: Path, manifest_path: Path, allow_real: bool) -> dict:
    _guard(db_path, allow_real)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    db = sqlite3.connect(db_path, timeout=240)
    db.execute("PRAGMA foreign_keys=ON")
    t0 = time.perf_counter()
    try:
        db.execute("BEGIN IMMEDIATE")
        pids = data.get("product_ids") or []
        removed = 0
        for i in range(0, len(pids), 400):
            part = pids[i:i + 400]
            q = ",".join("?" * len(part))
            removed += db.execute(f"DELETE FROM product WHERE product_id IN ({q})", part).rowcount
        for rec in data.get("added_product_names") or []:
            db.execute("DELETE FROM product_name WHERE product_id=? AND key_id=? AND name_type=?",
                       rec)
        for item in data.get("enriched") or []:
            db.execute(f"UPDATE product SET {item['field']}=? WHERE product_id=?",
                       (item.get("old"), item["product_id"]))
        for k, raw in data.get("created_name_variants") or []:
            db.execute("DELETE FROM name_variant WHERE key_id=? AND raw=?", (k, raw))
        keys = data.get("created_name_keys") or []
        if keys:
            q = ",".join("?" * len(keys))
            db.execute(f"DELETE FROM name_key WHERE key_id IN ({q}) AND key_id NOT IN"
                       " (SELECT key_id FROM product_name UNION SELECT key_id FROM name_variant)",
                       keys)
        db.execute("DELETE FROM ingest_run WHERE run_id=?", (data.get("run_id"),))
        db.commit()
        return {"removed_products": removed, "restored_enriched": len(data.get("enriched") or []),
                "removed_keys": len(keys), "elapsed_s": round(time.perf_counter() - t0, 2)}
    finally:
        db.close()


def print_plan(kept: list[dict], stats: dict, existing: int) -> None:
    print("=== AU ARTG 入库计划（dry-run）===")
    print(f"  导出：{stats['rows']:,} 行 / {stats['ids']:,} 个 ARTG ID")
    print(f"  可入库 products：{stats['products']:,}（其中已存在 ARTG-ID 产品 {existing:,} 只补字段）"
          f"；新增 {stats['products'] - existing:,}")
    print(f"  成分：写成 {stats['components']:,} 行；未匹配 {stats['components_unmapped']:,}"
          f"（distinct {stats['unmatched_distinct']}）；token 覆盖 {stats['token_coverage_pct']}%")
    print(f"  无可用成分产品：{stats['no_ingredient_products']:,}；Listed (Export Only)：{stats['export_only']:,}")
    print("  未匹配 Top：", stats["unmatched_top"])
    print("  类别：", dict(stats["categories"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AU ARTG Medicines 公开入库（幂等 / 可回滚）")
    ap.add_argument("--csv-dir", default=str(CSV_DIR))
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个 ARTG ID（0=全量）")
    ap.add_argument("--keep-name-only", action="store_true",
                    help="无可映射成分的产品也入库（只名称层，默认丢弃）")
    ap.add_argument("--apply", action="store_true", help="写库（真实库需 --allow-real）")
    ap.add_argument("--rollback", action="store_true", help="按撤销清单回滚")
    ap.add_argument("--db", default=str(DB_DEFAULT))
    ap.add_argument("--allow-real", action="store_true")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    args = ap.parse_args(argv)
    db_path = Path(args.db)
    manifest = Path(args.manifest)

    if args.rollback:
        res = rollback(db_path, manifest, args.allow_real)
        print(f"回滚完成：{res}")
        return 0

    records, fstats = load_export(Path(args.csv_dir), args.limit)
    mapping, map_src = load_substance_map()
    aliases = load_aliases()
    kept, stats = build(records, mapping, aliases, args.limit, args.keep_name_only)
    stats = {**stats, "rows": fstats["rows"], "ids": fstats["ids"],
             "categories": fstats["categories"]}
    db = connect(db_path, write=False)
    existing = existing_artg_products(db)
    existing_hit = sum(1 for row in kept if row["artg_id"] in existing)
    db.close()
    print(f"  成分词典：{len(mapping):,} 个 (名,盐) 组合（{map_src}）；别名表 {len(aliases)}")
    print_plan(kept, stats, existing_hit)
    if not args.apply:
        print("\n（dry-run：未写库；加 --apply 才写）")
        return 0
    res = write_db(db_path, kept, stats, manifest, args.allow_real)
    print(f"\n== APPLY 完成 == {res}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
