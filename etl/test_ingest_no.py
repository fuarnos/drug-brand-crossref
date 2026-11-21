"""NO（挪威 DMP FEST 2.5.1）入库测试：解析/映射/状态口径。

- 纯函数测试不碰库、不联网（CI 也能跑）；
- 集成测试只在 `data/raw/no/fest251.zip` 与 `data/drugs.db` 都在时跑：解析整包快照、
  核对条数与引用解析、对前 50 个品牌出计划（只读开库，**不写库**、不跑 ingest）。
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "etl" / "markets"))

import ingest_no  # noqa: E402

DB = ROOT / "data" / "drugs.db"
ZIP = ROOT / "data" / "raw" / "no" / "fest251.zip"


class FoldAndForm(unittest.TestCase):
    """挪威语折叠 + 剂型词表：ñ/ø/å 与 9 个主类。"""

    def test_fold_transliterates_norwegian_letters(self):
        self.assertEqual(ingest_no.fold_no("Øyedråper, oppløsning"),
                         "oyedraper opplosning")
        self.assertEqual(ingest_no.fold_no("Brusetablett"), "brusetablett")

    def test_form_base_main_classes(self):
        cases = {
            "Tablett": "tablet",
            "Depottablett": "tablet",
            "Brusetablett": "effervescent",
            "Kapsel, hard": "capsule",
            "Injeksjonsvæske, oppløsning": "injection",
            "Konsentrat til infusjonsvæske, oppløsning": "injection",
            "Pulver til injeksjonsvæske, oppløsning": "injection",
            "Inhalasjonspulver": "inhalation",
            "Stikkpille": "suppository",
            "Vagitorie": "pessary",
            "Krem": "topical",
            "Mikstur, oppløsning": "liquid",
            "Granulat til mikstur, suspensjon": "powder",
            "Medisinsk gass, komprimert": "gas",
            "Sublingvalt lyofilisat": "tablet",
            "Sublingvalfilm": "film",
        }
        for form, want in cases.items():
            with self.subTest(form=form):
                self.assertEqual(ingest_no.form_base_no(form), want)

    def test_form_base_never_leaks_raw_norwegian(self):
        # 命不中词表就落 other/unknown，绝不把整串原文写进 form_base
        for form in ("Munnhulepose", "Matriks til vevslim", ""):
            with self.subTest(form=form):
                self.assertIn(ingest_no.form_base_no(form), {"other", "unknown"})

    def test_release_from_norwegian_form(self):
        self.assertEqual(ingest_no.release_no("Depottablett"), "ER")
        self.assertEqual(ingest_no.release_no("Enterotablett"), "DR")
        self.assertEqual(ingest_no.release_no("Tablett med modifisert frisetting"), "MR")
        self.assertEqual(ingest_no.release_no("Tablett"), "none")


class RouteAndUnit(unittest.TestCase):
    """结构化途径 + 挪威语单位（只做文本归一，不换算）。"""

    def test_route_map(self):
        self.assertEqual(ingest_no.route_no("Oral bruk"), "oral")
        self.assertEqual(ingest_no.route_no("Intravenøs bruk"), "intravenous")
        self.assertEqual(ingest_no.route_no("Bruk på hud"), "topical")
        self.assertEqual(ingest_no.route_no("Urethral bruk"), "urethral")
        self.assertIsNone(ingest_no.route_no("Administrasjonsvei ikke spesifisert"))
        self.assertIsNone(ingest_no.route_no(None))

    def test_unit_normalisation(self):
        self.assertEqual(ingest_no.unit_of("mikrog")[0], "mcg")
        self.assertEqual(ingest_no.unit_of("IE")[0], "IU")
        self.assertEqual(ingest_no.unit_of("mg")[0], "mg")
        self.assertEqual(ingest_no.unit_of("% w/v")[0], "%w/v")
        self.assertEqual(ingest_no.unit_of(None)[0], None)
        # 生物制品单位保留原文（不认识就别猜）
        self.assertEqual(ingest_no.unit_of("SQ-E")[0], "SQ-E")

    def test_strength_value_parsing(self):
        self.assertEqual(ingest_no.strength_value_of("40"), 40.0)
        self.assertEqual(ingest_no.strength_value_of("0,5"), 0.5)
        self.assertIsNone(ingest_no.strength_value_of("n/a"))
        self.assertEqual(ingest_no.denom_of("5", "ml"), (5.0, "mL"))
        self.assertEqual(ingest_no.denom_of("1", "sprøyte"), (1.0, "sprøyte"))


class Names(unittest.TestCase):
    """成分名候选与 INN 对齐（只做名字对应，不做剂量/等效判断）。"""

    def test_candidates_include_salt_base_and_ion(self):
        self.assertIn("cetirizine", ingest_no.candidate_keys("Cetirizine dihydrochloride"))
        self.assertIn("copper", ingest_no.candidate_keys("Copper(II) ion"))
        self.assertIn("pramipexole",
                      ingest_no.candidate_keys("Pramipexole dihydrochloride monohydrate"))

    def test_element_guard_does_not_strip_salt(self):
        # KCl ≠ K：元素/电解质母体不允许靠去盐词命中
        self.assertEqual(ingest_no.salt_base("Potassium chloride"), "")
        self.assertEqual(ingest_no.salt_base("Sodium hydrogen carbonate"), "")

    def test_inn_aliases(self):
        for name, want in (("Paracetamol", "acetaminophen"),
                           ("Adrenaline", "epinephrine"),
                           ("Acetylsalicylic acid", "aspirin"),
                           ("Sodium hydrogen carbonate", "sodium bicarbonate")):
            with self.subTest(name=name):
                self.assertIn(want, ingest_no.candidate_keys(name))

    def test_non_substance_placeholder(self):
        res = ingest_no.resolve_component(
            {"navn": "Homeopatic composed drug", "navn_en": "Homeopatic composed drug"},
            "ID_X", {})
        self.assertEqual(res["method"], "non-substance")


TINY_XML = """<?xml version="1.0" encoding="utf-8"?>
<FEST xmlns="http://www.kith.no/xmlstds/eresept/m30/2014-12-01">
  <HentetDato>2026-11-10T10:24:32</HentetDato>
  <KatLegemiddelMerkevare>
    <OppfLegemiddelMerkevare>
      <Id>OPPF-B1</Id><Tidspunkt>2026-01-01T00:00:00</Tidspunkt>
      <Status V="A" DN="Aktiv oppføring" />
      <LegemiddelMerkevare xmlns="http://www.kith.no/xmlstds/eresept/forskrivning/2014-12-01">
        <Atc V="N02BE01" DN="Paracetamol" />
        <LegemiddelformKort V="53" DN="Tablett" />
        <Id>B1</Id>
        <Varenavn>Testbrand</Varenavn>
        <SortertVirkestoffMedStyrke>
          <Sortering>0</Sortering><RefVirkestoffMedStyrke>V1</RefVirkestoffMedStyrke>
        </SortertVirkestoffMedStyrke>
        <ProduktInfo><Produsent>Test MAH</Produsent></ProduktInfo>
      </LegemiddelMerkevare>
    </OppfLegemiddelMerkevare>
  </KatLegemiddelMerkevare>
  <KatVirkestoff>
    <OppfVirkestoff>
      <Id>OPPF-K1</Id>
      <Virkestoff xmlns="http://www.kith.no/xmlstds/eresept/forskrivning/2014-12-01">
        <Id>K1</Id><Navn>Paracetamol</Navn><NavnEngelsk>Paracetamol</NavnEngelsk>
      </Virkestoff>
    </OppfVirkestoff>
    <OppfVirkestoff>
      <Id>OPPF-V1</Id>
      <VirkestoffMedStyrke xmlns="http://www.kith.no/xmlstds/eresept/forskrivning/2014-12-01">
        <Id>V1</Id><Styrke V="500" U="mg" /><RefVirkestoff>K1</RefVirkestoff>
      </VirkestoffMedStyrke>
    </OppfVirkestoff>
  </KatVirkestoff>
  <KatLegemiddelpakning>
    <OppfLegemiddelpakning>
      <Id>OPPF-P1</Id><Status V="A" DN="Aktiv oppføring" />
      <Legemiddelpakning xmlns="http://www.kith.no/xmlstds/eresept/forskrivning/2014-12-01">
        <Id>P1</Id><Varenr>123456</Varenr>
        <Pakningsinfo>
          <RefLegemiddelMerkevare>B1</RefLegemiddelMerkevare>
          <Pakningsstr>20</Pakningsstr>
          <EnhetPakning V="stk" DN="stykk" />
        </Pakningsinfo>
        <Markedsforingsinfo>
          <VarenrUtgaende>999999</VarenrUtgaende>
          <Markedsforingsdato>2020-01-01</Markedsforingsdato>
        </Markedsforingsinfo>
      </Legemiddelpakning>
    </OppfLegemiddelpakning>
  </KatLegemiddelpakning>
