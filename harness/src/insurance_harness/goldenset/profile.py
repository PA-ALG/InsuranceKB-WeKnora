"""QualityProfile：按字段的质量画像与阈值判定（019 spec Q3）。

- Q3.1 每 field_id 输出 support / value accuracy / tri-state confusion / hallucination rate /
  evidence accuracy，并绑定 baseline 运行指纹；
- Q3.2 画像版本化且可验证 golden manifest hash；hash/schema/model/prompt 任一不匹配视为 stale；
- Q3.3 全局回归阈值与字段自动化阈值，判定结果逐条列出失败指标与实际值。

画像是只读 artifact；真实 13 产品画像由 020 用同一 API 产出。
"""

from collections import Counter, defaultdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .baseline import RunFingerprint
from .normalize import quote_in_page, values_equal
from .records import GoldenRecord, TriState


class FieldMetrics(BaseModel):
    """单字段确定性指标（Q3.1）。"""

    model_config = ConfigDict(frozen=True)

    field_id: str
    support: int
    value_accuracy: float
    hallucination_rate: float
    evidence_accuracy: float
    tri_state_confusion: dict[str, int]


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
    """只读质量画像 artifact（Q3.1/Q3.2）。"""

    model_config = ConfigDict(frozen=True)

    profile_version: int
    fingerprint: RunFingerprint
    fields: dict[str, FieldMetrics]

    def field(self, field_id: str) -> FieldMetrics | None:
        return self.fields.get(field_id)

    def is_stale(self, current: RunFingerprint) -> bool:
        """Q3.2：golden hash / schema / model / prompt 任一不匹配即 stale。"""
        return (
            self.fingerprint.golden_release_hash != current.golden_release_hash
            or self.fingerprint.schema_version != current.schema_version
            or self.fingerprint.model_id != current.model_id
            or self.fingerprint.prompt_version != current.prompt_version
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
            failures.append(
                f"support={metrics.support}<{thresholds.support_min}"
            )
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
    """全局回归阈值（Q3.3/Q4.6）：候选相对已批准 baseline 不得退化超过容差。"""

    model_config = ConfigDict(frozen=True)

    max_value_accuracy_drop: float = 0.0
    max_hallucination_increase: float = 0.0


def check_regression(
    approved: QualityProfile,
    candidate: QualityProfile,
    thresholds: RegressionThresholds | None = None,
) -> FieldVerdict:
    """Q4.6：候选画像相对已批准画像的退化检查；失败列出每个退化字段与实际差值。"""
    thresholds = thresholds or RegressionThresholds()
    failures: list[str] = []
    for field_id, base in approved.fields.items():
        cand = candidate.fields.get(field_id)
        if cand is None:
            failures.append(f"{field_id}: 候选缺该字段画像")
            continue
        acc_drop = base.value_accuracy - cand.value_accuracy
        if acc_drop > thresholds.max_value_accuracy_drop:
            failures.append(
                f"{field_id}: value_accuracy 退化 {acc_drop:.3f}"
            )
        halluc_inc = cand.hallucination_rate - base.hallucination_rate
        if halluc_inc > thresholds.max_hallucination_increase:
            failures.append(
                f"{field_id}: hallucination 上升 {halluc_inc:.3f}"
            )
    return FieldVerdict(
        field_id="<regression>", eligible=not failures, failures=tuple(failures)
    )


def _evidence_verified(
    record: GoldenRecord, page_cache: dict[Path, dict[int, str]], dataset_root: Path | None
) -> bool:
    """present 预测是否有可信证据：至少一条 evidence，且有 dataset_root 时引文回验通过。"""
    if not record.evidence:
        return False
    if dataset_root is None:
        return True
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
    dataset_root: Path | None = None,
    version: int = 1,
) -> QualityProfile:
    """从 golden vs pred 逐字段派生画像（确定性；disputed 金标排除）。"""
    usable = [g for g in golden if not g.disputed]
    g_map = {(g.product_id, g.field_id): g for g in usable}
    p_map = {(p.product_id, p.field_id): p for p in pred}
    page_cache: dict[Path, dict[int, str]] = {}

    by_field_keys: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in g_map:
        by_field_keys[key[1]].append(key)

    fields: dict[str, FieldMetrics] = {}
    for field_id, keys in by_field_keys.items():
        support = len(keys)
        confusion: Counter[str] = Counter()
        value_hits = 0
        value_pairs = 0
        pred_present = 0
        hallucinated = 0
        evidence_ok = 0
        evidence_total = 0
        for key in keys:
            g = g_map[key]
            p = p_map.get(key)
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
        fields[field_id] = FieldMetrics(
            field_id=field_id,
            support=support,
            value_accuracy=(value_hits / value_pairs) if value_pairs else 1.0,
            hallucination_rate=(hallucinated / pred_present) if pred_present else 0.0,
            evidence_accuracy=(evidence_ok / evidence_total) if evidence_total else 1.0,
            tri_state_confusion=dict(confusion),
        )
    return QualityProfile(
        profile_version=version, fingerprint=fingerprint, fields=fields
    )
