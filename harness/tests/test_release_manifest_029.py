"""OpenSpec 029 RA1: complete, canonical release manifests."""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.knowledge.pages import render_snapshot_pages
from insurance_harness.knowledge.release_manifest import (
    CanonicalDirectoryEntry,
    CanonicalPage,
    CanonicalRelationship,
    CanonicalSnapshotFact,
    ReleaseManifest,
    ReleaseManifestBuildError,
    ReleaseManifestIntegrityError,
    build_release_manifest,
    build_release_manifest_from_snapshot,
    verify_release_manifest,
)
from insurance_harness.knowledge.snapshots import build_snapshot_facts
from insurance_harness.knowledge.tables import ReleaseSnapshot, SnapshotFact
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


def _items() -> dict[str, list[dict[str, Any]]]:
    def evidence(claim_id: str) -> dict[str, Any]:
        return {
            "id": f"evidence-{claim_id}",
            "claim_id": claim_id,
            "knowledge_id": f"knowledge-{claim_id}",
            "doc_title": f"document-{claim_id}",
            "chunk_id": f"chunk-{claim_id}",
            "quote": "frozen quote",
            "page": 1,
            "section": "coverage",
            "table_ref": None,
            "timestamp_ms": None,
            "authority_level": 1,
            "doc_role": "terms",
            "extraction_method": "llm",
            "extracted_at": NOW,
            "raw_kb_id": "raw-1",
            "source_revision": _A,
            "file_hash": _B,
            "original_digest": _C,
            "parser_version": "parser/1",
            "chunk_hash": _A,
            "lineage_status": "linked",
            "stale_at": None,
            "created_at": NOW,
            "updated_at": NOW,
        }

    def fact(index: int) -> dict[str, Any]:
        claim_id = f"claim-{index}"
        return {
            "space_id": "space-1",
            "snapshot_id": "snapshot-1",
            "claim_id": claim_id,
            "revision_no": index,
            "product_id": f"product-{index}",
            "product_version_id": f"version-{index}",
            "product_code": f"P{index}",
            "product_name": f"Product {index}",
            "version_label": "V1",
            "predicate": "waiting_period",
            "field_name": "Waiting period",
            "field_group": "coverage",
            "value_state": "present",
            "value": {"currency": "CNY", "amount": index * 10},
            "effective_from": None,
            "effective_to": None,
            "confidence": 0.9,
            "schema_version": "insurance-knowledge-v1",
            "evidence": (evidence(claim_id),),
        }

    def page(index: int) -> dict[str, Any]:
        return {
            "slug": f"product/P{index}/V1/overview",
            "title": f"Product {index}",
            "content": f"page-{index}",
            "source_refs": (),
            "chunk_refs": (),
            "page_metadata": {
                "entity_ids": {
                    "product_id": f"product-{index}",
                    "product_version_id": f"version-{index}",
                },
                "snapshot_id": "snapshot-1",
                "claim_ids": (f"claim-{index}",),
                "compiled_at": NOW.isoformat(),
                "harness_version": "insurance-harness/0.1.0",
                "schema_version": "insurance-knowledge-v1",
                "managed_by": "insurance-harness",
                "space_id": "space-1",
                "schema_versions": ("insurance-knowledge-v1",),
            },
        }

    return {
        "facts": [fact(2), fact(1)],
        "rendered_pages": [page(2), page(1)],
        "directory_entries": [
            {
                "product_id": "product-2",
                "product_version_id": "version-2",
                "product_code": "P2",
                "product_name": "Product 2",
                "version_label": "V1",
                "page_slugs": ("product/P2/V1/overview",),
            },
            {
                "product_id": "product-1",
                "product_version_id": "version-1",
                "product_code": "P1",
                "product_name": "Product 1",
                "version_label": "V1",
                "page_slugs": ("product/P1/V1/overview",),
            },
        ],
        "relationships": [
            {
                "from_type": "product_version",
                "from_id": "version-2",
                "relationship": "renders",
                "to_type": "page",
                "to_id": "product/P2/V1/overview",
            },
            {
                "from_type": "page",
                "from_id": "product/P1/V1/overview",
                "relationship": "contains_claim",
                "to_type": "claim",
                "to_id": "claim-1",
            },
        ],
    }


