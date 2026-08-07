from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    CaptureAttemptV2,
    CaptureCallsV2,
    CaptureParserV2,
    MinerUCaptureBundle5961V1,
    MinerUCaptureEvidenceV2,
    MinerUCaptureIntakeItem5961V1,
    NativeCrossPageFactsV1,
    NativeCrossPageMarkerEvidenceV1,
    NativeCrossPageMarkerProvenanceV1,
    marker_provenance_custody_preimage,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    POLICY_SHA256,
    CrossPageEndpointV1,
    CrossPageRelationBindingV1,
)
from insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1 import (
    RelationReceiptBridgeError,
    build_relation_receipt_596_1,
    publish_relation_receipt_596_1,
    replay_relation_receipt_596_1,
)

TERMS_SHA = "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"
BROCHURE_SHA = "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"
RATE_SHA = "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"
H = "0" * 64


def _marker(
    kind: str,
    index: int,
    *,
    page_index: int | None = None,
    node_type: str = "text",
) -> NativeCrossPageMarkerEvidenceV1:
    return NativeCrossPageMarkerEvidenceV1.model_construct(
        marker_kind=kind,
        page_index=index if page_index is None else page_index,
        structural_path_sha256=("b" if index == 0 else "c") * 64,
        node_type=node_type,
        local_index=index,
        marker_sha256=("d" if index == 0 else "e") * 64,
    )


def _item(
    role: str, source: str, *, markers: tuple[NativeCrossPageMarkerEvidenceV1, ...]
) -> MinerUCaptureIntakeItem5961V1:
    facts = (
        NativeCrossPageFactsV1.model_construct(
            contract="mineru-native-cross-page-facts.v1",
            status="NATIVE_CROSS_PAGE_FACT_AMBIGUOUS",
            required_capability=("cross_page_sections" if role == "terms" else "cross_page_tables"),
            source_sha256=source,
            parser_model="pipeline",
            mineru_version="3.4.4",
            raw_zip_sha256="1" * 64,
            native_member_sha256="2" * 64,
            member_inventory_sha256="3" * 64,
            projection_sha256="4" * 64,
            relation_count=0,
            ambiguous_marker_count=len(markers),
            ambiguous_observation_hashes=tuple("5" * 64 for _ in markers),
            members=(),
            relations=(),
        )
        if markers
        else None
    )
    provenance = (
        NativeCrossPageMarkerProvenanceV1.model_construct(
            contract="mineru-native-cross-page-marker-provenance.v1",
            source_sha256=source,
            parser_model="pipeline",
            mineru_version="3.4.4",
            raw_zip_sha256="1" * 64,
            native_member_sha256="2" * 64,
            marker_count=len(markers),
            markers=markers,
            replay_digest_sha256="3" * 64,
        )
        if markers
        else None
    )
    evidence = MinerUCaptureEvidenceV2.model_construct(
        contract="mineru-semantic-content-custody.v2",
        source_sha256=source,
        attempt=CaptureAttemptV2(attempt_number=2, attempt_role="bounded_upgrade", generation=0),
        raw_structure_sha256="4" * 64,
        sanitized_structure_sha256="5" * 64,
        sanitized_structure=b"{}",
        content_snapshot_sha256="6" * 64,
        content_snapshot="private",
        capture_identity_sha256="7" * 64,
        parser=CaptureParserV2(
            engine="mineru_cloud",
            implementation="NewMinerUCloudReader",
            native_structure_schema="mineru-native-structure.v1",
            model="pipeline",
            formula=True,
            table=True,
            ocr=True,
            language="ch",
            config_sha256="a" * 64,
        ),
        calls=CaptureCallsV2(allocation_post=1, upload_put=1, status_get=1, zip_get=1),
        latency_milliseconds=1,
        status="completed",
        cross_page_facts=facts,
        cross_page_marker_provenance=provenance,
    )
    facts_digest = (
        canonical_hash(
            "mineru-native-cross-page-facts-custody.v1",
            facts.model_dump(mode="json", exclude_none=True),
        )
        if facts is not None
        else None
    )
    marker_digest = (
        canonical_hash(
            "mineru-cross-page-marker-provenance-custody.v1",
            marker_provenance_custody_preimage(provenance),
        )
        if provenance is not None
        else None
    )
    return MinerUCaptureIntakeItem5961V1.model_construct(
        role=role,
        source_sha256=source,
        capture_identity_sha256=evidence.capture_identity_sha256,
        cross_page_facts_digest_sha256=facts_digest,
        marker_provenance_digest_sha256=marker_digest,
        intake_digest_sha256=("0" if role == "terms" else "1" if role == "brochure" else "2") * 64,
        evidence=evidence,
    )


