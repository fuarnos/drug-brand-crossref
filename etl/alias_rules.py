#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P0-3 别名质量闸门：整句 / 说明文字 / 剂型尾缀 / 两名挤一格。

为什么单独一份规则
------------------
2026-11-11 用户走查发现成分页「也叫」里混进「宣传自己的商品」「生产厂家为突出」
「硫酸氢氯吡格雷片是波立维」这类**整句**。根因是 `etl/extract_cn_slang.py::is_junk_term()`
把「是 / 为 / 的」锚在**行首**（`^是`、`^为`、`^的`），出现在句中就一律放行；
而 `run_all.py` 只跑 `etl/ingest_cn_slang.py`（入库）、**不跑** `extract_cn_slang.py`（抽取），
所以只在抽取侧补闸门挡不住「删了又被下次重建灌回来」。

规则因此放在这里一份，两个入口共用：
  * `etl/extract_cn_slang.py::is_junk_term()` —— 抽取时拦（不写进候选 CSV）；
  * `etl/ingest_cn_slang.py::build_plan()` —— 入库时拦（历史 CSV 里的旧行也过一遍）。

口径（与 AGENTS §1 一致）
------------------------
- **判不了就不收**：宁可少收一个叫法，也不把整句挂到成分页上（Tier C 丢弃并计数）。
- **不在这里做语义判断**：「指向别的药」靠子串匹配太脏（`二甲胺四环素` 含 `四环素`、
  `葡萄糖胺` 含 `葡萄糖` 都是合法叫法）。真要判，用 `other_ingredient_names` 的组合入口，
  且必须同时满足「足够长」，见 `alias_junk_reason()`。
- **保留 `的松`**：`强的松` / `考的松` / `可的松` 是糖皮质激素的构词，不是抓取残句。
- **商品名不是别名**：AGENTS §4 说商品名进 `product_name`，不进 `nickname`/`drug_term`；
  所以「商品名 + 剂型」这种带剂型尾缀的写法在这里一律当不合格（`碘片`、`牙周康胶囊`…）。

用法
----
    from alias_rules import alias_junk_reason
    why = alias_junk_reason("宣传自己的商品")     # → "整句/说明文字（P0-3）"
    why = alias_junk_reason("强的松")             # → ""

自检（把 45 行脏样本 + 合法叫法 + 候选 CSV 金值写成断言）：

    python etl/alias_rules.py --self-check
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATE_CSV = ROOT / "data" / "cn_slang_candidates.csv"

# 原因标签：固定几个短字符串，便于在 drop/skipped 计数器里聚合，不要随手改文案。
R_SENTENCE = "整句/说明文字（P0-3）"
R_PURE = "纯虚词残片（P0-3）"
R_FORM = "剂型尾缀（P0-3）"
R_TWO_NAMES = "两名挤一格（P0-3）"
R_PUNCT = "标点残句（P0-3）"
R_LONG = "过长（P0-3）"
R_CROSS = "含其他成分名（P0-3）"

# 汉字上限：与 extract_cn_slang 既有阈值一致（>16 汉字基本是句子）。
MAX_HAN_LEN = 16
# 「成分名组合规则」的最短长度：短名容易撞母体（四环素 ⊂ 二甲胺四环素），长的才可疑。
CROSS_MIN_LEN = 8

RE_HAN = re.compile(r"[\u4e00-\u9fff]")
# 中文别名里不该出现的标点（句读、括号、引号）。`·`、`-` 这类名字内分隔符不算。
RE_PUNCT = re.compile(r"[，。；：！？、（）()【】《》〈〉「」『』“”‘’…]")

