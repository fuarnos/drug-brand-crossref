# 构建确定性：两次构建逐字节一致（task-14）

> 日期：2026-11-07（北京）｜状态：**只改 `site/build.py` + 新增 `deploy/check_build_determinism.py`**；未写默认 `site/dist`、未 commit、未发布、未改 `data/` `db/` `docs/`
> 起因：v0.9.7 发布时 gh-pages 有 112,692 个文件变化（+263,764/−264,361 行），v0.9.8 又出现 Pages 构建失败——但两版实际只改了少量代码。
> 基线：`site/dist` = 121,280 文件 / 885.6 MB（2026-11-06 13:38 构建，本次未改动）

## 0. 结论（先看这段）

| 指标 | 修复前（同一份代码 + 同一份数据，两次构建） | 修复后（不同进程 + 不同 `PYTHONHASHSEED` + 启动相差 56 秒） |
|---|---|---|
| 文件数 | 121,280 / 121,280 | 121,280 / 121,280 |
| 文件集合 | 完全相同（0 个只在单侧） | 完全相同 |
| 总字节 | 885,568,225 / 885,568,225 | 885,568,227 / 885,568,227 |
| **内容不同的文件** | **112,642（92.9%）** | **0** |
| sitemap URL | 63,351 | 63,351 |

**一句话根因**：112,642 个差异里 **112,533 个**只是 `<head>` 里的 `?v=<构建时刻秒级时间戳>` 变了（同一份 HTML，版本号不同）；剩下 **109 个名字页**是 `sorted(set, key=_sort_strength)` 在「5 mg / 5 mL」这类并列时退回 set 迭代顺序（随 `PYTHONHASHSEED` 变）。两处都修掉后，两个独立进程、不同哈希种子、启动相差 56 秒的构建 **121,280 个文件全部 SHA-256 相同**。

> 对照 Lead 的观察：gh-pages 的 112,692 与本次实测的 112,642 相差 50 个（与那两次发布的真实改动同量级）。**「发布 diff 11 万文件 / Pages 构建超时」的主因就是这个版本号。**

## 1. 证据 A：修复前的两次连续构建（A/B）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:SITE_OUT = "$PWD\.tmp\det\a"; & $py site/build.py      # 178.7 s，121,280 文件 / 885.6 MB
$env:SITE_OUT = "$PWD\.tmp\det\b"; & $py site/build.py      # 178.7 s，同一份代码与数据
& $py deploy/check_build_determinism.py .tmp/det/a .tmp/det/b
```

| 页面族 | 文件数 | 内容不同 | A 侧字节 |
|---|---:|---:|---:|
| name | 77,058 | 77,058 | 317,913,110 |
| maker | 15,213 | 15,213 | 138,345,485 |
| drug | 12,431 | 12,431 | 148,679,601 |
| combo | 15,190 | 6,735 | 50,756,382 |
| atc | 1,154 | 1,154 | 16,294,411 |
| cat | 16 | 16 | 737,873 |
| top-html（根页） | 9 | 9 | 595,556 |
| es / zh / zh-hant 副本 | 7+7+7 | 21 | 1,694,368 |
| assets | 6 | 2（app.js、atc4.js） | 136,936 |
| data/idx | 163 | 1（manifest.json） | 34,873 |
| top-txt | 3 | 1（checksums.txt） | 641 |
| top-json | 1 | 1（datapackage.json） | 21,210 |
| top-jsonld / 其它（data 11、nojekyll、docs、xml） | 15 | 0 | 0 |
| **合计** | **121,280** | **112,642** | **675,210,446** |

第一处差异（两次构建启动相差 5 秒，版本号差 3）：

```text
404.html    L6: ...assets/i18n.js?v=1794003530  ||  ...assets/i18n.js?v=1794003533
about.html  L20: assets/style.css?v=1794003530  ||  assets/style.css?v=1794003533
assets/app.js L899: data/idx/pinyin.json?v=1794003530 || ...?v=1794003533
```

文件集合与总字节完全一致 → 这不是数据变化，而是**同一份内容的版本号不同**。

## 2. 证据 B：时间戳修掉后还剩 109 个名字页（C/D 第一轮）

把 4 处「构建时刻」改成内容哈希后重跑两次（`PYTHONHASHSEED=1` vs `=2`）：

```text
内容不同: 109（占共有 0.1%）   ← 全部落在 name 族
差异样例：name/aclasta.html L11: 5 mg、5 mL  ||  5 mL、5 mg
         name/atropine.html L11: 1 %、1 mg、10 mg  ||  1 mg、1 %、10 mg
