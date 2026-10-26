# -*- coding: utf-8 -*-
"""爬 A+医学百科（a-hospital.com）药品条目，抽别名。"""
import csv, json, re, urllib.parse, urllib.request, time

UA = {"User-Agent": "Mozilla/5.0 (compatible; drug-index/0.1)"}
SUFFIX = re.compile(r"(缓释|控释|肠溶|分散|咀嚼|口腔崩解|口崩|含|泡腾|阴道|膨胀)?(片|胶囊|软胶囊|颗粒|散|注射液|注射剂|口服溶液|口服液|糖浆|滴剂|滴眼液|眼膏|乳膏|凝胶|软膏|栓|喷雾剂|气雾剂|混悬液|干混悬剂|溶液|洗剂|搽剂|酊|膜|贴|胶束|乳|灌肠液|鼻喷雾剂|滴丸|丸|合剂|粉剂|剂)$")

def base_h(n):
    n = re.sub(r"^注射用", "", n); prev = None
    while prev != n:
        prev = n; n = SUFFIX.sub("", n)
    return n

targets, seen = [], set()
with open("data/raw/nhsa/nhsa_codes_20250404.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        n = r["注册名称"]; code = r["批准文号"] or ""
        name = base_h(n) if code.startswith("国药准字H") else n
        if 2 <= len(name) <= 20 and name not in seen:
            seen.add(name); targets.append(name)

def fetch(titles):
    u = "https://www.a-hospital.com/api.php?action=query&prop=revisions&rvprop=content&format=json&titles=" + urllib.parse.quote("|".join(titles), safe="|")
    req = urllib.request.Request(u, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

FIELD = re.compile(r"^\s*(?:中文别名|中文俗名|别名|曾用名|［别名］|\[别名\]|药品别名|商品名)\s*[：:\]]\s*(.+)$", re.M)
def norm_links(s):
    s = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    return s.replace("'''", "")

def tokens(s, title):
    out = []
    for x in re.split(r"[、，,；;/]", norm_links(s)):
        x = re.sub(r"[（(].*?[）)]", "", x).strip(" 　:：*'\"“”()（）")
        x = re.sub(r"等$", "", x)
        if 2 <= len(x) <= 12 and re.fullmatch(r"[\u4e00-\u9fff]+", x) and x != title:
            out.append(x)
    return out

def extract(txt, title):
    got = []
    for m in FIELD.finditer(txt):
        got += tokens(m.group(1), title)
    for m in re.finditer(r"(?:又称|俗称)\s*((?:'''[^']+'''\s*[、，,]?\s*)+)", txt):
        for b in re.findall(r"'''([^']+)'''", m.group(1)):
            got += tokens(b, title)
    return got

out = "reports/ahospital_aliases.csv"
with open(out, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(["name", "alias"])
    pages = 0; rows = 0
    for i in range(0, len(targets), 20):
        try:
            j = fetch(targets[i:i+20])
        except Exception:
            time.sleep(1); continue
        if not isinstance(j, dict): continue
        pgs = j.get("query", {}).get("pages", {})
        if isinstance(pgs, list): pgs = {str(x.get("pageid")): x for x in pgs}
        for p in pgs.values():
            txt = (p.get("revisions") or [{}])[0].get("*", "")
            if not txt: continue
            pages += 1
            t = p.get("title", "")
            for a in set(extract(txt, t)):
                w.writerow([t, a]); rows += 1
        f.flush()
        time.sleep(0.05)
        if i % 1000 == 0:
            print("batch %d/%d pages %d rows %d" % (i, len(targets), pages, rows), flush=True)
    print("DONE targets %d pages %d rows %d" % (len(targets), pages, rows), flush=True)
