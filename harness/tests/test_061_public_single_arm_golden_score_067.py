from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from insurance_harness.knowledge_compiler import vertical_falsification as vf

_FAKE_GOLDEN_BYTES = b"067-approved-fake-golden"
_ADMISSION_DIGEST = "a" * 64


def _model_sha(seed: str) -> str:
    return (seed.encode("utf-8").hex() + "0" * 64)[:64]


def _identity(
    *,
    model_id: str = "gpt-5.6-sol",
    model_base: str = "offline://codex-gpt-5.6-sol",
    model_sha: str = "b" * 64,
    arm_profile_sha: str = "c" * 64,
) -> vf.ArmInputIdentityV1:
    return vf.ArmInputIdentityV1(
        product_version_id=vf.APPROVED_PRODUCT_VERSION_ID,
        source_sha256=vf.APPROVED_596_1_SOURCE_SHA256,
        schema_version=vf.APPROVED_SCHEMA_VERSION,
        schema_sha256=vf.APPROVED_SCHEMA_REGISTRY_SHA256,
        parser_identity_sha256=vf.APPROVED_CANDIDATE_PARSER_IDENTITY_SHA256,
        model_identity_sha256=model_sha,
        semantic_model_id=model_id,
        semantic_api_base=model_base,
        prompt_identity_sha256=vf.APPROVED_PROMPT_IDENTITY_SHA256,
        budget_identity_sha256=vf.APPROVED_BUDGET_IDENTITY_SHA256,
        normalizer_identity_sha256=vf.APPROVED_NORMALIZER_IDENTITY_SHA256,
        comparator_identity_sha256=vf.APPROVED_COMPARATOR_IDENTITY_SHA256,
        arm_profile_sha256=arm_profile_sha,
        parse_artifact_receipt_digest_sha256=_ADMISSION_DIGEST,
        parser_id="mineru-cloud-pipeline",
        parser_mode="bounded_upgrade",
        parser_attempt=2,
    )


def _approved_identity() -> vf.ArmInputIdentityV1:
    return _identity(
        model_id=vf.APPROVED_SEMANTIC_MODEL_ID,
        model_base=vf.APPROVED_SEMANTIC_API_BASE,
        model_sha=vf.APPROVED_SEMANTIC_MODEL_IDENTITY_SHA256,
        arm_profile_sha=vf.APPROVED_ARM_PROFILE_SHA256,
    )


def _evidence(*, rate: bool = False) -> vf.EvidenceLocatorV1:
    return vf.EvidenceLocatorV1(
        source_sha256=vf.APPROVED_596_1_SOURCE_SHA256[2 if rate else 0],
        quote_snapshot="synthetic supporting quote",
        page_number=1,
        block_id="block-1",
        table_id="table-1" if rate else None,
        cell_id="cell-1" if rate else None,
        row_index=1 if rate else None,
        column_index=1 if rate else None,
        header_snapshot="synthetic header" if rate else None,
        row_span=1 if rate else None,
        column_span=1 if rate else None,
    )


def _fields() -> tuple[vf.ArmFieldOutputV1, ...]:
    return tuple(
        vf.ArmFieldOutputV1(
            field_id=field_id,
            state="present",
            value_snapshot=f"synthetic-{index:03d}",
            evidence=(_evidence(rate=field_id in vf.APPROVED_RATE_FIELD_IDS),),
        )
        for index, field_id in enumerate(vf.APPROVED_SCHEMA60_FIELD_IDS, start=1)
    )


def _output(
    *,
    identity: vf.ArmInputIdentityV1 | None = None,
    fields: tuple[vf.ArmFieldOutputV1, ...] | None = None,
    arm: Literal["baseline", "candidate"] = "candidate",
) -> vf.FrozenArmOutputV1:
    return vf.freeze_arm_output(
        arm=arm,
        identity=_identity() if identity is None else identity,
        fields=_fields() if fields is None else fields,
    )


