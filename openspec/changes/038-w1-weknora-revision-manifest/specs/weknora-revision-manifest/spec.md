# 038 W1 WeKnora Revision Manifest 验收规格

> 名词约定：`attempt` = 服务端事务分配的 `parse_attempt`；`已提交
> revision` = `knowledge_revisions` 中存在的不可变行；`当前可服务
> attempt` = 满足「revision 行存在 AND `knowledges.current_parse_attempt`
> 等于该 attempt AND `parse_status = completed`」的 attempt。所有端点均在
> 既有 `/api/v1` 前缀与既有 ACL 链（KB 白名单 × capability、Viewer、
> `KBAccessReadFromKnowledgeIDParam`）之内。

## ADDED Requirements

### Requirement: W1.1 事务化单调 parse_attempt

系统 SHALL 在 `knowledges` 表维护每 knowledge 的 `current_parse_attempt`
（bigint，初始 0 表示尚无分配）。任何触发 chunk 集合重建的解析入口（文件
创建、reparse、manual 更新重建路径）SHALL 在写入 `parse_status=pending`
的**同一数据库事务**内对该行执行原子自增分配新 attempt，并把该值传入
解析任务 payload；分配 SHALL 由数据库行级序列化保证严格单调递增，
SHALL NOT 复用、回退或跳号分配已用值。worker 写入 chunk 行时 SHALL 逐行
携带任务 payload 中的该 attempt 值：SHALL NOT 在写入时重读
`current_parse_attempt`，SHALL NOT 采用 trace attempt 字段。attempt 分配
SHALL 与 trace `OpenAttempt`（`/spans` 的 `current_attempt`）完全解耦：
trace 记录失败 SHALL NOT 影响 attempt 分配与解析，二者数值允许不相等，
`/spans` 行为 SHALL 保持不变。

**分配先于销毁（顺序约束）**：对已存在 chunk 集合的重建（reparse、
manual 更新重建），分配事务（自增 + `parse_status=pending` 写）SHALL 在
对上一 attempt 的 chunk/索引资源开始任何销毁**之前**提交；分配事务失败
时 SHALL 中止本次重建，上一 attempt 保持完整可服务。由此 SHALL NOT 存在
「上一 attempt 仍解析为当前可服务、其 chunk 却已被（部分）删除」的窗口
——W0 T2 观察到的 cleanup-先于-状态写顺序在此被反转；分配提交之后清理
即使中断，上一 attempt 也已不可服务（W1.2 409 / W1.3 410），fail closed
而非静默缺页。本约束只重排既有 delete-and-rebuild 的推进顺序，
SHALL NOT 引入历史 chunk 保留或第二存储。

revision 提交（见 W1.5）SHALL 绑定**解析管线自身**把 `parse_status`
翻转为 `completed` 的那次事务——包括直接翻转与 `finalizing →
completed` 的 subtask 收敛提升路径
（`knowledgeRepository.FinalizeSubtask`，由 `knowledge_post_process.go`
驱动）——且该事务 SHALL 在行锁下复核 `current_parse_attempt` 仍等于
本次提交的 attempt（提交 fencing）：不等时事务 SHALL 整体失败并返回
typed 错误，`parse_status` SHALL NOT 翻转为 completed，SHALL NOT 写入
revision 行。解析管线之外对 `parse_status=completed` 的既有写入（如
clone/move 目标行与其他维护性更新）SHALL NOT 伪造或触发 revision 提交；
此类「completed 但无 revision 行」在 W1.2 呈现 typed 409（子况 d）。

`failed/cancelled` 的 attempt SHALL 不产生 revision 行；其分配记录
SHALL 保留（`current_parse_attempt` 停在该失败值，`parse_status` 呈现
`failed/cancelled`）。任何后续 attempt 的失败或取消 SHALL NOT 删除、
修改或回退任何已提交 revision 行，SHALL NOT 使 `current_parse_attempt`
减小。attempt 与 `current_parse_attempt` SHALL 通过 W1.2/W1.3/W1.7 的
版本化公开端点可见；SHALL NOT 要求消费方读取 `/spans`、时间戳或
`seq_id` 推断 generation。

