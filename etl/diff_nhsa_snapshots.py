# -*- coding: utf-8 -*-
import csv, collections, re, time

# merge parts
parts = ["data/raw/nhsa/p2025_%d.csv" % i for i in range(4)]
out = "data/raw/nhsa/nhsa_codes_20250404.csv"
with open(out, "w", newline="", encoding="utf-8-sig") as fo:
    w = csv.writer(fo)
    header = None
    for p in parts:
        with open(p, encoding="utf-8-sig") as fi:
            r = csv.reader(fi)
            h = next(r)
            if header is None:
                header = h; w.writerow(h)
            for row in r:
                w.writerow(row)

def load(path):
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows

a = load("data/raw/nhsa/nhsa_codes_20240105.csv")
b = load(out)

def stats(rows):
    appr = set(r["批准文号"] for r in rows if r["批准文号"])
    names = set(r["注册名称"] for r in rows)
    cats = collections.Counter()
    for r in rows:
        m = re.match(r"国药准字([A-Z])", r["批准文号"] or "")
        cats[m.group(1) if m else "?"] += 1
    return appr, names, cats

a_appr, a_names, a_cat = stats(a)
b_appr, b_names, b_cat = stats(b)

lines = []
lines.append("2024-01-05 rows %d approvals %d names %d" % (len(a), len(a_appr), len(a_names)))
lines.append("2025-04-04 rows %d approvals %d names %d" % (len(b), len(b_appr), len(b_names)))
lines.append("row delta %+d (%.1f%%)" % (len(b)-len(a), (len(b)-len(a))*100.0/len(a)))
lines.append("approval delta %+d (%.1f%%)" % (len(b_appr)-len(a_appr), (len(b_appr)-len(a_appr))*100.0/len(a_appr)))
lines.append("name delta %+d (%.1f%%)" % (len(b_names)-len(a_names), (len(b_names)-len(a_names))*100.0/len(a_names)))
lines.append("new approvals %d, removed %d" % (len(b_appr-a_appr), len(a_appr-b_appr)))
lines.append("new names %d, gone %d" % (len(b_names-a_names), len(a_names-b_names)))
lines.append("H rows 2024 %d -> 2025 %d" % (a_cat["H"], b_cat["H"]))
lines.append("Z rows 2024 %d -> 2025 %d" % (a_cat["Z"], b_cat["Z"]))
lines.append("S rows 2024 %d -> 2025 %d" % (a_cat["S"], b_cat["S"]))
lines.append("H names 2024 %d -> 2025 %d" % (len(set(r["注册名称"] for r in a if r["批准文号"].startswith("国药准字H"))),
                                             len(set(r["注册名称"] for r in b if r["批准文号"].startswith("国药准字H")))))
lines.append("")
lines.append("sample new approvals: " + ", ".join(sorted(b_appr-a_appr)[:8]))
open("reports/nhsa_diff_2024_2025.txt", "w", encoding="utf-8").write("\n".join(lines))
print("done")
