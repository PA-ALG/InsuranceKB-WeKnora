# RV1 · 审核标注与人工队列：发布时按版本化审核策略决定自动上线还是进人工队列

> 状态：用户已确认开工（2026-10-17："先发布后抽检"尽快排进来） ｜ 作者：Claude Code
> 依据：蓝图 §6.3（先发布后抽检）、§5.1（Claim.review）、硬边界 8；S4g、S3d-2 Spec
> 分支：`slice/rv1` ｜ 工作目录：`.worktrees/rv1` ｜ 实现方：Claude ｜ 审核方：Codex（改变发布规则）

"先发布后抽检"拆为 RV1–RV5：
- **RV1（本片）**：审核标注与按策略分流，无模型调用；
- RV2：独立审核打分（deepseek-flash 独立调用，Golden 上校准，≤40 次，用户已批准）；
- RV3：pack 质量准入，先从 1824 所在 pack 开始；
- RV4：上线后分层抽检与"请确认"队列；
- RV5：人工队列页面。

## 1. 目标

1. **标注真实**：发布的每条 Claim 的 `review` 如实写明由谁审核。
   - 现状 `Review` 默认 `mode: machine`，所以 1828 已发布的 Claim 虽经人工批准，却被标成"机器审核"；
   - 本片起人工决定的 Claim 标 `mode: human`；只有按策略自动通过的 Claim 才标 `mode: machine`，并带分数、审核者与时间。
2. **按策略分流**：发布命令新增 `--route`，按版本化的 ReviewPolicy 与审核分数决定：
   - 整款产品都通过 → 机器决定（带 `policy_ref`）并激活；
   - 否则 → 只提交候选，留在人工队列，等人工决定。
3. **失败关闭**：打分器（RV2）与 pack 准入（RV3）就绪前，策略不准入任何 pack，所有内容都进人工队列。

## 2. 现状（`main@76efdc825`）

- `contracts.knowledge.Review`：`mode`（默认 MACHINE）、`score`、`reviewer`、`reviewed_at`；`Claim.review` 默认 `Review()`。
- `contracts.bundle.ReviewPlan`：`mode`、`policy_ref`、`sample_size`；`CandidateBundle.review_plan` 列表。
- Go 决定接口：`mode` 为 `machine` 时必须带 `policy_ref`（`internal/enterprise/release/publish.go`）。
- 发布命令只支持显式 `--decide human --reason` 或 `--decide machine --policy-ref`，后者可以不经任何分数就标"机器审核"。
- catalog 中 11 个 pack 的 `quality_status` 都是 `REGISTERED_NOT_QUALITY_ADMITTED`。

## 3. 设计

### 3.1 审核策略（`harness/src/insurance_harness/catalog/review_policy.py` + 数据文件 `catalog/review_policy.json`）

```python
class PackThresholds(BaseModel):          # extra="forbid"
    default: float | None = None          # [0, 1]
    fields: dict[str, float] = {}         # field_key -> [0, 1]，覆盖 default

class ReviewPolicy(BaseModel):            # extra="forbid"
    version: NonBlank
    admitted_packs: list[NonBlank] = []   # 已通过质量准入的 pack（RV3 写入）
    thresholds: dict[str, PackThresholds] = {}
    @property
    def policy_ref(self) -> str: ...      # "review-policy@<version>"
    def admitted(self, pack_id: str) -> bool: ...
    def threshold(self, pack_id: str, field_key: str) -> float | None: ...  # 字段值优先，其次 default，没有则 None

def load_review_policy(path: str | Path | None = None) -> ReviewPolicy   # None → 包内 review_policy.json
```

- 包内数据：`{"version": "1", "admitted_packs": [], "thresholds": {}}`（不准入任何 pack）。门槛调整必须改版本号（硬边界 8）。
- 校验：分数门槛在 `[0, 1]`；`admitted_packs` 不重复；读不了或结构不对抛 `ValueError`。

### 3.2 分流与标注（`harness/src/insurance_harness/review/routing.py`，核心目录，只用合同类型）

```python
@dataclass(frozen=True)
class Scores:
    reviewer: str                 # 例如 "deepseek-flash@review-v1"
    reviewed_at: str              # ISO 8601
    by_key: Mapping[str, float]   # Claim.logical_key -> [0, 1]

@dataclass(frozen=True)
class Route:
    mode: ReviewMode              # MACHINE 或 HUMAN
    policy_ref: str | None        # MACHINE 时必有
    reasons: tuple[str, ...]      # HUMAN 时的原因码，去重后排序

HUMAN_DECISION: Route   # 人工决定：Route(HUMAN, None, ())

def route(claims, *, admitted: bool, threshold: Callable[[str], float | None],
          scores: Scores | None, policy_ref: str) -> Route
def labelled(claims, route: Route, scores: Scores | None) -> list[Claim]
```

- `route`：整款产品（一次发布的全部 Claim）为一个单元。全部满足以下条件才得 MACHINE，否则 HUMAN，并给出全部原因码：
  - `admitted` 为真，否则 `PACK_NOT_ADMITTED`；
  - 有 `scores`，否则 `SCORES_MISSING`；
  - 每条 Claim 都有分数，否则 `SCORE_MISSING`；
  - 每条 Claim 的 predicate 都有门槛，否则 `THRESHOLD_MISSING`；
  - 每条分数 ≥ 门槛，否则 `BELOW_THRESHOLD`；
  - 至少有一条 Claim，否则 `NO_CLAIMS`（没有内容可审，不自动上线）。

  缺 `scores` 时只报 `SCORES_MISSING`，不再逐条报 `SCORE_MISSING`；只有分数与门槛都在时才比较 `BELOW_THRESHOLD`。

  原因码不含字段键或任何输入文本。按字段拆分（部分自动、部分人工）要等平台支持激活时自动 rebase（S5），本片不做。
