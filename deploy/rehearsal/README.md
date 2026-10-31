# I3a 从制品全新安装演练（运维手册）

依据 [`docs/design/slices/I3-私有化演练.md`](../../docs/design/slices/I3-私有化演练.md) §1。目的：只凭“按 digest 固定的镜像 +
本目录的部署文件 + 本手册”，在一台干净的机器上装出可用环境，不从源码构建、不手工改镜像、不复制线上数据。
本机演练用独立的 colima profile `rehearsal`，线上 profile 只在 `images --from-live` 时做一次只读的 `docker save`。

## 文件

| 文件 | 作用 |
|---|---|
| `images.lock` | 五个镜像的固定引用：pg、redis 按官方 digest；App/UI/docreader 的 CI digest（I1 产物）与线上 image ID（I1 发布前的过渡来源） |
| `compose.yaml` | I2 拓扑：pg、redis、docreader 只在内部网络；App 另接出网网络；UI 只绑 `127.0.0.1`，并挂载本实例的随机标记。只经 `rehearsal.py` 使用 |
| `app.defaults.env` | App 的非密钥设置（自动迁移、存储、发现 F2 的 SSRF 白名单） |
| `rehearsal.py` | 各步骤命令（入口）；每步打印一行 JSON，失败只打印固定错误码与 HTTP 状态码，退出码 2 |
| `vm.py` | 演练虚拟机的创建、归属核验与拆除 |
| `stack.py` | 镜像、生成配置、compose，以及把 HTTP 绑定到已核验的演练实例 |
| `seed.py` | 最小新装与冒烟（HTTP 与 Harness 调用）；每一步可重复执行 |
| `private.py` | 私密目录与文件：原子写入、不跟随链接、权限 600 |

全部只用 Python 标准库，以 `python3 -I` 运行；离线测试在 `harness/tests/service_shell/test_rehearsal_*.py`（假的 colima/Docker/WeKnora，不碰真实环境）。

## 前提与设置

- 宿主：colima、limactl、Docker CLI（带 compose 插件）、Python 3.11+、OpenSSL；Harness 环境：在本仓库 `harness/` 下 `uv sync --frozen`。
- 本仓库检出到与镜像相同的提交：App 镜像不含 `contracts/`，安装时从仓库挂载（发现 F1）。
- 内存：本机同时运行线上（8 GB）与演练（5 GB）虚拟机，`staging` profile 必须先停掉。
- 用 GHCR 镜像时，若包是私有的，先用只读令牌 `docker --context colima-rehearsal login ghcr.io`。

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `REHEARSAL_DISK_ROOT` | 无（`profile`、`destroy` 必填） | 另一块盘上的目录，路径中不能有符号链接；数据盘放在其下 `insurancekb-rehearsal/<profile>/` |
| `REHEARSAL_HOME` | `~/weknora-rehearsal` | 私密目录：本用户所有、0700、路径无符号链接、不在 git 工作区内 |
| `REHEARSAL_PROFILE` | `rehearsal` | 不能是 `default`、`staging` |
| `REHEARSAL_UI_PORT` | `18495` | 只在 `profile` 时读取并写进归属记录；不能等于 `LIVE_UI_PORT` |
| `LIVE_CONTEXT` / `LIVE_UI_PORT` | `colima` / `18295` | 线上的 Docker 上下文与端口，只用于拒绝与只读核对 |
| `REHEARSAL_PRODUCT` | `1818` | 一个演练实例只装一款产品 |
| `DEEPSEEK_API_KEY`（或 `HARNESS_SCHEMA_FIELDS_API_KEY`）、`DASHSCOPE_API_KEY` | — | `seed`、`smoke` 需要；从不打印 |

## 安全边界（审核 R1–R6）

