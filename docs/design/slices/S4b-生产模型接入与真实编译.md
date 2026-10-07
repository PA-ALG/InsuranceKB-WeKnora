# S4b · 生产模型接入与第一份 DeepSeek 质量数字

> 状态：待用户批准（含真实调用预算与 API 密钥） ｜ 作者：Claude Code ｜ 依据：技术蓝图 1001 §4.2、§7.6、§7.7、§11（S4）；S4a、S2c Spec
> 分支：`slice/s4b`（基于 `main@eb0b2ab6b`） ｜ 工作目录：`.worktrees/s4b` ｜ 开工方式：**写完计划即开工**（第 2 部分的前置条件见 §4）
> 生产编译模型：**DeepSeek v4 flash**（官方 API，OpenAI 兼容）。

## 1. 目标

1. 建 `models/`：按阶段配置的 OpenAI 兼容调用器，满足蓝图 §7.6——输出预算含推理 token、每条调用链只有一个重试 Owner、
   有界退避、成功/失败/超时全部计量、代码里没有模型家族特判、密钥只从环境变量读。它在结构上实现 S4a 的 `CompletionPort`，
   S4a 引擎**不改**。
2. 用 DeepSeek v4 flash 对 S2b 的 4 款产品（1824、1826、1816、1814）**真实编译一次**，用 S2c 的语义评分给出项目第一份
   **生产目标模型**的逐 pack 质量数字，并与 G3 epoch9 的 S2c 数字对照。

蓝图 §11 S4 的另外两项——"PageText 由 ParseArtifact 重建"与"一款真实产品上传→编译→发布→回跳"——**不在本片**，归 S4c（§9）。
本片的页文本取自与 Golden **同一份冻结 PDF 快照**（`eval/pdf_text`），这样两边比较的只是抽取能力；S4c 把页文本换成 ParseArtifact 后需要重测。

## 2. 现状

- S4a：`SchemaFieldsCompiler(completion, batch_size=25, max_calls=10)`；每批都带**全部**页文本；引文回验失败的字段整条丢弃（评分时记为漏抽）。
  `to_candidate(output, display_name=..., schema_pack_id=...)` 产出 `predictions_from_candidate` 能读的候选形状。
- 旧 `compiler/llm.py::OpenAICompatClient`（async，S7 删除）记录了已踩的坑，本片移植为同步实现：
  `max_tokens` 不足时推理会吃光预算、正文为空；`finish_reason == "length"` 是截断；只取 `message.content`，忽略 `reasoning_content`；
  `httpx` 必须 `trust_env=False`（本机代理环境变量曾让请求全部失败）。
- 4 款原文长度（S2b 题目实测，含字段定义）：1814 ≈ 12.4 万字符、1816 ≈ 7.6 万、1826 ≈ 5.2 万、1824 ≈ 3.4 万。
  1814 可能超过模型上下文，因此需要 §3.2 的 `InputTooLarge`。
- 守卫：`models/` 属于 core 目录（G2：不得出现险种名、field_key；G1：不得 import `compilers/` 与旧目录）；`eval/` 可以 import `compilers/` 与 `models/`。

## 3. 设计

### 3.1 `models/` 文件

| 文件 | 职责 |
|---|---|
| `models/config.py` | `StageModelConfig`、`load_stage_config` |
| `models/stages.json` | 版本化的阶段配置（不含密钥） |
| `models/ledger.py` | `CallRecord`、`CallLedger`（调用计量与发送上限） |
| `models/openai_compatible.py` | `OpenAICompatibleCompletion` |
| `models/errors.py` | 错误类型 |

实现方可以调整文件划分，但下列公开名必须能从 `insurance_harness.models` 直接 import。

### 3.2 冻结接口（验收测试 `harness/tests/models/test_stage_completion.py` 按此断言）

