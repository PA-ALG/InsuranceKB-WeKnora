# PV-1 登记表 v2、版本迁移与新版本不替换

> 状态：Spec（2026-11-01，Claude）。设计依据：[PV-0](PV-0-产品版本与生命周期.md) §3.1、§4.2、§6、§9 PV-1 行，
> [附录 A](PV-0-附录A-身份发布同步与迁移.md) §1.1、§1.3、§1.4、§4。跟踪 Issue #501。实现 Claude，审核 Codex。
> 真实调用 0；不部署；不迁移线上登记表（线上迁移在批次一阶段 B 结束后作为单独一步执行，另记）。

## 1. 目标与不做

做：登记表能记录每个条目对应的**报备版本**（外部键 `planCode-versionNo`、销售期、来源状态、品牌系列、唯一前驱）；
只读入口纯读；单独的、有锁、有备份、带操作日志的迁移与刷新命令；归属按附录 A §1.3 的顺序组合匹配去重；
**新版本不再替换旧版本**（修订 S5b-1 §2.3 第 5 步与 §3.7）。

不做（后续切片）：主数据同步（PV-2）；方案 A、培训材料日期信号、人工入口约束（PV-3）；合同、发布、Go 读取、页面、问答
（PV-4）。编译、取值协议、字段卡、发布、证据、评分、材料角色数据与 `contracts/` **一律不改**，编译器身份不变。

## 2. 数据

### 2.1 版本目录（`ingest/version_catalog.py`，新）

从固定提交的平安产品仓库检出读出 `在售/*/product_meta.json` 与 `停售/*/product_meta.json`（只读、限大小、不可信输入），
每个文件夹一条 `VersionRecord`：

| 字段 | 来源 | 规则 |
|---|---|---|
| `version_key` | `versionNo` | 形如 `<actualPlanCode>-<n>`，必须以 `actualPlanCode-` 开头；全目录唯一，否则拒绝整个目录 |
| `plan_code` / `version_no` | `actualPlanCode` / `versionNo` 末段 | |
| `name` | `clauseName` | 非空 |
| `clause_code` | `sccode` | 规范化（§2.2）后匹配归属策略的条款号模式才保留，否则空（缺失、“无”、格式坏） |
| `sale_start` / `sale_end` | `startDate` / `endDate` | `YYYY-MM-DD` 合法日期才保留；`start < end` |
| `source_status` | `planSalesStatus` | 在售 → `on_sale`，停售 → `discontinued`，其他 → 空 |
| `channel` / `plan_type` | `planSalesChannel` / `planPlanType` | 原文 |

检出提交必须等于命令给出的 `--manifest-commit`（`git rev-parse HEAD`，40 位）。目录落盘为登记表同目录的
`<登记表名>.catalog-<sha256 前 12 位>.json`（合同 `product-catalog.v1`，内容寻址，写后不改、不删）；登记表
`metadata_basis` 记仓库名、提交、目录文件名与其 sha256、同步时间。`uploads run` 读 v2 登记表时按 `metadata_basis` 读回目录并
核对 sha256，不符或缺失即 `CATALOG_INVALID` 失败关闭；v1 登记表不读目录，归属沿用现有规则。

### 2.2 条款号规范化

NFKC、去空白，`[` / `]` 改为 `〔` / `〕`，再按归属策略 `clause_code_pattern` 全匹配（与正文抽出的编号同一形式）。登记表
`clause_codes` 比较前做同样规范化；**登记表里的值不改写**（正文确认的值）。

### 2.3 登记表 v2（`ingest/registry.py`、`ingest/product_versions.py`，新）

- `contract`: `product-registry.v1` | `product-registry.v2`。`load_registry` 原样读两种，**从不写文件**；保存时按读入的合同写回：
  v1 读入的登记表照旧写 v1（因此 `uploads run/confirm` 不会悄悄迁移）。
- `ProductEntry.version: ProductVersion | None`（v1 必须全为空；v2 由迁移/归属填写）：
  `version_key`、`plan_code`、`version_no`、`sale_start`、`sale_end`、`source_status`、`channel`、`plan_type`、`year_tag`、
  `family{key, display_name}`、`predecessor`、`version_ambiguous`（布尔）。
