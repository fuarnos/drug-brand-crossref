# core 索引字段守卫（P0-1 防回归）：`deploy/check_core_fields.py`

> 工位：search-alias · task-10 · 2026-11-12
> 上游：[reports/2026-11-12-p0-1-index-fields.md](2026-11-12-p0-1-index-fields.md)（P0-1 根因定位）
> 本轮**只加独立守卫脚本**，未接 CI、未改 `deploy/ci_checks.py`、未改 `site/build.py`、未写 `site/dist`。

---

## 0. 结论先行

1. 新增 `deploy/check_core_fields.py`（只读，5 项检查，PASS 退出 0 / FAIL 退出 1，`--json` 落盘）。
2. **对旧产物 `site/dist`（v0.11.1，缺 3 列）→ FAIL，exit 1**，3 项未过，逐条指出 `缺 ['t', 'nc', 'eo']`。
3. **对真实 v0.11.2 产物 `.tmp/v0112-build` → PASS，exit 0**：28 列、`t==1` 166,846（85.0%）、gzip 9.801 MB、109 个分片字段全被覆盖。
4. 四个反向对照（丢 `t` / `t` 全 0 / 列截断 / 产物缺失）全部按预期 FAIL —— 守卫不是「只会盖章」。
5. 接入 `ci_checks.py` 的 diff 见 §6，**本轮不落地**（发布窗口冻结），发布后由 Lead 决定。

---

## 1. 脚本与用法

`deploy/check_core_fields.py`（只读；只读 `core.json` / `manifest.json` / `shard-*.json`）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 默认查 site/dist
& $py deploy/check_core_fields.py

# 2) 查待发布产物（发布前预检）
& $py deploy/check_core_fields.py --dist .tmp\v0112-build

# 3) 直接指定 core.json（manifest / 分片按同目录推断）
& $py deploy/check_core_fields.py --core .tmp\v0112-build\data\idx\core.json

# 4) 落 JSON 摘要（报告 / CI artifact）
& $py deploy/check_core_fields.py --dist site/dist --json .tmp\ci\core-fields.json

# 5) 慢机器先看字段（跳过 gzip 与分片，约 0.5 s）
& $py deploy/check_core_fields.py --no-gzip --no-shards
```

退出码：`0` = PASS，`1` = FAIL（含产物不存在 / 无法解析）。
`--sample`（默认 200）、`--seed`（默认 20261112）控制抽样规模与可复现性。

---

## 2. 五项检查与阈值

| 检查 | 断言 | 阈值 / 依据 | 失败即代表 |
|---|---|---|---|
| `shape` | `n>0`、`cols.k` 长度 = `n`、`t/nc/eo` 列长度 = `n` | 精确相等 | 产物被截断 / 编码器写歪 |
| `required-cols` | `cols` 含 `t`、`nc`、`eo` | 三列必须都在 | **P0-1 正题**：客户端 `decodeCore` 后为 `undefined` |
| `values` | `t/nc/eo` 取值 ⊂ {0,1}；`t==1` 比例 85%±5%；抽样 200 条无空值、抽样 `t==1` 70%–95% | v0.11.2 实测 166,846/196,200 = 85.04%；绝对区间 **[158,432, 175,108]** | 列在但整体错位（如全 0） |
| `gzip-size` | `gzip -9` ∈ 2.5–12 MB | 与发布门槛同一护栏：主域 R2 的 `verify_live.py`、备份通道 `publish.ps1` | 索引悄悄膨胀 / 护栏失效 |
| `shard-coverage` | 分片条目字段集 ⊆ core 列集（除 `q` 稀疏、`dp` core 独有）；分片行数合计 = `core.n` | 根因级：**不针对具体字段名** | 下一次「写入侧加字段、读取侧忘同步」 |

两个实现细节值得记一笔：

- **`t==1` 用比例不是绝对值**：任务写的是「约 166k±5%」，实现为 `85%±5%` 再换算成绝对区间。
  这样新市场入库把 `n` 推高时不会误报，而 v0.11.2 的 166,846 正好落在区间正中。
- **`col_values()` 通用读列**：普通列（`[1,0,…]`）和字典列（`{"d":…,"i":…}`）都能读。
  即使将来有人把 `t` 改成字典编码，守卫也不会自己变成「两套映射」的新源头。

---

## 3. 实测：旧产物 FAIL / v0.11.2 PASS

### 3.1 旧产物 `site/dist`（v0.11.1，缺 3 列）→ **FAIL，exit 1**

```
core 索引字段守卫 · ...\site\dist\data\idx\core.json
  [OK  ] shape           n=196,200，cols.k 长度一致（25 列）  (0 ms)
  [FAIL] required-cols   core.cols 缺 ['t', 'nc', 'eo']（客户端 decodeCore 后为 undefined → 渲染错位）  (0 ms)
  [FAIL] values          t: 列缺失；nc: 列缺失；eo: 列缺失  (0 ms)
  [OK  ] gzip-size       gzip -9 9.773 MB（raw 41.62 MB），护栏 2.5–12.0 MB  (4434 ms)
  [FAIL] shard-coverage  分片有、core 没有的字段：['eo', 'nc', 't']（core 会缺列 → 客户端渲染错位）  (1330 ms)

