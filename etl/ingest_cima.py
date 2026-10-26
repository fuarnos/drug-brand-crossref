"""CIMA（西班牙，AEMPS）→ SQLite。

数据源：AEMPS 的 CIMA REST 接口，公开、无需账号。
    https://cima.aemps.es/cima/rest/medicamentos?pagina=N&tamanioPagina=100
    https://cima.aemps.es/cima/rest/medicamento?nregistro=NNNNN      （单条，含 ATC）

粒度：一个 nregistro = 一个西班牙注册号 = 我们的 L2 product（一行）。

字段对应
--------
nombre                            "A.A.S. 100 mg COMPRIMIDOS"（商品名+规格+剂型挤在一串里）
vtm                               Spanish INN，复方用 " + " 连接（"tramadol + paracetamol"）
dosis                             西班牙语写法，坑很多："600 mg/300 mg"、"5 mg/ml"、"20 mg/24 h"、
                                  "100.000 UI"、"600 - REVISAR mg"、"10 mg ezetimiba"、"-"、"Desconocida"
formaFarmaceuticaSimplificada     剂型（西班牙语）→ 翻译成英语再交给共享的 form_base_of()
estado                            {"aut": ts} / {"aut","rev"} / {"aut","susp"}；comerc 是「是否在市」
labtitular                        上市许可持有人

两个语言的坑，都在本文件里就地解决，不去动共享的 normalize_name：
1. 归一化器的剂型词表是英/中的，`COMPRIMIDOS`、`SOLUCIÓN` 会活下来污染名字键 → 本文件先剥。
2. 归一化器不认识 "UI"（西语 unidades internacionales）→ "100 UI" 会剩下裸数字 → 本文件丢掉纯数字 token。

跨语言对齐（本文件的核心）
--------------------------
substance_id 沿用美/英两库已经在用的英文 id（aspirin / acetaminophen / omeprazole ...），
否则西班牙会变成一座孤岛，身份卡上永远只有一行 ES。映射三层：
    1. ALIASES 静态表（高频 ~250 个，人工核对过；值可以是候选元组，取库里已存在的那个）
    2. 去重音后 slug 直接命中（tacrolimus 这类同形词）
    3. 后缀规则（-prazol→prazole、-statina→statin、-ina→ine/in ...），只在目标 id 已存在时接受
三层都不中 → 用西语 slug 造一个新 substance（这类会在末尾报告，是后续人工补表的输入）。
无论如何，西语原文都会作为 name_variant 挂在名字键上，所以西语查询两条路都能走通。

ATC
---
列表接口不返回 ATC；只有单条接口 `medicamento?nregistro=` 的 `atcs[]` 里有（nivel 5 是完整码）。
逐条拉 2.5 万次不现实（实测 ~0.8 s/请求），所以按 VTM 取一个代表产品（该 VTM 下最常见的
(dosis, forma)，同票取最小注册号）拉一次，缓存在 data/raw/cima/atc/ 下，重跑离线。
ATC 归于 substance；只对单方 VTM 取，复方产品的 ATC 是「组合码」，不能算到某个成分头上。
因此同一成分若有多个适应症（阿司匹林 100 mg 抗血小板 B01AC06 vs 500 mg 镇痛 N02BA01），
库里只留代表产品那一个 —— schema 的 substance.atc 只有一个字段，这是已知的折损。

用法：
    python etl/ingest_cima.py              # 全量（首次会下载 128 页 + ~1800 条 ATC 详情）
    python etl/ingest_cima.py --no-atc     # 跳过 ATC 补全（离线/求快）
    python etl/ingest_cima.py --limit 200  # 只跑前 200 条，验证用
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import permutations
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from ingest_openfda_ndc import form_base_of, slug  # noqa: E402
from normalize_name import normalize  # noqa: E402

CACHE = ROOT / "data" / "raw" / "cima"
ATC_CACHE = CACHE / "atc"
DB = ROOT / "data" / "drugs.db"
SCHEMA = ROOT / "db" / "schema.sql"
SOURCE_ID = "cima"
TODAY = date.today().isoformat()
UA = "drug-brand-crossref/0.2 (public-data research)"
LIST_URL = "https://cima.aemps.es/cima/rest/medicamentos?pagina={page}&tamanioPagina=100"
DETAIL_URL = "https://cima.aemps.es/cima/rest/medicamento?nregistro={nreg}"
PUBLIC_URL = "https://cima.aemps.es/cima/publico/detalle.html?nregistro={nreg}"
POLITE_SLEEP = 0.25
ATC_WORKERS = 4


def _deaccent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


# --- 西班牙语 INN → 本库已有的英文 substance_id ------------------------------
# 只写高频、确定能对上的。值是候选元组时取库里已存在的第一个（英美两库拼写不同时用得上）。
_ES_INN_RAW = {
    # 解热镇痛 / 抗炎 / 麻醉
    "ácido acetilsalicílico": "aspirin",
    "paracetamol": "acetaminophen",
    "metamizol": "metamizole",
    "ibuprofeno": "ibuprofen",
    "naproxeno": "naproxen",
    "diclofenaco": "diclofenac",
    "dexketoprofeno": "dexketoprofen",
    "ketoprofeno": "ketoprofen",
    "ketorolaco": "ketorolac",
    "aceclofenaco": "aceclofenac",
    "celecoxib": "celecoxib",
    "etoricoxib": "etoricoxib",
    "meloxicam": "meloxicam",
    "piroxicam": "piroxicam",
    "indometacina": "indomethacin",
    "codeína": "codeine",
    "tramadol": "tramadol",
    "tapentadol": "tapentadol",
    "morfina": "morphine",
    "oxicodona": "oxycodone",
    "hidromorfona": "hydromorphone",
    "fentanilo": "fentanyl",
    "remifentanilo": "remifentanil",
    "buprenorfina": "buprenorphine",
    "metadona": "methadone",
    "naloxona": "naloxone",
    "naltrexona": "naltrexone",
    "lidocaína": "lidocaine",
    "bupivacaína": "bupivacaine",
    "ropivacaína": "ropivacaine",
    "prilocaína": "prilocaine",
    "propofol": "propofol",
    "ketamina": "ketamine",
    "midazolam": "midazolam",
    "sugammadex": "sugammadex",
    "colchicina": "colchicine",
    "alopurinol": "allopurinol",
    "febuxostat": "febuxostat",
    # 激素 / 抗过敏
    "prednisona": "prednisone",
    "prednisolona": "prednisolone",
    "metilprednisolona": "methylprednisolone",
    "dexametasona": "dexamethasone",
    "betametasona": "betamethasone",
    "hidrocortisona": "hydrocortisone",
    "deflazacort": "deflazacort",
    "budesonida": "budesonide",
    "beclometasona": "beclomethasone",
    "fluticasona": "fluticasone",
    "mometasona": "mometasone",
    "loratadina": "loratadine",
    "desloratadina": "desloratadine",
    "cetirizina": "cetirizine",
    "levocetirizina": "levocetirizine",
    "ebastina": "ebastine",
    "bilastina": "bilastine",
    "fexofenadina": "fexofenadine",
    "hidroxizina": "hydroxyzine",
    "clorfenamina": "chlorpheniramine",
    "dexclorfeniramina": "dexchlorpheniramine",
    "difenhidramina": "diphenhydramine",
    "prometazina": "promethazine",
    "pseudoefedrina": "pseudoephedrine",
    "fenilefrina": "phenylephrine",
    # 心血管
    "enalapril": "enalapril",
    "lisinopril": "lisinopril",
    "ramipril": "ramipril",
    "captopril": "captopril",
    "perindopril": ("perindopril", "perindopril arginine"),
    "losartán": "losartan",
    "valsartán": "valsartan",
    "irbesartán": "irbesartan",
    "candesartán": "candesartan",
    "telmisartán": "telmisartan",
    "olmesartán": "olmesartan",
    "sacubitrilo": "sacubitril",
    "amlodipino": "amlodipine",
    "nifedipino": "nifedipine",
    "lercanidipino": "lercanidipine",
    "felodipino": "felodipine",
    "diltiazem": "diltiazem",
    "verapamilo": "verapamil",
    "bisoprolol": "bisoprolol",
    "carvedilol": "carvedilol",
    "metoprolol": "metoprolol",
    "propranolol": "propranolol",
    "atenolol": "atenolol",
    "nebivolol": "nebivolol",
    "hidroclorotiazida": "hydrochlorothiazide",
    "indapamida": "indapamide",
    "furosemida": "furosemide",
    "torasemida": "torasemide",
    "espironolactona": "spironolactone",
    "eplerenona": "eplerenone",
    "digoxina": "digoxin",
    "amiodarona": "amiodarone",
    "ivabradina": "ivabradine",
    "ranolazina": "ranolazine",
    "nitroglicerina": "nitroglycerin",
    "atorvastatina": "atorvastatin",
    "simvastatina": "simvastatin",
    "rosuvastatina": "rosuvastatin",
    "pravastatina": "pravastatin",
    "pitavastatina": "pitavastatin",
    "ezetimiba": "ezetimibe",
    "clopidogrel": "clopidogrel",
    "prasugrel": "prasugrel",
    "ticagrelor": "ticagrelor",
    "acenocumarol": "acenocoumarol",
    "warfarina": "warfarin",
    "enoxaparina": "enoxaparin",
    "bemiparina": "bemiparin",
    "tinzaparina": "tinzaparin",
    "heparina": "heparin",
    "apixabán": "apixaban",
    "rivaroxabán": "rivaroxaban",
    "dabigatrán": ("dabigatran", "dabigatran etexilate"),
    "edoxabán": "edoxaban",
    "ácido tranexámico": "tranexamic acid",
    "doxazosina": "doxazosin",
    "tamsulosina": "tamsulosin",
    "finasterida": "finasteride",
    "dutasterida": "dutasteride",
    "silodosina": "silodosin",
    "sildenafilo": "sildenafil",
    "tadalafilo": "tadalafil",
    "vardenafilo": "vardenafil",
    "bosentán": "bosentan",
    "ambrisentán": "ambrisentan",
    "selexipag": "selexipag",
    "riociguat": "riociguat",
    # 糖尿病
    "metformina": "metformin",
    "gliclazida": "gliclazide",
    "glimepirida": "glimepiride",
    "glibenclamida": ("glyburide", "glibenclamide"),
    "repaglinida": "repaglinide",
    "pioglitazona": "pioglitazone",
    "sitagliptina": "sitagliptin",
    "linagliptina": "linagliptin",
    "saxagliptina": "saxagliptin",
    "vildagliptina": "vildagliptin",
    "empagliflozina": "empagliflozin",
    "dapagliflozina": "dapagliflozin",
    "canagliflozina": "canagliflozin",
    "liraglutida": "liraglutide",
    "semaglutida": "semaglutide",
    "dulaglutida": "dulaglutide",
    "exenatida": "exenatide",
    "insulina glargina": "insulin glargine",
    "insulina aspart": "insulin aspart",
    "insulina lispro": "insulin lispro",
    "insulina detemir": "insulin detemir",
    "insulina degludec": "insulin degludec",
    "insulina": ("insulin", "insulin human"),
    "glucagón": "glucagon",
    "glucosa": "glucose",
    # 抗感染
    "amoxicilina": "amoxicillin",
    "ácido clavulánico": "clavulanate",
    "ampicilina": "ampicillin",
    "bencilpenicilina": "penicillin g",
    "fenoximetilpenicilina": "penicillin v",
    "flucloxacilina": "flucloxacillin",
    "cloxacilina": "cloxacillin",
    "cefalexina": "cephalexin",
    "cefuroxima": "cefuroxime",
    "cefixima": "cefixime",
    "ceftriaxona": "ceftriaxone",
    "cefotaxima": "cefotaxime",
    "ceftazidima": "ceftazidime",
    "meropenem": "meropenem",
    "ertapenem": "ertapenem",
    "azitromicina": "azithromycin",
    "claritromicina": "clarithromycin",
    "eritromicina": "erythromycin",
    "doxiciclina": "doxycycline",
    "minociclina": "minocycline",
    "tetraciclina": "tetracycline",
    "ciprofloxacino": "ciprofloxacin",
    "levofloxacino": "levofloxacin",
    "moxifloxacino": "moxifloxacin",
    "norfloxacino": "norfloxacin",
    "metronidazol": "metronidazole",
    "tinidazol": "tinidazole",
    "trimetoprima": "trimethoprim",
    "sulfametoxazol": "sulfamethoxazole",
    "nitrofurantoina": "nitrofurantoin",
    "fosfomicina": "fosfomycin",
    "vancomicina": "vancomycin",
    "teicoplanina": "teicoplanin",
    "gentamicina": "gentamicin",
    "tobramicina": "tobramycin",
    "amikacina": "amikacin",
    "clindamicina": "clindamycin",
    "linezolid": "linezolid",
    "daptomicina": "daptomycin",
    "rifampicina": "rifampin",
    "isoniazida": "isoniazid",
    "pirazinamida": "pyrazinamide",
    "etambutol": "ethambutol",
    "fluconazol": "fluconazole",
    "itraconazol": "itraconazole",
    "voriconazol": "voriconazole",
    "posaconazol": "posaconazole",
    "anfotericina": ("amphotericin", "amphotericin b"),
    "caspofungina": "caspofungin",
    "aciclovir": "acyclovir",
    "valaciclovir": "valacyclovir",
    "famciclovir": "famciclovir",
    "ganciclovir": "ganciclovir",
    "valganciclovir": "valganciclovir",
    "oseltamivir": "oseltamivir",
    "zanamivir": "zanamivir",
    "ribavirina": "ribavirin",
    "tenofovir": ("tenofovir", "tenofovir disoproxil"),
    "emtricitabina": "emtricitabine",
    "abacavir": "abacavir",
    "lamivudina": "lamivudine",
    "dolutegravir": "dolutegravir",
    "raltegravir": "raltegravir",
    "efavirenz": "efavirenz",
    "nevirapina": "nevirapine",
    "ritonavir": "ritonavir",
    "lopinavir": "lopinavir",
    "atazanavir": "atazanavir",
    "darunavir": "darunavir",
    "sofosbuvir": "sofosbuvir",
    "ledipasvir": "ledipasvir",
    "daclatasvir": "daclatasvir",
    "velpatasvir": "velpatasvir",
    "entecavir": "entecavir",
    "hidroxicloroquina": "hydroxychloroquine",
    "cloroquina": "chloroquine",
    "mefloquina": "mefloquine",
    "atovacuona": "atovaquone",
    "proguanil": "proguanil",
    "ivermectina": "ivermectin",
    "albendazol": "albendazole",
    "mebendazol": "mebendazole",
    "prazicuantel": "praziquantel",
    "permetrina": "permethrin",
    # 消化
    "omeprazol": "omeprazole",
    "pantoprazol": "pantoprazole",
    "esomeprazol": "esomeprazole",
    "lansoprazol": "lansoprazole",
    "rabeprazol": "rabeprazole",
    "ranitidina": "ranitidine",
    "famotidina": "famotidine",
    "domperidona": "domperidone",
    "metoclopramida": "metoclopramide",
    "ondansetrón": "ondansetron",
    "granisetrón": "granisetron",
    "loperamida": "loperamide",
    "lactulosa": "lactulose",
    "macrogol": ("macrogol", "macrogol 3350"),
    "bisacodilo": "bisacodyl",
    "senósidos": "senna",
    "ácido ursodesoxicólico": "ursodeoxycholic acid",
    "mesalazina": "mesalamine",
    "sulfasalazina": "sulfasalazine",
    "sucralfato": "sucralfate",
    "simeticona": ("simethicone", "simeticone"),
    "dimetilfumarato": "dimethyl fumarate",
    "acetilcisteína": "acetylcysteine",
    # 精神 / 神经
    "sertralina": "sertraline",
    "fluoxetina": "fluoxetine",
    "paroxetina": "paroxetine",
    "citalopram": "citalopram",
    "escitalopram": "escitalopram",
    "venlafaxina": "venlafaxine",
    "duloxetina": "duloxetine",
    "vortioxetina": "vortioxetine",
    "mirtazapina": "mirtazapine",
    "trazodona": "trazodone",
    "amitriptilina": "amitriptyline",
    "clomipramina": "clomipramine",
    "quetiapina": "quetiapine",
    "olanzapina": "olanzapine",
    "risperidona": "risperidone",
    "aripiprazol": "aripiprazole",
    "paliperidona": "paliperidone",
    "ziprasidona": "ziprasidone",
    "lurasidona": "lurasidone",
    "haloperidol": "haloperidol",
    "clozapina": "clozapine",
    "diazepam": "diazepam",
    "lorazepam": "lorazepam",
    "lormetazepam": "lormetazepam",
    "alprazolam": "alprazolam",
    "clonazepam": "clonazepam",
    "bromazepam": "bromazepam",
    "zolpidem": "zolpidem",
    "zopiclona": "zopiclone",
    "ácido valproico": "valproic acid",
    "valproato": "valproate",
    "carbamazepina": "carbamazepine",
    "oxcarbazepina": "oxcarbazepine",
    "eslicarbazepina": "eslicarbazepine",
    "lamotrigina": "lamotrigine",
    "levetiracetam": "levetiracetam",
    "brivaracetam": "brivaracetam",
    "lacosamida": "lacosamide",
    "zonisamida": "zonisamide",
    "perampanel": "perampanel",
    "fenitoína": "phenytoin",
    "gabapentina": "gabapentin",
    "pregabalina": "pregabalin",
    "topiramato": "topiramate",
    "sumatriptán": "sumatriptan",
    "zolmitriptán": "zolmitriptan",
    "rizatriptán": "rizatriptan",
    "eletriptán": "eletriptan",
    "donepezilo": "donepezil",
    "rivastigmina": "rivastigmine",
    "galantamina": "galantamine",
    "memantina": "memantine",
    "levodopa": "levodopa",
    "carbidopa": "carbidopa",
    "benserazida": "benserazide",
    "entacapona": "entacapone",
    "pramipexol": "pramipexole",
    "ropinirol": "ropinirole",
    "rotigotina": "rotigotine",
    "rasagilina": "rasagiline",
    "selegilina": "selegiline",
    "metilfenidato": "methylphenidate",
    "atomoxetina": "atomoxetine",
    "vareniclina": "varenicline",
    "bupropión": "bupropion",
    "nicotina": "nicotine",
    "melatonina": "melatonin",
    "betahistina": "betahistine",
    # 呼吸
    "salbutamol": "albuterol",
    "terbutalina": "terbutaline",
    "formoterol": "formoterol",
    "salmeterol": "salmeterol",
    "indacaterol": "indacaterol",
    "tiotropio": "tiotropium",
    "ipratropio": "ipratropium",
    "montelukast": "montelukast",
    "teofilina": "theophylline",
    "roflumilast": "roflumilast",
    "omalizumab": "omalizumab",
    "oxígeno": "oxygen",
    # 骨 / 维生素
    "colecalciferol": "cholecalciferol",
    "calcitriol": "calcitriol",
    "alendronato": "alendronate",
    "ácido alendrónico": "alendronate",
    "risedronato": "risedronate",
    "ácido risedrónico": "risedronate",
    "ibandronato": "ibandronate",
    "ácido ibandrónico": "ibandronate",
    "ácido zoledrónico": "zoledronic acid",
    "denosumab": "denosumab",
    "calcio carbonato": "calcium carbonate",
    "ácido fólico": "folic acid",
    "cianocobalamina": "cyanocobalamin",
    "tiamina": "thiamine",
    "piridoxina": "pyridoxine",
    "ácido ascórbico": "ascorbic acid",
    # 免疫 / 肿瘤 / 生物制品
    "metotrexato": "methotrexate",
    "azatioprina": "azathioprine",
    "leflunomida": "leflunomide",
    "ciclosporina": "cyclosporine",
    "tacrolimus": "tacrolimus",
    "sirolimus": "sirolimus",
    "everolimus": "everolimus",
    "micofenolato": "mycophenolate",
    "adalimumab": "adalimumab",
    "etanercept": "etanercept",
    "infliximab": "infliximab",
    "ustekinumab": "ustekinumab",
    "rituximab": "rituximab",
    "trastuzumab": "trastuzumab",
    "bevacizumab": "bevacizumab",
    "nivolumab": "nivolumab",
    "pembrolizumab": "pembrolizumab",
    "imatinib": "imatinib",
    "dasatinib": "dasatinib",
    "sunitinib": "sunitinib",
    "erlotinib": "erlotinib",
    "lenalidomida": "lenalidomide",
    "pomalidomida": "pomalidomide",
    "bortezomib": "bortezomib",
    "temozolomida": "temozolomide",
    "capecitabina": "capecitabine",
    "pemetrexed": "pemetrexed",
    "abiraterona": "abiraterone",
    "bicalutamida": "bicalutamide",
    "tamoxifeno": "tamoxifen",
    "letrozol": "letrozole",
    "anastrozol": "anastrozole",
    "exemestano": "exemestane",
    "filgrastim": "filgrastim",
    "darbepoetina": ("darbepoetin alfa", "darbepoetin"),
    "somatropina": "somatropin",
    "deferasirox": "deferasirox",
    "cinacalcet": "cinacalcet",
    "eltrombopag": "eltrombopag",
    "tolvaptán": "tolvaptan",
    "fingolimod": "fingolimod",
    "pirfenidona": "pirfenidone",
    "nintedanib": "nintedanib",
    "apremilast": "apremilast",
    # 眼科 / 皮肤 / 泌尿 / 其他
    "latanoprost": "latanoprost",
    "solifenacina": "solifenacin",
    "tolterodina": "tolterodine",
    "oxibutinina": "oxybutynin",
    "mirabegron": "mirabegron",
    "clotrimazol": "clotrimazole",
    "miconazol": "miconazole",
    "ketoconazol": "ketoconazole",
    "terbinafina": "terbinafine",
    "ácido fusídico": "fusidic acid",
    "mupirocina": "mupirocin",
    "peróxido de benzoilo": "benzoyl peroxide",
    "adapaleno": "adapalene",
    "isotretinoína": "isotretinoin",
    "tretinoína": "tretinoin",
    "ácido salicílico": "salicylic acid",
    "clorhexidina": "chlorhexidine",
    "glicerol": "glycerol",
    "levonorgestrel": "levonorgestrel",
    "etinilestradiol": "ethinyl estradiol",
    "estradiol": "estradiol",
    "progesterona": "progesterone",
    "didrogesterona": "dydrogesterone",
    "drospirenona": "drospirenone",
    "desogestrel": "desogestrel",
    "gestodeno": "gestodene",
    "testosterona": "testosterone",
    "oxitocina": "oxytocin",
    "dextrometorfano": "dextromethorphan",
    "oximetazolina": "oxymetazoline",
    "xilometazolina": "xylometazoline",
}

# 补充：高频但上面没写到的（先按西语名直出的那些，补上能一次对齐一批）
_ES_INN_EXTRA = {
    "levotiroxina": "levothyroxine",
    "levotiroxina sodica": "levothyroxine",
    "oxigeno gaseoso": "oxygen",
    "sodio cloruro": "sodium chloride",
    "sodio bicarbonato": "sodium bicarbonate",
    "amisulprida": "amisulpride",
    "manidipino": "manidipine",
    "teriflunomida": "teriflunomide",
    "folitropina alfa": "follitropin alfa",
    "povidona iodada": "povidone iodine",
    "flurbiprofeno": "flurbiprofen",
    "sevelamero": "sevelamer",
    "desmopresina": "desmopressin",
    "bencidamina": "benzydamine",
    "tirzepatida": "tirzepatide",
    "octreotida": "octreotide",
    "lisdexanfetamina": "lisdexamfetamine",
    "doxilamina": "doxylamine",
    "teriparatida": "teriparatide",
    "cefepima": "cefepime",
    "baclofeno": "baclofen",
    "raloxifeno": "raloxifene",
    "apomorfina": "apomorphine",
    "oxido nitrico": "nitric oxide",
    "albumina": ("albumin human", "albumin"),
    "insulina isofana": ("insulin isophane human", "insulin isophane"),
    "epoetina alfa": "epoetin alfa",
    "epoetina beta": "epoetin beta",
    "epoetina zeta": "epoetin zeta",
    "darbepoetina alfa": "darbepoetin alfa",
    "citicolina": "citicoline",
    "metamizol sodico": "metamizole",
    "espironolactona": "spironolactone",
    "levosimendan": "levosimendan",
    "tirofiban": "tirofiban",
    "eptifibatida": "eptifibatide",
    "landiolol": "landiolol",
    "remifentanilo": "remifentanil",
    "dexmedetomidina": "dexmedetomidine",
    "sugammadex": "sugammadex",
    "eritropoyetina": "epoetin",
    "epinefrina": "epinephrine",
    "norepinefrina": "norepinephrine",
    "bromacepam": "bromazepam",
    "ciclofosfamida": "cyclophosphamide",
    "cisatracurio": "cisatracurium",
    "icatibanto": "icatibant",
    "lanreotida": "lanreotide",
    "tiotepa": "thiotepa",
    "ketotifeno": "ketotifen",
    "oxaliplatino": "oxaliplatin",
    "dimenhidrinato": "dimenhydrinate",
    "efedrina": "ephedrine",
    "acido ursodeoxicolico": "ursodeoxycholic acid",
    "insulina regular": "insulin human",
    "insulina isofana bifasica": "insulin isophane biphasic human",
    "epoetina dseta": "epoetin zeta",
    "colistimetato": "colistimethate",
    "condroitin sulfato": "chondroitin sulfate",
    "menotropina": "menotropin",
    "nitisinona": "nitisinone",
    "carmelosa": "carmellose",
    "metotrexato sodico": "methotrexate",
    "acido folinico": "folinic acid",
    "fitomenadiona": "phytonadione",
    "vitamina k": "phytonadione",
    "vitamina d3": "cholecalciferol",
    "vitamina b12": "cyanocobalamin",
    "hierro sacarosa": "iron sucrose",
    "sulfato ferroso": "ferrous sulfate",
    "gluconato ferroso": "ferrous gluconate",
    "penicilina g": "penicillin g",
    "bromuro ipratropio": "ipratropium",
    "insulina asparta": "insulin aspart",
    "ofloxacino": "ofloxacin",
    "melfalan": "melphalan",
    "anagrelida": "anagrelide",
    "bromfenaco": "bromfenac",
    "fluocinolona": "fluocinolone acetonide",
    "acido gadoterico": "gadoteric acid",
    "barnidipino": "barnidipine",
    "cloperastina": "cloperastine",
    "cinitaprida": "cinitapride",
    "almagato": "almagate",
    "dimetindeno": "dimetindene",
    "tetrizolina": "tetryzoline",
    "triflusal": "triflusal",
    "condroitin sulfato": "chondroitin sulfate",
    "glucosamina": "glucosamine",
    "sulfato de condroitina": "chondroitin sulfate",
    "acido hialuronico": "hyaluronic acid",
    "hialuronidasa": "hyaluronidase",
    "lidocaina": "lidocaine",
    "prilocaina": "prilocaine",
    "cafeina": "caffeine",
    "potasio cloruro": "potassium chloride",
    "piperacilina": "piperacillin",
    "glicopirronio": "glycopyrronium",
    "bromuro de glicopirronio": "glycopyrronium",
    "cloruro potasico": "potassium chloride",
    "cloruro sodico": "sodium chloride",
    "bicarbonato sodico": "sodium bicarbonate",
}
_ES_INN_RAW.update(_ES_INN_EXTRA)

# 键统一成「去重音 + 小写」，值统一成 slug（表里写的是英文 INN 名，不是 id）
ALIASES: dict[str, tuple[str, ...]] = {}
for _k, _v in _ES_INN_RAW.items():
    _vals = (_v,) if isinstance(_v, str) else tuple(_v)
    ALIASES[_deaccent(_k).lower().strip()] = tuple(slug(v) for v in _vals)

# 西语盐型/水合物后缀：去掉后才能和英文 base 对上（enoxaparina sodio → enoxaparin）
ES_SALTS = {
    "sodio", "sodico", "sódico", "sodica", "sódica", "potasio", "potasico", "potásico",
    "calcico", "cálcico", "calcio", "magnesio", "magnesico", "magnésico", "hidrocloruro",
    "clorhidrato", "dihidrato", "hidrato", "monohidrato", "trihidrato", "anhidro",
    "mesilato", "besilato", "tosilato", "maleato", "tartrato", "succinato", "fumarato",
    "citrato", "sulfato", "fosfato", "nitrato", "acetato", "bromuro", "cloruro", "ioduro",
    "lactato", "gluconato", "aspartato", "trometamina", "trometamol", "meglumina",
    "mofetilo", "propionato", "valerato", "decanoato", "enantato", "cipionato", "pamoato",
    "embonato", "estearato", "palmitato", "benzoato", "furoato", "xinafoato", "aceponato",
    "buteprato", "sacarato", "sal", "sales", "complejo",
}

# 后缀变换候选（都必须在库里已存在才接受，猜错不会造垃圾）
ES_SUFFIX_RULES = (
    ("prazol", ("prazole",)),
    ("statina", ("statin",)),
    ("sartan", ("sartan",)),
    ("ciclina", ("cycline",)),
    ("micina", ("mycin",)),
    ("penicilina", ("penicillin",)),
    ("azepina", ("azepine",)),
    ("azepam", ("azepam",)),
    ("azina", ("azine",)),
    ("idina", ("idine",)),
    ("onida", ("onide",)),
    ("amida", ("amide",)),
    ("nida", ("nide",)),
    ("ina", ("ine", "in")),
    ("ol", ("ole", "ol")),
    ("ano", ("ane", "an")),
    ("ato", ("ate", "at")),
    ("ilo", ("il",)),
    ("ico", ("ic",)),
    ("osa", ("ose",)),
)

# --- 西班牙语剂型词：建名字键之前必须剥掉（共享归一化器只认英/中） -----------
ES_FORM_WORDS = {
    "comprimido", "comprimidos", "comp", "comps", "tableta", "tabletas", "pastilla",
    "pastillas", "gragea", "grageas", "capsula", "capsulas", "cápsula", "cápsulas", "cap",
    "caps", "polvo", "polvos", "granulado", "granulados", "sobre", "sobres", "sobrecito",
    "ampolla", "ampollas", "vial", "viales", "jeringa", "jeringas", "pluma", "plumas",
    "cartucho", "cartuchos", "bolsa", "bolsas", "frasco", "frascos", "tubo", "tubos",
    "pomo", "gotas", "gotero", "aplicador", "parche", "parches", "sistema", "sistemas",
    "dispositivo", "dispositivos", "implante", "implantes", "anillo", "anillos", "ovulo",
    "ovulos", "óvulo", "óvulos", "supositorio", "supositorios", "crema", "cremas",
    "pomada", "pomadas", "gel", "geles", "locion", "lociones", "loción", "champu",
    "champú", "espuma", "emulsion", "emulsión", "emulsiones", "suspension", "suspensión",
    "suspensiones", "solucion", "solución", "soluciones", "jarabe", "jarabes", "elixir",
    "concentrado", "concentrada", "inyectable", "inyectables", "inyeccion", "inyección",
    "inyecciones", "infusion", "infusión", "infusiones", "perfusion", "perfusión",
    "perfusiones", "inhalacion", "inhalación", "inhalaciones", "inhalador", "inhaladores",
    "nebulizador", "nebulizadores", "aerosol", "aerosoles", "pulverizacion",
    "pulverización", "pulverizador", "colirio", "colirios", "bucodispersable",
    "bucodispersables", "liofilizado", "liofilizados", "efervescente", "efervescentes",
    "masticable", "masticables", "sublingual", "sublinguales", "vaginal", "vaginales",
    "rectal", "rectales", "nasal", "nasales", "otico", "ótico", "otica", "ótica",
    "oticos", "oftalmico", "oftálmico", "oftalmica", "oftálmica", "cutaneo", "cutáneo",
    "cutanea", "cutánea", "transdermico", "transdérmico", "transdermica", "transdérmica",
    "oral", "orales", "orodispersable", "dispersable", "gastrorresistente",
    "gastrorresistentes", "recubierto", "recubiertos", "recubierta", "recubiertas",
    "pelicula", "película", "peliculas", "películas", "liberacion", "liberación",
    "prolongada", "prolongado", "modificada", "modificado", "retardada", "retard",
    "inmediata", "sostenida", "unidosis", "monodosis", "multidosis", "dosis",
    "pediatrico", "pediátrico", "pediatrica", "pediátrica", "bucal", "esofagico",
    "esofágico", "topico", "tópico", "topica", "tópica", "uso", "via", "vía", "vias",
    "vías", "parenteral", "intravenoso", "intramuscular", "subcutaneo", "subcutáneo",
    "efg", "disolvente", "disolventes", "diluyente", "conjunto", "kit",
    "duras", "duros", "dura", "blandas", "blandos", "blanda", "rigidas", "rígidas",
    "dispersion", "dispersión", "adulto", "adultos", "infantil", "neonatal",
    "lp", "mr", "xr", "sr", "dr", "er", "gaseoso", "gaseosa", "iv", "im", "sc",
    # 西语单位（normalize_name 的强度表只认 mg/mcg/g/ml/iu/% 里的英文写法）
    "mg", "mcg", "g", "kg", "ml", "cl", "dl", "l", "ui", "iu", "u", "meq", "mmol", "%",
    "microgramos", "microgramo", "miligramos", "miligramo", "gramos", "gramo",
    "mililitros", "mililitro", "unidades", "unidad", "puff", "puffs",
    # 西语虚词：不剥掉会把 "COMPRIMIDOS DE LIBERACION PROLONGADA" 的尾巴留在名字键里
    "de", "del", "con", "para", "en", "y", "e", "o", "la", "el", "los", "las",
    "un", "una", "al", "por",
}

# 剂型词 → 英文，翻译后再交给共享的 form_base_of()
FORM_ES_EN = {
    "comprimido": "tablet", "comprimidos": "tablet", "tableta": "tablet",
    "tabletas": "tablet", "gragea": "tablet", "grageas": "tablet", "pastilla": "tablet",
    "capsula": "capsule", "capsulas": "capsule", "cápsula": "capsule", "cápsulas": "capsule",
    "polvo": "powder", "polvos": "powder", "granulado": "granules", "granulados": "granules",
    "sobre": "sachet", "sobres": "sachet", "solucion": "solution", "solución": "solution",
    "soluciones": "solution", "suspension": "suspension", "suspensión": "suspension",
    "suspensiones": "suspension", "emulsion": "emulsion", "emulsión": "emulsion",
    "jarabe": "syrup", "elixir": "elixir", "inyectable": "injection",
    "inyectables": "injection", "inyeccion": "injection", "inyección": "injection",
    "infusion": "infusion", "infusión": "infusion", "perfusion": "infusion",
    "perfusión": "infusion", "concentrado": "concentrate", "concentrada": "concentrate",
    "inhalacion": "inhalation", "inhalación": "inhalation", "inhalador": "inhaler",
    "aerosol": "aerosol", "nebulizador": "nebulizer", "colirio": "eye drops",
    "colirios": "eye drops", "pomada": "ointment", "crema": "cream", "cremas": "cream",
    "gel": "gel", "geles": "gel", "locion": "lotion", "loción": "lotion",
    "champu": "shampoo", "champú": "shampoo", "espuma": "foam", "parche": "patch",
    "parches": "patch", "supositorio": "suppository", "supositorios": "suppository",
    "ovulo": "pessary", "ovulos": "pessary", "óvulo": "pessary", "óvulos": "pessary",
    "liquido": "liquid", "líquido": "liquid", "gotas": "drops",
    "bucodispersable": "orodispersible", "liofilizado": "lyophilisate",
    "efervescente": "effervescent", "masticable": "chewable", "sublingual": "sublingual",
    "vaginal": "vaginal", "rectal": "rectal", "nasal": "nasal", "otico": "ear drops",
    "ótico": "ear drops", "oftalmico": "eye drops", "oftálmico": "eye drops",
    "topico": "topical", "tópico": "topical", "transdermico": "transdermal",
    "transdérmico": "transdermal", "oral": "oral", "orales": "oral",
    "gastrorresistente": "gastro-resistant", "liberacion": "release",
    "liberación": "release", "prolongada": "prolonged", "prolongado": "prolonged",
    "modificada": "modified", "modificado": "modified", "retardada": "retarded",
    "retard": "retarded",
}

# 剂型串里出现这些就说明释放机制不是速释
_RE_RELEASE = (
    ("DR", ("gastrorresistente", "gastro resistente", "enterico", "entérico")),
    ("ER", ("prolongada", "prolongado", "retardada", "retard", "liberacion prolongada")),
    ("MR", ("modificada", "modificado", "liberacion modificada")),
)

_RE_NUM = r"\d+(?:[.,]\d+)?"
_RE_THOUSANDS = re.compile(r"(\d)[.](\d{3})(?!\d)")
_RE_QTY = re.compile(
    r"(?P<val>" + _RE_NUM + r")\s*"
    r"(?P<unit>mg|mcg|ug|µg|μg|g|kg|ui|iu|u|%|ml|cl|dl|l|h|d[ií]a|dosis|"
    r"comprimidos?|sobres?|ampollas?|viales?|pulsaciones?|aplicaciones?|"
    r"microgramos?|miligramos?|gramos?|unidades?|mililitros?)(?!\w)",
    re.IGNORECASE,
)
# 只有分母、没有数字的写法："5 mg/ml"、"20 mg/comprimido"
_RE_BARE_DENOM = re.compile(
    r"^(ml|cl|dl|l|h|d[ií]a|dosis|comprimidos?|sobres?|ampollas?|viales?|"
    r"pulsaciones?|aplicaciones?|mililitros?)$", re.IGNORECASE)
_UNIT_MAP = {
    "mg": "mg", "mcg": "mcg", "ug": "mcg", "µg": "mcg", "μg": "mcg", "g": "g",
    "kg": "kg", "ui": "iu", "iu": "iu", "u": "iu", "%": "%", "ml": "ml", "cl": "cl",
    "dl": "dl", "l": "l", "h": "h", "dia": "day", "día": "day", "dosis": "dose",
    "microgramos": "mcg", "microgramo": "mcg", "miligramos": "mg", "miligramo": "mg",
    "gramos": "g", "gramo": "g", "unidades": "iu", "unidad": "iu",
    "mililitros": "ml", "mililitro": "ml", "comprimido": "tablet",
    "comprimidos": "tablet", "sobre": "sachet", "sobres": "sachet",
    "ampolla": "ampoule", "ampollas": "ampoule", "vial": "vial", "viales": "vial",
    "pulsacion": "puff", "pulsaciones": "puff", "aplicacion": "application",
    "aplicaciones": "application",
}
_VOLUME_UNITS = {"ml", "cl", "dl", "l", "h", "day", "dose", "tablet", "sachet",
                 "ampoule", "vial", "puff", "application"}


def _clean_dose(text: str) -> str:
    """把 dosis 里的噪声先抹掉："600 - REVISAR mg"、"100.000 UI"、"Desconocida"。"""
    s = (text or "").strip().lower()
    s = s.replace("microgramos", "mcg").replace("miligramos", "mg")
    s = s.replace("unidades internacionales", "ui")
    for junk in ("revisar", "desconocida", "n.a.", "n/a", "ver sección", "ver seccion",
                 "contiene", "más de", "mas de", "de un principio"):
        s = s.replace(junk, " ")
    s = re.sub(r"\s*[-–]\s*", " ", s)   # "600 - revisar mg" → "600   mg"
    s = _RE_THOUSANDS.sub(r"\1\2", s)   # 100.000 UI → 100000 UI（欧洲千分位）
    s = _RE_THOUSANDS.sub(r"\1\2", s)
    return s


def parse_dosis(text: str) -> list[tuple[float, str, float | None, str | None]]:
    """"600 mg/300 mg" → 两个成分；"5 mg/ml" / "20 mg/24 h" → 强度 + 每容积。

    返回 [(value, unit, per_volume, per_volume_unit)]，顺序即剂型串里的顺序。
    """
    s = _clean_dose(text)
    if not s or s.strip(" -") in {"", "0"}:
        return []
    out: list[tuple[float, str, float | None, str | None]] = []
    for group in re.split(r"\s*\+\s*", s):
        # "/" 既可能是复方分隔（600 mg/300 mg）也可能是每容积（5 mg/ml、20 mg/24 h）
        for seg in (x.strip() for x in group.split("/")):
            if not seg:
                continue
            m = _RE_QTY.search(seg)
            if not m:
                bare = _RE_BARE_DENOM.match(seg.strip())
                if bare and out:      # "5 mg/ml" → 每 1 ml
                    v, u, _pv, _pu = out[-1]
                    unit = _UNIT_MAP.get(bare.group(1).lower(), bare.group(1).lower())
                    out[-1] = (v, u, 1.0, unit)
                continue
            unit = _UNIT_MAP.get(m.group("unit").lower(), m.group("unit").lower())
            try:
                val = float(m.group("val").replace(",", "."))
            except ValueError:
                continue
            if unit in _VOLUME_UNITS:
                if out:      # 容积/时间/单位数 → 上一个成分的「每 X」
                    v, u, _pv, _pu = out[-1]
                    out[-1] = (v, u, val, unit)
                continue
            out.append((val, unit, None, None))
    return out


def status_of(rec: dict) -> tuple[str, str | None, str]:
    """estado/comerc → (status, status_date, 说明)。

    estado 的键：aut=已批准（总是有，值可能是 1966 这种哨兵负数）、
    rev=已撤销（→ withdrawn）、susp=已暂停（→ discontinued）。
    comerc=false 且没有 rev/susp = 不再上市（→ discontinued）。
    """
    est = rec.get("estado") or {}
    if isinstance(est, dict) and "rev" in est:
        return "withdrawn", _ms_date(est.get("rev")), "revocado"
    if isinstance(est, dict) and "susp" in est:
        return "discontinued", _ms_date(est.get("susp")), "suspendido"
    if not rec.get("comerc"):
        return "discontinued", None, "no comercializado"
    return "active", None, ""


def _ms_date(ms) -> str | None:
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        return None
    if ms <= 0 or ms > 4102444800000:      # 哨兵值 / 明显越界
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def release_of(*texts: str) -> str:
    blob = _deaccent(" ".join(t for t in texts if t)).lower()
    for code, keys in _RE_RELEASE:
        if any(k in blob for k in keys):
            return code
    return "none"


def form_base_es(form_es: str) -> str:
    """西语剂型 → 英文短语 → 共享的 form_base_of()（tablet/capsule/liquid/...）。

    共享函数按固定顺序找关键词（liquid 在 powder/injection 之前），西语长句里
    "POLVO PARA SOLUCION INYECTABLE" 会先撞上 solution，所以几处先自己定调。
    """
    f = _deaccent(form_es or "").lower()
    if "topico" in f or "cutane" in f or "transdermic" in f:
        return "topical"
    if f.startswith(("polvo", "granulado", "sobre", "gragea")):
        return "powder" if not f.startswith("gragea") else "tablet"
    drop = {"producto", "uso", "via", "con", "de", "para", "en", "y", "o", "para"}
    words = [w for w in re.split(r"[\s/,;()]+", f) if w and w not in drop]
    return form_base_of(" ".join(FORM_ES_EN.get(w, w) for w in words))


def split_salt_es(name: str) -> tuple[str, str]:
    """"enoxaparina sodio" → ("enoxaparina", "sodio")；只剥尾部的盐型词。

    "sodio cloruro" / "sodio bicarbonato" 是「盐在前」的西语写法，首词本身就是盐，
    再剥就把名字剥空了，所以首词是盐型词时不动。
    """
    words = name.lower().replace("-", " ").split()
    if len(words) > 1 and words[0] in ES_SALTS:
        return " ".join(words), ""
    tail: list[str] = []
    while len(words) > 1 and words[-1] in ES_SALTS:
        tail.insert(0, words.pop())
    if len(words) > 1 and words[-1] == "de":      # "colistimetato de sodio" → 剩下 "colistimetato de"
        words.pop()
    return " ".join(words), " ".join(tail)


def _noise_token(tok: str) -> bool:
    """规格/剂型/单位 → 名字键里不该出现。"""
    low = _deaccent(tok).lower().strip("().,;")
    if not low:
        return True
    if low in ES_FORM_WORDS:
        return True
    if re.fullmatch(r"[\d.,/%+-]+", low):
        return True
    if re.fullmatch(r"[\d.,]+\s*(mg|mcg|g|ml|cl|dl|l|ui|iu|%|u)", low):
        return True
    parts = [p for p in re.split(r"[/]", low) if p]
    return bool(parts) and all(
        p in ES_FORM_WORDS or re.fullmatch(r"[\d.,]+", p) for p in parts)


def es_brand_tokens(norm: str) -> list[str]:
    """归一化后的 token 里去掉西语剂型词、单位和纯数字。"""
    return [t for t in norm.split() if not _noise_token(t)]


def es_brand_display(nombre: str) -> str:
    """原始 nombre 里剥掉规格与剂型，留下人看的商品名（保留大小写）。"""
    out = [tok for tok in re.split(r"\s+", (nombre or "").strip()) if not _noise_token(tok)]
    return " ".join(out).strip(" /-")


# --- 网络层 ----------------------------------------------------------------
def _get_bytes(url: str, timeout: int = 90, tries: int = 4) -> bytes:
    last: Exception | None = None
    for i in range(tries):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 —— 网络抖动就地重试
            last = exc
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"请求失败 {url}: {last}")


def iter_pages(refresh: bool = False):
    """逐页产出 CIMA 的 resultados；原始 JSON 缓存在 data/raw/cima/page-NNN.json。

    CIMA 把 tamanioPagina 的下限钳到 200：请求 100，实际每页 200（128 页跑完全量）。
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    page = 1
    seen = 0
    total = None
    while True:
        dest = CACHE / f"page-{page:03d}.json"
        if dest.exists() and dest.stat().st_size > 100 and not refresh:
            payload = json.loads(dest.read_text(encoding="utf-8"))
        else:
            payload = json.loads(_get_bytes(LIST_URL.format(page=page)).decode("utf-8"))
            dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            time.sleep(POLITE_SLEEP)
        rows = payload.get("resultados") or []
        total = payload.get("totalFilas") or total
        if not rows:
            break
        yield rows
        seen += len(rows)
        if total and seen >= total:
            break
        page += 1
        if page > 400:
            raise SystemExit("页数异常，停下检查")


