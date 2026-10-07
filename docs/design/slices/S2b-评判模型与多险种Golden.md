# S2b · 评判模型生成多险种 Golden，并给出 G3 的第一份有效质量数字

> 状态：待用户批准 ｜ 作者：Claude Code ｜ 依据：技术蓝图 1001 §7.7、§11（S2）
> 分支：`slice/s2b`（S2a 合并后同步到 `main`） ｜ 开工方式：**等确认再开工**
> 评判模型：**GPT-6 Astra，推理档位 xhigh**（用户 2026-10-03 改定，原定 GPT-6.1 sol），在**独立的 Codex 会话**里担任评委，与代码用文件交换题目和答案；
> 不走 API，不需要密钥。工作量见 §6。

## 1. 目标

S2a 的尺子能用，但唯一有 Golden 的产品 596 在 epoch9 里没被重新抽取（67 个字段只有 2 个有值），测出的 0% 不代表
G3 的抽取能力。本片用离线评判模型，为 G3 实际抽取过的 4 款产品生成 Golden，覆盖 4 个险种 pack，然后给出
G3 在这 4 款上的逐 pack、逐字段 precision / recall——这是项目第一份能说明问题的质量数字。

| 产品 | 名称 | pack | epoch9 有值字段 |
|---|---|---|---|
| 1826 | 平安守护百分百（2026）两全保险 | `schemapack_endowment_insurance` | 40/79 |
| 1824 | 平安盛世金越（尊享版26）终身寿险 | `schemapack_whole_life_insurance` | 39/75 |
| 1814 | 平安附加（2026）意外伤害保险 | `schemapack_accident_insurance` | 38/62 |
| 1816 | 平安附加（2026）失能收入损失保险 | `schemapack_disability_income_insurance` | 49/76 |

**1828（重疾险）暂缓**（用户 2026-10-03 决定）：仓库里另外 13 款都有完整的 `product_meta.json`，1828 只有三份 PDF，
缺备案字段（`versionNo` 等）会让 `test_i8_real_dataset_bootstrap_full_and_zero_claims` 失败；备案字段不能猜。
拿到同源主数据快照后单独补一片，重疾险 pack 届时再出数。

## 2. 原则

- **盲评**：评判模型只看产品原文与字段定义，绝不看 epoch9 或任何候选结果。评委会话只打开题目目录（在任何 git 仓库之外），
  不打开本仓库、`dataset/golden/`、epoch9 或任何抽取输出。实现者会话写代码时看过现有 Golden 与 epoch9，**不能兼任评委**。
- **只评可从文档得出的字段**：Catalog 中 `formation_method` 含"原文抽取"的字段才进 Golden；纯"外部映射""规则衍生""LLM生成"
  的字段不进（它们不来自 PDF）。评分时这些字段计为 unscored。每个 pack 约 38–55 个字段。
- **证据确定性回验**：评判模型给出的每条引文必须在它声明的页面原文里找到（归一化后子串匹配）；找不到就丢弃该引文，
  present / absent 若没有一条通过回验，整个字段记为 `evidence_not_verified` 并排除出 Golden，不改成 unknown。
- **先校准再使用**：先在 596 上对照已批准的 40 条 Golden 校准，达标才生成 4 款产品的 Golden（§4）。
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
- **`value` 的形态（prompt v2 起，2026-10-04 修订）**：`value` 是该字段**可直接展示给人的最简答案**，不是原文摘抄。
  例：`一年`、`30日`、`计划一1万元；计划二0元`。细则、条件、例外放 `components`（每个必要要素一条，`accepted` 列等价措辞），
  逐字原文放 `evidence`。禁止把整段条款粘进 `value`。系统提示词必须写明这条，并给出正反例各一个。
  理由与最终取值口径见 **§8**（2026-10-05 用户裁决）：`value` 短答案逐字取自原文、长答案裁剪但保留全部核心事实、
  允许不改变语义的适度润色；比较按语义等价而非整值相等。
- 以下一律 `JudgeProtocolError`：无法解析；缺少请求的字段；出现未请求或重复的字段；三态与值、证据的形状不符。
- `calibrate(judged, reference)`：只比较两边都有的字段；三态一致计 `state_agreement`；双方 present 时用 S2a 的
  `compare_value`（参考 Golden 的值与组成要素）判定 `present_value_agreement`。
