from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
from collections import Counter
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn, TypedDict, cast

import pytest

from insurance_harness.knowledge_compiler.schema_wiki_contracts import schema_wiki_sha256

_REPO = Path(__file__).parents[2]
_BUNDLE = Path(
    os.environ.get(
        "G1_ACTUAL_C5_BUNDLE",
        "/private/tmp/weknora-815-final-06e08c.sbD1nuoR/c5-bundle-v3",
    )
)
_PROFILE = _REPO / "docs/insurance-kb/evidence/830-g1/medical-presentation-profile.v1.json"
_VECTOR = Path(__file__).parent / "fixtures/entity_page_graph_830_g1_contract_vector.json"
_MODULE = "insurance_harness.knowledge_compiler.entity_page_graph_830_g1"
_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_SHA_D = "d" * 64
_VECTOR_SHA256 = "cffb39e5a7214e2720b54a80acacab6923afa8e00e6174befc88b3cd44e069d1"


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _c5_object_sha256(contract: str, value: object) -> str:
    return hashlib.sha256(
        b"weknora.schema-wiki-c5.815.v1\0"
        + contract.encode("ascii")
        + b"\0"
        + _canonical_json_bytes(value)
    ).hexdigest()


def _rehash_member(member: dict[str, object]) -> None:
    payload = member["payload"]
    assert type(payload) is dict
    member["payload_sha256"] = schema_wiki_sha256(cast(str, payload["contract"]), payload)
    preimage = {key: value for key, value in member.items() if key != "member_digest"}
    member["member_digest"] = schema_wiki_sha256(cast(str, member["contract"]), preimage)


def _rehash_manifest(wire: dict[str, object]) -> None:
    preimage = {key: value for key, value in wire.items() if key != "manifest_sha256"}
    wire["manifest_sha256"] = schema_wiki_sha256(cast(str, wire["contract"]), preimage)


def _graph_module() -> ModuleType | None:
    if importlib.util.find_spec(_MODULE) is None:
        return None
    return importlib.import_module(_MODULE)


def _legacy_fail(requirement: str, expected: str, actual: str) -> NoReturn:
    pytest.fail(
        f"{requirement} business RED: expected {expected}; actual {actual} "
        "(legacy Schema Wiki contract has 75 root/section/field members and no entity page graph)"
    )


def _actual_context(graph: ModuleType, **updates: object) -> Any:
    values: dict[str, object] = {
        "release_id": "release-42a3dd0c-ec76-4017-a288-37f1b13519a0",
        "activation_epoch": 2,
        "space_id": "a8751a40-83ce-55c8-a160-079b283483ca",
        "wiki_kb_id": "8d5695de-f255-42d5-9a41-042ba86e97b9",
        "entity_id": "ping-an-e-sheng-bao",
        "entity_version_id": "ping-an-e-sheng-bao@596-1",
        "display_name": "平安e生保（尊享版）医疗保险",
        "classification_display_name": "医疗险",
        "expected_candidate_sha256": (
            "4aebf1e1b755e7d4dee4ea62dac86318f6229aeca6bc2ca52510dcf8883efea1"
        ),
        "expected_candidate_file_sha256": (
            "7799539c4b44e74e1b157ccfae2ab6f32b0eecfb1e9415e70b15751a3f5fb3ca"
        ),
        "expected_claim_set_sha256": (
            "2586b88cae0f3a13c55e2be7f08fa9f892261264c01f9ca75a21ff05b614354c"
        ),
        "expected_evidence_receipt_set_sha256": (
            "6f868c773d652a46347ce4b3c38aa55fa50e8b09d56a05906070307f3abec2b4"
        ),
        "expected_evidence_authority_sha256": (
            "d56cd38c18ccc1aa511b0a1f89ffdf52899d477cbf5336b6f84ee9662bc995d0"
        ),
        "expected_evidence_authority_file_sha256": (
            "35023c59acebc1b1c4131b24da6019d91c5f18f81c99b444db0c39e11db521c1"
        ),
        "expected_bundle_manifest_sha256": (
            "b2a8f157e097502bc5074c5930a28a73c08c7dbd99fd76439b65eb1c66694a3b"
        ),
        "expected_bundle_manifest_file_sha256": (
            "d4efedad59f5e8c4301cd655bb9fc75b491315e310c42066086d6c963e447c25"
        ),
        "expected_preview_sha256": (
            "742b98610caf4fb7440c448575f12b5c9c4361238c7d7a18a881a4b172db2e2a"
        ),
        "expected_preview_file_sha256": (
            "7c9c59a8486268a9d2ff4cb5a0d09b2790affabfeb147b93ebc710f9cc4e3934"
        ),
        "expected_profile_sha256": (
            "d83a3b38e3b72bd986823d373b86fe1077e0baa6333a27dc74a2545f58bfd3e9"
        ),
        "expected_profile_file_sha256": (
            "72a1e36215c313b26092c9fd640a03c7d6ba8d7f95a94b11005edc9710ab8859"
        ),
    }
    values.update(updates)
    return graph.EntityPageCompileContextV1(**values)


