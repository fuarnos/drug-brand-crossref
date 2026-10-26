"""静态站生成：SQLite → site/dist/

产物：
    index.html          搜索（客户端匹配，返回候选集与碰撞提示）
    drug/<id>.html      成分身份卡（各国商品名对照）
    name/<id>.html      名字页（这个名字下挂了哪些药——碰撞页）
    confused.html       FDA tall-man 易混淆药对
    about.html          数据来源、覆盖率、免责
    whats-new.html      更新日志（由 CHANGELOG.md 生成）
    404.html            路径不存在时的兜底页
    robots.txt          全站可抓 + sitemap 地址
    sitemap.xml         全站 HTML 的 sitemap
    data/index.json     检索索引
    data/aliases.json   俗称 / 街头叫法 / 类别词索引
    data/confused.json  易混淆药对索引
    assets/             css + js

用法：python site/build.py
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
# 默认 site/dist；SITE_OUT 允许并发构建到独立目录，避免两个进程互相 rmtree。
OUT = Path(os.environ.get("SITE_OUT") or (ROOT / "site" / "dist"))
# 报错入口：静态站没有后端，用 GitHub Issue 收集纠错，附上查询词和页面 URL。
REPORT_REPO = "https://github.com/fuarnos/drug-brand-crossref"
# 公开站根地址：404 页、robots.txt、sitemap.xml 里要用绝对 URL。
SITE_URL = "https://fuarnos.github.io/drug-brand-crossref/"
# 每次构建换一个版本号，给 css/js/json 都带上，避免用户拿到缓存里的旧代码。
BUILD_V = str(int(time.time()))

CHANGELOG = ROOT / "CHANGELOG.md"


def _read_latest_release() -> tuple[str, str]:
    """页脚显示的版本：CHANGELOG 最上面的 ## vX — date。"""
    try:
        text = CHANGELOG.read_text(encoding="utf-8")
    except OSError:
        return "", ""
    m = re.search(r"^## (v[0-9][^\s]*)\s*[—–-]\s*(\d{4}-\d{2}-\d{2})", text, re.M)
    return (m.group(1), m.group(2)) if m else ("", "")


LATEST_VERSION, LATEST_DATE = _read_latest_release()

DISEASE_NOTE = (
    "本站只做「名字 → 成分」的标识对应，不提供用药建议、"
    "不换算服药剂量、不建议替换药品。"
)

# 三语界面文案。英文是默认、也是 HTML 里的兜底文本；
# 页面加载后 i18n.js 按 ?lang= / localStorage / 浏览器语言替换带 data-i18n 的元素。
I18N = {
    "en": {
        "nav.search": "Search", "nav.confused": "Confused names", "nav.about": "About",
        "nav.whatsnew": "What's new",
        "home.h1": "Find out what a medicine really is",
        "home.sub": ("Type a brand name, a generic name, a nickname (try 两只青蛙), or a line "
                     "from the pack. Chinese, full-width and Cyrillic input all work, and you can "
                     "include the dose — e.g. Lipitor 20mg, 泰诺, СОРТИС."),
        "home.ph": "Brand name / generic name / nickname / a line from the pack",
        "home.all": "All countries", "home.us": "United States",
        "home.gb": "United Kingdom", "home.cn": "China", "home.es": "Spain",
        "home.mx": "Mexico", "home.au": "Australia", "home.ca": "Canada",
        "home.coverage": ("An empty result does not mean the medicine does not exist. "
                          "Coverage:"),
        "home.loading": "Loading index…",
        "res.matched": "names matched", "res.none": "No match",
        "res.brands": "brand names found",
        "res.alias": "alias matched",
        "res.alias_no_products": "not a single product — see the note above",
        "res.notin": "Not covered in this country",
        "res.caveat": "an empty result does not mean the drug does not exist",
        "artg.title": "Also on the ARTG (ingredient not captured yet)",
        "artg.note": ("These entries are registered in Australia, but this site has not linked "
                      "them to an active ingredient yet — so they are not shown as products."),
        "artg.sponsor": "Sponsor", "artg.id": "ARTG ID",
        "res.fuzzy": "No exact match — closest names",
        "card.packs": "packs",
        "col.ing": "Ingredient", "col.dose": "Dose",
        "col.brand": "Brand", "col.mah": "Manufacturer",
        "same.ing": "Other products with the same ingredient",
        "same.note": "You searched a brand name — this is what else contains the same active ingredient.",
        "badge.severe": "Same name, different drug",
        "badge.warning": "Different release",
        "badge.combo": "Combination",
        "fam.title": "The same brand in other markets",
        "fam.warn": "Same brand, different drug",
        "drug.brand": "Brand", "drug.strength": "Strength", "drug.nostrength": "not disclosed",
        "drug.release": "Release", "drug.status": "Status",
        "drug.records": "records", "drug.showing": "showing first 40 of",
        "drug.sid": "Substance ID",
        "drug.notice": ("The same ingredient can carry completely different brand names in "
                        "different countries, and the same name can point to a different "
                        "ingredient. Listed by country — not interchangeable."),
        "drug.empty": "No products recorded yet.",
        "drug.confused": "Easily confused with",
        "drug.confused_note": ("FDA recommends tall-man lettering for this pair; check the "
                               "ingredient, not the name."),
        "drug.confused_all": "All pairs",
        "name.countries": "Countries", "name.form": "Form",
        "name.strength": "Strength", "name.release": "Release",
        "name.also": "Also written as", "name.found": "Found in",
        "name.empty": "No records",
        "name.severe": ("This brand name points to different active ingredients in different "
                        "countries or variants. Check the composition, never treat the names "
                        "as equivalent."),
        "name.warning": ("Same name, but immediate vs modified release — not interchangeable."),
        "nick.hit": "Nickname",
        "nick.slang": "internet nickname", "nick.legacy": "older name",
        "nick.translit": "transliterated old name", "nick.abbrev": "abbreviation",
        "nick.misnomer": "common misnomer",
        "nick.unverified": "user-provided (unverified)",
        "nick.community": "community name",
        "nick.source": "Source",
        "nick.street": "US street name", "nick.folk": "folk name",
        "nick.class": "class term",
        "nick.class_caveat": ("This is a class term, not a specific medicine — it can cover "
                              "several ingredients. Check the ingredient."),
        "nick.folk_caveat": ("This is a folk/category term, not a specific medicine — it can "
                             "cover several ingredients. A product whose name contains the "
                             "term is not necessarily in that class; check the ingredient."),
        "nick.nomap_caveat": ("This term points to a substance with no marketed product in "
                              "this database, so no product list is shown."),
        "nick.ambiguous": ("This nickname may point to more than one ingredient — "
                           "check the composition."),
        "nick.caveat": ("Nicknames point to an ingredient, not to a specific pack: the same "
                        "ingredient is sold under different brand names in each country."),
        "footer": ("Information only — not medical advice, and no substitute for a pharmacist."),
        "report.link": "Report a data error",
        "report.all": "Known issues",
        "report.note": "Wrong ingredient, wrong dose, or a drug we do not have? Tell us:",
        "report.cta": "Report this result",
        "conf.title": "Easily confused drug names",
        "conf.intro": ("Look-alike / sound-alike pairs from the FDA Name Differentiation Project. "
                       "This is the official tall-man list, not the full ISMP LASA list."),
        "conf.note": ("A pair here means the names can be mistaken for each other; it does not "
                      "mean the drugs are interchangeable. FDA recommends tall-man lettering."),
        "conf.pair": "Pair", "conf.tml": "Tall-man spelling",
        "conf.search_hit": "This name is easily confused with",
    },
    "es": {
        "nav.search": "Buscar", "nav.confused": "Nombres confundibles", "nav.about": "Acerca de",
        "nav.whatsnew": "Novedades",
        "home.h1": "Descubre qué es realmente un medicamento",
        "home.sub": ("Escribe un nombre comercial, un nombre genérico, un apodo (prueba 两只青蛙) "
                     "o una línea del envase. También funciona en chino, en ancho completo y en "
                     "cirílico; puedes incluir la dosis — p. ej. Lipitor 20mg, 泰诺, СОРТИС."),
        "home.ph": "Nombre comercial / genérico / apodo / una línea del envase",
        "home.all": "Todos los países", "home.us": "Estados Unidos",
        "home.gb": "Reino Unido", "home.cn": "China", "home.es": "España",
        "home.mx": "México", "home.au": "Australia", "home.ca": "Canadá",
        "home.coverage": ("Un resultado vacío no significa que el medicamento no exista. "
                          "Cobertura:"),
        "home.loading": "Cargando el índice…",
        "res.matched": "nombres encontrados", "res.none": "Sin resultados",
        "res.brands": "nombres comerciales encontrados",
        "res.alias": "alias encontrado",
        "res.alias_no_products": "no es un producto único — ver la nota",
        "res.notin": "No incluido en este país",
        "res.caveat": "un resultado vacío no significa que el medicamento no exista",
        "artg.title": "También en el ARTG (principio activo no registrado)",
        "artg.note": ("Estos registros existen en Australia, pero el sitio todavía no los ha "
                      "vinculado a un principio activo, así que no se muestran como productos."),
        "artg.sponsor": "Titular", "artg.id": "ID ARTG",
        "res.fuzzy": "Sin coincidencia exacta — nombres más parecidos",
        "card.packs": "envases",
        "col.ing": "Principio activo", "col.dose": "Dosis",
        "col.brand": "Marca", "col.mah": "Fabricante",
        "same.ing": "Mismo principio activo, otros productos",
        "same.note": "Buscaste una marca: esto es lo demás que contiene el mismo principio activo.",
        "badge.severe": "Mismo nombre, otro medicamento",
        "badge.warning": "Liberación diferente",
        "badge.combo": "Combinación",
        "fam.title": "La misma marca en otros mercados",
        "fam.warn": "Misma marca, otro medicamento",
        "drug.brand": "Marca", "drug.strength": "Concentración", "drug.nostrength": "no publicado",
        "drug.release": "Liberación", "drug.status": "Estado",
        "drug.records": "registros", "drug.showing": "mostrando 40 de",
        "drug.sid": "ID de sustancia",
        "drug.notice": ("Un mismo principio activo puede tener nombres comerciales totalmente "
                        "distintos según el país, y un mismo nombre puede corresponder a otro "
                        "principio activo. Listado por país — no son intercambiables."),
        "drug.empty": "Todavía no hay productos registrados.",
        "drug.confused": "Fácil de confundir con",
        "drug.confused_note": ("La FDA recomienda tall-man lettering para este par; "
                               "comprueba el principio activo, no el nombre."),
        "drug.confused_all": "Todos los pares",
        "name.countries": "Países", "name.form": "Forma",
        "name.strength": "Concentración", "name.release": "Liberación",
        "name.also": "También escrito como", "name.found": "Presente en",
        "name.empty": "Sin registros",
        "name.severe": ("Este nombre comercial corresponde a principios activos distintos "
                        "según el país o la variante. Comprueba la composición; nunca trates "
                        "los nombres como equivalentes."),
        "name.warning": ("Mismo nombre, pero liberación inmediata frente a modificada — "
                         "no son intercambiables."),
        "nick.hit": "Apodo",
        "nick.slang": "apodo de internet", "nick.legacy": "nombre antiguo",
        "nick.translit": "nombre antiguo transliterado", "nick.abbrev": "abreviatura",
        "nick.misnomer": "denominación errónea habitual",
        "nick.unverified": "aportado por el usuario (sin verificar)",
        "nick.community": "nombre de la comunidad",
        "nick.source": "Fuente",
        "nick.street": "nombre callejero en EE. UU.", "nick.folk": "nombre popular",
        "nick.class": "término de clase",
        "nick.class_caveat": ("Es un término de clase, no un medicamento concreto: puede "
                              "abarcar varios principios activos. Comprueba el principio activo."),
        "nick.folk_caveat": ("Es un término popular/de categoría, no un medicamento concreto: "
                             "puede abarcar varios principios activos. Un producto cuyo nombre "
                             "contiene el término no pertenece necesariamente a esa clase."),
        "nick.nomap_caveat": ("Este término apunta a una sustancia sin producto comercializado "
                              "en esta base de datos; no se muestra lista de productos."),
        "nick.ambiguous": ("Este apodo puede corresponder a más de un principio activo — "
                           "comprueba la composición."),
        "nick.caveat": ("Los apodos señalan un principio activo, no un envase concreto: el mismo "
                        "principio se vende con marcas distintas en cada país."),
        "footer": ("Solo información — no es consejo médico ni sustituye a un farmacéutico."),
        "report.link": "Informar de un error",
        "report.all": "Problemas conocidos",
        "report.note": "¿Principio activo equivocado, dosis equivocada o falta un medicamento? Escríbenos:",
        "report.cta": "Informar de este resultado",
        "conf.title": "Nombres de medicamentos fáciles de confundir",
        "conf.intro": ("Pares de nombres parecidos o que suenan igual, del proyecto de "
                       "diferenciación de nombres de la FDA. Es la lista oficial tall-man, "
                       "no la lista LASA completa de ISMP."),
        "conf.note": ("Un par significa que los nombres pueden confundirse; no significa que "
                      "los medicamentos sean intercambiables. La FDA recomienda tall-man lettering."),
        "conf.pair": "Par", "conf.tml": "Grafía tall-man",
        "conf.search_hit": "Este nombre se confunde fácilmente con",
    },
    "zh": {
        "nav.search": "检索", "nav.confused": "易混淆药名", "nav.about": "关于",
        "nav.whatsnew": "更新日志",
        "home.h1": "查一个药名，看它在各国是什么",
        "home.sub": ("商品名、通用名、俗称都能搜（比如「两只青蛙」）；支持中英文、全角、"
                     "西里尔字母，也可以连剂量一起输入，例如 Lipitor 20mg、泰诺、СОРТИС。"),
        "home.ph": "商品名 / 通用名 / 俗称 / 包装上的一行字",
        "home.all": "全部国家", "home.us": "美国",
        "home.gb": "英国", "home.cn": "中国", "home.es": "西班牙",
        "home.mx": "墨西哥", "home.au": "澳大利亚", "home.ca": "加拿大",
        "home.coverage": "查不到不代表这个药不存在。当前覆盖：",
        "home.loading": "正在加载索引…",
        "res.matched": "个名字命中", "res.none": "没有匹配的名字",
        "res.brands": "个商品名命中",
        "res.alias": "个别名命中",
        "res.alias_no_products": "不是单一商品，见上方说明",
        "res.notin": "所选国家没有收录这个名字",
        "res.caveat": "查不到不代表这个药不存在",
        "artg.title": "ARTG 也有登记（成分尚未收录）",
        "artg.note": "这些条目在澳洲 ARTG 有登记，但本站还没把成分对上，所以不作为产品展示。",
        "artg.sponsor": "申办方", "artg.id": "ARTG 编号",
        "res.fuzzy": "没有精确命中，以下是最接近的名字",
        "card.packs": "个包装",
        "col.ing": "成分", "col.dose": "剂量",
        "col.brand": "品牌", "col.mah": "厂家",
        "same.ing": "同成分的其他商品",
        "same.note": "你搜的是商品名 —— 下面是同一活性成分的其他商品。",
        "badge.severe": "同名不同药",
        "badge.warning": "释放机制不同",
        "badge.combo": "复方",
        "fam.title": "同一品牌在其他市场的写法",
        "fam.warn": "同名不同药",
        "drug.brand": "商品名", "drug.strength": "规格", "drug.nostrength": "未公开",
        "drug.release": "释放", "drug.status": "状态",
        "drug.records": "条记录", "drug.showing": "仅显示前 40 条，共",
        "drug.sid": "规范成分",
        "drug.notice": ("同一成分在不同国家可能用完全不同的商品名；同名也可能指向不同成分。"
                        "下方按国家列出，不代表可以互换。"),
        "drug.empty": "暂无已收录产品。",
        "drug.confused": "易混淆",
        "drug.confused_note": "FDA 建议这一对使用 tall-man 大小写；请核对成分，不要按名字等同。",
        "drug.confused_all": "查看全部药对",
        "name.countries": "国家", "name.form": "剂型",
        "name.strength": "规格", "name.release": "释放",
        "name.also": "写法", "name.found": "覆盖",
        "name.empty": "无记录",
        "name.severe": ("这个商品名在不同国家或不同变体下指向不同活性成分，"
                        "选药前必须核对成分，不能按名字等同。"),
        "name.warning": "同名产品存在缓释/速释差异，不能直接互换。",
        "nick.hit": "俗称命中",
        "nick.slang": "网络俗称", "nick.legacy": "旧名",
        "nick.translit": "音译旧名", "nick.abbrev": "简称",
        "nick.misnomer": "常见误称",
        "nick.unverified": "用户提供（未证实）",
        "nick.community": "社区叫法",
        "nick.source": "出处",
        "nick.street": "美国街头叫法", "nick.folk": "民间叫法",
        "nick.class": "类别俗称",
        "nick.class_caveat": "这是类别叫法，不是具体药名，可能对应多种成分；请按成分核对。",
        "nick.folk_caveat": "这是民间叫法，不是具体药名，可能对应多种成分；名字里含这个词的商品不一定属于该类别，请按成分核对。",
        "nick.nomap_caveat": "这个词指向的成分在本库没有上市产品记录，因此不列商品名。",
        "nick.ambiguous": "这个叫法可能对应不止一个成分，请按成分核对。",
        "nick.caveat": "俗称指向成分，不指向某个包装；同一成分在各国的商品名不同。",
        "footer": "本站只做标识对应，不构成用药建议，不能替代医师或药师。",
        "report.link": "报错 / 纠错",
        "report.all": "已知问题",
        "report.note": "成分错了、剂量错了、或者库里没有这个药？告诉我们：",
        "report.cta": "报告这个结果",
        "conf.title": "容易混淆的药物",
        "conf.intro": ("来自 FDA Name Differentiation Project 的形似/音似药对。"
                       "这是官方 tall-man 名单，不是 ISMP 全量 LASA 清单。"),
        "conf.note": ("列在这里只说明两个名字可能被看错/听错，不表示两种药可以互换。"
                      "FDA 建议这一对使用 tall-man 大小写。"),
        "conf.pair": "药对", "conf.tml": "建议 tall-man 写法",
        "conf.search_hit": "这个药名容易与以下名字混淆",
    },
}

