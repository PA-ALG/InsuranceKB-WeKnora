# PV-3 培训材料按版本归属（方案 A）与人工闭环

> 状态：Spec（2026-11-01，Claude）。设计依据：[PV-0](PV-0-产品版本与生命周期.md) §0、§4.1–§4.4、§9 PV-3 行，
> [附录 A](PV-0-附录A-身份发布同步与迁移.md)。跟踪 Issue #501。实现 Claude，审核 Codex。依赖 PV-1（#505，登记表 v2）。
> 真实调用 0；不部署；不迁移、不写线上登记表。

## 1. 目标与不做

做：v2 登记表上，销售/培训材料在强内容锚点（条款编号、首页标题、整行标题）缺失时，按“品牌 + 日期信号”在已登记版本中
计算**候选全集**并逐个给出一致性结论；只有一个一致候选时**自动归属**并记为机器结论（方案 A）；否则交人，人只能选“一致”的
候选（无日期信号时可选类型不矛盾的同系列版本，记为人工版本决定）；应用答复时按同一规则重验；决定记录保存不可变依据并分开
记录版本与角色由谁决定；补培训材料的角色信号（数据）；`uploads detach` 受控解除归属。

不做：主数据同步（PV-2）；合同、发布、Go 读取、页面、问答（PV-4）。编译、取值协议、字段卡、发布、证据、评分、
`material_roles.json` 与 `contracts/` **一律不改**，编译器身份不变。v1 登记表的归属行为**逐字节不变**（本片所有新行为只在
登记条目带版本数据，即 v2 登记表时启用）。

## 2. 规则（`identity/training_versions.py`，规则为数据：`attribution_policy.json`）

### 2.1 启用条件

与 S11c 品牌候选相同的位置（条款编号与标题锚点都未定下产品之后）：材料角色在 `brand_roles` 内，或角色未识别且是 Office
文件；并且登记表是 v2（`registered()` 的条目带版本数据）。v1 登记表照旧走 S11c 品牌候选。条款、说明书、费率表永远不走方案 A。

### 2.2 培训角色信号（只在 v2 启用）

`role_of` 未识别出角色、且**没有任何**其他角色显示信号时，文件名或开头窗口含 `training_signals` 中的词（培训、学习材料、
学习课程、课程、销售方法、销售技巧、话术、集训、训练、通关、异议处理、常见问题）→ 角色为 `training_role`（`sales_training`）。
任何别的角色有信号（名称或开头）→ 仍未识别，不覆盖冲突。词表在归属策略中，不改 `material_roles.json`（编译读后者）。

### 2.3 品牌系列

已登记条目的品牌核心沿用 S11c（`brand_core`）；材料文件名或开头窗口含某条目品牌核心的前 `brand_min_chars` 个字 → 该条目是
品牌命中（召回）。每个命中取材料实际写出的**最长核心前缀**；这些前缀里互不为前缀的“最宽”者多于一个 → 材料分别写出了不同系列
（即使它们共享短前缀，如“远山恒泰”“远山恒安”），`QUARANTINE / multiple_families`（只能忽略）；只写出一个系列时，前缀与之不相容
的命中不进入系列（审核 R1）。
没有任何命中 → `QUARANTINE / no_registered_version`（只能忽略）。v2 下培训材料不再提供“任选已登记产品”。

### 2.4 日期信号

来源只限材料本身：文件名（`file_name`）、开头窗口（`opening`，归属策略 `anchor_chars`）、头部文本中整行只是一个日期的行
（`date_line`）。读日期前先按 `date_masks`（数据）遮蔽货币金额、带单位的数字与方括号/〔〕引用编号，它们永远不是日期（审核 R2）。`date_patterns`（数据）按精度给出：日（`2024年5月27日`、`2024-05-27`、`2024.05.27`、`20240527`）、月
（`2024年5月`、`2024-05`、`2024.05`）、年（独立的四位年份）。被更精确匹配覆盖的较粗匹配不再单独计数；年份须在
`date_year_range` 内、月日须是合法日历日期，否则不是信号。每个信号转为半开日期区间（年 → 整年，月 → 整月，日 → 当日）。