def _actual_paths_or_skip() -> dict[str, Path]:
    paths = {
        "candidate": _BUNDLE / "formal-candidate.json",
        "authority": _BUNDLE / "candidate-evidence-authority.json",
        "manifest": _BUNDLE / "manifest.json",
        "preview": _BUNDLE / "preview.json",
        "profile": _PROFILE,
    }
    missing = tuple(str(path) for path in paths.values() if not path.is_file())
    if missing:
        pytest.skip(f"actual C5 replay inputs unavailable: {', '.join(missing)}")
    return paths


def _compile_actual_with(
    graph: ModuleType,
    *,
    context_updates: dict[str, object] | None = None,
    candidate_bytes: bytes | None = None,
    evidence_authority_bytes: bytes | None = None,
    bundle_manifest_bytes: bytes | None = None,
    profile_bytes: bytes | None = None,
) -> Any:
    paths = _actual_paths_or_skip()
    return graph.compile_actual_815_entity_page_manifest(
        candidate_bytes=(
            candidate_bytes if candidate_bytes is not None else paths["candidate"].read_bytes()
        ),
        evidence_authority_bytes=(
            evidence_authority_bytes
            if evidence_authority_bytes is not None
            else paths["authority"].read_bytes()
        ),
        bundle_manifest_bytes=(
            bundle_manifest_bytes
            if bundle_manifest_bytes is not None
            else paths["manifest"].read_bytes()
        ),
        preview_bytes=paths["preview"].read_bytes(),
        profile_bytes=profile_bytes if profile_bytes is not None else paths["profile"].read_bytes(),
        context=_actual_context(graph, **(context_updates or {})),
    )


@lru_cache(maxsize=1)
def _vector_manifest() -> Any | None:
    graph = _graph_module()
    return (
        None
        if graph is None
        else graph.EntityPageManifestV1.model_validate_json(_VECTOR.read_bytes())
    )


def _vector_assertions(graph: ModuleType, manifest: Any) -> tuple[Any, ...]:
    return tuple(
        graph.FieldAssertionInputV1(
            field_key=member.payload.field_key,
            state=member.payload.state,
            value_snapshot=member.payload.value_snapshot,
            unknown_reason=member.payload.unknown_reason,
            source_typed_reason=member.payload.source_typed_reason,
            evidence_receipt_sha256s=member.payload.reference.evidence_receipt_sha256s,
            citations=member.payload.citations,
        )
        for member in manifest.members
        if member.page_kind == "field"
    )


def _vector_context(graph: ModuleType, manifest: Any, **updates: object) -> Any:
    values = {
        "release_id": manifest.release_id,
        "activation_epoch": manifest.activation_epoch,
        "space_id": manifest.space_id,
        "wiki_kb_id": manifest.wiki_kb_id,
        "entity_id": manifest.entity_id,
        "entity_version_id": manifest.entity_version_id,
        "display_name": manifest.display_name,
        "classification_display_name": manifest.classification_display_name,
    }
    values.update(updates)
    return graph.EntityPageCompileContextV1(**values)


