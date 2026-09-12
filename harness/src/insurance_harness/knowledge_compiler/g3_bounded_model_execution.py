"""Sole command boundary and deterministic helpers for G3 bounded execution."""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Literal, cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
)

from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_json_bytes_830_g3
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCandidateBundle830G3V1,
    BatchConceptCompileRequest830G3V1,
    EntityCompileBinding830G3V1,
    assemble_candidate_bundle,
    compile_output_hash_g3,
    compile_request_hash_g3,
    compiler_context_g3,
    compose_batch_output,
    record_composed_output,
    record_model_compile,
    review_context_g3,
    validate_delta_output,
)
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    _batch_sha256 as _compile_sha256,
)
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    _definition_hash_g3 as _compile_definition_hash,
)
from insurance_harness.knowledge_compiler.batch_entity_resolution_830_g3 import (
    BatchCorpusV1,
    BatchEntityResolutionV1,
    BatchResolutionPolicyV1,
    EntityProposalV1,
    ExistingEntitySnapshotV1,
    LabelProposalV1,
    MaterialBindingV1,
    MaterialProposalV1,
    ModelReceiptBindingV1,
    ProposalBatchV1,
    ProposalEvidenceV1,
    VersionAnchorV1,
    _batch_sha256,
    _normalized,
    resolve_batch,
)
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    AuditDisposition,
    CompileOutput,
    CompileResult,
    ExecutionRecord,
    HumanBatchAdmission,
    ReviewOutput,
    ReviewResult,
    ValueScore,
    free_page_id,
)
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    ConceptDefinition,
    Evidence,
    FieldAssertion,
    FreeWikiPage,
    SourceBlock,
    verify_evidence,
)
from insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3 import (
    SchemaPackCatalogV1,
)
from insurance_harness.model_policy import ModelIdentity
from insurance_harness.run_admission.g3_models import (
    G3ArtifactRefV1,
    G3BoundedAdmissionPlanV1,
    G3BoundedApprovalEnvelopeV1,
    G3CallPlanV1,
    G3CallTerminalReceiptV1,
    G3CostAuditV1,
    G3DispositionCountsV1,
    G3ModelProcessingAuthorizationEnvelopeV1,
    G3ModelProcessingAuthorizationV1,
    G3StageTerminalReceiptV1,
    G3UsageTotalsV1,
    canonical_g3_hash,
    canonical_json,
    stage_approval_signed_bytes,
)

from .g3_field_task_routing import (
    ROUTING_VERSION,
    route_field_task_sources,
    validate_routed_selections,
)
from .g3_field_tasks import FieldTaskEvidenceResultV1, adapt_catalog_field_tasks


def _structured_text(value: str) -> str:
    if unicodedata.normalize("NFC", value) != value or any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in value
    ):
        raise ValueError("semantic structured text must be canonical NFC")
    return value


def _body_text(value: str) -> str:
    if any(
        ord(character) == 0x7F
        or (ord(character) < 0x20 and character not in "\t\n\r")
        for character in value
    ):
        raise ValueError("semantic source body contains a forbidden control")
    return value


Text = Annotated[StrictStr, StringConstraints(min_length=1), AfterValidator(_structured_text)]
BodyText = Annotated[StrictStr, StringConstraints(min_length=1), AfterValidator(_body_text)]
BodyTextOrEmpty = Annotated[StrictStr, AfterValidator(_body_text)]

_G3_REQUEST_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "enable_thinking",
        "max_tokens",
        "messages",
        "model",
        "response_format",
        "temperature",
    ],
    "properties": {
        "model": {"type": "string", "minLength": 1},
        "temperature": {"type": "number"},
        "max_tokens": {"type": "integer", "minimum": 1},
        "messages": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "prefixItems": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["content", "role"],
                    "properties": {
                        "role": {"const": "system"},
                        "content": {"type": "string"},
                    },
                },
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["content", "role"],
                    "properties": {
                        "role": {"const": "user"},
                        "content": {"type": "string"},
                    },
                },
            ],
            "items": False,
        },
        "response_format": {
            "type": "object",
            "additionalProperties": False,
            "required": ["type"],
            "properties": {"type": {"const": "json_object"}},
        },
        "enable_thinking": {"type": "boolean"},
    },
}

_G3_GEMINI_REQUEST_SCHEMA: dict[str, object] = {
    **_G3_REQUEST_SCHEMA,
    "required": [
        "max_tokens",
        "messages",
        "model",
        "response_format",
        "stream",
        "temperature",
    ],
    "properties": {
        **cast(dict[str, object], _G3_REQUEST_SCHEMA["properties"]),
        "stream": {"const": False},
    },
}
cast(dict[str, object], _G3_GEMINI_REQUEST_SCHEMA["properties"]).pop(
    "enable_thinking"
)

_G3_GEMINI_JSON_INSTRUCTION = (
    "Return only valid JSON, without Markdown fences or explanations."
)


def _is_g3_gemini_identity(identity: ModelIdentity) -> bool:
    return (
        identity.provider,
        identity.family,
        identity.deployment_id,
        identity.policy_version,
        identity.role,
    ) in {
        (
            "g3-user-gateway",
            "gemini",
            "gemini-3.7-flash-medium",
            "g3-user-gemini-gateway-v1",
            role,
        )
        for role in ("classify", "extract", "verify")
    }


def _is_g3_gemini_d_identity(stage: str, identity: ModelIdentity) -> bool:
    return _is_g3_gemini_identity(identity) and identity.role == {
        "D_COMPILE": "extract",
        "D_REVIEW": "verify",
    }.get(stage)


def g3_current_schema_specs(
    stage: Literal["C_CLASSIFY", "D_COMPILE", "D_REVIEW"],
    identity: ModelIdentity | None = None,
) -> tuple[tuple[str, str, dict[str, object]], ...]:
    """Return the only current schema producers and source modules for one stage."""

    request_module = (
        "harness/src/insurance_harness/knowledge_compiler/g3_bounded_model_execution.py"
    )
    response_module = request_module
    response_schema: dict[str, object]
    if stage == "C_CLASSIFY":
        response_schema = _c_response_schema(identity)
    elif stage == "D_COMPILE":
        if identity is not None and _is_g3_gemini_d_identity(stage, identity):
            response_schema = G3DCompileReferenceResponseV1.model_json_schema()
        else:
            response_module = (
                "harness/src/insurance_harness/knowledge_compiler/concept_compile_830_g2.py"
            )
            response_schema = CompileOutput.model_json_schema()
    else:
        if identity is not None and _is_g3_gemini_d_identity(stage, identity):
            response_schema = G3DReviewReferenceResponseV1.model_json_schema()
        else:
            response_module = (
                "harness/src/insurance_harness/knowledge_compiler/concept_compile_830_g2.py"
            )
            response_schema = ReviewOutput.model_json_schema()
    if identity is None or (
        identity.provider == "bailian" and identity.family == "qwen"
    ):
        request_schema = _G3_REQUEST_SCHEMA
    elif _is_g3_gemini_identity(identity):
        request_schema = _G3_GEMINI_REQUEST_SCHEMA
    else:
        raise ValueError("unsupported G3 model identity")
    return (
        ("request", request_module, request_schema),
        ("response", response_module, response_schema),
    )


def g3_openai_request_bytes(
    *,
    plan: G3BoundedAdmissionPlanV1,
    call: G3CallPlanV1,
    system: str,
    user: str,
) -> bytes:
    """Render the sole G3 Bailian/Qwen OpenAI-compatible wire envelope."""

    from insurance_harness.compiler.llm import openai_compat_request_bytes

    if plan.routing_lock.identity != call.identity:
        raise ValueError("unsupported G3 model route")
    gemini = _is_g3_gemini_identity(call.identity)
    if gemini:
        if (
            call.endpoint_origin != "http://8.148.158.241:3131"
            or call.endpoint_path != "/v1/chat/completions"
            or plan.routing_lock.thinking is not True
        ):
            raise ValueError("unsupported G3 model route")
    elif (
        call.identity.provider != "bailian"
        or call.identity.family != "qwen"
        or call.endpoint_origin != "https://dashscope.aliyuncs.com"
        or call.endpoint_path != "/compatible-mode/v1/chat/completions"
    ):
        raise ValueError("unsupported G3 model route")
    base = openai_compat_request_bytes(
        model=call.identity.deployment_id,
        temperature=plan.routing_lock.temperature_micros / 1_000_000,
        max_tokens=call.output_token_ceiling,
        system=(f"{system}\n\n{_G3_GEMINI_JSON_INSTRUCTION}" if gemini else system),
        user=user,
        thinking=None,
        response_format="json_object",
    )
    value = json.loads(base, object_pairs_hook=lambda pairs: dict(pairs))
    if type(value) is not dict or "thinking" in value or "extra_body" in value:
        raise ValueError("invalid base G3 wire envelope")
    if gemini:
        value["stream"] = False
    else:
        value["enable_thinking"] = plan.routing_lock.thinking
    return canonical_json(value)


class _SemanticModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class G3SemanticLocatorV1(_SemanticModel):
    block_ref: Text
    start: Annotated[StrictInt, Field(ge=0)]
    end: Annotated[StrictInt, Field(gt=0)]
    quote: BodyText


class G3SemanticEvidenceV1(_SemanticModel):
    evidence_ref: Text
    entity_ref: Text | None
    purpose: Literal[
        "issuer",
        "product_code",
        "name",
        "version",
        "classification",
        "material_role",
        "field",
    ]
    field_key: Text | None
    locator: G3SemanticLocatorV1


class G3SemanticLabelV1(_SemanticModel):
    taxonomy_label: Text
    confidence: Annotated[StrictStr, StringConstraints(pattern=r"^(0\.[0-9]{6}|1\.000000)$")]
    evidence_refs: tuple[Text, ...]


class G3SemanticAnchorV1(_SemanticModel):
    kind: Literal["filing_number", "registration_number"]
    value: Text


class G3SemanticEntityV1(_SemanticModel):
    entity_ref: Text
    issuer: Text | None
    name: Text | None
    product_code: Text | None
    version_label: Text | None
    filing_or_registration: G3SemanticAnchorV1 | None
    identity_confidence: Annotated[
        StrictStr, StringConstraints(pattern=r"^(0\.[0-9]{6}|1\.000000)$")
    ]
    identity_evidence_refs: tuple[Text, ...]
    labels: tuple[G3SemanticLabelV1, ...]
    primary_label: Text
    valid_from: Text | None
    valid_through: Text | None


class G3SemanticMaterialV1(_SemanticModel):
    material_id: Text
    material_role: Text
    material_role_evidence_refs: tuple[Text, ...]
    entities: tuple[G3SemanticEntityV1, ...]
    evidence: tuple[G3SemanticEvidenceV1, ...]


class G3SemanticResponseV1(_SemanticModel):
    contract: Literal["g3-batch-resolution-semantic-response.local.v1"]
    materials: tuple[G3SemanticMaterialV1, ...]


class G3SemanticReferenceEvidenceV1(_SemanticModel):
    evidence_ref: Text
    locator_ref: Annotated[StrictStr, StringConstraints(pattern=r"^loc_[0-9a-f]{64}$")]


class G3SemanticReferenceIdentityEvidenceV1(G3SemanticReferenceEvidenceV1):
    entity_ref: Text
    purpose: Literal[
        "issuer", "product_code", "name", "version", "classification"
    ]
    field_key: None


class G3SemanticReferenceRoleEvidenceV1(G3SemanticReferenceEvidenceV1):
    entity_ref: None
    purpose: Literal["material_role"]
    field_key: None


class G3SemanticReferenceFieldEvidenceV1(G3SemanticReferenceEvidenceV1):
    entity_ref: Text
    purpose: Literal["field"]
    field_key: Text


class G3SemanticReferenceMaterialV1(_SemanticModel):
    material_id: Text
    material_role: Text
    material_role_evidence_refs: tuple[Text, ...]
    entities: tuple[G3SemanticEntityV1, ...]
    evidence: tuple[Annotated[
        G3SemanticReferenceIdentityEvidenceV1
        | G3SemanticReferenceRoleEvidenceV1
        | G3SemanticReferenceFieldEvidenceV1,
        Field(discriminator="purpose"),
    ], ...]


class G3SemanticReferenceResponseV1(_SemanticModel):
    contract: Literal["g3-batch-resolution-semantic-references.local.v1"]
    materials: tuple[G3SemanticReferenceMaterialV1, ...]


class G3DSourceSelectionV1(_SemanticModel):
    source_ref: Text
    quote: BodyText


class G3DDefinitionReferenceV1(_SemanticModel):
    definition_ref: Text
    canonical_key: Text
    sense_key: Text
    title: BodyText
    body: BodyText
    aliases: tuple[Text, ...]
    evidence: tuple[G3DSourceSelectionV1, ...]
    disposition: Literal["new_page", "sense"]
    audit_reason: BodyText


class G3DFieldReferenceV1(_SemanticModel):
    field_ref: Text
    state: Literal["present", "absent_explicitly", "unknown"]
    value: BodyText | None
    unknown_reason: BodyText | None
    evidence: tuple[G3DSourceSelectionV1, ...]
    concept_refs: tuple[Text, ...]
    conditions: tuple[BodyText, ...]
    exceptions: tuple[BodyText, ...]
    valid_time: BodyTextOrEmpty
    audit_reason: BodyText


class G3DPageReferenceV1(_SemanticModel):
    page_ref: Text
    entity_ref: Text
    stable_key: Text
    title: BodyText
    body: BodyText
    evidence: tuple[G3DSourceSelectionV1, ...]
    concept_refs: tuple[Text, ...]
    conditions: tuple[BodyText, ...]
    exceptions: tuple[BodyText, ...]
    valid_time: BodyTextOrEmpty
    audit_reason: BodyText


class G3DCompileReferenceResponseV1(_SemanticModel):
    contract: Literal["g3-d-compile-semantic-references.local.v1"]
    transformation: Literal["EXTRACT", "NORMALIZE", "COMPRESS", "SYNTHESIZE"]
    definitions: tuple[G3DDefinitionReferenceV1, ...]
    fields: tuple[G3DFieldReferenceV1, ...]
    pages: tuple[G3DPageReferenceV1, ...]


class G3DReviewScoreReferenceV1(_SemanticModel):
    review_ref: Text
    business_value: Annotated[StrictInt, Field(ge=0, le=25)]
    reuse: Annotated[StrictInt, Field(ge=0, le=20)]
    evidence_quality: Annotated[StrictInt, Field(ge=0, le=20)]
    definability: Annotated[StrictInt, Field(ge=0, le=15)]
    novel_identity: Annotated[StrictInt, Field(ge=0, le=10)]
    name_stability: Annotated[StrictInt, Field(ge=0, le=10)]


class G3DReviewReferenceResponseV1(_SemanticModel):
    contract: Literal["g3-d-review-semantic-references.local.v1"]
    decision: Literal["PASS", "REJECT", "NEEDS_HUMAN"]
    reasons: tuple[BodyText, ...]
    scores: tuple[G3DReviewScoreReferenceV1, ...]


def _g3_d_ref(kind: str, request_sha256: str, value: object) -> str:
    return kind + "_" + hashlib.sha256(
        ("g3-d-" + kind + "-reference.830.v1").encode("ascii")
        + b"\0"
        + canonical_json({"request_sha256": request_sha256, "value": value})
    ).hexdigest()


def _g3_d_source_index(
    request: BatchConceptCompileRequest830G3V1,
) -> tuple[list[dict[str, object]], dict[str, SourceBlock], dict[tuple[str, str], str]]:
    options: list[dict[str, object]] = []
    by_ref: dict[str, SourceBlock] = {}
    by_key: dict[tuple[str, str], str] = {}
    for source in request.base_request.sources:
        identity = source.model_dump(mode="json", exclude={"text"})
        source_ref = _g3_d_ref(
            "source",
            request.request_sha256,
            {"identity": identity, "start": 0, "end": len(source.text), "quote": source.text},
        )
        key = (source.revision_id, source.block_id)
        if source_ref in by_ref or key in by_key:
            raise ValueError("duplicate D source reference")
        by_ref[source_ref] = source
        by_key[key] = source_ref
        options.append({"source_ref": source_ref, "source": source})
    return (
        sorted(options, key=lambda item: cast(str, item["source_ref"])),
        by_ref,
        by_key,
    )


def _g3_d_entity_refs(
    request: BatchConceptCompileRequest830G3V1,
) -> dict[str, str]:
    return {
        binding.entity_id: _g3_d_ref(
            "entity",
            request.request_sha256,
            {
                "entity_id": binding.entity_id,
                "entity_version": binding.entity_version,
                "binding_sha256": binding.binding_sha256,
            },
        )
        for binding in request.entity_bindings
    }


def _g3_d_existing_concept_refs(
    request: BatchConceptCompileRequest830G3V1,
) -> tuple[list[dict[str, str]], dict[str, str]]:
    rows: list[dict[str, str]] = []
    index: dict[str, str] = {}
    for definition in request.base_request.existing_definitions:
        ref = _g3_d_ref(
            "concept",
            request.request_sha256,
            {
                "concept_id": definition.concept_id,
                "definition_hash": _compile_definition_hash(definition),
            },
        )
        index[ref] = definition.concept_id
        rows.append(
            {
                "concept_ref": ref,
                "concept_id": definition.concept_id,
                "canonical_key": definition.canonical_key,
                "sense_key": definition.sense_key,
            }
        )
    return sorted(rows, key=lambda item: item["concept_ref"]), index


def _g3_d_entity_source_refs(
    request: BatchConceptCompileRequest830G3V1,
    by_source_key: dict[tuple[str, str], str],
    entity_refs: dict[str, str],
) -> list[dict[str, object]]:
    source_keys_by_material = {
        entry.material_id: {(block.revision_id, block.block_id) for block in entry.blocks}
        for entry in request.resolution_inputs.corpus.entries
    }
    base_fields: dict[str, list[FieldAssertion]] = {}
    base_pages: dict[str, list[FreeWikiPage]] = {}
    for field in request.base_request.existing_fields:
        base_fields.setdefault(field.entity_id, []).append(field)
    for page in request.base_request.existing_pages:
        base_pages.setdefault(page.entity_id, []).append(page)
    definitions = {item.concept_id: item for item in request.base_request.existing_definitions}
    rows: list[dict[str, object]] = []
    for binding in request.entity_bindings:
        allowed = {
            key
            for material_id in binding.source_material_ids
            for key in source_keys_by_material[material_id]
        }
        owner_members: tuple[FieldAssertion | FreeWikiPage, ...] = (
            *base_fields.get(binding.entity_id, ()),
            *base_pages.get(binding.entity_id, ()),
        )
        allowed.update(
            (evidence.revision_id, evidence.block_id)
            for member in owner_members
            for evidence in member.evidence
        )
        linked = {concept for member in owner_members for concept in member.concept_ids}
        allowed.update(
            (evidence.revision_id, evidence.block_id)
            for linked_id in linked
            if (definition := definitions.get(linked_id)) is not None
            for evidence in definition.evidence
        )
        try:
            refs = sorted(by_source_key[key] for key in allowed)
        except KeyError as exc:
            raise ValueError("D entity source closure is incomplete") from exc
        rows.append(
            {
                "entity_ref": entity_refs[binding.entity_id],
                "entity_id": binding.entity_id,
                "source_refs": refs,
            }
        )
    return sorted(rows, key=lambda item: cast(str, item["entity_id"]))


def _g3_d_field_targets(
    request: BatchConceptCompileRequest830G3V1,
    entity_refs: dict[str, str],
) -> list[dict[str, object]]:
    bindings = {row.entity_id: row for row in request.entity_bindings}
    rows = []
    for task in adapt_catalog_field_tasks(request):
        binding = bindings[task.entity_id]
        field_ref = _g3_d_ref("field", request.request_sha256, {
            "entity_id": task.entity_id,
            "entity_version": task.entity_version,
            "field_key": task.field_key,
            "profile_sha256": binding.profile_sha256,
        })
        rows.append({
            "field_ref": field_ref,
            "entity_ref": entity_refs[task.entity_id],
            "entity_id": task.entity_id,
            "entity_version": task.entity_version,
            "display_name": binding.display_name,
            "field_key": task.field_key,
            "short_title": task.short_title,
            "description": task.description,
            "source_guidance": task.source_guidance,
        })
    return rows


def gemini_d_extraction_policy() -> dict[str, object]:
    """Return the bundled, source-pinned field batching policy."""

    value: dict[str, object] = {
        "policy_version": "g3-field-batches.830.v2",
        "source_routing_version": ROUTING_VERSION,
        "max_source_chars": 24000,
        "max_source_span_chars": 2000,
        "max_fields_per_call": 10,
        "max_profile_fields": 83,
        "max_entities_per_material": 2,
    }
    per_call = value["max_fields_per_call"]
    profile = value["max_profile_fields"]
    entities = value["max_entities_per_material"]
    if (
        type(per_call) is not int
        or type(profile) is not int
        or type(entities) is not int
        or per_call <= 0
        or profile <= 0
        or entities <= 0
        or per_call > profile
    ):
        raise RuntimeError("invalid bundled Gemini D extraction policy")
    return dict(value)


