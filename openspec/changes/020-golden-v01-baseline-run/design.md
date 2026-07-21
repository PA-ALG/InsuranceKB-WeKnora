# 020 运行设计

权威设计：`docs/insurance-kb/20-enterprise-runtime-foundation.md` §7；工具契约：019。

T1 admission 详细设计：`docs/superpowers/specs/2026-07-19-golden-run-admission-design.md`。

运行分四个可恢复阶段：annotation、release、baseline、adjudication/profile。每阶段产物先写 WIP/run 目录，validator 通过后才进入 immutable release/approval。进程退出或网络失败从 manifest 记录的最后完成单元恢复。

真实模型选择不写成“最强可用”模糊口径：执行前在 `run-admission.md` 固定精确 ID。若模型变更，生成新的 admission revision 和 artifact fingerprint，不混写同一 baseline。

020 是环境约束 change：软件门禁可以绿而真实运行仍 blocked；validation-report 必须分别报告数据覆盖、模型调用、裁决完成度和阻塞原因。

## T1 可执行准入

准入采用单一类型化 plan，生成 canonical JSON result 与 `run-admission.md`。plan payload 固定唯一 `run_identity`/purpose、完整 identity contract 的 domain-separated SHA-256 与预算合同 SHA-256，`plan_payload_hash` 排除 approval envelope 与派生状态，避免自引用但阻止替换 manifest/digest 后复用签名；历史 provenance 与预算批准由部署侧受信公钥验证的 detached Ed25519 envelope 绑定该 hash/run/purpose/scope。信任根只能从代码固定的 root-owned `/etc/insurancekb/run-admission-trust.yaml` 加载，run CLI 无自选公钥/角色参数。签名输入固定为版本化 domain label + 禁 float/extra 的 canonical JSON UTF-8，防字段拼接与跨 scope/run 重放。结果同时锁定 annotator、weak extractor、judge 三角色精确 provider/model 及 expected immutable revision/deployment（provider 无稳定身份则不能 READY），019/021 merge revision，schema/prompt/template/golden、execution surface 及恰好 13 产品全部实际输入内容指纹，逐产品历史 provenance、checkpoint 根目录和业务批准预算。

当前尚未具备的模型 revision、必需产品输入或预算合同用显式 typed pending/null 表示并稳定返回 exit 2 `BLOCKED`，不得填造占位 SHA/revision；pending 角色不能进入 probe/预算费率身份计算。YAML 入口拒绝重复键，plan/result/report 路径别名在删除或写入前拒绝，避免 last-key-wins 歧义或误删输入。

默认静态检查不访问网络且永远不能 `READY`；显式 remote probe 强制 HTTPS/TLS verify、`trust_env=False`、无 ambient proxy，只能选择代码内 provider policy 固定的 protocol/origin/GET|HEAD/规范化 path，空 body、无 query/userinfo/fragment、禁 redirect；任何编码绕过、3xx 或推理端点配置均在后续请求前拒绝。Bailian 仅以官方 dedicated deployment detail `GET /api/v1/deployments/{deployed_model}` 的 `deployed_model/base_model/gmt_modified/status` 作为生产身份依据，公开 alias 无稳定 deployment metadata 时保持 `BLOCKED`，不得用未文档化 `/models` 响应伪造 revision。凭据环境变量名、时钟、整体 monotonic deadline 和最大有效期由代码 policy 固定；请求强制 identity encoding，压缩响应在读取 body 前拒绝，identity body 流式限长并将递归耗尽解析为 typed blocker。所有响应字段须先通过 provider-specific 安全语法；失败结果不保留 response-derived identity，成功审计只写精确匹配后的签名 plan 值，response body 不进入配置、日志、异常或报告。HTTP loopback 只允许无生产凭据、生产构造器不可达且路径精确为 `/metadata/{deployed_model}` 的 test policy。

预算采用 provider spend-cap attestation、总 token/费用硬上限与单产品 worst-case reserve。可预先枚举的调用用精确 request reserve；retry/gap-fill/judge 等动态 prompt 用签名的逐产品/角色 request pool，pool 绑定 model-role identity、RoleRate digest、`max_attempts` 和逐次 input/output/cost 上限，与 exact reserve 合并的最坏值必须在产品/总额/provider cap 内。由 run_identity+purpose 生成稳定预算账户（不随 approval revision 改变）；扩容 envelope 绑定上一批准 digest 与新 plan hash，只能原子、单调提高同一账户 ceiling，全部 settled/reserved/uncertain debit 与 attempt 保留，且既有 exact reserve/pool 的模型、费率、次数和逐次上限不得修改。durable ledger 以 account/stage/product 唯一键在 SQLite `BEGIN IMMEDIATE` 事务内预留，状态只允许 reserved→settled/released；旧 schema 向 pool-aware schema 升级须在单事务逐行校验并无损保留所有 exact attempt，否则 fail closed 且不替换旧表。每个逻辑请求以签名角色、完整 model-role plan 和精确 system/user prompt 的 domain-separated SHA-256 作为 request unit，须精确命中 signed request reserve 或在对应 pool 上限内 claim，再以唯一 attempt key+owner token 在同一锁内 insert/CAS；未走到的动态分支不需创建 attempt，所有已创建 attempt 则必须可对账。只有 winner 可发网络，loser/observer 不发，lease 过期不自动转移发送权，release 与 attempt claim 同锁。request attempt 在网络前落库；成功响应先以 mode 0600 原子写入 checkpoint 并 fsync 文件/父目录，再将响应 SHA-256 和 terminal 状态落 ledger；observer 只复用与 ledger digest 一致的 terminal artifact。恢复时任何无 durable terminal response 的 attempt（含 pre-send/send 模糊边界）一律记 uncertain、按全 reserve 计费且不自动重放。仅从未创建 attempt 或 provider 幂等/usage 对账证明未消费时可 release。运行时余额不足则在产品边界安全停止并保留 checkpoint；换 run/模型/费率或扩大上限必须形成新 plan hash 和链式签名确认，其中换 run/模型/费率必须新预算账户。

当前 11 份 WIP 金标缺少行内 annotator/time，只有逐产品、可证明且由授权主体签名的 provenance 才能补足 admission 证据；全局 `default_annotator` 不得作为准入依据。runtime 每产品前重跑 evaluator，不信任可编辑 `READY` 字段，并重算共享/本产品 digest。021 未合入、任何 provenance 未证实或 runtime 未通过 reserve/revalidation capability 验收时，T1 必须诚实输出 `BLOCKED`，不得启动模型。