def _member(manifest: Any, *, kind: str, key: str) -> Any:
    matches = [
        item for item in manifest.members if item.page_kind == kind and item.stable_key == key
    ]
    assert len(matches) == 1
    return matches[0]


def _mutated_profile(graph: ModuleType, manifest: Any) -> Any:
    payload = manifest.profile.model_dump(mode="json")
    payload["sections"][1]["display_name"] = "合同与投保（新标题）"
    payload["sections"][1]["fields"][1]["short_title"] = "谁可以投保"
    payload["profile_sha256"] = schema_wiki_sha256(
        payload["contract"],
        {key: value for key, value in payload.items() if key != "profile_sha256"},
    )
    return graph.PresentationProfileV1.model_validate(payload)


def test_g1_r1_stable_entity_page_ids_and_routes_ignore_titles_and_classification() -> None:
    graph = _graph_module()
    baseline = _vector_manifest()
    if graph is None or baseline is None:
        _legacy_fail("G1-R1", "76 stable entity-scoped page IDs/routes", "0")

    changed = graph.compile_entity_page_manifest(
        context=_vector_context(
            graph,
            baseline,
            display_name="平安e生保尊享版（展示名变更）",
            classification_display_name="健康险 / 医疗",
        ),
        profile=_mutated_profile(graph, baseline),
        input_authority=baseline.input_authority,
        assertions=_vector_assertions(graph, baseline),
    )

    assert [(m.page_id, m.namespace, m.route) for m in changed.members] == [
        (m.page_id, m.namespace, m.route) for m in baseline.members
    ]
    assert baseline.members[0].route.endswith("/entities/ping-an-e-sheng-bao/overview")
    assert baseline.members[-1].route.endswith("/entities/ping-an-e-sheng-bao/free-wiki")


def test_g1_r2_frozen_vector_has_exact_unique_76_member_bijection() -> None:
    graph = _graph_module()
    manifest = _vector_manifest()
    if graph is None or manifest is None:
        _legacy_fail("G1-R2", "76 unique members and 67 FieldAssertions", "75 and 0")

    assert graph.sha256_hex(_VECTOR.read_bytes()) == _VECTOR_SHA256
    counts = Counter(item.page_kind for item in manifest.members)
    assert counts == {"overview": 1, "section": 7, "field": 67, "free_wiki": 1}
    assert len(manifest.members) == len({item.page_id for item in manifest.members}) == 76
    assert (
        len(manifest.field_assertion_page_ids) == len(set(manifest.field_assertion_page_ids)) == 67
    )
    assert manifest.free_wiki_empty is True
    assert json.loads(_VECTOR.read_bytes()) == manifest.model_dump(mode="json")


def test_g1_r3_all_67_field_assertions_preserve_exact_tri_state() -> None:
    manifest = _vector_manifest()
    if manifest is None:
        _legacy_fail("G1-R3", "67 FieldAssertions with 2/1/64 tri-state", "0/0/0")

    fields = [item.payload for item in manifest.members if item.page_kind == "field"]
    assert Counter(item.state for item in fields) == {
        "present": 2,
        "absent_explicitly": 1,
        "unknown": 64,
    }
    unknown = next(item for item in fields if item.field_key == "cooling_off_period")
    assert unknown.state == "unknown"
    assert unknown.value_snapshot is None
    assert unknown.citations == ()
    assert unknown.reference.evidence_receipt_sha256s == ()
    assert unknown.unknown_reason == "FIELD_UNKNOWN"
    assert unknown.source_typed_reason == "live_chunk_quote_not_unique"
    assert unknown.display_value is None
    assert Counter(item.source_typed_reason for item in fields if item.state == "unknown") == {
        "ANSWER_NOT_FOUND": 3,
        "FORMATION_MODE_DEFERRED": 32,
        "SOURCE_LOCATION_UNRESOLVED": 10,
        "SOURCE_NOT_AVAILABLE": 10,
        "live_chunk_quote_not_unique": 9,
    }


