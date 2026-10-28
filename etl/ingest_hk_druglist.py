"""香港衞生署「註冊藥劑製品名單」（DrugList.xml）→ 名称/成分层入库（task-88）。

数据源
------
`data/raw/hk_mo/hk_rpp_resource.xml`（源自 `http://www.drugoffice.gov.hk/eps/psi/DrugList.xml`，
data.gov.hk 数据集 hk-dh-dh_do-hk-dh-do-pharmaceutical-product；14,275 条；字段仅
productName / regCertHolderName / permitNo / activeIngs；**无规格、无剂型、无注册状态、无中文名**）。
许可：data.gov.hk Terms and Conditions（免费商用/非商用浏览、下载、分发、复制；须注明来源并
承认政府及原机构知识产权）。详见 `reports/hk-mo-audit.md` §1.2。

本脚本做什么
------------
- 解析 XML → product / product_component / name_key / name_variant / product_name / ingest_run；
- 成分：activeIng 串 → 复用 TW 的 `match_component`（DB inn_en+盐、TW 别名表、PBS/dm+d 别名），
  再叠一层香港常用 BAN→INN 别名（paracetamol→acetaminophen、frusemide→furosemide 等）；
  未匹配成分丢弃计数；整个产品无任何可挂成分则丢弃；
- **明确缺失字段**：`strength_value/unit=NULL`、`dosage_form='unknown'`、`release='none'`、
  `status='unknown'`（名单未提供状态；不等于 withdrawn）；note 写「HK DrugList: 無規格/劑型/狀態」；
- 幂等：按 `source_id='hk_dh'` 先删后写（FK 级联）；事务 + 撤销清单；默认拒绝写真实库。

用法
----
    python etl/ingest_hk_druglist.py                        # dry-run → .tmp/hk-ingest/hk_drugs_dryrun.csv
    python etl/ingest_hk_druglist.py --limit 500            # 小样本 dry-run
    python etl/ingest_hk_druglist.py --apply --db .tmp/hk-ingest/drugs-hk.db   # 写副本
    python etl/ingest_hk_druglist.py --apply --db .tmp/hk-ingest/drugs-hk.db --allow-real  # 写真实库（Lead）
    python etl/ingest_hk_druglist.py --rollback <manifest> --db ... --allow-real
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sqlite3
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))

from normalize_name import normalize  # noqa: E402
from ingest_tw_tfda import (  # noqa: E402  复用 TW 的成分映射机制
    WORK as TW_WORK,
    _split_salt_local,
    load_aliases,
    load_substance_map,
    match_component,
    nk,
)

XML_PATH = ROOT / "data" / "raw" / "hk_mo" / "hk_rpp_resource.xml"
WORK = ROOT / ".tmp" / "hk-ingest"
OUT_CSV = WORK / "hk_drugs_dryrun.csv"
DB_DEFAULT = ROOT / "data" / "drugs.db"
REAL_DB = DB_DEFAULT.resolve()
SOURCE_ID = "hk_dh"
SOURCE_NAME = "衞生署藥物辦公室（香港）註冊藥劑製品名單"
SOURCE_URL = ("https://data.gov.hk/en-data/dataset/"
              "hk-dh-dh_do-hk-dh-do-pharmaceutical-product")
LICENSE_NAME = "DATA.GOV.HK Terms and Conditions（free reuse, attribution required）"
LICENSE_URL = "https://data.gov.hk/en/terms-and-conditions"
TODAY = date.today().isoformat()
SCRIPT_VERSION = "2026-10-28"

# 香港惯用 BAN → 站内/INN 英文名（只做「碱基名」映射；盐/水合物交给 match_component）
HK_BAN_TO_INN = {
    "paracetamol": "acetaminophen",
    "frusemide": "furosemide",
    "lignocaine": "lidocaine",
    "adrenaline": "epinephrine",
    "noradrenaline": "norepinephrine",
    "amoxycillin": "amoxicillin",
    "oestradiol": "estradiol",
    "oestrone": "estrone",
    "ciclosporin": "cyclosporine",
    "sulphasalazine": "sulfasalazine",
    "glyceryl trinitrate": "nitroglycerin",
    "isosorbide dinitrate": "isosorbide dinitrate",
    "hyoscine": "scopolamine",
    "methylphenobarbitone": "methylphenobarbital",
    "phenobarbitone": "phenobarbital",
    "sodium cromoglycate": "cromolyn sodium",
    "levothyroxine sodium": "levothyroxine",
    "thyroxine sodium": "levothyroxine",
    "colecalciferol": "cholecalciferol",
    "ergocalciferol": "ergocalciferol",
    "retinol": "vitamin a",
    "thiamine": "thiamine",
    "pyridoxine": "pyridoxine",
    "cyanocobalamin": "cyanocobalamin",
    "folic acid": "folic acid",
    "potassium chloride": "potassium chloride",
    "sodium bicarbonate": "sodium bicarbonate",
}

OUT_FIELDS = ["product_id", "permit_no", "product_name", "holder", "n_ingredients",
              "matched_components", "unmapped_ingredients", "components", "status",
              "dosage_form", "release", "strength", "note"]


# ---------------------------------------------------------------- 解析
def parse_xml(path: Path) -> tuple[str, list[dict]]:
    """返回 (lastUpdate, [{permit, name, holder, ings:[...]}])。"""
    if not path.exists():
        raise SystemExit(f"找不到 {path}（先跑 HK 抓取/准备）")
    last_update = ""
    records: list[dict] = []
    for _ev, el in ET.iterparse(path, events=("end",)):
        tag = el.tag
        if tag == "lastUpdate":
            last_update = (el.text or "").strip()
        elif tag == "drug":
            name = (el.findtext("productName") or "").strip()
            holder = (el.findtext("regCertHolderName") or "").strip()
            permit = (el.findtext("permitNo") or "").strip()
            ings = [(x.text or "").strip() for x in el.findall("activeIngs/activeIng")
                    if (x.text or "").strip()]
            records.append({"permit": permit, "name": name, "holder": holder, "ings": ings})
            el.clear()
    return last_update, records


# ---------------------------------------------------------------- 成分映射
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
            rec.update(substance_id=sid, salt=salt, salt_code="",
                       status="matched", note="hk_ban_alias")
            return rec
    return rec


def build(records: list[dict], mapping: dict, aliases: dict, limit: int) -> tuple[list[dict], dict]:
    kept: list[dict] = []
    stats = {
        "source_id": SOURCE_ID, "rows_total": len(records), "scanned": 0,
        "kept": 0, "rejected": {"no_ingredient": 0, "no_matched_component": 0},
        "tokens_total": 0, "tokens_matched": 0, "tokens_match_db": 0,
        "tokens_tw_alias": 0, "tokens_ban_alias": 0, "tokens_unmatched": 0,
        "combo_rows": 0, "unmatched": {},
        "no_strength_rows": 0, "no_form_rows": 0, "no_status_rows": 0,
    }
    unmatched: dict[str, int] = {}
    for rec in records:
        stats["scanned"] += 1
        if limit and stats["scanned"] > limit:
            break
        ings = rec["ings"]
        if not ings:
            stats["rejected"]["no_ingredient"] += 1
            continue
        comps = []
        for ing in ings:
            c = match_ingredient(ing, mapping, aliases)
            stats["tokens_total"] += 1
            if c.get("substance_id"):
                stats["tokens_matched"] += 1
                note = c.get("note") or ""
                if note == "hk_ban_alias":
                    stats["tokens_ban_alias"] += 1
                elif "alias_table" in note:
                    stats["tokens_tw_alias"] += 1
                else:
                    stats["tokens_match_db"] += 1
            else:
                stats["tokens_unmatched"] += 1
                key = c.get("norm") or ing.upper()
                unmatched[key] = unmatched.get(key, 0) + 1
            comps.append(c)
        matched = [c for c in comps if c.get("substance_id")]
        if not matched:
            stats["rejected"]["no_matched_component"] += 1
            continue
        permit = rec["permit"]
        pid = permit if permit.upper().startswith("HK-") else "HK-" + permit
        note = "HK DrugList: 無規格/劑型/狀態（English only，DH register）"
        kept.append({
            "product_id": pid, "permit_no": permit, "product_name": rec["name"],
            "holder": rec["holder"], "n_ingredients": len(ings),
            "matched_components": len(matched),
            "unmapped_ingredients": "; ".join(ing for c, ing in zip(comps, ings)
                                              if not c.get("substance_id")),
            "components": "; ".join(
                f"{c['raw']} => {c['substance_id'] or '?'}"
                + (f" [{c['salt']}]" if c.get("salt") else "") for c in comps),
            "components_detail": comps, "note": note,
            "status": "unknown", "dosage_form": "unknown", "release": "none",
            "strength": "",
        })
        stats["kept"] += 1
        if len(matched) > 1:
            stats["combo_rows"] += 1
        stats["no_strength_rows"] += 1
        stats["no_form_rows"] += 1
        stats["no_status_rows"] += 1
    stats["unmatched"] = dict(sorted(unmatched.items(), key=lambda kv: -kv[1])[:30])
    stats["unmatched_distinct"] = len(unmatched)
    stats["token_coverage_pct"] = round(
        100 * stats["tokens_matched"] / max(1, stats["tokens_total"]), 1)
    stats["rows_with_all_matched"] = sum(
        1 for x in kept if not x["unmapped_ingredients"])
    stats["rows_with_any_unmapped"] = sum(
        1 for x in kept if x["unmapped_ingredients"])
    stats["products_dropped_no_component"] = stats["rejected"]["no_matched_component"]
    return kept, stats


# ---------------------------------------------------------------- 写库
def _db_path(arg: str) -> Path:
    p = Path(arg)
    return (p if p.is_absolute() else ROOT / p).resolve()


def _guard(db_path: Path, allow_real: bool) -> None:
    if db_path.resolve() == REAL_DB and not allow_real:
        raise SystemExit(f"拒绝写真实库 {REAL_DB}：请在副本验证；Lead 批准后加 --allow-real。")


def _require_hk_schema(db: sqlite3.Connection) -> None:
    row = db.execute("SELECT sql FROM sqlite_master WHERE name='product'").fetchone()
    if not row or "'HK'" not in (row[0] or ""):
        raise SystemExit("product.country CHECK 没有 'HK'：先跑 db/migrate_country_hk.py --apply --db <db> "
                         "（或 db/init_db.py 在 schema.sql 加 HK 后迁移）。")


def _ensure_source(db: sqlite3.Connection, last_update: str) -> None:
    if db.execute("SELECT 1 FROM source WHERE source_id=?", (SOURCE_ID,)).fetchone():
        db.execute("UPDATE source SET data_as_of=? WHERE source_id=? AND (data_as_of IS NULL OR data_as_of='')",
                   (last_update, SOURCE_ID))
        return
    db.execute(
        "INSERT INTO source (source_id, name, url, license, license_url, retrieved_at,"
        " data_as_of, data_as_of_note, notes) VALUES (?,?,?,?,?,?,?,?,?)",
        (SOURCE_ID, SOURCE_NAME, SOURCE_URL, LICENSE_NAME, LICENSE_URL, TODAY, last_update,
         "as when necessary（官方 XML lastUpdate）",
         "data.gov.hk 条款：免费商用/非商用浏览、下载、分发、复制，须注明来源并承认政府及原机构知识产权。"))


def write_db(db_path: Path, kept: list[dict], stats: dict, last_update: str,
             manifest_path: Path, allow_real: bool) -> dict:
    import time
    _guard(db_path, allow_real)
    t0 = time.perf_counter()
    db = sqlite3.connect(db_path, timeout=120)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    prev_keys: list[str] = []
    prev_variants: list[list[str]] = []
    if manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
            if old.get("source_id") == SOURCE_ID:
                prev_keys = list(old.get("created_name_keys") or [])
                prev_variants = [list(x) for x in (old.get("created_name_variants") or [])]
        except (OSError, ValueError):
            pass
    try:
        _require_hk_schema(db)
        _ensure_source(db, last_update)
        db.commit()   # source upsert 会开隐式事务；先提交，下面手动 BEGIN IMMEDIATE
        vidx: dict[tuple[str, str], str] = {}
        for r in db.execute(
                "SELECT variant_id, substance_id, COALESCE(salt_code,'') sc FROM variant"):
            vidx[(r["substance_id"], r["sc"])] = r["variant_id"]
        by_sid: dict[str, list[tuple[str, str]]] = {}
        for (sid, sc), vid in vidx.items():
            by_sid.setdefault(sid, []).append((vid, sc))
        salt_codes = {sc for (_sid, sc) in vidx if sc}

        def resolve_variant(sid: str, salt: str) -> str | None:
            salt_en = nk(salt)
            sc = ""
            if salt_en:
                try:
                    from normalize_salts import classify_salt
                    cl = classify_salt(salt_en)
                    sc = cl.salt_code if cl.kind == "salt" else ""
                except Exception:
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
                suffix = "-" + one
                if sid.endswith(suffix):
                    base = sid[:-len(suffix)]
                    bvid = vidx.get((base, one)) or vidx.get((base, ""))
                    if bvid:
                        return bvid
                    for v, _s in (by_sid.get(base) or []):
                        return v
            return None

        db.execute("BEGIN IMMEDIATE")
        removed = db.execute("DELETE FROM product WHERE source_id=?", (SOURCE_ID,)).rowcount
        created_keys: list[str] = []
        created_variants: list[list[str]] = []
        touched_keys: set[str] = set()
        product_ids: list[str] = []
        comp_count = 0
        drop_no_variant = 0
        run_id = f"{SOURCE_ID}-{TODAY}"
        for row in kept:
            resolved = []
            for c in row["components_detail"]:
                sid = c.get("substance_id")
                if not sid:
                    continue
                vid = resolve_variant(sid, c.get("salt") or "")
                if not vid:
                    drop_no_variant += 1
                    continue
                resolved.append({"ord": len(resolved), "vid": vid})
            if not resolved:
                continue
            pid = row["product_id"]
            db.execute(
                "INSERT OR REPLACE INTO product (product_id, country, dosage_form, form_base,"
                " route, release, pack, mah, approval_id, category, is_branded, status,"
                " status_date, source_id, source_url, retrieved_at, note)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, "HK", "unknown", None, None, "none", None, row["holder"] or None,
                 row["permit_no"] or None, None, 1, "unknown", None, SOURCE_ID,
                 SOURCE_URL, TODAY, row["note"][:300]))
            product_ids.append(pid)
            for item in resolved:
                db.execute(
                    "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                    " strength_value, strength_unit, per_volume_value, per_volume_unit)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (pid, item["ord"], item["vid"], None, None, None, None))
                comp_count += 1
            raw = (row["product_name"] or "").strip()
            if raw:
                nm = normalize(raw)
                key = nm.norm
                if key:
                    script = nm.script if nm.script in (
                        "latin", "cyrillic", "han", "kana", "hangul") else "latin"
                    cur = db.execute(
                        "INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                        " VALUES (?,?,?,?)", (key, key, key.replace(" ", ""), script))
                    if cur.rowcount:
                        created_keys.append(key)
                    touched_keys.add(key)
                    cur2 = db.execute(
                        "INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                        " VALUES (?,?,?)", (key, raw, SOURCE_ID))
                    if cur2.rowcount:
                        created_variants.append([key, raw])
                    db.execute(
                        "INSERT OR IGNORE INTO product_name (product_id, key_id, name_type,"
                        " is_primary) VALUES (?,?,?,?)", (pid, key, "trade", 1))
        db.execute(
            "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
            " rows_in, rows_kept, rows_rejected, status, note) VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, SOURCE_ID, TODAY, datetime.now().isoformat(timespec="seconds"),
             stats["rows_total"], len(product_ids),
             stats["rows_total"] - len(product_ids), "ok",
             json.dumps({"mode": "apply", "version": SCRIPT_VERSION,
                         "data_as_of": last_update,
                         "no_strength": True, "no_form": True, "no_status": True},
                        ensure_ascii=False)))
        db.commit()
        elapsed = round(time.perf_counter() - t0, 2)
        db_size = db_path.stat().st_size
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    all_keys = sorted(set(prev_keys) | set(created_keys))
    all_variants = sorted({tuple(x) for x in (prev_variants + created_variants)})
    res = {"db": str(db_path), "run_id": run_id, "products": len(product_ids),
           "components": comp_count, "components_no_variant": drop_no_variant,
           "removed_old_products": removed, "created_name_keys": len(created_keys),
           "created_name_variants": len(created_variants),
           "name_keys_touched": len(touched_keys), "elapsed_s": elapsed, "db_size": db_size}
    manifest = {"tool": "etl/ingest_hk_druglist.py", "version": SCRIPT_VERSION,
                "db": str(db_path), "source_id": SOURCE_ID, "created_at": TODAY,
                "data_as_of": last_update, "committed": True, "run_id": run_id,
                "product_ids": product_ids, "created_name_keys": all_keys,
                "created_name_variants": [list(x) for x in all_variants],
                "name_keys_touched": sorted(touched_keys),
                "stats": {"products": len(product_ids), "components": comp_count}}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n== HK WRITE-DB 完成 == {res}")
    print("撤销清单：", manifest_path)
    return res


def rollback_db(db_path: Path, manifest_path: Path, allow_real: bool) -> dict:
    _guard(db_path, allow_real)
    if not manifest_path.exists():
        raise SystemExit(f"找不到撤销清单: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    db = sqlite3.connect(db_path, timeout=120)
    db.execute("PRAGMA foreign_keys=ON")
    try:
        db.execute("BEGIN IMMEDIATE")
        n = db.execute("DELETE FROM product WHERE source_id=?", (SOURCE_ID,)).rowcount
        db.execute("DELETE FROM ingest_run WHERE run_id=?", (data.get("run_id") or "",))
        removed_keys = removed_variants = 0
        created_keys = set(data.get("created_name_keys") or [])
        for key, raw in (data.get("created_name_variants") or []):
            cur = db.execute("DELETE FROM name_variant WHERE key_id=? AND raw=?", (key, raw))
            removed_variants += cur.rowcount
        for key in sorted(created_keys):
            if not db.execute("SELECT 1 FROM product_name WHERE key_id=? LIMIT 1", (key,)).fetchone():
                cur = db.execute("DELETE FROM name_variant WHERE key_id=?", (key,))
                removed_variants += cur.rowcount
                db.execute("DELETE FROM name_key WHERE key_id=?", (key,))
                removed_keys += 1
        db.commit()
    finally:
        db.close()
    res = {"removed_products": n, "removed_name_keys": removed_keys,
           "removed_name_variants": removed_variants, "run_id": data.get("run_id"),
           "db": str(db_path)}
    print(f"\n== HK ROLLBACK 完成 == {res}")
    return res


# ---------------------------------------------------------------- 主流程
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HK DrugList → 名称/成分层入库（默认 dry-run）")
    ap.add_argument("--xml", default=None, help="XML 路径（默认 data/raw/hk_mo/hk_rpp_resource.xml）")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（0=全量）")
    ap.add_argument("--out", default=None, help="dry-run CSV 输出（默认 .tmp/hk-ingest/hk_drugs_dryrun.csv）")
    ap.add_argument("--apply", action="store_true", help="真正写库（需 --allow-real 才可写真实库）")
    ap.add_argument("--db", default=str(DB_DEFAULT), help="目标 DB（默认 data/drugs.db；演练用副本）")
    ap.add_argument("--allow-real", action="store_true", help="允许写真实库 data/drugs.db")
    ap.add_argument("--manifest", default=None, help="撤销清单路径（默认 .tmp/hk-ingest/hk_write_manifest.json）")
    ap.add_argument("--rollback", nargs="?", const="latest", default=None, help="按撤销清单回滚")
    args = ap.parse_args(argv)
    WORK.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.manifest) if args.manifest else WORK / "hk_write_manifest.json"
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    if args.rollback:
        m = Path(args.rollback) if args.rollback != "latest" else manifest_path
        if not m.is_absolute():
            m = ROOT / m
        rollback_db(_db_path(args.db), m, args.allow_real)
        return 0

    xml_path = Path(args.xml) if args.xml else XML_PATH
    if not xml_path.is_absolute():
        xml_path = ROOT / xml_path
    last_update, records = parse_xml(xml_path)
    print(f"输入：{xml_path.relative_to(ROOT)}  {len(records):,} 条；lastUpdate={last_update or '?'}")
    mapping, map_source = load_substance_map()
    aliases = load_aliases()
    print(f"成分词典：{len(mapping):,} 个 (名,盐) 组合（来源 {map_source}）；"
          f"TW 别名表 {len(aliases):,}；HK BAN 别名 {len(HK_BAN_TO_INN)} 条")
    kept, stats = build(records, mapping, aliases, args.limit)
    stats.update({"last_update": last_update, "xml": str(xml_path.relative_to(ROOT)),
                  "today": TODAY})
    out_path = Path(args.out) if args.out else OUT_CSV
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(kept)
    stats_path = WORK / "hk_dryrun-stats.json"
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    unmatched_path = WORK / "hk_unmatched.csv"
    with unmatched_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ingredient", "count"])
        w.writerows((k, v) for k, v in sorted(stats["unmatched"].items(), key=lambda kv: -kv[1]))

    print(f"\n{'APPLY 计划' if args.apply else 'DRY RUN（未写 DB）'}")
    print(f"  扫描 {stats['scanned']:,} 条；输出 {stats['kept']:,} products → "
          f"{out_path.relative_to(ROOT)}")
    print(f"  丢弃：{stats['rejected']}；成分 token {stats['tokens_matched']}/{stats['tokens_total']} "
          f"({stats['token_coverage_pct']}%，DB {stats['tokens_match_db']} / TW别名 {stats['tokens_tw_alias']}"
          f" / HK-BAN {stats['tokens_ban_alias']})；未匹配 distinct {stats['unmatched_distinct']}")
    print(f"  复方 {stats['combo_rows']} 行；无规格/剂型/状态行 = {stats['no_strength_rows']}/"
          f"{stats['no_form_rows']}/{stats['no_status_rows']}（全部，页面需明示）")
    print(f"  统计：{stats_path.relative_to(ROOT)}；未匹配清单：{unmatched_path.relative_to(ROOT)}")

    if args.apply:
        db_path = _db_path(args.db)
        print(f"\n写库目标：{db_path}")
        res = write_db(db_path, kept, stats, last_update, manifest_path, args.allow_real)
        stats["write_db"] = res
        stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    print("下一步：db/migrate_country_hk.py --apply --db <副本> → --apply --db <副本> → check_data/quick_check；"
          "真实库 apply 待下一谷段批准（--allow-real）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
