# v0.11.6 · `data/release_notes_i18n.json` 补丁（可直接粘贴，解除构建中止）

> 工位：**site-ui** ｜ 时间：2026-11-14 ｜ 目的：解除**构建期硬中止**，不是我擅自改公开口径。
> 现象：`CHANGELOG.md` 已有 `## v0.11.6 — 2026-11-14`，但 `data/release_notes_i18n.json` 没有 `v0.11.6` 块 →
> `& $py site/build.py` 在 `_assert_i18n_rules()` 直接 `SystemExit`：`release-latest-missing: 最新版 v0.11.6…没有译文`；
> `deploy/ci_checks.py --fast` 同一项 FAIL。**任何人的发布构建都会被这一条拦住**，与 `site/build.py` 的实现无关。
> 边界：`data/` **不在 site-ui 写权限**（task-1 写作用域 = `site/build.py` + `reports/`），本文件只提供**可直接落的 JSON**，
> 由有 `data/` 权限的工位或 Lead 粘贴；zh 原文即 `CHANGELOG.md` 第一节 5 条，en/es/fr 为机器翻译、zh-Hant 按项目台湾用语。

## 落的方式

把下面这个块插入 `data/release_notes_i18n.json` 的 `"_meta"` 之后（**必须在最前**，因为发布门槛只看最新版）：

