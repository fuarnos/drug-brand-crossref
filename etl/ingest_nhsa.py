"""国家医保局 医保药品分类与代码数据库（NHSA）→ SQLite（中国数据）。

数据源
------
`data/raw/nhsa/nhsa_codes_20240105.csv`：2024-01-05 快照，234,370 行，UTF-8（带 BOM）。
同一批数据另有 19,531 页的 PDF 版（`nhsa_codes_full.pdf`），CSV 是从这份公开数据整理出来的
表格版；本脚本只吃 CSV，PDF 不再重复抽取。

范围
----
默认只吃 `药品代码` 以 `X` 开头的化学药（135,667 行）。`Z` 开头是中成药（98,703 行）：
其中只有 42 行带真实商品名，且没有英文成分可对，进来就是 ~8,300 个伪成分。所以默认不进来，
需要时用 `--include-tcm`。

与其它市场的对接
----------------
其它市场（US/GB/ES）挂在英文 INN 的 substance_id 上，所以中国行的关键是把中文通用名
落到已有的英文成分上。解析顺序（逐级降级，命中即停）：

1. `substance.inn_zh` 精确匹配；
2. 本文件内的人工 CN→EN 表（约 700 条常用药）；
3. 用代码里的 ATC-4 反查：`substr(atc,1,5) = 药品代码[1:6]` 且**恰好只有一个**成分时采用
   （多于一个说明这一级有同类药，宁可不错配）；
4. 都没有 → 建一个 CN 专属成分，`drug_class='unmapped-cn'`，等后续人工映射。

中文名在查表前会做剂型/盐基剥离（`盐酸二甲双胍片` → `二甲双胍`），剥离是逐级生成的，
每一级都当候选名去查表，所以 `氯化钠`（不能把钠当盐基剥掉）和 `阿托伐他汀钙` 能同时成立。

表结构
------
一行 = 一个国家的一个包装。`药品代码` 只有 23,778 个不同值却对应 135,667 行——同一代码下
挂着一堆厂家/包装变体，所以产品主键不能只用「药品代码 + 规格 + 包装」：那样会撞掉 29,190 行
（21.5%）。主键取 `批准文号 + 生产企业 + 规格 + 包装` 的指纹（见 `product_id_of`）。

写入方式
--------
**只增不删**：`INSERT OR REPLACE`（product / product_component）与 `INSERT OR IGNORE`
（substance / variant / name_key / name_variant / product_name），全按主键覆盖，可以反复跑。
不执行 `db/schema.sql`（库已存在，避免与并行写入的其它导入器抢 schema 锁）。

用法：
    python etl/ingest_nhsa.py                  # 只吃化学药（默认）
    python etl/ingest_nhsa.py --include-tcm    # 连中成药一起（会多出 ~8,300 个伪成分）
    python etl/ingest_nhsa.py --limit 2000     # 只跑前 2000 行，用于验证
    python etl/ingest_nhsa.py --db x.db        # 写到别的库（开发用，别指向正式库）
"""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from ingest_openfda_ndc import form_base_of  # noqa: E402
from normalize_name import normalize  # noqa: E402

RAW = ROOT / "data" / "raw" / "nhsa" / "nhsa_codes_20240105.csv"
DB = ROOT / "data" / "drugs.db"
SOURCE_ID = "nhsa"
SNAPSHOT = "2024-01-05"          # 快照日期，不是跑脚本的日期
SOURCE_URL = "https://code.nhsa.gov.cn/yp/toPublicGoodsData.html"
CAT_CHEM = "化学药"
CAT_TCM = "中成药"
NEW_EN_CLASS = "cn-only-en"      # 新建成分，但中文名已能给出英文 INN
UNMAPPED_CLASS = "unmapped-cn"   # 新建成分，只有中文名，等人工映射
BRAND_EMPTY = {"", "无", "无商品名", "-", "—", "－", "/", "暂无"}


