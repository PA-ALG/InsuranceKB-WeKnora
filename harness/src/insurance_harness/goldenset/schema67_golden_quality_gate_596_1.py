"""Deterministic Golden quality gate for the single 596-1 Schema67 product."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import threading
import unicodedata
import weakref
from collections import Counter
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Annotated, Final, Literal, Protocol, Self, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.config import HarnessSettings
from insurance_harness.goldenset.expert_golden_admission_596_2 import (
    validate_schema67_candidate_v2,
)
from insurance_harness.knowledge_compiler.medical_schema_pack_596_1 import (
    MEDICAL_VERSION_ID,
    make_medical_schema_pack_596_1,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    APPROVED_ORDERED_FIELD_IDS,
)
from insurance_harness.knowledge_compiler.schema_wiki_candidate_evidence_join_596_1 import (
    CandidateEvidenceAuthorityError,
    Schema67CitationAuthorityJoinReceiptV1,
    Schema67LiveSourceAuthorityV1,
    validate_schema67_candidate_evidence_authority_596_1,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import (
    CitationBBoxV1,
    Schema67GoldenQualityGateReceiptV1,
    schema_wiki_canonical_bytes,
    schema_wiki_sha256,
)

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonBlank = Annotated[StrictStr, StringConstraints(min_length=1, pattern=r"^\S(?:[^\r\n]*\S)?$")]
FieldState = Literal["present", "absent_explicitly", "unknown"]
RiskLevel = Literal["critical", "high", "standard"]
EvaluationStatus = Literal["PASS", "FAIL", "FIXTURE_ONLY"]

_PROVIDER_ZERO_FIXTURE_ID: Final[str] = "schema67-provider-zero-fixture-596-1.v1"
NORMALIZATION_POLICY_SHA256: Final[str] = schema_wiki_sha256(
    "schema67-golden-normalization-policy.v1",
    {"product_version_id": "596-1", "rule": "schema67-nfc-trim-exact.v1"},
)
RISK_POLICY_SHA256: Final[str] = schema_wiki_sha256(
    "schema67-golden-risk-policy.v1",
    {"critical_high_exact": True, "product_version_id": "596-1"},
)
METRIC_POLICY_SHA256: Final[str] = schema_wiki_sha256(
    "schema67-golden-metric-policy.v1",
    {
        "product_version_id": "596-1",
        "state_accuracy_min": "65/67",
        "state_recall_min_ppm": 950_000,
        "present_precision_min_ppm": 950_000,
        "present_recall_min_ppm": 950_000,
        "present_macro_f1_min_ppm": 900_000,
        "wrong_fill_max_ppm": 20_000,
        "hallucinated_fill_max_ppm": 0,
        "evidence_exact_ppm": 1_000_000,
        "bbox_iou_min_ppm": 800_000,
        "bbox_high_risk_iou_min_ppm": 900_000,
    },
)
EVALUATOR_IDENTITY_SHA256: Final[str] = schema_wiki_sha256(
    "schema67-golden-evaluator.v1",
    {
        "implementation": "deterministic-596-1-only.v2",
        "metric_policy_sha256": METRIC_POLICY_SHA256,
        "normalization_policy_sha256": NORMALIZATION_POLICY_SHA256,
        "risk_policy_sha256": RISK_POLICY_SHA256,
    },
)
GOLDEN_DOSSIER_REVIEW_POLICY_SHA256: Final[str] = schema_wiki_sha256(
    "schema67-golden-dossier-review-policy.v1",
    {
        "decision": "approve",
        "human_batch_receipt_version": "1",
        "principal_id": "linyao",
        "product_version_id": "596-1",
        "review_scope": "whole-formal-dossier",
        "subject_domain": "insurancekb.schema67-golden-dossier-human-batch.596-1.v1",
    },
)

GOLDEN_METRIC_IDS: Final[tuple[str, ...]] = (
    "sgq.state.micro_accuracy.v1",
    "sgq.state.macro_recall.v1",
    "sgq.value.present.micro_precision.v1",
    "sgq.value.present.micro_recall.v1",
    "sgq.value.present.macro_f1.v1",
    "sgq.state.absent_to_unknown.v1",
    "sgq.state.unknown_to_absent.v1",
    "sgq.value.wrong_fill_rate.v1",
    "sgq.value.hallucinated_fill_rate.v1",
    "sgq.evidence.document_revision_page_precision.v1",
    "sgq.evidence.field_support_recall.v1",
    "sgq.evidence.bbox_iou.v1",
    "sgq.evidence.highlight_accuracy.v1",
    "sgq.human.high_risk_pass.v1",
    "sgq.human.conflict_resolution_pass.v1",
)


class Schema67GoldenQualityGateError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class HumanBatchDecisionReceiptV1(_FrozenModel):
    """Exact Python mirror of the existing Go named-human receipt wire."""

    version: Literal["1"]
    decision: Literal["approve"]
    principal_id: NonBlank
    tenant_id: Annotated[StrictInt, Field(gt=0)]
    space_id: NonBlank
    raw_kb_id: NonBlank
    wiki_kb_id: NonBlank
    candidate_hash: Sha256Hex
    human_batch_hash: Sha256Hex
    review_policy_hash: Sha256Hex
    issued_at: Annotated[StrictInt, Field(gt=0)]
    expires_at: Annotated[StrictInt, Field(gt=0)]
    nonce: NonBlank
    signer_key_id: NonBlank
    signature: NonBlank

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        try:
            signature = base64.urlsafe_b64decode(self.signature + "=" * (-len(self.signature) % 4))
        except (UnicodeEncodeError, ValueError):
            raise ValueError("human batch signature invalid") from None
        if (
            self.expires_at <= self.issued_at
            or len(signature) != 64
            or base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii") != self.signature
        ):
            raise ValueError("human batch receipt invalid")
        return self


def canonical_human_batch_decision_receipt_v1(
    receipt: HumanBatchDecisionReceiptV1, include_signature: bool
) -> bytes:
    fields = (
        "version",
        "decision",
        "principal_id",
        "tenant_id",
        "space_id",
        "raw_kb_id",
        "wiki_kb_id",
        "candidate_hash",
        "human_batch_hash",
        "review_policy_hash",
        "issued_at",
        "expires_at",
        "nonce",
        "signer_key_id",
    )
    payload = {name: getattr(receipt, name) for name in fields}
    if include_signature:
        payload["signature"] = receipt.signature
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


class Schema67GoldenApprovalV1(_FrozenModel):
    contract: Literal["schema67-golden-approval.v1"]
    domain: Literal["insurancekb.schema67-golden-approval.596-1.v1"]
    action: Literal["approve"]
    principal_id: NonBlank
    golden_set_sha256: Sha256Hex
    golden_version: NonBlank
    product_version_id: Literal["596-1"]
    entity_version_id: Literal["ping-an-e-sheng-bao@596-1"]
    schema_pack_sha256: Sha256Hex
    ordered_field_ids_sha256: Sha256Hex
    source_authorities_sha256: Sha256Hex
    policies_sha256: Sha256Hex
    issued_at: Annotated[StrictInt, Field(gt=0)]
    expires_at: Annotated[StrictInt, Field(gt=0)]
    signer_key_id: NonBlank
    signature: NonBlank
    approval_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_approval(self) -> Self:
        payload = self.model_dump(mode="python", exclude={"approval_sha256"})
        if (
            not self.principal_id.startswith("human:")
            or self.expires_at <= self.issued_at
            or self.approval_sha256 != schema_wiki_sha256(self.contract, payload)
        ):
            raise ValueError("Golden approval invalid")
        try:
            decoded = base64.urlsafe_b64decode(self.signature + "=" * (-len(self.signature) % 4))
        except (ValueError, UnicodeEncodeError):
            raise ValueError("Golden approval signature invalid") from None
        if (
            len(decoded) != 64
            or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != self.signature
        ):
            raise ValueError("Golden approval signature invalid")
        return self


def schema67_golden_approval_signing_bytes(approval: Schema67GoldenApprovalV1) -> bytes:
    payload = approval.model_dump(mode="python", exclude={"signature", "approval_sha256"})
    return b"insurancekb.schema67-golden-approval.596-1.v1\x00" + schema_wiki_canonical_bytes(
        approval.contract, payload
    )


def _golden_approval_bindings(golden: Schema67GoldenSet5961V1) -> tuple[str, str, str]:
    return (
        schema_wiki_sha256(
            "schema67-golden-ordered-fields.v1",
            {"ordered_field_ids": golden.ordered_field_ids},
        ),
        schema_wiki_sha256(
            "schema67-golden-source-authorities.v1",
            {"source_authorities": golden.source_authorities},
        ),
        schema_wiki_sha256(
            "schema67-golden-policies.v1",
            {
                "normalization_policy_sha256": golden.normalization_policy_sha256,
                "risk_policy_sha256": golden.risk_policy_sha256,
                "metric_policy_sha256": golden.metric_policy_sha256,
            },
        ),
    )


class _Schema67GoldenApprovalVerifierV1:
    __slots__ = ("_key_material", "_keys", "_now_epoch")

    def __init__(
        self,
        keys: dict[str, Ed25519PublicKey],
        *,
        now_epoch: int,
    ) -> None:
        self._key_material = MappingProxyType(
            {
                key_id: key.public_bytes(Encoding.Raw, PublicFormat.Raw)
                for key_id, key in keys.items()
            }
        )
        self._keys = MappingProxyType(
            {
                key_id: Ed25519PublicKey.from_public_bytes(material)
                for key_id, material in self._key_material.items()
            }
        )
        self._now_epoch = now_epoch

    def verify(
        self,
        golden: Schema67GoldenSet5961V1,
        approvals: tuple[Schema67GoldenApprovalV1, Schema67GoldenApprovalV1],
    ) -> tuple[Schema67GoldenApprovalV1, Schema67GoldenApprovalV1]:
        if len(approvals) != 2:
            raise Schema67GoldenQualityGateError("GOLDEN_APPROVAL_INVALID")
        ordered_sha, sources_sha, policies_sha = _golden_approval_bindings(golden)
        principals: set[str] = set()
        key_ids: set[str] = set()
        key_materials: set[bytes] = set()
        for approval in approvals:
            if type(approval) is not Schema67GoldenApprovalV1:
                raise Schema67GoldenQualityGateError("GOLDEN_APPROVAL_INVALID")
            key = self._keys.get(approval.signer_key_id)
            key_material = self._key_material.get(approval.signer_key_id)
            expected = (
                golden.golden_set_sha256,
                golden.golden_version,
                golden.product_version_id,
                golden.entity_version_id,
                golden.schema_pack_sha256,
                ordered_sha,
                sources_sha,
                policies_sha,
            )
            actual = (
                approval.golden_set_sha256,
                approval.golden_version,
                approval.product_version_id,
                approval.entity_version_id,
                approval.schema_pack_sha256,
                approval.ordered_field_ids_sha256,
                approval.source_authorities_sha256,
                approval.policies_sha256,
            )
            if (
                key is None
                or key_material is None
                or actual != expected
                or not approval.issued_at <= self._now_epoch < approval.expires_at
                or approval.principal_id in principals
                or approval.signer_key_id in key_ids
                or key_material in key_materials
            ):
                raise Schema67GoldenQualityGateError("GOLDEN_APPROVAL_INVALID")
            try:
                signature = base64.urlsafe_b64decode(
                    approval.signature + "=" * (-len(approval.signature) % 4)
                )
                key.verify(signature, schema67_golden_approval_signing_bytes(approval))
            except (InvalidSignature, ValueError):
                raise Schema67GoldenQualityGateError("GOLDEN_APPROVAL_INVALID") from None
            principals.add(approval.principal_id)
            key_ids.add(approval.signer_key_id)
            key_materials.add(key_material)
        return approvals


class _Schema67QualityGateSignerV1:
    __slots__ = ("key_id", "_private_key")

    def __init__(self, key_id: str, private_key: Ed25519PrivateKey) -> None:
        if not key_id:
            raise ValueError("quality gate signer key id required")
        self.key_id = key_id
        self._private_key = private_key

    def sign(self, payload: Mapping[str, object]) -> str:
        raw = (
            b"insurancekb.schema67-golden-quality-gate-receipt.v1\x00"
            + schema_wiki_canonical_bytes("schema67-golden-quality-gate-receipt.v1", payload)
        )
        return base64.urlsafe_b64encode(self._private_key.sign(raw)).rstrip(b"=").decode("ascii")


class Schema67GoldenQualityEvaluatorSigningCredentialSource:
    """Deployment-owned source for the evaluator's private signing key."""

    def load_ed25519_private_key(self, signer_key_id: str) -> Ed25519PrivateKey:
        raise NotImplementedError


_EVALUATOR_AUTHORITY_CONSTRUCTION_TOKEN: Final[object] = object()
_FIXTURE_PROVENANCE_CONSTRUCTION_TOKEN: Final[object] = object()


