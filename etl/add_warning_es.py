"""dose_warning 西语补全（task-39）：把 41 条种子的 `title_es` / `body_es` 写进库。

译文唯一真相源在 `data/seed_warnings.py`（`ES_TRANSLATIONS` → 每条 WARNINGS 的
title_es/body_es；重建种子时不会丢）。本脚本只做一件事：

    UPDATE dose_warning SET title_es=?, body_es=?, updated_at=?
     WHERE warning_id=?    —— 且只对「与库内现值不同」的行

**只更新 title_es / body_es（+ updated_at）**，不改 status、不改其他任何列；
事务提交；幂等；apply 前把旧值备份成 CSV，rollback 只还原「仍等于 apply 后值」的行，
避免覆盖别人后来的手工修改。

翻译口径（见 reports/warn-es.md）：
  · 医学通用西语（西班牙/墨西哥都能读）；保留数字、单位、成分名与 INN；
  · 不新增英文/中文段没有的医学断言，不出现用药建议（不给「换几片/等效剂量」）；
  · 释放机制用 liberación inmediata / prolongada；盐型用 forma salina；
    强度基准用 base / sal；治疗窗用 índice terapéutico estrecho；不可互换 non intercambiables。

CLI：
    python etl/add_warning_es.py --dry-run                  # 默认：只报告将改多少行
    python etl/add_warning_es.py --apply --db PATH          # 写 title_es/body_es
    python etl/add_warning_es.py --rollback --db PATH       # 用备份还原
    python etl/add_warning_es.py --verify --db PATH         # 打印 es 覆盖率

真实库 data/drugs.db 上的 --apply/--rollback 必须加 --confirm-real-db；
本轮只在 .tmp/warn-es/test.db 副本上验证，真实库由 Lead apply。
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data"))
from seed_warnings import WARNINGS  # noqa: E402

DEFAULT_DB = ROOT / "data" / "drugs.db"
WORK = ROOT / ".tmp" / "warn-es"
BACKUP_DIR = WORK / "backups"
NULL_SENTINEL = "\\N"

MAX_TITLE = 200
MAX_BODY = 900
BANNED = ("吃几片", "粒", "片/次", "take .* tablets", "dosis recomendada")
# 术语一致性词表：出现即说明用了统一口径（便于报告/自检，不强制全命中）
GLOSSARY = ("liberación", "forma salina", "índice terapéutico", "no son intercambiables",
            "miligramo por miligramo", "base")


def _num_tokens(text: str) -> list[str]:
    """提取数字 token 并把小数点统一成 '点'，用于中英/西语数字一致性检查。"""
    return [t.replace(",", ".") for t in re.findall(r"\d+(?:[.,]\d+)?", text or "")]


def validate_translations() -> list[str]:
    """种子自检：41 条都有 es、长度合理、数字与英文段一致、无禁用措辞。"""
    errors: list[str] = []
    ids = [w["warning_id"] for w in WARNINGS]
    if len(ids) != len(set(ids)):
        errors.append("warning_id 重复")
    for w in WARNINGS:
        wid = w["warning_id"]
        tes, bes = w.get("title_es"), w.get("body_es")
        if not (tes or "").strip():
            errors.append(f"{wid}: 缺 title_es")
            continue
        if not (bes or "").strip():
            errors.append(f"{wid}: 缺 body_es")
            continue
        if len(tes) > MAX_TITLE:
            errors.append(f"{wid}: title_es 过长（{len(tes)}）")
        if len(bes) > MAX_BODY:
            errors.append(f"{wid}: body_es 过长（{len(bes)}）")
        en_nums = _num_tokens(w["body_en"]) + _num_tokens(w["title_en"])
        es_nums = _num_tokens(bes) + _num_tokens(tes)
        if sorted(en_nums) != sorted(es_nums):
            errors.append(f"{wid}: 数字不一致 en={en_nums} es={es_nums}")
        if any(b in (tes + bes) for b in BANNED):
            errors.append(f"{wid}: 含禁用措辞")
        if "  " in tes or "  " in bes:
            errors.append(f"{wid}: 连续空格")
    return errors


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(db_path: Path, write: bool) -> sqlite3.Connection:
    if write:
        return sqlite3.connect(db_path, timeout=120)
    return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=120)


def _guard_target(db_path: Path, action: str, confirmed: bool) -> None:
    try:
        is_real = db_path.resolve() == DEFAULT_DB.resolve()
    except OSError:
        is_real = False
    if is_real and action in ("apply", "rollback") and not confirmed:
        raise SystemExit(
            f"拒绝在真实库 {db_path} 上执行 --{action}：本轮只做副本验证。\n"
            "确认要写时加 --confirm-real-db，并先备份 data/drugs.db。"
        )


def plan(db: sqlite3.Connection) -> tuple[list[dict], list[str]]:
    """→ (需要更新的行, 库里不存在的 warning_id)。"""
    es = {w["warning_id"]: (w["title_es"], w["body_es"])
          for w in WARNINGS if w.get("title_es")}
    current = {r[0]: (r[1], r[2]) for r in db.execute(
        "SELECT warning_id, title_es, body_es FROM dose_warning")}
    rows, missing = [], []
    for wid in [w["warning_id"] for w in WARNINGS]:
        if wid not in current:
            missing.append(wid)
            continue
        tes, bes = es[wid]
        cur_tes, cur_bes = current[wid]
        if (cur_tes or "") != tes or (cur_bes or "") != bes:
            rows.append({"warning_id": wid, "title_es_before": cur_tes,
                         "body_es_before": cur_bes, "title_es_after": tes,
                         "body_es_after": bes})
    return rows, missing


def _write_backup(rows: list[dict]) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKUP_DIR / f"rollback_warning_es_{stamp}.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["warning_id", "title_es_before", "body_es_before",
                    "title_es_after", "body_es_after"])
        for r in rows:
            w.writerow([r["warning_id"],
                        NULL_SENTINEL if r["title_es_before"] is None else r["title_es_before"],
                        NULL_SENTINEL if r["body_es_before"] is None else r["body_es_before"],
                        r["title_es_after"], r["body_es_after"]])
    (BACKUP_DIR / "rollback_warning_es_latest.csv").write_text(
        path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _csv_value(value: str) -> str | None:
    return None if value == NULL_SENTINEL else value


def cmd_dry_run(args: argparse.Namespace) -> int:
    db = _connect(args.db, write=False)
    try:
        rows, missing = plan(db)
        total = db.execute("SELECT COUNT(*) FROM dose_warning").fetchone()[0]
        have_es = db.execute(
            "SELECT COUNT(*) FROM dose_warning WHERE title_es IS NOT NULL AND title_es<>''"
        ).fetchone()[0]
        print("=== add_warning_es --dry-run ===")
        print(f"种子条数 / 库内条数 : {len(WARNINGS)} / {total}")
        print(f"库内已有 title_es   : {have_es}")
        print(f"本次将更新          : {len(rows)} 行")
        print(f"库内缺失（先 seed） : {len(missing)} {missing or ''}")
        for r in rows[:5]:
            print(f"  · {r['warning_id']}: {r['title_es_after'][:60]}")
        if len(rows) > 5:
            print(f"  … 其余 {len(rows) - 5} 行")
        return 0
    finally:
        db.close()


def cmd_apply(args: argparse.Namespace) -> int:
    db = _connect(args.db, write=True)
    try:
        rows, missing = plan(db)
        print(f"=== add_warning_es --apply ===\n计划更新 {len(rows)} 行；缺失 {len(missing)} 行")
        if missing:
            print(f"  库内缺少这些 warning_id（先跑 seed_warnings --apply）：{missing}",
                  file=sys.stderr)
        if not rows:
            print("无需更新（幂等）。")
            return 0
        backup = _write_backup(rows)
        print(f"回滚备份 : {backup}")
        now = _now()
        with db:
            db.executemany(
                "UPDATE dose_warning SET title_es=?, body_es=?, updated_at=?"
                " WHERE warning_id=?",
                [(r["title_es_after"], r["body_es_after"], now, r["warning_id"])
                 for r in rows])
        print(f"已更新 {len(rows)} 行 title_es/body_es。")
        return 0
    finally:
        db.close()


def cmd_rollback(args: argparse.Namespace) -> int:
    path = args.rollback_file or (BACKUP_DIR / "rollback_warning_es_latest.csv")
    if not Path(path).exists():
        print(f"找不到备份 CSV：{path}", file=sys.stderr)
        return 1
    with Path(path).open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    db = _connect(args.db, write=True)
    try:
        current = {r[0]: (r[1] or "", r[2] or "") for r in db.execute(
            "SELECT warning_id, title_es, body_es FROM dose_warning")}
        todo, skipped = [], 0
        for r in rows:
            wid = r["warning_id"]
            if current.get(wid) == (r["title_es_after"], r["body_es_after"]):
                todo.append((_csv_value(r["title_es_before"]),
                             _csv_value(r["body_es_before"]), wid))
            else:
                skipped += 1
        with db:
            db.executemany(
                "UPDATE dose_warning SET title_es=?, body_es=? WHERE warning_id=?", todo)
        print(f"=== add_warning_es --rollback ===\n备份 {path}\n"
              f"还原 {len(todo)} 行（跳过已变更 {skipped}）")
        return 0
    finally:
        db.close()


def cmd_verify(args: argparse.Namespace) -> int:
    db = _connect(args.db, write=False)
    try:
        print("=== add_warning_es --verify ===")
        total = db.execute("SELECT COUNT(*) FROM dose_warning").fetchone()[0]
        have = db.execute(
            "SELECT COUNT(*) FROM dose_warning WHERE title_es IS NOT NULL AND title_es<>'' "
            "AND body_es IS NOT NULL AND body_es<>''").fetchone()[0]
        print(f"  title_es+body_es 非空 : {have}/{total}")
        for status, n, es in db.execute(
                "SELECT status, COUNT(*), SUM(CASE WHEN title_es IS NOT NULL "
                "AND title_es<>'' THEN 1 ELSE 0 END) FROM dose_warning GROUP BY status"):
            print(f"  {status:10} {n:>3} 行，其中西语 {es}")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="dose_warning 西语补全（title_es/body_es）")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只报告（默认）")
    mode.add_argument("--apply", action="store_true", help="写 title_es/body_es")
    mode.add_argument("--rollback", action="store_true", help="用备份还原")
    mode.add_argument("--verify", action="store_true", help="打印 es 覆盖率")
    ap.add_argument("--rollback-file", type=Path, default=None)
    ap.add_argument("--confirm-real-db", action="store_true")
    args = ap.parse_args(argv)

    errors = validate_translations()
    if errors:
        print("译文自检失败：", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    action = ("verify" if args.verify else "rollback" if args.rollback
              else "apply" if args.apply else "dry")
    if action in ("apply", "rollback"):
        _guard_target(args.db, action, args.confirm_real_db)
    if action != "dry" and not args.db.exists():
        print(f"数据库不存在：{args.db}", file=sys.stderr)
        return 1
    if action == "verify":
        return cmd_verify(args)
    if action == "rollback":
        return cmd_rollback(args)
    if action == "apply":
        return cmd_apply(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
