-- ============================================================================
-- TW 数据源登记（source_id = tfda_tw）—— task-71
--
-- 用途：给 data/markets.json 的 TW.source_id='tfda_tw' 在 DB `source` 表登记
--       数据源信息（许可/署名/data_as_of），使 lib/markets.py 校验与站点 About
--       署名有据可依。幂等（INSERT OR REPLACE），可重复执行。
--
-- 执行（真实库，**由 Lead 执行；本文件不自动执行**）：
--   sqlite3 data/drugs.db < db/source_tfda_tw.sql
--   或 & $py -c "import sqlite3;c=sqlite3.connect('data/drugs.db');c.executescript(open('db/source_tfda_tw.sql',encoding='utf-8').read());c.commit()"
--   或由 etl/ingest_tw_tfda.py 的 --write-db 首次写库时代码内一并 upsert（推荐，同事务）。
--
-- 前置/配套：
--   - data/markets.json TW.source_id 已是 tfda_tw（enabled=false）；
--   - 数据库需已含 TW 国家枚举（db/init_db.py / db/migrate_country_tw.py）；
--   - 本 SQL 只登记来源，不写 product 数据。
--
-- 校验：
--   sqlite3 data/drugs.db "SELECT source_id,name,license,license_url,data_as_of FROM source WHERE source_id='tfda_tw';"
--   & $py lib/markets.py --check      # 期望 exit 0 / "OK: 注册表校验通过"
--   & $py -m unittest tests.test_markets_registry -v   # 期望 47/47 通过（需真实库已执行本 SQL）
--
-- 回滚：
--   DELETE FROM source WHERE source_id='tfda_tw';
--   注意：若 markets.json 仍引用 tfda_tw，删除后 lib/markets.py --check 会失败；
--   完整回滚 = 恢复本 SQL 前的 DB 备份（或同时把 markets.json TW.source_id 改回 null）。
-- ============================================================================

INSERT OR REPLACE INTO source
    (source_id, name, url, license, license_url, retrieved_at,
     data_as_of, data_as_of_note, notes)
VALUES (
    'tfda_tw',
    '衛生福利部食品藥物管理署（TFDA）全部藥品許可證資料集',
    'https://data.gov.tw/dataset/9122',
    '政府資料開放授權條款－第1版 (OGDL v1.0)',
    'https://data.gov.tw/license',
    '2026-10-28',
    '2026-10-22',
    'weekly（每 7 日與藥證業務管理系統同步）',
    '可再发布（OGDL v1.0，须按「顯名聲明」署名：衛福部食藥署 TFDA「全部藥品許可證資料集」，依政府資料開放授權條款第1版釋出，https://data.gov.tw/license）；本站只存事实字段（品名/成分/劑型/廠商/證號/狀態），不存適應症/用法用量正文。'
);

-- 可选：首次 ingest 时由脚本写 ingest_run（本文件不含，避免重复执行污染计数）
-- INSERT INTO ingest_run (run_id, source_id, started_at, finished_at, rows_in, rows_kept,
--                         rows_rejected, status, note)
-- VALUES ('tfda_tw-20261028', 'tfda_tw', '2026-10-28T00:00:00-07:00', NULL,
--         72096, 17892, 54204, 'ok', 'first TW ingest; data_as_of=2026-10-22');
