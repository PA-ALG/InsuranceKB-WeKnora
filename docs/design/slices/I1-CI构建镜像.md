# I1 CI 构建镜像

> 状态：Spec（2026-10-30，Claude）；2026-10-30 实现时修订 §3.1/§3.3/§3.4/§5（App 先只发 linux/arm64，amd64 移到 I1b）。实现方 Claude，审核方 Codex。蓝图 §3「交付」、§9「构建与部署」、§11 I1。
> 真实调用：0。不部署；部署仍按单独 Issue。

## 1. 目标

App、UI（frontend）、DocReader、Harness 由 GitHub Actions 构建，多架构（linux/amd64 + linux/arm64），按 digest 发布到
GHCR，附构建回执。环境按 digest 拉取，Mac 不再是唯一的构建机。

动机（2026-10-28～30 的实际故障）：本机构建三次失败在容器内外网下载（Go 模块、Debian 快照、anydoc），一次把 Docker
数据盘写满导致线上 401；构建依赖本机 BuildKit 缓存，清缓存后必须现场下载。

## 2. 现状

| 资产 | 现状 |
|---|---|
| `scripts/app_artifact.py`（BA0 合同） | 本机 `select-or-build`：按 `deploy/local-build/app-build-inputs.v1.json` 与 `app-external-dependencies.v1.json` 计算 artifact identity、选取或构建 App 镜像，写回执（`image_id`、`artifact_identity`、`build_source_head`、标签）。**只支持 linux/arm64**。 |
| `docker/Dockerfile.app` | 多阶段（lock-plan → rust/anydoc → browserskill → Go builder → runtime），依赖 BA0 依赖锁的下载 URL 与校验和。 |
| UI | 本机 `git archive` + `docker build --build-arg VITE_FRONTEND_COMMIT`（`frontend/Dockerfile`，node 构建 + nginx）。 |
| DocReader | `docker/Dockerfile.docreader`（python 3.10.18 镜像固定 digest）。 |
| `.github/workflows/weknora-app-local-live-image.yml` | 我们的“可信 local-live 镜像”流水线：仅 `workflow_dispatch`、仅 main、`ubuntu-24.04-arm`；先用 `harness/scripts/verify_weknora_app_source.py` 校验 `deploy/local-live/weknora-app-source.lock.json`，再构建 app/frontend/docreader 推到 `ghcr.io/pa-alg/insurancekb-weknora-*`，带 provenance、SBOM、attestation。最后成功运行 2026-07-28，之后的部署全部走本机构建。 |
| `.github/workflows/docker-image.yml` | 上游的 DockerHub 发布流水线（`workflow_dispatch`），我们不用。 |
| Harness | 没有镜像；CI 的 wheel-smoke 构建 wheel。 |

## 3. 设计

1. **新流水线 `.github/workflows/images.yml`**（我们自有文件；`.github/` 不计 G10）。
   - 触发：push 到 main（只在运行时路径变化时：`cmd/ internal/ migrations/ frontend/ docreader/ docker/ go.mod go.sum third_party/ harness/src harness/pyproject.toml harness/uv.lock deploy/local-build/`）、tag `v*`、`workflow_dispatch`。
   - 矩阵：`frontend`、`docreader`、`harness` × `ubuntu-24.04`（amd64）与 `ubuntu-24.04-arm`（arm64）原生 runner，各自按 digest 推送后 `docker buildx imagetools create` 合成多架构索引；`app` 只在 `ubuntu-24.04-arm` 上构建（见 3.3）。
   - 沿用现有可信流水线的做法：actions 固定 commit SHA、`provenance: mode=max`、`sbom: true`、`attest-build-provenance`、GHA 缓存。