- 两个 state 不一致的字段（`premium_grace_period`、`product_bundle_rules`）在该报告中逐条列出，供人工判断。
- 原 `reference_atom_coverage` 诊断已**删除**（切句后仍要求整句逐字命中，粒度不对），由 §8.2 的语义等价层取代。
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
- **`annotate ingest --product <id> --run-root <dir> --judge-model gpt-6-astra [--calibrate]`**：从 `run.json` 读字段与
  `batch_size`，重读 PDF 重建题目，用 `FileJudgeClient` 回放；`unconsumed()` 非空即失败。`--judge-model` 必填，原样写入
  `judged_by="model:<id>"` 与 manifest。`--calibrate` 只允许 596，只输出 `CalibrationReport`，**不写** `596.jsonl`。
- 哈希只能证明题目没变，证明不了答题的是哪个模型：开评委会话的人必须选 GPT-6 Astra、推理档位 xhigh，596 与 4 款产品全部用同一模型与档位，PR 里写明每个会话的模型与推理档位。

### 3.3 评委会话规则（prepare 写进每个产品目录的 `AGENTS.md`）

1. 你是保险条款的离线评委。只读当前目录下的文件；不打开当前目录以外的任何路径，不联网，不运行抽取或比对程序。
2. 逐个处理 `requests/` 里的题目：`system_lines` 是规则，`user_lines` 是题目。把答案写成严格 JSON，存为
   `responses/` 下的同名文件。已有答案的题目跳过（会话中断后可以新开会话接着做）。
3. 可以用 grep 等只读命令查找原文和核对引文；不得用脚本批量生成答案。
4. 引文必须从所在页原文**逐字复制**，并核对它确实在你声明的 `[page N]` 之下；原文没有依据就答 `unknown`，不要猜。
5. 不修改 `requests/`、`run.json` 与本文件。

### 3.4 每款产品一道题

题目文件是**自包含**的：每道题都带该产品的全部页面原文（§3.1），因此同一份原文在多个批次里会重复出现，
既浪费评委会话的上下文，也没有必要。`--batch-size` 取**大于该 pack 原文抽取字段数**（当前最大 56，取 60 即可），
使每款产品只产生**一道题**：评委每款产品只开一个会话、只读一个文件，`max_calls` 也远够用。

```sh
uv run python -m insurance_harness.eval.annotate prepare --product 1824 \
  --run-root "$HOME/judge-runs/s2b" --batch-size 60
```

不再改题目文件之间的引用关系：题目自包含是受保护验收 `test_judge_files.py` 钉住的协议，
改成共享原文会引入"哪份原文、被谁引用"的额外校验，得不偿失。

596 已有的 2 道题**保持现状**，不为去重重出——作废一次校准机会的代价高于重复一次原文。其余四款按本节出题。

### 3.5 运行顺序

1. **校准**：`prepare` 596 → 在 `<run_root>/596` 开评委会话答题 → `ingest --calibrate`，对照 `dataset/golden/v1/596.jsonl`。
   达标条件见 **§8.1**：三态一致率 ≥ 90%、**语义等价率 ≥ 80%（§8.1 的 L1+L2 三层口径）**、`contradicted` 必须为 0、
   `evidence_not_verified` ≤ 10%。**不再使用"值整串一致率 ≥ 80%"**——596 的两次校准证明它对 legacy 参考不可达
   （v1 详写 0/19、v2 简写 1/19），度量的不是事实对错。不达标：**停下**，在 PR 中贴出不一致与矛盾明细，交回 Claude 与用户。
   prompt 修订额度已在 2026-10-04 用尽（v1 → v2）；本次口径调整是用户裁决的**度量口径变更**，按 §8.3 升 `PROMPT_VERSION`
   到 `"3"` 并**新开 run root**，旧的 v1/v2 题目与答卷全部保留。
2. **生成**：校准达标后才 `prepare` 4 款产品（同一 prompt 版本），**每款产品单开一个评委会话**，答完后逐个 `ingest`。
   先校准再出题，是为了 prompt 一旦要改，不会白答 4 款产品的题。
3. **评分**：用 report CLI 对 epoch9 candidate 评分，覆盖 4 个 pack（596 也一并报告）。

## 4. 交付物