- **归属而非名称**：`profile` 只新建——profile、Lima 磁盘项、外置目录任何一个已存在就拒绝；私密目录必须为空。创建时在私密目录写归属记录
  （创建 id、实例 id、profile、上下文、外置目录的规范路径、UI 端口），并在外置目录写同一创建 id。之后每一步都核对：记录、外置目录标记、
  Lima 数据盘链接确实指向记录里的磁盘、路径无符号链接且位于 `<REHEARSAL_DISK_ROOT>/insurancekb-rehearsal/<profile>`、Docker 上下文的
  socket 属于该 profile。
- **安全拆除**：`destroy` 先做完全部核验再动手；`colima delete` 失败、删除后 profile 仍在、Lima 实例目录仍在、`limactl disk list` 失败或显示
  磁盘仍被使用，都会停止并保留一切（退出码 2）。只有确认 profile 已删除、磁盘未被使用后，才在不跟随链接打开的目录里按固定文件名删除
  Lima 链接、外置数据盘与标记，再删私密目录里的演练密钥，归属记录标为 `destroyed`。
- **HTTP 只写演练实例**：任何请求前先绑定——端口来自归属记录且不是线上端口；演练上下文里的 compose 项目确实发布了该回环端口；线上上下文
  没有发布它；该端点返回本实例创建时生成的随机标记。缓存的服务 key 与状态记录了签发它的实例与租户，不符即拒绝；key 必须仍在 Owner 的
  key 列表里；复用的模型与知识库必须属于同一租户。
- **私密文件**：在已核验的 0700 目录里以 `O_EXCL|O_NOFOLLOW` 写临时文件、原子改名，最终文件核对为本用户的普通文件且权限 600
  （UI 标记与 `config.yaml` 不含密钥，为 644 以便容器读取）；读取拒绝链接和他人可读的密钥文件。
- **错误不带响应体**：HTTP 出错时响应体在读取层即丢弃；所有失败只输出固定错误码、HTTP 状态码，以及形如 `UPPER_CASE` 的下游错误码。
- **材料按摘要绑定**：一个实例一款产品；本产品文件按 SHA-256 记录、复用与核对（RAW 列表的摘要必须相同）；文件变了、缺了、换产品、
  同摘要多条都拒绝；来源映射只写本产品记录的那几条。

## 步骤

所有命令在仓库根目录执行：`python3 -I deploy/rehearsal/rehearsal.py <命令>`。实测耗时为 2026-10-31 首次演练（当时脚本为本轮修改前的版本，步骤与产物相同）。

| # | 命令 | 预期 | 实测 |
|---|---|---|---|
| 1 | `profile`（带 `REHEARSAL_DISK_ROOT`） | 新建 4 CPU / 5 GB / 40 GB 虚拟机，数据盘移到外置目录；默认上下文切回线上；`{"profile": ..., "state": "ready"}` | 197 s |
| 2 | `images`（I1 发布前加 `--from-live`） | pg、redis 按 digest 拉取；产品镜像按 CI digest 拉取，或从线上只读复制同一 image ID；写 `images.env` 与 `config.yaml`（发现 F3） | 742 s（`--from-live`；paradedb 2.4 GB 拉取约 10 min，三个产品镜像复制 107 s） |
| 3 | `env` | `{"env": "written"}`：密钥在本地生成，不打印 | < 1 s |
| 4 | `dns` | `{"dns": "resolves"}` 或 `{"dns": "gateway"}` | < 5 s |
| 5 | `up` | 绑定成功且 App 应答后 `{"healthy_seconds": N}` | 10 s |
| 6 | `ledger` | `{"official": {"version": 134, "dirty": false}, "enterprise": {"version": 12, "dirty": false}}`（以账本状态证明迁移，不以日志） | < 1 s |
| 7 | `seed` | 三行：`platform`（租户、三个模型、Space）→ 重建 App → `materials`（3 份 PDF 解析完成）→ `harness`（见下） | platform 1 s，materials 10 s，harness 360 s |
| 8 | `smoke` | 一行，`"passed": true` | 6 s |
| 9 | `destroy`（带同一个 `REHEARSAL_DISK_ROOT`） | 删除 profile、Lima 磁盘项、外置数据盘与演练密钥；`{"state": "destroyed", "kept": ["run"]}`：`run/`（登记、编译与审核输出，不含密钥）留作证据，下次 `profile` 前移走 | 5 s |

