# 031 验收报告 — Operational run admission

> 当前状态（2026-07-23）：**PR #26 保持 Draft；A、B、C 已分别通过冻结树复审，D 已按
> 26-path allowlist 完成 finalizer/wiring 的提交前门禁。D 的 Spec 与 Quality/Security 独立复审均为
> C0/I0/M0；唯一一次 full deterministic 已通过。软件候选可进入提交/stacked PR 阶段，外部准入
> 条件继续 `BLOCKED`。** 本报告不声称
> canonical admission 或 020 `READY`，不声称已取得真实签名、provider hard cap、root-owned
> runtime trust store 或远端最终状态，也不把旧测试计数冒充当前最终 diff 的证据。
>
> D 层 allowlist 已由总控从 25 路径机械修正为 26 路径；新增路径只允许删除
> `harness/tests/test_operational_stack_blocker_031.py`。该测试只验证 A-C 临时 blocker，D 已用
> submit/resume/begin/post-settlement 四次 fresh finalizer、typed blocker 与零副作用测试替代；
> 旧 canonical D 也删除该文件。本修正不扩大生产功能或信任边界。

## 1. 结论与证明力边界

031 已实现从输入规范化、legacy provenance 证据回验、离线 Ed25519 authority、部署前授权与
durable infrastructure reserve、crash-safe provider 控制器、可信价格/cap/cleanup，到最终
new/adoption 状态机及 020 production wiring 的 fail-closed 软件路径。PR 首轮复审关闭了共享
provider cap 聚合、caller trust 注入、receipt capability 自铸、transport credential 串换、
adoption→cleanup 生产工件断链、cap 报告误判与 `run_020` 绕过 canonical finalizer 等问题；
随后独立复审发现的 caller `authorized_roles/now`、topology provenance、production/test seal、
controller dependency authority、durable observation 续期与 workspace cap identity 也已在同一
T9 中关闭；仍需最终只读复审确认没有遗漏，不能把软件门禁等同于外部运行准入。

本次没有执行 provider 创建、采纳、删除或推理调用。软件通过只能证明：当完整、匹配且受信的
外部证据到位时，系统有可验证的准入路径；当任一身份、签名、价格、cap、ownership、receipt
或预算事实缺失/漂移时，系统会拒绝放行。它不能证明外部审批已经完成，也不能证明当前远端
资源状态或费用已经变化。

## 2. 软件完成项

- **O1 输入 identity**：将唯一错误扩展名 byte-preserving 迁移为 `product_meta.json`，并验证
  canonical JSON、原始 bytes、Git blob 与 SHA-256 identity；权威 production identity 必须在
  人工 clean commit 后重新生成。
- **O2 provenance**：实现 observed/legacy 联合模型与只读 Git evidence inspector，回验 ancestor、
  literal path、blob、digest、freeze time 和 recorded agent allowlist。仓库只保留批次/模型标签，
  没有唯一历史 session-agent ID，因此 T2.3 合法地保持 `BLOCKED`，未生成伪候选。
- **O3 authority**：实现 identity/domain/scope/role 绑定的离线 key ceremony、签名/验签与
  production 固定 trust path；所有独立 operational domain 均支持安全 render→外部 sign→verify；
  production mutation API 不接受 caller trust override，私钥不入库、不输出。
- **O4/O6 durable reserve**：BudgetLedger v7 在 provider POST 前 exact-once 占用固定最大费用；
  provider hard cap 按相同受信资源边界聚合跨 run/purpose/account 的 fixed+inference 占用。
  final bind 同事务写入 topology 与两个 receipt annex，fresh production reload 还必须与固定
  operation-store artifact 精确比对后才签发 opaque `VerifiedFinalTopology`；强 annotator/judge
  共享 reserve，弱模型独立 reserve。
- **O5 provider 控制器**：实现固定 request/receipt 合同、durable pre-send journal、确定性 marker、
  timeout/409/响应丢失 reconciliation、受信 issuer capability、transport credential identity
  绑定、共享 OS run lock、原子 receipt、强弱双部署原子 observation batch 与 `trust_env=False`。