- 上述模块与测试（验收测试之外的单测自行补充，测试中只用假评判客户端，CI 不发真实调用）。
- `dataset/golden/v1/{1826,1824,1814,1816}.jsonl` 与更新后的 `manifest.json`（每个产品：pack、评判模型 ID、
  评判方式 `codex-session-file-exchange`、题目数、条目数、三态分布、`evidence_not_verified` 数与字段清单、源文件 SHA256、
  prompt 版本与每道题的 SHA256）。
- 撤回已加入的 1828：删除 `dataset/shouxian_product/平安安佑福(全能版)重大疾病保险/` 与 manifest 里的 1828 条目，
  相应调整实现提交自己加的 `test_scheduled_products_have_declared_pack_inputs`。
- PR 描述：校准报告（一致率与不一致明细）；4 个 pack 的 per-pack 结果表与 gate 结论；每个 pack 列出漏抽最多的 10 个字段；
  每个产品的题目数、评委会话数及所用模型与推理档位。题目与答案文件留在 `run_root`，**不入库**。

## 5. 验收

Claude 提供的 `harness/tests/eval/test_judge_annotation.py` 与 `harness/tests/eval/test_judge_files.py`（受保护，当前 RED）
全部通过；另外：

- `uv run pytest tests/eval`、`uv run ruff check .`、`uv run mypy src tests`（在 `harness/`）通过；
- 仓库根架构守卫通过；CI 全绿；
- 校准达标（§3.5），或按 §3.5 停下并在 PR 中说明。

## 6. 评判工作量

- **评判模型**：GPT-6 Astra（xhigh），在用户自己开的 Codex 会话里答题；与生产编译模型 DeepSeek v4 flash 不同族。**无 API 调用、无密钥。**
- **题目数**：`batch_size` 默认 25，按 §3.4 出题时取 60，每款产品 1 道题（596 已有 2 道），5 款产品共约 6 道；`max_calls` 每款产品 ≤ 3，总上限 **20 道**
  （含一次 prompt 修订后的校准重跑）。
- **数据量**：596 与 4 款产品，单款原文 3–11 万字（1814 约 11 万字，含费率表）。每道题都带该产品全部原文，单个题目文件约 3–11 万字；
  评委按需 grep 查找，不必整篇读入。
- **外发内容**：产品条款、说明书、费率表原文进入用户的 Codex 会话（开发阶段用户已同意外发评测）。

## 7. 改动范围

- 允许新增：`eval/pdf_text.py`、`eval/judge.py`、`eval/judge_files.py`、`eval/annotate.py`、`eval/equivalence.py`、
  对应测试、`dataset/golden/v1/` 下 4 个新 jsonl。删除：`dataset/shouxian_product/平安安佑福(全能版)重大疾病保险/`（见 §4）。
- 允许修改：`eval/catalog.py`、`eval/report.py`、`dataset/golden/v1/manifest.json`。
- **受保护（由 Claude 写，实现方不得改）**：`harness/tests/eval/test_equivalence.py`。
  它钉住 §8.2–§8.5 的公开 API 与 L3 裁定口径，当前为 RED；实现完成即变绿，不得改动其中的断言。
- 不得修改：`harness/tests/eval/test_judge_annotation.py`、`harness/tests/eval/test_judge_files.py`、
  `harness/tests/eval/test_golden_evaluation.py`、`docs/design/`（Claude 可改）、旧目录、蓝图、
  `tests/architecture/`、`contracts/`。不新增依赖。

## 8. 取值与比较的口径（2026-10-05 用户裁决，取代 §3.1 的整值比较）

596 两次校准证明"整值相等"这把尺子是坏的：legacy 参考金标 `gs-s0q-596-v1` 的 40 条**全无 components**、
值是人工摘要（中位 58 字），比较器在参考无 components 时退化为整串相等；v1（详写原文）得 0/19、v2（简写）
得 5.3%（1/19，仅 `coverage_period` 的"一年"=="一年"）。**两种相反风格被同一门槛判死**，说明度量的是
"有没有写出和人一样的摘要"，不是"事实对不对"。我加的 `reference_atom_coverage` 也无效：它切句后仍要求整句
逐字命中，粒度只从整段降到整句。

用户 2026-10-05 裁决：**按语义等价比较，不要求一模一样；细节由实现方定。**

### 8.1 比较分三层，各司其职