def _bundle() -> MinerUCaptureBundle5961V1:
    return MinerUCaptureBundle5961V1.model_construct(
        contract="mineru-capture-intake-596-1.v1",
        sources=(
            _item(
                "terms",
                TERMS_SHA,
                markers=(_marker("cross_page", 0), _marker("lines_deleted", 1)),
            ),
            _item("brochure", BROCHURE_SHA, markers=()),
            _item(
                "rate",
                RATE_SHA,
                markers=(
                    _marker("cross_page", 0, node_type="table"),
                    _marker("cross_page", 1, node_type="table"),
                ),
            ),
        ),
        bundle_digest_sha256="f" * 64,
    )


def _complete_bundle() -> MinerUCaptureBundle5961V1:
    current = _bundle()
    terms = _item(
        "terms",
        TERMS_SHA,
        markers=(_marker("cross_page", 0), _marker("cross_page", 1)),
    )
    return current.model_copy(update={"sources": (terms, current.sources[1], current.sources[2])})


def _replace_terms(
    bundle: MinerUCaptureBundle5961V1,
    terms: MinerUCaptureIntakeItem5961V1,
) -> MinerUCaptureBundle5961V1:
    return bundle.model_copy(update={"sources": (terms, bundle.sources[1], bundle.sources[2])})


def _mutate_terms_provenance(
    bundle: MinerUCaptureBundle5961V1,
    updates: dict[str, object],
) -> MinerUCaptureBundle5961V1:
    terms = bundle.sources[0]
    provenance = terms.evidence.cross_page_marker_provenance
    assert provenance is not None
    changed = provenance.model_copy(update=updates)
    evidence = terms.evidence.model_copy(update={"cross_page_marker_provenance": changed})
    return _replace_terms(bundle, terms.model_copy(update={"evidence": evidence}))


def _binding(
    kind: str,
    source: str,
    seed: str,
    bundle: MinerUCaptureBundle5961V1,
) -> CrossPageRelationBindingV1:
    endpoint_kind: Literal["block", "table"] = "block" if kind == "section" else "table"
    values: dict[str, Any] = {
        "contract": "cross-page-relation-binding.v1",
        "status": "DERIVED_STRUCTURAL_BINDING_VERIFIED",
        "provenance": "DERIVED_STRUCTURAL_RELATION",
        "relation_kind": kind,
        "source_sha256": source,
        "parser_identity_sha256": seed * 64,
        "parser_config_sha256": "a" * 64,
        "intake_bundle_digest_sha256": "f" * 64,
        "intake_item_digest_sha256": ("0" if kind == "section" else "2") * 64,
        "capture_identity_sha256": "7" * 64,
        "raw_structure_sha256": "4" * 64,
        "artifact_sha256": "5" * 64,
        "cross_page_facts_digest_sha256": (
            bundle.sources[0].cross_page_facts_digest_sha256
            if kind == "section"
            else bundle.sources[2].cross_page_facts_digest_sha256
        ),
        "parsed_document_hash": "b" * 64,
        "parse_manifest_hash": "c" * 64,
        "native_projection_sha256": "d" * 64,
        "native_observation_sha256": "e" * 64,
        "typed_marker_evidence_digest_sha256": "1" * 64,
        "marker_path_sha256": "2" * 64,
        "policy_sha256": POLICY_SHA256,
        "source_endpoint": CrossPageEndpointV1(
            endpoint_kind=endpoint_kind,
            endpoint_id=f"{kind}-source",
            page_number=1,
            endpoint_fact_digest_sha256="4" * 64,
            locator_digest_sha256="5" * 64,
        ),
        "target_endpoint": CrossPageEndpointV1(
            endpoint_kind=endpoint_kind,
            endpoint_id=f"{kind}-target",
            page_number=2,
            endpoint_fact_digest_sha256="6" * 64,
            locator_digest_sha256="7" * 64,
        ),
    }
    hash_values = dict(values)
    hash_values["source_endpoint"] = values["source_endpoint"].model_dump(mode="python")
    hash_values["target_endpoint"] = values["target_endpoint"].model_dump(mode="python")
    values["replay_digest_sha256"] = canonical_hash("cross-page-relation-binding.v1", hash_values)
    return CrossPageRelationBindingV1.model_validate(values)


