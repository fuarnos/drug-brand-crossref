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
    data/index.json     旧检索索引（v0.6.1 起默认不再生成；仅 WRITE_LEGACY_INDEX=1 过渡写）
    data/idx/core.json  检索索引唯一真相源（列式 + 字典编码；客户端 decodeCore 解码）
    data/idx/legacy-mini.json  可选二级兜底（WRITE_LEGACY_MINI=1 时生成；core 损坏时用）
    data/aliases.json   俗称 / 街头叫法 / 类别词索引
    data/confused.json  易混淆药对索引
    assets/             css + js

用法：python site/build.py
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import time
import unicodedata
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

# v0.6.2：繁体中文（zh-Hant）UI。字典来自 data/i18n_zh_hant.json（由简体 I18N 经
# OpenCC + 台湾用语表转换，247 键）；缺键回退简体 zh。搜索输入繁体→简体归一用
# data/zh_hant_t2s.json（OpenCC TSCharacters 常用字子集，构建期注入 app.js）。
ZH_HANT_I18N_FILE = ROOT / "data" / "i18n_zh_hant.json"
ZH_HANT_T2S_FILE = ROOT / "data" / "zh_hant_t2s.json"


def _load_json_file(path: Path) -> dict:
    """读 JSON 对象；文件缺失/损坏返回 {}（构建不因此失败）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_zh_hant_dict() -> dict[str, str]:
    payload = _load_json_file(ZH_HANT_I18N_FILE)
    mapping = payload.get("zh-Hant") or {}
    return {str(k): str(v) for k, v in mapping.items()} if isinstance(mapping, dict) else {}


def _load_zh_hant_t2s() -> dict[str, str]:
    payload = _load_json_file(ZH_HANT_T2S_FILE)
    mapping = payload.get("map") or {}
    return {str(k): str(v) for k, v in mapping.items()} if isinstance(mapping, dict) else {}


def _subst_placeholders(text: str, values: dict) -> str:
    for key, val in values.items():
        text = text.replace("@@" + str(key) + "@@", str(val))
    return text


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
        "home.sub": ("Type a brand name, a generic name, a nickname, or a line from the pack. "
                     "Chinese, full-width and Cyrillic input all work, and you can include the "
                     "dose — e.g. Lipitor 20mg, Tylenol, or Paracetamol 500mg."),
        "home.ph": "Brand name / generic name / nickname / a line from the pack",
        "home.all": "All countries and regions", "home.us": "United States",
        "home.gb": "United Kingdom", "home.cn": "China", "home.es": "Spain",
        "home.mx": "Mexico", "home.au": "Australia", "home.ca": "Canada",
        "home.sg": "Singapore",
        "home.tw": "Taiwan",
        "home.coverage": ("An empty result does not mean the medicine does not exist. "
                          "Coverage (countries and regions):"),
        "home.loading": "Loading index…",
        "home.hint_idle": ("First search loads only one small shard of the index (~0.2 MB); the "
                           "full index fills in the background — start typing, focus the search "
                           "box, or pick a sample."),
        "home.hint_loading": "Loading a small index shard (~0.2 MB)…",
        # v0.6.6：成分页多国并排矩阵
        "matrix.spec": "Strength / form / release",
        "matrix.none": "not recorded",
        "matrix.hidden_note": ("Discontinued, withdrawn or unverified-status products are hidden "
                               "by default."),
        "matrix.capped": "Showing the first {shown} of {total} strength/form rows.",
        # v0.6.7：/warn 分页
        "warn.page_prev": "Previous", "warn.page_next": "Next",
        "warn.pagination": "Warning pages",
        "warn.page_status": "Page {n} of {total} · {count} warnings",
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
    "res.partial": "partial results — loading the full index…",
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
        "name.countries": "Countries & regions", "name.form": "Form",
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
        "home.country_label": "See what this medicine is called in each country/region:",
        "home.country_label_sel": "See what this medicine is called in {country}:",
        "country.missing": "This country/region has no product listed under this name.",
        "country.missing_note": ("The name matched an ingredient, not a product in this "
                                 "country/region. Switch country/region or open the ingredient page."),
        "country.open_card": "Ingredient page",
        "country.change": "Change country/region",
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
        "res.copy": "Copy table", "res.csv": "Download CSV",
        "res.copied": "Copied", "res.copy_fail": "Copy failed — select the table manually",
        "res.col_country": "Countries & regions", "res.col_form": "Form",
        "res.col_match": "Match", "res.col_link": "Page",
        "a3.salt": "Salt forms:", "a3.release": "Release:",
        "a3.incompat": "Not interchangeable — see warning",
        "row.report": "Report this row",
        "report.field_row": "Row",
        "a1.expand": "Details", "a1.loading": "Loading details…",
        "a1.none": "No product records for this name.",
        "a1.goto": "Open substance page",
        "a1.market": "Market", "a1.pack": "Pack", "a1.approval": "Approval / NDC / DIN",
        "a1.status": "Status", "a1.source": "Source", "a1.raw": "Original record",
        "a1.more": "Showing the first 12 records; see the substance page for all.",
    },
    "es": {
        "nav.search": "Buscar", "nav.confused": "Nombres confundibles", "nav.about": "Acerca de",
        "nav.whatsnew": "Novedades",
        "home.h1": "Descubre qué es realmente un medicamento",
        "home.sub": ("Escribe un nombre comercial, un genérico, un apodo o una línea del envase. "
                     "También funciona en chino, ancho completo y cirílico; puedes incluir la "
                     "dosis — p. ej. Paracetamol 500mg, Ibuprofeno 600mg o Lipitor 20mg."),
        "home.ph": "Nombre comercial / genérico / apodo / una línea del envase",
        "home.all": "Todos los países y regiones", "home.us": "Estados Unidos",
        "home.gb": "Reino Unido", "home.cn": "China", "home.es": "España",
        "home.mx": "México", "home.au": "Australia", "home.ca": "Canadá",
        "home.sg": "Singapur",
        "home.tw": "Taiwán",
        "home.coverage": ("Un resultado vacío no significa que el medicamento no exista. "
                          "Cobertura (países y regiones):"),
        "home.loading": "Cargando el índice…",
        "home.hint_idle": ("La primera búsqueda carga solo un fragmento pequeño del índice "
                           "(~0,2 MB); el índice completo se completa en segundo plano — empieza "
                           "a escribir, enfoca el buscador o elige un ejemplo."),
        "home.hint_loading": "Cargando un fragmento del índice (~0,2 MB)…",
        # v0.6.6：成分页多国并排矩阵
        "matrix.spec": "Concentración / forma / liberación",
        "matrix.none": "no consta",
        "matrix.hidden_note": ("Los productos retirados, suspendidos o con estado no verificado "
                               "se ocultan por defecto."),
        "matrix.capped": "Mostrando las primeras {shown} de {total} filas de concentración/forma.",
        # v0.6.7：/warn 分页
        "warn.page_prev": "Anterior", "warn.page_next": "Siguiente",
        "warn.pagination": "Páginas de avisos",
        "warn.page_status": "Página {n} de {total} · {count} avisos",
        "error.index_failed": "No se pudo cargar el índice.",
        "error.local_file": ("Si abriste esta página directamente, el navegador bloquea la "
                             "lectura de archivos locales — ejecuta python -m http.server y "
                             "visita http://localhost:8000/."),
        "error.retry": "Reintentar",
        "res.matched": "nombres encontrados", "res.none": "Sin resultados",
        "res.brands": "nombres comerciales encontrados",
        "res.alias": "alias encontrado",
        "res.alias_no_products": "no es un producto único — ver la nota",
        "res.notin": "No incluido en este país/región",
        "res.caveat": "un resultado vacío no significa que el medicamento no exista",
    "res.partial": "resultados parciales — cargando el índice completo…",
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
        "name.countries": "Países y regiones", "name.form": "Forma",
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
        "home.country_label": "Mira cómo se llama este medicamento en cada país/región:",
        "home.country_label_sel": "Mira cómo se llama este medicamento en {country}:",
        "country.missing": "Este país/región no tiene ningún producto registrado con este nombre.",
        "country.missing_note": ("El nombre coincide con un principio activo, no con un producto "
                                 "de este país/región. Cambia de país/región o abre la ficha del "
                                 "principio activo."),
        "country.open_card": "Ficha del principio",
        "country.change": "Cambiar país/región",
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
        "res.copy": "Copiar tabla", "res.csv": "Descargar CSV",
        "res.copied": "Copiado", "res.copy_fail": "No se pudo copiar — selecciona la tabla",
        "res.col_country": "Países y regiones", "res.col_form": "Forma",
        "res.col_match": "Coincidencia", "res.col_link": "Página",
        "a3.salt": "Formas salinas:", "a3.release": "Liberación:",
        "a3.incompat": "No intercambiables — ver aviso",
        "row.report": "Informar de esta fila",
        "report.field_row": "Fila",
        "a1.expand": "Detalles", "a1.loading": "Cargando detalles…",
        "a1.none": "No hay registros de producto para este nombre.",
        "a1.goto": "Abrir página del principio activo",
        "a1.market": "Mercado", "a1.pack": "Envase", "a1.approval": "Registro / NDC / DIN",
        "a1.status": "Estado", "a1.source": "Fuente", "a1.raw": "Registro original",
        "a1.more": "Se muestran los primeros 12 registros; la página del principio activo tiene todos.",
    },
    "zh": {
        "nav.search": "检索", "nav.confused": "易混淆药名", "nav.about": "关于",
        "nav.whatsnew": "更新日志",
        "home.h1": "查一个药名，看它在各国是什么",
        "home.sub": ("商品名、通用名、俗称都能搜（比如「两只青蛙」）；支持中英文、全角、"
                     "西里尔字母，也可以连剂量一起输入，例如 Lipitor 20mg、泰诺、СОРТИС。"),
        "home.ph": "商品名 / 通用名 / 俗称 / 包装上的一行字",
        "home.all": "全部国家和地区", "home.us": "美国",
        "home.gb": "英国", "home.cn": "中国", "home.es": "西班牙",
        "home.mx": "墨西哥", "home.au": "澳大利亚", "home.ca": "加拿大",
        "home.sg": "新加坡",
        "home.tw": "台湾",
        "home.coverage": "查不到不代表这个药不存在。当前覆盖（国家和地区）：",
        "home.loading": "正在加载索引…",
        "home.hint_idle": ("首次搜索只加载当前首字符的一小片索引（约 0.2 MB），完整索引会在后台补全"
                           "——直接输入、点搜索框或选一个示例。"),
        "home.hint_loading": "正在加载索引分片（约 0.2 MB）…",
        # v0.6.6：成分页多国并排矩阵
        "matrix.spec": "规格 / 剂型 / 释放",
        "matrix.none": "未收录",
        "matrix.hidden_note": "已停售、撤市或状态未确认的产品默认隐藏。",
        "matrix.capped": "仅显示前 {shown} / {total} 个规格行。",
        # v0.6.7：/warn 分页
        "warn.page_prev": "上一页", "warn.page_next": "下一页",
        "warn.pagination": "警示分页",
        "warn.page_status": "第 {n} / {total} 页 · 共 {count} 条",
        "error.index_failed": "索引没加载成功。",
        "error.local_file": ("如果是本地双击打开的页面，浏览器会拦截本地文件读取——请用 "
                             "python -m http.server 起服务后访问 http://localhost:8000/。"),
        "error.retry": "重试",
        "res.matched": "个名字命中", "res.none": "没有匹配的名字",
        "res.brands": "个商品名命中",
        "res.alias": "个别名命中",
        "res.alias_no_products": "不是单一商品，见上方说明",
        "res.notin": "所选国家/地区没有收录这个名字",
        "res.caveat": "查不到不代表这个药不存在",
    "res.partial": "部分结果 —— 正在加载完整索引…",
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
        "name.countries": "国家/地区", "name.form": "剂型",
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
        "home.country_label": "看这个药在哪个国家/地区叫什么：",
        "home.country_label_sel": "看这个药在{country}叫什么：",
        "country.missing": "该国家/地区没有以这个名字上架的产品。",
        "country.missing_note": "这个名字命中的是成分卡，不是该国家/地区上架的产品。可以换一个国家/地区，或直接看成分卡。",
        "country.open_card": "看成分卡",
        "country.change": "换国家/地区",
        "parse.label": "检索解析",
        "parse.name": "名称", "parse.dose": "剂量", "parse.form": "剂型",
        "parse.match": "匹配方式",
        "parse.match.exact": "精确", "parse.match.compact": "连写",
        "parse.match.prefix": "前缀", "parse.match.contains": "包含",
        "parse.match.fuzzy": "模糊", "parse.match.nickname": "别名",
    "parse.match.pinyin": "拼音",
        "parse.match.country": "国家/地区视图", "parse.match.none": "无匹配",
        "ac.suggestions": "搜索建议",
        "res.brands_noun": "个品牌",
        "res.show_brands": "展开全部品牌",
        "res.fold": "折叠",
        "res.load_more": "加载更多",
        "res.loaded_all": "已显示全部结果",
        "res.copy": "复制表格", "res.csv": "下载 CSV",
        "res.copied": "已复制", "res.copy_fail": "复制失败，请手动选择表格",
        "res.col_country": "国家/地区", "res.col_form": "剂型",
        "res.col_match": "匹配方式", "res.col_link": "页面",
        "a3.salt": "盐型：", "a3.release": "释放：",
        "a3.incompat": "不可互换 — 见警示",
        "row.report": "报告这一行",
        "report.field_row": "行",
        "a1.expand": "详情", "a1.loading": "正在加载明细…",
        "a1.none": "这个名字下没有产品记录。",
        "a1.goto": "打开成分页",
        "a1.market": "市场", "a1.pack": "包装", "a1.approval": "批准号 / NDC / DIN",
        "a1.status": "状态", "a1.source": "来源", "a1.raw": "原始记录",
        "a1.more": "仅显示前 12 条记录，全部见成分页。",
    },
}

# v0.6.2：四语言。zh-Hant 的 URL 目录用全小写 zh-hant/（hreflang 仍是 BCP47 zh-Hant）。
LANGS = [("en", "EN", ""), ("es", "ES", "es/"), ("zh", "中文", "zh/"),
         ("zh-Hant", "繁", "zh-hant/")]
LANG_PATH = {code: path for code, _label, path in LANGS}
LANG_HREFLANG = {code: ("zh-Hant" if code == "zh-Hant" else code)
                 for code, _label, _path in LANGS}
# i18n.js 运行时用：?lang=zh-hant、/zh-hant/、navigator.language=zh-TW 等 → zh-Hant
LANG_ALIASES = {
    "zh-hant": "zh-Hant", "zh_hant": "zh-Hant", "zh-tw": "zh-Hant",
    "zh-hk": "zh-Hant", "zh-mo": "zh-Hant",
    "zh-hans": "zh", "zh-cn": "zh", "zh-sg": "zh",
}
LANG_META_JS = (
    "var LANG_PATH=" + json.dumps(LANG_PATH, ensure_ascii=False, separators=(",", ":")) + ";\n"
    + "var LANG_ALIAS=" + json.dumps(LANG_ALIASES, ensure_ascii=False, separators=(",", ":")) + ";\n"
    + "var DEFAULT_LANG='en';"
)

# ── v0.6.3 U3：界面标签本地化（LABEL_I18N）+ U1/U2 文案（UI_I18N） ──────────
# 单一数据源：服务端 label helper 与客户端 T() 共用同一批 key；zh-Hant 直接给值，
# 不再依赖 data/i18n_zh_hant.json（新 key 无法及时进该 JSON 时也不会回落简体）。
LABEL_I18N = {
    "en": {
        "form.tablet": "tablet", "form.capsule": "capsule", "form.liquid": "liquid",
        "form.injection": "injection", "form.topical": "topical", "form.powder": "powder",
        "form.suppository": "suppository", "form.inhalation": "inhalation",
        "form.pellet": "pellet", "form.stick": "stick", "form.kit": "kit",
        "form.gas": "gas", "form.unknown": "unknown",
        "release.ER": "extended-release", "release.DR": "delayed-release",
        "release.MR": "modified-release", "release.none": "—",
        "unit.iu": "IU", "unit.unit": "unit", "unit.meq": "mEq", "unit.mci": "mCi",
        "unit.ug": "mcg", "unit.microgram": "mcg", "unit.万iu": "10k IU",
    },
    "es": {
        "form.tablet": "comprimido", "form.capsule": "cápsula", "form.liquid": "líquido",
        "form.injection": "inyectable", "form.topical": "tópico", "form.powder": "polvo",
        "form.suppository": "supositorio", "form.inhalation": "inhalado",
        "form.pellet": "pellet", "form.stick": "stick", "form.kit": "kit",
        "form.gas": "gas", "form.unknown": "desconocido",
        "release.ER": "liberación prolongada", "release.DR": "liberación retardada",
        "release.MR": "liberación modificada", "release.none": "—",
        "unit.iu": "UI", "unit.unit": "unidad", "unit.meq": "meq", "unit.mci": "mCi",
        "unit.ug": "mcg", "unit.microgram": "mcg", "unit.万iu": "10 000 UI",
    },
    "zh": {
        "form.tablet": "片剂", "form.capsule": "胶囊", "form.liquid": "液体",
        "form.injection": "注射剂", "form.topical": "外用", "form.powder": "粉末",
        "form.suppository": "栓剂", "form.inhalation": "吸入剂",
        "form.pellet": "微丸", "form.stick": "棒剂", "form.kit": "套装",
        "form.gas": "气体", "form.unknown": "未知",
        "release.ER": "缓释", "release.DR": "延迟释放",
        "release.MR": "改良释放", "release.none": "—",
        "unit.iu": "国际单位", "unit.unit": "单位", "unit.meq": "毫当量", "unit.mci": "mCi",
        "unit.ug": "mcg", "unit.microgram": "mcg", "unit.万iu": "10 万 IU",
    },
    "zh-Hant": {
        "form.tablet": "錠劑", "form.capsule": "膠囊", "form.liquid": "液體",
        "form.injection": "注射劑", "form.topical": "外用", "form.powder": "粉末",
        "form.suppository": "栓劑", "form.inhalation": "吸入劑",
        "form.pellet": "微丸", "form.stick": "棒劑", "form.kit": "套組",
        "form.gas": "氣體", "form.unknown": "未知",
        "release.ER": "緩釋", "release.DR": "延遲釋放",
        "release.MR": "修飾釋放", "release.none": "—",
        "unit.iu": "國際單位", "unit.unit": "單位", "unit.meq": "毫當量", "unit.mci": "mCi",
        "unit.ug": "mcg", "unit.microgram": "mcg", "unit.万iu": "10 萬 IU",
    },
}
UI_I18N = {
    "en": {
        "u1.title": "How to use it in 3 steps",
        "u1.step1": "Type the name from the pack",
        "u1.step1_hint": ("Brand, generic name, nickname, or a line from the pack — "
                          "dose included is fine."),
        "u1.step2": "See the ingredient and strength",
        "u1.step2_hint": "You always get a candidate set — never a single answer.",
        "u1.step3": "Switch to a country/region",
        "u1.step3_hint": ("Pick a country/region to see the names it is sold under there, "
                          "or use the names-by-country/region row."),
        "u1.try": "Try:", "u1.close": "Dismiss", "u1.aria": "Getting-started guide",
        "u2.title": "Names by country/region",
        "u2.hint": ("Same ingredient, local name — click a country/region to see its products. "
                    "Not listed does not prove it is unavailable there."),
        "u2.none": "Not listed",
        "u2.none_hint": ("No product under this ingredient in this market's public data. "
                         "This does not prove it is unavailable there."),
        "u2.multi": "Several ingredients match — switch country/region to see the full list.",
        # v0.6.4 A2：ATC 码搜索 + B10 术语表
        "nav.glossary": "Glossary",
        "meta.glossary.title": "Glossary · Medicine Brand Cross-Reference",
        "meta.glossary.desc": ("Short definitions of the codes and terms used on this site: "
                               "INN, BAN, USAN, ATC, MAH, DIN, NDC, ARTG, FDC, LASA, OTC, Rx, "
                               "strength."),
        "parse.atc": "ATC code", "parse.match.atc": "ATC code",
        "atc.label": "ATC",
        "atc.hint": ("ATC prefix match — results are products whose active ingredient carries "
                     "this ATC code, not brand-name matches."),
        "atc.hit": ("ATC {code}: {n} product names matched by active-ingredient ATC code. "
                    "Identity only — not a recommendation."),
        "atc.none": "No recorded active ingredient carries this ATC code or prefix.",
        "atc.none_meta": "No ATC match for {code}",
        "atc.loading": "Loading the index for ATC search…",
    },
    "es": {
        "u1.title": "Cómo funciona en 3 pasos",
        "u1.step1": "Escribe el nombre del envase",
        "u1.step1_hint": ("Marca, genérico, apodo o una línea del envase; la dosis puede "
                          "ir incluida."),
        "u1.step2": "Mira el principio activo y la concentración",
        "u1.step2_hint": "Siempre obtienes un conjunto de candidatos, nunca una única respuesta.",
        "u1.step3": "Cambia a un país/región",
        "u1.step3_hint": ("Elige un país/región para ver los nombres con los que se vende "
                          "allí, o usa la fila de nombres por país/región."),
        "u1.try": "Prueba:", "u1.close": "Cerrar", "u1.aria": "Guía de inicio",
        "u2.title": "Nombres por país/región",
        "u2.hint": ("Mismo principio, nombre local: haz clic en un país/región para ver sus "
                    "productos. «Sin datos» no prueba que no exista allí."),
        "u2.none": "Sin datos",
        "u2.none_hint": ("Sin datos públicos para este principio en ese mercado; no prueba "
                         "que no exista allí."),
        "u2.multi": "Varios principios coinciden — cambia de país/región para ver la lista completa.",
        # v0.6.4 A2：ATC 码搜索 + B10 术语表
        "nav.glossary": "Glosario",
        "meta.glossary.title": "Glosario · Medicine Brand Cross-Reference",
        "meta.glossary.desc": ("Definiciones breves de los códigos y términos usados en el sitio: "
                               "INN, BAN, USAN, ATC, MAH, DIN, NDC, ARTG, FDC, LASA, OTC, Rx, "
                               "concentración."),
        "parse.atc": "Código ATC", "parse.match.atc": "Código ATC",
        "atc.label": "ATC",
        "atc.hint": ("Coincidencia por prefijo ATC: los resultados son productos cuyo principio "
                     "activo lleva este código ATC, no nombres comerciales."),
        "atc.hit": ("ATC {code}: {n} nombres de producto coinciden por el código ATC del "
                    "principio activo. Solo identidad, no una recomendación."),
        "atc.none": "Ningún principio activo registrado lleva este código o prefijo ATC.",
        "atc.none_meta": "Sin coincidencias ATC para {code}",
        "atc.loading": "Cargando el índice para la búsqueda ATC…",
    },
    "zh": {
        "u1.title": "三步看懂",
        "u1.step1": "输入包装上的名字",
        "u1.step1_hint": "商品名、通用名、俗称或包装上一行字；可连剂量一起输入。",
        "u1.step2": "看成分和规格",
        "u1.step2_hint": "结果永远是候选集，不保证唯一。",
        "u1.step3": "切国家/地区看叫法",
        "u1.step3_hint": "选一个国家/地区，看这个成分在当地叫什么；也可以用结果顶部的「国家/地区叫法」横排。",
        "u1.try": "试试：", "u1.close": "关闭", "u1.aria": "使用引导",
        "u2.title": "国家/地区叫法",
        "u2.hint": "同一成分在当地叫什么；点国家/地区看该地商品。未收录不等于该国家/地区没有这个药。",
        "u2.none": "未收录",
        "u2.none_hint": "公开数据里暂无该国该成分的产品；不等于该国没有这个药。",
        "u2.multi": "多成分/多结果，切国家/地区查看全部。",
        # v0.6.4 A2：ATC 码搜索 + B10 术语表
        "nav.glossary": "术语表",
        "meta.glossary.title": "术语表 · 药品商品名跨国定位",
        "meta.glossary.desc": ("本站常用代码与术语的简短解释：INN、BAN、USAN、ATC、MAH、DIN、NDC、"
                               "ARTG、FDC、LASA、OTC、Rx、规格。"),
        "parse.atc": "ATC 码", "parse.match.atc": "ATC 码",
        "atc.label": "ATC",
        "atc.hint": "按 ATC 码前缀匹配：结果是「活性成分带有该 ATC 码」的产品，不是商品名匹配。",
        "atc.hit": "ATC {code}：{n} 个商品名按活性成分 ATC 码命中。只做身份对应，不构成推荐。",
        "atc.none": "已收录的活性成分中没有这个 ATC 码或前缀。",
        "atc.none_meta": "{code} 没有 ATC 命中",
        "atc.loading": "正在加载索引以进行 ATC 搜索…",
    },
    "zh-Hant": {
        "u1.title": "三步看懂",
        "u1.step1": "輸入包裝上的名字",
        "u1.step1_hint": "商品名、通用名、俗稱或包裝上一行字；可連劑量一起輸入。",
        "u1.step2": "看成分和規格",
        "u1.step2_hint": "結果永遠是候選集，不保證唯一。",
        "u1.step3": "切國家/地區看叫法",
        "u1.step3_hint": "選一個國家/地區，看這個成分在當地叫什麼；也可以用結果頂部的「國家/地區叫法」橫排。",
        "u1.try": "試試：", "u1.close": "關閉", "u1.aria": "使用引導",
        "u2.title": "國家/地區叫法",
        "u2.hint": "同一成分在當地叫什麼；點國家/地區看該地商品。未收錄不等於該國家/地區沒有這個藥。",
        "u2.none": "未收錄",
        "u2.none_hint": "公開資料裡暫無該國該成分的產品；不等於該國沒有這個藥。",
        "u2.multi": "多成分/多結果，切國家/地區查看全部。",
        # v0.6.4 A2：ATC 码搜索 + B10 術語表
        "nav.glossary": "術語表",
        "meta.glossary.title": "術語表 · 藥品商品名跨國定位",
        "meta.glossary.desc": ("本站常用代碼與術語的簡短解釋：INN、BAN、USAN、ATC、MAH、DIN、NDC、"
                               "ARTG、FDC、LASA、OTC、Rx、規格。"),
        "parse.atc": "ATC 碼", "parse.match.atc": "ATC 碼",
        "atc.label": "ATC",
        "atc.hint": "依 ATC 碼前綴比對：結果是「有效成分帶有此 ATC 碼」的產品，不是商品名比對。",
        "atc.hit": "ATC {code}：{n} 個商品名依有效成分 ATC 碼命中。只做身分對應，不構成推薦。",
        "atc.none": "已收錄的有效成分中沒有這個 ATC 碼或前綴。",
        "atc.none_meta": "{code} 沒有 ATC 命中",
        "atc.loading": "正在載入索引以進行 ATC 搜尋…",
        "home.sub": ("商品名、通用名、俗稱或包裝上一行字；支援中英文、全形、西里爾字母，"
                     "也可連劑量一起輸入，例如 Lipitor 20mg、泰諾、СОРТИС。"),
        "home.hint_idle": ("首次搜尋只載入目前首字元的一小片索引（約 0.2 MB），完整索引會在背景"
                           "補齊——直接輸入、點搜尋框或選一個範例。"),
        "home.hint_loading": "正在載入索引分片（約 0.2 MB）…",
        # v0.6.6：成分頁多國並排矩陣
        "matrix.spec": "規格 / 劑型 / 釋放",
        "matrix.none": "未收錄",
        "matrix.hidden_note": "已停售、撤市或狀態未確認的產品預設隱藏。",
        "matrix.capped": "僅顯示前 {shown} / {total} 個規格列。",
        # v0.6.7：/warn 分頁
        "warn.page_prev": "上一頁", "warn.page_next": "下一頁",
        "warn.pagination": "警示分頁",
        "warn.page_status": "第 {n} / {total} 頁 · 共 {count} 條",
        # v0.7.0：TW 市場（zh-Hant 直接給值，避免 JSON 未含時回落簡體）
        "home.tw": "台灣",
        "about.tw_source": (
            '<p class="sub"><b>台灣</b>：TFDA「全部藥品許可證資料集」（data.gov.tw 資料集 9122）'
            '依<b>政府資料開放授權條款第 1 版（OGDL v1.0）</b>釋出，須署名「衛福部食藥署 TFDA」；'
            '資料截止 <b>2026-10-22</b>（每週同步）。只存事實欄位（品名、成分、劑型、廠商、'
            '許可證號、狀態）。<b>規格由品名解析，置信度有限。</b>'
            '授權：<a href="https://data.gov.tw/license">data.gov.tw/license</a>。</p>'),
        # v0.7.x：SG 市場（英文市場；zh-Hant 直接給值）
        "home.sg": "新加坡",
        "about.sg_source": (
            '<p class="sub"><b>新加坡</b>：HSA「Listing of Registered Therapeutic Products」'
            '（data.gov.sg 資料集 d_767279312753558cbf19d48344577084）依<b>新加坡開放資料授權條款'
            '第 1 版（SODL v1.0）</b>釋出，須署名並鏈回授權頁，不得暗示政府背書；資料截止 '
            '<b>2026-08-07</b>（每 6 個月更新）。<b>在冊名單不代表在售。</b>商品名保留英文原文、'
            '不翻譯；中文僅成分名（inn_zh）可顯示。</p>'),
    },
}

# ── v0.6.4 B10：术语表 /glossary.html（四语，INN/BAN/USAN/ATC/MAH/DIN/NDC/ARTG/FDC/LASA…）──
GLOSSARY_I18N = {
    "en": {
        "glossary.title": "Glossary",
        "glossary.intro": ("Short definitions for the codes and terms you see on product labels, "
                           "regulator records and on this site. It is a decoding aid, not medical "
                           "advice."),
        "glossary.term": "Term", "glossary.def": "Meaning",
        "glossary.note": ("Same acronym can differ by country (e.g. a DIN is Canadian, an ARTG "
                          "number is Australian). Always read the code with its source."),
        "glossary.t.inn": "INN",
        "glossary.d.inn": ("International Nonproprietary Name: the WHO generic name for an active "
                           "ingredient (e.g. acetaminophen/paracetamol, metoprolol)."),
        "glossary.t.ban": "BAN",
        "glossary.d.ban": ("British Approved Name: the UK generic name, usually identical to INN; "
                           "a few older names differ (e.g. adrenaline for epinephrine)."),
        "glossary.t.usan": "USAN",
        "glossary.d.usan": ("United States Adopted Name: the US generic name; mostly INN, but "
                            "sometimes different (e.g. albuterol for salbutamol)."),
        "glossary.t.atc": "ATC code",
        "glossary.d.atc": ("Anatomical Therapeutic Chemical classification (WHO): a code such as "
                           "C07AB02. The first letters/numbers group by organ/system, class and "
                           "substance — useful for finding the same kind of drug across markets."),
        "glossary.t.mah": "MAH",
        "glossary.d.mah": ("Marketing Authorisation Holder: the company that holds the licence "
                           "for a product in a market; not necessarily the factory."),
        "glossary.t.din": "DIN",
        "glossary.d.din": ("Drug Identification Number: the Canadian product identifier; "
                           "DIN-HM is used for homeopathic products."),
        "glossary.t.ndc": "NDC",
        "glossary.d.ndc": ("National Drug Code: the US product identifier (labeler + product + "
                           "package segments)."),
        "glossary.t.artg": "ARTG",
        "glossary.d.artg": ("Australian Register of Therapeutic Goods number: identifies a "
                            "therapeutic good listed/registered for Australia."),
        "glossary.t.fdc": "FDC",
        "glossary.d.fdc": ("Fixed-Dose Combination: two or more active ingredients in one product "
                           "(e.g. metformin + glibenclamide). A combination page on this site."),
        "glossary.t.lasa": "LASA / tall-man",
        "glossary.d.lasa": ("Look-Alike, Sound-Alike drug names. FDA 'tall-man' lettering and the "
                            "confused-names list help avoid mix-ups between similar names."),
        "glossary.t.otc": "OTC",
        "glossary.d.otc": ("Over-the-counter: sold without a prescription in that market; the "
                           "same medicine may be prescription-only elsewhere."),
        "glossary.t.rx": "Rx",
        "glossary.d.rx": "Prescription-only medicine in that market.",
        "glossary.t.strength": "Strength",
        "glossary.d.strength": ("The amount of active ingredient per unit (e.g. 500 mg per "
                                "tablet); strengths and release forms can vary between markets."),
    },
    "es": {
        "glossary.title": "Glosario",
        "glossary.intro": ("Definiciones breves de los códigos y términos que aparecen en envases, "
                           "registros de reguladores y en este sitio. Ayuda para descifrar, no es "
                           "consejo médico."),
        "glossary.term": "Término", "glossary.def": "Significado",
        "glossary.note": ("El mismo acrónimo puede variar según el país (un DIN es canadiense, un "
                          "número ARTG es australiano). Lee siempre el código con su fuente."),
        "glossary.t.inn": "INN",
        "glossary.d.inn": ("Nombre genérico internacional (OMS) del principio activo; p. ej. "
                           "acetaminofeno/paracetamol, metoprolol."),
        "glossary.t.ban": "BAN",
        "glossary.d.ban": ("Nombre genérico británico; casi siempre igual al INN, con algunas "
                           "excepciones (adrenalina por epinefrina)."),
        "glossary.t.usan": "USAN",
        "glossary.d.usan": ("Nombre genérico adoptado en EE. UU.; normalmente INN, a veces "
                            "distinto (albuterol por salbutamol)."),
        "glossary.t.atc": "Código ATC",
        "glossary.d.atc": ("Clasificación Anatómica Terapéutica Química (OMS): código tipo "
                           "C07AB02; agrupa por órgano, clase y sustancia y ayuda a encontrar "
                           "fármacos equivalentes entre mercados."),
        "glossary.t.mah": "MAH",
        "glossary.d.mah": ("Titular de la autorización de comercialización: empresa que posee la "
                           "licencia del producto en un mercado; no siempre es la fábrica."),
        "glossary.t.din": "DIN",
        "glossary.d.din": ("Drug Identification Number: identificador de producto canadiense; "
                           "DIN-HM se usa para homeopáticos."),
        "glossary.t.ndc": "NDC",
        "glossary.d.ndc": ("National Drug Code: identificador de producto estadounidense "
                           "(etiquetador + producto + envase)."),
        "glossary.t.artg": "ARTG",
        "glossary.d.artg": ("Australian Register of Therapeutic Goods: número de registro "
                            "australiano del producto terapéutico."),
        "glossary.t.fdc": "FDC",
        "glossary.d.fdc": ("Combinación en dosis fija: dos o más principios activos en un mismo "
                           "producto (p. ej. metformina + glibenclamida)."),
        "glossary.t.lasa": "LASA / tall-man",
        "glossary.d.lasa": ("Nombres parecidos o que suenan igual. La tipografía tall-man de la "
                            "FDA y las listas de nombres confundibles ayudan a evitar errores."),
        "glossary.t.otc": "OTC",
        "glossary.d.otc": ("Venta libre: sin receta en ese mercado; el mismo medicamento puede "
                           "ser de prescripción en otro país."),
        "glossary.t.rx": "Rx",
        "glossary.d.rx": "Medicamento con receta en ese mercado.",
        "glossary.t.strength": "Concentración",
        "glossary.d.strength": ("Cantidad de principio activo por unidad (p. ej. 500 mg por "
                                "comprimido); concentraciones y formas pueden variar entre países."),
    },
    "zh": {
        "glossary.title": "术语表",
        "glossary.intro": ("包装、监管记录和本站里常见代码/术语的简短解释。只帮助读代码，不是医疗建议。"),
        "glossary.term": "术语", "glossary.def": "含义",
        "glossary.note": ("同一个缩写在不同国家含义可能不同（DIN 是加拿大、ARTG 是澳大利亚）；"
                          "看代码时务必连同来源一起看。"),
        "glossary.t.inn": "INN",
        "glossary.d.inn": "国际非专利名（WHO）：活性成分的全球通用名，如对乙酰氨基酚、美托洛尔。",
        "glossary.t.ban": "BAN",
        "glossary.d.ban": "英国批准名：通常与 INN 相同，少数旧名不同（如 adrenaline 对应 epinephrine）。",
        "glossary.t.usan": "USAN",
        "glossary.d.usan": "美国采用名：多数同 INN，个别不同（如 albuterol 对应 salbutamol）。",
        "glossary.t.atc": "ATC 码",
        "glossary.d.atc": ("ATC 解剖治疗化学分类（WHO），如 C07AB02：按器官系统、类别、成分分组，"
                           "便于跨市场找同类药。"),
        "glossary.t.mah": "MAH",
        "glossary.d.mah": "上市许可持有人：在某市场持有该产品许可的公司，不一定是生产工厂。",
        "glossary.t.din": "DIN",
        "glossary.d.din": "加拿大药品识别号；DIN-HM 用于顺势疗法产品。",
        "glossary.t.ndc": "NDC",
        "glossary.d.ndc": "美国国家药品代码（企业 + 产品 + 包装三段）。",
        "glossary.t.artg": "ARTG",
        "glossary.d.artg": "澳大利亚治疗用品登记号：标识在澳登记的治疗用品。",
        "glossary.t.fdc": "FDC",
        "glossary.d.fdc": "固定剂量复方：一个产品含两种或以上活性成分（如二甲双胍 + 格列本脲）。",
        "glossary.t.lasa": "LASA / tall-man",
        "glossary.d.lasa": "形似/音似药名。FDA 的 tall-man 大小写写法和易混淆药名表用于减少拿错药。",
        "glossary.t.otc": "OTC",
        "glossary.d.otc": "非处方药：在该市场无需处方；同一药在别国可能只作处方药。",
        "glossary.t.rx": "Rx",
        "glossary.d.rx": "该市场的处方药。",
        "glossary.t.strength": "规格/强度",
        "glossary.d.strength": "每单位活性成分含量（如每片 500 mg）；不同国家规格和释放剂型可能不同。",
    },
    "zh-Hant": {
        "glossary.title": "術語表",
        "glossary.intro": ("包裝、監管紀錄和本站裡常見代碼/術語的簡短解釋。只幫助讀代碼，不是醫療建議。"),
        "glossary.term": "術語", "glossary.def": "含義",
        "glossary.note": ("同一個縮寫在不同國家含義可能不同（DIN 是加拿大、ARTG 是澳大利亞）；"
                          "看代碼時務必連同來源一起看。"),
        "glossary.t.inn": "INN",
        "glossary.d.inn": "國際非專利名（WHO）：有效成分的全球通用名，如對乙醯氨基酚、美托洛爾。",
        "glossary.t.ban": "BAN",
        "glossary.d.ban": "英國批准名：通常與 INN 相同，少數舊名不同（如 adrenaline 對應 epinephrine）。",
        "glossary.t.usan": "USAN",
        "glossary.d.usan": "美國採用名：多數同 INN，個別不同（如 albuterol 對應 salbutamol）。",
        "glossary.t.atc": "ATC 碼",
        "glossary.d.atc": ("ATC 解剖治療化學分類（WHO），如 C07AB02：依器官系統、類別、成分分組，"
                           "便於跨市場找同類藥。"),
        "glossary.t.mah": "MAH",
        "glossary.d.mah": "上市許可持有人：在某市場持有該產品許可的公司，不一定是生產工廠。",
        "glossary.t.din": "DIN",
        "glossary.d.din": "加拿大藥品識別號；DIN-HM 用於順勢療法產品。",
        "glossary.t.ndc": "NDC",
        "glossary.d.ndc": "美國國家藥品代碼（企業 + 產品 + 包裝三段）。",
        "glossary.t.artg": "ARTG",
        "glossary.d.artg": "澳大利亞治療用品登記號：標識在澳登記的治療用品。",
        "glossary.t.fdc": "FDC",
        "glossary.d.fdc": "固定劑量複方：一個產品含兩種或以上有效成分（如二甲雙胍 + 格列本脲）。",
        "glossary.t.lasa": "LASA / tall-man",
        "glossary.d.lasa": "形似/音似藥名。FDA 的 tall-man 大小寫寫法和易混淆藥名表用於減少拿錯藥。",
        "glossary.t.otc": "OTC",
        "glossary.d.otc": "非處方藥：在該市場無需處方；同一藥在別國可能只作處方藥。",
        "glossary.t.rx": "Rx",
        "glossary.d.rx": "該市場的處方藥。",
        "glossary.t.strength": "規格/強度",
        "glossary.d.strength": "每單位有效成分含量（如每片 500 mg）；不同國家規格和釋放劑型可能不同。",
    },
}
# U1 防闪烁：首页 head 里在 body 解析前先打标记（localStorage flag → html.u1-off）。
U1_HEAD_JS = ("<script>try{if(localStorage.getItem('u1.dismiss.v1')==='1')"
              "document.documentElement.className+=' u1-off';}catch(e){}</script>")

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
            '<p>“Two frogs” (liǎng zhī qīngwā) is not a brand name and is never stored as one: it '
            'points to an ingredient, metformin. Nicknames are a separate, hand-maintained table — '
            'searchable, but deliberately kept out of the brand-name tables. When one matches, the '
            'page labels it (<i>internet nickname / older name</i>) and then lists that ingredient’s '
            'brands; it is never presented as a name printed on a pack. Every entry carries a '
            'source; “user-provided” is shown as <i>unverified</i> and is not promoted to '
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
            'sleeping pill (shuìqiányào), the pill, morning-after pill, statin. Unlike '
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
            '<div class="tablewrap"><table><tr><th>Country / region</th><th>Products</th>'
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
        "about.tw_source": (
            '<p class="sub"><b>Taiwan 台灣</b>: TFDA 「全部藥品許可證資料集」 (data.gov.tw '
            'dataset 9122) under <b>Open Government Data Licence v1.0 (OGDL v1.0)</b>; '
            'attribution required: 衛福部食藥署 TFDA. Data as of <b>2026-10-22</b> (weekly '
            'sync). Facts only (product name, ingredients, dosage form, manufacturer, licence '
            'number, status). <b>Strengths are parsed from product names, so confidence is '
            'limited.</b> Licence: <a href="https://data.gov.tw/license">data.gov.tw/license</a>.</p>'),
        "about.sg_source": (
            '<p class="sub"><b>Singapore 新加坡</b>: HSA <b>Listing of Registered Therapeutic '
            'Products</b> (data.gov.sg dataset d_767279312753558cbf19d48344577084) under the '
            '<b>Singapore Open Data Licence v1.0 (SODL)</b>; attribution and licence link '
            'required, no government endorsement implied. Data as of <b>2026-08-07</b> '
            '(updated every 6 months). <b>Being on the register does not mean the product is '
            'currently marketed.</b> Brand names stay in English and are never translated; only '
            'Chinese ingredient names (inn_zh) may be shown. Attribution: Contains information '
            'from Listing of Registered Therapeutic Products accessed on 2026-10-28 from Health '
            'Sciences Authority (HSA), and made available under the Singapore Open Data Licence '
            'v1.0 (<a href="https://data.gov.sg/open-data-licence">licence</a>).</p>'),
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
            'Traditional Chinese medicines (TCM) are not loaded.</li>'
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
            'Search terms (including queries that returned no result) are sent only as aggregate '
            'event names — the normalized query text, never linked to an account, IP address or '
            'device identifier. '
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
            '<p>«Dos ranas» (liǎng zhī qīngwā) no es un nombre comercial y nunca se guarda como tal: '
            'apunta a un principio activo, la metformina. Los apodos están en una tabla aparte '
            'mantenida a mano: se pueden buscar, pero se mantienen fuera de las tablas de nombres '
            'comerciales. '
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
            'pill, blood thinner, pastilla para dormir, «la píldora», «la píldora del día '
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
            '<div class="tablewrap"><table><tr><th>País / región</th><th>Productos</th>'
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
        "about.tw_source": (
            '<p class="sub"><b>Taiwán 台灣</b>: TFDA «全部藥品許可證資料集» (data.gov.tw, '
            'conjunto 9122) bajo la <b>Licencia de Datos Gubernamentales Abiertos v1.0 '
            '(OGDL v1.0)</b>; atribución: 衛福部食藥署 TFDA. Datos hasta <b>2026-10-22</b> '
            '(sincronización semanal). Solo campos fácticos (nombre, principios, forma, '
            'fabricante, nº de licencia, estado). <b>Las concentraciones proceden del análisis '
            'de los nombres de producto, con confianza limitada.</b> Licencia: '
            '<a href="https://data.gov.tw/license">data.gov.tw/license</a>.</p>'),
        "about.sg_source": (
            '<p class="sub"><b>Singapur 新加坡</b>: HSA <b>Listing of Registered Therapeutic '
            'Products</b> (data.gov.sg, conjunto d_767279312753558cbf19d48344577084) bajo la '
            '<b>Licencia de Datos Abiertos de Singapur v1.0 (SODL)</b>; se exige atribución y '
            'enlace a la licencia; no implica respaldo gubernamental. Datos hasta '
            '<b>2026-08-07</b> (actualización cada 6 meses). <b>Estar en el registro no significa '
            'que el producto esté actualmente comercializado.</b> Los nombres comerciales se '
            'conservan en inglés y no se traducen; solo los nombres chinos de principios activos '
            '(inn_zh) pueden mostrarse. Atribución: Contains information from Listing of '
            'Registered Therapeutic Products accessed on 2026-10-28 from Health Sciences '
            'Authority (HSA), and made available under the Singapore Open Data Licence v1.0 '
            '(<a href="https://data.gov.sg/open-data-licence">licencia</a>).</p>'),
        "about.samename": (
            '<h2>Por qué ocurre «mismo nombre, otro medicamento»</h2>'
            '<p class="sub">La misma marca pertenece a empresas distintas en cada mercado y la '
            'fórmula puede ser totalmente diferente. Ejemplos verificados: <b>Tylenol</b> en EE. UU. '
            'es paracetamol de un solo principio 500 mg, mientras que <b>泰诺</b> en China es un '
            'antigripal de cuatro principios y el producto de un solo principio es <b>泰诺林</b>; '
            '<b>Benadryl</b> en EE. UU. es difenhidramina y en el Reino Unido <b>Benadryl</b> '
            'es acrivastina; '
            '<b>Gaviscon</b> en EE. UU. es un antiácido de aluminio/magnesio y en el Reino Unido '
            'es una barrera de alginato.</p>'),
        "about.gaps": (
            '<h2>Lagunas conocidas</h2><ul class="sub">'
            '<li>China tiene 146.344 registros de medicamentos químicos, pero ~9% solo resuelven a '
            'una sustancia exclusiva de China (sin INN en inglés); su ATC se guarda en nivel 4. '
            'No se cargan los medicamentos chinos tradicionales (TCM).</li>'
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
            'búsqueda. Los términos de búsqueda (incluidas las búsquedas sin resultado) se envían '
            'solo como nombres de evento agregados: el texto normalizado de la consulta, nunca '
            'vinculado a una cuenta, dirección IP o identificador de dispositivo. '
            'Ver la <a href="https://www.goatcounter.com/privacy" target="_blank" '
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
            '<i>「网络俗称 / 旧名」</i>，再列该成分的商品名，绝不把它说成包装上的名字。每条都写出处；'
            '「用户提供」只算线索，公开页标<i>「未证实」</i>，找到独立出处后才升级为 '
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
            '（CN/GB/AU/ES）标<i>「社区叫法」</i>并保留检索。FDA 官方 tall-man 药对：'
            '@@CONFUSABLE@@ 对，<a href="confused.html">见列表</a>。</li></ul>'),
        "about.sources": (
            '<h2>数据来源与覆盖</h2>'
            '<div class="tablewrap"><table><tr><th>国家/地区</th><th>已收录产品</th>'
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
        "about.tw_source": (
            '<p class="sub"><b>台湾</b>：TFDA「全部藥品許可證資料集」（data.gov.tw 資料集 9122）'
            '依<b>政府資料開放授權條款第 1 版（OGDL v1.0）</b>釋出，須署名「衛福部食藥署 TFDA」；'
            '資料截止 <b>2026-10-22</b>（每週同步）。只存事實欄位（品名、成分、劑型、廠商、'
            '許可證號、狀態）。<b>規格由品名解析，置信度有限。</b>'
            '授權：<a href="https://data.gov.tw/license">data.gov.tw/license</a>。</p>'),
        "about.sg_source": (
            '<p class="sub"><b>新加坡</b>：HSA「Listing of Registered Therapeutic Products」'
            '（data.gov.sg 数据集 d_767279312753558cbf19d48344577084）依<b>新加坡开放数据许可'
            '第 1 版（SODL v1.0）</b>释出，须署名并链回许可页，不得暗示政府背书；数据截止 '
            '<b>2026-08-07</b>（每 6 个月更新）。<b>在册名单不代表在售。</b>商品名保留英文原文、'
            '不翻译；中文仅成分名（inn_zh）可显示。署名：Contains information from Listing of '
            'Registered Therapeutic Products accessed on 2026-10-28 from Health Sciences '
            'Authority (HSA), and made available under the Singapore Open Data Licence v1.0'
            '（<a href="https://data.gov.sg/open-data-licence">许可</a>）。</p>'),
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
            '搜索词（含无结果的查询）仅以聚合事件名发送——只含归一化查询文本，不与账号、IP 或'
            '设备标识关联。'
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
        "whatsnew.lang_note": ('Release notes are machine-translated (AI); the Chinese original in '
                               'CHANGELOG.md is authoritative.'),
        "whatsnew.pending": ('Chinese original only — English/Spanish translation pending.'),
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
        "whatsnew.lang_note": ('Las notas de versión están traducidas automáticamente (IA); el '
                               'original chino en CHANGELOG.md es la referencia.'),
        "whatsnew.pending": ('Solo original en chino — traducción al inglés/español pendiente.'),
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
        "whatsnew.lang_note": "英文/西语更新说明为 AI 机器翻译；中文原文（CHANGELOG.md）为准。",
        "whatsnew.pending": "中文原文；英/西语译文待补。",
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

# ── v0.5.5：页面 title / meta description / OG 本地化（en/es/zh）────────────
# 根页面（about/confused/warn/whats-new/首页）用 data-i18n-title / data-i18n-meta
# 让 i18n.js 在语言切换时同步 <title>、description、og:title/description；
# /es/、/zh/ 静态副本在构建期直接写入对应语言。
META_I18N = {
    "en": {
        "meta.index.title": "Medicine Brand Cross-Reference — drug names across countries",
        "meta.index.desc": ("Search a brand name, generic name or nickname and see the active "
                            "ingredient, strength, and the same product's names in other "
                            "countries. Public, non-commercial reference."),
        "meta.about.title": "About · Medicine Brand Cross-Reference",
        "meta.about.desc": ("How this cross-reference works: sources and coverage, licences and "
                            "attribution, known gaps and editorial rules. Reference only, not "
                            "medical advice."),
        "meta.confused.title": "Easily confused drug names · Medicine Brand Cross-Reference",
        "meta.confused.desc": ("FDA tall-man look-alike / sound-alike pairs: a warning about names, "
                               "not a statement that the drugs are interchangeable."),
        "meta.warn.title": "Warnings: same name, different drug · Medicine Brand Cross-Reference",
        "meta.warn.desc": ("Published warnings on same-name / different-drug products and "
                           "combinations that are not interchangeable across countries, salt "
                           "forms or release mechanisms. Information only."),
        "meta.whatsnew.title": "What's new · Medicine Brand Cross-Reference",
        "meta.whatsnew.desc": ("Release notes for the drug brand cross-reference: fixes and "
                               "additions in each version."),
    },
    "es": {
        "meta.index.title": ("Referencia cruzada de marcas de medicamentos: nombres en distintos "
                             "países"),
        "meta.index.desc": ("Busca un nombre comercial, genérico o un apodo y consulta el principio "
                            "activo, la concentración y los nombres del mismo producto en otros "
                            "países. Referencia pública y sin ánimo de lucro."),
        "meta.about.title": "Acerca de · Medicine Brand Cross-Reference",
        "meta.about.desc": ("Cómo funciona esta referencia cruzada: fuentes y cobertura, licencias "
                            "y atribución, lagunas conocidas y reglas editoriales. Solo "
                            "información, no consejo médico."),
        "meta.confused.title": ("Nombres de medicamentos fáciles de confundir · Medicine Brand "
                                "Cross-Reference"),
        "meta.confused.desc": ("Pares tall-man de la FDA con nombres parecidos o que suenan igual; "
                               "un aviso sobre nombres, no una afirmación de intercambiabilidad."),
        "meta.warn.title": ("Alertas: mismo nombre, otro medicamento · Medicine Brand "
                            "Cross-Reference"),
        "meta.warn.desc": ("Avisos publicados sobre productos con el mismo nombre y distinto "
                           "principio activo, y combinaciones no intercambiables entre países, "
                           "formas salinas o mecanismos de liberación."),
        "meta.whatsnew.title": "Novedades · Medicine Brand Cross-Reference",
        "meta.whatsnew.desc": ("Notas de versión de la referencia cruzada: correcciones y novedades "
                               "de cada versión."),
    },
    "zh": {
        "meta.index.title": "药品商品名跨国定位 — 跨国家/语言的药品名对照",
        "meta.index.desc": ("输入商品名、通用名或俗称，查它的活性成分、剂量，以及其他国家的商品名。"
                            "公开、非商业的参考站。"),
        "meta.about.title": "关于 · 药品商品名跨国定位",
        "meta.about.desc": ("本站如何工作：数据来源与覆盖、许可与署名、已知缺口与编辑规则。"
                            "仅供参考，不构成用药建议。"),
        "meta.confused.title": "易混淆药名 · 药品商品名跨国定位",
        "meta.confused.desc": "FDA tall-man 形似/音似药对；这是对名字的警示，不代表两种药可以互换。",
        "meta.warn.title": "警示：同名不同药 / 不可互换 · 药品商品名跨国定位",
        "meta.warn.desc": ("已发布的警示：同名不同药，以及跨国、盐型或释放机制下不可互换的复方"
                           "产品。"),
        "meta.whatsnew.title": "更新日志 · 药品商品名跨国定位",
        "meta.whatsnew.desc": "药品商品名跨国定位的版本更新说明。",
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
        for source in (ABOUT_I18N[lang], PAGE_I18N[lang], WARN_I18N[lang], COMBO_I18N[lang],
                       MAKER_I18N[lang], META_I18N[lang], GLOSSARY_I18N[lang],
                       ATC_I18N[lang], BILINGUAL_I18N[lang], FILTER_I18N[lang],
                       LABEL_I18N[lang], UI_I18N[lang]):
            for key, text in source.items():
                merged = text
                for ph, val in values.items():
                    merged = merged.replace("@@" + ph + "@@", str(val))
                I18N[lang][key] = merged


def _install_zh_hant(values: dict) -> None:
    """装载 zh-Hant 字典：简体 zh 兜底 + data/i18n_zh_hant.json 覆盖，并替换 @@占位符@@。

    必须在 _merge_static_i18n 之后调用（此时 zh 已含全部静态字典与动态占位符）。
    """
    base = dict(I18N.get("zh") or I18N["en"])
    overrides = _load_zh_hant_dict()
    merged: dict[str, str] = {}
    fallback = 0
    for key, text in base.items():
        value = overrides.get(key)
        if value is None:
            fallback += 1
            value = text
        merged[key] = _subst_placeholders(value, values)
    for key, text in overrides.items():
        if key not in merged:
            merged[key] = _subst_placeholders(text, values)
    # v0.6.3：U1/U2/U3 新 key 的 zh-Hant 值直接来自 build.py（不依赖 JSON 是否已补齐），
    # 避免新 key 回落到简体中文。
    for extra in (LABEL_I18N["zh-Hant"], UI_I18N["zh-Hant"], GLOSSARY_I18N["zh-Hant"],
                  ATC_I18N["zh-Hant"], BILINGUAL_I18N["zh-Hant"], FILTER_I18N["zh-Hant"]):
        for key, text in extra.items():
            merged[key] = _subst_placeholders(text, values)
    I18N["zh-Hant"] = merged
    print(f"i18n zh-Hant: {len(merged)} keys "
          f"({len(overrides)} from json, {fallback} fallback zh)", flush=True)


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

# ── 组合页（/combo/<成分集合slug>.html）三语文案 ─────────────────────
COMBO_I18N = {
    "en": {
        "combo.title": "Fixed-dose combination",
        "combo.intro": ('<p class="sub">This page lists brands whose active-ingredient set is '
                        'exactly the combination below. It is identity information only — a '
                        'fixed-dose combination is not the same product as its single '
                        'ingredients, and the brand names are not interchangeable across '
                        'markets.</p>'),
        "combo.ingredients": "Active ingredients",
        "combo.products": "Brands with this exact combination",
        "combo.no_advice": ('Not medical advice. Check the pack and the exact composition before '
                            'comparing products; ask a pharmacist if unsure.'),
        "combo.empty": "No brand names recorded for this combination yet.",
        "combo.capped": "Showing the first {cap} of {total} names.",
        "combo.source_note": ('<b>Source &amp; licence</b>: built from the same regulator data as '
                              'the ingredient pages (openFDA, dm+d, CIMA, COFEPRIS, PBS/TGA, '
                              'Health Canada DPD, NHSA). Facts only; see the '
                              '<a href="../about.html#licences">licence register</a>.'),
        "combo.see_warnings": "See warnings for these ingredients",
        "combo.no_page": "No separate brand page for this name",
        "combo.compact": "combination",
        # v0.6.0：跨市场同组合区块
        "combo.cross_title": "Same combination in other markets",
        "combo.cross_exact": ('These markets record products with the same active-ingredient '
                              'combination. Identity only — not a recommendation that products '
                              'are interchangeable.'),
        "combo.cross_products": "products",
        "combo.cross_record": "record",
        "combo.cross_overlap": ('The closest combination found in other markets is similar but '
                                'NOT identical — it is not interchangeable.'),
        "combo.cross_none": ('No product with this combination is recorded in the other covered '
                             'markets yet.'),
        "combo.cross_primary": ('Only the main ingredient is the same — this is NOT the same '
                                'fixed-dose combination.'),
        "combo.cross_primary_link": "View the main ingredient",
        "combo.cross_unmatched": ('Cross-market comparison is not available for this grouped '
                                  'name.'),
    },
    "es": {
        "combo.title": "Combinación en dosis fija",
        "combo.intro": ('<p class="sub">Esta página enumera las marcas cuyo conjunto de principios '
                        'activos es exactamente la combinación siguiente. Es solo información de '
                        'identidad: una combinación en dosis fija no es el mismo producto que sus '
                        'principios por separado, y los nombres comerciales no son intercambiables '
                        'entre mercados.</p>'),
        "combo.ingredients": "Principios activos",
        "combo.products": "Marcas con esta combinación exacta",
        "combo.no_advice": ('No es consejo médico. Comprueba el envase y la composición exacta '
                            'antes de comparar productos; consulta a un farmacéutico si dudas.'),
        "combo.empty": "Todavía no hay nombres comerciales para esta combinación.",
        "combo.capped": "Mostrando los primeros {cap} de {total} nombres.",
        "combo.source_note": ('<b>Fuente y licencia</b>: mismos datos regulatorios que las páginas '
                              'de principios activos (openFDA, dm+d, CIMA, COFEPRIS, PBS/TGA, '
                              'Health Canada DPD, NHSA). Solo hechos; ver el '
                              '<a href="../about.html#licences">registro de licencias</a>.'),
        "combo.see_warnings": "Ver alertas de estos principios",
        "combo.no_page": "Este nombre no tiene página de marca propia",
        "combo.compact": "combinación",
        # v0.6.0：跨市场同组合区块
        "combo.cross_title": "Misma combinación en otros mercados",
        "combo.cross_exact": ('Estos mercados registran productos con la misma combinación de '
                              'principios activos. Solo identidad — no es una recomendación de '
                              'intercambiabilidad.'),
        "combo.cross_products": "productos",
        "combo.cross_record": "registro",
        "combo.cross_overlap": ('La combinación más cercana en otros mercados es similar pero '
                                'NO idéntica: no son intercambiables.'),
        "combo.cross_none": ('Todavía no hay productos con esta combinación en los otros '
                             'mercados cubiertos.'),
        "combo.cross_primary": ('Solo coincide el principio principal — NO es la misma '
                                'combinación en dosis fija.'),
        "combo.cross_primary_link": "Ver el principio principal",
        "combo.cross_unmatched": ('La comparación entre mercados no está disponible para este '
                                  'nombre agrupado.'),
    },
    "zh": {
        "combo.title": "复方组合",
        "combo.intro": ('<p class="sub">本页列出「活性成分集合恰好等于下面这组」的商品名。'
                        '这里只做身份对应：复方产品≠各单方成分的简单相加，同名商品在不同'
                        '市场也不可互换。</p>'),
        "combo.ingredients": "活性成分",
        "combo.products": "属于该组合的商品名",
        "combo.no_advice": "这不是医疗建议。比较产品前请核对实际包装与完整成分；不确定时咨询药师。",
        "combo.empty": "该组合暂无已收录商品名。",
        "combo.capped": "仅显示前 {cap} / {total} 条。",
        "combo.source_note": ('<b>来源与许可</b>：与成分页使用同一批监管数据（openFDA、dm+d、'
                              'CIMA、COFEPRIS、PBS/TGA、Health Canada DPD、国家医保局）。'
                              '只做事实字段；见 <a href="../about.html#licences">许可清单</a>。'),
        "combo.see_warnings": "查看这些成分的警示",
        "combo.no_page": "这个名字没有独立品牌页",
        "combo.compact": "复方",
        # v0.6.0：跨市场同组合区块
        "combo.cross_title": "其他国家/地区的同组合",
        "combo.cross_exact": "这些市场收录了成分组合完全相同的产品。只做身份对应，不代表可以互换或替代。",
        "combo.cross_products": "个产品",
        "combo.cross_record": "记录",
        "combo.cross_overlap": "其他市场最接近的组合相近但并不完全相同——不可互换。",
        "combo.cross_none": "其他已收录市场暂无该成分组合的产品。",
        "combo.cross_primary": "仅主成分相同，这不是同一个复方组合。",
        "combo.cross_primary_link": "查看主成分",
        "combo.cross_unmatched": "这个合并后的名称暂无法做跨市场对照。",
    },
}

# ── v0.5.4：厂家页（/maker/<slug>.html）与结果行厂家链接 ─────────────
# 页数守卫：≥2 产品阈值会有 10,975 页；按 v0.5.3 基线（50,953 文件 / 279 MB）
# 预估会超过 400 MB，所以按任务约定降到 ≥5 产品（6,997 页），并在报告里记录。
MAKER_MIN_PRODUCTS = 5
MAKERS: dict[str, dict] = {}


# v0.5.4：厂家名规范化必须与 etl/build_maker_candidates.py 的 norm_key 完全一致，
# 否则 CSV 里的 maker_key 匹配不到 DB 的 product.mah（会漏建厂家页 / 链接失效）。
PUNCT_RE = re.compile(r"[.,;:'\"()\[\]{}&/\\|]+")
DASH_RE = re.compile(r"[-\u2010-\u2015\uff0d]+")


def norm_maker(s: str) -> str:
    """厂家名规范化：NFKC → 空白折叠 → casefold → 去标点 → 破折号→'-'（与 data 任务一致）。"""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\u00a0", " ").strip()
    s = re.sub(r"\s+", " ", s)
    s = s.casefold()
    s = PUNCT_RE.sub(" ", s)
    s = DASH_RE.sub("-", s)
    return re.sub(r"\s+", " ", s).strip()


def load_makers(threshold: int = MAKER_MIN_PRODUCTS) -> dict[str, dict]:
    """data/maker_candidates.csv → {norm_key: {name, slug, n, has}}。

    只把 n_products >= threshold 且非占位（Special Order 等）的厂家标记 has=True。
    """
    import csv as _csv

    path = ROOT / "data" / "maker_candidates.csv"
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in _csv.DictReader(fh):
            if (row.get("is_placeholder") or "") == "1":
                continue
            key = (row.get("maker_key") or "").strip()
            slug = (row.get("slug") or "").strip()
            if not key or not slug:
                continue
            try:
                n = int(row.get("n_products") or 0)
            except ValueError:
                n = 0
            out[key] = {"name": row.get("maker_name") or key, "slug": slug, "n": n,
                        "has": n >= threshold}
    return out


MAKER_I18N = {
    "en": {
        "maker.title": "Manufacturer / marketing-authorisation holder",
        "maker.intro": ('<p class="sub">{name} — {products} products across {markets} markets, '
                        '{brands} brand names. Products are grouped by country; brand names link '
                        'to their brand page and ingredients to the ingredient or combination '
                        'page. It is the marketing-authorisation holder recorded by the regulator, '
                        'not necessarily the factory.</p>'),
        "maker.stats": '<p class="sub">{products} products · {markets} markets · {brands} brand names</p>',
        "maker.by_country": "Products by country",
        "maker.brand": "Brand",
        "maker.ingredient": "Active ingredient(s)",
        "maker.source": "Source",
        "maker.capped": "Showing the first {shown} of {total} products (ordered by country).",
        "maker.no_page": "No separate brand page",
        "maker.no_page_count": "{n} more manufacturer(s) without a page",
        "maker.empty": "No products recorded for this manufacturer.",
        "maker.source_note": ('<b>Source &amp; licence</b>: product rows link to the regulator '
                              'record (openFDA, dm+d, CIMA, COFEPRIS, PBS/TGA, Health Canada DPD, '
                              'NHSA); facts only — see the '
                              '<a href="../about.html#licences">licence register</a>.'),
    },
    "es": {
        "maker.title": "Fabricante / titular de la autorización de comercialización",
        "maker.intro": ('<p class="sub">{name} — {products} productos en {markets} mercados, '
                        '{brands} nombres comerciales. Los productos se agrupan por país; los '
                        'nombres comerciales enlazan a su página de marca y los principios activos '
                        'a la página del principio o de la combinación. Es el titular registrado '
                        'por el regulador, no necesariamente la fábrica.</p>'),
        "maker.stats": '<p class="sub">{products} productos · {markets} mercados · {brands} marcas</p>',
        "maker.by_country": "Productos por país",
        "maker.brand": "Marca",
        "maker.ingredient": "Principio(s) activo(s)",
        "maker.source": "Fuente",
        "maker.capped": "Mostrando los primeros {shown} de {total} productos (orden por país).",
        "maker.no_page": "Sin página de marca propia",
        "maker.no_page_count": "{n} fabricante(s) más sin página",
        "maker.empty": "No hay productos registrados para este fabricante.",
        "maker.source_note": ('<b>Fuente y licencia</b>: cada fila enlaza al registro del '
                              'regulador (openFDA, dm+d, CIMA, COFEPRIS, PBS/TGA, Health Canada '
                              'DPD, NHSA); solo hechos — ver el '
                              '<a href="../about.html#licences">registro de licencias</a>.'),
    },
    "zh": {
        "maker.title": "厂家 / 上市许可持有人",
        "maker.intro": ('<p class="sub">{name} —— 共 {products} 个产品，覆盖 {markets} 个市场、'
                        '{brands} 个品牌名。产品按国家分组；品牌名链到品牌页，成分链到成分页/'
                        '组合页。这里记录的是监管数据里的「上市许可持有人」，不一定是生产工厂。</p>'),
        "maker.stats": '<p class="sub">{products} 个产品 · {markets} 个市场 · {brands} 个品牌名</p>',
        "maker.by_country": "各国产品",
        "maker.brand": "品牌",
        "maker.ingredient": "活性成分",
        "maker.source": "来源",
        "maker.capped": "仅显示前 {shown} / {total} 个产品（按国家排序）。",
        "maker.no_page": "没有独立品牌页",
        "maker.no_page_count": "另有 {n} 个厂家暂无页面",
        "maker.empty": "该厂家暂无已收录产品。",
        "maker.source_note": ('<b>来源与许可</b>：产品行链到监管原始记录（openFDA、dm+d、CIMA、'
                              'COFEPRIS、PBS/TGA、Health Canada DPD、国家医保局）；只发布事实字段，'
                              '见 <a href="../about.html#licences">许可清单</a>。'),
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
    items_html = []
    for row in rows:
        items_html.append(
            f'<article class="warn-item" id="w-{esc(row["warning_id"])}">'
            + _warn_lang_blocks(row, sub_names, prefix="") + "</article>")
    # v0.6.7：客户端分页（10 条/页）。无 JS 时全部可见（优雅降级）；?page=N 刷新/分享保持。
    pager_js = """