#### Scenario: 分配与 pending 写同事务且单调

- **WHEN** 同一 knowledge 依次经历上传解析与两次 reparse，期间人为使
  trace `OpenAttempt` 失败一次
- **THEN** 三次解析分配的 `parse_attempt` 严格单调递增且各自与
  `parse_status=pending` 的写入处于同一事务（事务中断则二者都不存在）；
  trace 失败的那一轮解析照常完成，其 attempt 值不缺失、不错位

#### Scenario: 并发触发分配不冲突

- **WHEN** 两个客户端对同一 knowledge 并发触发 reparse
- **THEN** 两次分配获得两个不同的、严格递增的 attempt 值；
  `knowledge_revisions` 以 `(knowledge_id, parse_attempt)` 主键保证不
  产生同 attempt 的第二行

#### Scenario: 分配提交前零销毁、分配后中断 fail closed

- **WHEN** 对已提交 attempt N 的 knowledge 触发 reparse，分三轮观察：
  (a) 正常执行并记录分配事务提交与首次 chunk 删除的先后；(b) 在分配
  事务提交前注入失败；(c) 在分配事务提交后、清理完成前中断
- **THEN** (a) attempt N 的任何 chunk 删除都发生在分配事务提交之后；
  (b) 重建中止，attempt N 仍是当前可服务 attempt 且其绑定读取完整；
  (c) attempt N 已不可服务（`/revision` 409、`/revisions/N/chunks`
  410）——任何一轮都不存在「200 但 chunk 缺失」的读取

#### Scenario: 迟到 worker 被提交 fencing 拒绝

- **WHEN** attempt N 的 worker 尚未提交时又触发了 reparse（分配
  attempt N+1），随后 attempt N 的 worker 尝试提交 revision
- **THEN** 该提交事务因 `current_parse_attempt = N+1 ≠ N` 整体失败并
  返回 typed 错误；`parse_status` 不因该次提交翻转 completed，
  `knowledge_revisions` 中不出现 attempt N 的行

#### Scenario: 失败 attempt 不回退已提交历史

- **WHEN** attempt 3 已提交 revision 后，attempt 4 的 reparse 以 failed
  终止
- **THEN** attempt 3 的 revision 行逐字段不变，`current_parse_attempt`
  为 4 且不回退；公开端点以 typed 状态呈现该事实（见 W1.2），不需要
  消费方读 `/spans` 或比较时间戳

### Requirement: W1.2 revision 描述符端点

系统 SHALL 提供 `GET /api/v1/knowledge/:id/revision`，返回该 knowledge
当前可服务 revision 的描述符，并以 HTTP 状态 + 稳定 typed 错误码区分四
种互斥状态；SHALL NOT 出现无法归入下列四种之一的响应：

1. **200**（当前 attempt 已提交且可服务）：`data` SHALL 至少包含
   `knowledge_id`、`parse_attempt`、`file_digest`
   （`{"algorithm":"sha256","value":"<64位小写hex>"}`）、
   `parser_identity`（提交时快照，见下）、`chunk_manifest`
   （`{"algorithm":"<W1.5 算法标识>","digest":"<64位小写hex>",
   "chunk_count":N}`）、`completed_at`；全部取自不可变 revision 行，
   SHALL NOT 从可变 KB 配置或 knowledge 行现算。
2. **409** typed `revision_not_committed`（knowledge 存在但当前无可服务
   revision）：覆盖 (a) 从未成功 completed、(b) 当前 attempt 处于
   `pending/processing/finalizing`、(c) 最新 attempt 以
   `failed/cancelled` 终止、(d) `parse_status=completed` 但当前 attempt
   无 revision 行（传承数据、clone/move 或其他非解析路径写入的
   completed，见 W1.1）、(e) 无存量原文件字节的 knowledge（manual/FAQ
   等 `file_path` 为空的来源；URL 入库若未持久化原文件字节亦同）——
   W1 v1 revision 合同只覆盖 file-backed knowledge，此类行 SHALL 永久
   豁免于 revision 提交并恒为本状态。body SHALL 附 `parse_status`、当前
   `parse_attempt` 与机读 `reason`（可无歧义区分 a–e，file-less 为
   `file_less_source`）；存在历史已提交 revision 时 SHALL 附
   `last_committed`（`parse_attempt`、`manifest_digest`、
   `completed_at`），供 lifecycle 消费方证明「completed 历史未被回退」。
