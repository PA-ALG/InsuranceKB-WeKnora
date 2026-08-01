# 055 · Validation report

## Candidate identity

- base：`ad99ca9a3e658e7d0fd768164f7aab247fe92933`
- branch：`codex/055-weknora-sensitive-log-redaction`
- state：`GREEN COMPLETE / FROZEN FOR EXTERNAL REVIEW`

## Root-cause evidence

- production `internal/container.initDatabase` 调用 `gorm.Open` 时只设置 `NowFunc`；
- GORM `v1.31.1` 默认 logger 的 `ParameterizedQueries=false`；
- callback 在 Trace 前通过 Dialector `Explain` 把 params 插回 SQL；慢 SQL与执行
  error 两个分支都会输出该 SQL。

## RED → GREEN

- root-cause reproduction：GORM 1.31.1 非参数化 error Trace 对合成重复 INSERT
  输出完整 `synthetic.jwt.auth-token-secret`、Authorization header 值与
  `[0.125,-0.5,0.75]`；测试按预期复现。
- logger RED：安全 constructor 尚不存在时 focused test 编译失败：
  `undefined: newSensitiveGORMLogger`。
- production-wiring RED：未接线时 `initDatabase` 的 ParamsFilter 保留两个敏感
  params，focused test 按预期失败。
- error-detail RED：即使 SQL 已参数化，合成数据库 error 文本仍泄露 token/header/
  vector 且缺少固定 redacted marker。
- GREEN：GORM callback 在 Explain 前得到空 params；慢 SQL 和失败 INSERT 只输出
  SQL 结构与占位符。logger 收到的 error 副本固定为
  `[database error details redacted]`，调用方仍收到原始数据库约束错误。
- storage invariant：成功 INSERT 后隔离 SQLite 逐字段读回 token/header/vector，
  与输入 exact 相同。

## Gates

- focused logger 四节点：PASS。
- production `initDatabase` wiring 单节点：PASS。
- `go test ./internal/logger -count=1`：PASS。
- `go vet ./internal/logger ./internal/container`：PASS。
- gofmt：PASS。
- OpenSpec055 strict / diff-check / exact九路径与100644 mode：PASS。
- private/secret：PASS；唯一 secret-pattern match 是 focused test 中具名
  `synthetic-header-secret` 合成哨兵，无真实 credential。
- full / provider / live / PostgreSQL / existing WeKnora DB：`NOT RUN`。
