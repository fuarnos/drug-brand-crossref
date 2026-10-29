# 贡献指南（CONTRIBUTING）

> 这个仓库是「药品商品名跨国定位站」：给一个名字（商品名 / 通用名 / 俗称 / 包装上一行字），
> 定位它是哪个药、什么规格，再给出其他国家的对应产品。
> **先读 [AGENTS.md](AGENTS.md)**（数据纪律、验收门槛、发布纪律都以它为准），再看本页。

## 0. 三条红线（不可违背）

1. **商品名不是主键**：查询永远返回候选集，唯一性由「国家 × 剂型 × 规格 × 活性成分」锁定。
2. **碰撞自动推导**：`collision` 视图按「不同成分数 / 释放机制」分级，不手工标注；只有「品牌家族」是人工表。
3. **不给用药建议**：只做身份对应和「不可互换」警示，不输出剂量换算后的服药方案，不判断能否互相替代。

## 1. 环境与命令

Windows + PowerShell，仓库根就是工作目录。Python 3.12：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py db/init_db.py          # 建/升级库（幂等迁移）
& $py db/check_data.py       # 数据体检
& $py db/q.py "SELECT ..."   # 临时只读查询（只读连接用 mode=ro）
& $py run_all.py             # 备份库 → 入库 → 种子 → 建站
& $py site/build.py          # 只建站（等终端出现 == done ==）
```

发布唯一入口 `deploy/publish.ps1`（或双击 `发布网站.cmd`）——**绝不手工推 gh-pages**，见 [DEPLOY.md](DEPLOY.md)。

## 2. 四套测试（改到哪层跑哪套，发布前全跑）

```powershell
& $py -m unittest discover -s etl -t etl      # 归一化 + 各入库
& $py -m unittest discover -s lib -t lib      # 检索 / 碰撞
& $py -m unittest tests.test_mobile_inbox -v  # 手机通道：队列 / CLI / 端点
& $py tests/trilingual/run_tests.py           # 三语检索一致性（只读开库）
```

## 3. 数据纪律（摘要）

- `db/schema.sql` 是**单一真相源**；改表必须同时改 `db/init_db.py` 的幂等迁移（加列 `ALTER TABLE ADD COLUMN`；
  `country` 的 CHECK 只能重建表，init_db 已实现迁移路径）。schema 改动必须**先备份、在副本验证、能回滚**。
- 新增数据源：**许可先行**——先查清再落 [docs/许可清单.md](docs/许可清单.md) 结论；页面必须署名并链回原文；
  不确定就标「待确认」。对外**只发派生层**，不整包分发受限来源（见 [docs/数据溯源与许可.md](docs/数据溯源与许可.md)）。
- 溯源：新写入的 `substance` / `brand_family` 用 `etl/provenance.py` 的 `mark_substance()/mark_family()`
  记录 `source_id / method / confidence / decided_at`；`method` 只能是
  `rule | multi-source | editorial | imported`，`confidence` 只能是 `high | medium | low | unknown`。
  **旧行保持 NULL（来源未记录），不伪造**；规则自动定案 + 多源交叉 ≠ 人工复核。
- 俗称 / 旧名 / 网络叫法进 `nickname`（指向活性成分），**不进 `product_name`**；只做精确匹配，逐条写出处。
- 计数口径统一：README / About / CHANGELOG / `coverage` 表用同一组数字，**以 `data/drugs.db` 现查为准**，不照抄旧数字。
- 提交不包含：`data/*.db`、`data/raw/`、`data/backups/`、`site/dist/`、`.env`、`tools/`、`.tmp/`、`__pycache__/`。

## 4. 数据源漂移检查

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/drift_check.py          # 对比基线；有告警写 reports/drift-YYYYMMDD.md，退出码 1
& $py etl/drift_check.py --write-baseline --force   # 更新基线（需维护者批准）
```

基线 `data/sources/drift-baseline.json` 由维护者确认后更新；告警只提示，**不自动重跑 ingest、不改数据**。

## 5. 提交规范

- 一次提交一个主题；不顺手格式化无关文件；提交信息沿用 `v0.3.4: ...` / `MX strength: ...` / 中文描述。
- 改到 `etl/**`：重跑对应 ingest → `db/check_data.py` → 条数变化写进 CHANGELOG / README。
- 改到 `lib/search.py`、归一化：对应 unittest + `tests/trilingual/run_tests.py`。
- 改到站点/文案：全量建站到 `== done ==`、三语各抽 3 条检索、页数/索引/首屏体积回归、链接/404/sitemap 抽检。

## 6. 提 Issue / 报错

请带上：① 页面 URL 或检索词（商品名/通用名 + 国家）；② 期望看到什么、实际看到什么；③ 截图（放 `docs/img/`，kebab-case）；
④ 如涉及数据，附 `db/q.py` 的只读 SQL 与结果。**不要**在 issue 里贴受限来源的原始文件。

## 7. 许可

- **代码 MIT**（见 [LICENSE](LICENSE)）；**数据不随代码许可**，按来源分级（见 [docs/许可清单.md](docs/许可清单.md)）。
- 贡献代码即同意以 MIT 授权；贡献数据请同时说明来源与许可，维护者会写进许可清单。

_本项目为免费、非商业的公共信息站；不提供用药建议，不替代医生/药师或官方说明书。_
