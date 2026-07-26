# 038 · W1 WeKnora Revision Manifest

> 状态：📋 规格起草（W0 触发的条件 W1）。触发依据：037
> `artifacts/w0-evidence-report.md` T6 裁决——`SourceLifecycleContract` 与
> `RevisionManifestContract` 双双 **insufficient**，按 033 §4.4 第 2 项进入
> 条件 W1。
>
> 权威：033 §4.4（W1 最小字段清单与禁区）、§11.4（patch budget 规则）、
> §16 `C0 + W0 → W1 [conditional]` 行、§16.2（PR 颗粒度）、§18（Contract
> Card）。API 内容基线：037 `artifacts/w1-api-draft.md`（T7 产物）；与草案
> 的少量偏离在 spec 内逐条标注理由。本 change 对应 patch inventory
> （`deploy/patches/enterprise-llm-wiki-patch-inventory.yaml`）中已注册的
> `patch_id: W1`（status: planned）。
>
> 本阶段 **SPEC ONLY**：只交付 proposal/specs/tasks 与 README 台账行，
> 不写任何 Go 代码、迁移或测试。

## 为什么做（W0 五条证据线）

W0 在 023 已验收 live 环境 + pinned 源码（运行 commit `5eefa70e`）上以
3 次重复的可复现探针证明，现有公开 API 无法支撑 P4a/P4c 所需合同：

1. **无公开单调 parse generation**（T1/T6.1）：knowledge 对象没有任何
   attempt/generation/revision 字段；唯一单调量 `/spans` 的
   `current_attempt` 是 best-effort trace 观测量——`OpenAttempt` 失败仅
   Warn 并以 attempt=0 继续解析
   （`internal/application/service/knowledge_process.go:1971-1974`），与
   chunk 写入无事务绑定；`processed_at/updated_at` 是时间戳，被 033 §4.4
   明确排除为 revision token。
2. **删除无 tombstone**（T5.3，3/3）：DELETE 异步，约 0.5–1.4s 后
   knowledge 与 chunks 双 404（code 1003），与「从未存在」同形；lifecycle
   消费方只能靠无快照的 offset 列表 diff 推断删除。
3. **文件 digest 仅 MD5、parser/chunker 身份不可绑定**（T2.4）：服务端
   `file_hash` 是 MD5；client 提交的 `metadata.sha256` 不被服务端校验；
   KB `chunking_config` 不回显生效值、可变且无版本——completed 态无法与
   「当时使用的 parser/chunker 身份 + 强文件 digest」绑定成一次不可变读取。
4. **metadata/chunk 交换非原子可见**（T2，3/3）：旧 chunk 集合先清零
   （~600–800ms 窗口）→ 新集合在 `parse_status=processing` 时即完整可读 →
   `enable_status` 在 `finalizing` 先行恢复 enabled → 才到 completed，共 4
   个可外部观察的中间态；pinned 源码确认 cleanup 先于状态写、无共同事务
   （`knowledge_process.go:2056`、`knowledge_delete.go:616-703`）。
5. **分页竞态静默混版且缺页**（T4，3/3）：`page_size=5` 走查中触发
   reparse，一次逻辑走查读到旧新混合集（旧 10 + 新 27/27/22）并丢失新集合
   `chunk_index` 10–14，每一页都是 200、无任何错误或标记；客户端可构造的
   最强防线全部是时间戳/启发式比较，恰是 033 §4.4 与 W0.1 排除的证明形态。

结构性合格项（W1 复用、不重做）：`chunk_index ASC` 稳定排序、offset 分页
clamp/越界语义（`internal/handler/chunk.go:127-128`、
`internal/application/repository/chunk.go:246`）、KB 白名单 × capability
的 ACL 矩阵（T5.4，8/8 符合预期）。

## 本 Change 做什么

按 037 `w1-api-draft.md` 冻结一个**最小版本化 revision/manifest 读取面**
的实现规格（`specs/weknora-revision-manifest/spec.md`）：

- 恰好 1 个 versioned migration：不可变 `knowledge_revisions` 表 +
  `knowledges.current_parse_attempt`/`knowledges.file_sha256` +
  `chunks.parse_attempt`（0 = 传承数据，不可绑定）；
- **事务化 attempt 分配**：与写 `parse_status=pending` 同一 DB 事务，单调
  +1，与 trace `OpenAttempt` 完全解耦（W1.1）；