def _g3_d_entity_slots(
    request: BatchConceptCompileRequest830G3V1,
) -> tuple[tuple[EntityCompileBinding830G3V1, str, int], ...]:
    policy = gemini_d_extraction_policy()
    max_entities = cast(int, policy["max_entities_per_material"])
    by_primary: dict[str, list[EntityCompileBinding830G3V1]] = {}
    for binding in request.entity_bindings:
        material_ids = binding.source_material_ids
        if not material_ids or material_ids != tuple(sorted(set(material_ids))):
            raise ValueError("D window entity material binding is invalid")
        by_primary.setdefault(material_ids[0], []).append(binding)
    rows: list[tuple[EntityCompileBinding830G3V1, str, int]] = []
    for primary_material_id in sorted(by_primary):
        bindings = sorted(by_primary[primary_material_id], key=lambda item: item.entity_id)
        if len(bindings) > max_entities:
            raise ValueError("D window primary material entity capacity exceeded")
        rows.extend(
            (binding, primary_material_id, entity_slot)
            for entity_slot, binding in enumerate(bindings)
        )
    return tuple(rows)


def derive_gemini_d_compile_windows(
    request: BatchConceptCompileRequest830G3V1,
) -> tuple[dict[str, object], ...]:
    """Derive the only admissible Gemini D compile window partition."""

    entity_refs = _g3_d_entity_refs(request)
    policy = gemini_d_extraction_policy()
    max_fields_per_call = cast(int, policy["max_fields_per_call"])
    max_profile_fields = cast(int, policy["max_profile_fields"])
    targets = _g3_d_field_targets(request, entity_refs)
    by_entity: dict[str, list[dict[str, object]]] = {
        binding.entity_id: [] for binding in request.entity_bindings
    }
    for target in targets:
        by_entity[cast(str, target["entity_id"])].append(target)
    rows: list[dict[str, object]] = []
    for binding, primary_material_id, entity_slot in _g3_d_entity_slots(request):
        if len(binding.required_fields) > max_profile_fields:
            raise ValueError("D window profile field capacity exceeded")
        entity_ref = entity_refs[binding.entity_id]
        common = {
            "primary_material_id": primary_material_id,
            "material_ids": binding.source_material_ids,
            "entity_slot": entity_slot,
            "entity_id": binding.entity_id,
            "entity_ref": entity_ref,
        }
        entity_targets = by_entity[binding.entity_id]
        if not entity_targets:
            continue
        synth_value = {**common, "kind": "ENTITY_SYNTHESIS", "field_refs": ()}
        rows.append(
            {
                **synth_value,
                "window_id": _g3_d_ref(
                    "window",
                    request.request_sha256,
                    {"extraction_policy": policy, **synth_value},
                ),
            }
        )
        for offset in range(0, len(entity_targets), max_fields_per_call):
            field_refs = tuple(
                cast(str, item["field_ref"])
                for item in entity_targets[offset : offset + max_fields_per_call]
            )
            value = {**common, "kind": "FIELDS", "field_refs": field_refs}
            rows.append(
                {
                    **value,
                    "window_id": _g3_d_ref(
                        "window",
                        request.request_sha256,
                        {"extraction_policy": policy, **value},
                    ),
                }
            )
    if len(rows) > 300:
        raise ValueError("D window call capacity exceeded")
    return tuple(rows)


def _exact_gemini_d_window(
    request: BatchConceptCompileRequest830G3V1, window: object
) -> dict[str, object]:
    if not isinstance(window, dict) or set(window) != {
        "window_id", "kind", "primary_material_id", "material_ids", "entity_slot",
        "entity_id", "entity_ref", "field_refs"
    }:
        raise ValueError("invalid D compile window")
    matches = [
        row
        for row in derive_gemini_d_compile_windows(request)
        if row["window_id"] == window.get("window_id")
    ]
    if len(matches) != 1 or matches[0] != window:
        raise ValueError("foreign D compile window")
    return matches[0]


def render_gemini_d_compile_window_context(
    identity: ModelIdentity,
    request: BatchConceptCompileRequest830G3V1,
    window: object,
) -> dict[str, object]:
    """Render one compact, typed Gemini D compile window."""

    if not _is_g3_gemini_d_identity("D_COMPILE", identity):
        raise ValueError("D compile windows require Gemini extract identity")
    exact = _exact_gemini_d_window(request, window)
    return _render_gemini_d_compile_window_context(identity, request, exact)


def _render_gemini_d_compile_window_context(
    identity: ModelIdentity,
    request: BatchConceptCompileRequest830G3V1,
    exact: dict[str, object],
) -> dict[str, object]:
    """Shared renderer; callers first validate a full or recovery window."""
    source_options, _, source_keys = _g3_d_source_index(request)
    entity_refs = _g3_d_entity_refs(request)
    entity_sources = _g3_d_entity_source_refs(request, source_keys, entity_refs)
    source_row = next(
        row for row in entity_sources if row["entity_id"] == exact["entity_id"]
    )
    allowed = set(cast(list[str], source_row["source_refs"]))
    field_refs = set(cast(tuple[str, ...], exact["field_refs"]))
    field_targets = [
        row
        for row in _g3_d_field_targets(request, entity_refs)
        if row["field_ref"] in field_refs
    ]
    binding = next(
        row for row in request.entity_bindings if row.entity_id == exact["entity_id"]
    )
    catalog_entries = tuple(
        row
        for row in request.catalog.entries
        if (
            row.pack.schema_pack_id,
            row.pack.schema_version,
            row.pack.schema_pack_sha256,
        )
        == (binding.schema_pack_id, binding.schema_version, binding.schema_pack_sha256)
    )
    if len(catalog_entries) != 1:
        raise ValueError("D window catalog binding mismatch")
    existing_fields = tuple(
            row
            for row in request.base_request.existing_fields
            if row.entity_id == binding.entity_id
        )
    existing_pages = tuple(
            row
            for row in request.base_request.existing_pages
            if row.entity_id == binding.entity_id
        )
    linked_existing_ids = {
        concept_id
        for row in (*existing_fields, *existing_pages)
        for concept_id in row.concept_ids
    }
    existing_members = {
        "definitions": tuple(
            row
            for row in request.base_request.existing_definitions
            if row.concept_id in linked_existing_ids
        ),
        "fields": existing_fields,
        "pages": existing_pages,
    }
    concept_rows, _ = _g3_d_existing_concept_refs(request)
    selected_keys = {str(row["field_key"]) for row in field_targets}
    tasks = tuple(task for task in adapt_catalog_field_tasks(request)
                  if task.entity_id == binding.entity_id
                  and (exact["kind"] == "ENTITY_SYNTHESIS" or task.field_key in selected_keys))
    routed_sources = route_field_task_sources(
        tasks, {str(row["source_ref"]): row["source"] for row in source_options
                if row["source_ref"] in allowed},
    )
    source_row = {**source_row, "source_refs": [row["source_ref"] for row in routed_sources]}
    return {
        "contract": "g3-d-compile-window-prompt-context.830.v1",
        "request_sha256": request.request_sha256,
        "base_request_hash": compile_request_hash_g3(request.base_request),
        "extraction_policy": gemini_d_extraction_policy(),
        "window": exact,
        "entity_bindings": (binding,),
        "catalog_entries": tuple({
            "schema_pack_id": row.pack.schema_pack_id,
            "schema_version": row.pack.schema_version,
            "schema_pack_sha256": row.pack.schema_pack_sha256,
        } for row in catalog_entries),
        "existing_members": existing_members,
        "field_targets": field_targets,
        "source_options": routed_sources,
        "field_tasks": tuple({
            "task_sha256": task.task_sha256,
            "field_key": task.field_key,
            "adapter_kind": task.adapter_kind,
            "value_constraint": task.value_constraint,
            "allowed_states": task.allowed_states,
        } for task in tasks) if exact["kind"] == "FIELDS" else (),
        "entity_source_refs": (source_row,),
        "existing_concept_refs": concept_rows,
        "response_schema": G3DCompileReferenceResponseV1.model_json_schema(),
    }


def render_gemini_d_review_display_context(
    request: BatchConceptCompileRequest830G3V1, output: CompileOutput
) -> dict[str, object]:
    """Keep all business content and source text once for Gemini review."""

    source_options, _, source_keys = _g3_d_source_index(request)
    selected = {
        (row.schema_pack_id, row.schema_version, row.schema_pack_sha256)
        for row in request.entity_bindings
    }
    catalog_entries = tuple(
        row
        for row in request.catalog.entries
        if (row.pack.schema_pack_id, row.pack.schema_version, row.pack.schema_pack_sha256)
        in selected
    )
    if len(catalog_entries) != len(selected):
        raise ValueError("D review catalog selection mismatch")
    selected_catalog = {
        name: catalog_entries if name == "entries" else getattr(request.catalog, name)
        for name in type(request.catalog).model_fields
    }
    base_omitted = {"sources", "existing_definitions", "existing_fields", "existing_pages"}
    base_scope = {
        name: getattr(request.base_request, name)
        for name in type(request.base_request).model_fields
        if name not in base_omitted
    }
    corpus_entry_metadata = tuple(
        {
            **entry.model_dump(mode="python", exclude={"blocks"}),
            "block_refs": tuple(
                (
                    {
                        "source_ref": source_keys[(block.revision_id, block.block_id)],
                        "revision_id": block.revision_id,
                        "block_id": block.block_id,
                    }
                    if (block.revision_id, block.block_id) in source_keys
                    else {
                        "source_ref": None,
                        "source": block,
                        "revision_id": block.revision_id,
                        "block_id": block.block_id,
                    }
                )
                for block in entry.blocks
            ),
        }
        for entry in request.resolution_inputs.corpus.entries
    )
    review_targets = _g3_d_review_targets(request, output)
    return {
        "contract": "g3-d-review-compact-display-context.830.v1",
        "request_scope": {
            "contract": request.contract,
            "quality_status": request.quality_status,
            "release_lane": request.release_lane,
            "base_request": base_scope,
            "profile_confirmation": request.profile_confirmation,
            "unknown_field_key_alignments": request.unknown_field_key_alignments,
        },
        "selected_catalog": selected_catalog,
        "resolution_policy": request.resolution_inputs.policy,
        "accepted_resolution": request.resolution,
        "corpus_entry_metadata": corpus_entry_metadata,
        "entity_bindings": request.entity_bindings,
        "entity_source_refs": _g3_d_entity_source_refs(
            request, source_keys, _g3_d_entity_refs(request)
        ),
        "field_targets": _g3_d_field_targets(request, _g3_d_entity_refs(request)),
        "source_options": source_options,
        "candidate": output,
        "review_targets": review_targets,
        "machine_bindings": {
            "request_sha256": request.request_sha256,
            "base_request_hash": compile_request_hash_g3(request.base_request),
            "catalog_wire_sha256": request.catalog_wire_sha256,
            "catalog_sha256": request.catalog.catalog_sha256,
            "resolution_inputs_sha256": request.resolution_inputs.inputs_sha256,
            "corpus_sha256": request.resolution_inputs.corpus.corpus_sha256,
            "proposals_sha256": request.resolution_inputs.proposals.proposals_sha256,
            "existing_snapshot_sha256": (
                request.resolution_inputs.existing_entities.snapshot_sha256
            ),
            "policy_sha256": request.resolution_inputs.policy.policy_sha256,
            "resolution_batch_sha256": request.resolution.batch_sha256,
            "output_hash": compile_output_hash_g3(output),
        },
    }


def _g3_d_review_targets(
    request: BatchConceptCompileRequest830G3V1, output: CompileOutput
) -> list[dict[str, object]]:
    definitions = {item.concept_id: item for item in output.definitions}
    pages = {free_page_id(item): item for item in output.pages}
    audits = {item.key: item for item in output.audit}
    rows: list[dict[str, object]] = []
    output_hash = compile_output_hash_g3(output)
    for member_id in sorted(_g3_novel_page_ids(request, output)):
        member = definitions.get(member_id) or pages.get(member_id)
        audit = audits.get(member_id)
        if member is None or audit is None:
            raise ValueError("D review target closure mismatch")
        rows.append(
            {
                "review_ref": _g3_d_ref(
                    "review",
                    request.request_sha256,
                    {"member_id": member_id, "output_hash": output_hash},
                ),
                "member_id": member_id,
                "kind": "definition" if member_id in definitions else "free_page",
                "audit": audit,
            }
        )
    return rows


def _g3_d_review_definition_owners(
    request: BatchConceptCompileRequest830G3V1,
    output: CompileOutput,
    entity_rows: tuple[tuple[EntityCompileBinding830G3V1, str, int], ...],
    source_keys: dict[tuple[str, str], str],
    entity_sources: dict[str, set[str]],
) -> dict[str, str]:
    existing = {
        row.concept_id: _compile_definition_hash(row)
        for row in request.base_request.existing_definitions
    }
    affected = {row[0].entity_id for row in entity_rows}
    linked: dict[str, set[str]] = {entity_id: set() for entity_id in affected}
    for member in (*output.fields, *output.pages):
        if member.entity_id in linked:
            linked[member.entity_id].update(member.concept_ids)
    ordered_entities = [row[0].entity_id for row in entity_rows]
    owners: dict[str, str] = {}
    for definition in output.definitions:
        if existing.get(definition.concept_id) == _compile_definition_hash(definition):
            continue
        evidence_refs = {
            source_keys[(item.revision_id, item.block_id)] for item in definition.evidence
        }
        eligible = [
            entity_id
            for entity_id in ordered_entities
            if evidence_refs <= entity_sources[entity_id]
        ]
        referencing = [
            entity_id
            for entity_id in ordered_entities
            if definition.concept_id in linked[entity_id]
        ]
        candidates = eligible or referencing or ordered_entities
        if not candidates:
            raise ValueError("D review novel definition has no affected entity owner")
        owners[definition.concept_id] = candidates[0]
    return owners


_REVIEW_WINDOW_POLICY = {
    "version": "g3-evidence-bounded-review.830.v2",
    "max_fields": 10,
    "max_source_chars": 24000,
    "neighbor_chars": 128,
    "max_context_bytes": 262144,
}


def _g3_review_field_tasks(request, fields):
    from .g3_field_tasks import _source_scope, _task, catalog_value_constraint

    tasks = {(task.entity_id, task.field_key): task for task in adapt_catalog_field_tasks(request)}
    for key in fields.keys() - tasks.keys():
        entity_id, field_key = key
        binding = next(row for row in request.entity_bindings if row.entity_id == entity_id)
        catalog = next(
            row
            for row in request.catalog.entries
            if (row.pack.schema_pack_id, row.pack.schema_version, row.pack.schema_pack_sha256)
            == (binding.schema_pack_id, binding.schema_version, binding.schema_pack_sha256)
        )
        definition = next(row for row in catalog.pack.fields if row.field_key == field_key)
        tasks[key] = _task(
            dict(
                adapter_kind="CATALOG_SCHEMA",
                adapter_version="g3-review-catalog-field.830.v1",
                entity_id=entity_id,
                entity_version=binding.entity_version,
                field_key=field_key,
                short_title=definition.short_title,
                description=definition.description,
                source_guidance=definition.source_guidance,
                value_constraint=catalog_value_constraint(
                    definition.value_spec,
                    single_valued=(
                        field_key == "product_type" and definition.short_title == "产品类型"
                    ),
                ),
                material_ids=binding.source_material_ids,
                allowed_sources=_source_scope(request, binding.source_material_ids),
                concept_ids=(),
                allowed_states=("present", "absent_explicitly", "unknown"),
                max_attempts=1,
            )
        )
    return tasks


def _g3_review_scope(request, output):
    from .batch_concept_compile_830_g3 import aligned_existing_fields

    _, sources, source_keys = _g3_d_source_index(request)
    entity_rows = _g3_d_entity_slots(request)
    entity_refs = _g3_d_entity_refs(request)
    source_rows = _g3_d_entity_source_refs(request, source_keys, entity_refs)
    entity_sources = {row["entity_id"]: set(row["source_refs"]) for row in source_rows}
    owners = _g3_d_review_definition_owners(
        request, output, entity_rows, source_keys, entity_sources
    )
    existing = {(row.entity_id, row.field_key): row for row in aligned_existing_fields(request)}
    fields = {
        (row.entity_id, row.field_key): row
        for row in output.fields
        if existing.get((row.entity_id, row.field_key)) != row
    }
    targets = _g3_d_review_targets(request, output)
    members = {row.concept_id: row for row in output.definitions}
    members.update({free_page_id(row): row for row in output.pages})
    target_owners = {}
    for target in targets:
        member = members[target["member_id"]]
        owner = member.entity_id if isinstance(member, FreeWikiPage) else owners[member.concept_id]
        target_owners[target["review_ref"]] = owner
    return dict(
        sources=sources,
        source_keys=source_keys,
        entity_rows=entity_rows,
        entity_refs=entity_refs,
        entity_sources=entity_sources,
        fields=fields,
        targets={row["review_ref"]: row for row in targets},
        members=members,
        target_owners=target_owners,
        tasks=_g3_review_field_tasks(request, fields),
        output_hash=compile_output_hash_g3(output),
    )


def _merge_review_intervals(rows):
    merged = []
    for start, end in sorted(rows):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _g3_review_source_options(scope, members, entity_id, tasks):
    sources, keys = scope["sources"], scope["source_keys"]
    intervals = {}
    for member in members:
        for evidence in member.evidence:
            ref = keys.get((evidence.revision_id, evidence.block_id))
            if ref is None:
                raise ValueError("D review evidence references foreign source")
            verify_evidence(evidence, (sources[ref],))
            intervals.setdefault(ref, []).append((evidence.start, evidence.end))
    intervals = {ref: _merge_review_intervals(rows) for ref, rows in intervals.items()}
    size = sum(end - start for rows in intervals.values() for start, end in rows)
    budget = _REVIEW_WINDOW_POLICY["max_source_chars"]
    if size > budget:
        raise ValueError("D review evidence exceeds source budget")
    # Preserve every cited character before spending remaining space on neighbors.
    for ref, rows in sorted(intervals.items()):
        padded = []
        for start, end in rows:
            left = min(start, _REVIEW_WINDOW_POLICY["neighbor_chars"], budget - size)
            right = min(
                len(sources[ref].text) - end,
                _REVIEW_WINDOW_POLICY["neighbor_chars"],
                budget - size - left,
            )
            padded.append((start - left, end + right))
            size += left + right
        intervals[ref] = _merge_review_intervals(padded)
    # Unknown assertions also require relevant source context, not merely an empty quote list.
    unknown_tasks = [
        task
        for task in tasks
        if scope["fields"][(task.entity_id, task.field_key)].state == "unknown"
    ]
    remaining = budget - size
    if unknown_tasks and remaining > 0:
        routed = route_field_task_sources(
            unknown_tasks,
            {ref: sources[ref] for ref in scope["entity_sources"][entity_id]},
            max_source_chars=remaining,
            max_span_chars=min(2000, remaining),
        )
        for row in routed:
            intervals.setdefault(row["source_ref"], []).extend(
                (span["start"], span["end"]) for span in row["spans"]
            )
    result = []
    for ref, ranges in sorted(intervals.items()):
        source = sources[ref]
        result.append(
            {
                "source_ref": ref,
                "source": source.model_dump(exclude={"text"}),
                "spans": tuple(
                    {"start": start, "end": end, "quote": source.text[start:end]}
                    for start, end in _merge_review_intervals(ranges)
                ),
            }
        )
    if sum(len(span["quote"]) for row in result for span in row["spans"]) > budget:
        raise ValueError("D review source budget exceeded")
    return tuple(result)


def _g3_review_member_view(member, scope):
    # Candidate text appears once; evidence text lives only in the exact source spans.
    return {
        **member.model_dump(exclude={"evidence"}),
        "evidence": tuple(
            {
                "source_ref": scope["source_keys"][(row.revision_id, row.block_id)],
                "start": row.start,
                "end": row.end,
                "quote_hash": row.quote_hash,
            }
            for row in member.evidence
        ),
    }


def _render_g3_bounded_review_context(request, output, exact, scope):
    entity_id = exact["entity_id"]
    binding = next(row for row in request.entity_bindings if row.entity_id == entity_id)
    fields = tuple(scope["fields"][(entity_id, key)] for key in exact["field_keys"])
    targets = tuple(scope["targets"][ref] for ref in exact["review_refs"])
    members = tuple(scope["members"][row["member_id"]] for row in targets)
    pages = tuple(row for row in members if isinstance(row, FreeWikiPage))
    definitions = tuple(row for row in members if isinstance(row, ConceptDefinition))
    tasks = tuple(scope["tasks"][(entity_id, field.field_key)] for field in fields)
    source_options = _g3_review_source_options(scope, (*fields, *members), entity_id, tasks)
    ids = {*(row.assertion_id for row in fields), *(row["member_id"] for row in targets)}
    references = sorted({concept_id for row in (*fields, *pages) for concept_id in row.concept_ids})
    result = {
        "contract": "g3-d-review-bounded-window-context.830.v2",
        "request_sha256": request.request_sha256,
        "base_request_hash": compile_request_hash_g3(request.base_request),
        "output_hash": scope["output_hash"],
        "window": exact,
        "review_instructions": (
            "Review every field in candidate_partition.fields, including unknown and explicit "
            "absence. Your decision covers all listed fields even when scores is empty.",
            "Check values, subject, conditions, exceptions, versions, negations and citations "
            "against the exact offered evidence and neighboring context. Unknown is not absence.",
            "Evidence start/end select the original source substring; source text appears only "
            "in source_options.spans. Never assume omitted text supports a candidate claim.",
            "Score exactly review_targets. Other novel members are reviewed in separate windows; "
            "existing unchanged members have already been reviewed and are not targets here.",
            "Reject unsupported claims; if necessary source context is unavailable, return "
            "NEEDS_HUMAN with the affected field keys or member refs rather than guessing.",
        ),
        "entity_binding": {
            key: getattr(binding, key)
            for key in (
                "entity_id",
                "entity_version",
                "display_name",
                "issuer",
                "product_code",
                "version_label",
                "schema_pack_id",
                "schema_version",
                "schema_pack_sha256",
                "profile_id",
                "profile_version",
                "profile_sha256",
                "source_material_ids",
            )
        },
        "field_descriptors": tuple(
            {
                "field_key": task.field_key,
                "short_title": task.short_title,
                "description": task.description,
                "source_guidance": task.source_guidance,
                "value_constraint": task.value_constraint,
            }
            for task in tasks
        ),
        "candidate_partition": {
            "fields": tuple(_g3_review_member_view(row, scope) for row in fields),
            "pages": tuple(_g3_review_member_view(row, scope) for row in pages),
            "owned_novel_definitions": tuple(
                _g3_review_member_view(row, scope) for row in definitions
            ),
            "linked_concept_refs": tuple(
                {
                    "concept_id": ref,
                    "title": scope["members"][ref].title,
                    "canonical_key": scope["members"][ref].canonical_key,
                    "sense_key": scope["members"][ref].sense_key,
                    "definition_hash": _compile_definition_hash(scope["members"][ref]),
                }
                for ref in references
                if ref in scope["members"]
            ),
            "audit": tuple(row for row in output.audit if row.key in ids),
        },
        "source_options": source_options,
        "review_targets": targets,
        "local_whole_candidate_binding": {
            "output_hash": scope["output_hash"],
            "definition_count": len(output.definitions),
            "field_count": len(output.fields),
            "page_count": len(output.pages),
            "audit_count": len(output.audit),
        },
        "response_schema": G3DReviewReferenceResponseV1.model_json_schema(),
    }
    if len(batch_json_bytes_830_g3(result)) > _REVIEW_WINDOW_POLICY["max_context_bytes"]:
        raise ValueError("D review window exceeds context byte budget")
    return result


