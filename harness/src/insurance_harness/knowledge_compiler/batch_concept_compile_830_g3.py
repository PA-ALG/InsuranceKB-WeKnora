"""Strict offline G3 batch concept DTOs and deterministic composition helpers."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal, Self, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from .batch_canonical_830_g3 import (
    batch_json_bytes_830_g3 as _canonical_json_bytes,
)
from .batch_canonical_830_g3 import (
    batch_sha256_830_g3 as _canonical_batch_sha256,
)
from .batch_canonical_830_g3 import definition_sha256_830_g3, paired_execution_sha256_830_g3
from .batch_entity_resolution_830_g3 import (
    BatchCorpusV1,
    BatchEntityResolutionV1,
    BatchResolutionPolicyV1,
    CandidateVersionAnchorV1,
    ExistingEntitySnapshotV1,
    ProposalBatchV1,
    resolve_batch,
)
from .concept_compile_830_g2 import (
    AuditDisposition,
    CompileOutput,
    CompileRequest,
    CompileResult,
    ExecutionRecord,
    HumanBatchAdmission,
    PageMember,
    ReviewResult,
    free_page_id,
    validate_disposition_semantics,
    validate_output_link_and_evidence_semantics,
    validate_output_member_semantics,
)
from .concept_free_wiki_830_g2 import (
    ConceptDefinition,
    Evidence,
    FieldAssertion,
    FreeWikiPage,
    SourceBlock,
    digest,
    verify_evidence,
)
from .schema_pack_catalog_830_g3 import SchemaPackCatalogV1, validate_catalog

Hash = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def _structured_text(value: str) -> str:
    if (
        unicodedata.normalize("NFC", value) != value
        or not value
        or value != value.strip()
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise ValueError("G3 structured text must be canonical and control-free")
    return value


Text = Annotated[StrictStr, AfterValidator(_structured_text)]


class BatchConceptCompileError(ValueError):
    """Stable failure at the G3 batch concept boundary."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


def _without_hash(model: BaseModel, field: str) -> dict[str, object]:
    if field not in type(model).model_fields:
        raise ValueError("root hash field is not declared")
    return {
        name: getattr(model, name)
        for name in type(model).model_fields
        if name != field
    }


def _batch_sha256(object_type: str, payload: object) -> str:
    return _canonical_batch_sha256(object_type, payload)


def _hashed(model_type: type[BaseModel], contract: str, hash_field: str, **payload: object) -> Any:
    return model_type.model_validate(
        {**payload, hash_field: _batch_sha256(contract, payload)}
    )


def _canonical_json(value: object) -> str:
    return _canonical_json_bytes(value).decode("utf-8")


def compile_request_hash_g3(request: CompileRequest) -> str:
    """Hash an exact G2 request while preserving G3 source-body bytes."""

    if type(request) is not CompileRequest:
        raise TypeError("G3 compile request hash requires the exact DTO")
    return _batch_sha256("compile-request.830.g2.v1", request)


def compile_output_hash_g3(output: CompileOutput) -> str:
    """Hash an exact G2 output while preserving G3 evidence-body bytes."""

    if type(output) is not CompileOutput:
        raise TypeError("G3 compile output hash requires the exact DTO")
    return _batch_sha256("compile-output.830.g2.v1", output)


def _definition_hash_g3(definition: ConceptDefinition) -> str:
    return definition_sha256_830_g3(definition)


def _concept_member_hash_g3(member: PageMember) -> str:
    if type(member) is not PageMember:
        raise TypeError("G3 concept member hash requires the exact DTO")
    return _batch_sha256("concept-member.830.g2.v1", member)


class ProfileConfirmationIdentity830G3V1(_FrozenModel):
    profile_id: Text
    profile_version: Text
    profile_sha256: Hash


class CatalogProfileConfirmationReceipt830G3V1(_FrozenModel):
    contract: Literal["830-g3-profile-user-confirmation.v1"]
    confirmed_at_recorded: Text
    decision: Literal["CONFIRMED"]
    user_reply_verbatim: Text
    actor: Text
    actor_display_name: Text | None
    confirmation_channel: Text
    review_document: Text
    review_document_sha256: Hash
    catalog_sha256: Hash
    catalog_wire_sha256: Hash
    profiles: tuple[ProfileConfirmationIdentity830G3V1, ...]
    scope: Text
    not_included: tuple[Text, ...]
    queue_owner: Text | None
    identity_metadata_note: Text

    @model_validator(mode="after")
    def canonical_profiles(self) -> Self:
        keys = tuple((item.profile_id, item.profile_version) for item in self.profiles)
        if len(keys) != len(set(keys)):
            raise ValueError("profile confirmation contains duplicate identity")
        return self


class CatalogProfileConfirmationBinding830G3V1(_FrozenModel):
    contract: Literal["catalog-profile-confirmation-binding.830.g3.v1"]
    receipt: CatalogProfileConfirmationReceipt830G3V1
    receipt_file_sha256: Hash
    receipt_semantic_sha256: Hash

    @model_validator(mode="after")
    def semantic_hash(self) -> Self:
        if self.receipt_semantic_sha256 != _batch_sha256(
            self.receipt.contract, self.receipt
        ):
            raise ValueError("PROFILE_CONFIRMATION_HASH_MISMATCH")
        return self


class BatchResolutionInputs830G3V1(_FrozenModel):
    contract: Literal["batch-resolution-inputs.830.g3.v1"]
    corpus: BatchCorpusV1
    proposals: ProposalBatchV1
    existing_entities: ExistingEntitySnapshotV1
    policy: BatchResolutionPolicyV1
    inputs_sha256: Hash

    @model_validator(mode="after")
    def content_hash(self) -> Self:
        if self.inputs_sha256 != _batch_sha256(
            self.contract, _without_hash(self, "inputs_sha256")
        ):
            raise ValueError("RESOLUTION_INPUTS_HASH_MISMATCH")
        return self


class ResolutionDecisionRef830G3V1(_FrozenModel):
    material_id: Text
    proposal_ref: Text
    decision_sha256: Hash
    classification_assignment_sha256: Hash


class BoundResolutionEvidence830G3V1(_FrozenModel):
    material_id: Text
    proposal_ref: Text
    evidence_id: Text
    purpose: Literal["issuer", "product_code", "name", "version", "classification"]
    evidence: Evidence


class EntityCompileBinding830G3V1(_FrozenModel):
    contract: Literal["entity-compile-binding.830.g3.v1"]
    entity_id: Text
    entity_version: Text
    resolution_disposition: Literal["MATCH", "CREATE"]
    resolution_refs: tuple[ResolutionDecisionRef830G3V1, ...]
    entity_key_sha256: Hash
    version_candidate_key_sha256: Hash
    candidate_id: Text | None
    entity_candidate_sha256: Hash | None
    display_name: Text
    issuer: Text
    product_code: Text
    version_label: Text
    version_anchor: CandidateVersionAnchorV1
    primary_classification: Text
    schema_pack_id: Text
    schema_version: Text
    schema_pack_sha256: Hash
    profile_id: Text
    profile_version: Text
    profile_sha256: Hash
    required_fields: tuple[Text, ...]
    source_material_ids: tuple[Text, ...]
    resolution_evidence: tuple[BoundResolutionEvidence830G3V1, ...]
    binding_sha256: Hash

    @model_validator(mode="after")
    def shape_and_hash(self) -> Self:
        refs = tuple((item.material_id, item.proposal_ref) for item in self.resolution_refs)
        evidence = tuple(
            (item.material_id, item.evidence_id) for item in self.resolution_evidence
        )
        nullable = (self.candidate_id, self.entity_candidate_sha256)
        if (
            not self.resolution_refs
            or refs != tuple(sorted(set(refs)))
            or evidence != tuple(sorted(set(evidence)))
            or self.source_material_ids != tuple(sorted(set(self.source_material_ids)))
            or len(self.required_fields) != len(set(self.required_fields))
            or (self.resolution_disposition == "MATCH" and nullable != (None, None))
            or (self.resolution_disposition == "CREATE" and any(v is None for v in nullable))
            or self.binding_sha256
            != _batch_sha256(self.contract, _without_hash(self, "binding_sha256"))
        ):
            raise ValueError("ENTITY_COMPILE_BINDING_INVALID")
        return self


class UnknownFieldKeyAlignment830G3V1(_FrozenModel):
    contract: Literal["unknown-field-key-alignment.830.g3.v1"]
    source_release_id: Text
    source_activation_epoch: Annotated[StrictInt, Field(gt=0)]
    source_candidate_sha256: Hash
    entity_id: Text
    entity_version: Text
    old_field_key: Text
    new_field_key: Text
    old_member_id: Text
    old_member_digest: Hash
    new_member_id: Text
    new_member_digest: Hash
    alignment_sha256: Hash

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if self.alignment_sha256 != _batch_sha256(
            self.contract, _without_hash(self, "alignment_sha256")
        ):
            raise ValueError("unknown field alignment hash mismatch")
        return self


