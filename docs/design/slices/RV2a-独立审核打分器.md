# RV2a · 独立审核打分器：只看字段规则、取值与引文，给每条有内容的 Claim 打分

> 状态：用户已确认开工（2026-10-17："先发布后抽检"排期；审核模型 deepseek-flash 独立调用；unknown 不打分、不阻挡） ｜ 作者：Claude Code
> 依据：蓝图 §6.3（独立审核打分，与编译隔离，不用编译模型自评）、硬边界 8；RV1 Spec
> 分支：`slice/rv2a` ｜ 工作目录：`.worktrees/rv2a` ｜ 实现方：Claude ｜ 审核方：Codex（新模块、真实调用链路、改 RV1 规则）

RV2 拆为三片：
- **RV2a（本片）**：打分器与运行命令（离线可测，本片不发真实调用）；
- **RV2b**：校准工具（Golden → 评委输入、按 pack 求门槛）；
- **RV2c**：真实运行（GPT-6 Astra 评委重判 5 款，deepseek-flash 打分 ≤ 40 次），给出门槛建议。

## 1. 目标

1. **打分器**：对一次编译输出中 `present` 与 `absent_explicitly` 的字段，各给一个 `[0, 1]` 分数，表示"该状态与取值被所给引文完整、准确地支持，并符合字段规则"的可信度。
   - 审核调用只看字段规则、状态、取值与引文，**不看编译上下文**（提示词、选段过程、页文本、示例），不用编译模型的自评。
2. **`unknown` 不打分、不阻挡**（用户 2026-10-17 裁定）：
   - 它不发布事实，错判只影响召回，由 RV4 抽检覆盖；
   - RV1 的分流规则相应修改：`unknown` 的 Claim 不需要分数与门槛。
3. **运行命令**：
   - 按产品批量打分，写出 RV1 格式的分数文件；
   - 预算按运行目录累计并持久化；中断后重跑，已保存的响应不再发送。

## 2. 现状（`main@55a36ea59`）

- `models/`：
  - `stages.json` 只有 `schema_fields` 一个阶段；
  - `OpenAICompatibleCompletion.complete(system=, user=)` 每次尝试先 `ledger.reserve_send()`；
  - `CallLedger(max_sent=)`；
  - 持久化账本 `_DurableLedger` 是 `eval/compile_run.py` 的私有类：`budget.jsonl` 预留、`ledger.jsonl` 记录、服务模型变化即停。
- RV1 `review/routing.py`：每条 Claim 都要分数与门槛；分数文件格式 `{reviewer, reviewed_at, scores}`。
- 字段规则：
  - `compilers/schema_fields/definitions.py`：`short_title`、`description`、`value_spec`、`source_guidance`；
  - `cards.py` 的 `card_payload(definition, examples=False)`：不含示例。示例中有 Golden 产品，审核绝不带示例。
- 真实编译输出（`cards_version` 为空）只能用于校准，不能经 `claims_from` 发布。

## 3. 设计

### 3.1 打分器（`harness/src/insurance_harness/review/scorer.py`，核心目录，通用）

```python
@dataclass(frozen=True)
class ReviewItem:
    logical_key: str
    title: str
    rules: str                 # 字段定义与边界规则（调用方准备的数据文本）
    state: str                 # "present" | "absent_explicitly"
    value: str | None
    quotes: tuple[str, ...]

class Completion(Protocol):
    def complete(self, *, system: str, user: str) -> str: ...

class ReviewOutputError(ValueError): ...   # 带 reason 码，不带输出文本

def review_batches(items: Sequence[ReviewItem], *, max_chars: int) -> list[list[ReviewItem]]
def score_items(items: Sequence[ReviewItem], completion: Completion, *, max_chars: int = 60_000) -> dict[str, float]
```

- **分批**：
  - 按引文字数相加，不超过 `max_chars`；
  - 单条超过上限的单独成批，引文截到上限并加截断标记（宁可低分，不漏发）；
  - 保持输入顺序。
- **请求**：
  - system 提示词通用、不含领域词：逐条判断状态与取值是否被引文完整准确支持、是否符合规则，只依据给出的引文，输出 JSON；
  - user 为 JSON：`{"items": [{"key", "title", "rules", "state", "value", "quotes"}]}`。
- **解析**：
  - 只接受 `{"scores": [{"key": <str>, "score": <0..1 数字>}]}`；
  - 每个 key 恰好出现一次，不能多也不能少；分数为严格数字（布尔与字符串拒绝）；
  - 任何不符 → `ReviewOutputError("REVIEW_OUTPUT_INVALID")`，不重试（重试归 `models/` 的唯一重试 Owner）。
- **结果**：`{logical_key: score}`；空输入返回 `{}`，不发调用。

### 3.2 审核条目（`compilers/schema_fields/review_items.py`）

```python
def logical_key(entity_id: str, field_key: str) -> str            # 与 Claim.logical_key 同一规则，claims.py 改为调用它
def review_items(output: CompileOutput, definitions: Mapping[str, FieldDefinition]) -> list[ReviewItem]
```

- 只取 `present` 与 `absent_explicitly` 的字段，`unknown` 跳过。
- `rules`：
  - FieldDefinition 的 `short_title`、`description`、`value_spec`、`source_guidance`；
  - 加 `card_payload(definition, examples=False)`；
  - 合成稳定的 JSON 文本；没有定义的字段（catalog 中找不到）抛 `ValueError("DEFINITION_MISSING")`。
- `quotes`：该字段 `evidence[].quote`，顺序不变；`value`：present 时为字段值文本（列表按"；"连接），否则 `None`。

