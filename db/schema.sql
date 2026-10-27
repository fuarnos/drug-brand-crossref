-- 药品商品名跨国定位站 · 数据契约 v0.4
-- 单一真相源：SQLite。站点与检索索引都从这里构建，不反向写入。
-- v0.2 改动：强度下沉到 product_component，支持复方（Augmentin 这类多成分产品）；
--            新增 corroboration（多源佐证）。
-- v0.3 改动：nickname / drug_term / alias_all 视图；collision 口径收敛。
-- v0.4 改动：D2 盐基折算前置字段 variant.salt_code / variant.strength_basis；
--            新增 dose_warning（D3 `/warn` 页人工策展警示）。老库由 db/init_db.py 幂等迁移。
-- 市场：US（openFDA NDC）、GB（dm+d）、CN（医保代码库）、ES（CIMA / AEMPS）、
--       MX（COFEPRIS）、AU（PBS Schedule）、CA（Health Canada DPD）。
--       country 是「上市国家」，不是语言；西语名走 name_variant，不新建表。

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS source (
    source_id     TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    url           TEXT,
    license       TEXT,
    license_url   TEXT,
    retrieved_at  TEXT,
    data_as_of    TEXT,           -- 数据源自己发布/生效/快照的日期（不是我们抓取的日期）
    data_as_of_note TEXT,         -- live（实时目录）/ annual（年度 PDF）/ 其他说明
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS ingest_run (
    run_id        TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL REFERENCES source (source_id),
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    rows_in       INTEGER,
    rows_kept     INTEGER,
    rows_rejected INTEGER,
    status        TEXT NOT NULL DEFAULT 'running'
                  CHECK (status IN ('running', 'ok', 'failed')),
    note          TEXT
);

-- L1 规范活性成分
CREATE TABLE IF NOT EXISTS substance (
    substance_id  TEXT PRIMARY KEY,
    inn_en        TEXT NOT NULL UNIQUE,
    inn_zh        TEXT,
    atc           TEXT,
    atc_name      TEXT,
    drug_class    TEXT,
    ddd_value     REAL,
    ddd_unit      TEXT,
    ddd_route     TEXT
);

-- L1b 盐型 / 水合物 / 酯：可替代性判定的最小单位
-- v0.4 新增（D2 盐基折算）：
--   salt_code      = 盐名规范化后的代码，与 data/salt_base_fraction.csv 的 salt_code 对齐；
--                    salt 保留来源原文，不覆盖。非盐值分流为 'non_salt'，复盐/混合/未收录
--                    盐分流为 'mixed'（都不可自动折算），空字符串 = 来源未给盐。
--   strength_basis = 标签强度的基准。默认 'unknown'：宁可不出折算结论，也不猜。
CREATE TABLE IF NOT EXISTS variant (
    variant_id     TEXT PRIMARY KEY,
    substance_id   TEXT NOT NULL REFERENCES substance (substance_id),
    salt           TEXT NOT NULL DEFAULT '',
    hydrate        TEXT NOT NULL DEFAULT '',
    ester          TEXT NOT NULL DEFAULT '',
    salt_code      TEXT NOT NULL DEFAULT '',
    strength_basis TEXT NOT NULL DEFAULT 'unknown'
                   CHECK (strength_basis IN ('base', 'salt', 'salt_equivalent', 'unknown')),
    base_fraction  REAL NOT NULL DEFAULT 1.0
                   CHECK (base_fraction > 0 AND base_fraction <= 1),
    interchange    TEXT NOT NULL DEFAULT 'unknown'
                   CHECK (interchange IN ('yes', 'no', 'unknown')),
    interchange_note TEXT
);

CREATE INDEX IF NOT EXISTS idx_variant_salt_code ON variant (salt_code);
CREATE INDEX IF NOT EXISTS idx_variant_basis ON variant (strength_basis);

-- L2 某国上市的某个具体产品（一行 = 一个国家的一个包装）
CREATE TABLE IF NOT EXISTS product (
    product_id     TEXT PRIMARY KEY,
    country        TEXT NOT NULL CHECK (country IN ('US', 'GB', 'CN', 'ES', 'MX', 'AU', 'CA')),
    dosage_form    TEXT NOT NULL,
    form_base      TEXT,                      -- 归一化剂型：tablet / capsule / liquid / ...
    route          TEXT,
    release        TEXT NOT NULL DEFAULT 'none'
                   CHECK (release IN ('none', 'IR', 'ER', 'SR', 'DR', 'GITS', 'MR')),
    pack           TEXT,
    mah            TEXT,
    approval_id    TEXT,
    category       TEXT,                      -- NDA / ANDA / BLA / OTC MONOGRAPH ...
    is_branded     INTEGER NOT NULL DEFAULT 1 CHECK (is_branded IN (0, 1)),
    status         TEXT NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active', 'discontinued', 'withdrawn', 'unknown')),
    status_date    TEXT,
    source_id      TEXT NOT NULL REFERENCES source (source_id),
    source_url     TEXT,
    retrieved_at   TEXT NOT NULL,
    note           TEXT
);

CREATE INDEX IF NOT EXISTS idx_product_country ON product (country, status);

-- 成分：复方在这里是多行。强度跟着成分走，因为 Augmentin 500/125 的强度是分别归属的。
CREATE TABLE IF NOT EXISTS product_component (
    product_id        TEXT NOT NULL REFERENCES product (product_id) ON DELETE CASCADE,
    ord               INTEGER NOT NULL DEFAULT 0,   -- 0 = 主成分
    variant_id        TEXT NOT NULL REFERENCES variant (variant_id),
    strength_value    REAL,
    strength_unit     TEXT,
    per_volume_value  REAL,
    per_volume_unit   TEXT,
    PRIMARY KEY (product_id, ord)
);

CREATE INDEX IF NOT EXISTS idx_component_variant ON product_component (variant_id);

-- 佐证源：一条产品记录可以有多个独立来源核对过。
CREATE TABLE IF NOT EXISTS corroboration (
    product_id    TEXT NOT NULL REFERENCES product (product_id) ON DELETE CASCADE,
    source_type   TEXT NOT NULL
                  CHECK (source_type IN ('regulator', 'mah_pdf', 'provincial_list',
                                         'commercial', 'manual')),
    url           TEXT,
    retrieved_at  TEXT NOT NULL,
    verified_by   TEXT,
    note          TEXT,
    PRIMARY KEY (product_id, source_type, url)
);

-- L3 归一化查找键：碰撞检测的挂点
CREATE TABLE IF NOT EXISTS name_key (
    key_id   TEXT PRIMARY KEY,
    norm     TEXT NOT NULL UNIQUE,
    compact  TEXT NOT NULL,
    script   TEXT NOT NULL
             CHECK (script IN ('latin', 'cyrillic', 'han', 'kana', 'hangul')),
    lang     TEXT
);

CREATE INDEX IF NOT EXISTS idx_name_key_compact ON name_key (compact);

CREATE TABLE IF NOT EXISTS name_variant (
    v_id       INTEGER PRIMARY KEY,
    key_id     TEXT NOT NULL REFERENCES name_key (key_id),
    raw        TEXT NOT NULL,
    source_id  TEXT REFERENCES source (source_id),
    UNIQUE (key_id, raw)
);

CREATE TABLE IF NOT EXISTS product_name (
    product_id  TEXT NOT NULL REFERENCES product (product_id) ON DELETE CASCADE,
    key_id      TEXT NOT NULL REFERENCES name_key (key_id),
    name_type   TEXT NOT NULL
                CHECK (name_type IN ('trade', 'inn', 'old', 'colloquial', 'translit')),
    is_primary  INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
    PRIMARY KEY (product_id, key_id, name_type)
);

CREATE INDEX IF NOT EXISTS idx_product_name_key ON product_name (key_id);

-- 俗称 / 网络别名 / 旧名：人嘴里说的名字，不一定是包装上的名字。
-- 它指向**活性成分**，不指向某个产品：同一个昵称在不同国家会落到不同品牌上。
-- 如果写进 product_name，会让 collision 把「两只青蛙」算成一个挂了几万个包装的
-- 商品名，也会生成一张没有意义的同名页——所以单独一张表，只做检索入口。
CREATE TABLE IF NOT EXISTS nickname (
    nickname_id  INTEGER PRIMARY KEY,
    substance_id TEXT NOT NULL REFERENCES substance (substance_id),
    alias        TEXT NOT NULL,
    alias_norm   TEXT NOT NULL,
    label_zh     TEXT,                       -- 目标成分的中文显示名（人工填，仅用于命中提示）
    kind         TEXT NOT NULL DEFAULT 'slang'
                 CHECK (kind IN ('slang', 'legacy', 'translit', 'abbrev', 'misnomer')),
    confidence   TEXT NOT NULL DEFAULT 'community'
                 CHECK (confidence IN ('user', 'community', 'documented')),
    source       TEXT,                       -- 「用户提供」「中文旧版药名」这类出处
    note         TEXT,
    created_at   TEXT NOT NULL,
    UNIQUE (alias_norm, substance_id)
);

CREATE INDEX IF NOT EXISTS idx_nickname_norm ON nickname (alias_norm);

-- 美国街头叫法 / 常见民间叫法 / 类别俗称（v0.3）
-- 与 nickname 分开的原因：这里有些词指向「类别」（downers = 镇静剂）或指向
-- 本库没有上市产品的管制物质（molly = MDMA）。nickname 要求 substance_id 非空，
-- 而这一类叫法恰恰不能硬塞给某一个成分。两者由 alias_all 视图统一给检索层。
CREATE TABLE IF NOT EXISTS drug_term (
    term_id      INTEGER PRIMARY KEY,
    term         TEXT NOT NULL,
    term_norm    TEXT NOT NULL,
    term_type    TEXT NOT NULL DEFAULT 'street'
                 CHECK (term_type IN ('street', 'folk', 'class', 'brand_generic')),
    country      TEXT NOT NULL DEFAULT 'US',
    label_zh     TEXT,                       -- 指向物的中文名（成分/类别/管制物质）
    label_en     TEXT,
    meaning_en   TEXT,                       -- 这个词是什么意思（命中时给人看）
    meaning_zh   TEXT,
    substance_id TEXT REFERENCES substance (substance_id),  -- 可为空：类别词或无上市产品
    examples     TEXT,                       -- JSON 数组：类别词的举例成分 id
    confidence   TEXT NOT NULL DEFAULT 'documented'
                 CHECK (confidence IN ('user', 'community', 'documented')),
    source_id    TEXT REFERENCES source (source_id),
    source_url   TEXT,
    note         TEXT,
    created_at   TEXT NOT NULL,
    UNIQUE (term_norm, term_type, substance_id)
);

CREATE INDEX IF NOT EXISTS idx_drug_term_norm ON drug_term (term_norm);
CREATE INDEX IF NOT EXISTS idx_drug_term_substance ON drug_term (substance_id);

-- 统一别名视图：nickname（人工中文旧名/俗称）+ drug_term（美国街头/民间/类别）。
-- 检索层和建站都只读这个视图，避免两套查询各写一遍、口径漂移。
DROP VIEW IF EXISTS alias_all;
CREATE VIEW alias_all AS
SELECT n.nickname_id       AS alias_id,
       'nickname'          AS origin,
       n.substance_id,
       n.alias,
       n.alias_norm,
       n.label_zh,
       NULL                AS label_en,
       n.kind,
       n.confidence,
       n.source,
       NULL                AS source_url,
       NULL                AS country,
       NULL                AS meaning_en,
       NULL                AS meaning_zh,
       NULL                AS examples,
       n.note,
       n.created_at
FROM nickname n
UNION ALL
SELECT d.term_id,
       'drug_term',
       d.substance_id,
       d.term,
       d.term_norm,
       d.label_zh,
       d.label_en,
       CASE d.term_type WHEN 'street' THEN 'street'
                        WHEN 'folk'   THEN 'folk'
                        WHEN 'class'  THEN 'class'
                        ELSE 'slang' END,
       d.confidence,
       s.name,
       d.source_url,
       d.country,
       d.meaning_en,
       d.meaning_zh,
       d.examples,
       d.note,
       d.created_at
FROM drug_term d
LEFT JOIN source s ON s.source_id = d.source_id;

-- 易混淆药物（LASA / look-alike, sound-alike）
-- 只收「有官方出处」的配对；算法候选不直接入库，先出 CSV 人工复核。
-- a/b 的 substance_id 可为空：官方名单里有些药本库没有产品（如 acetohexamide）。
CREATE TABLE IF NOT EXISTS confusable_pair (
    pair_id       INTEGER PRIMARY KEY,
    name_a        TEXT NOT NULL,
    name_b        TEXT NOT NULL,
    norm_a        TEXT NOT NULL,
    norm_b        TEXT NOT NULL,
    a_substance_id TEXT REFERENCES substance (substance_id),
    b_substance_id TEXT REFERENCES substance (substance_id),
    tml_a         TEXT,                      -- FDA 建议的 tall-man 写法
    tml_b         TEXT,
    reason        TEXT NOT NULL DEFAULT 'both'
                  CHECK (reason IN ('look_alike', 'sound_alike', 'both')),
    severity      TEXT NOT NULL DEFAULT 'high'
                  CHECK (severity IN ('high', 'medium')),
    source_id     TEXT REFERENCES source (source_id),
    source_url    TEXT,
    note          TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE (norm_a, norm_b)
);

CREATE INDEX IF NOT EXISTS idx_confusable_a ON confusable_pair (a_substance_id);
CREATE INDEX IF NOT EXISTS idx_confusable_b ON confusable_pair (b_substance_id);

-- 品牌家族：同一个商标在不同国家/不同文字的写法（Tylenol ↔ 泰诺 ↔ 泰诺林）。
-- 这是唯一一处必须人工维护的映射——因为"它们是同一个品牌"不写在任何数据里。
CREATE TABLE IF NOT EXISTS brand_family (
    family_id  TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    note       TEXT
);

CREATE TABLE IF NOT EXISTS name_family (
    key_id     TEXT NOT NULL REFERENCES name_key (key_id),
    family_id  TEXT NOT NULL REFERENCES brand_family (family_id),
    note       TEXT,
    PRIMARY KEY (key_id, family_id)
);

-- 碰撞视图：由数据自动推导
-- severe  = 同一个名字下出现不同活性成分（泰诺这类）
-- warning = 成分相同但释放机制不同（IR vs ER，真的不能互换）
-- info    = 只是剂型/规格/包装不同（正常情况，卡片上已显示剂型）
--
-- 注意：名字里本身写着配方（"0.9% SODIUM CHLORIDE IRRIGATION"、电解质输液的
-- 百分比配方名）时，成分差异不是「同名不同药」，那是名字就描述了配方——这类
-- 只在同一成分集合下比释放机制，不出 severe。同理，一方是复方（≥3 个成分，如
-- "Pain Relief Patch"、肠外营养液 Olimel）时，它和单方同名不算同名不同药：
-- 撞的是「用了同名」，看组成就知道了；severe 只留给「两边都是单方/简单复方」的情形。
DROP VIEW IF EXISTS collision;
CREATE VIEW IF NOT EXISTS collision AS
SELECT
    pn.key_id,
    COUNT(DISTINCT v.substance_id)  AS n_substances,
    COUNT(DISTINCT p.product_id)    AS n_products,
    CASE
        WHEN COUNT(DISTINCT v.substance_id) > 1
             AND (COUNT(DISTINCT v.substance_id) FILTER (
                      WHERE pn.name_type = 'trade'
                  ) = 0
                  OR MAX(per_product.n_ing) >= 3)
            THEN CASE WHEN COUNT(DISTINCT p.release) > 1 THEN 'warning' ELSE 'info' END
        WHEN COUNT(DISTINCT v.substance_id) > 1 THEN 'severe'
        WHEN COUNT(DISTINCT p.release) > 1 THEN 'warning'
        ELSE 'info'
    END                             AS level
FROM product_name pn
JOIN product p            ON p.product_id = pn.product_id
JOIN product_component pc ON pc.product_id = p.product_id
JOIN variant v            ON v.variant_id = pc.variant_id
JOIN (SELECT product_id, COUNT(*) AS n_ing
      FROM product_component GROUP BY product_id) per_product
     ON per_product.product_id = p.product_id
GROUP BY pn.key_id;

-- 剂量/不可互换警示（D3 `/warn` 页与成分页警示块的数据源，v0.4）。
-- 只收人工策展、且有监管来源的条目；算法候选不直接入库（先出 CSV 人工复核）。
-- 与 confusable_pair 的分工：confusable_pair 是 FDA tall-man 官方 LASA 名单；
-- 这里放「同名不同药 / 同成分不可互换 / 复方配比 / 剂型途径」等剂量相关警示。
-- substance_id / country 可为空：R4 同名不同药的警示挂在商品名上，没有单一成分。
CREATE TABLE IF NOT EXISTS dose_warning (
    warning_id    TEXT PRIMARY KEY,          -- 稳定 slug，如 'metoprolol-tartrate-vs-succinate'
    substance_id  TEXT REFERENCES substance (substance_id),   -- 可空（R4 商品名警示）
    related_substance_id TEXT REFERENCES substance (substance_id),  -- pair 时的另一端，可空
    country       TEXT,                      -- 可空；空 = 跨国通用警示
    rule          TEXT NOT NULL DEFAULT 'R4'
                  CHECK (rule IN ('R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7')),
    severity      TEXT NOT NULL DEFAULT 'medium'
                  CHECK (severity IN ('high', 'medium', 'info')),
    title_zh      TEXT NOT NULL,
    title_en      TEXT NOT NULL,
    title_es      TEXT,
    body_zh       TEXT NOT NULL,
    body_en       TEXT NOT NULL,
    body_es       TEXT,
    source_url    TEXT NOT NULL,             -- 监管原始文件（label/说明书/SmPC/DPD）
    evidence      TEXT NOT NULL,             -- 事实摘录 + 编辑说明（≤200 字，不转载全文）
    status        TEXT NOT NULL DEFAULT 'draft'
                  CHECK (status IN ('published', 'draft', 'retracted')),
    reviewed_by   TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dose_warning_substance
    ON dose_warning (substance_id, status);
CREATE INDEX IF NOT EXISTS idx_dose_warning_country
    ON dose_warning (country, status);

-- ARTG 名称层：eBS 公开目录能翻到的全量「现行药品」条目（商品名 + 申办方 + ARTG ID）。
-- 只有名字，没有成分——用来回答「这个牌子在澳洲注册过吗、ARTG 号多少」，
-- 不参与 product 身份，也不进 collision（同名不同药的判定只认真实产品）。
CREATE TABLE IF NOT EXISTS artg_entry (
    artg_id      TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    name_norm    TEXT NOT NULL,
    sponsor      TEXT,
    retrieved_at TEXT NOT NULL,
    source_id    TEXT REFERENCES source (source_id)
);

CREATE INDEX IF NOT EXISTS idx_artg_norm ON artg_entry (name_norm);

-- 覆盖度：公开站必须如实展示的数字
DROP VIEW IF EXISTS coverage;
CREATE VIEW IF NOT EXISTS coverage AS
SELECT p.country,
       COUNT(DISTINCT p.product_id)                                      AS n_products,
       COUNT(DISTINCT pc.variant_id)                                     AS n_variants,
       COUNT(DISTINCT CASE WHEN p.status = 'active' THEN p.product_id END) AS n_active,
       MAX(p.retrieved_at)                                               AS last_synced
FROM product p
LEFT JOIN product_component pc ON pc.product_id = p.product_id
GROUP BY country;