# 顺序即优先级：先给最能解释的来源，再退到更泛的规则。
# 每条都是**句中**判定（不锚行首），这正是 P0-3 的直接修复点。
RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"宣传|生产厂家|生产厂商|厂家|厂商|商品|药品|说明书"), R_SENTENCE),
    (re.compile(r"可以|可能|啥|别称|分别|收载|曾用名|误导|音译|类药物"), R_SENTENCE),
    (re.compile(r"别被"), R_SENTENCE),
    (re.compile(r"吗$"), R_SENTENCE),
    (re.compile(r"而来|多为|多个|不一样|常为|通常为|常见"), R_SENTENCE),
    # 纯虚词：整格就是一个虚词，或明显是「…之一 / …之类」的残片。
    (re.compile(r"^不同$|不同$|之一|之类|等等|^以下$|^以上$"), R_PURE),
    # 「是 / 为」：药名里不会出现；原闸门只锚行首，句中全漏。
    (re.compile(r"[是为]"), R_SENTENCE),
    (re.compile(r"的$"), R_SENTENCE),
    # 句中「的」：`的松` 例外（强的松 / 考的松 / 可的松）。
    (re.compile(r"的(?!松)"), R_SENTENCE),
    # 剂型尾缀 = 商品名或说明书写法，不是别名。
    (re.compile(r"(片|胶囊|注射液|口服液|颗粒|乳膏|软膏|滴眼液|糖浆)$"), R_FORM),
    # 两个真名挤在一格（需人工拆分后再入）。
    (re.compile(r"[或和与及]"), R_TWO_NAMES),
)


def han_len(text: str) -> int:
    """汉字个数（判断长度用汉字，不数拉丁字母/数字）。"""
    return len(RE_HAN.findall(text or ""))


def alias_junk_reason(
    term: str,
    *,
    other_ingredient_names: frozenset[str] | set[str] | None = None,
    extended: bool = True,
) -> str:
    """返回不合格原因；空字符串表示通过。

    term                    待判定的叫法（原始写法即可）
    other_ingredient_names  库内其他成分的中文名；给了才启用「成分名组合规则」：
                            含别的成分名 **且** 汉字数 ≥ CROSS_MIN_LEN 才算可疑。
    extended                True（默认）= 全量规则；False = 只用「审计报告 §5.3 的 64/1,108」
                            那一套（少了纯虚词规则），留给对拍用。
    """
    t = (term or "").strip()
    if not t:
        return "空"
    if not RE_HAN.search(t):
        return "非中文"
    if han_len(t) > MAX_HAN_LEN:
        return R_LONG
    if RE_PUNCT.search(t):
        return R_PUNCT
    for rx, reason in RULES:
        if not extended and reason == R_PURE:
            continue
        if rx.search(t):
            return reason
    if other_ingredient_names:
        n = han_len(t)
        if n >= CROSS_MIN_LEN:
            for name in other_ingredient_names:
                if name and len(name) >= 2 and name in t:
                    return R_CROSS
    return ""


def is_junk(term: str, **kwargs) -> bool:
    return bool(alias_junk_reason(term, **kwargs))


# ---------------------------------------------------------------------------
# 自检（把事故样本写成断言，方便 CI / 手跑）
# ---------------------------------------------------------------------------
# 2026-11-12 库内 45 行删除清单（reports/2026-11-12-p0-3-alias-cleanup.md §2 + .tmp/alias_cleanup_removals.csv）。
# 这 45 条必须全部被拦——用户走查点名的三条也在里面。
SELF_CHECK_JUNK: tuple[str, ...] = (
    "速效伤风胶囊", "速效感冒胶囊", "万艾可的", "不一样", "他达拉非是药品",
    "伟哥的", "利拉鲁肽的", "别称", "别被", "可以说都很低调",
    "可能因生产厂商", "右美沙芬片的", "呼吸科的", "啥名", "啥名字",
    "塞来昔布的", "多个", "多为", "多潘立酮或吗丁啉", "宣传自己的商品",
    "常为", "常见药品", "扑尔敏的", "抗癬乳膏", "收载",
    "无环鸟苷的阿昔洛韦", "曾用名", "氨氯地平的", "沙星类药物", "瑞舒伐他汀的",
    "生产厂家为突出", "硫酸氢氯吡格雷片是波立维", "而来", "芬必得吗", "药品",
    "西地那非的", "误导", "选项C胶岭石是蒙脱石", "通常为", "阿司匹林的",
    "阿司匹林的三个", "阿奇霉素的", "音译", "不同", "之一",
)

