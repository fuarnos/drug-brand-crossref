# -*- coding: utf-8 -*-
"""从 COFEPRIS《Registros Sanitarios de Medicamentos PRORROGADOS AAAA》PDF 抽续期清单。

为什么值得单独抽：续期清单里有**2001 年以前批的注册号**（3790、0136M79、023M94 这种），
而「Expdidos 2001–2026」那 26 个文件只列新批的。所以这份清单同时补两件事：
  1. 老注册号的续期到期日（拿来修正状态）
  2. 只出现在续期清单里的老产品（品牌 / 通用名 / 剂型 / 持有人）

版式（2011/2012/2013 三份实体清单 + 5 份孤儿药清单）：
  Registro · Denominación distintiva · Denominación genérica · Forma farmacéutica ·
  Clasificación Art.226 · Titular · Vencimiento/Vigencia

输出 data/raw/mx/cofepris_prorrogas.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, ".pylibs")
import pymupdf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "mx"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_cofepris_alop import looks_like_form, norm, strip_acc  # noqa: E402

ANCHOR_RE = re.compile(r"^\d{3,5}(?:M\d{2,4})?$")
MONTHS = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
          "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}
RE_DATE = re.compile(r"^(\d{1,2})-([a-záéíóú]{3})-(\d{2,4})$", re.I)


def is_date(s: str) -> bool:
    m = RE_DATE.match((s or "").strip())
    if not m:
        return False
    return strip_acc(m.group(2)).lower() in MONTHS


def clean_reg(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", s or "")


def block_lines(page) -> list[str]:
    lines = [norm(x) for x in page.get_text("text").splitlines()]
    drop = ("comisión de autorización", "dirección ejecutiva", "relación de registros",
            "registros de medicamentos", "fecha de actualización", "página ",
            "consejo de salubridad", "fuente:")
    return [l for l in lines if l and not any(l.lower().startswith(d) for d in drop)]


def parse_block(block: list[str]) -> dict[str, str] | None:
    """registro · 商品名 · 通用名 · 剂型 · 分类 · 持有人 · 有效期"""
    if len(block) < 4:
        return None
    vigencia = ""
    # 2011 那份末尾多一列 "MG"，先剥掉再找日期
    if len(block) >= 2 and not is_date(block[-1]) and len(block[-1]) <= 4 \
            and is_date(block[-2]):
        block.pop()
    if is_date(block[-1]):
        vigencia = block.pop()
    form_i = next((i for i in range(len(block) - 1, 0, -1) if looks_like_form(block[i])), None)
    if form_i is None:
        return None
    form = block[form_i]
    left, right = block[:form_i], block[form_i + 1:]
    class226 = ""
    if right and re.match(r"^(I{1,3}|IV|V|VI)$", right[0]):
        class226 = right.pop(0)
    holder = " ".join(right).strip()
    if len(left) < 2:
        return None
    brand, generic = left[0], " / ".join(left[1:])
    return {"brand": brand, "generic": generic, "form": form,
            "holder": holder, "class226": class226, "vigencia": vigencia}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(RAW / "cofepris_prorrogas.csv"))
    args = ap.parse_args()

    pdfs = sorted(p for p in RAW.glob("*.pdf") if re.search(r"prorrog", p.name, re.I))
    print(f"PDF {len(pdfs)} 个")

    total = 0
    with Path(args.out).open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["registro", "brand", "generic", "form", "class226", "holder",
                    "vigencia", "src_year", "src_file"])
        for pdf in pdfs:
            m = re.search(r"(19|20)\d{2}", pdf.name)
            src_year = m.group(0) if m else ""
            doc = pymupdf.open(pdf)
            n = 0
            seen: set[str] = set()
            for pno in range(doc.page_count):
                lines = block_lines(doc[pno])
                starts = [i for i, l in enumerate(lines) if ANCHOR_RE.match(l.strip())]
                for k, i in enumerate(starts):
                    end = starts[k + 1] if k + 1 < len(starts) else len(lines)
                    rec = parse_block(lines[i + 1:end])
                    if not rec:
                        continue
                    reg = clean_reg(lines[i])
                    if reg in seen:
                        continue
                    seen.add(reg)
                    w.writerow([reg, rec["brand"], rec["generic"], rec["form"],
                                rec["class226"], rec["holder"], rec["vigencia"],
                                src_year, pdf.name])
                    n += 1
            total += n
            print(f"  {pdf.name:<40} pages={doc.page_count:<3} rows={n}")
    print(f"总计 {total:,} 行 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
