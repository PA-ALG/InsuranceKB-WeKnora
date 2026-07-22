"""OpenSpec 029 RA4: approved, hash-bound frozen serving contract."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from insurance_harness.db.base import make_session_factory
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.knowledge.release_approval import (
    AuthorizationDecision,
    ReleaseApprovalService,
    persist_release_manifest,
)
from insurance_harness.knowledge.release_authority import (
    ReleaseActivationSuccess,
    ReleaseAuthorityService,
)
from insurance_harness.knowledge.release_manifest import (
    ReleaseManifest,
    build_release_manifest_from_snapshot,
)
from insurance_harness.knowledge.serving import (
    ApprovedSnapshotReader,
    ApprovedSnapshotResult,
    CanonicalServingFact,
    ServingDocumentEvidence,
    ServingFailure,
    ServingStructuredEvidence,
)
from insurance_harness.knowledge.snapshots import build_snapshot_facts
from insurance_harness.knowledge.tables import (
    Claim,
    ClaimEvidence,
    CurrentRelease,
    ReleaseApproval,
)
from tests.support.release_018 import (
    NOW,
    persist_release_snapshot,
    release_claim,
    release_product,
    release_scope,
)

_A = "a" * 64
_B = "b" * 64
_C = "c" * 64


class _Authorizer:
    def authorize(self, **request: object) -> AuthorizationDecision:
        return AuthorizationDecision(
            outcome="authorized",
            space_id=str(request["space_id"]),
            actor=str(request["actor"]),
            actor_type=str(request["actor_type"]),
            role="release_approver",
            manifest_hash=str(request["manifest_hash"]),
            authorization_receipt=str(request["authorization_receipt"]),
        )


@dataclass(frozen=True)
class _ApprovedFixture:
    scope: KnowledgeScope
    manifest: ReleaseManifest
    product_a_id: str
    version_a_id: str
    product_b_id: str
    version_b_id: str
    waiting_claim_id: str
    limited_claim_id: str


def _reader(session: Session) -> ApprovedSnapshotReader:
    bind = session.get_bind()
    assert isinstance(bind, Engine)
    return ApprovedSnapshotReader(make_session_factory(bind))


def _approve(
    session: Session,
    scope: KnowledgeScope,
    manifest: ReleaseManifest,
) -> ReleaseApproval:
    approval = ReleaseApprovalService(session, _Authorizer()).approve(
        scope,
        snapshot_id=manifest.snapshot_id,
        manifest_hash=manifest.manifest_sha256,
        actor="release.owner@example.com",
        actor_type="human",
        authorization_receipt="iam:release-owner:029",
        reason="reviewed exact serving manifest",
    )
    session.commit()
    return approval


def _persist_manifest(
    session: Session,
    scope: KnowledgeScope,
    *,
    snapshot_id: str,
) -> ReleaseManifest:
    manifest = build_release_manifest_from_snapshot(
        session,
        scope,
        snapshot_id=snapshot_id,
        schema_version="v1.1+release",
        template_hashes=(_A, _B),
        model_plan_hash=_C,
    )
    persist_release_manifest(session, scope, manifest)
    session.commit()
    return manifest


def _approved_release(
    session: Session,
    suffix: str = "serving",
    *,
    unknown_waiting_fact: bool = False,
) -> _ApprovedFixture:
    scope = release_scope(session, suffix)
    product_a, version_a = release_product(session, scope, code=f"A-{suffix}")
    product_b, version_b = release_product(session, scope, code=f"B-{suffix}")
    waiting_claim, first_evidence = release_claim(
        session,
        scope,
        version_a,
        claim_id=f"claim-waiting-{suffix}",
        predicate="waiting_period",
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
    )
    assert first_evidence is not None
    session.add(
        ClaimEvidence(
            id=f"evidence-000-{suffix}",
            claim_id=waiting_claim.id,
            knowledge_id=f"knowledge-000-{suffix}",
            chunk_id=f"chunk-000-{suffix}",
            quote="earlier stable source",
            page=1,
            section="总则",
            table_ref=None,
            timestamp_ms=None,
            authority_level=1,
            doc_role="terms",
            extraction_method="llm",
            extracted_at=NOW,
            raw_kb_id=scope.raw_kb_id,
            source_revision="0" * 64,
            file_hash="1" * 64,
            original_digest="2" * 64,
            parser_version="parser/1",
            chunk_hash="3" * 64,
            lineage_status="linked",
            stale_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    limited_claim, _ = release_claim(
        session,
        scope,
        version_a,
        claim_id=f"claim-limited-{suffix}",
        predicate="limited_period",
        effective_from=date(2026, 3, 1),
        effective_to=date(2026, 3, 31),
    )
    release_claim(
        session,
        scope,
        version_b,
        claim_id=f"claim-hesitation-{suffix}",
        predicate="hesitation_period",
    )
    snapshot_id = f"snapshot-{suffix}"
    facts = [
        fact.model_copy(
            update={
                "evidence": tuple(
                    evidence.model_copy(
                        update={
                            "extracted_at": NOW,
                            "created_at": NOW,
                            "updated_at": NOW,
                        }
                    )
                    for evidence in fact.evidence
                )
            }
        )
        for fact in build_snapshot_facts(session, scope, snapshot_id=snapshot_id)
    ]
    if unknown_waiting_fact:
        facts = [
            fact.model_copy(update={"value_state": "unknown", "value": None})
            if fact.claim_id == waiting_claim.id
            else fact
            for fact in facts
        ]
    persist_release_snapshot(
        session,
        scope,
        snapshot_id=snapshot_id,
        facts=facts,
        make_current=False,
    )
    manifest = _persist_manifest(session, scope, snapshot_id=snapshot_id)
    _approve(session, scope, manifest)
    activated = ReleaseAuthorityService(session).promote(
        scope,
        snapshot_id=snapshot_id,
        manifest_hash=manifest.manifest_sha256,
        expected_current_snapshot_id=None,
        reason="activate approved serving snapshot",
    )
    assert isinstance(activated, ReleaseActivationSuccess)
    session.commit()
    return _ApprovedFixture(
        scope=scope,
        manifest=manifest,
        product_a_id=product_a.id,
        version_a_id=version_a.id,
        product_b_id=product_b.id,
        version_b_id=version_b.id,
        waiting_claim_id=waiting_claim.id,
        limited_claim_id=limited_claim.id,
    )


def test_ra4_approved_current_returns_strict_hash_bound_canonical_facts(
    session: Session,
) -> None:
    approved = _approved_release(session, "success")

    result = _reader(session).read_current(approved.scope)

    assert isinstance(result, ApprovedSnapshotResult)
    assert result.snapshot_id == approved.manifest.snapshot_id
    assert result.manifest_hash == approved.manifest.manifest_sha256
    assert result.approval_principal == "release.owner@example.com"
    assert result.approved_at.tzinfo is not None
    assert result.read_model_version == 1
    assert len(result.facts) == 3
    keys = [
        (
            fact.product_id,
            fact.product_version_id,
            fact.predicate,
            fact.effective_from or date.min,
            fact.effective_to or date.max,
            fact.claim_id,
            fact.revision_no,
        )
        for fact in result.facts
    ]
    assert keys == sorted(keys)
    waiting = next(fact for fact in result.facts if fact.claim_id == approved.waiting_claim_id)
    evidence_keys = [
        (
            item.kind,
            item.raw_kb_id,
            item.knowledge_id,
            item.source_revision,
            item.file_hash,
            item.chunk_id or "",
            item.id,
        )
        for item in waiting.evidence
        if isinstance(item, ServingDocumentEvidence)
    ]
    assert evidence_keys == sorted(evidence_keys)
    with pytest.raises(Exception, match="frozen"):
        result.snapshot_id = "changed"


def test_ra4_unknown_in_approved_snapshot_is_a_successful_fact(
    session: Session,
) -> None:
    approved = _approved_release(
        session,
        "unknown",
        unknown_waiting_fact=True,
    )

    result = _reader(session).read_current(
        approved.scope,
        claim_id=approved.waiting_claim_id,
    )

    assert isinstance(result, ApprovedSnapshotResult)
    assert result.snapshot_id == approved.manifest.snapshot_id
    assert result.manifest_hash == approved.manifest.manifest_sha256
    assert len(result.facts) == 1
    assert result.facts[0].value_state == "unknown"
    assert result.facts[0].value is None


def test_ra4_filters_are_exact_composable_and_have_fixed_gap_precedence(
    session: Session,
) -> None:
    approved = _approved_release(session, "filters")
    reader = _reader(session)

    combined = reader.read_current(
        approved.scope,
        product_id=approved.product_a_id,
        product_version_id=approved.version_a_id,
        predicates=("limited_period", "waiting_period"),
        effective_on=date(2026, 3, 15),
        claim_id=approved.limited_claim_id,
    )
    assert isinstance(combined, ApprovedSnapshotResult)
    assert [fact.claim_id for fact in combined.facts] == [approved.limited_claim_id]
    product_only = reader.read_current(
        approved.scope,
        product_id=approved.product_b_id,
    )
    version_only = reader.read_current(
        approved.scope,
        product_version_id=approved.version_a_id,
    )
    predicate_only = reader.read_current(
        approved.scope,
        predicates=("hesitation_period",),
    )
    date_only = reader.read_current(
        approved.scope,
        effective_on=date(2026, 3, 31),
    )
    claim_only = reader.read_current(
        approved.scope,
        claim_id=approved.waiting_claim_id,
    )
    assert isinstance(product_only, ApprovedSnapshotResult)
    assert {fact.product_id for fact in product_only.facts} == {approved.product_b_id}
    assert isinstance(version_only, ApprovedSnapshotResult)
    assert {fact.product_version_id for fact in version_only.facts} == {
        approved.version_a_id
    }
    assert isinstance(predicate_only, ApprovedSnapshotResult)
    assert {fact.predicate for fact in predicate_only.facts} == {"hesitation_period"}
    assert isinstance(date_only, ApprovedSnapshotResult)
    assert approved.limited_claim_id in {fact.claim_id for fact in date_only.facts}
    assert isinstance(claim_only, ApprovedSnapshotResult)
    assert [fact.claim_id for fact in claim_only.facts] == [approved.waiting_claim_id]

    common = {
        "snapshot_id": approved.manifest.snapshot_id,
        "manifest_hash": approved.manifest.manifest_sha256,
    }
    assert reader.read_current(
        approved.scope,
        product_id="missing-product",
        predicates=("missing",),
        effective_on=date(1900, 1, 1),
        claim_id="missing-claim",
    ) == ServingFailure(code="product_not_found", **common)
    assert reader.read_current(
        approved.scope,
        product_id=approved.product_a_id,
        predicates=("missing",),
        effective_on=date(1900, 1, 1),
        claim_id="missing-claim",
    ) == ServingFailure(code="predicate_not_found", **common)
    assert reader.read_current(
        approved.scope,
        product_id=approved.product_a_id,
        predicates=("limited_period",),
        effective_on=date(2027, 1, 1),
        claim_id="missing-claim",
    ) == ServingFailure(code="effective_date_miss", **common)
    assert reader.read_current(
        approved.scope,
        product_id=approved.product_a_id,
        predicates=("waiting_period",),
        effective_on=date(2026, 3, 15),
        claim_id="missing-claim",
    ) == ServingFailure(code="claim_not_found", **common)


@pytest.mark.parametrize(
    "predicates",
    [(), ("",), (" waiting_period",), ("waiting_period", "waiting_period")],
)
def test_ra4_invalid_predicate_requests_raise_value_error(
    session: Session,
    predicates: tuple[str, ...],
) -> None:
    approved = _approved_release(session, f"invalid-{len(predicates)}")

    with pytest.raises(ValueError, match="predicates"):
        _reader(session).read_current(approved.scope, predicates=predicates)


def test_ra4_authority_chain_maps_every_noncoverage_failure_code(session: Session) -> None:
    empty_scope = release_scope(session, "no-release")
    session.commit()
    assert _reader(session).read_current(empty_scope) == ServingFailure(code="no_release")

    unsupported_scope = release_scope(session, "unsupported")
    persist_release_snapshot(
        session,
        unsupported_scope,
        snapshot_id="snapshot-unsupported",
        read_model_version=0,
        make_current=False,
    )
    session.execute(text("DROP TRIGGER trg_current_release_insert_guard_018"))
    session.add(
        CurrentRelease(
            space_id=unsupported_scope.space_id,
            id="current",
            snapshot_id="snapshot-unsupported",
        )
    )
    session.commit()
    assert _reader(session).read_current(unsupported_scope) == ServingFailure(
        code="unsupported_read_model",
        snapshot_id="snapshot-unsupported",
    )

    missing_scope = release_scope(session, "manifest-missing")
    persist_release_snapshot(
        session,
        missing_scope,
        snapshot_id="snapshot-manifest-missing",
    )
    assert _reader(session).read_current(missing_scope) == ServingFailure(
        code="manifest_missing",
        snapshot_id="snapshot-manifest-missing",
    )

    approval_scope = release_scope(session, "approval-missing")
    product, version = release_product(session, approval_scope, code="NO-APPROVAL")
    release_claim(
        session,
        approval_scope,
        version,
        claim_id="claim-no-approval",
        predicate="waiting_period",
    )
    facts = [
        fact.model_copy(
            update={
                "evidence": tuple(
                    evidence.model_copy(
                        update={
                            "extracted_at": NOW,
                            "created_at": NOW,
                            "updated_at": NOW,
                        }
                    )
                    for evidence in fact.evidence
                )
            }
        )
        for fact in build_snapshot_facts(
            session,
            approval_scope,
            snapshot_id="snapshot-approval-missing",
        )
    ]
    persist_release_snapshot(
        session,
        approval_scope,
        snapshot_id="snapshot-approval-missing",
        facts=facts,
    )
    manifest = _persist_manifest(
        session,
        approval_scope,
        snapshot_id="snapshot-approval-missing",
    )
    assert product.id
    assert _reader(session).read_current(approval_scope) == ServingFailure(
        code="approval_missing",
        snapshot_id=manifest.snapshot_id,
        manifest_hash=manifest.manifest_sha256,
    )


def test_ra4_manifest_drift_fails_closed_with_safe_identity(session: Session) -> None:
    approved = _approved_release(session, "drift")
    session.execute(text("DROP TRIGGER trg_snapshot_facts_update_guard_018"))
    session.execute(
        text("UPDATE snapshot_facts SET value=:value WHERE claim_id=:claim"),
        {"value": json.dumps({"text": "tampered"}), "claim": approved.waiting_claim_id},
    )
    session.commit()

    assert _reader(session).read_current(approved.scope) == ServingFailure(
        code="manifest_mismatch",
        snapshot_id=approved.manifest.snapshot_id,
        manifest_hash=approved.manifest.manifest_sha256,
    )


def test_ra4_scope_mismatch_and_foreign_filters_never_leak_other_space(
    session: Session,
) -> None:
    approved = _approved_release(session, "scope-a")
    foreign = _approved_release(session, "scope-b")
    forged = KnowledgeScope(**approved.scope.model_dump())

    assert _reader(session).read_current(forged) == ServingFailure(code="scope_mismatch")
    result = _reader(session).read_current(
        approved.scope,
        product_id=foreign.product_a_id,
        product_version_id=foreign.version_a_id,
        claim_id=foreign.waiting_claim_id,
    )
    assert isinstance(result, ServingFailure)
    assert result.code == "product_not_found"
    assert foreign.manifest.snapshot_id not in result.model_dump_json()


def test_ra4_corrupt_cross_space_pointer_returns_identity_free_scope_failure(
    session: Session,
) -> None:
    approved = _approved_release(session, "pointer-a")
    foreign = _approved_release(session, "pointer-b")
    bind = session.get_bind()
    assert isinstance(bind, Engine)
    session.commit()
    with bind.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.exec_driver_sql("DROP TRIGGER trg_current_release_update_guard_018")
        connection.execute(
            text(
                "UPDATE current_release SET snapshot_id=:foreign_snapshot "
                "WHERE space_id=:space"
            ),
            {
                "foreign_snapshot": foreign.manifest.snapshot_id,
                "space": approved.scope.space_id,
            },
        )
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()

    result = _reader(session).read_current(approved.scope)

    assert result == ServingFailure(code="scope_mismatch")
    assert foreign.manifest.snapshot_id not in result.model_dump_json()


def test_ra4_mutable_claim_changes_do_not_change_approved_serving_fact(
    session: Session,
) -> None:
    approved = _approved_release(session, "immutable")
    before = _reader(session).read_current(
        approved.scope,
        claim_id=approved.waiting_claim_id,
    )
    assert isinstance(before, ApprovedSnapshotResult)
    claim = session.get(Claim, approved.waiting_claim_id)
    assert claim is not None
    claim.value = {"text": "mutable claim changed"}
    session.commit()

    after = _reader(session).read_current(
        approved.scope,
        claim_id=approved.waiting_claim_id,
    )
    assert after == before


def test_ra4_document_and_structured_evidence_are_strict_discriminated_dtos() -> None:
    structured = ServingStructuredEvidence(
        kind="structured",
        id="structured-evidence-1",
        claim_id="claim-1",
        source_system="official-catalog",
        source_record_id="record-42",
        source_revision="revision-7",
        source_locator="$.products[42]",
        source_hash="f" * 64,
        mapping_version="mapping/v3",
    )
    document = ServingDocumentEvidence(
        kind="document",
        id="document-evidence-1",
        claim_id="claim-1",
        knowledge_id="knowledge-1",
        doc_title="保险条款",
        chunk_id="chunk-1",
        quote="等待期90天",
        page=3,
        section="保险责任",
        table_ref=None,
        timestamp_ms=None,
        authority_level=1,
        doc_role="terms",
        extraction_method="llm",
        extracted_at=datetime(2026, 7, 1, tzinfo=UTC),
        raw_kb_id="raw-1",
        source_revision="a" * 64,
        file_hash="b" * 64,
        original_digest="c" * 64,
        parser_version="parser/1",
        chunk_hash="d" * 64,
        lineage_status="linked",
        stale_at=None,
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        updated_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    fact = CanonicalServingFact(
        claim_id="claim-1",
        revision_no=1,
        product_id="product-1",
        product_version_id="version-1",
        product_code="P-1",
        product_name="产品1",
        version_label="V1",
        predicate="waiting_period",
        field_name="等待期",
        field_group="基础规则",
        value_state="unknown",
        value=None,
        effective_from=None,
        effective_to=None,
        confidence=0.9,
        schema_version="v1.1+release",
        evidence=(structured, document),
    )

    dumped = fact.model_dump(mode="json")
    assert dumped["value_state"] == "unknown"
    assert [item["kind"] for item in dumped["evidence"]] == ["document", "structured"]
    assert "page" not in dumped["evidence"][1]
    assert "chunk_id" not in dumped["evidence"][1]


def test_ra4_serving_value_is_recursively_deep_immutable_and_serializes_stably() -> None:
    evidence = ServingStructuredEvidence(
        kind="structured",
        id="structured-immutable",
        claim_id="claim-immutable",
        source_system="official-catalog",
        source_record_id="record-immutable",
        source_revision="revision-1",
        source_locator="$.record",
        source_hash="e" * 64,
        mapping_version="mapping/v1",
    )
    fact = CanonicalServingFact(
        claim_id="claim-immutable",
        revision_no=1,
        product_id="product-immutable",
        product_version_id="version-immutable",
        product_code="IMMUTABLE",
        product_name="深冻结",
        version_label="V1",
        predicate="structured_value",
        field_name="结构值",
        field_group="测试",
        value_state="present",
        value={"nested": {"answer": 42}, "array": [{"item": "stable"}]},
        effective_from=None,
        effective_to=None,
        confidence=1.0,
        schema_version="v1.1+release",
        evidence=(evidence,),
    )
    result = ApprovedSnapshotResult(
        snapshot_id="snapshot-immutable",
        manifest_hash="f" * 64,
        approval_principal="release.owner@example.com",
        approved_at=datetime(2026, 7, 22, tzinfo=UTC),
        read_model_version=1,
        facts=(fact,),
    )
    before = result.model_dump_json()
    before_hash = hashlib.sha256(before.encode()).hexdigest()
    root = fact.value
    nested = root["nested"]
    array = root["array"]

    for target in (root, nested, array[0]):
        for attribute, replacement in (
            ("_values", {"tampered": True}),
            ("_items", ("tampered",)),
        ):
            with pytest.raises((AttributeError, TypeError), match="immutable"):
                setattr(target, attribute, replacement)
    with pytest.raises(TypeError):
        array[0] = {"item": "tampered"}

    after = result.model_dump_json()
    assert after == before
    assert hashlib.sha256(after.encode()).hexdigest() == before_hash
    assert result.model_dump(mode="json")["facts"][0]["value"] == {
        "array": [{"item": "stable"}],
        "nested": {"answer": 42},
    }


def test_ra4_human_and_agent_use_same_public_dto_method(session: Session) -> None:
    approved = _approved_release(session, "same-contract")
    reader = _reader(session)

    human_result = reader.read_current(approved.scope)
    agent_result = reader.read_current(approved.scope)

    assert human_result == agent_result
    assert isinstance(human_result, ApprovedSnapshotResult)
    assert set(vars(ApprovedSnapshotReader)) & {"read_current"} == {"read_current"}


def test_ra4_serving_module_has_no_mutable_claim_query_or_forbidden_import() -> None:
    import insurance_harness.knowledge.serving as serving_module

    tree = ast.parse(Path(serving_module.__file__).read_text(encoding="utf-8"))
    imported_names = {
        alias.asname or alias.name.rsplit(".", 1)[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    imported_modules = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert "Claim" not in imported_names
    assert "ClaimEvidence" not in imported_names
    forbidden = {"runtime", "model", "provider", "publisher", "mcp", "workbench"}
    assert not any(forbidden & set(module.split(".")) for module in imported_modules)


def test_ra4_public_knowledge_package_exports_exact_serving_contract() -> None:
    from insurance_harness import knowledge

    assert knowledge.ApprovedSnapshotReader is ApprovedSnapshotReader
    assert knowledge.ApprovedSnapshotResult is ApprovedSnapshotResult
    assert knowledge.CanonicalServingFact is CanonicalServingFact
    assert knowledge.ServingDocumentEvidence is ServingDocumentEvidence
    assert knowledge.ServingStructuredEvidence is ServingStructuredEvidence
    assert knowledge.ServingFailure is ServingFailure
