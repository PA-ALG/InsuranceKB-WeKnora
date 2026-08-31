"""Deterministic raw-to-parsed-to-Candidate derivation validation for EC-01 C3."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any, Final, Literal, NoReturn, cast

from pydantic import ValidationError

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.evidence_verifier import (
    FreeformEvidenceBindingReceiptV1,
    FreeformFieldOutputV1,
)
from insurance_harness.goldenset.expert_golden_admission_596_2 import (
    ORDERED_FIELD_IDS,
)
from insurance_harness.knowledge_compiler import (
    deepseek_locator_extractor_596_1 as deepseek,
)
from insurance_harness.knowledge_compiler import (
    ec01_formal_candidate_run_815 as ec01_run,
)
from insurance_harness.knowledge_compiler.deepseek_locator_extractor_596_1 import (
    Schema67BoundAttemptV1,
    Schema67ExecutionPlanV1,
)
from insurance_harness.knowledge_compiler.ec01_formal_candidate_run_815 import (
    EC01FormalCandidateRun815V1,
    EC01FormalCandidateRunError,
    require_ec01_formal_candidate_run_815,
)
from insurance_harness.knowledge_compiler.schema67_native_pdf_selection_815 import (
    ModelTaskSelectionResponse815V1,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    FieldContractSetV1,
)

FieldAttemptDerivationKind815 = Literal[
    "MODEL_RESPONSE",
    "CODE_OWNED_DEFERRED_UNKNOWN",
]
FieldAttemptParseOutcome815 = Literal[
    "PARSED_PRESENT",
    "PARSED_ABSENT_EXPLICITLY",
    "PARSED_UNKNOWN_NO_SUPPORT",
    "PARSED_UNKNOWN_AMBIGUOUS_SOURCE",
    "PARSED_UNKNOWN_EVIDENCE_INVALID",
    "PARSED_UNKNOWN_EXPLICIT_NOT_STATED",
    "CODE_OWNED_DEFERRED_UNKNOWN",
]
FieldAttemptManifestSource815 = Literal[
    "SYNTHETIC_TEST_ONLY",
    "EC01_ORIGINAL_RUN",
]
FieldAttemptState815 = Literal["present", "absent_explicitly", "unknown"]

_MANIFEST_CONTRACT: Final[str] = "schema67-field-attempt-manifest.815.v1"
_ROW_CONTRACT: Final[str] = "schema67-field-attempt.815.v1"
_FIELD_SET_CONTRACT: Final[str] = "schema67-formal-candidate-fields.815.v1"
_EVIDENCE_SET_CONTRACT: Final[str] = "schema67-formal-candidate-evidence.815.v1"
_DERIVATION_CONTRACT: Final[str] = "schema67-formal-candidate-derivation.815.v1"
_RESULT_CONTRACT: Final[str] = "schema67-formal-candidate-validation.815.v1"
_SYNTHETIC_IDENTITY: Final[str] = "SYNTHETIC_TEST_ONLY"
_SEMANTIC_CLAUSE_SPLIT_815: Final[re.Pattern[str]] = re.compile(
    r"[，。；、,;.!?！？：:\n]+"
)
_SEMANTIC_COMPACT_815: Final[re.Pattern[str]] = re.compile(
    r"[^0-9a-z\u3400-\u9fff]+"
)
_SEMANTIC_NUMBER_815: Final[re.Pattern[str]] = re.compile(r"\d+(?:\.\d+)?%?")
_SEMANTIC_MARKERS_815: Final[tuple[str, ...]] = tuple(
    sorted(
        {
            "不超过",
            "不少于",
            "不得",
            "必须",
            "至少",
            "至多",
            "以上",
            "以下",
            "以内",
            "以外",
            "除外",
            "例外",
            "需要",
            "最高",
            "最低",
            "如果",
            "若",
            "如",
            "须",
            "仅",
            "限",
            "不",
            "无",
            "未",
            "且",
            "但",
        },
        key=lambda value: (-len(value), value),
    )
)
_SEMANTIC_MARKER_815: Final[re.Pattern[str]] = re.compile(
    "|".join(re.escape(value) for value in _SEMANTIC_MARKERS_815)
)
_FOOTNOTE_MARKER_PATTERN_815: Final[str] = (
    r"(?:[①-⑳]|[＊*†‡※]|[⁰¹²³⁴⁵⁶⁷⁸⁹]+|\[\d{1,2}\]|（\d{1,2}）)"
)
_FOOTNOTE_MARKER_815: Final[re.Pattern[str]] = re.compile(
    _FOOTNOTE_MARKER_PATTERN_815
)
_FOOTNOTE_MARKER_BEFORE_815: Final[re.Pattern[str]] = re.compile(
    rf"{_FOOTNOTE_MARKER_PATTERN_815}$"
)
_PARSE_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        "PARSED_PRESENT",
        "PARSED_ABSENT_EXPLICITLY",
        "PARSED_UNKNOWN_NO_SUPPORT",
        "PARSED_UNKNOWN_AMBIGUOUS_SOURCE",
        "PARSED_UNKNOWN_EVIDENCE_INVALID",
        "PARSED_UNKNOWN_EXPLICIT_NOT_STATED",
        "CODE_OWNED_DEFERRED_UNKNOWN",
    }
)
_UNKNOWN_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        "PARSED_UNKNOWN_NO_SUPPORT",
        "PARSED_UNKNOWN_AMBIGUOUS_SOURCE",
        "PARSED_UNKNOWN_EVIDENCE_INVALID",
        "PARSED_UNKNOWN_EXPLICIT_NOT_STATED",
    }
)
_MANIFEST_KEYS: Final[frozenset[str]] = frozenset(
    {
        "attempted_field_count",
        "candidate_evidence_sha256",
        "candidate_fields_sha256",
        "code_deferred_count",
        "coordinate_evidence_companion_sha256",
        "contract",
        "derivation_source",
        "dispositioned_count",
        "execution_identity_sha256",
        "experiment_id",
        "formal_candidate_derivation_sha256",
        "integration_head",
        "integration_tree",
        "manifest_sha256",
        "ordered_field_ids",
        "raw_response_sha256s",
        "evidence_repairs",
        "provider_calls",
        "provider_visible_count",
        "repair_field_ids",
        "repair_task_key",
        "receipt_id",
        "request_body_sha256s",
        "request_manifest_sha256",
        "revision_set_sha256",
        "revision_validation_sha256",
        "rows",
        "run_derivation_sha256",
        "run_id",
        "schema_rows_sha256",
        "task_keys",
        "terminal_sha256",
        "real_model_output_count",
        "response_contract_repairs",
        "transport_retries",
        "unclassified_count",
        "attempt_id",
    }
)
_ROW_KEYS: Final[frozenset[str]] = frozenset(
    {
        "attempted",
        "candidate_field_sha256",
        "coordinate_evidence_sha256s",
        "contract",
        "derivation_kind",
        "evidence_receipt_sha256",
        "field_id",
        "final_state",
        "initial_failure_reason",
        "model_returned_state",
        "parse_outcome",
        "raw_response_byte_size",
        "raw_response_sha256",
        "request_body_sha256",
        "request_ordinal",
        "provider_visible",
        "repair_attempted",
        "repair_parent_bound_attempt_hash",
        "repair_parent_verification_hash",
        "repair_raw_response_byte_size",
        "repair_raw_response_sha256",
        "repair_request_sha256",
        "response_ordinal",
        "row_sha256",
        "schema_order",
        "task_key",
        "task_ordinal",
        "typed_reason",
    }
)


class FormalCandidateDerivationValidationError(ValueError):
    """Typed deterministic validation failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class Schema67FieldAttempt815V1:
    contract: Literal["schema67-field-attempt.815.v1"]
    derivation_kind: FieldAttemptDerivationKind815
    field_id: str
    schema_order: int
    attempted: bool
    provider_visible: bool
    task_key: str | None
    task_ordinal: int | None
    request_ordinal: int | None
    response_ordinal: int | None
    request_body_sha256: str | None
    raw_response_sha256: str | None
    raw_response_byte_size: int | None
    initial_failure_reason: str | None
    repair_attempted: Literal[0, 1]
    repair_parent_bound_attempt_hash: str | None
    repair_parent_verification_hash: str | None
    repair_request_sha256: str | None
    repair_raw_response_sha256: str | None
    repair_raw_response_byte_size: int | None
    parse_outcome: FieldAttemptParseOutcome815
    model_returned_state: FieldAttemptState815 | None
    final_state: FieldAttemptState815
    typed_reason: str | None
    coordinate_evidence_sha256s: tuple[str, ...]
    candidate_field_sha256: str
    evidence_receipt_sha256: str
    row_sha256: str

    def to_wire(self, *, include_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "attempted": self.attempted,
            "candidate_field_sha256": self.candidate_field_sha256,
            "coordinate_evidence_sha256s": self.coordinate_evidence_sha256s,
            "contract": self.contract,
            "derivation_kind": self.derivation_kind,
            "evidence_receipt_sha256": self.evidence_receipt_sha256,
            "field_id": self.field_id,
            "final_state": self.final_state,
            "initial_failure_reason": self.initial_failure_reason,
            "model_returned_state": self.model_returned_state,
            "parse_outcome": self.parse_outcome,
            "raw_response_byte_size": self.raw_response_byte_size,
            "raw_response_sha256": self.raw_response_sha256,
            "request_body_sha256": self.request_body_sha256,
            "request_ordinal": self.request_ordinal,
            "provider_visible": self.provider_visible,
            "repair_attempted": self.repair_attempted,
            "repair_parent_bound_attempt_hash": self.repair_parent_bound_attempt_hash,
            "repair_parent_verification_hash": self.repair_parent_verification_hash,
            "repair_raw_response_byte_size": self.repair_raw_response_byte_size,
            "repair_raw_response_sha256": self.repair_raw_response_sha256,
            "repair_request_sha256": self.repair_request_sha256,
            "response_ordinal": self.response_ordinal,
            "schema_order": self.schema_order,
            "task_key": self.task_key,
            "task_ordinal": self.task_ordinal,
            "typed_reason": self.typed_reason,
        }
        if include_hash:
            payload["row_sha256"] = self.row_sha256
        return payload


