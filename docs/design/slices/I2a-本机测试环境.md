# I2a 本机测试环境（I2 的本机预演）

> 状态：首次运行完成（2026-10-30，Claude）。Issue #466。实现方 Claude，自审（只有部署脚本与文档，不改 Go/前端/Harness 运行时代码）。
> 来源：用户 2026-10-30"云端测试环境先本机测试不行么"。I2（`I2-云端测试环境.md`，#462）的拓扑先在本机独立的 colima 虚拟机里跑通，上云时只换宿主。

## 1. 目标与边界

- 用 I2 的 compose 拓扑在本机起一套与线上同版本、同数据的测试环境，验证部署、恢复与冒烟的操作手册。
- **不解决单机风险**：测试环境与线上在同一台 Mac、同一块外置盘上，磁盘写满、colima 异常、休眠等故障会同时影响两者。消除单点仍需 I2 上云或另一台机器。
- 线上只读：只做 `docker inspect`、`docker save`、`docker exec … pg_dump`、`docker exec … tar`；不停、不改、不重启 `default` 虚拟机和任何 `upg-final-082-20260928-live-*` 容器。

## 2. 拓扑

| 项 | 取值 |
|---|---|
| 虚拟机 | colima profile `staging`：4 CPU / 5 GB 内存 / 48 GB 数据盘；数据盘放外置盘 `ColimaData/colima-staging/datadisk`（稀疏文件，`cp` 复制保持稀疏） |
| Docker 上下文 | `colima-staging`；默认上下文始终保持 `colima`（`colima start -p staging` 会切换默认上下文，脚本与手册都切回） |
| 服务 | pg（ParadeDB）、redis、docreader、app、ui，`restart: unless-stopped` |
| 网络 | `internal`（internal: true，五个服务）、`egress`（app 访问模型）、`edge`（ui 对外） |
| 端口 | ui `127.0.0.1:18395`（线上为 18295） |
| 卷 | pgdata、files、c5、docreader-tmp（项目名 `insurancekb-staging`） |
| 镜像 | 与线上容器**同一 image ID**，从线上虚拟机 `docker save` 流式导入后打本地标签，不拉取 |

## 3. 密钥

- 测试环境使用**自己生成**的密钥（数据库与 Redis 口令、JWT、`SYSTEM_AES_KEY`、引用签名键），保存在仓库外的 `$STAGING_HOME/secrets.env`（权限 600），重复运行时沿用。
- **不复制线上密钥**：本机权限检查拒绝把线上凭据物化到文件；I2 Spec 也建议新环境不复制 `SYSTEM_AES_KEY`、重新录入模型密钥。
- 后果：恢复来的数据库里，模型密钥是用线上 `SYSTEM_AES_KEY` 加密的，测试环境解不开。需要模型的操作（问答、编译）要先在测试环境界面重新录入模型密钥（DeepSeek；百炼的 embedding、rerank、VLM）。不需要模型的读取（Active、页面、发布预演）不受影响。
- 非密钥配置（`ENTERPRISE_SPACES`、存储、检索驱动等）按白名单从线上容器复制。

## 4. 操作手册（`deploy/staging/staging.sh`）

1. `colima start -p staging` 后执行 `docker context use colima`。
2. `staging.sh env`：生成各服务 env 文件（只打印计数，不打印取值）。
3. `staging.sh images`：按 image ID 复制五个镜像并打标签，写 `images.env`。
4. `staging.sh restore`：起 pg → 建库 → `pg_dump -Fc` 流式 `pg_restore`；files、c5 两个卷用 `tar` 流式复制（保留属主）。`pg_dump` 失败即中止；`pg_restore` 对仅存在于线上的角色授权等可忽略告警计数并记日志。
5. `staging.sh dns`：确认测试虚拟机能解析域名（必要时指向其网关）；`staging.sh up`：起全部服务（重建容器）。
6. `staging.sh ledger`：官方与企业两个迁移账本应与线上一致（预期 110 / 12，均非 dirty），即没有发生迁移。
7. 冒烟（第 5 节）。
8. `staging.sh stop`：停服务、停 `staging` 虚拟机、默认上下文切回 `colima`。

## 5. 冒烟与通过标准

- `http://127.0.0.1:18395/health` 返回 200；
- 用现有服务密钥读 Active：epoch / 成员数与线上相同；
- 两个迁移账本与线上相同；
- Harness 发布预演（`publish_navigation --dry-run`）对测试环境返回正常状态；
- 一轮快问快答：需先完成第 3 节的模型密钥录入，录入前记为"待录入"，不算失败；
- 线上：健康 200、Active 不变、`default` 数据盘使用率不升过 85%。

## 6. 改动范围

`deploy/staging/compose.yaml`、`deploy/staging/staging.sh`、本 Spec。无 Go、前端、Harness 运行时代码改动；无迁移。

## 7. 清理与回滚

`staging.sh stop` 停机；彻底删除：`colima delete -p staging` 并删除外置盘上的 `ColimaData/colima-staging/`。线上不受影响，无需回滚。

## 8. 结果（2026-10-30 首次运行）

| 项 | 结果 |
|---|---|
| 虚拟机 | `staging` 4 CPU / 5 GB / 48 GB；数据盘在外置盘，恢复后用 16 GB（36%） |
| 镜像 | 5 个按 image ID 复制，139 s（约 11 GB） |
| 数据库 | 3.5 GB，`pg_dump -Fc` 流式恢复 203 s；`pg_restore` 仅 3 条可忽略错误（paradedb、tiger、topology 三个 schema 已由镜像在模板库中创建） |
| 卷 | files 1.1 GB 17 s，c5 1 s；恢复合计 228 s |
| 迁移账本 | 官方 110 / 企业 12，均非 dirty，与线上相同（未发生迁移） |
| 健康 | `127.0.0.1:18395/health` 200 |
| Active | 与线上同一 Release，epoch 139 / 3055 成员 |
| 发布预演 | `publish_navigation --dry-run` 返回 `current`（导航 2026-10-28.1 已发布），与线上一致 |
| 快问快答 | 按设计待录入：DeepSeek 返回 401（库内模型密钥用线上 `SYSTEM_AES_KEY` 加密，测试环境解不开），未消耗 token |
| 对线上影响 | 全程健康 200、Active 不变；`default` 数据盘 70% 前后不变；内存占用 8 + 5 GB（本机 16 GB） |

运行中发现并已写进脚本的三个问题：

1. `colima start -p staging` 会把 Docker 默认上下文切到 `colima-staging`，可能让依赖默认上下文的工具误连测试环境。手册与 `stop` 都切回 `colima`。
2. 新建的 colima 虚拟机里 `/etc/resolv.conf` 仍是指向 systemd-resolved stub 的链接，而该服务未运行，所以任何域名都解析不了（应用的 SSRF 检查报 DNS 失败）。新增 `staging.sh dns`：指向测试虚拟机自己的网关，不依赖线上虚拟机，修好后重建容器。
3. 引用签名键必须是合法的 Ed25519 私钥（`internal/config/config.go`），随机串会让应用启动时配置校验失败。`env` 用 OpenSSL 生成合规密钥，已有的非法值会自动替换。

调用：DeepSeek 2 次尝试，0 token（1 次在 DNS 修复前未发出，1 次 401）。

上云（I2）时沿用本手册，只换宿主与镜像来源（I1 的 GHCR 摘要）；模型密钥在新环境界面录入。