- **O7 价格、cap、cleanup**：实现 content-addressed price evidence、独立签名 pricing/provider-cap
  能力与只允许 verified-owned RUNNING PTU 的授权 cleanup；不确定结果不声称停止计费。
- **O8 编排**：new/adoption 两条唯一状态机接入最终 plan/contract/admission/probe；
  `run_020` 的 submit/resume/begin 每次在产品执行前 fresh 调用 canonical 031 finalizer。020 DTO、
  失败类型、fake/testing ledger 与 report 均不能铸造 READY/cap capability；当前缺外部条件时只
  产出 typed blocker/adoption 候选，不执行外部 mutation。

## 3. 本地门禁证据

以下旧 T8 数字产生于本轮 PR review hardening 之前，只保留为历史基线，**不得用于证明当前
最终 diff 可合并**。各组存在重叠，亦不得相加。

| 门禁 | 阶段结果 | 证明范围 |
|---|---:|---|
| O1/O2 identity + provenance | 110 passed | clean identity 算法、legacy Git evidence、受影响 020 identity |
| O3 authority + affected 020 | 103 passed | trust policy、key ceremony、签名安全边界 |
| O4 authorization / BudgetLedger v5（历史） | 146 passed | pre-POST reserve、post-receipt binding、迁移与回滚 |
| O5 provider controller | 23 passed | journal、reconcile、collision、receipt、代理隔离 |
| O6/O7 pricing/cap/cleanup | 56 passed | signed price/cap、成本计算、cleanup gate |
| T7 coordinator / production wiring | 21 passed | new/adoption 状态机、最终准入顺序 |
| 031 affected regression | 160 passed | 031 与受影响 020 合同组合 |
| T8 031 focused（历史） | **248 passed** | review hardening 前的 `tests/test_operational_*_031.py` |
| T8 020 admission（历史） | **711 passed** | review hardening 前的 `tests/test_run_admission_*_020.py` |
| T8 deterministic（历史） | **2965 passed / 30 deselected** | review hardening 前的全量 deterministic lane |
| T8 Ruff/mypy/OpenSpec/audit（历史） | **PASS** | 只证明旧 diff，不替代 T9 fresh gate |

### 3.1 PR review Critical RED→GREEN 证据

以下为当前 worktree 已确认的 focused 证据；每组存在重叠，且最终数字由总控在 T9.11 fresh gate
后回填。

