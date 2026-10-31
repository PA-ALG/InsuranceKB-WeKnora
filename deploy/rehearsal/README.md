# I3a 从制品全新安装演练（运维手册）

依据 [`docs/design/slices/I3-私有化演练.md`](../../docs/design/slices/I3-私有化演练.md) §1。目的：只凭“按 digest 固定的镜像 +
本目录的部署文件 + 本手册”，在一台干净的机器上装出可用环境，不从源码构建、不手工改镜像、不复制线上数据。
本机演练用独立的 colima profile `rehearsal`，线上 profile 只在 `images --from-live` 时做一次只读的 `docker save`。

## 文件

| 文件 | 作用 |
|---|---|
| `images.lock` | 五个镜像的固定引用：pg、redis 按官方 digest；App/UI/docreader 的 CI digest（I1 产物）与线上 image ID（I1 发布前的过渡来源） |
| `compose.yaml` | I2 拓扑：pg、redis、docreader 只在内部网络；App 另接出网网络；UI 只绑 `127.0.0.1` |
| `app.defaults.env` | App 的非密钥设置（自动迁移、存储、发现 F2 的 SSRF 白名单） |
| `rehearsal.sh` | 各步骤命令；密钥只生成到 `$REHEARSAL_HOME`（权限 600，必须在任何 git 仓库之外），从不打印 |
| `seed.py` | 最小新装与冒烟（只用 Python 标准库，以 `python3 -I` 运行）；每一步可重复执行，已存在的对象按名称或文件摘要复用 |

## 前提

- 宿主：colima、Docker CLI（带 compose 插件）、Python 3.11+、OpenSSL；Harness 环境：在本仓库 `harness/` 下 `uv sync --frozen`。
- 本仓库检出到与镜像相同的提交：App 镜像不含 `contracts/`，安装时从仓库挂载（发现 F1）。
- 一块另外的磁盘目录（`REHEARSAL_DISK_ROOT`），放虚拟机数据盘，避免占用线上磁盘。
- 模型密钥放在执行 `seed`/`smoke` 的 shell 环境里：`DEEPSEEK_API_KEY`（或 `HARNESS_SCHEMA_FIELDS_API_KEY`）、`DASHSCOPE_API_KEY`。
- 用 `--from-ghcr` 时，若 GHCR 包是私有的，先用只读令牌 `docker --context colima-rehearsal login ghcr.io`。
- 内存：本机同时运行线上（8 GB）与演练（5 GB）虚拟机，`staging` profile 必须先停掉。

## 步骤

每步给出命令、预期输出和 2026-10-31 首次演练的实测耗时。所有命令在仓库根目录执行，前缀 `deploy/rehearsal/rehearsal.sh`。

| # | 命令 | 预期 | 实测 |
|---|---|---|---|
| 1 | `REHEARSAL_DISK_ROOT=<另一块盘上的目录> rehearsal.sh profile` | 新建 4 CPU / 5 GB / 40 GB 虚拟机，数据盘移到该目录；Docker 默认上下文切回线上 | 197 s |
| 2 | `rehearsal.sh images --from-ghcr`（I1 发布前用 `--from-live`） | pg、redis 按 digest 拉取；App/UI/docreader 按 CI digest 拉取（或从线上只读复制同一 image ID）；写 `images.env` 与 `config.yaml`（发现 F3）；打印线上磁盘占用 | 742 s（`--from-live`；其中 paradedb 2.4 GB 拉取约 10 min，三个产品镜像复制 107 s） |
| 3 | `rehearsal.sh env` | `env files written (secrets generated locally, never printed)` | < 1 s |
| 4 | `rehearsal.sh dns` | `rehearsal VM now resolves via <网关>` 或 `rehearsal VM resolves names` | < 5 s |
| 5 | `rehearsal.sh up` | `stack healthy in Ns`，五个服务 Up | 10 s |
| 6 | `rehearsal.sh ledger` | `official|134|f`、`enterprise|12|f`：两个账本都推进到当前头且非 dirty（以账本状态证明迁移，不以日志） | < 1 s |
| 7 | `rehearsal.sh seed` | 三行 JSON：`platform`（租户、三个模型、Space）→ 重建 App → `materials`（3 份 PDF 解析完成）→ `harness`（见下） | platform 1 s，materials 10 s，harness 360 s |
| 8 | `rehearsal.sh smoke` | 一行 JSON，`"passed": true` | 6 s |
| 9 | `rehearsal.sh destroy`（带同一个 `REHEARSAL_DISK_ROOT`） | 删除 profile 与外置数据盘；`$REHEARSAL_HOME` 里的密钥需手工删除 | 3 s |

