# 039 P3 API/Worker 壳验收规格

## ADDED Requirements

### Requirement: P3.1 同一 wheel 的两个进程角色

LLM Wiki 服务 SHALL 从同一个 Python wheel（同一 harness 包、同一领域代码）
提供恰好两个进程角色入口：`wiki-api`（API 角色）与 `wiki-worker`（Worker
角色），以 console script 入口注册。角色 SHALL 只由被调用的入口决定，
SHALL NOT 依据环境变量猜测或在运行中切换。两个角色 SHALL 共享同一配置
加载入口（P3.6）与同一 principal 模型（P3.2/P3.3）。

角色边界 SHALL 是：API 进程 SHALL NOT 在进程内运行 Worker claim 循环，
SHALL NOT 领取或执行 P1 任务；Worker 进程 SHALL NOT 提供任何业务/查询/
观测 HTTP 面，其 HTTP 面 SHALL 仅限 liveness 与 readiness 探针（P3.4），
SHALL NOT 持有用户会话。两个角色 SHALL 支持多副本并发启动：任意数量的
API 与 Worker 副本对同一 PostgreSQL 并发启动与运行 SHALL 不需要副本间
协调、进程内锁或 leader 选举；多实例正确性 SHALL 只依赖 PostgreSQL
（033 §6.2）。

#### Scenario: 多副本并发启动

- **WHEN** 对同一 PostgreSQL 同时启动 ≥2 个 API 副本与 ≥2 个 Worker 副本
- **THEN** 全部副本正常完成启动并各自达到 ready（P3.4），副本间无锁、
  无选举、无启动顺序要求；任一副本退出不影响其余副本

#### Scenario: 角色互斥

- **WHEN** 检查以 `wiki-api` 入口启动的进程与以 `wiki-worker` 入口启动的
  进程各自的运行面
- **THEN** API 进程内不存在 claim 循环、未领取任何 P1 任务；Worker 进程
  只应答 liveness/readiness 探针，对其他 HTTP 路径返回 typed 拒绝或不
  监听，业务与观测端点仅存在于 API 角色

### Requirement: P3.2 typed principal 模型与 fail-closed 铸造

principal SHALL 是封闭的 typed 模型：人类 principal 携带身份与按 Space
绑定的领域角色，角色 SHALL 是封闭枚举
`viewer | editor | reviewer | space_admin | super_admin`（033 §13）；服务
principal SHALL 是封闭枚举 `source_reader | wiki_projector`（P3.3）。系统
SHALL NOT 定义其他角色或其他 principal 种类。

principal 的铸造与校验 SHALL 只经唯一入口完成；该入口 SHALL fail closed：
凭据缺失、未知、格式非法或校验失败时 SHALL 返回 typed 拒绝，SHALL NOT
产生匿名/默认 principal，SHALL NOT 回落到任何默认角色；绑定中出现未知
角色名或未知 Space SHALL 同样 typed 拒绝而非忽略。

API SHALL NOT 信任调用方提交的 `space_id` 或 `user_id`（033 §13）：请求
路径、查询参数、header 或 body 中携带的任何 space/user 标识 SHALL NOT
授予或放大权限；生效的 Space scope SHALL 只从已认证 principal 的绑定
推导，请求目标 Space 不在绑定内时 SHALL 在进入 handler 前 typed 拒绝。
授权判断 SHALL 使用铸造时刻的当前绑定，SHALL NOT 把历史快照当持续授权。

MVP 的 principal 绑定与服务凭据 SHALL 来自配置/静态 provider（接口化，
可被后续 PR 替换），SHALL NOT 新建持久化表（P3.10）；与 WeKnora 身份/
ACL digest 的对账归 P2d/P11/P13，不在本 change。

#### Scenario: 未认证与非法凭据拒绝

- **WHEN** 请求不携带凭据、携带未知凭据或携带格式非法的凭据访问任一
  受保护端点
- **THEN** 铸造入口返回 typed 拒绝，请求以认证失败结束，不存在匿名
  principal，handler 未被执行

#### Scenario: caller 自报 space_id 不放大权限

- **WHEN** 已认证 principal 仅绑定 Space A，但在请求参数/header/body 中
  声明 `space_id = B`（或声明他人 `user_id`）访问 Space 范围端点
