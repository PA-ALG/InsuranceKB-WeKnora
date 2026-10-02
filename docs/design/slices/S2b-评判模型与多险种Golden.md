# S2b · 评判模型生成多险种 Golden，并给出 G3 的第一份有效质量数字

> 状态：待用户批准 ｜ 作者：Claude Code ｜ 依据：技术蓝图 1001 §7.7、§11（S2）
> 分支：`slice/s2b`（S2a 合并后同步到 `main`） ｜ 开工方式：**等确认再开工**
> 评判模型：**GPT-6.1 sol**（用户 2026-10-02 确认），在**独立的 Codex 会话**里担任评委，与代码用文件交换题目和答案；
> 不走 API，不需要密钥。工作量见 §6。

## 1. 目标

S2a 的尺子能用，但唯一有 Golden 的产品 596 在 epoch9 里没被重新抽取（67 个字段只有 2 个有值），测出的 0% 不代表
G3 的抽取能力。本片用离线评判模型，为 G3 实际抽取过的 5 款产品生成 Golden，覆盖 5 个险种 pack，然后给出
G3 在这 5 款上的逐 pack、逐字段 precision / recall——这是项目第一份能说明问题的质量数字。

| 产品 | 名称 | pack | epoch9 有值字段 |
|---|---|---|---|
| 1826 | 平安守护百分百（2026）两全保险 | `schemapack_endowment_insurance` | 40/79 |
| 1824 | 平安盛世金越（尊享版26）终身寿险 | `schemapack_whole_life_insurance` | 39/75 |
| 1814 | 平安附加（2026）意外伤害保险 | `schemapack_accident_insurance` | 38/62 |
| 1816 | 平安附加（2026）失能收入损失保险 | `schemapack_disability_income_insurance` | 49/76 |
| 1828 | 平安安佑福（全能版）重大疾病保险 | `schemapack_critical_illness_insurance` | 41/67 |

## 2. 原则

- **盲评**：评判模型只看产品原文与字段定义，绝不看 epoch9 或任何候选结果。评委会话只打开题目目录（在任何 git 仓库之外），
  不打开本仓库、`dataset/golden/`、epoch9 或任何抽取输出。实现者会话写代码时看过现有 Golden 与 epoch9，**不能兼任评委**。
- **只评可从文档得出的字段**：Catalog 中 `formation_method` 含"原文抽取"的字段才进 Golden；纯"外部映射""规则衍生""LLM生成"
  的字段不进（它们不来自 PDF）。评分时这些字段计为 unscored。每个 pack 约 38–55 个字段。
- **证据确定性回验**：评判模型给出的每条引文必须在它声明的页面原文里找到（归一化后子串匹配）；找不到就丢弃该引文，
  present / absent 若没有一条通过回验，整个字段记为 `evidence_not_verified` 并排除出 Golden，不改成 unknown。
- **先校准再使用**：先在 596 上对照已批准的 40 条 Golden 校准，达标才生成 5 款产品的 Golden（§4）。
- **来源标注**：生成的条目 `judged_by="model:<模型 ID>"`，与人工、旧金标区分；业务专家回归后抽检复核，不覆盖原记录。

## 3. 设计

新代码继续放 `harness/src/insurance_harness/eval/`，不 import 旧目录。

| 模块 | 职责 |
|---|---|
| `eval/pdf_text.py` | `PageText(document, document_sha256, page, text)`；用 pdfplumber 按页抽文本并计算文件 SHA256 |
| `eval/judge.py` | `JudgeRequest(system, user)` 与只读属性 `sha256`、`JudgeClient` 协议（`complete(request) -> str`、只读属性 `model_id`）、`JudgeAnnotator`、`AnnotationResult`、`JudgeProtocolError`、`JudgeBudgetExceeded`、`calibrate()` |
| `eval/judge_files.py` | 文件交换（§3.2）：`write_requests(requests, run_dir) -> list[Path]`；`FileJudgeClient(run_dir, *, model_id)` 实现 `JudgeClient`，另有 `unconsumed() -> list[str]` |
| `eval/catalog.py`（扩展） | `field_definition(pack_id, field_key)`：返回 short_title、description、source_guidance、value_spec、formation_method；`source_extractable_fields(pack_id)` |
| `eval/annotate.py` | CLI：`prepare`（出题）与 `ingest`（收卷、回验、写 `dataset/golden/v1/<product_id>.jsonl`；`--calibrate` 只出校准报告） |
| `eval/report.py`（扩展） | 支持多个 Golden 文件，逐 pack 输出 |

### 3.1 JudgeAnnotator（验收测试按此断言）