```python
class StageModelConfig(BaseModel):          # frozen, extra="forbid"
    stage: NonBlank
    provider: NonBlank
    base_url: str                           # 必须 https://
    model: NonBlank
    api_key_env: str                        # 环境变量名，匹配 ^[A-Z][A-Z0-9_]*$；配置里永远没有密钥本身
    max_tokens: int                         # > 0，输出预算，含推理 token
    temperature: float = 0.0                # 0 ≤ t ≤ 2
    timeout_s: float = 180.0                # > 0
    max_attempts: int = 3                   # 1–5，含首次
    max_input_chars: int | None = None      # > 0；len(system) + len(user) 超过即拒绝
    thinking: Literal["enabled", "disabled"] | None = None
    response_format: Literal["json_object"] | None = None
    policy_version: NonBlank                # 配置版本，写进每条 CallRecord

def load_stage_config(path: Path, stage: str) -> StageModelConfig
    # 文件形状 {"stages": [ {...}, ... ]}；stage 不存在、重名、字段非法 → ModelConfigError

class CallRecord(BaseModel):                # frozen, extra="forbid"
    stage: str
    model: str
    policy_version: str
    request_sha256: str                     # 发送的 JSON 字节的 SHA256
    attempt: int                            # 从 1 开始
    outcome: Literal["ok", "truncated", "http_error", "rate_limited", "server_error",
                     "timeout", "transport_error", "input_too_large", "budget_exceeded"]
    status_code: int | None = None
    latency_ms: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None     # usage.completion_tokens_details.reasoning_tokens
    finish_reason: str | None = None

class CallLedger:
    def __init__(self, *, max_sent: int | None = None) -> None: ...
    @property
    def records(self) -> tuple[CallRecord, ...]: ...
    @property
    def sent(self) -> int: ...              # 真正发到网络的尝试数（不含 input_too_large / budget_exceeded）

class OpenAICompatibleCompletion:           # 结构上实现 S4a 的 CompletionPort
    def __init__(self, config: StageModelConfig, *, environ: Mapping[str, str] | None = None,
                 ledger: CallLedger | None = None, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None: ...
    @property
    def model(self) -> str: ...             # = config.model
    @property
    def ledger(self) -> CallLedger: ...
    def complete(self, *, system: str, user: str) -> str: ...
    def close(self) -> None: ...

# errors：ModelCallError 为基类；ModelConfigError、TruncatedCompletion、InputTooLarge、
#        ModelHTTPError、ModelUnavailable、ModelBudgetExceeded 均继承它
```

行为规则：

1. **构造**：从 `environ`（默认 `os.environ`）读 `config.api_key_env`；缺失或空白 → `ModelConfigError`，不发请求。
2. **请求**：`POST {base_url}/chat/completions`，JSON 含 `model`、`messages`（system、user 各一条）、`max_tokens`、`temperature`；
   `thinking` 非空时加 `{"thinking": {"type": ...}}`；`response_format` 非空时加 `{"response_format": {"type": "json_object"}}`。
   请求头 `Authorization: Bearer <key>`。同一输入每次产生相同字节（`request_sha256` 稳定）。`httpx` 客户端 `trust_env=False`。
3. **输入上限**：`max_input_chars` 已设且超出 → 记一条 `input_too_large`，抛 `InputTooLarge`，**不发送**。
4. **成功响应**：返回 `choices[0].message.content`，忽略 `reasoning_content`。`finish_reason == "length"` 或正文为空白 →
   记 `truncated`，抛 `TruncatedCompletion`，**不重试**（同样的预算重试只会再次截断；要改配置）。
5. **重试只在这里**：只对 429、5xx、超时、传输错误重试，总尝试数 ≤ `max_attempts`；等待时间取 `Retry-After` 秒数（上限 60），
   没有则 `2 ** (attempt - 1)` 秒（上限 30），经注入的 `sleep` 执行。用尽后抛 `ModelUnavailable`。其他 4xx 立即抛 `ModelHTTPError`，不重试。
   超时后重试可能导致供应商重复计费（Chat Completions 没有幂等键可对账），因此每次尝试都记账，PR 里如实汇总。
6. **发送上限**：每次尝试前检查 `ledger.max_sent`，已达上限 → 记 `budget_exceeded`，抛 `ModelBudgetExceeded`，不发送。
   同一个 `CallLedger` 可在多个调用器之间共享，作为整次运行的总上限。
