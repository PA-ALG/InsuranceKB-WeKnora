# S3e · 企业知识导航与概念页：按领域与险种组织，跨产品概念带模型汇总与对照表

> 状态：用户已确认（2026-10-18：导航按 Schema 的 11 类险种、领域可扩展到权益与服务；概念页开头用大模型说明与跨产品汇总，接可点击切换的产品对照表与实时摘要；同意修订"模型补充不含产品事实"的规则；概念生成预算 ≤ 40 次 deepseek-flash，质量优先；"关键字段"子字段放到下一轮；UI 一次构建上线）
> 作者：Claude Code ｜ 依据：蓝图 §5.1、§7.2（概念实体与 `relates_to_concept`）、§7.4，硬边界 5、6
> 拆分：S3e-1 发布数据与合同（Harness，Claude 实现、Codex 审核）· S3e-2 导航与概念页（前端，Codex 实现、Claude 审核）· S3e-3 概念说明生成（Harness 真实调用，Claude 实现、Codex 审核）

## 1. 目标

1. **导航**：
   - 企业知识页左侧是导航树：领域 → 分组 → 条目 → 展示分组 → 字段。
   - 领域先有"产品库"，按 Schema 的 11 类险种分组，显示每组条目数。
   - 以后加"服务权益""服务条线"等领域只改导航数据，不改页面代码。
2. **概念页**：Release 中被 2 个及以上条目使用的同一字段（如犹豫期）就是一个跨产品概念。页面内容依次为：
   - 字段定义：`concept` 成员中面向读者的一句定义，标"模型补充"；没有发布概念说明时不显示（见 §3"审核补充"的 S3e-4 修订）；
   - 模型说明：这是什么，标"模型补充"；
   - 跨产品汇总：各产品在这一点上的情况。每句话都挂上依据的产品 Claim，程序核对其中的数字与期限，标"模型汇总（依据各产品原文）"；
   - 对照表：险种、产品、实时摘要、出处数、跳转到该产品的这个字段。
3. **关联**：
   - 产品页的字段标题链接到它的概念页；
   - 概念页反向列出所有产品（相当于 `mentioned_by`），并列出同一 Schema 分类下的"同类概念"。
4. **一致性**：页面和其中的全部链接读同一个 Release；模型说明在发布时生成，浏览时不调用模型。

## 2. 发布数据（S3e-1）

### 2.1 导航（新成员种类 `navigation`）

- 数据文件 `catalog/navigation.json`（版本化）：

```json
{"navigation_id": "enterprise", "navigation_version": "2026-10-18.1",
 "domains": [
   {"domain_key": "product", "display_name": "产品库", "entity_types": ["insurance_product"],
    "groups": [{"group_key": "schemapack_medical_insurance", "display_name": "医疗险",
                "classification_labels": ["medical_insurance"]}, "… 其余 10 类，按 Schema 顺序 …"]},
   {"domain_key": "service_benefit", "display_name": "服务权益", "entity_types": ["service_benefit"], "groups": []}]}
```

- 产品库的 11 个分组由 schema pack 目录生成（`display_name` 与 `applicable_classifications` 原样取用）。生成规则写在 Harness 中，生成结果写入数据文件，可以人工调整顺序。
- Harness 合同新增 `NavigationProfile`（`navigation_id`、`navigation_version`、`domains[domain_key, display_name, entity_types[], groups[group_key, display_name, classification_labels[]]]`）。校验键唯一、名称非空；导出 JSON Schema 到 `contracts/`。
- 发布命令每次在候选包中带上导航成员，slug 为 `navigation/<navigation_id>`。导航成员整体替换，与 presentation profile 相同。
- 读者规则：
  - 条目按 `entity_type` 归入领域；
  - 再按 `classification_labels` 与分组标签的交集归入分组，取第一个匹配的分组；
  - 归不进任何分组的条目放进该领域的"其他"；
  - 没有条目的分组与领域不显示；
  - Release 中没有导航成员时，退化为现在的平铺列表。

