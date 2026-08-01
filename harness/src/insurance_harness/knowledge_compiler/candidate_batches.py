"""Pure fixture Candidate and human-batch envelopes for OpenSpec 059 PR1."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Annotated, Any, Final, Literal, Self

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
    RepairResolutionV1,
    VerificationBatchV1,
    bind_054_attempt_receipt,
)
from insurance_harness.compiler.extraction_receipts import ReceiptChainV1
from insurance_harness.compiler.extraction_tasks import ArtifactRefV1
from insurance_harness.knowledge_compiler.incremental_changes import (
    ChangeItemDraftV1,
    ChangeSetDraftV1,
    VerifiedFactV1,
)

NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=512, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ReviewReason = Literal["conflict", "high_risk", "repair_needed"]

FACT_VERIFICATION_LINK_OBJECT_TYPE: Final[str] = "fixture-fact-verification-link.v1"
HUMAN_BATCH_POLICY_OBJECT_TYPE: Final[str] = "fixture-human-batch-policy.v1"
CANDIDATE_CHANGE_OBJECT_TYPE: Final[str] = "fixture-candidate-change.v1"
FIXTURE_CANDIDATE_OBJECT_TYPE: Final[str] = "fixture-candidate.v1"
HUMAN_REVIEW_ITEM_OBJECT_TYPE: Final[str] = "fixture-human-review-item.v1"
HUMAN_BATCH_OBJECT_TYPE: Final[str] = "fixture-human-batch.v1"


class CandidateAssemblyError(ValueError):
    """Typed fail-closed result for malformed fixture Candidate composition."""

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


def _canonical_unique(values: tuple[str, ...], *, allow_empty: bool = True) -> bool:
    return (
        (allow_empty or bool(values))
        and values == tuple(sorted(values))
        and len(values) == len(set(values))
    )


class FactVerificationLinkV1(_FrozenModel):
    """Explicit content-addressed join; it grants no new verification authority."""

    fact_hash: Sha256Hex
    verification_hash: Sha256Hex
    field_id: NonBlankStr
    candidate_snapshot_hash: Sha256Hex

    @computed_field  # type: ignore[prop-decorator]
    @property
    def link_hash(self) -> str:
        return canonical_hash(
            FACT_VERIFICATION_LINK_OBJECT_TYPE,
            self.model_dump(mode="python", exclude={"link_hash"}),
        )


class HumanBatchPolicyV1(_FrozenModel):
    """One exact fixture policy, not a configurable review platform."""

    policy_id: NonBlankStr
    high_risk_field_ids: tuple[NonBlankStr, ...]

    @model_validator(mode="after")
    def require_canonical_high_risk_fields(self) -> Self:
        if not _canonical_unique(self.high_risk_field_ids):
            raise ValueError("high-risk fields must be canonical and unique")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def policy_hash(self) -> str:
        return canonical_hash(
            HUMAN_BATCH_POLICY_OBJECT_TYPE,
            self.model_dump(mode="python", exclude={"policy_hash"}),
        )


class CandidateChangeV1(_FrozenModel):
    """Exact 058 item plus the exact imported 058 fact objects it references."""

    item: ChangeItemDraftV1
    incoming_fact: VerifiedFactV1 | None
    prior_facts: tuple[VerifiedFactV1, ...]

    @model_validator(mode="after")
    def require_exact_058_fact_membership(self) -> Self:
        if tuple(fact.fact_hash for fact in self.prior_facts) != self.item.prior_fact_hashes:
            raise ValueError("prior_fact_membership_mismatch")
        if (None if self.incoming_fact is None else self.incoming_fact.fact_hash) != (
            self.item.incoming_fact_hash
        ):
            raise ValueError("incoming_fact_membership_mismatch")
        if (
            self.incoming_fact is not None
            and self.incoming_fact.fact_hash in self.item.prior_fact_hashes
        ):
            raise ValueError("competing_fact_membership_ambiguous")
        facts = (*self.prior_facts, *((self.incoming_fact,) if self.incoming_fact else ()))
        if any(fact.scope != self.item.scope for fact in facts):
            raise ValueError("change_fact_scope_mismatch")
        if self.item.action == "retract":
            if self.incoming_fact is not None:
                raise ValueError("retract_cannot_carry_incoming_fact")
        else:
            expected_evidence = tuple(
                sorted({evidence for fact in facts for evidence in fact.evidence_hashes})
            )
            if expected_evidence != self.item.evidence_hashes:
                raise ValueError("change_evidence_membership_mismatch")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def candidate_change_hash(self) -> str:
        return canonical_hash(
            CANDIDATE_CHANGE_OBJECT_TYPE,
            self.model_dump(mode="python", exclude={"candidate_change_hash"}),
        )


class FixtureCandidateV1(_FrozenModel):
    object_type: Literal["fixture_candidate.v1"] = "fixture_candidate.v1"
    space_id: NonBlankStr
    product_version_id: NonBlankStr
    schema_contract: ArtifactRefV1
    source_revision_ids: tuple[NonBlankStr, ...]
    change_set: ChangeSetDraftV1
    changes: tuple[CandidateChangeV1, ...]
    verification_batches: tuple[VerificationBatchV1, ...]
    receipt_chains: tuple[ReceiptChainV1, ...]
    fact_verification_links: tuple[FactVerificationLinkV1, ...]
    repair_resolutions: tuple[RepairResolutionV1, ...]

    @model_validator(mode="after")
    def require_canonical_exact_inputs(self) -> Self:
        if not _canonical_unique(self.source_revision_ids, allow_empty=False):
            raise ValueError("source revisions must be canonical and unique")
        if self.change_set.space_id != self.space_id or (
            self.change_set.product_version_id != self.product_version_id
        ):
            raise ValueError("candidate_change_set_scope_mismatch")
        if tuple(change.item for change in self.changes) != self.change_set.items:
            raise ValueError("candidate_change_set_membership_mismatch")
        if tuple(item.verification_hash for item in self.verification_batches) != tuple(
            sorted(item.verification_hash for item in self.verification_batches)
        ):
            raise ValueError("verification receipts must be canonical")
        chain_keys = tuple(
            (chain.task_hash, tuple(receipt.receipt_hash for receipt in chain.receipts))
            for chain in self.receipt_chains
        )
        if not chain_keys or chain_keys != tuple(sorted(chain_keys)) or (
            len(chain_keys) != len(set(chain_keys))
        ):
            raise ValueError("054 receipt chains must be canonical and unique")
        if tuple(item.fact_hash for item in self.fact_verification_links) != tuple(
            sorted(item.fact_hash for item in self.fact_verification_links)
        ):
            raise ValueError("fact receipt links must be canonical")
        if tuple(item.resolution_hash for item in self.repair_resolutions) != tuple(
            sorted(item.resolution_hash for item in self.repair_resolutions)
        ):
            raise ValueError("repair resolutions must be canonical")
        _validate_candidate_custody(self)
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def candidate_hash(self) -> str:
        return canonical_hash(
            FIXTURE_CANDIDATE_OBJECT_TYPE,
            self.model_dump(mode="python", exclude={"candidate_hash"}),
        )


class HumanReviewItemV1(_FrozenModel):
    field_id: NonBlankStr
    reasons: tuple[ReviewReason, ...]
    change_item_hash: Sha256Hex | None
    verification_hashes: tuple[Sha256Hex, ...]
    fact_hashes: tuple[Sha256Hex, ...]
    evidence_hashes: tuple[Sha256Hex, ...]

    @model_validator(mode="after")
    def require_canonical_review_custody(self) -> Self:
        for values in (
            self.reasons,
            self.verification_hashes,
            self.fact_hashes,
            self.evidence_hashes,
        ):
            if not _canonical_unique(values):
                raise ValueError("review custody must be canonical and unique")
        if not self.reasons:
            raise ValueError("review item requires a reason")
        if "conflict" in self.reasons and (
            self.change_item_hash is None or len(self.fact_hashes) < 2
        ):
            raise ValueError("conflict review requires all competing facts")
        if "repair_needed" in self.reasons and not self.verification_hashes:
            raise ValueError("repair review requires verification custody")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def review_item_hash(self) -> str:
        return canonical_hash(
            HUMAN_REVIEW_ITEM_OBJECT_TYPE,
            self.model_dump(mode="python", exclude={"review_item_hash"}),
        )


class HumanBatchV1(_FrozenModel):
    object_type: Literal["human_batch.v1"] = "human_batch.v1"
    candidate_hash: Sha256Hex
    review_policy: HumanBatchPolicyV1
    authority: Literal["NONE_REQUIRES_NAMED_HUMAN"] = "NONE_REQUIRES_NAMED_HUMAN"
    items: tuple[HumanReviewItemV1, ...]

    @model_validator(mode="after")
    def require_canonical_review_items(self) -> Self:
        keys = tuple((item.field_id, item.review_item_hash) for item in self.items)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("human batch items must be canonical and unique")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def batch_hash(self) -> str:
        return canonical_hash(
            HUMAN_BATCH_OBJECT_TYPE,
            self.model_dump(mode="python", exclude={"batch_hash"}),
        )


class CandidateAssemblyV1(_FrozenModel):
    candidate: FixtureCandidateV1
    human_batch: HumanBatchV1

    @model_validator(mode="after")
    def require_exact_candidate_binding(self) -> Self:
        if self.human_batch.candidate_hash != self.candidate.candidate_hash:
            raise ValueError("human_batch_candidate_mismatch")
        _validate_candidate_custody(self.candidate)
        expected_items = _expected_human_review_items(
            self.candidate,
            self.human_batch.review_policy,
        )
        if self.human_batch.items != expected_items:
            raise ValueError("human_batch_required_membership_mismatch")
        return self


def _revalidate_exact[ModelT: BaseModel](
    value: object, expected: type[ModelT], reason: str
) -> ModelT:
    if not isinstance(value, expected):
        raise CandidateAssemblyError(reason)
    try:
        return expected.model_validate(
            value.model_dump(mode="python", exclude_computed_fields=True)
        )
    except (TypeError, ValueError, ValidationError):
        raise CandidateAssemblyError(reason) from None


def _revalidate_many[ModelT: BaseModel](
    values: Iterable[object], expected: type[ModelT], reason: str
) -> tuple[ModelT, ...]:
    return tuple(_revalidate_exact(value, expected, reason) for value in values)


def _candidate_changes(
    change_set: ChangeSetDraftV1,
    facts_by_hash: dict[str, VerifiedFactV1],
) -> tuple[CandidateChangeV1, ...]:
    changes: list[CandidateChangeV1] = []
    for item in change_set.items:
        try:
            prior = tuple(facts_by_hash[value] for value in item.prior_fact_hashes)
            incoming = (
                None
                if item.incoming_fact_hash is None
                else facts_by_hash[item.incoming_fact_hash]
            )
            changes.append(
                CandidateChangeV1(
                    item=item,
                    incoming_fact=incoming,
                    prior_facts=prior,
                )
            )
        except (KeyError, ValidationError):
            raise CandidateAssemblyError("change_fact_membership_mismatch") from None
    return tuple(changes)


def _review_item_from_change(
    change: CandidateChangeV1,
    reasons: set[ReviewReason],
) -> HumanReviewItemV1:
    facts = (*change.prior_facts, *((change.incoming_fact,) if change.incoming_fact else ()))
    return HumanReviewItemV1(
        field_id=change.item.scope.field_id,
        reasons=tuple(sorted(reasons)),
        change_item_hash=change.item.item_hash,
        verification_hashes=(),
        fact_hashes=tuple(sorted(fact.fact_hash for fact in facts)),
        evidence_hashes=tuple(
            sorted({evidence for fact in facts for evidence in fact.evidence_hashes})
        ),
    )


def _validate_candidate_custody(candidate: FixtureCandidateV1) -> None:
    facts = tuple(
        fact
        for change in candidate.changes
        for fact in (
            *change.prior_facts,
            *((change.incoming_fact,) if change.incoming_fact else ()),
        )
    )
    facts_by_hash = {fact.fact_hash: fact for fact in facts}
    if len(facts_by_hash) != len(facts):
        raise ValueError("candidate_fact_membership_ambiguous")

    links_by_fact = {
        item.fact_hash: item for item in candidate.fact_verification_links
    }
    if len(links_by_fact) != len(candidate.fact_verification_links) or (
        set(links_by_fact) != set(facts_by_hash)
    ):
        raise ValueError("fact_receipt_bijection_mismatch")

    verification_by_hash = {
        item.verification_hash: item for item in candidate.verification_batches
    }
    if len(verification_by_hash) != len(candidate.verification_batches):
        raise ValueError("duplicate_verification_receipt")

    matched_verifications: set[str] = set()
    for chain in candidate.receipt_chains:
        task = chain.task
        if (
            task.space_id != candidate.space_id
            or task.product_version_id != candidate.product_version_id
            or task.input_refs.schema_contract != candidate.schema_contract
            or task.input_refs.schema_contract.object_type != "schema-contract.v1"
        ):
            raise ValueError("receipt_chain_scope_or_schema_mismatch")
        matches: list[str] = []
        for candidate_verification in candidate.verification_batches:
            try:
                bind_054_attempt_receipt(
                    chain=chain,
                    verification=candidate_verification,
                )
            except (TypeError, ValueError, ValidationError):
                continue
            matches.append(candidate_verification.verification_hash)
        if len(matches) != 1 or matches[0] in matched_verifications:
            raise ValueError("receipt_chain_verification_bijection_mismatch")
        matched_verifications.add(matches[0])
    if matched_verifications != set(verification_by_hash):
        raise ValueError("receipt_chain_verification_bijection_mismatch")

    used_verifications: set[str] = set()
    for fact_hash, fact in facts_by_hash.items():
        link = links_by_fact[fact_hash]
        fact_verification = verification_by_hash.get(link.verification_hash)
        if fact_verification is None:
            raise ValueError("fact_receipt_missing")
        result = next(
            (
                item
                for item in fact_verification.results
                if item.field_id == link.field_id
            ),
            None,
        )
        if (
            link.field_id != fact.scope.field_id
            or fact_verification.product_version_id != fact.scope.product_version_id
            or fact_verification.source_revision_id
            != fact.authority.source_revision_id
            or result is None
            or result.status != "PASS"
            or result.candidate_snapshot_hash != link.candidate_snapshot_hash
        ):
            raise ValueError("fact_verification_custody_mismatch")
        used_verifications.add(fact_verification.verification_hash)

    repair_parents: set[str] = set()
    repaired_fields: set[str] = set()
    for repair in candidate.repair_resolutions:
        parent = verification_by_hash.get(repair.parent_verification_hash)
        if parent is None or repair.parent_verification_hash in repair_parents:
            raise ValueError("repair_receipt_bijection_mismatch")
        repair_parents.add(repair.parent_verification_hash)
        parent_fields = tuple(item.field_id for item in parent.results)
        repair_fields = tuple(item.field_id for item in repair.results)
        parent_unresolved = tuple(
            item.field_id for item in parent.results if item.status != "PASS"
        )
        if (
            not parent_unresolved
            or parent_fields != repair_fields
            or len(parent_fields) != len(set(parent_fields))
        ):
            raise ValueError("repair_receipt_bijection_mismatch")
        repair_by_field = {item.field_id: item for item in repair.results}
        if any(
            repair_by_field[item.field_id] != item
            for item in parent.results
            if item.status == "PASS"
        ):
            raise ValueError("repair_parent_pass_result_drift")
        unresolved_results = tuple(
            item for item in repair.results if item.status != "PASS"
        )
        expected_gaps = tuple(
            (item.field_id, item.reason_codes) for item in unresolved_results
        )
        actual_gaps = tuple(
            (item.field_id, item.reason_codes) for item in repair.gaps
        )
        expected_reviews = tuple(
            (
                item.field_id,
                item.reason_codes[0],
                parent.verification_hash,
            )
            for item in unresolved_results
        )
        actual_reviews = tuple(
            (
                item.field_id,
                item.reason_code,
                item.parent_verification_hash,
            )
            for item in repair.review_items
        )
        review_fields = tuple(item.field_id for item in repair.review_items)
        if (
            actual_gaps != expected_gaps
            or actual_reviews != expected_reviews
            or len(review_fields) != len(set(review_fields))
            or any(field in repaired_fields for field in review_fields)
        ):
            raise ValueError("repair_receipt_bijection_mismatch")
        repaired_fields.update(review_fields)
        used_verifications.add(parent.verification_hash)
    if used_verifications != set(verification_by_hash):
        raise ValueError("unused_or_ambiguous_verification_receipt")

    expected_source_revisions = tuple(
        sorted(
            {
                *(chain.task.source_revision_id for chain in candidate.receipt_chains),
                *(
                    verification.source_revision_id
                    for verification in candidate.verification_batches
                ),
                *(fact.authority.source_revision_id for fact in facts),
                *(
                    revision
                    for fact in facts
                    for revision in fact.supporting_source_revision_ids
                ),
            }
        )
    )
    if candidate.source_revision_ids != expected_source_revisions:
        raise ValueError("candidate_source_revision_membership_mismatch")


def _expected_human_review_items(
    candidate: FixtureCandidateV1,
    policy: HumanBatchPolicyV1,
) -> tuple[HumanReviewItemV1, ...]:
    affected_fields = {change.item.scope.field_id for change in candidate.changes}
    if not set(policy.high_risk_field_ids) <= affected_fields:
        raise ValueError("high_risk_field_not_affected")

    review_items_by_field: dict[str, HumanReviewItemV1] = {}
    for change in candidate.changes:
        reasons: set[ReviewReason] = set()
        if change.item.action == "conflict":
            reasons.add("conflict")
        if change.item.scope.field_id in policy.high_risk_field_ids:
            reasons.add("high_risk")
        if reasons:
            review_items_by_field[change.item.scope.field_id] = _review_item_from_change(
                change, reasons
            )

    changes_by_field = {
        change.item.scope.field_id: change for change in candidate.changes
    }
    for repair in candidate.repair_resolutions:
        for review in repair.review_items:
            existing = review_items_by_field.get(review.field_id)
            repair_change = changes_by_field.get(review.field_id)
            facts_for_change = (
                ()
                if repair_change is None
                else (
                    *repair_change.prior_facts,
                    *((repair_change.incoming_fact,) if repair_change.incoming_fact else ()),
                )
            )
            repair_reasons: set[ReviewReason] = {"repair_needed"}
            verification_hashes = {repair.parent_verification_hash}
            if existing is not None:
                repair_reasons.update(existing.reasons)
                verification_hashes.update(existing.verification_hashes)
            review_items_by_field[review.field_id] = HumanReviewItemV1(
                field_id=review.field_id,
                reasons=tuple(sorted(repair_reasons)),
                change_item_hash=(
                    None if repair_change is None else repair_change.item.item_hash
                ),
                verification_hashes=tuple(sorted(verification_hashes)),
                fact_hashes=tuple(sorted(fact.fact_hash for fact in facts_for_change)),
                evidence_hashes=tuple(
                    sorted(
                        {
                            evidence
                            for fact in facts_for_change
                            for evidence in fact.evidence_hashes
                        }
                    )
                ),
            )

    return tuple(
        sorted(
            review_items_by_field.values(),
            key=lambda item: (item.field_id, item.review_item_hash),
        )
    )


def build_fixture_candidate_batch(
    *,
    change_set: ChangeSetDraftV1,
    facts: tuple[VerifiedFactV1, ...],
    verification_batches: tuple[VerificationBatchV1, ...],
    receipt_chains: tuple[ReceiptChainV1, ...],
    fact_verification_links: tuple[FactVerificationLinkV1, ...],
    repair_resolutions: tuple[RepairResolutionV1, ...],
    review_policy: HumanBatchPolicyV1,
) -> CandidateAssemblyV1:
    """Assemble non-authoritative fixture artifacts from exact 057/058 values."""

    change_set = _revalidate_exact(
        change_set, ChangeSetDraftV1, "invalid_058_change_set"
    )
    facts = _revalidate_many(facts, VerifiedFactV1, "invalid_058_fact")
    verifications = _revalidate_many(
        verification_batches, VerificationBatchV1, "invalid_057_verification"
    )
    chains = _revalidate_many(
        receipt_chains, ReceiptChainV1, "invalid_054_receipt_chain"
    )
    if not chains:
        raise CandidateAssemblyError("receipt_chain_verification_bijection_mismatch")
    links = _revalidate_many(
        fact_verification_links,
        FactVerificationLinkV1,
        "invalid_fact_verification_link",
    )
    repairs = _revalidate_many(
        repair_resolutions, RepairResolutionV1, "invalid_057_repair_resolution"
    )
    if len({repair.resolution_hash for repair in repairs}) != len(repairs):
        raise CandidateAssemblyError("duplicate_repair_resolution")
    policy = _revalidate_exact(
        review_policy, HumanBatchPolicyV1, "invalid_human_batch_policy"
    )

    facts_by_hash = {fact.fact_hash: fact for fact in facts}
    if len(facts_by_hash) != len(facts):
        raise CandidateAssemblyError("duplicate_058_fact")
    referenced = {
        fact_hash
        for item in change_set.items
        for fact_hash in (
            *item.prior_fact_hashes,
            *((item.incoming_fact_hash,) if item.incoming_fact_hash else ()),
        )
    }
    if referenced != set(facts_by_hash):
        raise CandidateAssemblyError("change_fact_membership_mismatch")
    changes = _candidate_changes(change_set, facts_by_hash)

    verification_by_hash = {item.verification_hash: item for item in verifications}
    if len(verification_by_hash) != len(verifications):
        raise CandidateAssemblyError("duplicate_verification_receipt")
    links_by_fact = {item.fact_hash: item for item in links}
    if len(links_by_fact) != len(links) or set(links_by_fact) != set(facts_by_hash):
        raise CandidateAssemblyError("fact_receipt_bijection_mismatch")

    used_verifications: set[str] = set()
    for fact_hash, fact in facts_by_hash.items():
        link = links_by_fact[fact_hash]
        verification = verification_by_hash.get(link.verification_hash)
        if verification is None:
            raise CandidateAssemblyError("fact_receipt_missing")
        if (
            link.field_id != fact.scope.field_id
            or verification.product_version_id != fact.scope.product_version_id
            or verification.source_revision_id != fact.authority.source_revision_id
        ):
            raise CandidateAssemblyError("verification_scope_mismatch")
        result = next(
            (item for item in verification.results if item.field_id == link.field_id),
            None,
        )
        if (
            result is None
            or result.status != "PASS"
            or result.candidate_snapshot_hash != link.candidate_snapshot_hash
        ):
            raise CandidateAssemblyError("fact_receipt_not_verified")
        used_verifications.add(verification.verification_hash)

    for repair in repairs:
        parent = verification_by_hash.get(repair.parent_verification_hash)
        if parent is None or not repair.review_items:
            raise CandidateAssemblyError("repair_receipt_missing")
        parent_by_field = {item.field_id: item for item in parent.results}
        resolution_by_field = {item.field_id: item for item in repair.results}
        for review in repair.review_items:
            if (
                review.parent_verification_hash != parent.verification_hash
                or review.field_id not in parent_by_field
                or review.field_id not in resolution_by_field
                or resolution_by_field[review.field_id].status == "PASS"
            ):
                raise CandidateAssemblyError("repair_receipt_mismatch")
        used_verifications.add(parent.verification_hash)
    if used_verifications != set(verification_by_hash):
        raise CandidateAssemblyError("unused_or_ambiguous_verification_receipt")

    affected_fields = {item.scope.field_id for item in change_set.items}
    if not set(policy.high_risk_field_ids) <= affected_fields:
        raise CandidateAssemblyError("high_risk_field_not_affected")
    source_revision_ids = tuple(
        sorted(
            {
                *(chain.task.source_revision_id for chain in chains),
                *(verification.source_revision_id for verification in verifications),
                *(fact.authority.source_revision_id for fact in facts),
                *(
                    revision
                    for fact in facts
                    for revision in fact.supporting_source_revision_ids
                ),
            }
        )
    )
    try:
        candidate = FixtureCandidateV1(
            space_id=change_set.space_id,
            product_version_id=change_set.product_version_id,
            schema_contract=chains[0].task.input_refs.schema_contract,
            source_revision_ids=source_revision_ids,
            change_set=change_set,
            changes=changes,
            verification_batches=tuple(
                sorted(verifications, key=lambda item: item.verification_hash)
            ),
            receipt_chains=tuple(
                sorted(
                    chains,
                    key=lambda chain: (
                        chain.task_hash,
                        tuple(receipt.receipt_hash for receipt in chain.receipts),
                    ),
                )
            ),
            fact_verification_links=tuple(sorted(links, key=lambda item: item.fact_hash)),
            repair_resolutions=tuple(
                sorted(repairs, key=lambda item: item.resolution_hash)
            ),
        )
    except ValidationError as exc:
        raise CandidateAssemblyError("candidate_identity_mismatch") from exc

    batch = HumanBatchV1(
        candidate_hash=candidate.candidate_hash,
        review_policy=policy,
        items=_expected_human_review_items(candidate, policy),
    )
    return CandidateAssemblyV1(candidate=candidate, human_batch=batch)


__all__ = [
    "CandidateAssemblyError",
    "CandidateAssemblyV1",
    "CandidateChangeV1",
    "FactVerificationLinkV1",
    "FixtureCandidateV1",
    "HumanBatchPolicyV1",
    "HumanBatchV1",
    "HumanReviewItemV1",
    "build_fixture_candidate_batch",
]
