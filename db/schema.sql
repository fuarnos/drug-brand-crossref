-- 药品商品名跨国定位站 · 数据契约 v0.2
-- 单一真相源：SQLite。站点与检索索引都从这里构建，不反向写入。
-- v0.2 改动：强度下沉到 product_component，支持复方（Augmentin 这类多成分产品）；
--            新增 corroboration（多源佐证）。
-- 市场：US（openFDA NDC）、GB（dm+d）、CN（医保代码库）、ES（CIMA / AEMPS）、
--       MX（COFEPRIS）、AU（PBS Schedule）。
--       country 是「上市国家」，不是语言；西语名走 name_variant，不新建表。

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS source (
    source_id     TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    url           TEXT,
    license       TEXT,
    license_url   TEXT,
    retrieved_at  TEXT,
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
CREATE TABLE IF NOT EXISTS variant (
    variant_id     TEXT PRIMARY KEY,
    substance_id   TEXT NOT NULL REFERENCES substance (substance_id),
    salt           TEXT NOT NULL DEFAULT '',
    hydrate        TEXT NOT NULL DEFAULT '',
    ester          TEXT NOT NULL DEFAULT '',
    base_fraction  REAL NOT NULL DEFAULT 1.0
                   CHECK (base_fraction > 0 AND base_fraction <= 1),
    interchange    TEXT NOT NULL DEFAULT 'unknown'
                   CHECK (interchange IN ('yes', 'no', 'unknown')),
    interchange_note TEXT
);

-- L2 某国上市的某个具体产品（一行 = 一个国家的一个包装）
CREATE TABLE IF NOT EXISTS product (
    product_id     TEXT PRIMARY KEY,
    country        TEXT NOT NULL CHECK (country IN ('US', 'GB', 'CN', 'ES', 'MX', 'AU')),
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
DROP VIEW IF EXISTS collision;
CREATE VIEW IF NOT EXISTS collision AS
SELECT
    pn.key_id,
    COUNT(DISTINCT v.substance_id)  AS n_substances,
    COUNT(DISTINCT p.product_id)    AS n_products,
    CASE
        WHEN COUNT(DISTINCT v.substance_id) > 1 THEN 'severe'
        WHEN COUNT(DISTINCT p.release) > 1 THEN 'warning'
        ELSE 'info'
    END                             AS level
FROM product_name pn
JOIN product p            ON p.product_id = pn.product_id
JOIN product_component pc ON pc.product_id = p.product_id
JOIN variant v            ON v.variant_id = pc.variant_id
GROUP BY pn.key_id;

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
