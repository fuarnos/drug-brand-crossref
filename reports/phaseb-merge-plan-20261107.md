# Phase B 合并/改名执行计划（只读产出 → 供 DB 窗口照单执行）

> 日期：2026-11-07｜状态：**只读**，未写 `data/drugs.db`、未改 `site/` `lib/` `docs/`、未 commit
> 产物：`data/sources/phaseb-merge-plan-20261107.csv`（92 行，列 `action,target_substance_id,source_substance_id(s),reason,evidence,confidence,rollback_note`）+ 本报告
> 上游：`reports/phaseb-candidates-20261031.md`、`reports/phaseb-dup-zh-20261031.md`、`reports/phaseb-prep-20261031.md`、`reports/task5-inn-mapping-plan.md`、`data/substance_aliases.csv`
> 基线（现查，`data/drugs.db` 只读 `mode=ro`）：成分 **12,649** / variant **14,249** / 产品 **477,098** / 组件 **628,013** / 中文主名 **1,791**

## 0. 先看这段：下一窗口照这个顺序做

| 批次 | 内容 | CSV 行 | 改库？ | 风险 | 一句话 |
|---|---|---:|---|---|---|
| **B0** | `alias_link` 异名表（10 行已落地 + 2 行待加） | 12 | 否（只改 `data/substance_aliases.csv`） | 零 | 先做，10 分钟，跑一次 `lib` 测试即可 |
| **B1** | `rename_inn` 改名（CJK 主名 → 英文 INN，保留中文名） | 21 | 是（单列 UPDATE，318 产品仅换显示名） | 低 | 无 UNIQUE 冲突、产品/组件 0 变化，可回滚成一条 UPDATE |
| **B2** | `merge_duplicate` 小合并（≤91 产品/条） | 10 | 是（移动组件 + 删 1 条 substance） | 中 | 逐条 `--apply` + 逐条校验，失败即停 |
| **B3** | `merge_duplicate` 大体量/校验缺口 | 2 | 是 | 中高 | 间苯二酚（目标无 ATC）先人工看样例；manitol（330 产品）最后做 |
| **B4** | `candidate_only` 只留候选 | 37 | 否 | — | 本窗口**不做**，卡在「盐/酯没落 variant」等前置 |
| **B5** | `drop` 判不了 | 10 行 / 1,722 条 | 否 | — | 本窗口**不做**，不猜、不翻译 |

**一句话**：92 行 = 12 异名 + 21 改名 + 12 合并 + 37 只留候选 + 10 行丢弃（聚合 1,719 + 个体 3）。
下一窗口真正的写库动作只有 **B0 的 2 行文件改动 + B1 的 21 条 UPDATE + B2/B3 的 12 次合并**；B4/B5 是留档，不动。
**池内 1,791 条被唯一分解**：21 + 11 + 37 + 3 + 1,719 = 1,791（脚本内 `assert` 校验，见 §8）。

## 1. 动作计数（与 CSV 逐行对齐）

| action | CSV 行数 | 覆盖记录数 | 是否改库 | 说明 |
|---|---:|---:|---|---|
| `alias_link` | 12 | 12（对） | 否 | 只加异名表；10 对已在 `data/substance_aliases.csv:L16–L25`，2 对待加 |
| `rename_inn` | 21 | 21 | 是 | `substance.inn_en` CJK → INN + `name_lang` zh → en，`inn_zh` 原样保留 |
| `merge_duplicate` | 12 | 12（源记录） | 是 | 11 条池内 + 1 条池外（`manitol`→`mannitol`） |
| `candidate_only` | 37 | 37 | 否 | 保留候选，卡点写在 `reason` |
| `drop` | 10 | 1,722 | 否 | 7 条聚合行（1,719 条）+ 3 条个体（2 条 low + 1 条复方） |
| **合计** | **92** | — | — | — |

池内 1,791 的分解：`rename_inn` 21 + `merge_duplicate` 11 + `candidate_only` 37 + `drop`（3 个体 + 1,719 聚合）= **1,791**。
池外 13 行：`alias_link` 12（10 已落地 + 2 待加）+ `merge_duplicate` 1（`manitol`）。CSV 一行只对应一个动作，同一 substance 不重复出现。

