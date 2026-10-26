# -*- coding: utf-8 -*-
"""从国家医保局《医保药品分类与代码数据库》PDF 抽取产品表（单进程、流式写盘）。"""
import sys, csv, time, argparse
sys.path.insert(0, ".pylibs")
import pymupdf

COLS = ["药品代码", "编号", "注册名称", "注册剂型", "注册规格", "商品名称", "剂型", "规格",
        "包装材质", "最小包装数量", "最小制剂单位", "最小包装单位", "药品企业",
        "批准文号", "药品本位码", "甲乙类", "医保编号", "药品名称", "医保剂型", "备注"]

def clean(v):
    return "" if v is None else str(v).replace("\n", "").strip()

def parse_page(page):
    rows = []
    try:
        tabs = page.find_tables()
    except Exception:
        return rows
    if not tabs.tables:
        return rows
    for raw in tabs.tables[0].extract():
        c = [clean(x) for x in raw]
        if len(c) < 19:
            c += [""] * (19 - len(c))
        if c[1] == "注册名称" or c[0] == "药品代码" or not c[1]:
            continue
        code, bianhao = c[0], c[15]
        raw0 = str(raw[0] or "")
        if "\n" in raw0:
            parts = raw0.split("\n")
            code, bianhao = parts[0], parts[-1]
        rows.append([code, bianhao, c[1], c[2], c[3], c[4], c[5], c[6], c[7], c[8], c[9], c[10],
                     c[11], c[12], c[13], c[14], c[15], c[16], c[17], c[18]])
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=999999)
    a = ap.parse_args()
    doc = pymupdf.open(a.pdf)
    end = min(a.end, doc.page_count)
    t0 = time.time(); n = 0
    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(COLS)
        for i in range(a.start, end):
            for r in parse_page(doc[i]):
                w.writerow(r); n += 1
            if i % 200 == 0:
                f.flush()
                print("page %d/%d rows %d sec %.0f" % (i, end, n, time.time()-t0), flush=True)
    print("DONE rows %d sec %.0f" % (n, time.time()-t0), flush=True)

if __name__ == "__main__":
    main()
