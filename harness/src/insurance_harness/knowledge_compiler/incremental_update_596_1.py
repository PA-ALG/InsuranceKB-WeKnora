"""Task-local synthetic 596-1 incremental-update vertical for OpenSpec 078."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Annotated, Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictStr,
    StringConstraints,
    ValidationError,
    computed_field,
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.evidence_verifier import (
    CandidateValueV1,
    FieldCandidateV1,
    FieldRuleV1,
    RepairResolutionV1,
    VerificationBatchV1,
    bind_054_attempt_receipt,
    verify_evidence_batch,
)
from insurance_harness.compiler.extraction_receipts import ReceiptChainV1
from insurance_harness.compiler.extraction_tasks import (
    ArtifactRefV1,
    ParsedArtifactAdmissionPort,
)
from insurance_harness.compiler.material_profiles import (
    MaterialProfileCatalog,
    MaterialProfileResolution,
    material_profile_catalog_hash,
)
from insurance_harness.compiler.parsed_documents import (
    ParsedDocumentV1,
    ParseManifestV1,
    ParseQualityDecisionV1,
    build_parse_manifest,
    evaluate_parse_quality,
)
from insurance_harness.knowledge_compiler.candidate_batches import (
    FactVerificationLinkV1,
    HumanBatchPolicyV1,
    build_fixture_candidate_batch,
)
from insurance_harness.knowledge_compiler.incremental_changes import (
    VerifiedFactV1,
    compile_incremental_changes,
)
from insurance_harness.knowledge_compiler.retractions import RetractionProofV1

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=512, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
Action = Literal["enrich", "supersede", "conflict", "retract"]
CandidateState = Literal["known", "unknown", "absent_explicitly"]

FIXTURE_OBJECT_TYPE: Final[str] = "s0q-5961-incremental-fixture.v1"
PREIMAGE_OBJECT_TYPE: Final[str] = "s0q-5961-incremental-preimage.v1"
RETRACTION_LINK_OBJECT_TYPE: Final[str] = "s0q-5961-retraction-verification-link.v1"
RECEIPT_OBJECT_TYPE: Final[str] = "s0q-5961-incremental-receipt.v1"
ACTION_OBJECT_TYPE: Final[str] = "s0q-5961-action-receipt.v1"
VALUE_OBJECT_TYPE: Final[str] = "s0q-5961-synthetic-value.v1"
EVIDENCE_OBJECT_TYPE: Final[str] = "s0q-5961-synthetic-evidence.v1"
EXPECTED_FIELD_ACTIONS: Final[tuple[tuple[str, Action], ...]] = (
    ("clause_version", "enrich"),
    ("zh_1ec5e3f2cc", "supersede"),
    ("zh_3d8424595d", "conflict"),
    ("zh_f32c510a5e", "retract"),
)
EXPECTED_ACTIONS: Final[frozenset[str]] = frozenset(action for _, action in EXPECTED_FIELD_ACTIONS)
EXPECTED_SCHEMA60_FIELD_IDS_HASH: Final[str] = (
    "a57d3bddd20e718907d641742b5072cf42845f51f77cd4b0d5d9752a661d0f70"
)
EXPLICIT_ABSENCE_MARKER: Final[str] = "synthetic-explicit-absence"


class IncrementalUpdateFixtureError(ValueError):
    """Typed fail-closed result for an invalid OpenSpec 078 fixture."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class _AffectedFixtureV1(_FrozenModel):
    field_id: NonBlankStr
    action: Action
    baseline_value_tag: NonBlankStr
    candidate_value_tag: NonBlankStr | None
    candidate_state: CandidateState
    complete_scope: bool = False
    explicitly_absent: bool = False
    exclusive_support: bool = False

    @model_validator(mode="after")
    def require_synthetic_action_shape(self) -> Self:
        tags = tuple(
            value
            for value in (self.baseline_value_tag, self.candidate_value_tag)
            if value is not None
        )
        if any(not value.startswith("synthetic-") for value in tags):
            raise ValueError("NON_SYNTHETIC_FIXTURE_VALUE")
        if self.action == "retract":
            if (
                self.candidate_value_tag is not None
                or self.candidate_state != "absent_explicitly"
                or not self.complete_scope
                or not self.explicitly_absent
                or not self.exclusive_support
            ):
                raise ValueError("RETRACTION_AUTHORITY_INCOMPLETE")
        elif (
            self.candidate_value_tag is None
            or self.candidate_state != "known"
            or self.complete_scope
            or self.explicitly_absent
            or self.exclusive_support
        ):
            raise ValueError("INVALID_AFFECTED_ACTION_SHAPE")
        return self


