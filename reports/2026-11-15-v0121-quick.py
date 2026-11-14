"""快速验证包：渲染 home/about/drug 到指定目录，并从已构建产物复制 data/idx 让结果页可跑。

用法：$py reports/2026-11-15-v0121-quick.py .tmp/v0121-quick [--with-data .tmp/v0121]
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_build():
    spec = importlib.util.spec_from_file_location("v0121_build", ROOT / "site" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    out = ROOT / (sys.argv[1] if len(sys.argv) > 1 else ".tmp/v0121-quick")
    out.mkdir(parents=True, exist_ok=True)
    mod = load_build()
    mod.OUT = out
    mod.BUILD_V = mod._compute_build_v()
    mod.MAKERS = {}
    db = sqlite3.connect(f"file:{ROOT / 'data' / 'drugs.db'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    stats = {"products": 0, "substances": 0, "atc": 0, "keys": 0, "nickname": 0, "aliases": 0,
             "confusable": 0, "severe": 0, "atc_pct": 0.0, "drug_term": 0,
             "nickname_total": 0, "nickname_merged": 0}
    coverage = [dict(r) for r in db.execute("SELECT * FROM coverage ORDER BY country")]
    mod._merge_static_i18n({})
    mod._install_zh_hant({})
    mod._inject_release_liners()
    (out / "assets").mkdir(parents=True, exist_ok=True)
    (out / "assets" / "i18n.js").write_text(
        "window.I18N=" + json.dumps({c: mod.I18N[c] for c in ("en", "es", "zh", "zh-Hant")},
                                    ensure_ascii=False, separators=(",", ":")) + ";\n"
        + "window.T=function(k){var L=window.__I18N_PARTIAL||'en';var D=window.I18N[L]||{};"
          "var E=window.I18N.en;return (D[k]!==undefined?D[k]:(E[k]!==undefined?E[k]:k));};\n"
          "function apply(){document.querySelectorAll('[data-i18n]').forEach(function(el){"
          "var v=window.T(el.getAttribute('data-i18n'));if(v!=null)el.textContent=v;});"
          "document.querySelectorAll('[data-ph]').forEach(function(el){"
          "el.placeholder=window.T(el.dataset.ph);});}\n"
          "window.addEventListener('load', apply);\n", encoding="utf-8")
    _css = mod.CSS.encode("utf-8")
    (out / "assets" / mod.CSS_FILE.split("/")[-1]).write_bytes(_css)
    (out / "assets" / "style.css").write_bytes(_css)
    _t2s = mod._load_zh_hant_t2s()
    _app_js = (mod.APP_JS.replace("REPORT_REPO_PLACEHOLDER", mod.REPORT_REPO)
               .replace("__DETAIL_ROW_FIELDS__", json.dumps(mod.DETAIL_ROW_FIELDS,
                                                           ensure_ascii=False))
               .replace("__T2S_JSON__", json.dumps(_t2s, ensure_ascii=False,
                                                   separators=(",", ":")))
               .replace("data/idx/core.json", f"data/idx/core.json?v={mod.BUILD_V}")
               .replace("data/idx/pinyin.json", f"data/idx/pinyin.json?v={mod.BUILD_V}")
               .replace("data/idx/manifest.json", f"data/idx/manifest.json?v={mod.BUILD_V}"))
    (out / "assets" / "app.js").write_text(_app_js, encoding="utf-8")
    _boot = ROOT / "site" / "dist" / "assets" / "boot.js"
    if _boot.exists():
        (out / "assets" / "boot.js").write_text(
            _boot.read_text(encoding="utf-8") + "\n" + mod._mkblock_js(), encoding="utf-8")
    # 索引数据（结果页要真实跑）：从已构建产物复制，别改 dist
    src_data = ROOT / (sys.argv[2] if len(sys.argv) > 2 else ".tmp/v0121") / "data"
    if src_data.is_dir():
        dst = out / "data"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src_data, dst)
        print(f"data copied from {src_data}")

    mod.build_coverage_page(db, coverage, [])
    mod.build_index_page([], stats, coverage)
    mod.build_about(stats, coverage, [])
    mod.SUB_NAME_LANG.clear()
    for sid, nl in db.execute("SELECT substance_id, name_lang FROM substance"):
        mod.SUB_NAME_LANG[sid] = nl or ""
    mod.load_substance_zh(db)
    mod.DRUG_PAGE_IDS.update(r[0] for r in db.execute("SELECT substance_id FROM substance"))
    mod.build_drug_pages(db, [], only_sids={"amlodipine", "acetaminophen"})
    print("rendered:", sorted(p.name for p in out.glob("*.html")), "drug/amlodipine.html")


if __name__ == "__main__":
    main()
