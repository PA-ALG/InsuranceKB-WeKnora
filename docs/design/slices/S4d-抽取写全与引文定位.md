# S4d · 抽取写全与引文定位：把完整率往上推

> 状态：用户已批准（2026-10-14：先做 S4d；真实调用约 60 次、$1–3，评委会话 2–3 个） ｜ 作者：Claude Code ｜ 依据：蓝图 §2.5、§7.1、§7.7、§12（"不达标时调整抽取配置或分片"）；S4b 结果
> 分支：`slice/s4d` ｜ 工作目录：`.worktrees/s4d` ｜ 实现方：Claude ｜ 审核方：Codex（编译器与引文校验属复杂改动）

## 1. 目标

S4b 用 `deepseek-flash` 在 4 款产品上测得：准确率 81%–100%、**完整率 6%–36%**、幻觉 0。完整率差距有两个可修的来源：

1. **写不全**：L3 后仍有 48 个字段只覆盖了 Golden 的部分事实（缺条件、例外、选项与适用对象）。
2. **引文校验丢字段**：1816 丢 19、1814 丢 9、1824 丢 2（原因见 §2）。

本片只做可在 Harness 内解决的部分，并用 S2c/S4b 的同一套评分量化每一步。

## 2. 先验分析（2026-10-14，用 S4b 已保存的原始回答，零调用）

S4b 丢掉的 30 个字段里，**27 个至少有一条引文能逐字回验**——字段被丢是因为同一字段的多条引文里有一条对不上（编译器"任一引文失败即丢整个字段"）。对不上的引文按原因分：

| 原因 | 例子 | 能否在 Harness 内修 |
|---|---|---|
| **版面文字交错**：页边小标题、两栏表格被 pdfplumber 混入正文 | 1814 条款原文抽取为"保险金**限制**险金总和"，模型引用的是干净正文 | 否，需版面解析（S4c 调研 WeKnora 解析产物） |
| **标错文件或页码**：引文逐字存在于同一产品的另一份文件 | 1814 退保、1816 宽限期引文实在说明书，却标为条款 | 能：在该产品全部文件中查找**唯一**逐字命中 |
| **拼接引文**：模型跳过中间文字把两段拼成一句 | 1816 保险责任引文漏掉中间一句 | 部分能：提示词明确"引文必须是原文连续片段，不得跳过或拼接" |

"同一文件内更正页码"这一项按实测**救回 0 个字段**，已从设计中删除。

## 3. 设计

### 3.1 引文定位扩到同一产品的全部文件（`evidence/quote_verification.py`）

- `QuoteVerifier.verify(reference)`：先按声明的 `(document, document_sha256, page)` 校验，命中则行为不变；
- 声明处找不到（或声明页不存在）时，在构造它的**全部页**（即同一产品的全部文件）按现有 `verify_quote` 规则查找；
  **恰好一页**命中时返回指向该页的 `VerifiedQuote`，并填 `cited_document`、`cited_page`（模型声明的文件与页）；
  零页或多页命中返回 `None`（多页即歧义，不猜）。
- `VerifiedQuote` 新增可选字段 `cited_document: str | None = None`、`cited_page: int | None = None`，只在重定位时填写。
- 不放宽 EXACT / NORMALIZED 判定；不跨产品（verifier 只持有本产品的页）。
- **有意改变 S4a 的"标错页即拒绝"**：S4a 的三条测试（受保护的 `test_engine_contract.py` 一条、实现方 `test_engine_boundaries.py` 两条）在单独提交 `214dbf45f` 中改为新规则下仍成立的不变量：任何页都找不到的引文仍被拒；文件、指纹或页码错且原文出现在多页时因歧义仍被拒；跨页拼接永不接受。由审核方逐条确认。

### 3.2 写全与引文保真（`compilers/schema_fields/prompt.py`）

`SYSTEM_PROMPT` 增加两条通用规则（验收测试检查关键词）：
- 写全：value 必须列全原文中该字段的全部数值、选项、条件、例外与适用对象，**不得概括**，不得用"等"省略；
- 保真：quote 必须是原文中**连续**的一段，不得跳过中间文字，不得把不相邻的两处拼成一句。

批量大小已是 `compile_run --batch-size`，不新增配置。

### 3.3 回放模式（`eval/compile_run.py`）

`compile_products(..., replay_from: Path | None = None)` 与 CLI `--replay-from <run_root>`：对每款产品按序读取
`<replay_from>/<产品>/responses/<最新 attempt>/NNN.txt` 作为模型回答，**不构造客户端、不占预算、不写 budget.jsonl**；
其余流程（解析、引文校验、写 output、候选合并）与真实运行相同。保存的回答少于所需批次即报错。
用途：A 轮实验；以后改引文校验或解析时做零成本回归。

### 3.4 实验（按 Issue 预算）

每轮：编译 4 款 → `semantic_run`（L2 由 `codex exec` 启动的 GPT-6 Astra / xhigh 会话）→ L3 → 报告准确率、完整率、丢字段数、调用与费用。

| 轮次 | 变化 | 发送 |
|---|---|---|
| A | 仅跨文件引文定位：`--replay-from ~/compile-runs/s4b-v1` | 0（只统计救回的字段，不开评委会话） |
| B | 新提示词，批量 25 | ~11 |
| C | 新提示词，批量 10 | ~25 |

B、C 各开一个评委会话；取完整率最高、准确率不降、幻觉仍为 0 的组合，写进 PR 与 `stages.json` 旁的说明。

### 3.5 不在本片

- 版面文字交错（页边标题、两栏表格）：S4c 先调研 WeKnora 解析产物对这些 PDF 的输出是否正确，再决定页文本来源。
- "部分引文通过即保留字段"的放宽：会让无原文依据的内容进入结果，与蓝图"具体产品事实必须可回验"冲突，不做。

## 4. 交付物与验收

- 受保护验收（Claude 写，RED）：`harness/tests/evidence/test_quote_relocation.py`、`harness/tests/eval/test_compile_replay.py`、
  `harness/tests/compilers/schema_fields/test_prompt_rules.py`；
- `harness/` 下 `pytest tests/evidence tests/compilers tests/eval tests/models`、`ruff check .`、`mypy src tests` 通过；守卫 25 项通过；CI 全绿；
- PR 写明 A/B/C 三轮的准确率、完整率、丢字段数与费用，以及最终选定的批量大小。

## 5. 改动范围

- 允许修改：`evidence/quote_verification.py`、`compilers/schema_fields/prompt.py`、`eval/compile_run.py`，及对应实现方测试。
- 受保护：上面三个验收文件、S4a 的 `test_engine_contract.py`、既有受保护验收、`docs/design/`、蓝图。
- 不改：`models/`、Golden、Catalog、`extraction_profiles.json` 的绑定关系。

## 6. 真实调用预算（用户 2026-10-14 批准）

- 模型：`deepseek-flash`（阶段 `schema_fields`）；B 轮约 11 次、C 轮约 25 次，**上限 60 次**（含重试），各轮 run root 分开，`--max-sent` 强制执行；约 $1–3。
- 评委：GPT-6 Astra / xhigh，由 Claude 以 `codex exec` 启动，B、C 各 1 个会话。