class _FixtureV1(_FrozenModel):
    contract: Literal["596-1-incremental-update-fixture.v1"]
    fixture_id: Literal["synthetic-596-1-four-action-v1"]
    synthetic_only: Literal[True]
    space_id: Literal["space-078-fixture"]
    product_version_id: Literal["596-1"]
    subject_id: Literal["product:596-1:synthetic-fixture"]
    schema_version: Literal["v1.1+b31a411c621c"]
    field_ids: tuple[NonBlankStr, ...]
    affected: tuple[_AffectedFixtureV1, ...]

    @model_validator(mode="before")
    @classmethod
    def canonicalize_exact_affected_order(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        affected = value.get("affected")
        if not isinstance(affected, (list, tuple)):
            return value
        expected_index = {
            field_id: index for index, (field_id, _) in enumerate(EXPECTED_FIELD_ACTIONS)
        }
        if len(affected) != 4 or any(not isinstance(item, Mapping) for item in affected):
            return value
        pairs = {(item.get("field_id"), item.get("action")) for item in affected}
        if pairs != set(EXPECTED_FIELD_ACTIONS):
            return value
        return {
            **value,
            "affected": tuple(
                sorted(affected, key=lambda item: expected_index[str(item.get("field_id"))])
            ),
        }

    @model_validator(mode="after")
    def require_exact_partition(self) -> Self:
        if len(self.field_ids) != 60 or len(set(self.field_ids)) != 60:
            raise ValueError("INVALID_60_FIELD_BIJECTION")
        if tuple((item.field_id, item.action) for item in self.affected) != EXPECTED_FIELD_ACTIONS:
            raise ValueError("INVALID_4_56_PARTITION")
        if not {field_id for field_id, _ in EXPECTED_FIELD_ACTIONS} <= set(self.field_ids):
            raise ValueError("INVALID_4_56_PARTITION")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fixture_hash(self) -> str:
        return canonical_hash(
            FIXTURE_OBJECT_TYPE,
            self.model_dump(mode="python", exclude={"fixture_hash"}),
        )


class RetractionVerificationLinkV1(_FrozenModel):
    """Task-local join from explicit-absence Evidence to one 058 proof."""

    field_id: Literal["zh_f32c510a5e"]
    proof_hash: Sha256Hex
    evidence_hash: Sha256Hex
    candidate_snapshot_hash: Sha256Hex
    verification_hash: Sha256Hex
    task_hash: Sha256Hex
    receipt_hash: Sha256Hex

    @computed_field  # type: ignore[prop-decorator]
    @property
    def link_hash(self) -> str:
        return canonical_hash(
            RETRACTION_LINK_OBJECT_TYPE,
            self.model_dump(mode="python", exclude={"link_hash"}),
        )


class IncrementalUpdatePreimageV1(_FrozenModel):
    """Caller-owned exact 053/054/057 and 058 input custody."""

    contract: Literal["596-1-incremental-update-preimage.v1"]
    baseline_facts: tuple[VerifiedFactV1, ...]
    baseline_fact_hashes: tuple[Sha256Hex, ...]
    candidate_facts: tuple[VerifiedFactV1, ...]
    retraction_proofs: tuple[RetractionProofV1, ...]
    parsed_documents: tuple[ParsedDocumentV1, ...]
    parse_manifests: tuple[ParseManifestV1, ...]
    parse_quality_decisions: tuple[ParseQualityDecisionV1, ...]
    field_candidates: tuple[FieldCandidateV1, ...]
    verification_batches: tuple[VerificationBatchV1, ...]
    receipt_chains: tuple[ReceiptChainV1, ...]
    fact_verification_links: tuple[FactVerificationLinkV1, ...]
    retraction_verification_link: RetractionVerificationLinkV1
    repair_resolutions: tuple[RepairResolutionV1, ...]
    review_policy: HumanBatchPolicyV1

    @computed_field  # type: ignore[prop-decorator]
    @property
    def preimage_hash(self) -> str:
        return canonical_hash(
            PREIMAGE_OBJECT_TYPE,
            self.model_dump(mode="python", exclude={"preimage_hash"}),
        )


class IncrementalActionReceiptV1(_FrozenModel):
    field_id: NonBlankStr
    action: Action
    item_hash: Sha256Hex
    incoming_fact_hash: Sha256Hex | None
    prior_fact_hashes: tuple[Sha256Hex, ...]
    evidence_hashes: tuple[Sha256Hex, ...]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def action_receipt_hash(self) -> str:
        return canonical_hash(
            ACTION_OBJECT_TYPE,
            self.model_dump(mode="python", exclude={"action_receipt_hash"}),
        )


class IncrementalUpdateReceiptV1(_FrozenModel):
    contract: Literal["596-1-incremental-update-receipt.v1"]
    fixture_hash: Sha256Hex
    preimage_hash: Sha256Hex
    space_id: Literal["space-078-fixture"]
    product_version_id: Literal["596-1"]
    field_count: Literal[60]
    affected_count: Literal[4]
    unchanged_count: Literal[56]
    actions: tuple[IncrementalActionReceiptV1, ...]
    unchanged_fact_hashes: tuple[Sha256Hex, ...]
    change_set_hash: Sha256Hex
    candidate_hash: Sha256Hex
    human_batch_hash: Sha256Hex
    human_review_field_ids: tuple[NonBlankStr, ...]
    release_authority: Literal["NONE_FIXTURE_ONLY"] = "NONE_FIXTURE_ONLY"

    @model_validator(mode="after")
    def require_exact_result_partition(self) -> Self:
        action_keys = tuple((item.field_id, item.action_receipt_hash) for item in self.actions)
        if (
            tuple((item.field_id, item.action) for item in self.actions)
            != tuple(sorted(EXPECTED_FIELD_ACTIONS))
            or action_keys != tuple(sorted(action_keys))
            or len(self.unchanged_fact_hashes) != 56
            or self.unchanged_fact_hashes != tuple(sorted(set(self.unchanged_fact_hashes)))
            or self.human_review_field_ids != tuple(sorted(set(self.human_review_field_ids)))
        ):
            raise ValueError("INVALID_078_RESULT_PARTITION")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def receipt_hash(self) -> str:
        return canonical_hash(
            RECEIPT_OBJECT_TYPE,
            self.model_dump(mode="python", exclude={"receipt_hash"}),
        )


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _synthetic_hash(object_type: str, **payload: str) -> str:
    return canonical_hash(object_type, payload)


def _value_hash(field_id: str, tag: str) -> str:
    return _synthetic_hash(VALUE_OBJECT_TYPE, field_id=field_id, tag=tag)


def _quote(field_id: str, source_revision_id: str, tag: str) -> str:
    return f"synthetic-evidence:{field_id}:{source_revision_id}:{tag}"


def _evidence_hash(field_id: str, source_revision_id: str, tag: str) -> str:
    return _synthetic_hash(
        EVIDENCE_OBJECT_TYPE,
        field_id=field_id,
        source_revision_id=source_revision_id,
        quote_sha256=_hash_text(_quote(field_id, source_revision_id, tag)),
    )


def _load_fixture(path: Path) -> _FixtureV1:
    if not isinstance(path, Path):
        raise IncrementalUpdateFixtureError("INVALID_FIXTURE_PATH")
    try:
        return _FixtureV1.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError):
        raise IncrementalUpdateFixtureError("INVALID_SYNTHETIC_FIXTURE") from None