def pick_representatives(records) -> dict[str, str]:
    """每个单方 VTM 选一个代表产品（最常见的 (dosis, forma)，同票取最小注册号）→ nregistro。"""
    mode: dict[str, tuple[str, str]] = {}
    bucket: dict[str, Counter] = defaultdict(Counter)
    for rec in records:
        vtm = ((rec.get("vtm") or {}).get("nombre") or "").lower().strip()
        if not vtm or "+" in vtm:
            continue                        # 复方不取：组合 ATC 不能归到单一成分
        bucket[vtm][(_dose_key(rec), _form_key(rec))] += 1
    for vtm, c in bucket.items():
        mode[vtm] = c.most_common(1)[0][0]
    best: dict[str, tuple[int, str]] = {}
    for rec in records:
        vtm = ((rec.get("vtm") or {}).get("nombre") or "").lower().strip()
        if vtm not in mode or (_dose_key(rec), _form_key(rec)) != mode[vtm]:
            continue
        try:
            n = int(str(rec.get("nregistro") or "9" * 18))
        except ValueError:
            n = 10 ** 18
        if vtm not in best or n < best[vtm][0]:
            best[vtm] = (n, str(rec.get("nregistro")))
    return {k: v[1] for k, v in best.items()}


def _dose_key(rec: dict) -> str:
    return str(rec.get("dosis") or "")