(function(){
  var PAGE = 10;
  var list = document.getElementById('warnlist');
  var pager = document.getElementById('warnpager');
  if(!list || !pager) return;
  var items = Array.prototype.slice.call(list.querySelectorAll('article.warn-item'));
  var total = Math.ceil(items.length / PAGE);
  if(total <= 1) return;
  var T = window.T || function(k){ return k; };
  var params = new URLSearchParams(location.search);
  var cur = parseInt(params.get('page') || '1', 10);
  if(!cur || cur < 1) cur = 1;
  if(cur > total) cur = total;
  if(params.get('page') && String(cur) !== params.get('page')){
    try{ params.set('page', String(cur)); history.replaceState(null, '', '?' + params.toString()); }catch(e){}
  }
  function pageHref(n){
    var p = new URLSearchParams(location.search);
    p.set('page', String(n));
    p.delete('lang');
    var q = p.toString();
    return '?' + q;
  }
  items.forEach(function(el, i){
    el.style.display = (i >= (cur - 1) * PAGE && i < cur * PAGE) ? '' : 'none';
  });
  function link(n, label, cls, rel, disabled){
    if(disabled) return '<span class="' + cls + ' disabled" aria-disabled="true">' + label + '</span>';
    return '<a class="' + cls + '" href="' + pageHref(n) + '"' + (rel ? ' rel="' + rel + '"' : '') + '>' + label + '</a>';
  }
  var html = '<span class="pg-status" aria-live="polite">' +
    T('warn.page_status').replace('{n}', cur).replace('{total}', total).replace('{count}', items.length) +
    '</span>';
  html += link(cur - 1, '‹ ' + T('warn.page_prev'), 'pg-prev', 'prev', cur <= 1);
  for(var n = 1; n <= total; n++){
    if(n === cur) html += '<span class="pg-num on" aria-current="page">' + n + '</span>';
    else html += link(n, String(n), 'pg-num', '', false);
  }
  html += link(cur + 1, T('warn.page_next') + ' ›', 'pg-next', 'next', cur >= total);
  pager.innerHTML = html;
})();
"""
    body = f"""<h1 data-i18n="warn.title">{esc(I18N["en"]["warn.title"])}</h1>