`seed` 的三步：

1. **platform**：注册首个用户（该用户即租户 Owner），建全权限服务 API key，录入生产模型组合（DeepSeek 问答；百炼 embedding、
   rerank），给内置“快问快答”智能体设对话模型（发现 F4），建原始材料库与 wiki 库（原始材料库不设摘要模型，否则每次上传都会多一次
   对话调用），写 `spaces.env`（`ENTERPRISE_SPACES` 与 `DISABLE_REGISTRATION=true`）。随后 App 重建，注册随之关闭。
2. **materials**：上传 `dataset/shouxian_product` 中一款公开产品（默认 `1818`，`REHEARSAL_PRODUCT` 可换）的条款、说明书、费率表，
   等待解析完成，写来源映射。
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

另：`deploy/staging/compose.yaml` 从线上复制的 `c5` 卷没有任何代码读取，新装不需要。

## 人工操作

全程无手工改镜像、无从源码构建。需要人做的只有：准备另一块盘的目录；在 shell 环境里提供两组模型密钥；GHCR 包为私有时做一次只读登录；
拆除后删除 `$REHEARSAL_HOME`。其余步骤都由脚本完成。

## 结果（2026-10-31）

| 项 | 结果 |
|---|---|
| 镜像来源 | `--from-live`（I1 的 arm64 镜像尚未发布，见 PR #474）：App `sha256:82b994e5…`、UI `sha256:55dbdff6…`、docreader `sha256:c34b8caf…`，与线上同一 image ID |
| 迁移 | 空库启动后官方 134 / 企业 12，均非 dirty |
| 编译发布 | 产品 1818：DeepSeek 编译 4 次、审核 2 次；随包策略 → 人工队列 1 个候选；演练策略 → 机器审核上线，Release epoch 1：56 claim、1 entity、1 navigation、1 presentation profile |
| 冒烟 | 健康 200；Active 可读；原文 PDF 503 KB 打开；导航 `current`；快问快答 575 字，回答“0周岁（须出生满28日）至17周岁”，引用已发布字段 `1818/entry_age_range` |
| 模型调用 | DeepSeek 共 8 次（编译 4、审核 2、问答 2），预算 ≤ 10；百炼 embedding 若干次 |
| 第二轮 | 同一虚拟机清空数据卷、换新的 `$REHEARSAL_HOME`，用最终版脚本重做：`images` 0 s，`env`→`ledger` 11 s（账本 134 / 12），首次注册 → 重建 App → 上传解析 17 s，注册已关闭（403），重复 `platform` 幂等；Harness 登记与 `publish --dry-run` 计划编译发布 1818，0 次调用。编译与问答没有重做（预算） |
| 资源 | 演练数据盘 40 GB 用 11 GB；拆除后 profile 与外置数据盘均已删除，Docker 默认上下文为线上；线上 `default` 数据盘 80% 前后不变，线上健康全程 200 |
| 总耗时 | 机器时间约 22 min（建虚拟机 3 min、镜像 12 min、安装与迁移 < 1 min、新装与编译发布 6 min、冒烟 6 s、拆除 3 s）；镜像改为 GHCR 拉取后取决于带宽 |

## 换到 I2 云主机

只换宿主与镜像来源：`images --from-ghcr`（`images.lock` 填入 I1 发布的 digest），模型密钥用该环境独立的一组；宿主 DNS 正常时去掉
F2 的白名单；F1、F3、F4 的处理照用。
