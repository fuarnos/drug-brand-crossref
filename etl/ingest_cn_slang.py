#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把中文俗名候选（Tier B）增量写入 `drug_term`（默认 dry-run，不写生产库）。

输入：`data/cn_slang_candidates.csv`（task-23 产物；1,108 条 Tier B，含 documented/community）
输出：drug_term 新行 + 新增 source 行；撤销清单 JSON（默认 `.tmp/cn-slang-ingest/undo_*.json`）

字段对齐 `db/schema.sql` 的 drug_term：
    term, term_norm, term_type(street/folk/class/brand_generic), country,
    label_zh, label_en, meaning_en, meaning_zh, substance_id, examples(JSON),
    confidence(user/community/documented), source_id, source_url, note, created_at

入库规则
--------
1. 跳过 `substance_id LIKE 'cn-%'` 的行（等成分合并后再另跑，避免引用将被删除的 cn-*）；
2. 跳过与 `product_name` / `nickname` / 现有 `drug_term` 重复的术语（按归一化键比较）；
3. 批内按 (term_norm, term_type, substance_id) 去重；
4. `term_type` 沿用候选 CSV 的 folk/class/street；`country='CN'`；
5. confidence 重算：候选来源族 ≥2 → documented，1 → community（与 CSV 不一致时以重算为准，
   并在报告里列出差异数）；
6. 全部通过 Tier B 的候选进 `drug_term`，**不新增 nickname**。

用法
----
    python etl/ingest_cn_slang.py                    # dry-run（只读，打印计划）
    python etl/ingest_cn_slang.py --db X.db --apply  # 事务写库 + 撤销清单
    python etl/ingest_cn_slang.py --db X.db --rollback [manifest]

注意：真实库由 Lead 审核后 apply；本轮验证只在 `.tmp/cn-slang-ingest/` 的 DB 副本上做。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
CSV_DEFAULT = ROOT / "data" / "cn_slang_candidates.csv"
DB_DEFAULT = ROOT / "data" / "drugs.db"
MANIFEST_DIR = ROOT / ".tmp" / "cn-slang-ingest"

