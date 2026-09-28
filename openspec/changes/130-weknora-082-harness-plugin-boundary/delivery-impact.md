## 2026-09-28 0.8.2 最终交付与本地切换通过（当前）

PR #131 已合入 main@c5beb1afc；可信软件源 d5be03b3b，主干9项远端工作流全部成功。
本轮 App/DocReader各构建1次，UI前两次下载失败后通过已有代理完成第3次构建，Harness复用。
三个最终镜像均绑定完整输入身份；本地入口 http://127.0.0.1:18295 实测 version0.8.2、
commit d5be03b3b2da18d9bdcfb8f32d66e0bc31843a83、DB110，正常登录/静态资源/Harness链路通过。

停写后的五库、文件、配置、C5、可信配置与Redis已备份；在新卷恢复并通过一次原生迁移，
official110/false、enterprise5/false、pg_search0.22.6。原数据库卷未原位升级，旧服务与卷保留。
原数据旧列保持，仅有已审迁移例外；epoch27、members、来源字段、引用权限与696913字节PDF一致。
真实PDF样本上传、原生解析、嵌入、revision/source下载通过；MD错误样本的失败保留，实际embedding
合计2次embedding HTTP200/模型传输重试0（MD后处理失败与内部重试另存），样本只在隔离副本，不形成新业务Release或质量结论。

首次备份在1GiB全表校验时OOM，旧环境自动恢复；其后一次预检把挂载顺序变化误判为漂移，未停服。
失败现场均保留；Redis导出同步错误经原生导出/完整性检查后修正，重新完成一致备份。
有效备份位于工作区tmp/upg-final-backup-20260928-recovery3，旧部分备份原样保留；
私密恢复元数据已持久保存。入口开放后禁止自动倒回旧快照，以免丢失新增数据。
revision内app_commit/app_version未知的既有局限与legacy log非空页未覆盖均明确保留；不推导语义质量或发布验收。

CURRENT=已批准升级交付完成；NEXT=用户正常使用0.8.2，后续产品功能另按既有任务授权。
精确镜像、六维状态、回执SHA、备份及验收边界见 docs/insurance-kb/evidence/830-upgrade/final-delivery-20260928.json。
以下状态均为历史，不覆盖本块。

## 2026-09-28 当前交付边界

software：07d0e3e48测试前置及ReplaceFile来源SHA修复独审/定向PASS；完整CI未闭合。
source lock绑定07d0/8eb1，verify/report PASS；已有e71/82镜像不冒充新源。
provisioning：五库/准确配置恢复及既有e71 App唯一隔离75→110/e5/pg_search0.22.6迁移PASS。
container health/local live：旧版b393与新版e71隔离App健康及epoch27/source/PDF连续性PASS，测试Apps已停。
61旧表闭合、无意外业务变化；legacy log页0的非空改写场景NOT EXERCISED，详见最终回执fca2ae6e…。
provider probe、新业务tracer、原环境切换/新源码镜像NOT RUN；原8保持，App追加构建0。
GitHub live：8b121最终19成功/2失败/5跳过；Go/root lint失败，Draft不合并。

下方为历史影响记录，不能覆盖本块。

# 升级交付影响与现有运行基线

## 2026-09-28 当前续行

Colima 130 GiB已生效；App追加构建0，继续固定e71/442701。DocReader以e71固定
112项输入构建一次，image d1777c…，健康与Markdown解析烟测PASS。UI以82ff324de
冻结872项实际输入，一次构建PASS，image1ca8b0…；构建wrapper错误生成的label作为observed记录，
正确canonical预期9feb8130…与实际label e3da5700…不匹配，exact reuse保持BLOCKED，
不能虚报匹配或追加重建。按immutable image ID的无网络烟测PASS，14项静态资源、
Nginx配置、运行配置和7位源码标记已验证；两次烟测脚本错误保留，不冒充产品失败。

数据库五份备份已完成，恢复未执行。自动审批对新建隔离资源及归档敏感配置的拒绝
已报告用户，待明确答复；不切换旧服务、不迁移原卷。App、UI、DocReader来源与未来
trusted publication source 844f03c55分别列明，可信发布镜像NOT RUN。下方均为历史。

下表记录2026-09-27既有运行基线与原计划。当前2026-09-28 App制品已零构建恢复并通过隔离smoke，实际镜像仍未部署；其余组件状态不外推。最新回执为delivery-attempt-05.json。

