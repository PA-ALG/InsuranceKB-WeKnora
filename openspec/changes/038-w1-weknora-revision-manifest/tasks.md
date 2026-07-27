# 038 任务（W1 WeKnora Revision Manifest；单个小 Go PR；先冻结 Contract Card 再写代码）

## Contract Card（033 §18）

### 单一职责与非目标

单一领域不变量：**经 W1 读取面取得的任何 chunk 内容都可被密码学绑定到
唯一一次 completed parse attempt 及其不可变 manifest；无法绑定时返回
typed 状态（409/410/404），绝不返回近似或混版数据。** W1 只拥有
`knowledge_revisions` 表、三个新列（`knowledges.current_parse_attempt`
/`knowledges.file_sha256`/`chunks.parse_attempt`）、其唯一 migration、
attempt 分配/提交事务接线与两个新只读端点。非目标（proposal「不做
什么」全文有效）：webhook、共享 DB/Redis/Asynq、第二套解析器、
docreader/上传/OCR/chunk 算法改动、delete-and-rebuild 与既有
parse_status 状态机改动、历史 attempt 内容保留/回填、`/spans` 改动、
LLM Wiki 领域逻辑入 Go、P11/P13/P14 surface。

### 读写权威、事务边界与幂等键

- **权威**：WeKnora Go 服务 + 其自有 DB 是 attempt 簿记与 revision 行
  的唯一读写权威。这是 **WeKnora 内部状态，不与 Harness 共享**——
  Harness/P4a/P4c 只经版本化 REST 消费（033 §4.3/§11.4），不读 WeKnora
  DB/Redis/Asynq。
- **事务边界**：(1) attempt 分配与 `parse_status=pending` 写同一事务，
  且该事务先于旧 attempt 资源销毁提交（分配先于销毁，spec W1.1）；
  (2) revision 提交（manifest 计算 + revision INSERT + `completed`
  翻转 + `current_parse_attempt` fencing 复核）同一事务，仅挂接解析
  管线的 completed 翻转（含 knowledge_post_process 驱动的
  FinalizeSubtask finalizing→completed 提升）；clone/move 等非解析
  completed 写入不触发提交；(3) tombstone 来自既有软删事务，W1 只读。
- **幂等/唯一键**：`(knowledge_id, parse_attempt)` 主键；revision 行
  INSERT-only 不可变（无 UPDATE 路径）；同 attempt 重复提交因主键 +
  状态机 typed 失败；读端点天然幂等。

### 状态机（派生自既有 parse_status，本体不改）

```text
无可服务 revision（从未 completed / in-flight / failed / 非解析
  completed 无行 / file-less 豁免）                         → 409
attempt N 已提交且 current_parse_attempt=N 且 completed     → 200 / W1.3 可读
attempt N 被 N+1 替换（in-flight/failed/新提交）            → 410 revision_superseded
knowledge 软删（保留窗口内）                                → 410 knowledge_deleted
保留窗口外被显式清理                                        → 404（唯一允许的退化）
```

既有 `pending/processing/finalizing/completed/failed/deleting/cancelled`
枚举与转换零修改；W1 只在其提交/失败节点挂接。

### 威胁矩阵