def _form_key(rec: dict) -> str:
    return str((rec.get("formaFarmaceuticaSimplificada") or {}).get("nombre") or "")


def atc_of(nregistro: str) -> tuple[str, str] | None:
    """单条接口里的 atcs[]，取 nivel 最大的（= 最细的 ATC）。缓存到 data/raw/cima/atc/。"""
    ATC_CACHE.mkdir(parents=True, exist_ok=True)
    dest = ATC_CACHE / f"{nregistro}.json"
    if dest.exists():
        payload = json.loads(dest.read_text(encoding="utf-8"))
    else:
        try:
            full = json.loads(_get_bytes(DETAIL_URL.format(nreg=nregistro)).decode("utf-8"))
        except RuntimeError:
            return None
        payload = {"nregistro": nregistro, "atcs": full.get("atcs") or []}
        dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    codes = payload.get("atcs") or []
    if not codes:
        return None
    best = max(codes, key=lambda c: (c.get("nivel") or 0))
    code, name = best.get("codigo"), best.get("nombre")
    return (code, name) if code else None


def fetch_atc_map(reps: dict[str, str]) -> dict[str, tuple[str, str]]:
    """并发取代表产品的 ATC。失败不致命：缺口如实报告。"""
    if not reps:
        return {}
    ATC_CACHE.mkdir(parents=True, exist_ok=True)
    todo = sorted(reps.items())
    missing = sum(1 for _vtm, nreg in todo if not (ATC_CACHE / f"{nreg}.json").exists())
    print(f"ATC: {len(todo)} 个单方 VTM，其中 {missing} 条需要联网（其余已缓存）", flush=True)
    out: dict[str, tuple[str, str]] = {}
    t0 = time.time()

    def work(item):
        vtm, nreg = item
        return vtm, atc_of(nreg)

    with ThreadPoolExecutor(max_workers=ATC_WORKERS) as ex:
        for done, (vtm, atc) in enumerate(ex.map(work, todo), 1):
            if atc:
                out[vtm] = atc
            if done % 300 == 0:
                print(f"  ATC {done}/{len(todo)}  {time.time()-t0:.0f}s", flush=True)
    return out