| 组件 | 现有不可变镜像 | 当前升级影响 | 计划动作 |
|---|---|---|---|
| App | `sha256:7d97028e6994b4a48cfbbc7dea0407e42454d35c076134c600a0c86049ff5527` | 固定上游+模型/来源/Release接线；AnyDoc/BrowserSkill与新 runtime 配方 | BUILD_AFFECTED；BA0先lookup，命中exact则REUSE；只允许一次当前identity构建 |
| UI | `sha256:d488e95945f58a0967fd07108cacd32b0c83360e48d123d0bb57cc6ec2bfc57e` | Vue/i18n/上传队列/nginx/依赖均有变化 | BUILD_AFFECTED；源码前端构建已PASS，镜像未构建 |
| DocReader | `sha256:a5533268445e42b4e7a3501cf65a59c0bc8b2bf94898fa1deb66cb36898b9966` | 42个路径及20个生产Python文件/lock发生变化，gRPC proto未变；独审已确认 | BUILD_AFFECTED；需固定完整context身份并对新镜像跑解析器检查 |
| Harness API/worker | `sha256:593493031187b0ffaff1e2eacc6eef347e6206caf1b65f2eb6fa4e09be06c334` | 相对产品基线 src、Dockerfile、pyproject、uv.lock无变化，只有测试改动 | 保留旧运行；REUSE前绑定已有源码/依赖回执，不能只凭tag |
| PostgreSQL | `sha256:af585013f97f622715de01e48d00558f7edf17055d7b40deafc9f98ca8d99a56` | 上游pg_search目标0.22.6，official75→110，enterprise5保持 | 新服务器制品、真实备份/恢复演练与切换属于单独明确窗口，NOT RUN |
| Redis及未使用sandbox/检索后端 | 保持现有运行 | 当前不为新上游能力默认启用服务 | SKIP；不使用整套start-all/build-all |

## 回滚与真实验证的边界

- 未改变现有 epoch27 数据、对象文件、模型配置、provider、发布或现有服务。旧 G3/G3.5 的 FLOW_PASS/QUALITY_PARTIAL 不是新版本验收结果。
- 应用回滚与数据库恢复分离：旧 app 不支持 official110。迁移前需一致备份两账本、数据库、对象/文件及运行身份；旧 app 只能在兼容数据库恢复后验收。
- 新 app 初次实际构建必须保留完整固定依赖，不为省时恢复已废弃host skills或关闭上游默认AnyDoc。BrowserSkill动态链接、扩展包与许可由exact-image smoke核验，但不冒充业务健康。
- 真实链路在批准的同一环境验证：历史epoch27读取→旧固定来源读取→新来源/原生发现→Harness准入→正常审核/唯一发布→检索及原文点击。按原receipt复用成功输出，任何新增模型调用明确记账；不人工修改业务结果。
- cold/warm成本仅记录实际经过；不清缓存制造冷建，也不重建同identity测量。

## DocReader 的组件输入与本地检查

独审确认旧DocReader标签源码 `460c664cf20f23ede858aa06c24e8275cb56a495`，其DocReader树与升级基线一致，但不是目标树。当前Dockerfile复制整个packages与docreader，故组件输入至少包括 `.dockerignore`、`docker/Dockerfile.docreader`、`docreader/**`、`packages/**`；不能只比较PDF parser文件。D2沿现有构建入口冻结这些输入与base digest、args、platform，输出不可变image ID/receipt，不新建长期构建框架。

只读审查的有限本地诊断：38个变更Python文件语法编译；14个纯stdlib SSRF/tempfile、2个loopback proxy、6个endecode测试通过。完整宿主机环境缺NumPy/解析器依赖，系统Python3.9低于项目要求；不安装第二环境来冒充目标image。两个Go docreader live用例因未连接localhost:50051跳过。完整解析器测试和容器验证均NOT RUN，待目标镜像可用后执行；旧运行容器不作新源码测试环境。

固定目标镜像只读清单已确认提供linux/arm64，platform manifest为`sha256:ea992f2ee1e44d961d3b0f8b4b184cb2061fc9a8fc1dbfafb88f88180e3a16db`（paradedb/paradedb:v0.22.6-pg17）；实际拉取、扩展可用性探测与数据库操作尚未执行，标签清单不能替代实际服务器验证。

## 交付前只读核对与执行顺序

当前App同时连接 `weknora-g3-830-internal-recovery-02` 与 `weknora-g3-830-provider-egress`；UI通过 `weknora-g3-830-ui-edge` 绑定本机 `127.0.0.1:18295`。DB没有宿主端口，卷为 `weknora-g3-830-postgres-recovery-02-data`；文件卷为 `weknora-g3-830-files`，DocReader临时卷为 `weknora-g3-830-docreader-tmp`，C5签名配置卷为 `weknora-g3-830-c5-authority`。检查没有导出环境变量或凭据。

