# W0 WeKnora Revision Contract Spike · Evidence Report

> 执行日期：2026-07-27（本机 live 环境，OpenSpec 023 已验收拓扑）。
> 授权：037 proposal / tasks（T1–T7）；权威：033 §4.4。
> 本报告只含脱敏内容：不出现任何 key/token/DSN/Authorization/账号身份；
> 凭据一律以 `<REDACTED>` 表示。

## 0. 环境与方法（可复现前提）

**被测系统**（与 023 供应链锁定完全一致）：

- App API：`http://127.0.0.1:8080/api/v1`（容器 `WeKnora-app`，HTTP 200 健康）。
- 运行镜像：`ghcr.io/pa-alg/insurancekb-weknora-app:src-5eefa70e6fc8-patch-6f6d8ad1e0e9`；
  镜像标签 `org.opencontainers.image.revision=5eefa70e6fc8f9ec27958779f91ece6cf685598c`、
  `io.insurancekb.source.tree=a44f7eaeb40cf156d2893398046ffcb3094e5940`，与
  `deploy/local-live/weknora-app-source.lock.json` 一致（外加同 lock 中的
  model-debug 日志脱敏 patch，不涉及本 spike 探测的路径）。
- 本 worktree 源码与运行 commit `5eefa70e` 在本报告引用的全部文件上逐一
  `git diff` 校验：仅 `internal/handler/knowledge.go` 差 7 行（Asynq 队列名常量），
  其余引用文件（router、chunk repo/handler、knowledge types/service、
  knowledge_process、knowledge_delete）完全一致。源码引用只作解释，裁决
  只基于 live 观察。

**鉴权路径**（全部凭据仅驻内存，来源文件 mode 0600，未打印）：

1. 读取 023 生成的本地 runtime 文件 `.env.local-live.runtime`（0600 校验后解析）。
2. `POST /auth/login`（admin 邮箱+密码 `<REDACTED>`）→ Bearer JWT；
   `POST /auth/switch-tenant` 切到 runtime 记录的租户 `10002`。
3. 用 admin JWT 创建 spike 自有 scratch 对象（见下），数据面调用一律用
   scratch 范围 API key 的 `X-API-Key` 头。
4. 所有 httpx 客户端 `trust_env=False`（避免 shell 代理变量干扰）。

**安全边界执行情况**（spec W0.3）：

- 全部创建/重解析/删除只作用于本 spike 自建、带 `w0-spike-` 前缀命名的对象：
  - scratch KB `w0-spike-kb-0727010627`（id `b05667d7-1cf6-4d4d-a997-31ff43298259`）；
  - scratch API key `w0-spike-key-rw-0727010627`（id 6，retrieve+ingest）、
    `w0-spike-key-ro-0727010627`（id 7，retrieve）；
  - scratch knowledge `w0-spike-doc-0727010627.pdf`（id
    `db15bea9-03a1-4e32-a9f8-27c7176e2933`）及 T5 竞态用的 2 个变体。
- 既有 KB/knowledge 仅只读列表（附 before/after 对比，见 §7 清理证据）；
  对既有对象的 3 次跨界访问全部是 GET 且观察到 403（这本身是 T5 ACL 证据）。
- 探针 PDF 为脚本合成的 ASCII 文本 PDF（5 页 ×25 行，20251 bytes，
  sha256 `d70b9139…`），未使用任何业务数据集内容作为上传字节。

**复现步骤总览**：`probes/` 目录附完整探针脚本
（`w0lib.py` + `p0_setup.py` … `p9_cleanup.py`），`raw/` 目录附各 probe 的
原始观察 JSON（均已过脱敏过滤器）。下文每节给出等价的裸 HTTP 调用序列。

---

## T1 · stable identity：重解析前后的字段稳定性与单调 generation

**步骤**（`p0_setup.py` + `p1_t1.py`；raw `03_attempt1_completed.json`、
`10..12_t1_attempt*_settled.json`、`13_t1_analysis.json`）：

1. `POST /knowledge-bases/{kb}/knowledge/file`（multipart：file + metadata
   `{"owner":"w0-spike-…","sha256":"…"}`）→ 200，返回 knowledge 全对象，
   `parse_status=pending`。
