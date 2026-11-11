# 法国（FR）真库窗口执行报告 —— BDPM 入库 + country 枚举迁移

- 日期：北京时间 2026-11-13 06:2x（本机 PT 2026-11-11 14:22–14:35）
- 工位：phaseb-data（Lead 授权的 **真库写窗口**）
- 结论：**两步都成功**，`data/drugs.db` 现有 **FR 15,799 产品**、总产品 **494,992**；
  `integrity_check ok` / `foreign_key_check 0` / `quick_check ok`；`check_data` 前后差异**只有 FR 相关行**。
  ⚠️ 但**注册表还没改**，`tests.test_markets_registry` 现在**红 1 项**（§5 给了可直接套的补丁）。

---

## 0. 一句话数字

| 项 | 改前 | 改后 | Δ |
|---|---:|---:|---:|
| `product` 总数 | 479,193 | **494,992** | **+15,799** |
| └ `country='FR'` | 0 | **15,799** | +15,799 |
| `product_component` | 630,151 | **649,322** | +19,171 |
| `name_key` | 202,739 | **214,397** | +11,658 |
| `name_variant` | 231,105 | **246,650** | +15,545 |
| `product_name` | 655,004 | **670,803** | +15,799 |
| `substance` | 12,637 | 12,637 | **0** ✓ |
| `variant` | 14,237 | 14,237 | 0 |
| `source` | 41 | 42 | +1（`bdpm_fr`） |
| `ingest_run` | 19 | 20 | +1（`bdpm_fr-2026-11-11`，rows_in 15,799 / kept 15,799 / ok） |
| `collisions(severe)` | 23,855 | 24,954 | +1,099（FR 品牌名带来的跨市场同名，属预期） |
| `collisions(warning)` | 925 | 925 | 0 |
| 别名（`drug_term` / `alias_all`） | 1,017 / 1,074 | 1,017 / 1,074 | 0（未受影响） |

---

## 1. 备份（两份，都在 `data/backups/`）

| 文件 | 大小 | 说明 |
|---|---:|---|
| `data\backups\drugs-20261111-142234.db` | 428,703,744 B | **手动备份**（窗口第一步） |
| `data\backups\drugs.before-country-check-20261111-142250.db` | 428.7 MB | 迁移脚本 `--backup-dir` 自动备份（迁移前一刻） |

撤销清单：

| manifest | 内容 |
|---|---|
| `.tmp\country-mig\country_check_manifest.json` | country 枚举 10→14 的前后快照（枚举 / 行数 / hash / 索引 / 视图 / db_size） |
| `.tmp\fr-apply-manifest.json` | FR 入库写入明细（见 §2），含回滚所需信息 |

---

## 2. 执行步骤与结果

### 2.1 ① country CHECK 迁移（FR/LV/JP/KR）

```powershell
& $py db\migrate_country_check.py --apply --allow-real --db data\drugs.db --backup-dir data\backups --vacuum
```

```
当前枚举: [US,GB,CN,ES,MX,AU,CA,TW,HK,SG]  → 目标 [.., FR,LV,JP,KR]
已备份: data\backups\drugs.before-country-check-20261111-142250.db（0.1s，428.7 MB）
迁移完成：3.91s | 行数 479,193（不变）| hash 一致
VACUUM 完成：6.89s，DB 422.1 MB
DB size: 428.7 MB → 422.1 MB
```

- 行数 479,193 不变、`product_id` 内容 hash 一致、索引 2 个 / 视图 3 个不变
- 迁移后枚举 14 个：`US,GB,CN,ES,MX,AU,CA,TW,HK,SG,**FR,LV,JP,KR**`

### 2.2 ② FR（BDPM）入库

```powershell
& $py etl\markets\fr.py --apply --allow-real --db data\drugs.db --manifest .tmp\fr-apply-manifest.json
```

```
!! 警告：正在对真实库 data\drugs.db 执行 apply（--allow-real）
=== FR（BDPM）写入完成 ===
written: product 15,799 | name_key 11,658 | name_variant 15,545 |
         product_name 15,799 | product_component 19,171 | ingest_run 1
counts_before: product 479,193 | product_fr 0 | components 630,151 | name_key 202,739 | source 41
counts_after : product 494,992 | product_fr 15,799 | components 649,322 | name_key 214,397 | source 42
旧 FR 行删除 0 · 撤销清单 .tmp\fr-apply-manifest.json
db sha256 46c783b2… → 5deee24c… · 耗时 6.78s
```

