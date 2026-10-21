# Q2b · Agent 回答引用：每条产品事实带出处，回答记录被引用的来源

> 状态：Claude 2026-10-21 提出，用户同日批准（#286："一起修"；因评测脚本误差，范围收窄为只修引用）｜ 作者：Claude Code
> 依据：问答评测 #286
> 实现方：Codex（Go）｜ 审核方：Claude ｜ 实现阶段真实模型调用：0
> 排期：在 Q2a（#287）合并之后实施（两片都改 `internal/enterprise/chatsource/`）

## 1. 问题（评测与代码核对，`main@6f14852e2`）

- **评测结果**：评测中 Agent 回答事实基本正确（L3 后 wiki 库 21/30、混合 22/30），但**没有任何引用**的回答分别有 13/30 和 10/30。用户与对外接口无法回验这些回答。
- **引用指令是建议，不是要求**：`modelcontext/citations.go` 的协议写的是"在来源支撑相邻内容时引用"，没有来源时可以不引用。企业知识说明（`chatsource.KnowledgeNotice`）只说"引用当前工具返回的字段句柄"，没有要求每条产品事实都带出处。
- **Agent 回合不记录引用**：
  - `AgentState.KnowledgeRefs` 初始化后从未写入，消息的 `knowledge_references` 因此始终为空；
  - 前端靠工具事件拼出来源，对外接口与评测拿不到结构化来源；
  - 快问快答没有这个问题。
- **更正**：#286 中"Agent 停不下来"是评测脚本把工具事件数当成调用数造成的，线上不存在这个问题，本切片不处理。

## 2. 设计

### 2.1 企业知识说明要求每条产品事实带出处

在 `KnowledgeNotice` 末尾（Space 有 wiki 库时）追加这一句：

```
回答中的每一条产品事实都必须在同一行带上支撑它的来源句柄（如 <ref id="c1"/>）；找不到可引用来源的产品事实不要写，改为说明未找到。
```

- 只改企业 Space 回合的说明，不改通用引用协议，也不影响普通知识库的 Agent。
- 已有说明的其余内容与顺序不变。

### 2.2 Agent 回合记录被引用的来源

最终回答展开引用后，把**回答中实际引用到**的知识来源写入 `AgentState.KnowledgeRefs`：

- **范围**：按回答中首次出现的顺序去重；没被引用的检索结果不写入。
- **字段**：每条是一个 `types.SearchResult`，至少有：
  - `ID`：与展开后 `<kb chunk_id=..>` 相同，包括 `release:<id>:<slug>`；
  - `KnowledgeBaseID`、`KnowledgeID`、`KnowledgeTitle`（有就带）；
  - `Metadata["source_tier"]`：`release`、`wiki_page` 或 `raw_text`；企业来源同时带 `release_id`。

  层级与 Q1a/Q1b/S6e 已有的标注一致；只有工具已标注过层级的来源才写层级，不靠 ID 前缀猜。
- **路径**：现有完成事件与消息保存流程会把它写进消息的 `knowledge_references`，不新增事件类型。
- **覆盖的回答方式**：正常结束的回答、达到轮数上限后强制给出的回答，都要记录。
- **适用范围（2026-10-21 按 #289 实现方提问补充）**：记录被引用来源是通用行为，对所有 Agent 生效，包括普通知识库的 Agent。WeKnora 的 `AgentState.KnowledgeRefs` 字段本来就为此设计，只是从未写入；验收用的是通用引擎。企业专属的只有 2.1 的说明文字。普通知识库 Agent 的提示词、回答正文与工具流程保持不变，唯一变化是消息多了被引用来源的记录。

### 2.3 不做

- 不在回答结束后再调用一次模型补引用。先看 2.1 的效果：复测后没有引用的回答仍多于 1/5，再提出补引用切片。
- 不改通用引用协议；普通知识库 Agent 的提示词、正文与工具流程不变（只多记录被引用来源）；不处理工具循环。

## 3. 上游补丁

改动已登记或需登记的 `internal/agent/` 与 `internal/modelcontext/` 文件，在 `docs/design/upstream-patches.md` 追加一行；G10 基线由 Claude 审查后更新。`chatsource` 是项目自有包。

## 4. 验收（RED，Claude 编写，受保护）

- `internal/enterprise/chatsource/citation_notice_test.go`：
  1. Space 有 wiki 库时，说明含 2.1 的那句要求；
  2. 没有 wiki 库时，说明仍为空。
- `internal/agent/answer_references_test.go`：
  3. 本轮登记了三个来源：一个已发布字段 `release:rel-1:E/field`、一个原文片段 `chunk-raw`、一个没被引用的 `chunk-unused`。模型回答引用前两个，且第一个引用了两次。执行后 `KnowledgeRefs` 的 ID 依次为 `release:rel-1:E/field`、`chunk-raw`，不含 `chunk-unused`。
  4. 回答没有任何引用时，`KnowledgeRefs` 为空。

实现方另补：

- `source_tier` 与 `release_id` 元数据；
- 达到轮数上限后强制给出的回答也记录引用；
- 消息 `knowledge_references` 被写入；
- 普通知识库 Agent 的提示词、正文与工具流程不变。

## 5. 改动范围

- `internal/enterprise/chatsource/knowledge.go`；
- `internal/agent/`（结束与引用记录）与 `internal/modelcontext/`（如需保存来源层级）；
- 实现方测试；
- `docs/design/upstream-patches.md` 追加登记。

## 6. 上线与验证

合并后随 App 构建上线（需用户批准），用 #286 的同一套题复测两种 Agent 问法。预算已获批准：约 250 次调用加 1 个评委会话。评分规则改进：评委能看到产品编号，有引用支撑的补充事实不算无依据。
