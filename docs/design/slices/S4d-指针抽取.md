# S4d · 指针抽取：模型选段，代码取原文

> 状态：用户已批准方向（2026-10-14"从第一性原理重做"；2026-10-15 批准 Golden v2、预算追加到 100 次、字段口径两条裁定） ｜ 作者：Claude Code
> 依据：蓝图 §5.1、§7.1、§7.7；Issue #157 中 A2–A7 实验、Golden v2 与 1818 实测记录
> 分支：`slice/s4d` ｜ 工作目录：`.worktrees/s4d` ｜ 实现方：Claude ｜ 审核方：Codex（编译器、证据与评分口径属复杂改动）

本片取代 2026-10-14 版 S4d（"跨文件引文重定位 + 写全提示词"，已由 `26c2b4fe3` 整体回退）：那一版在"模型照抄引文"
的前提下修补，实验表明问题出在这个前提本身。

## 1. 根因与最小机制

S4b（`deepseek-flash`）召回只有 6%–36%，两类问题反复出现：

1. **照抄引文天然脆弱**：模型必须逐字复制 quote，一条对不上（版面交错、标错文件、跳字拼接）整字段就被丢弃（S4b 丢 30 个）；
   照抄也让模型倾向少引。
2. **字段边界不清**：234 个评分结果里 38 个卡在"这段算不算本字段"；Golden v1 本身偏窄（相对 Golden v2 召回 0.52）。

最小必要机制：**模型只指出原文在哪里（段落编号），原文由代码按编号取出；value 只看选中的段落写；字段边界写成数据（字段卡）。**
证据按构造即可回验，不再需要 quote 校验、重定位与纠错。

## 2. 实验证据（Issue #157；一次只变一项）

| 实验 | 变化 | 选段召回 | 选段精确率 | 召回≥0.8 |
|---|---|---|---|---|
| A2 | 指针（pdfplumber 段落） | 0.72 | 0.59 | 25/53 |
| A5 | A2 + 字段卡（有卡字段 0.73→0.89；无卡对照不变） | 0.75 | 0.62 | 29 |
| A3 | 指针（pdfium 段落） | 0.71 | 0.58 | 23 |
| A6 | A3 + 同一次调用写 value | 0.59 | 0.60 | 17 |

（对照 Golden v2：两个独立 GPT-6 Astra xhigh 会话按字段卡在 pdfium 段落上标注。）

- **A7 两步法写 value**（对照 Golden v1 值，L2 语义评分，与 S4b 同口径）：1816 正确 2→14、精确率 0.79→0.97、召回 0.06→0.41；1814 召回持平；
  整字段丢失 27→0。不完整的 40 个字段中 35 个源于第一步漏选段落，5 个源于第二步写漏。
- **留出产品 1818**（两全，全部 82 张字段卡）：56 个字段状态全部正确；34 个字段完全正确，22 个被独立复核纠正（漏选 18、概括不全 5、多选 3、
  显示 3、写错 2）。
- 多选片段盲判：真正噪声约占选中段落 5%；指针输出的无效编号 A2 为 6 个、其后为 0；模型会自发用 `A-B` 区间引用长清单。
- 页文本来源对指针抽取无差别（A3≈A2），按架构选 pdfium（与 WeKnora 原生解析同一引擎；蓝图 §7.1 不迁 pdfplumber）。

## 3. 设计

### 3.1 页文本与分段（`eval/pdf_text.py`；新增 `evidence/segments.py`）

- `read_pdf` 改用 pypdfium2（已在锁文件中，改为直接依赖）：每页 `get_text_range()`，`\r\n`、`\r` 统一为 `\n`。pdfplumber 直接依赖保留：
  S7 前的旧模块（`compiler/`、`goldenset/`、`knowledge_compiler/` 等）仍在使用，随 S7 一并删除。
- `SegmentedSource(pages)` 是本模块唯一入口：
  - 构造时校验页身份唯一（`document`+`page`），按页切段：文件编号按 `pages` 中首次出现的顺序 `D1`、`D2`……；段落编号
    `D<文件>P<页>S<序号>`，序号每页从 1 起；
  - 切段规则：按行累积；行尾是句末标点（`。；;！!？?`）时结束一段；行首是条款编号（`第X条/章/节`、`1.2`、`1、`、`（一）`）时先结束上一段；
    累计达 300 字时结束；每段 `text == page.text[start:end]`（去首尾空白后的原文切片）；同一输入永远得到同样的编号；
  - `listing()`：每行"编号 原文"；`resolve(refs) -> (ids, dropped)`：编号或"起-止"区间（按阅读顺序含两端），不存在的编号与倒序区间进入 dropped；
  - `evidence(ids) -> list[VerifiedQuote]`：按阅读顺序，同一页上相邻的段落合并为一条，`quote = page.text[首段.start:末段.end]`，`match = EXACT`。
- 页文本由 WeKnora ParseArtifact 提供后（S4c）只换 `pages` 来源，本模块不变。

### 3.2 第一步：选段

- 请求：本批字段定义（含 `extraction_profiles.json` 指令与字段卡）+ `listing()`。批大小沿用 `batch_size`（默认 25）。
- 回答每行恰为 `ordinal`、`field_key`、`state`、`segments`。信封与行的校验沿用 S4a 的失败关闭规则（缺行、多行、重复、序号错、形状错整批拒绝）；
  `unknown` 必须 `segments` 为空，其余必须非空。
