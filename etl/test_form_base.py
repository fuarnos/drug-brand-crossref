"""剂型 / 释放机制归一化的单测：`form_base_of` / `release_of` 与三个来源语言的分叉。

覆盖 task-7 的四条规则（reports/consistency-audit-form-20261110.md、
reports/form-effervescent-20261110.md）：

1. `FORM_BASES` 顺序：`liquid` 排最后，`injection, solution` 不能再落成液体、
   `Powder For Solution` 不能再落成液体；
2. `effervescent` 是新类，7 种原文拼写都要认（含 TW 繁体 `發泡錠` / `發泡顆粒劑`）；
3. `release_of()` 认 enteric / controlled / prolonged / 西语 `liberación prolongada`；
4. `form_base` 兜底不再返回原文整串：认不出的落 `other`，占位词落 `unknown`。
"""
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from ingest_cima import form_base_es as cima_form_base  # noqa: E402
from ingest_mx import form_base_es as mx_form_base  # noqa: E402
from ingest_nhsa import translate_form  # noqa: E402
from ingest_openfda_ndc import (  # noqa: E402
    EFFERVESCENT_KEYS, FORM_BASES, PLAIN_BASES, form_base_of, release_of,
)
from ingest_tw_tfda import tw_form_base  # noqa: E402


class FormOrder(unittest.TestCase):
    """`liquid` 排最后：注射剂/粉剂不再被吃成液体（审计 R1 的 15,570 + 3,304 行）。"""

    def test_injection_wins_over_solution(self):
        self.assertEqual(form_base_of("injection, solution"), "injection")
        self.assertEqual(form_base_of("INJECTION, SOLUTION"), "injection")
        self.assertEqual(form_base_of("Injection, solution, concentrate"), "injection")
        self.assertEqual(form_base_of("pre-filled syringe"), "injection")

    def test_powder_wins_over_solution(self):
        self.assertEqual(form_base_of("Powder For Solution"), "powder")
        self.assertEqual(form_base_of("powder, for solution"), "powder")
        self.assertEqual(form_base_of("granule, for suspension, extended release"), "powder")

    def test_injection_wins_over_powder(self):
        # `injection, powder, lyophilized, for solution` 是注射用粉末，不是粉剂
        self.assertEqual(form_base_of("injection, powder, lyophilized, for solution"),
                         "injection")

    def test_liquid_last_keeps_plain_liquids(self):
        self.assertEqual(form_base_of("solution"), "liquid")
        self.assertEqual(form_base_of("oral suspension"), "liquid")
        self.assertEqual(form_base_of("syrup"), "liquid")

    def test_keyword_order_is_explicit(self):
        bases = [base for base, _keys in FORM_BASES]
        self.assertEqual(bases[-1], "liquid")
        self.assertLess(bases.index("effervescent"), bases.index("tablet"))
        self.assertLess(bases.index("injection"), bases.index("liquid"))
        self.assertLess(bases.index("powder"), bases.index("liquid"))


class Effervescent(unittest.TestCase):
    """新增 `effervescent` 类：7 种原文拼写 + 三个来源语言的分叉。"""

    def test_seven_spellings(self):
        for text in ("Tablet, effervescent", "Tablet (Effervescent)",
                     "granule, effervescent", "comprimido efervescente",
                     "發泡錠", "發泡顆粒劑", "effervescent powder", "fizzy tablet"):
            with self.subTest(text=text):
                self.assertEqual(form_base_of(text), "effervescent")

    def test_keys_cover_simplified_and_traditional(self):
        for key in ("effervesc", "efervesc", "泡腾", "泡騰", "發泡", "发泡", "fizzy"):
            self.assertIn(key, EFFERVESCENT_KEYS)

    def test_cima_translation(self):
        # CIMA 先把西语翻成英文再交给共享规则：`efervescente` → effervescent
        self.assertEqual(cima_form_base("comprimido efervescente"), "effervescent")
        self.assertEqual(cima_form_base("solución oral efervescente"), "effervescent")

    def test_nhsa_translation(self):
        # CN 医保库的剂型是「片剂(泡腾)」：先命中的是「片」，所以泡腾必须排第一
        self.assertEqual(translate_form("片剂(泡腾)"), "effervescent")
        self.assertEqual(form_base_of(translate_form("颗粒剂(泡腾)")), "effervescent")

    def test_tw_translation(self):
        # TW 的 `發泡錠` 含「錠」、`發泡顆粒劑` 含「顆粒」，泡腾必须排在 tablet/powder 之前
        self.assertEqual(tw_form_base("發泡錠"), "effervescent")
        self.assertEqual(tw_form_base("發泡顆粒劑"), "effervescent")

    def test_mx_translation(self):
        self.assertEqual(mx_form_base("Comprimido efervescente"), "effervescent")

    def test_plain_tablet_still_tablet(self):
        # 防回归：加了泡腾类之后，普通片剂/薄膜衣片不能漂成泡腾
        self.assertEqual(form_base_of("Tablet, film coated"), "tablet")
        self.assertEqual(form_base_of("Cápsula dura"), "capsule")


