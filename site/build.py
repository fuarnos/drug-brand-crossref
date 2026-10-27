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
    data/index.json     检索索引（兼容回退：?legacy=1 或核心加载失败时用）
    data/idx/core.json  检索索引的列式 + 字典编码核心（P1；客户端解码回 index.json 的结构）
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


def _env_value(key: str, default: str = "") -> str:
    """从环境变量或仓库根 .env 读配置（.env 不入库，供本机构建用）。"""
    val = os.environ.get(key, "").strip()
    if val:
        return val
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return default


# 访问统计：GoatCounter（cookieless，后台看 PV/UV/来源/国家/浏览器/屏幕尺寸）。
# code 放 .env 的 GOATCOUNTER_CODE=...；不配置就不注入脚本，站点完全不受影响。
GOATCOUNTER_CODE = re.sub(r"[^A-Za-z0-9_-]", "", _env_value("GOATCOUNTER_CODE"))
GC_TAG = (
    f'\n<script data-goatcounter="https://{GOATCOUNTER_CODE}.goatcounter.com/count"'
    f' async src="https://gc.zgo.at/count.js"></script>'
) if GOATCOUNTER_CODE else ""


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
        "home.hint_idle": ("First search needs to load the index (~6 MB gzipped; cached after "
                           "the first time) — start typing, focus the search box, or pick a "
                           "sample."),
        "home.hint_loading": "Loading the index… (~6 MB the first time)",
        "error.index_failed": "The index failed to load.",
        "error.local_file": ("If you opened this page directly, the browser blocks local file "
                             "reads — run python -m http.server and visit "
                             "http://localhost:8000/."),
        "error.retry": "Retry",
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
        "drug.status.active": "active", "drug.status.discontinued": "discontinued",
        "drug.status.withdrawn": "withdrawn", "drug.status.unknown": "unknown",
        "drug.status_note.discontinued": "expired",
        "drug.status_note.withdrawn": "market authorisation withdrawn",
        "drug.status_note.unknown": "validity unknown",
        "drug.no_brand": "(no brand name)", "drug.also_called": "Also called:",
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
        "nick.tag": "nickname",
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
        "report.issue_title": "Data error: ",
        "report.field_query": "Query", "report.field_page": "Page",
        "report.field_expected": "Expected result", "report.field_actual": "Actual result",
        "report.field_pack": "Pack or lot",
        "conf.title": "Easily confused drug names",
        "conf.intro": ("Look-alike / sound-alike pairs from the FDA Name Differentiation Project. "
                       "This is the official tall-man list, not the full ISMP LASA list."),
        "conf.note": ("A pair here means the names can be mistaken for each other; it does not "
                      "mean the drugs are interchangeable. FDA recommends tall-man lettering."),
        "conf.pair": "Pair", "conf.tml": "Tall-man spelling",
        "conf.search_hit": "This name is easily confused with",
        "home.country_label": "See what this medicine is called in:",
        "home.country_label_sel": "See what this medicine is called in {country}:",
        "country.missing": "This market has no product listed under this name.",
        "country.missing_note": ("The name matched an ingredient, not a product in this "
                                 "country. Switch country or open the ingredient page."),
        "country.open_card": "Ingredient page",
        "country.change": "Change country",
        "parse.label": "Parsed query",
        "parse.name": "Name", "parse.dose": "Dose", "parse.form": "Form",
        "parse.match": "Match",
        "parse.match.exact": "exact", "parse.match.compact": "joined",
        "parse.match.prefix": "prefix", "parse.match.contains": "substring",
        "parse.match.fuzzy": "fuzzy", "parse.match.nickname": "alias",
    "parse.match.pinyin": "pinyin",
        "parse.match.country": "country view", "parse.match.none": "no match",
        "ac.suggestions": "Suggestions",
        "res.brands_noun": "brands",
        "res.show_brands": "Show all brands",
        "res.fold": "Show fewer",
        "res.load_more": "Load more",
        "res.loaded_all": "All results shown",
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
        "home.hint_idle": ("La primera búsqueda necesita cargar el índice (~6 MB comprimido; "
                           "queda en caché) — empieza a escribir, enfoca el buscador o elige "
                           "un ejemplo."),
        "home.hint_loading": "Cargando el índice… (~6 MB la primera vez)",
        "error.index_failed": "No se pudo cargar el índice.",
        "error.local_file": ("Si abriste esta página directamente, el navegador bloquea la "
                             "lectura de archivos locales — ejecuta python -m http.server y "
                             "visita http://localhost:8000/."),
        "error.retry": "Reintentar",
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
        "drug.status.active": "activo", "drug.status.discontinued": "descatalogado",
        "drug.status.withdrawn": "retirado", "drug.status.unknown": "desconocido",
        "drug.status_note.discontinued": "caducado",
        "drug.status_note.withdrawn": "autorización retirada",
        "drug.status_note.unknown": "validez desconocida",
        "drug.no_brand": "(sin nombre comercial)", "drug.also_called": "También llamado:",
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
        "nick.tag": "apodo",
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
        "report.issue_title": "Error de datos: ",
        "report.field_query": "Consulta", "report.field_page": "Página",
        "report.field_expected": "Resultado esperado", "report.field_actual": "Resultado real",
        "report.field_pack": "Envase o lote",
        "conf.title": "Nombres de medicamentos fáciles de confundir",
        "conf.intro": ("Pares de nombres parecidos o que suenan igual, del proyecto de "
                       "diferenciación de nombres de la FDA. Es la lista oficial tall-man, "
                       "no la lista LASA completa de ISMP."),
        "conf.note": ("Un par significa que los nombres pueden confundirse; no significa que "
                      "los medicamentos sean intercambiables. La FDA recomienda tall-man lettering."),
        "conf.pair": "Par", "conf.tml": "Grafía tall-man",
        "conf.search_hit": "Este nombre se confunde fácilmente con",
        "home.country_label": "Mira cómo se llama este medicamento en:",
        "home.country_label_sel": "Mira cómo se llama este medicamento en {country}:",
        "country.missing": "Este mercado no tiene ningún producto registrado con este nombre.",
        "country.missing_note": ("El nombre coincide con un principio activo, no con un producto "
                                 "de este país. Cambia de país o abre la ficha del principio activo."),
        "country.open_card": "Ficha del principio",
        "country.change": "Cambiar país",
        "parse.label": "Consulta interpretada",
        "parse.name": "Nombre", "parse.dose": "Dosis", "parse.form": "Forma",
        "parse.match": "Coincidencia",
        "parse.match.exact": "exacta", "parse.match.compact": "unida",
        "parse.match.prefix": "prefijo", "parse.match.contains": "subcadena",
        "parse.match.fuzzy": "aproximada", "parse.match.nickname": "alias",
    "parse.match.pinyin": "pinyin",
        "parse.match.country": "vista por país", "parse.match.none": "sin coincidencias",
        "ac.suggestions": "Sugerencias",
        "res.brands_noun": "marcas",
        "res.show_brands": "Mostrar todas las marcas",
        "res.fold": "Mostrar menos",
        "res.load_more": "Cargar más",
        "res.loaded_all": "Todos los resultados mostrados",
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
        "home.hint_idle": ("首次搜索需要加载索引，约 6 MB（gzip 压缩后，之后浏览器会缓存）"
                           "——输入、聚焦搜索框或点一个示例即可开始。"),
        "home.hint_loading": "正在加载索引…（首次约 6 MB）",
        "error.index_failed": "索引没加载成功。",
        "error.local_file": ("如果是本地双击打开的页面，浏览器会拦截本地文件读取——请用 "
                             "python -m http.server 起服务后访问 http://localhost:8000/。"),
        "error.retry": "重试",
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
        "drug.status.active": "在售", "drug.status.discontinued": "已停售",
        "drug.status.withdrawn": "已撤市", "drug.status.unknown": "状态未知",
        "drug.status_note.discontinued": "有效期已过",
        "drug.status_note.withdrawn": "批文已撤销",
        "drug.status_note.unknown": "有效期待确认",
        "drug.no_brand": "（无商品名）", "drug.also_called": "也叫：",
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
        "nick.tag": "俗称",
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
        "report.issue_title": "数据错误：",
        "report.field_query": "查询词", "report.field_page": "页面",
        "report.field_expected": "期望结果", "report.field_actual": "实际结果",
        "report.field_pack": "包装或批号",
        "conf.title": "容易混淆的药物",
        "conf.intro": ("来自 FDA Name Differentiation Project 的形似/音似药对。"
                       "这是官方 tall-man 名单，不是 ISMP 全量 LASA 清单。"),
        "conf.note": ("列在这里只说明两个名字可能被看错/听错，不表示两种药可以互换。"
                      "FDA 建议这一对使用 tall-man 大小写。"),
        "conf.pair": "药对", "conf.tml": "建议 tall-man 写法",
        "conf.search_hit": "这个药名容易与以下名字混淆",
        "home.country_label": "看这个药在哪个国家叫什么：",
        "home.country_label_sel": "看这个药在{country}叫什么：",
        "country.missing": "该市场没有以这个名字上架的产品。",
        "country.missing_note": "这个名字命中的是成分卡，不是该国上架的产品。可以换一个国家，或直接看成分卡。",
        "country.open_card": "看成分卡",
        "country.change": "换国家",
        "parse.label": "检索解析",
        "parse.name": "名称", "parse.dose": "剂量", "parse.form": "剂型",
        "parse.match": "匹配方式",
        "parse.match.exact": "精确", "parse.match.compact": "连写",
        "parse.match.prefix": "前缀", "parse.match.contains": "包含",
        "parse.match.fuzzy": "模糊", "parse.match.nickname": "别名",
    "parse.match.pinyin": "拼音",
        "parse.match.country": "国家视图", "parse.match.none": "无匹配",
        "ac.suggestions": "搜索建议",
        "res.brands_noun": "个品牌",
        "res.show_brands": "展开全部品牌",
        "res.fold": "折叠",
        "res.load_more": "加载更多",
        "res.loaded_all": "已显示全部结果",
    },
}

LANGS = [("en", "EN", ""), ("es", "ES", "es/"), ("zh", "中文", "zh/")]

# ── i18n P1：About / What's new / Confused / 404 的三语正文 ────────────────
# 用法：About 正文按块走 `data-i18n-html`（i18n.js 用 innerHTML 替换，块内可含链接/表格）；
# 动态数字用 @@PLACEHOLDER@@（main() 里替换成当前库的统计值，不写死数字）。
# 许可段落直接用 reports/license-audit.md §4 的三语并排版（同一段内 EN/中文/ES 并列，
# 是「许可原文三语并列」，不是漏翻）。
DOCS_LICENCE_URL = ("https://github.com/fuarnos/drug-brand-crossref/blob/main/"
                    "docs/%E8%AE%B8%E5%8F%AF%E6%B8%85%E5%8D%95.md")

