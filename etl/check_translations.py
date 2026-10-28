# -*- coding: utf-8 -*-
"""AI 译文 / 术语一致性自动校验（只读；不修改任何译文）。

目标：在 build / 发布之前，自动发现「术语译名不一致、数字/剂量单位丢失、占位符/HTML
被吃掉、安全警示被弱化、繁体字典残留简体」等问题，输出清单供后续修复；**不自动改文案**。

输入（默认）
------------
  data/terminology_glossary.csv     术语基准表（131 条，含来源/许可/置信度；见 reports/terminology-accuracy.md）
  site/dist/assets/i18n.js          构建产物里的运行时字典（4 语言）；不存在时回退解析 site/build.py
  data/i18n_zh_hant.json            繁体字典 + 与简体 zh 的对应（用于残留检查）
  data/release_notes_i18n.json      What's new 的 zh/en/es AI 译文块（逐版本逐条）
  data/es_ui_missing.csv            es UI 缺口建议表（en_text → es_suggested）

规则（--checks 可开关；severity：critical / warning / info）
  term        术语命中：en 文本含术语时，目标语言必须含基准译名（术语表四语+变体）
  number      数字一致：en 的数字 token 必须在目标语言出现（容忍 1,000/1000 等写法）
  unit        剂量单位：en 的 mg/ml/IU/% 等必须在目标语言出现（允许本地化写法）
  placeholder @@X@@ 与 {name} 占位符必须在目标语言完整保留
  html        HTML 标签序列必须一致（防止译文吃掉 <b>/<a> 结构）
  safety      安全用语不得弱化：not interchangeable / warning / contraindicated 等必须保留强译
  zh_hant     繁体字典：与简体 zh 相同的值若含「只可能是简体」的字 → 残留；缺键 → 回退告警

用法
----
    python etl/check_translations.py                       # 默认全跑，退出码 0
    python etl/check_translations.py --strict              # 有 critical → 退出码 1（发布护栏）
    python etl/check_translations.py --json                # 只打印 JSON 摘要
    python etl/check_translations.py --i18n site/build.py  # 直接分析源码字典
    python etl/check_translations.py --checks term,safety  # 只跑部分规则

输出
----
  .tmp/terminology/translation_check.json   机器可读摘要 + findings
  .tmp/terminology/translation_findings.csv 明细（规则/严重度/语言/key/问题/证据）
  stdout 摘要表（默认；--quiet 可静默，--json 打 JSON）

边界：本脚本只读 DB 之外的文件；不写 DB、不改 build.py / 译文；不联网。
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLOSSARY_DEFAULT = ROOT / "data" / "terminology_glossary.csv"
I18N_JS_DEFAULT = ROOT / "site" / "dist" / "assets" / "i18n.js"
BUILD_PY_DEFAULT = ROOT / "site" / "build.py"
ZH_HANT_DEFAULT = ROOT / "data" / "i18n_zh_hant.json"
RELEASE_DEFAULT = ROOT / "data" / "release_notes_i18n.json"
ES_MISSING_DEFAULT = ROOT / "data" / "es_ui_missing.csv"
OUT_DEFAULT = ROOT / ".tmp" / "terminology"

ALL_CHECKS = ("term", "number", "unit", "placeholder", "html", "safety", "zh_hant")
LANGS = ("en", "es", "zh", "zh-Hant")

# en 单位 → 目标语言可接受写法（英文/西语/简中/繁中）
UNIT_ALIASES = {
    "mg": ["mg", "毫克", "mg"],
    "mcg": ["mcg", "μg", "ug", "微克"],
    "µg": ["mcg", "μg", "ug", "微克"],
    "g": ["g", "克", "公克"],
    "kg": ["kg", "公斤", "千克"],
    "ml": ["ml", "mL", "毫升"],
    "mL": ["ml", "mL", "毫升"],
    "l": ["l", "L", "升"],
    "IU": ["IU", "UI", "国际单位", "國際單位"],
    "UI": ["IU", "UI", "国际单位", "國際單位"],
    "%": ["%", "％", "百分比"],
    "mEq": ["mEq", "meq", "毫当量", "毫當量"],
}
NUMBER_RE = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)*)(?![\w.])")
UNIT_RE = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)*)\s*(mg|mcg|µg|g|kg|ml|mL|l|IU|UI|%|mEq)\b")
PLACEHOLDER_RES = (re.compile(r"@@[A-Za-z0-9_]+@@"), re.compile(r"\{[a-z][a-z0-9_]*\}"))
TAG_RE = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)[^>]*>")
# 「只可能是简体」的字：由 OpenCC TSCharacters 计算（简化值 − 繁体键），
# 且只保留站点繁体字典中未出现过、但简体字典使用过的字（避免繁简同形误报）。
SIMPLIFIED_ONLY = set("""这为说时国药厂检释盐剂颗胶软规录诊发应临试单双价医数据网络页线点击关闭开启链缓视频标签风险种资讯统设备权责认证审评号监会处务专业际连结档""")
WEAK_HINTS = ("提示", "提醒", "注意", "参考", "建议", "告知", "info", "note", "please note",
              "may", "might", "suggestion", "consider")

rows_glossary: list[dict] = []
findings: list[dict] = []


def finding(check: str, severity: str, lang: str, key: str, message: str,
            evidence: str = "", glossary: str = "") -> None:
    findings.append({
        "check": check, "severity": severity, "lang": lang, "key": key,
        "message": message, "evidence": evidence[:300], "glossary_term": glossary,
    })


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------
def load_glossary(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            r = {k: (v or "").strip() for k, v in r.items()}
            if not r.get("term_en"):
                continue
            r["_variants"] = {
                "es": [r["term_es"]] if r["term_es"] else [],
                "zh": [r["term_zh"]] + ([r["zh_variants"]] if r["zh_variants"] else []),
                "zh-Hant": [r["term_zh_hant"]]
                + ([r["zh_hant_variants"]] if r["zh_hant_variants"] else []),
            }
            for lang in ("zh", "zh-Hant"):
                r["_variants"][lang] = [
                    v.strip() for item in r["_variants"][lang]
                    for v in re.split(r"[|;；/]", item) if v.strip()
                ]
            if r.get("es_variants"):
                r["_variants"]["es"] = [v.strip() for v in re.split(r"[|;；/]", r["es_variants"])
                                         if v.strip()]
            r["do_not_weaken"] = r.get("do_not_weaken") == "1"
            r["severity"] = r.get("severity") or "warning"
            rows.append(r)
    # 不同 domain 可能有同名词条（如 safety 与 regulatory 都有 adverse reaction）：
    # 合并为一个，变体取并集，安全项优先。
    by_term: dict[str, dict] = {}
    for r in rows:
        key = r["term_en"].lower()
        if key not in by_term:
            by_term[key] = r
            continue
        base = by_term[key]
        for lang in ("es", "zh", "zh-Hant"):
            base["_variants"][lang] = list(dict.fromkeys(
                base["_variants"][lang] + r["_variants"][lang]))
        if r["do_not_weaken"]:
            base["do_not_weaken"] = True
            base["severity"] = "critical"
    return list(by_term.values())


def _merge_i18n(bases: dict[str, dict], extra: dict[str, dict]) -> dict[str, dict]:
    out = {lang: dict(d) for lang, d in bases.items()}
    for lang, d in extra.items():
        out.setdefault(lang, {}).update(d)
    return out


def load_i18n(path: Path) -> tuple[dict[str, dict], str]:
    """返回 ({lang: {key: text}}, 来源说明)。支持构建产物 i18n.js 或 site/build.py。"""
    if path.suffix == ".js":
        text = path.read_text(encoding="utf-8")
        m = re.search(r"window\.I18N=(\{.*?\});\n", text, re.S)
        if not m:
            raise SystemExit(f"无法从 {path} 解析 window.I18N")
        data = json.loads(m.group(1))
        return {lang: {k: str(v) for k, v in d.items()} for lang, d in data.items()}, f"js:{path.name}"
    if path.name == "build.py":
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = ("I18N", "ABOUT_I18N", "PAGE_I18N", "WARN_I18N", "COMBO_I18N",
                 "MAKER_I18N", "META_I18N", "GLOSSARY_I18N")
        consts: dict[str, dict] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names:
                try:
                    consts[node.targets[0].id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    pass
        if "I18N" not in consts:
            raise SystemExit("site/build.py 中未找到可解析的 I18N 字典")
        base = consts["I18N"]
        extra = {lang: {} for lang in base}
        for name in names[1:]:
            for lang, d in (consts.get(name) or {}).items():
                extra.setdefault(lang, {}).update(d)
        merged = _merge_i18n(base, extra)
        return {lang: {k: str(v) for k, v in d.items()} for lang, d in merged.items()}, "build.py-ast"
    raise SystemExit("--i18n 只支持 .js（构建产物 i18n.js）或 site/build.py")


def load_zh_hant(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("zh-Hant") or {}


# ---------------------------------------------------------------------------
# 通用文本规则
# ---------------------------------------------------------------------------
def norm_numbers(text: str) -> list[str]:
    out = []
    for m in NUMBER_RE.finditer(text or ""):
        out.append(re.sub(r"[.,]", "", m.group(1)))
    return out


def check_placeholder(key: str, lang: str, src: str, tgt: str) -> None:
    for rx in PLACEHOLDER_RES:
        a = sorted(rx.findall(src))
        b = sorted(rx.findall(tgt))
        if a != b:
            finding("placeholder", "critical", lang, key,
                    f"占位符不一致: {a} → {b}", src)


def check_html(key: str, lang: str, src: str, tgt: str) -> None:
    a = TAG_RE.findall(src)
    b = TAG_RE.findall(tgt)
    if a != b:
        finding("html", "warning", lang, key, f"HTML 标签序列不一致: {a} → {b}", src)


def check_number_unit(key: str, lang: str, src: str, tgt: str,
                      visible: str = "en", target_visible: str = "") -> None:
    src_nums = norm_numbers(src)
    tgt_nums = norm_numbers(tgt)
    tgt_flat = tgt.replace(",", "").replace(" ", "").replace(".", "")
    CJK_NUM = {"1": "一", "2": "二", "3": "三", "4": "四", "5": "五",
               "6": "六", "7": "七", "8": "八", "9": "九", "10": "十"}
    missing = []
    for n in src_nums:
        if n in tgt_nums or n in tgt_flat:
            continue
        if n in CJK_NUM and CJK_NUM[n] in tgt:
            continue
        # 大数本地化（146,344 → 14.6 万 / 146k）近似接受（±5%）
        try:
            val = float(n)
        except ValueError:
            missing.append(n)
            continue
        if val >= 1000:
            scale = {"万": 1e4, "萬": 1e4, "亿": 1e8, "億": 1e8, "k": 1e3, "K": 1e3,
                     "million": 1e6, "M": 1e6}
            ok = False
            for unit, mult in scale.items():
                for m in re.finditer(r"(\d+(?:\.\d+)?)\s*" + re.escape(unit), tgt):
                    if abs(float(m.group(1)) * mult - val) / max(val, 1) <= 0.05:
                        ok = True
            if ok:
                continue
        missing.append(n)
    if missing:
        finding("number", "warning", lang, key,
                f"数字未在译文中出现: {missing[:8]}（en 共 {len(src_nums)} 个数字）", src)
    for m in UNIT_RE.finditer(src):
        unit = m.group(2)
        aliases = UNIT_ALIASES.get(unit, [unit])
        if not any(alias in tgt for alias in aliases):
            finding("unit", "warning", lang, key,
                    f"剂量单位 {unit!r} 在译文中缺失（可接受写法: {aliases}）", src)


def match_terms(text: str) -> list[dict]:
    """en 文本里命中的术语（按 term_en 做词边界匹配；最长优先去重叠）。"""
    hits: list[dict] = []
    low = (text or "").lower()
    for row in rows_glossary:
        if row.get("domain") == "status":
            term_low = row["term_en"].lower()
            if not (low.strip() == term_low
                    or re.search(r"\b(status|state|estado)\b[^.]{0,12}" + re.escape(term_low), low)):
                continue
        term = row["term_en"]
        if not term or len(term) < 2:
            continue
        if re.search(r"[A-Za-z]", term):
            pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.I)
        else:
            pat = re.compile(re.escape(term))
        if pat.search(low if re.search(r"[A-Za-z]", term) else text):
            hits.append(row)
    # 同一位置被多个术语命中时保留最长（避免 "active" 命中 "active ingredient"）
    hits.sort(key=lambda r: -len(r["term_en"]))
    keep: list[dict] = []
    for row in hits:
        if any(row["term_en"].lower() in k["term_en"].lower()
               and row["term_en"].lower() != k["term_en"].lower() for k in keep):
            continue
        keep.append(row)
    return keep


def check_terms(key: str, lang: str, en_text: str, tgt_text: str) -> None:
    for row in match_terms(en_text):
        expected = row["_variants"].get(lang) or []
        if not expected:
            continue
        target_low = tgt_text.lower() if re.search(r"[A-Za-z]", " ".join(expected)) else tgt_text
        if any(exp and (exp.lower() in target_low if re.search(r"[A-Za-z]", exp) else exp in tgt_text)
               for exp in expected):
            continue
        severity = row["severity"] if row["do_not_weaken"] else "warning"
        finding("safety" if row["do_not_weaken"] else "term", severity, lang, key,
                f"术语 {row['term_en']!r} 的 {lang} 译名未命中基准（期望 {expected[:2]}）",
                en_text, row["term_en"])


def check_pair(key: str, lang: str, src: str, tgt: str, *,
               checks: set[str], with_terms: bool = True) -> None:
    if "placeholder" in checks:
        check_placeholder(key, lang, src, tgt)
    if "html" in checks:
        check_html(key, lang, src, tgt)
    if "number" in checks or "unit" in checks:
        check_number_unit(key, lang, src, tgt)
    if with_terms and ("term" in checks or "safety" in checks):
        check_terms(key, lang, src, tgt)


# ---------------------------------------------------------------------------
# 各数据源
# ---------------------------------------------------------------------------
def run_i18n(i18n: dict[str, dict], source: str, checks: set[str]) -> dict:
    coverage = Counter()
    en = i18n.get("en") or {}
    for key, src in en.items():
        if not isinstance(src, str):
            continue
        if "term" in checks or "safety" in checks:
            for row in match_terms(src):
                coverage[row["domain"]] += 1
        for lang in ("es", "zh", "zh-Hant"):
            tgt = (i18n.get(lang) or {}).get(key)
            if not isinstance(tgt, str):
                continue
            check_pair(key, lang, src, tgt, checks=checks)
    return {"keys": len(en), "coverage": dict(coverage), "source": source}


def run_zh_hant(zh: dict[str, dict], hant: dict, checks: set[str]) -> dict:
    missing = sorted(set(zh) - set(hant))
    residue = []
    for key in sorted(set(zh) & set(hant)):
        a, b = zh[key], hant[key]
        if a != b:
            continue
        bad = sorted({c for c in b if c in SIMPLIFIED_ONLY})
        if bad:
            residue.append((key, "".join(bad[:6]), b[:80]))
    for key, chars, text in residue[:200]:
        finding("zh_hant", "warning", "zh-Hant", key,
                f"繁体值含只可能是简体的字: {chars}", text)
    if missing:
        for key in missing[:100]:
            finding("zh_hant", "warning", "zh-Hant", key,
                    "繁体字典缺键（构建时回退简体 zh）", zh[key])
    return {"zh_keys": len(zh), "hant_keys": len(hant), "missing": len(missing),
            "same_but_simplified": len(residue)}


def run_release_notes(path: Path, checks: set[str]) -> dict:
    if not path.exists():
        return {"versions": 0, "items": 0}
    data = json.loads(path.read_text(encoding="utf-8"))
    versions = [k for k in data if not k.startswith("_")]
    items = 0
    for ver in versions:
        block = data[ver]
        zh = block.get("zh") or []
        en = block.get("en") or []
        es = block.get("es") or []
        for i, (zt, et, st) in enumerate(zip(zh, en, es)):
            items += 1
            key = f"release:{ver}#{i + 1}"
            # zh 是权威原文；检查 en/es 是否保留数字/占位符/HTML
            check_pair(key, "en", zt, et, checks=checks, with_terms=False)
            check_pair(key, "es", zt, st, checks=checks, with_terms=False)
            # en → es 术语一致性（AI 译文层）
            if "term" in checks:
                check_terms(key, "es", et, st)
    return {"versions": len(versions), "items": items}


def run_es_missing(path: Path, checks: set[str]) -> dict:
    if not path.exists():
        return {"rows": 0}
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    for i, r in enumerate(rows, 2):
        en_text = r.get("en_text") or ""
        es_text = r.get("es_suggested") or ""
        key = f"es_ui_missing:{r.get('key') or i}"
        check_pair(key, "es", en_text, es_text, checks=checks, with_terms=False)
        if es_text and not r.get("es_suggested"):
            finding("term", "warning", "es", key, "es 建议为空", en_text)
    return {"rows": len(rows)}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    global rows_glossary, findings
    ap = argparse.ArgumentParser(description="AI 译文 / 术语一致性自动校验（只读）")
    ap.add_argument("--glossary", type=Path, default=GLOSSARY_DEFAULT)
    ap.add_argument("--i18n", type=Path, default=None,
                    help="构建产物 i18n.js 或 site/build.py（默认优先 dist i18n.js）")
    ap.add_argument("--zh-hant", type=Path, default=ZH_HANT_DEFAULT)
    ap.add_argument("--release-notes", type=Path, default=RELEASE_DEFAULT)
    ap.add_argument("--es-missing", type=Path, default=ES_MISSING_DEFAULT)
    ap.add_argument("--out-dir", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--checks", default=",".join(ALL_CHECKS),
                    help="逗号分隔：" + ",".join(ALL_CHECKS))
    ap.add_argument("--skip", default="", help="逗号分隔：跳过哪些规则")
    ap.add_argument("--strict", action="store_true", help="有 critical 时退出码 1")
    ap.add_argument("--json", action="store_true", help="打印 JSON 摘要")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    checks = {c.strip() for c in args.checks.split(",") if c.strip()}
    bad = checks - set(ALL_CHECKS)
    if bad:
        raise SystemExit(f"未知规则: {sorted(bad)}（可选 {ALL_CHECKS}）")
    checks -= {c.strip() for c in args.skip.split(",") if c.strip()}

    rows_glossary = load_glossary(args.glossary)
    i18n_path = args.i18n or (I18N_JS_DEFAULT if I18N_JS_DEFAULT.exists() else BUILD_PY_DEFAULT)
    i18n, source = load_i18n(i18n_path)
    zh = i18n.get("zh") or {}
    hant = load_zh_hant(args.zh_hant)
    if hant and "zh-Hant" not in i18n:
        i18n["zh-Hant"] = hant

    stats: dict[str, dict] = {"i18n": run_i18n(i18n, source, checks)}
    stats["zh_hant"] = run_zh_hant(zh, hant, checks) if "zh_hant" in checks else {}
    stats["release_notes"] = run_release_notes(args.release_notes, checks)
    stats["es_ui_missing"] = run_es_missing(args.es_missing, checks)

    # 汇总
    by_check = Counter(f["check"] for f in findings)
    by_sev = Counter(f["severity"] for f in findings)
    by_lang = Counter(f["lang"] for f in findings)
    summary = {
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds"),
        "glossary": {"rows": len(rows_glossary), "path": str(args.glossary)},
        "i18n": {"path": str(i18n_path), "source": source,
                 "langs": {k: len(v) for k, v in i18n.items()}},
        "stats": stats,
        "findings_total": len(findings),
        "by_check": dict(by_check), "by_severity": dict(by_sev), "by_lang": dict(by_lang),
        "checks": sorted(checks),
        "findings": findings[:2000],
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    js = args.out_dir / "translation_check.json"
    js.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    csv_path = args.out_dir / "translation_findings.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["check", "severity", "lang", "key", "message",
                                           "evidence", "glossary_term"])
        w.writeheader()
        w.writerows(findings)

    if args.json:
        print(json.dumps({k: v for k, v in summary.items() if k != "findings"},
                         ensure_ascii=False, indent=1))
    elif not args.quiet:
        print("== 术语 / AI 译文自动校验 ==")
        print(f"术语基准: {len(rows_glossary)} 条 ({args.glossary.relative_to(ROOT) if args.glossary.is_relative_to(ROOT) else args.glossary})")
        print(f"i18n: {summary['i18n']['langs']}  来源={source}")
        print(f"数据源检查: " + "；".join(
            f"{k}={stats[k]}" for k in ("zh_hant", "release_notes", "es_ui_missing")))
        print(f"术语覆盖（en 文本命中次数）: {stats['i18n']['coverage']}")
        print(f"\nfindings 共 {len(findings)} 条: " + ", ".join(
            f"{k}={v}" for k, v in by_sev.most_common()))
        print("  按规则: " + ", ".join(f"{k}={v}" for k, v in by_check.most_common()) or "无")
        print("  按语言: " + ", ".join(f"{k}={v}" for k, v in by_lang.most_common()))
        for sev in ("critical", "warning"):
            sample = [f for f in findings if f["severity"] == sev][:8]
            if sample:
                print(f"\n-- {sev} 样例（前 8）--")
                for f in sample:
                    print(f"  [{f['check']}/{f['lang']}] {f['key']}: {f['message'][:150]}")
        print(f"\n报告: {js.relative_to(ROOT) if js.is_relative_to(ROOT) else js}")
        print(f"明细: {csv_path.relative_to(ROOT) if csv_path.is_relative_to(ROOT) else csv_path}")

    critical = by_sev.get("critical", 0)
    if args.strict and critical:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
