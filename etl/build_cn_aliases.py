# -*- coding: utf-8 -*-
import csv, json, re, time, urllib.parse, urllib.request, urllib.error

UA = {"User-Agent": "drug-alias-research/0.1", "Accept": "application/sparql-results+json"}
q = """SELECT ?title ?alias WHERE {
  ?d wdt:P267 ?atc ; rdfs:label ?title ; skos:altLabel ?alias .
  FILTER(LANG(?title)="zh") FILTER(LANG(?alias)="zh")
} LIMIT 5000"""
u = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q)
wd = []
for attempt in range(3):
    try:
        req = urllib.request.Request(u, headers=UA)
        with urllib.request.urlopen(req, timeout=90) as r:
            j = json.loads(r.read().decode("utf-8"))
        wd = [(b["title"]["value"], b["alias"]["value"]) for b in j["results"]["bindings"]]
        break
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(65); continue
        raise

wiki = []
with open("reports/wiki_aliases.csv", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        wiki.append((row["wiki_title"], row["alias"], "wikipedia"))

BAD = re.compile(r"[，。：；！？、（）\(\)]|则有|^有[^\s]{1,3}片$")
def ok(a):
    if not a or len(a) < 2 or len(a) > 12: return False
    if re.search(r"[0-9A-Za-z]", a): return False
    if BAD.search(a): return False
    if not re.search(r"[\u4e00-\u9fff]", a): return False
    return True

rows, seen = [], set()
for t, a, src in [(t, a, "wikipedia") for t, a, s in wiki] + [(t, a, "wikidata") for t, a in wd]:
    a = a.strip(); t = t.strip()
    if not ok(a) or a == t: continue
    k = (a, t)
    if k in seen: continue
    seen.add(k); rows.append([a, t, src])

with open("reports/cn_aliases.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(["alias", "target_cn", "source"]); w.writerows(rows)

print("wikidata rows", len(wd), "wiki rows", len(wiki), "clean rows", len(rows))
