# S2b · 评判模型生成多险种 Golden，并给出 G3 的第一份有效质量数字

> 状态：待用户批准 ｜ 作者：Claude Code ｜ 依据：技术蓝图 1001 §7.7、§11（S2）
> 分支：`slice/s2b`（基于 `slice/s2a`；S2a 合并后变基到 `main`） ｜ 开工方式：**等确认再开工**
> 真实模型调用：**需要**，预算见 §6，开工前用户须确认评判模型与密钥。

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

- **盲评**：评判模型只看产品原文与字段定义，绝不看 epoch9 或任何候选结果。
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
| `eval/judge.py` | `JudgeRequest(system, user)`、`JudgeClient` 协议（`complete(request) -> str`、`model_id`）、`JudgeAnnotator`、`AnnotationResult`、`JudgeProtocolError`、`JudgeBudgetExceeded`、`calibrate()` |
| `eval/judge_http.py` | OpenAI 兼容 chat-completions 客户端（httpx，已是依赖）；模型、地址、密钥从环境变量读取；仅对网络/5xx 错误重试 1 次 |
| `eval/catalog.py`（扩展） | `field_definition(pack_id, field_key)`：返回 short_title、description、source_guidance、value_spec、formation_method；`source_extractable_fields(pack_id)` |
| `eval/annotate.py` | CLI：对一个产品跑评判、回验、写 `dataset/golden/v1/<product_id>.jsonl`；原始请求/响应写到仓库外目录 |
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

### 3.2 运行顺序

1. **校准**：对 596 的 40 个映射字段中属"原文抽取"的部分跑评判，`calibrate` 对照 `dataset/golden/v1/596.jsonl`。
   达标条件（初值，可在 PR 中提出调整）：三态一致率 ≥ 90%，双方都是 present 的字段值一致率 ≥ 80%，且
   `evidence_not_verified` ≤ 10%。不达标：**停下**，在 PR 中贴出不一致明细，允许修改一次 prompt 后重跑一次校准；仍不达标则
   不生成 5 款产品的 Golden，交回 Claude 与用户决定。
2. **生成**：校准达标后，用**同一份 prompt 与模型**为 5 款产品生成 Golden。
3. **评分**：用 report CLI 对 epoch9 candidate 评分，覆盖 5 个 pack（596 也一并报告）。

## 4. 交付物

- 上述模块与测试（验收测试之外的单测自行补充，测试中只用假评判客户端，CI 不发真实调用）。
- `dataset/golden/v1/{1826,1824,1814,1816,1828}.jsonl` 与更新后的 `manifest.json`（每个产品：pack、评判模型 ID、
  调用次数、条目数、三态分布、`evidence_not_verified` 数与字段清单、源文件 SHA256、prompt 的 SHA256）。
- 1828 的原文目前只在本机 `~/Downloads/shouxian_product/平安安佑福(全能版)重大疾病保险/`，复制到
  `dataset/shouxian_product/` 下与其他产品同样的目录结构，并在 manifest 记录 SHA256。
- PR 描述：校准报告（一致率与不一致明细）；5 个 pack 的 per-pack 结果表与 gate 结论；每个 pack 列出漏抽最多的 10 个字段；
  实际调用次数、输入/输出 token 数（若接口返回）。原始请求与响应**不入库**。

## 5. 验收

Claude 提供的 `harness/tests/eval/test_judge_annotation.py`（受保护，当前 RED）全部通过；另外：

- `uv run pytest tests/eval`、`uv run ruff check .`、`uv run mypy src tests`（在 `harness/`）通过；
- 仓库根架构守卫通过；CI 全绿；
- 校准达标（§3.2），或按 §3.2 停下并在 PR 中说明。

## 6. 真实调用预算

- **评判模型**：用户确认（建议 Opus 5.5 或 GPT-6.1 sol；与生产编译模型 DeepSeek v4 flash 不同族）。
- **次数**：校准 ≤ 6 次，5 款产品合计 ≤ 34 次，总上限 **40 次**（含一次 prompt 修订后的重跑）。
- **数据量**：6 款产品原文合计约 35 万字（1814 约 11 万字，含费率表）。每批调用都带上该产品的全部原文，预计总输入约
  250–300 万 token、输出约 20 万 token；实际以接口回执为准，在 PR 中报告。
- **外发内容**：产品条款、说明书、费率表原文（开发阶段用户已同意外发评测）。

## 7. 改动范围

- 允许新增：`eval/pdf_text.py`、`eval/judge.py`、`eval/judge_http.py`、`eval/annotate.py`、对应测试、
  `dataset/golden/v1/` 下 5 个新 jsonl、`dataset/shouxian_product/平安安佑福(全能版)重大疾病保险/`。
- 允许修改：`eval/catalog.py`、`eval/report.py`、`dataset/golden/v1/manifest.json`。
- 不得修改：`harness/tests/eval/test_judge_annotation.py`、`harness/tests/eval/test_golden_evaluation.py`、旧目录、蓝图、
  `docs/design/`、`tests/architecture/`、`contracts/`。不新增依赖。

## 8. 非目标

- 不与 V5 对比（V5 的结果文件与业务反馈表还未提供）。
- 不评证据页码与引文是否与候选一致（只回验 Golden 自己的证据）。
- 不接 CI 质量门；不重新编译产品；不调用生产编译模型。
