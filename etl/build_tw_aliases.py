#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TW TFDA 未匹配成分 token → 库内 substance 的别名映射（task-67）。

只读 `data/drugs.db`；输入为 task-54 dry-run 的未匹配 token 清单
（`.tmp/tw-ingest/full_dryrun-unmatched.csv` / `unmatched_tokens.csv`）与
dry-run 明细（用于算覆盖率）；输出 `data/tw_ingredient_aliases.csv`。

匹配顺序（每步都保留证据）：
  1. 归一后与 `substance.inn_en` 精确匹配（大写/去括号/去空格标点）；
  2. 词序变体（如 PANTOTHENATE CALCIUM → CALCIUM PANTOTHENATE）；
  3. 盐/酯/水合物剥离后匹配（HCL/HBR/SODIUM/…；盐型再到 `variant.salt` 校验）；
  4. 人工 BAN/USAN/旧名同义表（如 GUAIACOL GLYCERYL ETHER→guaifenesin、
     IODOCHLORHYDROXYQUIN→clioquinol、RETINOIC ACID→tretinoin）；
  5. 名称相似度（≥0.90 且唯一 → medium；0.86–0.90 → 仅记 uncertain 候选，不写 substance_id）；
  6. 仍判不了：若同义表能给出 INN 名（库内无该成分）→ `suggested_inn_not_in_db`；
     生物制品/疫苗/植物提取物/乱码 → 分类记 `unresolved`/`biologic`/`plant`/`junk`。

产物：
  data/tw_ingredient_aliases.csv   tw_token/inn_en/substance_id/salt/evidence/confidence/…
  .tmp/tw-alias/stats.json         样本/全量覆盖率 before-after、映射类型分布
  .tmp/tw-alias/top_unmapped.txt   剩余缺口 top
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
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
TMP_IN = ROOT / ".tmp" / "tw-ingest"
OUT = ROOT / "data" / "tw_ingredient_aliases.csv"
TMP = ROOT / ".tmp" / "tw-alias"

