# Release Scale 2 · 固定 Release 成员索引与按键读取

- Issue #573，Codex 实现，Claude 审核。基线为 PR #574 合并提交 `3d18d8a34a36017ffd5a3f5ef603903ab9b90564`。
- [PR-2 裁定](https://github.com/PA-ALG/InsuranceKB-WeKnora/issues/573#issuecomment-6879562547) · [carry 补充](https://github.com/PA-ALG/InsuranceKB-WeKnora/issues/573#issuecomment-6880100995) · [完整激活预算补充](https://github.com/PA-ALG/InsuranceKB-WeKnora/issues/573#issuecomment-6881815702)

## 1. 范围

在当前 Space 一次固定 Head。Judge Batch 按款发布走固定版本索引、按 slug 批读、小回执、固定版本核对和原抽检。新路径由 `publish --targeted-release-reads` 显式选择，对新尝试同时启用小回执；该选择随尝试冻结。旧尝试保持原恢复路径。旧 App 仍可用既有命令模式。固定读取失败时停止，保留未知激活尝试，禁止因接口错误降级或重发。

`compile_run --carry-active` 固定一次 Release，并用索引的 Claim 归属选出所请求产品的旧 Claim；没有命中时不做正文批读。选择按 `subject_ref`，包含旧别名，沿原值、材料标识、parse attempt、SHA 及引用筛选。编译、候选变更判定、已有单 Head/激活事务、审核、CAS、撤回与证据契约照旧。

## 2. REST 与存储

三个端点复用企业 Space 全权服务 key 挂载，每请求重新鉴权。读取作用域为当前配置的 tenant/Space/RAW/Wiki。无 Head 允许初次发布；历史丢失、授权问题、超限、损坏、网络故障均停止。旧 Active、历史全读、ETag 和激活默认响应保持原行为。

| 端点 | 成功数据 |
| --- | --- |
| GET `releases/active/summary` | 当前固定 `id`、`epoch`、`base_release_id`、`candidate_id`、`decision_digest`、可缺省的 `retired_at`；无成员 |
| GET `releases/:release_id/member-index` | 固定身份及 `members`，每行含 `logical_slug`、`member_digest`、`kind`，另外按类型投影 Claim `subject_ref/logical_key`、Entity `entity_id` |
| POST `releases/:release_id/member-lookup` | 只读；请求为 `{"slugs":[...]}`，1–256 个不同非空 slug；数据含固定身份、完整命中的原 Member 和 `missing` |

固定端点拒绝空或 `active` 作版本。单次索引最多 20,000 项，索引与批读各最多 8 MiB 未压缩 JSON（含信封）。入站批读有固定小请求体预算；出站超限 `RELEASE_READ_LIMIT`，HTTP 413。单个产品发布相关响应总计 8 MiB，超限停止。摘要及回执各 64 KiB。客户端严格验证固定 id/epoch、其余身份、响应覆盖、重复、摘要、返回成员与请求匹配及实际正文的业务 digest。批次不发送替代 Head 请求。顺序依原固定数据库读取，跨批按索引还原。

不增加持久索引、分页或迁移。权威的 scope/Release 记录与准备记录 manifest 摘要重新核对；索引 slug/digest 与 manifest 完整逐键核对。旧格式/bridge 以同一已固定的 Release 行选择旧成员；新格式走 ST-1 验证预约，校验块、对象映射与作用域。索引只查询窄列与必要 JSON 字段；正文选择同一 Release 的指定 slug，验完整对象身份和业务 digest。没有历史名录或对象时停止，新格式不落回旧副本。索引会在 PostgreSQL 读取所需 JSON 投影，服务端磁盘与事务耗时以测量为准。

## 3. Harness

先用索引校验全局 slug/key 冲突及历史别名，再取本款已有 Claim 和需要核对的候选目标。保留旧维护身份、撤回、专家锁与占用规则。摘要和按键正文携带同一固定版本身份。发布后按原 Candidate/Decision 回执逐项核对提交、删除；摘要差使用实际激活前驱。抽检读取实际变化 Claim、其 Entity 与原有 Profile，沿用旧层次、顺序、排序与 seed。不存在前驱只按空表处理；固定版本读取失败停止。旧模式仍可用。

补充容量裁定：旧完整激活 `ACTIVATE` 与 `FULL_RELEASE` 同用 `release_max_bytes`，环境变量范围和默认 32 MiB 保持。小回执激活 `ACTIVATE_RECEIPT` 仍为 64 KiB。激活读超时及其余请求预算不变。

## 4. 验收与写域

- 独立 RED：真实企业路由权限及输入边界，包含固定历史、换 Head、两种格式、损坏和预算。业务索引/批读对旧完整读取核等价。
- 独立 RED：公开非 receipt 激活接收超过 32 MiB 的完整合成 Release，在配置允许时成功；默认与超出配置时拒绝，小回执限额隔离。
- Judge Batch 和 compile_run 公开入口经离线 HTTP 验证新/旧产品、旧别名、固定修订、冲突、重放、超限及抽检等价。故障不得用别的版本或触发模型；测试合成。
- 隔离实际 PostgreSQL 合成 7,300/13,000 各三次。13,000 单款发布零全量 Release HTTP 读取、相关响应总计 ≤8 MiB。实际时间和激活阶段分列，无 p95 门槛。遵守 #559 优先级和环境隔离。
- 写域为自有企业挂载、release 服务及 store 和 memberstore 读取，Harness 客户端、changes/judge_batch 发布、carry/compile、各自新验收。原合约生成物、守卫基线、迁移、上游文件、激活事务不改。无生产、模型或部署。