def _revalidate_authority_inputs(
    catalog_value: MaterialProfileCatalog,
    resolution_values: Iterable[MaterialProfileResolution],
) -> tuple[MaterialProfileCatalog, tuple[MaterialProfileResolution, ...]]:
    try:
        if not isinstance(catalog_value, MaterialProfileCatalog):
            raise TypeError
        raw_resolutions = tuple(resolution_values)
        if len(raw_resolutions) != 3 or any(
            not isinstance(value, MaterialProfileResolution) for value in raw_resolutions
        ):
            raise TypeError
        catalog = MaterialProfileCatalog.model_validate(
            catalog_value.model_dump(mode="python", exclude_computed_fields=True)
        )
        resolutions = tuple(
            MaterialProfileResolution.model_validate(
                value.model_dump(mode="python", exclude_computed_fields=True)
            )
            for value in raw_resolutions
        )
    except (TypeError, ValueError, ValidationError):
        raise IncrementalUpdateFixtureError("AUTHORITY_INPUT_INVALID") from None
    if {item.profile.material_role for item in resolutions} != {
        "terms",
        "brochure",
        "rate_table",
    }:
        raise IncrementalUpdateFixtureError("AUTHORITY_INPUT_INVALID")
    return catalog, tuple(sorted(resolutions, key=lambda item: item.profile.material_role))


def _revalidate_preimage(value: object) -> IncrementalUpdatePreimageV1:
    try:
        if not isinstance(value, IncrementalUpdatePreimageV1):
            raise TypeError
        clean = IncrementalUpdatePreimageV1.model_validate(
            value.model_dump(mode="python", exclude_computed_fields=True)
        )
        payload = clean.model_dump(mode="python", exclude_computed_fields=True)
        payload.update(
            baseline_facts=tuple(sorted(clean.baseline_facts, key=lambda item: item.fact_hash)),
            baseline_fact_hashes=tuple(sorted(clean.baseline_fact_hashes)),
            candidate_facts=tuple(sorted(clean.candidate_facts, key=lambda item: item.fact_hash)),
            retraction_proofs=tuple(
                sorted(clean.retraction_proofs, key=lambda item: item.proof_hash)
            ),
            parsed_documents=tuple(
                sorted(clean.parsed_documents, key=lambda item: item.document_hash)
            ),
            parse_manifests=tuple(
                sorted(clean.parse_manifests, key=lambda item: item.manifest_hash)
            ),
            parse_quality_decisions=tuple(
                sorted(clean.parse_quality_decisions, key=lambda item: item.decision_hash)
            ),
            field_candidates=tuple(
                sorted(
                    clean.field_candidates,
                    key=lambda item: item.candidate_snapshot_hash,
                )
            ),
            verification_batches=tuple(
                sorted(clean.verification_batches, key=lambda item: item.verification_hash)
            ),
            receipt_chains=tuple(
                sorted(
                    clean.receipt_chains,
                    key=lambda item: (
                        item.task_hash,
                        tuple(receipt.receipt_hash for receipt in item.receipts),
                    ),
                )
            ),
            fact_verification_links=tuple(
                sorted(clean.fact_verification_links, key=lambda item: item.fact_hash)
            ),
            repair_resolutions=tuple(
                sorted(clean.repair_resolutions, key=lambda item: item.resolution_hash)
            ),
        )
        return IncrementalUpdatePreimageV1.model_validate(payload)
    except (TypeError, ValueError, ValidationError):
        raise IncrementalUpdateFixtureError("INCREMENTAL_CUSTODY_INVALID") from None


def _schema60_hash(field_ids: tuple[str, ...]) -> str:
    return canonical_hash("s0q-5961-schema60-field-ids.v1", field_ids)


def _validate_schema60_authority(
    fixture: _FixtureV1,
    catalog: MaterialProfileCatalog,
    resolutions: tuple[MaterialProfileResolution, ...],
) -> None:
    observed = (
        fixture.field_ids,
        catalog.schema_binding.field_ids,
        *(item.request.schema_field_ids for item in resolutions),
    )
    if any(
        field_ids != fixture.field_ids
        or _schema60_hash(field_ids) != EXPECTED_SCHEMA60_FIELD_IDS_HASH
        for field_ids in observed
    ):
        raise IncrementalUpdateFixtureError("SCHEMA60_AUTHORITY_DRIFT")