def test_g1_r4_known_page_section_and_overview_share_exact_claim_evidence_and_citation() -> None:
    graph = _graph_module()
    manifest = _vector_manifest()
    if graph is None or manifest is None:
        _legacy_fail("G1-R4", "same release-bound Claim/Evidence/citation refs", "none")

    field = _member(manifest, kind="field", key="insured_eligibility")
    section = _member(manifest, kind="section", key="application-and-contract")
    overview = _member(manifest, kind="overview", key="overview")
    field_ref = field.payload.reference
    section_ref = next(
        item for item in section.payload.field_assertions if item.field_key == field_ref.field_key
    )
    overview_ref = next(
        item for item in overview.payload.field_assertions if item.field_key == field_ref.field_key
    )

    assert field_ref == section_ref == overview_ref
    assert field.release_id == section.release_id == overview.release_id == manifest.release_id
    assert field_ref.source_release_id == manifest.release_id
    assert field_ref.source_candidate_sha256 == manifest.input_authority.candidate_sha256
    assert field_ref.product_version_id == manifest.input_authority.product_version_id
    assert field_ref.claim_sha256 == graph.field_claim_sha256(
        source_release_id=manifest.release_id,
        source_candidate_sha256=manifest.input_authority.candidate_sha256,
        product_version_id=manifest.input_authority.product_version_id,
        field_id=field.payload.field_key,
        state=field.payload.state,
        value_snapshot=field.payload.value_snapshot,
    )
    assert not hasattr(field_ref, "claim_id")
    tampered_payload = field.payload.model_dump(mode="python")
    tampered_payload["reference"]["claim_sha256"] = _SHA_A
    with pytest.raises(ValueError, match="FieldAssertion claim hash mismatch"):
        graph.FieldAssertionPayloadV1.model_validate(tampered_payload)
    assert len(field.payload.citations) == 3
    first = field.payload.citations[0]
    assert first.source_revision_id == (
        "ea7160149d2fd99ea4a4960c50bfa6ca3641e4532956671b9956f4f8b57ad681"
    )
    assert first.page_number == 2
    assert first.locator_ref == (
        "block-35d8d0accd7cc0e9669496a7512fb82ba417d7cde0175f824b67d924dd5d379d"
    )
    assert first.quote_snapshot == (
        "您可以同时为符合我们承保条件的家庭成员投保本产品，家庭成员仅指投保"
    )
    assert field_ref.citation_sha256s == tuple(
        item.citation_sha256 for item in field.payload.citations
    )


def test_g1_r4_fully_rehashed_section_cross_reference_drift_fails_closed() -> None:
    graph = _graph_module()
    if graph is None:
        _legacy_fail("G1-R4", "closed section-to-field reference topology", "no compiler")

    wire = json.loads(_VECTOR.read_bytes())
    section = next(item for item in wire["members"] if item["page_kind"] == "section")
    section["payload"]["field_assertions"][0]["page_id"] = "page_crossref_drift"
    _rehash_member(section)
    _rehash_manifest(wire)

    with pytest.raises(ValueError, match="entity page manifest closure or hash mismatch"):
        graph.EntityPageManifestV1.model_validate(wire)


def test_g1_r2_fully_rehashed_overview_section_page_drift_fails_closed() -> None:
    graph = _graph_module()
    if graph is None:
        _legacy_fail("G1-R2", "overview-to-section page topology closure", "no compiler")

    wire = json.loads(_VECTOR.read_bytes())
    overview = next(item for item in wire["members"] if item["page_kind"] == "overview")
    overview["payload"]["ordered_section_page_ids"][0] = "page_section_drift"
    _rehash_member(overview)
    _rehash_manifest(wire)

    with pytest.raises(ValueError, match="entity page manifest closure or hash mismatch"):
        graph.EntityPageManifestV1.model_validate(wire)