- **事务化 revision 提交**：与 `parse_status` 翻转 `completed` 同一 DB
  事务内计算并固化 ordered chunk manifest digest、INSERT 不可变 revision
  行，并以 `current_parse_attempt` 复核做提交 fencing（W1.1/W1.5）；
- 2 个新只读端点：`GET /api/v1/knowledge/:id/revision`（typed
  200 completed / 409 in-progress / 410 tombstone / 404 never-existed，
  W1.2/W1.4）与
  `GET /api/v1/knowledge/:id/revisions/:attempt/chunks`（attempt 绑定 +
  每页 revision 回显 + 被替换即 410 `revision_superseded`，绝不静默混版，
  W1.3）；
- 既有 `GET /knowledge/:id` 与 KB knowledge 列表项的**只增不改**字段：
  `current_parse_attempt`、`file_sha256`（W1.7）；
- 上传路径流式计算 sha256 文件 digest；MD5 `file_hash` 原样保留（W1.5）；
- patch inventory W1 行更新为 exact 实现面 + upstream compatibility
  matrix + 普通知识 REST 非回归测试（W1.6）；
- W0 T4 竞态以 RED-style Go contract test 复刻：走查中 reparse 绝不混
  attempt、绝不静默丢 chunk（W1.3 场景 + tasks 验收清单）。

## 不做什么（非目标）

以下明确不属于 W1，出现在实现 diff 中即 scope 违规（033 §4.4 第 2 项
禁区 + §4.3 + inventory `compatibility_tests`）：

- 不加 webhook / 事件推送；P4a 消费方语义仍是轮询；
- 不建立共享数据库读取、Redis/Asynq 耦合：attempt 簿记是 WeKnora 内部
  状态（其 Go 服务 + 其 DB），Harness 只经版本化 REST 消费，绝不共享；
- 不引入第二套解析器；不改 docreader；不改上传/OCR/chunk 算法本身；
- 不改既有 delete-and-rebuild 流程与
  `pending/processing/finalizing/completed/failed/deleting/cancelled`
  状态机本身；
- 不把 LLM Wiki 领域逻辑搬进 Go：端点/表/算法命名全部通用
  （revision/manifest/attempt），设计保持可上游化；
- 不追溯回填历史 attempt：`parse_attempt=0` 传承 chunk 不可绑定读取，
  需要绑定时由消费方触发一次 reparse 产生首个 revision；
- 不改 `/spans`（继续作为观测面）、不动既有端点的请求/响应语义（只增
  字段）；
- 不为超出 W1 的 P11/P13/P14 surface 顺手改动任何文件；
- 不提供历史 attempt 的 chunk 内容读取或保留（superseded 一律 410，
  历史快照持久化归 Harness P4c 的 SourceRevisionArtifact，033 §8.3）。

## 影响面

- **解除 P4a/P4c blocked 的前提**：W1 合入并按 W0 探针复刻重验后，
  P4a（SourceLifecycleContract 消费）与 P4c（RevisionManifestContract
  消费）按 033 §16 DAG 开工；二者必须以 W1.7 capability probe 对旧部署
  fail closed；
- 033 §7 的 metadata 双读正式降级为附加防线（W0 证据表明它连「察觉」都
  依赖时间戳精度）；
- patch inventory：实现 PR 内把 W1 行 `status: planned` 更新为实现状态、
  `file_path` 更新为 exact 实现面、`upstream_issue` 由
  `pending-W0-verdict` 更新为真实上游 issue 引用（W1.6）；本 spec-only
  阶段不改该 yaml；
- 本阶段仓库变更：仅新增 `openspec/changes/038-w1-weknora-revision-manifest/`
  与 `openspec/changes/README.md` 台账 038 行；无任何运行代码变化。

## 依赖与后续

- 依赖：W0（037 证据报告与 API 草案）、C0（033 §8.4 digest 框架口径；
  W1.5 采用其 domain-separator + 版本化 + SHA-256 框架并给出不引入完整
  CanonicalEnvelopeV1 Go codec 的理由与升级路径）、D0（patch inventory
  已注册 W1）；
- 后续：P4a/P4c 消费；上游化——按 inventory `remove_when`，等上游接受
  等价 SourceLifecycleContract/RevisionManifestContract 后移除本 patch；
- 实现窗口：一个独立小 PR，从当时最新 `origin/main` 干净 worktree 开始
  （033 §16.2），预算见 tasks Contract Card（净 ≤ ~600 行 Go 生产代码 +
  tests，恰好 1 个 migration）。
