# 830 BA0 本地构建复用实施计划

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> **Status:** 2026-09-04 independent plan review PASS；仅待用户明确授权 BA0 implementation。

**Goal:** 在固定 g1-build Colima 上实现 app 镜像 lookup-before-build、持久 Go 编译缓存与 exact-image 制品自检，使同一 artifact identity 的第二次请求不调用 Docker build。

**Architecture:** scripts/build_images.sh --app 仍是唯一公共构建入口；一个 Python 标准库 helper 负责 canonical identity、local inspect、REUSE/BUILD_AFFECTED 选择和最小回执。D3 只做无网络、无端口、无依赖、只读的 CONTAINER_ARTIFACT_SMOKE，不再为了验证构建复用启动另一套业务数据库。BA0 不改变 WeKnora/Harness 产品架构、产品 Goal 顺序或 G2 DoD。

**Tech Stack:** Bash、Python 3.12 标准库、pytest、Docker BuildKit/Compose、Go、OpenSpec Markdown、JSON Evidence Pack。

---

## 0. 执行授权与硬边界

当前状态是 PLAN_READY_AWAIT_EXECUTION_AUTHORIZATION。文档合入不自动授权实现。用户明确启动 BA0 后，执行者先用 superpowers:using-git-worktrees，从包含本计划的最新干净 origin/main，在 LLM_wiki 项目内创建 worktree。

固定约束：

- PRODUCT_GOAL_ORDER=B0→G1→G2→...；BA0 是工程门，不计产品进度。
- 产品 WIP=0，BA0 工程 WIP=1；G2 始终锁定到 BA0 PASS 后用户另行授权。
- Provider/model、生产 8081、生产 Active、业务数据库和 G2 effects 均为 0。
- 最多一次真实 app image build；第二个同 identity 请求必须 build=0。
- 不清 cache、不制造冷构建、不建 CI/remote cache/数据库/制品服务/基础镜像产品线。
- 性能分钟数只观测，不是 PASS 门；无自然增量样本写 NOT_MEASURED + reason。
- 第二层前置、新服务、新表、第二构建 authority 或第二次真实 build 请求均立即 STOP。
- 每个 Task focused test GREEN 后立即提交，不积累大批未提交代码。

已验证测试解释器：

    /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python3.12

开始前运行其 -m pytest --version。路径失效就停止报告，不在 BA0 临时安装另一套 Python/uv。
OpenSpec 1.2.0 固定入口为 /Users/houjing/.nvm/versions/node/v24.13.1/bin/openspec；路径或版本不符就停止，不联网安装替代工具。

## Task 1：紧凑中文 OpenSpec 与原子状态切换

**Files:**

- Create: openspec/changes/127-830-ba0-local-build-reuse/proposal.md
- Create: openspec/changes/127-830-ba0-local-build-reuse/tasks.md
- Create: openspec/changes/127-830-ba0-local-build-reuse/specs/local-build-reuse/spec.md
- Create: openspec/changes/127-830-ba0-local-build-reuse/validation-report.md
- Modify: openspec/changes/README.md
- Modify: AGENTS.md
- Modify: HANDOFF.md
- Modify: jlx_enterprise_llm_wiki_technical_blueprint_830.md (§0 only)
- Modify: docs/insurance-kb/28-development-execution-charter-830.md (header only)
- Modify: docs/insurance-kb/29-goal-cards-830.md (header/BA0 card only)

**Steps:**

1. RED：运行以下命令，预期因 change 不存在而 FAIL：

       OPENSPEC_TELEMETRY=0 /Users/houjing/.nvm/versions/node/v24.13.1/bin/openspec validate 127-830-ba0-local-build-reuse --strict
2. 写中文规格，只冻结 BA0-REQ-01 至 06：完整 identity、exact hit build=0/miss≤1、稳定 metadata/共享 Go cache、版本化依赖事实、D3 artifact smoke build/pull=0、一次 build/effects=0/STOP。
3. 不写 G2、远端 cache、第二平台或性能硬 SLA。
4. 原子把五个当前状态面切为 BA0_ONLY；不能只改 HANDOFF。冻结 base commit/tree、worktree、Owner；G2 保持锁定。
5. 验证：

       test -f openspec/changes/127-830-ba0-local-build-reuse/specs/local-build-reuse/spec.md
       rg -n '^### Requirement: BA0-REQ-0[1-6]' openspec/changes/127-830-ba0-local-build-reuse/specs/local-build-reuse/spec.md
       OPENSPEC_TELEMETRY=0 /Users/houjing/.nvm/versions/node/v24.13.1/bin/openspec validate 127-830-ba0-local-build-reuse --strict
       git diff --check