| 层 | 判据 | 谁执行 | 结果 |
|---|---|---|---|
| L1 确定性 | 归一化相等、数值相等、日期相等、枚举同义（`eval/normalize.py` 的 `values_equal`） | 代码 | equal / not-equal |
| L2 语义等价 | 参考列出的事实是否被评委的 `value` + `components[].accepted` 覆盖，措辞不同不算错 | 离线上限模型（同一文件交换机制） | equivalent / contradicted / insufficient |
| L3 人工 | L2 判 contradicted 或 insufficient 的明细 | 人工抽检，落地方式见 §8.5 | 最终裁定 |

- **门槛（取代 §3.5 的值一致率 ≥80%）**：`compared` ≥ 1 时，
  **`equivalent / compared` ≥ 80%**，且 **`contradicted` 必须为 0**。
  "矛盾"是事实错误（如参考"30日"、评委"90日"），不是措辞差异，**一条都不允许**。
- `insufficient`（参考或评委信息不足以判定）计入分母、不计入分子，并在报告中单独列出。
- 报告保留 L1 的原始结果作为 `literal_agreement` 诊断项，**不进门槛**——用来观察措辞分布，不参与裁定。
- **删除 `reference_atom_coverage`**：它不是正确的粒度，由 L2 取代。

### 8.2 L2 的实现：等价问题走同一套文件交换

复用 §3.2 的 `requests/` ↔ `responses/` 机制，不新造通道：

```python
# eval/equivalence.py
EQUIVALENCE_PROMPT_VERSION = "2"             # 新题用当前版本；旧 run 用自己 run.json 里记的版本

class EquivalenceQuestion(BaseModel):        # frozen, extra="forbid"
    field_key: str
    reference: str                           # 参考 value 原文
    judged: str | None                       # 评委 value
    components: list[ValueComponent] = []    # 评委 components

class EquivalenceReport(BaseModel):
    compared: int = 0
    equivalent: int = 0
    contradicted: dict[str, str] = {}        # field_key -> 理由（L3 之后的最终分桶）
    insufficient: list[str] = []
    insufficient_reasons: dict[str, str] = {}
    rate: float | None = None                # equivalent / compared
    adjudicated: dict[str, str] = {}         # L3 记录：field_key -> "contradicted->equivalent"
    raw_contradicted: dict[str, str] = {}    # L2 原始判定，诊断用，不进门槛
    raw_insufficient: list[str] = []

def build_equivalence_requests(
    questions: Sequence[EquivalenceQuestion], *, product_id: str,
    batch_size: int = 25, prompt_version: str = EQUIVALENCE_PROMPT_VERSION,
) -> list[JudgeRequest]: ...

def compare_equivalence(
    client: JudgeClient, questions: Sequence[EquivalenceQuestion], *, max_calls: int,
    batch_size: int = 25, prompt_version: str = EQUIVALENCE_PROMPT_VERSION,
) -> EquivalenceReport: ...

def apply_adjudications(
    report: EquivalenceReport, adjudications: Sequence[Adjudication],
) -> EquivalenceReport: ...
```

- **system 文本按版本冻结**：模块内维护一张版本→完整 system 文本的冻结表（私有实现细节，
  测试只钉行为、不访问私有名），`build_equivalence_requests` 按 `prompt_version` 取用。
  `prompt_version` 不在表内即 `ValueError`（fail closed）。v1 文本**原样保留**，不得改写——
  改一个字节就会让已答的 596 卷子对不上 sha。这样改 prompt 不会让旧 run 失效：
  `prepare`/`ingest` 读回该 run 目录 `run.json` 里记的版本，再用同一文本重建题目。
- **`Adjudication`**（L3 输入，§8.5）：`field_key`、`from`（`contradicted`/`insufficient`）、
  `to`（`equivalent`/`insufficient`）、`reason`、`by`、`on`；全部非空，`extra="forbid"`。
  JSON 里字段名就是 `from` / `to`（Python 侧用 `from_verdict` / `to_verdict` 加 `alias`，或允许 `from` 作别名）。

- 每题只含 `field_key`、参考 `value`、评委 `value` 与 `components`；**不含原文、不含页码**——L2 判的是
  "两句说法是否同义"，不是"是否有原文依据"（后者已由 §3.1 的引文回验负责）。
