# SK-1 方法用途登记与方法材料归属

> 状态：Spec r3（2026-11-01，Claude；r2 在 §3.1 补“已挂产品的销售材料补登记方法用途”；r3 按 Owner 修订把适用范围改为
> 多标签、机器优先，改 §1、§2.3、§3.2、§4、§7、§8，见 SK-0 §4.2 修订注）。设计依据：[SK-0](SK-0-销售方法与通用知识.md) §1、§2.2、§3.4、§4.1–§4.3、§9 SK-1 行；
> [PV-3](PV-3-培训材料按版本归属与人工闭环.md)（方案 A、`uploads detach`）；[S11c](S11c-Harness读取Office与销售材料.md)（块切分、
> `sales_training` 只服务四个销售字段）。跟踪 Issue #507。实现 Claude，审核 Codex。依赖 PV-3（已合并）。
> 真实调用 0；不部署；不迁移、不写线上登记表。

## 1. 目标与不做

做：v2 登记表上，销售/培训类材料在原始来源修订（`knowledge_id + parse_attempt + sha256`，下称“三元组”）上登记**材料级方法
用途记录**（命中块、险种类别标签、决定来源；不含方法 ID）及其失效；方法信号在块级检测，独立于 `role_of()`；新归属结论
`METHOD_MATERIAL`（无版本可挂、含方法信号的材料不再隔离）；唯一版本匹配（或版本问题待人）且含方法信号时另记方法用途
（“版本 + 方法”双记录）；适用范围标签按确定性词表判定：材料各块命中的**每个**险种标签（与“通用”）都由机器打上并记依据，
一个都没命中才在待确认材料页由人选择（可选多个）；标签是适用标签、不是产品事实，之后可由人经同一确认流程更正；
`material_roles.json` 新增不参与自动识别的 `sales_method` 角色，TrustPolicy 把它限定在方法卡谓词。

不做（SK-2/SK-3）：方法发现与准入、方法 ID 与 `methods` 段、方法卡、编译、发布、合同、Go、页面、问答。产品知识的编译器身份
**不变**：产品条目、材料、`source_map()`、`registered()` 与产品材料的有效角色都不受方法用途影响；编译输出复用身份
（材料、有效角色、卡片版本、取值协议）不含角色数据文件与 TrustPolicy 的版本。v1 登记表的行为**不变**：方法用途与
`METHOD_MATERIAL` 只在 v2 启用，v1 文件拒绝这些字段（与 PV-1 审核 R5、PV-3 R7 同一规则）。

## 2. 数据

### 2.1 词表 `catalog/sales_taxonomy.json`（版本化数据）

| 键 | 内容 |
|---|---|
| `version` | 词表版本，进入方法用途记录的依据 |
| `method_signals` | 方法信号词（销售方法、讲解步骤、讲解逻辑、讲解关键句、关键句、需求分析、异议、促成、转保、实操、学习笔记…） |
| `min_signals` | 一份材料至少命中多少个**不同**信号词才算方法材料（防止产品材料偶然出现一个词） |
| `insurance_categories` | 险种类别：`label` = 归属策略 `classifications` 中的 `classification`（与导航分组同一组标签），`words` = 命中词 |
| `general` | 通用：`label = scope:general`，`words`（通用、不限险种…） |
| `plan_types` / `life_stages` / `sales_stages` | SK-0 §2.2 的其余维度，`plan_type:` / `life_stage:` / `sales_stage:` 前缀；SK-1 只校验与保存，按方法判定在 SK-2 |

校验：标签唯一、各维度前缀正确、险种标签都是归属策略的 `classification`，词非空、不跨标签重复。

### 2.2 角色与 TrustPolicy

- `material_roles.json`（版本升级）：角色新增 `recognized`（默认 `true`）。新角色 `sales_method`：`evidence: false`、
  `recognized: false`、无关键词。`role_of()`、`role_signals()` 只看 `recognized` 的角色，所以现有材料的角色识别逐个不变；
  “选择角色”问题只列可识别角色（`sales_method` 不出现在产品材料的角色选项里，现有问题的选项不变）。
- `trust_policy.json`（版本升级）：`scoped_rules` 新增 `sales_method` → 方法卡五个谓词（`method_summary`、`method_steps`、
  `key_phrases`、`applicable_scenario`、`cautions`）。产品字段编译只读产品条目的材料，从不包含 `sales_method`；方法编译（SK-2）
  只读方法用途记录。两边都不放宽 S11c。