# ---------------------------------------------------------------------------
# CN→EN：中文通用名 → 英文 INN（人工整理，按出现频次排过序）
#
# 键用「剥掉剂型、保留盐基」的写法；查表时还会试更进一步的盐基剥离结果，
# 所以 `盐酸二甲双胍` 只需登记 `二甲双胍`。反过来，盐基不能剥的名字（氯化钠、
# 硫酸镁、葡萄糖酸钙）按原样登记，靠「先查更具体的写法」保证不被剥坏。
# 目标是覆盖中国化学药的高频品种；没覆盖到的靠 ATC-4 与 CN 专属成分兜底。
# ---------------------------------------------------------------------------
CN2EN: dict[str, str] = {
    # --- 心血管 / 血液 ---
    "阿托伐他汀": "atorvastatin",
    "瑞舒伐他汀": "rosuvastatin",
    "辛伐他汀": "simvastatin",
    "匹伐他汀": "pitavastatin",
    "洛伐他汀": "lovastatin",
    "普伐他汀": "pravastatin",
    "氨氯地平": "amlodipine",
    "左氨氯地平": "levamlodipine",
    "硝苯地平": "nifedipine",
    "非洛地平": "felodipine",
    "尼群地平": "nitrendipine",
    "尼莫地平": "nimodipine",
    "尼卡地平": "nicardipine",
    "地尔硫卓": "diltiazem",
    "地尔硫䓬": "diltiazem",
    "维拉帕米": "verapamil",
    "美托洛尔": "metoprolol",
    "比索洛尔": "bisoprolol",
    "阿替洛尔": "atenolol",
    "普萘洛尔": "propranolol",
    "艾司洛尔": "esmolol",
    "卡维地洛": "carvedilol",
    "拉贝洛尔": "labetalol",
    "索他洛尔": "sotalol",
    "缬沙坦": "valsartan",
    "氯沙坦": "losartan",
    "厄贝沙坦": "irbesartan",
    "替米沙坦": "telmisartan",
    "坎地沙坦酯": "candesartan",
    "奥美沙坦酯": "olmesartan",
    "缬沙坦氨氯地平": "valsartan",
    "氯沙坦钾氢氯噻嗪": "losartan",
    "厄贝沙坦氢氯噻嗪": "irbesartan",
    "缬沙坦氢氯噻嗪": "valsartan",
    "奥美沙坦酯氢氯噻嗪": "olmesartan",
    "奥美沙坦酯氨氯地平": "olmesartan",
    "沙库巴曲缬沙坦": "valsartan",
    "卡托普利": "captopril",
    "依那普利": "enalapril",
    "赖诺普利": "lisinopril",
    "培哚普利": "perindopril",
    "贝那普利": "benazepril",
    "福辛普利": "fosinopril",
    "雷米普利": "ramipril",
    "咪达普利": "imidapril",
    "氢氯噻嗪": "hydrochlorothiazide",
    "吲达帕胺": "indapamide",
    "呋塞米": "furosemide",
    "托拉塞米": "torasemide",
    "布美他尼": "bumetanide",
    "螺内酯": "spironolactone",
    "氨苯蝶啶": "triamterene",
    "美托拉宗": "metolazone",
    "阿司匹林": "aspirin",
    "乙酰水杨酸": "aspirin",
    "赖氨匹林": "aspirin",
    "氯吡格雷": "clopidogrel",
    "氢氯吡格雷": "clopidogrel",
    "替格瑞洛": "ticagrelor",
    "替罗非班": "tirofiban",
    "西洛他唑": "cilostazol",
    "双嘧达莫": "dipyridamole",
    "华法林": "warfarin",
    "利伐沙班": "rivaroxaban",
    "阿哌沙班": "apixaban",
    "达比加群酯": "dabigatran",
    "肝素": "heparin",
    "肝素钠": "heparin",
    "依诺肝素": "enoxaparin",
    "那屈肝素": "nadroparin",
    "低分子量肝素": "heparin",
    "尿激酶": "urokinase",
    "阿替普酶": "alteplase",
    "氨甲环酸": "tranexamic acid",
    "氨甲苯酸": "aminomethylbenzoic acid",
    "氨基己酸": "aminocaproic acid",
    "酚磺乙胺": "etamsylate",
    "卡络磺": "carbazochrome",
    "肾上腺色腙": "carbazochrome",
    "维生素K1": "phytonadione",
    "地高辛": "digoxin",
    "去乙酰毛花苷": "deslanoside",
    "胺碘酮": "amiodarone",
    "普罗帕酮": "propafenone",
    "美西律": "mexiletine",
    "伊伐布雷定": "ivabradine",
    "尼可地尔": "nicorandil",
    "硝酸甘油": "nitroglycerin",
    "硝酸甘": "nitroglycerin",
    "单硝酸异山梨酯": "isosorbide mononitrate",
    "硝酸异山梨酯": "isosorbide dinitrate",
    "异山梨酯": "isosorbide dinitrate",
    "曲美他嗪": "trimetazidine",
    "尼麦角林": "nicergoline",
    "倍他司汀": "betahistine",
    "氟桂利嗪": "flunarizine",
    "桂利嗪": "cinnarizine",
    "尼莫地平注射液": "nimodipine",
    "长春西汀": "vinpocetine",
    "银杏叶提取物": "ginkgo biloba",
    "川芎嗪": "ligustrazine",
    "丹参酮": "tanshinone",
    "藻酸双酯": "propyl gallate",
    "棓丙酯": "propyl gallate",
    "阿魏酸": "ferulic acid",
    "阿魏酸哌嗪": "ferulic acid",
    "曲克芦丁": "troxerutin",
    "芦丁": "rutin",
    "羟苯磺酸钙": "calcium dobesilate",
    "七叶皂苷": "aescin",
    "葛根素": "puerarin",
    "天麻素": "gastrodin",
    "黄豆苷元": "daidzein",

    # --- 抗感染 ---
    "阿莫西林": "amoxicillin",
    "阿莫西林克拉维酸": "amoxicillin",
    "阿莫西林钠克拉维酸钾": "amoxicillin",
    "氨苄西林": "ampicillin",
    "氨苄西林钠舒巴坦": "ampicillin",
    "氨苄西林钠氯唑西林": "ampicillin",
    "哌拉西林": "piperacillin",
    "哌拉西林钠他唑巴坦": "piperacillin",
    "美洛西林": "mezlocillin",
    "美洛西林钠舒巴坦": "mezlocillin",
    "阿洛西林": "azlocillin",
    "替卡西林": "ticarcillin",
    "氯唑西林": "cloxacillin",
    "苯唑西林": "oxacillin",
    "氟氯西林": "flucloxacillin",
    "双氯西林": "dicloxacillin",
    "磺苄西林": "sulbenicillin",
    "青霉素": "penicillin g",
    "青霉素G": "penicillin g",
    "青霉素V": "penicillin v",
    "苄星青霉素": "penicillin g",
    "头孢氨苄": "cefalexin",
    "头孢拉定": "cefradine",
    "头孢羟氨苄": "cefadroxil",
    "头孢克洛": "cefaclor",
    "头孢呋辛": "cefuroxime",
    "头孢呋辛酯": "cefuroxime",
    "头孢克肟": "cefixime",
    "头孢地尼": "cefdinir",
    "头孢泊肟酯": "cefpodoxime",
    "头孢丙烯": "cefprozil",
    "头孢他啶": "ceftazidime",
    "头孢曲松": "ceftriaxone",
    "头孢噻肟": "cefotaxime",
    "头孢哌酮": "cefoperazone",
    "头孢哌酮舒巴坦": "cefoperazone",
    "头孢哌酮钠舒巴坦": "cefoperazone",
    "头孢哌酮钠舒巴坦钠": "cefoperazone",
    "头孢哌酮钠他唑巴坦": "cefoperazone",
    "头孢唑林": "cefazolin",
    "头孢西丁": "cefoxitin",
    "头孢美唑": "cefmetazole",
    "头孢米诺": "cefminox",
    "头孢替唑": "ceftezole",
    "头孢替安": "cefotiam",
    "头孢唑肟": "ceftizoxime",
    "头孢地嗪": "cefodizime",
    "头孢匹罗": "cefpirome",
    "头孢匹胺": "cefpiramide",
    "头孢尼西": "cefonicid",
    "头孢孟多酯": "cefamandole",
    "头孢硫脒": "cefathiamidine",
    "头孢噻吩": "cefalotin",
    "头孢甲肟": "cefmenoxime",
    "头孢他美酯": "cefetamet",
    "拉氧头孢": "latamoxef",
    "头孢氨苄甲氧苄啶": "cefalexin",
    "头孢哌酮钠": "cefoperazone",
    "舒巴坦": "sulbactam",
    "他唑巴坦": "tazobactam",
    "克拉维酸": "clavulanic acid",
    "亚胺培南": "imipenem",
    "美罗培南": "meropenem",
    "厄他培南": "ertapenem",
    "氨曲南": "aztreonam",
    "磷霉素": "fosfomycin",
    "红霉素": "erythromycin",
    "琥乙红霉素": "erythromycin",
    "依托红霉素": "erythromycin",
    "乳糖酸红霉素": "erythromycin",
    "阿奇霉素": "azithromycin",
    "克拉霉素": "clarithromycin",
    "罗红霉素": "roxithromycin",
    "地红霉素": "dirithromycin",
    "乙酰螺旋霉素": "acetylspiramycin",
    "螺旋霉素": "spiramycin",
    "吉他霉素": "kitasamycin",
    "乙酰吉他霉素": "acetylkitasamycin",
    "麦白霉素": "meleumycin",
    "麦迪霉素": "midecamycin",
    "林可霉素": "lincomycin",
    "克林霉素": "clindamycin",
    "克林霉素磷酸酯": "clindamycin",
    "林可霉素利多卡因": "lincomycin",
    "四环素": "tetracycline",
    "土霉素": "oxytetracycline",
    "多西环素": "doxycycline",
    "米诺环素": "minocycline",
    "美他环素": "metacycline",
    "金霉素": "chlortetracycline",
    "替加环素": "tigecycline",
    "氯霉素": "chloramphenicol",
    "甲砜霉素": "thiamphenicol",
    "庆大霉素": "gentamicin",
    "阿米卡星": "amikacin",
    "妥布霉素": "tobramycin",
    "奈替米星": "netilmicin",
    "依替米星": "etimicin",
    "小诺霉素": "micronomicin",
    "卡那霉素": "kanamycin",
    "链霉素": "streptomycin",
    "核糖霉素": "ribostamycin",
    "西索米星": "sisomicin",
    "新霉素": "neomycin",
    "诺氟沙星": "norfloxacin",
    "左氧氟沙星": "levofloxacin",
    "氧氟沙星": "ofloxacin",
    "环丙沙星": "ciprofloxacin",
    "莫西沙星": "moxifloxacin",
    "加替沙星": "gatifloxacin",
    "培氟沙星": "pefloxacin",
    "洛美沙星": "lomefloxacin",
    "氟罗沙星": "fleroxacin",
    "依诺沙星": "enoxacin",
    "司帕沙星": "sparfloxacin",
    "帕珠沙星": "pazufloxacin",
    "吡哌酸": "pipemidic acid",
    "甲硝唑": "metronidazole",
    "替硝唑": "tinidazole",
    "奥硝唑": "ornidazole",
    "塞克硝唑": "secnidazole",
    "磺胺甲噁唑": "sulfamethoxazole",
    "磺胺嘧啶": "sulfadiazine",
    "磺胺二甲嘧啶": "sulfadimidine",
    "磺胺脒": "sulfaguanidine",
    "联磺甲氧苄啶": "sulfamethoxazole",
    "甲氧苄啶": "trimethoprim",
    "呋喃唑酮": "furazolidone",
    "呋喃妥因": "nitrofurantoin",
    "利奈唑胺": "linezolid",
    "万古霉素": "vancomycin",
    "替考拉宁": "teicoplanin",
    "夫西地酸": "fusidic acid",
    "磷霉素氨丁三醇": "fosfomycin",
    "异烟肼": "isoniazid",
    "利福平": "rifampin",
    "利福昔明": "rifaximin",
    "利福喷丁": "rifapentine",
    "利福霉素": "rifamycin",
    "利福定": "rifandin",
    "吡嗪酰胺": "pyrazinamide",
    "乙胺丁醇": "ethambutol",
    "对氨基水杨酸钠": "aminosalicylic acid",
    "氨苯砜": "dapsone",
    "氟康唑": "fluconazole",
    "伊曲康唑": "itraconazole",
    "伏立康唑": "voriconazole",
    "酮康唑": "ketoconazole",
    "咪康唑": "miconazole",
    "益康唑": "econazole",
    "克霉唑": "clotrimazole",
    "联苯苄唑": "bifonazole",
    "特比萘芬": "terbinafine",
    "灰黄霉素": "griseofulvin",
    "制霉菌素": "nystatin",
    "两性霉素B": "amphotericin b",
    "氟胞嘧啶": "flucytosine",
    "阿昔洛韦": "acyclovir",
    "伐昔洛韦": "valacyclovir",
    "更昔洛韦": "ganciclovir",
    "泛昔洛韦": "famciclovir",
    "喷昔洛韦": "penciclovir",
    "利巴韦林": "ribavirin",
    "金刚烷胺": "amantadine",
    "奥司他韦": "oseltamivir",
    "扎那米韦": "zanamivir",
    "阿比多尔": "arbidol",
    "恩替卡韦": "entecavir",
    "拉米夫定": "lamivudine",
    "替比夫定": "telbivudine",
    "阿德福韦酯": "adefovir",
    "富马酸替诺福韦二吡呋酯": "tenofovir",
    "富马酸丙酚替诺福韦": "tenofovir alafenamide",
    "齐多夫定": "zidovudine",
    "奈韦拉平": "nevirapine",
    "依非韦伦": "efavirenz",
    "洛匹那韦": "lopinavir",
    "利托那韦": "ritonavir",
    "单磷酸阿糖腺苷": "vidarabine",
    "吗啉胍": "moroxydine",
    "聚肌胞": "polyinosinic-polycytidylic acid",
    "胸腺肽": "thymosin",
    "胸腺五肽": "thymopentin",
    "胸腺法新": "thymalfasin",
    "转移因子": "transfer factor",
    "脾氨肽": "spleen aminopeptide",
    "卡介菌多糖核酸": "bacillus calmette-guerin polysaccharide nucleic acid",

    # --- 消化 ---
    "奥美拉唑": "omeprazole",
    "艾司奥美拉唑": "esomeprazole",
    "艾司奥美拉唑镁": "esomeprazole",
    "兰索拉唑": "lansoprazole",
    "泮托拉唑": "pantoprazole",
    "雷贝拉唑": "rabeprazole",
    "艾普拉唑": "ilaprazole",
    "法莫替丁": "famotidine",
    "西咪替丁": "cimetidine",
    "雷尼替丁": "ranitidine",
    "罗沙替丁": "roxatidine",
    "铝碳酸镁": "hydrotalcite",
    "氢氧化铝": "aluminum hydroxide",
    "碳酸氢钠": "sodium bicarbonate",
    "大黄碳酸氢钠": "sodium bicarbonate",
    "龙胆碳酸氢钠": "sodium bicarbonate",
    "胶体果胶铋": "bismuth",
    "枸橼酸铋钾": "bismuth subcitrate",
    "铝酸铋": "bismuth aluminate",
    "硫糖铝": "sucralfate",
    "蒙脱石": "diosmectite",
    "多潘立酮": "domperidone",
    "莫沙必利": "mosapride",
    "伊托必利": "itopride",
    "甲氧氯普胺": "metoclopramide",
    "昂丹司琼": "ondansetron",
    "格拉司琼": "granisetron",
    "托烷司琼": "tropisetron",
    "帕洛诺司琼": "palonosetron",
    "雷莫司琼": "ramosetron",
    "阿扎司琼": "azasetron",
    "多拉司琼": "dolasetron",
    "消旋山莨菪碱": "anisodamine",
    "山莨菪碱": "anisodamine",
    "东莨菪碱": "scopolamine",
    "丁溴东莨菪碱": "scopolamine butylbromide",
    "阿托品": "atropine",
    "颠茄": "belladonna",
    "间苯三酚": "phloroglucinol",
    "曲美布汀": "trimebutine",
    "匹维溴铵": "pinaverium",
    "奥曲肽": "octreotide",
    "生长抑素": "somatostatin",
    "乳果糖": "lactulose",
    "开塞露": "glycerol",
    "甘油": "glycerol",
    "聚乙二醇": "macrogol",
    "比沙可啶": "bisacodyl",
    "酚酞": "phenolphthalein",
    "双歧杆菌": "bifidobacterium",
    "乳酶生": "lactasin",
    "干酵母": "dried yeast",
    "胰酶": "pancreatin",
    "胃蛋白酶": "pepsin",
    "多酶": "multienzyme",
    "熊去氧胆酸": "ursodeoxycholic acid",
    "茴三硫": "anethole trithione",
    "曲匹布通": "trepibutone",
    "丙谷胺": "proglumide",
    "谷氨酸": "glutamic acid",
    "联苯双酯": "bifendate",
    "齐墩果酸": "oleanolic acid",
    "甘草酸二铵": "glycyrrhizin",
    "甘草酸苷": "glycyrrhizin",
    "甘草酸单铵": "glycyrrhizin",
    "硫普罗宁": "tiopronin",
    "葡醛内酯": "glucurolactone",
    "水飞蓟宾": "silibinin",
    "双环醇": "bicyclol",
    "门冬氨酸鸟氨酸": "ornithine",
    "腺苷蛋氨酸": "ademetionine",

    # --- 内分泌 / 代谢 ---
    "二甲双胍": "metformin",
    "二甲双胍格列本脲": "metformin",
    "二甲双胍格列吡嗪": "metformin",
    "二甲双胍格列齐特": "metformin",
    "格列齐特": "gliclazide",
    "格列吡嗪": "glipizide",
    "格列美脲": "glimepiride",
    "格列本脲": "glibenclamide",
    "格列喹酮": "gliquidone",
    "格列奈": "repaglinide",
    "瑞格列奈": "repaglinide",
    "那格列奈": "nateglinide",
    "阿卡波糖": "acarbose",
    "伏格列波糖": "voglibose",
    "米格列醇": "miglitol",
    "罗格列酮": "rosiglitazone",
    "吡格列酮": "pioglitazone",
    "西格列汀": "sitagliptin",
    "维格列汀": "vildagliptin",
    "沙格列汀": "saxagliptin",
    "利格列汀": "linagliptin",
    "阿格列汀": "alogliptin",
    "达格列净": "dapagliflozin",
    "恩格列净": "empagliflozin",
    "卡格列净": "canagliflozin",
    "胰岛素": "insulin",
    "人胰岛素": "insulin human",
    "门冬胰岛素": "insulin aspart",
    "赖脯胰岛素": "insulin lispro",
    "甘精胰岛素": "insulin glargine",
    "地特胰岛素": "insulin detemir",
    "谷赖胰岛素": "insulin glulisine",
    "左甲状腺素": "levothyroxine",
    "甲状腺": "thyroid",
    "甲巯咪唑": "methimazole",
    "丙硫氧嘧啶": "propylthiouracil",
    "碘": "iodine",
    "碘化钾": "potassium iodide",
    "左卡尼汀": "levocarnitine",
    "阿仑膦酸": "alendronic acid",
    "阿仑膦酸钠": "alendronic acid",
    "伊班膦酸": "ibandronic acid",
    "帕米膦酸": "pamidronic acid",
    "唑来膦酸": "zoledronic acid",
    "利塞膦酸": "risedronic acid",
    "骨化三醇": "calcitriol",
    "阿法骨化醇": "alfacalcidol",
    "维生素D": "cholecalciferol",
    "维生素D2": "ergocalciferol",
    "维生素D3": "cholecalciferol",
    "碳酸钙": "calcium carbonate",
    "碳酸钙D3": "calcium carbonate",
    "牡蛎碳酸钙": "calcium carbonate",
    "醋酸钙": "calcium acetate",
    "乳酸钙": "calcium lactate",
    "葡萄糖酸钙": "calcium gluconate",
    "葡萄糖酸钙锌": "calcium gluconate",
    "氯化钙": "calcium chloride",
    "枸橼酸钙": "calcium citrate",
    "非布司他": "febuxostat",
    "别嘌醇": "allopurinol",
    "苯溴马隆": "benzbromarone",
    "秋水仙碱": "colchicine",
    "左旋咪唑": "levamisole",
    "木糖醇": "xylitol",
    "果糖": "fructose",
    "转化糖": "invert sugar",
    "葡萄糖": "glucose",
    "葡萄糖氯化钠": "glucose",
    "葡萄糖氯化钙": "glucose",
    "葡萄糖氯化钠钾": "glucose",
    "口服五维葡萄糖": "glucose",
    "氯化钠": "sodium chloride",
    "浓氯化钠": "sodium chloride",
    "生理氯化钠": "sodium chloride",
    "复方氯化钠": "sodium chloride",
    "氯化钾": "potassium chloride",
    "氯化镁": "magnesium chloride",
    "硫酸镁": "magnesium sulfate",
    "硫酸锌": "zinc sulfate",
    "硫酸钙": "calcium sulfate",
    "门冬氨酸钾镁": "potassium magnesium aspartate",
    "枸橼酸钾": "potassium citrate",
    "枸橼酸钠": "sodium citrate",
    "乳酸钠": "sodium lactate",
    "乳酸钠林格": "sodium lactate",
    "醋酸钠林格": "sodium acetate",
    "钠林格": "sodium chloride",
    "灭菌注射用水": "water for injection",
    "甘油氯化钠": "glycerol",
    "甘油果糖氯化钠": "glycerol",
    "右旋糖酐40": "dextran 40",
    "右旋糖酐40葡萄糖": "dextran 40",
    "右旋糖酐40氯化钠": "dextran 40",
    "右旋糖酐70": "dextran 70",
    "羟乙基淀粉130/0.4氯化钠": "hydroxyethyl starch",
    "羟乙基淀粉": "hydroxyethyl starch",
    "复方氨基酸": "amino acids",
    "氨基酸": "amino acids",
    "脂肪乳": "fat emulsion",
    "中/长链脂肪乳": "fat emulsion",
    "丙泊酚中/长链脂肪乳": "propofol",
    "丙泊酚": "propofol",
    "维生素C": "ascorbic acid",
    "维生素B1": "thiamine",
    "维生素B2": "riboflavin",
    "维生素B6": "pyridoxine",
    "维生素B12": "cyanocobalamin",
    "甲钴胺": "mecobalamin",
    "腺苷钴胺": "cobamamide",
    "维生素E": "tocopherol",
    "维生素A": "retinol",
    "维生素AD": "retinol",
    "烟酰胺": "nicotinamide",
    "烟酸": "nicotinic acid",
    "叶酸": "folic acid",
    "亚叶酸": "folinic acid",
    "亚叶酸钙": "calcium folinate",
    "复合维生素B": "vitamin b complex",
    "水溶性维生素": "vitamin b complex",
    "维生素B": "vitamin b complex",
    "芦丁片": "rutin",
    "谷维素": "oryzanol",

    # --- 神经 / 精神 ---
    "吡拉西坦": "piracetam",
    "奥拉西坦": "oxiracetam",
    "茴拉西坦": "aniracetam",
    "胞磷胆碱": "citicoline",
    "胞磷胆碱钠": "citicoline",
    "脑蛋白水解物": "cerebrolysin",
    "小牛血去蛋白提取物": "deproteinized calf blood extract",
    "依达拉奉": "edaravone",
    "尼莫地平片": "nimodipine",
    "法舒地尔": "fasudil",
    "石杉碱甲": "huperzine a",
    "多奈哌齐": "donepezil",
    "加兰他敏": "galantamine",
    "美金刚": "memantine",
    "卡巴拉汀": "rivastigmine",
    "奥拉西坦胶囊": "oxiracetam",
    "左乙拉西坦": "levetiracetam",
    "丙戊酸": "valproic acid",
    "卡马西平": "carbamazepine",
    "奥卡西平": "oxcarbazepine",
    "拉莫三嗪": "lamotrigine",
    "托吡酯": "topiramate",
    "加巴喷丁": "gabapentin",
    "普瑞巴林": "pregabalin",
    "苯妥英": "phenytoin",
    "苯巴比妥": "phenobarbital",
    "拉考沙胺": "lacosamide",
    "唑尼沙胺": "zonisamide",
    "氯硝西泮": "clonazepam",
    "地西泮": "diazepam",
    "咪达唑仑": "midazolam",
    "劳拉西泮": "lorazepam",
    "阿普唑仑": "alprazolam",
    "艾司唑仑": "estazolam",
    "佐匹克隆": "zopiclone",
    "右佐匹克隆": "eszopiclone",
    "唑吡坦": "zolpidem",
    "氯丙嗪": "chlorpromazine",
    "奋乃静": "perphenazine",
    "氟哌啶醇": "haloperidol",
    "舒必利": "sulpiride",
    "利培酮": "risperidone",
    "奥氮平": "olanzapine",
    "喹硫平": "quetiapine",
    "氯氮平": "clozapine",
    "阿立哌唑": "aripiprazole",
    "齐拉西酮": "ziprasidone",
    "氨磺必利": "amisulpride",
    "帕利哌酮": "paliperidone",
    "氟西汀": "fluoxetine",
    "帕罗西汀": "paroxetine",
    "舍曲林": "sertraline",
    "西酞普兰": "citalopram",
    "艾司西酞普兰": "escitalopram",
    "氟伏沙明": "fluvoxamine",
    "文拉法辛": "venlafaxine",
    "度洛西汀": "duloxetine",
    "米氮平": "mirtazapine",
    "曲唑酮": "trazodone",
    "安非他酮": "bupropion",
    "伏硫西汀": "vortioxetine",
    "阿米替林": "amitriptyline",
    "多塞平": "doxepin",
    "氯米帕明": "clomipramine",
    "托莫西汀": "atomoxetine",
    "哌甲酯": "methylphenidate",
    "多巴丝肼": "levodopa",
    "左旋多巴": "levodopa",
    "卡比多巴": "carbidopa",
    "普拉克索": "pramipexole",
    "罗匹尼罗": "ropinirole",
    "金刚烷胺片": "amantadine",
    "苯海索": "trihexyphenidyl",
    "恩他卡朋": "entacapone",
    "司来吉兰": "selegiline",
    "利斯的明": "rivastigmine",
    "依帕司他": "epalrestat",
    "甲钴胺片": "mecobalamin",
    "硫辛酸": "thioctic acid",
    "牛磺酸": "taurine",
    "氨酪酸": "aminobutyric acid",
    "乙酰谷酰胺": "aceglutamide",
    "谷胱甘肽": "glutathione",
    "鼠神经生长因子": "mouse nerve growth factor",
    "神经节苷脂": "ganglioside",
    "单唾液酸四己糖神经节苷脂": "ganglioside",
    "细胞色素C": "cytochrome c",
    "辅酶A": "coenzyme a",
    "辅酶Q10": "coenzyme q10",
    "三磷酸腺苷": "adenosine triphosphate",
    "三磷酸胞苷": "cytidine triphosphate",
    "环磷腺苷": "cyclic adenosine monophosphate",
    "脑苷肌肽": "cattle encephalon glycoside and ignotin",
    "肌氨肽苷": "muscle amino peptide and nucleoside",

    # --- 镇痛 / 解热 / 抗炎 ---
    "对乙酰氨基酚": "acetaminophen",
    "氨酚黄那敏": "acetaminophen",
    "氨咖黄敏": "acetaminophen",
    "氨酚烷胺": "acetaminophen",
    "氨酚那敏": "acetaminophen",
    "酚氨咖敏": "acetaminophen",
    "氨酚苯海拉明": "acetaminophen",
    "酚咖": "acetaminophen",
    "阿咖酚": "aspirin",
    "布洛芬": "ibuprofen",
    "布洛伪麻": "ibuprofen",
    "右布洛芬": "ibuprofen",
    "双氯芬酸": "diclofenac",
    "双氯芬酸钾": "diclofenac",
    "氯芬黄敏": "diclofenac",
    "醋氯芬酸": "aceclofenac",
    "吲哚美辛": "indomethacin",
    "氨糖美辛": "indomethacin",
    "萘普生": "naproxen",
    "酮洛芬": "ketoprofen",
    "洛索洛芬": "loxoprofen",
    "芬布芬": "fenbufen",
    "吡罗昔康": "piroxicam",
    "美洛昔康": "meloxicam",
    "氯诺昔康": "lornoxicam",
    "塞来昔布": "celecoxib",
    "依托考昔": "etoricoxib",
    "尼美舒利": "nimesulide",
    "甲芬那酸": "mefenamic acid",
    "保泰松": "phenylbutazone",
    "贝诺酯": "benorilate",
    "安乃近": "metamizole",
    "去痛": "metamizole",
    "氨基比林咖啡因": "aminophenazone",
    "氨林巴比妥": "aminophenazone",
    "曲马多": "tramadol",
    "奈福泮": "nefopam",
    "帕瑞昔布": "parecoxib",
    "氟比洛芬": "flurbiprofen",
    "酮咯酸氨丁三醇": "ketorolac",
    "丙帕他莫": "propacetamol",
    "高乌甲素": "lappaconitine",
    "罗通定": "rotundine",
    "美索巴莫": "methocarbamol",
    "氯唑沙宗": "chlorzoxazone",
    "乙哌立松": "eperisone",
    "别嘌醇片": "allopurinol",

    # --- 呼吸 / 抗过敏 ---
    "氯苯那敏": "chlorpheniramine",
    "氯雷他定": "loratadine",
    "地氯雷他定": "desloratadine",
    "西替利嗪": "cetirizine",
    "左西替利嗪": "levocetirizine",
    "非索非那定": "fexofenadine",
    "依巴斯汀": "ebastine",
    "咪唑斯汀": "mizolastine",
    "氮卓斯汀": "azelastine",
    "奥洛他定": "olopatadine",
    "酮替芬": "ketotifen",
    "赛庚啶": "cyproheptadine",
    "苯海拉明": "diphenhydramine",
    "异丙嗪": "promethazine",
    "茶苯海明": "dimenhydrinate",
    "倍他司汀片": "betahistine",
    "氨溴索": "ambroxol",
    "溴己新": "bromhexine",
    "乙酰半胱氨酸": "acetylcysteine",
    "羧甲司坦": "carbocisteine",
    "福多司坦": "fudosteine",
    "氨溴特罗": "ambroxol",
    "喷托维林": "pentoxyverine",
    "苯丙哌林": "benproperine",
    "右美沙芬": "dextromethorphan",
    "可待因": "codeine",
    "愈创木酚": "guaiacol",
    "左羟丙哌嗪": "levodropropizine",
    "孟鲁司特": "montelukast",
    "沙丁胺醇": "albuterol",
    "左沙丁胺醇": "levosalbutamol",
    "特布他林": "terbutaline",
    "班布特罗": "bambuterol",
    "丙卡特罗": "procaterol",
    "福莫特罗": "formoterol",
    "沙美特罗": "salmeterol",
    "茚达特罗": "indacaterol",
    "异丙托溴铵": "ipratropium",
    "噻托溴铵": "tiotropium",
    "茶碱": "theophylline",
    "氨茶碱": "aminophylline",
    "多索茶碱": "doxofylline",
    "二羟丙茶碱": "diprophylline",
    "麻黄碱": "ephedrine",
    "伪麻黄碱": "pseudoephedrine",
    "布地奈德": "budesonide",
    "倍氯米松": "beclometasone",
    "氟替卡松": "fluticasone",
    "糠酸莫米松": "mometasone",
    "环索奈德": "ciclesonide",
    "色甘酸钠": "sodium cromoglicate",
    "尼多克罗": "nedocromil",

    # --- 泌尿 / 生殖 ---
    "西地那非": "sildenafil",
    "他达拉非": "tadalafil",
    "伐地那非": "vardenafil",
    "达泊西汀": "dapoxetine",
    "非那雄胺": "finasteride",
    "度他雄胺": "dutasteride",
    "特拉唑嗪": "terazosin",
    "坦索罗辛": "tamsulosin",
    "多沙唑嗪": "doxazosin",
    "赛洛多辛": "silodosin",
    "阿夫唑嗪": "alfuzosin",
    "萘哌地尔": "naftopidil",
    "米诺地尔": "minoxidil",
    "托特罗定": "tolterodine",
    "索利那新": "solifenacin",
    "奥昔布宁": "oxybutynin",
    "黄酮哌酯": "flavoxate",
    "左炔诺孕酮": "levonorgestrel",
    "黄体酮": "progesterone",
    "地屈孕酮": "dydrogesterone",
    "甲羟孕酮": "medroxyprogesterone",
    "炔雌醇": "ethinylestradiol",
    "雌二醇": "estradiol",
    "己烯雌酚": "diethylstilbestrol",
    "氯米芬": "clomifene",
    "来曲唑": "letrozole",
    "他莫昔芬": "tamoxifen",
    "米非司酮": "mifepristone",
    "缩宫素": "oxytocin",
    "垂体后叶": "posterior pituitary",
    "绒促性素": "chorionic gonadotrophin",
    "尿促性素": "menotrophin",
    "壬苯醇醚": "nonoxinol",
    "乳酸依沙吖啶": "ethacridine",
    "聚甲酚磺醛": "policresulen",
    "氯己定": "chlorhexidine",
    "醋酸氯己定": "chlorhexidine",
    "聚维酮碘": "povidone-iodine",
    "碘酊": "iodine",
    "过氧化氢": "hydrogen peroxide",
    "高锰酸钾": "potassium permanganate",

    # --- 皮肤 / 外用 ---
    "莫匹罗星": "mupirocin",
    "夫西地酸乳膏": "fusidic acid",
    "阿达帕林": "adapalene",
    "维A酸": "tretinoin",
    "异维A酸": "isotretinoin",
    "过氧苯甲酰": "benzoyl peroxide",
    "氢化可的松": "hydrocortisone",
    "丁酸氢化可的松": "hydrocortisone butyrate",
    "醋酸氢化可的松": "hydrocortisone",
    "地塞米松": "dexamethasone",
    "地塞米松磷酸钠": "dexamethasone",
    "醋酸地塞米松": "dexamethasone",
    "泼尼松": "prednisone",
    "泼尼松龙": "prednisolone",
    "甲泼尼龙": "methylprednisolone",
    "甲泼尼龙琥珀酸钠": "methylprednisolone",
    "曲安奈德": "triamcinolone",
    "醋酸曲安奈德": "triamcinolone",
    "曲安奈德益康唑": "triamcinolone",
    "倍他米松": "betamethasone",
    "卤米松": "halometasone",
    "哈西奈德": "halcinonide",
    "氟轻松": "fluocinolone acetonide",
    "醋酸氟轻松": "fluocinolone acetonide",
    "糠酸莫米松乳膏": "mometasone",
    "炉甘石": "calamine",
    "尿素": "urea",
    "维E": "tocopherol",
    "水杨酸": "salicylic acid",
    "苯甲酸": "benzoic acid",
    "樟脑": "camphor",
    "薄荷脑": "menthol",
    "氧化锌": "zinc oxide",
    "硫软膏": "sulfur",
    "硫": "sulfur",
    "甲紫": "methylrosanilinium chloride",
    "碘甘油": "iodine",
    "玻璃酸": "hyaluronic acid",
    "玻璃酸钠": "sodium hyaluronate",
    "透明质酸": "hyaluronic acid",

    # --- 眼科 / 耳鼻喉 ---
    "左氧氟沙星滴眼液": "levofloxacin",
    "妥布霉素滴眼液": "tobramycin",
    "氯霉素滴眼液": "chloramphenicol",
    "羟甲唑啉": "oxymetazoline",
    "萘甲唑啉": "naphazoline",
    "赛洛唑啉": "xylometazoline",
    "色甘酸钠滴眼液": "sodium cromoglicate",
    "毛果芸香碱": "pilocarpine",
    "噻吗洛尔": "timolol",
    "布林佐胺": "brinzolamide",
    "拉坦前列素": "latanoprost",
    "曲伏前列素": "travoprost",
    "溴莫尼定": "brimonidine",
    "复方托吡卡胺": "tropicamide",
    "托吡卡胺": "tropicamide",
    "阿托品眼膏": "atropine",
    "苄达赖氨酸": "bendazac",
    "吡诺克辛": "pirenoxine",
    "七叶洋地黄双苷": "esculin and digitalis glycosides",
    "卵磷脂络合碘": "iodized lecithin",

    # --- 抗肿瘤 / 免疫 ---
    "环磷酰胺": "cyclophosphamide",
    "异环磷酰胺": "ifosfamide",
    "甲氨蝶呤": "methotrexate",
    "氟尿嘧啶": "fluorouracil",
    "替加氟": "tegafur",
    "替吉奥": "tegafur",
    "卡培他滨": "capecitabine",
    "吉西他滨": "gemcitabine",
    "阿糖胞苷": "cytarabine",
    "羟基脲": "hydroxycarbamide",
    "阿霉素": "doxorubicin",
    "表柔比星": "epirubicin",
    "吡柔比星": "pirarubicin",
    "多柔比星": "doxorubicin",
    "柔红霉素": "daunorubicin",
    "米托蒽醌": "mitoxantrone",
    "长春新碱": "vincristine",
    "长春瑞滨": "vinorelbine",
    "长春地辛": "vindesine",
    "紫杉醇": "paclitaxel",
    "多西他赛": "docetaxel",
    "白蛋白紫杉醇": "paclitaxel",
    "顺铂": "cisplatin",
    "卡铂": "carboplatin",
    "奥沙利铂": "oxaliplatin",
    "奈达铂": "nedaplatin",
    "洛铂": "lobaplatin",
    "环孢素": "ciclosporin",
    "他克莫司": "tacrolimus",
    "吗替麦考酚酯": "mycophenolate mofetil",
    "麦考酚钠": "mycophenolate sodium",
    "硫唑嘌呤": "azathioprine",
    "来氟米特": "leflunomide",
    "羟氯喹": "hydroxychloroquine",
    "甲氨蝶呤片": "methotrexate",
    "沙利度胺": "thalidomide",
    "来那度胺": "lenalidomide",
    "伊马替尼": "imatinib",
    "吉非替尼": "gefitinib",
    "厄洛替尼": "erlotinib",
    "埃克替尼": "icotinib",
    "阿法替尼": "afatinib",
    "奥希替尼": "osimertinib",
    "克唑替尼": "crizotinib",
    "索拉非尼": "sorafenib",
    "舒尼替尼": "sunitinib",
    "仑伐替尼": "lenvatinib",
    "安罗替尼": "anlotinib",
    "伊布替尼": "ibrutinib",
    "达沙替尼": "dasatinib",
    "尼洛替尼": "nilotinib",
    "硼替佐米": "bortezomib",
    "阿那曲唑": "anastrozole",
    "依西美坦": "exemestane",
    "比卡鲁胺": "bicalutamide",
    "氟他胺": "flutamide",
    "戈舍瑞林": "goserelin",
    "亮丙瑞林": "leuprorelin",
    "曲普瑞林": "triptorelin",
    "干扰素": "interferon alfa",
    "人干扰素α2b": "interferon alfa-2b",
    "人干扰素α1b": "interferon alfa-1b",
    "聚乙二醇干扰素": "peginterferon alfa",
    "白介素2": "aldesleukin",
    "人粒细胞刺激因子": "filgrastim",
    "人粒细胞巨噬细胞刺激因子": "sargramostim",
    "人促红素": "epoetin alfa",
    "重组人促红素": "epoetin alfa",
    "人生长激素": "somatropin",
    "胸腺素": "thymosin",
    "人血白蛋白": "albumin human",
    "人免疫球蛋白": "immunoglobulin human",
    "静注人免疫球蛋白": "immunoglobulin human",
    "乙型肝炎人免疫球蛋白": "hepatitis b immunoglobulin",
    "破伤风人免疫球蛋白": "tetanus immunoglobulin",
    "狂犬病人免疫球蛋白": "rabies immunoglobulin",
    "凝血酶": "thrombin",
    "凝血酶原复合物": "prothrombin complex concentrate",
    "纤维蛋白原": "fibrinogen",
    "人纤维蛋白原": "fibrinogen",
    "巴曲酶": "batroxobin",
    "降纤酶": "defibrinogenase",
    "蚓激酶": "lumbrokinase",
    "胰激肽原酶": "kallidinogenase",
    "尿激酶原": "prourokinase",
    "阿加曲班": "argatroban",
    "特利加压素": "terlipressin",
    "垂体后叶素": "posterior pituitary",
    "去氨加压素": "desmopressin",
    "促皮质素": "corticotrophin",
    "曲普瑞林缓释": "triptorelin",

    # --- 麻醉 / 肌松 / 镇痛 ---
    "利多卡因": "lidocaine",
    "碳酸利多卡因": "lidocaine",
    "布比卡因": "bupivacaine",
    "罗哌卡因": "ropivacaine",
    "普鲁卡因": "procaine",
    "丁卡因": "tetracaine",
    "甲哌卡因": "mepivacaine",
    "丙胺卡因": "prilocaine",
    "氯胺酮": "ketamine",
    "丙泊酚注射液": "propofol",
    "依托咪酯": "etomidate",
    "咪达唑仑注射液": "midazolam",
    "芬太尼": "fentanyl",
    "瑞芬太尼": "remifentanil",
    "舒芬太尼": "sufentanil",
    "哌替啶": "pethidine",
    "吗啡": "morphine",
    "羟考酮": "oxycodone",
    "可待因片": "codeine",
    "丁丙诺啡": "buprenorphine",
    "纳洛酮": "naloxone",
    "氟马西尼": "flumazenil",
    "维库溴铵": "vecuronium",
    "罗库溴铵": "rocuronium",
    "顺阿曲库铵": "cisatracurium",
    "苯磺顺阿曲库铵": "cisatracurium",
    "阿曲库铵": "atracurium",
    "泮库溴铵": "pancuronium",
    "琥珀胆碱": "suxamethonium",
    "新斯的明": "neostigmine",
    "溴吡斯的明": "pyridostigmine",
    "舒更葡糖钠": "sugammadex",

    # --- 其它高频 ---
    "肌苷": "inosine",
    "小檗碱": "berberine",
    "小檗碱甲氧苄啶": "berberine",
    "苦参碱": "matrine",
    "苦参素": "oxymatrine",
    "喜树碱": "camptothecin",
    "羟喜树碱": "hydroxycamptothecin",
    "高三尖杉酯碱": "homoharringtonine",
    "骨肽": "ossein",
    "骨瓜提取物": "bone extract",
    "鹿瓜多肽": "cervus and cucumis polypeptide",
    "氨肽素": "amino peptide",
    "甘露聚糖肽": "mannatide",
    "香菇菌多糖": "lentinan",
    "云芝胞内糖肽": "coriolus versicolor polypeptide",
    "薄芝糖肽": "bozhi glycopeptide",
    "灵杆菌多糖": "prodiginine",
    "聚肌胞苷酸": "polyinosinic-polycytidylic acid",
    "右旋糖酐铁": "iron dextran",
    "蔗糖铁": "iron sucrose",
    "葡萄糖酸亚铁": "ferrous gluconate",
    "硫酸亚铁": "ferrous sulfate",
    "富马酸亚铁": "ferrous fumarate",
    "琥珀酸亚铁": "ferrous succinate",
    "枸橼酸铁铵": "ferric ammonium citrate",
    "多糖铁复合物": "polysaccharide iron complex",
    "叶酸片": "folic acid",
    "腺苷": "adenosine",
    "三磷酸腺苷二钠": "adenosine triphosphate",
    "磷酸肌酸": "creatine phosphate",
    "磷酸肌酸钠": "creatine phosphate",
    "环磷腺苷葡胺": "cyclic adenosine monophosphate",
    "二丁酰环磷腺苷": "dibutyryl cyclic amp",
    "果糖二磷酸": "fructose diphosphate",
    "果糖二磷酸钠": "fructose diphosphate",
    "1,6-二磷酸果糖": "fructose diphosphate",
    "左卡尼汀注射液": "levocarnitine",
    "丙氨酰谷氨酰胺": "alanyl glutamine",
    "谷氨酰胺": "glutamine",
    "精氨酸": "arginine",
    "赖氨酸": "lysine",
    "甲硫氨酸": "methionine",
    "维生素B1片": "thiamine",
    "多维元素": "multivitamin",
    "五维他": "vitamin b complex",
    "维酶素": "vitacoenzyme",
    "盖胃平": "gavipine",
    "胃膜素": "gastric mucin",
    "食母生": "dried yeast",
    "干酵母片": "dried yeast",
    "乳酸菌素": "lactasin",
    "酪酸梭菌活菌": "clostridium butyricum",
    "双歧杆菌三联活菌": "bifidobacterium",
    "地衣芽孢杆菌活菌": "bacillus licheniformis",
    "枯草杆菌二联活菌": "bacillus subtilis",
    "蒙脱石散": "diosmectite",
    "消旋卡多曲": "racecadotril",
    "洛哌丁胺": "loperamide",
    "复方地芬诺酯": "diphenoxylate",
    "二甲硅油": "dimeticone",
    "西甲硅油": "simeticone",
    "活性炭": "activated charcoal",
    "碳酸镧": "lanthanum carbonate",
    "司维拉姆": "sevelamer",
    "复方α-酮酸": "keto acid",
    "酮酸": "keto acid",
    "非诺贝特": "fenofibrate",
    "吉非罗齐": "gemfibrozil",
    "苯扎贝特": "bezafibrate",
    "阿昔莫司": "acipimox",
    "依折麦布": "ezetimibe",
    "普罗布考": "probucol",
    "多烯酸乙酯": "ethyl polyenoate",
    "月见草油": "evening primrose oil",
    "考来烯胺": "colestyramine",
    "藻酸双酯钠": "propyl gallate",
    "羟乙基芦丁": "troxerutin",
    "肝浸膏": "liver extract",
    "肝浸": "liver extract",
    "垂体前叶": "anterior pituitary",
    "缩合葡萄糖": "condensed glucose",
    "右旋糖酐": "dextran",
    "聚明胶肽": "polygeline",
    "琥珀酰明胶": "succinylated gelatin",
    "人纤维蛋白粘合剂": "fibrin sealant",
    "医用": "medical",
    "生理盐水": "sodium chloride",
    "复方电解质": "electrolytes",
    "电解质": "electrolytes",
    "口服补液盐": "oral rehydration salts",
    "碘海醇": "iohexol",
    "碘帕醇": "iopamidol",
    "碘普罗胺": "iopromide",
    "碘美普尔": "iomeprol",
    "碘佛醇": "ioversol",
    "碘克沙醇": "iodixanol",
    "钆喷酸葡胺": "gadopentetic acid",
    "钆特酸葡胺": "gadoteric acid",
    "钆双胺": "gadodiamide",
    "六氟化硫": "sulfur hexafluoride",
    "声诺维": "sulfur hexafluoride",

    # --- 第二轮补漏：跑完一遍后按「没对上且行数多」的清单补的 ---
    "奥扎格雷": "ozagrel",
    "阿苯达唑": "albendazole",
    "氨基葡萄糖": "glucosamine",
    "右美托咪定": "dexmedetomidine",
    "甘草": "glycyrrhiza",
    "甘草酸单铵S": "glycyrrhizin",
    "甘草锌": "zinc glycyrrhizinate",
    "葡萄糖酸锌": "zinc gluconate",
    "茶碱麻黄碱": "theophylline",
    "愈创木酚": "guaiacol",
    "肌醇烟酸酯": "inositol nicotinate",
    "硫酸软骨素": "chondroitin sulfate",
    "利血平": "reserpine",
    "托法替布": "tofacitinib",
    "培美曲塞": "pemetrexed",
    "甲氯芬酯": "meclofenoxate",
    "吡硫醇": "pyritinol",
    "二氧丙嗪": "dioxopromethazine",
    "阿莫西林舒巴坦": "amoxicillin",
    "哌拉西林舒巴坦": "piperacillin",
    "替卡西林克拉维酸": "ticarcillin",
    "尼可刹米": "nikethamide",
    "乌拉地尔": "urapidil",
    "多巴酚丁胺": "dobutamine",
    "多巴胺": "dopamine",
    "酚妥拉明": "phentolamine",
    "羟甲香豆素": "hymecromone",
    "核黄素": "riboflavin",
    "尿素维E": "urea",
    "度米芬": "domiphen",
    "岩白菜素": "bergenin",
    "氨氯地平阿托伐他汀": "amlodipine",
    "地巴唑": "bendazol",
    "地芬尼多": "difenidol",
    "舒他西林": "sultamicillin",
    "维D2磷酸氢钙": "calcium phosphate",
    "赖氨酸磷酸氢钙": "lysine",
    "甲硫氨酸维B1": "methionine",
    "促肝细胞生长素": "hepatocyte growth factor",
    "炎琥宁": "potassium dehydroandrographolide succinate",
    "穿琥宁": "potassium dehydroandrographolide succinate",
    "细辛脑": "asarone",
    "鱼腥草素": "houttuynin",
    "莪术油": "zedoary oil",
    "西地碘": "iodophor",
    "肠内营养": "enteral nutrition",
    # 复方：按主成分挂（product_component 只放一个主成分，其余看 product.note）
    "双唑泰": "metronidazole",
    "曲咪新": "triamcinolone",
    "三合钙": "calcium carbonate",
    "维U颠茄铝": "aluminum hydroxide",
    "颠茄磺苄啶": "sulfamethoxazole",
    "赖氨葡锌": "zinc gluconate",
    "枸橼酸铁铵维B1糖浆Ⅱ": "ferric ammonium citrate",

    # --- 第三轮补漏：盐基剥掉以后是「裸名」，裸名本身也要能查到 ---
    "肾上腺素": "epinephrine",
    "去甲肾上腺素": "norepinephrine",
    "异丙肾上腺素": "isoprenaline",
    "酚苄明": "phenoxybenzamine",
    "西那卡塞": "cinacalcet",
    "阿普米司特": "apremilast",
    "甲苯磺丁脲": "tolbutamide",
    "哌嗪": "piperazine",
    "硝呋太尔": "nifuratel",
    "环吡酮胺": "ciclopirox",
    "溶菌酶": "lysozyme",
    "豆腐果苷": "helicid",
    "大蒜素": "allicin",
    "人白介素-2": "aldesleukin",
    "精蛋白人胰岛素混合": "insulin human",
    "替莫唑胺": "temozolomide",
    "维D2乳酸钙": "calcium lactate",
    "平衡盐": "balanced salt solution",
}


