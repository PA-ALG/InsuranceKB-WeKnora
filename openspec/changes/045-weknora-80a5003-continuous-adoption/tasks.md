# 045 · Tasks（WeKnora `80a5003` Continuous Adoption）

## Contract Card

### 单一职责

持续采用批准的官方不可变 identity，同时无损保留 W1：官方源码/migration
原样跟随，
Harness 插件化，enterprise migration 独立 ledger，legacy `000066` 经一次
可证明兼容桥收敛。

### 权威

- Tencent exact commit/tree/checksum（stable tag 或批准的 mainline snapshot）：
  official source authority；
- `schema_migrations`：official migration authority；
- `enterprise_schema_migrations`：enterprise migration authority；
- patch inventory：唯一允许的 WeKnora project delta；
- trusted image digest/provenance：runtime identity authority；
- Harness 仍拥有保险领域逻辑，WeKnora 不获得新领域 authority。

### 失败边界

identity 漂移、dirty/partial/unknown schema、checksum mismatch、未登记 patch、
W1 contract regression、备份/恢复证据缺失均 fail closed；不得 force、
drop/recreate、清空数据库或静默继续。

### 范围警报

- `MAINLINE DRIFT`：升级被扩成 P2d/P3/P11/P13/P14 或产品新功能；
- `DETAIL TRAP`：只修一个 SQL 文件/版本号，却没有持续升级、两 ledger、
  四状态与 artifact 合同；
- `UNREVIEWABLE DELTA`：把大规模 upstream vendor delta 与 project-authored
  逻辑混为一体，无法分辨真实补丁。

## Spec-only 清单

- [x] S1 用户批准“官方持续跟随 + Harness 插件化 + 企业迁移独立记账”；
- [x] S2 用户确认任何现有数据库不可清空/重建；
- [x] S3 核验 v0.7.1 ancestor、目标
  `80a5003cc99a427098afe184eee6601916d3d156`、tree、17-commit/122-path
  增量、官方 `000075` 与双方 `000066` 的真实语义；
- [x] S4 冻结四状态、unknown fail-closed、双 ledger 与 collision 合同；
- [x] S5 冻结 Code/Artifact 两阶段交付及主航道非目标；
- [x] S6 strict OpenSpec、diff/scope/UTF-8/private/secret 门禁；
- [x] S7 对 exact `80a5003` 修订重新执行独立 Spec + Mainline/YAGNI review：
  BLOCKER/BACKLOG=0，MAINLINE DRIFT/DETAIL TRAP=NO，
  Spec/Mainline/YAGNI Approved=YES；
- [x] S8 用户审阅书面规格后批准 implementation plan，并确认后续升级须可通过
  同一入口发现最新 stable 或 mainline-head、解析为 exact commit/tree 后复用门禁。

## Code PR（实现前必须由用户批准书面规格）

- [ ] C0 从实现时最新项目 `origin/main` 新建唯一 writer worktree；核验官方
  target 仍精确为 `80a5003...`/tree `18fcf68e...` 且 ancestry 可证明；
  不自动漂移到 upstream mutable main；
- [ ] C1 RED：官方 tag/source/migration checksum 漂移门禁；
- [ ] C2 RED：migration collision inventory 覆盖编号、schema object、patch
  surface，分别证明真实 project merge-base delta 与 source-lock runtime
  delta，先复现 legacy `000066` 冲突；
- [ ] C2a RED：machine-readable Harness plugin contract 覆盖 REST envelope、
  typed error、principal/authoritative Space binding/current tenant+RAW-KB ACL、
  allowed read/denied mutation/zero-write、retry/idempotency、forbidden coupling
  与 exact validation nodes；W1 runtime、consumer adapted、source-reader
  authority 三态不得互相冒充，私有 Go symbol 不得成为兼容权威；
- [ ] C3 RED：PostgreSQL 16 四状态 matrix；每态验证数据 count/digest、
  official/enterprise ledger、span type 与 W1 schema；
- [ ] C4 RED：dirty、partial、unknown、preflight race、双实例 race 全部零写；
  bridge 后/official 后 crash checkpoints 均可幂等续跑；
- [ ] C5 GREEN：同步官方 `80a5003` source/migrations（official head 75）；
  保留 machine-readable upstream identity，不手工挑选 upstream commits；
- [ ] C6 GREEN：将 W1 active migration 移入 enterprise source/ledger，保留
  legacy SQL/checksum fixture；
- [ ] C7 GREEN：实现只读 classifier、transactional compatibility bridge、
  official→enterprise 顺序 migrator 和分离状态观测；
- [ ] C8 GREEN：在 `80a5003` 重放 W1 + redaction patch，更新 inventory baseline、
  exact paths、overlap verdict 和 compatibility tests；
- [ ] C8a 将 source lock 升级为 exact identity + ordered patch + 三镜像定义，
  并让 main-only trusted workflow 可从同一 verified tree 构建 app/frontend/
  docreader；不写 runtime digest 或 adopted 结论；
- [ ] C9 验证官方普通 knowledge/wiki/API 非回归、W1 exact revision/manifest、
  reparse race、删除与 principal/ACL 既有边界；
- [ ] C9a 验证普通 Wiki 单页 history、line diff、manual edit optimistic
  locking、revert 生成新 revision 与 ACL 非回归；不接入 Harness
  Release/P11/P14；
- [ ] C10 focused Go、Ruff/mypy（Harness 受影响时）、OpenSpec、diff-check；
  不运行 provider/live/full；
- [ ] C11 独立 Spec 与 Quality/Security/Delivery review；BLOCKER 清零后才 Ready。

## Artifact PR（Code 合入后）

- [ ] A1 从已合入 main 的 trusted workflow dispatch exact `80a5003...`
  commit/tree，并重放 exact inventory；
- [ ] A2 生成 final tree、image digest、provenance、SBOM、attestation 与
  official/enterprise migration receipt；
- [ ] A3 在四类可恢复备份 clone 上执行 PostgreSQL 16 upgrade + restore drill；
- [ ] A4 W1 capability/live bounded probe，普通 source/wiki 非回归；
- [ ] A5 exact candidate 全绿后更新 source lock、image lock、Compose 与
  HANDOFF/control board；
- [ ] A6 独立 supply-chain/data-safety review 后决定受控 local-live cutover；
- [ ] A7 只有 runtime digest、数据库 evidence 与 Wiki revision bounded
  feature probe 同时闭合，才声明 `80a5003 SNAPSHOT ADOPTED`。

## 明确不执行

- 不在 Spec PR 写生产代码、migration 或 workflow；
- 不对现有 live/PG 数据库试跑；
- 不运行 provider/full/load；
- 不清理历史 worktree/branch/PR；
- 不实现 P2d/P3 ACL、P11/P13/P14；
- 不因官方新特性顺手扩大 Harness 产品面。
