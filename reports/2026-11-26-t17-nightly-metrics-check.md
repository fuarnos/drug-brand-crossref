# T17 核查：`db/nightly_metrics.py` sitemap 指标（误报关闭 + 两条真遗留）

- 日期：2026-11-26（北京，谷段）
- 工位：backend（任务 `task-5` A 段，Lead 2026-11-26 缩水改派）
- 结论：**T17 不成立，关闭；未改任何脚本、未写库、未建站**。附带登记两条真问题（已由 Lead 登记为 **T20**）。

## 1 结论（先行，3 行）

1. **T17 是误报**：`db/nightly_metrics.py` L221–236 早在 **v1.2.3（commit `ec9e3981993`）** 就适配了 sitemap 索引——`<sitemapindex` → 逐分片 `<url>` 求和，单文件 `<urlset>` 走旧分支；口径（sitemap URL 总数）未变。
2. **实跑复核通过**：`pages.sitemap_urls = **230,435**`（v1.2.5 现数），**没有**「sitemap URL 数下降」告警。
3. **release 三次报的根因**：照抄旧报告（`reports/2026-11-25-v123-sitemap-gates.md:90` → v1.2.4 → v1.2.5）而未复核；同一批 v1.2.3 报告里的 `reports/2026-11-25-v123-sitemap-index.md` §2.5 其实已写明「已适配」。**不改代码即可关闭。**

## 2 核实证据（命令 + 输出）

### 2.1 代码现状（HEAD = 线上源码 = v1.2.5 收尾后）

```powershell
& .\tools\git\cmd\git.exe log --oneline -S '<sitemapindex' -- db/nightly_metrics.py
# ec9e3981993 v1.2.3: sitemap 索引拆分（4 片）+ 静态页软上限 150k 分档告警 + CHANGELOG/九语 notes

& .\tools\git\cmd\git.exe status --short db/nightly_metrics.py     # 输出为空：工作树与 HEAD 一致
```

代码块（`db/nightly_metrics.py:221-236`，HEAD）：

```python
sitemap_urls = 0
sm = dist / "sitemap.xml"
if sm.is_file():
    sm_text = sm.read_text(encoding="utf-8", errors="replace")
    if "<sitemapindex" in sm_text:
        # v1.2.3 起 sitemap.xml 是索引（分片 sitemap-N.xml，每片 ≤50,000）：
        # URL 总数 = 各分片 <url> 求和，口径与旧单文件一致，避免夜间指标误报「下跌」。
        for ref in re.findall(r"<loc>\s*(.*?)\s*</loc>", sm_text, re.S):
            name = ref.rsplit("/", 1)[-1]
            shard = dist / name
            if shard.is_file():
                sitemap_urls += shard.read_text(
                    encoding="utf-8", errors="replace").count("<url>")
    else:
        sitemap_urls = sm_text.count("<url>")
pages["sitemap_urls"] = sitemap_urls
```

release 报的单据是「第 221–224 行只数单文件 `<url>`」——那 4 行是**这个块的开头**（`sitemap_urls = 0` / `sm = ...` / `if sm.is_file():` / `sm_text = ...`），索引分支在第 225 行之后，读到第 4 行就下了结论。

### 2.2 现查 dist 形态（v1.2.5 产物）

```powershell
Get-ChildItem site\dist\sitemap*.xml | Select-Object Name,Length
# sitemap.xml 622 B（索引）；sitemap-1..5.xml
# 各分片 <url> 计数：50,000 / 50,000 / 50,000 / 50,000 / 30,435 → 合计 230,435
```

`sitemap.xml` 里 5 条 `<loc>` 是绝对地址（`https://drugcrossref.com/sitemap-N.xml`），脚本用 `rsplit("/",1)[-1]` 取文件名再拼 `dist/`，本地能命中。

### 2.3 实跑（**写 `.tmp`，没写 `reports/metrics/`**）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py db/nightly_metrics.py --out-dir .tmp\t17
```

输出（UTF-8 终端，摘录）：

```
== 夜间指标 2026-11-25（121.27s）==
  产品 731,078 | 成分 16,550 | ATC 41.48% | severe 37,933 | 重复成分 16 对
  页面 361,305 HTML / 362,112 文件 | sitemap 230,435 | 首搜 0.25 MB gz | 首屏 365,966 B gz
  上一份: （无，本次为基线）

  WARNINGS（2）:
   - data/index.json 缺失或为 0 字节（站点构建不完整？）
   - 未找到 2026-11-25 之前的指标文件；本次为基线快照