`down` 停服务与虚拟机（保留数据），之后 `up` 会先启动这台已归属的虚拟机；`status` 显示服务与数据盘占用。

`seed` 的三步：

1. **platform**：注册首个用户（该用户即租户 Owner），建全权限服务 API key（记录实例 id、租户与 key id），录入生产模型组合（DeepSeek 问答；百炼 embedding、
   rerank），给内置“快问快答”智能体设对话模型（发现 F4），建原始材料库与 wiki 库（原始材料库不设摘要模型，否则每次上传都会多一次
   对话调用），写 `spaces.env`（`ENTERPRISE_SPACES` 与 `DISABLE_REGISTRATION=true`）。随后 App 重建，注册随之关闭。
2. **materials**：按 SHA-256 上传 `dataset/shouxian_product` 中一款公开产品（默认 `1818`）的条款、说明书、费率表，只等待本次记录的
   这几条解析完成，核对 RAW 列表摘要后写来源映射。
3. **harness**：`ingest.uploads seed` 建产品登记；`ingest.uploads publish` 走生产路径（编译 ≤ 4 次、独立审核 ≤ 3 次 DeepSeek）。
   随包发布的审核策略不准入任何 pack，所以产品进入**人工队列**——这就是真实新装后的行为（发现 F6）。为了在一次性环境里验证
   上线、读取与回跳，再用一份**只在演练中生成**的策略（`review-policy@rehearsal-i3a-1`，准入该 pack、门槛 0）走机器路由，
   内容如实标注“机器审核”。正式环境不得使用这份策略。

`smoke` 检查：健康 200；服务 API key 读 Active（含 claim）；从 Active 的来源引用打开原文 PDF（200 且以 `%PDF-` 开头）；人工队列可读；
`publish_navigation --dry-run` 返回 `current`；一轮快问快答（问投保年龄，回答须给出年龄数字，错误提示不算通过）。

## 发现（演练中暴露、已写进脚本）

| # | 发现 | 处理 |
|---|---|---|
| F1 | App 镜像带 `config/`，不带 `contracts/`；配置 `ENTERPRISE_SPACES` 后发布需要 `ENTERPRISE_CONTRACTS_DIR` | 从与镜像同一提交的仓库只读挂载 `contracts/`。I2 上云沿用；也可另开 Issue 把 `contracts/` 打进镜像 |
| F2 | 宿主若用带 fake-IP DNS 的代理，`dashscope.aliyuncs.com` 解析到 `198.18.0.0/15`，App 的 SSRF 检查拒绝录入模型 | `app.defaults.env` 设 `SSRF_WHITELIST_EXTRA=dashscope.aliyuncs.com`（与线上一致）；DNS 返回真实地址的主机不需要 |
| F3 | 镜像自带的 `config.yaml` 没有引用签名密钥环；一旦设置 `ENTERPRISE_SPACES`，App 启动即 panic（`enterprise capture needs an active artifact signing key`），且列表型配置无法只靠环境变量提供 | `images` 从镜像取出它自己的 `config.yaml`，追加 `schema_wiki_signing`，密钥写成 `${E2E_CITATION_SIGNING_KEY}` 占位，由 App 启动时展开；文件本身不含密钥 |
| F4 | 新租户的内置快问快答智能体没有对话模型，问答直接返回 `chat model is not configured`，单次请求指定模型也不能代替 | `platform` 用 `PATCH /api/v1/agents/builtin-quick-answer` 设为 DeepSeek 模型 |
| F5 | 注册密码规则为 8–32 位且同时含字母和数字 | 第二轮演练发现脚本随机密码偶尔不含数字，已改为保证满足规则 |
| F6 | 随包审核策略不准入任何 pack，新装后所有产品都进人工队列，Active 在有人审核前为空（`RELEASE_NOT_FOUND`） | 符合蓝图“先发布后抽检”的现状；上线前须由人审核首批产品，或在某 pack 通过质量准入（RV3）后更新策略版本 |
| F7 | `colima start` 留下的守护进程（Lima 承载端口转发的 ssh ControlMaster）继承调用方给它的输出；若是管道，调用方退出后它随之退出，宿主上演练端口不再转发（本轮修改后的第一次真跑发现） | colima 的启动、停止、删除一律以 `/dev/null` 为输入输出运行 |

