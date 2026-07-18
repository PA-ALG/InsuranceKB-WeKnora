"""008 工作台测试构件：**真实服务入口造数**（PR#15 阻断 1 教训）。

主正向用例一律经 ``MergeEngine.apply_batch`` 产生 ChangeSet/ChangeItem/ReviewItem
（真实 ``proposed`` 形态：``{"claim": …}`` 嵌套等），不得手写扁平 ``proposed``。
仅并发竞态类边缘场景允许 ORM 直造，但也必须用真实嵌套形态且字段与 Claim 行
逐项一致（``seed_parallel_open_review``——模拟两条并行摄入会话都看不见对方的场景）。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope, load_scope
from insurance_harness.goldenset.baseline import (
    ApprovalRecord,
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
from insurance_harness.knowledge import (
    MergeEngine,
    MergePolicy,
    MergeReport,
    ProposedClaim,
    ProposedEvidence,
)
from insurance_harness.knowledge.quality_gate import QualityGate
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    ReviewItem,
)
from insurance_harness.schemas.models import (
    FieldSpec,
    ProductLineSchema,
    SchemaRegistry,
)
from tests.kbhelpers import seed_bound_scope, seed_product

_HEX = "a" * 64


def wb_registry() -> SchemaRegistry:
    """内联 schema 注册表：与 kbhelpers.seed_product 的 category=endowment 对齐。

    含一个**从未被抽取**的字段（never_extracted）——矩阵全字段底图断言用。
    """
    fields = (
        FieldSpec(name="等待期", field_id="waiting_period", risk_level="low"),
        FieldSpec(name="宽限期", field_id="grace_period", risk_level="low"),
        FieldSpec(name="保障范围", field_id="coverage_scope", risk_level="low"),
        FieldSpec(name="费率表", field_id="premium_rate", risk_level="high"),
        FieldSpec(name="从未抽取字段", field_id="never_extracted", risk_level="low"),
    )
    line = ProductLineSchema(
        line_key="endowment", sheet_name="两全保险", fields=fields
    )
    return SchemaRegistry(
        version="v1.1+wbtest", lines={"endowment": line}, glossary=()
    )


def bound_space(session: Session, sfx: str) -> str:
    scope = seed_bound_scope(
        session,
        tenant_id=f"tenant-{sfx}",
        raw_kb_id=f"raw-{sfx}",
        wiki_kb_id=f"wiki-{sfx}",
    )
    session.commit()
    return scope.space_id


def seed_wb_product(
    session: Session, space_id: str, code: str = "P001", name: str = "测试终身寿"
) -> str:
    scope = load_scope(session, space_id)
    _product, version = seed_product(session, scope=scope, code=code, name=name)
    session.commit()
    return str(version.id)


def make_client(
    factory: Callable[[], Session],
    space_a: str,
    *,
    extra: dict[str, object] | None = None,
    raise_server_exceptions: bool = True,
    session_secret: str | None = "wb-test-secret",
) -> TestClient:
    from insurance_harness.workbench.app import create_app

    tokens: dict[str, object] = {
        "tok-alice": {"principal": "alice", "space_ids": [space_a]},
    }
    if extra:
        tokens = {**tokens, **extra}
    return TestClient(
        create_app(
            session_factory=factory,
            tokens_config=tokens,
            schema_registry=wb_registry(),
            session_secret=session_secret,
        ),
        raise_server_exceptions=raise_server_exceptions,
    )


def current_version(session: Session, space_id: str, review_key: str) -> str:
    """读取审核项当前乐观并发版本（与页面 hidden expected_version 同源）。"""
    from sqlalchemy import select as _select

    session.expire_all()
    item = session.execute(
        _select(ReviewItem).where(
            ReviewItem.space_id == space_id,
            ReviewItem.review_key == review_key,
        )
    ).scalar_one()
    return item.updated_at.isoformat()


def post_action(
    client: TestClient,
    session: Session,
    space_id: str,
    review_key: str,
    action: str,
    *,
    reason: str | None = None,
    headers: dict[str, str] | None = None,
    csrf: str | None = None,
    expected_version: str | None = None,
    request_id: str | None = None,
    extra: dict[str, str] | None = None,
    follow_redirects: bool = False,
) -> Response:
    """W1 强制并发合同（codex R2-P1）下的动作提交：默认取**最新真实版本**再提交。

    正向用例不得再走"省略版本也成功"的路径；stale/缺失场景用
    ``expected_version``/``request_id`` 显式覆盖。
    """
    from uuid import uuid4

    if expected_version is None:
        expected_version = current_version(session, space_id, review_key)
    data: dict[str, str] = {
        "action": action,
        "expected_version": expected_version,
        "request_id": request_id or uuid4().hex,
    }
    if reason is not None:
        data["reason"] = reason
    if csrf is not None:
        data["csrf_token"] = csrf
    if extra:
        data = {**data, **extra}
    return cast(
        Response,
        client.post(
            f"/spaces/{space_id}/queue/{review_key}/action",
            headers=headers,
            data=data,
            follow_redirects=follow_redirects,
        ),
    )


def prop(
    scope: KnowledgeScope,
    version_id: str,
    predicate: str = "waiting_period",
    *,
    value: str | None = "90天",
    value_state: str = "present",
    doc_role: str = "official_desc",
    authority: int = 2,
    knowledge_id: str = "doc-brochure",
    quote: str = "等待期为90天",
    page: int = 3,
    confidence: float = 0.9,
    pending_judge: bool = False,
    with_evidence: bool = True,
) -> ProposedClaim:
    return ProposedClaim(
        space_id=scope.space_id,
        product_version_id=version_id,
        predicate=predicate,
        field_name=predicate,
        value_state=value_state,  # type: ignore[arg-type]
        value=value,
        confidence=confidence,
        pending_judge=pending_judge,
        evidence=(
            [
                ProposedEvidence(
                    knowledge_id=knowledge_id,
                    doc_title=knowledge_id,
                    quote=quote,
                    page=page,
                    doc_role=doc_role,
                    authority_level=authority,
                )
            ]
            if with_evidence
            else []
        ),
    )


def run_merge(
    session: Session,
    space_id: str,
    props: list[ProposedClaim],
    *,
    external_id: str,
    policy: MergePolicy | None = None,
    quality_gate: QualityGate | None = None,
    run_fingerprint: RunFingerprint | None = None,
    risk_of: Callable[[str], str] | None = None,
) -> MergeReport:
    """真实入口造数：一批提案经 MergeEngine 走完整合并（含 ReviewItem/Conflict）。"""
    scope = load_scope(session, space_id)
    engine = MergeEngine(
        session,
        scope=scope,
        policy=policy,
        quality_gate=quality_gate,
        run_fingerprint=run_fingerprint,
        risk_of=risk_of,
    )
    change_set, _ = engine.open_change_set(
        source_kind="document", external_record_id=external_id
    )
    report = engine.apply_batch(change_set, props)
    session.commit()
    return report


def open_review_key(
    session: Session,
    space_id: str,
    version_id: str,
    predicate: str = "waiting_period",
    *,
    value: str | None = "90天",
    external_id: str | None = None,
    risk: str = "low",
) -> str:
    """默认保守策略（全走审核）下造一条 open 审核项，返回 review_key。"""
    scope = load_scope(session, space_id)
    report = run_merge(
        session,
        space_id,
        [prop(scope, version_id, predicate, value=value)],
        external_id=external_id or f"doc-{predicate}",
        risk_of=(lambda _p: risk),
    )
    assert report.review_keys, "保守策略下 add 必产生审核项"
    return report.review_keys[0]


def seed_parallel_open_review(
    session: Session,
    space_id: str,
    version_id: str,
    predicate: str,
    *,
    key: str,
    value: str = "90天",
    with_evidence: bool = True,
    risk: str = "low",
) -> str:
    """并行摄入竞态种子（仅供边缘场景）：真实嵌套 ``proposed={"claim": …}`` 形态，
    Claim 行与提案逐字段一致（能通过 ``_require_claim_matches_proposal``）。

    模拟两条并行会话各自都看不见对方 candidate 的场景——顺序 MergeEngine 会把
    第二条同谓词提案并入裁决路径，无法造出"同字段两条独立 open add"。
    """
    scope = load_scope(session, space_id)
    proposal = prop(
        scope, version_id, predicate, value=value, with_evidence=with_evidence
    )
    claim = Claim(
        space_id=proposal.space_id,
        subject_type="product_version",
        product_version_id=proposal.product_version_id,
        predicate=proposal.predicate,
        value_state=proposal.value_state,
        value=None if proposal.value is None else {"text": proposal.value},
        effective_from=proposal.effective_from,
        status="candidate",
        confidence=proposal.confidence,
        extraction_method=proposal.extraction_method,
        schema_version=proposal.schema_version,
        pending_judge=proposal.pending_judge,
    )
    session.add(claim)
    session.flush()
    for e in proposal.evidence:
        session.add(
            ClaimEvidence(
                claim_id=claim.id,
                knowledge_id=e.knowledge_id,
                quote=e.quote,
                page=e.page,
                doc_role=e.doc_role,
                authority_level=e.authority_level,
                extraction_method=e.extraction_method,
            )
        )
    session.flush()
    change_set = ChangeSet(
        space_id=scope.space_id,
        source_kind="document",
        external_record_id=f"parallel-{key}",
        status="pending",
        created_by="parallel-ingest",
    )
    session.add(change_set)
    session.flush()
    item = ChangeItem(
        change_set_id=change_set.id,
        action="add",
        claim_id=claim.id,
        proposed={"claim": proposal.model_dump(mode="json")},  # 真实嵌套形态
        decision="needs_review",
    )
    session.add(item)
    session.flush()
    review = ReviewItem(
        space_id=scope.space_id,
        review_key=key,
        type="low_confidence",
        subject={
            "change_item_id": item.id,
            "new_claim_id": claim.id,
            "predicate": predicate,
        },
        allowed_actions=["approve", "reject", "defer"],
        status="open",
        risk_level=risk,
    )
    session.add(review)
    session.commit()
    return key


# ------------------------------------------------------------------ 真实 gate 变体


def _fingerprint(**overrides: str) -> RunFingerprint:
    base = dict(
        git_sha="wb-sha", schema_version="v1.1+wbtest", model_id="wb-model",
        prompt_version="p1", template_profile="t1", source_profile="s1",
        golden_release_hash=_HEX,
    )
    base.update(overrides)
    return RunFingerprint(**base)


def _approved_profile(
    fp: RunFingerprint, fields: dict[str, FieldMetrics]
) -> tuple[QualityProfile, ApprovalRecord]:
    shas = {k: _HEX for k in (
        "run_manifest", "pred", "dead_letter", "judge_queue", "judgements",
        "keypoints", "eval_report",
    )}
    artifact = BaselineArtifact(
        baseline_id="wb-baseline",
        fingerprint=fp,
        products=(build_product_artifacts("P1", shas=shas, pred_count=12),),
    )
    candidate = QualityProfile(
        profile_version="1", artifact_sha256=artifact.sha256(),
        baseline_approval_sha256="", fingerprint=fp, fields=fields,
        global_metrics=GlobalMetrics(
            micro_f1=1.0, macro_f1=1.0, hallucination_rate=0.0,
            evidence_accuracy=1.0,
        ),
    )
    approval = approve_baseline(
        artifact, candidate, approved_by="wb-test",
        approved_at=datetime(2026, 7, 14, tzinfo=UTC),
    )
    return candidate.with_approval(approval), approval


def real_gate(
    kind: str, predicates: tuple[str, ...] = ("waiting_period",)
) -> tuple[QualityGate, RunFingerprint]:
    """真实 QualityGate 的三类拒绝（W7 测试禁手造 quality_gate 工单）：

    - ``missing``：无画像（缺字段画像）
    - ``stale``：画像指纹 ≠ 当前 run 指纹
    - ``threshold``：画像存在但指标不达阈值
    - ``passing``：达标（对照组，可自动发布）
    """
    fp = _fingerprint()
    if kind == "missing":
        return QualityGate(None, approval=None), fp
    good = {
        p: FieldMetrics(
            field_id=p, support=12, value_accuracy=1.0, hallucination_rate=0.0,
            evidence_accuracy=1.0, precision=1.0, recall=1.0, f1=1.0,
            tri_state_confusion={},
        )
        for p in predicates
    }
    if kind == "threshold":
        bad = {
            p: FieldMetrics(
                field_id=p, support=12, value_accuracy=0.5, hallucination_rate=0.0,
                evidence_accuracy=1.0, precision=1.0, recall=1.0, f1=1.0,
                tri_state_confusion={},
            )
            for p in predicates
        }
        profile, approval = _approved_profile(fp, bad)
        return QualityGate(profile, approval=approval), fp
    profile, approval = _approved_profile(fp, good)
    if kind == "stale":
        return QualityGate(profile, approval=approval), _fingerprint(
            model_id="other-model"
        )
    if kind == "passing":
        return QualityGate(profile, approval=approval), fp
    raise ValueError(f"unknown gate kind {kind!r}")