现有 `scripts/deployment/g3_replace_app.py` 固定了历史UI容器ID并要求App只有一个网络，不能直接用于当前运行身份；同时它只负责App替换，不处理本次DB升级。真正交付须以届时重新冻结的容器/制品/配置和当前双网络为准，不能把旧脚本可执行性当成新窗口准备完成。

1. C2冻结代码并独审通过后提交；D2仅构建App/UI/DocReader。App沿 `scripts/app_artifact.py select-or-build --context colima` 使用同一BA0权威（包装脚本仍默认已不存在的colima-g1-build），不能另写App构建命令绕过identity。UI/DocReader沿仓库Dockerfile、固定来源context构建，先按组件输入identity查询；记录build invocation、耗时、平台及最终image ID。
2. 目标镜像先做不接现有DB/provider的制品检查。DocReader解析单测使用新镜像和本地fixture；健康、provider、DB迁移和业务结果分别记录。
3. 实际窗口前确认工作流空闲，按已有恢复runbook准备双ledger/业务数据的一致备份、文件卷与运行配置身份；敏感备份不进入Git。先在独立目标卷恢复并执行75→110/e5迁移与0.22.6后置检查，旧卷/旧容器保留。迁移失败停止，不让旧App连接110。
4. 在隔离恢复副本核对历史Release、固定来源及凭据解析后，再执行已明确授权的测试环境切换；回退使用旧App与旧一致数据库/文件快照组合。新来源tracer、模型调用、审核发布和原文点击按各自授权及回执执行。此处是待执行顺序，各步当前均NOT RUN。

## D2实际结果（覆盖上方准备时态）

软件提交8a0863fa0，App lookup miss后唯一构建于197.05秒因Colima磁盘不足失败，无image。UI/DocReader lookup miss，构建NOT RUN。详见delivery-attempt-01.json；不继续构建或自动prune。空间恢复候选32个无容器引用历史业务镜像需明确批准，所有容器/卷及build cache保留。push被自动审批拒绝，正文准备完成但未创建PR；真实迁移与切换仍NOT RUN。

## 用户授权后的恢复结果（最新）

用户“允许”后，精确32个镜像已删除，容器/卷/build cache完整保留，可用空间约6.63GiB。独立复核支持一次恢复尝试；相同App identity/source的恢复构建已执行，约13.50秒后在Dockerfile frontend元数据阶段因配置镜像源EOF失败，没有进入编译或生成镜像。新增1次预算已用完，累计App构建2次；停止D2序列，不自动重试，UI/DocReader仍NOT RUN。详见delivery-attempt-02.json。push/Draft PR已获明确授权，历史自动审批拒绝不再是当前授权障碍；普通上传HTTP400/408（直连也408）后，确认fork已有固定上游对象，在同一目标分支引用3e8b0bfc，再普通快进到f3ff602b9，push成功，未force或改写提交。迁移/部署仍NOT RUN。

第三次恢复尝试已执行并失败（BrowserSkill子进程pnpm不可发现）；网络热重载在结束后已恢复，容器无重启。新增PATH修复属于App输入变更，旧8a/identity不可复用为修复制品。依赖锁保持；重新冻结/独审后才能使用新source和identity，未自动追加第四次。见delivery-attempt-03.json。

修复源e71c72f7d（identity 12d583e5…）的第四次App尝试已获新授权并执行，10.095880297秒后于官方frontend metadata TLS超时失败，没有进入编译；本轮1/1用尽，无第五次。网络临时配置自动恢复且8容器启动身份不变。后续应先验证实际daemon registry/代理路径，而非用客体直连401代表构建网络稳定。见delivery-attempt-04.json。

## 2026-09-28 最新：App制品恢复，整体交付未闭合

固定源e71c72f7d/identity12d583e5…第五次构建在最终本机解包ENOSPC，原失败保留；OCI导出已完整，失败后空间自行恢复。22层摘要核验与容量/独审通过后，既有selector硬预算0 REUSE、隔离smoke PASS，镜像sha256:442701a3bde3de5ff8aee7dfc9f7f461df1819b050c417f38ecd4ff226e33775。累计App5次，余量0；无第六次、无额外pull，无人工清理或现有服务重启。原8容器身份不变，烟测只清理自身临时容器，剩余1583464KiB；不在该容量下自动继续UI/DocReader或新App构建。7组CI、其余镜像、迁移/部署/业务仍未闭合；原epoch27不变。