6. Commit:

       git add openspec/changes/127-830-ba0-local-build-reuse openspec/changes/README.md AGENTS.md HANDOFF.md jlx_enterprise_llm_wiki_technical_blueprint_830.md docs/insurance-kb/28-development-execution-charter-830.md docs/insurance-kb/29-goal-cards-830.md
       git commit -m "spec(BA0): freeze local app build reuse contract"

## Task 2：先写完整 RED，并通过 YELLOW 范围门

**Files:**

- Create: harness/tests/test_local_app_build_830_ba0.py
- Create: cmd/download/duckdb/duckdb_test.go

**Steps:**

1. Python 测试用 injected fake runner 冻结：
   - manifest/identity 稳定、输入变化敏感、已知闭包不漏；
   - 稳定时间、builder Go、不泄密；
   - hit=0、miss=1、冲突/label/OS/arch/inspect fail closed；
   - 两个 Go RUN 共享 module/build cache；
   - Makefile 无第二裸 build；
   - standalone D3 config 与事件顺序。
2. 先写具名 Go 测试 TestLockedExtensionOrigin、TestLockedExtensionPlatform、TestLockedExtensionDigestRejectsTampering；不得用“零测试匹配”冒充 RED。
3. RED：

       cd harness
       PYTHONPATH="$PWD/src" /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python3.12 -m pytest -q tests/test_local_app_build_830_ba0.py
       cd ..
       GOCACHE=/private/tmp/weknora-ba0-go-cache go test ./cmd/download/duckdb -run '^TestLocked' -count=1 -v

   Expected: 两条均因缺实现而 FAIL。
4. Commit RED。
5. 只读 reviewer 在生产修改前确认 YELLOW：范围仍限本计划、没有 RED 级新服务/表/平台、build budget=1、D3 不接业务数据。非 PASS 则停止。

## Task 3：先冻结有界外部依赖事实

**Files:**

- Create: deploy/local-build/app-external-dependencies.v1.json
- Modify: harness/tests/test_local_app_build_830_ba0.py

**Steps:**

1. 运行 dependency_lock RED。
2. 在 60 分钟内，从受信 G1 镜像/缓存和上游清单核验 builder/runtime manifest digest、Debian snapshot/Release 与实际包版本、pip/setuptools/wheel 版本/校验、DuckDB extension 的版本/平台/来源/content SHA-256。
3. mirror/proxy/credential 不入锁；未经 inspect 的 digest 不得抄入。一次解析仍无法证明任一关键事实就 STOP，不试建镜像、不造通用锁平台。
4. GREEN：

       cd harness
       PYTHONPATH="$PWD/src" /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python3.12 -m pytest -q tests/test_local_app_build_830_ba0.py -k dependency_lock

5. Commit: build(BA0): freeze local app dependency inputs

## Task 4：versioned input manifest 与 canonical identity

**Files:**

- Create: deploy/local-build/app-build-inputs.v1.json
- Create: scripts/app_artifact.py
- Modify: harness/tests/test_local_app_build_830_ba0.py

**Steps:**

1. RED：运行 -k "manifest or identity or docs_only_head"。
2. manifest 描述真实输出输入：Go entrypoints/internal deps/go:embed、go.mod/sum、Dockerfile/.dockerignore、Makefile/version/build entry、最终 COPY 的 config/scripts/migrations/samples/preloaded skills、docreader/client、deploy/upstream 和 Task 3 lock。
3. helper 只用标准库并提供 load_manifest、resolve_inputs、canonical_identity；closed schema、路径排序、SHA-256、禁止越仓、缺文件或 unresolved Go dependency fail closed。
4. identity 包含 manifest/lock hash、target/platform/CGO、builder/runtime digest、有效 build args 与显式 D2 build-source metadata；不含 cache、当前 integration HEAD、运行时间、运行号或操作者。
5. helper 要求调用方显式给出 build-source head，并验证当前工作树的全部 manifest 输入与该 commit 一致；docs-only integration commit 不得改变 identity，任一 app input 漂移必须 fail closed。
6. GREEN：

       cd harness
       PYTHONPATH="$PWD/src" /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python3.12 -m pytest -q tests/test_local_app_build_830_ba0.py -k 'manifest or identity or docs_only_head'

