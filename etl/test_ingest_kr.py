"""KR（韩国 HIRA 약가마스터）入库测试：解析/映射/状态口径。

- 纯函数测试不碰库、不联网（CI 也能跑）；
- 最小 CSV 快照测试：用临时目录里 2 个 CP949 CSV 验证 join / 品目聚合 / 状态 / 包装；
- 快照集成测试只在 `data/raw/kr/…csv` 存在时跑（核对报告里的实测条数）。
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "etl" / "markets"))

import ingest_kr  # noqa: E402

STD = ingest_kr._locate(ingest_kr.STD_NAME)
ING = ingest_kr._locate(ingest_kr.ING_NAME)

STD_HEADER = ["한글상품명", "업체명", "약품규격", "제품총수량", "제형구분", "포장형태",
              "품목기준코드", "품목허가일자", "전문일반구분", "대표코드", "표준코드",
              "제품코드(개정후)", "일반명코드(성분명코드)", "비고", "취소일자",
              "양도양수적용(공고)일자", "양도양수종료일자", "일련번호생략여부",
              "일련번호생략사유", "국제표준코드(ATC코드)", "특수관리약품구분",
              "의약품판독장비구분"]
ING_HEADER = ["일반명코드", "제형구분코드", "제형", "일반명", "분류번호", "투여", "함량", "단위"]


def _std_row(**kw) -> list[str]:
    base = {h: "" for h in STD_HEADER}
    base.update({"업체명": "테스트제약", "약품규격": "없음", "제품총수량": "0",
                 "품목허가일자": "2020-01-01", "전문일반구분": "일반의약품",
                 "품목기준코드": "199905709", "표준코드": "8800000000001"})
    # 列名含括号，无法直接当 kwargs：给两个短别名
    alias = {"성분코드": "일반명코드(성분명코드)", "ATC": "국제표준코드(ATC코드)"}
    for short, header in alias.items():
        if short in kw:
            base[header] = kw.pop(short)
    base.update(kw)
    return [base[h] for h in STD_HEADER]


def _ing_row(**kw) -> list[str]:
    base = {h: "" for h in ING_HEADER}
    base.update({"일반명코드": "100101ATB", "제형구분코드": "TB", "제형": "정제,저작정",
                 "일반명": "paracetamol", "분류번호": "421", "투여": "내복",
                 "함량": "500", "단위": "mg"})
    base.update(kw)
    return [base[h] for h in ING_HEADER]


class FoldUnitForm(unittest.TestCase):
    """韩文折叠 / 单位 / 剂型 / 释放 / 途径。"""

    def test_fold_keeps_hangul(self):
        got = ingest_kr.fold_kr("아작탐주사500밀리그람(아즈트레오남)")
        self.assertEqual(got, "아작탐주사500밀리그람 아즈트레오남")

    def test_units(self):
        self.assertEqual(ingest_kr.unit_of_kr("mg")[0], "mg")
        self.assertEqual(ingest_kr.unit_of_kr("㎍")[0], "mcg")
        self.assertEqual(ingest_kr.unit_of_kr("μg")[0], "mcg")
        self.assertEqual(ingest_kr.unit_of_kr("I.U")[0], "IU")
        self.assertEqual(ingest_kr.unit_of_kr("KI.U")[0], "kIU")
        self.assertEqual(ingest_kr.unit_of_kr("mg/ml")[0], "mg/mL")
        # 复合单位（含括号浓度）不解析、原样保留
        self.assertEqual(ingest_kr.unit_of_kr("mg(0.3mg/mL)"),
                         ("mg(0.3mg/mL)", "composite"))
        self.assertEqual(ingest_kr.unit_of_kr(""), (None, "empty"))

    def test_strength(self):
        self.assertEqual(ingest_kr.strength_of("0.5"), 0.5)
        self.assertIsNone(ingest_kr.strength_of("n/a"))

    def test_forms(self):
        self.assertEqual(ingest_kr.form_base_kr("정제,저작정"), "tablet")
        self.assertEqual(ingest_kr.form_base_kr("경질캡슐제"), "capsule")
        self.assertEqual(ingest_kr.form_base_kr("주사제"), "injection")
        self.assertEqual(ingest_kr.form_base_kr("점안제(점안액)"), "ophthalmic")
        self.assertEqual(ingest_kr.form_base_kr("크림제,겔제,젤리"), "topical")
        self.assertEqual(ingest_kr.form_base_kr(""), "unknown")
        self.assertEqual(ingest_kr.form_base_kr("기타제형"), "other")

    def test_release(self):
        self.assertEqual(ingest_kr.release_kr(["서방형정제"]), "ER")
        self.assertEqual(ingest_kr.release_kr(["장용정제"]), "DR")
        self.assertEqual(ingest_kr.release_kr(["정제,저작정"]), "none")

    def test_route(self):
        self.assertEqual(ingest_kr.route_kr("내복"), "oral")
        self.assertEqual(ingest_kr.route_kr("주사"), "injection")
        self.assertEqual(ingest_kr.route_kr("외용"), "topical")
        self.assertIsNone(ingest_kr.route_kr("기타"))


class Names(unittest.TestCase):
    """成分名候选：希腊字母 / 立体化学前缀 / 词序 / 显式别名。"""

    def test_greek_and_stereo(self):
        self.assertIn("valine", [k for k, _ in ingest_kr.kr_candidates("L-valine")])
        self.assertIn("gamma oryzanol",
                      [k for k, _ in ingest_kr.kr_candidates("γ-oryzanol")])
        self.assertIn("beta carotene",
                      [k for k, _ in ingest_kr.kr_candidates("β-carotene")])
        self.assertIn("methylephedrine",
                      [k for k, _ in ingest_kr.kr_candidates(
                          "dl-methylephedrine hydrochloride")])

    def test_explicit_alias(self):
        cands = dict(ingest_kr.kr_candidates("L-menthol"))
        self.assertEqual(cands.get("levomenthol"), "kr_alias")

    def test_token_order(self):
        self.assertIn("aluminum magnesium silicate",
                      [k for k, _ in ingest_kr.kr_candidates("magnesium aluminum silicate")])

    def test_new_ids(self):
        self.assertEqual(ingest_kr.new_substance_id("Paracetamol"), "paracetamol")
        self.assertTrue(ingest_kr.new_substance_id("아세트아미노펜").startswith("kr-"))


class StatusAndPack(unittest.TestCase):
    """状态只看真实취소일자；包装描述不臆造。"""

    def test_status(self):
        self.assertEqual(ingest_kr.item_status(
            {"real_cancel": False, "sentinel_cancel": False, "cancel_dates": []})[:2],
            ("active", None))
        self.assertEqual(ingest_kr.item_status(
            {"real_cancel": False, "sentinel_cancel": True,
             "cancel_dates": ["9999-01-01"]})[:2], ("active", None))
        status, date, note = ingest_kr.item_status(
            {"real_cancel": True, "sentinel_cancel": False, "cancel_dates": ["2020-01-01"]})
        self.assertEqual((status, date), ("unknown", None))
        self.assertIn("≠ 批文撤销", note)
        self.assertIn("2020-01-01", note)

    def test_pack(self):
        self.assertEqual(ingest_kr.pack_row({"약품규격": "250밀리그램", "제품총수량": "16",
                                             "제형구분": "정", "포장형태": "PTP"}),
                         "250밀리그램 16정 PTP")
        self.assertEqual(ingest_kr.pack_row({"약품규격": "500그램", "제품총수량": "1",
                                             "제형구분": "기타", "포장형태": "기타"}),
                         "500그램 1")
        self.assertEqual(ingest_kr.pack_row({"약품규격": "없음", "제품총수량": "0",
                                             "제형구분": "", "포장형태": ""}), "")

    def test_product_id(self):
        self.assertEqual(ingest_kr.item_product_id("199905709"), "KR-199905709")


class TinyCsvSnapshot(unittest.TestCase):
    """最小 CP949 CSV：配方码 join、品目聚合、多写名、状态、ATC。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.ing_path = tmp / "ing.csv"
        cls.std_path = tmp / "std.csv"
        with cls.ing_path.open("w", encoding=ingest_kr.ENCODING, newline="") as f:
            w = csv.writer(f)
            w.writerow(ING_HEADER)
            w.writerow(_ing_row())                                      # 单方 paracetamol
            w.writerow(_ing_row(일반명코드="200202ATB", 일반명="codeine",
                                함량="10", 단위="mg"))                  # 复方第二成分
        with cls.std_path.open("w", encoding=ingest_kr.ENCODING, newline="") as f:
            w = csv.writer(f)
            w.writerow(STD_HEADER)
            w.writerow(_std_row(한글상품명="타이레놀정500밀리그람",
                                약품규격="500밀리그램", 제품총수량="20", 제형구분="정",
                                포장형태="PTP", 성분코드="100101ATB",
                                ATC="N02BE01"))
            w.writerow(_std_row(한글상품명="타이레놀정500밀리그람 (새포장)",
                                약품규격="500밀리그램", 제품총수량="20", 제형구분="정",
                                포장형태="PTP", 표준코드="8800000000002",
                                성분코드="100101ATB", ATC="N02BE01"))
            w.writerow(_std_row(한글상품명="코데인복합정", 약품규격="없음",
                                품목기준코드="199905710", 표준코드="8800000000003",
                                성분코드="200202ATB", 취소일자="2020-01-01"))
        cls.ingredients = ingest_kr.load_ingredients(cls.ing_path)
        cls.items = ingest_kr.load_items(cls.ingredients, cls.std_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_ingredient_join(self):
        self.assertEqual(set(self.ingredients), {"100101ATB", "200202ATB"})
        self.assertEqual(self.ingredients["200202ATB"][0]["name"], "codeine")

    def test_item_aggregation(self):
        self.assertEqual(len(self.items), 2)
        item = self.items["199905709"]
        self.assertEqual(item["rows"], 2)
        self.assertEqual(sorted(item["names"]),
                         sorted(["타이레놀정500밀리그람", "타이레놀정500밀리그람 (새포장)"]))
        self.assertEqual(item["packs"], ["500밀리그램 20정 PTP"])
        self.assertEqual(item["codes"], ["100101ATB"])
        self.assertEqual(item["atcs"].most_common(1)[0][0], "N02BE01")
        self.assertEqual(item["forms"], ["정제,저작정"])

    def test_canceled_item(self):
        item = self.items["199905710"]
        self.assertTrue(item["real_cancel"])
        self.assertEqual(ingest_kr.item_status(item)[0], "unknown")

    def test_component_dedup(self):
        # 同一配方码在品目里被两行引用 → 成分只取一次
        self.assertEqual(len(self.items["199905709"]["components"]), 1)
        self.assertEqual(self.items["199905709"]["components"][0]["amount"], "500")


@unittest.skipUnless(STD is not None and ING is not None,
                     "没有 data/raw/kr 快照（CI 无快照时跳过）")
class SnapshotCounts(unittest.TestCase):
    """整包快照：条数与评估报告一致（2026-11-22 快照）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ingredients = ingest_kr.load_ingredients()
        cls.items = ingest_kr.load_items(cls.ingredients)

    def test_rows(self):
        self.assertEqual(len(self.items), 97356)
        self.assertEqual(len(self.ingredients), 20465)
        self.assertEqual(ingest_kr._csv_rows(STD), 309889)
        self.assertEqual(ingest_kr._csv_rows(ING), 60750)

    def test_join_coverage(self):
        with_code = sum(1 for r in self.items.values() if r["codes"])
        self.assertEqual(with_code, 50595)
        missing = sum(1 for r in self.items.values() if r["missing_codes"])
        self.assertEqual(missing, 69)

    def test_status_counts(self):
        active = sum(1 for r in self.items.values() if not r["real_cancel"])
        unknown = sum(1 for r in self.items.values() if r["real_cancel"])
        self.assertEqual((active, unknown), (65086, 32270))


if __name__ == "__main__":
    unittest.main()