LANGS = [("en", "EN", ""), ("es", "ES", "es/"), ("zh", "中文", "zh/")]

CSS = """
:root{--bg:#fbfbf9;--fg:#1f2328;--muted:#646b73;--line:#e3e1da;--card:#fff;
--accent:#0b6b53;--warn:#b4471f;--warnbg:#fdf1ec;--sev:#a01b1b;--sevbg:#fdecec}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);min-height:100vh;
display:flex;flex-direction:column;
font:16px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
header{border-bottom:1px solid var(--line);background:#fff}
.wrap{max-width:920px;margin:0 auto;padding:0 20px}
header .wrap{display:flex;align-items:center;gap:16px;height:60px}
.logo{font-weight:700;font-size:16px;color:var(--fg)}
.logo-zh{font-weight:400;font-size:13px;color:var(--muted);margin-left:8px}
.langs{margin-left:6px;font-size:13px}
.langs a{color:var(--muted);padding:1px 5px;border-radius:5px}
.langs a.on{background:var(--accent);color:#fff}
nav{display:flex;gap:14px;font-size:14px}
main{padding:28px 0 60px;flex:1}
h1{font-size:24px;margin:0 0 6px}h2{font-size:18px;margin:28px 0 10px}
.sub{color:var(--muted);font-size:14px;margin:0 0 18px}
#q{width:100%;padding:14px 16px;font-size:17px;border:1px solid var(--line);
border-radius:10px;background:#fff}
.row{display:flex;gap:10px;align-items:center;margin-top:10px;flex-wrap:wrap}
select,button{padding:8px 12px;border:1px solid var(--line);border-radius:8px;
background:#fff;font-size:14px}
button{cursor:pointer;background:var(--accent);color:#fff;border-color:var(--accent)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:14px 16px;margin:10px 0}
.card h3{margin:0 0 4px;font-size:16px}
.card .meta{color:var(--muted);font-size:13px}
.tag{display:inline-block;font-size:12px;padding:1px 7px;border-radius:999px;
border:1px solid var(--line);margin-left:6px;color:var(--muted)}
.tag.cn{color:#8a4b00;border-color:#e8c9a6}
.tag.gb{color:#1f4f8a;border-color:#b9cde6}
.tag.us{color:#0b6b53;border-color:#a9d3c5}
.tag.es{color:#8a2c1f;border-color:#e6bdb4}
.tag.au{color:#6b3b0b;border-color:#e0c9a6}
.tag.combo{color:#7a3b1f;border-color:#e6c3b3}
.tag.ca{color:#7a1420;border-color:#e7c3c7}
.tag.mx{color:#4b5b0b;border-color:#cdd6a6}
.tag.warn{color:#8a4b12;border-color:#e6c9a2;background:#fff6e8}
.badge{display:inline-block;font-size:12px;padding:2px 8px;border-radius:6px;
margin-left:8px}
.badge.sev{background:var(--sevbg);color:var(--sev);border:1px solid #f0c4c4}
.badge.warn{background:var(--warnbg);color:var(--warn);border:1px solid #f0d3c4}
.notice{background:var(--warnbg);border:1px solid #f0d3c4;border-radius:10px;
padding:12px 14px;font-size:14px;margin:14px 0}
.notice.nick{background:#f1f8f4;border-color:#cfe6da}
.notice.nick .nick-head{font-size:15px}
.notice.nick .nick-head b{font-size:17px}
.notice.nick .sub{margin:6px 0 0}
.notice.nick .sub a{white-space:nowrap}
.notice.nick .sub.src{font-size:12px;margin-top:4px}
.notice.warnbox{background:#fff8e8;border-color:#ecd9a8}
table{width:100%;border-collapse:collapse;font-size:14px;margin-top:8px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600;font-size:13px}
table.res{margin-top:12px;background:#fff;border:1px solid var(--line);
border-radius:12px;overflow:hidden}
table.res th{background:#faf9f6;font-size:12px;letter-spacing:.02em}
table.res td{vertical-align:top}
table.res tbody tr:hover{background:#fcfcfa}
.c-ing{font-weight:600;width:26%}
.c-dose{width:14%;white-space:nowrap;font-variant-numeric:tabular-nums}
.c-brand{width:38%}
.c-mah{width:22%;color:var(--muted);font-size:13px}
footer{border-top:1px solid var(--line);color:var(--muted);font-size:13px;
padding:18px 0 40px;background:#fff}
footer .wrap{display:flex;gap:16px;flex-wrap:wrap;align-items:baseline}
.foot-links{margin-left:auto;display:flex;gap:14px;white-space:nowrap}
.foot-links a{color:var(--accent)}
.report-line{margin-top:14px}
kbd{background:#eee;padding:1px 5px;border-radius:4px;font-size:13px}
.empty{color:var(--muted);padding:20px 0}
.release{border-top:1px solid var(--line);padding:18px 0 6px;margin-top:18px}
.release:first-of-type{border-top:0;margin-top:0;padding-top:4px}
.release h2{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;margin:0 0 8px}
.release .rel-date{font-size:13px;font-weight:400;color:var(--muted)}
.release table{font-size:13px}
.release ul{margin:6px 0 12px;padding-left:22px}
.release li{margin:4px 0}
"""

