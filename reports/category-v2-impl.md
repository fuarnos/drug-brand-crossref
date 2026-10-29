# task-1：ATC 类名 v2 + 大类 v2 + ATC/大类页去重（代码完成，构建待 DB 窗口）

> 2026-10-29 ｜ 范围：`site/build.py`（build.py 唯一写者）｜ 未写 DB、未改 `data/*`、未改 CHANGELOG、未构建 `site/dist`。
> 批次：v0.9.0（与 task-17/19/20/6 共用一次全量构建；构建前等 Lead 确认 DB 窗口结束）。

## 0. 结论

- 已应用 `.tmp/cat2/build-partial-v085-b.patch`（含 ATC v2 加载、大类 v2、base 去重、cap 80 + `<details>`、状态徽标、逐语来源；根目录验证文件 `write_bytes` 保留在 7450 行，未冲突）。
- 补完 atc.html L1 卡片 v2、`categories.json` 全量 v2 码集（1,154 项，299,356 B）、CSS 增量。
- 函数级冒烟：生成 1,154 个 ATC 页 + 16 个大类页 + atc.html + categories.json；weight-loss 含 semaglutide/tirzepatide；cold 无 R06 成员；allergy 全 R06；statins 7 个 base、成员无 cerivastatin（仅说明文字出现）、atorvastatin 两个盐型并 1 行；A 页 `<details>` 首段 80 行、隐藏 523 行。
- **未跑全量 build**：等 task-3 DB 窗口结束、Lead 明确「可以构建」。

## 1. 类名 v2

| 项 | 实测 |
|---|---|
| CSV 覆盖 | 1,154 码；en 非空 1,074 / zh 841 / es 441；全缺 20 码用 fallback_text |
| 回退链 | 本语 → en → zh → fallback_text；来源/许可/URL 跟随实际取用那一档 |
| 来源 | Wikipedia 749（CC BY-SA 4.0）/ Wikidata 281（CC0）/ 编辑译名 44 / 空 80 |
| 页面 | ATC 类目页标题 + 逐语来源小字；atc.html L1 卡片带来源；categories.json 1,154 ATC 项 + `atc_codes` 1,154 |
| 许可 | 逐语 source/license/URL 小字；editorial 条目标「编辑整理（项目）」 |

## 2. 大类 v2

| 大类 | 变化 | 冒烟成员数（base 去重后） |
|---|---|---:|
| weight-loss | A08 + A10BJ + A10BX16（tirzepatide）；GLP-1/降糖大类交集说明 | 19 |
| cold-medicine | 只留 R05 + N02BE；R06 全部移出；与 allergy 互见说明 | 54 |
| allergy | R06 全部归入；与 cold 互见说明 | 32 |
| statins | 排除 cerivastatin；保留状态徽标 + 撤市说明 | 7 |

## 3. 去重 / cap / 状态

- 复用 v0.8.3 `_sub_base_map`（canonical + 去盐/水合物）→ 同 base 只一行，附「盐型：…」。
- 函数级全量：1,154 页共 16,484 行；**base 重复页 0**；803 页有盐型被合并。
- 「同码重复页」从旧 851 → **696**：剩余均为**不同活性成分共用类目级 ATC 码**（如 A05BA 17 个成分、J07BN01 疫苗类），不是同药盐型重复；base/salt 重复为 0。
- cap 由 60/80 统一为 80；超出用 `<details class="atcdetails">` 展开（无 JS 可点开）。命中 28 页（旧 71）；A 页首段 80 + 隐藏 523。
- 成员状态角标聚合产品 status（withdrawn/discontinued/active/unknown），按产品数 title。
- 四语 key：`atc.show_all` / `atc.salt_label` / `atc.status_note` / `atc.names_source_note` 四语齐全（冒烟生成时 i18n 397 keys zh-Hant 无缺）。

## 4. 复核命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -m py_compile site/build.py
& $py .tmp/cat2/verify_functions.py        # 类名/大类/去重/cap 函数级
& $py .tmp/cat2/task1_smoke.py             # 1,154 ATC + 16 大类 + categories.json 冒烟
Get-Content .tmp/cat2/task1-smoke.json -Encoding utf8
```

## 5. 缺口 / 待办

- 全量构建与 dist 数字（文件数/体积/sitemap）待 DB 窗口后统一构建；本报告不填。
- zh-Hant 类名回退按 Lead 指定链 本语→en→zh；个别类目（如 A10BJ）zh/es 无值时显示英文名并标 fallback，不机器翻译。
- 「696 同码页」为 ATC 类目级码语义，非盐型重复；报告已单列口径。