| Critical | RED 证明的缺陷 | GREEN 关闭边界 | 当前证据 |
|---|---|---|---:|
| shared provider cap | 两个不同 run/purpose 共用 10,000 cap，各 reserve 6,000 均成功，总占用 12,000 | 按受信资源 identity 聚合 fixed+inference；跨账号并发、轮换 cap、重放与合法隔离覆盖 | ledger/cost/deployment 组合 **135 passed** |
| reconciliation issuer | 两个相等 caller receipt DTO 可自铸 verified capability | 只有受信 provider ownership issuer 基于 fresh remote evidence 可签发；跨 operation/resource/replay 拒绝 | 同上 focused GREEN |
| transport credential binding | authorization/cap 的 credential A 可被 transport key B 发起请求 | 非 secret transport identity 在网络前与 signed workspace/project/credential 精确匹配，receipt 从 verified transport 派生 | 同上 focused GREEN |
| adoption→cleanup artifact | cleanup 测试手工 seed artifact，production adoption 不产出 cleanup 输入 | adoption 原子/内容寻址写 verified artifact；共享 OS lock、获锁后 freshness、故障无半工件、replay 幂等 | 同上 focused GREEN |
| conservative cap reporting | 部分失败类型被硬编码为 `cap_verified=True` | 失败类型/020 DTO 不再推断 cap，缺 opaque production capability 时保守 unbounded/typed blocker | coordinator/run_020 组合 **111 passed** |
| operator CLI ceremony | provisioning/adoption/pricing/provider-cap/cleanup 无完整 render→sign→verify | 所有独立 domain/role/scope 可操作且禁止 self-enroll、跨域重放、私钥泄漏 | authority focused 包含于受影响组合，最终数字待回填 |
| canonical finalizer wiring | `run_020` 在 020 evaluate 后直接 `begin_product`，绕过 031 topology/cap | submit/resume/begin 在 evaluator/model/provider I/O/写入前 fresh 经 031 finalizer；fake/testing capability 不可放行 | coordinator/run_020 组合 **111 passed** |
| v6 topology sidecar | READY facts 只散落在 row/DTO，缺完整 durable capability；稍后 replay 会因写入时间漂移 | 同事务写完整 sidecar、fresh reload/reverify 后签发 sealed capability；v5 迁移空 sidecar、篡改 fail closed、exact replay digest 稳定 | infrastructure **44 passed**；idempotency exact test **1 passed** |
| caller roles/time authority | public production API 可接受 caller `authorized_roles` 或回拨 `now`；旧 topology 路径还会在 post-commit 二次复核失败后留下 bound rows | public API 物理移除覆盖参数；锁内从 root policy/internal clock 一次性重验并构造 capability facts，commit 后只做不可失败 seal | 关键 focused **120 passed**；相关 7 文件 **241 passed** |
| topology issuer/transport provenance | topology 可内嵌一组自洽 issuer/transport/digest 并同步重算 inner/outer digest后取得 capability | issuer 固定；transport digest 从 fresh signed cap 与固定 endpoint机械派生；strong/weak 与时间窗篡改均拒绝且 DB bytes 不变 | 对抗参数 **8 passed**；cost **67 passed**；infra **52 passed** |
| v5 bound migration | 首次扩展 020/031 回归暴露 19 个旧 fixture/schema v6 兼容失败；真实 bound v5 row 的 cleanup/READY 边界需验证 | v5 不虚构 sidecar；legacy cleanup 可查，READY fail closed；兼容 fixture 已调整 | 复现 **983 passed / 19 failed**；受影响 3 文件 **72 passed** |
| main pre-finalizer probe | `run_020.main` 仍先执行旧 020 evaluator；`probe=True` 时 topology/cap gate 前可产生 3 次 provider probe | main 只做纯输入准备；首次 evaluation 在 session lock 内由 canonical `finalize_durable` 发起，缺 topology 时 evaluator/probe/write=0 | RED **4 failed** → affected **77 passed**；wiring复审 APPROVED |
| capability issuer isolation | test issuer 与 production capability 共用 seal，测试 receipt 可被 public production topology bind 接受 | production/test 四类 capability seal 不可互认；public production topology 测试改用 signed cap→production transport→provider observation issuer | infra+cost **124 passed**；Ruff/mypy PASS |
| controller dependency authority | production controller 构造器接受 caller reader/transport，可替换 durable ledger/provider transport | no-DI canonical factory固定 ledger/run-root/API-key transport；依赖替换在authority/network前拒绝，fake DI 仅 private testing seam | deployment **36 passed**；Ruff/mypy PASS |
| durable observation refresh | sidecar 只靠 DB 内字段重算 reconciliation，5 分钟 TTL 进入 valid_until 且无续期路径 | v7 receipt annex 与固定 operation-store artifact建立独立 provenance；每个 submit/resume/begin 都原子刷新强弱双部署 observation，旧 batch 不可复用；static topology 不再被初始 5 分钟 TTL 错误截断 | deployment **43 passed**；coordinator **39 passed**；六个核心文件 **278 passed** |
| workspace cap identity | signed inference attestation 缺 `workspace_ref`，合法不同 workspace 可能互相污染 | workspace 纳入签名合同与 shared-cap identity；同资源全局聚合、不同资源隔离 | 跨 workspace exact **1 passed**；已包含于 fresh 020/031 与 deterministic 门禁 |
| workspace exact join | public bind/reload 可接受 workspace A reserve/cap 与 workspace B contract | contract、cap、reserve、receipt 与 topology 对 workspace/project/credential/evidence/amount/expiry/coverage exact join；错配零写 | focused **126 passed**；包含于最终门禁 |
| production cap self-enroll | caller 可将自签 cap 与任意 ledger/transport 注入 production controller | no-argument production factory 固定 canonical ledger/transport，每次操作 fresh 读取 root-approved cap，并将 approval digest 贯穿 transport/receipt/observation | focused **105 passed**；包含于最终门禁 |
| independent reconciliation artifact | 攻击者修改 strong/weak observation window并重算 reconciliation 与 topology digest，旧 fresh reload 仍接受 | controller 原子发布独立 content-addressed reconciliation artifact；v7 annex 同时绑定 immutable receipt 与 reconciliation 工件，替换/缺失/伪 digest 均零写拒绝 | RED strong/weak 均 `DID NOT RAISE` → GREEN **2 passed**；三目标文件 **178 passed** |
| typed infrastructure blocker | SQLite/filesystem 异常可越过 report 边界直接逃逸 | 仅捕获 `sqlite3.Error`/`OSError` 并产生 typed blocker；不吞 `KeyboardInterrupt`/`SystemExit`，evaluator/I/O/write=0 | coordinator **56 passed**；包含于最终门禁 |
| receipt cap approval join | receipt 只对齐 cap evidence，approval A receipt 可与 approval B reserve 混用并在 commit 后才失败 | receipt capability 在事务前 exact join evidence+approval；strong/weak 任一漂移均数据库字节不变 | RED **2 failed** → GREEN **2 passed**；infra ledger **59 passed** |
| single-bind cap observation join | legacy public single bind 未传 signed cap `observed_at`，漂移 contract 可写入 | production transaction 强制传入并 exact join verified approval evidence 的 observation time；失败零写 | RED `DID NOT RAISE` → GREEN **1 passed** |
| post-observation freshness | observation 等待期间 topology/cap 过期，旧顺序先 evaluator/probe 后 BLOCKED | observation 后立即 fresh clock+topology/cap+binding，再 evaluator；evaluator 后保留复核 | RED `evaluator.calls=1` → GREEN **1 passed**；coordinator **57 passed** |
| post-settlement candidate boundary | 首个 canary 模型/settlement 后直接 candidate evaluator/write，期间 authority 过期仍写 | candidate transition 前增加第 4 次 canonical finalizer；过期时 evaluator/builder/persister=0 | RED **2 failed** → GREEN **2 passed**；entrypoints **51 passed** |
| candidate evaluator return post-check | 第 4 次 finalizer READY 后，normal/resume 的 candidate evaluator 可在 probe 期间让 topology/cap 漂移或过期，旧 READY 随后仍 build/persist | normal/resume 共用 `evaluator → fresh durable topology/cap reload → build/persist` 原子边界；digest drift、cap rotation/expiry、SQLite/OSError typed fail closed，process-control exceptions 透传，evaluator 不重跑；production composition identity 与真实 boundary failure 由回归测试锁定 | RED **8 failed** → GREEN corrective **11 passed**；coordinator/entrypoint/wiring **140 passed** |
| shared transaction mode bypass | production ledger 可直接调用 shared dual transaction，在 `production_requests=None` 时消费 test receipt/self-enrolled policy；single 也可省略 root evidence | transaction 入口绑定 ledger mode；production 强制完整 root evidence/requests并覆盖 caller policy/time/bindings，testing 拒 production evidence | RED single message drift + dual `DID NOT RAISE` → GREEN **2 passed**；infra ledger **61 passed** |
| cleanup recovery authority | READY/budget/cap 过期会锁死减费 DELETE；ambiguous A journal 也阻止新授权 B 对同资源恢复 | 独立 cleanup-only factory只信 fixed ownership/root cleanup authority/credential；journal v2分离资源与授权尝试，获锁后重验，cap read=0 | focused **90 passed**；两文件 **142 passed** |
| foreign terminal receipt restore | v1/v2 journal 可指向同 store 中另一资源的合法 terminal receipt，并无 I/O 返回 `billing_stop_verified` | restore exact join run/op/reserve/source receipt/model/manifest，auth∈history，`absent_404` auth∈delete attempts | RED **16/16 DID NOT RAISE** → GREEN **16 passed** |
| canonical cleanup E2E | adoption/bind 测试与 cleanup-only 过期测试分离，后者手 seed/fake binding | strong/weak public adoption→4 artifacts→v7 dual bind→cap过期→两个 real-reserve cleanup-only factory→public cleanup | **1 passed**；严格 `GET/DELETE/GET ×2`，cleanup cap reads=0 |
| cleanup causal replay | A 的 DELETE 结果不确定、B 接管时 provider 已 404；首次 B 成功但精确重放因 receipt 错绑 B 而失败 | 有旧 attempt 的 `absent_404` 终态绑定最后一个 causal DELETE authorization；无旧 attempt 的 `already_absent_404` 才绑定当前 authorization，foreign receipt exact join 不放松 | RED **2 failed / 2 passed** → GREEN **4 passed**；完整 cleanup **92 passed**；独立复审 APPROVED |