行数 196,200 · 列 25 · raw 41.62 MB · t==1 n/a（列缺失） · 5 项检查 · 6.23 s
== FAIL ==（3 项未过：['required-cols', 'values', 'shard-coverage']）
```

### 3.2 真实 v0.11.2 产物 `.tmp/v0112-build` → **PASS，exit 0**

（`build_version=0477923035`，构建于 2026-11-11 09:34）

```
  [OK  ] shape           n=196,200，cols.k 长度一致（28 列）  (0 ms)
  [OK  ] required-cols   core.cols 含 ['t', 'nc', 'eo']  (0 ms)
  [OK  ] values          t==1 166,846/196,200 = 85.0%（区间 80.8%–89.2%）；抽样 200 条无空值、t==1 84.0%  (21 ms)
  [OK  ] gzip-size       gzip -9 9.801 MB（raw 42.80 MB），护栏 2.5–12.0 MB  (4835 ms)
  [OK  ] shard-coverage  109 个分片的 28 个字段全被 core 覆盖；行数 196,200 与 core.n 一致  (1415 ms)

行数 196,200 · 列 28 · raw 42.80 MB · t==1 166,846 · 5 项检查 · 6.93 s
== PASS ==
```

### 3.3 逐项对照

| 项 | 旧产物 v0.11.1 | 新产物 v0.11.2 | 判定 |
|---|---|---|---|
| `cols` 数 | 25 | **28**（+t/nc/eo） | 由缺到齐 |
| `required-cols` | ✗ 缺 3 列 | ✓ | **FAIL → PASS** |
| `t==1` | n/a（列缺失） | 166,846 / 196,200 = 85.04%（区间 158,432–175,108） | 居中 |
| `nc==1` / `eo==1` | n/a | 3,023 / 2,292 | 与 P0-1 报告一致 |
| raw / gzip -9 | 41.62 MB / 9.773 MB | 42.80 MB / **9.801 MB** | +1.18 MB raw / +28 KB gz，护栏内 |
| `shard-coverage` | ✗ 缺 `['eo','nc','t']` | ✓ 28/28 字段、196,200 行 | **FAIL → PASS** |
| 退出码 | **1** | **0** | 闸门有效 |

---

## 4. 反向对照（守卫能不能真的抓住回归）

在 `.tmp/guard-fixture`（= 旧 core 补三列的等价夹具，用 `os.link` 硬链接 109 个分片，不额外占盘）上就地改造：

| # | 构造 | 期望 | 实测 |
|---|---|---|---|
| A | 只删 `t`（模拟「修了一半」） | FAIL | `[FAIL] required-cols 缺 ['t']` + `[FAIL] values t: 列缺失` → exit 1 ✓ |
| B | `t` 列存在但全 0（列在、值错） | FAIL | `[FAIL] values t==1 比例 0.0% 超出 80.8%–89.2%` → exit 1 ✓ |
| C | 截断 `cols.k` 100 行（产物被裁） | FAIL | `[FAIL] shape cols.k 长度 196,100 ≠ n 196,200` → exit 1 ✓ |
| D | `--dist .tmp\nonexistent` | FAIL | `! core.json 不存在` → exit 1 ✓ |
| E | 夹具（三列齐全） | PASS | 5 项全过 → exit 0 ✓（gzip 9.796 MB） |

C 尤其说明问题：**只查 `t/nc/eo` 三个名字是不够的**，列截断这类错误只有 `shape` / `shard-coverage` 能兜住。

### 4.1 夹具与真实产物的一致性

| | 夹具 `guard-fixture` | 真实 `.tmp/v0112-build` |
|---|---|---|
| `raw_bytes` | 42,801,654 | **42,801,654（逐字节同长）** |
| gzip -9 | 9,795,595（9.796 MB） | 9,801,041（9.801 MB） |
| `t==1` | 166,846 | 166,846 |

原始体积完全相同，gzip 差 5.4 KB —— 因为夹具把三列**追加在 `cols` 末尾**，真实产物按 `CORE_FIELDS` 顺序插入，列顺序影响压缩率。夹具只用于反向对照，**不作为产物证据**；产物证据一律用 §3.2 的真实构建。

---

## 5. 与 P0-1 报告的数字互证

| 指标 | P0-1 报告（独立测得） | 本守卫实测 | 一致 |
|---|---|---|---|
| `n` | 196,200 | 196,200 | ✓ |
| `t==1` | 166,846（85.0%） | 166,846（85.04%） | ✓ |
| `nc==1` | 3,023 | 3,023 | ✓ |
| `eo==1` | 2,292 | 2,292 | ✓ |
| 补三列后 raw | +1.18 MB（预测 42.80） | 42,801,654（42.80 MB） | ✓ |
| 补三列后 gzip | +22.4 KB（预测 9.796） | 9.801 MB（+28 KB） | ✓（预测偏差 5.6 KB，原报告已注明以实跑为准） |
| 分片数 / 行数 | 109 / 196,200 | 109 / 196,200 | ✓ |

---

## 6. 接入 `ci_checks.py` 的建议（**本轮不落地**，发布后由 Lead 决定）

理由：`deploy/ci_checks.py` 在发布窗口冻结；且 `check_dist()` 目前**只查 core 体积**（`ci_checks.py:371-373`），不查字段——这正是 P0-1 能发到线上的结构性原因。

### 6.1 diff（三处）

```diff
--- a/deploy/ci_checks.py
+++ b/deploy/ci_checks.py
@@ SUMMARY_ORDER
     "unittest:lib-atc-category", "trilingual", "check_data", "dist-integrity",