7. Commit: feat(BA0): add canonical app artifact identity

## Task 5：稳定元数据、锁定依赖并共享 Go cache

**Files:**

- Modify: scripts/get_version.sh
- Modify: scripts/build_images.sh (只统一 metadata，暂不接 selector)
- Modify: docker/Dockerfile.app
- Modify: cmd/download/duckdb/duckdb.go
- Modify: harness/tests/test_local_app_build_830_ba0.py

**Steps:**

1. RED：运行 -k "metadata or dockerfile or cache_probe or builder_go_version" 和具名 Go tests。
2. BUILD_TIME 来自 SOURCE_DATE_EPOCH 或 build-source commit timestamp；运行时间只进 provenance。
3. 两个 FROM、apt、pip 只消费 Task 3 lock；禁止 mutable/unbounded fallback。
4. 两个 Go RUN 用同一稳定 cache-ID 函数挂载 /go/pkg/mod 与 /root/.cache/go-build，sharing=locked，ID 不含 source SHA。第一 RUN 写非秘密 probe/确认非空，第二 RUN 读取。
5. builder 内取得真实 go version 注入 ldflags；DuckDB 校验 locked origin/platform/hash。
6. 不大拆 COPY . .，本任务不切换公共 selector。
7. GREEN：

       cd harness
       PYTHONPATH="$PWD/src" /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python3.12 -m pytest -q tests/test_local_app_build_830_ba0.py -k 'metadata or dockerfile or cache_probe or builder_go_version'
       cd ..
       GOCACHE=/private/tmp/weknora-ba0-go-cache go test ./cmd/download/duckdb -run '^TestLocked' -count=1 -v

8. Commit: build(BA0): stabilize inputs and persist Go caches

## Task 6：lookup-before-build 与唯一公共入口

**Files:**

- Modify: scripts/app_artifact.py
- Modify: scripts/build_images.sh
- Modify: Makefile
- Modify: harness/tests/test_local_app_build_830_ba0.py

**Steps:**

1. RED：运行 -k "lookup or selector or conflicting_hit or secret or public_entry"。
2. helper 所有 Docker 命令显式使用 --context colima-g1-build。按 identity label 查找并 inspect：唯一 image ID、linux/arm64、identity/build-source label 均匹配才 REUSE。
3. exact hit build=0；miss 最多一次 BUILD_AFFECTED；不同 image ID 冲突或 inspect 异常停止。不得按 latest/创建时间兜底。
4. scripts/build_images.sh --app 在核心全部 GREEN 后接 helper，要求显式
   --build-source-head SHA 并支持 --evidence-out；Makefile 只委托该入口。
5. receipt 区分 current integration head、build-source head、image ID、selector/build count；secret 不进 argv/label/receipt。
6. GREEN 运行该测试筛选及 git diff --check。
7. Commit: feat(BA0): reuse exact local app artifact before build

## Task 7：D3 standalone exact-image 制品自检

**Files:**

- Create: deploy/local-build/docker-compose.app-exact.yml
- Create: scripts/start_exact_image.py
- Modify: harness/tests/test_local_app_build_830_ba0.py

**Steps:**

1. RED：运行 -k d3_exact_image。
2. standalone Compose 只含 app-smoke：
   - image 直接取 D2 receipt 的 sha256 image ID，pull_policy=never，无 build；
   - network_mode=none；无 port、volume、container_name、env_file、depends_on；
   - read_only=true、tmpfs=/tmp、AUTO_MIGRATE=false；
   - 覆盖 entrypoint，只读检查 /app/WeKnora 可执行、必要文件存在、ldd 无 missing dependency，然后保持进程；healthcheck 只验证这些条件。
