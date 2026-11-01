# PV-0 附录 A：身份映射、元数据发布、主数据同步与登记表迁移

> 主文档：[PV-0 产品版本与生命周期](PV-0-产品版本与生命周期.md)。本附录给出 PV-1、PV-2、PV-4 必须共同遵守的细则
> （Codex 设计审核 R1、R2、R5、R6）。只写设计，不改代码。

## 1. 身份映射（PV-1 与 PV-4 共用，R1）

### 1.1 三种标识

| 标识 | 形式 | 用途 | 规则 |
|---|---|---|---|
| 内部实体 ID（`product_id` = `entity_id`） | 种子条目为 planCode（如 `2650`）；新建条目为 `sc-` + 条款号摘要 | 登记表键、Release 实体、slug `entity/<id>`、Claim `subject_ref` 与 `logical_key` 前缀 | 现有规则不变、确定性；一经发布永不改写 |
| 外部版本键 `version_key` | `planCode-versionNo`（如 `2635-1`） | 与平安仓库对账、展示、同步 | 可空；非空时在登记表内唯一 |
| 条款号 `clause_codes` | 条款报备号 | 内容锚点 | 正文确认，不被清单覆盖 |

### 1.2 合同映射（PV-4 实施）

- **Entity**：每个登记条目发布一个实体，`entity_type` 保持 `product`（读者、导航与 S3d 页面都按它工作）；一个 `product`
  实体就是一个报备版本。本设计不使用 `product_version` 类型，也不新增按编码汇总的实体。
- `identifiers`：`product_code` 改为真实 planCode（今天 `page.py` 写入内部 ID，`sc-` 条目会得到伪编码）——已知时写，
  未知时**省略**；新增 `version_key`（已知时）；`filing_no` = 条款号。
- 销售期等属性：Entity 合同（`contracts/knowledge.py`，`extra=forbid`）新增可选对象 `lifecycle{sale_start, sale_end,
  source_status, basis_commit, basis_date}`；按 Harness pydantic → `contracts/*.schema.json` 导出，Go 校验结构与不变量
  （`sale_start < sale_end`、日期格式），前端按 schema 生成类型。销售状态不入合同，由读取侧按评价日推出（§3.2）。
- 分组数据：Entity 新增可选对象 `product_family{key, display_name}`，由 Harness 按品牌数据规则（主文档 §3.3）计算后随实体
  发布；产品库页面只从 Release 中的实体读取它分组，**前端不读 Harness 登记表，也不另写品牌规则**。它只能经 §2 的元数据发布
  路径更新（属于允许改动的字段），缺失时页面把该版本放在“未分组”。
- **Claim**：`product_version_ref` = 同一 `subject_ref`（内部实体 ID）。该实体必须是同一 Release 的成员，否则组包失败关闭
  （typed error），不发布空或悬空引用。
- **Relation `supersedes`**：`from` = 新版本实体 ID，`to` = 前驱实体 ID；两端都必须是同一 Release 的成员，否则不发布该
  关系（报告）。`relation_id` 由两端 ID 确定性生成。
- 不可解析的情况（外部键为空、前驱不唯一、前驱未登记）只影响对应可选属性或关系，不阻断实体与 Claim 的发布。

### 1.3 去重：两个标识组合一致才认定，否则失败关闭

新材料（或迁移、同步中的一条清单记录）带外部版本键 `K`（已知时）与条款号 `C`。在登记表中分别查找：`X` = `version_key` 为 `K`
的条目，`Y` = `clause_codes` 含 `C` 的条目集合；`n(C)` = `C` 在登记表 `metadata_basis` 固定的清单提交中对应的版本数（清单中
没有 `C` 时为 0；尚未固定清单的登记表没有任何 `version_key`，沿用现有规则）。**按下列顺序判定，命中即停**：

