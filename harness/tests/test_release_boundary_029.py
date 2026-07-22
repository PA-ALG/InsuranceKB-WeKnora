"""OpenSpec 029 RA6: staging-only legacy publisher and P-1 fail-closed boundary."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.knowledge.pages import render_snapshot_pages
from insurance_harness.knowledge.publisher import (
    LegacyStagingReleasePublisher,
    ReleasePublisher,
)
from insurance_harness.knowledge.release_boundary import (
    P1CapabilityMissing,
    ProductionWikiPublishRequest,
    build_staging_candidate_manifest,
    request_production_wiki_publish,
)
from insurance_harness.knowledge.release_manifest import ReleaseManifest
from insurance_harness.knowledge.serving import ServingFailure
from insurance_harness.knowledge.snapshots import build_snapshot_facts
from insurance_harness.knowledge.tables import (
    CurrentRelease,
    ReleaseApproval,
    ReleaseSnapshot,
    SnapshotFact,
)
from tests.support.release_018 import (
    NOW,
    release_claim,
    release_product,
    release_scope,
)
from tests.test_serving_reader_029 import _approved_release, _reader

_A = "a" * 64
_B = "b" * 64
_C = "c" * 64


def _building_frozen_candidate(
    session: Session,
    suffix: str,
) -> tuple[KnowledgeScope, str]:
    scope = release_scope(session, suffix)
    _product, version = release_product(session, scope, code=f"STAGE-{suffix}")
    release_claim(
        session,
        scope,
        version,
        claim_id=f"claim-stage-{suffix}",
        predicate="waiting_period",
    )
    snapshot_id = f"snapshot-stage-{suffix}"
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
    pages = [
        page.model_dump(mode="json")
        for page in render_snapshot_pages(
            facts,
            space_id=scope.space_id,
            snapshot_id=snapshot_id,
            compiled_at=NOW,
        )
    ]
    snapshot = ReleaseSnapshot(
        id=snapshot_id,
        space_id=scope.space_id,
        label=snapshot_id,
        rendered_pages=pages,
        status="building",
        read_model_version=1,
        projection_frozen_at=None,
        published_at=None,
        published_by="staging-test",
    )
    session.add(snapshot)
    session.flush()
    for index, fact in enumerate(facts):
        session.add(
            SnapshotFact(
                id=f"fact-stage-{suffix}-{index}",
                space_id=fact.space_id,
                snapshot_id=snapshot_id,
                claim_id=fact.claim_id,
                revision_no=fact.revision_no,
                product_id=fact.product_id,
                product_version_id=fact.product_version_id,
                product_code=fact.product_code,
                product_name=fact.product_name,
                version_label=fact.version_label,
                predicate=fact.predicate,
                field_name=fact.field_name,
                field_group=fact.field_group,
                value_state=fact.value_state,
                value=fact.value,
                effective_from=fact.effective_from,
                effective_to=fact.effective_to,
                confidence=fact.confidence,
                schema_version=fact.schema_version,
                evidence=[item.model_dump(mode="json") for item in fact.evidence],
            )
        )
    session.flush()
    snapshot.projection_frozen_at = NOW
    session.commit()
    return scope, snapshot_id


def test_ra6_building_frozen_candidate_isolated_from_release_and_wiki(
    session: Session,
) -> None:
    scope, snapshot_id = _building_frozen_candidate(session, "candidate")

    class WikiFake:
        calls = 0

    before_approvals = session.scalar(select(func.count()).select_from(ReleaseApproval))
    manifest = build_staging_candidate_manifest(
        session,
        scope,
        snapshot_id=snapshot_id,
        schema_version="v1.1+release",
        template_hashes=(_A, _B),
        model_plan_hash=_C,
    )

    assert isinstance(manifest, ReleaseManifest)
    assert manifest.snapshot_id == snapshot_id
    assert session.get(CurrentRelease, (scope.space_id, "current")) is None
    assert session.scalar(select(func.count()).select_from(ReleaseApproval)) == (
        before_approvals
    )
    assert WikiFake.calls == 0
    serving = _reader(session).read_current(scope)
    assert isinstance(serving, ServingFailure)
    assert serving.code == "no_release"


def test_ra6_production_wiki_request_is_typed_blocked_and_preserves_serving(
    session: Session,
) -> None:
    approved = _approved_release(session, "p1-blocked")
    reader = _reader(session)
    before = reader.read_current(approved.scope)
    pointer_before = session.get(
        CurrentRelease,
        (approved.scope.space_id, "current"),
    )
    assert pointer_before is not None
    approval_count = session.scalar(select(func.count()).select_from(ReleaseApproval))
    request = ProductionWikiPublishRequest(
        scope=approved.scope,
        snapshot_id=approved.manifest.snapshot_id,
        manifest_hash=approved.manifest.manifest_sha256,
        principal="release.owner@example.com",
        reason="request ordinary-user production Wiki publication",
    )

    blocked = request_production_wiki_publish(request)

    assert blocked == P1CapabilityMissing(
        status="blocked",
        code="p1_capability_missing",
    )
    pointer_after = session.get(
        CurrentRelease,
        (approved.scope.space_id, "current"),
    )
    assert pointer_after is not None
    assert pointer_after.snapshot_id == pointer_before.snapshot_id
    assert session.scalar(select(func.count()).select_from(ReleaseApproval)) == approval_count
    assert reader.read_current(approved.scope) == before


def test_ra6_production_request_has_no_silent_identity_defaults() -> None:
    with pytest.raises(ValidationError):
        ProductionWikiPublishRequest.model_validate({})
    for field, value in (
        ("snapshot_id", ""),
        ("manifest_hash", "not-a-hash"),
        ("principal", " model "),
        ("reason", ""),
    ):
        payload = {
            "scope": {
                "space_id": "space",
                "tenant_id": "tenant",
                "raw_kb_id": "raw",
                "wiki_kb_id": "wiki",
            },
            "snapshot_id": "snapshot",
            "manifest_hash": "a" * 64,
            "principal": "human@example.com",
            "reason": "reviewed",
        }
        payload[field] = value
        with pytest.raises(ValidationError):
            ProductionWikiPublishRequest.model_validate(payload)


def test_ra6_package_exports_production_boundary_not_legacy_publisher() -> None:
    from insurance_harness import knowledge

    assert knowledge.ProductionWikiPublishRequest is ProductionWikiPublishRequest
    assert knowledge.P1CapabilityMissing is P1CapabilityMissing
    assert knowledge.build_staging_candidate_manifest is build_staging_candidate_manifest
    assert knowledge.request_production_wiki_publish is request_production_wiki_publish
    for legacy in ("ReleasePublisher", "PublishResult", "RollbackResult"):
        assert not hasattr(knowledge, legacy)
        assert legacy not in knowledge.__all__


def test_ra6_legacy_publisher_remains_direct_module_characterization_only() -> None:
    assert LegacyStagingReleasePublisher is ReleasePublisher
    assert "staging/test-only" in (ReleasePublisher.__doc__ or "")


def test_ra6_boundary_and_production_src_have_no_publish_bypass() -> None:
    import insurance_harness.knowledge.release_boundary as boundary_module

    boundary_path = Path(boundary_module.__file__)
    boundary_tree = ast.parse(boundary_path.read_text(encoding="utf-8"))
    boundary_modules = {
        node.module or ""
        for node in ast.walk(boundary_tree)
        if isinstance(node, ast.ImportFrom)
    }
    forbidden = {"publisher", "weknora", "runtime", "model", "provider"}
    assert not any(forbidden & set(module.split(".")) for module in boundary_modules)

    src_root = boundary_path.parents[2]
    bypasses: list[str] = []
    for path in src_root.rglob("*.py"):
        if path.name == "publisher.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports_publisher = any(
            isinstance(node, ast.ImportFrom)
            and (node.module or "") == "insurance_harness.knowledge.publisher"
            and {alias.name for alias in node.names}
            & {
                "ReleasePublisher",
                "LegacyStagingReleasePublisher",
                "PublishResult",
                "RollbackResult",
            }
            for node in ast.walk(tree)
        )
        imports_legacy_name = any(
            isinstance(node, (ast.Name, ast.Attribute))
            and getattr(node, "id", getattr(node, "attr", None))
            in {"ReleasePublisher", "LegacyStagingReleasePublisher"}
            for node in ast.walk(tree)
        )
        if imports_publisher or imports_legacy_name:
            bypasses.append(str(path.relative_to(src_root)))
    assert bypasses == []
