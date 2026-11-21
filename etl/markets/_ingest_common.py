# -*- coding: utf-8 -*-
"""国别市场写库公用件（CZ / LV 共用）。

为什么单独一个模块：`etl/markets/cz.py`、`etl/markets/lv.py` 原本只有 `--dry-run`，
写库路径要照 `etl/markets/fr.py` / `etl/ingest_eu.py` 的三段式补（`--apply` / `--rollback` /
`--manifest`）。两个市场写的是同一套表、同一套回滚口径，所以把「连接 / 写 source / 写 product /
写 name / 写 component / 回滚」收在这里，避免两份实现漂移。

纪律（与 `AGENTS.md` §4、§9 一致）：
  - 只落来源既有字段，不换算、不四舍五入、不改来源含义；
  - 商品名不是主键：名字只进 `name_key` / `name_variant` / `product_name`，不参与产品唯一性；
  - 写库必须带 `--allow-real` 才允许动 `data/drugs.db`，否则只写 `.tmp/` 副本；
  - 回滚只删 manifest 里记过的行（保护既有数据），并逐表核对回写前计数。

本模块没有 CLI，只被 `etl/markets/cz.py`、`etl/markets/lv.py` 与 `etl/ingest_no.py`（挪威 FEST，
2026-11-21）引用。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys_stdout_guard = True  # 占位：调用方各自处理控制台编码

PRODUCT_COLUMNS = (
    "product_id", "country", "region", "dosage_form", "form_base", "route", "release",
    "pack", "mah", "approval_id", "category", "is_branded", "status", "status_date",
    "source_id", "source_url", "retrieved_at", "note",
)


def now() -> str:
    """UTC 秒级时间戳（manifest 用）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def connect(db_path: Path, write: bool = False) -> sqlite3.Connection:
    """写库连接开 `foreign_keys=ON`；只读一律 `mode=ro`。"""
    if write:
        db = sqlite3.connect(db_path, timeout=180)
        db.execute("PRAGMA foreign_keys=ON")
    else:
        db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=120)
    db.row_factory = sqlite3.Row
    return db


def guard_real(db_path: Path, real_db: Path, action: str, allow_real: bool) -> None:
    """真实库写保护（沿用 `etl/ingest_eu.py`）：没有 `--allow-real` 只允许写副本。"""
    try:
        is_real = db_path.resolve() == real_db.resolve()
    except OSError:
        is_real = False
    if is_real and not allow_real:
        raise SystemExit(
            f"拒绝在真实库 {db_path} 执行 {action}：DB 写窗口需显式加 --allow-real"
            "（并先备份 data/drugs.db、持有 manifest）。")
    if is_real:
        print(f"!! 警告：正在对真实库 {db_path} 执行 {action}（--allow-real），"
              "请确认已备份并持有回滚清单。")


def require_country(db: sqlite3.Connection, country: str) -> None:
    """`product.country` 的 CHECK 必须已含该国家码，否则产品行写不进去。"""
    row = db.execute("SELECT sql FROM sqlite_master WHERE name='product'").fetchone()
    sql = (row["sql"] if row else "") or ""
    if f"'{country}'" not in sql:
        raise SystemExit(
            f"product.country 的 CHECK 枚举没有 '{country}'：先跑 `python db/init_db.py`"
            " 完成 schema 迁移（db/schema.sql 加国家码 → 幂等重建 product 表）。")


def table_counts(db: sqlite3.Connection, country: str, source_id: str) -> dict:
    """逐表计数（写前 / 写后 / 回滚后用同一口径）。"""
    return {
        "product": db.execute("SELECT COUNT(*) FROM product").fetchone()[0],
        "product_market": db.execute(
            "SELECT COUNT(*) FROM product WHERE country=? AND source_id=?",
            (country, source_id)).fetchone()[0],
        "product_component": db.execute("SELECT COUNT(*) FROM product_component").fetchone()[0],
        "product_name": db.execute("SELECT COUNT(*) FROM product_name").fetchone()[0],
        "name_key": db.execute("SELECT COUNT(*) FROM name_key").fetchone()[0],
        "name_variant": db.execute("SELECT COUNT(*) FROM name_variant").fetchone()[0],
        "substance": db.execute("SELECT COUNT(*) FROM substance").fetchone()[0],
        "variant": db.execute("SELECT COUNT(*) FROM variant").fetchone()[0],
        "source": db.execute("SELECT COUNT(*) FROM source").fetchone()[0],
        "ingest_run": db.execute("SELECT COUNT(*) FROM ingest_run").fetchone()[0],
    }