# --- 主流程 ----------------------------------------------------------------
def resolve_ingredient(name: str, english_ids: set[str], created: set[str],
                       counts: Counter) -> tuple[str, str, str, bool, str, str]:
    """(substance_id, 规范名, salt, 是否对上了英文成分, 走的哪一层, 原始西语 base)。

    三层映射，见模块 docstring；都对不上就造一个西语 id（mapped=False）。
    """
    base, salt = split_salt_es(name)
    key = _deaccent(base).lower().strip()
    cands = ALIASES.get(key)
    if cands:
        for c in cands:
            if c in english_ids:
                counts["map_alias"] += 1
                return c, c, salt, True, "alias", base
        # 静态表是权威的：库里的美/英数据没收录也按英文 id 建，方便以后合并
        c = cands[0]
        counts["map_alias_new"] += 1
        english_ids.add(c)
        return c, c, salt, True, "alias_new", base
    s = slug(base)
    if s in english_ids:
        counts["map_slug"] += 1
        return s, s, salt, True, "slug", base
    if s in created:
        counts["map_repeat_es"] += 1
        return s, base, salt, False, "created", base
    for suf, repls in ES_SUFFIX_RULES:
        if not s.endswith(suf):
            continue
        stem = s[: -len(suf)]
        for r in repls:
            cand = stem + r
            if cand in english_ids:
                counts["map_rule"] += 1
                return cand, cand, salt, True, "rule", base
    counts["map_none"] += 1
    created.add(s)
    return s, base, salt, False, "none", base