@dataclass(frozen=True, slots=True)
class Schema67FieldAttemptManifest815V1:
    contract: Literal["schema67-field-attempt-manifest.815.v1"]
    derivation_source: FieldAttemptManifestSource815
    experiment_id: str
    execution_identity_sha256: str
    run_id: str
    attempt_id: str
    receipt_id: str
    integration_head: str
    integration_tree: str
    run_derivation_sha256: str
    revision_validation_sha256: str
    revision_set_sha256: str
    request_manifest_sha256: str
    schema_rows_sha256: str
    ordered_field_ids: tuple[str, ...]
    task_keys: tuple[str, ...]
    rows: tuple[Schema67FieldAttempt815V1, ...]
    attempted_field_count: int
    provider_visible_count: int
    real_model_output_count: int
    code_deferred_count: int
    dispositioned_count: int
    unclassified_count: int
    request_body_sha256s: tuple[str, ...]
    raw_response_sha256s: tuple[str, ...]
    provider_calls: int
    transport_retries: Literal[0, 1]
    response_contract_repairs: Literal[0, 1]
    evidence_repairs: int
    repair_task_key: str | None
    repair_field_ids: tuple[str, ...]
    terminal_sha256: str
    candidate_fields_sha256: str
    candidate_evidence_sha256: str
    coordinate_evidence_companion_sha256: str | None
    manifest_sha256: str
    formal_candidate_derivation_sha256: str

    def to_wire(
        self,
        *,
        include_hashes: bool = True,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "attempted_field_count": self.attempted_field_count,
            "attempt_id": self.attempt_id,
            "candidate_evidence_sha256": self.candidate_evidence_sha256,
            "candidate_fields_sha256": self.candidate_fields_sha256,
            "code_deferred_count": self.code_deferred_count,
            "coordinate_evidence_companion_sha256": (
                self.coordinate_evidence_companion_sha256
            ),
            "contract": self.contract,
            "derivation_source": self.derivation_source,
            "dispositioned_count": self.dispositioned_count,
            "execution_identity_sha256": self.execution_identity_sha256,
            "experiment_id": self.experiment_id,
            "integration_head": self.integration_head,
            "integration_tree": self.integration_tree,
            "ordered_field_ids": self.ordered_field_ids,
            "raw_response_sha256s": self.raw_response_sha256s,
            "evidence_repairs": self.evidence_repairs,
            "provider_calls": self.provider_calls,
            "provider_visible_count": self.provider_visible_count,
            "repair_field_ids": self.repair_field_ids,
            "repair_task_key": self.repair_task_key,
            "receipt_id": self.receipt_id,
            "request_body_sha256s": self.request_body_sha256s,
            "request_manifest_sha256": self.request_manifest_sha256,
            "revision_set_sha256": self.revision_set_sha256,
            "revision_validation_sha256": self.revision_validation_sha256,
            "rows": tuple(row.to_wire() for row in self.rows),
            "run_derivation_sha256": self.run_derivation_sha256,
            "run_id": self.run_id,
            "schema_rows_sha256": self.schema_rows_sha256,
            "task_keys": self.task_keys,
            "terminal_sha256": self.terminal_sha256,
            "real_model_output_count": self.real_model_output_count,
            "response_contract_repairs": self.response_contract_repairs,
            "transport_retries": self.transport_retries,
            "unclassified_count": self.unclassified_count,
        }
        if include_hashes:
            payload["formal_candidate_derivation_sha256"] = (
                self.formal_candidate_derivation_sha256
            )
            payload["manifest_sha256"] = self.manifest_sha256
        return payload


@dataclass(frozen=True, slots=True)
class FormalCandidateDerivationValidation815V1:
    contract: Literal["schema67-formal-candidate-validation.815.v1"]
    status: Literal["PASS", "SYNTHETIC_TEST_ONLY"]
    derivation_source: FieldAttemptManifestSource815
    ordered_field_count: Literal[67]
    attempted_field_count: int
    request_count: Literal[8]
    raw_response_count: Literal[8]
    manifest_sha256: str
    terminal_sha256: str
    candidate_fields_sha256: str
    candidate_evidence_sha256: str
    formal_candidate_derivation_sha256: str
    provider_calls: Literal[0]


def _reject(reason: str) -> NoReturn:
    raise FormalCandidateDerivationValidationError(reason)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _read_canonical_artifact(root: Path, name: str) -> tuple[bytes, object]:
    try:
        payload = (root / name).read_bytes()
    except OSError:
        _reject("FIELD_ATTEMPT_ARTIFACT_MISSING")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _reject("FIELD_ATTEMPT_ARTIFACT_NONCANONICAL")
    if payload != _canonical_bytes(decoded):
        _reject("FIELD_ATTEMPT_ARTIFACT_NONCANONICAL")
    return payload, decoded


def _require_wire_string(value: object) -> str:
    if type(value) is not str or not value:
        _reject("FIELD_ATTEMPT_ARTIFACT_INVALID")
    return value