# 盐/酯/水合物 token（英文 INN 尾部；剥离后用于 base 匹配）
SALT_TOKENS = {
    "HCL", "HYDROCHLORIDE", "HBR", "HYDROBROMIDE", "SODIUM", "POTASSIUM",
    "CALCIUM", "MAGNESIUM", "ZINC", "IRON", "AMMONIUM", "NITRATE", "SULFATE",
    "SULPHATE", "BISULFATE", "BISULPHATE", "PHOSPHATE", "CITRATE", "TARTRATE",
    "MALEATE", "FUMARATE", "HEMIFUMARATE", "SUCCINATE", "BESYLATE", "MESYLATE",
    "TOSYLATE", "LACTATE", "GLUCONATE", "CARBONATE", "BICARBONATE", "OXIDE",
    "HYDROXIDE", "TRIHYDRATE", "DIHYDRATE", "MONOHYDRATE", "HEMIHYDRATE",
    "ANHYDROUS", "HYDRATE", "PROPIONATE", "DIPROPIONATE", "PALMITATE",
    "STEARATE", "VALERATE", "ACETATE", "BENZOATE", "ACETONIDE", "PIVOXIL",
    "AXETIL", "MEDOXOMIL", "DISODIUM", "DIPOTASSIUM", "BISULFITE", "SULFONATE",
    "TROMETAMOL", "MEGLUMINE", "CHOLINE", "LYSINE", "ARGININE",
}
STEREO = {"L", "D", "DL", "RS", "S", "R"}
# 人工同义表（TW 常见 BAN/USAN/旧名 → 规范 INN）。值可以是库内名称或标准 INN。
SYNONYMS = {
    "GUAIACOLGLYCERYLETHER": "GUAIFENESIN",
    "GLYCERYLGUAIACOLATE": "GUAIFENESIN",
    "GUAIACOLGLYCOLATE": "GUAIFENESIN",
    "IODOCHLORHYDROXYQUIN": "CLIOQUINOL",
    "RETINOICACID": "TRETINOIN",
    "METAPROTERENOL": "ORCIPRENALINE",
    "METAPROTERENOLSULFATE": "ORCIPRENALINE",
    "PANTOTHENATECALCIUM": "CALCIUMPANTOTHENATE",
    "GLYCYRRHIZINICACID": "GLYCYRRHIZIN",
    "BASICALUMINUMSUCROSE SULFATE": "SUCRALFATE",
    "BASICALUMINUMSUCROSE SULFATE": "SUCRALFATE",
    "CARBOCYSTEINE": "CARBOCISTEINE",
    "TRIGLYCERIDESMEDIUMCHAIN": "MEDIUMCHAINTRIGLYCERIDES",
    "CLOBETASOL17PROPIONATE": "CLOBETASOLPROPIONATE",
    "ESTRADIOLETHINYL": "ETHINYLESTRADIOL",
    "METHIONINEDL": "METHIONINE",
    "LYSINEHCL": "LYSINE",
    "HISTIDINEHCL": "HISTIDINE",
    "DEXTROMETHORPHANHBR": "DEXTROMETHORPHAN",
    "BUTYLSCOPOLAMINEBROMIDE": "SCOPOLAMINEBUTYLBROMIDE",
    "ACETAMIDOCAPROICACIDEPSILON": "AMINOCAPROICACID",
    "EPSILONAMINOCAPROICACID": "AMINOCAPROICACID",
    "CETUXIMABCHIMERICANTIBODY": "CETUXIMAB",
    "POTASSIUMCRESOLSULFONATE": "POTASSIUMCRESOLSULFONATE",
    "POLYCRESOLSULFONATE": "POLICRESULEN",
    "SENNOSIDE": "SENNOSIDES",
    "SCOPOLIAEXTRACT": "SCOPOLIA",
    # TW/旧药（库内很可能没有）→ 标准 INN 建议
    "DLMETHYLEPHEDRINE": "METHYLEPHEDRINE",
    "METHYLEPHEDRINE": "METHYLEPHEDRINE",
    "GUAIACOLSULFONATE": "POTASSIUM GUAIACOLSULFONATE",
    "ORYZANOLGAMMA": "ORYZANOL",
    "CRYSTALLINEGLUCOSAMINESULFATE": "GLUCOSAMINE SULFATE",
    "DIASTASEBIO": "DIASTASE",
    "GLYCYRRHIZINATEDIPOTASSIUM": "GLYCYRRHIZIN",
    "CHLOROPHYLLSODIUMCOPPER": "CHLOROPHYLLINS",
    "MEPHENOXALONE": "MEPHENOXALONE",
    "NITROFURAZONE": "NITROFURAZONE",
    "EPRAZINONE": "EPRAZINONE",
    "PROSULTIAMINE": "PROSULTIAMINE",
    "VITAMINU": "VITAMIN U",
    "DISULFIDE": "THIAMINE DISULFIDE",
    "ETHENZAMIDE": "ETHENZAMIDE",
    "NOSCAPINE": "NOSCAPINE",
    "POTASSIUMGUAIACOLSULFONATE": "POTASSIUM GUAIACOLSULFONATE",
    "BROMISOVALUM": "BROMISOVAL",
    "SILYMARIN": "SILYMARIN",
    "OROTICACID": "OROTIC ACID",
    "THIAMINEDISULFIDE": "THIAMINE DISULFIDE",
    "OXETHAZAINE": "OXETHAZAINE",
    "ISOCONAZOLENITRATE": "ISOCONAZOLE",
    "CEPHRADINE": "CEPHALORIDINE",
    "CHLORMEZANONE": "CHLORMEZANONE",
    "DIPHENIDOLHYDROCHLORIDE": "DIPHENIDOL",
    "DIPHENIDOL": "DIPHENIDOL",
    "ALUMINUMSILICATE": "ALUMINUM SILICATE",
    "BUTAMIRATECITRATE": "BUTAMIRATE",
    "TIPEPIDINEHIBENZATE": "TIPEPIDINE",
    "ETOFENAMATE": "ETOFENAMATE",
    "OXOLAMINECITRATE": "OXOLAMINE",
    "HYDROPROPIZINE": "HYDROPROPIZINE",
    "ENOXOLONE": "ENOXOLONE",
    "DIPHENIDOL": "DIPHENIDOL",
}
BIO_WORDS = ("VIRUS", "VACCINE", "TOXOID", "ANTIBODY", "PROTEIN", "CELL",
             "BACTERI", "IMMUNOGLOBULIN", "ANTIGEN", "PLASMA", "SERUM")
