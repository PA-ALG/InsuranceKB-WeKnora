# PV-4 发布与读取（版本身份进入 Release）

> 状态：Spec（2026-11-01，Claude）。设计依据：[PV-0](PV-0-产品版本与生命周期.md) §3、§5、§9 PV-4 行；
> [附录 A](PV-0-附录A-身份发布同步与迁移.md) §1.2 合同映射、§2 元数据发布路径（含 SK-0 接口修订）、§3.2 销售状态评价。
> 跟踪 Issue #501。实现 Claude，审核 Codex。真实调用 0；**不执行线上全量重发布**（单独 Issue，附录 A §2 纪律）。

## 0. 拆分

PV-4 分两片，按写域与验证方式分开：

| 片 | 范围 | 验证 |
|---|---|---|
| **PV-4a**（本 PR） | 合同（Entity `lifecycle` / `product_family`、Origin `identity_refresh`）；平台按完整目标 Release 校验受限变换；Harness 元数据发布路径（`uploads refresh-identity`）；编译发布路径与版本身份对齐（Claim `product_version_ref`、Entity 身份与销售期） | 离线：合同导出、Go 单元/验收、Harness 单元；零模型调用 |
| **PV-4b**（下一 PR） | 读取侧：页面按 `product_family` 分组与销售状态、版本页前驱/后继、问答的在售过滤 / 同名消歧 / 在保服务路径 | 前端门禁 + 问答回归（按当轮 Issue 的预算） |

PV-4a 合并后页面与问答行为不变（新字段只被写入、不被读取）；PV-4b 只读不写。

## 1. 合同（PV-4a）

### 1.1 Entity

`contracts/knowledge.py` 的 Entity 新增两个**可选**字段，`extra=forbid` 不变：

| 字段 | 形状 | 规则 |
|---|---|---|
| `lifecycle` | `{sale_start, sale_end, source_status, basis_commit, basis_date}`，全部可空 | 日期 `YYYY-MM-DD` 合法日历日；`sale_start < sale_end`（都已知时）；`source_status ∈ {on_sale, discontinued}`；`basis_commit` 40 位小写十六进制 |
| `product_family` | `{key, display_name}`，两者非空 | 由 Harness 按品牌数据规则计算（PV-0 §3.3） |

两个字段为空时**不出现在 payload 中**（序列化省略），所以现有 Entity 成员的 digest 不变，不因合同扩展产生改动。
销售状态不入合同（附录 A §3.2，读取时推出，PV-4b）。

### 1.2 CandidateBundle

`origin` 枚举新增 `identity_refresh`。其余字段不变。

### 1.3 Relation `supersedes`

`kind = "relation"`，`logical_slug = "relation/" + relation_id`，`relation_id = "supersedes/<新版本实体 ID>/<前驱实体 ID>"`
（确定性；两端是内部实体 ID，不含 `/`），`predicate = "supersedes"`，`from` = 新版本，`to` = 前驱，`evidence` 为空。

### 1.4 导出

`uv run python -m insurance_harness.contracts.export` 重新生成 `contracts/*.schema.json`；`--check` 逐字节一致（G9）。

## 2. 平台：受限变换校验（PV-4a，附录 A §2）

### 2.1 受版本约束的实体类型是平台配置

平台不写险种或产品类型的字面量（硬边界 4）。“哪些 `entity_type` 是报备版本实体”由服务配置
`WithVersionedEntityTypes(types...)` 给出；生产装配从环境变量 `ENTERPRISE_VERSIONED_ENTITY_TYPES`（逗号分隔）读取。
**未配置时 `identity_refresh` 一律拒绝**（失败关闭，`CANDIDATE_INVALID`）。部署：线上 App 需配置为 Harness 产品实体的
`entity_type`（目录中为 `insurance_product`），写进下一次部署 Issue。