- **THEN** 请求被 typed 拒绝且零数据返回；生效 scope 始终来自 principal
  绑定，自报标识不产生任何权限效果

#### Scenario: 未知角色名 fail closed

- **WHEN** 配置/静态 provider 中某 principal 的绑定包含枚举外的角色名
- **THEN** 该 principal 的铸造被 typed 拒绝（而非忽略未知角色继续放行），
  错误可观测且不含凭据明文

### Requirement: P3.3 scoped service principals 权限不放大

服务 principal SHALL 只有两个：`source_reader` 与 `wiki_projector`
（033 §13）。每个服务 principal SHALL 携带显式声明的封闭能力集：
`source_reader` 仅限只读读取所绑定 RAW KnowledgeBase 的
Source/chunk/artifact 一类能力；`wiki_projector` 仅限调用 managed-page
conditional endpoint 一类能力。能力检查 SHALL 经唯一入口，未声明的能力
SHALL typed 拒绝（fail closed）。

服务 principal SHALL NOT 持有 `super_admin` 或任何人类领域角色能力；
类型系统与铸造校验 SHALL 使「服务 principal + 人类角色」「服务 principal
+ superadmin 能力」的构造不可表达或在校验时 typed 拒绝。服务 principal
SHALL 绑定显式 Space scope，SHALL NOT 默认全局。本 change 只冻结身份/
scope 模型与校验；以这些 principal 发起的真实 WeKnora 调用归
P4a/P4c/P12，P3 内 SHALL NOT 出现任何 WeKnora 调用。

#### Scenario: 服务 principal 请求人类角色能力被拒

- **WHEN** 以 `source_reader` 或 `wiki_projector` 身份请求需要
  `viewer/editor/reviewer/space_admin/super_admin` 领域角色的端点（含
  P3.9 观测端点）
- **THEN** 请求被 typed 拒绝且零数据返回；服务 principal 不因任何配置
  组合获得人类角色

#### Scenario: 服务 principal 无法获得 superadmin 能力

- **WHEN** 尝试构造或配置一个携带 `super_admin` 能力（或人类角色绑定）
  的服务 principal
- **THEN** 构造在类型/校验层被 typed 拒绝，不产生可用 principal

#### Scenario: 跨能力集调用被拒

- **WHEN** 以 `wiki_projector` 身份请求 `source_reader` 能力集内的能力
  （或反向）
- **THEN** 能力检查 typed 拒绝；能力集不可互换、不可合并

### Requirement: P3.4 liveness 与 readiness 探针

两个角色 SHALL 各自暴露 liveness 与 readiness 两个探针端点，语义 SHALL
严格区分：

- liveness SHALL 只回答「进程/事件循环存活」，SHALL NOT 包含任何外部
  依赖检查；数据库不可用 SHALL NOT 使 liveness 失败（避免依赖故障触发
  重启风暴）；
- readiness SHALL 同时验证：(a) 以真实查询验证 PostgreSQL 连通；
  (b) migration head 检查——数据库当前 Alembic revision 与 wheel 内打包
  的期望 head 完全相等；落后、超前、multi-head 或无法读取 SHALL 均判定
  not ready 并返回 typed 原因。

readiness SHALL fail closed：检查执行错误或超时 SHALL 判定 not ready；
readiness 结果 SHALL 反映真实检查——SHALL NOT 硬编码 ready，SHALL NOT
在进程启动完成首次成功检查前上报 ready，缓存的成功结果 SHALL 只在配置的
新鲜度窗口内有效，窗口外 SHALL 重新检查。进入 draining（P3.5）后
readiness SHALL 立即变为 not ready。探针响应 SHALL NOT 携带 secret、
DSN 或任务负载。

#### Scenario: 迁移状态不一致时 readiness 不撒谎

- **WHEN** 数据库 Alembic revision 落后于（或不等于）wheel 期望 head 时
  查询 readiness
- **THEN** readiness 返回 not ready 与 typed `migration_head_mismatch`
  一类原因；进程不得据任何缓存或默认值上报 ready

#### Scenario: DB 不可达时 liveness 与 readiness 分离

- **WHEN** PostgreSQL 不可达或连接超时
- **THEN** readiness 在配置的检查超时内返回 not ready（typed 原因），
  liveness 继续成功；恢复连通后 readiness 在下一次真实检查后恢复 ready