3. **410** typed `knowledge_deleted`（tombstone，见 W1.4）。
4. **404** typed `knowledge_not_found`：该 id 从未存在；SHALL 与 410
   可区分。

`parser_identity` SHALL 是提交事务内固化的快照，至少包含构建标识
（app 源码 commit/版本）、docreader 版本标识、**已生效**的 chunker 配置
（`chunk_size`、`chunk_overlap`、separators 的 digest）与
`embedding_model_id`；SHALL 取自解析实际使用的有效配置，SHALL NOT 引用
提交后可变的 KB 当前配置。构建标识 SHALL 来自构建期注入的版本信息（与
镜像 source lock 一致的 commit/版本值），SHALL NOT 在运行时从可变环境
推断；某一分量在提交时确实不可得时 SHALL 记为显式 tagged 值
`"unknown"`——SHALL NOT 省略键、SHALL NOT 写空串，也 SHALL NOT 因此使
提交失败——使消费方可确定性检出降级身份；W1.6 的 compatibility matrix
SHALL 记录生产镜像下各分量非 `"unknown"`。

端点 SHALL 沿用既有读 ACL 链（KB 白名单 + retrieve capability +
Viewer + KB 读权限校验）；无权限时 SHALL 维持既有 403/404 语义，
SHALL NOT 因 revision 端点泄漏无权限对象的存在性。

#### Scenario: completed 单次读取绑定全部身份

- **WHEN** knowledge 完成 attempt 3 后调用 `GET /knowledge/:id/revision`
- **THEN** 单次 200 响应同时给出 knowledge_id、parse_attempt=3、sha256
  文件 digest、parser/chunker 身份快照、ordered chunk manifest digest
  与 completed_at；重复调用逐字段相等（不可变）

#### Scenario: 重建期间与失败后的 typed 409

- **WHEN** attempt 3 已提交后触发 reparse（attempt 4），分别在 4 进行中
  与 4 失败后调用该端点
- **THEN** 两次均返回 409 `revision_not_committed`，body 含当时
  `parse_status`（如 `processing`/`failed`）、`parse_attempt=4` 与
  `last_committed.parse_attempt=3`；SHALL NOT 返回把 attempt 3 描述为
  仍可服务的 200（其 chunk 集合已被 delete-and-rebuild 清除）

#### Scenario: 四态互斥可区分

- **WHEN** 分别对「从未存在的 id」「存在且已提交」「已删除且在保留窗口
  内」「存在但从未 completed」各调用一次
- **THEN** 依次得到 404、200、410、409，错误码稳定且两两不同

#### Scenario: 非解析 completed 与 file-less 来源呈现 typed 409

- **WHEN** 分别对 (a) 一个经 clone/move 写入 `parse_status=completed`
  且当前 attempt 无 revision 行的 knowledge、(b) 一个 manual/FAQ 等无
  存量原文件字节的 knowledge 调用 `/revision`
- **THEN** 二者均返回 409 `revision_not_committed`，`reason` 机读可
  区分（分别为「非解析 completed 无 revision」与 `file_less_source`）；
  SHALL NOT 为其伪造 revision 行或返回 200

### Requirement: W1.3 attempt 绑定的 chunk 读取

系统 SHALL 提供
`GET /api/v1/knowledge/:id/revisions/:attempt/chunks?page=&page_size=`，
只返回**恰好属于该 attempt** 的 chunk 页。服务端 SHALL 执行读取协议：

1. 解析 `(knowledge_id, attempt)` 的 revision 行：不存在 SHALL 返回
   404 typed `revision_not_found`（含 attempt=0 传承数据与尚未提交的
   in-flight attempt）；
