# QA5 · 网络搜索关闭时 web_search 意图回落到知识库检索

> 状态：Claude 2026-11-01 提出 ｜ 作者：Claude Code ｜ 用户 2026-10-27 已将审批全部授权给 Claude
> 实现方：Claude ｜ 审核方：Codex ｜ Issue #527 ｜ 真实模型调用：0（上线后的复核另计）

## 1. 依据

11-01 线上问答版本回归（#501 评论，原始数据存仓库外的私有位置）：20 道版本题中有 3 道
（"现在还能/可以买吗"一类）零引用作答，回答说"未开启网络搜索"。App 日志为 `intent=web_search`、
`SearchParallel skip reason="intent_no_search"`。

机理（上游 v0.9.0，固定基线与上游 main 相同）：

1. 问题理解（`QUERY_UNDERSTAND`，`chat_pipeline/query_understand.go`）让模型在 `kb_search`、`web_search`、
   `chitchat` 等意图中选一个；"现在还能买吗"带时效词，被判为 `web_search`。
2. `ChatManage.NeedsRetrieval()`（`internal/types/chat_manage.go`）对 `web_search` 只看 `WebSearchEnabled`：关闭时返回
   false。
3. 于是检索、重排、合并、TopK 各阶段全部跳过；企业已发布字段的注入（Q1b-2，同样以 `NeedsRetrieval()` 为条件）也不做；
   企业"找不到就给固定答复"的规则（Q2a）同样以 `NeedsRetrieval()` 为条件，不触发。
4. 问题理解在 `!NeedsRetrieval()` 时套用意图提示（`applyIntentPromptOverride`，写入 `SystemPromptOverride`），
   `web_search` 的提示告诉用户网络搜索不可用。

对企业快问快答，这些问题的答案就在本轮固定的 Release 与原文里；网络搜索关闭时，`web_search` 意图唯一能用的来源就是知识库。

## 2. 方案

### 2.1 规则

本轮**读企业知识**（`chatsource.HasPublished(ctx) || chatsource.IsEnterpriseAnswer(ctx)`，与 Q2a 固定答复的判定相同）、
**网络搜索关闭**、且问题理解给出的意图为 `web_search` 时，在问题理解阶段结束后把意图改为 `kb_search`，并清空
`SystemPromptOverride`。之后各阶段照常按 `NeedsRetrieval()` 走知识库检索、字段注入与固定答复。

- 结果状态与"模型直接给出 `kb_search`"完全相同：问题理解只在 `!NeedsRetrieval()` 时写 `SystemPromptOverride`（全仓只有
  `applyIntentPromptOverride` 写它），`kb_search` 不写。
- 不变：不读企业知识的回合（普通知识库的问答、搜索接口；Agent 不走这条管线）；网络搜索开启时（`web_search` 本就检索知识库并加网页）；
  `chitchat`、`greeting` 等其他不检索意图；问题理解失败（意图为空，本就检索）。
- 日志：改写时记一条 Info（只记意图，不记问题原文）。

### 2.2 为什么放在企业层

| 做法 | 结论 |
|---|---|
| 配置 | 没有可用开关：`IntentSystemPrompts` 只换提示词，不改检索；按 Agent 改写问题理解提示词是改提示词，判别不稳定，且不在本片范围 |
| 改 `NeedsRetrieval()` 一律回落 | 改变普通知识库行为（上游的设计是告诉用户网络搜索不可用），不采用 |
| 给 `ChatManage` 加字段、`NeedsRetrieval()` 读它 | 要多改一个上游文件（`internal/types/chat_manage.go`，G10 +1）并在 `Clone` 里同步，不如下一种少 |
| **企业层函数 + 已有接缝调用一行** | `session_knowledge_qa.go` 已为企业阶段作用域打过补丁（QA2 `RetrievalScope`、`AnalysisScope`）；在同一循环里加一行调用，规则留在 `internal/enterprise/chatsource`，G10 文件数不变 |

### 2.3 接口（冻结，验收依赖）

```go
// internal/enterprise/chatsource/intent.go
func AnswerIntent(ctx context.Context, event types.EventType, cm *types.ChatManage)
```

`event != QUERY_UNDERSTAND`、`cm == nil`、不满足 §2.1 任一条件时什么都不做。调用点：`KnowledgeQAByEvent` 循环中阶段触发并恢复
作用域之后（`restoreAnalysis()` 之后）。

## 3. 改动范围

- 新文件 `internal/enterprise/chatsource/intent.go`
- 上游文件 `internal/application/service/session_knowledge_qa.go`：一行调用；`docs/design/upstream-patches.md` 追加登记行
- 验收测试：`internal/enterprise/chatsource/intent_test.go`、`internal/application/service/session_web_search_intent_test.go`

不改提示词正文、AnswerRules、Harness、`contracts/`、前端；G10 文件数不变（151）。

## 4. 验收

1. 函数（`intent_test.go`）：
   - 企业快问快答（固定了 Release）、只读已发布字段的回合：网络搜索关闭 + `web_search` → `kb_search`，`SystemPromptOverride` 清空；
   - 网络搜索开启：意图与提示不变；
   - `chitchat`、`greeting`、`kb_search`、空意图：不变；
   - 普通知识库、搜索接口（`ResolveQuick`）回合：不变；
   - 其他阶段（如 `CHUNK_SEARCH_PARALLEL`）调用：不变。
2. 接线（`session_web_search_intent_test.go`，真实 `KnowledgeQA` 与并行检索插件，问题理解由测试插件模拟输出）：
   - 企业快问快答 + `web_search` + 网络搜索关闭：本轮固定原文被检索一次，模型收到"已发布字段 + 固定原文"，无意图提示；
   - 同样设置但意图为 `chitchat`：不检索，意图提示保留；
   - 普通知识库 + `web_search` + 网络搜索关闭：不检索，意图提示保留（上游行为）。

## 5. 上线后复核

随下一次 App 部署上线；复核用 11-01 版本题中 v01、v17、v18 三题（每轮 2 次平台调用：问题理解 + 回答），期望有引用且不再说
"未开启网络搜索"。