### 2.2 展示分组与字段定义（合同字段扩展）

- `PresentationProfile` 增加 `display_name`，取 pack 的显示名，如"重疾险"。
- `ProfileField` 增加 `description`（可空），取 Schema 字段说明，用作概念页的"字段定义"；再增加 `schema_category`（可空），如"05 合同与交费规则"，用于"同类概念"。
- 两者都是新增的可空字段，旧 Release 不受影响。

## 3. 概念页与导航（S3e-2，前端）

- **路由**：
  - `enterprise/:spaceId` 改为双栏布局：左侧导航树（领域页签 + 树），右侧为首页或所选内容；
  - 新增 `enterprise/:spaceId/concepts/:conceptKey`（`?release=` 同条目页）；
  - 条目页的字段带锚点 `#<field_key>`，从对照表跳过去时直接定位到该字段。
- **视图模型**（纯函数，`releaseView.ts` 或新文件）：
  - `navigationTree(release)`；
  - `conceptKeys(release)`：被 ≥ 2 个条目使用、状态为 present 或 absent_explicitly 的谓词；
  - `conceptView(release, key)`：标题、定义、同类概念、对照行，以及模型说明（如有）。
- **实时摘要**：
  - 取值有编号结构时，取前 3 条的名称，用"；"连接；
  - 否则取第一句；
  - 最多 60 字，超出加"…"；
  - absent / unknown 显示状态文案。
- **模型说明**：读 `concept/<key>` 成员（§4）。
  - 通用说明标"模型补充"；
  - 跨产品汇总每句后接产品链接，标"模型汇总（依据各产品原文）"；
  - 若该成员记录的依据 Claim 摘要与当前 Release 不一致，显示"汇总基于较早版本"，仍然显示。
- **"概念"页签**：按 schema 分类列出所有概念。
- **体验**：覆盖加载、空状态、失败重试与键盘可达；窄屏下导航可折叠。

### 3.1 S3e-2 细则（验收依据）

- **视图模型**：
  - `navigationView.ts`：`navigationTree(release): NavigationDomain[]`，其中 `NavigationDomain {key, title, groups}`，`NavigationGroup {key, title, entries: EntitySummary[]}`。
    - 归不进分组的条目放进 `{key: '__other__', title: ''}`；`entity_type` 不属于任何领域的条目放进末尾的 `{key: '__other__'}` 领域。
    - 没有导航成员时，返回唯一领域 `{key: '', title: ''}`，其中唯一分组 `{key: '', title: ''}` 按成员顺序列出全部条目。
  - `conceptView.ts`：
    - `conceptKeys(release)`：按 profile 中字段出现的顺序，余下的按键名排序；
    - `conceptView(release, key)`：返回 `{key, title, definition, category, related[{key,title}], rows[{entityId, name, group, state, summary, evidenceCount, slug}], summary | null}`。非概念返回 `null`。行按条目成员顺序排列，包含该字段的全部 Claim（含 unknown）。
    - `summary` 为 `{explanation, statements[{text, refs[{slug, entityId, name}]}], stale}`；`stale` 在 `based_on` 中任一摘要与当前成员摘要不同或成员缺失时为真。
  - `liveSummary(state, value)`：
    - 非 present 返回空串；
    - 数组：取前 3 个元素的名称（有"名称："时去掉冒号），否则取元素原文，以"；"连接，多于 3 个加"…"；
    - 字符串且顶层各条都有名称：取前 3 个名称，规则同上；
    - 其余情况取第一句（到第一个 `。；;！？!?` 为止，含该符号）；
    - 超过 60 字的截到 60 字并加"…"。
