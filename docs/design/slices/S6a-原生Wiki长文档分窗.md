# S6a · 原生 Wiki 长文档分窗：候选概念读完整份文档，引用按窗口给候选，输出被截断时明确失败

> 状态：用户 2026-10-18 批准（"原生 Wiki 长文档被截断，要不要做修复实验——修复吧"） ｜ 作者：Claude Code
> 依据：#199 第二轮结论（1828 条款约 5 万字，两轮都没有处理成功）、蓝图硬边界 3（上游补丁登记）、AGENTS 首要原则
> 实现方：Codex（Go，上游文件）；审核方：Claude

## 1. 问题（#199 第二轮，代码核对见本节末）

1. **输入截断**：`mapOneDocument` 把整份文档拼起来后截到 `maxContentForWiki = 32768` 个字符，再交给候选概念、文档摘要和撤回三步。5 万字的条款，后一半永远进不了候选概念。
2. **输出截断**：每次 Wiki 调用的输出上限都是 `wikiLLMMaxTokens = 32768`。详尽粒度下，候选列表 JSON 和引用调用的输出都会超过上限。`finish_reason` 被忽略，被截断的答案按 JSON 解析失败处理，看不出真正的原因。
3. **引用调用的候选列表随文档增长**：每个引用批次（约 12,000 字）都附上整份文档的全部候选，候选越多，输入和输出越大。

代码位置（`main@c82cd6cf2`）：

- `wiki_ingest.go:41`：`maxContentForWiki`；`:178`：`wikiLLMMaxTokens`；
- `wiki_ingest_batch.go:1253-1258`：截断；`:1308`：候选概念；`:1374`：摘要；`:1587`：撤回；
- `wiki_ingest_cite.go:74`：`extractCandidateSlugs`；`:152`：`splitChunksIntoCitationBatches`；`:282`：`classifyChunkCitations`。

## 2. 设计（通用机制，不按文档或产品特判）

1. **分窗**：
   - `mapOneDocument` 不再截断。改为按文档顺序，把文本 chunk 分成若干窗口，每个窗口重建后的内容不超过 `maxContentForWiki` 个字符（复用 `splitChunksIntoCitationBatches` 的排序与"单个超大 chunk 独占一批"规则）。
   - 只有一个窗口的文档（不超过 32,768 字），行为与现在完全相同。
2. **候选概念按窗口**：
   - 每个窗口单独调用一次候选概念提示词，`PreviousSlugs` 与粒度不变；并发数不超过现有引用批次的并发上限。
   - 各窗口的候选按 slug 合并：首次出现的名称与描述为准，别名去重合并。合并后的集合交给现有的 `deduplicateExtractedBatch`。
   - 任一窗口失败，整份文档按候选阶段失败处理，沿用现有 FAILED/UNKNOWN 分类，不回退到短 `details`。
3. **引用按窗口给候选**：
   - 引用批次在各自窗口内划分，不跨窗口；每个批次的 `<candidate_slugs>` 只列出该窗口找到的候选。
   - `new_slugs` 机制不变：某个窗口里出现、但没在该窗口候选中的概念，仍可经 `new_slugs` 加入。
   - 合并引用沿用 `mergeCitationsIntoItems`。
4. **摘要与撤回**：仍用第一个窗口的内容（与现在用截断后内容的效果相同）。日志写明窗口数与各窗口长度。
5. **输出被截断时明确失败**：
   - 候选概念与引用两类调用，`finish_reason == "length"` 时不再尝试解析，返回 `wikiStageFailure{Stage: 对应阶段, Outcome: FAILED}`，`Cause` 包装新的哨兵错误 `errWikiOutputTruncated`。
   - 页面改写已有续写机制，不在本片范围。
6. **不改的东西**：粒度、提示词文本、输出 token 上限、引用批次大小、重试与结算语义、受管 KB 的 G3 路径。

## 3. 上游补丁

- 改动只落在已登记的上游文件：`wiki_ingest.go`、`wiki_ingest_batch.go`、`wiki_ingest_cite.go`。这些文件已在 G10 基线中，计数不增加。
- 在 `docs/design/upstream-patches.md` 追加一行：
  - 原因："长文档候选概念只读前 32k、输出截断被当作解析失败"；
  - 能否回馈上游：是；
  - 退出条件："上游对长文档分段处理候选概念并检查 finish_reason 后撤回"。

## 4. 验收（RED：`internal/application/service/wiki_ingest_longdoc_test.go`，Claude 编写，受保护）

1. 约 54,000 字、90 个 chunk 的文档：候选概念调用不少于 2 次。每次调用的文档内容不超过 32,768 字；首尾两段的标记都出现在某次候选调用中，说明整份文档都被读到了。
2. 含尾段标记的引用批次列出尾段窗口找到的候选，只含首段的批次不列出它。
3. 候选答案 `finish_reason == "length"` 时，`mapOneDocument` 返回 `wiki_candidate_slug` 阶段的 `wikiStageFailure`，`errors.Is(err, errWikiOutputTruncated)` 为真，且不再发出引用调用。
4. 实现方另补：单窗口文档的行为不变（现有测试全部保持通过）；引用调用被截断时同样失败；合并去重（同一 slug 出现在两个窗口）。

## 5. 真实验证（合并之后，单独开 Issue）

- 构建并替换 App 1 次。用户批准修复，验证必须用新 App；需要的构建在验证 Issue 中写明。
- 只用 1828 验证：新建一个不受管知识库，配置同 #199 C2（单产品、不传费率表、详尽粒度）。
- 生成调用约 60 次 deepseek-flash。用同一套盲评办法、1 个评委会话，与 C2-1828 对比准确率和覆盖率。
- 判定规则（运行前写定）：
  - 1828 条款处理成功（不再出现候选或引用阶段的截断失败）；
  - 覆盖率高于 C2-1828（46/74）；
  - 准确率不低于 C2-1828（9/16 页）。
