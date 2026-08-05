"""Pure Candidate -> Wiki draft -> review -> release-preparation handoff."""

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
from insurance_harness.compiler.evidence_verifier import FieldCandidateV1
from insurance_harness.knowledge_compiler.candidate_batches import CandidateAssemblyV1
from insurance_harness.knowledge_compiler.candidate_wiki_manifest import (
    BaseWikiManifestV1,
    CandidateWikiManifestDraftV1,
    CandidateWikiManifestError,
    ReleaseBaseAuthorityPort,
    WikiReleaseMemberV1,
    compile_candidate_wiki_manifest,
)
from insurance_harness.knowledge_compiler.review_dossier import (
    ReviewDossierError,
    ReviewDossierV1,
    build_review_dossier,
)

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=4096, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
PREPARATION_AUTHORITY: Final[
    Literal["INPUT_ONLY_REQUIRES_EXTERNAL_NAMED_HUMAN_DECISION"]
] = "INPUT_ONLY_REQUIRES_EXTERNAL_NAMED_HUMAN_DECISION"
HANDOFF_AUTHORITY: Final[
    Literal["DETERMINISTIC_HANDOFF_NO_APPROVAL_OR_SERVING_AUTHORITY"]
] = "DETERMINISTIC_HANDOFF_NO_APPROVAL_OR_SERVING_AUTHORITY"
PREPARATION_OBJECT_TYPE: Final[
    Literal["candidate-review-release-preparation-input.v1"]
] = "candidate-review-release-preparation-input.v1"
HANDOFF_OBJECT_TYPE: Final[Literal["candidate-review-release-handoff.v1"]] = (
    "candidate-review-release-handoff.v1"
)


class CandidateReviewReleaseHandoffError(ValueError):
    """Typed failure returned without a partial handoff."""

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


def _exact_assembly(value: object) -> CandidateAssemblyV1:
    if not isinstance(value, CandidateAssemblyV1):
        raise ValueError("candidate_assembly_invalid")
    return CandidateAssemblyV1.model_validate(
        value.model_dump(mode="python", exclude_computed_fields=True)
    )


class ReleasePreparationInputV1(_FrozenModel):
    """Non-authoritative fields consumable by 059 after external human approval."""

    contract: Literal["candidate-review-release-preparation-input.v1"]
    authority: Literal["INPUT_ONLY_REQUIRES_EXTERNAL_NAMED_HUMAN_DECISION"]
    preparation_id: Sha256Hex
    candidate_digest: Sha256Hex
    required_human_batch_hash: Sha256Hex
    review_policy_id: Sha256Hex
    change_set_hash: Sha256Hex
    space_id: NonBlankStr
    product_version_id: NonBlankStr
    expected_release_id: NonBlankStr
    expected_activation_epoch: int
    base_manifest_digest: Sha256Hex
    members: tuple[WikiReleaseMemberV1, ...]
    manifest_bytes: bytes
    manifest_digest: Sha256Hex
    human_decision_digest: None = None
    signature: None = None
    active_head: None = None

    @model_validator(mode="after")
    def require_complete_draft_identity(self) -> Self:
        if self.expected_activation_epoch < 0:
            raise ValueError("invalid_expected_activation_epoch")
        draft = CandidateWikiManifestDraftV1(
            candidate_hash=self.candidate_digest,
            human_batch_hash=self.required_human_batch_hash,
            review_policy_hash=self.review_policy_id,
            base_release_id=self.expected_release_id,
            base_activation_epoch=self.expected_activation_epoch,
            base_manifest_digest=self.base_manifest_digest,
            members=self.members,
            manifest_bytes=self.manifest_bytes,
            manifest_digest=self.manifest_digest,
        )
        expected_id = canonical_hash(
            PREPARATION_OBJECT_TYPE,
            {
                "candidate_digest": self.candidate_digest,
                "required_human_batch_hash": self.required_human_batch_hash,
                "review_policy_id": self.review_policy_id,
                "change_set_hash": self.change_set_hash,
                "space_id": self.space_id,
                "product_version_id": self.product_version_id,
                "expected_release_id": self.expected_release_id,
                "expected_activation_epoch": self.expected_activation_epoch,
                "base_manifest_digest": self.base_manifest_digest,
                "manifest_digest": draft.manifest_digest,
                "member_digests": tuple(member.member_digest for member in draft.members),
            },
        )
        if self.preparation_id != expected_id:
            raise ValueError("preparation_identity_mismatch")
        return self