def derive_gemini_d_review_windows(request, output) -> tuple[dict[str, object], ...]:
    """Partition only novel members, bounding both evidence and complete context size."""
    return _derive_g3_review_partition(request, output)


def _derive_g3_review_partition(request, output, candidate_window=None):
    # Exact reopening needs only the relevant fixed parent group, not every sibling.
    scope = _g3_review_scope(request, output)
    rows = []

    def add(common, field_keys=(), review_refs=()):
        value = {
            **common,
            "kind": "FIELDS_REVIEW" if field_keys else "MEMBERS_REVIEW",
            "field_keys": tuple(field_keys),
            "review_refs": tuple(review_refs),
        }
        window = {
            **value,
            "window_id": _g3_d_ref(
                "window",
                request.request_sha256,
                {
                    "output_hash": scope["output_hash"],
                    "review_policy": _REVIEW_WINDOW_POLICY,
                    **value,
                },
            ),
        }
        try:
            _render_g3_bounded_review_context(request, output, window, scope)
        except ValueError as exc:
            if "budget" not in str(exc) or len(field_keys) <= 1:
                raise
            split = len(field_keys) // 2
            add(common, field_keys[:split])
            add(common, field_keys[split:])
            return
        rows.append(window)

    for binding, primary, slot in scope["entity_rows"]:
        if candidate_window is not None and candidate_window.get("entity_id") != binding.entity_id:
            continue
        common = dict(
            primary_material_id=primary,
            material_ids=binding.source_material_ids,
            entity_slot=slot,
            entity_id=binding.entity_id,
            entity_ref=scope["entity_refs"][binding.entity_id],
        )
        keys = sorted(key for entity, key in scope["fields"] if entity == binding.entity_id)
        for start in range(0, len(keys), _REVIEW_WINDOW_POLICY["max_fields"]):
            group = keys[start : start + _REVIEW_WINDOW_POLICY["max_fields"]]
            if candidate_window is not None and (
                candidate_window.get("kind") != "FIELDS_REVIEW"
                or not candidate_window.get("field_keys")
                or candidate_window["field_keys"][0] not in group
            ):
                continue
            add(common, group)
        for ref, owner in sorted(scope["target_owners"].items()):
            if owner == binding.entity_id and (
                candidate_window is None
                or (candidate_window.get("kind") == "MEMBERS_REVIEW"
                    and ref in candidate_window.get("review_refs", ()))
            ):
                add(common, review_refs=(ref,))
    if len(rows) > 300:
        raise ValueError("D review window call capacity exceeded")
    return tuple(rows)


def _exact_gemini_d_review_window(request, output, window) -> dict[str, object]:
    if not isinstance(window, dict):
        raise ValueError("invalid D review window")
    matches = [
        row
        for row in _derive_g3_review_partition(request, output, candidate_window=window)
        if row["window_id"] == window.get("window_id")
    ]
    if len(matches) != 1 or batch_json_bytes_830_g3(matches[0]) != batch_json_bytes_830_g3(window):
        raise ValueError("foreign D review window")
    return matches[0]


def render_gemini_d_review_window_context(identity, request, output, window) -> dict[str, object]:
    if not _is_g3_gemini_d_identity("D_REVIEW", identity):
        raise ValueError("D review windows require Gemini verify identity")
    exact = _exact_gemini_d_review_window(request, output, window)
    return _render_g3_bounded_review_context(
        request, output, exact, _g3_review_scope(request, output)
    )


def _g3_novel_page_ids(
    request: BatchConceptCompileRequest830G3V1, output: CompileOutput
) -> set[str]:
    existing = {
        definition.concept_id: _compile_definition_hash(definition)
        for definition in request.base_request.existing_definitions
    }
    identifiers = {
        definition.concept_id
        for definition in output.definitions
        if existing.get(definition.concept_id) != _compile_definition_hash(definition)
    }
    existing_pages = {free_page_id(page): page for page in request.base_request.existing_pages}
    identifiers.update(
        free_page_id(page)
        for page in output.pages
        if existing_pages.get(free_page_id(page)) != page
    )
    return identifiers

def _g3_human_admission(
    request: BatchConceptCompileRequest830G3V1,
    output: CompileOutput,
    checked: ReviewOutput,
) -> HumanBatchAdmission:
    if checked.decision not in ("PASS", "NEEDS_HUMAN"):
        raise ValueError("REVIEW_NOT_APPROVED_OR_STALE")
    pending: list[str] = []
    for member_id in sorted(_g3_novel_page_ids(request, output)):
        score = checked.page_scores.get(member_id)
        if score is None or score.total < 60:
            raise ValueError("PAGE_ADMISSION_REJECTED")
        if score.total < 80:
            pending.append(member_id)
    return HumanBatchAdmission(
        contract="concept-admission.830.g2.v1",
        status="NEEDS_HUMAN",
        pending_page_ids=tuple(pending),
    )


def _g3_d_display_context(
    request: BatchConceptCompileRequest830G3V1,
    by_source_key: dict[tuple[str, str], str],
) -> dict[str, object]:
    """Project signed typed input for Gemini display without changing its domain hash."""

    base_request = {
        name: (
            tuple(
                {
                    **source.model_dump(mode="json", exclude={"text"}),
                    "source_ref": by_source_key[(source.revision_id, source.block_id)],
                }
                for source in request.base_request.sources
            )
            if name == "sources"
            else getattr(request.base_request, name)
        )
        for name in type(request.base_request).model_fields
    }
    corpus = request.resolution_inputs.corpus
    corpus_projection = {
        name: (
            tuple(
                {
                    field: (
                        tuple(
                            {
                                **block.model_dump(mode="json", exclude={"text"}),
                                "source_ref": by_source_key.get(
                                    (block.revision_id, block.block_id)
                                ),
                            }
                            for block in entry.blocks
                        )
                        if field == "blocks"
                        else getattr(entry, field)
                    )
                    for field in type(entry).model_fields
                }
                for entry in corpus.entries
            )
            if name == "entries"
            else getattr(corpus, name)
        )
        for name in type(corpus).model_fields
    }
    resolution_inputs = {
        name: (
            corpus_projection
            if name == "corpus"
            else getattr(request.resolution_inputs, name)
        )
        for name in type(request.resolution_inputs).model_fields
    }

    selected_packs = {
        (binding.schema_pack_id, binding.schema_version, binding.schema_pack_sha256)
        for binding in request.entity_bindings
    }
    selected_entries = tuple(
        entry
        for entry in request.catalog.entries
        if (
            entry.pack.schema_pack_id,
            entry.pack.schema_version,
            entry.pack.schema_pack_sha256,
        )
        in selected_packs
    )
    if len(selected_entries) != len(selected_packs):
        raise ValueError("D display catalog selection mismatch")
    catalog = {
        name: selected_entries if name == "entries" else getattr(request.catalog, name)
        for name in type(request.catalog).model_fields
    }
    semantic_request = {
        name: (
            base_request
            if name == "base_request"
            else catalog
            if name == "catalog"
            else resolution_inputs
            if name == "resolution_inputs"
            else getattr(request, name)
        )
        for name in type(request).model_fields
    }
    return {
        "contract": "g3-d-compile-display-context.830.v1",
        "semantic_request": semantic_request,
        "request_sha256": request.request_sha256,
        "base_request_hash": compile_request_hash_g3(request.base_request),
        "output_mode": "NEW_MEMBERS_ONLY",
    }


def render_g3_d_prompt_context(
    stage: Literal["D_COMPILE", "D_REVIEW"],
    identity: ModelIdentity,
    request: BatchConceptCompileRequest830G3V1,
    output: CompileOutput | None = None,
) -> dict[str, object]:
    """Render the identity-selected D prompt context used by host and runtime."""

    if stage == "D_COMPILE":
        if output is not None:
            raise ValueError("D compile context cannot contain an output")
        if not _is_g3_gemini_d_identity(stage, identity):
            return {
                "contract": "g3-d-compile-prompt-context.830.v1",
                "context": compiler_context_g3(request),
                "response_schema": CompileOutput.model_json_schema(),
            }
        source_options, _, source_keys = _g3_d_source_index(request)
        entity_refs = _g3_d_entity_refs(request)
        concept_rows, _ = _g3_d_existing_concept_refs(request)
        return {
            "contract": "g3-d-compile-prompt-context.830.v1",
            "context": _g3_d_display_context(request, source_keys),
            "field_targets": _g3_d_field_targets(request, entity_refs),
            "source_options": source_options,
            "entity_source_refs": _g3_d_entity_source_refs(
                request, source_keys, entity_refs
            ),
            "existing_concept_refs": concept_rows,
            "response_schema": G3DCompileReferenceResponseV1.model_json_schema(),
        }
    if output is None:
        raise ValueError("D review context requires the final output")
    if not _is_g3_gemini_d_identity(stage, identity):
        return {
            "contract": "g3-d-review-prompt-context.830.v1",
            "context": review_context_g3(request, output),
            "response_schema": ReviewOutput.model_json_schema(),
        }
    return {
        "contract": "g3-d-review-prompt-context.830.v1",
        "context": render_gemini_d_review_display_context(request, output),
        "review_targets": _g3_d_review_targets(request, output),
        "response_schema": G3DReviewReferenceResponseV1.model_json_schema(),
    }


def g3_d_template_name(stage: str, identity: ModelIdentity) -> str:
    if _is_g3_gemini_d_identity(stage, identity):
        if stage == "D_COMPILE":
            return "g3_d_compile_references_v1.txt"
        if stage == "D_REVIEW":
            return "g3_d_review_references_v1.txt"
    return {"D_COMPILE": "g3_d_compile_v1.txt", "D_REVIEW": "g3_d_review_v1.txt"}[stage]


def _resolve_g3_d_evidence(
    selections: tuple[G3DSourceSelectionV1, ...],
    sources: dict[str, SourceBlock],
    *,
    allowed: set[str] | None = None,
) -> tuple[Evidence, ...]:
    keys = tuple((item.source_ref, item.quote) for item in selections)
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate D source selection")
    evidence: list[Evidence] = []
    for selection in selections:
        source = sources.get(selection.source_ref)
        if source is None or (allowed is not None and selection.source_ref not in allowed):
            raise ValueError("foreign D source reference")
        starts: list[int] = []
        cursor = 0
        while True:
            position = source.text.find(selection.quote, cursor)
            if position < 0:
                break
            starts.append(position)
            cursor = position + 1
        if len(starts) != 1:
            raise ValueError("D source quote must occur exactly once")
        start = starts[0]
        row = Evidence(
            **source.model_dump(exclude={"text"}),
            start=start,
            end=start + len(selection.quote),
            quote=selection.quote,
            quote_hash=hashlib.sha256(selection.quote.encode()).hexdigest(),
        )
        verify_evidence(row, (source,))
        evidence.append(row)
    return tuple(sorted(evidence, key=lambda item: (item.revision_id, item.block_id, item.start)))


def project_gemini_d_compile_response(
    raw: bytes,
    request: BatchConceptCompileRequest830G3V1,
    window: dict[str, object] | None = None,
) -> CompileOutput:
    response = G3DCompileReferenceResponseV1.model_validate(_unique_json_bytes(raw))
    if canonical_json(response.model_dump(mode="json", round_trip=True)) != raw:
        raise ValueError("D compile semantic wire mismatch")
    identity = ModelIdentity(
        provider="g3-user-gateway", family="gemini",
        deployment_id="gemini-3.7-flash-medium", role="extract",
        policy_version="g3-user-gemini-gateway-v1",
    )
    context = (
        render_g3_d_prompt_context("D_COMPILE", identity, request)
        if window is None
        else render_gemini_d_compile_window_context(identity, request, window)
    )
    return _project_gemini_d_compile_response_with_context(response, request, window, context)


def _project_gemini_d_compile_response_with_context(
    response: G3DCompileReferenceResponseV1,
    request: BatchConceptCompileRequest830G3V1,
    window: dict[str, object] | None,
    context: dict[str, object],
) -> CompileOutput:
    """Shared strict projector after raw parsing and caller-owned scope validation."""
    if window is not None:
        validate_routed_selections(
            tuple((selection.source_ref, selection.quote)
                  for row in (*response.definitions, *response.fields, *response.pages)
                  for selection in row.evidence),
            context["source_options"],
        )
    _, sources, _ = _g3_d_source_index(request)
    task_index = {
        (task.entity_id, task.field_key): task for task in adapt_catalog_field_tasks(request)
    }
    context_field_targets = cast(list[dict[str, object]], context["field_targets"])
    context_entity_sources = cast(list[dict[str, object]], context["entity_source_refs"])
    field_targets = {
        cast(str, row["field_ref"]): row for row in context_field_targets
    }
    entity_sources = {
        cast(str, row["entity_ref"]): set(cast(list[str], row["source_refs"]))
        for row in context_entity_sources
    }
    entity_ids = {
        cast(str, row["entity_ref"]): cast(str, row["entity_id"])
        for row in context_entity_sources
    }
    existing_rows, concept_refs = _g3_d_existing_concept_refs(request)
    del existing_rows
    definition_refs = tuple(row.definition_ref for row in response.definitions)
    window_kind = None if window is None else cast(str, window["kind"])
    if window_kind == "FIELDS" and (response.definitions or response.pages):
        raise ValueError("D field window cannot create definitions or pages")
    if window_kind == "ENTITY_SYNTHESIS" and response.fields:
        raise ValueError("D synthesis window cannot contain fields")
    if window is not None and (
        response.transformation not in {"EXTRACT", "SYNTHESIZE"}
        or (window_kind == "FIELDS" and response.transformation != "EXTRACT")
    ):
        raise ValueError("D window transformation is invalid for its kind")
    if (
        len(definition_refs) != len(set(definition_refs))
        or set(definition_refs).intersection(concept_refs)
    ):
        raise ValueError("duplicate D definition reference")
    definitions: list[ConceptDefinition] = []
    dispositions: list[AuditDisposition] = []
    window_sources = (
        None
        if window is None
        else entity_sources[cast(str, window["entity_ref"])]
    )
    for definition_row in response.definitions:
        if not definition_row.evidence:
            raise ValueError("D definition evidence is required")
        definition = ConceptDefinition(
            space_id=request.base_request.space_id,
            canonical_key=definition_row.canonical_key,
            sense_key=definition_row.sense_key,
            title=definition_row.title,
            body=definition_row.body,
            evidence=_resolve_g3_d_evidence(
                definition_row.evidence, sources, allowed=window_sources
            ),
            aliases=definition_row.aliases,
            origin="MODEL_COMPILE",
        )
        definitions.append(definition)
        concept_refs[definition_row.definition_ref] = definition.concept_id
        dispositions.append(
            AuditDisposition(
                key=definition.concept_id,
                disposition=definition_row.disposition,
                reason=definition_row.audit_reason,
            )
        )
    field_refs = tuple(row.field_ref for row in response.fields)
    if len(field_refs) != len(set(field_refs)) or set(field_refs) != set(field_targets):
        raise ValueError("D field reference coverage mismatch")
    fields: list[FieldAssertion] = []
    for field_row in response.fields:
        target = field_targets[field_row.field_ref]
        entity_ref = cast(str, target["entity_ref"])
        if field_row.state == "unknown":
            if (
                field_row.value is not None
                or field_row.evidence
                or field_row.unknown_reason is None
            ):
                raise ValueError("D unknown field semantic shape mismatch")
        elif (
            field_row.value is None
            or not field_row.evidence
            or field_row.unknown_reason is not None
        ):
            raise ValueError("D known field semantic shape mismatch")
        try:
            links = tuple(concept_refs[ref] for ref in field_row.concept_refs)
        except KeyError as exc:
            raise ValueError("foreign D concept reference") from exc
        if len(field_row.concept_refs) != len(set(field_row.concept_refs)):
            raise ValueError("duplicate D concept reference")
        field = FieldAssertion(
            space_id=request.base_request.space_id,
            entity_id=cast(str, target["entity_id"]),
            field_key=cast(str, target["field_key"]),
            entity_version=cast(str, target["entity_version"]),
            state=field_row.state,
            value=field_row.value,
            attempted=True,
            unknown_reason=field_row.unknown_reason,
            evidence=_resolve_g3_d_evidence(
                field_row.evidence, sources, allowed=entity_sources[entity_ref]
            ),
            concept_ids=links,
            conditions=field_row.conditions,
            exceptions=field_row.exceptions,
            valid_time=field_row.valid_time,
        )
        task = task_index.get((field.entity_id, field.field_key))
        if task is not None:
            FieldTaskEvidenceResultV1.create(
                task=task, state=field.state, value=field.value,
                evidence=field.evidence, unknown_reason=field.unknown_reason,
                concept_ids=field.concept_ids, conditions=field.conditions,
                exceptions=field.exceptions, valid_time=field.valid_time,
                source_blocks=tuple(sources.values()),
            )
        fields.append(field)
        dispositions.append(
            AuditDisposition(
                key=field.assertion_id,
                disposition="field_rule",
                reason=field_row.audit_reason,
            )
        )
    page_refs = tuple(row.page_ref for row in response.pages)
    if len(page_refs) != len(set(page_refs)):
        raise ValueError("duplicate D page reference")
    pages: list[FreeWikiPage] = []
    for page_row in response.pages:
        entity_id = entity_ids.get(page_row.entity_ref)
        if entity_id is None:
            raise ValueError("foreign D page entity reference")
        if window is not None and entity_id != window["entity_id"]:
            raise ValueError("foreign D page window entity")
        try:
            links = tuple(concept_refs[ref] for ref in page_row.concept_refs)
        except KeyError as exc:
            raise ValueError("foreign D concept reference") from exc
        if len(page_row.concept_refs) != len(set(page_row.concept_refs)):
            raise ValueError("duplicate D concept reference")
        page = FreeWikiPage(
            space_id=request.base_request.space_id,
            entity_id=entity_id,
            entity_version=request.base_request.entity_versions[entity_id],
            stable_key=page_row.stable_key,
            title=page_row.title,
            body=page_row.body,
            evidence=_resolve_g3_d_evidence(
                page_row.evidence,
                sources,
                allowed=entity_sources[page_row.entity_ref],
            ),
            concept_ids=links,
            conditions=page_row.conditions,
            exceptions=page_row.exceptions,
            valid_time=page_row.valid_time,
        )
        pages.append(page)
        dispositions.append(
            AuditDisposition(
                key=free_page_id(page),
                disposition="new_page",
                reason=page_row.audit_reason,
            )
        )
    output = CompileOutput(
        request_hash=compile_request_hash_g3(request.base_request),
        definitions=tuple(sorted(definitions, key=lambda item: item.concept_id)),
        fields=tuple(sorted(fields, key=lambda item: (item.entity_id, item.field_key))),
        pages=tuple(sorted(pages, key=free_page_id)),
        audit=tuple(sorted(dispositions, key=lambda item: item.key)),
        transformation=response.transformation,
    )
    return output


def project_gemini_d_compile_window_response(
    raw: bytes,
    request: BatchConceptCompileRequest830G3V1,
    window: dict[str, object],
) -> CompileOutput:
    """Project one response against its exact code-owned D window."""

    exact = _exact_gemini_d_window(request, window)
    return project_gemini_d_compile_response(raw, request, exact)


def aggregate_gemini_d_compile_window_outputs(
    request: BatchConceptCompileRequest830G3V1,
    outputs: Sequence[CompileOutput],
) -> CompileOutput:
    """Union independently validated windows into one exact model delta."""

    windows = derive_gemini_d_compile_windows(request)
    return _aggregate_gemini_d_compile_outputs(request, windows, outputs)


