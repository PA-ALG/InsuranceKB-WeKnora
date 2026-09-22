"""Reuse immutable PASS reviews only when their entire local review input is unchanged."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, model_validator

from insurance_harness.model_policy import ModelIdentity
from insurance_harness.model_policy import g3_bounded_gateway as gateway
from insurance_harness.run_admission.g3_models import (
    G3BoundedAdmissionPlanV1,
    G3BoundedApprovalEnvelopeV1,
    G3ModelProcessingAuthorizationEnvelopeV1,
    G3ProviderUsageV1,
    G3StageLedgerBindingV1,
    G3StageTerminalReceiptV1,
    canonical_g3_hash,
)

from .batch_canonical_830_g3 import batch_json_bytes_830_g3, batch_sha256_830_g3
from .batch_concept_compile_830_g3 import (
    BatchConceptCompileRequest830G3V1,
    Hash,
    compile_output_hash_g3,
    compile_request_hash_g3,
    compose_batch_output,
)
from .concept_compile_830_g2 import CompileOutput, CompileResult, ReviewOutput
from .concept_free_wiki_830_g2 import SourceBlock
from .g3_d_projection_reuse import _read

CONTRACT = "g3-d-review-result-reuse.830.v1"

if TYPE_CHECKING:
    from .g3_bounded_model_execution import G3DReviewWindow, G3DReviewWindowContext


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class G3ReviewReuseEntryV1(_Frozen):
    origin_call_id: str
    origin_window_id: str
    current_window_id: str
    entity_id: str
    local_context_sha256: Hash
    origin_request_body_sha256: Hash
    origin_response_body_sha256: Hash
    origin_call_terminal_sha256: Hash
    origin_review_sha256: Hash
    current_review_sha256: Hash
    observed_usage: G3ProviderUsageV1


class G3ReviewResultReuseV1(_Frozen):
    contract: Literal["g3-d-review-result-reuse.830.v1"]
    current_request_sha256: Hash
    current_output_sha256: Hash
    origin_admission_digest: Hash
    origin_request_sha256: Hash
    origin_output_sha256: Hash
    origin_chain_manifest_hash: Hash
    origin_parent_authorization_digest: Hash
    origin_stage_terminal_sha256: Hash
    origin_stage_status: Literal["SUCCESS", "FAILED"]
    entries: tuple[G3ReviewReuseEntryV1, ...]
    receipt_sha256: Hash

    @model_validator(mode="after")
    def closure(self) -> Self:
        if (
            not self.entries
            or len({r.origin_call_id for r in self.entries}) != len(self.entries)
            or len({r.current_window_id for r in self.entries}) != len(self.entries)
            or self.receipt_sha256
            != batch_sha256_830_g3(self.contract, self.model_dump(exclude={"receipt_sha256"}))
        ):
            raise ValueError("review reuse hash or unique partition mismatch")
        return self


@dataclass(frozen=True)
class _OriginReview:
    plan: G3BoundedAdmissionPlanV1
    request: BatchConceptCompileRequest830G3V1
    output: CompileOutput
    terminal: G3StageTerminalReceiptV1
    records: dict[str, gateway.G3RecordedCall]


def _signed_input[ModelT: BaseModel](
    root: Path,
    plan: G3BoundedAdmissionPlanV1,
    contract: str,
    model: type[ModelT],
) -> ModelT:
    refs = [ref for ref in plan.eligibility_lock.input_artifacts if ref.contract == contract]
    if len(refs) != 1:
        raise ValueError("review reuse original input reference ambiguous")
    ref = refs[0]
    original = Path(ref.artifact_ref)
    if (
        original.parent.name != ref.sha256
        or original.parent.parent.name != "sha256"
        or ref not in plan.provenance_lock.artifacts
        or ref not in plan.rights_lock.artifacts
    ):
        raise ValueError("review reuse original input custody mismatch")
    path = root / "sha256" / ref.sha256 / original.name
    result = _read(path, model, ref.sha256)
    if path.stat().st_size != ref.bytes:
        raise ValueError("review reuse original input size mismatch")
    return result


def _load_origin_review(
    origin_admission_digest: str,
    *,
    admission_root: str | Path | None = None,
    ledger_root: str | Path | None = None,
) -> _OriginReview:
    from insurance_harness.run_admission import evaluator
    from insurance_harness.run_admission.g3_trust_policy import (
        load_g3_root_trust_policy,
        verify_delegated_stage_signature,
        verify_parent_authorization,
    )
    from insurance_harness.run_admission.profiles.g3_bounded_execution import (
        validate_g3_bounded_plan,
        validate_g3_parent_scope,
    )

    root = Path(admission_root if admission_root is not None else evaluator._ADMISSION_STORE_ROOT)
    approval = _read(
        root / "sha256" / origin_admission_digest / "approval-envelope.json",
        G3BoundedApprovalEnvelopeV1,
        origin_admission_digest,
    )
    plan = validate_g3_bounded_plan(approval.payload)
    parent = _read(
        root / "sha256" / plan.parent_authorization_digest / "model-processing-authorization.json",
        G3ModelProcessingAuthorizationEnvelopeV1,
        plan.parent_authorization_digest,
    )
    verify_parent_authorization(load_g3_root_trust_policy(), parent)
    verify_delegated_stage_signature(parent, approval)
    validate_g3_parent_scope(parent.payload, plan)
    if plan.stage != "D_REVIEW":
        raise ValueError("review reuse requires original review admission")
    request = _signed_input(
        root, plan, "batch-concept-compile-request.830.g3.v1", BatchConceptCompileRequest830G3V1
    )
    model = _signed_input(root, plan, "g3-d-model-compile-result.830.v1", CompileResult)
    final = _signed_input(root, plan, "g3-d-final-compile-result.830.v1", CompileResult)
    if final.output != compose_batch_output(request, model):
        raise ValueError("review reuse original compile composition mismatch")
    ledger = Path(ledger_root if ledger_root is not None else gateway.G3_LEDGER_ROOT)
    chain = ledger / "chains" / plan.chain_manifest_hash
    binding = _read(chain / "stage-bindings/D_REVIEW.json", G3StageLedgerBindingV1)
    terminal = _read(chain / "stage-terminals/D_REVIEW.json", G3StageTerminalReceiptV1)
    if (
        binding.chain_manifest_hash != plan.chain_manifest_hash
        or binding.parent_authorization_digest != plan.parent_authorization_digest
        or binding.admission_artifact_digest != origin_admission_digest
        or binding.stage != "D_REVIEW"
        or binding.receipt_sha256 != canonical_g3_hash(binding.contract, binding, "receipt_sha256")
        or terminal.stage != "D_REVIEW"
        or terminal.status not in ("SUCCESS", "FAILED")
        or terminal.chain_id != plan.chain_id
        or terminal.parent_authorization_digest != plan.parent_authorization_digest
        or terminal.admission_artifact_digest != origin_admission_digest
        or terminal.stage_binding_receipt_sha256 != binding.receipt_sha256
        or terminal.receipt_sha256
        != canonical_g3_hash(terminal.contract, terminal, "receipt_sha256")
    ):
        raise ValueError("review reuse stage custody mismatch")
    calls = tuple(sorted(plan.request_manifest.calls, key=lambda call: call.ordinal))
    records = {
        call.call_id: gateway.read_g3_recorded_call(
            plan=plan,
            call=call,
            admission_artifact_digest=origin_admission_digest,
            ledger_root=ledger,
        )
        for call in calls
    }
    if (
        terminal.calls_consumed != len(calls)
        or any(row.terminal.status != "SUCCESS" for row in records.values())
        or tuple(records[call.call_id].terminal.receipt_sha256 for call in calls)
        != terminal.call_terminal_sha256s
    ):
        raise ValueError("review reuse requires complete successful call closure")
    # A REJECT may have prevented Candidate assembly. Its FAILED stage remains FAILED.
    return _OriginReview(plan, request, final.output, terminal, records)


def local_review_context(
    request: BatchConceptCompileRequest830G3V1,
    context: G3DReviewWindowContext,
    *,
    _sources: Mapping[str, SourceBlock] | None = None,
) -> dict[str, Any]:
    """Normalize only declared global bindings and request-derived opaque references.

    Sources use full SourceBlock content identity; selected snippets and all candidate,
    schema, policy, audit and linked-definition content remain exact comparison inputs.
    """
    from . import g3_bounded_model_execution as runtime

    value = cast(dict[str, Any], runtime._unique_json_bytes(batch_json_bytes_830_g3(context)))
    if value.get("contract") != "g3-d-review-bounded-window-context.830.v2":
        raise ValueError("review reuse requires bounded local context")
    if (
        not {"fields", "pages", "owned_novel_definitions"}
        <= value.get("candidate_partition", {}).keys()
    ):
        raise ValueError("review reuse local candidate shape mismatch")
    sources = runtime._g3_d_source_index(request)[1] if _sources is None else _sources
    offered = value["source_options"]
    source_map = {}
    for option in offered:
        ref = option["source_ref"]
        source = sources.get(ref)
        if source is None or option["source"] != source.model_dump(mode="json", exclude={"text"}):
            raise ValueError("review reuse local source identity mismatch")
        for span in option["spans"]:
            if (
                type(span["start"]) is not int
                or type(span["end"]) is not int
                or not 0 <= span["start"] < span["end"] <= len(source.text)
                or span["quote"] != source.text[span["start"] : span["end"]]
            ):
                raise ValueError("review reuse local source span mismatch")
        source_map[ref] = batch_sha256_830_g3("g3-review-reused-source.830.v1", source)
    review_map = {target["review_ref"]: target["member_id"] for target in value["review_targets"]}
    for key in (
        "request_sha256",
        "base_request_hash",
        "output_hash",
        "local_whole_candidate_binding",
    ):
        value.pop(key)
    window = value["window"]
    window.pop("window_id")
    window.pop("entity_slot")
    window["entity_ref"] = window["entity_id"]
    window["review_refs"] = [review_map[ref] for ref in window["review_refs"]]
    for target in value["review_targets"]:
        target["review_ref"] = review_map[target["review_ref"]]
    for option in offered:
        option["source_ref"] = source_map[option["source_ref"]]
    value["source_options"] = sorted(offered, key=lambda row: row["source_ref"])
    for key in ("fields", "pages", "owned_novel_definitions"):
        for member in value["candidate_partition"][key]:
            for evidence in member["evidence"]:
                evidence["source_ref"] = source_map[evidence["source_ref"]]
    return value


def _local_hash(
    request: BatchConceptCompileRequest830G3V1,
    context: G3DReviewWindowContext,
    sources: Mapping[str, SourceBlock] | None = None,
) -> str:
    return batch_sha256_830_g3(
        "g3-local-review-context.830.v1", local_review_context(request, context, _sources=sources)
    )


def _contexts(
    request: BatchConceptCompileRequest830G3V1, output: CompileOutput
) -> tuple[tuple[G3DReviewWindow, G3DReviewWindowContext], ...]:
    from . import g3_bounded_model_execution as runtime

    windows = runtime.derive_gemini_d_review_windows(request, output)
    scope = runtime._g3_review_scope(request, output)
    return tuple(
        (window, runtime._render_g3_bounded_review_context(request, output, window, scope))
        for window in windows
    )


def _derive(
    origin_admission_digest: str,
    origin: _OriginReview,
    current_request: BatchConceptCompileRequest830G3V1,
    current_output: CompileOutput,
    origin_call_ids: Sequence[str] | None = None,
    current_identity: ModelIdentity | None = None,
) -> tuple[G3ReviewResultReuseV1, dict[str, ReviewOutput]]:
    from . import g3_bounded_model_execution as runtime

    current_sources = runtime._g3_d_source_index(current_request)[1]
    old_sources = runtime._g3_d_source_index(origin.request)[1]
    old_targets = {
        row["review_ref"]: row["member_id"]
        for row in runtime._g3_d_review_targets(origin.request, origin.output)
    }
    current: dict[str, G3DReviewWindow] = {}
    for window, context in _contexts(current_request, current_output):
        digest = _local_hash(current_request, context, current_sources)
        if digest in current:
            raise ValueError("review reuse local partition ambiguous")
        current[digest] = window
    old = {
        window["window_id"]: (window, context)
        for window, context in _contexts(origin.request, origin.output)
    }
    calls = {call.call_id: call for call in origin.plan.request_manifest.calls}
    selected = tuple(calls) if origin_call_ids is None else tuple(origin_call_ids)
    if len(set(selected)) != len(selected) or not set(selected) <= calls.keys():
        raise ValueError("review reuse origin call selection is foreign or duplicated")
    entries: list[G3ReviewReuseEntryV1] = []
    outputs: dict[str, ReviewOutput] = {}
    for call_id in selected:
        call, record = calls[call_id], origin.records[call_id]
        if call.window_id is None:
            raise ValueError("review reuse call has no window")
        if current_identity is not None and call.identity != current_identity:
            raise ValueError("review reuse current model identity mismatch")
        if record.terminal.status != "SUCCESS":
            raise ValueError("review reuse requires successful original call")
        pair = old.get(call.window_id)
        if pair is None:
            raise ValueError("review reuse original window no longer derivable")
        window, context = pair
        if tuple(window["material_ids"]) != call.material_ids:
            raise ValueError("review reuse original material binding mismatch")
        prompt = (
            Path(runtime.__file__).parent
            / "prompts"
            / runtime.g3_d_template_name("D_REVIEW", call.identity)
        ).read_text()
        expected_body = runtime.g3_openai_request_bytes(
            plan=origin.plan,
            call=call,
            system=prompt,
            user=batch_json_bytes_830_g3(context).decode(),
        )
        if record.request_bytes != expected_body:
            raise ValueError("review reuse original prompt/context no longer exact")
        previous = runtime._project_g3_exact_review_response(
            record.semantic_bytes, origin.request, origin.output, window, old_targets
        )
        if record.terminal.projection_sha256 != runtime._gemini_d_review_window_projection_hash(
            call.window_id, previous
        ):
            raise ValueError("review reuse original projection mismatch")
        if previous.decision != "PASS":
            if origin_call_ids is not None:
                raise ValueError("review reuse requires original PASS decision")
            continue
        local_sha = _local_hash(origin.request, context, old_sources)
        target = current.get(local_sha)
        if target is None:
            if origin_call_ids is not None:
                raise ValueError("review reuse local context changed")
            continue
        rebound = previous.model_copy(
            update=dict(
                request_hash=compile_request_hash_g3(current_request.base_request),
                output_hash=compile_output_hash_g3(current_output),
            )
        )
        if target["window_id"] in outputs:
            raise ValueError("review reuse current window duplicated")
        outputs[target["window_id"]] = rebound
        entries.append(
            G3ReviewReuseEntryV1(
                origin_call_id=call_id,
                origin_window_id=call.window_id,
                current_window_id=target["window_id"],
                entity_id=target["entity_id"],
                local_context_sha256=local_sha,
                origin_request_body_sha256=hashlib.sha256(record.request_bytes).hexdigest(),
                origin_response_body_sha256=hashlib.sha256(record.response_bytes).hexdigest(),
                origin_call_terminal_sha256=record.terminal.receipt_sha256,
                origin_review_sha256=batch_sha256_830_g3(
                    "g3-reused-review-output.830.v1", previous
                ),
                current_review_sha256=batch_sha256_830_g3(
                    "g3-reused-review-output.830.v1", rebound
                ),
                observed_usage=record.observed_usage,
            )
        )
    origin_status = origin.terminal.status
    if origin_status not in ("SUCCESS", "FAILED"):
        raise ValueError("review reuse origin terminal status is invalid")
    payload = dict(
        contract=CONTRACT,
        current_request_sha256=current_request.request_sha256,
        current_output_sha256=compile_output_hash_g3(current_output),
        origin_admission_digest=origin_admission_digest,
        origin_request_sha256=origin.request.request_sha256,
        origin_output_sha256=compile_output_hash_g3(origin.output),
        origin_chain_manifest_hash=origin.plan.chain_manifest_hash,
        origin_parent_authorization_digest=origin.plan.parent_authorization_digest,
        origin_stage_terminal_sha256=origin.terminal.receipt_sha256,
        origin_stage_status=origin_status,
        entries=tuple(entries),
    )
    return G3ReviewResultReuseV1.model_validate(
        {**payload, "receipt_sha256": batch_sha256_830_g3(CONTRACT, payload)}
    ), outputs


def build_review_result_reuse(
    *,
    origin_admission_digest: str,
    current_request: BatchConceptCompileRequest830G3V1,
    current_output: CompileOutput,
    origin_call_ids: Sequence[str] | None = None,
    admission_root: str | Path | None = None,
    ledger_root: str | Path | None = None,
) -> G3ReviewResultReuseV1:
    origin = _load_origin_review(
        origin_admission_digest, admission_root=admission_root, ledger_root=ledger_root
    )
    return _derive(
        origin_admission_digest, origin, current_request, current_output, origin_call_ids
    )[0]


def normalize_review_reuse(value: object) -> tuple[G3ReviewResultReuseV1, ...]:
    items = value if isinstance(value, (tuple, list)) else (value,)
    result = tuple(G3ReviewResultReuseV1.model_validate(item) for item in items)
    if not result or len({row.receipt_sha256 for row in result}) != len(result):
        raise ValueError("review reuse manifests empty or duplicated")
    return result


def derive_remaining_review_windows(
    request: BatchConceptCompileRequest830G3V1,
    output: CompileOutput,
    reuse: object,
) -> tuple[G3DReviewWindow, ...]:
    from . import g3_bounded_model_execution as runtime

    windows = runtime.derive_gemini_d_review_windows(request, output)
    all_ids = {window["window_id"] for window in windows}
    selected: list[str] = []
    for manifest in normalize_review_reuse(reuse):
        if (
            manifest.current_request_sha256 != request.request_sha256
            or manifest.current_output_sha256 != compile_output_hash_g3(output)
        ):
            raise ValueError("review reuse current binding mismatch")
        selected.extend(entry.current_window_id for entry in manifest.entries)
    if len(set(selected)) != len(selected) or not set(selected) <= all_ids:
        raise ValueError("review reuse windows foreign or duplicated")
    return tuple(window for window in windows if window["window_id"] not in set(selected))


def validate_review_result_reuse(
    receipt: object,
    *,
    current_request: BatchConceptCompileRequest830G3V1,
    current_output: CompileOutput,
    current_identity: ModelIdentity | None = None,
    admission_root: str | Path | None = None,
    ledger_root: str | Path | None = None,
) -> dict[str, ReviewOutput]:
    manifests = normalize_review_reuse(receipt)
    derive_remaining_review_windows(current_request, current_output, manifests)
    outputs: dict[str, ReviewOutput] = {}
    for manifest in manifests:
        origin = _load_origin_review(
            manifest.origin_admission_digest, admission_root=admission_root, ledger_root=ledger_root
        )
        rebuilt, projected = _derive(
            manifest.origin_admission_digest,
            origin,
            current_request,
            current_output,
            tuple(entry.origin_call_id for entry in manifest.entries),
            current_identity,
        )
        if rebuilt != manifest:
            raise ValueError("review reuse original receipt binding mismatch")
        outputs.update(projected)
    return outputs


def aggregate_reused_review_outputs(
    request: BatchConceptCompileRequest830G3V1,
    output: CompileOutput,
    *,
    new_outputs: Sequence[ReviewOutput],
    reused: Mapping[str, ReviewOutput],
) -> ReviewOutput:
    from . import g3_bounded_model_execution as runtime

    windows = runtime.derive_gemini_d_review_windows(request, output)
    if not set(reused) <= {window["window_id"] for window in windows}:
        raise ValueError("review reuse aggregate contains foreign window")
    if len(new_outputs) + len(reused) != len(windows):
        raise ValueError("review reuse aggregate output count mismatch")
    iterator = iter(new_outputs)
    ordered = tuple(
        reused[window["window_id"]] if window["window_id"] in reused else next(iterator)
        for window in windows
    )
    return runtime.aggregate_gemini_d_review_window_outputs(request, output, ordered)