-    "ui-surface", "first-screen", "workflow",
+    "core-fields", "ui-surface", "first-screen", "workflow",

@@ 新增检查（放在 check_dist 之后）
+@timed("core-fields")
+def check_core_fields(verbose: bool, fast: bool) -> None:
+    """P0-1 守卫：core.json 必须携带 t/nc/eo（v0.11.1 整体缺失 → 85% 商品名消失）。
+
+    fast 只验字段（跳过 gzip -9 ≈5 s、分片覆盖 ≈1.4 s），约 0.5 s 出结论。
+    """
+    core = DIST_PATH / "data" / "idx" / "core.json"
+    if not core.exists():
+        record("SKIP", "core-fields", f"无 {_rel(core)}（生成物不入库；发布前本地必跑）")
+        return
+    cmd = [PY, str(ROOT / "deploy" / "check_core_fields.py"),
+           "--dist", str(DIST_PATH),
+           "--json", str(ROOT / ".tmp" / "ci" / "core-fields.json")]
+    if fast:
+        cmd += ["--no-gzip", "--no-shards"]
+    proc = _run(cmd, timeout=180)
+    out = (proc.stdout or "") + (proc.stderr or "")
+    if proc.returncode == 0:
+        line = next((ln.strip() for ln in out.splitlines() if ln.startswith("行数")), "")
+        record("PASS", "core-fields", line or "core 字段齐全")
+        return
+    bad = [ln.strip() for ln in out.splitlines() if "[FAIL]" in ln]
+    record("FAIL", "core-fields", "；".join(bad[:3]) or _tail(out, 2))

@@ main() · fast 分支
         check_dist(args.verbose, fast=True)
+        check_core_fields(args.verbose, fast=True)
         record("SKIP", "ui-surface", "--fast 跳过（要拉无头 Chrome，全量才跑）")

