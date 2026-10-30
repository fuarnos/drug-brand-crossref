"""常用药双向对照审计（只读，task-140）。

回答：CN / US 各取产品数 Top-N 的成分，在对方市场是否查得到？查不到的，逐条归因——
`synonym`（同物异名，如 Glibenclamide/Glyburide）、`same_base`（盐/酯/水合物或描述词差异）、
`non_drug`（辅料/气体/溶剂）、`cosmetic`（防晒/化妆活性物）、`market_absent`（市场未上市）。

输出：
- CSV 明细（默认 data/sources/crossref-audit-20261030.csv）
- 终端摘要（分类计数 + 每条缺口的归因与「对方市场的同物候选」）

约束：只读开库（mode=ro），不写 data/drugs.db；只做身份对照，不判断可替代。

用法：
    & $py db/crossref_audit.py --top 100
    & $py db/crossref_audit.py --top 30 --out .tmp/crossref-audit.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"

# 盐 / 水合物 / 酯 / 前药后缀（归一化后按词匹配，命中即从 base 名去掉）
SALT_TOKENS = {
    "hydrochloride", "hydrobromide", "hydroiodide", "sulfate", "sulphate", "bisulfate",
    "sodium", "potassium", "calcium", "magnesium", "zinc", "lithium", "ammonium",
    "tartrate", "bitartrate", "maleate", "mesylate", "besylate", "tosylate",
    "fumarate", "succinate", "citrate", "phosphate", "diphosphate", "acetate",
    "nitrate", "chloride", "bromide", "iodide", "oxide", "hydroxide", "carbonate",
    "lactate", "gluconate", "oxalate", "malate", "benzoate", "salicylate",
    "propionate", "valerate", "butyrate", "palmitate", "stearate", "oleate",
    "hydrate", "monohydrate", "dihydrate", "trihydrate", "anhydrous",
    "hemihydrate", "sesquihydrate", "decanoate", "enanthate", "cypionate",
    "undecanoate", "dipropionate", "acetonide", "medoxomil", "cilexetil",
    "axetil", "pivoxil", "proxetil", "fosamil", "etabonate", "trifenatate",
    "acid", "unspecified", "form", "synthetic",
}

# 同物异名组（INN vs USAN / 拼写差异）；组内互相视为同一成分的候选
SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("glucose", "dextrose"),
    ("chlorphenamine", "chlorpheniramine"),
    ("glycerol", "glycerin", "glycerine"),
    ("manitol", "mannitol"),
    ("glibenclamide", "glyburide"),
    ("salbutamol", "albuterol"),
    ("lignocaine", "lidocaine"),
    ("adrenaline", "epinephrine"),
    ("noradrenaline", "norepinephrine"),
    ("frusemide", "furosemide"),
    ("hyoscine", "scopolamine"),
    ("isoprenaline", "isoproterenol"),
    ("tetracaine", "amethocaine"),
    ("rifampicin", "rifampin"),
    ("ciclosporin", "cyclosporine"),
    ("norethisterone", "norethindrone"),
    ("oestradiol", "estradiol"),
    ("amoxycillin", "amoxicillin"),
    ("cephalexin", "cefalexin"),
    ("cephradine", "cefradine"),
)

# 非药品：辅料 / 医用气体 / 溶剂 / 防晒与化妆活性物（不参与「药品跨市场对照」口径）
NON_DRUG = {
    "alcohol", "isopropyl alcohol", "oxygen", "water for injection", "purified water",
    "dimethicone", "petrolatum", "mineral oil", "talc", "silica",
    "sodium fluoride", "aluminum chlorohydrate", "aluminum zirconium tetrachlorohydrex g",
    "aluminum sesquichlorohydrate", "zinc pyrithione", "pyrithione zinc",
}
COSMETIC = {
    "octisalate", "octinoxate", "octocrylene", "avobenzone", "homosalate",
    "ensulizole", "oxybenzone", "benzophenone", "titanium dioxide", "zinc oxide",
    "padimate o", "cinoxate", "meradimate", "sulisobenzone", "drometrizole",
}


def norm(name: str) -> str:
    """小写、标点归一为空格（Povidone-Iodine -> povidone iodine）。"""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def base_name(name: str) -> str:
    """去掉盐/酯/水合物词，得到对照用的 base 名。"""
    words = [w for w in norm(name).split() if w not in SALT_TOKENS]
    return " ".join(words).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="常用药双向对照审计（只读）")
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--out", default=str(ROOT / "data" / "sources" / "crossref-audit-20261030.csv"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    names = {
        sid: (en, zh or "")
        for sid, en, zh in con.execute("SELECT substance_id, inn_en, inn_zh FROM substance")
    }

    def load_counts(country: str) -> dict[str, int]:
        rows = con.execute(
            """
            SELECT v.substance_id, COUNT(DISTINCT p.product_id) n
            FROM product p
            JOIN product_component pc ON pc.product_id = p.product_id
            JOIN variant v            ON v.variant_id = pc.variant_id
            WHERE p.country = ?
            GROUP BY v.substance_id
            """,
            (country,),
        )
        return {sid: n for sid, n in rows}

    cnt = {c: load_counts(c) for c in ("CN", "US")}
    by_base: dict[str, set[str]] = {}
    for sid, (en, _zh) in names.items():
        by_base.setdefault(base_name(en), set()).add(sid)

    synonym_of: dict[str, set[str]] = {}
    for group in SYNONYM_GROUPS:
        for member in group:
            synonym_of[member] = set(group) - {member}

    rows: list[dict[str, object]] = []
    for side, partner in (("CN", "US"), ("US", "CN")):
        top = sorted(cnt[side].items(), key=lambda kv: -kv[1])[: args.top]
        for rank, (sid, n) in enumerate(top, 1):
            en, zh = names.get(sid, ("", ""))
            partner_n = cnt[partner].get(sid, 0)
            base = base_name(en)
            same_base = sorted(by_base.get(base, set()) - {sid}) if len(base) >= 3 else []
            base_hits = [(h, cnt[partner].get(h, 0)) for h in same_base if cnt[partner].get(h, 0) > 0]

            syn_hits: list[tuple[str, int]] = []
            for alias in synonym_of.get(base, set()):
                for h in by_base.get(alias, set()):
                    if h != sid and cnt[partner].get(h, 0) > 0:
                        syn_hits.append((h, cnt[partner][h]))

            if partner_n > 0:
                verdict = "present"
            elif syn_hits:
                verdict = "synonym"
            elif base_hits:
                verdict = "same_base"
            elif base in NON_DRUG or norm(en) in NON_DRUG:
                verdict = "non_drug"
            elif base in COSMETIC or norm(en) in COSMETIC:
                verdict = "cosmetic"
            else:
                verdict = "market_absent"

            hits = syn_hits if verdict == "synonym" else base_hits if verdict == "same_base" else []
            rows.append(
                {
                    "side": side,
                    "rank": rank,
                    "substance_id": sid,
                    "inn_en": en,
                    "inn_zh": zh,
                    "home_n": n,
                    "partner_n": partner_n,
                    "verdict": verdict,
                    "base": base,
                    "partner_candidates": "|".join(
                        f"{names.get(h, ('', ''))[0]}:{pn}" for h, pn in hits
                    ),
                }
            )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    if args.quiet:
        print(f"written {out} ({len(rows)} rows)")
        return 0

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    order = ("present", "synonym", "same_base", "non_drug", "cosmetic", "market_absent")
    for side, partner in (("CN", "US"), ("US", "CN")):
        sub = [r for r in rows if r["side"] == side]
        stats = {k: sum(1 for r in sub if r["verdict"] == k) for k in order}
        print(f"== {side} Top{args.top} 成分 -> 在 {partner} 是否有产品 ==")
        for k in order:
            print(f"  {k:<14}: {stats[k]}")
        for r in sub:
            if r["verdict"] in ("synonym", "same_base"):
                print(f"    - {r['inn_en']} ({side} {r['home_n']}) ==> {r['partner_candidates']}")
    print(f"\nCSV: {out}  rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
