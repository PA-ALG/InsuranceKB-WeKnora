# 平台产品处理服务

此目录部署常驻 API、后台任务服务和一次性数据库迁移。三者使用同一不可变镜像；正常上传只创建任务，不执行源码构建或部署。后台任务与上传页面、Codex 的生命周期无关。

构建使用 `Dockerfile`、`harness/uv.lock` 导出的 `requirements.lock` 和明确的 Linux Python 基础镜像。配置不随镜像打包：私密 env 文件同时提供 `WIKI_POSTGRES_DSN` 和迁移使用的 `HARNESS_DB_URL`，两者使用 `postgresql+psycopg://` 并指向同一个 Harness 专用数据库。允许与 WeKnora 复用 PostgreSQL 服务，禁止复用 WeKnora 业务表作为任务存储。

`G3_TRUSTED_CONFIG_DIR` 只读挂载 Catalog、Profile 确认和归并策略。`WIKI_PRODUCT_INGESTION_RUNTIME_JSON` 内的对应文件路径必须使用 `/run/product-config/`，内容摘要必须匹配。API 和 worker 使用同一空间绑定、模型策略、任务并发与租约设置；仅测试隔离环境启用系统自动审核签名身份。

部署顺序：冻结和检查代码 → 构建镜像 → 校验私密配置 → 迁移至当前 Alembic head → 启动 API/worker → 检查两者 `/readyz` → 接通 WeKnora 产品上传和系统处理路由 → 网页验收。迁移失败不会启动依赖服务。

在正式计时前记录实际镜像、配置摘要、数据库版本及健康状态。真实产品上传开始后，只能使用平台网页操作和只读观察。任何代码修改、临时拼接候选、调用发布脚本或服务切换，都会使该次独立链路验收无效。

后台任务服务同时连接平台内部网络和常驻 provider-egress 出站网络。WeKnora 应用在部署时连接相同出站网络；DocReader、数据库和 API 无需因此获得外网连接。此网络不映射任何端口，取代旧运行中的临时模型转发进程。

2026-09-13 收敛要求：本目录描述的是平台共用的产品处理能力，不是每次测试的独立环境。接入当前已有应用、PostgreSQL、Redis、DocReader 和文件卷；不再启动新的数据库实例或复制整套平台。已经准备的逻辑库与镜像直接复用，不为改名字、换布局重新迁移或构建。后续产品上传使用同一套服务；只有必要的代码更新才进行部署。
