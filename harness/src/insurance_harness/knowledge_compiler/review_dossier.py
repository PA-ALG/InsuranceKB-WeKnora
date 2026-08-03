"""Pure display-only dossier for one exact fixture Candidate human batch."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Annotated, Any, Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictStr,
    StringConstraints,
    ValidationError,
    computed_field,
)

from insurance_harness.canonical import canonical_bytes, canonical_hash
from insurance_harness.compiler.evidence_verifier import (
    FieldCandidateV1,
    FieldVerificationV1,
    RepairResolutionV1,
    VerificationBatchV1,
    value_snapshot,
)
from insurance_harness.knowledge_compiler.candidate_batches import (
    CandidateAssemblyV1,
    CandidateChangeV1,
    HumanReviewItemV1,
)
from insurance_harness.knowledge_compiler.incremental_changes import VerifiedFactV1

DISPLAY_AUTHORITY: Final[Literal["DISPLAY_ONLY_REQUIRES_NAMED_HUMAN"]] = (
    "DISPLAY_ONLY_REQUIRES_NAMED_HUMAN"
)
DOSSIER_OBJECT_TYPE: Final[str] = "release-human-review-dossier.v1"
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ChangeCategory = Literal["add", "update", "conflict", "retract"]
RawAction = Literal["add", "enrich", "supersede", "conflict", "retract"]


class ReviewDossierError(ValueError):
    """Typed fail-closed result for incomplete or inconsistent display custody."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        del deep
        values = self.model_dump(
            mode="python",
            round_trip=True,
            warnings=False,
            exclude_computed_fields=True,
        )
        if update is not None:
            values.update(dict(update))
        return type(self).model_validate(values)


class DossierCountsV1(_FrozenModel):
    add: int
    update: int
    conflict: int
    retract: int
    high_risk: int
    repair: int
    gap: int


class DossierFactV1(_FrozenModel):
    fact: VerifiedFactV1
    verification_hash: Sha256Hex
    verification_result: FieldVerificationV1
    candidate_snapshot_hash: Sha256Hex
    field_candidate: FieldCandidateV1


class DossierChangeV1(_FrozenModel):
    category: ChangeCategory
    raw_action: RawAction
    field_id: str
    change_item_hash: Sha256Hex
    reason: str
    incoming_fact: DossierFactV1 | None
    prior_facts: tuple[DossierFactV1, ...]
    retraction_proof_hash: Sha256Hex | None


class ReviewDossierV1(_FrozenModel):
    contract: Literal["release-human-review-dossier.v1"]
    authority: Literal["DISPLAY_ONLY_REQUIRES_NAMED_HUMAN"]
    upstream_authority: Literal["NONE_REQUIRES_NAMED_HUMAN"]
    space_id: str
    product_version_id: str
    candidate_hash: Sha256Hex
    human_batch_hash: Sha256Hex
    policy_hash: Sha256Hex
    change_set_hash: Sha256Hex
    counts: DossierCountsV1
    changes: tuple[DossierChangeV1, ...]
    review_items: tuple[HumanReviewItemV1, ...]
    repair_resolutions: tuple[RepairResolutionV1, ...]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dossier_hash(self) -> str:
        return canonical_hash(
            DOSSIER_OBJECT_TYPE,
            self.model_dump(mode="python", exclude={"dossier_hash"}),
        )


def _revalidate_assembly(value: object) -> CandidateAssemblyV1:
    if not isinstance(value, CandidateAssemblyV1):
        raise ReviewDossierError("candidate_assembly_invalid")
    try:
        return CandidateAssemblyV1.model_validate(
            value.model_dump(mode="python", exclude_computed_fields=True)
        )
    except (TypeError, ValueError, ValidationError):
        raise ReviewDossierError("candidate_assembly_invalid") from None


def _revalidate_candidates(values: Iterable[object]) -> tuple[FieldCandidateV1, ...]:
    candidates: list[FieldCandidateV1] = []
    for value in values:
        if not isinstance(value, FieldCandidateV1):
            raise ReviewDossierError("field_candidate_invalid")
        try:
            candidates.append(
                FieldCandidateV1.model_validate(
                    value.model_dump(mode="python", exclude_computed_fields=True)
                )
            )
        except (TypeError, ValueError, ValidationError):
            raise ReviewDossierError("field_candidate_invalid") from None
    return tuple(candidates)