3. start_exact_image.py 的 fake-runner 顺序固定：receipt→image inspect/labels/OS/arch→compose config→静态拓扑验证→project collision check→up→runtime .Image/health inspect→cleanup→receipt。任一 preflight 失败 mutation=0。
4. exact argv 固定为：

       docker --context colima-g1-build compose --project-name insurancekb-ba0-d3-<nonce> --env-file <0600-temp-env> -f deploy/local-build/docker-compose.app-exact.yml config --format json
       docker --context colima-g1-build compose --project-name insurancekb-ba0-d3-<nonce> --env-file <same> -f deploy/local-build/docker-compose.app-exact.yml up -d --wait --wait-timeout 30 --no-build --pull never app-smoke

5. 这只证明 CONTAINER_ARTIFACT_SMOKE，不宣称 WeKnora HTTP health；不得复用 base compose、local-live override、G1 clone 或 start_all.sh。
6. GREEN 运行测试筛选及 git diff --check。
7. Commit: feat(BA0): add exact image artifact smoke

## Task 8：最小 Evidence Pack 验证器

**Files:**

- Create: docs/insurance-kb/evidence/830-ba0/README.md
- Create: docs/insurance-kb/evidence/830-ba0/tools/verify_ba0_evidence.py
- Create: harness/tests/test_ba0_evidence_pack_830.py

**Steps:**

1. RED：运行新测试；它必须因 verifier 缺失/不完整而失败。
2. 复用 B0 canonical JSON/self-hash 模式，不复制 B0 Goal/branch 常量，不建通用平台。
3. 验证 manifest/lock hash、implementation/build-source/integration 身份区分、第一请求 build≤1、第二请求 build=0 且 image ID 相同、cache probe、D3 build/pull=0、artifact smoke、G1 历史未改、production/Provider/G2 effects=0、NOT_MEASURED reason。
4. GREEN：

       cd harness
       PYTHONPATH="$PWD/src" /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python3.12 -m pytest -q tests/test_ba0_evidence_pack_830.py

5. Commit: test(BA0): add verifiable local build evidence pack

## Task 9：D0/D1 前门

**Files:**

- Modify: openspec/changes/127-830-ba0-local-build-reuse/validation-report.md

**Steps:**

1. 运行全部 focused Python、具名 Go tests、OpenSpec strict validate、链接检查和 diff/status；不得构建镜像：

       cd harness
       PYTHONPATH="$PWD/src" /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python3.12 -m pytest -q tests/test_local_app_build_830_ba0.py tests/test_ba0_evidence_pack_830.py
       cd ..
       GOCACHE=/private/tmp/weknora-ba0-go-cache go test ./cmd/download/duckdb -run '^TestLocked' -count=1 -v
       OPENSPEC_TELEMETRY=0 /Users/houjing/.nvm/versions/node/v24.13.1/bin/openspec validate 127-830-ba0-local-build-reuse --strict
       git diff --check
       git status --short

2. 取当前代码提交为 IMPLEMENTATION_HEAD/TREE 和 D2_BUILD_SOURCE_HEAD；从此冻结该 SHA。
   helper 必须证明当前 manifest 输入与该 commit 一致。随后只允许 validation/Evidence 状态文档改变；
   任一 app input 再变化必须回到 D0/D1 并重新冻结，且仍不得增加真实 build 预算。
3. 记录 identity/lock hash、fixed context/profile、资源状态和 REAL_APP_BUILD_BUDGET_REMAINING=1。
4. 只读 reviewer 确认无 G2/Provider/生产 effects、无第二 build 入口、无 prune、standalone smoke 拓扑严格。
5. validation report 写 D0_D1_PASS / D2_AWAITING_SINGLE_BUILD_AUTHORIZATION。该 report 不声称自证包含自己的提交。
6. Commit: docs(BA0): record pre-build validation gate

## Task 10：唯一 D2、零构建复用与 artifact smoke

**Files:**

- Create: docs/insurance-kb/evidence/830-ba0/d2/initialization-build.json
- Create: docs/insurance-kb/evidence/830-ba0/d2/same-identity-reuse.json
- Create: docs/insurance-kb/evidence/830-ba0/d3/exact-image-smoke.json
- Create: docs/insurance-kb/evidence/830-ba0/ba0-closeout.json
- Modify: openspec/changes/127-830-ba0-local-build-reuse/validation-report.md