APP_JS = r"""
const box = document.getElementById('q');
const out = document.getElementById('out');
const ctry = document.getElementById('country');
const meta = document.getElementById('meta');
// 页面在 / 或 /es/ 或 /zh/ 下，资源与内容页都在站点根目录，按 app.js 的位置推根路径
const BASE = ((document.currentScript && document.currentScript.src) || location.href)
  .replace(/assets\/app\.js.*$/, '');
let IDX = [], NICKS = [], CONF = [];
// P0 索引懒加载：页面加载时只下 app.js/css/i18n（约 16 KB），
// 全量索引（34.8 MB，gzip 约 6 MB）等用户真的要用搜索时再下。
let IDX_READY = false, IDX_P = null;
// ARTG 名称层：只在产品没命中时懒加载，避免每次搜索都多下 3 MB
let ARTG = null, artgLoading = false;
function artgPaint(nq){
  const box = document.getElementById('artgbox');
  if(!box || !ARTG) return;
  const T = window.T || (k=>k);
  const rows = ARTG.filter(r => r[0] === nq || r[0].startsWith(nq + ' '))
    .sort((a,b) => a[1].length - b[1].length).slice(0, 20);
  if(!rows.length){ box.innerHTML = ''; return; }
  const body = rows.map(r => `<tr><td>${esc(r[1])}</td><td>${esc(r[2]) || '—'}</td>
    <td><code>${esc(r[3])}</code></td></tr>`).join('');
  box.innerHTML = `<h2>${T('artg.title')}</h2><p class="sub">${T('artg.note')}</p>
    <table class="res"><thead><tr><th>${T('col.brand')}</th><th>${T('artg.sponsor')}</th>
    <th>${T('artg.id')}</th></tr></thead><tbody>${body}</tbody></table>`;
}
function artgFallback(nq){
  if(!nq || nq.length < 3 || !document.getElementById('artgbox')) return;
  if(ARTG){ artgPaint(nq); return; }
  if(artgLoading) return;
  artgLoading = true;
  fetch(BASE + 'data/artg.json').then(r => r.json()).then(d => {
    ARTG = d || []; artgLoading = false; artgPaint(nq);
  }).catch(() => { ARTG = []; artgLoading = false; });
}

function norm(s){
  return (s||'').normalize('NFKC').toLowerCase()
    .replace(/[®™©]/g,' ')
    .replace(/[\u0300-\u036f]/g,'')
    .replace(/\s+/g,' ').trim();
}
function splitDose(q){
  // 把「Lipitor 20mg」「两只青蛙 500mg」「875/125 mg」里的剂量切出来，
  // 名字部分才拿去和索引比对——不切的话带剂量的搜索会一个都命中不了。
  const ratio = q.match(/([\d.]+)\s*\/\s*([\d.]+)\s*(mg|mcg|µg|ug|g)\b/i);
  const single = q.match(/([\d.]+)\s*(mg|mcg|µg|ug|g|ml|iu|%|万单位)\b/i);
  const m = ratio || single;
  if(!m) return [q, null];
  const rest = (q.slice(0, m.index) + ' ' + q.slice(m.index + m[0].length))
    .replace(/\s+/g,' ').trim();
  return [rest, [m[1], (ratio ? m[3] : m[2]).toLowerCase()]];
}
function lev(a,b){
  if(Math.abs(a.length-b.length)>3) return 99;
  const d=Array.from({length:b.length+1},(_,i)=>i);
  for(let i=1;i<=a.length;i++){
    let prev=d[0]; d[0]=i;
    for(let j=1;j<=b.length;j++){
      const t=d[j];
      d[j]=Math.min(d[j]+1,d[j-1]+1,prev+(a[i-1]===b[j-1]?0:1));
      prev=t;
    }
  }
  return d[b.length];
}
function tier(nq,k){
  if(k===nq) return ['exact',1.0];
  if(k.replace(/ /g,'')===nq.replace(/ /g,'')) return ['compact',0.95];
  if(k.startsWith(nq)) return ['prefix',0.80];
  // 中文药名普遍很短：「利嗪」「头孢」「地平」这种两三个字就是有效线索，
  // 用英文的四字下限会把只记得一部分的人挡在门外。
  const cjk = /[\u4e00-\u9fff]/.test(nq);
  const minSub = cjk ? 2 : 4;
  if(nq.length>=minSub && k.includes(nq)) return ['contains',0.70];
  if(nq.length>=4 && lev(nq,k) <= (nq.length>=9 ? 3 : 2)) return ['fuzzy',0.55];
  return null;
}
function doseNum(s){ const m=(s||'').match(/[\d.]+/); return m?parseFloat(m[0]):0; }
function esc(s){
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function aliasHits(nq){
  // 俗称只做精确 / 连写命中：昵称差一个字往往就是另一个梗，模糊匹配会闹笑话。
  return NICKS.filter(a => a.n === nq || a.n.replace(/ /g,'') === nq.replace(/ /g,''));
}
function confHits(nq){
  // 易混淆药对也只做精确命中：这是「名字像」的提示，不做模糊扩展。
  return CONF.filter(p => p.n === nq);
}
function rowHTML(r){
  const T = window.T || (k=>k);
  const badge = r.l==='severe' ? `<span class="badge sev">${T('badge.severe')}</span>` :
                r.l==='warning' ? `<span class="badge warn">${T('badge.warning')}</span>` : '';
  const tags = r.c.map(x=>`<span class="tag ${x.toLowerCase()}">${x}</span>`).join('');
  const combo = (r.x || '').indexOf(' + ') >= 0
    ? `<span class="tag combo">${T('badge.combo')}</span>` : '';
  const link = r.u ? `${BASE}name/${r.u}` : `${BASE}drug/${r.v}.html`;
  const mah = r.m ? (r.mn > 1 ? `${r.m} <span class="more">+${r.mn-1}</span>` : r.m) : '';
  return `<tr>
    <td class="c-ing">${r.x || '—'}</td>
    <td class="c-dose">${r.d || '—'}</td>
    <td class="c-brand"><a href="${link}">${r.b}</a>${tags}${combo}${badge}</td>
    <td class="c-mah">${mah || '—'}</td></tr>`;
}
function render(){
  const q = box.value.trim();
  if(!q){ out.innerHTML=''; meta.textContent='';
    const r0 = document.getElementById('report'); if(r0) r0.style.display='none'; return; }
  const [nameQ, st] = splitDose(q);
  const nq = norm(nameQ);
  const c = ctry.value;
  const nicks = aliasHits(nq);
  const confs = confHits(nq);
  const nickSids = new Set(nicks.map(a=>a.v).filter(Boolean));
  // 只有「没有对应成分」的叫法（如海洛因的 Hammer）时，不要再拿商品名做包含匹配：
  // 否则会倒出一堆名字里刚好有 hammer 的保健品，和这个词没关系。
  const onlyUnmapped = nicks.length > 0 && nicks.every(a => !a.v);
  let hits=[];
  const seen = new Set();
  const addHit = (e, t) => {
    if(seen.has(e.k)) return;
    seen.add(e.k);
    let score = 0.55*t[1] + 0.20*(c && e.c.includes(c) ? 1 : 0.5);
    score += 0.15*(st && e.s.some(x=>x.toLowerCase().startsWith(st[0]+' ')) ? 1 : 0.5);
    score += 0.05;
    hits.push([score, t[0], e]);
  };
  // 第一遍只认确切的几种匹配；模糊匹配要等确定命中太少时才补，
  // 否则搜 Lipitor 会把 Zifitor、Dipifor 这些隔壁牌子一起倒出来。
  for(const e of IDX){
    if(onlyUnmapped) continue;
    // 复方产品：e.x 是这条名字下成分的中文/英文展示串（最多 6 个），
    // 直接按成分名 tokens 比对，比在每个索引条目里再存一份 vs 数组省 4 MB。
    const subs = (e.x || '').split(' + ');
    const byNick = (e.v && nickSids.has(e.v)) ||
      nicks.some(a => a.i && subs.includes(a.i));
    const t = byNick ? ['nickname', 1.0] : tier(nq, e.k);
    if(!t || t[0]==='fuzzy') continue;
    addHit(e, t);
  }
  let fuzzyUsed = false;
  if(hits.length === 0 && nicks.length === 0){
    for(const e of IDX){
      const t = tier(nq, e.k);
      if(!t || t[0]!=='fuzzy') continue;
      const before = hits.length;
      addHit(e, t);
      if(hits.length > before) fuzzyUsed = true;
    }
  }
  hits.sort((a,b)=> b[0]-a[0] || (a[2].q?1:0)-(b[2].q?1:0) ||
                     b[2].n-a[2].n || a[2].d.length-b[2].d.length);
  const shown = hits.slice(0,40);
  // 选了国家 = 「这个药在那个国家叫什么」，不是「只显示那个国家的搜索命中」。
  // 先用查询词定位成分（不受国家限制），再把这个成分在目标国的商品名列出来。
  let display = shown;
  if(c && hits.length){
    try{
      const sids = new Set();
      for(const [, , e] of hits.slice(0,3)){
        const list = (e.vs && e.vs.length) ? e.vs : [e.v];
        list.filter(Boolean).forEach(s => sids.add(s));
      }
      const inCountry = IDX.filter(x => (x.c || []).includes(c) &&
        ((x.vs && x.vs.length) ? x.vs : [x.v]).filter(Boolean).some(s => sids.has(s)));
      // display 的每一项必须是 [score, tier, entry] 三元组，和 shown 同构，
      // 否则下面 for(const [, , e] of display) 会解构出 undefined。
      if(inCountry.length) display = inCountry.slice(0,40).map(e => [0, 'country', e]);
    }catch(err){
      console.error('country resolve failed', err);
    }
  }
  const T = window.T || (k=>k);
  if(!hits.length && nicks.length){
    meta.textContent = `${nicks.length} ${T('res.alias')} · ${T('res.alias_no_products')}`;
  } else {
    meta.textContent = hits.length
      ? (fuzzyUsed
          ? `${T('res.fuzzy')} · ${hits.length} ${T(nicks.length ? 'res.brands' : 'res.matched')}`
          : `${hits.length} ${T(nicks.length ? 'res.brands' : 'res.matched')}`)
      : (c ? `${T('res.none')} — ${T('res.notin')}. ${T('res.caveat')}.`
           : `${T('res.none')} — ${T('res.caveat')}.`);
  }
  // 俗称命中：先说清「这不是商品名，是某个成分的叫法」，再列该成分的商品名。
  let nickHTML = '';
  if(nicks.length){
    nickHTML = nicks.slice(0,3).map(a=>{
      const target = a.v
        ? `<a href="${BASE}drug/${encodeURIComponent(a.v)}.html">${esc(a.x)}</a>`
        : `<b>${esc(a.x)}</b>`;
      const detail = window.LANG === 'zh' ? (a.hint || a.m) : (a.me || '');
      const hint = detail ? `<div class="sub">${esc(detail)}</div>` : '';
      const packs = a.np ? ` · ${a.np} ${T('card.packs')}` : '';
      const caveat = a.k === 'class' ? T('nick.class_caveat')
        : a.k === 'folk' ? T('nick.folk_caveat')
        : (a.v ? T('nick.caveat') : T('nick.nomap_caveat'));
      const unverified = a.cf && a.cf !== 'documented';
      const cfTag = !unverified ? ''
        : (a.cf === 'user'
            ? ` <span class="tag warn">${T('nick.unverified')}</span>`
            : ` <span class="tag">${T('nick.community')}</span>`);
      // 每条都显示出处；有 URL 的做成链接，没有 URL 的至少显示 provenance 文本。
      const srcText = a.src
        ? (a.su
            ? `<a href="${esc(a.su)}" target="_blank" rel="noopener">${esc(a.src)}</a>`
            : esc(a.src))
        : '—';
      const srcLine = `<div class="sub src">${T('nick.source')}: ${srcText}</div>`;
      return `<div class="notice nick"><div class="nick-head">${T('nick.hit')}：
        <b>${esc(a.a)}</b> → ${target}
        <span class="tag">${esc(T('nick.'+a.k))}</span>${cfTag}</div>
        <div class="sub">${caveat}${packs}</div>${hint}${srcLine}</div>`;
    }).join('');
    if(nicks.length > 1) nickHTML += `<div class="notice">${T('nick.ambiguous')}</div>`;
  }
  let confHTML = '';
  if(confs.length){
    const items = confs.slice(0,6).map(p=>{
      const label = p.sid
        ? `<a href="${BASE}drug/${encodeURIComponent(p.sid)}.html">${esc(p.x)}</a>`
        : `<b>${esc(p.x)}</b>`;
      const tml = p.tml ? ` <code>${esc(p.tml)}</code>` : '';
      return label + tml;
    }).join('、');
    confHTML = `<div class="notice warnbox"><b>${T('conf.search_hit')}：</b>${items}.
      <a href="${BASE}confused.html">${T('drug.confused_all')}</a></div>`;
  }
  const shownKeys = new Set(shown.map(x=>x[2].k));
  const byFam = new Map();
  for(const [, , e] of shown){
    if(!e.g) continue;
    if(!byFam.has(e.g)) byFam.set(e.g, {note:e.gn||'', comps:new Set()});
    byFam.get(e.g).comps.add(e.x);
  }
  let warnHTML = '';
  const T2 = window.T || (k=>k);
  for(const [label, f] of byFam){
    if(f.comps.size > 1){
      warnHTML += `<div class="notice"><b>${T2('fam.warn')}：${label}。</b>${f.note||''}</div>`;
    }
  }
  let extraHTML = '';
  for(const [label, f] of byFam){
    const members = IDX.filter(x=>x.g===label && !shownKeys.has(x.k));
    if(!members.length) continue;
    extraHTML += `<h2>${T2('fam.title')}</h2>` +
      members.map(e=>`<div class="card"><h3><a href="${e.u?BASE+'name/'+e.u:BASE+'drug/'+e.v+'.html'}">${e.d}</a></h3>
      <div class="meta">${e.x} · ${e.s.join(' / ')||'—'}</div></div>`).join('');
  }
  // 主结果：保留相关度顺序（精确命中在前），每一行内部再按剂量数字排序。
  // 这样"成分-剂量"始终是最左两列，但不会被无关的模糊命中顶到前面。
  let rows=[];
  for(const [, , e] of display){
    const ds = (e.s && e.s.length) ? e.s.slice().sort((a,b)=>doseNum(a)-doseNum(b)) : [''];
    for(const d of ds) rows.push({x:e.x, d:d, b:e.d, m:e.m, mn:e.mn, c:e.c, l:e.l, u:e.u, v:e.v});
  }
  const capped = rows.slice(0, 80);

  // 精确命中某个品牌之后，再把「同一成分的其他商品」单独列一段：
  // 用户搜的是牌子，但真正想知道的往往是这个成分还有哪些选择。
  let sameHTML = '';
  const exactSubs = new Set();
  for(const [, t, e] of shown){
    if(t !== 'exact' && t !== 'compact') continue;
    (e.vs && e.vs.length ? e.vs : [e.v]).forEach(s => exactSubs.add(s));
  }
  if(exactSubs.size && exactSubs.size <= 6){
    const others = IDX.filter(x => !shownKeys.has(x.k) &&
      (x.vs && x.vs.length ? x.vs : [x.v]).some(s => exactSubs.has(s)));
    if(others.length){
      const oRows = [];
      for(const e of others.slice(0, 40)){
        const ds = (e.s && e.s.length) ? e.s.slice().sort((a,b)=>doseNum(a)-doseNum(b)) : [''];
        for(const d of ds) oRows.push({x:e.x, d:d, b:e.d, m:e.m, mn:e.mn, c:e.c, l:e.l, u:e.u, v:e.v});
      }
      sameHTML = `<h2>${T2('same.ing')}</h2>` +
        `<p class="sub">${T2('same.note')}</p>` +
        `<table class="res"><thead><tr>
          <th>${T2('col.ing')}</th><th>${T2('col.dose')}</th>
          <th>${T2('col.brand')}</th><th>${T2('col.mah')}</th>
        </tr></thead><tbody>${oRows.slice(0,80).map(rowHTML).join('')}</tbody></table>`;
    }
  }

  out.innerHTML = confHTML + nickHTML + warnHTML + (capped.length ? `<table class="res"><thead><tr>
      <th>${T2('col.ing')}</th><th>${T2('col.dose')}</th>
      <th>${T2('col.brand')}</th><th>${T2('col.mah')}</th>
    </tr></thead><tbody>${capped.map(rowHTML).join('')}</tbody></table>` : '') + sameHTML + extraHTML;
  // 产品层没命中时，再去 ARTG 名称层找「登记存在、成分未收录」的条目；
  // 选了澳洲但澳洲产品为空时同样触发（很多 listed OTC 只有 ARTG 名字）。
  const hasAU = display.some(x => ((x[2].c) || []).includes('AU'));
  if(!capped.length || (c === 'AU' && !hasAU)){
    out.insertAdjacentHTML('beforeend', '<div id="artgbox"></div>');
    artgFallback(nq);
  }
  const rep = document.getElementById('report');
  if(rep){
    rep.style.display = 'block';
    const a = document.getElementById('reportLink');
    if(a) a.href = reportURL(q);
  }
}
function reportURL(q){
  const body = [
    '**查询词 / query**: ' + (q || ''),
    '**页面 / page**: ' + location.href,
    '**期望结果 / expected**: ',
    '**实际结果 / actual**: ',
    '**包装或批号 / pack or lot**: ',
    ''
  ].join('\n');
  return 'REPORT_REPO_PLACEHOLDER' + '/issues/new?labels=data-error&template=data-error.yml'
    + '&title=' + encodeURIComponent('数据错误: ' + (q || ''))
    + '&body=' + encodeURIComponent(body);
}
// ── P0 索引懒加载 ──────────────────────────────────────────────────
// 页面加载时不请求完整索引；首次输入 / 聚焦搜索框 / 点示例按钮，或带 ?q= 深链
// 进来时才 loadIndex()。加载失败给出提示与「重试」按钮（不做静默失败）。
// ?legacy=1 一键回滚成旧行为（页面加载即拉全量索引）。
const LEGACY = new URLSearchParams(location.search).get('legacy') === '1';
const hintEl = document.getElementById('loadhint');
const HINT_IDLE = '首次搜索需要加载索引，约 6 MB（gzip）。'
  + 'First search needs to load the index (~6 MB gzipped) — start typing or focus the box.';
const HINT_LOADING = '正在加载索引… Loading the index…（首次约 6 MB / ~6 MB first time）';
function setHint(html, show){
  if(!hintEl) return;
  hintEl.innerHTML = html || '';
  hintEl.style.display = (show === false || !html) ? 'none' : '';
}
function loadIndex(){
  if(IDX_READY) return Promise.resolve(true);
  if(IDX_P) return IDX_P;
  if(!LEGACY) setHint(HINT_LOADING);
  IDX_P = Promise.all([
    fetch(BASE + 'data/index.json').then(r=>{ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); }),
    fetch(BASE + 'data/aliases.json').then(r=>r.json()).catch(()=>[]),
    fetch(BASE + 'data/confused.json').then(r=>r.json()).catch(()=>[])
  ]).then(([d,a,c])=>{
    IDX=d||[]; NICKS=a||[]; CONF=c||[]; IDX_READY=true;
    setHint('');
    return true;
  }).catch(err=>{
    // 失败后清掉缓存的 Promise，允许点「重试」重新发起。
    IDX_P = null;
    if(hintEl) hintEl.style.display = 'none';
    out.innerHTML = '<div class="notice">索引没加载成功 / Index failed to load. '
      + '如果是本地双击打开的页面，浏览器会拦截本地文件读取；'
      + 'If you opened this file directly the browser blocks local file reads — run '
      + '<kbd>python -m http.server</kbd> and visit <kbd>http://localhost:8000/</kbd>.'
      + '<br>' + esc(String((err && err.message) || err || ''))
      + '<br><button type="button" data-retry="1">重试 / Retry</button></div>';
    return false;
  });
  return IDX_P;
}
function startSearch(){
  if(IDX_READY){ render(); return; }
  loadIndex().then(ok => { if(ok) render(); });
}
// 失败提示里的「重试」按钮（事件委托，重试后直接按当前输入出结果）。
out.addEventListener('click', ev => {
  const b = ev.target && ev.target.closest ? ev.target.closest('[data-retry]') : null;
  if(!b) return;
  out.innerHTML = '';
  loadIndex().then(ok => { if(ok) render(); });
});
box.addEventListener('input', startSearch);
ctry.addEventListener('change', startSearch);
document.querySelectorAll('[data-q]').forEach(b=>b.addEventListener('click',()=>{
  box.value=b.dataset.q; startSearch(); box.focus();
}));
// 聚焦搜索框就先预取索引：等用户敲键时 6 MB 已经在路上。
box.addEventListener('focus', ()=>{ if(!IDX_READY) loadIndex(); });
const initial = new URLSearchParams(location.search).get('q');
if(initial){ box.value = initial; }
const ctry0 = new URLSearchParams(location.search).get('country');
if(ctry0 && ctry){ ctry.value = ctry0.toUpperCase(); }
if(LEGACY){
  // 回滚开关：?legacy=1 = 旧行为，页面一加载就拉全量索引。
  setHint('');
  out.innerHTML = '<div class="sub">Loading index… 正在加载索引（第一次会慢一点）</div>';
  loadIndex().then(ok => { if(ok) render(); });
} else if(initial){
  // ?q= 深链：立即加载（加载完直接出结果）。
  startSearch();
}
"""


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def key_file(key: str) -> str:
    """文件名尽量保留可读性（含中文），只替换路径非法字符。

    NHSA 的 CSV 里混进了控制字符（例如「糠酸莫米松乳膏\\x02」），
    不剥掉会让 Windows 直接抛 OSError，整个建站中断。
    """
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", "", key or "")
    s = re.sub(r'[\\/:*?"<>|\s]+', "-", cleaned.strip()).strip("-.")
    if len(s) > 80:
        s = s[:60] + "-" + hashlib.md5(key.encode("utf-8")).hexdigest()[:8]
    if not s:
        s = "k-" + hashlib.md5(key.encode("utf-8")).hexdigest()[:10]
    return s + ".html"


