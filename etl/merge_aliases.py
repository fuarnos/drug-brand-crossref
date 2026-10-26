# -*- coding: utf-8 -*-
import csv, json, re, urllib.parse, urllib.request, collections

UA = {"User-Agent": "drug-alias-research/0.1", "Accept": "application/sparql-results+json"}
q = """SELECT ?title ?alias WHERE {
  ?d wdt:P267 ?atc ; rdfs:label ?title ; skos:altLabel ?alias .
  FILTER(LANG(?title)="zh") FILTER(LANG(?alias)="zh")
} LIMIT 5000"""
u = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q)
req = urllib.request.Request(u, headers=UA)
with urllib.request.urlopen(req, timeout=90) as r:
    j = json.loads(r.read().decode("utf-8"))
wd = [(b["title"]["value"], b["alias"]["value"]) for b in j["results"]["bindings"]]

wiki = []
with open("reports/wiki_aliases.csv", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        wiki.append((row["wiki_title"], row["alias"], "wikipedia"))

rows = [(t, a, "wikidata") for t, a in wd] + wiki
# dedupe
seen = set(); merged = []
for t, a, src in rows:
    a = a.strip(); t = t.strip()
    if not a or a == t: continue
    k = (t, a)
    if k in seen: continue
    seen.add(k); merged.append([t, a, src])

with open("reports/cn_aliases.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(["name", "alias", "source"]); w.writerows(merged)

# coverage vs our CN names
names = set()
with open("data/raw/nhsa/nhsa_codes_20250404.csv", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        names.add(row["注册名称"])
SUFFIX = re.compile(r"(缓释|控释|肠溶|分散|咀嚼|口腔崩解|口崩|含|泡腾|阴道|膨胀)?(片|胶囊|软胶囊|颗粒|散|注射液|注射剂|口服溶液|口服液|糖浆|滴剂|滴眼液|眼膏|乳膏|凝胶|软膏|栓|喷雾剂|气雾剂|混悬液|干混悬剂|溶液|洗剂|搽剂|酊|膜|贴|胶束|乳|灌肠液|鼻喷雾剂|滴丸|丸|合剂|粉剂|剂)$")
base = set()
for n in names:
    b = re.sub(r"^注射用", "", n)
    prev = None
    while prev != b:
        prev = b; b = SUFFIX.sub("", b)
    if len(b) >= 2: base.add(b)

titles = set(t for t, a, s in merged)
alias_only = set(a for t, a, s in merged)
lines = []
lines.append("wiki aliases rows %d, wikidata rows %d, merged rows %d" % (len(wiki), len(wd), len(merged)))
lines.append("distinct titles %d, distinct aliases %d" % (len(titles), len(alias_only)))
lines.append("titles that are our CN base names %d / %d" % (len(titles & base), len(base)))
lines.append("aliases that are our CN base names %d" % len(alias_only & base))
lines.append("aliases that are our full CN names %d" % len(alias_only & names))
open("reports/cn_alias_summary.txt", "w", encoding="utf-8").write("\n".join(lines))
print("ok")