def _assert_root_scope(fixture: _FixtureV1, fact: VerifiedFactV1) -> None:
    scope = fact.scope
    if (
        scope.space_id != fixture.space_id
        or scope.product_version_id != fixture.product_version_id
        or scope.subject_id != fixture.subject_id
        or scope.valid_from != "2026-01-01T00:00:00.000000Z"
        or scope.valid_through is not None
        or scope.region != "CN"
        or scope.channel != "all-approved-channels"
        or scope.population != "eligible-insured"
        or scope.conditions != ("plan=synthetic-standard",)
    ):
        raise IncrementalUpdateFixtureError("FACT_SCOPE_DRIFT")


def _assert_fact(
    fixture: _FixtureV1,
    fact: VerifiedFactV1,
    *,
    tag: str,
    role: str,
    revision: str,
    reliable_at: str,
    resolution: MaterialProfileResolution,
) -> None:
    _assert_root_scope(fixture, fact)
    authority = fact.authority
    binding = authority.binding
    affected_fields = {field_id for field_id, _ in EXPECTED_FIELD_ACTIONS}
    if (
        fact.state != "known"
        or fact.value_hash != _value_hash(fact.scope.field_id, tag)
        or len(fact.evidence_hashes) != 1
        or (
            fact.scope.field_id not in affected_fields
            and fact.evidence_hashes
            != (_evidence_hash(fact.scope.field_id, revision, tag),)
        )
        or fact.supporting_source_revision_ids != (revision,)
        or authority.source_id != resolution.profile.source.sha256
        or authority.source_revision_id != revision
        or authority.material_role != role
        or authority.reliable_at != reliable_at
        or binding.catalog_hash != resolution.catalog_hash
        or binding.binding_hash != resolution.binding_hash
        or binding.space_id != fixture.space_id
        or binding.product_version_id != fixture.product_version_id
        or binding.source_id != resolution.profile.source.sha256
        or binding.source_revision_id != revision
        or binding.material_role != role
    ):
        raise IncrementalUpdateFixtureError("FACT_CUSTODY_DRIFT")


def _validate_fact_partition(
    fixture: _FixtureV1,
    catalog: MaterialProfileCatalog,
    resolutions: tuple[MaterialProfileResolution, ...],
    preimage: IncrementalUpdatePreimageV1,
) -> None:
    baseline_by_field = {item.scope.field_id: item for item in preimage.baseline_facts}
    candidate_by_field = {item.scope.field_id: item for item in preimage.candidate_facts}
    affected = {item.field_id: item for item in fixture.affected}
    if (
        len(preimage.baseline_facts) != 60
        or set(baseline_by_field) != set(fixture.field_ids)
        or len(preimage.candidate_facts) != 3
        or set(candidate_by_field)
        != {field_id for field_id, action in EXPECTED_FIELD_ACTIONS if action != "retract"}
        or len(preimage.retraction_proofs) != 1
        or preimage.baseline_fact_hashes
        != tuple(sorted(item.fact_hash for item in preimage.baseline_facts))
    ):
        raise IncrementalUpdateFixtureError("FACT_PARTITION_DRIFT")
    by_role = {item.profile.material_role: item for item in resolutions}
    old_time = "2026-01-01T00:00:00.000000Z"
    new_time = "2026-02-01T00:00:00.000000Z"
    for field_id in fixture.field_ids:
        scenario = affected.get(field_id)
        if scenario is None:
            role = catalog.authority_for(field_id).primary_role
            _assert_fact(
                fixture,
                baseline_by_field[field_id],
                tag=f"synthetic-unchanged-{field_id}",
                role=role,
                revision=f"revision-078-{role}-unchanged",
                reliable_at=old_time,
                resolution=by_role[role],
            )
            continue
        role = "brochure" if scenario.action == "supersede" else "terms"
        _assert_fact(
            fixture,
            baseline_by_field[field_id],
            tag=scenario.baseline_value_tag,
            role=role,
            revision=f"revision-078-{role}-old",
            reliable_at=old_time,
            resolution=by_role[role],
        )
        if scenario.action != "retract":
            if scenario.candidate_value_tag is None:
                raise IncrementalUpdateFixtureError("FACT_CUSTODY_DRIFT")
            _assert_fact(
                fixture,
                candidate_by_field[field_id],
                tag=scenario.candidate_value_tag,
                role="terms",
                revision="revision-078-terms-new",
                reliable_at=old_time if scenario.action == "conflict" else new_time,
                resolution=by_role["terms"],
            )
    proof = preimage.retraction_proofs[0]
    retract_field = EXPECTED_FIELD_ACTIONS[-1][0]
    replacement = proof.replacement_authority
    if (
        proof.scope != baseline_by_field[retract_field].scope
        or proof.old_source_revision_id != "revision-078-terms-old"
        or not proof.complete_scope
        or not proof.explicitly_absent
        or proof.reason_code != "source_revision_replaced"
        or replacement.source_revision_id != "revision-078-terms-new"
        or replacement.material_role != "terms"
        or replacement.reliable_at != new_time
        or replacement.binding.binding_hash != by_role["terms"].binding_hash
    ):
        raise IncrementalUpdateFixtureError("RETRACTION_CUSTODY_DRIFT")