### 3.2 当前 D 候选门禁状态

| 门禁 | 当前状态 |
|---|---|
| D 核心 coordinator + 受影响 020 focused | **279 passed** |
| 全部 operational-031 + run-admission-020 affected | **1274 passed** |
| 冻结 main + 当前 031 聚合树的 027/030 compatibility focused | **375 passed**；`canonical_verifier_unavailable` / `unknown_admission_profile` 精确断言 **2 passed** |
| Ruff（D changed Python paths） | **PASS** |
| mypy strict（D 3 source files） | **PASS** |
| deterministic `not live and not integration_postgres` | **PASS — 3280 passed / 30 deselected / 495 warnings，509.75s**；按冻结合同仅运行一次 |
| OpenSpec strict | **PASS — 031 与依赖的 020 change 均 valid** |
| `git diff --check` | **PASS** |
| final 26-path scope / blob+mode / secret audit | **PASS**；26 paths、sole deletion、working/blob equality、C 9 protected blobs、real index staged=0、secret/private-path patterns 均通过；报告更新后在冻结 exact tree 上再次复核 |
| 真实 provider / WeKnora live | **NOT RUN**；本轮禁止外部 mutation/inference |

A authority/cap、B receipt/transport 与 C adoption/cleanup/CLI 的冻结层均已取得跨窗口
Spec 与 Quality/Security C/I=0；D 最终候选也已取得两路独立 C/I=0 并完成唯一一次 full，软件
aggregate 可进入提交与 stacked PR 复核，但尚未据此把 PR #26 转为 Ready。该边界同样不覆盖外部签名、
root-owned trust/provider、人工 clean identity 或真实 provider/live 条件。