7. **计量**：每次尝试（无论成败）恰好追加一条 `CallRecord`；200 响应带 `usage` 时记录 token 数。
8. **不泄密**：密钥、prompt 正文、响应正文都不得出现在异常信息、`CallRecord` 或日志里（响应可能回显材料）；异常信息只含 stage、model、状态码与 outcome。
9. **无家族特判**：代码不得按 `model` 或 `provider` 字符串分支；差异全部写在配置里。`models/` 的 `.py` 文件里不出现任何供应商名（含注释与文档字符串），验收测试会检查；踩坑来源写在本 Spec 与 PR 里。

### 3.3 `models/stages.json`

先只有一个阶段 `schema_fields`：`provider` = `deepseek`，`base_url` = `https://api.deepseek.com`，`model` = DeepSeek v4 flash 的官方模型名，
`api_key_env` = `HARNESS_SCHEMA_FIELDS_API_KEY`，`policy_version` = `2026-10-07.1`。`max_tokens`、`max_input_chars`、`thinking` 按 DeepSeek
**官方文档**取值，PR 里写明文档地址与查阅日期；`max_input_chars` 按上下文窗口保守折算（中文按 1 字符 ≈ 1 token 估算，留出输出预算）。

### 3.4 真实编译 CLI：`python -m insurance_harness.eval.compile_run`

```text
--products 1824 1826 1816 1814 --stage schema_fields --stage-config <stages.json> --run-root R
[--batch-size 25] [--max-sent 20]
```

- `R` 必须在任何 git 仓库之外。全部产品共享一个 `CallLedger(max_sent=--max-sent)`。
- 每款产品：pack 取 `dataset/golden/v1/manifest.json` 的 `products[<id>].pack_id`；字段 = `pack_definitions(catalog, pack)`（只取可原文抽取字段，
  与 Golden 的字段集合一致）；页文本 = 该产品 `dataset/shouxian_product/<目录>/*.pdf` 经 `eval/pdf_text.read_pdf`；
  `SchemaFieldsCompiler(..., max_calls=ceil(字段数 / batch_size))`。
- **按参数顺序逐款编译**（由小到大），第一款出现 `TruncatedCompletion`、`InputTooLarge`、`ModelHTTPError` 就**停下**，后面的不发。
- 产物：每款成功后原子写 `R/<id>/output.json`（`CompileOutput`）；每次尝试追加到 `R/ledger.jsonl`。重跑时已有 `output.json` 的产品**复用、不重编**，
  复用数单独统计。全部完成后写 `R/candidate.json`（各款 `to_candidate` 合并：bindings 与 fields 依次拼接）与 `R/product-map.json`
  （display_name → 产品号）；这两个文件已存在则退出码 2，不覆盖。
- 产品源目录与 pack 的解析：把 `eval/annotate.py` 里的 `_sources` / `_pages` / `_pack` 提成一个新模块（如 `eval/product_sources.py`）的公开函数，
  `annotate.py` 改为调用它们，**不留重复实现**。这一步必须在含 S2c 的 `main` merge 进来之后做（S2c 也改 `annotate.py`）。
- 退出码：全部完成 0；按规则停下或输入非法 2。标准输出打印每款的调用数、复用与否、token 汇总。

## 4. 运行顺序

**第 1 部分（现在即可开工，不发真实调用）**

1. `models/` 与单测（只用 `httpx.MockTransport` 与假 `sleep`）。验收测试转绿、门禁通过后推送，在 Issue 里报告。

**第 2 部分（前置：S2c 已合并；用户已在 Codex 环境设置 `HARNESS_SCHEMA_FIELDS_API_KEY`）**

2. 把最新 `main` merge 进本分支；做 §3.4 的源解析提取与 `compile_run`，含实现方测试（假 `CompletionPort` / MockTransport，不发真实调用）。
3. 真实编译：`--products 1824 1826 1816 1814`，run root 建议 `~/compile-runs/s4b-v1`。停下条件见 §3.4。若 1824 就截断，
   可在官方文档允许的范围内调高 `max_tokens` **一次**（改 `stages.json` 并升 `policy_version`），仍失败则停下交回 Claude。