class BatchConceptCompileRequest830G3V1(_FrozenModel):
    contract: Literal["batch-concept-compile-request.830.g3.v1"]
    base_request: CompileRequest
    catalog: SchemaPackCatalogV1
    catalog_wire_sha256: Hash
    profile_confirmation: CatalogProfileConfirmationBinding830G3V1
    resolution_inputs: BatchResolutionInputs830G3V1
    resolution: BatchEntityResolutionV1
    entity_bindings: tuple[EntityCompileBinding830G3V1, ...]
    unknown_field_key_alignments: tuple[UnknownFieldKeyAlignment830G3V1, ...]
    quality_status: Literal["REGISTERED_NOT_QUALITY_ADMITTED"]
    release_lane: Literal["ISOLATED_NOT_FOR_PRODUCTION"]
    request_sha256: Hash

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if self.request_sha256 != _batch_sha256(
            self.contract, _without_hash(self, "request_sha256")
        ):
            raise ValueError("BATCH_REQUEST_HASH_MISMATCH")
        _validate_request_closure(self)
        return self


class BatchConceptPageManifest830G3V1(_FrozenModel):
    contract: Literal["batch-concept-page-manifest.830.g3.v1"]
    members: tuple[PageMember, ...]
    members_sha256: Hash
    audit: tuple[AuditDisposition, ...]

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        keys = tuple((item.kind, item.member_id) for item in self.members)
        ids = tuple(item.member_id for item in self.members)
        if (
            keys != tuple(sorted(keys))
            or len(ids) != len(set(ids))
            or self.members_sha256
            != _batch_sha256(
                "batch-concept-page-members.830.g3.v1", {"members": self.members}
            )
        ):
            raise ValueError("PAGE_MANIFEST_MISMATCH")
        return self


class DirectoryField830G3V1(_FrozenModel):
    field_key: Text
    short_title: StrictStr
    member_id: Text


class DirectorySection830G3V1(_FrozenModel):
    section_key: Text
    display_name: StrictStr
    fields: tuple[DirectoryField830G3V1, ...]


class EntityDirectoryEntry830G3V1(_FrozenModel):
    contract: Literal["entity-directory-entry.830.g3.v1"]
    entity_id: Text
    entity_version: Text
    display_name: Text
    issuer: Text
    product_code: Text
    primary_classification: Text
    schema_pack_id: Text
    schema_version: Text
    schema_pack_sha256: Hash
    schema_pack_display_name: StrictStr
    profile_id: Text
    profile_version: Text
    profile_sha256: Hash
    quality_status: Literal["REGISTERED_NOT_QUALITY_ADMITTED"]
    release_lane: Literal["ISOLATED_NOT_FOR_PRODUCTION"]
    sections: tuple[DirectorySection830G3V1, ...]


class BatchConceptCandidateBundle830G3V1(_FrozenModel):
    contract: Literal["batch-concept-candidate-bundle.830.g3.v1"]
    request: BatchConceptCompileRequest830G3V1
    model_compile_result: CompileResult
    compile_result: CompileResult
    review_result: ReviewResult
    page_manifest: BatchConceptPageManifest830G3V1
    admission: HumanBatchAdmission
    candidate_hash: Hash

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        validate_candidate_bundle(self)
        return self


def validate_unknown_field_key_alignments(
    request: CompileRequest,
    output: CompileOutput,
    rows: tuple[dict[str, object], ...] | tuple[UnknownFieldKeyAlignment830G3V1, ...],
) -> tuple[UnknownFieldKeyAlignment830G3V1, ...]:
    """Validate frozen unknown-only lineage against exact old and aligned fields."""

    try:
        exact_request = CompileRequest.model_validate(request)
        exact_output = CompileOutput.model_validate(output)
        exact_rows = tuple(UnknownFieldKeyAlignment830G3V1.model_validate(row) for row in rows)
    except (TypeError, ValueError):
        raise BatchConceptCompileError("BASE_UNKNOWN_KEY_MIGRATION_REQUIRED") from None
    if tuple(row.entity_id for row in exact_rows) != tuple(
        sorted({row.entity_id for row in exact_rows})
    ) or tuple(row.alignment_sha256 for row in exact_rows) != _ALIGNMENT_HASHES:
        raise BatchConceptCompileError("BASE_UNKNOWN_KEY_MIGRATION_REQUIRED")
    old_fields = {(item.entity_id, item.field_key): item for item in exact_request.existing_fields}
    new_fields = {(item.entity_id, item.field_key): item for item in exact_output.fields}
    if len(old_fields) != len(exact_request.existing_fields) or len(new_fields) != len(
        exact_output.fields
    ):
        raise BatchConceptCompileError("BASE_UNKNOWN_KEY_MIGRATION_REQUIRED")
    for row in exact_rows:
        if (
            row.source_release_id != exact_request.base_release_id
            or row.source_activation_epoch != exact_request.base_activation_epoch
            or row.source_candidate_sha256 != _BASE_CANDIDATE
            or row.entity_version != exact_request.entity_versions.get(row.entity_id)
        ):
            raise BatchConceptCompileError("BASE_UNKNOWN_KEY_MIGRATION_REQUIRED")
        old = old_fields.get((row.entity_id, row.old_field_key))
        new = new_fields.get((row.entity_id, row.new_field_key))
        if old is None or new is None or row.old_member_id != old.assertion_id:
            raise BatchConceptCompileError("BASE_UNKNOWN_KEY_MIGRATION_REQUIRED")
        if row.new_member_id != new.assertion_id:
            raise BatchConceptCompileError("BASE_UNKNOWN_KEY_MIGRATION_REQUIRED")
        old_member = PageMember(
            kind="field_assertion",
            member_id=old.assertion_id,
            owner_id=old.entity_id,
            title=old.field_key,
            content=_field_content(old),
            payload=old.model_dump(mode="json"),
        )
        if row.old_member_digest != _concept_member_hash_g3(old_member):
            raise BatchConceptCompileError("BASE_UNKNOWN_KEY_MIGRATION_REQUIRED")
        eligible = (
            old.attempted
            and old.state == "unknown"
            and old.value is None
            and not old.evidence
            and not old.conditions
            and not old.exceptions
            and not old.concept_ids
            and old.valid_time == ""
            and old.unknown_reason is not None
        )
        old_payload = old.model_dump(mode="json")
        expected_payload = {**old_payload, "field_key": row.new_field_key}
        if not eligible or new.model_dump(mode="json") != expected_payload:
            raise BatchConceptCompileError("BASE_UNKNOWN_KEY_MIGRATION_INELIGIBLE")
    return exact_rows


_BASE_RELEASE = "release-9cb493e3-8d27-4a0f-8f29-93e2a078725b"
_BASE_EPOCH = 5
_BASE_CANDIDATE = "bdc806e2084afde6651e85c83a88e3d5395487398bea9b4b2c509473a663d684"
_OLD_KEY = "social_insurance_requirement"
_NEW_KEY = "social_insurance_requirements"
_ALIGNMENT_HASHES = (
    "de1a8ca7a18882403fb97312531fd770e4bf5fa822b08db3c61b93bb828b22ce",
    "fbba36cd2226893f51e6ac2333523a22d5854938a987676e1075186df834d069",
)
_MEDICAL_PACK = (
    "medical_insurance",
    "schemapack_medical_insurance",
    "2026-08-12-v5",
    "5a7938dcb86327f12dbff6e3056271e03c63842ba34904eefebb5bcdc8694079",
    "profile_medical_insurance",
    "1.0.0-candidate",
    "61595e9b2fec127dfca4c31ef95f161d55a9b0939211316b4508ccc4b7d21cf3",
)
_BASE_MEMBERS_SHA256 = "260247295fb8530ca298f350d9127f21e412f8155371babc8915c86dc52c7475"
_PROFILE_CONFIRMATION_FILE_SHA256 = (
    "7f6141c63db4a77e3d13a0a8d632ea5463761bedeee7bd1aabef165d68c86863"
)
_PROFILE_CONFIRMATION_SEMANTIC_SHA256 = (
    "cd40072b3c4c32c3ed9440c7ff1ff5effc502c506b4ab11c86bbe438c7649b66"
)


def _catalog_wire_sha256(catalog: SchemaPackCatalogV1) -> str:
    return hashlib.sha256(_canonical_json(catalog).encode()).hexdigest()


