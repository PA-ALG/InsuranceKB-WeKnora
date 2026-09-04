# 830 BA0：固定 Colima 的本地构建复用设计

> 日期：2026-09-04  
> 状态：已完成方案讨论，待书面规格复核与用户确认  
> 设计基线：`origin/main=0e7a26568`，tree=`b96aa35`  
> G1 终态证据：`docs/insurance-kb/evidence/830-g1/g1-closeout.json`  
> 适用范围：当前 Mac、固定 `g1-build` Colima profile、Linux ARM64 本地构建

## 1. 目标与事实基线

G1 已完成并形成 `PASS` closeout，但一次 replacement app 镜像构建的实测墙钟为
`131m07s`。其中最长的 BuildKit step 是 `make build-prod`，耗时 `6557.9s`
（约 `109m18s`）；另有 runtime dependency layer `1604.7s`、Go module 下载
`404.1s`、DuckDB 下载 `265.9s` 和镜像导出 `299.3s`。这些步骤存在并行，不能
简单相加。权威原始记录为：

`docs/insurance-kb/evidence/830-g1/m3/d2-replacement-image-build-retry.json`

当前慢构建的主要原因已经有代码证据：

1. `docker/Dockerfile.app` 只挂载 `/go/pkg/mod`，没有持久化
   `/root/.cache/go-build`；源码变化后，大量 CGO 依赖重新编译。
2. `scripts/get_version.sh` 每次使用当前墙钟时间生成 `BUILD_TIME`；该值进入
   Go ldflags，使相同源码的重试也可能失去编译层缓存。
3. builder 和 runtime 的 `FROM` 使用可变 tag；G1 两轮构建实际解析到了不同
   base digest，使 runtime dependency 等稳定层也重新执行。
4. `COPY . .` 的失效域包含 Harness、OpenSpec 和历史 Evidence 等非 app 输入。
5. 当前 `start_all.sh --no-pull` 仍执行 `compose up --build`，不能满足 D3
   “只运行既有精确镜像”的合同。
6. G1 曾因错误的 Colima 探针发生假 STOP；客户端退出后 BuildKit 实际仍在运行，
   造成额外等待、调查和重建风险。

BA0 的唯一目标是：

> 同一 app artifact identity 不再构建；普通 Go 修改使用固定 Colima 中持久的
> Go 编译缓存；D3 只运行 D2 冻结的精确镜像，不再隐式触发 Docker build。

## 2. 决策与边界

BA0 是一次工程维护门，不是新的 Enterprise LLM Wiki 产品能力，也不改变 G2 的
产品需求、架构或验收标准。执行期间占用唯一 WIP：

```text
G1=PASS
CURRENT_AUTHORIZATION=BA0_ONLY
CURRENT_WORK=LOCAL_BUILD_REUSE
G2=LOCKED_PENDING_BA0_AND_USER_AUTHORIZATION
```

BA0 完成后不得自动启动 G2；总控先报告结果，再由用户授权下一张产品卡。

### 2.1 本次包含

- 固定 Mac + `g1-build` Colima profile 的本地缓存复用；
- Go module cache、Go build cache 和稳定 Docker layer cache；
- build 前本地 exact artifact 查询；
- 一个 versioned app 构建输入清单和薄 identity 计算；
- D2 单次构建和 D3 exact image 复用；
- 构建耗时、cache hit/miss、image identity 和失败阶段的最小记录；
- G1 `PASS` 与当前 BA0 状态的权威指针同步。

### 2.2 明确不包含

- GitHub-hosted CI cache mount 的跨机保存；
- remote builder、共享 registry cache 或跨开发机缓存；
- Colima profile 删除后的离线恢复包；
- `weknora-builder-base`、`weknora-runtime-base` 等新基础镜像产品线；
- 新数据库、新制品服务、第二套 Evidence/receipt 平台；
- 大规模 Dockerfile 重构或一次性彻底移除 `COPY . .`；
- Provider、模型、生产 `8081`、生产 Active、业务数据库或 G2 产品开发；
- 为统计目的反复清缓存或重复执行冷构建。

固定 Colima profile 或其缓存被删除时，允许性能退化并重新冷构建一次；缓存永远
不是制品正确性的 authority。

## 3. 方案选择

本设计采用“薄 identity 查询 + 固定 builder 的多层缓存”，不采用以下两个替代方案：

1. **仅修改 Dockerfile**：虽然能降低增量编译时间，但无法阻止同一 identity
   重复进入 Docker，也无法修复 D3 隐式 build。