def _derive(kind: str, bundle: MinerUCaptureBundle5961V1) -> CrossPageRelationBindingV1:
    return _binding(
        kind,
        TERMS_SHA if kind == "section" else RATE_SHA,
        "8" if kind == "section" else "9",
        bundle,
    )


def _verified_receipt(monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setattr(
        "insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1._derive_binding",
        lambda *args, relation_kind, **kwargs: _derive(relation_kind, args[0]),
    )
    return build_relation_receipt_596_1(
        _complete_bundle(),
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
    )


def test_actual_091_marker_shape_blocks_without_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def never_called(*args: object, **kwargs: object) -> CrossPageRelationBindingV1:
        nonlocal calls
        calls += 1
        return _derive(cast(str, kwargs["relation_kind"]), cast(Any, args[0]))

    monkeypatch.setattr(
        "insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1._derive_binding",
        never_called,
    )
    with pytest.raises(RelationReceiptBridgeError, match="BLOCKED_ON_CROSS_PAGE_BINDING"):
        build_relation_receipt_596_1(
            _bundle(),
            cast(Any, object()),
            cast(Any, object()),
            cast(Any, object()),
            cast(Any, object()),
        )
    assert calls == 0


@pytest.mark.parametrize(
    "markers",
    [
        (_marker("cross_page", 0),),
        (_marker("cross_page", 0), _marker("lines_deleted", 1)),
        (
            _marker("cross_page", 0, page_index=0),
            _marker("cross_page", 1, page_index=0),
        ),
        (
            _marker("cross_page", 0),
            _marker("cross_page", 1, node_type="table"),
        ),
        (
            _marker("cross_page", 0),
            _marker("cross_page", 1).model_copy(update={"structural_path_sha256": "b" * 64}),
        ),
    ],
)
def test_single_multi_kind_page_local_path_or_endpoint_ambiguity_blocks_before_086(
    monkeypatch: pytest.MonkeyPatch,
    markers: tuple[NativeCrossPageMarkerEvidenceV1, ...],
) -> None:
    calls = 0

    def counted(*args: object, **kwargs: object) -> CrossPageRelationBindingV1:
        nonlocal calls
        calls += 1
        return _derive(cast(str, kwargs["relation_kind"]), cast(Any, args[0]))

    monkeypatch.setattr(
        "insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1._derive_binding",
        counted,
    )
    bundle = _complete_bundle()
    bundle = _replace_terms(bundle, _item("terms", TERMS_SHA, markers=markers))
    with pytest.raises(RelationReceiptBridgeError, match="BLOCKED_ON_CROSS_PAGE_BINDING"):
        build_relation_receipt_596_1(
            bundle,
            cast(Any, object()),
            cast(Any, object()),
            cast(Any, object()),
            cast(Any, object()),
        )
    assert calls == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda bundle: _mutate_terms_provenance(bundle, {"source_sha256": RATE_SHA}),
        lambda bundle: _mutate_terms_provenance(bundle, {"parser_model": "other"}),
        lambda bundle: _mutate_terms_provenance(bundle, {"mineru_version": "3.4.5"}),
        lambda bundle: _mutate_terms_provenance(bundle, {"raw_zip_sha256": "0" * 64}),
        lambda bundle: _mutate_terms_provenance(bundle, {"native_member_sha256": "0" * 64}),
        lambda bundle: _mutate_terms_provenance(bundle, {"replay_digest_sha256": "0" * 64}),
        lambda bundle: _replace_terms(
            bundle,
            bundle.sources[0].model_copy(update={"marker_provenance_digest_sha256": "0" * 64}),
        ),
    ],
)
def test_source_parser_version_and_hash_drift_blocks_before_086(
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[MinerUCaptureBundle5961V1], MinerUCaptureBundle5961V1],
) -> None:
    calls = 0

    def counted(*args: object, **kwargs: object) -> CrossPageRelationBindingV1:
        nonlocal calls
        calls += 1
        return _derive(cast(str, kwargs["relation_kind"]), cast(Any, args[0]))

    monkeypatch.setattr(
        "insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1._derive_binding",
        counted,
    )
    with pytest.raises(RelationReceiptBridgeError, match="BLOCKED_ON_CROSS_PAGE_BINDING"):
        build_relation_receipt_596_1(
            mutate(_complete_bundle()),
            cast(Any, object()),
            cast(Any, object()),
            cast(Any, object()),
            cast(Any, object()),
        )
    assert calls == 0


