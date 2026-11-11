"""`product.country` CHECK 迁移的回归测试（task-56：一次加 FR / LV / JP / KR）。

覆盖：
1. `db/schema.sql` 的枚举含四国、无重复、EU 不进 country；
2. 全新库按 schema 建出来后枚举正确，且**第二次 build 不重建**（幂等）；
3. 老库（枚举仍是 10 国）能就地升级，数据行原样保留；
4. `db/migrate_country_check.py`：dry-run 不写库 → apply 生效 → 再 apply 幂等 → rollback 回旧枚举；
5. 回滚护栏：库里有 FR/LV/JP/KR 行时拒绝回滚；
6. 写真实库的护栏：不带 `--allow-real` 时 `--apply` 在建连之前就被拒绝。

只读 `data/drugs.db`（护栏测试只跑子进程、不落盘）；其余测试文件都建在 `.tmp/tests-country-check/`。
（受限沙箱里「新建子目录 + 在其中建 SQLite 文件」会 OperationalError，所以这里是平铺文件。）

运行：& $py -m unittest tests.test_country_check_migration -v
"""

from __future__ import annotations

import contextlib
import io
import sqlite3
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "db"))
import init_db  # noqa: E402
import migrate_country_check as mig  # noqa: E402

SCHEMA = ROOT / "db" / "schema.sql"
WORK = ROOT / ".tmp" / "tests-country-check"
OLD_MARKETS = ["US", "GB", "CN", "ES", "MX", "AU", "CA", "TW", "HK", "SG"]
NEW_MARKETS = ["FR", "LV", "JP", "KR"]

_CREATED: list[Path] = []


def tmpfile(name: str, ext: str = ".db") -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    p = WORK / f"{name}-{uuid.uuid4().hex[:8]}{ext}"
    _CREATED.append(p)
    return p


def cleanup_created() -> None:
    for p in _CREATED:
        for cand in (p, Path(str(p) + "-journal"), Path(str(p) + "-wal")):
            with contextlib.suppress(OSError):
                if cand.exists():
                    cand.unlink()
    _CREATED.clear()


def schema_text() -> str:
    return SCHEMA.read_text(encoding="utf-8")


def old_schema_text() -> str:
    """把 schema.sql 的 country 枚举退回 10 国，用来模拟「老库」。"""
    repl = "country TEXT NULL CHECK (country IS NULL OR country IN (%s))" % (
        "'" + "', '".join(OLD_MARKETS) + "'")
    text, n = mig.CHECK_RE.subn(repl, schema_text(), count=1)
    assert n == 1, "schema.sql 里找不到 country CHECK，无法构造老库"
    return text


def seed_rows(con: sqlite3.Connection, countries: list[str]) -> None:
    """插一个 source + 若干 product 行（满足外键；迁移后必须原样保留）。"""
    con.execute(
        "INSERT INTO source (source_id, name, url, license, retrieved_at) "
        "VALUES ('manual_seed','手工种子','https://example.invalid','CC0','2026-01-01')")
    for i, c in enumerate(countries):
        con.execute(
            "INSERT INTO product (product_id, country, dosage_form, release, is_branded,"
            " status, source_id, retrieved_at) VALUES (?,?,?,?,?,?,?,?)",
            (f"T-{c}-{i}", c, "tablet", "none", 1, "active", "manual_seed", "2026-01-01"))
    con.commit()


def build_silently(db: Path) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        con = init_db.build(db)
    con.close()
    return buf.getvalue()


def product_enum(db: Path) -> list[str]:
    con = sqlite3.connect(db)
    try:
        ddl = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='product'").fetchone()[0]
        return mig.enum_of(ddl)
    finally:
        con.close()


class TestSchemaEnum(unittest.TestCase):
    def test_schema_has_four_new_markets(self):
        enum = mig.enum_of(schema_text())
        self.assertEqual(len(enum), len(set(enum)), f"枚举有重复：{enum}")
        for m in OLD_MARKETS + NEW_MARKETS:
            self.assertIn(m, enum, f"schema.sql 的 country 枚举缺 {m}")
        self.assertEqual(len(enum), len(OLD_MARKETS) + len(NEW_MARKETS))

    def test_eu_not_in_country_enum(self):
        """EU 是区域层（product.region），不能塞进 country。"""
        self.assertNotIn("EU", mig.enum_of(schema_text()))

    def test_target_markets_matches_schema(self):
        self.assertEqual(mig.target_markets(), mig.enum_of(schema_text()))


