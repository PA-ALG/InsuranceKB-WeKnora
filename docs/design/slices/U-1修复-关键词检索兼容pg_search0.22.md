# U-1 修复：关键词检索兼容 pg_search 0.22

> 状态：Spec 冻结（2026-10-30，Claude）。实现方 Claude，审核方 Codex。关联 #451（U-1）、#470（v0.9.0 上线）。
> 真实调用：实现阶段 0；上线后复核见 §5。

## 1. 问题

v0.9.0 上线（#470）后，快问快答回归 10 题中 q24（1824 合同内容变更的形式）稳定退化：只检索到条款目录里的“7.9 合同内容变更”一行，没有检索到条款正文，回答“无法说明具体形式”（上线后 3 次运行均如此；上线前通过）。

## 2. 根因（只读核对，线上 pg_search 0.22.6）

- v0.9.0 在关键词检索（`internal/application/repository/retriever/postgres/repository.go` `KeywordsRetrieve`）里新增了生成问题行的排除条件 `generatedQuestionExclusionClause`：对“关闭了问题生成”的文档知识库，WHERE 中追加
  `NOT (knowledge_base_id IN (…) AND source_type = 0 AND chunk_id <> '' AND source_id <> chunk_id AND substr(source_id, 1, length(chunk_id) + 1) = chunk_id || '-')`。
- 本项目的受管 RAW KB 都关闭了问题生成，因此每次关键词检索都带上这个条件。
- 线上 ParadeDB 的 pg_search 为 **0.22.6**。在只读事务中实测：
  - 原有形状（`content ||| …` + `paradedb.score(id)` + 排序）返回 10 行；
  - 追加上述 `NOT (… AND …)` 条件后报 `ERROR: Unsupported query shape`（SQLSTATE XX000）。
- 关键词检索报错后，混合检索只剩向量一路：知识库混合检索接口的结果与纯向量结果逐行相同（全部 `match_type=0`），关键词一路的接口直接返回 500。**这影响所有受管 RAW KB 的检索，不只 q24**；q24 只是排在边界上的条款正文最先掉出。
- 上游 000115 迁移只在镜像提供 pg_search 0.25.11 时升级扩展；线上仍为 0.22.x，U-1 阶段 b 把 ParadeDB 升级判为“可解耦”，没有发现 v0.9.0 的关键词 SQL 依赖更新的 pg_search。

## 3. 改动

把排除条件从“与 BM25 条件同级的 `NOT (… AND …)`”改为**反连接子查询**：

```
id NOT IN (SELECT id FROM embeddings WHERE knowledge_base_id IN (…) IS NOT FALSE AND (<生成问题行谓词>) IS NOT FALSE)
```

- 语义不变：原条件 `NOT (K AND P)` 会过滤 `K AND P` 为 TRUE **或 UNKNOWN** 的行（如 `chunk_id IS NULL`），子查询因此选取 `(K AND P) IS NOT FALSE`，写成等价的 `K IS NOT FALSE AND (P) IS NOT FALSE`（AND 当且仅当一侧为 FALSE 时为 FALSE；PostgreSQL 中 `IN` 优先级高于 `IS`）。仍在 TopK 之前排除；没有命中行时结果与无排除条件完全相同。（#471 审核 R1 修订，2026-10-30）
- 线上 pg_search 0.22.6 只读实测该形状可执行并返回 10 行；它是普通 SQL，不依赖 pg_search 版本。
- 向量检索的同名排除条件走 pgvector，不经 pg_search 自定义扫描，本片不改。
- SQLite 检索不受影响，不改。

改动落在上游文件 `repository.go`（G10 168 → 169）。原因：检索 SQL 没有扩展点可挂，包一层仓储只能在 TopK 之后过滤，语义不同。登记 `docs/design/upstream-patches.md`，退出条件：ParadeDB 升级到 pg_search ≥ 0.25 并验证原形状可执行，或上游采用兼容写法（本修复拟提交上游）。

## 4. 验收

- RED（受保护）与补充验收（#471 R1，新文件 `keyword_exclusion_semantics_test.go`：sqlmock 钉住 `IS NOT FALSE` 形状；内存 SQLite 逐行对照原 `NOT (K AND P)` 的三值语义，覆盖 NULL/空串 chunk_id、NULL KB、正常正文、生成问题行、其他 KB，以及 TopK=1 的 NULL chunk 反例）：
  1. sqlmock：带 `ExcludeGeneratedQuestionKBIDs` 时，关键词检索 SQL 使用 `id NOT IN (SELECT id FROM embeddings WHERE …)`，不再出现与 `|||` 同级的 `NOT (knowledge_base_id IN …)`；不带时 SQL 与原来相同。
  2. 真实 ParadeDB（环境变量 `WEKNORA_RETRIEVER_TEST_PARADEDB_DSN` 开启，本机用与线上同版本 pg_search 0.22.6 的镜像跑）：建表与 BM25 索引，写入普通行与生成问题行，带排除条件的关键词检索不报错、返回普通行、不返回生成问题行。
- 受影响包 `go test`、golangci-lint（改动行）、架构守卫（G10 只多这一项且已登记）、`git diff --check`。

## 5. 上线与复核

App 换镜像（无迁移）。上线后：
- 知识库混合检索接口在 RAW KB 上恢复关键词结果（出现 `match_type` 为关键词的命中），关键词一路接口不再 500；
- 快问快答回归 10 题复跑（≤ 30 次发送），q24 预期恢复；如仍未恢复，单独分析排序（v0.9.0 的 composite 分数口径），不在本片处理。

## 6. 不做

- 不升级 ParadeDB（另行评估，需要 BM25 索引重建与线上演练）。
- 不调整 v0.9.0 的 rerank composite 分数口径。