def _expected_fact_tag(
    fixture: _FixtureV1,
    fact: VerifiedFactV1,
) -> str:
    scenario = next(
        (item for item in fixture.affected if item.field_id == fact.scope.field_id),
        None,
    )
    if scenario is None:
        return f"synthetic-unchanged-{fact.scope.field_id}"
    if fact.authority.source_revision_id == "revision-078-terms-new":
        if scenario.candidate_value_tag is None:
            raise IncrementalUpdateFixtureError("FIELD_CANDIDATE_CUSTODY_DRIFT")
        return scenario.candidate_value_tag
    return scenario.baseline_value_tag


def _absence_evidence_hash(candidate: FieldCandidateV1) -> str:
    if len(candidate.evidence) != 1:
        raise IncrementalUpdateFixtureError("RETRACTION_EVIDENCE_CUSTODY_DRIFT")
    return canonical_hash(
        "s0q-5961-explicit-absence-evidence.v1",
        candidate.evidence[0].model_dump(mode="python"),
    )


def _known_evidence_hash(candidate: FieldCandidateV1) -> str:
    if len(candidate.evidence) != 1:
        raise IncrementalUpdateFixtureError("FIELD_CANDIDATE_CUSTODY_DRIFT")
    return canonical_hash(
        "s0q-5961-known-evidence-snapshot.v1",
        candidate.evidence[0].model_dump(mode="python"),
    )


def _candidate_rule_for_fact(
    fixture: _FixtureV1,
    fact: VerifiedFactV1,
    candidate: FieldCandidateV1,
) -> FieldRuleV1:
    tag = _expected_fact_tag(fixture, fact)
    expected_value = CandidateValueV1(kind="enum", enum_value=tag)
    if (
        candidate.field_id != fact.scope.field_id
        or candidate.product_version_id != fixture.product_version_id
        or candidate.subject_id != fixture.subject_id
        or candidate.condition_ids != fact.scope.conditions
        or candidate.tri_state != "present"
        or candidate.value != expected_value
        or len(candidate.evidence) != 1
        or fact.evidence_hashes != (_known_evidence_hash(candidate),)
    ):
        raise IncrementalUpdateFixtureError("FIELD_CANDIDATE_CUSTODY_DRIFT")
    evidence = candidate.evidence[0]
    if (
        evidence.field_id != fact.scope.field_id
        or evidence.product_version_id != fixture.product_version_id
        or evidence.source_revision_id != fact.authority.source_revision_id
        or evidence.quote_snapshot != tag
        or evidence.support_scope.product_version_id != fixture.product_version_id
        or evidence.support_scope.subject_id != fixture.subject_id
        or evidence.support_scope.condition_ids != fact.scope.conditions
    ):
        raise IncrementalUpdateFixtureError("FIELD_CANDIDATE_CUSTODY_DRIFT")
    return FieldRuleV1(
        field_id=fact.scope.field_id,
        value_kind="enum",
        allowed_values=(tag,),
        allow_absent=False,
    )


def _absence_rule(
    fixture: _FixtureV1,
    candidate: FieldCandidateV1,
) -> FieldRuleV1:
    if (
        candidate.field_id != EXPECTED_FIELD_ACTIONS[-1][0]
        or candidate.product_version_id != fixture.product_version_id
        or candidate.subject_id != fixture.subject_id
        or candidate.condition_ids
        != ("plan=synthetic-standard",)
        or candidate.tri_state != "absent_explicitly"
        or candidate.value is not None
        or len(candidate.evidence) != 1
    ):
        raise IncrementalUpdateFixtureError("RETRACTION_EVIDENCE_CUSTODY_DRIFT")
    evidence = candidate.evidence[0]
    if (
        evidence.field_id != candidate.field_id
        or evidence.product_version_id != fixture.product_version_id
        or evidence.source_revision_id != "revision-078-terms-new"
        or evidence.quote_snapshot != EXPLICIT_ABSENCE_MARKER
        or evidence.support_scope.product_version_id != fixture.product_version_id
        or evidence.support_scope.subject_id != fixture.subject_id
        or evidence.support_scope.condition_ids != candidate.condition_ids
    ):
        raise IncrementalUpdateFixtureError("RETRACTION_EVIDENCE_CUSTODY_DRIFT")
    return FieldRuleV1(
        field_id=candidate.field_id,
        value_kind="enum",
        allowed_values=(EXPLICIT_ABSENCE_MARKER,),
        absence_markers=(EXPLICIT_ABSENCE_MARKER,),
        allow_absent=True,
    )