PLANT_WORDS = ("EXTRACT", "SILYMARIN", "GLYCYRRHIZ", "SENNOSIDE", "SCOPOLIA",
               "FISH-OIL", "OMEGA", "HERB", "ROOT", "LEAF", "SEED", "POLLEN",
               "GLYCYRRHIZINIC", "ESCIN", "PLACENTA", "PANCREATIN", "PEPSIN")
RE_PAREN = re.compile(r"\([^)]*\)")


def nk(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").upper()
    s = RE_PAREN.sub(" ", s)
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def key(s: str) -> str:
    return re.sub(r"\s+", "", nk(s))


def strip_salt(k: str) -> tuple[str, list[str]]:
    """去掉盐/水合 token 和立体前缀 → (base_key, 识别到的盐 token 列表)。"""
    toks = k.split()
    salts = [t for t in toks if t in SALT_TOKENS]
    base = [t for t in toks if t not in SALT_TOKENS and t not in STEREO]
    return "".join(base) if base else "", salts


SALT_COMPACT = {
    "HYDROCHLORIDE": "HYDROCHLORIDE", "DIHYDROCHLORIDE": "HYDROCHLORIDE",
    "HCL": "HYDROCHLORIDE", "HYDROBROMIDE": "HYDROBROMIDE", "HBR": "HYDROBROMIDE",
    "SODIUM": "SODIUM", "POTASSIUM": "POTASSIUM", "CALCIUM": "CALCIUM",
    "MAGNESIUM": "MAGNESIUM", "NITRATE": "NITRATE", "SULFATE": "SULFATE",
    "SULPHATE": "SULFATE", "BISULFATE": "SULFATE", "PHOSPHATE": "PHOSPHATE",
    "CITRATE": "CITRATE", "TARTRATE": "TARTRATE", "MALEATE": "MALEATE",
    "MALEICACID": "MALEATE", "FUMARATE": "FUMARATE", "FUMARICACID": "FUMARATE",
    "HEMIFUMARATE": "FUMARATE", "SUCCINATE": "SUCCINATE", "SUCCINICACID": "SUCCINATE",
    "BESYLATE": "BESYLATE", "MESYLATE": "MESYLATE", "TOSYLATE": "TOSYLATE",
    "LACTATE": "LACTATE", "GLUCONATE": "GLUCONATE", "CARBONATE": "CARBONATE",
    "BICARBONATE": "BICARBONATE", "OXIDE": "OXIDE", "HYDROXIDE": "HYDROXIDE",
    "TRIHYDRATE": "TRIHYDRATE", "DIHYDRATE": "DIHYDRATE",
    "MONOHYDRATE": "MONOHYDRATE", "ANHYDROUS": "ANHYDROUS",
    "PROPIONATE": "PROPIONATE", "DIPROPIONATE": "DIPROPIONATE",
    "PALMITATE": "PALMITATE", "STEARATE": "STEARATE", "VALERATE": "VALERATE",
    "ACETATE": "ACETATE", "BENZOATE": "BENZOATE", "TROMETAMOL": "TROMETAMOL",
    "MEGLUMINE": "MEGLUMINE",
}


def strip_salt_compact(k: str) -> tuple[str, list[str]]:
    """compact key（无空格）去盐/立体前缀：DL-METHYLEPHEDRINEHCL → METHYLEPHEDRINE。"""
    words: list[str] = []
    k = k.upper()
    # 立体前缀
    while k.startswith("DL") and len(k) > 4:
        k = k[2:]
    # 后缀盐（长词优先）
    changed = True
    while changed:
        changed = False
        for w in sorted(SALT_COMPACT, key=len, reverse=True):
            if k.endswith(w) and len(k) > len(w) + 2:
                words.append(SALT_COMPACT[w])
                k = k[: -len(w)]
                changed = True
                break
    # 前缀盐（如 SODIUMRABEPRAZOLE）
    changed = True
    while changed:
        changed = False
        for w in sorted(SALT_COMPACT, key=len, reverse=True):
            if k.startswith(w) and len(k) > len(w) + 2:
                words.append(SALT_COMPACT[w])
                k = k[len(w):]
                changed = True
                break
    return k, words


def pick_sid(sids: list[str]) -> str:
    """同名/同义命中多个 id 时优先英文 id（非 mx-es-/cn-），再取最短。"""
    en = [s for s in sids if not s.startswith(("mx-es-", "cn-"))]
    pool = en or sids
    return sorted(pool, key=lambda x: (len(x), x))[0]


def sid_result(sid: str, part: str, evidence: str, confidence: str,
               salt: str = "") -> dict:
    """西语/中文重复成分 id 不能当英文 INN 映射结果 → 记 suggested。"""
    if sid.startswith(("mx-es-", "cn-")):
        return dict(status="suggested_inn_not_in_db", confidence="medium",
                    inn_en=part.upper(), substance_id="", salt="",
                    evidence=evidence + f"；库内仅有西语/中文重复成分 {sid}，无英文 INN")
    return dict(status="mapped", confidence=confidence, inn_en="", substance_id=sid,
                salt=salt, evidence=evidence)


def salt_variant_check(con: sqlite3.Connection, sid: str,
                       salt_words: list[str]) -> tuple[bool, str]:
    if not salt_words:
        return True, ""
    want = [w.lower() for w in salt_words]
    for r in con.execute("SELECT salt, salt_code FROM variant WHERE substance_id=?", (sid,)):
        text = ((r[0] or "") + " " + (r[1] or "")).lower()
        if any(w in text for w in want):
            return True, (r[0] or r[1] or "")
    return False, ""


def main() -> int:
    ap = argparse.ArgumentParser(description="TW 未匹配 token → INN 别名映射（只读 DB）")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--dry-run", action="store_true", help="只打印统计，不写 CSV")
    args = ap.parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"FATAL: DB 不存在: {db_path}", file=sys.stderr)
        return 2
    con = sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    # DB 索引
    inn_sid: dict[str, list[str]] = defaultdict(list)
    sid_inn: dict[str, str] = {}
    for r in con.execute("SELECT substance_id, inn_en FROM substance WHERE inn_en IS NOT NULL"
                         " AND trim(inn_en)<>''"):
        sid_inn[r["substance_id"]] = r["inn_en"]
        inn_sid[key(r["inn_en"])].append(r["substance_id"])
    # 去盐基索引（DB 内 inn_en 自身）
    base_sid: dict[str, list[str]] = defaultdict(list)
    for k, sids in inn_sid.items():
        b, _ = strip_salt(k)
        if b:
            base_sid[b].extend(sids)
    # 输入
    full_tok = list(csv.DictReader(open(TMP_IN / "full_dryrun-unmatched.csv",
                                        encoding="utf-8-sig")))
    sample_tok = list(csv.DictReader(open(TMP_IN / "unmatched_tokens.csv",
                                          encoding="utf-8-sig")))
    sample_occ = {r["token"]: int(r["count"]) for r in sample_tok}
    full_occ = {r["token"]: int(r["count"]) for r in full_tok}
    tokens = sorted(full_occ, key=lambda t: -full_occ[t])
    stats_in = json.load(open(TMP_IN / "full_dryrun-stats.json", encoding="utf-8"))
    sample_stats = json.load(open(TMP_IN / "stats.json", encoding="utf-8"))

    def match_one(token: str) -> dict:
        raw = token
        # 多 token（; 分隔）取第一个可映射段
        parts = [p.strip() for p in re.split(r"[;+]", token) if p.strip()] or [token]
        best = None
        for part in parts:
            r = _match_part(part, raw)
            if r and (best is None or _rank(r) > _rank(best)):
                best = r
        return best or dict(status="unresolved", confidence="uncertain",
                            inn_en="", substance_id="", salt="",
                            evidence="无匹配候选（库内无此成分/生物制品/植物提取物/乱码）")

    def _rank(r: dict) -> int:
        return {"high": 3, "medium": 2, "uncertain": 1}.get(r.get("confidence"), 0)

    def _match_part(part: str, raw: str) -> dict | None:
        k = key(part)
        if not k:
            return None
        # 1) 精确
        if k in inn_sid:
            sid = pick_sid(inn_sid[k])
            return sid_result(sid, k, "与 substance.inn_en 精确匹配（归一后）", "high")
        # 2) 词序变体（2–4 词全排列）
        toks = k.split()
        if 2 <= len(toks) <= 4 and len(toks) <= 3:
            import itertools
            for perm in itertools.permutations(toks):
                kk = "".join(perm)
                if kk in inn_sid:
                    sid = pick_sid(inn_sid[kk])
                    return sid_result(sid, kk, f"词序变体匹配（{part}）", "medium")
        # 3) 盐/立体前缀剥离（compact 写法）
        b, salts = strip_salt_compact(k)
        cands = [b]
        if b and b[0] in "LD" and len(b) > 3:
            cands.append(b[1:])
        for cand in cands:
            if cand and cand in inn_sid:
                sid = pick_sid(inn_sid[cand])
                ok, salt_text = salt_variant_check(con, sid, salts)
                return sid_result(
                    sid, cand, (f"去盐/立体前缀后匹配 substance.inn_en；识别盐: "
                                f"{salts or '无'}"
                                + ("" if ok else "（库内无对应盐 variant，按 base 记录）")),
                    "high" if ok else "medium", salt_text)
            if cand and cand in base_sid:
                sid = pick_sid(base_sid[cand])
                return sid_result(sid, cand, "去盐后与库内成分碱基名匹配", "medium")
        # 4) 同义表
        syn = SYNONYMS.get(k) or SYNONYMS.get(b) or ""
        if syn:
            sk = key(syn)
            if sk in inn_sid:
                sid = pick_sid(inn_sid[sk])
                return sid_result(sid, sk, f"人工同义表：{part}", "medium")
            return dict(status="suggested_inn_not_in_db", confidence="medium",
                        inn_en=syn, substance_id="", salt="",
                        evidence=f"人工同义表识别为 {syn}，但库内无该成分")
        # 5) 名称相似度
        target = b or k
        best = (0.0, "")
        digits = sorted(set(re.findall(r"\d+", target)))
        if len(target) >= 5 and len(target) <= 60 and "SEROTYPE" not in target:
            for dbk, sids in inn_sid.items():
                if abs(len(dbk) - len(target)) > 5:
                    continue
                # 数字/血清型必须一致（PNEUMOCOCCAL … SEROTYPE 7F ≠ 19F）
                if digits and sorted(set(re.findall(r"\d+", dbk))) != digits:
                    continue
                r = difflib.SequenceMatcher(None, target, dbk).ratio()
                if r > best[0]:
                    best = (r, dbk)
        if best[0] >= 0.90 and best[1]:
            sid = pick_sid(inn_sid[best[1]])
            return sid_result(sid, best[1],
                              f"名称相似度 {best[0]:.2f}（{target} ≈ {sid_inn[sid]}）",
                              "medium")
        if best[0] >= 0.86 and best[1]:
            return dict(status="uncertain", confidence="uncertain",
                        inn_en=sid_inn[pick_sid(inn_sid[best[1]])], substance_id="", salt="",
                        evidence=f"名称相似度 {best[0]:.2f}，低于自动映射门槛（候选 {best[1]}）")
        # 6) 分类缺口
        up = nk(part)
        cat = ""
        if any(w in up for w in BIO_WORDS):
            cat = "biologic_or_vaccine"
        elif any(w in up for w in PLANT_WORDS):
            cat = "plant_or_tcm"
        elif len(re.sub(r"[^A-Z]", "", up)) < 3 or not re.search(r"[AEIOU]", up):
            cat = "junk_or_abbrev"
        return dict(status="unresolved", confidence="uncertain", inn_en="",
                    substance_id="", salt="",
                    evidence={"biologic_or_vaccine": "生物制品/疫苗（保留 unmapped，不硬造）",
                              "plant_or_tcm": "植物/中药提取物（需与中藥边界一起定标）",
                              "junk_or_abbrev": "乱码/缩写，无法判断"}.get(
                                  cat, "无匹配候选"))

    rows = []
    for tok in tokens:
        r = match_one(tok)
        if r.get("status") == "mapped" and r.get("substance_id"):
            r["inn_en"] = sid_inn.get(r["substance_id"], r.get("inn_en", ""))
        r.update(tw_token=tok, occ_full=full_occ.get(tok, 0),
                 occ_sample=sample_occ.get(tok, 0))
        rows.append(r)
    # 统计
    mapped = [r for r in rows if r["status"] == "mapped"]
    suggested = [r for r in rows if r["status"] == "suggested_inn_not_in_db"]
    unresolved = [r for r in rows if r["status"] == "unresolved"]
    uncertain = [r for r in rows if r["status"] == "uncertain"]
    mapped_occ_full = sum(r["occ_full"] for r in mapped)
    mapped_occ_sample = sum(r["occ_sample"] for r in mapped)
    total_full = stats_in["components"]["tokens_total"]
    matched_full = stats_in["components"]["tokens_matched"]
    total_sample = sample_stats["components"]["tokens_total"]
    matched_sample = sample_stats["components"]["tokens_matched"]

    def rowlevel(dryrun_path: Path, mapped_keys: set[str]) -> tuple[int, int]:
        rows_ = list(csv.DictReader(open(dryrun_path, encoding="utf-8-sig")))
        all_matched = 0
        for row in rows_:
            unm = [t.strip() for t in (row.get("unmapped_tokens") or "").split(";")
                   if t.strip()]
            if not unm:
                all_matched += 1
                continue
            if all(key(t) in mapped_keys or key(t) in
                   {key(m["tw_token"]) for m in mapped} for t in unm):
                all_matched += 1
        return all_matched, len(rows_)

    mapped_keys = {key(r["tw_token"]): r for r in mapped}
    # 用映射结果重新评估行级（逐 token 查映射表）
    def rowlevel2(dryrun_path: Path, mapping: dict[str, str]) -> tuple[int, int]:
        rows_ = list(csv.DictReader(open(dryrun_path, encoding="utf-8-sig")))
        all_matched = 0
        for row in rows_:
            unm = [t.strip() for t in (row.get("unmapped_tokens") or "").split(";")
                   if t.strip()]
            if not unm or all(t in mapping for t in unm):
                all_matched += 1
        return all_matched, len(rows_)

    mapping = {r["tw_token"]: r["substance_id"] for r in mapped if r["substance_id"]}
    mapped_rows_full, total_rows_full = rowlevel2(TMP_IN / "full_dryrun.csv", mapping)
    mapped_rows_sample, total_rows_sample = rowlevel2(
        ROOT / "data" / "tw_ingest_dryrun.csv", mapping)
    stats = dict(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        db=str(db_path),
        full=dict(tokens_total=total_full, matched_before=matched_full,
                  coverage_before=round(matched_full / total_full, 4),
                  mapped_occurrences=mapped_occ_full,
                  coverage_after=round((matched_full + mapped_occ_full) / total_full, 4),
                  rows_total=total_rows_full,
                  rows_all_matched_before=stats_in["components"]["rows_with_all_matched"],
                  rows_all_matched_after=mapped_rows_full,
                  rows_full_match_rate_before=round(
                      stats_in["components"]["rows_with_all_matched"] / total_rows_full, 4),
                  rows_full_match_rate_after=round(mapped_rows_full / total_rows_full, 4)),
        sample=dict(tokens_total=total_sample, matched_before=matched_sample,
                    coverage_before=round(matched_sample / total_sample, 4),
                    mapped_occurrences=mapped_occ_sample,
                    coverage_after=round((matched_sample + mapped_occ_sample) / total_sample, 4),
                    rows_total=total_rows_sample,
                    rows_all_matched_before=sample_stats["components"]["rows_with_all_matched"],
                    rows_all_matched_after=mapped_rows_sample,
                    rows_full_match_rate_before=round(
                        sample_stats["components"]["rows_with_all_matched"] / total_rows_sample, 4),
                    rows_full_match_rate_after=round(mapped_rows_sample / total_rows_sample, 4)),
        distinct=dict(unmatched_before=len(rows), mapped=len(mapped),
                      suggested_inn=len(suggested), uncertain=len(uncertain),
                      unresolved=len(unresolved),
                      mapped_occurrences=sum(r["occ_full"] for r in mapped)),
        by_confidence=dict(Counter(r["confidence"] for r in mapped)),
        remaining_top=[[t, full_occ[t]] for t in
                       sorted((t for t in tokens
                               if any(r["tw_token"] == t and r["status"] in
                                      ("unresolved", "uncertain") for r in rows)),
                              key=lambda x: -full_occ[x])[:20]],
    )
    print(f"DB: {db_path}")
    print(f"未匹配 distinct {len(rows)}（样本/全量出现次数 {sum(sample_occ.values())}"
          f" / {sum(full_occ.values())}）")
    print(f"→ 映射到库内 substance: {len(mapped)} 个 token（全量 {mapped_occ_full} 次）")
    print(f"→ 识别 INN 但库内无成分（建议新成分）: {len(suggested)}")
    print(f"→ 名称相似度不足 uncertain: {len(uncertain)}；未解决 {len(unresolved)}")
    print(f"全量 token 覆盖率: {stats['full']['coverage_before']*100:.1f}% → "
          f"{stats['full']['coverage_after']*100:.1f}%;  行级全匹配 "
          f"{stats['full']['rows_full_match_rate_before']*100:.1f}% → "
          f"{stats['full']['rows_full_match_rate_after']*100:.1f}%")
    print(f"样本 token 覆盖率: {stats['sample']['coverage_before']*100:.1f}% → "
          f"{stats['sample']['coverage_after']*100:.1f}%")
    print("\n映射样例 top:")
    for r in sorted(mapped, key=lambda x: -x["occ_full"])[:20]:
        print(f"  {r['occ_full']:>4}  {r['tw_token']:<42} -> {r['inn_en']}"
              f" ({r['substance_id']}) [{r['confidence']}] {r['evidence'][:60]}")
    print("\n剩余缺口 top:")
    for t, n in stats["remaining_top"][:10]:
        print(f"  {n:>4}  {t}")
    if not args.dry_run:
        TMP.mkdir(parents=True, exist_ok=True)
        cols = ["tw_token", "status", "inn_en", "substance_id", "salt", "confidence",
                "evidence", "occ_full", "occ_sample"]
        rows_sorted = sorted(rows, key=lambda r: (-r["occ_full"], r["tw_token"]))
        with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows_sorted)
        (TMP / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
        top = "\n".join(f"{n}\t{t}" for t, n in
                        sorted(((t, full_occ[t]) for t in tokens), key=lambda x: -x[1])[:120])
        (TMP / "top_unmapped.txt").write_text(top, encoding="utf-8")
        print(f"\n写入 {OUT}（{len(rows)} 行）；统计 {TMP / 'stats.json'}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
