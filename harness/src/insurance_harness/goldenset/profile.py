"""QualityProfile：按字段的质量画像、全局指标与回归判定（019 spec Q3 + 实施计划 Task4）。

- Q3.1 每 field_id 输出 support/value accuracy/tri-state confusion/hallucination/evidence/
  precision/recall/f1，并绑定 baseline 运行指纹与其派生 artifact/approval 的内容哈希；
- Q3.2 画像版本化 + 六维指纹 staleness；
- Q3.3/Q4.6 `compare_baselines` 覆盖全局 micro/macro F1 + hallucination + evidence + unresolved
  与字段阈值，结构化列出每个失败 `{metric, baseline, candidate, allowed}`。

画像是只读 artifact；真实 13 产品画像由 020 用同一 API 从已批准 baseline 派生。
"""

from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from .baseline import FiniteFloat, NonNegativeInt, Rate, RunFingerprint, canonical_sha256
from .normalize import quote_in_page, values_equal
from .records import GoldenRecord, TriState

if TYPE_CHECKING:
    from .baseline import ApprovalRecord

# 指标合法域（构造期不可越界）：Rate=[0,1] 有限；NonNegativeInt≥0；FiniteFloat 仅拒 NaN/±inf。
# 越界（如 value_accuracy=2.0、负计数）与 NaN 同属"应无法构造的非法状态"。

# design.md:13 —— 数据/模型维指纹，任一变化都要求重跑或重新批准（git_sha 属溯源，不计）。
_STALENESS_FIELDS = (
    "golden_release_hash",
    "schema_version",
    "model_id",
    "prompt_version",
    "template_profile",
    "source_profile",
)


class FieldMetrics(BaseModel):
    """单字段确定性指标（Q3.1）。"""

    model_config = ConfigDict(frozen=True)

    field_id: str
    support: NonNegativeInt
    value_accuracy: Rate
    hallucination_rate: Rate
    # None = 未回验（无 dataset_root 或引文无法定位），区别于"回验过但 0%"（0.0）——
    # 未回验不得当作 0% 参与回归（否则误报/漏报），但对自动资格仍 fail-closed（None→不达标）。
    evidence_accuracy: Rate | None
    precision: Rate = 0.0
    recall: Rate = 0.0
    f1: Rate = 0.0
    tri_state_confusion: dict[str, int]


class GlobalMetrics(BaseModel):
    """跨字段的全局指标（回归判定用；实施计划 Task3 要求）。"""

    model_config = ConfigDict(frozen=True)

    micro_f1: Rate = 0.0
    macro_f1: Rate = 0.0
    hallucination_rate: Rate = 0.0
    evidence_accuracy: Rate | None = None  # None = 未回验（不参与回归）
    unresolved_count: NonNegativeInt = 0


class AutomationThresholds(BaseModel):
    """字段自动化门槛（Q4.4 默认值）。"""

    model_config = ConfigDict(frozen=True)

    support_min: NonNegativeInt = 10
    value_accuracy_min: Rate = 0.98
    hallucination_rate_max: Rate = 0.01
    evidence_accuracy_min: Rate = 1.0


class FieldVerdict(BaseModel):
    """字段自动化资格判定；不达标时逐条列出失败指标与实际值（Q3.3）。"""

    model_config = ConfigDict(frozen=True)

    field_id: str
    eligible: bool
    failures: tuple[str, ...] = ()


