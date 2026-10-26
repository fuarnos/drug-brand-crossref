"""把美国街头叫法 / 民间叫法 / 类别俗称写入 drug_term。

数据源（都可公开再发布）：
  - NIDA, "Drugs A to Z"（美国国立药物滥用研究所，US Government work）
    https://nida.nih.gov/research-topics/drugs-a-to-z
  - DEA, "Slang Terms and Code Words"（DEA-HOU-DIR-022-18, 2018）
    https://archive.org/details/dea-drug-slang-terms-and-code-words-july2018
    Public Domain Mark 1.0

为什么不用 nickname 表：
  nickname.substance_id 是 NOT NULL，只适合「一个叫法 → 一个成分」。
  街头叫法里有三类例外，硬塞会撒谎：
    1. 类别词：downers = 镇静剂，不是某一个成分；
    2. 本库没有上市产品的管制物质：molly = MDMA；
    3. 复方：lean = 可待因 + 异丙嗪。
  所以单独一张 drug_term，允许 substance_id 为空；两表由 alias_all 视图统一。

运行：
    python etl/ingest_us_terms.py --dry-run   # 只看会写什么
    python etl/ingest_us_terms.py             # 写入 data/drugs.db
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from normalize_name import normalize  # noqa: E402

DB = ROOT / "data" / "drugs.db"
NIDA_SNAPSHOT = ROOT / "data" / "raw" / "nida" / "drugs-a-to-z.md"
NIDA_URL = "https://nida.nih.gov/research-topics/drugs-a-to-z"
DEA_URL = ("https://archive.org/details/"
           "dea-drug-slang-terms-and-code-words-july2018")

# --- NIDA 条目的指向 -------------------------------------------------------
# 有上市产品的具体成分：heading -> (substance_id 列表, 中文名, 英文名)
NIDA_SPECIFIC = {
    "Cocaine": (["cocaine"], "可卡因", "Cocaine"),
    "Codeine": (["codeine"], "可待因", "Codeine"),
    "Dextromethorphan": (["dextromethorphan"], "右美沙芬", "Dextromethorphan"),
    "Fentanyl": (["fentanyl"], "芬太尼", "Fentanyl"),
    "Flunitrazepam": (["flunitrazepam"], "氟硝西泮", "Flunitrazepam"),
    "Hydrocodone": (["hydrocodone-bitartrate"], "氢可酮", "Hydrocodone"),
    "Hydromorphone": (["hydromorphone"], "氢吗啡酮", "Hydromorphone"),
    "Ketamine": (["ketamine"], "氯胺酮", "Ketamine"),
    "Methamphetamine": (["methamphetamine"], "甲基苯丙胺", "Methamphetamine"),
    "Methylphenidate": (["methylphenidate"], "哌甲酯", "Methylphenidate"),
    "Morphine": (["morphine"], "吗啡", "Morphine"),
    "Oxycodone": (["oxycodone"], "羟考酮", "Oxycodone"),
}

# 类别词：heading -> (中文类别名, 英文类别名, 说明, 举例 substance_id)
NIDA_CLASS = {
    "Amphetamines": (
        "苯丙胺类", "Amphetamines",
        "苯丙胺类中枢兴奋剂，常见成分包括苯丙胺、甲基苯丙胺。",
        ["amphetamine", "methamphetamine"]),
    "Anabolic Steroids": (
        "合成代谢类固醇", "Anabolic steroids",
        "合成代谢类固醇，常见包括睾酮、南诺龙、羟甲烯龙、美雄酮。",
        ["testosterone", "nandrolone", "oxandrolone", "oxymetholone"]),
    "Barbiturates": (
        "巴比妥类", "Barbiturates",
        "巴比妥类镇静催眠药，常见包括苯巴比妥、司可巴比妥、戊巴比妥。",
        ["phenobarbital", "secobarbital", "pentobarbital"]),
    "Benzodiazepines": (
        "苯二氮䓬类", "Benzodiazepines",
        "苯二氮䓬类镇静抗焦虑药，常见包括阿普唑仑、地西泮、劳拉西泮、氯硝西泮。",
        ["alprazolam", "diazepam", "lorazepam", "clonazepam"]),
    "Depressants": (
        "中枢抑制剂", "Depressants",
        "中枢抑制剂/镇静剂，包括巴比妥类、苯二氮䓬类、GHB、非苯二氮䓬类安眠药等。",
        ["diazepam", "zolpidem"]),
    "Opioids": (
        "阿片类", "Opioids",
        "阿片类镇痛药，常见包括羟考酮、氢可酮、吗啡、芬太尼、可待因。",
        ["oxycodone", "hydrocodone-bitartrate", "morphine", "fentanyl", "codeine"]),
    "Sleep Medications": (
        "非苯二氮䓬类安眠药", "Non-benzodiazepine sleep medications",
        "非苯二氮䓬类安眠药（Z 药），如唑吡坦、艾司佐匹克隆、扎来普隆。",
        ["zolpidem", "eszopiclone", "zaleplon"]),
    "Stimulants": (
        "中枢兴奋剂", "Stimulants",
        "中枢兴奋剂，包括苯丙胺类、可卡因、哌甲酯等。",
        ["amphetamine", "methamphetamine", "cocaine", "methylphenidate"]),
    "Synthetic Cannabinoids": (
        "合成大麻素", "Synthetic cannabinoids",
        "合成大麻素，常喷在植物碎屑上吸食；不是大麻。",
        []),
    "Synthetic Cathinones": (
        "合成卡西酮", "Synthetic cathinones",
        "合成卡西酮（常称 bath salts），不是浴盐。",
        []),
    "Aerosols": (
        "吸入剂", "Inhalants",
        "吸入剂（挥发性气体/气雾剂），不是某一种药。",
        []),
    "Gases": (
        "吸入剂", "Inhalants",
        "吸入剂（挥发性气体/气雾剂），不是某一种药。",
        []),
    "Inhalants": (
        "吸入剂", "Inhalants",
        "吸入剂（挥发性气体/气雾剂），不是某一种药。",
        []),
    "Nitrites": (
        "亚硝酸酯类", "Alkyl nitrites",
        "亚硝酸酯类（poppers），不是硝酸甘油等心血管药。",
        []),
}

# 本库没有上市产品（多为美国附表 I 管制物质）的具体指向
NIDA_UNMAPPED = {
    "Cannabis": ("大麻", "Cannabis",
                 "大麻（Cannabis），美国联邦附表 I；本库没有大麻花叶的上市药品记录。"),
    "Delta-8 THC": ("Δ-8-四氢大麻酚", "Delta-8 THC",
                    "Δ-8-四氢大麻酚，大麻中的致幻大麻素；本库无上市产品。"),
    "DMT": ("二甲基色胺", "DMT",
            "二甲基色胺，强效致幻剂；本库无上市产品。"),
    "GHB": ("γ-羟基丁酸", "GHB",
            "γ-羟基丁酸，中枢抑制剂；本库无上市产品。"),
    "Heroin": ("海洛因", "Heroin",
               "海洛因（二乙酰吗啡），阿片类；本库无上市产品。"),
    "Khat": ("阿拉伯茶", "Khat",
             "阿拉伯茶（Catha edulis），含卡西酮；本库无上市产品。"),
    "Kratom": ("卡痛叶", "Kratom",
               "卡痛叶（Mitragyna speciosa），含帽柱木碱；本库无上市产品。"),
    "LSD": ("麦角二乙胺", "LSD",
            "麦角二乙胺，致幻剂；本库无上市产品。"),
    "MDMA": ("亚甲二氧甲基苯丙胺", "MDMA",
             "亚甲二氧甲基苯丙胺（摇头丸），致幻/兴奋剂；本库无上市产品。"),
    "Mescaline": ("麦司卡林", "Mescaline",
                  "麦司卡林（佩约特仙人掌成分），致幻剂；本库无上市产品。"),
    "NBOMes": ("NBOMe 类致幻剂", "NBOMes",
               "NBOMe 类致幻剂；本库无上市产品。"),
    "PCP": ("苯环己哌啶", "PCP",
            "苯环己哌啶，分离性致幻剂；本库无上市产品。"),
    "Psilocybin": ("裸盖菇素", "Psilocybin",
                   "裸盖菇素（致幻蘑菇成分）；本库无上市产品。"),
    "Salvia": ("鼠尾草", "Salvia divinorum",
               "鼠尾草（Salvia divinorum），含 Salvinorin A；本库无上市产品。"),
    "Tianeptine": ("噻奈普汀", "Tianeptine",
                   "噻奈普汀，美国未批准的抗抑郁药；本库无上市产品。"),
}

# 逐个别名覆盖：同一个 heading 下并不是每个词都指向同一种东西。
# 值为 substance_id 列表，或 "class" 表示按类别词处理。
ALIAS_TARGETS = {
    ("Amphetamines", "Bennies"): ["amphetamine"],
    ("Amphetamines", "Black Beauties"): ["amphetamine"],
    ("Amphetamines", "Speed"): ["amphetamine", "methamphetamine"],
    ("Amphetamines", "Uppers"): "class",
    ("Barbiturates", "Phenobarbital"): ["phenobarbital"],
    ("Codeine", "Lean"): ["codeine", "promethazine"],
    ("Dextromethorphan", "Skittles"): ["dextromethorphan", "methylphenidate"],
    ("Hydrocodone", "Norco"): ["hydrocodone-bitartrate", "acetaminophen"],
    ("Hydrocodone", "Vic"): ["hydrocodone-bitartrate", "acetaminophen"],
    ("Hydrocodone", "Vikes"): ["hydrocodone-bitartrate", "acetaminophen"],
    ("Hydrocodone", "Watsons"): ["hydrocodone-bitartrate", "acetaminophen"],
    ("Hydrocodone", "357's"): ["hydrocodone-bitartrate", "acetaminophen"],
    ("Hydrocodone", "Hydro"): ["hydrocodone-bitartrate"],
    ("Hydrocodone", "Fluff"): ["hydrocodone-bitartrate"],
    ("Methylphenidate", "Skittles"): ["methylphenidate", "dextromethorphan"],
    ("Methylphenidate", "Smarties"): ["methylphenidate", "amphetamine"],
    ("Oxycodone", "30s"): ["oxycodone"],
    ("Oxycodone", "40s"): ["oxycodone"],
    ("Oxycodone", "Cotton"): ["oxycodone"],
    ("Oxycodone", "Greens"): ["oxycodone"],
    ("Oxycodone", "Hillbilly Heroin"): ["oxycodone"],
    ("Oxycodone", "Killers"): ["oxycodone"],
    ("Oxycodone", "OC"): ["oxycodone"],
    ("Oxycodone", "Oxy"): ["oxycodone"],
    ("Oxycodone", "Roxy"): ["oxycodone"],
}

# 入口页里用 "See [X]" 的别名；NIDA 正文没有把它们放进 Also called。
SEE_ALIASES = {
    "Rohypnol": "Flunitrazepam",
    "Crystal Meth": "Methamphetamine",
    "Magic Mushrooms": "Psilocybin",
    "Coke": "Cocaine",
    "Crack": "Cocaine",
    "Ecstasy": "MDMA",
    "Acid": "LSD",
    "Angel Dust": "PCP",
    "Bath Salts": "Synthetic Cathinones",
    "Flakka": "Synthetic Cathinones",
    "Juice": "Anabolic Steroids",
    "DXM": "Dextromethorphan",
    "Benzos": "Benzodiazepines",
}

# --- DEA 补充：NIDA 没列、但美国处方药街头叫法里常见的 --------------------
# (term, targets, 中文指向, 英文指向, 说明)
DEA_SUPPLEMENT = [
    ("Bars", ["alprazolam"], "阿普唑仑", "Alprazolam",
     "阿普唑仑片，常指 2 mg 条状片。"),
    ("Xanies", ["alprazolam"], "阿普唑仑", "Alprazolam", "阿普唑仑的常见拼写变体。"),
    ("Zannies", ["alprazolam"], "阿普唑仑", "Alprazolam", "阿普唑仑的常见拼写变体。"),
    ("Footballs", ["alprazolam"], "阿普唑仑", "Alprazolam",
     "按 0.5 mg 椭圆形片外观得名。"),
    ("School Bus", ["alprazolam"], "阿普唑仑", "Alprazolam",
     "按 2 mg 黄色长条片外观得名。"),
    ("Upjohns", ["alprazolam"], "阿普唑仑", "Alprazolam",
     "按原厂 Upjohn 标记得名。"),
    ("Yellow Boys", ["alprazolam"], "阿普唑仑", "Alprazolam",
     "按黄色片外观得名。"),
    ("L7", ["alprazolam"], "阿普唑仑", "Alprazolam", "按片剂印记得名。"),
    ("Sticks", ["alprazolam"], "阿普唑仑", "Alprazolam", "按条状片外观得名。"),
    ("Planks", ["alprazolam"], "阿普唑仑", "Alprazolam", "按条状片外观得名。"),
    ("K-Pin", ["clonazepam"], "氯硝西泮", "Clonazepam", "Klonopin 的缩写叫法。"),
    ("Super Valium", ["clonazepam"], "氯硝西泮", "Clonazepam",
     "误当成「更强的地西泮」，实际是氯硝西泮。"),
    ("Tranks", ["clonazepam"], "氯硝西泮", "Clonazepam", "tranquilizer 的缩写。"),
    ("Addy", ["amphetamine", "dextroamphetamine"], "阿得拉（复方苯丙胺）",
     "Adderall", "Adderall 的缩写叫法；复方含苯丙胺与右苯丙胺。"),
    ("A-Train", ["amphetamine", "dextroamphetamine"], "阿得拉（复方苯丙胺）",
     "Adderall", "Adderall 的街头叫法。"),
    ("Smart Pills", ["amphetamine", "dextroamphetamine"], "阿得拉（复方苯丙胺）",
     "Adderall", "按「聪明药」用途得名。"),
    ("Study Buddies", ["amphetamine", "dextroamphetamine", "methylphenidate"],
     "阿得拉 / 哌甲酯", "Adderall / methylphenidate", "学习用途的统称，可能指多种兴奋剂。"),
    ("Study Skittles", ["amphetamine", "dextroamphetamine"], "阿得拉（复方苯丙胺）",
     "Adderall", "Adderall 的街头叫法。"),
    ("Zing", ["amphetamine", "dextroamphetamine"], "阿得拉（复方苯丙胺）",
     "Adderall", "Adderall 的街头叫法。"),
    ("Subs", ["buprenorphine", "naloxone"], "丁丙诺啡/纳洛酮", "Buprenorphine/naloxone",
     "Suboxone 的缩写叫法。"),
    ("Sobos", ["buprenorphine", "naloxone"], "丁丙诺啡/纳洛酮", "Buprenorphine/naloxone",
     "Suboxone 的街头叫法。"),
    ("Bupe", ["buprenorphine"], "丁丙诺啡", "Buprenorphine", "buprenorphine 的缩写。"),
    ("Boxes", ["buprenorphine", "naloxone"], "丁丙诺啡/纳洛酮", "Buprenorphine/naloxone",
     "按 Suboxone 包装得名。"),
    ("Stop Signs", ["buprenorphine", "naloxone"], "丁丙诺啡/纳洛酮",
     "Buprenorphine/naloxone", "按含片形状得名。"),
    ("Stops", ["buprenorphine", "naloxone"], "丁丙诺啡/纳洛酮",
     "Buprenorphine/naloxone", "按含片形状得名。"),
    ("Vikes", ["hydrocodone-bitartrate", "acetaminophen"], "氢可酮/对乙酰氨基酚",
     "Hydrocodone/acetaminophen", "Vicodin 的缩写叫法。"),
    ("Veeks", ["hydrocodone-bitartrate", "acetaminophen"], "氢可酮/对乙酰氨基酚",
     "Hydrocodone/acetaminophen", "Vicodin 的变体拼写。"),
    ("Vies", ["hydrocodone-bitartrate", "acetaminophen"], "氢可酮/对乙酰氨基酚",
     "Hydrocodone/acetaminophen", "Vicodin 的变体拼写。"),
    ("Hydros", ["hydrocodone-bitartrate"], "氢可酮", "Hydrocodone",
     "hydrocodone 的缩写。"),
    ("Watsons", ["hydrocodone-bitartrate", "acetaminophen"], "氢可酮/对乙酰氨基酚",
     "Hydrocodone/acetaminophen", "按 Watson 药厂标记得名。"),
    ("357s", ["hydrocodone-bitartrate", "acetaminophen"], "氢可酮/对乙酰氨基酚",
     "Hydrocodone/acetaminophen", "按片剂印记 357 得名。"),
    ("Dillies", ["hydromorphone"], "氢吗啡酮", "Hydromorphone",
     "Dilaudid 的缩写叫法。"),
    ("K4", ["hydromorphone"], "氢吗啡酮", "Hydromorphone", "按片剂印记得名。"),
    ("Needle Candy", ["hydromorphone"], "氢吗啡酮", "Hydromorphone",
     "指注射用氢吗啡酮。"),
    ("OC", ["oxycodone"], "羟考酮", "Oxycodone", "OxyContin 的缩写。"),
    ("Oxy", ["oxycodone"], "羟考酮", "Oxycodone", "oxycodone 的缩写。"),
    ("Roxy", ["oxycodone"], "羟考酮", "Oxycodone", "Roxicodone 的缩写。"),
    ("Roxy Shorts", ["oxycodone"], "羟考酮", "Oxycodone", "Roxicodone 的街头叫法。"),
    ("Hillbilly Heroin", ["oxycodone"], "羟考酮", "Oxycodone",
     "按阿片类效果得名，不是海洛因。"),
    ("Killers", ["oxycodone"], "羟考酮", "Oxycodone", "按止痛效果得名。"),
    ("Greens", ["oxycodone"], "羟考酮", "Oxycodone", "按 15 mg 绿色片外观得名。"),
    ("Rittys", ["methylphenidate"], "哌甲酯", "Methylphenidate",
     "Ritalin 的缩写叫法。"),
    ("Vitamin R", ["methylphenidate"], "哌甲酯", "Methylphenidate",
     "Ritalin 的谐音叫法。"),
    ("Kiddie Coke", ["methylphenidate"], "哌甲酯", "Methylphenidate",
     "误当成「儿童可卡因」，实际是哌甲酯。"),
    ("MPH", ["methylphenidate"], "哌甲酯", "Methylphenidate",
     "methylphenidate 的缩写。"),
    ("R-Ball", ["methylphenidate"], "哌甲酯", "Methylphenidate",
     "Ritalin 的街头叫法。"),
    ("Pineapple", ["methylphenidate"], "哌甲酯", "Methylphenidate",
     "按片剂外观/地区叫法得名。"),
    ("Morph", ["morphine"], "吗啡", "Morphine", "morphine 的缩写。"),
    ("Miss Emma", ["morphine"], "吗啡", "Morphine", "morphine 的谐音叫法。"),
    ("Mister Blue", ["morphine"], "吗啡", "Morphine", "按蓝色片外观得名。"),
    ("Dreamer", ["morphine"], "吗啡", "Morphine", "按镇静效果得名。"),
    ("Fent", ["fentanyl"], "芬太尼", "Fentanyl", "fentanyl 的缩写。"),
    ("China White", ["fentanyl"], "芬太尼", "Fentanyl",
     "历史上也指高纯度海洛因；现在常指非法芬太尼。"),
    ("Apache", ["fentanyl"], "芬太尼", "Fentanyl", "非法芬太尼的街头品牌名。"),
    ("Dance Fever", ["fentanyl"], "芬太尼", "Fentanyl", "非法芬太尼的街头叫法。"),
    ("Jackpot", ["fentanyl"], "芬太尼", "Fentanyl", "非法芬太尼的街头叫法。"),
    ("Great Bear", ["fentanyl"], "芬太尼", "Fentanyl", "非法芬太尼的街头叫法。"),
    ("He-Man", ["fentanyl"], "芬太尼", "Fentanyl", "非法芬太尼的街头叫法。"),
    ("King Ivory", ["fentanyl"], "芬太尼", "Fentanyl", "非法芬太尼的街头叫法。"),
    ("Murder 8", ["fentanyl"], "芬太尼", "Fentanyl", "非法芬太尼的街头叫法。"),
    ("Tango and Cash", ["fentanyl"], "芬太尼", "Fentanyl", "非法芬太尼的街头叫法。"),
    ("Blow", ["cocaine"], "可卡因", "Cocaine", "可卡因的常见街头叫法。"),
    ("Yayo", ["cocaine"], "可卡因", "Cocaine", "西班牙语 yayo 的变体。"),
    ("Nose Candy", ["cocaine"], "可卡因", "Cocaine", "按鼻吸用法得名。"),
    ("White Girl", ["cocaine"], "可卡因", "Cocaine", "可卡因的街头叫法。"),
    ("Rock", ["cocaine"], "可卡因（快克）", "Crack cocaine", "指快克可卡因固体块。"),
    ("Crystal", ["methamphetamine"], "甲基苯丙胺", "Methamphetamine",
     "指甲基苯丙胺晶体。"),
    ("Ice", ["methamphetamine"], "甲基苯丙胺", "Methamphetamine",
     "指透明晶体状甲基苯丙胺。"),
    ("Tina", ["methamphetamine"], "甲基苯丙胺", "Methamphetamine",
     "甲基苯丙胺的街头叫法。"),
    ("Shabu", ["methamphetamine"], "甲基苯丙胺", "Methamphetamine",
     "东南亚对甲基苯丙胺的叫法。"),
    ("Yaba", ["methamphetamine"], "甲基苯丙胺", "Methamphetamine",
     "东南亚的甲基苯丙胺片。"),
    ("Glass", ["methamphetamine"], "甲基苯丙胺", "Methamphetamine",
     "指晶体状甲基苯丙胺。"),
    ("Special K", ["ketamine"], "氯胺酮", "Ketamine", "氯胺酮的常见街头叫法。"),
    ("Kit Kat", ["ketamine"], "氯胺酮", "Ketamine", "氯胺酮的街头叫法。"),
    ("Vitamin K", ["ketamine"], "氯胺酮", "Ketamine",
     "这里的 K 指 ketamine，不是维生素 K。"),
    ("Cat Valium", ["ketamine"], "氯胺酮", "Ketamine", "氯胺酮的街头叫法。"),
    ("Lean", ["codeine", "promethazine"], "可待因/异丙嗪", "Codeine/promethazine",
     "含可待因与异丙嗪的糖浆饮品，不是单一成分。"),
    ("Purple Drank", ["codeine", "promethazine"], "可待因/异丙嗪",
     "Codeine/promethazine", "含可待因与异丙嗪的糖浆饮品。"),
    ("Sizzurp", ["codeine", "promethazine"], "可待因/异丙嗪",
     "Codeine/promethazine", "含可待因与异丙嗪的糖浆饮品。"),
    ("Percs", ["oxycodone", "acetaminophen"], "羟考酮/对乙酰氨基酚",
     "Oxycodone/acetaminophen", "Percocet 的缩写叫法。"),
    ("Perks", ["oxycodone", "acetaminophen"], "羟考酮/对乙酰氨基酚",
     "Oxycodone/acetaminophen", "Percocet 的变体拼写。"),
]

SINGLE_LETTER_OK = {"k", "h", "g", "d"}

# 个别词在 NIDA 挂在某个具体类别下，但语义更宽；改挂到更准确的类别条目。
CLASS_OVERRIDE = {
    ("Benzodiazepines", "Downers"): "Depressants",
    ("Amphetamines", "Uppers"): "Stimulants",
}

# 类别条目里个别词指向具体成分时，用它补中文/英文显示名。
ZH_BY_SID = {
    "amphetamine": ("苯丙胺", "Amphetamine"),
    "methamphetamine": ("甲基苯丙胺", "Methamphetamine"),
    "phenobarbital": ("苯巴比妥", "Phenobarbital"),
    "codeine": ("可待因", "Codeine"),
    "promethazine": ("异丙嗪", "Promethazine"),
    "acetaminophen": ("对乙酰氨基酚", "Acetaminophen"),
    "hydrocodone-bitartrate": ("氢可酮", "Hydrocodone"),
    "dextromethorphan": ("右美沙芬", "Dextromethorphan"),
    "methylphenidate": ("哌甲酯", "Methylphenidate"),
    "oxycodone": ("羟考酮", "Oxycodone"),
    "clonazepam": ("氯硝西泮", "Clonazepam"),
    "alprazolam": ("阿普唑仑", "Alprazolam"),
    "buprenorphine": ("丁丙诺啡", "Buprenorphine"),
    "naloxone": ("纳洛酮", "Naloxone"),
    "fentanyl": ("芬太尼", "Fentanyl"),
    "cocaine": ("可卡因", "Cocaine"),
    "morphine": ("吗啡", "Morphine"),
    "hydromorphone": ("氢吗啡酮", "Hydromorphone"),
    "ketamine": ("氯胺酮", "Ketamine"),
    "dextroamphetamine": ("右苯丙胺", "Dextroamphetamine"),
}

# NIDA 的 Also called 里有两处把 "and" 当分隔符；不手工拆会把两个词粘成一个。
MANUAL_SPLITS = {
    "Ketum and Biak": ["Ketum", "Biak"],
    "Skooby Snax and Crazy Clown": ["Skooby Snax", "Crazy Clown"],
}


def parse_nida() -> list[dict]:
    """把 NIDA 快照拆成 [{title, aliases, see}]。"""
    text = NIDA_SNAPSHOT.read_text(encoding="utf-8")
    entries: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            title = re.sub(r"\s*\(non-benzodiazepine\)\s*$", "", m.group(1)).strip()
            cur = {"title": title, "aliases": [], "see": None}
            entries.append(cur)
            continue
        if not cur:
            continue
        m = re.match(r"\*\*Also called:\*\*\s*(.+?)\s*$", line)
        if m:
            raw = m.group(1).strip()
            # 逗号和分号是分隔符；"and" 不拆（Kibbles and Bits / Tango & Cash 是词组）。
            # 少数确实用 and 分隔的，在 MANUAL_SPLITS 里手工拆。
            parts: list[str] = []
            for x in re.split(r"[;,]", raw):
                x = x.strip()
                if not x:
                    continue
                parts.extend(MANUAL_SPLITS.get(x, [x]))
            cur["aliases"] = parts
            continue
        m = re.match(r"See\s+\[(.+?)\]", line)
        if m:
            cur["see"] = m.group(1).strip()
    return entries


def clean_term(term: str) -> str:
    t = term.strip().strip(".")
    t = re.sub(r"^and\s+", "", t, flags=re.I)
    t = t.replace(" & ", " and ")
    t = t.replace("25l", "25I")  # OCR：数字 1 被认成小写 l
    return t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all", action="store_true", help="dry-run 时打印全部候选行")
    args = ap.parse_args()

    db = sqlite3.connect(args.db, timeout=60)
    db.execute("PRAGMA foreign_keys = ON")
    existing = {r[0] for r in db.execute("SELECT substance_id FROM substance")}
    rows: list[dict] = []
    seen: set[tuple] = set()
    skipped: list[str] = []

    def add(term: str, term_type: str, sid: str | None,
            label_zh: str, label_en: str,
            meaning_zh: str | None, meaning_en: str | None,
            note: str, source_id: str, source_url: str,
            examples: list[str] | None = None) -> None:
        term = clean_term(term)
        n = normalize(term)
        if not n.norm:
            skipped.append(f"{term}（归一化后为空）")
            return
        if len(n.norm) < 2 and n.norm not in SINGLE_LETTER_OK:
            skipped.append(f"{term}（单字母，太容易误命中）")
            return
        if sid and sid not in existing:
            skipped.append(f"{term} → {sid}（库里没有这个成分）")
            return
        key = (n.norm, term_type, sid or "")
        if key in seen:
            return
        seen.add(key)
        rows.append({
            "term": term,
            "term_norm": n.norm,
            "term_type": term_type,
            "label_zh": label_zh,
            "label_en": label_en,
            "meaning_zh": meaning_zh,
            "meaning_en": meaning_en,
            "substance_id": sid,
            "examples": json.dumps(examples, ensure_ascii=False) if examples else None,
            "confidence": "documented",
            "source_id": source_id,
            "source_url": source_url,
            "note": note,
        })

    def add_heading(title: str, aliases: list[str]) -> None:
        spec = NIDA_SPECIFIC.get(title)
        cls = NIDA_CLASS.get(title)
        unm = NIDA_UNMAPPED.get(title)
        if not (spec or cls or unm):
            skipped.append(f"[{title}]（没有配置指向）")
            return
        for alias in aliases:
            override = ALIAS_TARGETS.get((title, alias))
            if override == "class":
                class_key = CLASS_OVERRIDE.get((title, alias), title)
                label_zh, label_en, meaning_zh, examples = NIDA_CLASS[class_key]
                add(alias, "class", None, label_zh, label_en, meaning_zh,
                    f"Street/class term for {label_en}.",
                    f"NIDA Drugs A to Z「{class_key}」类别条目；这是类别叫法，不是具体药名。",
                    "nida_slang", NIDA_URL, examples)
                continue
            if override:
                # 类别条目里的个别词（Bennies / Phenobarbital）其实指向具体成分。
                for sid in override:
                    zh, en = ZH_BY_SID.get(sid, (sid, sid))
                    add(alias, "street", sid, zh, en, None, None,
                        f"NIDA Drugs A to Z「{title}」条目；街头叫法，"
                        f"不等于包装上的商品名。",
                        "nida_slang", NIDA_URL)
                continue

            if spec:
                for sid in spec[0]:
                    add(alias, "street", sid, spec[1], spec[2], None, None,
                        f"NIDA Drugs A to Z「{title}」条目；街头叫法，"
                        f"不等于包装上的商品名。",
                        "nida_slang", NIDA_URL)
            elif unm:
                label_zh, label_en, meaning_zh = unm
                add(alias, "street", None, label_zh, label_en, meaning_zh,
                    f"Not a marketed medicine in this database: {label_en}.",
                    f"NIDA Drugs A to Z「{title}」条目；本库没有该成分的上市产品记录。",
                    "nida_slang", NIDA_URL)
            else:  # class
                class_key = CLASS_OVERRIDE.get((title, alias), title)
                label_zh, label_en, meaning_zh, examples = NIDA_CLASS[class_key]
                add(alias, "class", None, label_zh, label_en, meaning_zh,
                    f"Street/class term for {label_en}.",
                    f"NIDA Drugs A to Z「{class_key}」类别条目；这是类别叫法，不是具体药名。",
                    "nida_slang", NIDA_URL, examples)

    entries = parse_nida()
    for e in entries:
        if e["aliases"]:
            add_heading(e["title"], e["aliases"])

    # "See [X]" 入口别名：按目标 heading 的配置写，来源仍标 NIDA。
    by_title = {e["title"]: e for e in entries}
    for alias, target_title in SEE_ALIASES.items():
        target = by_title.get(target_title)
        if not target:
            skipped.append(f"{alias} → {target_title}（找不到目标条目）")
            continue
        # 只写这个别名本身，不重复目标条目的全部别名。
        add_heading(target_title, [alias])

    # DEA 补充
    for term, targets, label_zh, label_en, note in DEA_SUPPLEMENT:
        for sid in targets:
            add(term, "street", sid, label_zh, label_en, None, None,
                f"DEA Slang Terms and Code Words (2018) 补充；{note}",
                "dea_slang", DEA_URL)

    print(f"NIDA 条目 {len(entries)}；候选行 {len(rows)}；跳过 {len(skipped)}")
    if skipped:
        for s in skipped[:40]:
            print("  跳过", s)
        if len(skipped) > 40:
            print(f"  ... 另有 {len(skipped) - 40} 条")

    if args.dry_run:
        for r in (rows if args.all else rows[:30]):
            print(f"  {r['term']:22} {r['term_type']:6} "
                  f"{r['substance_id'] or '-':28} {r['label_zh']}")
        print(f"  ... 共 {len(rows)} 行")
        db.close()
        return

    today = date.today().isoformat()
    db.execute(
        """INSERT INTO source (source_id, name, url, license, license_url,
                               retrieved_at, notes)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT (source_id) DO UPDATE SET
               name=excluded.name, url=excluded.url, license=excluded.license,
               license_url=excluded.license_url, retrieved_at=excluded.retrieved_at,
               notes=excluded.notes""",
        ("nida_slang", "NIDA — Drugs A to Z (street names)",
         NIDA_URL, "US Government work (public domain)", None, today,
         "Also called 列表；只取文字事实，不转载页面。"))
    db.execute(
        """INSERT INTO source (source_id, name, url, license, license_url,
                               retrieved_at, notes)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT (source_id) DO UPDATE SET
               name=excluded.name, url=excluded.url, license=excluded.license,
               license_url=excluded.license_url, retrieved_at=excluded.retrieved_at,
               notes=excluded.notes""",
        ("dea_slang", "DEA — Slang Terms and Code Words (2018)",
         DEA_URL, "Public Domain Mark 1.0",
         "https://creativecommons.org/publicdomain/mark/1.0/", today,
         "DEA-HOU-DIR-022-18；只取与处方药/管制物质对应的词，不取度量、武器等条目。"))

    db.execute("DELETE FROM drug_term WHERE source_id IN ('nida_slang','dea_slang')")
    db.executemany(
        """INSERT INTO drug_term
           (term, term_norm, term_type, country, label_zh, label_en,
            meaning_en, meaning_zh, substance_id, examples, confidence,
            source_id, source_url, note, created_at)
           VALUES (:term, :term_norm, :term_type, 'US', :label_zh, :label_en,
                   :meaning_en, :meaning_zh, :substance_id, :examples, :confidence,
                   :source_id, :source_url, :note, :created_at)""",
        [{**r, "created_at": today} for r in rows],
    )
    db.commit()
    total = db.execute("SELECT COUNT(*) FROM drug_term").fetchone()[0]
    print(f"drug_term: 写入 {len(rows)} 行；表内共 {total} 行")
    db.close()


if __name__ == "__main__":
    main()