2. 轮询 `GET /knowledge/{id}` 至 `completed`；抓
   `GET /knowledge/{id}/spans`、`GET /chunks/{id}?page=1&page_size=100`。
3. `POST /knowledge/{id}/reparse`（空 body）×2 轮，每轮等 `completed` 后
   重抓同一组读数，对全部 28 个公开字段做三方 diff。

**原始观察**：

- 上传即返回完整 knowledge 对象；完成态字段（attempt 1）：
  `id=db15bea9-…`、`created_at=2026-07-27T01:06:27.482278+08:00`、
  `file_hash=dccd482b0e50188efed3683f0c566f94`（== 本地对上传字节算的 MD5）、
  `file_size=20251`、`file_path=local://10002/db15bea9-…/….pdf`、
  `parse_status=completed`、`enable_status=enabled`、
  `processed_at=updated_at=01:06:39.077796`、`metadata` 原样回读、
  `summary_status=pending`（scratch KB 无 summary 模型，长期停在 pending）。
- 三次 attempt 的字段 diff（attempt1→2、2→3 完全同构）：
  - **稳定**：`id, created_at, file_hash, file_name, file_path, file_size,
    file_type, knowledge_base_id, embedding_model_id, metadata, source,
    channel, type, title, tenant_id, enable_status(终态), parse_status(终态),
    …`（28 字段中 26 个）。
  - **变化**：仅 `processed_at` 与 `updated_at`（每次完成后二者相等且严格递增：
    `01:06:39.077796 → 01:10:50.696651 → 01:13:54.449839`）。
- knowledge 对象 **没有任何 attempt/generation/revision 字段**（全字段清单
  见 raw 03/10–12）。
- chunk 集合每轮**全量替换**：三轮两两 id 交集 = 0；`seq_id`（bigint 全局
  自增）区间严格递进：`[100000023,100000064] → [100000065,100000106] →
  [100000107,100000148]`；`chunk_index` 每轮从 0 重排。
- `GET /knowledge/{id}/spans`（同 `/stages`）返回
  `data.current_attempt`：1→2→3 单调递增，并带全 trace span 树
  （root output 里含 `chunks_total=42`）。这是 **trace view**：
  pinned 源码 `internal/application/service/knowledge_process.go:1983-1988`
  显示 reparse 的 `OpenAttempt` 失败仅 Warn 并以 attempt=0 继续走 worker
  fallback——attempt 记录是 best-effort 观测量，服务端不保证其与 chunk 集合
  写入事务一致（033 §4.4 的预判在源码层面成立；live 下未观察到失配，但
  合同不能建立在"没碰上失败"上）。

**结论**：`knowledge_id` 及文件身份字段（`file_hash`(MD5)、`file_size`、
`created_at`、`metadata`）跨 reparse 稳定；内容层完全替换且无重叠。公开
**非 trace** API 上不存在单调 generation/attempt；唯一单调量是
(a) `/spans` 的 trace `current_attempt`（best-effort、非事务绑定）、
(b) chunk `seq_id` 的区间跳变（未文档化的实现细节推断）、
(c) `processed_at/updated_at` 时间戳（033 明令不得作为原子合同证明）。

---

## T2 · completed 绑定与 metadata/chunk 交换原子性

**步骤**（`p2_t2.py`；raw `20_t2_atomicity_reps.json`、
`21_t2_completed_binding.json`）：后台采样线程以 ~8–25 次/秒执行三连读
`GET /knowledge/{id}` → `GET /chunks/{id}?page=1&page_size=1` →
`GET /knowledge/{id}`（metadata 双读夹住 chunk 计数读），主线程触发
`POST /knowledge/{id}/reparse`，采样至再次 completed 后 2s。**重复 3 次**
（504/585/598 个采样点）。

**原始观察**：

1. 三次重复观察到完全一致的中间态序列（首次可见时刻，rep1）：
   | t | parse_status | enable_status | chunk_total |
   |---|---|---|---|
   | +36ms | completed | enabled | 42（旧） |
   | +350ms | pending | disabled | **0** |
   | +944ms | processing | disabled | 0 |
   | +995ms | processing | disabled | **42（新，seq_id 已跳到 100000149）** |
   | +1482ms | finalizing | **enabled** | 42（新） |
   | +1505ms | completed | enabled | 42（新） |