**Steps:**

1. 第一个请求：

       ./scripts/build_images.sh --app --build-source-head <D2_BUILD_SOURCE_HEAD> --evidence-out docs/insurance-kb/evidence/830-ba0/d2/initialization-build.json

   Expected: miss 时 BUILD_AFFECTED/build=1；已有合格 exact hit 时 REUSE/build=0；绝不超过 1。
2. 使用同一 D2_BUILD_SOURCE_HEAD 原样第二次请求到 same-identity-reuse.json。Expected:
   REUSE、build=0、identity/image ID 与第一请求一致。若调用 build，立即 FAIL，无第三次机会。

       ./scripts/build_images.sh --app --build-source-head <D2_BUILD_SOURCE_HEAD> --evidence-out docs/insurance-kb/evidence/830-ba0/d2/same-identity-reuse.json
3. D3：

       /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python3.12 scripts/start_exact_image.py --d2-receipt docs/insurance-kb/evidence/830-ba0/d2/same-identity-reuse.json --evidence-out docs/insurance-kb/evidence/830-ba0/d3/exact-image-smoke.json

   Expected: artifact smoke PASS、runtime image ID 相同、build=0、pull=0、网络/端口/生产/业务 DB effects=0。
4. 运行
   /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python3.12
   docs/insurance-kb/evidence/830-ba0/tools/verify_ba0_evidence.py。自然增量不存在则写
   NOT_MEASURED + reason，不制造新 identity。
5. Commit evidence。长 build 按日志/BuildKit/资源判断是否推进，不按固定分钟重启。

## Task 11：独立复核、原子关闭并返回用户

**Files:**

- Modify: AGENTS.md
- Modify: HANDOFF.md
- Modify: jlx_enterprise_llm_wiki_technical_blueprint_830.md
- Modify: docs/insurance-kb/28-development-execution-charter-830.md
- Modify: docs/insurance-kb/29-goal-cards-830.md
- Modify: openspec/changes/127-830-ba0-local-build-reuse/validation-report.md
- Modify: docs/insurance-kb/evidence/830-ba0/ba0-closeout.json

**Steps:**

1. 使用 superpowers:requesting-code-review，给 reviewer frozen base/head、OpenSpec、tests、D2/D3 receipts、effects=0。必须核对 build≤1、reuse build=0、smoke build/pull=0、identity 完整、secret 不泄露、cache 非 authority、G1 未改、G2 未动。
2. blocker 只允许同卡一次最小修复并重跑受影响验证；不得新增 successor。
3. 终态重跑 focused Python、具名 Go、Evidence verifier、Requirement ID/链接与 diff 检查。
4. 同一提交原子同步五个当前状态面：

       G1_STATUS=PASS
       BA0_STATUS=PASS
       CURRENT_AUTHORIZATION=NONE
       CURRENT_PRODUCT_GOAL=NONE
       G2_STATUS=LOCKED_PENDING_EXPLICIT_USER_AUTHORIZATION
       NEXT_ACTION=RETURN_TO_USER_FOR_G2_AUTHORIZATION

5. closeout 区分 IMPLEMENTATION_HEAD/TREE、D2_BUILD_SOURCE_HEAD/TREE、执行时 integration head 和 image ID；不得自引用尚未产生的最终提交。最终 branch head 在提交后通过报告/PR 记录。
6. Commit: docs(BA0): close local build reuse engineering gate
7. 使用 superpowers:finishing-a-development-branch 报告集成选项，然后停止；不得创建 G2 worktree/OpenSpec、任务或环境。

## 时间盒

- OpenSpec、RED、YELLOW：约 1 小时；
- 依赖锁、实现、focused tests：约 4–6 小时；
- 唯一真实 build：miss 时可能接近 G1 的约 2 小时；
- reuse/smoke/复核/收尾：约 1–2 小时。

目标 1 个工作日，最多 2 个工作日。超时、依赖锁无界化、同一阻断第二次纠偏或 build 预算将超过 1 时立即 STOP/RETURN_TO_USER。