- **页面与 data 属性**：
  - Space 页：
    - 领域页签 `[data-nav-domain]`；分组标题 `[data-nav-group]`，含条目数；条目链接 `[data-nav-entry]`，显示名称与"n 项"；
    - 概念链接 `[data-nav-concept]`，路由为 `{name: 'enterpriseConcept', params: {spaceId, conceptKey}, query: {release}}`。
  - 概念页 `EnterpriseConcept.vue`（props：`spaceId`、`conceptKey`、`releaseId?`）：
    - `[data-concept-definition]`；
    - `[data-concept-explanation]`（含"模型补充"）；
    - `[data-concept-summary]`（含"模型汇总（依据各产品原文）"）；
    - `[data-concept-statement]`，每个引用一个条目链接，带 `hash: '#<conceptKey>'`；
    - `[data-concept-stale]`；
    - `[data-concept-row]`，每行一个条目链接，带同样的 hash；非 present 行显示状态文案；
    - `[data-concept-related]`；
    - 加载失败用 `[role="alert"]` 加重试，非概念显示"该版本中没有这个概念"。
  - 条目页：
    - 字段根元素 `id` 为字段键；
    - 是概念的字段，标题 `.ek-field__title` 内为概念链接；不是概念的保持纯文本。
- **文案**（zh-CN，其余 4 种语言同步）：
  - 导航：`nav.other`"其他"、`nav.concepts`"概念"；
  - 概念页：`concept.definition`"字段定义"、`concept.summary`"模型汇总（依据各产品原文）"、`concept.stale`"汇总基于较早版本"、`concept.related`"同类概念"、`concept.notFound`"该版本中没有这个概念"、`concept.failed`"概念加载失败"；
  - 表头：`concept.columns.group`"险种"、`concept.columns.product`"产品"、`concept.columns.summary`"摘要"、`concept.columns.sources`"出处"；
  - 模型说明的标签沿用 `origin.generated`"模型补充"。
- **审核补充（PR #218，2026-10-18，Claude 用真实数据渲染后提出）**：
  - **字段定义的来源**：154 个 Schema 字段说明中有 28 个混有抽取指令（如"只允许从正式条款中抽取"），不宜原样展示。
    - 概念页的"字段定义"优先取 `concept` 成员的 `definition`，由 S3e-3 生成：依据 Schema 说明改写成面向读者的一句定义，去掉抽取指令，并归在"模型补充"的标注之下；
    - ~~没有 `concept` 成员时，才显示 profile 中的字段说明。~~ **S3e-4 修订（2026-10-18）**：没有 `concept` 成员，或其 `definition` 为空时，概念页与关系图都**不显示字段定义**，不再回退到 profile 的字段说明。原因：字段说明是写给抽取模型的，真实 Release 的 143 个字段说明中有 37 个含抽取指令（如"优先提取产品说明书……""只允许从正式条款中抽取"）；会走到回退的恰好是概念说明生成失败的概念，例如 epoch 29 的"产品特色"就把抽取指令显示给了读者。profile 的 `description` 字段本身保留（Agent 与抽取仍可使用），只是不在阅读页面显示。
  - **对照表的行序**：先按导航分组顺序，同组内再按条目成员顺序，让同一险种的产品排在一起；不在任何分组的条目排在最后。
- **S3d-3a 验收修正**：Space 页也会列出概念链接，所以 `enterprisePages.spec.ts` 中 Space 页那条用例只核对条目链接，其余断言不变。

## 4. 概念说明生成（S3e-3，Harness，真实调用）

- **范围**：Active Release 中被 ≥ 2 个条目使用的谓词。按 13 款产品估计约 70 个概念。
- **输入**：每个概念给模型三样东西：
  - 字段定义（Schema 说明）；
  - 每个产品的 Claim：产品名、险种、状态、取值，不带编译上下文；
  - 输出格式。
- **输出与新成员种类 `concept`**（slug `concept/<field_key>`）：

```json
{"concept_key": "cooling_off_period", "title": "犹豫期", "definition": "<Schema 字段说明>",
 "explanation": "<通用说明，MODEL_GENERATED>",
 "statements": [{"text": "多数产品的犹豫期为15日……", "refs": ["596/cooling_off_period", "…"]}],
 "based_on": {"<claim slug>": "<member_digest>"}, "origin": "MODEL_GENERATED",
 "model": "<served model>", "prompt_version": "concept-2026-10-18.1"}
```