def _profile_set_identity(bindings: Sequence[EntityCompileBinding830G3V1]) -> str:
    rows = [
        {
            "entity_id": item.entity_id,
            "profile_id": item.profile_id,
            "profile_version": item.profile_version,
            "profile_sha256": item.profile_sha256,
        }
        for item in sorted(bindings, key=lambda row: row.entity_id)
    ]
    return "profile-set:" + _batch_sha256("batch-profile-bindings.830.g3.v1", rows)


def _catalog_entry(
    request: BatchConceptCompileRequest830G3V1,
    binding: EntityCompileBinding830G3V1,
) -> Any:
    matches = [
        entry
        for entry in request.catalog.entries
        if (
            entry.pack.schema_pack_id,
            entry.pack.schema_version,
            entry.pack.schema_pack_sha256,
        )
        == (binding.schema_pack_id, binding.schema_version, binding.schema_pack_sha256)
    ]
    if len(matches) != 1:
        raise BatchConceptCompileError("SCHEMA_PACK_BINDING_MISMATCH")
    return matches[0]


def _decision_index(resolution: BatchEntityResolutionV1) -> dict[tuple[str, str], tuple[Any, Any]]:
    result: dict[tuple[str, str], tuple[Any, Any]] = {}
    for material in resolution.decisions:
        for child in material.children:
            key = (material.material_id, child.proposal_ref)
            if key in result:
                raise BatchConceptCompileError("RESOLUTION_REFERENCE_INVALID")
            result[key] = (material, child)
    return result


def _validate_confirmation(request: BatchConceptCompileRequest830G3V1) -> None:
    confirmation = request.profile_confirmation
    receipt = confirmation.receipt
    if (
        receipt.catalog_sha256 != request.catalog.catalog_sha256
        or receipt.catalog_wire_sha256 != request.catalog_wire_sha256
        or confirmation.receipt_file_sha256 != _PROFILE_CONFIRMATION_FILE_SHA256
        or confirmation.receipt_semantic_sha256
        != _PROFILE_CONFIRMATION_SEMANTIC_SHA256
    ):
        raise BatchConceptCompileError("PROFILE_CONFIRMATION_MISMATCH")
    expected = {
        (entry.profile.profile_id, entry.profile.profile_version, entry.profile.profile_sha256)
        for entry in request.catalog.entries
    }
    actual = {
        (item.profile_id, item.profile_version, item.profile_sha256) for item in receipt.profiles
    }
    if actual != expected:
        raise BatchConceptCompileError("PROFILE_CONFIRMATION_MISMATCH")


def _validate_request_closure(request: BatchConceptCompileRequest830G3V1) -> None:
    base = request.base_request
    inputs = request.resolution_inputs
    resolution = request.resolution
    if (
        request.catalog_wire_sha256 != _catalog_wire_sha256(request.catalog)
        or resolution.catalog_sha256 != request.catalog.catalog_sha256
        or resolution.space_id != base.space_id
        or (
            inputs.corpus.corpus_sha256,
            inputs.proposals.proposals_sha256,
            inputs.existing_entities.snapshot_sha256,
            inputs.policy.policy_sha256,
        )
        != (
            resolution.corpus_sha256,
            resolution.proposals_sha256,
            resolution.existing_snapshot_sha256,
            resolution.policy_sha256,
        )
    ):
        raise BatchConceptCompileError("RESOLUTION_INPUT_BINDING_MISMATCH")
    scope = (base.tenant_id, base.space_id, base.raw_kb_id, base.wiki_kb_id)
    if scope != (
        inputs.corpus.tenant_id,
        inputs.corpus.space_id,
        inputs.corpus.raw_kb_id,
        inputs.corpus.wiki_kb_id,
    ) or scope != (
        inputs.existing_entities.tenant_id,
        inputs.existing_entities.space_id,
        inputs.existing_entities.raw_kb_id,
        inputs.existing_entities.wiki_kb_id,
    ):
        raise BatchConceptCompileError("SCOPE_MISMATCH")
    if (
        inputs.existing_entities.base_release_id != base.base_release_id
        or inputs.existing_entities.base_activation_epoch != base.base_activation_epoch
        or resolve_batch(
            catalog=request.catalog,
            corpus=inputs.corpus,
            proposals=inputs.proposals,
            existing_entities=inputs.existing_entities,
            policy=inputs.policy,
        )
        != resolution
    ):
        raise BatchConceptCompileError("RESOLUTION_REPLAY_MISMATCH")
    _validate_confirmation(request)
    bindings = request.entity_bindings
    ids = tuple(item.entity_id for item in bindings)
    if ids != tuple(sorted(set(ids))) or set(ids) != set(base.required_fields):
        raise BatchConceptCompileError("ENTITY_BINDING_COVERAGE_MISMATCH")
    if set(ids) != set(base.entity_versions):
        raise BatchConceptCompileError("ENTITY_BINDING_COVERAGE_MISMATCH")
    if base.schema_identity != (
        f"catalog:{request.catalog.catalog_id}@{request.catalog.catalog_version}#"
        f"{request.catalog.catalog_sha256}"
    ) or base.profile_identity != _profile_set_identity(bindings):
        raise BatchConceptCompileError("SCHEMA_PROFILE_IDENTITY_MISMATCH")
    if base.policy_identity != "g3-resolution-policy:" + resolution.policy_sha256:
        raise BatchConceptCompileError("POLICY_IDENTITY_MISMATCH")
    decision_index = _decision_index(resolution)
    proposal_index = {item.material_id: item for item in inputs.proposals.proposals}
    corpus_index = {item.material_id: item for item in inputs.corpus.entries}
    corpus_sources: dict[tuple[str, str], SourceBlock] = {}
    for corpus_row in inputs.corpus.entries:
        for block in corpus_row.blocks:
            key = (block.revision_id, block.block_id)
            previous = corpus_sources.get(key)
            if previous is not None and previous != block:
                raise BatchConceptCompileError("SOURCE_CLOSURE_MISMATCH")
            corpus_sources[key] = block
    base_sources = {
        (block.revision_id, block.block_id): block for block in base.sources
    }
    if any(
        base_sources[key] != block
        for key, block in corpus_sources.items()
        if key in base_sources
    ):
        raise BatchConceptCompileError("SOURCE_CLOSURE_MISMATCH")
    base_entities = set(base.existing_entity_versions)
    matched_base: set[str] = set()
    for binding in bindings:
        entry = _catalog_entry(request, binding)
        expected_profile = entry.profile
        if (
            binding.entity_version != base.entity_versions[binding.entity_id]
            or binding.required_fields != tuple(base.required_fields[binding.entity_id])
            or binding.required_fields != expected_profile.ordered_field_keys
            or (
                binding.profile_id,
                binding.profile_version,
                binding.profile_sha256,
            )
            != (
                expected_profile.profile_id,
                expected_profile.profile_version,
                expected_profile.profile_sha256,
            )
            or entry.pack.applicable_classifications != (binding.primary_classification,)
        ):
            raise BatchConceptCompileError("SCHEMA_PROFILE_BINDING_MISMATCH")
        refs = {(item.material_id, item.proposal_ref): item for item in binding.resolution_refs}
        evidence_ids = {item.evidence_id for item in binding.resolution_evidence}
        if set(binding.source_material_ids) != {key[0] for key in refs}:
            raise BatchConceptCompileError("RESOLUTION_REFERENCE_INVALID")
        bound_by_ref: dict[tuple[str, str], set[str]] = {
            key: set() for key in refs
        }
        for bound in binding.resolution_evidence:
            key = (bound.material_id, bound.proposal_ref)
            found = decision_index.get(key)
            if (
                key not in refs
                or found is None
                or bound.evidence_id not in found[1].evidence_ids
            ):
                raise BatchConceptCompileError("RESOLUTION_EVIDENCE_MISSING")
            bound_by_ref[key].add(bound.evidence_id)
        for key, ref in refs.items():
            found = decision_index.get(key)
            if found is None:
                raise BatchConceptCompileError("RESOLUTION_REFERENCE_INVALID")
            parent, child = found
            if (
                parent.disposition not in ("MATCH", "CREATE", "MULTI")
                or child.disposition != binding.resolution_disposition
                or child.decision_sha256 != ref.decision_sha256
                or child.classification.assignment_sha256
                != ref.classification_assignment_sha256
                or child.classification.primary_label != binding.primary_classification
                or child.classification.schema_pack_id != binding.schema_pack_id
                or child.classification.schema_version != binding.schema_version
                or child.classification.schema_pack_sha256 != binding.schema_pack_sha256
            ):
                raise BatchConceptCompileError("RESOLUTION_REFERENCE_INVALID")
            anchors = child.anchors
            if (
                anchors.issuer is None
                or anchors.name is None
                or anchors.product_code is None
                or anchors.version_label is None
                or anchors.version_anchor is None
                or (
                    binding.display_name,
                    binding.issuer,
                    binding.product_code,
                    binding.version_label,
                    binding.version_anchor,
                )
                != (
                    anchors.name.observed_value,
                    anchors.issuer.observed_value,
                    anchors.product_code.observed_value,
                    anchors.version_label.observed_value,
                    anchors.version_anchor,
                )
            ):
                raise BatchConceptCompileError("RESOLUTION_REFERENCE_INVALID")
            expected_entity_key = _batch_sha256(
                "entity-candidate-key.830.g3.v1",
                {
                    "space_id": resolution.space_id,
                    "product_code": anchors.product_code.normalized_value,
                },
            )
            expected_version_key = _batch_sha256(
                "entity-version-candidate-key.830.g3.v1",
                {
                    "entity_key_sha256": expected_entity_key,
                    "version_label": anchors.version_label.normalized_value,
                    "version_anchor": {
                        "kind": anchors.version_anchor.kind,
                        "value": anchors.version_anchor.normalized_value,
                    },
                },
            )
            if (
                binding.entity_key_sha256 != expected_entity_key
                or binding.version_candidate_key_sha256 != expected_version_key
                or bound_by_ref[key] != set(child.evidence_ids)
            ):
                raise BatchConceptCompileError("RESOLUTION_REFERENCE_INVALID")
            required_identity_evidence = {
                *child.multi_identity_name_evidence_ids,
                *child.multi_identity_code_evidence_ids,
            }
            if not required_identity_evidence.issubset(evidence_ids):
                raise BatchConceptCompileError("RESOLUTION_EVIDENCE_MISSING")
        for bound in binding.resolution_evidence:
            proposal = proposal_index.get(bound.material_id)
            corpus_entry = corpus_index.get(bound.material_id)
            if proposal is None or corpus_entry is None:
                raise BatchConceptCompileError("RESOLUTION_EVIDENCE_MISSING")
            matches = [item for item in proposal.evidence if item.evidence_id == bound.evidence_id]
            if (
                len(matches) != 1
                or matches[0].entity_proposal_ref != bound.proposal_ref
                or matches[0].purpose != bound.purpose
                or matches[0].evidence != bound.evidence
            ):
                raise BatchConceptCompileError("RESOLUTION_EVIDENCE_MISSING")
            verify_evidence(bound.evidence, corpus_entry.blocks)
            source_key = (bound.evidence.revision_id, bound.evidence.block_id)
            if (
                source_key not in corpus_sources
                or source_key not in base_sources
                or base_sources[source_key] != corpus_sources[source_key]
            ):
                raise BatchConceptCompileError("SOURCE_CLOSURE_MISMATCH")
        if binding.resolution_disposition == "MATCH":
            children = [decision_index[key][1] for key in refs]
            if any(
                (child.matched_entity_id, child.matched_entity_version)
                != (binding.entity_id, binding.entity_version)
                for child in children
            ):
                raise BatchConceptCompileError("BASE_ENTITY_MATCH_REQUIRED")
            if binding.entity_id in base_entities:
                matched_base.add(binding.entity_id)
                if (
                    binding.primary_classification,
                    binding.schema_pack_id,
                    binding.schema_version,
                    binding.schema_pack_sha256,
                    binding.profile_id,
                    binding.profile_version,
                    binding.profile_sha256,
                ) != _MEDICAL_PACK:
                    raise BatchConceptCompileError("BASE_PACK_MIGRATION_REQUIRED")
        else:
            children = [decision_index[key][1] for key in refs]
            candidate = children[0].entity_candidate if children else None
            if (
                candidate is None
                or any(child.entity_candidate != candidate for child in children)
                or binding.entity_id != "entity_" + candidate.entity_key_sha256
                or binding.entity_version
                != "entity_"
                + candidate.entity_key_sha256
                + "@"
                + candidate.version_candidate_key_sha256
                or binding.candidate_id != candidate.candidate_id
                or binding.entity_candidate_sha256 != candidate.candidate_sha256
                or binding.entity_key_sha256 != candidate.entity_key_sha256
                or binding.version_candidate_key_sha256
                != candidate.version_candidate_key_sha256
            ):
                raise BatchConceptCompileError("CREATE_IDENTITY_MISMATCH")
    if matched_base != base_entities:
        raise BatchConceptCompileError("BASE_ENTITY_MATCH_REQUIRED")
    source_keys = {(item.revision_id, item.block_id) for item in base.sources}
    existing_members: tuple[ConceptDefinition | FieldAssertion | FreeWikiPage, ...] = (
        *base.existing_definitions,
        *base.existing_fields,
        *base.existing_pages,
    )
    required_source_keys = {
        (evidence.revision_id, evidence.block_id)
        for member in existing_members
        for evidence in member.evidence
    }
    selected_material_ids = {
        material_id for binding in bindings for material_id in binding.source_material_ids
    }
    for material_id in selected_material_ids:
        corpus_entry = corpus_index.get(material_id)
        if corpus_entry is None:
            raise BatchConceptCompileError("SOURCE_CLOSURE_MISMATCH")
        required_source_keys.update(
            (block.revision_id, block.block_id) for block in corpus_entry.blocks
        )
    if source_keys != required_source_keys:
        raise BatchConceptCompileError("SOURCE_CLOSURE_MISMATCH")
    if (
        base.base_release_id,
        base.base_activation_epoch,
        len(base.existing_fields),
        tuple(item.alignment_sha256 for item in request.unknown_field_key_alignments),
    ) != (_BASE_RELEASE, _BASE_EPOCH, 134, _ALIGNMENT_HASHES):
        raise BatchConceptCompileError("BASE_UNKNOWN_KEY_MIGRATION_REQUIRED")
    base_members = {
        "base_release_id": base.base_release_id,
        "base_activation_epoch": base.base_activation_epoch,
        "existing_definitions": base.existing_definitions,
        "existing_fields": base.existing_fields,
        "existing_pages": base.existing_pages,
        "existing_entity_versions": base.existing_entity_versions,
    }
    if _batch_sha256("actual-base-members.830.g3.v1", base_members) != (
        _BASE_MEMBERS_SHA256
    ):
        raise BatchConceptCompileError("BASE_SNAPSHOT_MISMATCH")
    aligned_existing_fields(request)


