"""归一化器的回归测试。运行：python -m unittest discover -s etl -v"""

from __future__ import annotations

import unittest

from normalize_name import normalize


class TestNormalize(unittest.TestCase):
    def check(self, raw, norm, strengths=()):
        got = normalize(raw)
        self.assertEqual(got.norm, norm, f"{raw!r} -> {got.norm!r}")
        self.assertEqual(got.strengths, strengths, f"{raw!r} strengths")

    def test_latin_basic(self):
        self.check("Losec® 20 mg", "losec", (("20", "mg"),))
        self.check("Sortis 20mg", "sortis", (("20", "mg"),))
        self.check("  PANADOL   Extra 500mg ", "panadol extra", (("500", "mg"),))
        self.check("Doliprane 1000 mg", "doliprane", (("1000", "mg"),))
        self.check("Panadol Advance 500 mg tablet", "panadol advance", (("500", "mg"),))

    def test_fullwidth_and_diacritics(self):
        self.check("ＬＯＳＥＣ　２０ｍｇ", "losec", (("20", "mg"),))
        self.check("Éfferalgan 500 mg", "efferalgan", (("500", "mg"),))

    def test_cyrillic_transliteration(self):
        self.check("СОРТИС 20 мг", "sortis", (("20", "mg"),))
        self.check("Аторис 20 мг", "atoris", (("20", "mg"),))
        self.check("Липримар 20мг", "liprimar", (("20", "mg"),))
        self.check("Нурофен", "nurofen")

    def test_han(self):
        self.check("立普妥 20mg", "立普妥", (("20", "mg"),))
        self.check("泰诺", "泰诺")
        self.check("鹽酸氨氯地平 5mg", "盐酸氨氯地平", (("5", "mg"),))

    def test_combinations(self):
        self.check("Augmentin 875/125 mg", "augmentin", (("875", "mg"), ("125", "mg")))
        self.check("Co-Amoxiclav 500/125 mg", "co amoxiclav",
                   (("500", "mg"), ("125", "mg")))
        self.check("Augmentin 500/125", "augmentin", (("500", ""), ("125", "")))
        self.check("Amoxiclav 5 mg/5 ml", "amoxiclav", (("5/5", "mg/ml"),))

    def test_brand_variant_words_kept(self):
        # Cold & Flu 是产品变体的一部分，不能当噪音删掉——这正是碰撞的来源
        self.check("Nurofen Cold & Flu", "nurofen cold flu")

    def test_form_tokens_stripped_but_recorded(self):
        got = normalize("Metoprolol succinate ER 50 mg")
        self.assertEqual(got.norm, "metoprolol succinate")
        self.assertIn("er", got.form_hint)

    def test_compact_key(self):
        self.assertEqual(normalize("Co-Amoxiclav").compact, "coamoxiclav")

    def test_empty(self):
        self.assertTrue(normalize("").is_empty)
        self.assertTrue(normalize("   ").is_empty)
        self.assertEqual(normalize("20 mg").norm, "")


if __name__ == "__main__":
    unittest.main()