- `ProductRegistry.metadata_basis: MetadataBasis | None`：v1 必须为空，v2 必须有。
- 校验：非空 `version_key` 在登记表内唯一；`sale_start < sale_end`（都有时）；`predecessor` 指向另一个已登记条目。
- `family`：由归属策略的品牌规则（S11c 品牌核心：去前缀、去括号限定、去最长险种后缀）从规范名称派生；`year_tag`：名称中
  `product_year_patterns` 唯一命中的年份。两者都是派生数据，只用于分组与候选（PV-3/PV-4），从不作归属锚点。
- 唯一前驱（附录 A §1.4）：同 `plan_code`、`p.sale_end == v.sale_start`、满足这两条的条目恰好一个；否则为空。每次新增条目、
  迁移、刷新后对全部条目确定性重算。

## 3. 归属（`identity/attribution.py`、`identity/versions.py`，新）

`attribute(..., catalog=None)` 新增可选版本索引（条款号 → 版本键列表）。只有 v2 登记表的 `uploads run` 传入；人工确认路径
（`confirm`）本片不传（PV-3 接入人工约束）。`RegisteredProduct` 增加 `version_key`。

有编号 `C`（自有或引用）且传入索引时，按附录 A §1.3 顺序判定，命中即停（`K` = 索引中 `C` 唯一对应的版本键，否则空）：

| 顺序 | 条件 | 结论 |
|---|---|---|
| 1 | 存在 `version_key == K` 的条目 `X`，编号命中的条目为空或只有 `X` | 认定为 `X`（`C` 不在 `X` 编号里时不判新版本） |
| 2 | `X` 存在，编号还命中其他条目 | `QUARANTINE / anchor_conflict` |
| 3 | `X` 不存在，`n(C) > 1` | `QUARANTINE / shared_clause_code`（不论编号是否命中条目、`K` 是否已知；不新建） |
| 4 | `n(C) ≤ 1`，编号命中多个条目 | `QUARANTINE / anchor_conflict`（现有规则） |
| 5 | `n(C) ≤ 1`，编号命中恰好一个 `Y` | 认定为 `Y`；`Y.version_key` 非空且 `K` 已知而不等 → `anchor_conflict` |
| 6 | `n(C) ≤ 1`，编号没有命中 | 现有规则（标题、新建、品牌候选）；新建条目带 `K` |

**新版本**（修订 S5b-1）：条款有自有编号、名称命中已登记产品 `P`、编号不在 `P` 中 → `NEW_VERSION / new_clause_code`，但
`product_id` 是**新条目**（与 `CREATE` 同规则：`sc-` + 自有编号摘要），`display_name` 与 `schema_pack_id` 取 `P`，
`candidates = (P,)` 记同名的已登记版本，`version_key = K`，`replaces` 为空。新 ID 已存在 → `anchor_conflict`。登记表新建该条目，
`P` 的材料与已发布知识**原样保留**；之后同名的说明书、费率表若两版本都命中名称，按现有规则 `NEEDS_CONFIRM /
multiple_products` 交人（PV-3 再加日期信号）。人工确认把条款归到 `P` 时，结论同样是新条目，`confirm` 以 `candidates` 核对
所选产品；保存的 `NEW_VERSION` 结论在新 ID 尚未登记时仍可执行。同一版本内的权威替代（人工 `REPLACE`）与材料撤回不变。

## 4. 迁移命令（`ingest/registry_migration.py`，新；`uploads migrate-registry`）

```
python -m insurance_harness.ingest.uploads migrate-registry --registry PATH \
    --manifest-dir DIR --manifest-commit SHA [--refresh] [--dry-run]
```

不需要平台地址与密钥；持与 `seed/run/confirm/publish` 相同的锁文件。

1. 发现未关闭的操作日志 `<登记表名>.migration-journal.json` → 先恢复（第 6 条）。
2. 校验目标：首次迁移要求 v1（已是 v2 → no-op 报告）；`--refresh` 要求 v2。
3. 生成新内容（纯计算）：按规范化条款号到目录匹配——0 个版本 → 版本字段空；恰好一个且 `n(C) = 1` → 填全部字段；共用条款号
   或条目的多个编号指向不同版本 → `version_ambiguous`，字段空；两个条目落到同一 `version_key` → 拒绝（`MIGRATION_VERSION_DUPLICATE`，
   不写任何文件）。名称与目录不一致只报告，不改 `names`。`retired` 非空的条目在报告中列出，格式继续支持。刷新时只重算版本
   字段，其他内容必须逐项不变。新内容与当前相同 → no-op。`--dry-run` 到此为止，只出报告。