def _build_unknown_alignments(
    base: CompileRequest,
    catalog: SchemaPackCatalogV1,
) -> tuple[UnknownFieldKeyAlignment830G3V1, ...]:
    medical = next(
        (
            entry
            for entry in catalog.entries
            if entry.pack.schema_pack_id == _MEDICAL_PACK[1]
            and entry.pack.schema_version == _MEDICAL_PACK[2]
            and entry.pack.schema_pack_sha256 == _MEDICAL_PACK[3]
        ),
        None,
    )
    if medical is None:
        raise BatchConceptCompileError("BASE_PACK_AUTHORITY_UNSUPPORTED")
    title = next(
        (
            field.short_title
            for section in medical.profile.sections
            for field in section.fields
            if field.field_key == _NEW_KEY
        ),
        None,
    )
    if title is None:
        raise BatchConceptCompileError("BASE_PACK_AUTHORITY_UNSUPPORTED")
    rows: list[UnknownFieldKeyAlignment830G3V1] = []
    for entity_id in sorted(base.existing_entity_versions):
        matches = [
            field
            for field in base.existing_fields
            if (field.entity_id, field.field_key) == (entity_id, _OLD_KEY)
        ]
        if len(matches) != 1:
            raise BatchConceptCompileError("BASE_UNKNOWN_KEY_MIGRATION_REQUIRED")
        old = matches[0]
        new = old.model_copy(update={"field_key": _NEW_KEY})
        old_member = PageMember(
            kind="field_assertion",
            member_id=old.assertion_id,
            owner_id=old.entity_id,
            title=old.field_key,
            content=_field_content(old),
            payload=old.model_dump(mode="json"),
        )
        new_member = PageMember(
            kind="field_assertion",
            member_id=new.assertion_id,
            owner_id=new.entity_id,
            title=title,
            content=_field_content(new),
            payload=new.model_dump(mode="json"),
        )
        payload: dict[str, object] = {
            "contract": "unknown-field-key-alignment.830.g3.v1",
            "source_release_id": base.base_release_id,
            "source_activation_epoch": base.base_activation_epoch,
            "source_candidate_sha256": _BASE_CANDIDATE,
            "entity_id": entity_id,
            "entity_version": base.existing_entity_versions[entity_id],
            "old_field_key": _OLD_KEY,
            "new_field_key": _NEW_KEY,
            "old_member_id": old.assertion_id,
            "old_member_digest": _concept_member_hash_g3(old_member),
            "new_member_id": new.assertion_id,
            "new_member_digest": _batch_sha256(
                "batch-concept-member.830.g3.v1", new_member
            ),
        }
        rows.append(
            UnknownFieldKeyAlignment830G3V1.model_validate(
                {
                    **payload,
                    "alignment_sha256": _batch_sha256(
                        "unknown-field-key-alignment.830.g3.v1", payload
                    ),
                }
            )
        )
    result = tuple(rows)
    if tuple(row.alignment_sha256 for row in result) != _ALIGNMENT_HASHES:
        raise BatchConceptCompileError("BASE_UNKNOWN_KEY_MIGRATION_REQUIRED")
    return result