class QualityProfile(BaseModel):
    """只读质量画像（Q3.1/Q3.2）；关联其派生 artifact 与批准记录的内容哈希（实施计划 Task4）。"""

    model_config = ConfigDict(frozen=True)

    profile_version: str
    artifact_sha256: str
    baseline_approval_sha256: str
    fingerprint: RunFingerprint
    fields: dict[str, FieldMetrics]
    global_metrics: GlobalMetrics = GlobalMetrics()

    def field(self, field_id: str) -> FieldMetrics | None:
        return self.fields.get(field_id)

    def content_hash(self) -> str:
        """画像**内容**的确定性哈希（版本/artifact 绑定/全局指标/各字段/指纹）。

        **排除 baseline_approval_sha256 回指**——使其在批准前后稳定，从而可被 ApprovalRecord
        提交（`profile_content_sha256`）；批准即"提交这份内容"，任意替换指标的画像哈希必然不同。
        """
        return canonical_sha256(
            self.model_dump(mode="json", exclude={"baseline_approval_sha256"})
        )

    def with_approval(self, approval: "ApprovalRecord") -> "QualityProfile":
        """由候选画像生成"已批准"画像：回链批准记录内容哈希（gate 据此验证绑定）。

        批准必须绑定同一 artifact **且提交本画像内容**——否则无法用任意画像给别的
        artifact/指标背书（批准提交的是内容哈希，不是可复制的公开 approval 哈希）。
        """
        if approval.artifact_sha256 != self.artifact_sha256:
            raise ValueError("approval.artifact_sha256 与画像 artifact_sha256 不一致")
        if approval.profile_content_sha256 != self.content_hash():
            raise ValueError("approval 未提交该画像内容（profile_content_sha256 不符）")
        return self.model_copy(update={"baseline_approval_sha256": approval.sha256()})

    def is_stale(self, current: RunFingerprint) -> bool:
        """Q3.2 + design：golden hash/schema/model/prompt/template/source 任一不匹配即 stale。

        （git_sha 是溯源信息、非数据维，按 design.md 不作为 staleness 触发。）
        """
        return any(
            getattr(self.fingerprint, f) != getattr(current, f)
            for f in _STALENESS_FIELDS
        )

    def field_verdict(
        self, field_id: str, thresholds: AutomationThresholds | None = None
    ) -> FieldVerdict:
        thresholds = thresholds or AutomationThresholds()
        metrics = self.fields.get(field_id)
        if metrics is None:
            return FieldVerdict(
                field_id=field_id, eligible=False, failures=("无该字段画像",)
            )
        failures: list[str] = []
        if metrics.support < thresholds.support_min:
            failures.append(f"support={metrics.support}<{thresholds.support_min}")
        if metrics.value_accuracy < thresholds.value_accuracy_min:
            failures.append(
                f"value_accuracy={metrics.value_accuracy:.3f}"
                f"<{thresholds.value_accuracy_min}"
            )
        if metrics.hallucination_rate > thresholds.hallucination_rate_max:
            failures.append(
                f"hallucination_rate={metrics.hallucination_rate:.3f}"
                f">{thresholds.hallucination_rate_max}"
            )
        if metrics.evidence_accuracy is None:  # 未回验 → 不达标（fail-closed，Q4.3）
            failures.append("evidence 未回验（无 dataset_root 或引文不可回验）")
        elif metrics.evidence_accuracy < thresholds.evidence_accuracy_min:
            failures.append(
                f"evidence_accuracy={metrics.evidence_accuracy:.3f}"
                f"<{thresholds.evidence_accuracy_min}"
            )
        return FieldVerdict(
            field_id=field_id, eligible=not failures, failures=tuple(failures)
        )


class RegressionThresholds(BaseModel):
    """回归容差（Q3.3/Q4.6 + 实施计划）：候选相对已批准基线在各指标上不得退化超过容差。"""

    model_config = ConfigDict(frozen=True)

    # 全局
    max_micro_f1_drop: Rate = 0.0
    max_macro_f1_drop: Rate = 0.0
    max_global_hallucination_increase: Rate = 0.0
    max_global_evidence_drop: Rate = 0.0
    max_unresolved_increase: NonNegativeInt = 0
    # 字段
    max_field_value_accuracy_drop: Rate = 0.0
    max_field_hallucination_increase: Rate = 0.0
    max_field_evidence_drop: Rate = 0.0


class RegressionFailure(BaseModel):
    """一条结构化回归失败：指标、已批准基线值、候选值、允许边界。"""

    model_config = ConfigDict(frozen=True)

    metric: str
    baseline: FiniteFloat
    candidate: FiniteFloat
    allowed: FiniteFloat


class RegressionResult(BaseModel):
    """回归判定结果；`failures` 为空才可批准（Q4.6）。"""

    model_config = ConfigDict(frozen=True)

    failures: tuple[RegressionFailure, ...] = ()

    @property
    def eligible(self) -> bool:
        return not self.failures

    def summary(self) -> str:
        return "；".join(
            f"{f.metric}: {f.baseline:.4g}→{f.candidate:.4g}（允许≥/≤{f.allowed:.4g}）"
            for f in self.failures
        )


