# S6a-3 · 原生 Wiki 处理被取消后：未发出的调用归为 NOT_RUN，可以重试，不再报告成功

> 状态：Claude 2026-10-20 提出（#266 中 1837 第一次处理的事故）｜ 作者：Claude Code
> 实现方：Codex（Go，已登记的上游文件）｜ 审核方：Claude ｜ 真实模型调用：0

## 1. 事故（日志核对）

- 1837 的发现库处理中，候选与引用都正常。12:48:09 发出的分类规划请求挂起，12:51:21 批次上下文被取消，同一时刻的数据库查询也报错。
- 随后约 209 个页面改写在 1 秒内全部以 `OUTCOME_UNKNOWN` 失败，日志中没有一条对应的模型请求。
- 结算把这些失败一律转为死信并释放知识的处理位，批次记为 `status=success`，发现库只剩摘要和索引。
- 后续同一输入被 `recoveryBlocked` 挡住，不会重试。
- 上下文被取消的原因不明：任务已运行 5 分 10 秒，不是 60 分钟的任务期限。

## 2. 设计（通用机制）

### 2.1 调用结果归类（`generateWithTemplateResult`）

- **NOT_RUN**：请求没有离开进程。包括所有用途（页面改写、分类、摘要、索引、去重、候选、引用）在发送前上下文已结束、等待请求合并或缓存预热时被取消等情况。
- **OUTCOME_UNKNOWN**：只用于已经调用 `chatModel.Chat` 后，结果不明的情况，包括调用中被取消。这条规则不变，已发出的请求仍不重发。
- 实现提示：在调用 `Chat` 前记一个"已发送"标记；`select` 走到 `ctx.Done()` 分支时，没有该标记就返回 NOT_RUN。共享同一请求键的合并请求继承同一结果，这本身是正确的。

### 2.2 批次结算

- 页面改写在派发前先检查 `reduceCtx`，已结束时直接记 NOT_RUN，不调用模型。
- 一个操作的全部失败都是 NOT_RUN 时，释放该操作以便重试（清除 `claimed_at` 与 `execution_id`），不转死信，也不释放知识的处理位。
- 只要有 UNKNOWN 或 FAILED，仍按现有规则转死信，不重发。
- 失败账本不为空时，批次状态不是 `success`（例如 `reduce_failed`）。上下文已结束时，处理函数返回错误，由现有的 10 次重试预算重跑。
- 重跑会重复 map 阶段的模型调用，接受这一代价。缓存 map 结果不在本片范围内。

### 2.3 诊断

- 失败日志带上原因类别（`context canceled` / `deadline exceeded` / 传输错误），不含模型正文。
- 批次上下文结束时记一行 `context.Cause`，用于以后查清本次取消的来源。

## 3. 验收（RED：`internal/application/service/wiki_ingest_notrun_test.go`，Claude 编写，受保护）

1. 7 种用途在发送前被取消时都是 NOT_RUN，而且没有调用模型（当前有 5 种是 UNKNOWN）。
2. 页面改写与分类在发送后被取消，仍是 OUTCOME_UNKNOWN，调用 1 次。
3. 实现方另补：
   - 一个批次的上下文在分类阶段被取消：没有页面改写被发出；操作被释放、不转死信；知识的处理位不释放；批次状态不是 `success`；
   - 已发出后失败的改写仍转死信为 UNKNOWN；
   - `execution_id` 被清除后，下一次认领可以成功。

## 4. 改动范围

- `internal/application/service/wiki_ingest.go`、`wiki_ingest_batch.go`（已登记）、`wiki_ingest_outcome.go`（项目文件）；
- 如需新增认领存储方法：`internal/types/interfaces/task_queue.go` 与对应仓库实现（上游时追加登记，G10 由 Claude 单独处理）；
- 实现方测试。

## 5. 上线

合并后随下一次 App 构建上线（需用户批准）。在此之前，S6 扩展遇到同类失败时人工重跑一次（#266 的做法）。
