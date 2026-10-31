# S11c Harness 读取 Office 页、销售/培训材料角色与按品牌候选归属

> 状态：Spec 冻结（2026-10-31，Claude）。实现方 Claude，审核方 Codex。计划见 #446，平台侧采集见 S11b（#469，已合并）。
> 真实调用：实现与验收测试 0；私有端到端验证 ≤ 30 次 DeepSeek（只在本机，样本不进仓库、Issue、PR 或日志）。

## 0. 背景

S11b 让平台对企业 RAW KB 的 `.pptx/.docx/.xlsx` 生成 Office 采集，来源页接口按页返回逐字文本与块（`blocks`），块带 Office locator：PPTX 为 `PPTX_SHAPE{slide}`（无 `shape_id`），DOCX 为 `DOCX_BLOCK{block_index}`，XLSX 为 `XLSX_CELL_RANGE{sheet, "A<r>:XFD<r>"}`；页文本为本页各块文本以 `\n\n` 连接，块的 `start/end` 是该块在页文本中的码点区间。

用户提供的业务材料是销售、培训类 PPT/Word/Excel。它们不是合同，不能支撑条款事实；字段卡里有四个字段明确以这类材料为来源：`sales_pitch_script`（Pitch 话术）、`four_step_sales_script`（四步法讲解话术）、`objection_handling_scripts`（产品异议话术）、`product_faq`（产品 Q&A）。这类材料通常只写品牌简称（如某系列名），不写备案全称，按现有"整题名或条款编号"锚点无法归属，会被隔离。

## 1. 目标

1. Harness 能读取 Office 来源页（含块），按块切分，证据不跨块；为 Office 证据定义 locator 形状。
2. 新增材料角色 `sales_training`（销售/培训材料）：**只能作为上述四个销售类字段的证据**，其余字段一律不可用。
3. 销售/培训材料与无法识别角色的 Office 文件，按产品品牌名（及年份）给出**候选产品**，交人确认；**从不自动归属**；无候选则照旧隔离（S11a 已能在页面处理）。

## 2. 设计

### 2.1 读取 Office 来源页（`evidence/weknora_pages.py`）

- 响应中的页可带 `blocks`（PDF 页没有该键，行为与输出逐字节不变）。块字段：`block_id`、`start`、`end`、`locator{kind, slide?, block_index?, sheet?, cell_range?}`，严格解析（未知字段、重复键、非有限数一律拒绝）。locator 只能带其 kind 的键（PPTX `slide`，DOCX `block_index`，XLSX `sheet`、`cell_range`），任何键为显式 `null` 或属于别的 kind 都在响应边界拒绝，不先规范化再判断；通用 `Locator` 合同的可选字段不变（审核 R2，#479）。
- 一个文档只要有任一页带 `blocks` **键**（含空列表），即为 Office 文档；按键是否存在判断，不按列表是否为空，否则带文字的空块页会被当作 PDF 文本、绕过 §2.3 的闸门（审核 R1，#479）。其各页都返回 `OfficePageText`（`eval/pdf_text.PageText` 的子类，增加 `blocks: tuple[OfficeBlock, ...]`，空页为空元组）。`OfficeBlock` 为 `start`、`end` 与 contracts `Locator`。
- 额外校验（任一不满足 → `PARSE_ARTIFACT_INTEGRITY`，与现有完整性错误同码）：
  - 块按 `start` 升序、互不重叠，`0 ≤ start < end ≤ 页文本码点数`，块文本去空白后非空，同页 `block_id` 唯一；
  - 页文本等于本页各块文本以 `\n\n` 连接（无块的页文本为空串；平台对无块的 Office 页省略 `blocks`，在 Office 文档内空列表与省略同义）；
  - 一个文档内所有块的 `kind` 相同，且为 `PPTX_SHAPE`、`DOCX_BLOCK`、`XLSX_CELL_RANGE` 之一；`PPTX_SHAPE` 只有 `slide` 且等于页码；`DOCX_BLOCK` 只有 `block_index`，文档只有 1 页且 `block_index` 严格递增；`XLSX_CELL_RANGE` 只有 `sheet`、`cell_range`，同页 `sheet` 相同、不同页不同，`cell_range` 为同一行 `A<r>:XFD<r>` 且行号严格递增。
- `contracts` 的 `Locator`：`PPTX_SHAPE` 的必填字段从 `slide, shape_id` 放宽为 `slide`（`shape_id` 仍可填）。JSON Schema 不编码各 kind 的必填字段，`contracts/` 导出不变，以导出命令 `--check` 为准。

### 2.2 切分与证据（`evidence/segments.py`）

