# -*- coding: utf-8 -*-
"""**已退役（v0.11.3）——不要再运行本脚本。**

历史
----
v0.7.1 时它是 `lib/categories.py` 的生成器：把 `site/dist/data/categories.json` 里
16 大类（id/url/prefixes/四语 labels/aliases）快照下来，并补一份口语别名表，
整份 `lib/categories.py` 由内嵌模板 `write_text()` 覆盖写出。

为什么退役
----------
1. 内嵌模板停在 v0.7.1，之后的 `NAME_KEY_SHADOW_EXCEPTIONS` / `is_shadowed()` /
   `colloquial_aliases_by_category()` / `assert_no_unlisted_shadow()` 全都不在里面。
   **今天再跑一次，会把这些功能直接从 lib 里覆盖掉。**
2. `CATEGORY_SNAPSHOT` 的 `aliases` 从 v0.11.3 起不再手抄，而是在 `lib/categories.py`
   内按构建期同一口径（`[官方英文 label, 大类 id, *该类口语别名]`）**派生**。
   生成器再写死一堆 `aliases` 字面量，等于把它刚修好的漂移问题重新种回去
   （v0.10.3 起这 16 类漂了 3 个版本，见 `reports/2026-11-13-lib-atc-category-fix.md`）。

现在该怎么做
------------
- 改了构建侧大类配置（`site/build.py` 的 `CONSUMER_CATEGORIES`）后**不用跑生成器**：
  直接在 `lib/categories.py` 里同步 `id/url/prefixes/labels`（`aliases` 不用管）。
- 校验是否同步：
  `python -m unittest tests.test_lib_atc_category`
  （`test_snapshot_sync_with_dist` 逐字段比对产物；这条已进 `ci_checks.py --fast`）。
"""

from __future__ import annotations

import sys


def main() -> int:
    print(__doc__.strip().splitlines()[0])
    print()
    print("本脚本已退役，运行它只会破坏 lib/categories.py —— 已拒绝执行。")
    print("校验快照是否与产物同步：python -m unittest tests.test_lib_atc_category")
    print("背景：reports/2026-11-13-lib-atc-category-fix.md")
    return 2


if __name__ == "__main__":
    sys.exit(main())
