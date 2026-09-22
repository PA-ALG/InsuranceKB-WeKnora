"""Pure, bounded projection of a verified checkpoint onto one current base."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from insurance_harness.knowledge_compiler import (
    batch_concept_compile_830_g3 as compiler,
)
from insurance_harness.knowledge_compiler import (
    batch_entity_resolution_830_g3 as resolver,
)
from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_json_bytes_830_g3
from insurance_harness.knowledge_compiler.g3_field_tasks import adapt_catalog_field_tasks
from insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3 import validate_catalog
from insurance_harness.product_ingestion.compilation import (
    build_existing_snapshot,
    build_platform_compile_request,
    project_field_attempts,
)
from insurance_harness.product_ingestion.field_validation import (
    FieldValidationReport,
    apply_field_validation,
)
from insurance_harness.product_ingestion.models import FieldAttemptSnapshot, ProductScope
from insurance_harness.product_ingestion.stages import json_bytes


def rebase_checkpoint_inputs(
    *,
    scope: ProductScope,
    base_body: Mapping[str, Any],
    base_raw: bytes,
    catalog_json: bytes,
    profile_confirmation_json: bytes,
    policy: resolver.BatchResolutionPolicyV1,
    identity_payload: bytes,
    original_request: bytes,
    original_attempts: tuple[FieldAttemptSnapshot, ...],
    original_field_validation: bytes,
    run_id: str,
) -> dict[str, bytes]:
    """Validate the complete old field report before selecting current exact tasks."""
    identity = json.loads(identity_payload)
    corpus = resolver.BatchCorpusV1.model_validate(identity["corpus"])
    proposals = resolver.ProposalBatchV1.model_validate(identity["proposals"])
    old_resolution = resolver.BatchEntityResolutionV1.model_validate(identity["resolution"])
    old_request = compiler.BatchConceptCompileRequest830G3V1.model_validate_json(
        original_request
    )
    # The original full attempt set and its authenticated derived view are
    # checked before any carry filtering. A missing attempt cannot become zero.
    effective = apply_field_validation(
        tuple(original_attempts),
        FieldValidationReport.model_validate_json(original_field_validation),
    )
    existing = build_existing_snapshot(scope=scope, base_body=base_body, policy=policy)
    resolution = resolver.resolve_batch(
        catalog=validate_catalog(catalog_json),
        corpus=corpus,
        proposals=proposals,
        existing_entities=existing,
        policy=policy,
        compiler_version=old_resolution.compiler_version,
    )
    if any(row.disposition not in {"CREATE", "MATCH"} for row in resolution.decisions):
        raise ValueError("rebased identity needs confirmation")
    selected_refs = tuple(tuple(row) for row in identity["selected_refs"])
    request = build_platform_compile_request(
        scope=scope, base_body=base_body, catalog_json=catalog_json,
        profile_confirmation_json=profile_confirmation_json,
        corpus=corpus, proposals=proposals, policy=policy,
        resolution=resolution, selected_refs=selected_refs,
    )
    old_ids = set(identity["current_entity_ids"])
    old_bindings = {row.entity_id: row for row in old_request.entity_bindings
                    if row.entity_id in old_ids}
    new_bindings = {row.entity_id: row for row in request.entity_bindings
                    if row.entity_id in old_ids}
    if set(old_bindings) != old_ids or set(new_bindings) != old_ids:
        raise ValueError("rebased identity entity changed")
    for entity_id in old_ids:
        old, new = old_bindings[entity_id], new_bindings[entity_id]
        for binding_field in (
            "entity_version", "issuer", "schema_pack_id", "schema_pack_sha256",
            "schema_version", "source_material_ids", "required_fields",
        ):
            if getattr(old, binding_field) != getattr(new, binding_field):
                raise ValueError("rebased identity binding changed")
    by_key = {(row.entity_id, row.field_key): row for row in effective}
    selected: list[FieldAttemptSnapshot] = []
    for task in adapt_catalog_field_tasks(request):
        key = (task.entity_id, task.field_key)
        row = by_key.get(key)
        if row is None or row.task_sha256 != task.task_sha256:
            raise ValueError("rebased request needs a new field extraction")
        selected.append(row)
    delta = project_field_attempts(request=request, attempts=tuple(selected), run_id=run_id)
    identity_record = {
        "contract": "product-rebased-identity.830.v1",
        "origin_identity_sha256": old_resolution.batch_sha256,
        "corpus": corpus,
        "proposals": proposals,
        "resolution": resolution,
        "selected_refs": selected_refs,
        "current_entity_ids": sorted(old_ids),
        "base_snapshot_sha256": base_body["snapshot_sha256"],
    }
    return {
        "rebased_base_snapshot": base_raw,
        "rebased_compile_request": batch_json_bytes_830_g3(request),
        "rebased_identity": json_bytes(identity_record),
        "rebased_compile_delta": delta.model_dump_json().encode(),
    }