def test_complete_verified_bindings_build_exact_two_relation_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1._derive_binding",
        lambda *args, relation_kind, **kwargs: _derive(relation_kind, args[0]),
    )
    receipt = build_relation_receipt_596_1(
        _complete_bundle(),
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
    )
    assert [item.receipt_role for item in receipt.relations] == ["terms", "rate_table"]
    assert [item.binding.relation_kind for item in receipt.relations] == ["section", "table"]
    assert "brochure" not in receipt.model_dump_json()
    assert "ADMIT" not in receipt.model_dump_json() and "READY" not in receipt.model_dump_json()
    assert replay_relation_receipt_596_1(receipt) == receipt


@pytest.mark.parametrize(
    "field", ["source_sha256", "parser_config_sha256", "policy_sha256", "replay_digest_sha256"]
)
def test_binding_and_receipt_drift_fail_closed(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    monkeypatch.setattr(
        "insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1._derive_binding",
        lambda *args, relation_kind, **kwargs: _derive(relation_kind, args[0]),
    )
    receipt = build_relation_receipt_596_1(
        _complete_bundle(),
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
    )
    payload = receipt.model_dump(mode="python")
    if field == "replay_digest_sha256":
        payload[field] = H
    else:
        payload["relations"][0]["binding"][field] = H
    with pytest.raises(RelationReceiptBridgeError):
        replay_relation_receipt_596_1(cast(Any, payload))


def test_private_atomic_publish_is_0600_no_replace_and_no_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = _verified_receipt(monkeypatch)
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    target = publish_relation_receipt_596_1(cast(Any, receipt), root)
    payload = target.read_bytes()
    assert target.name == "596-1-relation-receipt.json"
    assert target.read_bytes() == payload
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(RelationReceiptBridgeError, match="RECEIPT_OUTPUT_EXISTS"):
        publish_relation_receipt_596_1(cast(Any, receipt), root)
    assert target.read_bytes() == payload

    link = tmp_path / "linked"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(RelationReceiptBridgeError, match="OUTPUT_ROOT_NOT_PRIVATE"):
        publish_relation_receipt_596_1(cast(Any, receipt), link)


def test_failed_publish_has_zero_final_visibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    receipt = _verified_receipt(monkeypatch)

    def fail_link(*args: object, **kwargs: object) -> None:
        raise OSError("private body must not escape")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(RelationReceiptBridgeError, match="RECEIPT_PUBLISH_FAILED") as error:
        publish_relation_receipt_596_1(cast(Any, receipt), root)
    assert "private body" not in str(error.value)
    assert not (root / "596-1-relation-receipt.json").exists()
    assert list(root.iterdir()) == []
