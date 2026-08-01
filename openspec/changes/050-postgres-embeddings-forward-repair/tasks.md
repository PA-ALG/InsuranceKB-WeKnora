# 050 · Tasks

## 合同与 RED

- [x] T1 从 exact `origin/main=130e73d1607cc256c7ce956456873ca0567433d8`
  创建隔离 worktree，占用 OpenSpec 050，并锁定十一条 load-bearing 路径。
- [x] T2 冻结 enterprise forward migration、skip、无损和保守 down 合同。
- [x] T3 先写 PostgreSQL RED，复现 official ledger 已推进、PostgreSQL retrieval
  active、`embeddings` 缺失且 repository 1024 维写入不可达。

## 最小 GREEN

- [x] T4 新增 enterprise migration `000003` up/down，并只更新 packaged enterprise
  head；不修改 official migrations。
- [x] T5 证明 legacy缺表升级、健康已有表no-op、partial已有表typed拒绝且ledger不
  推进、skip不误建、down/up幂等和1024维transaction rollback。

## 门禁与交付

- [x] T6 focused PostgreSQL、相关 Go tests、Ruff/mypy适用性、OpenSpec050 strict、
  diff-check、exact scope/private/secret。
- [x] T7 冻结 exact candidate，等待两路独立 review；不commit/push/PR。

## NOT RUN

full、provider、live、真实WeKnora数据库、PDF upload/reparse和模型调用不属于本
Mission。