def _aggregate_gemini_d_compile_outputs(
    request: BatchConceptCompileRequest830G3V1,
    windows: Sequence[dict[str, object]],
    outputs: Sequence[CompileOutput],
) -> CompileOutput:
    """Shared complete-delta validation for fixed and explicitly recovered partitions."""
    if len(outputs) != len(windows):
        raise ValueError("D window output count mismatch")
    definitions: dict[str, ConceptDefinition] = {}
    fields: dict[tuple[str, str], FieldAssertion] = {}
    pages: dict[str, FreeWikiPage] = {}
    audits: dict[str, AuditDisposition] = {}
    field_targets = _g3_d_field_targets(request, _g3_d_entity_refs(request))
    for window, output in zip(windows, outputs, strict=True):
        if (
            output.request_hash != compile_request_hash_g3(request.base_request)
            or output.transformation not in {"EXTRACT", "SYNTHESIZE"}
            or (window["kind"] == "FIELDS" and output.transformation != "EXTRACT")
        ):
            raise ValueError("D window output identity mismatch")
        window_refs = set(cast(tuple[str, ...], window["field_refs"]))
        expected_fields = {
            (cast(str, row["entity_id"]), cast(str, row["field_key"]))
            for row in field_targets
            if row["field_ref"] in window_refs
        }
        if {(row.entity_id, row.field_key) for row in output.fields} != expected_fields:
            raise ValueError("D window field coverage mismatch")
        if window["kind"] == "FIELDS" and (output.definitions or output.pages):
            raise ValueError("D field window generated synthesis members")
        if window["kind"] == "ENTITY_SYNTHESIS" and output.fields:
            raise ValueError("D synthesis window generated fields")
        for key, row in (
            *((item.concept_id, item) for item in output.definitions),
            *((free_page_id(item), item) for item in output.pages),
        ):
            target = definitions if isinstance(row, ConceptDefinition) else pages
            if key in target:
                raise ValueError("duplicate D window generated member")
            target[key] = row
        for row in output.fields:
            key = (row.entity_id, row.field_key)
            if key in fields or row.attempted is not True:
                raise ValueError("duplicate or unattempted D window field")
            fields[key] = row
        for row in output.audit:
            if row.key in audits:
                raise ValueError("duplicate D window audit")
            audits[row.key] = row
    expected = {
        (cast(str, row["entity_id"]), cast(str, row["field_key"]))
        for row in _g3_d_field_targets(request, _g3_d_entity_refs(request))
    }
    if set(fields) != expected:
        raise ValueError("D window field coverage mismatch")
    output = CompileOutput(
        request_hash=compile_request_hash_g3(request.base_request),
        definitions=tuple(sorted(definitions.values(), key=lambda item: item.concept_id)),
        fields=tuple(sorted(fields.values(), key=lambda item: (item.entity_id, item.field_key))),
        pages=tuple(sorted(pages.values(), key=free_page_id)),
        audit=tuple(sorted(audits.values(), key=lambda item: item.key)),
        transformation=(
            "SYNTHESIZE" if any(row.transformation == "SYNTHESIZE" for row in outputs)
            else "EXTRACT"
        ),
    )
    probe = record_model_compile(
        request,
        output,
        run_id="g3-d-window-aggregate-validation",
        implementation="g3-gemini-d-window-aggregate.830.v1",
        raw=batch_json_bytes_830_g3(output).decode(),
    )
    validate_delta_output(request, probe)
    return output


def project_gemini_d_review_response(
    raw: bytes,
    request: BatchConceptCompileRequest830G3V1,
    output: CompileOutput,
) -> ReviewOutput:
    response = G3DReviewReferenceResponseV1.model_validate(_unique_json_bytes(raw))
    if canonical_json(response.model_dump(mode="json", round_trip=True)) != raw:
        raise ValueError("D review semantic wire mismatch")
    targets = _g3_d_review_targets(request, output)
    target_index = {cast(str, row["review_ref"]): cast(str, row["member_id"]) for row in targets}
    refs = tuple(item.review_ref for item in response.scores)
    if len(refs) != len(set(refs)) or set(refs) != set(target_index):
        raise ValueError("D review reference coverage mismatch")
    scores = {
        target_index[item.review_ref]: ValueScore.model_validate(
            item.model_dump(exclude={"review_ref"})
        )
        for item in response.scores
    }
    return ReviewOutput(
        request_hash=compile_request_hash_g3(request.base_request),
        output_hash=compile_output_hash_g3(output),
        decision=response.decision,
        reasons=response.reasons,
        page_scores=scores,
    )


def project_gemini_d_review_window_response(
    raw: bytes,
    request: BatchConceptCompileRequest830G3V1,
    output: CompileOutput,
    window: dict[str, object],
) -> ReviewOutput:
    """Project one review response against its exact entity-owned targets."""

    exact = _exact_gemini_d_review_window(request, output, window)
    all_targets = {
        cast(str, row["review_ref"]): cast(str, row["member_id"])
        for row in _g3_d_review_targets(request, output)
    }
    return _project_g3_exact_review_response(raw, request, output, exact, all_targets)


def _project_g3_exact_review_response(raw, request, output, exact, all_targets):
    """Shared projector after the caller has derived and bound the exact window."""
    response = G3DReviewReferenceResponseV1.model_validate(_unique_json_bytes(raw))
    if canonical_json(response.model_dump(mode="json", round_trip=True)) != raw:
        raise ValueError("D review semantic wire mismatch")
    expected_refs = set(cast(tuple[str, ...], exact["review_refs"]))
    refs = tuple(item.review_ref for item in response.scores)
    if len(refs) != len(set(refs)) or set(refs) != expected_refs:
        raise ValueError("D review window reference coverage mismatch")
    if not expected_refs <= set(all_targets):
        raise ValueError("D review window contains a foreign reference")
    scores = {
        all_targets[item.review_ref]: ValueScore.model_validate(
            item.model_dump(exclude={"review_ref"})
        )
        for item in response.scores
    }
    return ReviewOutput(
        request_hash=compile_request_hash_g3(request.base_request),
        output_hash=compile_output_hash_g3(output),
        decision=response.decision,
        reasons=response.reasons,
        page_scores=scores,
    )


def aggregate_gemini_d_review_window_outputs(
    request: BatchConceptCompileRequest830G3V1,
    output: CompileOutput,
    reviews: Sequence[ReviewOutput],
) -> ReviewOutput:
    """Join exact entity review partitions with conservative global disposition."""

    windows = derive_gemini_d_review_windows(request, output)
    if len(reviews) != len(windows):
        raise ValueError("D review window output count mismatch")
    request_hash = compile_request_hash_g3(request.base_request)
    output_hash = compile_output_hash_g3(output)
    target_index = {
        cast(str, row["review_ref"]): cast(str, row["member_id"])
        for row in _g3_d_review_targets(request, output)
    }
    scores: dict[str, ValueScore] = {}
    reasons: list[str] = []
    decisions: list[str] = []
    for window, review in zip(windows, reviews, strict=True):
        expected_member_ids = {
            target_index[review_ref]
            for review_ref in cast(tuple[str, ...], window["review_refs"])
        }
        if (
            review.request_hash != request_hash
            or review.output_hash != output_hash
            or set(review.page_scores) != expected_member_ids
        ):
            raise ValueError("D review window output identity or coverage mismatch")
        if set(scores) & set(review.page_scores):
            raise ValueError("duplicate D review window score")
        scores.update(review.page_scores)
        reasons.extend(review.reasons)
        decisions.append(review.decision)
    if set(scores) != set(target_index.values()):
        raise ValueError("D review window aggregate coverage mismatch")
    decision: Literal["PASS", "REJECT", "NEEDS_HUMAN"]
    if "REJECT" in decisions:
        decision = "REJECT"
    elif "NEEDS_HUMAN" in decisions:
        decision = "NEEDS_HUMAN"
    else:
        decision = "PASS"
    return ReviewOutput(
        request_hash=request_hash,
        output_hash=output_hash,
        decision=decision,
        reasons=tuple(reasons),
        page_scores=scores,
    )


def _c_response_schema(identity: ModelIdentity | None = None) -> dict[str, object]:
    if identity is not None and _is_g3_gemini_identity(identity):
        schema = G3SemanticReferenceResponseV1.model_json_schema()
        definitions = cast(dict[str, dict[str, object]], schema["$defs"])
        for definition, field in (
            ("G3SemanticReferenceMaterialV1", "entities"),
            ("G3SemanticReferenceMaterialV1", "evidence"),
            ("G3SemanticReferenceMaterialV1", "material_role_evidence_refs"),
            ("G3SemanticEntityV1", "labels"),
            ("G3SemanticLabelV1", "evidence_refs"),
        ):
            properties = cast(dict[str, dict[str, object]], definitions[definition]["properties"])
            properties[field]["minItems"] = 1
        return schema
    return G3SemanticResponseV1.model_json_schema()


class G3NativeCharacterBoxV1(_SemanticModel):
    index: Annotated[StrictInt, Field(ge=0)]
    x: StrictFloat
    y: StrictFloat
    width: StrictFloat
    height: StrictFloat


class G3NativePageProjectionV1(_SemanticModel):
    block_ref: Text
    material_id: Text
    revision_id: Text
    block_id: Text
    page_number: Annotated[StrictInt, Field(gt=0)]
    page_width: StrictFloat
    page_height: StrictFloat
    text: BodyText
    boxes: tuple[G3NativeCharacterBoxV1, ...]


class G3NativePageProjectionSetV1(_SemanticModel):
    contract: Literal["g3-native-page-projections.830.v1"]
    pages: tuple[G3NativePageProjectionV1, ...]


def canonical_native_page_projections(value: G3NativePageProjectionSetV1) -> bytes:
    """Serialize only the exact native projection root with source bytes intact."""

    if type(value) is not G3NativePageProjectionSetV1:
        raise TypeError("native projection serializer requires its exact root type")
    validated = G3NativePageProjectionSetV1.model_validate(value)
    return canonical_json(validated.model_dump(mode="json", round_trip=True))


def _decode_unique_canonical_json_bytes(raw: bytes) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    if raw != canonical_json(value):
        raise ValueError("response must be canonical JSON")
    return value


def _unique_json_bytes(raw: bytes) -> object:
    if type(raw) is not bytes or not raw or len(raw) > 8 * 1024 * 1024:
        raise ValueError("invalid semantic response bytes")
    return _decode_unique_canonical_json_bytes(raw)


def _parse_native_page_projection_bytes(raw: bytes) -> G3NativePageProjectionSetV1:
    from insurance_harness.run_admission import evaluator

    if (
        type(raw) is not bytes
        or not raw
        or len(raw) > evaluator._MAX_G3_NATIVE_PROJECTION_BYTES
    ):
        raise ValueError("invalid native projection bytes")
    projection = G3NativePageProjectionSetV1.model_validate(
        _decode_unique_canonical_json_bytes(raw)
    )
    if canonical_json(projection.model_dump(mode="json", round_trip=True)) != raw:
        raise ValueError("native projection typed wire mismatch")
    return projection


def parse_c_semantic_response_bytes(raw: bytes) -> tuple[G3SemanticResponseV1, bytes]:
    """Parse the exact C response and preserve its canonical source-body bytes."""

    response = G3SemanticResponseV1.model_validate(_unique_json_bytes(raw))
    if canonical_json(response.model_dump(mode="json", round_trip=True)) != raw:
        raise ValueError("semantic response typed wire mismatch")
    return response, raw


def _structural_id(domain: str, material_id: str, local_ref: str) -> str:
    return hashlib.sha256(
        domain.encode()
        + b"\0"
        + canonical_json({"local_ref": local_ref, "material_id": material_id})
    ).hexdigest()


def _native_page_evidence(
    *,
    locator: G3SemanticLocatorV1,
    page: G3NativePageProjectionV1,
    source: SourceBlock,
) -> Evidence:
    text = source.text
    if locator.end > len(text) or locator.start >= locator.end:
        raise ValueError("semantic locator outside W1 block")
    if text[locator.start : locator.end] != locator.quote:
        raise ValueError("semantic quote echo mismatch")
    occurrences: list[int] = []
    cursor = 0
    while True:
        found = page.text.find(locator.quote, cursor)
        if found < 0:
            break
        occurrences.append(found)
        cursor = found + 1
    if len(occurrences) != 1:
        raise ValueError("native quote occurrence is not unique")
    begin = occurrences[0]
    by_index = {box.index: box for box in page.boxes}
    visible = tuple(
        index
        for index, character in enumerate(locator.quote, start=begin)
        if not character.isspace()
    )
    if (
        not math.isfinite(page.page_width)
        or not math.isfinite(page.page_height)
        or page.page_width <= 0
        or page.page_height <= 0
        or tuple(box.index for box in page.boxes)
        != tuple(sorted(set(box.index for box in page.boxes)))
        or len(by_index) != len(page.boxes)
        or any(index not in by_index for index in visible)
    ):
        raise ValueError("native box coverage is incomplete")
    for index in visible:
        box = by_index[index]
        if (
            not all(
                math.isfinite(value)
                for value in (
                    box.x,
                    box.y,
                    box.width,
                    box.height,
                    page.page_width,
                    page.page_height,
                )
            )
            or box.x < 0
            or box.y < 0
            or box.width <= 0
            or box.height <= 0
            or box.x + box.width > page.page_width
            or box.y + box.height > page.page_height
        ):
            raise ValueError("native box is outside page")
    evidence = Evidence(
        **source.model_dump(exclude={"text"}),
        start=locator.start,
        end=locator.end,
        quote=locator.quote,
        quote_hash=hashlib.sha256(locator.quote.encode()).hexdigest(),
    )
    verify_evidence(evidence, (source,))
    return evidence


def assemble_c_semantic_response(
    *,
    raw: bytes,
    corpus: BatchCorpusV1,
    requested_material_ids: tuple[str, ...],
    native_pages: tuple[G3NativePageProjectionV1, ...],
    allowed_material_roles: tuple[str, ...],
    allowed_taxonomy_labels: tuple[str, ...],
    model_request_sha256: str,
    use_locator_refs: bool = False,
) -> tuple[MaterialProposalV1, ...]:
    """Build C proposals from local refs while retaining all source authority locally."""

    if use_locator_refs:
        response = _resolve_c_source_references(
            raw, corpus=corpus, native_pages=native_pages,
            requested_material_ids=requested_material_ids,
        )
    else:
        response, _ = parse_c_semantic_response_bytes(raw)
    if tuple(sorted(set(requested_material_ids))) != requested_material_ids:
        raise ValueError("requested materials must be sorted unique")
    entries = {entry.material_id: entry for entry in corpus.entries}
    pages = {page.block_ref: page for page in native_pages}
    if len(pages) != len(native_pages):
        raise ValueError("opaque block refs must be unique")
    material_ids = tuple(item.material_id for item in response.materials)
    if material_ids != tuple(sorted(set(material_ids))) or any(
        item not in requested_material_ids or item not in entries for item in material_ids
    ):
        raise ValueError("semantic material scope mismatch")
    proposals: list[MaterialProposalV1] = []
    for material in response.materials:
        entry = entries[material.material_id]
        if material.material_role not in allowed_material_roles:
            raise ValueError("material role outside policy")
        evidence_refs = tuple(item.evidence_ref for item in material.evidence)
        entity_refs = tuple(item.entity_ref for item in material.entities)
        if (
            evidence_refs != tuple(sorted(set(evidence_refs)))
            or entity_refs != tuple(sorted(set(entity_refs)))
            or material.material_role_evidence_refs
            != tuple(sorted(set(material.material_role_evidence_refs)))
            or not material.entities
            or not material.evidence
        ):
            raise ValueError("semantic refs must be sorted unique")
        sources = {(block.revision_id, block.block_id): block for block in entry.blocks}
        evidence_by_local: dict[str, tuple[G3SemanticEvidenceV1, Evidence]] = {}
        for semantic in material.evidence:
            page = pages.get(semantic.locator.block_ref)
            if page is None or page.material_id != material.material_id:
                raise ValueError("opaque block ref crosses material")
            source = sources.get((page.revision_id, page.block_id))
            if source is None or source.page_number != page.page_number:
                raise ValueError("native page/source drift")
            if semantic.purpose == "material_role":
                valid_shape = semantic.entity_ref is None and semantic.field_key is None
            elif semantic.purpose == "field":
                valid_shape = semantic.entity_ref is not None and semantic.field_key is not None
            else:
                valid_shape = semantic.entity_ref is not None and semantic.field_key is None
            if not valid_shape:
                raise ValueError("semantic evidence scope invalid")
            evidence_by_local[semantic.evidence_ref] = (
                semantic,
                _native_page_evidence(locator=semantic.locator, page=page, source=source),
            )
        final_evidence = tuple(
            ProposalEvidenceV1(
                evidence_id=_structural_id(
                    "g3-c-evidence-ref.830.v1",
                    material.material_id,
                    semantic.evidence_ref,
                ),
                entity_proposal_ref=(
                    None
                    if semantic.entity_ref is None
                    else _structural_id(
                        "g3-c-entity-ref.830.v1",
                        material.material_id,
                        semantic.entity_ref,
                    )
                ),
                purpose=semantic.purpose,
                field_key=semantic.field_key,
                evidence=evidence,
            )
            for semantic, evidence in evidence_by_local.values()
        )
        final_entities: list[EntityProposalV1] = []
        for entity in material.entities:
            if entity.identity_evidence_refs != tuple(sorted(set(entity.identity_evidence_refs))):
                raise ValueError("identity evidence refs must be sorted unique")
            if not entity.labels or any(
                label.taxonomy_label not in allowed_taxonomy_labels for label in entity.labels
            ):
                raise ValueError("taxonomy label outside policy")
            if tuple(label.taxonomy_label for label in entity.labels) != tuple(
                sorted({label.taxonomy_label for label in entity.labels})
            ):
                raise ValueError("labels must be sorted unique")
            if sum(label.taxonomy_label == entity.primary_label for label in entity.labels) != 1:
                raise ValueError("primary label mismatch")
            referenced = set(entity.identity_evidence_refs)
            referenced.update(ref for label in entity.labels for ref in label.evidence_refs)
            if any(ref not in evidence_by_local for ref in referenced):
                raise ValueError("dangling semantic evidence ref")
            for ref in entity.identity_evidence_refs:
                evidence_model = evidence_by_local[ref][0]
                if evidence_model.entity_ref != entity.entity_ref or evidence_model.purpose in {
                    "classification",
                    "material_role",
                    "field",
                }:
                    raise ValueError("wrong-purpose identity evidence")
            for label in entity.labels:
                if (
                    label.evidence_refs != tuple(sorted(set(label.evidence_refs)))
                    or not label.evidence_refs
                    or any(
                        evidence_by_local[ref][0].entity_ref != entity.entity_ref
                        or evidence_by_local[ref][0].purpose != "classification"
                        for ref in label.evidence_refs
                    )
                ):
                    raise ValueError("classification evidence mismatch")
            identity_values = {
                "issuer": () if entity.issuer is None else (entity.issuer,),
                "name": () if entity.name is None else (entity.name,),
                "product_code": (() if entity.product_code is None else (entity.product_code,)),
                "version": tuple(
                    value
                    for value in (
                        entity.version_label,
                        None
                        if entity.filing_or_registration is None
                        else entity.filing_or_registration.value,
                    )
                    if value is not None
                ),
            }
            identity_rows = tuple(
                evidence_by_local[ref][0] for ref in entity.identity_evidence_refs
            )
            if any(
                not any(
                    row.purpose == purpose and _normalized(value) in _normalized(row.locator.quote)
                    for row in identity_rows
                )
                for purpose, values in identity_values.items()
                for value in values
            ):
                raise ValueError("identity value lacks exact source evidence")
            for date in (entity.valid_from, entity.valid_through):
                if date is not None and not any(
                    row.purpose == "version" and date in row.locator.quote for row in identity_rows
                ):
                    raise ValueError("validity date lacks version evidence")
            final_entities.append(
                EntityProposalV1(
                    proposal_ref=_structural_id(
                        "g3-c-entity-ref.830.v1",
                        material.material_id,
                        entity.entity_ref,
                    ),
                    issuer=entity.issuer,
                    name=entity.name,
                    product_code=entity.product_code,
                    version_label=entity.version_label,
                    filing_or_registration=(
                        None
                        if entity.filing_or_registration is None
                        else VersionAnchorV1.model_validate(
                            entity.filing_or_registration.model_dump()
                        )
                    ),
                    identity_confidence=entity.identity_confidence,
                    identity_evidence_ids=tuple(
                        sorted(
                            _structural_id("g3-c-evidence-ref.830.v1", material.material_id, ref)
                            for ref in entity.identity_evidence_refs
                        )
                    ),
                    labels=tuple(
                        LabelProposalV1(
                            taxonomy_label=label.taxonomy_label,
                            confidence=label.confidence,
                            evidence_ids=tuple(
                                sorted(
                                    _structural_id(
                                        "g3-c-evidence-ref.830.v1",
                                        material.material_id,
                                        ref,
                                    )
                                    for ref in label.evidence_refs
                                )
                            ),
                        )
                        for label in entity.labels
                    ),
                    primary_label=entity.primary_label,
                    valid_from=entity.valid_from,
                    valid_through=entity.valid_through,
                )
            )
        payload: dict[str, object] = {
            "material_id": material.material_id,
            "corpus_entry_sha256": entry.entry_sha256,
            "model_request_sha256": model_request_sha256,
            "material_role": material.material_role,
            "material_role_evidence_ids": tuple(
                sorted(
                    _structural_id("g3-c-evidence-ref.830.v1", material.material_id, ref)
                    for ref in material.material_role_evidence_refs
                )
            ),
            "entities": tuple(sorted(final_entities, key=lambda item: item.proposal_ref)),
            "evidence": tuple(sorted(final_evidence, key=lambda item: item.evidence_id)),
        }
        proposals.append(
            MaterialProposalV1.model_validate(
                {
                    **payload,
                    "proposal_sha256": _batch_sha256("material-proposal.830.g3.v1", payload),
                }
            )
        )
    return tuple(proposals)