def compare_baselines(
    current: QualityProfile,
    candidate: QualityProfile,
    thresholds: RegressionThresholds | None = None,
) -> RegressionResult:
    """候选画像相对已批准画像的退化检查（Q3.3/Q4.6）：全局 micro/macro F1、hallucination、
    evidence、unresolved-count 及每字段 value_accuracy/hallucination/evidence，逐条结构化返回。"""
    t = thresholds or RegressionThresholds()
    failures: list[RegressionFailure] = []
    cg, dg = current.global_metrics, candidate.global_metrics

    def drop(metric: str, base: float, cand: float, max_drop: float) -> None:
        if base - cand > max_drop:
            failures.append(RegressionFailure(
                metric=metric, baseline=base, candidate=cand, allowed=base - max_drop))

    def increase(metric: str, base: float, cand: float, max_inc: float) -> None:
        if cand - base > max_inc:
            failures.append(RegressionFailure(
                metric=metric, baseline=base, candidate=cand, allowed=base + max_inc))

    def drop_opt(metric: str, base: float | None, cand: float | None, max_drop: float) -> None:
        # 任一侧未回验（None）就跳过——未测量维度不参与回归，避免"未测量→0"造成误报/漏报；
        # 候选的证据绝对达标由 gate 的 field_verdict（evidence≥1.0）兜底，与回归分层。
        if base is None or cand is None:
            return
        drop(metric, base, cand, max_drop)

    drop("global.micro_f1", cg.micro_f1, dg.micro_f1, t.max_micro_f1_drop)
    drop("global.macro_f1", cg.macro_f1, dg.macro_f1, t.max_macro_f1_drop)
    increase("global.hallucination_rate", cg.hallucination_rate, dg.hallucination_rate,
             t.max_global_hallucination_increase)
    drop_opt("global.evidence_accuracy", cg.evidence_accuracy, dg.evidence_accuracy,
             t.max_global_evidence_drop)
    increase("global.unresolved_count", cg.unresolved_count, dg.unresolved_count,
             t.max_unresolved_increase)

    for field_id, base in current.fields.items():
        cand = candidate.fields.get(field_id)
        if cand is None:
            failures.append(RegressionFailure(
                metric=f"{field_id}.missing", baseline=1.0, candidate=0.0, allowed=1.0))
            continue
        drop(f"{field_id}.value_accuracy", base.value_accuracy, cand.value_accuracy,
             t.max_field_value_accuracy_drop)
        increase(f"{field_id}.hallucination_rate", base.hallucination_rate,
                 cand.hallucination_rate, t.max_field_hallucination_increase)
        drop_opt(f"{field_id}.evidence_accuracy", base.evidence_accuracy,
                 cand.evidence_accuracy, t.max_field_evidence_drop)
    return RegressionResult(failures=tuple(failures))


def _evidence_quote_counts(
    record: GoldenRecord, page_cache: dict[Path, dict[int, str]], dataset_root: Path | None
) -> tuple[int, int]:
    """该 present 预测的 (可回验引文数, 总引文数)，与 `eval._evidence_accuracy` 同一 **per-quote**
    口径（消除 profile↔evaluator 的证据语义漂移）。

    无证据 / 无 dataset_root / PDF 缺失都返回 (0,0)——即"未测量"，不当作"回验失败(0%)"：
    未测量与测得 0% 必须区分（None vs 0.0），否则回归会误报/漏报。真实自动化
    用画像必须带 dataset_root（Q3.1/Q5.1）。
    """
    if not record.evidence or dataset_root is None:
        return 0, 0
    pdf = dataset_root / record.product_name / record.doc
    if not pdf.exists():
        return 0, 0
    if pdf not in page_cache:
        from .pdf import extract_pages

        page_cache[pdf] = {p.page_no: p.text for p in extract_pages(pdf)}
    pages = page_cache[pdf]
    ok = sum(
        1 for ev in record.evidence
        if ev.page in pages and quote_in_page(ev.quote, pages[ev.page])
    )
    return ok, len(record.evidence)