def _build_entity_bindings(
    *,
    catalog: SchemaPackCatalogV1,
    proposals: ProposalBatchV1,
    resolution: BatchEntityResolutionV1,
    selected_decision_refs: tuple[tuple[str, str], ...],
) -> tuple[EntityCompileBinding830G3V1, ...]:
    if selected_decision_refs != tuple(sorted(set(selected_decision_refs))):
        raise BatchConceptCompileError("RESOLUTION_REFERENCE_INVALID")
    decisions = _decision_index(resolution)
    proposal_index = {item.material_id: item for item in proposals.proposals}
    selected: list[tuple[str, str, Any, Any]] = []
    for key in selected_decision_refs:
        found = decisions.get(key)
        if found is None or found[1].disposition not in ("MATCH", "CREATE"):
            raise BatchConceptCompileError("RESOLUTION_REFERENCE_INVALID")
        selected.append((*key, *found))
    grouped: dict[str, list[tuple[str, str, Any, Any]]] = {}
    for material_id, proposal_ref, parent, child in selected:
        if parent.disposition not in ("MATCH", "CREATE", "MULTI"):
            raise BatchConceptCompileError("RESOLUTION_REFERENCE_INVALID")
        if child.disposition == "MATCH":
            entity_id = child.matched_entity_id
        else:
            candidate = child.entity_candidate
            entity_id = None if candidate is None else "entity_" + candidate.entity_key_sha256
        if entity_id is None:
            raise BatchConceptCompileError("RESOLUTION_REFERENCE_INVALID")
        grouped.setdefault(entity_id, []).append(
            (material_id, proposal_ref, parent, child)
        )
    bindings: list[EntityCompileBinding830G3V1] = []
    for entity_id in sorted(grouped):
        rows = grouped[entity_id]
        first = rows[0][3]
        anchors = first.anchors
        if any(
            row[3].disposition != first.disposition
            or row[3].anchors != anchors
            or row[3].classification != first.classification
            for row in rows
        ):
            raise BatchConceptCompileError("RESOLUTION_REFERENCE_INVALID")
        if (
            anchors.issuer is None
            or anchors.name is None
            or anchors.product_code is None
            or anchors.version_label is None
            or anchors.version_anchor is None
        ):
            raise BatchConceptCompileError("RESOLUTION_REFERENCE_INVALID")
        classification = first.classification
        entries = [
            entry
            for entry in catalog.entries
            if (
                entry.pack.schema_pack_id,
                entry.pack.schema_version,
                entry.pack.schema_pack_sha256,
            )
            == (
                classification.schema_pack_id,
                classification.schema_version,
                classification.schema_pack_sha256,
            )
        ]
        if len(entries) != 1:
            raise BatchConceptCompileError("SCHEMA_PACK_BINDING_MISMATCH")
        entry = entries[0]
        if first.disposition == "MATCH":
            entity_version = first.matched_entity_version
            candidate_id = candidate_sha = None
            entity_key = _batch_sha256(
                "entity-candidate-key.830.g3.v1",
                {
                    "space_id": resolution.space_id,
                    "product_code": anchors.product_code.normalized_value,
                },
            )
            version_key = _batch_sha256(
                "entity-version-candidate-key.830.g3.v1",
                {
                    "entity_key_sha256": entity_key,
                    "version_label": anchors.version_label.normalized_value,
                    "version_anchor": {
                        "kind": anchors.version_anchor.kind,
                        "value": anchors.version_anchor.normalized_value,
                    },
                },
            )
        else:
            candidate = first.entity_candidate
            if candidate is None:
                raise BatchConceptCompileError("CREATE_IDENTITY_MISMATCH")
            entity_key = candidate.entity_key_sha256
            version_key = candidate.version_candidate_key_sha256
            entity_version = "entity_" + entity_key + "@" + version_key
            candidate_id = candidate.candidate_id
            candidate_sha = candidate.candidate_sha256
        if entity_version is None:
            raise BatchConceptCompileError("RESOLUTION_REFERENCE_INVALID")
        bound_evidence: list[BoundResolutionEvidence830G3V1] = []
        refs: list[ResolutionDecisionRef830G3V1] = []
        for material_id, proposal_ref, _parent, child in rows:
            refs.append(
                ResolutionDecisionRef830G3V1(
                    material_id=material_id,
                    proposal_ref=proposal_ref,
                    decision_sha256=child.decision_sha256,
                    classification_assignment_sha256=(
                        child.classification.assignment_sha256
                    ),
                )
            )
            proposal = proposal_index.get(material_id)
            if proposal is None:
                raise BatchConceptCompileError("RESOLUTION_EVIDENCE_MISSING")
            for evidence in proposal.evidence:
                if evidence.evidence_id not in child.evidence_ids:
                    continue
                if evidence.entity_proposal_ref != proposal_ref or evidence.purpose not in (
                    "issuer",
                    "product_code",
                    "name",
                    "version",
                    "classification",
                ):
                    raise BatchConceptCompileError("RESOLUTION_EVIDENCE_MISSING")
                bound_evidence.append(
                    BoundResolutionEvidence830G3V1(
                        material_id=material_id,
                        proposal_ref=proposal_ref,
                        evidence_id=evidence.evidence_id,
                        purpose=evidence.purpose,
                        evidence=evidence.evidence,
                    )
                )
        payload: dict[str, object] = {
            "contract": "entity-compile-binding.830.g3.v1",
            "entity_id": entity_id,
            "entity_version": entity_version,
            "resolution_disposition": first.disposition,
            "resolution_refs": tuple(
                sorted(refs, key=lambda item: (item.material_id, item.proposal_ref))
            ),
            "entity_key_sha256": entity_key,
            "version_candidate_key_sha256": version_key,
            "candidate_id": candidate_id,
            "entity_candidate_sha256": candidate_sha,
            "display_name": anchors.name.observed_value,
            "issuer": anchors.issuer.observed_value,
            "product_code": anchors.product_code.observed_value,
            "version_label": anchors.version_label.observed_value,
            "version_anchor": anchors.version_anchor,
            "primary_classification": classification.primary_label,
            "schema_pack_id": entry.pack.schema_pack_id,
            "schema_version": entry.pack.schema_version,
            "schema_pack_sha256": entry.pack.schema_pack_sha256,
            "profile_id": entry.profile.profile_id,
            "profile_version": entry.profile.profile_version,
            "profile_sha256": entry.profile.profile_sha256,
            "required_fields": entry.profile.ordered_field_keys,
            "source_material_ids": tuple(sorted({row[0] for row in rows})),
            "resolution_evidence": tuple(
                sorted(
                    bound_evidence,
                    key=lambda item: (item.material_id, item.evidence_id),
                )
            ),
        }
        bindings.append(
            EntityCompileBinding830G3V1.model_validate(
                {
                    **payload,
                    "binding_sha256": _batch_sha256(
                        "entity-compile-binding.830.g3.v1", payload
                    ),
                }
            )
        )
    return tuple(bindings)