def _fact_candidate(
    *,
    fact: VerifiedFactV1,
    candidate: FieldCandidateV1,
    verification: VerificationBatchV1,
    verification_result: FieldVerificationV1,
    candidate_snapshot_hash: str,
) -> DossierFactV1:
    if candidate.candidate_snapshot_hash != candidate_snapshot_hash:
        raise ReviewDossierError("field_candidate_snapshot_mismatch")
    scope = fact.scope
    if (
        candidate.field_id != scope.field_id
        or candidate.product_version_id != scope.product_version_id
        or candidate.subject_id != scope.subject_id
        or candidate.condition_ids != scope.conditions
    ):
        raise ReviewDossierError("field_candidate_scope_mismatch")
    if fact.state != "known" or candidate.tri_state != "present" or candidate.value is None:
        raise ReviewDossierError("field_candidate_state_mismatch")
    expected_value_hash = hashlib.sha256(
        value_snapshot(candidate.value).encode("utf-8")
    ).hexdigest()
    if fact.value_hash != expected_value_hash:
        raise ReviewDossierError("field_candidate_value_mismatch")
    if (
        verification_result.field_id != scope.field_id
        or verification_result.status != "PASS"
        or verification_result.candidate_snapshot_hash != candidate_snapshot_hash
    ):
        raise ReviewDossierError("field_candidate_verification_mismatch")
    if not candidate.evidence:
        raise ReviewDossierError("field_candidate_locator_missing")
    for evidence in candidate.evidence:
        if evidence.source_revision_id != verification.source_revision_id:
            raise ReviewDossierError("field_candidate_source_revision_mismatch")
        if evidence.support_scope.product_version_id != scope.product_version_id:
            raise ReviewDossierError("field_candidate_support_scope_mismatch")
        if (
            evidence.field_id != scope.field_id
            or evidence.product_version_id != scope.product_version_id
            or evidence.source_revision_id not in fact.supporting_source_revision_ids
            or evidence.support_scope.subject_id != scope.subject_id
            or evidence.support_scope.condition_ids != scope.conditions
            or evidence.value_snapshot != value_snapshot(candidate.value)
            or evidence.parse_attempt_id != verification.parse_attempt_id
            or evidence.parsed_document_hash != verification.parsed_document_hash
            or evidence.parse_manifest_hash != verification.parse_manifest_hash
        ):
            if (
                evidence.parse_attempt_id != verification.parse_attempt_id
                or evidence.parsed_document_hash != verification.parsed_document_hash
                or evidence.parse_manifest_hash != verification.parse_manifest_hash
            ):
                raise ReviewDossierError("field_candidate_parse_identity_mismatch")
            raise ReviewDossierError("field_candidate_locator_mismatch")
    return DossierFactV1(
        fact=fact,
        verification_hash=verification.verification_hash,
        verification_result=verification_result,
        candidate_snapshot_hash=candidate_snapshot_hash,
        field_candidate=candidate,
    )


def _category(action: RawAction) -> ChangeCategory:
    if action in {"enrich", "supersede"}:
        return "update"
    if action == "add":
        return "add"
    if action == "conflict":
        return "conflict"
    return "retract"


def _dossier_change(
    change: CandidateChangeV1,
    *,
    links_by_fact: dict[str, tuple[str, str, str]],
    candidates_by_hash: dict[str, FieldCandidateV1],
    verification_results: dict[
        tuple[str, str], tuple[VerificationBatchV1, FieldVerificationV1]
    ],
) -> DossierChangeV1:
    def bind(fact: VerifiedFactV1) -> DossierFactV1:
        try:
            linked_field, snapshot_hash, verification_hash = links_by_fact[fact.fact_hash]
            candidate = candidates_by_hash[snapshot_hash]
            verification, result = verification_results[(verification_hash, linked_field)]
        except KeyError:
            raise ReviewDossierError("field_candidate_membership_mismatch") from None
        if linked_field != fact.scope.field_id:
            raise ReviewDossierError("field_candidate_scope_mismatch")
        return _fact_candidate(
            fact=fact,
            candidate=candidate,
            verification=verification,
            verification_result=result,
            candidate_snapshot_hash=snapshot_hash,
        )

    item = change.item
    return DossierChangeV1(
        category=_category(item.action),
        raw_action=item.action,
        field_id=item.scope.field_id,
        change_item_hash=item.item_hash,
        reason=item.reason,
        incoming_fact=None if change.incoming_fact is None else bind(change.incoming_fact),
        prior_facts=tuple(bind(fact) for fact in change.prior_facts),
        retraction_proof_hash=item.retraction_proof_hash,
    )