2. **App 身份与回执沿用 BA0 合同**：CI 先跑 `app_artifact.py` 的身份计算（纯函数部分），把 artifact identity、依赖锁 sha、manifest sha 写成镜像标签，与本机构建同名同值；回执（JSON）作为 workflow artifact 上传，tag 时附在 Release 上。回执字段在本机回执基础上增加 `index_digest` 与每架构 `digest`。
3. **BA0 合同扩到 amd64 移到 I1b**（实现时修订）：BA0 合同与其受保护验收（`harness/tests/test_local_app_build_830_ba0.py`，3,791 行）把 linux/arm64 写死在清单 `build_contract`、依赖锁平台、`GOARCH`、镜像架构检查与回执校验（`start_exact_image.py`）各处，并显式断言 amd64 被拒绝；amd64 还需要逐项核实 uv、DuckDB spatial/excel 扩展等下载项与校验和。按 §6「不确定的项先只发 arm64」，I1 的 App 只发 linux/arm64，身份与本机构建同名同值；amd64 App 另立 I1b（新增 amd64 清单与依赖锁、`app_artifact.py` 按架构取值、受保护断言单独披露修改）。线上与 I2a 测试环境都是 arm64；I2 若选 amd64 云主机，须先完成 I1b（或选用 ARM 实例）。
4. **Harness 镜像**：`docker/Dockerfile.harness`（python:3.12-slim-bookworm 与 uv 0.9.26 均按多架构索引 digest 固定；`uv export --locked` 生成带哈希的依赖清单，`pip install --require-hashes` 安装，再装本次构建的 wheel），非 root 用户运行；不含任何数据、配置与密钥。Harness 没有 `insurance-harness` 控制台命令，镜像用法为 `python -I -m insurance_harness.<模块>`（实现时修订）。
5. **发布命名**：`ghcr.io/pa-alg/insurancekb-weknora-{app,frontend,docreader,harness}`；tag `sha-<12 位>`、`main`、语义版本（tag 触发时）；**部署只用 digest**。
6. **不含密钥**：镜像不复制 `config.yaml`、`contracts/`、`.env*`；运行时挂载。流水线加一步镜像密钥扫描（采用成熟工具 trivy 的 secret 扫描，Apache-2.0；命中即失败）。公开仓库的 GHCR 包设为 public 或给部署环境发只读 PAT（由用户决定，见 I2）。
7. **本机路径保留**：`app_artifact.py select-or-build` 不变；新增“按 digest 拉取 CI 镜像并核对标签身份”的选取方式（`select --pull <ref@digest>`），本机部署优先拉 CI 镜像，避免现场下载。
8. **旧可信流水线与 023 源码锁**：U-1 合并后评估把 `weknora-app-local-live-image.yml` 与 `deploy/local-live/*.lock` 的源码锁校验并入或退役（I1 的回执 + attestation 已覆盖“构建来源可证明”）；本 Spec 不改它们。

## 4. 改动范围

`.github/workflows/images.yml`（新）、`docker/Dockerfile.harness`（新）、`scripts/app_artifact.py`（多架构与 `--pull` 选取）、`deploy/local-build/*.json`（amd64 项，升版本）、对应测试（`harness/tests/` 中 BA0 合同测试按需扩展，受保护断言改动单独披露）、本 Spec。

## 5. 验收

1. RED：`scripts/app_image_registry.py` 的 `plan` 输出与本机相同的身份标签与构建参数，`select --pull` 只接受本仓库 App 的精确 digest、在标签身份/架构/RepoDigests 不符时拒绝且不写 PASS 回执，PASS 回执能通过 `start_exact_image.py` 的回执校验；工作流合同（触发、动作固定 SHA、权限、不用仓库密钥、四个镜像、原生 runner、provenance/SBOM/attestation、secret 扫描失败即失败）；守卫通过。amd64 App 身份的测试移到 I1b。
2. 合并后在 main 上运行一次（或在 PR 分支 `workflow_dispatch`——仅当工作流文件已在默认分支，GitHub 才允许手动触发）：App（arm64）与其余三个镜像 × 两架构构建成功，索引 digest 可拉取；secret 扫描通过；回执 artifact 字段完整。
3. 同一提交重跑一次：App 的 artifact identity 与标签相同（镜像 digest 可因时间戳不同，须写明）。
4. 本机 colima `docker pull <app@digest>` 后用 `select --pull` 选取并通过一次只读烟测（`/app/WeKnora --help` 退出码、健康检查需在 I3a 的独立环境里做，不碰线上）。
5. 不改线上；部署仍单独开 Issue。

## 6. 风险与回滚

- amd64 依赖下载项与校验和须逐项核实（来源、许可证不变）；不确定的项先只发 arm64，Spec 记录缺口。
- CI 构建时长：App 约 10–20 分钟/架构；只在运行时路径变化与 tag 时触发。
- 回滚：删除新流水线即可；本机构建路径不受影响。
