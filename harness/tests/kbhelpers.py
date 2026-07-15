"""change 007 测试构件：产品种子与 PredRecord 工厂（specs K2~K6）。"""

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from insurance_harness.compiler.models import Confidence, PredRecord
from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.db.scope import KnowledgeScope, load_scope
from insurance_harness.goldenset.baseline import (
    BaselineArtifact,
    RunFingerprint,
    approve_baseline,
    build_product_artifacts,
)
from insurance_harness.goldenset.profile import (
    FieldMetrics,
    GlobalMetrics,
    QualityProfile,
)
from insurance_harness.goldenset.records import Evidence, TriState
from insurance_harness.knowledge.quality_gate import GateDecision, QualityGate

BROCHURE = "产品说明书.pdf"  # official_desc，权威 2
TERMS = "保险条款.pdf"  # terms，权威 1

_HEX = "a" * 64
_AT = datetime(2026, 7, 14, tzinfo=UTC)


def green_gate(
    predicates: Iterable[str],
) -> tuple[QualityGate, RunFingerprint]:
    """测试用绿灯闸门 + 指纹（019 fail-closed 后自动发布必须过 gate）。

    构造一条**完整可批准**的链：valid artifact → 达标候选画像 → approve → 已批准画像，
    gate 校验画像回链该批准且同一 artifact，故低风险 add/enrich/supersede 会被判 eligible。
    """
    fp = RunFingerprint(
        git_sha="test-sha", schema_version="v1.1+test", model_id="test-model",
        prompt_version="p1", template_profile="tpl1", source_profile="src1",
        golden_release_hash="rh-test",
    )
    shas = {k: _HEX for k in (
        "run_manifest", "pred", "dead_letter", "judge_queue", "judgements",
        "keypoints", "eval_report",
    )}
    product = build_product_artifacts("P1", shas=shas, pred_count=12)
    artifact = BaselineArtifact(baseline_id="test-baseline", fingerprint=fp, products=(product,))
    fields = {
        p: FieldMetrics(
            field_id=p, support=12, value_accuracy=1.0, hallucination_rate=0.0,
            evidence_accuracy=1.0, precision=1.0, recall=1.0, f1=1.0, tri_state_confusion={},
        )
        for p in set(predicates)
    }
    candidate = QualityProfile(
        profile_version="1", artifact_sha256=artifact.sha256(),
        baseline_approval_sha256="", fingerprint=fp, fields=fields,
        global_metrics=GlobalMetrics(
            micro_f1=1.0, macro_f1=1.0, hallucination_rate=0.0, evidence_accuracy=1.0,
        ),
    )
    approval = approve_baseline(artifact, candidate, approved_by="test", approved_at=_AT)
    approved = candidate.with_approval(approval)
    return QualityGate(approved, approval=approval), fp


class _AllowLowRiskGate(QualityGate):
    """测试替身：低风险且可自动化的动作放行；仍拒绝高风险/不可自动化，保持真实 gate 安全语义。

    供**不针对 gate 本身**、只需"自动化已获批"前置数据的合并/发布测试做种子。真实 gate 的
    画像/批准/staleness/阈值判定由 test_quality_gate_019.py 用真实画像全覆盖。
    """

    def __init__(self) -> None:  # 无需画像/批准
        pass

    def decide(
        self, field_id: str, risk: str, action: str, run_fingerprint: object
    ) -> "GateDecision":
        from insurance_harness.knowledge.quality_gate import (
            _AUTOMATABLE_ACTIONS,
            GateDecision,
        )

        if action not in _AUTOMATABLE_ACTIONS:
            return GateDecision(
                eligible=False, reason=f"动作 {action} 不可自动化",
                field_id=field_id, action=action,
            )
        if risk != "low":
            return GateDecision(
                eligible=False, reason=f"风险 {risk} 非 low",
                field_id=field_id, action=action,
            )
        return GateDecision(
            eligible=True, reason="测试替身放行", field_id=field_id, action=action
        )


def allow_all_gate() -> tuple[QualityGate, RunFingerprint]:
    """返回 (低风险放行的测试替身 gate, 任意匹配指纹)。用于种子发布，不测 gate 本身。"""
    fp = RunFingerprint(
        git_sha="test-sha", schema_version="v1.1+test", model_id="test-model",
        prompt_version="p1", template_profile="tpl1", source_profile="src1",
        golden_release_hash="rh-test",
    )
    return _AllowLowRiskGate(), fp


def seed_bound_scope(
    session: Session,
    *,
    tenant_id: str,
    raw_kb_id: str,
    wiki_kb_id: str,
) -> KnowledgeScope:
    from insurance_harness.db.models import KnowledgeSpace

    space = KnowledgeSpace(
        name=f"{tenant_id}:{raw_kb_id}:{wiki_kb_id}",
        binding_status="bound",
        tenant_id=tenant_id,
        raw_kb_id=raw_kb_id,
        wiki_kb_id=wiki_kb_id,
    )
    session.add(space)
    session.flush()
    return load_scope(session, space.id)


def seed_product(
    session: Session,
    *,
    scope: KnowledgeScope,
    code: str = "AXB001",
    name: str = "安心保两全保险",
    version_label: str = "2024版",
) -> tuple[InsuranceProduct, ProductVersion]:
    product = InsuranceProduct(
        space_id=scope.space_id,
        product_code=code,
        canonical_name=name,
        category="endowment",
        status="在售",
    )
    session.add(product)
    session.flush()
    version = ProductVersion(
        space_id=scope.space_id,
        product_id=product.id,
        version_label=version_label,
    )
    session.add(version)
    session.flush()
    return product, version


def pred(
    field_id: str,
    *,
    value: str | None,
    tri_state: TriState = "present",
    doc: str = BROCHURE,
    page: int = 3,
    quote: str | None = None,
    field_name: str | None = None,
    confidence: Confidence = "high",
    pending_judge: bool = False,
) -> PredRecord:
    evidence = (
        []
        if tri_state == "unknown" or quote is None
        else [Evidence(page=page, quote=quote)]
    )
    return PredRecord(
        product_id="AXB001",
        product_name="安心保两全保险",
        doc=doc,
        field_id=field_id,
        field_name=field_name or field_id,
        value=value,
        tri_state=tri_state,
        evidence=evidence,
        annotator_model="test-fixture",
        schema_version="v1.1+test",
        created_at=datetime.now(UTC),
        confidence=confidence,
        pending_judge=pending_judge,
    )
