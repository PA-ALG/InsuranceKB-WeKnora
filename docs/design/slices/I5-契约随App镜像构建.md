# I5 · 契约随 App 镜像构建，换装不再挂载契约目录

> 状态：Claude 2026-11-01 提出 ｜ 作者：Claude Code ｜ 实现方 Claude，审核方 Codex ｜ Issue #524
> 起因：#522 第 2 段 `--live` 被平台拒绝（首包 400 `CANDIDATE_INVALID`，`/origin` 校验失败），未激活任何 Release。
> 真实调用 0；不部署（部署另开 Issue）；不改 Go。

## 1. 问题与根因

平台在启动时从 `ENTERPRISE_CONTRACTS_DIR`（默认相对工作目录的 `contracts`）读取 `candidate_bundle.schema.json` 与
`evidence.schema.json`，用来校验候选包（`internal/enterprise/releasestore/production.go`）。App 镜像不带 `contracts/`
（`deploy/rehearsal/README.md` 发现 F1），于是：

- **线上**：`deploy/local-live/swap_app.py` 把运维私有目录里的 `contracts/` 只读挂载到 `/app/contracts`。这份目录是 10-16
  手工放进去的，此后换 App 时没有同步。平台用旧契约校验新代码产出的候选包：`identity_refresh` 来源、实体的 `lifecycle` /
  `product_family` 都不认识。
- **预发布**（`deploy/staging`）：照搬线上 App 的契约挂载，漂移原样复制过去。
- **演练**（`deploy/rehearsal`）：挂载演练用的仓库检出里的 `contracts/`，前提是检出与镜像是同一提交，否则同样漂移。

根因是契约有两份来源：二进制来自构建提交，契约来自另一处手工维护的目录，没有任何检查把两者绑定。

另有一处会让漂移在构建侧复现：`deploy/local-build/app-build-inputs.v1.json` 的 `required_paths` 不含 `contracts`，
制品身份（`artifact_identity`）不覆盖契约。契约进镜像后，如果只改了契约，`select-or-build` 会认为身份没变，直接复用
带旧契约的镜像。

## 2. 做法

契约只有一份来源，就是构建提交本身。

1. **镜像带契约**：`docker/Dockerfile.app` 的 `runtime` 阶段加一行 `COPY --from=builder /app/contracts ./contracts`，与
   `config`、`migrations` 同样从构建阶段复制。镜像工作目录是 `/app`，所以镜像内路径是 `/app/contracts`。
   `.dockerignore` 不排除 `contracts/`。
2. **身份覆盖契约**：`app-build-inputs.v1.json` 的 `required_paths` 加 `contracts`。改了契约，身份就变，从而重新构建。
3. **运行时复用不带旧契约**：`scripts/app_artifact.py` 的 `runtime_reuse_facts` 受保护路径加 `contracts`。复用的运行时底包
   与构建源之间契约有任何差异，就拒绝复用（`runtime-rebase` 阶段只换二进制，不刷新契约）。I5 之前的底包由于
   Dockerfile 的 `runtime` 阶段改了，复用本来就会被拒（`runtime dependency recipe changed`），只能全量构建。
4. **换装工具**（`deploy/local-live/swap_app.py`）：
   - 默认不再挂载契约。`ENTERPRISE_CONTRACTS_DIR` 仍设为 `/app/contracts`，指向镜像自带的那一份；路径不变，运行时环境的
     键名集合也不变。
   - 私有目录不再要求有 `contracts/`（只要 `config.yaml` 与 `secrets.env`）。
   - **新镜像先验契约**：动容器之前，用一次性容器检查新镜像里两个 schema 文件是否存在：
     `docker run --rm --network none --pull never --entrypoint test <镜像 ID> -f /app/contracts/candidate_bundle.schema.json
     -a -f /app/contracts/evidence.schema.json`。不挂载、不带环境值、不联网，只运行 `test`，不碰任何线上容器。退出码
     0 = 自带契约，1 = 不带；其他退出码（docker 自身失败）一律拒绝。
   - **旧镜像显式回退**：`--legacy-contracts-dir DIR` 只用于不带契约的旧镜像（回滚到 I5 之前的镜像）。DIR 必须是目录且有
     上面两个 schema 文件，路径不能含 `:`。只读挂载到 `/app/contracts`。
     - 新镜像不带契约，又没传该参数：拒绝。不静默回到私有目录，以免再次漂移。
     - 新镜像自带契约，却传了该参数：拒绝。外部目录会覆盖镜像里的契约，正是本次的漂移形态。
   - `--dry-run` 与执行输出增加 `contracts`（`"image"` 或 `"legacy_dir"`），以及新镜像标签
     `io.insurancekb.app.build-source-head` 的值（没有该标签时为 `null`）。运维据此导出旧镜像对应的契约。
5. **预发布**（`deploy/staging`）：`compose.yaml` 去掉固定的契约挂载。`staging.sh images` 照搬线上 App 的状态：线上 App
   有 `/app/contracts` 挂载（旧镜像）时，写一个只含这条挂载的 compose 覆盖文件 `$STAGING_HOME/contracts.compose.yaml`；
   没有挂载时删除该文件。`compose()` 在文件存在时把它作为第二个 `-f`。I5 之后的线上 App 不挂载，预发布也就直接用
   镜像自带的契约。
