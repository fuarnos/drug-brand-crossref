"""Canada layer tests: brand cleaning, ingredient canonicalisation, dosage arithmetic."""
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from ingest_ca_dpd import (  # noqa: E402
    canonical_base,
    clean_brand,
    normalise_strength,
    release_of,
    status_of,
)


class CleanBrand(unittest.TestCase):
    def test_form_suffix_stripped_but_strength_words_kept(self):
        self.assertEqual(clean_brand("TYLENOL EXTRA STRENGTH CAPLETS")[0],
                         "TYLENOL EXTRA STRENGTH")
        self.assertEqual(clean_brand("MOTRIN IB CAPLET/TAB 200MG")[0], "MOTRIN IB")
        self.assertEqual(clean_brand("APO-AMOXI CAP 500MG")[0], "APO-AMOXI")
        self.assertEqual(clean_brand("ADVIL LIQUI-GELS")[0], "ADVIL")

    def test_paren_becomes_extra_and_short_words_survive(self):
        name, extra, _ = clean_brand("SOMNOTOL (PENTOBARBITAL SODIUM INJECTION, USP)")
        self.assertEqual((name, extra), ("SOMNOTOL", "PENTOBARBITAL SODIUM INJECTION, USP"))
        # RAPID / JR 不是剂型词，不能被切掉
        self.assertEqual(clean_brand("RAPID RELEASE TYLENOL CAPLETS")[0], "RAPID RELEASE TYLENOL")
        self.assertEqual(clean_brand("EPIPEN JR AUTO-INJ 0.15MG")[0], "EPIPEN JR")

    def test_descriptive_names_keep_display_but_loosen_key(self):
        name, _, key = clean_brand("15 SPF FPS PREMIUM SUNSCREEN")
        self.assertEqual(name, "15 SPF FPS PREMIUM SUNSCREEN")
        self.assertEqual(key, "15 SPF FPS PREMIUM")


class Ingredients(unittest.TestCase):
    def test_canadian_old_names_map_to_usan(self):
        self.assertEqual(canonical_base("ACETYLSALICYLIC ACID")[0], "aspirin")
        self.assertEqual(canonical_base("ADRENALINE")[0], "epinephrine")
        self.assertEqual(canonical_base("GLYCERYL TRINITRATE")[0], "nitroglycerin")

    def test_salt_inside_parentheses_becomes_variant(self):
        sid, disp, vid, salt = canonical_base("ATORVASTATIN (ATORVASTATIN CALCIUM)")
        self.assertEqual((sid, vid, salt), ("atorvastatin", "atorvastatin-calcium", "calcium"))
        # 主名与括号同名（EPOETIN ALFA (EPOETIN ALFA)）：不造 salt
        self.assertEqual(canonical_base("EPOETIN ALFA (EPOETIN ALFA)")[3], "")

    def test_vaccine_carrier_is_not_a_salt(self):
        sid, _disp, vid, salt = canonical_base(
            "PNEUMOCOCCAL POLYSACCHARID SEROT. 19F CONJUG. TO DIPHTHERIA TOXOID CARRIER PROT.")
        self.assertEqual(sid, vid)
        self.assertEqual(salt, "")

    def test_trailing_decimal_is_kept(self):
        self.assertEqual(normalise_strength(".0114", "ML"), (0.0114, "ml"))
        self.assertEqual(normalise_strength("500", "MG"), (500.0, "mg"))
        self.assertEqual(normalise_strength("", "MG"), (None, None))


class Status(unittest.TestCase):
    def test_status_mapping(self):
        self.assertEqual(status_of("Marketed", None)[0], "active")
        self.assertEqual(status_of("Approved", None)[0], "active")
        self.assertEqual(status_of("Dormant", "2020-01-01"), ("discontinued", "2020-01-01"))
        self.assertEqual(status_of("Cancelled Post Market", None)[0], "discontinued")
        self.assertEqual(status_of("Authorization By Interim Order Revoked", None)[0], "withdrawn")

    def test_release_words(self):
        self.assertEqual(release_of("Capsule (Controlled-Release)"), "ER")
        self.assertEqual(release_of("Tablet (Delayed-Release)"), "DR")
        self.assertEqual(release_of("Capsule"), "none")


if __name__ == "__main__":
    unittest.main()