2. **预制 builder/runtime base 与可搬迁离线包**：可进一步优化冷构建，但会新增
   上游跟版、安全更新、ABI、存储和恢复治理；当前收益不足以覆盖复杂度。

如本设计完成后，真实的自然冷构建仍长期受 runtime dependency layer 支配，才允许
基于新证据另行讨论固定 base；不得在 BA0 内预建。

## 4. 构建流程

### 4.1 唯一公共入口

本地 app 镜像继续通过现有 `scripts/build_images.sh --app` 进入。允许增加一个仅由
该脚本调用的标准库 helper，用于可测试的 identity 计算和 Docker inspect；不得暴露
第二个并列构建入口。`make docker-build-app` 必须委托同一入口，不能继续维护另一条
裸 `docker build` 路径。

### 4.2 Lookup-before-build

```text
冻结干净 integration head
        ↓
读取 versioned app build-input manifest
        ↓
计算 ARTIFACT_IDENTITY
        ↓
在固定 Colima 中按 label 查询并 inspect
        ↓
┌──────────────────────┴──────────────────────┐
│ exact hit                                    │ miss
│ 校验 OS/arch/identity/image ID               │ 执行一次 BUILD_AFFECTED
│ 返回既有不可变 image identity                │ 校验并记录新 image identity
│ Docker build invocations = 0                 │ Docker build invocations = 1
└───────────────────────────────────────────────┘
```

同一 identity 命中多个不同 image ID、label 缺失、架构不符或 inspect 失败时必须
fail closed；不得选择 `latest`、最近创建时间或任意一个结果继续。

### 4.3 Artifact identity

一个 app identity 至少覆盖：

- versioned app build-input manifest 自身；
-实际 app Go 源码闭包和 `go:embed` 输入；
- `go.mod`、`go.sum`；
- `docker/Dockerfile.app` 与实际生效的 ignore/context 定义；
- `Makefile`、`scripts/get_version.sh`、构建入口及有效 ldflags；
- builder 与 runtime 两个 base image digest；
- `GOOS`、`GOARCH`、容器内 Go 版本、CGO/toolchain 合同；
- 影响输出的 build args；秘密只参与必要比较，不写入日志、label 或 Evidence；
- 最终镜像复制的 config、scripts、migrations、samples、preloaded skills；
- DuckDB extension 的版本、平台、来源和内容校验；
- Debian snapshot/Release 校验、实际安装包版本，以及 `pip`、`setuptools`、`wheel`
  的固定版本与校验值；
- 最终 target stage 和输出架构。

B0 Evidence Pack 中已有的 app source subset 是历史证据，不得原地改写，也不能直接
作为本次运行清单。它至少漏掉 Swagger `docs` 包、`docreader/client` 和
`deploy/upstream`。BA0 新清单必须补齐这些实际依赖，并用 focused test 防止后续导入
新顶层 package 后静默漏算。

如果 integration head 变化但 app identity 完全相同，复用旧镜像是合法的；Evidence
Pack 必须同时记录“当前 integration head”和“该镜像原始 build-source head”，不得
伪造镜像是在当前 head 重新构建的。

### 4.4 缓存层次

缓存按以下顺序使用：

1. **L0 exact image**：相同 identity 直接复用，完全不调用 Docker build。
2. **L1 Docker layers**：固定 base digest，使 apt/pip/uv、migrate、DuckDB 等稳定层
   在输入不变时命中。
3. **L2 Go module cache**：所有 Go 命令使用同一稳定 cache ID 和
   `/go/pkg/mod`，`sharing=locked`。
4. **L3 Go build cache**：`go run cmd/download/duckdb` 与 `make build-prod`
   使用按 Linux ARM64、Go 和 CGO contract 区分的 `/root/.cache/go-build`，
   `sharing=locked`。

L2/L3 的 cache ID 必须由同一版本化函数生成，两个 Go `RUN` 不得各自拼装。唯一一次
合法 D2 build 中，第一个 Go `RUN` 在完成后写入非秘密探针并确认 cache 非空；后一个
Go `RUN` 在编译前必须以同一 cache ID 读到该探针和非空 cache。证据只记录 cache ID、
target、命中与非空状态，不收集缓存内容本身。这样无需第二次镜像构建，也能证明两个
阶段确实共享同一持久 cache，而不是只在 Dockerfile 中出现了两条 mount 声明。