#### Scenario: 启动完成前不上报 ready

- **WHEN** 进程已启动但尚未完成首次 DB + migration head 检查
- **THEN** readiness 返回 not ready；只有首次检查真实通过后才返回 ready

### Requirement: P3.5 优雅停止与 P1 lease drain

两个角色收到 SIGTERM/SIGINT SHALL 进入 draining：readiness SHALL 立即
变为 not ready；API SHALL 停止接受新连接/新请求并在配置的 drain deadline
内完成在飞请求；Worker SHALL 立即停止发起新的 claim（信号后零新领取），
在飞任务继续执行并保持 heartbeat。

在飞任务的收敛 SHALL 是：在 drain deadline 内完成的任务照常经 P1 typed
完成/失败转换提交；到达 deadline 仍未完成的任务 SHALL 被放弃——取消其
执行、停止其 heartbeat，此后 shell SHALL NOT 再为被放弃任务发起新的完成
事务；被放弃任务由 P1 的数据库时钟 lease 过期 + 回收 + 更高 generation
接管收敛（P1.10），其 attempt 消耗与 `lease_expired` 记录是显式设计代价
而非静默丢失。无论进程在 drain 的哪一刻退出，同一任务 SHALL 恰好持久化
一份领域结果（由 P1.5/P1.3 保证；shell SHALL NOT 提供绕过 P1 store 的
第二提交路径）。

整个停止过程 SHALL 有界：drain deadline 与总退出时限 SHALL 来自配置；
重复信号 SHALL 触发立即退出（仍不产生半写——完成事务原子性归 P1.6）。
draining 期间 SHALL NOT 接受新 claim、SHALL NOT 启动新的 durable 工作。

#### Scenario: 信号后零新领取且在飞任务正常收尾

- **WHEN** Worker 正在执行任务时收到 SIGTERM，任务能在 drain deadline 内
  完成
- **THEN** 信号后该 Worker 不再产生任何新 claim；在飞任务照常提交，恰好
  一份领域结果与完成事件；进程在配置时限内退出

#### Scenario: 超时任务被放弃并由其他实例接管

- **WHEN** Worker 收到 SIGTERM 后某在飞任务无法在 drain deadline 内完成，
  进程按时限退出，另一存活 Worker 持续运行
- **THEN** 被放弃任务的 lease 按数据库时钟过期，被回收（记
  `lease_expired` typed `retryable`）并以严格更大的 generation 被存活
  实例重新领取执行；最终该任务恰好一份领域结果

#### Scenario: drain 开始即摘除流量

- **WHEN** API 副本收到 SIGTERM 进入 draining，随后到达新请求与 readiness
  探测
- **THEN** readiness 立即 not ready（负载均衡可摘除该副本）；已在飞请求
  在 deadline 内正常完成，新请求不被该副本接受

### Requirement: P3.6 env-prefixed 配置合同与密钥不泄漏

shell 配置 SHALL 经唯一 typed 配置模型加载，环境变量 SHALL 使用单一
文档化前缀 `WIKI_`；shell SHALL NOT 从散落的 `os.environ` 读取业务配置。
必填项（至少 PostgreSQL DSN）缺失或无法解析时，进程 SHALL 在启动时
fail closed：以非零码拒绝启动，并给出列出全部缺失/非法键名的 typed
错误；SHALL NOT 以隐式默认值代替必填项，SHALL NOT 把失败推迟到首次
使用。可选项 SHALL 有显式文档化默认值。

所有运行数值——worker 本地并发、claim 空轮询间隔、heartbeat 间隔、
lease 有效期、readiness 检查超时/新鲜度窗口、drain deadline、探针端口
等——SHALL 来自配置；任何具体数值 SHALL 只是环境默认值而非产品上限，
SHALL NOT 硬编码于行为代码（033 高频不变量）。配置间存在依赖时 SHALL
启动时校验：heartbeat 间隔 SHALL 严格小于 lease 有效期，违反即拒绝启动。