def parse_d_compile_output(raw: bytes) -> CompileOutput:
    return CompileOutput.model_validate(_unique_json_bytes(raw))


def parse_d_review_output(raw: bytes) -> ReviewOutput:
    return ReviewOutput.model_validate(_unique_json_bytes(raw))


def build_d_review_result(
    *, raw: bytes, output: ReviewOutput, run_id: str, context_hash: str
) -> ReviewResult:
    if parse_d_review_output(raw) != output:
        raise ValueError("review raw output mismatch")
    return ReviewResult(
        output=output,
        execution=ExecutionRecord(
            run_id=run_id,
            implementation="g3-bounded-model-review.830.v1",
            context_hash=context_hash,
            raw_output=raw.decode(),
            raw_output_hash=hashlib.sha256(raw).hexdigest(),
        ),
    )


def _build_d_compile_result_from_semantic(
    *,
    raw: bytes,
    request: BatchConceptCompileRequest830G3V1,
    identity: ModelIdentity,
    run_id: str,
) -> CompileResult:
    gemini = _is_g3_gemini_d_identity("D_COMPILE", identity)
    output = (
        project_gemini_d_compile_response(raw, request)
        if gemini
        else parse_d_compile_output(raw)
    )
    projected = (
        batch_json_bytes_830_g3(output)
        if gemini
        else canonical_json(output.model_dump(mode="json", round_trip=True))
    )
    return record_model_compile(
        request,
        output,
        run_id=run_id,
        implementation=(
            "g3-gemini-d-reference-projector.830.v1"
            if gemini
            else "g3-bounded-model-compile.830.v1"
        ),
        raw=projected.decode(),
    )


def _gemini_d_window_output(
    *,
    raw: bytes,
    request: BatchConceptCompileRequest830G3V1,
    call: G3CallPlanV1,
) -> CompileOutput:
    if call.window_id is None:
        raise ValueError("Gemini D compile call has no window")
    windows = {
        cast(str, row["window_id"]): row
        for row in derive_gemini_d_compile_windows(request)
    }
    window = windows.get(call.window_id)
    if window is None or call.material_ids != cast(tuple[str, ...], window["material_ids"]):
        raise ValueError("Gemini D compile call/window binding mismatch")
    return project_gemini_d_compile_window_response(raw, request, window)


def _prepared_gemini_d_window_output(*, raw, request, call, prepared):
    if prepared.projection_reuse is None:
        return _gemini_d_window_output(raw=raw, request=request, call=call)
    from .g3_d_recovery_execution import project_recovery_response

    window = next((row for row in prepared.recovery_windows
                   if row["window_id"] == call.window_id), None)
    if window is None or tuple(window["material_ids"]) != call.material_ids:
        raise ValueError("recovery call/window binding mismatch")
    return project_recovery_response(raw, request, window)


def _gemini_d_window_projection_hash(
    window_id: str, output: CompileOutput
) -> str:
    return _compile_sha256(
        "g3-d-compile-window-projection.830.v1",
        {"window_id": window_id, "output": output},
    )


def _gemini_d_review_window_output(
    *,
    raw: bytes,
    request: BatchConceptCompileRequest830G3V1,
    output: CompileOutput,
    call: G3CallPlanV1,
) -> ReviewOutput:
    if call.window_id is None:
        raise ValueError("Gemini D review call has no window")
    windows = {
        cast(str, row["window_id"]): row
        for row in derive_gemini_d_review_windows(request, output)
    }
    window = windows.get(call.window_id)
    if window is None or call.material_ids != cast(tuple[str, ...], window["material_ids"]):
        raise ValueError("Gemini D review call/window binding mismatch")
    return project_gemini_d_review_window_response(raw, request, output, window)


def _gemini_d_review_window_projection_hash(
    window_id: str, review: ReviewOutput
) -> str:
    return _compile_sha256(
        "g3-d-review-window-projection.830.v1",
        {"window_id": window_id, "output": review},
    )


def _build_d_review_result_from_semantic(
    *,
    raw: bytes,
    request: BatchConceptCompileRequest830G3V1,
    output: CompileOutput,
    identity: ModelIdentity,
    run_id: str,
) -> tuple[ReviewOutput, ReviewResult]:
    gemini = _is_g3_gemini_d_identity("D_REVIEW", identity)
    review = (
        project_gemini_d_review_response(raw, request, output)
        if gemini
        else parse_d_review_output(raw)
    )
    projected = (
        batch_json_bytes_830_g3(review)
        if gemini
        else canonical_json(review.model_dump(mode="json", round_trip=True))
    )
    context_hash = _compile_sha256(
        "batch-concept-review-context.830.g3.v1", review_context_g3(request, output)
    )
    result = build_d_review_result(
        raw=projected,
        output=review,
        run_id=run_id,
        context_hash=context_hash,
    )
    if gemini:
        result = result.model_copy(
            update={
                "execution": result.execution.model_copy(
                    update={"implementation": "g3-gemini-d-review-reference-projector.830.v1"}
                )
            }
        )
    return review, result


def canonical_cost_aggregation(
    stage: str,
    calls: Sequence[tuple[int, str, G3CostAuditV1]],
) -> tuple[bytes, str]:
    """Return the exact stage cost aggregation bytes and their raw SHA-256."""

    rows: list[dict[str, object]] = []
    previous = -1
    for ordinal, terminal_hash, cost in calls:
        if type(ordinal) is not int or ordinal < 0 or ordinal <= previous:
            raise ValueError("cost rows must use increasing strict integer ordinals")
        if (
            type(terminal_hash) is not str
            or len(terminal_hash) != 64
            or any(character not in "0123456789abcdef" for character in terminal_hash)
        ):
            raise ValueError("invalid call terminal hash")
        canonical_cost = G3CostAuditV1.model_validate(cost.model_dump())
        cost_value = canonical_cost.model_dump(mode="json", round_trip=True)
        rows.append(
            {
                "ordinal": ordinal,
                "call_terminal_receipt_sha256": terminal_hash,
                "cost_audit": cost_value,
                "cost_audit_sha256": hashlib.sha256(canonical_json(cost_value)).hexdigest(),
            }
        )
        previous = ordinal
    if stage not in {"C_CLASSIFY", "D_COMPILE", "D_REVIEW"}:
        raise ValueError("invalid stage cost aggregation")
    payload = canonical_json({"stage": stage, "calls": rows})
    return payload, hashlib.sha256(payload).hexdigest()


def _read_unique_json(path: Path, *, max_bytes: int = 2 * 1024 * 1024) -> tuple[object, bytes]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        payload = os.read(descriptor, max_bytes + 1)
    finally:
        os.close(descriptor)
    if not payload or len(payload) > max_bytes:
        raise ValueError("invalid artifact size")
    return json.loads(payload, object_pairs_hook=unique), payload


def _write_store_artifact(root: Path, payload: bytes, name: str) -> Path:
    from insurance_harness.model_policy.g3_bounded_gateway import _write_exclusive

    digest = hashlib.sha256(payload).hexdigest()
    directory = root / "sha256" / digest
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / name
    _write_exclusive(path, payload)
    return path


def prepare_stage(*, parent_authorization: str, stage: str, stage_input: str) -> Path:
    """Validate one complete unsigned plan, delegate-sign it, and store exact bytes."""

    from insurance_harness.run_admission import evaluator
    from insurance_harness.run_admission.g3_trust_policy import (
        load_g3_root_trust_policy,
        verify_parent_authorization,
    )
    from insurance_harness.run_admission.profiles.g3_bounded_execution import (
        validate_g3_bounded_plan,
        validate_g3_parent_scope,
    )

    parent_path = Path(parent_authorization)
    parent_digest = parent_path.parent.name
    expected_parent = (
        evaluator._ADMISSION_STORE_ROOT
        / "sha256"
        / parent_digest
        / "model-processing-authorization.json"
    )
    if parent_path != expected_parent:
        raise ValueError("parent content address mismatch")
    parent_bytes = evaluator._read_g3_parent(parent_authorization, parent_digest)
    parent = G3ModelProcessingAuthorizationEnvelopeV1.model_validate(
        _unique_json_bytes(parent_bytes)
    )
    if (
        hashlib.sha256(parent_bytes).hexdigest() != parent_digest
        or parent_bytes
        != canonical_json(parent.model_dump(mode="json", round_trip=True))
    ):
        raise ValueError("parent content address mismatch")
    verify_parent_authorization(load_g3_root_trust_policy(), parent)
    input_path = Path(stage_input)
    input_digest = input_path.parent.name
    expected_input = (
        evaluator._ADMISSION_STORE_ROOT / "sha256" / input_digest / "stage-input.json"
    )
    if input_path != expected_input:
        raise ValueError("stage input content address mismatch")
    from insurance_harness.run_admission import trust_policy

    input_bytes = trust_policy._read_root_protected_file(
        input_path,
        root=evaluator._ADMISSION_STORE_ROOT,
        max_bytes=2 * 1024 * 1024,
        reason_code="invalid_admission_artifact",
    )
    if hashlib.sha256(input_bytes).hexdigest() != input_digest:
        raise ValueError("stage input content address mismatch")
    plan = validate_g3_bounded_plan(
        G3BoundedAdmissionPlanV1.model_validate(_unique_json_bytes(input_bytes))
    )
    if input_bytes != canonical_json(plan.model_dump(mode="json", round_trip=True)):
        raise ValueError("stage input bytes are not canonical")
    if (
        plan.stage != stage
        or plan.parent_authorization_digest != hashlib.sha256(parent_bytes).hexdigest()
    ):
        raise ValueError("stage input parent/stage mismatch")
    try:
        validate_g3_parent_scope(parent.payload, plan)
    except ValueError:
        raise ValueError("stage input exceeds parent authorization") from None
    evaluator._verify_g3_current_content(plan, parent.payload)
    private_b64 = os.environ.get("G3_BOUNDED_STAGE_SIGNING_PRIVATE_KEY_B64")
    if private_b64 is None:
        raise ValueError("stage signing key is unavailable")
    raw_private = base64.b64decode(private_b64, validate=True)
    if len(raw_private) != 32 or base64.b64encode(raw_private).decode() != private_b64:
        raise ValueError("stage signing key is invalid")
    private_key = Ed25519PrivateKey.from_private_bytes(raw_private)
    public_raw = private_key.public_key().public_bytes_raw()
    signer = parent.payload.delegated_stage_signer
    if (
        base64.b64encode(public_raw).decode() != signer.public_key_b64
        or hashlib.sha256(public_raw).hexdigest() != signer.public_key_fingerprint
    ):
        raise ValueError("stage signing key is not delegated")
    parent_ref = G3ArtifactRefV1(
        contract="g3-model-processing-authorization.830.v1",
        artifact_ref=parent_authorization,
        sha256=hashlib.sha256(parent_bytes).hexdigest(),
        bytes=len(parent_bytes),
    )
    provisional = G3BoundedApprovalEnvelopeV1(
        schema_version="insurancekb.g3-bounded-run-admission-approval-envelope.v1",
        signature_domain="insurancekb.run-admission.g3-bounded-model-execution.v1",
        parent_authorization_ref=parent_ref,
        parent_authorization_digest=parent_ref.sha256,
        stage_signer_key_id=signer.key_id,
        stage_signer_public_key_fingerprint=signer.public_key_fingerprint,
        payload=plan,
        signature_b64=base64.b64encode(bytes(64)).decode(),
    )
    signature = private_key.sign(stage_approval_signed_bytes(provisional))
    envelope = provisional.model_copy(
        update={"signature_b64": base64.b64encode(signature).decode()}
    )
    envelope_bytes = canonical_json(envelope.model_dump(mode="json", round_trip=True))
    return _write_store_artifact(
        evaluator._ADMISSION_STORE_ROOT, envelope_bytes, "approval-envelope.json"
    )


def _request_for_plan(
    plan: G3BoundedAdmissionPlanV1, admission_ref: str, admission_digest: str
) -> Any:
    from insurance_harness.model_policy import StrictAdmissionRequestBinding

    return StrictAdmissionRequestBinding(
        expected_purpose=plan.purpose,
        expected_run_schema_version=plan.run_schema_version,
        expected_run_id=plan.run_id,
        expected_run_revision=plan.run_revision,
        expected_space_id=plan.space_id,
        expected_admission_artifact_ref=admission_ref,
        expected_admission_artifact_digest=admission_digest,
        expected_manifest_hash=plan.manifest_hash,
        expected_eligibility_hash=plan.eligibility_hash,
        expected_golden_slice_hash=plan.golden_slice_hash,
        expected_routing_policy_hash=plan.routing_policy_hash,
        expected_schema_hash=plan.schema_hash,
        expected_template_lock_hash=plan.template_lock_hash,
        expected_structured_dispatch_hash=plan.structured_dispatch_hash,
        expected_model_plan_hash=plan.model_plan_hash,
        expected_deployment_roles_hash=plan.deployment_roles_hash,
        expected_resource_caps_hash=plan.resource_caps_hash,
        expected_rights_hash=plan.rights_hash,
        expected_provenance_hash=plan.provenance_hash,
        expected_clean_integration_sha=plan.clean_integration_sha,
    )


def _artifact_payloads(plan: G3BoundedAdmissionPlanV1) -> dict[str, list[bytes]]:
    from insurance_harness.run_admission import evaluator

    refs = {
        (ref.contract, ref.artifact_ref, ref.sha256, ref.bytes): ref
        for group in (
            plan.eligibility_lock.input_artifacts,
            plan.provenance_lock.artifacts,
            plan.rights_lock.artifacts,
        )
        for ref in group
    }
    result: dict[str, list[bytes]] = {}
    for ref in refs.values():
        result.setdefault(ref.contract, []).append(evaluator._read_g3_artifact(ref))
    return result


def _one_artifact[ModelT: BaseModel](
    artifacts: dict[str, list[bytes]], contract: str, model: type[ModelT]
) -> ModelT:
    values = artifacts.get(contract, [])
    if len(values) != 1:
        raise ValueError(f"expected one {contract} artifact")
    if (
        contract == "g3-native-page-projections.830.v1"
        and model is G3NativePageProjectionSetV1
    ):
        return cast(ModelT, _parse_native_page_projection_bytes(values[0]))
    return model.model_validate(_unique_json_bytes(values[0]))


@dataclass(frozen=True)
class G3StageExecutionContext:
    """Typed immutable stage inputs parsed once and shared by every call path."""

    plan: G3BoundedAdmissionPlanV1
    context_by_call: Mapping[str, bytes]
    context_index: bytes
    preview: bytes | None
    corpus: BatchCorpusV1 | None = None
    policy: BatchResolutionPolicyV1 | None = None
    catalog: SchemaPackCatalogV1 | None = None
    existing: ExistingEntitySnapshotV1 | None = None
    native_pages: G3NativePageProjectionSetV1 | None = None
    compile_request: BatchConceptCompileRequest830G3V1 | None = None
    model_compile_result: CompileResult | None = None
    final_compile_result: CompileResult | None = None
    projection_reuse: Any = None
    reused_outputs: tuple[CompileOutput, ...] = ()
    review_reuse: Any = None
    reused_reviews: tuple[tuple[str, ReviewOutput], ...] = ()
    recovery_windows: tuple[dict[str, object], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "context_by_call", MappingProxyType(dict(self.context_by_call)))


def _parse_g3_stage_artifacts(
    plan: G3BoundedAdmissionPlanV1, artifacts: dict[str, list[bytes]]
) -> G3StageExecutionContext:
    common = {"plan": plan, "context_by_call": {}, "context_index": b"", "preview": None}
    if plan.stage == "C_CLASSIFY":
        return G3StageExecutionContext(
            **common,
            corpus=_one_artifact(artifacts, "batch-corpus.830.g3.v1", BatchCorpusV1),
            policy=_one_artifact(
                artifacts, "batch-resolution-policy.830.g3.v1", BatchResolutionPolicyV1
            ),
            catalog=_one_artifact(
                artifacts, "schema-pack-catalog.830.g3.v1", SchemaPackCatalogV1
            ),
            existing=_one_artifact(
                artifacts, "existing-entities.830.g3.v1", ExistingEntitySnapshotV1
            ),
            native_pages=_one_artifact(
                artifacts,
                "g3-native-page-projections.830.v1",
                G3NativePageProjectionSetV1,
            ),
        )
    request = _one_artifact(
        artifacts,
        "batch-concept-compile-request.830.g3.v1",
        BatchConceptCompileRequest830G3V1,
    )
    if plan.stage == "D_COMPILE":
        reuse_rows = artifacts.get("g3-d-projection-reuse.830.v1", [])
        if reuse_rows:
            from .g3_d_projection_reuse import validate_d_projection_reuse
            from .g3_d_recovery_execution import (
                derive_recovery_windows,
                normalize_projection_reuse,
            )

            manifests = normalize_projection_reuse(
                tuple(_unique_json_bytes(raw) for raw in reuse_rows)
            )
            windows = derive_recovery_windows(request, manifests)
            verified = tuple(validate_d_projection_reuse(row, current_request=request)
                             for row in manifests)
            return G3StageExecutionContext(
                **common, compile_request=request, projection_reuse=manifests,
                reused_outputs=tuple(output for result in verified for output in result.outputs),
                recovery_windows=windows,
            )
        return G3StageExecutionContext(**common, compile_request=request)
    model_result = _one_artifact(artifacts, "g3-d-model-compile-result.830.v1", CompileResult)
    final_result = _one_artifact(artifacts, "g3-d-final-compile-result.830.v1", CompileResult)
    review_rows = artifacts.get("g3-d-review-result-reuse.830.v1", [])
    if review_rows:
        from .g3_d_review_reuse import (
            derive_remaining_review_windows,
            normalize_review_reuse,
            validate_review_result_reuse,
        )
        manifests = normalize_review_reuse(tuple(_unique_json_bytes(raw) for raw in review_rows))
        if not plan.request_manifest.calls:
            raise ValueError("review reuse requires an explicitly bounded remaining call")
        verified = validate_review_result_reuse(
            manifests, current_request=request, current_output=final_result.output,
            current_identity=plan.request_manifest.calls[0].identity,
        )
        return G3StageExecutionContext(
            **common, compile_request=request, model_compile_result=model_result,
            final_compile_result=final_result, review_reuse=manifests,
            reused_reviews=tuple(verified.items()),
            recovery_windows=derive_remaining_review_windows(
                request, final_result.output, manifests,
            ),
        )
    return G3StageExecutionContext(
        **common, compile_request=request, model_compile_result=model_result,
        final_compile_result=final_result,
    )



def _c_source_locators(block_ref: str, text: str) -> tuple[G3SemanticLocatorV1, ...]:
    """Offer exact bounded source spans; the model never needs to count offsets."""

    locators: list[G3SemanticLocatorV1] = []

    def emit(start: int, end: int) -> None:
        quote = text[start:end]
        if quote.strip():
            locators.append(G3SemanticLocatorV1(
                block_ref=block_ref, start=start, end=end, quote=quote,
            ))

    offset = 0
    pending_start: int | None = None
    pending_end = 0
    for line in text.splitlines(keepends=True):
        end = offset + len(line)
        if len(line) > 256:
            if pending_start is not None:
                emit(pending_start, pending_end)
                pending_start = None
            start = offset
            while start < end:
                piece_end = min(start + 256, end)
                emit(start, piece_end)
                if piece_end == end:
                    break
                start = piece_end - 64
        else:
            if pending_start is not None and end - pending_start > 256:
                emit(pending_start, pending_end)
                pending_start = None
            if pending_start is None:
                pending_start = offset
            pending_end = end
        offset = end
    if pending_start is not None:
        emit(pending_start, pending_end)
    return tuple(locators)


def _c_locator_ref(locator: G3SemanticLocatorV1) -> str:
    return "loc_" + hashlib.sha256(canonical_json(locator.model_dump(mode="json"))).hexdigest()


def _c_eligible_source_locators(
    page: G3NativePageProjectionV1, source: SourceBlock,
) -> tuple[G3SemanticLocatorV1, ...]:
    if (page.revision_id, page.block_id, page.page_number) != (
        source.revision_id, source.block_id, source.page_number,
    ):
        raise ValueError("reference native/source identity mismatch")
    eligible: list[G3SemanticLocatorV1] = []
    covered: set[int] = set()

    def admit(locator: G3SemanticLocatorV1) -> None:
        if not locator.quote.strip():
            return
        try:
            _native_page_evidence(locator=locator, page=page, source=source)
        except ValueError:
            return
        eligible.append(locator)
        covered.update(range(locator.start, locator.end))

    for locator in _c_source_locators(page.block_ref, source.text):
        admit(locator)
    for match in re.finditer(r"[^\r\n]+", source.text):
        physical = match.group()
        start = match.start() + len(physical) - len(physical.lstrip())
        end = start + len(physical.strip())
        while start < end:
            stop = min(start + 256, end)
            if not all(index in covered for index in range(start, stop)):
                admit(G3SemanticLocatorV1(
                    block_ref=page.block_ref, start=start, end=stop,
                    quote=source.text[start:stop],
                ))
            if stop == end:
                break
            start = stop - 64
    return tuple(sorted(eligible, key=lambda locator: (locator.start, locator.end)))


def _c_prompt_block(
    block_ref: str, text: str, *, use_locator_refs: bool = False,
    native_page: G3NativePageProjectionV1 | None = None,
    source: SourceBlock | None = None,
) -> dict[str, object]:
    if use_locator_refs:
        if (
            native_page is None or source is None
            or native_page.block_ref != block_ref or source.text != text
        ):
            raise ValueError("reference prompt requires exact native/source binding")
        locators = _c_eligible_source_locators(native_page, source)
        return {
            "block_ref": block_ref, "text": text,
            "evidence_locator_refs": [
                {"locator_ref": _c_locator_ref(locator), "quote": locator.quote}
                for locator in locators
            ],
        }
    return {"block_ref": block_ref, "text": text, "evidence_locators": [
        locator.model_dump(mode="json") for locator in _c_source_locators(block_ref, text)
    ]}