class Release(unittest.TestCase):
    """`release_of()` 要认 enteric / controlled / prolonged / 西语 liberación prolongada。"""

    def test_er_words(self):
        for text in ("Tablet, controlled release", "Tablet, modified release",
                     "Capsule, extended release", "Capsule (Sustained-Release)",
                     "Tablet, prolonged release", "Capsule, ER", "Tablet, XR",
                     "comprimido de liberación prolongada", "comprimido de liberacion modificada",
                     "缓释片", "控释胶囊", "長效錠"):
            with self.subTest(text=text):
                self.assertEqual(release_of(text), "ER")

    def test_dr_words(self):
        for text in ("Tablet, enteric coated", "Capsule, enteric", "gastro-resistant tablet",
                     "肠溶片", "腸溶錠", "resistant to gastric juice"):
            with self.subTest(text=text):
                self.assertEqual(release_of(text), "DR")

    def test_immediate_release_is_none(self):
        for text in ("Tablet", "Capsule, soft", "Oral solution", "", "injection, solution"):
            with self.subTest(text=text):
                self.assertEqual(release_of(text), "none")

    def test_extra_texts_are_joined(self):
        # release_of 也接受商品名等附加文本（CN/ES 的 release 可能是按名字推的）
        self.assertEqual(release_of("錠劑", "倍他乐克缓释片"), "ER")


class Fallback(unittest.TestCase):
    """兜底不再把原文整串塞进 form_base（审计 R2 的 2,187 行）。"""

    def test_free_text_never_returned(self):
        for text in ("indometacin 100mg suppositories",
                     "amorolfine 5% medicated nail lacquer",
                     "chlorhexidine gluconate 0.2% mouthwash",
                     "nicotine 2mg medicated chewing gum sugar free",
                     "oxygen cylinders 1360litres",
                     "dialisis peritoneal"):
            with self.subTest(text=text):
                got = form_base_of(text)
                self.assertNotEqual(got, text.lower())
                self.assertNotIn(" ", got)
                self.assertFalse(any(ch.isdigit() for ch in got))

    def test_wordlist_lands_real_classes(self):
        self.assertEqual(form_base_of("clotrimazole 500mg pessaries"), "suppository")
        self.assertEqual(form_base_of("diclofenac 100 mg suppositories"), "suppository")
        self.assertEqual(form_base_of("mesalazine 1g suppositories"), "suppository")
        self.assertEqual(form_base_of("amorolfine 5% medicated nail lacquer"), "topical")
        self.assertEqual(form_base_of("chlorhexidine gluconate 0.2% mouthwash"), "mouthwash")
        self.assertEqual(form_base_of("dialisis peritoneal"), "liquid")
        self.assertEqual(form_base_of("pholcodine 5mg/5ml linctus sugar free"), "liquid")
        self.assertEqual(form_base_of("semisolido rectal"), "topical")
        self.assertEqual(form_base_of("barniz unas"), "topical")

    def test_unmatched_goes_to_other(self):
        for text in ("system", "chicle", "wafer", "insert", "pulverizacion bucal",
                     "nitrous oxide 50% / oxygen 50%", "tea (herbal)"):
            with self.subTest(text=text):
                self.assertIn(form_base_of(text), ("other", "tea (herbal)"))

    def test_placeholders_go_to_unknown(self):
        for text in ("", "   ", "unknown", "not stated", "null", "cancelado", "N/A"):
            with self.subTest(text=text):
                self.assertEqual(form_base_of(text), "unknown")

    def test_plain_values_pass_through(self):
        # 来源给的单个剂型名（stick / pellet / kit / gas …）不参与关键词匹配，原样保留
        for text in ("stick", "pellet", "kit", "gas", "mouthwash", "topical", "plaster",
                     "gum, chewing", "film"):
            with self.subTest(text=text):
                self.assertEqual(form_base_of(text), text)
        for text in ("stick", "pellet", "kit", "gas", "mouthwash"):
            self.assertIn(text, PLAIN_BASES)


if __name__ == "__main__":
    unittest.main()