- **确定性检查**（不通过的概念不发布，记入报告）：
  - `explanation` 不得出现 Release 中任何产品的名称或编号；
  - 每条 `statement` 至少引用 1 个 Claim，且引用的 Claim 都在 `based_on` 里；
  - `statement` 中出现的每个"数字 + 单位"（日、天、年、周岁、%、元、次等）都必须出现在某个被引用 Claim 的取值中（对齐全角/半角与空白）；
  - 每个被引用的产品，名称或编号要出现在该句中，或该句是概括性陈述（如"多数产品""各产品"）；
  - 文本长度有上限。
- **质量优先**：
  - 每次调用 1–2 个概念；
  - 单个概念检查失败时，在预算内重试 1 次；
  - 第二次仍失败就不发布该概念（页面仍有对照表；S3e-4 起不显示字段定义）。
- **发布**：
  - 单独的命令 `concept_publish`，以 Active 为 base 提交只含 concept 成员的候选包；
  - 人工决定，理由写明是模型汇总；不撤下 Claim。
- **预算**：deepseek-flash ≤ 40 次，可续跑，预算与账本同 compile_run。

### 4.1 S3e-3 细则（验收依据）

- **合同 `ConceptSummary`**（`contracts/knowledge.py`，导出为 `concept_summary.schema.json`）：
  - 字段：
    - `concept_key`、`title`、`definition`、`explanation`：均非空；
    - `statements[{text, refs[≥1]}]`：1–6 条；
    - `based_on{slug: sha256}`：非空；
    - `origin` 固定为 `MODEL_GENERATED`；
    - `model`、`prompt_version`。
  - 每条 statement 的 `refs` 都必须在 `based_on` 中。
- **概念输入 `concept_inputs(release)`**（`compilers/concepts/synthesis.py`）：
  - 取被 ≥ 2 个条目陈述（present 或 absent_explicitly）的谓词，顺序同前端 `conceptKeys`。
  - 每个概念：
    - 来自 profile：标题、Schema 说明；
    - 每个陈述了它的条目：条目名、险种（profile `display_name`）、状态、取值、Claim slug 与成员摘要。
  - unknown 的 Claim 不进入输入。
- **请求**：
  - system 提示词说明任务与 JSON 格式：
    - `definition` 用一句话给出面向读者的定义，不含抽取指令；
    - `explanation` 写通用解释，不点名任何产品；
    - `statements` 写跨产品汇总，每句列出所依据的 slug。
  - user 是 JSON，内容为各概念的输入。
  - 每次调用 `--per-call` 个概念，默认 2（质量优先）。
- **解析**：
  - 只接受 `{"concepts": [{"key", "definition", "explanation", "statements": [{"text", "refs"}]}]}`。
    - 修订（2026-10-18 真实运行后）：模型给概念或句子对象多加的字段（如 `title`、`explanation_note`）直接忽略，不读取也不发布。
    - 必需字段缺失或类型错误仍整批拒绝；顶层对象仍只能有 `concepts`。
  - 键与本批概念一一对应；
  - 不符时整批记为 `CONCEPT_OUTPUT_INVALID`，不重试解析。