- 输出严格 JSON：`{"fields":[{"field_key":..., "verdict":"equivalent|contradicted|insufficient",
  "reason":"一句话理由"}]}`；缺字段、多字段、重复字段、非法 verdict 一律 `JudgeProtocolError`（fail closed）。
- 预算：19 个字段 → 1 道题；`max_calls=2`。**只有 596 校准用它**（见下条）。
- **L2 只用于 596 校准，不用于 4 款产品**（2026-10-06 澄清）：L2 判的是"参考 value 与评委 value 是否同义"，
  而**只有 596 有参考**（legacy `gs-s0q-596-v1`）。4 款产品的 Golden 由评委**新生成**，没有第二份参考可比，
  `ingest` 的非校准分支走 `_save_golden`，不建 reference、不调 L2。**4 款产品的质量数字来自 G3 抽取
  与该 Golden 之间的 `evaluate`（precision/recall，见 `eval/report.py`），与 L2 无关。** 故 §8.4/§8.5 的
  prompt 版本与 L3 裁定均不影响 4 款产品的评分口径。
- **判等不是重新抽原文**：L2 只读参考与评委的两段文字，不打开 PDF。
- **2026-10-07 更正（Claude Code）**：上面"4 款产品的质量数字来自 `evaluate`、与 L2 无关"一条**作废**。它与用户 2026-10-05
  "按语义等价比较"的裁决冲突：`evaluate` 的逐字 component 匹配下，Golden 自身 value 只命中自身 components 21/108，
  PR #142 的 G3 分数（0%–12%）因此不作质量结论。G3 对 4 款 Golden 的有效评分改由
  [S2c](S2c-语义评分.md) 以 L1/L2/L3 给出；本片交付的是评委流程、596 校准与 4 款 Golden。

### 8.3 取值形态（`value` 的写法，prompt v3）

用户口径：**短的用原文；长的做裁剪但不得丢失核心信息；允许在不改变语义的前提下适度润色，便于人阅读。**

- 短答案（时长、金额、比例、枚举、日期等）**逐字取自原文**，如 `15日`、`计划一1万元，计划二0元`。
- 长答案（清单、责任、免责等）**裁剪为要点，保留全部核心事实**：项目数不能少、数值不能丢、条件不能省；
  **禁止**用"等""包括但不限于""详见条款"带过材料已列明的内容。
- 允许适度润色（补主语、调整语序、统一标点）**当且仅当不改变语义**；改变数值、范围、条件、责任方向的
  改写属**禁止**。
- `components` 必须覆盖包括 `value` 主答案在内的**全部必要要素**（每个要素一条，`accepted` 列等价措辞）；
  **不得**只列补充条件而漏掉主答案。
- `evidence` 仍是逐字原文，不受本节影响。
- `PROMPT_VERSION` 升到 `"3"`；**v1、v2 的题目与答卷全部保留**，作为口径演进的证据，不覆盖、不删除。

### 8.4 L2 判定规则（prompt v2，2026-10-06 用户裁决）

596 第一轮等价题（v1）暴露一个系统性偏差：评委把"**评委答比参考更具体**"判成了 `contradicted`。
两处实例（均已回原文核实，见下表）：参考是人工摘要，把原文的限定条件漏掉了；评委答按 §8.3 要求
保留了原文条件（如"**知道**保险事故发生后"、特药的"**按拥有基本医保或公费医疗投保**"），
**逐字与原文一致**。评委却把这种"更精确"读成了"条件不同"。这会在 4 款产品上重复发生，
污染全部数字，所以改 prompt 而不是改分数。

**规则（写入 `_SYSTEM_BY_VERSION["2"]`）**：v2 文本 = v1 文本**逐字保留**，仅**追加**下面两行
（追加位置在 v1 最后一行之后、结尾"只输出严格 JSON"之后另起）。这两行是受保护测试逐字断言的对象，
**必须原样出现在 v2 的 system 文本中**：

```
判定单向：只问参考列出的核心事实是否被评委答案覆盖；评委答额外给出或更精确地给出参考未列的条件，
而参考列出的事实仍成立时判 equivalent，不得判 contradicted。
contradicted 只留给同一事实上的互斥：数值不同、范围不相交、条件互相排斥、责任方向相反。
```

- 判定**单向**：只问"参考列出的核心事实是否被评委的 `value` + `components[].accepted` 覆盖"。
  评委答**额外**给出、或**更精确**地给出参考未列的条件/限定，而参考列出的事实**全部仍成立**时，
  判 `equivalent`，**不得**判 `contradicted`。