class _Schema67ProviderZeroFixtureProvenanceV1:
    """Factory-sealed, non-authoritative provider-zero evaluation provenance."""

    __slots__ = (
        "_sealed",
        "candidate_evidence_authority_sha256",
        "candidate_sha256",
        "fixture_id",
        "provenance_sha256",
    )

    def __init__(
        self,
        construction_token: object,
        *,
        candidate_sha256: str,
        candidate_evidence_authority_sha256: str,
    ) -> None:
        if construction_token is not _FIXTURE_PROVENANCE_CONSTRUCTION_TOKEN:
            raise Schema67GoldenQualityGateError(
                "PROVIDER_ZERO_FIXTURE_PROVENANCE_INVALID"
            )
        payload = {
            "contract": "schema67-provider-zero-fixture-provenance.v1",
            "fixture_id": _PROVIDER_ZERO_FIXTURE_ID,
            "product_version_id": "596-1",
            "candidate_sha256": candidate_sha256,
            "candidate_evidence_authority_sha256": (
                candidate_evidence_authority_sha256
            ),
        }
        object.__setattr__(self, "fixture_id", _PROVIDER_ZERO_FIXTURE_ID)
        object.__setattr__(self, "candidate_sha256", candidate_sha256)
        object.__setattr__(
            self,
            "candidate_evidence_authority_sha256",
            candidate_evidence_authority_sha256,
        )
        object.__setattr__(
            self,
            "provenance_sha256",
            schema_wiki_sha256(
                "schema67-provider-zero-fixture-provenance.v1", payload
            ),
        )
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("Schema67 provider-zero fixture provenance is sealed")
        object.__setattr__(self, name, value)


class _Schema67ProviderZeroFixtureProvenanceFields(Protocol):
    fixture_id: str
    candidate_sha256: str
    candidate_evidence_authority_sha256: str
    provenance_sha256: str


def _require_provider_zero_fixture_provenance_596_1(
    provenance: object,
    *,
    candidate_sha256: str,
    candidate_evidence_authority_sha256: str,
) -> _Schema67ProviderZeroFixtureProvenanceV1:
    try:
        if type(provenance) is not _Schema67ProviderZeroFixtureProvenanceV1:
            raise TypeError
        exact_provenance = cast(_Schema67ProviderZeroFixtureProvenanceFields, provenance)
        payload = {
            "contract": "schema67-provider-zero-fixture-provenance.v1",
            "fixture_id": _PROVIDER_ZERO_FIXTURE_ID,
            "product_version_id": "596-1",
            "candidate_sha256": candidate_sha256,
            "candidate_evidence_authority_sha256": (
                candidate_evidence_authority_sha256
            ),
        }
        if (
            exact_provenance.fixture_id != _PROVIDER_ZERO_FIXTURE_ID
            or exact_provenance.candidate_sha256 != candidate_sha256
            or exact_provenance.candidate_evidence_authority_sha256
            != candidate_evidence_authority_sha256
            or exact_provenance.provenance_sha256
            != schema_wiki_sha256(
                "schema67-provider-zero-fixture-provenance.v1", payload
            )
        ):
            raise ValueError
        return provenance
    except (AttributeError, TypeError, ValueError):
        raise Schema67GoldenQualityGateError(
            "PROVIDER_ZERO_FIXTURE_PROVENANCE_INVALID"
        ) from None


def make_schema67_provider_zero_fixture_provenance_596_1(
    *,
    candidate: object,
    evidence_authority: object,
) -> _Schema67ProviderZeroFixtureProvenanceV1:
    """Bind one exact Candidate/authority pair to non-authoritative fixture use."""

    try:
        exact_candidate = validate_schema67_candidate_v2(candidate)
        exact_authority = validate_schema67_candidate_evidence_authority_596_1(
            candidate=exact_candidate,
            authority=evidence_authority,
        )
    except (CandidateEvidenceAuthorityError, TypeError, ValueError, ValidationError):
        raise Schema67GoldenQualityGateError(
            "PROVIDER_ZERO_FIXTURE_PROVENANCE_INVALID"
        ) from None
    return _Schema67ProviderZeroFixtureProvenanceV1(
        _FIXTURE_PROVENANCE_CONSTRUCTION_TOKEN,
        candidate_sha256=exact_candidate.candidate_sha256,
        candidate_evidence_authority_sha256=exact_authority.authority_sha256,
    )


class Schema67GoldenQualityEvaluatorAuthority:
    """Sealed evaluator composed once from deployment-owned trust material."""

    _approval_verifier: _Schema67GoldenApprovalVerifierV1
    _quality_gate_signer: _Schema67QualityGateSignerV1
    _sealed: bool
    __slots__ = ("_approval_verifier", "_quality_gate_signer", "_sealed")

    def __init__(
        self,
        construction_token: object,
        approval_verifier: _Schema67GoldenApprovalVerifierV1,
        quality_gate_signer: _Schema67QualityGateSignerV1,
    ) -> None:
        if construction_token is not _EVALUATOR_AUTHORITY_CONSTRUCTION_TOKEN:
            raise Schema67GoldenQualityGateError("GOLDEN_EVALUATOR_AUTHORITY_UNAVAILABLE")
        object.__setattr__(self, "_approval_verifier", approval_verifier)
        object.__setattr__(self, "_quality_gate_signer", quality_gate_signer)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("Schema67 Golden evaluator authority is sealed")
        object.__setattr__(self, name, value)

    def evaluate(
        self,
        *,
        candidate: object,
        evidence_authority: object,
        golden: Schema67GoldenSet5961V1,
        golden_approvals: tuple[Schema67GoldenApprovalV1, Schema67GoldenApprovalV1],
    ) -> Schema67GoldenEvaluationResultV1:
        return _evaluate_schema67_golden_quality_596_1(
            candidate=candidate,
            evidence_authority=evidence_authority,
            golden=golden,
            golden_approvals=golden_approvals,
            golden_approval_verifier=self._approval_verifier,
            quality_gate_signer=self._quality_gate_signer,
            fixture_provenance=None,
            require_fixture_provenance=False,
        )

    def evaluate_provider_zero_fixture(
        self,
        *,
        candidate: object,
        evidence_authority: object,
        fixture_provenance: object,
        golden: Schema67GoldenSet5961V1,
        golden_approvals: tuple[Schema67GoldenApprovalV1, Schema67GoldenApprovalV1],
    ) -> Schema67GoldenEvaluationResultV1:
        return _evaluate_schema67_golden_quality_596_1(
            candidate=candidate,
            evidence_authority=evidence_authority,
            golden=golden,
            golden_approvals=golden_approvals,
            golden_approval_verifier=self._approval_verifier,
            quality_gate_signer=self._quality_gate_signer,
            fixture_provenance=fixture_provenance,
            require_fixture_provenance=True,
        )


def _decode_ed25519_public_key_text(value: str) -> bytes:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, UnicodeEncodeError):
        raise Schema67GoldenQualityGateError("GOLDEN_APPROVER_KEY_RING_INVALID") from None
    if (
        len(decoded) != 32
        or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value
    ):
        raise Schema67GoldenQualityGateError("GOLDEN_APPROVER_KEY_RING_INVALID")
    return bytes(decoded)


def compose_schema67_golden_quality_evaluator_authority_596_1(
    *,
    signer_credential_source: Schema67GoldenQualityEvaluatorSigningCredentialSource | None,
    now_epoch: int,
) -> Schema67GoldenQualityEvaluatorAuthority:
    """Compose the single 596-1 evaluator from deployment-owned configuration."""

    try:
        settings = HarnessSettings()  # type: ignore[call-arg]
    except ValidationError:
        raise Schema67GoldenQualityGateError("GOLDEN_EVALUATOR_AUTHORITY_UNAVAILABLE") from None

    return _compose_schema67_golden_quality_evaluator_authority_596_1(
        settings=settings,
        signer_credential_source=signer_credential_source,
        now_epoch=now_epoch,
    )


def _compose_schema67_golden_quality_evaluator_authority_596_1(
    *,
    settings: HarnessSettings,
    signer_credential_source: Schema67GoldenQualityEvaluatorSigningCredentialSource | None,
    now_epoch: int,
) -> Schema67GoldenQualityEvaluatorAuthority:

    if (
        signer_credential_source is None
        or not isinstance(
            signer_credential_source,
            Schema67GoldenQualityEvaluatorSigningCredentialSource,
        )
        or len(settings.schema67_golden_approver_public_keys) != 2
        or not settings.schema67_golden_evaluator_signer_key_id
        or not settings.schema67_golden_evaluator_public_key_base64
        or now_epoch <= 0
    ):
        raise Schema67GoldenQualityGateError("GOLDEN_EVALUATOR_AUTHORITY_UNAVAILABLE")

    key_material: dict[str, bytes] = {}
    for key_id, encoded in settings.schema67_golden_approver_public_keys:
        if (
            not key_id
            or key_id != key_id.strip()
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in key_id)
        ):
            raise Schema67GoldenQualityGateError("GOLDEN_APPROVER_KEY_RING_INVALID")
        if key_id in key_material:
            raise Schema67GoldenQualityGateError("GOLDEN_APPROVER_KEY_RING_INVALID")
        material = _decode_ed25519_public_key_text(encoded)
        if material in key_material.values():
            raise Schema67GoldenQualityGateError("GOLDEN_APPROVER_KEY_RING_INVALID")
        key_material[key_id] = material

    signer_key_id = settings.schema67_golden_evaluator_signer_key_id
    if signer_key_id != signer_key_id.strip() or any(
        ord(char) < 0x20 or ord(char) == 0x7F for char in signer_key_id
    ):
        raise Schema67GoldenQualityGateError("GOLDEN_EVALUATOR_AUTHORITY_UNAVAILABLE")
    evaluator_public_material = _decode_ed25519_public_key_text(
        settings.schema67_golden_evaluator_public_key_base64
    )
    if signer_key_id in key_material or evaluator_public_material in key_material.values():
        raise Schema67GoldenQualityGateError("GOLDEN_EVALUATOR_AUTHORITY_UNAVAILABLE")
    try:
        private_key = signer_credential_source.load_ed25519_private_key(signer_key_id)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise TypeError
        actual_public_material = private_key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )
    except Exception:
        raise Schema67GoldenQualityGateError("GOLDEN_EVALUATOR_AUTHORITY_UNAVAILABLE") from None
    if actual_public_material != evaluator_public_material:
        raise Schema67GoldenQualityGateError("GOLDEN_EVALUATOR_AUTHORITY_UNAVAILABLE")

    verifier = _Schema67GoldenApprovalVerifierV1(
        {
            key_id: Ed25519PublicKey.from_public_bytes(material)
            for key_id, material in key_material.items()
        },
        now_epoch=now_epoch,
    )
    signer = _Schema67QualityGateSignerV1(signer_key_id, private_key)
    return Schema67GoldenQualityEvaluatorAuthority(
        _EVALUATOR_AUTHORITY_CONSTRUCTION_TOKEN,
        verifier,
        signer,
    )


class Schema67GoldenEvidenceTargetV1(_FrozenModel):
    contract: Literal["schema67-golden-evidence-target.v1"]
    source_role: Literal["terms", "brochure", "rate_table"]
    live_revision_source_receipt_sha256: Sha256Hex
    revision_source_id: Sha256Hex
    knowledge_id: NonBlank
    evidence_parse_attempt_id: NonBlank
    weknora_parse_attempt: Annotated[StrictInt, Field(gt=0)]
    file_sha256: Sha256Hex
    parsed_document_sha256: Sha256Hex
    parse_manifest_sha256: Sha256Hex
    weknora_manifest_algorithm: Literal["weknora.chunk_manifest.v1"]
    weknora_manifest_digest: Sha256Hex
    chunk_id: NonBlank
    page_number: Annotated[StrictInt, Field(gt=0)]
    locator_kind: Literal["page", "block", "table", "cell"]
    locator_ref: NonBlank
    quote_sha256: Sha256Hex
    content_sha256: Sha256Hex
    bbox_evaluation: Literal["required", "not_evaluable"]
    coordinate_space: Literal["normalized_0_1e6"] | None
    bbox: CitationBBoxV1 | None
    page_width: Annotated[StrictInt, Field(gt=0)] | None
    page_height: Annotated[StrictInt, Field(gt=0)] | None
    rotation_degrees: Literal[0, 90, 180, 270] | None
    target_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        required = self.bbox_evaluation == "required"
        bbox_fields = (
            self.coordinate_space,
            self.bbox,
            self.page_width,
            self.page_height,
            self.rotation_degrees,
        )
        if required != all(item is not None for item in bbox_fields):
            raise ValueError("bbox evaluation custody mismatch")
        if not required and any(item is not None for item in bbox_fields):
            raise ValueError("not-evaluable bbox must remain absent")
        payload = self.model_dump(mode="python", exclude={"target_sha256"})
        if self.target_sha256 != schema_wiki_sha256(self.contract, payload):
            raise ValueError("golden evidence target hash mismatch")
        return self


class Schema67GoldenFieldV1(_FrozenModel):
    contract: Literal["schema67-golden-field.v1"]
    field_id: NonBlank
    state: FieldState
    value_schema: Literal["scalar", "ordered_list", "unordered_set", "range", "structured"]
    canonical_value: NonBlank | None
    accepted_values: tuple[NonBlank, ...]
    normalization_rule_id: Literal["schema67-nfc-trim-exact.v1"]
    evidence_targets: tuple[Schema67GoldenEvidenceTargetV1, ...]
    risk_level: RiskLevel
    conflict_status: Literal["agreed", "resolved"]
    annotator_decision_sha256s: tuple[Sha256Hex, Sha256Hex]
    adjudication_sha256: Sha256Hex | None
    field_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_field(self) -> Self:
        known = self.state != "unknown"
        if known:
            if (
                self.canonical_value is None
                or not self.accepted_values
                or self.canonical_value not in self.accepted_values
                or not self.evidence_targets
            ):
                raise ValueError("known Golden field lacks value or evidence")
        elif self.canonical_value is not None or self.accepted_values or self.evidence_targets:
            raise ValueError("unknown Golden field carries value or evidence")
        if len(set(self.annotator_decision_sha256s)) != 2:
            raise ValueError("independent annotator decisions required")
        if (self.conflict_status == "resolved") != (self.adjudication_sha256 is not None):
            raise ValueError("conflict adjudication mismatch")
        if known:
            for value in self.accepted_values:
                _normalized_atoms(self.value_schema, value)
        payload = self.model_dump(mode="python", exclude={"field_sha256"})
        if self.field_sha256 != schema_wiki_sha256(self.contract, payload):
            raise ValueError("Golden field hash mismatch")
        return self


