# 可直接粘贴：`data/release_notes_i18n.json` 的 v0.11.10 第 5 条译文

> 用途：修复 `release-latest-incomplete`（CHANGELOG v0.11.10 有 5 条、json 只有 4 条）。
> 写入位置：`data/release_notes_i18n.json` → `"v0.11.10"` → 每种语言数组**追加**下面这一项。
> `data/` 不在 site-ui 写权限内，由 Lead 或 phaseb-data 落盘；本文件只是待粘贴文本。

## zh（可直接用 CHANGELOG 原文）

```json
"**结果列表改成「药名主角」**：列序变为 **产品名称 / 成分 / 规格与剂型 / 市场 / 操作**，药名用最大字号最深字重，厂家·来源·日期降为次要文字；按钮改成看得懂的「选择此产品 / 查看登记详情」；选中行用**浅绿底 + 左侧标记 + 「已选择」**，顶部保留紧凑摘要与「重新选择」；正文最小字号由 14px 提到 16px。手机端沿用同一顺序，靠间距与字号分层、不再逐项套边框。"
```

## en

```json
"**Results now put the product name first**: the columns are **product name / ingredient / strength & form / market / actions**; the name uses the largest and darkest type, while manufacturer, source and date drop to secondary text; buttons became readable (“Pick this product” / “Registry details”); the selected row gets **a pale-green background, a left marker and a “Selected” tag**, with a compact summary and “Reselect” kept above; the minimum body text size rose from 14px to 16px. Mobile keeps the same order, separated by spacing and type scale instead of per-item borders."
```

## es

```json
"**La lista de resultados pone el nombre del producto primero**: las columnas son **nombre del producto / principio activo / concentración y forma / mercado / acciones**; el nombre usa el mayor tamaño y el peso más oscuro, mientras fabricante, fuente y fecha pasan a texto secundario; los botones pasan a «Elegir este producto» / «Ficha del registro»; la fila seleccionada lleva **fondo verde claro, marca a la izquierda y la etiqueta «Seleccionado»**, con un resumen compacto y «Elegir otra» arriba; el tamaño mínimo del texto sube de 14px a 16px. En móvil se mantiene el mismo orden, con espacio y jerarquía tipográfica en lugar de bordes por elemento."
```

## zh-Hant

```json
"**結果列表改成「藥名主角」**：欄序變為 **產品名稱 / 成分 / 規格與劑型 / 市場 / 操作**，藥名用最大字號最深字重，廠家·來源·日期降為次要文字；按鈕改成看得懂的「選擇此產品 / 檢視登記詳情」；選中列用**淺綠底 + 左側標記 + 「已選擇」**，頂部保留緊湊摘要與「重新選擇」；正文最小字號由 14px 提到 16px。手機端沿用同一順序，靠間距與字號分層、不再逐項套邊框。"
```

## fr

```json
"**La liste de résultats met le nom du produit en premier** : les colonnes sont **nom du produit / principe actif / dosage et forme / marché / actions** ; le nom prend la taille la plus grande et la graisse la plus forte, tandis que fabricant, source et date passent en texte secondaire ; les boutons deviennent lisibles (« Choisir ce produit » / « Fiche d'enregistrement ») ; la ligne sélectionnée reçoit **un fond vert clair, un repère à gauche et l'étiquette « Sélectionné »**, avec un résumé compact et « Choisir une autre » au-dessus ; la taille minimale du texte passe de 14 px à 16 px. Le mobile conserve le même ordre, séparé par l'espacement et la hiérarchie typographique plutôt que par des bordures."
```

## 改完自检

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py deploy/i18n_check.py          # 期望 FAIL 0 / WARN 2 / INFO 24
& $py -c "import json,io; d=json.load(io.open('data/release_notes_i18n.json',encoding='utf-8'))['v0.11.10']; print({k:len(v) for k,v in d.items()})"
# 期望 {'en': 5, 'es': 5, 'zh': 5, 'zh-Hant': 5, 'fr': 5}
```