ABOUT_I18N = {
    "en": {
        "about.title": "About",
        "about.lead": (
            '<p class="sub"><b>One job:</b> turn a brand name into the actual substance, and say '
            'how sure we are. The site is public, ad-free and non-commercial. Every answer is a '
            'candidate set, never a prescription.</p>'),
        "about.rules": (
            '<h2>Three rules</h2><ol>'
            '<li><b>A brand name is not a primary key.</b> Every query returns a set of '
            'candidates; identity is pinned by country × form × strength × active ingredient.</li>'
            '<li><b>Collisions are derived, not annotated.</b> When one name hangs off different '
            'ingredients, the site flags “same name, different drug” automatically.</li>'
            '<li><b>No dosing advice.</b> Identification and “not interchangeable” warnings only — '
            'no dose conversion, no substitution recommendations.</li></ol>'),
        "about.nick": (
            '<h2>Nicknames and old names</h2>'
            '<p>“两只青蛙” is not a brand name and is never stored as one: it points to an '
            'ingredient, metformin. Nicknames are a separate, hand-maintained table — searchable, '
            'but deliberately kept out of the brand-name tables. When one matches, the page labels '
            'it (<i>internet nickname / older name</i>) and then lists that ingredient’s brands; '
            'it is never presented as a name printed on a pack. Every entry carries a source; '
            '“user-provided” is shown as <i>unverified</i> and is not promoted to '
            '<code>documented</code> until an independent source is attached. No source, no new '
            'entry.</p>'
            '<ul class="sub">'
            '<li>@@NICKNAMES@@ nicknames are curated by hand in <code>data/seed_nicknames.py</code> '
            'and rebuilt — not scraped.</li>'
            '<li>Nicknames never enter collision detection and never get a “same name” page: a '
            'nickname is not an identity, the ingredient is.</li></ul>'),
        "about.terms": (
            '<h2>Folk names and class terms</h2>'
            '<p>A separate table (<code>drug_term</code>, @@DRUGTERMS@@ entries) holds folk names '
            'and category terms for <b>legal medicines only</b>: water pill, blood thinner, '
            '睡前药 (sleeping pill), the pill, morning-after pill, statin. Unlike '
            '<code>nickname</code>, it may point to a class rather than one ingredient, so '
            '<code>substance_id</code> is nullable; <code>alias_all</code> unions both tables for '
            'search. <b>Drugs of abuse and recreational slang are explicitly out of scope</b> '
            '(street / recreational drug slang); such entries were removed from the database and are not '
            're-added.</p>'
            '<ul class="sub">'
            '<li><b>NIDA / DEA lists</b> are no longer used for recreational slang; only '
            'prescription-drug category terms that are legal medicines are kept, each with a '
            'source URL.</li>'
            '<li><b>MedlinePlus (NLM)</b> contributes common folk/category terms (US Government '
            'work); community sources (CN/GB/AU/ES) are labelled <i>community name</i> and stay '
            'searchable. FDA tall-man pairs: @@CONFUSABLE@@ official pairs. '
            '<a href="confused.html">See the list</a>.</li></ul>'),
        "about.sources": (
            '<h2>Sources and coverage</h2>'
            '<div class="tablewrap"><table><tr><th>Market</th><th>Products</th>'
            '<th>Data as of</th></tr>@@COV@@</table></div>'
            '<p class="sub"><b>Data as of</b> = the date the source itself published / took effect '
            '/ snapshotted, not our crawl date. <code>live</code> = a live directory with no '
            'single source date; <b>—</b> = annual lists only.</p>'
            '<p class="sub"><b>US</b>: openFDA NDC Directory (US Government public data). '
            '<b>UK</b>: NHSBSA dm+d, Open Government Licence v3.0 — '
            '<i>Contains public sector information licensed under the Open Government Licence '
            'v3.0.</i> <b>Spain</b>: AEMPS CIMA — re-use allowed with express attribution and the '
            'date of last update; not an open licence (see licences below). <b>Mexico</b>: '
            'COFEPRIS registration lists (no stated open licence; factual fields with links) plus '
            'strength back-fill from datos.gob.mx procurement/price datasets, CC BY 4.0. '
            '<b>Australia</b>: PBS Schedule API (copyright notice retained) + TGA CMI directory '
            '+ curated listed-OTC seeds — factual fields only, no full CMI/ARTG text. '
            '<b>Canada</b>: Health Canada DPD — non-commercial re-use with source acknowledgement. '
            '<b>China</b>: 国家医保局 医保药品分类与代码数据库 (2025-04-04 snapshot); no open '
            'redistribution licence was found, so only factual fields with links are stored.</p>'),
        "about.samename": (
            '<h2>Why “same name, different drug” happens</h2>'
            '<p class="sub">The same trademark is held by different companies in different '
            'markets, and the formula can differ completely. Verified examples: US <b>Tylenol</b> '
            'is single-ingredient acetaminophen 500 mg, while China <b>泰诺</b> is a four-ingredient '
            'cold medicine and the single-ingredient product is <b>泰诺林</b>; US <b>Benadryl</b> '
            'is diphenhydramine, UK <b>Benadryl</b> is acrivastine; US <b>Gaviscon</b> is an '
            'aluminium/magnesium antacid, UK Gaviscon is an alginate raft.</p>'),
        "about.gaps": (
            '<h2>Known gaps</h2><ul class="sub">'
            '<li>China has 146,344 chemical-drug registrations, but ~9% resolve only to a '
            'China-only substance (no English INN yet), and China’s ATC is stored at level 4. '
            '中成药 is not loaded.</li>'
            '<li>Strength equivalence stops at level D1 (same salt form); salt–base conversion '
            '(D2) and bioavailability judgement (D3) are not implemented.</li>'
            '<li>Mexico has no strength column in the regulator’s lists; only 29% of products '
            'could be back-filled from public catalogues.</li>'
            '<li>Canada’s DPD has no pack size or price, and many OTC consumer packs were '
            'authorised before the DPD’s electronic era, so a shelf product can be missing.</li>'
            '<li><b>ATC coverage — two denominators:</b> @@ATC_ALL_PCT@@% of all substances '
            '(@@ATC_ALL@@ / @@ATC_ALL_N@@) and @@ATC_DRUG_PCT@@% of drug entities (inn_drug, '
            '@@ATC_DRUG@@ / @@ATC_DRUG_N@@). The gap is mostly non-drug entities (homeopathic, '
            'herbal, food, material), not missing data. ATC data comes from Wikidata P267 (CC0) '
            'and ChEMBL (CC BY-SA 4.0); WHOCC’s ATC/DDD index needs a licence and is not used.</li>'
            '</ul>'),
        "about.analytics": (
            '<h2>Analytics</h2><p class="sub">This site uses '
            '<a href="https://www.goatcounter.com/" target="_blank" rel="noopener">GoatCounter</a> '
            'for anonymous, cookie-free analytics. No personal data is stored and it is not used '
            'for advertising. We only see page views, referring sites, country/region, browser and '
            'screen size, plus on-site search terms and result clicks, to improve search quality. '
            'See the <a href="https://www.goatcounter.com/privacy" target="_blank" '
            'rel="noopener">GoatCounter privacy policy</a>.</p>'),
        "about.stats": (
            '<p class="sub">Stats: @@PRODUCTS@@ products · @@SUBSTANCES@@ substances · '
            '@@KEYS@@ name keys · @@ALIASES@@ aliases (@@NICKNAMES@@ hand-curated nicknames, '
            '@@DRUGTERMS@@ folk/class terms) · @@CONFUSABLE@@ FDA confused pairs · @@SEVERE@@ names '
            'flagged “same name, different drug”.</p>'),
    },
    "es": {
        "about.title": "Acerca de",
        "about.lead": (
            '<p class="sub"><b>Un solo trabajo:</b> convertir un nombre comercial en el principio '
            'activo real y decir con qué seguridad lo sabemos. El sitio es público, sin anuncios y '
            'sin ánimo de lucro. Toda respuesta es un conjunto de candidatos, nunca una receta.</p>'),
        "about.rules": (
            '<h2>Tres reglas</h2><ol>'
            '<li><b>Un nombre comercial no es clave primaria.</b> Cada consulta devuelve un '
            'conjunto de candidatos; la identidad se fija por país × forma × concentración × '
            'principio activo.</li>'
            '<li><b>Las colisiones se derivan, no se anotan.</b> Cuando un nombre corresponde a '
            'principios activos distintos, el sitio marca automáticamente «mismo nombre, otro '
            'medicamento».</li>'
            '<li><b>Sin consejo de dosificación.</b> Solo identificación y avisos de «no '
            'intercambiable»: sin conversión de dosis ni recomendaciones de sustitución.</li></ol>'),
        "about.nick": (
            '<h2>Apodos y nombres antiguos</h2>'
            '<p>«两只青蛙» no es un nombre comercial y nunca se guarda como tal: apunta a un '
            'principio activo, la metformina. Los apodos están en una tabla aparte mantenida a '
            'mano: se pueden buscar, pero se mantienen fuera de las tablas de nombres comerciales. '
            'Cuando uno coincide, la página lo etiqueta (<i>apodo de internet / nombre antiguo</i>) '
            'y enumera las marcas de ese principio; nunca se presenta como un nombre impreso en el '
            'envase. Cada entrada lleva fuente; «aportado por el usuario» se muestra como '
            '<i>sin verificar</i> y no pasa a <code>documented</code> hasta adjuntar una fuente '
            'independiente. Sin fuente no hay entrada nueva.</p>'
            '<ul class="sub">'
            '<li>@@NICKNAMES@@ apodos se mantienen a mano en '
            '<code>data/seed_nicknames.py</code> y se reconstruyen; no se rastrean.</li>'
            '<li>Los apodos no entran en la detección de colisiones ni generan página de «mismo '
            'nombre»: un apodo no es una identidad, el principio activo sí.</li></ul>'),
        "about.terms": (
            '<h2>Nombres populares y términos de clase</h2>'
            '<p>Una tabla aparte (<code>drug_term</code>, @@DRUGTERMS@@ entradas) recoge nombres '
            'populares y términos de categoría de <b>medicamentos legales únicamente</b>: water '
            'pill, blood thinner, 睡前药 (pastilla para dormir), «la píldora», «la píldora del día '
            'después», estatina. A diferencia de <code>nickname</code>, puede apuntar a una clase '
            'y no a un principio, así que <code>substance_id</code> puede ser nulo; '
            '<code>alias_all</code> une ambas tablas para la búsqueda. <b>Las drogas de abuso y la '
            'jerga recreativa quedan explícitamente fuera</b> (jerga de la calle / recreativa); esas '
            'entradas se eliminaron de la base y no se vuelven a añadir.</p>'
            '<ul class="sub">'
            '<li>Las listas de <b>NIDA / DEA</b> ya no se usan para jerga recreativa; solo se '
            'conservan términos de categoría de medicamentos legales, cada uno con su URL de '
            'fuente.</li>'
            '<li><b>MedlinePlus (NLM)</b> aporta términos populares/de categoría (obra del '
            'Gobierno de EE. UU.); las fuentes comunitarias (CN/GB/AU/ES) se etiquetan '
            '<i>nombre de la comunidad</i> y siguen siendo buscables. Pares tall-man de la FDA: '
            '@@CONFUSABLE@@ pares oficiales. <a href="confused.html">Ver la lista</a>.</li></ul>'),
        "about.sources": (
            '<h2>Fuentes y cobertura</h2>'
            '<div class="tablewrap"><table><tr><th>Mercado</th><th>Productos</th>'
            '<th>Datos hasta</th></tr>@@COV@@</table></div>'
            '<p class="sub"><b>Datos hasta</b> = la fecha en que la propia fuente publicó / entró '
            'en vigor / tomó la instantánea, no la fecha de nuestro rastreo. <code>live</code> = '
            'directorio en vivo sin fecha única; <b>—</b> = solo listas anuales.</p>'
            '<p class="sub"><b>EE. UU.</b>: openFDA NDC Directory (datos públicos del Gobierno de '
            'EE. UU.). <b>Reino Unido</b>: NHSBSA dm+d, Open Government Licence v3.0 — '
            '<i>Contains public sector information licensed under the Open Government Licence '
            'v3.0.</i> <b>España</b>: AEMPS CIMA — reutilización permitida citando expresamente '
            'la fuente y la fecha de última actualización; no es licencia abierta (ver licencias). '
            '<b>México</b>: listas de registro sanitario de COFEPRIS (sin licencia abierta '
            'declarada; solo campos fácticos con enlaces) y concentraciones completadas con '
            'conjuntos de datos de datos.gob.mx, CC BY 4.0. <b>Australia</b>: API PBS Schedule '
            '(aviso de copyright conservado) + directorio TGA CMI + semillas OTC verificadas a '
            'mano; solo campos fácticos, sin texto completo de CMI/ARTG. <b>Canadá</b>: Health '
            'Canada DPD — reutilización no comercial con mención de la fuente. <b>China</b>: base '
            'de datos de clasificación y códigos de medicamentos del NHSA (instantánea '
            '2025-04-04); no se encontró licencia abierta de redistribución, así que solo se '
            'guardan campos fácticos con enlaces.</p>'),
        "about.samename": (
            '<h2>Por qué ocurre «mismo nombre, otro medicamento»</h2>'
            '<p class="sub">La misma marca pertenece a empresas distintas en cada mercado y la '
            'fórmula puede ser totalmente diferente. Ejemplos verificados: <b>Tylenol</b> en EE. UU. '
            'es paracetamol de un solo principio 500 mg, mientras que <b>泰诺</b> en China es un '
            'antigripal de cuatro principios y el producto de un solo principio es <b>泰诺林</b>; '
            '<b>Benadryl</b> en EE. UU. es difenhidramina y en el Reino Unido es acrivastina; '
            '<b>Gaviscon</b> en EE. UU. es un antiácido de aluminio/magnesio y en el Reino Unido '
            'es una barrera de alginato.</p>'),
        "about.gaps": (
            '<h2>Lagunas conocidas</h2><ul class="sub">'
            '<li>China tiene 146.344 registros de medicamentos químicos, pero ~9% solo resuelven a '
            'una sustancia exclusiva de China (sin INN en inglés); su ATC se guarda en nivel 4. '
            'No se cargan los 中成药.</li>'
            '<li>La equivalencia de concentración llega al nivel D1 (misma forma salina); la '
            'conversión sal–base (D2) y la biodisponibilidad (D3) no están implementadas.</li>'
            '<li>México no tiene columna de concentración en las listas del regulador; solo el 29% '
            'de los productos pudo completarse desde catálogos públicos.</li>'
            '<li>El DPD de Canadá no tiene tamaño de envase ni precio, y muchos envases OTC se '
            'autorizaron antes de la era electrónica del DPD, así que un producto de estantería '
            'puede faltar.</li>'
            '<li><b>Cobertura ATC — dos denominadores:</b> @@ATC_ALL_PCT@@% de todas las '
            'sustancias (@@ATC_ALL@@ / @@ATC_ALL_N@@) y @@ATC_DRUG_PCT@@% de las entidades '
            'farmacéuticas (inn_drug, @@ATC_DRUG@@ / @@ATC_DRUG_N@@). La diferencia son sobre '
            'todo entidades no farmacéuticas (homeopáticas, herbales, alimentos, materiales), no '
            'datos ausentes. Los ATC vienen de Wikidata P267 (CC0) y ChEMBL (CC BY-SA 4.0); el '
            'índice ATC/DDD de WHOCC requiere licencia y no se usa.</li></ul>'),
        "about.analytics": (
            '<h2>Estadísticas de visita</h2><p class="sub">Este sitio usa '
            '<a href="https://www.goatcounter.com/" target="_blank" rel="noopener">GoatCounter</a> '
            'para estadísticas anónimas sin cookies: no guarda datos personales y no se usa para '
            'publicidad. Solo se registran visitas, sitios de referencia, país/región, navegador y '
            'tamaño de pantalla, además de las búsquedas y clics en resultados, para mejorar la '
            'búsqueda. Ver la <a href="https://www.goatcounter.com/privacy" target="_blank" '
            'rel="noopener">política de privacidad de GoatCounter</a>.</p>'),
        "about.stats": (
            '<p class="sub">Cifras: @@PRODUCTS@@ productos · @@SUBSTANCES@@ sustancias · '
            '@@KEYS@@ claves de nombre · @@ALIASES@@ alias (@@NICKNAMES@@ apodos mantenidos a mano, '
            '@@DRUGTERMS@@ términos populares/de clase) · @@CONFUSABLE@@ pares confundibles de la '
            'FDA · @@SEVERE@@ nombres marcados «mismo nombre, otro medicamento».</p>'),
    },
    "zh": {
        "about.title": "关于本站",
        "about.lead": (
            '<p class="sub"><b>这里只有一件事：</b>把商品名定位到真正的成分，并说明它到底有多'
            '可信。本站公开、无广告、非商业；所有答案都是候选集，不是处方。</p>'),
        "about.rules": (
            '<h2>三条底线</h2><ol>'
            '<li><b>商品名不是主键。</b>每次查询返回候选集，唯一性由「国家 × 剂型 × 规格 × '
            '活性成分」锁定。</li>'
            '<li><b>碰撞自动推导，不手工标注。</b>一个名字挂到不同成分时，站点自动标出'
            '「同名不同药」。</li>'
            '<li><b>不给用药建议。</b>只做身份对应与「不可互换」提示——不做剂量换算，'
            '不给替代建议。</li></ol>'),
        "about.nick": (
            '<h2>俗称与旧名</h2>'
            '<p>「两只青蛙」不是商品名，也永远不当作商品名存储：它指向成分二甲双胍。'
            '俗称是单独的人工维护表，可检索，但刻意不进入商品名表。命中时先标注'
            '「网络俗称 / 旧名」，再列该成分的商品名，绝不把它说成包装上的名字。每条都写出处；'
            '「用户提供」只算线索，公开页标「未证实」，找到独立出处后才升级为 '
            '<code>documented</code>。没有来源就不新增。</p>'
            '<ul class="sub"><li>@@NICKNAMES@@ 条俗称在 <code>data/seed_nicknames.py</code> '
            '里人工维护并重建，不自动抓取。</li>'
            '<li>俗称不参与同名碰撞推导，也不生成同名页——昵称不是身份，成分才是。</li></ul>'),
        "about.terms": (
            '<h2>民间叫法与类别词</h2>'
            '<p>另有一张表 <code>drug_term</code>（@@DRUGTERMS@@ 条）收录<b>合法药品</b>的民间'
            '叫法与类别词：water pill（利尿剂）、blood thinner（抗凝药）、睡前药、the pill、'
            'morning-after pill、statin 等。与 <code>nickname</code> 不同，它可以指向类别而不是'
            '单一成分，因此 <code>substance_id</code> 可空；检索层读 <code>alias_all</code> '
            '统一视图。<b>毒品与娱乐性用药黑话明确不在收录范围</b>（街头/娱乐性用药黑话），'
            '此类条目已从库中移除，不再新增。</p>'
            '<ul class="sub"><li><b>NIDA / DEA 清单</b>不再用于娱乐性黑话，只保留合法药品的'
            '处方药类别词，并逐条带出处 URL。</li>'
            '<li><b>MedlinePlus（NLM）</b>提供常见民间/类别词（美国政府作品）；社区来源'
            '（CN/GB/AU/ES）标「社区叫法」并保留检索。FDA 官方 tall-man 药对：'
            '@@CONFUSABLE@@ 对，<a href="confused.html">见列表</a>。</li></ul>'),
        "about.sources": (
            '<h2>数据来源与覆盖</h2>'
            '<div class="tablewrap"><table><tr><th>市场</th><th>已收录产品</th>'
            '<th>数据截止</th></tr>@@COV@@</table></div>'
            '<p class="sub"><b>数据截止</b> = 数据源自己发布 / 生效 / 快照的日期，不是我们的抓取'
            '日期。<code>live</code> = 实时目录，源头没有单独日期；<b>—</b> = 只有年度清单。</p>'
            '<p class="sub"><b>美国</b>：openFDA NDC Directory（美国政府公开数据）。'
            '<b>英国</b>：NHSBSA dm+d，Open Government Licence v3.0——'
            '<i>Contains public sector information licensed under the Open Government Licence '
            'v3.0.</i> <b>西班牙</b>：AEMPS CIMA——引用须注明来源与文件最后更新日期，非开放许可'
            '（见下方许可段）。<b>墨西哥</b>：COFEPRIS 注册清单（未标注开放许可，只存事实字段并'
            '链回原文）；规格回填来自 datos.gob.mx 的采购/价格数据集，CC BY 4.0。'
            '<b>澳洲</b>：PBS Schedule API（保留版权声明）+ TGA CMI 目录 + 人工核对的 listed '
            'OTC 种子，只存事实字段，不转载 CMI/ARTG 全文。<b>加拿大</b>：Health Canada DPD，'
            '允许非商业再使用并须注明来源。<b>中国</b>：国家医保局「医保药品分类与代码数据库」'
            '（2025-04-04 快照）；未找到开放的再发布许可，只存事实字段并链回原文。</p>'),
        "about.samename": (
            '<h2>为什么会有「同名不同药」</h2>'
            '<p class="sub">同一个商标在不同市场属于不同公司，配方可能完全不同。已验证的例子：'
            '美国 <b>Tylenol</b> 是单一成分对乙酰氨基酚 500 mg，中国 <b>泰诺</b> 是四成分感冒药，'
            '单一成分产品叫 <b>泰诺林</b>；美国 <b>Benadryl</b> 是苯海拉明，英国 <b>Benadryl</b> '
            '是阿伐斯汀；美国 <b>Gaviscon</b> 是铝/镁抗酸剂，英国 Gaviscon 是海藻酸盐筏剂。</p>'),
        "about.gaps": (
            '<h2>已知缺口</h2><ul class="sub">'
            '<li>中国已入库 14.6 万条化学药注册，但约 9% 只能落到 CN 专属成分（暂无英文 INN），'
            'ATC 只到第 4 级；中成药未收录。</li>'
            '<li>剂量对应只做到同型对应（D1）；盐基折算（D2）与生物利用度判定（D3）未做。</li>'
            '<li>墨西哥官方清单没有浓度列，只有 29% 的产品能从公开目录回填。</li>'
            '<li>加拿大 DPD 没有包装数量/价格，很多 OTC 消费装在 DPD 电子化之前就获批，'
            '货架上有的产品可能查不到。</li>'
            '<li><b>ATC 覆盖——两个分母：</b>全部 substance 为 @@ATC_ALL_PCT@@%'
            '（@@ATC_ALL@@ / @@ATC_ALL_N@@），药物实体（inn_drug）为 @@ATC_DRUG_PCT@@%'
            '（@@ATC_DRUG@@ / @@ATC_DRUG_N@@）。缺口主要是非药物实体（顺势疗法、草药、食品、'
            '材料），不是没抓到数据。ATC 来自 Wikidata P267（CC0）与 ChEMBL（CC BY-SA 4.0）；'
            'WHOCC 的 ATC/DDD 索引需要授权，未使用。</li></ul>'),
        "about.analytics": (
            '<h2>访问统计</h2><p class="sub">本站使用 '
            '<a href="https://www.goatcounter.com/" target="_blank" rel="noopener">GoatCounter</a> '
            '做匿名访问统计：不使用 cookie、不记录个人数据、不用于广告；只统计页面浏览、来源'
            '网站、国家/地区、浏览器与屏幕尺寸，以及站内搜索词和结果点击，用于改进检索质量。'
            '详见 <a href="https://www.goatcounter.com/privacy" target="_blank" '
            'rel="noopener">GoatCounter 隐私政策</a>。</p>'),
        "about.stats": (
            '<p class="sub">统计：@@PRODUCTS@@ 个产品 · @@SUBSTANCES@@ 个成分 · '
            '@@KEYS@@ 个检索名 · @@ALIASES@@ 条别名（其中 @@NICKNAMES@@ 条人工俗称、'
            '@@DRUGTERMS@@ 条民间/类别词）· @@CONFUSABLE@@ 对 FDA 易混淆药对 · '
            '@@SEVERE@@ 个名字被标「同名不同药」。</p>'),
    },
}

# What's new / Confused / 404 的三语文案（同样走 data-i18n / data-i18n-html）。
PAGE_I18N = {
    "en": {
        "whatsnew.title": "What's new",
        "whatsnew.intro": ('Every release ships with a short summary. Old versions '
                           'are backfilled from git tags; the full history lives in '
                           f'<a href="{REPORT_REPO}/blob/main/CHANGELOG.md" target="_blank" '
                           'rel="noopener">CHANGELOG.md</a>.'),
        "whatsnew.lang_note": ('Release notes are written in Chinese (the project language); the '
                               'site UI is available in English, Spanish and Chinese.'),
        "conf.source_note": (
            'Source: <a href="https://www.fda.gov/drugs/medication-errors-related-'
            'cder-regulated-drug-products/fda-name-differentiation-project" target="_blank" '
            'rel="noopener">FDA Name Differentiation Project</a> (content current as of '
            '2026-06-12; US Government work). Only the @@CONF_PAIRS@@ officially re-publishable '
            'pairs from the FDA list are included; the copyright ISMP/ECRI “List of Confused Drug '
            'Names” is not copied. Single names in the FDA list without a pair (hydromorphone, '
            'mitoxantrone) are not listed. A pair is a warning about names, not a statement that '
            'the drugs are equivalent.'),
        "notfound.title": "Page not found",
        "notfound.p1": ("This address has no page. It may be an old link, a typo, or a renamed "
                        "entry."),
        "notfound.p2": ("Go back to the home page and type a medicine name (brand, generic or "
                        "nickname)."),
        "notfound.search": "Search", "notfound.about": "About",
        "notfound.confused": "Confused names", "notfound.whatsnew": "What's new",
        "notfound.report": ('If an internal link is broken, tell us on '
                            f'<a href="{REPORT_REPO}/issues/new?labels=data-error&amp;'
                            'template=data-error.yml">GitHub</a>.'),
    },
    "es": {
        "whatsnew.title": "Novedades",
        "whatsnew.intro": ('Cada versión incluye un resumen breve. Las versiones '
                           'antiguas se rellenan desde las etiquetas de git; el historial completo '
                           f'está en <a href="{REPORT_REPO}/blob/main/CHANGELOG.md" '
                           'target="_blank" rel="noopener">CHANGELOG.md</a>.'),
        "whatsnew.lang_note": ('Las notas de versión están en chino (idioma del proyecto); la '
                               'interfaz del sitio está en inglés, español y chino.'),
        "conf.source_note": (
            'Fuente: <a href="https://www.fda.gov/drugs/medication-errors-related-'
            'cder-regulated-drug-products/fda-name-differentiation-project" target="_blank" '
            'rel="noopener">FDA Name Differentiation Project</a> (contenido actualizado a '
            '2026-06-12; obra del Gobierno de EE. UU.). Solo se incluyen los @@CONF_PAIRS@@ pares '
            'oficiales reutilizables de la lista de la FDA; la lista con copyright de ISMP/ECRI no '
            'se copia. Los nombres sueltos sin pareja (hidromorfona, mitoxantrona) no se listan. '
            'Un par es un aviso sobre nombres, no una afirmación de equivalencia.'),
        "notfound.title": "Página no encontrada",
        "notfound.p1": ("Esta dirección no tiene página. Puede ser un enlace antiguo, una errata o "
                        "una entrada renombrada."),
        "notfound.p2": ("Vuelve al inicio y escribe el nombre de un medicamento (comercial, "
                        "genérico o apodo)."),
        "notfound.search": "Buscar", "notfound.about": "Acerca de",
        "notfound.confused": "Nombres confundibles", "notfound.whatsnew": "Novedades",
        "notfound.report": ('Si un enlace interno está roto, avísanos en '
                            f'<a href="{REPORT_REPO}/issues/new?labels=data-error&amp;'
                            'template=data-error.yml">GitHub</a>.'),
    },
    "zh": {
        "whatsnew.title": "更新日志",
        "whatsnew.intro": ('每次上线都带一条更新摘要；旧版本已按 git tag 补到这里，'
                           f'完整历史见 <a href="{REPORT_REPO}/blob/main/CHANGELOG.md" '
                           'target="_blank" rel="noopener">CHANGELOG.md</a>。'),
        "whatsnew.lang_note": "更新说明正文使用中文（项目语言）；站点界面提供英文、西班牙文与中文。",
        "conf.source_note": (
            '来源：<a href="https://www.fda.gov/drugs/medication-errors-related-'
            'cder-regulated-drug-products/fda-name-differentiation-project" target="_blank" '
            'rel="noopener">FDA Name Differentiation Project</a>（内容截至 2026-06-12，'
            '美国政府作品）。只收 FDA 官方可再发布的 @@CONF_PAIRS@@ 对；ISMP/ECRI 的'
            '《List of Confused Drug Names》有版权，未整表复制。FDA 表里的单名条目'
            '（hydromorphone、mitoxantrone）没有配对，未列入。药对只说明名字可能混淆，'
            '不表示两种药可以互换。'),
        "notfound.title": "页面不存在",
        "notfound.p1": "这个地址没有对应的页面。可能是链接过期、拼写有误，或页面已改名。",
        "notfound.p2": "回到首页输入一个药名（商品名、通用名、俗称都可以）。",
        "notfound.search": "检索", "notfound.about": "关于",
        "notfound.confused": "易混淆药名", "notfound.whatsnew": "更新日志",
        "notfound.report": ('如果是站内链接坏了，欢迎到 '
                            f'<a href="{REPORT_REPO}/issues/new?labels=data-error&amp;'
                            'template=data-error.yml">GitHub</a> 报一声。'),
    },
}


