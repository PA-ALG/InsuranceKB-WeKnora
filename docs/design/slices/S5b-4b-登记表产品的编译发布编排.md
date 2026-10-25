# S5b-4b · 登记表产品的编译发布编排

> 状态：Claude 2026-10-25 提出 ｜ 作者：Claude Code
> 依据：
> - S5b-1 §0：归属变化后只编译、发布受影响的产品；
> - S5b-4a（#350）：编译、首次发布、变化发布三个命令都能读产品登记表；
> - 蓝图硬边界 8："先发布后抽检"。只有确定性检查通过、所属险种包已通过质量准入、审核分数达到门槛的内容才自动上线，其余进人工队列。
>
> 实现方：**Codex** ｜ 审核方：Claude ｜ 真实模型调用：本片 0（测试用假命令）；线上运行另需用户批准预算

## 1. 目标

新增命令 `uploads publish`，一轮完成三件事：

1. 编译材料有变化的产品；
2. 给新编译的产品做审核打分；
3. 把编译结果有变化的产品发布出去。

只调用现有的三个命令（S5b-4a 之后都能读登记表），不改编译、打分、路由、发布的规则。重点有三条：

- **只花必要的调用**：材料与卡片版本都没变的产品，不编译、不打分；
- **每轮有上限**：编译与打分各自有每轮的发送上限，用完就停，下一轮接着做；
- **可以先演练**：只算计划，不调用模型，也不读写平台。

## 2. 运行目录

`--run-root DIR`：

| 路径 | 内容 |
|---|---|
| `DIR/compile/` | 编译运行目录（`compile_run` 的 `--run-root`），每个产品一个 `output.json` |
| `DIR/review/` | 打分运行目录（`review_run` 的 `--run-root`），每个产品一个 `scores.json` |
| `DIR/published.json` | 各产品最近一次发布成功时 `output.json` 的 SHA-256，原子写入 |

## 3. 一轮的步骤

产品取登记表中的全部产品，按 id 排序；`--products` 可以限定一部分。

1. **计划**（不调用模型，不读平台）：
   - **要编译**：`compile/<p>/output.json` 不存在；或其 `materials` 不等于登记表中该产品材料的 `knowledge_id:parse_attempt:sha256`（排序后）；或其 `cards_version` 不等于当前卡片版本。
     - 这与 `compile_products` 自己的复用判断一致。编译时页面仍按固定版本重新读取并核对，计划只决定要不要调用这个命令。
   - **要发布**：本轮会编译的产品；或 `output.json` 的 SHA-256 不等于 `published.json` 中的记录。
2. **编译**：要编译的产品不为空时，调用 `compile_run.main`：
   - 参数为 `--registry`、`--products <要编译的产品>`、`--stage schema_fields`、`--stage-config`、`--run-root DIR/compile`；
   - `--max-sent` 取该目录已发送数加 `--compile-max-sent`（默认 30），已发送数用 `models.durable.prior_sends` 计算；
   - 停下（退出码非 0）时，本轮按它输出的错误码结束：已完成的产品已经落盘，下一轮复用；本轮不打分、不发布。
3. **打分**：对本轮实际重新编译的产品（`reused` 为 false），调用 `review_run.main`：
   - 参数为 `--products …`、`--compile-root DIR/compile`、`--stage review`、`--stage-config`、`--run-root DIR/review`；
   - `--max-sent` 取已发送数加 `--review-max-sent`（默认 10）；
   - 打分停下时**不结束本轮**，报告其错误码，继续发布：没有分数的产品，按现有路由进入人工队列。
4. **发布**：按 id 顺序，对每个要发布的产品：
   - 读一次 Active，判断其中有没有该产品的 Claim：
     - 没有：用首次发布命令（`publish.main`）；
     - 有：用变化发布命令（`publish_changes.main`）；
   - 两者参数都是：
     - `--run-root DIR/compile`、`--product`、`--registry`、`--route`；
     - `--scores DIR/review/<p>/scores.json`，只在该文件存在时给；
     - 默认的审核策略与抽检策略；
   - 成功（退出码 0）后，把该产品 `output.json` 的 SHA-256 写入 `published.json`；
   - 失败时报告错误码，不写 `published.json`，继续下一个产品；下一轮还会再发布它。
5. **报告**：输出一行 JSON：
   - `compiled`、`reused`、`reviewed`、`published`（每个产品的路由结果：`machine` / `human` / `unchanged`）、`failed`（产品与错误码）、`stopped`（如有）；
   - 本轮编译与打分的发送数；
   - 只含产品 id、计数与错误码，不含路径或材料内容。

## 4. 其他规则

- **锁**：在登记表锁内运行，与 `seed`、`run`、`confirm` 互斥，避免运行中归属又发生变化。
- **演练**（`--dry-run`）：只做第 1 步，报告要编译、要发布的产品；不调用任何命令，不读平台。
- **起步复用**（`--seed-from DIR`，可多次给）：第 1 步之前，对 `compile/<p>/output.json` 还不存在的产品，在给出的目录中找 `<p>/output.json`，满足以下条件就复制进来：
  - `entity_id` 是这个产品，`pack_id` 是登记表中的险种包；
  - `materials` 与 `cards_version` 都与当前一致。

  复制来的产品计划上不编译。演练时不复制文件，按复制之后的情况计划。如果它的内容已经在 Active 中，变化发布报告"无变化"，记入 `published.json`。用途是首次运行时复用产生当前 Active 的编译结果，不必全部重编。