| 顺序 | 条件 | 结论 |
|---|---|---|
| 1 | `X` 存在，且 `Y` 为空或只含 `X` | 认定为 `X`（补充或重复） |
| 2 | `X` 存在，`Y` 含 `X` 以外的条目 | 冲突：归属记 `QUARANTINE / anchor_conflict`；迁移、同步拒绝写入并报告 |
| 3 | `X` 不存在，且 `n(C) > 1`（共用条款号），**不论 `Y` 是否为空、`K` 是否已知** | 不能认定：隔离并报告，不并入、不新建——新建条目的内部 ID 由条款号决定，无法区分共用该号的版本；`K` 未知不能用来绕过这一歧义 |
| 4 | `X` 不存在，`n(C) ≤ 1`，`Y` 含多个条目 | 冲突，隔离并报告 |
| 5 | `X` 不存在，`n(C) ≤ 1`，`Y` 恰好一个 | 认定为 `Y`；该条目 `version_key` 为空时由迁移或同步补 `K`，非空且不等于 `K` 时按冲突处理 |
| 6 | `X` 不存在，`n(C) ≤ 1`，`Y` 为空 | 走现有新建规则（条款与标题锚点），新条目写入 `K`（已知时） |

例：清单中 `C` 对应 `K1`、`K2` 两个版本，两者都未登记、材料不带版本键——按第 3 行隔离并报告，不会新建 `sc-` + 摘要（`C`）。
共用条款号版本的接入，要等内部 ID 规则能区分版本时另行设计。

任何情况下都不合并两个已有条目；两个条目映射到同一 `version_key` 时迁移与同步拒绝写入，由人工处理。种子条目（ID = planCode，
如 `2650`）迁移后补 `version_key`（如 `2650-1`），之后同一版本的材料按上表命中种子条目，不会以 `sc-` ID 再登记一次。

### 1.4 唯一前驱规则

新版本 `v` 的前驱 `p` 必须同时满足：同一 `plan_code`；`p.sale_end` 已知且等于 `v.sale_start`；登记表中满足前两条的版本
恰好一个。否则（编码未知、销售期未知、多个候选、同名或共用条款号的并行版本、同起售日的多个版本）不建 `predecessor`，
只在报告中列出。不按名称或日期排序推断前驱。

## 2. 元数据发布路径（PV-4，R2）

现有事实链路不会自然带出版本属性：`changes/decision.py` 对同值同引文判 UNCHANGED，`publish_changes.py` 在没有 Claim 变化时
直接结束，且对 Active 已有的实体不重发；`ingest/publication.py` 依据既有输出与回执可能判为无需发布。因此身份补齐与元数据
更新走一条**独立的元数据发布路径**，与事实 delta 分开：

- **输入**：当前 Active Release `A`（候选包必须带非空的 `base_release_id` 与 `base_epoch`，指向 `A`）+ 登记表 v2 的身份、销售期
  与分组 + 固定的元数据提交。
- **候选包**：CandidateBundle 的 `origin` 枚举新增 `identity_refresh`（合同改动），其余字段与现有协议相同。
- **平台按完整目标 Release 校验**（不只看提交的成员，也不因 origin 标记而信任提交者）：平台按现有 `release/publish.go`
  `materialize` 得到目标 `T` = `A` 先删除 `removals`、再叠加提交成员，然后逐项检查，任一不满足即拒绝整包（typed error）：
  1. **成员集合**：`T` 相对 `A` 新增的成员只能是谓词为 `supersedes` 的 Relation；被删除的成员只能是 `A` 中谓词为 `supersedes`
     的 Relation（`removals` 只能列这类 slug）。不得增删 Claim、Entity 或其他任何成员。
  2. **保留成员的完整投影**：`A` 与 `T` 共有的每个 slug，成员的 kind、slug、`evidence_refs`、`access_scope` 不变；payload 去掉
     允许字段后逐字段相等；允许字段只有 Claim 的 `product_version_ref`，Entity 的 `identifiers.product_code`、
     `identifiers.version_key`、`identifiers.filing_no`、`lifecycle`、`product_family`。`member_digest` 由平台按新 payload 重算并
     核对。Claim 的 value、state、unit、applicability、effective_*、evidence、provenance、origin、expert_lock、
     unknown_reason、review（含 mode 与分数）、maintenance 因此全部原样保留。
  3. **引用完整**：`product_version_ref` 必须等于该 Claim 的 `subject_ref`，并指向 `T` 中的 Entity；新增 `supersedes` 的两端
     都是 `T` 中的 Entity，`relation_id` 等于平台按两端 ID 重算的确定值。