def _resolve_c_source_references(
    raw: bytes, *, corpus: BatchCorpusV1,
    native_pages: tuple[G3NativePageProjectionV1, ...],
    requested_material_ids: tuple[str, ...],
) -> G3SemanticResponseV1:
    response = G3SemanticReferenceResponseV1.model_validate(_unique_json_bytes(raw))
    if canonical_json(response.model_dump(mode="json", round_trip=True)) != raw:
        raise ValueError("reference response typed wire mismatch")
    entries = {entry.material_id: entry for entry in corpus.entries}
    if len({page.block_ref for page in native_pages}) != len(native_pages):
        raise ValueError("opaque block refs must be unique")
    locators: dict[tuple[str, str], G3SemanticLocatorV1] = {}
    for page in native_pages:
        if page.material_id not in requested_material_ids:
            continue
        entry = entries.get(page.material_id)
        if entry is None:
            raise ValueError("reference page material outside corpus")
        sources = {(block.revision_id, block.block_id): block for block in entry.blocks}
        source = sources.get((page.revision_id, page.block_id))
        if source is None or source.page_number != page.page_number:
            raise ValueError("reference page source binding mismatch")
        for locator in _c_eligible_source_locators(page, source):
            key = (page.material_id, _c_locator_ref(locator))
            if key in locators:
                raise ValueError("duplicate source locator reference")
            locators[key] = locator
    materials = []
    for material in response.materials:
        if material.material_id not in requested_material_ids:
            raise ValueError("reference material outside call")
        evidence = []
        for row in material.evidence:
            resolved_locator = locators.get((material.material_id, row.locator_ref))
            if resolved_locator is None:
                raise ValueError("unknown or foreign source locator reference")
            evidence.append(G3SemanticEvidenceV1(
                **row.model_dump(exclude={"locator_ref"}), locator=resolved_locator,
            ))
        entities = []
        for entity in material.entities:
            labels = tuple(
                label.model_copy(update={"evidence_refs": tuple(sorted(label.evidence_refs))})
                for label in sorted(entity.labels, key=lambda row: row.taxonomy_label)
            )
            entities.append(entity.model_copy(update={
                "identity_evidence_refs": tuple(sorted(entity.identity_evidence_refs)),
                "labels": labels,
            }))
        materials.append(G3SemanticMaterialV1(
            **material.model_dump(exclude={"evidence", "entities", "material_role_evidence_refs"}),
            evidence=tuple(sorted(evidence, key=lambda row: row.evidence_ref)),
            entities=tuple(sorted(entities, key=lambda row: row.entity_ref)),
            material_role_evidence_refs=tuple(sorted(material.material_role_evidence_refs)),
        ))
    return G3SemanticResponseV1(
        contract="g3-batch-resolution-semantic-response.local.v1",
        materials=tuple(sorted(materials, key=lambda row: row.material_id)),
    )


def _render_g3_stage_contexts(
    *,
    plan: G3BoundedAdmissionPlanV1,
    parent: G3ModelProcessingAuthorizationV1,
    artifacts: dict[str, list[bytes]],
    template_bytes: bytes,
    _prepared: G3StageExecutionContext | None = None,
) -> tuple[dict[str, bytes], bytes, bytes | None]:
    """Rebuild model-visible user contexts and their stage witnesses from typed inputs."""

    try:
        template_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("stage template is not UTF-8") from None
    prepared = _prepared or _parse_g3_stage_artifacts(plan, artifacts)
    if prepared.plan is not plan and prepared.plan != plan:
        raise ValueError("prepared stage context plan mismatch")
    context_by_call: dict[str, bytes] = {}
    preview_bytes: bytes | None = None
    if plan.stage == "C_CLASSIFY":
        corpus = prepared.corpus
        policy = prepared.policy
        catalog = prepared.catalog
        existing = prepared.existing
        page_set = prepared.native_pages
        if any(value is None for value in (corpus, policy, catalog, existing, page_set)):
            raise ValueError("prepared C stage inputs are incomplete")
        assert corpus is not None
        assert policy is not None
        assert catalog is not None
        assert existing is not None
        assert page_set is not None
        page_bytes = artifacts["g3-native-page-projections.830.v1"][0]
        if (
            plan.dispatch_lock.opaque_block_map_sha256
            != hashlib.sha256(page_bytes).hexdigest()
        ):
            raise ValueError("opaque block map hash mismatch")
        entries = {entry.material_id: entry for entry in corpus.entries}
        parent_materials = {item.material_id: item for item in parent.c_materials}
        if set(entries) != set(parent_materials):
            raise ValueError("parent material set mismatch")
        pages_by_material: dict[str, list[G3NativePageProjectionV1]] = {
            material_id: [] for material_id in entries
        }
        seen_block_refs: set[str] = set()
        seen_source_blocks: set[tuple[str, str, str]] = set()
        blocks_by_material: dict[str, dict[tuple[str, str], SourceBlock]] = {
            material_id: {(block.revision_id, block.block_id): block for block in entry.blocks}
            for material_id, entry in entries.items()
        }
        for page in page_set.pages:
            source_key = (page.material_id, page.revision_id, page.block_id)
            if page.block_ref in seen_block_refs or source_key in seen_source_blocks:
                raise ValueError("duplicate opaque block mapping")
            seen_block_refs.add(page.block_ref)
            seen_source_blocks.add(source_key)
            source = blocks_by_material.get(page.material_id, {}).get(
                (page.revision_id, page.block_id)
            )
            if source is None or page.page_number != source.page_number:
                raise ValueError("foreign opaque block mapping")
            pages_by_material[page.material_id].append(page)
        for material_id, entry in entries.items():
            material_pages = sorted(pages_by_material[material_id], key=lambda item: item.block_ref)
            if not material_pages:
                raise ValueError("material has no opaque block mapping")
            parent_row = parent_materials[material_id]
            actual_bindings = (
                entry.entry_sha256,
                hashlib.sha256(canonical_json(entry.receipt.model_dump(mode="json"))).hexdigest(),
                hashlib.sha256(
                    canonical_json([block.model_dump(mode="json") for block in entry.blocks])
                ).hexdigest(),
                hashlib.sha256(
                    canonical_json(
                        {
                            "contract": "g3-native-page-projections.830.v1",
                            "pages": [page.model_dump(mode="json") for page in material_pages],
                        }
                    )
                ).hexdigest(),
            )
            if actual_bindings != (
                parent_row.corpus_entry_sha256,
                parent_row.source_revision_receipt_sha256,
                parent_row.w1_sha256,
                parent_row.native_page_map_sha256,
            ):
                raise ValueError("parent material binding mismatch")
        call_materials: list[str] = []
        roles = sorted({role for rule in policy.rules for role in rule.material_roles})
        labels = sorted(
            {
                label
                for catalog_entry in catalog.entries
                for label in catalog_entry.pack.applicable_classifications
            }
        )
        for call in plan.request_manifest.calls:
            call_materials.extend(call.material_ids)
            material_rows: list[dict[str, object]] = []
            for material_id in sorted(call.material_ids):
                if material_id not in entries:
                    raise ValueError("call selects a foreign material")
                blocks: list[dict[str, object]] = []
                for page in sorted(pages_by_material[material_id], key=lambda item: item.block_ref):
                    source = blocks_by_material[material_id][(page.revision_id, page.block_id)]
                    blocks.append(_c_prompt_block(
                        page.block_ref, source.text,
                        use_locator_refs=_is_g3_gemini_identity(call.identity),
                        native_page=page, source=source,
                    ))
                material_rows.append({"material_id": material_id, "blocks": blocks})
            context_by_call[call.call_id] = canonical_json(
                {
                    "contract": "g3-c-classify-prompt-context.830.v1",
                    "window_id": call.window_id,
                    "materials": material_rows,
                    "allowed_material_roles": roles,
                    "allowed_taxonomy_labels": labels,
                    "existing_entities": [
                        entity.model_dump(mode="json") for entity in existing.entities
                    ],
                    "response_schema": _c_response_schema(call.identity),
                }
            )
        if tuple(sorted(call_materials)) != tuple(entries) or len(call_materials) != len(
            set(call_materials)
        ):
            raise ValueError("C call materials are not an exact partition")
    elif plan.stage == "D_COMPILE":
        request = prepared.compile_request
        if request is None:
            raise ValueError("prepared D compile input is incomplete")
        calls = plan.request_manifest.calls
        if (
            calls
            and _is_g3_gemini_d_identity("D_COMPILE", calls[0].identity)
            and calls[0].window_id is not None
        ):
            from .g3_d_recovery_execution import render_recovery_context

            recovering = prepared.projection_reuse is not None
            windows = (prepared.recovery_windows if recovering
                       else derive_gemini_d_compile_windows(request))
            render = (render_recovery_context if recovering
                      else render_gemini_d_compile_window_context)
            if tuple((call.window_id, call.material_ids) for call in calls) != tuple(
                (cast(str, row["window_id"]), cast(tuple[str, ...], row["material_ids"]))
                for row in windows
            ):
                raise ValueError("Gemini D calls are not the exact active window partition")
            for call, window in zip(calls, windows, strict=True):
                context_by_call[call.call_id] = batch_json_bytes_830_g3(
                    render(call.identity, request, window)
                )
        else:
            if len(calls) != 1:
                raise ValueError("legacy D compile requires one call")
            call = calls[0]
            context_by_call[call.call_id] = batch_json_bytes_830_g3(
                render_g3_d_prompt_context("D_COMPILE", call.identity, request)
            )
    else:
        request = prepared.compile_request
        model_result = prepared.model_compile_result
        final_result = prepared.final_compile_result
        if request is None or model_result is None or final_result is None:
            raise ValueError("prepared D review inputs are incomplete")
        expected_output = compose_batch_output(request, model_result)
        if final_result.output != expected_output:
            raise ValueError("D review final output carry closure mismatch")
        calls = plan.request_manifest.calls
        if (
            calls
            and _is_g3_gemini_d_identity("D_REVIEW", calls[0].identity)
            and calls[0].window_id is not None
        ):
            windows = (prepared.recovery_windows if prepared.review_reuse is not None
                       else derive_gemini_d_review_windows(request, final_result.output))
            if tuple((call.window_id, call.material_ids) for call in calls) != tuple(
                (cast(str, row["window_id"]), cast(tuple[str, ...], row["material_ids"]))
                for row in windows
            ):
                raise ValueError("Gemini D review calls are not the exact active window partition")
            for call, window in zip(calls, windows, strict=True):
                context_by_call[call.call_id] = batch_json_bytes_830_g3(
                    render_gemini_d_review_window_context(
                        call.identity, request, final_result.output, window
                    )
                )
        else:
            if len(calls) != 1:
                raise ValueError("legacy D review requires one call")
            call = calls[0]
            context_by_call[call.call_id] = batch_json_bytes_830_g3(
                render_g3_d_prompt_context(
                    "D_REVIEW", call.identity, request, final_result.output
                )
            )
    for call in plan.request_manifest.calls:
        context = context_by_call.get(call.call_id)
        if context is None or hashlib.sha256(context).hexdigest() != call.input_context_sha256:
            raise ValueError("rendered call context hash mismatch")
    index_bytes = canonical_json(
        {
            "contract": "g3-stage-render-contexts.830.v1",
            "stage": plan.stage,
            "calls": [
                {
                    "call_id": call.call_id,
                    "ordinal": call.ordinal,
                    "input_context_sha256": call.input_context_sha256,
                }
                for call in plan.request_manifest.calls
            ],
        }
    )
    if hashlib.sha256(index_bytes).hexdigest() != plan.dispatch_lock.input_context_sha256:
        raise ValueError("stage context index hash mismatch")
    if plan.stage == "C_CLASSIFY":
        system = template_bytes.decode("utf-8")
        preview_bytes = canonical_json(
            {
                "contract": "g3-c-prompt-preview.830.v1",
                "calls": [
                    {
                        "call_id": call.call_id,
                        "ordinal": call.ordinal,
                        "window_id": call.window_id,
                        "material_ids": list(call.material_ids),
                        "input_context_sha256": call.input_context_sha256,
                        "request_body_sha256": call.request_body_sha256,
                        "system": system,
                        "user": context_by_call[call.call_id].decode("utf-8"),
                    }
                    for call in plan.request_manifest.calls
                ],
            }
        )
        if hashlib.sha256(preview_bytes).hexdigest() != parent.c_prompt_preview_sha256:
            raise ValueError("C prompt preview hash mismatch")
    return context_by_call, index_bytes, preview_bytes


def prepare_g3_stage_execution_context(
    *,
    plan: G3BoundedAdmissionPlanV1,
    parent: G3ModelProcessingAuthorizationV1,
    artifacts: dict[str, list[bytes]],
    template_bytes: bytes,
) -> G3StageExecutionContext:
    """Parse and verify all immutable stage inputs once before any call is resumed or sent."""

    prepared = _parse_g3_stage_artifacts(plan, artifacts)
    contexts, index, preview = _render_g3_stage_contexts(
        plan=plan,
        parent=parent,
        artifacts=artifacts,
        template_bytes=template_bytes,
        _prepared=prepared,
    )
    return G3StageExecutionContext(
        plan=plan,
        context_by_call=contexts,
        context_index=index,
        preview=preview,
        corpus=prepared.corpus,
        policy=prepared.policy,
        catalog=prepared.catalog,
        existing=prepared.existing,
        native_pages=prepared.native_pages,
        compile_request=prepared.compile_request,
        model_compile_result=prepared.model_compile_result,
        final_compile_result=prepared.final_compile_result,
        projection_reuse=prepared.projection_reuse,
        reused_outputs=prepared.reused_outputs,
        review_reuse=prepared.review_reuse,
        reused_reviews=prepared.reused_reviews,
        recovery_windows=prepared.recovery_windows,
    )


def _g3_chain_directory(plan: G3BoundedAdmissionPlanV1) -> Path:
    from insurance_harness.model_policy import g3_bounded_gateway as gateway

    return Path(gateway.G3_LEDGER_ROOT) / "chains" / plan.chain_manifest_hash


def _secure_stage_results_directory(plan: G3BoundedAdmissionPlanV1) -> Path:
    chain_dir = _g3_chain_directory(plan)
    result_root = chain_dir / "stage-results"
    result_dir = result_root / plan.stage
    for directory in (chain_dir, result_root, result_dir):
        directory.mkdir(parents=False, exist_ok=True, mode=0o700)
        info = directory.stat(follow_symlinks=False)
        if (
            directory.is_symlink()
            or not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o700
            or info.st_uid != os.geteuid()
        ):
            raise RuntimeError("invalid G3 stage-results custody")
    return result_dir


def _existing_stage_results_directory(
    plan: G3BoundedAdmissionPlanV1,
    stage: Literal["C_CLASSIFY", "D_COMPILE", "D_REVIEW"],
) -> Path:
    chain_dir = _g3_chain_directory(plan)
    directories = (chain_dir, chain_dir / "stage-results", chain_dir / "stage-results" / stage)
    for directory in directories:
        info = directory.stat(follow_symlinks=False)
        if (
            directory.is_symlink()
            or not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o700
            or info.st_uid != os.geteuid()
        ):
            raise RuntimeError("invalid G3 stage-results custody")
    return directories[-1]


def _read_secure_exact(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
        ):
            raise RuntimeError("invalid G3 result file custody")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _write_or_verify_stage_result(
    plan: G3BoundedAdmissionPlanV1, filename: str, payload: bytes
) -> Path:
    from insurance_harness.model_policy.g3_bounded_gateway import _write_exclusive

    if filename not in {
        "proposal-batch.json",
        "resolution.json",
        "model-compile-result.json",
        "final-compile-result.json",
        "review-result.json",
        "candidate.json",
        "failed-classification-quarantine.json",
    }:
        raise RuntimeError("unknown G3 result filename")
    chain_dir = _g3_chain_directory(plan)
    lock_fd = os.open(
        chain_dir / ".chain.lock",
        os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        path = _secure_stage_results_directory(plan) / filename
        try:
            _write_exclusive(path, payload)
        except FileExistsError:
            if _read_secure_exact(path) != payload:
                raise RuntimeError("G3 stage result conflict") from None
        return path
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _persist_stage_result(
    plan: G3BoundedAdmissionPlanV1, filename: str, value: BaseModel
) -> Path:
    payload = canonical_json(value.model_dump(mode="json", round_trip=True))
    return _write_or_verify_stage_result(plan, filename, payload)


def _validate_g3_prior_stage_results(
    plan: G3BoundedAdmissionPlanV1, artifacts: dict[str, list[bytes]]
) -> None:
    if plan.stage == "C_CLASSIFY":
        return
    compile_reuse_rows = artifacts.get("g3-d-compile-result-reuse.830.v1", [])
    if compile_reuse_rows:
        from .g3_d_compile_reuse import (
            G3CompileResultReuseV1,
            validate_compile_result_reuse,
        )
        if plan.stage != "D_REVIEW" or len(compile_reuse_rows) != 1:
            raise ValueError("completed compile reuse requires an explicit D review input")
        receipt = _one_artifact(
            artifacts, "g3-d-compile-result-reuse.830.v1", G3CompileResultReuseV1,
        )
        if plan.prior_terminal_receipt_sha256 != receipt.origin_terminal_sha256:
            raise ValueError("completed compile reuse prior mismatch")
        validate_compile_result_reuse(
            receipt,
            request=_one_artifact(artifacts, "batch-concept-compile-request.830.g3.v1",
                                  BatchConceptCompileRequest830G3V1),
            model_result=_one_artifact(
                artifacts, "g3-d-model-compile-result.830.v1", CompileResult,
            ),
            final_result=_one_artifact(
                artifacts, "g3-d-final-compile-result.830.v1", CompileResult,
            ),
        )
        return
    reuse_raw = (
        artifacts.get("g3-classification-reuse.830.v1", [])
        + artifacts.get("g3-classification-reuse.830.v2", [])
    )
    if reuse_raw:
        from .g3_classification_reuse import (
            parse_classification_reuse,
            validate_classification_reuse,
        )
        if plan.stage != "D_COMPILE" or len(reuse_raw) != 1:
            raise ValueError("classification reuse is only an explicit D compile input")
        reuse = parse_classification_reuse(reuse_raw[0])
        if (canonical_json(reuse.model_dump(mode="json", round_trip=True)) != reuse_raw[0]
                or plan.prior_terminal_receipt_sha256 != reuse.source_terminal_receipt_sha256):
            raise ValueError("classification reuse prior receipt mismatch")
        request = _one_artifact(
            artifacts, "batch-concept-compile-request.830.g3.v1", BatchConceptCompileRequest830G3V1
        )
        validate_classification_reuse(reuse, request=request)
        return
    prior_stage: Literal["C_CLASSIFY", "D_COMPILE"] = (
        "C_CLASSIFY" if plan.stage == "D_COMPILE" else "D_COMPILE"
    )
    chain_dir = _g3_chain_directory(plan)
    terminal_bytes = _read_secure_exact(
        chain_dir / "stage-terminals" / f"{prior_stage}.json"
    )
    prior = G3StageTerminalReceiptV1.model_validate_json(terminal_bytes)
    if (
        prior.stage != prior_stage
        or prior.chain_id != plan.chain_id
        or prior.parent_authorization_digest != plan.parent_authorization_digest
        or prior.status != "SUCCESS"
        or prior.receipt_sha256 != plan.prior_terminal_receipt_sha256
        or prior.receipt_sha256
        != canonical_g3_hash("g3-stage-terminal-receipt.830.v1", prior, "receipt_sha256")
    ):
        raise RuntimeError("invalid G3 prior stage terminal")
    result_dir = _existing_stage_results_directory(plan, prior_stage)
    if prior_stage == "C_CLASSIFY":
        proposal_bytes = _read_secure_exact(result_dir / "proposal-batch.json")
        resolution_bytes = _read_secure_exact(result_dir / "resolution.json")
        proposal = ProposalBatchV1.model_validate_json(proposal_bytes)
        resolution = BatchEntityResolutionV1.model_validate_json(resolution_bytes)
        request = _one_artifact(
            artifacts,
            "batch-concept-compile-request.830.g3.v1",
            BatchConceptCompileRequest830G3V1,
        )
        if (
            proposal_bytes
            != canonical_json(proposal.model_dump(mode="json", round_trip=True))
            or resolution_bytes
            != canonical_json(resolution.model_dump(mode="json", round_trip=True))
            or request.resolution != resolution
            or resolution.proposals_sha256 != proposal.proposals_sha256
            or prior.stage_output_sha256 != resolution.batch_sha256
        ):
            raise RuntimeError("C stage result closure mismatch")
        return
    model_bytes = _read_secure_exact(result_dir / "model-compile-result.json")
    final_bytes = _read_secure_exact(result_dir / "final-compile-result.json")
    model_result = CompileResult.model_validate_json(model_bytes)
    final_result = CompileResult.model_validate_json(final_bytes)
    signed_model = _one_artifact(
        artifacts, "g3-d-model-compile-result.830.v1", CompileResult
    )
    signed_final = _one_artifact(
        artifacts, "g3-d-final-compile-result.830.v1", CompileResult
    )
    request = _one_artifact(
        artifacts,
        "batch-concept-compile-request.830.g3.v1",
        BatchConceptCompileRequest830G3V1,
    )
    if (
        model_bytes != canonical_json(model_result.model_dump(mode="json", round_trip=True))
        or final_bytes != canonical_json(final_result.model_dump(mode="json", round_trip=True))
        or signed_model != model_result
        or signed_final != final_result
        or final_result.output != compose_batch_output(request, model_result)
        or prior.stage_output_sha256 != compile_output_hash_g3(final_result.output)
    ):
        raise RuntimeError("D compile stage result closure mismatch")


def _call_terminal(
    *,
    plan: G3BoundedAdmissionPlanV1,
    call: G3CallPlanV1,
    admission_digest: str,
    verified_digest: str,
    call_dir: str,
    projection_sha256: str,
    reservation_capability: Any,
) -> G3CallTerminalReceiptV1:
    from insurance_harness.model_policy import ModelIdentity, PolicyReceipt
    from insurance_harness.model_policy.g3_bounded_gateway import (
        _is_g3_gemini_identity,
        _parse_g3_gemini_provider_response,
        consume_g3_response_audit,
    )
    from insurance_harness.run_admission.g3_models import (
        G3CallPlanV1,
        G3CallReservationV1,
        G3StartedReceiptV1,
    )

    current_call = G3CallPlanV1.model_validate(call.model_dump())
    directory = Path(call_dir)
    reservation = G3CallReservationV1.model_validate_json(
        (directory / "reservation.json").read_bytes()
    )
    started = G3StartedReceiptV1.model_validate_json((directory / "started.json").read_bytes())
    policy_bytes = (directory / "policy-receipt.json").read_bytes()
    PolicyReceipt.model_validate_json(policy_bytes)
    response_bytes = (directory / "response-body.private.json").read_bytes()
    semantic_bytes = (directory / "semantic-content.private.json").read_bytes()
    response_meta, usage = consume_g3_response_audit(reservation_capability)
    if usage is None:
        raise RuntimeError("successful provider usage is missing")
    if _is_g3_gemini_identity(current_call.identity):
        _content, derived_semantic, derived_usage = (
            _parse_g3_gemini_provider_response(current_call.identity, response_bytes)
        )
        if derived_semantic != semantic_bytes or derived_usage != usage:
            raise RuntimeError("Gemini response audit closure mismatch")
    ended = datetime.now(UTC)
    duration_ms = max(0, int((ended - started.started_at).total_seconds() * 1000))
    cost = G3CostAuditV1(
        status="NOT_MEASURED",
        currency=None,
        amount_minor_units=None,
        rate_card_sha256=None,
        provider_cost_receipt_sha256=None,
        reason_code="NO_FROZEN_RATE_CARD",
    )
    provisional = G3CallTerminalReceiptV1(
        contract="g3-call-terminal-receipt.830.v1",
        chain_id=plan.chain_id,
        stage=plan.stage,
        call_id=current_call.call_id,
        ordinal=current_call.ordinal,
        run_id=plan.run_id,
        run_revision=plan.run_revision,
        admission_artifact_digest=admission_digest,
        verified_binding_digest=verified_digest,
        call_reservation_receipt_sha256=reservation.receipt_sha256,
        policy_receipt_sha256=hashlib.sha256(policy_bytes).hexdigest(),
        identity=ModelIdentity.model_validate(current_call.identity.model_dump()),
        endpoint_origin=current_call.endpoint_origin,
        endpoint_path=current_call.endpoint_path,
        request_body_sha256=current_call.request_body_sha256,
        request_bytes=current_call.request_bytes,
        response_meta=response_meta,
        response_body_sha256=hashlib.sha256(response_bytes).hexdigest(),
        response_bytes=len(response_bytes),
        semantic_content_sha256=hashlib.sha256(semantic_bytes).hexdigest(),
        projection_sha256=projection_sha256,
        provider_usage=usage,
        cost_audit=cost,
        started_receipt_sha256=started.receipt_sha256,
        started_at=started.started_at,
        ended_at=ended,
        duration_ms=duration_ms,
        status="SUCCESS",
        reason_code="SUCCESS",
        retry_count=0,
        receipt_sha256="0" * 64,
    )
    terminal = provisional.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-call-terminal-receipt.830.v1", provisional, "receipt_sha256"
            )
        }
    )
    from insurance_harness.model_policy.g3_bounded_gateway import _write_exclusive

    _write_exclusive(
        directory / "call-terminal.json",
        canonical_json(terminal.model_dump(mode="json", round_trip=True)),
    )
    return terminal