def build_batch_compile_request(
    *,
    base_request: CompileRequest,
    catalog_json: bytes,
    profile_confirmation_json: bytes,
    corpus: BatchCorpusV1,
    proposals: ProposalBatchV1,
    existing_entities: ExistingEntitySnapshotV1,
    policy: BatchResolutionPolicyV1,
    resolution: BatchEntityResolutionV1,
    selected_decision_refs: tuple[tuple[str, str], ...],
) -> BatchConceptCompileRequest830G3V1:
    """Build one exact, offline G3 request from Catalog and replayed C inputs."""

    try:
        catalog = validate_catalog(catalog_json)
        confirmation_receipt = CatalogProfileConfirmationReceipt830G3V1.model_validate_json(
            profile_confirmation_json
        )
    except (TypeError, ValueError):
        raise BatchConceptCompileError("BATCH_REQUEST_INVALID") from None
    replayed = resolve_batch(
        catalog=catalog,
        corpus=corpus,
        proposals=proposals,
        existing_entities=existing_entities,
        policy=policy,
    )
    if replayed != resolution:
        raise BatchConceptCompileError("RESOLUTION_REPLAY_MISMATCH")
    bindings = _build_entity_bindings(
        catalog=catalog,
        proposals=proposals,
        resolution=resolution,
        selected_decision_refs=selected_decision_refs,
    )
    binding_index = {item.entity_id: item for item in bindings}
    if any(
        (binding := binding_index.get(entity_id)) is None
        or binding.resolution_disposition != "MATCH"
        or binding.entity_version != entity_version
        for entity_id, entity_version in base_request.existing_entity_versions.items()
    ):
        raise BatchConceptCompileError("BASE_ENTITY_MATCH_REQUIRED")
    confirmation = CatalogProfileConfirmationBinding830G3V1(
        contract="catalog-profile-confirmation-binding.830.g3.v1",
        receipt=confirmation_receipt,
        receipt_file_sha256=hashlib.sha256(profile_confirmation_json).hexdigest(),
        receipt_semantic_sha256=_batch_sha256(
            confirmation_receipt.contract, confirmation_receipt
        ),
    )
    inputs_payload: dict[str, object] = {
        "contract": "batch-resolution-inputs.830.g3.v1",
        "corpus": corpus,
        "proposals": proposals,
        "existing_entities": existing_entities,
        "policy": policy,
    }
    resolution_inputs = BatchResolutionInputs830G3V1.model_validate(
        {
            **inputs_payload,
            "inputs_sha256": _batch_sha256(
                "batch-resolution-inputs.830.g3.v1", inputs_payload
            ),
        }
    )
    payload: dict[str, object] = {
        "contract": "batch-concept-compile-request.830.g3.v1",
        "base_request": base_request,
        "catalog": catalog,
        "catalog_wire_sha256": _catalog_wire_sha256(catalog),
        "profile_confirmation": confirmation,
        "resolution_inputs": resolution_inputs,
        "resolution": resolution,
        "entity_bindings": bindings,
        "unknown_field_key_alignments": _build_unknown_alignments(base_request, catalog),
        "quality_status": "REGISTERED_NOT_QUALITY_ADMITTED",
        "release_lane": "ISOLATED_NOT_FOR_PRODUCTION",
    }
    try:
        return BatchConceptCompileRequest830G3V1.model_validate(
            {
                **payload,
                "request_sha256": _batch_sha256(
                    "batch-concept-compile-request.830.g3.v1", payload
                ),
            }
        )
    except BatchConceptCompileError:
        raise
    except (TypeError, ValueError):
        raise BatchConceptCompileError("BATCH_REQUEST_INVALID") from None


def aligned_existing_fields(
    request: BatchConceptCompileRequest830G3V1,
) -> tuple[FieldAssertion, ...]:
    rows = {(row.entity_id, row.old_field_key): row for row in request.unknown_field_key_alignments}
    result: list[FieldAssertion] = []
    for field in request.base_request.existing_fields:
        row = rows.get((field.entity_id, field.field_key))
        result.append(
            field
            if row is None
            else field.model_copy(update={"field_key": row.new_field_key})
        )
    output = CompileOutput(
        request_hash=compile_request_hash_g3(request.base_request),
        definitions=request.base_request.existing_definitions,
        fields=tuple(sorted(result, key=lambda item: (item.entity_id, item.field_key))),
        pages=request.base_request.existing_pages,
        audit=(),
    )
    checked = validate_unknown_field_key_alignments(
        request.base_request, output, request.unknown_field_key_alignments
    )
    by_entity = {item.entity_id: item for item in request.entity_bindings}
    for row in checked:
        old = next(
            item
            for item in request.base_request.existing_fields
            if (item.entity_id, item.field_key) == (row.entity_id, row.old_field_key)
        )
        new = next(
            item
            for item in result
            if (item.entity_id, item.field_key) == (row.entity_id, row.new_field_key)
        )
        old_member = PageMember(
            kind="field_assertion",
            member_id=old.assertion_id,
            owner_id=old.entity_id,
            title=old.field_key,
            content=_field_content(old),
            payload=old.model_dump(mode="json"),
        )
        entry = _catalog_entry(request, by_entity[row.entity_id])
        title = next(
            field.short_title
            for section in entry.profile.sections
            for field in section.fields
            if field.field_key == row.new_field_key
        )
        new_member = PageMember(
            kind="field_assertion",
            member_id=new.assertion_id,
            owner_id=new.entity_id,
            title=title,
            content=_field_content(new),
            payload=new.model_dump(mode="json"),
        )
        if (
            row.source_candidate_sha256 != _BASE_CANDIDATE
            or row.old_member_digest != _concept_member_hash_g3(old_member)
            or row.new_member_digest
            != _batch_sha256("batch-concept-member.830.g3.v1", new_member)
        ):
            raise BatchConceptCompileError("BASE_UNKNOWN_KEY_MIGRATION_REQUIRED")
    return tuple(sorted(result, key=lambda item: (item.entity_id, item.field_key)))


def _unique_json(raw: str | bytes) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("RAW_OUTPUT_DUPLICATE_KEY")
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=unique)


def _validate_raw(raw: str, output: BaseModel) -> None:
    try:
        parsed = type(output).model_validate(_unique_json(raw))
        if type(parsed) is not type(output) or parsed != output:
            raise ValueError
        if raw.encode("utf-8") != _canonical_json_bytes(output):
            raise ValueError
    except (TypeError, ValueError, json.JSONDecodeError):
        raise BatchConceptCompileError("RAW_OUTPUT_BINDING_MISMATCH") from None


def compiler_context_g3(request: BatchConceptCompileRequest830G3V1) -> dict[str, object]:
    return {
        "request": request,
        "request_sha256": request.request_sha256,
        "base_request_hash": compile_request_hash_g3(request.base_request),
        "output_mode": "NEW_MEMBERS_ONLY",
    }


def carry_context_g3(
    request: BatchConceptCompileRequest830G3V1, model_compile_result: CompileResult
) -> dict[str, object]:
    return {
        "request_sha256": request.request_sha256,
        "model_compile_output_hash": compile_output_hash_g3(model_compile_result.output),
        "model_compile_execution_sha256": paired_execution_sha256_830_g3(
            "batch-concept-model-execution.830.g3.v1", model_compile_result
        ),
    }


def review_context_g3(
    request: BatchConceptCompileRequest830G3V1, output: CompileOutput
) -> dict[str, object]:
    return {
        "request": request,
        "candidate": output,
        "request_sha256": request.request_sha256,
        "base_request_hash": compile_request_hash_g3(request.base_request),
        "output_hash": compile_output_hash_g3(output),
    }


def record_model_compile(
    request: BatchConceptCompileRequest830G3V1,
    output: CompileOutput,
    *,
    run_id: str,
    implementation: str,
    raw: str,
) -> CompileResult:
    _validate_raw(raw, output)
    return CompileResult(
        output=output,
        execution=ExecutionRecord(
            run_id=run_id,
            implementation=implementation,
            context_hash=_batch_sha256(
                "batch-concept-compile-context.830.g3.v1", compiler_context_g3(request)
            ),
            raw_output=raw,
            raw_output_hash=hashlib.sha256(raw.encode()).hexdigest(),
        ),
    )


def _delta_objects(output: CompileOutput) -> dict[str, object]:
    return {
        **{item.concept_id: item for item in output.definitions},
        **{item.assertion_id: item for item in output.fields},
        **{free_page_id(item): item for item in output.pages},
    }