def canonical_key(name: str, english_ids: set[str]) -> str:
    """只算 id、不改状态：单方产品统计「成分习惯单位」时用。"""
    base, _salt = split_salt_es(name)
    key = _deaccent(base).lower().strip()
    cands = ALIASES.get(key)
    if cands:
        for c in cands:
            if c in english_ids:
                return c
        return cands[0]
    s = slug(base)
    if s in english_ids:
        return s
    for suf, repls in ES_SUFFIX_RULES:
        if not s.endswith(suf):
            continue
        stem = s[: -len(suf)]
        for r in repls:
            if stem + r in english_ids:
                return stem + r
    return s


def build_unit_prefs(records, english_ids: set[str]) -> dict[str, Counter]:
    """单方产品里每个成分习惯用什么单位（复方配比顺序不可靠时用来纠偏）。"""
    prefs: dict[str, Counter] = defaultdict(Counter)
    for rec in records:
        vtm = ((rec.get("vtm") or {}).get("nombre") or "").strip()
        if not vtm or "+" in vtm:
            continue
        doses = parse_dosis(rec.get("dosis") or "")
        if len(doses) == 1:
            prefs[canonical_key(vtm, english_ids)].update([doses[0][1]])
    return prefs


def reorder_doses(doses, sids, prefs, threshold: int = 1):
    """复方：把强度按「成分习惯单位」重新对齐；同单位复方保持原顺序。

    例：alendronato + colecalciferol 的 dosis 写成 "2800 UI/70 mg"，
    VTM 顺序却是 alendronato 在前 —— 用单方产品学到的单位偏好就能摆正。
    只在明显更优（默认多命中 ≥1 个成分）时才改，避免把 "500 mg/125 mg" 这类同单位复方搞乱。
    """
    n = len(doses)
    if n < 2 or n > 4 or len(sids) != n:
        return doses

    def score(perm):
        return sum(prefs.get(sids[i], {}).get(doses[j][1], 0)
                   for i, j in enumerate(perm))

    identity = tuple(range(n))
    best = identity
    best_score = score(identity)
    for perm in permutations(range(n)):
        sc = score(perm)
        if sc > best_score + threshold - 1:
            best, best_score = perm, sc
    return [doses[j] for j in best]


