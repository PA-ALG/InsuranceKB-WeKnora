"""Build source-bound admission context; no model or persistence effects."""

from __future__ import annotations

from typing import Any

from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCompileRequest830G3V1,
)
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    FieldAssertion,
    SourceBlock,
)
from insurance_harness.product_ingestion.discovery import build_discovery_knowledge_view
from insurance_harness.product_ingestion.native_admission_contract import (
    NativeAdmissionResponse,
    NativeAdmissionResponseV2,
    native_admission_prompt,
)
from insurance_harness.product_ingestion.native_discovery import NativeDiscoverySnapshot
from insurance_harness.product_ingestion.platform import DecodedSourceSnapshot
from insurance_harness.product_ingestion.stages import json_bytes


def resolve_native_window_sources(
    request: BatchConceptCompileRequest830G3V1,
    entity_id: str,
    snapshot: NativeDiscoverySnapshot,
    source: DecodedSourceSnapshot,
) -> tuple[SourceBlock, ...]:
    bindings = [row for row in request.entity_bindings if row.entity_id == entity_id]
    scope = request.base_request
    if (
        len(bindings) != 1
        or snapshot.phase != "snapshot"
        or len(snapshot.windows) != 1
        or snapshot.contract != "g3-platform-native-discovery-snapshot.830.v1"
        or snapshot.scope
        != {
            "tenant_id": scope.tenant_id,
            "space_id": scope.space_id,
            "raw_kb_id": scope.raw_kb_id,
            "wiki_kb_id": scope.wiki_kb_id,
        }
        or snapshot.source_snapshot_sha256 != source.snapshot["snapshot_sha256"]
        or snapshot.knowledge_id != source.snapshot["receipt"]["knowledge_id"]
        or snapshot.parse_attempt != source.snapshot["receipt"]["parse_attempt"]
    ):
        raise ValueError("native admission scope/source binding mismatch")
    allowed = {
        (b.revision_id, b.block_id)
        for entry in request.resolution_inputs.corpus.entries
        if entry.material_id in bindings[0].source_material_ids
        for b in entry.blocks
    }
    current = {(b.revision_id, b.block_id): b for b in scope.sources}
    blocks = {b.block_id: b for b in source.blocks}
    ids = snapshot.windows[0].chunk_ids
    if len(set(ids)) != len(ids) or not ids:
        raise ValueError("native admission window coverage invalid")
    selected = []
    for identity in ids:
        block = blocks.get(identity)
        if (
            block is None
            or (block.revision_id, block.block_id) not in allowed
            or current.get((block.revision_id, block.block_id)) != block
            or (block.knowledge_id, block.parse_attempt)
            != (snapshot.knowledge_id, snapshot.parse_attempt)
        ):
            raise ValueError("native admission source not in bound window")
        selected.append(block)
    return tuple(selected)


def render_native_admission_context(
    *,
    request: BatchConceptCompileRequest830G3V1,
    entity_id: str,
    snapshot: NativeDiscoverySnapshot,
    source: DecodedSourceSnapshot,
    max_context_bytes: int = 262144,
    dependency_policy: str | None = None,
    isolation_enabled: bool = False,
    effective_fields: tuple[FieldAssertion, ...] | None = None,
    relation_capability: str | None = None,
) -> dict[str, Any]:
    native_admission_prompt(dependency_policy)
    if type(isolation_enabled) is not bool or (isolation_enabled and dependency_policy is None):
        raise ValueError("native admission isolation policy invalid")
    blocks = resolve_native_window_sources(request, entity_id, snapshot, source)
    binding = next(row for row in request.entity_bindings if row.entity_id == entity_id)
    refs = {block.block_id: f"s{i + 1}" for i, block in enumerate(blocks)}
    candidates = []
    for i, row in enumerate(snapshot.candidates):
        if not set(row.source_chunks) <= refs.keys():
            raise ValueError("native candidate source outside window")
        candidates.append(
            {
                **row.model_dump(mode="json"),
                "candidate_ref": f"c{i + 1}",
                "source_chunks": [refs[key] for key in row.source_chunks],
            }
        )
    value: dict[str, Any] = {
        "contract": "native-knowledge-admission-context.830.v1",
        "native_snapshot_sha256": snapshot.snapshot_sha256,
        "source_snapshot_sha256": snapshot.source_snapshot_sha256,
        "entity": {
            "entity_id": entity_id,
            "entity_version": binding.entity_version,
            "display_name": binding.display_name,
        },
        "existing_knowledge": build_discovery_knowledge_view(request, entity_id),
        "knowledge_updates_enabled": request.knowledge_update_policy
        == "explicit-same-identity.830.v1",
        "native_candidates": candidates,
        "source_options": [
            {
                "source_ref": refs[b.block_id],
                "material_ref": b.knowledge_id,
                "page_number": b.page_number,
                "spans": [{"start": 0, "end": len(b.text), "quote": b.text}],
            }
            for b in blocks
        ],
        "content_rendering": {
            "definition": "body",
            "page": (
                "body + each '\\n条件：' + condition + each '\\n例外：' + exception "
                "+ optional '\\n有效期：' + valid_time"
            ),
        },
        "response_schema": NativeAdmissionResponse.model_json_schema(),
        "max_context_bytes": max_context_bytes,
    }
    if dependency_policy is not None:
        value["contract"] = "native-knowledge-admission-context.830.v2"
        value["dependency_policy"] = dependency_policy
        value["isolation_enabled"] = isolation_enabled
        value["response_schema"] = NativeAdmissionResponseV2.model_json_schema()
        value["member_contract"] = {
            "contract": "native-admission-member-guidance.830.v1",
            "pages": "Independently useful concepts, rules and explanations become Wiki pages.",
            "definitions": "Terminology definitions, each used by at least one supplied page.",
            "concept_refs": "Use a definition member_ref or an offered existing concept_id; "
            "never a canonical_key. Empty is valid when no definition is needed.",
            "coverage_rules": [
                "Preserve rights, duties, recipients, time limits, conditions, exceptions, "
                "formulas and illustration limitations for each useful supplied candidate.",
                "Never target a fixed page count or drop source-supported detail "
                "to shorten output.",
                "Separate model explanations from source-supported claims with content_provenance.",
            ],
            "reference_example": {
                "definition": {"member_ref": "d1", "canonical_key": "example_term"},
                "page": {"concept_refs": ["d1"]},
            },
        }
    if dependency_policy is not None and effective_fields is not None:
        from insurance_harness.product_ingestion.field_comparison import build_effective_field_view

        value["existing_knowledge"]["effective_fields"] = build_effective_field_view(
            request, entity_id, effective_fields
        )
    from insurance_harness.product_ingestion.native_relation_admission import (
        enable_relation_context,
    )

    enable_relation_context(value, relation_capability)
    if (
        type(max_context_bytes) is not int
        or max_context_bytes < 1
        or len(json_bytes(value)) > max_context_bytes
    ):
        raise ValueError("native admission context budget exceeded")
    return value