2. 即：**chunk 集合的删除与重建在多个可外部观察的中间态中发生**——旧集合
   先清零（status=pending/processing 窗口 ~600–800ms），**新集合在
   `parse_status` 仍为 `processing` 时已完整可读**，`enable_status` 在
   `finalizing`（而非 completed）时先行恢复 enabled。状态字段与 chunk 集合
   不构成单一原子切换。
3. "stale-completed"窗口（双读均 completed 且 updated_at 相同、但 chunk
   计数异常）在 3×~550 个采样中 **0 命中**。pinned 源码显示该窗口存在
   （`ReparseKnowledge` 先同步 `cleanupKnowledgeResources`（含
   `DeleteChunksByKnowledgeID`）**之后**才写 `parse_status=pending` 行，
   `knowledge_process.go:2068-2092`、`knowledge_delete.go:616-703`），
   但宽度低于本探针 ~40ms 的分辨率。按 W0.1 只记录：**未在 live 观察到，
   源码层面窗口存在且无事务保证**。
4. completed 单次读取可绑定的身份：`file_hash`（**MD5-only**，服务端算）、
   client 提交的 `metadata.sha256`（**服务端不校验**）、
   `embedding_model_id`。**parser/chunker 精确身份不存在于任何可读面**：
   knowledge 无 parser/chunker 字段；KB 对象的 `chunking_config` 返回
   `{"chunk_overlap":0,"chunk_size":0,"separators":null}`（服务端默认值
   不回显），且 KB 配置可变、无版本——completed 态无法与"当时使用的
   parser/chunker 身份"绑定成一次不可变读取。
5. 附加发现：completed 之后行仍会被后台任务改写（T4 中观察到 completed
   后 ~1s 出现第 5 个 `updated_at` 值；summary/enrichment 子任务导致），
   `updated_at` 既非内容版本号也非静默性信号。

**结论**：completed 状态无法与 parser/chunker 身份 + 强文件 digest 绑定为
一次不可变读取（MD5 + 未回显的 chunker 默认值 + 可变 KB 配置）；
metadata 与 chunk 集合的更新**非原子可见**（三次重复观察到 4 个中间态，
新集合先于 completed 可读），源码确认删除先于状态写且无共同事务。

---

## T3 · chunk 枚举：排序键、分页语义、manifest

**步骤**（`p3_t3.py`；raw `30_t3_enumeration.json`）：completed 态下做
全量 `page_size=100` 读、`page_size=5` 逐页走查、越界页、超限
`page_size=1000`、`sort_order=desc`、`chunk_type=image_ocr`、
`GET /chunks/by-id/{chunk_id}`，并对全部 chunk 内容做客户端 manifest 计算。

**原始观察**：

- 响应信封：顶层 `{"success":true,"data":[…],"total":42,"page":N,
  "page_size":M}`（total/page/page_size 在 data 之外）。
- **排序键**：`chunk_index ASC`（0..41 连续），`seq_id` 同序单调；与
  pinned `internal/application/repository/chunk.go:253`（document 类型
  `Order("chunk_index ASC")` + `Offset/Limit`）一致。链表字段
  `pre_chunk_id/next_chunk_id` 与该序一致。
- **分页游标语义**：纯 offset 分页（`page`/`page_size`），无 cursor、无
  snapshot token。`types.Pagination` 只有这两个字段（form 绑定）。
- 走查 `page_size=5`：9 页、并集 == 全量、无重复无遗漏（静态条件下）。
- 越界 `page=99` → 200，`data:[]`（空数组）、`total=42`。
- `page_size=1000` → 200，回显 `page_size=100`（handler clamp>100→100，
  `internal/handler/chunk.go:127-128`；<1 默认 10）。
