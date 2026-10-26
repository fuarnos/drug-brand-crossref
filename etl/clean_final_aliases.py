# -*- coding: utf-8 -*-
import csv, re, collections
rows = list(csv.DictReader(open("data/cn_aliases_final.csv", encoding="utf-8-sig")))
BAD = re.compile(r"类药物$|受体|抑制剂|拮抗剂|激动剂|®|™|/|-|·")
out, seen = [], set()
for r in rows:
    a, n = r["alias"], r["name"]
    if not re.fullmatch(r"[\u4e00-\u9fff]{2,12}", a): continue
    if BAD.search(a): continue
    if a == n: continue
    k = (a, n)
    if k in seen: continue
    seen.add(k); out.append([a, n])
with open("data/cn_aliases_final.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(["alias", "name"]); w.writerows(out)
print("final rows", len(out), "aliases", len(set(a for a, n in out)), "names", len(set(n for a, n in out)))