class Schema67GoldenSet5961V1(_FrozenModel):
    contract: Literal["schema67-golden-set-596-1.v1"]
    golden_id: NonBlank
    golden_version: NonBlank
    product_version_id: Literal["596-1"]
    entity_version_id: Literal["ping-an-e-sheng-bao@596-1"]
    schema_pack_id: Literal["medical-schema67.v1"]
    schema_pack_sha256: Sha256Hex
    ordered_field_ids: tuple[NonBlank, ...]
    source_authorities: tuple[Schema67LiveSourceAuthorityV1, ...]
    fields: tuple[Schema67GoldenFieldV1, ...]
    annotator_principal_ids: tuple[NonBlank, NonBlank]
    whole_batch_approval_receipt_sha256: Sha256Hex
    normalization_policy_sha256: Sha256Hex = NORMALIZATION_POLICY_SHA256
    risk_policy_sha256: Sha256Hex = RISK_POLICY_SHA256
    metric_policy_sha256: Sha256Hex = METRIC_POLICY_SHA256
    golden_set_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_golden(self) -> Self:
        pack = make_medical_schema_pack_596_1()
        if (
            self.entity_version_id != MEDICAL_VERSION_ID
            or self.schema_pack_id != pack.schema_pack_id
            or self.schema_pack_sha256 != pack.schema_pack_sha256
            or self.ordered_field_ids != APPROVED_ORDERED_FIELD_IDS
            or tuple(item.field_id for item in self.fields) != APPROVED_ORDERED_FIELD_IDS
            or tuple(item.source_role for item in self.source_authorities)
            != ("terms", "brochure", "rate_table")
            or len(set(self.annotator_principal_ids)) != 2
            or any(not item.startswith("human:") for item in self.annotator_principal_ids)
            or self.normalization_policy_sha256 != NORMALIZATION_POLICY_SHA256
            or self.risk_policy_sha256 != RISK_POLICY_SHA256
            or self.metric_policy_sha256 != METRIC_POLICY_SHA256
        ):
            raise ValueError("Golden authority identity mismatch")
        if any(
            row.source_sha256 != row.live_revision_source_receipt.file_sha256
            for row in self.source_authorities
        ):
            raise ValueError("Golden source revision mismatch")
        source_by_role = {row.source_role: row for row in self.source_authorities}
        for field in self.fields:
            for target in field.evidence_targets:
                source = source_by_role.get(target.source_role)
                if source is None or (
                    target.live_revision_source_receipt_sha256
                    != source.live_revision_source_receipt.source_receipt_sha256
                    or target.revision_source_id
                    != source.live_revision_source_receipt.revision_source_id
                    or target.knowledge_id != source.live_revision_source_receipt.knowledge_id
                    or target.weknora_parse_attempt
                    != source.live_revision_source_receipt.weknora_parse_attempt
                    or target.file_sha256 != source.source_sha256
                    or target.weknora_manifest_algorithm
                    != source.live_revision_source_receipt.weknora_manifest_algorithm
                    or target.weknora_manifest_digest
                    != source.live_revision_source_receipt.weknora_manifest_digest
                ):
                    raise ValueError("Golden evidence source authority mismatch")
        payload = self.model_dump(mode="python", exclude={"golden_set_sha256"})
        if self.golden_set_sha256 != schema_wiki_sha256(self.contract, payload):
            raise ValueError("Golden set hash mismatch")
        return self


class Schema67GoldenFieldDecisionV1(_FrozenModel):
    field_id: NonBlank
    golden_field_sha256: Sha256Hex
    candidate_state: FieldState
    golden_state: FieldState
    state_correct: bool
    value_correct: bool
    atom_true_positive: StrictInt
    atom_false_positive: StrictInt
    atom_false_negative: StrictInt
    atom_f1_ppm: Annotated[StrictInt, Field(ge=0, le=1_000_000)]
    evidence_fragments: StrictInt
    evidence_fragments_matched: StrictInt
    bbox_required: StrictInt
    bbox_passed: StrictInt
    bbox_iou_ppm_values: tuple[Annotated[StrictInt, Field(ge=0, le=1_000_000)], ...]
    high_risk_pass: bool
    conflict_resolved: bool
    decision_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        payload = self.model_dump(mode="python", exclude={"decision_sha256"})
        if (
            min(
                self.evidence_fragments,
                self.evidence_fragments_matched,
                self.atom_true_positive,
                self.atom_false_positive,
                self.atom_false_negative,
                self.bbox_required,
                self.bbox_passed,
            )
            < 0
            or self.evidence_fragments_matched > self.evidence_fragments
            or self.bbox_passed > self.bbox_required
            or len(self.bbox_iou_ppm_values) != self.bbox_required
            or self.decision_sha256
            != schema_wiki_sha256("schema67-golden-field-decision.v1", payload)
        ):
            raise ValueError("field decision invalid")
        return self


class Schema67GoldenMetricV1(_FrozenModel):
    metric_id: NonBlank
    numerator: StrictInt | None
    denominator: StrictInt | None
    value_ppm: Annotated[StrictInt, Field(ge=0, le=1_000_000)] | None
    supports: tuple[StrictInt, ...]
    evaluability: Literal["EVALUABLE", "NOT_EVALUABLE"]
    sample_size: Literal["SMALL_SAMPLE", "ADEQUATE", "NOT_EVALUABLE"]
    wilson_low_ppm: Annotated[StrictInt, Field(ge=0, le=1_000_000)] | None
    wilson_high_ppm: Annotated[StrictInt, Field(ge=0, le=1_000_000)] | None
    admission_status: Literal["PASS", "FAIL"]
    metric_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_metric(self) -> Self:
        evaluable = self.evaluability == "EVALUABLE"
        if evaluable != (
            self.numerator is not None
            and self.denominator is not None
            and self.denominator > 0
            and self.value_ppm is not None
        ):
            raise ValueError("metric denominator missing")
        if not evaluable and any(
            item is not None
            for item in (
                self.numerator,
                self.denominator,
                self.value_ppm,
                self.wilson_low_ppm,
                self.wilson_high_ppm,
            )
        ):
            raise ValueError("not-evaluable metric carries a value")
        payload = self.model_dump(mode="python", exclude={"metric_sha256"})
        if self.metric_sha256 != schema_wiki_sha256("schema67-golden-metric.v1", payload):
            raise ValueError("metric hash mismatch")
        return self


class Schema67GoldenPrivateDossierV1(_FrozenModel):
    contract: Literal["schema67-golden-private-dossier.v1"]
    candidate_sha256: Sha256Hex
    candidate_evidence_authority_sha256: Sha256Hex
    golden_set_sha256: Sha256Hex
    field_decisions: tuple[Schema67GoldenFieldDecisionV1, ...]
    metrics: tuple[Schema67GoldenMetricV1, ...]
    status: EvaluationStatus
    reason_codes: tuple[NonBlank, ...]
    dossier_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_dossier(self) -> Self:
        payload = self.model_dump(mode="python", exclude={"dossier_sha256"})
        if (
            tuple(row.field_id for row in self.field_decisions) != APPROVED_ORDERED_FIELD_IDS
            or tuple(row.metric_id for row in self.metrics) != GOLDEN_METRIC_IDS
            or self.dossier_sha256 != schema_wiki_sha256(self.contract, payload)
        ):
            raise ValueError("private dossier mismatch")
        return self


class Schema67GoldenPublicAggregateV1(_FrozenModel):
    contract: Literal["schema67-golden-public-aggregate.v1"]
    product_version_id: Literal["596-1"]
    candidate_sha256: Sha256Hex
    golden_set_sha256: Sha256Hex
    evaluator_identity_sha256: Sha256Hex
    metrics: tuple[Schema67GoldenMetricV1, ...]
    status: EvaluationStatus
    reason_codes: tuple[NonBlank, ...]
    aggregate_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_aggregate(self) -> Self:
        payload = self.model_dump(mode="python", exclude={"aggregate_sha256"})
        if (
            tuple(row.metric_id for row in self.metrics) != GOLDEN_METRIC_IDS
            or self.evaluator_identity_sha256 != EVALUATOR_IDENTITY_SHA256
            or self.aggregate_sha256 != schema_wiki_sha256(self.contract, payload)
        ):
            raise ValueError("public aggregate mismatch")
        return self


class Schema67GoldenEvaluationResultV1(_FrozenModel):
    status: EvaluationStatus
    private_dossier: Schema67GoldenPrivateDossierV1
    public_aggregate: Schema67GoldenPublicAggregateV1
    quality_gate_receipt: Schema67GoldenQualityGateReceiptV1 | None
    provider_calls: Literal[0] = 0
    draft_calls: Literal[0] = 0
    review_calls: Literal[0] = 0
    activation_calls: Literal[0] = 0


class Schema67GoldenEvaluationReviewBundleV1(_FrozenModel):
    contract: Literal["schema67-golden-evaluation-review-bundle.v1"]
    evaluation_id: Sha256Hex
    quality_gate_receipt: Schema67GoldenQualityGateReceiptV1
    public_aggregate: Schema67GoldenPublicAggregateV1
    private_dossier: Schema67GoldenPrivateDossierV1
    evaluation_bundle_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_evaluation_bundle(self) -> Self:
        receipt = self.quality_gate_receipt
        public = self.public_aggregate
        private = self.private_dossier
        payload = self.model_dump(mode="python", exclude={"evaluation_bundle_sha256"})
        if (
            self.evaluation_id != receipt.receipt_sha256
            or receipt.status != "PASS"
            or public.status != "PASS"
            or private.status != "PASS"
            or public.reason_codes
            or private.reason_codes
            or receipt.candidate_sha256 != public.candidate_sha256
            or receipt.candidate_sha256 != private.candidate_sha256
            or receipt.candidate_evidence_authority_sha256
            != private.candidate_evidence_authority_sha256
            or receipt.golden_set_sha256 != public.golden_set_sha256
            or receipt.golden_set_sha256 != private.golden_set_sha256
            or receipt.evaluator_identity_sha256 != public.evaluator_identity_sha256
            or receipt.ordered_field_decision_sha256s
            != tuple(row.decision_sha256 for row in private.field_decisions)
            or receipt.metric_receipt_sha256s != tuple(row.metric_sha256 for row in public.metrics)
            or public.metrics != private.metrics
            or receipt.private_dossier_sha256 != private.dossier_sha256
            or receipt.public_aggregate_sha256 != public.aggregate_sha256
            or self.evaluation_bundle_sha256 != schema_wiki_sha256(self.contract, payload)
        ):
            raise ValueError("Golden evaluation review bundle mismatch")
        return self


class Schema67GoldenReviewValueV1(_FrozenModel):
    mode: Literal["LITERAL", "SHA256_ONLY", "NONE"]
    literal: StrictStr | None
    sha256: Sha256Hex | None

    @model_validator(mode="after")
    def validate_value(self) -> Self:
        if self.mode == "NONE":
            if self.literal is not None or self.sha256 is not None:
                raise ValueError("review value NONE carries data")
            return self
        if self.mode == "SHA256_ONLY":
            if self.literal is not None or self.sha256 is None:
                raise ValueError("review value digest mismatch")
            return self
        if self.literal is None or self.sha256 != schema_wiki_sha256(
            "schema67-golden-review-value.v1", {"literal": self.literal}
        ):
            raise ValueError("review literal hash mismatch")
        return self


class Schema67GoldenEvidenceChangeV1(_FrozenModel):
    change_kind: Literal["ADDED", "REMOVED", "REPLACED", "UNCHANGED"]
    candidate_evidence_id: Sha256Hex | None
    golden_evidence_sha256: Sha256Hex | None
    change_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_change(self) -> Self:
        if self.change_kind == "ADDED":
            valid_shape = (
                self.candidate_evidence_id is not None and self.golden_evidence_sha256 is None
            )
        elif self.change_kind == "REMOVED":
            valid_shape = (
                self.candidate_evidence_id is None and self.golden_evidence_sha256 is not None
            )
        else:
            valid_shape = (
                self.candidate_evidence_id is not None and self.golden_evidence_sha256 is not None
            )
        payload = self.model_dump(mode="python", exclude={"change_sha256"})
        if not valid_shape or self.change_sha256 != schema_wiki_sha256(
            "schema67-golden-evidence-change.v1", payload
        ):
            raise ValueError("review evidence change mismatch")
        return self


