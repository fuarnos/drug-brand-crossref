#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 WHO INN 官方列表 PDF 解析成多语言名称表 data/who_inn_names.csv。

PDF 版式（WHO IRIS / who.int 的三语版，1990s–2013 与近期 Proposed List）：
每个 INN 条目是一个以 **粗体拉丁名** 开头的文本块，块内按段落依次给出：
    Latin 名（粗体）
    English 名 + 英文说明
    French 名 + 法文说明
    Spanish 名 + 西文说明
    （化学式/CAS/抗体序列等附加块，忽略）
段落边界用行距判断：同一段内 y 间距≈8.7pt，跨语言段落≈17pt。

局限：官方公开电子版只含 Latin/English/French/Spanish 四种写法；
中文/俄文/阿拉伯文版本未见公开下载，因此 inn_zh/inn_ru/inn_ar 列为空
（详见 reports/who-inn-20261026.md）。

用法：
    python etl/parse_who_inn.py              # 解析 data/raw/who_inn/ 下已下载 PDF
    python etl/parse_who_inn.py --stats      # 额外打印每文件条目数与抽样
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "who_inn"
OUT = ROOT / "data" / "who_inn_names.csv"
sys.path.insert(0, str(ROOT / ".pylibs"))
try:
    import pymupdf  # type: ignore
except ImportError:  # pragma: no cover
    pymupdf = None

SKIP_HEADS = ("who drug information", "proposed inn", "recommended inn",
              "international nonproprietary", "lists of proposed", "notice is hereby",
              "des substances pharmaceutiques", "para las sustancias",
              "dénominations communes", "denominaciones comunes", "dci ")
RE_TRAIL = re.compile(r"\s*[#*†‡]\s*$")
# 语言识别词表（段落内出现即加分）
MARKERS = {
    "fr": ("dérivé", "acide", "éthyl", "méthyl", "chlorhydrate", "sodique",
           "propionique", "l'", "d'", "antagoniste", "inhibiteur", "modulateur",
           "agoniste", "anticorps", "immunoglobuline", "protéine", "sérique",
           "solution", "utilisé", "facteur", "sel de", "ester", "anhydre"),
    "es": ("ácido", "derivado", "etil", "metil", "clorhidrato", "sódico",
           "propiónico", "antagonista", "inhibidor", "modulador", "agonista",
           "anticuerpo", "inmunoglobulina", "proteína", "sérica", "solución",
           "utilizado", "factor", "sal de", "éster", "anhidro", "para"),
    "en": ("acid", "derivative", "ethyl", "methyl", "hydrochloride", "sodium",
           "antagonist", "inhibitor", "modulator", "agonist", "antibody",
           "immunoglobulin", "protein", "serum", "solution", "used", "factor",
           "salt", "ester", "anhydrous"),
}


def text_of_lines(block: dict) -> list[dict]:
    """block → [{text, y0, y1, bold}]，过滤空行。"""
    out = []
    for line in block.get("lines", []):
        txt = "".join(s["text"] for s in line.get("spans", [])).strip()
        if not txt:
            continue
        fonts = [s.get("font", "") for s in line.get("spans", [])]
        flags = [s.get("flags", 0) for s in line.get("spans", [])]
        out.append(dict(text=txt, y0=line["bbox"][1], y1=line["bbox"][3],
                        x0=line["bbox"][0],
                        bold=any("Bold" in f for f in fonts) or any(f & 16 for f in flags)))
    return out


def split_paragraphs(lines: list[dict], gap: float = 12.0) -> list[list[dict]]:
    """按 y 间距把行分成段落。"""
    paras: list[list[dict]] = []
    cur: list[dict] = []
    prev_y = None
    for ln in lines:
        if prev_y is not None and ln["y0"] - prev_y > gap:
            if cur:
                paras.append(cur)
            cur = []
        cur.append(ln)
        prev_y = ln["y0"]
    if cur:
        paras.append(cur)
    return paras


def lang_score(text: str, lang: str) -> int:
    low = text.lower()
    return sum(1 for w in MARKERS[lang] if w in low)