- **发布结果未知**：发布命令成功、但写入 `published.json` 之前中断时，下一轮会再发布一次：
  - 已上线的内容，变化发布报告"无变化"；
  - 进入人工队列、尚未上线的内容，会再提交一个候选。

  这是已知限制，写进报告说明；人工队列按候选的发布版本基线核对。
- **不新增质量规则**：路由与抽检完全沿用现有命令。只有已准入的险种包（目前是重疾险）在分数达标时自动上线并提交抽检样本，其余进人工队列。

## 5. 改动

- `harness/src/insurance_harness/ingest/publication.py`（新）：

  ```python
  class PublicationPlan(BaseModel):
      compile: list[str]
      publish: list[str]

  class PublicationReport(BaseModel):
      planned_compile: list[str]
      planned_publish: list[str]
      compiled: list[str]      # 本轮实际重新编译的（编译摘要中 reused 为 false）
      reused: list[str]
      reviewed: list[str]
      routes: dict[str, Literal["machine", "human", "unchanged"]]
      failed: dict[str, str]   # 产品 -> 发布命令的错误码
      stopped: str | None      # 编译停下时的错误码
      review_stopped: str | None
      compile_sent: int        # 本轮的发送数：运行前后 prior_sends 之差
      review_sent: int

  def plan(registry: ProductRegistry, run_root: Path,
           products: Sequence[str] | None = None) -> PublicationPlan
  def run_publication(registry_path: Path, run_root: Path, *, client: PlatformClient,
                      stage_config: Path, compile_max_sent: int = 30, review_max_sent: int = 10,
                      dry_run: bool = False, products: Sequence[str] | None = None,
                      seed_from: Sequence[Path] = ()) -> PublicationReport
  ```

  - 四个命令按模块属性调用：`compile_run.main`、`review_run.main`、`publish.main`、`publish_changes.main`，模块分别从 `insurance_harness.eval` 与 `insurance_harness.compilers.schema_fields` 导入。在进程内调用，用 `contextlib.redirect_stdout` 读取它们输出的一行 JSON。
  - 路由取发布命令输出的 `review`（`machine` / `human`）；变化发布输出 `no_changes: true` 时记为 `unchanged`。
  - 读 Active 用传入的 `client`。`uploads publish` 用环境变量与 `transport` 构造它，和 `confirm` 一样。
  - 未知产品（`--products` 中有登记表里没有的）：在任何命令之前以 `PRODUCT_UNKNOWN` 停下。
- `harness/src/insurance_harness/ingest/uploads.py`：`publish` 子命令，参数为：
  - `--registry`、`--run-root`、`--stage-config`；
  - `--compile-max-sent`、`--review-max-sent`；
  - `--products`、`--seed-from`、`--dry-run`。

  它与其他子命令共用锁、退出码（0 成功；1 错误码，包括编译停下；2 缺配置；3 `REGISTRY_BUSY`）和环境变量。
- **不改** `compile_run.py`（已 499 行）、`review_run.py`、两个发布命令。

## 6. 验收（RED，Claude 编写，受保护）

`harness/tests/ingest/test_publication.py`。三个命令在测试里换成假的 `main`：记录收到的参数，写出或读入 `output.json` / `scores.json`，输出一行 JSON；平台的 Active 也是假的。

1. **计划**：
   - 没有输出、材料变化、卡片版本变化的产品要编译；
   - 材料与版本都没变的不编译；
   - 已发布摘要不同的要发布；
   - 摘要相同的既不编译也不发布。
2. **编译**：
   - 只把要编译的产品传给编译命令；
   - `--max-sent` 等于目录已发送数加每轮上限；
   - 参数含 `--registry`；
   - 编译停下时，本轮以其错误码结束，不打分、不发布。
3. **打分**：
   - 只对实际重新编译的产品打分，上限计算同上；
   - 打分停下时仍然发布，没有分数的产品不带 `--scores`。
4. **发布**：
   - Active 中没有该产品的 Claim 用首次发布，有则用变化发布；
   - 参数含 `--registry`、`--route`，有分数时带 `--scores`；
   - 成功后写 `published.json`；
   - 某个产品失败不影响其他产品，下一轮重发失败的那个。
5. **演练**：不调用任何命令，不读平台；报告与随后正式运行的计划一致。
6. **起步复用**：
   - 符合条件的输出被复制并计划为不编译；
   - 产品、险种包、材料、卡片版本任一不符时不复制。
7. **报告与命令**：
   - 报告不含路径或材料内容；
   - 子命令遵守登记表锁与退出码；
   - 缺少配置返回 2。

**门禁**：
- 在 `harness/` 下运行 `uv run pytest`（相对 main 不新增失败）、`uv run ruff check .`、`uv run mypy src tests`；
- 架构守卫。

## 7. 上线与预算（需要用户批准）

- 本片合并后，第一次线上运行先演练，再正式运行。正式运行用 `--seed-from` 指向产生当前 Active 的编译目录。按目前登记表（13 个产品、没有新材料），预计不调用模型，只做 13 次"无变化"的发布核对。
- 以后有新材料时：每个材料变化的产品，编译约 4 到 6 次 DeepSeek flash 调用（按批选段，再按批抽值），打分约 1 次；每轮上限默认编译 30 次、打分 10 次。
- 质量：
  - 只有重疾险包已通过准入，分数达标才自动上线并抽检；
  - 其余险种发布后进入人工队列，等人在页面确认。
