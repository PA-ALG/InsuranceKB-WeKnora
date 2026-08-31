"""Pure bounded extraction attempts and receipts for OpenSpec 054 Stage 1."""

from __future__ import annotations

from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.extraction_tasks import (
    ArtifactRefV1,
    ExtractionTaskV1,
    NonBlankStr,
    Sha256Hex,
)

AttemptPurpose = Literal["initial", "targeted_repair"]
FieldStatus = Literal["candidate", "unknown", "blocked", "failed"]
AttemptOutcome = Literal["completed", "insufficient", "blocked", "failed"]

EXTRACTION_ATTEMPT_OBJECT_TYPE: Final[str] = "extraction-attempt.v1"
EXTRACTION_RECEIPT_OBJECT_TYPE: Final[str] = "extraction-attempt-receipt.v1"


class ReceiptContractError(ValueError):
    """Typed failure for an invalid receipt-chain operation."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


def _require_canonical_fields(field_ids: tuple[str, ...]) -> None:
    if not field_ids or len(field_ids) != len(set(field_ids)):
        raise ValueError("invalid_attempt_field_partition")


def _attempt_payload(
    *,
    task_hash: str,
    attempt_number: int,
    purpose: AttemptPurpose,
    field_ids: tuple[str, ...],
    parent_receipt_hash: str | None,
) -> dict[str, object]:
    return {
        "task_hash": task_hash,
        "attempt_number": attempt_number,
        "purpose": purpose,
        "field_ids": field_ids,
        "parent_receipt_hash": parent_receipt_hash,
    }


class AttemptRequestV1(_FrozenModel):
    task_hash: Sha256Hex
    attempt_number: Literal[1, 2]
    purpose: AttemptPurpose
    field_ids: tuple[NonBlankStr, ...]
    parent_receipt_hash: Sha256Hex | None
    attempt_hash: Sha256Hex

    @model_validator(mode="after")
    def require_exact_sequence_and_hash(self) -> Self:
        _require_canonical_fields(self.field_ids)
        if (self.attempt_number, self.purpose) not in {
            (1, "initial"),
            (2, "targeted_repair"),
        }:
            raise ValueError("invalid_attempt_sequence")
        if (self.attempt_number == 1) != (self.parent_receipt_hash is None):
            raise ValueError("invalid_attempt_parent_receipt")
        expected_hash = canonical_hash(
            EXTRACTION_ATTEMPT_OBJECT_TYPE,
            _attempt_payload(
                task_hash=self.task_hash,
                attempt_number=self.attempt_number,
                purpose=self.purpose,
                field_ids=self.field_ids,
                parent_receipt_hash=self.parent_receipt_hash,
            ),
        )
        if self.attempt_hash != expected_hash:
            raise ValueError("attempt_hash_mismatch")
        return self


class FieldOutcomeV1(_FrozenModel):
    field_id: NonBlankStr
    status: FieldStatus
    candidate_ref: ArtifactRefV1 | None
    reason_code: NonBlankStr | None

    @model_validator(mode="after")
    def require_typed_outcome(self) -> Self:
        if self.status == "candidate":
            if self.candidate_ref is None or self.reason_code is not None:
                raise ValueError("invalid_candidate_outcome")
        elif self.candidate_ref is not None or self.reason_code is None:
            raise ValueError("invalid_non_candidate_outcome")
        return self


def _receipt_payload(
    *,
    attempt: AttemptRequestV1,
    field_outcomes: tuple[FieldOutcomeV1, ...],
    outcome: AttemptOutcome,
    reason_code: str | None,
) -> dict[str, object]:
    return {
        "task_hash": attempt.task_hash,
        "attempt_hash": attempt.attempt_hash,
        "attempt_number": attempt.attempt_number,
        "purpose": attempt.purpose,
        "attempted_fields": attempt.field_ids,
        "parent_receipt_hash": attempt.parent_receipt_hash,
        "field_outcomes": tuple(
            item.model_dump(mode="python") for item in field_outcomes
        ),
        "outcome": outcome,
        "reason_code": reason_code,
    }


class AttemptReceiptV1(_FrozenModel):
    task_hash: Sha256Hex
    attempt_hash: Sha256Hex
    attempt_number: Literal[1, 2]
    purpose: AttemptPurpose
    attempted_fields: tuple[NonBlankStr, ...]
    parent_receipt_hash: Sha256Hex | None
    field_outcomes: tuple[FieldOutcomeV1, ...]
    outcome: AttemptOutcome
    reason_code: NonBlankStr | None
    receipt_hash: Sha256Hex

    @model_validator(mode="after")
    def require_complete_explicit_outcome_and_hash(self) -> Self:
        _require_canonical_fields(self.attempted_fields)
        if tuple(item.field_id for item in self.field_outcomes) != self.attempted_fields:
            raise ValueError("receipt_field_bijection_mismatch")
        candidate_count = sum(
            item.status == "candidate" for item in self.field_outcomes
        )
        if self.outcome == "completed":
            if candidate_count != len(self.field_outcomes) or self.reason_code is not None:
                raise ValueError("invalid_completed_receipt")
        elif self.outcome == "insufficient":
            if candidate_count == len(self.field_outcomes) or self.reason_code is None:
                raise ValueError("invalid_insufficient_receipt")
        elif candidate_count or self.reason_code is None:
            raise ValueError("invalid_failed_receipt")
        attempt = AttemptRequestV1.model_validate(
            {
                "task_hash": self.task_hash,
                "attempt_number": self.attempt_number,
                "purpose": self.purpose,
                "field_ids": self.attempted_fields,
                "parent_receipt_hash": self.parent_receipt_hash,
                "attempt_hash": self.attempt_hash,
            }
        )
        expected_hash = canonical_hash(
            EXTRACTION_RECEIPT_OBJECT_TYPE,
            _receipt_payload(
                attempt=attempt,
                field_outcomes=self.field_outcomes,
                outcome=self.outcome,
                reason_code=self.reason_code,
            ),
        )
        if self.receipt_hash != expected_hash:
            raise ValueError("receipt_hash_mismatch")
        return self


class ReceiptChainV1(_FrozenModel):
    task: ExtractionTaskV1
    task_hash: Sha256Hex
    receipts: tuple[AttemptReceiptV1, ...]

    @field_validator("receipts")
    @classmethod
    def require_one_or_two_receipts(
        cls, value: tuple[AttemptReceiptV1, ...]
    ) -> tuple[AttemptReceiptV1, ...]:
        if len(value) not in {1, 2}:
            raise ValueError("invalid_receipt_chain_length")
        return value

    @model_validator(mode="after")
    def require_append_only_attempt_sequence(self) -> Self:
        if self.task_hash != self.task.task_hash or any(
            receipt.task_hash != self.task_hash for receipt in self.receipts
        ):
            raise ValueError("receipt_task_mismatch")
        first = self.receipts[0]
        if (first.attempt_number, first.purpose) != (1, "initial"):
            raise ValueError("invalid_receipt_chain_sequence")
        if first.attempted_fields != self.task.field_ids:
            raise ValueError("initial_receipt_fields_mismatch")
        if len(self.receipts) == 2:
            second = self.receipts[1]
            unresolved = tuple(
                item.field_id
                for item in first.field_outcomes
                if item.status != "candidate"
            )
            if (
                (second.attempt_number, second.purpose) != (2, "targeted_repair")
                or second.attempted_fields != unresolved
                or second.parent_receipt_hash != first.receipt_hash
                or first.receipt_hash == second.receipt_hash
            ):
                raise ValueError("invalid_receipt_chain_sequence")
        return self


def _build_attempt(
    *,
    task_hash: str,
    attempt_number: Literal[1, 2],
    purpose: AttemptPurpose,
    field_ids: tuple[str, ...],
    parent_receipt_hash: str | None,
) -> AttemptRequestV1:
    payload = _attempt_payload(
        task_hash=task_hash,
        attempt_number=attempt_number,
        purpose=purpose,
        field_ids=field_ids,
        parent_receipt_hash=parent_receipt_hash,
    )
    return AttemptRequestV1.model_validate(
        {**payload, "attempt_hash": canonical_hash(EXTRACTION_ATTEMPT_OBJECT_TYPE, payload)}
    )


def build_initial_attempt(task: ExtractionTaskV1) -> AttemptRequestV1:
    return _build_attempt(
        task_hash=task.task_hash,
        attempt_number=1,
        purpose="initial",
        field_ids=task.field_ids,
        parent_receipt_hash=None,
    )


def build_attempt_receipt(
    attempt: AttemptRequestV1,
    *,
    field_outcomes: tuple[FieldOutcomeV1, ...],
    outcome: AttemptOutcome,
    reason_code: str | None,
) -> AttemptReceiptV1:
    payload = _receipt_payload(
        attempt=attempt,
        field_outcomes=field_outcomes,
        outcome=outcome,
        reason_code=reason_code,
    )
    return AttemptReceiptV1.model_validate(
        {**payload, "receipt_hash": canonical_hash(EXTRACTION_RECEIPT_OBJECT_TYPE, payload)}
    )


def build_targeted_repair(
    task: ExtractionTaskV1,
    chain: ReceiptChainV1,
) -> AttemptRequestV1:
    if chain.task_hash != task.task_hash:
        raise ReceiptContractError("receipt_task_mismatch")
    if len(chain.receipts) != 1:
        raise ReceiptContractError("repair_budget_exhausted")
    if task.budget.max_targeted_repairs != 1 or task.budget.max_total_attempts != 2:
        raise ReceiptContractError("repair_not_authorized")
    unresolved = tuple(
        item.field_id
        for item in chain.receipts[0].field_outcomes
        if item.status != "candidate"
    )
    if not unresolved:
        raise ReceiptContractError("no_unresolved_fields")
    return _build_attempt(
        task_hash=task.task_hash,
        attempt_number=2,
        purpose="targeted_repair",
        field_ids=unresolved,
        parent_receipt_hash=chain.receipts[0].receipt_hash,
    )