def _validate_parse_and_receipt_custody(
    fixture: _FixtureV1,
    catalog: MaterialProfileCatalog,
    resolutions: tuple[MaterialProfileResolution, ...],
    preimage: IncrementalUpdatePreimageV1,
) -> None:
    if (
        len(preimage.parsed_documents) != 3
        or len(preimage.parse_manifests) != 3
        or len(preimage.parse_quality_decisions) != 3
        or len(preimage.field_candidates) != 8
        or len(preimage.verification_batches) != 8
        or len(preimage.receipt_chains) != 8
        or len(preimage.fact_verification_links) != 7
        or preimage.repair_resolutions
        or preimage.review_policy
        != HumanBatchPolicyV1(
            policy_id="078-synthetic-review-policy-v1",
            high_risk_field_ids=(EXPECTED_FIELD_ACTIONS[-1][0],),
        )
    ):
        raise IncrementalUpdateFixtureError("CUSTODY_CARDINALITY_DRIFT")
    if any(
        len({getattr(item, attr) for item in values}) != len(values)
        for values, attr in (
            (preimage.parsed_documents, "document_hash"),
            (preimage.parse_manifests, "manifest_hash"),
            (preimage.parse_quality_decisions, "decision_hash"),
            (preimage.field_candidates, "candidate_snapshot_hash"),
            (preimage.verification_batches, "verification_hash"),
            (preimage.receipt_chains, "task_hash"),
            (preimage.fact_verification_links, "fact_hash"),
        )
    ):
        raise IncrementalUpdateFixtureError("CUSTODY_DUPLICATE_OR_AMBIGUOUS")
    resolution_by_profile = {item.profile.profile_id: item for item in resolutions}
    manifests = {item.document_hash: item for item in preimage.parse_manifests}
    qualities = {item.manifest_hash: item for item in preimage.parse_quality_decisions}
    documents_by_hash = {item.document_hash: item for item in preimage.parsed_documents}
    for document in preimage.parsed_documents:
        resolution = resolution_by_profile.get(document.subject.material_profile_id)
        manifest = manifests.get(document.document_hash)
        if resolution is None or manifest is None:
            raise IncrementalUpdateFixtureError("PARSE_CUSTODY_DRIFT")
        quality = qualities.get(manifest.manifest_hash)
        if (
            quality is None
            or document.subject.space_id != fixture.space_id
            or document.subject.product_version_id != fixture.product_version_id
            or document.subject.material_profile_binding_hash != resolution.binding_hash
            or build_parse_manifest(document, resolution.profile) != manifest
            or evaluate_parse_quality(
                document=document,
                manifest=manifest,
                material_profile_resolution=resolution,
            )
            != quality
            or quality.decision != "ADMIT"
        ):
            raise IncrementalUpdateFixtureError("PARSE_CUSTODY_DRIFT")
    affected_facts = (*preimage.baseline_facts, *preimage.candidate_facts)
    expected_fact_hashes = {
        item.fact_hash
        for item in affected_facts
        if item.scope.field_id in {field_id for field_id, _ in EXPECTED_FIELD_ACTIONS}
    }
    if {item.fact_hash for item in preimage.fact_verification_links} != expected_fact_hashes:
        raise IncrementalUpdateFixtureError("FACT_RECEIPT_CUSTODY_DRIFT")
    facts_by_hash = {
        item.fact_hash: item for item in affected_facts if item.fact_hash in expected_fact_hashes
    }
    verification_by_hash = {item.verification_hash: item for item in preimage.verification_batches}
    candidates_by_hash = {
        item.candidate_snapshot_hash: item for item in preimage.field_candidates
    }
    verification_by_scope: dict[tuple[str, str], VerificationBatchV1] = {}
    for batch in preimage.verification_batches:
        if len(batch.results) != 1:
            raise IncrementalUpdateFixtureError("VERIFICATION_CUSTODY_DRIFT")
        key = (batch.results[0].field_id, batch.source_revision_id)
        if key in verification_by_scope:
            raise IncrementalUpdateFixtureError("VERIFICATION_CUSTODY_DRIFT")
        verification_by_scope[key] = batch
    for link in preimage.fact_verification_links:
        fact = facts_by_hash.get(link.fact_hash)
        linked_batch = verification_by_hash.get(link.verification_hash)
        if fact is None or linked_batch is None:
            raise IncrementalUpdateFixtureError("FACT_RECEIPT_CUSTODY_DRIFT")
        result = linked_batch.results[0]
        candidate = candidates_by_hash.get(link.candidate_snapshot_hash)
        candidate_document = documents_by_hash.get(linked_batch.parsed_document_hash)
        candidate_manifest = next(
            (
                item
                for item in preimage.parse_manifests
                if item.manifest_hash == linked_batch.parse_manifest_hash
            ),
            None,
        )
        if (
            candidate is None
            or candidate_document is None
            or candidate_manifest is None
            or link.field_id != fact.scope.field_id
            or linked_batch.source_revision_id != fact.authority.source_revision_id
            or result.field_id != fact.scope.field_id
            or result.status != "PASS"
            or result.candidate_snapshot_hash != link.candidate_snapshot_hash
        ):
            raise IncrementalUpdateFixtureError("FACT_RECEIPT_CUSTODY_DRIFT")
        rule = _candidate_rule_for_fact(fixture, fact, candidate)
        if (
            verify_evidence_batch(
                document=candidate_document,
                manifest=candidate_manifest,
                candidates=(candidate,),
                rules=(rule,),
            )
            != linked_batch
        ):
            raise IncrementalUpdateFixtureError("VERIFICATION_REPLAY_DRIFT")

    retraction_link = preimage.retraction_verification_link
    proof = preimage.retraction_proofs[0]
    absence_candidate = candidates_by_hash.get(
        retraction_link.candidate_snapshot_hash
    )
    absence_batch = verification_by_hash.get(retraction_link.verification_hash)
    if absence_candidate is None or absence_batch is None:
        raise IncrementalUpdateFixtureError("RETRACTION_EVIDENCE_CUSTODY_DRIFT")
    absence_document = documents_by_hash.get(absence_batch.parsed_document_hash)
    absence_manifest = next(
        (
            item
            for item in preimage.parse_manifests
            if item.manifest_hash == absence_batch.parse_manifest_hash
        ),
        None,
    )
    absence_rule = _absence_rule(fixture, absence_candidate)
    if (
        absence_document is None
        or absence_manifest is None
        or retraction_link.field_id != proof.scope.field_id
        or retraction_link.proof_hash != proof.proof_hash
        or retraction_link.evidence_hash != proof.evidence_hash
        or retraction_link.evidence_hash
        != _absence_evidence_hash(absence_candidate)
        or absence_batch.source_revision_id
        != proof.replacement_authority.source_revision_id
        or absence_batch.results[0].candidate_snapshot_hash
        != absence_candidate.candidate_snapshot_hash
        or verify_evidence_batch(
            document=absence_document,
            manifest=absence_manifest,
            candidates=(absence_candidate,),
            rules=(absence_rule,),
        )
        != absence_batch
    ):
        raise IncrementalUpdateFixtureError("RETRACTION_EVIDENCE_CUSTODY_DRIFT")
    used_candidate_hashes = {
        *(item.candidate_snapshot_hash for item in preimage.fact_verification_links),
        retraction_link.candidate_snapshot_hash,
    }
    if used_candidate_hashes != set(candidates_by_hash):
        raise IncrementalUpdateFixtureError("FIELD_CANDIDATE_CUSTODY_DRIFT")
    retraction_chain_seen = False
    for chain in preimage.receipt_chains:
        task = chain.task
        if (
            task.space_id != fixture.space_id
            or task.product_version_id != fixture.product_version_id
            or task.module_id != "078-synthetic-incremental-update"
            or len(task.field_ids) != 1
            or task.field_ids[0] not in {field_id for field_id, _ in EXPECTED_FIELD_ACTIONS}
        ):
            raise IncrementalUpdateFixtureError("RECEIPT_CHAIN_CUSTODY_DRIFT")
        chain_document = documents_by_hash.get(task.input_refs.parsed_document.artifact_hash)
        if chain_document is None:
            raise IncrementalUpdateFixtureError("RECEIPT_CHAIN_CUSTODY_DRIFT")
        manifest = manifests.get(chain_document.document_hash)
        quality = None if manifest is None else qualities.get(manifest.manifest_hash)
        resolution = resolution_by_profile.get(task.task_profile.material_profile.profile_id)
        if (
            manifest is None
            or quality is None
            or resolution is None
            or task.material_role != resolution.profile.material_role
            or task.task_profile.material_profile != resolution.profile
            or task.task_profile.material_profile_binding_hash != resolution.binding_hash
            or task.task_profile.parse_policy_receipt != resolution.parse_policy_receipt
        ):
            raise IncrementalUpdateFixtureError("RECEIPT_CHAIN_CUSTODY_DRIFT")
        expected_refs = ParsedArtifactAdmissionPort().admitted_input_refs(
            task_profile=task.task_profile,
            space_id=fixture.space_id,
            product_version_id=fixture.product_version_id,
            source_revision_id=task.source_revision_id,
            source_revision=ArtifactRefV1(
                object_type="source-revision.v1",
                artifact_hash=_synthetic_hash(
                    "s0q-5961-source-revision.v1",
                    revision=task.source_revision_id,
                ),
            ),
            resolved_template=ArtifactRefV1(
                object_type="resolved-template.v1",
                artifact_hash=resolution.resolved_template.content_hash,
            ),
            schema_contract=ArtifactRefV1(
                object_type="schema-contract.v1",
                artifact_hash=_synthetic_hash(
                    "s0q-5961-schema-contract.v1",
                    schema_version=fixture.schema_version,
                    field_count="60",
                ),
            ),
            document=chain_document,
            manifest=manifest,
            quality_decision=quality,
        )
        if task.input_refs != expected_refs:
            raise IncrementalUpdateFixtureError("RECEIPT_CHAIN_CUSTODY_DRIFT")
        chain_batch = verification_by_scope.get((task.field_ids[0], task.source_revision_id))
        if chain_batch is None:
            raise IncrementalUpdateFixtureError("RECEIPT_CHAIN_CUSTODY_DRIFT")
        bound_receipt = bind_054_attempt_receipt(
            chain=chain,
            verification=chain_batch,
        )
        if chain.task_hash == retraction_link.task_hash:
            if (
                retraction_chain_seen
                or bound_receipt.receipt_hash != retraction_link.receipt_hash
                or chain_batch.verification_hash != retraction_link.verification_hash
            ):
                raise IncrementalUpdateFixtureError(
                    "RETRACTION_EVIDENCE_CUSTODY_DRIFT"
                )
            retraction_chain_seen = True
    if not retraction_chain_seen:
        raise IncrementalUpdateFixtureError("RETRACTION_EVIDENCE_CUSTODY_DRIFT")
    for batch in preimage.verification_batches:
        verification_document = documents_by_hash.get(batch.parsed_document_hash)
        verification_manifest = next(
            (
                item
                for item in preimage.parse_manifests
                if item.manifest_hash == batch.parse_manifest_hash
            ),
            None,
        )
        if (
            verification_document is None
            or verification_manifest is None
            or verification_manifest.document_hash != verification_document.document_hash
        ):
            raise IncrementalUpdateFixtureError("VERIFICATION_CUSTODY_DRIFT")