@pytest.mark.parametrize(
    "reference_key",
    ("citation_sha256s", "evidence_receipt_sha256s"),
)
def test_g1_r4_fully_rehashed_field_reference_evidence_drift_fails_closed(
    reference_key: str,
) -> None:
    graph = _graph_module()
    if graph is None:
        _legacy_fail("G1-R4", "field citation and receipt reference closure", "no compiler")

    wire = json.loads(_VECTOR.read_bytes())
    members = wire["members"]
    field = next(
        item
        for item in members
        if item["page_kind"] == "field" and item["stable_key"] == "insured_eligibility"
    )
    replacement = list(field["payload"]["reference"][reference_key])
    if reference_key == "citation_sha256s":
        replacement[0] = _SHA_A
    else:
        replacement.append(_SHA_A)

    affected = [field]
    field["payload"]["reference"][reference_key] = replacement
    for member in members:
        if member["page_kind"] not in ("overview", "section"):
            continue
        matching = [
            reference
            for reference in member["payload"]["field_assertions"]
            if reference["field_key"] == "insured_eligibility"
        ]
        if matching:
            matching[0][reference_key] = replacement
            affected.append(member)
    for member in affected:
        _rehash_member(member)
    _rehash_manifest(wire)

    with pytest.raises(ValueError, match="FieldAssertion evidence reference mismatch"):
        graph.EntityPageManifestV1.model_validate(wire)


def test_g1_r5_short_titles_are_distinct_from_full_namespace_and_page_id() -> None:
    manifest = _vector_manifest()
    if manifest is None:
        _legacy_fail(
            "G1-R5",
            "Chinese short titles plus canonical namespace/page ID",
            "field_id only",
        )

    expected = {
        "insured_eligibility": "投保范围",
        "guaranteed_renewal_period": "保证续保期",
        "cooling_off_period": "犹豫期",
    }
    for field_key, short_title in expected.items():
        member = _member(manifest, kind="field", key=field_key)
        assert member.short_title == short_title
        assert member.page_id.startswith("page_") and len(member.page_id) == 69
        assert member.namespace == (
            "urn:jlx:wiki:a8751a40-83ce-55c8-a160-079b283483ca:"
            f"entity:ping-an-e-sheng-bao:field:{field_key}"
        )
        assert member.short_title not in member.namespace


def test_g1_r8_manifest_is_rebuildable_payload_not_a_second_serving_authority() -> None:
    graph = _graph_module()
    manifest = _vector_manifest()
    if graph is None or manifest is None:
        _legacy_fail("G1-R8", "compiler-only rebuildable payload with empty free_wiki", "unfrozen")

    replayed = graph.EntityPageManifestV1.model_validate(manifest.model_dump(mode="python"))
    rebuilt = graph.compile_entity_page_manifest(
        context=_vector_context(graph, manifest),
        profile=manifest.profile,
        input_authority=manifest.input_authority,
        assertions=_vector_assertions(graph, manifest),
    )
    wire = json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    assert replayed == rebuilt == manifest
    assert manifest.authority.serving_authority == "WEKNORA"
    assert manifest.authority.harness_role == "OFFLINE_PURE_COMPILER"
    assert manifest.authority.per_page_activation_allowed is False
    assert manifest.authority.rendered_content_authoritative is False
    assert "markdown" not in wire.lower()
    assert _member(manifest, kind="free_wiki", key="free-wiki").payload.items == ()