class Schema67GoldenReviewFieldMetadataV1(_FrozenModel):
    field_id: NonBlank
    decision_sha256: Sha256Hex
    candidate_state: FieldState
    golden_state: FieldState
    candidate_value: Schema67GoldenReviewValueV1
    golden_value: Schema67GoldenReviewValueV1
    value_comparison: Literal["MATCH", "DIFF", "NOT_COMPARABLE"]
    evidence_changes: tuple[Schema67GoldenEvidenceChangeV1, ...]
    risk_status: Literal["PASS", "HIGH_RISK_PENDING"]
    conflict_status: Literal["RESOLVED", "PENDING"]
    review_status: Literal["REVIEWED", "PENDING_RESIDUAL"]
    reason_codes: tuple[NonBlank, ...]
    field_metadata_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_field_metadata(self) -> Self:
        payload = self.model_dump(mode="python", exclude={"field_metadata_sha256"})
        if (
            self.review_status != "REVIEWED"
            or self.reason_codes
            or self.risk_status != "PASS"
            or self.conflict_status != "RESOLVED"
            or self.field_metadata_sha256
            != schema_wiki_sha256("schema67-golden-review-field-metadata.v1", payload)
        ):
            raise ValueError("formal review field metadata mismatch")
        return self


class Schema67GoldenAnnotationLayerV1(_FrozenModel):
    contract: Literal["schema67-annotation-layer.v1"]
    annotator_model_id: Literal["claude-fable-5"]
    annotation_receipt_sha256: Sha256Hex


class Schema67GoldenHumanReviewLayerV1(_FrozenModel):
    contract: Literal["schema67-human-review-layer.v1"]
    reviewed_by: Literal["linyao"]
    reviewed_at: NonBlank
    receipt_status: Literal["VERIFIED"]
    review_receipt_sha256: Sha256Hex


class Schema67GoldenReviewSuccessorMetadataV1(_FrozenModel):
    contract: Literal["schema67-golden-review-successor-metadata.v1"]
    authority_level: Literal["REAL_NAMED_HUMAN"]
    candidate_sha256: Sha256Hex
    golden_set_sha256: Sha256Hex
    quality_gate_receipt_sha256: Sha256Hex
    evaluation_bundle_sha256: Sha256Hex
    golden_version: NonBlank
    annotation_layer: Schema67GoldenAnnotationLayerV1
    human_review_layer: Schema67GoldenHumanReviewLayerV1
    ordered_fields: tuple[Schema67GoldenReviewFieldMetadataV1, ...]
    metadata_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_metadata(self) -> Self:
        payload = self.model_dump(mode="python", exclude={"metadata_sha256"})
        if tuple(
            row.field_id for row in self.ordered_fields
        ) != APPROVED_ORDERED_FIELD_IDS or self.metadata_sha256 != schema_wiki_sha256(
            "schema67-golden-review-successor-metadata.v1", payload
        ):
            raise ValueError("review successor metadata mismatch")
        return self


class SchemaWikiGoldenQualityDossierV2(_FrozenModel):
    version: Literal["schema-wiki-golden-quality-dossier.v2"]
    preparation_id: NonBlank
    evaluation_id: Sha256Hex
    quality_gate_receipt_sha256: Sha256Hex
    private_dossier: Schema67GoldenPrivateDossierV1
    review_successor: Schema67GoldenReviewSuccessorMetadataV1
    evaluation_bundle_sha256: Sha256Hex
    serving_effect: Literal["NONE"]


def _review_value(value: str | None) -> Schema67GoldenReviewValueV1:
    if value is None:
        return Schema67GoldenReviewValueV1(mode="NONE", literal=None, sha256=None)
    return Schema67GoldenReviewValueV1(
        mode="LITERAL",
        literal=value,
        sha256=schema_wiki_sha256("schema67-golden-review-value.v1", {"literal": value}),
    )


def _evidence_change(
    *, candidate_evidence_id: str | None, golden_evidence_sha256: str | None
) -> Schema67GoldenEvidenceChangeV1:
    if candidate_evidence_id is None:
        kind = "REMOVED"
    elif golden_evidence_sha256 is None:
        kind = "ADDED"
    else:
        kind = "UNCHANGED"
    payload = {
        "change_kind": kind,
        "candidate_evidence_id": candidate_evidence_id,
        "golden_evidence_sha256": golden_evidence_sha256,
    }
    return Schema67GoldenEvidenceChangeV1.model_validate(
        {
            **payload,
            "change_sha256": schema_wiki_sha256("schema67-golden-evidence-change.v1", payload),
        }
    )


def _make_review_successor_metadata(
    *,
    evaluation: Schema67GoldenEvaluationReviewBundleV1,
    candidate: object,
    evidence_authority: object,
    golden: Schema67GoldenSet5961V1,
    annotator_model_id: str,
    annotation_receipt_sha256: str,
    reviewed_by: str,
    reviewed_at: str,
    review_receipt_sha256: str,
) -> Schema67GoldenReviewSuccessorMetadataV1:
    exact_candidate = validate_schema67_candidate_v2(candidate)
    exact_evidence_authority = validate_schema67_candidate_evidence_authority_596_1(
        candidate=candidate, authority=evidence_authority
    )
    if (
        annotator_model_id != "claude-fable-5"
        or reviewed_by != "linyao"
        or evaluation.quality_gate_receipt.candidate_sha256 != exact_candidate.candidate_sha256
        or evaluation.quality_gate_receipt.golden_set_sha256 != golden.golden_set_sha256
        or evaluation.quality_gate_receipt.candidate_evidence_authority_sha256
        != exact_evidence_authority.authority_sha256
        or golden.ordered_field_ids != exact_candidate.ordered_field_ids
    ):
        raise ValueError("review successor authority mismatch")
    candidate_by_field = {row.field_id: row for row in exact_candidate.fields}
    joins_by_field: dict[str, list[Schema67CitationAuthorityJoinReceiptV1]] = {}
    for join in exact_evidence_authority.join_receipts:
        joins_by_field.setdefault(join.field_id, []).append(join)
    decisions = {row.field_id: row for row in evaluation.private_dossier.field_decisions}
    rows: list[Schema67GoldenReviewFieldMetadataV1] = []
    for golden_field in golden.fields:
        candidate_field = candidate_by_field[golden_field.field_id]
        decision = decisions[golden_field.field_id]
        candidate_joins = joins_by_field.get(golden_field.field_id, [])
        target_digests = [target.target_sha256 for target in golden_field.evidence_targets]
        changes = tuple(
            _evidence_change(
                candidate_evidence_id=(
                    candidate_joins[index].receipt_sha256 if index < len(candidate_joins) else None
                ),
                golden_evidence_sha256=(
                    target_digests[index] if index < len(target_digests) else None
                ),
            )
            for index in range(max(len(candidate_joins), len(target_digests)))
        )
        candidate_value = _review_value(candidate_field.value_snapshot)
        golden_value = _review_value(golden_field.canonical_value)
        comparison = (
            "NOT_COMPARABLE"
            if candidate_field.state == "unknown" or golden_field.state == "unknown"
            else "MATCH"
            if candidate_field.state == golden_field.state
            and candidate_field.value_snapshot == golden_field.canonical_value
            else "DIFF"
        )
        field_payload = {
            "field_id": golden_field.field_id,
            "decision_sha256": decision.decision_sha256,
            "candidate_state": candidate_field.state,
            "golden_state": golden_field.state,
            "candidate_value": candidate_value,
            "golden_value": golden_value,
            "value_comparison": comparison,
            "evidence_changes": changes,
            "risk_status": "PASS",
            "conflict_status": "RESOLVED",
            "review_status": "REVIEWED",
            "reason_codes": (),
        }
        rows.append(
            Schema67GoldenReviewFieldMetadataV1.model_validate(
                {
                    **field_payload,
                    "field_metadata_sha256": schema_wiki_sha256(
                        "schema67-golden-review-field-metadata.v1", field_payload
                    ),
                }
            )
        )
    payload = {
        "contract": "schema67-golden-review-successor-metadata.v1",
        "authority_level": "REAL_NAMED_HUMAN",
        "candidate_sha256": exact_candidate.candidate_sha256,
        "golden_set_sha256": golden.golden_set_sha256,
        "quality_gate_receipt_sha256": evaluation.quality_gate_receipt.receipt_sha256,
        "evaluation_bundle_sha256": evaluation.evaluation_bundle_sha256,
        "golden_version": golden.golden_version,
        "annotation_layer": Schema67GoldenAnnotationLayerV1(
            contract="schema67-annotation-layer.v1",
            annotator_model_id="claude-fable-5",
            annotation_receipt_sha256=annotation_receipt_sha256,
        ),
        "human_review_layer": Schema67GoldenHumanReviewLayerV1(
            contract="schema67-human-review-layer.v1",
            reviewed_by="linyao",
            reviewed_at=reviewed_at,
            receipt_status="VERIFIED",
            review_receipt_sha256=review_receipt_sha256,
        ),
        "ordered_fields": tuple(rows),
    }
    return Schema67GoldenReviewSuccessorMetadataV1.model_validate(
        {
            **payload,
            "metadata_sha256": schema_wiki_sha256(
                "schema67-golden-review-successor-metadata.v1", payload
            ),
        }
    )


def _schema67_dossier_scope(evidence_authority: object) -> tuple[int, str, str, str]:
    source_scopes = {
        (
            row.live_revision_source_receipt.tenant_id,
            row.live_revision_source_receipt.space_id,
            row.live_revision_source_receipt.raw_kb_id,
            row.live_revision_source_receipt.wiki_kb_id,
        )
        for row in evidence_authority.source_authorities  # type: ignore[attr-defined]
    }
    if len(source_scopes) != 1:
        raise Schema67GoldenQualityGateError("GOLDEN_DOSSIER_REVIEW_RECEIPT_INVALID")
    return next(iter(source_scopes))