- `sort_order=desc` 无效果（仍 0..4）：该参数未接入此端点。
- `chunk_type=image_ocr` → `total=0`（本文档无图），默认只回 `text` 型。
- `GET /chunks/by-id/{id}` → 200 单对象（同字段形）。
- **manifest**：响应无任何 server 端 manifest/digest 字段或端点；chunk 的
  `content_hash` 字段存在但 **live 值为空字符串**（42/42 chunk 均空）。
  客户端可计算（本次算得 sha256 over 有序 `chunk_index:id:sha256(content)`
  = `raw 30` 内记录），但它由 9 次无快照保障的 offset 读拼成，且没有任何
  服务端字段可把该 digest 归属到某个 parse attempt。
- chunk 对象无 attempt/version/revision 字段（全键清单见 raw 30）。

**结论**：排序键稳定（`chunk_index ASC`）、offset 分页语义明确
（clamp=100、越界空页、total 恒显）；但**无服务端 manifest digest、
`content_hash` 未填充、无快照/attempt 归属**——客户端 manifest 可计算但
不可证明其原子性与归属。

---

## T4 · 分页读取中触发重解析（竞态，3 次重复）

**步骤**（`p4_t4.py`；raw `40_t4_race_reps.json`）：`page_size=5`、页间
400ms 思考时间的走查；每页前后各读一次 `GET /knowledge/{id}`（meta 双读）；
第 2 页后从同客户端 `POST /reparse`。**重复 3 次**。

**原始观察**（rep1 完整时间线；rep2/3 同构）：

| page | t | total | 返回 chunk_index | 旧/新集合 | 页前 meta |
|---|---|---|---|---|---|
| 1 | 9ms | 42 | 0–4 | 旧×5 | completed/enabled |
| 2 | 437ms | 42 | 5–9 | 旧×5 | completed/enabled（此后发 reparse @474ms） |
| 3 | 894ms | **0** | （空） | — | processing/disabled |
| 4 | 1321ms | 42 | **15–19** | **新×5** | processing/enabled |
| 5–8 | …3019ms | 42 | 20–39 | 新×20 | processing→finalizing |
| 9 | 3444ms | 42 | 40–41 | 新×2 | completed/enabled |

- 三次重复中，一次逻辑走查全部读到 **旧新混合集**（rep1/rep2：旧 10 +
  新 27；rep3：旧 10 + 新 22），且 **丢失新集合的 index 10–14**（offset
  错位落在替换后的集合上）——**每一页都是 200，无任何错误/标记**。
- 客户端**可察觉**替换的信号（全部为跨读比较）：
  `total` 跳变（42→0→42）；`parse_status/enable_status` 中间态；
  id 集合不相交；新集合 `min(seq_id) > 旧 max(seq_id)`（3/3 成立）；
  `updated_at` 出现 5 个不同值（含 completed 后 ~1s 的第 5 次改写——
  enrichment 子任务也会改行，`updated_at` 变化 ≠ 内容替换，反向亦然
  不能保证毫秒级碰撞不存在）。
- 客户端**不能证明**"读到的是同一 attempt 的完整快照"：没有任何服务端
  字段把某一页绑定到某个 attempt/manifest；`/spans` 的 `current_attempt`
  是独立读取的 trace 量，与 chunk 页之间同样无原子关系；能构造的最强
  协议是"走查前后 meta 双读 + total/seq/id 一致性比较后重试"，其本质是
  **时间戳与启发式比较**——正是 033 §4.4 / W0.1 明确不接受为原子合同的
  证明形态。**本 probe 以 3/3 重复证明了"不能"**。

**结论**：重解析期间 offset 分页会无告警地返回旧新混合且可缺页的集合；
替换**可被启发式察觉**但**同一 attempt 完整快照不可证明**。

---

## T5 · 删除/禁用枚举、响应形状、读竞态、ACL 粒度

**步骤**（`p5_t5.py`；raw `50_t5_disable_and_acl.json`、
`51_t5_delete_race_reps.json`）。删除竞态：走查循环（150ms 间隔）第 3 轮
后发 `DELETE /knowledge/{id}`，持续记录两端点状态码；**3 次重复**（后两次
用新上传的变体 PDF）。ACL：ro key（仅 retrieve）与跨 KB 只读访问矩阵。

**原始观察**：

