# L1：韩语（ko）接入为第 6 界面语言（KR 市场不做）

> 状态：**全键翻译表已出**（`.tmp/ko_i18n.py`，667 键，硬校验全过），**尚未并进 `site/build.py`**
> ——按 Lead 纪律等「v0.13.7 tag 已打」后再合并。本文件先记录口径与校验结果，合并 + 构建后再补
> ④ 的截图 / 首屏 / i18n_check 实测。

## 1. 结论先行

| 项 | 结果 |
|---|---|
| 键集 | **667 / 667**，与构建期 `I18N["en"]` 完全一致（不多不少） |
| 占位符 | 逐键一致（`{n}` / `{shown}` / `{u}` / `{k}` / `{url}` / `{code}` / `{total}` / `{m}` / `{q}` / `@@X@@`） |
| HTML 标签序列 | 逐键一致（`data-i18n-html` 的正文块结构不会错位） |
| 空值 | 0 |
| 伪翻译（与 en 完全相同） | 0（19 个专名/单位/缩写键登记为允许同形） |
| 谚文覆盖 | 除登记键外，每条都含한글 |
| 产物 | `.tmp/ko_i18n.py`（61,490 字节，扁平表 `KO_I18N: dict[str, str]`） |

## 2. 怎么做的（可复核）

1. **键集来源不是抄来的清单**：用 `deploy/i18n_check.py` 的 `load_build_i18n()` + `effective_i18n()`
   复刻构建期合并顺序，得到 `I18N["en"]` 的 **667 键**（与 `deploy/i18n_check.py` 打印的
   「有效字典 en 667 键」一致），导出为 `.tmp/en_all.json` 并按 60 键切成 12 批（`.tmp/ko_batch/bNN.json`）。
2. 逐批翻译成 `.tmp/ko_batch/bNN.ko.json`（12 个文件，键 = 同一个英文键）。
3. `.tmp/ko_assemble.py` 合成 + 硬校验，**任一校验不过就非 0 退出、不写产物**：
   键集一致 / 占位符一致 / HTML 标签序列一致 / 无空值 / 无伪翻译 / 有谚文。
4. 翻译口径（与仓库既有做法一致）：
   - **不新造药名/市场名**：商品名与 INN 一律保留原文；国家/地区用韩语通用名（미국·영국·중국·대만…），
     与 `data/markets.json` 的既有五语表不冲突（韩语原本没有该字段，属新增语言的自然译名）。
   - **红线句一致**：`about.rules` 第三条与 `warn.intro` / `warn.no_advice` / `footer` 都明确写
     「복약 조언은 하지 않습니다（不给用药建议）」「용량 환산·대체 추천 없음（不做剂量换算/替代推荐）」
     「호환되지 않습니다（不可互换）」，不引入任何用药建议。
   - **许可/出处段照实翻译**：`about.*_source` 里的 CC BY / OGL / SODL / etalab 等许可名、
     机构缩写（SÚKL、ZVA、TFDA、HSA、AEMPS、COFEPRIS、NHSA）与英文/中文原名保留，
     只翻译说明性文字，便于日后引用条文核对。
   - **长段落保留占位符与统计位**：`about.stats` / `about.gaps` / `warn.count` 的 `@@PRODUCTS@@`
     等由构建期替换，韩语侧位置与英文一一对应。

## 3. 合并清单（已做成**可直接执行的补丁** `.tmp/ko_merge.py`，镜像目录里预演通过）

补丁覆盖五处（每个替换点都要求「锚点恰好出现一次」，否则整体失败、**一个文件都不写**）：