def _require_sha256(value: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise Schema67GoldenQualityGateError("GOLDEN_DOSSIER_REVIEW_RECEIPT_INVALID")
    return value


def schema67_golden_dossier_review_subject_preimage_596_1(
    *,
    result: Schema67GoldenEvaluationResultV1,
    evaluation: Schema67GoldenEvaluationReviewBundleV1,
    candidate: object,
    evidence_authority: object,
    golden: Schema67GoldenSet5961V1,
    mapping_sha256: str,
    golden_artifact_sha256: str,
    status_vector_sha256: str,
    attestation_sha256: str,
    annotator_model_id: str,
    annotation_receipt_sha256: str,
    reviewed_by: str,
    reviewed_at: str,
    preparation_id: str,
) -> bytes:
    """Build the Golden-dossier domain subject embedded in the existing receipt."""

    try:
        _require_registered_evaluation_bundle(evaluation, result=result)
        exact_candidate = validate_schema67_candidate_v2(candidate)
        exact_authority = validate_schema67_candidate_evidence_authority_596_1(
            candidate=candidate, authority=evidence_authority
        )
        exact_golden = Schema67GoldenSet5961V1.model_validate(golden.model_dump(mode="python"))
        fresh_evaluation = Schema67GoldenEvaluationReviewBundleV1.model_validate(
            evaluation.model_dump(mode="python")
        )
        if (
            reviewed_by != "linyao"
            or not reviewed_at
            or not preparation_id
            or fresh_evaluation != evaluation
            or exact_golden != golden
            or exact_candidate.candidate_sha256 != evaluation.quality_gate_receipt.candidate_sha256
            or exact_authority.authority_sha256
            != evaluation.quality_gate_receipt.candidate_evidence_authority_sha256
            or exact_golden.golden_set_sha256 != evaluation.quality_gate_receipt.golden_set_sha256
        ):
            raise Schema67GoldenQualityGateError("GOLDEN_DOSSIER_REVIEW_RECEIPT_INVALID")
        provisional = _make_review_successor_metadata(
            evaluation=evaluation,
            candidate=candidate,
            evidence_authority=evidence_authority,
            golden=exact_golden,
            annotator_model_id=annotator_model_id,
            annotation_receipt_sha256=annotation_receipt_sha256,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
            review_receipt_sha256="0" * 64,
        )
        tenant_id, space_id, raw_kb_id, wiki_kb_id = _schema67_dossier_scope(exact_authority)
        dossier_authority_sha256 = schema_wiki_sha256(
            "schema67-golden-dossier-pre-receipt-authority.v1",
            {
                "preparation_id": preparation_id,
                "evaluation_id": evaluation.evaluation_id,
                "quality_gate_receipt_sha256": (evaluation.quality_gate_receipt.receipt_sha256),
                "private_dossier_sha256": evaluation.private_dossier.dossier_sha256,
                "public_aggregate_sha256": evaluation.public_aggregate.aggregate_sha256,
                "review_successor_pre_receipt_sha256": provisional.metadata_sha256,
                "evaluation_bundle_sha256": evaluation.evaluation_bundle_sha256,
                "serving_effect": "NONE",
            },
        )
        payload = {
            "contract": "schema67-golden-dossier-review-subject.v1",
            "product_version_id": "596-1",
            "candidate_sha256": exact_candidate.candidate_sha256,
            "candidate_evidence_authority_sha256": exact_authority.authority_sha256,
            "golden_artifact_sha256": _require_sha256(golden_artifact_sha256),
            "golden_set_sha256": exact_golden.golden_set_sha256,
            "golden_version": exact_golden.golden_version,
            "mapping_sha256": _require_sha256(mapping_sha256),
            "status_vector_sha256": _require_sha256(status_vector_sha256),
            "attestation_sha256": _require_sha256(attestation_sha256),
            "annotator_model_id": annotator_model_id,
            "annotation_receipt_sha256": _require_sha256(annotation_receipt_sha256),
            "dossier_authority_sha256": dossier_authority_sha256,
            "schema_pack_id": exact_golden.schema_pack_id,
            "schema_pack_sha256": exact_golden.schema_pack_sha256,
            "ordered_field_ids": exact_golden.ordered_field_ids,
            "source_sha256s": tuple(row.source_sha256 for row in exact_golden.source_authorities),
            "live_source_receipt_sha256s": tuple(
                row.live_revision_source_receipt.source_receipt_sha256
                for row in exact_golden.source_authorities
            ),
            "citation_join_receipt_sha256s": tuple(
                row.receipt_sha256 for row in exact_authority.join_receipts
            ),
            "golden_approval_sha256s": (evaluation.quality_gate_receipt.golden_approval_sha256s),
            "golden_whole_batch_approval_receipt_sha256": (
                exact_golden.whole_batch_approval_receipt_sha256
            ),
            "quality_gate_receipt_sha256": (evaluation.quality_gate_receipt.receipt_sha256),
            "evaluation_bundle_sha256": evaluation.evaluation_bundle_sha256,
            "private_dossier_sha256": evaluation.private_dossier.dossier_sha256,
            "public_aggregate_sha256": evaluation.public_aggregate.aggregate_sha256,
            "ordered_field_decision_sha256s": tuple(
                row.decision_sha256 for row in evaluation.private_dossier.field_decisions
            ),
            "review_field_metadata_sha256s": tuple(
                row.field_metadata_sha256 for row in provisional.ordered_fields
            ),
            "preparation_id": preparation_id,
            "tenant_id": tenant_id,
            "space_id": space_id,
            "raw_kb_id": raw_kb_id,
            "wiki_kb_id": wiki_kb_id,
            "reviewed_by": reviewed_by,
            "formal_reviewed_at": reviewed_at,
            "review_policy_sha256": GOLDEN_DOSSIER_REVIEW_POLICY_SHA256,
        }
        return (
            b"insurancekb.schema67-golden-dossier-human-batch.596-1.v1\x00"
            + schema_wiki_canonical_bytes("schema67-golden-dossier-review-subject.v1", payload)
        )
    except Schema67GoldenQualityGateError:
        raise
    except (
        AttributeError,
        CandidateEvidenceAuthorityError,
        KeyError,
        TypeError,
        ValueError,
        ValidationError,
    ):
        raise Schema67GoldenQualityGateError("GOLDEN_DOSSIER_REVIEW_RECEIPT_INVALID") from None


class _Schema67GoldenDossierReviewAuthorityPort(Protocol):
    def verify_dossier_receipt(
        self,
        *,
        receipt: HumanBatchDecisionReceiptV1,
        result: Schema67GoldenEvaluationResultV1,
        evaluation: Schema67GoldenEvaluationReviewBundleV1,
        candidate: object,
        evidence_authority: object,
        golden: Schema67GoldenSet5961V1,
        mapping_sha256: str,
        golden_artifact_sha256: str,
        status_vector_sha256: str,
        attestation_sha256: str,
        annotator_model_id: str,
        annotation_receipt_sha256: str,
        reviewed_by: str,
        reviewed_at: str,
        preparation_id: str,
    ) -> HumanBatchDecisionReceiptV1: ...


class _Schema67GoldenDossierReviewAuthorityComposer(Protocol):
    def __call__(self, *, now_epoch: int) -> _Schema67GoldenDossierReviewAuthorityPort: ...


def _build_schema67_golden_dossier_review_authority_api() -> tuple[
    _Schema67GoldenDossierReviewAuthorityComposer,
    Callable[..., tuple[object, ...]],
]:
    authority_lock = threading.Lock()
    deployment_authorities: weakref.WeakValueDictionary[int, object] = weakref.WeakValueDictionary()
    verified_receipts: dict[int, tuple[object, ...]] = {}

    class DeploymentSchema67GoldenDossierReviewAuthority:
        __slots__ = ("_keys", "_now_epoch", "_sealed", "__weakref__")
        _keys: Mapping[str, Ed25519PublicKey]
        _now_epoch: int
        _sealed: bool

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise Schema67GoldenQualityGateError("GOLDEN_DOSSIER_REVIEW_AUTHORITY_UNAVAILABLE")

        def __setattr__(self, name: str, value: object) -> None:
            if getattr(self, "_sealed", False):
                raise AttributeError("Golden dossier review authority is sealed")
            object.__setattr__(self, name, value)

        def verify_dossier_receipt(
            self,
            *,
            receipt: HumanBatchDecisionReceiptV1,
            result: Schema67GoldenEvaluationResultV1,
            evaluation: Schema67GoldenEvaluationReviewBundleV1,
            candidate: object,
            evidence_authority: object,
            golden: Schema67GoldenSet5961V1,
            mapping_sha256: str,
            golden_artifact_sha256: str,
            status_vector_sha256: str,
            attestation_sha256: str,
            annotator_model_id: str,
            annotation_receipt_sha256: str,
            reviewed_by: str,
            reviewed_at: str,
            preparation_id: str,
        ) -> HumanBatchDecisionReceiptV1:
            try:
                with authority_lock:
                    registered = deployment_authorities.get(id(self))
                if registered is not self:
                    raise Schema67GoldenQualityGateError(
                        "GOLDEN_DOSSIER_REVIEW_AUTHORITY_UNAVAILABLE"
                    )
                fresh = HumanBatchDecisionReceiptV1.model_validate(
                    receipt.model_dump(mode="python")
                )
                preimage = schema67_golden_dossier_review_subject_preimage_596_1(
                    result=result,
                    evaluation=evaluation,
                    candidate=candidate,
                    evidence_authority=evidence_authority,
                    golden=golden,
                    mapping_sha256=mapping_sha256,
                    golden_artifact_sha256=golden_artifact_sha256,
                    status_vector_sha256=status_vector_sha256,
                    attestation_sha256=attestation_sha256,
                    annotator_model_id=annotator_model_id,
                    annotation_receipt_sha256=annotation_receipt_sha256,
                    reviewed_by=reviewed_by,
                    reviewed_at=reviewed_at,
                    preparation_id=preparation_id,
                )
                tenant_id, space_id, raw_kb_id, wiki_kb_id = _schema67_dossier_scope(
                    evidence_authority
                )
                key = self._keys.get(fresh.signer_key_id)
                signature = base64.urlsafe_b64decode(
                    fresh.signature + "=" * (-len(fresh.signature) % 4)
                )
                if (
                    type(receipt) is not HumanBatchDecisionReceiptV1
                    or fresh != receipt
                    or key is None
                    or fresh.principal_id != reviewed_by
                    or reviewed_by != "linyao"
                    or fresh.candidate_hash != evaluation.quality_gate_receipt.candidate_sha256
                    or fresh.human_batch_hash != hashlib.sha256(preimage).hexdigest()
                    or fresh.review_policy_hash != GOLDEN_DOSSIER_REVIEW_POLICY_SHA256
                    or (fresh.tenant_id, fresh.space_id, fresh.raw_kb_id, fresh.wiki_kb_id)
                    != (tenant_id, space_id, raw_kb_id, wiki_kb_id)
                    or fresh.nonce != "schema67-golden-dossier-review-596-1"
                    or not fresh.issued_at <= self._now_epoch < fresh.expires_at
                ):
                    raise Schema67GoldenQualityGateError("GOLDEN_DOSSIER_REVIEW_RECEIPT_INVALID")
                key.verify(
                    signature,
                    canonical_human_batch_decision_receipt_v1(fresh, False),
                )
                registration = (
                    receipt,
                    result,
                    evaluation,
                    candidate,
                    evidence_authority,
                    golden,
                    mapping_sha256,
                    golden_artifact_sha256,
                    status_vector_sha256,
                    attestation_sha256,
                    annotator_model_id,
                    annotation_receipt_sha256,
                    reviewed_by,
                    reviewed_at,
                    preparation_id,
                )
                with authority_lock:
                    verified_receipts[id(receipt)] = registration
                return receipt
            except Schema67GoldenQualityGateError:
                raise
            except (AttributeError, InvalidSignature, TypeError, ValueError, ValidationError):
                raise Schema67GoldenQualityGateError(
                    "GOLDEN_DOSSIER_REVIEW_RECEIPT_INVALID"
                ) from None

    def compose(*, now_epoch: int) -> _Schema67GoldenDossierReviewAuthorityPort:
        try:
            settings = HarnessSettings()  # type: ignore[call-arg]
            configured = settings.schema_wiki_human_decision_public_keys
            if not configured:
                raise ValueError("empty human decision key ring")
            keys: dict[str, Ed25519PublicKey] = {}
            material_seen: set[bytes] = set()
            for key_id, encoded in configured:
                material = _decode_ed25519_public_key_text(encoded)
                if not key_id or key_id in keys or material in material_seen:
                    raise ValueError("duplicate human decision authority")
                keys[key_id] = Ed25519PublicKey.from_public_bytes(material)
                material_seen.add(material)
            authority = object.__new__(DeploymentSchema67GoldenDossierReviewAuthority)
            object.__setattr__(authority, "_keys", MappingProxyType(dict(keys)))
            object.__setattr__(authority, "_now_epoch", now_epoch)
            object.__setattr__(authority, "_sealed", True)
            with authority_lock:
                deployment_authorities[id(authority)] = authority
            return authority
        except (Schema67GoldenQualityGateError, ValidationError, TypeError, ValueError):
            raise Schema67GoldenQualityGateError(
                "GOLDEN_DOSSIER_REVIEW_AUTHORITY_UNAVAILABLE"
            ) from None

    def require_verified_receipt(
        receipt: HumanBatchDecisionReceiptV1,
        *,
        evaluation: Schema67GoldenEvaluationReviewBundleV1,
        candidate: object,
        evidence_authority: object,
        golden: Schema67GoldenSet5961V1,
        mapping_sha256: str,
        golden_artifact_sha256: str,
        status_vector_sha256: str,
        attestation_sha256: str,
        annotator_model_id: str,
        annotation_receipt_sha256: str,
        reviewed_by: str,
        reviewed_at: str,
        preparation_id: str,
    ) -> tuple[object, ...]:
        with authority_lock:
            current = verified_receipts.get(id(receipt))
        expected = (
            receipt,
            evaluation,
            candidate,
            evidence_authority,
            golden,
            mapping_sha256,
            golden_artifact_sha256,
            status_vector_sha256,
            attestation_sha256,
            annotator_model_id,
            annotation_receipt_sha256,
            reviewed_by,
            reviewed_at,
            preparation_id,
        )
        if current is None or current[0] is not receipt or current[2:] != expected[1:]:
            raise Schema67GoldenQualityGateError("GOLDEN_DOSSIER_REVIEW_RECEIPT_INVALID")
        return current

    return compose, require_verified_receipt


(
    compose_schema67_golden_dossier_review_authority_596_1,
    _require_verified_dossier_receipt,
) = _build_schema67_golden_dossier_review_authority_api()
del _build_schema67_golden_dossier_review_authority_api


def make_schema67_golden_review_successor_metadata_596_1(
    *,
    evaluation: Schema67GoldenEvaluationReviewBundleV1,
    candidate: object,
    evidence_authority: object,
    golden: Schema67GoldenSet5961V1,
    annotator_model_id: str,
    annotation_receipt_sha256: str,
    reviewed_by: str,
    reviewed_at: str,
    human_decision_receipt: HumanBatchDecisionReceiptV1,
    mapping_sha256: str,
    golden_artifact_sha256: str,
    status_vector_sha256: str,
    attestation_sha256: str,
    preparation_id: str,
) -> Schema67GoldenReviewSuccessorMetadataV1:
    try:
        _require_verified_dossier_receipt(
            human_decision_receipt,
            evaluation=evaluation,
            candidate=candidate,
            evidence_authority=evidence_authority,
            golden=golden,
            mapping_sha256=mapping_sha256,
            golden_artifact_sha256=golden_artifact_sha256,
            status_vector_sha256=status_vector_sha256,
            attestation_sha256=attestation_sha256,
            annotator_model_id=annotator_model_id,
            annotation_receipt_sha256=annotation_receipt_sha256,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
            preparation_id=preparation_id,
        )
        receipt_sha256 = hashlib.sha256(
            canonical_human_batch_decision_receipt_v1(human_decision_receipt, True)
        ).hexdigest()
        successor = _make_review_successor_metadata(
            evaluation=evaluation,
            candidate=candidate,
            evidence_authority=evidence_authority,
            golden=golden,
            annotator_model_id=annotator_model_id,
            annotation_receipt_sha256=annotation_receipt_sha256,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
            review_receipt_sha256=receipt_sha256,
        )
        _register_review_successor(
            successor,
            human_decision_receipt=human_decision_receipt,
            evaluation=evaluation,
            candidate=candidate,
            evidence_authority=evidence_authority,
            golden=golden,
            mapping_sha256=mapping_sha256,
            golden_artifact_sha256=golden_artifact_sha256,
            status_vector_sha256=status_vector_sha256,
            attestation_sha256=attestation_sha256,
            preparation_id=preparation_id,
        )
        return successor
    except (
        AttributeError,
        CandidateEvidenceAuthorityError,
        KeyError,
        TypeError,
        ValueError,
        ValidationError,
    ):
        raise Schema67GoldenQualityGateError("GOLDEN_REVIEW_SUCCESSOR_INVALID") from None


def validate_schema67_golden_review_successor_metadata_596_1(
    metadata: Schema67GoldenReviewSuccessorMetadataV1,
    *,
    evaluation: Schema67GoldenEvaluationReviewBundleV1,
    candidate: object,
    evidence_authority: object,
    golden: Schema67GoldenSet5961V1,
) -> Schema67GoldenReviewSuccessorMetadataV1:
    try:
        registration = _require_registered_review_successor(
            metadata,
            evaluation=evaluation,
            candidate=candidate,
            evidence_authority=evidence_authority,
            golden=golden,
        )
        expected = _make_review_successor_metadata(
            evaluation=evaluation,
            candidate=candidate,
            evidence_authority=evidence_authority,
            golden=golden,
            annotator_model_id=metadata.annotation_layer.annotator_model_id,
            annotation_receipt_sha256=metadata.annotation_layer.annotation_receipt_sha256,
            reviewed_by=metadata.human_review_layer.reviewed_by,
            reviewed_at=metadata.human_review_layer.reviewed_at,
            review_receipt_sha256=metadata.human_review_layer.review_receipt_sha256,
        )
        fresh = Schema67GoldenReviewSuccessorMetadataV1.model_validate(
            metadata.model_dump(mode="python")
        )
    except (
        AttributeError,
        CandidateEvidenceAuthorityError,
        KeyError,
        TypeError,
        ValueError,
        ValidationError,
    ):
        raise Schema67GoldenQualityGateError("GOLDEN_REVIEW_SUCCESSOR_INVALID") from None
    if fresh != expected or registration[0] is not metadata:
        raise Schema67GoldenQualityGateError("GOLDEN_REVIEW_SUCCESSOR_INVALID")
    return fresh


def make_schema_wiki_golden_quality_dossier_v2_596_1(
    *,
    preparation_id: str,
    evaluation: Schema67GoldenEvaluationReviewBundleV1,
    review_successor: Schema67GoldenReviewSuccessorMetadataV1,
    human_decision_receipt: HumanBatchDecisionReceiptV1,
) -> SchemaWikiGoldenQualityDossierV2:
    registration = _require_registered_review_successor(
        review_successor,
        evaluation=evaluation,
        human_decision_receipt=human_decision_receipt,
        preparation_id=preparation_id,
    )
    if registration[0] is not review_successor:
        raise Schema67GoldenQualityGateError("GOLDEN_REVIEW_SUCCESSOR_INVALID")
    dossier = SchemaWikiGoldenQualityDossierV2(
        version="schema-wiki-golden-quality-dossier.v2",
        preparation_id=preparation_id,
        evaluation_id=evaluation.evaluation_id,
        quality_gate_receipt_sha256=evaluation.quality_gate_receipt.receipt_sha256,
        private_dossier=evaluation.private_dossier,
        review_successor=review_successor,
        evaluation_bundle_sha256=evaluation.evaluation_bundle_sha256,
        serving_effect="NONE",
    )
    _register_quality_dossier(
        dossier,
        review_successor=review_successor,
        evaluation=evaluation,
        human_decision_receipt=human_decision_receipt,
    )
    return dossier


_RECEIPT_LOCK = threading.Lock()
_RECEIPT_REGISTRY: dict[
    int, tuple[weakref.ReferenceType[Schema67GoldenQualityGateReceiptV1], str]
] = {}
_EVALUATION_BUNDLE_REGISTRY: dict[
    int, tuple[Schema67GoldenEvaluationReviewBundleV1, Schema67GoldenEvaluationResultV1]
] = {}
_REVIEW_SUCCESSOR_REGISTRY: dict[int, tuple[object, ...]] = {}
_QUALITY_DOSSIER_REGISTRY: dict[int, tuple[object, ...]] = {}


def _register_evaluation_bundle(
    evaluation: Schema67GoldenEvaluationReviewBundleV1,
    result: Schema67GoldenEvaluationResultV1,
) -> None:
    with _RECEIPT_LOCK:
        _EVALUATION_BUNDLE_REGISTRY[id(evaluation)] = (evaluation, result)


def _require_registered_evaluation_bundle(
    evaluation: Schema67GoldenEvaluationReviewBundleV1,
    *,
    result: Schema67GoldenEvaluationResultV1 | None = None,
) -> tuple[Schema67GoldenEvaluationReviewBundleV1, Schema67GoldenEvaluationResultV1]:
    with _RECEIPT_LOCK:
        current = _EVALUATION_BUNDLE_REGISTRY.get(id(evaluation))
    if (
        current is None
        or current[0] is not evaluation
        or (result is not None and current[1] is not result)
    ):
        raise Schema67GoldenQualityGateError("GOLDEN_EVALUATION_BUNDLE_INVALID")
    return current


def _register_review_successor(
    successor: Schema67GoldenReviewSuccessorMetadataV1,
    *,
    human_decision_receipt: HumanBatchDecisionReceiptV1,
    evaluation: Schema67GoldenEvaluationReviewBundleV1,
    candidate: object,
    evidence_authority: object,
    golden: Schema67GoldenSet5961V1,
    mapping_sha256: str,
    golden_artifact_sha256: str,
    status_vector_sha256: str,
    attestation_sha256: str,
    preparation_id: str,
) -> None:
    registration = (
        successor,
        human_decision_receipt,
        evaluation,
        candidate,
        evidence_authority,
        golden,
        mapping_sha256,
        golden_artifact_sha256,
        status_vector_sha256,
        attestation_sha256,
        preparation_id,
    )
    with _RECEIPT_LOCK:
        _REVIEW_SUCCESSOR_REGISTRY[id(successor)] = registration


def _require_registered_review_successor(
    successor: Schema67GoldenReviewSuccessorMetadataV1,
    *,
    evaluation: Schema67GoldenEvaluationReviewBundleV1,
    human_decision_receipt: HumanBatchDecisionReceiptV1 | None = None,
    preparation_id: str | None = None,
    candidate: object | None = None,
    evidence_authority: object | None = None,
    golden: Schema67GoldenSet5961V1 | None = None,
) -> tuple[object, ...]:
    with _RECEIPT_LOCK:
        current = _REVIEW_SUCCESSOR_REGISTRY.get(id(successor))
    if (
        current is None
        or current[0] is not successor
        or current[2] is not evaluation
        or (human_decision_receipt is not None and current[1] is not human_decision_receipt)
        or (preparation_id is not None and current[10] != preparation_id)
        or (candidate is not None and current[3] is not candidate)
        or (evidence_authority is not None and current[4] is not evidence_authority)
        or (golden is not None and current[5] is not golden)
    ):
        raise Schema67GoldenQualityGateError("GOLDEN_REVIEW_SUCCESSOR_INVALID")
    return current


def _register_quality_dossier(
    dossier: SchemaWikiGoldenQualityDossierV2,
    *,
    review_successor: Schema67GoldenReviewSuccessorMetadataV1,
    evaluation: Schema67GoldenEvaluationReviewBundleV1,
    human_decision_receipt: HumanBatchDecisionReceiptV1,
) -> None:
    with _RECEIPT_LOCK:
        _QUALITY_DOSSIER_REGISTRY[id(dossier)] = (
            dossier,
            review_successor,
            evaluation,
            human_decision_receipt,
        )


def validate_registered_schema_wiki_golden_quality_dossier_v2_596_1(
    dossier: SchemaWikiGoldenQualityDossierV2,
    *,
    result: Schema67GoldenEvaluationResultV1,
    evaluation: Schema67GoldenEvaluationReviewBundleV1,
    human_decision_receipt: HumanBatchDecisionReceiptV1,
    candidate: object,
    evidence_authority: object,
    golden: Schema67GoldenSet5961V1,
    mapping_sha256: str,
    golden_artifact_sha256: str,
    status_vector_sha256: str,
    attestation_sha256: str,
) -> SchemaWikiGoldenQualityDossierV2:
    """Fresh-replay one factory-created formal dossier and every authority join."""

    try:
        with _RECEIPT_LOCK:
            registration = _QUALITY_DOSSIER_REGISTRY.get(id(dossier))
        if (
            registration is None
            or registration[0] is not dossier
            or registration[2] is not evaluation
            or registration[3] is not human_decision_receipt
        ):
            raise Schema67GoldenQualityGateError("GOLDEN_QUALITY_DOSSIER_INVALID")
        successor = registration[1]
        if type(successor) is not Schema67GoldenReviewSuccessorMetadataV1:
            raise Schema67GoldenQualityGateError("GOLDEN_QUALITY_DOSSIER_INVALID")
        _require_registered_evaluation_bundle(evaluation, result=result)
        _require_verified_dossier_receipt(
            human_decision_receipt,
            evaluation=evaluation,
            candidate=candidate,
            evidence_authority=evidence_authority,
            golden=golden,
            mapping_sha256=mapping_sha256,
            golden_artifact_sha256=golden_artifact_sha256,
            status_vector_sha256=status_vector_sha256,
            attestation_sha256=attestation_sha256,
            annotator_model_id=successor.annotation_layer.annotator_model_id,
            annotation_receipt_sha256=(successor.annotation_layer.annotation_receipt_sha256),
            reviewed_by=successor.human_review_layer.reviewed_by,
            reviewed_at=successor.human_review_layer.reviewed_at,
            preparation_id=dossier.preparation_id,
        )
        _require_registered_review_successor(
            successor,
            evaluation=evaluation,
            human_decision_receipt=human_decision_receipt,
            preparation_id=dossier.preparation_id,
            candidate=candidate,
            evidence_authority=evidence_authority,
            golden=golden,
        )
        receipt_sha256 = hashlib.sha256(
            canonical_human_batch_decision_receipt_v1(human_decision_receipt, True)
        ).hexdigest()
        fresh_successor = _make_review_successor_metadata(
            evaluation=evaluation,
            candidate=candidate,
            evidence_authority=evidence_authority,
            golden=golden,
            annotator_model_id=successor.annotation_layer.annotator_model_id,
            annotation_receipt_sha256=(successor.annotation_layer.annotation_receipt_sha256),
            reviewed_by=successor.human_review_layer.reviewed_by,
            reviewed_at=successor.human_review_layer.reviewed_at,
            review_receipt_sha256=receipt_sha256,
        )
        fresh_dossier = SchemaWikiGoldenQualityDossierV2(
            version="schema-wiki-golden-quality-dossier.v2",
            preparation_id=dossier.preparation_id,
            evaluation_id=evaluation.evaluation_id,
            quality_gate_receipt_sha256=(evaluation.quality_gate_receipt.receipt_sha256),
            private_dossier=evaluation.private_dossier,
            review_successor=fresh_successor,
            evaluation_bundle_sha256=evaluation.evaluation_bundle_sha256,
            serving_effect="NONE",
        )
        fresh_input = SchemaWikiGoldenQualityDossierV2.model_validate(
            dossier.model_dump(mode="python")
        )
        if fresh_successor != successor or fresh_input != fresh_dossier:
            raise Schema67GoldenQualityGateError("GOLDEN_QUALITY_DOSSIER_INVALID")
        return dossier
    except Schema67GoldenQualityGateError:
        raise
    except (
        AttributeError,
        CandidateEvidenceAuthorityError,
        KeyError,
        TypeError,
        ValueError,
        ValidationError,
    ):
        raise Schema67GoldenQualityGateError("GOLDEN_QUALITY_DOSSIER_INVALID") from None


def _register_receipt(receipt: Schema67GoldenQualityGateReceiptV1) -> None:
    identity = id(receipt)

    def remove(ref: weakref.ReferenceType[Schema67GoldenQualityGateReceiptV1]) -> None:
        with _RECEIPT_LOCK:
            current = _RECEIPT_REGISTRY.get(identity)
            if current is not None and current[0] is ref:
                _RECEIPT_REGISTRY.pop(identity, None)

    ref = weakref.ref(receipt, remove)
    with _RECEIPT_LOCK:
        _RECEIPT_REGISTRY[identity] = (ref, receipt.receipt_sha256)


def _require_registered_receipt(receipt: Schema67GoldenQualityGateReceiptV1) -> None:
    with _RECEIPT_LOCK:
        current = _RECEIPT_REGISTRY.get(id(receipt))
        if current is None or current[0]() is not receipt or current[1] != receipt.receipt_sha256:
            raise Schema67GoldenQualityGateError("QUALITY_GATE_RECEIPT_INVALID")


def make_schema67_golden_evaluation_review_bundle_596_1(
    result: Schema67GoldenEvaluationResultV1,
) -> Schema67GoldenEvaluationReviewBundleV1:
    if (
        type(result) is not Schema67GoldenEvaluationResultV1
        or result.status != "PASS"
        or result.quality_gate_receipt is None
        or type(result.quality_gate_receipt) is not Schema67GoldenQualityGateReceiptV1
    ):
        raise Schema67GoldenQualityGateError("GOLDEN_EVALUATION_BUNDLE_INVALID")
    _require_registered_receipt(result.quality_gate_receipt)
    payload = {
        "contract": "schema67-golden-evaluation-review-bundle.v1",
        "evaluation_id": result.quality_gate_receipt.receipt_sha256,
        "quality_gate_receipt": result.quality_gate_receipt,
        "public_aggregate": result.public_aggregate,
        "private_dossier": result.private_dossier,
    }
    try:
        evaluation = Schema67GoldenEvaluationReviewBundleV1.model_validate(
            {
                **payload,
                "evaluation_bundle_sha256": schema_wiki_sha256(
                    "schema67-golden-evaluation-review-bundle.v1",
                    payload,
                ),
            }
        )
        _register_evaluation_bundle(evaluation, result)
        return evaluation
    except ValidationError:
        raise Schema67GoldenQualityGateError("GOLDEN_EVALUATION_BUNDLE_INVALID") from None


def _normalized(value: str | None) -> str | None:
    return None if value is None else unicodedata.normalize("NFC", value).strip()


def _structured_atoms(value: object, path: str = "$") -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(
            atom for key in sorted(value) for atom in _structured_atoms(value[key], f"{path}.{key}")
        )
    if isinstance(value, list):
        return tuple(
            atom
            for index, item in enumerate(value)
            for atom in _structured_atoms(item, f"{path}[{index}]")
        )
    scalar = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (f"{path}={scalar}",)


def _normalized_atoms(value_schema: str, value: str | None) -> tuple[str, ...]:
    normalized = _normalized(value)
    if normalized is None:
        return ()
    if value_schema == "scalar":
        return (normalized,)
    try:
        decoded = json.loads(normalized)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("structured Golden value is not canonical JSON") from None
    if value_schema in {"ordered_list", "unordered_set"}:
        if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
            raise ValueError("Golden collection value invalid")
        values = tuple(unicodedata.normalize("NFC", item).strip() for item in decoded)
        if any(not item for item in values):
            raise ValueError("Golden collection value invalid")
        if value_schema == "ordered_list":
            return tuple(f"{index}:{item}" for index, item in enumerate(values))
        if len(set(values)) != len(values):
            raise ValueError("Golden set contains duplicates")
        return tuple(sorted(values))
    if value_schema in {"range", "structured"}:
        if not isinstance(decoded, (dict, list)):
            raise ValueError("Golden structured value invalid")
        return _structured_atoms(decoded)
    raise ValueError("unknown Golden value schema")


def _best_atom_counts(
    field: Schema67GoldenFieldV1,
    candidate_value: str | None,
) -> tuple[int, int, int]:
    try:
        predicted = Counter(_normalized_atoms(field.value_schema, candidate_value))
    except ValueError:
        predicted = Counter()
    alternatives = tuple(
        Counter(_normalized_atoms(field.value_schema, row)) for row in field.accepted_values
    )
    if not alternatives:
        return (0, sum(predicted.values()), 0)
    scored: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = []
    for expected in alternatives:
        true_positive = sum((predicted & expected).values())
        false_positive = sum((predicted - expected).values())
        false_negative = sum((expected - predicted).values())
        scored.append(
            (
                (true_positive, -false_positive, -false_negative),
                (true_positive, false_positive, false_negative),
            )
        )
    return max(scored, key=lambda row: row[0])[1]


def _join_projection(join: Schema67CitationAuthorityJoinReceiptV1) -> tuple[object, ...]:
    return (
        join.source_role,
        join.live_revision_source_receipt_sha256,
        join.live_revision_source_receipt.revision_source_id,
        join.knowledge_id,
        join.evidence_parse_attempt_id,
        join.weknora_parse_attempt,
        join.file_sha256,
        join.parsed_document_sha256,
        join.parse_manifest_sha256,
        join.weknora_manifest_algorithm,
        join.weknora_manifest_digest,
        join.chunk_id,
        join.page_number,
        join.locator_kind,
        join.locator_ref,
        join.quote_sha256,
        join.locator_content_sha256,
    )


def _target_projection(target: Schema67GoldenEvidenceTargetV1) -> tuple[object, ...]:
    return (
        target.source_role,
        target.live_revision_source_receipt_sha256,
        target.revision_source_id,
        target.knowledge_id,
        target.evidence_parse_attempt_id,
        target.weknora_parse_attempt,
        target.file_sha256,
        target.parsed_document_sha256,
        target.parse_manifest_sha256,
        target.weknora_manifest_algorithm,
        target.weknora_manifest_digest,
        target.chunk_id,
        target.page_number,
        target.locator_kind,
        target.locator_ref,
        target.quote_sha256,
        target.content_sha256,
    )


def _bbox_iou_ppm(
    join: Schema67CitationAuthorityJoinReceiptV1,
    target: Schema67GoldenEvidenceTargetV1,
) -> int | None:
    if target.bbox_evaluation == "not_evaluable":
        return None
    if (
        target.coordinate_space != join.target_coordinate_space
        or target.page_width != join.page_width
        or target.page_height != join.page_height
        or target.rotation_degrees != join.rotation_degrees
        or target.bbox is None
    ):
        return 0
    left = max(target.bbox.x0, join.normalized_bbox.x0)
    top = max(target.bbox.y0, join.normalized_bbox.y0)
    right = min(target.bbox.x1, join.normalized_bbox.x1)
    bottom = min(target.bbox.y1, join.normalized_bbox.y1)
    intersection = max(0, right - left) * max(0, bottom - top)
    target_area = (target.bbox.x1 - target.bbox.x0) * (target.bbox.y1 - target.bbox.y0)
    join_area = (join.normalized_bbox.x1 - join.normalized_bbox.x0) * (
        join.normalized_bbox.y1 - join.normalized_bbox.y0
    )
    union = target_area + join_area - intersection
    return 0 if union <= 0 else int(intersection * 1_000_000 / union)


def _decision(
    field: Schema67GoldenFieldV1,
    candidate_state: FieldState,
    candidate_value: str | None,
    joins: tuple[Schema67CitationAuthorityJoinReceiptV1, ...],
) -> Schema67GoldenFieldDecisionV1:
    state_correct = candidate_state == field.state
    if field.state == "present" and candidate_state == "present":
        atom_tp, atom_fp, atom_fn = _best_atom_counts(field, candidate_value)
    elif field.state == "present":
        atom_tp, atom_fp, atom_fn = _best_atom_counts(field, None)
    else:
        atom_tp = atom_fp = atom_fn = 0
    atom_denominator = 2 * atom_tp + atom_fp + atom_fn
    atom_f1_ppm = (
        1_000_000 if atom_denominator == 0 else round(2 * atom_tp * 1_000_000 / atom_denominator)
    )
    value_correct = (
        (candidate_state == "unknown" and field.state == "unknown" and candidate_value is None)
        or (candidate_state == field.state == "present" and atom_fp == 0 and atom_fn == 0)
        or (
            candidate_state == field.state == "absent_explicitly"
            and _normalized(candidate_value) in field.accepted_values
        )
    )
    targets = {_target_projection(target): target for target in field.evidence_targets}
    matched = [join for join in joins if _join_projection(join) in targets]
    joins_by_projection = {_join_projection(join): join for join in matched}
    bbox_scores = tuple(
        0
        if (join := joins_by_projection.get(_target_projection(target))) is None
        else (_bbox_iou_ppm(join, target) or 0)
        for target in field.evidence_targets
        if target.bbox_evaluation == "required"
    )
    bbox_required = sum(target.bbox_evaluation == "required" for target in field.evidence_targets)
    bbox_passed = sum(score >= 800_000 for score in bbox_scores)
    evidence_exact = len(matched) == len(joins) == len(field.evidence_targets) and (
        field.state == "unknown" or bool(matched)
    )
    conflict_resolved = field.conflict_status == "agreed" or field.adjudication_sha256 is not None
    high_risk_pass = field.risk_level == "standard" or (
        state_correct
        and value_correct
        and evidence_exact
        and all(score >= 900_000 for score in bbox_scores)
    )
    payload = {
        "field_id": field.field_id,
        "golden_field_sha256": field.field_sha256,
        "candidate_state": candidate_state,
        "golden_state": field.state,
        "state_correct": state_correct,
        "value_correct": value_correct,
        "atom_true_positive": atom_tp,
        "atom_false_positive": atom_fp,
        "atom_false_negative": atom_fn,
        "atom_f1_ppm": atom_f1_ppm,
        "evidence_fragments": len(joins),
        "evidence_fragments_matched": len(matched),
        "bbox_required": bbox_required,
        "bbox_passed": bbox_passed,
        "bbox_iou_ppm_values": bbox_scores,
        "high_risk_pass": high_risk_pass,
        "conflict_resolved": conflict_resolved,
    }
    return Schema67GoldenFieldDecisionV1.model_validate(
        {
            **payload,
            "decision_sha256": schema_wiki_sha256("schema67-golden-field-decision.v1", payload),
        }
    )


def _wilson_ppm(numerator: int, denominator: int) -> tuple[int, int]:
    proportion = numerator / denominator
    z = 1.959963984540054
    denominator_term = 1 + z * z / denominator
    centre = (proportion + z * z / (2 * denominator)) / denominator_term
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / denominator + z * z / (4 * denominator * denominator)
        )
        / denominator_term
    )
    return (
        max(0, round((centre - margin) * 1_000_000)),
        min(1_000_000, round((centre + margin) * 1_000_000)),
    )