| 威胁 | W1 冻结的处理 |
|---|---|
| 走查中并发 reparse（W0 T4，3/3 混版+缺页） | attempt 过滤 + 页后复核当前可服务 attempt；替换后首个页请求 410 `revision_superseded`；0 混版、0 静默缺页（RED-style 确定性交错合同测试 + live 挂钟复验） |
| 清理先行窗口（W0 T2：cleanup 先于状态写——旧 attempt 看似可服务、chunk 实已缺失；清理失败中止时可永久化） | 分配先于销毁（spec W1.1）：分配事务提交前对旧 attempt 零销毁；分配失败即中止且旧 attempt 完整可服务；分配提交后中断只呈现 typed 409/410，不存在「200 但缺 chunk」 |
| attempt 分配竞态（并发 reparse 双触发） | 分配 = 行级原子自增（与 pending 写同事务），DB 序列化保证不同值；`(knowledge_id, parse_attempt)` 主键兜底 |
| chunk 写入错标 attempt（写入时重读可变列或采用 trace 值） | chunk 行只携带任务 payload 中事务分配的 attempt 值；存活 text chunk 上 `(knowledge_id, parse_attempt, chunk_index)` 唯一索引兜底 |
| 迟到 worker 提交错位（stale attempt 提交） | 提交事务行锁复核 `current_parse_attempt == N`，不等则整体失败、不翻 completed、不写 revision 行 |
| 非解析路径 completed 翻转伪造可服务假象（clone/move、维护性写入） | revision 提交仅挂接解析管线翻转（含 FinalizeSubtask 提升）；其余 completed 行无 revision 行 → typed 409 子况 (d)，绝不 200 |
| tombstone GC 与读竞态 | W1 不引入硬删 GC 也不新增配置接线；软删行在即 410；未来清理 change 拥有窗口配置并遵守窗口内禁硬删、窗口外 410→404 唯一退化 |
| digest 失配（提交后 chunk 编辑等内容漂移） | revision 行不可变、服务端不重算不掩盖；消费方按同算法重算 ≠ 存储 digest 即确定性检出（fail-closed 信号，见 spec W1.5 场景） |
| 存量行迁移（无 attempt 历史） | 传承 chunk `parse_attempt=0`、`current_parse_attempt=0`、`file_sha256` 空；不回填不伪造——0 不可绑定（W1.3 404），首个 revision 只能由新解析产生；空 sha256 在下一次提交前由存量字节补算 |
| tombstone/新端点成为 ACL 旁路 | 新端点全量沿用既有 KB 白名单 × retrieve capability × Viewer × KB 读校验；软删行先解析到 KB 再过同一 ACL；无权限维持既有 403/404，不泄漏存在性 |
| trace 与合同耦合回潮 | attempt 分配与 `OpenAttempt` 解耦；trace 失败不影响分配与提交；`/spans` 仅观测 |

### exact 验收测试清单

1. manifest 算法纯函数 + 语言中立 vectors（空集、单 chunk、多字节
   UTF-8、非连续 chunk_index、`decimal(0)`=`"0"` 编码、重复
   chunk_index typed 拒绝）（unit）；
2. migration/schema 合同：`knowledge_revisions` 列/主键、三个新列及其
   默认值、存活 text chunk 上 `(knowledge_id, parse_attempt,
   chunk_index)` 唯一索引、恰好一对新 versioned migration（只落
   `migrations/versioned/`，mysql/sqlite/paradedb 目录零修改）、历史
   迁移零修改；
3. attempt 分配：与 pending 写同事务（中断则双无）、严格单调、并发
   reparse 双触发得不同值、trace OpenAttempt 失败不影响；**分配先于
   销毁**：分配事务提交前旧 attempt 零 chunk 删除，分配前失败 → 旧
   attempt 仍完整可服务，分配后清理中断 → 仅 typed 409/410；chunk 行
   attempt 值 == payload 分配值（注入「写入时重读 current 列/采用
   trace 值」的实现即失败）；
4. revision 提交：与解析管线 completed 翻转同事务（中断则双无；覆盖
   直接翻转与 knowledge_post_process/FinalizeSubtask 提升两路径）、
   fencing 复核拒绝 stale attempt 提交、failed/cancelled 零 revision
   行、clone/move 非解析 completed 写入零 revision 行、同 attempt 重复
   提交 typed 失败、行不可变（无 UPDATE 面）；
5. `GET /knowledge/:id/revision` 状态矩阵：200 字段完整性与不可变重
   读、409 五种子况（未曾 completed / in-flight / failed-after-
   committed 含 `last_committed` / 非解析 completed 无 revision 行 /
   file-less 来源 `file_less_source`）及机读 `reason` 区分、
   `parser_identity` 分量不可得时显式 `"unknown"`（不缺键不空串不
   失败）、410 tombstone、404 never-existed、ACL 矩阵（ro key 可读、
   无权限 key 既有语义）；
6. `GET /knowledge/:id/revisions/:attempt/chunks`：attempt 过滤恰好性
   （cancel 残留 chunk 不出现）、`chunk_index ASC` 稳定序、clamp/越界
   与既有一致、`total == chunk_count` 恒等、每页 revision 绑定块回显、
   404 `revision_not_found`（attempt=0 / in-flight / 不存在）；
