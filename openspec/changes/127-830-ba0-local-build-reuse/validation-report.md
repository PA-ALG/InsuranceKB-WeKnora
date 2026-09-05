# 127 · Validation Report

## Current identity

```text
CURRENT_AUTHORIZATION=NONE
CURRENT_PRODUCT_GOAL=NONE
CURRENT_ENGINEERING_GATE=BA0_LOCAL_BUILD_REUSE
BA0_KIND=ENGINEERING_GATE_NOT_PRODUCT_GOAL
BA0_STATUS=PASS
G1_STATUS=PASS
G2_STATUS=LOCKED_PENDING_EXPLICIT_USER_AUTHORIZATION
ORIGIN_MAIN_BASE=0e7a26568a2164f9501e409f38fee0d4a62539cb
ORIGIN_MAIN_TREE=b96aa35fd2fe86283757deb258920c489de4b4b6
IMPLEMENTATION_BASE=874e50d44aec5941faae045e761280aa69aee1a3
IMPLEMENTATION_BASE_TREE=2ec76af38258a0220d5dc117a9b789890345e7d7
WORKTREE=/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-ba0-implementation
BRANCH=codex/830-ba0-implementation
OWNER=830-BA0总控
TASK1_RED=OPENSPEC_CHANGE_MISSING_CAPTURED
D0_D1_STATUS=PASS
CURRENT_RED=NONE
NEXT_PHYSICAL_RESULT=RETURN_TO_USER_FOR_G2_AUTHORIZATION
NEXT_ACTION=RETURN_TO_USER_FOR_G2_AUTHORIZATION
REAL_APP_BUILD_BUDGET=2
REAL_APP_BUILDS_USED=2
REAL_APP_BUILD_BUDGET_REMAINING=0
IMPLEMENTATION_HEAD=fe9a97d092fbb470985bf32c5c4e5a9e6ec135c9
IMPLEMENTATION_TREE=c4843cfb4c6949900e47a2a57af6493011dc8fda
D2_BUILD_SOURCE_HEAD=fe9a97d092fbb470985bf32c5c4e5a9e6ec135c9
D2_BUILD_SOURCE_TREE=c4843cfb4c6949900e47a2a57af6493011dc8fda
APP_ARTIFACT_IDENTITY=sha256:afbc7c23f072459b3fa1f786b7f13dcedb47a6437ba5b69f9fb38f2fbb2e2235
APP_MANIFEST_SHA256=4433d74442d07ff2a172c0e2079954a2f53fe01009fe1be094dd793abc803e87
APP_DEPENDENCY_LOCK_SHA256=681026d97cc7a7f4c6c31c324e7a0faec6a1aae316455804fedffdf19ef65258
DOCKER_CONTEXT=colima-g1-build
COLIMA_PROFILE=g1-build
PROVIDER_MODEL_EFFECTS=0
PRODUCTION_8081_EFFECTS=0
PRODUCTION_ACTIVE_EFFECTS=0
BUSINESS_DB_EFFECTS=0
G2_EFFECTS=0
```

## Task 10 · Recovery D2/D3 (2026-09-05)

用户“继续授权，执行”批准 wheel 文件名修复和新增一次真实构建。历史失败 1 次加本轮
成功 1 次，累计 2/2；授权与原失败收据见
[recovery-authorization.md](../../../docs/insurance-kb/evidence/830-ba0/recovery-authorization.md)。
该修订只增加一次恢复预算，不改变 G2 或业务授权。

- 修复提交与 build source：`fe9a97d092fbb470985bf32c5c4e5a9e6ec135c9`；
  tree `c4843cfb4c6949900e47a2a57af6493011dc8fda`。
- RED：真实 wheel 文件名解析器拒绝旧名称；GREEN：123 focused Python tests PASS。
- 独立修复审查 PASS，12 处 download/hash/install 路径与锁定 origin 完全匹配。
- D2 初始化：PASS / BUILD_AFFECTED / build=1；同身份复用：PASS / REUSE / build=0。
  复用直接调用同一 selector API 并设置 remaining budget=0，避免 CLI 默认额度允许新构建。