正常任务不得执行全局 `docker builder prune` 或 `go clean -cache`。磁盘压力必须先
报告精确占用，再由总控执行有界清理；缓存被清理只允许导致下一次变慢，不能改变
identity、镜像内容或验收结论。

### 4.5 稳定元数据

- `BUILD_TIME` 使用 build-source commit timestamp 或对应的
  `SOURCE_DATE_EPOCH`，不使用调用时墙钟；
- `GO_VERSION` 使用 Linux builder 内真实值，不使用 Mac 宿主值；
- `VERSION`、`COMMIT_ID` 和其他有效 ldflags 必须由冻结 build source 确定；
-运行编号、操作者和当前时间属于 provenance/Evidence，不进入会破坏编译缓存的
- 运行编号、操作者和当前时间属于 provenance/Evidence，不进入会破坏编译缓存的
  二进制输入。

### 4.6 冷构建的外部依赖锁

固定 base digest 仍不足以让冷构建可重放，因为当前 Dockerfile 还会执行可变的
`apt-get update/install` 和无版本的 `pip install --upgrade`。BA0 不建设新的 builder
base，但必须用一个受版本控制的依赖锁把这些解析结果冻结：

- Debian 使用固定 snapshot/Release 身份，并锁定实际安装包版本；
- Python 构建工具固定版本和校验值，禁止无界 `--upgrade`；
- DuckDB、uv 等网络下载继续固定版本、来源、平台和内容校验；
- mirror、代理地址和凭据不进入公开 identity；真正影响输出的非秘密解析结果进入锁与
  identity；
- 锁发生变化就是新 identity；固定 Colima 被删除后可进行一次冷构建，但不得在同一
  identity 下静默解析出另一组依赖。

若依赖锁无法解析或校验，必须在 build 前/对应下载 step fail closed，不能退回浮动源。

### 4.7 D2 与 D3

- D0：只做文档和静态合同验证，Docker action 为 `SKIP`；
- D1：focused tests 和受影响 package 验证，不构建镜像；
- D2：唯一总控在固定 Colima 上执行一次 lookup；hit 为 `REUSE`，miss 才允许一次
  `BUILD_AFFECTED`；
- D3：使用 D2 的 exact image identity，以 `--no-build --pull never` 启动隔离环境。

不得复用当前 `start_all.sh --no-pull` 代表 D3。实施应增加语义明确的 exact-image
入口，或由 D3 runbook 直接调用等价 compose 命令；不得悄悄改变普通开发者现有
`--no-pull` 语义。

## 5. 错误处理与可观测性

1. **Identity 不可计算**：停止在 build 前；不得降级为按 Git SHA 或 tag 构建。
2. **Exact hit 不一致**：停止并报告所有冲突 image ID；不得自动选择。
3. **缓存 miss**：只表示需要执行编译，不表示合同失败。
4. **缓存丢失**：允许一次冷构建恢复；不从旧 receipt 推断缓存仍存在。
5. **网络不可用**：exact hit 必须仍可复用；miss 且所需依赖未缓存时明确失败，禁止
   使用不匹配镜像绕过。
6. **长步骤**：依据实际日志增长、BuildKit step 状态、CPU、内存、磁盘和当前总时间盒
   判断是否仍有进展；确认无进展则停止，有真实进展可在总时间盒内继续。不得预写固定
   分钟数把仍在推进的合法编译误判为卡死。
7. **Colima 探针**：固定 profile、Docker context 和正确的 Colima/Lima home；客户端
   中断后先按 tag、BuildKit job 和 daemon 状态复核，禁止直接宣布 VM 丢失并重建。

## 6. 测试与验收

### 6.1 先行 RED

本设计经用户书面确认后，必须先冻结一个紧凑中文 OpenSpec，使用稳定
Requirement ID 覆盖 exact lookup、Go build cache、稳定 metadata 和 D3 no-build。
OpenSpec 验证通过后，才允许写 focused RED；顺序固定为：

```text
Goal/authority → compact OpenSpec → RED → implementation → validation
```

RED 必须证明旧实现至少存在以下失败：

- 相同 identity 会进入 Docker build；
- build time 随墙钟变化；
- Go build cache 未挂载；
- D3 路径仍可能带 `--build`；
- app input manifest 漏掉已知实际依赖时验证失败。

测试通过 fake Docker/process runner 证明控制流，不用真实构建冒充单元测试。

### 6.2 实际构建预算

本次最多执行一次真实 app image build：

1. **缓存初始化构建**：Dockerfile/构建合同改变后形成一个新 identity，允许一次
   BUILD_AFFECTED。该次可能仍接近冷构建，只记录事实，不为追求统计重复执行。

