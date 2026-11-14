"""T16 四语文案自检：新增 key 在 en / es / zh / zh-Hant（+fr）都有值，且 zh-Hant 不回落简体。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = ["fam.rel.multi", "fam.rel.multi_unknown", "fam.rel.multi_why",
        "name.rel_multi_title", "name.rel_unknown_title", "name.rel_note", "t11.multi"]
spec = importlib.util.spec_from_file_location("t16_build", ROOT / "site" / "build.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)
mod._merge_static_i18n({})
mod._install_zh_hant({})

bad = sorted(set(mod.ZH_HANT_FALLBACK_KEYS) - mod.ZH_HANT_FALLBACK_OK)
print(f"zh-Hant 只能回落简体的 key: {len(bad)} 个")
missing = []
for key in KEYS:
    print(f"\n[{key}]")
    for lang in ("en", "es", "zh", "zh-Hant", "fr"):
        val = mod.I18N[lang].get(key)
        print(f"  {lang:8} {val}")
        if not val:
            missing.append((lang, key))
print(f"\n缺失: {missing or '无'}")
print("键数：", {lang: len(mod.I18N[lang]) for lang in ("en", "es", "zh", "zh-Hant", "fr")})
