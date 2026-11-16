"""R5 探针：只渲染指定成分页到临时目录，用于「未公开规格」块 before / after 对照。

不写 site/dist、不写库（只读开库）。用法：

    $py reports/2026-11-17-r5-undisclosed-probe.py .tmp/r5-before tirzepatide acetaminophen

然后对生成的 HTML 用 `--dump` 抽出市场块 / 未公开段数字（见 main 里的 dump_block）。
"""
from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_build():
    spec = importlib.util.spec_from_file_location("r5_build", ROOT / "site" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def dump_block(html: str) -> list[dict]:
    """从成分页 HTML 抽出每个市场块的计数事实（正则，够用且不依赖 HTML 解析器）。"""
    out: list[dict] = []
    for m in re.finditer(r'<details class="mkblock".*?</details>', html, re.S):
        seg = m.group(0)
        mk = re.search(r'data-mk="([A-Z]+)"', seg)
        head = re.search(r'<summary class="mkhead">(.*?)</summary>', seg, re.S)
        head_txt = re.sub(r"<[^>]+>", " ", head.group(1)) if head else ""
        spec = re.search(r'<span class="mkspec"[^>]*>(.*?)</span>', seg, re.S)
        spec_txt = re.sub(r"<[^>]+>", " ", spec.group(1)) if spec else ""
        und = re.search(r'<details class="undis">(.*?)</details>', seg, re.S)
        und_txt = ""
        chips: list[str] = []
        if und:
            body = und.group(1)
            summ = re.search(r"<summary>(.*?)</summary>", body, re.S)
            und_txt = re.sub(r"<[^>]+>", " ", summ.group(1)) if summ else ""
            chips = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                     for c in re.findall(r'<span class="uname">(.*?)</span>\s*</span>',
                                         body, re.S)]
        out.append({"mk": mk.group(1) if mk else "?", "records": " ".join(head_txt.split()),
                    "spec": " ".join(spec_txt.split()),
                    "undisclosed": " ".join(und_txt.split()), "chips": chips})
    return out


def main() -> int:
    out = ROOT / (sys.argv[1] if len(sys.argv) > 1 else ".tmp/r5-probe")
    sids = [s for s in sys.argv[2:] if s]
    if not sids:
        print("需要至少一个 substance_id（inn_en）")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    mod = load_build()
    mod.OUT = out
    mod.BUILD_V = mod._compute_build_v()
    # 五语字典：服务端四语块（_lang_block_text）靠这两步才有真值
    mod._merge_static_i18n({})
    mod._install_zh_hant({})
    db = sqlite3.connect(f"file:{ROOT / 'data' / 'drugs.db'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    # 名称显示串：与 load_index() 同口径（name_variant 里同 key 的第一条 raw）
    displays: dict[str, str] = {}
    for key_id, raw in db.execute("SELECT key_id, raw FROM name_variant ORDER BY key_id, v_id"):
        displays.setdefault(key_id, raw)
    entries = [{"k": k, "d": v, "u": ""} for k, v in displays.items()]
    mod.SUB_NAME_LANG.clear()
    for sid, nl in db.execute("SELECT substance_id, name_lang FROM substance"):
        mod.SUB_NAME_LANG[sid] = nl or ""
    mod.load_substance_zh(db)
    mod.DRUG_PAGE_IDS.update(r[0] for r in db.execute("SELECT substance_id FROM substance"))
    # 只渲染指定成分：不在列表里的 substance 会被 only_sids 过滤掉
    wanted = {sid for sid in sids}
    n = mod.build_drug_pages(db, entries, only_sids=wanted)
    print(f"drug pages: {n}")
    facts = {}
    for sid in sids:
        sid = sid.strip()
        if not sid:
            continue
        path = out / "drug" / f"{sid}.html"
        if not path.exists():
            print(f"缺页 {sid} → {path}")
            continue
        facts[sid] = dump_block(path.read_text(encoding="utf-8"))
        print(f"\n## {sid}")
        for row in facts[sid]:
            print(f"  [{row['mk']}] {row['records']} || spec[{row['spec']}] "
                  f"|| und[{row['undisclosed']}] || chips={row['chips']}")
    (out / "r5-facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    return 0 if len(facts) == len(wanted) else 1


if __name__ == "__main__":
    sys.exit(main())
