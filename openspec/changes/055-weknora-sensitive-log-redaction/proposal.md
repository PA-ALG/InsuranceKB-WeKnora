# 055 · WeKnora sensitive log redaction

## 状态

`SPEC + TDD / IMPLEMENTATION IN PROGRESS`

## 为什么做

生产 `initDatabase` 没有显式提供 GORM logger，因而继承 GORM 1.31.1 默认
`ParameterizedQueries=false`。GORM 在慢 SQL 与失败 SQL 的 Trace 阶段把绑定参数
插回 SQL；当 INSERT 携带 auth token、自定义 header 或 embedding vector 时，完整
值会进入 stdout/采集日志。

## 本 Change 做什么

- 用合成 token、header 和小向量稳定复现慢 SQL 与失败 INSERT 的参数泄露；
- 为生产 GORM 组合显式安装参数化 logger，日志只保留 SQL 结构和占位符；
- 同时覆盖慢 SQL 与执行失败路径，防止只修一条日志分支；
- 证明请求参数、SQL 执行、向量存储结果和业务错误保持原语义。

## 不做什么

- 不读取真实 Docker 日志、secret、数据库或 provider；
- 不修改 migration、模型、parser、认证协议或业务 repository；
- 不建设通用 observability、DLP、日志采集或字段分类平台；
- 不改变 SQL、请求、响应、事务或向量内容。

## 路径预算

严格九路径：README、OpenSpec 四文件、GORM logger 实现与 focused test、生产
`initDatabase` 组合及其 focused wiring test。出现第十条生产路径即停止并重新划界。