允许改动的字段只作用于这些类型的实体及其 Claim；其他实体（如 SK-0 的方法实体）及其 Claim 在 `identity_refresh` 中任何
改动都整包拒绝（SK-0 接口修订）。一个实体 ID 若同时被受版本约束类型与其他类型的实体使用，该 ID 不算版本实体（其 Claim
无法区分归属），按“其他实体”处理（#510 审核 R2/R3）。

### 2.2 接收时（结构）

`origin = identity_refresh` 的包：`base_release_id` 非空、`base_epoch` 非空；成员 `kind ∈ {entity, claim, relation}`；
`review_plan` 为空。否则 `CANDIDATE_INVALID`。

### 2.3 激活、审批预检与候选详情时（完整目标 Release）

1. **基线严格**：`base_release_id`/`base_epoch` 必须等于当前 Head；**不适用** S8b 的“未触及成员即可放行”的宽松换基——Head
   已移动即 `NEEDS_REBASE`，由 Harness 按新的 Active 重新计算。
2. 目标 `T` = `materialize(A, bundle)`（先删 `removals`，再叠加成员，与现有激活同一函数）。
3. **成员集合**：`T` 相对 `A` 新增的成员只能是 `predicate = supersedes` 的 Relation；被删的成员只能是 `A` 中
   `predicate = supersedes` 的 Relation。
4. **保留成员投影**：`A` 与 `T` 共有的每个 slug：`kind`、`evidence_refs`、`access_scope` 相同；payload 去掉允许字段后逐字段
   相等。允许字段：
   - 受版本约束类型实体：`identifiers.product_code`、`identifiers.version_key`、`identifiers.filing_no`、`lifecycle`、
     `product_family`；
   - 主体为受版本约束类型实体的 Claim：`product_version_ref`；
   - 其他成员：无（Relation 的任何改动也拒绝）。
   成员 digest 在接收时已按 payload 重算核对。
5. **字段值**：改动后的 `lifecycle`、`product_family` 必须符合 §1.1 的形状；`identifiers` 的值必须是字符串。
6. **引用完整**（Owner 裁定，#510 审核 R3，统一本节与附录 A §1.2/§2 的表述）：对 `T` 中**每一个** Claim 检查，不论本包
   是否改动它：
   - 主体是受版本约束类型实体的 Claim（产品 Claim）：`product_version_ref` 非空时必须等于其 `subject_ref`；为空（`null` 或
     缺省）只容许在**本包未触及**的 Claim 上（迁移期内尚未被任何刷新触及的遗留 Claim）；本包触及（作为成员提交）的每个产品
     Claim 必须以非空且等于 `subject_ref` 的引用结束。因此引用一经建立，`identity_refresh` 永远不能把它清空或省略。
   - 其他 Claim（主体不是受版本约束类型实体，如方法 Claim）：引用必须为空，且不得改动。
   - 新增 `supersedes` 的 `relation_id` 与 slug 等于按两端重算的确定值，两端不同且都是 `T` 中受版本约束类型的实体。
7. **no-op**：新增、删除都为空且提交的每个成员 digest 都等于 `A` 中同 slug 的 digest → 拒绝（“没有改动”）。
   只删除 `supersedes` 的包不是 no-op。

任一不满足 → `CANDIDATE_INVALID`（detail 只给规则与成员位置，不回显 payload）。决定与激活沿用现有
Candidate → Decision → Activate：Decision 为机器决定，`policy_ref = identity_refresh@<元数据提交>`；Head CAS、
（tenant、Space、bundle digest）去重、已提交激活的 replay 回读都不变。

### 2.4 只能由机器整包决定（#510 审核 R1）

生产 Store 同时是 `PointStore`：逐点审核（`ReviewPoints`）把选中的增量直接交给 `Publisher.Activate`，不经过整包激活，
也就不经过 §2.3 的完整目标校验与严格基线。采用的规则：**`identity_refresh` 候选包不参与逐点审核，也不接受任何人工决定**，
唯一能激活它的路径是元数据发布路径的机器整包决定（Decide `mode = machine` → Activate，§2.3 全部检查都在 Activate 内）。