在初始化构建后，必须另执行一次相同 identity 的**构建请求**，但它必须在 lookup
阶段直接返回，因此不计真实 build，且 Docker build invocation 为 `0`。

不得创建临时源码 identity 并构建第二个探针镜像。Go 增量编译耗时留到 G2 或后续
第一个自然、获授权的新 app identity 的 D2 build 观测；此前明确记录
`NOT_MEASURED + reason`。这不降低本轮对 cache mount 持久性、exact reuse 和 D3
no-build 的硬验收。

### 6.3 硬验收与性能观察目标

- G1 的 `109m18s` business compile 作为 before 基线；不再主动清缓存复测冷构建；
- same identity 的唯一硬门是 Docker build invocation=`0` 且返回同一 image identity；
- miss 的唯一硬门是最多一次 `BUILD_AFFECTED`；
- D3 的唯一构建硬门是 build invocation=`0`、pull invocation=`0`；
- `60s` 的 exact lookup 和 `30m` 的自然增量编译只是观察目标，不是 BA0 PASS
  的预写死门槛；样本不足时记录 `NOT_MEASURED + reason`；
-第一个自然增量样本若明显偏离目标，按当时 BuildKit step、cache hit/miss 和 G1
  基线决定是否授权一次有界纠偏，不得自动叠加 builder-base 等方案。

这些性能观察目标只用于固定 Mac/Colima 的当前资源配置，不外推到 CI 或其他主机，
也不作为 BA0 的 PASS/FAIL 门槛。

### 6.4 BA0 Definition of Done

以下条件必须同时成立：

1. G1 closeout 仍可重算为 `PASS`，其历史 Evidence 未被改写；
2. Go module 与 Go build cache 均在固定 Colima 中持久化；两个 Go `RUN` 使用同一稳定
   cache ID，且后一步能观察到前一步产生的非空 cache 状态；
3. builder/runtime base digest、Debian/Python 外部依赖锁与稳定 build metadata 生效；
4. identity manifest 覆盖已知真实 app 输入，focused tests 通过；
5. 一个新 identity 只构建一次并绑定不可变 image identity；
6. 第二次相同 identity 请求不调用 Docker build并返回相同 image identity；
7. 初始化构建后可证明 Go cache mount 持续存在且未被清理；自然增量样本尚不存在时
   明确记录 `NOT_MEASURED + reason`；
8. D3 exact-image 启动日志中没有 build/pull，健康检查通过；
9. Provider/model、生产 `8081`、生产 Active、业务数据库和 G2 effects 均为 `0`；
10. 独立 reviewer 对冻结 commit/tree、测试和 Evidence Pack 给出 `PASS`；
11. 最终报告记录 before/after、cache hit/miss、构建调用数、image identity、
    integration/build-source identity 和剩余风险。

只有代码、控制流测试或缓存目录存在，均不足以宣称 BA0 PASS。

## 7. 文档与资产范围

实施阶段只允许同步：

- `HANDOFF.md`：G1 PASS、BA0 current state、G2 lock 和最终 Evidence 指针；
- `docs/insurance-kb/28-development-execution-charter-830.md`：lookup-before-build、
  缓存丢失语义、D3 no-build；
- `docs/insurance-kb/29-goal-cards-830.md`：一张简短 BA0 工程维护卡及当前状态；
-本设计、一个紧凑中文 OpenSpec、后续实施计划、focused tests 与 BA0 Evidence Pack；
-为完成上述合同所需的最小 Dockerfile、构建脚本和本地启动脚本。

不修改 `docs/insurance-kb/02-architecture.md`、历史
`docs/insurance-kb/16-roadmap.md`，不建立大型或平行 OpenSpec。BA0 的紧凑 OpenSpec
是行为改动的唯一 Requirement authority；实施 RED 若发现其无法表达一个真实必要行为，
必须先停下修订同一 OpenSpec，不得另起 successor。

## 8. 预计工期

-规格确认、RED 与实现：`4–6` 小时；
-缓存初始化构建：可能接近 G1 冷构建，预计约 `2` 小时；
-same-identity 复用验证与证据整理：预计 `1–2` 小时；
-独立复核和收尾：`1–2` 小时。

正常预计 `1` 个工作日；若首次初始化遇到网络、Colima 或依赖异常，最多时间盒为
`2` 个工作日。超过时间盒仍未满足 DoD，必须停止并报告，不得通过新增前置继续延长。