def _run(
    fixture: _FixtureV1,
    catalog: MaterialProfileCatalog,
    resolutions: tuple[MaterialProfileResolution, ...],
    preimage: IncrementalUpdatePreimageV1,
) -> IncrementalUpdateReceiptV1:
    if (
        fixture.field_ids != catalog.schema_binding.field_ids
        or fixture.schema_version != catalog.schema_binding.schema_version
        or fixture.product_version_id != catalog.product.product_version
        or any(
            item.request.space_id != fixture.space_id
            or item.request.product_version != fixture.product_version_id
            for item in resolutions
        )
    ):
        raise IncrementalUpdateFixtureError("FIXTURE_AUTHORITY_IDENTITY_DRIFT")
    _validate_fact_partition(fixture, catalog, resolutions, preimage)
    _validate_parse_and_receipt_custody(fixture, catalog, resolutions, preimage)
    change_set = compile_incremental_changes(
        space_id=fixture.space_id,
        product_version_id=fixture.product_version_id,
        material_profile_catalog=catalog,
        material_profile_resolutions=resolutions,
        baseline_facts=preimage.baseline_facts,
        candidate_facts=preimage.candidate_facts,
        retraction_proofs=preimage.retraction_proofs,
    )
    expected_by_field = dict(EXPECTED_FIELD_ACTIONS)
    if {item.scope.field_id: item.action for item in change_set.items} != expected_by_field or any(
        item.action == "add" for item in change_set.items
    ):
        raise IncrementalUpdateFixtureError("FOUR_ACTION_MATRIX_MISMATCH")
    affected_fields = set(expected_by_field)
    unchanged = tuple(
        sorted(
            fact.fact_hash
            for fact in preimage.baseline_facts
            if fact.scope.field_id not in affected_fields
        )
    )
    referenced_hashes = {
        fact_hash
        for item in change_set.items
        for fact_hash in (
            *item.prior_fact_hashes,
            *((item.incoming_fact_hash,) if item.incoming_fact_hash else ()),
        )
    }
    affected_facts = tuple(
        sorted(
            (
                fact
                for fact in (*preimage.baseline_facts, *preimage.candidate_facts)
                if fact.fact_hash in referenced_hashes
            ),
            key=lambda item: item.fact_hash,
        )
    )
    if len(unchanged) != 56 or set(unchanged) & referenced_hashes or len(affected_facts) != 7:
        raise IncrementalUpdateFixtureError("UNCHANGED_FACT_ENTERED_CANDIDATE")
    assembly = build_fixture_candidate_batch(
        change_set=change_set,
        facts=affected_facts,
        verification_batches=tuple(
            item
            for item in preimage.verification_batches
            if item.verification_hash
            != preimage.retraction_verification_link.verification_hash
        ),
        receipt_chains=tuple(
            item
            for item in preimage.receipt_chains
            if item.task_hash != preimage.retraction_verification_link.task_hash
        ),
        fact_verification_links=preimage.fact_verification_links,
        repair_resolutions=preimage.repair_resolutions,
        review_policy=preimage.review_policy,
    )
    candidate_fields = {item.item.scope.field_id for item in assembly.candidate.changes}
    review_fields = tuple(item.field_id for item in assembly.human_batch.items)
    if candidate_fields != affected_fields or set(review_fields) - affected_fields:
        raise IncrementalUpdateFixtureError("CANDIDATE_PARTITION_MISMATCH")
    actions = tuple(
        sorted(
            (
                IncrementalActionReceiptV1(
                    field_id=item.scope.field_id,
                    action=item.action,
                    item_hash=item.item_hash,
                    incoming_fact_hash=item.incoming_fact_hash,
                    prior_fact_hashes=item.prior_fact_hashes,
                    evidence_hashes=item.evidence_hashes,
                )
                for item in change_set.items
                if item.action != "add"
            ),
            key=lambda item: (item.field_id, item.action_receipt_hash),
        )
    )
    return IncrementalUpdateReceiptV1(
        contract="596-1-incremental-update-receipt.v1",
        fixture_hash=fixture.fixture_hash,
        preimage_hash=preimage.preimage_hash,
        space_id=fixture.space_id,
        product_version_id=fixture.product_version_id,
        field_count=60,
        affected_count=4,
        unchanged_count=56,
        actions=actions,
        unchanged_fact_hashes=unchanged,
        change_set_hash=change_set.change_set_hash,
        candidate_hash=assembly.candidate.candidate_hash,
        human_batch_hash=assembly.human_batch.batch_hash,
        human_review_field_ids=tuple(sorted(review_fields)),
    )