- 解析后：`present` 的有效段落为 0 时该字段丢弃并计入 `dropped_fields`；无效引用计入 `dropped_refs`；`absent_explicitly` 证据同样由代码生成。

### 3.3 第二步：写 value

- 对第一步 `present` 的字段，请求只含字段定义与它选中段落的"编号 原文"；按段落总字数分批（`value_batch_chars`，默认 60000，单字段超限时独占一批）。
- 回答每行恰为 `ordinal`、`field_key`、`value`（非空字符串）；未知、重复的字段或形状错误整批拒绝；某字段缺行只丢该字段（计入 `dropped_fields`），
  因为各字段的 value 相互独立。
- 规则：只用给定段落中的事实；列全数值、选项、条件、例外与适用对象；不概括、不用"等"省略；多项在同一字符串内编号；有行列关系的保留对应关系。

### 3.4 字段卡是数据（新增 `compilers/schema_fields/field_cards.json`）

- 结构：`{version, state_rules, cards: {field_key: {title, sources, source_scope, definition, includes, excludes[[内容, 归入]], absent_rule, unknown_rule, bad, examples[]}}}`；
  `examples` 每条为 `{insurance_type, product, state, value, reason}`，只取自不参与评测的产品，由独立评委复核；请求中只附与当前 pack 险种相同的示例。
- 覆盖 1814/1816/1824/1826 四个 pack 的全部 82 个字段，守卫测试列出缺卡字段。修改卡片只改数据与 `version`。
- 状态口径（用户 2026-10-15 裁定）：材料含完整保险责任条款时，其中未列的责任判 `absent_explicitly` 并引用该列举条款；条款写明产品类型（如"本合同为分红保险合同"，或普通型产品的完整条款未创设账户、红利）时，只属于其他产品类型的字段
  （万能账户、分红、投资账户等规则）判 `absent_explicitly` 并引用写明类型的条款（用户 2026-10-15 单独确认）；`sources` 含条款、说明书
  以外文件（投保/核保/保全规则、销售与培训材料等）的字段，本批材料未提及一律 `unknown`；疾病清单只列名称、分组、适用责任与限制，医学定义
  统一存于 `disease_definitions_and_criteria`。
- 字段的险种差异由 pack 的 FieldDefinition（与《11类保险产品知识Schema》v5 逐字一致）承载，卡片不复述。

### 3.5 评测（`eval/`）

- Golden v2 进入 `dataset/golden/v2/<产品>.json`：每字段 `state`、`value`、`reason` 与证据（`document`、`document_sha256`、`page`、`quote`=段落原文、`segment_id`），
  由独立 GPT-6 Astra xhigh 会话按字段卡标注、Claude 审计；评分时把 quote 映射到当前段落，分段规则变化也能复用。
- 新增段落评分（`eval/segment_score.py`）：每字段召回 = |选中 ∩ Golden| / |Golden|，精确率 = |选中 ∩ Golden| / |选中|；报告均值、召回≥0.8 字段数、
  状态一致数；value 仍走 S2c 语义评分。
- `compile_run`：两步的每次调用都记账并保存原始回答（按调用顺序 `NNN.txt`）与该次请求的指纹（`NNN.request.sha256`）；
  `--replay-from <run_root>` 按同一顺序读回，不构造客户端、不占预算；当前请求与保存的指纹不一致（原文、卡片、定义或提示词变了）、
  缺指纹或目标已有输出时拒绝回放（Codex 审核 PR #159 第 2、3 项）。

### 3.6 删除

照抄引文的提示词、quote 解析与"任一引文失败即丢字段"的路径删除；`QuoteVerifier` 只保留评测与标注工具仍在用的部分。

## 4. 验收

- 受保护验收（RED 单独提交）：`tests/evidence/test_segments.py`、`tests/compilers/schema_fields/test_pointer_protocol.py`、`tests/compilers/schema_fields/test_field_cards.py`、
  `tests/eval/test_segment_score.py`、`tests/eval/test_compile_replay.py`；S4a 的 `test_engine_contract.py` 按新合同改写（同一 RED 提交，原因见 §1）。
- `harness/` 下 `pytest`、`ruff check .`、`mypy src tests` 通过；守卫全部通过；CI 全绿。
- 真实验证：四款产品两步编译，报告段落召回/精确率（对 Golden v2）与语义准确率/完整率（对 Golden v2 的值），与 S4b 对比。

## 5. 改动范围

- 允许：`evidence/segments.py`（新）、`evidence/quote_verification.py`（删不再使用的部分）、`eval/pdf_text.py`、`compilers/schema_fields/`（含 `field_cards.json`）、
  `eval/compile_run.py`、`eval/segment_score.py`（新）、`dataset/golden/v2/`、`harness/pyproject.toml` 与 `uv.lock`、对应实现方测试。
- 受保护：本片验收文件、既有受保护验收、`docs/design/`、蓝图。

## 6. 真实调用预算

- `deepseek-flash`，S4d 累计上限 100 次（含 A2–A7 与留出产品实验已用约 90 次）。四款产品真实验证约需 25 次，另行申请。
- 评委：GPT-6 Astra xhigh，由 Claude 以 `codex exec` 启动：Golden v2b 4 个会话、留出产品复核每款 1 个、语义评分每轮 1 个。