复核命令：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$csv = 'data\sources\phaseb-merge-plan-20261107.csv'
(Import-Csv $csv).Count                                                        # 92
Import-Csv $csv | Group-Object action | Sort-Object Name | Format-Table Count,Name
Import-Csv $csv | Where-Object {$_.action -eq 'merge_duplicate'} | Measure-Object  # 12
Import-Csv $csv | Where-Object {-not $_.evidence -or -not $_.rollback_note} | Measure-Object  # 0
```

## 2. CSV 约定（读表前先看这 6 行）

1. `target_substance_id`：动作作用的记录 —— 改名 = 被改的 CJK 记录；合并 = 保留的目标；异名 = canonical。
2. `source_substance_id(s)`：被合并/被连接的来源 —— 合并 = 删除的那条；异名 = alias；改名与只留候选填 `-`；聚合丢弃填 `count:N`。
3. `reason` 以 **批次前缀** `[B0]…[B5]` 开头，可直接按前缀排序执行；改名行里用 `inn_en: 旧 → 新` 记录目标写法。
4. `evidence` 必带上游出处（`phaseb-candidates-20261031.csv:L<物理行号>`）与复核用 SQL/命令。
5. `rollback_note` 必带可执行回滚（改名 = 反向 UPDATE 原值；合并 = manifest 逆序；异名 = 删该行；B4/B5 = 无操作）。
6. `confidence` 沿用上游（high/medium/low）；聚合丢弃行为 `none`（它们没有候选，谈不上置信度）。

## 3. 按风险排序：每类动作的前置校验 SQL

### 3.1 B0 `alias_link`（零风险，只改一个 CSV）

前置：

```powershell
# 两个 id 必须都在库（应 2 行）
& $py db/q.py "SELECT substance_id, inn_en, atc FROM substance WHERE substance_id IN ('pizotifen','pizotifeno')"
# 同一对不得已在异名表里（应 0 行）
Import-Csv data\substance_aliases.csv | Where-Object {$_.alias_id -eq 'pizotifeno'}
```

后置：

```powershell
& $py -c "from lib.aliases import load; am=load(); print(sorted(am.lookup_name('Pizotifeno')), sorted(am.lookup_name('Silibinina')))"
# 期望：两个集合都含各自的 canonical id（pizotifen / silibinin）
& $py -m unittest discover -s lib -t lib      # 异名表改动只影响检索层
```

**注意**：`manitol`→`mannitol` 合并（B3-2）之后，`data/substance_aliases.csv:L7` 会变成自环
（canonical_id = alias_id = `mannitol`）。`lib/aliases.py` 对自环无害（并查集 no-op），建议合并后顺手删该行，删不删都不影响功能。

### 3.2 B1 `rename_inn`（低风险：一条 UPDATE，产品/组件不动）

以 `甘羟铝` 为例，**每一行都要先跑这 3 条**：

```powershell
# ① 撞车检查：目标写法在库内任何形式都不得存在（应 0 行）——UNIQUE(inn_en) 的前置防线
& $py db/q.py "SELECT substance_id, inn_en FROM substance WHERE lower(replace(replace(inn_en,' ',''),'-',''))='aluminiumglycinate'"
# ② 记录现状：应为 1 行，name_lang='zh'，inn_en=inn_zh=CJK 主名（改名后 inn_zh 必须还是这个中文名）
& $py db/q.py "SELECT substance_id, inn_en, inn_zh, atc, name_lang FROM substance WHERE substance_id='cn-9be0c6ea3c'"
# ③ 影响面基线：改名前后必须完全相同
& $py db/q.py "SELECT COUNT(DISTINCT pc.product_id), COUNT(*) FROM product_component pc JOIN variant v ON v.variant_id=pc.variant_id WHERE v.substance_id='cn-9be0c6ea3c'"
```

后置（每 10 行跑一次，别攒到最后）：

```powershell
# 逐条回看：inn_en 已是拉丁写法、inn_zh 仍是中文原名、name_lang='en'（把 21 个 id 一次 IN 进去）
& $py db/q.py "SELECT substance_id, inn_en, inn_zh, name_lang FROM substance WHERE substance_id IN ('cn-9be0c6ea3c','cn-ac149aec0e')"
# name_lang 分布：zh = 1791 − 已改数，en = 10858 + 已改数，其余不变
& $py db/q.py "SELECT name_lang, COUNT(*) FROM substance GROUP BY 1 ORDER BY 2 DESC"
& $py db/q.py "SELECT (SELECT COUNT(*) FROM substance) s, (SELECT COUNT(*) FROM variant) v, (SELECT COUNT(*) FROM product) p, (SELECT COUNT(*) FROM product_component) c"
# 期望：s=12649 v=14249 p=477098 c=628013（改名一条都不减）
```

> **坑（现查过）**：别用 `inn_en GLOB '*[^ -~]*'` 判「en 主名里还有没有中文」——库里有 **225** 条 `name_lang='en'` 带重音拉丁字母（`Ácido Mefenámico`、`Toxina Botulínica A`、`Zinc Óxido`…），会全部误报；且中文主名里也常有拉丁字母（`放线菌素D`）。判 CJK 只能用 Python 正则 `[\u4e00-\u9fff]` 或直接看 `name_lang` 分布。

### 3.3 B2/B3 `merge_duplicate`（中风险：移动组件 + 删 1 条 substance）

对**每一条**合并，用同一组 SQL，合并前后各跑一次，数字必须一致：

```powershell
# ① 产品/组件：合并前后必须相同（组件只改挂，不删不建）——把 src/tgt 换成 CSV 里的两个 id
& $py db/q.py "SELECT COUNT(DISTINCT pc.product_id)||'/'||COUNT(*) FROM product_component pc JOIN variant v ON v.variant_id=pc.variant_id WHERE v.substance_id IN ('cn-9b556b8ffa','mesalamine')"
# 期望 396/396（= CSV evidence 里写的「期望」值）
# ② variant：合并前 N，合并后 N−1
& $py db/q.py "SELECT COUNT(*) FROM variant WHERE substance_id IN ('cn-9b556b8ffa','mesalamine')"
# ③ substance：合并前 2，合并后 1
& $py db/q.py "SELECT COUNT(*) FROM substance WHERE substance_id IN ('cn-9b556b8ffa','mesalamine')"
# ④ 源记录不得被引用（4 个数字必须全 0；任一非 0 → 不合并，回填本计划后另议）
& $py db/q.py "SELECT (SELECT COUNT(*) FROM nickname WHERE substance_id='cn-9b556b8ffa'), (SELECT COUNT(*) FROM drug_term WHERE substance_id='cn-9b556b8ffa'), (SELECT COUNT(*) FROM confusable_pair WHERE a_substance_id='cn-9b556b8ffa' OR b_substance_id='cn-9b556b8ffa'), (SELECT COUNT(*) FROM dose_warning WHERE substance_id='cn-9b556b8ffa' OR related_substance_id='cn-9b556b8ffa')"
# ⑤ 目标 base variant 必须唯一（应 1 行）；`loxapine` 有 3 个 variant，需显式指定 base
& $py db/q.py "SELECT variant_id FROM variant WHERE substance_id='mesalamine' AND COALESCE(salt,'')='' AND COALESCE(hydrate,'')='' AND COALESCE(ester,'')=''"
# ⑥ 目标中文名状态：空 → 合并时把源 inn_zh 写进去；非空 → 走 nickname(kind=legacy)，不覆盖
& $py db/q.py "SELECT substance_id, inn_zh FROM substance WHERE substance_id='mesalamine'"
```

合并后全局（每次 `--apply` 之后立刻跑）：

```powershell
& $py db/q.py "SELECT (SELECT COUNT(*) FROM substance) s, (SELECT COUNT(*) FROM variant) v, (SELECT COUNT(*) FROM product) p, (SELECT COUNT(*) FROM product_component) c"
# 单条合并后：s 减 1、v 减 1、p 不变、c 不变
```

**全部 12 条合并做完后的终态**（本报告的唯一硬验收数）：

```text
substance 12,649 → 12,637（−12）
variant   14,249 → 14,237（−12）
product   477,098 → 477,098（不变）
component 628,013 → 628,013（不变）
name_lang='zh' 1,791 → 1,759（−21 改名 −11 合并）
```

### 3.4 B4 `candidate_only` / B5 `drop`（不执行，只复核）

```powershell
# 这两类不允许出现任何写库；抽查 3 条确认原样
& $py db/q.py "SELECT substance_id, inn_en, name_lang FROM substance WHERE substance_id IN ('cn-7b0dc44273','cn-c78abb9d43','cn-1267bbdd5d')"
```

## 4. 合并前后计数（每条都写死，执行时对着看）

| # | 源（删除） | 目标（保留） | 合并前 产品/组件/variant | 合并后应有 产品/组件/variant | 批次 |
|---:|---|---|---|---:|---|
| 1 | `cn-4843d6cbec` 蛋氨酸 | `methionine` | 0+443=443 / 0+446=446 / 1+1 | 443 / 446 / 1 | B2 |
| 2 | `cn-9b556b8ffa` 美沙拉嗪 | `mesalamine` | 1+395=396 / 1+395=396 / 1+1 | 396 / 396 / 1 | B2 |
| 3 | `cn-b46751b5ce` 玻璃酸酶 | `hyaluronidase` | 8+10=18 / 8+10=18 / 1+1 | 18 / 18 / 1 | B2 |
| 4 | `cn-ad8ef97013` 硼酸 | `boric-acid` | 12+75=87 / 12+75=87 / 1+1 | 87 / 87 / 1 | B2 |
| 5 | `cn-a9cb857f66` 普罗雌烯 | `promestrieno` | 7+6=13 / 7+6=13 / 1+1 | 13 / 13 / 1 | B2 |
| 6 | `cn-6805b038c2` 交沙霉素 | `josamicina` | 8+1=9 / 8+1=9 / 1+1 | 9 / 9 / 1 | B2 |
| 7 | `cn-6324366133` 放线菌素D | `dactinomycin` | 3+10=13 / 3+10=13 / 1+1 | 13 / 13 / 1 | B2 |
| 8 | `cn-5b6808bd1c` 丝裂霉素 | `mitomycin` | 7+84=91 / 7+84=91 / 1+1 | 91 / 91 / 1 | B2 |
| 9 | `cn-81406bceba` 苯噻啶 | `pizotifen` | 1+47=48 / 1+47=48 / 1+1 | 48 / 48 / 1 | B2 |
| 10 | `cn-997ef86830` 洛沙平吸入剂 | `loxapine` | 1+87=88 / 1+87=88 / 1+3 | 88 / 88 / 3 | B2 |
| 11 | `cn-c94867c0ad` 间苯二酚 | `resorcinol` | 6+49=55 / 6+49=55 / 1+1 | 55 / 55 / 1 | B3 |
| 12 | `manitol` 甘露醇 | `mannitol` | 330+85=415 / 330+98=428 / 1+1 | 415 / 428 / 1 | B3 |

12 条合计：移动 **384 个产品 / 384 个组件**（源记录每条产品恰好 1 个组件），删除 **12 条 substance + 12 条 variant**，产品身份（`product_id`）一条都不变。
所有 12 对的产品重叠数都是 **0**（没有「同一产品两侧都有成分」的塌缩情况），所以「合并后产品数 = 两侧相加」是安全的。

## 5. 建议执行批次与顺序

| 步 | 动作 | 具体 | 前置 | 验收 |
|---:|---|---|---|---|
| 0 | 备份 + 基线 | 复制 `data/drugs.db` → `data/backups/drugs-before-phaseb-20261107.db`；记录 4 表基线与 `name_lang` 分布 | DB 窗口独占（不与其他入库并行） | 基线数字对得上本报告开头 |
| 1 | **B0** | 加 2 行异名（`pizotifen↔pizotifeno`、`silibinin↔silibinina`），另 10 行已存在 | 无 | `lib` 测试 + `lookup_name` 抽查 |
| 2 | **B1-1** | 改名 10 条（ATC A02AB–J01ED，表见 §6.1） | §3.2 ① 全 0 行 | 4 个计数 + 抽查 3 条检索 |
| 3 | **B1-2** | 改名 11 条（ATC J01MA–R07AB） | 同上 | 同上；`zh` 计数应为 1,770 |
| 4 | **B2** | 10 条小合并，逐条 `--dry-run` → `--apply` → §3.3 六条 SQL | B1 完成 | 每条后跑全局 4 计数；失败即停 |
| 5 | **B3-1** | `间苯二酚 → resorcinol`（目标无 ATC，先人工看 3 个样例产品） | 人工确认 | 同上 |
| 6 | **B3-2** | `manitol → mannitol`（330 产品，体量最大，放最后） | B3-1 通过 | 415/428；`aliases.csv:L7` 顺手删 |
| 7 | 收尾 | `db/check_data.py` → 4 套测试 → `site/build.py` 到 `== done ==` → 三语各抽 3 条检索 | — | 终态 §3.3 数字 |
| — | **B4/B5** | 不执行 | — | 只在本计划留档 |

时段：按 AGENTS §12，写库/建站尽量落在北京时间 **00:30–08:30 谷段**；B1 与 B2 之间可以断开，因为它们互不依赖。

## 6. 明细

### 6.1 B1 改名 21 条（产品/组件只是显示名变化）

| # | substance_id | 现主名 | 改为 | ATC | 产品/组件 | 批次 |
|---:|---|---|---|---|---:|---|
| 1 | `cn-9be0c6ea3c` | 甘羟铝 | Aluminium Glycinate | A02AB | 7 / 7 | B1 |
| 2 | `cn-ac149aec0e` | 磷酸铝 | Aluminium Phosphate | A02AB | 10 / 10 | B1 |
| 3 | `cn-44d979c469` | 吉法酯 | Gefarnate | A02BX | 1 / 1 | B1 |
| 4 | `cn-c8e70a4bd8` | 瑞巴派特 | Rebamipide | A02BX | 93 / 93 | B1 |
| 5 | `cn-b6e78d9b17` | 羟甲烟胺 | Nicotinyl Methylamide | A05AB | 19 / 19 | B1 |
| 6 | `cn-b77647d164` | 吲哚布芬 | Indobufen | B01AC | 47 / 47 | B1 |
| 7 | `cn-9d914cf7e9` | 胰蛋白酶 | Trypsin | B06AA | 4 / 4 | B1 |
| 8 | `cn-baac1b376a` | 长春胺 | Vincamine | C04AX | 11 / 11 | B1 |
| 9 | `cn-bd2d3d49b2` | 西尼地平 | Cilnidipine | C08CA | 24 / 24 | B1 |
| 10 | `cn-eafc36d659` | 二硫化硒 | Selenium Disulfide | D01AE | 14 / 14 | B1 |
| 11 | `cn-824b3c6206` | 磺胺林 | Sulfalene | J01ED | 1 / 1 | B1 |
| 12 | `cn-843e46d77b` | 磺胺对甲氧嘧啶 | Sulphamethoxydiazine | J01ED | 12 / 12 | B1 |
| 13 | `cn-970a437917` | 普卢利沙星 | Prulifloxacin | J01MA | 26 / 26 | B1 |
| 14 | `cn-a0a548096f` | 西他沙星 | Sitafloxacin | J01MA | 11 / 11 | B1 |
| 15 | `cn-a81c6d1750` | 司莫司汀 | Semustine | L01AD | 6 / 6 | B1 |
| 16 | `cn-7884949cb9` | 卡莫氟 | Carmofur | L01BC | 1 / 1 | B1 |
| 17 | `cn-afaaa0ade5` | 依普黄酮 | Ipriflavone | M05BX | 2 / 2 | B1 |
| 18 | `cn-ca853b98ee` | 地佐辛 | Dezocine | N02AX | 9 / 9 | B1 |
| 19 | `cn-e5373190c8` | 丙戊酰胺 | Valpromide | N03AG | 3 / 3 | B1 |
| 20 | `cn-3c5b26497c` | 妥洛特罗 | Tulobuterol | R03AC | 11 / 11 | B1 |
| 21 | `cn-b546c4dccf` | 贝美格 | Bemegride | R07AB | 6 / 6 | B1 |

两条写法说明（不改、不猜）：
- `磺胺对甲氧嘧啶 → Sulphamethoxydiazine` 是 BAN 写法，INN 写法 `sulfametoxydiazine`；库内没有对应记录，按上游证据原样落库，不自行改写（本条已写进 CSV 的 `reason`）。
- `卡巴匹林钙`（`carbaspirin calcium` 是 USAN，INN 为 `carbasalate calcium`）**不在**改名清单里，卡点见 §6.2「候选写法存疑」。

### 6.2 B4 只留候选 37 条的卡点分类

| 卡点 | 条数 |
|---|---:|
| 盐型没落到 `variant.salt`（目标只有 base variant，或候选只给 base） | 20 |
| 酯型没落到 `variant.ester`（苯丙酸/苯甲酸/丙酸/乙酰/磷酸酯…） | 5 |
| 盐型＋酯型 | 1 |
| 盐型＋立体标记 | 1 |
| 候选多带酯（中文名没酯） | 1 |
| ATC 前 5 位不一致（`B01AF` vs `B01AB11`、`P01BF` vs `P01BE05`） | 2 |
| ATC 是复方码（`G03AA` vs `G03DC02`，dup-zh §3 C 类） | 1 |
| 候选是组分名（`silibinin A` ≠ 水飞蓟素） | 1 |
| 候选写法存疑（USAN `carbaspirin calcium`） | 1 |
| 候选是制剂名（`syrup of ipecac`） | 1 |
| 多成分复方（间苯二酚＋水杨酸） | 1 |
| 候选带立体标记（`(RS)-methoxyphenamine`） | 1 |
| 目标结构待清（`asunaprevir` 有 2 个 base variant） | 1 |
| **合计** | **37** |

### 6.3 B5 丢弃 1,722 条（判不了 1,719 + 政策不做 3）

| 类别 | 条数 | 处置 |
|---|---:|---|
| 无名字证据 | 1,459 | 本地没有任何「中文名→INN」证据（ATC5 组内英文成分为 0 或多个） |
| 仅 ATC4 唯一 | 114 | 中文名对不上，只留线索不当候选（46 个 `R05XX` 指向 `Guaiacol` 等） |
| 复方/多成分 | 99 | 按方案 §6 复方不做成分映射 |
| ATC 冲突 | 30 | 含 `曲安西龙`/`多黏菌素E甲磺酸钠`/`地喹氯铵`（dup-zh §3 C 类中的 3 组） |
| ATC 无法校验 | 8 | 候选在库但无 ATC |
| 盐/酯不一致 | 7 | 换了盐/酯 |
| 立体异构 | 2 | `右旋酮洛芬`/`右旋布洛芬`，库内无 dex 写法 |
| **个体 3 条** | 3 | `钠钾葡萄糖`/`醋酸钠葡萄糖`（low，复方原料名）、`碳酸钙D₃`（复方＋ATC 不一致，0 产品） |

复核命令：

```powershell
Import-Csv data\sources\phaseb-candidates-20261031.csv |
  Where-Object {$_.置信度 -eq 'none'} | ForEach-Object { $_.理由.Split('：')[0] } |
  Group-Object | Sort-Object Count -Descending | Format-Table Count,Name
