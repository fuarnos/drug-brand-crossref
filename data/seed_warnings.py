"""dose_warning 首批种子（D3 `/warn` 页）：人工策展的剂量/不可互换警示。

设计依据 reports/dose-mapping-plan.md §3。原则（写进数据，不靠自觉）：
  · 每条必须有 ≥1 个监管来源的 `source_url`（FDA/DailyMed、EMA、MHRA、Health
    Canada DPD、AEMPS CIMA、NMPA 等），`evidence` 只摘事实、≤200 字、不转载全文；
  · 没在本轮核实的条目标 `status='draft'`，只有报告里 [已验证] 的几条标 published；
  · published 条目 `reviewed_by` 至少两个名字（录入 + 核对）；
  · 措辞只做警示，不出现「等量替换 / 可互换 / 吃几片」这类用药建议。

本脚本**只定义数据 + 校验 + 幂等 upsert**，不主动写库：
    python data/seed_warnings.py --dry-run     # 默认：校验 + 打印统计 + 导审计 CSV
    python data/seed_warnings.py --apply --db PATH          # 写 dose_warning
    python data/seed_warnings.py --rollback --db PATH       # 用备份还原
    python data/seed_warnings.py --verify --db PATH

真实库 data/drugs.db 上的 --apply/--rollback 需要 --confirm-real-db。
写入前把被覆盖的旧行备份到 .tmp/dose-impl/backups/。
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "drugs.db"
DEFAULT_OUT = ROOT / ".tmp" / "dose-impl" / "seed_warnings.csv"
DEFAULT_BACKUP_DIR = ROOT / ".tmp" / "dose-impl" / "backups"

SEED_DATE = "2026-10-26"
SEED_TS = f"{SEED_DATE}T00:00:00Z"
REVIEWED_DRAFT = "dose-impl（待第二人复核）"
REVIEWED_PUBLISHED = "dose-mapping（审计）;dose-impl（录入）"

TRUSTED_DOMAINS = (
    "dailymed.nlm.nih.gov", "api.fda.gov", "accessdata.fda.gov", "fda.gov",
    "medicines.org.uk", "ema.europa.eu", "health-products.canada.ca",
    "cima.aemps.es", "nmpa.gov.cn", "pbs.gov.au", "tga.gov.au", "gov.uk",
)

FIELDS = ["warning_id", "substance_id", "related_substance_id", "country", "rule",
          "severity", "title_zh", "title_en", "title_es", "body_zh", "body_en",
          "body_es", "source_url", "evidence", "status", "reviewed_by",
          "created_at", "updated_at"]


def _w(wid: str, rule: str, severity: str, *, tzh: str, ten: str,
       bzh: str, ben: str, url: str, evidence: str,
       sid: str | None = None, rsid: str | None = None,
       country: str | None = None,
       status: str = "draft") -> dict:
    """构造一条 warning；es / time 字段统一由种子文件决定，减少重复。"""
    return {
        "warning_id": wid,
        "substance_id": sid,
        "related_substance_id": rsid,
        "country": country,
        "rule": rule,
        "severity": severity,
        "title_zh": tzh,
        "title_en": ten,
        "title_es": None,
        "body_zh": bzh,
        "body_en": ben,
        "body_es": None,
        "source_url": url,
        "evidence": evidence,
        "status": status,
        "reviewed_by": (REVIEWED_PUBLISHED if status == "published"
                        else REVIEWED_DRAFT),
        "created_at": SEED_TS,
        "updated_at": SEED_TS,
    }


DM = "https://dailymed.nlm.nih.gov/dailymed/search.cfm?labeltype=all&query="
EMC = "https://www.medicines.org.uk/emc/search?q="
FDA_NDC = "https://api.fda.gov/drug/ndc.json?search=generic_name:%22{}%22&limit=1"
NMPA = "https://www.nmpa.gov.cn/datasearch/home-index.html"
CIMA = "https://cima.aemps.es/cima/publico/lista.html"
DPD = "https://health-products.canada.ca/dpd-bdpp/index-eng.jsp"

WARNINGS: list[dict] = [
    # ---------- R4 同名不同药（/warn 区块 A） ----------
    _w("tylenol-vs-tainuo", "R4", "high",
       tzh="Tylenol 与泰诺不是同一种药",
       ten="Tylenol and 泰诺 (Tai Nuo) are not the same medicine",
       bzh="美国 Tylenol 通常为单方对乙酰氨基酚；中国的「泰诺」是含对乙酰氨基酚、"
           "伪麻黄碱、右美沙芬、氯苯那敏的复方感冒药。同名不等于同成分，混用会重复用药。",
       ben="In the US, Tylenol is usually single-ingredient acetaminophen. In China, "
           "泰诺 is a multi-ingredient cold medicine (acetaminophen + pseudoephedrine "
           "+ dextromethorphan + chlorpheniramine). Same name does not mean same actives.",
       url=DM + "tylenol", evidence="DailyMed Tylenol 产品标签：单方 acetaminophen；"
       "中国「泰诺」说明书为复方（本库 7 个产品/4 个成分，2026-10-26 核对）。",
       status="published", country="US/CN"),
    _w("tainuo-vs-tainuolin", "R4", "high",
       tzh="「泰诺」与「泰诺林」是两种 China 产品",
       ten="泰诺 and 泰诺林 are different products in China",
       bzh="泰诺林是单方对乙酰氨基酚；泰诺是复方感冒药。名字只差一个字，成分不同。",
       ben="泰诺林 is single-ingredient acetaminophen; 泰诺 is a combination cold "
           "medicine. One character apart, different actives.",
       url=NMPA, evidence="国家药监局药品查询：两名为独立批准的产品；本库中文名"
       "「泰诺林」仅对乙酰氨基酚，「泰诺」为 4 成分复方（2026-10-26 库内核对）。",
       country="CN"),
    _w("benadryl-us-vs-uk", "R4", "high",
       tzh="Benadryl 在美国与英国成分不同",
       ten="Benadryl has different actives in the US and UK",
       bzh="美国 Benadryl 以苯海拉明（diphenhydramine）为主；英国 Benadryl Allergy "
           "Relief 是阿伐斯汀（acrivastine）8 mg。跨国买同名药先看成分表。",
       ben="US Benadryl is mainly diphenhydramine; UK Benadryl Allergy Relief is "
           "acrivastine 8 mg. Check the active ingredients across markets.",
       url=EMC + "acrivastine", evidence="UK emc：Benadryl Allergy Relief 8 mg "
       "capsules 含 acrivastine；美国产品为 diphenhydramine（本库已验证）。",
       status="published", country="US/GB"),
    _w("gaviscon-us-vs-uk", "R4", "high",
       tzh="Gaviscon 在美国与英国/西班牙配方不同",
       ten="Gaviscon formulations differ between the US and UK/Spain",
       bzh="美国 Gaviscon 常见为氢氧化铝+碳酸镁；英国/西班牙常见为海藻酸钠+碳酸氢钠"
           "+碳酸钙。同名不同配方，抗反流机制与钠含量都不同。",
       ben="US Gaviscon is typically aluminium hydroxide + magnesium carbonate; "
           "UK/Spain versions use sodium alginate + sodium bicarbonate + calcium "
           "carbonate. Different formulation, different sodium load.",
       url=EMC + "gaviscon", evidence="UK emc 与 AEMPS CIMA 的 Gaviscon 成分表；"
       "美国标签为铝/镁抗酸剂（本库已验证）。",
       status="published", country="US/GB/ES"),
    _w("augmentin-ratio-mismatch", "R3", "high",
       tzh="Augmentin 不同配比的阿莫西林/克拉维酸不可直接替换",
       ten="Augmentin amoxicillin/clavulanate ratios are not interchangeable",
       bzh="同样叫 Augmentin，阿莫西林:克拉维酸常见 2:1、4:1、7:1、14:1 等多种配比；"
           "按片数换用会改变克拉维酸暴露。必须按具体配比与规格核对。",
       ben="Augmentin products come in several amoxicillin:clavulanate ratios "
           "(2:1, 4:1, 7:1, 14:1). Matching tablet counts can change clavulanate "
           "exposure; check the exact ratio and strength.",
       url=DM + "augmentin", evidence="DailyMed/emc 多个 Augmentin 标签的配比不同"
       "（2:1/4:1/7:1/14:1）；本库内同名字段下存在多配比，配比差异项本轮未逐条"
       "核验，标 draft。",
       country="US/GB"),
    _w("sudafed-vs-sudafed-pe", "R4", "high",
       tzh="Sudafed 与 Sudafed PE 的活性成分不同",
       ten="Sudafed and Sudafed PE contain different active ingredients",
       bzh="美国 Sudafed 含伪麻黄碱（pseudoephedrine）；Sudafed PE 含去氧肾上腺素"
           "（phenylephrine）。两者不是同一成分，不能按同名互换。",
       ben="US Sudafed contains pseudoephedrine while Sudafed PE contains "
           "phenylephrine. Different actives despite the shared brand stem.",
       url=DM + "sudafed", evidence="DailyMed 两产品标签成分分别为 pseudoephedrine "
       "与 phenylephrine；同名同品牌前缀。",
       country="US"),

    # ---------- R1/R2 盐型与释放机制：同成分不可互换（区块 B） ----------
    _w("metoprolol-tartrate-vs-succinate", "R2", "high",
       tzh="酒石酸美托洛尔与琥珀酸美托洛尔不可按毫克数互换",
       ten="Metoprolol tartrate and metoprolol succinate are not interchangeable "
           "milligram-for-milligram",
       bzh="两者是不同盐型，且常见剂型释放机制不同（酒石酸盐多为速释，琥珀酸盐多为"
           "缓释）。标示强度所依据的盐/碱基基准也不同，不能把 50 mg 当 50 mg 换用；"
           "换药须由医生评估。",
       ben="Different salt forms, and commonly different release mechanisms "
           "(tartrate immediate-release, succinate extended-release). Label strength "
           "bases differ; do not swap 50 mg for 50 mg. Any switch needs clinical review.",
       url=DM + "metoprolol+tartrate",
       evidence="DailyMed Lopressor（tartrate）与 Toprol-XL（succinate）标签：盐型与"
       "释放机制不同；本库 tartrate 304 个组件、succinate 269 个组件（2026-10）。",
       status="published", sid="metoprolol", rsid="metoprolol"),
    _w("levothyroxine-sodium-vs-base", "R6", "high",
       tzh="左甲状腺素钠与左甲状腺素碱基不是等量关系",
       ten="Levothyroxine sodium is not equivalent to levothyroxine base",
       bzh="左甲状腺素治疗窗窄。标示强度按钠盐计还是按碱基计会影响折算（钠盐约含 "
           "97.25% 碱基），且不同国家/产品基准不一致。任何剂量调整须由医生按 TSH 监测。",
       ben="Narrow therapeutic index. Whether label strength is expressed as the "
           "sodium salt or the base changes the conversion (sodium salt ≈ 97.25% "
           "base), and the basis differs across products. Dose changes need clinical "
           "monitoring, not arithmetic swapping.",
       url=DM + "levothyroxine+sodium",
       evidence="DailyMed Synthroid/Levo-T 标签：强度以 levothyroxine sodium 表示；"
       "PubChem 分子式 C15H10I4NNaO4（798.85）vs 碱基 776.87，f=0.9725。",
       status="published", sid="levothyroxine"),
    _w("aminophylline-vs-theophylline", "R2", "high",
       tzh="氨茶碱与茶碱的标示强度基准不同",
       ten="Aminophylline and theophylline use different strength bases",
       bzh="氨茶碱是茶碱与乙二胺的复盐（约含 80% 茶碱），标签强度可能按氨茶碱或茶碱"
           "计。茶碱治疗窗窄，不能按毫克数直接互换。",
       ben="Aminophylline is a theophylline-ethylenediamine complex (about 80% "
           "theophylline by mass); label strengths may refer to either. Narrow "
           "therapeutic index — no milligram-for-milligram substitution.",
       url=DM + "aminophylline", evidence="DailyMed aminophylline 与 theophylline "
       "标签的强度表述不同；复盐含量约 80%。",
       sid="theophylline"),
    _w("theophylline-ir-vs-er", "R1", "high",
       tzh="茶碱速释与缓释剂型不可互换",
       ten="Immediate- and extended-release theophylline are not interchangeable",
       bzh="茶碱治疗窗窄，缓释剂型的吸收曲线与速释不同；按相同日剂量直接换算可能"
           "导致峰浓度过高或过低。须按具体剂型与监测结果调整。",
       ben="Theophylline has a narrow therapeutic index; extended-release products "
           "have a different absorption profile. Same daily dose does not mean same "
           "serum levels; monitor and use the prescribed formulation.",
       url=DM + "theophylline", evidence="DailyMed 多款 theophylline ER 标签要求"
       "整片吞服并监测血药浓度；IR/ER 生物利用度曲线不同。",
       sid="theophylline"),
    _w("morphine-ir-vs-er", "R1", "high",
       tzh="吗啡速释与缓释剂型不可互换",
       ten="Immediate- and extended-release morphine are not interchangeable",
       bzh="缓释阿片类按 24 小时覆盖设计，速释用于按需镇痛；同 mg 数换用可能导致"
           "过量或镇痛不足。阿片类转换须由有经验的医生按等效镇痛表评估。",
       ben="Extended-release opioids are designed for around-the-clock coverage; "
           "immediate-release is for breakthrough pain. Same milligram counts can "
           "cause overdose or under-treatment; opioid rotation requires clinical "
           "assessment.",
       url=DM + "morphine+sulfate", evidence="DailyMed MS Contin（ER）与硫酸吗啡"
       "速释片标签：给药频率与释放机制不同，ER 须整片吞服。",
       sid="morphine"),
    _w("oxycodone-ir-vs-er", "R1", "high",
       tzh="羟考酮速释与缓释剂型不可互换",
       ten="Immediate- and extended-release oxycodone are not interchangeable",
       bzh="缓释羟考酮不可掰开/碾碎，速释与缓释的峰谷浓度不同；同 mg 数直接换用"
           "有呼吸抑制风险。",
       ben="ER oxycodone must not be crushed or split; IR and ER differ in peak/trough "
           "exposure. Milligram-for-milligram switching risks respiratory depression.",
       url=DM + "oxycodone", evidence="DailyMed OxyContin（ER）标签黑框警告：不可"
       "碾碎/咀嚼；与速释产品释放机制不同。",
       sid="oxycodone"),
    _w("nifedipine-ir-vs-er", "R1", "high",
       tzh="硝苯地平速释与缓释/控释剂型不可互换",
       ten="Immediate- and extended-release nifedipine are not interchangeable",
       bzh="速释硝苯地平（尤其短效胶囊）与缓释/控释片释放曲线差异大，直接按 mg 换用"
           "可能引起血压骤降或反射性心动过速。",
       ben="IR nifedipine (especially short-acting capsules) and ER/controlled-release "
           "tablets have very different release profiles; milligram-for-milligram "
           "switching can cause abrupt hypotension or reflex tachycardia.",
       url=DM + "nifedipine", evidence="DailyMed Procardia（IR）与 Procardia XL"
       "（GITS）标签：释放机制不同，XL 不可掰开。",
       sid="nifedipine"),
    _w("diltiazem-ir-vs-er", "R1", "medium",
       tzh="地尔硫䓬速释与缓释剂型不可互换",
       ten="Immediate- and extended-release diltiazem are not interchangeable",
       bzh="缓释地尔硫䓬的释放曲线与速释不同，同 mg 数换用会改变峰浓度与给药间隔。",
       ben="ER diltiazem has a different release profile; same milligram counts do "
           "not reproduce the same exposure or dosing interval.",
       url=DM + "diltiazem", evidence="DailyMed Cardizem/CD/XR 系列标签：IR 与 ER "
       "给药频次与释放机制不同。",
       sid="diltiazem"),
    _w("verapamil-ir-vs-er", "R1", "medium",
       tzh="维拉帕米速释与缓释剂型不可互换",
       ten="Immediate- and extended-release verapamil are not interchangeable",
       bzh="缓释维拉帕米按 24 小时覆盖设计，速释按每日多次给药；同 mg 数直接换用"
           "会改变血压/心率控制。",
       ben="ER verapamil is designed for 24-hour coverage while IR is dosed multiple "
           "times daily; same milligram counts change blood pressure/heart-rate control.",
       url=DM + "verapamil", evidence="DailyMed Calan（IR）与 Calan SR/Verelan"
       "（ER）标签：给药频次与释放机制不同。",
       sid="verapamil"),
    _w("carbamazepine-ir-vs-er", "R1", "high",
       tzh="卡马西平速释与缓释剂型不可互换",
       ten="Immediate- and extended-release carbamazepine are not interchangeable",
       bzh="卡马西平治疗窗窄且自身诱导代谢，缓释与速释的峰浓度不同；同 mg 数换用"
           "可能诱发不良反应或发作。须监测血药浓度。",
       ben="Carbamazepine has a narrow therapeutic index and autoinduces metabolism; "
           "IR and ER differ in peak concentrations. Same milligram counts may cause "
           "toxicity or loss of seizure control; monitor levels.",
       url=DM + "carbamazepine", evidence="DailyMed Tegretol（IR）与 Tegretol-XR 标签："
       "释放机制不同且需监测血药浓度。",
       sid="carbamazepine"),
    _w("valproate-formulations", "R2", "high",
       tzh="丙戊酸/丙戊酸钠/双丙戊酸钠不是等量关系",
       ten="Valproic acid, sodium valproate and divalproex sodium are not equivalent",
       bzh="不同丙戊酸盐型/复盐的标示强度基准不同（按丙戊酸计还是按盐计），且速释/"
           "缓释曲线不同。治疗窗窄，不可按 mg 数互换。",
       ben="Different valproate forms use different strength bases (valproic acid vs "
           "salt) and IR/ER profiles differ. Narrow therapeutic index — no simple "
           "milligram conversion.",
       url=DM + "divalproex+sodium", evidence="DailyMed Depakote（divalproex）与"
       "Depakene（valproic acid）标签的强度基准不同。",
       sid="valproate"),
    _w("methylphenidate-ir-vs-er", "R1", "medium",
       tzh="哌甲酯速释与缓释/长效剂型不可互换",
       ten="Immediate- and extended-release methylphenidate are not interchangeable",
       bzh="哌甲酯 IR 与 ER/LA 剂型的释放与给药时间表不同，同 mg 数换用会改变全天"
           "暴露与依从性安排。",
       ben="IR and ER/LA methylphenidate differ in release and daily exposure; same "
           "milligram counts do not reproduce the same coverage timeline.",
       url=DM + "methylphenidate", evidence="DailyMed Ritalin（IR）与 Concerta/"
       "Ritalin LA（ER/LA）标签：释放机制与给药频次不同。",
       sid="methylphenidate"),
    _w("venlafaxine-ir-vs-er", "R1", "medium",
       tzh="文拉法辛速释与缓释剂型不可互换",
       ten="Immediate- and extended-release venlafaxine are not interchangeable",
       bzh="文拉法辛缓释（XR）与速释的峰浓度和停药反应不同；同 mg 数换用会改变"
           "暴露曲线。",
       ben="Venlafaxine XR and IR differ in peak exposure and discontinuation "
           "profile; same milligram counts do not give the same curve.",
       url=DM + "venlafaxine", evidence="DailyMed Effexor（IR）与 Effexor XR 标签："
       "释放机制与给药频次不同。",
       sid="venlafaxine"),
    _w("bupropion-ir-sr-xl", "R1", "medium",
       tzh="安非他酮速释/缓释/控释剂型不可互换",
       ten="Bupropion IR, SR and XL are not interchangeable",
       bzh="安非他酮 IR/SR/XL 的释放机制与给药频次不同；同 mg 数换用会改变峰浓度"
           "与癫痫风险相关的暴露。",
       ben="Bupropion IR, SR and XL differ in release profile and dosing frequency; "
           "same milligram counts change peak exposure relevant to seizure risk.",
       url=DM + "bupropion", evidence="DailyMed Wellbutrin（IR/SR/XL）标签：三种剂型"
       "给药频次与释放机制不同。",
       sid="bupropion"),
    _w("metformin-ir-vs-er", "R1", "medium",
       tzh="二甲双胍速释与缓释剂型不可互换",
       ten="Immediate- and extended-release metformin are not interchangeable",
       bzh="缓释二甲双胍的胃肠道耐受性与释放曲线不同；同 mg 数换用可能改变血糖"
           "控制与不良反应。",
       ben="ER metformin has a different release profile and GI tolerability; same "
           "milligram counts may change glycemic control and side effects.",
       url=DM + "metformin", evidence="DailyMed 多款 metformin ER 标签：与 IR 释放"
       "机制不同。",
       sid="metformin"),
    _w("clonidine-ir-vs-er", "R1", "medium",
       tzh="可乐定速释与缓释剂型不可互换",
       ten="Immediate- and extended-release clonidine are not interchangeable",
       bzh="可乐定缓释片按 24 小时覆盖，速释与缓释同 mg 数换用可能导致低血压或"
           "撤药性反跳。",
       ben="ER clonidine provides 24-hour coverage; milligram-for-milligram swaps "
       "between IR and ER can cause hypotension or rebound withdrawal.",
       url=DM + "clonidine", evidence="DailyMed Catapres（IR）与 Kapvay（ER）标签："
       "给药频次与释放机制不同。",
       sid="clonidine"),
    _w("quetiapine-ir-vs-er", "R1", "medium",
       tzh="喹硫平速释与缓释剂型不可互换",
       ten="Immediate- and extended-release quetiapine are not interchangeable",
       bzh="喹硫平缓释（XR）与速释的峰浓度不同，同 mg 数换用会改变镇静与代谢"
           "暴露；且盐型（富马酸盐）的强度基准须按产品说明书。",
       ben="Quetiapine XR and IR differ in peak exposure; same milligram counts change "
           "sedation and metabolic exposure. Check the fumarate salt strength basis "
           "on the label.",
       url=DM + "quetiapine", evidence="DailyMed Seroquel（IR）与 Seroquel XR 标签："
       "释放机制不同；强度以 quetiapine 计（富马酸盐）。",
       sid="quetiapine"),
    _w("levodopa-carbidopa-ir-vs-er", "R1", "medium",
       tzh="左旋多巴/卡比多巴速释与缓释剂型不可互换",
       ten="Immediate- and extended-release levodopa/carbidopa are not interchangeable",
       bzh="缓释剂型的左旋多巴释放曲线不同，同 mg 数换用会改变「开-关」现象与"
           "运动并发症控制。",
       ben="ER levodopa/carbidopa has a different release profile; same milligram "
       "counts change wearing-off and dyskinesia control.",
       url=DM + "levodopa", evidence="DailyMed Sinemet（IR）与 Sinemet CR（ER）标签："
       "释放机制与给药频次不同。",
       sid="levodopa"),

    # ---------- R2 盐型差异（区块 B） ----------
    _w("amlodipine-besylate-vs-base", "R2", "medium",
       tzh="苯磺酸氨氯地平与氨氯地平碱基不是等量",
       ten="Amlodipine besylate is not equivalent to amlodipine base",
       bzh="美国 Norvasc 等产品标示强度按氨氯地平碱基计，而部分市场按苯磺酸盐计。"
           "折算系数约 0.721：100 mg 苯磺酸氨氯地平 ≈ 72.1 mg 氨氯地平碱基（按分子量"
           "折算，不构成用药建议）。",
       ben="Some labels express amlodipine as the base, others as the besylate salt. "
           "Base fraction ≈ 0.721: 100 mg amlodipine besylate ≈ 72.1 mg amlodipine "
           "base (molecular-weight calculation; not a dosing recommendation).",
       url=DM + "amlodipine+besylate", evidence="DailyMed Norvasc 标签：强度以 "
       "amlodipine 计；PubChem 苯磺酸盐 567.10 vs 碱基 408.90，f=0.7210。",
       sid="amlodipine"),
    _w("atorvastatin-calcium-vs-base", "R2", "medium",
       tzh="阿托伐他汀钙与阿托伐他汀碱基不是等量",
       ten="Atorvastatin calcium is not equivalent to atorvastatin base",
       bzh="标示强度按碱基计还是按钙盐计会影响折算；无水钙盐的碱基系数约 0.967，"
           "三水合物更低（约 0.924）。须按具体产品说明书核对基准。",
       ben="Label strength may refer to the base or the calcium salt; anhydrous "
           "calcium salt base fraction ≈ 0.967 and the trihydrate ≈ 0.924. Check the "
           "specific label basis before any calculation.",
       url=DM + "atorvastatin+calcium", evidence="DailyMed Lipitor 标签：强度以 "
       "atorvastatin 计；PubChem 钙盐 1155.30 vs 碱基 558.60，f=0.9671。",
       sid="atorvastatin"),
    _w("omeprazole-magnesium-vs-base", "R2", "medium",
       tzh="奥美拉唑镁与奥美拉唑碱基不是等量",
       ten="Omeprazole magnesium is not equivalent to omeprazole base",
       bzh="奥美拉唑镁（2:1）与奥美拉唑碱基的标示强度基准不同，碱基系数约 0.969；"
           "不同产品的标示基准须按说明书核对。",
       ben="Omeprazole magnesium (2:1) and omeprazole base use different label bases; "
       "base fraction ≈ 0.969. Check each product's label basis.",
       url=DM + "omeprazole+magnesium", evidence="DailyMed 奥美拉唑镁标签：强度以 "
       "omeprazole 计；PubChem 镁盐 713.10 vs 2×碱基 690.8，f=0.9687。",
       sid="omeprazole"),
    _w("diphenhydramine-salts", "R2", "medium",
       tzh="苯海拉明不同盐型的标示强度基准不同",
       ten="Diphenhydramine salts use different strength bases",
       bzh="苯海拉明盐酸盐是常见形式，也有枸橼酸盐等；不同盐型按 mg 数直接换用会"
           "改变碱基暴露。",
       ben="Diphenhydramine hydrochloride is common, but citrate and other salts "
           "exist; milligram-for-milligram swaps change base exposure.",
       url=DM + "diphenhydramine", evidence="DailyMed 苯海拉明产品盐型不同（HCl/ citrate "
       "等）；碱基系数 HCl ≈ 0.8751。",
       sid="diphenhydramine"),
    _w("phenytoin-sodium-vs-base", "R2", "high",
       tzh="苯妥英钠与苯妥英碱基不是等量",
       ten="Phenytoin sodium is not equivalent to phenytoin base",
       bzh="苯妥英钠标示强度按盐计，而苯妥英碱基约占 92%；两者治疗窗窄且非线性"
           "代谢，不可按 mg 数互换，须监测血药浓度。",
       ben="Phenytoin sodium label strength refers to the salt; the base is about 92% "
       "by mass. Narrow therapeutic index and nonlinear kinetics — no milligram "
       "conversion without level monitoring.",
       url=DM + "phenytoin", evidence="DailyMed Dilantin 标签：强度以 phenytoin sodium "
       "表示；游离酸与钠盐需区分。",
       sid="phenytoin"),
    _w("albuterol-sulfate-vs-base", "R2", "medium",
       tzh="硫酸沙丁胺醇与沙丁胺醇碱基不是等量",
       ten="Albuterol sulfate is not equivalent to albuterol base",
       bzh="吸入制剂常按沙丁胺醇碱基标示强度（如 90 mcg/喷），也有按硫酸盐标示的；"
           "跨国产品比对要看基准，同 mcg 数不一定同碱基量。",
       ben="Inhalers often label strength as albuterol base (e.g. 90 mcg/actuation), "
           "while some products use the sulfate salt. Cross-market comparison requires "
           "checking the basis.",
       url=DM + "albuterol+sulfate", evidence="DailyMed Ventolin/ProAir 标签：强度以 "
       "albuterol 计；硫酸盐形式存在。",
       sid="albuterol"),
    _w("clindamycin-hcl-vs-phosphate", "R5", "high",
       tzh="盐酸克林霉素（口服）与克林霉素磷酸酯（注射）不是同一形式",
       ten="Clindamycin hydrochloride (oral) and clindamycin phosphate (IV) are "
           "different forms",
       bzh="口服多为盐酸克林霉素，注射多为克林霉素磷酸酯（前药，体内水解为克林霉素）。"
           "不同盐/酯形式对应不同给药途径，不可直接换用或按 mg 数互换。",
       ben="Oral products are usually clindamycin hydrochloride; IV products are "
       "clindamycin phosphate (a prodrug hydrolysed to clindamycin). Different forms "
       "and routes — not directly interchangeable.",
       url=DM + "clindamycin", evidence="DailyMed Cleocin HCl（口服）与 Cleocin "
       "Phosphate（注射）标签：盐/酯形式不同，给药途径不同。",
       sid="clindamycin"),
    _w("dexamethasone-sodium-phosphate", "R5", "high",
       tzh="地塞米松与地塞米松磷酸钠的途径与形式不同",
       ten="Dexamethasone and dexamethasone sodium phosphate differ in form and route",
       bzh="注射用地塞米松磷酸钠是磷酸酯前药，口服/外用多为地塞米松碱基。不同形式"
           "对应不同途径，标示强度基准也不同，不可按 mg 数互换。",
       ben="Injectable dexamethasone sodium phosphate is a phosphate ester prodrug; "
       "oral/topical products use dexamethasone base. Different forms, routes and "
       "strength bases — no milligram substitution.",
       url=DM + "dexamethasone", evidence="DailyMed 地塞米松磷酸钠注射液与地塞米松"
       "片标签：形式与给药途径不同。",
       sid="dexamethasone"),
    _w("hydrocortisone-sodium-succinate", "R5", "high",
       tzh="氢化可的松与氢化可的松琥珀酸钠的途径不同",
       ten="Hydrocortisone and hydrocortisone sodium succinate differ in route",
       bzh="氢化可的松琥珀酸钠为静脉用酯盐，口服/外用为氢化可的松或其他酯（如醋酸酯）。"
           "不同酯/盐形式的标示强度基准不同，不可按 mg 数互换。",
       ben="Hydrocortisone sodium succinate is an IV ester salt; oral/topical products "
       "use hydrocortisone or another ester (e.g. acetate). Different strength bases — "
       "no milligram substitution.",
       url=DM + "hydrocortisone", evidence="DailyMed Solu-Cortef（琥珀酸钠注射）与"
       "氢化可的松口服/外用标签：酯/盐形式不同。",
       sid="hydrocortisone"),
    _w("erythromycin-esters", "R2", "medium",
       tzh="红霉素不同酯/盐形式的标示强度基准不同",
       ten="Erythromycin esters/salts use different strength bases",
       bzh="红霉素碱、硬脂酸酯、琥珀酸乙酯、依托酸酯（estolate）等形式的标示强度"
           "基准不同，且部分酯有肝毒性差异；不可按 mg 数直接互换。",
       ben="Erythromycin base, stearate, ethylsuccinate and estolate use different "
           "strength bases and have different hepatic profiles; no milligram "
           "substitution.",
       url=DM + "erythromycin", evidence="DailyMed 红霉素碱/硬脂酸酯/琥珀酸乙酯/"
       "estolate 标签的强度基准不同。",
       sid="erythromycin"),

    # ---------- R6 治疗窗窄 / 高警示：不折算（区块 D） ----------
    _w("warfarin-narrow-index", "R6", "high",
       tzh="华法林：治疗窗窄，不做盐基折算或剂量互换",
       ten="Warfarin: narrow therapeutic index — no salt conversion or dose swapping",
       bzh="华法林（钠盐）治疗窗窄，剂量须按 INR 个体化。本站不提供任何折算或互换"
           "结论；不同市场产品的外消旋比例也可能不同。",
       ben="Warfarin (sodium salt) has a narrow therapeutic index and is titrated to "
       "INR. This site gives no conversion or interchange conclusion; racemate "
       "composition can also differ by product.",
       url=DM + "warfarin+sodium", evidence="DailyMed Coumadin 标签：按 INR 个体化"
       "给药；治疗窗窄。",
       sid="warfarin"),
    _w("digoxin-narrow-index", "R6", "high",
       tzh="地高辛：治疗窗窄，不做折算",
       ten="Digoxin: narrow therapeutic index — no conversion",
       bzh="地高辛治疗窗窄，血药浓度受制剂生物利用度影响；不同市场/剂型不可按 mg 数"
           "直接互换，须按浓度监测。",
       ben="Digoxin has a narrow therapeutic index; exposure depends on formulation "
       "bioavailability. Do not swap products by milligram; monitor levels.",
       url=DM + "digoxin", evidence="DailyMed Lanoxin 标签：治疗窗窄，需监测血药浓度。",
       sid="digoxin"),
    _w("lithium-narrow-index", "R6", "high",
       tzh="锂盐：治疗窗窄，不做折算",
       ten="Lithium salts: narrow therapeutic index — no conversion",
       bzh="碳酸锂、枸橼酸锂等不同锂盐的标示强度基准不同，治疗窗窄，须按血锂浓度"
           "个体化调整；不可按 mg 数互换。",
       ben="Lithium carbonate and lithium citrate use different strength bases; narrow "
       "therapeutic index requires serum-level monitoring. No milligram swapping.",
       url=DM + "lithium+carbonate", evidence="DailyMed 碳酸锂/枸橼酸锂标签：需监测"
       "血锂浓度；不同盐强度基准不同。",
       sid="lithium"),
    _w("tacrolimus-ir-vs-er", "R6", "high",
       tzh="他克莫司速释与缓释不可互换",
       ten="Tacrolimus IR and ER formulations are not interchangeable",
       bzh="他克莫司治疗窗窄，速释（每日两次）与缓释（每日一次）不可按 mg 数互换，"
           "转换须在移植团队指导下并监测谷浓度。",
       ben="Tacrolimus has a narrow therapeutic index; IR (twice daily) and ER (once "
       "daily) are not milligram-interchangeable. Conversion requires transplant-team "
       "supervision and trough monitoring.",
       url=DM + "tacrolimus", evidence="DailyMed Prograf（IR）与 Astagraf XL/Envarsus"
       "（ER）标签：不可随意转换，需监测谷浓度。",
       sid="tacrolimus"),
    _w("ciclosporin-ir-vs-er", "R6", "high",
       tzh="环孢素速释与缓释不可互换",
       ten="Ciclosporin IR and ER formulations are not interchangeable",
       bzh="环孢素治疗窗窄，不同制剂/盐型（如微乳、缓释）的生物利用度不同，不可按 "
           "mg 数互换；转换须监测血药浓度。",
       ben="Ciclosporin has a narrow therapeutic index and formulation-dependent "
           "bioavailability; IR and ER are not milligram-interchangeable. Conversion "
           "requires level monitoring.",
       url=DM + "ciclosporin", evidence="DailyMed Neoral（改良型）与 Sandimmune 标签："
       "剂型间不可随意互换，需监测浓度。",
       sid="ciclosporin"),
    _w("insulin-u100-vs-u500", "R6", "high",
       tzh="胰岛素 U-100 与 U-500 浓度不同，不可直接换算",
       ten="Insulin U-100 and U-500 concentrations are not interchangeable",
       bzh="U-500 是 U-100 的 5 倍浓度，误用会导致严重低血糖。本站不做任何胰岛素"
           "剂量折算；请使用处方笔芯/注射器并遵医嘱。",
       ben="U-500 insulin is five times the concentration of U-100; mix-ups cause "
       "severe hypoglycaemia. This site gives no insulin dose conversion.",
       url=DM + "insulin", evidence="DailyMed Humulin R U-500 标签：浓度与 U-100 不同，"
       "需专用注射器。",
       sid="insulin"),
    _w("heparin-unfractionated", "R6", "medium",
       tzh="肝素类：不同来源与低分子量肝素不可互换",
       ten="Heparins: unfractionated and low-molecular-weight heparin are not "
           "interchangeable",
       bzh="普通肝素与低分子量肝素（依诺肝素、达肝素等）的抗 Xa/IIa 活性比例不同，"
           "不可按单位数互换；本站不做折算。",
       ben="Unfractionated heparin and LMWHs differ in anti-Xa/IIa activity ratios; "
       "not interchangeable by unit counts. This site gives no conversion.",
       url=DM + "heparin", evidence="DailyMed 肝素与低分子量肝素标签：抗 Xa/IIa 活性"
       "比例与监测方式不同。",
       sid="heparin"),
]


def validate(rows: list[dict]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    required = ["warning_id", "rule", "severity", "title_zh", "title_en", "body_zh",
                "body_en", "source_url", "evidence", "status", "created_at", "updated_at"]
    for r in rows:
        wid = r.get("warning_id", "?")
        for f in required:
            if not (r.get(f) or "").strip():
                errors.append(f"{wid}: 缺必填字段 {f}")
        if wid in seen:
            errors.append(f"{wid}: warning_id 重复")
        seen.add(wid)
        if not wid.replace("-", "").replace("_", "").isalnum():
            errors.append(f"{wid}: warning_id 需为 ascii slug")
        if r["rule"] not in {"R1", "R2", "R3", "R4", "R5", "R6", "R7"}:
            errors.append(f"{wid}: 非法 rule {r['rule']}")
        if r["severity"] not in {"high", "medium", "info"}:
            errors.append(f"{wid}: 非法 severity {r['severity']}")
        if r["status"] not in {"published", "draft", "retracted"}:
            errors.append(f"{wid}: 非法 status {r['status']}")
        if not r["source_url"].startswith("https://") or not any(
                d in r["source_url"] for d in TRUSTED_DOMAINS):
            errors.append(f"{wid}: source_url 必须是监管来源（{r['source_url']}）")
        if len(r["evidence"]) > 200:
            errors.append(f"{wid}: evidence 超过 200 字（{len(r['evidence'])}）")
        if r["status"] == "published" and ";" not in (r.get("reviewed_by") or ""):
            errors.append(f"{wid}: published 条目需至少两位 reviewed_by")
        if r["rule"] == "R4" and r["substance_id"]:
            errors.append(f"{wid}: R4 同名不同药不应挂单一 substance_id")
    return errors


def _connect(db_path: Path, write: bool) -> sqlite3.Connection:
    if write:
        return sqlite3.connect(db_path, timeout=120)
    return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=120)


def _guard_target(db_path: Path, action: str, confirmed: bool) -> None:
    try:
        is_real = db_path.resolve() == DEFAULT_DB.resolve()
    except OSError:
        is_real = False
    if is_real and action in ("apply", "rollback") and not confirmed:
        raise SystemExit(
            f"拒绝在真实库 {db_path} 上执行 --{action}：种子脚本默认不写库。\n"
            "确认要写时加 --confirm-real-db，并先备份 data/drugs.db。"
        )


def check_substances(db: sqlite3.Connection, rows: list[dict]) -> tuple[list[str], list[str]]:
    """返回 (库里存在的 id, 不存在的 id)，用于发布前核对 seed 挂点。"""
    ids = sorted({r["substance_id"] for r in rows if r.get("substance_id")}
                 | {r["related_substance_id"] for r in rows
                    if r.get("related_substance_id")})
    if not ids:
        return [], []
    have = {x[0] for x in db.execute(
        f"SELECT substance_id FROM substance WHERE substance_id IN "
        f"({','.join('?' * len(ids))})", ids)}
    return sorted(have), sorted(set(ids) - have)


def _write_backup(rows: list[dict], db: sqlite3.Connection, backup_dir: Path) -> Path | None:
    ids = [r["warning_id"] for r in rows]
    old = []
    for wid in ids:
        row = db.execute(
            "SELECT * FROM dose_warning WHERE warning_id=?", (wid,)).fetchone()
        if row:
            old.append(dict(zip([d[0] for d in db.execute(
                "SELECT * FROM dose_warning LIMIT 0").description], row)))
    if not old:
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = backup_dir / f"rollback_seed_warnings_{stamp}.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["warning_id", "row_json"])
        for r in old:
            w.writerow([r["warning_id"], json.dumps(r, ensure_ascii=False)])
    (backup_dir / "rollback_seed_warnings_latest.csv").write_text(
        path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _apply(args: argparse.Namespace, rows: list[dict]) -> int:
    db = _connect(args.db, write=True)
    try:
        has_table = db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='dose_warning'"
        ).fetchone()[0]
        if not has_table:
            print("dose_warning 表不存在：先跑 python db/init_db.py", file=sys.stderr)
            return 1
        have, missing = check_substances(db, rows)
        if missing and not args.allow_unknown_substance:
            print(f"substance 不存在：{missing}（确认无误可加 --allow-unknown-substance，"
                  "该条 substance_id 会被置空）", file=sys.stderr)
            return 1
        for r in rows:
            if r.get("substance_id") in missing:
                r["substance_id"] = None
            if r.get("related_substance_id") in missing:
                r["related_substance_id"] = None
        backup = _write_backup(rows, db, args.backup_dir)
        sql = (f"INSERT OR REPLACE INTO dose_warning ({','.join(FIELDS)}) "
               f"VALUES ({','.join('?' * len(FIELDS))})")
        with db:
            db.executemany(sql, [tuple(r[f] for f in FIELDS) for r in rows])
        print(f"=== seed_warnings --apply ===")
        print(f"写入条目 : {len(rows):,}（published "
              f"{sum(1 for r in rows if r['status'] == 'published')} / draft "
              f"{sum(1 for r in rows if r['status'] == 'draft')}）")
        print(f"substance 检查 : 存在 {len(have)} / 缺失 {len(missing)}")
        print(f"旧行备份 : {backup or '(无覆盖)'}")
        return 0
    finally:
        db.close()


def _rollback(args: argparse.Namespace, rows: list[dict]) -> int:
    path = args.rollback_file
    if path is None:
        latest = args.backup_dir / "rollback_seed_warnings_latest.csv"
        path = latest if latest.exists() else None
    # 首次 apply 时库里没有旧行 → 没有备份是正常情况，直接删种子行即可
    db = _connect(args.db, write=True)
    try:
        seed_ids = [r["warning_id"] for r in rows]
        restored = 0
        with db:
            db.executemany("DELETE FROM dose_warning WHERE warning_id=?",
                           [(wid,) for wid in seed_ids])
            if path is not None:
                with Path(path).open(encoding="utf-8") as fh:
                    for r in csv.DictReader(fh):
                        data = json.loads(r["row_json"])
                        db.execute(
                            f"INSERT OR REPLACE INTO dose_warning ({','.join(FIELDS)}) "
                            f"VALUES ({','.join('?' * len(FIELDS))})",
                            tuple(data.get(f) for f in FIELDS))
                        restored += 1
        print(f"=== seed_warnings --rollback ===\n备份 {path or '(无，首次 apply)'}"
              f"\n删除 {len(seed_ids)} 个种子 id，恢复旧行 {restored}")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="dose_warning 首批人工策展种子")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="校验 + 统计（默认）")
    mode.add_argument("--apply", action="store_true", help="写入 dose_warning")
    mode.add_argument("--rollback", action="store_true", help="用备份还原")
    mode.add_argument("--verify", action="store_true", help="打印库内分布")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="种子审计 CSV")
    ap.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    ap.add_argument("--rollback-file", type=Path, default=None)
    ap.add_argument("--allow-unknown-substance", action="store_true")
    ap.add_argument("--confirm-real-db", action="store_true")
    args = ap.parse_args(argv)

    rows = WARNINGS
    action = "verify" if args.verify else ("rollback" if args.rollback
                                           else ("apply" if args.apply else "dry"))
    errors = validate(rows)
    if errors:
        print("种子校验失败：", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    if action in ("apply", "rollback"):
        _guard_target(args.db, action, args.confirm_real_db)
    if not args.db.exists():
        print(f"数据库不存在：{args.db}", file=sys.stderr)
        return 1

    if action == "rollback":
        return _rollback(args, rows)
    if action == "apply":
        return _apply(args, rows)

    # dry-run / verify：只读库，导审计 CSV，打印可发布性统计
    db = _connect(args.db, write=False)
    try:
        has_table = db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='dose_warning'"
        ).fetchone()[0]
        have, missing = check_substances(db, rows)
        n_existing = 0
        if has_table:
            n_existing = db.execute(
                f"SELECT COUNT(*) FROM dose_warning WHERE warning_id IN "
                f"({','.join('?' * len(rows))})",
                [r["warning_id"] for r in rows]).fetchone()[0]
    finally:
        db.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    print("=== seed_warnings --dry-run ===")
    print(f"种子条数       : {len(rows)}")
    print(f"rule 分布      : {dict(sorted(Counter(r['rule'] for r in rows).items()))}")
    print(f"severity 分布  : {dict(Counter(r['severity'] for r in rows))}")
    print(f"status 分布    : {dict(Counter(r['status'] for r in rows))}")
    print(f"挂 substance   : {len(have)} 个存在 / 缺失 {missing or '无'}")
    print(f"dose_warning 表: {'存在' if has_table else '不存在（先跑 db/init_db.py）'}"
          f"，已存在同 id {n_existing} 条")
    print(f"审计 CSV       : {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
