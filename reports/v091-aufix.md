# v0.9.1 P0 回归修复：AU 名字页误杀

> 2026-10-30 ｜ `site/build.py` ｜ 正式 `site/dist` 已重建（v0.9.1）｜ **未 publish、未改 CHANGELOG**。

## 0. 结论

- 错误：`worth_page` 使用 `"AU" not in a["c"]`，把**任何含 AU 产品的 name_key** 全部排除，导致 AU+其他国家的多国名字页缺失（如 `/name/lipitor.html`、`/name/abilify.html`）。
- 修复：改为 `set(a["c"]) != {"AU"}`，**只排除 AU-only**；AU+其他国家保留。
- 重建后：`name` 页 **74,436 → 77,058（+2,622）**；sitemap **60,737 → 63,359（+2,622）**；`lipitor.html`、`abilify.html` 存在；索引 name/combo 链接 0 缺失。
- 体积 **893.6 MiB / 936,965,162 B**，仍 ≤900 MiB 且十进制 <1e9；0 空文件；页脚 v0.9.1。
- `core.json` 41.4 MB raw 属预期：索引条目内容没变，AU 过滤只影响 `u`/页面生成，不影响 core 字段。

## 1. 错误与影响

```python
# 错误
worth_page = ... and "AU" not in a["c"]
# 修复
worth_page = ... and set(a["c"]) != {"AU"}
```

- 含 AU 的 name_key：33,764；其中 AU+其他国家 **3,345**。
- 实际恢复 name 页 **2,622**（其余 723 个因 pure INN / 无 trade / 单包装体积守卫等原本无页）。
- 损失页面示例：`/name/lipitor.html`、`/name/abilify.html` 等旧 URL 404；修复后均存在。
- 不是数据丢失：DB / 索引 / 搜索结果一直在；只是展示页被误排除。

## 2. before / after

| 项 | 错误版本 | 修复后 | delta |
|---|---:|---:|---:|
| 文件数 | 110,200 | **112,822** | +2,622 |
| name 页 | 74,436 | **77,058** | +2,622 |
| sitemap | 60,737 | **63,359** | +2,622 |
| 字节 | 925,496,800 | **936,965,162** | +11.47 MB |
| MiB | 882.6 | **893.6** | +11.0 |
| 0 空文件 | 0 | 0 | 0 |
| drug / combo / maker | 12,442 / 6,736 / 15,213 | 同左 | 0 |
| core.json raw | 41.3 MB | 41.4 MB | 预期内 |

## 3. 验证

```text
== done ==  (3.29 min)
name pages : 77058
sitemap    : 63359
files=112822 bytes=936965162 MiB=893.6 zero=0
footer: v0.9.1 · 2026-10-30
lipitor.html=True  abilify.html=True  lipitor sitemap=1
index links missing 0
html ../name|combo|drug/ missing sample 0
```

- 未 publish；未改 CHANGELOG；未写 DB。
- 体积仍达标；Lighthouse 首页/成分页不受影响（上次正式 dist：首页 90/100/100/100、orlistat 93/100/100/100）。
- 已知：AU-only 名字页仍按体积策略不建；AU 多国名字页恢复。若要求 AU-only 也可点，需另评估体积（约 +30MB）。
