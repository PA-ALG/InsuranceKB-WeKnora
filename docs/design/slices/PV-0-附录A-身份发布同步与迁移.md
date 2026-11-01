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

- **Entity**：每个登记条目发布一个实体，`entity_type` 保持 `product`（读者、导航与 S3d 页面都按它工作）。在我们的模型里
  一个 `product` 实体就是一个报备版本；蓝图的 `product_version` 类型保留给“一个实体承载多个版本”的场景，本设计不使用，
  不新增按编码汇总的实体。
- `identifiers`：`product_code` 改为真实 planCode（今天 `page.py` 写入内部 ID，`sc-` 条目会得到伪编码）——已知时写，
  未知时**省略**；新增 `version_key`（已知时）；`filing_no` = 条款号。
- 销售期等属性：Entity 合同（`contracts/knowledge.py`，`extra=forbid`）新增可选对象 `lifecycle{sale_start, sale_end,
  source_status, basis_commit, basis_date}`；按 Harness pydantic → `contracts/*.schema.json` 导出，Go 校验结构与不变量
  （`sale_start < sale_end`、日期格式），前端按 schema 生成类型。销售状态不入合同，由读取侧按评价日推出（§3.2）。
- **Claim**：`product_version_ref` = 同一 `subject_ref`（内部实体 ID）。该实体必须是同一 Release 的成员，否则组包失败关闭
  （typed error），不发布空或悬空引用。
- **Relation `supersedes`**：`from` = 新版本实体 ID，`to` = 前驱实体 ID；两端都必须是同一 Release 的成员，否则不发布该
  关系（报告）。`relation_id` 由两端 ID 确定性生成。
- 不可解析的情况（外部键为空、前驱不唯一、前驱未登记）只影响对应可选属性或关系，不阻断实体与 Claim 的发布。

### 1.3 去重：同一外部版本不得登记两次

- 新建条目前，先按 `version_key`（已知时）与条款号在登记表中查找；命中已有条目 → 该材料属于已有条目（补充或重复），
  不新建。
- 迁移与同步时，两个条目映射到同一 `version_key` → 拒绝写入并报告（人工合并），不自动选择。
- 种子条目（ID = planCode，如 `2650`）迁移后补 `version_key`（如 `2650-1`）；之后同一版本的材料再到达时按 `version_key`
  与条款号命中种子条目，不会以 `sc-` ID 再登记一次。

### 1.4 唯一前驱规则

新版本 `v` 的前驱 `p` 必须同时满足：同一 `plan_code`；`p.sale_end` 已知且等于 `v.sale_start`；登记表中满足前两条的版本
恰好一个。否则（编码未知、销售期未知、多个候选、同名或共用条款号的并行版本、同起售日的多个版本）不建 `predecessor`，
只在报告中列出。不按名称或日期排序推断前驱。

## 2. 元数据发布路径（PV-4，R2）

现有事实链路不会自然带出版本属性：`changes/decision.py` 对同值同引文判 UNCHANGED，`publish_changes.py` 在没有 Claim 变化时
直接结束，且对 Active 已有的实体不重发；`ingest/publication.py` 依据既有输出与回执可能判为无需发布。因此身份补齐与元数据
更新走一条**独立的元数据发布路径**，与事实 delta 分开：

- **输入**：当前 Active Release 的成员（固定 `release_id` 与 epoch）+ 登记表 v2 的身份与销售期 + 固定的元数据提交。
- **允许改动的字段**：Claim 的 `product_version_ref`；Entity 的 `identifiers`（`product_code`、`version_key`、`filing_no`）与
  `lifecycle`；`supersedes` Relation 的增删。**其余一律原样保留**：Claim 的 value、state、unit、applicability、effective_*、
  evidence、provenance、origin、expert_lock、unknown_reason、review（含 mode 与分数）、maintenance（revision_no、changed_at、
  changed_by、first/last release）；成员与审核记录的关联不变。
- **候选包**：CandidateBundle 新增 `origin = identity_refresh`（合同改动）。平台不变量：此类候选包的每个成员与 Active 中同 slug
  成员相比，只能在上述允许字段上不同，否则整包拒绝（失败关闭）；不产生新的审核项，审核方式与分数沿用。
- **幂等**：重跑时若算出的成员 digest 全部等于 Active，则不提交候选包（no-op）；中断后重跑按 Active 重新计算，不依赖本地回执。
- **Entity 单独变化**：同步只改了销售期时，同一路径只发布变化的 Entity 成员，不需要 Claim 变化。
- **不改变的语义**：同一版本内的权威替代、材料撤回、专家锁优先级仍由事实链路按 `decision.py` 判定；跨版本是“并存”；
  全过程只推进同一个 Space Head。
- **纪律**：首次全量重发布（所有 Claim 补 `product_version_ref`，成员 digest 全变）单独开 Issue，执行前后核对 Active epoch 与
  成员数，不与编译轮次重叠；之后的元数据发布同样不与编译轮次重叠。

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
- **写入口**：单独的迁移命令（如 `uploads migrate-registry --manifest-commit <sha>`），持与 `uploads run/confirm` 相同的文件锁；
  步骤：校验输入为合法 v1（否则拒绝，不改原件）→ 写带时间戳的备份 → 生成 v2 到同目录临时文件并 fsync → 原子替换 → 重新读回
  校验。任何一步失败，原件不变；中断后重跑从原件重新开始。对已是 v2 的文件运行 = no-op（可用 `--refresh` 只重算版本字段）。
- **保留**：products、materials、retired、pending（含未完成的 Settlement）、decisions（含 ConfirmationRef）、全部 ID 与发布 slug
  原样保留。校验：v2 投影回 v1 字段后与原件逐项相等。
- **匹配**：按条款号到固定提交的清单匹配；0 个匹配 → 版本字段为空、状态 `unknown`；多个匹配（共用条款号）→ 版本字段为空并
  标记 `version_ambiguous`；两个条目映射到同一 `version_key` → 拒绝迁移并报告。
- **不完整版本**：v2 校验允许版本字段为空，但 `version_key` 非空时必须唯一、销售期非空时必须 `start < end`。不完整版本：
  不能作为方案 A 的自动归属目标（只能经内容锚点或人工）；照常编译与发布事实，元数据发布时省略缺失属性。
- **`retired`**：迁移前检查并在报告中列出非空的 `retired`；v2 格式继续支持该字段，旧数据不拆分。
- **来源可重放**：迁移、同步与主文档 §1 的统计都固定来源提交（§1 使用 `cd93dfcfd59b981fd532dc323c043e16c026ad9c`）。