- D3：CONTAINER_ARTIFACT_SMOKE PASS / build=0 / pull=0 / cleanup=PASS；九项 effects=0。
- Evidence verifier：PASS，真实重算 identity 与三张收据一致，G1 changed_paths=0。
- 独立 closeout 审查 PASS（冻结证据提交 `a3c5d22f3d0ca6005a03f0471113f03a8f25d94b`），
  无 BLOCKER。收尾重跑：123 focused Python PASS、三个 TestLocked PASS、OpenSpec strict PASS。
- BA0 终态 PASS，授权 NONE，返回用户；G2 仍锁定。HTTP health、业务验收与 GitHub live 未执行。

## Task 1 RED

在创建 change 前执行：

```text
OPENSPEC_TELEMETRY=0 /Users/houjing/.nvm/versions/node/v24.13.1/bin/openspec validate 127-830-ba0-local-build-reuse --strict
exit=1
Unknown item '127-830-ba0-local-build-reuse'
```

失败原因是目标 change 尚不存在，符合 Task 1 唯一允许的 missing-change RED；不是依赖、环境
或语法错误。RED 之后才创建本规格。

## Requirement matrix

| Requirement | Task 1 specification | Task 2 focused RED | Implementation / live | Status |
|---|---|---|---|---|
| BA0-REQ-01 | 完整可重算 identity 已冻结 | focused + 独立重算 PASS | D2 identity PASS | PASS |
| BA0-REQ-02 | hit=0 / 每个授权窗口 miss≤1 / conflict fail closed | fake-runner PASS | D2 build=1、reuse=0 | PASS |
| BA0-REQ-03 | 稳定 metadata 与两个 Go RUN 共享 cache | metadata/cache contract PASS | D2 PASS；速度 NOT_MEASURED | PASS |
| BA0-REQ-04 | versioned external dependency facts | lock/parser/Go locked tests PASS | 修复后 D2 PASS | PASS |
| BA0-REQ-05 | standalone exact-image artifact smoke | Compose/runner contract PASS | D3 artifact smoke PASS | PASS |
| BA0-REQ-06 | 追加授权累计≤2、每窗口≤1、effects=0 | budget/effects gate PASS | 历史1 + 恢复1；D3 effects=0 | PASS |

以下 Task 1 章节保留当时 D0 规格事实；当前 D2/D3 事实以上方 Task 10 与收据为准。
Task 1 未运行 Docker、Provider/model、数据库、生产 `8081`、生产 Active 或 G2 动作。

## Task 1 quality review correction

- 将 G1 已合入 `origin/main` 的 base/tree 与 BA0 implementation 起点 base/tree 分项冻结；
  `git rev-parse 874e50d44aec5941faae045e761280aa69aee1a3^{tree}` 返回
  `2ec76af38258a0220d5dc117a9b789890345e7d7`。
- 冻结秘密/凭据不得进入 argv、日志、image label、receipt 或公开 identity，并要求 canary
  secret 在 fake-runner trace 与全部公开输出中为零命中。
- 将 candidate set 定义为排序去重的确定性 image ID 集合；零候选、唯一完整候选、非空无效或
  冲突候选三类互斥，只有零候选允许至多一次 build。
- 明确定义同一阻断最多一次有界单变量纠偏、第二层前置 `A→B→计划外 C` 与最大 2 工作日 STOP。

## Task 1 GREEN

quality review correction 全部落盘后执行以下命令，均通过：

| Check | Exit | Result |
|---|---:|---|
| `test -f openspec/changes/127-830-ba0-local-build-reuse/specs/local-build-reuse/spec.md` | 0 | PASS |
| `rg -n '^### Requirement: BA0-REQ-0[1-6]' openspec/changes/127-830-ba0-local-build-reuse/specs/local-build-reuse/spec.md` | 0 | PASS；恰好列出 01..06 |
| `OPENSPEC_TELEMETRY=0 /Users/houjing/.nvm/versions/node/v24.13.1/bin/openspec validate 127-830-ba0-local-build-reuse --strict` | 0 | `Change '127-830-ba0-local-build-reuse' is valid` |
| `git diff --check` | 0 | PASS |