- `contradicted` 只留给**同一事实上的互斥**：数值不同（30日 ≠ 90日）、范围不相交、条件互相排斥、
  责任方向相反（赔 ↔ 不赔）。
- `insufficient` 保持不变：参考漏答、或两边信息不足以判定。**参考漏答不算评委的错**，但也不进分子。
- **v1 文本一个字都不许改**：v1 必须仍含 `遗漏不得按措辞不同放过。`，且**不得**含 `不得判 contradicted`。

### 8.5 L3 裁定（人工）的落地与先例

L2 是模型判定，会误判；§8.1 的 L3 是最终裁定。落地方式：

- **裁定文件**：等价 run 根目录下的 `adjudications.json`，形状为
  `{"entries":[{"field_key":..., "from":"contradicted|insufficient", "to":"equivalent|insufficient", "reason":..., "by":"Claude Code", "on":"YYYY-MM-DD"}]}`。
  由 Claude 写入，随 run 目录保存。**不得**修改 `requests/`、`responses/` 或 `run.json`。
- **生效点**：`ingest` 调用 `compare_equivalence` 之后、算 `passed` 之前，读该文件并 `apply_adjudications`。
  每条裁定必须**指向 L2 确实判过该 field_key 且断言与原始判定一致**，否则 `ValueError`（fail closed）。
- **报告口径**：`contradicted` / `insufficient` 是**裁定后**的最终分桶，进门槛；
  L2 原始判定留在 `raw_contradicted` / `raw_insufficient`，同 `literal_agreement` 一样只作诊断，
  **不进门槛**。报告另记 `adjudicated`，让"改过几条"始终可见。
- 裁定必须在报告与 PR 里**逐条给出理由与原文依据**（field_key + 为什么 L2 判错/判对），不写"人工复核通过"。

**先例（596，prompt v1，2026-10-06 裁定）**：

| field_key | L2 原判 | 裁定 | 依据（原文） |
|---|---|---|---|
| `claim_application_deadline_and_documents` | contradicted | equivalent | 条款 5.2"您、被保险人或受益人**知道**保险事故发生后应当在 10 日内通知我们"——评委答与原文逐字一致，参考漏"知道" |
| `reimbursement_rate_rules` | contradicted | equivalent | 条款 1.5.8 / page 19"若您**按被保险人拥有基本医疗保险或公费医疗的情况进行投保**……我们将按 60% 的给付比例给付"——该前置条件是原文的，参考在特药条省略 |

裁定后 596 的等价结果：**equivalent 16 / compared 19 = 84.2% ≥ 80%，contradicted 0 → 通过**
（`insufficient` 3 条维持，见 §8.6）。

### 8.6 596 维持为 insufficient 的 3 条（真缺陷，记入 4 款产品的教训）

以下三条裁定**维持 insufficient**，是评委答的真实遗漏，不是参考的问题：

- `policyholder_rights`：参考列"15 日犹豫期全额退费 / 享受合同保障 / 享受健康管理服务 / 可退保"，
  评委答的是**现金价值计算公式**（属 `surrender_and_cancellation_terms`），**答错了字段**。
- `insured_eligibility`：只答家庭成员定义，**漏掉常规投保年龄**（出生满 28 日至 70 周岁）与 71–100 周岁条件。
- `entry_age_range`：只答"已投保指定产品"一条例外，**漏掉"上一保险期间届满后 60 日内重新投保"另一条**
  （原文 page 2 两条并列）。

> **给 4 款产品的教训**：`insured_eligibility` 与 `entry_age_range` 取材自**同一段"投保范围"原文**，
> 模型把年龄类事实全塞进后者、家庭类塞进前者，两字段各缺一半。这是**字段描述的重叠**，不是模型能力问题；
> 生成前应检查 pack 内字段描述的取材边界是否互斥。此项不改 596 的既有结论，只在 4 款产品上避免重犯。

## 9. 非目标

- 不与 V5 对比（V5 的结果文件与业务反馈表还未提供）。
- 不做 1828 与重疾险 pack（缺主数据快照，见 §1）。
- 不评证据页码与引文是否与候选一致（只回验 Golden 自己的证据）。
- 不接 CI 质量门；不重新编译产品；不调用生产编译模型。