与 Lead 预期完全一致：**+15,799 产品 / +19,171 组件 / +11,658 name_key / 0 substance**，source = `bdpm_fr`。

### 2.3 ③ 核对

```powershell
& $py db\q.py "SELECT COUNT(*) FROM product WHERE country='FR'"          -- 15,799 ✅
& $py db\q.py "SELECT COUNT(*) FROM product"                             -- 494,992 ✅
& $py db\check_data.py                                                   -- 见下
PRAGMA integrity_check = ok | foreign_key_check = 0 条 | quick_check = ok
```

`coverage` 新增 FR 行（现查）：

| country | n_products | n_variants | n_active | last_synced |
|---|---:|---:|---:|---|
| **FR** | **15,799** | 1,869 | **13,559** | 2026-11-11 |
| CN | 145,051 | 3,086 | 145,051 | 2026-10-26 |
| US | 110,179 | 4,802 | 110,179 | 2026-10-25 |
| GB | 61,051 | 3,941 | 61,051 | 2026-10-26 |
| AU | 44,794 | 3,595 | 7,160 | 2026-10-29 |
| CA | 43,847 | 3,536 | 14,519 | … |
| ES | 25,395 | 2,157 | 16,030 | 2026-10-27 |
| TW | 16,457 | 2,010 | 16,457 | 2026-10-28 |
| HK | 13,935 | 1,649 | 0 | 2026-10-29 |
| MX | 10,878 | 1,970 | 1,772 | 2026-10-25 |
| SG | 5,511 | 1,671 | 5,511 | 2026-10-28 |
| EU（区域层） | 2,095 | 1,045 | 1,547 | 2026-11-10 |

**其余 10 个市场的行数与改前逐项相同**（AU 44,794 / CA 43,847 / CN 145,051 / ES 25,395 / EU 2,095 /
GB 61,051 / HK 13,935 / MX 10,878 / SG 5,511 / TW 16,457 / US 110,179）→ 没有误伤别国数据。

### 2.4 `check_data` 前后 diff（29 行，全部是 FR 相关）

```diff
+   ('FR', 15799, 1869, 13559, '2026-11-11')          # coverage 新行
-   products             479193
+   products             494992
-   components           630151
+   components           649322
    substances           12637        (不变)
-   name_keys            202739
+   name_keys            214397
-   names                655004
+   names                670803
-   collisions(severe)   23855
+   collisions(severe)   24954
    collisions(warning)  925          (不变)
    nickname             57 / drug_term 1017 / aliases(total) 1074   (不变)
    confusable_pairs     22           (不变)
```

### 2.5 FR 数据抽查

| 项 | 值 |
|---|---|
| 有成分的 FR 产品 | **13,861 / 15,799**（1,938 条无成分行，多为 BDPM 无成份字段的制剂/耗材） |
| 状态分布 | active **13,559** / discontinued 1,217 / withdrawn 1,017 / unknown 6 |
| 主名条数 | 15,799（`product_name` primary） |
| source | `bdpm_fr` = *Base de données publique des médicaments (BDPM) — ANSM*，`data_as_of=2026-11-03` |
| ingest_run | `bdpm_fr-2026-11-11`：rows_in 15,799 / rows_kept 15,799 / status **ok** / finished 2026-11-11T22:23:21Z |

样例（现查，法语原文）：

```
FR-60002283 | comprimé pelliculé     | tablet      | Anastrozole 1.0mg
FR-60003620 | suspension pour inhalation par nébuliseur | inhalation | Beclometasone Dipropionate 800.0mcg
FR-60004277 | gélule                  | capsule     | Fenofibrate 100.0mg
FR-60004487 | comprimé à libération prolongée | tablet | Tramadol Hydrochloride 200.0mg
```

---

## 3. 回滚命令（**只在需要时、由 Lead 拍板**）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 3.1 先撤 FR 数据（按 fr.py 自己的 manifest）
& $py etl\markets\fr.py --rollback --allow-real --db data\drugs.db --manifest .tmp\fr-apply-manifest.json

# 3.2 再撤 country 枚举（要求库里已无 FR/LV/JP/KR 行）
& $py db\migrate_country_check.py --rollback --allow-real --db data\drugs.db `
      --manifest .tmp\country-mig\country_check_manifest.json

# 3.3 兜底：直接还原窗口前的备份（最快、最确定）
Copy-Item "data\backups\drugs-20261111-142234.db" data\drugs.db -Force
```

