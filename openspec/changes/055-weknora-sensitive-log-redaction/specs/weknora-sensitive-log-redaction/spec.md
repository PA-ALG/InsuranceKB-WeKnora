# WeKnora Sensitive Log Redaction Specification

## ADDED Requirements

### Requirement: L1 GORM Trace 不得输出绑定参数正文

生产数据库 logger SHALL 对 SQL 参数化。慢 SQL、失败 SQL 与普通 Trace 日志不得
包含 auth token、Authorization/header 值、embedding vector 正文或其他绑定参数；
日志 MAY 保留 SQL 操作结构、表列名、固定占位符、耗时、rows affected 与业务错误。

#### Scenario: 失败 INSERT 包含敏感参数

- **WHEN** INSERT 绑定合成 token、header 与 embedding vector 后因数据库约束失败
- **THEN** 日志包含失败与 SQL 结构，但不包含任一绑定值正文

#### Scenario: 慢 SQL 包含敏感参数

- **WHEN** 同类 INSERT 超过配置的慢 SQL 阈值
- **THEN** 慢 SQL 日志只包含参数化 SQL，不包含任一绑定值正文

### Requirement: L2 脱敏不得改变数据库行为

脱敏 SHALL 只作用于日志参数过滤，不得改写请求 DTO、GORM Statement vars、实际
执行 SQL、事务、存储值、rows affected 或返回错误。

#### Scenario: 成功 INSERT

- **WHEN** 合成 row 通过参数化 logger 成功写入隔离 SQLite
- **THEN** 重新读取的 token、header 与向量值与输入 exact 相同

#### Scenario: 约束失败

- **WHEN** 相同主键再次 INSERT
- **THEN** 调用方仍收到数据库约束错误，且已存在 row 不变

### Requirement: L3 生产入口必须显式使用安全 logger

唯一生产 `initDatabase` 组合 SHALL 显式设置本 Change 的参数化 GORM logger，
不得依赖 GORM 全局默认值或环境日志级别来决定是否泄露参数。

#### Scenario: 默认运行配置

- **WHEN** WeKnora 以 PostgreSQL 或 SQLite driver 初始化数据库
- **THEN** 返回的 GORM handle 使用参数化 logger，且数据库 driver/DSN/迁移行为
  不因本 Change 改变
