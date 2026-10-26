"""俗称 / 网络别名 / 旧名种子：人工维护，指向活性成分。

为什么单独一张表、而不是写进 product_name：
    昵称不是商品名。它属于「人嘴里怎么叫」，不属于「包装上印了什么」。
    写进 product_name 会让 collision 视图把「两只青蛙」算成一个挂着几千个包装的
    商品名，也会生成一张毫无意义的同名页。所以 nickname 只做检索入口，
    命中后回到 substance，再由成分页给出各国商品名。

运行：python data/seed_nicknames.py
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from normalize_name import normalize  # noqa: E402

DB = ROOT / "data" / "drugs.db"
SCHEMA = ROOT / "db" / "schema.sql"

# kind: slang 网络俗称 · legacy 旧名/曾用名 · translit 音译 · abbrev 简称 · misnomer 常见误称
# confidence: user 用户提供 · community 民间通行 · documented 有文献/药典依据的旧名
ALIASES = [
    # --- 网络俗称 ---------------------------------------------------------
    dict(alias="两只青蛙", sid="metformin", zh="二甲双胍", kind="slang",
         confidence="user", source="用户提供（本站缘起）",
         note="「胍」与青蛙的「呱」同音，被叫成两只青蛙；指降糖药二甲双胍。"),
    dict(alias="伟哥", sid="sildenafil", zh="西地那非", kind="slang",
         confidence="community", source="中文网络通行叫法",
         note="原指万艾可（Viagra），后来泛指西地那非；不是官方名称。"),
    dict(alias="蓝色小药丸", sid="sildenafil", zh="西地那非", kind="slang",
         confidence="community", source="中文网络通行叫法",
         note="按外观得名，通常指西地那非；同类蓝色药片不止一种，需核对成分。"),

    # --- 中文旧名 / 曾用名 ------------------------------------------------
    dict(alias="安定", sid="diazepam", zh="地西泮", kind="legacy",
         confidence="documented", source="1980–2000 年代中文常用名",
         note="旧商品名/常用名，现通用名为地西泮。"),
    dict(alias="心得安", sid="propranolol", zh="普萘洛尔", kind="legacy",
         confidence="documented", source="中文旧版药名",
         note="现通用名为普萘洛尔。"),
    dict(alias="心痛定", sid="nifedipine", zh="硝苯地平", kind="legacy",
         confidence="documented", source="中文旧版药名",
         note="现通用名为硝苯地平。"),
    dict(alias="消心痛", sid="isosorbide-dinitrate", zh="硝酸异山梨酯", kind="legacy",
         confidence="documented", source="中文旧版药名",
         note="现通用名为硝酸异山梨酯。"),
    dict(alias="胃复安", sid="metoclopramide", zh="甲氧氯普胺", kind="legacy",
         confidence="documented", source="中文旧版药名",
         note="现通用名为甲氧氯普胺。"),
    dict(alias="氟哌酸", sid="norfloxacin", zh="诺氟沙星", kind="legacy",
         confidence="documented", source="中文旧版药名",
         note="现通用名为诺氟沙星。"),
    dict(alias="病毒灵", sid="moroxydine", zh="吗啉胍", kind="legacy",
         confidence="documented", source="中文旧版药名",
         note="现通用名为吗啉胍。"),
    dict(alias="病毒唑", sid="ribavirin", zh="利巴韦林", kind="legacy",
         confidence="documented", source="中文旧版药名",
         note="现通用名为利巴韦林。"),
    dict(alias="痢特灵", sid="furazolidone", zh="呋喃唑酮", kind="legacy",
         confidence="documented", source="中文旧版药名",
         note="现通用名为呋喃唑酮。"),
    dict(alias="灭滴灵", sid="metronidazole", zh="甲硝唑", kind="legacy",
         confidence="documented", source="中文旧版药名",
         note="现通用名为甲硝唑。"),
    dict(alias="强的松", sid="prednisone", zh="泼尼松", kind="legacy",
         confidence="documented", source="中文旧版药名",
         note="现通用名为泼尼松。"),
    dict(alias="杜冷丁", sid="pethidine", zh="哌替啶", kind="legacy",
         confidence="documented", source="中文旧版药名（音译）",
         note="现通用名为哌替啶，英文 pethidine / meperidine。"),
    dict(alias="鲁米那", sid="phenobarbital", zh="苯巴比妥", kind="legacy",
         confidence="documented", source="Luminal 的音译旧名",
         note="旧商品名，现通用名为苯巴比妥。"),
    dict(alias="甲氰咪胍", sid="cimetidine", zh="西咪替丁", kind="legacy",
         confidence="documented", source="中文旧版药名",
         note="现通用名为西咪替丁。"),
    dict(alias="舒乐安定", sid="estazolam", zh="艾司唑仑", kind="legacy",
         confidence="documented", source="旧商品名",
         note="旧商品名，现通用名为艾司唑仑。"),
    dict(alias="扑热息痛", sid="acetaminophen", zh="对乙酰氨基酚", kind="legacy",
         confidence="documented", source="paracetamol 的中文旧称",
         note="英文 paracetamol，美国称 acetaminophen，中文通用名为对乙酰氨基酚。"),
    dict(alias="慢心律", sid="mexiletine", zh="美西律", kind="legacy",
         confidence="documented", source="中文旧版药名",
         note="现通用名为美西律。"),
    dict(alias="心律平", sid="propafenone", zh="普罗帕酮", kind="legacy",
         confidence="documented", source="中文旧版药名",
         note="现通用名为普罗帕酮。"),
    dict(alias="开搏通", sid="captopril", zh="卡托普利", kind="legacy",
         confidence="documented", source="Capoten 的旧商品名",
         note="旧商品名，现通用名为卡托普利。"),
    dict(alias="文迪雅", sid="rosiglitazone", zh="罗格列酮", kind="legacy",
         confidence="documented", source="Avandia 的旧商品名",
         note="旧商品名，现通用名为罗格列酮。"),

    # --- 补充：中文旧名 / 口头简称 -------------------------------------
    dict(alias="扑尔敏", sid="chlorphenamine", zh="氯苯那敏", kind="legacy",
         confidence="documented", source="Chlor-Trimeton 的中文旧名",
         note="抗组胺药，现通用名为氯苯那敏（美国写作 chlorpheniramine）。"),
    dict(alias="非那根", sid="promethazine", zh="异丙嗪", kind="legacy",
         confidence="documented", source="Phenergan 的中文旧名",
         note="旧商品名，现通用名为异丙嗪。"),
    dict(alias="654-2", sid="anisodamine", zh="山莨菪碱", kind="abbrev",
         confidence="documented", source="国内临床沿用编号简称",
         note="「654-2」是山莨菪碱的编号简称，不是商品名。"),
    dict(alias="速尿", sid="furosemide", zh="呋塞米", kind="legacy",
         confidence="documented", source="Lasix 的中文俗称",
         note="按药理作用得名，现通用名为呋塞米。"),
    dict(alias="双氢克尿噻", sid="hydrochlorothiazide", zh="氢氯噻嗪", kind="legacy",
         confidence="documented", source="中文旧名",
         note="旧名，现通用名为氢氯噻嗪。"),
    dict(alias="安体舒通", sid="spironolactone", zh="螺内酯", kind="legacy",
         confidence="documented", source="Aldactone 的中文旧名",
         note="旧名，现通用名为螺内酯。"),
    dict(alias="黄连素", sid="berberine", zh="小檗碱", kind="misnomer",
         confidence="community", source="民间按来源称呼",
         note="黄连素是小檗碱的俗称，来自黄连等植物，现已可合成。"),
    dict(alias="雷米封", sid="isoniazid", zh="异烟肼", kind="legacy",
         confidence="documented", source="Rimifon 的中文旧名",
         note="抗结核药，现通用名为异烟肼。"),
    dict(alias="安乃近", sid="metamizole", zh="安乃近", kind="legacy",
         confidence="documented", source="Analgin 的中文旧名",
         note="即 metamizole（dipyrone），部分国家已撤市。"),
    dict(alias="达菲", sid="oseltamivir", zh="奥司他韦", kind="legacy",
         confidence="documented", source="Tamiflu 的中文商品名",
         note="抗流感药，「达菲」是 Tamiflu 的通行叫法。"),
    dict(alias="芬必得", sid="ibuprofen", zh="布洛芬", kind="legacy",
         confidence="documented", source="芬必得（Fenbid）商品名",
         note="GSK 的布洛芬缓释胶囊商品名，常被当成药名本身。"),
    dict(alias="必理通", sid="acetaminophen", zh="对乙酰氨基酚", kind="legacy",
         confidence="documented", source="必理通（Panadol）中文商品名",
         note="GSK 的对乙酰氨基酚商品名。"),
    dict(alias="吗丁啉", sid="domperidone", zh="多潘立酮", kind="legacy",
         confidence="documented", source="Motilium 的中文商品名",
         note="西安杨森的多潘立酮商品名，常被当成药名。"),
    dict(alias="思密达", sid="diosmectite", zh="蒙脱石", kind="legacy",
         confidence="documented", source="Smecta 的中文商品名",
         note="止泻药，商品名比通用名更常被使用。"),
    dict(alias="达克宁", sid="miconazole", zh="咪康唑", kind="legacy",
         confidence="documented", source="Daktarin 的中文商品名",
         note="抗真菌药，常被当成药名本身。"),

    # --- 补充：降压 / 降糖原研商品名（中国患者常直接叫商品名）----------
    dict(alias="络活喜", sid="amlodipine", zh="氨氯地平", kind="legacy",
         confidence="documented", source="Norvasc 的中文商品名",
         note="辉瑞的氨氯地平商品名。"),
    dict(alias="拜新同", sid="nifedipine", zh="硝苯地平", kind="legacy",
         confidence="documented", source="Adalat GITS 的中文商品名",
         note="拜耳的硝苯地平控释片商品名。"),
    dict(alias="波依定", sid="felodipine", zh="非洛地平", kind="legacy",
         confidence="documented", source="Plendil 的中文商品名",
         note="阿斯利康的非洛地平缓释片商品名。"),
    dict(alias="代文", sid="valsartan", zh="缬沙坦", kind="legacy",
         confidence="documented", source="Diovan 的中文商品名",
         note="诺华的缬沙坦商品名。"),
    dict(alias="科素亚", sid="losartan", zh="氯沙坦", kind="legacy",
         confidence="documented", source="Cozaar 的中文商品名",
         note="默沙东的氯沙坦商品名。"),
    dict(alias="安博维", sid="irbesartan", zh="厄贝沙坦", kind="legacy",
         confidence="documented", source="Aprovel 的中文商品名",
         note="赛诺菲的厄贝沙坦商品名。"),
    dict(alias="拜唐苹", sid="acarbose", zh="阿卡波糖", kind="legacy",
         confidence="documented", source="Glucobay 的中文商品名",
         note="拜耳的阿卡波糖商品名。"),
    dict(alias="达美康", sid="gliclazide", zh="格列齐特", kind="legacy",
         confidence="documented", source="Diamicron 的中文商品名",
         note="施维雅的格列齐特商品名。"),
    dict(alias="亚莫利", sid="glimepiride", zh="格列美脲", kind="legacy",
         confidence="documented", source="Amaryl 的中文商品名",
         note="赛诺菲的格列美脲商品名。"),
    dict(alias="糖适平", sid="gliquidone", zh="格列喹酮", kind="legacy",
         confidence="documented", source="Glurenorm 的中文商品名",
         note="格列喹酮商品名，肾病常用。"),
    dict(alias="优甲乐", sid="levothyroxine", zh="左甲状腺素", kind="legacy",
         confidence="documented", source="Euthyrox 的中文商品名",
         note="默克的左甲状腺素钠商品名。"),
    dict(alias="赛治", sid="methimazole", zh="甲巯咪唑", kind="legacy",
         confidence="documented", source="Thyrozol 的中文商品名",
         note="默克的甲巯咪唑商品名。"),
    dict(alias="洛赛克", sid="omeprazole", zh="奥美拉唑", kind="legacy",
         confidence="documented", source="Losec 的中文商品名",
         note="阿斯利康的奥美拉唑商品名。"),
    dict(alias="波立维", sid="clopidogrel", zh="氯吡格雷", kind="legacy",
         confidence="documented", source="Plavix 的中文商品名",
         note="赛诺菲的氯吡格雷商品名。"),
    dict(alias="舒降之", sid="simvastatin", zh="辛伐他汀", kind="legacy",
         confidence="documented", source="Zocor 的中文商品名",
         note="默沙东的辛伐他汀商品名。"),
    dict(alias="力平之", sid="fenofibrate", zh="非诺贝特", kind="legacy",
         confidence="documented", source="Lipanthyl 的中文商品名",
         note="雅培的非诺贝特商品名。"),
    dict(alias="拜阿司匹灵", sid="aspirin", zh="阿司匹林", kind="legacy",
         confidence="documented", source="Bayer 阿司匹林商品名",
         note="拜耳的阿司匹林肠溶片商品名。"),

    # --- 补充：西语区（加州/墨西哥）常见商品名 -------------------------
    dict(alias="Tempra", sid="acetaminophen", zh="对乙酰氨基酚", kind="legacy",
         confidence="documented", source="墨西哥常见商品名（Tempra）",
         note="墨西哥最常用的对乙酰氨基酚商品名之一；注意 Tempra XT/MAX 是复方，不是单方。"),
    dict(alias="Mejoral", sid="acetaminophen", zh="对乙酰氨基酚", kind="legacy",
         confidence="community", source="墨西哥常见商品名（Mejoral）",
         note="墨西哥的对乙酰氨基酚商品名。"),
]


def main() -> None:
    db = sqlite3.connect(DB, timeout=60)
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    today = date.today().isoformat()
    kept = skipped = shadowed = 0

    for a in ALIASES:
        row = db.execute(
            "SELECT substance_id FROM substance WHERE substance_id = ?", (a["sid"],)
        ).fetchone()
        if not row:
            print(f"跳过 {a['alias']}：库里没有成分 {a['sid']}")
            skipped += 1
            continue
        n = normalize(a["alias"])
        if not n.norm:
            print(f"跳过 {a['alias']}：归一化后为空")
            skipped += 1
            continue

        # 如果这个写法已经是某个商品的正式名字，别名会抢在名字前命中——
        # 不阻止（人工表就是要这个优先级），但必须让人看见。
        exists = db.execute(
            "SELECT norm FROM name_key WHERE norm = ?", (n.norm,)).fetchone()
        if exists:
            print(f"注意 {a['alias']}：同时是一个商品名键，别名会优先命中")
            shadowed += 1

        db.execute(
            """INSERT INTO nickname (substance_id, alias, alias_norm, label_zh,
                                     kind, confidence, source, note, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT (alias_norm, substance_id) DO UPDATE SET
                   alias      = excluded.alias,
                   label_zh   = excluded.label_zh,
                   kind       = excluded.kind,
                   confidence = excluded.confidence,
                   source     = excluded.source,
                   note       = excluded.note""",
            (a["sid"], a["alias"], n.norm, a.get("zh"), a["kind"],
             a["confidence"], a["source"], a["note"], today),
        )
        kept += 1

    db.commit()
    total = db.execute("SELECT COUNT(*) FROM nickname").fetchone()[0]
    print(f"nickname: 写入 {kept} 条，跳过 {skipped} 条，同名键 {shadowed} 条；表内共 {total} 条")
    db.close()


if __name__ == "__main__":
    main()