2. 该 attempt 不是当前可服务 attempt 时 SHALL 返回 410 typed
   `revision_superseded`，body 附 `current_parse_attempt` 与当前
   `parse_status`；knowledge 已 tombstone 时 SHALL 返回 410 typed
   `knowledge_deleted`（同 W1.4）；
3. 页数据 SHALL 按 `WHERE knowledge_id = :id AND parse_attempt =
   :attempt` 加既有 document text chunk 过滤，`ORDER BY chunk_index
   ASC` 加既有 offset 分页；分页 clamp、越界空页与 `total` 语义 SHALL
   与既有 `GET /chunks/:id` 一致（`page_size` 上限 clamp、越界页返回
   200 空 `data`）；同一可服务 attempt 内的分页 SHALL 稳定且完整：无
   重复、无遗漏、`total` 恒等于该 revision 的 `chunk_count`；
4. 页读取后 SHALL 复核当前可服务 attempt；已变化时 SHALL 丢弃该页并
   返回 410 `revision_superseded`。

200 响应 SHALL 在既有 `data/total/page/page_size` 信封之上**每页**回显
绑定块 `revision`：`knowledge_id`、`parse_attempt`、`manifest_digest`、
`chunk_count`。由此客户端合同 SHALL 成立：一次走查的所有页
`revision.parse_attempt` 与 `manifest_digest` 相同，且页并集大小等于
`chunk_count`，则该并集即该 manifest 的完整快照；任何 410 表示必须重新
走 W1.2 → W1.3。消费方 SHALL NOT 需要 `updated_at`、`seq_id` 或 id 集合
启发式。完整性证明以「一个可服务 attempt 在走查期间持续存在」为活性
前提（正常运行下重解析间隔 ≫ 单次走查时长）；在持续替换下走查可能反复
410 而无法完成——这是正确性优先的预期行为：W1 只承诺绝不返回错误/混版
数据，不承诺该对抗情形下的完成时限。消费方 SHOULD 在重新走查前经
W1.2/W1.7 观察 `current_parse_attempt` 稳定并做退避。

**superseded 语义裁决（与 037 草案一致）**：被替换 attempt 的 chunk 读
SHALL 返回 410 `revision_superseded`，SHALL NOT 返回冻结的历史全集。
理由：(a) 033 §4.4 禁止 W1 改动 delete-and-rebuild——被替换 attempt 的
chunk 行已被既有清理路径删除，服务端冻结保留将引入保留窗口、存储增长与
第二套 GC，超出最小 patch 预算；(b) 历史快照的持久化责任在 Harness 侧
P4c 的 SourceRevisionArtifact（033 §8.3），WeKnora 只需保证原子归属与
typed 失效，不承诺历史内容服务。

在重解析或删除与走查并发时（W0 T4/T5 竞态的合同化）：系统 SHALL 保证
一次走查**绝不**把两个 attempt 的 chunk 混入同一逻辑结果集，**绝不**在
无 typed 信号的情况下丢失该 attempt 的任何 chunk；替换/删除发生后的下
一次页请求 SHALL 以 410 终止走查。该场景 SHALL 以 RED-style Go contract
test 先行落地（先复现 W0 T4 的旧新混合 + 缺页作为 RED 基线，再由绑定
端点转 GREEN）。该 Go 测试 SHALL 采用**确定性交错**：在页读取之间直接
调用分配/清理服务序列（或经注入点驱动替换），SHALL NOT 依赖挂钟竞速；
fixture 的 chunk 数 SHALL 在所用 `page_size` 下覆盖至少 3 页。挂钟并发
下重复 ≥3 次的复验归 live lane（tasks 验收 13）。

#### Scenario: 走查中重解析被 410 终止而非静默混版（W0 T4 复刻）

- **WHEN** 客户端走查 attempt N 的 `/revisions/N/chunks`（fixture 在
  所用 `page_size` 下至少 3 页），读完第 2 页后测试以确定性交错触发
  reparse（直接调用分配/清理序列，attempt N+1 分配并清除旧集合），原
  客户端继续请求后续页；live lane 另以挂钟并发全流程重复至少 3 次