def page(title: str, body: str, prefix: str = "", lang: str = "en",
         alternates: bool = False) -> str:
    ver = f"{LATEST_VERSION} · {LATEST_DATE}" if LATEST_VERSION else "What's new"
    sw = "".join(
        f'<a data-lang="{code}" href="?lang={code}">{label}</a>' for code, label, _ in LANGS
    )
    alt = ""
    if alternates:
        alt = ("\n".join(
            f'<link rel="alternate" hreflang="{code}" href="/{path}">'
            for code, _l, path in LANGS
        ) + '\n<link rel="alternate" hreflang="x-default" href="/">')
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · Medicine Brand Cross-Reference</title>{alt}
<link rel="stylesheet" href="{prefix}assets/style.css?v={BUILD_V}">
<script src="{prefix}assets/i18n.js?v={BUILD_V}"></script></head>
<body>
<header><div class="wrap">
  <a class="logo" href="{prefix}index.html">Medicine Brand Cross-Reference
    <span class="logo-zh">药品商品名跨国定位</span></a>
  <nav><a href="{prefix}index.html" data-i18n="nav.search">Search</a>
    <a href="{prefix}confused.html" data-i18n="nav.confused">Confused names</a>
    <a href="{prefix}about.html" data-i18n="nav.about">About</a>
    <a href="{prefix}whats-new.html" data-i18n="nav.whatsnew">What's new</a>
    <span class="langs">{sw}</span></nav>
</div></header>
<main><div class="wrap">{body}</div></main>
<footer><div class="wrap">
  <span data-i18n="footer">{esc(I18N['en']['footer'])}</span>
  <span class="foot-links">
    <a href="{prefix}whats-new.html">{ver}</a>
    <a href="{REPORT_REPO}/issues/new?labels=data-error&amp;template=data-error.yml"
       target="_blank" rel="noopener" data-i18n="report.link">Report a data error</a>
    <a href="{REPORT_REPO}/issues" target="_blank" rel="noopener"
       data-i18n="report.all">Known issues</a>
  </span>
</div></footer>
<script src="{prefix}assets/i18n.js?v={BUILD_V}"></script>
</body></html>"""


# ------------------------------------------------------------ release notes
def _md_inline(text: str) -> str:
    s = esc(text)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
               r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    return s


def _is_cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf"


def _md_join(parts) -> str:
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if out and not (_is_cjk(out[-1]) and _is_cjk(p[0])):
            out += " "
        out += p
    return out


def _md_table(rows) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    if len(cells) >= 2 and all(re.fullmatch(r":?-{2,}:?", c) for c in cells[1]):
        head, body = cells[0], cells[2:]
    else:
        head, body = cells[0], cells[1:]
    html = ["<table><thead><tr>"]
    html += [f"<th>{_md_inline(c)}</th>" for c in head]
    html.append("</tr></thead><tbody>")
    for row in body:
        html.append("<tr>" + "".join(f"<td>{_md_inline(c)}</td>" for c in row) + "</tr>")
    html.append("</tbody></table>")
    return "".join(html)


def _md_list(lines, start):
    items = []  # [text, [subitems]]
    i = start
    while i < len(lines):
        m = re.match(r"^(\s*)-\s+(.*)$", lines[i])
        if not m or len(m.group(1)) > 0:
            break
        items.append([m.group(2), []])
        i += 1
        while i < len(lines) and lines[i].strip():
            m2 = re.match(r"^(\s*)-\s+(.*)$", lines[i])
            if m2 and len(m2.group(1)) >= 2:
                sub = [m2.group(2)]
                i += 1
                while (i < len(lines) and lines[i].strip()
                       and not re.match(r"^\s*-\s+", lines[i])):
                    sub.append(lines[i].strip())
                    i += 1
                items[-1][1].append(_md_join(sub))
            elif m2:
                break
            else:
                items[-1][0] = _md_join([items[-1][0], lines[i]])
                i += 1
    html = ["<ul>"]
    for text, subs in items:
        html.append("<li>" + _md_inline(text))
        if subs:
            html.append("<ul>" + "".join(f"<li>{_md_inline(s)}</li>" for s in subs) + "</ul>")
        html.append("</li>")
    html.append("</ul>")
    return "".join(html), i


def _md_block(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append("<p>" + _md_inline(_md_join(para)) + "</p>")
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
            continue
        if line.startswith("### "):
            flush()
            out.append("<h3>" + _md_inline(line[4:].strip()) + "</h3>")
            i += 1
            continue
        if line.lstrip().startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_md_table(rows))
            continue
        if re.match(r"^-\s+", line):
            flush()
            html, i = _md_list(lines, i)
            out.append(html)
            continue
        para.append(line)
        i += 1
    flush()
    return "\n".join(out)


def load_releases() -> list[dict]:
    try:
        text = CHANGELOG.read_text(encoding="utf-8")
    except OSError:
        return []
    releases = []
    for part in re.split(r"^## ", text, flags=re.M)[1:]:
        head, _, body = part.partition("\n")
        m = re.match(r"(v[0-9][^\s]*)\s*[—–-]\s*(\d{4}-\d{2}-\d{2})", head.strip())
        if not m:
            continue
        releases.append({"version": m.group(1), "date": m.group(2),
                         "html": _md_block(body.strip())})
    return releases


def build_whats_new() -> None:
    releases = load_releases()
    cards = []
    for r in releases:
        cards.append(
            f'<section class="release"><h2>{esc(r["version"])}'
            f'<span class="rel-date">{esc(r["date"])}</span></h2>{r["html"]}</section>')
    body = f"""<h1>What's new 更新日志</h1>