**一致**：任意两个信号的区间相互包含（年 2024 ⊇ 2024-05 ⊇ 2024-05-27）；材料区间 `M` = 最精确信号的区间。
**冲突**：存在不相互包含的两个信号（文件名 2024-06、封面 2024-04）→ `QUARANTINE / date_signals_conflict`，只能忽略，
不先挑一个日期再算候选。**无信号** → §2.7 的 `no_date_signal`。

### 2.5 候选全集与逐个结论

在全部品牌命中条目上计算（任何展示上限之前）。条目 `v` 的销售期 `[sale_start, sale_end)`：`sale_start` 空 → 期间未知；
`sale_end` 空且来源状态为在售 → 开放到未来；`sale_end` 空而状态不是在售 → 期间未知。

进入候选全集：`year_tag` = `M` 的年份，或期间已知且与 `M` 有交集；与材料类型词矛盾（§2.6）的条目只展示为
`type_conflict`，不进候选。候选的逐个结论：

| 结论 | 条件 |
|---|---|
| `consistent` | 期间已知，且 `M` 为年精度（材料没有月/日信号要核对），或 `M`（月/日精度）完全落在期间内 |
| `partial` | `M` 为月/日精度，期间已知、与 `M` 有交集但不完全包含（月份跨越换版） |
| `date_conflict` | `M` 为月/日精度，期间已知且与 `M` 无交集（只因 `year_tag` 命中而进入候选） |
| `period_unknown` | 期间未知（只因 `year_tag` 命中而进入候选；可作候选，不能是“一致”的唯一候选） |
| `unbound` | 条目没有外部版本键（未绑定报备版本，PV-0 附录 A §4）：只展示，不作自动或人工目标（审核 R3） |

合法错位（标签年 = 起售年 + 1）：年精度时由“期间与该年有交集”或“`year_tag` 命中”任一覆盖，二者不互相否定；
精确日期落在期间外则是 `date_conflict`，不是合法错位。

### 2.6 类型词矛盾（数据）

只读材料的文件名与开头窗口；版本一侧只用明确信息，没有明确信息就不判矛盾：
- **险种形态组**（`plan_type_groups`：分红型 / 万能型 / 投资连结型 / 普通型，“普通型”也是明确写法）：材料只指向组内一种形态，
  且版本的 `plan_type`（或名称限定）是另一种 → 矛盾；材料指向多种或没有 → 不约束。
- **附加险**（`rider_words`）：材料标明附加险而版本名称不含“附加” → 矛盾。
- **版别**（`edition_pattern`，括号里以“版/款”结尾、不含数字的限定）：材料明确写出的版别（括号内或紧跟品牌）与已登记名称
  里被写到的版别合并；恰好一种时，任何不属于该版别的版本（含无版别的版本）都矛盾——无论正确版本是否已登记（审核 R3）。

渠道（“创”前缀）与“税优”不进矛盾表：材料极少写渠道；仓库 1841 个名称里只有 1 个写“税优”，版本一侧没有可靠标记，用它判
矛盾会把正确版本排除。二者只作展示依据。

### 2.7 结论

| 情形 | 结果 | 人可选 |
|---|---|---|
| 候选全集恰好一个，它是 `consistent`，角色已定 | `SUPPLEMENT / matched_by_version_period`（经 S5b-1 的既有判定：同角色已有材料时照旧 `same_role_differs`），机器版本 + 机器角色 | — |
| 同上但角色未定 | `NEEDS_CONFIRM / version_role_unresolved`，`product_id` 为该版本 | 只问角色：`brand_roles` 内的角色，或忽略 |
| 候选全集多于一个，或唯一候选不是 `consistent` | `NEEDS_CONFIRM / version_candidates` | 只有 `consistent` 的候选 + 忽略 |
| 候选全集为空 | `QUARANTINE / no_registered_version` | 只能忽略（正确版本未登记时只能忽略或等登记，不改选别的版本） |
| 日期信号冲突 | `QUARANTINE / date_signals_conflict` | 只能忽略 |
| 没有日期信号 | `NEEDS_CONFIRM / no_date_signal` | 类型词不矛盾的全部品牌命中条目（标注“材料无日期依据”）+ 忽略；选择记为人工版本决定 |
| 多个系列 / 无系列 | `QUARANTINE / multiple_families`、`no_registered_version` | 只能忽略 |