def test_g1_r9_generic_compiler_accepts_ordered_two_section_profile() -> None:
    graph = _graph_module()
    if graph is None:
        _legacy_fail("G1-R9", "profile-driven 2-section compiler output", "7-section-only legacy")

    sections = [
        {
            "section_key": "identity",
            "display_name": "身份",
            "fields": [{"field_key": "name", "short_title": "名称"}],
        },
        {
            "section_key": "terms",
            "display_name": "条款",
            "fields": [{"field_key": "term", "short_title": "期限"}],
        },
    ]
    profile_payload = {
        "contract": "presentation-profile.v1",
        "profile_id": "two-section.test.v1",
        "profile_version": "v1",
        "schema_pack_id": "two-field.test.v1",
        "schema_version": "v1",
        "schema_pack_sha256": _SHA_A,
        "sections": sections,
    }
    profile = graph.PresentationProfileV1.model_validate(
        {
            **profile_payload,
            "profile_sha256": schema_wiki_sha256("presentation-profile.v1", profile_payload),
        }
    )
    assertions = tuple(
        graph.FieldAssertionInputV1(
            field_key=field_key,
            state="unknown",
            value_snapshot=None,
            unknown_reason="FIELD_UNKNOWN",
            source_typed_reason="SYNTHETIC_SOURCE_UNAVAILABLE",
            evidence_receipt_sha256s=(),
            citations=(),
        )
        for field_key in ("name", "term")
    )
    claim_set_sha256 = graph.claim_input_set_sha256(
        candidate_sha256=_SHA_A,
        product_version_id="test-v1",
        assertions=assertions,
    )
    authority = graph.ManifestInputAuthorityV1(
        candidate_contract="two-field-candidate.v1",
        candidate_sha256=_SHA_A,
        candidate_file_sha256=_SHA_B,
        product_version_id="test-v1",
        claim_set_sha256=claim_set_sha256,
        evidence_receipt_set_sha256=_SHA_C,
        evidence_authority_contract="two-field-evidence.v1",
        evidence_authority_sha256=_SHA_D,
        evidence_authority_file_sha256=_SHA_A,
        source_authorities=(),
        actual_files=graph.ActualInputFilesV1(
            bundle_manifest_contract="synthetic-bundle.v1",
            bundle_manifest_sha256=_SHA_A,
            bundle_manifest_file_sha256=_SHA_B,
            preview_contract="synthetic-preview.v1",
            preview_sha256=_SHA_C,
            preview_file_sha256=_SHA_D,
            profile_file_sha256=_SHA_A,
        ),
    )
    authority_without_custody = authority.model_dump(mode="python")
    authority_without_custody.pop("actual_files")
    with pytest.raises(ValueError, match="actual_files"):
        graph.ManifestInputAuthorityV1.model_validate(authority_without_custody)
    context = graph.EntityPageCompileContextV1(
        release_id="release-test-v1",
        activation_epoch=1,
        space_id="space-test",
        wiki_kb_id="wiki-test",
        entity_id="entity-test",
        entity_version_id="entity-test@test-v1",
        display_name="双节点测试实体",
        classification_display_name="测试分类",
    )
    manifest = graph.compile_entity_page_manifest(
        context=context,
        profile=profile,
        input_authority=authority,
        assertions=assertions,
    )

    assert [(m.page_kind, m.stable_key) for m in manifest.members] == [
        ("overview", "overview"),
        ("section", "identity"),
        ("section", "terms"),
        ("field", "name"),
        ("field", "term"),
        ("free_wiki", "free-wiki"),
    ]
    assert manifest.section_count == 2
    assert manifest.field_assertion_count == 2


def test_actual_c5_replay_matches_frozen_contract_vector_or_skips_explicitly() -> None:
    graph = _graph_module()
    vector = _vector_manifest()
    if graph is None or vector is None:
        _legacy_fail("G1-C5", "actual replay matches frozen contract vector", "no compiler")

    actual = _compile_actual_with(graph)

    assert actual == vector