def validate_delta_output(
    request: BatchConceptCompileRequest830G3V1, result: CompileResult
) -> None:
    output = result.output
    if output.request_hash != compile_request_hash_g3(request.base_request):
        raise BatchConceptCompileError("REQUEST_IDENTITY_MISMATCH")
    context_hash = _batch_sha256(
        "batch-concept-compile-context.830.g3.v1", compiler_context_g3(request)
    )
    if result.execution.context_hash != context_hash:
        raise BatchConceptCompileError("EXECUTION_CONTEXT_MISMATCH")
    _validate_raw(result.execution.raw_output, output)
    aligned = aligned_existing_fields(request)
    carried = {(item.entity_id, item.field_key) for item in aligned}
    expected = {
        (entity_id, field_key)
        for entity_id, fields in request.base_request.required_fields.items()
        for field_key in fields
        if (entity_id, field_key) not in carried
    }
    actual = {(item.entity_id, item.field_key) for item in output.fields}
    if actual != expected or len(actual) != len(output.fields):
        raise BatchConceptCompileError("DELTA_FIELD_COVERAGE_MISMATCH")
    if any(
        item.entity_version != request.base_request.entity_versions.get(item.entity_id)
        for item in output.fields
    ):
        raise BatchConceptCompileError("ENTITY_VERSION_MISMATCH")
    old_definitions = {item.concept_id for item in request.base_request.existing_definitions}
    old_pages = {free_page_id(item) for item in request.base_request.existing_pages}
    definition_collision = old_definitions.intersection(
        item.concept_id for item in output.definitions
    )
    page_collision = old_pages.intersection(free_page_id(item) for item in output.pages)
    if definition_collision or page_collision:
        raise BatchConceptCompileError("DELTA_IDENTITY_COLLISION")
    objects = _delta_objects(output)
    promoted = {
        item.key: item
        for item in output.audit
        if item.disposition in ("new_page", "sense", "field_rule")
    }
    if len(promoted) != len(output.audit) or set(promoted) != set(objects):
        raise BatchConceptCompileError("DELTA_AUDIT_MISMATCH")
    if any(
        promoted[item.assertion_id].disposition != "field_rule" for item in output.fields
    ):
        raise BatchConceptCompileError("DELTA_AUDIT_MISMATCH")
    sources = request.base_request.sources
    binding_by_entity = {item.entity_id: item for item in request.entity_bindings}
    source_keys_by_material = {
        entry.material_id: {(block.revision_id, block.block_id) for block in entry.blocks}
        for entry in request.resolution_inputs.corpus.entries
    }
    base_fields_by_entity: dict[str, list[FieldAssertion]] = {}
    for field in request.base_request.existing_fields:
        base_fields_by_entity.setdefault(field.entity_id, []).append(field)
    base_pages_by_entity: dict[str, list[FreeWikiPage]] = {}
    for page in request.base_request.existing_pages:
        base_pages_by_entity.setdefault(page.entity_id, []).append(page)
    definition_by_id = {
        item.concept_id: item for item in request.base_request.existing_definitions
    }
    delta_members: tuple[FieldAssertion | FreeWikiPage, ...] = (
        *output.fields,
        *output.pages,
    )
    for member in delta_members:
        binding = binding_by_entity.get(member.entity_id)
        if binding is None:
            raise BatchConceptCompileError("UNKNOWN_ENTITY")
        allowed = {
            key
            for material_id in binding.source_material_ids
            for key in source_keys_by_material[material_id]
        }
        owner_members: tuple[FieldAssertion | FreeWikiPage, ...] = (
            *base_fields_by_entity.get(member.entity_id, ()),
            *base_pages_by_entity.get(member.entity_id, ()),
        )
        allowed.update(
            (evidence.revision_id, evidence.block_id)
            for owner_member in owner_members
            for evidence in owner_member.evidence
        )
        linked_concept_ids = {
            concept_id for owner_member in owner_members for concept_id in owner_member.concept_ids
        }
        allowed.update(
            (evidence.revision_id, evidence.block_id)
            for concept_id in linked_concept_ids
            if (definition := definition_by_id.get(concept_id)) is not None
            for evidence in definition.evidence
        )
        for evidence in member.evidence:
            verify_evidence(evidence, sources)
            if (evidence.revision_id, evidence.block_id) not in allowed:
                raise BatchConceptCompileError("CROSS_ENTITY_EVIDENCE")


def _validate_output_g3(request: CompileRequest, output: CompileOutput) -> None:
    """Run the G2 semantic phases with byte-preserving G3 identity hashes."""

    request = CompileRequest.model_validate(request)
    output = CompileOutput.model_validate(output)
    if output.request_hash != compile_request_hash_g3(request):
        raise ValueError("REQUEST_IDENTITY_MISMATCH")
    validate_output_member_semantics(request, output)
    existing_defs = {item.concept_id: item for item in request.existing_definitions}
    for definition in output.definitions:
        protected_old = existing_defs.get(definition.concept_id)
        if (
            protected_old is not None
            and protected_old.origin in ("SCHEMA_DEFINITION", "EXPERT_REVISION_RECORD")
            and _definition_hash_g3(protected_old) != _definition_hash_g3(definition)
        ):
            raise ValueError("PROTECTED_DEFINITION_REPLACED")
    validate_output_link_and_evidence_semantics(request, output)
    for obj, old, disposition in validate_disposition_semantics(request, output):
        if disposition == "update" and old == obj:
            raise ValueError("UPDATE_TARGET_MISSING_OR_DUPLICATE")
        if disposition == "alias_link":
            unchanged = (
                isinstance(old, ConceptDefinition)
                and isinstance(obj, ConceptDefinition)
                and _definition_hash_g3(old) == _definition_hash_g3(obj)
            ) or old == obj
            if not unchanged:
                raise ValueError("ALIAS_TARGET_MISMATCH")


def compose_batch_output(
    request: BatchConceptCompileRequest830G3V1, model_compile_result: CompileResult
) -> CompileOutput:
    validate_delta_output(request, model_compile_result)
    base = request.base_request
    delta = model_compile_result.output
    aligned = aligned_existing_fields(request)
    definitions = tuple(
        sorted((*base.existing_definitions, *delta.definitions), key=lambda item: item.concept_id)
    )
    fields = tuple(
        sorted((*aligned, *delta.fields), key=lambda item: (item.entity_id, item.field_key))
    )
    pages = tuple(sorted((*base.existing_pages, *delta.pages), key=free_page_id))
    if (
        len({item.concept_id for item in definitions}) != len(definitions)
        or len({item.assertion_id for item in fields}) != len(fields)
        or len({free_page_id(item) for item in pages}) != len(pages)
    ):
        raise BatchConceptCompileError("COMPOSE_IDENTITY_COLLISION")
    aligned_ids = {row.new_member_id for row in request.unknown_field_key_alignments}
    original_ids = {item.assertion_id for item in base.existing_fields}
    carry_audit = [
        AuditDisposition(key=item.concept_id, disposition="alias_link", reason="BASE_CARRYOVER")
        for item in base.existing_definitions
    ]
    carry_audit.extend(
        AuditDisposition(
            key=item.assertion_id,
            disposition="field_rule",
            reason=(
                "BASE_UNKNOWN_KEY_ALIGNMENT"
                if item.assertion_id in aligned_ids
                else "BASE_CARRYOVER"
            ),
        )
        for item in aligned
    )
    carry_audit.extend(
        AuditDisposition(key=free_page_id(item), disposition="alias_link", reason="BASE_CARRYOVER")
        for item in base.existing_pages
    )
    if aligned_ids.intersection(original_ids):
        raise BatchConceptCompileError("BASE_UNKNOWN_KEY_MIGRATION_REQUIRED")
    output = CompileOutput(
        request_hash=compile_request_hash_g3(base),
        definitions=definitions,
        fields=fields,
        pages=pages,
        audit=tuple(sorted((*carry_audit, *delta.audit), key=lambda item: item.key)),
        transformation=delta.transformation,
    )
    try:
        _validate_output_g3(base, output)
    except ValueError as exc:
        raise BatchConceptCompileError(str(exc)) from None
    return output


def record_composed_output(
    request: BatchConceptCompileRequest830G3V1,
    model_compile_result: CompileResult,
    output: CompileOutput,
    *,
    run_id: str,
) -> CompileResult:
    expected = compose_batch_output(request, model_compile_result)
    if output != expected:
        raise BatchConceptCompileError("COMPILED_OUTPUT_MISMATCH")
    raw = _canonical_json(output)
    return CompileResult(
        output=output,
        execution=ExecutionRecord(
            run_id=run_id,
            implementation="base-carry-compiler.830.g3.v1",
            context_hash=_batch_sha256(
                "batch-concept-carry-context.830.g3.v1",
                carry_context_g3(request, model_compile_result),
            ),
            raw_output=raw,
            raw_output_hash=hashlib.sha256(raw.encode()).hexdigest(),
        ),
    )


def _field_content(field: FieldAssertion) -> str:
    if field.state == "present":
        lines = ["值：" + cast(str, field.value)]
    elif field.state == "absent_explicitly":
        lines = ["明确不提供：" + cast(str, field.value)]
    else:
        lines = ["未知：" + cast(str, field.unknown_reason)]
    lines.extend("条件：" + item for item in field.conditions)
    lines.extend("例外：" + item for item in field.exceptions)
    if field.valid_time:
        lines.append("有效期：" + field.valid_time)
    return "\n".join(lines)


def _free_page_content(page: Any) -> str:
    lines = [page.body]
    lines.extend("条件：" + item for item in page.conditions)
    lines.extend("例外：" + item for item in page.exceptions)
    if page.valid_time:
        lines.append("有效期：" + page.valid_time)
    return "\n".join(lines)