4. 评分：用 S2c 的 `semantic_run`（Golden = 4 款文件，candidate / product map = 上一步产物，run root 建议 `~/judge-runs/s4b-v1`）。
   `prepare` 后在 Issue 贴题数并 @ 用户；**用户**新开 1 个 GPT-6 Astra / xhigh Codex 会话答题；无裁定 `score` 后贴 `l2_raw` 与错误清单；
   **Claude** 写 `rulings.json`（规则同 S2c §2.3、§4 第 5 步）；最终 `score`。
5. 开 PR。

## 5. 交付物

- `models/` 全部文件与单测；`eval/compile_run.py`、`eval/product_sources.py`（或同等）及测试；`annotate.py` 改为调用公开函数。
- PR 描述：
  - 逐 pack 结果表：DeepSeek v4 flash 与 G3 epoch9（S2c 数字）并列，P / R / 幻觉 / 缺内容 / 说错 / 放错字段 / 门槛；
  - 调用汇总：发送数、重试数、复用数、prompt / completion / reasoning token 合计、总耗时，按供应商公开价格估算的费用；
  - 引文回验被丢弃的字段数（逐款）；停下或失败的情况如实写出；
  - `stages.json` 的取值依据（文档地址与日期）；
  - L3 裁定全文、评委会话数与模型档位。
  原始输出、账本与报告留在 run root，**不入库**。

## 6. 验收

- Claude 提供的 `harness/tests/models/test_stage_completion.py`（受保护，当前 RED）全部通过；
- `harness/` 下 `pytest tests/models tests/eval tests/compilers tests/evidence`、`ruff check .`、`mypy src tests` 通过；
- 仓库根架构守卫通过（`models/` 无 G1/G2 违例），基线不回升；CI 全绿；
- 已把最新 `main` merge 进本分支（不 rebase）。

## 7. 改动范围

- 允许新增：`harness/src/insurance_harness/models/`、`eval/compile_run.py`、`eval/product_sources.py`（或同等新模块）、`harness/tests/models/`、对应测试。
- 允许修改：`eval/annotate.py`（仅把源解析改为调用新公开函数）。
- **受保护**：`harness/tests/models/test_stage_completion.py`、`harness/tests/eval/` 下全部受保护验收、S4a 的 `test_engine_contract.py`、
  `docs/design/`、蓝图、`tests/architecture/`、`contracts/`。
- 不得修改：`compilers/`、`evidence/`、`dataset/golden/`、旧目录（含旧 `compiler/llm.py`，它在 S7 删除）。不新增依赖（`httpx` 已有）。

## 8. 真实调用预算

- 模型：DeepSeek v4 flash（官方 API），阶段 `schema_fields`。
- 场景：4 款产品各编译一次。预计发送 **11 次**（1824 = 3、1826 = 3、1816 = 3、1814 = 2，按每批 25 个字段计）；
  **发送上限 20 次**（含重试与一次 `max_tokens` 调整后的重跑），由 `--max-sent 20` 强制执行。
- 数据量：每次发送都带该产品全部原文，输入合计约 70 万字符；外发内容为产品条款、说明书、费率表（开发阶段用户已同意外发）。
- 密钥：用户在运行 Codex 的环境里设置 `HARNESS_SCHEMA_FIELDS_API_KEY`；**密钥不进入仓库、日志、PR 或 Issue**。
- 评分：GPT-6 Astra（xhigh），用户新开 1 个 Codex 会话，预计 4 道题、上限 8 道；无 API。
- 无构建、部署、数据库迁移。

## 9. 非目标（S4c 及以后）

- PageText 由 WeKnora ParseArtifact 重建；上传→编译→产出 CandidateBundle→平台预览/上线→字段页→PDF 回跳的端到端纵切（S4c）。
- 页面召回与分片（1814 若超出上下文，由后续切片按 S4a `extraction_profiles` 的召回提示实现，本片只如实报告）。
- 任务缓存与恢复的通用 CompileJob（S5）；Gemini 等其他供应商的配置（只改配置即可，本片不加）。
- 不与 V5 对比（V5 结果文件未提供）。