- **激活**：沿用现有 Candidate → Decision → Activate，不新增协议：Decision 记为机器决定，策略引用写明 `identity_refresh` 与元数据
  提交，不生成新的审核项；激活照旧做 Head CAS（Head 已移动 → `NEEDS_REBASE`，按新的 Active 重新计算），候选按
  （tenant、Space、bundle digest）去重，已提交的激活按现有 replay 回读。历史 Release 中的审核决定不改动；保留成员的审核信息
  就在其 payload 中，原样进入新 Release。
- **幂等与 no-op**：Harness 先在本地算出 `T`；当新增集合、删除集合都为空，且每个保留成员的 payload 与 `A` 相同，才判定为 no-op
  （只删除 `supersedes` 的候选包提交成员为空，但删除集合非空，不是 no-op）。中断后重跑按当时的 Active 重新计算，不依赖本地回执。
- **Entity 单独变化**：同步只改了销售期或分组时，同一路径只发布变化的 Entity 成员，不需要 Claim 变化。
- **不改变的语义**：同一版本内的权威替代、材料撤回、专家锁优先级仍由事实链路按 `decision.py` 判定；跨版本是“并存”；
  全过程只推进同一个 Space Head。
- **纪律**：首次全量重发布（所有产品事实 Claim 补 `product_version_ref`，这些成员的 digest 全变）单独开 Issue，执行前后核对
  Active epoch 与成员数，不与编译轮次重叠；之后的元数据发布同样不与编译轮次重叠。
- **适用范围（SK-0 接口修订，2026-11-01）**：本节“Claim 补 `product_version_ref` = `subject_ref`”只适用于 **subject 为 `product`
  实体的 Claim**。非版本知识（SK-0 的 `sales_method` 实体及其 Claim，`product_version_ref` 为空）不属于允许改动的字段范围：
  `identity_refresh` 从不为它们补版本引用，也不改动它们；它们按“保留成员的完整投影”校验，任何改动整包拒绝。

## 3. 主数据同步规则（PV-2，R5）

### 3.1 字段处理

| 清单变化 | 处理 |
|---|---|
| `endDate` 新出现或变化；`startDate` 原为空 | 自动更新登记表（机器、记录前后值与提交），随下一次元数据发布进入 Release |
| `planCode`、`versionNo` 原为空且条款号唯一匹配 | 自动补齐，并做 §1.3 去重检查 |
| 名称、条款号、险种 | **只报告**，等待内容回验；不覆盖正文确认的 `names` / `clause_codes` / `schema_pack_id` |
| 新版本（登记表中没有） | 只生成待接入建议 |
| 已登记版本在清单中消失 | 只报告；不改状态、不删知识 |

来源固定为仓库的一个提交（CLI 必填），提交 SHA 与同步时间写入报告与 `metadata_basis`。

### 3.2 销售状态的评价

- 评价日：读取时的 Space 业务时区日历日（蓝图 §5.1“两种时间”的同一时区约定）；问答的“投保日期”按同一时区解释。
- `not_yet_on_sale`：`sale_start` 已知且评价日 < `sale_start`；
- `discontinued`：`sale_end` 已知且评价日 ≥ `sale_end`；
- `on_sale`：`sale_start` 已知且 ≤ 评价日，且 `sale_end` 未知时来源状态（固定提交时的“在售/停售”）为在售——显示为“在售
  （据 YYYY-MM-DD 数据）”；
