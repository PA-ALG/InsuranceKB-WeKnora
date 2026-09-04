# 830 BA0 Local Build Reuse Specification

## ADDED Requirements

### Requirement: BA0-REQ-01 complete and reproducible artifact identity

系统 SHALL 从受版本控制的 app build-input manifest 计算 canonical artifact identity。该 identity
MUST 覆盖 manifest 本身、实际 Go 源码闭包与 `go:embed` 输入、`go.mod`/`go.sum`、Dockerfile、
实际 context/ignore、Makefile、版本与构建入口、有效 ldflags/build args、builder/runtime base
digest、GOOS/GOARCH、builder 内 Go 版本、CGO/toolchain 合同、最终镜像复制资产、外部依赖锁、
target stage 与输出架构。计算 MUST 绑定显式冻结的 build-source identity，区分当前 integration
identity；只改未进入 manifest 的文档不得改变 artifact identity。canonical bytes、输入清单与
SHA-256 MUST 可离线重算；秘密或凭据不得进入 canonical bytes 或公开 identity。输入缺失、越仓、
未解析依赖、输入漂移或秘密进入公开 identity 时 MUST 在 Docker 调用前失败关闭。

#### Scenario: docs-only integration head changes

- **WHEN** integration head 只改变未进入 manifest 的文档，且所有冻结 build-source 输入不变
- **THEN** 重算得到相同 artifact identity，并分别保留 integration 与原 build-source identity

#### Scenario: one effective input is missing or drifts

- **WHEN** 任一有效 app 输入缺失、未纳入、无法解析或与冻结 build-source 不一致
- **THEN** identity 计算在 Docker 调用前失败，且不会按 Git SHA、tag 或秘密值降级

### Requirement: BA0-REQ-02 exact lookup bounds real builds and fails closed

唯一公共 app 构建入口 SHALL 在固定 `colima-g1-build` context 中，使用冻结的 repository scope
与 artifact-identity label 执行一次本地查询；查询结果 MUST 规范化为按 image ID 排序去重的
确定性 candidate set。查询或解析失败不得分类为 miss。candidate set 恰好为零才是 miss，单次请求
MAY 执行至多一次 `BUILD_AFFECTED`。candidate set 恰好有一个候选，且 inspect 得到的 image ID
与查询值相同、artifact identity/build-source/全部必需 label 完整匹配、OS/arch 为 `linux/arm64`
时才是 exact hit，SHALL 返回该 image identity 且 Docker build invocation=`0`。存在任一候选但
上述字段缺失或漂移、inspect 失败，或存在多个不同 image ID 时 MUST 以 build=`0` fail closed；
不得按 `latest`、创建时间或任意候选继续。

构建与查询入口 MUST 保证秘密或凭据不进入 subprocess argv、日志、image label、receipt 或
公开 identity。注入 canary secret 的 focused fake-runner MUST 能断言其 trace 和所有公开输出
均不包含该 canary；违反时在任何 Docker build 前失败关闭。

#### Scenario: exact local hit

- **WHEN** 确定性 candidate set 恰好有一个候选，且其 identity、build-source、全部 label、image ID 与 `linux/arm64` 均通过 inspect 校验
- **THEN** 入口返回该不可变 image identity，Docker build invocation 为 0

#### Scenario: zero candidates is the only miss

- **WHEN** 本地查询成功且规范化 candidate set 恰好为空
- **THEN** 该请求分类为 miss，并且最多调用一次 Docker build

#### Scenario: present invalid or conflicting candidates fail closed

- **WHEN** candidate set 非空且任一候选 inspect/label/build-source/identity/OS/arch 不完整或漂移，或含多个不同 image ID
- **THEN** 该请求不分类为 miss 或 hit，以 Docker build invocation=`0` 失败关闭

#### Scenario: canary secret never enters runner trace or public output

- **WHEN** focused test 通过许可的秘密输入通道注入唯一 canary secret 并运行 fake runner
- **THEN** fake-runner trace、subprocess argv、日志、image label、receipt 与公开 identity 均不含该 canary

### Requirement: BA0-REQ-03 stable metadata and shared persistent Go caches