def _metric(
    metric_id: str,
    numerator: int | None,
    denominator: int | None,
    *,
    supports: tuple[int, ...] = (),
    passing: bool,
    binomial: bool = True,
) -> Schema67GoldenMetricV1:
    evaluable = denominator is not None and denominator > 0 and numerator is not None
    if evaluable:
        assert numerator is not None and denominator is not None
        value_ppm = round(numerator * 1_000_000 / denominator)
        interval: tuple[int | None, int | None] = (
            _wilson_ppm(numerator, denominator) if binomial else (None, None)
        )
        sample_size = "SMALL_SAMPLE" if denominator < 20 else "ADEQUATE"
    else:
        value_ppm = None
        interval = (None, None)
        sample_size = "NOT_EVALUABLE"
    payload = {
        "metric_id": metric_id,
        "numerator": numerator if evaluable else None,
        "denominator": denominator if evaluable else None,
        "value_ppm": value_ppm,
        "supports": supports,
        "evaluability": "EVALUABLE" if evaluable else "NOT_EVALUABLE",
        "sample_size": sample_size,
        "wilson_low_ppm": interval[0],
        "wilson_high_ppm": interval[1],
        "admission_status": "PASS" if evaluable and passing else "FAIL",
    }
    return Schema67GoldenMetricV1.model_validate(
        {
            **payload,
            "metric_sha256": schema_wiki_sha256("schema67-golden-metric.v1", payload),
        }
    )