顺序理由：枚举回滚**会拒绝**「库里还有 FR 行」的库（防止静默丢行），所以必须先撤数据再撤枚举。

---

## 4. 当前状态与风险

| # | 事项 | 状态 |
|---|---|---|
| 1 | 真库已写 FR（15,799）/ 枚举 14 国 | ✅ 完成、核对通过 |
| 2 | `check_data` / `integrity` / `FK` / `coverage` | ✅ 全部符合预期 |
| 3 | **`tests.test_markets_registry` 现在 FAILED 1 项** | ⚠️ 见 §5（必须同批补注册表） |
| 4 | 站点产物未重建 | 待 build（新 FR 数据要重建才会出现在页面/索引） |
| 5 | LV/JP/KR 枚举已就绪但无数据 | 预期（枚举先行） |

---

## 5. ⚠️ 必须同批补的注册表补丁（不在本工位写权限内，已用 `lib/markets.py` 验证）

`& $py -m unittest tests.test_markets_registry` 现状：

```
FAILED (failures=1)
AssertionError: Items in the second set but not the first: 'FR'
: 注册表启用国家与 DB product.country 不一致（改 DB 前先改注册表）
```

### 5.1 三处改动（缺一个都过不了）

**① `data/markets.json` → `markets` 数组插入 FR**（`order=52`，插在 ES(50) 之后）：

```json
{
  "code": "FR", "kind": "country", "parent": "EU", "group": "EUROPE",
  "name": {"en": "France", "es": "Francia", "zh": "法国"},
  "i18n_key": "home.fr", "flag": "🇫🇷",
  "source_id": "bdpm_fr", "extra_source_ids": [],
  "default_lang": "en", "languages": ["en"],
  "enabled": true, "order": 52, "data_as_of": "2026-11-03",
  "notes": "BDPM（ANSM 公开数据，Etalab 2.0）；15,799 产品 / 19,171 组件；法语原文、UI 暂用英文（fr 语言未启用）。"
}
```

**② `data/languages.json`：把禁用占位 `fr` 的 `default_country` 从 `FR` 改成 `BE`，并把 `BE` 加进 `planned_markets`**

理由（实测，不是推断）：`fr` 语言是 disabled 占位且 `default_country=FR`。一旦注册 FR 市场：
- 若 `FR.languages=["en"]` → `validate()` 报「语言 fr: default_country=FR 的 languages 未包含该语言」；
- 若 `FR.languages=["fr","en"]` → 报「市场 FR: 启用了未启用的语言 fr」。
两条死路，唯一可行解是把 `fr` 占位的默认国家挪到一个**未注册**的法语市场（BE），并登记 `planned_markets`。

```json
"fr": { ..., "default_country": "BE", ... }      // 原为 "FR"
"planned_markets": ["DE", "IT", "NL", "PL", "PT", "BE"]   // 原为 DE/IT/NL/PL/PT
```

**③ `site/build.py` 的 I18N 补 `home.fr`**（三语：`France` / `Francia` / `法国`）
——`tests.test_markets_registry::test_i18n_keys_unique_and_match_existing_site_keys` 要求
「启用市场的 `i18n_key` 必须存在于站点 I18N」。

### 5.2 验证证据（我只读跑过，未落盘）

```
方案 C：FR.languages=['en'] + fr.default_country=BE + planned_markets+=BE  → validate(): OK ✅
方案 D：fr 保持 default_country=FR                                        → FAIL（上述第一条）
方案 E：fr.default_country=BE 但 planned_markets 不加 BE                  → FAIL（既不在 markets 也不在 planned）
```

> 另注：`planned_markets` 现为 `('DE','IT','NL','PL','PT')`（FR 已被别的工位移出），所以只需再补 `BE`。

---

## 6. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py db\q.py "SELECT COUNT(*) FROM product WHERE country='FR'"
& $py db\check_data.py
& $py -m unittest tests.test_markets_registry -v      # 现在：FAILED 1（等 §5 注册表补丁）
```

证据文件（不入库）：`.tmp\fr-apply.log`、`.tmp\fr-window-check_data-before.txt`、
`.tmp\fr-window-check_data-after.txt`、`.tmp\fr-apply-manifest.json`、
`.tmp\country-mig\country_check_manifest.json`。