报告补记后再次执行同一组检查；最终结果仍以交接消息记录的退出码为准。Task 1 当时的下一
物理结果仅为 `TASK_2_COMPLETE_RED_AND_YELLOW_SCOPE_GATE`。

## Task 9 · D0/D1 pre-build gate

Task 2–8 的实现与独立纠偏提交完成后，将当前代码提交
`869c9fef6badbcd3f789caa3a4bd53977499b594` / tree
`0ee4bb0302cce554093f959b256ab8ef8e443f69` 同时冻结为 `IMPLEMENTATION_HEAD/TREE` 与
`D2_BUILD_SOURCE_HEAD/TREE`。后续只允许 validation/Evidence 状态文档变化；任何 app manifest
输入变化都必须回到 D0/D1，且不会增加真实 build 预算。本报告包含自身的提交尚未产生，因此
不声称自证最终 branch head。

冻结 build source 的 canonical 重算结果：

```text
APP_ARTIFACT_IDENTITY=sha256:7c1c1891365c74b41fdb120278bf6d240f767a18bc54e1e8df72f191b3d30255
APP_MANIFEST_SHA256=4433d74442d07ff2a172c0e2079954a2f53fe01009fe1be094dd793abc803e87
APP_DEPENDENCY_LOCK_SHA256=681026d97cc7a7f4c6c31c324e7a0faec6a1aae316455804fedffdf19ef65258
BUILD_SOURCE_VERSION=0.7.1
BUILD_SOURCE_DATE_EPOCH=1788532083
BUILD_SOURCE_TIME=2026-09-04 14:28:03 UTC
TARGET=runtime
PLATFORM=linux/arm64
```

固定 Docker context 的只读 preflight 为 `colima-g1-build`，context 描述为
`colima [profile=g1-build]`。daemon 只读 `docker info` 返回 `linux/aarch64`、4 CPU、
8308088832 bytes RAM、`io.containerd.snapshotter.v1`。`aarch64` 是 daemon 的原始架构文本；
镜像合同仍固定为 `linux/arm64`。本步骤只执行 context/info 查询，没有 build、pull、container、
network 或 volume mutation。

| Check | Exit | Result |
|---|---:|---|
| focused Python 两文件 | 0 | PASS；122 passed |
| `go test ./cmd/download/duckdb -run '^TestLocked' -count=1 -v` | 0 | PASS；3 named tests |
| OpenSpec strict validate | 0 | PASS |
| BA0 authority 文档本地 Markdown links | 0 | PASS |
| canonical identity 重算与 origin/main ancestry/tree | 0 | PASS |
| `git diff --check` / pre-report `git status --short` | 0 | PASS / clean |
| Task 9 独立只读 review | 0 | PASS；P0–P2=0 |

独立 reviewer 核对 exact frozen commit/tree/hash、唯一 app build authority、无 prune/destructive
命令、D3 strict standalone topology、build budget=1，并确认 G2、Provider/model、生产 `8081`、
生产 Active 与业务数据库 effects 均为 0。Task 9 终态为：

```text
D0_D1_STATUS=PASS
D2_STATUS=AWAITING_SINGLE_BUILD_AUTHORIZATION
REAL_APP_BUILDS_USED=0
REAL_APP_BUILD_BUDGET_REMAINING=1
CURRENT_RED=D2_AWAITING_SINGLE_BUILD_AUTHORIZATION
NEXT_PHYSICAL_RESULT=RUN_FIRST_EXACT_SELECTOR_REQUEST_WITH_BUILD_BUDGET_1
```

该门只允许 Task 10 按冻结 build source 发出第一个 exact selector 请求；不授权 G2 或任何业务
环境动作。