@@ main() · 全量分支
         check_dist(args.verbose, fast=False)
+        check_core_fields(args.verbose, fast=False)
         _run_parallel([("i18n", ...), ...])
```

### 6.2 接入后的预期

| 场景 | 行为 |
|---|---|
| `--fast`（约 15–25 s 基线） | +0.5 s，仍能在 25 s 内报出「缺 t/nc/eo」 |
| 全量（约 3–4 min） | +6.5 s（gzip -9 4.8 s + 分片 1.4 s） |
| 无 `site/dist`（CI 常态，产物不入库） | 记 SKIP，与 `dist-integrity` 同处理 |
| 产物缺列 | `[FAIL] core-fields`，`ci_checks` 退出码 1 |

要接的话建议**先只接 fast 分支**（成本最低、抓的就是 P0-1 这一类），全量分支等 gzip 那 4.8 s 是否值得再定。

---

## 7. 边界与注意事项

1. **只查结构与字段，不查「渲染对不对」**。字段齐了但 `brandHTML()` 逻辑错，本守卫不会报。
   视觉/DOM 层面的回归仍用 P0-1 报告 §6 的 8 条人工用例。
2. **`t==1` 的 85% 是「当前数据形态」**。若将来把大量通用名条目并进索引，比例会漂移，届时改 `T1_RATIO` 一个常量即可（脚本里已在注释写明依据）。
3. **gzip -9 是本脚本最慢的一步（≈4.8 s / 42.8 MB）**。慢机器或 `--fast` 场景用 `--no-gzip`。
4. **JSON 落盘用 `ensure_ascii=False` + utf-8**，与 `deploy/ci_checks.py` / `first_screen_check.py` 现有产物一致。
   **Windows PowerShell 5.1 读它必须带 `-Encoding utf8`**，否则中文乱码且 `ConvertFrom-Json` 可能直接报错（本轮实测踩到）：
   ```powershell
   Get-Content .tmp\guard-v0112.json -Raw -Encoding utf8 | ConvertFrom-Json
   ```
5. **`.tmp/v0112-build` 是易失目录**：本轮取证期间它被另一个会话清理并重建过一次（09:34 重建后 PASS 证据成立，`build_version=0477923035`）。
   正式发布仍应以 `site/build.py` 跑完 `== done ==` 后、对 `site/dist` 再跑一次本守卫为准。
6. **`.tmp/guard-fixture` 不是构建产物**，是为反向对照造的三列等价夹具（约 42.8 MB + 109 个硬链接），可用 `.tmp/make_fixture.py` 重建或直接删除。
7. **没有做的事**：没改 `site/build.py`、没改 `deploy/ci_checks.py`、没写 `site/dist`、没 commit / publish。
   脚本自身也没有单元测试——它是一层静态闸门，靠 §4 的五个对照手工验证。

---

## 8. 复现命令清单

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 旧产物 FAIL（应 exit 1）
& $py deploy/check_core_fields.py --json .tmp\guard-old.json; "exit=$LASTEXITCODE"

# 真实 v0.11.2 PASS（应 exit 0）
& $py deploy/check_core_fields.py --dist .tmp\v0112-build --json .tmp\guard-v0112.json; "exit=$LASTEXITCODE"

# 夹具 PASS（可重建）
& $py .tmp\make_fixture.py
& $py deploy/check_core_fields.py --dist .tmp\guard-fixture --json .tmp\guard-fixed.json

# 反向对照（A/B/C 依次 FAIL，最后 restore）
& $py .tmp\guard_neg.py drop-t;  & $py deploy/check_core_fields.py --dist .tmp\guard-fixture --no-gzip --no-shards
& $py .tmp\guard_neg.py zero-t;  & $py deploy/check_core_fields.py --dist .tmp\guard-fixture --no-gzip --no-shards
& $py .tmp\guard_neg.py trunc-cols; & $py deploy/check_core_fields.py --dist .tmp\guard-fixture --no-gzip --no-shards
& $py .tmp\make_fixture.py
```

JSON 摘要在 `.tmp/guard-old.json`（FAIL）、`.tmp/guard-v0112.json`（PASS，真实产物）、`.tmp/guard-fixed.json`（PASS，夹具）。