def _failed_call_terminal(
    *,
    plan: G3BoundedAdmissionPlanV1,
    call: G3CallPlanV1,
    admission_digest: str,
    verified_digest: str,
    call_dir: str,
    reservation_capability: Any,
) -> G3CallTerminalReceiptV1 | None:
    from insurance_harness.model_policy import PolicyReceipt
    from insurance_harness.model_policy.g3_bounded_gateway import (
        _write_exclusive,
        consume_g3_response_audit,
    )
    from insurance_harness.run_admission.g3_models import (
        G3CallReservationV1,
        G3StartedReceiptV1,
    )

    directory = Path(call_dir)
    if not (directory / "started.json").exists():
        return None
    reservation = G3CallReservationV1.model_validate_json(
        (directory / "reservation.json").read_bytes()
    )
    started = G3StartedReceiptV1.model_validate_json((directory / "started.json").read_bytes())
    policy_bytes = (directory / "policy-receipt.json").read_bytes()
    PolicyReceipt.model_validate_json(policy_bytes)
    response_path = directory / "response-body.private.json"
    response_bytes = response_path.read_bytes() if response_path.exists() else None
    response_meta = None
    usage = None
    try:
        response_meta, usage = consume_g3_response_audit(reservation_capability)
    except Exception:
        response_meta = None
        usage = None
    ended = datetime.now(UTC)
    cost = G3CostAuditV1(
        status="NOT_MEASURED",
        currency=None,
        amount_minor_units=None,
        rate_card_sha256=None,
        provider_cost_receipt_sha256=None,
        reason_code="NO_FROZEN_RATE_CARD",
    )
    provisional = G3CallTerminalReceiptV1(
        contract="g3-call-terminal-receipt.830.v1",
        chain_id=plan.chain_id,
        stage=plan.stage,
        call_id=call.call_id,
        ordinal=call.ordinal,
        run_id=plan.run_id,
        run_revision=plan.run_revision,
        admission_artifact_digest=admission_digest,
        verified_binding_digest=verified_digest,
        call_reservation_receipt_sha256=reservation.receipt_sha256,
        policy_receipt_sha256=hashlib.sha256(policy_bytes).hexdigest(),
        identity=call.identity,
        endpoint_origin=call.endpoint_origin,
        endpoint_path=call.endpoint_path,
        request_body_sha256=call.request_body_sha256,
        request_bytes=call.request_bytes,
        response_meta=response_meta,
        response_body_sha256=(
            None if response_bytes is None else hashlib.sha256(response_bytes).hexdigest()
        ),
        response_bytes=None if response_bytes is None else len(response_bytes),
        semantic_content_sha256=None,
        projection_sha256=None,
        provider_usage=usage,
        cost_audit=cost,
        started_receipt_sha256=started.receipt_sha256,
        started_at=started.started_at,
        ended_at=ended,
        duration_ms=max(0, int((ended - started.started_at).total_seconds() * 1000)),
        status="OUTCOME_UNKNOWN" if response_bytes is None else "FAILED",
        reason_code=(
            "PROVIDER_OUTCOME_UNKNOWN" if response_bytes is None else "INVALID_PROVIDER_RESPONSE"
        ),
        retry_count=0,
        receipt_sha256="0" * 64,
    )
    terminal = provisional.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-call-terminal-receipt.830.v1", provisional, "receipt_sha256"
            )
        }
    )
    _write_exclusive(
        directory / "call-terminal.json",
        canonical_json(terminal.model_dump(mode="json", round_trip=True)),
    )
    return terminal


def _failed_stage_terminal(
    *,
    plan: G3BoundedAdmissionPlanV1,
    admission_digest: str,
    call_dir: str,
    completed_call_terminals: tuple[G3CallTerminalReceiptV1, ...],
    failed_call_terminal: G3CallTerminalReceiptV1 | None,
    calls_reserved: int,
    started_at: datetime,
) -> G3StageTerminalReceiptV1:
    from insurance_harness.model_policy.g3_bounded_gateway import _write_exclusive
    from insurance_harness.run_admission.g3_models import G3StageLedgerBindingV1

    chain_dir = Path(call_dir).parents[1]
    binding = G3StageLedgerBindingV1.model_validate_json(
        (chain_dir / "stage-bindings" / f"{plan.stage}.json").read_bytes()
    )
    terminals = completed_call_terminals + (
        () if failed_call_terminal is None else (failed_call_terminal,)
    )
    rows = tuple(
        (terminal.ordinal, terminal.receipt_sha256, terminal.cost_audit) for terminal in terminals
    )
    _aggregation, aggregation_hash = canonical_cost_aggregation(plan.stage, rows)
    stage_cost = G3CostAuditV1(
        status="NOT_MEASURED",
        currency=None,
        amount_minor_units=None,
        rate_card_sha256=None,
        provider_cost_receipt_sha256=aggregation_hash,
        reason_code="NO_FROZEN_RATE_CARD",
    )
    provisional = G3StageTerminalReceiptV1(
        contract="g3-stage-terminal-receipt.830.v1",
        chain_id=plan.chain_id,
        stage=plan.stage,
        parent_authorization_digest=plan.parent_authorization_digest,
        admission_artifact_digest=admission_digest,
        prior_terminal_receipt_sha256=plan.prior_terminal_receipt_sha256,
        stage_binding_receipt_sha256=binding.receipt_sha256,
        call_terminal_sha256s=tuple(terminal.receipt_sha256 for terminal in terminals),
        stage_output_sha256=None,
        disposition_counts=None,
        coverage_gap_codes=(),
        calls_consumed=calls_reserved,
        provider_usage_total=G3UsageTotalsV1(
            successful_usage_records=sum(
                terminal.provider_usage is not None for terminal in terminals
            ),
            prompt_tokens=sum(
                terminal.provider_usage.prompt_tokens
                for terminal in terminals
                if terminal.provider_usage is not None
            ),
            completion_tokens=sum(
                terminal.provider_usage.completion_tokens
                for terminal in terminals
                if terminal.provider_usage is not None
            ),
            total_tokens=sum(
                terminal.provider_usage.total_tokens
                for terminal in terminals
                if terminal.provider_usage is not None
            ),
        ),
        cost_audit=stage_cost,
        started_at=started_at,
        ended_at=datetime.now(UTC),
        status=(
            "OUTCOME_UNKNOWN"
            if failed_call_terminal is not None and failed_call_terminal.status == "OUTCOME_UNKNOWN"
            else "FAILED"
        ),
        receipt_sha256="0" * 64,
    )
    terminal = provisional.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-stage-terminal-receipt.830.v1", provisional, "receipt_sha256"
            )
        }
    )
    _write_exclusive(
        chain_dir / "stage-terminals" / f"{plan.stage}.json",
        canonical_json(terminal.model_dump(mode="json", round_trip=True)),
    )
    return terminal


def _finalize_gemini_d_compile_windows(
    *,
    request: BatchConceptCompileRequest830G3V1,
    outputs: Sequence[CompileOutput],
    plan: G3BoundedAdmissionPlanV1,
    admission_digest: str,
    call_dir: str,
    call_terminals: tuple[G3CallTerminalReceiptV1, ...],
    started_at: datetime,
    prepared: G3StageExecutionContext | None = None,
) -> CompileResult:
    """Aggregate successful window calls or seal the stage as failed."""

    try:
        implementation = "g3-gemini-d-window-aggregate.830.v1"
        if prepared is not None and prepared.projection_reuse is not None:
            from .g3_field_task_recovery import aggregate_g3_recovered_compile_outputs

            aggregate = aggregate_g3_recovered_compile_outputs(
                request, (*prepared.reused_outputs, *outputs),
            )
            implementation = "g3-gemini-d-recovery-aggregate.830.v1"
            raw = batch_json_bytes_830_g3(aggregate).decode()
        else:
            aggregate = aggregate_gemini_d_compile_window_outputs(request, outputs)
            raw = batch_json_bytes_830_g3(aggregate).decode()
        return record_model_compile(
            request,
            aggregate,
            run_id=plan.run_id,
            implementation=implementation,
            raw=raw,
        )
    except Exception:
        _failed_stage_terminal(
            plan=plan,
            admission_digest=admission_digest,
            call_dir=call_dir,
            completed_call_terminals=call_terminals,
            failed_call_terminal=None,
            calls_reserved=len(call_terminals),
            started_at=started_at,
        )
        raise


def _finalize_gemini_d_review_windows(
    *,
    request: BatchConceptCompileRequest830G3V1,
    model_compile_result: CompileResult,
    final_compile_result: CompileResult,
    outputs: Sequence[ReviewOutput],
    plan: G3BoundedAdmissionPlanV1,
    admission_digest: str,
    call_dir: str,
    call_terminals: tuple[G3CallTerminalReceiptV1, ...],
    started_at: datetime,
    prepared: G3StageExecutionContext | None = None,
) -> tuple[ReviewResult, BatchConceptCandidateBundle830G3V1]:
    """Aggregate successful review windows or seal the stage as failed."""

    try:
        if prepared is not None and prepared.review_reuse is not None:
            from .g3_d_review_reuse import aggregate_reused_review_outputs
            aggregate = aggregate_reused_review_outputs(
                request, final_compile_result.output, new_outputs=outputs,
                reused=dict(prepared.reused_reviews),
            )
        else:
            aggregate = aggregate_gemini_d_review_window_outputs(
                request, final_compile_result.output, outputs
            )
        raw = batch_json_bytes_830_g3(aggregate)
        context_hash = _compile_sha256(
            "batch-concept-review-context.830.g3.v1",
            review_context_g3(request, final_compile_result.output),
        )
        review_result = build_d_review_result(
            raw=raw,
            output=aggregate,
            run_id=plan.run_id,
            context_hash=context_hash,
        )
        review_result = review_result.model_copy(
            update={
                "execution": review_result.execution.model_copy(
                    update={
                        "implementation": "g3-gemini-d-review-window-aggregate.830.v1"
                    }
                )
            }
        )
        admission_state = _g3_human_admission(
            request, final_compile_result.output, aggregate
        )
        candidate = assemble_candidate_bundle(
            request,
            model_compile_result,
            final_compile_result,
            review_result,
            admission_state,
        )
        return review_result, candidate
    except Exception:
        _failed_stage_terminal(
            plan=plan,
            admission_digest=admission_digest,
            call_dir=call_dir,
            completed_call_terminals=call_terminals,
            failed_call_terminal=None,
            calls_reserved=len(call_terminals),
            started_at=started_at,
        )
        raise


async def _run_bounded_call_tasks(calls, execute, *, worker_limit: int):
    """Execute independent calls with bounded concurrency and stable result order."""
    import asyncio
    if worker_limit not in (1, 2):
        raise ValueError("G3 worker limit must be 1 or 2")
    semaphore = asyncio.Semaphore(worker_limit)
    gateway_unavailable = False
    async def one(call):
        nonlocal gateway_unavailable
        async with semaphore:
            if gateway_unavailable:
                # Never enter execute: no reservation, started receipt or retry.
                return None
            try:
                result = await execute(call)
                if (
                    isinstance(result, G3CallTerminalReceiptV1)
                    and result.status == "FAILED"
                    and result.response_meta is not None
                    and result.response_meta.http_status in (429, 503)
                ):
                    # This is shared transport exhaustion, not a field failure.
                    # In-flight tasks finish; a later explicit run starts fresh.
                    gateway_unavailable = True
                return result
            except Exception as error:
                return error
    return tuple(await asyncio.gather(*(one(call) for call in calls)))


def _failed_classification_quarantines(
    *,
    plan: G3BoundedAdmissionPlanV1,
    admission_digest: str,
    corpus: BatchCorpusV1,
    policy: BatchResolutionPolicyV1,
    failed_terminals: tuple[G3CallTerminalReceiptV1, ...],
):
    from .g3_failed_classification_quarantine import (
        build_verified_failed_classification_quarantines,
    )

    return build_verified_failed_classification_quarantines(
        plan=plan,
        admission_digest=admission_digest,
        corpus=corpus,
        policy=policy,
        failed_terminals=failed_terminals,
    )


def _persist_failed_classification_quarantines(
    *,
    plan: G3BoundedAdmissionPlanV1,
    admission_digest: str,
    corpus: BatchCorpusV1,
    policy: BatchResolutionPolicyV1,
    failed_terminals: tuple[G3CallTerminalReceiptV1, ...],
):
    quarantine = _failed_classification_quarantines(
        plan=plan,
        admission_digest=admission_digest,
        corpus=corpus,
        policy=policy,
        failed_terminals=failed_terminals,
    )
    _persist_stage_result(
        plan,
        "failed-classification-quarantine.json",
        quarantine,
    )
    return quarantine