### 2.3 材料级方法用途记录（登记表 v2 新增 `method_uses`）

每条记录：

| 字段 | 说明 |
|---|---|
| `knowledge_id`、`parse_attempt`、`sha256`、`file_name` | 三元组（与产品材料相同的来源身份） |
| `role` | 固定 `sales_method` |
| `block_scheme` | 块编号方案，固定 `segments.v1`：用 S4d/S11c 的分段规则只切这一份材料，块 ID = `P<页>S<序号>`（Office 页按块切分，分段不跨块） |
| `block_ids` | 命中方法信号的块（非空，按出现顺序，去重） |
| `signals` | 命中的方法信号词（去重、排序） |
| `label_hits` | 词表命中的每个标签（险种标签或 `scope:general`，按标签排序），各带命中块 ID 与命中词：机器结论的依据 |
| `evidence_digest` | 上述依据与词表版本的摘要；确认题的修订号包含它，依据变了就是新问题 |
| `taxonomy_version` | 判定时的词表版本 |
| `state` | `awaiting_scope`（一个标签都没命中，待人选）/ `active` / `ignored` / `invalidated` |
| `categories`、`decided_by`、`confirmation` | 结论：生效的适用范围标签（排序；`active` 时非空）、`machine`/`person`（机器结论恰好是 `label_hits` 的全部标签）、人最近一次答复的引用 |
| `editing` | 人正在选择或更正标签（只在 `active` 时；题目在页上，§4） |
| `invalidated_reason` | `source_revised` / `withdrawn` / `detached` / `ignored`（`invalidated` 时必填） |
| `settlement` | 人工答复的待执行意图（先存后关，见 §4.3），只在题目在页上（`awaiting_scope` 或 `editing`）时存在 |

规则：同一三元组最多一条记录；同一 `knowledge_id` 最多一条未失效（`awaiting_scope`/`active`）记录；失效记录保留（审计），
不复活——材料新修订是新三元组、新记录（SK-0 §4.3）。

## 3. 判定（`identity/method_signals.py` 纯函数 + `ingest/method_uses.py`）

### 3.1 何时检测

只在 v2 登记表、对本轮被判定的材料（`attribute_uploads` 的候选，与产品归属同一次页面读取）检测：

- 材料的归属结论角色在 `brand_roles`（`sales_training`），或角色未识别且是 Office 文件（与 S11c/PV-3 的启用位置相同）；
- 条款、说明书、费率表从不检测（它们的角色可识别且不在上述集合）；
- 已有最终决定的材料（`IGNORED`、`DETACHED`）与已有同三元组记录的材料不再检测；
- **已挂在产品条目上的销售/培训材料**（记录角色在 `brand_roles`，即 SK-1 之前或由人挂接的）不再被重判，因此每轮对列表中
  修订一致、还没有本修订方法用途记录的这类材料单独读页检测一次（补登记）；没有命中不记录，下一轮再读（这类材料很少，读取
  量有界）。产品条目与材料不变（实现中补充，r2）。

### 3.2 方法信号与险种

- 全部页面按 `segments.v1` 切块；块文本（NFKC、去空白）含任一 `method_signals` 词即命中。命中的不同信号词少于
  `min_signals` → 不是方法材料。
- 适用范围：同样按块匹配 `insurance_categories` 与 `general` 的词（材料的全部块，不只命中方法信号的块）→ `label_hits`，
  每个标签记命中的块 ID 与词。
- 机器结论：命中的**每个**标签都打上（`active`，`decided_by = machine`，`categories` = 全部命中标签，可以多个，可以含
  `scope:general`）；一个都没命中 → `awaiting_scope`，交人（§4）。销售方法常适用于多个险种；标签是适用标签、不是产品事实，
  错了由人更正（§4.5），所以宁可多打一个标签，也不多问一道题。
- 为什么用全部块：离线重放中 5 份方法材料有 2 份的方法块里没有险种词（险种写在封面或产品页），只看方法块会把它们送给人。

### 3.3 与产品归属的组合（`attribute_uploads`）

| 产品归属结论 | 含方法信号时 |
|---|---|
| `QUARANTINE`（`no_registered_version`、`multiple_families`、`date_signals_conflict`、`no_product_anchor`、`anchor_conflict` 等） | 改为 **`METHOD_MATERIAL / method_material`**：留在 `pending`（与隔离一样每轮重判，以后登记了对应版本仍可匹配），**不推产品确认题**（旧的产品确认题按“已过时”关闭，不记人工答复）；同时登记方法用途 |
| `SUPPLEMENT`（方案 A 唯一版本等）、`NEEDS_CONFIRM`（版本或角色问题） | 产品结论照旧；**另**登记方法用途（双记录，两条记录绑定同一三元组，各自确认、各自记录） |
| 其他（`DUPLICATE` 等） | 不检测 |