### 3.3 运行命令（`harness/src/insurance_harness/eval/review_run.py`）

```text
python -m insurance_harness.eval.review_run --products P... --compile-root DIR [--compile-root DIR ...]
    --stage review --stage-config FILE --run-root DIR [--max-sent N] [--max-chars N] [--repo DIR]
```

- 每个产品：
  - 取第一个含 `<root>/<product>/output.json` 的编译目录；
  - 定义取 `pack_definitions(<repo>/<catalog>, output.pack_id, only_source_extractable=False)`；
  - 构造条目、分批、打分；
  - 写 `<run-root>/<product>/scores.json`：`{"reviewer": "<served_model>@<policy_version>", "reviewed_at": <带时区的 ISO 8601>, "scores": {...}}`，即 RV1 分数文件。
- **持久化与恢复**：
  - 每批请求的 sha256 与原始响应存 `<run-root>/<product>/responses/NNN.{request.sha256,txt}`；
  - 重跑时请求 sha 相同的批直接复用已存响应，不再发送；已有 `scores.json` 的产品跳过。
  - 只复用打分器接受过的响应：原始响应到达即存 `NNN.txt`，接受后才写 `NNN.request.sha256`。被拒的响应只留作诊断，重跑时该批在预算内重发；请求指纹含审核模型与 `policy_version`，换策略版本不复用旧响应。
- **预算**：
  - `--max-sent` 按运行目录累计（`budget.jsonl` 预留、`ledger.jsonl` 记录）；
  - 服务模型在一个运行目录内变化即停；运行目录加锁，不能并发。
- **失败**：任何一步失败打印一行 `{"stopped": <code>, ...}` 并以 2 退出。原因码有：
  - `OUTPUT_MISSING`、`DEFINITION_MISSING`、`REVIEW_OUTPUT_INVALID`；
  - `BUDGET_EXCEEDED`、`SERVED_MODEL_CHANGED`、`RUN_ROOT_BUSY`、`MODEL_ERROR`；
  - `INVALID_ARGUMENTS`（参数不合法）、`OUTPUT_INVALID`（编译输出读不了、结构不对或不属于该产品）、`RUN_ROOT_INVALID`（运行目录在 git 仓库内，或其预算、账本文件损坏，或写入失败）。

  输出不含路径、密钥或材料文本。
- **共用账本**：`eval/compile_run.py` 的 `_DurableLedger`、运行目录锁与 `prior_sends` 移到 `models/durable.py`（公开名），compile_run 与 review_run 共用，行为不变。
- **新阶段**：`models/stages.json` 增加 `review` 阶段，模型与供应商同 `schema_fields`，复用其密钥环境变量名，不新增密钥。输出 `json_object`，`policy_version` 独立。

### 3.4 RV1 规则修改（`review/routing.py`）

- `route`：
  - `unknown` 的 Claim 不检查分数与门槛；
  - 没有任何 `present`/`absent_explicitly` 的 Claim（含空列表）→ `NO_CLAIMS`；
  - 其余规则不变。
- `labelled`：
  - MACHINE 路由只要求 `present`/`absent_explicitly` 都有分数；
  - `unknown` 也标 MACHINE（同一审核者与时间），`score=None`。

### 3.5 不在本片

校准工具（RV2b）、真实调用与门槛（RV2c）、pack 准入（RV3）、抽检（RV4）。

## 4. 验收

- 受保护验收（Claude 写，RED 单独提交）：
  - `harness/tests/review/test_review_scorer.py`：
    - 分批（字数上限、单条超限截断、保序）；
    - 请求不含编译上下文，只有条目字段；
    - 解析拒绝缺 key、多 key、重复 key、越界、布尔、非 JSON；
    - 空输入不调用。
  - `harness/tests/compilers/schema_fields/test_review_items.py`：
    - 只取有内容的字段；
    - `rules` 含定义与卡片规则、不含示例；
    - logical key 与 Claim 一致；
    - 缺定义报错。
  - `harness/tests/eval/test_review_run.py`（假补全器）：
    - 写出分数文件，可被 RV1 分数文件格式读取；
    - 重跑不重发；
    - 预算用尽即停；
    - 服务模型变化即停；
    - 失败输出不泄露路径。
  - `harness/tests/review/test_review_routing.py`（RV1 验收，**本片更新**）：
    - 原用例改用有证据的 `present`/`absent_explicitly` Claim；
    - 新增 `unknown` 不需分数、全为 `unknown` 得 `NO_CLAIMS`、`unknown` 在机器路由下的标注三例。
    - 原因：用户 2026-10-17 裁定 unknown 不打分、不阻挡。
- 门禁：Harness `pytest`、`ruff`、`mypy src tests`；架构守卫（`review/` 核心目录不 import `compilers`、无领域词）；CI 全绿。

## 5. 改动范围

- 允许：
  - 新增 `review/scorer.py`、`compilers/schema_fields/review_items.py`、`eval/review_run.py`、`models/durable.py`；
  - 修改 `review/routing.py`、`compilers/schema_fields/claims.py`（只改为调用 `logical_key`）、`eval/compile_run.py`（只改为使用 `models/durable.py`）、`models/stages.json`；
  - 新增或更新上述测试。
- 不改：Go、前端、`contracts/`、编译提示词与编译流程行为、Golden。
- 受保护：本片验收文件、`docs/design/`、蓝图。

## 6. 依赖与预算

依赖 RV1（已在 `main`）。本片无真实调用、无迁移、无部署。真实运行在 RV2c，按已批准的 ≤ 40 次 deepseek-flash 与 5 个评委会话执行。
