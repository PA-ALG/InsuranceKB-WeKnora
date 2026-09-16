"""Pure G3 batch identity and classification resolution contracts.

The module consumes already captured source and model audit objects.  It never
opens a provider, database, source repository, release, or serving head.
"""

from __future__ import annotations

import json
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.model_policy.models import PolicyReceipt

from .batch_canonical_830_g3 import batch_sha256_830_g3 as _canonical_batch_sha256
from .concept_free_wiki_830_g2 import Evidence, SourceBlock, verify_evidence
from .schema_pack_catalog_830_g3 import SchemaPackCatalogV1
from .schema_wiki_candidate_evidence_join_596_1 import LiveRevisionSourceReceiptV1
from .text_controls import BODY_CONTROLS, STRUCTURED_CONTROLS

Hash = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Confidence = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^(0\.[0-9]{6}|1\.000000)$"),
]
Disposition = Literal["MATCH", "CREATE", "MULTI", "NEEDS_CONFIRM", "QUARANTINE"]
ChildDisposition = Literal["MATCH", "CREATE", "NEEDS_CONFIRM", "QUARANTINE"]
Purpose = Literal[
    "issuer",
    "product_code",
    "name",
    "version",
    "classification",
    "material_role",
    "field",
]
ProvenanceKind = Literal[
    "official_public_document",
    "user_supplied_document",
    "internal_document",
    "unknown",
]
ReasonCode = Literal[
    "INPUT_CONTRACT_INVALID",
    "INPUT_HASH_MISMATCH",
    "DUPLICATE_MATERIAL",
    "DUPLICATE_PROPOSAL",
    "SCOPE_MISMATCH",
    "SOURCE_RECEIPT_MISMATCH",
    "EVIDENCE_JOIN_FAILED",
    "IDENTITY_ANCHOR_CONFLICT",
    "MODEL_OUTPUT_MISSING",
    "MODEL_RECEIPT_INVALID",
    "IDENTITY_EVIDENCE_MISSING",
    "VERSION_UNRESOLVED",
    "AMBIGUOUS_IDENTITY",
    "IDENTITY_BELOW_THRESHOLD",
    "CLASSIFICATION_BELOW_THRESHOLD",
    "CLASSIFICATION_UNRESOLVED",
    "TRUST_POLICY_UNRESOLVED",
    "MULTI_ENTITY_REVIEW",
    "EXACT_EXISTING_MATCH",
    "NEW_ENTITY_CANDIDATE",
    "COMPILED_BATCH_INVALID",
]

_AUTO_REQUIREMENTS = (
    "code",
    "dual_threshold",
    "evidence",
    "issuer",
    "name",
    "no_conflict",
    "unique_key",
    "version",
)
_COMPILER_VERSION = "batch-entity-resolution-compiler.830.g3.v1"
COMPILER_VERSION_V2 = "batch-entity-resolution-compiler.830.g3.v2"
COMPILER_VERSION_V3 = "batch-entity-resolution-compiler.830.g3.v3"
_MODEL_PURPOSE = "g3-batch-resolution"
_MODEL_RUN_SCHEMA_VERSION = "830-g3-v1"
_MODEL_ROLE = "classify"
_AUTOMATIC_REASON: dict[str, ReasonCode] = {
    "MATCH": "EXACT_EXISTING_MATCH",
    "CREATE": "NEW_ENTITY_CANDIDATE",
}