def build_review_dossier(
    *,
    assembly: CandidateAssemblyV1,
    field_candidates: Iterable[FieldCandidateV1],
) -> ReviewDossierV1:
    """Join a complete immutable Candidate to its original locator-bearing inputs."""

    exact = _revalidate_assembly(assembly)
    candidates = _revalidate_candidates(field_candidates)
    candidate_hashes = tuple(item.candidate_snapshot_hash for item in candidates)
    if len(candidate_hashes) != len(set(candidate_hashes)):
        raise ReviewDossierError("field_candidate_duplicate")
    candidates_by_hash = {
        item.candidate_snapshot_hash: item
        for item in sorted(candidates, key=lambda value: value.candidate_snapshot_hash)
    }
    links_by_fact = {
        item.fact_hash: (
            item.field_id,
            item.candidate_snapshot_hash,
            item.verification_hash,
        )
        for item in exact.candidate.fact_verification_links
    }
    linked_hashes = tuple(item[1] for item in links_by_fact.values())
    if len(linked_hashes) != len(set(linked_hashes)):
        raise ReviewDossierError("field_candidate_link_ambiguous")
    required_hashes = set(linked_hashes)
    if set(candidates_by_hash) != required_hashes:
        raise ReviewDossierError("field_candidate_membership_mismatch")
    verification_results = {
        (verification.verification_hash, result.field_id): (verification, result)
        for verification in exact.candidate.verification_batches
        for result in verification.results
    }

    changes = tuple(
        sorted(
            (
                _dossier_change(
                    change,
                    links_by_fact=links_by_fact,
                    candidates_by_hash=candidates_by_hash,
                    verification_results=verification_results,
                )
                for change in exact.candidate.changes
            ),
            key=lambda item: (item.field_id, item.change_item_hash),
        )
    )
    action_counts = {
        action: sum(change.raw_action == action for change in changes)
        for action in ("add", "enrich", "supersede", "conflict", "retract")
    }
    gaps = sum(len(item.gaps) for item in exact.candidate.repair_resolutions)
    return ReviewDossierV1(
        contract="release-human-review-dossier.v1",
        authority=DISPLAY_AUTHORITY,
        upstream_authority=exact.human_batch.authority,
        space_id=exact.candidate.space_id,
        product_version_id=exact.candidate.product_version_id,
        candidate_hash=exact.candidate.candidate_hash,
        human_batch_hash=exact.human_batch.batch_hash,
        policy_hash=exact.human_batch.review_policy.policy_hash,
        change_set_hash=exact.candidate.change_set.change_set_hash,
        counts=DossierCountsV1(
            add=action_counts["add"],
            update=action_counts["enrich"] + action_counts["supersede"],
            conflict=action_counts["conflict"],
            retract=action_counts["retract"],
            high_risk=sum(
                "high_risk" in item.reasons for item in exact.human_batch.items
            ),
            repair=len(exact.candidate.repair_resolutions),
            gap=gaps,
        ),
        changes=changes,
        review_items=exact.human_batch.items,
        repair_resolutions=exact.candidate.repair_resolutions,
    )


def dossier_json_bytes(dossier: ReviewDossierV1) -> bytes:
    """Return deterministic C0 JSON bytes without writing or granting authority."""

    exact = ReviewDossierV1.model_validate(
        dossier.model_dump(mode="python", exclude_computed_fields=True)
    )
    return canonical_bytes(exact.model_dump(mode="python"))