def _metrics(
    fields: tuple[Schema67GoldenFieldV1, ...],
    decisions: tuple[Schema67GoldenFieldDecisionV1, ...],
    candidate_states: tuple[FieldState, ...],
) -> tuple[Schema67GoldenMetricV1, ...]:
    supports = Counter(field.state for field in fields)
    correct = Counter(
        field.state
        for field, decision in zip(fields, decisions, strict=True)
        if decision.state_correct
    )
    state_accuracy = sum(row.state_correct for row in decisions)
    class_recall_ppm = tuple(
        round(correct[state] * 1_000_000 / supports[state]) if supports[state] else 0
        for state in ("present", "absent_explicitly", "unknown")
    )
    macro_numerator = sum(class_recall_ppm)
    present_indexes = tuple(index for index, field in enumerate(fields) if field.state == "present")
    atom_true_positive = sum(decisions[index].atom_true_positive for index in present_indexes)
    atom_false_positive = sum(decisions[index].atom_false_positive for index in present_indexes)
    atom_false_negative = sum(decisions[index].atom_false_negative for index in present_indexes)
    predicted_atoms = atom_true_positive + atom_false_positive
    golden_atoms = atom_true_positive + atom_false_negative
    macro_f1_numerator = sum(decisions[index].atom_f1_ppm for index in present_indexes)
    absent_to_unknown = sum(
        field.state == "absent_explicitly" and candidate_states[index] == "unknown"
        for index, field in enumerate(fields)
    )
    unknown_to_absent = sum(
        field.state == "unknown" and candidate_states[index] == "absent_explicitly"
        for index, field in enumerate(fields)
    )
    present_present = sum(
        field.state == "present" and candidate_states[index] == "present"
        for index, field in enumerate(fields)
    )
    wrong_fills = sum(
        field.state == "present"
        and candidate_states[index] == "present"
        and not decisions[index].value_correct
        for index, field in enumerate(fields)
    )
    absent_unknown_support = supports["absent_explicitly"] + supports["unknown"]
    hallucinations = sum(
        field.state in {"absent_explicitly", "unknown"} and candidate_states[index] == "present"
        for index, field in enumerate(fields)
    )
    evidence_total = sum(row.evidence_fragments for row in decisions)
    evidence_matched = sum(row.evidence_fragments_matched for row in decisions)
    known_indexes = tuple(index for index, field in enumerate(fields) if field.state != "unknown")
    known_supported = sum(
        decisions[index].evidence_fragments_matched > 0 for index in known_indexes
    )
    bbox_total = sum(row.bbox_required for row in decisions)
    bbox_passed = sum(row.bbox_passed for row in decisions)
    bbox_iou_total = sum(value for row in decisions for value in row.bbox_iou_ppm_values)
    high_indexes = tuple(
        index for index, field in enumerate(fields) if field.risk_level in {"critical", "high"}
    )
    high_passed = sum(decisions[index].high_risk_pass for index in high_indexes)
    conflict_indexes = tuple(
        index for index, field in enumerate(fields) if field.conflict_status == "resolved"
    )
    conflict_passed = sum(decisions[index].conflict_resolved for index in conflict_indexes)
    return (
        _metric(GOLDEN_METRIC_IDS[0], state_accuracy, 67, passing=state_accuracy >= 65),
        _metric(
            GOLDEN_METRIC_IDS[1],
            macro_numerator,
            (
                3_000_000
                if all(supports[state] > 0 for state in ("present", "absent_explicitly", "unknown"))
                else None
            ),
            supports=tuple(
                supports[state] for state in ("present", "absent_explicitly", "unknown")
            ),
            passing=all(value >= 950_000 for value in class_recall_ppm),
            binomial=False,
        ),
        _metric(
            GOLDEN_METRIC_IDS[2],
            atom_true_positive,
            predicted_atoms,
            passing=predicted_atoms > 0 and atom_true_positive * 100 >= predicted_atoms * 95,
        ),
        _metric(
            GOLDEN_METRIC_IDS[3],
            atom_true_positive,
            golden_atoms,
            passing=golden_atoms > 0 and atom_true_positive * 100 >= golden_atoms * 95,
        ),
        _metric(
            GOLDEN_METRIC_IDS[4],
            macro_f1_numerator,
            len(present_indexes) * 1_000_000 if present_indexes else None,
            passing=bool(present_indexes)
            and macro_f1_numerator * 10 >= len(present_indexes) * 9_000_000,
            binomial=False,
        ),
        _metric(
            GOLDEN_METRIC_IDS[5],
            absent_to_unknown,
            supports["absent_explicitly"],
            passing=absent_to_unknown == 0,
        ),
        _metric(
            GOLDEN_METRIC_IDS[6],
            unknown_to_absent,
            supports["unknown"],
            passing=unknown_to_absent == 0,
        ),
        _metric(
            GOLDEN_METRIC_IDS[7],
            wrong_fills,
            present_present,
            passing=present_present > 0 and wrong_fills * 100 <= present_present * 2,
        ),
        _metric(
            GOLDEN_METRIC_IDS[8],
            hallucinations,
            absent_unknown_support,
            passing=absent_unknown_support > 0 and hallucinations == 0,
        ),
        _metric(
            GOLDEN_METRIC_IDS[9],
            evidence_matched,
            evidence_total,
            passing=evidence_total > 0 and evidence_matched == evidence_total,
        ),
        _metric(
            GOLDEN_METRIC_IDS[10],
            known_supported,
            len(known_indexes),
            passing=bool(known_indexes) and known_supported == len(known_indexes),
        ),
        _metric(
            GOLDEN_METRIC_IDS[11],
            bbox_iou_total,
            bbox_total * 1_000_000 if bbox_total else None,
            passing=bbox_total > 0 and bbox_iou_total >= bbox_total * 800_000,
            binomial=False,
        ),
        _metric(
            GOLDEN_METRIC_IDS[12],
            bbox_passed,
            bbox_total,
            passing=bbox_total > 0 and bbox_passed == bbox_total,
        ),
        _metric(
            GOLDEN_METRIC_IDS[13],
            high_passed,
            len(high_indexes),
            passing=bool(high_indexes) and high_passed == len(high_indexes),
        ),
        _metric(
            GOLDEN_METRIC_IDS[14],
            conflict_passed,
            len(conflict_indexes),
            passing=bool(conflict_indexes) and conflict_passed == len(conflict_indexes),
        ),
    )