6. **演练**（`deploy/rehearsal`）：本片不改挂载。`images.lock` 当前固定的 App 镜像早于 I5、不带契约，去掉挂载会直接坏掉。
   README F1 与 compose 注释改为：I5 起镜像自带契约；`images.lock` 换到 I5 之后的镜像时，同一变更里去掉这条挂载。

## 3. 失败关闭

| 情形 | 结果 |
|---|---|
| 新镜像缺两个 schema 文件之一、未传 `--legacy-contracts-dir` | 换装前拒绝，不碰容器 |
| 新镜像自带契约、传了 `--legacy-contracts-dir` | 换装前拒绝 |
| `--legacy-contracts-dir` 不是目录、缺 schema 文件，或路径含 `:` | 换装前拒绝 |
| 探测容器无法运行（docker 返回 0/1 以外的退出码） | 换装前拒绝 |
| 换装后平台启动时读契约失败 | 平台本身拒绝启动（`enterprise publishing needs …`），健康检查失败，按部署步骤回滚 |

探测只证明文件存在，不证明内容与二进制一致。一致性由第 2 节第 1–3 条保证：契约与二进制出自同一构建上下文，身份
覆盖契约，复用底包时要求契约不变。

## 4. 回滚

- **回滚到 I5 之后的镜像**：照常换装，不需要额外参数。
- **回滚到 I5 之前的镜像**（例如 `7325ce5c`，构建源 `292fef2a5`）：
  1. 先看 `--dry-run` 输出的 `build_source_head`，确认旧镜像的构建源；
  2. 用 `git archive <该提交> contracts | tar -x -C <新建空目录>` 导出契约；
  3. 换装时传 `--legacy-contracts-dir <新建空目录>/contracts`。

  #522 步骤 1b 已把私有目录的 `contracts/` 对齐到 `292fef2a5`，回滚到 `7325ce5c` 时也可以直接传它。但新导出的目录才能
  确定与旧镜像的构建源一致，所以优先用新导出的。
- **I5 代码本身回滚**：撤销本 PR，换装工具恢复为挂载私有目录。此时私有目录必须先对齐到要换上的镜像的构建源。

## 5. 测试（离线，假 docker）

- `harness/tests/service_shell/test_swap_app.py`：
  - 新镜像自带契约时不挂载、`contracts == "image"`、`ENTERPRISE_CONTRACTS_DIR=/app/contracts`；
  - 新镜像不带契约且未传参数时拒绝，且不碰容器；
  - 新镜像不带契约且传了合格目录时，只读挂载该目录、`contracts == "legacy_dir"`；
  - 新镜像自带契约又传参数时拒绝；目录缺文件或路径含 `:` 时拒绝；
  - 探测失败（假 docker 返回 125）时拒绝；
  - 私有目录没有 `contracts/` 也能换装；
  - 输出带 `build_source_head`；
  - 探测命令不带 `-e`、`-v`，并且用 `--network none`。
- `harness/tests/service_shell/app_build/`：
  - `runtime` 阶段复制 `/app/contracts`；
  - 清单 `required_paths` 含 `contracts`，解析出的输入含 `contracts/` 下的文件（`REQUIRED_COPY_ROOTS` 加 `contracts`，
    合成仓库补一个契约文件）；
  - `runtime_reuse_facts` 的受保护路径含 `contracts`。
- 预发布、演练脚本没有离线测试；本片只做第 2 节第 5、6 条所列的最小改动，`bash -n` 检查语法。

## 6. G10

`docker/Dockerfile.app` 已计入 G10 基线（G10 按文件计；0.8.2 升级时已修改），增加 1 行不改变 G10 计数。本片允许修改该
上游文件，实现提交在 `docs/design/upstream-patches.md` 追加它的登记行（原因：镜像带契约；退出条件：上游镜像提供
额外资源目录的扩展点，或本项目改用自有 Dockerfile）。其余改动都在项目自有文件内。

## 改动范围

- `docker/Dockerfile.app`（1 行）、`docs/design/upstream-patches.md`（追加 1 行）
- `deploy/local-build/app-build-inputs.v1.json`、`scripts/app_artifact.py`（受保护路径 1 项）
- `deploy/local-live/swap_app.py`
- `deploy/staging/staging.sh`、`deploy/staging/compose.yaml`
- `deploy/rehearsal/README.md`、`deploy/rehearsal/compose.yaml`（只改注释）
- 测试：`harness/tests/service_shell/test_swap_app.py`、`harness/tests/service_shell/app_build/`（`helpers.py`、
  `contract_helpers.py`、`test_app_build_dockerfile.py`）

## 7. 部署（另开 Issue，由 Codex 执行）

1. 构建含 I5 的 App 镜像，在镜像里确认 `/app/contracts` 与构建源的 `contracts/` 逐文件 sha256 一致；
2. 先 `swap_app.py --dry-run`，确认 `contracts == "image"`；
3. 换装、启动、健康检查，核对 Active 与账本不变；
4. 之后线上不再读私有目录的 `contracts/`。旧镜像回滚需要时仍可按第 4 节使用该目录，所以保留，不删除。