# ---------------------------------------------------------------------------
# 中文名剥离：剂型 / 限定词 / 盐基
# 逐级剥离，每一级都是候选名；查表时从最具体的写法往最一般的写法试，
# 所以 `氯化钠` 不会被剥成 `氯化`，而 `苯磺酸氨氯地平` 会剥到 `氨氯地平`。
# ---------------------------------------------------------------------------
FORM_TAILS = [
    # 剂型（长词优先，靠 sort 保证）
    "注射用无菌粉末", "无菌分装粉针剂", "小容量注射剂", "大容量注射剂", "冻干粉针剂",
    "注射用浓溶液", "口服混悬剂", "口服溶液剂", "干混悬剂", "薄膜衣片", "肠溶胶囊",
    "缓释胶囊", "控释胶囊", "口腔崩解片", "雾化吸入用", "雾化吸入", "吸入溶液",
    "吸入用", "气雾剂", "喷雾剂", "滴眼液", "滴耳液", "滴鼻液", "眼用凝胶",
    "眼膏剂", "乳胶剂", "凝胶剂", "洗剂", "搽剂", "涂剂", "酊剂", "栓剂",
    "散剂", "颗粒剂", "片剂", "胶囊剂", "注射剂", "溶液剂", "混悬剂", "糖浆剂",
    "乳膏剂", "软膏剂", "丸剂", "膜剂", "贴剂", "膏剂", "胶浆剂", "合剂",
    "含漱液", "含漱剂", "滴丸", "胶丸", "滴剂", "粉针剂", "冻干粉针", "粉雾剂",
    "口崩片", "分散片", "咀嚼片", "泡腾片", "缓释片", "控释片", "肠溶片",
    "舌下片", "含片", "薄膜片", "糖衣片", "注射液", "口服液",
    "口服溶液", "混悬液", "乳膏", "软膏", "凝胶", "眼膏", "贴膏", "贴片",
    "喷雾", "气雾", "糖浆", "搽剂", "酊", "栓", "散", "丸", "片", "膜", "膏",
    "锭", "胶", "液", "贴", "粉",
    "冻干粉", "阴道用", "阴道", "发用", "含漱", "冲剂", "煎膏", "胶剂",
    "曲剂", "糕剂",
    # 颗粒/胶囊：不带「剂」的写法在注册名称里更常见，漏了就等于整类产品不剥剂型
    "颗粒", "软胶囊", "胶囊", "泡腾颗粒", "乳剂", "涂膜剂", "洗液", "冲洗液",
    "灌注液", "滴眼剂", "眼用制剂", "滴耳剂", "滴鼻剂", "鼻喷剂", "鼻喷雾剂",
    "口腔喷雾剂", "含化片", "溶液", "乳状", "分散", "缓释", "控释", "肠溶",
]
FORM_TAILS = sorted(set(FORM_TAILS), key=len, reverse=True)

