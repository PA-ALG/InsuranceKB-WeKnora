"""OpenSpec 029 RA1: complete, canonical release manifests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from insurance_harness.knowledge.release_manifest import (
    ReleaseManifest,
    ReleaseManifestBuildError,
    ReleaseManifestIntegrityError,
    build_release_manifest,
    build_release_manifest_from_snapshot,
    verify_release_manifest,
)
from insurance_harness.knowledge.snapshots import build_snapshot_facts
from insurance_harness.knowledge.tables import ReleaseSnapshot
from tests.support.release_018 import (
    persist_release_snapshot,
    release_claim,
    release_product,
    release_scope,
)

_A = "a" * 64
_B = "b" * 64
_C = "c" * 64


def _items() -> dict[str, list[dict[str, Any]]]:
    return {
        "facts": [
            {"claim_id": "claim-2", "value": {"currency": "CNY", "amount": 20}},
            {"claim_id": "claim-1", "value": {"amount": 10, "currency": "CNY"}},
        ],
        "rendered_pages": [
            {"page_id": "page-2", "body": "B"},
            {"body": "A", "page_id": "page-1"},
        ],
        "directory_entries": [
            {"product_id": "product-2", "page_id": "page-2"},
            {"page_id": "page-1", "product_id": "product-1"},
        ],
        "relationships": [
            {"from": "page-2", "kind": "related", "to": "page-1"},
            {"kind": "product", "to": "product-1", "from": "page-1"},
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

    assert {item["claim_id"] for item in manifest.facts} == {"claim-1", "claim-2"}
    assert {item["page_id"] for item in manifest.rendered_pages} == {"page-1", "page-2"}
    assert {item["product_id"] for item in manifest.directory_entries} == {
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


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("facts", ({"claim_id": "tampered"},)),
        ("rendered_pages", ({"page_id": "tampered"},)),
        ("directory_entries", ({"product_id": "tampered"},)),
        ("relationships", ({"from": "tampered", "to": "page-1"},)),
    ],
)
def test_ra1_any_artifact_content_tamper_fails_closed(
    field: str, replacement: tuple[dict[str, str], ...]
) -> None:
    manifest = _manifest().model_copy(update={field: replacement})

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

    with pytest.raises(ValidationError):
        ReleaseManifest.model_validate(data)


def test_ra1_manifest_schema_forbids_extra_fields() -> None:
    data = _manifest().model_dump(mode="json")
    data["unbound_artifacts"] = [{"id": "outside-manifest"}]

    with pytest.raises(ValidationError):
        ReleaseManifest.model_validate(data)


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
    items["rendered_pages"].append({"page_id": "page-3", "body": "C"})
    items["directory_entries"][0]["page_id"] = "page-x"
    items["relationships"].clear()

    assert manifest == _manifest(**original)
    verify_release_manifest(manifest)


def test_ra1_manifest_models_are_frozen_and_revalidate_nested_models() -> None:
    manifest = _manifest()

    with pytest.raises(ValidationError):
        manifest.space_id = "space-2"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ReleaseManifest.model_validate(
            manifest.model_dump(mode="json")
            | {"facts_digest": {"count": -1, "sha256": _A}}
        )


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
    assert second.facts[0]["value"] == {"text": "90天"}


def test_ra1_snapshot_builder_derives_directory_from_frozen_facts(
    kb_session: Session,
) -> None:
    scope, _claim = _persist_frozen_snapshot(kb_session, suffix="directory")

    manifest = _build_from_snapshot(kb_session, scope, "snapshot-directory")

    assert manifest.directory_entries == (
        {
            "page_slugs": [],
            "product_code": "P-directory",
            "product_id": manifest.facts[0]["product_id"],
            "product_name": "产品P-directory",
            "product_version_id": manifest.facts[0]["product_version_id"],
            "version_label": "V1",
        },
    )
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