- **THEN** 每次执行（含 live 重复）中，替换点之后的首个页请求返回 410
  `revision_superseded`（body 含 current_parse_attempt=N+1）；已返回的
  各页 `revision.parse_attempt` 均为 N；任何一次走查的并集要么被 410
  终止、要么大小恰为 chunk_count 且逐 chunk 属于 attempt N——0 次旧新
  混合、0 次静默缺页

#### Scenario: 静态走查可证明完整快照

- **WHEN** 无并发写时客户端逐页走查当前可服务 attempt 并聚合
- **THEN** 所有页的 `revision.parse_attempt/manifest_digest` 相同，
  `total` 恒为 `chunk_count`，并集大小等于 `chunk_count`，按 W1.5 算法
  重算的 digest 与 `manifest_digest` 逐字节一致

#### Scenario: 走查中删除转 typed 终止

- **WHEN** 走查进行中该 knowledge 被 DELETE（异步）完成软删
- **THEN** 后续页请求返回 410 `knowledge_deleted`（tombstone 语义），
  SHALL NOT 出现与「从未存在」同形的裸 404，SHALL NOT 返回部分旧数据
  冒充完整集

#### Scenario: 传承数据与未提交 attempt 不可绑定

- **WHEN** 对迁移前已存在（chunks.parse_attempt=0）的 knowledge 请求
  `/revisions/0/chunks`，或对 in-flight attempt 请求其 chunks
- **THEN** 均返回 404 `revision_not_found`；SHALL NOT 把无归属数据
  伪装成可绑定 revision

### Requirement: W1.4 删除 tombstone 与保留窗口

已删除 knowledge SHALL 与「从未存在」可区分：knowledge 删除沿用既有
gorm 软删除（`knowledges.deleted_at`），W1 端点（W1.2/W1.3）对软删行
SHALL 经 Unscoped 查询返回 410 typed `knowledge_deleted`，body 附
tombstone（`knowledge_id`、`deleted_at`）；对不存在的 id SHALL 返回
404。tombstone 读取 SHALL 先解析软删行到其 KB 并执行与在世对象相同的
ACL 校验，SHALL NOT 因 tombstone 泄漏无权限对象的存在性或删除时间。

tombstone 可读性 SHALL 有显式保留窗口不变量，但 **W1 SHALL NOT 新增
配置接线，也 SHALL NOT 引入硬删 GC**：只要软删行存在，410 SHALL 持续
可读（W1 交付形态下窗口事实上无限）。保留窗口时长是部署策略量；任何
未来引入软删行硬删清理的 change SHALL 拥有该窗口配置并遵守本不变量——
窗口内 SHALL NOT 硬删（410 保证可读），窗口外 410 退化为 404 是唯一
允许的退化路径。删除 SHALL NOT 删除或改写 `knowledge_revisions`
历史行以外的 W1 状态语义；既有 DELETE 端点的请求/响应形状 SHALL 保持
不变。

#### Scenario: 删除后 410 与 404 可区分（W0 T5 复刻）

- **WHEN** 上传并完成解析的 knowledge 被 DELETE，异步删除收敛后分别
  请求该 id 与一个随机不存在 id 的 `/revision`
- **THEN** 前者返回 410 `knowledge_deleted` 且 tombstone 含
  `deleted_at`；后者返回 404；两者状态码与错误码均不同

#### Scenario: 保留窗口内清理不得抹除 tombstone

- **WHEN** 软删发生后，在保留窗口策略生效期内执行任何清理任务，随后
  请求 `/revision`；另在测试内模拟窗口外清理（直接硬删该软删行）后再
  请求一次
- **THEN** 窗口内仍返回 410 tombstone（W1 自身不交付任何硬删清理，软
  删行在即 410）；仅当窗口外软删行被显式清理，该 id 才允许退化为
  404，且这是唯一退化路径

#### Scenario: tombstone 不成为 ACL 旁路

- **WHEN** 无该 KB 读权限的 API key 请求一个已软删 knowledge 的
  `/revision`
- **THEN** 响应遵循既有无权限语义（403/404），SHALL NOT 返回 410 或
  暴露 deleted_at

