# -*- coding: utf-8 -*-
"""从 COFEPRIS《Registros Sanitarios de Medicamentos Alopáticos Expedidos AAAA》PDF 抽产品表。

26 个 PDF（2001–2026），列序随年份变化，所以按表头文本定位列，不按位置写死。
输出 data/raw/mx/cofepris_alopaticos.csv。

已知口径（重要）：
- 这是「当年新批（expedidos）」清单，不是「当前在册」清单。
- **没有浓度/规格列**。只有 品名 · 通用名 · 剂型 · 持有人 · 注册号 · 有效期。
- 2001–2010 用 NOMBRE COMERCIAL / GENÉRICO，2011 起改成 Denominación distintiva / genérica。
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

# 表头别名：按子串命中，顺序即优先级（越具体的放前面）
HEADER_RULES = [
    ("registro", "registro"),
    ("distintiva", "brand"),
    ("comercial", "brand"),
    ("denominaci", "generic"),   # 只出现在「Denominación genérica」
    ("genéric", "generic"),
    ("generic", "generic"),
    ("forma", "form"),
    ("titular", "holder"),
    ("226", "class226"),
    ("vigencia", "vigencia"),
    ("estado", "estado"),
    ("tipo de medicamento", "tipo"),
]

FIELDS = ["registro", "brand", "generic", "form", "holder", "class226", "vigencia", "estado", "tipo"]

# 注册号：001M2023 / 0383M79 / 572M2000 / 86610 / 79384 …
REG_RE = re.compile(r"^\s*\d{3,6}\s*[A-Z]?\s*\d{0,4}\s*$")
ANCHOR_TXT_RE = re.compile(r"^(?:\d{3,4}M\d{2,4}|\d{5})$")
DATE_RE = re.compile(r"^\d{1,2}[-/][a-záéíóú]{3}[-/]\d{4}$|^\d{1,2}/\d{1,2}/\d{4}$", re.I)
ROMAN_RE = re.compile(r"^(I{1,3}|IV|V|VI|VII|VIII|IX|X)\b")
STATUS_WORDS = {"aprobado", "vigente", "suspendido", "cancelado", "negado", "vencido",
                "prorrogado", "en trámite", "en tramite", "concluido"}

# 剂型词表（去重音、小写后比对）
FORM_WORDS = (
    "solucion", "soluciones", "tableta", "tabletas", "comprimido", "comprimidos",
    "capsula", "capsulas", "gragea", "grageas", "jarabe", "polvo", "suspension",
    "crema", "unguento", "pomada", "gel", "gotas", "inyectable", "supositorio",
    "ovulo", "parche", "aerosol", "espuma", "shampoo", "emulsion", "locion",
    "elixir", "colirio", "jalea", "pasta", "granulado", "cristales", "liquido",
    "solução", "suspensión", "solución", "ampolleta", "sobre", "sachet", "implante",
    "pelicula", "película", "bucal", "sublingual", "nasal", "rectal", "vaginal",
    "oftalmica", "oftálmica", "topica", "tópica", "intravenosa", "oral",
)


def strip_acc(s: str) -> str:
    table = str.maketrans("áéíóúÁÉÍÓÚüÜñÑ", "aeiouAEIOUuUnN")
    return s.translate(table)


def looks_like_form(s: str) -> bool:
    t = strip_acc(s).lower()
    return any(w in t for w in FORM_WORDS) and len(s) <= 60


def looks_like_vigencia(s: str) -> bool:
    t = strip_acc(s).strip().lower()
    return bool(DATE_RE.match(s.strip())) or t in STATUS_WORDS


def norm(v) -> str:
    if v is None:
        return ""
    return re.sub(r"[ \t]+", " ", str(v).replace("\n", " ")).strip()


def is_header(cells: list[str]) -> bool:
    joined = " ".join(c.lower() for c in cells)
    return "registro" in joined and (
        "distintiva" in joined or "comercial" in joined or "genéric" in joined or "generic" in joined
    )


def map_header(cells: list[str]) -> dict[int, str]:
    out: dict[int, str] = {}
    for i, c in enumerate(cells):
        key = norm(c).lower().strip(" :.")
        if not key:
            continue
        for needle, field in HEADER_RULES:
            if needle in key:
                out.setdefault(i, field)
                break
    return out


def rows_from_page(page) -> tuple[list[list[str]], dict[int, str] | None]:
    """返回 (数据行, 本页列映射)。列映射由页内表头行给出，缺省时沿用上一页。"""
    try:
        tabs = page.find_tables()
    except Exception:  # noqa: BLE001
        return [], None
    if not tabs.tables:
        return [], None
    data: list[list[str]] = []
    mapping: dict[int, str] | None = None
    for tab in tabs.tables:
        for raw in tab.extract():
            cells = [norm(c) for c in raw]
            if not any(cells):
                continue
            if is_header(cells):
                m = map_header(cells)
                if len(m) >= 2:
                    mapping = m
                continue
            if mapping is None:
                continue
            rec: dict[str, str] = {}
            for i, field in mapping.items():
                if i < len(cells):
                    rec[field] = cells[i]
            if not rec.get("registro") and not rec.get("brand"):
                continue
            data.append([rec.get(f, "") for f in FIELDS[:8]])
    return data, mapping


def _block_lines(page) -> list[str]:
    """按阅读顺序取行，丢掉页眉页脚。"""
    lines = [norm(x) for x in page.get_text("text").splitlines()]
    drop = ("comisión de autorización", "dirección ejecutiva", "registros sanitarios de medicamentos",
            "fecha de actualización", "página ", "consejo de salubridad", "fuente:", "comisión federal para")
    return [l for l in lines if l and not any(l.lower().startswith(d) for d in drop)]


def _parse_block(block: list[str], era_b: bool) -> dict[str, str] | None:
    """把一个注册号后面的若干行拆成字段。"""
    if len(block) < 3:
        return None

    # 续行合并：以 / 或 , 结尾的行与下一行同一字段
    merged: list[str] = []
    carry = ""
    for ln in block:
        cur = (carry + " " + ln).strip() if carry else ln
        if cur.endswith("/") or cur.endswith(","):
            carry = cur
            continue
        merged.append(cur)
        carry = ""
    if carry:
        merged.append(carry.rstrip("/,").strip())
    block = merged

    # 尾部：有效期 / 状态
    vigencia = ""
    if block and looks_like_vigencia(block[-1]):
        vigencia = block.pop()

    # 剂型：从尾部往前找
    form_i = next((i for i in range(len(block) - 1, -1, -1) if looks_like_form(block[i])), None)
    if form_i is None:
        return None
    form = block[form_i]
    body = block[:form_i] + block[form_i + 1:]

    # 分类（Roman numeral）紧贴剂型之前
    class226 = ""
    if body and ROMAN_RE.match(body[-1]) and len(body[-1]) <= 20:
        class226 = body.pop()

    if era_b:
        if len(body) < 3:
            return None
        holder, brand, generic = body[0], body[1], " / ".join(body[2:])
    else:
        if len(body) < 3:
            return None
        brand, generic, holder = body[0], " / ".join(body[1:-1]), body[-1]
    return {
        "registro": "", "brand": brand, "generic": generic, "form": form,
        "holder": holder, "class226": class226, "vigencia": vigencia, "estado": "",
    }


def rows_from_text(page, era_b: bool) -> list[list[str]]:
    """表格识别失效时（2011–2013 部分文件）按注册号锚点切块解析。"""
    lines = _block_lines(page)
    starts = [i for i, l in enumerate(lines) if ANCHOR_TXT_RE.match(l)]
    out: list[list[str]] = []
    for k, i in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        rec = _parse_block(lines[i + 1:end], era_b)
        if rec is None:
            continue
        rec["registro"] = lines[i]
        out.append([rec.get(f, "") for f in FIELDS[:8]])
    return out


def count_anchors(doc) -> int:
    return sum(len(ANCHOR_TXT_RE.findall(l)) for p in range(doc.page_count)
               for l in (norm(x) for x in doc[p].get_text("text").splitlines()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(RAW / "cofepris_alopaticos.csv"))
    args = ap.parse_args()

    pdfs = sorted(
        p for p in RAW.glob("*.pdf")
        if re.search(r"alop|regalopa", p.name, re.I)
    )
    print(f"PDF {len(pdfs)} 个")

    total = 0
    out_path = Path(args.out)
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["src_year", "src_file", "page"] + FIELDS[:8])
        for pdf in pdfs:
            year = re.search(r"(19|20)\d{2}", pdf.name)
            src_year = year.group(0) if year else ""
            doc = pymupdf.open(pdf)
            era_b = bool(src_year) and int(src_year) >= 2011
            mapping: dict[int, str] | None = None
            buf: list[list[str]] = []
            for pno in range(doc.page_count):
                rows, m = rows_from_page(doc[pno])
                if m:
                    mapping = m
                for r in rows:
                    if any(r):
                        buf.append([src_year, pdf.name, str(pno + 1)] + r)
            anchors = count_anchors(doc)
            mode = "table"
            if anchors and len(buf) < anchors * 0.95:
                mode = "text"
                buf = []
                for pno in range(doc.page_count):
                    for r in rows_from_text(doc[pno], era_b):
                        buf.append([src_year, pdf.name, str(pno + 1)] + r)
            # 同文件内按注册号去重（表格识别对合并单元格会重复出行）
            seen: set[str] = set()
            kept: list[list[str]] = []
            for r in buf:
                r = list(r)
                r[3] = re.sub(r"[^0-9A-Za-z]", "", r[3] or "")
                joined = " ".join(r[3:]).upper()
                if "SIAMED" in joined:
                    continue
                if not re.match(r"^(?:\d{3,4}M\d{2,4}|\d{5})$", r[3]):
                    continue
                reg = r[3]
                if reg in seen:
                    continue
                seen.add(reg)
                kept.append(r)
            for r in kept:
                w.writerow(r)
            total += len(kept)
            print(f"  {pdf.name:<24} pages={doc.page_count:<3} anchors={anchors:<5} "
                  f"rows={len(kept):<5} mode={mode:<5} cols={list((mapping or {}).values())}")
    print(f"总计 {total:,} 行 → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