<div data-i18n-html="warn.intro">{I18N["en"]["warn.intro"]}</div>
<div class="notice" data-i18n="warn.no_advice">{esc(I18N["en"]["warn.no_advice"])}</div>
<div data-i18n-html="warn.count">{I18N["en"]["warn.count"]}</div>
<div id="warnlist">{''.join(items_html) if items_html else '<p class="empty" data-i18n="warn.empty">No published warnings yet.</p>'}</div>
<nav id="warnpager" class="warnpager" aria-label="Warning pages" data-i18n-aria="warn.pagination"></nav>
<div class="notice warnbox" data-i18n-html="warn.source_note">{I18N["en"]["warn.source_note"]}</div>
<script>{pager_js}</script>"""
    html = page("Warnings", body, meta_key="warn", alternates=True,
                canonical_rel="warn.html", alt_rel="warn.html")
    _write_with_copies("warn.html", html, "warn")
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
<li><b>Taiwan 台灣 / Taiwán</b>: TFDA 「全部藥品許可證資料集」 (data.gov.tw dataset 9122) —
<b>Open Government Data Licence v1.0 (OGDL v1.0)</b>; attribution: 衛福部食藥署 TFDA
(<a href="https://data.gov.tw/license">data.gov.tw/license</a>); data as of <b>2026-10-22</b>
(weekly sync). 中文：依政府資料開放授權條款第1版釋出，須署名「衛福部食藥署 TFDA 全部藥品許可證
資料集」；只存事實欄位；規格由品名解析、置信度有限。ES: licencia OGDL v1.0 con atribución a la
TFDA; datos hasta 2026-10-22; concentraciones derivadas de los nombres de producto, con confianza
limitada.</li>
<li><b>Singapore 新加坡 / Singapur</b>: <b>Health Sciences Authority (HSA)</b> —
<b>Listing of Registered Therapeutic Products</b> (data.gov.sg dataset
d_767279312753558cbf19d48344577084) under the <b>Singapore Open Data Licence v1.0 (SODL)</b>;
attribution: Contains information from Listing of Registered Therapeutic Products accessed on
2026-10-28 from Health Sciences Authority (HSA), and made available under the Singapore Open Data
Licence v1.0 (<a href="https://data.gov.sg/open-data-licence">licence</a>); no government
endorsement implied. 中文：依新加坡開放資料授權條款第 1 版（SODL v1.0）釋出，須署名並鏈回授權頁；
資料截止 2026-08-07（每 6 個月更新）；在冊名單不代表在售；品牌名保留英文原文、不翻譯，中文僅
成分名可譯。ES: contiene información del registro de HSA bajo la SODL v1.0 con atribución;
datos hasta 2026-08-07; estar en el registro no implica comercialización.</li>
<li><b>WHO ATC/DDD Index</b>: ATC codes and hierarchy reference the <b>WHO Collaborating Centre
for Drug Statistics Methodology</b> ATC/DDD Index; the Index itself is copyrighted and is not
reproduced. Class/category names shown on ATC pages are editorial or AI-assisted translations,
not official WHO labels — the ATC code and WHO hierarchy are authoritative.
中文：ATC 码与层级引自 WHOCC ATC/DDD Index（版权归 WHOCC，不转载索引全文）；本站类别名是编辑/AI
辅助译名，不是 WHO 官方译名，以 ATC 码与 WHO 层级为准。
ES: los códigos y la jerarquía ATC remiten al ATC/DDD Index del WHOCC (con copyright, no se
reproduce); los nombres de clase son traducciones editoriales/asistidas por IA, no etiquetas
oficiales de la OMS.
<a href="https://atcddd.fhi.no/atc_ddd_index/">ATC/DDD Index</a></li>
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
header .wrap{display:flex;align-items:center;gap:16px;height:60px;flex-wrap:nowrap}
.logo{font-weight:700;font-size:16px;color:var(--fg);white-space:nowrap}
.logo-zh{font-weight:400;font-size:13px;color:var(--muted);margin-left:8px;white-space:nowrap}
/* v0.6.5：logo 中文副标题只在简体中文界面显示（en/es/zh-Hant 隐藏，移动端仍隐藏） */
html:not([lang="zh"]) .logo-zh{display:none}
.langs{margin-left:6px;font-size:13px;display:flex;align-items:center;gap:6px;
  white-space:nowrap;flex-wrap:nowrap}
.langs a{color:var(--muted);padding:1px 5px;border-radius:5px;white-space:nowrap;
  display:inline-flex;align-items:center}
.langs a.on{background:var(--accent);color:#fff}
nav{display:flex;gap:14px;font-size:14px;flex-wrap:nowrap;white-space:nowrap;align-items:center}
nav a{white-space:nowrap}
/* v0.8.2 task-118：宽屏一行；768–1023 允许换行（禁止单字竖排）；<768 汉堡菜单 */
@media (max-width:1099px) and (min-width:768px){
  header .wrap{height:auto;flex-wrap:wrap;gap:6px 12px;padding-top:8px;padding-bottom:8px}
  nav{order:3;flex-basis:100%;flex-wrap:wrap;gap:8px 12px;font-size:13px}
  .langs{margin-left:auto;order:2;gap:4px}
}
.nav-toggle{display:none;align-items:center;justify-content:center;min-width:40px;min-height:40px;
  font-size:18px;background:#fff;color:var(--fg);border:1px solid var(--line);border-radius:8px;
  cursor:pointer}
@media (max-width:767px){
  header .wrap{height:auto;flex-wrap:wrap;gap:8px 12px}
  .nav-toggle{display:inline-flex;margin-left:auto}
  header nav{display:none;order:3;width:100%;flex-wrap:wrap;gap:6px 14px;padding:4px 0 2px;
    font-size:14px}
  header.nav-open nav{display:flex}
  header nav a{display:inline-flex;align-items:center;min-height:40px;white-space:nowrap}
  .langs{margin-left:0;gap:6px}
  .langs a{min-height:40px;padding:4px 6px}
  .logo{font-size:15px}
  .logo-zh{display:none}
}
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
.tag.tw{color:#1f5c7a;border-color:#b7d5e3}
.tag.sg{color:#7a1f3d;border-color:#e3b7c5}
/* v0.8.1：双语对照开关/来源徽章/版本/原文 */
.bil-toggle{display:inline-flex;align-items:center;gap:4px;font-size:12px;
  color:var(--muted);margin:0 8px;cursor:pointer}
.bil-toggle input{width:14px;height:14px}
.tr-badge{display:inline-block;margin-left:6px;font-size:11px;padding:0 5px;
  border:1px solid var(--line);border-radius:6px;color:var(--muted);vertical-align:1px}
.tr-ver{font-size:11px;color:var(--muted);margin-left:4px}
.tr-orig{color:var(--muted);font-weight:400}
/* v0.7.x：ATC 类别 / 大类浏览 */
.atcgrid,.catgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));
  gap:8px;margin:10px 0}
.atccard{display:block;padding:8px 10px;border:1px solid var(--line);border-radius:10px;
  background:#fff;color:var(--fg);font-size:14px}
.atccard:hover{border-color:var(--accent)}
.atccard code{font-weight:700;margin-right:4px}
.atclist{columns:2;column-gap:24px}
.atclist li{break-inside:avoid;margin:2px 0}
@media (max-width:719px){ .atclist{columns:1} }
.catquick{margin:18px 0 6px}
.catquick h2{font-size:16px;margin:0 0 8px}
.catchip{display:inline-block;margin:0 8px 8px 0;padding:5px 10px;border:1px solid var(--line);
  border-radius:999px;background:#faf9f6;color:var(--fg);font-size:13px}
.catchip:hover{border-color:var(--accent)}
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
.release-pending{color:var(--warn);font-size:13px;margin:6px 0 0}
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
/* v0.5.6：A1 详情 / A3 盐型释放上下文 / B6 行级报告 / B7 导出工具条 */
.ctxwrap{margin-left:4px}
.ctx{display:inline-block;font-size:12px;line-height:1.5;padding:1px 7px;border-radius:999px;
 border:1px solid var(--line);color:var(--muted);margin:1px 4px 1px 0;white-space:nowrap}
.ctx.warn{color:var(--warn);border-color:#f0d3c4;background:#fff6e8}
a.ctx:hover{text-decoration:none;border-color:var(--accent);color:var(--accent)}
.rowreport{display:inline-block;margin-left:6px;font-size:13px;color:var(--muted);text-decoration:none}
.rowreport:hover{color:var(--warn);text-decoration:none}
.detbtn{margin-left:6px;font-size:12px}
.restools{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:10px 0 0}
.restools .exportnote{color:var(--muted);font-size:12px}
table.det{margin:4px 0 8px;font-size:13px;background:#faf9f6;border:1px solid var(--line);
 border-radius:8px;overflow:hidden}
table.det th{background:#f4f2ec;font-size:11px}
table.det td{padding:5px 8px;vertical-align:top}
tr.detrow>td.detcell{padding:4px 8px 10px;background:#faf9f6}
tr.detrow table.det{margin:0}
/* v0.6.3 U1：首屏 3 步引导（v0.8.2 task-115：移到搜索框正下方、国家行之前；层级增强） */
.u1guide{border:1px solid var(--line);border-radius:12px;background:#fff;
 padding:16px 18px;margin:12px 0 2px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.u1head{display:flex;align-items:baseline;gap:10px}
.u1head h2{margin:0;font-size:18px;font-weight:700;letter-spacing:.01em}
.u1close{margin-left:auto;background:none;border:0;color:var(--muted);font-size:20px;
 line-height:1;padding:6px 8px;min-width:36px;min-height:36px;cursor:pointer}
.u1close:hover{color:var(--fg)}
.u1steps{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:12px 0 0;
 padding:0;list-style:none}
.u1step{border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:#faf9f6}
.u1step b{display:block;font-size:15px;margin:0 0 3px}
.u1step .sub{margin:4px 0 0;font-size:13px}
.u1try{margin-top:6px;font-size:12px;color:var(--muted)}
.u1try button{padding:3px 8px;font-size:12px;margin:2px 4px 2px 0;border-radius:8px}
html.u1-off #u1guide{display:none!important}
/* v0.8.2 task-116：搜索后收起「按大类浏览」 */
.catquick.cat-hidden{display:none!important}
/* v0.6.3 U2：结果顶部各国叫法横排（单成分唯一锚定时才渲染） */
.u2bar{border:1px solid var(--line);border-radius:12px;background:#fff;
 padding:10px 12px;margin:12px 0}
.u2head{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.u2head b{font-size:14px}
.u2head .sub{margin:0;font-size:12px}
.u2chips{display:flex;gap:8px;overflow-x:auto;-webkit-overflow-scrolling:touch;
 margin-top:8px;padding-bottom:2px}
.u2chip{flex:0 0 auto;display:flex;flex-direction:column;align-items:flex-start;gap:1px;
 background:#faf9f6;border:1px solid var(--line);color:var(--fg);border-radius:10px;
 padding:6px 10px;font-size:12px;cursor:pointer;text-align:left;min-width:0;max-width:220px}
.u2chip:hover{border-color:var(--accent)}
.u2chip.on{border-color:var(--accent);background:#f1f8f4}
.u2chip .u2c{font-weight:600;color:var(--muted);font-size:11px}
.u2chip .u2n{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px}
.u2chip .u2n.empty{color:var(--muted);font-style:italic}
/* v0.6.6：成分页多国并排矩阵（行=规格/剂型/释放，列=国家；服务端默认 en 序，客户端按语言重排） */
.matwrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:10px 0}
table.matrix{width:100%;border-collapse:collapse;min-width:860px}
table.matrix th,table.matrix td{border:1px solid var(--line);padding:6px 8px;
  text-align:left;vertical-align:top;font-size:14px}
table.matrix thead th{white-space:nowrap;font-weight:650}
table.matrix td.m-spec{white-space:nowrap;background:#faf9f6}
table.matrix .m-brand{display:-webkit-box;-webkit-box-orient:vertical;
  -webkit-line-clamp:2;overflow:hidden;max-width:220px;margin:0 6px 2px 0;
  vertical-align:top;line-height:1.35}
.m-en{display:inline-block;margin:0 6px 2px 0;font-size:11px;color:var(--muted)}
.m-zh{display:inline-block;margin:0 0 2px 0;font-size:11px;color:var(--muted)}
/* v0.8.4 task-128：状态彩色角标（A1 明细等） */
.st-badge{display:inline-block;font-size:11px;padding:1px 6px;border-radius:999px;
  border:1px solid var(--line);margin-right:4px;white-space:nowrap}
.st-active{color:#0b6b53;border-color:#a9d3c5;background:#eef7f3}
.st-discontinued{color:#8a4b12;border-color:#e6c9a2;background:#fff6e8}
.st-withdrawn{color:#8a2c1f;border-color:#e6bdb4;background:#fdf0ee}
.st-unknown{color:var(--muted);background:#f6f5f2}
.c-brand{overflow-wrap:anywhere}
.matrix-brand-note{margin:6px 0 0;font-size:12px}
/* v0.8.3 task-119：矩阵筛选器 */
.matrix-filters{margin:10px 0 6px;border:1px solid var(--line);border-radius:10px;
  background:#fff;padding:10px 12px}
.mf-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.mf-title{font-weight:600;font-size:14px}
.mf-count{color:var(--muted);font-size:13px}
.mf-toggle{margin-left:auto}
.mf-panel{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));
  gap:8px 14px;margin-top:10px}
.mf-field{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted)}
.mf-field select,.mf-field input[type=search]{padding:6px 8px;border:1px solid var(--line);
  border-radius:8px;font-size:13px;background:#fff;color:var(--fg)}
.mf-countries{display:flex;flex-wrap:wrap;gap:4px 10px;font-size:13px;color:var(--fg)}
.mf-countries label{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}
.mf-reset{border:1px solid var(--line);background:#fff;color:var(--fg);border-radius:8px;
  padding:6px 12px;font-size:13px;cursor:pointer}
.matrix-sort-note{margin:4px 0 0;font-size:12px}
@media (max-width:767px){
  .matrix-filters .mf-panel{display:none}
  .matrix-filters.mf-open .mf-panel{display:grid}
  .mf-toggle{display:inline-flex;min-height:40px;align-items:center}
  .mf-field select,.mf-field input[type=search]{min-height:40px}
  .mf-countries label{min-height:36px}
}
@media (max-width:719px){
  table.matrix{min-width:840px}
  .matwrap{margin:8px 0}
}
@media (max-width:719px){
  .u1steps{grid-template-columns:1fr}
  .u1close{min-width:44px;min-height:44px}
  .u2chip{max-width:70vw}
}
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
  table.res tr.detrow{background:#faf9f6;border-color:#e7e5dc;padding:4px 8px}
  table.res tr.detrow>td.detcell{display:block;padding:0}
  table.det{display:block;overflow-x:auto;white-space:nowrap}
  .restools{margin-top:8px}
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
/* v0.5.3：品牌无页 → 不可点文本（不是链接，禁止回退 drug 页） */
.brand-plain{font-weight:600;color:var(--fg)}
/* v0.6.0：组合页跨市场同组合区块 */
.xlist{margin:6px 0 0;padding-left:18px;font-size:14px}
.xlist li{margin:3px 0}
.xlist .x-mkt{font-weight:600;color:var(--fg)}
/* v0.6.4 B10：术语表 */
dl.glossary{margin:10px 0;border-top:1px solid var(--line)}
dl.glossary dt{font-weight:650;margin:10px 0 2px}
dl.glossary dd{margin:0 0 4px;color:var(--muted)}
.atcbar code{font-size:13px}
/* v0.5.4：厂家列（可点厂家 + 「+N」展开列表） */
.maker-link{color:var(--accent)}
.maker-plain{color:var(--fg)}
.mah-toggle{font-size:12px;margin-left:4px;padding:0;text-decoration:underline}
.mah-list{margin:6px 0 0;padding-left:18px;font-size:13px}
.mah-list[hidden]{display:none}
.mah-list li{margin:2px 0}
.maker-page table.res{margin-top:6px}
.grp-name{font-weight:600}
a.grp-name{color:var(--accent)}
.warn-item{border:1px solid var(--line);border-radius:12px;background:#fff;
  padding:12px 14px;margin:10px 0}
.warn-item h3{margin:0 0 6px;font-size:16px;line-height:1.45}
.warn-item .warn-body{margin:0 0 8px}
.warn-item .warn-meta{color:var(--muted);font-size:13px;margin:0;overflow-wrap:anywhere}
.warn-item .badge{vertical-align:2px}
/* v0.6.7：/warn 分页（10 条/页；移动端 ≥40px 可点） */
.warnpager{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:16px 0 4px;font-size:14px}
.warnpager .pg-status{color:var(--muted);font-size:13px;margin-right:6px}
.warnpager a,.warnpager span{min-width:36px;min-height:36px;display:inline-flex;
  align-items:center;justify-content:center;padding:4px 9px;border:1px solid var(--line);
  border-radius:8px;color:var(--fg);background:#fff}
.warnpager a:hover{border-color:var(--accent)}
.warnpager .pg-num.on{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.warnpager .disabled{color:var(--muted);opacity:.5;cursor:not-allowed}
.drugwarn ul{margin:6px 0 4px;padding-left:20px}
@media (max-width:719px){
  .warn-item .warn-meta{font-size:12px}
  .warnpager{gap:6px}
  .warnpager a,.warnpager span{min-width:40px;min-height:40px;font-size:15px}
}
"""