class CandidateReviewReleaseHandoffV1(_FrozenModel):
    contract: Literal["candidate-review-release-handoff.v1"]
    authority: Literal["DETERMINISTIC_HANDOFF_NO_APPROVAL_OR_SERVING_AUTHORITY"]
    candidate_assembly: CandidateAssemblyV1
    base_manifest: BaseWikiManifestV1
    field_candidates: tuple[FieldCandidateV1, ...]
    candidate_hash: Sha256Hex
    human_batch_hash: Sha256Hex
    policy_hash: Sha256Hex
    change_set_hash: Sha256Hex
    space_id: NonBlankStr
    product_version_id: NonBlankStr
    wiki_manifest: CandidateWikiManifestDraftV1
    review_dossier: ReviewDossierV1
    release_preparation: ReleasePreparationInputV1

    @model_validator(mode="after")
    def require_exact_cross_projection_custody(self) -> Self:
        assembly = _exact_assembly(self.candidate_assembly)
        candidate = assembly.candidate
        candidate_keys = tuple(
            item.candidate_snapshot_hash for item in self.field_candidates
        )
        if (
            not candidate_keys
            or candidate_keys != tuple(sorted(candidate_keys))
            or len(candidate_keys) != len(set(candidate_keys))
            or self.base_manifest.space_id != candidate.space_id
            or self.base_manifest.product_version_id != candidate.product_version_id
            or self.base_manifest.schema_contract != candidate.schema_contract
        ):
            raise ValueError("handoff_replay_input_mismatch")
        expected = (
            candidate.candidate_hash,
            assembly.human_batch.batch_hash,
            assembly.human_batch.review_policy.policy_hash,
            candidate.change_set.change_set_hash,
            candidate.space_id,
            candidate.product_version_id,
        )
        if (
            self.candidate_hash,
            self.human_batch_hash,
            self.policy_hash,
            self.change_set_hash,
            self.space_id,
            self.product_version_id,
        ) != expected:
            raise ValueError("handoff_candidate_identity_mismatch")
        if (
            self.wiki_manifest.candidate_hash != self.candidate_hash
            or self.wiki_manifest.human_batch_hash != self.human_batch_hash
            or self.wiki_manifest.review_policy_hash != self.policy_hash
        ):
            raise ValueError("handoff_manifest_identity_mismatch")
        dossier = self.review_dossier
        if (
            dossier.candidate_hash != self.candidate_hash
            or dossier.human_batch_hash != self.human_batch_hash
            or dossier.policy_hash != self.policy_hash
            or dossier.change_set_hash != self.change_set_hash
            or dossier.space_id != self.space_id
            or dossier.product_version_id != self.product_version_id
        ):
            raise ValueError("handoff_dossier_identity_mismatch")
        preparation = self.release_preparation
        if (
            preparation.candidate_digest != self.candidate_hash
            or preparation.required_human_batch_hash != self.human_batch_hash
            or preparation.review_policy_id != self.policy_hash
            or preparation.change_set_hash != self.change_set_hash
            or preparation.space_id != self.space_id
            or preparation.product_version_id != self.product_version_id
            or preparation.expected_release_id != self.wiki_manifest.base_release_id
            or preparation.expected_activation_epoch
            != self.wiki_manifest.base_activation_epoch
            or preparation.base_manifest_digest
            != self.wiki_manifest.base_manifest_digest
            or preparation.members != self.wiki_manifest.members
            or preparation.manifest_bytes != self.wiki_manifest.manifest_bytes
            or preparation.manifest_digest != self.wiki_manifest.manifest_digest
        ):
            raise ValueError("handoff_preparation_identity_mismatch")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def handoff_hash(self) -> str:
        return canonical_hash(
            HANDOFF_OBJECT_TYPE,
            {
                "authority": self.authority,
                "candidate_hash": self.candidate_hash,
                "human_batch_hash": self.human_batch_hash,
                "policy_hash": self.policy_hash,
                "change_set_hash": self.change_set_hash,
                "space_id": self.space_id,
                "product_version_id": self.product_version_id,
                "base_manifest_digest": self.base_manifest.manifest_digest,
                "field_candidate_hashes": tuple(
                    item.candidate_snapshot_hash for item in self.field_candidates
                ),
                "wiki_draft_hash": self.wiki_manifest.draft_hash,
                "dossier_hash": self.review_dossier.dossier_hash,
                "preparation_id": self.release_preparation.preparation_id,
            },
        )