- `ReviewPoints` 对该类候选包的 approve 与 reject 都拒绝，typed error `MACHINE_DECISION_ONLY`（HTTP 409）；
- 整包人工审核 `Review`（approve/reject，包括借已批准的机器决定重新激活）与 `Decide(mode = human)` 同样拒绝；
- 候选详情（逐点与整包两种详情）`blocker = MACHINE_DECISION_ONLY`，逐点详情中每个待定审核点的 `blocker` 相同；
- 人工无法处理这类候选包不会造成堆积：Harness 提交后立即机器决定；中断留下的候选包在重跑时按当时 Active 重新规划，
  相同的包按 bundle digest 去重后再次机器决定。

## 3. Harness（PV-4a）

### 3.1 实体身份与销售期（`ingest/version_metadata.py`，新）

从登记表 v2 条目算出一个实体的元数据（附录 A §1.2）：

| 输出 | 规则 |
|---|---|
| `identifiers.product_code` | `version.plan_code` 已知时写，否则省略 |
| `identifiers.version_key` | 已知时写 |
| `identifiers.filing_no` | 条目恰有一个条款号时写，否则省略（不猜） |
| `lifecycle` | `sale_start`、`sale_end`、`source_status` 至少一个已知时写；`basis_commit` / `basis_date` 取登记表 `metadata_basis` |
| `product_family` | `version.family` |

条目没有版本记录（v1 登记表或未迁移）时沿用旧行为：`identifiers = {"product_code": <实体 ID>}`，无 `lifecycle` 与
`product_family`——迁移前不产生任何改动。

### 3.2 编译发布路径对齐

- `claims_from` 生成的 Claim `product_version_ref = subject_ref`（schema_fields 编译的主体都是产品实体）。变化判定按值与
  引文比较，同值的 Claim 仍判 UNCHANGED，不因补引用而重发。
- `product_page` 接收 §3.1 的元数据；`publish`、`publish_changes`、`judge_batch` 三个入口从登记表取元数据传入。这样元数据
  发布之后，编译发布不会把实体或 Claim 写回旧形状（judge_batch 的 `WOULD_OVERWRITE` 检查也因此保持成立）。

### 3.3 元数据发布路径（`ingest/identity_refresh.py`，新；`uploads refresh-identity`）

- 只接受 v2 登记表（有 `metadata_basis`），否则 `REGISTRY_NOT_V2`；持与其他 `uploads` 子命令相同的文件锁（只读登记表，锁保证
  不与迁移、归属并发）。
- **规划**（纯函数，输入 Active `A` + 登记表 + 受版本约束的产品类型）：
  - **版本实体**：`entity_type` 属于受版本约束的产品类型、ID 是登记条目、且该 ID 没有被其他类型实体共用的实体（#510 审核 R2）。
    产品类型取自 SchemaPack 目录各 pack 的 `entity_type`（事实链路编译产品实体用的就是它，目录中为 `insurance_product`；
    `--catalog` 默认仓库内目录），与平台的 `ENTERPRISE_VERSIONED_ENTITY_TYPES` 对应；同 ID 的 `sales_method` 等其他类型实体
    永远不进计划；
  - 版本实体：按 §3.1 更新 `identifiers` / `lifecycle` / `product_family`（在原 payload 上按键改动，其余键原样）；
  - 主体是版本实体的 Claim：`product_version_ref = subject_ref`（原 payload 上改一个键）；
  - `supersedes`：只管理**两端都是版本实体**的关系——登记条目的 `predecessor` 两端都是版本实体时生成关系；`A` 中两端都是
    版本实体、但不再成立的 `supersedes` 列入删除；一端不是版本实体（未登记、不在 `A` 中或其他类型）的关系一律不动；
  - 不碰任何其他成员（非登记实体、其他类型实体、它们的 Claim 与关系、页面、导航、概念、wiki 页、方法知识）。
  - 新 digest 等于原 digest 的成员不提交。全部为空 → no-op。