### Requirement: W1.5 digest 升级与 manifest 算法

**文件 digest**：上传路径 SHALL 在既有写入流上流式计算 sha256 并持久化
到 `knowledges.file_sha256`；既有 MD5 `file_hash` 字段与语义 SHALL 保持
不变。revision 行 SHALL NOT 以空 `file_sha256` 提交：迁移前上传的
knowledge 在其下一次解析提交前 SHALL 由服务端从存量原文件字节计算并
持久化 sha256。无存量原文件字节的 knowledge 豁免于 revision 提交
（W1.2 子况 e），因此 SHALL NOT 存在需要以空 digest 提交的路径。客户端
提交的 `metadata.sha256` 维持现状（不校验、不采信），SHALL NOT 作为
`file_digest` 来源。

**manifest digest**：提交事务内 SHALL 按以下规范化字节序列计算（记法：
`LF` = 0x0A；`decimal(x)` = 无符号十进制 ASCII、无前导零，且
`decimal(0)` = `"0"`；`hex(...)` = 64 位小写十六进制）：

```text
input = "weknora.chunk_manifest" LF        # domain separator
        "v1" LF                            # hash schema version
        knowledge_id LF                    # API 返回的 UUID 字符串原文
        decimal(parse_attempt) LF
        decimal(chunk_count) LF
        每个 chunk（chunk_index 严格升序）:
          decimal(chunk_index) ":" chunk_id ":" hex(sha256(content_bytes)) LF

manifest_digest    = hex(sha256(input))
manifest_algorithm = "weknora.chunk_manifest.v1"
```

其中 `content_bytes` SHALL 是 chunk content 的存储 UTF-8 字节逐字节
原文——SHALL NOT 施加 Unicode 规范化、trim、换行转换或 JSON 转义；
`chunk_id` SHALL 是 API 返回的该 chunk UUID 字符串原文（与存储主键一致
的 ASCII 形态）——主键形态若变化 SHALL 升 v2；chunk 集合范围 SHALL
恰好等于 W1.3 端点服务的集合（同 knowledge、同 attempt、同 document
text chunk 过滤）——image/OCR/多模态等非 text chunk 类型 SHALL 明确
不在 v1 manifest 与绑定读取范围内（与既有默认列表语义一致），纳入它们
SHALL 升 v2；`chunk_index` 在同一 attempt 内 SHALL 唯一，提交事务发现
重复时 SHALL 整体失败（typed），SHALL NOT 提交歧义 manifest，并 SHALL
以数据库唯一索引兜底（存活 document text chunk 行上的
`(knowledge_id, parse_attempt, chunk_index)` 唯一；软删行不参与）。revision 行 SHALL 持久化 `manifest_algorithm` 与
`manifest_digest`；提交后 SHALL NOT 重算或刷新该 digest——提交后经其他
既有入口（如 chunk 编辑）发生的内容漂移 SHALL 通过「消费方按同算法重算
≠ 存储 digest」确定性可检出，服务端 SHALL NOT 掩盖该不一致。

**对 033 §8.4 的采用口径**：本算法遵守 §8.4 的 hash 框架不变量——
domain separator + hash schema version + 对象身份绑定 + SHA-256 +
禁止运行时默认编码（Go map 序、JSON 编码器输出）参与 hash 输入。W1
SHALL NOT 引入完整 CanonicalEnvelopeV1 Go codec：manifest 输入是扁平
有序的 `(int, uuid, hex)` 元组序列，无 map/float/日期/sentinel，JCS/NFC
规范化无增量收益，而完整 C0 adapter 将耗尽 ~600 行 patch 预算并把 fork
耦合到 C0 包发布节奏；C0 vectors 的 Go 消费义务由首个真正消费 envelope
对象的 patch（P11 managed-page contract）承担。更换算法或框架（含未来
迁移到 CanonicalEnvelopeV1 framing）SHALL 升级版本标识（v2），只作用于
新 revision，SHALL NOT 静默重算历史行。本算法 SHALL 附语言中立测试
vectors（固定输入 → 期望 digest），Harness 侧按 vectors 与 live 重算
双向验证跨语言一致。