def _preparation(
    assembly: CandidateAssemblyV1,
    manifest: CandidateWikiManifestDraftV1,
) -> ReleasePreparationInputV1:
    candidate = assembly.candidate
    values = {
        "candidate_digest": candidate.candidate_hash,
        "required_human_batch_hash": assembly.human_batch.batch_hash,
        "review_policy_id": assembly.human_batch.review_policy.policy_hash,
        "change_set_hash": candidate.change_set.change_set_hash,
        "space_id": candidate.space_id,
        "product_version_id": candidate.product_version_id,
        "expected_release_id": manifest.base_release_id,
        "expected_activation_epoch": manifest.base_activation_epoch,
        "base_manifest_digest": manifest.base_manifest_digest,
        "manifest_digest": manifest.manifest_digest,
        "member_digests": tuple(member.member_digest for member in manifest.members),
    }
    return ReleasePreparationInputV1(
        contract=PREPARATION_OBJECT_TYPE,
        authority=PREPARATION_AUTHORITY,
        preparation_id=canonical_hash(PREPARATION_OBJECT_TYPE, values),
        candidate_digest=candidate.candidate_hash,
        required_human_batch_hash=assembly.human_batch.batch_hash,
        review_policy_id=assembly.human_batch.review_policy.policy_hash,
        change_set_hash=candidate.change_set.change_set_hash,
        space_id=candidate.space_id,
        product_version_id=candidate.product_version_id,
        expected_release_id=manifest.base_release_id,
        expected_activation_epoch=manifest.base_activation_epoch,
        base_manifest_digest=manifest.base_manifest_digest,
        members=manifest.members,
        manifest_bytes=manifest.manifest_bytes,
        manifest_digest=manifest.manifest_digest,
    )


def verify_candidate_review_release_handoff(
    value: object,
    *,
    base_authority: ReleaseBaseAuthorityPort | None,
) -> CandidateReviewReleaseHandoffV1:
    """Revalidate the immutable aggregate and every mechanical cross-edge."""

    if not isinstance(value, CandidateReviewReleaseHandoffV1):
        raise CandidateReviewReleaseHandoffError("handoff_invalid")
    try:
        exact = CandidateReviewReleaseHandoffV1.model_validate(
            value.model_dump(mode="python", exclude_computed_fields=True)
        )
        replayed_manifest = compile_candidate_wiki_manifest(
            assembly=exact.candidate_assembly,
            base=exact.base_manifest,
            base_authority=base_authority,
            field_candidates=exact.field_candidates,
        )
        replayed_dossier = build_review_dossier(
            assembly=exact.candidate_assembly,
            field_candidates=exact.field_candidates,
        )
        replayed_preparation = _preparation(
            exact.candidate_assembly,
            replayed_manifest,
        )
        if (
            replayed_manifest != exact.wiki_manifest
            or replayed_dossier != exact.review_dossier
            or replayed_preparation != exact.release_preparation
        ):
            raise ValueError("handoff_replay_mismatch")
        return exact
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise CandidateReviewReleaseHandoffError("handoff_invalid") from None


def build_candidate_review_release_handoff(
    *,
    assembly: CandidateAssemblyV1,
    base: BaseWikiManifestV1,
    base_authority: ReleaseBaseAuthorityPort | None,
    field_candidates: Iterable[FieldCandidateV1],
) -> CandidateReviewReleaseHandoffV1:
    """Build all projections in memory and expose none until validation succeeds."""

    try:
        exact = _exact_assembly(assembly)
        candidates = tuple(
            sorted(field_candidates, key=lambda item: item.candidate_snapshot_hash)
        )
        manifest = compile_candidate_wiki_manifest(
            assembly=exact,
            base=base,
            base_authority=base_authority,
            field_candidates=candidates,
        )
        dossier = build_review_dossier(
            assembly=exact,
            field_candidates=candidates,
        )
        candidate = exact.candidate
        handoff = CandidateReviewReleaseHandoffV1(
            contract=HANDOFF_OBJECT_TYPE,
            authority=HANDOFF_AUTHORITY,
            candidate_assembly=exact,
            base_manifest=base,
            field_candidates=candidates,
            candidate_hash=candidate.candidate_hash,
            human_batch_hash=exact.human_batch.batch_hash,
            policy_hash=exact.human_batch.review_policy.policy_hash,
            change_set_hash=candidate.change_set.change_set_hash,
            space_id=candidate.space_id,
            product_version_id=candidate.product_version_id,
            wiki_manifest=manifest,
            review_dossier=dossier,
            release_preparation=_preparation(exact, manifest),
        )
        return verify_candidate_review_release_handoff(
            handoff,
            base_authority=base_authority,
        )
    except CandidateReviewReleaseHandoffError:
        raise
    except (CandidateWikiManifestError, ReviewDossierError) as error:
        raise CandidateReviewReleaseHandoffError(
            f"upstream_{error.reason_code}"
        ) from None
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise CandidateReviewReleaseHandoffError("handoff_input_invalid") from None


__all__ = [
    "CandidateReviewReleaseHandoffError",
    "CandidateReviewReleaseHandoffV1",
    "ReleasePreparationInputV1",
    "build_candidate_review_release_handoff",
    "verify_candidate_review_release_handoff",
]