```python
JudgeAnnotator(client, catalog, *, max_calls: int, batch_size: int)
  .annotate(product_id, pack_id, field_keys, pages) -> AnnotationResult

AnnotationResult: items: list[GoldenItem], rejected: dict[field_key, reason], calls: int, model_id: str
CalibrationReport: compared, not_judged: list[field_key], state_agreement,
                   present_value_agreement, disagreements: dict[field_key, "state" | "value"]
```

- 按 `batch_size` 把字段分批，每批一次调用；**每次调用前**检查 `calls < max_calls`，否则抛 `JudgeBudgetExceeded`，不发送。
- Prompt：系统消息给三态规则与输出 JSON 格式；用户消息给产品与 pack、每个字段的 key/中文名/说明/取值来源/取值规范，
  以及带 `[page N]` 标记的全部页面原文。**不包含任何预测或候选值。**
- 输出 JSON `{"fields":[{field_key, state, value, components:[{name, accepted:[...]}], evidence:[{document, page, quote}]}]}`；
  允许 ```json 代码块包裹。
- 以下一律 `JudgeProtocolError`：无法解析；缺少请求的字段；出现未请求或重复的字段；三态与值、证据的形状不符。
- `calibrate(judged, reference)`：只比较两边都有的字段；三态一致计 `state_agreement`；双方 present 时用 S2a 的
  `compare_value`（参考 Golden 的值与组成要素）判定 `present_value_agreement`。
- `build_requests(product_id, pack_id, field_keys, pages) -> list[JudgeRequest]`：返回 `annotate` 会发出的同一批请求
  （同样的分批与 prompt），不调用 client、不占预算。每批 prompt 只取决于产品、pack、本批字段与页面原文，**不含**批次序号、
  批次总数、时间戳，因此"同样输入出同样题目"。
- 页面原文的格式：每页先单独一行 `[page N]`，下面是该页原文的各行。
- `JudgeRequest.sha256`：`{"system", "user"}` 的确定性 JSON 序列化（UTF-8）的 SHA256 十六进制串。

### 3.2 文件交换（验收测试 `test_judge_files.py` 按此断言）

```text
<run_root>/<product_id>/        run_root 必须在任何 git 仓库之外，建议 ~/judge-runs/s2b
  AGENTS.md                     评委规则（§3.3），prepare 时写入
  run.json                      product、pack、字段清单、batch_size、prompt 版本、源文件 SHA256、每道题的 sha256
  requests/001.json …           {"request_sha256", "system_lines": [...], "user_lines": [...]}（按行存，便于 grep）
  responses/001.json …          评委写入：§3.1 的输出 JSON