secret（DSN 口令、服务 principal 凭据等）SHALL NOT 出现在日志、
`repr`/`str`、异常消息、探针与观测响应中；配置对象的字符串表示 SHALL
对 secret 字段脱敏。shell 启动 SHALL NOT 要求 WeKnora 凭据（P3 无
WeKnora 调用）；遗留 `HARNESS_` 配置模型不是 shell 的权威。

#### Scenario: 缺失必填项拒绝启动

- **WHEN** 未设置 `WIKI_` 前缀的 PostgreSQL DSN（或任一必填项）时启动
  任一角色
- **THEN** 进程以非零码拒绝启动，错误信息列出全部缺失/非法键名，且不含
  任何 secret 值；不存在半启动状态

#### Scenario: secret 不进入任何输出

- **WHEN** 审查配置对象的 `repr`/`str`、启动日志、认证失败错误、探针与
  观测端点响应
- **THEN** DSN 口令与服务凭据均不以明文出现；脱敏表示可辨识字段存在但
  不泄漏值

#### Scenario: 行为只由配置决定

- **WHEN** 同一代码分别以两组不同的 `WIKI_` 配置值（如不同 drain
  deadline、不同本地并发）运行
- **THEN** 两组行为按各自配置值生效，无代码变更；heartbeat 间隔 ≥ lease
  有效期的组合在启动时被拒绝

### Requirement: P3.7 Worker 主循环消费 P1 store

Worker 主循环 SHALL 只通过 P1 JobStore 的存储层 API 消费任务：claim 领取
→ 派发 handler → 按配置间隔 heartbeat（持有期间维持 lease）→ 经 P1
typed 转换提交完成/失败。Worker SHALL NOT 绕过 store 直接读写
`wiki_jobs`/`wiki_outbox_events` 行，SHALL NOT 复制、覆盖或放松 P1 的
per-Space/全局并发上限（store 侧上限仍是唯一权威）。

Worker 本地在飞并发（每实例同时执行的任务数）SHALL 来自配置；仅当存在
空闲槽位时才发起新的 claim。空队列（P1 typed 空结果）SHALL 进入配置的
空轮询间隔等待，SHALL NOT 忙轮询；store/DB 瞬时错误 SHALL 按有界退避
重试，主循环 SHALL 存活且错误可观测，SHALL NOT 因瞬时错误退出进程或
静默吞掉。

P3 SHALL 交付空的 handler registry：SHALL NOT 注册任何业务 handler
（业务 handler 归 P4a 及后续消费方 PR）；registry SHALL 是显式注册扩展
点。领取到未注册 `job_type` 的任务 SHALL 经 P1 记为 typed `retryable`
失败（错误摘要 `unknown_job_type`），由 P1 按 `max_attempts` 路由；
SHALL NOT 伪装成功、SHALL NOT 静默丢弃、SHALL NOT 停留在 `running`。
handler 抛出的异常 SHALL 全部落入 P1 typed 错误分类（P1.4），shell
SHALL NOT 吞掉任何失败。

#### Scenario: 多实例消费收敛于 P1 合同

- **WHEN** ≥2 个 Worker 副本以本地并发 >1 并发消费同一批任务（使用注册
  的测试 handler）
- **THEN** 每个任务在其 lease generation 内恰好被一个副本领取（P1.2），
  完成经 P1 typed 转换提交，恰好一份领域结果；副本间无进程内协调

#### Scenario: 未注册 job_type 不伪装成功

- **WHEN** 队列中存在 handler registry 未注册的 `job_type` 任务被领取
- **THEN** 该任务经 P1 记 typed `retryable` 失败（摘要
  `unknown_job_type`）并按 `max_attempts` 路由至 `retry_wait` 或
  `dead_letter`；不产生伪造的 `succeeded`，主循环继续消费其他任务

#### Scenario: 本地并发与空轮询只由配置决定

- **WHEN** 同一 Worker 代码分别以本地并发 1 与 4 运行，且队列被清空
- **THEN** 同时在飞任务数分别至多 1 与 4；空队列后 claim 频率退到配置的
  空轮询间隔，无忙轮询；瞬时 DB 断连后主循环在有界退避内恢复消费

### Requirement: P3.8 API 请求生命周期纯净性