- `labelled`：返回新的 Claim 列表（不改原对象）；MACHINE 路由下若有 Claim 缺分数（或没有 `scores`）抛 `ValueError`。
  - MACHINE：`review = Review(mode=MACHINE, score=<该条分数>, reviewer=scores.reviewer, reviewed_at=scores.reviewed_at)`；
  - HUMAN：`review = Review(mode=HUMAN, score=<有则带上>, reviewer=None, reviewed_at=None)`，由人工决定记录谁、何时。

### 3.3 候选包（`compilers/schema_fields/claims.py`、`bundle/assemble.py`）

- `candidate_bundle(..., review: tuple[Route, Scores | None] | None = None)`：
  - 先按 `review` 标注 Claim，再组装；`review` 为 `None` 时按 `HUMAN_DECISION` 标注（不再沿用默认的 machine）；
  - 包的 `review_plan` 写一项 `ReviewPlan(mode=<route.mode>, policy_ref=<route.policy_ref>)`。
- `assemble(..., review_plan: Sequence[ReviewPlan] = ())` 透传到 `CandidateBundle.review_plan`。

### 3.4 发布命令（`compilers/schema_fields/publish.py`）

- 参数：
  - `--decide` 只剩 `human`（须带 `--reason`）。删除 `--decide machine --policy-ref`：机器决定只能来自 `--route`。
  - 新增 `--route`：按 `--review-policy <file>`（默认包内策略）与 `--scores <file>`（可省）分流。
  - `--activate` 只能与 `--decide human` 同用；`--route` 自带激活规则。
  - 以下组合一律 `INVALID_ARGUMENTS`，且不发出任何请求：`--route` 与 `--decide` 同用；`--route` 与 `--activate` 同用；
    `--scores` 或 `--review-policy` 不带 `--route`；分数文件读不了或结构不对；策略文件读不了或结构不对。
- 分数文件：`{"reviewer": "...", "reviewed_at": "...", "scores": {"<logical_key>": <0..1>, ...}}`，结构不对即拒绝。
- 行为：
  - `--decide human`：Claim 标 HUMAN，决定 `{outcome: approve, mode: human, reason}`，可 `--activate`；
  - `--route` 得 MACHINE：Claim 标 MACHINE，决定 `{outcome: approve, mode: machine, policy_ref}` 并激活；
  - `--route` 得 HUMAN：Claim 标 HUMAN，只提交候选，不决定、不激活；
  - 都不给：只提交候选，Claim 标 HUMAN。
- 输出 JSON 增加 `"review": "machine" | "human"`；`--route` 得 HUMAN 时另加 `"reasons": [...]`。其余字段不变。

### 3.5 不在本片

- 打分器（RV2）、准入数据（RV3）、抽检（RV4）、人工队列页面（RV5）；
- 页面上显示审核标签（S3d-3a 合并后另做）；
- 合同中 `Review` 默认值的调整：本片起所有发布路径都显式设置，默认值不再生效；
- 按字段拆分（等 S5 自动 rebase）。

## 4. 验收

- 受保护验收（Claude 写，RED 单独提交）：
  - `harness/tests/review/test_routing.py`：
    - 未准入、缺分数、缺单条分数、缺门槛、低于门槛各自得 HUMAN 并给出原因码；
    - 全部满足得 MACHINE，带 policy_ref；字段门槛覆盖默认门槛；
    - 标注结果逐字段正确，且不改原 Claim。
  - `harness/tests/catalog/test_review_policy.py`：加载、校验、`policy_ref`、门槛优先级；包内策略不准入任何 pack。
  - `harness/tests/compilers/schema_fields/test_publish_routing.py`（新）：
    - `--route` 用包内策略 → 只提交、不决定、不激活，原因 `PACK_NOT_ADMITTED`、`SCORES_MISSING`、`THRESHOLD_MISSING`；
    - `--route` 用准入策略加全部达标的分数 → 机器决定带 `policy_ref` 并激活，Claim 标 machine 带分数；
    - 单字段低于门槛 → 整款进人工队列，原因 `BELOW_THRESHOLD`。
  - `harness/tests/compilers/schema_fields/test_publish_cli.py`（S4g/S3d-2 验收，**本片更新**）：
    - 人工决定的 Claim 标 human；`review_plan` 正确；
    - 参数组合非法一律 `INVALID_ARGUMENTS` 且不发出请求；删除 `--decide machine` 一例。
    - 原因：S4g 时允许不经分数手动标"机器审核"，违反硬边界 8；输出增加 `review` 字段。
- 门禁：Harness `pytest`、`ruff`、`mypy src tests`；架构守卫（`review/` 是核心目录：不得 import `compilers`、不得含领域词）；CI 全绿。

## 5. 改动范围

- 允许：
  - 新增 `harness/src/insurance_harness/review/`、`harness/src/insurance_harness/catalog/`（含 `review_policy.json`）；
  - `bundle/assemble.py`、`compilers/schema_fields/claims.py`、`compilers/schema_fields/publish.py`；
  - 新增或更新上述测试；`harness/pyproject.toml`（只在需要打包 JSON 数据时）。
- 不改：Go、前端、`contracts/`、迁移、catalog 生成文件。
- 受保护：本片验收文件、`docs/design/`、蓝图。

## 6. 依赖与环境

依赖 S4g、S3d-2（均已在 `main`）。无模型调用、无迁移、无部署。S3d 部署重新发布 1828 时，若本片已合并，即可修正已发布 Claim 的标注。