- **分包**：每包不超过平台大小上限；同一产品的实体与 Claim 尽量同包，超限时 Claim 分到后续包；关系与删除随“新版本”所在的包。
- **执行**：默认只规划（dry-run，输出各类计数与包数）；`--live` 才提交。每一包：按**当时**的 Active 重新规划，取第一包
  → submit → machine Decide（`policy_ref = identity_refresh@<commit>`）→ Activate → 读回核对 digest；循环到 no-op 或达到
  `--max-bundles` 上限。`NEEDS_REBASE` 等平台错误立即停止并报告错误码，重跑按当时 Active 重新计算，不依赖本地回执。
- 输出只含计数、slug 数量、Release ID 与错误码，不输出 payload。

### 3.4 首次全量重发布

不在本片执行。单独开 Issue：部署 PV-4a（含 `ENTERPRISE_VERSIONED_ENTITY_TYPES`）→ 线上登记表迁移到 v2 → 前后核对 Active
epoch 与成员数 → `uploads refresh-identity --live`，不与编译轮次重叠。

## 4. 读取侧（PV-4b，下一 PR）

按 PV-0 §5.3、§5.4 与附录 A §3.2：页面按 `product_family` 分组、销售状态四态（评价日为 Space 业务时区日历日；首期 Space
业务时区固定为 `Asia/Shanghai`，平台常量，Space 级配置留作后续）、版本页前驱/后继、问答的在售过滤与同名消歧、在保服务按
投保日期选版本。PV-4b 开工时补 RED。

## 5. 验收（PV-4a）

- **合同**：`lifecycle`/`product_family` 为空时 Entity payload 与旧版逐字节相同；非法日期、`start ≥ end`、错误状态、空的
  系列字段被拒；Origin 含 `identity_refresh`；`contracts/` 导出 `--check` 一致。
- **平台**（Go，真实 `candidate_bundle.schema.json`）：合法刷新（实体补身份与销售期、Claim 补引用、新增与删除 `supersedes`）
  通过并激活；以下各被整包拒绝：新增或删除 Claim/实体、改 Claim 的值或证据、改 `evidence_refs`/`access_scope`/`kind`、
  `product_version_ref ≠ subject_ref`、引用指向非版本类型或不存在的实体、非版本类型实体改允许字段、`lifecycle` 非法、新增非
  `supersedes` 关系、`relation_id` 不确定、删除非 `supersedes` 成员、改已有关系、`base` 为空、Head 已移动（`NEEDS_REBASE`，
  不走宽松换基）、no-op、未配置版本类型；只删除关系的包通过。R3：清空或省略已建立的引用、本包触及的产品 Claim 引用为空、
  未触及的产品 Claim 引用错误、非版本 Claim 带引用、版本 ID 与其他类型实体共用，各被整包拒绝；未触及的遗留空引用可保留。
  R1（测试替身实现 `PointStore` 与 `QueueStore`）：逐点 approve/reject、整包人工 Review、人工 Decide 都返回
  `MACHINE_DECISION_ONLY`，详情与每个待定审核点 `blocker` 相同；Head 移动后机器整包路径 `NEEDS_REBASE`；对照：同一替身能
  逐点发布编译包。
- **Harness**：v1 条目元数据与旧行为一致；v2 条目的标识、销售期与系列；规划只改登记实体及其 Claim、不碰其他成员；关系增删
  只限两端都是版本实体（一端未登记的关系不动）；同 ID 的其他类型实体及其 Claim 不进计划、类型共用的 ID 不算版本；
  no-op；只删关系不是 no-op；分包不超限且同产品优先同包；`--live` 循环按每次的 Active 重新规划、遇平台错误停止；
  `claims_from` 带引用；三个编译发布入口传入元数据。
- 门禁：Go build/vet/受影响包测试、golangci-lint（new-from-rev）、Harness pytest/ruff/mypy、合同导出 `--check`、
  `tests/architecture`、手写文件 ≤ 500 行、`git diff --check`。