def _name_rows(brand_display: str, brand_norm: str, vtm_norm: str):
    """品牌名 → [(raw, name_type, is_primary)]。品牌等于 VTM 时降级成 inn。"""
    if not brand_norm:
        return []
    if brand_norm == vtm_norm:
        return [(brand_display or brand_norm, "inn", 1)]
    return [(brand_display or brand_norm, "trade", 1)]


def _put_name(db: sqlite3.Connection, pid: str, raw: str, ntype: str, primary: int,
              seen_key: set[str], seen_nv: set[tuple[str, str]],
              extra_raw: str | None = None) -> None:
    n = normalize(raw)
    if n.is_empty:
        return
    key = n.norm
    if key not in seen_key:
        seen_key.add(key)
        db.execute("INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                   " VALUES (?,?,?,?)", (key, key, n.compact, n.script))
    for one in (raw, extra_raw):
        if not one or (key, one) in seen_nv:
            continue
        seen_nv.add((key, one))
        db.execute("INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                   " VALUES (?,?,?)", (key, one, SOURCE_ID))
    db.execute("INSERT OR IGNORE INTO product_name (product_id, key_id, name_type, is_primary)"
               " VALUES (?,?,?,?)", (pid, key, ntype, primary))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（验证用）")
    ap.add_argument("--no-atc", action="store_true", help="不补 ATC（离线/求快）")
    ap.add_argument("--refresh", action="store_true", help="忽略缓存重新下载")
    ap.add_argument("--db", type=Path, default=DB, help="目标库（默认 data/drugs.db）")
    ap.add_argument("--reset", action="store_true",
                    help="先删掉已有 ES 产品再导入（幂等重跑用）")
    args = ap.parse_args()

    t0 = time.time()
    print("读取 CIMA 列表 ...", flush=True)
    records: list[dict] = []
    for rows in iter_pages(refresh=args.refresh):
        records.extend(rows)
        if args.limit and len(records) >= args.limit:
            records = records[: args.limit]
            break
    print(f"  {len(records)} 条记录  {time.time()-t0:.0f}s", flush=True)

    reps = {} if args.no_atc else pick_representatives(records)
    atc_map = fetch_atc_map(reps)
    if not args.no_atc:
        print(f"  ATC 覆盖 {len(atc_map)}/{len(reps)} 个单方 VTM", flush=True)
        if atc_map:
            code, name = next(iter(atc_map.values()))
            print(f"  例：{code} {name}", flush=True)

    db = sqlite3.connect(args.db)
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    db.execute(
        "INSERT OR REPLACE INTO source (source_id, name, url, license, license_url,"
        " retrieved_at, notes) VALUES (?,?,?,?,?,?,?)",
        (SOURCE_ID, "CIMA (AEMPS) — Centro de Información online de Medicamentos",
         "https://cima.aemps.es/cima/publico/home.html",
         "Datos públicos de la AEMPS (reutilización con atribución)",
         "https://www.aemps.gob.es/", TODAY,
         "REST: /cima/rest/medicamentos (lista) + /cima/rest/medicamento (ficha, ATC)"),
    )

    if args.reset:
        old = db.execute("SELECT COUNT(*) FROM product WHERE country = 'ES'").fetchone()[0]
        db.execute("DELETE FROM product WHERE country = 'ES'")
        print(f"  --reset：删掉已有 ES 产品 {old:,} 条", flush=True)

    db_ids = {r[0] for r in db.execute("SELECT substance_id FROM substance")}
    # 「英文成分」= 已经挂着美/英（或人工种子）产品的 substance。
    # 不能拿整张 substance 表当映射目标：别的西语市场（MX）也会在这张表里造西语 id，
    # 那些 id 会把西班牙产品吸走，反而断掉和美/英的合并。
    english_ids = {r[0] for r in db.execute(
        """SELECT DISTINCT v.substance_id FROM product p
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           WHERE p.country IN ('US', 'GB', 'CN')""")}
    print(f"  已有英文成分 {len(english_ids):,} 个（US/GB/CN 在用）", flush=True)
    unit_pref = build_unit_prefs(records, english_ids)
    created: set[str] = set()          # 本次造出来的西语 id
    new_substances: set[str] = set()
    seen_key: set[str] = set()
    seen_nv: set[tuple[str, str]] = set()
    seen_variant: set[str] = set()
    counts: Counter = Counter()
    sub_atc: dict[str, tuple[str, str]] = {}
    unmapped: Counter = Counter()
    alias_new: Counter = Counter()

    for rec in records:
        counts["in"] += 1
        nreg = str(rec.get("nregistro") or "").strip()
        nombre = (rec.get("nombre") or "").strip()
        vtm_raw = ((rec.get("vtm") or {}).get("nombre") or "").strip()
        if not nreg or not nombre or not vtm_raw:
            counts["skip"] += 1
            counts["skip_no_fields"] += 1
            continue
        if vtm_raw.lower() == "multicomponente":
            # 西语「多成分」占位 VTM（≥4 个活性成分的复方/造影剂/血浆制品），无对应成分
            counts["skip"] += 1
            counts["skip_multicomponente"] += 1
            continue

        form_es = ((rec.get("formaFarmaceuticaSimplificada") or {}).get("nombre")
                   or (rec.get("formaFarmaceutica") or {}).get("nombre") or "").strip()
        dosage_form = form_es.lower() or "unknown"
        status, status_date, status_note = status_of(rec)
        pid = f"ES-{nreg}"

        ingredients = [x.strip() for x in vtm_raw.split(" + ") if x.strip()]
        doses = parse_dosis(rec.get("dosis") or "")
        if not doses:      # dosis 常是 "-" / "Desconocida"：退回从 nombre 里切强度
            doses = [(float(v), u, None, None) for v, u in normalize(nombre).strengths
                     if re.fullmatch(r"[\d.]+", v)]

        brand_display = es_brand_display(nombre)
        brand_norm = " ".join(es_brand_tokens(normalize(nombre).norm))
        vtm_norm = normalize(vtm_raw).norm
        is_branded = int(bool(brand_norm) and brand_norm != vtm_norm)
        is_combo = len(ingredients) > 1

        note = " | ".join(x for x in (
            (rec.get("cpresc") or "").strip(),
            "genérico" if rec.get("generico") else "",
            "biosimilar" if rec.get("biosimilar") else "",
            "triángulo" if rec.get("triangulo") else "",
            status_note) if x)
        # 产品行必须先写：product_component.product_id 有外键
        db.execute(
            "INSERT OR REPLACE INTO product (product_id, country, dosage_form, form_base,"
            " route, release, pack, mah, approval_id, category, is_branded, status,"
            " status_date, source_id, source_url, retrieved_at, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, "ES", dosage_form, form_base_es(form_es), _route_of(rec),
             release_of(form_es, nombre), None,
             (rec.get("labtitular") or "").strip() or None, nreg, "CIMA", is_branded,
             status, status_date, SOURCE_ID, PUBLIC_URL.format(nreg=nreg), TODAY,
             note or None))

        resolved = [resolve_ingredient(ing, english_ids, created, counts)
                    for ing in ingredients]
        sids = [r[0] for r in resolved]
        en_names: list[str] = []
        product_mapped = True
        for (_sid, display, _salt, mapped, via, es_base) in resolved:
            if not mapped:
                product_mapped = False
                unmapped[es_base.lower()] += 1
                en_names.append("")
            else:
                en_names.append(display)
                if via == "alias_new":
                    alias_new[display] += 1
        if len(doses) == len(ingredients) > 1:
            doses = reorder_doses(doses, sids, unit_pref)

        for i, (sid, display, salt, _mapped, _via, _es) in enumerate(resolved):
            if sid not in db_ids:
                db.execute("INSERT OR IGNORE INTO substance (substance_id, inn_en)"
                           " VALUES (?,?)", (sid, display.title()))
                db_ids.add(sid)
                if sid not in english_ids:
                    new_substances.add(sid)
            vid = f"{sid}-{slug(salt)}" if salt else sid
            if vid not in seen_variant:
                seen_variant.add(vid)
                db.execute("INSERT OR IGNORE INTO variant (variant_id, substance_id, salt)"
                           " VALUES (?,?,?)", (vid, sid, salt))
            d = doses[i] if i < len(doses) else (None, None, None, None)
            db.execute(
                "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                " strength_value, strength_unit, per_volume_value, per_volume_unit)"
                " VALUES (?,?,?,?,?,?,?)", (pid, i, vid, d[0], d[1], d[2], d[3]))

        # ATC 只挂单方：复方的 ATC 是组合码，不能算到某个成分头上
        atc = atc_map.get(vtm_raw.lower()) if not is_combo else None
        if atc and sids:
            sub_atc.setdefault(sids[0], atc)

        # 名字键：品牌 + 西语 VTM + 对应的英文 INN
        for raw, ntype, primary in _name_rows(brand_display, brand_norm, vtm_norm):
            _put_name(db, pid, raw, ntype, primary, seen_key, seen_nv)
        if vtm_norm:
            _put_name(db, pid, vtm_raw, "inn", 0 if is_branded else 1, seen_key, seen_nv)
        if all(en_names):
            en_combined = " + ".join(en_names)
            en_norm = normalize(en_combined).norm
            if en_norm and en_norm != vtm_norm:
                _put_name(db, pid, en_combined, "inn", 0, seen_key, seen_nv,
                          extra_raw=vtm_raw)

        counts["kept"] += 1
        counts["branded"] += is_branded
        counts["combo"] += int(is_combo)
        counts["prod_all_mapped"] += int(product_mapped)
        if counts["kept"] % 5000 == 0:
            db.commit()
            print(f"  ... {counts['kept']} products  {time.time()-t0:.0f}s", flush=True)

    for sid, (code, name) in sub_atc.items():
        db.execute("UPDATE substance SET atc = COALESCE(NULLIF(atc,''), ?),"
                   " atc_name = COALESCE(NULLIF(atc_name,''), ?) WHERE substance_id = ?",
                   (code, name, sid))

    if args.reset:      # 清掉已经没有任何产品引用的死角行（对站点不可见）
        dead_v = db.execute(
            "DELETE FROM variant WHERE variant_id NOT IN"
            " (SELECT variant_id FROM product_component)").rowcount
        dead_s = db.execute(
            "DELETE FROM substance WHERE substance_id NOT IN"
            " (SELECT substance_id FROM variant)").rowcount
        if dead_v or dead_s:
            print(f"  清理无产品引用的 variant {dead_v} / substance {dead_s}", flush=True)

    db.execute(
        "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
        " rows_in, rows_kept, rows_rejected, status, note) VALUES (?,?,?,?,?,?,?,?,?)",
        (f"{SOURCE_ID}-{TODAY}", SOURCE_ID, TODAY, TODAY, counts["in"], counts["kept"],
         counts["in"] - counts["kept"], "ok",
         json.dumps({k: v for k, v in counts.items() if k != "in"}, ensure_ascii=False)))
    db.commit()

    kept = max(counts["kept"], 1)
    print("\n== done ==")
    print(f"  用时 {time.time()-t0:.0f}s")
    print("  counts:", dict(sorted(counts.items())))
    print(f"  全成分映射到英文 id 的产品：{counts['prod_all_mapped']}/{counts['kept']}"
          f"  ({counts['prod_all_mapped']/kept:.1%})")
    print(f"  西语孤岛 substance（本次用到的、无英文映射）：{len(created)}"
          f"，其中本次新建 {len(new_substances)}")
    print(f"  ATC 写入成分：{len(sub_atc)}")
    if alias_new:
        print("  静态表目标在库里不存在（已按英文 id 新建，检查拼写）:")
        for name, n in alias_new.most_common(15):
            print(f"    {n:5d}  {name}")
    if unmapped:
        print("  未映射的西语 VTM（按出现次数）:")
        for name, n in unmapped.most_common(15):
            print(f"    {n:5d}  {name}")
    for row in db.execute("SELECT country, n_products, n_variants, n_active, last_synced"
                          " FROM coverage ORDER BY country"):
        print("  coverage:", row)
    db.close()


def _route_of(rec: dict) -> str | None:
    vias = [((v or {}).get("nombre") or "").strip().lower()
            for v in rec.get("viasAdministracion") or []]
    vias = [v for v in vias if v]
    return ", ".join(vias) or None


if __name__ == "__main__":
    main()
