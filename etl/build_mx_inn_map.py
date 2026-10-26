# -*- coding: utf-8 -*-
"""西语通用名（Denominación genérica）→ 英文 INN 映射。

为什么要专门做一层：卡上的身份是英文 INN（substance.inn_en），
而 COFEPRIS 给的是西语名（"Paracetamol" / "Ácido acetilsalicílico" / "Amoxicilina"）。
两边差的不只是重音，还有系统性词尾（-ina↔-ine、-ona↔-one、-ol↔-ole）和一堆不规则项。

策略（由严到松）：
  1. 精确命中（归一化后）
  2. 手工表（不规则的常用药）
  3. 规则变形（词尾替换 + 拼写等价）后精确命中
  4. difflib 模糊匹配，分数 ≥ 阈值才收
匹配不上的写进报告，人工补，不猜。

产物：
  data/mx_inn_map.json      {es_term: {"inn": "...", "via": "exact|manual|rule|fuzzy", "score": 1.0}}
  reports/mx_inn_unmatched.csv

用法：
    python etl/build_mx_inn_map.py            # 生成 + 报告
    python etl/build_mx_inn_map.py --report   # 只看未命中
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
ALOP_CSV = ROOT / "data" / "raw" / "mx" / "cofepris_alopaticos.csv"
OUT = ROOT / "data" / "mx_inn_map.json"
UNMATCHED = ROOT / "reports" / "mx_inn_unmatched.csv"

# 西语盐型/水合物/酯类词尾：匹配前先剥掉，跟英文侧 split_salt 对齐
ES_SALT = {
    "clorhidrato", "diclorhidrato", "bromhidrato", "mesilato", "besilato", "tosilato",
    "maleato", "succinato", "fumarato", "tartrato", "bitartrato", "citrato", "fosfato",
    "sulfato", "acetato", "propionato", "valerato", "maleato", "nitrato", "carbonato",
    "bicarbonato", "lactato", "gluconato", "oxalato", "benzoato", "cinamato", "sodico",
    "potasico", "calcico", "magnesico", "monohidrato", "dihidrato", "trihidrato",
    "tetrahidrato", "anhidro", "hidrato", "sal", "base", "libre",
}

# 手工表：西语名 → 英文 INN（写成的结果是 slug 化前的英文名）
MANUAL = {
    "acido acetilsalicilico": "aspirin",
    "acetilsalicilico": "aspirin",
    "paracetamol": "acetaminophen",
    "acetaminofen": "acetaminophen",
    "adrenalina": "epinephrine",
    "noradrenalina": "norepinephrine",
    "salbutamol": "albuterol",
    "isoprenalina": "isoproterenol",
    "furosemida": "furosemide",
    "frusemida": "furosemide",
    "lidocaina": "lidocaine",
    "lignocaina": "lidocaine",
    "nitroglicerina": "nitroglycerin",
    "clorfenamina": "chlorpheniramine",
    "colecalciferol": "cholecalciferol",
    "estradiol": "estradiol",
    "estriol": "estriol",
    "noretisterona": "norethindrone",
    "ciclosporina": "cyclosporine",
    "mesalazina": "mesalamine",
    "rifampicina": "rifampin",
    "suxametonio": "succinylcholine",
    "bromuro de escopolamina": "scopolamine butylbromide",
    "bencilpenicilina": "penicillin g",
    "fenoximetilpenicilina": "penicillin v",
    "levotiroxina": "levothyroxine",
    "tiroxina": "levothyroxine",
    "etilestradiol": "ethinyl estradiol",
    "amoxicilina": "amoxicillin",
    "sulfametoxazol": "sulfamethoxazole",
    "sulfasalazina": "sulfasalazine",
    "hidroxido de aluminio": "aluminum hydroxide",
    "acido folico": "folic acid",
    "acido valproico": "valproic acid",
    "valproato de sodio": "valproate",
    "acido ursodesoxicolico": "ursodeoxycholic acid",
    "acido tranexamico": "tranexamic acid",
    "acido retinoico": "tretinoin",
    "acido micofenolico": "mycophenolic acid",
    "acido alendronico": "alendronic acid",
    "acido risedronico": "risedronic acid",
    "acido ibandronico": "ibandronic acid",
    "acido zoledronico": "zoledronic acid",
    "acido pamidronico": "pamidronic acid",
    "acido borico": "boric acid",
    "acido lactico": "lactic acid",
    "acido citrico": "citric acid",
    "acido ascorbico": "ascorbic acid",
    "acido nicotinico": "nicotinic acid",
    "acido hialuronico": "hyaluronic acid",
    "acido fusidico": "fusidic acid",
    "acido azelaico": "azelaic acid",
    "acido glicolico": "glycolic acid",
    "acido salicilico": "salicylic acid",
    "acido benzoico": "benzoic acid",
    "acido acetico": "acetic acid",
    "acido boric": "boric acid",
    "dipirona": "metamizole",
    "metamizol": "metamizole",
    "metamizol sodico": "metamizole",
    "ambroxol": "ambroxol",
    "butilhioscina": "hyoscine butylbromide",
    "hioscina": "hyoscine",
    "escopolamina": "scopolamine",
    "omeprazol": "omeprazole",
    "pantoprazol": "pantoprazole",
    "esomeprazol": "esomeprazole",
    "lansoprazol": "lansoprazole",
    "rabeprazol": "rabeprazole",
    "ranitidina": "ranitidine",
    "famotidina": "famotidine",
    "metformina": "metformin",
    "glibenclamida": "glyburide",
    "glimepirida": "glimepiride",
    "sitagliptina": "sitagliptin",
    "insulina": "insulin",
    "levotiroxina sodica": "levothyroxine",
    "metimazol": "methimazole",
    "propiltiouracilo": "propylthiouracil",
    "prednisona": "prednisone",
    "prednisolona": "prednisolone",
    "metilprednisolona": "methylprednisolone",
    "dexametasona": "dexamethasone",
    "betametasona": "betamethasone",
    "hidrocortisona": "hydrocortisone",
    "triamcinolona": "triamcinolone",
    "budesonida": "budesonide",
    "fluticasona": "fluticasone",
    "beclometasona": "beclomethasone",
    "mometasona": "mometasone",
    "cortisona": "cortisone",
    "warfarina": "warfarin",
    "acenocumarol": "acenocoumarol",
    "clopidogrel": "clopidogrel",
    "ticagrelor": "ticagrelor",
    "prasugrel": "prasugrel",
    "dipiridamol": "dipyridamole",
    "heparina": "heparin",
    "enoxaparina": "enoxaparin",
    "dalteparina": "dalteparin",
    "rivaroxaban": "rivaroxaban",
    "apixaban": "apixaban",
    "dabigatran": "dabigatran",
    "atorvastatina": "atorvastatin",
    "rosuvastatina": "rosuvastatin",
    "simvastatina": "simvastatin",
    "pravastatina": "pravastatin",
    "lovastatina": "lovastatin",
    "fluvastatina": "fluvastatin",
    "ezetimiba": "ezetimibe",
    "fenofibrato": "fenofibrate",
    "gemfibrozilo": "gemfibrozil",
    "enalapril": "enalapril",
    "captopril": "captopril",
    "lisinopril": "lisinopril",
    "ramipril": "ramipril",
    "perindopril": "perindopril",
    "losartan": "losartan",
    "valsartan": "valsartan",
    "irbesartan": "irbesartan",
    "telmisartan": "telmisartan",
    "olmesartan": "olmesartan",
    "candesartan": "candesartan",
    "amlodipino": "amlodipine",
    "nifedipino": "nifedipine",
    "felodipino": "felodipine",
    "nitrendipino": "nitrendipine",
    "verapamilo": "verapamil",
    "diltiazem": "diltiazem",
    "metoprolol": "metoprolol",
    "atenolol": "atenolol",
    "bisoprolol": "bisoprolol",
    "carvedilol": "carvedilol",
    "nebivolol": "nebivolol",
    "propranolol": "propranolol",
    "furosemida": "furosemide",
    "espironolactona": "spironolactone",
    "hidroclorotiazida": "hydrochlorothiazide",
    "clortalidona": "chlorthalidone",
    "indapamida": "indapamide",
    "finerenona": "finerenone",
    "digoxina": "digoxin",
    "amiodarona": "amiodarone",
    "isosorbida": "isosorbide",
    "mononitrato de isosorbida": "isosorbide mononitrate",
    "etoricoxib": "etoricoxib",
    "celecoxib": "celecoxib",
    "diclofenaco": "diclofenac",
    "ibuprofeno": "ibuprofen",
    "naproxeno": "naproxen",
    "ketorolaco": "ketorolac",
    "ketoprofeno": "ketoprofen",
    "indometacina": "indomethacin",
    "meloxicam": "meloxicam",
    "piroxicam": "piroxicam",
    "nimesulida": "nimesulide",
    "paracetamol": "acetaminophen",
    "tramadol": "tramadol",
    "codeina": "codeine",
    "morfina": "morphine",
    "fentanilo": "fentanyl",
    "buprenorfina": "buprenorphine",
    "naloxona": "naloxone",
    "oxicodona": "oxycodone",
    "hidromorfona": "hydromorphone",
    "tapentadol": "tapentadol",
    "gabapentina": "gabapentin",
    "pregabalina": "pregabalin",
    "carbamazepina": "carbamazepine",
    "oxcarbazepina": "oxcarbazepine",
    "fenitoina": "phenytoin",
    "lamotrigina": "lamotrigine",
    "levetiracetam": "levetiracetam",
    "topiramato": "topiramate",
    "valproato": "valproate",
    "clonazepam": "clonazepam",
    "diazepam": "diazepam",
    "lorazepam": "lorazepam",
    "midazolam": "midazolam",
    "alprazolam": "alprazolam",
    "zolpidem": "zolpidem",
    "zopiclona": "zopiclone",
    "quetiapina": "quetiapine",
    "olanzapina": "olanzapine",
    "risperidona": "risperidone",
    "aripiprazol": "aripiprazole",
    "haloperidol": "haloperidol",
    "clozapina": "clozapine",
    "sertralina": "sertraline",
    "fluoxetina": "fluoxetine",
    "paroxetina": "paroxetine",
    "citalopram": "citalopram",
    "escitalopram": "escitalopram",
    "fluvoxamina": "fluvoxamine",
    "venlafaxina": "venlafaxine",
    "desvenlafaxina": "desvenlafaxine",
    "duloxetina": "duloxetine",
    "amitriptilina": "amitriptyline",
    "imipramina": "imipramine",
    "clomipramina": "clomipramine",
    "nortriptilina": "nortriptyline",
    "mirtazapina": "mirtazapine",
    "trazodona": "trazodone",
    "bupropion": "bupropion",
    "donepezilo": "donepezil",
    "memantina": "memantine",
    "rivastigmina": "rivastigmine",
    "galantamina": "galantamine",
    "levodopa": "levodopa",
    "carbidopa": "carbidopa",
    "pramipexol": "pramipexole",
    "ropinirol": "ropinirole",
    "amantadina": "amantadine",
    "sumatriptan": "sumatriptan",
    "rizatriptan": "rizatriptan",
    "eletriptan": "eletriptan",
    "alopurinol": "allopurinol",
    "colchicina": "colchicine",
    "febuxostat": "febuxostat",
    "prednisona": "prednisone",
    "metotrexato": "methotrexate",
    "azatioprina": "azathioprine",
    "micofenolato": "mycophenolate",
    "tacrolimus": "tacrolimus",
    "sirolimus": "sirolimus",
    "everolimus": "everolimus",
    "leflunomida": "leflunomide",
    "hidroxicloroquina": "hydroxychloroquine",
    "cloroquina": "chloroquine",
    "sulfasalazina": "sulfasalazine",
    "adalimumab": "adalimumab",
    "etanercept": "etanercept",
    "infliximab": "infliximab",
    "rituximab": "rituximab",
    "tocilizumab": "tocilizumab",
    "abatacept": "abatacept",
    "secukinumab": "secukinumab",
    "ustekinumab": "ustekinumab",
    "omalizumab": "omalizumab",
    "trastuzumab": "trastuzumab",
    "bevacizumab": "bevacizumab",
    "rituximab": "rituximab",
    "pembrolizumab": "pembrolizumab",
    "nivolumab": "nivolumab",
    "atezolizumab": "atezolizumab",
    "ipilimumab": "ipilimumab",
    "imatinib": "imatinib",
    "erlotinib": "erlotinib",
    "gefitinib": "gefitinib",
    "sorafenib": "sorafenib",
    "sunitinib": "sunitinib",
    "everolimus": "everolimus",
    "tamoxifeno": "tamoxifen",
    "anastrozol": "anastrozole",
    "letrozol": "letrozole",
    "exemestano": "exemestane",
    "bicalutamida": "bicalutamide",
    "leuprorelina": "leuprolide",
    "goserrelina": "goserelin",
    "triptorelina": "triptorelin",
    "octreotida": "octreotide",
    "desmopresina": "desmopressin",
    "oxitocina": "oxytocin",
    "misoprostol": "misoprostol",
    "dinoprostona": "dinoprostone",
    "sildenafil": "sildenafil",
    "tadalafil": "tadalafil",
    "vardenafil": "vardenafil",
    "finasterida": "finasteride",
    "dutasterida": "dutasteride",
    "tamsulosina": "tamsulosin",
    "doxazosina": "doxazosin",
    "terazosina": "terazosin",
    "solifenacina": "solifenacin",
    "tolterodina": "tolterodine",
    "oxibutinina": "oxybutynin",
    "alendronato": "alendronate",
    "risedronato": "risedronate",
    "ibandronato": "ibandronate",
    "zoledronato": "zoledronate",
    "raloxifeno": "raloxifene",
    "denosumab": "denosumab",
    "teriparatida": "teriparatide",
    "calcio": "calcium",
    "carbonato de calcio": "calcium carbonate",
    "citrato de calcio": "calcium citrate",
    "hierro": "iron",
    "sulfato ferroso": "ferrous sulfate",
    "fumarato ferroso": "ferrous fumarate",
    "acido folico": "folic acid",
    "cianocobalamina": "cyanocobalamin",
    "hidroxocobalamina": "hydroxocobalamin",
    "tiamina": "thiamine",
    "riboflavina": "riboflavin",
    "piridoxina": "pyridoxine",
    "niacinamida": "niacinamide",
    "vitamina a": "retinol",
    "vitamina c": "ascorbic acid",
    "vitamina d": "cholecalciferol",
    "vitamina e": "tocopherol",
    "vitamina k": "phytonadione",
    "zinc": "zinc",
    "magnesio": "magnesium",
    "potasio": "potassium",
    "cloruro de sodio": "sodium chloride",
    "solucion salina": "sodium chloride",
    "agua inyectable": "water for injection",
    "dextrosa": "dextrose",
    "glucosa": "dextrose",
    "amikacina": "amikacin",
    "gentamicina": "gentamicin",
    "tobramicina": "tobramycin",
    "neomicina": "neomycin",
    "estreptomicina": "streptomycin",
    "vancomicina": "vancomycin",
    "teicoplanina": "teicoplanin",
    "linezolid": "linezolid",
    "daptomicina": "daptomycin",
    "colistina": "colistin",
    "polimixina b": "polymyxin b",
    "penicilina g": "penicillin g",
    "penicilina v": "penicillin v",
    "ampicilina": "ampicillin",
    "amoxicilina": "amoxicillin",
    "cloxacilina": "cloxacillin",
    "dicloxacilina": "dicloxacillin",
    "piperacilina": "piperacillin",
    "cefalotina": "cephalothin",
    "cefazolina": "cefazolin",
    "cefalexina": "cephalexin",
    "cefuroxima": "cefuroxime",
    "cefotaxima": "cefotaxime",
    "ceftriaxona": "ceftriaxone",
    "ceftazidima": "ceftazidime",
    "cefepima": "cefepime",
    "cefixima": "cefixime",
    "cefdinir": "cefdinir",
    "cefpodxime": "cefpodoxime",
    "meropenem": "meropenem",
    "imipenem": "imipenem",
    "ertapenem": "ertapenem",
    "azitromicina": "azithromycin",
    "eritromicina": "erythromycin",
    "claritromicina": "clarithromycin",
    "clindamicina": "clindamycin",
    "doxiciclina": "doxycycline",
    "tetraciclina": "tetracycline",
    "minociclina": "minocycline",
    "ciprofloxacino": "ciprofloxacin",
    "levofloxacino": "levofloxacin",
    "moxifloxacino": "moxifloxacin",
    "norfloxacino": "norfloxacin",
    "ofloxacino": "ofloxacin",
    "nitrofurantoina": "nitrofurantoin",
    "trimetoprima": "trimethoprim",
    "metronidazol": "metronidazole",
    "tinidazol": "tinidazole",
    "fluconazol": "fluconazole",
    "itraconazol": "itraconazole",
    "ketoconazol": "ketoconazole",
    "voriconazol": "voriconazole",
    "posaconazol": "posaconazole",
    "terbinafina": "terbinafine",
    "nistatina": "nystatin",
    "anfotericina b": "amphotericin b",
    "acoclovir": "acyclovir",
    "aciclovir": "acyclovir",
    "valaciclovir": "valacyclovir",
    "ganciclovir": "ganciclovir",
    "oseltamivir": "oseltamivir",
    "ribavirina": "ribavirin",
    "lamivudina": "lamivudine",
    "zidovudina": "zidovudine",
    "tenofovir": "tenofovir",
    "efavirenz": "efavirenz",
    "nevirapina": "nevirapine",
    "lopinavir": "lopinavir",
    "ritonavir": "ritonavir",
    "atazanavir": "atazanavir",
    "darunavir": "darunavir",
    "dolutegravir": "dolutegravir",
    "raltegravir": "raltegravir",
    "emtricitabina": "emtricitabine",
    "abacavir": "abacavir",
    "interferon": "interferon",
    "ondansetron": "ondansetron",
    "granisetron": "granisetron",
    "metoclopramida": "metoclopramide",
    "domperidona": "domperidone",
    "escopolamina": "scopolamine",
    "omeprazol": "omeprazole",
    "bromuro de otilonio": "otilonium bromide",
    "loperamida": "loperamide",
    "trimebutina": "trimebutine",
    "simeticona": "simethicone",
    "lactulosa": "lactulose",
    "bisacodilo": "bisacodyl",
    "senosidos": "senna",
    "polietilenglicol": "polyethylene glycol",
    "mesalazina": "mesalamine",
    "sulfasalazina": "sulfasalazine",
    "lactobacilo": "lactobacillus",
    "prednisona": "prednisone",
    "beclometasona": "beclomethasone",
    "salbutamol": "albuterol",
    "salmeterol": "salmeterol",
    "formoterol": "formoterol",
    "budesonida": "budesonide",
    "ipratropio": "ipratropium",
    "tiotropio": "tiotropium",
    "montelukast": "montelukast",
    "zafirlukast": "zafirlukast",
    "teofilina": "theophylline",
    "aminofilina": "aminophylline",
    "cetirizina": "cetirizine",
    "levocetirizina": "levocetirizine",
    "loratadina": "loratadine",
    "desloratadina": "desloratadine",
    "fexofenadina": "fexofenadine",
    "clorfeniramina": "chlorpheniramine",
    "difenhidramina": "diphenhydramine",
    "hidroxicina": "hydroxyzine",
    "dexclorfeniramina": "dexchlorpheniramine",
    "bilastina": "bilastine",
    "ebastina": "ebastine",
    "olopatadina": "olopatadine",
    "ketotifeno": "ketotifen",
    "fluticasona": "fluticasone",
    "mometasona": "mometasone",

    # --- 第二批：按 COFEPRIS 实际词频补（2026-10-25） ---
    "dextrometorfano": "dextromethorphan",
    "acido clavulanico": "clavulanic acid",
    "clavulanico": "clavulanic acid",
    "fenilefrina": "phenylephrine",
    "cafeina": "caffeine",
    "etinilestradiol": "ethinyl estradiol",
    "etinil estradiol": "ethinyl estradiol",
    "bromuro de pinaverio": "pinaverium bromide",
    "pinaverio": "pinaverium",
    "magaldrato": "magaldrate",
    "cinarizina": "cinnarizine",
    "quinfamida": "quinfamide",
    "cloranfenicol": "chloramphenicol",
    "cisaprida": "cisapride",
    "clonixinato de lisina": "lysine clonixinate",
    "clonixinato": "clonixinate",
    "cinitaprida": "cinitapride",
    "subsalicilato de bismuto": "bismuth subsalicylate",
    "nitroprusiato de sodio": "sodium nitroprusside",
    "hipromelosa": "hypromellose",
    "dropropizina": "dropropizine",
    "fosfomicina": "fosfomycin",
    "bromuro de ipratropio": "ipratropium bromide",
    "ipratropio": "ipratropium",
    "estrogenos conjugados": "conjugated estrogens",
    "ketorolaco trometamina": "ketorolac tromethamine",
    "pentoxifilina": "pentoxifylline",
    "lincomicina": "lincomycin",
    "pseudoefedrina": "pseudoephedrine",
    "fenoterol": "fenoterol",
    "clemastina": "clemastine",
    "econazol": "econazole",
    "miconazol": "miconazole",
    "clotrimazol": "clotrimazole",
    "tioconazol": "tioconazole",
    "permetrina": "permethrin",
    "lindano": "lindane",
    "benzocaina": "benzocaine",
    "prilocaina": "prilocaine",
    "tetracaina": "tetracaine",
    "bupivacaina": "bupivacaine",
    "ropivacaina": "ropivacaine",
    "articaina": "articaine",
    "mepivacaina": "mepivacaine",
    "secnidazol": "secnidazole",
    "ornidazol": "ornidazole",
    "albendazol": "albendazole",
    "mebendazol": "mebendazole",
    "ivermectina": "ivermectin",
    "pirantel": "pyrantel",
    "nitazoxanida": "nitazoxanide",
    "paromomicina": "paromomycin",
    "furazolidona": "furazolidone",
    "nifuroxazida": "nifuroxazide",
    "bacitracina": "bacitracin",
    "mupirocina": "mupirocin",
    "gramicidina": "gramicidin",
    "retapamulina": "retapamulin",
    "pimecrolimus": "pimecrolimus",
    "calcipotriol": "calcipotriol",
    "isotretinoina": "isotretinoin",
    "tretinoina": "tretinoin",
    "adapaleno": "adapalene",
    "tazaroteno": "tazarotene",
    "peroxido de benzoilo": "benzoyl peroxide",
    "hidroquinona": "hydroquinone",
    "minoxidil": "minoxidil",
    "levonorgestrel": "levonorgestrel",
    "desogestrel": "desogestrel",
    "gestodeno": "gestodene",
    "medroxiprogesterona": "medroxyprogesterone",
    "progesterona": "progesterone",
    "testosterona": "testosterone",
    "tibolona": "tibolone",
    "danazol": "danazol",
    "clomifeno": "clomiphene",
    "cabergolina": "cabergoline",
    "bromocriptina": "bromocriptine",
    "liotironina": "liothyronine",
    "deflazacort": "deflazacort",
    "fludrocortisona": "fludrocortisone",
    "desonida": "desonide",
    "clobetasol": "clobetasol",
    "halobetasol": "halobetasol",
    "ciclesonida": "ciclesonide",
    "budesonida con formoterol": "budesonide/formoterol",
    "dimenhidrinato": "dimenhydrinate",
    "dimenhidrinalo": "dimenhydrinate",

    # --- 第三批：续期清单补录后新出现的 + 构词规则没吃到的 ---
    "metilfenidato": "methylphenidate",
    "valproato semisodico": "valproate semisodium",
    "valproato de magnesio": "valproate magnesium",
    "valproato": "valproate",
    "cromoglicato de sodio": "sodium cromoglicate",
    "cromoglicato": "cromoglicate",
    "acetonido de fluocinolona": "fluocinolone acetonide",
    "fluocinolona": "fluocinolone",
    "fenazopiridina": "phenazopyridine",
    "oxido de zinc": "zinc oxide",
    "hidroxido de magnesio": "magnesium hydroxide",
    "bicarbonato de sodio": "sodium bicarbonate",
    "complejo b": "vitamin b complex",
    "electrolitos orales": "oral rehydration salts",
    "macrogol": "macrogol",
    "citicolina": "citicoline",
    "flutamida": "flutamide",
    "enoxaparina sodica": "enoxaparin",
    "heparina sodica": "heparin",
    "micofenolato de mofetilo": "mycophenolate mofetil",
    "bromuro de rocuronio": "rocuronium bromide",
    "rocuronio": "rocuronium",
    "fenitoina sodica": "phenytoin",
    "glicopirronio": "glycopyrronium",
    "ceftibuteno": "ceftibuten",
    "bencidamina": "benzydamine",
    "doxofilina": "doxofylline",
    "floroglucinol": "phloroglucinol",
    "oxigeno": "oxygen",
    "solucion fisiologica": "sodium chloride",
    "pseudofedrina": "pseudoephedrine",
    "cloruro de sodio": "sodium chloride",
    "agua para inyeccion": "water for injection",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def key(s: str) -> str:
    s = strip_accents(s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def drop_es_salt(s: str) -> str:
    words = [w for w in s.split() if w not in ES_SALT]
    out = " ".join(words)
    # "maleato de dimenhidrinato" → 去掉盐以后还剩一个孤零零的 "de"
    out = re.sub(r"^de\s+", "", out)
    return out or s


def load_substances(db_path: Path) -> dict[str, str]:
    """归一化英文 INN → 原始写法。

    必须排除 ingest_mx 自己造的「西语名 substance」（id 前缀 mx-es-），
    否则第二次跑映射时西语名会精确命中自己，全部变成"已映射"，永远对不上英文。
    """
    db = sqlite3.connect(db_path)
    out: dict[str, str] = {}
    for (inn,) in db.execute(
            "SELECT inn_en FROM substance WHERE substance_id NOT LIKE 'mx-es-%'"):
        out.setdefault(key(inn), inn)
    db.close()
    return out


def es_terms() -> dict[str, tuple[str, int]]:
    """COFEPRIS 里出现的西语通用名：按归一化键去重，值 = (最常见写法, 次数)。"""
    raw: Counter = Counter()
    # 主清单 + 续期清单（续期清单里有 2001 年前的老药，通用名写法不一定出现在主清单）
    for path in (ALOP_CSV, ROOT / "data" / "raw" / "mx" / "cofepris_prorrogas.csv"):
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                g = (row.get("generic") or "").strip()
                if not g:
                    continue
                # 复方在源数据里既用 " / " 也用 "," 分隔
                for part in re.split(r"\s*[/,]\s*", g):
                    p = " ".join(part.split()).strip(" .,-")
                    if not p or len(p) <= 2:
                        continue
                    if p.upper() in {"CANCELADO", "REVOCADO", "VARIOS"}:
                        continue
                    # 2011–2013 文本兜底解析漏进来的页脚/状态列
                    if re.search(r"contenida|aprobado|informativo|documento|s\.a\. de c\.v|"
                                 r"^de c\.v|no legal", p, re.I):
                        continue
                    raw[p] += 1
    out: dict[str, tuple[str, int]] = {}
    for r, n in raw.items():
        k = key(r)
        if not k:
            continue
        cur = out.get(k)
        if cur is None or n > cur[1]:
            out[k] = (r, n)
    return out


def rule_variants(es: str) -> list[str]:
    """西语名 → 英文拼写的候选变形，按可能性排序。"""
    s = es
    out = [s]
    # 词尾：西语 -ina → 英语 -ine，-ina → -in（amoxicilina → amoxicillin）
    for a, b in (("ina", "ine"), ("ina", "in"), ("ona", "one"), ("ano", "ane"),
                 ("eno", "ene"), ("ilo", "yl"), ("ico", "ic"), ("ato", "ate"),
                 ("osa", "ose"), ("ol", "ole"), ("ilo", "il")):
        if s.endswith(a):
            out.append(s[: -len(a)] + b)
    # 拼写等价
    pairs = (("f", "ph"), ("t", "th"), ("c", "k"), ("qu", "c"), ("z", "s"),
             ("y", "i"), ("i", "y"), ("ll", "l"), ("ñ", "n"))
    base = list(out)
    for src, dst in pairs:
        for v in base:
            if src in v:
                out.append(v.replace(src, dst))
    return list(dict.fromkeys(out))


# 西语构词 → 英语构词（顺序敏感，长的在前）
MORPH = [
    ("hidroxido", "hydroxide"), ("hidroxi", "hydroxy"), ("hidro", "hydro"),
    ("metilfenidato", "methylphenidate"),
    ("metil", "methyl"), ("etil", "ethyl"), ("fenil", "phenyl"),
    ("propil", "propyl"), ("butil", "butyl"), ("bencil", "benzyl"),
    ("acetil", "acetyl"), ("acetato", "acetate"), ("acetonido", "acetonide"),
    ("clor", "chlor"), ("ciclo", "cyclo"), ("cistein", "cystein"),
    ("cromo", "chromo"), ("glico", "glyco"), ("glicer", "glycer"),
    ("fosf", "phosph"), ("ftal", "phth"), ("tio", "thio"), ("tiam", "thiam"),
    ("magnesio", "magnesium"), ("magnesico", "magnesium"),
    ("calcio", "calcium"), ("calcico", "calcium"),
    ("potasio", "potassium"), ("potasico", "potassium"),
    ("sodio", "sodium"), ("sodico", "sodium"), ("sodica", "sodium"),
    ("calcica", "calcium"), ("semisodico", "sodium"),
    ("oxido", "oxide"), ("hierro", "iron"), ("zinc", "zinc"),
    ("enoxaparina", "enoxaparin"), ("heparina", "heparin"),
    ("rocuronio", "rocuronium"), ("micofenolato", "mycophenolate"),
    ("mofetilo", "mofetil"), ("fluocinolona", "fluocinolone"),
    ("cromoglicato", "cromoglicate"), ("cromoglicico", "cromoglycic"),
    ("glicopirronio", "glycopyrronium"), ("bencidamina", "benzydamine"),
    ("doxofilina", "doxofylline"), ("citicolina", "citicoline"),
    ("floroglucinol", "phloroglucinol"), ("ceftibuteno", "ceftibuten"),
    ("valproato", "valproate"), ("macrogol", "macrogol"),
    ("acido ", ""), (" de ", " "), (" con ", " "),
    ("ina", "ine"), ("ato", "ate"), ("ico", "ic"), ("osa", "ose"),
    ("ona", "one"), ("ilo", "yl"), ("oso", "ous"), ("ano", "ane"), ("eno", "ene"),
]


def morph(s: str) -> str:
    for a, b in MORPH:
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--threshold", type=float, default=0.90)
    args = ap.parse_args()

    subs = load_substances(DB)
    subs_compact = {}
    for k, v in subs.items():
        subs_compact.setdefault(k.replace(" ", ""), v)
    subs_morph = {}
    for k, v in subs.items():
        subs_morph.setdefault(morph(k), v)
    print(f"substance {len(subs):,} 个；西语通用名去重后 ", end="")
    terms = es_terms()
    print(f"{len(terms):,} 个（总出现 {sum(n for _, n in terms.values()):,} 次）")

    mapping: dict[str, dict] = {}
    unmatched: list[tuple[str, int]] = []
    stat = Counter()

    for k, (es, n) in sorted(terms.items(), key=lambda kv: -kv[1][1]):
        # 1 精确
        if k in subs:
            mapping[k] = {"es": es, "inn": subs[k], "via": "exact", "score": 1.0}
            stat["exact"] += 1
            continue
        # 2 手工
        k2 = drop_es_salt(k)
        if k in MANUAL:
            target = MANUAL[k]
        elif k2 in MANUAL:
            target = MANUAL[k2]
        else:
            target = None
        if target:
            hit = subs.get(key(target))
            mapping[k] = {"es": es, "inn": hit or target.title(), "via": "manual", "score": 1.0}
            stat["manual"] += 1
            continue
        # 3 规则变形
        hit = None
        for v in rule_variants(k2):
            if v in subs:
                hit = subs[v]
                break
        if hit:
            mapping[k] = {"es": es, "inn": hit, "via": "rule", "score": 1.0}
            stat["rule"] += 1
            continue
        # 3.5 构词变形（metilfenidato → methylphenidate）
        m = morph(k2)
        hit = subs.get(m) or subs_morph.get(m)
        if hit:
            mapping[k] = {"es": es, "inn": hit, "via": "morph", "score": 1.0}
            stat["morph"] += 1
            continue
        # 3.6 去空格（PSE UDOEFEDRINA 这类排版断字）
        hit = subs_compact.get(k2.replace(" ", ""))
        if hit:
            mapping[k] = {"es": es, "inn": hit, "via": "compact", "score": 1.0}
            stat["compact"] += 1
            continue
        # 4 模糊（在构词变形后的空间里比）
        cand = difflib.get_close_matches(m, list(subs_morph), n=1, cutoff=args.threshold)
        if cand:
            mapping[k] = {"es": es, "inn": subs_morph[cand[0]], "via": "fuzzy",
                          "score": round(difflib.SequenceMatcher(None, m, cand[0]).ratio(), 3)}
            stat["fuzzy"] += 1
            continue
        unmatched.append((es, n))
        stat["unmatched"] += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"terms": mapping, "stats": dict(stat),
                               "generated_by": "etl/build_mx_inn_map.py"},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print("映射统计：", dict(stat), f"→ {OUT.relative_to(ROOT)}")

    if unmatched or args.report:
        UNMATCHED.parent.mkdir(parents=True, exist_ok=True)
        with UNMATCHED.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["es_term", "count"])
            w.writerows(unmatched)
        print(f"未命中 {len(unmatched)} 个 → {UNMATCHED.relative_to(ROOT)}；前 30：")
        for es, n in unmatched[:30]:
            print(f"   {n:>4}  {es}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