<p class="sub">每次上线都带一条更新摘要。旧版本已按 git tag 补到这里；完整历史见
<a href="{REPORT_REPO}/blob/main/CHANGELOG.md" target="_blank" rel="noopener">CHANGELOG.md</a>。</p>
{''.join(cards)}"""
    (OUT / "whats-new.html").write_text(page("What's new", body), encoding="utf-8")


def _norm_name(s: str) -> str:
    """名字归一化，只用于比较 key 与成分 INN 是否同一个词。"""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def load_index(db: sqlite3.Connection):
    """构建检索索引：只收有品牌名的 key。全量一次查询，避免 N+1。"""
    coll = {r[0]: r[1] for r in db.execute("SELECT key_id, level FROM collision")}
    displays: dict[str, str] = {}
    for key_id, raw in db.execute(
        "SELECT key_id, raw FROM name_variant ORDER BY key_id, v_id"
    ):
        displays.setdefault(key_id, raw)

    agg: dict[str, dict] = {}
    mixed_inn: set[str] = set()
    # 每个产品自己的成分名集合：复方产品在每个成分的通用名 key 下都有一行
    # name_type=inn，但当前这行不一定是那个成分（join 会展开所有成分），
    # 所以要用「产品级」的集合判断，而不是当前行的 inn_en。
    comp_keys: dict[str, set[str]] = {}
    for pid, inn in db.execute(
        """SELECT pc.product_id, s.inn_en
           FROM product_component pc
           JOIN variant v ON v.variant_id = pc.variant_id
           JOIN substance s ON s.substance_id = v.substance_id"""
    ):
        comp_keys.setdefault(pid, set()).add(_norm_name(inn))
    for (key_id, pid, country, form_base, dosage_form, sv, su,
         inn_en, sid, mah, ntype, n_ing) in db.execute(
        """SELECT pn.key_id, p.product_id, p.country, p.form_base, p.dosage_form,
                  pc.strength_value, pc.strength_unit, s.inn_en, s.substance_id, p.mah,
                  pn.name_type,
                  (SELECT COUNT(*) FROM product_component pc2
                   WHERE pc2.product_id = p.product_id) AS n_ing
           FROM product_name pn
           JOIN product p ON p.product_id = pn.product_id
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           JOIN substance s ON s.substance_id = v.substance_id
           WHERE pn.name_type IN ('trade', 'inn')"""
    ):
        # 复方产品的「成分名」行（name_type=inn 且 key 就是其中一个成分）不能并进
        # 该成分的通用名条目，否则 acetaminophen 条目会把复方里的其他成分、剂量、
        # 厂家全并进来，看起来像一个六成分产品。复方仍按商品名 / 复方全名检索。
        if (ntype == "inn" and n_ing > 1
                and _norm_name(key_id) in comp_keys.get(pid, ())):
            mixed_inn.add(key_id)
            continue
        a = agg.get(key_id)
        if a is None:
            a = agg[key_id] = {"pids": set(), "c": set(), "subs": [], "s": [],
                               "f": [], "v": sid, "mah": {}, "trade": False,
                               "sids": set()}
        if ntype == "trade":
            a["trade"] = True
        a["sids"].add(sid)
        a["pids"].add(pid)
        a["c"].add(country)
        if inn_en not in a["subs"]:
            a["subs"].append(inn_en)
        if sv is not None:
            st = f"{sv:g} {su or ''}".strip()
            if st not in a["s"]:
                a["s"].append(st)
        f = form_base or dosage_form
        if f and f not in a["f"]:
            a["f"].append(f)
        if mah:
            a["mah"][mah] = a["mah"].get(mah, 0) + 1

    entries = []
    fam = {}
    for key_id, label, note in db.execute(
        "SELECT nf.key_id, bf.label, bf.note FROM name_family nf"
        " JOIN brand_family bf ON bf.family_id = nf.family_id"
    ):
        fam[key_id] = (label, note)
    for key_id, a in agg.items():
        n = len(a["pids"])
        level = coll.get(key_id, "info")
        # 只由单方产品组成的通用名条目：碰撞视图仍把复方的成分算进来，
        # 这里改回 info，并且不单独成页（直接链到成分页），避免「同名不同药 /
        # 释放机制不同」这类误导性警告。
        pure_inn = key_id in mixed_inn and len(a["sids"]) == 1
        if pure_inn:
            level = "info"
        # 只有这些名字值得单独成页：有碰撞的、或包装数够多的。
        # 其余名字仍能被搜到，卡片直接链到成分页——不为只有一个包装的冷门名字生成几万张页。
        # 通用名照样能搜到，但只有「有品牌名」或碰撞/多包装的名字才单独成页，
        # 否则光中国就会多出上万张价值很低的页面。
        worth_page = (not pure_inn) and (a["trade"] or level == "warning") and (
            level == "warning" or (level == "severe" and n >= 2) or n >= 3)
        entry = {
            "k": key_id,
            "d": displays.get(key_id, key_id),
            "c": sorted(a["c"]),
            "x": " + ".join(a["subs"][:6]),
            "s": a["s"][:6],
            "f": a["f"][0] if a["f"] else "",
            "l": level,
            "n": n,
            "v": a["v"],
            "vs": sorted(a["sids"]) if len(a["sids"]) > 1 else None,
            "u": key_file(key_id) if worth_page else "",
            "g": fam[key_id][0] if key_id in fam else "",
            "gn": fam[key_id][1] if key_id in fam else "",
            "m": (max(a["mah"].items(), key=lambda kv: kv[1])[0]
                  if a["mah"] else ""),
            "mn": len(a["mah"]),
        }
        # 加拿大 DPD 的商品名里混着「222 AF EXTRA STRENGTH」这类以数字开头的名字
        # 和「+ SINUS COLD FORMULA」这种被削掉前缀的残名。它们在索引里查得到，
        # 但排到最前面会顶掉真正的品牌，所以打个标记降权（不影响纯字母开头的名字）。
        if "CA" in a["c"] and (key_id[:1].isdigit() or key_id[:1] in "+-/&"):
            entry["q"] = 1
        entries.append(entry)
    entries.sort(key=lambda e: -e["n"])
    return entries


def load_aliases(db: sqlite3.Connection) -> list[dict]:
    """俗称索引：单独一份 aliases.json。

    不塞进商品名索引，因为昵称属于「成分」，不属于某个名字键——塞进去会让
    「两只青蛙」变成一张挂着几千个包装的商品名。
    """
    counts: dict[str, tuple[int, set[str]]] = {}
    for sid, n, countries in db.execute(
        """SELECT v.substance_id, COUNT(DISTINCT p.product_id),
                  GROUP_CONCAT(DISTINCT p.country)
           FROM product p
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           WHERE p.status = 'active'
           GROUP BY v.substance_id"""
    ):
        counts[sid] = (n, set((countries or "").split(",")))
    out = []
    for (alias, norm, sid, zh, label_en, kind, confidence, note, source, inn_en,
         inn_zh, meaning_zh, meaning_en, country, source_url) in db.execute(
        """SELECT a.alias, a.alias_norm, a.substance_id, a.label_zh, a.label_en,
                  a.kind, a.confidence, a.note, a.source, s.inn_en, s.inn_zh,
                  a.meaning_zh, a.meaning_en, a.country, a.source_url
           FROM alias_all a
           LEFT JOIN substance s ON s.substance_id = a.substance_id
           ORDER BY a.alias_id"""
    ):
        n_prod, countries = counts.get(sid, (0, set()))
        display = zh or inn_zh or label_en or inn_en or alias
        out.append({
            "a": alias,
            "n": norm,
            "v": sid,
            "i": inn_en or label_en or alias,
            "x": display,
            "k": kind,
            "cf": confidence or "",
            "hint": note or "",
            "src": source or "",
            "m": meaning_zh or meaning_en or "",
            "me": meaning_en or "",
            "ct": country or "",
            "su": source_url or "",
            "c": sorted(countries),
            "np": n_prod,
        })
    return out


def load_confusable(db: sqlite3.Connection) -> list[dict]:
    """易混淆药对的检索索引：一行 = 一个名字 → 它容易混的那个名字。"""
    out: list[dict] = []
    for r in db.execute(
        """SELECT cp.norm_a, cp.norm_b, cp.name_a, cp.name_b,
                  cp.tml_a, cp.tml_b, cp.a_substance_id, cp.b_substance_id,
                  sa.inn_en AS a_inn, sa.inn_zh AS a_zh,
                  sb.inn_en AS b_inn, sb.inn_zh AS b_zh
           FROM confusable_pair cp
           LEFT JOIN substance sa ON sa.substance_id = cp.a_substance_id
           LEFT JOIN substance sb ON sb.substance_id = cp.b_substance_id"""
    ):
        # 搜 A 时提示 B，搜 B 时提示 A；x 是「对方」的显示名。
        out.append({
            "n": r["norm_a"],
            "x": r["b_zh"] or r["b_inn"] or r["name_b"],
            "sid": r["b_substance_id"],
            "tml": r["tml_b"],
        })
        out.append({
            "n": r["norm_b"],
            "x": r["a_zh"] or r["a_inn"] or r["name_a"],
            "sid": r["a_substance_id"],
            "tml": r["tml_a"],
        })
    return out


def build_drug_pages(db: sqlite3.Connection) -> int:
    # 一次性取全量，按成分分组；逐个成分查询会退化成正表全扫 × 4445 次
    products: dict[str, list] = {}
    for row in db.execute(
        """SELECT v.substance_id, p.country, p.form_base, p.dosage_form, p.release,
                  p.status, pc.strength_value, pc.strength_unit,
                  pc.per_volume_value, pc.per_volume_unit, p.product_id
           FROM product p
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id"""
    ):
        products.setdefault(row[0], []).append(row[1:])

    names: dict[str, list[str]] = {}
    for pid, raw in db.execute(
        """SELECT pn.product_id, nv.raw FROM product_name pn
           JOIN name_variant nv ON nv.key_id = pn.key_id
           WHERE pn.name_type = 'trade'"""
    ):
        bucket = names.setdefault(pid, [])
        if raw not in bucket:
            bucket.append(raw)

    subs = db.execute("SELECT substance_id, inn_en, inn_zh, atc FROM substance").fetchall()
    # 易混淆药对：成分页顶部给一条警告，链到对方成分页和 /confused.html。
    conflicts: dict[str, list[dict]] = defaultdict(list)
    for r in db.execute(
        """SELECT cp.name_a, cp.name_b, cp.tml_a, cp.tml_b,
                  cp.a_substance_id, cp.b_substance_id,
                  sa.inn_en AS a_inn, sa.inn_zh AS a_zh,
                  sb.inn_en AS b_inn, sb.inn_zh AS b_zh
           FROM confusable_pair cp
           LEFT JOIN substance sa ON sa.substance_id = cp.a_substance_id
           LEFT JOIN substance sb ON sb.substance_id = cp.b_substance_id"""
    ):
        a = {"sid": r["a_substance_id"], "name": r["a_zh"] or r["a_inn"] or r["name_a"],
             "en": r["a_inn"] or r["name_a"], "tml": r["tml_a"]}
        b = {"sid": r["b_substance_id"], "name": r["b_zh"] or r["b_inn"] or r["name_b"],
             "en": r["b_inn"] or r["name_b"], "tml": r["tml_b"]}
        if a["sid"]:
            conflicts[a["sid"]].append(b)
        if b["sid"]:
            conflicts[b["sid"]].append(a)

    nicknames: dict[str, list[str]] = {}
    for sid, alias in db.execute(
        """SELECT substance_id, alias FROM alias_all
           WHERE substance_id IS NOT NULL ORDER BY alias_id"""
    ):
        nicknames.setdefault(sid, []).append(alias)
    made = 0
    (OUT / "drug").mkdir(parents=True, exist_ok=True)
    for sid, inn_en, inn_zh, atc in subs:
        rows = products.get(sid)
        if not rows:
            continue

        brands = defaultdict(lambda: defaultdict(int))
        by_country = defaultdict(list)
        for (country, fb, df, rel, status, sv, su, pv, pu, pid) in rows:
            b = names.get(pid, [])
            for x in b:
                brands[country][x] += 1
            st = f"{sv:g} {su}" if sv is not None else ""
            if pv:
                st += f"/{pv:g} {pu}"
            by_country[country].append((st.strip(), rel, status, b[0] if b else ""))

        blocks = []
        for country in ("US", "GB", "CA", "CN", "ES", "MX", "AU"):
            if country not in by_country:
                continue
            uniq = {}
            for st, rel, status, brand in by_country[country]:
                k = (brand, st, rel)
                if k not in uniq:
                    uniq[k] = (brand, st, rel, status)
            ordered = sorted(uniq.values(),
                             key=lambda t: (t[0] == "", t[0].lower(), _sort_strength(t[1])))
            # 名字以数字/符号开头的（DPD 的「222 AF EXTRA STRENGTH」、
            # 「+ SINUS COLD FORMULA」）排在真正的品牌后面，否则一上来全是这种名字。
            ordered.sort(key=lambda t: (bool(t[0]) and (t[0][:1].isdigit()
                                                        or t[0][:1] in "+-/&"), 0))
            lis = []
            for brand, st, rel, status in ordered[:40]:
                name = esc(brand) if brand else '<span class="meta">（无商品名）</span>'
                st_html = esc(st) if st else (
                    '<span class="meta" data-i18n="drug.nostrength">not disclosed</span>')
                flag = {
                    "withdrawn": " <em>(withdrawn 已撤市)</em>",
                    "discontinued": " <em>(expired 有效期已过)</em>",
                    "unknown": " <em>(validity unknown 有效期待确认)</em>",
                }.get(status, "")
                lis.append(f"<tr><td>{name}</td><td>{st_html}</td>"
                           f"<td>{esc(rel) if rel != 'none' else '—'}</td>"
                           f"<td>{esc(status)}{flag}</td></tr>")
            more = (f'<p class="sub"><span data-i18n="drug.showing">showing first 40 of</span> '
                    f'{len(ordered)}</p>' if len(ordered) > 40 else "")
            blocks.append(
                f"<h2>{country} <span class='meta'>({len(ordered)} "
                f"<span data-i18n='drug.records'>records</span>)</span></h2>"
                f"<table><tr><th data-i18n='drug.brand'>Brand</th>"
                f"<th data-i18n='drug.strength'>Strength</th>"
                f"<th data-i18n='drug.release'>Release</th>"
                f"<th data-i18n='drug.status'>Status</th></tr>"
                + "".join(lis) + "</table>" + more
            )
        nick_line = ""
        if sid in nicknames:
            also = "、".join(esc(x) for x in nicknames[sid])
            nick_line = (f'<p class="sub">Also called 也叫：{also} '
                         f'<span class="tag">nickname 俗称</span></p>')
        conf_line = ""
        if conflicts.get(sid):
            items = []
            for other in conflicts[sid][:6]:
                label = esc(other["name"])
                if other["sid"]:
                    label = f'<a href="{other["sid"]}.html">{label}</a>'
                tml = (f' <code>{esc(other["tml"])}</code>' if other["tml"] else "")
                items.append(f"{label}（{esc(other['en'])}{tml}）")
            conf_line = (
                '<div class="notice warnbox"><b>'
                '<span data-i18n="drug.confused">Easily confused with</span>：</b>'
                + "、".join(items)
                + ' <span data-i18n="drug.confused_note">FDA recommends tall-man '
                  'lettering for this pair; check the ingredient, not the name.</span> '
                  f'<a href="../confused.html" data-i18n="drug.confused_all">All pairs</a></div>')
        body = f"""<h1>{esc(inn_zh) or esc(inn_en)} <span class="meta">{esc(inn_en)}</span></h1>