```json
  "v0.11.6": {
    "date": "2026-11-14",
    "zh": [
      "**规格和剂型不再混着算**：搜索结果与品牌页改成「剂型 + 规格」成对列出（如「片剂 500 mg · 液体 960 mg/30 mL」）。一瓶 30 mL 的液体不再被一个「片剂」标签代表，浓度也不会从「960 mg/30 mL」缩成「960 mg」；同一名字下只有一种剂型时照旧只显示一种，多种时写「多剂型」并列出前几种。",
      "**成分页分开单方与复方**：同一成分的页面拆成「仅含此成分」与「含此成分的复方」两段；复方行列出全部活性成分**与各自含量**（如「羟考酮 5 mg + 对乙酰氨基酚 325 mg」），不再把复方混进单方的剂量组里。「同类 ≠ 可互换」的提示保留。",
      "**换算误差的规格不再刺眼**：TGA 数据里 `499.9996 mg` 这类换算残渣显示成 `500 mg`，同时保留可追溯的「原记录 499.9996 mg」小字；**数据库与数据包里的原始值一个都不改**（只影响显示，判定规则窄口写死：仅接近整数且偏差极小的值）。",
      "**品牌页改成说配方差异，不再像「翻译表」**：标题从「同一品牌在其他市场的写法」改成「**相关品牌名称与配方差异**」，用表格列出市场 / 注册名 / 完整活性成分 / 关系说明；成分旁显示**成分自己的中文名**（如 Acetaminophen → 对乙酰氨基酚），「无中文名」角标只贴在没有中文名的**名称**上；去掉「严重碰撞」这类内部术语，泰诺 / 泰诺林不再各出现两次。",
      "**浓度型规格不再被折叠吃掉**：成分页原来按「每剂型前 10 个规格」折叠，导致 `960 mg/30 mL` 这类浓度规格整页一次都不出现；现在每个剂型至少保留一个带浓度基数的规格可见。"
    ],
    "en": [
      "**Dosage form and strength are no longer mixed together**: search results and brand pages now list form-and-strength as pairs (e.g. \"tablet 500 mg · liquid 960 mg/30 mL\"). A 30 mL bottle is no longer represented by a single \"tablet\" label, and a concentration no longer collapses from \"960 mg/30 mL\" to \"960 mg\"; when a name has only one dosage form it is still shown once, and when it has several the page says \"multiple dosage forms\" and lists the first few.",
      "**Ingredient pages separate single-ingredient products from combinations**: each ingredient page is split into \"only this ingredient\" and \"combination products containing this ingredient\"; combination rows list every active ingredient **with its own amount** (e.g. \"oxycodone 5 mg + acetaminophen 325 mg\") instead of mixing combinations into single-ingredient strength groups. The \"same class ≠ interchangeable\" note stays.",
      "**Conversion artefacts no longer glare at you**: values such as `499.9996 mg` from TGA data now display as `500 mg`, with a traceable \"recorded as 499.9996 mg\" note; **no raw value in the database or the data package is changed** (display only, with a deliberately narrow rule: only values very close to an integer with a tiny deviation).",
      "**The brand page now describes formula differences instead of looking like a translation table**: the heading changed from \"the same brand in other markets\" to \"**related brand names and formula differences**\", with a table listing market / registered name / all active ingredients / relation; ingredients now show **their own Chinese name** (e.g. Acetaminophen → 对乙酰氨基酚), and the \"no Chinese name\" badge is only attached to **names** that really have none; internal jargon such as \"severe collision\" is gone, and 泰诺 / 泰诺林 no longer each appear twice.",
      "**Concentration strengths are no longer lost to folding**: the ingredient page used to fold to \"first 10 strengths per dosage form\", so concentration strengths like `960 mg/30 mL` never appeared anywhere on the page; every dosage form now keeps at least one strength with its per-volume basis visible."
    ],
    "es": [
      "**La forma farmacéutica y la concentración ya no se mezclan**: los resultados de búsqueda y las páginas de marca muestran ahora forma y concentración emparejadas (p. ej. «comprimido 500 mg · líquido 960 mg/30 mL»). Un envase de 30 mL ya no queda representado por una sola etiqueta «comprimido», y una concentración ya no se reduce de «960 mg/30 mL» a «960 mg»; si un nombre tiene una sola forma farmacéutica se sigue mostrando una vez, y si tiene varias la página indica «varias formas farmacéuticas» y enumera las primeras.",
      "**Las páginas de principio activo separan monofármacos y asociaciones**: cada página se divide en «solo este principio activo» y «asociaciones que contienen este principio activo»; las filas de asociación enumeran todos los principios activos **con su propia cantidad** (p. ej. «oxicodona 5 mg + paracetamol 325 mg») en lugar de mezclar asociaciones con los grupos de concentración de monofármacos. Se mantiene el aviso «misma clase ≠ intercambiables».",
      "**Los artefactos de conversión ya no llaman la atención**: valores como `499.9996 mg` de los datos de TGA ahora se muestran como `500 mg`, con la nota trazable «registrado como 499.9996 mg»; **no se modifica ningún valor bruto de la base de datos ni del paquete de datos** (solo afecta a la visualización, con una regla deliberadamente estrecha: solo valores muy próximos a un entero con una desviación mínima).",
      "**La página de marca describe diferencias de fórmula en lugar de parecer una tabla de traducción**: el título pasa de «la misma marca en otros mercados» a «**nombres de marca relacionados y diferencias de fórmula**», con una tabla mercado / nombre registrado / principios activos completos / relación; los principios activos muestran **su propio nombre chino** (p. ej. Acetaminophen → 对乙酰氨基酚), y la etiqueta «sin nombre chino» solo se aplica a los **nombres** que realmente no lo tienen; desaparece la jerga interna como «colisión grave», y 泰诺 / 泰诺林 ya no aparecen dos veces cada uno.",
      "**Las concentraciones ya no se pierden al plegar**: la página de principio activo se plegaba a «las 10 primeras concentraciones por forma farmacéutica», de modo que una concentración como `960 mg/30 mL` no aparecía en toda la página; ahora cada forma farmacéutica conserva al menos una concentración con su base por volumen visible."
    ],
    "fr": [
      "**Forme galénique et dosage ne sont plus mélangés** : les résultats de recherche et les pages de marque présentent désormais forme et dosage par paires (par ex. « comprimé 500 mg · liquide 960 mg/30 mL »). Un flacon de 30 mL n'est plus représenté par une seule étiquette « comprimé », et une concentration ne se réduit plus de « 960 mg/30 mL » à « 960 mg » ; lorsqu'un nom n'a qu'une seule forme galénique, elle reste affichée une fois, et lorsqu'il en a plusieurs la page indique « formes multiples » et liste les premières.",
      "**Les pages d'ingrédient séparent les produits à principe unique des associations** : chaque page est scindée en « uniquement ce principe actif » et « associations contenant ce principe actif » ; les lignes d'association listent tous les principes actifs **avec leur propre quantité** (par ex. « oxycodone 5 mg + paracétamol 325 mg ») au lieu de mélanger les associations aux groupes de dosage à principe unique. La mention « même classe ≠ interchangeables » est conservée.",
      "**Les artefacts de conversion ne sautent plus aux yeux** : des valeurs comme `499.9996 mg` issues des données TGA s'affichent désormais `500 mg`, avec la mention traçable « enregistré 499.9996 mg » ; **aucune valeur brute de la base ni du paquet de données n'est modifiée** (affichage uniquement, règle volontairement étroite : seules les valeurs très proches d'un entier avec un écart minime).",
      "**La page de marque décrit désormais les différences de formule au lieu de ressembler à un tableau de traduction** : le titre passe de « la même marque sur d'autres marchés » à « **noms de marque liés et différences de formule** », avec un tableau marché / nom enregistré / principes actifs complets / relation ; les principes actifs affichent **leur propre nom chinois** (par ex. Acetaminophen → 对乙酰氨基酚), et le badge « pas de nom chinois » ne s'applique qu'aux **noms** qui n'en ont vraiment pas ; le jargon interne comme « collision sévère » disparaît, et 泰诺 / 泰诺林 n'apparaissent plus deux fois chacun.",
      "**Les dosages de concentration ne sont plus perdus par le repli** : la page d'ingrédient se repliait sur « les 10 premiers dosages par forme galénique », si bien qu'un dosage de concentration comme `960 mg/30 mL` n'apparaissait nulle part ; chaque forme galénique conserve désormais au moins un dosage avec sa base volumique visible."
    ],
    "machine_translated": true,
    "zh-Hant": [
      "**規格和劑型不再混著算**：搜尋結果與品牌頁改成「劑型 + 規格」成對列出（如「錠劑 500 mg · 液體 960 mg/30 mL」）。一瓶 30 mL 的液體不再被一個「錠劑」標籤代表，濃度也不會從「960 mg/30 mL」縮成「960 mg」；同一名稱下只有一種劑型時照舊只顯示一種，多種時寫「多劑型」並列出前幾種。",
      "**成分頁分開單方與複方**：同一成分的頁面拆成「僅含此成分」與「含此成分的複方」兩段；複方列列出全部活性成分**與各自含量**（如「羥考酮 5 mg + 對乙醯胺基酚 325 mg」），不再把複方混進單方的劑量組裡。「同類 ≠ 可互換」的提示保留。",
      "**換算誤差的規格不再刺眼**：TGA 資料裡 `499.9996 mg` 這類換算殘渣顯示成 `500 mg`，同時保留可追溯的「原紀錄 499.9996 mg」小字；**資料庫與資料包裡的原始值一個都不改**（只影響顯示，判定規則窄口寫死：僅接近整數且偏差極小的值）。",
      "**品牌頁改成說配方差異，不再像「翻譯表」**：標題從「同一品牌在其他市場的寫法」改成「**相關品牌名稱與配方差異**」，用表格列出市場 / 註冊名 / 完整活性成分 / 關係說明；成分旁顯示**成分自己的中文名**（如 Acetaminophen → 對乙醯胺基酚），「無中文名」角標只貼在沒有中文名的**名稱**上；去掉「嚴重碰撞」這類內部術語，泰諾 / 泰諾林不再各出現兩次。",
      "**濃度型規格不再被摺疊吃掉**：成分頁原本按「每劑型前 10 個規格」摺疊，導致 `960 mg/30 mL` 這類濃度規格整頁一次都不出現；現在每個劑型至少保留一個帶濃度基數的規格可見。"
    ]
  },
```

## 落完后的自检（两条都过才算解除）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'
& $py deploy/i18n_check.py | Select-Object -Last 6      # 期望 release notes: 最新 v0.11.6 译文齐；FAIL 0
& $py site/build.py                                     # 不再 SystemExit；跑到 == done ==
```

> 顺手项：`_meta.versions` / `_meta.items` 是生成期统计（58 版 / 247 条），若生成器会重算就不用手改；本块只保证「最新版五语条数 = CHANGELOG 第一节 5 条」。