## 4. 外部未满足条件

1. **人工 clean commit 与 identity 重算**：当前 AI 工作树不能提供 production clean SHA。人工提交
   后必须从该 clean revision 重算产品、共享输入与 execution-surface identity；旧 SHA 的派生工件
   不得复用。
2. **legacy provenance T2.3**：仓库没有唯一历史 session-agent ID。需要真实 provenance 责任人
   提供可审计的唯一身份/裁决并签名；工具不得把 `claude-fable-5 (session agents, gs-v0.1)` 等批次
   标签伪装成唯一 agent ID。
3. **外部签名**：仍需 provenance、budget、provisioning、adoption、pricing、shared provider cap、
   cleanup 各自 domain-separated 的真实签名；签名必须精确绑定 031 规定的 identity、scope、金额、
   deployment、receipt、时限与角色。
4. **受保护的运行时信任材料**：仍需安装 root-owned production trust store 与 provider cap；CLI
   不得用本地覆盖路径绕过固定生产策略。
5. **provider 条件**：pricing 与 provider cap 必须覆盖相同 workspace/project/credential、区域、
   currency、固定部署费和推理费，并在有效期内；deployment ownership/manifest/receipt 必须 fresh
   重验。条件缺失时 canonical admission 继续 typed `BLOCKED`。

### 4.1 非阻塞但需后续收紧的边界