| # | 文件 | 改动 |
|---|---|---|
| ① | `site/build.py` | 插入 `KO_I18N: dict[str, str]`（667 键，扁平表，同 `FR_I18N` 形状） |
| ② | `site/build.py` | `_merge_static_i18n()` 生成 `I18N["ko"]`（键集与 en 相同，缺键才回落英文） |
| ③ | `site/build.py` | `LANG_NATIVE_LABELS` 加 `"ko": "한국어"`；`_enabled_ui_langs()` 加 `("ko","한국어","ko/")` → 语言菜单 / `LANGS` / `LANG_PATH` / hreflang / canonical 自动带上 |
| ④ | `data/languages.json` | 注册 ko：`native_name=한국어`、`ui_label=KO`、`hreflang=ko`、`path=ko/`、`script=hangul`、`enabled:true`、`order=65`、`default_country:null`（**不加 KR 市场**） |
| ⑤ | `deploy/i18n_check.py` | `LANGS` 加 `ko`；新增 `KO_FLAT_TABLES` / `FLAT_LANGS`，把 `load_fr_flat`/`normalize_fr` 泛化成 `load_flat_tables(names)`/`normalize_flat(lang)`（旧名保留为薄包装，向后兼容）；`effective_i18n(..., ko_flat)`；`check_dicts` 的 fr 分支改成「扁平表语言」分支；`PSEUDO_OK_KEYS_KO` 白名单；`RELEASE_LATE_LANGS` 加 `ko: v0.13.8`，并把「后加语言」判定从「不是最新版」改成 **`_ver_key(ver) < _ver_key(登记版本)`** —— 否则最新版还是 v0.13.7 时会因为「缺 ko」误报 FAIL |

**用法**（等 Lead 通知「v0.13.7 tag 已打」后执行）：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\ko_merge.py --dry-run     # 只校验 22 个锚点 + 生成内容，不写文件
& $py .tmp\ko_merge.py               # 真正打补丁（三个文件）
& $py deploy/i18n_check.py           # 目标：FAIL 0
```

**镜像预演结果**（`.tmp/merge_test/` 是仓库镜像，只拷 `build.py` + `i18n_check.py` + i18n_check 需要的 5 个数据文件 + CHANGELOG）：

```
== i18n 一致性门禁（en / es / zh / zh-Hant / fr / ko）==
有效字典: en 667 / es 667 / zh 667 / zh-Hant 667 / fr 667 / ko 667
release notes: 最新 v0.13.7 译文齐；硬编码文案 0 处
FAIL 0 / WARN 2（仅存量 es form.kit / form.gas 白名单告警）
```

再导入补丁后的 `build.py` 验证语言注册：

```
LANGS: [..., ('fr','Français','fr/'), ('ko','한국어','ko/')]
LANG_NATIVE_LABELS['ko'] = 한국어      LANG_PATH['ko'] = 'ko/'
KO_I18N 键数 = 667
```

（镜像里 `SHELL 市场数 = 0` 是因为只拷了 5 个数据文件、没拷 `data/markets.json`；真实仓库现查仍是 **15**。）

## 4. 待补验收（合并后填写）

- [ ] `deploy/i18n_check.py` FAIL 0（六语键集一致、无伪翻译、ko 覆盖率 ≥ fr 水平）
- [ ] `/ko/` 首页 / 结果 / 成分 / 覆盖 各 1 张截图（`docs/img/ko-*.png`）
- [ ] `first_screen_check` ko 四档（390/768/1440/2560）不退化
- [ ] 市场数仍 **15**、`product` 计数不变（不碰库）
- [ ] 构建 `== done ==`，产物只在 `.tmp/`，`site/dist` 未写

## 5. 一句话交接

改了什么：把 667 个界面文案键全部翻成韩语，做成可直接并入 `site/build.py` 的扁平表 `.tmp/ko_i18n.py`。
怎么验的：键集/占位符/HTML 标签/空值/伪翻译/谚文六项硬校验全过（667/667）。
还剩什么：按纪律还没动 `site/build.py`、`data/languages.json`、`deploy/i18n_check.py` ——
等「v0.13.7 tag 已打」后合并 + 构建 + 补 §4 的四项实测。