#### Scenario: manifest 与客户端重算逐字节一致

- **WHEN** 完成解析后读取 `/revision` 与该 attempt 全部 chunk 页，
  客户端按上述规范重算 digest
- **THEN** 重算值与 `chunk_manifest.digest` 逐字节相等，
  `chunk_manifest.algorithm` 恰为 `weknora.chunk_manifest.v1`

#### Scenario: 语言中立 vectors 固定算法

- **WHEN** 用规格附带的固定 vectors（含空集、单 chunk、多字节 UTF-8
  内容、非连续 chunk_index、`decimal(0)`=`"0"` 编码等边界）分别在 Go
  实现与独立参考实现上计算
- **THEN** 双方对每条 vector 输出相同 digest；任何实现改动导致 vector
  不匹配即视为破坏合同，必须升 v2 而不是改 v1 语义

#### Scenario: 提交后内容漂移可确定性检出

- **WHEN** revision 提交后经既有 chunk 编辑入口修改了其中一个 chunk 的
  content，消费方重新走查并按同算法重算
- **THEN** 重算 digest ≠ revision 行存储的 `manifest_digest`（确定性
  失配，可作为 fail-closed 信号）；revision 行本身逐字段不变，服务端
  未刷新 digest 掩盖漂移

#### Scenario: 空 sha256 不得提交

- **WHEN** 迁移前上传（`file_sha256` 为空）的 knowledge 触发 reparse
  并完成
- **THEN** 提交的 revision 行携带非空 sha256 `file_digest`，其值等于对
  存量原文件字节独立计算的 sha256；不存在以空 digest 提交的路径

### Requirement: W1.6 patch budget 与上游兼容义务

W1 SHALL 是 patch inventory
（`deploy/patches/enterprise-llm-wiki-patch-inventory.yaml`）中
`patch_id: W1` 行描述的**唯一** WeKnora fork 改动来源：实现 PR SHALL
在同 PR 内把该行 `status` 更新为实现状态、`file_path` 更新为与实际
diff 完全一致的 exact 文件清单、`upstream_issue` 由
`pending-W0-verdict` 更新为真实上游 issue 引用；inventory 声明面与实际
patch surface 不一致 SHALL 视为验收失败。实现 SHALL NOT 改动允许面之外
的文件；允许面限于：`migrations/versioned/` 恰好一对新 up/down、
`internal/types/`（knowledge/chunk/revision 类型）、
`internal/application/repository/`（`knowledge.go` 的
FinalizeSubtask 提交挂钩、`chunk.go` 的 attempt 过滤、revision 存取）、
`internal/application/service/`（knowledge_create/knowledge_process/
knowledge_post_process 的分配与提交接线）、`internal/handler/`（新只读
handler）、`internal/router/router.go`（路由 + API-key capability
声明）及其对应测试文件；SHALL NOT 修改任何历史迁移。迁移 SHALL 只落在
`migrations/versioned/`（PostgreSQL/ParadeDB 生产链）；`mysql/`、
`sqlite/`、`paradedb/` 目录 SHALL 零修改——sqlite 单测 lane 沿既有
`AutoMigrate` 模式获得新列/新表，但 W1 的事务/并发合同只对 PostgreSQL
承诺，sqlite 结果 SHALL NOT 冒充并发证据。

按 033 §11.4，W1 SHALL 交付：(a) 上游 API contract tests（本规格各
Requirement 的场景化测试）；(b) 普通知识/chunk REST 非回归测试（既有
端点行为与响应形状不变，仅允许 W1.7 声明的增量字段）；(c) 官方跟版
compatibility matrix——在 inventory `upstream_baseline` 基线（当前
`5eefa70e`）上记录 patch surface 与 conflict 状态，跟版时重放
inventory `compatibility_tests` 四项向量（exact completed-attempt
manifest/content binding、reparse-pagination-delete race rejects mixed
revisions、existing knowledge REST behavior remains compatible、no
shared database Redis or Asynq dependency）。设计 SHALL 可上游化：
端点/表/错误码/算法命名不含 InsuranceKB 领域语义，不依赖 Harness 的
存在。