def run_incremental_update_fixture(
    fixture_path: Path,
    *,
    material_profile_catalog: MaterialProfileCatalog,
    material_profile_resolutions: Iterable[MaterialProfileResolution],
    preimage: IncrementalUpdatePreimageV1 | None = None,
) -> IncrementalUpdateReceiptV1:
    """Revalidate caller-owned custody and compose merged public contracts."""

    fixture = _load_fixture(fixture_path)
    catalog, resolutions = _revalidate_authority_inputs(
        material_profile_catalog, material_profile_resolutions
    )
    if material_profile_catalog_hash(catalog) != resolutions[0].catalog_hash:
        raise IncrementalUpdateFixtureError("AUTHORITY_INPUT_INVALID")
    _validate_schema60_authority(fixture, catalog, resolutions)
    frozen_preimage = _revalidate_preimage(preimage)
    try:
        return _run(fixture, catalog, resolutions, frozen_preimage)
    except IncrementalUpdateFixtureError:
        raise
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        reason = getattr(exc, "reason_code", "INCREMENTAL_CUSTODY_INVALID")
        raise IncrementalUpdateFixtureError(str(reason)) from None


__all__ = [
    "IncrementalActionReceiptV1",
    "IncrementalUpdateFixtureError",
    "IncrementalUpdatePreimageV1",
    "IncrementalUpdateReceiptV1",
    "RetractionVerificationLinkV1",
    "run_incremental_update_fixture",
]
