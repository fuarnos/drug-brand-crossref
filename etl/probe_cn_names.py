# -*- coding: utf-8 -*-
import json, sqlite3, csv, collections, re, os

snap = json.load(open("data/raw/nhsa/public_batch_20220110.json", encoding="utf-8"))
rows = snap["rows"]
mp = json.load(open("data/cn_name_map.json", encoding="utf-8"))["map"]
con = sqlite3.connect("data/drugs.db")
db_names = [r[0] for r in con.execute("select inn_en from substance")]
db_lower = [x.lower() for x in db_names]

def find(cands):
    for c in cands:
        cl = c.lower()
        for i, d in enumerate(db_lower):
            if d == cl or d.startswith(cl + " "):
                return db_names[i]
    return None

names = collections.OrderedDict()
for r in rows:
    n = r["registeredproductname"]
    d = names.setdefault(n, {"rows": 0, "companies": set(), "strengths": set(), "codes": set(), "cats": set()})
    d["rows"] += 1
    d["companies"].add(r["companynamesc"])
    d["strengths"].add(r["realityoutlook"])
    d["codes"].add(r["approvalcode"])
    m = re.match(r"国药准字([A-Z])", r["approvalcode"] or "")
    d["cats"].add(m.group(1) if m else "?")

def cat_of(cats):
    for c in ("H", "Z", "S", "B"):
        if c in cats:
            return c
    return "?"

stat = collections.Counter()
out = []
detail = collections.defaultdict(list)
for n, d in names.items():
    cat = cat_of(d["cats"])
    cands = mp.get(n, "MISSING")
    if cat == "Z":
        st, en = "tcm", ""
    elif cat == "S":
        st, en = "biologic", ""
    elif cands == "MISSING":
        st, en = "unmapped", ""
        detail["unmapped"].append((cat, n))
    elif cands is None:
        st, en = "compound", ""
        detail["compound"].append(n)
    else:
        hit = find(cands)
        if hit:
            st, en = "matched", hit
        else:
            st, en = "not_in_db", "/".join(cands)
            detail["not_in_db"].append((n, en))
    stat[(cat, st)] += 1
    detail[st + "_rows"] = detail.get(st + "_rows", 0) + d["rows"]
    out.append([n, cat, d["rows"], len(d["companies"]), len(d["strengths"]), len(d["codes"]), en, st])

os.makedirs("reports", exist_ok=True)
with open("reports/cn_name_coverage.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["中文名", "类别", "批号行数", "厂家数", "规格数", "英文成分", "状态"])
    w.writerows(sorted(out, key=lambda x: (x[1], x[7], x[0])))

lines = []
lines.append("unique names %d, rows %d" % (len(names), len(rows)))
for k in sorted(stat):
    lines.append("%s %s %d" % (k[0], k[1], stat[k]))
lines.append("")
for key in ("unmapped", "not_in_db"):
    lines.append("%s (%d):" % (key, len(detail[key])))
    for item in detail[key][:60]:
        lines.append("   " + " | ".join(item))
lines.append("")
lines.append("compound (%d)" % len(detail["compound"]))
open("reports/cn_name_summary.txt", "w", encoding="utf-8").write("\n".join(lines))
print("done", len(names))