1. **API 枚举**（router 源码 + live 验证）：
   - `DELETE /api/v1/knowledge/:id`（API key 需 ingest）→ live 200，
     `{"success":true,"message":"Delete task submitted","data":{"task_id":"…"}}`
     ——**异步删除**。
   - `POST /api/v1/knowledge/batch-delete`、`/move`、`PUT /tags`：仅 JWT
     Contributor，API key 未声明 → live 403（default-deny 证实）。
   - `DELETE /api/v1/knowledge-bases/:id/knowledge`（清空 KB）：仅
     full-access key + Admin → scoped rw key live 403。
   - chunk 级：`DELETE /chunks/:kid/:cid`、`DELETE /chunks/:kid`、
     `PUT /chunks/:kid/:cid`（含 `is_enabled`）。
   - `POST /knowledge/:id/cancel-parse`：completed 态 live 400
     `{"error":{"code":1000,"message":"解析已结束，无法取消"}}`。
2. **禁用**：
   - chunk 禁用：`PUT /chunks/{kid}/{cid}` body 含 `is_enabled:false` →
     200；`GET /chunks/by-id/{cid}` 回读 `is_enabled=false`（已复原）。
   - knowledge 级禁用**不存在**：`PUT /knowledge/:id` body
     `{"enable_status":"disabled"}` → 200 `"Knowledge chunk updated
     successfully"`，但回读 `enable_status` 仍 `enabled`——service 只接受
     title/description（`internal/application/service/knowledge.go:590-611`），
     其余字段**静默丢弃**。`enable_status` 仅由解析生命周期内部切换
     （T2：reparse→disabled，finalizing→enabled）。
3. **删除 vs chunk 读竞态**（3/3 同构）：DELETE 返回 task_id 后，
   `GET /chunks/{id}` 与 `GET /knowledge/{id}` 在 ~0.5–1.4s 内从
   `200/completed(全量 chunk 仍可读)` 直接翻转为 **双 404**
   `{"error":{"code":1003,"message":"Knowledge not found"}}`；未观察到
   `deleting` 状态或部分删除中间态；**无 tombstone**——404 与"从未存在"
   不可区分，删除只能靠列表 diff 发现（列表同样是无快照 offset 分页）。
4. **ACL 粒度**（全部只读试探，预期=观察）：
   - ro key（retrieve）：读 chunks 200；`POST /reparse` 403；`DELETE` 403
     （capability 粒度：retrieve/ingest/full_access）。
   - scratch rw key → 既有 RAW KB 列表、既有 knowledge GET：403
     `{"error":{"code":1002,"message":"API key scope does not allow one or
     more knowledge bases"}}`；主 live key → scratch KB 列表：403（KB
     白名单双向生效）。
   - **粒度证据**：ACL = per-API-key 的 KB 白名单 × capability 集合；
     **无 Source/knowledge 级 ACL**；知识级最细动作门是 KB 级 write 权限。

**结论**：删除为异步、无 tombstone、终态 404(code 1003) 与不存在同形；
knowledge 级禁用无公开 API（PUT 静默丢弃）；chunk 级禁用可用；ACL 是
KB×capability 粒度，足以隔离 spike/生产对象，但不提供 Source 级授权。

---

## T6 · 合同裁决

### SourceLifecycleContract（stable id、状态/删除枚举、ACL）— **insufficient**

支持充分的证据：

- ✔ stable id：T1 三 attempt 间 `id/created_at/file_hash/file_name/
  file_size/metadata` 全稳定。
- ✔ 状态枚举：`parse_status` 状态集（源码枚举 pending/processing/
  finalizing/completed/failed/deleting/cancelled）+ `enable_status` +
  `processed_at/error_message` 可读；live 观察到
  pending→processing→finalizing→completed 全链路迁移（T2 3/3）。
- ✔ ACL：KB 白名单 × capability 矩阵 8/8 探测符合预期（T5.4）。

导致 insufficient 的缺口（033 §4.4 第一、五条要求）：

1. **无公开单调 parse generation**：knowledge 对象无 attempt 字段（T1）；
   唯一单调量 `/spans.current_attempt` 是 trace 观测量，源码证实
   best-effort（OpenAttempt 失败仍继续解析，attempt 可缺失/错位），
   033 已预先声明其不构成 revision token；`processed_at/updated_at` 是
   时间戳，被 W0.1 明确排除。