`METHOD_MATERIAL` 是等待类结论（与 `NEEDS_CONFIRM`、`QUARANTINE` 一起属于 `WAITING`），不是最终结论；`attribute()` 从不
返回它，由 `attribute_uploads` 在记录前转换（与 `REPLACE`、`DETACHED` 一样只由特定步骤产生）。归属策略升版本
（`2026-11-01.7`），以此区分新规则下的结论；产品归属规则本身不变。

### 3.4 失效

`attribute_uploads` 每轮按完整列表：

- 记录的 `knowledge_id` 列出的修订与三元组不同 → `source_revised`（新修订按 §3.1 重新检测）；
- 不在完整列表、也不在未完成列表 → `withdrawn`；
- 材料有 `IGNORED` 决定 → `ignored`。

`uploads detach`（PV-3）：材料挂在产品条目上时照旧解除，并使该材料的方法用途失效（`detached`）；材料只有方法用途时
（`METHOD_MATERIAL`）也可解除：方法用途失效、移出 `pending`、记 `DETACHED` 决定（`product_id` 为空、`role = sales_method`），
此后该 `knowledge_id` 不再参与归属与检测（与产品材料解除后“不再判定”一致）。

## 4. 人工确认（`ingest/method_confirmations.py`、`ingest/method_wording.json`）

### 4.1 问题

- 只问两种记录：一个标签都没命中的（`awaiting_scope`），和有人请求更正的（`editing`，§4.5）。机器打了标签的记录不问。
- 主题 `method:<knowledge_id>`（与产品题 `material:` 分开；产品题的同步与清理只处理 `material:`）；来源引用同产品题，可在页面
  打开原文件。
- **逐项多选**：平台确认项一次答复只能选一个选项（S5b-3a；`internal/enterprise/confirm` 的答复只有一个 `option_key`），所以
  多选按步进行。每题选项：加上每个未生效的标签（`add:<label>`，含 `add:scope:general`）/ 去掉一个已生效的标签
  （`remove:<label>`，生效标签不少于 2 个时；只剩一个时先加上新的再去掉）/ 完成（`done`，有生效标签时）/ 不是销售方法材料
  （`ignore`）。加上或去掉后标签立即生效（记录 `active`、人工），同一轮接着推出下一题；选“完成”结束。题面列出系统识别到的
  标签与当前生效的标签。
- 修订号 = 三元组、`evidence_digest`、词表版本、措辞版本、是否仅方法材料、生效标签、上一条答复 ID 的摘要：每一步都是新题，
  依据、状态或措辞变了的旧题按“已过时”关闭。
- 退出条件：平台确认项支持多选（平台合同与页面变更，另开切片，不在 SK-1）后，逐项改为一题多选，记录模型不变。

### 4.2 应用时重验

答复只在“题目仍是这条记录当前的问题”时应用：记录仍在问（`awaiting_scope` 或 `editing`）、三元组相同、条目的修订号与按
当前状态重算的修订号相同、选项在当前选项内；否则 `CHOICE_STALE`：按“已过时”关闭、记录不变，以当前的题再问。

### 4.3 先存后关（与产品题相同的提交纪律）

应用：先在记录上保存 `settlement`（条目、答复、选项、答复人、结论）→ 关闭条目（`applied`，平台在锁内核对答复仍是最新）→
执行保存的结论。中断后下一轮先对账：条目已按该答复关闭 → 执行；仍开放且答复未变 → 关闭再执行；答复已变或条目已按其他方式
关闭 → 清掉 `settlement`、重新判定。已保存的 `settlement` 不被重算覆盖；产品题已持久化的 `Settlement` 不受本片影响。

### 4.4 结论

- 加上/去掉 → `active`，`categories` 为结果，`decided_by = person`，`confirmation` 为本次答复，`editing = true`（接着问）；
  完成 → 标签不变，`decided_by = person`，记 `confirmation`，`editing = false`。
- 忽略 → 方法用途 `ignored`；材料只有方法用途（`pending` 中为 `METHOD_MATERIAL`）时同时记 `IGNORED` 决定（人工、带答复引用），
  材料不再参与归属与抽取（忽略语义不变）；双记录材料只忽略方法用途，产品用途不变。

