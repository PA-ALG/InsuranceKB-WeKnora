# S5b-3d-2b · Harness 提交待确认项时带上原文件引用

> 状态：Claude 2026-10-27 提出 ｜ 作者：Claude Code
> 依据：S5b-3d-2 Spec §5（分支 `slice/s5b3d2`，PR #378）：平台给待确认项增加可选的 `source_ref`，管理员可以打开原文件；Harness 一侧另开本切片。
>
> 实现方：Claude ｜ 审核方：Codex（跨组件请求体）｜ 真实模型调用：0 ｜ 数据库迁移：无

## 1. 目标

Harness 推送的每个待确认项都带上 `source_ref`，值为这份材料在平台上的来源引用：

```
source:v1:<knowledge_id>:<parse_attempt>:<sha256>
```

三项都取自 `PendingEntry`，与证据引用使用同一个 `SourceRevision.ref`。待确认页上的"打开原文件"按钮靠它来定位文件。

## 2. 做法

1. `ConfirmationInput` 增加 `source_ref: str | None = None`。请求体中，值为 None 时**省略**这个键，因为旧平台的严格解码会拒绝未知键。`ConfirmationItem` 增加 `source_ref: str = ""`，平台对空值省略这个字段。
2. `question_of` 填入 `source_ref`。题目的 revision 不变：它已经包含 knowledge_id、parse_attempt 和 sha256。
3. 提交结果核对（客户端的 `_asked`）与同步时比较内容（`_content`）都加入 `source_ref`，因为平台的内容指纹包含它。
4. **过渡：已有的待确认项。** 平台上已有的项不带 `source_ref`，内容指纹与新题不同，所以：
   - **没有答复的旧项**：照 S5b-3d-1 改文案时的做法，推送带引用的新项，旧项在清理时关为 obsolete。每份材料只发生一次。
   - **已有答复的旧项**（有人已经答复，本系统还没处理）：**不能丢答复。** 同一份材料，如果平台上有一个未关闭、已答复、不带 `source_ref` 的项，而且它的 subject、revision、title、detail、options 与新题完全相同（只差引用），本次运行**先按这个旧项结算**，与平常结算答复一样：
     - 结算会得出 applied 或 obsolete，规则与平常相同；
     - 这一次不推送新题；
     - 清理时也不把这个旧项关为 obsolete。

     如果这次没能结算（例如读不到文件开头，或者登记表拒绝），旧项保持打开，下次运行再试。
5. **上线顺序**：本 PR 可以随时合并，但**在平台的 S5b-3d-2（#378，迁移 000012）部署之前，不得对线上运行**。旧平台的严格解码会把带 `source_ref` 的整批请求拒为 400。

## 3. 改动范围

- `harness/src/insurance_harness/bundle/confirmation_items.py`、`bundle/client.py`（只改请求体与 `_asked`）；
- `harness/src/insurance_harness/ingest/confirmation_questions.py`、`ingest/confirmations.py`。`confirmations.py` 会超过 500 行，所以把"平台项如何对应题目与结算"的比较规则移到新模块 `ingest/confirmation_matching.py`；
- 测试。

不改平台、`contracts/`，文案版本也不变。

## 4. 验收（RED，Claude 编写）

- `tests/ingest/confirmation_platform.py`：假平台按 000012 的规则处理 `source_ref`，规则如下：
  - 可选；
  - 格式与 `release.ParseSourceRef` 相同；
  - 非空时计入内容指纹；
  - 为空时省略。
- `tests/ingest/test_confirmations.py` 第一个用例：比较推送内容时加入 `source_ref` 键。这是受保护断言的最小改动，原因是请求体按本 Spec 增加了这个字段。
- 新增 `tests/ingest/test_confirmation_source_ref.py`，覆盖以下情况：
  - 题目带上准确的引用；
  - 请求体对 None 省略这个键；
  - 客户端拒绝引用不一致的提交结果；
  - 没有答复的旧项被换成带引用的新项，只换一次；
  - 已有答复的旧项按原答复结算，不推新题；
  - 读不到文件开头时，已答复的旧项保持打开。
