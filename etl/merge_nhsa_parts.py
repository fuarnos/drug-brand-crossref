# -*- coding: utf-8 -*-
import csv, collections, re, time

parts = ["data/raw/nhsa/part%d.csv" % i for i in range(4)]
out = "data/raw/nhsa/nhsa_codes_20240105.csv"
t0 = time.time()
rows = 0
header = None
with open(out, "w", newline="", encoding="utf-8-sig") as fo:
    w = csv.writer(fo)
    for pi, p in enumerate(parts):
        with open(p, encoding="utf-8-sig") as fi:
            r = csv.reader(fi)
            h = next(r)
            if header is None:
                header = h
                w.writerow(h)
            for row in r:
                w.writerow(row)
                rows += 1
print("merged rows", rows, "sec %.0f" % (time.time()-t0))

names, companies, approvals, codes = set(), set(), set(), set()
brand = 0
cat = collections.Counter()
forms = collections.Counter()
with open(out, encoding="utf-8-sig") as f:
    r = csv.DictReader(f)
    for row in r:
        names.add(row["注册名称"])
        companies.add(row["药品企业"])
        approvals.add(row["批准文号"])
        codes.add(row["药品代码"])
        if row["商品名称"] and row["商品名称"] != "无":
            brand += 1
        m = re.match(r"国药准字([A-Z])", row["批准文号"] or "")
        cat[m.group(1) if m else "?"] += 1
        forms[row["注册剂型"]] += 1
lines = []
lines.append("rows %d" % rows)
lines.append("unique 注册名称 %d" % len(names))
lines.append("unique 药品企业 %d" % len(companies))
lines.append("unique 批准文号 %d" % len(approvals))
lines.append("unique 药品代码 %d" % len(codes))
lines.append("商品名有值 %d = %.1f%%" % (brand, brand*100.0/rows))
lines.append("批号类别 " + str(dict(cat.most_common(8))))
lines.append("剂型 top " + str(forms.most_common(10)))
open("reports/nhsa_full_stats.txt", "w", encoding="utf-8").write("\n".join(lines))
print("done")