class BatchEntityResolutionError(ValueError):
    """Stable fail-closed error for malformed whole inputs or outputs."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _text(value: str) -> str:
    if (
        unicodedata.normalize("NFC", value) != value
        or not value.strip()
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise ValueError("text must be non-empty canonical NFC")
    return value


Text = Annotated[StrictStr, AfterValidator(_text)]


def _normalized(value: str) -> str:
    return "".join(unicodedata.normalize("NFC", value).split())


def _payload(model: BaseModel, hash_field: str) -> dict[str, object]:
    return {
        name: getattr(model, name)
        for name in type(model).model_fields
        if name != hash_field
    }


def _validate_body_text(value: str) -> None:
    if BODY_CONTROLS.search(value):
        raise ValueError("batch body text is not canonical")


def _validate_structured_text(value: str) -> None:
    if unicodedata.normalize("NFC", value) != value or STRUCTURED_CONTROLS.search(value):
        raise ValueError("batch structured text is not canonical control-free text")


def _validate_typed_batch_text(value: object) -> None:
    """Validate typed C trees before serialization; only exact G2 bodies allow line controls."""

    if type(value) is SourceBlock:
        for name in value.__class__.model_fields:
            item = getattr(value, name)
            if name == "text":
                _validate_body_text(cast(str, item))
            else:
                _validate_typed_batch_text(item)
        return
    if type(value) is Evidence:
        for name in value.__class__.model_fields:
            item = getattr(value, name)
            if name == "quote":
                _validate_body_text(cast(str, item))
            else:
                _validate_typed_batch_text(item)
        return
    if isinstance(value, BaseModel):
        for name in value.__class__.model_fields:
            _validate_typed_batch_text(getattr(value, name))
        return
    if type(value) is str:
        _validate_structured_text(value)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("batch object keys must be strings")
            _validate_structured_text(key)
            _validate_typed_batch_text(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        for item in value:
            _validate_typed_batch_text(item)
        return
    if value is None or type(value) in (bool, int, float) or isinstance(value, date | datetime):
        return


def _batch_sha256(object_type: str, payload: object) -> str:
    _validate_typed_batch_text(payload)
    return _canonical_batch_sha256(object_type, payload)


def _hash_matches(model: BaseModel, hash_field: str, object_type: str) -> bool:
    _validate_typed_batch_text(model)
    return cast(str, getattr(model, hash_field)) == _canonical_batch_sha256(
        object_type, _payload(model, hash_field)
    )


def _sorted_unique(values: Sequence[Any], key: Any) -> bool:
    keys = tuple(key(item) for item in values)
    return keys == tuple(sorted(keys)) and len(keys) == len(set(keys))


def _confidence(value: str) -> Decimal:
    return Decimal(value)


def _iso_date(value: str) -> date | None:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _hashed[ModelT: BaseModel](
    model_type: type[ModelT],
    *,
    object_type: str,
    hash_field: str,
    payload: dict[str, object],
) -> ModelT:
    _validate_typed_batch_text(payload)
    digest = _canonical_batch_sha256(object_type, payload)
    wire = {key: _json_value(value) for key, value in payload.items()}
    wire[hash_field] = digest
    return model_type.model_validate(wire)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class VersionAnchorV1(_FrozenModel):
    kind: Literal["filing_number", "registration_number"]
    value: Text


class ObservedNormalizedValueV1(_FrozenModel):
    observed_value: Text
    normalized_value: Text

    @model_validator(mode="after")
    def validate_normalized(self) -> Self:
        if self.normalized_value != _normalized(self.observed_value):
            raise ValueError("normalized identity value mismatch")
        return self


class CandidateVersionAnchorV1(_FrozenModel):
    kind: Literal["filing_number", "registration_number"]
    observed_value: Text
    normalized_value: Text

    @model_validator(mode="after")
    def validate_normalized(self) -> Self:
        if self.normalized_value != _normalized(self.observed_value):
            raise ValueError("normalized version anchor mismatch")
        return self


class EntityIdentityAnchorsV1(_FrozenModel):
    issuer: ObservedNormalizedValueV1 | None
    name: ObservedNormalizedValueV1 | None
    product_code: ObservedNormalizedValueV1 | None
    version_label: ObservedNormalizedValueV1 | None
    version_anchor: CandidateVersionAnchorV1 | None


class SourceProvenanceV1(_FrozenModel):
    provenance_id: Text
    kind: ProvenanceKind
    source_uri: Text
    acquisition_receipt_sha256: Hash
    declared_by: Text
    declaration_sha256: Hash

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if not _hash_matches(self, "declaration_sha256", "source-provenance.830.g3.v1"):
            raise ValueError("source provenance hash mismatch")
        return self


class RegisteredSourceReceipt830G3V1(_FrozenModel):
    """Exact mirror of the current knowledge-revision-source.v1 HTTP data."""

    contract: Literal["knowledge-revision-source.v1"]
    knowledge_id: Text
    parse_attempt: Annotated[StrictInt, Field(gt=0)]
    revision_source_id: Hash
    file_sha256: Hash
    object_sha256: Hash
    size: Annotated[StrictInt, Field(gt=0)]
    mime_type: Text
    page_count: Annotated[StrictInt, Field(gt=0)]
    manifest_algorithm: Literal["weknora.chunk_manifest.v1"]
    manifest_digest: Hash
    chunk_count: Annotated[StrictInt, Field(gt=0)]
    binding_digest: Hash
    retention_state: Text


SourceReceipt830G3 = Annotated[
    LiveRevisionSourceReceiptV1 | RegisteredSourceReceipt830G3V1,
    Field(discriminator="contract"),
]


class CorpusEntryV1(_FrozenModel):
    material_id: Text
    receipt: SourceReceipt830G3
    native_capture_sha256: Hash
    parser_identity_sha256: Hash
    blocks: tuple[SourceBlock, ...] = Field(min_length=1)
    provenance: SourceProvenanceV1
    entry_sha256: Hash

    @model_validator(mode="after")
    def validate_entry(self) -> Self:
        if not _sorted_unique(self.blocks, lambda item: (item.revision_id, item.block_id)):
            raise ValueError("corpus blocks must be canonical unique")
        if not _hash_matches(self, "entry_sha256", "corpus-entry.830.g3.v1"):
            raise ValueError("corpus entry hash mismatch")
        return self


class BatchCorpusV1(_FrozenModel):
    contract: Literal["batch-corpus.830.g3.v1"]
    tenant_id: Annotated[StrictInt, Field(gt=0)]
    space_id: Text
    raw_kb_id: Text
    wiki_kb_id: Text
    entries: tuple[CorpusEntryV1, ...] = Field(min_length=1)
    corpus_sha256: Hash

    @model_validator(mode="after")
    def validate_corpus(self) -> Self:
        if not _sorted_unique(self.entries, lambda item: item.material_id):
            raise ValueError("corpus entries must be canonical unique")
        if not _hash_matches(self, "corpus_sha256", self.contract):
            raise ValueError("corpus hash mismatch")
        return self


class MaterialBindingV1(_FrozenModel):
    material_id: Text
    corpus_entry_sha256: Hash


class ModelReceiptBindingV1(_FrozenModel):
    policy_receipt: PolicyReceipt
    material_bindings: tuple[MaterialBindingV1, ...] = Field(min_length=1)
    request_sha256: Hash
    input_sha256: Hash
    raw_output_sha256: Hash
    execution_receipt_sha256: Hash

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if not _sorted_unique(self.material_bindings, lambda item: item.material_id):
            raise ValueError("model material bindings must be canonical unique")
        return self


class ProposalEvidenceV1(_FrozenModel):
    evidence_id: Text
    entity_proposal_ref: Text | None
    purpose: Purpose
    field_key: Text | None
    evidence: Evidence

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.purpose == "material_role":
            valid = self.entity_proposal_ref is None and self.field_key is None
        elif self.purpose == "field":
            valid = self.entity_proposal_ref is not None and self.field_key is not None
        else:
            valid = self.entity_proposal_ref is not None and self.field_key is None
        if not valid:
            raise ValueError("proposal evidence scope is invalid")
        return self


class LabelProposalV1(_FrozenModel):
    taxonomy_label: Text
    confidence: Confidence
    evidence_ids: tuple[Text, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> Self:
        if tuple(self.evidence_ids) != tuple(sorted(set(self.evidence_ids))):
            raise ValueError("label evidence IDs must be canonical unique")
        return self


class EntityProposalV1(_FrozenModel):
    proposal_ref: Text
    issuer: Text | None
    name: Text | None
    product_code: Text | None
    version_label: Text | None
    filing_or_registration: VersionAnchorV1 | None
    identity_confidence: Confidence
    identity_evidence_ids: tuple[Text, ...]
    labels: tuple[LabelProposalV1, ...] = Field(min_length=1)
    primary_label: Text
    valid_from: Text | None
    valid_through: Text | None

    @model_validator(mode="after")
    def validate_entity(self) -> Self:
        if tuple(self.identity_evidence_ids) != tuple(sorted(set(self.identity_evidence_ids))):
            raise ValueError("identity evidence IDs must be canonical unique")
        if not _sorted_unique(self.labels, lambda item: item.taxonomy_label):
            raise ValueError("labels must be canonical unique")
        if sum(item.taxonomy_label == self.primary_label for item in self.labels) != 1:
            raise ValueError("primary label must identify exactly one label")
        return self


class MaterialProposalV1(_FrozenModel):
    material_id: Text
    corpus_entry_sha256: Hash
    model_request_sha256: Hash
    material_role: Text
    material_role_evidence_ids: tuple[Text, ...] = Field(min_length=1)
    entities: tuple[EntityProposalV1, ...] = Field(min_length=1)
    evidence: tuple[ProposalEvidenceV1, ...] = Field(min_length=1)
    proposal_sha256: Hash

    @model_validator(mode="after")
    def validate_proposal(self) -> Self:
        if (
            tuple(self.material_role_evidence_ids)
            != tuple(sorted(set(self.material_role_evidence_ids)))
            or not _sorted_unique(self.entities, lambda item: item.proposal_ref)
            or not _sorted_unique(self.evidence, lambda item: item.evidence_id)
        ):
            raise ValueError("proposal collections must be canonical unique")
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        refs = {item.proposal_ref for item in self.entities}
        if any(
            evidence_by_id.get(item) is None or evidence_by_id[item].purpose != "material_role"
            for item in self.material_role_evidence_ids
        ):
            raise ValueError("material role evidence membership mismatch")
        if any(
            item.entity_proposal_ref is not None and item.entity_proposal_ref not in refs
            for item in self.evidence
        ):
            raise ValueError("orphan proposal evidence")
        if any(
            evidence_id not in evidence_by_id
            for entity in self.entities
            for evidence_id in (
                *entity.identity_evidence_ids,
                *(value for label in entity.labels for value in label.evidence_ids),
            )
        ):
            raise ValueError("proposal evidence membership mismatch")
        if not _hash_matches(self, "proposal_sha256", "material-proposal.830.g3.v1"):
            raise ValueError("material proposal hash mismatch")
        return self


class ProposalBatchV1(_FrozenModel):
    contract: Literal["batch-identity-proposals.830.g3.v1"]
    corpus_sha256: Hash
    model_receipts: tuple[ModelReceiptBindingV1, ...]
    proposals: tuple[MaterialProposalV1, ...]
    proposals_sha256: Hash

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        evidence_ids = tuple(
            evidence.evidence_id for proposal in self.proposals for evidence in proposal.evidence
        )
        if not _sorted_unique(
            self.model_receipts, lambda item: item.request_sha256
        ) or not _sorted_unique(self.proposals, lambda item: item.material_id):
            raise ValueError("proposal batch collections must be canonical unique")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("proposal evidence IDs must be batch unique")
        if not _hash_matches(self, "proposals_sha256", self.contract):
            raise ValueError("proposal batch hash mismatch")
        return self


class ApprovedAliasV1(_FrozenModel):
    value: Text
    approval_receipt_sha256: Hash


class ExistingEntityV1(_FrozenModel):
    entity_id: Text
    entity_version: Text
    product_id: Text | None
    product_version_id: Text | None
    issuer: Text
    name: Text
    product_code: Text
    version_label: Text
    filing_or_registration: VersionAnchorV1
    approved_aliases: tuple[ApprovedAliasV1, ...]
    identity_evidence_sha256s: tuple[Hash, ...]

    @model_validator(mode="after")
    def validate_entity(self) -> Self:
        if not _sorted_unique(self.approved_aliases, lambda item: item.value) or tuple(
            self.identity_evidence_sha256s
        ) != tuple(sorted(set(self.identity_evidence_sha256s))):
            raise ValueError("existing entity collections must be canonical unique")
        return self


class ExistingEntitySnapshotV1(_FrozenModel):
    contract: Literal["existing-entities.830.g3.v1"]
    tenant_id: Annotated[StrictInt, Field(gt=0)]
    space_id: Text
    raw_kb_id: Text
    wiki_kb_id: Text
    base_release_id: Text
    base_activation_epoch: Annotated[StrictInt, Field(gt=0)]
    head_receipt_sha256: Hash
    resolver_version: Text
    resolver_policy_sha256: Hash
    entities: tuple[ExistingEntityV1, ...]
    snapshot_sha256: Hash

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if not _sorted_unique(self.entities, lambda item: (item.entity_id, item.entity_version)):
            raise ValueError("existing entities must be canonical unique")
        entity_ids_by_code: dict[str, set[str]] = defaultdict(set)
        codes_by_entity_id: dict[str, set[str]] = defaultdict(set)
        for item in self.entities:
            normalized_code = _normalized(item.product_code)
            entity_ids_by_code[normalized_code].add(item.entity_id)
            codes_by_entity_id[item.entity_id].add(normalized_code)
        if any(len(values) != 1 for values in entity_ids_by_code.values()) or any(
            len(values) != 1 for values in codes_by_entity_id.values()
        ):
            raise ValueError("existing entity key collision")
        if not _hash_matches(self, "snapshot_sha256", self.contract):
            raise ValueError("existing entity snapshot hash mismatch")
        return self


class TrustRuleV1(_FrozenModel):
    rule_id: Text
    provenance_kinds: tuple[ProvenanceKind, ...] = Field(min_length=1)
    material_roles: tuple[Text, ...] = Field(min_length=1)
    purposes: tuple[Purpose, ...] = Field(min_length=1)
    field_keys: tuple[Text, ...]
    space_ids: tuple[Text, ...] = Field(min_length=1)
    product_version_anchors: tuple[Text, ...]
    validity_mode: Literal["identity_only", "interval"]
    valid_from: Text | None
    valid_through: Text | None
    priority: StrictInt

    @model_validator(mode="after")
    def validate_rule(self) -> Self:
        values: tuple[Sequence[str], ...] = (
            self.provenance_kinds,
            self.material_roles,
            self.purposes,
            self.field_keys,
            self.space_ids,
            self.product_version_anchors,
        )
        if any(tuple(item) != tuple(sorted(set(item))) for item in values):
            raise ValueError("trust rule sets must be canonical unique")
        if any(
            any(character in value for character in "*?[]{}") for item in values for value in item
        ):
            raise ValueError("trust rule wildcard is forbidden")
        parsed_from = None if self.valid_from is None else _iso_date(self.valid_from)
        parsed_through = None if self.valid_through is None else _iso_date(self.valid_through)
        if (self.valid_from is not None and parsed_from is None) or (
            self.valid_through is not None and parsed_through is None
        ):
            raise ValueError("trust rule date is invalid")
        if self.validity_mode == "interval" and parsed_from is None:
            raise ValueError("interval trust rule requires valid_from")
        if parsed_from is not None and parsed_through is not None and parsed_through < parsed_from:
            raise ValueError("trust rule interval is invalid")
        return self


class BatchResolutionPolicyV1(_FrozenModel):
    contract: Literal["batch-resolution-policy.830.g3.v1"]
    policy_id: Text
    policy_version: Text
    taxonomy_id: Text
    taxonomy_version: Text
    identity_threshold: Confidence
    classification_threshold: Confidence
    queue_id: Text
    queue_owner: Text
    auto_candidate_requires: tuple[Text, ...]
    rules: tuple[TrustRuleV1, ...] = Field(min_length=1)
    policy_sha256: Hash

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.auto_candidate_requires != _AUTO_REQUIREMENTS:
            raise ValueError("auto candidate requirement set mismatch")
        if not _sorted_unique(self.rules, lambda item: item.rule_id):
            raise ValueError("trust rules must be canonical unique")
        if not _hash_matches(self, "policy_sha256", self.contract):
            raise ValueError("batch policy hash mismatch")
        return self


class ClassificationLabelAssignmentV1(_FrozenModel):
    label: Text
    confidence: Confidence
    evidence_ids: tuple[Text, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        if tuple(self.evidence_ids) != tuple(sorted(set(self.evidence_ids))):
            raise ValueError("classification evidence IDs must be canonical unique")
        return self


class ClassificationAssignmentV1(_FrozenModel):
    taxonomy_id: Text
    taxonomy_version: Text
    labels: tuple[ClassificationLabelAssignmentV1, ...] = Field(min_length=1)
    primary_label: Text
    schema_pack_id: Text | None
    schema_version: Text | None
    schema_pack_sha256: Hash | None
    classification_threshold: Confidence
    assignment_sha256: Hash

    @model_validator(mode="after")
    def validate_assignment(self) -> Self:
        if not _sorted_unique(self.labels, lambda item: item.label):
            raise ValueError("classification labels must be canonical unique")
        if sum(item.label == self.primary_label for item in self.labels) != 1:
            raise ValueError("classification primary label mismatch")
        pack_fields = (self.schema_pack_id, self.schema_version, self.schema_pack_sha256)
        if any(item is None for item in pack_fields) and any(
            item is not None for item in pack_fields
        ):
            raise ValueError("classification pack identity must be complete or absent")
        if not _hash_matches(self, "assignment_sha256", "classification-assignment.830.g3.v1"):
            raise ValueError("classification assignment hash mismatch")
        return self


class EntityCandidateV1(_FrozenModel):
    contract: Literal["entity-candidate.830.g3.v1"]
    candidate_id: Text
    entity_key_sha256: Hash
    version_candidate_key_sha256: Hash
    issuer: ObservedNormalizedValueV1
    name: ObservedNormalizedValueV1
    product_code: ObservedNormalizedValueV1
    version_label: ObservedNormalizedValueV1
    version_anchor: CandidateVersionAnchorV1
    evidence_ids: tuple[Text, ...] = Field(min_length=1)
    status: Literal["NOT_ACTIVE"]
    candidate_sha256: Hash

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        if (
            not self.candidate_id.startswith("entity_candidate_")
            or self.candidate_id != "entity_candidate_" + self.version_candidate_key_sha256
            or tuple(self.evidence_ids) != tuple(sorted(set(self.evidence_ids)))
            or not _hash_matches(self, "candidate_sha256", self.contract)
        ):
            raise ValueError("entity candidate identity or hash mismatch")
        return self


class EntityDecisionV1(_FrozenModel):
    proposal_ref: Text
    disposition: ChildDisposition
    matched_entity_id: Text | None
    matched_entity_version: Text | None
    entity_candidate: EntityCandidateV1 | None
    anchors: EntityIdentityAnchorsV1
    identity_confidence: Confidence
    identity_threshold: Confidence
    classification: ClassificationAssignmentV1
    evidence_ids: tuple[Text, ...]
    multi_identity_name_evidence_ids: tuple[Text, ...]
    multi_identity_code_evidence_ids: tuple[Text, ...]
    reason_codes: tuple[ReasonCode, ...]
    queue_id: Text | None
    queue_owner: Text | None
    decision_sha256: Hash

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        matched = self.matched_entity_id is not None and self.matched_entity_version is not None
        expected_reason = {
            "MATCH": "EXACT_EXISTING_MATCH",
            "CREATE": "NEW_ENTITY_CANDIDATE",
        }.get(self.disposition)
        if (
            (self.matched_entity_id is None) != (self.matched_entity_version is None)
            or (self.disposition == "MATCH" and (not matched or self.entity_candidate is not None))
            or (
                self.disposition == "CREATE"
                and (
                    matched
                    or self.entity_candidate is None
                    or self.entity_candidate.status != "NOT_ACTIVE"
                )
            )
            or (
                self.disposition not in ("MATCH", "CREATE")
                and (matched or self.entity_candidate is not None)
            )
            or tuple(self.evidence_ids) != tuple(sorted(set(self.evidence_ids)))
            or tuple(self.multi_identity_name_evidence_ids)
            != tuple(sorted(set(self.multi_identity_name_evidence_ids)))
            or tuple(self.multi_identity_code_evidence_ids)
            != tuple(sorted(set(self.multi_identity_code_evidence_ids)))
            or not set(self.multi_identity_name_evidence_ids).issubset(self.evidence_ids)
            or not set(self.multi_identity_code_evidence_ids).issubset(self.evidence_ids)
            or tuple(self.reason_codes) != tuple(sorted(set(self.reason_codes)))
            or (expected_reason is not None and expected_reason not in self.reason_codes)
            or (
                self.disposition not in ("MATCH", "CREATE")
                and bool({"EXACT_EXISTING_MATCH", "NEW_ENTITY_CANDIDATE"} & set(self.reason_codes))
            )
        ):
            raise ValueError("entity decision shape is invalid")
        human = self.disposition in ("NEEDS_CONFIRM", "QUARANTINE")
        if human != (self.queue_id is not None and self.queue_owner is not None):
            raise ValueError("entity decision queue binding mismatch")
        if self.disposition in ("MATCH", "CREATE") and not _automatic_decision_valid(self):
            raise ValueError("automatic entity decision is not qualified")
        if not _hash_matches(self, "decision_sha256", "entity-decision.830.g3.v1"):
            raise ValueError("entity decision hash mismatch")
        return self


def _candidate_matches_anchors(
    candidate: EntityCandidateV1, anchors: EntityIdentityAnchorsV1
) -> bool:
    if any(
        value is None
        for value in (
            anchors.issuer,
            anchors.name,
            anchors.product_code,
            anchors.version_label,
            anchors.version_anchor,
        )
    ):
        return False
    issuer = cast(ObservedNormalizedValueV1, anchors.issuer)
    name = cast(ObservedNormalizedValueV1, anchors.name)
    product_code = cast(ObservedNormalizedValueV1, anchors.product_code)
    version_label = cast(ObservedNormalizedValueV1, anchors.version_label)
    version_anchor = cast(CandidateVersionAnchorV1, anchors.version_anchor)
    return (
        candidate.issuer.normalized_value == issuer.normalized_value
        and candidate.name.normalized_value == name.normalized_value
        and candidate.product_code.normalized_value == product_code.normalized_value
        and candidate.version_label.normalized_value == version_label.normalized_value
        and candidate.version_anchor.kind == version_anchor.kind
        and candidate.version_anchor.normalized_value == version_anchor.normalized_value
    )


def _automatic_decision_valid(decision: EntityDecisionV1) -> bool:
    expected_reason = _AUTOMATIC_REASON.get(decision.disposition)
    primary = next(
        (
            item
            for item in decision.classification.labels
            if item.label == decision.classification.primary_label
        ),
        None,
    )
    pack_complete = all(
        value is not None
        for value in (
            decision.classification.schema_pack_id,
            decision.classification.schema_version,
            decision.classification.schema_pack_sha256,
        )
    )
    candidate_valid = decision.disposition == "MATCH" or (
        decision.entity_candidate is not None
        and _candidate_matches_anchors(decision.entity_candidate, decision.anchors)
    )
    return bool(
        expected_reason is not None
        and set(decision.reason_codes) == {expected_reason}
        and _confidence(decision.identity_confidence) >= _confidence(decision.identity_threshold)
        and primary is not None
        and _confidence(primary.confidence)
        >= _confidence(decision.classification.classification_threshold)
        and pack_complete
        and decision.evidence_ids
        and candidate_valid
    )


def _multi_children_valid(children: Sequence[EntityDecisionV1]) -> bool:
    blockers = {
        "SCOPE_MISMATCH",
        "SOURCE_RECEIPT_MISMATCH",
        "EVIDENCE_JOIN_FAILED",
        "IDENTITY_ANCHOR_CONFLICT",
        "MODEL_RECEIPT_INVALID",
    }
    qualified = tuple(
        child
        for child in children
        if child.disposition != "QUARANTINE"
        and child.anchors.name is not None
        and child.anchors.product_code is not None
        and _confidence(child.identity_confidence) >= _confidence(child.identity_threshold)
        and child.multi_identity_name_evidence_ids
        and child.multi_identity_code_evidence_ids
        and not blockers.intersection(child.reason_codes)
    )
    by_key: dict[str, list[EntityDecisionV1]] = defaultdict(list)
    for child in qualified:
        product_code = cast(ObservedNormalizedValueV1, child.anchors.product_code)
        by_key[product_code.normalized_value].append(child)
    clusters: list[set[str]] = []
    for rows in by_key.values():
        names = {
            cast(ObservedNormalizedValueV1, child.anchors.name).normalized_value
            for child in rows
        }
        if len(names) != 1:
            continue
        clusters.append(
            {
                evidence_id
                for child in rows
                for evidence_id in (
                    *child.multi_identity_name_evidence_ids,
                    *child.multi_identity_code_evidence_ids,
                )
            }
        )
    return len(clusters) >= 2 and all(
        clusters[left].isdisjoint(clusters[right])
        for left in range(len(clusters))
        for right in range(left + 1, len(clusters))
    )


class MaterialDecisionV1(_FrozenModel):
    material_id: Text
    disposition: Disposition
    reason_codes: tuple[ReasonCode, ...]
    children: tuple[EntityDecisionV1, ...]
    queue_id: Text | None
    queue_owner: Text | None
    evidence_ids: tuple[Text, ...]
    decision_sha256: Hash

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        direct_child = len(self.children) == 1 and self.children[0].disposition
        multi_valid = _multi_children_valid(self.children)
        if (
            not _sorted_unique(self.children, lambda item: item.proposal_ref)
            or tuple(self.reason_codes) != tuple(sorted(set(self.reason_codes)))
            or tuple(self.evidence_ids) != tuple(sorted(set(self.evidence_ids)))
            or (self.disposition in ("MATCH", "CREATE") and direct_child != self.disposition)
            or (self.disposition == "MULTI") != multi_valid
            or ("MULTI_ENTITY_REVIEW" in self.reason_codes) != multi_valid
            or (not self.children and self.disposition not in ("NEEDS_CONFIRM", "QUARANTINE"))
            or (self.disposition == "MATCH" and "EXACT_EXISTING_MATCH" not in self.reason_codes)
            or (self.disposition == "CREATE" and "NEW_ENTITY_CANDIDATE" not in self.reason_codes)
        ):
            raise ValueError("material decision collections are not canonical")
        human = self.disposition in ("MULTI", "NEEDS_CONFIRM", "QUARANTINE")
        if human != (self.queue_id is not None and self.queue_owner is not None):
            raise ValueError("material decision queue binding mismatch")
        if not _hash_matches(self, "decision_sha256", "material-decision.830.g3.v1"):
            raise ValueError("material decision hash mismatch")
        return self


class DispositionCountsV1(_FrozenModel):
    MATCH: Annotated[StrictInt, Field(ge=0)]
    CREATE: Annotated[StrictInt, Field(ge=0)]
    MULTI: Annotated[StrictInt, Field(ge=0)]
    NEEDS_CONFIRM: Annotated[StrictInt, Field(ge=0)]
    QUARANTINE: Annotated[StrictInt, Field(ge=0)]


class BatchEntityResolutionV1(_FrozenModel):
    contract: Literal["batch-entity-resolution.830.g3.v1"]
    compiler_version: Text
    space_id: Text
    catalog_sha256: Hash
    corpus_sha256: Hash
    proposals_sha256: Hash
    existing_snapshot_sha256: Hash
    policy_sha256: Hash
    model_execution_receipt_sha256s: tuple[Hash, ...]
    decisions: tuple[MaterialDecisionV1, ...]
    material_count: Annotated[StrictInt, Field(ge=0)]
    resolution_decision_count: Annotated[StrictInt, Field(ge=0)]
    model_attempted_count: Annotated[StrictInt, Field(ge=0)]
    disposition_counts: DispositionCountsV1
    batch_sha256: Hash

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        counts = Counter(item.disposition for item in self.decisions)
        names: tuple[Disposition, ...] = (
            "MATCH",
            "CREATE",
            "MULTI",
            "NEEDS_CONFIRM",
            "QUARANTINE",
        )
        expected_counts = {name: counts[name] for name in names}
        if (
            self.compiler_version
            not in (_COMPILER_VERSION, COMPILER_VERSION_V2, COMPILER_VERSION_V3)
            or tuple(self.model_execution_receipt_sha256s)
            != tuple(sorted(set(self.model_execution_receipt_sha256s)))
            or not _sorted_unique(self.decisions, lambda item: item.material_id)
            or self.material_count != len(self.decisions)
            or self.resolution_decision_count != len(self.decisions)
            or not 0 <= self.model_attempted_count <= self.material_count
            or self.disposition_counts.model_dump(mode="python") != expected_counts
            or not _resolution_wire_semantics_valid(self)
            or not _hash_matches(self, "batch_sha256", self.contract)
        ):
            raise ValueError("compiled batch closure or hash mismatch")
        return self


def _resolution_wire_semantics_valid(resolution: BatchEntityResolutionV1) -> bool:
    candidate_children: dict[str, list[EntityDecisionV1]] = defaultdict(list)
    for material in resolution.decisions:
        for child in material.children:
            if child.disposition in ("MATCH", "CREATE") and not _automatic_decision_valid(child):
                return False
            if child.disposition == "CREATE" and child.entity_candidate is not None:
                candidate_children[child.entity_candidate.candidate_id].append(child)
    for children in candidate_children.values():
        candidate = children[0].entity_candidate
        if candidate is None:
            return False
        expected_entity_key = _batch_sha256(
            "entity-candidate-key.830.g3.v1",
            {
                "space_id": resolution.space_id,
                "product_code": candidate.product_code.normalized_value,
            },
        )
        expected_version_key = _batch_sha256(
            "entity-version-candidate-key.830.g3.v1",
            {
                "entity_key_sha256": expected_entity_key,
                "version_label": candidate.version_label.normalized_value,
                "version_anchor": {
                    "kind": candidate.version_anchor.kind,
                    "value": candidate.version_anchor.normalized_value,
                },
            },
        )
        allowed_evidence = {evidence_id for child in children for evidence_id in child.evidence_ids}
        if (
            any(child.entity_candidate != candidate for child in children)
            or candidate.entity_key_sha256 != expected_entity_key
            or candidate.version_candidate_key_sha256 != expected_version_key
            or candidate.candidate_id != "entity_candidate_" + expected_version_key
            or not set(candidate.evidence_ids).issubset(allowed_evidence)
        ):
            return False
    return True


def _exact[ModelT: BaseModel](value: object, expected: type[ModelT]) -> ModelT:
    if type(value) is not expected:
        raise BatchEntityResolutionError("INPUT_CONTRACT_INVALID")
    try:
        return expected.model_validate(
            value.model_dump(
                mode="python", round_trip=True, warnings=False, exclude_computed_fields=True
            )
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise BatchEntityResolutionError("INPUT_CONTRACT_INVALID") from None


def _receipt_parse_attempt(receipt: SourceReceipt830G3) -> int:
    if isinstance(receipt, RegisteredSourceReceipt830G3V1):
        return receipt.parse_attempt
    return receipt.weknora_parse_attempt


def _receipt_manifest_digest(receipt: SourceReceipt830G3) -> str:
    if isinstance(receipt, RegisteredSourceReceipt830G3V1):
        return receipt.manifest_digest
    return receipt.weknora_manifest_digest


def _receipt_scope(
    receipt: SourceReceipt830G3, corpus: BatchCorpusV1
) -> tuple[int, str, str, str]:
    if isinstance(receipt, RegisteredSourceReceipt830G3V1):
        return corpus.tenant_id, corpus.space_id, corpus.raw_kb_id, corpus.wiki_kb_id
    return receipt.tenant_id, receipt.space_id, receipt.raw_kb_id, receipt.wiki_kb_id


def _receipt_source_key(
    receipt: SourceReceipt830G3, corpus: BatchCorpusV1
) -> tuple[int, str, str, str, str, int, str]:
    return (
        *_receipt_scope(receipt, corpus),
        receipt.knowledge_id,
        _receipt_parse_attempt(receipt),
        receipt.revision_source_id,
    )


def _entry_source_reasons(entry: CorpusEntryV1, corpus: BatchCorpusV1) -> set[ReasonCode]:
    receipt = entry.receipt
    reasons: set[ReasonCode] = set()
    if _receipt_scope(receipt, corpus) != (
        corpus.tenant_id,
        corpus.space_id,
        corpus.raw_kb_id,
        corpus.wiki_kb_id,
    ):
        reasons.add("SCOPE_MISMATCH")
    if isinstance(receipt, RegisteredSourceReceipt830G3V1) and (
        receipt.object_sha256 != receipt.file_sha256 or receipt.retention_state != "pinned"
    ):
        reasons.add("SOURCE_RECEIPT_MISMATCH")
    for block in entry.blocks:
        if (block.tenant_id, block.space_id, block.raw_kb_id) != (
            corpus.tenant_id,
            corpus.space_id,
            corpus.raw_kb_id,
        ):
            reasons.add("SCOPE_MISMATCH")
        if (
            block.knowledge_id != receipt.knowledge_id
            or block.parse_attempt != _receipt_parse_attempt(receipt)
            or block.revision_id != receipt.revision_source_id
            or block.source_hash != receipt.file_sha256
            or block.parse_hash != _receipt_manifest_digest(receipt)
            or block.parser_identity != entry.parser_identity_sha256
            or block.page_number > receipt.page_count
        ):
            reasons.add("SOURCE_RECEIPT_MISMATCH")
    return reasons


def _valid_model_receipt(
    binding: ModelReceiptBindingV1,
    corpus: BatchCorpusV1,
    entry_by_id: Mapping[str, CorpusEntryV1],
) -> bool:
    receipt = binding.policy_receipt
    material_payload = [item.model_dump(mode="json") for item in binding.material_bindings]
    expected_input = _batch_sha256(
        "batch-classifier-input.830.g3.v1",
        {"corpus_sha256": corpus.corpus_sha256, "material_bindings": material_payload},
    )
    permit = receipt.permit_view
    return (
        receipt.decision == "ALLOW"
        and receipt.permit_digest is not None
        and permit is not None
        and receipt.space_id == corpus.space_id
        and receipt.purpose == _MODEL_PURPOSE
        and permit.purpose == _MODEL_PURPOSE
        and receipt.run_schema_version == _MODEL_RUN_SCHEMA_VERSION
        and permit.run_schema_version == _MODEL_RUN_SCHEMA_VERSION
        and permit.identity.role == _MODEL_ROLE
        and receipt.identity_key == permit.identity.identity_key
        and binding.input_sha256 == expected_input
        and all(
            (entry := entry_by_id.get(item.material_id)) is not None
            and entry.entry_sha256 == item.corpus_entry_sha256
            for item in binding.material_bindings
        )
    )


def _valid_model_receipt_requests(
    proposals: ProposalBatchV1,
    corpus: BatchCorpusV1,
    entry_by_id: Mapping[str, CorpusEntryV1],
) -> set[str]:
    """Validate unchanged receipts against their original admission corpus group."""

    groups: dict[tuple[str, str, str], list[ModelReceiptBindingV1]] = defaultdict(list)
    for binding in proposals.model_receipts:
        receipt = binding.policy_receipt
        groups[(receipt.admission_hash, receipt.run_id, receipt.run_revision)].append(binding)

    material_group: dict[str, tuple[str, str, str]] = {}
    result: set[str] = set()
    for group_key, bindings in groups.items():
        identities = {
            (
                row.policy_receipt.space_id,
                row.policy_receipt.purpose,
                row.policy_receipt.run_schema_version,
                row.policy_receipt.identity_key,
                None
                if row.policy_receipt.permit_view is None
                else row.policy_receipt.permit_view.identity,
            )
            for row in bindings
        }
        if len(identities) != 1:
            return set()
        material_ids = tuple(item.material_id for row in bindings for item in row.material_bindings)
        if len(material_ids) != len(set(material_ids)):
            return set()
        if any(
            material_id in material_group and material_group[material_id] != group_key
            for material_id in material_ids
        ):
            return set()
        for material_id in material_ids:
            material_group[material_id] = group_key
        try:
            source_entries = tuple(
                sorted(
                    (entry_by_id[material_id] for material_id in material_ids),
                    key=lambda entry: entry.material_id,
                )
            )
        except KeyError:
            continue
        source_payload: dict[str, object] = {
            "contract": "batch-corpus.830.g3.v1",
            "tenant_id": corpus.tenant_id,
            "space_id": corpus.space_id,
            "raw_kb_id": corpus.raw_kb_id,
            "wiki_kb_id": corpus.wiki_kb_id,
            "entries": source_entries,
        }
        source_corpus = _hashed(
            BatchCorpusV1,
            object_type="batch-corpus.830.g3.v1",
            hash_field="corpus_sha256",
            payload=source_payload,
        )
        source_index = {entry.material_id: entry for entry in source_entries}
        result.update(
            row.request_sha256
            for row in bindings
            if _valid_model_receipt(row, corpus, entry_by_id)
            or _valid_model_receipt(row, source_corpus, source_index)
        )
    return result


def _matching_rule(
    *,
    policy: BatchResolutionPolicyV1,
    space_id: str,
    entry: CorpusEntryV1,
    proposal: MaterialProposalV1,
    evidence: ProposalEvidenceV1,
    entity: EntityProposalV1 | None,
) -> bool:
    matches: list[TrustRuleV1] = []
    anchor_value = (
        None
        if entity is None or entity.filing_or_registration is None
        else _normalized(entity.filing_or_registration.value)
    )
    for rule in policy.rules:
        if (
            entry.provenance.kind not in rule.provenance_kinds
            or proposal.material_role not in rule.material_roles
            or evidence.purpose not in rule.purposes
            or space_id not in rule.space_ids
            or (evidence.purpose == "field" and evidence.field_key not in rule.field_keys)
            or (rule.product_version_anchors and anchor_value not in rule.product_version_anchors)
        ):
            continue
        if rule.validity_mode == "interval" and entity is not None:
            if entity.valid_from is None:
                continue
            entity_from = _iso_date(entity.valid_from)
            entity_through = (
                None if entity.valid_through is None else _iso_date(entity.valid_through)
            )
            rule_from = None if rule.valid_from is None else _iso_date(rule.valid_from)
            rule_through = None if rule.valid_through is None else _iso_date(rule.valid_through)
            if entity_from is None or rule_from is None:
                continue
            if entity.valid_through is not None and entity_through is None:
                continue
            if entity_through is not None and entity_through < entity_from:
                continue
            if entity_from < rule_from:
                continue
            if rule_through is not None and (
                entity_through is None or entity_through > rule_through
            ):
                continue
        matches.append(rule)
    if not matches:
        return False
    top = max(item.priority for item in matches)
    top_matches = [item for item in matches if item.priority == top]
    return len(top_matches) == 1


def _anchor(value: str | None) -> ObservedNormalizedValueV1 | None:
    if value is None:
        return None
    return ObservedNormalizedValueV1(observed_value=value, normalized_value=_normalized(value))


def _anchors(entity: EntityProposalV1) -> EntityIdentityAnchorsV1:
    version_anchor = entity.filing_or_registration
    return EntityIdentityAnchorsV1(
        issuer=_anchor(entity.issuer),
        name=_anchor(entity.name),
        product_code=_anchor(entity.product_code),
        version_label=_anchor(entity.version_label),
        version_anchor=(
            None
            if version_anchor is None
            else CandidateVersionAnchorV1(
                kind=version_anchor.kind,
                observed_value=version_anchor.value,
                normalized_value=_normalized(version_anchor.value),
            )
        ),
    )


def _classification(
    catalog: SchemaPackCatalogV1,
    entity: EntityProposalV1,
    policy: BatchResolutionPolicyV1,
) -> ClassificationAssignmentV1:
    pack = next(
        (
            entry.pack
            for entry in catalog.entries
            if entity.primary_label in entry.pack.applicable_classifications
        ),
        None,
    )
    labels = tuple(
        ClassificationLabelAssignmentV1(
            label=item.taxonomy_label,
            confidence=item.confidence,
            evidence_ids=item.evidence_ids,
        )
        for item in entity.labels
    )
    payload: dict[str, object] = {
        "taxonomy_id": policy.taxonomy_id,
        "taxonomy_version": policy.taxonomy_version,
        "labels": labels,
        "primary_label": entity.primary_label,
        "schema_pack_id": None if pack is None else pack.schema_pack_id,
        "schema_version": None if pack is None else pack.schema_version,
        "schema_pack_sha256": None if pack is None else pack.schema_pack_sha256,
        "classification_threshold": policy.classification_threshold,
    }
    return _hashed(
        ClassificationAssignmentV1,
        object_type="classification-assignment.830.g3.v1",
        hash_field="assignment_sha256",
        payload=payload,
    )


def _json_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_computed_fields=True)
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def _evidence_reasons(
    *,
    space_id: str,
    entry: CorpusEntryV1,
    proposal: MaterialProposalV1,
    entity: EntityProposalV1,
    policy: BatchResolutionPolicyV1,
) -> set[ReasonCode]:
    reasons: set[ReasonCode] = set()
    evidence_by_id = {item.evidence_id: item for item in proposal.evidence}
    selected_ids = set(entity.identity_evidence_ids)
    selected_ids.update(value for label in entity.labels for value in label.evidence_ids)
    selected_ids.update(proposal.material_role_evidence_ids)
    for evidence_id in selected_ids:
        row = evidence_by_id.get(evidence_id)
        if row is None:
            reasons.add("EVIDENCE_JOIN_FAILED")
            continue
        if row.purpose != "material_role" and row.entity_proposal_ref != entity.proposal_ref:
            reasons.add("EVIDENCE_JOIN_FAILED")
        try:
            verify_evidence(row.evidence, entry.blocks)
        except (TypeError, ValueError, ValidationError):
            reasons.add("EVIDENCE_JOIN_FAILED")
        if not _matching_rule(
            policy=policy,
            space_id=space_id,
            entry=entry,
            proposal=proposal,
            evidence=row,
            entity=None if row.purpose == "material_role" else entity,
        ):
            reasons.add("TRUST_POLICY_UNRESOLVED")
    identity_purpose_set = {"issuer", "name", "product_code", "version"}
    for evidence_id in entity.identity_evidence_ids:
        row = evidence_by_id.get(evidence_id)
        if (
            row is None
            or row.purpose not in identity_purpose_set
            or row.entity_proposal_ref != entity.proposal_ref
        ):
            reasons.add("EVIDENCE_JOIN_FAILED")
    for label in entity.labels:
        for evidence_id in label.evidence_ids:
            row = evidence_by_id.get(evidence_id)
            if (
                row is None
                or row.purpose != "classification"
                or row.entity_proposal_ref != entity.proposal_ref
            ):
                reasons.add("EVIDENCE_JOIN_FAILED")
    values: dict[Purpose, tuple[str, ...]] = {
        "issuer": () if entity.issuer is None else (entity.issuer,),
        "name": () if entity.name is None else (entity.name,),
        "product_code": () if entity.product_code is None else (entity.product_code,),
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
        "classification": (entity.primary_label,),
        "material_role": (proposal.material_role,),
        "field": (),
    }
    purpose_rows: dict[Purpose, list[ProposalEvidenceV1]] = defaultdict(list)
    for evidence_id in selected_ids:
        row = evidence_by_id.get(evidence_id)
        if row is not None:
            purpose_rows[row.purpose].append(row)
    identity_purposes: tuple[Purpose, ...] = (
        "issuer",
        "name",
        "product_code",
        "version",
    )
    for purpose in identity_purposes:
        for value in values[purpose]:
            if not any(
                _normalized(value) in _normalized(row.evidence.quote)
                for row in purpose_rows[purpose]
                if row.entity_proposal_ref == entity.proposal_ref
            ):
                reasons.add("IDENTITY_EVIDENCE_MISSING")
    primary = next(item for item in entity.labels if item.taxonomy_label == entity.primary_label)
    if not all(
        evidence_by_id[item].purpose == "classification"
        and evidence_by_id[item].entity_proposal_ref == entity.proposal_ref
        for item in primary.evidence_ids
        if item in evidence_by_id
    ):
        reasons.add("EVIDENCE_JOIN_FAILED")
    if entity.valid_from is not None or entity.valid_through is not None:
        parsed_from = None if entity.valid_from is None else _iso_date(entity.valid_from)
        parsed_through = None if entity.valid_through is None else _iso_date(entity.valid_through)
        dates_valid = parsed_from is not None and (
            entity.valid_through is None
            or (parsed_through is not None and parsed_through >= parsed_from)
        )
        dates_supported = all(
            any(
                row is not None
                and row.purpose == "version"
                and row.entity_proposal_ref == entity.proposal_ref
                and value in row.evidence.quote
                for evidence_id in entity.identity_evidence_ids
                if (row := evidence_by_id.get(evidence_id)) is not None
            )
            for value in (entity.valid_from, entity.valid_through)
            if value is not None
        )
        if not dates_valid or not dates_supported:
            reasons.add("TRUST_POLICY_UNRESOLVED")
    return reasons


def _multi_identity_evidence_ids(
    *,
    space_id: str,
    entry: CorpusEntryV1,
    proposal: MaterialProposalV1,
    entity: EntityProposalV1,
    policy: BatchResolutionPolicyV1,
    reasons: set[ReasonCode],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if (
        reasons
        & {
            "SCOPE_MISMATCH",
            "SOURCE_RECEIPT_MISMATCH",
            "EVIDENCE_JOIN_FAILED",
            "MODEL_RECEIPT_INVALID",
        }
        or _confidence(entity.identity_confidence) < _confidence(policy.identity_threshold)
    ):
        return (), ()
    anchors = {"name": entity.name, "product_code": entity.product_code}
    valid: dict[str, list[str]] = {"name": [], "product_code": []}
    evidence_by_id = {item.evidence_id: item for item in proposal.evidence}
    for evidence_id in entity.identity_evidence_ids:
        row = evidence_by_id.get(evidence_id)
        if row is None or row.purpose not in anchors:
            continue
        anchor = anchors[row.purpose]
        if anchor is None or row.entity_proposal_ref != entity.proposal_ref:
            continue
        try:
            verify_evidence(row.evidence, entry.blocks)
        except (TypeError, ValueError, ValidationError):
            continue
        if not _matching_rule(
            policy=policy,
            space_id=space_id,
            entry=entry,
            proposal=proposal,
            evidence=row,
            entity=entity,
        ):
            continue
        if _normalized(anchor) not in _normalized(row.evidence.quote):
            continue
        valid[row.purpose].append(evidence_id)
    return tuple(sorted(valid["name"])), tuple(sorted(valid["product_code"]))


def _evidence_occurrence(evidence: Evidence) -> tuple[object, ...]:
    return (
        evidence.tenant_id,
        evidence.space_id,
        evidence.raw_kb_id,
        evidence.knowledge_id,
        evidence.parse_attempt,
        evidence.revision_id,
        evidence.source_hash,
        evidence.parse_hash,
        evidence.parser_identity,
        evidence.source_type,
        evidence.block_id,
        evidence.page_number,
        evidence.offset_unit,
        evidence.start,
        evidence.end,
        evidence.quote_hash,
    )


def _identity_key(space_id: str, code: str) -> str:
    return _batch_sha256(
        "entity-candidate-key.830.g3.v1",
        {"space_id": space_id, "product_code": _normalized(code)},
    )


def _version_key(entity_key: str, entity: EntityProposalV1) -> str | None:
    if entity.version_label is None or entity.filing_or_registration is None:
        return None
    return _batch_sha256(
        "entity-version-candidate-key.830.g3.v1",
        {
            "entity_key_sha256": entity_key,
            "version_label": _normalized(entity.version_label),
            "version_anchor": {
                "kind": entity.filing_or_registration.kind,
                "value": _normalized(entity.filing_or_registration.value),
            },
        },
    )


def _candidate(
    *,
    space_id: str,
    entity: EntityProposalV1,
    evidence_ids: tuple[str, ...],
) -> EntityCandidateV1:
    if (
        entity.issuer is None
        or entity.name is None
        or entity.product_code is None
        or entity.version_label is None
        or entity.filing_or_registration is None
    ):
        raise ValueError("candidate identity is incomplete")
    entity_key = _identity_key(space_id, entity.product_code)
    version_key = _version_key(entity_key, entity)
    if version_key is None:
        raise ValueError("candidate version is incomplete")
    payload: dict[str, object] = {
        "contract": "entity-candidate.830.g3.v1",
        "candidate_id": "entity_candidate_" + version_key,
        "entity_key_sha256": entity_key,
        "version_candidate_key_sha256": version_key,
        "issuer": _anchor(entity.issuer),
        "name": _anchor(entity.name),
        "product_code": _anchor(entity.product_code),
        "version_label": _anchor(entity.version_label),
        "version_anchor": CandidateVersionAnchorV1(
            kind=entity.filing_or_registration.kind,
            observed_value=entity.filing_or_registration.value,
            normalized_value=_normalized(entity.filing_or_registration.value),
        ),
        "evidence_ids": evidence_ids,
        "status": "NOT_ACTIVE",
    }
    return _hashed(
        EntityCandidateV1,
        object_type="entity-candidate.830.g3.v1",
        hash_field="candidate_sha256",
        payload=payload,
    )


def _existing_matches(
    existing: ExistingEntitySnapshotV1, entity: EntityProposalV1
) -> tuple[ExistingEntityV1, ...]:
    if entity.product_code is None:
        return ()
    code = _normalized(entity.product_code)
    return tuple(item for item in existing.entities if _normalized(item.product_code) == code)


def _has_existing_identity_competition(
    existing: ExistingEntitySnapshotV1, entity: EntityProposalV1
) -> bool:
    proposed_code = None if entity.product_code is None else _normalized(entity.product_code)
    proposed_name = None if entity.name is None else _normalized(entity.name)
    proposed_anchor = entity.filing_or_registration
    for item in existing.entities:
        if proposed_code is not None and _normalized(item.product_code) == proposed_code:
            continue
        names = {
            _normalized(item.name),
            *(_normalized(alias.value) for alias in item.approved_aliases),
        }
        name_competes = proposed_name is not None and proposed_name in names
        anchor_competes = (
            proposed_anchor is not None
            and proposed_anchor.kind == item.filing_or_registration.kind
            and _normalized(proposed_anchor.value) == _normalized(item.filing_or_registration.value)
        )
        if name_competes or anchor_competes:
            return True
    return False


def _entity_reasons(
    *,
    space_id: str,
    entity: EntityProposalV1,
    proposal: MaterialProposalV1,
    entry: CorpusEntryV1,
    catalog: SchemaPackCatalogV1,
    existing: ExistingEntitySnapshotV1,
    policy: BatchResolutionPolicyV1,
    forced_reasons: set[ReasonCode],
) -> tuple[set[ReasonCode], ClassificationAssignmentV1]:
    reasons = set(forced_reasons)
    reasons.update(
        _evidence_reasons(
            space_id=space_id,
            entry=entry,
            proposal=proposal,
            entity=entity,
            policy=policy,
        )
    )
    if any(value is None for value in (entity.issuer, entity.name, entity.product_code)):
        reasons.add("IDENTITY_EVIDENCE_MISSING")
    if entity.version_label is None or entity.filing_or_registration is None:
        reasons.add("VERSION_UNRESOLVED")
    if _confidence(entity.identity_confidence) < _confidence(policy.identity_threshold):
        reasons.add("IDENTITY_BELOW_THRESHOLD")
    primary = next(item for item in entity.labels if item.taxonomy_label == entity.primary_label)
    classification = _classification(catalog, entity, policy)
    if _confidence(primary.confidence) < _confidence(policy.classification_threshold):
        reasons.add("CLASSIFICATION_BELOW_THRESHOLD")
    if classification.schema_pack_id is None:
        reasons.add("CLASSIFICATION_UNRESOLVED")
    if _has_existing_identity_competition(existing, entity):
        reasons.add("AMBIGUOUS_IDENTITY")
    return reasons, classification


def _decision(
    *,
    space_id: str,
    entity: EntityProposalV1,
    proposal: MaterialProposalV1,
    entry: CorpusEntryV1,
    catalog: SchemaPackCatalogV1,
    existing: ExistingEntitySnapshotV1,
    policy: BatchResolutionPolicyV1,
    forced_reasons: set[ReasonCode],
    candidate: EntityCandidateV1 | None,
    version_ambiguous: bool,
    multi_identity_name_evidence_ids: tuple[str, ...],
    multi_identity_code_evidence_ids: tuple[str, ...],
) -> EntityDecisionV1:
    anchors = _anchors(entity)
    reasons, classification = _entity_reasons(
        space_id=space_id,
        entity=entity,
        proposal=proposal,
        entry=entry,
        catalog=catalog,
        existing=existing,
        policy=policy,
        forced_reasons=forced_reasons,
    )
    if version_ambiguous:
        reasons.add("AMBIGUOUS_IDENTITY")

    matches = _existing_matches(existing, entity)
    exact_match: ExistingEntityV1 | None = None
    if matches:
        issuer_matches = tuple(
            match
            for match in matches
            if entity.issuer is None or _normalized(entity.issuer) == _normalized(match.issuer)
        )
        if not issuer_matches:
            reasons.add("IDENTITY_ANCHOR_CONFLICT")
        else:
            exact_matches = tuple(
                match
                for match in issuer_matches
                if entity.name is not None
                and _normalized(entity.name)
                in {
                    _normalized(match.name),
                    *(_normalized(alias.value) for alias in match.approved_aliases),
                }
                and entity.version_label is not None
                and entity.filing_or_registration is not None
                and _normalized(entity.version_label) == _normalized(match.version_label)
                and entity.filing_or_registration.kind == match.filing_or_registration.kind
                and _normalized(entity.filing_or_registration.value)
                == _normalized(match.filing_or_registration.value)
            )
            if len(exact_matches) != 1:
                reasons.add("AMBIGUOUS_IDENTITY")
            else:
                exact_match = exact_matches[0]

    quarantine_reasons = {
        "SCOPE_MISMATCH",
        "SOURCE_RECEIPT_MISMATCH",
        "EVIDENCE_JOIN_FAILED",
        "IDENTITY_ANCHOR_CONFLICT",
        "MODEL_RECEIPT_INVALID",
    }
    if reasons & quarantine_reasons:
        disposition: ChildDisposition = "QUARANTINE"
        exact_match = None
        candidate = None
    elif reasons:
        disposition = "NEEDS_CONFIRM"
        exact_match = None
        candidate = None
    elif exact_match is not None:
        disposition = "MATCH"
        reasons.add("EXACT_EXISTING_MATCH")
        candidate = None
    else:
        disposition = "CREATE"
        reasons.add("NEW_ENTITY_CANDIDATE")
        if candidate is None:
            candidate = _candidate(
                space_id=space_id,
                entity=entity,
                evidence_ids=tuple(sorted(set(entity.identity_evidence_ids))),
            )
    human = disposition in ("NEEDS_CONFIRM", "QUARANTINE")
    evidence_ids = tuple(
        sorted(
            set(entity.identity_evidence_ids)
            | {value for label in entity.labels for value in label.evidence_ids}
        )
    )
    if disposition == "QUARANTINE" or reasons & {
        "IDENTITY_ANCHOR_CONFLICT",
        "EVIDENCE_JOIN_FAILED",
    }:
        multi_identity_name_evidence_ids = ()
        multi_identity_code_evidence_ids = ()
    payload: dict[str, object] = {
        "proposal_ref": entity.proposal_ref,
        "disposition": disposition,
        "matched_entity_id": None if exact_match is None else exact_match.entity_id,
        "matched_entity_version": None if exact_match is None else exact_match.entity_version,
        "entity_candidate": candidate if disposition == "CREATE" else None,
        "anchors": anchors,
        "identity_confidence": entity.identity_confidence,
        "identity_threshold": policy.identity_threshold,
        "classification": classification,
        "evidence_ids": evidence_ids,
        "multi_identity_name_evidence_ids": multi_identity_name_evidence_ids,
        "multi_identity_code_evidence_ids": multi_identity_code_evidence_ids,
        "reason_codes": tuple(sorted(reasons)),
        "queue_id": policy.queue_id if human else None,
        "queue_owner": policy.queue_owner if human else None,
    }
    return _hashed(
        EntityDecisionV1,
        object_type="entity-decision.830.g3.v1",
        hash_field="decision_sha256",
        payload=payload,
    )


def _material_decision(
    *,
    entry: CorpusEntryV1,
    proposal: MaterialProposalV1 | None,
    children: tuple[EntityDecisionV1, ...],
    policy: BatchResolutionPolicyV1,
    reasons: set[ReasonCode],
) -> MaterialDecisionV1:
    source_quarantine = reasons & {
        "SCOPE_MISMATCH",
        "SOURCE_RECEIPT_MISMATCH",
        "EVIDENCE_JOIN_FAILED",
        "MODEL_RECEIPT_INVALID",
    }
    if source_quarantine:
        disposition: Disposition = "QUARANTINE"
        evidence_ids = (
            () if proposal is None else tuple(item.evidence_id for item in proposal.evidence)
        )
    elif proposal is None:
        disposition = "NEEDS_CONFIRM"
        evidence_ids = ()
    else:
        if _multi_children_valid(children):
            disposition = "MULTI"
            reasons.add("MULTI_ENTITY_REVIEW")
        elif len(children) == 1:
            disposition = cast(Disposition, children[0].disposition)
        else:
            disposition = "NEEDS_CONFIRM"
            reasons.add("AMBIGUOUS_IDENTITY")
        evidence_ids = tuple(item.evidence_id for item in proposal.evidence)
    if disposition == "MATCH":
        reasons.add("EXACT_EXISTING_MATCH")
    elif disposition == "CREATE":
        reasons.add("NEW_ENTITY_CANDIDATE")
    human = disposition in ("MULTI", "NEEDS_CONFIRM", "QUARANTINE")
    payload: dict[str, object] = {
        "material_id": entry.material_id,
        "disposition": disposition,
        "reason_codes": tuple(sorted(reasons)),
        "children": children,
        "queue_id": policy.queue_id if human else None,
        "queue_owner": policy.queue_owner if human else None,
        "evidence_ids": tuple(sorted(set(evidence_ids))),
    }
    return _hashed(
        MaterialDecisionV1,
        object_type="material-decision.830.g3.v1",
        hash_field="decision_sha256",
        payload=payload,
    )


def effective_evidence_proposals_v2(
    proposals: ProposalBatchV1, corpus: BatchCorpusV1 | None = None
) -> ProposalBatchV1:
    """A read-only resolver view; original model objects/receipt hashes stay intact.

    A filing number is already an explicit version identity. The existing wire
    label slot carries that observed anchor when there is no separate title label.
    """
    if corpus is not None:
        from .g3_evidence_identity_v2 import expand_directory
        entries = {row.material_id: row for row in corpus.entries}
        proposals = proposals.model_copy(update={
            "proposals": tuple(
                expand_directory(row, entries[row.material_id]) for row in proposals.proposals
            )
        })
    return proposals.model_copy(update={"proposals": tuple(
        proposal.model_copy(update={"entities": tuple(
            entity.model_copy(update={"version_label": entity.filing_or_registration.value})
            if entity.version_label is None and entity.filing_or_registration is not None
            else entity for entity in proposal.entities
        )}) for proposal in proposals.proposals
    )})


def _distinct_filing_versions_v2(contenders, classifications) -> bool:
    identities, anchors, versions = set(), set(), set()
    for (entry, _, entity), version in contenders:
        classification = classifications[(entry.material_id, entity.proposal_ref)]
        identities.add((entity.issuer, entity.name, entity.product_code,
                        classification.schema_pack_id, classification.schema_version,
                        classification.schema_pack_sha256))
        if entity.filing_or_registration is None:
            return False
        anchors.add((entity.filing_or_registration.kind,
                     _normalized(entity.filing_or_registration.value)))
        versions.add(version)
    return len(identities) == 1 and len(anchors) == len(versions)


def resolve_batch(
    *,
    catalog: SchemaPackCatalogV1,
    corpus: BatchCorpusV1,
    proposals: ProposalBatchV1,
    existing_entities: ExistingEntitySnapshotV1,
    policy: BatchResolutionPolicyV1,
    compiler_version: str = _COMPILER_VERSION,
) -> BatchEntityResolutionV1:
    """Resolve an already captured batch without IO or serving side effects."""

    try:
        if compiler_version not in (_COMPILER_VERSION, COMPILER_VERSION_V2, COMPILER_VERSION_V3):
            raise BatchEntityResolutionError("INPUT_CONTRACT_INVALID")
        if type(corpus) is not BatchCorpusV1 or type(proposals) is not ProposalBatchV1:
            raise BatchEntityResolutionError("INPUT_CONTRACT_INVALID")
        corpus_material_ids = tuple(item.material_id for item in corpus.entries)
        if len(corpus_material_ids) != len(set(corpus_material_ids)):
            raise BatchEntityResolutionError("DUPLICATE_MATERIAL")
        proposal_material_ids = tuple(item.material_id for item in proposals.proposals)
        if len(proposal_material_ids) != len(set(proposal_material_ids)):
            raise BatchEntityResolutionError("DUPLICATE_PROPOSAL")
        exact_catalog = _exact(catalog, SchemaPackCatalogV1)
        exact_corpus = _exact(corpus, BatchCorpusV1)
        exact_proposals = _exact(proposals, ProposalBatchV1)
        exact_existing = _exact(existing_entities, ExistingEntitySnapshotV1)
        exact_policy = _exact(policy, BatchResolutionPolicyV1)
        if compiler_version in (COMPILER_VERSION_V2, COMPILER_VERSION_V3):
            exact_proposals = effective_evidence_proposals_v2(exact_proposals, exact_corpus)
        source_keys = tuple(
            _receipt_source_key(entry.receipt, exact_corpus)
            for entry in exact_corpus.entries
        )
        if len(source_keys) != len(set(source_keys)):
            raise BatchEntityResolutionError("DUPLICATE_MATERIAL")
        if exact_proposals.corpus_sha256 != exact_corpus.corpus_sha256:
            raise BatchEntityResolutionError("INPUT_HASH_MISMATCH")

        entry_by_id = {item.material_id: item for item in exact_corpus.entries}
        proposal_by_id = {item.material_id: item for item in exact_proposals.proposals}
        if set(proposal_by_id) - set(entry_by_id):
            raise BatchEntityResolutionError("INPUT_CONTRACT_INVALID")
        scope = (
            exact_corpus.tenant_id,
            exact_corpus.space_id,
            exact_corpus.raw_kb_id,
            exact_corpus.wiki_kb_id,
        )
        if scope != (
            exact_existing.tenant_id,
            exact_existing.space_id,
            exact_existing.raw_kb_id,
            exact_existing.wiki_kb_id,
        ):
            global_scope_mismatch = True
        else:
            global_scope_mismatch = False

        receipt_by_request = {item.request_sha256: item for item in exact_proposals.model_receipts}
        valid_requests = _valid_model_receipt_requests(
            exact_proposals, exact_corpus, entry_by_id
        )
        attempted_materials = {
            binding.material_id
            for request_sha in valid_requests
            for binding in receipt_by_request[request_sha].material_bindings
        }

        material_reasons_by_id: dict[str, set[ReasonCode]] = {}
        for entry in exact_corpus.entries:
            material_proposal = proposal_by_id.get(entry.material_id)
            reasons = _entry_source_reasons(entry, exact_corpus)
            if global_scope_mismatch:
                reasons.add("SCOPE_MISMATCH")
            if material_proposal is not None:
                receipt = receipt_by_request.get(material_proposal.model_request_sha256)
                material_bound = receipt is not None and any(
                    item.material_id == entry.material_id
                    and item.corpus_entry_sha256 == entry.entry_sha256
                    for item in receipt.material_bindings
                )
                if (
                    receipt is None
                    or material_proposal.model_request_sha256 not in valid_requests
                    or not material_bound
                ):
                    reasons.add("MODEL_RECEIPT_INVALID")
                if material_proposal.corpus_entry_sha256 != entry.entry_sha256:
                    reasons.add("EVIDENCE_JOIN_FAILED")
            material_reasons_by_id[entry.material_id] = reasons

        # Establish each row's eligibility before any aggregation. Only fully
        # qualified rows may contribute candidate identity or evidence.
        EntityRow = tuple[CorpusEntryV1, MaterialProposalV1, EntityProposalV1]
        entity_rows: list[EntityRow] = []
        row_reasons: dict[tuple[str, str], set[ReasonCode]] = {}
        row_classification: dict[tuple[str, str], ClassificationAssignmentV1] = {}
        row_multi_identity_evidence: dict[
            tuple[str, str], tuple[tuple[str, ...], tuple[str, ...]]
        ] = {}
        for proposal_row in exact_proposals.proposals:
            entry = entry_by_id[proposal_row.material_id]
            for entity in proposal_row.entities:
                row_id = (entry.material_id, entity.proposal_ref)
                reasons, classification = _entity_reasons(
                    space_id=exact_corpus.space_id,
                    entity=entity,
                    proposal=proposal_row,
                    entry=entry,
                    catalog=exact_catalog,
                    existing=exact_existing,
                    policy=exact_policy,
                    forced_reasons=material_reasons_by_id[entry.material_id],
                )
                entity_rows.append((entry, proposal_row, entity))
                row_reasons[row_id] = reasons
                row_classification[row_id] = classification
                row_multi_identity_evidence[row_id] = _multi_identity_evidence_ids(
                    space_id=exact_corpus.space_id,
                    entry=entry,
                    proposal=proposal_row,
                    entity=entity,
                    policy=exact_policy,
                    reasons=reasons,
                )

        identity_rows_by_key: dict[str, list[EntityRow]] = defaultdict(list)
        occurrence_keys: dict[tuple[object, ...], set[str]] = defaultdict(set)
        for row in entity_rows:
            entry, proposal_row, entity = row
            row_id = (entry.material_id, entity.proposal_ref)
            name_ids, code_ids = row_multi_identity_evidence[row_id]
            if entity.name is None or entity.product_code is None or not name_ids or not code_ids:
                continue
            entity_key = _identity_key(exact_corpus.space_id, entity.product_code)
            identity_rows_by_key[entity_key].append(row)
            evidence_by_id = {item.evidence_id: item for item in proposal_row.evidence}
            for evidence_id in (*name_ids, *code_ids):
                occurrence_keys[_evidence_occurrence(evidence_by_id[evidence_id].evidence)].add(
                    entity_key
                )

        invalid_identity_keys = {
            entity_key
            for entity_key, rows in identity_rows_by_key.items()
            if len({_normalized(cast(str, row[2].name)) for row in rows}) != 1
        }
        invalid_identity_keys.update(
            entity_key
            for keys in occurrence_keys.values()
            if len(keys) > 1
            for entity_key in keys
        )
        if invalid_identity_keys:
            for row in entity_rows:
                entry, _, entity = row
                if entity.product_code is None:
                    continue
                entity_key = _identity_key(exact_corpus.space_id, entity.product_code)
                if entity_key in invalid_identity_keys:
                    row_multi_identity_evidence[(entry.material_id, entity.proposal_ref)] = ((), ())

        structural_only: set[ReasonCode] = {
            "IDENTITY_EVIDENCE_MISSING",
            "VERSION_UNRESOLVED",
        }
        contenders_by_entity_key: dict[str, list[tuple[EntityRow, str]]] = defaultdict(list)
        eligible_by_version: dict[tuple[str, str], list[EntityRow]] = defaultdict(list)
        for row in entity_rows:
            entry, _, entity = row
            if entity.product_code is None:
                continue
            entity_key = _identity_key(exact_corpus.space_id, entity.product_code)
            version_key = _version_key(entity_key, entity)
            if version_key is None:
                continue
            row_id = (entry.material_id, entity.proposal_ref)
            reasons = row_reasons[row_id]
            if reasons <= structural_only:
                contenders_by_entity_key[entity_key].append((row, version_key))
            if not reasons:
                eligible_by_version[(entity_key, version_key)].append(row)

        ambiguous_rows: set[tuple[str, str]] = set()
        for contenders in contenders_by_entity_key.values():
            versions = {version_key for _, version_key in contenders}
            if len(versions) > 1:
                if (compiler_version == COMPILER_VERSION_V2
                        and _distinct_filing_versions_v2(contenders, row_classification)):
                    continue
                ambiguous_rows.update(
                    (row[0].material_id, row[2].proposal_ref) for row, _ in contenders
                )
                continue
            shapes = {
                (
                    None if entity.issuer is None else _normalized(entity.issuer),
                    None if entity.name is None else _normalized(entity.name),
                    None if entity.product_code is None else _normalized(entity.product_code),
                    None if entity.version_label is None else _normalized(entity.version_label),
                    None
                    if entity.filing_or_registration is None
                    else entity.filing_or_registration.kind,
                    None
                    if entity.filing_or_registration is None
                    else _normalized(entity.filing_or_registration.value),
                    row_classification[(entry.material_id, entity.proposal_ref)].schema_pack_id,
                    row_classification[(entry.material_id, entity.proposal_ref)].schema_version,
                    row_classification[(entry.material_id, entity.proposal_ref)].schema_pack_sha256,
                )
                for (entry, _, entity), _ in contenders
            }
            if len(shapes) > 1:
                ambiguous_rows.update(
                    (row[0].material_id, row[2].proposal_ref) for row, _ in contenders
                )

        candidate_by_version: dict[tuple[str, str], EntityCandidateV1] = {}
        for key, rows in eligible_by_version.items():
            qualified = tuple(
                row
                for row in rows
                if (row[0].material_id, row[2].proposal_ref) not in ambiguous_rows
            )
            if not qualified:
                continue
            representative = min(
                qualified, key=lambda item: (item[0].material_id, item[2].proposal_ref)
            )[2]
            evidence_ids = tuple(
                sorted(
                    {
                        evidence_id
                        for _, _, entity in qualified
                        for evidence_id in entity.identity_evidence_ids
                    }
                )
            )
            candidate_by_version[key] = _candidate(
                space_id=exact_corpus.space_id,
                entity=representative,
                evidence_ids=evidence_ids,
            )

        decisions: list[MaterialDecisionV1] = []
        for entry in exact_corpus.entries:
            material_proposal = proposal_by_id.get(entry.material_id)
            source_reasons = material_reasons_by_id[entry.material_id]
            if material_proposal is None:
                decisions.append(
                    _material_decision(
                        entry=entry,
                        proposal=None,
                        children=(),
                        policy=exact_policy,
                        reasons={"MODEL_OUTPUT_MISSING", *source_reasons},
                    )
                )
                continue
            material_reasons = set(source_reasons)
            children: list[EntityDecisionV1] = []
            for entity in material_proposal.entities:
                decision_entity_key = (
                    None
                    if entity.product_code is None
                    else _identity_key(exact_corpus.space_id, entity.product_code)
                )
                decision_version_key = (
                    None
                    if decision_entity_key is None
                    else _version_key(decision_entity_key, entity)
                )
                row_id = (entry.material_id, entity.proposal_ref)
                ambiguous = row_id in ambiguous_rows
                multi_name_ids, multi_code_ids = row_multi_identity_evidence[row_id]
                candidate = (
                    None
                    if decision_entity_key is None or decision_version_key is None
                    else candidate_by_version.get((decision_entity_key, decision_version_key))
                )
                forced = set(material_reasons)
                children.append(
                    _decision(
                        space_id=exact_corpus.space_id,
                        entity=entity,
                        proposal=material_proposal,
                        entry=entry,
                        catalog=exact_catalog,
                        existing=exact_existing,
                        policy=exact_policy,
                        forced_reasons=forced,
                        candidate=candidate,
                        version_ambiguous=ambiguous,
                        multi_identity_name_evidence_ids=multi_name_ids,
                        multi_identity_code_evidence_ids=multi_code_ids,
                    )
                )
            decisions.append(
                _material_decision(
                    entry=entry,
                    proposal=material_proposal,
                    children=tuple(children),
                    policy=exact_policy,
                    reasons=material_reasons,
                )
            )

        ordered = tuple(decisions)
        if compiler_version == COMPILER_VERSION_V2:
            from .g3_evidence_identity_v2 import associate_brochures
            ordered = associate_brochures(ordered, exact_proposals)
        if compiler_version == COMPILER_VERSION_V3:
            from .g3_evidence_identity_v3 import associate_material_groups
            ordered = associate_material_groups(
                ordered, exact_proposals, exact_corpus, exact_existing, exact_policy
            )
        counts = Counter(item.disposition for item in ordered)
        valid_execution_hashes = tuple(
            sorted(
                receipt_by_request[request].execution_receipt_sha256 for request in valid_requests
            )
        )
        payload: dict[str, object] = {
            "contract": "batch-entity-resolution.830.g3.v1",
            "compiler_version": compiler_version,
            "space_id": exact_corpus.space_id,
            "catalog_sha256": exact_catalog.catalog_sha256,
            "corpus_sha256": exact_corpus.corpus_sha256,
            "proposals_sha256": exact_proposals.proposals_sha256,
            "existing_snapshot_sha256": exact_existing.snapshot_sha256,
            "policy_sha256": exact_policy.policy_sha256,
            "model_execution_receipt_sha256s": valid_execution_hashes,
            "decisions": ordered,
            "material_count": len(exact_corpus.entries),
            "resolution_decision_count": len(ordered),
            "model_attempted_count": len(attempted_materials),
            "disposition_counts": DispositionCountsV1(
                MATCH=counts["MATCH"],
                CREATE=counts["CREATE"],
                MULTI=counts["MULTI"],
                NEEDS_CONFIRM=counts["NEEDS_CONFIRM"],
                QUARANTINE=counts["QUARANTINE"],
            ),
        }
        return _hashed(
            BatchEntityResolutionV1,
            object_type="batch-entity-resolution.830.g3.v1",
            hash_field="batch_sha256",
            payload=payload,
        )
    except BatchEntityResolutionError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, ValidationError):
        raise BatchEntityResolutionError("COMPILED_BATCH_INVALID") from None


def validate_batch(payload: str | bytes) -> BatchEntityResolutionV1:
    """Validate a self-contained compiled result without asserting source liveness."""

    try:
        return BatchEntityResolutionV1.model_validate_json(payload)
    except (TypeError, ValueError, ValidationError):
        try:
            json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise BatchEntityResolutionError("INPUT_CONTRACT_INVALID") from None
        raise BatchEntityResolutionError("COMPILED_BATCH_INVALID") from None


__all__ = [
    "ApprovedAliasV1",
    "BatchCorpusV1",
    "BatchEntityResolutionError",
    "BatchEntityResolutionV1",
    "BatchResolutionPolicyV1",
    "CandidateVersionAnchorV1",
    "ClassificationAssignmentV1",
    "ClassificationLabelAssignmentV1",
    "CorpusEntryV1",
    "DispositionCountsV1",
    "EntityCandidateV1",
    "EntityDecisionV1",
    "EntityIdentityAnchorsV1",
    "EntityProposalV1",
    "ExistingEntitySnapshotV1",
    "ExistingEntityV1",
    "LabelProposalV1",
    "MaterialBindingV1",
    "MaterialDecisionV1",
    "MaterialProposalV1",
    "ModelReceiptBindingV1",
    "ObservedNormalizedValueV1",
    "ProposalBatchV1",
    "ProposalEvidenceV1",
    "RegisteredSourceReceipt830G3V1",
    "SourceReceipt830G3",
    "SourceProvenanceV1",
    "TrustRuleV1",
    "VersionAnchorV1",
    "resolve_batch",
    "validate_batch",
]
