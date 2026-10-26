# -*- coding: utf-8 -*-
"""从 COFEPRIS《Registros Sanitarios de Medicamentos REVOCADOS / CANCELADOS AAAA》PDF 抽注销清单。

用途：给 alopáticos 主表打状态（revocado → withdrawn，cancelado → withdrawn），
并把注销年份写进 product.status_date。

两套版式：
  B 版（2015 起，与 alopáticos 同构）：registro · titular · distintiva · genérica · class226 · forma · estatus
  R 版（2010 年前后）：registro [SSA] · distintiva · forma · titular · causa

输出 data/raw/mx/cofepris_status.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, ".pylibs")
import pymupdf  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_cofepris_alop import (  # noqa: E402
    FORM_WORDS, looks_like_form, norm, strip_acc,
)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "mx"

ANCHOR_RE = re.compile(r"^\d{3,4}M\d{2,5}(?:\s*SSA)?$")
STATUS_TOKENS = {"revocado", "cancelado", "revocada", "cancelada", "concluido"}


def block_lines(page) -> list[str]:
    lines = [norm(x) for x in page.get_text("text").splitlines()]
    drop = ("comisión de autorización", "dirección ejecutiva", "registros sanitarios de medicamentos",
            "fecha de actualización", "página ", "consejo de salubridad", "fuente:")
    return [l for l in lines if l and not any(l.lower().startswith(d) for d in drop)]


def parse_block_r(block: list[str]) -> dict[str, str] | None:
    """registro · distintiva · forma · titular · causa"""
    if len(block) < 3:
        return None
    form_i = next((i for i in range(1, len(block)) if looks_like_form(block[i])), None)
    if form_i is None:
        return None
    brand, form = block[0], block[form_i]
    rest = block[1:form_i] + block[form_i + 1:]
    if not rest:
        return None
    causa = rest[-1] if len(rest) > 1 else ""
    holder = " ".join(rest[:-1]) if len(rest) > 1 else rest[0]
    return {"brand": brand, "generic": "", "form": form, "holder": holder,
            "class226": "", "causa": causa, "estatus": ""}


def parse_block_b(block: list[str]) -> dict[str, str] | None:
    """registro · titular · distintiva · genérica · class226 · forma · estatus"""
    if len(block) < 4:
        return None
    estatus = ""
    if strip_acc(block[-1]).lower() in STATUS_TOKENS:
        estatus = block.pop()
    form_i = next((i for i in range(len(block) - 1, 0, -1) if looks_like_form(block[i])), None)
    if form_i is None:
        return None
    form = block[form_i]
    rest = block[:form_i] + block[form_i + 1:]
    class226 = ""
    if rest and re.match(r"^(I{1,3}|IV|V|VI)$", rest[-1]):
        class226 = rest.pop()
    if len(rest) < 2:
        return None
    return {"brand": rest[1], "generic": " / ".join(rest[2:]), "form": form,
            "holder": rest[0], "class226": class226, "causa": "", "estatus": estatus}


def detect_layout(doc) -> str:
    txt = doc[0].get_text().lower()
    return "R" if "causa" in txt else "B"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(RAW / "cofepris_status.csv"))
    args = ap.parse_args()

    pdfs = sorted(p for p in RAW.glob("*.pdf") if re.search(r"revoc|cancel", p.name, re.I))
    print(f"PDF {len(pdfs)} 个")

    total = 0
    with Path(args.out).open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["src_year", "src_file", "kind", "registro", "brand", "generic",
                    "form", "holder", "cause", "estatus", "page"])
        for pdf in pdfs:
            kind = "revocado" if re.search(r"revoc", pdf.name, re.I) else "cancelado"
            m = re.search(r"(19|20)\d{2}", pdf.name)
            src_year = m.group(0) if m else ""
            doc = pymupdf.open(pdf)
            layout = detect_layout(doc)
            n = 0
            seen: set[str] = set()
            for pno in range(doc.page_count):
                lines = block_lines(doc[pno])
                starts = [i for i, l in enumerate(lines) if ANCHOR_RE.match(l)]
                for k, i in enumerate(starts):
                    end = starts[k + 1] if k + 1 < len(starts) else len(lines)
                    rec = parse_block_r(lines[i + 1:end]) if layout == "R" else parse_block_b(lines[i + 1:end])
                    if not rec:
                        continue
                    reg = re.sub(r"[^0-9A-Za-z]", "", lines[i])
                    if reg in seen:
                        continue
                    seen.add(reg)
                    w.writerow([src_year, pdf.name, kind, reg, rec["brand"], rec["generic"],
                                rec["form"], rec["holder"], rec["causa"], rec["estatus"], pno + 1])
                    n += 1
            total += n
            print(f"  {pdf.name:<38} kind={kind:<10} layout={layout} pages={doc.page_count:<3} rows={n}")
    print(f"总计 {total:,} 行 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
