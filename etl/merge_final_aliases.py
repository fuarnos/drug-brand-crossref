# -*- coding: utf-8 -*-
import csv, collections

rows = []
with open("reports/cn_aliases.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        rows.append((r["alias"].strip(), r["target_cn"].strip()))
with open("reports/ahospital_aliases.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        rows.append((r["alias"].strip(), r["name"].strip()))

GENERIC = set("药品 药物 西药 中药 中成药 片剂 胶囊 注射液 针剂 口服液 颗粒 软膏 乳膏 医保 处方药 非处方药 抗生素 消炎药 退烧药 止痛药 感冒药 儿童 成人 外用 口服 注射".split())
seen = set(); out = []
for a, n in rows:
    if not a or a == n or a in GENERIC: continue
    if len(a) < 2 or len(a) > 12: continue
    k = (a, n)
    if k in seen: continue
    seen.add(k); out.append([a, n])

with open("data/cn_aliases_final.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(["alias", "name"]); w.writerows(out)

names = set(n for a, n in out)
print("rows", len(out), "distinct alias", len(set(a for a, n in out)), "names", len(names))