def _golden() -> vf.GoldenSetV1:
    critical = {
        field_id: priority
        for priority, field_id, _field_name in vf.APPROVED_CRITICAL18_FIELDS
    }
    return vf.GoldenSetV1(
        product_version_id=vf.APPROVED_PRODUCT_VERSION_ID,
        schema_version=vf.APPROVED_SCHEMA_VERSION,
        schema_sha256=vf.APPROVED_SCHEMA_REGISTRY_SHA256,
        source_sha256=vf.APPROVED_596_1_SOURCE_SHA256,
        release_hash=vf.APPROVED_GOLDEN_RELEASE_SHA256,
        artifact_hash=vf.APPROVED_GOLDEN_ARTIFACT_SHA256,
        approval_subject_hash=vf.APPROVED_GOLDEN_APPROVAL_SUBJECT_SHA256,
        golden_596_jsonl_sha256=vf.APPROVED_GOLDEN_596_JSONL_SHA256,
        golden_content_digest_sha256="d" * 64,
        critical18_contract_id="critical18-candidate.v1",
        critical18_contract_sha256=vf.APPROVED_CRITICAL18_SHA256,
        fields=tuple(
            vf.GoldenFieldV1(
                field_id=field_id,
                expected_state="present",
                expected_value=f"synthetic-{index:03d}",
                critical=critical.get(field_id),
                rate=field_id in vf.APPROVED_RATE_FIELD_IDS,
            )
            for index, field_id in enumerate(
                vf.APPROVED_SCHEMA60_FIELD_IDS, start=1
            )
        ),
    )


def _install_ready_fakes(
    monkeypatch: pytest.MonkeyPatch,
) -> list[object]:
    golden_reads: list[object] = []
    monkeypatch.setattr(
        vf,
        "admit_596_1_vertical_falsification",
        lambda **_kwargs: vf.VerticalFalsificationAdmission(
            status="READY_FOR_QUALITY_FALSIFICATION",
            missing_contracts=(),
            receipt_digest_sha256=_ADMISSION_DIGEST,
        ),
    )

    def _parse(value: object) -> vf.GoldenSetV1 | None:
        golden_reads.append(value)
        return _golden() if value == _FAKE_GOLDEN_BYTES else None

    monkeypatch.setattr(vf, "_parse_approved_golden_bytes", _parse)
    return golden_reads


def test_public_single_arm_score_api_exists() -> None:
    scorer = getattr(vf, "score_admitted_frozen_arm", None)
    score_type = getattr(vf, "AdmittedFrozenArmScoreV1", None)

    assert callable(scorer)
    assert isinstance(score_type, type)