另：`deploy/staging/compose.yaml` 从线上复制的 `c5` 卷没有任何代码读取，新装不需要。

## 人工操作

全程无手工改镜像、无从源码构建。需要人做的只有：准备另一块盘的目录；在 shell 环境里提供两组模型密钥；GHCR 包为私有时做一次只读登录。
其余步骤（含拆除时删除演练密钥）都由脚本完成。

## 结果（2026-10-31）

| 项 | 结果 |
|---|---|
| 镜像来源 | `--from-live`（I1 的 arm64 镜像尚未发布，见 PR #474）：App `sha256:82b994e5…`、UI `sha256:55dbdff6…`、docreader `sha256:c34b8caf…`，与线上同一 image ID |
| 迁移 | 空库启动后官方 134 / 企业 12，均非 dirty |
| 编译发布 | 产品 1818：DeepSeek 编译 4 次、审核 2 次；随包策略 → 人工队列 1 个候选；演练策略 → 机器审核上线，Release epoch 1：56 claim、1 entity、1 navigation、1 presentation profile |
| 冒烟 | 健康 200；Active 可读；原文 PDF 503 KB 打开；导航 `current`；快问快答 575 字，回答“0周岁（须出生满28日）至17周岁”，引用已发布字段 `1818/entry_age_range` |
| 模型调用 | DeepSeek 共 8 次（编译 4、审核 2、问答 2），预算 ≤ 10；百炼 embedding 若干次 |
| 第二轮 | 同一虚拟机清空数据卷、换新的 `$REHEARSAL_HOME`，用最终版脚本重做：`images` 0 s，`env`→`ledger` 11 s（账本 134 / 12），首次注册 → 重建 App → 上传解析 17 s，注册已关闭（403），重复 `platform` 幂等；Harness 登记与 `publish --dry-run` 计划编译发布 1818，0 次调用。编译与问答没有重做（预算） |
| 第三轮（本轮修改后） | 用审核 R1–R6 修改后的脚本在新 profile 上真跑：`profile` 154 s（归属记录、外置目录标记、Lima 链接指向记录的磁盘、上下文 socket 均核对通过）→ `images --from-live` 435 s → `env`、`dns` → `up`（端口转发正常、实例标记绑定成功）→ `ledger` 134 / 12 非 dirty → `down`/`up` 26 s（先启动归属的虚拟机）→ `platform`、重建 App、`materials`（20 s，3 份按摘要上传并核对）→ 重跑两步幂等、注册已关闭 403 → Harness 登记与 `publish --dry-run`（0 次调用）→ `destroy` 5 s：profile、Lima 磁盘项、外置数据盘、演练密钥均删除，无遗留。编译与问答未重跑（预算） |
| 资源 | 演练数据盘 40 GB 用 11 GB；拆除后 profile 与外置数据盘均已删除，Docker 默认上下文为线上；线上 `default` 数据盘 80% 前后不变，线上健康全程 200 |
| 总耗时 | 机器时间约 22 min（建虚拟机 3 min、镜像 12 min、安装与迁移 < 1 min、新装与编译发布 6 min、冒烟 6 s、拆除 3 s）；镜像改为 GHCR 拉取后取决于带宽 |

## 换到 I2 云主机

只换宿主与镜像来源：`images --from-ghcr`（`images.lock` 填入 I1 发布的 digest），模型密钥用该环境独立的一组；宿主 DNS 正常时去掉
F2 的白名单；F1、F3、F4 的处理照用。