```

- `write_requests`：从 `001` 起按顺序写 `requests/NNN.json` 并建空的 `responses/`；`requests/` 已存在时抛 `FileExistsError`，
  **不覆盖**；`run_dir` 或其任一上级目录含 `.git` 时抛 `ValueError`（消息含 "git"）——在仓库里开评委会话就能看到 Golden 与
  候选，不再是盲评。
- `FileJudgeClient.complete` 按调用顺序读第 N 个题目文件：用存储的行重算哈希，与存储的 `request_sha256` 和本次请求的
  `sha256` 三者必须一致，否则 `JudgeProtocolError`（消息含 "changed"）；题目或答案文件缺失时 `JudgeProtocolError`，消息含
  题号（如 `001`）。答案原样交给 `JudgeAnnotator`，解析、三态与引文回验与 §3.1 完全相同。
  `unconsumed()` 返回没被读到的题号。
- **`annotate prepare --product <id> --run-root <dir>`**：读 PDF → `source_extractable_fields` → `build_requests` →
  `write_requests`，再写 `AGENTS.md` 与 `run.json`。目录已存在就失败。
- **`annotate ingest --product <id> --run-root <dir> --judge-model gpt-6.1-sol [--calibrate]`**：从 `run.json` 读字段与
  `batch_size`，重读 PDF 重建题目，用 `FileJudgeClient` 回放；`unconsumed()` 非空即失败。`--judge-model` 必填，原样写入
  `judged_by="model:<id>"` 与 manifest。`--calibrate` 只允许 596，只输出 `CalibrationReport`，**不写** `596.jsonl`。
- 哈希只能证明题目没变，证明不了答题的是哪个模型：开评委会话的人必须选 GPT-6.1 sol，PR 里写明每个会话的模型与推理档位。

### 3.3 评委会话规则（prepare 写进每个产品目录的 `AGENTS.md`）

1. 你是保险条款的离线评委。只读当前目录下的文件；不打开当前目录以外的任何路径，不联网，不运行抽取或比对程序。
2. 逐个处理 `requests/` 里的题目：`system_lines` 是规则，`user_lines` 是题目。把答案写成严格 JSON，存为
   `responses/` 下的同名文件。已有答案的题目跳过（会话中断后可以新开会话接着做）。
3. 可以用 grep 等只读命令查找原文和核对引文；不得用脚本批量生成答案。
4. 引文必须从所在页原文**逐字复制**，并核对它确实在你声明的 `[page N]` 之下；原文没有依据就答 `unknown`，不要猜。
5. 不修改 `requests/`、`run.json` 与本文件。

### 3.4 运行顺序

1. **校准**：`prepare` 596 → 在 `<run_root>/596` 开评委会话答题 → `ingest --calibrate`，对照 `dataset/golden/v1/596.jsonl`。
   达标条件（初值，可在 PR 中提出调整）：三态一致率 ≥ 90%，双方都是 present 的字段值一致率 ≥ 80%，且
   `evidence_not_verified` ≤ 10%。不达标：**停下**，在 PR 中贴出不一致明细，允许修改一次 prompt（提升 prompt 版本，
   换新的 `run_root` 重新出题）后重跑一次校准；仍不达标则不生成 5 款产品的 Golden，交回 Claude 与用户决定。
2. **生成**：校准达标后才 `prepare` 5 款产品（同一 prompt 版本），**每款产品单开一个评委会话**，答完后逐个 `ingest`。
   先校准再出题，是为了 prompt 一旦要改，不会白答 5 款产品的题。
3. **评分**：用 report CLI 对 epoch9 candidate 评分，覆盖 5 个 pack（596 也一并报告）。

## 4. 交付物

- 上述模块与测试（验收测试之外的单测自行补充，测试中只用假评判客户端，CI 不发真实调用）。
- `dataset/golden/v1/{1826,1824,1814,1816,1828}.jsonl` 与更新后的 `manifest.json`（每个产品：pack、评判模型 ID、
  评判方式 `codex-session-file-exchange`、题目数、条目数、三态分布、`evidence_not_verified` 数与字段清单、源文件 SHA256、
  prompt 版本与每道题的 SHA256）。
- 1828 的原文目前只在本机 `~/Downloads/shouxian_product/平安安佑福(全能版)重大疾病保险/`，复制到
  `dataset/shouxian_product/` 下与其他产品同样的目录结构，并在 manifest 记录 SHA256。
- PR 描述：校准报告（一致率与不一致明细）；5 个 pack 的 per-pack 结果表与 gate 结论；每个 pack 列出漏抽最多的 10 个字段；
  每个产品的题目数、评委会话数及所用模型与推理档位。题目与答案文件留在 `run_root`，**不入库**。

## 5. 验收

Claude 提供的 `harness/tests/eval/test_judge_annotation.py` 与 `harness/tests/eval/test_judge_files.py`（受保护，当前 RED）
全部通过；另外：

- `uv run pytest tests/eval`、`uv run ruff check .`、`uv run mypy src tests`（在 `harness/`）通过；
- 仓库根架构守卫通过；CI 全绿；
- 校准达标（§3.4），或按 §3.4 停下并在 PR 中说明。

## 6. 评判工作量

- **评判模型**：GPT-6.1 sol，在用户自己开的 Codex 会话里答题；与生产编译模型 DeepSeek v4 flash 不同族。**无 API 调用、无密钥。**
- **题目数**：`batch_size` 默认 25，每款产品约 2–3 道题，6 款产品约 12–15 道；`max_calls` 每款产品 ≤ 3，总上限 **20 道**
  （含一次 prompt 修订后的校准重跑）。
- **数据量**：6 款产品原文合计约 35 万字（1814 约 11 万字，含费率表）。每道题都带该产品全部原文，单个题目文件约 3–11 万字；
  评委按需 grep 查找，不必整篇读入。
- **外发内容**：产品条款、说明书、费率表原文进入用户的 Codex 会话（开发阶段用户已同意外发评测）。

## 7. 改动范围

- 允许新增：`eval/pdf_text.py`、`eval/judge.py`、`eval/judge_files.py`、`eval/annotate.py`、对应测试、
  `dataset/golden/v1/` 下 5 个新 jsonl、`dataset/shouxian_product/平安安佑福(全能版)重大疾病保险/`。
- 允许修改：`eval/catalog.py`、`eval/report.py`、`dataset/golden/v1/manifest.json`。
- 不得修改：`harness/tests/eval/test_judge_annotation.py`、`harness/tests/eval/test_judge_files.py`、
  `harness/tests/eval/test_golden_evaluation.py`、旧目录、蓝图、
  `docs/design/`、`tests/architecture/`、`contracts/`。不新增依赖。

## 8. 非目标

- 不与 V5 对比（V5 的结果文件与业务反馈表还未提供）。
- 不评证据页码与引文是否与候选一致（只回验 Golden 自己的证据）。
- 不接 CI 质量门；不重新编译产品；不调用生产编译模型。
