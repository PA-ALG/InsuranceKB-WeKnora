# knowledge — S2→S3 主链（Claim 落库、增量合并、审核门禁、页面发布）

change 007 落点；数据模型/权威序/发布契约以 `docs/insurance-kb/03-knowledge-model.md` 为唯一权威。

## 职责与入口

| 模块 | 职责 |
|---|---|
| `tables.py` | 知识域 ORM（claims/claim_evidence/claim_revisions/change_sets/change_items/conflicts/review_items/release_snapshots/snapshot_claims/current_release；迁移 `migrations/versions/0002_knowledge_domain.py`） |
| `authority.py` | doc_role → 权威等级（03 §6.1）、离散置信度 → 浮点 |
| `importer.py` | pred JSONL（compiler.PredRecord）→ ProposedClaim → 合并引擎；记录级/批级幂等 |
| `merge.py` | 增量合并引擎：add/enrich/supersede/conflict/retract；裁决序严格 03 §6.2（④=claude-session 队列占位，零模型调用）；审核动作 approve/reject/defer；翻案=新 ChangeSet |
| `review.py` | ReviewItem 内容稳定 ID（sha256 派生）+ 受限动作集 |
| `pages.py` | published Claims → 产品限定页 Markdown（分组渲染 + 证据角标） |
| `publisher.py` | 经 adapters/weknora 写 wiki 页（03 §7 契约）；ReleaseSnapshot + current_release 指针；回滚=按快照重发布 |

## 与其他包的关系

- 上游：`compiler/`（pred.jsonl 行格式与 judge-queue 形态，只读复用）、`db/`（Base 与产品主数据）、`schemas/`（字段风险级与展示名）；
- 下游：`adapters/weknora`（唯一允许出现 WeKnora API 细节的位置）。

测试：`tests/test_knowledge_*.py`（spec 编号 K1~K6 一一对应）；发布器全 respx mock，live 契约留 `-m live`。