### 4.5 更正

`uploads relabel --registry PATH --knowledge-id ID [--dry-run]`（登记表锁下，与 `detach` 相同）把该材料有效的 `active` 记录
标为 `editing`，下次 `confirm` 按 §4.1 从当前标签起推出同一题；已在问的记录不变；没有有效记录 → `METHOD_USE_NOT_FOUND`。
`label_hits`（机器依据）不变；人的更正记在 `categories`、`decided_by`、`confirmation`，每一步的答复与关闭留在平台上（只追加）。

已知限制：材料换新修订是新记录，按词表重新打标签，之前的人工更正不带过去（SK-0 §4.3“不复活”）；业务需要沿用时另开切片。

## 5. 兼容

- v1 登记表：`method_uses` 必须为空，任何 `METHOD_MATERIAL` 结论都拒绝（载入与 `record` 都拒绝）；v1 文件写回不含 `method_uses`。
- 现有产品材料的角色识别、产品确认题的选项与修订号不变（措辞文件不改；产品题只覆盖可识别角色）。
- 已持久化的产品题 `Settlement` 不受影响（带 `settlement` 的材料不被重判，与 S11a 相同）。

## 6. 改动范围

新增：`catalog/sales_taxonomy.json`、`catalog/sales_taxonomy.py`、`identity/method_signals.py`、`ingest/method_use_model.py`、
`ingest/method_uses.py`、`ingest/method_confirmations.py`、`ingest/method_wording.json`。修改：`identity/material_roles.json`、
`identity/material_roles.py`、`catalog/trust_policy.json`、`identity/attribution.py`（结论类型）、`identity/attribution_policy.json`
（版本）、`identity/confirmation.py`（角色选项只列可识别角色）、`ingest/confirmation_questions.py`（措辞覆盖可识别角色）、
`ingest/confirmations.py`（产品题不含 `METHOD_MATERIAL`）、`ingest/registry.py`、`ingest/product_versions.py`、
`ingest/raw_sources.py`（整份页面读取）、`ingest/uploads.py`（含 `relabel` 命令）、`ingest/detach.py`。合并 S5b-9 后 `uploads.py`
超过 500 行，登记表锁原样移到新文件 `ingest/registry_lock.py`，已挂材料补检测的读页移进 `MethodStep`（都不改行为）。测试为新增文件；受保护测试只改版本号（单独披露提交）。

## 7. 验收（RED，合成材料）

1. 现有材料角色识别不变（`role_of` 对含方法词的合成材料与改前一致；`sales_method` 从不被自动识别）。
2. 块检测：合成 PPTX（多页多块）与 PDF；命中块 ID、信号、`min_signals` 门槛；条款/说明书/费率表不检测。
3. 适用范围：命中的每个标签都由机器打上（一类、多类、类 + 通用、只通用），每个标签带块与词依据；都没命中 → 待人。
4. 组合：无版本可挂的培训材料 → `METHOD_MATERIAL`（不再隔离、不推产品题、每轮重判；之后登记了版本 → 方案 A 正常挂接，
   方法用途保留）；唯一版本 → `SUPPLEMENT` + 方法用途（两条记录、同一三元组）；版本问题待人 → 问题照旧 + 方法用途。
5. 失效：新修订、撤出列表（未完成的不算）、`IGNORED`、`detach`（产品材料与仅方法材料）。
6. 人工确认：只问无标签与请求更正的记录；逐项加上、去掉、完成，下一题同一轮推出；修订号含依据、生效标签与上一条答复；
   应用写结论与答复引用；`relabel` 更正机器标签；依据或状态变了 `CHOICE_STALE`；先存后关的中断对账；忽略的两种语义。
7. v1：拒绝 `method_uses` 与 `METHOD_MATERIAL`；写回不含新字段。
8. 编译器身份：产品条目、`source_map()`、`registered()` 在登记方法用途前后逐字节相同。

## 8. 离线重放（不读线上、零模型）

线上登记表只读副本按 PV-1 迁移为 v2，并模拟登记 2635-1（与 PV-3 重放相同）：

- 全部 PDF 材料（90 份）判定结果与基线逐份相同（方法检测不改变它们）；
- 6 份 Office 材料：只报告结论、命中块数、信号数、标签结论（机器/待人）与标签数，不报告任何文本；预期有方法用途的材料
  都由机器打标签、不产生确认题。重放的整份页面由本机从
  原文件按 Office 结构近似切出（平台采集不可读时的替代），与平台块切分可能不同，只作工程验证。