```

### 6.4 15 组同名成分的最终处置（dup-zh 报告的三种类型）

| 组 | 类型 | 本计划处置 |
|---|---|---|
| 菠萝蛋白酶 / 苯溴马隆 / 碘化钾 / 甲芬那酸 / 环丙孕酮 / 氯米芬 / 氧化锌 / 对氨基水杨酸 / 丁溴东莨菪碱 / 灭菌注射用水 | A 语言写法（10 组） | `alias_link`，10 行已在 `data/substance_aliases.csv:L16–L25`，**不合并记录** |
| 甘露醇（`manitol` / `mannitol`） | B 拼写重复（1 组） | `merge_duplicate` → `mannitol`（B3-2，330 产品，最后做） |
| 炔诺酮 | C CJK-only 待核 | `candidate_only`（ATC `G03AA` 是复方码） |
| 曲安西龙 / 多黏菌素E甲磺酸钠 / 地喹氯铵 | C CJK-only 待核 | 留在 `drop`（1,719 条聚合内）——ATC 不一致，`dequalinium`/`decualinio` 两条候选也无法二选一，**不猜** |

另：`pizotifeno`（N02CX01）、`silibinina`（A05BA03）两条西语写法记录进 `alias_link`（B0 待加），与 A 类同一处理；
`pizotifen-malate` 的 `variant.salt` 为空（盐型写在主名里），属数据缺陷，**本轮不动**（见 §7 缺口 5）。

## 7. 缺口（写清，不藏）

1. **28 条候选卡在盐/酯口径**：其中 **27 条**是中文主名带盐酸/磷酸/钠/钙/酯，但源记录只有 1 个 base variant（`salt=''`、`ester=''`），另 **1 条**（甲地孕酮）是候选多带 `acetate`。改名会把盐/酯身份抹平，所以本计划一律 `candidate_only`。补法：单独窗口给目标成分建 `variant(salt=..., ester=..., base_fraction)`（需要产品级证据 + 换算基础），再走合并/改名。**这是 B4 里最大的一块。**
2. **1,719 条判不了**（其中 1,459 条连候选都没有）：不是阈值卡掉的，是本地确实没有。只能靠 Wikidata 在线批（1,791 条 × 2–3 s ≈ 60–90 min，见 `reports/task5-inn-mapping-plan.md` §4）或 CN 注册名人工补录。
3. **2 行异名待人工确认**：`pizotifeno`、`silibinina` 的出处是「ES/PT 入库写法 + ATC 同码」，没有 `source_id`（这两条记录 `substance.source_id` 为空），加行时 `source` 列建议写「ES/PT label（库内记录写法）」。
4. **合并后主名仍是西语写法**：`promestrieno`、`josamicina` 保留为西语。主名写法归一不在本轮（否则会把「合并」和「改名」绑在一次事务里，回滚粒度变粗）。
5. **`pizotifen-malate` 盐型记在 `inn_en`、`variant.salt` 为空**：`candidate_only`/不动，属名称清洗窗口的活。
6. **本计划不含任何「可替代」判断、剂量换算或服药建议**（AGENTS §1.3 / §9）。

## 8. 边界与复核

- 只读：DB 连接 `file:...?mode=ro`；未写 `data/drugs.db`、未改 `site/` `lib/` `docs/`、未 commit、未建站。
- 采集脚本（临时，`.tmp/` 不入库）：`.tmp/phaseb-plan/probe.py`（72 候选 + 15 组同名 + 库内现状）、`.tmp/phaseb-plan/merges.py`（12 对合并前后计数）、`.tmp/phaseb-plan/gen_plan.py`（生成 CSV，内含 5 条 `assert`）、`.tmp/phaseb-plan/tables.py`（本报告表格同源生成）。
- 生成 CSV 时的硬自检（`gen_plan.py` 全部通过才写出）：
  1. 池内 1,791 = 21 + 11 + 37 + 3 + 1,719；
  2. 72 条候选唯一分解，同一 substance 不重复；
  3. 21 条改名目标在库内归一化查重**全部 0 命中**（不会撞 `UNIQUE(inn_en)`）；
  4. 12 条合并都有 `merges.json` 计数（前后产品/组件/variant）；
  5. 37 条 `candidate_only` 都能对回 72 条候选。
- 复跑：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp/phaseb-plan/probe.py       # 只读 DB → .tmp/phaseb-plan/data.json
& $py .tmp/phaseb-plan/merges.py      # 只读 DB → .tmp/phaseb-plan/merges.json
& $py .tmp/phaseb-plan/gen_plan.py    # → data/sources/phaseb-merge-plan-20261107.csv（92 行）
& $py .tmp/phaseb-plan/tables.py      # → .tmp/phaseb-plan/tables.md（报告表格）
```

_本文件是只读执行计划：CSV 里每个动作都带出处和回滚方式，真正写库留给下一次 DB 窗口，逐条按 §3/§5 执行并签字验收。_