def _atc_coverage(db: sqlite3.Connection) -> dict:
    """ATC 双口径（动态）：全部 substance vs 药物实体（entity_type.csv 里 inn_drug）。

    药物实体分母 = entity_type.csv 中 entity_type=inn_drug、且当前库里存在的 substance。
    这样 About 的数字随库/CSV 自动更新，不在模板里写死。
    """
    import csv as _csv

    path = ROOT / "data" / "entity_type.csv"
    drug_ids: set[str] = set()
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in _csv.DictReader(fh):
                if (row.get("entity_type") or "").strip() == "inn_drug":
                    sid = (row.get("substance_id") or "").strip()
                    if sid:
                        drug_ids.add(sid)
    rows = db.execute("SELECT substance_id, atc FROM substance").fetchall()
    all_n = len(rows)
    all_atc = sum(1 for _sid, atc in rows if atc)
    drug = [(sid, atc) for sid, atc in rows if sid in drug_ids]
    drug_n = len(drug)
    drug_atc = sum(1 for _sid, atc in drug if atc)

    def pct(a: int, n: int) -> float:
        return round(a / n * 100, 1) if n else 0.0

    return {"all_atc": all_atc, "all_n": all_n, "all_pct": pct(all_atc, all_n),
            "drug_atc": drug_atc, "drug_n": drug_n, "drug_pct": pct(drug_atc, drug_n)}


def _i18n_placeholders(stats: dict, atc_cov: dict, coverage, source_cover) -> dict:
    """把 About/Confused 里 @@XXX@@ 占位符替换成当前库的统计值（构建期算，不写死）。"""
    by_country: dict[str, list] = {}
    for r in source_cover:
        by_country.setdefault(r["country"], []).append(r)
    cov = "".join(
        f"<tr><td>{esc(r['country'])}</td><td>{r['n_products']:,}</td>"
        f"<td>{_as_of_cell(by_country.get(r['country'], []))}</td></tr>" for r in coverage)
    return {
        "COV": cov,
        "PRODUCTS": f"{stats['products']:,}",
        "SUBSTANCES": f"{stats['substances']:,}",
        "KEYS": f"{stats['keys']:,}",
        "ALIASES": f"{stats['aliases']:,}",
        "NICKNAMES": f"{stats['nickname']:,}",
        "DRUGTERMS": f"{stats['drug_term']:,}",
        "CONFUSABLE": str(stats["confusable"]),
        "CONF_PAIRS": str(stats["confusable"]),
        "SEVERE": f"{stats['severe']:,}",
        "ATC_ALL_PCT": f"{atc_cov['all_pct']:.1f}",
        "ATC_ALL": f"{atc_cov['all_atc']:,}",
        "ATC_ALL_N": f"{atc_cov['all_n']:,}",
        "ATC_DRUG_PCT": f"{atc_cov['drug_pct']:.1f}",
        "ATC_DRUG": f"{atc_cov['drug_atc']:,}",
        "ATC_DRUG_N": f"{atc_cov['drug_n']:,}",
        "WARN_TOTAL": str(stats.get("warn_total", 0)),
        "WARN_HIGH": str(stats.get("warn_high", 0)),
        "WARN_MEDIUM": str(stats.get("warn_medium", 0)),
        "WARN_INFO": str(stats.get("warn_info", 0)),
    }


def _merge_static_i18n(values: dict) -> None:
    """把 ABOUT_I18N / PAGE_I18N / WARN_I18N 合并进 I18N，并替换 @@占位符@@。"""
    for lang in ("en", "es", "zh"):
        for source in (ABOUT_I18N[lang], PAGE_I18N[lang], WARN_I18N[lang]):
            for key, text in source.items():
                merged = text
                for ph, val in values.items():
                    merged = merged.replace("@@" + ph + "@@", str(val))
                I18N[lang][key] = merged


# ── /warn 页 + 成分页警示：文案三语（页面 UI；警示正文来自 dose_warning 数据）──
WARN_I18N = {
    "en": {
        "nav.warn": "Warnings",
        "warn.title": "Warnings: same name, different drug",
        "warn.intro": ('<p class="sub">Published warnings about names that are easily confused, '
                       'or products that are <b>not interchangeable</b> — across countries, salt '
                       'forms or release mechanisms. This page only flags identity and '
                       'interchangeability; it contains <b>no dosing advice</b> and no substitution '
                       'recommendations.</p>'),
        "warn.count": ('<p class="sub">@@WARN_TOTAL@@ published warnings: @@WARN_HIGH@@ high '
                       'severity, @@WARN_MEDIUM@@ medium, @@WARN_INFO@@ info. Draft warnings are '
                       'not shown.</p>'),
        "warn.no_advice": ('Not medical advice. Check the actual pack and the ingredient, and ask '
                          'a pharmacist before changing products.'),
        "warn.group.high": "High severity — do not assume interchangeability",
        "warn.group.medium": "Medium severity — check before assuming equivalence",
        "warn.group.info": "Also worth knowing",
        "warn.sev.high": "High", "warn.sev.medium": "Medium", "warn.sev.info": "Info",
        "warn.source": "Regulatory source",
        "warn.related": "Related ingredient",
        "warn.countries": "Markets",
        "warn.reviewed": "Reviewed by",
        "warn.drug_summary": "Safety warnings for this ingredient",
        "warn.see_all": "See all warnings",
        "warn.empty": "No published warnings yet.",
        "warn.source_note": ('<b>Sources &amp; licences</b>: each warning links to the regulator’s '
                             'original document (DailyMed/FDA, EMA/MHRA, Health Canada DPD, AEMPS '
                             'CIMA, PBS/TGA, NMPA …). We publish factual excerpts only and keep the '
                             'source link; labels, SmPC/CMI full texts are not reproduced. See the '
                             'licence register in About for terms.'),
    },
    "es": {
        "nav.warn": "Alertas",
        "warn.title": "Alertas: mismo nombre, otro medicamento",
        "warn.intro": ('<p class="sub">Alertas publicadas sobre nombres que se confunden '
                       'fácilmente, o productos que <b>no son intercambiables</b> — entre países, '
                       'formas salinas o mecanismos de liberación. Esta página solo señala '
                       'identidad e intercambiabilidad; <b>no contiene consejos de dosificación</b> '
                       'ni recomendaciones de sustitución.</p>'),
        "warn.count": ('<p class="sub">@@WARN_TOTAL@@ alertas publicadas: @@WARN_HIGH@@ de '
                       'severidad alta, @@WARN_MEDIUM@@ media, @@WARN_INFO@@ informativas. Las '
                       'alertas en borrador no se muestran.</p>'),
        "warn.no_advice": ('No es consejo médico. Comprueba el envase y el principio activo, y '
                          'consulta a un farmacéutico antes de cambiar de producto.'),
        "warn.group.high": "Severidad alta — no supongas que son intercambiables",
        "warn.group.medium": "Severidad media — comprueba antes de asumir equivalencia",
        "warn.group.info": "También conviene saberlo",
        "warn.sev.high": "Alta", "warn.sev.medium": "Media", "warn.sev.info": "Info",
        "warn.source": "Fuente regulatoria",
        "warn.related": "Principio relacionado",
        "warn.countries": "Mercados",
        "warn.reviewed": "Revisado por",
        "warn.drug_summary": "Alertas de seguridad de este principio activo",
        "warn.see_all": "Ver todas las alertas",
        "warn.empty": "Todavía no hay alertas publicadas.",
        "warn.source_note": ('<b>Fuentes y licencias</b>: cada alerta enlaza al documento original '
                             'del regulador (DailyMed/FDA, EMA/MHRA, Health Canada DPD, AEMPS CIMA, '
                             'PBS/TGA, NMPA …). Solo publicamos extractos fácticos y conservamos el '
                             'enlace; no reproducimos prospectos ni textos completos SmPC/CMI. Las '
                             'condiciones están en el registro de licencias de «Acerca de».'),
    },
    "zh": {
        "nav.warn": "警示",
        "warn.title": "警示：同名不同药 / 不可互换",
        "warn.intro": ('<p class="sub">已发布的警示：名字容易混淆、或产品<b>不可互换</b>——'
                       '涉及不同国家、盐型或释放机制。本页只说明身份与不可互换性，'
                       '<b>不提供任何用药建议</b>，也不给替代方案。</p>'),
        "warn.count": ('<p class="sub">已发布 @@WARN_TOTAL@@ 条：高严重度 @@WARN_HIGH@@ 条、'
                       '中 @@WARN_MEDIUM@@ 条、提示 @@WARN_INFO@@ 条。草稿状态不展示。</p>'),
        "warn.no_advice": "这不是医疗建议。换药前请核对实际包装与成分，并咨询药师。",
        "warn.group.high": "高严重度——不要假定可以互换",
        "warn.group.medium": "中严重度——先核对再假定等效",
        "warn.group.info": "也值得了解",
        "warn.sev.high": "高", "warn.sev.medium": "中", "warn.sev.info": "提示",
        "warn.source": "监管来源",
        "warn.related": "相关成分",
        "warn.countries": "涉及市场",
        "warn.reviewed": "核验",
        "warn.drug_summary": "该成分的安全警示",
        "warn.see_all": "查看全部警示",
        "warn.empty": "暂无已发布警示。",
        "warn.source_note": ('<b>来源与许可</b>：每条警示都链接到监管机构原文（DailyMed/FDA、'
                             'EMA/MHRA、Health Canada DPD、AEMPS CIMA、PBS/TGA、NMPA 等）。'
                             '本站只发布事实摘录并保留来源链接，不转载说明书、SmPC/CMI 全文；'
                             '具体条款见「关于」里的许可清单。'),
    },
}


def _warn_badge(severity: str, lang: str) -> str:
    cls = {"high": "badge sev", "medium": "badge warn"}.get(severity, "tag")
    label = I18N[lang].get("warn.sev." + severity, severity)
    return f'<span class="{cls}">{esc(label)}</span>'


def _warn_meta_html(row: dict, lang: str, sub_names: dict[str, str],
                    prefix: str = "") -> str:
    """一条警示的来源/相关成分/市场（语言无关链接 + 本地化标签）。"""
    T = I18N[lang]
    parts = [f'<b>{esc(T["warn.source"])}</b>: '
             f'<a href="{esc(row["source_url"])}" target="_blank" rel="noopener">'
             f'{esc(row["source_url"].split("//")[-1].split("/")[0])}</a>']
    rel = []
    seen: set[str] = set()
    for key in ("substance_id", "related_substance_id"):
        sid = row.get(key)
        if sid and sid not in seen:
            seen.add(sid)
            name = sub_names.get(sid) or sid
            rel.append(f'<a href="{prefix}drug/{esc(sid)}.html">{esc(name)}</a>')
    if rel:
        parts.append(f'<b>{esc(T["warn.related"])}</b>: ' + " · ".join(rel))
    if row.get("country"):
        parts.append(f'<b>{esc(T["warn.countries"])}</b>: {esc(row["country"])}')
    if row.get("reviewed_by"):
        parts.append(f'<b>{esc(T["warn.reviewed"])}</b>: {esc(row["reviewed_by"])}')
    return '<p class="warn-meta">' + " · ".join(parts) + "</p>"


def _warn_lang_blocks(row: dict, sub_names: dict[str, str], *, prefix: str,
                      link: bool = False) -> str:
    """一条警示的 zh/en/es 三块正文（data-lang-block；数据缺 es 时回退英文并标注）。"""
    out = []
    for lang in ("en", "zh", "es"):
        title = row.get("title_" + lang) or row.get("title_en") or ""
        body = row.get("body_" + lang) or row.get("body_en") or ""
        fallback = "" if row.get("body_" + lang) else (
            ' <span class="meta">(EN)</span>' if lang != "en" else "")
        head = f'<h3>{_warn_badge(row["severity"], lang)} {esc(title)}{fallback}</h3>'
        if link:
            head = (f'<h3><a href="{prefix}warn.html#w-{esc(row["warning_id"])}">'
                    f'{esc(title)}{fallback}</a>{_warn_badge(row["severity"], lang)}</h3>')
        out.append(
            f'<div class="lang-block" data-lang-block="{lang}">'
            f'{head}<p class="warn-body">{esc(body)}</p>'
            f'{_warn_meta_html(row, lang, sub_names, prefix)}</div>')
    return "".join(out)


def _drug_warn_html(rows: list[dict]) -> str:
    """成分页顶部警示摘要（最多 3 条 + 链 /warn），按当前语言只显示一块。"""
    if not rows:
        return ""
    parts = ['<div class="notice warnbox drugwarn">']
    for lang in ("en", "zh", "es"):
        T = I18N[lang]
        items = "".join(
            f'<li><a href="../warn.html#w-{esc(r["warning_id"])}">{esc(r.get("title_" + lang) or r.get("title_en") or "")}</a></li>'
            for r in rows[:3])
        parts.append(
            f'<div class="lang-block" data-lang-block="{lang}">'
            f'<b>{esc(T["warn.drug_summary"])}</b><ul class="sub">{items}</ul>'
            f'<a href="../warn.html">{esc(T["warn.see_all"])}</a></div>')
    parts.append("</div>")
    return "".join(parts)


def build_warn(db: sqlite3.Connection) -> int:
    """/warn 页：只展示 dose_warning.status='published'，按 severity 分组（high→medium→info）。

    页面只做「同名不同药 / 不可互换」警示，不给用药建议；每条带监管来源链接。
    警示正文是数据行（zh/en/es 各一份），用 data-lang-block 在客户端按语言切换。
    """
    rows = [dict(r) for r in db.execute(
        """SELECT * FROM dose_warning WHERE status = 'published'
           ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                    warning_id""")]
    sub_names: dict[str, str] = {}
    for sid, inn_zh, inn_en in db.execute(
            "SELECT substance_id, inn_zh, inn_en FROM substance"):
        sub_names[sid] = inn_zh or inn_en or sid
    groups = {"high": [], "medium": [], "info": []}
    for row in rows:
        groups.setdefault(row["severity"], []).append(row)
    grp_html = []
    for sev in ("high", "medium", "info"):
        if not groups.get(sev):
            continue
        grp_html.append(f'<h2 data-i18n="warn.group.{sev}">{esc(I18N["en"]["warn.group." + sev])}</h2>')
        for row in groups[sev]:
            grp_html.append(
                f'<article class="warn-item" id="w-{esc(row["warning_id"])}">'
                + _warn_lang_blocks(row, sub_names, prefix="")
                + "</article>")
    body = f"""<h1 data-i18n="warn.title">{esc(I18N["en"]["warn.title"])}</h1>
<div data-i18n-html="warn.intro">{I18N["en"]["warn.intro"]}</div>
<div class="notice" data-i18n="warn.no_advice">{esc(I18N["en"]["warn.no_advice"])}</div>
<div data-i18n-html="warn.count">{I18N["en"]["warn.count"]}</div>
{''.join(grp_html) if grp_html else '<p class="empty" data-i18n="warn.empty">No published warnings yet.</p>'}
<div class="notice warnbox" data-i18n-html="warn.source_note">{I18N["en"]["warn.source_note"]}</div>"""
    (OUT / "warn.html").write_text(page("Warnings", body), encoding="utf-8")
    return len(rows)