2. **删除枚举无 tombstone**：DELETE 异步 + 终态 404 与"从未存在"同形
   （T5.3，3/3），lifecycle 消费方只能靠无快照列表 diff 推断删除。
3. **文件 revision 身份过弱**：服务端 digest 仅 MD5（`file_hash`）；
   client 提交的 `metadata.sha256` 不被服务端校验（T2.4）。

### RevisionManifestContract（exact attempt/snapshot/ordered manifest）— **insufficient**

- ✘ chunk API 无 attempt 字段（T3 全键清单）；`/spans` attempt 与 chunk
  页读取之间无绑定（T4）。
- ✘ 无服务端 manifest digest（端点/字段均无）；`content_hash` live 为空
  （T3）；客户端 manifest 可算但无归属、无原子性。
- ✘ metadata/chunk 交换非原子可见：3/3 观察到旧清零→新集合在
  `processing` 期即可读→`finalizing` 先 enabled→completed 的 4 个中间态
  （T2）；源码确认 cleanup 先于状态写、无共同事务。
- ✘ 同一 attempt 完整快照不可证明：3/3 走查读到旧新混合并缺页
  （旧 10+新 27/27/22，丢新 idx 10–14），每页 200 无任何标记；可用的
  察觉手段全部是时间戳/启发式比较，被 033 §4.4 与 W0.1 排除（T4）。
- ✔ 仅排序与分页语义本身合格（`chunk_index ASC`、clamp、total 恒显，T3）
  ——不足以补偿以上缺口。

### 总体结论

两份合同均 `insufficient` ⇒ 按 033 §4.4 第 2 项触发最小 W1：见
`artifacts/w1-api-draft.md`（T7 产物）。P4a/P4c 在 W1 合入并重验前保持
blocked；033 §7 的 metadata 双读只能作为附加防线（T2/T4 证据同时表明它
连"察觉"都依赖时间戳精度，不能宣称"绝不混版"）。

---

## 7. 清理证据（T8 前置，已执行）

`p9_cleanup.py`；raw `90_cleanup_evidence.json`：

- scratch knowledge：T5 竞态中已全部 DELETE（3 个，双 404 确认）；KB 删除
  前列表 residual = 0。
- `DELETE /knowledge-bases/b05667d7-…` → 200；
  `DELETE /tenants/10002/api-keys/6`、`/7` → 200/200。
- 终检：KB 列表、API key 列表、全部 KB 的 knowledge 列表中
  `w0-spike-` 残留 = **0/0/0**。
- 既有数据 no-touch：清理后对 spike 开始前基线
  （`00_baseline_readonly.json`：全部既有 KB 的 knowledge id/updated_at/
  parse_status 快照）逐 KB 比对，**全部逐字段一致**。
- 脱敏复检：对报告与 raw/ 全量执行"runtime 凭据值扫描"（值仅驻内存比对，
  未打印），0 命中；raw JSON 中所有 key/token 字段由脱敏过滤器写为
  `<REDACTED>`。

## 8. 附录索引

- `probes/w0lib.py, p0_setup.py, p1_t1.py, p2_t2.py, p3_t3.py, p4_t4.py,
  p5_t5.py, p9_cleanup.py` — 探针源码（可直接在 harness venv 重放：
  `uv run python probes/p0_setup.py` 起）。
- `raw/00…90_*.json` — 各 probe 原始观察（脱敏后）。
- 源码引用（运行 commit `5eefa70e`，与 worktree 差异已在 §0 说明）：
  `internal/router/router.go:305-352`（knowledge 路由与 API key 声明）、
  `internal/handler/chunk.go:103-163`（分页 clamp 与信封）、
  `internal/application/repository/chunk.go:236-260`（`chunk_index ASC`）、
  `internal/application/service/knowledge_process.go:1963-2152`（reparse：
  OpenAttempt best-effort、cleanup 先于状态写）、
  `internal/application/service/knowledge_delete.go:616-703`（cleanup 序）、
  `internal/application/service/knowledge.go:590-611`（PUT 仅
  title/description）、`internal/types/knowledge.go`（状态枚举与全字段）。