隔离的两类每次 `uploads run` 都会重判（登记了新版本后可能变为唯一），沿用 S5b-2。

### 2.8 依据记录

`Attribution.version_basis`（新，可空；v1 登记表从不写出）：日期信号（值、精度、来源）、材料区间、候选全集逐个结论
（条目 ID、外部版本键、结论）、所用元数据提交（登记表 `metadata_basis.commit`）、`version_decided_by`、`role_decided_by`
（`machine` / `person`）。它随 `Attribution` 进入 `pending` 与不可追加修改的 `decisions`，因此历史判断依据随决定保存，不依赖
条目当前元数据。问题 revision 由整份 `Attribution` 计算，依据（信号、结论、元数据提交）变化而候选 ID 不变也产生新问题。

## 3. 人工入口（`identity/confirmation.py`、`ingest/confirmation_questions.py`、`confirmation_wording.json`）

- **选项**：§2.7 的“人可选”；展示依据与可选资格分开——问题正文列出候选全集与逐个结论（最多 10 个，写明“共 N 个”），选项
  只有可选的。
- **应用时重验**（`conclude`）：v2 上除“忽略”外的**所有**答复（选版本、只问角色、同角色的替换/补充、人选版本后的第二问）都以
  同一材料与当前登记表重新判定，依据须相同（不含 decided_by）：问题本身要求原因相同且所选仍可选；机器定的版本要求仍是同一版本；
  人选的版本要求仍在重判后的可选集合内；否则 `CHOICE_STALE`（审核 R4）（问题作废、按当时
  情况重新提问，已持久化的 Settlement 按 S5b-3c-2 原协议完成，不被重算改写）。
- **旧问题**：v2 登记表上，若材料现在走方案 A（重判带出 `version_basis`），而待答问题是旧原因（`brand_candidates`、
  `no_product_anchor`），对它的产品选择一律 `CHOICE_STALE`，不能借旧问题绕过版本约束。
- **来源**：人选版本 → `version_decided_by = person`；只问角色 → 版本 `machine`、角色 `person`；自动归属两者都是 `machine`。
  替换、补充、忽略等终局决定保留问题里的 `version_basis` 与 `shared_versions`（审核 R4）。

- **共用条款号**（PV-1 附录 A §1.3 第 3 行的 `QUARANTINE / shared_clause_code`）：同样可推为问题，只能忽略；正文写明共用的
  条款编号、固定目录中共用它的报备版本（`Attribution.shared_versions`）与暂不能挂接的原因（内部编号按条款编号生成，无法区分
  这些版本）；忽略记为人工决定。v1 登记表与 `version_basis` 一样拒绝该字段。

## 4. 解除归属（`uploads detach`）

`uploads detach --registry PATH --knowledge-id ID --reason {wrong_version,wrong_product,not_product_material} [--dry-run]`：
持上传文件锁；只用于 v2 登记表（v1 拒绝，保持 v1 文件可被旧代码读取）；材料必须当前挂在某个条目下，且**不是该条目的最后一份**
材料（`LAST_MATERIAL`）：没有来源的条目在现有导出/编译链路上会被拒（来源映射不接受空条目），因此“下一轮编译按来源撤回”对最后
一份材料不可达；整条版本的撤回另行设计（审核 R6，Owner 裁定）。效果：材料移出该条目的
`materials`（移入 `retired`），追加决定记录 `DETACHED`（`reason` 为上述代码之一，不记人写的文字），之后不再自动重判该材料。
对知识的影响走既有变化判定：下一轮编译时，只由该材料支持的 Claim 按来源撤回处理，仍有其他来源或 `expert_lock` 的 Claim 保留。