- **确定性检查** `check_concept(draft, concept, release_names)`，返回问题码列表，空表示通过：
  - `DEFINITION_LENGTH`（不超过 120 字）、`EXPLANATION_LENGTH`（不超过 400 字）、`STATEMENT_LENGTH`（每句不超过 200 字）；
  - `PRODUCT_NAMED`：`definition` 或 `explanation` 中出现 Release 中任一条目的名称或编号；
  - `REF_UNKNOWN`：引用了不属于该概念输入的 slug；
  - `NUMBER_UNSUPPORTED`：statement 中"数字 + 单位"（日、天、个月、月、年、周岁、岁、%、％、元、万元、次、倍）在被引用的 Claim 取值中都找不到；比较前先做 NFKC 并去掉空白。
    - 修订（2026-10-18 真实运行后）：以下写法在两边按同一规则处理。
      - 点一律当作小数点。列表序号与写了空格的小数无法可靠区分（#227 四轮审核），所以列表里的"1. 20年"也读作 1.2年：宁可拒收，也不截取尾数；
      - 以不含"十、百、千、万"等进位字的中文数字开头（"零"除外）、紧接阿拉伯数字的写法（如"计划三5000元"），前面的中文数字是标签，数从阿拉伯数字开始。含进位字的混写（如"一万零5元"）仍按整数读取；
      - 这两条只用于读数字。`PRODUCT_NAMED` 的名称比对仍是 NFKC 后去空白，不做这些改写。
  - `NUMBER_UNMATCHED_REF`：statement 含数字记号，而某个被引用 Claim 的取值里一个都不包含，防止"均为 15 日"挂上一条 20 日的产品；
  - `STATEMENT_COUNT`：statement 少于 1 条或多于 6 条。
  - 修订：原 §4 中"被引用产品须在句中点名"一条不再检查。前端在每句后列出被引用产品的链接，点名与否不影响可回验性；数字核对已经保证事实一致。
- **重试**：未通过检查的概念单独再请求 1 次，把问题码作为提示附上，消耗预算。仍不通过的概念不发布，记入报告。
- **运行与发布**（`compilers/concepts/run.py`）：

  ```text
  python -m insurance_harness.compilers.concepts.run --space S --stage concepts --stage-config F --run-root D [--max-sent N] [--per-call K] [--publish --reason TEXT]
  ```

  - 用 API Key 读取 Active Release。
  - 断点续跑：已接受的响应按请求 sha256 保存，同一请求不重发。预算与账本沿用 `models/durable.py`（`--max-sent` 累计计数，运行目录加锁）。
  - 写出：`concepts.json`，含通过检查的 `ConceptSummary`，`based_on` 取输入时的成员摘要；以及 `report.json`，含每个概念的问题码、发送次数与重试情况。
  - 加 `--publish`：以 Active 为 base 提交只含 concept 成员的候选包（slug 为 `concept/<key>`，不带 removals），人工决定并激活，理由取自 `--reason`。
  - 任何一步失败都打印一行 `{"stopped": <code>}` 并以 2 退出，输出中不含路径或密钥。
- **新阶段**：`models/stages.json` 增加 `concepts`，模型与供应商同 `schema_fields`，`policy_version` 为 `concept-2026-10-18.1`。

## 5. 蓝图修订（§7.2，用户 2026-10-18 同意）

原规则："模型补充的通用概念解释……出现具体产品事实即被确定性检查拦下"。修订为：
- 通用解释仍不得出现具体产品事实；
- 概念页的"跨产品汇总"可以陈述产品事实，但每句必须引用所依据的已发布 Claim，其中的数字与期限必须能在被引用 Claim 的取值中找到，并单独标注"模型汇总（依据各产品原文）"。

## 6. 验收（各子片的 RED 单独提交）

- **S3e-1**：
  - `NavigationProfile` 与扩展字段的合同测试和导出的 JSON Schema；
  - 导航数据由 pack 目录生成的 11 个分组；
  - 发布候选包带导航成员，profile 带 `display_name`、字段说明与分类；
  - 旧 Release 读取不受影响。
- **S3e-2**：
  - 导航树分组与"其他"，没有导航成员时退化；
  - 概念键（≥ 2 个条目）；
  - 对照表行、实时摘要与跳转锚点；
  - 模型说明的标注与"较早版本"提示；
  - 字段标题链接到概念页；
  - 加载、空、失败状态。
- **S3e-3**：
  - 确定性检查逐项（产品名泄漏、缺引用、数字不在 Claim 中、长度）；
  - 生成命令的预算、续跑与失败概念不发布；
  - 候选包只含 concept 成员。

## 7. 上线

S3e-1、S3e-2、S3e-3 合并后一次性执行：
- 重新发布 13 款产品的导航与 profile（不重新编译，无模型调用）；
- 生成并发布概念说明；
- 构建 1 次 UI 并替换（包含已合并的 #214）。
