"""Reproducible local projections of immutable D call evidence; no transport authority."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from insurance_harness.model_policy import g3_bounded_gateway as gateway
from insurance_harness.run_admission.g3_models import (
    G3BoundedApprovalEnvelopeV1,
    G3ModelProcessingAuthorizationEnvelopeV1,
    G3ProviderUsageV1,
    G3UsageTotalsV1,
    canonical_json,
)

from .batch_canonical_830_g3 import batch_sha256_830_g3
from .batch_concept_compile_830_g3 import (
    BatchConceptCompileRequest830G3V1,
    Hash,
    compile_request_hash_g3,
)
from .concept_compile_830_g2 import CompileOutput
from .g3_field_tasks import _source_scope, adapt_catalog_field_tasks

VALIDATOR_VERSION = "g3-d-recorded-projection-validator.830.v1"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class G3DProjectionSelectionV1(_Frozen):
    origin_call_id: str
    field_keys: tuple[str, ...] = ()
    include_synthesis: bool = False

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if (
            not self.origin_call_id
            or self.field_keys != tuple(sorted(set(self.field_keys)))
            or bool(self.field_keys) == self.include_synthesis
        ):
            raise ValueError("recorded projection selection must be explicit and unique")
        return self


class G3DProjectionReuseEntryV1(G3DProjectionSelectionV1):
    origin_window_id: str
    entity_id: str
    task_sha256s: tuple[Hash, ...]
    entity_scope_sha256: Hash
    origin_chain_manifest_hash: Hash
    origin_parent_authorization_digest: Hash
    origin_request_body_sha256: Hash
    origin_response_body_sha256: Hash
    origin_terminal_receipt_sha256: Hash
    origin_terminal_status: Literal["SUCCESS", "FAILED"]
    origin_projection_sha256: Hash
    current_projection_sha256: Hash
    observed_usage: G3ProviderUsageV1
    input_token_ceiling: int
    output_token_ceiling: int
    anomaly_codes: tuple[str, ...]


class G3DProjectionReuseManifestV1(_Frozen):
    contract: Literal["g3-d-projection-reuse.830.v1"]
    current_request_sha256: Hash
    origin_admission_digest: Hash
    origin_request_sha256: Hash
    validator_version: Literal["g3-d-recorded-projection-validator.830.v1"]
    validator_sha256: Hash
    entries: tuple[G3DProjectionReuseEntryV1, ...]
    manifest_sha256: Hash

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if not self.entries or self.manifest_sha256 != batch_sha256_830_g3(
            self.contract, self.model_dump(exclude={"manifest_sha256"})
        ):
            raise ValueError("projection reuse manifest evidence/hash mismatch")
        return self


@dataclass(frozen=True, slots=True)
class G3DProjectionReuseResult:
    outputs: tuple[CompileOutput, ...]
    reused_task_sha256s: tuple[str, ...]
    origin_call_count: int
    historical_usage: G3UsageTotalsV1
    anomaly_codes: tuple[str, ...]


def validator_sha256() -> str:
    """Bind the actual local projection and verification implementation."""
    base = Path(__file__).parent
    paths = (
        Path(__file__),
        base / "g3_field_task_recovery.py",
        base / "g3_field_tasks.py",
        base / "g3_bounded_model_execution.py",
        Path(gateway.__file__),
    )
    return batch_sha256_830_g3(
        VALIDATOR_VERSION,
        {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
    )


def _read(path: Path, model, digest: str | None = None):
    raw = gateway._read_secure_ledger_file(path)
    if digest is not None and hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("projection reuse origin artifact digest mismatch")
    value = model.model_validate_json(raw)
    if raw != canonical_json(value.model_dump(mode="json", round_trip=True)):
        raise ValueError("projection reuse noncanonical origin artifact")
    return value


def _load_origin(origin_admission_digest: str, admission_root=None):
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
    # Historical signatures authenticate evidence only. Current admission grants all new calls.
    verify_parent_authorization(load_g3_root_trust_policy(), parent)
    verify_delegated_stage_signature(parent, approval)
    validate_g3_parent_scope(parent.payload, plan)
    if plan.stage != "D_COMPILE":
        raise ValueError("projection reuse requires original D compile admission")
    refs = [
        r
        for r in plan.eligibility_lock.input_artifacts
        if r.contract == "batch-concept-compile-request.830.g3.v1"
    ]
    if len(refs) != 1:
        raise ValueError("projection reuse original request reference is ambiguous")
    ref = refs[0]
    # The signed ref selects the exact file; an export changes only the store root.
    original_path = Path(ref.artifact_ref)
    if (
        original_path.parent.name != ref.sha256
        or original_path.parent.parent.name != "sha256"
        or ref not in plan.provenance_lock.artifacts
        or ref not in plan.rights_lock.artifacts
    ):
        raise ValueError("projection reuse original request custody mismatch")
    path = root / "sha256" / ref.sha256 / original_path.name
    request = _read(path, BatchConceptCompileRequest830G3V1, ref.sha256)
    if path.stat().st_size != ref.bytes:
        raise ValueError("projection reuse original request byte count mismatch")
    return plan, request


def _entity_scope(request, entity_id):
    bindings = [b for b in request.entity_bindings if b.entity_id == entity_id]
    if len(bindings) != 1:
        raise ValueError("projection reuse entity is not currently bound")
    binding = bindings[0]
    # Scoped to this entity; unrelated additions to the batch do not invalidate old tasks.
    attributes = (
        "entity_id",
        "entity_version",
        "entity_key_sha256",
        "version_candidate_key_sha256",
        "display_name",
        "issuer",
        "product_code",
        "version_label",
        "schema_pack_id",
        "schema_version",
        "schema_pack_sha256",
        "profile_id",
        "profile_version",
        "profile_sha256",
        "required_fields",
        "source_material_ids",
    )
    return batch_sha256_830_g3(
        "g3-reuse-entity-scope.830.v1",
        {
            "binding": {key: getattr(binding, key) for key in attributes},
            "sources": _source_scope(request, binding.source_material_ids),
        },
    )


def _derive(
    *, plan, origin_request, current_request, origin_admission_digest, selections, ledger_root=None
):
    from .g3_bounded_model_execution import derive_gemini_d_compile_windows
    from .g3_field_task_recovery import project_g3_recorded_compile_subset

    windows = {w["window_id"]: w for w in derive_gemini_d_compile_windows(origin_request)}
    calls = {c.call_id: c for c in plan.request_manifest.calls}
    old_tasks = {(t.entity_id, t.field_key): t for t in adapt_catalog_field_tasks(origin_request)}
    new_tasks = {(t.entity_id, t.field_key): t for t in adapt_catalog_field_tasks(current_request)}
    entries, outputs, records, seen = [], [], {}, set()
    for selection in selections:
        selection = G3DProjectionSelectionV1.model_validate(selection)
        call = calls.get(selection.origin_call_id)
        if call is None or call.window_id not in windows:
            raise ValueError("projection reuse origin call/window not in signed plan")
        window = windows[call.window_id]
        entity_id = str(window["entity_id"])
        if tuple(window["material_ids"]) != call.material_ids:
            raise ValueError("projection reuse source window mismatch")
        old_scope = _entity_scope(origin_request, entity_id)
        if old_scope != _entity_scope(current_request, entity_id):
            raise ValueError("projection reuse entity/catalog/source dependency changed")
        task_hashes = []
        targets = selection.field_keys or ("__synthesis__",)
        for key in targets:
            if (entity_id, key) in seen:
                raise ValueError("projection reuse duplicate selected task")
            seen.add((entity_id, key))
            if key != "__synthesis__":
                old, current = old_tasks.get((entity_id, key)), new_tasks.get((entity_id, key))
                if old is None or current is None or old.task_sha256 != current.task_sha256:
                    raise ValueError("projection reuse stable FieldTask dependency changed")
                task_hashes.append(old.task_sha256)
        if call.call_id not in records:
            records[call.call_id] = gateway.read_g3_recorded_call(
                plan=plan,
                call=call,
                admission_artifact_digest=origin_admission_digest,
                ledger_root=Path(ledger_root) if ledger_root is not None else None,
            )
        recorded = records[call.call_id]
        output = project_g3_recorded_compile_subset(
            recorded.semantic_bytes,
            origin_request,
            window,
            field_keys=selection.field_keys,
            include_synthesis=selection.include_synthesis,
        )
        rebound = CompileOutput.model_validate(
            {
                **output.model_dump(),
                "request_hash": compile_request_hash_g3(current_request.base_request),
            }
        )
        terminal = recorded.terminal
        entries.append(
            G3DProjectionReuseEntryV1(
                **selection.model_dump(),
                origin_window_id=call.window_id,
                entity_id=entity_id,
                task_sha256s=tuple(task_hashes),
                entity_scope_sha256=old_scope,
                origin_chain_manifest_hash=plan.chain_manifest_hash,
                origin_parent_authorization_digest=plan.parent_authorization_digest,
                origin_request_body_sha256=call.request_body_sha256,
                origin_response_body_sha256=hashlib.sha256(recorded.response_bytes).hexdigest(),
                origin_terminal_receipt_sha256=terminal.receipt_sha256,
                origin_terminal_status=terminal.status,
                origin_projection_sha256=batch_sha256_830_g3(
                    "g3-reused-compile-output.830.v1", output
                ),
                current_projection_sha256=batch_sha256_830_g3(
                    "g3-reused-compile-output.830.v1", rebound
                ),
                observed_usage=recorded.observed_usage,
                input_token_ceiling=call.input_token_ceiling,
                output_token_ceiling=call.output_token_ceiling,
                anomaly_codes=recorded.anomaly_codes,
            )
        )
        outputs.append(rebound)
    usage = [r.observed_usage for r in records.values()]
    result = G3DProjectionReuseResult(
        outputs=tuple(outputs),
        reused_task_sha256s=tuple(sorted(t for e in entries for t in e.task_sha256s)),
        origin_call_count=len(records),
        historical_usage=G3UsageTotalsV1(
            successful_usage_records=sum(r.terminal.status == "SUCCESS" for r in records.values()),
            prompt_tokens=sum(u.prompt_tokens for u in usage),
            completion_tokens=sum(u.completion_tokens for u in usage),
            total_tokens=sum(u.total_tokens for u in usage),
        ),
        anomaly_codes=tuple(sorted({code for r in records.values() for code in r.anomaly_codes})),
    )
    return tuple(entries), result


def build_d_projection_reuse_manifest(
    *,
    origin_request,
    current_request,
    origin_admission_digest,
    selections,
    ledger_root=None,
    admission_root=None,
):
    plan, recorded_request = _load_origin(origin_admission_digest, admission_root)
    if origin_request != recorded_request:
        raise ValueError("projection reuse supplied original request is not signed origin")
    entries, _ = _derive(
        plan=plan,
        origin_request=recorded_request,
        current_request=current_request,
        origin_admission_digest=origin_admission_digest,
        selections=selections,
        ledger_root=ledger_root,
    )
    payload = dict(
        contract="g3-d-projection-reuse.830.v1",
        current_request_sha256=current_request.request_sha256,
        origin_admission_digest=origin_admission_digest,
        origin_request_sha256=recorded_request.request_sha256,
        validator_version=VALIDATOR_VERSION,
        validator_sha256=validator_sha256(),
        entries=entries,
    )
    return G3DProjectionReuseManifestV1.model_validate(
        {**payload, "manifest_sha256": batch_sha256_830_g3(payload["contract"], payload)}
    )


def validate_d_projection_reuse(
    manifest, *, current_request, ledger_root=None, admission_root=None
):
    manifest = G3DProjectionReuseManifestV1.model_validate(manifest)
    if (
        manifest.current_request_sha256 != current_request.request_sha256
        or manifest.validator_sha256 != validator_sha256()
    ):
        raise ValueError("projection reuse current request/validator mismatch")
    plan, origin = _load_origin(manifest.origin_admission_digest, admission_root)
    if origin.request_sha256 != manifest.origin_request_sha256:
        raise ValueError("projection reuse original request mismatch")
    selections = tuple(
        G3DProjectionSelectionV1(
            origin_call_id=e.origin_call_id,
            field_keys=e.field_keys,
            include_synthesis=e.include_synthesis,
        )
        for e in manifest.entries
    )
    entries, result = _derive(
        plan=plan,
        origin_request=origin,
        current_request=current_request,
        origin_admission_digest=manifest.origin_admission_digest,
        selections=selections,
        ledger_root=ledger_root,
    )
    if entries != manifest.entries:
        raise ValueError("projection reuse original evidence/projection mismatch")
    return result