class TestInitDb(unittest.TestCase):
    def test_fresh_db_and_idempotent_rebuild(self):
        db = tmpfile("fresh")
        first = build_silently(db)
        self.assertNotIn("迁移 product 表", first, "全新库不该触发迁移")
        enum = product_enum(db)
        for m in NEW_MARKETS:
            self.assertIn(m, enum)
        con = sqlite3.connect(db)
        ddl = con.execute(
            "SELECT sql FROM sqlite_master WHERE name='product'").fetchone()[0]
        rows_before = con.execute("SELECT COUNT(*) FROM product").fetchone()[0]
        con.close()

        second = build_silently(db)          # 第二次：枚举已一致 → 不重建
        self.assertNotIn("迁移 product 表", second, "第二次 build 不该重建")
        con = sqlite3.connect(db)
        ddl2 = con.execute(
            "SELECT sql FROM sqlite_master WHERE name='product'").fetchone()[0]
        self.assertEqual(ddl, ddl2, "product DDL 变了（说明重建了）")
        self.assertEqual(rows_before,
                         con.execute("SELECT COUNT(*) FROM product").fetchone()[0])
        con.close()

    def test_old_db_upgrade_keeps_rows(self):
        db = tmpfile("old")
        con = sqlite3.connect(db)
        con.executescript(old_schema_text())
        seed_rows(con, ["US", "GB", "US"])
        con.close()
        self.assertEqual(sorted(product_enum(db)), sorted(OLD_MARKETS))

        out = build_silently(db)
        self.assertIn("迁移 product 表", out, "老库应触发一次迁移")
        enum = product_enum(db)
        for m in NEW_MARKETS:
            self.assertIn(m, enum)

        con = sqlite3.connect(db)
        rows = [r[0] for r in con.execute(
            "SELECT product_id FROM product ORDER BY product_id")]
        self.assertEqual(rows, ["T-GB-1", "T-US-0", "T-US-2"], "迁移后行集合应完全保留")
        self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        con.close()


class TestMigrateScript(unittest.TestCase):
    def setUp(self):
        self.db = tmpfile("mig")
        con = sqlite3.connect(self.db)
        con.executescript(old_schema_text())
        seed_rows(con, ["US", "GB", "CN"])
        con.close()
        self.manifest = tmpfile("manifest", ".json")

    def tearDown(self):
        cleanup_created()

    def run_migrate(self, *args: str) -> tuple[int, str]:
        p = subprocess.run(
            [sys.executable, str(ROOT / "db" / "migrate_country_check.py"),
             "--db", str(self.db), "--manifest", str(self.manifest), *args],
            capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
        return p.returncode, (p.stdout or "") + (p.stderr or "")

    def test_dry_run_then_apply_then_idempotent_then_rollback(self):
        code, out = self.run_migrate()
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(product_enum(self.db)), sorted(OLD_MARKETS),
                         "dry-run 不该写库")
        self.assertFalse(self.manifest.exists(), "dry-run 不该写 manifest")

        code, out = self.run_migrate("--apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(product_enum(self.db)),
                         sorted(OLD_MARKETS + NEW_MARKETS))
        self.assertTrue(self.manifest.exists())
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM product").fetchone()[0], 3)
        self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        con.close()

        code, out = self.run_migrate("--apply")      # 幂等
        self.assertEqual(code, 0, out)
        self.assertIn("已是目标枚举（幂等）", out)
        self.assertEqual(sorted(product_enum(self.db)),
                         sorted(OLD_MARKETS + NEW_MARKETS))

        code, out = self.run_migrate("--rollback")   # 回滚到 10 国
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(product_enum(self.db)), sorted(OLD_MARKETS))
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM product").fetchone()[0], 3)
        con.close()

    def test_rollback_refuses_when_new_market_rows_exist(self):
        code, out = self.run_migrate("--apply")
        self.assertEqual(code, 0, out)
        con = sqlite3.connect(self.db)
        con.execute(
            "INSERT INTO product (product_id, country, dosage_form, release, is_branded,"
            " status, source_id, retrieved_at) VALUES (?,?,?,?,?,?,?,?)",
            ("T-FR", "FR", "tablet", "none", 1, "active", "manual_seed", "2026-01-01"))
        con.commit()
        con.close()

        code, out = self.run_migrate("--rollback")
        self.assertNotEqual(code, 0, "有 FR 行时回滚必须被拒绝")
        self.assertIn("拒绝回滚", out)
        self.assertEqual(sorted(product_enum(self.db)),
                         sorted(OLD_MARKETS + NEW_MARKETS), "被拒绝时不该改动库")

    def test_refuses_real_db_without_allow_real(self):
        """写 data/drugs.db 必须显式 --allow-real；否则在建连之前就退出（不碰真库）。"""
        p = subprocess.run(
            [sys.executable, str(ROOT / "db" / "migrate_country_check.py"),
             "--db", str(ROOT / "data" / "drugs.db"), "--apply"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("拒绝写 data/drugs.db", p.stderr + p.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