</FEST>
"""


class TinySnapshot(unittest.TestCase):
    """最小快照：两套命名空间、Oppf* 包裹层、引用解析、标记日期。"""

    @classmethod
    def setUpClass(cls) -> None:
        import tempfile
        import zipfile

        cls._tmp = tempfile.TemporaryDirectory()
        path = Path(cls._tmp.name) / "fest251.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("fest251.xml", TINY_XML)
        cls.snap = ingest_no.load_snapshot(path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_brand_package_and_refs(self):
        brand = self.snap["brands"]["B1"]
        self.assertEqual(brand["varenavn"], "Testbrand")
        self.assertEqual(brand["refs"], ["V1"])
        self.assertEqual(brand["produsent"], "Test MAH")
        self.assertEqual(self.snap["hentet"][:10], "2026-11-10")
        pkg = self.snap["packages"][0]
        self.assertEqual(pkg["varenr"], "123456")
        self.assertEqual(pkg["infos"][0]["brand_ref"], "B1")
        self.assertEqual(pkg["infos"][0]["pakningsstr"], "20")
        self.assertEqual(pkg["infos"][0]["enhet_dn"], "stykk")

    def test_varenr_utgaende_is_not_a_status_marker(self):
        # 实测 VarenrUtgaende 的文本是另一个订货号（999999），不是日期；
        # 解析层只保留 AvregDato / MidlUtgattDato 两个状态日期键。
        pkg = self.snap["packages"][0]
        self.assertNotIn("utg", pkg)
        self.assertEqual(pkg["avreg"], "")
        self.assertEqual(pkg["midl"], "")
        status, date, _notes = ingest_no.brand_status([pkg])
        self.assertEqual((status, date), ("active", None))

    def test_strength_and_ingredient(self):
        vms = self.snap["vms"]["V1"]
        self.assertEqual((vms["styrke"], vms["unit"]), ("500", "mg"))
        self.assertEqual(vms["ref"], "K1")
        self.assertEqual(self.snap["virk"]["K1"]["navn_en"], "Paracetamol")


class StatusAndPack(unittest.TestCase):
    """品牌状态只由包装级日期标记聚合（VarenrUtgaende 不是状态）。"""

    def test_status_aggregation(self):
        self.assertEqual(ingest_no.brand_status([])[0], "unknown")
        self.assertEqual(ingest_no.brand_status([{"avreg": "", "midl": ""}])[0], "active")
        self.assertEqual(ingest_no.brand_status([{"avreg": "2026-10-12", "midl": ""}])[0],
                         "withdrawn")
        self.assertEqual(ingest_no.brand_status([{"avreg": "", "midl": "2026-10-12"}])[0],
                         "discontinued")
        mixed = [{"avreg": "", "midl": ""}, {"avreg": "", "midl": "2026-10-12"}]
        status, date, notes = ingest_no.brand_status(mixed)
        self.assertEqual((status, date), ("active", None))
        self.assertTrue(notes and "1/2" in notes[0])

    def test_pack_text_dedupes_and_keeps_order(self):
        pkgs = [
            {"infos": [{"brand_ref": "B1", "pakningsstr": "100", "enhet_dn": "stykk",
                        "enhet": "stk"},
                       {"brand_ref": "B1", "pakningsstr": "100", "enhet_dn": "stykk",
                        "enhet": "stk"}]},
            {"infos": [{"brand_ref": "B1", "pakningsstr": "3 x 1", "enhet_dn": "stykk",
                        "enhet": "stk"}]},
        ]
        self.assertEqual(ingest_no.pack_text("B1", pkgs), ("100 stykk · 3 x 1 stykk", 2))

    def test_product_id_stable_and_prefixed(self):
        pid = ingest_no.brand_product_id("ID_ABC", "Thylip")
        self.assertTrue(pid.startswith("NO-thylip-"))
        self.assertEqual(pid, ingest_no.brand_product_id("ID_ABC", "Thylip"))


@unittest.skipUnless(ZIP.exists(), "没有 data/raw/no/fest251.zip（CI 无快照时跳过）")
class SnapshotCounts(unittest.TestCase):
    """整包解析：条数与引用解析率必须与评估报告一致（2026-11-10 快照）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = ingest_no.load_snapshot()

    def test_counts(self):
        self.assertEqual(len(self.snap["brands"]), 8985)
        self.assertEqual(len(self.snap["packages"]), 10867)
        self.assertEqual(len(self.snap["vms"]), 7652)
        self.assertEqual(len(self.snap["virk"]), 8645)
        self.assertEqual(self.snap["hentet"][:10], "2026-11-10")

    def test_every_ref_resolves(self):
        brand_ids = set(self.snap["brands"])
        vms_ids = set(self.snap["vms"])
        virk_ids = set(self.snap["virk"])
        self.assertEqual({i["brand_ref"] for p in self.snap["packages"] for i in p["infos"]}
                         - brand_ids, set())
        self.assertEqual({r for b in self.snap["brands"].values() for r in b["refs"]}
                         - vms_ids, set())
        self.assertEqual({v["ref"] for v in self.snap["vms"].values()} - virk_ids, set())
        self.assertEqual({r for b in self.snap["brands"].values()
                          for r in b["refs_no_strength"]} - virk_ids, set())

    def test_all_brands_have_strength_or_plain_ingredient(self):
        for brand in self.snap["brands"].values():
            with self.subTest(brand=brand["varenavn"]):
                self.assertTrue(brand["refs"] or brand["refs_no_strength"])


@unittest.skipUnless(DB.exists() and ZIP.exists(), "缺 data/drugs.db 或 NO 快照")
class PlanAgainstDb(unittest.TestCase):
    """只读开库出计划（不写库）：验证两段式 pending 与成分映射方法名。"""

    def test_plan_smoke(self):
        snap = ingest_no.load_snapshot()
        db = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            first = ingest_no.build_plan(db, snap, limit=200)
            fake = {k: [f"sim-{i}", f"sim-{i}"]
                    for i, k in enumerate(sorted(first["pending_new"]))}
            plan = ingest_no.build_plan(db, snap, fake, limit=200)
        finally:
            db.close()
        self.assertEqual(plan["stats"]["brands_planned"], 200)
        self.assertNotIn("pending_new_components", plan["stats"])
        methods = {k for k in plan["stats"] if k.startswith("method_")}
        self.assertTrue(methods, "计划里应有 method_* 统计")
        self.assertTrue(all(m in {"method_exact", "method_paren", "method_spelling",
                                  "method_ion", "method_salt", "method_inn_alias",
                                  "method_exact-no", "method_new"} for m in methods),
                        methods)


if __name__ == "__main__":
    unittest.main()
