# W1 WeKnora Revision Manifest · 最小 API 规格草案

> 依据：033 §4.4 第 2 项 + 037 `w0-evidence-report.md`（两份合同均
> insufficient）。定位：单个小型 Go PR，只补足 W0 证明缺失的**版本化
> lifecycle/manifest/snapshot 读取面**。SHALL NOT 引入 webhook、共享数据库
> 读取、新的 Asynq 耦合或第二套解析器；解析/删除的既有 delete-and-rebuild
> 流程保持不变。

## 1. 要解决的、且仅解决的缺口（对应 W0 证据）

| W0 缺口 | W1 机制 |
|---|---|
| 公开 API 无单调 parse attempt（trace `current_attempt` 为 best-effort 观测量） | `parse_attempt` 成为服务端事务分配的一等列，随 revision 提交返回 |
| completed 无法绑定 parser/chunker 身份与强文件 digest | 不可变 `knowledge_revisions` 行：`file_digest(sha256)` + `parser_identity` 快照 + `completed_at` |
| 无服务端 ordered chunk manifest digest（`content_hash` 为空） | 提交事务内计算并固化 `chunk_manifest` digest |
| 分页读取无法证明同一 attempt 完整快照（3/3 观察到旧新混合、缺页、无标记） | attempt 绑定的 chunk 读取端点：页内容按 attempt 过滤 + 双检，attempt 被替换时给 410 而非静默混版 |
| 删除后 404 与"从未存在"同形，无 tombstone | revision 端点对软删除行返回 410 tombstone（利用既有 gorm 软删除数据，无新事件机制） |

## 2. 数据模型（1 个 migration）

```sql
CREATE TABLE knowledge_revisions (
    knowledge_id   varchar(36) NOT NULL,
    parse_attempt  bigint      NOT NULL,          -- 服务端事务分配，单调
    tenant_id      bigint      NOT NULL,
    file_sha256    varchar(64) NOT NULL,          -- 上传流式计算并持久化
    parser_identity jsonb      NOT NULL,          -- 见 §4，提交时快照
    manifest_algorithm varchar(64) NOT NULL,      -- 'sha256/chunk_index:id:sha256(content)/v1'
    manifest_digest varchar(64) NOT NULL,
    chunk_count    int         NOT NULL,
    completed_at   timestamptz NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (knowledge_id, parse_attempt)
);
ALTER TABLE knowledges ADD COLUMN current_parse_attempt bigint NOT NULL DEFAULT 0;
ALTER TABLE knowledges ADD COLUMN file_sha256 varchar(64) NOT NULL DEFAULT '';
ALTER TABLE chunks     ADD COLUMN parse_attempt bigint NOT NULL DEFAULT 0;  -- 0 = 传承数据
```

- 行不可变：`knowledge_revisions` 只 INSERT，不 UPDATE；同一
  `(knowledge_id, parse_attempt)` 唯一。
- 历史 revision 行在 chunk 被下一次 reparse 删除后仍保留（用于审计与
  410 语义），knowledge 硬删时级联删除。

## 3. attempt 分配与提交语义（事务边界）

1. **分配**：`CreateKnowledgeFromFile` 与 `ReparseKnowledge` 在写
   `parse_status=pending` 的**同一 DB 事务**内执行
   `current_parse_attempt = current_parse_attempt + 1`，并把该值放入任务
   payload。与 trace/OpenAttempt 完全解耦（trace 失败不影响，二者可以不
   相等；`/spans` 保持观测用途不变）。
2. **写入**：worker 插入 chunk 时携带 `parse_attempt`。
3. **提交**：worker 在把 `parse_status` 翻到 `completed` 的**同一 DB
   事务**内：按 `chunk_index ASC` 读回本 attempt 的 text chunk，计算
   manifest digest，INSERT `knowledge_revisions` 行。事务失败则整体失败
   （状态不翻 completed）。
4. `failed/cancelled` attempt 不产生 revision 行；cancel 保留的旧 chunk
   因 attempt 过滤不会被绑定读取返回。

## 4. `parser_identity` 快照字段

提交时从构建信息与**已解析的有效配置**（非 KB 当前可变配置）固化：

```json
{
  "app_commit": "5eefa70e6fc8…",
  "docreader_version": "<build info>",
  "chunker": {"chunk_size": 512, "chunk_overlap": 50, "separators_sha256": "…"},
  "enable_multimodel": false,
  "embedding_model_id": "…"
}
```