<p class="sub">ATC {esc(atc) or '—'} · <span data-i18n="drug.sid">Substance ID</span>
<code>{esc(sid)}</code></p>
{nick_line}
{conf_line}
<div class="notice" data-i18n="drug.notice">The same ingredient can carry completely different
brand names in different countries, and the same name can point to a different ingredient.
Listed by country — not interchangeable.</div>
{''.join(blocks) if blocks else '<p class="empty" data-i18n="drug.empty">No products recorded yet.</p>'}"""
        (OUT / "drug").mkdir(parents=True, exist_ok=True)
        (OUT / "drug" / f"{sid}.html").write_text(page(f"{inn_en}", body, "../"), encoding="utf-8")
        made += 1
    return made


def collect_name_data(db: sqlite3.Connection) -> dict:
    """一次性把名字页需要的全部数据取到内存，避免上万次逐条查询。"""
    data: dict[str, dict] = {}
    for (key_id, inn_en, sid, country, form_base, dosage_form, rel,
         sv, su) in db.execute(
        """SELECT pn.key_id, s.inn_en, s.substance_id, p.country, p.form_base,
                  p.dosage_form, p.release, pc.strength_value, pc.strength_unit
           FROM product_name pn
           JOIN product p ON p.product_id = pn.product_id
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           JOIN substance s ON s.substance_id = v.substance_id"""
    ):
        d = data.setdefault(key_id, {"subs": {}, "countries": set()})
        d["countries"].add(country)
        s = d["subs"].setdefault(
            sid, {"inn": inn_en, "country": set(), "s": set(), "f": set(), "rel": set()})
        s["country"].add(country)
        st = f"{sv:g} {su or ''}".strip() if sv is not None else ""
        if st:
            s["s"].add(st)
        s["f"].add(form_base or dosage_form)
        s["rel"].add(rel)
    return data


def build_name_pages(db: sqlite3.Connection, entries, data: dict,
                     families: dict | None = None, displays: dict | None = None) -> int:
    families = families or {}
    displays = displays or {e["k"]: e["d"] for e in entries}
    made = 0
    (OUT / "name").mkdir(parents=True, exist_ok=True)
    variants: dict[str, list[str]] = {}
    for key_id, raw in db.execute("SELECT key_id, raw FROM name_variant ORDER BY v_id"):
        variants.setdefault(key_id, []).append(raw)

    for e in entries:
        if not e["u"]:
            continue
        d = data.get(e["k"])
        if not d:
            continue
        level = e["l"]
        banner = {
            "severe": '<div class="notice"><b data-i18n="badge.severe">Same name, different drug</b>'
                      '<span data-i18n="name.severe"> — this brand name points to different '
                      'active ingredients. Check the composition.</span></div>',
            "warning": '<div class="notice"><b data-i18n="badge.warning">Different release</b>'
                       '<span data-i18n="name.warning"> — not interchangeable.</span></div>',
        }.get(level, "")

        cards = []
        for sid, g in d["subs"].items():
            rel = g["rel"] - {"none"}
            cards.append(
                f"""<div class="card"><h3><a href="../drug/{sid}.html">{esc(g['inn'])}</a></h3>
<div class="meta"><span data-i18n="name.countries">Countries</span>:
{esc('、'.join(sorted(g['country'])))} ·
<span data-i18n="name.form">Form</span>: {esc('、'.join(sorted(g['f'])))} ·
<span data-i18n="name.strength">Strength</span>:
{esc('、'.join(sorted(g['s'], key=_sort_strength)) or '—')}
{f" · <span data-i18n='name.release'>Release</span>: {esc('、'.join(sorted(rel)))}" if rel else ''}</div></div>"""
            )
        body = f"""<h1>{esc(e['d'])}</h1>
<p class="sub"><span data-i18n="name.also">Also written as</span>:
{esc('、'.join(variants.get(e['k'], [])[:6]))} ·
<span data-i18n="name.found">Found in</span>: {esc('、'.join(sorted(d['countries'])))}</p>
{banner}{''.join(cards) if cards else '<p class="empty" data-i18n="name.empty">No records</p>'}{_family_block(e, families, displays, variants)}"""
        (OUT / "name" / e["u"]).write_text(page(e["d"], body, "../"), encoding="utf-8")
        made += 1
    return made


def _family_block(e, families, displays, variants) -> str:
    """同一品牌在其他市场的写法——这是跨语言碰撞唯一能落地的地方。"""
    fam = families.get(e["k"])
    if not fam:
        return ""
    fam_id, label, note = fam["id"], fam["label"], fam["note"]
    siblings = [k for k in fam["members"] if k != e["k"]]
    if not siblings:
        return ""
    items = []
    for k in siblings:
        siblings_names = "、".join(variants.get(k, [])[:2])
        fname = key_file(k)
        items.append(
            f'<li><a href="{fname}">{esc(displays.get(k, siblings_names))}</a>'
            f'<span class="tag">{esc(k)}</span></li>')
    return (f'<h2 data-i18n="fam.title">The same brand in other markets</h2>'
            f'<div class="notice">{esc(note or "")}</div>'
            f'<ul class="sub">{"".join(items)}</ul>')


def _sort_strength(text: str) -> float:
    m = re.match(r"([\d.]+)", text)
    return float(m.group(1)) if m else 0.0


def build_index_page(entries, stats, coverage) -> None:
    """三份落地页：/ 、/es/ 、/zh/。内容相同，语言由脚本按路径/参数决定。"""
    covline = ", ".join(f"{r['country']} {r['n_products']:,}" for r in coverage)
    body = f"""<h1 data-i18n="home.h1">Find out what a medicine really is</h1>
<p class="sub" data-i18n="home.sub">Type a brand name, a generic name, a nickname, or a line from the pack.</p>
<input id="q" data-ph="home.ph" placeholder="Brand name / generic name / nickname / a line from the pack" autocomplete="off">
<div class="row">
  <select id="country"><option value="" data-i18n="home.all">All countries</option>
    <option value="US" data-i18n="home.us">United States</option>
    <option value="GB" data-i18n="home.gb">United Kingdom</option>
    <option value="CN" data-i18n="home.cn">China</option>
    <option value="ES" data-i18n="home.es">Spain</option>
    <option value="MX" data-i18n="home.mx">Mexico</option>
    <option value="AU" data-i18n="home.au">Australia</option>
    <option value="CA" data-i18n="home.ca">Canada</option></select>
  <button data-q="泰诺">泰诺</button>
  <button data-q="两只青蛙">两只青蛙</button>
  <button data-q="Lipitor 20mg">Lipitor 20mg</button>
  <button data-q="Benadryl">Benadryl</button>
  <button data-q="Gaviscon">Gaviscon</button>
</div>
<p class="sub" id="loadhint">首次搜索需要加载索引，约 6 MB（gzip 压缩后，之后浏览器会缓存）。
First search needs to load the index (~6 MB gzipped; cached after the first time) —
start typing, focus the search box, or pick a sample.</p>
<p class="sub" id="meta" style="margin-top:14px"></p>
<div id="out"></div>
<p class="sub report-line" id="report" style="display:none">
  <span data-i18n="report.note">Wrong ingredient, wrong dose, or a drug we do not have? Tell us:</span>
  <a id="reportLink" href="{REPORT_REPO}/issues/new?labels=data-error&amp;template=data-error.yml"
     target="_blank" rel="noopener" data-i18n="report.cta">Report this result</a>
</p>
<div class="notice"><span data-i18n="home.coverage">An empty result does not mean the medicine
does not exist. Coverage:</span> {covline}.</div>
<script src="{{prefix}}assets/app.js?v={BUILD_V}"></script>"""
    for code, _label, path in LANGS:
        prefix = "../" if path else ""
        html = page("Medicine Brand Cross-Reference", body.replace("{prefix}", prefix),
                    prefix=prefix, lang=code, alternates=True)
        target = OUT / (path + "index.html")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")


SOURCE_SHORT = {
    "openfda_ndc": "openFDA",
    "dmd": "dm+d",
    "nhsa": "NHSA",
    "pbs": "PBS",
    "tga_cmi": "TGA CMI",
    "artg_index": "ARTG",
    "artg_enrich": "ARTG",
    "artg_detail": "ARTG",
    "cima": "CIMA",
    "cofepris_mx": "COFEPRIS",
    "hc_dpd": "Health Canada DPD",
    "manual_seed": "manual",
}


def _as_of_cell(rows) -> str:
    """覆盖表的「数据日期」：主源日期 + 其他有日期的源；实时源标 live，年度清单标 —。

    旧的第三列取 product.retrieved_at（我们的抓取时间），会把 2025-04-04 的
    中国快照显示成 2026-10-26，所以改成 source.data_as_of。
    """
    rows = [r for r in rows if (r["n_products"] or 0) >= 100] or list(rows)
    groups: list[list] = []
    for r in rows:
        label = SOURCE_SHORT.get(r["source_id"], r["source_id"])
        if r["data_as_of"]:
            text = str(r["data_as_of"])
            if len(text) > 10 and text[10] in "T ":
                text = text[:10]
        elif (r["data_as_of_note"] or "") == "live":
            text = "live"
        else:
            continue
        for g in groups:
            if g[0] == text:
                g[1].append(label)
                break
        else:
            groups.append([text, [label]])
    if not groups:
        return "—"
    first_text, first_labels = groups[0]
    out = f"{first_text} ({', '.join(dict.fromkeys(first_labels))})"
    for text, labels in groups[1:]:
        out += f" + {text} ({', '.join(dict.fromkeys(labels))})"
    return esc(out)


def build_about(stats, coverage, source_cover=()) -> None:
    by_country: dict[str, list] = {}
    for r in source_cover:
        by_country.setdefault(r["country"], []).append(r)
    cov = "".join(
        f"<tr><td>{esc(r['country'])}</td><td>{r['n_products']:,}</td>"
        f"<td>{_as_of_cell(by_country.get(r['country'], []))}</td></tr>" for r in coverage)
    body = f"""<h1>About 关于本站</h1>
<p class="sub"><b>One job:</b> turn a brand name into the actual substance, and say how sure
we are. 这里只有一件事：把商品名定位到成分，并说明它到底有多可信。</p>

<h2>Three rules 三条底线</h2>
<ol>
<li><b>A brand name is not a primary key. 商品名不是主键。</b>
Every query returns a set of candidates; identity is pinned by country × form × strength ×
active ingredient. 唯一性由「国家 × 剂型 × 规格 × 活性成分」锁定。</li>
<li><b>Collisions are derived, not annotated. 碰撞自动推导。</b>
When one name hangs off different ingredients, the site flags
“same name, different drug” automatically.</li>
<li><b>No dosing advice. 不给用药建议。</b>
Identification and “not interchangeable” warnings only — no dose conversion, no substitution
recommendations.</li>
</ol>