QUALIFIERS = sorted(
    # 注意：不要放「新」——`新霉素` 会被剥成 `霉素`
    ["复方", "小儿", "儿童", "婴儿", "注射用", "吸入用", "雾化吸入用", "特殊",
     "医用", "复方制剂", "重组"],
    key=len, reverse=True,
)

SALT_PREFIX = sorted(
    {
        "对甲苯磺酸", "苯磺酸", "甲苯磺酸", "甲磺酸", "门冬氨酸", "天冬氨酸",
        "葡萄糖酸", "枸橼酸", "柠檬酸", "酒石酸", "马来酸", "富马酸", "琥珀酸",
        "硬脂酸", "棕榈酸", "氢溴酸", "氢氯酸", "盐酸", "硫酸", "磷酸", "醋酸",
        "硝酸", "乳酸", "草酸", "谷氨酸", "溴化", "氯化", "碘化", "氟化",
        "亚硫酸", "硫酸氢", "托西酸", "双羟萘酸", "昔萘酸", "环丙酸", "丙酸",
        "戊酸", "苯乙酸", "二丙酸", "糠酸", "曲安西龙", "半琥珀酸", "甲硫酸",
    },
    key=len, reverse=True,
)

SALT_SUFFIX = sorted(
    {
        # 注射液里常见的「主药 + 氯化钠/葡萄糖」溶媒，不整体剥掉就永远对不上主药
        "氯化钠", "葡萄糖", "磷酸氢钙",
        "二钠", "三钠", "磷酸钠", "磷酸酯", "琥珀酸钠", "琥珀酸酯", "葡甲胺",
        "钠", "钾", "钙", "镁", "锌", "铁", "铵", "酯", "盐",
    },
    key=len, reverse=True,
)