def _require_wire_integer(value: object, *, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        _reject("FIELD_ATTEMPT_ARTIFACT_INVALID")
    return value


def _require_optional_wire_string(value: object) -> str | None:
    if value is None:
        return None
    return _require_wire_string(value)


def _require_optional_wire_integer(value: object) -> int | None:
    if value is None:
        return None
    return _require_wire_integer(value)


def _require_wire_string_list(value: object) -> tuple[str, ...]:
    if type(value) is not list or any(type(item) is not str for item in value):
        _reject("FIELD_ATTEMPT_ARTIFACT_INVALID")
    return tuple(cast(list[str], value))


def _semantic_compact_815(value: str) -> str:
    without_footnotes = _FOOTNOTE_MARKER_815.sub("", value)
    return _SEMANTIC_COMPACT_815.sub(
        "", unicodedata.normalize("NFKC", without_footnotes).casefold()
    ).replace("为", "")


def _semantic_clauses_815(value: str) -> tuple[str, ...]:
    return tuple(
        clause
        for item in _SEMANTIC_CLAUSE_SPLIT_815.split(
            unicodedata.normalize("NFKC", value).casefold()
        )
        if (clause := _semantic_compact_815(item))
    )


def _semantic_marker_counts_815(value: str) -> Counter[str]:
    return Counter(_SEMANTIC_MARKER_815.findall(value))


def _semantic_clause_supported_815(value_clause: str, quote_clause: str) -> bool:
    if (
        _SEMANTIC_NUMBER_815.findall(value_clause)
        != _SEMANTIC_NUMBER_815.findall(quote_clause)
        or _semantic_marker_counts_815(value_clause)
        != _semantic_marker_counts_815(quote_clause)
    ):
        return False
    return value_clause in quote_clause


def _semantic_value_supported_by_quotes_815(
    value_snapshot: str,
    quote_snapshots: tuple[str, ...],
) -> bool:
    """Require clause-scoped semantic support without cross-quote field stitching."""

    if (
        type(value_snapshot) is not str
        or not value_snapshot
        or type(quote_snapshots) is not tuple
        or not quote_snapshots
        or any(type(quote) is not str or not quote for quote in quote_snapshots)
    ):
        return False
    value_clauses = _semantic_clauses_815(value_snapshot)
    if not value_clauses:
        return False
    for quote_snapshot in quote_snapshots:
        quote_clauses = _semantic_clauses_815(quote_snapshot)
        if not quote_clauses:
            continue
        quote_cursor = 0
        supported = True
        for value_clause in value_clauses:
            selected = next(
                (
                    index
                    for index in range(quote_cursor, len(quote_clauses))
                    if _semantic_clause_supported_815(
                        value_clause, quote_clauses[index]
                    )
                ),
                None,
            )
            if selected is None:
                supported = False
                break
            quote_cursor = selected + 1
        if supported:
            return True
    return False


def _quote_is_exact_literal_page_anchor_815(
    quote_snapshot: str,
    page_content_snapshot: str,
) -> bool:
    """Require byte-for-text literal occurrence including adjacent footnote markers."""

    if (
        type(quote_snapshot) is not str
        or not quote_snapshot
        or type(page_content_snapshot) is not str
        or not page_content_snapshot
    ):
        return False
    offset = page_content_snapshot.find(quote_snapshot)
    while offset >= 0:
        end = offset + len(quote_snapshot)
        preceding = _FOOTNOTE_MARKER_BEFORE_815.search(
            page_content_snapshot,
            0,
            offset,
        )
        following = _FOOTNOTE_MARKER_815.match(page_content_snapshot, end)
        if preceding is None and following is None:
            return True
        offset = page_content_snapshot.find(quote_snapshot, offset + 1)
    return False


def _require_original_run_evidence_support_815(
    fields: tuple[FreeformFieldOutputV1, ...],
) -> None:
    for field in fields:
        if any(
            not _quote_is_exact_literal_page_anchor_815(
                evidence.quote_snapshot,
                evidence.locator.content_snapshot,
            )
            for evidence in field.evidence
        ):
            _reject("FIELD_ATTEMPT_LITERAL_QUOTE_INVALID")
        if field.state == "present" and (
            field.value_snapshot is None
            or not _semantic_value_supported_by_quotes_815(
                field.value_snapshot,
                tuple(evidence.quote_snapshot for evidence in field.evidence),
            )
        ):
            _reject("FIELD_ATTEMPT_SEMANTIC_VALUE_INVALID")


def _load_field_attempt_row(value: object) -> Schema67FieldAttempt815V1:
    if type(value) is not dict or frozenset(value) != _ROW_KEYS:
        _reject("FIELD_ATTEMPT_ARTIFACT_INVALID")
    row = cast(dict[str, object], value)
    outcome = _require_wire_string(row["parse_outcome"])
    derivation_kind = _require_wire_string(row["derivation_kind"])
    attempted = row["attempted"]
    provider_visible = row["provider_visible"]
    model_returned_state = row["model_returned_state"]
    final_state = row["final_state"]
    coordinate_values = row["coordinate_evidence_sha256s"]
    if (
        outcome not in _PARSE_OUTCOMES
        or derivation_kind
        not in {"MODEL_RESPONSE", "CODE_OWNED_DEFERRED_UNKNOWN"}
        or type(attempted) is not bool
        or type(provider_visible) is not bool
        or attempted != provider_visible
        or (
            model_returned_state is not None
            and model_returned_state
            not in {"present", "absent_explicitly", "unknown"}
        )
        or final_state not in {"present", "absent_explicitly", "unknown"}
        or type(coordinate_values) is not list
        or any(
            type(item) is not str
            or len(item) != 64
            or any(character not in "0123456789abcdef" for character in item)
            for item in cast(list[object], coordinate_values)
        )
    ):
        _reject("FIELD_ATTEMPT_ARTIFACT_INVALID")
    schema_order = _require_wire_integer(row["schema_order"])
    typed_reason = _require_optional_wire_string(row["typed_reason"])
    task_key = _require_optional_wire_string(row["task_key"])
    task_ordinal = _require_optional_wire_integer(row["task_ordinal"])
    request_ordinal = _require_optional_wire_integer(row["request_ordinal"])
    response_ordinal = _require_optional_wire_integer(row["response_ordinal"])
    request_body_sha256 = _require_optional_wire_string(
        row["request_body_sha256"]
    )
    raw_response_sha256 = _require_optional_wire_string(
        row["raw_response_sha256"]
    )
    raw_response_byte_size = _require_optional_wire_integer(
        row["raw_response_byte_size"]
    )
    initial_failure_reason = _require_optional_wire_string(
        row["initial_failure_reason"]
    )
    repair_attempted = _require_wire_integer(
        row["repair_attempted"], minimum=0
    )
    if repair_attempted not in {0, 1}:
        _reject("FIELD_ATTEMPT_ARTIFACT_INVALID")
    repair_parent_bound_attempt_hash = _require_optional_wire_string(
        row["repair_parent_bound_attempt_hash"]
    )
    repair_parent_verification_hash = _require_optional_wire_string(
        row["repair_parent_verification_hash"]
    )
    repair_request_sha256 = _require_optional_wire_string(
        row["repair_request_sha256"]
    )
    repair_raw_response_sha256 = _require_optional_wire_string(
        row["repair_raw_response_sha256"]
    )
    repair_raw_response_byte_size = _require_optional_wire_integer(
        row["repair_raw_response_byte_size"]
    )
    repair_values = (
        repair_parent_bound_attempt_hash,
        repair_parent_verification_hash,
        repair_request_sha256,
        repair_raw_response_sha256,
        repair_raw_response_byte_size,
    )
    provider_values = (
        task_key,
        task_ordinal,
        request_ordinal,
        response_ordinal,
        request_body_sha256,
        raw_response_sha256,
        raw_response_byte_size,
    )
    if (
        derivation_kind == "MODEL_RESPONSE"
        and (
            not provider_visible
            or model_returned_state is None
            or any(item is None for item in provider_values)
        )
    ) or (
        derivation_kind == "CODE_OWNED_DEFERRED_UNKNOWN"
        and (
            provider_visible
            or any(item is not None for item in provider_values)
            or model_returned_state is not None
            or final_state != "unknown"
            or typed_reason
            not in {"FORMATION_MODE_DEFERRED", "SOURCE_NOT_AVAILABLE"}
            or bool(coordinate_values)
            or initial_failure_reason is not None
            or repair_attempted != 0
            or any(item is not None for item in repair_values)
            or outcome != "CODE_OWNED_DEFERRED_UNKNOWN"
        )
    ) or (
        repair_attempted == 0 and any(item is not None for item in repair_values)
    ) or (
        repair_attempted == 1
        and (
            initial_failure_reason is None
            or any(item is None for item in repair_values)
        )
    ) or (
        outcome == "PARSED_UNKNOWN_EVIDENCE_INVALID"
        and initial_failure_reason is None
    ) or (
        repair_attempted == 0
        and initial_failure_reason is not None
        and outcome != "PARSED_UNKNOWN_EVIDENCE_INVALID"
    ):
        _reject("FIELD_ATTEMPT_ARTIFACT_INVALID")
    return Schema67FieldAttempt815V1(
        contract=cast(
            Literal["schema67-field-attempt.815.v1"],
            _require_wire_string(row["contract"]),
        ),
        derivation_kind=cast(FieldAttemptDerivationKind815, derivation_kind),
        field_id=_require_wire_string(row["field_id"]),
        schema_order=schema_order,
        attempted=attempted,
        provider_visible=provider_visible,
        task_key=task_key,
        task_ordinal=task_ordinal,
        request_ordinal=request_ordinal,
        response_ordinal=response_ordinal,
        request_body_sha256=request_body_sha256,
        raw_response_sha256=raw_response_sha256,
        raw_response_byte_size=raw_response_byte_size,
        initial_failure_reason=initial_failure_reason,
        repair_attempted=cast(Literal[0, 1], repair_attempted),
        repair_parent_bound_attempt_hash=repair_parent_bound_attempt_hash,
        repair_parent_verification_hash=repair_parent_verification_hash,
        repair_request_sha256=repair_request_sha256,
        repair_raw_response_sha256=repair_raw_response_sha256,
        repair_raw_response_byte_size=repair_raw_response_byte_size,
        parse_outcome=cast(FieldAttemptParseOutcome815, outcome),
        model_returned_state=model_returned_state,
        final_state=final_state,
        typed_reason=typed_reason,
        coordinate_evidence_sha256s=tuple(cast(list[str], coordinate_values)),
        candidate_field_sha256=_require_wire_string(
            row["candidate_field_sha256"]
        ),
        evidence_receipt_sha256=_require_wire_string(
            row["evidence_receipt_sha256"]
        ),
        row_sha256=_require_wire_string(row["row_sha256"]),
    )


def _require_batch_repair_contract(
    *,
    derivation_source: FieldAttemptManifestSource815,
    task_keys: tuple[str, ...],
    rows: tuple[Schema67FieldAttempt815V1, ...],
    provider_calls: int,
    transport_retries: int,
    response_contract_repairs: int,
    evidence_repairs: int,
    repair_task_key: str | None,
    repair_field_ids: tuple[str, ...],
) -> None:
    extras = transport_retries + response_contract_repairs + evidence_repairs
    repaired_rows = tuple(row for row in rows if row.repair_attempted == 1)
    repaired_ids = tuple(row.field_id for row in repaired_rows)
    if (
        transport_retries != 0
        or response_contract_repairs != 0
        or evidence_repairs not in range(0, 9)
        or extras > 8
        or provider_calls > 16
        or len(repair_field_ids) != len(set(repair_field_ids))
        or repair_field_ids
        != tuple(field_id for field_id in ORDERED_FIELD_IDS if field_id in repair_field_ids)
    ):
        _reject("FIELD_ATTEMPT_REPAIR_BUDGET_INVALID")
    if derivation_source == "SYNTHETIC_TEST_ONLY":
        if (
            provider_calls != 0
            or extras != 0
            or repair_task_key is not None
            or repair_field_ids
            or repaired_rows
        ):
            _reject("FIELD_ATTEMPT_REPAIR_BUDGET_INVALID")
        return
    if (
        derivation_source != "EC01_ORIGINAL_RUN"
        or provider_calls != 8 + evidence_repairs
    ):
        _reject("FIELD_ATTEMPT_REPAIR_BUDGET_INVALID")
    if evidence_repairs == 0:
        if repair_task_key is not None or repair_field_ids or repaired_rows:
            _reject("FIELD_ATTEMPT_REPAIR_LINEAGE_INVALID")
        return
    if (
        repair_task_key != deepseek._SHARED_EVIDENCE_REPAIR_TASK_KEY
        or not repair_field_ids
        or repaired_ids != repair_field_ids
    ):
        _reject("FIELD_ATTEMPT_REPAIR_LINEAGE_INVALID")
    shared_repair_lineages = {
        (
            row.repair_request_sha256,
            row.repair_raw_response_sha256,
            row.repair_raw_response_byte_size,
        )
        for row in repaired_rows
    }
    repaired_task_keys = tuple(
        dict.fromkeys(cast(str, row.task_key) for row in repaired_rows)
    )
    parent_lineages_by_task = {
        task_key: {
            (
                row.repair_parent_bound_attempt_hash,
                row.repair_parent_verification_hash,
            )
            for row in repaired_rows
            if row.task_key == task_key
        }
        for task_key in repaired_task_keys
    }
    if (
        len(shared_repair_lineages) != evidence_repairs
        or any(row.task_key not in task_keys for row in repaired_rows)
        or any(len(values) != 1 for values in parent_lineages_by_task.values())
        or len(repaired_task_keys) != evidence_repairs
        or len(
            {
                next(iter(values))
                for values in parent_lineages_by_task.values()
            }
        )
        != len(repaired_task_keys)
    ):
        _reject("FIELD_ATTEMPT_REPAIR_LINEAGE_INVALID")


def _require_task_repair_field_order_815(
    repair_field_ids: tuple[str, ...],
    task_contract_field_ids: tuple[str, ...],
) -> None:
    repair_field_id_set = frozenset(repair_field_ids)
    if (
        not repair_field_ids
        or len(repair_field_id_set) != len(repair_field_ids)
        or repair_field_ids
        != tuple(
            field_id
            for field_id in task_contract_field_ids
            if field_id in repair_field_id_set
        )
    ):
        _reject("FIELD_ATTEMPT_REPAIR_LINEAGE_INVALID")


def _load_field_attempt_manifest(value: object) -> Schema67FieldAttemptManifest815V1:
    if type(value) is not dict or frozenset(value) != _MANIFEST_KEYS:
        _reject("FIELD_ATTEMPT_ARTIFACT_INVALID")
    manifest = cast(dict[str, object], value)
    row_values = manifest["rows"]
    if type(row_values) is not list:
        _reject("FIELD_ATTEMPT_ARTIFACT_INVALID")
    rows = tuple(_load_field_attempt_row(row) for row in row_values)
    derivation_source = _require_wire_string(manifest["derivation_source"])
    if derivation_source not in {"SYNTHETIC_TEST_ONLY", "EC01_ORIGINAL_RUN"}:
        _reject("FIELD_ATTEMPT_ARTIFACT_INVALID")
    task_keys = _require_wire_string_list(manifest["task_keys"])
    provider_calls = _require_wire_integer(manifest["provider_calls"], minimum=0)
    transport_retries = _require_wire_integer(
        manifest["transport_retries"], minimum=0
    )
    response_contract_repairs = _require_wire_integer(
        manifest["response_contract_repairs"], minimum=0
    )
    evidence_repairs = _require_wire_integer(
        manifest["evidence_repairs"], minimum=0
    )
    repair_task_key = _require_optional_wire_string(manifest["repair_task_key"])
    repair_field_ids = _require_wire_string_list(manifest["repair_field_ids"])
    attempted_field_count = _require_wire_integer(
        manifest["attempted_field_count"], minimum=0
    )
    provider_visible_count = _require_wire_integer(
        manifest["provider_visible_count"], minimum=0
    )
    real_model_output_count = _require_wire_integer(
        manifest["real_model_output_count"], minimum=0
    )
    code_deferred_count = _require_wire_integer(
        manifest["code_deferred_count"], minimum=0
    )
    dispositioned_count = _require_wire_integer(
        manifest["dispositioned_count"], minimum=0
    )
    unclassified_count = _require_wire_integer(
        manifest["unclassified_count"], minimum=0
    )
    coordinate_evidence_companion_sha256 = _require_optional_wire_string(
        manifest["coordinate_evidence_companion_sha256"]
    )
    model_rows = tuple(row for row in rows if row.provider_visible)
    deferred_rows = tuple(row for row in rows if not row.provider_visible)
    if (
        tuple(row.field_id for row in rows) != ORDERED_FIELD_IDS
        or tuple(row.schema_order for row in rows) != tuple(range(1, 68))
        or attempted_field_count != len(model_rows)
        or provider_visible_count != len(model_rows)
        or real_model_output_count != len(model_rows)
        or code_deferred_count != len(deferred_rows)
        or dispositioned_count != len(rows)
        or unclassified_count != 0
        or dispositioned_count != 67
    ):
        _reject("FIELD_ATTEMPT_ARTIFACT_INVALID")
    exact_source = cast(FieldAttemptManifestSource815, derivation_source)
    _require_batch_repair_contract(
        derivation_source=exact_source,
        task_keys=task_keys,
        rows=rows,
        provider_calls=provider_calls,
        transport_retries=transport_retries,
        response_contract_repairs=response_contract_repairs,
        evidence_repairs=evidence_repairs,
        repair_task_key=repair_task_key,
        repair_field_ids=repair_field_ids,
    )
    return Schema67FieldAttemptManifest815V1(
        contract=cast(
            Literal["schema67-field-attempt-manifest.815.v1"],
            _require_wire_string(manifest["contract"]),
        ),
        derivation_source=exact_source,
        experiment_id=_require_wire_string(manifest["experiment_id"]),
        execution_identity_sha256=_require_wire_string(
            manifest["execution_identity_sha256"]
        ),
        run_id=_require_wire_string(manifest["run_id"]),
        attempt_id=_require_wire_string(manifest["attempt_id"]),
        receipt_id=_require_wire_string(manifest["receipt_id"]),
        integration_head=_require_wire_string(manifest["integration_head"]),
        integration_tree=_require_wire_string(manifest["integration_tree"]),
        run_derivation_sha256=_require_wire_string(
            manifest["run_derivation_sha256"]
        ),
        revision_validation_sha256=_require_wire_string(
            manifest["revision_validation_sha256"]
        ),
        revision_set_sha256=_require_wire_string(
            manifest["revision_set_sha256"]
        ),
        request_manifest_sha256=_require_wire_string(
            manifest["request_manifest_sha256"]
        ),
        schema_rows_sha256=_require_wire_string(manifest["schema_rows_sha256"]),
        ordered_field_ids=_require_wire_string_list(manifest["ordered_field_ids"]),
        task_keys=task_keys,
        rows=rows,
        attempted_field_count=attempted_field_count,
        provider_visible_count=provider_visible_count,
        real_model_output_count=real_model_output_count,
        code_deferred_count=code_deferred_count,
        dispositioned_count=dispositioned_count,
        unclassified_count=unclassified_count,
        request_body_sha256s=_require_wire_string_list(
            manifest["request_body_sha256s"]
        ),
        raw_response_sha256s=_require_wire_string_list(
            manifest["raw_response_sha256s"]
        ),
        provider_calls=provider_calls,
        transport_retries=cast(Literal[0, 1], transport_retries),
        response_contract_repairs=cast(
            Literal[0, 1], response_contract_repairs
        ),
        evidence_repairs=evidence_repairs,
        repair_task_key=repair_task_key,
        repair_field_ids=repair_field_ids,
        terminal_sha256=_require_wire_string(manifest["terminal_sha256"]),
        candidate_fields_sha256=_require_wire_string(
            manifest["candidate_fields_sha256"]
        ),
        candidate_evidence_sha256=_require_wire_string(
            manifest["candidate_evidence_sha256"]
        ),
        coordinate_evidence_companion_sha256=(
            coordinate_evidence_companion_sha256
        ),
        manifest_sha256=_require_wire_string(manifest["manifest_sha256"]),
        formal_candidate_derivation_sha256=_require_wire_string(
            manifest["formal_candidate_derivation_sha256"]
        ),
    )


def _load_fields_artifact(value: object) -> tuple[FreeformFieldOutputV1, ...]:
    if type(value) is not list:
        _reject("FIELD_ATTEMPT_ARTIFACT_INVALID")
    try:
        return tuple(FreeformFieldOutputV1.model_validate(item) for item in value)
    except (TypeError, ValueError, ValidationError):
        _reject("FIELD_ATTEMPT_ARTIFACT_INVALID")


def _load_evidence_artifact(
    value: object,
) -> tuple[FreeformEvidenceBindingReceiptV1, ...]:
    if type(value) is not list:
        _reject("FIELD_ATTEMPT_ARTIFACT_INVALID")
    try:
        return tuple(
            FreeformEvidenceBindingReceiptV1.model_validate(item) for item in value
        )
    except (TypeError, ValueError, ValidationError):
        _reject("FIELD_ATTEMPT_ARTIFACT_INVALID")


def _require_terminal_bytes(value: object) -> bytes:
    if type(value) is not bytes or not value:
        _reject("FIELD_ATTEMPT_TERMINAL_INVALID")
    try:
        decoded = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _reject("FIELD_ATTEMPT_TERMINAL_INVALID")
    if (
        type(decoded) is not dict
        or value != _canonical_bytes(decoded)
        or decoded.get("status") != "SUCCEEDED"
        or decoded.get("failed_ordinal") is not None
    ):
        _reject("FIELD_ATTEMPT_TERMINAL_INVALID")
    return value


def _require_task_inputs(
    *,
    task_keys: object,
    field_task_ordinals: object,
    request_bodies: object,
    raw_response_bodies: object,
) -> tuple[tuple[str, ...], tuple[int, ...], tuple[bytes, ...], tuple[bytes, ...]]:
    if (
        type(task_keys) is not tuple
        or len(task_keys) != 8
        or any(type(value) is not str or not value for value in task_keys)
        or len(set(task_keys)) != 8
        or type(field_task_ordinals) is not tuple
        or len(field_task_ordinals) != 67
        or any(type(value) is not int or value < 1 or value > 8 for value in field_task_ordinals)
        or set(field_task_ordinals) != set(range(1, 9))
        or type(request_bodies) is not tuple
        or len(request_bodies) != 8
        or any(type(value) is not bytes or not value for value in request_bodies)
        or type(raw_response_bodies) is not tuple
        or len(raw_response_bodies) != 8
        or any(type(value) is not bytes or not value for value in raw_response_bodies)
    ):
        _reject("FIELD_ATTEMPT_TASK_INPUT_INVALID")
    return (
        cast(tuple[str, ...], task_keys),
        cast(tuple[int, ...], field_task_ordinals),
        cast(tuple[bytes, ...], request_bodies),
        cast(tuple[bytes, ...], raw_response_bodies),
    )


def _require_fields(
    value: object,
    *,
    reason: str,
) -> tuple[FreeformFieldOutputV1, ...]:
    if (
        type(value) is not tuple
        or len(value) != 67
        or any(type(item) is not FreeformFieldOutputV1 for item in value)
    ):
        _reject(reason)
    try:
        checked = tuple(
            FreeformFieldOutputV1.model_validate(
                item.model_dump(mode="python", round_trip=True)
            )
            for item in value
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        _reject(reason)
    if (
        checked != value
        or tuple(item.field_id for item in checked) != ORDERED_FIELD_IDS
        or any(item.product_version_id != "596-1" for item in checked)
    ):
        _reject(reason)
    return checked


def _require_evidence(
    value: object,
    *,
    fields: tuple[FreeformFieldOutputV1, ...],
    reason: str,
) -> tuple[FreeformEvidenceBindingReceiptV1, ...]:
    if (
        type(value) is not tuple
        or len(value) != 67
        or any(type(item) is not FreeformEvidenceBindingReceiptV1 for item in value)
    ):
        _reject(reason)
    try:
        checked = tuple(
            FreeformEvidenceBindingReceiptV1.model_validate(
                item.model_dump(mode="python", round_trip=True)
            )
            for item in value
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        _reject(reason)
    if (
        checked != value
        or tuple(item.field_id for item in checked) != ORDERED_FIELD_IDS
        or any(
            receipt.product_version_id != field.product_version_id
            or receipt.field_id != field.field_id
            or receipt.state != field.state
            or receipt.value_snapshot != field.value_snapshot
            or receipt.evidence != field.evidence
            for field, receipt in zip(fields, checked, strict=True)
        )
    ):
        _reject(reason)
    return checked


def _require_parse_outcomes(
    value: object,
    fields: tuple[FreeformFieldOutputV1, ...],
    derivation_kinds: tuple[FieldAttemptDerivationKind815, ...],
) -> tuple[FieldAttemptParseOutcome815, ...]:
    if (
        type(value) is not tuple
        or len(value) != 67
        or len(derivation_kinds) != 67
    ):
        _reject("FIELD_ATTEMPT_PARSE_OUTCOME_INVALID")
    checked: list[FieldAttemptParseOutcome815] = []
    for outcome, field, derivation_kind in zip(
        value, fields, derivation_kinds, strict=True
    ):
        if type(outcome) is not str or outcome not in _PARSE_OUTCOMES:
            _reject("FIELD_ATTEMPT_PARSE_OUTCOME_INVALID")
        if derivation_kind == "CODE_OWNED_DEFERRED_UNKNOWN":
            if (
                outcome != "CODE_OWNED_DEFERRED_UNKNOWN"
                or field.state != "unknown"
                or field.value_snapshot is not None
                or field.evidence
            ):
                _reject("FIELD_ATTEMPT_PARSE_OUTCOME_INVALID")
        elif (
            outcome == "CODE_OWNED_DEFERRED_UNKNOWN"
            or (field.state == "present" and outcome != "PARSED_PRESENT")
            or (
                field.state == "absent_explicitly"
                and outcome != "PARSED_ABSENT_EXPLICITLY"
            )
            or (field.state == "unknown" and outcome not in _UNKNOWN_OUTCOMES)
        ):
            _reject("FIELD_ATTEMPT_PARSE_OUTCOME_INVALID")
        checked.append(cast(FieldAttemptParseOutcome815, outcome))
    return tuple(checked)


def _field_sha256(field: FreeformFieldOutputV1) -> str:
    return canonical_hash(
        "schema67-candidate-field.815.v1",
        field.model_dump(mode="python", round_trip=True),
    )


def _candidate_fields_sha256(fields: tuple[FreeformFieldOutputV1, ...]) -> str:
    return canonical_hash(
        _FIELD_SET_CONTRACT,
        {
            "ordered_field_ids": ORDERED_FIELD_IDS,
            "fields": tuple(
                item.model_dump(mode="python", round_trip=True) for item in fields
            ),
        },
    )


def _candidate_evidence_sha256(
    receipts: tuple[FreeformEvidenceBindingReceiptV1, ...],
) -> str:
    return canonical_hash(
        _EVIDENCE_SET_CONTRACT,
        {
            "ordered_field_ids": ORDERED_FIELD_IDS,
            "evidence_receipt_hashes": tuple(item.receipt_hash for item in receipts),
        },
    )


def _make_schema67_field_attempt_manifest_815(
    *,
    derivation_source: FieldAttemptManifestSource815,
    experiment_id: str,
    execution_identity_sha256: str,
    run_id: str,
    attempt_id: str,
    receipt_id: str,
    integration_head: str,
    integration_tree: str,
    run_derivation_sha256: str,
    revision_validation_sha256: str,
    revision_set_sha256: str,
    request_manifest_sha256: str,
    schema_rows_sha256: str,
    task_keys: tuple[str, ...],
    field_task_ordinals: tuple[int | None, ...],
    request_body_sha256s: tuple[str, ...],
    raw_response_bodies: tuple[bytes, ...],
    derivation_kinds: tuple[FieldAttemptDerivationKind815, ...],
    model_returned_states: tuple[FieldAttemptState815 | None, ...],
    typed_reasons: tuple[str | None, ...],
    coordinate_evidence_sha256s_by_field: dict[str, tuple[str, ...]],
    coordinate_evidence_companion_sha256: str | None,
    parse_outcomes: tuple[FieldAttemptParseOutcome815, ...],
    initial_failure_reasons: tuple[str | None, ...],
    provider_calls: int,
    transport_retries: Literal[0, 1],
    response_contract_repairs: Literal[0, 1],
    evidence_repairs: int,
    repair_task_key: str | None,
    repair_field_ids: tuple[str, ...],
    repair_lineage_by_field: dict[str, tuple[str, str, str]],
    repair_raw_by_request_sha256: dict[str, bytes],
    parsed_fields: tuple[FreeformFieldOutputV1, ...],
    parsed_evidence_receipts: tuple[FreeformEvidenceBindingReceiptV1, ...],
    terminal_sha256: str,
    candidate_fields: tuple[FreeformFieldOutputV1, ...],
    candidate_evidence_receipts: tuple[FreeformEvidenceBindingReceiptV1, ...],
) -> Schema67FieldAttemptManifest815V1:
    identity_values = (
        experiment_id,
        execution_identity_sha256,
        run_id,
        attempt_id,
        receipt_id,
        integration_head,
        integration_tree,
        run_derivation_sha256,
        revision_validation_sha256,
        revision_set_sha256,
        request_manifest_sha256,
        schema_rows_sha256,
    )
    if derivation_source == "SYNTHETIC_TEST_ONLY":
        if any(value != _SYNTHETIC_IDENTITY for value in identity_values):
            _reject("FIELD_ATTEMPT_DERIVATION_SOURCE_INVALID")
    elif derivation_source == "EC01_ORIGINAL_RUN":
        if any(value == _SYNTHETIC_IDENTITY for value in identity_values):
            _reject("FIELD_ATTEMPT_DERIVATION_SOURCE_INVALID")
    else:
        _reject("FIELD_ATTEMPT_DERIVATION_SOURCE_INVALID")
    if (
        type(task_keys) is not tuple
        or len(task_keys) != 8
        or any(type(value) is not str or not value for value in task_keys)
        or len(set(task_keys)) != 8
        or type(field_task_ordinals) is not tuple
        or len(field_task_ordinals) != 67
        or type(derivation_kinds) is not tuple
        or len(derivation_kinds) != 67
        or type(model_returned_states) is not tuple
        or len(model_returned_states) != 67
        or type(typed_reasons) is not tuple
        or len(typed_reasons) != 67
        or any(
            value is not None
            and value not in {"present", "absent_explicitly", "unknown"}
            for value in model_returned_states
        )
        or any(
            value is not None and (type(value) is not str or not value)
            for value in typed_reasons
        )
        or type(coordinate_evidence_sha256s_by_field) is not dict
        or not frozenset(coordinate_evidence_sha256s_by_field).issubset(
            ORDERED_FIELD_IDS
        )
        or any(
            type(values) is not tuple
            or any(
                type(value) is not str
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
                for value in values
            )
            for values in coordinate_evidence_sha256s_by_field.values()
        )
        or (
            coordinate_evidence_companion_sha256 is not None
            and (
                type(coordinate_evidence_companion_sha256) is not str
                or len(coordinate_evidence_companion_sha256) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in coordinate_evidence_companion_sha256
                )
            )
        )
        or type(initial_failure_reasons) is not tuple
        or len(initial_failure_reasons) != 67
        or any(
            value is not None and (type(value) is not str or not value)
            for value in initial_failure_reasons
        )
        or type(request_body_sha256s) is not tuple
        or len(request_body_sha256s) != 8
        or any(
            type(value) is not str
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in request_body_sha256s
        )
        or type(raw_response_bodies) is not tuple
        or len(raw_response_bodies) != 8
        or any(type(value) is not bytes or not value for value in raw_response_bodies)
    ):
        _reject("FIELD_ATTEMPT_TASK_INPUT_INVALID")
    if type(repair_lineage_by_field) is not dict:
        _reject("FIELD_ATTEMPT_REPAIR_LINEAGE_INVALID")
    repair_lineage_fields = frozenset(repair_lineage_by_field)
    repair_request_sha256s = frozenset(
        repair_lineage_by_field[field_id][2]
        for field_id in repair_field_ids
        if field_id in repair_lineage_by_field
    )
    if (
        evidence_repairs == 0
        and (repair_lineage_by_field or repair_raw_by_request_sha256)
    ) or (
        evidence_repairs > 0
        and (
            repair_lineage_fields != frozenset(repair_field_ids)
            or len(repair_request_sha256s) != evidence_repairs
            or type(repair_raw_by_request_sha256) is not dict
            or frozenset(repair_raw_by_request_sha256)
            != repair_request_sha256s
            or any(
                type(body) is not bytes or not body
                for body in repair_raw_by_request_sha256.values()
            )
            or any(
                type(lineage) is not tuple
                or len(lineage) != 3
                or any(
                    type(value) is not str
                    or len(value) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in value
                    )
                    for value in lineage
                )
                for lineage in repair_lineage_by_field.values()
            )
        )
    ):
        _reject("FIELD_ATTEMPT_REPAIR_LINEAGE_INVALID")
    exact_task_keys = task_keys
    exact_ordinals = field_task_ordinals
    exact_kinds = derivation_kinds
    exact_requests = request_body_sha256s
    exact_raw = raw_response_bodies
    exact_parsed_fields = _require_fields(
        parsed_fields,
        reason="FIELD_ATTEMPT_PARSED_FIELDS_INVALID",
    )
    exact_parsed_evidence = _require_evidence(
        parsed_evidence_receipts,
        fields=exact_parsed_fields,
        reason="FIELD_ATTEMPT_PARSED_EVIDENCE_INVALID",
    )
    exact_candidate_fields = _require_fields(
        candidate_fields,
        reason="FIELD_ATTEMPT_CANDIDATE_FIELDS_INVALID",
    )
    exact_candidate_evidence = _require_evidence(
        candidate_evidence_receipts,
        fields=exact_candidate_fields,
        reason="FIELD_ATTEMPT_CANDIDATE_EVIDENCE_INVALID",
    )
    if (
        exact_candidate_fields != exact_parsed_fields
        or exact_candidate_evidence != exact_parsed_evidence
    ):
        _reject("FIELD_ATTEMPT_CANDIDATE_JOIN_INVALID")
    exact_outcomes = _require_parse_outcomes(
        parse_outcomes, exact_parsed_fields, exact_kinds
    )
    if type(terminal_sha256) is not str or not terminal_sha256:
        _reject("FIELD_ATTEMPT_TERMINAL_INVALID")
    request_hashes = exact_requests
    raw_hashes = tuple(_sha256(value) for value in exact_raw)
    rows: list[Schema67FieldAttempt815V1] = []
    for (
        schema_order,
        field_id,
        derivation_kind,
        task_ordinal,
        model_returned_state,
        typed_reason,
        outcome,
        initial_failure_reason,
        field,
        receipt,
    ) in zip(
        range(1, 68),
        ORDERED_FIELD_IDS,
        exact_kinds,
        exact_ordinals,
        model_returned_states,
        typed_reasons,
        exact_outcomes,
        initial_failure_reasons,
        exact_parsed_fields,
        exact_parsed_evidence,
        strict=True,
    ):
        if derivation_kind == "MODEL_RESPONSE":
            if type(task_ordinal) is not int or task_ordinal < 1 or task_ordinal > 8:
                _reject("FIELD_ATTEMPT_TASK_INPUT_INVALID")
            task_key: str | None = exact_task_keys[task_ordinal - 1]
            request_ordinal: int | None = task_ordinal
            response_ordinal: int | None = task_ordinal
            request_body_sha256: str | None = request_hashes[task_ordinal - 1]
            raw_response_sha256: str | None = raw_hashes[task_ordinal - 1]
            raw_response_byte_size: int | None = len(exact_raw[task_ordinal - 1])
            provider_visible = True
            if model_returned_state is None:
                _reject("FIELD_ATTEMPT_TASK_INPUT_INVALID")
        elif derivation_kind == "CODE_OWNED_DEFERRED_UNKNOWN":
            if (
                task_ordinal is not None
                or model_returned_state is not None
                or typed_reason
                not in {"FORMATION_MODE_DEFERRED", "SOURCE_NOT_AVAILABLE"}
                or field.state != "unknown"
                or field.value_snapshot is not None
                or field.evidence
                or receipt.documents
                or receipt.evidence
                or initial_failure_reason is not None
            ):
                _reject("FIELD_ATTEMPT_DEFERRED_UNKNOWN_INVALID")
            task_key = None
            request_ordinal = None
            response_ordinal = None
            request_body_sha256 = None
            raw_response_sha256 = None
            raw_response_byte_size = None
            provider_visible = False
        else:
            _reject("FIELD_ATTEMPT_TASK_INPUT_INVALID")
        repair_lineage = repair_lineage_by_field.get(field_id)
        repair_attempted: Literal[0, 1] = 1 if repair_lineage else 0
        if repair_lineage is None:
            row_repair_parent_bound_attempt_hash = None
            row_repair_parent_verification_hash = None
            row_repair_request_sha256 = None
        else:
            (
                row_repair_parent_bound_attempt_hash,
                row_repair_parent_verification_hash,
                row_repair_request_sha256,
            ) = repair_lineage
        if repair_attempted and row_repair_request_sha256 is None:
            _reject("FIELD_ATTEMPT_REPAIR_LINEAGE_INVALID")
        repair_raw_response_body = (
            repair_raw_by_request_sha256.get(row_repair_request_sha256)
            if row_repair_request_sha256 is not None
            else None
        )
        if repair_attempted and repair_raw_response_body is None:
            _reject("FIELD_ATTEMPT_REPAIR_LINEAGE_INVALID")
        row_repair_raw_response_sha256 = (
            _sha256(repair_raw_response_body)
            if repair_raw_response_body is not None
            else None
        )
        row_repair_raw_response_byte_size = (
            len(repair_raw_response_body)
            if repair_raw_response_body is not None
            else None
        )
        if (
            outcome == "PARSED_UNKNOWN_EVIDENCE_INVALID"
            and initial_failure_reason is None
        ) or (
            repair_attempted == 0
            and
            initial_failure_reason is not None
            and outcome != "PARSED_UNKNOWN_EVIDENCE_INVALID"
        ):
            _reject("FIELD_ATTEMPT_PARSE_OUTCOME_INVALID")
        row_values: dict[str, object] = {
            "attempted": provider_visible,
            "candidate_field_sha256": _field_sha256(field),
            "coordinate_evidence_sha256s": (
                coordinate_evidence_sha256s_by_field.get(field_id, ())
            ),
            "contract": _ROW_CONTRACT,
            "derivation_kind": derivation_kind,
            "evidence_receipt_sha256": receipt.receipt_hash,
            "field_id": field_id,
            "final_state": field.state,
            "initial_failure_reason": initial_failure_reason,
            "model_returned_state": model_returned_state,
            "parse_outcome": outcome,
            "raw_response_byte_size": raw_response_byte_size,
            "raw_response_sha256": raw_response_sha256,
            "request_body_sha256": request_body_sha256,
            "request_ordinal": request_ordinal,
            "provider_visible": provider_visible,
            "repair_attempted": repair_attempted,
            "repair_parent_bound_attempt_hash": row_repair_parent_bound_attempt_hash,
            "repair_parent_verification_hash": row_repair_parent_verification_hash,
            "repair_raw_response_byte_size": row_repair_raw_response_byte_size,
            "repair_raw_response_sha256": row_repair_raw_response_sha256,
            "repair_request_sha256": row_repair_request_sha256,
            "response_ordinal": response_ordinal,
            "schema_order": schema_order,
            "task_key": task_key,
            "task_ordinal": task_ordinal,
            "typed_reason": typed_reason,
        }
        rows.append(
            Schema67FieldAttempt815V1(
                contract="schema67-field-attempt.815.v1",
                derivation_kind=derivation_kind,
                field_id=field_id,
                schema_order=schema_order,
                attempted=provider_visible,
                provider_visible=provider_visible,
                task_key=task_key,
                task_ordinal=task_ordinal,
                request_ordinal=request_ordinal,
                response_ordinal=response_ordinal,
                request_body_sha256=request_body_sha256,
                raw_response_sha256=raw_response_sha256,
                raw_response_byte_size=raw_response_byte_size,
                initial_failure_reason=initial_failure_reason,
                repair_attempted=repair_attempted,
                repair_parent_bound_attempt_hash=row_repair_parent_bound_attempt_hash,
                repair_parent_verification_hash=row_repair_parent_verification_hash,
                repair_request_sha256=row_repair_request_sha256,
                repair_raw_response_sha256=row_repair_raw_response_sha256,
                repair_raw_response_byte_size=row_repair_raw_response_byte_size,
                parse_outcome=outcome,
                model_returned_state=model_returned_state,
                final_state=field.state,
                typed_reason=typed_reason,
                coordinate_evidence_sha256s=(
                    coordinate_evidence_sha256s_by_field.get(field_id, ())
                ),
                candidate_field_sha256=cast(str, row_values["candidate_field_sha256"]),
                evidence_receipt_sha256=receipt.receipt_hash,
                row_sha256=canonical_hash(_ROW_CONTRACT, row_values),
            )
        )
    exact_rows = tuple(rows)
    if (
        set(
            cast(int, ordinal)
            for kind, ordinal in zip(exact_kinds, exact_ordinals, strict=True)
            if kind == "MODEL_RESPONSE"
        )
        != set(range(1, 9))
    ):
        _reject("FIELD_ATTEMPT_TASK_INPUT_INVALID")
    candidate_fields_sha256 = _candidate_fields_sha256(exact_candidate_fields)
    candidate_evidence_sha256 = _candidate_evidence_sha256(exact_candidate_evidence)
    provider_visible_count = sum(row.provider_visible for row in exact_rows)
    real_model_output_count = sum(
        row.model_returned_state is not None for row in exact_rows
    )
    code_deferred_count = sum(
        row.derivation_kind == "CODE_OWNED_DEFERRED_UNKNOWN"
        for row in exact_rows
    )
    dispositioned_count = len(exact_rows)
    unclassified_count = dispositioned_count - (
        provider_visible_count + code_deferred_count
    )
    if (
        provider_visible_count != real_model_output_count
        or dispositioned_count != 67
        or unclassified_count != 0
        or bool(coordinate_evidence_sha256s_by_field)
        != (coordinate_evidence_companion_sha256 is not None)
        or (
            coordinate_evidence_companion_sha256 is not None
            and any(
                (
                    row.final_state == "unknown"
                    and bool(row.coordinate_evidence_sha256s)
                )
                or (
                    row.final_state != "unknown"
                    and not row.coordinate_evidence_sha256s
                )
                or (row.final_state == "unknown" and row.typed_reason is None)
                or (row.final_state != "unknown" and row.typed_reason is not None)
                for row in exact_rows
            )
        )
    ):
        _reject("FIELD_ATTEMPT_DISPOSITION_INVALID")
    _require_batch_repair_contract(
        derivation_source=derivation_source,
        task_keys=exact_task_keys,
        rows=exact_rows,
        provider_calls=provider_calls,
        transport_retries=transport_retries,
        response_contract_repairs=response_contract_repairs,
        evidence_repairs=evidence_repairs,
        repair_task_key=repair_task_key,
        repair_field_ids=repair_field_ids,
    )
    manifest_values: dict[str, object] = {
        "attempted_field_count": provider_visible_count,
        "attempt_id": attempt_id,
        "candidate_evidence_sha256": candidate_evidence_sha256,
        "candidate_fields_sha256": candidate_fields_sha256,
        "code_deferred_count": code_deferred_count,
        "coordinate_evidence_companion_sha256": (
            coordinate_evidence_companion_sha256
        ),
        "contract": _MANIFEST_CONTRACT,
        "derivation_source": derivation_source,
        "dispositioned_count": dispositioned_count,
        "execution_identity_sha256": execution_identity_sha256,
        "experiment_id": experiment_id,
        "integration_head": integration_head,
        "integration_tree": integration_tree,
        "ordered_field_ids": ORDERED_FIELD_IDS,
        "raw_response_sha256s": raw_hashes,
        "evidence_repairs": evidence_repairs,
        "provider_calls": provider_calls,
        "provider_visible_count": provider_visible_count,
        "repair_field_ids": repair_field_ids,
        "repair_task_key": repair_task_key,
        "receipt_id": receipt_id,
        "request_body_sha256s": request_hashes,
        "request_manifest_sha256": request_manifest_sha256,
        "revision_set_sha256": revision_set_sha256,
        "revision_validation_sha256": revision_validation_sha256,
        "rows": tuple(row.to_wire() for row in exact_rows),
        "run_derivation_sha256": run_derivation_sha256,
        "run_id": run_id,
        "schema_rows_sha256": schema_rows_sha256,
        "task_keys": exact_task_keys,
        "terminal_sha256": terminal_sha256,
        "real_model_output_count": real_model_output_count,
        "response_contract_repairs": response_contract_repairs,
        "transport_retries": transport_retries,
        "unclassified_count": unclassified_count,
    }
    manifest_sha256 = canonical_hash(_MANIFEST_CONTRACT, manifest_values)
    derivation_sha256 = canonical_hash(
        _DERIVATION_CONTRACT,
        {
            "attempt_id": attempt_id,
            "candidate_evidence_sha256": candidate_evidence_sha256,
            "candidate_fields_sha256": candidate_fields_sha256,
            "derivation_source": derivation_source,
            "execution_identity_sha256": execution_identity_sha256,
            "experiment_id": experiment_id,
            "field_attempt_manifest_sha256": manifest_sha256,
            "integration_head": integration_head,
            "integration_tree": integration_tree,
            "receipt_id": receipt_id,
            "request_manifest_sha256": request_manifest_sha256,
            "revision_set_sha256": revision_set_sha256,
            "revision_validation_sha256": revision_validation_sha256,
            "run_derivation_sha256": run_derivation_sha256,
            "run_id": run_id,
            "schema_rows_sha256": schema_rows_sha256,
            "terminal_sha256": terminal_sha256,
        },
    )
    return Schema67FieldAttemptManifest815V1(
        contract="schema67-field-attempt-manifest.815.v1",
        derivation_source=derivation_source,
        experiment_id=experiment_id,
        execution_identity_sha256=execution_identity_sha256,
        run_id=run_id,
        attempt_id=attempt_id,
        receipt_id=receipt_id,
        integration_head=integration_head,
        integration_tree=integration_tree,
        run_derivation_sha256=run_derivation_sha256,
        revision_validation_sha256=revision_validation_sha256,
        revision_set_sha256=revision_set_sha256,
        request_manifest_sha256=request_manifest_sha256,
        schema_rows_sha256=schema_rows_sha256,
        ordered_field_ids=ORDERED_FIELD_IDS,
        task_keys=exact_task_keys,
        rows=exact_rows,
        attempted_field_count=provider_visible_count,
        provider_visible_count=provider_visible_count,
        real_model_output_count=real_model_output_count,
        code_deferred_count=code_deferred_count,
        dispositioned_count=dispositioned_count,
        unclassified_count=unclassified_count,
        request_body_sha256s=request_hashes,
        raw_response_sha256s=raw_hashes,
        provider_calls=provider_calls,
        transport_retries=transport_retries,
        response_contract_repairs=response_contract_repairs,
        evidence_repairs=evidence_repairs,
        repair_task_key=repair_task_key,
        repair_field_ids=repair_field_ids,
        terminal_sha256=terminal_sha256,
        candidate_fields_sha256=candidate_fields_sha256,
        candidate_evidence_sha256=candidate_evidence_sha256,
        coordinate_evidence_companion_sha256=(
            coordinate_evidence_companion_sha256
        ),
        manifest_sha256=manifest_sha256,
        formal_candidate_derivation_sha256=derivation_sha256,
    )


def make_schema67_field_attempt_manifest_815(
    *,
    task_keys: tuple[str, ...],
    field_task_ordinals: tuple[int, ...],
    request_bodies: tuple[bytes, ...],
    raw_response_bodies: tuple[bytes, ...],
    parse_outcomes: tuple[FieldAttemptParseOutcome815, ...],
    parsed_fields: tuple[FreeformFieldOutputV1, ...],
    parsed_evidence_receipts: tuple[FreeformEvidenceBindingReceiptV1, ...],
    terminal_bytes: bytes,
    candidate_fields: tuple[FreeformFieldOutputV1, ...],
    candidate_evidence_receipts: tuple[FreeformEvidenceBindingReceiptV1, ...],
) -> Schema67FieldAttemptManifest815V1:
    """Build an explicitly synthetic fixture manifest; never EC-01 PASS evidence."""

    exact_task_keys, exact_ordinals, exact_requests, exact_raw = _require_task_inputs(
        task_keys=task_keys,
        field_task_ordinals=field_task_ordinals,
        request_bodies=request_bodies,
        raw_response_bodies=raw_response_bodies,
    )
    exact_terminal = _require_terminal_bytes(terminal_bytes)
    return _make_schema67_field_attempt_manifest_815(
        derivation_source="SYNTHETIC_TEST_ONLY",
        experiment_id=_SYNTHETIC_IDENTITY,
        execution_identity_sha256=_SYNTHETIC_IDENTITY,
        run_id=_SYNTHETIC_IDENTITY,
        attempt_id=_SYNTHETIC_IDENTITY,
        receipt_id=_SYNTHETIC_IDENTITY,
        integration_head=_SYNTHETIC_IDENTITY,
        integration_tree=_SYNTHETIC_IDENTITY,
        run_derivation_sha256=_SYNTHETIC_IDENTITY,
        revision_validation_sha256=_SYNTHETIC_IDENTITY,
        revision_set_sha256=_SYNTHETIC_IDENTITY,
        request_manifest_sha256=_SYNTHETIC_IDENTITY,
        schema_rows_sha256=_SYNTHETIC_IDENTITY,
        task_keys=exact_task_keys,
        field_task_ordinals=tuple(exact_ordinals),
        request_body_sha256s=tuple(_sha256(value) for value in exact_requests),
        raw_response_bodies=exact_raw,
        derivation_kinds=tuple("MODEL_RESPONSE" for _ in ORDERED_FIELD_IDS),
        model_returned_states=tuple(item.state for item in parsed_fields),
        typed_reasons=tuple(None for _ in ORDERED_FIELD_IDS),
        coordinate_evidence_sha256s_by_field={},
        coordinate_evidence_companion_sha256=None,
        parse_outcomes=parse_outcomes,
        initial_failure_reasons=tuple(None for _ in ORDERED_FIELD_IDS),
        provider_calls=0,
        transport_retries=0,
        response_contract_repairs=0,
        evidence_repairs=0,
        repair_task_key=None,
        repair_field_ids=(),
        repair_lineage_by_field={},
        repair_raw_by_request_sha256={},
        parsed_fields=parsed_fields,
        parsed_evidence_receipts=parsed_evidence_receipts,
        terminal_sha256=_sha256(exact_terminal),
        candidate_fields=candidate_fields,
        candidate_evidence_receipts=candidate_evidence_receipts,
    )


def validate_formal_candidate_derivation_815(
    *,
    manifest: Schema67FieldAttemptManifest815V1,
    task_keys: tuple[str, ...],
    field_task_ordinals: tuple[int, ...],
    request_bodies: tuple[bytes, ...],
    raw_response_bodies: tuple[bytes, ...],
    parse_outcomes: tuple[FieldAttemptParseOutcome815, ...],
    parsed_fields: tuple[FreeformFieldOutputV1, ...],
    parsed_evidence_receipts: tuple[FreeformEvidenceBindingReceiptV1, ...],
    terminal_bytes: bytes,
    candidate_fields: tuple[FreeformFieldOutputV1, ...],
    candidate_evidence_receipts: tuple[FreeformEvidenceBindingReceiptV1, ...],
) -> FormalCandidateDerivationValidation815V1:
    """Freshly recompute every raw/parsed/Candidate join without running Golden."""

    if type(manifest) is not Schema67FieldAttemptManifest815V1:
        _reject("FIELD_ATTEMPT_MANIFEST_MISMATCH")
    expected = make_schema67_field_attempt_manifest_815(
        task_keys=task_keys,
        field_task_ordinals=field_task_ordinals,
        request_bodies=request_bodies,
        raw_response_bodies=raw_response_bodies,
        parse_outcomes=parse_outcomes,
        parsed_fields=parsed_fields,
        parsed_evidence_receipts=parsed_evidence_receipts,
        terminal_bytes=terminal_bytes,
        candidate_fields=candidate_fields,
        candidate_evidence_receipts=candidate_evidence_receipts,
    )
    if manifest != expected:
        _reject("FIELD_ATTEMPT_MANIFEST_MISMATCH")
    return _make_validation_result(
        expected,
        status="SYNTHETIC_TEST_ONLY",
    )


def _make_validation_result(
    manifest: Schema67FieldAttemptManifest815V1,
    *,
    status: Literal["PASS", "SYNTHETIC_TEST_ONLY"],
) -> FormalCandidateDerivationValidation815V1:
    if (
        (status == "PASS" and manifest.derivation_source != "EC01_ORIGINAL_RUN")
        or (
            status == "SYNTHETIC_TEST_ONLY"
            and manifest.derivation_source != "SYNTHETIC_TEST_ONLY"
        )
    ):
        _reject("FIELD_ATTEMPT_DERIVATION_SOURCE_INVALID")
    return FormalCandidateDerivationValidation815V1(
        contract="schema67-formal-candidate-validation.815.v1",
        status=status,
        derivation_source=manifest.derivation_source,
        ordered_field_count=67,
        attempted_field_count=manifest.attempted_field_count,
        request_count=8,
        raw_response_count=8,
        manifest_sha256=manifest.manifest_sha256,
        terminal_sha256=manifest.terminal_sha256,
        candidate_fields_sha256=manifest.candidate_fields_sha256,
        candidate_evidence_sha256=manifest.candidate_evidence_sha256,
        formal_candidate_derivation_sha256=(
            manifest.formal_candidate_derivation_sha256
        ),
        provider_calls=0,
    )


def _parse_outcome_from_candidate_field(
    field: FreeformFieldOutputV1,
) -> FieldAttemptParseOutcome815:
    if field.state == "present":
        return "PARSED_PRESENT"
    if field.state == "absent_explicitly":
        return "PARSED_ABSENT_EXPLICITLY"
    return "PARSED_UNKNOWN_NO_SUPPORT"


def _initial_evidence_failure_reason_by_field(
    run: EC01FormalCandidateRun815V1,
) -> dict[str, str]:
    reasons_by_field: dict[str, list[str]] = {}
    demoted_field_ids: set[str] = set()
    for execution in run.candidate.batch_execution.executions:
        demotion = execution.evidence_demotion
        if not isinstance(execution.initial, Schema67BoundAttemptV1):
            if demotion is not None or execution.evidence_repair is not None:
                _reject("FIELD_ATTEMPT_INITIAL_VERIFICATION_INVALID")
            continue
        if demotion is not None:
            demoted_field_ids.update(demotion.demoted_field_ids)
            matching_batches = execution.initial.verification_batches
            target_field_ids = demotion.demoted_field_ids
        elif execution.evidence_repair is not None:
            repair = execution.evidence_repair
            try:
                children = deepseek._schema67_repair_children(
                    initial=execution.initial,
                    locator_refs=tuple(
                        (item.field_id, item.locator_refs)
                        for item in repair.repair_plan.approved_locators
                    ),
                )
                parent_hash = deepseek._shared_repair_parent_hash(children)
            except (AttributeError, TypeError, ValueError, ValidationError):
                _reject("FIELD_ATTEMPT_INITIAL_VERIFICATION_INVALID")
            child_parent_hashes = {
                item.parent_verification_hash for item in children
            }
            matching_batches = tuple(
                batch
                for batch in execution.initial.verification_batches
                if batch.verification_hash in child_parent_hashes
            )
            target_field_ids = repair.repair_plan.field_ids
            demoted_field_ids.update(target_field_ids)
            if (
                not children
                or parent_hash != repair.repair_plan.parent_verification_hash
                or len(matching_batches) != len(child_parent_hashes)
            ):
                _reject("FIELD_ATTEMPT_INITIAL_VERIFICATION_INVALID")
        else:
            continue
        for batch in matching_batches:
            for result in batch.results:
                if result.field_id in target_field_ids and result.status != "PASS":
                    if not result.reason_codes:
                        _reject("FIELD_ATTEMPT_INITIAL_VERIFICATION_INVALID")
                    reasons_by_field.setdefault(result.field_id, []).extend(
                        result.reason_codes
                    )
    exact: dict[str, str] = {}
    for field_id in demoted_field_ids:
        reasons = tuple(dict.fromkeys(reasons_by_field.get(field_id, ())))
        if len(reasons) != 1:
            _reject("FIELD_ATTEMPT_INITIAL_VERIFICATION_INVALID")
        exact[field_id] = reasons[0]
    return exact


def validate_ec01_formal_candidate_run_derivation_815(
    *,
    run: EC01FormalCandidateRun815V1,
    revision_set_root: Path,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
) -> tuple[
    Schema67FieldAttemptManifest815V1,
    FormalCandidateDerivationValidation815V1,
]:
    """Freshly require one original EC-01 run and derive its C3 companion."""

    if type(run) is not EC01FormalCandidateRun815V1:
        _reject("FIELD_ATTEMPT_ORIGINAL_RUN_INVALID")
    try:
        exact_run = require_ec01_formal_candidate_run_815(
            run=run,
            revision_set_root=revision_set_root,
            field_contracts=field_contracts,
            execution_plan=execution_plan,
        )
    except EC01FormalCandidateRunError:
        _reject("FIELD_ATTEMPT_ORIGINAL_RUN_INVALID")
    return _validate_required_ec01_formal_candidate_run_derivation_815(
        exact_run=exact_run,
        field_contracts=field_contracts,
        execution_plan=execution_plan,
    )


def _validate_required_ec01_formal_candidate_run_derivation_815(
    *,
    exact_run: EC01FormalCandidateRun815V1,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
) -> tuple[
    Schema67FieldAttemptManifest815V1,
    FormalCandidateDerivationValidation815V1,
]:
    try:
        request_manifest = json.loads(exact_run.request_manifest_bytes.decode("utf-8"))
        task_rows = request_manifest["tasks"]
        schema_rows_sha256 = request_manifest["schema_rows_sha256"]
        if (
            type(schema_rows_sha256) is not str
            or schema_rows_sha256 != exact_run.schema_rows_sha256
            or schema_rows_sha256 != field_contracts.schema_rows_sha256
        ):
            raise ValueError
        if type(task_rows) is not list or len(task_rows) != 8:
            raise TypeError
        task_keys: list[str] = []
        request_hashes: list[str] = []
        field_to_ordinal: dict[str, int] = {}
        for ordinal, (task_row, task_slice) in enumerate(
            zip(task_rows, execution_plan.task_slices, strict=True),
            start=1,
        ):
            if type(task_row) is not dict:
                raise TypeError
            task_key = task_row["task_key"]
            field_ids = task_row["field_ids"]
            request_fact = task_row["canonical_request"]
            if (
                type(task_key) is not str
                or task_key != task_slice.task_key
                or type(field_ids) is not list
                or tuple(field_ids) != task_slice.field_ids
                or type(request_fact) is not dict
                or type(request_fact.get("external_sha256")) is not str
            ):
                raise ValueError
            task_keys.append(task_key)
            request_hashes.append(cast(str, request_fact["external_sha256"]))
            for field_id in field_ids:
                if type(field_id) is not str or field_id in field_to_ordinal:
                    raise ValueError
                field_to_ordinal[field_id] = ordinal
        deferred_field_ids = frozenset(execution_plan.deferred_unknown_field_ids)
        if (
            frozenset(field_to_ordinal) & deferred_field_ids
            or frozenset(field_to_ordinal) | deferred_field_ids
            != frozenset(ORDERED_FIELD_IDS)
        ):
            raise ValueError
    except (
        AttributeError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ):
        _reject("FIELD_ATTEMPT_ORIGINAL_RUN_INVALID")
    try:
        execution_mode = deepseek._require_schema67_execution_plan_mode_815(
            field_contracts=field_contracts,
            execution_plan=execution_plan,
            available_source_roles=("terms", "brochure", "rate_table"),
        )
        native_projection = (
            deepseek.build_schema67_native_pdf_execution_projection_815(
                field_contracts=field_contracts,
                base_execution_plan=deepseek.build_schema67_execution_plan(
                    field_contracts
                ),
                available_source_roles=("terms", "brochure", "rate_table"),
            )
            if execution_mode == "NATIVE_PDF_SOURCE_EXTRACT"
            else None
        )
    except (AttributeError, TypeError, ValueError, deepseek.DeepSeekCompilerError):
        _reject("FIELD_ATTEMPT_ORIGINAL_RUN_INVALID")
    fields = exact_run.candidate.fields
    evidence = exact_run.candidate.evidence_receipts
    if native_projection is None:
        _require_original_run_evidence_support_815(fields)
    initial_failure_by_field = _initial_evidence_failure_reason_by_field(exact_run)
    derivation_kinds: tuple[FieldAttemptDerivationKind815, ...] = tuple(
        (
            "CODE_OWNED_DEFERRED_UNKNOWN"
            if field_id in deferred_field_ids
            else "MODEL_RESPONSE"
        )
        for field_id in ORDERED_FIELD_IDS
    )
    field_task_ordinals = tuple(
        field_to_ordinal.get(field_id) for field_id in ORDERED_FIELD_IDS
    )
    parse_outcomes: tuple[FieldAttemptParseOutcome815, ...] = tuple(
        (
            "CODE_OWNED_DEFERRED_UNKNOWN"
            if kind == "CODE_OWNED_DEFERRED_UNKNOWN"
            else "PARSED_UNKNOWN_EVIDENCE_INVALID"
            if field.field_id in initial_failure_by_field and field.state == "unknown"
            else _parse_outcome_from_candidate_field(field)
        )
        for kind, field in zip(derivation_kinds, fields, strict=True)
    )
    initial_failure_reasons = tuple(
        initial_failure_by_field.get(field_id) for field_id in ORDERED_FIELD_IDS
    )
    model_returned_state_by_field: dict[str, FieldAttemptState815] = {}
    model_typed_reason_by_field: dict[str, str | None] = {}
    deferred_reason_by_field = (
        {
            item.field_id: item.reason for item in native_projection.code_deferred
        }
        if native_projection is not None
        else {}
    )
    coordinate_evidence_sha256s_by_field: dict[str, tuple[str, ...]] = {}
    coordinate_evidence_companion_sha256: str | None = None
    if native_projection is not None:
        try:
            for raw, task_slice in zip(
                exact_run.raw_responses,
                execution_plan.task_slices,
                strict=True,
            ):
                response = ModelTaskSelectionResponse815V1.model_validate(
                    json.loads(raw.response_bytes)
                )
                if (
                    response.task_key != task_slice.task_key
                    or tuple(item.field_id for item in response.fields)
                    != task_slice.field_ids
                ):
                    raise ValueError
                for selection_row in response.fields:
                    if selection_row.field_id in model_returned_state_by_field:
                        raise ValueError
                    model_returned_state_by_field[selection_row.field_id] = (
                        selection_row.state
                    )
                    model_typed_reason_by_field[selection_row.field_id] = (
                        selection_row.typed_reason
                    )
            for coordinate_row in (
                exact_run.coordinate_evidence_companion.coordinate_rows
            ):
                coordinate_evidence_sha256s_by_field[coordinate_row.field_id] = (
                    *coordinate_evidence_sha256s_by_field.get(
                        coordinate_row.field_id, ()
                    ),
                    coordinate_row.recomputed_coordinate_evidence_sha256(),
                )
            coordinate_evidence_companion_sha256 = (
                exact_run.coordinate_evidence_companion.companion_sha256
            )
            if (
                tuple(
                    field_id
                    for field_id in ORDERED_FIELD_IDS
                    if field_id in model_returned_state_by_field
                )
                != native_projection.provider_visible_field_ids
            ):
                raise ValueError
        except (
            AttributeError,
            KeyError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
            ValidationError,
            json.JSONDecodeError,
        ):
            _reject("FIELD_ATTEMPT_ORIGINAL_RUN_INVALID")
    else:
        model_returned_state_by_field = {
            item.field_id: item.state for item in fields
        }
    model_returned_states: tuple[FieldAttemptState815 | None, ...] = tuple(
        model_returned_state_by_field.get(field_id)
        for field_id in ORDERED_FIELD_IDS
    )
    candidate_state_by_field = {item.field_id: item.state for item in fields}
    typed_reasons = tuple(
        (
            deferred_reason_by_field[field_id]
            if field_id in deferred_reason_by_field
            else initial_failure_by_field.get(field_id)
            or model_typed_reason_by_field.get(field_id)
            or (
                "SOURCE_LOCATION_UNRESOLVED"
                if native_projection is not None
                and model_returned_state_by_field.get(field_id)
                in {"present", "absent_explicitly"}
                and candidate_state_by_field[field_id] == "unknown"
                else None
            )
        )
        for field_id in ORDERED_FIELD_IDS
    )
    batch_receipt = exact_run.candidate.batch_receipt
    repair_executions = tuple(
        (ordinal, execution)
        for ordinal, execution in enumerate(
            exact_run.candidate.batch_execution.executions,
            start=1,
        )
        if execution.evidence_repair is not None
    )
    repair_task_key: str | None = None
    repair_field_ids: tuple[str, ...] = ()
    repair_lineage_by_field: dict[str, tuple[str, str, str]] = {}
    repair_raw_by_request_sha256: dict[str, bytes] = {}
    if batch_receipt.evidence_repairs > 0:
        if (
            len(repair_executions) != batch_receipt.evidence_repairs
            or len(exact_run.repair_raw_responses)
            != batch_receipt.evidence_repairs
        ):
            _reject("FIELD_ATTEMPT_REPAIR_LINEAGE_INVALID")
        repair_task_key = deepseek._SHARED_EVIDENCE_REPAIR_TASK_KEY
        if any(
            repair_raw.ordinal != repair_ordinal
            or repair_raw.task_key != repair_task_key
            for repair_ordinal, repair_raw in enumerate(
                exact_run.repair_raw_responses,
                start=1,
            )
        ):
            _reject("FIELD_ATTEMPT_REPAIR_LINEAGE_INVALID")
        repair_request_sha256s: set[str] = set()
        for (task_ordinal, repair_execution), repair_raw in zip(
            repair_executions,
            exact_run.repair_raw_responses,
            strict=True,
        ):
            repair = repair_execution.evidence_repair
            if repair is None:
                _reject("FIELD_ATTEMPT_REPAIR_LINEAGE_INVALID")
            task_repair_field_ids = repair.repair_plan.field_ids
            _require_task_repair_field_order_815(
                task_repair_field_ids,
                execution_plan.task_slices[task_ordinal - 1].field_ids,
            )
            if (
                any(
                    field_to_ordinal.get(field_id) != task_ordinal
                    or field_id in repair_lineage_by_field
                    or field_id not in initial_failure_by_field
                    for field_id in task_repair_field_ids
                )
                or repair.accepted_response_sha256
                != repair_raw.response_sha256
            ):
                _reject("FIELD_ATTEMPT_REPAIR_LINEAGE_INVALID")
            repair_request_sha256s.add(repair.repair_request_sha256)
            repair_raw_by_request_sha256[
                repair.repair_request_sha256
            ] = repair_raw.response_bytes
            for field_id in task_repair_field_ids:
                repair_lineage_by_field[field_id] = (
                    repair.parent_bound_attempt_hash,
                    repair.repair_plan.parent_verification_hash,
                    repair.repair_request_sha256,
                )
        if len(repair_request_sha256s) != batch_receipt.evidence_repairs:
            _reject("FIELD_ATTEMPT_REPAIR_LINEAGE_INVALID")
        repair_field_ids = tuple(
            field_id
            for field_id in ORDERED_FIELD_IDS
            if field_id in repair_lineage_by_field
        )
    elif (
        batch_receipt.evidence_repairs != 0
        or repair_executions
        or exact_run.repair_raw_responses
    ):
        _reject("FIELD_ATTEMPT_REPAIR_LINEAGE_INVALID")
    manifest = _make_schema67_field_attempt_manifest_815(
        derivation_source="EC01_ORIGINAL_RUN",
        experiment_id=exact_run.experiment_id,
        execution_identity_sha256=exact_run.execution_identity_sha256,
        run_id=exact_run.run_id,
        attempt_id=exact_run.attempt_id,
        receipt_id=exact_run.receipt_id,
        integration_head=exact_run.integration_head,
        integration_tree=exact_run.integration_tree,
        run_derivation_sha256=exact_run.derivation_sha256,
        revision_validation_sha256=exact_run.revision_validation_sha256,
        revision_set_sha256=exact_run.terminal.revision_set_sha256,
        request_manifest_sha256=exact_run.request_manifest_sha256,
        schema_rows_sha256=schema_rows_sha256,
        task_keys=tuple(task_keys),
        field_task_ordinals=field_task_ordinals,
        request_body_sha256s=tuple(request_hashes),
        raw_response_bodies=tuple(
            item.response_bytes for item in exact_run.raw_responses
        ),
        derivation_kinds=derivation_kinds,
        model_returned_states=model_returned_states,
        typed_reasons=typed_reasons,
        coordinate_evidence_sha256s_by_field=(
            coordinate_evidence_sha256s_by_field
        ),
        coordinate_evidence_companion_sha256=(
            coordinate_evidence_companion_sha256
        ),
        parse_outcomes=parse_outcomes,
        initial_failure_reasons=initial_failure_reasons,
        provider_calls=batch_receipt.provider_calls,
        transport_retries=batch_receipt.transport_retries,
        response_contract_repairs=batch_receipt.response_contract_repairs,
        evidence_repairs=batch_receipt.evidence_repairs,
        repair_task_key=repair_task_key,
        repair_field_ids=repair_field_ids,
        repair_lineage_by_field=repair_lineage_by_field,
        repair_raw_by_request_sha256=repair_raw_by_request_sha256,
        parsed_fields=fields,
        parsed_evidence_receipts=evidence,
        terminal_sha256=exact_run.terminal.terminal_sha256,
        candidate_fields=fields,
        candidate_evidence_receipts=evidence,
    )
    return manifest, _make_validation_result(manifest, status="PASS")


def _require_synthetic_raw_parsed_consistency(
    *,
    manifest: Schema67FieldAttemptManifest815V1,
    raw_response_bodies: tuple[bytes, ...],
    parsed_fields: tuple[FreeformFieldOutputV1, ...],
) -> None:
    if manifest.derivation_source != "SYNTHETIC_TEST_ONLY":
        _reject("FIELD_ATTEMPT_DERIVATION_SOURCE_INVALID")
    parsed_by_field = {item.field_id: item for item in parsed_fields}
    try:
        for ordinal, raw_body in enumerate(raw_response_bodies, start=1):
            raw = json.loads(raw_body.decode("utf-8"))
            if (
                type(raw) is not dict
                or raw.get("task_key") != manifest.task_keys[ordinal - 1]
                or type(raw.get("fields")) is not list
            ):
                raise ValueError
            expected_ids = tuple(
                row.field_id
                for row in manifest.rows
                if row.derivation_kind == "MODEL_RESPONSE"
                and row.task_ordinal == ordinal
            )
            raw_rows = cast(list[object], raw["fields"])
            if tuple(
                row.get("field_id") if type(row) is dict else None
                for row in raw_rows
            ) != expected_ids:
                raise ValueError
            for raw_row in raw_rows:
                if type(raw_row) is not dict:
                    raise TypeError
                field_id = raw_row["field_id"]
                parsed = parsed_by_field[cast(str, field_id)]
                if raw_row.get("state") != parsed.state:
                    raise ValueError
                if parsed.state == "unknown":
                    if raw_row.get("value_snapshot") is not None or raw_row.get(
                        "evidence", []
                    ) not in ([], ()):
                        raise ValueError
                elif (
                    raw_row.get("value_snapshot") != parsed.value_snapshot
                    or raw_row.get("evidence")
                    != [
                        item.model_dump(mode="json", round_trip=True)
                        for item in parsed.evidence
                    ]
                ):
                    raise ValueError
    except (
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ):
        _reject("FIELD_ATTEMPT_RAW_PARSED_REPLAY_MISMATCH")


def validate_ec01_formal_candidate_run_artifact_815(
    *,
    artifact_root: Path,
    revision_set_root: Path,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
) -> tuple[
    Schema67FieldAttemptManifest815V1,
    FormalCandidateDerivationValidation815V1,
]:
    """Fresh-open a persisted original run and replay the formal C3 validator."""

    artifact_dir_fd: int | None = None
    try:
        artifact_dir_fd, opened = ec01_run._open_original_run_artifact_root_815(
            artifact_root
        )
        _, manifest_wire = ec01_run._read_original_run_artifact_json_815(
            artifact_dir_fd,
            "field-attempt-manifest.json",
            trailing_newline=True,
        )
        _, validation_wire = ec01_run._read_original_run_artifact_json_815(
            artifact_dir_fd,
            "formal-derivation-validation.json",
            trailing_newline=True,
        )
        persisted_manifest = _load_field_attempt_manifest(manifest_wire)
        validation_keys = {
            item.name
            for item in dataclass_fields(FormalCandidateDerivationValidation815V1)
        }
        if type(validation_wire) is not dict or set(validation_wire) != validation_keys:
            _reject("FIELD_ATTEMPT_ORIGINAL_RUN_ARTIFACT_INVALID")
        persisted_validation = FormalCandidateDerivationValidation815V1(
            **cast(Any, validation_wire)
        )
        if (
            persisted_manifest.derivation_source != "EC01_ORIGINAL_RUN"
            or persisted_validation.status != "PASS"
            or persisted_validation.derivation_source != "EC01_ORIGINAL_RUN"
            or persisted_validation
            != _make_validation_result(persisted_manifest, status="PASS")
        ):
            _reject("FIELD_ATTEMPT_ORIGINAL_RUN_ARTIFACT_INVALID")
        exact_run = ec01_run._require_ec01_formal_candidate_run_artifact_from_dir_fd_815(
            artifact_dir_fd=artifact_dir_fd,
            revision_set_root=revision_set_root,
            field_contracts=field_contracts,
            execution_plan=execution_plan,
        )
        manifest, validation = (
            _validate_required_ec01_formal_candidate_run_derivation_815(
                exact_run=exact_run,
                field_contracts=field_contracts,
                execution_plan=execution_plan,
            )
        )
        if manifest != persisted_manifest or validation != persisted_validation:
            _reject("FIELD_ATTEMPT_ORIGINAL_RUN_ARTIFACT_INVALID")
        ec01_run._require_original_run_artifact_root_binding_815(
            artifact_root,
            artifact_dir_fd,
            opened,
        )
        return manifest, validation
    except (EC01FormalCandidateRunError, TypeError):
        _reject("FIELD_ATTEMPT_ORIGINAL_RUN_ARTIFACT_INVALID")
    finally:
        if artifact_dir_fd is not None:
            os.close(artifact_dir_fd)


def validate_formal_candidate_derivation_directory_815(
    artifact_root: Path,
) -> FormalCandidateDerivationValidation815V1:
    """Fresh-open the fixed persisted artifact set and replay the existing validator."""

    if (
        not isinstance(artifact_root, Path)
        or not artifact_root.is_absolute()
        or not artifact_root.is_dir()
    ):
        _reject("FIELD_ATTEMPT_DIRECTORY_NOT_READY")
    _, manifest_wire = _read_canonical_artifact(
        artifact_root, "field-attempt-manifest.json"
    )
    manifest = _load_field_attempt_manifest(manifest_wire)
    request_bodies = tuple(
        _read_canonical_artifact(artifact_root, f"request-{ordinal:02d}.json")[0]
        for ordinal in range(1, 9)
    )
    raw_response_bodies = tuple(
        _read_canonical_artifact(
            artifact_root, f"raw-response-{ordinal:02d}.json"
        )[0]
        for ordinal in range(1, 9)
    )
    _, parsed_fields_wire = _read_canonical_artifact(
        artifact_root, "parsed-fields.json"
    )
    _, parsed_evidence_wire = _read_canonical_artifact(
        artifact_root, "parsed-evidence.json"
    )
    _, candidate_fields_wire = _read_canonical_artifact(
        artifact_root, "candidate-fields.json"
    )
    _, candidate_evidence_wire = _read_canonical_artifact(
        artifact_root, "candidate-evidence.json"
    )
    terminal_bytes, _ = _read_canonical_artifact(artifact_root, "terminal.json")
    parsed_fields = _load_fields_artifact(parsed_fields_wire)
    parsed_evidence = _load_evidence_artifact(parsed_evidence_wire)
    candidate_fields = _load_fields_artifact(candidate_fields_wire)
    candidate_evidence = _load_evidence_artifact(candidate_evidence_wire)
    _require_synthetic_raw_parsed_consistency(
        manifest=manifest,
        raw_response_bodies=raw_response_bodies,
        parsed_fields=parsed_fields,
    )
    if any(type(row.task_ordinal) is not int for row in manifest.rows):
        _reject("FIELD_ATTEMPT_ARTIFACT_INVALID")
    return validate_formal_candidate_derivation_815(
        manifest=manifest,
        task_keys=manifest.task_keys,
        field_task_ordinals=cast(
            tuple[int, ...], tuple(row.task_ordinal for row in manifest.rows)
        ),
        request_bodies=request_bodies,
        raw_response_bodies=raw_response_bodies,
        parse_outcomes=tuple(row.parse_outcome for row in manifest.rows),
        parsed_fields=parsed_fields,
        parsed_evidence_receipts=parsed_evidence,
        terminal_bytes=terminal_bytes,
        candidate_fields=candidate_fields,
        candidate_evidence_receipts=candidate_evidence,
    )


__all__ = [
    "FieldAttemptDerivationKind815",
    "FieldAttemptManifestSource815",
    "FieldAttemptParseOutcome815",
    "FormalCandidateDerivationValidation815V1",
    "FormalCandidateDerivationValidationError",
    "Schema67FieldAttempt815V1",
    "Schema67FieldAttemptManifest815V1",
    "make_schema67_field_attempt_manifest_815",
    "validate_ec01_formal_candidate_run_artifact_815",
    "validate_formal_candidate_derivation_815",
    "validate_formal_candidate_derivation_directory_815",
    "validate_ec01_formal_candidate_run_derivation_815",
]
