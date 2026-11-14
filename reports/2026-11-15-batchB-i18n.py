"""把当前 build.py 的 i18n 字典写成 assets/i18n.js（证据构建用；正式构建由 main() 写）。

用法：$py reports/2026-11-15-batchB-i18n.py .tmp/v01110
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / (sys.argv[1] if len(sys.argv) > 1 else ".tmp/v01110")

spec = importlib.util.spec_from_file_location("v01110_build", ROOT / "site" / "build.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)
mod._merge_static_i18n({})
mod._install_zh_hant({})

dicts = {c: mod.I18N[c] for c in ("en", "es", "zh", "zh-Hant")}
js = ("window.I18N=" + json.dumps(dicts, ensure_ascii=False, separators=(",", ":")) + ";\n"
      # 最小 apply()：只做 [data-i18n] 文本 / [data-i18n-aria] / [data-i18n-html] 替换，
      # 够证据渲染用（正式 i18n.js 还有语言切换、字段级逻辑等）。
      "function __apply(){var L=window.__I18N_PARTIAL||'en';var D=window.I18N[L]||{};var E=window.I18N.en;"
      "document.querySelectorAll('[data-i18n]').forEach(function(el){var k=el.getAttribute('data-i18n');"
      "var v=D[k]||E[k];if(v!=null)el.textContent=v;});"
      "document.querySelectorAll('[data-i18n-aria]').forEach(function(el){var k=el.getAttribute('data-i18n-aria');"
      "var v=D[k]||E[k];if(v!=null)el.setAttribute('aria-label',v);});"
      "document.querySelectorAll('[data-i18n-html]').forEach(function(el){var k=el.getAttribute('data-i18n-html');"
      "var v=D[k]||E[k];if(v!=null)el.innerHTML=v;});"
      "document.querySelectorAll('html')[0].setAttribute('lang',L);}\n"
      "window.T=function(k){var L=window.__I18N_PARTIAL||'en';var D=window.I18N[L]||{};"
      "return (D[k]!==undefined?D[k]:(window.I18N.en[k]!==undefined?window.I18N.en[k]:k));};\n"
      "function apply(){try{__apply();}catch(e){}}\n"
      "window.addEventListener('load', apply);\n")
(out / "assets").mkdir(parents=True, exist_ok=True)
(out / "assets" / "i18n.js").write_text(js, encoding="utf-8")
print(f"i18n.js: {len(js):,} B · en {len(dicts['en'])} keys")
