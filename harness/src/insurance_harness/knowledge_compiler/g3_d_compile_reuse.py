"""Reuse a completed compile for independently bounded review without new extraction."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self, TypedDict

from pydantic import BaseModel, ConfigDict, model_validator

from insurance_harness.model_policy import g3_bounded_gateway as gateway
from insurance_harness.run_admission.g3_models import (
    G3StageLedgerBindingV1,
    G3StageTerminalReceiptV1,
    canonical_g3_hash,
)

from .batch_canonical_830_g3 import batch_sha256_830_g3
from .batch_concept_compile_830_g3 import (
    BatchConceptCompileRequest830G3V1,
    Hash,
    compile_output_hash_g3,
    compose_batch_output,
)
from .concept_compile_830_g2 import CompileResult
from .g3_d_projection_reuse import _load_origin, _read


class G3CompileResultReuseV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    contract: Literal["g3-d-compile-result-reuse.830.v1"]
    origin_admission_digest: Hash
    origin_terminal_sha256: Hash
    request_sha256: Hash
    model_result_sha256: Hash
    final_result_sha256: Hash
    receipt_sha256: Hash

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if self.receipt_sha256 != batch_sha256_830_g3(
            self.contract,
            self.model_dump(exclude={"receipt_sha256"}),
        ):
            raise ValueError("compile reuse receipt hash mismatch")
        return self


@dataclass(frozen=True)
class _CompletedCompile:
    request: BatchConceptCompileRequest830G3V1
    model_result: CompileResult
    final_result: CompileResult
    terminal_sha256: str


class _CompileReusePayload(TypedDict):
    contract: Literal["g3-d-compile-result-reuse.830.v1"]
    origin_admission_digest: str
    origin_terminal_sha256: str
    request_sha256: str
    model_result_sha256: str
    final_result_sha256: str


def _load_successful_compile(
    origin_admission_digest: str,
    *,
    admission_root: str | Path | None = None,
    ledger_root: str | Path | None = None,
) -> _CompletedCompile:
    plan, request = _load_origin(origin_admission_digest, admission_root)
    root = Path(ledger_root if ledger_root is not None else gateway.G3_LEDGER_ROOT)
    chain = root / "chains" / plan.chain_manifest_hash
    binding = _read(chain / "stage-bindings/D_COMPILE.json", G3StageLedgerBindingV1)
    terminal = _read(chain / "stage-terminals/D_COMPILE.json", G3StageTerminalReceiptV1)
    if (
        binding.chain_manifest_hash != plan.chain_manifest_hash
        or binding.parent_authorization_digest != plan.parent_authorization_digest
        or binding.admission_artifact_digest != origin_admission_digest
        or binding.stage != "D_COMPILE"
        or binding.receipt_sha256
        != canonical_g3_hash(
            binding.contract,
            binding,
            "receipt_sha256",
        )
        or terminal.status != "SUCCESS"
        or terminal.stage != "D_COMPILE"
        or terminal.chain_id != plan.chain_id
        or terminal.parent_authorization_digest != plan.parent_authorization_digest
        or terminal.admission_artifact_digest != origin_admission_digest
        or terminal.stage_binding_receipt_sha256 != binding.receipt_sha256
        or terminal.receipt_sha256
        != canonical_g3_hash(
            terminal.contract,
            terminal,
            "receipt_sha256",
        )
    ):
        raise ValueError("compile reuse requires an authenticated successful stage")
    calls = tuple(sorted(plan.request_manifest.calls, key=lambda row: row.ordinal))
    recorded = tuple(
        gateway.read_g3_recorded_call(
            plan=plan,
            call=call,
            admission_artifact_digest=origin_admission_digest,
            ledger_root=root,
        )
        for call in calls
    )
    if (
        terminal.calls_consumed != len(calls)
        or any(row.terminal.status != "SUCCESS" for row in recorded)
        or tuple(row.terminal.receipt_sha256 for row in recorded) != terminal.call_terminal_sha256s
    ):
        raise ValueError("compile reuse successful call closure mismatch")
    model = _read(chain / "stage-results/D_COMPILE/model-compile-result.json", CompileResult)
    final = _read(chain / "stage-results/D_COMPILE/final-compile-result.json", CompileResult)
    if final.output != compose_batch_output(
        request, model
    ) or terminal.stage_output_sha256 != compile_output_hash_g3(final.output):
        raise ValueError("compile reuse result closure mismatch")
    return _CompletedCompile(request, model, final, terminal.receipt_sha256)


def _payload(origin_admission_digest: str, completed: _CompletedCompile) -> _CompileReusePayload:
    return _CompileReusePayload(
        contract="g3-d-compile-result-reuse.830.v1",
        origin_admission_digest=origin_admission_digest,
        origin_terminal_sha256=completed.terminal_sha256,
        request_sha256=completed.request.request_sha256,
        model_result_sha256=batch_sha256_830_g3(
            "g3-d-model-compile-result.830.v1", completed.model_result
        ),
        final_result_sha256=batch_sha256_830_g3(
            "g3-d-final-compile-result.830.v1", completed.final_result
        ),
    )


def build_compile_result_reuse(
    *,
    origin_admission_digest: str,
    admission_root: str | Path | None = None,
    ledger_root: str | Path | None = None,
) -> G3CompileResultReuseV1:
    completed = _load_successful_compile(
        origin_admission_digest,
        admission_root=admission_root,
        ledger_root=ledger_root,
    )
    payload = _payload(origin_admission_digest, completed)
    return G3CompileResultReuseV1.model_validate(
        {
            **payload,
            "receipt_sha256": batch_sha256_830_g3(payload["contract"], payload),
        }
    )


def validate_compile_reuse_binding(
    receipt: object,
    *,
    request: BatchConceptCompileRequest830G3V1,
    model_result: CompileResult,
    final_result: CompileResult,
) -> G3CompileResultReuseV1:
    receipt = G3CompileResultReuseV1.model_validate(receipt)
    supplied = _CompletedCompile(
        request, model_result, final_result, receipt.origin_terminal_sha256
    )
    if _payload(receipt.origin_admission_digest, supplied) != receipt.model_dump(
        exclude={"receipt_sha256"},
    ):
        raise ValueError("compile reuse current result binding mismatch")
    return receipt


def validate_compile_result_reuse(
    receipt: object,
    *,
    request: BatchConceptCompileRequest830G3V1,
    model_result: CompileResult,
    final_result: CompileResult,
    admission_root: str | Path | None = None,
    ledger_root: str | Path | None = None,
) -> None:
    receipt = validate_compile_reuse_binding(
        receipt,
        request=request,
        model_result=model_result,
        final_result=final_result,
    )
    completed = _load_successful_compile(
        receipt.origin_admission_digest,
        admission_root=admission_root,
        ledger_root=ledger_root,
    )
    if _payload(receipt.origin_admission_digest, completed) != receipt.model_dump(
        exclude={"receipt_sha256"},
    ):
        raise ValueError("compile reuse origin binding mismatch")
