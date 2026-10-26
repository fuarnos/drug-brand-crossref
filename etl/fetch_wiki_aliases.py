# -*- coding: utf-8 -*-
import csv, json, re, time, urllib.parse, urllib.request, urllib.error, os, sys

UA = {"User-Agent": "drug-alias-research/0.1 (https://example.org; contact: local)"}
SUFFIX = re.compile(r"(缓释|控释|肠溶|分散|咀嚼|口腔崩解|口崩|含|泡腾|阴道|膨胀)?(片|胶囊|软胶囊|颗粒|散|注射液|注射剂|口服溶液|口服液|糖浆|滴剂|滴眼液|眼膏|乳膏|凝胶|软膏|栓|喷雾剂|气雾剂|吸入粉雾剂|混悬液|干混悬剂|溶液|洗剂|搽剂|酊|膜|贴|胶束|乳|灌肠液|鼻喷雾剂|滴丸|丸|合剂|粉剂|散剂|剂)$")
CAS = re.compile(r"^\d{2,7}-\d{2}-\d$")
LATIN = re.compile(r"^[A-Za-z0-9\s\-\(\)\[\]\.\+]+$")

def base(n):
    n = re.sub(r"^注射用", "", n)
    prev = None
    while prev != n:
        prev = n
        n = SUFFIX.sub("", n)
    return n

def query(titles):
    data = urllib.parse.urlencode({
        "action": "query", "prop": "redirects|extracts", "exintro": 1, "explaintext": 1,
        "rdlimit": 50, "titles": "|".join(titles), "format": "json", "redirects": 1,
        "maxlag": 5}).encode()
    for attempt in range(5):
        try:
            req = urllib.request.Request("https://zh.wikipedia.org/w/api.php", data=data, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                time.sleep(10 * (attempt + 1)); continue
            raise
    raise RuntimeError("too many retries")

names, seen = [], set()
with open("data/raw/nhsa/nhsa_codes_20250404.csv", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        if not row["批准文号"].startswith("国药准字H"):
            continue
        n = row["注册名称"]
        if n not in seen:
            seen.add(n); names.append(n)
bases, bseen = [], set()
for n in names:
    b = base(n)
    if 2 <= len(b) <= 20 and b not in bseen:
        bseen.add(b); bases.append(b)

PAT = re.compile(r"(?:又称|俗称|别名|又名|旧称|音译|简称|商品名[为是]?)[「“]?([^，。；、（）\(\)]{2,14})")
out = "reports/wiki_aliases.csv"
with open(out, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(["wiki_title", "alias", "kind", "pageid"])
    found = 0; nrows = 0
    for i in range(0, len(bases), 50):
        j = query(bases[i:i+50])
        for pid, p in j.get("query", {}).get("pages", {}).items():
            if "missing" in p or "invalid" in p: continue
            found += 1
            title = p.get("title", "")
            cand = [(r["title"], "redirect") for r in p.get("redirects", [])]
            for m in PAT.finditer(p.get("extract", "") or ""):
                cand.append((m.group(1).strip(), "extract"))
            for a, kind in cand:
                a = a.strip()
                if not a or a == title or a == base(title): continue
                if CAS.match(a) or LATIN.match(a): continue
                if len(a) < 2 or len(a) > 20: continue
                if not re.search(r"[\u4e00-\u9fff]", a): continue
                if "稱" in a and len(a) > 8: continue
                w.writerow([title, a, kind, pid]); nrows += 1
        f.flush()
        time.sleep(0.4)
        if i % 500 == 0:
            print("batch %d/%d pages %d rows %d" % (i, len(bases), found, nrows), flush=True)
    print("DONE bases %d pages %d rows %d" % (len(bases), found, nrows), flush=True)