写入: .tmp\t17\2026-11-25.json
```

- **sitemap 230,435** ✅，与 v1.2.5 发布报告 §3c / `verify_live sitemap-urls` 的 230,435 一致。
- 第 1 条 warning 是**真问题**（见 §3.2）；第 2 条是因为 `--out-dir` 指到空目录（**不是**「没跑过」的证据，`reports/metrics/` 的情况见 §3.1）。
- 为什么没有「下降」告警：`RULES` 里 `pages.sitemap_urls` 是 `drop_pct`；只要有上一份基线且数不跌就不报。假设解析真的失败（读成 0），才会出现 `prev 62,057 → 0（-100%，阈值 1%）`——本次没有发生。

> 说明：Lead 已指示「不要再跑以免生成快照」。本次跑在收到指示**之前**、且 `--out-dir` 指向 `.tmp\t17`（gitignore），`reports/metrics/` 里没有任何新文件；`reports/metrics/2026-11-25.json` 若存在只可能是 Lead 那次跑的，与本工位无关。

### 2.4 兼容老形态（单文件 urlset）

老分支是 `else: sitemap_urls = sm_text.count("<url>")`——v1.2.2 及以前的产物就是单文件 `<urlset>`（`reports/2026-11-25-v123-sitemap-index.md`：单文件 170,435 URL）。该分支自 v1.2.3 起未改动、也没有被本次改动触及，逻辑与 `deploy/verify_live.py:530` 的旧单文件分支同构（`findall("<loc>")`），因此**不需要额外造样本重测**；本次没有改脚本，也就不存在「新代码在老形态上跑不通」的风险。

## 3 两条真遗留（已由 Lead 登记 T20；本工位只记录，不动实现）

### 3.1 「夜间」指标一个月没跑

```powershell
Get-ChildItem reports\metrics | Sort-Object Name
# 2026-10-27.json / 2026-10-29.json / goatcounter-2026-10-29.json / goatcounter-2026-11-11.json
```

- 最新快照 **2026-10-29**，距今 **27 天**；仓库里没有任何 cron / scheduled task 引用 `nightly_metrics`（`grep nightly_metrics` 命中只有文档、报告与脚本自身）。
- 后果：本次（以及 Lead 那次）实跑都是「和一个月前的基线比」，出来的下降类告警属于**内容增长**（ATC 覆盖率、severe 碰撞数、core 体积等），不是回归。
- 待定（T20）：指标在哪跑（**不许新建 cron**：可放每日收尾并提交快照，或明确「按需跑」）；**基线断档 >7 天时降级为「首次基线」不报下降**。

### 3.2 `data/index.json` 指标已过时（恒告警）

```powershell
Test-Path site\dist\data\index.json        # False
(Get-Item site\dist\data\idx\core.json).Length      # 67,963,821
```

- `db/nightly_metrics.py:244` 仍在看 `data/index.json`，`:405-409` 缺失就报警；但 **v0.6.1 起默认不再写 `data/index.json`**（`site/build.py:22819-22824`，要 `WRITE_LEGACY_INDEX=1` 才写），`deploy/verify_live.py:417-423` 也已把它的 404 当预期。
- 唯一索引实际是 `site/dist/data/idx/core.json`：**67,963,821 B raw / 13,321,117 B gzip-9**（本次现查，与 AGENTS §6 / v1.2.5 报告一致）。
- 待定（T20）：把 `index_gz` 预检改为「core（未来是 `core-*.json` 分片）存在且非 0」或直接删掉这条；**T10 落地时必须一起改**（见 `reports/2026-11-26-t10-index-sharding-design.md` §5）。

### 3.3 附带发现（无害，记录备查）

- `RULES` 里同时有 `("sitemap.urls", ...)`（`:66`）和 `("pages.sitemap_urls", ...)`（`:70`）；实际指标键是 `pages.sitemap_urls`，第一条是**死规则**（`fnmatch` 永不命中），文件头 docstring `:25` 也写成 `sitemap.urls`。不影响数字，改的时候一并删掉即可。
- 分片 `<loc>` 若改成 `.xml.gz` 或带查询串，`rsplit("/",1)[-1]` + `.count("<url>")` 会读不到（当前产物是纯 `.xml`，无风险）。

## 4 改了什么 / 怎么验的 / 还剩什么

- **改了什么**：无（未改 `db/nightly_metrics.py`、未改任何脚本/数据/产物；本报告为唯一产出）。
- **怎么验的**：`git log -S` 定位适配提交 → 读 HEAD 代码 → 现查 dist sitemap 索引/分片计数 → 实跑（`.tmp` 出参）核对 230,435 与告警面。
- **回滚**：无需回滚（零代码改动）；`.tmp\t17\` 可随时删除。
- **还剩**：T20 两条（跑法 + 过时指标）待排期；T10 分片方案见另一份报告。