二进制 `BUILD_TIME` SHALL 来自冻结 build-source commit timestamp 或对应 `SOURCE_DATE_EPOCH`，
`VERSION`/`COMMIT_ID`/有效 ldflags SHALL 由同一 build source 决定，Go version SHALL 来自 Linux
builder；运行时间、运行号和操作者只属于 provenance。Dockerfile 中下载 DuckDB 与执行
`make build-prod` 的两个 Go `RUN` MUST 使用同一版本化 cache-ID 函数，同时挂载持久
`/go/pkg/mod` 与 `/root/.cache/go-build`，并使用 `sharing=locked`。前一 `RUN` MUST 写入非秘密
probe 并确认 cache 非空，后一 `RUN` MUST 在编译前读到同一 probe 和非空 cache。缓存命中、
缺失或清理不得改变 artifact identity，缓存不得成为正确性 authority。

#### Scenario: repeat metadata generation and cross-RUN cache probe

- **WHEN** 同一 build source 在不同墙钟时间生成元数据，且两个 Go `RUN` 依次执行
- **THEN** 有效二进制元数据保持相同，第二个 `RUN` 观察到第一个 `RUN` 的同一 module/build cache probe

### Requirement: BA0-REQ-04 versioned external dependency facts

冷构建所需且影响输出的外部事实 MUST 进入 versioned lock 并参与 artifact identity，包括
builder/runtime base digest、Debian snapshot/Release identity 与实际包版本、固定版本且带校验值的
`pip`/`setuptools`/`wheel`，以及 DuckDB、uv 等下载项的版本、平台、来源和内容摘要。非秘密
mirror/代理地址 MUST NOT 进入 versioned lock、公开 identity 或 receipt；秘密/凭据 MUST NOT
进入 subprocess argv、日志、image label、receipt 或任何公开输出。锁缺失、来源/平台/摘要不符
或依赖只能从浮动源解析时 MUST 在 build 前或对应下载阶段 fail closed，不得无界 upgrade 或静默回退。

#### Scenario: locked dependency cannot be verified

- **WHEN** base、Debian、Python 工具或下载制品的任一 versioned fact 无法解析或校验
- **THEN** 构建停止且不以浮动 tag、最新包、镜像源或未校验下载继续

### Requirement: BA0-REQ-05 standalone exact-image D3 artifact smoke

D3 SHALL 只运行 D2 冻结的 exact app image，以 standalone Compose 和明确的
`--no-build --pull never` 语义执行只读 `CONTAINER_ARTIFACT_SMOKE`。该拓扑 MUST 无网络、无端口、无服务
依赖，不连接 PostgreSQL、Redis、Docreader、Provider/model、业务数据或生产环境；Docker build
invocation 与 pull invocation 均为 0。smoke SHALL 校验 runtime image ID 等于 D2 image identity、
二进制/必要文件与动态依赖可用，但不得宣称 WeKnora HTTP application health。

#### Scenario: run the D2 artifact in D3

- **WHEN** D3 接收已验证的 D2 exact image identity
- **THEN** 只读 artifact smoke 通过，runtime image ID 相同，build/pull、网络、端口、依赖和业务 effects 全为 0

### Requirement: BA0-REQ-06 one-build budget, zero effects and mandatory return

BA0 全程真实 app image build 总预算 SHALL 为 1；首次请求 exact hit 时 build=`0`，miss 时
build SHALL 不超过 1，随后相同 identity 请求 MUST build=`0` 且返回相同 image identity。
Provider/model、生产 `8081`、生产 Active、业务数据库与 G2 effects MUST 全为 0，G1 SHALL 保持
`PASS`。同一可复现阻断最多允许一次有证据、有界、单变量纠偏；纠偏后同一阻断第二次失败 MUST
STOP。若完成已冻结动作 A 需要新增前置 B，且 B 又需要计划外新前置 C，即构成第二层前置并 MUST
STOP。BA0 总时间盒最大为 2 个工作日；预算将超出、新服务/表/平台、第二层前置或时间盒超出时
MUST STOP 并返回用户。即使 BA0 最终 PASS，也 SHALL 先清零当前授权并返回用户；G2 继续锁定，
不得自动创建其 worktree/OpenSpec、写代码或启动环境。性能耗时只记录观察事实，不构成硬 SLA。

#### Scenario: budget or scope boundary would be crossed

- **WHEN** 下一动作将产生第二次真实 app build 或任一受禁 effect、第二层前置或范围扩张
- **THEN** 系统不执行该动作，记录 STOP 原因并 `RETURN_TO_USER`

#### Scenario: repeated blocker, chained prerequisite or timebox exhaustion

- **WHEN** 同一阻断在一次有界纠偏后第二次失败，或 A→B 且 B 又要求计划外新 C，或已达到 2 个工作日
- **THEN** BA0 立即 STOP，保留既有证据并 `RETURN_TO_USER`