<h2>Nicknames, old names, internet slang 俗称、旧名与网络别名</h2>
<p>“两只青蛙” is not a brand name and is never stored as one: it points to an ingredient,
metformin (二甲双胍). Nicknames are a separate, hand-maintained table — searchable, but kept out
of the brand-name tables on purpose.</p>
<ul>
<li>When a nickname matches, the page says so (<i>internet nickname / older name</i>) and then
lists that ingredient’s brand names. It is never presented as a name printed on a pack.
<br>命中时先标注「网络俗称 / 旧名」，再列该成分的商品名；不把它说成包装上的名字。</li>
<li>Every published entry carries a source. “User-provided” is a lead, not evidence: it is
shown as <i>user-provided (unverified)</i> and is not promoted to <code>documented</code> until an
independent source is attached. <b>Community names stay searchable</b> and are labelled
<i>community name</i>; they are not presented as documented. Review verifies a source; it cannot
replace one. No source, no new entry.
<br>每条都写出处。「用户提供」只算线索，公开页标「用户提供（未证实）」；<b>社区叫法保留检索</b>，
标「社区叫法」，不冒充 documented；找到独立出处后才升级。审核只能核实出处，不能代替出处；
没有来源线索的不新增。</li>
<li>Nicknames never enter collision detection and never get a “same name” page — a nickname is
not an identity, the ingredient is.
<br>不参与同名碰撞推导，也不生成同名页——昵称不是身份，成分才是。</li>
<li>To add one, edit <code>data/seed_nicknames.py</code> and rebuild. It is curated by hand,
not scraped.
<br>要补一条：改 <code>data/seed_nicknames.py</code> 再重建；人工维护，不自动抓。</li>
</ul>
<p class="sub">This layer started as a joke: the <i>guā</i> in 二甲双胍 sounds like a frog’s
<i>guā</i> (呱), so it got called “two frogs”. The point of the site is to connect exactly this
kind of name back to the substance.<br>
这一层最初来自一个笑话：二甲双胍的「胍」和青蛙的「呱」同音，于是被叫成「两只青蛙」。这个站想
做的，就是把这类叫法接回它真正的成分。</p>

<h2>US street names and confused names 美国街头叫法 / 易混淆药名</h2>
<p class="sub">A separate table (<code>drug_term</code>) holds US street names, folk names and
class terms. Unlike <code>nickname</code>, it may point to a class (“downers” = depressants)
or to a controlled substance with no marketed product in this database (“molly” = MDMA), so
<code>substance_id</code> is nullable. <code>alias_all</code> unions both tables for search.
<br>美国街头叫法单独放在 <code>drug_term</code>：允许指向类别，或指向本库没有上市产品的管制物质
（如 MDMA）。检索层只读 <code>alias_all</code> 这一个视图。</p>
<ul class="sub">
<li><b>NIDA “Drugs A to Z”</b>: official “Also called” lists — cannabis, cocaine, fentanyl,
heroin, methamphetamine, prescription opioids, etc. US Government work.
<br>NIDA 官方 Also called 列表，约 250 条。</li>
<li><b>DEA “Slang Terms and Code Words” (2018)</b>: a curated subset for prescription-drug
slang (bars, addy, vikes, dillies, oxy, lean…). Public Domain Mark 1.0.
<br>DEA 2018 报告，只取与处方药/管制物质对应的词，不取度量、武器等条目。</li>
<li><b>MedlinePlus (NLM)</b>: common folk/category terms — water pill, blood thinner,
the pill, morning-after pill, statin… 20 entries.
<br>MedlinePlus 民间叫法，只收类别词，不转载正文。</li>
<li><b>Community / country sources</b>: 34 entries — CN community/consumer pages,
UK <a href="https://www.talktofrank.com/" target="_blank" rel="noopener">Talk to FRANK</a>,
AU <a href="https://adf.org.au/drug-facts/" target="_blank" rel="noopener">ADF</a>,
ES <a href="https://pnsd.sanidad.gob.es/" target="_blank" rel="noopener">PNSD</a>.
Each row carries its own source URL; only the nickname fact is stored.
<br>社区叫法（CN/GB/AU/ES）逐条带 URL，标「社区叫法」，保留检索。</li>
<li><b>FDA Name Differentiation Project</b>: {stats['confusable']} official tall-man pairs.
US Government work. <a href="confused.html">See the list</a>.
<br>FDA 官方 tall-man 药对；ISMP/ECRI 的完整 LASA 清单有版权，未整表复制。</li>
</ul>

<h2>Sources and coverage 数据来源与覆盖</h2>
<table><tr><th>Market 市场</th><th>Products 已收录</th><th>Data as of 数据截止</th></tr>{cov}</table>
<p class="sub"><b>Data as of 数据截止</b> = 数据源自己发布 / 生效 / 快照的日期，不是我们的抓取日期。
<code>live</code> = 实时目录或数据库，源头没有单独的日期；<b>—</b> = 源头只发布年度清单，没有单一日期。
</p>
<p class="sub"><b>US 美国</b>: openFDA NDC Directory (US Government public data;
<code>brand_name</code> + <code>active_ingredients</code>).<br>
<b>UK 英国</b>: NHSBSA dm+d, Release 10.2.0, under the Open Government Licence v3.0 —
attribution: <i>Contains public sector information licensed under the Open Government Licence
v3.0.</i> Appliance/device entries were filtered out.<br>
<b>Spain 西班牙</b>: AEMPS CIMA (Centro de Información online de Medicamentos),
<code>nregistro</code> + <code>vtm</code> + <code>dosis</code> + <code>atcs</code>; Spanish
generic names carry the manufacturer (e.g. “Omeprazol Cinfa”), which is how the pack is
labelled. 西班牙按 VTM 归成分，西语名与英文 INN 共用同一 substance_id。<br>
<b>Mexico 墨西哥</b>: COFEPRIS «Registros Sanitarios de Medicamentos Alopáticos Expedidos»,
26 annual PDFs 2001–2026, plus the <i>prórrogas</i> (renewal) lists that carry 1,040 older
registrations granted before 2001 — 10,878 records in total. Status is derived, not given:
<i>revocados / cancelados</i> → withdrawn; an expiry date in the past → discontinued; no expiry
column at all (the 2001–2010 files) → <b>unknown</b>, we do not pretend either way. The lists
carry <b>no strength column</b>: strengths are back-filled from the ISSSTE procurement catalogue
and the PROFECO price survey (both CC BY 4.0), only where the value is unambiguous — so a blank
strength in Mexico is expected, not a bug.<br>
<b>Australia 澳洲</b>: three layers, because no single Australian source covers both
prescription and OTC. <b>(1) PBS Schedule API v3</b> (Department of Health), schedule 4751
effective 1 October 2026 — 15,073 item × brand rows, 5,452 products after collapsing the same
brand/strength/pack that appears under several restriction codes; the API's copyright notice
permits use and redistribution if the statement is retained: <i>Copyright (c) 2024 Department
of Health, Commonwealth of Australia.</i> <b>(2) TGA CMI repository</b> — 4,730 products for
registered medicines that have a Consumer Medicine Information document (most registered OTC,
e.g. Panadol, Nurofen), with trade name + active ingredients only: the directory carries no
strength or form, so those are blank. <b>(3) curated listed-OTC seeds</b> — Gaviscon is an
AUST L medicine: not in PBS, and listed medicines are not required to have a CMI, so its
five Australian packs were entered by hand from the sponsor's Australian product pages
(ingredients and strength per 10 mL / per tablet, source URL kept on each product).
The full register (TGA ARTG) still has no bulk extract — the eBS public register lists
current medicines 30 per page but its detail pages are PDFs; complete ingredient-level ARTG
data would need an FOI request. Stoma/incontinence appliances (PBS program R1) are filtered out.
<br>澳洲分三层，因为没有单一数据源能同时覆盖处方药和 OTC：PBS 官方 API（补贴处方药）+
TGA 的 CMI 目录（有消费者说明书的注册类药品，如 Panadol / Nurofen，只有商品名和成分、
没有规格）+ 人工核对的 listed OTC 种子（Gaviscon 这类 AUST L 药品不进 PBS、也不要求 CMI）。
ARTG 全量仍然没有批量文件：eBS 的现行药品目录可以按 30 条/页翻，但每条详情只有 PDF，
要做成分级全量只能走 FOI。R1 造口/失禁用品已按 dm+d 滤器械的同一逻辑排除。<br>
<b>Canada 加拿大</b>: Health Canada <b>Drug Product Database (DPD)</b> — one row per
<b>DIN</b> (Drug Identification Number), human products, with brand name, active ingredients
<b>and strength</b>, pharmaceutical form, route, schedule, ATC-4 and status
(Marketed / Approved / Dormant / Cancelled). The regulator's bulk ZIP (
<i>allfiles.zip</i>) is served from canada.ca in a way that blocks programmatic downloads,
so the extract is taken from the same host's public <b>DPD Open API</b>
(<code>/api/drug/&lt;endpoint&gt;</code>, nine endpoints, full JSON, no key). The DPD web query
itself cannot be paged by script — it is a server-side table whose “next page” call needs a
session bound to the search form — so it is not used as a bulk source. DPD terms allow
re-use for non-commercial purposes with source acknowledgement: <i>© His Majesty the King in
Right of Canada, as represented by the Minister of Health.</i>
<br>加拿大用 Health Canada 的 DPD，一行 = 一个 DIN（加拿大的药品识别号）：商品名、成分、
<strong>强度</strong>、剂型、途径、处方类别、ATC-4、状态都在。官方的 allfiles.zip 挂在
canada.ca，程序化下载会被挡（HEAD/GET 都超时），所以改为同一台主机上的公开 DPD Open API
（9 个端点、全量 JSON、无需 key）。DPD 网页查询是服务端分页表，翻页要绑定搜索会话，
脚本翻不动，因此不当批量源用。许可只允许非商业再使用，须注明来源。
Canadian names are mapped to the same <code>substance_id</code>s as the other markets —
<i>ACETYLSALICYLIC ACID</i> → aspirin, <i>ADRENALINE</i> → epinephrine,
<i>GLYCERYL TRINITRATE</i> → nitroglycerin; the salt inside the parentheses becomes the
variant. Homeopathic entries (schedule <i>HOMEOPATHIC</i>, strengths given as CH/DH/X dilutions)
are excluded, as are veterinary, radiopharmaceutical and disinfectant products.
<br>加拿大的老式英文名（acetylsalicylic acid、adrenaline、glyceryl trinitrate）统一映射到
其他市场用的 INN，括号里的盐记成 variant；顺势疗法（强度是 CH/DH/X 稀释度）以及兽药、
放射性药品、消毒剂整条排除。
<b>China 中国</b>: 国家医保局「医保药品分类与代码数据库」, 2025-04-04 snapshot — 252,097
catalogue rows (the same batch is a PDF), of which the chemical-drug rows load as 146,344
products. Chinese generic names are mapped onto the same English
<code>substance_id</code>s the other markets use, through a hand-built 中文→INN table (~1,080
entries) plus an ATC-4 lookup that only fires when that ATC class is unambiguous; the residue
sits on China-only substances that a later pass can map. 中成药 is excluded on purpose.
商品名 exists for only a minority of rows, so most Chinese products are
reachable by generic name rather than by brand.</p>

<h2>Why “same name, different drug” happens 为什么会有同名不同药</h2>
<p class="sub">The same trademark is held by different companies in different markets, and the
formula can differ completely. Verified examples: US <b>Tylenol</b> is single-ingredient
acetaminophen 500 mg, while China <b>泰诺</b> is a four-ingredient cold medicine and the
single-ingredient product is <b>泰诺林</b>; US <b>Benadryl</b> is diphenhydramine, UK
<b>Benadryl</b> is acrivastine; US <b>Gaviscon</b> is an aluminium/magnesium antacid, UK
Gaviscon is an alginate raft.</p>