def build_profile(
    golden: list[GoldenRecord],
    pred: list[GoldenRecord],
    fingerprint: RunFingerprint,
    *,
    artifact_sha256: str,
    unresolved_count: int = 0,
    dataset_root: Path | None = None,
    version: str = "1",
) -> QualityProfile:
    """从 golden vs pred 逐字段派生候选画像（确定性；disputed 金标排除）。

    产出 baseline_approval_sha256="" 的**候选**画像；批准后由 `.with_approval(approval)` 回链。
    `artifact_sha256` 必须等于派生自的 BaselineArtifact.sha256()（approve 时强制核对）。
    """
    # 复用权威 evaluator（不重复实现指标口径）+ 共用"可评测键"权威。
    from .eval import evaluate, excluded_disputed_keys

    usable = [g for g in golden if not g.disputed]
    g_map = {(g.product_id, g.field_id): g for g in usable}
    p_map = {(p.product_id, p.field_id): p for p in pred}
    excluded_only = excluded_disputed_keys(golden)  # disputed-only 键：预测不可评测，不进字段聚合
    page_cache: dict[Path, dict[int, str]] = {}

    # 全局指标 + 每字段 P/R/F1 全部取自 evaluate：pred-only 多余字段计入 micro FP、
    # 空分母口径一致——避免"只遍历金标键"导致产生多余字段的模型被误判满分。
    result = evaluate(golden, pred, dataset_root=dataset_root)

    golden_field_ids = {key[1] for key in g_map}
    by_field_keys: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in g_map:
        by_field_keys[key[1]].append(key)
    # 已知 field_id 的 pred-only present 键也纳入该字段观察——本字段的伪造必须体现在字段画像上，
    # 否则在线 gate 只看字段指标会误放。
    for key in p_map:
        if key in g_map or key in excluded_only:  # disputed-only 的预测不计入字段幻觉/证据
            continue
        if key[1] in golden_field_ids:
            by_field_keys[key[1]].append(key)

    fields: dict[str, FieldMetrics] = {}
    for field_id, keys in by_field_keys.items():
        support = sum(1 for k in keys if k in g_map)  # support = 金标观测数（不含 pred-only）
        confusion: Counter[str] = Counter()
        value_hits = value_pairs = pred_present = 0
        hallucinated = ev_ok = ev_total = 0
        for key in keys:
            g = g_map.get(key)  # None = pred-only（本字段覆盖面之外的伪造）
            p = p_map.get(key)
            p_tri: TriState = p.tri_state if p is not None else "unknown"
            if g is not None:
                confusion[f"{g.tri_state}>{p_tri}"] += 1
            if p is not None and p.tri_state == "present":
                pred_present += 1
                vq, tq = _evidence_quote_counts(p, page_cache, dataset_root)
                ev_ok += vq
                ev_total += tq
                if g is not None and g.tri_state == "present":
                    value_pairs += 1
                    if values_equal(g.value, p.value):
                        value_hits += 1
                else:  # g absent，或 g is None（pred-only）→ 幻觉
                    hallucinated += 1
        stats = result.per_field.get(field_id)  # evaluate 对每金标字段都建有条目
        fields[field_id] = FieldMetrics(
            field_id=field_id,
            support=support,
            # 零观测不给满分：无 present 预测配对 = 无正确抽取证据 → 0.0（失格），
            # 绝不用零分母默认 1.0 让"什么都没抽到"的字段获得自动资格（Q4.3）。
            value_accuracy=(value_hits / value_pairs) if value_pairs else 0.0,
            hallucination_rate=(hallucinated / pred_present) if pred_present else 0.0,
            # None = 未回验（无 dataset_root 或引文无法定位），区别于回验过的 0%。
            evidence_accuracy=(ev_ok / ev_total) if ev_total else None,
            precision=stats.precision if stats else 0.0,
            recall=stats.recall if stats else 0.0,
            f1=stats.f1 if stats else 0.0,
            tri_state_confusion=dict(confusion),
        )
    global_metrics = GlobalMetrics(
        micro_f1=result.micro.f1,
        macro_f1=result.macro_f1,
        hallucination_rate=result.hallucination_rate,
        evidence_accuracy=result.evidence_accuracy,  # None 透传（未回验不参与回归）
        unresolved_count=unresolved_count,
    )
    return QualityProfile(
        profile_version=version,
        artifact_sha256=artifact_sha256,
        baseline_approval_sha256="",
        fingerprint=fingerprint,
        fields=fields,
        global_metrics=global_metrics,
    )
