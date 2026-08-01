# 055 · Tasks

## 合同与 RED

- [x] T1 从 exact main `ad99ca9a3e658e7d0fd768164f7aab247fe92933`
  创建隔离 worktree，锁定九路径。
- [x] T2 追踪 GORM Trace 参数插值链，冻结根因为生产未显式启用参数化日志。
- [x] T3 先写 focused RED，以合成 token/header/vector 复现慢 SQL 与失败 INSERT
  泄露。

## 最小 GREEN

- [x] T4 新增最小参数化 GORM logger，并接入唯一生产 `initDatabase` 入口。
- [x] T5 证明慢 SQL、失败 INSERT 都不出现合成敏感值，只保留 SQL 结构/占位符。
- [x] T6 证明 SQL 执行、存储值、rows affected 与业务错误语义不变。

## 门禁与交付

- [x] T7 focused Go tests、gofmt、go vet、OpenSpec055 strict、diff-check、exact
  scope/private/secret。
- [x] T8 冻结 stable candidate，等待两路独立 review；不commit/push/PR。

## NOT RUN

full、provider、live、PostgreSQL、真实 WeKnora DB、真实日志与 secret 不属于本
Mission。