def validate_schema67_golden_quality_gate_receipt_596_1(
    receipt: object,
    *,
    candidate: object,
    evidence_authority: object,
) -> Schema67GoldenQualityGateReceiptV1:
    try:
        exact_candidate = validate_schema67_candidate_v2(candidate)
        exact_authority = validate_schema67_candidate_evidence_authority_596_1(
            candidate=exact_candidate,
            authority=evidence_authority,
        )
        if type(receipt) is not Schema67GoldenQualityGateReceiptV1:
            raise TypeError
        _require_registered_receipt(receipt)
        if (
            receipt.candidate_sha256 != exact_candidate.candidate_sha256
            or receipt.candidate_evidence_authority_sha256 != exact_authority.authority_sha256
            or receipt.evaluator_identity_sha256 != EVALUATOR_IDENTITY_SHA256
            or receipt.metric_policy_sha256 != METRIC_POLICY_SHA256
        ):
            raise ValueError
        return receipt
    except (CandidateEvidenceAuthorityError, TypeError, ValueError, ValidationError):
        raise Schema67GoldenQualityGateError("QUALITY_GATE_RECEIPT_INVALID") from None


def _evaluate_schema67_golden_quality_596_1(
    *,
    candidate: object,
    evidence_authority: object,
    golden: Schema67GoldenSet5961V1,
    golden_approvals: tuple[Schema67GoldenApprovalV1, Schema67GoldenApprovalV1],
    golden_approval_verifier: _Schema67GoldenApprovalVerifierV1,
    quality_gate_signer: _Schema67QualityGateSignerV1,
    fixture_provenance: object | None,
    require_fixture_provenance: bool,
) -> Schema67GoldenEvaluationResultV1:
    if candidate is None:
        raise Schema67GoldenQualityGateError("CANDIDATE_ABSENT")
    try:
        exact_candidate = validate_schema67_candidate_v2(candidate)
        exact_authority = validate_schema67_candidate_evidence_authority_596_1(
            candidate=exact_candidate,
            authority=evidence_authority,
        )
        if require_fixture_provenance:
            _require_provider_zero_fixture_provenance_596_1(
                fixture_provenance,
                candidate_sha256=exact_candidate.candidate_sha256,
                candidate_evidence_authority_sha256=exact_authority.authority_sha256,
            )
        elif fixture_provenance is not None:
            raise Schema67GoldenQualityGateError(
                "PROVIDER_ZERO_FIXTURE_PROVENANCE_INVALID"
            )
        exact_golden = Schema67GoldenSet5961V1.model_validate(
            golden.model_dump(mode="python", round_trip=True)
        )
        if type(golden_approval_verifier) is not _Schema67GoldenApprovalVerifierV1:
            raise Schema67GoldenQualityGateError("GOLDEN_APPROVAL_INVALID")
        approvals = golden_approval_verifier.verify(exact_golden, golden_approvals)
        if type(quality_gate_signer) is not _Schema67QualityGateSignerV1:
            raise Schema67GoldenQualityGateError("QUALITY_GATE_SIGNER_UNAVAILABLE")
        candidate_source_rows = tuple(
            (row["role"], row["source_sha256"]) for row in exact_candidate.source_roles
        )
        golden_source_rows = tuple(
            (row.source_role, row.source_sha256) for row in exact_golden.source_authorities
        )
        if (
            candidate_source_rows != golden_source_rows
            or exact_golden.source_authorities != exact_authority.source_authorities
        ):
            raise ValueError
        outputs = {row.field_id: row for row in exact_candidate.fields}
        joins: dict[str, list[Schema67CitationAuthorityJoinReceiptV1]] = {}
        for row in exact_authority.join_receipts:
            joins.setdefault(row.field_id, []).append(row)
        decisions = tuple(
            _decision(
                field,
                outputs[field.field_id].state,
                outputs[field.field_id].value_snapshot,
                tuple(joins.get(field.field_id, ())),
            )
            for field in exact_golden.fields
        )
        metrics = _metrics(
            exact_golden.fields,
            decisions,
            tuple(outputs[field_id].state for field_id in APPROVED_ORDERED_FIELD_IDS),
        )
        fixture = require_fixture_provenance
        passed = not fixture and all(row.admission_status == "PASS" for row in metrics)
        status: EvaluationStatus = "FIXTURE_ONLY" if fixture else "PASS" if passed else "FAIL"
        reasons = (
            ("PROVIDER_ZERO_FIXTURE_ONLY",)
            if fixture
            else ()
            if passed
            else tuple(row.metric_id for row in metrics if row.admission_status == "FAIL")
        )
        dossier_payload = {
            "contract": "schema67-golden-private-dossier.v1",
            "candidate_sha256": exact_candidate.candidate_sha256,
            "candidate_evidence_authority_sha256": exact_authority.authority_sha256,
            "golden_set_sha256": exact_golden.golden_set_sha256,
            "field_decisions": decisions,
            "metrics": metrics,
            "status": status,
            "reason_codes": reasons,
        }
        dossier = Schema67GoldenPrivateDossierV1.model_validate(
            {
                **dossier_payload,
                "dossier_sha256": schema_wiki_sha256(
                    "schema67-golden-private-dossier.v1", dossier_payload
                ),
            }
        )
        aggregate_payload = {
            "contract": "schema67-golden-public-aggregate.v1",
            "product_version_id": "596-1",
            "candidate_sha256": exact_candidate.candidate_sha256,
            "golden_set_sha256": exact_golden.golden_set_sha256,
            "evaluator_identity_sha256": EVALUATOR_IDENTITY_SHA256,
            "metrics": metrics,
            "status": status,
            "reason_codes": reasons,
        }
        aggregate = Schema67GoldenPublicAggregateV1.model_validate(
            {
                **aggregate_payload,
                "aggregate_sha256": schema_wiki_sha256(
                    "schema67-golden-public-aggregate.v1", aggregate_payload
                ),
            }
        )
        receipt = None
        if passed:
            receipt_payload = {
                "contract": "schema67-golden-quality-gate-receipt.v1",
                "status": "PASS",
                "product_version_id": "596-1",
                "candidate_sha256": exact_candidate.candidate_sha256,
                "candidate_evidence_authority_sha256": exact_authority.authority_sha256,
                "golden_set_sha256": exact_golden.golden_set_sha256,
                "golden_version": exact_golden.golden_version,
                "evaluator_identity_sha256": EVALUATOR_IDENTITY_SHA256,
                "metric_policy_sha256": METRIC_POLICY_SHA256,
                "ordered_field_decision_sha256s": tuple(row.decision_sha256 for row in decisions),
                "metric_receipt_sha256s": tuple(row.metric_sha256 for row in metrics),
                "private_dossier_sha256": dossier.dossier_sha256,
                "public_aggregate_sha256": aggregate.aggregate_sha256,
                "golden_approval_sha256s": tuple(
                    approval.approval_sha256 for approval in approvals
                ),
                "whole_batch_approval_receipt_sha256": (
                    exact_golden.whole_batch_approval_receipt_sha256
                ),
                "signer_key_id": quality_gate_signer.key_id,
            }
            signature = quality_gate_signer.sign(receipt_payload)
            signed_receipt_payload = {**receipt_payload, "signature": signature}
            receipt = Schema67GoldenQualityGateReceiptV1.model_validate(
                {
                    **signed_receipt_payload,
                    "receipt_sha256": schema_wiki_sha256(
                        "schema67-golden-quality-gate-receipt.v1", signed_receipt_payload
                    ),
                }
            )
            _register_receipt(receipt)
        result = Schema67GoldenEvaluationResultV1(
            status=status,
            private_dossier=dossier,
            public_aggregate=aggregate,
            quality_gate_receipt=receipt,
        )
        if result.quality_gate_receipt is not None:
            _register_receipt(result.quality_gate_receipt)
        return result
    except Schema67GoldenQualityGateError:
        raise
    except (
        AttributeError,
        CandidateEvidenceAuthorityError,
        KeyError,
        TypeError,
        ValueError,
        ValidationError,
    ):
        raise Schema67GoldenQualityGateError("SCHEMA67_GOLDEN_QUALITY_GATE_FAILED") from None


__all__ = [
    "EVALUATOR_IDENTITY_SHA256",
    "GOLDEN_DOSSIER_REVIEW_POLICY_SHA256",
    "GOLDEN_METRIC_IDS",
    "METRIC_POLICY_SHA256",
    "HumanBatchDecisionReceiptV1",
    "Schema67GoldenEvidenceTargetV1",
    "Schema67GoldenApprovalV1",
    "Schema67GoldenEvaluationResultV1",
    "Schema67GoldenEvaluationReviewBundleV1",
    "Schema67GoldenEvidenceChangeV1",
    "Schema67GoldenFieldDecisionV1",
    "Schema67GoldenFieldV1",
    "Schema67GoldenReviewFieldMetadataV1",
    "Schema67GoldenReviewSuccessorMetadataV1",
    "Schema67GoldenReviewValueV1",
    "Schema67GoldenMetricV1",
    "Schema67GoldenPrivateDossierV1",
    "Schema67GoldenPublicAggregateV1",
    "Schema67GoldenQualityGateError",
    "Schema67GoldenQualityEvaluatorAuthority",
    "Schema67GoldenQualityEvaluatorSigningCredentialSource",
    "Schema67GoldenSet5961V1",
    "SchemaWikiGoldenQualityDossierV2",
    "compose_schema67_golden_quality_evaluator_authority_596_1",
    "compose_schema67_golden_dossier_review_authority_596_1",
    "canonical_human_batch_decision_receipt_v1",
    "make_schema67_golden_evaluation_review_bundle_596_1",
    "make_schema67_provider_zero_fixture_provenance_596_1",
    "make_schema67_golden_review_successor_metadata_596_1",
    "make_schema_wiki_golden_quality_dossier_v2_596_1",
    "schema67_golden_approval_signing_bytes",
    "schema67_golden_dossier_review_subject_preimage_596_1",
    "validate_registered_schema_wiki_golden_quality_dossier_v2_596_1",
    "validate_schema67_golden_quality_gate_receipt_596_1",
    "validate_schema67_golden_review_successor_metadata_596_1",
]
