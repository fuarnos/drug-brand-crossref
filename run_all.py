"""一键重建：建库 → 美国入库（用本地缓存）→ 英国 dm+d → 西班牙 CIMA → 墨西哥 → 澳洲 PBS
→ 人工种子 → 品牌家族 → 静态站。

    python run_all.py             # 全量
    python run_all.py --no-ingest # 跳过入库（只重建站点）

美国入库依赖 data/raw/openfda/ndc-01.json 缓存；没有缓存时会尝试下载，
若 SSL 被中间人拦截（企业代理常见），先用 PowerShell 下好再重跑。
西班牙入库依赖 data/raw/cima/page-*.json 缓存（etl/ingest_cima.py 自己会下载）；
ATC 详情缓存在 data/raw/cima/atc/，首次需要联网，之后离线。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(script: str, *args: str) -> None:
    print(f"\n>>> {script} {' '.join(args)}".rstrip(), flush=True)
    t0 = time.time()
    r = subprocess.run([sys.executable, script, *args], cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit(f"{script} 失败（exit {r.returncode}）")
    print(f"    ok  {time.time() - t0:.1f}s", flush=True)


def backup_db() -> None:
    """anything that重建之前先留一份，删库这件事从此不该再发生。"""
    db = ROOT / "data" / "drugs.db"
    if not db.exists():
        return
    bdir = ROOT / "data" / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = bdir / f"drugs-{stamp}.db"
    shutil.copy2(db, dest)
    print(f"    备份 -> {dest.relative_to(ROOT)}  ({dest.stat().st_size / 1e6:.0f} MB)", flush=True)
    keep = sorted(bdir.glob("drugs-*.db"))[:-5]
    for old in keep:
        old.unlink()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ingest", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    if not args.no_backup:
        backup_db()
    run("db/init_db.py")
    if not args.no_ingest:
        cache = ROOT / "data/raw/openfda/ndc-01.json"
        if not cache.exists():
            print("警告：没有 openFDA 缓存，跳过美国入库", flush=True)
        else:
            run("etl/ingest_openfda_ndc.py")
        if list((ROOT / "data/raw/dmd").glob("nhsbsa_dmd_*.zip")):
            run("etl/ingest_dmd.py")
        else:
            print("提示：没有 dm+d 包，跳过英国入库（python etl/trud_fetch.py 可下载）",
                  flush=True)
        # 西班牙：CIMA 的列表页缓存；没有缓存也跑，脚本会自己下载 128 页
        run("etl/ingest_cima.py")
        # 墨西哥：COFEPRIS 的 26 个按年 PDF（data/raw/mx 缓存）+ 注销清单 + 浓度回填
        if (ROOT / "data/raw/mx/cofepris_alopaticos.csv").exists():
            run("etl/ingest_mx.py")
        else:
            print("提示：没有墨西哥抽取结果，跳过（python etl/mx_discover.py --download alop "
                  "然后 etl/extract_cofepris_alop.py）", flush=True)
        # 澳洲：PBS 官方 API 缓存（3 次请求，20 秒限速 → 约 1 分钟；python etl/fetch_pbs.py）
        if (ROOT / "data/raw/pbs/api/items.json").exists():
            run("etl/ingest_pbs.py")
        else:
            print("提示：没有 PBS 缓存，跳过澳洲（python etl/fetch_pbs.py 可抓）", flush=True)
        # 澳洲 OTC：TGA CMI 目录（注册类 OTC 的品牌→成分，无规格）
        if (ROOT / "data/raw/tga_cmi/cmi.json").exists():
            run("etl/ingest_tga_cmi.py")
        else:
            print("提示：没有 TGA CMI 缓存，跳过（python etl/fetch_tga_cmi.py 可抓）",
                  flush=True)
        # ARTG 名称层（eBS 目录，34k 条名称 + 申办方 + ARTG ID；无成分）
        if (ROOT / "data/raw/artg/medicine_index.jsonl").exists():
            run("etl/ingest_artg_index.py")
        else:
            print("提示：没有 ARTG 目录缓存，跳过（python etl/fetch_artg_index.py 可抓）",
                  flush=True)
        # 加拿大：Health Canada DPD Open API（9 个端点，一次全量；python etl/fetch_ca_dpd.py）
        if (ROOT / "data/raw/ca/dpd/drugproduct.json").exists():
            run("etl/ingest_ca_dpd.py")
        else:
            print("提示：没有加拿大 DPD 缓存，跳过（python etl/fetch_ca_dpd.py 可抓）",
                  flush=True)
    run("data/seed_manual.py")
    # 英国 salt 恢复：dm+d 原料名里带盐型（besilate/fumarate/trihydrate…），
    # ingest_dmd 只建 base variant，这里把组件改挂到盐 variant（幂等，需 --confirm-real-db）。
    if (ROOT / "data/raw/dmd").exists():
        run("etl/fix_dmd_salts.py", "--apply", "--confirm-real-db")
    # 品牌种子就位后，才能用 ARTG 名字给「已认识的品牌」补规格/剂型
    if (ROOT / "data/raw/artg/medicine_index.jsonl").exists():
        run("etl/ingest_artg_enrich.py")
    # ARTG Public Summary 详情：成分 + 规格（1,728 条消费品牌；抓取很慢，单独跑）
    if (ROOT / "data/raw/artg/details.jsonl").exists():
        run("etl/ingest_artg_details.py")
    run("data/seed_families.py")
    run("data/seed_nicknames.py")
    # 美国街头叫法（NIDA + DEA 补充）与 FDA 易混淆药对；都读 data/raw 快照，可离线重跑。
    run("etl/ingest_us_terms.py")
    # 社区叫法 / 各国街头叫法（CN/GB/AU/ES），人工策展 + 逐条 URL。
    run("etl/ingest_community_terms.py")
    # 清除毒品 / 娱乐性用药黑话（用户口径：只保留合法药品俗名；脚本幂等）。
    run("etl/clean_drug_terms.py", "--apply")
    # 中文互联网俗名（Tier B，全部进 drug_term；候选 CSV 在仓库里，可离线重跑）。
    if (ROOT / "data/cn_slang_candidates.csv").exists():
        run("etl/ingest_cn_slang.py", "--apply")
    # 盐型规范化（为 D2 折算铺路）、/warn 种子。
    run("etl/normalize_salts.py", "--apply", "--confirm-real-db")
    run("data/seed_warnings.py", "--apply", "--confirm-real-db")
    # ChEMBL ATC（CC BY-SA，只补空值；有缓存才跑）。
    if (ROOT / "data/raw/chembl").exists():
        run("etl/ingest_chembl_atc.py", "--apply", "--allow-real-db")
    # MX「每 mL / 每瓶」浓度（候选 CSV 在仓库里，幂等）。
    if (ROOT / "data/mx_pervolume_candidates.csv").exists():
        run("etl/ingest_mx_pervolume.py", "--apply", "--allow-real")
    run("etl/ingest_fda_confusable.py")
    # 覆盖表要显示「数据源自己的日期」，不是我们的抓取时间
    run("db/source_dates.py")
    run("site/build.py")
    print("\n全部完成。预览：python serve.py 8000")


if __name__ == "__main__":
    main()