7. **W0 T4 竞态复刻（RED-style，先复现混版基线再转 GREEN）**：Go 测试
   以**确定性交错**构造（页间直接调用分配/清理服务序列或注入点，不依赖
   挂钟竞速），fixture 在所用 page_size 下 ≥3 页；替换后首页请求 410、
   0 混版、0 静默缺页；变体：走查中 DELETE → 410 `knowledge_deleted`
   （对应 inventory「reparse-pagination-delete race rejects mixed
   revisions」向量）；挂钟并发 ≥3 次重复归验收 13 live lane；
8. W0 T2 复刻：`parse_attempt/manifest/completed_at` 与 completed 可见
   性同事务原子（采样读不出现「completed 但无 revision」窗口）；
9. digest 端到端：客户端按 spec 算法对全量页重算 == 存储
   `manifest_digest`；提交后 chunk 编辑 → 重算失配确定性检出且行不变；
10. file sha256：上传流式计算持久化、legacy 行提交前补算、空 sha256
    零提交路径；MD5 `file_hash` 不变；
11. 兼容与探测：既有 knowledge/chunk 端点全量非回归（仅两个新增字段，
    零值仍序列化）、新端点仅 retrieve 声明、capability probe 对含/不含
    W1 的部署二值判定、错误码稳定映射；
12. patch surface：diff 文件集 == inventory `file_path`（更新后）==
    允许面；`status/upstream_issue` 已更新；
13. live 复验（受控 lane）：在 023 live 环境重放 W0 探针 p2/p4/p5 的
    W1 版本（绑定端点走查、原子可见性采样、删除区分），挂钟并发下全
    流程重复 ≥3 次；未运行时如实报告 NOT RUN。

1–12 为 Go 合同测试（unit + DB integration lane）；13 为受控 live
lane，遵循 CLAUDE.md 验证约定，不以模拟结果冒充 live 证据。

### 路径预算

- 生产净增 ≤ ~600 行 Go（037 草案口径；超过约 900 行触发重新切分评审，
  033 §16.2），tests 另计；
- 恰好 1 对新 versioned migration（`migrations/versioned/` 下一个空闲
  号，占号遵守 README 台账规则）；历史迁移零修改；
- 逻辑文件 ≤ ~14：migration up/down、`internal/types/`（knowledge.go/
  chunk.go 加列 + revision 类型）、`internal/application/repository/`
  （revision 存取、`chunk.go` attempt 过滤、`knowledge.go` 的
  `FinalizeSubtask` 提交挂钩）、
  `internal/application/service/knowledge_create.go`（上传 sha256 +
  分配）、`internal/application/service/knowledge_process.go`（reparse
  分配先于销毁的顺序重排 + 直接翻转路径提交 + fencing）、
  `internal/application/service/knowledge_post_process.go`
  （FinalizeSubtask 提升路径的提交接线）、`internal/handler/`（新只读
  revision handler）、`internal/router/router.go`
  （`RegisterKnowledgeRoutes` kRead 组两条路由）、
  `deploy/patches/enterprise-llm-wiki-patch-inventory.yaml`（W1 行
  更新）+ 对应测试文件。较 037 草案多出的两个文件
  （knowledge_post_process.go、repository/knowledge.go）是同一提交
  不变量在既有 completed 翻转点上的薄接线，不引入第二不变量，仍在
  033 §16.2 的 10–15 逻辑文件带内。

## Tasks

严格 TDD：每任务先落 RED 再实现 GREEN；本 change 为 spec-only，以下
T1–T13 属于未来实现 PR 的执行顺序（T13 为合入前独立复审；开工前先按
HANDOFF/控制板取得实现窗口授权，并从当时最新 `origin/main` 干净
worktree 开始）。

- [x] T1 RED：manifest 算法 vectors 单元测试（验收 1，含重复
  chunk_index typed 拒绝与多字节 UTF-8 内容逐字节语义）。GREEN：纯
  函数 digest 实现 + 固定 vectors 文件（供 Harness 复用）。
- [x] T2 RED：schema/migration 合同测试（验收 2）。GREEN：在
  `migrations/versioned/` 占号写唯一 up/down 对 + types 加列/新类型
  （`parse_attempt` 默认 0、`file_sha256` 默认空、revision 表主键与
  NOT NULL 约束）。
