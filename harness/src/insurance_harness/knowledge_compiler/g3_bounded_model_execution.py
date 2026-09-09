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
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
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
    assemble_candidate_bundle,
    compile_output_hash_g3,
    compile_request_hash_g3,
    compiler_context_g3,
    compose_batch_output,
    record_composed_output,
    record_model_compile,
    review_context_g3,
)
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    _batch_sha256 as _compile_sha256,
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
    CompileOutput,
    CompileResult,
    ExecutionRecord,
    ReviewOutput,
    ReviewResult,
)
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    Evidence,
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
        response_module = (
            "harness/src/insurance_harness/knowledge_compiler/concept_compile_830_g2.py"
        )
        response_schema = CompileOutput.model_json_schema()
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


def _c_response_schema(identity: ModelIdentity | None = None) -> dict[str, object]:
    if identity is not None and _is_g3_gemini_identity(identity):
        return G3SemanticReferenceResponseV1.model_json_schema()
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
            "entities": tuple(final_entities),
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
) -> tuple[dict[str, bytes], bytes, bytes | None]:
    """Rebuild model-visible user contexts and their stage witnesses from typed inputs."""

    try:
        template_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("stage template is not UTF-8") from None
    context_by_call: dict[str, bytes] = {}
    preview_bytes: bytes | None = None
    if plan.stage == "C_CLASSIFY":
        corpus = _one_artifact(artifacts, "batch-corpus.830.g3.v1", BatchCorpusV1)
        policy = _one_artifact(
            artifacts, "batch-resolution-policy.830.g3.v1", BatchResolutionPolicyV1
        )
        catalog = _one_artifact(
            artifacts, "schema-pack-catalog.830.g3.v1", SchemaPackCatalogV1
        )
        existing = _one_artifact(
            artifacts, "existing-entities.830.g3.v1", ExistingEntitySnapshotV1
        )
        page_set = _one_artifact(
            artifacts,
            "g3-native-page-projections.830.v1",
            G3NativePageProjectionSetV1,
        )
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
        request = _one_artifact(
            artifacts,
            "batch-concept-compile-request.830.g3.v1",
            BatchConceptCompileRequest830G3V1,
        )
        call = plan.request_manifest.calls[0]
        context_by_call[call.call_id] = batch_json_bytes_830_g3(
            {
                "contract": "g3-d-compile-prompt-context.830.v1",
                "context": compiler_context_g3(request),
                "response_schema": CompileOutput.model_json_schema(),
            }
        )
    else:
        request = _one_artifact(
            artifacts,
            "batch-concept-compile-request.830.g3.v1",
            BatchConceptCompileRequest830G3V1,
        )
        model_result = _one_artifact(
            artifacts, "g3-d-model-compile-result.830.v1", CompileResult
        )
        final_result = _one_artifact(
            artifacts, "g3-d-final-compile-result.830.v1", CompileResult
        )
        expected_output = compose_batch_output(request, model_result)
        if final_result.output != expected_output:
            raise ValueError("D review final output carry closure mismatch")
        call = plan.request_manifest.calls[0]
        context_by_call[call.call_id] = batch_json_bytes_830_g3(
            {
                "contract": "g3-d-review-prompt-context.830.v1",
                "context": review_context_g3(request, final_result.output),
                "response_schema": ReviewOutput.model_json_schema(),
            }
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
    parent_bytes = evaluator._read_g3_parent(
        envelope.parent_authorization_ref.artifact_ref,
        envelope.parent_authorization_digest,
    )
    parent = G3ModelProcessingAuthorizationEnvelopeV1.model_validate(
        _unique_json_bytes(parent_bytes)
    )
    bodies = evaluator._verify_g3_current_content(plan, parent.payload)
    artifacts = _artifact_payloads(plan)
    template_bytes = evaluator._read_current_file(plan.template_lock.path)
    call_terminals: list[G3CallTerminalReceiptV1] = []
    c_proposals: list[MaterialProposalV1] = []
    model_receipts: list[ModelReceiptBindingV1] = []
    compile_result: CompileResult | None = None
    review_result: ReviewResult | None = None
    candidate: BatchConceptCandidateBundle830G3V1 | None = None
    stage_started = datetime.now(UTC)
    for call in plan.request_manifest.calls:
        reopened = _reopen_completed_g3_call(
            plan=plan,
            call=call,
            admission_artifact_digest=admission_digest,
        )
        if reopened is not None:
            terminal, semantic, policy_bytes, _call_dir = reopened
            if plan.stage == "C_CLASSIFY":
                corpus = _one_artifact(artifacts, "batch-corpus.830.g3.v1", BatchCorpusV1)
                policy = _one_artifact(
                    artifacts, "batch-resolution-policy.830.g3.v1", BatchResolutionPolicyV1
                )
                catalog = _one_artifact(
                    artifacts, "schema-pack-catalog.830.g3.v1", SchemaPackCatalogV1
                )
                page_set = _one_artifact(
                    artifacts,
                    "g3-native-page-projections.830.v1",
                    G3NativePageProjectionSetV1,
                )
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
                compile_request_model = _one_artifact(
                    artifacts,
                    "batch-concept-compile-request.830.g3.v1",
                    BatchConceptCompileRequest830G3V1,
                )
                assert isinstance(compile_request_model, BatchConceptCompileRequest830G3V1)
                compile_output = parse_d_compile_output(semantic)
                compile_result = record_model_compile(
                    compile_request_model,
                    compile_output,
                    run_id=plan.run_id,
                    implementation="g3-bounded-model-compile.830.v1",
                    raw=semantic.decode(),
                )
                if terminal.projection_sha256 != _compile_sha256(
                    "g3-d-compile-projection.830.v1", compile_result
                ):
                    raise RuntimeError("reopened D compile projection mismatch")
            else:
                compile_request_model = _one_artifact(
                    artifacts,
                    "batch-concept-compile-request.830.g3.v1",
                    BatchConceptCompileRequest830G3V1,
                )
                model_compile_result = _one_artifact(
                    artifacts, "g3-d-model-compile-result.830.v1", CompileResult
                )
                final_compile_result = _one_artifact(
                    artifacts, "g3-d-final-compile-result.830.v1", CompileResult
                )
                assert isinstance(compile_request_model, BatchConceptCompileRequest830G3V1)
                assert isinstance(model_compile_result, CompileResult)
                assert isinstance(final_compile_result, CompileResult)
                review_output = parse_d_review_output(semantic)
                expected_context = _compile_sha256(
                    "batch-concept-review-context.830.g3.v1",
                    review_context_g3(compile_request_model, final_compile_result.output),
                )
                review_result = build_d_review_result(
                    raw=semantic,
                    output=review_output,
                    run_id=plan.run_id,
                    context_hash=expected_context,
                )
                if (
                    review_output.request_hash
                    != compile_request_hash_g3(compile_request_model.base_request)
                    or review_output.output_hash
                    != compile_output_hash_g3(final_compile_result.output)
                    or review_output.decision == "REJECT"
                ):
                    raise ValueError("review output is stale or rejected")
                from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
                    _human_admission,
                )

                admission_state = _human_admission(
                    compile_request_model.base_request,
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
            continue
        capability = reserve_g3_call(
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
                corpus = _one_artifact(artifacts, "batch-corpus.830.g3.v1", BatchCorpusV1)
                policy = _one_artifact(
                    artifacts, "batch-resolution-policy.830.g3.v1", BatchResolutionPolicyV1
                )
                catalog = _one_artifact(
                    artifacts, "schema-pack-catalog.830.g3.v1", SchemaPackCatalogV1
                )
                page_set = _one_artifact(
                    artifacts,
                    "g3-native-page-projections.830.v1",
                    G3NativePageProjectionSetV1,
                )
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
                compile_request_model = _one_artifact(
                    artifacts,
                    "batch-concept-compile-request.830.g3.v1",
                    BatchConceptCompileRequest830G3V1,
                )
                assert isinstance(compile_request_model, BatchConceptCompileRequest830G3V1)
                compile_output = parse_d_compile_output(semantic)
                compile_result = record_model_compile(
                    compile_request_model,
                    compile_output,
                    run_id=plan.run_id,
                    implementation="g3-bounded-model-compile.830.v1",
                    raw=content,
                )
                projection_hash = _compile_sha256("g3-d-compile-projection.830.v1", compile_result)
            else:
                compile_request_model = _one_artifact(
                    artifacts,
                    "batch-concept-compile-request.830.g3.v1",
                    BatchConceptCompileRequest830G3V1,
                )
                model_compile_result = _one_artifact(
                    artifacts, "g3-d-model-compile-result.830.v1", CompileResult
                )
                final_compile_result = _one_artifact(
                    artifacts, "g3-d-final-compile-result.830.v1", CompileResult
                )
                review_output = parse_d_review_output(semantic)
                expected_context = _compile_sha256(
                    "batch-concept-review-context.830.g3.v1",
                    review_context_g3(compile_request_model, final_compile_result.output),
                )
                review_result = build_d_review_result(
                    raw=semantic,
                    output=review_output,
                    run_id=plan.run_id,
                    context_hash=expected_context,
                )
                if (
                    review_output.request_hash
                    != compile_request_hash_g3(compile_request_model.base_request)
                    or review_output.output_hash
                    != compile_output_hash_g3(final_compile_result.output)
                    or review_output.decision == "REJECT"
                ):
                    raise ValueError("review output is stale or rejected")
                from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
                    _human_admission,
                )

                admission_state = _human_admission(
                    compile_request_model.base_request,
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
        except Exception:
            failed_call = _failed_call_terminal(
                plan=plan,
                call=call,
                admission_digest=admission_digest,
                verified_digest=verified.receipt.verified_binding_digest,
                call_dir=call_dir,
                reservation_capability=capability,
            )
            _failed_stage_terminal(
                plan=plan,
                admission_digest=admission_digest,
                call_dir=call_dir,
                completed_call_terminals=tuple(call_terminals),
                failed_call_terminal=failed_call,
                calls_reserved=len(call_terminals) + 1,
                started_at=stage_started,
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
        existing = _one_artifact(
            artifacts, "existing-entities.830.g3.v1", ExistingEntitySnapshotV1
        )
        assert isinstance(existing, ExistingEntitySnapshotV1)
        resolution = resolve_batch(
            catalog=catalog,
            corpus=corpus,
            proposals=proposal_batch,
            existing_entities=existing,
            policy=policy,
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
    raise SystemExit(main())


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