async def run_stage(admission: str) -> G3StageTerminalReceiptV1:
    """Verify, reserve and execute every call once, then persist the stage terminal."""

    from insurance_harness.model_policy import ModelCallFacts, ModelCallRequest
    from insurance_harness.model_policy.g3_bounded_gateway import (
        _reopen_completed_g3_call,
        _reservation_snapshot,
        build_g3_bounded_model_client,
        prepare_g3_reserved_call,
        reserve_g3_call,
    )
    from insurance_harness.run_admission import evaluator

    admission_path = Path(admission)
    admission_digest_from_path = admission_path.parent.name
    envelope_bytes = evaluator._read_external_artifact(
        admission, admission_digest_from_path
    )
    envelope_value = _unique_json_bytes(envelope_bytes)
    admission_digest = hashlib.sha256(envelope_bytes).hexdigest()
    if admission_path != (
        evaluator._ADMISSION_STORE_ROOT / "sha256" / admission_digest / "approval-envelope.json"
    ):
        raise ValueError("stage admission path is not content addressed")
    envelope = G3BoundedApprovalEnvelopeV1.model_validate(envelope_value)
    if envelope_bytes != canonical_json(
        envelope.model_dump(mode="json", round_trip=True)
    ):
        raise ValueError("stage admission is not canonical")
    plan = envelope.payload
    request = _request_for_plan(plan, admission, admission_digest)
    verified = evaluator.select_canonical_admission_verifier(
        plan.purpose, plan.run_schema_version
    ).verify(request)
    content = evaluator._verified_g3_current_content(verified)
    bodies = content
    artifacts: dict[str, list[bytes]] = {}
    for artifact in content.artifacts:
        values = artifacts.setdefault(artifact.contract, [])
        if artifact.payload not in values:
            values.append(artifact.payload)
    prepared = content.stage_context
    if not isinstance(prepared, G3StageExecutionContext) or prepared.plan != plan:
        raise ValueError("verified G3 typed context is absent or mismatched")
    template_bytes = content.template_bytes
    corpus = prepared.corpus
    policy = prepared.policy
    catalog = prepared.catalog
    compile_request_model = prepared.compile_request
    model_compile_result = prepared.model_compile_result
    final_compile_result = prepared.final_compile_result
    partial = plan.chain_manifest.failure_policy.policy_version == "g3-chain-failure-policy.830.v2"
    failures: list[tuple[G3CallTerminalReceiptV1 | None, str, Exception]] = []
    call_terminals: list[G3CallTerminalReceiptV1] = []
    c_proposals: list[MaterialProposalV1] = []
    model_receipts: list[ModelReceiptBindingV1] = []
    compile_result: CompileResult | None = None
    compile_window_by_ordinal: dict[int, CompileOutput] = {}
    review_window_by_ordinal: dict[int, ReviewOutput] = {}
    review_result: ReviewResult | None = None
    candidate: BatchConceptCandidateBundle830G3V1 | None = None
    stage_started = datetime.now(UTC)
    last_call_dir: str | None = None
    async def execute_call(call):
        nonlocal last_call_dir, compile_result, review_result, candidate
        from insurance_harness.model_policy.g3_bounded_gateway import (
            inspect_g3_call_state,
            resume_g3_unstarted_call,
            seal_g3_unknown_call,
        )
        state = inspect_g3_call_state(
            plan=plan, call=call, admission_artifact_digest=admission_digest,
        ) if partial else None
        if state is not None and state.status in {"FAILED", "OUTCOME_UNKNOWN"}:
            if state.terminal is None:
                # An unacknowledged request is never sent again. Only a timed-out
                # request may be sealed; active requests retain their worker slot.
                terminal = seal_g3_unknown_call(
                    plan=plan, call=call, admission_artifact_digest=admission_digest,
                )
            else:
                terminal = state.terminal
            failures.append((terminal, "", RuntimeError("existing call " + state.status)))
            return
        reopened = _reopen_completed_g3_call(
            plan=plan,
            call=call,
            admission_artifact_digest=admission_digest,
        )
        if reopened is not None:
            terminal, semantic, policy_bytes, _call_dir = reopened
            last_call_dir = _call_dir
            if plan.stage == "C_CLASSIFY":
                corpus = prepared.corpus
                policy = prepared.policy
                catalog = prepared.catalog
                page_set = prepared.native_pages
                assert isinstance(corpus, BatchCorpusV1)
                assert isinstance(policy, BatchResolutionPolicyV1)
                assert isinstance(catalog, SchemaPackCatalogV1)
                assert isinstance(page_set, G3NativePageProjectionSetV1)
                roles = tuple(
                    sorted({role for rule in policy.rules for role in rule.material_roles})
                )
                labels = tuple(
                    sorted(
                        {
                            label
                            for entry in catalog.entries
                            for label in entry.pack.applicable_classifications
                        }
                    )
                )
                proposals = assemble_c_semantic_response(
                    raw=semantic,
                    corpus=corpus,
                    requested_material_ids=call.material_ids,
                    native_pages=page_set.pages,
                    allowed_material_roles=roles,
                    allowed_taxonomy_labels=labels,
                    model_request_sha256=call.request_body_sha256,
                    use_locator_refs=_is_g3_gemini_identity(call.identity),
                )
                if terminal.projection_sha256 != _batch_sha256(
                    "g3-c-call-projection.830.v1", {"proposals": proposals}
                ):
                    raise RuntimeError("reopened C projection mismatch")
                c_proposals.extend(proposals)
                policy_receipt = __import__(
                    "insurance_harness.model_policy", fromlist=["PolicyReceipt"]
                ).PolicyReceipt.model_validate_json(policy_bytes)
                entry_index = {entry.material_id: entry for entry in corpus.entries}
                material_bindings = tuple(
                    MaterialBindingV1(
                        material_id=material_id,
                        corpus_entry_sha256=entry_index[material_id].entry_sha256,
                    )
                    for material_id in call.material_ids
                )
                model_receipts.append(
                    ModelReceiptBindingV1(
                        policy_receipt=policy_receipt,
                        material_bindings=material_bindings,
                        request_sha256=call.request_body_sha256,
                        input_sha256=_batch_sha256(
                            "batch-classifier-input.830.g3.v1",
                            {
                                "corpus_sha256": corpus.corpus_sha256,
                                "material_bindings": [
                                    item.model_dump(mode="json") for item in material_bindings
                                ],
                            },
                        ),
                        raw_output_sha256=hashlib.sha256(semantic).hexdigest(),
                        execution_receipt_sha256=terminal.receipt_sha256,
                    )
                )
            elif plan.stage == "D_COMPILE":
                compile_request_model = prepared.compile_request
                assert isinstance(compile_request_model, BatchConceptCompileRequest830G3V1)
                if (
                    _is_g3_gemini_d_identity("D_COMPILE", call.identity)
                    and call.window_id is not None
                ):
                    output = _prepared_gemini_d_window_output(
                        raw=semantic, request=compile_request_model, call=call, prepared=prepared,
                    )
                    assert call.window_id is not None
                    if terminal.projection_sha256 != _gemini_d_window_projection_hash(
                        call.window_id, output
                    ):
                        raise RuntimeError("reopened D compile window projection mismatch")
                    compile_window_by_ordinal[call.ordinal] = output
                else:
                    compile_result = _build_d_compile_result_from_semantic(
                        raw=semantic,
                        request=compile_request_model,
                        identity=call.identity,
                        run_id=plan.run_id,
                    )
                    if terminal.projection_sha256 != _compile_sha256(
                        "g3-d-compile-projection.830.v1", compile_result
                    ):
                        raise RuntimeError("reopened D compile projection mismatch")
            else:
                compile_request_model = prepared.compile_request
                model_compile_result = prepared.model_compile_result
                final_compile_result = prepared.final_compile_result
                assert isinstance(compile_request_model, BatchConceptCompileRequest830G3V1)
                assert isinstance(model_compile_result, CompileResult)
                assert isinstance(final_compile_result, CompileResult)
                if (
                    _is_g3_gemini_d_identity("D_REVIEW", call.identity)
                    and call.window_id is not None
                ):
                    review_output = _gemini_d_review_window_output(
                        raw=semantic,
                        request=compile_request_model,
                        output=final_compile_result.output,
                        call=call,
                    )
                    if terminal.projection_sha256 != _gemini_d_review_window_projection_hash(
                        call.window_id, review_output
                    ):
                        raise RuntimeError("reopened D review window projection mismatch")
                    review_window_by_ordinal[call.ordinal] = review_output
                else:
                    review_output, review_result = _build_d_review_result_from_semantic(
                        raw=semantic,
                        request=compile_request_model,
                        output=final_compile_result.output,
                        identity=call.identity,
                        run_id=plan.run_id,
                    )
                    if (
                        review_output.request_hash
                        != compile_request_hash_g3(compile_request_model.base_request)
                        or review_output.output_hash
                        != compile_output_hash_g3(final_compile_result.output)
                        or review_output.decision == "REJECT"
                    ):
                        raise ValueError("review output is stale or rejected")
                    admission_state = _g3_human_admission(
                        compile_request_model,
                        final_compile_result.output,
                        review_output,
                    )
                    candidate = assemble_candidate_bundle(
                        compile_request_model,
                        model_compile_result,
                        final_compile_result,
                        review_result,
                        admission_state,
                    )
                    if terminal.projection_sha256 != candidate.candidate_hash:
                        raise RuntimeError("reopened D review projection mismatch")
            call_terminals.append(terminal)
            return
        reserve = (
            resume_g3_unstarted_call
            if state is not None and state.status == "RESERVED_NOT_SENT"
            else reserve_g3_call
        )
        capability = reserve(
            plan=plan,
            call=call,
            admission_artifact_digest=admission_digest,
        )
        route = prepare_g3_reserved_call(
            plan=plan,
            call=call,
            admission_artifact_digest=admission_digest,
            verified_binding_digest=verified.receipt.verified_binding_digest,
            reservation_capability=capability,
        )
        snapshot = _reservation_snapshot(capability)
        if snapshot is None:
            raise RuntimeError("reservation authority was lost")
        call_dir = str(snapshot[2])
        last_call_dir = call_dir
        body = bodies[call.request_body_sha256]
        client = build_g3_bounded_model_client(
            verified_admission=verified,
            transport_identity=call.identity,
            route_config=route,
            reservation_capability=capability,
        )
        facts = ModelCallFacts(
            job_id=call.call_id,
            stage=plan.stage,
            attempt=1,
            input_digest=call.input_context_sha256,
            content_digest=hashlib.sha256(body).hexdigest(),
            rendered_prompt_digest=hashlib.sha256(template_bytes).hexdigest(),
            purpose=plan.purpose,
            run_schema_version=plan.run_schema_version,
            space_id=plan.space_id,
            run_id=plan.run_id,
            run_revision=plan.run_revision,
            admission_artifact_digest=admission_digest,
            template_hash=plan.template_lock.approved_template_hash,
            model_plan_hash=plan.model_plan_hash,
            identity=call.identity,
            role=call.identity.role,
        )
        try:
            content = await client.call(
                verified,
                facts,
                ModelCallRequest(content=body, rendered_prompt=template_bytes),
            )
            semantic = content.encode()
            if plan.stage == "C_CLASSIFY":
                corpus = prepared.corpus
                policy = prepared.policy
                catalog = prepared.catalog
                page_set = prepared.native_pages
                assert isinstance(corpus, BatchCorpusV1)
                assert isinstance(policy, BatchResolutionPolicyV1)
                assert isinstance(catalog, SchemaPackCatalogV1)
                assert isinstance(page_set, G3NativePageProjectionSetV1)
                roles = tuple(
                    sorted({role for rule in policy.rules for role in rule.material_roles})
                )
                labels = tuple(
                    sorted(
                        {
                            label
                            for entry in catalog.entries
                            for label in entry.pack.applicable_classifications
                        }
                    )
                )
                proposals = assemble_c_semantic_response(
                    raw=semantic,
                    corpus=corpus,
                    requested_material_ids=call.material_ids,
                    native_pages=page_set.pages,
                    allowed_material_roles=roles,
                    allowed_taxonomy_labels=labels,
                    model_request_sha256=call.request_body_sha256,
                    use_locator_refs=_is_g3_gemini_identity(call.identity),
                )
                projection_hash = _batch_sha256(
                    "g3-c-call-projection.830.v1", {"proposals": proposals}
                )
                c_proposals.extend(proposals)
            elif plan.stage == "D_COMPILE":
                compile_request_model = prepared.compile_request
                assert isinstance(compile_request_model, BatchConceptCompileRequest830G3V1)
                if (
                    _is_g3_gemini_d_identity("D_COMPILE", call.identity)
                    and call.window_id is not None
                ):
                    output = _prepared_gemini_d_window_output(
                        raw=semantic, request=compile_request_model, call=call, prepared=prepared,
                    )
                    assert call.window_id is not None
                    projection_hash = _gemini_d_window_projection_hash(
                        call.window_id, output
                    )
                    compile_window_by_ordinal[call.ordinal] = output
                else:
                    compile_result = _build_d_compile_result_from_semantic(
                        raw=semantic,
                        request=compile_request_model,
                        identity=call.identity,
                        run_id=plan.run_id,
                    )
                    projection_hash = _compile_sha256(
                        "g3-d-compile-projection.830.v1", compile_result
                    )
            else:
                compile_request_model = prepared.compile_request
                model_compile_result = prepared.model_compile_result
                final_compile_result = prepared.final_compile_result
                if (
                    _is_g3_gemini_d_identity("D_REVIEW", call.identity)
                    and call.window_id is not None
                ):
                    review_output = _gemini_d_review_window_output(
                        raw=semantic,
                        request=compile_request_model,
                        output=final_compile_result.output,
                        call=call,
                    )
                    projection_hash = _gemini_d_review_window_projection_hash(
                        call.window_id, review_output
                    )
                    review_window_by_ordinal[call.ordinal] = review_output
                else:
                    review_output, review_result = _build_d_review_result_from_semantic(
                        raw=semantic,
                        request=compile_request_model,
                        output=final_compile_result.output,
                        identity=call.identity,
                        run_id=plan.run_id,
                    )
                    if (
                        review_output.request_hash
                        != compile_request_hash_g3(compile_request_model.base_request)
                        or review_output.output_hash
                        != compile_output_hash_g3(final_compile_result.output)
                        or review_output.decision == "REJECT"
                    ):
                        raise ValueError("review output is stale or rejected")
                    admission_state = _g3_human_admission(
                        compile_request_model,
                        final_compile_result.output,
                        review_output,
                    )
                    candidate = assemble_candidate_bundle(
                        compile_request_model,
                        model_compile_result,
                        final_compile_result,
                        review_result,
                        admission_state,
                    )
                    projection_hash = candidate.candidate_hash
        except Exception as error:
            failed_call = _failed_call_terminal(
                plan=plan,
                call=call,
                admission_digest=admission_digest,
                verified_digest=verified.receipt.verified_binding_digest,
                call_dir=call_dir,
                reservation_capability=capability,
            )
            if partial:
                failures.append((failed_call, call_dir, error))
                return failed_call
            _failed_stage_terminal(
                plan=plan,
                admission_digest=admission_digest,
                call_dir=call_dir,
                completed_call_terminals=tuple(call_terminals),
                failed_call_terminal=failed_call,
                calls_reserved=len(call_terminals) + 1,
                started_at=stage_started,
            )
            if (
                plan.stage == "C_CLASSIFY"
                and failed_call is not None
                and failed_call.status == "FAILED"
                and failed_call.reason_code == "INVALID_PROVIDER_RESPONSE"
                and failed_call.response_meta is not None
                and failed_call.response_meta.http_status == 200
                and failed_call.response_meta.content_type.split(";", 1)[0].strip().lower()
                == "application/json"
            ):
                _persist_failed_classification_quarantines(
                    plan=plan,
                    admission_digest=admission_digest,
                    corpus=corpus,
                    policy=policy,
                    failed_terminals=(failed_call,),
                )
            raise
        terminal = _call_terminal(
            plan=plan,
            call=call,
            admission_digest=admission_digest,
            verified_digest=verified.receipt.verified_binding_digest,
            call_dir=call_dir,
            projection_sha256=projection_hash,
            reservation_capability=capability,
        )
        call_terminals.append(terminal)
        if plan.stage == "C_CLASSIFY":
            policy_receipt = __import__(
                "insurance_harness.model_policy", fromlist=["PolicyReceipt"]
            ).PolicyReceipt.model_validate_json(
                (Path(call_dir) / "policy-receipt.json").read_bytes()
            )
            entry_index = {entry.material_id: entry for entry in corpus.entries}
            material_bindings = tuple(
                MaterialBindingV1(
                    material_id=material_id,
                    corpus_entry_sha256=entry_index[material_id].entry_sha256,
                )
                for material_id in call.material_ids
            )
            model_receipts.append(
                ModelReceiptBindingV1(
                    policy_receipt=policy_receipt,
                    material_bindings=material_bindings,
                    request_sha256=call.request_body_sha256,
                    input_sha256=_batch_sha256(
                        "batch-classifier-input.830.g3.v1",
                        {
                            "corpus_sha256": corpus.corpus_sha256,
                            "material_bindings": [
                                item.model_dump(mode="json") for item in material_bindings
                            ],
                        },
                    ),
                    raw_output_sha256=hashlib.sha256(semantic).hexdigest(),
                    execution_receipt_sha256=terminal.receipt_sha256,
                )
            )
    if partial:
        outcomes = await _run_bounded_call_tasks(
            plan.request_manifest.calls, execute_call,
            worker_limit=plan.stage_caps.worker_limit,
        )
        unrecorded = [item for item in outcomes if isinstance(item, Exception)]
        if unrecorded:
            # Reservation/auth/state errors cannot become business unknown values.
            raise unrecorded[0]
    else:
        for call in plan.request_manifest.calls:
            await execute_call(call)
    call_terminals.sort(key=lambda item: item.ordinal)
    compile_window_outputs = [
        compile_window_by_ordinal[key] for key in sorted(compile_window_by_ordinal)
    ]
    review_window_outputs = [
        review_window_by_ordinal[key] for key in sorted(review_window_by_ordinal)
    ]
    if failures:
        # Successful leaves stay immutable and reusable; no partial candidate is
        # emitted and other independent calls have already had their opportunity.
        if plan.stage == "C_CLASSIFY":
            failed_classifications = tuple(
                terminal
                for terminal, _, _ in failures
                if terminal is not None
                and terminal.status == "FAILED"
                and terminal.reason_code == "INVALID_PROVIDER_RESPONSE"
                and terminal.response_meta is not None
                and terminal.response_meta.http_status == 200
                and terminal.response_meta.content_type.split(";", 1)[0].strip().lower()
                == "application/json"
            )
            if failed_classifications:
                _persist_failed_classification_quarantines(
                    plan=plan,
                    admission_digest=admission_digest,
                    corpus=corpus,
                    policy=policy,
                    failed_terminals=failed_classifications,
                )
        raise RuntimeError(
            f"{len(failures)} local G3 call(s) need correction; successful calls retained"
        ) from failures[0][2]
    disposition_counts = None
    coverage_gaps: tuple[str, ...] = ()
    if plan.stage == "C_CLASSIFY":
        proposals_payload: dict[str, object] = {
            "contract": "batch-identity-proposals.830.g3.v1",
            "corpus_sha256": corpus.corpus_sha256,
            "model_receipts": sorted(model_receipts, key=lambda item: item.request_sha256),
            "proposals": sorted(c_proposals, key=lambda item: item.material_id),
        }
        proposal_batch = ProposalBatchV1.model_validate(
            {
                **proposals_payload,
                "proposals_sha256": _batch_sha256(
                    "batch-identity-proposals.830.g3.v1", proposals_payload
                ),
            }
        )
        existing = prepared.existing
        assert isinstance(existing, ExistingEntitySnapshotV1)
        resolution = resolve_batch(
            catalog=catalog,
            corpus=corpus,
            proposals=proposal_batch,
            existing_entities=existing,
            policy=policy,
            compiler_version="batch-entity-resolution-compiler.830.g3.v2",
        )
        _persist_stage_result(plan, "proposal-batch.json", proposal_batch)
        _persist_stage_result(plan, "resolution.json", resolution)
        stage_output_sha = resolution.batch_sha256
        disposition_counts = G3DispositionCountsV1.model_validate(
            resolution.disposition_counts.model_dump()
        )
        from insurance_harness.run_admission.g3_models import g3_coverage_gap_codes

        coverage_gaps = g3_coverage_gap_codes(disposition_counts)
    elif plan.stage == "D_COMPILE":
        if compile_window_outputs:
            if last_call_dir is None:
                raise RuntimeError("D window calls have no ledger directory")
            compile_result = _finalize_gemini_d_compile_windows(
                request=compile_request_model,
                outputs=compile_window_outputs,
                plan=plan,
                admission_digest=admission_digest,
                call_dir=last_call_dir,
                call_terminals=tuple(call_terminals),
                started_at=stage_started,
                prepared=prepared,
            )
        assert compile_result is not None
        composed = compose_batch_output(compile_request_model, compile_result)
        final_compile_result = record_composed_output(
            compile_request_model,
            compile_result,
            composed,
            run_id=f"{plan.run_id}-carry",
        )
        _persist_stage_result(plan, "model-compile-result.json", compile_result)
        _persist_stage_result(plan, "final-compile-result.json", final_compile_result)
        stage_output_sha = compile_output_hash_g3(final_compile_result.output)
    else:
        if review_window_outputs:
            if last_call_dir is None:
                raise RuntimeError("D review window calls have no ledger directory")
            review_result, candidate = _finalize_gemini_d_review_windows(
                request=compile_request_model,
                model_compile_result=model_compile_result,
                final_compile_result=final_compile_result,
                outputs=review_window_outputs,
                plan=plan,
                admission_digest=admission_digest,
                call_dir=last_call_dir,
                call_terminals=tuple(call_terminals),
                started_at=stage_started,
                prepared=prepared,
            )
        assert review_result is not None
        assert candidate is not None
        _persist_stage_result(plan, "review-result.json", review_result)
        _persist_stage_result(plan, "candidate.json", candidate)
        stage_output_sha = candidate.candidate_hash
    usages = tuple(item.provider_usage for item in call_terminals)
    usage_total = G3UsageTotalsV1(
        successful_usage_records=len(usages),
        prompt_tokens=sum(item.prompt_tokens for item in usages if item is not None),
        completion_tokens=sum(item.completion_tokens for item in usages if item is not None),
        total_tokens=sum(item.total_tokens for item in usages if item is not None),
    )
    aggregation_bytes, aggregation_hash = canonical_cost_aggregation(
        plan.stage,
        tuple((item.ordinal, item.receipt_sha256, item.cost_audit) for item in call_terminals),
    )
    del aggregation_bytes
    stage_cost = G3CostAuditV1(
        status="NOT_MEASURED",
        currency=None,
        amount_minor_units=None,
        rate_card_sha256=None,
        provider_cost_receipt_sha256=aggregation_hash,
        reason_code="NO_FROZEN_RATE_CARD",
    )
    stage_binding = __import__(
        "insurance_harness.run_admission.g3_models", fromlist=["G3StageLedgerBindingV1"]
    ).G3StageLedgerBindingV1.model_validate_json(
        (_g3_chain_directory(plan) / "stage-bindings" / f"{plan.stage}.json").read_bytes()
    )
    provisional_stage = G3StageTerminalReceiptV1(
        contract="g3-stage-terminal-receipt.830.v1",
        chain_id=plan.chain_id,
        stage=plan.stage,
        parent_authorization_digest=plan.parent_authorization_digest,
        admission_artifact_digest=admission_digest,
        prior_terminal_receipt_sha256=plan.prior_terminal_receipt_sha256,
        stage_binding_receipt_sha256=stage_binding.receipt_sha256,
        call_terminal_sha256s=tuple(item.receipt_sha256 for item in call_terminals),
        stage_output_sha256=stage_output_sha,
        disposition_counts=disposition_counts,
        coverage_gap_codes=coverage_gaps,
        calls_consumed=len(call_terminals),
        provider_usage_total=usage_total,
        cost_audit=stage_cost,
        started_at=stage_started,
        ended_at=datetime.now(UTC),
        status="SUCCESS",
        receipt_sha256="0" * 64,
    )
    terminal_stage = provisional_stage.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-stage-terminal-receipt.830.v1",
                provisional_stage,
                "receipt_sha256",
            )
        }
    )
    from insurance_harness.model_policy.g3_bounded_gateway import _write_exclusive

    _write_exclusive(
        _g3_chain_directory(plan) / "stage-terminals" / f"{plan.stage}.json",
        canonical_json(terminal_stage.model_dump(mode="json", round_trip=True)),
    )
    return terminal_stage


def _store_ref(value: str) -> str:
    if not value.startswith("/var/lib/insurancekb/run-admission/sha256/"):
        raise argparse.ArgumentTypeError("reference must use the fixed admission store")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="g3-bounded-model-execution")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-stage")
    prepare.add_argument("--parent-authorization", type=_store_ref, required=True)
    prepare.add_argument("--stage", choices=("C_CLASSIFY", "D_COMPILE", "D_REVIEW"), required=True)
    prepare.add_argument("--stage-input", type=_store_ref, required=True)
    run = commands.add_parser("run-stage")
    run.add_argument("--admission", type=_store_ref, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the closed prepare or execution operation using fixed custody roots."""

    arguments = build_parser().parse_args(argv)
    if arguments.command == "prepare-stage":
        path = prepare_stage(
            parent_authorization=arguments.parent_authorization,
            stage=arguments.stage,
            stage_input=arguments.stage_input,
        )
        print(path)
        return 0
    import asyncio

    terminal = asyncio.run(run_stage(arguments.admission))
    print(canonical_json(terminal.model_dump(mode="json")).decode())
    return 0


if __name__ == "__main__":
    # The admission verifier imports the canonical module to create typed
    # contexts. Execute its main so CLI runs use the same class identities.
    from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
        main as canonical_main,
    )

    raise SystemExit(canonical_main())


__all__ = [
    "G3NativeCharacterBoxV1",
    "G3NativePageProjectionSetV1",
    "G3NativePageProjectionV1",
    "G3SemanticResponseV1",
    "assemble_c_semantic_response",
    "build_d_review_result",
    "build_parser",
    "canonical_cost_aggregation",
    "main",
    "parse_d_compile_output",
    "parse_d_review_output",
    "prepare_stage",
    "run_stage",
]