```

根因：`sorted(g['s'], key=_sort_strength)` 的键只有数值 —— `5 mg` 与 `5 mL` 都是 5.0，**并列**；`sorted` 是稳定排序，并列项就按输入顺序（`g['s']` 是 `set`）→ 受哈希种子影响。

## 3. 根因清单（4 处时间戳 + 1 处 set 排序）

| # | 位置（修复前行号） | 旧写法 | 实测影响 |
|---:|---|---|---|
| 1 | `site/build.py:49` | `BUILD_V = str(int(time.time()))` | **112,642 个文件**：每页 `<head>` 的 `assets/*.js?v=`、`style.css?v=`（`page()` 5904/5913、`build_404`、`_optimize_home_html`、atc4、app.js 里 3 处 data `?v=`） |
| 2 | `site/build.py:9957` | `manifest = {"v": int(time.time()), ...}` | `data/idx/manifest.json`（分片版本号） |
| 3 | `site/build.py:9654` | `"created": time.strftime("%Y-%m-%dT%H:%M:%SZ", ...)` | `datapackage.json` + 经 `checksums.txt` 的 sha256 级联 1 个 = 2 个文件 |
| 4 | `site/build.py:9676` | `"dateModified": time.strftime("%Y-%m-%d", ...)` | `dataset.jsonld`（同日稳定，跨天构建会变——潜伏项） |
| 5 | `site/build.py:7426` | `sorted(g['s'], key=_sort_strength)` | 109 个名字页的规格列表顺序（唯一一处真正的 set 顺序泄漏） |

排查过的其它位置（**确认无问题**，不用改）：`g['country']`/`g['f']`/`g['rel']`/`d['countries']`/`a['c']`/`a['atc']`/`a['sids']`/`spec_raws` 全部是 `sorted()` 全序；maker 的 `sids`、combo 的 `groups`、atc 的 `sorted(groups[ln].items())`、`categories.json` 的 `sorted(all_codes)`、拼音 token 的 `sorted(toks.items())`、sitemap 的 `urls.sort()` 都在输出前排序；`next(iter(set))` 只出现在 `len(sids)==1` 的分支（唯一元素，安全）。

## 4. 修法（只改 `site/build.py`）

### 4.1 版本号 = 输入内容哈希，不是时间（`site/build.py:53/78/10040`）

```python
def _sha1_inputs(*paths: Path) -> str: ...        # 名字+内容 串起来做 sha1，缺文件用占位符

def _compute_build_v() -> str:
    """构建版本号 = 静态资源源码的内容哈希（task-14，替代 time.time()）。"""
    digest = _sha1_inputs(Path(__file__).resolve(), ZH_HANT_I18N_FILE, ZH_HANT_T2S_FILE)
    # 8 位十六进制转十进制定宽 10 位：与旧时间戳同宽，dist 体积不变
    return f"{int(digest[:8], 16):010d}"

def main() -> None:
    global BUILD_V
    BUILD_V = _compute_build_v()        # 写任何产物之前定下来
    print(f"build version: {BUILD_V} (content hash)", flush=True)
```

三条设计约束：

1. **不含数据库**：数据更新是最常见的一类发布，不该让 12 万页的 `?v=` 全变。资源缓存 TTL（GitHub Pages 10 分钟）与 HTML 同量级，数据新鲜度不受影响；只要改 CSS/JS/模板/字典（都在 `build.py` 或 `data/i18n_zh_hant.json`、`data/zh_hant_t2s.json` 里）才换号。
2. **10 位十进制**：`deploy/verify_live.py:187` 用 `assets/app\.js\?v=\d+` 校验线上；宽度与旧时间戳一致（10 位）→ dist 总体积不变（实测 +2 B，见 §5）。
3. **打一行 `build version: ...`**：发布时能一眼核对「这次构建用的是哪个版本号」。

### 4.2 分片 manifest 跟 BUILD_V 走（`site/build.py:10001`）

```python
manifest = {"v": BUILD_V, "n": len(entries), ...}   # 客户端只拿它拼 ?v=，不解析内容
```

### 4.3 数据包时间戳改用 CHANGELOG 的发布日期（`site/build.py:9696/9718`）

```python
pkg_date = LATEST_DATE or time.strftime("%Y-%m-%d", time.gmtime())
... "created": f"{pkg_date}T00:00:00Z",      # 原来是构建时刻（精确到秒）
... "dateModified": pkg_date,                # 原来是构建当天
```

同一次发布的所有构建共用同一个日期；`checksums.txt` 里 `datapackage.json` 的哈希也随之稳定。

### 4.4 规格排序补全序键（`site/build.py:7457`）

```python
strengths = '、'.join(sorted(g['s'], key=lambda s: (_sort_strength(s), s)))
#                                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# 数值相同时按原串码点兜底：默认排序 + 稳定排序 → 结果与 PYTHONHASHSEED 无关
```

## 5. 验证（全部实跑）

| 项 | 命令 | 结果 |
|---|---|---|
| **两次构建逐字节一致** | `check_build_determinism.py .tmp/det/c .tmp/det/d` | **121,280 个文件，0 差异**；两侧 885,568,227 B；`PYTHONHASHSEED=1` vs `2`、启动相差 56 秒、两个独立进程 |
| 与现网产物正文一致 | `check_build_determinism.py .tmp/det/c --against site/dist --sample 200` | 200/200 一致（忽略 `?v=`），差集为空 |
| 改动是否只动版本号 | `check_build_determinism.py .tmp/det/c --against .tmp/det/a --sample 2000` | 2,000/2,000 一致 |
| CI 门槛 | `python deploy/ci_checks.py --fast` | **8 项：PASS 6 / SKIP 2 / FAIL 0**（28.2 s） |
| hash 清单模式（CI 用） | `--write-manifest` / `--check-manifest` | atc 目录 1,154 文件，缺 0 / 多 0 / 不同 0 |
| 体积与页数 | 构建日志 | 121,280 文件 / 885.6 MB / sitemap 63,351 URL / core.json 41.4 MB，与修复前一致 |

产物体积变化：**+2 字节**（`data/idx/manifest.json` 的 `"v":1794003530` → `"v":"3511751054"`，多了两个引号）。页面正文与索引 `core.json`（41,382,193 B）逐字节未变。

## 6. 对发布 diff 的影响（预估）

| 发布类型 | 修复前 | 修复后 |
|---|---|---|
| 无改动重建（验证用） | 112,642 个文件 | **0** |
| 只更新数据（DB 入库） | 112,642 个文件 | 只有真正变化的页面/索引文件（数百~数千量级） |
| 改 CSS/JS/模板/字典 | 112,642 个文件 | 仍约 112k，但每页只差 2–4 行 `?v=`（这是「资源真的换了」时该有的行为） |

为什么第三类还会全站动：`?v=` 写在每一页的 `<head>` 里，只要资源版本变了，页面字节就变。要把它也压掉有两条路（都会动发布流程，建议**另开任务**）：

1. 把 `?v=` 从 HTML 里拿掉，只靠 GitHub Pages 的 10 分钟 TTL —— 代价：UI 发布后最多 10 分钟内可能「新 HTML + 旧 CSS」；
2. 资源改成文件名指纹（`style.<hash>.css`）+ `publish.ps1` 保留上一版指纹文件 —— 代价：gh-pages 体积 + 发布逻辑改动。

对 Pages 构建的意义：**数据发布不再产生 11 万文件 diff**，v0.9.7/v0.9.8 那种「只改一点代码却触发 11 万文件、Pages 反复超时」的情况不会再现；UI 发布的 diff 也回到「每页 2–4 行版本号」。

## 7. 边界与已知项

- 只改 `site/build.py`（5 组改动：版本号、manifest、两处数据包时间戳、规格排序）+ 新增 `deploy/check_build_determinism.py`；`site/dist` 未被写入（LastWriteTime 仍是 13:38），`data/` `db/` `docs/` 未动，未 commit、未发布。
- 不改内容语义与文案：抽样 2,000 页正文一致；`?v=` 仍是同一个值贯穿全站；唯一可见变化是 109 个名字页里「同数值不同单位」的规格顺序被固定为码点序（任务允许的顺序变化）。
- 兜底：`pkg_date` / sitemap `lastmod` 在 CHANGELOG 缺日期时才用 `time.strftime("%Y-%m-%d")`（同日稳定，跨天才会变 1 个文件）。
- `deploy/publish.ps1` 自己也用时间戳拼缓存穿透 URL（`?v=<now>`），那是发布动作的临时 URL，不写进产物，无需改。
- 未跑：全量 `ci_checks`（含 trilingual，约 10 分钟）留给发布前那一轮；本次 `--fast` 已 6 PASS。

## 8. 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 修复后：两次构建（不同进程 + 不同哈希种子）
$env:PYTHONHASHSEED='1'; $env:SITE_OUT="$PWD\.tmp\det\c"; & $py site/build.py
$env:PYTHONHASHSEED='2'; $env:SITE_OUT="$PWD\.tmp\det\d"; & $py site/build.py
& $py deploy/check_build_determinism.py .tmp/det/c .tmp/det/d     # 期望：内容不同 0

# 与现网产物比正文（忽略 ?v=）
& $py deploy/check_build_determinism.py .tmp/det/c --against site/dist --sample 200

# CI 用：产物 hash 清单
& $py deploy/check_build_determinism.py .tmp/det/c --write-manifest .tmp/dist.sha256
& $py deploy/check_build_determinism.py .tmp/det/d --check-manifest .tmp/dist.sha256

& $py deploy/ci_checks.py --fast
```

_本次只做「让构建可复现」：产物内容、页数、体积、文案都没动；发布与 commit 留给人。_
