# PV-5b 目录快照日期，不以同步时间冒充数据日期

> Issue #532，跟踪 #501、阻塞 #531 D2。用户授权 Codex 写 Spec/独立 RED/实现，Claude 审核。
> 本片修订 PV-1 §2.1/2.3 的内部目录依据与 PV-4 §1.1 的 basis_date 来源；不改蓝图、平台合同或生命周期业务期。
> 真实模型/评委/线上登记写/部署/发布 0；#531 运维另行执行，不随工程交付放行。

## 1. 问题与取舍

`entity_metadata` 目前把 `metadata_basis.synced_at[:10]` 写入 `lifecycle.basis_date`。同步是审计事件，不能把旧目录快照
展示成今天的数据。采用固定提交的 **committer 时间**（不是 author 时间、文件 mtime、工作区 HEAD 或同步时间），换算到
固定 UTC+8 日历日。该日是目录快照依据日期，不是销售起止、保单适用或 Claim 业务有效期。

读时查询 Git 会破坏纯读与离线复用；只在 metadata_basis 加一个调用方填值又缺少固定来源传递。因此在现有内部内容寻址目录中
携带该日期，由迁移/refresh 复制到登记依据，身份展示只读依据。无需新服务、缓存、依赖或字段卡规则。

## 2. 数据和读取

- 内部 `VersionCatalog` 与 `MetadataBasis` 新增 `snapshot_date: YYYY-MM-DD | None`，缺省 None，合法日历日校验，严格类型。
  这不是 contracts/ 的协议字段；内部合同名 `product-catalog.v1` / `product-registry.v2` 不变。
- `catalog_from_checkout(directory, commit)` 沿用 40 位实际 commit 校验、Git 对象读取、禁懒取/禁交互、来源校验与整目录失败关闭；
  从同一个指定 commit 读取 committer Unix 时间并按 UTC+8 取日，不读取工作区内容或运行目录中的脚本。
  时间读取/解码或日期转换失败返回既有安全 `CatalogError`，不暴露路径或原始内容，不用当前时间兜底。
- 有 snapshot_date 时它进入目录文档和 sha256，登记表继续绑定该内容摘要、repository、commit。旧目录/登记依据缺该字段时，
  序列化省略新增空值，旧目录字节及 digest 保持；已存在的内容寻址目录永不覆盖。
- 旧文件可正常 load/保存/恢复；只读入口不查 Git、不补字段、不创建锁/日志。字段未知时不猜目录日期。

## 3. 迁移、refresh 与展示

- 实际 `uploads migrate-registry [--refresh]` 从固定提交重建目录时取得 snapshot_date，`plan_migration` 把它写入新的
  metadata_basis；旧登记在显式 refresh 时补齐。目录提交变化，日期取新提交；同提交可多次同步，日期不随时钟变化。
- `synced_at` 保持现有 UTC 审计语义。实质目录/版本变化时可更新；与现有逻辑相同的 no-op 保留旧依据，不为了刷新审计时间而
  产生实体改动。旧内部目录无该可选字段时继续原兼容路径，生产补齐由显式 Git refresh 负责。
- `entity_metadata`：basis 存在时 `basis_date = snapshot_date or synced_at[:10]`；basis 不存在仍 None。旧登记补齐前
  保留原行为。identifiers、family、销售期、材料、Claim、版本前驱规则均不变。
- 首次刷新补齐日期可能产生 identity_refresh 实体 delta；将该结果构成合成 Active 后，再次同目录刷新，`plan_refresh.noop`
  必须为真。若只有同步审计时钟变化，已补齐的 basis_date 不变，不重发实体。
- 备份独占/短写续写/fsync/操作日志严格字段及摘要/原子替换提交点/恢复分类全部沿用 PV-1，不新增日志字段。旧未完成日志仍
  先按原 old/new 完整摘要确认，不重算已提交意图；完成恢复后才按当前固定目录规划补齐。备份、日志和目录旧文件不覆写。

## 4. 写域与冻结边界

- 本 Spec（独立提交），新验收 `harness/tests/ingest/test_snapshot_dates.py`（独立 RED）。
- 运行时仅 `harness/src/insurance_harness/ingest/{version_catalog.py,product_versions.py,registry_migration.py,version_metadata.py}`。
- 可新增本片自身测试；不改旧保护测试、蓝图、守卫/基线、contracts/schema、Go、前端、导航、编译/评分/发布协议或材料角色数据。
- 不重构 PV-1 日志/文件发布，不进入 H1 实现树。每文件不超过 500 行；公共接口/G6 约束保持。

## 5. 验收与限制

全用合成 Git 对象、登记文件与时钟，走实际目录读取、迁移/refresh、entity_metadata 和 plan_refresh；不把真实产品编号特判进代码。

1. 同一提交用不同同步时钟刷新：snapshot/basis_date 不变；有实质变化时 synced_at 可变化；同内容再次 refresh no-op。
2. commit 改变时日期随新 commit；committer 与 author 不同、UTC+8 跨日和不同 offset 正反控，工作区 HEAD/脏文件不影响固定提交。
3. 旧目录/登记缺字段读写/摘要兼容，补齐前仍旧展示；新字段坏类型、坏日期失败关闭；新目录保存/读回绑定不退化。
4. 补齐后构成的合成 Active 再 plan_refresh 为 noop，Claim/证据/审核等不动。
5. dry-run 零写、首次迁移/refresh 与旧日志中断恢复/备份保留，既有 PV-1 安全测试继续通过。

用户给定固定目录提交的预期日期是 2026-10-21；若核实只读该 commit 元数据并先核 checkout 身份/干净，不读业务材料、
不执行源仓库脚本。线上 28 实体刷新、唯一 supersedes、Claim0/removal0 由 #531 后续运维单独计划，不是本测试的线上结论。

## 6. 实施清单

- [ ] 独立提交本 Spec，Issue 署名说明设计/计划；按已给授权继续，不重复申请方向。
- [ ] 写新验收并在旧 runtime 运行，记录预期失败；独立提交 RED，此后冻结。
- [ ] 实现固定 commit 日期传递/兼容序列化/展示优先级，运行 RED 与相关旧迁移/目录/身份测试。
- [ ] ruff/mypy、架构与合同导出 check，diff 与行数/写域检查；不重复无关全量/PG/build。
- [ ] merge 最新 origin/main（不 rebase），开 Closes #532 的 PR；精确 head CI 全绿后交 Claude 审核，不自行合并/运维。