#### Scenario: inventory 声明面与实际 diff 一致

- **WHEN** 审查 W1 实现 PR 的 diff 与 inventory W1 行
- **THEN** diff 触碰的每个文件都在允许面内且被 `file_path` 逐一列出，
  `file_path` 不含 diff 外文件；恰好一对新 versioned migration；历史
  迁移零修改；`status`/`upstream_issue` 已更新

#### Scenario: 兼容性向量在跟版基线上通过

- **WHEN** 在 `upstream_baseline.sha` 基线上应用 W1 patch 并运行
  inventory 四项 `compatibility_tests` 向量与普通知识 REST 非回归套件
- **THEN** 四项向量与非回归套件全部通过；报告列出 patch surface 与
  upstream conflict 状态

### Requirement: W1.7 向后兼容与能力探测

既有端点 SHALL 保持请求/响应语义不变：`GET /api/v1/knowledge/:id` 与
KB knowledge 列表项 SHALL 仅新增 `current_parse_attempt`（0 = 尚无
分配）与 `file_sha256`（空 = 尚未计算）两个字段，且 SHALL 无条件序列化
（不使用 omitempty 之类的零值省略），使字段**存在性**本身构成部署能力
信号。两个新字段加在 knowledge 序列化类型上：凡内嵌 knowledge 对象的
既有响应（详情、列表、batch、search 等）SHALL 一并出现该增量字段（同一
类型、同一只增语义）；chunk 对象同理仅新增 `parse_attempt` 字段。不
内嵌 knowledge/chunk 对象的既有端点（`/spans`、DELETE、reparse、
cancel-parse 等）SHALL 零变更；一切既有端点的请求参数、既有字段、状态
码与错误码 SHALL 逐一不变。新端点 SHALL 只注册为只读（retrieve
capability + Viewer + KB 读 ACL），SHALL NOT 扩大任何既有 API key 的写
能力。

新读取面 SHALL 可被消费方无歧义探测：`GET /knowledge/:id` 响应 JSON 中
`current_parse_attempt` 键存在 ⇔ 部署含 W1。消费方（P4a/P4c Harness）
SHALL 以该探测 fail closed：探测失败（键缺失或新端点路由缺失）时
SHALL NOT 把旧部署上的 404 当作「从未存在」语义消费，SHALL NOT 回退到
时间戳/启发式合同。W1 revision 端点 SHALL 使用**五个**稳定机读错误码：
`revision_not_committed`（409）、`revision_superseded`（410）、
`knowledge_deleted`（410）、`knowledge_not_found`（404，id 从未
存在）、`revision_not_found`（404，该 attempt 无 revision 行）——两个
404 与两个 410 分别以错误码无歧义区分；错误码与 HTTP 状态映射一经发布
SHALL NOT 变更；合同演进 SHALL 通过新增字段或升版本标识，SHALL NOT
复用既有码表达新语义。

#### Scenario: 既有端点非回归

- **WHEN** 对同一数据集在 patch 前后分别调用既有 knowledge/chunk 全部
  读写端点并比对
- **THEN** 除 `GET /knowledge/:id` 与列表项新增的两个字段外，请求
  参数、状态码、错误码与响应字段逐一相等；新增字段在零值时仍存在于
  响应 JSON 中

#### Scenario: 旧部署探测 fail closed

- **WHEN** 消费方对不含 W1 的旧部署执行能力探测（检查
  `current_parse_attempt` 键与 revision 端点可达性）
- **THEN** 探测判定能力缺失；消费方进入 typed fail-closed 路径（保持
  blocked/告警），SHALL NOT 把旧部署的 404 解释为 tombstone 区分或把
  启发式比较当作 revision 合同

#### Scenario: 错误码稳定可机读

- **WHEN** 客户端仅依据 HTTP 状态 + 错误码分支处理 W1 全部响应
- **THEN** 五个错误码各自唯一稳定（两个 404、两个 410 均可无歧义
  区分），无需解析人类可读 message 即可路由所有分支