- [x] T3 RED：attempt 分配事务/并发/trace 解耦 + **分配先于销毁** +
  payload 传递测试（验收 3）。GREEN：`knowledge_create.go`/
  `knowledge_process.go`（含 manual 重建路径）在 pending 写事务内原子
  自增并注入任务 payload；重排重建路径使分配事务先于
  `cleanupKnowledgeResources` 提交；chunk 写入逐行携带 payload 分配值
  （不重读、不用 trace 值）。
- [x] T4 RED：revision 提交原子性 + fencing + 失败零行 + 不可变测试
  （验收 4、8，覆盖直接翻转与 FinalizeSubtask 提升两路径、clone/move
  非解析 completed 零 revision 行）。GREEN：解析管线完成翻转的提交
  事务（按 `chunk_index ASC` 读回本 attempt text chunk → 算 digest →
  INSERT revision → fencing 复核 → 翻 completed），接线于
  `knowledge_process.go` 与 `knowledge_post_process.go`/
  `repository/knowledge.go(FinalizeSubtask)`。
- [x] T5 RED：`/revision` 状态矩阵 + ACL 测试（验收 5，覆盖
  failed-after-committed 的 `last_committed` body、409 子况 (d) 非解析
  completed 与 (e) file-less 的机读 `reason`、`parser_identity`
  `"unknown"` 行为）。GREEN：revision handler +
  `RegisterKnowledgeRoutes` kRead 路由（retrieve capability）+
  tombstone Unscoped 读（先 KB ACL 后 410）。
- [x] T6 RED：绑定 chunk 读端点语义测试（验收 6）。GREEN：attempt 过滤
  repo 查询 + 分页 clamp 复用 + 每页 revision 绑定块 + 页后复核。
- [x] T7 RED：**W0 T4 竞态复刻合同测试（确定性交错）**——先在无绑定
  端点语义下复现旧新混合/缺页作为 RED 基线，再断言绑定端点 0 混版
  0 缺页、替换后 410；交错经页间直接调用分配/清理序列（或注入点）
  构造，fixture ≥3 页；加 DELETE 变体（验收 7；挂钟 ≥3 次重复归 T12
  live lane）。GREEN：双检窗口收口，不引入锁或快照存储。
- [x] T8 RED：tombstone 持续性与退化边界测试（验收 5/13 的窗口子
  项）：软删行存在期间 410 持续可读；测试内模拟窗口外清理（直接硬删
  软删行）后 404 且为唯一退化。GREEN：无新增配置/GC 生产代码（W1 不
  交付清理与窗口配置接线；若 T5 实现已满足则本任务只固化不变量测试）。
- [x] T9 RED：file sha256 流式计算 + legacy 补算 + 空值零提交测试
  （验收 10）。GREEN：上传路径 sha256 + 提交前补算分支。
- [x] T10 RED：兼容/探测测试（验收 11）：既有端点非回归快照、新增字段
  零值仍序列化、probe 二值判定、错误码稳定表。GREEN：响应字段接线
  （无 omitempty）+ 错误码常量表。
- [x] T11：patch inventory W1 行更新（exact `file_path`/`status`/
  `upstream_issue`）+ patch surface 比对脚本或断言（验收 12）+
  upstream compatibility matrix 记录（基线 `5eefa70e`，四项
  `compatibility_tests` 向量）。按本次 Mission Card 的项目边界，
  `upstream_issue` 明确记录为 `not-filed-project-owned-thin-adapter`；
  本 PR 不创建或处理 Tencent 通用上游事项。
- [x] T12 收尾：focused Go tests → `go vet`/lint → `openspec validate
  038-w1-weknora-revision-manifest --strict` → migration 合同门禁 →
  validation report。按本次 Mission Card，真实 PG/受控 live lane 如实
  记为 NOT RUN；`openspec/changes/README.md`、控制板与 `HANDOFF.md`
  属共享收尾文档，待本 PR 合并后另行更新，本 PR 禁止触碰。
- [x] T13 独立 Spec/质量复审：按冻结合同查正确性与安全性；复审中出现
  新的同域基础不变量时，按 033 §18 停止补丁循环回到边界设计，不追加
  状态与异常分支。

完成 T12 前不得宣称 W1 验收达成；P4a/P4c 在 W1 合入并重验前保持
blocked，不得提前接线。
