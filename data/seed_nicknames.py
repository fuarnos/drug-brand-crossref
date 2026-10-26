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