# 合法叫法必须**通过**：含「的松」的糖皮质激素、口语化真叫法、化学长名、数字商品名。
SELF_CHECK_KEEP: tuple[str, ...] = (
    "强的松", "考的松", "可的松", "醋酸可的松", "氢化可的松", "泼尼松",
    "蓝色小药丸", "薄血丸", "白加黑", "舒喘灵", "胃达喜", "顺尔宁",
    "必理通", "泰诺", "泰诺林", "扑热息痛", "对乙酰氨基酚", "万艾可", "芬必得",
    "阿司匹林", "头孢拉定", "布洛芬", "甲硝唑", "奥美拉唑", "二甲胺四环素",
    "葡萄糖胺", "去甲酰氧甲基唑肟头孢菌素", "999感冒灵", "云南白药", "片仔癀",
    "风油精", "红花油", "六味地黄丸", "速效救心丸",
)

# 候选 CSV（data/cn_slang_candidates.csv，1,108 行）上的金值：
#   core     = 审计报告 §5.3 的规则集 → 64 行
#   extended = 本模块（多一条纯虚词规则，捞出「不同 / 之一 / 称之一」）→ 67 行
# CSV 重新生成后这两个数会变，改这里并写进报告，别只改一个。
SELF_CHECK_CANDIDATE_GOLDEN = (64, 67)


def self_check(candidate_csv: Path | None = None, verbose: bool = True) -> list[str]:
    """跑全部断言；返回失败项（空列表 = 全过）。"""
    fails: list[str] = []
    for t in SELF_CHECK_JUNK:
        why = alias_junk_reason(t)
        if not why:
            fails.append(f"脏样本未拦住：{t}")
        elif verbose:
            print(f"  ✓ 拦  {t:<16} {why}")
    for t in SELF_CHECK_KEEP:
        why = alias_junk_reason(t)
        if why:
            fails.append(f"合法叫法被误杀：{t}（{why}）")
        elif verbose:
            print(f"  ✓ 过  {t}")

    csv_path = candidate_csv or CANDIDATE_CSV
    if csv_path.exists():
        import csv as _csv

        with open(csv_path, encoding="utf-8-sig") as fh:
            rows = list(_csv.DictReader(fh))
        core = sum(1 for r in rows
                   if alias_junk_reason(r["term"], extended=False))
        ext = sum(1 for r in rows if alias_junk_reason(r["term"]))
        want_core, want_ext = SELF_CHECK_CANDIDATE_GOLDEN
        if verbose:
            print(f"  候选 CSV {len(rows)} 行：core 拦 {core}（金值 {want_core}）、"
                  f"extended 拦 {ext}（金值 {want_ext}）")
        if core != want_core:
            fails.append(f"候选 CSV core 拦截数变了：{core} != {want_core}（重新生成过 CSV？）")
        if ext != want_ext:
            fails.append(f"候选 CSV extended 拦截数变了：{ext} != {want_ext}（重新生成过 CSV？）")
    elif verbose:
        print(f"  （跳过候选 CSV 断言：{csv_path} 不存在）")

    if verbose:
        print()
        print("自检通过" if not fails else f"自检失败 {len(fails)} 项")
        for f in fails:
            print(f"  !! {f}")
    return fails


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="P0-3 别名闸门自检")
    ap.add_argument("--self-check", action="store_true", help="跑断言（默认就做这件事）")
    ap.add_argument("--csv", default=None, help="候选 CSV 路径（默认 data/cn_slang_candidates.csv）")
    args = ap.parse_args()
    fails = self_check(Path(args.csv) if args.csv else None)
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