- `BudgetLedger(db_path)` 仍是公开的通用 ledger 构造器，测试、迁移与离线工具依赖它；canonical
  controller/run 已固定 production path 且执行前核验 exact dependency，因此当前不能用 shadow
  database 触发 provider mutation。后续应把 production namespace ownership 做成独立工厂/进程级
  capability，降低未来新 call site 误接任意路径的风险。
- 本轮冻结条款要求每次 submit/resume/begin fresh finalization，已覆盖 observation 后与 candidate
  transition；尚未定义长 executor 跨越 `valid_until` 时每个 `AdmittedModelClient.complete()` 的租约
  语义。后续 spec 应裁定是每次 provider send 前只读复核 durable topology/cap，还是签发有最短
  剩余时长和可撤销语义的执行租约；在裁定前不得把一次 READY 外推为无限期 authority。

## 5. 已知持续费用风险与外部变更声明

以下只记录 **2026-07-21 最后一次观测**，本次 T9 hardening 没有刷新远端状态：

- `qwen3.7-plus-2026-05-26-031strng`：last observed `RUNNING`；
- `deepseek-v4-flash-031weak1`：last observed `RUNNING`；
- 两者合计持续费用风险约 **¥11.04/小时**。

该历史观测不能证明它们此刻仍在运行，也不能证明计费已停止。本次没有创建、采纳、删除、停止、
扩容或调用任何外部模型；在真实 adoption/cleanup 授权、provider cap、ownership 与 fresh GET 证据
到位前，不得更新为“已采纳”“已清理”或“已停止计费”。

## 6. 合并与后续顺序

1. PR #26 保持 Draft；T9.12～T9.20 的分层 RED→GREEN、focused、Ruff、mypy strict、OpenSpec、
   两路独立 C/I=0 与唯一一次 deterministic 均已完成；重新冻结报告回填后的 exact 26-path tree，
   再按 A→B→C→D stacked 顺序提交/推送并更新 PR，转 Ready 前仍需最终远端 CI；
2. 使用 stacked review：`main ← A authority/cap ← B receipt/transport ←`
   `C adoption/cleanup/CLI ← D finalizer/wiring`。A 只承载固定 trust root 与 shared cap；durable
   topology 依赖 B 新增的 trusted receipt/transport facts，因此 sidecar/capability 在 B 闭合；
   C 承载 adoption artifact、shared lock、cleanup 与 operator ceremony；D 最后接通 canonical
   finalizer/run_020。`admission_budget.py`、`admission_deployment.py` 与 cost tests 跨层，不能按
   整文件粗暴拆分，必须按条款/信任边界 hunk 组织并保持每个 stacked head 可独立审查、编译且
   fail-closed；
   具体层级、hunk 边界和逐层门禁见 `stacked-review-plan.md`；
3. A～D 全部复审通过后再反向聚合为完整栈，一次进入 `main`；不得把半成品逐层合入并宣称
   可运行；
4. 人工复核、commit 031，基于 clean SHA 重算 production identity；
5. 在真实外部签名、root-owned trust store/provider cap 到位后重新生成 canonical admission；仍有
   blocker 就保持 `BLOCKED`，不得运行 020 T2～T7；
6. 031 独立合并后，再 rebase 002 并重新计算其依赖 identity；不得把 002 与 031 混入同一提交。

## 7. 本轮执行教训

- 每个高风险闭环先取得分段 RED，再做最小实现与 focused GREEN，避免大批改动后才发现合同偏差；
- 任何 agent/tool 60 秒无新输出即轮询并向业务方报告可验证进度；
- focused 绿色不能替代全量回归：本轮全量组合会揭示旧迁移 fixture 与新 BudgetLedger schema 的
  交互，必须在最终 diff 上 fresh 运行后才能收口；
- security capability 必须由受信 issuer 从 durable/fresh evidence 签发，不能以“两个 DTO 相等”、
  caller boolean 或 report 类型代替；费用 hard cap 的资源边界也不能被 account/run 键切碎；
- adoption→artifact→cleanup 必须由 production 端到端测试证明，测试手工 seed 只能验证 reader，
  不能证明生产链路存在。
