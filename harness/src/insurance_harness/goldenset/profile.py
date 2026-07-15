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

from .baseline import RunFingerprint, canonical_sha256
from .normalize import quote_in_page, values_equal
from .records import GoldenRecord, TriState

if TYPE_CHECKING:
    from .baseline import ApprovalRecord

# design.md:13 —— 数据/模型维指纹，任一变化都要求重跑或重新批准（git_sha 属溯源，不计）。
_STALENESS_FIELDS = (
    "golden_release_hash",
    "schema_version",
    "model_id",
    "prompt_version",
    "template_profile",
    "source_profile",
)


def _f1(precision: float, recall: float) -> float:
    return (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0


class FieldMetrics(BaseModel):
    """单字段确定性指标（Q3.1）。"""

    model_config = ConfigDict(frozen=True)

    field_id: str
    support: int
    value_accuracy: float
    hallucination_rate: float
    evidence_accuracy: float
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    tri_state_confusion: dict[str, int]


class GlobalMetrics(BaseModel):
    """跨字段的全局指标（回归判定用；实施计划 Task3 要求）。"""

    model_config = ConfigDict(frozen=True)

    micro_f1: float = 0.0
    macro_f1: float = 0.0
    hallucination_rate: float = 0.0
    evidence_accuracy: float = 0.0
    unresolved_count: int = 0


class AutomationThresholds(BaseModel):
    """字段自动化门槛（Q4.4 默认值）。"""

    model_config = ConfigDict(frozen=True)

    support_min: int = 10
    value_accuracy_min: float = 0.98
    hallucination_rate_max: float = 0.01
    evidence_accuracy_min: float = 1.0


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
        """画像内容的确定性哈希（覆盖版本/关联哈希/全局指标/各字段/指纹）。"""
        return canonical_sha256(self.model_dump(mode="json"))

    def with_approval(self, approval: "ApprovalRecord") -> "QualityProfile":
        """由候选画像生成"已批准"画像：回链批准记录内容哈希（gate 据此验证绑定）。

        批准必须绑定同一 artifact——否则无法用任意画像给别的 artifact 背书。
        """
        if approval.artifact_sha256 != self.artifact_sha256:
            raise ValueError("approval.artifact_sha256 与画像 artifact_sha256 不一致")
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
        if metrics.evidence_accuracy < thresholds.evidence_accuracy_min:
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
    max_micro_f1_drop: float = 0.0
    max_macro_f1_drop: float = 0.0
    max_global_hallucination_increase: float = 0.0
    max_global_evidence_drop: float = 0.0
    max_unresolved_increase: int = 0
    # 字段
    max_field_value_accuracy_drop: float = 0.0
    max_field_hallucination_increase: float = 0.0
    max_field_evidence_drop: float = 0.0


class RegressionFailure(BaseModel):
    """一条结构化回归失败：指标、已批准基线值、候选值、允许边界。"""

    model_config = ConfigDict(frozen=True)

    metric: str
    baseline: float
    candidate: float
    allowed: float


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

    drop("global.micro_f1", cg.micro_f1, dg.micro_f1, t.max_micro_f1_drop)
    drop("global.macro_f1", cg.macro_f1, dg.macro_f1, t.max_macro_f1_drop)
    increase("global.hallucination_rate", cg.hallucination_rate, dg.hallucination_rate,
             t.max_global_hallucination_increase)
    drop("global.evidence_accuracy", cg.evidence_accuracy, dg.evidence_accuracy,
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
        drop(f"{field_id}.evidence_accuracy", base.evidence_accuracy, cand.evidence_accuracy,
             t.max_field_evidence_drop)
    return RegressionResult(failures=tuple(failures))


def _evidence_verified(
    record: GoldenRecord, page_cache: dict[Path, dict[int, str]], dataset_root: Path | None
) -> bool:
    """present 预测是否有可信证据：至少一条 evidence 且引文经 PDF 回验通过。

    无 dataset_root 时**无法回验**——不得把未回验的引文当作可信证据（否则生产自动资格
    会被 CI 代理证据蒙混）。真实自动化用画像必须带 dataset_root（Q3.1/Q5.1）。
    """
    if not record.evidence:
        return False
    if dataset_root is None:
        return False
    pdf = dataset_root / record.product_name / record.doc
    if not pdf.exists():
        return False
    if pdf not in page_cache:
        from .pdf import extract_pages

        page_cache[pdf] = {p.page_no: p.text for p in extract_pages(pdf)}
    pages = page_cache[pdf]
    return all(
        ev.page in pages and quote_in_page(ev.quote, pages[ev.page])
        for ev in record.evidence
    )


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
    usable = [g for g in golden if not g.disputed]
    g_map = {(g.product_id, g.field_id): g for g in usable}
    p_map = {(p.product_id, p.field_id): p for p in pred}
    page_cache: dict[Path, dict[int, str]] = {}

    by_field_keys: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in g_map:
        by_field_keys[key[1]].append(key)

    fields: dict[str, FieldMetrics] = {}
    tot_hits = tot_pred_present = tot_golden_present = 0
    tot_hallucinated = tot_evidence_ok = tot_evidence_total = 0
    f1s: list[float] = []
    for field_id, keys in by_field_keys.items():
        support = len(keys)
        confusion: Counter[str] = Counter()
        value_hits = value_pairs = pred_present = golden_present = 0
        hallucinated = evidence_ok = evidence_total = 0
        for key in keys:
            g = g_map[key]
            p = p_map.get(key)
            if g.tri_state == "present":
                golden_present += 1
            p_tri: TriState = p.tri_state if p is not None else "unknown"
            confusion[f"{g.tri_state}>{p_tri}"] += 1
            if p is not None and p.tri_state == "present":
                pred_present += 1
                evidence_total += 1
                if _evidence_verified(p, page_cache, dataset_root):
                    evidence_ok += 1
                if g.tri_state == "present":
                    value_pairs += 1
                    if values_equal(g.value, p.value):
                        value_hits += 1
                else:
                    hallucinated += 1
        precision = (value_hits / pred_present) if pred_present else 0.0
        recall = (value_hits / golden_present) if golden_present else 0.0
        field_f1 = _f1(precision, recall)
        f1s.append(field_f1)
        tot_hits += value_hits
        tot_pred_present += pred_present
        tot_golden_present += golden_present
        tot_hallucinated += hallucinated
        tot_evidence_ok += evidence_ok
        tot_evidence_total += evidence_total
        fields[field_id] = FieldMetrics(
            field_id=field_id,
            support=support,
            # 零观测不给满分：无 present 预测配对 = 无正确抽取证据 → 0.0（失格），
            # 绝不用零分母默认 1.0 让"什么都没抽到"的字段获得自动资格（Q4.3）。
            value_accuracy=(value_hits / value_pairs) if value_pairs else 0.0,
            hallucination_rate=(hallucinated / pred_present) if pred_present else 0.0,
            evidence_accuracy=(evidence_ok / evidence_total) if evidence_total else 0.0,
            precision=precision,
            recall=recall,
            f1=field_f1,
            tri_state_confusion=dict(confusion),
        )
    micro_p = (tot_hits / tot_pred_present) if tot_pred_present else 0.0
    micro_r = (tot_hits / tot_golden_present) if tot_golden_present else 0.0
    global_metrics = GlobalMetrics(
        micro_f1=_f1(micro_p, micro_r),
        macro_f1=(sum(f1s) / len(f1s)) if f1s else 0.0,
        hallucination_rate=(tot_hallucinated / tot_pred_present) if tot_pred_present else 0.0,
        evidence_accuracy=(tot_evidence_ok / tot_evidence_total) if tot_evidence_total else 0.0,
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