## 5. 兼容

- 归属策略版本 `2026-11-01.4`（在 PV-1 的 `.2` 之上；`.3` 新增日期、训练信号、类型词数据，`.4` 为审核 R1–R3、R5 的规则修正）。v1 登记表上结论不变；S5b-7 的
  “同一结论只换策略版本不重新提问”使已问的问题保持原样。
- `confirmation_wording.json` 只新增原因与依据文字，已有原因的文字不变，因此不升版本（同 S11c 先例）。
- 登记表文件：`version_basis`、`shared_versions`、`DETACHED` 只出现在 v2 登记表；v1 登记表在载入与 `record` 时遇到它们直接拒绝
  （与 PV-1 审核 R5 对版本键的规则一致，审核 R7），而不是保存时丢弃。

## 6. 改动范围

`harness/src/insurance_harness/identity/`：`attribution.py`、新 `titles.py`（开头标题读取函数从 `attribution.py` 移出，
行为不变）、新 `training_versions.py`、新 `version_basis.py`、`brands.py`、`confirmation.py`、`material_roles.py`（只新增
`role_signals`，`role_of` 不变）、`attribution_policy.json`；`ingest/`：`registry.py`（`registered()` 传版本数据、`DETACHED`）、
`product_versions.py`、新 `detach.py`、`uploads.py`（`detach` 命令）、`confirmation_questions.py`、`confirmation_wording.json`；
测试；本 Spec 与 S11c Spec 末尾的修订说明。

## 7. 验收（RED）

`tests/identity/test_training_versions.py`、`tests/identity/test_version_confirmation.py`、`tests/ingest/test_version_questions.py`、
`tests/ingest/test_detach.py`，全部用合成材料（公开产品名可用，私有样本文字不进仓库）：
- §2.4 精度与一致性（年/月/日、包含、冲突、非法日期与范围外年份不是信号、被覆盖的粗匹配不重复计数）；
- §2.5–§2.7 每个分支：唯一一致自动归属（机器/机器）、角色未定只问角色、多个、零个、唯一但 `date_conflict`/`period_unknown`、
  跨越换版（`partial`）、信号冲突、类型矛盾（形态、附加、版别）、无日期、多系列、展示上限前计算全集；
- v1 登记表上同一材料结论与现状逐字节相同；条款/说明书/费率表不走方案 A；
- 人工：只能选一致候选；无日期时可选类型不矛盾版本并记 `person`；依据变化 → `CHOICE_STALE`；旧原因问题在 v2 上选产品 →
  `CHOICE_STALE`；只问角色的答复保留机器版本；
- 问题：正文含信号与逐个结论、超过 10 个写“共 N 个”、依据变化 revision 变化；
- detach：v2 移出并记 `DETACHED`、v1 拒绝、未挂材料拒绝、`dry-run` 不写。

## 8. 离线重放（不读线上、零模型）

线上登记表只读副本按 PV-1 迁移为 v2，并模拟登记 2635-1（目录记录 + 正式三材料的条目）；用 6 份 Office 材料已记录的开头
（只报告数量与结论，不报告文字）逐份判定，期望：2024 税优护理险培训材料 → 2635-1 自动归属；百万医疗与分红型终身寿险的
培训材料 → 交人或未挂接（按候选）；综合集训手册 → 不挂接。

## 9. 相对 PV-0 的取舍

- PV-0 §4.3 第 5 条“零候选时附清单中唯一匹配的未登记版本建议”：本片不做。归属核心只经 `VersionIndex` 看目录，建议属于
  PV-2 同步报告的“待接入建议”；问题文字写明“对应版本尚未登记”。
- 类型词表不含渠道与“税优”（§2.6 理由）。