RE_TRAIL_PAREN = re.compile(r"[\(（\[【][^\)）\]】]{0,24}[\)）\]】]\s*$")
RE_SPACES = re.compile(r"\s+")

# 剂量解析用：中文单位 → 英文单位（先长后短）
UNIT_ZH = [
    ("毫克", "mg"), ("微克", "mcg"), ("克", "g"), ("毫升", "ml"),
    ("升", "l"), ("万单位", "iu"), ("单位", "iu"),
]
RE_NUM_UNIT = re.compile(
    r"([\d]+(?:[.,]\d+)?)\s*(mg|mcg|ug|μg|g|ml|l|iu|%|万单位|万iu)", re.IGNORECASE)
RE_RATIO = re.compile(
    r"([\d]+(?:[.,]\d+)?)\s*(mg|mcg|ug|μg|g|ml|iu)\s*[:：]\s*([\d]+(?:[.,]\d+)?)"
    r"\s*(mg|mcg|ug|μg|g|ml|iu)?", re.IGNORECASE)
RE_PER_VOL = re.compile(
    r"([\d]+(?:[.,]\d+)?)\s*(mg|mcg|ug|μg|g|ml|iu)\s*/\s*([\d]+(?:[.,]\d+)?)\s*(ml|l)",
    re.IGNORECASE)
