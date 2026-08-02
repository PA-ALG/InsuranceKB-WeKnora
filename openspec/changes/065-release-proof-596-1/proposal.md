# 065 · 596-1 Release/CAS/pinned-read/revert proof runner

## 状态

`STABLE CANDIDATE / EXTERNAL AUTHORITY NOT PROVIDED / NO PROVIDER OR PG RUN`

## 用户价值

059 已交付并合入 experimental Release、Active Head、CAS、pinned read 与 revert surface，但
596-1 纵向闭环还缺一个任务专用、可重复执行的证明入口。065 只组合现有 059
service/repository：用 Total Control 未来注入的 exact authority envelopes 和 hashes，
证明 `none -> R0/e1 -> R1/e2 -> R0/e3`、竞态单胜者、pinned read 与回滚合同。

该 runner 是 proof tool，不是 serving authority。WeKnora Active Head 继续是唯一生产 serving
authority；runner 不新增 HTTP 路由、签名平台、migration、DB schema 或通用发布框架。

## 冻结边界

- 输入必须显式提供两组 canonical human-decision/publish-authorization bytes，以及
  candidate、batch、policy、release、artifact、human-receipt 的 exact lowercase SHA-256；
- 其中 release/artifact 是上游049 Golden identity，只作为外部custody输入原样绑定，
  不得冒充或替换059自身的 Wiki manifest digest/member identity；
- runner 只校验并消费这些 authority，不生成 key、签名、decision、authorization、
  receipt 或默认 hash；
- 三个 task-local Release ID 由 Total Control 与签名 envelope 一起显式注入，只用于
  059事务寻址且不进入脱敏receipt；runner不暗藏ID命名约定；
- Head序列、pinned read、正式revert与事务回滚必须由现有
  `WikiReleaseService`/`WikiReleaseRepository` 执行；runner只在内存 SQLite 中以既有五表
  模型建立一次性事务证明库；
- 因本轮禁止外部PostgreSQL，并发单胜者使用一个task-local deterministic CAS fake；它只
  证明同一expected Head下的一胜一typed loser，receipt必须明确标记
  `DETERMINISTIC_CONCURRENCY_PROOF_NOT_PG`，不能冒充生产数据库并发证据；
- 真实059 service/repository独立完成正式revert、R0/e3与五表计数证明；不新增 migration
  文件、外部 DB 写入、通用事务抽象或第二套 release platform；
- proof receipt 只包含稳定状态、四阶段计数、输入 hash 和 C0 domain-separated digest，不含
  member body、secret、完整 principal/Space/KB 标识或签名原文；
- 真实外部 PG、provider、live、WeKnora 与 full suite 均不运行。

## 路径预算

065 最多六路径：四个 OpenSpec 文件，加一个 task-local Go command 和一个 focused
test。README registry 当前由另一 Owner 占用，本 change 不修改 README。若 GREEN
必须修改 production service/repository/types、增加第七路径或引入新架构，立即停止。
