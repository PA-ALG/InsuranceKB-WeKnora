# Release Scale 1 · 发布请求预算与激活回执

- Issue #573，Codex 实现，Claude 审核
- [裁定](https://github.com/PA-ALG/InsuranceKB-WeKnora/issues/573#issuecomment-6879562547)
- [编译 carry 补充范围](https://github.com/PA-ALG/InsuranceKB-WeKnora/issues/573#issuecomment-6880100995)
- 初始基线 `a8cb32011677750fe71f42afb70bd988c90dbd59`

## 1. 目标与范围

单款发布的客户端可独立提高激活读取超时和旧全量 Release 读取字节预算。
激活可选择只传身份，随后按固定 Release 核对。旧 Active、历史全读、默认激活、
候选/审核/CAS/来源/幂等状态机和 ST-1 验证日志预算保持原语义。

本阶段不承诺激活耗时下降。提交后的完整成员读取及校验照常执行，回执只减少
一次传输。13,000 档定向读、发布零全量传输与 8 MiB 门槛属于 PR-2。隔离
7,300/13,000 各三次，记录阶段时序；#559 的 7,300/15,000 与容量验收照旧。
本 PR 只跑离线机制测试，无模型或生产调用，无部署、索引或迁移。

## 2. REST 扩展

同一个服务 key 路由 `POST candidates/:candidate_id/activations` 接受可选
`?response=receipt`。省略仍返回原完整 Release。显式值只接受单个
`receipt`。重复、空、非法值、包含该参数的不可完整解析查询返回 HTTP 400
`INVALID_REQUEST`，并在激活前拒绝。无此参数的原路由查询保持原有行为。

新增只读 `GET candidates/:candidate_id/activations?decision_id=<id>`，恰一个
非空 decision_id。两条小回执路径使用相同 full-access API key 与原
Tenant/Space 授权，未开放浏览器或受限 key。对账绑定原 Candidate、Bundle、
批准的 Decision 及其 digest、同四段 Scope 与确定性 nonce，读原本的永久
activation receipt 和它指向的 Release，不取当前 Head。必须核对回执的
scope、nonce、authorization digest、Release ID、epoch、前驱及 manifest 的
候选和决策。GET 保留发布后的完整读取与校验。不存在该次已提交回执时返回
`RELEASE_NOT_FOUND`，只表示本次读取未证明提交。其它错误沿原类型或
脱敏内部错误。对账接口不进行业务写入；chunks.v1 仍按 ST-1 规则记录读取验证。

小回执使用原成功信封，data 的固定字段为 `id`、`epoch`、
`base_release_id`、`candidate_id`、`decision_id`、`decision_digest`。
新 POST 复用旧激活入口完成事务和原完整校验，只从成功结果投影身份；
返回给其他决定的历史 Release 不能包装成本决定的回执。完整响应的旧
候选复用行为保持。回执与失败控制只用于新增协议，旧客户端继续按旧协议工作。

## 3. Harness

显式预算类型按调用目的选择：

| 请求 | read | 解压后响应上限 |
| --- | --- | --- |
| 旧 Active 或指定 Release 全量 GET | 30 秒 | 默认 32 MiB，可配 32–128 MiB |
| 原激活 POST（完整响应） | 默认 30 秒，可配 30–180 秒 | 32 MiB |
| 小回执激活 POST | 同激活预算 | 64 KiB |
| 精确回执 GET | 30 秒 | 64 KiB |
| 其它原请求 | 30 秒 | 32 MiB |

连接、写入、连接池仍为 30 秒，禁重定向和外部代理的既有选项不变。
`HARNESS_WEKNORA_ACTIVATION_READ_TIMEOUT_SECONDS` 和
`HARNESS_WEKNORA_RELEASE_MAX_RESPONSE_MIB` 接受所列范围内的规范 ASCII
十进制整数。未设置采用默认值，空字符串等非法设置在首次发送前报
`INVALID_REQUEST`。预算按流式解压后的字节计，超限返回 `INVALID_RESPONSE`。
旧激活全量响应溢出时应改用受支持的小回执，不能借全读预算放大其它响应。

`compile_run --carry-active` 继续为本轮读取一次 Active，使用同一全量 Release
GET 预算。完整响应超过预算时以 `INVALID_RESPONSE` 退出 2，发生在读取来源页、
创建模型客户端、发送请求或写入候选之前。保留既有已审引文、产品及材料固定修订
筛选。PR-2 再改为在固定 Release 中定向读取本产品的已发布 Claim。

Judge Batch `publish --activation-receipt` 给新建尝试启用小回执，作为
记录属性随断点保存。已有全量尝试保持既有恢复行为，收回开关不改变
已经冻结为小回执的尝试。小回执模式独立核对响应的候选、决定与保存的
决策 digest，再根据回执的固定 ID 全量 GET，核对上述身份、epoch、前驱、
候选成员摘要及移除项，才允许标记已验证、提交抽检并完成。后续 PR-2 替换
该全量 GET 及发布前正文读取。首次小回执 POST 在发送前记录 `pending=activate`。
POST 读超时、无效回执、进程中断等保留待确认状态。恢复只对当时的
Candidate/Decision 进行 GET 对账并读固定 Release。未找到或不可核实时停止，
保留未知状态和同一尝试。没有自动补发激活或改用旧接口。
`NEEDS_REBASE` 沿现有显式业务分支处理。抽检算法和其它发布命令不变。

## 4. 独立 RED 与门禁

- Go 通过真实 auth/gate/路由和 Service 验证显式投影、原响应、
  权限/参数拒绝、写失败和已提交之后完整读取失败。用真实 repo 的 PG
  验收历史 exact receipt、head 前进、错误绑定与零额外激活。
- Harness 通过公开客户端与 Judge Batch 的离线 transport/记录验证预算隔离、
  默认及上下界、压缩后超限、小回执和全量旧回执兼容。断点对账测试覆盖
  Head 已前进、无精确回执及固定版本身份错配，确认不重发 POST。
- `compile_run --carry-active` 经合成 HTTP 验证同一完整 Active 在默认预算和
  配置后的边界行为，超限必须零模型发送，配置允许时按固定修订携带相同引文。
- 冻结新增 RED 后实施。旧保护案例不改。定向 Go/Harness、ruff/mypy、
  架构守卫、合同对照由本地与精确 head CI 提供证据。

写域为企业激活 HTTP/服务/存储适配器与新增同模块测试，Harness
`bundle` 客户端/预算、`ingest/judge_batch` 的 CLI 和发布记录，以及
`eval/compile_run` 的诊断和自有测试。
该扩展不改 Candidate/Release 成员 JSON Schema、前端、上游文件及守卫基线。
