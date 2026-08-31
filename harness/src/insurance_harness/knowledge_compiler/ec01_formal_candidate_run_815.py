"""Task-local EC-01 Formal Candidate success path.

This module owns no second runner.  It records the raw responses around the
existing exact-eight runner and makes both execution and deterministic
validation use the same existing strict response parser and Evidence hydrator.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from dataclasses import fields as dataclass_fields
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal, Protocol, cast

from pydantic import SecretStr, ValidationError

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.extraction_tasks import (
    ArtifactRefV1,
    AttemptBudgetV1,
    ExtractionTaskProfileV1,
    MaterialRole,
    ParsedArtifactAdmissionPort,
    build_extraction_task_profile,
)
from insurance_harness.compiler.material_profiles import (
    ApprovedParsePolicy,
    FieldAuthority,
    MaterialProfile,
    ParsePolicyReceipt,
    SourceDocumentIdentity,
)
from insurance_harness.compiler.native_pdfplumber import (
    NativePdfSelectionProjection815V1,
    extract_native_pdf_selection_projection_815,
)
from insurance_harness.compiler.parsed_documents import (
    BlockLocatorV1,
    CapabilityEvidenceV1,
    CellLocatorV1,
    PageLocatorV1,
    ParseAttemptV1,
    ParseBlockV1,
    ParseCellV1,
    ParsedDocumentV1,
    ParseOutputFactsV1,
    ParsePageV1,
    ParseQualityDecisionV1,
    ParseQualityMeasuredFactsV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
    ParseTableV1,
    TableLocatorV1,
    build_parse_manifest,
)
from insurance_harness.goldenset import expert_golden_admission_596_2 as admission
from insurance_harness.goldenset.expert_golden_admission_596_2 import Schema67CandidateV2
from insurance_harness.knowledge_compiler import deepseek_locator_extractor_596_1 as deepseek
from insurance_harness.knowledge_compiler.deepseek_locator_extractor_596_1 import (
    CanonicalLocatorInputV1,
    DeepSeekCompilerError,
    DeepSeekTaskExecutionV1,
    Schema67ExecutionPlanV1,
    Schema67RoleTaskInputV1,
)
from insurance_harness.knowledge_compiler.revision_set_manifest_815 import (
    RevisionSetValidation815V1,
    require_revision_set_validation_value_815,
    validate_revision_set_manifest_815,
)
from insurance_harness.knowledge_compiler.schema67_native_pdf_selection_815 import (
    CoordinateEvidence815V1,
    CoordinateEvidenceCompanion815V1,
    Schema67SelectionCatalog815V1,
    build_field_selection_catalogs_815,
    hydrate_model_selection_response_815,
    make_coordinate_evidence_companion_815,
    require_model_selection_response_815,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import FieldContractSetV1
from insurance_harness.knowledge_compiler.vertical_falsification import (
    AdmittedParseArtifactV1,
)
from insurance_harness.live_env.config import ModelProfile
from insurance_harness.model_policy import ProductionModelPolicy

_REQUEST_MANIFEST_DOMAIN: Final[str] = "weknora.ec.request-preflight.v1"
_RUN_CONTRACT: Final[Literal["ec01-formal-candidate-run.815.v1"]] = (
    "ec01-formal-candidate-run.815.v1"
)
_TERMINAL_CONTRACT: Final[Literal["ec01-formal-candidate-terminal.815.v1"]] = (
    "ec01-formal-candidate-terminal.815.v1"
)
_RAW_INDEX_DOMAIN: Final[str] = "ec01-formal-candidate-raw-index.815.v1"
_DERIVATION_DOMAIN: Final[str] = "ec01-formal-candidate-derivation.815.v1"
_EXECUTION_IDENTITY_DOMAIN: Final[str] = "ec01-execution-identity.v1"
_ORIGINAL_RUN_ARTIFACT_MAX_BYTES: Final[int] = 8 * 1024 * 1024
_CANDIDATE_TREE_SHA1: Final[str] = "bf38d51bef0b6d1ae119bb0535e8ff0dc9463c53"
_REVISION_SET_SHA256: Final[str] = (
    "a45b27adb592e89b0fd0a66785e63baff344edc68fd5d965326a59a62b94dc2a"
)
_REVISION_SET_EXTERNAL_SHA256: Final[str] = (
    "ef0db0f1fc9ebd7800d94ad1f53a496115e1aaa5d7d3f1c62bd15fe9f30a6b02"
)
_SOURCE_ROLE_SHA256S: Final[tuple[tuple[str, str], ...]] = (
    ("terms", "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"),
    ("brochure", "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"),
    ("rate_table", "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"),
)
_TASK_KEYS: Final[tuple[str, ...]] = (
    "terms-01",
    "terms-02",
    "terms-03",
    "terms-04",
    "terms-05",
    "brochure-01",
    "rate_table-01",
    "multi-source-01",
)


class _ModelTransport(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _domain_hash(domain: str, payload: dict[str, object]) -> str:
    return _sha256(domain.encode("ascii") + b"\0" + _canonical_bytes(payload))


def _require_execution_identity(
    *,
    experiment_id: str,
    execution_identity_sha256: str,
    run_id: str,
    attempt_id: str,
    receipt_id: str,
    integration_head: str,
    integration_tree: str,
    revision_set_sha256: str,
    request_identity_manifest_sha256: str,
) -> None:
    values = (experiment_id, run_id, attempt_id, receipt_id)
    try:
        valid_uuids = all(
            type(value) is str and str(uuid.UUID(value)) == value and uuid.UUID(value).version == 4
            for value in values
        )
    except (AttributeError, TypeError, ValueError):
        valid_uuids = False
    expected = canonical_hash(
        _EXECUTION_IDENTITY_DOMAIN,
        {
            "experiment_id": experiment_id,
            "run_id": run_id,
            "attempt_id": attempt_id,
            "receipt_id": receipt_id,
            "integration_head": integration_head,
            "integration_tree": integration_tree,
            "revision_set_sha256": revision_set_sha256,
            "request_identity_manifest_sha256": request_identity_manifest_sha256,
            "model_execution_identity_sha256": deepseek.DEEPSEEK_EXECUTION_IDENTITY_SHA256,
        },
    )
    if (
        not valid_uuids
        or len(set(values)) != 4
        or re.fullmatch(r"[0-9a-f]{40}", integration_head) is None
        or re.fullmatch(r"[0-9a-f]{40}", integration_tree) is None
        or execution_identity_sha256 != expected
    ):
        raise EC01FormalCandidateRunError("EXECUTION_IDENTITY_INVALID")


def _require_execution_identity_shape(
    *,
    experiment_id: str,
    execution_identity_sha256: str,
    run_id: str,
    attempt_id: str,
    receipt_id: str,
    integration_head: str,
    integration_tree: str,
) -> None:
    values = (experiment_id, run_id, attempt_id, receipt_id)
    try:
        valid_uuids = all(
            type(value) is str and str(uuid.UUID(value)) == value and uuid.UUID(value).version == 4
            for value in values
        )
    except (AttributeError, TypeError, ValueError):
        valid_uuids = False
    if (
        not valid_uuids
        or len(set(values)) != 4
        or re.fullmatch(r"[0-9a-f]{64}", execution_identity_sha256) is None
        or re.fullmatch(r"[0-9a-f]{40}", integration_head) is None
        or re.fullmatch(r"[0-9a-f]{40}", integration_tree) is None
    ):
        raise EC01FormalCandidateRunError("EXECUTION_IDENTITY_INVALID")


@dataclass(frozen=True, slots=True)
class EC01RawResponse815V1:
    ordinal: int
    task_key: str
    response_bytes: bytes
    byte_size: int
    response_sha256: str


@dataclass(frozen=True, slots=True)
class EC01FormalCandidateTerminal815V1:
    contract: Literal["ec01-formal-candidate-terminal.815.v1"]
    status: Literal["SUCCEEDED", "FAILED"]
    failure_reason: str | None
    raw_count: int
    attempted_field_count: int
    provider_visible_field_count: int
    real_model_output_count: int
    code_deferred_field_count: int
    dispositioned_field_count: int
    experiment_id: str
    execution_identity_sha256: str
    run_id: str
    attempt_id: str
    receipt_id: str
    integration_head: str
    integration_tree: str
    model_execution_identity_sha256: str
    revision_set_sha256: str
    schema_rows_sha256: str
    request_manifest_sha256: str
    raw_index_sha256: str
    batch_receipt_sha256: str | None
    coordinate_evidence_companion_sha256: str | None
    terminal_sha256: str

    def rehash_with_raw(
        self,
        raw_responses: tuple[EC01RawResponse815V1, ...],
        repair_raw_responses: tuple[EC01RawResponse815V1, ...] = (),
    ) -> EC01FormalCandidateTerminal815V1:
        raw_count = len(raw_responses) + len(repair_raw_responses)
        raw_index_sha256 = _raw_index_sha256(
            raw_responses,
            repair_raw_responses,
        )
        unsigned = _terminal_payload(
            status=self.status,
            failure_reason=self.failure_reason,
            raw_count=raw_count,
            attempted_field_count=self.attempted_field_count,
            provider_visible_field_count=self.provider_visible_field_count,
            real_model_output_count=self.real_model_output_count,
            code_deferred_field_count=self.code_deferred_field_count,
            dispositioned_field_count=self.dispositioned_field_count,
            experiment_id=self.experiment_id,
            execution_identity_sha256=self.execution_identity_sha256,
            run_id=self.run_id,
            attempt_id=self.attempt_id,
            receipt_id=self.receipt_id,
            integration_head=self.integration_head,
            integration_tree=self.integration_tree,
            model_execution_identity_sha256=self.model_execution_identity_sha256,
            revision_set_sha256=self.revision_set_sha256,
            schema_rows_sha256=self.schema_rows_sha256,
            request_manifest_sha256=self.request_manifest_sha256,
            raw_index_sha256=raw_index_sha256,
            batch_receipt_sha256=self.batch_receipt_sha256,
            coordinate_evidence_companion_sha256=(
                self.coordinate_evidence_companion_sha256
            ),
        )
        return replace(
            self,
            raw_count=raw_count,
            raw_index_sha256=raw_index_sha256,
            terminal_sha256=_domain_hash(_TERMINAL_CONTRACT, unsigned),
        )


@dataclass(frozen=True, slots=True)
class EC01FormalCandidateRun815V1:
    contract: Literal["ec01-formal-candidate-run.815.v1"]
    revision_validation_sha256: str
    schema_rows_sha256: str
    experiment_id: str
    execution_identity_sha256: str
    run_id: str
    attempt_id: str
    receipt_id: str
    integration_head: str
    integration_tree: str
    request_manifest_sha256: str
    request_manifest_bytes: bytes
    raw_responses: tuple[EC01RawResponse815V1, ...]
    repair_raw_responses: tuple[EC01RawResponse815V1, ...]
    terminal: EC01FormalCandidateTerminal815V1
    candidate_kind: Literal["FORMAL"]
    candidate: Schema67CandidateV2
    coordinate_evidence_companion: CoordinateEvidenceCompanion815V1
    derivation_sha256: str

    def recomputed_derivation_sha256(self) -> str:
        return _domain_hash(
            _DERIVATION_DOMAIN,
            {
                "revision_validation_sha256": self.revision_validation_sha256,
                "schema_rows_sha256": self.schema_rows_sha256,
                "experiment_id": self.experiment_id,
                "execution_identity_sha256": self.execution_identity_sha256,
                "run_id": self.run_id,
                "attempt_id": self.attempt_id,
                "receipt_id": self.receipt_id,
                "integration_head": self.integration_head,
                "integration_tree": self.integration_tree,
                "model_execution_identity_sha256": deepseek.DEEPSEEK_EXECUTION_IDENTITY_SHA256,
                "request_manifest_sha256": self.request_manifest_sha256,
                "raw_index_sha256": _raw_index_sha256(
                    self.raw_responses,
                    self.repair_raw_responses,
                ),
                "repair_raw_index_sha256": _raw_index_sha256(
                    (),
                    self.repair_raw_responses,
                ),
                "terminal_sha256": self.terminal.terminal_sha256,
                "candidate_kind": self.candidate_kind,
                "candidate_sha256": self.candidate.candidate_sha256,
                "coordinate_evidence_companion_sha256": (
                    self.coordinate_evidence_companion.companion_sha256
                ),
            },
        )


class EC01FormalCandidateRunError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        *,
        terminal: EC01FormalCandidateTerminal815V1 | None = None,
        raw_responses: tuple[EC01RawResponse815V1, ...] = (),
        repair_raw_responses: tuple[EC01RawResponse815V1, ...] = (),
    ) -> None:
        self.reason_code = reason_code
        self.terminal = terminal
        self.raw_responses = raw_responses
        self.repair_raw_responses = repair_raw_responses
        self.candidate = None
        super().__init__(reason_code)


def _raw_index_sha256(
    raw_responses: tuple[EC01RawResponse815V1, ...],
    repair_raw_responses: tuple[EC01RawResponse815V1, ...] = (),
) -> str:
    return _domain_hash(
        _RAW_INDEX_DOMAIN,
        {
            "rows": [
                {
                    "phase": phase,
                    "ordinal": row.ordinal,
                    "task_key": row.task_key,
                    "byte_size": row.byte_size,
                    "response_sha256": row.response_sha256,
                }
                for phase, rows in (
                    ("INITIAL", raw_responses),
                    ("TARGETED", repair_raw_responses),
                )
                for row in rows
            ]
        },
    )


def _require_targeted_repair_validation(
    *,
    batch_execution: deepseek.Schema67BatchExecutionV1,
    repair_raw_responses: Sequence[EC01RawResponse815V1],
) -> None:
    _require_repair_raw_rows(tuple(repair_raw_responses))
    final_output_by_field = {
        output.field_id: output
        for execution in batch_execution.executions
        for output in execution.final_outputs
    }
    for execution in batch_execution.executions:
        if execution.evidence_repair is None:
            continue
        for result in execution.evidence_repair.verifier_resolution.results:
            if result.status == "PASS":
                continue
            output = final_output_by_field.get(result.field_id)
            if (
                result.reason_codes
                and output is not None
                and output.state == "unknown"
                and output.value_snapshot is None
                and output.evidence == ()
            ):
                continue
            raise EC01FormalCandidateRunError(
                "TARGETED_REPAIR_VALIDATION_FAILED"
            )


def _terminal_payload(
    *,
    status: Literal["SUCCEEDED", "FAILED"],
    failure_reason: str | None,
    raw_count: int,
    attempted_field_count: int,
    provider_visible_field_count: int,
    real_model_output_count: int,
    code_deferred_field_count: int,
    dispositioned_field_count: int,
    experiment_id: str,
    execution_identity_sha256: str,
    run_id: str,
    attempt_id: str,
    receipt_id: str,
    integration_head: str,
    integration_tree: str,
    model_execution_identity_sha256: str,
    revision_set_sha256: str,
    schema_rows_sha256: str,
    request_manifest_sha256: str,
    raw_index_sha256: str,
    batch_receipt_sha256: str | None,
    coordinate_evidence_companion_sha256: str | None,
) -> dict[str, object]:
    return {
        "contract": _TERMINAL_CONTRACT,
        "status": status,
        "failure_reason": failure_reason,
        "raw_count": raw_count,
        "attempted_field_count": attempted_field_count,
        "provider_visible_field_count": provider_visible_field_count,
        "real_model_output_count": real_model_output_count,
        "code_deferred_field_count": code_deferred_field_count,
        "dispositioned_field_count": dispositioned_field_count,
        "experiment_id": experiment_id,
        "execution_identity_sha256": execution_identity_sha256,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "receipt_id": receipt_id,
        "integration_head": integration_head,
        "integration_tree": integration_tree,
        "model_execution_identity_sha256": model_execution_identity_sha256,
        "revision_set_sha256": revision_set_sha256,
        "schema_rows_sha256": schema_rows_sha256,
        "request_manifest_sha256": request_manifest_sha256,
        "raw_index_sha256": raw_index_sha256,
        "batch_receipt_sha256": batch_receipt_sha256,
        "coordinate_evidence_companion_sha256": (
            coordinate_evidence_companion_sha256
        ),
    }


def _make_terminal(
    *,
    status: Literal["SUCCEEDED", "FAILED"],
    failure_reason: str | None,
    raw_responses: tuple[EC01RawResponse815V1, ...],
    repair_raw_responses: tuple[EC01RawResponse815V1, ...],
    attempted_field_count: int,
    provider_visible_field_count: int,
    real_model_output_count: int,
    code_deferred_field_count: int,
    dispositioned_field_count: int,
    experiment_id: str,
    execution_identity_sha256: str,
    run_id: str,
    attempt_id: str,
    receipt_id: str,
    integration_head: str,
    integration_tree: str,
    revision_set_sha256: str,
    schema_rows_sha256: str,
    request_manifest_sha256: str,
    batch_receipt_sha256: str | None,
    coordinate_evidence_companion_sha256: str | None,
) -> EC01FormalCandidateTerminal815V1:
    raw_count = len(raw_responses) + len(repair_raw_responses)
    raw_index_sha256 = _raw_index_sha256(
        raw_responses,
        repair_raw_responses,
    )
    payload = _terminal_payload(
        status=status,
        failure_reason=failure_reason,
        raw_count=raw_count,
        attempted_field_count=attempted_field_count,
        provider_visible_field_count=provider_visible_field_count,
        real_model_output_count=real_model_output_count,
        code_deferred_field_count=code_deferred_field_count,
        dispositioned_field_count=dispositioned_field_count,
        experiment_id=experiment_id,
        execution_identity_sha256=execution_identity_sha256,
        run_id=run_id,
        attempt_id=attempt_id,
        receipt_id=receipt_id,
        integration_head=integration_head,
        integration_tree=integration_tree,
        model_execution_identity_sha256=deepseek.DEEPSEEK_EXECUTION_IDENTITY_SHA256,
        revision_set_sha256=revision_set_sha256,
        schema_rows_sha256=schema_rows_sha256,
        request_manifest_sha256=request_manifest_sha256,
        raw_index_sha256=raw_index_sha256,
        batch_receipt_sha256=batch_receipt_sha256,
        coordinate_evidence_companion_sha256=(
            coordinate_evidence_companion_sha256
        ),
    )
    return EC01FormalCandidateTerminal815V1(
        contract=_TERMINAL_CONTRACT,
        status=status,
        failure_reason=failure_reason,
        raw_count=raw_count,
        attempted_field_count=attempted_field_count,
        provider_visible_field_count=provider_visible_field_count,
        real_model_output_count=real_model_output_count,
        code_deferred_field_count=code_deferred_field_count,
        dispositioned_field_count=dispositioned_field_count,
        experiment_id=experiment_id,
        execution_identity_sha256=execution_identity_sha256,
        run_id=run_id,
        attempt_id=attempt_id,
        receipt_id=receipt_id,
        integration_head=integration_head,
        integration_tree=integration_tree,
        model_execution_identity_sha256=deepseek.DEEPSEEK_EXECUTION_IDENTITY_SHA256,
        revision_set_sha256=revision_set_sha256,
        schema_rows_sha256=schema_rows_sha256,
        request_manifest_sha256=request_manifest_sha256,
        raw_index_sha256=raw_index_sha256,
        batch_receipt_sha256=batch_receipt_sha256,
        coordinate_evidence_companion_sha256=(
            coordinate_evidence_companion_sha256
        ),
        terminal_sha256=_domain_hash(_TERMINAL_CONTRACT, payload),
    )


def _require_request_manifest(
    value: object,
    *,
    revision_set_validation: RevisionSetValidation815V1,
    schema_rows_sha256: str,
    integration_head: str,
    integration_tree: str,
) -> tuple[dict[str, object], str]:
    if type(value) is not bytes:
        raise EC01FormalCandidateRunError("REQUEST_MANIFEST_INVALID")
    try:
        if (
            revision_set_validation.revision_set_sha256 != _REVISION_SET_SHA256
            or revision_set_validation.revision_set_external_sha256 != _REVISION_SET_EXTERNAL_SHA256
            or tuple((row.role, row.file_sha256) for row in revision_set_validation.rows)
            != _SOURCE_ROLE_SHA256S
        ):
            raise ValueError
        manifest = json.loads(value)
        if type(manifest) is not dict or value != _canonical_bytes(manifest) + b"\n":
            raise TypeError
        unsigned = dict(manifest)
        observed_selfhash = unsigned.pop("manifest_sha256", None)
        if observed_selfhash != _domain_hash(_REQUEST_MANIFEST_DOMAIN, unsigned):
            raise ValueError
        required_keys = {
            "compiler",
            "contract",
            "disposition_counts",
            "effects",
            "formation_policy_projection_sha256",
            "manifest_sha256",
            "model",
            "ordered_task_keys",
            "revision_set",
            "schema_rows_sha256",
            "selection_catalog_sha256",
            "source_projection_sha256s",
            "tasks",
        }
        if set(manifest) != required_keys or manifest["contract"] != (
            _REQUEST_MANIFEST_DOMAIN
        ):
            raise TypeError
        compiler = manifest["compiler"]
        revision = manifest["revision_set"]
        model = manifest["model"]
        effects = manifest["effects"]
        tasks = manifest["tasks"]
        ordered_task_keys = manifest["ordered_task_keys"]
        counts = manifest["disposition_counts"]
        if (
            type(compiler) is not dict
            or compiler.get("head") != integration_head
            or compiler.get("tree") != integration_tree
            or type(revision) is not dict
            or revision.get("revision_set_sha256") != revision_set_validation.revision_set_sha256
            or revision.get("external_sha256")
            != revision_set_validation.revision_set_external_sha256
            or manifest.get("schema_rows_sha256") != schema_rows_sha256
            or type(model) is not dict
            or model.get("provider") != deepseek.DEEPSEEK_PROVIDER
            or model.get("protocol") != deepseek.DEEPSEEK_PROTOCOL
            or model.get("base_url") != deepseek.DEEPSEEK_BASE_URL
            or model.get("model") != deepseek.DEEPSEEK_MODEL
            or model.get("temperature") != deepseek.DEEPSEEK_TEMPERATURE
            or model.get("max_tokens") != deepseek.DEEPSEEK_MAX_TOKENS
            or model.get("thinking") != deepseek.DEEPSEEK_THINKING
            or model.get("response_format") != deepseek.DEEPSEEK_RESPONSE_FORMAT
            or model.get("execution_identity_sha256") != deepseek.DEEPSEEK_EXECUTION_IDENTITY_SHA256
            or type(effects) is not dict
            or any(value != 0 for value in effects.values())
            or type(ordered_task_keys) is not list
            or tuple(ordered_task_keys) != _TASK_KEYS
            or type(tasks) is not list
            or len(tasks) != 8
            or type(counts) is not dict
            or set(counts)
            != {
                "code_deferred_field_count",
                "dispositioned_field_count",
                "provider_visible_field_count",
                "real_model_output_count",
            }
            or tuple(row.get("task_key") for row in tasks if type(row) is dict) != _TASK_KEYS
        ):
            raise ValueError
        for ordinal, row in enumerate(tasks, start=1):
            if (
                type(row) is not dict
                or set(row)
                != {
                    "canonical_request",
                    "field_ids",
                    "field_selection_catalog_sha256s",
                    "ordinal",
                    "parse_manifest_sha256s",
                    "provider_visible_field_ids",
                    "response_task_key_required",
                    "selection_catalog_sha256",
                    "source_projection_sha256s",
                    "system",
                    "task_key",
                    "user",
                }
                or row.get("ordinal") != ordinal
                or row.get("response_task_key_required") is not True
                or type(row.get("field_ids")) is not list
                or type(row.get("system")) is not dict
                or type(row.get("user")) is not dict
                or type(row.get("canonical_request")) is not dict
            ):
                raise TypeError
        return manifest, cast(str, observed_selfhash)
    except EC01FormalCandidateRunError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise EC01FormalCandidateRunError("REQUEST_MANIFEST_INVALID") from None


@dataclass(frozen=True, slots=True)
class _C1Source:
    role: str
    item: dict[str, object]
    pdf_bytes: bytes


@dataclass(frozen=True, slots=True)
class _C1PreparedInputs:
    revision_validation: RevisionSetValidation815V1
    role_inputs: tuple[Schema67RoleTaskInputV1, ...]
    admitted_sources: tuple[AdmittedParseArtifactV1, ...]
    locators_by_task: tuple[tuple[CanonicalLocatorInputV1, ...], ...]
    source_projections: tuple[NativePdfSelectionProjection815V1, ...]
    execution_projection: deepseek.Schema67NativePdfExecutionProjection815V1
    selection_catalog: Schema67SelectionCatalog815V1


def _exact_read_file(path: Path) -> bytes:
    before = os.lstat(path)
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_uid != os.geteuid()
        or before.st_nlink != 1
    ):
        raise EC01FormalCandidateRunError("REVISION_SET_VALIDATION_INVALID")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_uid) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_uid,
        ):
            raise EC01FormalCandidateRunError("REVISION_SET_VALIDATION_INVALID")
        chunks: list[bytes] = []
        while block := os.read(descriptor, 1024 * 1024):
            chunks.append(block)
        after = os.fstat(descriptor)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        ):
            raise EC01FormalCandidateRunError("REVISION_SET_VALIDATION_INVALID")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _load_c1_sources(
    revision_set_root: Path,
) -> tuple[RevisionSetValidation815V1, tuple[_C1Source, ...]]:
    if not isinstance(revision_set_root, Path) or not revision_set_root.is_absolute():
        raise EC01FormalCandidateRunError("REVISION_SET_VALIDATION_INVALID")
    root_stat = os.lstat(revision_set_root)
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or stat.S_IMODE(root_stat.st_mode) != 0o700
        or root_stat.st_uid != os.geteuid()
    ):
        raise EC01FormalCandidateRunError("REVISION_SET_VALIDATION_INVALID")
    validation = validate_revision_set_manifest_815(revision_set_root / "revision-set.json")
    require_revision_set_validation_value_815(validation)
    if validation.revision_set_sha256 != _REVISION_SET_SHA256:
        raise EC01FormalCandidateRunError("REVISION_SET_VALIDATION_INVALID")
    revision_bytes = _exact_read_file(revision_set_root / "revision-set.json")
    revision = json.loads(revision_bytes.decode("utf-8"))
    if type(revision) is not dict or revision_bytes != _canonical_bytes(revision) + b"\n":
        raise EC01FormalCandidateRunError("REVISION_SET_VALIDATION_INVALID")
    sources: list[_C1Source] = []
    rows = cast(list[object], revision.get("items"))
    for expected_role, summary in zip(("terms", "brochure", "rate_table"), rows, strict=True):
        if type(summary) is not dict or summary.get("role") != expected_role:
            raise EC01FormalCandidateRunError("REVISION_SET_VALIDATION_INVALID")
        manifest_name = summary.get("manifest_file")
        material_name = summary.get("material_file")
        if type(manifest_name) is not str or type(material_name) is not str:
            raise EC01FormalCandidateRunError("REVISION_SET_VALIDATION_INVALID")
        manifest_bytes = _exact_read_file(revision_set_root / manifest_name)
        item = json.loads(manifest_bytes.decode("utf-8"))
        pdf_bytes = _exact_read_file(revision_set_root / material_name)
        if (
            type(item) is not dict
            or manifest_bytes != _canonical_bytes(item) + b"\n"
            or _sha256(manifest_bytes) != summary.get("manifest_file_sha256")
            or _sha256(pdf_bytes) != item.get("file_sha256")
            or len(pdf_bytes) != item.get("file_size")
        ):
            raise EC01FormalCandidateRunError("REVISION_SET_VALIDATION_INVALID")
        sources.append(_C1Source(expected_role, cast(dict[str, object], item), pdf_bytes))
    return validation, tuple(sources)


def _task_profile(
    *, role: str, item: dict[str, object], field_ids: tuple[str, ...]
) -> ExtractionTaskProfileV1:
    profile_id = f"596-1-{role}-v1"
    parse_policy = ApprovedParsePolicy(
        policy_id=f"596-1-{role}-approved-parse-policy",
        policy_version="v1",
        material_profile_id=profile_id,
        default_parser_profile_ref="approved-parser-profile:parser-neutral-default.v1",
        bounded_upgrade_profile_ref="approved-parser-profile:parser-neutral-bounded.v1",
        upgrade_trigger_conditions=("required_capability_missing",),
        max_parser_attempts=2,
        privacy_policy_ref="privacy-policy:private.v1",
        output_policy_ref="output-policy:internal.v1",
    )
    material = MaterialProfile(
        profile_id=profile_id,
        material_role=cast(Any, role),
        source=SourceDocumentIdentity(
            name=cast(str, item["material_file"]),
            path=f"revision-set/{item['material_file']}",
            size=cast(int, item["file_size"]),
            sha256=cast(str, item["file_sha256"]),
        ),
        document_type_id=f"596-1-{role}",
        required_parse_capabilities=("ordered_pages",),
        parse_policy=parse_policy,
    )
    receipt = ParsePolicyReceipt.model_validate(
        {
            **parse_policy.model_dump(mode="python"),
            "required_parse_capabilities": material.required_parse_capabilities,
        }
    )
    binding_hash = canonical_hash(
        "weknora.ec.material-profile-binding.v1",
        {
            "role": role,
            "file_sha256": item["file_sha256"],
            "manifest_self_sha256": item["manifest_self_sha256"],
        },
    )
    return build_extraction_task_profile(
        material_profile=material,
        material_profile_binding_hash=binding_hash,
        parse_policy_receipt=receipt,
        field_authority=FieldAuthority(
            authority_class=(
                "contract_fact"
                if role == "terms"
                else "brochure_fact"
                if role == "brochure"
                else "rate_numeric"
            ),
            primary_role=cast(Any, role),
            support_roles=(),
            field_ids=field_ids,
        ),
        attempt_budget=AttemptBudgetV1(
            max_fields=len(field_ids), max_total_attempts=2, max_targeted_repairs=1
        ),
    )


def _parsed_source(
    source: _C1Source, task_profile: Any
) -> tuple[
    AdmittedParseArtifactV1,
    NativePdfSelectionProjection815V1,
    tuple[CanonicalLocatorInputV1, ...],
]:
    item = source.item
    projection = extract_native_pdf_selection_projection_815(
        source.pdf_bytes,
        expected_source_sha256=cast(str, item["file_sha256"]),
        source_revision_id=cast(str, item["compiler_source_revision_id"]),
        source_role=cast(Any, source.role),
    )
    locators: list[CanonicalLocatorInputV1] = []
    pages: list[ParsePageV1] = []
    blocks: list[ParseBlockV1] = []
    cells: list[ParseCellV1] = []
    tables: list[ParseTableV1] = []
    for page in projection.pages:
        page_id = f"{source.role}-page-{page.page_number:04d}"
        if (
            not page.canonical_page_text
            or page.page_text_sha256
            != _sha256(page.canonical_page_text.encode("utf-8"))
        ):
            raise EC01FormalCandidateRunError("REVISION_SET_VALIDATION_INVALID")
        pages.append(
            ParsePageV1(
                page_id=page_id,
                order_index=len(pages),
                locator=PageLocatorV1(page_number=page.page_number),
                content_hash=page.page_text_sha256,
                structure_hash=canonical_hash(
                    "weknora.ec.native-page-structure.815.v1",
                    {
                        "role": source.role,
                        "page_number": page.page_number,
                        "page_width_points": page.page_width_points,
                        "page_height_points": page.page_height_points,
                        "word_ids": tuple(item.word_id for item in page.words),
                        "span_ids": tuple(item.span_id for item in page.spans),
                    },
                ),
            )
        )
        for block_index, span in enumerate(page.spans):
            bbox = tuple(Decimal(item) for item in span.rects[0])
            blocks.append(
                ParseBlockV1(
                    block_id=span.parent_block_id,
                    order_index=len(blocks),
                    locator=BlockLocatorV1(
                        page_number=page.page_number,
                        block_index=block_index,
                        bbox=cast(Any, bbox),
                    ),
                    content_hash=span.text_sha256,
                    structure_hash=canonical_hash(
                        "weknora.ec.native-text-block.815.v1",
                        {
                            "span_id": span.span_id,
                            "char_start": span.char_start,
                            "char_end": span.char_end,
                            "rects": span.rects,
                        },
                    ),
                )
            )
            locators.append(
                CanonicalLocatorInputV1(
                    locator_ref=span.parent_block_id,
                    locator_kind="block",
                    page_number=page.page_number,
                    parent_refs=(page_id,),
                    content_snapshot=span.exact_text,
                    content_snapshot_sha256=span.text_sha256,
                )
            )
        cells_by_table: dict[str, list[ParseCellV1]] = {}
        for projected_cell in page.cells:
            parsed_cell = ParseCellV1(
                cell_id=projected_cell.cell_id,
                order_index=len(cells),
                table_id=projected_cell.table_id,
                locator=CellLocatorV1(
                    page_number=projected_cell.page_number,
                    bbox=cast(
                        Any,
                        tuple(Decimal(item) for item in projected_cell.bbox),
                    ),
                    table_id=projected_cell.table_id,
                    row_index=projected_cell.row_index,
                    column_index=projected_cell.column_index,
                    row_span=1,
                    column_span=1,
                ),
                content_hash=projected_cell.text_sha256,
                structure_hash=canonical_hash(
                    "weknora.ec.native-table-cell.815.v1",
                    {
                        "cell_id": projected_cell.cell_id,
                        "bbox": projected_cell.bbox,
                    },
                ),
            )
            cells.append(parsed_cell)
            cells_by_table.setdefault(parsed_cell.table_id, []).append(parsed_cell)
            if (
                projected_cell.exact_text
                and "\n" not in projected_cell.exact_text
                and "\r" not in projected_cell.exact_text
            ):
                locators.append(
                    CanonicalLocatorInputV1(
                        locator_ref=projected_cell.cell_id,
                        locator_kind="cell",
                        page_number=projected_cell.page_number,
                        parent_refs=(page_id, projected_cell.table_id),
                        content_snapshot=projected_cell.exact_text,
                        content_snapshot_sha256=projected_cell.text_sha256,
                    )
                )
        for table_index, (table_id, table_cells) in enumerate(cells_by_table.items()):
            left = min(item.locator.bbox[0] for item in table_cells)
            top = min(item.locator.bbox[1] for item in table_cells)
            right = max(item.locator.bbox[2] for item in table_cells)
            bottom = max(item.locator.bbox[3] for item in table_cells)
            tables.append(
                ParseTableV1(
                    table_id=table_id,
                    order_index=len(tables),
                    locator=TableLocatorV1(
                        page_number=page.page_number,
                        table_index=table_index,
                        bbox=(left, top, right, bottom),
                    ),
                    content_hash=canonical_hash(
                        "weknora.ec.native-table-content.815.v1",
                        {
                            "cell_content_hashes": tuple(
                                item.content_hash for item in table_cells
                            )
                        },
                    ),
                    structure_hash=canonical_hash(
                        "weknora.ec.native-table-structure.815.v1",
                        {"cell_ids": tuple(item.cell_id for item in table_cells)},
                    ),
                    row_count=max(item.locator.row_index for item in table_cells) + 1,
                    column_count=max(item.locator.column_index for item in table_cells) + 1,
                    header_cell_ids=tuple(
                        item.cell_id
                        for item in table_cells
                        if item.locator.row_index == 0
                    ),
                    continuation_table_ids=(),
                )
            )
    attempt_number = cast(int, item["weknora_parse_attempt"])
    subject = ParseSubjectV1(
        space_id=cast(str, item["knowledge_base_id"]),
        source_id=cast(str, item["knowledge_id"]),
        source_revision_id=cast(str, item["compiler_source_revision_id"]),
        product_version_id="596-1",
        material_profile_id=task_profile.material_profile.profile_id,
        material_profile_binding_hash=task_profile.material_profile_binding_hash,
        source_sha256=cast(str, item["file_sha256"]),
        raw_artifact_hash=cast(str, item["file_sha256"]),
        canonical_envelope_hash=canonical_hash(
            "weknora.ec.source-envelope.815.v1",
            {
                "manifest_self_sha256": item["manifest_self_sha256"],
                "compiler_source_revision_id": item["compiler_source_revision_id"],
            },
        ),
    )
    parser = ParserIdentityV1(
        parser_id="pdfplumber-native-position-815",
        parser_profile_ref=(
            task_profile.parse_policy_receipt.default_parser_profile_ref
            if attempt_number == 1
            else task_profile.parse_policy_receipt.bounded_upgrade_profile_ref
        ),
        parser_build_id=projection.adapter_version,
        parser_config_hash=canonical_hash(
            "weknora.ec.pdfplumber-native-position-config.815.v1",
            {
                "adapter_version": projection.adapter_version,
                "coordinate_space": projection.coordinate_space,
                "parse_manifest_sha256": projection.parse_manifest_sha256,
            },
        ),
    )
    attempt = ParseAttemptV1(
        attempt_id=f"ec01-{source.role}-parse-attempt-{attempt_number}",
        attempt_number=cast(Any, attempt_number),
        attempt_role="default" if attempt_number == 1 else "bounded_upgrade",
        generation=0,
    )
    snapshot = ParseSnapshotV1(
        snapshot_id=f"ec01-{source.role}-snapshot-0",
        snapshot_generation=0,
        pagination_complete=True,
        concurrent_mutation_fence_hash=cast(str, item["manifest_self_sha256"]),
    )
    output = ParseOutputFactsV1(
        privacy_policy_ref=task_profile.parse_policy_receipt.privacy_policy_ref,
        output_policy_ref=task_profile.parse_policy_receipt.output_policy_ref,
        body_text_included=True,
        secrets_included=False,
        absolute_paths_included=False,
        unknown_vendor_fields_included=False,
    )
    capability_rows: list[CapabilityEvidenceV1] = [
        CapabilityEvidenceV1(
            capability="ordered_pages", subject_refs=tuple(page.page_id for page in pages)
        ),
    ]
    if blocks:
        capability_rows.append(
            CapabilityEvidenceV1(
                capability="block_locators",
                subject_refs=tuple(item.block_id for item in blocks),
            )
        )
    if tables:
        capability_rows.append(
            CapabilityEvidenceV1(
                capability="table_grid",
                subject_refs=(
                    *(item.table_id for item in tables),
                    *(item.cell_id for item in cells),
                ),
            )
        )
    evidence = tuple(capability_rows)
    document = ParsedDocumentV1(
        contract="parsed-document.v1",
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output,
        pages=tuple(pages),
        blocks=tuple(blocks),
        tables=tuple(tables),
        cells=tuple(cells),
        capability_evidence=evidence,
        warnings=(),
        unsupported=(),
    )
    manifest = build_parse_manifest(document, task_profile.material_profile)
    decision = ParseQualityDecisionV1(
        contract="parse-quality-decision.v1",
        subject=subject,
        manifest_hash=manifest.manifest_hash,
        parse_policy_receipt=task_profile.parse_policy_receipt,
        measured_facts=ParseQualityMeasuredFactsV1(
            threshold_version="parse-quality-structural.v1",
            required_capabilities=manifest.required_capabilities,
            satisfied_capabilities=manifest.satisfied_capabilities,
            unsatisfied_capabilities=(),
            trigger_conditions=(),
            attempts_exhausted=attempt_number >= 2,
        ),
        decision="ADMIT",
        reason_codes=(),
        admitted_attempt_id=attempt.attempt_id,
        next_parser_profile_ref=None,
        review_item=None,
    )
    admitted = AdmittedParseArtifactV1(
        role=cast(Any, source.role),
        source_sha256=cast(str, item["file_sha256"]),
        artifact_sha256=document.document_hash,
        document=document,
        manifest=manifest,
        decision=decision,
        manifest_sha256=manifest.manifest_hash,
        decision_sha256=decision.decision_hash,
    )
    return (
        admitted,
        projection,
        tuple(locators),
    )


def _prepare_c1_inputs(
    *,
    revision_set_root: Path,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
) -> _C1PreparedInputs:
    validation, sources = _load_c1_sources(revision_set_root)
    available_roles = cast(
        tuple[MaterialRole, ...],
        tuple(source.role for source in sources),
    )
    execution_projection = deepseek.build_schema67_native_pdf_execution_projection_815(
        field_contracts=field_contracts,
        base_execution_plan=deepseek.build_schema67_execution_plan(field_contracts),
        available_source_roles=available_roles,
    )
    if execution_plan != execution_projection.execution_plan:
        raise EC01FormalCandidateRunError("EXECUTION_PLAN_INVALID")
    contract_by_id = {item.field_id: item for item in field_contracts.contracts}
    item_by_role = {source.role: source.item for source in sources}
    field_ids_by_role = {
        role: tuple(
            sorted(
                field_id
                for task_slice in execution_plan.task_slices
                for field_id in task_slice.field_ids
                if role in contract_by_id[field_id].source_roles
            )
        )
        for role in ("terms", "brochure", "rate_table")
    }
    base_profiles = {
        role: _task_profile(role=role, item=item_by_role[role], field_ids=field_ids_by_role[role])
        for role in ("terms", "brochure", "rate_table")
    }
    parsed = {source.role: _parsed_source(source, base_profiles[source.role]) for source in sources}
    admitted_by_role = {role: value[0] for role, value in parsed.items()}
    projection_by_role = {role: value[1] for role, value in parsed.items()}
    locators_by_role = {role: value[2] for role, value in parsed.items()}
    source_projections = tuple(
        projection_by_role[role] for role in ("terms", "brochure", "rate_table")
    )
    selection_catalog = build_field_selection_catalogs_815(
        field_contracts=field_contracts,
        provider_visible_field_ids=execution_projection.provider_visible_field_ids,
        available_source_roles=available_roles,
        source_projections=source_projections,
    )
    locator_ref_by_subject: dict[str, str] = {}
    for projection in source_projections:
        for page in projection.pages:
            locator_ref_by_subject.update(
                (span.span_id, span.parent_block_id) for span in page.spans
            )
            locator_ref_by_subject.update(
                (cell.cell_id, cell.cell_id)
                for cell in page.cells
                if cell.exact_text
                and "\n" not in cell.exact_text
                and "\r" not in cell.exact_text
            )
    role_inputs: list[Schema67RoleTaskInputV1] = []
    admission_port = ParsedArtifactAdmissionPort()
    for task_slice in execution_plan.task_slices:
        for role in task_slice.material_roles:
            item = item_by_role[role]
            field_ids = tuple(
                sorted(
                    field_id
                    for field_id in task_slice.field_ids
                    if role in contract_by_id[field_id].source_roles
                )
            )
            profile = _task_profile(role=role, item=item, field_ids=field_ids)
            admitted = admitted_by_role[role]
            refs = admission_port.admitted_input_refs(
                task_profile=profile,
                space_id=cast(str, item["knowledge_base_id"]),
                product_version_id="596-1",
                source_revision_id=cast(str, item["compiler_source_revision_id"]),
                source_revision=ArtifactRefV1(
                    object_type="source-revision.v1",
                    artifact_hash=cast(str, item["compiler_source_revision_id"]),
                ),
                resolved_template=ArtifactRefV1(
                    object_type="resolved-template.v1",
                    artifact_hash=canonical_hash(
                        "weknora.ec.resolved-template.v1",
                        {"role": role, "contract_set_sha256": field_contracts.contract_set_sha256},
                    ),
                ),
                schema_contract=ArtifactRefV1(
                    object_type="schema67-field-contract-set.v1",
                    artifact_hash=field_contracts.contract_set_sha256,
                ),
                document=admitted.document,
                manifest=admitted.manifest,
                quality_decision=admitted.decision,
            )
            selected = tuple(
                (
                    field_id,
                    tuple(
                        sorted(
                            {
                                locator_ref_by_subject[subject_id]
                                for selection in selection_catalog.require_field(
                                    field_id
                                ).selections
                                if selection.source_role == role
                                for subject_id in selection.subject_ids
                                if subject_id in locator_ref_by_subject
                            }
                        )
                    ),
                )
                for field_id in field_ids
            )
            role_inputs.append(
                Schema67RoleTaskInputV1(
                    task_key=task_slice.task_key,
                    material_role=cast(Any, role),
                    space_id=cast(str, item["knowledge_base_id"]),
                    product_version_id="596-1",
                    source_revision_id=cast(str, item["compiler_source_revision_id"]),
                    module_id=f"schema67-{task_slice.task_key}-{role}",
                    risk_partition_id=f"schema67-{task_slice.task_key}-{role}-risk",
                    allowed_locator_refs=selected,
                    input_refs=refs,
                    task_profile=profile,
                )
            )
    exact_role_inputs = tuple(role_inputs)
    prepared = deepseek.prepare_schema67_deepseek_tasks(
        field_contracts=field_contracts,
        execution_plan=execution_plan,
        role_inputs=exact_role_inputs,
    )
    groups: list[tuple[CanonicalLocatorInputV1, ...]] = []
    for task in prepared:
        allowed = {
            ref
            for role_input in exact_role_inputs
            if role_input.task_key == task.task_key
            for _field_id, refs in role_input.allowed_locator_refs
            for ref in refs
        }
        groups.append(
            tuple(
                locator
                for role in task.source_tasks
                for locator in locators_by_role[role.material_role]
                if locator.locator_ref in allowed
            )
        )
    return _C1PreparedInputs(
        revision_validation=validation,
        role_inputs=exact_role_inputs,
        admitted_sources=tuple(
            admitted_by_role[role] for role in ("terms", "brochure", "rate_table")
        ),
        locators_by_task=tuple(groups),
        source_projections=source_projections,
        execution_projection=execution_projection,
        selection_catalog=selection_catalog,
    )


def _require_raw_rows(
    raw_responses: object,
    *,
    expected_count: int,
) -> tuple[EC01RawResponse815V1, ...]:
    if (
        type(expected_count) is not int
        or expected_count < 0
        or expected_count > 8
        or type(raw_responses) is not tuple
        or len(raw_responses) != expected_count
    ):
        raise EC01FormalCandidateRunError("RAW_RESPONSE_INDEX_INVALID")
    for ordinal, row in enumerate(raw_responses, start=1):
        if (
            type(row) is not EC01RawResponse815V1
            or row.ordinal != ordinal
            or row.task_key != _TASK_KEYS[ordinal - 1]
            or type(row.response_bytes) is not bytes
            or row.byte_size != len(row.response_bytes)
            or row.response_sha256 != _sha256(row.response_bytes)
        ):
            raise EC01FormalCandidateRunError("RAW_RESPONSE_INDEX_INVALID")
    return raw_responses


def _require_repair_raw_rows(
    raw_responses: object,
) -> tuple[EC01RawResponse815V1, ...]:
    if type(raw_responses) is not tuple or len(raw_responses) > 8:
        raise EC01FormalCandidateRunError("REPAIR_RAW_RESPONSE_INDEX_INVALID")
    for ordinal, row in enumerate(raw_responses, start=1):
        if (
            type(row) is not EC01RawResponse815V1
            or row.ordinal != ordinal
            or row.task_key != deepseek._SHARED_EVIDENCE_REPAIR_TASK_KEY
            or type(row.response_bytes) is not bytes
            or row.byte_size != len(row.response_bytes)
            or row.response_sha256 != _sha256(row.response_bytes)
        ):
            raise EC01FormalCandidateRunError("REPAIR_RAW_RESPONSE_INDEX_INVALID")
    return raw_responses


def _require_terminal_raw_prefix(
    *,
    terminal: EC01FormalCandidateTerminal815V1,
    raw_responses: tuple[EC01RawResponse815V1, ...],
    repair_raw_responses: tuple[EC01RawResponse815V1, ...],
) -> EC01FormalCandidateTerminal815V1:
    if type(terminal) is not EC01FormalCandidateTerminal815V1:
        raise EC01FormalCandidateRunError("TERMINAL_RAW_PREFIX_INVALID")
    exact_raw = _require_raw_rows(
        raw_responses,
        expected_count=len(raw_responses),
    )
    exact_repair_raw = _require_repair_raw_rows(repair_raw_responses)
    if terminal != terminal.rehash_with_raw(exact_raw, exact_repair_raw):
        raise EC01FormalCandidateRunError("TERMINAL_RAW_PREFIX_INVALID")
    return terminal


class _RecordingTransport:
    def __init__(self, delegate: _ModelTransport, task_rows: Sequence[object]) -> None:
        self._delegate = delegate
        self._task_rows = tuple(task_rows)
        self.raw_responses: list[EC01RawResponse815V1] = []
        self.repair_raw_responses: list[EC01RawResponse815V1] = []
        self._repair_task_indexes: list[int] = []

    async def complete(self, system: str, user: str) -> str:
        try:
            payload = json.loads(user)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise DeepSeekCompilerError("SCHEMA67_TASK_AUTHORITY_INVALID") from None
        is_evidence_repair = payload.get("repair_kind") == "evidence"
        if is_evidence_repair:
            task_key = payload.get("task_key")
            parent_attempts = payload.get("parent_attempts")
            task_indexes = (
                {
                    parent.get("task_index")
                    for parent in parent_attempts
                    if type(parent) is dict
                }
                if type(parent_attempts) is list
                else set()
            )
            if (
                task_key != deepseek._SHARED_EVIDENCE_REPAIR_TASK_KEY
                or len(self.raw_responses) != 8
                or len(self.repair_raw_responses) >= 8
                or len(task_indexes) != 1
            ):
                raise DeepSeekCompilerError("SCHEMA67_TASK_AUTHORITY_INVALID")
            task_index = next(iter(task_indexes))
            if (
                type(task_index) is not int
                or task_index < 0
                or task_index >= 8
                or (
                    self._repair_task_indexes
                    and task_index <= self._repair_task_indexes[-1]
                )
            ):
                raise DeepSeekCompilerError("SCHEMA67_TASK_AUTHORITY_INVALID")
            ordinal = len(self.repair_raw_responses) + 1
            row = self._task_rows[task_index]
        else:
            ordinal = len(self.raw_responses) + 1
            task_index = ordinal - 1
            row = self._task_rows[task_index]
        if ordinal > len(self._task_rows):
            raise DeepSeekCompilerError("SCHEMA67_MVP_EXACT_EIGHT_TASKS_REQUIRED")
        if type(row) is not dict:
            raise DeepSeekCompilerError("SCHEMA67_TASK_AUTHORITY_INVALID")
        system_bytes = system.encode("utf-8")
        user_bytes = user.encode("utf-8")
        request_bytes = deepseek._deepseek_request_bytes(system=system, user=user)
        system_fact = row["system"]
        user_fact = row["user"]
        request_fact = row["canonical_request"]
        if (
            type(system_fact) is not dict
            or type(user_fact) is not dict
            or type(request_fact) is not dict
            or row["ordinal"] != task_index + 1
            or row["task_key"] != _TASK_KEYS[task_index]
            or (
                not is_evidence_repair
                and (
                    system_fact.get("byte_size") != len(system_bytes)
                    or system_fact.get("external_sha256") != _sha256(system_bytes)
                    or user_fact.get("byte_size") != len(user_bytes)
                    or user_fact.get("external_sha256") != _sha256(user_bytes)
                    or request_fact.get("byte_size") != len(request_bytes)
                    or request_fact.get("external_sha256") != _sha256(request_bytes)
                )
            )
        ):
            raise DeepSeekCompilerError("SCHEMA67_TASK_AUTHORITY_INVALID")
        response = await self._delegate.complete(system, user)
        if type(response) is not str:
            raise DeepSeekCompilerError("MODEL_TRANSPORT_FAILED")
        response_bytes = response.encode("utf-8")
        raw = EC01RawResponse815V1(
            ordinal=ordinal,
            task_key=(
                deepseek._SHARED_EVIDENCE_REPAIR_TASK_KEY
                if is_evidence_repair
                else cast(str, row["task_key"])
            ),
            response_bytes=response_bytes,
            byte_size=len(response_bytes),
            response_sha256=_sha256(response_bytes),
        )
        if is_evidence_repair:
            self._repair_task_indexes.append(task_index)
            self.repair_raw_responses.append(raw)
        else:
            self.raw_responses.append(raw)
        return response


class _RequestCaptureTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        payload = json.loads(user)
        native = "field_selection_catalogs" in payload
        response = {
            "task_key": payload["task_key"],
            "fields": [
                (
                    {
                        "field_id": row["field_id"],
                        "state": "unknown",
                        "selection_ids": [],
                        "typed_reason": "ANSWER_NOT_FOUND",
                    }
                    if native
                    else {
                        "field_id": row["field_id"],
                        "state": "unknown",
                        "value_snapshot": None,
                        "evidence": [],
                    }
                )
                for row in (
                    payload["field_selection_catalogs"]
                    if native
                    else payload["field_contracts"]
                )
            ],
        }
        return _canonical_bytes(response).decode("utf-8")


async def _build_request_manifest(
    *,
    prepared_inputs: _C1PreparedInputs,
    profile: ModelProfile,
    policy: ProductionModelPolicy,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
    integration_head: str,
    integration_tree: str,
) -> bytes:
    capture = _RequestCaptureTransport()
    await deepseek._run_schema67_deepseek_batch(
        profile=profile,
        policy=policy,
        transport=capture,
        field_contracts=field_contracts,
        execution_plan=execution_plan,
        role_inputs=prepared_inputs.role_inputs,
        admitted_sources=prepared_inputs.admitted_sources,
        locators_by_task=prepared_inputs.locators_by_task,
        _single_pass_mvp=True,
        _allow_evidence_repair=False,
        _selection_authority=(
            prepared_inputs.selection_catalog,
            prepared_inputs.source_projections,
        ),
    )
    prepared = deepseek.prepare_schema67_deepseek_tasks(
        field_contracts=field_contracts,
        execution_plan=execution_plan,
        role_inputs=prepared_inputs.role_inputs,
    )
    tasks: list[dict[str, object]] = []
    for ordinal, ((system, user), task) in enumerate(
        zip(capture.calls, prepared, strict=True), start=1
    ):
        system_bytes = system.encode("utf-8")
        user_bytes = user.encode("utf-8")
        request_bytes = deepseek._deepseek_request_bytes(system=system, user=user)
        task_catalogs = tuple(
            deepseek._task_native_selection_catalog_815(
                prompt=item,
                catalog=prepared_inputs.selection_catalog.require_field(item.field_id),
            )
            for item in task.field_prompts
        )
        task_roles = tuple(item.material_role for item in task.source_tasks)
        task_projections = tuple(
            item
            for item in prepared_inputs.source_projections
            if item.source_role in task_roles
        )
        tasks.append(
            {
                "canonical_request": {
                    "byte_size": len(request_bytes),
                    "external_sha256": _sha256(request_bytes),
                },
                "field_ids": [item.field_id for item in task.field_prompts],
                "field_selection_catalog_sha256s": [
                    item.catalog_sha256 for item in task_catalogs
                ],
                "ordinal": ordinal,
                "parse_manifest_sha256s": [
                    item.parse_manifest_sha256 for item in task_projections
                ],
                "provider_visible_field_ids": [
                    item.field_id for item in task.field_prompts
                ],
                "response_task_key_required": True,
                "selection_catalog_sha256": prepared_inputs.selection_catalog.catalog_sha256,
                "source_projection_sha256s": [
                    item.parse_manifest_sha256 for item in task_projections
                ],
                "system": {
                    "byte_size": len(system_bytes),
                    "external_sha256": _sha256(system_bytes),
                },
                "task_key": task.task_key,
                "user": {
                    "byte_size": len(user_bytes),
                    "external_sha256": _sha256(user_bytes),
                },
            }
        )
    manifest: dict[str, object] = {
        "compiler": {"head": integration_head, "tree": integration_tree},
        "contract": _REQUEST_MANIFEST_DOMAIN,
        "effects": {
            "candidate_objects_created": 0,
            "client_constructions": 0,
            "credential_reads": 0,
            "execution_identities_created": 0,
            "golden_reads": 0,
            "provider_calls": 0,
            "transport_calls": 0,
        },
        "model": {
            "base_url": deepseek.DEEPSEEK_BASE_URL,
            "execution_identity_sha256": deepseek.DEEPSEEK_EXECUTION_IDENTITY_SHA256,
            "max_tokens": deepseek.DEEPSEEK_MAX_TOKENS,
            "model": deepseek.DEEPSEEK_MODEL,
            "protocol": deepseek.DEEPSEEK_PROTOCOL,
            "provider": deepseek.DEEPSEEK_PROVIDER,
            "response_format": deepseek.DEEPSEEK_RESPONSE_FORMAT,
            "temperature": deepseek.DEEPSEEK_TEMPERATURE,
            "thinking": deepseek.DEEPSEEK_THINKING,
        },
        "ordered_task_keys": list(_TASK_KEYS),
        "disposition_counts": {
            "provider_visible_field_count": len(
                prepared_inputs.execution_projection.provider_visible_field_ids
            ),
            "real_model_output_count": len(
                prepared_inputs.execution_projection.provider_visible_field_ids
            ),
            "code_deferred_field_count": len(
                prepared_inputs.execution_projection.code_deferred
            ),
            "dispositioned_field_count": len(field_contracts.contracts),
        },
        "formation_policy_projection_sha256": (
            prepared_inputs.execution_projection.projection_sha256
        ),
        "revision_set": {
            "external_sha256": prepared_inputs.revision_validation.revision_set_external_sha256,
            "items": [row.to_wire() for row in prepared_inputs.revision_validation.rows],
            "revision_set_sha256": prepared_inputs.revision_validation.revision_set_sha256,
        },
        "schema_rows_sha256": field_contracts.schema_rows_sha256,
        "selection_catalog_sha256": prepared_inputs.selection_catalog.catalog_sha256,
        "source_projection_sha256s": [
            item.parse_manifest_sha256 for item in prepared_inputs.source_projections
        ],
        "tasks": tasks,
    }
    manifest["manifest_sha256"] = _domain_hash(_REQUEST_MANIFEST_DOMAIN, manifest)
    return _canonical_bytes(manifest) + b"\n"


def _fresh_request_manifest_bytes(
    *,
    prepared_inputs: _C1PreparedInputs,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
    integration_head: str,
    integration_tree: str,
) -> bytes:
    """Regenerate all eight requests for synchronous fixed-input validation."""

    def build() -> bytes:
        profile = ModelProfile(
            base_url=deepseek.DEEPSEEK_BASE_URL,
            api_key=SecretStr("provider-free-request-revalidation"),
            model=deepseek.DEEPSEEK_MODEL,
            provider=deepseek.DEEPSEEK_PROVIDER,
            protocol=deepseek.DEEPSEEK_PROTOCOL,
        )
        policy = ProductionModelPolicy({deepseek.DEEPSEEK_MODEL_IDENTITY.identity_key})
        return asyncio.run(
            _build_request_manifest(
                prepared_inputs=prepared_inputs,
                profile=profile,
                policy=policy,
                field_contracts=field_contracts,
                execution_plan=execution_plan,
                integration_head=integration_head,
                integration_tree=integration_tree,
            )
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(build).result()


def _reason_code(error: Exception) -> str:
    reason = getattr(error, "reason_code", None)
    return reason if type(reason) is str and reason else type(error).__name__


def _replay_native_selection_coordinates_815(
    *,
    raw_responses: tuple[EC01RawResponse815V1, ...],
    candidate: Schema67CandidateV2,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
    prepared_inputs: _C1PreparedInputs,
) -> tuple[CoordinateEvidence815V1, ...]:
    try:
        prepared = deepseek.prepare_schema67_deepseek_tasks(
            field_contracts=field_contracts,
            execution_plan=execution_plan,
            role_inputs=prepared_inputs.role_inputs,
        )
        ports = deepseek._schema67_binding_ports(
            prepared_tasks=prepared,
            role_inputs=prepared_inputs.role_inputs,
            admitted_sources=prepared_inputs.admitted_sources,
        )
        if not (
            len(prepared)
            == len(ports)
            == len(raw_responses)
            == len(candidate.batch_execution.executions)
            == 8
        ):
            raise ValueError
        coordinate_rows: list[CoordinateEvidence815V1] = []
        for task, port, raw, execution in zip(
            prepared,
            ports,
            raw_responses,
            candidate.batch_execution.executions,
            strict=True,
        ):
            task_catalogs = tuple(
                deepseek._task_native_selection_catalog_815(
                    prompt=prompt,
                    catalog=prepared_inputs.selection_catalog.require_field(
                        prompt.field_id
                    ),
                )
                for prompt in task.field_prompts
            )
            response = require_model_selection_response_815(
                json.loads(raw.response_bytes),
                task_key=task.task_key,
                field_catalogs=task_catalogs,
            )
            outputs, rows, _reasons = hydrate_model_selection_response_815(
                response=response,
                field_catalogs=task_catalogs,
                source_projections=prepared_inputs.source_projections,
                admitted_sources=port.admitted_sources,
            )
            bound = port.bind_native_selection_outputs(outputs, task_catalogs)
            final_outputs, receipts, demotion = deepseek._demote_initial_nonpass(
                bound,
                outputs,
            )
            if (
                raw.task_key != task.task_key
                or outputs != execution.initial_outputs
                or final_outputs != execution.final_outputs
                or receipts != execution.evidence_receipts
                or demotion != execution.evidence_demotion
                or execution.response_contract_repair is not None
                or execution.evidence_repair is not None
            ):
                raise ValueError
            known = {
                item.field_id for item in final_outputs if item.state != "unknown"
            }
            coordinate_rows.extend(item for item in rows if item.field_id in known)
        order = {
            field_id: index
            for index, field_id in enumerate(
                prepared_inputs.selection_catalog.provider_visible_field_ids
            )
        }
        return tuple(
            sorted(
                coordinate_rows,
                key=lambda item: (
                    order[item.field_id],
                    item.source_role,
                    item.page_number,
                    item.selection_id,
                ),
            )
        )
    except EC01FormalCandidateRunError:
        raise
    except Exception:
        raise EC01FormalCandidateRunError("RAW_PARSED_CANDIDATE_MISMATCH") from None


def _strict_raw_replay(
    *,
    raw_responses: tuple[EC01RawResponse815V1, ...],
    repair_raw_responses: tuple[EC01RawResponse815V1, ...],
    candidate: Schema67CandidateV2,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
    role_inputs: tuple[Schema67RoleTaskInputV1, ...],
    admitted_sources: tuple[AdmittedParseArtifactV1, ...],
    locators_by_task: tuple[tuple[CanonicalLocatorInputV1, ...], ...],
) -> None:
    try:
        prepared = deepseek.prepare_schema67_deepseek_tasks(
            field_contracts=field_contracts,
            execution_plan=execution_plan,
            role_inputs=role_inputs,
        )
        ports = deepseek._schema67_binding_ports(
            prepared_tasks=prepared,
            role_inputs=role_inputs,
            admitted_sources=admitted_sources,
        )
        if not (
            len(prepared)
            == len(ports)
            == len(locators_by_task)
            == len(raw_responses)
            == len(candidate.batch_execution.executions)
            == 8
        ):
            raise EC01FormalCandidateRunError("RAW_RESPONSE_INDEX_INVALID")
        structural_failure_codes: list[str | None] = []
        for task, port, locators, raw, execution in zip(
            prepared,
            ports,
            locators_by_task,
            raw_responses,
            candidate.batch_execution.executions,
            strict=True,
        ):
            if raw.task_key != task.task_key:
                raise EC01FormalCandidateRunError("RAW_RESPONSE_INDEX_INVALID")
            contracts = tuple(task.field_prompts)
            replay_text, structural_failure_code = (
                deepseek._replace_structurally_invalid_initial_response(
                    response_text=raw.response_bytes.decode("utf-8"),
                    port=port,
                    contracts=contracts,
                    locators=locators,
                    task_key=task.task_key,
                )
            )
            structural_failure_codes.append(structural_failure_code)
            payload = json.loads(replay_text)
            slot_authority = deepseek._build_locator_slot_authority(
                port=port,
                contracts=contracts,
                locators=locators,
            )
            deepseek._validate_locator_slot_authority(
                authority=slot_authority,
                port=port,
                contracts=contracts,
                locators=locators,
            )
            selections = deepseek._require_extractor_envelope(
                payload,
                contracts=contracts,
                slot_authority=slot_authority,
                task_key=task.task_key,
            )
            outputs = port.hydrate_extractor_outputs(
                selections=selections,
                contracts=contracts,
                locators=locators,
            )
            if (
                outputs != execution.initial_outputs
                or execution.response_contract_repair is not None
            ):
                raise EC01FormalCandidateRunError("RAW_PARSED_CANDIDATE_MISMATCH")
            initial_binding_bytes = deepseek._canonical_bytes(
                {
                    "task_id": port.task_id,
                    "attempt_hash": port.attempt_hash,
                    "arm_blueprint_hash": port.arm_blueprint_hash,
                    "model_identity_sha256": port.model_identity_sha256,
                    "fields": tuple(
                        item.model_dump(mode="python") for item in outputs
                    ),
                }
            )
            initial = port.bind_initial_exact_literal(initial_binding_bytes)
            if initial != execution.initial:
                raise EC01FormalCandidateRunError("RAW_PARSED_CANDIDATE_MISMATCH")
            if execution.evidence_repair is None:
                if execution.evidence_demotion is None and (
                    outputs != execution.final_outputs
                ):
                    raise EC01FormalCandidateRunError("RAW_PARSED_CANDIDATE_MISMATCH")
        repaired_executions = tuple(
            item
            for item in candidate.batch_execution.executions
            if item.evidence_repair is not None
        )
        if not repaired_executions:
            if repair_raw_responses:
                raise EC01FormalCandidateRunError(
                    "REPAIR_RAW_RESPONSE_INDEX_INVALID"
                )
            return
        contexts = deepseek._prepare_shared_evidence_repair(
            prepared=prepared,
            ports=ports,
            locators_by_task=locators_by_task,
            executions=candidate.batch_execution.executions,
            parent_response_sha256s=tuple(
                item.response_sha256 for item in raw_responses
            ),
            structural_failure_codes=tuple(structural_failure_codes),
        )
        if (
            len(contexts) != len(repaired_executions)
            or len(contexts) != len(repair_raw_responses)
            or any(len(context.tasks) != 1 for context in contexts)
        ):
            raise EC01FormalCandidateRunError("RAW_PARSED_CANDIDATE_MISMATCH")
        expected: tuple[DeepSeekTaskExecutionV1, ...] = tuple(
            candidate.batch_execution.executions
        )
        for context, repair_raw in zip(
            contexts,
            repair_raw_responses,
            strict=True,
        ):
            task_index = context.tasks[0].index
            repair = candidate.batch_execution.executions[
                task_index
            ].evidence_repair
            if (
                repair is None
                or repair.accepted_response_sha256 != repair_raw.response_sha256
            ):
                raise EC01FormalCandidateRunError(
                    "REPAIR_RAW_RESPONSE_INDEX_INVALID"
                )
            repair_payload = json.loads(
                repair_raw.response_bytes.decode("utf-8")
            )
            expected = deepseek._apply_shared_evidence_repair(
                context=context,
                repair_text=repair_raw.response_bytes.decode("utf-8"),
                repair_json=repair_payload,
                executions=expected,
            )
        if expected != candidate.batch_execution.executions:
            raise EC01FormalCandidateRunError("RAW_PARSED_CANDIDATE_MISMATCH")
        _require_targeted_repair_validation(
            batch_execution=candidate.batch_execution,
            repair_raw_responses=repair_raw_responses,
        )
    except EC01FormalCandidateRunError:
        raise
    except DeepSeekCompilerError as error:
        raise EC01FormalCandidateRunError(error.reason_code) from None
    except (
        AttributeError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ):
        raise EC01FormalCandidateRunError("RAW_RESPONSE_REPLAY_INVALID") from None


async def prepare_ec01_formal_candidate_request_manifest_815(
    *,
    revision_set_root: Path,
    profile: ModelProfile,
    policy: ProductionModelPolicy,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
    integration_head: str,
    integration_tree: str,
) -> bytes:
    """Build the exact-eight request identity without invoking the caller transport."""

    if (
        re.fullmatch(r"[0-9a-f]{40}", integration_head) is None
        or re.fullmatch(r"[0-9a-f]{40}", integration_tree) is None
    ):
        raise EC01FormalCandidateRunError("EXECUTION_IDENTITY_INVALID")
    prepared_inputs = _prepare_c1_inputs(
        revision_set_root=revision_set_root,
        field_contracts=field_contracts,
        execution_plan=execution_plan,
    )
    return await _build_request_manifest(
        prepared_inputs=prepared_inputs,
        profile=profile,
        policy=policy,
        field_contracts=field_contracts,
        execution_plan=execution_plan,
        integration_head=integration_head,
        integration_tree=integration_tree,
    )


async def run_ec01_formal_candidate_815(
    *,
    revision_set_root: Path,
    request_identity_manifest_bytes: bytes,
    experiment_id: str,
    execution_identity_sha256: str,
    run_id: str,
    attempt_id: str,
    receipt_id: str,
    integration_head: str,
    integration_tree: str,
    profile: ModelProfile,
    policy: ProductionModelPolicy,
    transport: _ModelTransport,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
) -> EC01FormalCandidateRun815V1:
    """Run the existing exact-eight path and seal one task-local FORMAL Candidate."""

    _require_execution_identity_shape(
        experiment_id=experiment_id,
        execution_identity_sha256=execution_identity_sha256,
        run_id=run_id,
        attempt_id=attempt_id,
        receipt_id=receipt_id,
        integration_head=integration_head,
        integration_tree=integration_tree,
    )
    prepared_inputs = _prepare_c1_inputs(
        revision_set_root=revision_set_root,
        field_contracts=field_contracts,
        execution_plan=execution_plan,
    )
    revision_set_validation = prepared_inputs.revision_validation
    rebuilt_manifest_bytes = await _build_request_manifest(
        prepared_inputs=prepared_inputs,
        profile=profile,
        policy=policy,
        field_contracts=field_contracts,
        execution_plan=execution_plan,
        integration_head=integration_head,
        integration_tree=integration_tree,
    )
    if request_identity_manifest_bytes != rebuilt_manifest_bytes:
        raise EC01FormalCandidateRunError("REQUEST_MANIFEST_INVALID")
    manifest, manifest_sha256 = _require_request_manifest(
        request_identity_manifest_bytes,
        revision_set_validation=revision_set_validation,
        schema_rows_sha256=field_contracts.schema_rows_sha256,
        integration_head=integration_head,
        integration_tree=integration_tree,
    )
    _require_execution_identity(
        experiment_id=experiment_id,
        execution_identity_sha256=execution_identity_sha256,
        run_id=run_id,
        attempt_id=attempt_id,
        receipt_id=receipt_id,
        integration_head=integration_head,
        integration_tree=integration_tree,
        revision_set_sha256=revision_set_validation.revision_set_sha256,
        request_identity_manifest_sha256=manifest_sha256,
    )
    role_inputs = prepared_inputs.role_inputs
    admitted_sources = prepared_inputs.admitted_sources
    locators_by_task = prepared_inputs.locators_by_task
    recorder = _RecordingTransport(
        transport,
        cast(list[object], manifest["tasks"]),
    )
    try:
        batch_execution = await deepseek._run_schema67_deepseek_batch(
            profile=profile,
            policy=policy,
            transport=recorder,
            field_contracts=field_contracts,
            execution_plan=execution_plan,
            role_inputs=role_inputs,
            admitted_sources=admitted_sources,
            locators_by_task=locators_by_task,
            _single_pass_mvp=True,
            _allow_evidence_repair=False,
            _selection_authority=(
                prepared_inputs.selection_catalog,
                prepared_inputs.source_projections,
            ),
        )
        if recorder.repair_raw_responses:
            raise EC01FormalCandidateRunError("REPAIR_RAW_RESPONSE_INDEX_INVALID")
        candidate = admission.make_total_control_schema67_candidate_v2(
            field_contracts=field_contracts,
            execution_plan=execution_plan,
            role_inputs=role_inputs,
            batch_execution=batch_execution,
            candidate_tree_sha1=_CANDIDATE_TREE_SHA1,
        )
        if not any(item.state != "unknown" for item in candidate.fields):
            raise EC01FormalCandidateRunError("FORMAL_CANDIDATE_ALL_UNKNOWN")
        replay_raw = _require_raw_rows(tuple(recorder.raw_responses), expected_count=8)
        coordinate_rows = _replay_native_selection_coordinates_815(
            raw_responses=replay_raw,
            candidate=candidate,
            field_contracts=field_contracts,
            execution_plan=execution_plan,
            prepared_inputs=prepared_inputs,
        )
        coordinate_companion = make_coordinate_evidence_companion_815(
            candidate_sha256=candidate.candidate_sha256,
            selection_catalog=prepared_inputs.selection_catalog,
            source_projections=prepared_inputs.source_projections,
            coordinate_rows=coordinate_rows,
        )
    except Exception as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        raw_responses = tuple(recorder.raw_responses)
        repair_raw_responses = tuple(recorder.repair_raw_responses)
        failure_reason = _reason_code(error)
        terminal = _make_terminal(
            status="FAILED",
            failure_reason=failure_reason,
            raw_responses=raw_responses,
            repair_raw_responses=repair_raw_responses,
                attempted_field_count=(
                    len(prepared_inputs.execution_projection.provider_visible_field_ids)
                    if failure_reason == "FORMAL_CANDIDATE_ALL_UNKNOWN"
                    and len(raw_responses) == 8
                    else 0
                ),
                provider_visible_field_count=len(
                    prepared_inputs.execution_projection.provider_visible_field_ids
                ),
                real_model_output_count=0,
                code_deferred_field_count=len(
                    prepared_inputs.execution_projection.code_deferred
                ),
                dispositioned_field_count=len(field_contracts.contracts),
            experiment_id=experiment_id,
            execution_identity_sha256=execution_identity_sha256,
            run_id=run_id,
            attempt_id=attempt_id,
            receipt_id=receipt_id,
            integration_head=integration_head,
            integration_tree=integration_tree,
            revision_set_sha256=revision_set_validation.revision_set_sha256,
            schema_rows_sha256=field_contracts.schema_rows_sha256,
            request_manifest_sha256=manifest_sha256,
                batch_receipt_sha256=None,
                coordinate_evidence_companion_sha256=None,
        )
        raise EC01FormalCandidateRunError(
            terminal.failure_reason or "FORMAL_CANDIDATE_RUN_FAILED",
            terminal=terminal,
            raw_responses=raw_responses,
            repair_raw_responses=repair_raw_responses,
        ) from None
    raw_responses = _require_raw_rows(tuple(recorder.raw_responses), expected_count=8)
    repair_raw_responses = _require_repair_raw_rows(
        tuple(recorder.repair_raw_responses)
    )
    terminal = _make_terminal(
        status="SUCCEEDED",
        failure_reason=None,
        raw_responses=raw_responses,
        repair_raw_responses=repair_raw_responses,
        attempted_field_count=len(
            prepared_inputs.execution_projection.provider_visible_field_ids
        ),
        provider_visible_field_count=len(
            prepared_inputs.execution_projection.provider_visible_field_ids
        ),
        real_model_output_count=len(
            prepared_inputs.execution_projection.provider_visible_field_ids
        ),
        code_deferred_field_count=len(
            prepared_inputs.execution_projection.code_deferred
        ),
        dispositioned_field_count=len(field_contracts.contracts),
        experiment_id=experiment_id,
        execution_identity_sha256=execution_identity_sha256,
        run_id=run_id,
        attempt_id=attempt_id,
        receipt_id=receipt_id,
        integration_head=integration_head,
        integration_tree=integration_tree,
        revision_set_sha256=revision_set_validation.revision_set_sha256,
        schema_rows_sha256=field_contracts.schema_rows_sha256,
        request_manifest_sha256=manifest_sha256,
        batch_receipt_sha256=batch_execution.receipt.batch_receipt_sha256,
        coordinate_evidence_companion_sha256=coordinate_companion.companion_sha256,
    )
    run = EC01FormalCandidateRun815V1(
        contract=_RUN_CONTRACT,
        revision_validation_sha256=revision_set_validation.validation_sha256,
        schema_rows_sha256=field_contracts.schema_rows_sha256,
        experiment_id=experiment_id,
        execution_identity_sha256=execution_identity_sha256,
        run_id=run_id,
        attempt_id=attempt_id,
        receipt_id=receipt_id,
        integration_head=integration_head,
        integration_tree=integration_tree,
        request_manifest_sha256=manifest_sha256,
        request_manifest_bytes=request_identity_manifest_bytes,
        raw_responses=raw_responses,
        repair_raw_responses=repair_raw_responses,
        terminal=terminal,
        candidate_kind="FORMAL",
        candidate=candidate,
        coordinate_evidence_companion=coordinate_companion,
        derivation_sha256="0" * 64,
    )
    run = replace(run, derivation_sha256=run.recomputed_derivation_sha256())
    return _require_ec01_formal_candidate_run_with_prepared_815(
        run=run,
        prepared_inputs=prepared_inputs,
        field_contracts=field_contracts,
        execution_plan=execution_plan,
    )


def _open_original_run_artifact_root_815(
    artifact_root: Path,
) -> tuple[int, os.stat_result]:
    descriptor: int | None = None
    try:
        if not isinstance(artifact_root, Path) or not artifact_root.is_absolute():
            raise TypeError
        descriptor = os.open(
            artifact_root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        row = os.lstat(artifact_root)
    except (OSError, TypeError):
        if descriptor is not None:
            os.close(descriptor)
        raise EC01FormalCandidateRunError("ORIGINAL_RUN_ARTIFACT_INVALID") from None
    if (
        not stat.S_ISDIR(opened.st_mode)
        or not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or stat.S_IMODE(opened.st_mode) != 0o700
        or opened.st_uid != os.geteuid()
        or (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_uid)
        != (row.st_dev, row.st_ino, row.st_mode, row.st_uid)
    ):
        os.close(descriptor)
        raise EC01FormalCandidateRunError("ORIGINAL_RUN_ARTIFACT_INVALID")
    return descriptor, opened


def _require_original_run_artifact_root_binding_815(
    artifact_root: Path,
    artifact_dir_fd: int,
    opened: os.stat_result,
) -> None:
    try:
        current = os.fstat(artifact_dir_fd)
        row = os.lstat(artifact_root)
    except (OSError, TypeError):
        raise EC01FormalCandidateRunError("ORIGINAL_RUN_ARTIFACT_INVALID") from None
    expected = (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_uid)
    if (
        not stat.S_ISDIR(current.st_mode)
        or not stat.S_ISDIR(row.st_mode)
        or stat.S_ISLNK(row.st_mode)
        or (current.st_dev, current.st_ino, current.st_mode, current.st_uid)
        != expected
        or (row.st_dev, row.st_ino, row.st_mode, row.st_uid) != expected
    ):
        raise EC01FormalCandidateRunError("ORIGINAL_RUN_ARTIFACT_INVALID")


def _read_original_run_artifact_json_815(
    artifact_dir_fd: int,
    name: str,
    *,
    trailing_newline: bool,
    require_sorted_canonical: bool = True,
) -> tuple[bytes, object]:
    try:
        if type(name) is not str or Path(name).name != name or name in {".", ".."}:
            raise TypeError
        before = os.stat(name, dir_fd=artifact_dir_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > _ORIGINAL_RUN_ARTIFACT_MAX_BYTES
        ):
            raise OSError
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=artifact_dir_fd,
        )
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_uid) != (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_uid,
            ):
                raise OSError
            chunks: list[bytes] = []
            while block := os.read(descriptor, 1024 * 1024):
                chunks.append(block)
            after = os.fstat(descriptor)
            if (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            ):
                raise OSError
        finally:
            os.close(descriptor)
        payload = b"".join(chunks)
        value = json.loads(payload.decode("utf-8"))
        expected = _canonical_bytes(value) + (b"\n" if trailing_newline else b"")
        if require_sorted_canonical and payload != expected:
            raise ValueError
        if not require_sorted_canonical and payload.endswith(b"\n"):
            raise ValueError
        return payload, value
    except (OSError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        raise EC01FormalCandidateRunError("ORIGINAL_RUN_ARTIFACT_INVALID") from None


def _require_ec01_formal_candidate_run_artifact_from_dir_fd_815(
    *,
    artifact_dir_fd: int,
    revision_set_root: Path,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
) -> EC01FormalCandidateRun815V1:
    request_manifest_bytes, request_manifest_wire = (
        _read_original_run_artifact_json_815(
            artifact_dir_fd,
            "request-identity-manifest.json",
            trailing_newline=True,
        )
    )
    if type(request_manifest_wire) is not dict:
        raise EC01FormalCandidateRunError("ORIGINAL_RUN_ARTIFACT_INVALID")
    task_rows = request_manifest_wire.get("tasks")
    if type(task_rows) is not list or len(task_rows) != 8:
        raise EC01FormalCandidateRunError("ORIGINAL_RUN_ARTIFACT_INVALID")
    raw_responses: list[EC01RawResponse815V1] = []
    try:
        for ordinal, task_row in enumerate(task_rows, start=1):
            if type(task_row) is not dict:
                raise TypeError
            task_key = task_row["task_key"]
            request_fact = task_row["canonical_request"]
            if (
                type(task_key) is not str
                or task_key != _TASK_KEYS[ordinal - 1]
                or task_row.get("ordinal") != ordinal
                or type(request_fact) is not dict
            ):
                raise ValueError
            request_bytes, _ = _read_original_run_artifact_json_815(
                artifact_dir_fd,
                f"request-{ordinal:02d}.json",
                trailing_newline=False,
                require_sorted_canonical=False,
            )
            if (
                request_fact.get("byte_size") != len(request_bytes)
                or request_fact.get("external_sha256") != _sha256(request_bytes)
            ):
                raise ValueError
            response_bytes, response_wire = _read_original_run_artifact_json_815(
                artifact_dir_fd,
                f"raw-response-{ordinal:02d}.json",
                trailing_newline=False,
                require_sorted_canonical=False,
            )
            if type(response_wire) is not dict or response_wire.get("task_key") != task_key:
                raise ValueError
            raw_responses.append(
                EC01RawResponse815V1(
                    ordinal=ordinal,
                    task_key=task_key,
                    response_bytes=response_bytes,
                    byte_size=len(response_bytes),
                    response_sha256=_sha256(response_bytes),
                )
            )
    except (EC01FormalCandidateRunError, KeyError, TypeError, ValueError):
        raise EC01FormalCandidateRunError("ORIGINAL_RUN_ARTIFACT_INVALID") from None

    _, terminal_wire = _read_original_run_artifact_json_815(
        artifact_dir_fd,
        "terminal.json",
        trailing_newline=True,
    )
    _, candidate_wire = _read_original_run_artifact_json_815(
        artifact_dir_fd,
        "formal-candidate.json",
        trailing_newline=True,
    )
    _, companion_wire = _read_original_run_artifact_json_815(
        artifact_dir_fd,
        "coordinate-evidence-companion.json",
        trailing_newline=True,
    )
    terminal_keys = {item.name for item in dataclass_fields(EC01FormalCandidateTerminal815V1)}
    if type(terminal_wire) is not dict or set(terminal_wire) != terminal_keys:
        raise EC01FormalCandidateRunError("ORIGINAL_RUN_ARTIFACT_INVALID")

    prepared_inputs = _prepare_c1_inputs(
        revision_set_root=revision_set_root,
        field_contracts=field_contracts,
        execution_plan=execution_plan,
    )
    try:
        terminal = EC01FormalCandidateTerminal815V1(**cast(Any, terminal_wire))
        candidate = admission.load_schema67_candidate_v2(
            candidate_wire,
            field_contracts=field_contracts,
            execution_plan=execution_plan,
            role_inputs=prepared_inputs.role_inputs,
        )
        companion = CoordinateEvidenceCompanion815V1.model_validate(companion_wire)
        _, request_manifest_sha256 = _require_request_manifest(
            request_manifest_bytes,
            revision_set_validation=prepared_inputs.revision_validation,
            schema_rows_sha256=field_contracts.schema_rows_sha256,
            integration_head=terminal.integration_head,
            integration_tree=terminal.integration_tree,
        )
        run = EC01FormalCandidateRun815V1(
            contract=_RUN_CONTRACT,
            revision_validation_sha256=(
                prepared_inputs.revision_validation.validation_sha256
            ),
            schema_rows_sha256=field_contracts.schema_rows_sha256,
            experiment_id=terminal.experiment_id,
            execution_identity_sha256=terminal.execution_identity_sha256,
            run_id=terminal.run_id,
            attempt_id=terminal.attempt_id,
            receipt_id=terminal.receipt_id,
            integration_head=terminal.integration_head,
            integration_tree=terminal.integration_tree,
            request_manifest_sha256=request_manifest_sha256,
            request_manifest_bytes=request_manifest_bytes,
            raw_responses=tuple(raw_responses),
            repair_raw_responses=(),
            terminal=terminal,
            candidate_kind="FORMAL",
            candidate=candidate,
            coordinate_evidence_companion=companion,
            derivation_sha256="0" * 64,
        )
        run = replace(run, derivation_sha256=run.recomputed_derivation_sha256())
        return _require_ec01_formal_candidate_run_with_prepared_815(
            run=run,
            prepared_inputs=prepared_inputs,
            field_contracts=field_contracts,
            execution_plan=execution_plan,
        )
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        ValidationError,
        admission.LaneCReportGateError,
        EC01FormalCandidateRunError,
    ):
        raise EC01FormalCandidateRunError("ORIGINAL_RUN_ARTIFACT_INVALID") from None


def require_ec01_formal_candidate_run_artifact_815(
    *,
    artifact_root: Path,
    revision_set_root: Path,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
) -> EC01FormalCandidateRun815V1:
    """Fresh-open one persisted original-run split set and require its nominal run."""

    artifact_dir_fd, opened = _open_original_run_artifact_root_815(artifact_root)
    try:
        run = _require_ec01_formal_candidate_run_artifact_from_dir_fd_815(
            artifact_dir_fd=artifact_dir_fd,
            revision_set_root=revision_set_root,
            field_contracts=field_contracts,
            execution_plan=execution_plan,
        )
        _require_original_run_artifact_root_binding_815(
            artifact_root,
            artifact_dir_fd,
            opened,
        )
        return run
    finally:
        os.close(artifact_dir_fd)


def require_ec01_formal_candidate_run_815(
    *,
    run: EC01FormalCandidateRun815V1,
    revision_set_root: Path,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
) -> EC01FormalCandidateRun815V1:
    """Freshly derive parsed fields from original raw bytes and require the Candidate."""

    prepared_inputs = _prepare_c1_inputs(
        revision_set_root=revision_set_root,
        field_contracts=field_contracts,
        execution_plan=execution_plan,
    )
    return _require_ec01_formal_candidate_run_with_prepared_815(
        run=run,
        prepared_inputs=prepared_inputs,
        field_contracts=field_contracts,
        execution_plan=execution_plan,
    )


def _require_ec01_formal_candidate_run_with_prepared_815(
    *,
    run: EC01FormalCandidateRun815V1,
    prepared_inputs: _C1PreparedInputs,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
) -> EC01FormalCandidateRun815V1:
    """Require one run against already fresh-validated inputs from the same call."""

    revision_set_validation = prepared_inputs.revision_validation
    request_identity_manifest_bytes = run.request_manifest_bytes
    if request_identity_manifest_bytes != _fresh_request_manifest_bytes(
        prepared_inputs=prepared_inputs,
        field_contracts=field_contracts,
        execution_plan=execution_plan,
        integration_head=run.integration_head,
        integration_tree=run.integration_tree,
    ):
        raise EC01FormalCandidateRunError("REQUEST_MANIFEST_INVALID")
    manifest, manifest_sha256 = _require_request_manifest(
        request_identity_manifest_bytes,
        revision_set_validation=revision_set_validation,
        schema_rows_sha256=field_contracts.schema_rows_sha256,
        integration_head=run.integration_head,
        integration_tree=run.integration_tree,
    )
    _require_execution_identity(
        experiment_id=run.experiment_id,
        execution_identity_sha256=run.execution_identity_sha256,
        run_id=run.run_id,
        attempt_id=run.attempt_id,
        receipt_id=run.receipt_id,
        integration_head=run.integration_head,
        integration_tree=run.integration_tree,
        revision_set_sha256=revision_set_validation.revision_set_sha256,
        request_identity_manifest_sha256=manifest_sha256,
    )
    if (
        type(run) is not EC01FormalCandidateRun815V1
        or run.contract != _RUN_CONTRACT
        or run.revision_validation_sha256 != revision_set_validation.validation_sha256
        or run.schema_rows_sha256 != field_contracts.schema_rows_sha256
        or run.schema_rows_sha256 != manifest["schema_rows_sha256"]
        or run.request_manifest_sha256 != manifest_sha256
        or run.candidate_kind != "FORMAL"
        or type(run.candidate) is not Schema67CandidateV2
        or type(run.request_manifest_bytes) is not bytes
    ):
        raise EC01FormalCandidateRunError("FORMAL_RUN_IDENTITY_INVALID")
    raw_responses = _require_raw_rows(run.raw_responses, expected_count=8)
    repair_raw_responses = _require_repair_raw_rows(run.repair_raw_responses)
    terminal_payload = _terminal_payload(
        status=run.terminal.status,
        failure_reason=run.terminal.failure_reason,
        raw_count=run.terminal.raw_count,
        attempted_field_count=run.terminal.attempted_field_count,
        provider_visible_field_count=run.terminal.provider_visible_field_count,
        real_model_output_count=run.terminal.real_model_output_count,
        code_deferred_field_count=run.terminal.code_deferred_field_count,
        dispositioned_field_count=run.terminal.dispositioned_field_count,
        experiment_id=run.terminal.experiment_id,
        execution_identity_sha256=run.terminal.execution_identity_sha256,
        run_id=run.terminal.run_id,
        attempt_id=run.terminal.attempt_id,
        receipt_id=run.terminal.receipt_id,
        integration_head=run.terminal.integration_head,
        integration_tree=run.terminal.integration_tree,
        model_execution_identity_sha256=run.terminal.model_execution_identity_sha256,
        revision_set_sha256=run.terminal.revision_set_sha256,
        schema_rows_sha256=run.terminal.schema_rows_sha256,
        request_manifest_sha256=run.terminal.request_manifest_sha256,
        raw_index_sha256=run.terminal.raw_index_sha256,
        batch_receipt_sha256=run.terminal.batch_receipt_sha256,
        coordinate_evidence_companion_sha256=(
            run.terminal.coordinate_evidence_companion_sha256
        ),
    )
    if (
        type(run.terminal) is not EC01FormalCandidateTerminal815V1
        or run.terminal.contract != _TERMINAL_CONTRACT
        or run.terminal.status != "SUCCEEDED"
        or run.terminal.failure_reason is not None
        or run.terminal.raw_count != 8
        or repair_raw_responses
        or run.terminal.attempted_field_count
        != len(prepared_inputs.execution_projection.provider_visible_field_ids)
        or run.terminal.provider_visible_field_count
        != len(prepared_inputs.execution_projection.provider_visible_field_ids)
        or run.terminal.real_model_output_count
        != len(prepared_inputs.execution_projection.provider_visible_field_ids)
        or run.terminal.code_deferred_field_count
        != len(prepared_inputs.execution_projection.code_deferred)
        or run.terminal.dispositioned_field_count != len(admission.ORDERED_FIELD_IDS)
        or run.terminal.experiment_id != run.experiment_id
        or run.terminal.execution_identity_sha256 != run.execution_identity_sha256
        or run.terminal.run_id != run.run_id
        or run.terminal.attempt_id != run.attempt_id
        or run.terminal.receipt_id != run.receipt_id
        or run.terminal.integration_head != run.integration_head
        or run.terminal.integration_tree != run.integration_tree
        or run.terminal.model_execution_identity_sha256
        != deepseek.DEEPSEEK_EXECUTION_IDENTITY_SHA256
        or run.terminal.revision_set_sha256 != revision_set_validation.revision_set_sha256
        or run.terminal.schema_rows_sha256 != run.schema_rows_sha256
        or run.terminal.schema_rows_sha256 != manifest["schema_rows_sha256"]
        or run.terminal.request_manifest_sha256 != manifest_sha256
        or run.terminal.raw_index_sha256
        != _raw_index_sha256(raw_responses, repair_raw_responses)
        or run.terminal.batch_receipt_sha256 != run.candidate.batch_receipt.batch_receipt_sha256
        or run.terminal.coordinate_evidence_companion_sha256
        != run.coordinate_evidence_companion.companion_sha256
        or run.terminal.terminal_sha256 != _domain_hash(_TERMINAL_CONTRACT, terminal_payload)
        or run.derivation_sha256 != run.recomputed_derivation_sha256()
    ):
        raise EC01FormalCandidateRunError("FORMAL_RUN_IDENTITY_INVALID")
    try:
        admission.validate_schema67_candidate_v2(run.candidate)
    except (AttributeError, TypeError, ValueError):
        raise EC01FormalCandidateRunError("FORMAL_CANDIDATE_INVALID") from None
    request_rows = cast(list[object], manifest["tasks"])
    request_sha256s = tuple(
        cast(dict[str, object], cast(dict[str, object], row)["canonical_request"])[
            "external_sha256"
        ]
        for row in request_rows
    )
    execution_sha256s = tuple(
        execution.receipt.extractor_request_sha256
        for execution in run.candidate.batch_execution.executions
    )
    if request_sha256s != execution_sha256s:
        raise EC01FormalCandidateRunError("FORMAL_RUN_IDENTITY_INVALID")
    fields = run.candidate.fields
    executable_field_ids = tuple(
        field_id for item in execution_plan.task_slices for field_id in item.field_ids
    )
    provider_visible_field_ids = (
        prepared_inputs.execution_projection.provider_visible_field_ids
    )
    deferred_field_ids = tuple(
        item.field_id for item in prepared_inputs.execution_projection.code_deferred
    )
    by_field = {item.field_id: item for item in fields}
    demoted_field_ids = tuple(
        field_id
        for execution in run.candidate.batch_execution.executions
        if execution.evidence_demotion is not None
        for field_id in execution.evidence_demotion.demoted_field_ids
    )
    repaired_unknown_field_ids = tuple(
        item.field_id
        for execution in run.candidate.batch_execution.executions
        if execution.evidence_repair is not None
        for item in execution.evidence_repair.verifier_resolution.results
        if item.status != "PASS"
        and item.field_id in execution.evidence_repair.repair_plan.field_ids
    )
    initial_unknown_field_ids = tuple(
        item.field_id
        for execution in run.candidate.batch_execution.executions
        for item in execution.initial_outputs
        if item.state == "unknown"
    )
    normalized_unknown_field_ids = (
        *initial_unknown_field_ids,
        *demoted_field_ids,
        *repaired_unknown_field_ids,
    )
    if (
        tuple(item.field_id for item in fields) != admission.ORDERED_FIELD_IDS
        or len(fields) != 67
        or len(executable_field_ids) != len(provider_visible_field_ids)
        or set(executable_field_ids) != set(provider_visible_field_ids)
        or execution_plan.deferred_unknown_field_ids != deferred_field_ids
        or set(provider_visible_field_ids).intersection(deferred_field_ids)
        or tuple(
            item
            for item in admission.ORDERED_FIELD_IDS
            if item in set(provider_visible_field_ids) | set(deferred_field_ids)
        )
        != admission.ORDERED_FIELD_IDS
        or len(normalized_unknown_field_ids) != len(set(normalized_unknown_field_ids))
        or any(
            (by_field[field_id].state == "unknown")
            != (field_id in normalized_unknown_field_ids)
            for field_id in executable_field_ids
        )
        or any(
            by_field[field_id].state != "unknown"
            or by_field[field_id].value_snapshot is not None
            or by_field[field_id].evidence
            for field_id in deferred_field_ids
        )
    ):
        raise EC01FormalCandidateRunError("FORMAL_CANDIDATE_FIELD_SET_INVALID")
    coordinate_rows = _replay_native_selection_coordinates_815(
        raw_responses=raw_responses,
        candidate=run.candidate,
        field_contracts=field_contracts,
        execution_plan=execution_plan,
        prepared_inputs=prepared_inputs,
    )
    expected_companion = make_coordinate_evidence_companion_815(
        candidate_sha256=run.candidate.candidate_sha256,
        selection_catalog=prepared_inputs.selection_catalog,
        source_projections=prepared_inputs.source_projections,
        coordinate_rows=coordinate_rows,
    )
    if (
        type(run.coordinate_evidence_companion)
        is not CoordinateEvidenceCompanion815V1
        or run.coordinate_evidence_companion != expected_companion
    ):
        raise EC01FormalCandidateRunError("FORMAL_RUN_IDENTITY_INVALID")
    return run


__all__ = [
    "EC01FormalCandidateRun815V1",
    "EC01FormalCandidateRunError",
    "EC01FormalCandidateTerminal815V1",
    "EC01RawResponse815V1",
    "prepare_ec01_formal_candidate_request_manifest_815",
    "require_ec01_formal_candidate_run_artifact_815",
    "require_ec01_formal_candidate_run_815",
    "run_ec01_formal_candidate_815",
]