def _directory_entry(
    request: BatchConceptCompileRequest830G3V1,
    binding: EntityCompileBinding830G3V1,
    fields: Mapping[tuple[str, str], FieldAssertion],
) -> EntityDirectoryEntry830G3V1:
    entry = _catalog_entry(request, binding)
    sections = tuple(
        DirectorySection830G3V1(
            section_key=section.section_key,
            display_name=section.display_name,
            fields=tuple(
                DirectoryField830G3V1(
                    field_key=item.field_key,
                    short_title=item.short_title,
                    member_id=fields[(binding.entity_id, item.field_key)].assertion_id,
                )
                for item in section.fields
            ),
        )
        for section in entry.profile.sections
    )
    return EntityDirectoryEntry830G3V1(
        contract="entity-directory-entry.830.g3.v1",
        entity_id=binding.entity_id,
        entity_version=binding.entity_version,
        display_name=binding.display_name,
        issuer=binding.issuer,
        product_code=binding.product_code,
        primary_classification=binding.primary_classification,
        schema_pack_id=binding.schema_pack_id,
        schema_version=binding.schema_version,
        schema_pack_sha256=binding.schema_pack_sha256,
        schema_pack_display_name=entry.pack.display_name,
        profile_id=binding.profile_id,
        profile_version=binding.profile_version,
        profile_sha256=binding.profile_sha256,
        quality_status=request.quality_status,
        release_lane=request.release_lane,
        sections=sections,
    )


def project_batch_members(
    request: BatchConceptCompileRequest830G3V1, output: CompileOutput
) -> BatchConceptPageManifest830G3V1:
    _validate_output_g3(request.base_request, output)
    bindings = {item.entity_id: item for item in request.entity_bindings}
    fields = {(item.entity_id, item.field_key): item for item in output.fields}
    members: list[PageMember] = []
    for definition in output.definitions:
        members.append(
            PageMember(
                kind="concept",
                member_id=definition.concept_id,
                owner_id=request.base_request.space_id,
                title=definition.title,
                content=definition.body,
                payload=definition.model_dump(mode="json"),
            )
        )
    titles: dict[tuple[str, str], str] = {}
    for binding in request.entity_bindings:
        entry = _catalog_entry(request, binding)
        for section in entry.profile.sections:
            for field in section.fields:
                titles[(binding.entity_id, field.field_key)] = field.short_title
    for field in output.fields:
        members.append(
            PageMember(
                kind="field_assertion",
                member_id=field.assertion_id,
                owner_id=field.entity_id,
                title=titles[(field.entity_id, field.field_key)],
                content=_field_content(field),
                payload=field.model_dump(mode="json"),
            )
        )
    for page in output.pages:
        members.append(
            PageMember(
                kind="free_wiki_item",
                member_id=free_page_id(page),
                owner_id=page.entity_id,
                title=page.title,
                content=_free_page_content(page),
                payload=page.model_dump(mode="json"),
            )
        )
    for entity_id in sorted(bindings):
        binding = bindings[entity_id]
        directory = _directory_entry(request, binding, fields)
        section_names = "、".join(section.display_name for section in directory.sections)
        members.append(
            PageMember(
                kind="entity_overview",
                member_id="entity_overview_"
                + digest(
                    "entity-group",
                    [request.base_request.space_id, entity_id, "entity_overview"],
                ),
                owner_id=entity_id,
                title=binding.display_name,
                content=(
                    f"产品：{binding.display_name}\n分类：{binding.primary_classification}\n"
                    f"SchemaPack：{directory.schema_pack_display_name}\n栏目：{section_names}"
                ),
                payload=directory.model_dump(mode="json"),
            )
        )
        free_ids = sorted(
            item.member_id
            for item in members
            if item.owner_id == entity_id and item.kind == "free_wiki_item"
        )
        members.append(
            PageMember(
                kind="free_wiki",
                member_id="free_wiki_"
                + digest("entity-group", [request.base_request.space_id, entity_id, "free_wiki"]),
                owner_id=entity_id,
                title="开放知识",
                content="",
                payload={"member_ids": cast(Any, free_ids)},
            )
        )
    ordered = tuple(sorted(members, key=lambda item: (item.kind, item.member_id)))
    return BatchConceptPageManifest830G3V1(
        contract="batch-concept-page-manifest.830.g3.v1",
        members=ordered,
        members_sha256=_batch_sha256(
            "batch-concept-page-members.830.g3.v1", {"members": ordered}
        ),
        audit=output.audit,
    )


def _validate_execution(
    result: CompileResult | ReviewResult, expected_context_hash: str
) -> None:
    if result.execution.context_hash != expected_context_hash:
        raise BatchConceptCompileError("EXECUTION_CONTEXT_MISMATCH")
    _validate_raw(result.execution.raw_output, result.output)


def validate_candidate_bundle(bundle: BatchConceptCandidateBundle830G3V1) -> None:
    request = bundle.request
    validate_delta_output(request, bundle.model_compile_result)
    expected = compose_batch_output(request, bundle.model_compile_result)
    if bundle.compile_result.output != expected:
        raise BatchConceptCompileError("COMPILED_OUTPUT_MISMATCH")
    compiled_execution = bundle.compile_result.execution
    if (
        compiled_execution.implementation != "base-carry-compiler.830.g3.v1"
        or compiled_execution.raw_output != _canonical_json(expected)
    ):
        raise BatchConceptCompileError("FINAL_EXECUTION_INVALID")
    _validate_execution(
        bundle.compile_result,
        _batch_sha256(
            "batch-concept-carry-context.830.g3.v1",
            carry_context_g3(request, bundle.model_compile_result),
        ),
    )
    review = bundle.review_result
    _validate_execution(
        review,
        _batch_sha256(
            "batch-concept-review-context.830.g3.v1",
            review_context_g3(request, expected),
        ),
    )
    if (review.output.request_hash, review.output.output_hash) != (
        compile_request_hash_g3(request.base_request),
        compile_output_hash_g3(expected),
    ) or review.output.decision == "REJECT":
        raise BatchConceptCompileError("REVIEW_NOT_APPROVED_OR_STALE")
    run_ids = {
        bundle.model_compile_result.execution.run_id,
        compiled_execution.run_id,
        review.execution.run_id,
    }
    if len(run_ids) != 3 or bundle.admission.status != "NEEDS_HUMAN":
        raise BatchConceptCompileError("EXECUTION_INDEPENDENCE_INVALID")
    if bundle.page_manifest != project_batch_members(request, expected):
        raise BatchConceptCompileError("PAGE_MANIFEST_MISMATCH")
    if bundle.candidate_hash != _batch_sha256(
        bundle.contract, _without_hash(bundle, "candidate_hash")
    ):
        raise BatchConceptCompileError("CANDIDATE_HASH_MISMATCH")


def assemble_candidate_bundle(
    request: BatchConceptCompileRequest830G3V1,
    model_compile_result: CompileResult,
    compile_result: CompileResult,
    review_result: ReviewResult,
    admission: HumanBatchAdmission,
) -> BatchConceptCandidateBundle830G3V1:
    manifest = project_batch_members(request, compile_result.output)
    payload: dict[str, object] = {
        "contract": "batch-concept-candidate-bundle.830.g3.v1",
        "request": request,
        "model_compile_result": model_compile_result,
        "compile_result": compile_result,
        "review_result": review_result,
        "page_manifest": manifest,
        "admission": admission,
    }
    return BatchConceptCandidateBundle830G3V1.model_validate(
        {
            **payload,
            "candidate_hash": _batch_sha256(
                cast(str, payload["contract"]), payload
            ),
        }
    )


def validate_batch_candidate(payload: str | bytes) -> BatchConceptCandidateBundle830G3V1:
    try:
        return BatchConceptCandidateBundle830G3V1.model_validate(_unique_json(payload))
    except BatchConceptCompileError:
        raise
    except (TypeError, ValueError):
        raise BatchConceptCompileError("BATCH_CANDIDATE_INVALID") from None


__all__ = [
    "BatchConceptCandidateBundle830G3V1",
    "BatchConceptCompileError",
    "BatchConceptCompileRequest830G3V1",
    "BatchConceptPageManifest830G3V1",
    "BatchResolutionInputs830G3V1",
    "BoundResolutionEvidence830G3V1",
    "CatalogProfileConfirmationBinding830G3V1",
    "CatalogProfileConfirmationReceipt830G3V1",
    "EntityCompileBinding830G3V1",
    "EntityDirectoryEntry830G3V1",
    "ProfileConfirmationIdentity830G3V1",
    "ResolutionDecisionRef830G3V1",
    "UnknownFieldKeyAlignment830G3V1",
    "aligned_existing_fields",
    "assemble_candidate_bundle",
    "build_batch_compile_request",
    "carry_context_g3",
    "compile_output_hash_g3",
    "compile_request_hash_g3",
    "compiler_context_g3",
    "compose_batch_output",
    "project_batch_members",
    "record_composed_output",
    "record_model_compile",
    "review_context_g3",
    "validate_batch_candidate",
    "validate_candidate_bundle",
    "validate_delta_output",
    "validate_unknown_field_key_alignments",
]
