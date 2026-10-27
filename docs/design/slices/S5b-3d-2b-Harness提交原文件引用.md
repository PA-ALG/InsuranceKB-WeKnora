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
4. **已有的待确认项：原样保留，不迁移**（Owner 2026-10-27 第二轮裁定，取代原来的过渡方案）。
   - 平台上未关闭、不带 `source_ref` 的项，如果除引用外内容与新题完全相同（subject、revision、title、detail、options），就**视为同一道题**：
     - 原样保留，不为补引用而关为 obsolete，也不重新提交新题（不发 POST）；
     - 这一项只是没有"打开原文件"按钮；
     - 它的答复走平常的结算路径。
   - 关为 obsolete 只沿用 main 已有的原因：题目确实变了，或者材料已不再等待确认。
   - 理由：Codex 审核 #380 时指出，旧方案在补引用时要把旧项关为 obsolete。平台关 obsolete 时不检查答复，管理员答复与关项交错时会丢答复；中断后恢复的路径也绕过了"本次不推新题"的保护。不迁移就没有这些窗口。补引用本身也不值得为它关项：线上当时没有未关闭的待确认项，以后的新题都会带引用。
5. **上线顺序**：本 PR 可以随时合并，但**在平台的 S5b-3d-2（#378，迁移 000012）部署之前，不得对线上运行**。旧平台的严格解码会把带 `source_ref` 的整批请求拒为 400。

## 3. 改动范围

- `harness/src/insurance_harness/bundle/confirmation_items.py`、`bundle/client.py`（只改请求体与 `_asked`）；
- `harness/src/insurance_harness/ingest/confirmation_questions.py`、`ingest/confirmations.py`。`confirmations.py` 会超过 500 行，所以把"平台项如何对应题目与结算"的比较规则移到新模块 `ingest/confirmation_matching.py`；
- 测试。

不改平台、`contracts/`，文案版本也不变。

## 4. 验收（RED，Claude 编写）

- `tests/ingest/confirmation_platform.py`：假平台按 000012 的规则处理 `source_ref`，规则如下：
  - 可选；
  - 格式与 `release.ParseSourceRef` 相同（正则加有符号 int64 解析）；
  - 非空时计入内容指纹；
  - 为空时省略。
- `tests/ingest/test_confirmations.py` 第一个用例：比较推送内容时加入 `source_ref` 键。这是受保护断言的最小改动，原因是请求体按本 Spec 增加了这个字段。
- 新增 `tests/ingest/test_confirmation_source_ref.py`，覆盖以下情况：
  - 题目带上准确的引用；
  - 请求体对 None 省略这个键；
  - 客户端拒绝引用不一致的提交结果；
  - 除引用外相同的不带引用旧项：原样保留，不关、不推新题；它的答复照常结算；
  - 假平台对 `source_ref` 的校验与 Go 的 `ParseSourceRef` 一致，attempt 取有符号 int64：最大值接受，最大值加一拒绝。