def _manifest(**overrides: Any) -> ReleaseManifest:
    values: dict[str, Any] = {
        "schema_version": "insurance-knowledge-v1",
        "space_id": "space-1",
        "snapshot_id": "snapshot-1",
        "read_model_version": 1,
        "template_hashes": (_B, _A),
        "model_plan_hash": _C,
        **_items(),
    }
    values.update(overrides)
    return build_release_manifest(**values)


def test_ra1_manifest_binds_all_four_artifact_groups_with_count_and_digest() -> None:
    manifest = _manifest()

    assert {item.claim_id for item in manifest.facts} == {"claim-1", "claim-2"}
    assert {item.slug for item in manifest.rendered_pages} == {
        "product/P1/V1/overview",
        "product/P2/V1/overview",
    }
    assert {item.product_id for item in manifest.directory_entries} == {
        "product-1",
        "product-2",
    }
    assert len(manifest.relationships) == 2
    assert manifest.facts_digest.count == len(manifest.facts)
    assert manifest.rendered_pages_digest.count == len(manifest.rendered_pages)
    assert manifest.directory_digest.count == len(manifest.directory_entries)
    assert manifest.relationships_digest.count == len(manifest.relationships)
    for digest in (
        manifest.facts_digest,
        manifest.rendered_pages_digest,
        manifest.directory_digest,
        manifest.relationships_digest,
    ):
        assert len(digest.sha256) == 64
    assert len(manifest.manifest_sha256) == 64
    verify_release_manifest(manifest)


def test_ra1_empty_groups_are_explicit_and_hashed() -> None:
    manifest = _manifest(
        facts=[], rendered_pages=[], directory_entries=[], relationships=[]
    )

    assert manifest.facts == ()
    assert manifest.rendered_pages == ()
    assert manifest.directory_entries == ()
    assert manifest.relationships == ()
    assert manifest.facts_digest.count == 0
    assert manifest.facts_digest.sha256
    verify_release_manifest(manifest)


def test_ra1_input_and_mapping_key_order_do_not_change_canonical_hash() -> None:
    items = _items()
    reordered = {
        name: [dict(reversed(tuple(item.items()))) for item in reversed(group)]
        for name, group in items.items()
    }

    first = _manifest(**items)
    second = _manifest(**reordered)

    assert first == second
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.template_hashes == tuple(sorted((_A, _B)))


def test_ra1_nested_evidence_order_does_not_change_canonical_hash() -> None:
    items = _items()
    target_claim_id = items["facts"][0]["claim_id"]
    first_evidence = items["facts"][0]["evidence"][0]
    second_evidence = dict(first_evidence)
    second_evidence["id"] = "evidence-second"
    second_evidence["knowledge_id"] = "knowledge-second"
    second_evidence["chunk_id"] = "chunk-second"
    items["facts"][0]["evidence"] = (first_evidence, second_evidence)

    reordered = deepcopy(items)
    reordered["facts"][0]["evidence"] = tuple(
        reversed(reordered["facts"][0]["evidence"])
    )

    first = _manifest(**items)
    second = _manifest(**reordered)

    assert first == second
    assert first.manifest_sha256 == second.manifest_sha256
    canonical_fact = next(
        fact for fact in first.facts if fact.claim_id == target_claim_id
    )
    assert tuple(item.id for item in canonical_fact.evidence) == (
        f"evidence-{target_claim_id}",
        "evidence-second",
    )


@pytest.mark.parametrize("conflicting_duplicate", [False, True])
def test_ra1_duplicate_evidence_identity_is_rejected(
    conflicting_duplicate: bool,
) -> None:
    items = _items()
    original = items["facts"][0]["evidence"][0]
    duplicate = dict(original)
    if conflicting_duplicate:
        duplicate["quote"] = "conflicting duplicate"
    items["facts"][0]["evidence"] = (original, duplicate)

    with pytest.raises(ValidationError, match="evidence identities must be unique"):
        _manifest(**items)