# 许可与署名：直接取自 reports/license-audit.md §4（三语并列的许可原文段落）。
LICENCE_HTML = f"""
<h2 id="licences">Data sources and licences 数据来源与许可 Fuentes y licencias</h2>
<p class="sub"><b>EN</b>: This site is a non-commercial public reference. We store only factual
fields (names, active ingredients, strengths, dosage forms, status) and link to the originals;
we do not republish full labels, CMI/SmPC texts or data dumps. Source-specific terms and
attribution are listed in the <a href="{DOCS_LICENCE_URL}">licence register</a>.
<br><b>中文</b>：本站为非商业公开参考站，只存事实字段（名称、成分、规格、剂型、状态）并链回原文，
不转载说明书 / CMI / SmPC 全文，也不提供原始数据批量下载。各来源许可与署名见
<a href="{DOCS_LICENCE_URL}">许可清单</a>。
<br><b>ES</b>: Este sitio es una referencia pública sin ánimo de lucro. Solo almacenamos campos
fácticos (nombres, principios activos, concentraciones, formas farmacéuticas, estado) y enlazamos
al original; no reproducimos prospectos, textos CMI/SmPC ni volcados de datos. Las condiciones y
atribuciones por fuente están en el <a href="{DOCS_LICENCE_URL}">registro de licencias</a>.</p>
<ul class="sub">
<li><b>China 中国 / China</b>: 医保药品分类与代码数据库由<b>国家医保局</b>公开；我们<b>未找到开放的再发布许可</b>，
只存事实字段并链回原文，不再发布原始数据表。EN: the NHSA catalogue is public but we found
<b>no open licence for redistribution</b>; factual fields only, with links, no bulk republication.
ES: el catálogo de la NHSA es público, pero <b>no hemos encontrado una licencia abierta de
redistribución</b>; solo campos fácticos y enlaces. 来源 Source: <a href="https://code.nhsa.gov.cn/yp/toPublicGoodsData.html">code.nhsa.gov.cn</a></li>
<li><b>Spain 西班牙 / España</b>: © <b>AEMPS</b> — CIMA (Centro de Información online de
Medicamentos). Reproduction of AEMPS website contents is authorised provided the source is
expressly cited and the <b>date of last update</b> is mentioned (Aviso legal). This is not an open
licence; we treat it as "conditional / pending confirmation". 中文：© AEMPS，引用须注明来源与文件最后更新日期，
非开放许可，按「待确认」处理。ES: © AEMPS — se autoriza la reproducción citando expresamente la
fuente y la fecha de última actualización (Aviso legal); no es una licencia abierta.
<a href="https://www.aemps.gob.es/aviso-legal/">Aviso legal</a> · <a href="https://cima.aemps.es/cima/publico/home.html">CIMA</a></li>
<li><b>Mexico 墨西哥 / México</b>: COFEPRIS registration lists published on gob.mx carry
<b>no stated open licence</b> (status: pending confirmation); we store factual fields only and
link to the source. Strengths were back-filled from <b>ISSSTE, PROFECO, HGMGG, INER, INPRFM and
SEMAR</b> procurement/price datasets published on <b>datos.gob.mx</b>, licensed <b>CC BY 4.0</b>
(attribution: Gobierno de México — datos.gob.mx, each dataset attributed to its publishing
institution). 中文：COFEPRIS 清单未标注开放许可，按「待确认」只存事实 + 链接；规格回填数据来自
datos.gob.mx 的 ISSSTE/PROFECO/HGMGG/INER/INPRFM/SEMAR 数据集（CC BY 4.0，署名发布机构）。
ES: las listas de COFEPRIS no declaran licencia abierta (pendiente de confirmación); solo campos
fácticos y enlaces. Los datos de concentración proceden de ISSSTE, PROFECO, HGMGG, INER, INPRFM y
SEMAR en datos.gob.mx, con licencia CC BY 4.0.
<a href="https://www.gob.mx/cofepris/documentos/registros-sanitarios-medicamentos">COFEPRIS</a> ·
<a href="https://datos.gob.mx/">datos.gob.mx</a> ·
<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a></li>
<li><b>Australia 澳洲 / Australia</b>: PBS Schedule data — <i>Copyright (c) 2024 Department of
Health, Commonwealth of Australia.</i> (copyright notice retained; content not modified).
TGA CMI repository and ARTG Public Summary entries — <b>© Commonwealth of Australia</b>; the TGA
copyright notice permits personal/internal non-commercial use of unaltered material and does not
permit re-transmission or redistribution without written permission, so we store <b>factual
fields only</b> (trade name, active ingredients, ARTG ID, status) with links and publish no
full-text CMI/ARTG content. 中文：PBS 保留版权声明且不修改内容；TGA CMI 与 ARTG 明细只取事实字段
（商品名/成分/ARTG ID/状态）并链回原文，不转载 CMI 全文、不再分发原始材料。
ES: datos PBS con aviso de copyright intacto y sin modificaciones; de TGA CMI y ARTG solo
almacenamos campos fácticos con enlaces, sin reproducir textos completos.
<a href="https://www.health.gov.au/using-our-websites/copyright">PBS copyright</a> ·
<a href="https://www.tga.gov.au/copyright">TGA copyright</a></li>
<li><b>Canada 加拿大 / Canadá</b>: Health Canada <b>Drug Product Database (DPD)</b> — re-use for
non-commercial purposes with source acknowledgement: <i>© His Majesty the King in Right of Canada,
as represented by the Minister of Health.</i> 中文：仅非商业再使用，须注明来源（加拿大卫生部）。
ES: reutilización no comercial con mención de la fuente. Terms: <a href="https://health-products.canada.ca/dpd-bdpp/">DPD</a></li>
<li><b>WHO INN / OMS</b>: Contains International Nonproprietary Names (INN) data from the
<b>World Health Organization</b>. WHO INN lists are licensed <b>CC BY-NC-SA 3.0 IGO</b>
(attribution + non-commercial + share-alike); this site is non-commercial, and any mapping table
derived from WHO INN lists is shared under the same licence. WHO does not endorse this site.
中文：含世界卫生组织 INN 数据；WHO INN 清单为 CC BY-NC-SA 3.0 IGO（署名 + 非商业 + 相同方式共享），
基于该清单的派生映射表以同许可共享；WHO 未背书本站。
ES: contiene datos de INN de la Organización Mundial de la Salud; las listas INN tienen licencia
CC BY-NC-SA 3.0 IGO (atribución + no comercial + compartir igual); los mapeos derivados se
comparten con la misma licencia. <a href="https://www.who.int/teams/health-product-and-policy-standards/inn">WHO INN</a> ·
<a href="https://creativecommons.org/licenses/by-nc-sa/3.0/igo/">CC BY-NC-SA 3.0 IGO</a></li>
<li><b>ChEMBL</b>: ATC mapping derived from <b>ChEMBL (EMBL-EBI)</b>, licensed <b>CC BY-SA 4.0</b>;
the derived ATC mapping table is available under the same licence. 中文：基于 ChEMBL 的 ATC 映射
须署名 EMBL-EBI 并按 CC BY-SA 4.0 相同方式共享。ES: mapeo ATC derivado de ChEMBL (EMBL-EBI),
licencia CC BY-SA 4.0; la tabla derivada se comparte con la misma licencia.
<a href="https://chembl.gitbook.io/chembl-interface-documentation/downloads">ChEMBL</a> ·
<a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a></li>
<li><b>Other sources 其他来源</b>: openFDA (public domain / CC0), FDA tall-man list (US Government
work), NIDA (US Government work), DEA (Public Domain Mark 1.0), MedlinePlus/NLM (US Government
work), NHSBSA dm+d (Open Government Licence v3.0 — <i>Contains public sector information licensed
under the Open Government Licence v3.0.</i>), Wikidata P267 (CC0 1.0). ISMP/ECRI LASA lists and
WHOCC ATC/DDD index are copyrighted and are <b>not</b> reproduced. 中文：其余来源见许可清单；
ISMP/ECRI 与 WHOCC ATC/DDD 有版权，未使用。ES: el resto de fuentes figura en el registro de
licencias; las listas ISMP/ECRI y el índice WHOCC ATC/DDD no se reproducen.</li>
</ul>
<p class="sub"><b>Non-commercial notice 非商业声明</b>: this site is public, ad-free and offers no
paid data service; if that changes, the NC/conditional sources above must be re-evaluated.
本站公开、无广告、不提供付费数据服务；如未来商业化，上述标非商业/待确认的来源须重新评估。</p>
"""


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
/* ── UI P0：解析条 / 自动完成 / 分组折叠 / 加载更多 / 国家提示 ── */
.sel-label{color:var(--muted);font-size:14px;margin-right:2px}
.searchwrap{position:relative}
#ac{position:absolute;left:0;right:0;top:calc(100% + 6px);z-index:30;display:none;
background:#fff;border:1px solid var(--line);border-radius:12px;
box-shadow:0 8px 24px rgba(31,35,40,.12);overflow:hidden;text-align:left}
#ac.open{display:block}
.ac-item{display:flex;justify-content:space-between;align-items:baseline;gap:10px;
padding:9px 12px;cursor:pointer;font-size:14px;border-bottom:1px solid #f1efe9}
.ac-item:last-child{border-bottom:0}
.ac-item.on{background:#f1f8f4}
.ac-name{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ac-meta{color:var(--muted);font-size:12px;white-space:nowrap;flex:none}
.parsebar{display:flex;flex-wrap:wrap;gap:6px 16px;background:#f4f6f4;
border:1px solid var(--line);border-radius:10px;padding:8px 12px;font-size:13px;margin:14px 0}
.parsebar b{color:var(--muted);font-weight:600;margin-right:4px}
.parsebar .pmatch{color:var(--accent)}
.grp-name{font-weight:600}
.grp-count{color:var(--muted);font-size:12px;font-weight:400;margin-left:6px}
.grp-tags{text-align:right}
.linkbtn{background:none;border:0;color:var(--accent);padding:2px 0;cursor:pointer;
font-size:13px;text-decoration:underline}
.fold-row td{padding:2px 8px 8px}
.loadmore{text-align:center;margin:10px 0 0}
.loadmore button{padding:8px 16px;font-size:14px}
.countrymiss .cm-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:8px}
.countrymiss .cm-actions a,.countrymiss .cm-actions button{font-size:14px}
@media (max-width:719px){
  .wrap{padding:0 14px}
  header .wrap{height:auto;flex-wrap:wrap;padding:10px 14px;gap:8px 12px}
  .logo{font-size:15px}
  .logo-zh{display:none}
  nav{flex-wrap:wrap;gap:8px 12px;font-size:13px}
  .langs{margin-left:auto}
  #q{font-size:16px;padding:12px 14px}
  .row{gap:8px}
  .sel-label{display:block;width:100%;margin:2px 0 0}
  .parsebar{gap:4px 12px;font-size:12px}
  .card{padding:12px}
  footer .wrap{display:block}
  .foot-links{margin:8px 0 0;display:flex;flex-wrap:wrap;white-space:normal;gap:8px 14px}
  /* 结果表 → 卡片（ARTG / 同成分表一并生效，靠 data-label 带出列名） */
  table.res{display:block;border:0;border-radius:0;background:transparent;margin-top:8px}
  table.res thead{display:none}
  table.res tbody{display:block}
  table.res tr{display:block;background:#fff;border:1px solid var(--line);
    border-radius:12px;margin:8px 0;padding:8px 12px}
  table.res td{display:block;border:0;padding:2px 0;width:auto}
  table.res td.c-dose{white-space:normal}
  table.res td.c-empty{display:none}
  table.res td[data-label]:before{content:attr(data-label) " · ";color:var(--muted);font-size:12px}
  table.res tr.grp{background:#f7f8f5;border-color:#e7e5dc;padding:8px 12px}
  table.res tr.grp td{display:block;width:auto}
  table.res tr.grp .grp-tags{text-align:left;margin-top:2px}
  table.res tr.fold-row{background:transparent;border:0;padding:0;margin:0}
  table.res tr.fold-row td{padding:0 0 4px}
  table.res tbody tr:hover{background:#fff}
  .loadmore button{width:100%}
}
/* i18n P1：静态页（About / What's new / Confused）移动端收尾 */
@media (max-width:719px){
  .tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
  main table:not(.res){font-size:13px}
  .release table{display:block;overflow-x:auto}
  .release ul,.release li,p,li{overflow-wrap:anywhere}
}
/* /warn 页：数据行按语言只显示一块（无 JS 时默认英文） */
.lang-block{display:none}
.lang-block[data-lang-block="en"]{display:block}
.warn-item{border:1px solid var(--line);border-radius:12px;background:#fff;
  padding:12px 14px;margin:10px 0}
.warn-item h3{margin:0 0 6px;font-size:16px;line-height:1.45}
.warn-item .warn-body{margin:0 0 8px}
.warn-item .warn-meta{color:var(--muted);font-size:13px;margin:0;overflow-wrap:anywhere}
.warn-item .badge{vertical-align:2px}
.drugwarn ul{margin:6px 0 4px;padding-left:20px}
@media (max-width:719px){
  .warn-item .warn-meta{font-size:12px}
}
"""

APP_JS = r"""
const box = document.getElementById('q');
const out = document.getElementById('out');
const ctry = document.getElementById('country');
const meta = document.getElementById('meta');
const acEl = document.getElementById('ac');
const ctryLabel = document.getElementById('ctrylabel');
// 页面在 / 或 /es/ 或 /zh/ 下，资源与内容页都在站点根目录，按 app.js 的位置推根路径
const BASE = ((document.currentScript && document.currentScript.src) || location.href)
  .replace(/assets\/app\.js.*$/, '');
// 访问统计（GoatCounter，cookieless）。未配置 code 时页面不会注入脚本，这里静默无操作。
// 事件命名：search-<归一化词> / click-result / click-report / click-whatsnew / country-<US|…>。
function gcEvent(name){
  try{
    if(name && window.goatcounter && typeof window.goatcounter.count === 'function'){
      window.goatcounter.count({path: String(name).slice(0,120), event: true});
    }
  }catch(e){}
}
let SEARCH_EV = null;
function scheduleSearchEvent(q){
  clearTimeout(SEARCH_EV);
  const term = norm(splitDose(q)[0]);
  if(!term || term.length < 2) return;
  SEARCH_EV = setTimeout(()=>gcEvent('search-' + term.slice(0,40)), 900);
}
let IDX = [], NICKS = [], CONF = [];
// 搜索增强（task-28）：运行时候选层 + 拼音表懒加载状态，见 collectHits()/pinyinFetch()。
let SEARCH_LAYERS = null, PY_MAP = null, PY_P = null;
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
  const body = rows.map(r => `<tr><td data-label="${esc(T('col.brand'))}">${esc(r[1])}</td>
    <td data-label="${esc(T('artg.sponsor'))}">${esc(r[2]) || '—'}</td>
    <td data-label="${esc(T('artg.id'))}"><code>${esc(r[3])}</code></td></tr>`).join('');
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
    <td class="c-dose" data-label="${esc(T('col.dose'))}">${r.d || '—'}</td>
    <td class="c-brand" data-label="${esc(T('col.brand'))}"><a href="${link}">${r.b}</a>${tags}${combo}${badge}</td>
    <td class="c-mah" data-label="${esc(T('col.mah'))}">${mah || '—'}</td></tr>`;
}
// ── UI P0 ③④：自动完成 / 解析条 / 成分分组 + 品牌折叠 + 加载更多 ──────
// 一条「品牌行」= 一个索引条目（同成分下的一个品牌/写法），剂量合并展示，
// 不再按每个规格各占一行；分组头显示成分与品牌数。
function brandRowHTML(e, T){
  const badge = e.l==='severe' ? `<span class="badge sev">${T('badge.severe')}</span>` :
                e.l==='warning' ? `<span class="badge warn">${T('badge.warning')}</span>` : '';
  const tags = (e.c || []).map(x=>`<span class="tag ${x.toLowerCase()}">${x}</span>`).join('');
  const combo = (e.x || '').indexOf(' + ') >= 0
    ? `<span class="tag combo">${T('badge.combo')}</span>` : '';
  const link = e.u ? `${BASE}name/${e.u}` : `${BASE}drug/${e.v}.html`;
  const mah = e.m ? (e.mn > 1 ? `${e.m} <span class="more">+${e.mn-1}</span>` : e.m) : '';
  const ds = (e.s && e.s.length) ? e.s.slice().sort((a,b)=>doseNum(a)-doseNum(b)) : [''];
  return `<tr class="br">
    <td class="c-ing c-empty"></td>
    <td class="c-dose" data-label="${esc(T('col.dose'))}">${esc(ds.join(' / ')) || '—'}</td>
    <td class="c-brand" data-label="${esc(T('col.brand'))}"><a href="${link}">${esc(e.d)}</a>${tags}${combo}${badge}</td>
    <td class="c-mah" data-label="${esc(T('col.mah'))}">${mah || '—'}</td></tr>`;
}
const RES_PAGE = 25;              // 每次「加载更多」新增的品牌行数
let RES_LIMIT = RES_PAGE;
let RES_EXPANDED = new Set();     // 已展开的分组下标
let RES_GROUPS = null;            // [{ing, tags:Set, rows:[entry]}]
function groupByIngredient(display){
  const order=[], map=new Map();
  for(const [, t, e] of display){
    const key = e.x || e.d || e.k;
    let g = map.get(key);
    if(!g){ g = {ing: e.x || e.d, tags:new Set(), rows:[], tier:t}; map.set(key, g); order.push(g); }
    (e.c || []).forEach(c => g.tags.add(c));
    g.rows.push(e);
  }
  return order;
}
function resultsHTML(T){
  if(!RES_GROUPS || !RES_GROUPS.length) return '';
  // 可见行数 = 展开组用全部品牌、折叠组只算前 2 个；「加载更多」按可见行分页，
  // 展开某个成分（品牌折叠）后才把该组的全部品牌计入分页。
  const visibleTotal = RES_GROUPS.reduce((n, g, gi) =>
    n + (RES_EXPANDED.has(gi) ? g.rows.length : Math.min(2, g.rows.length)), 0);
  let html='', count=0, cut=false;
  for(let gi=0; gi<RES_GROUPS.length; gi++){
    const g = RES_GROUPS[gi];
    if(count >= RES_LIMIT){ cut = true; break; }
    const expanded = RES_EXPANDED.has(gi);
    const vis = expanded ? g.rows : g.rows.slice(0, 2);
    const tags = [...g.tags].sort().map(x=>`<span class="tag ${x.toLowerCase()}">${x}</span>`).join('');
    html += `<tr class="grp"><td class="c-ing"><span class="grp-name">${esc(g.ing)}</span>`
      + `<span class="grp-count">${g.rows.length} ${esc(T('res.brands_noun'))}</span></td>`
      + `<td colspan="3" class="grp-tags">${tags}</td></tr>`;
    for(let i=0; i<vis.length; i++){
      if(count >= RES_LIMIT){ cut = true; break; }
      html += brandRowHTML(vis[i], T); count++;
    }
    if(g.rows.length > vis.length){
      html += `<tr class="fold-row"><td colspan="4"><button type="button" class="linkbtn"`
        + ` data-gi="${gi}" data-fold="1">${esc(T('res.show_brands'))}`
        + ` +${g.rows.length - vis.length}</button></td></tr>`;
    } else if(expanded && g.rows.length > 2){
      html += `<tr class="fold-row"><td colspan="4"><button type="button" class="linkbtn"`
        + ` data-gi="${gi}" data-fold="0">${esc(T('res.fold'))}</button></td></tr>`;
    }
    if(cut) break;
  }
  if(count < visibleTotal){
    html += `<tr class="fold-row"><td colspan="4"><button type="button" class="linkbtn"`
      + ` data-loadmore="1">${esc(T('res.load_more'))}`
      + ` (+${Math.min(RES_PAGE, visibleTotal-count)})</button></td></tr>`;
  } else if(visibleTotal > RES_PAGE){
    html += `<tr class="fold-row"><td colspan="4"><span class="sub">`
      + `${esc(T('res.loaded_all'))}</span></td></tr>`;
  }
  return html;
}
function resultsTableHTML(T){
  return `<table class="res grouped"><thead><tr>
      <th>${T('col.ing')}</th><th>${T('col.dose')}</th>
      <th>${T('col.brand')}</th><th>${T('col.mah')}</th>
    </tr></thead><tbody>${resultsHTML(T)}</tbody></table>`;
}
function paintResultsOnly(){
  const wrap = document.getElementById('reswrap');
  if(!wrap || !RES_GROUPS) return;
  const T = window.T || (k=>k);
  wrap.innerHTML = resultsTableHTML(T);
}
// ── 解析条：名称 / 剂量 / 剂型 / 匹配方式 ─────────────────────────
const FORM_TOKENS = ['片剂','片','胶囊','颗粒剂','颗粒','口服液','注射液','注射剂','软膏',
  '乳膏','凝胶','滴眼液','滴鼻液','喷雾剂','喷雾','吸入剂','缓释','控释','肠溶','糖浆',
  '混悬液','栓剂','贴剂','散剂','滴丸','丸','tablets','tablet','capsules','capsule',
  'syrup','injection','injectable','cream','ointment','gel','spray','inhaler','drops',
  'suspension','suppository','patch','powder','solution'];
function parseQuery(q){
  const [nameQ, st] = splitDose(q);
  const lower = String(nameQ || '').toLowerCase();
  let form = '';
  for(const w of FORM_TOKENS){ if(lower.indexOf(w) >= 0){ form = w; break; } }
  return {name: String(nameQ || '').trim(), dose: st ? (st[0] + ' ' + st[1]) : '', form};
}
function parseBarHTML(parsed, matchLabel){
  const T = window.T || (k=>k);
  const items = [];
  if(parsed.name) items.push(`<span class="pitem"><b>${esc(T('parse.name'))}</b>${esc(parsed.name)}</span>`);
  if(parsed.dose) items.push(`<span class="pitem"><b>${esc(T('parse.dose'))}</b>${esc(parsed.dose)}</span>`);
  if(parsed.form) items.push(`<span class="pitem"><b>${esc(T('parse.form'))}</b>${esc(parsed.form)}</span>`);
  items.push(`<span class="pitem"><b>${esc(T('parse.match'))}</b><span class="pmatch">${esc(matchLabel)}</span></span>`);
  return `<div class="parsebar" role="status" aria-label="${esc(T('parse.label'))}">${items.join('')}</div>`;
}
// ── 自动完成（输入 ≥2 字，top 8；键盘 ↑↓/回车/Esc，点击可选）────────
let AC_ITEMS = [], AC_I = -1, AC_T = null, AC_WANT = false;
function acClose(){
  if(!acEl) return;
  acEl.classList.remove('open');
  acEl.innerHTML = '';
  AC_ITEMS = []; AC_I = -1;
  if(box.setAttribute) box.setAttribute('aria-expanded', 'false');
}
function acPaint(){
  const T = window.T || (k=>k);
  if(!acEl || !AC_ITEMS.length){ acClose(); return; }
  acEl.innerHTML = AC_ITEMS.map((it, i) => {
    const e = it.e;
    const tags = (e.c || []).slice(0, 3)
      .map(x=>`<span class="tag ${x.toLowerCase()}">${x}</span>`).join('');
    return `<div class="ac-item${i===AC_I?' on':''}" role="option" aria-selected="${i===AC_I}" data-i="${i}">`
      + `<span class="ac-name">${esc(e.d || e.k)}</span>`
      + `<span class="ac-meta">${esc(e.x || '')}${tags ? ' ' + tags : ''}</span></div>`;
  }).join('');
  acEl.classList.add('open');
  if(box.setAttribute) box.setAttribute('aria-expanded', 'true');
}
function acCompute(nq){
  if(!IDX_READY || !nq || nq.length < 2) return [];
  const cjk = /[\u4e00-\u9fff]/.test(nq);
  const minSub = cjk ? 2 : 4;
  const pool = [];
  const rankOf = (e) => {
    const k = e.k;
    if(k === nq) return 0;
    if(k.replace(/ /g,'') === nq.replace(/ /g,'')) return 1;
    if(k.indexOf(nq) === 0) return 2;
    if(nq.length >= minSub && k.indexOf(nq) >= 0) return 3;
    return -1;
  };
  const collect = (e) => {
    const rank = rankOf(e);
    if(rank < 0) return;
    pool.push([rank, -(e.n || 0), e.k.length, e]);
  };
  // 派生层就绪时只遍历候选（语义与全表扫描的 rank 0-3 一致）；否则退回全表。
  const cand = (!LEGACY && SEARCH_LAYERS && SEARCH_LAYERS.heavy) ? layerCandidates(nq) : null;
  if(cand){
    for(const pair of cand){
      collect(IDX[pair[0]]);
      if(pool.length >= 500) break;
    }
  }else{
    for(const e of IDX){
      collect(e);
      if(pool.length >= 500) break;
    }
  }
  pool.sort((a,b)=> a[0]-b[0] || a[1]-b[1] || a[2]-b[2]);
  const seen = new Set(), out = [];
  for(const item of pool){
    const e = item[3];
    if(seen.has(e.k)) continue;
    seen.add(e.k); out.push({e});
    if(out.length >= 8) break;
  }
  return out;
}
function acUpdate(){
  clearTimeout(AC_T);
  const raw = box.value.trim();
  const nq = norm(splitDose(raw)[0]);
  if(nq.length < 2){ AC_WANT = false; acClose(); return; }
  if(!IDX_READY){ AC_WANT = true; acClose(); loadIndex(); return; }  // 加载完成后补算
  AC_WANT = false;
  AC_T = setTimeout(()=>{ AC_ITEMS = acCompute(nq); AC_I = -1; acPaint(); }, 90);
}
function acSelect(i){
  const it = AC_ITEMS[i];
  if(!it) return;
  box.value = it.e.d || it.e.k;
  acClose();
  render();
  try{ box.focus(); }catch(e){}
}
// ── 国家语义：标签随选择变化 / 该国无匹配时的显式提示 ────────────────
function updateCtryLabel(){
  if(!ctryLabel) return;
  const T = window.T || (k=>k);
  const c = ctry.value;
  let name = '';
  try{
    for(const o of ctry.options){ if(o.value === c){ name = o.text; break; } }
  }catch(e){}
  ctryLabel.textContent = c
    ? T('home.country_label_sel').replace('{country}', name)
    : T('home.country_label');
  if(ctryLabel.removeAttribute) ctryLabel.removeAttribute('data-i18n');
}
// ── URL 状态：q / country 可分享、可前进后退（history.replaceState，不新增历史项）──
let URL_T = null;
function syncURL(q){
  clearTimeout(URL_T);
  URL_T = setTimeout(()=>{
    try{
      if(!window.history || !window.history.replaceState) return;
      const u = new URL(location.href);
      if(q) u.searchParams.set('q', q); else u.searchParams.delete('q');
      const c = ctry.value;
      if(c) u.searchParams.set('country', c); else u.searchParams.delete('country');
      window.history.replaceState(null, '', u.pathname + (u.search || '') + (u.hash || ''));
    }catch(e){}
  }, 300);
}
if(window.addEventListener){
  window.addEventListener('popstate', ()=>{
    try{
      const p = new URLSearchParams(location.search);
      box.value = p.get('q') || '';
      ctry.value = (p.get('country') || '').toUpperCase();
      updateCtryLabel();
      if(box.value.trim()) startSearch(); else render();
    }catch(e){}
  });
}
/* ── 搜索增强（task-28）：运行时派生匹配层 + 拼音懒加载 ──────────────────────
   在已下载的 IDX 上零新增下载派生 exact/连写 Map、前缀排序数组、CJK bigram、
   拉丁 trigram；拼音/首字母用 data/idx/pinyin.json（懒加载）。?legacy=1 不启用。
   collectHits() 与旧线性扫描共享同一套 addHit/tier/排序，保证候选集/碰撞/国家
   视图语义不变；派生层构建失败时自动退回旧路径。基准见 reports/search-engine-v2.md */
function searchLayersBuildLight(){
  try{
    const exact = new Map(), compact = new Map(), sorted = new Array(IDX.length);
    for(let i=0;i<IDX.length;i++){
      const k = IDX[i].k;
      let a = exact.get(k); if(!a){ a = []; exact.set(k, a); } a.push(i);
      const kc = k.replace(/ /g,'');
      if(kc !== k){ let b = compact.get(kc); if(!b){ b = []; compact.set(kc, b); } b.push(i); }
      sorted[i] = i;
    }
    sorted.sort((a,b)=> IDX[a].k < IDX[b].k ? -1 : IDX[a].k > IDX[b].k ? 1 : 0);
    SEARCH_LAYERS = {light:{exact: exact, compact: compact, sorted: sorted}, heavy: null};
  }catch(err){
    SEARCH_LAYERS = null;
    if(window.console && console.warn) console.warn('search layers (light) unavailable', err);
  }
}
function searchLayersBuildHeavy(){
  if(!SEARCH_LAYERS || SEARCH_LAYERS.heavy) return;
  try{
    const bigram = new Map(), trigram = new Map();
    const addTo = (m,k,id) => { let a = m.get(k); if(!a){ a = []; m.set(k, a); } a.push(id); };
    for(let i=0;i<IDX.length;i++){
      const k = IDX[i].k;
      // bigram：任何含汉字的键（CJK 查询的 contains 预筛）
      if(/[\u3400-\u9fff]/.test(k)){
        for(const run of k.match(/[\u3400-\u9fff]+/g) || []){
          if(run.length === 1) addTo(bigram, run, i);
          for(let j=0;j+1<run.length;j++) addTo(bigram, run.slice(j,j+2), i);
        }
      }
      // trigram：任何含拉丁字母/数字的键（含「格华止 glucophage」这类中拉混合名，
      // 旧 contains 用它做拉丁子串命中；只建纯拉丁会漏掉它们）
      if(k.length >= 4 && /[a-z0-9]/.test(k)){
        const t = ' ' + k.replace(/\s+/g,' ') + ' ';
        for(let j=0;j+3<=t.length;j++) addTo(trigram, t.slice(j,j+3), i);
      }
    }
    SEARCH_LAYERS.heavy = {bigram: bigram, trigram: trigram};
  }catch(err){
    if(window.console && console.warn) console.warn('search layers (heavy) unavailable', err);
  }
}
function searchLayersScheduleHeavy(){
  const run = () => searchLayersBuildHeavy();
  try{ setTimeout(run, 0); }catch(e){ /* ignore */ }
}
function pinyinFetch(){
  if(PY_MAP) return Promise.resolve(true);
  if(PY_P) return PY_P;
  PY_P = fetch(BASE + 'data/idx/pinyin.json').then(r=>{
    if(!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(d=>{
    const m = new Map();
    for(const pair of (d && d.tokens) || []) m.set(pair[0], pair[1]);
    PY_MAP = m;
    return true;
  }).catch(err=>{
    PY_P = null;
    if(window.console && console.warn) console.warn('pinyin table unavailable', err);
    return false;
  });
  return PY_P;
}
// 候选枚举：返回 Map(entryIndex -> 匹配档位)；未就绪/不需要派生时返回 null。
function layerCandidates(nq){
  const L = SEARCH_LAYERS;
  if(!L || !L.light || !nq) return null;
  const out = new Map();
  const ex = L.light.exact.get(nq);
  if(ex) for(const id of ex) out.set(id, 'exact');
  const kc = nq.replace(/ /g,'');
  const cp = L.light.compact.get(kc);
  if(cp) for(const id of cp) if(!out.has(id)) out.set(id, 'compact');
  const sorted = L.light.sorted;
  let lo = 0, hi = sorted.length;
  while(lo < hi){ const mid = (lo+hi) >> 1; if(IDX[sorted[mid]].k < nq) lo = mid+1; else hi = mid; }
  let nPre = 0;
  for(let i=lo;i<sorted.length && nPre<2000;i++){
    const k = IDX[sorted[i]].k;
    if(k.indexOf(nq) !== 0) break;
    nPre++;
    if(!out.has(sorted[i])) out.set(sorted[i], 'prefix');
  }
  const H = L.heavy;
  if(!H) return out;
  const cjk = /[\u4e00-\u9fff]/.test(nq);
  const minSub = cjk ? 2 : 4;
  if(nq.length >= minSub){
    if(cjk){
      const gramSet = new Set();
      for(const run of nq.match(/[\u3400-\u9fff]+/g) || []){
        if(run.length === 1) gramSet.add(run);
        for(let j=0;j+1<run.length;j++) gramSet.add(run.slice(j,j+2));
      }
      const cnt = new Map();
      for(const g of gramSet){
        const ids = H.bigram.get(g);
        if(!ids) continue;
        for(const id of ids) cnt.set(id, (cnt.get(id) || 0) + 1);
      }
      const need = Math.max(1, Math.min(2, gramSet.size));
      for(const pair of cnt){
        if(pair[1] >= need && !out.has(pair[0]) && IDX[pair[0]].k.indexOf(nq) >= 0) out.set(pair[0], 'contains');
      }
    }else{
      const t = ' ' + nq.replace(/\s+/g,' ') + ' ';
      const grams = [];
      for(let j=0;j+3<=t.length;j++) grams.push(t.slice(j,j+3));
      const cnt = new Map();
      for(const g of new Set(grams)){
        const ids = H.trigram.get(g);
        if(!ids) continue;
        for(const id of ids) cnt.set(id, (cnt.get(id) || 0) + 1);
      }
      const need = Math.max(1, grams.length - 1);
      for(const pair of cnt){
        if(pair[1] >= need && !out.has(pair[0]) && IDX[pair[0]].k.indexOf(nq) >= 0) out.set(pair[0], 'contains');
      }
    }
  }
  // 已有确定命中（exact/连写/前缀/包含）时不再做模糊/拼音候选：与旧「两遍扫描」语义一致。
  if(out.size) return out;
  // CJK 模糊候选：bigram 交集里“重叠高但不是子串”的名字；第二遍仍用 tier() 的
  // Levenshtein 阈值复核（旧实现第二遍扫全表，这里只缩小候选集）。
  if(cjk && nq.length >= 4){
    const gramSet2 = new Set();
    for(const run of nq.match(/[\u3400-\u9fff]+/g) || []){
      if(run.length === 1) gramSet2.add(run);
      for(let j=0;j+1<run.length;j++) gramSet2.add(run.slice(j,j+2));
    }
    const cnt2 = new Map();
    for(const g of gramSet2){
      const ids = H.bigram.get(g);
      if(!ids) continue;
      for(const id of ids) cnt2.set(id, (cnt2.get(id) || 0) + 1);
    }
    const pool = [];
    for(const pair of cnt2) if(!out.has(pair[0])) pool.push(pair);
    pool.sort((a,b)=> b[1] - a[1]);
    for(let r=0;r<pool.length && r<1000;r++) out.set(pool[r][0], 'fuzzy');
    if(out.size) return out;
  }
  // 拼音/首字母：查询串本身即 token（tainuo -> j:tainuo，tn -> i:tn）
  if(PY_MAP && /^[a-z0-9]+$/.test(nq)){
    const pyIds = PY_MAP.get('j:' + nq) || PY_MAP.get('i:' + nq) || PY_MAP.get('s:' + nq);
    if(pyIds) for(const id of pyIds) if(!out.has(id)) out.set(id, 'pinyin');
  }
  if(out.size) return out;
  // 拉丁 typo：trigram 短名单 + 编辑距离（阈值与 tier() 的 fuzzy 一致）
  if(/^[a-z0-9 .&+\/-]+$/.test(nq) && nq.length >= 4){
    const t = ' ' + nq.replace(/\s+/g,' ') + ' ';
    const grams = [];
    for(let j=0;j+3<=t.length;j++) grams.push(t.slice(j,j+3));
    const cnt = new Map();
    for(const g of new Set(grams)){
      const ids = H.trigram.get(g);
      if(!ids) continue;
      for(const id of ids) cnt.set(id, (cnt.get(id) || 0) + 1);
    }
    const shortlist = [];
    for(const pair of cnt) shortlist.push(pair);
    shortlist.sort((a,b)=> b[1] - a[1]);
    const limit = nq.length >= 9 ? 3 : 2;
    for(let r=0;r<shortlist.length && r<2000;r++){
      const id = shortlist[r][0];
      if(out.has(id)) continue;
      const k = IDX[id].k;
      if(Math.abs(k.length - nq.length) <= 3 && lev(nq, k) <= limit) out.set(id, 'fuzzy');
    }
  }
  return out;
}
// 统一匹配：派生路径与旧线性扫描共用 addHit / tier / 两遍语义。
function collectHits(nq, st, nicks, nickSids, onlyUnmapped, c){
  const hits = [], seen = new Set();
  const addHit = (e, t) => {
    if(seen.has(e.k)) return;
    seen.add(e.k);
    let score = 0.55*t[1] + 0.20*(c && e.c.includes(c) ? 1 : 0.5);
    score += 0.15*(st && e.s.some(x=>x.toLowerCase().startsWith(st[0]+' ')) ? 1 : 0.5);
    score += 0.05;
    hits.push([score, t[0], e]);
  };
  let fuzzyUsed = false;
  const cand = (!LEGACY && !onlyUnmapped && nicks.length === 0
    && SEARCH_LAYERS && SEARCH_LAYERS.heavy) ? layerCandidates(nq) : null;
  if(cand){
    // 候选按 IDX 下标升序处理：与旧全表扫描的插入顺序一致，保证同分命中的稳定排序不变。
    const ids = [];
    for(const pair of cand) ids.push(pair[0]);
    ids.sort((a,b)=> a-b);
    const fuzzyIds = [];
    for(const id of ids){
      const kind = cand.get(id);
      if(kind === 'fuzzy'){ fuzzyIds.push(id); continue; }
      const e = IDX[id];
      const t = kind === 'pinyin' ? ['pinyin', 0.90]
        : (tier(nq, e.k) || (kind === 'contains' ? ['contains', 0.70] : null));
      if(!t || t[0] === 'fuzzy') continue;
      addHit(e, t);
    }
    if(hits.length === 0 && fuzzyIds.length){
      for(const id of fuzzyIds){
        const tt = tier(nq, IDX[id].k);
        if(!tt || tt[0] !== 'fuzzy') continue;   // 与旧第二遍的 tier()==='fuzzy' 过滤一致
        // 模糊档内按编辑距离细排：距离越近分越高，否则同分时会被高 n 的远邻顶到前面
        const d = lev(nq, IDX[id].k);
        const before = hits.length;
        addHit(IDX[id], ['fuzzy', Math.max(0.1, 1 - 0.12 * d)]);
        if(hits.length > before) fuzzyUsed = true;
      }
    }
  }else{
    // 回退路径：?legacy=1 / 派生层未就绪 / 昵称查询 —— 与旧实现逐行等价。
    for(const e of IDX){
      if(onlyUnmapped) continue;
      const subs = (e.x || '').split(' + ');
      const byNick = (e.v && nickSids.has(e.v)) ||
        nicks.some(a => a.i && subs.includes(a.i));
      const t = byNick ? ['nickname', 1.0] : tier(nq, e.k);
      if(!t || t[0]==='fuzzy') continue;
      addHit(e, t);
    }
    if(hits.length === 0 && nicks.length === 0){
      for(const e of IDX){
        const t = tier(nq, e.k);
        if(!t || t[0]!=='fuzzy') continue;
        const before = hits.length;
        addHit(e, t);
        if(hits.length > before) fuzzyUsed = true;
      }
    }
  }
  return {hits: hits, fuzzyUsed: fuzzyUsed};
}
/* ── 搜索增强 end ─────────────────────────────────────────────────────────── */
function render(){
  const q = box.value.trim();
  if(!q){ out.innerHTML=''; meta.textContent=''; syncURL('');
    const r0 = document.getElementById('report'); if(r0) r0.style.display='none'; return; }
  const [nameQ, st] = splitDose(q);
  const nq = norm(nameQ);
  const parsed = parseQuery(q);
  // 新一轮查询：重置分组/折叠/分页状态（「加载更多」「折叠」只在点击时增量重绘）
  RES_LIMIT = RES_PAGE;
  RES_EXPANDED = new Set();
  RES_GROUPS = null;
  scheduleSearchEvent(q);
  syncURL(q);
  const c = ctry.value;
  const nicks = aliasHits(nq);
  const confs = confHits(nq);
  const nickSids = new Set(nicks.map(a=>a.v).filter(Boolean));
  // 只有「没有对应成分」的叫法（如海洛因的 Hammer）时，不要再拿商品名做包含匹配：
  // 否则会倒出一堆名字里刚好有 hammer 的保健品，和这个词没关系。
  const onlyUnmapped = nicks.length > 0 && nicks.every(a => !a.v);
  const matched = collectHits(nq, st, nicks, nickSids, onlyUnmapped, c);
  const hits = matched.hits;
  const fuzzyUsed = matched.fuzzyUsed;
  // 拼音兜底：拉丁查询零命中且拼音表未加载 → 懒加载 data/idx/pinyin.json 后重跑一次。
  if(!hits.length && !nicks.length && !LEGACY && SEARCH_LAYERS
     && /^[a-z0-9 ]{2,}$/.test(nq) && !PY_MAP){
    pinyinFetch().then(ok => { if(ok && box.value.trim() === q) render(); });
  }
  hits.sort((a,b)=> b[0]-a[0] || (a[2].q?1:0)-(b[2].q?1:0) ||
                     b[2].n-a[2].n || a[2].d.length-b[2].d.length);
  // UI P0 ④：不再 40 行/80 行硬截断——保留至多 200 条候选交给前端
  // 「成分聚合 + 品牌折叠 + 加载更多」分页展示（默认每页 25 行可见品牌）。
  const shown = hits.slice(0, 200);
  // 选了国家 = 「这个药在那个国家叫什么」，不是「只显示那个国家的搜索命中」。
  // 先用查询词定位成分（不受国家限制），再把这个成分在目标国的商品名列出来。
  let display = shown;
  let countryMiss = false;    // 选了国家但该国没有任何该成分产品（不再静默回退到各国列表）
  let countryView = false;    // 当前展示的是「该国该成分的商品名」
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
      if(inCountry.length){
        display = inCountry.slice(0,200).map(e => [0, 'country', e]);
        countryView = true;
      } else {
        display = [];
        countryMiss = true;
      }
    }catch(err){
      console.error('country resolve failed', err);
    }
  }
  const T = window.T || (k=>k);
  // 解析条：匹配方式取首条命中/别名的档位（精确 / 连写 / 前缀 / 包含 / 模糊 / 别名）
  let matchKey = 'none';
  if(nicks.length) matchKey = 'nickname';
  else if(hits.length) matchKey = fuzzyUsed ? 'fuzzy' : hits[0][1];
  let matchLabel = T('parse.match.' + matchKey);
  if(countryView) matchLabel += ' · ' + T('parse.match.country');
  if(countryMiss){
    meta.textContent = `${T('res.none')} — ${T('res.notin')}. ${T('res.caveat')}.`;
  } else if(!hits.length && nicks.length){
    meta.textContent = `${nicks.length} ${T('res.alias')} · ${T('res.alias_no_products')}`;
  } else {
    meta.textContent = hits.length
      ? (fuzzyUsed
          ? `${T('res.fuzzy')} · ${hits.length} ${T(nicks.length ? 'res.brands' : 'res.matched')}`
          : `${hits.length} ${T(nicks.length ? 'res.brands' : 'res.matched')}`)
      : (c ? `${T('res.none')} — ${T('res.notin')}. ${T('res.caveat')}.`
           : `${T('res.none')} — ${T('res.caveat')}.`);
  }
  // 国家无匹配：显式提示 + 「看成分卡」/「换国家」，不再静默回退到各国列表。
  let countryMissHTML = '';
  if(countryMiss){
    const sids = [];
    for(const [, , e] of hits){
      for(const s of ((e.vs && e.vs.length) ? e.vs : [e.v])){
        if(s && sids.indexOf(s) < 0) sids.push(s);
        if(sids.length >= 3) break;
      }
      if(sids.length >= 3) break;
    }
    const cards = sids.map(s =>
      `<a href="${BASE}drug/${encodeURIComponent(s)}.html">${esc(T('country.open_card'))}</a>`).join('');
    countryMissHTML = `<div class="notice warnbox countrymiss"><b>${esc(T('country.missing'))}</b>`
      + ` ${esc(T('country.missing_note'))}`
      + `<div class="cm-actions">${cards}`
      + `<button type="button" data-clearcountry="1">${esc(T('country.change'))}</button></div></div>`;
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
  // 主结果：按成分聚合；同成分多品牌折叠（默认显示前 2 个品牌），
  // 超过 RES_PAGE 行时用「加载更多」分页，不再一刀切 40 行/80 行。
  let resHTML = '';
  if(!countryMiss && display.length){
    RES_GROUPS = groupByIngredient(display);
    resHTML = `<div id="reswrap">${resultsTableHTML(T2)}</div>`;
  }

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

  out.innerHTML = parseBarHTML(parsed, matchLabel) + confHTML + nickHTML + warnHTML
    + countryMissHTML + resHTML + sameHTML + extraHTML;
  // 产品层没命中时，再去 ARTG 名称层找「登记存在、成分未收录」的条目；
  // 选了澳洲但澳洲产品为空时同样触发（很多 listed OTC 只有 ARTG 名字）。
  const hasAU = display.some(x => ((x[2].c) || []).includes('AU'));
  if((!display.length && !countryMiss) || (c === 'AU' && !hasAU)){
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
  // issue 模板的字段名走 i18n，避免 es 用户在报告表单里看到中英混排。
  const body = [
    '**' + Tr('report.field_query') + '**: ' + (q || ''),
    '**' + Tr('report.field_page') + '**: ' + location.href,
    '**' + Tr('report.field_expected') + '**: ',
    '**' + Tr('report.field_actual') + '**: ',
    '**' + Tr('report.field_pack') + '**: ',
    ''
  ].join('\n');
  return 'REPORT_REPO_PLACEHOLDER' + '/issues/new?labels=data-error&template=data-error.yml'
    + '&title=' + encodeURIComponent(Tr('report.issue_title') + (q || ''))
    + '&body=' + encodeURIComponent(body);
}
// ── P0 索引懒加载 ──────────────────────────────────────────────────
// 页面加载时不请求完整索引；首次输入 / 聚焦搜索框 / 点示例按钮，或带 ?q= 深链
// 进来时才 loadIndex()。加载失败给出提示与「重试」按钮（不做静默失败）。
// ?legacy=1 一键回滚成旧行为（页面加载即拉全量索引）。
const LEGACY = new URLSearchParams(location.search).get('legacy') === '1';
// i18n.js 先于本脚本执行（<head>），window.T 可用；保留降级到原键名。
function Tr(k){ return (window.T || function(x){ return x; })(k); }
const hintEl = document.getElementById('loadhint');
const HINT_IDLE = Tr('home.hint_idle');
const HINT_LOADING = Tr('home.hint_loading');
function setHint(html, show){
  if(!hintEl) return;
  // 一旦由脚本接管提示文案，就摘掉 data-i18n，避免 i18n.js 的 apply() 把
  // 「正在加载…」又覆盖回静态 idle 文案。
  if(hintEl.removeAttribute) hintEl.removeAttribute('data-i18n');
  hintEl.innerHTML = html || '';
  hintEl.style.display = (show === false || !html) ? 'none' : '';
}
// ── P1 列式 + 字典编码核心（data/idx/core.json，见 reports/index-p1-impl.md）──
// 构建把 index.json 编成「版本头 + 列式数组 + 字符串字典」；这里解码回与旧
// index.json 完全同构（同字段、同顺序）的 IDX 数组，render() 以下逻辑一行不改。
//   cols[f] = {d:[字典值...], i:[每行的字典下标...]}  字典列
//   cols[f] = [值...]                                普通列
//   d 与 k 只差 ASCII 大小写时 cols.d 存 ""，cols.dp 存大小写位置模式（'0-2,5'）；
//   q=1 的条目单独用稀疏下标数组存。
function applyCase(k, pat){
  const out = k.split('');
  for(const run of pat.split(',')){
    const p = run.split('-'), lo = +p[0], hi = p.length > 1 ? +p[1] : lo;
    for(let i = lo; i <= hi; i++) out[i] = out[i].toUpperCase();
  }
  return out.join('');
}
function decodeCore(c){
  if(!c || !Array.isArray(c.cols && c.cols.k) || typeof c.n !== 'number') throw new Error('bad core');
  const n = c.n, C = c.cols, out = new Array(n);
  const kcol = C.k, dcol = C.d || [], dpcol = C.dp || [];
  for(let i = 0; i < n; i++){
    const k = kcol[i];
    let d = dcol[i];
    if(!d) d = dpcol[i] ? applyCase(k, dpcol[i]) : k;
    out[i] = {k: k, d: d};
  }
  for(const f in C){
    if(f === 'k' || f === 'd' || f === 'dp') continue;
    const col = C[f];
    if(!col) continue;
    if(col.d && col.i){                       // 字典列
      const dict = col.d, idx = col.i;
      for(let i = 0; i < n; i++) out[i][f] = dict[idx[i]];
    } else if(Array.isArray(col)){            // 普通列
      for(let i = 0; i < n; i++) out[i][f] = col[i];
    }
  }
  for(const i of (c.q || [])) out[i].q = 1;
  return out;
}
function fetchJSON(url){
  return fetch(url).then(r=>{ if(!r.ok) throw new Error('HTTP '+r.status+' '+url); return r.json(); });
}
function loadMainIndex(){
  // ?legacy=1 一键回滚：只走旧的 data/index.json，不碰 data/idx/core.json。
  if(LEGACY) return fetchJSON(BASE + 'data/index.json');
  return fetchJSON(BASE + 'data/idx/core.json').then(decodeCore).catch(err=>{
    // 核心文件 404 / 网络失败 / 解码异常（例如灰度期数据没跟上）→ 自动回退旧全量索引。
    if(window.console && console.warn) console.warn('core index unavailable, fallback to index.json', err);
    return fetchJSON(BASE + 'data/index.json');
  });
}
function loadIndex(){
  if(IDX_READY) return Promise.resolve(true);
  if(IDX_P) return IDX_P;
  if(!LEGACY) setHint(HINT_LOADING);
  IDX_P = Promise.all([
    loadMainIndex(),
    fetch(BASE + 'data/aliases.json').then(r=>r.json()).catch(()=>[]),
    fetch(BASE + 'data/confused.json').then(r=>r.json()).catch(()=>[])
  ]).then(([d,a,c])=>{
    IDX=d||[]; NICKS=a||[]; CONF=c||[]; IDX_READY=true;
    setHint('');
    // 搜索增强（task-28）：索引到位后先派生轻量层（exact/前缀，~0.2s），
    // 重层（bigram/trigram）放到下一轮事件循环，避免阻塞首个结果渲染。
    if(!LEGACY){
      searchLayersBuildLight();
      searchLayersScheduleHeavy();
    }
    // 用户可能在索引加载期间已经输入了 ≥2 字：加载完成后补算自动完成。
    // （?q= 深链不经过 input 事件，不会自动弹建议列表遮挡结果。）
    if(AC_WANT) acUpdate();
    return true;
  }).catch(err=>{
    // 失败后清掉缓存的 Promise，允许点「重试」重新发起。
    IDX_P = null;
    setHint(HINT_IDLE);
    out.innerHTML = '<div class="notice">' + esc(Tr('error.index_failed')) + ' '
      + esc(Tr('error.local_file'))
      + '<br>' + esc(String((err && err.message) || err || ''))
      + '<br><button type="button" data-retry="1">' + esc(Tr('error.retry')) + '</button></div>';
    return false;
  });
  return IDX_P;
}
function startSearch(){
  if(IDX_READY){ render(); return; }
  loadIndex().then(ok => { if(ok) render(); });
}
// 结果区事件委托：失败重试 / 加载更多 / 品牌折叠展开 / 换国家。
out.addEventListener('click', ev => {
  const t = ev.target;
  if(!t || !t.closest) return;
  if(t.closest('[data-retry]')){
    out.innerHTML = '';
    loadIndex().then(ok => { if(ok) render(); });
    return;
  }
  if(t.closest('[data-loadmore]')){
    RES_LIMIT += RES_PAGE;
    paintResultsOnly();
    return;
  }
  const fold = t.closest('[data-gi]');
  if(fold){
    const gi = +fold.getAttribute('data-gi');
    if(fold.getAttribute('data-fold') === '1') RES_EXPANDED.add(gi);
    else RES_EXPANDED.delete(gi);
    paintResultsOnly();
    return;
  }
  if(t.closest('[data-clearcountry]')){
    ctry.value = '';
    updateCtryLabel();
    render();
  }
});
// 点击事件：结果里的品牌/成分链接、报告入口、更新日志（只记事件，不记用户）。
document.addEventListener('click', ev => {
  const a = ev.target && ev.target.closest ? ev.target.closest('a') : null;
  if(!a) return;
  const href = a.getAttribute('href') || '';
  if(href.indexOf('/issues/new') >= 0){ gcEvent('click-report'); return; }
  if(href.indexOf('/name/') >= 0 || href.indexOf('/drug/') >= 0){ gcEvent('click-result'); return; }
  if(href.indexOf('whats-new') >= 0){ gcEvent('click-whatsnew'); return; }
});
box.addEventListener('input', ()=>{ startSearch(); acUpdate(); });
ctry.addEventListener('change', ()=>{
  gcEvent('country-' + (ctry.value || 'ALL'));
  updateCtryLabel();
  acClose();
  startSearch();
});
document.querySelectorAll('[data-q]').forEach(b=>b.addEventListener('click',()=>{
  box.value=b.dataset.q; acClose(); startSearch(); box.focus();
}));
// 自动完成键盘操作：↑↓ 移动、回车选中、Esc 关闭；点击在 #ac 上委托。
box.addEventListener('keydown', ev => {
  const open = !!(acEl && acEl.classList.contains('open') && AC_ITEMS.length);
  if(ev.key === 'ArrowDown'){
    if(!open) return;
    ev.preventDefault();
    AC_I = (AC_I + 1) % AC_ITEMS.length;
    acPaint();
  } else if(ev.key === 'ArrowUp'){
    if(!open) return;
    ev.preventDefault();
    AC_I = (AC_I - 1 + AC_ITEMS.length) % AC_ITEMS.length;
    acPaint();
  } else if(ev.key === 'Enter'){
    if(open && AC_I >= 0){ ev.preventDefault(); acSelect(AC_I); }
    else { acClose(); }
  } else if(ev.key === 'Escape'){
    acClose();
  }
});
if(acEl){
  // mousedown 阻止默认，避免输入框先失焦导致点击落空。
  acEl.addEventListener('mousedown', ev => { ev.preventDefault(); });
  acEl.addEventListener('click', ev => {
    const t = ev.target && ev.target.closest ? ev.target.closest('[data-i]') : null;
    if(!t) return;
    acSelect(+t.getAttribute('data-i'));
  });
}
document.addEventListener('click', ev => {
  if(!acEl || !acEl.classList.contains('open')) return;
  const t = ev.target;
  if(t === box || (t.closest && t.closest('#ac'))) return;
  acClose();
});
// 聚焦搜索框就先预取索引：等用户敲键时 6 MB 已经在路上。
box.addEventListener('focus', ()=>{ if(!IDX_READY) loadIndex(); });
const initial = new URLSearchParams(location.search).get('q');
if(initial){ box.value = initial; }
const ctry0 = new URLSearchParams(location.search).get('country');
if(ctry0 && ctry){ ctry.value = ctry0.toUpperCase(); }
updateCtryLabel();   // 「看这个药在哪个国家叫什么」标签随 URL/选择初始化
if(LEGACY){
  // 回滚开关：?legacy=1 = 旧行为，页面一加载就拉全量索引。
  setHint('');
  out.innerHTML = '<div class="sub">' + esc(Tr('home.loading')) + '</div>';
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
        # hreflang 必须带 GitHub Pages 的项目子路径（线上是 /drug-brand-crossref/），
        # 写 "/es/" 会指到域名根（404）。SITE_URL 已含末尾斜杠。
        alt = ("\n".join(
            f'<link rel="alternate" hreflang="{code}" href="{SITE_URL}{path}">'
            for code, _l, path in LANGS
        ) + f'\n<link rel="alternate" hreflang="x-default" href="{SITE_URL}">')
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · Medicine Brand Cross-Reference</title>{alt}
<link rel="stylesheet" href="{prefix}assets/style.css?v={BUILD_V}">
<script src="{prefix}assets/i18n.js?v={BUILD_V}"></script>{GC_TAG}</head>
<body>
<header><div class="wrap">
  <a class="logo" href="{prefix}index.html">Medicine Brand Cross-Reference
    <span class="logo-zh">药品商品名跨国定位</span></a>
  <nav><a href="{prefix}index.html" data-i18n="nav.search">Search</a>
    <a href="{prefix}confused.html" data-i18n="nav.confused">Confused names</a>
    <a href="{prefix}warn.html" data-i18n="nav.warn">Warnings</a>
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
    body = f"""<h1 data-i18n="whatsnew.title">What's new</h1>
<p class="sub" data-i18n-html="whatsnew.intro">Every release ships with a short summary. Old versions are backfilled from git tags; the full history lives in
<a href="{REPORT_REPO}/blob/main/CHANGELOG.md" target="_blank" rel="noopener">CHANGELOG.md</a>.</p>
<div class="notice" data-i18n="whatsnew.lang_note">Release notes are written in Chinese (the project language); the site UI is available in English, Spanish and Chinese.</div>
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


# 药品身份页「状态」列的受控词：状态词与说明都走 I18N（data-i18n），
# HTML 里的英文默认文案供无 JS / 首帧使用，i18n.js 再按语言替换。
STATUS_WORDS = ("active", "discontinued", "withdrawn", "unknown")
STATUS_NOTES = {
    "discontinued": "drug.status_note.discontinued",
    "withdrawn": "drug.status_note.withdrawn",
    "unknown": "drug.status_note.unknown",
}
STATUS_NOTES_EN = {
    "discontinued": "expired",
    "withdrawn": "market authorisation withdrawn",
    "unknown": "validity unknown",
}


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

    # /warn：成分页顶部摘要只取已发布警示，按严重度排序（high→medium→info）。
    warnings_by_sub: dict[str, list[dict]] = defaultdict(list)
    for r in db.execute(
        """SELECT * FROM dose_warning WHERE status = 'published'
           ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                    warning_id"""
    ):
        row = dict(r)
        seen_sids = set()
        for key in ("substance_id", "related_substance_id"):
            sid2 = row.get(key)
            if sid2 and sid2 not in seen_sids:
                seen_sids.add(sid2)
                warnings_by_sub[sid2].append(row)
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
                # 受控词走 data-i18n：en 默认文案在 HTML 里，i18n.js 按所选语言替换。
                name = esc(brand) if brand else (
                    '<span class="meta" data-i18n="drug.no_brand">(no brand name)</span>')
                st_html = esc(st) if st else (
                    '<span class="meta" data-i18n="drug.nostrength">not disclosed</span>')
                status_html = (
                    f'<span data-i18n="drug.status.{status}">{esc(status)}</span>'
                    if status in STATUS_WORDS else esc(status))
                note = STATUS_NOTES.get(status)
                if note:
                    note_en = STATUS_NOTES_EN[status]
                    status_html += (f' <em>(<span data-i18n="drug.status_note.{status}">'
                                    f'{note_en}</span>)</em>')
                lis.append(f"<tr><td>{name}</td><td>{st_html}</td>"
                           f"<td>{esc(rel) if rel != 'none' else '—'}</td>"
                           f"<td>{status_html}</td></tr>")
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
            nick_line = (f'<p class="sub"><span data-i18n="drug.also_called">Also called:</span> '
                         f'{also} <span class="tag" data-i18n="nick.tag">nickname</span></p>')
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
        warn_line = _drug_warn_html(warnings_by_sub.get(sid, []))
        body = f"""<h1>{esc(inn_zh) or esc(inn_en)} <span class="meta">{esc(inn_en)}</span></h1>
<p class="sub">ATC {esc(atc) or '—'} · <span data-i18n="drug.sid">Substance ID</span>
<code>{esc(sid)}</code></p>
{warn_line}
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
<div class="searchwrap">
<input id="q" data-ph="home.ph" placeholder="Brand name / generic name / nickname / a line from the pack" autocomplete="off" aria-autocomplete="list" aria-controls="ac" aria-expanded="false">
<div id="ac" role="listbox" aria-label="Suggestions"></div>
</div>
<div class="row">
  <label class="sel-label" for="country" id="ctrylabel" data-i18n="home.country_label">See what this medicine is called in:</label>
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
<p class="sub" id="loadhint" data-i18n="home.hint_idle">First search needs to load the index (~6 MB gzipped; cached after the first time) — start typing, focus the search box, or pick a sample.</p>
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
    """About：正文按块走 data-i18n-html（三语字典，占位符已在 main() 里替换成当前库统计）。

    许可/署名段为 reports/license-audit.md §4 的三语并列原文（LICENCE_HTML），
    ATC 覆盖用双口径（全部 substance / 药物实体 inn_drug），均为构建期动态计算。
    """
    T = I18N["en"]
    parts = [f'<h1 data-i18n="about.title">{esc(T["about.title"])}</h1>']
    for key in ("about.lead", "about.rules", "about.nick", "about.terms", "about.sources"):
        parts.append(f'<div data-i18n-html="{key}">{T[key]}</div>')
    parts.append(LICENCE_HTML)
    for key in ("about.samename", "about.gaps"):
        parts.append(f'<div data-i18n-html="{key}">{T[key]}</div>')
    if GOATCOUNTER_CODE:
        parts.append(f'<div data-i18n-html="about.analytics">{T["about.analytics"]}</div>')
    parts.append(f'<div data-i18n-html="about.stats">{T["about.stats"]}</div>')
    body = "\n".join(parts)
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
<div class="tablewrap"><table><thead><tr>
  <th data-i18n="conf.pair">Pair</th><th></th><th data-i18n="conf.tml">Tall-man spelling</th>
</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>
<p class="sub" data-i18n-html="conf.source_note">{I18N['en']['conf.source_note']}</p>"""
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
<script src="{SITE_URL}assets/i18n.js?v={BUILD_V}"></script>
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
<h1 data-i18n="notfound.title">Page not found</h1>
<p data-i18n="notfound.p1">This address has no page. It may be an old link, a typo, or a renamed entry.</p>
<p data-i18n="notfound.p2">Go back to the home page and type a medicine name (brand, generic or nickname).</p>
<p class="links"><a href="{SITE_URL}" data-i18n="notfound.search">Search</a>
<a href="{SITE_URL}about.html" data-i18n="notfound.about">About</a>
<a href="{SITE_URL}confused.html" data-i18n="notfound.confused">Confused names</a>
<a href="{SITE_URL}whats-new.html" data-i18n="notfound.whatsnew">What's new</a></p>
<p style="margin-top:28px;font-size:13px;color:#7a857e" data-i18n-html="notfound.report">If an internal link is broken, tell us on
<a href="{REPORT_REPO}/issues/new?labels=data-error&amp;template=data-error.yml">GitHub</a>.</p>
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


# ── P1 索引核心：列式 + 字典编码 ─────────────────────────────────────
# 目标：把 34.8 MB 的 data/index.json 编成 data/idx/core.json，客户端
#       decodeCore() 解码回与 index.json 完全同构（同字段、同顺序）的 IDX 数组，
#       render() 以下逻辑一行不改。旧 index.json 继续双写：?legacy=1 或核心
#       加载/解码失败时自动回退。设计与体积对比见 reports/index-p1-impl.md。
#
# 编码格式（v1）：
#   {"v":1,"n":条数,
#    "cols":{
#      "k":[str...],                     检索键（原样，不排序——保持 IDX 原有顺序，
#                                        下游 inCountry/同成分列表的顺序才不变）
#      "d":[str...],  "dp":[str...],     d 与 k 只差 ASCII 大小写时 d 存 ""、
#                                        dp 存大小写位置模式（"0-2,5" 表示把这些
#                                        位 toUpperCase 后还原 d）；否则 d 存原文
#      "c":{"d":[值...],"i":[下标...]}, 字典列：字符串字典 + 每行字典下标
#      ...（x/s/l/v/vs/g/gn/m 同字典列；c/s/vs 的值是数组，先 JSON 化再字典化）
#      "n":[int...], "mn":[int...], "u":[str...]   普通列
#    },
#    "q":[稀疏下标...]}                   q=1 的行下标（163 条，单独稀疏存）
#   f（剂型）客户端 0 处引用，直接丢弃（app.js 只用 k/d/c/x/s/l/n/v/vs/u/g/gn/m/mn/q）。
CORE_DICT_COLS = ("c", "x", "s", "l", "v", "vs", "g", "gn", "m")
CORE_ARRAY_COLS = ("c", "s", "vs")     # 值是数组：先 JSON 化再进字典


def _d_case_pattern(d: str, k: str) -> str | None:
    """d 与 k 只差 ASCII 大小写时返回大小写位置模式（'0' / '0-2,5'），否则 None。

    模式里 'a-b' 是闭区间：把 k 的第 a..b 个字符 toUpperCase 后即得 d。
    只处理 ASCII：非 ASCII 的大小写映射（ß→SS、İ→i̇ 等）Python 与 JS 行为
    未必一致，这类条目一律让 d 存完整原文，解码端不做映射。
    """
    if len(d) != len(k):
        return None
    runs: list[str] = []
    i = 0
    while i < len(k):
        if d[i] == k[i]:
            i += 1
            continue
        if ord(k[i]) > 127 or d[i] != k[i].upper():
            return None
        j = i
        while (j + 1 < len(k) and d[j + 1] != k[j + 1]
               and ord(k[j + 1]) < 128 and d[j + 1] == k[j + 1].upper()):
            j += 1
        runs.append(f"{i}-{j}" if j > i else str(i))
        i = j + 1
    return ",".join(runs)


def encode_core(entries) -> dict:
    """entries（load_index 的结果）→ 列式 + 字典编码的 core 对象。"""
    n = len(entries)
    d_col: list[str] = []
    dp_col: list[str] = []
    for e in entries:
        d, k = e["d"], e["k"]
        if d == k:
            d_col.append("")
            dp_col.append("")
            continue
        pat = _d_case_pattern(d, k)
        if pat is None:
            d_col.append(d)          # 大小写差异超出 ASCII 规则：存完整 d
            dp_col.append("")
        else:
            d_col.append("")         # 可由 k + 模式还原
            dp_col.append(pat)
    cols: dict[str, object] = {"k": [e["k"] for e in entries], "d": d_col, "dp": dp_col}
    for f in ("c", "x", "s", "l", "n", "v", "vs", "u", "g", "gn", "m", "mn"):
        vals = [e.get(f) for e in entries]
        if f in CORE_ARRAY_COLS:
            # 数组先序列化再字典化：客户端解码时把字典值直接给出（数组引用共享，
            # render 只读不写），不需要逐行 JSON.parse。
            raw = [json.dumps(v, ensure_ascii=False, separators=(",", ":")) for v in vals]
            uniq = list(dict.fromkeys(raw))
            pos = {u: i for i, u in enumerate(uniq)}
            cols[f] = {"d": [json.loads(u) for u in uniq],
                       "i": [pos[u] for u in raw]}
        elif f in CORE_DICT_COLS:
            uniq = list(dict.fromkeys(vals))
            pos = {u: i for i, u in enumerate(uniq)}
            cols[f] = {"d": uniq, "i": [pos[v] for v in vals]}
        else:
            cols[f] = vals
    return {"v": 1, "n": n, "cols": cols,
            "q": [i for i, e in enumerate(entries) if e.get("q")]}



# ── 搜索增强（task-28）：拼音字符表 + 拼音/首字母 token 编码 ──────────────────
# 1,582 个字 = 索引/别名里出现过的全部汉字（pinyin-pro 3.29.5，toneType=none，
# 取默认读音；多音字用默认读音即可，拼音只是 exact/prefix 之外的增量兜底路径）。
# 生成/校验方式见 reports/search-engine-v2.md；客户端不依赖拼音库：查询串本身就是
# token（tainuo -> j:tainuo，tn -> i:tn），只需按 token 精确查表。
_PINYIN_CHARS_TEXT = "䓬:zhuo 一:yi 丁:ding 七:qi 万:wan 三:san 上:shang 下:xia 不:bu 与:yu 专:zhuan 世:shi 丙:bing 业:ye 东:dong 丝:si 两:liang 严:yan 中:zhong 丰:feng 临:lin 丸:wan 丹:dan 为:wei 丽:li 乃:nai 久:jiu 之:zhi 乌:wu 乎:hu 乐:le 乙:yi 九:jiu 乱:luan 乳:ru 了:liao 予:yu 二:er 云:yun 五:wu 亚:ya 亢:kang 交:jiao 亦:yi 产:chan 京:jing 亭:ting 亮:liang 人:ren 亿:yi 仁:ren 今:jin 介:jie 仑:lun 仔:zai 仕:shi 他:ta 仙:xian 仟:qian 代:dai 令:ling 仪:yi 仲:zhong 价:jia 任:ren 伉:kang 伊:yi 伏:fu 伐:fa 休:xiu 众:zhong 优:you 伞:san 伟:wei 伤:shang 伦:lun 伪:wei 伯:bo 伲:ni 伴:ban 伶:ling 伸:shen 伽:jia 位:wei 低:di 佐:zuo 佑:you 体:ti 佛:fo 佩:pei 佰:bai 佳:jia 佶:ji 使:shi 侗:dong 供:gong 依:yi 侣:lü 侬:nong 便:bian 促:cu 俊:jun 保:bao 信:xin 俪:li 修:xiu 倍:bei 倡:chang 倩:qian 假:jia 停:ting 健:jian 催:cui 傲:ao 僖:xi 儒:ru 儿:er 允:yun 元:yuan 充:chong 兆:zhao 先:xian 光:guang 克:ke 免:mian 兔:tu 入:ru 全:quan 八:ba 公:gong 六:liu 兮:xi 兰:lan 关:guan 兴:xing 兵:bing 其:qi 典:dian 兹:zi 养:yang 内:nei 冉:ran 册:ce 再:zai 军:jun 农:nong 冠:guan 冬:dong 冰:bing 冲:chong 决:jue 冷:leng 冻:dong 净:jing 凌:ling 减:jian 凝:ning 凡:fan 凯:kai 出:chu 分:fen 切:qie 列:lie 则:ze 刚:gang 创:chuang 初:chu 利:li 别:bie 制:zhi 刹:cha 刺:ci 刻:ke 剂:ji 前:qian 剑:jian 力:li 功:gong 加:jia 动:dong 助:zhu 努:nu 劲:jin 劳:lao 勃:bo 勉:mian 勒:le 勤:qin 包:bao 化:hua 北:bei 匙:chi 匹:pi 区:qu 十:shi 千:qian 升:sheng 卉:hui 半:ban 华:hua 协:xie 卓:zhuo 单:dan 南:nan 博:bo 卜:bu 卟:bu 占:zhan 卡:ka 卢:lu 卤:lu 卫:wei 即:ji 卵:luan 卷:juan 厄:e 历:li 压:ya 原:yuan 去:qu 参:can 及:ji 友:you 双:shuang 反:fan 发:fa 叔:shu 取:qu 受:shou 变:bian 口:kou 古:gu 只:zhi 叮:ding 可:ke 台:tai 史:shi 右:you 叶:ye 号:hao 司:si 合:he 吉:ji 同:tong 名:ming 后:hou 吐:tu 吖:a 吗:ma 君:jun 吡:bi 吨:dun 吩:fen 含:han 启:qi 吲:yin 吸:xi 吻:wen 吾:wu 呋:fu 呗:bai 呤:ling 呫:tie 呱:gua 味:wei 呵:he 呼:hu 命:ming 咀:zui 和:he 咐:fu 咖:ka 咛:ning 咨:zi 咪:mi 咯:ge 咳:hai 品:pin 哈:ha 哌:pai 哒:da 哚:duo 哥:ge 哲:zhe 唐:tang 唑:zuo 唛:mai 唯:wei 唾:tuo 商:shang 啉:lin 啡:fei 啶:ding 喃:nan 善:shan 喉:hou 喏:nuo 喜:xi 喷:pen 喹:kui 嗉:su 嗜:shi 嗪:qin 嘉:jia 嘌:piao 嘧:mi 嘿:hei 噁:e 器:qi 噬:shi 噻:sai 嚼:jiao 囊:nang 囗:wei 四:si 因:yin 固:gu 国:guo 图:tu 土:tu 圣:sheng 在:zai 地:di 均:jun 坎:kan 坏:huai 坤:kun 坦:tan 垂:chui 型:xing 埃:ai 域:yu 培:pei 基:ji 堂:tang 塔:ta 塞:sai 增:zeng 墩:dun 壁:bi 士:shi 壬:ren 壮:zhuang 声:sheng 壹:yi 备:bei 复:fu 夏:xia 外:wai 多:duo 夜:ye 大:da 天:tian 太:tai 夫:fu 失:shi 头:tou 夷:yi 夸:kua 奇:qi 奈:nai 奉:feng 奋:fen 奎:kui 奕:yi 奥:ao 女:nü 奴:nu 好:hao 如:ru 妇:fu 妈:ma 妙:miao 妤:yu 妥:tuo 妮:ni 姆:mu 姜:jiang 威:wei 娜:na 婕:jie 婷:ting 媒:mei 子:zi 孕:yun 存:cun 孚:fu 孛:bei 孟:meng 孢:bao 学:xue 孩:hai 宁:ning 它:ta 宇:yu 安:an 宏:hong 宓:mi 宗:zong 定:ding 宜:yi 宝:bao 实:shi 宣:xuan 宫:gong 家:jia 容:rong 宾:bin 密:mi 富:fu 寒:han 对:dui 导:dao 封:feng 射:she 将:jiang 小:xiao 尓:er 尔:er 尖:jian 尘:chen 尚:shang 尤:you 尼:ni 尽:jin 尿:niao 层:ceng 屈:qu 屋:wu 屏:ping 屑:xie 山:shan 岁:sui 岚:lan 岛:dao 岩:yan 峰:feng 崩:beng 川:chuan 工:gong 左:zuo 巧:qiao 巨:ju 巯:qiu 己:ji 已:yi 巴:ba 布:bu 帅:shuai 帆:fan 希:xi 帕:pa 帝:di 带:dai 帮:bang 常:chang 幔:man 干:gan 平:ping 幸:xing 广:guang 庆:qing 库:ku 应:ying 庚:geng 度:du 康:kang 延:yan 廷:ting 廸:di 建:jian 廿:nian 开:kai 异:yi 式:shi 弗:fu 弘:hong 张:zhang 弥:mi 弹:tan 强:qiang 归:gui 当:dang 彤:tong 影:ying 彼:bi 征:zheng 待:dai 律:lü 得:de 御:yu 循:xun 微:wei 德:de 心:xin 必:bi 忆:yi 志:zhi 快:kuai 念:nian 忻:xin 忾:kai 思:si 怡:yi 性:xing 总:zong 恒:heng 恤:xu 恩:en 恪:ke 恬:tian 息:xi 恺:kai 悉:xi 悦:yue 悬:xuan 惟:wei 惠:hui 愈:yu 意:yi 感:gan 慢:man 慧:hui 慰:wei 慷:kang 戈:ge 戊:wu 成:cheng 戴:dai 扁:bian 手:shou 扎:zha 扑:pu 托:tuo 扬:yang 扰:rao 扶:fu 承:cheng 抑:yi 抒:shu 抗:kang 折:zhe 抚:fu 护:hu 拉:la 拓:tuo 拜:bai 择:ze 拿:na 挺:ting 换:huan 捷:jie 接:jie 控:kong 提:ti 握:wo 援:yuan 搏:bo 搽:cha 撒:sa 擎:qing 支:zhi 收:shou 攸:you 改:gai 放:fang 效:xiao 敌:di 敏:min 敖:ao 敢:gan 散:san 敦:dun 敬:jing 整:zheng 敷:fu 文:wen 斑:ban 断:duan 斯:si 新:xin 方:fang 施:shi 旁:pang 旋:xuan 无:wu 日:ri 旦:dan 旨:zhi 旭:xu 时:shi 旺:wang 昂:ang 昆:kun 昊:hao 昌:chang 明:ming 易:yi 昔:xi 昕:xin 昙:tan 星:xing 春:chun 显:xian 晋:jin 晓:xiao 晗:han 晟:sheng 晨:chen 普:pu 景:jing 晴:qing 晶:jing 智:zhi 暴:bao 曲:qu 更:geng 曼:man 曾:ceng 替:ti 月:yue 朋:peng 服:fu 朗:lang 望:wang 期:qi 朦:meng 木:mu 末:mo 本:ben 术:shu 朴:pu 朵:duo 机:ji 杆:gan 杉:shan 李:li 杏:xing 杖:zhang 杜:du 束:shu 来:lai 杨:yang 杭:hang 杰:jie 杷:pa 松:song 板:ban 极:ji 构:gou 枇:pi 析:xi 林:lin 果:guo 枝:zhi 枢:shu 枯:ku 架:jia 枸:gou 柏:bai 柑:gan 柔:rou 柠:ning 柯:ke 柳:liu 柴:chai 树:shu 栓:shuan 栢:bai 株:zhu 样:yang 核:he 根:gen 格:ge 桂:gui 桃:tao 桉:an 桑:sang 桔:ju 桦:hua 梅:mei 梗:geng 梨:li 梭:suo 检:jian 棉:mian 棒:bang 棓:bang 棕:zong 棘:ji 森:sen 植:zhi 椒:jiao 榄:lan 榈:lü 榔:lang 榕:rong 榭:xie 榴:liu 槐:huai 槟:bin 樟:zhang 橘:ju 橙:cheng 橼:yuan 檗:bo 檬:meng 次:ci 欢:huan 欣:xin 欧:ou 歌:ge 止:zhi 正:zheng 步:bu 武:wu 歧:qi 死:si 殊:shu 殷:yin 毅:yi 母:mu 每:mei 毒:du 毓:yu 比:bi 毕:bi 毛:mao 氏:shi 民:min 气:qi 氘:dao 氟:fu 氢:qing 氧:yang 氨:an 氮:dan 氯:lü 氰:qing 水:shui 永:yong 汀:ting 汁:zhi 汇:hui 汉:han 汕:shan 汝:ru 汞:gong 汰:tai 沁:qin 沂:yi 沃:wo 沐:mu 沙:sha 沛:pei 没:mei 沥:li 沫:mo 河:he 油:you 治:zhi 泉:quan 泊:bo 泌:mi 法:fa 泛:fan 泡:pao 波:bo 注:zhu 泪:lei 泮:pan 泯:min 泰:tai 泻:xie 泼:po 泽:ze 洁:jie 洋:yang 洗:xi 洛:luo 津:jin 洲:zhou 活:huo 派:pai 流:liu 浆:jiang 测:ce 济:ji 浓:nong 浙:zhe 浦:pu 浩:hao 浪:lang 海:hai 浸:jin 涂:tu 消:xiao 涓:juan 润:run 液:ye 涵:han 淀:dian 淑:shu 深:shen 淳:chun 混:hun 添:tian 清:qing 渗:shen 渠:qu 温:wen 渭:wei 港:gang 游:you 湖:hu 溉:gai 源:yuan 溢:yi 溴:xiu 溶:rong 滋:zi 滔:tao 滞:zhi 满:man 滤:lü 滨:bin 滴:di 漱:shu 潇:xiao 潘:pan 澜:lan 澳:ao 激:ji 瀚:han 灌:guan 火:huo 灭:mie 灰:hui 灵:ling 炉:lu 炎:yan 炔:que 炭:tan 点:dian 烃:ting 烟:yan 热:re 烯:xi 烷:wan 焦:jiao 然:ran 熊:xiong 熙:xi 熹:xi 爱:ai 爽:shuang 片:pian 牙:ya 牛:niu 牡:mu 物:wu 特:te 犀:xi 犬:quan 状:zhuang 狂:kuang 狄:di 狗:gou 独:du 猗:yi 猛:meng 猪:zhu 猫:mao 猴:hou 玄:xuan 玉:yu 王:wang 玖:jiu 玛:ma 玥:yue 玫:mei 环:huan 玻:bo 珀:po 珂:ke 珊:shan 珍:zhen 珐:fa 珑:long 珞:luo 珠:zhu 班:ban 珮:pei 球:qiu 琅:lang 理:li 琥:hu 琦:qi 琪:qi 琳:lin 琴:qin 琼:qiong 瑙:nao 瑚:hu 瑜:yu 瑞:rui 瑟:se 璃:li 璐:lu 璞:pu 瓜:gua 瓦:wa 甘:gan 甜:tian 生:sheng 用:yong 甫:fu 田:tian 由:you 甲:jia 申:shen 电:dian 甾:zai 畅:chang 留:liu 番:fan 疏:shu 疗:liao 疫:yi 疮:chuang 疱:pao 疹:zhen 病:bing 症:zheng 痔:zhi 痘:dou 痛:tong 痢:li 瘤:liu 癌:ai 癣:xuan 癸:gui 登:deng 白:bai 百:bai 皂:zao 的:de 皆:jie 皇:huang 皓:hao 皮:pi 皿:min 盈:ying 益:yi 盐:yan 盒:he 盖:gai 盘:pan 盛:sheng 盟:meng 目:mu 直:zhi 相:xiang 盼:pan 盾:dun 眉:mei 真:zhen 眩:xuan 眼:yan 睦:mu 睾:gao 睿:rui 矛:mao 知:zhi 短:duan 石:shi 矾:fan 砂:sha 研:yan 砜:feng 破:po 砷:shen 础:chu 硅:gui 硒:xi 硝:xiao 硫:liu 硬:ying 确:que 硼:peng 碇:ding 碘:dian 碧:bi 碱:jian 碳:tan 磊:lei 磷:lin 磺:huang 示:shi 社:she 祛:qu 祝:zhu 神:shen 祥:xiang 祺:qi 禄:lu 福:fu 离:li 禾:he 秀:xiu 秋:qiu 种:zhong 科:ke 秘:mi 秦:qin 积:ji 移:yi 稀:xi 稳:wen 穆:mu 穗:sui 穿:chuan 立:li 童:tong 端:duan 竹:zhu 笋:sun 笑:xiao 笔:bi 笛:di 符:fu 策:ce 简:jian 算:suan 管:guan 米:mi 类:lei 籽:zi 粉:fen 粒:li 粘:nian 粟:su 精:jing 糊:hu 糖:tang 糜:mi 糠:kang 系:xi 素:su 索:suo 紧:jin 紫:zi 累:lei 红:hong 纤:xian 纬:wei 纯:chun 纱:sha 纳:na 纷:fen 纽:niu 纾:shu 线:xian 组:zu 绅:shen 细:xi 织:zhi 绍:shao 经:jing 绒:rong 结:jie 给:gei 绛:jiang 络:luo 统:tong 绣:xiu 绥:sui 绪:xu 绮:qi 维:wei 绵:mian 综:zong 绿:lü 缇:ti 缌:si 缓:huan 缘:yuan 缩:suo 缬:xie 缺:que 罂:ying 罗:luo 置:zhi 羊:yang 美:mei 羔:gao 羚:ling 羟:qiang 群:qun 羧:suo 羽:yu 翁:weng 翔:xiang 翘:qiao 翰:han 考:kao 而:er 耐:nai 耳:er 联:lian 聚:ju 聪:cong 肉:rou 肌:ji 肖:xiao 肝:gan 肟:wo 肠:chang 肤:fu 肥:fei 肪:fang 肯:ken 育:yu 肺:fei 肼:jing 肽:tai 肾:shen 肿:zhong 胀:zhang 胂:shen 胃:wei 胆:dan 胍:gua 胎:tai 胚:pei 胜:sheng 胞:bao 胡:hu 胭:yan 胰:yi 胱:guang 胶:jiao 胸:xiong 胺:an 能:neng 脂:zhi 脉:mai 脊:ji 脑:nao 脒:mi 脯:pu 脱:tuo 脲:niao 脾:pi 腈:jing 腐:fu 腔:qiang 腙:zong 腥:xing 腮:sai 腹:fu 腺:xian 腾:teng 膏:gao 膜:mo 膦:lin 膨:peng 臣:chen 自:zi 至:zhi 致:zhi 臻:zhen 臼:jiu 舌:she 舍:she 舒:shu 良:liang 色:se 艾:ai 节:jie 芊:qian 芍:shao 芎:xiong 芙:fu 芝:zhi 芥:jie 芦:lu 芩:qin 芪:qi 芬:fen 芭:ba 芮:rui 芯:xin 花:hua 芳:fang 芷:zhi 芸:yun 芽:ya 苄:bian 苏:su 苓:ling 苗:miao 若:ruo 苦:ku 苧:zhu 苯:ben 英:ying 苷:gan 苹:ping 茁:zhuo 茄:qie 茉:mo 茚:yin 茛:gen 茜:qian 茴:hui 茵:yin 茶:cha 荃:quan 荆:jing 草:cao 荟:hui 荣:rong 荧:ying 药:yao 荷:he 荻:di 莎:sha 莨:lang 莪:e 莫:mo 莰:kan 莱:lai 莲:lian 获:huo 莹:ying 菁:jing 菇:gu 菊:ju 菌:jun 菏:he 菖:chang 菜:cai 菠:bo 菪:dang 菱:ling 菲:fei 萄:tao 萌:meng 萘:nai 萝:luo 营:ying 萨:sa 萩:qiu 落:luo 葆:bao 葎:lü 葛:ge 葡:pu 葵:kui 蒂:di 蒎:pai 蒙:meng 蒜:suan 蒲:pu 蒽:en 蒿:hao 蓉:rong 蓓:bei 蓝:lan 蓟:ji 蓣:yu 蔓:man 蔗:zhe 蔺:lin 蔻:kou 蕊:rui 蕲:qi 薁:yu 薄:bao 薇:wei 薯:shu 藤:teng 藻:zao 虎:hu 虑:lü 虫:chong 虹:hong 蚓:yin 蛇:she 蛋:dan 蛎:li 蛙:wa 蛹:yong 蜂:feng 蜚:fei 蜜:mi 蜡:la 蝎:xie 蝥:mao 蝮:fu 蝶:die 融:rong 螨:man 螺:luo 蠊:lian 血:xue 行:xing 衍:yan 衡:heng 衣:yi 补:bu 表:biao 袋:dai 裂:lie 装:zhuang 裕:yu 西:xi 见:jian 观:guan 视:shi 角:jiao 解:jie 言:yan 誉:yu 讯:xun 记:ji 设:she 诊:zhen 试:shi 诗:shi 诚:cheng 诺:nuo 谊:yi 谓:wei 谛:di 谱:pu 谷:gu 豆:dou 象:xiang 豪:hao 贝:bei 贞:zhen 质:zhi 贯:guan 贴:tie 贵:gui 费:fei 贺:he 贻:yi 赋:fu 赐:ci 赖:lai 赛:sai 赞:zan 赤:chi 赫:he 超:chao 越:yue 跃:yue 路:lu 踪:zong 蹄:ti 身:shen 车:che 轩:xuan 转:zhuan 轮:lun 软:ruan 轻:qing 载:zai 较:jiao 辅:fu 辉:hui 输:shu 辛:xin 辣:la 辰:chen 辽:liao 达:da 迁:qian 迅:xun 过:guo 迈:mai 运:yun 近:jin 返:fan 还:hai 远:yuan 连:lian 迦:jia 迪:di 迭:die 迷:mi 适:shi 选:xuan 逊:xun 透:tou 通:tong 速:su 造:zao 逸:yi 逻:luo 遇:yu 道:dao 那:na 邦:bang 邻:lin 郁:yu 郝:hao 都:dou 酊:ding 配:pei 酐:gan 酒:jiu 酚:fen 酞:tai 酪:lao 酮:tong 酯:zhi 酰:xian 酵:jiao 酶:mei 酸:suan 酿:niang 醇:chun 醋:cu 醌:kun 醑:xu 醚:mi 醛:quan 采:cai 释:shi 里:li 重:zhong 量:liang 金:jin 鑫:xin 钆:ga 钇:yi 钐:shan 钙:gai 钠:na 钡:bei 钦:qin 钩:gou 钰:yu 钴:gu 钾:jia 铁:tie 铂:bo 铃:ling 铊:ta 铋:bi 铜:tong 铝:lü 铭:ming 铵:an 银:yin 链:lian 铿:keng 锂:li 锆:gao 锋:feng 锌:xin 锐:rui 锑:ti 锝:de 锡:xi 锦:jin 锭:ding 锰:meng 锵:qiang 锶:si 镁:mei 镇:zhen 镜:jing 镧:lan 镭:lei 长:chang 门:men 闭:bi 闯:chuang 闲:xian 间:jian 阁:ge 阔:kuo 防:fang 阳:yang 阴:yin 阿:a 附:fu 陆:lu 降:jiang 陷:xian 隆:long 隐:yin 雄:xiong 雅:ya 集:ji 雌:ci 雨:yu 雪:xue 雷:lei 雾:wu 霁:ji 震:zhen 霉:mei 霍:huo 霖:lin 霜:shuang 霡:mai 露:lu 青:qing 靓:liang 靖:jing 静:jing 靛:dian 非:fei 面:mian 革:ge 鞘:qiao 鞣:rou 韦:wei 韬:tao 韵:yun 顶:ding 顺:shun 顿:dun 颂:song 预:yu 颅:lu 颇:po 颊:jia 颐:yi 颖:ying 颗:ke 颜:yan 颠:dian 风:feng 飒:sa 飞:fei 食:shi 饮:yin 馈:kui 首:shou 香:xiang 馨:xin 马:ma 骁:xiao 验:yan 骨:gu 髓:sui 高:gao 鬼:gui 魏:wei 鱼:yu 鲁:lu 鲑:gui 鲨:sha 鲸:jing 鸟:niao 鸡:ji 鸣:ming 鸿:hong 鹅:e 鹿:lu 麝:she 麟:lin 麦:mai 麸:fu 麻:ma 黄:huang 黏:nian 默:mo 黛:dai 鼎:ding 鼠:shu 鼻:bi 齐:qi 龄:ling 龙:long"
_PINYIN_DICT: dict[str, str] | None = None


def _pinyin_dict() -> dict[str, str]:
    """把「字:拼音」空格串解析成 dict（进程内只解析一次）。"""
    global _PINYIN_DICT
    if _PINYIN_DICT is None:
        out: dict[str, str] = {}
        for part in _PINYIN_CHARS_TEXT.split():
            ch, _, py = part.partition(":")
            if ch and py:
                out[ch] = py
        _PINYIN_DICT = out
    return _PINYIN_DICT


def _pinyin_tokens(text: str) -> list[str]:
    """汉字串 -> 拼音 token 集合：s:音节 / j:连写 / i:首字母；拉丁片段按词切。"""
    table = _pinyin_dict()
    syl: list[str] = []
    toks: set[str] = set()
    for ch in text or "":
        if "\u3400" <= ch <= "\u9fff":
            p = table.get(ch)
            if p:
                syl.append(p)
                toks.add("s:" + p)
        elif ch.isascii() and ch.isalnum():
            syl.append(ch.lower())
            toks.add("s:" + ch.lower())
    if len(syl) > 1:
        toks.add("j:" + "".join(syl))
        toks.add("i:" + "".join(x[0] for x in syl))
    return sorted(toks)


def encode_pinyin(entries, aliases) -> dict:
    """拼音/首字母别名表：token -> 条目下标数组（客户端懒加载，约 0.4 MB gzip）。

    - 名字键里含汉字的条目：按 k 生成 token；
    - 俗称/旧名：按显示名生成 token，指向该成分的条目（每个 token 最多 40 条，
      按 n 降序截断，控制懒加载体积；拼音只是增量路径，完整品牌列表仍由 result 页/中文俗称路径给出）。
    """
    toks: dict[str, set[int]] = {}
    for i, e in enumerate(entries):
        k = e.get("k") or ""
        if not re.search(r"[\u3400-\u9fff]", k):
            continue
        for tk in _pinyin_tokens(k):
            toks.setdefault(tk, set()).add(i)
    sid_ids: dict[str, list[int]] = {}
    for i, e in enumerate(entries):
        for sid in (e.get("vs") or [e.get("v")]):
            if sid:
                sid_ids.setdefault(sid, []).append(i)
    for a in aliases:
        sid = a.get("v")
        label = a.get("a") or a.get("n") or ""
        if not sid or not re.search(r"[\u3400-\u9fff]", label):
            continue
        ids = sid_ids.get(sid) or []
        if not ids:
            continue
        if len(ids) > 10:
            ids = sorted(ids, key=lambda i: -(entries[i].get("n") or 0))[:10]
        for tk in _pinyin_tokens(label):
            toks.setdefault(tk, set()).update(ids)
    return {"v": 1, "tokens": [[k, sorted(v)] for k, v in sorted(toks.items())]}


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True, exist_ok=True)
    (OUT / "data").mkdir(parents=True, exist_ok=True)
    (OUT / "assets" / "style.css").write_text(CSS, encoding="utf-8")
    def _render_i18n_js() -> str:
        return ("window.I18N=" + json.dumps(I18N, ensure_ascii=False) + ";\n" + r"""
(function(){
  var D = window.I18N;
  // 站点根路径：i18n.js 在 <head> 同步执行，currentScript 可用。
  // GitHub Pages 是项目子路径（/drug-brand-crossref/），不能假设语言目录在域名根。
  var scriptEl = document.currentScript;
  var ROOT = ((scriptEl && scriptEl.src) || location.href).replace(/assets\/i18n\.js.*$/, '');
  var rootPath = '/';
  try{ rootPath = new URL(ROOT).pathname || '/'; }catch(e){}
  function relPath(){
    // 相对站点根的路径，例如 /drug-brand-crossref/es/ → "es/"，子页 → "drug/x.html"。
    var p = location.pathname;
    return p.indexOf(rootPath) === 0 ? p.slice(rootPath.length) : p.replace(/^\//, '');
  }
  function pick(){
    var q = new URLSearchParams(location.search).get('lang');
    if(q && D[q]){ try{localStorage.setItem('lang',q);}catch(e){} return q; }
    var first = relPath().split('/').filter(Boolean)[0] || '';
    // 直接进 /es/、/zh/（hreflang 主入口）时把语言写进 localStorage，
    // 这样点导航去 /about.html 等根路径页面不会掉回 en。
    if(D[first]){ try{localStorage.setItem('lang',first);}catch(e){} return first; }
    try{ var s = localStorage.getItem('lang'); if(s && D[s]) return s; }catch(e){}
    var n = (navigator.language || 'en').slice(0,2);
    return D[n] ? n : 'en';
  }
  window.LANG = pick();
  window.T = function(k){ return (D[window.LANG] && D[window.LANG][k]) || D.en[k] || k; };
  function apply(){
    document.documentElement.lang = window.LANG;
    document.querySelectorAll('[data-i18n]').forEach(function(el){ el.textContent = window.T(el.dataset.i18n); });
    // i18n P1：About / What's new / Confused / 404 的正文块允许内嵌链接与表格，
    // 用 data-i18n-html 走 innerHTML（内容全部来自构建期字典，非用户输入）。
    document.querySelectorAll('[data-i18n-html]').forEach(function(el){ el.innerHTML = window.T(el.dataset.i18nHtml); });
    // /warn 与成分页的警示正文是数据行（zh/en/es 各一份），按当前语言只显示对应块。
    document.querySelectorAll('[data-lang-block]').forEach(function(el){
      el.style.display = (el.dataset.langBlock === window.LANG) ? '' : 'none';
    });
    document.querySelectorAll('[data-ph]').forEach(function(el){ el.placeholder = window.T(el.dataset.ph); });
    document.querySelectorAll('.langs a').forEach(function(a){
      a.classList.toggle('on', a.dataset.lang === window.LANG);
    });
  }
  function langTarget(code){
    // 入口页（/、/es/、/zh/）切到对应语言入口，URL 与显示语言保持一致；
    // 子页面（drug/、name/ 等）切语言时留在原页，只换 lang 参数。
    var params = new URLSearchParams(location.search);
    var landing = /(\/|index\.html)$/.test(location.pathname);
    var path;
    if(landing){ params.delete('lang'); path = ROOT + (code === 'en' ? '' : code + '/'); }
    else { params.set('lang', code); path = location.pathname; }
    var qs = params.toString();
    return path + (qs ? '?' + qs : '') + (location.hash || '');
  }
  window.setLang = function(l){
    try{ localStorage.setItem('lang', l); }catch(e){}
    location.assign(langTarget(l));
  };
  // 语言切换链接：保留 ?q= / ?country= 等查询参数（原先 ?lang= 会把它们清掉）。
  document.addEventListener('click', function(ev){
    var a = ev.target && ev.target.closest ? ev.target.closest('a[data-lang]') : null;
    if(!a) return;
    if(ev.defaultPrevented || ev.button || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    ev.preventDefault();
    window.setLang(a.getAttribute('data-lang'));
  });
  if(document.readyState === 'loading'){ document.addEventListener('DOMContentLoaded', apply); }
  else { apply(); }
  window.addEventListener('load', apply);
})();
"""
        )
    (OUT / "assets" / "i18n.js").write_text(_render_i18n_js(), encoding="utf-8")
    (OUT / "assets" / "app.js").write_text(
        APP_JS.replace("REPORT_REPO_PLACEHOLDER", REPORT_REPO)
        .replace("data/idx/core.json", f"data/idx/core.json?v={int(time.time())}")
        .replace("data/idx/pinyin.json", f"data/idx/pinyin.json?v={int(time.time())}")
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
        "atc": db.execute(
            "SELECT COUNT(*) FROM substance WHERE atc IS NOT NULL AND atc <> ''").fetchone()[0],
        "keys": db.execute("SELECT COUNT(*) FROM name_key").fetchone()[0],
        "nickname": db.execute("SELECT COUNT(*) FROM nickname").fetchone()[0],
        "aliases": db.execute("SELECT COUNT(*) FROM alias_all").fetchone()[0],
        "confusable": db.execute("SELECT COUNT(*) FROM confusable_pair").fetchone()[0],
        "severe": db.execute(
            "SELECT COUNT(*) FROM collision WHERE level='severe'").fetchone()[0],
    }
    stats["atc_pct"] = round(stats["atc"] / stats["substances"] * 100, 1) if stats["substances"] else 0
    # i18n P1：About 双口径 ATC（动态）+ drug_term 计数 + About/Confused 占位符替换。
    # i18n.js 里内嵌三语字典，所以必须在这批动态值算完后重写一次 i18n.js（前面那次是初版）。
    atc_cov = _atc_coverage(db)
    stats["drug_term"] = db.execute("SELECT COUNT(*) FROM drug_term").fetchone()[0]
    # /warn：只统计 published（draft/retracted 不展示，也不进页面计数）
    warn_by_sev = {"high": 0, "medium": 0, "info": 0}
    for sev, n in db.execute("SELECT severity, COUNT(*) FROM dose_warning "
                             "WHERE status = 'published' GROUP BY severity"):
        warn_by_sev[sev] = n
    stats["warn_high"] = warn_by_sev["high"]
    stats["warn_medium"] = warn_by_sev["medium"]
    stats["warn_info"] = warn_by_sev["info"]
    stats["warn_total"] = sum(warn_by_sev.values())
    _merge_static_i18n(_i18n_placeholders(stats, atc_cov, coverage, source_cover))
    (OUT / "assets" / "i18n.js").write_text(_render_i18n_js(), encoding="utf-8")

    print("building index ...", flush=True)
    entries = load_index(db)
    (OUT / "data" / "index.json").write_text(
        json.dumps(entries, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # P1：同一份 entries 再写一份列式 + 字典编码核心（客户端解码回 IDX）。
    # index.json 双写保留：?legacy=1 与核心加载/解码失败时自动回退，发布体积可接受。
    core = encode_core(entries)
    (OUT / "data" / "idx").mkdir(parents=True, exist_ok=True)
    (OUT / "data" / "idx" / "core.json").write_bytes(
        json.dumps(core, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    print(f"  {len(entries)} keys", flush=True)
    print(f"  core.json  { (OUT / 'data' / 'idx' / 'core.json').stat().st_size / 1e6:.1f} MB"
          f" (index.json {(OUT / 'data' / 'index.json').stat().st_size / 1e6:.1f} MB)", flush=True)

    print("building nickname index ...", flush=True)
    aliases = load_aliases(db)
    (OUT / "data" / "aliases.json").write_text(
        json.dumps(aliases, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {len(aliases)} nicknames", flush=True)

    # 搜索增强（task-28）：拼音/首字母 token 表（客户端按需懒加载，见 APP_JS 的 pinyinFetch）
    piny = encode_pinyin(entries, aliases)
    (OUT / "data" / "idx" / "pinyin.json").write_bytes(
        json.dumps(piny, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    print(f"  pinyin.json { (OUT / 'data' / 'idx' / 'pinyin.json').stat().st_size / 1e6:.2f} MB",
          flush=True)

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
    n_warn = build_warn(db)
    build_about(stats, coverage, source_cover)
    build_whats_new()
    build_404()
    build_seo_files()

    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"\n== done ==")
    print(f"  drug pages : {n_drug}")
    print(f"  name pages : {n_name}")
    print(f"  confused   : {n_conf} pairs")
    print(f"  warnings   : {n_warn} published")
    print(f"  index.json : {(OUT / 'data' / 'index.json').stat().st_size / 1e6:.1f} MB")
    print(f"  total size : {size / 1e6:.1f} MB")
    print(f"  open       : {OUT / 'index.html'}")
    db.close()


if __name__ == "__main__":
    main()