- `SegmentedSource` 对 Office 页**按块切分**：每个块单独按现有切分规则切（同一套句末、条号、列表标记与长度规则），偏移换算回页文本；段落编号仍为 `D<n>P<p>S<k>`，k 在本页内连续。段落**从不跨块**。
- `spans()` 合并相邻段落时，Office 页只在同一块内合并；PDF 页规则不变。
- 表头角色的 Office 文档（如被识别为费率表的 `.xlsx`）：表头块与各块取交集后逐块切分，同样不跨块。
- 同一文档不能既有 Office 页又有普通页（`ValueError`，与现有"同名两个指纹"同类）。
- 新方法 `locator(span) -> Locator`：PDF 返回 `PDF_TEXT_SPAN{page, start, end}`（与现在 `claims.py` 构造的对象相同）；Office 返回所在块的 locator 字段，加上 `page`、`start`、`end`（页文本码点，半开）。这就是 Office 证据的 locator 形状，供 S11d 平台回验与引用实现。
- PDF 页的段落、编号、区间与 locator 与现在逐字节一致（回归测试覆盖）。

### 2.3 发布闸门（平台未支持前失败关闭）

平台的发布回验与引用目前只支持 `PDF_TEXT_SPAN`（S11d 才支持 Office）。`compilers/schema_fields/claims.py` 构造证据时，若证据位于 Office 页，抛 `BundleError("EVIDENCE_LOCATOR_UNSUPPORTED", index)`，不提交平台。PDF 证据改由 `source.locator(span)` 构造，输出不变。退出条件：S11d 合并并部署后，移除该闸门，Office 证据按 §2.2 的 locator 提交。

运维约束：S11d 上线前，不在线上企业 RAW KB 确认或补入 Office 材料。

### 2.4 角色与信任策略

- `identity/material_roles.json` 新增角色 `sales_training`：`evidence: false`（不进入普通证据）；名称与开头信号使用通用的销售/培训用语（数据），两个信号都命中且没有其他角色信号时才自动识别，否则为未识别、交人确认（`role_unresolved` 选项中出现该角色）。新增角色不得改变现有任何 PDF 材料的识别结果（以数据集全部材料回归）。
- `catalog/trust_policy.json` 新增 `scoped_rules`：`{"role": "sales_training", "fields": ["sales_pitch_script", "four_step_sales_script", "objection_handling_scripts", "product_faq"]}`。规则：
  - 范围角色必须是非证据角色、唯一，且不与 `header_rules` 的角色重叠；
  - 范围角色的页**完整切分**（不像表头角色那样只取表头块），但只能作为其字段的证据；
  - `TrustPolicy.restricted_fields(role)` 返回该角色可服务的字段（表头规则与范围规则之并）；第一步的禁选（`engine._forbidden`）、发布证据检查（`claims.py`）与段落评分（`segment_score.py`）统一用它。Golden 重映射（`golden_remap.py`）只处理被排除材料的表头，仍用 `header_fields`，不变；
  - `TrustPolicy.restricted_roles()` 按策略顺序列出全部受限角色（表头角色在前）；`trusted_pages` 与按修订排序受限页的 `eval/compile_run.py` 都用它，不再只枚举 `header_rules`（否则受限页映射里出现范围角色时排序会抛错）；
  - `trusted_pages` 把范围角色的页放进受限页映射（与表头角色同一映射，所有读取全部页面的调用方因此自动带上它们）；`SegmentedSource` 对受限文档按信任策略决定：范围角色完整切分，其他受限角色照旧只切表头块（未知角色也照旧裁剪，失败关闭）。`evidence/segments.py` 因此读取 `catalog` 的信任策略（G1 允许）。
- 版本：`material_roles` `2026-10-31.1`，`trust_policy` `2026-10-31.1`。角色本已计入编译身份（S5b-6）；对没有 `sales_training` 材料的产品，编译请求与身份不变。

### 2.5 按品牌候选归属（`identity/attribution.py`，规则为数据）

适用材料：角色为 `sales_training`，或角色未识别且文件扩展名为 `.pptx/.docx/.xlsx`。其他材料（PDF 条款、说明书、费率表、未识别的 PDF）的判定与现在完全相同。

在整题名与条款编号都没有锚定（即现有逻辑将返回 `QUARANTINE no_product_anchor`）时：

1. 每个已登记产品的**品牌核心**：名称 NFKC 折叠、去空白、转小写后，反复去掉开头的 `brand_prefixes`（公司名 `平安` 与附加险标记 `附加`），去掉所有括号限定（如（悦享版）、（A款）、（2026）），再去掉最长匹配的险种后缀（`classifications` 中的后缀）。少于 `brand_min_chars`（3）个字符的核心不参与匹配。产品的全部名称（含别名）都参与。
2. 材料的文件名（去扩展名）或开头窗口（`anchor_chars`）经同样折叠后，包含某核心的前 `brand_min_chars` 个字符（即至少 3 个字符的核心前缀）→ 该产品为候选。用前缀而不是整个核心：核心常带"养老""长期""终身"等险种修饰（如"盛世金越养老""e生保长期"），而业务材料只写品牌（"盛世金越""e生保"）。宁可多给候选：多出的候选只是多一个选项，漏掉则材料被隔离、由人在全部产品中选。
3. 年份：材料文件名或开头窗口中出现的年份（`upload_year_pattern`，四位 `20xx`）；产品名称中的年份按 `product_year_patterns` 读取（四位年份，或"版"后两位数字，如（尊享版26））；两边都只比较末两位。若材料有年份、且候选中有年份相同的产品，则只保留这些；否则保留全部候选。
4. 有候选且不超过 `brand_max_candidates`（20）→ `NEEDS_CONFIRM`，原因 `brand_candidates`，`candidates` 为候选产品号（排序后）。**即使只有一个候选也不自动归属。** 无候选或候选过多 → 照旧 `QUARANTINE no_product_anchor`。