# 新增 source 行（与候选 CSV 的 platform/license 对应）
SOURCES = {
    "wikipedia_zh": dict(
        name="Chinese Wikipedia (中文维基百科：重定向/别名)",
        url="https://zh.wikipedia.org/",
        license="CC BY-SA 4.0",
        license_url="https://creativecommons.org/licenses/by-sa/4.0/",
        notes="只存「叫法」这一事实与条目链接，不转载正文；需在站点署名并链回原条目。",
    ),
    "wikidata": dict(
        name="Wikidata (中文标签/别名)",
        url="https://www.wikidata.org/",
        license="CC0 1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        notes="Wikidata 中文标签/别名，CC0；仅存短名与实体检索链接。",
    ),
    "alihealth_cn": dict(
        name="公开健康平台页面整理（阿里健康等）",
        url="https://www.alihealth.cn/",
        license="待确认（公开健康平台页面；仅存短名+链接）",
        license_url=None,
        notes="许可待确认；只存叫法事实与平台链接，不转载正文。",
    ),
    "community_web_cn": dict(
        name="中文社区/搜索抓取（维基/必应/头条/小红书/知乎等）",
        url="data/raw/cn_slang/",
        license="用户/社区公开内容（仅存叫法事实+原链接）",
        license_url=None,
        notes="抓取快照只保留 term/url/title/snippet 短事实；版权归原作者/平台，站外只用叫法并链回。",
    ),
}
# 候选 CSV 的 platform → 来源族
PLATFORM_FAMILY = {
    "wikipedia_zh": "wikipedia_zh",
    "wikidata": "wikidata",
    "alihealth_cn": "alihealth_cn",
    "wiki": "wikipedia_zh",
    "bing": "community_web_cn",
    "toutiao": "community_web_cn",
    "xiaohongshu": "community_web_cn",
    "zhihu": "community_web_cn",
    "weibo": "community_web_cn",
    "tieba": "community_web_cn",
}
PRIMARY_PRIORITY = ["wikipedia_zh", "wikidata", "alihealth_cn", "community_web_cn"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm_key(s: str) -> str:
    """与候选 CSV 的 normalized 对齐：NFKC、小写、去空格标点。"""
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[\s\u3000]+", "", s)
    s = re.sub(r"[·•・\-—_/\\.,;:!?()\[\]{}'\"’‘“”《》<>]+", "", s)
    return s


def connect(db_path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True, timeout=60)
    else:
        con = sqlite3.connect(str(db_path), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                       (name,)).fetchone() is not None


# ---------------------------------------------------------------------------
# 读取候选 + DB 上下文
# ---------------------------------------------------------------------------
def load_candidates(csv_path: Path) -> list[dict]:
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
    for r in rows:
        for k in r:
            r[k] = (r.get(k) or "").strip()
    return rows


def db_context(con: sqlite3.Connection) -> dict:
    cur = con.cursor()
    substr = {sid: (zh or "", en or "") for sid, en, zh in
              cur.execute("SELECT substance_id, inn_en, inn_zh FROM substance")}
    # 现有 drug_term 键（NULL substance_id 视为 ''）
    existing_dt: set[tuple[str, str, str]] = set()
    existing_dt_norm: set[str] = set()
    for tn, tt, sid in cur.execute(
            "SELECT term_norm, term_type, COALESCE(substance_id,'') FROM drug_term"):
        existing_dt.add((norm_key(tn), tt, sid))
        existing_dt_norm.add(norm_key(tn))
    # nickname
    nickname_norm: set[str] = set()
    for (a,) in cur.execute("SELECT alias_norm FROM nickname"):
        nickname_norm.add(norm_key(a))
    # product_name（含 name_key 全部语言，按归一化键比较）
    pn_norm: set[str] = set()
    for (n,) in cur.execute("SELECT DISTINCT norm FROM name_key"):
        k = norm_key(n)
        if k:
            pn_norm.add(k)
    return dict(substr=substr, existing_dt=existing_dt,
                existing_dt_norm=existing_dt_norm, nickname_norm=nickname_norm,
                pn_norm=pn_norm)


def source_families(csv_row: dict) -> set[str]:
    fams = set()
    for tok in (csv_row.get("platform") or "").split(";"):
        tok = tok.strip()
        if not tok:
            continue
        fams.add(PLATFORM_FAMILY.get(tok, "community_web_cn"))
    return fams or {"community_web_cn"}


def pick_source(fams: set[str]) -> str:
    for p in PRIMARY_PRIORITY:
        if p in fams:
            return p
    return "community_web_cn"


def build_plan(con: sqlite3.Connection, rows: list[dict]) -> dict:
    ctx = db_context(con)
    accepted: list[dict] = []
    skipped: Counter = Counter()
    skipped_samples: dict[str, list[str]] = {}
    conf_mismatch = 0
    seen: set[tuple[str, str, str]] = set()
    for r in rows:
        term = r.get("term") or ""
        tkey = norm_key(term)
        sid = r.get("substance_id") or ""
        ttype = r.get("term_type") or "folk"
        if not term or not tkey:
            skipped["术语为空"] += 1
            continue
        if ttype not in ("street", "folk", "class", "brand_generic"):
            skipped["term_type 非法"] += 1
            continue
        if sid.startswith("cn-"):
            skipped["substance 为 cn-*（待成分合并后另跑）"] += 1
            continue
        if (tkey, ttype, sid) in ctx["existing_dt"]:
            skipped["drug_term 已存在（幂等跳过）"] += 1
            continue
        if tkey in ctx["nickname_norm"]:
            skipped["与 nickname 重复"] += 1
            continue
        if tkey in ctx["pn_norm"]:
            skipped["与 product_name 重复"] += 1
            continue
        batch_key = (tkey, ttype, sid)
        if batch_key in seen:
            skipped["批内重复"] += 1
            continue
        seen.add(batch_key)
        fams = source_families(r)
        confidence = "documented" if len(fams) >= 2 else "community"
        if confidence != r.get("confidence"):
            conf_mismatch += 1
        label_zh = r.get("label_zh") or ""
        label_en = ""
        if sid and sid in ctx["substr"]:
            zh2, en2 = ctx["substr"][sid]
            label_zh = label_zh or zh2 or en2
            label_en = en2 or ""
        examples = [x for x in (r.get("examples") or "").split(";") if x]
        if sid:
            meaning_zh = (f"中文俗名/别名，指向 {label_zh or sid}（{sid}）；"
                          f"来源：{r.get('platform') or ''}。")
        elif ttype == "class":
            meaning_zh = (f"中文类别叫法（举例成分：{'、'.join(examples) or '未定'}）；"
                          f"不是单一成分，检索时给出候选集。")
        else:
            meaning_zh = "中文别名/叫法；成分未能唯一确定（歧义或本库无产品），检索时按歧义展示。"
        accepted.append(dict(
            term=term, term_norm=tkey, term_type=ttype, country="CN",
            label_zh=label_zh or None, label_en=label_en or None,
            meaning_en=None, meaning_zh=meaning_zh,
            substance_id=sid or None,
            examples=json.dumps(examples, ensure_ascii=False) if examples else None,
            confidence=confidence,
            source_id=pick_source(fams),
            source_url=r.get("source_url") or None,
            note=(f"候选来源：{r.get('platform') or ''}；{r.get('snippet') or ''}；"
                  f"许可：{r.get('license') or ''}")[:500],
            created_at=date.today().isoformat(),
        ))
    kind_dist = Counter(a["term_type"] for a in accepted)
    src_dist = Counter(a["source_id"] for a in accepted)
    conf_dist = Counter(a["confidence"] for a in accepted)
    return dict(rows=rows, accepted=accepted, skipped=skipped,
                skipped_samples=skipped_samples, conf_mismatch=conf_mismatch,
                kind=kind_dist, source=src_dist, confidence=conf_dist)


def print_plan(plan: dict) -> None:
    print(f"候选 CSV：{len(plan['rows'])} 行（Tier B）")
    print(f"可入库：{len(plan['accepted'])} 行；跳过：{sum(plan['skipped'].values())} 行")
    for k, v in plan["skipped"].most_common():
        print(f"  跳过 {k}: {v}")
    print("kind 分布:", dict(plan["kind"]))
    print("source 分布:", dict(plan["source"]))
    print("confidence 分布:", dict(plan["confidence"]),
          f"（与 CSV 重算不一致 {plan['conf_mismatch']} 行，以来源族重算为准）")
    print("\n样例（前 20）:")
    for a in plan["accepted"][:20]:
        print(f"  {a['term']:<12} {a['term_type']:<6} {a['substance_id'] or '-':<22} "
              f"{a['source_id']:<16} {a['confidence']}")


# ---------------------------------------------------------------------------
# apply / rollback
# ---------------------------------------------------------------------------
def ensure_sources(con: sqlite3.Connection) -> tuple[list[str], dict[str, dict]]:
    """插入/更新本脚本用到的 source 行。

    返回 (新建的 source_id 列表, 原有 source 行快照)，供回滚精确恢复。
    """
    created = []
    before: dict[str, dict] = {}
    today = date.today().isoformat()
    for sid, meta in SOURCES.items():
        row = con.execute("SELECT * FROM source WHERE source_id=?", (sid,)).fetchone()
        if row is not None:
            before[sid] = dict(row)
        else:
            created.append(sid)
        con.execute(
            """INSERT INTO source (source_id, name, url, license, license_url,
                                   retrieved_at, notes)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT (source_id) DO UPDATE SET
                   name=excluded.name, url=excluded.url, license=excluded.license,
                   license_url=excluded.license_url, retrieved_at=excluded.retrieved_at,
                   notes=excluded.notes""",
            (sid, meta["name"], meta["url"], meta["license"], meta["license_url"],
             today, meta["notes"]))
    return created, before


def apply_plan(con: sqlite3.Connection, plan: dict, db_path: Path, csv_path: Path,
               manifest_path: Path) -> int:
    accepted = plan["accepted"]
    if not accepted:
        print("没有可入库的行（幂等或全部跳过），未写库。")
        return 0
    manifest = dict(tool="etl/ingest_cn_slang.py", db=str(db_path.resolve()),
                    csv=str(csv_path.resolve()),
                    csv_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                    created_at=utc_now(), committed=False, inserted=[],
                    sources_created=[], sources_before={})
    try:
        con.execute("BEGIN IMMEDIATE")
        created_sources, sources_before = ensure_sources(con)
        manifest["sources_created"] = created_sources
        manifest["sources_before"] = sources_before
        for a in accepted:
            cur = con.execute(
                """INSERT INTO drug_term
                   (term, term_norm, term_type, country, label_zh, label_en,
                    meaning_en, meaning_zh, substance_id, examples, confidence,
                    source_id, source_url, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (a["term"], a["term_norm"], a["term_type"], a["country"],
                 a["label_zh"], a["label_en"], a["meaning_en"], a["meaning_zh"],
                 a["substance_id"], a["examples"], a["confidence"], a["source_id"],
                 a["source_url"], a["note"], a["created_at"]))
            manifest["inserted"].append(dict(term_id=cur.lastrowid,
                                             term=a["term"], term_norm=a["term_norm"],
                                             term_type=a["term_type"],
                                             substance_id=a["substance_id"]))
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        con.commit()
        manifest["committed"] = True
        manifest["committed_at"] = utc_now()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    except Exception:
        con.rollback()
        print("!! 写库失败，已回滚事务", file=sys.stderr)
        raise
    print(f"已写入 drug_term {len(accepted)} 行；撤销清单: {manifest_path}")
    print(f"本次新建 source: {manifest['sources_created'] or '无'}")
    return len(accepted)


def rollback(con: sqlite3.Connection, manifest_path: Path) -> None:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not data.get("committed"):
        raise SystemExit(f"清单 {manifest_path} 未标记 committed，拒绝回滚")
    if data.get("rolled_back_at"):
        print(f"清单已于 {data['rolled_back_at']} 回滚过，继续执行幂等回填")
    removed = 0
    missing = 0
    con.execute("BEGIN IMMEDIATE")
    try:
        for rec in reversed(data.get("inserted", [])):
            cur = con.execute("DELETE FROM drug_term WHERE term_id=? AND term=? AND term_type=?",
                              (rec["term_id"], rec["term"], rec["term_type"]))
            if cur.rowcount:
                removed += 1
            else:
                missing += 1
        for sid in data.get("sources_created", []):
            refs = con.execute("SELECT COUNT(*) FROM drug_term WHERE source_id=?",
                               (sid,)).fetchone()[0]
            if refs == 0:
                con.execute("DELETE FROM source WHERE source_id=?", (sid,))
        # 恢复被 upsert 覆盖的原有 source 行
        for sid, row in (data.get("sources_before") or {}).items():
            cols = ",".join(row.keys())
            ph = ",".join("?" * len(row))
            con.execute(f"INSERT OR REPLACE INTO source ({cols}) VALUES ({ph})",
                        tuple(row.values()))
        data["rolled_back_at"] = utc_now()
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        con.commit()
    except Exception:
        con.rollback()
        raise
    print(f"已删除本次写入的 drug_term {removed} 行；"
          f"已不存在 {missing} 行（此前已回滚/被清理）")
    if missing and not removed:
        print("（幂等：本次没有需要删除的行）")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="把中文俗名候选写入 drug_term（默认 dry-run，不写库）。")
    ap.add_argument("--csv", default=str(CSV_DEFAULT), help="候选 CSV")
    ap.add_argument("--db", default=str(DB_DEFAULT), help="SQLite 数据库")
    ap.add_argument("--apply", action="store_true", help="事务写库 + 撤销清单")
    ap.add_argument("--dry-run", action="store_true", help="只出计划（默认）")
    ap.add_argument("--rollback", nargs="?", const="latest", default=None,
                    help="回滚：可给清单路径，缺省取 .tmp/cn-slang-ingest 最新清单")
    ap.add_argument("--manifest", default=None, help="撤销清单路径")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"数据库不存在: {db_path}")
    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"候选 CSV 不存在: {csv_path}")
    rows = load_candidates(csv_path)

    if args.rollback is not None:
        con = connect(db_path, readonly=False)
        try:
            if args.rollback == "latest":
                cands = sorted(MANIFEST_DIR.glob("undo_*.json"),
                               key=lambda p: p.stat().st_mtime)
                if not cands:
                    raise SystemExit(f"{MANIFEST_DIR} 下没有 undo_*.json")
                mp = cands[-1]
            else:
                mp = Path(args.rollback)
            print(f"回滚清单: {mp}")
            rollback(con, mp)
        finally:
            con.close()
        return

    con = connect(db_path, readonly=not args.apply)
    try:
        plan = build_plan(con, rows)
        print(f"DB: {db_path}  ({'只读' if not args.apply else '读写'})")
        print(f"CSV: {csv_path}")
        print()
        print_plan(plan)
        if args.apply:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            manifest = Path(args.manifest) if args.manifest else (
                MANIFEST_DIR / f"undo_{stamp}.json")
            print()
            apply_plan(con, plan, db_path, csv_path, manifest)
        else:
            print("\n(dry-run，未写库。Lead 审核后加 --apply 执行)")
    finally:
        con.close()


if __name__ == "__main__":
    main()