def insert_source(db: sqlite3.Connection, source_id: str, meta: dict) -> tuple[bool, dict | None]:
    """写/更新 source 行 → (写前是否存在, 写前行快照)。"""
    before = db.execute("SELECT * FROM source WHERE source_id=?", (source_id,)).fetchone()
    db.execute(
        "INSERT INTO source (source_id, name, url, license, license_url, retrieved_at,"
        " data_as_of, data_as_of_note, notes) VALUES (?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(source_id) DO UPDATE SET name=excluded.name, url=excluded.url,"
        " license=excluded.license, license_url=excluded.license_url,"
        " retrieved_at=excluded.retrieved_at, data_as_of=excluded.data_as_of,"
        " data_as_of_note=excluded.data_as_of_note, notes=excluded.notes",
        (source_id, meta["name"], meta.get("url"), meta.get("license"),
         meta.get("license_url"), meta["retrieved_at"], meta.get("data_as_of"),
         meta.get("data_as_of_note"), meta.get("notes")))
    return (before is not None), (dict(before) if before else None)


def write_product(db: sqlite3.Connection, rec: dict) -> int:
    """写一行 product（字段缺省为 NULL / 默认值）。"""
    values = (
        rec["product_id"], rec["country"], None, rec["dosage_form"], rec.get("form_base"),
        rec.get("route"), rec.get("release") or "none", rec.get("pack"), rec.get("mah") or None,
        rec.get("approval_id") or None, rec.get("category") or None, rec.get("is_branded", 1),
        rec["status"], rec.get("status_date") or None, rec["source_id"], rec.get("source_url"),
        rec["retrieved_at"], (rec.get("note") or None),
    )
    return db.execute(
        "INSERT OR REPLACE INTO product (product_id, country, region, dosage_form, form_base,"
        " route, release, pack, mah, approval_id, category, is_branded, status, status_date,"
        " source_id, source_url, retrieved_at, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        values).rowcount


def write_name(db: sqlite3.Connection, product_id: str, raw: str, name_type: str,
               is_primary: int, source_id: str, normalize_fn) -> dict:
    """写一个名字：name_key（缺失则建）+ name_variant + product_name。

    `normalize_fn` 由调用方给（CZ / LV 各自的归一化入口），保证两处口径一致。
    """
    written = Counter()
    raw = (raw or "").strip()
    if not raw:
        return dict(written)
    nm = normalize_fn(raw)
    if not nm or not getattr(nm, "norm", ""):
        return dict(written)
    key = nm.norm
    written["name_key"] += db.execute(
        "INSERT OR IGNORE INTO name_key (key_id, norm, compact, script, lang)"
        " VALUES (?,?,?,?,NULL)", (key, key, nm.compact, nm.script)).rowcount
    written["name_variant"] += db.execute(
        "INSERT OR IGNORE INTO name_variant (key_id, raw, source_id) VALUES (?,?,?)",
        (key, raw, source_id)).rowcount
    written["product_name"] += db.execute(
        "INSERT OR IGNORE INTO product_name (product_id, key_id, name_type, is_primary)"
        " VALUES (?,?,?,?)", (product_id, key, name_type, is_primary)).rowcount
    return dict(written)


def write_component(db: sqlite3.Connection, product_id: str, ord_: int, variant_id: str,
                    strength: dict | None) -> int:
    """写一行 product_component（强度按来源原文，不换算）。"""
    s = strength or {}
    return db.execute(
        "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id, strength_value,"
        " strength_unit, per_volume_value, per_volume_unit) VALUES (?,?,?,?,?,?,?)",
        (product_id, ord_, variant_id, s.get("value"), s.get("unit"),
         s.get("per_volume_value"), s.get("per_volume_unit"))).rowcount


def write_ingest_run(db: sqlite3.Connection, run_id: str, source_id: str, started_at: str,
                     rows_in: int, rows_kept: int, note: dict) -> int:
    return db.execute(
        "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
        " rows_in, rows_kept, rows_rejected, status, note) VALUES (?,?,?,?,?,?,?,?,?)",
        (run_id, source_id, started_at, now(), rows_in, rows_kept,
         max(0, rows_in - rows_kept), "ok", json.dumps(note, ensure_ascii=False))).rowcount


def ensure_substance(db: sqlite3.Connection, inn_en: str, source_id: str,
                     decided_at: str, confidence: str = "medium") -> tuple[str, str, bool, bool]:
    """建一个新成分 + 它的 base variant（只在有出处时由调用方调用）。

    返回 (substance_id, variant_id, substance_created, variant_created)。已存在同 slug /
    同 inn_en 的成分直接复用；已有 variant 的成分不再造 variant（不猜盐型）。
    """
    from ingest_openfda_ndc import slug  # 循环引用无风险：调用时才导入

    inn_en = re.sub(r"\s+", " ", (inn_en or "").strip())
    sid = slug(inn_en)[:64]
    row = db.execute("SELECT substance_id FROM substance WHERE substance_id=? OR inn_en=?",
                     (sid, inn_en)).fetchone()
    created_sub = False
    if row:
        sid = row["substance_id"]
    else:
        db.execute(
            "INSERT INTO substance (substance_id, inn_en, source_id, method, confidence,"
            " decided_at, name_lang) VALUES (?,?,?,'imported',?,?,'en')",
            (sid, inn_en, source_id, confidence, decided_at))
        created_sub = True
    vrow = db.execute("SELECT variant_id FROM variant WHERE substance_id=?"
                      " ORDER BY variant_id LIMIT 1", (sid,)).fetchone()
    if vrow:
        return sid, vrow["variant_id"], created_sub, False
    vid = sid
    n = 1
    while db.execute("SELECT 1 FROM variant WHERE variant_id=?", (vid,)).fetchone():
        n += 1
        vid = f"{sid}-base{n}" if n > 1 else f"{sid}-base"
    db.execute(
        "INSERT INTO variant (variant_id, substance_id, salt, hydrate, ester, base_fraction,"
        " interchange, interchange_note, salt_code, strength_basis)"
        " VALUES (?,?,?,?,?,1.0,'unknown',NULL,'','unknown')", (vid, sid, "", "", ""))
    return sid, vid, created_sub, True


def rollback(db_path: Path, manifest: dict, country: str, source_id: str) -> tuple[dict, dict, dict]:
    """按 manifest 只删本次写入的行，并核对是否回到写前计数。"""
    targets = manifest
    if targets.get("source_id") != source_id or targets.get("country") != country:
        raise SystemExit("manifest 的 source_id/country 与本次回滚不匹配，拒绝执行")
    db = connect(db_path, write=True)
    removed = Counter()
    try:
        db.execute("BEGIN IMMEDIATE")
        for pid in targets.get("product_ids") or []:
            removed["product"] += db.execute(
                "DELETE FROM product WHERE product_id=? AND country=? AND source_id=?",
                (pid, country, source_id)).rowcount
        removed["ingest_run"] += db.execute(
            "DELETE FROM ingest_run WHERE run_id=?", (targets.get("run_id") or "",)).rowcount
        for key, raw in targets.get("created_name_variants") or []:
            removed["name_variant"] += db.execute(
                "DELETE FROM name_variant WHERE key_id=? AND raw=? AND source_id=?",
                (key, raw, source_id)).rowcount
        for key in targets.get("created_name_keys") or []:
            if not db.execute("SELECT 1 FROM product_name WHERE key_id=? LIMIT 1",
                              (key,)).fetchone():
                removed["name_variant"] += db.execute(
                    "DELETE FROM name_variant WHERE key_id=? AND source_id=?",
                    (key, source_id)).rowcount
                removed["name_key"] += db.execute(
                    "DELETE FROM name_key WHERE key_id=?", (key,)).rowcount
        # 新成分（只删本次建的、且已无产品引用的）
        for sid in targets.get("created_substances") or []:
            if db.execute("SELECT 1 FROM product_component pc JOIN variant v"
                          " ON v.variant_id = pc.variant_id WHERE v.substance_id=? LIMIT 1",
                          (sid,)).fetchone():
                continue
            removed["variant"] += db.execute(
                "DELETE FROM variant WHERE substance_id=?", (sid,)).rowcount
            removed["substance"] += db.execute(
                "DELETE FROM substance WHERE substance_id=?", (sid,)).rowcount
        # 给「既有 substance」补建的 base variant（KR 2026-11-22 起；只删仍未被引用的）
        for vid in targets.get("created_variants_for_existing_substances") or []:
            if db.execute("SELECT 1 FROM product_component WHERE variant_id=? LIMIT 1",
                          (vid,)).fetchone():
                continue
            removed["variant"] += db.execute(
                "DELETE FROM variant WHERE variant_id=?", (vid,)).rowcount
        if targets.get("source_existed"):
            before = targets.get("source_before") or {}
            if before:
                db.execute(
                    "UPDATE source SET name=?, url=?, license=?, license_url=?, retrieved_at=?,"
                    " data_as_of=?, data_as_of_note=?, notes=? WHERE source_id=?",
                    (before.get("name"), before.get("url"), before.get("license"),
                     before.get("license_url"), before.get("retrieved_at"),
                     before.get("data_as_of"), before.get("data_as_of_note"),
                     before.get("notes"), source_id))
        else:
            still = db.execute(
                "SELECT COUNT(*) FROM product WHERE source_id=? AND country=?",
                (source_id, country)).fetchone()[0]
            if not still:
                removed["source"] += db.execute(
                    "DELETE FROM source WHERE source_id=?", (source_id,)).rowcount
        db.commit()
        after = table_counts(db, country, source_id)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    expected = targets.get("counts_before") or {}
    diff = {k: after.get(k, 0) - int(expected.get(k, 0)) for k in after}
    return dict(removed), after, diff
