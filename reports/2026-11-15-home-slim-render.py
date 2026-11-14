"""v0.11.10 渲染探针：渲染首页四语 + About（E4）+ 成分页（task-6 用）到 .tmp。

用法：
  $py reports/2026-11-15-home-slim-render.py .tmp/v01110 [drug_sids...]
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_build():
    spec = importlib.util.spec_from_file_location("v01110_build", ROOT / "site" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    out = ROOT / (sys.argv[1] if len(sys.argv) > 1 else ".tmp/v01110")
    drug_sids = {s for s in (sys.argv[2:] or ["amlodipine"]) if s}
    out.mkdir(parents=True, exist_ok=True)
    mod = load_build()
    mod.OUT = out
    mod.BUILD_V = mod._compute_build_v()
    db = sqlite3.connect(f"file:{ROOT / 'data' / 'drugs.db'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    # i18n：首页内联字典取自 OUT/assets/i18n.js，所以必须先写出去
    stats = {"products": 0, "substances": 0, "atc": 0, "keys": 0, "nickname": 0, "aliases": 0,
             "confusable": 0, "severe": 0, "atc_pct": 0.0, "drug_term": 0}
    coverage = [dict(r) for r in db.execute("SELECT * FROM coverage ORDER BY country")]
    mod._merge_static_i18n({})
    mod._install_zh_hant({})
    # 首页内联字典取自 OUT/assets/i18n.js。真实构建里这份由 main() 内的嵌套函数写；
    # 证据渲染复用上一次发布的 assets/i18n.js（同一套逻辑，缺新 key 时按英文回落），
    # 没有就用最小 stub（只影响语言切换，不影响版式与 band_ratio 量测）。
    (out / "assets").mkdir(parents=True, exist_ok=True)
    # 样式（page() 引用的 style.<hash>.css + 稳定名 style.css）—— 少了它长尾页会没有版式，
    # band_ratio 会量出 1.0 的假数字。
    _css_bytes = mod.CSS.encode("utf-8")
    (out / "assets" / mod.CSS_FILE.split("/")[-1]).write_bytes(_css_bytes)
    (out / "assets" / "style.css").write_bytes(_css_bytes)
    # app.js（成分页的收起块 / 筛选等渐进增强都在这里）。APP_JS 带构建期占位符，必须按
    # main() 同样的替换写出去，否则脚本语法错误（证据页面就测不到收起行为了）。
    _t2s = mod._load_zh_hant_t2s()
    _app_js = (mod.APP_JS.replace("REPORT_REPO_PLACEHOLDER", mod.REPORT_REPO)
               .replace("__DETAIL_ROW_FIELDS__",
                        __import__("json").dumps(mod.DETAIL_ROW_FIELDS, ensure_ascii=False))
               .replace("__T2S_JSON__",
                        __import__("json").dumps(_t2s, ensure_ascii=False,
                                                 separators=(",", ":")))
               .replace("data/idx/core.json", f"data/idx/core.json?v={mod.BUILD_V}")
               .replace("data/idx/pinyin.json", f"data/idx/pinyin.json?v={mod.BUILD_V}")
               .replace("data/idx/manifest.json", f"data/idx/manifest.json?v={mod.BUILD_V}"))
    (out / "assets" / "app.js").write_text(_app_js, encoding="utf-8")
    # 长尾页（成分/名字/组合/厂家）的脚本与壳由 assets/boot.js 注入 —— 证据构建里直接复用
    # 上一次发布的 boot.js（它是稳定资产，收起逻辑全在 app.js 里）。
    _boot = ROOT / "site" / "dist" / "assets" / "boot.js"
    if _boot.exists():
        # 真实构建里 boot.js 尾部就是 _mkblock_js()（main() 现拼）；证据构建把同一段追加进去
        (out / "assets" / "boot.js").write_text(
            _boot.read_text(encoding="utf-8") + "\n" + mod._mkblock_js(), encoding="utf-8")
    src_i18n = ROOT / "site" / "dist" / "assets" / "i18n.js"
    if src_i18n.exists():
        (out / "assets" / "i18n.js").write_bytes(src_i18n.read_bytes())
    else:
        (out / "assets" / "i18n.js").write_text(
            'window.I18N={"en":{},"es":{},"zh":{},"zh-Hant":{}};\n'
            'window.addEventListener("load", function(){});\n', encoding="utf-8")
    mod.build_index_page([], stats, coverage)
    print("home pages:", sum(1 for p in ("index.html", "es/index.html", "zh/index.html",
                                          "zh-hant/index.html") if (out / p).exists()))
    # About（E4 的加载说明落在这一页）
    mod.build_about(stats, coverage, [])
    print("about.html:", (out / "about.html").stat().st_size, "B")
    # 成分页（task-6 的收起块）——只渲染指定成分
    mod.SUB_NAME_LANG.clear()
    for sid, nl in db.execute("SELECT substance_id, name_lang FROM substance"):
        mod.SUB_NAME_LANG[sid] = nl or ""
    mod.load_substance_zh(db)
    mod.DRUG_PAGE_IDS.update(r[0] for r in db.execute("SELECT substance_id FROM substance"))
    n = mod.build_drug_pages(db, [], only_sids=drug_sids)
    print("drug pages:", n, "->", sorted(p.name for p in (out / "drug").glob("*.html")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
