"""OpenSpec 092: exact relation-bound three-source admission integration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler import native_mineru_cloud
from insurance_harness.compiler.material_profiles import (
    MaterialProfileResolution,
    MaterialProfileResolutionRequest,
    load_material_profile_catalog,
    resolve_material_profile,
)
from insurance_harness.compiler.parsed_documents import (
    CapabilityEvidenceV1,
    ParsedDocumentV1,
    ParseManifestV1,
    ParseQualityDecisionV1,
    build_parse_manifest,
    evaluate_parse_quality,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
    intake_mineru_capture_bundle_596_1,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    POLICY_SHA256,
    CrossPageMarkerReplayRequestV1,
    CrossPageRelationBindingV1,
    CrossPageTypedMarkerEvidenceV1,
    derive_cross_page_relation_596_1,
)
from insurance_harness.knowledge_compiler.relation_bound_admission_596_1 import (
    RelationBoundAdmissionResultV1,
    SourceAdmissionAuthorityV1,
    Trusted090RelationInputV1,
    TypedMarkerEndpointMapV1,
    TypedMarkerNodeV1,
    assemble_relation_bound_admission_596_1,
)
from insurance_harness.template_packages import (
    EvidencePolicy,
    FieldGroup,
    ProvenanceReceipt,
    TemplateApproval,
    TemplateCatalogEntry,
    TemplatePackageContent,
    TemplateScope,
    TemplateVersion,
    ValidatorRef,
)
from tests._mineru_marker_envelope_fixture_108 import (
    MarkerFixtureV1,
    attach_marker_envelope_108,
)

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "harness/tests/fixtures/material_profile_596_1_052.json"
TERMS_SHA = "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"
BROCHURE_SHA = "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"
RATE_SHA = "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"
RAW_SHA = "4" * 64


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _compact(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


class _TemplateCatalog:
    def __init__(self, entry: TemplateCatalogEntry) -> None:
        self.entry = entry

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        return self.entry if scope == self.entry.version.scope else None


def _template_catalog() -> _TemplateCatalog:
    catalog = load_material_profile_catalog(CATALOG)
    scope = TemplateScope(space_id="space-092", level="global")
    content = TemplatePackageContent(
        schema_version=catalog.schema_binding.schema_version,
        field_groups=(
            FieldGroup(
                group_id="group-092",
                field_ids=(catalog.schema_binding.field_ids[0],),
                evidence_roles=("terms",),
            ),
        ),
        role_prompts={"extract": "extract-092"},
        validators=(
            ValidatorRef(
                validator_id="validator-092",
                validator_version="v1",
                config_hash="1" * 64,
            ),
        ),
        evidence_policy=EvidencePolicy(require_quote=True, require_locator=True, minimum_sources=1),
        attempt_limits={"extract": 1},
        golden_slice_ref="gs-s0q-596-v1",
        provenance=(
            ProvenanceReceipt(
                migration_id="MIG-092-test",
                source_repository="PA-ALG/InsuranceKB-WeKnora",
                source_branch="main",
                source_commit="96d7e02c08f89d4fcaad629b2e8cc8e41dcf7e37",
                source_path="frontend/src/lib/product-catalog-modules.ts",
                source_language="typescript",
                rights_status="project-owned",
                accepted_behavior="exact task-local relation admission fixture",
                rejected_behavior="runtime authority invention",
                python_target="harness/tests/test_relation_bound_admission_596_1_092.py",
                translation_method="behavior_port_with_characterization_tests",
                characterization_tests=(
                    "harness/tests/test_relation_bound_admission_596_1_092.py",
                ),
            ),
        ),
    )
    version = TemplateVersion.from_content(
        package_id="life-template-package",
        version_id="092-test-v1",
        scope=scope,
        content=content,
    )
    return _TemplateCatalog(
        TemplateCatalogEntry(
            version=version,
            approval=TemplateApproval(
                approval_id="approval-092",
                package_id=version.package_id,
                version_id=version.version_id,
                scope=scope,
                content_hash=version.content_hash,
                state="approved",
            ),
        )
    )


def _resolutions() -> tuple[MaterialProfileResolution, ...]:
    catalog = load_material_profile_catalog(CATALOG)
    templates = _template_catalog()
    by_role = {item.material_role: item for item in catalog.profiles}
    return tuple(
        resolve_material_profile(
            catalog,
            templates,
            MaterialProfileResolutionRequest(
                space_id="space-092",
                product_code=catalog.product.product_code,
                product_version=catalog.product.product_version,
                schema_version=catalog.schema_binding.schema_version,
                schema_field_ids=catalog.schema_binding.field_ids,
                source=by_role[role].source,
                classified_material_role=role,
            ),
        )
        for role in ("terms", "brochure", "rate_table")
    )


def _parser() -> dict[str, object]:
    value: dict[str, object] = {
        "engine": "mineru_cloud",
        "implementation": "NewMinerUCloudReader",
        "native_structure_schema": "mineru-native-structure.v1",
        "model": "pipeline",
        "formula": True,
        "table": True,
        "ocr": True,
        "language": "ch",
        "config_sha256": "",
    }
    value["config_sha256"] = _sha(b"mineru-capture-config.v1\0" + _compact(value))
    return value


def _cross_page(source: str, capability: str) -> dict[str, object]:
    members = [{"category": "middle_json", "size": 17, "sha256": "3" * 64}]
    observation = _sha(f"mineru-cross-page-ambiguous.v1\0{source}\0cross_page\0p0/b0")
    facts: dict[str, object] = {
        "contract": "mineru-native-cross-page-facts.v1",
        "status": "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS",
        "required_capability": capability,
        "source_sha256": source,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "raw_zip_sha256": "1" * 64,
        "native_member_sha256": "2" * 64,
        "member_inventory_sha256": _sha(_compact(members)),
        "projection_sha256": "",
        "relation_count": 0,
        "ambiguous_marker_count": 1,
        "ambiguous_observation_hashes": [observation],
        "members": members,
        "relations": [],
    }
    facts["projection_sha256"] = _sha(
        _compact(
            {
                key: facts[key]
                for key in (
                    "contract",
                    "status",
                    "required_capability",
                    "source_sha256",
                    "parser_model",
                    "mineru_version",
                    "relation_count",
                    "ambiguous_marker_count",
                    "ambiguous_observation_hashes",
                    "relations",
                )
            }
        )
    )
    return facts


def _table(table_id: str, page: int, order: int) -> tuple[dict[str, object], dict[str, object]]:
    cell_id = f"cell-{order:06d}"
    return (
        {
            "table_id": table_id,
            "order_index": order,
            "page_number": page,
            "table_index": 0,
            "bbox": ["10", "20", "90", "80"],
            "content_hash": _sha(f"table-content-{table_id}"),
            "structure_hash": _sha(f"table-structure-{table_id}"),
            "row_count": 2,
            "column_count": 2,
            "header_cell_ids": [cell_id],
        },
        {
            "cell_id": cell_id,
            "order_index": order,
            "table_id": table_id,
            "page_number": page,
            "row_index": 0,
            "column_index": 0,
            "row_span": 2,
            "column_span": 2,
            "bbox": ["10", "20", "90", "80"],
            "content_hash": _sha("shared-header"),
            "structure_hash": _sha("shared-header-structure"),
        },
    )


def _structure(role: str, source: str) -> dict[str, object]:
    pages = [
        {
            "page_id": f"page-{index:04d}",
            "page_number": index,
            "content_hash": _sha(f"{role}-page-content-{index}"),
            "structure_hash": _sha(f"{role}-page-structure-{index}"),
        }
        for index in range(1, 3 if role != "brochure" else 2)
    ]
    blocks = [
        {
            "block_id": f"block-{index:06d}",
            "order_index": index,
            "page_number": index + 1,
            "block_index": 0,
            "bbox": ["10", "20", "90", "80"],
            "content_hash": _sha(f"{role}-block-content-{index}"),
            "structure_hash": _sha(f"{role}-block-structure-{index}"),
        }
        for index in range(1 if role == "brochure" else 2)
    ]
    table_count = 2 if role == "rate" else 1
    pairs = [_table(f"table-{index:06d}", index + 1, index) for index in range(table_count)]
    return {
        "contract": "mineru-native-structure.v1",
        "source_schema": "mineru.content-list.pipeline.v1",
        "parser_model": "pipeline",
        "source_sha256": source,
        "raw_sha256": RAW_SHA,
        "pages": pages,
        "blocks": blocks,
        "tables": [item[0] for item in pairs],
        "cells": [item[1] for item in pairs],
        "unsupported": (
            ["cross_page_sections"]
            if role == "terms"
            else ["cross_page_tables"]
            if role == "rate"
            else []
        ),
    }


def _capture(role: str, source: str) -> bytes:
    parser = _parser()
    structure = _structure(role, source)
    payload: dict[str, object] = {
        "contract": "mineru-semantic-content-custody.v2",
        "source_sha256": source,
        "attempt": {"attempt_number": 2, "attempt_role": "bounded_upgrade", "generation": 0},
        "raw_structure_sha256": RAW_SHA,
        "sanitized_structure_sha256": _sha(_compact(structure)),
        "sanitized_structure": structure,
        "content_snapshot_sha256": _sha("safe snapshot"),
        "content_snapshot": "safe snapshot",
        "capture_identity_sha256": "",
        "parser": parser,
        "calls": {"allocation_post": 1, "upload_put": 1, "status_get": 3, "zip_get": 1},
        "latency_milliseconds": 25,
        "status": "completed",
    }
    payload["capture_identity_sha256"] = _sha(
        _compact(
            {
                "contract": payload["contract"],
                "source_sha256": source,
                "attempt": payload["attempt"],
                "parser_config_sha256": parser["config_sha256"],
                "raw_structure_sha256": RAW_SHA,
                "sanitized_structure_sha256": payload["sanitized_structure_sha256"],
                "content_snapshot_sha256": payload["content_snapshot_sha256"],
            }
        )
    )
    if role == "terms":
        payload["cross_page_facts"] = _cross_page(source, "cross_page_sections")
    elif role == "rate":
        payload["cross_page_facts"] = _cross_page(source, "cross_page_tables")
    if role in {"terms", "rate"}:
        return attach_marker_envelope_108(
            payload,
            markers=(
                MarkerFixtureV1(
                    marker_kind="cross_page",
                    page_index=0,
                    structural_path="p0/b0",
                    node_type="text" if role == "terms" else "table",
                    local_index=0,
                ),
            ),
        )
    return _compact(payload) + b"\n"


def _bundle() -> MinerUCaptureBundle5961V1:
    return intake_mineru_capture_bundle_596_1(
        (
            _capture("terms", TERMS_SHA),
            _capture("brochure", BROCHURE_SHA),
            _capture("rate", RATE_SHA),
        )
    )


def _authorities() -> tuple[SourceAdmissionAuthorityV1, ...]:
    return tuple(
        SourceAdmissionAuthorityV1(
            role=cast(Any, role),
            space_id="space-092",
            source_id=f"source-{role}",
            source_revision_id=f"revision-{role}",
            snapshot_id=f"snapshot-{role}",
            snapshot_generation=0,
            attempt_id=f"attempt-{role}-2",
            canonical_envelope_hash=_sha(f"envelope-{role}"),
            concurrent_mutation_fence_hash=_sha(f"fence-{role}"),
        )
        for role in ("terms", "brochure", "rate")
    )


def _marker_map(
    source: str,
    relation_kind: str,
    node_type: str,
) -> TypedMarkerEndpointMapV1:
    values: dict[str, object] = {
        "contract": "typed-marker-endpoint-map.v1",
        "source_sha256": source,
        "marker_kind": "cross_page",
        "relation_kind": relation_kind,
        "source_node": TypedMarkerNodeV1(
            page_index=0,
            node_type=cast(Any, node_type),
            local_index=0,
            structural_path_sha256=_sha(f"{source}-source-structural-path"),
        ),
        "target_node": TypedMarkerNodeV1(
            page_index=1,
            node_type=cast(Any, node_type),
            local_index=0,
            structural_path_sha256=_sha(f"{source}-target-structural-path"),
        ),
    }
    hash_values = {
        **values,
        "source_node": cast(TypedMarkerNodeV1, values["source_node"]).model_dump(mode="python"),
        "target_node": cast(TypedMarkerNodeV1, values["target_node"]).model_dump(mode="python"),
    }
    return TypedMarkerEndpointMapV1.model_validate(
        {
            **values,
            "replay_digest_sha256": canonical_hash("typed-marker-endpoint-map.v1", hash_values),
        }
    )


def _marker_maps() -> tuple[TypedMarkerEndpointMapV1, TypedMarkerEndpointMapV1]:
    return (
        _marker_map(TERMS_SHA, "section", "text"),
        _marker_map(RATE_SHA, "table", "table"),
    )


class _MarkerReplay:
    def replay_typed_cross_page_marker(
        self, request: CrossPageMarkerReplayRequestV1
    ) -> CrossPageTypedMarkerEvidenceV1:
        section = request.relation_kind == "section"
        source_id = "block-000000" if section else "table-000000"
        target_id = "block-000001" if section else "table-000001"
        path = "p0/b0"
        values: dict[str, object] = {
            "contract": "cross-page-typed-marker-evidence.v1",
            "authority": "future-089-typed-marker-replay",
            "request_digest_sha256": request.request_digest_sha256,
            "marker_kind": "cross_page",
            "relation_kind": request.relation_kind,
            "marker_structural_path": path,
            "marker_path_sha256": canonical_hash("mineru-native-structural-path.v1", path),
            "source_endpoint_id": source_id,
            "source_page_number": 1,
            "source_endpoint_path_sha256": _sha(f"source-{source_id}"),
            "target_endpoint_id": target_id,
            "target_page_number": 2,
            "target_endpoint_path_sha256": _sha(f"target-{target_id}"),
        }
        return CrossPageTypedMarkerEvidenceV1.model_validate(
            {
                **values,
                "evidence_digest_sha256": canonical_hash(
                    "cross-page-typed-marker-evidence.v1", values
                ),
            }
        )


def _relations(
    bundle: MinerUCaptureBundle5961V1,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    *,
    relation_kind: str,
) -> CrossPageRelationBindingV1:
    return derive_cross_page_relation_596_1(
        bundle,
        document,
        manifest,
        relation_kind=cast(Any, relation_kind),
        marker_replay=_MarkerReplay(),
        preserve_marker_envelope=True,
    )


class _Future090Builder:
    """Synthetic 090 contract: relation injection plus no-argument replay closure."""

    def __init__(self, original: Callable[..., object], *, replay: bool = True) -> None:
        self.original = original
        self.replay = replay
        self.cached: dict[
            str, tuple[ParsedDocumentV1, ParseManifestV1, ParseQualityDecisionV1]
        ] = {}
        self.calls: dict[str, int] = {}
        self.relations: list[Trusted090RelationInputV1] = []

    def __call__(
        self, sanitized_json: bytes, **kwargs: object
    ) -> tuple[ParsedDocumentV1, ParseManifestV1, ParseQualityDecisionV1]:
        source = cast(Any, kwargs["subject"]).source_sha256
        bindings = cast(
            tuple[Trusted090RelationInputV1, ...],
            kwargs.pop("trusted_relation_bindings", ()),
        )
        self.calls[source] = self.calls.get(source, 0) + 1
        if bindings and not self.replay and source in self.cached:
            return cast(
                tuple[ParsedDocumentV1, ParseManifestV1, ParseQualityDecisionV1],
                self.original(sanitized_json, **kwargs),
            )
        if not bindings and self.replay and source in self.cached:
            return self.cached[source]
        base = cast(
            tuple[ParsedDocumentV1, ParseManifestV1, ParseQualityDecisionV1],
            self.original(sanitized_json, **kwargs),
        )
        if not bindings:
            if source == BROCHURE_SHA and self.calls[source] >= 2:
                self.cached[source] = base
            return base
        binding = Trusted090RelationInputV1.model_validate(bindings[0])
        self.relations.append(binding)
        document = base[0]
        capability = (
            "cross_page_sections"
            if binding.relation_kind == "section_continuation"
            else "cross_page_tables"
        )
        unsupported = tuple(item for item in document.unsupported if item.capability != capability)
        evidence = (
            *document.capability_evidence,
            CapabilityEvidenceV1(capability=capability, subject_refs=binding.endpoint_ids),
        )
        tables = document.tables
        if binding.relation_kind == "table_continuation":
            first, second = binding.endpoint_ids
            tables = tuple(
                item.model_copy(
                    update={
                        "continuation_table_ids": (second,)
                        if item.table_id == first
                        else (first,)
                        if item.table_id == second
                        else ()
                    }
                )
                for item in tables
            )
        document = ParsedDocumentV1.model_validate(
            {
                **document.model_dump(mode="python", exclude={"document_hash"}),
                "tables": tables,
                "capability_evidence": evidence,
                "unsupported": unsupported,
            }
        )
        resolution = MaterialProfileResolution.model_validate(kwargs["material_profile_resolution"])
        manifest = build_parse_manifest(document, resolution.profile)
        decision = evaluate_parse_quality(
            document=document,
            manifest=manifest,
            material_profile_resolution=resolution,
        )
        result = (document, manifest, decision)
        self.cached[source] = result
        return result


def _run(
    monkeypatch: pytest.MonkeyPatch, *, replay: bool = True
) -> tuple[RelationBoundAdmissionResultV1, _Future090Builder]:
    original = native_mineru_cloud.build_mineru_parsed_document_v1
    builder = _Future090Builder(original, replay=replay)
    monkeypatch.setattr(native_mineru_cloud, "build_mineru_parsed_document_v1", builder)
    result = assemble_relation_bound_admission_596_1(
        bundle=_bundle(),
        source_authorities=_authorities(),
        material_profile_resolutions=_resolutions(),
        marker_endpoint_mappings=_marker_maps(),
        relation_binding_provider=_relations,
        trusted_builder=builder,
    )
    return result, builder


def test_exact_three_sources_map_rate_and_finish_real_061_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, builder = _run(monkeypatch)

    assert result.status == "READY_FOR_QUALITY_FALSIFICATION"
    assert result.provider_calls == result.golden_reads == 0
    assert result.admission is not None
    assert result.admission.status == "READY_FOR_QUALITY_FALSIFICATION"
    assert [item.role for item in result.admitted_parse_artifacts] == [
        "terms",
        "brochure",
        "rate_table",
    ]
    assert [item.relation_kind for item in builder.relations] == [
        "section_continuation",
        "table_continuation",
        "section_continuation",
        "table_continuation",
    ]
    for binding in builder.relations:
        payload = binding.model_dump(mode="python", exclude={"binding_hash"})
        assert binding.binding_hash == canonical_hash("cross-page-relation-binding.v1", payload)
        assert binding.policy_context_hash != POLICY_SHA256
    terms, _, rate = result.admitted_parse_artifacts
    assert "cross_page_sections" in terms.manifest.satisfied_capabilities
    assert "cross_page_tables" in rate.manifest.satisfied_capabilities
    assert rate.document.tables[0].continuation_table_ids == ("table-000001",)
    assert rate.document.tables[1].continuation_table_ids == ("table-000000",)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda values: values[0].model_copy(update={"space_id": "other-space"}),
        lambda values: values[2].model_copy(update={"role": "terms"}),
        lambda values: values[1].model_copy(update={"source_revision_id": "unknown"}),
    ],
)
def test_authority_and_role_drift_fail_with_zero_bundle(
    monkeypatch: pytest.MonkeyPatch,
    mutation: Callable[[list[SourceAdmissionAuthorityV1]], SourceAdmissionAuthorityV1],
) -> None:
    original = native_mineru_cloud.build_mineru_parsed_document_v1
    builder = _Future090Builder(original)
    monkeypatch.setattr(native_mineru_cloud, "build_mineru_parsed_document_v1", builder)
    authorities = list(_authorities())
    changed = mutation(authorities)
    if changed.role == "terms" and authorities[2].role == "rate":
        authorities[2] = changed
    elif changed.space_id == "other-space":
        authorities[0] = changed
    else:
        authorities[1] = changed
    result = assemble_relation_bound_admission_596_1(
        bundle=_bundle(),
        source_authorities=tuple(authorities),
        material_profile_resolutions=_resolutions(),
        marker_endpoint_mappings=_marker_maps(),
        relation_binding_provider=_relations,
        trusted_builder=builder,
    )
    assert result.status == "BLOCKED_ON_INTAKE_AUTHORITY"
    assert result.admitted_parse_artifacts == ()
    assert result.provider_calls == result.golden_reads == 0


def test_090_must_replay_relation_receipts_and_never_expose_partial_brochure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = _run(monkeypatch, replay=False)
    assert result.status == "BLOCKED_ON_061_REPLAY"
    assert result.admitted_parse_artifacts == ()
    assert result.admission is None
    assert result.provider_calls == result.golden_reads == 0


def test_relation_binding_drift_fails_before_any_bundle_is_exposed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = native_mineru_cloud.build_mineru_parsed_document_v1
    builder = _Future090Builder(original)
    monkeypatch.setattr(native_mineru_cloud, "build_mineru_parsed_document_v1", builder)

    def drift(
        bundle: MinerUCaptureBundle5961V1,
        document: ParsedDocumentV1,
        manifest: ParseManifestV1,
        *,
        relation_kind: str,
    ) -> CrossPageRelationBindingV1:
        binding = _relations(bundle, document, manifest, relation_kind=relation_kind)
        return binding.model_copy(update={"parser_config_sha256": "9" * 64})

    result = assemble_relation_bound_admission_596_1(
        bundle=_bundle(),
        source_authorities=_authorities(),
        material_profile_resolutions=_resolutions(),
        marker_endpoint_mappings=_marker_maps(),
        relation_binding_provider=drift,
        trusted_builder=builder,
    )
    assert result.status == "BLOCKED_ON_RELATION_BINDING"
    assert result.admitted_parse_artifacts == ()
    assert result.provider_calls == result.golden_reads == 0


@pytest.mark.parametrize("insufficiency", ["missing-target", "hash-only-wrong-index"])
def test_089_metadata_must_uniquely_map_two_typed_nodes_not_path_hashes(
    monkeypatch: pytest.MonkeyPatch,
    insufficiency: str,
) -> None:
    original = native_mineru_cloud.build_mineru_parsed_document_v1
    builder = _Future090Builder(original)
    monkeypatch.setattr(native_mineru_cloud, "build_mineru_parsed_document_v1", builder)
    mappings = list(_marker_maps())
    source = mappings[0].source_node
    if insufficiency == "missing-target":
        mappings[0] = TypedMarkerEndpointMapV1.model_construct(
            **mappings[0].model_dump(mode="python", exclude={"target_node"}),
            target_node=None,
        )
    else:
        target = mappings[0].target_node.model_copy(update={"local_index": 1})
        values: dict[str, object] = {
            **mappings[0].model_dump(mode="python", exclude={"replay_digest_sha256"}),
            "source_node": source.model_dump(mode="python"),
            "target_node": target.model_dump(mode="python"),
        }
        mappings[0] = TypedMarkerEndpointMapV1.model_validate(
            {
                **values,
                "replay_digest_sha256": canonical_hash("typed-marker-endpoint-map.v1", values),
            }
        )
    result = assemble_relation_bound_admission_596_1(
        bundle=_bundle(),
        source_authorities=_authorities(),
        material_profile_resolutions=_resolutions(),
        marker_endpoint_mappings=cast(Any, tuple(mappings)),
        relation_binding_provider=_relations,
        trusted_builder=builder,
    )
    assert result.status == "BLOCKED_ON_RELATION_BINDING"
    assert result.admitted_parse_artifacts == ()
    assert result.provider_calls == result.golden_reads == 0