API 请求生命周期内 SHALL NOT 启动任何 durable background task：SHALL NOT
fire-and-forget 领域写、SHALL NOT 在请求进程内启动编译/投影/外部同步、
SHALL NOT 创建生命周期超出该请求且承载领域副作用的线程/协程/进程。
表达 durable 工作的唯一方式 SHALL 是经 P1 enqueue 在请求事务内落一条
任务行（由 Worker 部署执行）；响应返回时该事务 SHALL 已提交或已失败，
不存在「响应成功但工作既未入队也未完成」的中间态。

P3 SHALL NOT 交付任何业务 handler：API 面 SHALL 仅包含探针（P3.4）与
观测端点（P3.9）。P3 的两个角色 SHALL NOT 发起任何 WeKnora 调用。
请求范围内的非 durable 并发（如并行只读查询）SHALL 在请求结束前收敛。

#### Scenario: 请求结束后无遗留领域工作

- **WHEN** 任一 API 请求返回响应后检查进程内任务/线程与数据库
- **THEN** 进程内不存在承载领域副作用的遗留后台任务；请求造成的一切
  durable 工作以已提交的 P1 任务行形式存在（或请求整体失败、零任务行）

#### Scenario: API 角色不执行 durable 工作

- **WHEN** 审查 API 角色对 P1 store 的调用面
- **THEN** API 只使用 enqueue 与只读指标查询；claim/heartbeat/完成转换
  只出现在 Worker 角色

### Requirement: P3.9 观测端点映射 P1.9 指标查询

API 角色 SHALL 提供只读观测端点，把 P1.9 的存储层指标查询原样暴露：
per-Space 的各状态任务计数（含 queued 队列深度与 dead_letter 计数）、
最老可调度任务年龄、attempt 累计与当前 `retry_wait` 计数。端点 SHALL 是
同步只读查询，SHALL NOT 建设 metrics 平台、第二存储或后台聚合任务。

授权 SHALL fail closed 且遵守 P3.2/P1.8 的 Space scope 规则：per-Space
指标 SHALL 要求已认证人类 principal 在目标 Space 持有 `space_admin`
（或 `super_admin`）；全局聚合 SHALL 是显式命名的独立端点且 SHALL 仅限
`super_admin`；其他角色、服务 principal、未认证或跨 Space 请求 SHALL
typed 拒绝、零数据。响应 SHALL 只含计数/年龄/时间戳一类聚合值，
SHALL NOT 携带任务负载、幂等键明细或 secret。

#### Scenario: space_admin 读取本 Space 指标

- **WHEN** 在 Space A 持有 `space_admin` 的 principal 查询 Space A 指标
  端点，且 store 预置了已知任务分布
- **THEN** 返回值与 P1.9 对该分布的查询结果精确一致；响应不含任务负载
  与 secret

#### Scenario: 权限不足与跨 Space fail closed

- **WHEN** 以下请求分别到达：Space A 的 `viewer/editor/reviewer` 查询
  Space A 指标；Space A 的 `space_admin` 查询 Space B 指标；服务
  principal 查询任一指标；未认证请求
- **THEN** 全部被 typed 拒绝且零数据返回

#### Scenario: 全局聚合仅限 super_admin

- **WHEN** 非 `super_admin` 的任何 principal 请求全局聚合端点；随后
  `super_admin` 请求同一端点
- **THEN** 前者 typed 拒绝零数据；后者返回与 P1.9 全局查询一致的聚合值

### Requirement: P3.10 零迁移与无新表

P3 实现 SHALL 包含零个 Alembic 迁移，SHALL NOT 创建、修改或删除任何表、
索引或约束；合入前后数据库 schema 与 Alembic head SHALL 完全不变。
principal 绑定与服务凭据在 MVP SHALL 由配置/静态 provider 承载（P3.2）：
身份持久化不属于 P3 的所有权（033 §16.2——binding/ACL 状态归 P2d），且
本 change 的单一不变量不含任何持久身份状态。实现中若发现确需持久化表，
SHALL 停止并另立 change 修订规格，SHALL NOT 在 P3 实现窗口内临场加表。

#### Scenario: diff 零迁移零表变更

- **WHEN** 审查 P3 实现 PR 的 diff 并在合入前后各执行一次
  `alembic heads`/schema 对比
- **THEN** diff 中不存在迁移文件与 ORM 表定义变更；合入前后 Alembic
  head 与数据库 schema 完全一致