def test_scores_offline_strong_arm_only_as_unadmitted_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    golden_reads = _install_ready_fakes(monkeypatch)

    score = vf.score_admitted_frozen_arm(
        arm_output=_output(),
        golden_596_jsonl_bytes=_FAKE_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert score.status == "UNADMITTED_RAW"
    assert "ARM_PROFILE_MISMATCH" in score.reason_codes
    assert "ARM_AUTHORITY_MISMATCH" in score.reason_codes
    assert score.metrics.denominator == 60
    assert score.metrics.exact_field_correct == 60
    assert score.raw_metrics == vf.RawSingleArmMetricsV1(
        state_exact=vf.MetricFractionV1(60, 60),
        present_exact=vf.MetricFractionV1(60, 60),
        absent_exact=vf.MetricFractionV1(0, 0),
        known_evidence=vf.MetricFractionV1(60, 60),
        critical18_raw_exact=vf.MetricFractionV1(18, 18),
    )
    assert len(score.field_correctness) == 60
    assert golden_reads == [_FAKE_GOLDEN_BYTES]
    assert len(score.score_receipt_hash) == 64


def test_scores_only_exact_approved_deepseek_profile_as_scored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ready_fakes(monkeypatch)

    score = vf.score_admitted_frozen_arm(
        arm_output=_output(identity=_approved_identity()),
        golden_596_jsonl_bytes=_FAKE_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert score.status == "SCORED"
    assert "ARM_PROFILE_MISMATCH" not in score.reason_codes
    assert "ARM_AUTHORITY_MISMATCH" not in score.reason_codes


def test_exact_049_parser_retains_absent_explicit_business_values() -> None:
    golden_path = (
        Path(__file__).parents[2]
        / "dataset/goldenset/gs-s0q-596-v1/596.jsonl"
    )

    golden_bytes = golden_path.read_bytes()
    golden = vf._parse_approved_golden_bytes(golden_bytes)
    source_absent_values = {
        str(record["field_id"]): record["value"]
        for line in golden_bytes.decode("utf-8").splitlines()
        if line.strip()
        for record in (json.loads(line),)
        if record["tri_state"] == "absent_explicitly"
    }

    assert golden is not None
    absent = tuple(
        field
        for field in golden.fields
        if field.expected_state == "absent_explicitly"
    )
    assert len(absent) == 2
    assert {field.field_id: field.expected_value for field in absent} == (
        source_absent_values
    )
    assert all(field.expected_value and field.expected_value.strip() for field in absent)


def test_raw_metrics_separate_absent_value_from_state_correctness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ready_fakes(monkeypatch)
    golden = _golden()
    critical_id = "zh_74aa1b9c93"
    noncritical_id = "zh_ca6e0226c2"
    golden_fields = tuple(
        replace(
            field,
            expected_state="absent_explicitly",
            expected_value=(
                "exact-critical-absence"
                if field.field_id == critical_id
                else "exact-noncritical-absence"
            ),
        )
        if field.field_id in {critical_id, noncritical_id}
        else field
        for field in golden.fields
    )
    monkeypatch.setattr(
        vf,
        "_parse_approved_golden_bytes",
        lambda _value: replace(golden, fields=golden_fields),
    )
    fields = tuple(
        replace(
            field,
            state="absent_explicitly",
            value_snapshot=(
                "wrong-critical-absence"
                if field.field_id == critical_id
                else "exact-noncritical-absence"
            ),
        )
        if field.field_id in {critical_id, noncritical_id}
        else field
        for field in _fields()
    )

    score = vf.score_admitted_frozen_arm(
        arm_output=_output(fields=fields),
        golden_596_jsonl_bytes=_FAKE_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert score.raw_metrics == vf.RawSingleArmMetricsV1(
        state_exact=vf.MetricFractionV1(60, 60),
        present_exact=vf.MetricFractionV1(58, 58),
        absent_exact=vf.MetricFractionV1(1, 2),
        known_evidence=vf.MetricFractionV1(60, 60),
        critical18_raw_exact=vf.MetricFractionV1(17, 18),
    )


@pytest.mark.parametrize(
    "case",
    (
        "admission",
        "hash",
        "product",
        "baseline",
        "parser",
        "prompt",
        "field_order",
    ),
)
def test_rejects_pre_golden_custody_drift(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    golden_reads = _install_ready_fakes(monkeypatch)
    output = _output()
    if case == "admission":
        monkeypatch.setattr(
            vf,
            "admit_596_1_vertical_falsification",
            lambda **_kwargs: vf.VerticalFalsificationAdmission(
                status="BLOCKED_ON_REQUIRED_CONTRACTS",
                missing_contracts=("fixture",),
            ),
        )
    elif case == "hash":
        output = replace(output, output_hash="e" * 64)
    elif case == "product":
        output = _output(
            identity=replace(output.identity, product_version_id="foreign-product")
        )
    elif case == "baseline":
        output = _output(arm="baseline")
    elif case == "parser":
        output = _output(
            identity=replace(
                output.identity,
                parser_id="foreign-parser",
                parser_identity_sha256="e" * 64,
            )
        )
    elif case == "prompt":
        output = _output(
            identity=replace(output.identity, prompt_identity_sha256="e" * 64)
        )
    else:
        output = _output(fields=tuple(reversed(output.fields)))

    score = vf.score_admitted_frozen_arm(
        arm_output=output,
        golden_596_jsonl_bytes=_FAKE_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert score.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert score.field_correctness == ()
    assert golden_reads == []


def test_rejects_golden_byte_drift_after_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    golden_reads = _install_ready_fakes(monkeypatch)

    score = vf.score_admitted_frozen_arm(
        arm_output=_output(),
        golden_596_jsonl_bytes=b"mutated",
        admitted_parse_artifacts=(),
    )

    assert score.status == "GOLDEN_INVALID"
    assert score.reason_codes == ("GOLDEN_596_BYTES_INVALID",)
    assert golden_reads == [b"mutated"]


def test_model_identity_changes_receipt_not_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ready_fakes(monkeypatch)
    first = vf.score_admitted_frozen_arm(
        arm_output=_output(),
        golden_596_jsonl_bytes=_FAKE_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )
    second = vf.score_admitted_frozen_arm(
        arm_output=_output(
            identity=_identity(
                model_id="another-offline-model",
                model_base="https://offline.invalid/v1",
                model_sha=_model_sha("another-offline-model"),
            )
        ),
        golden_596_jsonl_bytes=_FAKE_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert first.status == second.status == "UNADMITTED_RAW"
    assert first.metrics == second.metrics
    assert first.field_correctness == second.field_correctness
    assert first.score_receipt_hash != second.score_receipt_hash


def test_reports_critical_value_and_rate_locator_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ready_fakes(monkeypatch)
    fields = list(_fields())
    critical_index = vf.APPROVED_SCHEMA60_FIELD_IDS.index(
        vf.APPROVED_CRITICAL18_FIELD_IDS[0]
    )
    fields[critical_index] = replace(
        fields[critical_index], value_snapshot="wrong-value"
    )
    rate_index = vf.APPROVED_SCHEMA60_FIELD_IDS.index(vf.APPROVED_RATE_FIELD_IDS[0])
    fields[rate_index] = replace(
        fields[rate_index],
        evidence=(
            vf.EvidenceLocatorV1(
                source_sha256=vf.APPROVED_596_1_SOURCE_SHA256[2],
                quote_snapshot="synthetic supporting quote",
                page_number=1,
            ),
        ),
    )

    score = vf.score_admitted_frozen_arm(
        arm_output=_output(identity=_approved_identity(), fields=tuple(fields)),
        golden_596_jsonl_bytes=_FAKE_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    by_id = {item.field_id: item for item in score.field_correctness}
    assert score.status == "SCORED"
    assert "CRITICAL_SEMANTIC_ERROR" in score.reason_codes
    assert "RATE_EVIDENCE_LOCATOR_INCOMPLETE" in score.reason_codes
    assert by_id[vf.APPROVED_CRITICAL18_FIELD_IDS[0]].critical_priority == "P0"
    assert not by_id[vf.APPROVED_CRITICAL18_FIELD_IDS[0]].exact_field_correct
    assert by_id[vf.APPROVED_RATE_FIELD_IDS[0]].rate_field
    assert not by_id[vf.APPROVED_RATE_FIELD_IDS[0]].rate_locator_complete


def test_serialized_score_contains_no_golden_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ready_fakes(monkeypatch)
    score = vf.score_admitted_frozen_arm(
        arm_output=_output(),
        golden_596_jsonl_bytes=_FAKE_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    serialized = json.dumps(asdict(score), sort_keys=True)

    assert "synthetic-001" not in serialized
    assert "expected_value" not in serialized
    assert "expected_state" not in serialized
    assert "reasoning" not in serialized


@pytest.mark.parametrize(
    ("state", "value"),
    (
        ("present", "synthetic-001"),
        ("absent_explicitly", "not provided"),
        ("unknown", None),
    ),
)
def test_per_field_serialization_does_not_disclose_golden_state_or_value(
    monkeypatch: pytest.MonkeyPatch,
    state: Literal["present", "absent_explicitly", "unknown"],
    value: str | None,
) -> None:
    _install_ready_fakes(monkeypatch)
    golden = _golden()
    golden_fields = list(golden.fields)
    golden_fields[0] = replace(
        golden_fields[0],
        expected_state=state,
        expected_value=value,
    )
    monkeypatch.setattr(
        vf,
        "_parse_approved_golden_bytes",
        lambda _value: replace(golden, fields=tuple(golden_fields)),
    )
    fields = list(_fields())
    fields[0] = replace(fields[0], state=state, value_snapshot=value)

    score = vf.score_admitted_frozen_arm(
        arm_output=_output(fields=tuple(fields)),
        golden_596_jsonl_bytes=_FAKE_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    serialized_field = asdict(score.field_correctness[0])
    assert set(serialized_field) == {
        "field_id",
        "critical_priority",
        "rate_field",
        "tri_state_correct",
        "exact_field_correct",
        "known_evidence_present",
        "rate_locator_complete",
    }
    assert all("value" not in key and "expected" not in key for key in serialized_field)


def test_non_ready_admission_short_circuits_malformed_arm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    golden_reads = _install_ready_fakes(monkeypatch)
    monkeypatch.setattr(
        vf,
        "admit_596_1_vertical_falsification",
        lambda **_kwargs: vf.VerticalFalsificationAdmission(
            status="BLOCKED_ON_REQUIRED_CONTRACTS",
            missing_contracts=("fixture",),
        ),
    )
    malformed = vf.FrozenArmOutputV1(
        arm="candidate",
        identity=cast(Any, object()),
        fields=cast(tuple[vf.ArmFieldOutputV1, ...], (object(),)),
        output_hash=cast(str, object()),
    )

    score = vf.score_admitted_frozen_arm(
        arm_output=malformed,
        golden_596_jsonl_bytes=_FAKE_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert score.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert score.output_hash is None
    assert score.arm_identity is None
    assert golden_reads == []


@pytest.mark.parametrize("case", ("identity", "field", "hash"))
def test_ready_admission_rejects_malformed_nested_arm_before_golden(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    golden_reads = _install_ready_fakes(monkeypatch)
    valid = _output()
    if case == "identity":
        malformed = replace(valid, identity=cast(Any, object()))
    elif case == "field":
        malformed = replace(
            valid,
            fields=cast(tuple[vf.ArmFieldOutputV1, ...], (object(),)),
        )
    else:
        malformed = replace(valid, output_hash=cast(str, object()))

    score = vf.score_admitted_frozen_arm(
        arm_output=malformed,
        golden_596_jsonl_bytes=_FAKE_GOLDEN_BYTES,
        admitted_parse_artifacts=(),
    )

    assert score.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert score.reason_codes == ("ARM_OUTPUT_MALFORMED",)
    assert score.output_hash == (valid.output_hash if case != "hash" else None)
    assert golden_reads == []