- `unknown`：其余情况（未匹配、日期缺失、来源状态与日期矛盾）。**`sale_end` 为空本身不推出在售**。
- 停售元数据只随元数据发布进入对应 Release 快照；`sale_end` 不写入 Claim `effective_to`，不视为来源撤回。

## 4. 登记表 v1 → v2 迁移（PV-1，R6）

- **只读入口保持纯读**：`load_registry` 能读 v1 与 v2；读到 v1 时在内存中按 v2 模型构造（版本字段为空），**从不写文件**。
  发布 dry-run 等经 `changes.options.registry_inputs` 的只读调用行为不变，不持锁、不迁移。
- **写入口**：单独的迁移命令（如 `uploads migrate-registry --manifest-commit <sha>`；`--refresh` 对已是 v2 的文件只重算版本
  字段），持与 `uploads run/confirm` 相同的文件锁。首次迁移（v1 → v2）与刷新（v2 → v2）使用同一套步骤与**操作日志**：
  1. 校验目标：首次迁移要求合法 v1，刷新要求合法 v2；存在未关闭的操作日志 → 先按下面的恢复规则处理；都不满足 → 拒绝，不改任何文件；
  2. 写备份（带时间戳的新文件，永不覆盖已有备份，命令也从不删除备份），fsync；
  3. 生成新内容到同目录临时文件并 fsync；
  4. **替换前写操作日志并 fsync**（与登记表同目录，固定文件名）：操作编号、类型（migrate / refresh）、目标的旧完整内容摘要
     （整个文件字节的 sha256）、预期新完整内容摘要（临时文件字节的 sha256）、备份路径与摘要、清单提交、开始时间；
  5. **原子替换 = 提交点**。替换之前的任何失败：目标仍是旧内容，删除临时文件，关闭日志为“未执行”，保留备份；
  6. 替换之后读回：目标摘要等于预期新摘要，且新内容通过 v2 校验（首次迁移另核 v1 投影与备份逐项相等）→ 写迁移记录并关闭日志。
     读回失败或进程中断时日志保持未关闭，结果视为**已提交但未确认**。
- **恢复**（任何一次运行，同一把锁下，发现未关闭的操作日志时先执行）：计算目标当前完整内容摘要——
  - 等于日志中的预期新摘要 → 已提交：补做第 6 步的校验，写迁移记录并关闭日志，**不重做**；
  - 等于日志中的旧摘要，且备份文件摘要等于日志中的备份摘要 → 未提交：关闭日志为“未执行”，可从第 1 步重新开始（新日志、新备份）；
  - 其他（摘要都不符、备份缺失或不符、目标损坏）→ 停止并报告，由人用备份恢复，命令不自动写任何文件。
  判定只依据本次操作日志记录的摘要，因此刷新（v1 投影前后相同）也不会把替换前中断误判为已提交。没有未关闭日志时，对已确认的
  v2 运行首次迁移 = no-op。
- **保留**：products、materials、retired、pending（含未完成的 Settlement）、decisions（含 ConfirmationRef）、全部 ID 与发布 slug
  原样保留。校验：v2 投影回 v1 字段后与原件逐项相等。
- **匹配**：按条款号到固定提交的清单匹配；0 个匹配 → 版本字段为空、状态 `unknown`；多个匹配（共用条款号）→ 版本字段为空并
  标记 `version_ambiguous`；两个条目映射到同一 `version_key` → 拒绝迁移并报告。
- **不完整版本**：v2 校验允许版本字段为空，但 `version_key` 非空时必须唯一、销售期非空时必须 `start < end`。不完整版本：
  不能作为方案 A 的自动归属目标（只能经内容锚点或人工）；照常编译与发布事实，元数据发布时省略缺失属性。
- **`retired`**：迁移前检查并在报告中列出非空的 `retired`；v2 格式继续支持该字段，旧数据不拆分。
- **来源可重放**：迁移、同步与主文档 §1 的统计都固定来源提交（§1 使用 `cd93dfcfd59b981fd532dc323c043e16c026ad9c`）。