策略文件新增字段：`brand_prefixes`、`brand_min_chars`、`brand_max_candidates`、`brand_roles`、`brand_extensions`、`upload_year_pattern`、`product_year_patterns`（正则各恰有一个两位数字分组）；`version` `2026-10-31.1`，`basis` 记录本条依据。

### 2.6 人工确认（`identity/confirmation.py`、`ingest/confirmation_questions.py`）

- `brand_candidates` 的选项为候选产品（与 `multiple_products` 相同），最后为忽略。选择产品后按既有 `attribute(product=…)` 重新判定：角色未识别则接着问角色（`role_unresolved`，选项含 `sales_training`），角色已知则补入或询问同角色替换。
- 文案：`details` 新增 `brand_candidates` 一条，`roles` 新增 `sales_training` 的名称；**`version` 不变、已有文案逐字不变**（与 S11a 相同做法，已开放的问题不会被关闭重推）。
- 同一产品的第二份销售/培训材料沿用 `same_role_differs`（替换、作为补充材料保留、忽略），不另设规则。

## 3. 兼容性

- PDF 来源页、PDF 段落、证据区间与 locator 逐字节不变；没有 `sales_training` 材料的产品，编译请求、编译身份与输出不变。
- 现有 PDF 材料的角色识别与归属结果不变（数据集全部材料回归 + 现有测试）。
- 线上：新策略对已隔离的 PDF（例如那份放错的说明书）判定不变；已隔离的 Office 材料若匹配品牌核心，会改为品牌候选问题。
- 归属策略升版后，隔离材料（每次运行都重新判定）的判定带新的 `policy_ref`，其确认问题按既有机制换新一版（与以往每次升版相同）；等待人工的 `NEEDS_CONFIRM` 材料不重新判定，问题不变。信任策略的内容进入离线重放上下文（`compile_run` 的 `context.json`），升版后旧运行的原始回答不能再离线重放；编译产物的复用只看材料身份与角色，不受影响。

## 4. 改动范围

| 方 | 路径 |
|---|---|
| Claude（实现） | `harness/src/insurance_harness/evidence/{weknora_pages.py, segments.py}`、新 `evidence/office_pages.py`、`eval/pdf_text.py`（不改，`OfficePageText` 为子类）、`contracts/knowledge.py`（`LOCATOR_FIELDS`）、`catalog/{trust_policy.py, trust_policy.json}`、`identity/{material_roles.json, attribution.py, attribution_policy.json, confirmation.py}`、`ingest/{confirmation_questions.py, confirmation_wording.json}`、`compilers/schema_fields/{engine.py, claims.py}`、`eval/segment_score.py`（改用 `restricted_fields`）、`eval/compile_run.py`（改用 `restricted_roles`） |
| Claude（RED，受保护） | `harness/tests/evidence/test_office_source_pages.py`、`harness/tests/evidence/test_office_segments.py`、`harness/tests/catalog/test_sales_training_trust.py`、`harness/tests/identity/test_brand_candidates.py` |
| 受保护测试的预期调整（独立披露提交） | 只在本 Spec 改变的事实处更新期望：`tests/contracts/test_locator.py`（`PPTX_SHAPE.shape_id` 变为可选）、`tests/identity/test_material_roles.py`（角色目录多一个非证据角色），以及其他断言"角色目录恰为三种"的既有测试 |

手写文件 ≤ 500 行；不改 Go、前端、`contracts/` 生成物（导出 `--check` 通过）。

## 5. 验收

- RED 全部通过；Harness `pytest -m "not integration_postgres"`、ruff、mypy、`tests/architecture`、`git diff --check` 通过；`contracts` 导出 `--check` 通过。
- 回归：数据集全部 PDF 材料的角色识别结果与改动前相同；PDF 段落与 locator 不变。
- 私有端到端（本机，抽象报告）：6 份业务样本（4 PPTX、1 DOCX、1 XLSX）经平台采集或等价离线采集得到 Office 来源页 → 角色与品牌候选判定 → 人工确认（模拟）→ 对一款确认的产品编译四个销售类字段（≤ 30 次 DeepSeek），证据全部落在 `sales_training` 材料的块内，非销售字段不使用这些材料；只报告成功与否、候选数、字段状态与证据数量。

## 6. 不做

平台回验与引用（S11d）；查看器高亮（S11e）；PPTX 形状、单元格级定位；图片文字（S10）；`target_customer_profile`、`marketing_tagline` 是否也接受销售材料（另行裁定）；Office 证据的 carry。