RE_NUM = re.compile(r"[\d]+(?:[.,]\d+)?")

# 剂型中→英：先翻成英文剂型词，再交给 ingest_openfda_ndc.form_base_of 归一化，
# 这样 form_base 与 US/GB 的 tablet / injection 等取值是同一套。
FORM_ZH_EN = [
    ("注射用", "injection"), ("注射", "injection"), ("输液", "injection"),
    ("滴眼", "drops"), ("滴耳", "drops"), ("滴鼻", "drops"), ("眼用", "drops"),
    ("片", "tablet"), ("丸", "pill"), ("胶囊", "capsule"), ("颗粒", "granule"),
    ("散", "powder"), ("干混悬", "powder"), ("乳膏", "cream"), ("软膏", "ointment"),
    ("凝胶", "gel"), ("栓", "suppository"), ("贴", "patch"), ("气雾", "aerosol"),
    ("喷雾", "spray"), ("吸入", "inhalation"), ("糖浆", "syrup"),
    ("口服液", "liquid"), ("口服溶液", "liquid"), ("溶液", "liquid"),
    ("混悬", "suspension"), ("洗剂", "lotion"), ("酊", "liquid"),
    ("搽剂", "lotion"), ("胶浆", "liquid"), ("膜", "patch"), ("煎膏", "paste"),
]


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def slug(text: str) -> str:
    """英文名 → substance_id 风格（与 ingest_openfda_ndc.slug 一致）。"""
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "unknown"


def cn_slug(text: str) -> str:
    """中文名 → 稳定 id。非 ASCII 一律哈希，不做伪拼音。"""
    raw = (text or "").strip()
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    if ascii_slug and raw.isascii():
        return ascii_slug
    return "cn-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def brand_of(raw: str) -> str:
    """商品名称：只有不是「无/无商品名/-」这类占位时才算真商品名。"""
    s = RE_SPACES.sub("", (raw or "").strip())
    return "" if s in BRAND_EMPTY else s


def strip_one_form(s: str) -> str:
    s2 = RE_TRAIL_PAREN.sub("", s).strip()
    if s2 != s:
        return s2
    for t in FORM_TAILS:
        if s.endswith(t) and len(s) > len(t) + 1:
            return s[: -len(t)].strip()
    return s


def strip_one_qualifier(s: str) -> str:
    for q in QUALIFIERS:
        if s.startswith(q) and len(s) > len(q) + 1:
            return s[len(q):].strip()
    return s


def strip_one_salt(s: str) -> str:
    for p in SALT_PREFIX:
        if s.startswith(p) and len(s) >= len(p) + 2:
            return s[len(p):].strip()
    for p in SALT_SUFFIX:
        if s.endswith(p) and len(s) >= len(p) + 2:
            return s[: -len(p)].strip()
    return s


def reduction_chain(name: str, depth: int = 8) -> list[str]:
    """从原写法开始，逐级生成剥离候选；越靠前越具体。"""
    seen = [name]
    frontier = [name]
    for _ in range(depth):
        nxt: list[str] = []
        for s in frontier:
            for t in (strip_one_form(s), strip_one_qualifier(s), strip_one_salt(s)):
                if t and t != s and len(t) >= 2 and t not in seen:
                    seen.append(t)
                    nxt.append(t)
        if not nxt:
            break
        frontier = nxt
    return seen


def translate_form(form_zh: str) -> str:
    """中文剂型 → 英文剂型词（给 form_base_of 用）。"""
    f = form_zh or ""
    for zh, en in FORM_ZH_EN:
        if zh in f:
            return en
    return f


def release_of(form_zh: str, name: str) -> str:
    """缓释/控释/肠溶 → ER/DR；其余 none。"""
    f = (form_zh or "") + " " + (name or "")
    if "控释" in f or "缓释" in f or "迟释" in f:
        return "ER"
    if "肠溶" in f:
        return "DR"
    if "速释" in f:
        return "IR"
    return "none"


def parse_strength(spec: str):
    """从「规格」里抠出强度。

    返回 (value, unit, per_volume_value, per_volume_unit, note)。
    抠不出就返回 None 强度（绝不抛异常）；比 `a mg:b mg` 只取第一个值，
    完整原文通过 note 带回去。
    """
    raw = (spec or "").strip()
    if not raw or raw in {"/", "复方", "适量", "-"}:
        return None, None, None, None, None

    s = unicodedata.normalize("NFKC", raw)
    s = s.replace("／", "/").replace("：", ":")
    for zh, en in UNIT_ZH:
        s = re.sub(r"(\d)\s*" + zh, r"\1" + en, s)

    ratio = RE_RATIO.search(s)
    if ratio:
        u1 = ratio.group(2).lower().replace("ug", "mcg").replace("μg", "mcg")
        u2 = (ratio.group(4) or "").lower().replace("ug", "mcg").replace("μg", "mcg")
        v1 = float(ratio.group(1).replace(",", "."))
        v2 = float(ratio.group(3).replace(",", "."))
        # 「100ml:0.9g」是浓度不是配比：主强度取右边的质量，左边的体积当分母
        if u1 == "ml" and u2 in ("mg", "mcg", "g", "iu"):
            return v2, u2, v1, "ml", raw
        return v1, u1, None, None, raw

    per_vol = RE_PER_VOL.search(s)
    if per_vol:
        val = float(per_vol.group(1).replace(",", "."))
        unit = per_vol.group(2).lower().replace("ug", "mcg").replace("μg", "mcg")
        pv = float(per_vol.group(3).replace(",", "."))
        pu = per_vol.group(4).lower()
        return val, unit, pv, pu, None

    m = RE_NUM_UNIT.search(s)
    if m:
        val = float(m.group(1).replace(",", "."))
        unit = m.group(2).lower().replace("ug", "mcg").replace("μg", "mcg")
        pv = pu = None
        # 「每毫升含…」这类写成浓度，但式子只有一个数值：补 1 ml 的分母
        if "每毫升" in s or "每ml" in s:
            pv, pu = 1.0, "ml"
        return val, unit, pv, pu, None

    return None, None, None, None, raw