@pytest.mark.parametrize(
    "datetime_field", ["extracted_at", "created_at", "updated_at", "stale_at"]
)
def test_ra1_evidence_datetimes_normalize_same_instant_to_utc(
    datetime_field: str,
) -> None:
    utc_items = _items()
    offset_items = deepcopy(utc_items)
    utc_instant = NOW
    offset_instant = NOW.astimezone(timezone(timedelta(hours=8)))
    utc_items["facts"][0]["evidence"][0][datetime_field] = utc_instant
    offset_items["facts"][0]["evidence"][0][datetime_field] = offset_instant

    utc_manifest = _manifest(**utc_items)
    offset_manifest = _manifest(**offset_items)

    assert utc_manifest.manifest_sha256 == offset_manifest.manifest_sha256
    changed_fact = next(
        fact for fact in offset_manifest.facts if fact.claim_id == "claim-2"
    )
    normalized = getattr(changed_fact.evidence[0], datetime_field)
    assert normalized is not None and normalized.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "datetime_field", ["extracted_at", "created_at", "updated_at", "stale_at"]
)
def test_ra1_evidence_datetimes_reject_naive_values(datetime_field: str) -> None:
    items = _items()
    items["facts"][0]["evidence"][0][datetime_field] = datetime(2026, 7, 15, 8)

    with pytest.raises(ValidationError):
        _manifest(**items)


@pytest.mark.parametrize(
    ("field", "changed_field", "changed_value"),
    [
        ("facts", "product_name", "tampered"),
        ("rendered_pages", "content", "tampered"),
        ("directory_entries", "product_name", "tampered"),
        ("relationships", "to_id", "tampered"),
    ],
)
def test_ra1_any_artifact_content_tamper_fails_closed(
    field: str, changed_field: str, changed_value: str
) -> None:
    original = _manifest()
    item = getattr(original, field)[0]
    manifest = original.model_copy(
        update={field: (item.model_copy(update={changed_field: changed_value}),)}
    )

    with pytest.raises(ReleaseManifestIntegrityError, match=field):
        verify_release_manifest(manifest)


@pytest.mark.parametrize(
    "digest_field",
    [
        "facts_digest",
        "rendered_pages_digest",
        "directory_digest",
        "relationships_digest",
    ],
)
def test_ra1_count_or_artifact_hash_tamper_fails_closed(digest_field: str) -> None:
    manifest = _manifest()
    digest = getattr(manifest, digest_field)

    bad_count = manifest.model_copy(
        update={digest_field: digest.model_copy(update={"count": digest.count + 1})}
    )
    bad_hash = manifest.model_copy(
        update={digest_field: digest.model_copy(update={"sha256": "0" * 64})}
    )

    with pytest.raises(ReleaseManifestIntegrityError, match=digest_field):
        verify_release_manifest(bad_count)
    with pytest.raises(ReleaseManifestIntegrityError, match=digest_field):
        verify_release_manifest(bad_hash)


def test_ra1_outer_manifest_hash_tamper_fails_closed() -> None:
    manifest = _manifest().model_copy(update={"manifest_sha256": "0" * 64})

    with pytest.raises(ReleaseManifestIntegrityError, match="manifest_sha256"):
        verify_release_manifest(manifest)


@pytest.mark.parametrize(
    ("group", "digest_field", "operation"),
    [
        (group, digest, operation)
        for group, digest in (
            ("facts", "facts_digest"),
            ("rendered_pages", "rendered_pages_digest"),
            ("directory_entries", "directory_digest"),
            ("relationships", "relationships_digest"),
        )
        for operation in ("insert", "delete", "mutate")
    ],
)
def test_ra1_insert_delete_or_content_mutation_changes_group_and_outer_hash(
    group: str, digest_field: str, operation: str
) -> None:
    original = _manifest()
    values = _items()
    artifacts = values[group]
    if operation == "insert":
        artifacts.append(deepcopy(artifacts[0]))
    elif operation == "delete":
        artifacts.pop()
    elif group == "facts":
        artifacts[0]["evidence"][0]["quote"] = "evidence-only mutation"
    elif group == "rendered_pages":
        artifacts[0]["content"] = "page mutation"
    elif group == "directory_entries":
        artifacts[0]["product_name"] = "directory mutation"
    else:
        artifacts[0]["to_id"] = "relationship-mutation"

    rebuilt = _manifest(**{group: artifacts})

    assert getattr(rebuilt, digest_field) != getattr(original, digest_field)
    assert rebuilt.manifest_sha256 != original.manifest_sha256
    tampered = original.model_copy(update={group: getattr(rebuilt, group)})
    with pytest.raises(ReleaseManifestIntegrityError, match=group):
        verify_release_manifest(tampered)