<h2>Known gaps 已知缺口</h2>
<ul class="sub">
<li>China now carries 146,344 chemical-drug registrations, but ~9% of them resolve only to a
China-only substance (no English INN yet), and China's ATC is stored at level 4 — these
products carry ATC-4, not ATC-5. 中成药 is not loaded.<br>
中国已入库 14.6 万条化学药，但约 9% 只能落到 CN 专属成分（暂无英文 INN），
ATC 只到第 4 级；中成药未收录。</li>
<li>Strength equivalence stops at level D1 (same salt form). Salt-base conversion (D2) and
bioavailability judgement (D3) are not implemented.<br>
剂量只做到同型对应，盐基折算与生物利用度判定未做。</li>
<li>Mexico has no strength in the regulator's bulk lists; only 29% of products could be
back-filled from public catalogues, and no brand-level bulk source exists.
<br>墨西哥官方清单没有浓度列，只有 29% 的产品能从公开目录回填。</li>
<li>The Mexican files only list registrations issued from 2001 onward; the renewal lists recover
1,040 older ones, but anything never renewed is still missing.
<br>墨西哥清单只含 2001 年起新批的注册，续期清单补回 1,040 条老药，其余仍缺。</li>
<li>Canada's DPD carries no pack size or price, and most OTC consumer packs (Tylenol, Advil,
Motrin…) were authorised before the DPD's electronic era: only some of them have a DIN row,
so a Canadian OTC pack can be missing even though it is on every shelf.
<br>加拿大 DPD 没有包装数量/价格；很多 OTC 消费装（Tylenol、Advil、Motrin…）是电子化之前
就批的，DPD 里只有部分品牌有 DIN 行，所以货架上有的 OTC 可能查不到。</li>
<li>ATC codes cover 47.7% of substances (6,345 / 13,288). Part of the coverage comes from
Wikidata <code>P267</code> (CC0, attributed here); the rest is missing because dm+d carries no ATC
field and WHOCC's ATC/DDD index needs a licence.
<br>ATC 覆盖 47.7%（6,345 / 13,288），其中一部分由 Wikidata P267（CC0）补齐并在此署名；
其余缺失：dm+d 没有 ATC 字段，WHOCC 的 ATC/DDD 需要授权。</li>
</ul>
<p class="sub">Stats 统计：{stats['products']:,} products · {stats['substances']:,} substances ·
{stats['keys']:,} name keys · {stats['aliases']:,} aliases
({stats['nickname']:,} hand-curated nicknames) · {stats['confusable']} FDA confused pairs ·
{stats['severe']:,} names flagged “same name, different drug”.</p>"""
    (OUT / "about.html").write_text(page("About", body), encoding="utf-8")


def build_confused(db: sqlite3.Connection) -> int:
    """易混淆药对页：只列有官方出处的配对。"""
    rows = db.execute(
        """SELECT cp.*, sa.inn_en AS a_inn, sa.inn_zh AS a_zh,
                  sb.inn_en AS b_inn, sb.inn_zh AS b_zh
           FROM confusable_pair cp
           LEFT JOIN substance sa ON sa.substance_id = cp.a_substance_id
           LEFT JOIN substance sb ON sb.substance_id = cp.b_substance_id
           ORDER BY cp.norm_a, cp.norm_b"""
    ).fetchall()

    def cell(sid, zh, inn, name):
        label = esc(zh or inn or name)
        en = f' <span class="meta">{esc(inn or name)}</span>' if (inn or name) else ""
        if sid:
            return f'<a href="drug/{esc(sid)}.html">{label}</a>{en}'
        return f'{label}{en}'

    body_rows = []
    for r in rows:
        body_rows.append(
            "<tr>"
            f"<td>{cell(r['a_substance_id'], r['a_zh'], r['a_inn'], r['name_a'])}</td>"
            f"<td>{cell(r['b_substance_id'], r['b_zh'], r['b_inn'], r['name_b'])}</td>"
            f"<td><code>{esc(r['tml_a'])}</code> / <code>{esc(r['tml_b'])}</code></td>"
            "</tr>"
        )
    body = f"""<h1 data-i18n="conf.title">Easily confused drug names</h1>
<p class="sub" data-i18n="conf.intro">Look-alike / sound-alike pairs from the FDA Name
Differentiation Project. This is the official tall-man list, not the full ISMP LASA list.</p>
<div class="notice" data-i18n="conf.note">A pair here means the names can be mistaken for each
other; it does not mean the drugs are interchangeable.</div>
<table><thead><tr>
  <th data-i18n="conf.pair">Pair</th><th></th><th data-i18n="conf.tml">Tall-man spelling</th>
</tr></thead><tbody>{''.join(body_rows)}</tbody></table>
<p class="sub">Source: <a href="https://www.fda.gov/drugs/medication-errors-related-cder-regulated-drug-products/fda-name-differentiation-project"
target="_blank" rel="noopener">FDA Name Differentiation Project</a>
(content current as of 2026-06-12; US Government work).<br>
只收 FDA 官方可再发布的 {len(rows)} 对；ISMP/ECRI 的《List of Confused Drug Names》
有版权，未整表复制。FDA 表里的单名条目（hydromorphone、mitoxantrone）没有配对，未列入。<br>
A pair is a warning about names, not a statement that the drugs are equivalent.</p>"""
    (OUT / "confused.html").write_text(
        page("Easily confused drug names", body), encoding="utf-8")
    return len(rows)


def build_404() -> None:
    """404 页：GitHub Pages 在路径不存在时返回它。

    404 会出现在任意子路径下，相对资源路径会解析错，所以这一页不引用
    assets/、链接全用绝对地址。
    """
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Page not found · Medicine Brand Cross-Reference</title>
<style>
:root{{color-scheme:light dark}}
body{{margin:0;font:16px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif;
  background:#f6f7f5;color:#17201c}}
main{{max-width:640px;margin:12vh auto;padding:0 24px}}
h1{{font-size:22px;margin:0 0 10px}}
p{{color:#3d4a43;margin:8px 0}}
.links{{margin-top:20px;display:flex;gap:18px;flex-wrap:wrap}}
a{{color:#0b6b53}}
</style></head><body><main>
<h1>Page not found · 页面不存在</h1>
<p>这个地址没有对应的页面。可能是链接过期、拼写有误，或页面已改名。</p>
<p>This address has no page. It may be an old link, a typo, or a renamed entry.</p>
<p>回到首页输入一个药名（商品名、通用名、俗称都可以）：</p>
<p class="links"><a href="{SITE_URL}">Search · 检索</a>
<a href="{SITE_URL}about.html">About · 关于</a>
<a href="{SITE_URL}confused.html">Confused names · 易混淆</a>
<a href="{SITE_URL}whats-new.html">What's new · 更新</a></p>
<p style="margin-top:28px;font-size:13px;color:#7a857e">如果是站内链接坏了，欢迎到
<a href="{REPORT_REPO}/issues/new?labels=data-error&amp;template=data-error.yml">GitHub</a> 报一声。</p>
</main></body></html>"""
    (OUT / "404.html").write_text(html, encoding="utf-8")


def build_seo_files() -> None:
    """生成 robots.txt + sitemap.xml + .nojekyll（404.html 另由 build_404 生成）。

    sitemap 扫的是刚写出来的 HTML 文件，所以调用时机必须在所有页面之后。
    中文文件名百分号编码后写进 <loc>。
    """
    from urllib.parse import quote

    lastmod = LATEST_DATE or time.strftime("%Y-%m-%d")
    urls: list[str] = []
    for p in OUT.rglob("*.html"):
        rel = p.relative_to(OUT).as_posix()
        if rel == "404.html":
            continue
        if rel == "index.html":
            urls.append(SITE_URL)
        elif rel.endswith("/index.html"):
            urls.append(SITE_URL + rel[: -len("index.html")])
        else:
            urls.append(SITE_URL + rel)
    urls.sort()

    with (OUT / "sitemap.xml").open("w", encoding="utf-8", newline="\n") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        fh.write('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for url in urls:
            loc = quote(url, safe=":/?&=%#")
            fh.write(f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>\n")
        fh.write("</urlset>\n")

    (OUT / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\nSitemap: " + SITE_URL + "sitemap.xml\n",
        encoding="utf-8")
    # GitHub Pages 默认会跑 Jekyll；.nojekyll 让它直接当静态文件发。
    # 内容留一行说明：发布脚本会拒绝 0 字节文件（防止构建中断发布半成品）。
    (OUT / ".nojekyll").write_text(
        "# GitHub Pages: serve this directory as-is (skip Jekyll)\n", encoding="utf-8")
    print(f"  seo files  : 404 + robots + sitemap ({len(urls)} urls)", flush=True)


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True, exist_ok=True)
    (OUT / "data").mkdir(parents=True, exist_ok=True)
    (OUT / "assets" / "style.css").write_text(CSS, encoding="utf-8")
    i18n_js = (
        "window.I18N=" + json.dumps(I18N, ensure_ascii=False) + ";\n" + r"""
(function(){
  var D = window.I18N, seg = location.pathname.split('/').filter(Boolean);
  function pick(){
    var q = new URLSearchParams(location.search).get('lang');
    if(q && D[q]){ try{localStorage.setItem('lang',q);}catch(e){} return q; }
    var first = seg[0] || '';
    if(D[first]) return first;
    try{ var s = localStorage.getItem('lang'); if(s && D[s]) return s; }catch(e){}
    var n = (navigator.language || 'en').slice(0,2);
    return D[n] ? n : 'en';
  }
  window.LANG = pick();
  window.T = function(k){ return (D[window.LANG] && D[window.LANG][k]) || D.en[k] || k; };
  function apply(){
    document.documentElement.lang = window.LANG;
    document.querySelectorAll('[data-i18n]').forEach(function(el){ el.textContent = window.T(el.dataset.i18n); });
    document.querySelectorAll('[data-ph]').forEach(function(el){ el.placeholder = window.T(el.dataset.ph); });
    document.querySelectorAll('.langs a').forEach(function(a){
      a.classList.toggle('on', a.dataset.lang === window.LANG);
    });
  }
  window.setLang = function(l){ try{localStorage.setItem('lang',l);}catch(e){}
    location.search = '?lang=' + encodeURIComponent(l); };
  if(document.readyState === 'loading'){ document.addEventListener('DOMContentLoaded', apply); }
  else { apply(); }
  window.addEventListener('load', apply);
})();
"""
    )
    (OUT / "assets" / "i18n.js").write_text(i18n_js, encoding="utf-8")
    (OUT / "assets" / "app.js").write_text(
        APP_JS.replace("REPORT_REPO_PLACEHOLDER", REPORT_REPO)
        .replace("data/index.json", f"data/index.json?v={int(time.time())}"),
        encoding="utf-8")

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    coverage = [dict(r) for r in db.execute("SELECT * FROM coverage ORDER BY country")]
    source_cover = [dict(r) for r in db.execute(
        """SELECT p.country, p.source_id,
                  COUNT(DISTINCT p.product_id) AS n_products,
                  s.data_as_of, s.data_as_of_note
           FROM product p LEFT JOIN source s ON s.source_id = p.source_id
           GROUP BY p.country, p.source_id
           ORDER BY p.country, n_products DESC""")]
    stats = {
        "products": db.execute("SELECT COUNT(*) FROM product").fetchone()[0],
        "substances": db.execute("SELECT COUNT(*) FROM substance").fetchone()[0],
        "keys": db.execute("SELECT COUNT(*) FROM name_key").fetchone()[0],
        "nickname": db.execute("SELECT COUNT(*) FROM nickname").fetchone()[0],
        "aliases": db.execute("SELECT COUNT(*) FROM alias_all").fetchone()[0],
        "confusable": db.execute("SELECT COUNT(*) FROM confusable_pair").fetchone()[0],
        "severe": db.execute(
            "SELECT COUNT(*) FROM collision WHERE level='severe'").fetchone()[0],
    }

    print("building index ...", flush=True)
    entries = load_index(db)
    (OUT / "data" / "index.json").write_text(
        json.dumps(entries, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {len(entries)} keys", flush=True)

    print("building nickname index ...", flush=True)
    aliases = load_aliases(db)
    (OUT / "data" / "aliases.json").write_text(
        json.dumps(aliases, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {len(aliases)} nicknames", flush=True)

    print("building confused index ...", flush=True)
    confused = load_confusable(db)
    (OUT / "data" / "confused.json").write_text(
        json.dumps(confused, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {len(confused)} directions", flush=True)

    # ARTG 名称层：只有「品牌 + 申办方 + ARTG ID」，没有成分。
    # 检索时作为「登记存在、成分未收录」的兜底，不参与产品结果。
    print("building ARTG name index ...", flush=True)
    artg = [[r[0], r[1], r[2] or "", r[3]] for r in db.execute(
        "SELECT name_norm, name, sponsor, artg_id FROM artg_entry ORDER BY name")]
    (OUT / "data" / "artg.json").write_text(
        json.dumps(artg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {len(artg)} ARTG names", flush=True)

    print("building drug pages ...", flush=True)
    n_drug = build_drug_pages(db)
    print("collecting name data ...", flush=True)
    data = collect_name_data(db)
    families: dict[str, dict] = {}
    members: dict[str, list[str]] = defaultdict(list)
    for key_id, fam_id, label, note in db.execute(
        "SELECT nf.key_id, bf.family_id, bf.label, bf.note FROM name_family nf"
        " JOIN brand_family bf ON bf.family_id = nf.family_id"
    ):
        families[key_id] = {"id": fam_id, "label": label, "note": note, "members": []}
        members[fam_id].append(key_id)
    for key_id, fam in families.items():
        fam["members"] = members[fam["id"]]
    displays = {e["k"]: e["d"] for e in entries}
    print("building name pages ...", flush=True)
    n_name = build_name_pages(db, entries, data, families, displays)
    build_index_page(entries, stats, coverage)
    n_conf = build_confused(db)
    build_about(stats, coverage, source_cover)
    build_whats_new()
    build_404()
    build_seo_files()

    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"\n== done ==")
    print(f"  drug pages : {n_drug}")
    print(f"  name pages : {n_name}")
    print(f"  confused   : {n_conf} pairs")
    print(f"  index.json : {(OUT / 'data' / 'index.json').stat().st_size / 1e6:.1f} MB")
    print(f"  total size : {size / 1e6:.1f} MB")
    print(f"  open       : {OUT / 'index.html'}")
    db.close()


if __name__ == "__main__":
    main()