def classify_lang(text: str) -> str | None:
    """段落语言粗判：fr/es/en，都不像则 None。"""
    s = {k: lang_score(text, k) for k in ("fr", "es", "en")}
    best = max(s, key=s.get)
    if s[best] == 0:
        return None
    # 有明显法语/西语特征才认（英文化学描述也常含 "acid" 等，避免误判）
    if best == "fr" and s["fr"] >= 2 and s["fr"] > s["es"]:
        return "fr"
    if best == "es" and s["es"] >= 2 and s["es"] > s["fr"]:
        return "es"
    if s["en"] >= 2 and s["en"] >= s["fr"] and s["en"] >= s["es"]:
        return "en"
    return None


def clean_name(s: str) -> str:
    s = RE_TRAIL.sub("", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def name_like(s: str) -> bool:
    """像 INN 名：字母为主、不含化学式式的数字串、长度合理。"""
    if not s or len(s) > 80 or len(s) < 3:
        return False
    if re.search(r"\d", s):
        return False
    if s.endswith((".", ";", ":")):
        return False
    if not re.match(r"^[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\-\s()']*$", s):
        return False
    return 1 <= len(s.split()) <= 6


def parse_pdf(path: Path) -> tuple[list[dict], dict]:
    """解析单个 PDF → (entries, stats)。

    兼容两种版式：
      * 2001+ 版：一个条目 = 一个块，块内用行距分出 EN/FR/ES 段；
      * 1990s 版：EN/FR/ES 各占一个独立块（只有 EN 块以粗体拉丁名开头）。
    统一做法：按块顺序扫描，块内按行距分段，用语言特征 + “EN→FR→ES”次序落到条目上。
    """
    doc = pymupdf.open(path)
    stats = dict(pages=doc.page_count, blocks=0, header_blocks=0,
                 entries=0, with_fr=0, with_es=0, skipped=0)
    entries: list[dict] = []
    cur: dict | None = None

    def flush() -> None:
        nonlocal cur
        if cur and cur.get("inn_en") and name_like(cur["inn_en"]):
            entries.append(cur)
            stats["entries"] += 1
            stats["with_fr"] += bool(cur.get("inn_fr"))
            stats["with_es"] += bool(cur.get("inn_es"))
        elif cur:
            stats["skipped"] += 1
        cur = None

    for page in doc:
        d = page.get_text("dict")
        blocks = [b for b in d.get("blocks", []) if b.get("type") == 0]
        blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
        for block in blocks:
            lines = text_of_lines(block)
            if not lines:
                continue
            stats["blocks"] += 1
            first = lines[0]
            head = first["text"]
            if first["bold"] and not any(head.lower().startswith(s) for s in SKIP_HEADS) \
                    and not re.fullmatch(r"\d{1,4}", head) and len(head) <= 80 \
                    and not head.endswith("."):
                # 新条目开始
                flush()
                stats["header_blocks"] += 1
                paras = split_paragraphs(lines)
                p0 = paras[0]
                cand = [x for x in p0[1:]] + [x for x in (paras[1][:1] if len(paras) > 1 else [])]
                en = ""
                for x in cand:
                    if name_like(x["text"]):
                        en = clean_name(x["text"])
                        break
                cur = dict(inn_latin=clean_name(p0[0]["text"]), inn_en=en,
                           inn_fr="", inn_es="", _expect=["fr", "es"])
                # 同一块里的后续段落继续喂给状态机
                feed_paras(paras[1:], cur, stats)
                continue
            if cur is not None:
                feed_paras(split_paragraphs(lines), cur, stats)
    flush()
    doc.close()
    return entries, stats


def feed_paras(paras: list[list[dict]], cur: dict, stats: dict) -> None:
    """把段落按 EN→FR→ES 的期望顺序落到当前条目。"""
    for para in paras:
        txt = " ".join(x["text"] for x in para)
        lang = classify_lang(txt)
        expect = cur["_expect"]
        if not expect:
            return
        # 名称行：段落首行应像名字；不是则跳过（化学式/序列等）
        cand = para[0]["text"]
        if not name_like(cand):
            continue
        if lang == expect[0]:
            key = "inn_fr" if expect[0] == "fr" else "inn_es"
            cur[key] = clean_name(cand)
            expect.pop(0)
        elif lang in ("fr", "es"):
            # 顺序与期望不符：按首次出现的语言落位
            key = "inn_fr" if lang == "fr" else "inn_es"
            if not cur[key]:
                cur[key] = clean_name(cand)
                if lang in expect:
                    expect.remove(lang)
        elif lang == "en":
            continue
        elif len(para) <= 2 and len(cand.split()) <= 6:
            # 语言特征不足的短名称段：按期望顺序兜底
            key = "inn_fr" if expect[0] == "fr" else "inn_es"
            if not cur[key]:
                cur[key] = clean_name(cand)
                expect.pop(0)


def is_name_like(s: str) -> bool:
    if not s or len(s) > 60:
        return False
    if not re.match(r"^[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\-\s\u00b7()]*$", s):
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="解析 WHO INN 列表 PDF → data/who_inn_names.csv")
    ap.add_argument("--stats", action="store_true", help="打印每文件统计与抽样")
    args = ap.parse_args()
    if pymupdf is None:
        raise SystemExit("需要 pymupdf（见 .pylibs/）")
    meta_path = RAW / "meta.json"
    if not meta_path.exists():
        raise SystemExit(f"缺少 {meta_path}，先运行 etl/fetch_who_inn.py --download")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    rows: list[dict] = []
    per_file: list[dict] = []
    for key in sorted(meta["files"]):
        info = meta["files"][key]
        pdf = RAW / info["path"]
        if not pdf.exists():
            print(f"! 缺文件 {pdf}", file=sys.stderr)
            continue
        entries, st = parse_pdf(pdf)
        per_file.append(dict(key=key, **st))
        seq = 0
        for e in entries:
            if not is_name_like(e["inn_en"]):
                continue
            seq += 1
            rows.append(dict(
                inn_number=f"{info['series'][:2].upper()}{info['list_no']:03d}-{seq:03d}",
                inn_en=e["inn_en"], inn_zh="", inn_es=e["inn_es"],
                inn_fr=e["inn_fr"], inn_ru="", inn_ar="",
                list_no=info["list_no"], series=info["series"],
                inn_latin=e["inn_latin"], source_url=info["source_url"],
                license=info["license"],
            ))
        print(f"{key:<28} pages={st['pages']:>3} entries={st['entries']:>3} "
              f"fr={st['with_fr']:>3} es={st['with_es']:>3}")
    # 去重：同一 en 名（proposed 与 recommended 可能重复）保留信息最全的一条
    best: dict[str, dict] = {}
    order: list[str] = []
    for r in rows:
        k = r["inn_en"].lower()
        if k not in best:
            best[k] = r
            order.append(k)
            continue
        cur = best[k]
        score = lambda x: sum(bool(x[f]) for f in ("inn_es", "inn_fr"))
        if score(r) > score(cur):
            best[k] = r
    dedup = [best[k] for k in order]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cols = ["inn_number", "inn_en", "inn_zh", "inn_es", "inn_fr", "inn_ru", "inn_ar",
            "list_no", "series", "inn_latin", "source_url", "license"]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in dedup:
            w.writerow(r)
    print(f"\n写入 {OUT}: {len(dedup)} 条（去重前 {len(rows)}）")
    print("有西语名:", sum(1 for r in dedup if r["inn_es"]),
          "有法语名:", sum(1 for r in dedup if r["inn_fr"]))
    if args.stats:
        for st in per_file[:5]:
            print(st)
        print("\n抽样（前 15）:")
        for r in dedup[:15]:
            print(" ", r["inn_number"], "|", r["inn_en"], "|", r["inn_fr"], "|", r["inn_es"])
    (ROOT / "data" / "raw" / "who_inn" / "parse_stats.json").write_text(
        json.dumps(dict(per_file=per_file, total_rows=len(rows),
                        dedup_rows=len(dedup),
                        with_es=sum(1 for r in dedup if r["inn_es"]),
                        with_fr=sum(1 for r in dedup if r["inn_fr"])),
                   ensure_ascii=False, indent=1),
        encoding="utf-8")


if __name__ == "__main__":
    main()