def product_id_of(row: dict) -> str:
    """确定性的产品主键。

    只用「药品代码 + 规格 + 包装」会撞掉 29,190 行（同一代码下不同厂家共用规格包装），
    所以把批准文号与生产企业也放进指纹。8 位十六进制在本快照上没有哈希碰撞。
    """
    key = "|".join(
        (row.get(c) or "").strip()
        for c in ("规格", "包装材质", "最小包装数量", "最小包装单位", "批准文号", "药品企业")
    )
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    return f"CN-{row['药品代码'].strip()}-{h}"


def pack_of(row: dict) -> str | None:
    mat = (row.get("包装材质") or "").strip()
    qty = (row.get("最小包装数量") or "").strip()
    dose_unit = (row.get("最小制剂单位") or "").strip()
    pack_unit = (row.get("最小包装单位") or "").strip()
    if not (mat or qty):
        return None
    amount = f"{qty}{dose_unit}" if dose_unit else qty
    if pack_unit:
        amount = f"{amount}/{pack_unit}"
    return f"{mat}，{amount}".strip("，") if amount else mat


def canonical_name(name: str) -> str:
    """CN 专属成分用哪个写法当名字：只剥剂型/限定词后最短的候选（≥2 字）。

    不参与盐基剥离，避免 `硫酸亚铁片` 收敛成 `亚铁片` 这种残片；
    `炎琥宁注射液` 与 `注射用炎琥宁` 仍会收敛到 `炎琥宁`，不会各建一个伪成分。
    """
    seen = [name]
    frontier = [name]
    for _ in range(6):
        nxt: list[str] = []
        for s in frontier:
            for t in (strip_one_form(s), strip_one_qualifier(s)):
                if t and t != s and len(t) >= 2 and t not in seen:
                    seen.append(t)
                    nxt.append(t)
        if not nxt:
            break
        frontier = nxt
    return min(seen, key=len) if seen else name


RE_ATC4 = re.compile(r"^[A-Z][0-9]{2}[A-Z]{2}$")


# ---------------------------------------------------------------------------
# 中文名 → substance_id
# ---------------------------------------------------------------------------
class Mapper:
    """逐级降级地把中文通用名落到成分上，并登记新建的成分。"""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        self.en_to_sid: dict[str, str] = {}
        self.zh_to_sid: dict[str, str] = {}
        self.atc4_index: dict[str, set[str]] = defaultdict(set)
        self.known_sids: set[str] = set()
        for sid, inn_en, inn_zh, atc, atc_name, drug_class in db.execute(
                "SELECT substance_id, inn_en, inn_zh, atc, atc_name, drug_class"
                " FROM substance"):
            mine = drug_class in (UNMAPPED_CLASS, NEW_EN_CLASS)
            self.known_sids.add(sid)
            self.en_to_sid.setdefault((inn_en or "").strip().lower(), sid)
            # 中文名精确匹配只认「别的市场本来就有的中文名」（人工种子的 9 条）。
            # 自己上一轮建的伪成分不进这个索引：否则重跑时它的中文 inn_zh 会把
            # 本该走 ATC-4 / 新建的行吸走，两次跑的映射就不一致了。
            if inn_zh and inn_zh.strip() and not mine:
                self.zh_to_sid.setdefault(inn_zh.strip(), sid)
            # ATC-4 反查的候选池必须「跑多少次都一样」，否则第二次跑的时候，
            # 上一轮写进去的 5 位 ATC-4 会让某些前缀从唯一变成多个，映射整片漂移：
            #   - 本次/历次新建的 CN 伪成分（drug_class 有标记）不参与；
            #   - 5 位 ATC 只收「带 atc_name」的（ES/CIMA 带名字给的），
            #     本导入器回填的 ATC-4 不带名字，自动被排除；
            #   - 7 位 ATC-5 照收，那是其它市场本来就有的。
            if (atc and len(atc) >= 5
                    and drug_class not in (UNMAPPED_CLASS, NEW_EN_CLASS)
                    and (len(atc) >= 7 or (atc_name or "").strip())):
                self.atc4_index[atc[:5].upper()].add(sid)
        self.cache: dict[tuple[str, str | None], tuple[str, str, str | None, str]] = {}
        self.created: dict[str, dict] = {}
        self.pre_existing: set[str] = set(self.known_sids)
        self.atc_meta: dict[str, tuple[str, str]] = {
            sid: (atc, atc_name or "")
            for sid, atc, atc_name in db.execute(
                "SELECT substance_id, atc, atc_name FROM substance"
                " WHERE atc IS NOT NULL AND atc <> ''")
        }
        self.sid_inn: dict[str, str] = {
            sid: inn or ""
            for sid, inn in db.execute("SELECT substance_id, inn_en FROM substance")
        }

    # -- 主入口 ---------------------------------------------------------
    def resolve(self, name: str, atc4: str | None) -> tuple[str, str, str | None, str]:
        """返回 (substance_id, tier, en_guess, canonical_zh)。"""
        key = (name, atc4)
        hit = self.cache.get(key)
        if hit is not None:
            return hit

        canon = canonical_name(name)
        en_guess: str | None = None
        sid: str | None = None
        tier = ""

        # (a) 已有成分的中文名；(b) 人工 CN→EN 表
        for cand in reduction_chain(name):
            known = self.zh_to_sid.get(cand)
            if known:
                sid, tier = known, "inn_zh"
                break
            en = CN2EN.get(cand) or self._prefix_hit(cand)
            if en:
                en_guess = en
                known = self.en_to_sid.get(en.lower())
                if known:
                    sid, tier = known, "table"
                break                 # 表命中就以表为准，不再往更剥离的写法找

        # (c) ATC-4 反查：只有唯一成分、且过得了安全闸时才算数
        if sid is None and atc4:
            sid = self.atc4_target(atc4, en_guess)
            if sid:
                tier = "atc4"

        # (d) 建 CN 专属成分
        if sid is None:
            if en_guess:
                sid, tier = self._create_en(en_guess, canon, atc4), "new_en"
            else:
                sid, tier = self._create_cn(canon, atc4), "new_cn"

        out = (sid, tier, en_guess, canon)
        self.cache[key] = out
        return out

    # -- 复方名的「主成分前缀」 -----------------------------------------
    @staticmethod
    def _prefix_hit(cand: str) -> str | None:
        """`庆大霉素普鲁卡因维B12颗粒` 这类复方：取最长的已知成分前缀。

        只认长度 ≥4 的表键——`烟酸`（2 字）这类短键不去猜，
        否则 `烟酸占替诺` 会被误认成烟酸。
        """
        for k in range(len(cand) - 1, 3, -1):
            en = CN2EN.get(cand[:k])
            if en:
                return en
        return None

    # -- ATC-4 反查的安全闸 ---------------------------------------------
    def atc4_target(self, atc4: str, en_guess: str | None) -> str | None:
        """ATC-4 只有一个成分时返回它，否则 None。

        两道闸（都是为了不把「同类药」当成「同一个药」）：
        1. 「其它…」兜底类目不算：ATC 第 4 级以 X 结尾（A10XX / L01CX / V01BX…）
           或类目名以 Otros/Other 开头的，是「本类其它药」的筐，单成分命中毫无意义
           —— 没有这两道闸，硫辛酸会被安到 teplizumab 头上。
        2. 人工表已经知道英文名时，只接受名字相近的候选（西班牙语拼写差异如
           mannitol/manitol、suxamethonium/suxametonio 能过；aminoglycoside 里
           的 micronomicin/amikacin 过不去，于是宁可新建 micronomicin）。
        """
        pool = self.atc4_index.get(atc4)
        if not pool or len(pool) != 1:
            return None
        sid = next(iter(pool))
        atc, atc_name = self.atc_meta.get(sid, ("", ""))
        # 「其它…」兜底类目：ATC 第 4 级以 X 结尾（A10XX / L01CX / V09FX / N01BX…）
        # 或类目名以 Otros/Other 开头的，本质是「本类其它药」的筐。
        if atc4.upper().endswith("X"):
            return None
        if len(atc) == 5 and atc_name.strip().lower().startswith(("otros", "other")):
            return None
        if en_guess:
            other = self.sid_inn.get(sid, "")
            ratio = difflib.SequenceMatcher(
                None, en_guess.lower(), other.lower()).ratio()
            if ratio < 0.80:
                return None
        return sid

    # -- 新建成分 -------------------------------------------------------
    def _insert(self, sid: str, inn_en: str, inn_zh: str, atc: str | None,
                drug_class: str) -> str:
        existing = self.en_to_sid.get(inn_en.strip().lower())
        if existing:
            return existing
        base_sid = sid
        if sid in self.known_sids:
            # 极少数情况：slug 撞了但没有同名 inn_en，加哈希后缀区分
            sid = f"{base_sid}-{hashlib.sha1(inn_zh.encode('utf-8')).hexdigest()[:6]}"
        self.db.execute(
            "INSERT OR IGNORE INTO substance (substance_id, inn_en, inn_zh, atc, drug_class)"
            " VALUES (?,?,?,?,?)",
            (sid, inn_en, inn_zh, atc, drug_class),
        )
        self.known_sids.add(sid)
        self.en_to_sid[inn_en.strip().lower()] = sid
        # 刻意不登记到 zh_to_sid：本次新建的成分不该冒充「库里已有的中文名命中」，
        # 否则同一成分的后续行会把 tier 统计洗成 inn_zh。
        self.created[sid] = {"inn_en": inn_en, "inn_zh": inn_zh, "atc": atc,
                             "drug_class": drug_class}
        return sid

    def _create_en(self, en: str, zh: str, atc4: str | None) -> str:
        """中文名能给英文 INN，但库里还没有这个成分：用英文名建，方便以后并库。"""
        return self._insert(slug(en), en.title(), zh, atc4, NEW_EN_CLASS)

    def _create_cn(self, zh: str, atc4: str | None) -> str:
        """只知道中文名：建 cn-<hash>，标 unmapped-cn 等人工映射。"""
        return self._insert(cn_slug(zh), zh, zh, atc4, UNMAPPED_CLASS)


# ---------------------------------------------------------------------------
# 入库
# ---------------------------------------------------------------------------
REQUIRED_TABLES = (
    "product", "product_component", "substance", "variant",
    "name_key", "name_variant", "product_name", "source", "ingest_run",
)


def ensure_source(db: sqlite3.Connection, now: str) -> None:
    db.execute(
        "INSERT OR REPLACE INTO source (source_id, name, url, license, license_url,"
        " retrieved_at, notes) VALUES (?,?,?,?,?,?,?)",
        (SOURCE_ID, "国家医保局 医保药品分类与代码数据库", SOURCE_URL,
         "国家医保局公开数据（未标注开放许可，按公开数据引用）", None, SNAPSHOT,
         f"2024-01-05 快照（CSV 234,370 行，UTF-8）；同一批数据的 PDF 版共 19,531 页。"
         f"解析入库于 {now}；一行 = 一个厂家的一个包装。"),
    )


def fmt(n: int) -> str:
    return f"{n:,}"