@pytest.mark.parametrize(
    ("identity", "changed"),
    [
        ("schema_version", "insurance-knowledge-v2"),
        ("space_id", "space-2"),
        ("snapshot_id", "snapshot-2"),
        ("read_model_version", 2),
        ("template_hashes", (_A,)),
        ("model_plan_hash", _B),
    ],
)
def test_ra1_any_release_identity_change_changes_outer_hash(
    identity: str, changed: object
) -> None:
    assert _manifest().manifest_sha256 != _manifest(**{identity: changed}).manifest_sha256


@pytest.mark.parametrize(
    "missing",
    ["facts", "rendered_pages", "directory_entries", "relationships"],
)
def test_ra1_manifest_schema_rejects_a_missing_artifact_group(missing: str) -> None:
    data = _manifest().model_dump(mode="json")
    del data[missing]

    with pytest.raises(ValidationError) as exc_info:
        ReleaseManifest.model_validate_json(json.dumps(data))
    assert any(error["loc"] == (missing,) for error in exc_info.value.errors())


def test_ra1_manifest_schema_forbids_extra_fields() -> None:
    data = _manifest().model_dump(mode="json")
    data["unbound_artifacts"] = [{"id": "outside-manifest"}]

    with pytest.raises(ValidationError) as exc_info:
        ReleaseManifest.model_validate_json(json.dumps(data))
    assert any(error["loc"] == ("unbound_artifacts",) for error in exc_info.value.errors())


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("schema_version", " "),
        ("space_id", ""),
        ("snapshot_id", "\t"),
        ("read_model_version", 0),
        ("template_hashes", ("NOT-A-HASH",)),
        ("template_hashes", (_A, _A)),
        ("model_plan_hash", "A" * 64),
    ],
)
def test_ra1_builder_rejects_invalid_release_identity(field: str, bad_value: object) -> None:
    with pytest.raises(ValidationError):
        _manifest(**{field: bad_value})


def test_ra1_caller_mutation_cannot_drift_built_manifest() -> None:
    items = _items()
    original = deepcopy(items)
    manifest = _manifest(**items)

    items["facts"][0]["value"]["amount"] = 999
    items["rendered_pages"][0]["content"] = "changed"
    items["directory_entries"][0]["product_name"] = "changed"
    items["relationships"].clear()

    assert manifest == _manifest(**original)
    verify_release_manifest(manifest)


def test_ra1_manifest_models_are_frozen_and_revalidate_nested_models() -> None:
    manifest = _manifest()

    assert isinstance(manifest.facts[0], CanonicalSnapshotFact)
    assert isinstance(manifest.rendered_pages[0], CanonicalPage)
    assert isinstance(manifest.directory_entries[0], CanonicalDirectoryEntry)
    assert isinstance(manifest.relationships[0], CanonicalRelationship)
    with pytest.raises(ValidationError):
        manifest.space_id = "space-2"
    with pytest.raises(ValidationError):
        ReleaseManifest.model_validate(
            manifest.model_dump(mode="json")
            | {"facts_digest": {"count": -1, "sha256": _A}}
        )