## 5. 端点

### 5.1 `GET /api/v1/knowledge/:id/revision`

当前已提交 revision 描述符（唯一权威读取面）。

- 200：
  ```json
  {
    "success": true,
    "data": {
      "knowledge_id": "db15bea9-…",
      "parse_attempt": 3,
      "file_digest": {"algorithm": "sha256", "value": "d70b9139…"},
      "parser_identity": { … §4 … },
      "chunk_manifest": {
        "algorithm": "sha256/chunk_index:id:sha256(content)/v1",
        "digest": "…", "chunk_count": 42
      },
      "completed_at": "2026-07-27T01:13:54.449839+08:00"
    }
  }
  ```
- 409 `{"error":{"code":"revision_not_committed"}}`：存在 knowledge 但从未
  成功 completed，或当前 attempt 仍在 pending/processing/finalizing（body
  附 `parse_status` 与 `parse_attempt`，供 lifecycle 轮询）。
- 410 `{"error":{"code":"knowledge_deleted","tombstone":{"knowledge_id":"…",
  "deleted_at":"…"}}}`：软删除 tombstone（Unscoped 查询既有软删行）。
- 404：该 id 从未存在（与 410 明确区分）。
- ACL：沿用既有 KB 白名单 + retrieve capability。

### 5.2 `GET /api/v1/knowledge/:id/revisions/:attempt/chunks?page=&page_size=`

与 manifest 绑定的 chunk 页读取。

- 服务端逻辑（双检，无锁）：
  1. 读 revision 行 `(id, attempt)`；不存在 → 404 `revision_not_found`；
     不是当前已提交 attempt → 410 `revision_superseded`（body 附
     `current_parse_attempt`）。
  2. `SELECT … WHERE knowledge_id=:id AND parse_attempt=:attempt AND
     chunk_type='text' ORDER BY chunk_index ASC OFFSET/LIMIT`。
  3. 复读 revision/knowledge 当前 attempt；若已变化 → 410（丢弃页）。
- 200 信封在既有 `data/total/page/page_size` 之上**每页回显绑定头**：
  ```json
  {"success": true, "data": [ …chunk… ],
   "total": 42, "page": 2, "page_size": 5,
   "revision": {"knowledge_id": "…", "parse_attempt": 3,
                 "manifest_digest": "…", "chunk_count": 42}}
  ```
- 客户端合同：所有页 `revision.parse_attempt/manifest_digest` 相同且页并集
  数量 == `chunk_count` ⇒ 即为该 manifest 的完整快照；任何 410 ⇒ 重新走
  5.1 → 5.2。不再依赖 updated_at/seq_id/id-集合启发式。
- 分页语义沿用既有 clamp（`page_size` ≤100、越界空页）。

### 5.3 既有响应的增量字段（向后兼容，只增不改）

- `GET /api/v1/knowledge/:id` 与 KB knowledge 列表项增加：
  `current_parse_attempt`（0 表示尚无提交）、`file_sha256`。
  ——lifecycle 轮询者不必逐个调 5.1 即可看到单调 generation 与强 digest。

## 6. 明确不做

- 不加 webhook / 事件推送；消费方仍轮询（P4a 语义不变）。
- Harness 不读 WeKnora DB/Redis/Asynq；本草案全部经 REST。
- 不引入第二套解析器；不改 docreader；不改 delete-and-rebuild 与
  pending/processing/finalizing/completed 状态机本身。
- 不追溯回填历史 attempt（`parse_attempt=0` 传承 chunk 不可绑定读取，
  需要绑定时触发一次 reparse 生成首个 revision）。
- 不改 `/spans`（继续作为观测面）。

## 7. PR 体量与验收

- 触面：1 migration；`knowledge_create/knowledge_process` 两处事务内
  attempt 分配与 revision 提交；2 个新 handler + 路由/API-key 声明
  （retrieve）；upload 路径补 sha256 流式计算。预估 net ≤ ~600 行 Go。
- 验收 = 重放 W0 探针并新增：
  1. T4 复刻：走查中 reparse，绑定端点必须以 410 终止旧走查（0 次静默
     混版，≥3 次重复）；
  2. T2 复刻：5.1 的 `parse_attempt/manifest/completed_at` 在
     completed 可见的同一瞬间原子可见（同事务）；
  3. T5 复刻：删除后 5.1 返回 410 tombstone 且与 404 可区分；
  4. manifest digest 与客户端按同算法重算值逐字节一致。
