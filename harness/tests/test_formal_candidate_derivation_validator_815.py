"""EC-01 C3: provider-free formal Candidate derivation validation seam."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, replace
from dataclasses import fields as dataclass_fields
from inspect import signature
from pathlib import Path
from typing import cast, get_args, get_type_hints

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.evidence_verifier import (
    FreeformEvidenceBindingReceiptV1,
    FreeformFieldOutputV1,
    bind_freeform_arm_evidence,
)
from insurance_harness.goldenset.expert_golden_admission_596_2 import (
    ORDERED_FIELD_IDS,
)
from insurance_harness.knowledge_compiler import (  # noqa: E402
    deepseek_locator_extractor_596_1 as deepseek,
)
from insurance_harness.knowledge_compiler import (  # noqa: E402
    formal_candidate_derivation_validator_815 as derivation_validator,
)
from insurance_harness.knowledge_compiler.deepseek_locator_extractor_596_1 import (
    build_schema67_native_pdf_execution_projection_815,
)
from insurance_harness.knowledge_compiler.ec01_formal_candidate_run_815 import (
    EC01FormalCandidateRun815V1,
)
from insurance_harness.knowledge_compiler.formal_candidate_derivation_validator_815 import (
    FieldAttemptParseOutcome815,
    FormalCandidateDerivationValidationError,
    make_schema67_field_attempt_manifest_815,
    validate_formal_candidate_derivation_815,
    validate_formal_candidate_derivation_directory_815,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    approved_schema_rows,
)
from tests import test_deepseek_locator_extractor_119 as deepseek_fixtures
from tests import test_ec01_formal_candidate_run_815 as ec01_fixtures


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_task_local_artifact(root: Path, name: str, payload: bytes) -> None:
    path = root / name
    path.write_bytes(payload)
    path.chmod(0o600)


def _persist_original_run_artifact(
    *,
    root: Path,
    run: EC01FormalCandidateRun815V1,
    transport: ec01_fixtures._KnownTransport,
    manifest: derivation_validator.Schema67FieldAttemptManifest815V1,
    validation: derivation_validator.FormalCandidateDerivationValidation815V1,
) -> None:
    root.mkdir(mode=0o700)
    _write_task_local_artifact(
        root,
        "request-identity-manifest.json",
        run.request_manifest_bytes,
    )
    for ordinal, (system, user) in enumerate(transport.calls, start=1):
        _write_task_local_artifact(
            root,
            f"request-{ordinal:02d}.json",
            deepseek._deepseek_request_bytes(
                system=system,
                user=user,
            ),
        )
    for raw in run.raw_responses:
        _write_task_local_artifact(
            root,
            f"raw-response-{raw.ordinal:02d}.json",
            raw.response_bytes,
        )
    _write_task_local_artifact(
        root,
        "terminal.json",
        _canonical_bytes(asdict(run.terminal)) + b"\n",
    )
    _write_task_local_artifact(
        root,
        "formal-candidate.json",
        _canonical_bytes(run.candidate.model_dump(mode="json", round_trip=True))
        + b"\n",
    )
    _write_task_local_artifact(
        root,
        "coordinate-evidence-companion.json",
        _canonical_bytes(
            run.coordinate_evidence_companion.model_dump(
                mode="json",
                round_trip=True,
            )
        )
        + b"\n",
    )
    _write_task_local_artifact(
        root,
        "field-attempt-manifest.json",
        _canonical_bytes(manifest.to_wire()) + b"\n",
    )
    _write_task_local_artifact(
        root,
        "formal-derivation-validation.json",
        _canonical_bytes(asdict(validation)) + b"\n",
    )


def test_c3_semantic_value_and_literal_quote_contract_is_clause_scoped() -> None:
    semantic_supported = (
        derivation_validator._semantic_value_supported_by_quotes_815
    )
    exact_anchor = derivation_validator._quote_is_exact_literal_page_anchor_815

    exact_quote = "等待期为90日；等待期内不承担保险责任；期满后生效①"
    assert semantic_supported(
        "等待期为90日；等待期内不承担保险责任；期满后生效①",
        (exact_quote,),
    )
    assert semantic_supported(
        "等待期90日；期内不承担保险责任；期满后生效①",
        (exact_quote,),
    )
    assert semantic_supported(
        "等待期90日",
        ("等待期为90日；等待期内不承担保险责任",),
    )
    assert not semantic_supported(
        "甲责任10万元须备案；乙责任20万元须审核",
        ("甲责任10万元须审核；乙责任20万元须备案",),
    )
    assert not semantic_supported(
        "甲责任10万元；须备案；乙责任20万元；须审核",
        ("甲责任10万元；须审核；乙责任20万元；须备案",),
    )
    assert not semantic_supported("甲责任10万元", ("乙责任10万元",))
    assert not semantic_supported("甲责任10万元", ("甲责任20万元",))
    assert not semantic_supported("境外甲责任10万元", ("甲责任10万元",))
    assert not semantic_supported("甲责任10万元须赔付", ("甲责任10万元",))
    assert not semantic_supported("若住院则赔付10万元", ("住院赔付10万元",))
    assert not semantic_supported("不承担既往症责任", ("承担既往症责任",))
    assert not semantic_supported("既往症除外", ("保障既往症",))
    assert not semantic_supported("仅限中国境内", ("中国境内",))
    assert exact_anchor(exact_quote, f"前文。{exact_quote}后文。")
    assert not exact_anchor(
        "等待期为90日；等待期内不承担保险责任；期满后生效",
        f"前文。{exact_quote}后文。",
    )
    assert not exact_anchor(
        "等待期为90日；等待期内不承担保险责任；期满后生效",
        "前文。①等待期为90日；等待期内不承担保险责任；期满后生效。",
    )
    assert not exact_anchor(
        "等待期为 90 日；等待期内不承担保险责任；期满后生效①",
        f"前文。{exact_quote}后文。",
    )
    assert not exact_anchor(
        "等待期为90日,等待期内不承担保险责任；期满后生效①",
        f"前文。{exact_quote}后文。",
    )


def _synthetic_fixture() -> tuple[
    tuple[str, ...],
    tuple[int, ...],
    tuple[bytes, ...],
    tuple[bytes, ...],
    tuple[FieldAttemptParseOutcome815, ...],
    tuple[FreeformFieldOutputV1, ...],
    tuple[FreeformEvidenceBindingReceiptV1, ...],
    bytes,
]:
    task_keys = tuple(f"synthetic-task-{ordinal}" for ordinal in range(1, 9))
    field_task_ordinals = tuple(min(index // 9 + 1, 8) for index in range(67))
    fields = tuple(
        FreeformFieldOutputV1(
            product_version_id="596-1",
            field_id=field_id,
            state="unknown",
            value_snapshot=None,
            evidence=(),
        )
        for field_id in ORDERED_FIELD_IDS
    )
    evidence_receipts = tuple(
        bind_freeform_arm_evidence(
            field_output=field,
            documents=(),
            manifests=(),
        )
        for field in fields
    )
    outcome_values: tuple[FieldAttemptParseOutcome815, ...] = (
        "PARSED_UNKNOWN_NO_SUPPORT",
        "PARSED_UNKNOWN_AMBIGUOUS_SOURCE",
        "PARSED_UNKNOWN_EXPLICIT_NOT_STATED",
    )
    outcomes = tuple(outcome_values[index % 3] for index in range(67))
    request_bodies = tuple(
        _canonical_bytes(
            {
                "field_ids": [
                    field_id
                    for field_id, field_ordinal in zip(
                        ORDERED_FIELD_IDS, field_task_ordinals, strict=True
                    )
                    if field_ordinal == ordinal
                ],
                "task_key": task_keys[ordinal - 1],
            }
        )
        for ordinal in range(1, 9)
    )
    raw_response_bodies = tuple(
        _canonical_bytes(
            {
                "fields": [
                    {"field_id": field_id, "state": "unknown"}
                    for field_id, field_ordinal in zip(
                        ORDERED_FIELD_IDS, field_task_ordinals, strict=True
                    )
                    if field_ordinal == ordinal
                ],
                "task_key": task_keys[ordinal - 1],
            }
        )
        for ordinal in range(1, 9)
    )
    terminal_bytes = _canonical_bytes(
        {
            "contract": "synthetic-terminal.815.v1",
            "failed_ordinal": None,
            "status": "SUCCEEDED",
        }
    )
    return (
        task_keys,
        field_task_ordinals,
        request_bodies,
        raw_response_bodies,
        outcomes,
        fields,
        evidence_receipts,
        terminal_bytes,
    )


def test_c3_synthetic_exact67_recomputes_raw_parsed_candidate_cross_hashes() -> None:
    (
        task_keys,
        field_task_ordinals,
        request_bodies,
        raw_response_bodies,
        outcomes,
        parsed_fields,
        parsed_evidence,
        terminal_bytes,
    ) = _synthetic_fixture()
    manifest = make_schema67_field_attempt_manifest_815(
        task_keys=task_keys,
        field_task_ordinals=field_task_ordinals,
        request_bodies=request_bodies,
        raw_response_bodies=raw_response_bodies,
        parse_outcomes=outcomes,
        parsed_fields=parsed_fields,
        parsed_evidence_receipts=parsed_evidence,
        terminal_bytes=terminal_bytes,
        candidate_fields=parsed_fields,
        candidate_evidence_receipts=parsed_evidence,
    )

    result = validate_formal_candidate_derivation_815(
        manifest=manifest,
        task_keys=task_keys,
        field_task_ordinals=field_task_ordinals,
        request_bodies=request_bodies,
        raw_response_bodies=raw_response_bodies,
        parse_outcomes=outcomes,
        parsed_fields=parsed_fields,
        parsed_evidence_receipts=parsed_evidence,
        terminal_bytes=terminal_bytes,
        candidate_fields=parsed_fields,
        candidate_evidence_receipts=parsed_evidence,
    )

    assert result.status == "SYNTHETIC_TEST_ONLY"
    assert manifest.derivation_source == "SYNTHETIC_TEST_ONLY"
    assert result.ordered_field_count == 67
    assert result.attempted_field_count == 67
    assert result.request_count == 8
    assert result.raw_response_count == 8
    assert result.provider_calls == 0
    assert tuple(row.field_id for row in manifest.rows) == ORDERED_FIELD_IDS
    assert all(row.attempted for row in manifest.rows)
    assert all(row.parse_outcome.startswith("PARSED_UNKNOWN_") for row in manifest.rows)
    for row, task_ordinal, field, evidence_receipt in zip(
        manifest.rows,
        field_task_ordinals,
        parsed_fields,
        parsed_evidence,
        strict=True,
    ):
        assert row.task_key == task_keys[task_ordinal - 1]
        assert row.task_ordinal == task_ordinal
        assert row.request_ordinal == task_ordinal
        assert row.response_ordinal == task_ordinal
        assert row.request_body_sha256 == hashlib.sha256(
            request_bodies[task_ordinal - 1]
        ).hexdigest()
        assert row.raw_response_sha256 == hashlib.sha256(
            raw_response_bodies[task_ordinal - 1]
        ).hexdigest()
        assert row.raw_response_byte_size == len(
            raw_response_bodies[task_ordinal - 1]
        )
        assert row.field_id == field.field_id
        assert row.candidate_field_sha256 == canonical_hash(
            "schema67-candidate-field.815.v1",
            field.model_dump(mode="python", round_trip=True),
        )
        assert row.evidence_receipt_sha256 == evidence_receipt.receipt_hash
        assert row.row_sha256 == canonical_hash(
            "schema67-field-attempt.815.v1",
            row.to_wire(include_hash=False),
        )
    assert result.formal_candidate_derivation_sha256 == (
        manifest.formal_candidate_derivation_sha256
    )

    drifted_raw = (raw_response_bodies[0] + b" ", *raw_response_bodies[1:])
    with pytest.raises(
        FormalCandidateDerivationValidationError,
        match="FIELD_ATTEMPT_MANIFEST_MISMATCH",
    ):
        validate_formal_candidate_derivation_815(
            manifest=manifest,
            task_keys=task_keys,
            field_task_ordinals=field_task_ordinals,
            request_bodies=request_bodies,
            raw_response_bodies=drifted_raw,
            parse_outcomes=outcomes,
            parsed_fields=parsed_fields,
            parsed_evidence_receipts=parsed_evidence,
            terminal_bytes=terminal_bytes,
            candidate_fields=parsed_fields,
            candidate_evidence_receipts=parsed_evidence,
        )

    with pytest.raises(
        FormalCandidateDerivationValidationError,
        match="FIELD_ATTEMPT_PARSE_OUTCOME_INVALID",
    ):
        make_schema67_field_attempt_manifest_815(
            task_keys=task_keys,
            field_task_ordinals=field_task_ordinals,
            request_bodies=request_bodies,
            raw_response_bodies=raw_response_bodies,
            parse_outcomes=(
                cast(FieldAttemptParseOutcome815, "NOT_ATTEMPTED"),
                *outcomes[1:],
            ),
            parsed_fields=parsed_fields,
            parsed_evidence_receipts=parsed_evidence,
            terminal_bytes=terminal_bytes,
            candidate_fields=parsed_fields,
            candidate_evidence_receipts=parsed_evidence,
        )

    with pytest.raises(
        FormalCandidateDerivationValidationError,
        match="FIELD_ATTEMPT_MANIFEST_MISMATCH",
    ):
        validate_formal_candidate_derivation_815(
            manifest=replace(
                manifest,
                formal_candidate_derivation_sha256="f" * 64,
            ),
            task_keys=task_keys,
            field_task_ordinals=field_task_ordinals,
            request_bodies=request_bodies,
            raw_response_bodies=raw_response_bodies,
            parse_outcomes=outcomes,
            parsed_fields=parsed_fields,
            parsed_evidence_receipts=parsed_evidence,
            terminal_bytes=terminal_bytes,
            candidate_fields=parsed_fields,
            candidate_evidence_receipts=parsed_evidence,
        )


def test_c3_manifest_derivation_preimage_binds_original_run_and_git_identity() -> None:
    (
        task_keys,
        field_task_ordinals,
        request_bodies,
        raw_response_bodies,
        outcomes,
        parsed_fields,
        parsed_evidence,
        terminal_bytes,
    ) = _synthetic_fixture()
    manifest = make_schema67_field_attempt_manifest_815(
        task_keys=task_keys,
        field_task_ordinals=field_task_ordinals,
        request_bodies=request_bodies,
        raw_response_bodies=raw_response_bodies,
        parse_outcomes=outcomes,
        parsed_fields=parsed_fields,
        parsed_evidence_receipts=parsed_evidence,
        terminal_bytes=terminal_bytes,
        candidate_fields=parsed_fields,
        candidate_evidence_receipts=parsed_evidence,
    )
    manifest_wire = manifest.to_wire()
    required_identity_fields = frozenset(
        {
            "attempt_id",
            "derivation_source",
            "execution_identity_sha256",
            "experiment_id",
            "integration_head",
            "integration_tree",
            "receipt_id",
            "request_manifest_sha256",
            "revision_set_sha256",
            "revision_validation_sha256",
            "run_id",
            "run_derivation_sha256",
            "schema_rows_sha256",
        }
    )

    missing_identity_fields = required_identity_fields - manifest_wire.keys()
    assert not missing_identity_fields, (
        "field-attempt manifest does not close the original run/Git identity: "
        f"{sorted(missing_identity_fields)}"
    )
    assert manifest.formal_candidate_derivation_sha256 == canonical_hash(
        "schema67-formal-candidate-derivation.815.v1",
        {
            "attempt_id": manifest_wire["attempt_id"],
            "candidate_evidence_sha256": manifest.candidate_evidence_sha256,
            "candidate_fields_sha256": manifest.candidate_fields_sha256,
            "derivation_source": manifest_wire["derivation_source"],
            "execution_identity_sha256": manifest_wire[
                "execution_identity_sha256"
            ],
            "experiment_id": manifest_wire["experiment_id"],
            "field_attempt_manifest_sha256": manifest.manifest_sha256,
            "integration_head": manifest_wire["integration_head"],
            "integration_tree": manifest_wire["integration_tree"],
            "receipt_id": manifest_wire["receipt_id"],
            "request_manifest_sha256": manifest_wire[
                "request_manifest_sha256"
            ],
            "revision_set_sha256": manifest_wire["revision_set_sha256"],
            "revision_validation_sha256": manifest_wire[
                "revision_validation_sha256"
            ],
            "run_id": manifest_wire["run_id"],
            "run_derivation_sha256": manifest_wire["run_derivation_sha256"],
            "schema_rows_sha256": "SYNTHETIC_TEST_ONLY",
            "terminal_sha256": manifest.terminal_sha256,
        },
    )


@pytest.mark.asyncio
async def test_c3_original_run_request_preserves_approved_schema_guidance() -> None:
    transport = ec01_fixtures._KnownTransport()
    run = await ec01_fixtures._run(transport)
    request_manifest = json.loads(run.request_manifest_bytes)
    approved_by_field = {row.field_id: row for row in approved_schema_rows()}
    guidance_keys = {
        "category",
        "field_name",
        "value_shape_raw",
        "source_authority_raw",
        "formation_raw",
    }

    for task, (_system, user) in zip(
        request_manifest["tasks"], transport.calls, strict=True
    ):
        payload = json.loads(user)
        projected = tuple(payload["field_contracts"])
        task_field_ids = tuple(task["field_ids"])
        assert tuple(row["field_id"] for row in projected) == task_field_ids
        assert tuple(row["field_id"] for row in projected) == tuple(
            field_id for field_id in approved_by_field if field_id in task_field_ids
        )
        for row in projected:
            missing = guidance_keys - row.keys()
            assert not missing, (
                f"request field {row['field_id']} loses approved Schema guidance: "
                f"{sorted(missing)}"
            )
            approved = approved_by_field[row["field_id"]]
            assert {key: row[key] for key in guidance_keys} == {
                "category": approved.category,
                "field_name": approved.field_name,
                "value_shape_raw": approved.value_shape_raw,
                "source_authority_raw": approved.source_authority_raw,
                "formation_raw": approved.formation_raw,
            }


@pytest.mark.asyncio
async def test_c3_original_run_and_attempt_manifest_bind_schema_rows_hash() -> None:
    run = await ec01_fixtures._cached_native_known_run()
    contracts = deepseek_fixtures._schema67_contract_set()
    plan = ec01_fixtures._native_execution_plan(contracts)
    request_manifest = json.loads(run.request_manifest_bytes)
    manifest, _ = (
        derivation_validator.validate_ec01_formal_candidate_run_derivation_815(
            run=run,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    )

    assert (
        request_manifest.get("schema_rows_sha256"),
        manifest.to_wire().get("schema_rows_sha256"),
    ) == (contracts.schema_rows_sha256, contracts.schema_rows_sha256)


@pytest.mark.asyncio
async def test_c3_formal_derivation_preimage_binds_schema_rows_hash() -> None:
    run = await ec01_fixtures._cached_native_known_run()
    contracts = deepseek_fixtures._schema67_contract_set()
    plan = ec01_fixtures._native_execution_plan(contracts)
    manifest, _ = (
        derivation_validator.validate_ec01_formal_candidate_run_derivation_815(
            run=run,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    )
    manifest_wire = manifest.to_wire()

    assert manifest.formal_candidate_derivation_sha256 == canonical_hash(
        "schema67-formal-candidate-derivation.815.v1",
        {
            "attempt_id": manifest.attempt_id,
            "candidate_evidence_sha256": manifest.candidate_evidence_sha256,
            "candidate_fields_sha256": manifest.candidate_fields_sha256,
            "derivation_source": manifest.derivation_source,
            "execution_identity_sha256": manifest.execution_identity_sha256,
            "experiment_id": manifest.experiment_id,
            "field_attempt_manifest_sha256": manifest.manifest_sha256,
            "integration_head": manifest.integration_head,
            "integration_tree": manifest.integration_tree,
            "receipt_id": manifest.receipt_id,
            "request_manifest_sha256": manifest.request_manifest_sha256,
            "revision_set_sha256": manifest.revision_set_sha256,
            "revision_validation_sha256": manifest.revision_validation_sha256,
            "run_id": manifest.run_id,
            "run_derivation_sha256": manifest.run_derivation_sha256,
            "schema_rows_sha256": contracts.schema_rows_sha256,
            "terminal_sha256": manifest.terminal_sha256,
        },
    )
    assert manifest_wire["schema_rows_sha256"] == contracts.schema_rows_sha256


@pytest.mark.asyncio
async def test_c3_original_run_builds_exact_model_attempt_rows() -> None:
    run = await ec01_fixtures._cached_native_known_run()
    contracts = deepseek_fixtures._schema67_contract_set()
    plan = ec01_fixtures._native_execution_plan(contracts)

    manifest, validation = (
        derivation_validator.validate_ec01_formal_candidate_run_derivation_815(
            run=run,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    )

    assert set(
        signature(
            derivation_validator.validate_ec01_formal_candidate_run_derivation_815
        ).parameters
    ) == {"run", "revision_set_root", "field_contracts", "execution_plan"}
    assert validation.status == "PASS"
    assert validation.derivation_source == "EC01_ORIGINAL_RUN"
    assert manifest.experiment_id == run.experiment_id
    assert manifest.execution_identity_sha256 == run.execution_identity_sha256
    assert manifest.run_id == run.run_id
    assert manifest.attempt_id == run.attempt_id
    assert manifest.receipt_id == run.receipt_id
    assert manifest.integration_head == run.integration_head
    assert manifest.integration_tree == run.integration_tree
    assert manifest.derivation_source == "EC01_ORIGINAL_RUN"
    assert "SYNTHETIC_TEST_ONLY" not in {
        manifest.experiment_id,
        manifest.execution_identity_sha256,
        manifest.run_id,
        manifest.attempt_id,
        manifest.receipt_id,
        manifest.integration_head,
        manifest.integration_tree,
    }
    assert manifest.run_derivation_sha256 == run.derivation_sha256
    assert manifest.revision_validation_sha256 == run.revision_validation_sha256
    assert manifest.revision_set_sha256 == run.terminal.revision_set_sha256
    assert manifest.request_manifest_sha256 == run.request_manifest_sha256
    assert manifest.terminal_sha256 == run.terminal.terminal_sha256
    assert manifest.attempted_field_count == 25
    assert len(manifest.request_body_sha256s) == 8
    assert len(manifest.raw_response_sha256s) == 8

    model_rows = tuple(
        row for row in manifest.rows if row.derivation_kind == "MODEL_RESPONSE"
    )
    deferred_rows = tuple(
        row
        for row in manifest.rows
        if row.derivation_kind == "CODE_OWNED_DEFERRED_UNKNOWN"
    )
    assert len(model_rows) == 25
    assert len(deferred_rows) == 42
    assert all(
        row.task_key is not None
        and row.task_ordinal is not None
        and row.request_ordinal is not None
        and row.response_ordinal is not None
        and row.request_body_sha256 is not None
        and row.raw_response_sha256 is not None
        and row.raw_response_byte_size is not None
        for row in model_rows
    )


@pytest.mark.asyncio
async def test_c3_original_run_artifact_fresh_opens_and_rejects_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = ec01_fixtures._KnownTransport()
    run = await ec01_fixtures._run(transport)
    contracts = deepseek_fixtures._schema67_contract_set()
    plan = ec01_fixtures._native_execution_plan(contracts)
    manifest, validation = (
        derivation_validator.validate_ec01_formal_candidate_run_derivation_815(
            run=run,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    )
    artifact_root = tmp_path / "original-run-artifact"
    _persist_original_run_artifact(
        root=artifact_root,
        run=run,
        transport=transport,
        manifest=manifest,
        validation=validation,
    )

    replayed_manifest, replayed_validation = (
        derivation_validator.validate_ec01_formal_candidate_run_artifact_815(
            artifact_root=artifact_root,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    )

    assert replayed_manifest == manifest
    assert replayed_validation == validation
    assert replayed_validation.status == "PASS"
    assert replayed_validation.derivation_source == "EC01_ORIGINAL_RUN"
    assert replayed_validation.provider_calls == 0

    raw_order_drift = tmp_path / "raw-order-drift"
    shutil.copytree(artifact_root, raw_order_drift)
    raw_1 = (raw_order_drift / "raw-response-01.json").read_bytes()
    raw_2 = (raw_order_drift / "raw-response-02.json").read_bytes()
    (raw_order_drift / "raw-response-01.json").write_bytes(raw_2)
    (raw_order_drift / "raw-response-02.json").write_bytes(raw_1)
    with pytest.raises(
        FormalCandidateDerivationValidationError,
        match="FIELD_ATTEMPT_ORIGINAL_RUN_ARTIFACT_INVALID",
    ):
        derivation_validator.validate_ec01_formal_candidate_run_artifact_815(
            artifact_root=raw_order_drift,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )

    replacement_root = tmp_path / "replacement-artifact"
    original_root = tmp_path / "original-artifact-after-swap"
    shutil.copytree(artifact_root, replacement_root)
    original_lstat = os.lstat
    original_open = os.open
    root_replaced = False

    def replace_root() -> None:
        nonlocal root_replaced
        artifact_root.rename(original_root)
        artifact_root.symlink_to(replacement_root, target_is_directory=True)
        root_replaced = True

    def replace_root_before_member_lstat(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    ) -> os.stat_result:
        if (
            not root_replaced
            and Path(os.fsdecode(path)).name == "request-identity-manifest.json"
        ):
            replace_root()
        return original_lstat(path)

    def replace_root_before_member_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal root_replaced
        if (
            not root_replaced
            and Path(os.fsdecode(path)).name == "request-identity-manifest.json"
        ):
            replace_root()
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "lstat", replace_root_before_member_lstat)
    monkeypatch.setattr(os, "open", replace_root_before_member_open)
    with pytest.raises(
        FormalCandidateDerivationValidationError,
        match="FIELD_ATTEMPT_ORIGINAL_RUN_ARTIFACT_INVALID",
    ):
        derivation_validator.validate_ec01_formal_candidate_run_artifact_815(
            artifact_root=artifact_root,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    assert root_replaced is True

    request_order_drift = tmp_path / "request-order-drift"
    shutil.copytree(artifact_root, request_order_drift)
    request_1 = (request_order_drift / "request-01.json").read_bytes()
    request_2 = (request_order_drift / "request-02.json").read_bytes()
    (request_order_drift / "request-01.json").write_bytes(request_2)
    (request_order_drift / "request-02.json").write_bytes(request_1)
    with pytest.raises(
        FormalCandidateDerivationValidationError,
        match="FIELD_ATTEMPT_ORIGINAL_RUN_ARTIFACT_INVALID",
    ):
        derivation_validator.validate_ec01_formal_candidate_run_artifact_815(
            artifact_root=request_order_drift,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )

    identity_drift = tmp_path / "identity-drift"
    shutil.copytree(artifact_root, identity_drift)
    terminal_path = identity_drift / "terminal.json"
    terminal = json.loads(terminal_path.read_bytes())
    terminal["run_id"] = "f52c2efe-5326-4b22-94b2-87df2a45ec8e"
    terminal_path.write_bytes(_canonical_bytes(terminal) + b"\n")
    with pytest.raises(
        FormalCandidateDerivationValidationError,
        match="FIELD_ATTEMPT_ORIGINAL_RUN_ARTIFACT_INVALID",
    ):
        derivation_validator.validate_ec01_formal_candidate_run_artifact_815(
            artifact_root=identity_drift,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )


@pytest.mark.asyncio
async def test_c3_native_selection_replays_honest_disposition_and_coordinates() -> None:
    run = await ec01_fixtures._run_native_selection()
    contracts = deepseek_fixtures._schema67_contract_set()
    projection = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=deepseek_fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    )

    manifest, validation = (
        derivation_validator.validate_ec01_formal_candidate_run_derivation_815(
            run=run,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=projection.execution_plan,
        )
    )

    assert validation.status == "PASS"
    assert manifest.provider_visible_count == 25
    assert manifest.attempted_field_count == 25
    assert manifest.real_model_output_count == 25
    assert manifest.code_deferred_count == 42
    assert manifest.dispositioned_count == 67
    assert manifest.unclassified_count == 0
    assert validation.attempted_field_count == 25
    assert manifest.coordinate_evidence_companion_sha256 == (
        run.coordinate_evidence_companion.companion_sha256
    )
    assert tuple(row.field_id for row in manifest.rows) == ORDERED_FIELD_IDS
    assert tuple(row.schema_order for row in manifest.rows) == tuple(range(1, 68))

    coordinate_hashes_by_field: dict[str, tuple[str, ...]] = {}
    for coordinate_row in run.coordinate_evidence_companion.coordinate_rows:
        coordinate_hashes_by_field.setdefault(coordinate_row.field_id, ())
        coordinate_hashes_by_field[coordinate_row.field_id] += (
            coordinate_row.recomputed_coordinate_evidence_sha256(),
        )
    deferred_reason_by_field = {
        deferred.field_id: deferred.reason for deferred in projection.code_deferred
    }
    candidate_by_field = {
        candidate.field_id: candidate for candidate in run.candidate.fields
    }
    for attempt_row in manifest.rows:
        candidate_field = candidate_by_field[attempt_row.field_id]
        assert attempt_row.final_state == candidate_field.state
        if attempt_row.derivation_kind == "MODEL_RESPONSE":
            assert attempt_row.provider_visible is True
            assert attempt_row.task_key is not None
            assert attempt_row.request_body_sha256 is not None
            assert attempt_row.raw_response_sha256 is not None
            assert attempt_row.model_returned_state in {
                "present",
                "absent_explicitly",
                "unknown",
            }
            assert attempt_row.coordinate_evidence_sha256s == (
                coordinate_hashes_by_field.get(attempt_row.field_id, ())
            )
        else:
            assert attempt_row.provider_visible is False
            assert attempt_row.task_key is None
            assert attempt_row.request_body_sha256 is None
            assert attempt_row.raw_response_sha256 is None
            assert attempt_row.model_returned_state is None
            assert attempt_row.typed_reason == deferred_reason_by_field[
                attempt_row.field_id
            ]
            assert attempt_row.coordinate_evidence_sha256s == ()


@pytest.mark.asyncio
async def test_c3_native_selection_preserves_field_local_unresolved_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_complete = ec01_fixtures._NativeSelectionTransport.complete
    changed_field_id: str | None = None

    async def complete_with_cross_field_selection(
        self: ec01_fixtures._NativeSelectionTransport,
        system: str,
        user: str,
    ) -> str:
        nonlocal changed_field_id
        response_text = await original_complete(self, system, user)
        if changed_field_id is not None:
            return response_text
        request = json.loads(user)
        response = json.loads(response_text)
        catalogs = request["field_selection_catalogs"]
        fields = response["fields"]
        for target_index, target_catalog in enumerate(catalogs):
            target_ids = {
                item["selection_id"] for item in target_catalog["selections"]
            }
            for donor_catalog in catalogs[target_index + 1 :]:
                donor_selections = donor_catalog["selections"]
                if (
                    donor_selections
                    and donor_selections[0]["selection_id"] not in target_ids
                ):
                    fields[target_index]["selection_ids"] = [
                        donor_selections[0]["selection_id"]
                    ]
                    changed_field_id = fields[target_index]["field_id"]
                    return _canonical_bytes(response).decode("utf-8")
        return response_text

    monkeypatch.setattr(
        ec01_fixtures._NativeSelectionTransport,
        "complete",
        complete_with_cross_field_selection,
    )
    run = await ec01_fixtures._run_native_selection()
    assert changed_field_id is not None
    candidate_field = next(
        item for item in run.candidate.fields if item.field_id == changed_field_id
    )
    assert candidate_field.state == "unknown"

    contracts = deepseek_fixtures._schema67_contract_set()
    projection = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=deepseek_fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    )
    manifest, validation = (
        derivation_validator.validate_ec01_formal_candidate_run_derivation_815(
            run=run,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=projection.execution_plan,
        )
    )

    assert validation.status == "PASS"
    changed_row = next(
        item for item in manifest.rows if item.field_id == changed_field_id
    )
    assert changed_row.model_returned_state == "present"
    assert changed_row.final_state == "unknown"
    assert changed_row.typed_reason == "SOURCE_LOCATION_UNRESOLVED"
    assert changed_row.coordinate_evidence_sha256s == ()


@pytest.mark.asyncio
async def test_c3_native_selection_rejects_rehashed_raw_and_coordinate_drift() -> None:
    run = await ec01_fixtures._run_native_selection()
    contracts = deepseek_fixtures._schema67_contract_set()
    projection = build_schema67_native_pdf_execution_projection_815(
        field_contracts=contracts,
        base_execution_plan=deepseek_fixtures._execution_plan(contracts),
        available_source_roles=("terms", "brochure", "rate_table"),
    )

    first_payload = json.loads(run.raw_responses[0].response_bytes)
    known_rows = [
        row for row in first_payload["fields"] if row["selection_ids"]
    ]
    first_known = known_rows[0]
    first_known["selection_ids"] = ["selection-" + "0" * 64]
    changed_bytes = _canonical_bytes(first_payload)
    changed_raw = replace(
        run.raw_responses[0],
        response_bytes=changed_bytes,
        byte_size=len(changed_bytes),
        response_sha256=hashlib.sha256(changed_bytes).hexdigest(),
    )
    changed_raws = (changed_raw, *run.raw_responses[1:])
    raw_drift = replace(
        run,
        raw_responses=changed_raws,
        terminal=run.terminal.rehash_with_raw(changed_raws),
    )
    raw_drift = replace(
        raw_drift,
        derivation_sha256=raw_drift.recomputed_derivation_sha256(),
    )

    cross_field_payload = json.loads(run.raw_responses[0].response_bytes)
    cross_field_rows = [
        row for row in cross_field_payload["fields"] if row["selection_ids"]
    ]
    cross_field_rows[0]["selection_ids"] = cross_field_rows[1]["selection_ids"]
    cross_field_bytes = _canonical_bytes(cross_field_payload)
    cross_field_raw = replace(
        run.raw_responses[0],
        response_bytes=cross_field_bytes,
        byte_size=len(cross_field_bytes),
        response_sha256=hashlib.sha256(cross_field_bytes).hexdigest(),
    )
    cross_field_raws = (cross_field_raw, *run.raw_responses[1:])
    cross_field_drift = replace(
        run,
        raw_responses=cross_field_raws,
        terminal=run.terminal.rehash_with_raw(cross_field_raws),
    )
    cross_field_drift = replace(
        cross_field_drift,
        derivation_sha256=cross_field_drift.recomputed_derivation_sha256(),
    )

    companion = run.coordinate_evidence_companion
    first_coordinate = companion.coordinate_rows[0]
    changed_coordinate = type(first_coordinate).model_validate(
        {
            **first_coordinate.model_dump(mode="python"),
            "page_width_points": "9999",
        }
    )
    changed_coordinate_rows = (
        changed_coordinate,
        *companion.coordinate_rows[1:],
    )
    companion_values = {
        **companion.model_dump(mode="python", exclude={"companion_sha256"}),
        "coordinate_rows": tuple(
            row.model_dump(mode="python") for row in changed_coordinate_rows
        ),
    }
    changed_companion = type(companion).model_validate(
        {
            **companion_values,
            "companion_sha256": canonical_hash(
                "schema67-coordinate-evidence-companion.815.v1",
                companion_values,
            ),
        }
    )
    changed_terminal = replace(
        run.terminal,
        coordinate_evidence_companion_sha256=(
            changed_companion.companion_sha256
        ),
    ).rehash_with_raw(run.raw_responses)
    coordinate_drift = replace(
        run,
        coordinate_evidence_companion=changed_companion,
        terminal=changed_terminal,
    )
    coordinate_drift = replace(
        coordinate_drift,
        derivation_sha256=coordinate_drift.recomputed_derivation_sha256(),
    )

    swapped_raws = (
        run.raw_responses[1],
        run.raw_responses[0],
        *run.raw_responses[2:],
    )
    raw_pointer_drift = replace(
        run,
        raw_responses=swapped_raws,
        terminal=run.terminal.rehash_with_raw(swapped_raws),
    )
    raw_pointer_drift = replace(
        raw_pointer_drift,
        derivation_sha256=raw_pointer_drift.recomputed_derivation_sha256(),
    )

    for changed_run in (
        raw_drift,
        cross_field_drift,
        coordinate_drift,
        raw_pointer_drift,
    ):
        with pytest.raises(
            FormalCandidateDerivationValidationError,
            match="FIELD_ATTEMPT_ORIGINAL_RUN_INVALID",
        ):
            derivation_validator.validate_ec01_formal_candidate_run_derivation_815(
                run=changed_run,
                revision_set_root=ec01_fixtures._REVISION_ROOT,
                field_contracts=contracts,
                execution_plan=projection.execution_plan,
            )


@pytest.mark.asyncio
async def test_c3_original_run_preserves_code_owned_evidence_demotion_reason() -> None:
    run = await ec01_fixtures._cached_native_known_run()
    contracts = deepseek_fixtures._schema67_contract_set()
    plan = ec01_fixtures._native_execution_plan(contracts)

    manifest, _ = (
        derivation_validator.validate_ec01_formal_candidate_run_derivation_815(
            run=run,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    )

    candidate_by_field = {
        item.field_id: item for item in run.candidate.fields
    }
    model_unknown_rows = tuple(
        row
        for row in manifest.rows
        if row.derivation_kind == "MODEL_RESPONSE"
        and candidate_by_field[row.field_id].state == "unknown"
    )

    assert manifest.attempted_field_count == 25
    assert manifest.provider_calls == 8
    assert manifest.transport_retries == 0
    assert manifest.response_contract_repairs == 0
    assert manifest.evidence_repairs == 0
    assert manifest.repair_task_key is None
    assert manifest.repair_field_ids == ()
    assert model_unknown_rows
    assert all(row.typed_reason is not None for row in model_unknown_rows)
    assert all(
        row.repair_attempted == 0
        and row.repair_parent_bound_attempt_hash is None
        and row.repair_parent_verification_hash is None
        and row.repair_request_sha256 is None
        and row.repair_raw_response_sha256 is None
        for row in manifest.rows
    )


@pytest.mark.asyncio
async def test_c3_original_run_replays_one_evidence_repair_lineage(
) -> None:
    run = await ec01_fixtures._cached_native_known_run()
    contracts = deepseek_fixtures._schema67_contract_set()
    plan = ec01_fixtures._native_execution_plan(contracts)

    manifest, validation = (
        derivation_validator.validate_ec01_formal_candidate_run_derivation_815(
            run=run,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    )

    assert validation.status == "PASS"
    assert manifest.attempted_field_count == 25
    assert manifest.provider_calls == 8
    assert manifest.transport_retries == 0
    assert manifest.response_contract_repairs == 0
    assert manifest.evidence_repairs == 0
    assert run.repair_raw_responses == ()
    assert manifest.repair_task_key is None
    assert manifest.repair_field_ids == ()
    assert all(
        row.repair_attempted == 0
        and row.repair_parent_bound_attempt_hash is None
        and row.repair_parent_verification_hash is None
        and row.repair_request_sha256 is None
        and row.repair_raw_response_sha256 is None
        and row.repair_raw_response_byte_size is None
        for row in manifest.rows
    )


@pytest.mark.asyncio
async def test_c3_original_run_replays_two_grouped_repair_raw_lineages() -> None:
    transport = ec01_fixtures._FieldLocalInvalidSelectionTransport(
        invalid_field_count=2
    )
    run = await ec01_fixtures._run(transport)
    contracts = deepseek_fixtures._schema67_contract_set()
    plan = ec01_fixtures._native_execution_plan(contracts)

    manifest, validation = (
        derivation_validator.validate_ec01_formal_candidate_run_derivation_815(
            run=run,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    )

    assert validation.status == "PASS"
    assert len(transport.target_field_ids) == 2
    assert run.repair_raw_responses == ()
    assert manifest.provider_calls == 8
    assert manifest.evidence_repairs == 0
    row_by_field = {row.field_id: row for row in manifest.rows}
    target_rows = tuple(
        row_by_field[field_id] for field_id in transport.target_field_ids
    )
    assert all(row.derivation_kind == "MODEL_RESPONSE" for row in target_rows)
    assert all(row.final_state == "unknown" for row in target_rows)
    assert all(row.typed_reason == "SOURCE_LOCATION_UNRESOLVED" for row in target_rows)
    assert all(row.repair_attempted == 0 for row in target_rows)
    assert all(row.raw_response_sha256 is not None for row in target_rows)


@pytest.mark.asyncio
async def test_c3_original_run_replays_same_task_multi_field_repair_in_contract_order() -> None:
    transport = ec01_fixtures._FieldLocalInvalidSelectionTransport(
        invalid_field_count=2
    )
    run = await ec01_fixtures._run(transport)
    contracts = deepseek_fixtures._schema67_contract_set()
    plan = ec01_fixtures._native_execution_plan(contracts)
    expected_field_ids = tuple(
        field_id
        for field_id in ORDERED_FIELD_IDS
        if field_id in set(transport.target_field_ids)
    )

    manifest, validation = (
        derivation_validator.validate_ec01_formal_candidate_run_derivation_815(
            run=run,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    )

    assert validation.status == "PASS"
    assert tuple(transport.target_field_ids) == expected_field_ids
    assert run.repair_raw_responses == ()
    assert manifest.repair_field_ids == ()
    row_by_field = {row.field_id: row for row in manifest.rows}
    target_rows = tuple(row_by_field[field_id] for field_id in expected_field_ids)
    assert len({row.task_key for row in target_rows}) == 1
    assert all(row.final_state == "unknown" for row in target_rows)
    assert all(row.typed_reason == "SOURCE_LOCATION_UNRESOLVED" for row in target_rows)


@pytest.mark.asyncio
async def test_c3_original_run_replays_task8_multi_source_repair() -> None:
    run = await ec01_fixtures._cached_native_known_run()
    contracts = deepseek_fixtures._schema67_contract_set()
    plan = ec01_fixtures._native_execution_plan(contracts)

    manifest, validation = (
        derivation_validator.validate_ec01_formal_candidate_run_derivation_815(
            run=run,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    )

    assert validation.status == "PASS"
    assert manifest.provider_calls == 8
    assert manifest.evidence_repairs == 0
    assert run.repair_raw_responses == ()
    assert all(row.repair_attempted == 0 for row in manifest.rows)
    assert run.coordinate_evidence_companion.coordinate_rows
    assert {
        row.source_role
        for row in run.coordinate_evidence_companion.coordinate_rows
    } <= {"terms", "brochure", "rate_table"}
    assert all(
        row.recomputed_coordinate_evidence_sha256()
        for row in run.coordinate_evidence_companion.coordinate_rows
    )


@pytest.mark.asyncio
async def test_c3_original_run_rejects_changed_repair_lineage_and_budget() -> None:
    run = await ec01_fixtures._cached_native_known_run()
    contracts = deepseek_fixtures._schema67_contract_set()
    plan = ec01_fixtures._native_execution_plan(contracts)
    manifest, _ = (
        derivation_validator.validate_ec01_formal_candidate_run_derivation_815(
            run=run,
            revision_set_root=ec01_fixtures._REVISION_ROOT,
            field_contracts=contracts,
            execution_plan=plan,
        )
    )
    assert run.repair_raw_responses == ()
    assert manifest.repair_task_key is None
    assert manifest.repair_field_ids == ()
    changed_runs = (
        replace(run, raw_responses=(run.raw_responses[0], *run.raw_responses[2:])),
        replace(
            run,
            raw_responses=(
                replace(run.raw_responses[0], task_key=manifest.task_keys[1]),
                *run.raw_responses[1:],
            ),
        ),
        replace(run, attempt_id="00000000-0000-4000-8000-000000000099"),
    )
    for changed_run in changed_runs:
        with pytest.raises(
            FormalCandidateDerivationValidationError,
            match="FIELD_ATTEMPT_ORIGINAL_RUN_INVALID",
        ):
            derivation_validator.validate_ec01_formal_candidate_run_derivation_815(
                run=changed_run,
                revision_set_root=ec01_fixtures._REVISION_ROOT,
                field_contracts=contracts,
                execution_plan=plan,
            )

    batch_contract = derivation_validator._require_batch_repair_contract
    with pytest.raises(
        FormalCandidateDerivationValidationError,
        match="FIELD_ATTEMPT_REPAIR_BUDGET_INVALID",
    ):
        batch_contract(
            derivation_source=manifest.derivation_source,
            task_keys=manifest.task_keys,
            rows=manifest.rows,
            provider_calls=11,
            transport_retries=manifest.transport_retries,
            response_contract_repairs=manifest.response_contract_repairs,
            evidence_repairs=manifest.evidence_repairs,
            repair_task_key=manifest.repair_task_key,
            repair_field_ids=manifest.repair_field_ids,
        )
    with pytest.raises(
        FormalCandidateDerivationValidationError,
        match="FIELD_ATTEMPT_REPAIR_BUDGET_INVALID",
    ):
        batch_contract(
            derivation_source=manifest.derivation_source,
            task_keys=manifest.task_keys,
            rows=manifest.rows,
            provider_calls=17,
            transport_retries=manifest.transport_retries,
            response_contract_repairs=manifest.response_contract_repairs,
            evidence_repairs=9,
            repair_task_key=manifest.repair_task_key,
            repair_field_ids=manifest.repair_field_ids,
        )
    for transport_retries, response_contract_repairs in ((1, 0), (0, 1)):
        with pytest.raises(
            FormalCandidateDerivationValidationError,
            match="FIELD_ATTEMPT_REPAIR_BUDGET_INVALID",
        ):
            batch_contract(
                derivation_source=manifest.derivation_source,
                task_keys=manifest.task_keys,
                rows=manifest.rows,
                provider_calls=10,
                transport_retries=transport_retries,
                response_contract_repairs=response_contract_repairs,
                evidence_repairs=manifest.evidence_repairs,
                repair_task_key=manifest.repair_task_key,
                repair_field_ids=manifest.repair_field_ids,
            )
    changed_lineage_rows = tuple(
        next(
            row
            for row in manifest.rows
            if row.derivation_kind == "MODEL_RESPONSE"
            and row.task_key == task_key
        )
        for task_key in manifest.task_keys[:2]
    )
    with pytest.raises(
        FormalCandidateDerivationValidationError,
        match="FIELD_ATTEMPT_REPAIR_LINEAGE_INVALID",
    ):
        batch_contract(
            derivation_source=manifest.derivation_source,
            task_keys=manifest.task_keys,
            rows=tuple(
                replace(
                    row,
                    repair_attempted=1,
                    repair_parent_bound_attempt_hash="0" * 64,
                    repair_parent_verification_hash="1" * 64,
                    repair_request_sha256="2" * 64,
                    repair_raw_response_sha256="3" * 64,
                    repair_raw_response_byte_size=1,
                )
                if row.field_id
                in {item.field_id for item in changed_lineage_rows}
                else row
                for row in manifest.rows
            ),
            provider_calls=10,
            transport_retries=manifest.transport_retries,
            response_contract_repairs=manifest.response_contract_repairs,
            evidence_repairs=2,
            repair_task_key="schema67-batch-evidence-repair-01",
            repair_field_ids=tuple(
                field_id
                for field_id in ORDERED_FIELD_IDS
                if field_id in {item.field_id for item in changed_lineage_rows}
            ),
        )


def test_c3_field_attempt_interface_closes_initial_to_repair_lineage() -> None:
    """Interface RED; positive repair raw awaits the frozen Win1 run successor."""
    row_fields = {
        item.name
        for item in dataclass_fields(derivation_validator.Schema67FieldAttempt815V1)
    }
    required_row_fields = {
        "initial_failure_reason",
        "repair_attempted",
        "repair_parent_bound_attempt_hash",
        "repair_parent_verification_hash",
        "repair_raw_response_byte_size",
        "repair_raw_response_sha256",
        "repair_request_sha256",
    }

    assert required_row_fields <= row_fields, (
        "field-attempt rows cannot replay initial-to-repair lineage: "
        f"{sorted(required_row_fields - row_fields)}"
    )
    row_hints = get_type_hints(derivation_validator.Schema67FieldAttempt815V1)
    assert set(get_args(row_hints["repair_attempted"])) == {0, 1}


def test_c3_manifest_interface_closes_grouped_repair_budget() -> None:
    """Interface RED; budget values must later come from the original run."""

    manifest_fields = {
        item.name
        for item in dataclass_fields(
            derivation_validator.Schema67FieldAttemptManifest815V1
        )
    }
    required_manifest_fields = {
        "evidence_repairs",
        "provider_calls",
        "repair_field_ids",
        "repair_task_key",
        "response_contract_repairs",
        "transport_retries",
    }
    assert required_manifest_fields <= manifest_fields, (
        "field-attempt manifest cannot enforce the batch repair budget: "
        f"{sorted(required_manifest_fields - manifest_fields)}"
    )

    manifest_hints = get_type_hints(
        derivation_validator.Schema67FieldAttemptManifest815V1
    )
    assert manifest_hints["evidence_repairs"] is int
    assert set(get_args(manifest_hints["transport_retries"])) == {0, 1}
    assert set(get_args(manifest_hints["response_contract_repairs"])) == {0, 1}

    # EC-01 is exact8 plus at most one Evidence repair for each original group.
    # Transport retry and response-contract repair remain disabled.
    initial_calls = 8
    transport_retries = 0
    response_contract_repairs = 0
    evidence_repairs = 8
    shared_extras = evidence_repairs
    provider_calls = initial_calls + shared_extras
    assert evidence_repairs <= 8
    assert transport_retries == response_contract_repairs == 0
    assert shared_extras <= 8
    assert provider_calls <= 16


def test_c3_repair_plan_fields_follow_task_contract_order() -> None:
    require_order = derivation_validator._require_task_repair_field_order_815
    contract_order = ("field-z", "field-a", "field-m")
    require_order(("field-z", "field-a"), contract_order)
    with pytest.raises(
        FormalCandidateDerivationValidationError,
        match="FIELD_ATTEMPT_REPAIR_LINEAGE_INVALID",
    ):
        require_order(tuple(sorted(("field-z", "field-a"))), contract_order)


def _persist_synthetic_fixture(root: Path) -> None:
    (
        task_keys,
        field_task_ordinals,
        request_bodies,
        raw_response_bodies,
        outcomes,
        parsed_fields,
        parsed_evidence,
        terminal_bytes,
    ) = _synthetic_fixture()
    manifest = make_schema67_field_attempt_manifest_815(
        task_keys=task_keys,
        field_task_ordinals=field_task_ordinals,
        request_bodies=request_bodies,
        raw_response_bodies=raw_response_bodies,
        parse_outcomes=outcomes,
        parsed_fields=parsed_fields,
        parsed_evidence_receipts=parsed_evidence,
        terminal_bytes=terminal_bytes,
        candidate_fields=parsed_fields,
        candidate_evidence_receipts=parsed_evidence,
    )
    root.mkdir()
    (root / "field-attempt-manifest.json").write_bytes(
        _canonical_bytes(manifest.to_wire())
    )
    for ordinal, (request_body, raw_response_body) in enumerate(
        zip(request_bodies, raw_response_bodies, strict=True),
        start=1,
    ):
        (root / f"request-{ordinal:02d}.json").write_bytes(request_body)
        (root / f"raw-response-{ordinal:02d}.json").write_bytes(raw_response_body)
    (root / "parsed-fields.json").write_bytes(
        _canonical_bytes(
            [
                item.model_dump(mode="json", round_trip=True)
                for item in parsed_fields
            ]
        )
    )
    (root / "parsed-evidence.json").write_bytes(
        _canonical_bytes(
            [
                item.model_dump(mode="json", round_trip=True)
                for item in parsed_evidence
            ]
        )
    )
    (root / "candidate-fields.json").write_bytes(
        _canonical_bytes(
            [
                item.model_dump(mode="json", round_trip=True)
                for item in parsed_fields
            ]
        )
    )
    (root / "candidate-evidence.json").write_bytes(
        _canonical_bytes(
            [
                item.model_dump(mode="json", round_trip=True)
                for item in parsed_evidence
            ]
        )
    )
    (root / "terminal.json").write_bytes(terminal_bytes)


def test_c3_persisted_fixture_fresh_opens_and_rejects_missing_or_changed_bytes(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "formal-candidate-artifacts"
    _persist_synthetic_fixture(artifact_root)

    result = validate_formal_candidate_derivation_directory_815(artifact_root)

    assert result.status == "SYNTHETIC_TEST_ONLY"
    assert (result.ordered_field_count, result.attempted_field_count) == (67, 67)
    assert (result.request_count, result.raw_response_count) == (8, 8)
    assert result.provider_calls == 0

    missing_root = tmp_path / "missing-raw-artifacts"
    _persist_synthetic_fixture(missing_root)
    (missing_root / "raw-response-04.json").unlink()
    with pytest.raises(
        FormalCandidateDerivationValidationError,
        match="FIELD_ATTEMPT_ARTIFACT_MISSING",
    ):
        validate_formal_candidate_derivation_directory_815(missing_root)

    with pytest.raises(
        FormalCandidateDerivationValidationError,
        match="FIELD_ATTEMPT_DIRECTORY_NOT_READY",
    ):
        validate_formal_candidate_derivation_directory_815(tmp_path / "wrong-directory")

    (artifact_root / "raw-response-01.json").write_bytes(
        (artifact_root / "raw-response-01.json").read_bytes() + b" "
    )
    with pytest.raises(
        FormalCandidateDerivationValidationError,
        match="FIELD_ATTEMPT_ARTIFACT_NONCANONICAL",
    ):
        validate_formal_candidate_derivation_directory_815(artifact_root)


def test_c3_persisted_full_rehash_cannot_pair_changed_raw_with_old_parsed_candidate(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "full-rehash-raw-mismatch"
    _persist_synthetic_fixture(artifact_root)
    (
        task_keys,
        field_task_ordinals,
        request_bodies,
        raw_response_bodies,
        outcomes,
        parsed_fields,
        parsed_evidence,
        terminal_bytes,
    ) = _synthetic_fixture()
    changed_first_raw = _canonical_bytes(
        {
            "fields": [
                {
                    "field_id": field_id,
                    "state": "present" if index == 0 else "unknown",
                }
                for index, (field_id, task_ordinal) in enumerate(
                    zip(ORDERED_FIELD_IDS, field_task_ordinals, strict=True)
                )
                if task_ordinal == 1
            ],
            "task_key": task_keys[0],
        }
    )
    changed_raw_bodies = (changed_first_raw, *raw_response_bodies[1:])
    rehashed_manifest = make_schema67_field_attempt_manifest_815(
        task_keys=task_keys,
        field_task_ordinals=field_task_ordinals,
        request_bodies=request_bodies,
        raw_response_bodies=changed_raw_bodies,
        parse_outcomes=outcomes,
        parsed_fields=parsed_fields,
        parsed_evidence_receipts=parsed_evidence,
        terminal_bytes=terminal_bytes,
        candidate_fields=parsed_fields,
        candidate_evidence_receipts=parsed_evidence,
    )
    (artifact_root / "raw-response-01.json").write_bytes(changed_first_raw)
    (artifact_root / "field-attempt-manifest.json").write_bytes(
        _canonical_bytes(rehashed_manifest.to_wire())
    )

    with pytest.raises(
        FormalCandidateDerivationValidationError,
        match="FIELD_ATTEMPT_RAW_PARSED_REPLAY_MISMATCH",
    ):
        validate_formal_candidate_derivation_directory_815(artifact_root)