def test_ra1_manifest_preserves_canonical_external_json_shape() -> None:
    manifest = _manifest()
    dumped = manifest.model_dump(mode="json")

    assert isinstance(dumped["facts"][0], dict)
    assert isinstance(dumped["facts"][0]["value"], dict)
    assert isinstance(dumped["facts"][0]["evidence"], list)
    assert isinstance(dumped["rendered_pages"][0]["page_metadata"], dict)
    restored = ReleaseManifest.model_validate_json(
        json.dumps(dumped, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    assert restored == manifest
    verify_release_manifest(restored)


def test_ra1_strict_models_reject_python_type_coercion() -> None:
    with pytest.raises(ValidationError):
        _manifest(read_model_version="1")
    bad = _items()
    bad["facts"][0]["revision_no"] = "1"
    with pytest.raises(ValidationError):
        _manifest(**bad)


def test_ra1_deep_json_values_cannot_be_mutated_in_place() -> None:
    manifest = _manifest()

    with pytest.raises(TypeError):
        manifest.facts[0].value["currency"] = "USD"
    with pytest.raises(ValidationError):
        manifest.facts[0].evidence[0].quote = "changed"
    with pytest.raises(ValidationError):
        manifest.rendered_pages[0].page_metadata.space_id = "changed"


def test_ra1_generic_builder_rejects_incomplete_untyped_fact() -> None:
    with pytest.raises(ValidationError):
        _manifest(facts=({"claim_id": "missing-complete-frozen-fields"},))

    missing_evidence = _items()
    del missing_evidence["facts"][0]["evidence"]
    with pytest.raises(ValidationError):
        _manifest(**missing_evidence)


def test_ra1_template_hashes_must_be_nonempty() -> None:
    with pytest.raises(ValidationError):
        _manifest(template_hashes=())


def _persist_frozen_snapshot(session: Session, *, suffix: str = "manifest") -> tuple[Any, Any]:
    scope = release_scope(session, suffix)
    _product, version = release_product(session, scope, code=f"P-{suffix}")
    claim, _evidence = release_claim(
        session,
        scope,
        version,
        claim_id=f"claim-{suffix}",
        predicate="waiting_period",
    )
    facts = build_snapshot_facts(session, scope, snapshot_id=f"snapshot-{suffix}")
    persist_release_snapshot(
        session,
        scope,
        snapshot_id=f"snapshot-{suffix}",
        facts=facts,
        make_current=False,
    )
    return scope, claim


def _build_from_snapshot(session: Session, scope: Any, snapshot_id: str) -> ReleaseManifest:
    return build_release_manifest_from_snapshot(
        session,
        scope,
        snapshot_id=snapshot_id,
        schema_version="v1.1+release",
        template_hashes=(_B, _A),
        model_plan_hash=_C,
    )


def _persist_projection_with_pages(
    session: Session,
    *,
    suffix: str,
    page_mutator: Callable[[list[dict[str, Any]]], None] | None = None,
    fact_mutator: Callable[[list[dict[str, Any]]], None] | None = None,
    two_products: bool = False,
) -> tuple[Any, Any]:
    scope = release_scope(session, suffix)
    _product, version = release_product(session, scope, code=f"P-{suffix}-A")
    claim, _evidence = release_claim(
        session,
        scope,
        version,
        claim_id=f"claim-{suffix}-a",
        predicate="waiting_period",
    )
    if two_products:
        _other_product, other_version = release_product(
            session, scope, code=f"P-{suffix}-B"
        )
        release_claim(
            session,
            scope,
            other_version,
            claim_id=f"claim-{suffix}-b",
            predicate="coverage_amount",
        )
    snapshot_id = f"snapshot-{suffix}"
    facts = build_snapshot_facts(session, scope, snapshot_id=snapshot_id)
    pages = [
        page.model_dump(mode="json")
        for page in render_snapshot_pages(
            facts,
            space_id=scope.space_id,
            snapshot_id=snapshot_id,
            compiled_at=NOW,
        )
    ]
    if page_mutator is not None:
        page_mutator(pages)
    fact_rows: list[dict[str, Any]] = [
        {
            "id": f"fact-{suffix}-{index}",
            "space_id": fact.space_id,
            "snapshot_id": snapshot_id,
            "claim_id": fact.claim_id,
            "revision_no": fact.revision_no,
            "product_id": fact.product_id,
            "product_version_id": fact.product_version_id,
            "product_code": fact.product_code,
            "product_name": fact.product_name,
            "version_label": fact.version_label,
            "predicate": fact.predicate,
            "field_name": fact.field_name,
            "field_group": fact.field_group,
            "value_state": fact.value_state,
            "value": fact.value,
            "effective_from": fact.effective_from,
            "effective_to": fact.effective_to,
            "confidence": fact.confidence,
            "schema_version": fact.schema_version,
            "evidence": [item.model_dump(mode="json") for item in fact.evidence],
        }
        for index, fact in enumerate(facts)
    ]
    # SQLite drops timezone information from ORM DateTime values; this helper
    # represents a valid production PostgreSQL frozen projection explicitly.
    for row in fact_rows:
        for evidence in row["evidence"]:
            for field in ("extracted_at", "created_at", "updated_at"):
                evidence[field] = NOW.isoformat()
    if fact_mutator is not None:
        fact_mutator(fact_rows)
    snapshot = ReleaseSnapshot(
        id=snapshot_id,
        space_id=scope.space_id,
        label=snapshot_id,
        rendered_pages=pages,
        status="building",
        read_model_version=1,
        projection_frozen_at=None,
        published_at=None,
        published_by="test",
    )
    session.add(snapshot)
    session.flush()
    for row in fact_rows:
        session.add(SnapshotFact(**row))
    session.flush()
    snapshot.projection_frozen_at = NOW
    snapshot.status = "published"
    snapshot.published_at = NOW
    session.commit()
    return scope, claim


def test_ra1_snapshot_builder_reads_only_frozen_projection_not_mutable_claim(
    kb_session: Session,
) -> None:
    scope, claim = _persist_frozen_snapshot(kb_session)
    first = _build_from_snapshot(kb_session, scope, "snapshot-manifest")

    claim.value = {"text": "mutable claim changed after freeze"}
    claim.status = "retracted"
    assert claim in kb_session.dirty
    second = _build_from_snapshot(kb_session, scope, "snapshot-manifest")

    assert claim in kb_session.dirty  # read-only builder must not autoflush mutable state
    assert second == first
    assert second.facts[0].value == {"text": "90天"}


def test_ra1_snapshot_builder_derives_directory_from_frozen_facts(
    kb_session: Session,
) -> None:
    scope, _claim = _persist_frozen_snapshot(kb_session, suffix="directory")

    manifest = _build_from_snapshot(kb_session, scope, "snapshot-directory")

    entry = manifest.directory_entries[0]
    assert entry.page_slugs == ()
    assert entry.product_code == "P-directory"
    assert entry.product_id == manifest.facts[0].product_id
    assert entry.product_name == "产品P-directory"
    assert entry.product_version_id == manifest.facts[0].product_version_id
    assert entry.version_label == "V1"
    assert manifest.relationships == ()
    verify_release_manifest(manifest)


def test_ra1_snapshot_builder_rejects_cross_scope_and_missing_snapshot(
    kb_session: Session,
) -> None:
    scope_a, _claim_a = _persist_frozen_snapshot(kb_session, suffix="scope-a")
    scope_b, _claim_b = _persist_frozen_snapshot(kb_session, suffix="scope-b")

    with pytest.raises(ReleaseManifestBuildError, match="snapshot unavailable"):
        _build_from_snapshot(kb_session, scope_a, "snapshot-scope-b")
    with pytest.raises(ReleaseManifestBuildError, match="snapshot unavailable"):
        _build_from_snapshot(kb_session, scope_b, "does-not-exist")


def test_ra1_snapshot_builder_rejects_unfrozen_snapshot(kb_session: Session) -> None:
    scope = release_scope(kb_session, "unfrozen")
    kb_session.add(
        ReleaseSnapshot(
            id="snapshot-unfrozen",
            space_id=scope.space_id,
            label="snapshot-unfrozen",
            rendered_pages=[],
            status="building",
            read_model_version=1,
            projection_frozen_at=None,
            published_at=None,
            published_by="test",
        )
    )
    kb_session.commit()

    with pytest.raises(ReleaseManifestBuildError, match="projection is not frozen"):
        _build_from_snapshot(kb_session, scope, "snapshot-unfrozen")


def test_ra1_snapshot_builder_accepts_projection_frozen_building_candidate(
    kb_session: Session,
) -> None:
    scope = release_scope(kb_session, "frozen-building")
    kb_session.add(
        ReleaseSnapshot(
            id="snapshot-frozen-building",
            space_id=scope.space_id,
            label="snapshot-frozen-building",
            rendered_pages=[],
            status="building",
            read_model_version=1,
            projection_frozen_at=NOW,
            published_at=None,
            published_by="test",
        )
    )
    kb_session.commit()

    manifest = _build_from_snapshot(kb_session, scope, "snapshot-frozen-building")

    assert manifest.snapshot_id == "snapshot-frozen-building"
    verify_release_manifest(manifest)


def test_ra1_snapshot_builder_rejects_dirty_frozen_rows(kb_session: Session) -> None:
    scope, _claim = _persist_frozen_snapshot(kb_session, suffix="dirty-frozen")
    snapshot = kb_session.get(ReleaseSnapshot, "snapshot-dirty-frozen")
    fact = kb_session.scalar(
        select(SnapshotFact).where(SnapshotFact.snapshot_id == "snapshot-dirty-frozen")
    )
    assert snapshot is not None and fact is not None

    fact.product_name = "dirty fact"
    with pytest.raises(ReleaseManifestBuildError, match="dirty frozen projection"):
        _build_from_snapshot(kb_session, scope, snapshot.id)
    kb_session.rollback()

    snapshot = kb_session.get(ReleaseSnapshot, "snapshot-dirty-frozen")
    assert snapshot is not None
    snapshot.notes = "dirty snapshot"
    with pytest.raises(ReleaseManifestBuildError, match="dirty frozen projection"):
        _build_from_snapshot(kb_session, scope, snapshot.id)


def test_ra1_snapshot_builder_rejects_deleted_frozen_row(kb_session: Session) -> None:
    scope, _claim = _persist_frozen_snapshot(kb_session, suffix="deleted-frozen")
    fact = kb_session.scalar(
        select(SnapshotFact).where(SnapshotFact.snapshot_id == "snapshot-deleted-frozen")
    )
    assert fact is not None
    kb_session.delete(fact)

    with pytest.raises(ReleaseManifestBuildError, match="dirty frozen projection"):
        _build_from_snapshot(kb_session, scope, "snapshot-deleted-frozen")


def test_ra1_snapshot_builder_ignores_untracked_in_place_json_mutation(
    kb_session: Session,
) -> None:
    scope, _claim = _persist_projection_with_pages(
        kb_session, suffix="identity-map-json"
    )
    snapshot = kb_session.get(ReleaseSnapshot, "snapshot-identity-map-json")
    fact = kb_session.scalar(
        select(SnapshotFact).where(
            SnapshotFact.snapshot_id == "snapshot-identity-map-json"
        )
    )
    assert snapshot is not None and snapshot.rendered_pages
    assert fact is not None and fact.value and fact.evidence

    fact.value["text"] = "untracked-memory-value"
    fact.evidence[0]["quote"] = "untracked-memory-evidence"
    snapshot.rendered_pages[0]["content"] = "untracked-memory-page"
    assert snapshot not in kb_session.dirty
    assert fact not in kb_session.dirty

    manifest = _build_from_snapshot(
        kb_session, scope, "snapshot-identity-map-json"
    )

    assert manifest.facts[0].value == {"text": "90天"}
    assert manifest.facts[0].evidence[0].quote != "untracked-memory-evidence"
    assert manifest.rendered_pages[0].content != "untracked-memory-page"
    assert fact.value["text"] == "untracked-memory-value"
    assert snapshot.rendered_pages[0]["content"] == "untracked-memory-page"


@pytest.mark.parametrize(
    ("suffix", "mutator", "error"),
    [
        (
            "page-cross-space",
            lambda pages: pages[0]["page_metadata"].__setitem__("space_id", "other"),
            "page identity",
        ),
        (
            "page-ghost-claim",
            lambda pages: pages[0]["page_metadata"]["claim_ids"].append("ghost"),
            "claim closure",
        ),
        (
            "page-duplicate-claim",
            lambda pages: pages[0]["page_metadata"]["claim_ids"].append(
                pages[0]["page_metadata"]["claim_ids"][0]
            ),
            "claims are invalid",
        ),
        (
            "page-missing-claim",
            lambda pages: pages[0]["page_metadata"].__setitem__("claim_ids", []),
            "claims are invalid",
        ),
        (
            "page-wrong-product",
            lambda pages: pages[0]["page_metadata"]["entity_ids"].__setitem__(
                "product_id", "other-product"
            ),
            "matching fact identity",
        ),
    ],
)
def test_ra1_snapshot_builder_rejects_invalid_page_fact_closure(
    kb_session: Session,
    suffix: str,
    mutator: Callable[[list[dict[str, Any]]], None],
    error: str,
) -> None:
    scope, _claim = _persist_projection_with_pages(
        kb_session, suffix=suffix, page_mutator=mutator
    )

    with pytest.raises(ReleaseManifestBuildError, match=error):
        _build_from_snapshot(kb_session, scope, f"snapshot-{suffix}")


def test_ra1_snapshot_builder_rejects_cross_product_claim_on_page(
    kb_session: Session,
) -> None:
    def cross_product(pages: list[dict[str, Any]]) -> None:
        pages.sort(key=lambda page: page["slug"])
        foreign_claim = pages[1]["page_metadata"]["claim_ids"][0]
        pages[0]["page_metadata"]["claim_ids"].append(foreign_claim)

    scope, _claim = _persist_projection_with_pages(
        kb_session,
        suffix="page-cross-product",
        page_mutator=cross_product,
        two_products=True,
    )

    with pytest.raises(ReleaseManifestBuildError, match="claim closure"):
        _build_from_snapshot(kb_session, scope, "snapshot-page-cross-product")


def test_ra1_snapshot_builder_rejects_duplicate_page_slug_across_products(
    kb_session: Session,
) -> None:
    def duplicate_slug(pages: list[dict[str, Any]]) -> None:
        pages[1]["slug"] = pages[0]["slug"]

    scope, _claim = _persist_projection_with_pages(
        kb_session,
        suffix="duplicate-page-slug",
        page_mutator=duplicate_slug,
        two_products=True,
    )

    with pytest.raises(ReleaseManifestBuildError, match="duplicate page slug"):
        _build_from_snapshot(kb_session, scope, "snapshot-duplicate-page-slug")


@pytest.mark.parametrize(
    ("suffix", "mutator", "error"),
    [
        (
            "evidence-cross-claim",
            lambda facts: facts[0]["evidence"][0].__setitem__(
                "claim_id", "other-claim"
            ),
            "evidence claim",
        ),
        (
            "evidence-cross-raw",
            lambda facts: facts[0]["evidence"][0].__setitem__(
                "raw_kb_id", "other-raw-kb"
            ),
            "evidence scope",
        ),
        (
            "evidence-stale",
            lambda facts: facts[0]["evidence"][0].__setitem__(
                "stale_at", NOW.isoformat()
            ),
            "evidence stale",
        ),
        (
            "evidence-bad-lineage",
            lambda facts: facts[0]["evidence"][0].__setitem__(
                "lineage_status", "page_only"
            ),
            "evidence lineage",
        ),
    ],
)
def test_ra1_snapshot_builder_rejects_invalid_frozen_evidence_closure(
    kb_session: Session,
    suffix: str,
    mutator: Callable[[list[dict[str, Any]]], None],
    error: str,
) -> None:
    scope, _claim = _persist_projection_with_pages(
        kb_session, suffix=suffix, fact_mutator=mutator
    )

    with pytest.raises(ReleaseManifestBuildError, match=error):
        _build_from_snapshot(kb_session, scope, f"snapshot-{suffix}")


@pytest.mark.parametrize(
    ("lineage_status", "cleared_field"),
    [("page_only", "chunk_hash"), ("ambiguous", "chunk_id")],
)
def test_ra1_nonlinked_evidence_rejects_any_single_chunk_identity_residue(
    kb_session: Session,
    lineage_status: str,
    cleared_field: str,
) -> None:
    def leave_one_chunk_identity(facts: list[dict[str, Any]]) -> None:
        evidence = facts[0]["evidence"][0]
        evidence["lineage_status"] = lineage_status
        evidence[cleared_field] = None

    suffix = f"evidence-{lineage_status}-residue"
    scope, _claim = _persist_projection_with_pages(
        kb_session, suffix=suffix, fact_mutator=leave_one_chunk_identity
    )

    with pytest.raises(ReleaseManifestBuildError, match="evidence lineage"):
        _build_from_snapshot(kb_session, scope, f"snapshot-{suffix}")


@pytest.mark.parametrize(
    "mutator",
    [
        lambda pages: pages[0]["page_metadata"].__setitem__(
            "schema_version", "other-schema"
        ),
        lambda pages: pages[0]["page_metadata"].__setitem__(
            "schema_versions", ["other-schema"]
        ),
    ],
)
def test_ra1_snapshot_builder_rejects_page_schema_identity_mismatch(
    kb_session: Session,
    mutator: Callable[[list[dict[str, Any]]], None],
) -> None:
    scope, _claim = _persist_projection_with_pages(
        kb_session, suffix="page-schema", page_mutator=mutator
    )

    with pytest.raises(ReleaseManifestBuildError, match="page schema"):
        _build_from_snapshot(kb_session, scope, "snapshot-page-schema")