4. 写备份 `<登记表名>.backup-<UTC 时间>-<操作编号>.json`（独占创建，永不覆盖、命令从不删除）并 fsync；写目录文件（内容寻址，
   已存在则核对 sha256）；写同目录临时文件并 fsync。
5. **替换前**独占写操作日志并 fsync：操作编号、类型、旧/预期新完整内容 sha256、备份文件名与 sha256、临时文件名、清单提交、
   开始时间。然后原子替换（提交点）并 fsync 目录。替换前的普通异常：删临时文件、日志按“未执行”关闭、保留备份；进程被中断
   （非 `Exception`）时日志保持未关闭，留给恢复。替换后读回：摘要等于预期新摘要、v2 合法、（首次迁移）v1 投影与备份逐项
   相等 → 追加迁移记录到 `<登记表名>.migrations.jsonl`（fsync）并删除日志；读回失败时日志保持未关闭（已提交但未确认）。
6. 恢复（同一把锁下，只依据日志摘要）：目标 = 预期新 → 补做第 5 步读回校验、记“已提交”、关闭，不重做；目标 = 旧且备份摘要
   相符 → 记“未执行”、删日志记下的临时文件、关闭，再从第 2 步开始；其他 → `MIGRATION_RECOVERY_UNSAFE`，不写任何文件。
   刷新的 v1 投影前后相同，判定从不使用投影。

报告（JSON，不含材料正文与路径）：每个条目 `matched / unmatched / ambiguous`、版本键、前驱、名称差异、`retired` 非空的条目、
no-op / 已恢复 / 已提交。

## 5. 验收（RED，单独提交）

- `tests/ingest/test_registry_version_fields.py`：v1/v2 合同与字段约束（v1 不得有版本字段；v2 必须有依据；版本键唯一；日期顺序；前驱存在）；
  `load_registry` 与 `changes.options.registry_inputs`（发布 dry-run 路径）对 v1、v2 都不写文件、不建锁/日志；v1 读入后
  `uploads run` 保存仍为 v1；`uploads run` 对 v2 读回目录并核对摘要，目录缺失或被改 → `CATALOG_INVALID`。
- `tests/ingest/test_registry_migration.py`：含 retired、pending（含未完成 Settlement）、decisions（含 ConfirmationRef）的 v1
  登记表迁移后 v1 投影逐项相等、ID 不变；匹配 / 未匹配 / 共用条款号 / 两个编号不同版本 / 两条目同版本键拒绝；唯一前驱与
  不唯一；三处中断点（写日志前、写日志后替换前、替换后读回前）与损坏目标的恢复分类；Codex 的刷新反例（刷新在替换前中断不被
  判为已提交）；备份永不覆盖；`--dry-run` 不写文件；no-op。
- `tests/identity/test_attribution_versions.py`：§3 表第 1–6 行各一例，含共用条款号首次接入（`C` 对应两个版本、都未登记、
  材料无版本键 → 隔离，不新建）；无索引时行为不变；新版本：新条目、旧条目材料保留、`candidates` 记同名版本、人工确认路径可执行。
- 受保护测试的必要修改单独提交并说明：S5b-1 的新版本断言（`replaces`、同一条目）按本 Spec 改为新条目；依赖“新版本退役旧条款”
  制造冲突的确认恢复用例改用其他方式制造同一冲突，断言意图不变。

门禁：Harness 确定性用例、ruff、mypy、`tests/architecture`、文件 ≤ 500 行、`git diff --check`。离线核对：对线上登记表**副本**
做迁移 `--dry-run`（固定提交 `cd93dfcfd59b981fd532dc323c043e16c026ad9c`），报告逐条目匹配结果；从不写线上登记表。

## 6. 回退

代码回退即可：v2 登记表需要先用迁移命令留下的备份还原为 v1（v1 代码不读 v2）。本片合并本身不迁移任何线上文件。