def test_actual_fully_rehashed_missing_source_authority_fails_closed() -> None:
    graph = _graph_module()
    if graph is None:
        _legacy_fail("G1-R4", "every citation has one source authority", "no compiler")

    paths = _actual_paths_or_skip()
    authority = json.loads(paths["authority"].read_bytes())
    authority["source_authorities"] = []
    authority_payload = {
        key: value for key, value in authority.items() if key != "authority_sha256"
    }
    authority["authority_sha256"] = schema_wiki_sha256(authority["contract"], authority_payload)
    authority_bytes = _canonical_json_bytes(authority)
    authority_file_sha256 = graph.sha256_hex(authority_bytes)

    bundle = json.loads(paths["manifest"].read_bytes())
    bundle["candidate_evidence_authority_sha256"] = authority["authority_sha256"]
    bundle["candidate_evidence_authority_file_sha256"] = authority_file_sha256
    authority_member = next(
        item for item in bundle["members"] if item["name"] == "candidate-evidence-authority.json"
    )
    authority_member["sha256"] = authority_file_sha256
    authority_member["size_bytes"] = len(authority_bytes)
    bundle_payload = {key: value for key, value in bundle.items() if key != "manifest_sha256"}
    bundle["manifest_sha256"] = _c5_object_sha256(bundle["contract"], bundle_payload)
    bundle_bytes = _canonical_json_bytes(bundle)

    with pytest.raises(graph.EntityPageGraphError):
        _compile_actual_with(
            graph,
            evidence_authority_bytes=authority_bytes,
            bundle_manifest_bytes=bundle_bytes,
            context_updates={
                "expected_evidence_authority_sha256": authority["authority_sha256"],
                "expected_evidence_authority_file_sha256": authority_file_sha256,
                "expected_bundle_manifest_sha256": bundle["manifest_sha256"],
                "expected_bundle_manifest_file_sha256": graph.sha256_hex(bundle_bytes),
            },
        )


def test_actual_external_drift_always_raises_stable_graph_error() -> None:
    graph = _graph_module()
    if graph is None:
        _legacy_fail("G1-DRIFT", "typed fail-closed drift errors", "no compiler")

    paths = _actual_paths_or_skip()
    candidate = json.loads(paths["candidate"].read_bytes())
    candidate["fields"][0]["field_id"] = "candidate-bytes-drift"
    candidate_bytes = json.dumps(
        candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()

    authority = json.loads(paths["authority"].read_bytes())
    join = authority["join_receipts"][0]
    join["locator_ref"] = f"{join['locator_ref']}-drift"
    join["receipt_sha256"] = schema_wiki_sha256(
        join["contract"], {key: value for key, value in join.items() if key != "receipt_sha256"}
    )
    authority["authority_sha256"] = schema_wiki_sha256(
        authority["contract"],
        {key: value for key, value in authority.items() if key != "authority_sha256"},
    )
    authority_bytes = json.dumps(
        authority, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()

    profile = json.loads(paths["profile"].read_bytes())
    profile["sections"][0]["display_name"] = "profile-hash-drift"
    profile_bytes = json.dumps(
        profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()

    class CompileActualKwargs(TypedDict, total=False):
        candidate_bytes: bytes
        evidence_authority_bytes: bytes
        profile_bytes: bytes
        context_updates: dict[str, object]

    cases: tuple[CompileActualKwargs, ...] = (
        {
            "candidate_bytes": candidate_bytes,
            "context_updates": {
                "expected_candidate_file_sha256": graph.sha256_hex(candidate_bytes)
            },
        },
        {
            "evidence_authority_bytes": authority_bytes,
            "context_updates": {
                "expected_evidence_authority_sha256": authority["authority_sha256"],
                "expected_evidence_authority_file_sha256": graph.sha256_hex(authority_bytes),
            },
        },
        {
            "profile_bytes": profile_bytes,
            "context_updates": {"expected_profile_file_sha256": graph.sha256_hex(profile_bytes)},
        },
    )
    for kwargs in cases:
        with pytest.raises(graph.EntityPageGraphError) as caught:
            _compile_actual_with(graph, **kwargs)
        assert caught.value.__cause__ is None