APP_JS = r"""
const box = document.getElementById('q');
const out = document.getElementById('out');
const ctry = document.getElementById('country');
const meta = document.getElementById('meta');
const acEl = document.getElementById('ac');
const ctryLabel = document.getElementById('ctrylabel');
// v0.6.3 U1：首屏引导关闭记忆（localStorage flag；隐私模式失败也不影响关闭）
const u1El = document.getElementById('u1guide');
const u1CloseEl = document.getElementById('u1close');
if(u1El && u1CloseEl){
  u1CloseEl.addEventListener('click', function(){
    try{ localStorage.setItem('u1.dismiss.v1', '1'); }catch(e){}
    u1El.hidden = true;
  });
}
// v0.8.2 task-116：搜索时收起首页「按大类浏览」（空查询/清空恢复）
function setCatsHidden(hide){
  const el = document.querySelector('.catquick');
  if(!el) return;
  el.classList.toggle('cat-hidden', !!hide);
  el.setAttribute('aria-hidden', hide ? 'true' : 'false');
}
// v0.6.2：繁体输入归一（OpenCC 常用字子集，构建期从 data/zh_hant_t2s.json 注入）。
// 只影响匹配前的归一化，不改变用户看到的输入/结果/页面文案。
const T2S = __T2S_JSON__;
function toSimp(s){
  if(!s || !T2S || !/[\u4e00-\u9fff]/.test(s)) return s;
  var out = '';
  for(var i=0;i<s.length;i++){ var c = s.charAt(i); out += (T2S[c] || c); }
  return out;
}
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
// v0.8.2：零结果埋点 search0-<归一化查询>（去重/防抖/≤64 字符；空/单字符不发）
let SEARCH0_EV = null, SEARCH0_SENT = new Set();
function scheduleSearch0(q){
  const term = norm(splitDose(q)[0]);
  if(!term || term.length < 2 || SEARCH0_SENT.has(term)) return;
  clearTimeout(SEARCH0_EV);
  const box0 = document.getElementById('q');
  const want = box0 ? box0.value.trim() : '';
  SEARCH0_EV = setTimeout(()=>{
    const cur = document.getElementById('q');
    if(cur && cur.value.trim() !== want) return;
    if(SEARCH0_SENT.has(term)) return;
    SEARCH0_SENT.add(term);
    gcEvent('search0-' + term.slice(0,64));
  }, 900);
}
let IDX = [], NICKS = [], CONF = [], CATS = null;
// 搜索增强（task-28）：运行时候选层 + 拼音表懒加载状态，见 collectHits()/pinyinFetch()。
let SEARCH_LAYERS = null, PY_MAP = null, PY_P = null;
// P2 分片（task-36）：manifest + 已加载分片池；分片先出结果，核心随后后台加载补全。
let MANIFEST = null, MANIFEST_P = null, SHARD_CACHE = new Map();
let POOL_READY = false, POOL_FILES = new Set(), SUPPORT_P = null, SHARD_P = null;
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
  return toSimp(s||'').normalize('NFKC').toLowerCase()
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
// v0.6.4 A2：ATC 码/类前缀识别（C07 / C07A / C07AB02）。只接受字母开头+两位数字的形态，
// 不会把普通药名误判成 ATC；Dose 等后缀由 splitDose 先剥掉。
function atcQuery(raw){
  const s = String(raw || '').trim().toUpperCase();
  if(!/^[A-Z]\d{2}(?:[A-Z]{0,2}\d{0,2})?$/.test(s)) return '';
  return s.length >= 3 ? s : '';
}
function esc(s){
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
// v0.5.5：中文界面优先用索引里的中文成分名（xz 与 x 的 " + " 分段平行，
// 缺失/空串逐段回退英文；其它语言仍用英文 x）。
function ingredientLabel(e){
  const x = (e && (e.x || e.d)) || '—';
  // v0.8.2 task-120：优先当前语言译名（terms.json 由 bilingual.js 暴露；无则保留原名）
  if(window.LANG && window.LANG !== 'en' && window.BILINGUAL_TERMS
     && window.BILINGUAL_TERMS.sub && e && e.v){
    const ent = window.BILINGUAL_TERMS.sub[e.v];
    const tr = ent && ent[window.LANG];
    if(tr && tr.n) return tr.n;
  }
  if(window.LANG === 'zh' && e && e.xz && e.xz.length){
    const parts = String(x).split(' + ');
    if(e.xz.length === parts.length){
      return parts.map(function(p, i){
        return (e.xz[i] && String(e.xz[i]).trim()) ? e.xz[i] : p;
      }).join(' + ');
    }
  }
  return x;
}
// v0.5.3 点击目标规则（用户报 Excedrin 点品牌跳到 acetaminophen 页）：
//   品牌列 → name/<u>.html；没有品牌页就渲染成不可点文本，**绝不回退 drug 页**。
//   成分列 → 复方（索引 cu 字段）进 /combo/<slug>.html；单成分进 drug/<v>.html。
function brandHTML(e){
  let d = e && e.d != null ? String(e.d) : '';
  if(e && e.f){
    const f = labelOf('form', e.f, '');
    if(f && d.length > f.length && d.slice(-f.length) === f) d = d.slice(0, -f.length).trim();
  }
  const title = e && e.d != null ? e.d : '';
  if(e && e.u) return `<a data-brand="1" title="${esc(title)}" href="${BASE}name/${e.u}">${esc(d)}</a>`;
  return `<span data-brand="1" title="${esc(title)}" class="brand-plain">${esc(d)}</span>`;
}
function ingredientHTML(e, cls){
  const label = ingredientLabel(e);
  const orig = (e && (e.x || e.d)) || '';
  if(e.cu) return `<a class="${cls || ''}" href="${BASE}${e.cu}">${label}</a>`;
  if(e.v) return `<a class="${cls || ''}" data-sub-ingredient="${esc(e.v)}" data-sub-orig="${esc(orig)}" href="${BASE}drug/${e.v}.html">${label}</a>`;
  return `<span class="${cls || ''}">${label}</span>`;
}
// v0.5.4 厂家列：第一个厂家可点（索引 mu），「+N」展开其它带页厂家（索引 ml）；
// 没页的厂家显示为纯文本 / 汇总成「另有 K 家暂无页面」，绝不产生 404。
function makerHTML(e, T){
  const name = e && e.m ? e.m : '';
  if(!name) return '—';
  const first = e.mu
    ? `<a class="maker-link" href="${BASE}maker/${e.mu}.html">${esc(name)}</a>`
    : `<span class="maker-plain">${esc(name)}</span>`;
  const extraTotal = (e.mn || 1) - 1;
  if(extraTotal <= 0) return first;
  const extras = (e.ml && e.ml.length) ? e.ml : [];
  const items = extras.map(([n, s]) =>
    `<li><a class="maker-link" href="${BASE}maker/${s}.html">${esc(n)}</a></li>`).join('');
  const unlinked = extraTotal - extras.length;
  const tail = unlinked > 0
    ? `<li class="sub">${esc(T('maker.no_page_count').replace('{n}', String(unlinked)))}</li>`
    : '';
  return `<span class="mah-wrap">${first}`
    + `<button type="button" class="linkbtn mah-toggle" data-mah="1" aria-expanded="false">+${extraTotal}</button>`
    + `<ul class="mah-list" hidden>${items}${tail}</ul></span>`;
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
  const mah = makerHTML(r, T);
  return `<tr>
    <td class="c-ing">${ingredientHTML(r)}</td>
    <td class="c-dose" data-label="${esc(T('col.dose'))}">${r.d || '—'}</td>
    <td class="c-brand" data-label="${esc(T('col.brand'))}">${brandHTML(r)}${tags}${combo}${badge}</td>
    <td class="c-mah" data-label="${esc(T('col.mah'))}">${mah || '—'}</td></tr>`;
}
// ── UI P0 ③④：自动完成 / 解析条 / 成分分组 + 品牌折叠 + 加载更多 ──────
// 一条「品牌行」= 一个索引条目（同成分下的一个品牌/写法），剂量合并展示，
// 不再按每个规格各占一行；分组头显示成分与品牌数。
// ── v0.5.6：A3 盐型/释放上下文 + B6 行级报告 + A1 明细桶 + B7 导出 ─────────
function a3HintHTML(e, T){
  // 不可互换只来自已发布 dose_warning（R1/R2）；多盐型只做中性提示，不写结论。
  const bits = [];
  if(e.wi) bits.push(`<a class="ctx warn" href="${BASE}warn.html#w-${esc(e.wi)}">${esc(T('a3.incompat'))}</a>`);
  if(e.sl) bits.push(`<span class="ctx" title="${esc(e.sl)}">${esc(T('a3.salt'))} ${esc(e.sl)}</span>`);
  if(e.rl) bits.push(`<span class="ctx">${esc(T('a3.release'))} ${esc(e.rl)}</span>`);
  return bits.length ? ` <span class="ctxwrap">${bits.join(' ')}</span>` : '';
}
function rowReportURL(e){
  // 行级报告：不带 template=（GitHub issue form 会忽略 URL 的 body 预填），
  // 用空白 issue + body 按表单字段顺序；只带查询词/当前页面/行信息，无隐私数据。
  const q = (box && box.value ? box.value : '').trim();
  const page = location.href.split('#')[0];
  const body = [
    '**' + Tr('report.field_query') + '**: ' + q,
    '**' + Tr('report.field_page') + '**: ' + page,
    '**' + Tr('report.field_row') + '**: ' + (e.d || '') + ' · ' + (e.x || '') +
      ' · ' + ((e.c || []).join(', ')),
    '**' + Tr('report.field_expected') + '**: ',
    '**' + Tr('report.field_actual') + '**: ',
    '**' + Tr('report.field_pack') + '**: ',
  ].join('\n');
  return 'REPORT_REPO_PLACEHOLDER' + '/issues/new?labels=data-error'
    + '&title=' + encodeURIComponent(Tr('report.issue_title') + (q || e.d || ''))
    + '&body=' + encodeURIComponent(body);
}
function detBucketOf(e){ return (e && e.db) ? e.db : 'other'; }
function loadDetailBucket(bucket){
  // 懒加载：只在用户点「详情」时拉一个桶（最大 ~4 MB raw / ~0.9 MB gzip），并缓存。
  if(DET_CACHE.has(bucket)) return Promise.resolve(DET_CACHE.get(bucket));
  return fetchManifest().catch(()=>null).then(m => {
    const ver = (m && m.v) ? '?v=' + m.v : '';
    return fetchJSON(BASE + 'data/idx/detail-' + bucket + '.json' + ver);
  }).then(d => { DET_CACHE.set(bucket, d || {}); return d || {}; })
    .catch(() => { DET_CACHE.set(bucket, {}); return {}; });
}
function findEntryByKey(k){
  if(!RES_GROUPS) return null;
  for(const g of RES_GROUPS) for(const e of g.rows) if(e.k === k) return e;
  return null;
}
function labelOf(prefix, code, fallback){
  // v0.6.3 U3：受控词走 i18n key，未注册的长尾值原样显示（返回 fallback/code）。
  const c = (code == null ? '' : String(code));
  const k = prefix + '.' + c;
  const v = Tr(k);
  return (v === k) ? (fallback != null ? fallback : c) : v;
}
function detPanelHTML(payload, key, e, T){
  const rows = (payload && payload.k && payload.k[key]) || [];
  if(!rows.length){
    return `<span class="sub">${esc(T('a1.none'))}</span> `
      + (e && e.v ? `<a href="${BASE}drug/${encodeURIComponent(e.v)}.html">${esc(T('a1.goto'))}</a>` : '');
  }
  const body = rows.map(r => {
    const raw = (payload.p && payload.p[r[11]] != null) ? String(payload.p[r[11]]) : '';
    const url = raw + (r[10] || '');
    const status = (payload.t && payload.t[r[5]]) || r[5];
    const rel = (payload.r && payload.r[r[7]]) || '';
    const src = (payload.s && payload.s[r[11]]) || '';
    const strength = r[8] ? ' · ' + esc(r[8]) : '';
    return `<tr><td>${esc(r[1])}</td><td>${esc(r[3]) || '—'}${strength}</td>`
      + `<td><code>${esc(r[4]) || '—'}</code></td>`
      + `<td><span class="st-badge st-${esc(status)}">${esc(labelOf('drug.status', status, status))}</span>${r[6] ? ' · ' + esc(r[6]) : ''}${rel && rel !== 'none' ? ' · ' + esc(labelOf('release', rel, rel)) : ''}</td>`
      + `<td>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(src || T('a1.raw'))} ↗</a>` : '—'}</td></tr>`;
  }).join('');
  return `<table class="det"><thead><tr><th>${esc(T('a1.market'))}</th><th>${esc(T('a1.pack'))}</th>`
    + `<th>${esc(T('a1.approval'))}</th><th>${esc(T('a1.status'))}</th>`
    + `<th>${esc(T('a1.source'))}</th></tr></thead><tbody>${body}</tbody></table>`
    + (rows.length >= 12 ? `<p class="sub">${esc(T('a1.more'))}</p>` : '');
}
// B7：导出当前视图全部结果（含折叠/未加载更多的行），纯前端。
function exportRows(){
  const src = (LAST_DISPLAY && LAST_DISPLAY.length) ? LAST_DISPLAY : [];
  const out = [];
  for(const [, tier, e] of src){
    const link = e.u ? (BASE + 'name/' + e.u)
      : (e.v ? (BASE + 'drug/' + encodeURIComponent(e.v) + '.html') : '');
    out.push([e.x || e.d || '', e.d || '', (e.s || []).join(' / '),
              (e.c || []).join(', '), e.f || '', e.m || '', tier || '', link]);
  }
  return out;
}
function csvCell(v){
  const s = String(v == null ? '' : v);
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}
function toCSV(rows){ return '\ufeff' + rows.map(r => r.map(csvCell).join(',')).join('\r\n'); }
function toTSV(rows){ return rows.map(r => r.map(v => String(v == null ? '' : v)
  .replace(/[\t\r\n]/g, ' ')).join('\t')).join('\n'); }
function exportHeader(T){
  return [T('col.ing'), T('col.brand'), T('col.dose'), T('res.col_country'),
          T('res.col_form'), T('col.mah'), T('res.col_match'), T('res.col_link')];
}
function exportNote(msg){
  const el = document.getElementById('exportnote');
  if(!el) return;
  el.textContent = msg || '';
  if(msg) setTimeout(() => { if(el.textContent === msg) el.textContent = ''; }, 2500);
}
function downloadCSV(rows, T){
  const text = toCSV([exportHeader(T)].concat(rows));
  const blob = new Blob([text], {type: 'text/csv;charset=utf-8'});
  const a = document.createElement('a');
  const d = new Date().toISOString().slice(0, 10);
  a.href = URL.createObjectURL(blob);
  a.download = 'drug-crossref-' + d + '.csv';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function fallbackCopy(text){
  const ta = document.createElement('textarea');
  ta.value = text; ta.setAttribute('readonly', '');
  ta.style.position = 'fixed'; ta.style.left = '-9999px'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch(e) { ok = false; }
  ta.remove();
  return ok;
}
function copyTSV(rows, T){
  const text = toTSV([exportHeader(T)].concat(rows));
  const done = ok => exportNote(ok ? T('res.copied') : T('res.copy_fail'));
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(() => done(true)).catch(() => done(fallbackCopy(text)));
  } else {
    done(fallbackCopy(text));
  }
}
function brandRowHTML(e, T){
  const badge = e.l==='severe' ? `<span class="badge sev">${T('badge.severe')}</span>` :
                e.l==='warning' ? `<span class="badge warn">${T('badge.warning')}</span>` : '';
  const tags = (e.c || []).map(x=>`<span class="tag ${x.toLowerCase()}">${x}</span>`).join('');
  const combo = (e.x || '').indexOf(' + ') >= 0
    ? `<span class="tag combo">${T('badge.combo')}</span>` : '';
  const mah = makerHTML(e, T);
  const ds = (e.s && e.s.length) ? e.s.slice().sort((a,b)=>doseNum(a)-doseNum(b)) : [''];
  // v0.5.6：A3 上下文徽章、B6 行级报告、A1 明细展开按钮（e.n 条产品记录）
  const ctx = a3HintHTML(e, T);
  const det = (e.n ? `<button type="button" class="linkbtn detbtn" data-det="${esc(e.k)}" `
    + `aria-expanded="false">${esc(T('a1.expand'))}</button>` : '');
  const rep = `<a class="rowreport" href="${esc(rowReportURL(e))}" target="_blank"`
    + ` rel="noopener" title="${esc(T('row.report'))}" aria-label="${esc(T('row.report'))}">⚑</a>`;
  return `<tr class="br" data-k="${esc(e.k)}">
    <td class="c-ing c-empty"></td>
    <td class="c-dose" data-label="${esc(T('col.dose'))}">${esc(ds.join(' / ')) || '—'}</td>
    <td class="c-brand" data-label="${esc(T('col.brand'))}">${brandHTML(e)}${tags}${combo}${badge}${ctx}${det}${rep}</td>
    <td class="c-mah" data-label="${esc(T('col.mah'))}">${mah || '—'}</td></tr>`;
}
const RES_PAGE = 25;              // 每次「加载更多」新增的品牌行数
let RES_LIMIT = RES_PAGE;
let RES_EXPANDED = new Set();     // 已展开的分组下标
let RES_GROUPS = null;            // [{ing, tags:Set, rows:[entry]}]
let LAST_DISPLAY = [];            // v0.5.6 B7：当前视图全部命中（[score,tier,entry]）
const DET_CACHE = new Map();      // v0.5.6 A1：明细桶缓存（bucket → payload）
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
    html += `<tr class="grp"><td class="c-ing">${ingredientHTML(g.rows[0], 'grp-name')}`
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
  // v0.6.4 A2：ATC 码查询在解析条里明确说明「按 ATC 前缀匹配」，避免误读成药名匹配。
  if(parsed.atc) items.push(`<span class="pitem atcbar"><b>${esc(T('parse.atc'))}</b>`
    + `<code>${esc(parsed.atc)}</code> <span class="sub">${esc(T('atc.hint'))}</span></span>`);
  if(parsed.category) items.push(`<span class="pitem"><b>${esc(T('parse.category'))}</b>`
    + `${esc(parsed.category)} <span class="sub">${esc(T('parse.category_note'))}</span></span>`);
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
    if(it.atc){
      // v0.6.4 A2：ATC 码补全建议
      return `<div class="ac-item${i===AC_I?' on':''}" role="option" aria-selected="${i===AC_I}" data-i="${i}">`
        + `<span class="ac-name">${esc(it.atc)}</span>`
        + `<span class="ac-meta">${esc(T('atc.label'))} · ${it.count} ${esc(T('res.matched'))}</span></div>`;
    }
    const e = it.e;
    const tags = (e.c || []).slice(0, 3)
      .map(x=>`<span class="tag ${x.toLowerCase()}">${x}</span>`).join('');
    return `<div class="ac-item${i===AC_I?' on':''}" role="option" aria-selected="${i===AC_I}" data-i="${i}">`
      + `<span class="ac-name">${esc(e.d || e.k)}</span>`
      + `<span class="ac-meta">${esc(ingredientLabel(e))}${tags ? ' ' + tags : ''}</span></div>`;
  }).join('');
  acEl.classList.add('open');
  if(box.setAttribute) box.setAttribute('aria-expanded', 'true');
}
function acCompute(nq, rawName){
  if((!IDX_READY && !POOL_READY) || !nq || nq.length < 2) return [];
  // v0.6.4 A2：ATC 码/前缀补全（按 distinct 码聚合命中条目数）
  const atcQ = atcQuery(rawName || '');
  if(atcQ){
    const map = new Map();
    for(const e of IDX){
      const codes = e.atc;
      if(!codes) continue;
      for(const c of codes){
        if(c.indexOf(atcQ) !== 0) continue;
        const cur = map.get(c);
        if(cur) cur.count++;
        else map.set(c, {atc: c, count: 1});
      }
    }
    return Array.from(map.values())
      .sort((a,b)=> a.atc.length - b.atc.length || b.count - a.count)
      .slice(0, 8);
  }
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
  const rawName = splitDose(raw)[0];
  const nq = norm(rawName);
  if(nq.length < 2 && atcQuery(rawName) === ''){ AC_WANT = false; acClose(); return; }
  if(!IDX_READY && !POOL_READY){ AC_WANT = true; acClose(); if(!SHARD_P) loadIndex(); return; }  // 加载完成后补算（分片加载中不抢跑 core）
  AC_WANT = false;
  AC_T = setTimeout(()=>{ AC_ITEMS = acCompute(nq, rawName); AC_I = -1; acPaint(); }, 90);
}
function acSelect(i){
  const it = AC_ITEMS[i];
  if(!it) return;
  box.value = it.atc || it.e.d || it.e.k;
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
// ── v0.6.3 U2：结果顶部「各国叫法」横排（仅在唯一单成分时显示）──────────────
const U2_COUNTRIES = ['US', 'GB', 'CN', 'ES', 'MX', 'AU', 'CA', 'TW', 'SG'];
function u2Order(){
  // v0.7.0：国家 chips 按界面语言顺序（i18n.js 在 apply() 里暴露 window.COUNTRY_ORDER）
  const order = (typeof window !== 'undefined' && window.COUNTRY_ORDER) || [];
  const rank = (c) => { const i = order.indexOf(c); return i < 0 ? 99 : i; };
  return U2_COUNTRIES.slice().sort((a, b) => rank(a) - rank(b));
}
function anchorSubstance(hits, nicks){
  // 只认 exact/compact/prefix 的最佳命中；fuzzy/contains 或复方/多成分一律不锚定。
  // （gaviscon / benadryl 这类多结果在这里返回 null → 不显示逐国叫法，避免误配。）
  let best = null;
  for(const h of hits){
    if(h[1] === 'exact' || h[1] === 'compact' || h[1] === 'prefix'){ best = h; break; }
  }
  if(!best && hits.length === 1 && hits[0][1] !== 'fuzzy') best = hits[0];
  if(best){
    const e = best[2];
    const sids = (e.vs && e.vs.length) ? e.vs : [e.v];
    if(sids.length !== 1) return null;         // 复方/多成分 → 降级隐藏
    const anchor = sids[0];
    // 「结果唯一」校验：其它单成分命中也必须指向同一成分；出现第二个成分即隐藏
    // （benadryl 跨国成分不同、tylenol vs tylenol pm 这类必须不显示逐国叫法）。
    for(const h of hits.slice(0, 20)){
      const s2 = (h[2].vs && h[2].vs.length) ? h[2].vs : [h[2].v];
      if(s2.length === 1 && s2[0] && s2[0] !== anchor) return null;
    }
    return {sid: anchor};
  }
  if(!hits.length && nicks.length === 1 && nicks[0].v) return {sid: nicks[0].v};
  return null;
}
function countryNamesHTML(anchor, selected, T){
  if(!anchor) return '';
  const best = {};
  for(const e of IDX){
    const sids = (e.vs && e.vs.length) ? e.vs : [e.v];
    if(sids.length !== 1 || sids[0] !== anchor.sid) continue;   // 只要单成分条目
    for(const code of (e.c || [])){
      const cur = best[code];
      const better = !cur || (!!e.u && !cur.u) ||
                     ((!!e.u === !!cur.u) && (e.n || 0) > (cur.n || 0));
      if(better) best[code] = e;
    }
  }
  if(!U2_COUNTRIES.some(code => best[code])) return '';
  const chips = u2Order().map(code => {
    const hit = best[code];
    const on = code === selected ? ' on' : '';
    const head = `<button type="button" class="u2chip${on}" data-u2country="${code}"`
      + ` aria-pressed="${code === selected ? 'true' : 'false'}">`
      + `<span class="u2c">${esc(T('home.' + code.toLowerCase()))}</span>`;
    if(!hit){
      return head + `<span class="u2n empty" title="${esc(T('u2.none_hint'))}">`
        + `${esc(T('u2.none'))}</span></button>`;
    }
    let name = hit.d || hit.k;
    if(name.length > 28) name = name.slice(0, 28) + '…';
    return head + `<span class="u2n">${esc(name)}</span></button>`;
  }).join('');
  return `<div class="u2bar"><div class="u2head"><b>${esc(T('u2.title'))}</b>`
    + `<span class="sub">${esc(T('u2.hint'))}</span></div>`
    + `<div class="u2chips">${chips}</div></div>`;
}
// v0.6.4 A2：ATC 码查询独立渲染（不参与名称/别名/模糊匹配，避免误当药名）
function renderATC(atcCode, q){
  const T = window.T || (k=>k);
  syncURL(q);
  scheduleSearchEvent(q);
  RES_LIMIT = RES_PAGE; RES_EXPANDED = new Set(); RES_GROUPS = null;
  const bar = parseBarHTML({atc: atcCode}, T('parse.match.atc'));
  // 有对应类别页才链接（L1–L4）；L5 成分码（如 C07AB02）回退到其 L4 类别 C07AB
  let classCode = '';
  if(CATS && CATS.atc_codes){
    if(CATS.atc_codes.indexOf(atcCode) >= 0) classCode = atcCode;
    else if(atcCode.length === 7 && CATS.atc_codes.indexOf(atcCode.slice(0, 5)) >= 0)
      classCode = atcCode.slice(0, 5);
  }
  const classLink = classCode
    ? `<p class="sub"><a href="${BASE}atc/${esc(classCode)}.html">${esc(T('atc.view_class'))} (${esc(classCode)})</a></p>`
    : "";
  const repEl = document.getElementById('report');
  if(!IDX_READY){
    // ATC 聚合字段只在完整 core 里；分片阶段先显示加载提示，core 到位后重跑。
    out.innerHTML = bar + `<div class="notice">${esc(T('atc.loading'))}</div>`;
    loadIndex().then(ok => { if(ok && box.value.trim() === q) render(); });
    return;
  }
  const hits = [];
  for(const e of IDX){
    const codes = e.atc;
    if(codes && codes.some(c => c.indexOf(atcCode) === 0)) hits.push(e);
  }
  hits.sort((a,b)=> (b.n || 0) - (a.n || 0));
  const shown = hits.slice(0, 200);
  if(!shown.length){
    RES_GROUPS = null; LAST_DISPLAY = [];
    out.innerHTML = bar + `<div class="notice warnbox"><b>${esc(T('atc.none_meta').replace('{code}', atcCode))}</b> ${esc(T('atc.none'))}</div>` + classLink;
    meta.textContent = T('atc.none_meta').replace('{code}', atcCode);
    scheduleSearch0(q);
    if(repEl){ repEl.style.display = 'block'; const a = document.getElementById('reportLink'); if(a) a.href = reportURL(q); }
    return;
  }
  const display = shown.map(e => [1, 'atc', e]);
  RES_GROUPS = groupByIngredient(display);
  LAST_DISPLAY = display;
  out.innerHTML = bar
    + `<div class="notice atcbar">${esc(T('atc.hit').replace('{code}', atcCode).replace('{n}', String(hits.length)))}</div>`
    + `<div id="reswrap">${resultsTableHTML(T)}</div>` + classLink;
  meta.textContent = `${hits.length} ${T('res.matched')} · ${T('atc.label')} ${atcCode}`;
  if(repEl){ repEl.style.display = 'block'; const a = document.getElementById('reportLink'); if(a) a.href = reportURL(q); }
}
// v0.7.x：大类词匹配（中英西+繁中，精确/别名；不匹配药名）
// v0.7.x：大类词匹配（中英西+繁中，精确/别名；不匹配药名；忽略重音/空格）
function _catNorm(s){
  return String(s || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .replace(/\s+/g, '').toLowerCase();
}
function catHit(nq){
  if(!CATS || !CATS.categories || !nq) return null;
  const q = _catNorm(nq);
  if(q.length < 2) return null;
  for(const c of CATS.categories){
    const labels = [];
    const L = c.labels || {};
    for(const k in L){ if(L[k]) labels.push(L[k]); }
    for(const a of (c.aliases || [])){ if(a) labels.push(a); }
    for(const lb of labels){
      if(_catNorm(lb) === q) return c;
    }
  }
  return null;
}
function renderCategory(cat, q){
  const T = window.T || (k=>k);
  syncURL(q);
  scheduleSearchEvent(q);
  RES_LIMIT = RES_PAGE; RES_EXPANDED = new Set(); RES_GROUPS = null;
  const label = (cat.labels && (cat.labels[window.LANG] || cat.labels.en)) || cat.id;
  const bar = parseBarHTML({category: label}, T('parse.match.category'));
  const catUrl = BASE + String(cat.url || '');
  if(!IDX_READY){
    out.innerHTML = bar + `<div class="notice">${esc(T('atc.loading'))}</div>`;
    loadIndex().then(ok => { if(ok && box.value.trim() === q) render(); });
    return;
  }
  const prefs = cat.prefixes || [];
  const hits = [];
  for(const e of IDX){
    const codes = e.atc;
    if(codes && codes.some(c => prefs.some(p => c.indexOf(p) === 0))) hits.push(e);
  }
  hits.sort((a,b)=> (b.n || 0) - (a.n || 0));
  const shown = hits.slice(0, 200);
  const link = `<p class="sub"><a href="${esc(catUrl)}">${esc(T('atc.view_class'))}</a> · `
    + `${esc(T('cat.disclaimer'))}</p>`;
  if(!shown.length){
    RES_GROUPS = null; LAST_DISPLAY = [];
    out.innerHTML = bar + `<div class="notice warnbox">${esc(T('cat.no_data'))}</div>` + link;
    meta.textContent = T('res.none');
    scheduleSearch0(q);
    return;
  }
  const display = shown.map(e => [1, 'category', e]);
  RES_GROUPS = groupByIngredient(display);
  LAST_DISPLAY = display;
  out.innerHTML = bar + `<div class="notice">${esc(T('parse.category_note'))}</div>` + link
    + `<div id="reswrap">${resultsTableHTML(T)}</div>`;
  meta.textContent = `${hits.length} ${T('res.matched')} · ${T('parse.category')} ${label}`;
}
function render(){
  const q = box.value.trim();
  setCatsHidden(!!q);   // v0.8.2 task-116：有查询（结果/零结果）即收起大类块；清空恢复
  if(!q){ out.innerHTML=''; meta.textContent=''; syncURL('');
    const r0 = document.getElementById('report'); if(r0) r0.style.display='none'; return; }
  // v0.6.4 A2：ATC 码/类前缀优先走独立路径（C07 / C07A / C07AB02 …）
  const atcCode = atcQuery(splitDose(q)[0]);
  if(atcCode){ renderATC(atcCode, q); return; }
  const [nameQ, st] = splitDose(q);
  const nq = norm(nameQ);
  // v0.7.x：大类词（降压药 / antibiotics / …）→ 主题合集过滤 + 解析条说明
  const cat = catHit(nq);
  if(cat){ renderCategory(cat, q); return; }
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
  // P2：分片阶段先出结果；core 未到位时标记 partial，跨条目的区块延后到补全后
  const partial = !!(POOL_READY && !IDX_READY && !LEGACY);
  const matched = collectHits(nq, st, nicks, nickSids, onlyUnmapped, c);
  const hits = matched.hits;
  const fuzzyUsed = matched.fuzzyUsed;
  // 拼音兜底：拉丁查询零命中（或只有模糊命中）且拼音表未加载 → 懒加载 pinyin.json 后重跑一次。
  if(!nicks.length && !LEGACY && SEARCH_LAYERS && /^[a-z0-9 ]{2,}$/.test(nq) && !PY_MAP
     && (!hits.length || hits.every(h=>h[1]==='fuzzy'))){
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
  if(c && hits.length && !partial){
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
  if(partial) meta.textContent += ' · ' + T('res.partial');
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
  // v0.6.3 U2：各国叫法横排——只在结果能唯一锚定单成分时显示；
  // 多成分/多结果（gaviscon、benadryl）与 partial/模糊一律不渲染，避免误配。
  let countryBarHTML = '';
  if(!partial && !countryMiss && display.length){
    const anchor = anchorSubstance(display, nicks);
    if(anchor) countryBarHTML = countryNamesHTML(anchor, c, T);
  }
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
      members.map(e=>`<div class="card"><h3>${e.u ? `<a href="${BASE}name/${e.u}">${esc(e.d)}</a>` : `<b>${esc(e.d)}</b>`}</h3>
      <div class="meta">${esc(e.x)} · ${esc((e.s||[]).join(' / ')||'—')}</div></div>`).join('');
  }
  // 主结果：按成分聚合；同成分多品牌折叠（默认显示前 2 个品牌），
  // 超过 RES_PAGE 行时用「加载更多」分页，不再一刀切 40 行/80 行。
  let resHTML = '';
  if(!countryMiss && display.length){
    RES_GROUPS = groupByIngredient(display);
    LAST_DISPLAY = display;      // v0.5.6 B7：导出「当前视图全部行」，不受折叠/分页影响
    resHTML = `<div class="restools">`
      + `<button type="button" class="linkbtn" data-export="copy">${esc(T2('res.copy'))}</button>`
      + `<button type="button" class="linkbtn" data-export="csv">${esc(T2('res.csv'))}</button>`
      + `<span class="exportnote" id="exportnote" role="status" aria-live="polite"></span>`
      + `</div>`
      + `<div id="reswrap">${resultsTableHTML(T2)}</div>`;
  } else {
    LAST_DISPLAY = [];
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
        for(const d of ds) oRows.push({x:e.x, xz:e.xz, d:d, b:e.d, m:e.m, mn:e.mn, mu:e.mu, ml:e.ml,
                                   c:e.c, l:e.l, u:e.u, v:e.v, cu:e.cu});
      }
      sameHTML = `<h2>${T2('same.ing')}</h2>` +
        `<p class="sub">${T2('same.note')}</p>` +
        `<table class="res"><thead><tr>
          <th>${T2('col.ing')}</th><th>${T2('col.dose')}</th>
          <th>${T2('col.brand')}</th><th>${T2('col.mah')}</th>
        </tr></thead><tbody>${oRows.slice(0,80).map(rowHTML).join('')}</tbody></table>`;
    }
  }

  if(partial){ sameHTML = ''; extraHTML = ''; }   // 跨条目区块等 core 到位再补
  // v0.8.2：最终无结果 → search0-<q>（部分加载/国家缺失不提前发；去重防抖在 scheduleSearch0）
  if(!partial && !countryMiss && !display.length && !nicks.length && !confs.length){
    scheduleSearch0(q);
  }
  out.innerHTML = parseBarHTML(parsed, matchLabel) + countryBarHTML + confHTML + nickHTML + warnHTML
    + countryMissHTML + resHTML + sameHTML + extraHTML;
  // 产品层没命中时，再去 ARTG 名称层找「登记存在、成分未收录」的条目；
  // 选了澳洲但澳洲产品为空时同样触发（很多 listed OTC 只有 ARTG 名字）。
  const hasAU = display.some(x => ((x[2].c) || []).includes('AU'));
  if(!partial && ((!display.length && !countryMiss) || (c === 'AU' && !hasAU))){
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
  // v0.6.1：data/index.json 双写已停（过渡期可用 WRITE_LEGACY_INDEX=1 恢复）。
  // ?legacy=1（旧「启动即拉全量」行为）与默认路径都走 data/idx/core.json + decodeCore；
  // 失败时先尝试可选的 data/idx/legacy-mini.json（构建开关 WRITE_LEGACY_MINI=1），
  // 仍失败则抛出，交给 loadIndex() 的统一错误提示 + 重试按钮，不再请求 index.json。
  return fetchJSON(BASE + 'data/idx/core.json').then(decodeCore).catch(err=>{
    if(window.console && console.warn) console.warn('core index unavailable, try legacy-mini', err);
    return fetchJSON(BASE + 'data/idx/legacy-mini.json').then(decodeCore).catch(()=>{ throw err; });
  });
}

// ── P2 分片加载（task-36）───────────────────────────────────────────────
function fetchManifest(){
  if(MANIFEST) return Promise.resolve(MANIFEST);
  if(MANIFEST_P) return MANIFEST_P;
  MANIFEST_P = fetchJSON(BASE + 'data/idx/manifest.json').then(m=>{ MANIFEST = m; return m; })
    .catch(err=>{ MANIFEST_P = null; throw err; });
  return MANIFEST_P;
}
function loadSupport(){
  if(SUPPORT_P) return SUPPORT_P;
  SUPPORT_P = Promise.all([
    fetch(BASE + 'data/aliases.json').then(r=>r.json()).catch(()=>[]),
    fetch(BASE + 'data/confused.json').then(r=>r.json()).catch(()=>[]),
    fetch(BASE + 'data/categories.json').then(r=>r.json()).catch(()=>null)
  ]).then(([a,c,cat])=>{ NICKS = a || []; CONF = c || []; CATS = cat || null; return true; })
    .catch(()=>{ SUPPORT_P = null; return false; });
  return SUPPORT_P;
}
function shardKeyOf(nq){
  const ch = nq && nq[0];
  if(!ch) return null;
  if(ch >= 'a' && ch <= 'z') return ch;
  if(ch >= '0' && ch <= '9') return 'digit';
  if(/[\u3400-\u9fff]/.test(ch)) return (MANIFEST && MANIFEST.cjkInitials && MANIFEST.cjkInitials[ch]) || null;
  return 'other';
}
function shardsForQuery(nq){
  const key = shardKeyOf(nq);
  if(!key || !MANIFEST || !MANIFEST.buckets || !MANIFEST.buckets[key]) return null;
  const files = MANIFEST.buckets[key];
  if(key.indexOf('cjk-') === 0) return files.slice(0, 3);
  const hi = nq + '\uffff';
  const picked = files.filter(f=> f.first <= hi && f.last >= nq);
  return picked.length ? picked.slice(0, 3) : null;
}
function loadShards(files){
  const ver = (MANIFEST && MANIFEST.v) ? '?v=' + MANIFEST.v : '';
  return Promise.all(files.map(f=>{
    if(SHARD_CACHE.has(f.f)) return Promise.resolve(SHARD_CACHE.get(f.f));
    return fetchJSON(BASE + f.f + ver).then(arr=>{ SHARD_CACHE.set(f.f, arr); return arr; });
  })).then(parts=>{
    // core 已先一步到达：丢弃分片追加，保持 IDX 为完整索引（避免 pool 覆盖 core 导致索引错位）
    if(IDX_READY){
      for(const f of files) POOL_FILES.add(f.f);
      return IDX;
    }
    const pool = POOL_READY ? IDX.slice() : [];
    for(const part of parts) for(const e of part) pool.push(e);
    IDX = pool;
    POOL_READY = true;
    for(const f of files) POOL_FILES.add(f.f);
    return pool;
  });
}
function loadShardedIndex(q){
  const nq = norm(splitDose(q)[0]);
  return Promise.all([fetchManifest(), loadSupport()]).then(()=>{
    const files = shardsForQuery(nq);
    if(!files) throw new Error('no shard for query');
    return loadShards(files);
  });
}
function ensureCoreInBackground(){
  if(IDX_READY || IDX_P || LEGACY) return;
  try{ setTimeout(()=>{ loadIndex(true); }, 0); }catch(e){}
}
function loadIndex(quiet){
  if(IDX_READY) return Promise.resolve(true);
  if(IDX_P) return IDX_P;
  if(!LEGACY && !quiet) setHint(HINT_LOADING);
  IDX_P = Promise.all([loadMainIndex(), loadSupport()]).then(([d])=>{
    IDX=d||[]; IDX_READY=true; POOL_READY=false;
    setHint('');
    // 搜索增强（task-28）：索引到位后先派生轻量层（exact/前缀，~0.2s），
    // 重层（bigram/trigram）放到下一轮事件循环，避免阻塞首个结果渲染。
    if(!LEGACY){
      searchLayersBuildLight();
      searchLayersScheduleHeavy();
    }
    // 用户可能在索引加载期间已经输入了 ≥2 字：加载完成后补算自动完成。
    if(AC_WANT) acUpdate();
    // P2：分片已先出结果时，核心到位后自动补全（国家视图/同成分/模糊/拼音等）。
    if(quiet && box.value.trim()) render();
    return true;
  }).catch(err=>{
    // 失败后清掉缓存的 Promise，允许点「重试」重新发起。
    IDX_P = null;
    if(quiet && POOL_READY){
      if(window.console && console.warn) console.warn('core index unavailable (sharded view kept)', err);
      return false;
    }
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
  if(LEGACY){ loadIndex().then(ok => { if(ok) render(); }); return; }
  const q = box.value.trim();
  if(!q){ render(); return; }
  // v0.6.4 A2：ATC 码查询需要完整索引（分片里的条目不一定带 atc 聚合），先确保 core 到位。
  if(atcQuery(splitDose(q)[0])){ loadIndex().then(ok => { if(ok) render(); }); return; }
  const nq = norm(splitDose(q)[0]);
  if(POOL_READY){
    const files = shardsForQuery(nq);
    if(files && files.some(f=> !POOL_FILES.has(f.f))){
      loadShards(files).then(()=>{ render(); ensureCoreInBackground(); })
        .catch(()=>{ render(); ensureCoreInBackground(); });
    }else{
      render();
      ensureCoreInBackground();
    }
    return;
  }
  SHARD_P = loadShardedIndex(q).then(()=>{ render(); ensureCoreInBackground(); })
    .catch(()=> loadIndex().then(ok => { if(ok) render(); }));
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
  const mt = t.closest('[data-mah]');
  if(mt){
    // v0.5.4：厂家列「+N」展开/收起其它厂家（列表项都带厂家页链接）
    const wrap = mt.parentNode;
    const list = wrap && wrap.querySelector ? wrap.querySelector('.mah-list') : null;
    if(list){
      const willOpen = list.hasAttribute('hidden');
      if(willOpen) list.removeAttribute('hidden');
      else list.setAttribute('hidden', '');
      mt.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
    }
    return;
  }
  // v0.5.6 B7：复制表格 / 下载 CSV（当前视图全部结果，含折叠与未加载行）
  const ex = t.closest('[data-export]');
  if(ex){
    const rows = exportRows();
    if(ex.getAttribute('data-export') === 'csv') downloadCSV(rows, Tr);
    else copyTSV(rows, Tr);
    gcEvent('export-' + ex.getAttribute('data-export'));
    return;
  }
  // v0.5.6 A1：行下展开产品级明细（懒加载 detail-<bucket>.json，再次点击折叠）
  const detBtn = t.closest('[data-det]');
  if(detBtn){
    const k = detBtn.getAttribute('data-det');
    const tr = detBtn.closest('tr');
    const next = tr && tr.nextElementSibling;
    if(next && next.classList && next.classList.contains('detrow')){
      const willOpen = next.style.display === 'none';
      next.style.display = willOpen ? '' : 'none';
      detBtn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
      return;
    }
    const e = findEntryByKey(k) || {k: k, v: ''};
    const row = document.createElement('tr');
    row.className = 'detrow';
    row.innerHTML = `<td colspan="4" class="detcell">${esc(Tr('a1.loading'))}</td>`;
    tr.parentNode.insertBefore(row, tr.nextSibling);
    detBtn.setAttribute('aria-expanded', 'true');
    loadDetailBucket(detBucketOf(e)).then(payload => {
      const cell = row.querySelector('.detcell');
      if(cell) cell.innerHTML = detPanelHTML(payload, k, e, Tr);
    });
    return;
  }
  // v0.6.3 U2：点国家 chip = 切到该国国家视图（复用现有 ctry 状态 + URL + 统计）
  const u2c = t.closest('[data-u2country]');
  if(u2c){
    ctry.value = u2c.getAttribute('data-u2country');
    updateCtryLabel();
    render();
    gcEvent('country-' + ctry.value);
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
// v0.6.4 B9：`/` 聚焦搜索框、`Esc` 关闭建议/清空查询。
// 不拦截输入法 composition（isComposing / keyCode 229），也不在其它输入控件里抢键。
document.addEventListener('keydown', ev => {
  if(ev.defaultPrevented || ev.isComposing || ev.keyCode === 229) return;
  const t = ev.target || {};
  const tag = String(t.tagName || '').toLowerCase();
  const typing = tag === 'input' || tag === 'textarea' || tag === 'select' || t.isContentEditable;
  if(ev.key === '/' && !typing && !ev.ctrlKey && !ev.metaKey && !ev.altKey){
    ev.preventDefault();
    try{ box.focus(); box.select(); }catch(e){}
    return;
  }
  if(ev.key === 'Escape'){
    if(acEl && acEl.classList.contains('open')){ acClose(); ev.preventDefault(); return; }
    if(box.value){ box.value = ''; acClose(); render(); ev.preventDefault(); }
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
// 聚焦搜索框就先预取「分片支持文件」（manifest + 别名/易混淆），不预取 core。
box.addEventListener('focus', ()=>{ if(!IDX_READY && !POOL_READY && !LEGACY){ fetchManifest().catch(()=>{}); loadSupport(); } });
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


def _page_meta(lang: str, meta_key: str | None) -> tuple[str, str]:
    if not meta_key:
        return "", ""
    D = I18N.get(lang, I18N["en"])
    return (D.get(f"meta.{meta_key}.title", ""), D.get(f"meta.{meta_key}.desc", ""))


TERMS_SUB_IDS: set[str] = set()
BILINGUAL_TRANS: dict = {}

# v0.8.1：双语对照显示（独立脚本，避免改动 i18n.js 模板；所有页面 defer 加载）
BILINGUAL_JS = r"""
(function(){
  var T = window.T || function(k){ return k; };
  var TERMS = null, SHOW = true, OBS = null, OUT = null;
  try {
    var saved = localStorage.getItem('dsh.showOrig');
    SHOW = (saved === '0') ? false : (saved === '1') ? true : (window.LANG !== 'en');
  } catch(e) { SHOW = (window.LANG !== 'en'); }
  function url(){
    var pre = (typeof window.DSH_PREFIX === 'string') ? window.DSH_PREFIX : '';
    return pre + 'data/terms.json';
  }
  function load(){
    if(TERMS) return Promise.resolve(TERMS);
    return fetch(url()).then(function(r){ return r.json(); }).then(function(d){
      TERMS = d; expose(); return d;
    }).catch(function(){ return null; });
  }
  function expose(){ try { window.BILINGUAL_TERMS = TERMS; } catch(e) {} }
  function srcLabel(s){
    if(!s) return '';
    var k = 'bilingual.source.' + s;
    var v = T(k);
    return (v === k) ? s : v;
  }
  function applyOne(el){
    var sid = el.getAttribute('data-sub-ingredient');
    var orig = el.getAttribute('data-sub-orig');
    if(orig === null || orig === undefined){
      orig = el.textContent || '';
      el.setAttribute('data-sub-orig', orig);
    }
    el.querySelectorAll('.tr-badge,.tr-ver,.tr-orig').forEach(function(n){ n.remove(); });
    var ent = (TERMS && TERMS.sub && TERMS.sub[sid]) || null;
    var tr = ent && ent[window.LANG];
    if(!tr || !tr.n){ el.textContent = orig; return; }
    el.textContent = tr.n;
    var badge = document.createElement('span');
    badge.className = 'tr-badge';
    badge.textContent = srcLabel(tr.s);
    if(tr.u) badge.title = tr.u;
    el.appendChild(badge);
    if(tr.v){
      var ver = document.createElement('span');
      ver.className = 'tr-ver';
      ver.textContent = 'v' + tr.v;
      el.appendChild(ver);
    }
    if(SHOW && orig && orig !== tr.n){
      var o = document.createElement('span');
      o.className = 'tr-orig';
      o.textContent = ' (' + orig + ')';
      el.appendChild(o);
    }
  }
  function renderNames(){
    document.querySelectorAll('.nm[data-n-en]').forEach(function(el){      var en = el.getAttribute('data-n-en') || '';
      var zh = el.getAttribute('data-n-zh') || '';
      var zhh = el.getAttribute('data-n-zhh') || '';
      var es = el.getAttribute('data-n-es') || '';
      var lang = window.LANG || 'en';
      if(lang === 'zh') el.textContent = zh || (en + ' 暂无中文名');
      else if(lang === 'zh-Hant') el.textContent = zhh || (en + ' 暫無中文名');
      else if(lang === 'es') el.textContent = es || en;
      else el.textContent = en;
    });
  }
  window.renderBilingualNames = renderNames;
  function render(){
    if(!TERMS) { renderNames(); return; }
    if(OBS) OBS.disconnect();
    renderNames();
    document.querySelectorAll('[data-sub-ingredient]').forEach(applyOne);
    var note = T('bilingual.brand_note');
    document.querySelectorAll('[data-brand]').forEach(function(el){
      if(!note || note.indexOf('bilingual.') === 0) return;
      // v0.8.4：保留全名 title，把「非翻译」说明附加在后面（不覆盖）
      var full = el.getAttribute('data-title-full');
      if(full === null){
        full = el.getAttribute('title') || '';
        el.setAttribute('data-title-full', full);
      }
      el.setAttribute('title', full ? (full + ' — ' + note) : note);
    });
    var cb = document.getElementById('bilOrig');
    if(cb) cb.checked = SHOW;
    // task-114：英文副标题在英文界面隐藏（避免重复）
    document.querySelectorAll('.cat-en').forEach(function(el){
      el.style.display = (window.LANG === 'en') ? 'none' : '';
    });
    if(OBS && OUT) OBS.observe(OUT, {childList: true, subtree: true});
  }
  function injectToggle(){
    if(document.getElementById('bilToggle')) return;
    var nav = document.querySelector('header nav');
    if(!nav) return;
    var lab = document.createElement('label');
    lab.id = 'bilToggle';
    lab.className = 'bil-toggle';
    lab.innerHTML = '<input type="checkbox" id="bilOrig"> <span></span>';
    lab.querySelector('span').textContent = T('bilingual.toggle');
    var langs = nav.querySelector('.langs');
    nav.insertBefore(lab, langs || null);
    var cb = lab.querySelector('input');
    cb.checked = SHOW;
    cb.addEventListener('change', function(){
      SHOW = cb.checked;
      try { localStorage.setItem('dsh.showOrig', SHOW ? '1' : '0'); } catch(e) {}
      render();
    });
  }
  function initNavToggle(){
    if(document.getElementById('navToggle')) return;
    var header = document.querySelector('header');
    var nav = header ? header.querySelector('nav') : null;
    if(!header || !nav) return;
    var b = document.createElement('button');
    b.id = 'navToggle';
    b.type = 'button';
    b.className = 'nav-toggle';
    b.setAttribute('aria-label', T('nav.menu'));
    b.setAttribute('aria-expanded', 'false');
    b.textContent = '\u2630';
    var wrap = header.querySelector('.wrap') || header;
    wrap.insertBefore(b, nav);
    b.addEventListener('click', function(){
      var open = header.classList.toggle('nav-open');
      b.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }
  function initMatrixFilters(){
    document.querySelectorAll('.matwrap table.matrix').forEach(function(table){
      if(table.getAttribute('data-mf-init')) return;
      table.setAttribute('data-mf-init', '1');
      var wrap = table.closest('.matwrap');
      if(!wrap) return;
      var ths = Array.from(table.querySelectorAll('thead th[data-country]'));
      var rows = Array.from(table.querySelectorAll('tbody tr'));
      var countries = ths.map(function(th){ return th.getAttribute('data-country'); });
      var forms = {}, releases = {};
      rows.forEach(function(tr){
        var f = tr.getAttribute('data-form') || '';
        var r = tr.getAttribute('data-release') || '';
        if(f) forms[f] = 1;
        if(r && r !== 'none') releases[r] = 1;
      });
      var T = window.T || function(k){ return k; };
      function opt(v, label){ var o = document.createElement('option'); o.value = v; o.textContent = label; return o; }
      var box = document.createElement('section');
      box.className = 'matrix-filters';
      box.innerHTML = '<div class="mf-head"><span class="mf-title"></span>'
        + '<span class="mf-count" aria-live="polite"></span>'
        + '<button type="button" class="mf-toggle" aria-expanded="false"></button></div>'
        + '<div class="mf-panel"></div>';
      box.querySelector('.mf-title').textContent = T('matrix.filters');
      box.querySelector('.mf-toggle').textContent = T('matrix.mobile_filters');
      var panel = box.querySelector('.mf-panel');
      // 国家多选
      var cf = document.createElement('div'); cf.className = 'mf-field';
      cf.innerHTML = '<span></span><div class="mf-countries"></div>';
      cf.querySelector('span').textContent = T('matrix.country');
      var cbox = cf.querySelector('.mf-countries');
      countries.forEach(function(c){
        var lab = document.createElement('label');
        var cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = true;
        cb.setAttribute('data-mf-country', c);
        lab.appendChild(cb); lab.appendChild(document.createTextNode(' ' + c));
        cbox.appendChild(lab);
      });
      panel.appendChild(cf);
      // 剂型
      var ff = document.createElement('label'); ff.className = 'mf-field';
      ff.innerHTML = '<span></span><select data-mf-form></select>';
      ff.querySelector('span').textContent = T('matrix.form');
      var fsel = ff.querySelector('select');
      fsel.appendChild(opt('', T('matrix.all')));
      Object.keys(forms).sort().forEach(function(f){ fsel.appendChild(opt(f, f)); });
      panel.appendChild(ff);
      // 释放
      var rf = document.createElement('label'); rf.className = 'mf-field';
      rf.innerHTML = '<span></span><select data-mf-rel></select>';
      rf.querySelector('span').textContent = T('matrix.release');
      var rsel = rf.querySelector('select');
      rsel.appendChild(opt('', T('matrix.all')));
      Object.keys(releases).sort().forEach(function(r){ rsel.appendChild(opt(r, r)); });
      panel.appendChild(rf);
      // 规格搜索
      var sf = document.createElement('label'); sf.className = 'mf-field';
      sf.innerHTML = '<span></span><input type="search" data-mf-spec>';
      sf.querySelector('span').textContent = T('matrix.spec_search');
      var sinp = sf.querySelector('input');
      panel.appendChild(sf);
      // 重置
      var resetWrap = document.createElement('div'); resetWrap.className = 'mf-field';
      var reset = document.createElement('button'); reset.type = 'button'; reset.className = 'mf-reset';
      reset.textContent = T('matrix.reset');
      resetWrap.appendChild(reset); panel.appendChild(resetWrap);
      wrap.parentNode.insertBefore(box, wrap);
      var note = document.createElement('p'); note.className = 'sub matrix-sort-note';
      note.textContent = T('matrix.sort_note');
      box.parentNode.insertBefore(note, wrap);
      function current(){
        var cc = Array.from(cbox.querySelectorAll('input[type=checkbox]'));
        var sel = cc.filter(function(cb){ return cb.checked; })
                    .map(function(cb){ return cb.getAttribute('data-mf-country'); });
        return {countries: sel, form: fsel.value, rel: rsel.value,
                spec: sinp.value.trim().toLowerCase(), all: cc.map(function(cb){ return cb.getAttribute('data-mf-country'); })};
      }
      function apply(updateURL){
        var s = current();
        var visible = 0;
        rows.forEach(function(tr){
          var ok = true;
          if(s.form && (tr.getAttribute('data-form') || '') !== s.form) ok = false;
          if(s.rel && (tr.getAttribute('data-release') || '') !== s.rel) ok = false;
          if(s.spec && (tr.getAttribute('data-spec') || '').toLowerCase().indexOf(s.spec) < 0) ok = false;
          tr.style.display = ok ? '' : 'none';
          if(ok) visible++;
        });
        ths.forEach(function(th){
          var c = th.getAttribute('data-country');
          var show = s.countries.indexOf(c) >= 0;
          th.style.display = show ? '' : 'none';
          rows.forEach(function(tr){
            Array.from(tr.children).forEach(function(td){
              if(td.getAttribute('data-country') === c) td.style.display = show ? '' : 'none';
            });
          });
        });
        var cnt = box.querySelector('.mf-count');
        cnt.textContent = T('matrix.showing').replace('{n}', visible).replace('{total}', rows.length);
        if(updateURL){
          try{
            var p = new URLSearchParams(location.search);
            s.form ? p.set('mform', s.form) : p.delete('mform');
            s.rel ? p.set('mrel', s.rel) : p.delete('mrel');
            s.spec ? p.set('mspec', sinp.value.trim()) : p.delete('mspec');
            (s.countries.length === s.all.length) ? p.delete('mcountry') : p.set('mcountry', s.countries.join(','));
            history.replaceState(null, '', location.pathname + (p.toString() ? '?' + p.toString() : '') + location.hash);
          }catch(e){}
        }
      }
      // URL 初值
      try{
        var q = new URLSearchParams(location.search);
        var mc = (q.get('mcountry') || '').split(',').filter(Boolean);
        if(mc.length){
          cbox.querySelectorAll('input[type=checkbox]').forEach(function(cb){
            cb.checked = mc.indexOf(cb.getAttribute('data-mf-country')) >= 0;
          });
        }
        if(q.get('mform')) fsel.value = q.get('mform');
        if(q.get('mrel')) rsel.value = q.get('mrel');
        if(q.get('mspec')) sinp.value = q.get('mspec');
      }catch(e){}
      fsel.addEventListener('change', function(){ apply(true); });
      rsel.addEventListener('change', function(){ apply(true); });
      sinp.addEventListener('input', function(){ apply(true); });
      cbox.addEventListener('change', function(){ apply(true); });
      reset.addEventListener('click', function(){
        cbox.querySelectorAll('input[type=checkbox]').forEach(function(cb){ cb.checked = true; });
        fsel.value = ''; rsel.value = ''; sinp.value = '';
        apply(true);
      });
      box.querySelector('.mf-toggle').addEventListener('click', function(){
        var open = box.classList.toggle('mf-open');
        this.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
      apply(false);
    });
  }
  function start(){
    initNavToggle();
    injectToggle();
    initMatrixFilters();
    renderNames();
    load().then(render);
    OUT = document.getElementById('out');
    if(OUT && window.MutationObserver){
      OBS = new MutationObserver(function(){ if(TERMS) render(); });
      OBS.observe(OUT, {childList: true, subtree: true});
    }
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
  window.addEventListener('load', render);
  window.applyBilingualTerms = render;
})();
"""


def build_terms_json(db: sqlite3.Connection) -> dict[str, int]:
    """v0.8.1：从 ingredient_names_i18n.csv 生成客户端/页面用 data/terms.json。

    规则：只收 display_default_<lang>=1 且 machine_translated=0 的译名；无译名不写。
    """
    terms: dict = {"sub": {}, "meta": {"version": "", "counts": {}}}
    global TERMS_SUB_IDS
    path = ROOT / "data" / "ingredient_names_i18n.csv"
    counts: dict[str, int] = {}
    version = ""
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                sid = (row.get("substance_id") or "").strip()
                if not sid:
                    continue
                ent: dict = {"en": (row.get("inn_en") or "").strip()}
                for lang, nk, sk, uk, ck, dk in (
                        ("zh", "name_zh", "source_zh", "source_url_zh", "confidence_zh",
                         "display_default_zh"),
                        ("es", "name_es", "source_es", "source_url_es", "confidence_es",
                         "display_default_es"),
                        ("zh-Hant", "name_zh_hant", "source_zh_hant", "source_url_zh_hant",
                         "confidence_zh_hant", "display_default_zh_hant"),
                        ("pt", "name_pt", "source_pt", "source_url_pt", "confidence_pt",
                         "display_default_pt")):
                    if (row.get(dk) or "0").strip() != "1":
                        continue
                    if (row.get("machine_translated") or "0").strip() == "1":
                        continue
                    name = (row.get(nk) or "").strip()
                    if not name:
                        continue
                    ent[lang] = {"n": name, "s": (row.get(sk) or "").strip(),
                                 "u": (row.get(uk) or "").strip(),
                                 "c": (row.get(ck) or "").strip(),
                                 "v": (row.get("version") or "").strip()}
                    counts[lang] = counts.get(lang, 0) + 1
                if len(ent) > 1:
                    terms["sub"][sid] = ent
                    version = version or (ent.get("zh") or ent.get("es") or {}).get("v", "")
    terms["meta"]["version"] = version
    terms["meta"]["counts"] = counts
    TERMS_SUB_IDS = set(terms["sub"])
    global BILINGUAL_TRANS
    BILINGUAL_TRANS = terms
    (OUT / "data").mkdir(parents=True, exist_ok=True)
    (OUT / "data" / "terms.json").write_text(
        json.dumps(terms, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return counts


def page(title: str, body: str, prefix: str = "", lang: str = "en",
         alternates: bool = False, meta_key: str | None = None,
         canonical_rel: str = "", alt_rel: str = "", head_js: str = "") -> str:
    ver = f"{LATEST_VERSION} · {LATEST_DATE}" if LATEST_VERSION else "What's new"
    sw = "".join(
        f'<a data-lang="{code}" href="?lang={code}">{label}</a>' for code, label, _ in LANGS
    )
    alt = ""
    if alternates:
        # hreflang 必须带 GitHub Pages 的项目子路径（线上是 /drug-brand-crossref/），
        # 写 "/es/" 会指到域名根（404）。SITE_URL 已含末尾斜杠。
        alt = ("\n".join(
            f'<link rel="alternate" hreflang="{LANG_HREFLANG[code]}" '
            f'href="{SITE_URL}{LANG_PATH[code]}{alt_rel}">'
            for code, _l, _path in LANGS
        ) + f'\n<link rel="alternate" hreflang="x-default" href="{SITE_URL}{alt_rel}">'
          # v0.7.0：TW 市場的語言區別名（zh-TW → zh-hant 副本）
          + f'\n<link rel="alternate" hreflang="zh-TW" '
            f'href="{SITE_URL}{LANG_PATH["zh-Hant"]}{alt_rel}">')
    if meta_key:
        # v0.5.5：title / description / OG 本地化（根页用 data-i18n-*，副本构建期写死）
        loc_title, loc_desc = _page_meta(lang, meta_key)
        loc_title = loc_title or title
        locale = {"en": "en_US", "es": "es_ES", "zh": "zh_CN",
                  "zh-Hant": "zh_Hant"}.get(lang, "en_US")
        head_title = (f'<title data-i18n-title="meta.{meta_key}.title">'
                      f'{esc(loc_title)}</title>')
        head_extra = (
            f'\n<link rel="canonical" href="{SITE_URL}{canonical_rel}">'
            f'\n<meta name="description" content="{esc(loc_desc)}" '
            f'data-i18n-meta="meta.{meta_key}.desc">'
            f'\n<meta property="og:type" content="website">'
            f'\n<meta property="og:site_name" content="Medicine Brand Cross-Reference">'
            f'\n<meta property="og:title" content="{esc(loc_title)}" '
            f'data-i18n-meta="meta.{meta_key}.title">'
            f'\n<meta property="og:description" content="{esc(loc_desc)}" '
            f'data-i18n-meta="meta.{meta_key}.desc">'
            f'\n<meta property="og:url" content="{SITE_URL}{canonical_rel}">'
            f'\n<meta property="og:locale" content="{locale}">'
            f'\n<meta name="twitter:card" content="summary">')
    else:
        head_title = f'<title>{esc(title)} · Medicine Brand Cross-Reference</title>'
        head_extra = ""
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{head_title}{alt}{head_extra}
<link rel="stylesheet" href="{prefix}assets/style.css?v={BUILD_V}">
<script src="{prefix}assets/i18n.js?v={BUILD_V}"></script>
<script>window.DSH_PREFIX={prefix!r};</script>
<script defer src="{prefix}assets/bilingual.js?v={BUILD_V}"></script>{GC_TAG}{head_js}</head>
<body>
<header><div class="wrap">
  <a class="logo" href="{prefix}index.html">Medicine Brand Cross-Reference
    <span class="logo-zh">药品商品名跨国定位</span></a>
  <nav><a href="{prefix}index.html" data-i18n="nav.search">Search</a>
    <a href="{prefix}confused.html" data-i18n="nav.confused">Confused names</a>
    <a href="{prefix}warn.html" data-i18n="nav.warn">Warnings</a>
    <a href="{prefix}about.html" data-i18n="nav.about">About</a>
    <a href="{prefix}whats-new.html" data-i18n="nav.whatsnew">What's new</a>
    <a href="{prefix}glossary.html" data-i18n="nav.glossary">Glossary</a>
    <a href="{prefix}atc.html" data-i18n="nav.atc">ATC &amp; categories</a>
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


def _localize_copy(html: str, lang: str, meta_key: str, rel: str) -> str:
    """把根页面 HTML 变成 /es/、/zh/、/zh-hant/ 静态副本：本地化 head + 相对链接加 ../ 前缀。"""
    loc_title, loc_desc = _page_meta(lang, meta_key)
    html = re.sub(r'<html lang="[A-Za-z-]+">', f'<html lang="{lang}">', html, count=1)
    if loc_title:
        html = re.sub(r'<title[^>]*>.*?</title>',
                      f'<title data-i18n-title="meta.{meta_key}.title">'
                      f'{esc(loc_title)}</title>', html, count=1, flags=re.S)
    if loc_desc:
        html = re.sub(r'(<meta name="description"[^>]*content=")[^"]*(")',
                      lambda m: m.group(1) + esc(loc_desc) + m.group(2), html, count=1)
        html = re.sub(r'(<meta property="og:description"[^>]*content=")[^"]*(")',
                      lambda m: m.group(1) + esc(loc_desc) + m.group(2), html, count=1)
    if loc_title:
        html = re.sub(r'(<meta property="og:title"[^>]*content=")[^"]*(")',
                      lambda m: m.group(1) + esc(loc_title) + m.group(2), html, count=1)
    copy_url = SITE_URL + LANG_PATH.get(lang, lang + "/") + rel
    html = re.sub(r'(<link rel="canonical" href=")[^"]*(")',
                  lambda m: m.group(1) + copy_url + m.group(2), html, count=1)
    html = re.sub(r'(<meta property="og:url" content=")[^"]*(")',
                  lambda m: m.group(1) + copy_url + m.group(2), html, count=1)
    # 根页相对链接 → ../ 前缀（绝对 URL / #锚点 / ?参数 不改）
    html = re.sub(r'(?P<attr>href|src)="(?P<url>(?![a-zA-Z]+:|#|/|\?)[^"]*)"',
                  lambda m: f'{m.group("attr")}="../{m.group("url")}"', html)
    return html


def _write_with_copies(rel: str, html: str, meta_key: str) -> None:
    """写根页面 + /es/<rel>、/zh/<rel>、/zh-hant/<rel> 静态本地化副本（供 SEO/直接访问）。"""
    (OUT / rel).write_text(html, encoding="utf-8")
    for code, _label, path in LANGS:
        if not path:
            continue
        target = OUT / path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_localize_copy(html, code, meta_key, rel), encoding="utf-8")


# ------------------------------------------------------------ release notes
def _md_inline(text: str) -> str:
    s = esc(text)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)

    def _link(m):
        url = m.group(2)
        # v0.5.5：CHANGELOG 里的相对 docs/ 链接在站点产物里没有对应文件（会 404），
        # 统一改到仓库 blob；中文文件名 percent-encode（/es/、/zh/ 副本同样生效）。
        if url.startswith(("docs/", "../docs/", "./docs/")):
            from urllib.parse import quote
            url = REPORT_REPO + "/blob/main/" + quote(url.lstrip("./"))
        return f'<a href="{url}" target="_blank" rel="noopener">{m.group(1)}</a>'

    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, s)
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
    """v0.5.6：What's new **以 CHANGELOG.md 的全量版本为主列表**。

    data/release_notes_i18n.json 只覆盖到 v0.5.2，旧实现只遍历 JSON 导致
    v0.5.3/v0.5.4/v0.5.5 从正文消失（线上 smoke whats-new-version 失败）。
    现在的规则：
      1) 版本顺序永远以 CHANGELOG.md 为准（最新在上，含全部版本）；
      2) 有 JSON 译文的版本 → 渲染 zh/en/es 三个语言块（按界面语言只显示一块）；
      3) 没有译文的版本 → 显示 CHANGELOG 中文原文 + 「译文待补」提示。
    """
    parts = [f'<h1 data-i18n="whatsnew.title">{esc(I18N["en"]["whatsnew.title"])}</h1>',
             f'<div data-i18n-html="whatsnew.intro">{I18N["en"]["whatsnew.intro"]}</div>',
             f'<div class="notice" data-i18n="whatsnew.lang_note">'
             f'{esc(I18N["en"]["whatsnew.lang_note"])}</div>']
    data = None
    try:
        data = json.loads((ROOT / "data" / "release_notes_i18n.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    translations = {}
    if isinstance(data, dict):
        translations = {k: v for k, v in data.items()
                        if k != "_meta" and isinstance(v, dict)}
    pending_html = (f'<p class="sub release-pending" data-i18n="whatsnew.pending">'
                    f'{esc(I18N["en"]["whatsnew.pending"])}</p>')
    for r in load_releases():
        ver = r["version"]
        item = translations.get(ver)
        if item:
            blocks = []
            for lang in ("zh", "en", "es"):
                items = item.get(lang) or item.get("zh") or []
                lis = "".join(f"<li>{_md_inline(str(x))}</li>" for x in items)
                blocks.append(f'<div class="lang-block" data-lang-block="{lang}">'
                              f'<ul>{lis}</ul></div>')
            body_html = "".join(blocks)
        else:
            # 无 AI 译文的版本：中文原文 + 三语可见的「译文待补」提示
            body_html = r["html"] + pending_html
        parts.append(
            f'<section class="release"><h2>{esc(ver)}'
            f'<span class="rel-date">{esc(r["date"])}</span></h2>{body_html}</section>')
    html = page("What's new", "\n".join(parts), meta_key="whatsnew", alternates=True,
                canonical_rel="whats-new.html", alt_rel="whats-new.html")
    _write_with_copies("whats-new.html", html, "whatsnew")


def _norm_name(s: str) -> str:
    """名字归一化，只用于比较 key 与成分 INN 是否同一个词。"""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def combo_slug(sids) -> str:
    """成分集合 → 组合页文件名（稳定、可读、长度受控）。"""
    return key_file("+".join(sorted(sids)))


# ── v0.8.3 伪复方 build 层归并：base+salt 视为同一 base 成分（不写 DB）────────
SALT_WORDS = {
    "hydrochloride", "hydrobromide", "sodium", "potassium", "calcium", "magnesium",
    "phosphate", "sulfate", "sulphate", "citrate", "tartrate", "maleate", "fumarate",
    "succinate", "malate", "glutamate", "aspartate", "lactate", "acetate", "carbonate",
    "bicarbonate", "chloride", "iodide", "bromide", "nitrate", "oxide", "hydroxide",
    "hydrate", "dihydrate", "trihydrate", "monohydrate", "sesquihydrate", "anhydrous",
    "mesilate", "mesylate", "besylate", "besilate", "benzoate", "trometamol",
    "tromethamine", "disodium", "dipotassium", "dicalcium", "magnesium",
    "monohydrochloride", "dihydrochloride", "lysine", "arginine", "gluconate",
    "digluconate", "heptanoate", "enantate", "decanoate", "palmitate", "stearate",
    "oleate", "laurate", "propionate", "butyrate", "valerate", "undecylenate",
    "cypionate", "phenylpropionate", "nitrite", "sulfite", "bisulfate", "edetate",
    "gluceptate", "glycinate", "asparto", "pamoate", "embonate", "hemihydrate",
    "dihydrate", "monohydrate", "hyclate", "tetrahydrate", "edisylate", "estolate",
    "taurate", "xinafoate", "furoate", "aceponate", "dipropionate", "diacetate",
    "dibenzoate", "pivalate", "tebutate", "sodium", "potassium",
}
_SALT_ELEMENTS = {"sodium", "potassium", "calcium", "magnesium", "lithium", "iron",
                  "zinc", "copper", "aluminium", "aluminum", "barium", "selenium"}


def _salt_base_of(name: str) -> str:
    toks = _norm_name(name).split()
    while toks and toks[-1] in SALT_WORDS:
        toks.pop()
    return " ".join(toks)


# ── v0.6.0：组合页跨市场同组合（输入 data/combo_match_candidates.csv，构建期只读）──
# 归一化规则必须与 etl/build_combo_matches.py 保持一致，否则页面的原始 substance_id
# 集合无法反查到 CSV 里的「归一名数签名」。
_COMBO_SYNONYMS = {
    "paracetamol": "acetaminophen", "glyburide": "glibenclamide",
    "salbutamol": "salbutamol", "albuterol": "salbutamol",
    "adrenaline": "epinephrine", "noradrenaline": "norepinephrine",
    "frusemide": "furosemide", "lignocaine": "lidocaine",
    "hyoscine": "scopolamine", "rifampicin": "rifampin",
    "pethidine": "meperidine", "oestradiol": "estradiol",
    "ethinyloestradiol": "ethinylestradiol", "levothyroxine": "levothyroxine",
    "thyroxine": "levothyroxine",
    "clavulanate": "clavulanic-acid", "clavulanic": "clavulanic-acid",
    "amoxycillin": "amoxicillin", "cefalexin": "cephalexin",
    "cefalotin": "cephalothin", "vitamin-c": "ascorbic-acid",
}
_COMBO_SALT_WORDS = {
    "hydrochloride", "hydrobromide", "bromide", "chloride", "sodium", "potassium",
    "calcium", "magnesium", "zinc", "iron", "ammonium", "sulfate", "sulphate",
    "phosphate", "acetate", "citrate", "tartrate", "maleate", "fumarate",
    "succinate", "malate", "lactate", "gluconate", "nitrate", "mesylate",
    "besylate", "tosylate", "pamoate", "stearate", "palmitate", "propionate",
    "dipropionate", "valerate", "butyrate", "benzoate", "carbonate", "bicarbonate",
    "hydroxide", "oxide", "trihydrate", "dihydrate", "monohydrate", "hemihydrate",
    "anhydrous", "hydrate", "dehydrate", "methyl", "ethyl", "ester", "acid",
    "trometamol", "tromethamine", "meglumine", "lysine", "arginine", "choline",
    "disodium", "dipotassium", "hemisuccinate", "furoate", "cipionate",
    "phenylacetate", "hyclate", "pivoxil", "axetil", "proxetil", "medoxomil",
}
_RE_NONALNUM = re.compile(r"[^a-z0-9]+")


def norm_ingredient(name: str) -> str:
    """英文 INN → 归一成分 key（去括号/盐/酯/水合物 → 同义词；与 ETL 一致）。"""
    s = unicodedata.normalize("NFKC", name or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = s.replace("/", " ")
    toks = [t for t in _RE_NONALNUM.sub(" ", s).split() if t]
    out = [t for t in toks if t not in _COMBO_SALT_WORDS]
    if not out:
        out = toks
    key = "-".join(out) if out else (name or "").strip().lower()
    return _COMBO_SYNONYMS.get(key, key)


def load_combo_matches() -> dict[str, list[dict]]:
    """data/combo_match_candidates.csv → {signature: [country row, ...]}。"""
    import csv as _csv

    path = ROOT / "data" / "combo_match_candidates.csv"
    out: dict[str, list[dict]] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in _csv.DictReader(fh):
            sig = (row.get("signature") or "").strip()
            if sig:
                out.setdefault(sig, []).append(row)
    return out


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
    merged_keys: set[str] = set()
    # v0.8.3：base+salt 归并映射（严格规则：长名 = 短名 + 全部 salt 词，且 base 存在）
    sub_names: dict[str, tuple[str, str]] = {}
    for sid0, en0, zh0 in db.execute("SELECT substance_id, inn_en, inn_zh FROM substance"):
        sub_names[sid0] = (en0 or "", zh0 or "")
    by_norm: dict[str, str] = {}
    for sid0, (en0, _zh0) in sub_names.items():
        if en0:
            by_norm.setdefault(_norm_name(en0), sid0)
    # 同名重复 substance（如 povidone-iodine / povidone-iodine-<hash>）→ 规范到同一 sid
    canon: dict[str, str] = {}
    for sid0, (en0, _zh0) in sub_names.items():
        if en0:
            canon[sid0] = by_norm.get(_norm_name(en0), sid0)
    salt_to_base: dict[str, str] = {}
    for sid0, (en0, _zh0) in sub_names.items():
        if canon.get(sid0) != sid0:
            continue
        toks = _norm_name(en0).split()
        if len(toks) < 2:
            continue
        # 从末尾逐个去掉 salt/hydrate 词，找到存在的 base 即止
        # （不把 "Calcium Chloride" 剥成 "Calcium" 这类无机盐基；元素基跳过）
        while len(toks) > 1 and toks[-1] in SALT_WORDS:
            toks = toks[:-1]
            base = " ".join(toks)
            if base in SALT_WORDS or base in _SALT_ELEMENTS or len(base) < 4:
                continue
            b = by_norm.get(base)
            if b and b != sid0:
                salt_to_base[sid0] = b
                break
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
         inn_en, inn_zh, atc, sid, mah, rel, ntype, n_ing) in db.execute(
        """SELECT pn.key_id, p.product_id, p.country, p.form_base, p.dosage_form,
                  pc.strength_value, pc.strength_unit, s.inn_en, s.inn_zh, s.atc, s.substance_id,
                  p.mah, p.release,
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
        # v0.8.3：base+salt/canonical 递归归并（如 Alendronate Sodium Trihydrate →
        # Alendronate Sodium → Alendronate），直到不动点，避免只剥一层。
        orig_sid = sid
        seen_sids: set[str] = set()
        while sid not in seen_sids:
            seen_sids.add(sid)
            nxt = salt_to_base.get(sid) or canon.get(sid, sid)
            if nxt == sid:
                break
            sid = nxt
        if sid != orig_sid:
            inn_en, inn_zh = sub_names.get(sid, (inn_en, inn_zh))
            merged_keys.add(key_id)
        a = agg.get(key_id)
        if a is None:
            a = agg[key_id] = {"pids": set(), "c": set(), "subs": [], "subs_zh": [], "s": [],
                               "f": [], "v": sid, "mah": {}, "trade": False,
                               "sids": set(), "rels": set(), "atc": set()}
        if ntype == "trade":
            a["trade"] = True
        a["sids"].add(sid)
        if atc:
            # v0.6.4 A2：条目涉及的 ATC 码（多成分=数组；客户端按前缀过滤 ATC 搜索）
            a["atc"].add(atc.strip())
        if rel and rel != "none":
            # v0.5.6 A3：该名字下产品的释放机制集合（IR/ER/SR/DR/MR/GITS），空 = 全是常释
            a["rels"].add(rel)
        a["pids"].add(pid)
        a["c"].add(country)
        if inn_en not in a["subs"]:
            a["subs"].append(inn_en)
            # v0.5.5：与 x 的分段一一对应的中文名；没有中文名留 ""（客户端逐段回退英文）
            a["subs_zh"].append(inn_zh or "")
        if sv is not None:
            st = f"{sv:g} {su or ''}".strip()
            if st not in a["s"]:
                a["s"].append(st)
        f = form_base or dosage_form
        if f and f not in a["f"]:
            a["f"].append(f)
        if mah:
            a["mah"][mah] = a["mah"].get(mah, 0) + 1

    # v0.5.6（A3/A1）：盐型上下文 + 已发布 R1/R2 警示 id + 明细桶名。
    # 只做「结果行提示」，不参与 collision 判定；多盐型仅提示，不写「不可互换」
    # （不可互换只来自 dose_warning 的已发布条目）。
    forms_by_sub: dict[str, list[str]] = {}
    has_salt_code = "salt_code" in {r[1] for r in db.execute("PRAGMA table_info(variant)")}
    variant_sql = ("SELECT substance_id, salt, hydrate, ester, salt_code FROM variant"
                   if has_salt_code else
                   "SELECT substance_id, salt, hydrate, ester, '' FROM variant")
    for sid, salt, hyd, est, code in db.execute(variant_sql):
        forms = forms_by_sub.setdefault(sid, [])
        label = (code or "").strip()
        if not label or label in ("mixed", "non_salt"):
            label = (salt or "").strip() or "base"
        if (hyd or "").strip():
            label += " " + hyd.strip()
        if (est or "").strip():
            label += " " + est.strip()
        if label not in forms:
            forms.append(label)
    warn_by_sub: dict[str, list[str]] = {}
    for sid, wid in db.execute(
            """SELECT substance_id, warning_id FROM dose_warning
               WHERE status='published' AND rule IN ('R1','R2')
                 AND substance_id IS NOT NULL
               ORDER BY CASE rule WHEN 'R2' THEN 0 ELSE 1 END, warning_id"""):
        warn_by_sub.setdefault(sid, []).append(wid)

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
        # v0.8.3：伪复方（base+salt 被并成单 base）不再算多成分碰撞
        if key_id in merged_keys and len(a["sids"]) <= 1:
            level = "info"
        # 只有这些名字值得单独成页：有碰撞的、或包装数够多的。
        # 其余名字仍能被搜到，卡片直接链到成分页——不为只有一个包装的冷门名字生成几万张页。
        # 通用名照样能搜到，但只有「有品牌名」或碰撞/多包装的名字才单独成页，
        # 否则光中国就会多出上万张价值很低的页面。
        # v0.5.3：trade 品牌有 ≥2 个包装就生成轻量品牌页（仍不为 8 万个单包装
        # 冷门名字建页；那些在结果里渲染成不可点文本，绝不回退成 drug 页）。
        worth_page = (not pure_inn) and (a["trade"] or level == "warning") and (
            level == "warning" or (level == "severe" and n >= 2) or n >= 3
            or (a["trade"] and n >= 2))
        ordered_mah = sorted(a["mah"].items(), key=lambda kv: (-kv[1], kv[0]))
        first_maker = ordered_mah[0][0] if ordered_mah else ""
        first_info = MAKERS.get(norm_maker(first_maker)) if first_maker else None
        # v0.5.4：结果行「+N」展开用的其它厂家（只存有厂家页的，带 name+slug；
        # 没页的厂家不进索引，前端用 mn 差额显示「另有 K 家暂无页面」）。
        ml: list[list[str]] = []
        for mname, _cnt in ordered_mah[1:]:
            info = MAKERS.get(norm_maker(mname))
            if info and info["has"]:
                ml.append([mname, info["slug"]])
        # v0.5.6：单成分条目才有盐型/警示上下文；复方条目 sl/rl/wi 留空
        sid1 = next(iter(a["sids"])) if len(a["sids"]) == 1 else ""
        forms = forms_by_sub.get(sid1, []) if sid1 else []
        sl_hint = "/".join(forms[:3]) if len(forms) > 1 else ""
        rl_hint = ",".join(sorted(a.get("rels") or [])) if a.get("rels") else ""
        wi_id = (warn_by_sub.get(sid1) or [""])[0] if sid1 else ""
        entry = {
            "k": key_id,
            "d": displays.get(key_id, key_id),
            "c": sorted(a["c"]),
            "x": " + ".join(a["subs"][:6]),
            # v0.5.5：中文成分名数组，与 x 的 " + " 分段平行；全空则不写（回退英文）
            "xz": ([zh for zh in a["subs_zh"][:6]]
                   if any(zh for zh in a["subs_zh"][:6]) else None),
            # v0.6.4 A2：ATC 码数组（最多 8 个；无 ATC 的条目为 None）
            "atc": sorted(a["atc"])[:8] or None,
            "s": a["s"][:6],
            "f": a["f"][0] if a["f"] else "",
            "l": level,
            "n": n,
            "v": a["v"],
            "vs": sorted(a["sids"]) if len(a["sids"]) > 1 else None,
            "u": key_file(key_id) if worth_page else "",
            # v0.5.3：复方 → 组合页 URL（成分列点击目标；单成分为空，走 drug 页）
            # combo_slug() 由 key_file() 生成、已含 .html 后缀。
            "cu": ("combo/" + combo_slug(a["sids"]))
                  if len(a["sids"]) > 1 else "",
            "g": fam[key_id][0] if key_id in fam else "",
            "gn": fam[key_id][1] if key_id in fam else "",
            "m": first_maker,
            # v0.5.4：主厂家页 slug（无页为空 → 结果行显示纯文本）
            "mu": first_info["slug"] if first_info and first_info["has"] else "",
            # v0.5.4：「+N」展开列表：[[name, slug], ...]（仅含可点的其它厂家）
            "ml": ml if ml else None,
            "mn": len(a["mah"]),
            # v0.5.6（A1/A3）：明细桶名（懒加载 data/idx/detail-<db>.json）+
            # 盐型提示（多盐型才写）+ 释放机制 + 已发布 R1/R2 警示 id。
            # sl/rl/wi 空值不写，避免 12.7 万条索引每行多背 3 个空串（约 +3 MB）。
            "db": _shard_bucket(key_id),
        }
        if sl_hint:
            entry["sl"] = sl_hint
        if rl_hint:
            entry["rl"] = rl_hint
        if wi_id:
            entry["wi"] = wi_id
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


# ── v0.6.3 U3：标签本地化 helper（服务端；与客户端 T() 共用 i18n key） ──────
def _label_html(prefix: str, code: str, fallback: str | None = None) -> str:
    """受控词 → data-i18n span；长尾/杂项值原样显示（不造数据、不空）。"""
    code = (code or "").strip()
    if not code:
        return ""
    key = f"{prefix}.{code}"
    if key in I18N["en"]:
        return f'<span data-i18n="{key}">{esc(I18N["en"][key])}</span>'
    return esc(fallback if fallback is not None else code)


def _label_join(prefix: str, codes) -> str:
    return "、".join(_label_html(prefix, c) for c in codes if (c or "").strip())


_RE_UNIT = re.compile(r"(?<![\w])(万iu|microgram|unit|meq|mci|iu|ug)(?![\w])")


def _label_unit_html(text: str) -> str:
    """强度串里的非国际通用单位包成 data-i18n span；mg/g/ml/%/mcg 等保持原样。"""
    def repl(m):
        key = f"unit.{m.group(1)}"
        if key in I18N["en"]:
            return f'<span data-i18n="{key}">{esc(I18N["en"][key])}</span>'
        return m.group(1)
    return _RE_UNIT.sub(repl, esc(text))


# v0.6.6：成分页多国矩阵（行=规格/剂型/释放；列=国家；服务端默认 en 顺序，客户端按界面语言重排）
COUNTRY_PRIORITY = ("US", "GB", "CA", "AU", "SG", "CN", "ES", "MX", "TW")
MATRIX_ROW_CAP = 120


def _strength_suspect(text: str) -> bool:
    """v0.8.4：明显错误的规格（如 400064g）→ 标「规格待核」并排最后；只标记不删数据。"""
    m = re.match(r"\s*([0-9][0-9,.]*)\s*([A-Za-z%μµ]*)", text or "")
    if not m:
        return False
    try:
        val = float(m.group(1).replace(",", ""))
    except ValueError:
        return False
    unit = (m.group(2) or "").lower()
    if val >= 1_000_000:
        return True
    if val > 10_000 and unit not in ("u", "iu", "unit", "units", "%", "ml"):
        return True
    return False


_FORM_WORD_ZH = {
    "tablet": ("片", "片剂"), "capsule": ("胶囊",), "injection": ("注射液", "注射剂"),
    "solution": ("溶液", "口服液", "液"), "syrup": ("糖浆",), "suspension": ("混悬液",),
    "cream": ("乳膏", "霜"), "ointment": ("软膏",), "gel": ("凝胶", "凝胶剂"),
    "granule": ("颗粒",), "powder": ("散", "粉"), "spray": ("喷雾剂", "喷剂"),
    "drops": ("滴剂", "滴眼液", "滴耳液", "滴鼻液"), "inhaler": ("吸入剂",),
    "suppository": ("栓",), "patch": ("贴剂", "贴片"),
}


def _strip_form_from_label(label: str, form: str) -> str:
    """v0.8.4：通用名已含剂型词时不在显示里重复剂型（如「阿莫西林胶囊」+「胶囊」）。"""
    text = (label or "").strip()
    f = (form or "").lower()
    if not text or not f:
        return text
    en_word = f.split()[0] if f.split() else f
    suffix = en_word
    for key, words in _FORM_WORD_ZH.items():
        if key in f:
            suffix = words[0]
            break
    for cand in (suffix, en_word):
        if cand and len(text) > len(cand) and text.lower().endswith(cand.lower()):
            return text[: -len(cand)].strip()
    return text


def build_drug_pages(db: sqlite3.Connection, entries=None) -> int:
    T = I18N["en"]
    entry_by_k = {e["k"]: e for e in (entries or [])}
    # task-136：CN 中文注册名可附的英文原名（同 key 的拉丁写法；无则不造）
    cn_latin: dict[str, str] = {}
    for kid, raw in db.execute(
            """SELECT DISTINCT pn.key_id, nv.raw FROM product_name pn
               JOIN name_variant nv ON nv.key_id = pn.key_id
               JOIN product p ON p.product_id = pn.product_id
               WHERE p.country = 'CN' AND pn.name_type = 'trade'"""):
        txt = (raw or "").strip()
        if txt and any("a" <= ch.lower() <= "z" for ch in txt) \
                and not any("\u4e00" <= ch <= "\u9fff" for ch in txt):
            cn_latin.setdefault(kid, txt)
    products: dict[str, list] = {}
    for row in db.execute(
        """SELECT v.substance_id, p.country, p.form_base, p.dosage_form, p.release,
                  p.status, pc.strength_value, pc.strength_unit,
                  pc.per_volume_value, pc.per_volume_unit, p.product_id, s.inn_zh
           FROM product p
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           JOIN substance s ON s.substance_id = v.substance_id"""
    ):
        products.setdefault(row[0], []).append(row[1:])

    names: dict[str, list[tuple[str, str]]] = {}
    for pid, key_id, raw in db.execute(
        """SELECT pn.product_id, pn.key_id, nv.raw FROM product_name pn
           JOIN name_variant nv ON nv.key_id = pn.key_id
           WHERE pn.name_type = 'trade'"""
    ):
        bucket = names.setdefault(pid, [])
        item = (key_id, raw)
        if item not in bucket:
            bucket.append(item)

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

        # v0.6.6：按「规格 + 剂型 + 释放机制」聚合，国家并排；默认只显示 active。
        spec_countries: dict[tuple, dict[str, dict[str, str]]] = {}
        for (country, fb, df, rel, status, sv, su, pv, pu, pid, zh_sub) in rows:
            if status != "active":
                continue
            st = f"{sv:g} {su}" if sv is not None else ""
            if pv:
                st += f"/{pv:g} {pu}"
            spec = (st.strip(), fb or df or "", rel)
            bucket = spec_countries.setdefault(spec, {}).setdefault(country, {})
            for key_id, raw in names.get(pid, []):
                e = entry_by_k.get(key_id)
                label = (e or {}).get("d") or raw
                if label and label not in bucket:
                    en = cn_latin.get(key_id, "") if country == "CN" else ""
                    bucket[label] = (f'../name/{e["u"]}' if e and e.get("u") else "", en,
                                     (zh_sub or "") if country == "CN" else "")
        countries = [c for c in COUNTRY_PRIORITY
                     if any(c in by_c for by_c in spec_countries.values())]
        for by_c in spec_countries.values():
            for c in by_c:
                if c not in countries:
                    countries.append(c)
        # v0.8.0：不再静默截断到 8 列——全部市场列都显示（US/GB/CA/AU/SG/CN/ES/MX/TW），
        # 移动端由 .matwrap 横向滚动；界面语言只决定列顺序（i18n.js MORDER）。
        # v0.8.3 task-119：常用度排序（跨国家产品/品牌记录数），「未公开」最后，空行隐藏。
        def _spec_num(st: str) -> float:
            m2 = re.match(r"\s*([0-9]+(?:[.,][0-9]+)?)", st or "")
            try:
                return float(m2.group(1).replace(",", ".")) if m2 else -1.0
            except ValueError:
                return -1.0

        def _form_rank(form: str) -> int:
            f = (form or "").lower()
            if "tablet" in f:
                return 0
            if "capsule" in f:
                return 1
            if any(w in f for w in ("solution", "liquid", "syrup", "suspension",
                                    "elixir", "drops")):
                return 2
            if any(w in f for w in ("injection", "infusion", "injectable", "vial", "ampoule")):
                return 3
            if any(w in f for w in ("cream", "ointment", "gel", "lotion", "patch",
                                    "suppositor")):
                return 4
            if any(w in f for w in ("spray", "inhaler", "aerosol", "nebuli")):
                return 5
            if any(w in f for w in ("powder", "granule", "sachet")):
                return 6
            return 9

        freq_by_spec = {
            spec: sum(len(bucket) for bucket in by_c.values())
            for spec, by_c in spec_countries.items()
        }
        suspect_by_spec = {spec: _strength_suspect(spec[0]) for spec in spec_countries}
        spec_rows = [kv for kv in spec_countries.items()
                     if any(bucket for bucket in kv[1].values())]
        spec_rows.sort(key=lambda kv: (
            kv[0][0].strip() == "",                  # 未公开规格排最后
            suspect_by_spec.get(kv[0], False),        # 规格待核排最后
            -freq_by_spec.get(kv[0], 0),              # 常用度降序
            _form_rank(kv[0][1]),                     # 剂型标准顺序
            -_spec_num(kv[0][0]),                     # 同频按数值（大→小）
            kv[0][2],
        ))
        shown = spec_rows[:MATRIX_ROW_CAP]
        head = (f'<th data-i18n="matrix.spec">{esc(T["matrix.spec"])}</th>'
                + "".join(f'<th data-country="{esc(c)}">{esc(c)}</th>'
                          for c in countries))
        tbody = []
        for spec, by_c in shown:
            st, form, rel = spec
            suspect = suspect_by_spec.get(spec, False)
            st_html = _label_unit_html(st) if st else (
                '<span class="meta" data-i18n="drug.nostrength">not disclosed</span>')
            if suspect:
                st_html += (' <span class="tag warn" data-i18n="matrix.spec_check">'
                            'check strength</span>')
            form_html = (_label_html("form", form, form) if form
                         else '<span class="meta">—</span>')
            rel_html = (f' · {_label_html("release", rel, rel)}'
                        if rel not in ("", "none") else "")
            cells = [f'<td class="m-spec"><b>{st_html}</b><br>{form_html}{rel_html}</td>']
            for c in countries:
                cell_brands = by_c.get(c) or {}
                if not cell_brands:
                    # v0.8.2 task-136：无数据也输出固定 td（带 data-country），禁止整行错位
                    cells.append(f'<td data-country="{esc(c)}"><span class="meta" '
                                 f'data-i18n="matrix.none">not recorded</span></td>')
                    continue
                ordered = sorted(cell_brands.items(), key=lambda kv: kv[0].lower())
                bits = []
                for label, (url, en, zh_sub) in ordered[:3]:
                    display = _strip_form_from_label(label, form)
                    if url:
                        bits.append(f'<a class="m-brand" data-brand="1" title="{esc(label)}" '
                                    f'href="{esc(url)}">{esc(display)}</a>')
                    else:
                        bits.append(f'<span class="m-brand" data-brand="1" '
                                    f'title="{esc(label)}">{esc(display)}</span>')
                    if en and en != label:
                        bits.append(f'<span class="m-en">{esc(en)}</span>')
                    if zh_sub and zh_sub != display:
                        bits.append(f'<span class="m-zh">{esc(zh_sub)}</span>')
                more = (f' <span class="meta">+{len(ordered) - 3}</span>'
                        if len(ordered) > 3 else "")
                cells.append(f'<td data-country="{esc(c)}">{" ".join(bits)}{more}</td>')
            tbody.append(f'<tr data-form="{esc(form or "")}" data-release="{esc(rel or "")}" '
                         f'data-spec="{esc(st or "")}" data-suspect="{1 if suspect else 0}" '
                         f'data-freq="{freq_by_spec.get(spec, 0)}">'
                         + "".join(cells) + "</tr>")
        capped_blocks = ""
        if len(spec_rows) > MATRIX_ROW_CAP:
            for lang in ("en", "es", "zh", "zh-Hant"):
                note = (I18N[lang].get("matrix.capped") or "")
                note = (note.replace("{shown}", str(len(shown)))
                            .replace("{total}", str(len(spec_rows))))
                capped_blocks += (f'<div class="lang-block" data-lang-block="{lang}">'
                                  f'<p class="sub">{esc(note)}</p></div>')
        if tbody:
            matrix_html = ('<div class="matwrap"><table class="matrix"><thead><tr>'
                           + head + "</tr></thead><tbody>" + "".join(tbody)
                           + "</tbody></table></div>"
                           + '<p class="sub matrix-brand-note" data-i18n="matrix.brand_note">'
                             'Each country column shows the locally registered trade names — '
                             'not translations.</p>' + capped_blocks)
        else:
            matrix_html = ('<p class="empty" data-i18n="drug.empty">'
                           'No products recorded yet.</p>')
        hidden_note = ('<p class="sub" data-i18n="matrix.hidden_note">'
                       'Discontinued, withdrawn or unverified-status products are hidden by '
                       'default.</p>')
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
        h1_inner = (f'<span data-sub-ingredient="{esc(sid)}" '
                    f'data-sub-orig="{esc(inn_en or sid)}">{esc(inn_en or sid)}</span>'
                    if sid in TERMS_SUB_IDS else esc(inn_en or sid))
        body = f"""<h1>{h1_inner}</h1>
<p class="sub">ATC {esc(atc) or '—'} · <span data-i18n="drug.sid">Substance ID</span>
<code>{esc(sid)}</code></p>
{warn_line}
{nick_line}
{conf_line}
<div class="notice" data-i18n="drug.notice">The same ingredient can carry completely different
brand names in different countries, and the same name can point to a different ingredient.
Listed by country — not interchangeable.</div>
{matrix_html}
{hidden_note}"""
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
    # v0.5.3：只有真实存在 name 页的 key 才允许在「同品牌其他市场」里做成链接。
    page_keys = {e["k"] for e in entries if e.get("u")}
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
            # v0.6.6：守住「u 有值 ⇒ name/<u> 页存在」的站内不变量；数据侧缺行时用索引
            # 条目自身信息生成最小页，避免品牌矩阵/索引出现 ../name/ 404。
            d = {"subs": {}, "countries": set(e.get("c") or [])}
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
<span data-i18n="name.form">Form</span>: {_label_join('form', sorted(g['f']))} ·
<span data-i18n="name.strength">Strength</span>:
{_label_unit_html('、'.join(sorted(g['s'], key=_sort_strength))) or '—'}
{f" · <span data-i18n='name.release'>Release</span>: {_label_join('release', sorted(rel))}" if rel else ''}</div></div>"""
            )
        body = f"""<h1>{esc(e['d'])}</h1>
<p class="sub"><span data-i18n="name.also">Also written as</span>:
{esc('、'.join(variants.get(e['k'], [])[:6]))} ·
<span data-i18n="name.found">Found in</span>: {esc('、'.join(sorted(d['countries'])))}</p>
{banner}{''.join(cards) if cards else '<p class="empty" data-i18n="name.empty">No records</p>'}{_family_block(e, families, displays, variants, page_keys)}"""
        (OUT / "name" / e["u"]).write_text(page(e["d"], body, "../"), encoding="utf-8")
        made += 1
    return made


def _family_block(e, families, displays, variants, page_keys=None) -> str:
    """同一品牌在其他市场的写法——这是跨语言碰撞唯一能落地的地方。

    page_keys：有 name 页的 key 集合；v0.5.3 起没有品牌页的成员渲染成不可点文本，
    保证站内不出现指向不存在页面的链接（无 404）。
    """
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
        label_html = esc(displays.get(k, siblings_names))
        if page_keys is None or k in page_keys:
            items.append(f'<li><a href="{key_file(k)}">{label_html}</a>'
                         f'<span class="tag">{esc(k)}</span></li>')
        else:
            items.append(f'<li><b>{label_html}</b><span class="tag">{esc(k)}</span></li>')
    return (f'<h2 data-i18n="fam.title">The same brand in other markets</h2>'
            f'<div class="notice">{esc(note or "")}</div>'
            f'<ul class="sub">{"".join(items)}</ul>')


COMBO_ROW_CAP = 200


def build_combo_pages(entries, db: sqlite3.Connection) -> int:
    """v0.5.3：按「活性成分集合」生成组合页 /combo/<slug>.html。

    背景：结果页「成分」列对复方（x 含 ' + '）必须点进组合页，而不是第一个成分的
    drug 页。组合页 slug 与索引里的 `cu` 字段共用 combo_slug()，保证一一对应。
    页面最小字段：成分集合（每个成分链成分页）、同组合的商品名/国家/规格/MAH、
    来源与许可；不写用药建议。
    """
    subs: dict[str, tuple[str, str]] = {}
    for sid, inn_zh, inn_en in db.execute(
            "SELECT substance_id, inn_zh, inn_en FROM substance"):
        subs[sid] = (inn_zh or inn_en or sid, inn_en or sid)
    groups: dict[tuple, list] = {}
    for e in entries:
        vs = e.get("vs")
        if not vs or len(vs) < 2:
            continue
        groups.setdefault(tuple(sorted(vs)), []).append(e)
    # v0.6.0：页面 sids 集合 → CSV 归一名数签名。
    # 组合页的 vs 是「同一 name_key 下所有产品的成分并集」，不一定等于单个产品的成分集合；
    # 先用「产品原始 sids 集合 == 页面集合」精确反查，再用页面归一并集兜底；
    # 仍对不上的分组名（合并了多个不同产品的名称）显示中性提示，不臆断 exact/none。
    combo_matches = load_combo_matches()
    sub_key = {sid: norm_ingredient(en) for sid, (_zh, en) in subs.items()}
    key_sid: dict[str, str] = {}
    key_display: dict[str, str] = {}
    for sid, key in sub_key.items():
        key_sid.setdefault(key, sid)
        key_display.setdefault(key, subs.get(sid, (sid, sid))[1])
    tuple_sig: dict[tuple, str] = {}
    if combo_matches:
        prod_sids: dict[str, list] = defaultdict(list)
        for pid, sid in db.execute(
                "SELECT pc.product_id, v.substance_id FROM product_component pc "
                "JOIN variant v ON v.variant_id = pc.variant_id"):
            prod_sids[pid].append(sid)
        seen_tuples: set[tuple] = set()
        for _pid, psids in prod_sids.items():
            if len(psids) < 2:
                continue
            t = tuple(sorted(psids))
            if t in seen_tuples:
                continue
            seen_tuples.add(t)
            sig = "|".join(sorted({sub_key.get(s, norm_ingredient(s)) for s in t}))
            if sig in combo_matches:
                tuple_sig[t] = sig
    page_sig: dict[str, str] = {}
    sig_pages: dict[str, list[str]] = defaultdict(list)
    for sids in groups:
        slug = combo_slug(sids)
        sig = tuple_sig.get(tuple(sids))
        if not sig:
            ukeys = sorted({sub_key.get(s, norm_ingredient(s)) for s in sids})
            cand = "|".join(ukeys)
            if len(ukeys) >= 2 and cand in combo_matches:
                sig = cand
        if sig:
            page_sig[slug] = sig
            sig_pages[sig].append(slug)
    entry_by_k = {e["k"]: e for e in entries}
    sample_pids = {row.get("sample_product_id") or "" for sig in set(page_sig.values())
                   for row in combo_matches.get(sig, [])}
    sample_pids.discard("")
    pid_key: dict[str, str] = {}
    for pid, key_id in db.execute(
            "SELECT product_id, key_id FROM product_name WHERE name_type = 'trade'"):
        if pid in sample_pids and pid not in pid_key:
            pid_key[pid] = key_id

    def _record_link(pid: str, fallback_sid: str) -> str:
        k = pid_key.get(pid or "")
        u = (entry_by_k.get(k) or {}).get("u") if k else ""
        if u:
            return f'<a href="../name/{esc(u)}" data-i18n="combo.cross_record">record</a>'
        if fallback_sid:
            return (f'<a href="../drug/{esc(fallback_sid)}.html" '
                    f'data-i18n="combo.cross_record">record</a>')
        return '<span data-i18n="combo.cross_record">record</span>'

    def cross_html(slug: str) -> str:
        title_html = (f'<h2 data-i18n="combo.cross_title">'
                      f'{esc(T["combo.cross_title"])}</h2>')
        sig = page_sig.get(slug)
        if not sig:
            return (title_html + f'<p class="sub" data-i18n="combo.cross_unmatched">'
                    f'{esc(T["combo.cross_unmatched"])}</p>')
        mrows = combo_matches.get(sig) or []
        strengths = {r.get("match_strength") for r in mrows}
        if "exact" in strengths:
            by_country = {r.get("country"): r for r in mrows if r.get("country")}
            markets: list[str] = []
            for r in mrows:
                for mk in (r.get("match_markets") or "").split("|"):
                    if mk and mk not in markets:
                        markets.append(mk)
            items = []
            for mk in markets[:8]:
                row = by_country.get(mk)
                if not row:
                    continue
                brands = "; ".join((row.get("brands") or "").split("; ")[:3])
                if not brands:
                    # 部分市场（如美国仿制药）商品名挂在 name_type=inn 下，brands 为空：
                    # 回退显示该市场的主成分/generic 名，而不是空白。
                    brands = key_display.get(row.get("primary_ingredient") or "") or "—"
                n = row.get("n_products") or "0"
                fb = key_sid.get(row.get("primary_ingredient") or "")
                items.append(
                    f'<li><span class="x-mkt">{esc(mk)}</span> · {esc(brands)} · '
                    f'<b>{esc(n)}</b> <span data-i18n="combo.cross_products">products</span> · '
                    f'{_record_link(row.get("sample_product_id") or "", fb or "")}</li>')
            return (title_html
                    + f'<div class="notice" data-i18n="combo.cross_exact">'
                      f'{esc(T["combo.cross_exact"])}</div>'
                    + f'<ul class="xlist">{"".join(items)}</ul>')
        if "overlap" in strengths:
            links: list[str] = []
            for r in mrows:
                if r.get("match_strength") != "overlap":
                    continue
                for msig in (r.get("matched_signatures") or "").split("|"):
                    if msig and msig not in links:
                        links.append(msig)
            items = []
            for msig in links[:5]:
                disp = " + ".join(key_display.get(k) or k for k in msig.split("|"))
                target = (sig_pages.get(msig) or [""])[0]
                if target and target != slug:
                    items.append(f'<li><a href="./{esc(target)}">{esc(disp)}</a></li>')
                else:
                    items.append(f'<li>{esc(disp)}</li>')
            return (title_html
                    + f'<div class="notice warnbox" data-i18n="combo.cross_overlap">'
                      f'{esc(T["combo.cross_overlap"])}</div>'
                    + (f'<ul class="xlist">{"".join(items)}</ul>' if items else ""))
        html = (title_html
                + f'<p class="sub" data-i18n="combo.cross_none">'
                  f'{esc(T["combo.cross_none"])}</p>')
        prim_row = next((r for r in mrows if r.get("primary_cross_market") == "yes"
                         and r.get("primary_ingredient")), None)
        if prim_row:
            psid = key_sid.get(prim_row.get("primary_ingredient") or "")
            if psid:
                html += (f'<p class="sub" data-i18n="combo.cross_primary">'
                         f'{esc(T["combo.cross_primary"])} '
                         f'<a href="../drug/{esc(psid)}.html" '
                         f'data-i18n="combo.cross_primary_link">'
                         f'{esc(T["combo.cross_primary_link"])}</a></p>')
        return html

    (OUT / "combo").mkdir(parents=True, exist_ok=True)
    T = I18N["en"]
    made = 0
    for sids, rows in groups.items():
        slug = combo_slug(sids)
        ing_items = []
        for sid in sids:
            zh, en = subs.get(sid, (sid, sid))
            # v0.8.2 task-120：组合页成分名四语（中文优先，无中文名加提示）
            ing_items.append(
                f'<li><a href="../drug/{esc(sid)}.html">{_sub_name_spans(en, zh, sid)}</a> '
                f'<code>{esc(sid)}</code></li>')
        title = " + ".join(subs.get(s, (s, s))[1] for s in sids)
        rows = sorted(rows, key=lambda e: -e["n"])
        total = len(rows)
        body_rows = []
        for e in rows[:COMBO_ROW_CAP]:
            if e.get("u"):
                brand = f'<a href="../name/{esc(e["u"])}">{esc(e["d"])}</a>'
            else:
                # 品牌列规则：没有品牌页 → 不可点文本；禁止回退 drug 页（无 404 / 不误导）
                brand = (f'<span class="brand-plain" title="{esc(T["combo.no_page"])}">'
                         f'{esc(e["d"])}</span>')
            tags = "".join(
                f'<span class="tag {c.lower()}">{esc(c)}</span>' for c in (e.get("c") or []))
            doses = " / ".join(e.get("s") or []) or "—"
            mah = e.get("m") or "—"
            body_rows.append(
                f'<tr><td class="c-brand" data-label="{esc(T["col.brand"])}">'
                f'{brand}{tags}</td>'
                f'<td data-label="{esc(T["col.dose"])}">{esc(doses)}</td>'
                f'<td data-label="{esc(T["col.mah"])}">{esc(mah)}</td></tr>')
        capped_html = ""
        if total > COMBO_ROW_CAP:
            capped = (T["combo.capped"].replace("{cap}", str(COMBO_ROW_CAP))
                      .replace("{total}", str(total)))
            capped_html = f'<p class="sub">{capped}</p>'
        rows_html = (
            '<div class="tablewrap"><table class="res"><thead><tr>'
            f'<th>{T["col.brand"]}</th><th>{T["col.dose"]}</th><th>{T["col.mah"]}</th>'
            f'</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>'
            if body_rows else
            '<p class="empty" data-i18n="combo.empty">No brand names recorded for this '
            'combination yet.</p>')
        body = f"""<h1>{esc(title)}</h1>
<p class="sub" data-i18n="combo.title">{esc(T["combo.title"])}</p>
<div data-i18n-html="combo.intro">{T["combo.intro"]}</div>
<div class="notice" data-i18n="combo.no_advice">{esc(T["combo.no_advice"])}</div>
<h2 data-i18n="combo.ingredients">{esc(T["combo.ingredients"])}</h2>
<ul class="sub">{''.join(ing_items)}</ul>
<h2 data-i18n="combo.products">{esc(T["combo.products"])}</h2>
{rows_html}
{capped_html}
{cross_html(slug)}
<p class="sub"><a href="../warn.html">{esc(T["combo.see_warnings"])}</a></p>
<div class="notice" data-i18n-html="combo.source_note">{T["combo.source_note"]}</div>"""
        (OUT / "combo" / slug).write_text(page(title, body, "../"), encoding="utf-8")
        made += 1
    return made


MAKER_PRODUCT_CAP = 60   # 每页产品行上限（按国家均摊）；控制 dist 体积（守卫 400MB）


def build_maker_pages(entries, db: sqlite3.Connection) -> int:
    """v0.5.4：生成 /maker/<slug>.html（厂家 / 上市许可持有人页）。

    - 数据：data/maker_candidates.csv（阈值 MAKER_MIN_PRODUCTS，占位厂家由 is_placeholder=1 排除）
    - 内容：厂家名、产品数/市场数/品牌数、按国家分组的品牌行（品牌→品牌页、成分→成分/组合页）、
      来源链接与许可说明；每页产品行最多 MAKER_PRODUCT_CAP（按国家均摊），多出的显示截断提示。
    - 链接目标全部在构建期验证过（无 404）：combo 只在已经生成了组合页时使用，否则逐个成分链 drug。
    """
    if not MAKERS:
        return 0
    page_makers = {k: v for k, v in MAKERS.items() if v["has"]}
    if not page_makers:
        return 0
    T = I18N["en"]
    (OUT / "maker").mkdir(parents=True, exist_ok=True)
    entry_by_k = {e["k"]: e for e in entries}
    combo_files = {p.name for p in (OUT / "combo").glob("*.html")}
    sub_names: dict[str, tuple[str, str]] = {}
    for sid, inn_zh, inn_en in db.execute(
            "SELECT substance_id, inn_zh, inn_en FROM substance"):
        sub_names[sid] = (inn_zh or inn_en or sid, inn_en or sid)

    # 一次性取产品（只保留有页厂家），再补品牌名与成分
    prod: dict[str, dict] = {}
    for (pid, country, mah, form, base, rel, pack, appr, src) in db.execute(
        """SELECT product_id, country, mah, dosage_form, form_base, release, pack,
                  approval_id, source_url
           FROM product WHERE mah IS NOT NULL AND mah <> ''"""
    ):
        info = page_makers.get(norm_maker(mah))
        if not info:
            continue
        prod[pid] = {"pid": pid, "country": country, "mah": mah, "mkey": norm_maker(mah),
                     "form": base or form or "", "release": rel if rel != "none" else "",
                     "pack": pack or "", "approval": appr or "", "src": src or "",
                     "keys": [], "sids": set()}
    for pid, key_id in db.execute(
            "SELECT product_id, key_id FROM product_name WHERE name_type = 'trade'"):
        p = prod.get(pid)
        if p is not None:
            p["keys"].append(key_id)
    for pid, sid in db.execute(
            """SELECT pc.product_id, v.substance_id
               FROM product_component pc JOIN variant v ON v.variant_id = pc.variant_id"""):
        p = prod.get(pid)
        if p is not None:
            p["sids"].add(sid)

    by_maker: dict[str, list] = defaultdict(list)
    for p in prod.values():
        by_maker[p["mkey"]].append(p)

    def brand_cell(p: dict, lang: str) -> str:
        if not p["keys"]:
            return '—'
        key_id = p["keys"][0]
        e = entry_by_k.get(key_id)
        label = esc((e or {}).get("d") or key_id)
        if e and e.get("u"):
            return f'<a href="../name/{esc(e["u"])}">{label}</a>'
        return (f'<span class="brand-plain" title="{esc(I18N[lang]["maker.no_page"])}">'
                f'{label}</span>')

    def ingredient_cell(p: dict, lang: str) -> str:
        sids = sorted(p["sids"])
        if not sids:
            return '—'
        labels = []
        for sid in sids[:3]:
            zh, en = sub_names.get(sid, (sid, sid))
            labels.append(esc(zh) if zh else esc(en))
        more = f' <span class="meta">+{len(sids) - 3}</span>' if len(sids) > 3 else ""
        if len(sids) == 1:
            return f'<a href="../drug/{esc(sids[0])}.html">{labels[0]}</a>' + more
        slug = combo_slug(sids)
        text = " + ".join(labels) + more
        if slug in combo_files:
            return f'<a href="../combo/{esc(slug)}">{text}</a>'
        parts = [f'<a href="../drug/{esc(sid)}.html">{lab}</a>'
                 for sid, lab in zip(sids[:3], labels)]
        return " · ".join(parts) + more

    made = 0
    for mkey, rows in by_maker.items():
        info = page_makers[mkey]
        rows.sort(key=lambda p: (p["country"], (entry_by_k.get(p["keys"][0]) or {}).get("d", "")
                                 if p["keys"] else "~"))
        countries = [c for c in COUNTRY_PRIORITY if c in {p["country"] for p in rows}]
        countries += sorted({p["country"] for p in rows} - set(countries))
        brands = {(entry_by_k.get(p["keys"][0]) or {}).get("k", p["keys"][0])
                  for p in rows if p["keys"]}
        n_products = len(rows)
        stats_vals = {"name": info["name"], "products": f"{n_products:,}",
                      "markets": str(len(countries)), "brands": f"{len(brands):,}"}
        intro_blocks = ""
        stats_blocks = ""
        for lang in ("en", "es", "zh"):
            li = I18N[lang]["maker.intro"]
            ls = I18N[lang]["maker.stats"]
            for k, v in stats_vals.items():
                li = li.replace("{" + k + "}", v)
                ls = ls.replace("{" + k + "}", v)
            intro_blocks += f'<div class="lang-block" data-lang-block="{lang}">{li}</div>'
            stats_blocks += f'<div class="lang-block" data-lang-block="{lang}">{ls}</div>'

        # 产品行：按国家均摊上限，保证每个国家都能露面
        per_country = max(1, (MAKER_PRODUCT_CAP + len(countries) - 1) // max(1, len(countries)))
        by_country: dict[str, list] = defaultdict(list)
        for p in rows:
            by_country[p["country"]].append(p)
        shown = 0
        sections = []
        for country in countries:
            items = by_country[country][:per_country]
            if shown + len(items) > MAKER_PRODUCT_CAP:
                items = items[:max(0, MAKER_PRODUCT_CAP - shown)]
            if not items:
                continue
            shown += len(items)
            body_rows = []
            for p in items:
                form = esc(p["form"]) if p["form"] else "—"
                body_rows.append(
                    f'<tr><td class="c-brand" data-i18n-label="maker.brand">'
                    f'{brand_cell(p, "en")}</td>'
                    f'<td data-i18n-label="maker.ingredient">{ingredient_cell(p, "en")}</td>'
                    f'<td data-i18n-label="col.dose">{form}</td></tr>')
            src = next((p["src"] for p in items if p["src"]), "")
            src_html = (f'<p class="sub"><span data-i18n="maker.source">Source</span>: '
                        f'<a href="{esc(src)}" target="_blank" rel="noopener">'
                        f'{esc(src.split("//")[-1].split("/")[0])}</a></p>'
                        if src else "")
            sections.append(
                f'<h2>{esc(country)} <span class="meta">({len(by_country[country])} '
                f'<span data-i18n="drug.records">records</span>)</span></h2>{src_html}'
                '<div class="tablewrap"><table class="res"><thead><tr>'
                f'<th data-i18n="maker.brand">{esc(T["maker.brand"])}</th>'
                f'<th data-i18n="maker.ingredient">{esc(T["maker.ingredient"])}</th>'
                f'<th data-i18n="col.dose">{esc(T["col.dose"])}</th>'
                f'</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>')
        capped_blocks = ""
        if n_products > shown:
            for lang in ("en", "es", "zh"):
                note = (I18N[lang]["maker.capped"]
                        .replace("{shown}", f"{shown:,}").replace("{total}", f"{n_products:,}"))
                capped_blocks += (f'<div class="lang-block" data-lang-block="{lang}">'
                                  f'<p class="sub">{esc(note)}</p></div>')
        body = f"""<h1>{esc(info["name"])}</h1>
<p class="sub" data-i18n="maker.title">{esc(T["maker.title"])}</p>
{intro_blocks}
{stats_blocks}
<h2 data-i18n="maker.by_country">{esc(T["maker.by_country"])}</h2>
{''.join(sections) if sections else '<p class="empty" data-i18n="maker.empty">No products recorded.</p>'}
{capped_blocks}
<div class="notice" data-i18n-html="maker.source_note">{T["maker.source_note"]}</div>"""
        (OUT / "maker" / f'{info["slug"]}.html').write_text(
            page(info["name"], body, "../"), encoding="utf-8")
        made += 1
    return made


def _sort_strength(text: str) -> float:
    m = re.match(r"([\d.]+)", text)
    return float(m.group(1)) if m else 0.0


# v0.6.5：首页示例按钮按页面语言渲染（en/es/zh/zh-Hant；zh-Hant 用繁體示例）
HOME_EXAMPLES = {
    "en": {"hero": ["Lipitor 20mg", "Tylenol", "Benadryl", "Gaviscon"],
           "try1": ["Lipitor 20mg", "Tylenol"], "try2": ["Paracetamol 500mg"],
           "try3": ["Benadryl", "Gaviscon"]},
    "es": {"hero": ["Paracetamol 500mg", "Ibuprofeno 600mg", "Omeprazol 20mg",
                    "Loratadina 10mg"],
           "try1": ["Paracetamol 500mg", "Omeprazol 20mg"],
           "try2": ["Ibuprofeno 600mg"], "try3": ["Loratadina 10mg", "Omeprazol 20mg"]},
    "zh": {"hero": ["泰诺", "两只青蛙", "Lipitor 20mg", "Benadryl", "Gaviscon"],
           "try1": ["泰诺", "Lipitor 20mg"], "try2": ["两只青蛙"],
           "try3": ["Benadryl", "Gaviscon"]},
    "zh-Hant": {"hero": ["泰諾", "兩隻青蛙", "Lipitor 20mg", "Benadryl", "Gaviscon"],
                "try1": ["泰諾", "Lipitor 20mg"], "try2": ["兩隻青蛙"],
                "try3": ["Benadryl", "Gaviscon"]},
}


def _sample_buttons(queries) -> str:
    return "".join(f'<button type="button" data-q="{esc(q)}">{esc(q)}</button>'
                   for q in queries)


def build_index_page(entries, stats, coverage) -> None:
    """四份落地页：/ 、/es/ 、/zh/ 、/zh-hant/。内容相同，语言由脚本按路径/参数决定。"""
    covline = ", ".join(f"{r['country']} {r['n_products']:,}" for r in coverage)
    body = f"""<h1 data-i18n="home.h1">Find out what a medicine really is</h1>
<p class="sub" data-i18n="home.sub">Type a brand name, a generic name, a nickname, or a line from the pack. Chinese, full-width and Cyrillic input all work, and you can include the dose — e.g. Lipitor 20mg, Tylenol, or Paracetamol 500mg.</p>
<div class="searchwrap">
<input id="q" data-ph="home.ph" placeholder="Brand name / generic name / nickname / a line from the pack" autocomplete="off" aria-autocomplete="list" aria-controls="ac" aria-expanded="false">
<div id="ac" role="listbox" aria-label="Suggestions"></div>
</div>
<section id="u1guide" class="u1guide" aria-labelledby="u1title" data-i18n-aria="u1.aria">
  <div class="u1head"><h2 id="u1title" data-i18n="u1.title">How to use it in 3 steps</h2>
    <button type="button" id="u1close" class="u1close" data-i18n-aria="u1.close"
      aria-label="Dismiss">×</button></div>
  <ol class="u1steps">
    <li class="u1step"><b data-i18n="u1.step1">Type the name from the pack</b>
      <p class="sub" data-i18n="u1.step1_hint">Brand, generic name, nickname, or a line from the pack — dose included is fine.</p>
      <div class="u1try"><span data-i18n="u1.try">Try:</span>
        {{try1}}</div></li>
    <li class="u1step"><b data-i18n="u1.step2">See the ingredient and strength</b>
      <p class="sub" data-i18n="u1.step2_hint">You always get a candidate set — never a single answer.</p>
      <div class="u1try"><span data-i18n="u1.try">Try:</span>
        {{try2}}</div></li>
    <li class="u1step"><b data-i18n="u1.step3">Switch to a country/region</b>
      <p class="sub" data-i18n="u1.step3_hint">Pick a country/region to see the names it is sold under there, or use the names-by-country/region row.</p>
      <div class="u1try"><span data-i18n="u1.try">Try:</span>
        {{try3}}</div></li>
  </ol>
</section>
<div class="row">
  <label class="sel-label" for="country" id="ctrylabel" data-i18n="home.country_label">See what this medicine is called in:</label>
  <select id="country"><option value="" data-i18n="home.all">All countries and regions</option>
    <option value="US" data-i18n="home.us">United States</option>
    <option value="GB" data-i18n="home.gb">United Kingdom</option>
    <option value="CN" data-i18n="home.cn">China</option>
    <option value="ES" data-i18n="home.es">Spain</option>
    <option value="MX" data-i18n="home.mx">Mexico</option>
    <option value="AU" data-i18n="home.au">Australia</option>
    <option value="CA" data-i18n="home.ca">Canada</option>
    <option value="TW" data-i18n="home.tw">Taiwan</option>
    <option value="SG" data-i18n="home.sg">Singapore</option></select>
  {{hero_examples}}
</div>
<section class="catquick"><h2 data-i18n="cat.quick_title">Browse by category</h2>
<div class="catgrid">{{cat_chips}}</div></section>
<p class="sub" id="loadhint" data-i18n="home.hint_idle">First search loads only one small shard of the index (~0.2 MB); the full index fills in the background — start typing, focus the search box, or pick a sample.</p>
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
        ex = HOME_EXAMPLES.get(code) or HOME_EXAMPLES["en"]
        page_body = (body.replace("{prefix}", prefix)
                     .replace("{hero_examples}", _sample_buttons(ex["hero"]))
                     .replace("{try1}", _sample_buttons(ex["try1"]))
                     .replace("{try2}", _sample_buttons(ex["try2"]))
                     .replace("{try3}", _sample_buttons(ex["try3"]))
                     .replace("{cat_chips}", _home_cat_chips(code, prefix)))
        html = page("Medicine Brand Cross-Reference", page_body,
                    prefix=prefix, lang=code, alternates=True, meta_key="index",
                    canonical_rel=path, alt_rel="", head_js=U1_HEAD_JS)
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
    for key in ("about.lead", "about.rules", "about.nick", "about.terms",
                "about.sources", "about.tw_source", "about.sg_source"):
        parts.append(f'<div data-i18n-html="{key}">{T[key]}</div>')
    parts.append(LICENCE_HTML)
    for key in ("about.samename", "about.gaps"):
        parts.append(f'<div data-i18n-html="{key}">{T[key]}</div>')
    if GOATCOUNTER_CODE:
        parts.append(f'<div data-i18n-html="about.analytics">{T["about.analytics"]}</div>')
    parts.append(f'<div data-i18n-html="about.stats">{T["about.stats"]}</div>')
    body = "\n".join(parts)
    html = page("About", body, meta_key="about", alternates=True,
                canonical_rel="about.html", alt_rel="about.html")
    _write_with_copies("about.html", html, "about")

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
    html = page("Easily confused drug names", body, meta_key="confused", alternates=True,
                canonical_rel="confused.html", alt_rel="confused.html")
    _write_with_copies("confused.html", html, "confused")
    return len(rows)


GLOSSARY_TERMS = ("inn", "ban", "usan", "atc", "mah", "din", "ndc", "artg",
                  "fdc", "lasa", "otc", "rx", "strength")


# ── v0.8.1 双语对照（成分原名 + 当前语言译名 + 来源/版本；品牌永不翻译）────────
# ── v0.8.3 task-119：矩阵筛选器文案（四语）──────────────────────────────────
FILTER_I18N = {
    "en": {"matrix.filters": "Filters", "matrix.mobile_filters": "Filters",
           "matrix.country": "Countries & regions", "matrix.form": "Form",
           "matrix.release": "Release", "matrix.spec_search": "Search strength",
           "matrix.reset": "Reset", "matrix.all": "All",
           "matrix.showing": "{n} / {total} rows",
           "matrix.sort_note": "Common strengths first; undisclosed strength last.",
           "matrix.spec_check": "check strength",
           "matrix.close": "Close"},
    "es": {"matrix.filters": "Filtros", "matrix.mobile_filters": "Filtros",
           "matrix.country": "Países y regiones", "matrix.form": "Forma",
           "matrix.release": "Liberación", "matrix.spec_search": "Buscar concentración",
           "matrix.reset": "Restablecer", "matrix.all": "Todos",
           "matrix.showing": "{n} / {total} filas",
           "matrix.sort_note": "Concentraciones más comunes primero; sin datos al final.",
           "matrix.spec_check": "verificar concentración",
           "matrix.close": "Cerrar"},
    "zh": {"matrix.filters": "筛选", "matrix.mobile_filters": "筛选",
           "matrix.country": "国家/地区", "matrix.form": "剂型", "matrix.release": "释放",
           "matrix.spec_search": "搜索规格", "matrix.reset": "重置",
           "matrix.all": "全部", "matrix.showing": "{n} / {total} 行",
           "matrix.sort_note": "常用规格在前；未公开规格排最后。",
           "matrix.spec_check": "规格待核",
           "matrix.close": "关闭"},
    "zh-Hant": {"matrix.filters": "篩選", "matrix.mobile_filters": "篩選",
                "matrix.country": "國家/地區", "matrix.form": "劑型", "matrix.release": "釋放",
                "matrix.spec_search": "搜尋規格", "matrix.reset": "重設",
                "matrix.all": "全部", "matrix.showing": "{n} / {total} 列",
                "matrix.sort_note": "常用規格在前；未公開規格排最後。",
                "matrix.spec_check": "規格待核",
                "matrix.close": "關閉"},
}


BILINGUAL_I18N = {
    "en": {
        "bilingual.toggle": "Show original",
        "bilingual.brand_note": "Name as registered in that market — not a translation.",
        "bilingual.source.official": "official",
        "bilingual.source.regulator": "regulator",
        "bilingual.source.pharmacopoeia": "pharmacopoeia",
        "bilingual.source.manual": "editorial",
        "nav.menu": "Menu",
        "matrix.brand_note": ("Each country/region column shows the locally registered trade "
                              "names — not translations."),
    },
    "es": {
        "bilingual.toggle": "Mostrar original",
        "bilingual.brand_note": "Nombre registrado en ese mercado — no es una traducción.",
        "bilingual.source.official": "oficial",
        "bilingual.source.regulator": "regulador",
        "bilingual.source.pharmacopoeia": "farmacopea",
        "bilingual.source.manual": "editorial",
        "nav.menu": "Menú",
        "matrix.brand_note": ("Cada columna de país/región muestra los nombres comerciales "
                              "registrados en ese mercado — no son traducciones."),
    },
    "zh": {
        "bilingual.toggle": "显示原文对照",
        "bilingual.brand_note": "该市场注册名，不是翻译。",
        "bilingual.source.official": "官方",
        "bilingual.source.regulator": "监管机构",
        "bilingual.source.pharmacopoeia": "药典",
        "bilingual.source.manual": "编辑整理",
        "nav.menu": "菜单",
        "matrix.brand_note": "各国家/地区列显示当地注册商品名，不是翻译；中英文名仅作对照。",
    },
    "zh-Hant": {
        "bilingual.toggle": "顯示原文對照",
        "bilingual.brand_note": "該市場註冊名，不是翻譯。",
        "bilingual.source.official": "官方",
        "bilingual.source.regulator": "監管機構",
        "bilingual.source.pharmacopoeia": "藥典",
        "bilingual.source.manual": "編輯整理",
        "nav.menu": "選單",
        "matrix.brand_note": "各國家/地區欄顯示當地註冊商品名，不是翻譯；中英文名僅作對照。",
        "about.analytics": (
            '<h2>訪問統計</h2><p class="sub">本站使用 '
            '<a href="https://www.goatcounter.com/" target="_blank" rel="noopener">GoatCounter</a> '
            '做匿名訪問統計：不使用 cookie、不記錄個人資料、不用於廣告；只統計頁面瀏覽、來源'
            '網站、國家/地區、瀏覽器與螢幕尺寸，以及站內搜尋詞和結果點擊，用於改進檢索品質。'
            '搜尋詞（含無結果的查詢）僅以聚合事件名發送——只含正規化查詢文字，不與帳號、IP 或'
            '裝置識別碼關聯。'
            '詳見 <a href="https://www.goatcounter.com/privacy" target="_blank" '
            'rel="noopener">GoatCounter 隱私政策</a>。</p>'),
    },
}


# ── v0.7.x ATC 类别浏览 + 常见大类 ─────────────────────────────────────────
# ATC 码/层级是权威数据（WHO ATC/DDD Index 引用，不转载）；类别名是编辑/AI 译名，
# 页面明确标注「ATC 码为准」。DB 的 atc_name 是西语药名，不含类别名，故类别名内置。
ATC_I18N = {
    "en": {
        "nav.atc": "ATC & categories",
        "atc.browse_title": "Browse by ATC class",
        "atc.browse_intro": ("WHO ATC classes group medicines by organ/system and "
                             "pharmacological class. Start from a top-level group or a consumer "
                             "category; each page lists the active ingredients recorded here."),
        "atc.level": "ATC level", "atc.parent": "Parent class", "atc.children": "Child classes",
        "atc.ingredients": "Active ingredients in this class",
        "atc.count": "{n} active ingredients", "atc.more": "and {n} more",
        "atc.no_data": "No active ingredients recorded under this class yet.",
        "atc.unnamed": "Class name not reviewed yet — the ATC code is authoritative.",
        "atc.ai_note": ("Class and category names are editorial or AI-assisted translations; "
                        "only the ATC code and the WHO hierarchy are authoritative."),
        "atc.source_note": ("ATC codes and hierarchy reference the WHO Collaborating Centre for "
                            "Drug Statistics Methodology ATC/DDD Index (copyright WHOCC; the "
                            "index itself is not reproduced). Ingredient/strength facts come from "
                            "the regulator records listed on About."),
        "atc.all_classes": "All ATC classes", "atc.search_link": "Search this class",
        "atc.view_class": "View this ATC class", "atc.categories_link": "Consumer categories",
        "cat.quick_title": "Browse by category", "cat.browse_title": "Common consumer categories",
        "cat.intro": ("Editorial topic collections: each category maps to ATC classes and active "
                      "ingredients. It is a way to browse, not evidence that the medicines are "
                      "equivalent."),
        "cat.disclaimer": "Theme collection — not a claim of equivalence or interchangeability.",
        "cat.count": "{n} active ingredients", "cat.related_atc": "Related ATC classes",
        "cat.no_data": "No active ingredients recorded for this category yet.",
        "cat.back": "All ATC classes & categories",
        "parse.category": "Category",
        "parse.category_note": ("Topic collection matched — not a name, and not a claim of "
                                "equivalence."),
        "parse.match.category": "Category / ATC class",
    },
    "es": {
        "nav.atc": "ATC y categorías",
        "atc.browse_title": "Explorar por clase ATC",
        "atc.browse_intro": ("Las clases ATC de la OMS agrupan medicamentos por órgano/sistema y "
                             "clase farmacológica. Empieza por un grupo superior o por una "
                             "categoría de consumidor; cada página lista los principios activos "
                             "registrados aquí."),
        "atc.level": "Nivel ATC", "atc.parent": "Clase superior",
        "atc.children": "Clases inferiores", "atc.ingredients": "Principios activos de esta clase",
        "atc.count": "{n} principios activos", "atc.more": "y {n} más",
        "atc.no_data": "Todavía no hay principios activos registrados en esta clase.",
        "atc.unnamed": "Nombre de clase sin revisar — el código ATC es la referencia.",
        "atc.ai_note": ("Los nombres de clase y categoría son traducciones editoriales o "
                        "asistidas por IA; solo el código ATC y la jerarquía de la OMS son "
                        "autoritativos."),
        "atc.source_note": ("Los códigos y la jerarquía ATC remiten al ATC/DDD Index del WHO "
                            "Collaborating Centre for Drug Statistics Methodology (copyright "
                            "WHOCC; no se reproduce el índice). Los datos de principios activos "
                            "proceden de los registros regulatorios listados en Acerca de."),
        "atc.all_classes": "Todas las clases ATC", "atc.search_link": "Buscar en esta clase",
        "atc.view_class": "Ver esta clase ATC", "atc.categories_link": "Categorías de consumidor",
        "cat.quick_title": "Explorar por categoría",
        "cat.browse_title": "Categorías comunes de consumidor",
        "cat.intro": ("Colecciones temáticas editoriales: cada categoría se asigna a clases ATC "
                      "y principios activos. Es una forma de explorar, no una prueba de que los "
                      "medicamentos sean equivalentes."),
        "cat.disclaimer": "Colección temática — no implica equivalencia ni intercambiabilidad.",
        "cat.count": "{n} principios activos", "cat.related_atc": "Clases ATC relacionadas",
        "cat.no_data": "Todavía no hay principios activos registrados en esta categoría.",
        "cat.back": "Todas las clases y categorías", "parse.category": "Categoría",
        "parse.category_note": ("Colección temática — no es un nombre ni una afirmación de "
                                "equivalencia."),
        "parse.match.category": "Categoría / clase ATC",
    },
    "zh": {
        "nav.atc": "ATC / 大类", "atc.browse_title": "按 ATC 类别浏览",
        "atc.browse_intro": ("WHO ATC 按器官系统与药理类别给药物分类。可从一级大类或消费者大类开始；"
                             "每个页面列出本站收录的该类别活性成分。"),
        "atc.level": "ATC 层级", "atc.parent": "上级类目", "atc.children": "下级类目",
        "atc.ingredients": "该类别下的活性成分", "atc.count": "{n} 个活性成分",
        "atc.more": "另有 {n} 个", "atc.no_data": "该类别暂未收录活性成分。",
        "atc.unnamed": "类别名尚未校订——以 ATC 码为准。",
        "atc.ai_note": "类别名称为编辑或 AI 辅助译名；只有 ATC 码与 WHO 层级是权威依据。",
        "atc.source_note": ("ATC 码与层级引自 WHO Collaborating Centre for Drug Statistics "
                            "Methodology 的 ATC/DDD Index（版权归 WHOCC，本站不转载索引全文）。"
                            "成分/规格事实来自 About 页所列监管记录。"),
        "atc.all_classes": "全部 ATC 类别", "atc.search_link": "搜索该类别",
        "atc.view_class": "查看该 ATC 类别", "atc.categories_link": "消费者大类",
        "cat.quick_title": "按大类浏览", "cat.browse_title": "常见消费者大类",
        "cat.intro": ("编辑整理的主题合集：每个大类映射到 ATC 类别与活性成分。它只是浏览入口，"
                      "不代表这些药可以互相替代或等同。"),
        "cat.disclaimer": "主题合集——不代表同效或可互换。",
        "cat.count": "{n} 个活性成分", "cat.related_atc": "相关 ATC 类别",
        "cat.no_data": "该大类暂未收录活性成分。", "cat.back": "全部 ATC 类别与大类",
        "parse.category": "大类",
        "parse.category_note": "命中的是主题大类，不是药名；也不代表同效或可互换。",
        "parse.match.category": "大类 / ATC 类别",
    },
    "zh-Hant": {
        "nav.atc": "ATC / 大類", "atc.browse_title": "依 ATC 類別瀏覽",
        "atc.browse_intro": ("WHO ATC 依器官系統與藥理類別為藥物分類。可從一級大類或消費者大類開始；"
                             "每個頁面列出本站收錄的該類別有效成分。"),
        "atc.level": "ATC 層級", "atc.parent": "上級類目", "atc.children": "下級類目",
        "atc.ingredients": "該類別下的有效成分", "atc.count": "{n} 個有效成分",
        "atc.more": "另有 {n} 個", "atc.no_data": "該類別暫未收錄有效成分。",
        "atc.unnamed": "類別名尚未校訂——以 ATC 碼為準。",
        "atc.ai_note": "類別名稱為編輯或 AI 輔助譯名；只有 ATC 碼與 WHO 層級是權威依據。",
        "atc.source_note": ("ATC 碼與層級引自 WHO Collaborating Centre for Drug Statistics "
                            "Methodology 的 ATC/DDD Index（版權歸 WHOCC，本站不轉載索引全文）。"
                            "成分/規格事實來自 About 頁所列監管紀錄。"),
        "atc.all_classes": "全部 ATC 類別", "atc.search_link": "搜尋該類別",
        "atc.view_class": "查看該 ATC 類別", "atc.categories_link": "消費者大類",
        "cat.quick_title": "依大類瀏覽", "cat.browse_title": "常見消費者大類",
        "cat.intro": ("編輯整理的主題合集：每個大類對應 ATC 類別與有效成分。它只是瀏覽入口，"
                      "不代表這些藥可以互相替代或等同。"),
        "cat.disclaimer": "主題合集——不代表同效或可互換。",
        "cat.count": "{n} 個有效成分", "cat.related_atc": "相關 ATC 類別",
        "cat.no_data": "該大類暫未收錄有效成分。", "cat.back": "全部 ATC 類別與大類",
        "parse.category": "大類",
        "parse.category_note": "命中的是主題大類，不是藥名；也不代表同效或可互換。",
        "parse.match.category": "大類 / ATC 類別",
    },
}

# WHO ATC level-1 groups（四语编辑译名；代码权威）
ATC_L1_I18N = {
    "en": {"A": "Alimentary tract and metabolism", "B": "Blood and blood forming organs",
           "C": "Cardiovascular system", "D": "Dermatologicals",
           "G": "Genito-urinary system and sex hormones", "H": "Systemic hormonal preparations",
           "J": "Antiinfectives for systemic use",
           "L": "Antineoplastic and immunomodulating agents", "M": "Musculo-skeletal system",
           "N": "Nervous system", "P": "Antiparasitic products", "R": "Respiratory system",
           "S": "Sensory organs", "V": "Various"},
    "es": {"A": "Tracto alimentario y metabolismo", "B": "Sangre y órganos hematopoyéticos",
           "C": "Sistema cardiovascular", "D": "Dermatológicos",
           "G": "Sistema genitourinario y hormonas sexuales",
           "H": "Preparados hormonales sistémicos", "J": "Antiinfecciosos de uso sistémico",
           "L": "Antineoplásicos e inmunomoduladores", "M": "Sistema musculoesquelético",
           "N": "Sistema nervioso", "P": "Productos antiparasitarios", "R": "Sistema respiratorio",
           "S": "Órganos de los sentidos", "V": "Varios"},
    "zh": {"A": "消化系统及代谢", "B": "血液及造血器官", "C": "心血管系统", "D": "皮肤科用药",
           "G": "泌尿生殖系统及性激素", "H": "全身用激素制剂", "J": "全身用抗感染药",
           "L": "抗肿瘤及免疫调节药", "M": "肌肉骨骼系统", "N": "神经系统", "P": "抗寄生虫药",
           "R": "呼吸系统", "S": "感觉器官", "V": "其他"},
    "zh-Hant": {"A": "消化系統及代謝", "B": "血液及造血器官", "C": "心血管系統", "D": "皮膚科用藥",
                "G": "泌尿生殖系統及性激素", "H": "全身用激素製劑", "J": "全身用抗感染藥",
                "L": "抗腫瘤及免疫調節藥", "M": "肌肉骨骼系統", "N": "神經系統", "P": "抗寄生蟲藥",
                "R": "呼吸系統", "S": "感覺器官", "V": "其他"},
}

# L2–L4 常见类别名（编辑/AI 译名；未收录的类目页以 ATC 码为标题并标注待校订）
ATC_CLASS_I18N = {
    "en": {"A02": "Drugs for acid related disorders", "A08": "Antiobesity preparations",
           "A10": "Drugs used in diabetes", "A10BA": "Biguanides",
           "B01": "Antithrombotic agents", "B01AA": "Vitamin K antagonists",
           "C07": "Beta blocking agents", "C07A": "Beta blocking agents",
           "C07AB": "Selective beta-1 blocking agents", "C08": "Calcium channel blockers",
           "C09": "Agents acting on the renin-angiotensin system", "C10": "Lipid modifying agents",
           "C10AA": "HMG-CoA reductase inhibitors (statins)", "D": "Dermatologicals",
           "G04": "Urologicals", "H02": "Corticosteroids for systemic use",
           "J01": "Antibacterials for systemic use", "J05": "Antivirals for systemic use",
           "M01": "Antiinflammatory and antirheumatic products", "N02": "Analgesics",
           "N02BE": "Anilides", "N06A": "Antidepressants",
           "R03": "Drugs for obstructive airway diseases", "R05": "Cough and cold preparations",
           "R06": "Antihistamines for systemic use"},
    "es": {"A02": "Fármacos para trastornos ácido-relacionados",
           "A08": "Preparados antiobesidad", "A10": "Fármacos usados en diabetes",
           "A10BA": "Biguanidas", "B01": "Agentes antitrombóticos",
           "B01AA": "Antagonistas de la vitamina K", "C07": "Betabloqueantes",
           "C07A": "Betabloqueantes", "C07AB": "Betabloqueantes selectivos beta-1",
           "C08": "Bloqueantes de los canales de calcio",
           "C09": "Agentes del sistema renina-angiotensina",
           "C10": "Fármacos modificadores de lípidos",
           "C10AA": "Inhibidores de la HMG-CoA reductasa (estatinas)", "D": "Dermatológicos",
           "G04": "Urológicos", "H02": "Corticosteroides de uso sistémico",
           "J01": "Antibacterianos de uso sistémico", "J05": "Antivirales de uso sistémico",
           "M01": "Antiinflamatorios y antirreumáticos", "N02": "Analgésicos",
           "N02BE": "Anilidas", "N06A": "Antidepresivos",
           "R03": "Fármacos para enfermedades obstructivas de las vías respiratorias",
           "R05": "Preparados para la tos y el resfriado",
           "R06": "Antihistamínicos de uso sistémico"},
    "zh": {"A02": "酸相关疾病用药", "A08": "减肥/抗肥胖药", "A10": "糖尿病用药",
           "A10BA": "双胍类", "B01": "抗血栓药", "B01AA": "维生素 K 拮抗剂",
           "C07": "β受体阻滞剂", "C07A": "β受体阻滞剂", "C07AB": "选择性 β1 受体阻滞剂",
           "C08": "钙通道阻滞剂", "C09": "肾素-血管紧张素系统药物", "C10": "调脂药",
           "C10AA": "HMG-CoA 还原酶抑制剂（他汀类）", "D": "皮肤科用药", "G04": "泌尿系统用药",
           "H02": "全身用糖皮质激素", "J01": "全身用抗菌药", "J05": "全身用抗病毒药",
           "M01": "抗炎抗风湿药", "N02": "镇痛药", "N02BE": "苯胺类", "N06A": "抗抑郁药",
           "R03": "阻塞性气道疾病用药", "R05": "咳嗽与感冒用药", "R06": "全身用抗组胺药"},
    "zh-Hant": {"A02": "酸相關疾病用藥", "A08": "減肥/抗肥胖藥", "A10": "糖尿病用藥",
                "A10BA": "雙胍類", "B01": "抗血栓藥", "B01AA": "維生素 K 拮抗劑",
                "C07": "β受體阻滯劑", "C07A": "β受體阻滯劑", "C07AB": "選擇性 β1 受體阻滯劑",
                "C08": "鈣通道阻滯劑", "C09": "腎素-血管緊張素系統藥物", "C10": "調脂藥",
                "C10AA": "HMG-CoA 還原酶抑制劑（他汀類）", "D": "皮膚科用藥", "G04": "泌尿系統用藥",
                "H02": "全身用糖皮質激素", "J01": "全身用抗菌藥", "J05": "全身用抗病毒藥",
                "M01": "抗炎抗風濕藥", "N02": "鎮痛藥", "N02BE": "苯胺類", "N06A": "抗抑鬱藥",
                "R03": "阻塞性氣道疾病用藥", "R05": "咳嗽與感冒用藥", "R06": "全身用抗組胺藥"},
}

CONSUMER_CATEGORIES = [
    {"id": "antihypertensives", "prefixes": ["C02", "C03", "C07", "C08", "C09"],
     "labels": {"en": "Blood-pressure medicines", "es": "Medicamentos para la presión arterial",
                "zh": "降压药", "zh-Hant": "降血壓藥"},
     "desc": {"en": "ATC C02/C03/C07/C08/C09 — antihypertensives and related classes.",
              "es": "ATC C02/C03/C07/C08/C09 — antihipertensivos y clases relacionadas.",
              "zh": "ATC C02/C03/C07/C08/C09——降压及相关类别。",
              "zh-Hant": "ATC C02/C03/C07/C08/C09——降壓及相關類別。"}},
    {"id": "antibiotics", "prefixes": ["J01"],
     "labels": {"en": "Antibiotics", "es": "Antibióticos", "zh": "抗生素", "zh-Hant": "抗生素"},
     "desc": {"en": "ATC J01 — systemic antibacterials.",
              "es": "ATC J01 — antibacterianos sistémicos.", "zh": "ATC J01——全身用抗菌药。",
              "zh-Hant": "ATC J01——全身用抗菌藥。"}},
    {"id": "diabetes", "prefixes": ["A10"],
     "labels": {"en": "Diabetes medicines", "es": "Medicamentos para la diabetes",
                "zh": "降糖药", "zh-Hant": "降血糖藥"},
     "desc": {"en": "ATC A10 — drugs used in diabetes.",
              "es": "ATC A10 — fármacos para diabetes.", "zh": "ATC A10——糖尿病用药。",
              "zh-Hant": "ATC A10——糖尿病用藥。"}},
    {"id": "weight-loss", "prefixes": ["A08"],
     "labels": {"en": "Weight-loss medicines", "es": "Medicamentos para perder peso",
                "zh": "减肥药", "zh-Hant": "減重藥"},
     "desc": {"en": "ATC A08 — antiobesity preparations.", "es": "ATC A08 — antiobesidad.",
              "zh": "ATC A08——抗肥胖药。", "zh-Hant": "ATC A08——抗肥胖藥。"}},
    {"id": "cold-medicine", "prefixes": ["R05", "N02BE", "R06"],
     "labels": {"en": "Cold & cough medicines", "es": "Medicamentos para resfriado y tos",
                "zh": "感冒咳嗽药", "zh-Hant": "感冒咳嗽藥"},
     "desc": {"en": "ATC R05/N02BE/R06 — cough/cold preparations and antihistamines. Consumer "
                    "“cold medicine” is broader than one ATC class.",
              "es": "ATC R05/N02BE/R06 — tos/resfriado y antihistamínicos; el término popular es "
                    "más amplio que una clase ATC.",
              "zh": "ATC R05/N02BE/R06——咳嗽/感冒与抗组胺类；消费者说的「感冒药」比单一 ATC 类别更宽。",
              "zh-Hant": "ATC R05/N02BE/R06——咳嗽/感冒與抗組胺類；消費者說的「感冒藥」比單一 ATC 類別更寬。"}},
    {"id": "analgesics", "prefixes": ["N02", "M01A"],
     "labels": {"en": "Pain & fever relief", "es": "Analgésicos y antitérmicos",
                "zh": "退烧止痛", "zh-Hant": "退燒止痛"},
     "desc": {"en": "ATC N02/M01A — analgesics and antipyretics.",
              "es": "ATC N02/M01A — analgésicos y antipiréticos.",
              "zh": "ATC N02/M01A——镇痛与退热药。", "zh-Hant": "ATC N02/M01A——鎮痛與退熱藥。"}},
    {"id": "allergy", "prefixes": ["R06"],
     "labels": {"en": "Allergy medicines", "es": "Medicamentos para la alergia",
                "zh": "抗过敏药", "zh-Hant": "抗過敏藥"},
     "desc": {"en": "ATC R06 — systemic antihistamines.",
              "es": "ATC R06 — antihistamínicos sistémicos.", "zh": "ATC R06——全身用抗组胺药。",
              "zh-Hant": "ATC R06——全身用抗組胺藥。"}},
    {"id": "acid-related", "prefixes": ["A02"],
     "labels": {"en": "Stomach / acid medicines", "es": "Medicamentos gástricos / de acidez",
                "zh": "胃药", "zh-Hant": "胃藥"},
     "desc": {"en": "ATC A02 — acid-related disorder drugs (antacids, PPIs, H2 blockers).",
              "es": "ATC A02 — antiácidos, IBP, antihistamínicos H2.",
              "zh": "ATC A02——抗酸、质子泵抑制剂、H2 受体拮抗剂等。",
              "zh-Hant": "ATC A02——抗酸、質子泵抑制劑、H2 受體拮抗劑等。"}},
    {"id": "anticoagulants", "prefixes": ["B01"],
     "labels": {"en": "Blood thinners / antithrombotics",
                "es": "Anticoagulantes / antitrombóticos", "zh": "抗凝药",
                "zh-Hant": "抗凝血藥"},
     "desc": {"en": "ATC B01 — antithrombotic agents. Not all are interchangeable.",
              "es": "ATC B01 — antitrombóticos; no todos son intercambiables.",
              "zh": "ATC B01——抗血栓药；彼此不都可互换。",
              "zh-Hant": "ATC B01——抗血栓藥；彼此不都可互換。"}},
    {"id": "statins", "prefixes": ["C10AA"],
     "labels": {"en": "Statins", "es": "Estatinas", "zh": "他汀类", "zh-Hant": "他汀類"},
     "desc": {"en": "ATC C10AA — HMG-CoA reductase inhibitors.",
              "es": "ATC C10AA — inhibidores de la HMG-CoA reductasa.",
              "zh": "ATC C10AA——HMG-CoA 还原酶抑制剂。",
              "zh-Hant": "ATC C10AA——HMG-CoA 還原酶抑制劑。"}},
    {"id": "beta-blockers", "prefixes": ["C07"],
     "labels": {"en": "Beta blockers", "es": "Betabloqueantes", "zh": "β受体阻滞剂",
                "zh-Hant": "β受體阻斷劑"},
     "desc": {"en": "ATC C07 — beta blocking agents.", "es": "ATC C07 — betabloqueantes.",
              "zh": "ATC C07——β受体阻滞剂。", "zh-Hant": "ATC C07——β受體阻滯劑。"}},
    {"id": "antidepressants", "prefixes": ["N06A"],
     "labels": {"en": "Antidepressants", "es": "Antidepresivos", "zh": "抗抑郁药",
                "zh-Hant": "抗憂鬱藥"},
     "desc": {"en": "ATC N06A — antidepressants.", "es": "ATC N06A — antidepresivos.",
              "zh": "ATC N06A——抗抑郁药。", "zh-Hant": "ATC N06A——抗抑鬱藥。"}},
    {"id": "asthma-copd", "prefixes": ["R03"],
     "labels": {"en": "Asthma / COPD inhalers", "es": "Inhaladores para asma / EPOC",
                "zh": "哮喘·慢阻肺吸入剂", "zh-Hant": "哮喘·慢阻肺吸入劑"},
     "desc": {"en": "ATC R03 — drugs for obstructive airway diseases.",
              "es": "ATC R03 — enfermedades obstructivas de las vías respiratorias.",
              "zh": "ATC R03——阻塞性气道疾病用药。", "zh-Hant": "ATC R03——阻塞性氣道疾病用藥。"}},
    {"id": "corticosteroids", "prefixes": ["H02"],
     "labels": {"en": "Steroid hormones", "es": "Hormonas esteroideas", "zh": "激素类",
                "zh-Hant": "荷爾蒙類"},
     "desc": {"en": "ATC H02 — corticosteroids for systemic use.",
              "es": "ATC H02 — corticosteroides sistémicos.", "zh": "ATC H02——全身用糖皮质激素。",
              "zh-Hant": "ATC H02——全身用糖皮質激素。"}},
    {"id": "antivirals", "prefixes": ["J05"],
     "labels": {"en": "Antivirals", "es": "Antivirales", "zh": "抗病毒药", "zh-Hant": "抗病毒藥"},
     "desc": {"en": "ATC J05 — antivirals for systemic use.",
              "es": "ATC J05 — antivirales sistémicos.", "zh": "ATC J05——全身用抗病毒药。",
              "zh-Hant": "ATC J05——全身用抗病毒藥。"}},
    {"id": "dermatologicals", "prefixes": ["D"],
     "labels": {"en": "Skin medicines", "es": "Medicamentos dermatológicos", "zh": "皮肤外用药",
                "zh-Hant": "皮膚外用藥"},
     "desc": {"en": "ATC D — dermatologicals (broad class).",
              "es": "ATC D — dermatológicos (clase amplia).", "zh": "ATC D——皮肤科用药（大类）。",
              "zh-Hant": "ATC D——皮膚科用藥（大類）。"}},
]


def build_glossary() -> None:
    """v0.6.4 B10：/glossary.html 术语表（四语，客户端按语言切块 + /es//zh//zh-hant/ 静态副本）。"""
    blocks = []
    for lang in ("en", "es", "zh", "zh-Hant"):
        D = I18N.get(lang) or I18N["en"]
        rows = "".join(
            f'<dt>{esc(D.get("glossary.t." + term, term))}</dt>'
            f'<dd>{esc(D.get("glossary.d." + term, ""))}</dd>'
            for term in GLOSSARY_TERMS)
        blocks.append(f'<div class="lang-block" data-lang-block="{lang}">'
                      f'<dl class="glossary">{rows}</dl></div>')
    body = (f'<h1 data-i18n="glossary.title">{esc(I18N["en"]["glossary.title"])}</h1>'
            f'<div data-i18n-html="glossary.intro">{I18N["en"]["glossary.intro"]}</div>'
            + "".join(blocks)
            + f'<div class="notice" data-i18n="glossary.note">'
              f'{esc(I18N["en"]["glossary.note"])}</div>')
    html = page("Glossary", body, meta_key="glossary", alternates=True,
                canonical_rel="glossary.html", alt_rel="glossary.html")
    _write_with_copies("glossary.html", html, "glossary")


# ── v0.7.x：ATC 类目页 / 大类页 / landing / 客户端 categories.json ──────────
ATC_MEMBER_CAP = 60
ATC_LEN_LEVEL = {1: 1, 3: 2, 4: 3, 5: 4}


def _atc_display_name(lang: str, code: str) -> str:
    if len(code) == 1:
        return ATC_L1_I18N.get(lang, {}).get(code, "")
    return ATC_CLASS_I18N.get(lang, {}).get(code, "")


def _atc_names(code: str) -> dict[str, str]:
    return {lang: _atc_display_name(lang, code) for lang in ("en", "es", "zh", "zh-Hant")}


def _lang_inline(labels: dict[str, str]) -> str:
    """行内语言块（i18n.js 对 data-lang-inline=1 用 inline 显示）。"""
    return "".join(
        f'<span class="lang-block" data-lang-block="{lang}" data-lang-inline="1">'
        f'{esc(text)}</span>'
        for lang, text in labels.items() if text)


def _atc_groups(db: sqlite3.Connection) -> dict[int, dict[str, list[dict]]]:
    rows = [dict(r) for r in db.execute(
        "SELECT substance_id, inn_en, inn_zh, atc FROM substance "
        "WHERE atc IS NOT NULL AND atc <> '' ORDER BY atc, inn_en")]
    groups: dict[int, dict[str, list[dict]]] = {1: {}, 3: {}, 4: {}, 5: {}}
    for r in rows:
        for ln in (1, 3, 4, 5):
            if len(r["atc"]) >= ln:
                groups[ln].setdefault(r["atc"][:ln], []).append(r)
    return groups


def _sub_name_spans(en: str, zh: str, sid: str) -> str:
    """v0.8.2 task-120：成分名紧凑多语标记（data-n-*；bilingual.js 按当前语言渲染，
    中文优先；无中文名 → 英文 + 暂无中文名）。比四个 lang-block 更省体积。"""
    entry = (BILINGUAL_TRANS.get("sub", {}) or {}).get(sid) or {}
    es = ((entry.get("es") or {}).get("n") or "")
    zhh = ((entry.get("zh-Hant") or {}).get("n") or "")
    en_txt = en or sid or ""
    return (f'<span class="nm" data-n-en="{esc(en_txt)}" data-n-zh="{esc(zh or "")}" '
            f'data-n-zhh="{esc(zhh)}" data-n-es="{esc(es)}">{esc(en_txt)}</span>')


def _atc_members_html(subs: list[dict], cap: int = ATC_MEMBER_CAP,
                      drug_sids: set[str] | None = None) -> str:
    # 有中文名的排前（中文用户优先看到可读名），其余按 en；再按 sid 稳定
    ordered = sorted(subs, key=lambda r: (
        0 if (r.get("inn_zh") or "").strip() else 1,
        (r.get("inn_zh") or r.get("inn_en") or "").lower(), r.get("substance_id") or ""))
    items = []
    for r in ordered[:cap]:
        zh = r.get("inn_zh") or ""
        en = r.get("inn_en") or ""
        sid = r["substance_id"]
        name_html = _sub_name_spans(en, zh, sid)
        if drug_sids is None or sid in drug_sids:
            label = f'<a href="../drug/{esc(sid)}.html">{name_html}</a>'
        else:
            # 有 ATC 但没有 product 的成分没有 drug 页 → 纯文本，避免 ../drug/ 404
            label = f'<span class="brand-plain">{name_html}</span>'
        items.append(f'<li>{label} <code>{esc(r["atc"])}</code></li>')
    more = ""
    if len(ordered) > cap:
        more = (f'<p class="sub" data-i18n="atc.more">and {len(ordered) - cap} more</p>')
    return f'<ul class="sub atclist atcmembers">{"".join(items)}</ul>{more}'


def build_atc_pages(db: sqlite3.Connection) -> int:
    """L1–L4 ATC 类目页 /atc/<prefix>.html（父/子类目可逐级浏览）。"""
    groups = _atc_groups(db)
    drug_sids = {p.stem for p in (OUT / "drug").glob("*.html")}
    (OUT / "atc").mkdir(parents=True, exist_ok=True)
    T = I18N["en"]
    made = 0
    for ln in (1, 3, 4, 5):
        child_ln = {1: 3, 3: 4, 4: 5}.get(ln)
        for code, subs in sorted(groups[ln].items()):
            level = ATC_LEN_LEVEL[len(code)]
            parent = {3: code[:1], 4: code[:3], 5: code[:4]}.get(len(code), "")
            names = _atc_names(code)
            name_html = _lang_inline(names)
            title_html = f'<code>{esc(code)}</code> {name_html}'
            unnamed = "" if any(names.values()) else (
                f'<p class="sub" data-i18n="atc.unnamed">{esc(T["atc.unnamed"])}</p>')
            crumbs = (f'<a href="../atc.html" data-i18n="atc.all_classes">'
                      f'{esc(T["atc.all_classes"])}</a>')
            if parent:
                crumbs += f' · <a href="../atc/{esc(parent)}.html"><code>{esc(parent)}</code></a>'
            children = ""
            if child_ln:
                kids = sorted(groups[child_ln].items())
                kids = [(c, s) for c, s in kids if c.startswith(code)]
                if kids:
                    lis = []
                    for c, s in kids:
                        lis.append(f'<li><a href="../atc/{esc(c)}.html"><code>{esc(c)}</code> '
                                   f'{_lang_inline(_atc_names(c))}</a> '
                                   f'<span class="meta">({len(s)})</span></li>')
                    children = (f'<h2 data-i18n="atc.children">{esc(T["atc.children"])}</h2>'
                                f'<ul class="sub atclist">{"".join(lis)}</ul>')
            search_href = f'../index.html?q={esc(code)}'
            body = f"""<p class="sub">{crumbs}</p>
<h1>{title_html} <span class="tag">L{level}</span></h1>
{unnamed}
<p class="sub"><span data-i18n="atc.level">{esc(T["atc.level"])}</span> L{level} ·
<a class="linkbtn" href="{search_href}" data-i18n="atc.search_link">{esc(T["atc.search_link"])}</a>
· <a href="../atc.html" data-i18n="atc.categories_link">{esc(T["atc.categories_link"])}</a></p>
{children}
<h2 data-i18n="atc.ingredients">{esc(T["atc.ingredients"])}</h2>
{_atc_members_html(subs, drug_sids=drug_sids)}
<div class="notice" data-i18n="atc.ai_note">{esc(T["atc.ai_note"])}</div>
<div class="notice" data-i18n="atc.source_note">{esc(T["atc.source_note"])}</div>"""
            (OUT / "atc" / f"{code}.html").write_text(
                page(f"ATC {code}", body, "../"), encoding="utf-8")
            made += 1
    return made


def build_category_pages(db: sqlite3.Connection) -> int:
    """常见消费者大类 /cat/<id>.html（主题合集，非药效等同）。"""
    rows = [dict(r) for r in db.execute(
        "SELECT substance_id, inn_en, inn_zh, atc FROM substance "
        "WHERE atc IS NOT NULL AND atc <> '' ORDER BY atc, inn_en")]
    drug_sids = {p.stem for p in (OUT / "drug").glob("*.html")}
    (OUT / "cat").mkdir(parents=True, exist_ok=True)
    T = I18N["en"]
    made = 0
    for cat in CONSUMER_CATEGORIES:
        seen = set()
        subs = []
        for r in rows:
            if any(r["atc"].startswith(p) for p in cat["prefixes"]):
                if r["substance_id"] not in seen:
                    seen.add(r["substance_id"])
                    subs.append(r)
        related = "".join(
            f'<li><a href="../atc/{esc(p)}.html"><code>{esc(p)}</code> '
            f'{_lang_inline(_atc_names(p))}</a></li>' for p in cat["prefixes"])
        title_labels = cat["labels"]
        display_title = _lang_inline(title_labels)
        desc_blocks = "".join(
            f'<div class="lang-block" data-lang-block="{lang}">{esc(cat["desc"][lang])}</div>'
            for lang in ("en", "es", "zh", "zh-Hant"))
        body = f"""<p class="sub"><a href="../atc.html" data-i18n="cat.back">{esc(T["cat.back"])}</a></p>
<h1>{display_title}</h1>
<p class="sub cat-en">{esc(cat["labels"]["en"])}</p>
{desc_blocks}
<p class="sub" data-i18n="cat.disclaimer">{esc(T["cat.disclaimer"])}</p>
<h2 data-i18n="cat.related_atc">{esc(T["cat.related_atc"])}</h2>
<ul class="sub atclist">{related}</ul>
<h2 data-i18n="atc.ingredients">{esc(T["atc.ingredients"])}</h2>
{_atc_members_html(subs, cap=80, drug_sids=drug_sids)}
<div class="notice" data-i18n="atc.ai_note">{esc(T["atc.ai_note"])}</div>
<div class="notice" data-i18n="atc.source_note">{esc(T["atc.source_note"])}</div>"""
        (OUT / "cat" / f'{cat["id"]}.html').write_text(
            page(cat["labels"]["en"], body, "../"), encoding="utf-8")
        made += 1
    return made


def build_atc_index() -> None:
    """���式 /atc.html：14 个 ATC L1 大类 + 16 个消费者大类入口。"""
    T = I18N["en"]
    l1_codes = ("A", "B", "C", "D", "G", "H", "J", "L", "M", "N", "P", "R", "S", "V")
    l1_html = "".join(
        f'<a class="atccard" href="atc/{code}.html"><code>{code}</code> '
        f'{_lang_inline(_atc_names(code))}</a>' for code in l1_codes)
    cat_html = "".join(
        f'<a class="atccard" href="cat/{cat["id"]}.html">'
        f'<span class="lang-block" data-lang-block="en" data-lang-inline="1">'
        f'{esc(cat["labels"]["en"])}</span>'
        f'<span class="lang-block" data-lang-block="es" data-lang-inline="1">'
        f'{esc(cat["labels"]["es"])}</span>'
        f'<span class="lang-block" data-lang-block="zh" data-lang-inline="1">'
        f'{esc(cat["labels"]["zh"])}</span>'
        f'<span class="lang-block" data-lang-block="zh-Hant" data-lang-inline="1">'
        f'{esc(cat["labels"]["zh-Hant"])}</span>'
        f'<span class="meta cat-en">{esc(cat["labels"]["en"])}</span></a>'
        for cat in CONSUMER_CATEGORIES)
    body = f"""<h1 data-i18n="atc.browse_title">{esc(T["atc.browse_title"])}</h1>
<div data-i18n="atc.browse_intro">{esc(T["atc.browse_intro"])}</div>
<h2 data-i18n="atc.browse_title">{esc(T["atc.browse_title"])}</h2>
<div class="atcgrid">{l1_html}</div>
<h2 data-i18n="cat.browse_title">{esc(T["cat.browse_title"])}</h2>
<div data-i18n="cat.intro">{esc(T["cat.intro"])}</div>
<div class="catgrid">{cat_html}</div>
<p class="sub" data-i18n="cat.disclaimer">{esc(T["cat.disclaimer"])}</p>
<div class="notice" data-i18n="atc.ai_note">{esc(T["atc.ai_note"])}</div>
<div class="notice" data-i18n="atc.source_note">{esc(T["atc.source_note"])}</div>"""
    (OUT / "atc.html").write_text(page("ATC classes & categories", body, ""), encoding="utf-8")


def build_categories_json(db: sqlite3.Connection) -> None:
    """客户端搜索用：大类/ATC 类别名 + 前缀 + 页面 URL + 已生成的 ATC 码集合。"""
    items = []
    for cat in CONSUMER_CATEGORIES:
        labels = dict(cat["labels"])
        aliases = [labels.get("en", ""), cat["id"]]
        items.append({"kind": "cat", "id": cat["id"], "url": f'cat/{cat["id"]}.html',
                      "prefixes": list(cat["prefixes"]), "labels": labels,
                      "aliases": [a for a in aliases if a]})
    codes = set(ATC_L1_I18N["en"]) | set(ATC_CLASS_I18N["en"])
    for code in sorted(codes):
        items.append({"kind": "atc", "id": code, "url": f"atc/{code}.html",
                      "prefixes": [code], "labels": _atc_names(code), "aliases": [code.lower()]})
    # atc_codes 用于客户端判断「该类目页是否存在」（全部 L1–L4 前缀，1,154 个）
    groups = _atc_groups(db)
    all_codes: set[str] = set()
    for ln in (1, 3, 4, 5):
        all_codes.update(groups[ln].keys())
    (OUT / "data" / "categories.json").write_text(
        json.dumps({"categories": items, "atc_codes": sorted(all_codes)},
                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _home_cat_chips(lang: str, prefix: str) -> str:
    """v0.8.2 task-114：chips 四语内联块（根页/副本都随 UI 语言切换，不再固定英文）。"""
    langs = ("en", "es", "zh", "zh-Hant")
    parts = []
    for cat in CONSUMER_CATEGORIES:
        spans = "".join(
            f'<span class="lang-block" data-lang-block="{l}" data-lang-inline="1">'
            f'{esc(cat["labels"][l])}</span>' for l in langs)
        parts.append(f'<a class="catchip" href="{prefix}cat/{cat["id"]}.html">{spans}</a>')
    return "".join(parts)


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
    # 第三方部署验证文件：固定公开随机串，每次构建都写到站点根目录（不属于页面，不进 sitemap）。
    # 用二进制写入保证恰好是 40 字节哈希 + LF（Windows 文本模式会写成 CRLF）。
    (OUT / "e2fea3dfe91d65e7c4dc23106afa53e2.txt").write_bytes(
        b"50b080b3ad91dc61bc684f8cef65ce3bbb99e77c\n")
    # GitHub Pages 默认会跑 Jekyll；.nojekyll 让它直接当静态文件发。
    # 内容留一行说明：发布脚本会拒绝 0 字节文件（防止构建中断发布半成品）。
    (OUT / ".nojekyll").write_text(
        "# GitHub Pages: serve this directory as-is (skip Jekyll)\n", encoding="utf-8")
    print(f"  seo files  : 404 + robots + sitemap ({len(urls)} urls) + deploy verify", flush=True)


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
#   f（剂型）v0.6.1 加入核心：B7 CSV 导出用 e.f，且 ?legacy=1 走 core 解码后需与旧
#   index.json 完全同构（除 f 外 19 字段已验证 0 差异；f 只有 ~9 种字典值，core +0.2–0.3 MB）。
CORE_DICT_COLS = ("c", "x", "s", "l", "v", "vs", "cu", "mu", "g", "gn", "m", "f",
                  "db", "sl", "rl", "wi")
CORE_ARRAY_COLS = ("c", "s", "vs", "ml", "xz", "atc")     # 值是数组：先 JSON 化再进字典


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
    for f in ("c", "x", "xz", "atc", "s", "l", "f", "n", "v", "vs", "u", "cu", "mu", "ml", "g", "gn",
              "m", "mn", "db", "sl", "rl", "wi"):
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



def _shard_bucket(key: str) -> str:
    """分片桶：首字符 A-Z / 数字 / CJK 按拼音首字母 / 其他符号。"""
    ch = (key or "")[:1]
    if not ch:
        return "other"
    if "a" <= ch <= "z":
        return ch
    if ch.isdigit():
        return "digit"
    if "\u3400" <= ch <= "\u9fff":
        py = _pinyin_dict().get(ch)
        return "cjk-" + (py[0] if py else "x")
    return "other"


def encode_shards(entries) -> dict:
    """P2：按首字母 A-Z/数字/CJK 拼音首字母分桶，再按原始字节切成 ~1.1 MB 的分片。

    每个分片是 index.json 同构的条目数组（客户端可直接渲染）；manifest 记录每片
    first/last 便于按查询前缀只取相交的 1-3 片；core.json 保留为一次加载的完整回退。
    """
    idx_dir = OUT / "data" / "idx"
    core_path = idx_dir / "core.json"
    buckets: dict[str, list] = {}
    for e in entries:
        buckets.setdefault(_shard_bucket(e["k"]), []).append(e)
    manifest = {"v": int(time.time()), "n": len(entries), "buckets": {},
                "cjkInitials": {},
                "core": {"f": "data/idx/core.json", "bytes": core_path.stat().st_size}}
    target = 1_100_000  # 原始字节/片（gzip 后约 150-220 KB）
    total_bytes = total_shards = 0
    for bucket in sorted(buckets):
        rows = sorted(buckets[bucket], key=lambda e: e["k"])
        sizes = [len(json.dumps(e, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                 for e in rows]
        groups, cur, acc = [], [], 0
        for i, e in enumerate(rows):
            cur.append(e)
            acc += sizes[i] + 1
            if acc >= target:
                groups.append(cur)
                cur, acc = [], 0
        if cur:
            groups.append(cur)
        files = []
        for si, grp in enumerate(groups):
            fn = f"shard-{bucket}-{si}.json"
            data = json.dumps(grp, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            (idx_dir / fn).write_bytes(data)
            files.append({"f": "data/idx/" + fn, "first": grp[0]["k"], "last": grp[-1]["k"],
                          "n": len(grp), "bytes": len(data)})
            total_bytes += len(data)
            total_shards += 1
        manifest["buckets"][bucket] = files
        if bucket.startswith("cjk-"):
            for e in rows:
                manifest["cjkInitials"].setdefault(e["k"][0], bucket)
    manifest["shardCount"] = total_shards
    manifest["shardBytes"] = total_bytes
    return manifest


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True, exist_ok=True)
    (OUT / "data").mkdir(parents=True, exist_ok=True)
    (OUT / "assets" / "style.css").write_text(CSS, encoding="utf-8")
    def _render_i18n_js() -> str:
        return ("window.I18N=" + json.dumps(I18N, ensure_ascii=False) + ";\n"
                + LANG_META_JS + "\n" + r"""
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
  function canon(x){
    if(!x) return '';
    var c = String(x).trim();
    if(D[c]) return c;
    var l = c.toLowerCase();
    if(LANG_ALIAS[l] && D[LANG_ALIAS[l]]) return LANG_ALIAS[l];
    var base = l.split('-')[0];
    if(base && D[base]) return base;
    return '';
  }
  function pick(){
    var q = canon(new URLSearchParams(location.search).get('lang'));
    if(q){ try{localStorage.setItem('lang',q);}catch(e){} return q; }
    var first = relPath().split('/').filter(Boolean)[0] || '';
    // 直接进 /es/、/zh/、/zh-hant/（hreflang 主入口）时把语言写进 localStorage，
    // 这样点导航去 /about.html 等根路径页面不会掉回 en。
    var seg = canon(first);
    if(seg){ try{localStorage.setItem('lang',seg);}catch(e){} return seg; }
    try{ var s = canon(localStorage.getItem('lang')); if(s) return s; }catch(e){}
    var n = canon(navigator.language);
    return n || DEFAULT_LANG;
  }
  window.LANG = pick();
  window.T = function(k){
    var L = D[window.LANG];
    var v = L ? L[k] : undefined;
    // v0.6.2：繁体字典缺键时回退简体（再回退英文），避免出现空文本
    if(v === undefined && window.LANG === 'zh-Hant' && D.zh) v = D.zh[k];
    if(v === undefined) v = D.en[k];
    return v === undefined ? k : v;
  };
  function apply(){
    document.documentElement.lang = window.LANG;
    document.querySelectorAll('[data-i18n]').forEach(function(el){ el.textContent = window.T(el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-aria]').forEach(function(el){ el.setAttribute('aria-label', window.T(el.dataset.i18nAria)); });
    // v0.5.5：<title> / description / OG 本地化（根页 head 带 data-i18n-title/meta）
    document.querySelectorAll('[data-i18n-title]').forEach(function(el){
      var t = window.T(el.dataset.i18nTitle);
      el.textContent = t;
      if(el.tagName === 'TITLE') document.title = t;
    });
    document.querySelectorAll('[data-i18n-meta]').forEach(function(el){
      el.setAttribute('content', window.T(el.dataset.i18nMeta));
    });
    // i18n P1：About / What's new / Confused / 404 的正文块允许内嵌链接与表格，
    // 用 data-i18n-html 走 innerHTML（内容全部来自构建期字典，非用户输入）。
    document.querySelectorAll('[data-i18n-html]').forEach(function(el){ el.innerHTML = window.T(el.dataset.i18nHtml); });
    // v0.5.4：移动端卡片列名（CSS content:attr(data-label)）也随语言切换（厂家页等）。
    document.querySelectorAll('[data-i18n-label]').forEach(function(el){
      el.setAttribute('data-label', window.T(el.dataset.i18nLabel));
    });
    // /warn 与成分页的警示正文是数据行（zh/en/es 各一份），按当前语言只显示对应块。
    document.querySelectorAll('[data-lang-block]').forEach(function(el){
      var on = (el.dataset.langBlock === window.LANG);
      var inline = el.getAttribute('data-lang-inline') === '1';
      el.style.display = on ? (inline ? 'inline' : 'block') : 'none';
    });
    // v0.6.6：成分页多国矩阵按界面语言排序列（服务端默认 en 序：US/GB/CA/AU/CN/ES/MX）。
    // v0.6.6/v0.7.0/v0.7.x：语言列序（含 TW/SG：zh → CN,TW,SG；zh-Hant → TW,CN,HK,SG；es → ES,MX…）
    var MORDER = {en: ['US','GB','CA','AU','SG','CN','ES','MX','TW'],
                  es: ['ES','MX','US','GB','CA','AU','SG','CN','TW'],
                  zh: ['CN','TW','SG','US','GB','CA','AU','ES','MX'],
                  'zh-Hant': ['TW','CN','HK','SG','US','GB','CA','AU','ES','MX']};
    var morder = MORDER[window.LANG] || MORDER.en;
    window.COUNTRY_ORDER = morder;   // app.js 用它给国家 chips 排序
    document.querySelectorAll('table.matrix').forEach(function(tb){
      var rank = {};
      for(var i = 0; i < morder.length; i++) rank[morder[i]] = i;
      Array.prototype.forEach.call(tb.querySelectorAll('tr'), function(tr){
        var cells = Array.prototype.slice.call(tr.children);
        cells.sort(function(a, b){
          var ca = a.getAttribute('data-country'), cb = b.getAttribute('data-country');
          if(!ca && !cb) return 0;
          if(!ca) return -1;
          if(!cb) return 1;
          var ra = (rank[ca] === undefined) ? 99 : rank[ca];
          var rb = (rank[cb] === undefined) ? 99 : rank[cb];
          return ra - rb;
        });
        for(var c = 0; c < cells.length; c++) tr.appendChild(cells[c]);
      });
    });
    // v0.7.0：国家下拉按界面语言排序（TW 已接入；「All countries」保持第一项）
    var selC = document.getElementById('country');
    if(selC){
      var rankC = {};
      for(var ci = 0; ci < morder.length; ci++) rankC[morder[ci]] = ci;
      var opts = Array.prototype.slice.call(selC.querySelectorAll('option[value]'))
        .filter(function(o){ return !!o.getAttribute('value'); });
      opts.sort(function(a, b){
        var ra = (rankC[a.value] === undefined) ? 99 : rankC[a.value];
        var rb = (rankC[b.value] === undefined) ? 99 : rankC[b.value];
        return ra - rb;
      });
      opts.forEach(function(o){ selC.appendChild(o); });
    }
    document.querySelectorAll('[data-ph]').forEach(function(el){ el.placeholder = window.T(el.dataset.ph); });
    document.querySelectorAll('.langs a').forEach(function(a){
      a.classList.toggle('on', a.dataset.lang === window.LANG);
    });
    // v0.8.2 task-120：语言确定后再渲染 ATC/组合页成分名（避免 defer 早于 ?lang 解析）
    if(window.renderBilingualNames) window.renderBilingualNames();
  }
  function langTarget(code){
    // v0.5.5/v0.6.2：有 /es/、/zh/、/zh-hant/ 静态副本的页面（首页/about/confused/
    // warn/whats-new）切到对应语言副本；其它子页面留在原页只换 lang 参数。
    code = canon(code) || DEFAULT_LANG;
    var params = new URLSearchParams(location.search);
    params.delete('lang');
    var m = relPath().match(/(?:^|\/)(index\.html|about\.html|confused\.html|whats-new\.html|warn\.html)$/);
    var qs = params.toString();
    if(m){
      return ROOT + (LANG_PATH[code] || '') + m[1]
        + (qs ? '?' + qs : '') + (location.hash || '');
    }
    var landing = /(\/|index\.html)$/.test(location.pathname);
    var path;
    if(landing){ path = ROOT + (LANG_PATH[code] || ''); }
    else { params.set('lang', code); path = location.pathname; qs = params.toString(); }
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
    (OUT / "assets" / "bilingual.js").write_text(BILINGUAL_JS, encoding="utf-8")
    t2s = _load_zh_hant_t2s()
    print(f"i18n t2s    : {len(t2s):,} chars (zh-Hant input normalization)", flush=True)
    (OUT / "assets" / "app.js").write_text(
        APP_JS.replace("REPORT_REPO_PLACEHOLDER", REPORT_REPO)
        .replace("__T2S_JSON__", json.dumps(t2s, ensure_ascii=False, separators=(",", ":")))
        .replace("data/idx/core.json", f"data/idx/core.json?v={int(time.time())}")
        .replace("data/idx/pinyin.json", f"data/idx/pinyin.json?v={int(time.time())}")
        .replace("data/idx/manifest.json", f"data/idx/manifest.json?v={int(time.time())}"),
        encoding="utf-8")

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    tr_counts = build_terms_json(db)
    print(f"bilingual   : {tr_counts.get('zh', 0)} zh / {tr_counts.get('es', 0)} es "
          f"display-default ingredient translations", flush=True)
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
    _values = _i18n_placeholders(stats, atc_cov, coverage, source_cover)
    _merge_static_i18n(_values)
    _install_zh_hant(_values)
    (OUT / "assets" / "i18n.js").write_text(_render_i18n_js(), encoding="utf-8")

    # v0.5.4：厂家页清单（必须在 load_index 之前载入，索引要用 mu/ml 字段）
    global MAKERS
    MAKERS = load_makers()
    print(f"maker list : {len(MAKERS):,} makers, "
          f"{sum(1 for v in MAKERS.values() if v['has']):,} with page "
          f"(>= {MAKER_MIN_PRODUCTS} products)", flush=True)

    print("building index ...", flush=True)
    entries = load_index(db)
    write_legacy_index = os.environ.get("WRITE_LEGACY_INDEX") == "1"
    if write_legacy_index:
        # v0.6.1 过渡开关：默认不再双写 data/index.json（dist -53 MB）。
        # 需要临时回滚线上旧客户端时：$env:WRITE_LEGACY_INDEX='1'; python site/build.py
        (OUT / "data" / "index.json").write_text(
            json.dumps(entries, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # P1：entries 写一份列式 + 字典编码核心（客户端 decodeCore 解码回 IDX，唯一真相源）。
    core = encode_core(entries)
    (OUT / "data" / "idx").mkdir(parents=True, exist_ok=True)
    (OUT / "data" / "idx" / "core.json").write_bytes(
        json.dumps(core, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if os.environ.get("WRITE_LEGACY_MINI") == "1":
        # 可选二级兜底（默认关）：核心损坏时客户端尝试 legacy-mini（<13.1 MB raw）。
        mini_cols = {k: v for k, v in core["cols"].items()
                     if k in {"k", "d", "dp", "c", "x", "s", "l", "n", "v", "u"}}
        mini = {"v": 1, "n": core["n"], "cols": mini_cols, "q": core["q"]}
        (OUT / "data" / "idx" / "legacy-mini.json").write_bytes(
            json.dumps(mini, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    print(f"  {len(entries)} keys", flush=True)
    legacy_txt = (f" (index.json legacy "
                  f"{(OUT / 'data' / 'index.json').stat().st_size / 1e6:.1f} MB)"
                  if write_legacy_index else " (legacy index.json: off)")
    print(f"  core.json  { (OUT / 'data' / 'idx' / 'core.json').stat().st_size / 1e6:.1f} MB"
          f"{legacy_txt}", flush=True)

    # P2 分片（task-36）：manifest + shard-*.json；客户端先拉 manifest，再按查询
    # 首字符/拼音首字母取 1-3 片；core.json 保留为完整回退。
    shards = encode_shards(entries)
    (OUT / "data" / "idx" / "manifest.json").write_bytes(
        json.dumps(shards, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    print(f"  manifest.json ({shards['shardCount']} shards, "
          f"{shards['shardBytes'] / 1e6:.1f} MB) "
          f"{(OUT / 'data' / 'idx' / 'manifest.json').stat().st_size / 1e3:.1f} KB", flush=True)

    # A1（v0.5.6）：产品明细桶由 etl/build_detail_buckets.py（index-perf task-58）
    # 预生成到 data/idx/；构建时原样复制到 OUT（懒加载，不进主索引/首屏）。
    # 桶内 key 集合 = 上一版 index.json 的 k 列表；DB/索引变更后需先重跑该脚本。
    detail_src = ROOT / "data" / "idx"
    detail_files = sorted(detail_src.glob("detail-*.json")) if detail_src.exists() else []
    detail_bytes = 0
    for p in detail_files:
        (OUT / "data" / "idx" / p.name).write_bytes(p.read_bytes())
        detail_bytes += p.stat().st_size
    if detail_files:
        print(f"  detail buckets {len(detail_files)} ({detail_bytes / 1e6:.1f} MB, "
              f"lazy-load on expand)", flush=True)
    else:
        print("  detail buckets 0 (A1 details disabled: data/idx/detail-*.json missing)",
              flush=True)

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
    n_drug = build_drug_pages(db, entries)
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
    print("building combo pages ...", flush=True)
    n_combo = build_combo_pages(entries, db)
    print("building maker pages ...", flush=True)
    n_maker = build_maker_pages(entries, db)
    build_index_page(entries, stats, coverage)
    n_conf = build_confused(db)
    n_warn = build_warn(db)
    build_about(stats, coverage, source_cover)
    build_whats_new()
    build_glossary()
    print("building atc pages ...", flush=True)
    n_atc = build_atc_pages(db)
    n_cat = build_category_pages(db)
    build_atc_index()
    build_categories_json(db)
    print("building 404 ...", flush=True)
    build_404()
    build_seo_files()

    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"\n== done ==")
    print(f"  drug pages : {n_drug}")
    print(f"  name pages : {n_name}")
    print(f"  combo pages: {n_combo}")
    print(f"  maker pages: {n_maker} (threshold >= {MAKER_MIN_PRODUCTS} products)")
    print(f"  confused   : {n_conf} pairs")
    print(f"  warnings   : {n_warn} published")
    print(f"  core.json  : {(OUT / 'data' / 'idx' / 'core.json').stat().st_size / 1e6:.1f} MB"
          f" (legacy index.json: {'on' if os.environ.get('WRITE_LEGACY_INDEX') == '1' else 'off'})")
    print(f"  total size : {size / 1e6:.1f} MB")
    print(f"  open       : {OUT / 'index.html'}")
    db.close()


if __name__ == "__main__":
    main()