def print_coverage(db: sqlite3.Connection) -> None:
    print("\n-- coverage --")
    print(f"{'country':<8}{'products':>11}{'variants':>10}{'active':>11}  last_synced")
    for country, n_products, n_variants, n_active, last in db.execute(
            "SELECT country, n_products, n_variants, n_active, last_synced"
            " FROM coverage ORDER BY country"):
        print(f"{country:<8}{n_products:>11,}{n_variants:>10,}{n_active:>11,}  {last}")


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="ingest_nhsa.py",
        description="国家医保局 医保药品分类与代码数据库（2024-01-05 快照）→ SQLite。"
                    "只增不删：按主键 INSERT OR REPLACE / INSERT OR IGNORE，可反复执行。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "范围说明：\n"
            "  药品代码 X 开头 = 化学药（135,667 行），默认只吃这一类。\n"
            "         代码 = X + ATC-4(5 位) + 4 位序号 + 4 位剂型/包装码，所以\n"
            "         ATC-4 只能取到第 4 级，不能当完整 ATC 用。\n"
            "  药品代码 Z 开头 = 中成药（98,703 行）。整批里只有 42 行带真实商品名，\n"
            "         也没有英文成分可对，全量进来会多出约 8,300 个伪成分，\n"
            "         把碰撞库和检索一起稀释掉。所以默认 OFF，需要时显式 --include-tcm。\n"
        ),
    )
    ap.add_argument("--csv", default=str(RAW), help="快照 CSV 路径")
    ap.add_argument("--db", default=str(DB), help="目标库（开发时可指向副本，勿指向正式库）")
    ap.add_argument("--include-tcm", action="store_true",
                    help="同时吃 Z 开头的中成药：98,703 行里只有 42 行有真实商品名，"
                         "会新增约 8,300 个只有中文名的伪成分（默认关闭）")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 行（验证用）")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"找不到快照 {csv_path}")
    now = date.today().isoformat()
    db = sqlite3.connect(args.db, timeout=120)
    db.execute("PRAGMA busy_timeout = 60000")
    for t in REQUIRED_TABLES:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                          (t,)).fetchone():
            raise SystemExit(f"库里缺少表 {t}；先建库（本脚本不负责建表，避免动 schema）")
    ensure_source(db, now)
    db.commit()

    mapper = Mapper(db)
    print(f"库里已有成分 {fmt(len(mapper.known_sids))}，其中带 ATC 的 "
          f"{fmt(sum(len(v) for v in mapper.atc4_index.values()))}；"
          f"CN→EN 表 {fmt(len(CN2EN))} 条")

    counters: Counter = Counter()
    tier_rows: Counter = Counter()
    tier_sids: dict[str, set[str]] = defaultdict(set)
    bucket_rows: Counter = Counter()
    bucket_sids: dict[str, set[str]] = defaultdict(set)
    unmapped_rows: Counter = Counter()
    unmapped_en: dict[str, str] = {}
    new_by_tier: dict[str, set[str]] = defaultdict(set)

    seen_keys: set[str] = set()
    seen_variants: set[tuple[str, str]] = set()
    variant_ok: set[str] = set()
    atc_filled: set[str] = set()

    def register_name(pid: str, raw: str, ntype: str, primary: int) -> None:
        n = normalize(raw)
        if n.is_empty:
            return
        key = n.norm
        if key not in seen_keys:
            seen_keys.add(key)
            db.execute(
                "INSERT OR IGNORE INTO name_key (key_id, norm, compact, script)"
                " VALUES (?,?,?,?)", (key, key, n.compact, n.script))
        if (key, raw) not in seen_variants:
            seen_variants.add((key, raw))
            db.execute(
                "INSERT OR IGNORE INTO name_variant (key_id, raw, source_id)"
                " VALUES (?,?,?)", (key, raw, SOURCE_ID))
        db.execute(
            "INSERT OR IGNORE INTO product_name (product_id, key_id, name_type, is_primary)"
            " VALUES (?,?,?,?)", (pid, key, ntype, primary))

    seen_pids: set[str] = set()

    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            counters["rows_csv"] += 1
            code = (row.get("药品代码") or "").strip()
            kind = code[:1]
            if kind not in ("X", "Z"):
                counters["skip_code"] += 1
                continue
            if kind == "Z" and not args.include_tcm:
                counters["skip_tcm"] += 1
                continue
            if args.limit and counters["in_scope"] >= args.limit:
                break
            counters["in_scope"] += 1

            name = (row.get("注册名称") or "").strip()
            if not name:
                counters["skip_noname"] += 1
                continue

            atc4 = None
            if kind == "X":
                cand = code[1:6].upper()
                if RE_ATC4.match(cand):
                    atc4 = cand
                else:
                    counters["bad_atc4"] += 1

            pid = product_id_of(row)
            if pid in seen_pids:
                counters["dup_product"] += 1
                continue
            seen_pids.add(pid)

            sid, tier, en_guess, canon = mapper.resolve(name, atc4)
            tier_rows[tier] += 1
            tier_sids[tier].add(sid)
            # 三个落点：已有成分（查名）· 已有成分（ATC-4 反查）· 本次新建
            if tier == "atc4":
                bucket = "atc4"
            elif sid in mapper.pre_existing:
                bucket = "existing"
            else:
                bucket = "created"
            bucket_rows[bucket] += 1
            bucket_sids[bucket].add(sid)
            if tier in ("new_en", "new_cn"):
                new_by_tier[tier].add(sid)
                unmapped_rows[name] += 1
                if en_guess:
                    unmapped_en[name] = en_guess

            # --- 成分 / 变体 ---
            if sid not in variant_ok:
                variant_ok.add(sid)
                db.execute("INSERT OR IGNORE INTO variant (variant_id, substance_id)"
                           " VALUES (?,?)", (sid, sid))
            if atc4 and sid not in atc_filled:
                atc_filled.add(sid)
                db.execute("UPDATE substance SET atc = ? WHERE substance_id = ?"
                           " AND (atc IS NULL OR atc = '')", (atc4, sid))

            # --- 产品 ---
            dosage_form = ((row.get("注册剂型") or "").strip()
                           or (row.get("剂型") or "").strip() or "unknown")
            form_base = form_base_of(translate_form(dosage_form))
            release = release_of(dosage_form, name)
            brand = brand_of(row.get("商品名称"))
            val, unit, pv, pu, lossy = parse_strength(row.get("规格"))
            note_parts = [(row.get("甲乙类") or "").strip(), (row.get("备注") or "").strip()]
            if lossy:
                note_parts.append(f"规格 {lossy}")
            note = " · ".join(p for p in note_parts if p) or None
            is_branded = int(bool(brand))

            db.execute(
                "INSERT OR REPLACE INTO product (product_id, country, dosage_form, form_base,"
                " route, release, pack, mah, approval_id, category, is_branded, status,"
                " status_date, source_id, source_url, retrieved_at, note)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, "CN", dosage_form, form_base, None, release, pack_of(row),
                 (row.get("药品企业") or "").strip() or None,
                 (row.get("批准文号") or "").strip() or None,
                 CAT_TCM if kind == "Z" else CAT_CHEM,
                 is_branded, "active", None, SOURCE_ID, SOURCE_URL, SNAPSHOT, note),
            )
            db.execute(
                "INSERT OR REPLACE INTO product_component (product_id, ord, variant_id,"
                " strength_value, strength_unit, per_volume_value, per_volume_unit)"
                " VALUES (?,?,?,?,?,?,?)",
                (pid, 0, sid, val, unit, pv, pu),
            )

            # --- 名字 ---
            register_name(pid, name, "inn", 0)
            if brand:
                bn = normalize(brand)
                ntype = "inn" if bn.norm and bn.norm == normalize(name).norm else "trade"
                register_name(pid, brand, ntype, 1)

            counters["products"] += 1
            if counters["products"] % 5000 == 0:
                db.commit()
                print(f"  ... {fmt(counters['products'])} products", flush=True)

    # --- run 记录 ---
    kept = counters["products"]
    rejected = (counters["skip_code"] + counters["skip_noname"]
                + counters["dup_product"] + counters["skip_tcm"])
    summary = {
        "rows_csv": counters["rows_csv"],
        "in_scope": counters["in_scope"],
        "products": kept,
        "dup_product": counters["dup_product"],
        "skip_tcm": counters["skip_tcm"],
        "skip_noname": counters["skip_noname"],
        "bad_atc4": counters["bad_atc4"],
        "tier_rows": dict(tier_rows),
        "created_substances": len(mapper.created),
    }
    db.execute(
        "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
        " rows_in, rows_kept, rows_rejected, status, note)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (f"{SOURCE_ID}-{SNAPSHOT}", SOURCE_ID, now, now,
         counters["rows_csv"], kept, rejected, "ok",
         json.dumps(summary, ensure_ascii=False)),
    )
    db.commit()

    # ------------------------------------------------------------------
    # 报告
    # ------------------------------------------------------------------
    print("\n== NHSA 中国 · 快照 %s ==" % SNAPSHOT)
    print(f"CSV 行数            : {fmt(counters['rows_csv'])}"
          f"（本次范围 {fmt(counters['in_scope'])} 行）")
    print(f"产品写入            : {fmt(kept)}")
    print(f"重复注册（同批文+厂家+包装，合并）: {fmt(counters['dup_product'])}")
    print(f"跳过的行            : 中成药 {fmt(counters['skip_tcm'])} · "
          f"无注册名称 {fmt(counters['skip_noname'])} · "
          f"代码类型异常 {fmt(counters['skip_code'])}")
    if counters["bad_atc4"]:
        print(f"ATC-4 不合法        : {fmt(counters['bad_atc4'])}（按无 ATC 处理）")

    print("\n-- 成分解析（行数 / 成分数）--")
    labels = {
        "inn_zh": "1. 中文名精确命中已有成分",
        "table": "2. 人工 CN→EN 表 → 已有英文成分",
        "atc4": "3. ATC-4 唯一反查",
        "new_en": "4a. 新建成分（表给了英文 INN，库里原来没有）",
        "new_cn": "4b. 新建 CN 专属成分（unmapped-cn）",
    }
    for tier in ("inn_zh", "table", "atc4", "new_en", "new_cn"):
        if not tier_rows[tier]:
            continue
        print(f"  {labels[tier]:<44} {fmt(tier_rows[tier]):>8} 行  "
              f"{fmt(len(tier_sids[tier])):>6} 个成分")

    created = len(mapper.created)
    print(f"\n落在已有英文成分上 : {fmt(bucket_rows['existing'])} 行  "
          f"（{fmt(len(bucket_sids['existing']))} 个成分）")
    print(f"ATC-4 反查命中     : {fmt(bucket_rows['atc4'])} 行  "
          f"（{fmt(len(bucket_sids['atc4']))} 个成分）")
    print(f"新建成分           : {fmt(created)} 个 / {fmt(bucket_rows['created'])} 行"
          f"（其中英文名已知 {fmt(len(new_by_tier['new_en']))}，"
          f"只有中文名 {fmt(len(new_by_tier['new_cn']))}）")
    print(f"补写 ATC-4 的成分 : {fmt(len(atc_filled))}")

    if unmapped_rows:
        print("\n-- 新建成分里行数最多的注册名称 Top 10 --")
        for i, (nm, n) in enumerate(unmapped_rows.most_common(10), 1):
            guess = unmapped_en.get(nm)
            tail = f"  →  guess {guess}" if guess else ""
            print(f"  {i:>2}. {fmt(n):>7} 行  {nm}{tail}")

    print_coverage(db)
    db.close()


if __name__ == "__main__":
    main()
