"""OpenSpec 061: dependency-gated 596-1 vertical falsification."""

from __future__ import annotations

import builtins
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.material_profiles import MaterialProfileResolution
from insurance_harness.compiler.parsed_documents import (
    CapabilityEvidenceV1,
    PageLocatorV1,
    ParseAttemptV1,
    ParsedDocumentV1,
    ParseElementCountsV1,
    ParseManifestV1,
    ParseOutputFactsV1,
    ParsePageV1,
    ParseQualityDecisionV1,
    ParseQualityMeasuredFactsV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
)
from insurance_harness.knowledge_compiler import vertical_falsification as vf
from insurance_harness.knowledge_compiler.vertical_falsification import (
    ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID,
    APPROVED_ARM_PROFILE_SHA256,
    APPROVED_CRITICAL18_FIELD_IDS,
    APPROVED_CRITICAL18_SHA256,
    REQUIRED_PUBLIC_CONTRACTS,
    ArmFieldOutputV1,
    ArmInputIdentityV1,
    CallBudgetLedgerV1,
    EvidenceLocatorV1,
    GoldenFieldV1,
    GoldenSetV1,
    VerticalFalsificationDecisionV1,
    admit_596_1_vertical_falsification,
    check_call_budget,
    freeze_arm_output,
    score_vertical_falsification,
    verify_arm_output_hash,
)


def _sha(value: int) -> str:
    return f"{value:064x}"


_SOURCE_BY_ROLE = {
    "terms": "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
    "brochure": "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
    "rate_table": "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
}
_INDEPENDENT_CRITICAL18_FIELDS: tuple[
    tuple[Literal["P0", "P1"], str, str], ...
] = (
    ("P0", "clause_version", "条款版本标识"),
    ("P0", "reduced_paid_up", "减额缴清"),
    ("P0", "reinstatement", "复效条款"),
    ("P0", "zh_0b3894ed2a", "产品类型"),
    ("P0", "zh_74aa1b9c93", "保证续保"),
    ("P0", "zh_d62301d84c", "宽限期"),
    ("P0", "zh_e1bea0527a", "特殊免责"),
    ("P1", "claim_filing_requirements", "理赔申请时效与申请材料"),
    ("P1", "exclusions_official", "责任免除"),
    ("P1", "external_drug_coverage", "外购药/特药责任"),
    ("P1", "waiting_period_claim_handling", "等待期内出险处理"),
    ("P1", "zh_09a5d9e54e", "保什么"),
    ("P1", "zh_3a3e6520a3", "给付限额"),
    ("P1", "zh_3d8424595d", "报销比例"),
    ("P1", "zh_4a789b1d6f", "报销范围"),
    ("P1", "zh_7d7fe38f09", "癌症医疗"),
    ("P1", "zh_7fe8603c08", "费用"),
    ("P1", "zh_f32c510a5e", "医院范围"),
)
_INDEPENDENT_CRITICAL18_FIELD_IDS = tuple(
    field_id for _priority, field_id, _field_name in _INDEPENDENT_CRITICAL18_FIELDS
)
_INDEPENDENT_SCHEMA60_FIELD_IDS = (
    "zh_fd9a0b9fa3",
    "zh_1a3227c6ce",
    "zh_8bd90889d3",
    "zh_f1de0de938",
    "zh_ad4a95859a",
    "zh_0b3894ed2a",
    "zh_789479e2d4",
    "zh_346f0dac8c",
    "zh_5162df17d8",
    "zh_67ee7025ef",
    "zh_89e518b987",
    "zh_6a3bd6cdbf",
    "zh_a271d96039",
    "zh_f8cc996739",
    "zh_14b93ce275",
    "zh_17a83223e4",
    "zh_313cabffd8",
    "zh_f558f0a88f",
    "zh_d62301d84c",
    "zh_540e1969e3",
    "zh_0c5a8e59e2",
    "zh_7598a3116c",
    "zh_1a5675a37a",
    "zh_c4f4b0d48a",
    "zh_7fe8603c08",
    "zh_b7ceabc3c0",
    "zh_17e15e0c5a",
    "zh_a17bd1c3f3",
    "zh_dcae594f8b",
    "zh_23a2625781",
    "zh_7bf05bc576",
    "zh_1ec5e3f2cc",
    "zh_b4b770e114",
    "regulatory_filing_no",
    "clause_version",
    "clause_effective_date",
    "exclusions_official",
    "waiting_period_claim_handling",
    "reinstatement",
    "claim_filing_requirements",
    "reduced_paid_up",
    "zh_7d7fe38f09",
    "zh_09a5d9e54e",
    "zh_58d313ee26",
    "zh_74aa1b9c93",
    "zh_ca6e0226c2",
    "zh_2df7d6256c",
    "zh_c588207763",
    "zh_0612362268",
    "zh_c5187f228e",
    "zh_74fd5a9469",
    "zh_3a3e6520a3",
    "zh_4a789b1d6f",
    "zh_3d8424595d",
    "zh_f32c510a5e",
    "zh_e1bea0527a",
    "zh_52548821b9",
    "pre_existing_conditions",
    "external_drug_coverage",
    "discontinuation_renewal",
)
_INDEPENDENT_RATE_FIELD_IDS = ("zh_7fe8603c08", "zh_c588207763")
_INDEPENDENT_GOLDEN_RELEASE_HASH = (
    "fca06f988bf0310d12a0f6f8d0703a9476c54a5405676fb1a9b3476f91ec21d0"
)
_INDEPENDENT_GOLDEN_ARTIFACT_HASH = (
    "83032da028ef227071fddac0ed422cbb9d1c2cc31e195972f9878a67d95b44ca"
)
_INDEPENDENT_GOLDEN_APPROVAL_SUBJECT_HASH = (
    "6feb2acf4be1ab5ce075b662bc9c9a40024038ca2324b893d3f31b1384f7674b"
)

_INDEPENDENT_ARM_PROFILE_PAYLOAD = {
    "contract": "061-arm-profile-candidate.v1",
    "authority_base": "1a8e36e032512e77474c83efbe1a97ed1c183b30",
    "invariant": "parser_artifact_is_only_arm_variable",
    "semantic_extraction": {
        "model": "deepseek-v4-flash",
        "endpoint": "https://api.deepseek.com/v1",
        "protocol": "openai_compatible",
        "credential_status": "PRESENT_BY_STRICT_LOADER",
    },
    "arms": [
        {
            "arm": "baseline",
            "parser_engine": "pdfplumber",
            "parser_profile_ref": "approved-parser-profile:parser-neutral-default.v1",
            "attempt_number": 1,
            "attempt_role": "default",
            "adapter_module": "insurance_harness.compiler.native_pdfplumber",
            "adapter_blob_git_sha1": "d158d000191aadcc5428a986f08b37df821450a4",
            "builder": "build_parsed_document_v1",
        },
        {
            "arm": "candidate",
            "parser_engine": "mineru-cloud-pipeline",
            "parser_profile_ref": (
                "approved-parser-profile:parser-neutral-bounded-upgrade.v1"
            ),
            "attempt_number": 2,
            "attempt_role": "bounded_upgrade",
            "adapter_module": "insurance_harness.compiler.native_mineru_cloud",
            "adapter_blob_git_sha1": "2c2fc16a60d2d7b7cbe9e28df989af3dd742a19d",
            "source_schema": "mineru.content-list.pipeline.v1",
            "sanitized_contract": "mineru-native-structure.v1",
            "builder": "build_mineru_parsed_document_v1",
        },
    ],
    "excluded": {
        "qwen3_7_plus": ["semantic_arm", "model_judge", "fallback"],
        "allowed_only": "separately-approved-local-vlm-parser-upgrade",
    },
}

_INDEPENDENT_COMPONENT_PAYLOADS = {
    "model": (
        "vertical-falsification-semantic-model.v1",
        {
            "model": "deepseek-v4-flash",
            "endpoint": "https://api.deepseek.com/v1",
            "protocol": "openai_compatible",
        },
    ),
    "prompt": (
        "vertical-falsification-prompt.v1",
        {
            "contract": "596-1-schema60-ten-task-extraction.v1",
            "task_count": 10,
            "golden_blind": True,
        },
    ),
    "budget": (
        "vertical-falsification-budget.v1",
        {
            "baseline_provider_max": 6,
            "candidate_main_max": 8,
            "candidate_repair_max": 4,
            "total_hard_cap": 18,
            "fallback_calls": 0,
            "retry_calls": 0,
        },
    ),
    "normalizer": (
        "vertical-falsification-normalizer.v1",
        {
            "contract": "identity-string-normalizer.v1",
            "operation": "preserve-exact-value-snapshot",
        },
    ),
    "comparator": (
        "vertical-falsification-comparator.v1",
        {
            "contract": "exact-state-value-comparator.v1",
            "operation": "exact-tri-state-and-value-snapshot-equality",
        },
    ),
}
_INDEPENDENT_COMPONENT_HASHES = {
    name: canonical_hash(domain, payload)
    for name, (domain, payload) in _INDEPENDENT_COMPONENT_PAYLOADS.items()
}
_BASELINE_PARSER_HASH = (
    "af128bc04ce9d5f5996f0171d8238acd52e3c704ab71ad28fbce6b4fae043bfe"
)
_CANDIDATE_PARSER_HASH = (
    "dadc77bf96d6e443d2785709513c302adb89a89c02f058b7982f558c3795445e"
)
_ADMISSION_RECEIPT_DIGEST = _sha(980)
_GOLDEN_596_PATH = (
    Path(__file__).resolve().parents[2]
    / "dataset"
    / "goldenset"
    / "gs-s0q-596-v1"
    / "596.jsonl"
)


def _golden_596_bytes() -> bytes:
    return _GOLDEN_596_PATH.read_bytes()


def _admitted_parse_artifact(
    role: Literal["terms", "brochure", "rate_table"],
) -> vf.AdmittedParseArtifactV1:
    source_sha256 = _SOURCE_BY_ROLE[role]
    subject = ParseSubjectV1(
        space_id="space-061",
        source_id=f"source-{role}",
        source_revision_id=f"revision-{role}",
        product_version_id="596-1",
        material_profile_id=f"596-1-{role.replace('_', '-')}-v1",
        material_profile_binding_hash=_sha(10),
        source_sha256=source_sha256,
        raw_artifact_hash=_sha(11),
        canonical_envelope_hash=_sha(12),
    )
    parser = ParserIdentityV1(
        parser_id="mineru-cloud-pipeline",
        parser_profile_ref=(
            "approved-parser-profile:parser-neutral-bounded-upgrade.v1"
        ),
        parser_build_id="mineru-060",
        parser_config_hash=_sha(13),
    )
    attempt = ParseAttemptV1(
        attempt_id=f"attempt-{role}",
        attempt_number=2,
        attempt_role="bounded_upgrade",
        generation=0,
    )
    snapshot = ParseSnapshotV1(
        snapshot_id=f"snapshot-{role}",
        snapshot_generation=0,
        pagination_complete=True,
        concurrent_mutation_fence_hash=_sha(14),
    )
    output_facts = ParseOutputFactsV1(
        privacy_policy_ref="privacy-policy:source-revision-private-processing.v1",
        output_policy_ref="output-policy:parsed-artifact-internal-only.v1",
        body_text_included=False,
        secrets_included=False,
        absolute_paths_included=False,
        unknown_vendor_fields_included=False,
    )
    page = ParsePageV1(
        page_id=f"page-{role}",
        order_index=0,
        locator=PageLocatorV1(page_number=1),
        content_hash=_sha(15),
        structure_hash=_sha(16),
    )
    evidence = CapabilityEvidenceV1(
        capability="ordered_pages",
        subject_refs=(page.page_id,),
    )
    document = ParsedDocumentV1(
        contract="parsed-document.v1",
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output_facts,
        pages=(page,),
        blocks=(),
        tables=(),
        cells=(),
        capability_evidence=(evidence,),
        warnings=(),
        unsupported=(),
    )
    manifest = ParseManifestV1(
        contract="parse-manifest.v1",
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output_facts,
        document_hash=document.document_hash,
        ordered_page_ids=(page.page_id,),
        ordered_block_ids=(),
        ordered_table_ids=(),
        ordered_cell_ids=(),
        element_counts=ParseElementCountsV1(
            pages=1,
            blocks=0,
            tables=0,
            cells=0,
        ),
        required_capabilities=("ordered_pages",),
        satisfied_capabilities=("ordered_pages",),
        unsatisfied_capabilities=(),
        capability_evidence=(evidence,),
        warnings=(),
        unsupported=(),
    )
    decision = ParseQualityDecisionV1(
        contract="parse-quality-decision.v1",
        subject=subject,
        manifest_hash=manifest.manifest_hash,
        parse_policy_receipt=None,
        measured_facts=ParseQualityMeasuredFactsV1(
            threshold_version="parse-quality-structural.v1",
            required_capabilities=("ordered_pages",),
            satisfied_capabilities=("ordered_pages",),
            unsatisfied_capabilities=(),
            trigger_conditions=(),
            attempts_exhausted=True,
        ),
        decision="ADMIT",
        reason_codes=(),
        admitted_attempt_id=attempt.attempt_id,
        next_parser_profile_ref=None,
        review_item=None,
    )
    intake_type = getattr(vf, "AdmittedParseArtifactV1", None)
    assert intake_type is not None
    return cast(
        vf.AdmittedParseArtifactV1,
        intake_type(
            role=role,
            source_sha256=source_sha256,
            artifact_sha256=document.document_hash,
            document=document,
            manifest=manifest,
            decision=decision,
            manifest_sha256=manifest.manifest_hash,
            decision_sha256=decision.decision_hash,
        ),
    )


def _admitted_parse_artifacts() -> tuple[vf.AdmittedParseArtifactV1, ...]:
    return tuple(
        _admitted_parse_artifact(role)
        for role in cast(
            tuple[Literal["terms", "brochure", "rate_table"], ...],
            ("terms", "brochure", "rate_table"),
        )
    )


def _unvalidated_resolution_shell(
    original: vf.AdmittedParseArtifactV1,
) -> MaterialProfileResolution:
    profile_source = SimpleNamespace(sha256=original.source_sha256)
    return MaterialProfileResolution.model_construct(
        catalog_hash=vf.APPROVED_MATERIAL_PROFILE_CATALOG_SHA256,
        request=SimpleNamespace(
            space_id=original.document.subject.space_id,
            product_version="596-1",
            source=profile_source,
        ),
        profile=SimpleNamespace(
            profile_id="596-1-terms-v1",
            material_role="terms",
            source=profile_source,
            required_parse_capabilities=(
                vf.EXPECTED_596_1_REQUIRED_CAPABILITIES["terms"]
            ),
        ),
        parse_policy_receipt=SimpleNamespace(
            required_parse_capabilities=(
                vf.EXPECTED_596_1_REQUIRED_CAPABILITIES["terms"]
            )
        ),
        binding_hash=original.document.subject.material_profile_binding_hash,
    )


def _arm_identity(*, parser_sha: str | None = None) -> ArmInputIdentityV1:
    return ArmInputIdentityV1(
        product_version_id="596-1",
        source_sha256=(
            _SOURCE_BY_ROLE["terms"],
            _SOURCE_BY_ROLE["brochure"],
            _SOURCE_BY_ROLE["rate_table"],
        ),
        schema_version=vf.APPROVED_SCHEMA_VERSION,
        schema_sha256=vf.APPROVED_SCHEMA_REGISTRY_SHA256,
        parser_identity_sha256=(
            parser_sha
            or _BASELINE_PARSER_HASH
        ),
        model_identity_sha256=_INDEPENDENT_COMPONENT_HASHES["model"],
        semantic_model_id="DeepSeek V4 Flash",
        semantic_api_base="https://api.deepseek.com/v1",
        prompt_identity_sha256=_INDEPENDENT_COMPONENT_HASHES["prompt"],
        budget_identity_sha256=_INDEPENDENT_COMPONENT_HASHES["budget"],
        normalizer_identity_sha256=_INDEPENDENT_COMPONENT_HASHES["normalizer"],
        comparator_identity_sha256=_INDEPENDENT_COMPONENT_HASHES["comparator"],
        arm_profile_sha256=APPROVED_ARM_PROFILE_SHA256,
        parse_artifact_receipt_digest_sha256=_ADMISSION_RECEIPT_DIGEST,
        parser_id=(
            "pdfplumber" if parser_sha is None else "mineru-cloud-pipeline"
        ),
        parser_mode="default" if parser_sha is None else "bounded_upgrade",
        parser_attempt=1 if parser_sha is None else 2,
    )


def _evidence(*, rate: bool = False) -> EvidenceLocatorV1:
    return EvidenceLocatorV1(
        source_sha256=_SOURCE_BY_ROLE["rate_table" if rate else "terms"],
        quote_snapshot="covered fact",
        page_number=1,
        block_id="block-1",
        table_id="table-1" if rate else None,
        cell_id="cell-1" if rate else None,
        row_index=1 if rate else None,
        column_index=1 if rate else None,
        header_snapshot="年龄" if rate else None,
        row_span=1 if rate else None,
        column_span=1 if rate else None,
    )


def _golden() -> GoldenSetV1:
    critical_priorities = {
        field_id: priority
        for priority, field_id, _field_name in _INDEPENDENT_CRITICAL18_FIELDS
    }
    return GoldenSetV1(
        product_version_id="596-1",
        schema_version=vf.APPROVED_SCHEMA_VERSION,
        schema_sha256=vf.APPROVED_SCHEMA_REGISTRY_SHA256,
        source_sha256=(
            _SOURCE_BY_ROLE["terms"],
            _SOURCE_BY_ROLE["brochure"],
            _SOURCE_BY_ROLE["rate_table"],
        ),
        release_hash=_INDEPENDENT_GOLDEN_RELEASE_HASH,
        artifact_hash=_INDEPENDENT_GOLDEN_ARTIFACT_HASH,
        approval_subject_hash=_INDEPENDENT_GOLDEN_APPROVAL_SUBJECT_HASH,
        golden_596_jsonl_sha256=vf.APPROVED_GOLDEN_596_JSONL_SHA256,
        golden_content_digest_sha256=_sha(981),
        critical18_contract_id="critical18-candidate.v1",
        critical18_contract_sha256=APPROVED_CRITICAL18_SHA256,
        fields=tuple(
            GoldenFieldV1(
                field_id=field_id,
                expected_state="present",
                expected_value=f"value-{index:03d}",
                critical=critical_priorities.get(field_id),
                rate=field_id in _INDEPENDENT_RATE_FIELD_IDS,
            )
            for index, field_id in enumerate(_INDEPENDENT_SCHEMA60_FIELD_IDS, start=1)
        ),
    )


def _outputs() -> tuple[ArmFieldOutputV1, ...]:
    return tuple(
        ArmFieldOutputV1(
            field_id=field_id,
            state="present",
            value_snapshot=f"value-{index:03d}",
            evidence=(_evidence(rate=field_id in _INDEPENDENT_RATE_FIELD_IDS),),
        )
        for index, field_id in enumerate(_INDEPENDENT_SCHEMA60_FIELD_IDS, start=1)
    )


def _field_index(field_id: str) -> int:
    return _INDEPENDENT_SCHEMA60_FIELD_IDS.index(field_id)


def _replace_output_value(
    fields: tuple[ArmFieldOutputV1, ...],
    index: int,
    value_snapshot: str,
) -> tuple[ArmFieldOutputV1, ...]:
    changed = list(fields)
    changed[index] = replace(changed[index], value_snapshot=value_snapshot)
    return tuple(changed)


def _replace_output_evidence(
    fields: tuple[ArmFieldOutputV1, ...],
    index: int,
    evidence: tuple[EvidenceLocatorV1, ...],
) -> tuple[ArmFieldOutputV1, ...]:
    changed = list(fields)
    changed[index] = replace(changed[index], evidence=evidence)
    return tuple(changed)


def _replace_output_with_unknown(
    fields: tuple[ArmFieldOutputV1, ...],
    index: int,
) -> tuple[ArmFieldOutputV1, ...]:
    changed = list(fields)
    changed[index] = replace(
        changed[index],
        state="unknown",
        value_snapshot=None,
    )
    return tuple(changed)


def _score(
    *,
    baseline_fields: tuple[ArmFieldOutputV1, ...] | None = None,
    candidate_fields: tuple[ArmFieldOutputV1, ...] | None = None,
    ledger: CallBudgetLedgerV1 | None = None,
    baseline_output: object | None = None,
    candidate_output: object | None = None,
    golden: GoldenSetV1 | None = None,
) -> VerticalFalsificationDecisionV1:
    baseline = baseline_output or freeze_arm_output(
        arm="baseline",
        identity=_arm_identity(),
        fields=baseline_fields or _outputs(),
    )
    candidate = candidate_output or freeze_arm_output(
        arm="candidate",
        identity=_arm_identity(parser_sha=_CANDIDATE_PARSER_HASH),
        fields=candidate_fields or _outputs(),
    )
    return vf._score_admitted_frozen_outputs(
        baseline_output=baseline,
        candidate_output=candidate,
        golden=golden or _golden(),
        ledger=ledger
        or CallBudgetLedgerV1(
            baseline_calls=6,
            candidate_main_calls=8,
            candidate_repair_calls=4,
        ),
        admission_receipt_digest_sha256=_ADMISSION_RECEIPT_DIGEST,
    )


def test_exact_mineru_contract_still_requires_three_admitted_artifacts_before_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _forbid_open(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("dependency admission must not read Golden/files")

    monkeypatch.setattr(builtins, "open", _forbid_open)

    result = admit_596_1_vertical_falsification()

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert len(REQUIRED_PUBLIC_CONTRACTS) == 1
    assert result.missing_contracts == (ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID,)
    assert result.provider_calls == 0
    assert result.golden_reads == 0
    assert result.terminal_outcome is None


def test_fake_python_release_module_has_no_effect_on_quality_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (mineru_requirement,) = REQUIRED_PUBLIC_CONTRACTS
    real_import = __import__(
        "insurance_harness.compiler.native_mineru_cloud",
        fromlist=("native_mineru_cloud",),
    )

    def _import_contract(module: str) -> object:
        if module == mineru_requirement.module:
            return real_import
        raise AssertionError(f"unexpected import: {module}")

    monkeypatch.setattr(
        "insurance_harness.knowledge_compiler.vertical_falsification.import_module",
        _import_contract,
    )

    monkeypatch.setitem(
        __import__("sys").modules,
        "insurance_harness.knowledge_compiler.candidate_releases",
        SimpleNamespace(
            NamedHumanCandidateReleaseV1=object(),
            verify_named_human_release=lambda: None,
        ),
    )

    result = admit_596_1_vertical_falsification(
        admitted_parse_artifacts=_admitted_parse_artifacts(),
    )

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert result.missing_contracts == (ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID,)
    assert (result.provider_calls, result.golden_reads) == (0, 0)


def test_incomplete_public_symbols_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _import_incomplete_contract(module: str) -> object:
        del module
        return SimpleNamespace()

    monkeypatch.setattr(
        "insurance_harness.knowledge_compiler.vertical_falsification.import_module",
        _import_incomplete_contract,
    )

    result = admit_596_1_vertical_falsification()

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert result.missing_contracts == tuple(
        requirement.contract_id for requirement in REQUIRED_PUBLIC_CONTRACTS
    ) + (ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID,)
    assert result.terminal_outcome is None


def test_broken_060_import_is_a_typed_zero_io_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _broken_import(module: str) -> object:
        del module
        raise RuntimeError("credential-value:absolute-path-value")

    monkeypatch.setattr(
        "insurance_harness.knowledge_compiler.vertical_falsification.import_module",
        _broken_import,
    )

    result = admit_596_1_vertical_falsification()

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert result.missing_contracts == (
        REQUIRED_PUBLIC_CONTRACTS[0].contract_id,
        ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID,
    )
    assert (result.provider_calls, result.golden_reads) == (0, 0)
    assert "credential-value" not in repr(result)
    assert "absolute-path-value" not in repr(result)


def test_exception_raising_060_symbol_lookup_is_a_typed_zero_io_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ExplosiveModule:
        def __getattr__(self, name: str) -> object:
            del name
            raise RuntimeError("credential-value:absolute-path-value")

    monkeypatch.setattr(
        "insurance_harness.knowledge_compiler.vertical_falsification.import_module",
        lambda _module: _ExplosiveModule(),
    )

    result = admit_596_1_vertical_falsification()

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert result.missing_contracts == (
        REQUIRED_PUBLIC_CONTRACTS[0].contract_id,
        ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID,
    )
    assert (result.provider_calls, result.golden_reads) == (0, 0)
    assert "credential-value" not in repr(result)
    assert "absolute-path-value" not in repr(result)


def test_captured_060_exports_are_never_read_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_module = __import__(
        "insurance_harness.compiler.native_mineru_cloud",
        fromlist=("native_mineru_cloud",),
    )

    class _SecondReadExplodes:
        def __init__(self) -> None:
            self.reads: dict[str, int] = {}

        def __getattr__(self, name: str) -> object:
            count = self.reads.get(name, 0) + 1
            self.reads[name] = count
            if count > 1:
                raise RuntimeError("credential-value:absolute-path-value")
            return getattr(real_module, name)

    monkeypatch.setattr(
        "insurance_harness.knowledge_compiler.vertical_falsification.import_module",
        lambda _module: _SecondReadExplodes(),
    )

    result = admit_596_1_vertical_falsification(
        admitted_parse_artifacts=_admitted_parse_artifacts(),
    )

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert "credential-value" not in repr(result)
    assert "absolute-path-value" not in repr(result)


def test_mineru_public_symbol_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (mineru_requirement,) = REQUIRED_PUBLIC_CONTRACTS

    def _import_with_drift(module: str) -> object:
        if module == mineru_requirement.module:
            exported = {
                symbol: object()
                for symbol in mineru_requirement.symbols
                if symbol != "ParseQualityDecisionV1"
            }
            return SimpleNamespace(**exported)
        raise AssertionError(f"unexpected import: {module}")

    monkeypatch.setattr(
        "insurance_harness.knowledge_compiler.vertical_falsification.import_module",
        _import_with_drift,
    )

    result = admit_596_1_vertical_falsification()

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert result.missing_contracts == (
        mineru_requirement.contract_id,
        ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID,
    )
    assert (result.provider_calls, result.golden_reads) == (0, 0)
    assert result.terminal_outcome is None


def test_three_untrusted_hash_claims_do_not_open_quality_readiness() -> None:
    result = admit_596_1_vertical_falsification(
        admitted_parse_artifact_sha256=(_sha(101), _sha(102), _sha(103)),
    )

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert result.missing_contracts == (ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID,)
    assert (result.provider_calls, result.golden_reads) == (0, 0)


def test_manually_constructed_admit_receipts_cannot_open_quality_readiness() -> None:
    result = admit_596_1_vertical_falsification(
        admitted_parse_artifacts=_admitted_parse_artifacts(),
    )

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert result.missing_contracts == (ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID,)
    assert (result.provider_calls, result.golden_reads) == (0, 0)


def test_unvalidated_replay_authority_fails_before_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipts = list(_admitted_parse_artifacts())
    original = receipts[0]
    receipts[0] = replace(
        original,
        sanitized_structure=b"{}",
        raw_structure_sha256=original.document.subject.raw_artifact_hash,
        sanitized_structure_sha256=_sha(999),
        material_profile_resolution=_unvalidated_resolution_shell(original),
    )
    native_mineru = __import__(
        "insurance_harness.compiler.native_mineru_cloud",
        fromlist=("native_mineru_cloud",),
    )
    real_builder = cast(
        Callable[
            ...,
            tuple[ParsedDocumentV1, ParseManifestV1, ParseQualityDecisionV1],
        ],
        vars(native_mineru)["build_mineru_parsed_document_v1"],
    )
    replay_calls = 0

    def _replay(
        *args: Any, **kwargs: Any
    ) -> tuple[ParsedDocumentV1, ParseManifestV1, ParseQualityDecisionV1]:
        nonlocal replay_calls
        replay_calls += 1
        return real_builder(*args, **kwargs)

    monkeypatch.setattr(native_mineru, "build_mineru_parsed_document_v1", _replay)

    result = admit_596_1_vertical_falsification(
        admitted_parse_artifacts=tuple(receipts),
    )

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert result.missing_contracts == (ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID,)
    assert replay_calls == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda receipt: replace(
            receipt,
            material_profile_resolution=MaterialProfileResolution.model_construct(
                profile="bad-profile"
            ),
        ),
        lambda receipt: replace(
            receipt,
            document=ParsedDocumentV1.model_construct(subject="bad-subject"),
        ),
        lambda receipt: replace(
            receipt,
            manifest=ParseManifestV1.model_construct(subject="bad-subject"),
        ),
        lambda receipt: replace(
            receipt,
            decision=ParseQualityDecisionV1.model_construct(subject="bad-subject"),
        ),
    ],
)
def test_malformed_nested_replay_dtos_fail_closed_without_raw_exception(
    mutate: Callable[[vf.AdmittedParseArtifactV1], vf.AdmittedParseArtifactV1],
) -> None:
    receipts = list(_admitted_parse_artifacts())
    original = receipts[0]
    replay_backed = replace(
        original,
        sanitized_structure=b"{}",
        raw_structure_sha256=original.document.subject.raw_artifact_hash,
        sanitized_structure_sha256=_sha(999),
        material_profile_resolution=_unvalidated_resolution_shell(original),
    )
    receipts[0] = mutate(replay_backed)

    result = admit_596_1_vertical_falsification(
        admitted_parse_artifacts=tuple(receipts),
    )

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert result.missing_contracts == (ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID,)
    assert (result.provider_calls, result.golden_reads) == (0, 0)


def test_missing_060_module_is_a_typed_zero_io_block() -> None:
    script = r'''
import sys
from importlib.abc import MetaPathFinder

class BlockNativeMinerU(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "insurance_harness.compiler.native_mineru_cloud":
            raise ModuleNotFoundError(fullname)
        return None

sys.meta_path.insert(0, BlockNativeMinerU())
from insurance_harness.knowledge_compiler.vertical_falsification import (
    ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID,
    REQUIRED_PUBLIC_CONTRACTS,
    admit_596_1_vertical_falsification,
)
result = admit_596_1_vertical_falsification()
assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
assert result.missing_contracts == (
    REQUIRED_PUBLIC_CONTRACTS[0].contract_id,
    ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID,
)
assert (result.provider_calls, result.golden_reads) == (0, 0)
'''
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "mutate",
    [
        lambda receipt: replace(receipt, role="brochure"),
        lambda receipt: replace(receipt, source_sha256=_sha(999)),
        lambda receipt: replace(receipt, artifact_sha256=_sha(999)),
        lambda receipt: replace(receipt, manifest_sha256=_sha(999)),
        lambda receipt: replace(receipt, decision_sha256=_sha(999)),
        lambda receipt: replace(
            receipt,
            decision=receipt.decision.model_copy(update={"decision": "BLOCK"}),
        ),
    ],
)
def test_wrong_role_source_hash_or_non_admit_receipt_fails_closed(
    mutate: Callable[
        [vf.AdmittedParseArtifactV1], vf.AdmittedParseArtifactV1
    ],
) -> None:
    receipts = list(_admitted_parse_artifacts())
    receipts[0] = mutate(receipts[0])

    result = admit_596_1_vertical_falsification(
        admitted_parse_artifacts=tuple(receipts),
    )

    assert result.status == "BLOCKED_ON_REQUIRED_CONTRACTS"
    assert result.missing_contracts == (ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID,)


@pytest.mark.parametrize(
    "artifacts",
    [
        (),
        (_sha(101), _sha(102)),
        (_sha(101), _sha(101), _sha(103)),
        (_sha(101), _sha(102), "not-a-sha"),
        (_sha(101), _sha(102), _sha(103), _sha(104)),
    ],
)
def test_parse_artifact_admission_requires_exact_three_unique_hashes(
    artifacts: tuple[str, ...],
) -> None:
    result = admit_596_1_vertical_falsification(
        admitted_parse_artifact_sha256=artifacts,
    )

    assert ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID in result.missing_contracts
    assert (result.provider_calls, result.golden_reads) == (0, 0)


def test_exact_call_budget_is_admitted_without_fallback_or_retry() -> None:
    decision = check_call_budget(
        CallBudgetLedgerV1(
            baseline_calls=6,
            candidate_main_calls=8,
            candidate_repair_calls=4,
            fallback_calls=0,
            retry_calls=0,
        )
    )

    assert decision.status == "WITHIN_BUDGET"
    assert decision.reason_codes == ()
    assert decision.total_calls == 18


@pytest.mark.parametrize("invalid", [True, 1.0, float("nan")])
def test_call_budget_rejects_bool_float_and_nan(invalid: object) -> None:
    with pytest.raises(ValueError, match="finite non-negative integers"):
        CallBudgetLedgerV1(
            baseline_calls=cast(int, invalid),
            candidate_main_calls=8,
            candidate_repair_calls=4,
        )


def test_exact_golden_bytes_parser_rejects_one_byte_mutation() -> None:
    approved = _golden_596_bytes()
    mutated = approved.replace(b'"product_id":"596"', b'"product_id":"597"', 1)

    assert vf._parse_approved_golden_bytes(approved) is not None
    assert vf._parse_approved_golden_bytes(mutated) is None


def test_public_scorer_replays_admission_before_touching_golden_bytes() -> None:
    class _ForbiddenGoldenBytes:
        def __bytes__(self) -> bytes:
            raise AssertionError("Golden bytes inspected before admission")

    baseline = freeze_arm_output(
        arm="baseline",
        identity=_arm_identity(),
        fields=_outputs(),
    )
    candidate = freeze_arm_output(
        arm="candidate",
        identity=_arm_identity(parser_sha=_CANDIDATE_PARSER_HASH),
        fields=_outputs(),
    )

    decision = score_vertical_falsification(
        baseline_output=baseline,
        candidate_output=candidate,
        golden_596_jsonl_bytes=_ForbiddenGoldenBytes(),
        admitted_parse_artifacts=_admitted_parse_artifacts(),
        ledger=CallBudgetLedgerV1(6, 8, 4),
    )

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert decision.reason_codes == ("PARSE_ARTIFACTS_NOT_ADMITTED",)


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        ({"baseline_calls": 7}, "BASELINE_CALL_BUDGET_EXCEEDED"),
        ({"candidate_main_calls": 9}, "CANDIDATE_MAIN_CALL_BUDGET_EXCEEDED"),
        ({"candidate_repair_calls": 5}, "CANDIDATE_REPAIR_CALL_BUDGET_EXCEEDED"),
        ({"fallback_calls": 1}, "FALLBACK_CALL_FORBIDDEN"),
        ({"retry_calls": 1}, "EXTRA_RETRY_FORBIDDEN"),
    ],
)
def test_call_budget_violation_is_typed_no_go(
    overrides: dict[str, int],
    reason_code: str,
) -> None:
    values = {
        "baseline_calls": 6,
        "candidate_main_calls": 8,
        "candidate_repair_calls": 4,
        "fallback_calls": 0,
        "retry_calls": 0,
        **overrides,
    }

    decision = check_call_budget(CallBudgetLedgerV1(**values))

    assert decision.status == "MVP_VERTICAL_SLICE_NO_GO"
    assert reason_code in decision.reason_codes


def test_arm_output_is_c0_stable_and_byte_mutation_sensitive() -> None:
    fields = (
        ArmFieldOutputV1(
            field_id="field-001",
            state="present",
            value_snapshot="10 CNY",
            evidence=(_evidence(),),
        ),
    )

    first = freeze_arm_output(
        arm="baseline",
        identity=_arm_identity(),
        fields=fields,
    )
    same = freeze_arm_output(
        arm="baseline",
        identity=_arm_identity(),
        fields=fields,
    )
    changed = freeze_arm_output(
        arm="baseline",
        identity=_arm_identity(),
        fields=(replace(fields[0], value_snapshot="11 CNY"),),
    )

    assert first.output_hash == same.output_hash
    assert first.output_hash != changed.output_hash
    assert verify_arm_output_hash(first)
    assert not verify_arm_output_hash(replace(first, output_hash=_sha(999)))


def test_all_frozen_quality_gates_stop_pending_real_go_human_release() -> None:
    decision = _score()

    scorer_parameters = signature(score_vertical_falsification).parameters
    assert "golden_596_jsonl_bytes" in scorer_parameters
    assert "admitted_parse_artifacts" in scorer_parameters
    assert "golden" not in scorer_parameters
    assert not {"release", "release_ref", "head", "activation_receipt"} & set(
        scorer_parameters
    )
    assert (
        decision.terminal_outcome
        == "QUALITY_GATES_PASS_PENDING_HUMAN_RELEASE"
    )
    assert decision.reason_codes == ()
    assert decision.candidate_metrics.denominator == 60
    assert decision.candidate_metrics.critical_denominator == 18
    assert decision.candidate_metrics.tri_state_correct == 60
    assert decision.candidate_metrics.normalized_value_correct == 60
    assert decision.candidate_metrics.normalized_value_denominator == 60
    assert decision.candidate_metrics.abstentions == 0
    assert decision.candidate_metrics.misses == 0
    assert decision.candidate_metrics.hallucinations == 0
    assert decision.candidate_metrics.wrong_values == 0
    assert decision.candidate_metrics.exact_field_correct == 60
    assert decision.candidate_metrics.tri_state_correct_basis_points == 10_000
    assert decision.candidate_metrics.normalized_value_correct_basis_points == 10_000
    assert decision.candidate_metrics.abstention_basis_points == 0
    assert decision.candidate_metrics.known_evidence_basis_points == 10_000


def test_critical18_contract_rejects_substitution_even_when_count_remains_18() -> None:
    golden = _golden()
    changed = list(golden.fields)
    changed[0] = replace(
        changed[0],
        field_id="substituted-critical-field",
        critical="P0",
    )
    outputs = list(_outputs())
    outputs[0] = replace(outputs[0], field_id="substituted-critical-field")

    decision = _score(
        golden=replace(golden, fields=tuple(changed)),
        baseline_fields=tuple(outputs),
        candidate_fields=tuple(outputs),
    )

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert "CRITICAL18_CONTRACT_MISMATCH" in decision.reason_codes


def test_critical18_contract_uses_the_exact_approved_ordered_field_tuple() -> None:
    assert APPROVED_CRITICAL18_FIELD_IDS == _INDEPENDENT_CRITICAL18_FIELD_IDS == (
        "clause_version",
        "reduced_paid_up",
        "reinstatement",
        "zh_0b3894ed2a",
        "zh_74aa1b9c93",
        "zh_d62301d84c",
        "zh_e1bea0527a",
        "claim_filing_requirements",
        "exclusions_official",
        "external_drug_coverage",
        "waiting_period_claim_handling",
        "zh_09a5d9e54e",
        "zh_3a3e6520a3",
        "zh_3d8424595d",
        "zh_4a789b1d6f",
        "zh_7d7fe38f09",
        "zh_7fe8603c08",
        "zh_f32c510a5e",
    )

    payload = {
        "contract": "critical18-candidate.v1",
        "schema_version": "v1.1+b31a411c621c",
        "source": "golden-maintenance-frozen-p0-7-p1-11-allowlist",
        "fields": tuple(
            {
                "priority": priority,
                "field_id": field_id,
                "field_name": field_name,
            }
            for priority, field_id, field_name in _INDEPENDENT_CRITICAL18_FIELDS
        ),
    }
    assert (
        canonical_hash("critical18-candidate.v1", payload)
        == APPROVED_CRITICAL18_SHA256
    )


def test_critical18_contract_rejects_order_drift() -> None:
    golden = _golden()
    changed = list(golden.fields)
    changed[0], changed[1] = changed[1], changed[0]

    decision = _score(golden=replace(golden, fields=tuple(changed)))

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert "SCHEMA60_FIELD_IDENTITY_MISMATCH" in decision.reason_codes


def test_schema60_and_arm_profile_authorities_use_independent_literal_preimages() -> None:
    assert len(_INDEPENDENT_SCHEMA60_FIELD_IDS) == 60
    assert len(set(_INDEPENDENT_SCHEMA60_FIELD_IDS)) == 60
    assert vf.APPROVED_SCHEMA60_FIELD_IDS == _INDEPENDENT_SCHEMA60_FIELD_IDS
    assert vf.APPROVED_RATE_FIELD_IDS == _INDEPENDENT_RATE_FIELD_IDS
    assert (
        canonical_hash(
            "vertical-falsification-arm-profile.v1",
            _INDEPENDENT_ARM_PROFILE_PAYLOAD,
        )
        == APPROVED_ARM_PROFILE_SHA256
    )
    assert vf.APPROVED_SEMANTIC_MODEL_IDENTITY_SHA256 == (
        _INDEPENDENT_COMPONENT_HASHES["model"]
    )
    assert vf.APPROVED_PROMPT_IDENTITY_SHA256 == (
        _INDEPENDENT_COMPONENT_HASHES["prompt"]
    )
    assert vf.APPROVED_BUDGET_IDENTITY_SHA256 == (
        _INDEPENDENT_COMPONENT_HASHES["budget"]
    )
    assert vf.APPROVED_NORMALIZER_IDENTITY_SHA256 == (
        _INDEPENDENT_COMPONENT_HASHES["normalizer"]
    )
    assert vf.APPROVED_COMPARATOR_IDENTITY_SHA256 == (
        _INDEPENDENT_COMPONENT_HASHES["comparator"]
    )


def test_self_consistent_foreign_noncritical_schema_field_is_no_go() -> None:
    foreign_field_id = "foreign-field"
    golden_fields = list(_golden().fields)
    baseline_fields = list(_outputs())
    candidate_fields = list(_outputs())
    index = next(
        index
        for index, field in enumerate(golden_fields)
        if field.critical is None
    )
    golden_fields[index] = replace(golden_fields[index], field_id=foreign_field_id)
    baseline_fields[index] = replace(
        baseline_fields[index],
        field_id=foreign_field_id,
    )
    candidate_fields[index] = replace(
        candidate_fields[index],
        field_id=foreign_field_id,
    )

    decision = _score(
        golden=replace(_golden(), fields=tuple(golden_fields)),
        baseline_fields=tuple(baseline_fields),
        candidate_fields=tuple(candidate_fields),
    )

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert "SCHEMA60_FIELD_IDENTITY_MISMATCH" in decision.reason_codes


def test_rate_field_cannot_be_declassified_to_remove_structure_evidence() -> None:
    rate_field_id = _INDEPENDENT_RATE_FIELD_IDS[0]
    index = _field_index(rate_field_id)
    golden_fields = list(_golden().fields)
    golden_fields[index] = replace(golden_fields[index], rate=False)
    outputs = _replace_output_evidence(
        _outputs(),
        index,
        (_evidence(rate=False),),
    )

    decision = _score(
        golden=replace(_golden(), fields=tuple(golden_fields)),
        baseline_fields=outputs,
        candidate_fields=outputs,
    )

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert "RATE_FIELD_AUTHORITY_MISMATCH" in decision.reason_codes
    assert "RATE_EVIDENCE_LOCATOR_INCOMPLETE" in decision.reason_codes


@pytest.mark.parametrize(
    "golden",
    [
        replace(_golden(), release_hash=_sha(971)),
        replace(_golden(), artifact_hash=_sha(972)),
        replace(_golden(), approval_subject_hash=_sha(973)),
        replace(_golden(), source_sha256=(_sha(974), _sha(975), _sha(976))),
    ],
)
def test_golden_authority_hashes_and_sources_are_not_caller_selectable(
    golden: GoldenSetV1,
) -> None:
    decision = _score(golden=golden)

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert "GOLDEN_AUTHORITY_MISMATCH" in decision.reason_codes


def test_score_receipt_binds_both_arms_golden_and_evaluator() -> None:
    baseline = freeze_arm_output(
        arm="baseline",
        identity=_arm_identity(),
        fields=_outputs(),
    )
    candidate = freeze_arm_output(
        arm="candidate",
        identity=_arm_identity(parser_sha=_CANDIDATE_PARSER_HASH),
        fields=_outputs(),
    )
    golden = _golden()

    decision = _score(
        baseline_output=baseline,
        candidate_output=candidate,
        golden=golden,
    )

    assert decision.baseline_output_hash == baseline.output_hash
    assert decision.candidate_output_hash == candidate.output_hash
    assert decision.golden_release_hash == golden.release_hash
    assert decision.golden_artifact_hash == golden.artifact_hash
    assert decision.golden_approval_subject_hash == golden.approval_subject_hash
    assert decision.golden_596_jsonl_sha256 == golden.golden_596_jsonl_sha256
    assert decision.golden_content_digest_sha256 == golden.golden_content_digest_sha256
    assert decision.admission_receipt_digest_sha256 == _ADMISSION_RECEIPT_DIGEST
    assert decision.evaluator_identity_sha256 == vf.APPROVED_EVALUATOR_IDENTITY_SHA256
    assert len(decision.score_receipt_hash) == 64
    assert (
        replace(decision, candidate_output_hash=_sha(977)).score_receipt_hash
        != decision.score_receipt_hash
    )
    assert (
        replace(decision, golden_artifact_hash=_sha(978)).score_receipt_hash
        != decision.score_receipt_hash
    )
    assert (
        replace(
            decision,
            admission_receipt_digest_sha256=_sha(979),
        ).score_receipt_hash
        != decision.score_receipt_hash
    )


def test_arm_output_must_bind_the_recomputed_admission_receipt_digest() -> None:
    candidate = freeze_arm_output(
        arm="candidate",
        identity=replace(
            _arm_identity(parser_sha=_CANDIDATE_PARSER_HASH),
            parse_artifact_receipt_digest_sha256=_sha(982),
        ),
        fields=_outputs(),
    )

    decision = _score(candidate_output=candidate)

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert "PARSE_ARTIFACT_RECEIPT_BINDING_MISMATCH" in decision.reason_codes


@pytest.mark.parametrize(
    "golden",
    [
        replace(_golden(), critical18_contract_sha256=_sha(999)),
        replace(_golden(), critical18_contract_id="caller-critical18.v1"),
    ],
)
def test_critical18_contract_identity_is_not_caller_selectable(
    golden: GoldenSetV1,
) -> None:
    decision = _score(golden=golden)

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert "CRITICAL18_CONTRACT_MISMATCH" in decision.reason_codes


@pytest.mark.parametrize(
    "changed_identity",
    [
        replace(
            _arm_identity(parser_sha=_CANDIDATE_PARSER_HASH),
            arm_profile_sha256=_sha(999),
        ),
        replace(
            _arm_identity(parser_sha=_CANDIDATE_PARSER_HASH),
            parser_id="qwen-parser",
        ),
        replace(
            _arm_identity(parser_sha=_CANDIDATE_PARSER_HASH),
            parser_mode="default",
        ),
        replace(
            _arm_identity(parser_sha=_CANDIDATE_PARSER_HASH),
            parser_attempt=1,
        ),
        replace(
            _arm_identity(parser_sha=_CANDIDATE_PARSER_HASH),
            semantic_model_id="Qwen3.7 Plus",
        ),
        replace(
            _arm_identity(parser_sha=_CANDIDATE_PARSER_HASH),
            semantic_api_base="https://example.invalid/v1",
        ),
        replace(
            _arm_identity(parser_sha=_CANDIDATE_PARSER_HASH),
            normalizer_identity_sha256=_sha(999),
        ),
        replace(
            _arm_identity(parser_sha=_CANDIDATE_PARSER_HASH),
            comparator_identity_sha256=_sha(999),
        ),
    ],
)
def test_approved_arm_profile_and_shared_semantics_are_not_self_attested(
    changed_identity: ArmInputIdentityV1,
) -> None:
    candidate = freeze_arm_output(
        arm="candidate",
        identity=changed_identity,
        fields=_outputs(),
    )

    decision = _score(candidate_output=candidate)

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert any(
        reason in decision.reason_codes
        for reason in ("ARM_PROFILE_MISMATCH", "ARM_INPUT_IDENTITY_MISMATCH")
    )


@pytest.mark.parametrize(
    "field_name",
    [
        "model_identity_sha256",
        "prompt_identity_sha256",
        "budget_identity_sha256",
        "normalizer_identity_sha256",
        "comparator_identity_sha256",
    ],
)
def test_both_arms_cannot_self_attest_changed_profile_components(
    field_name: str,
) -> None:
    def _mutate(identity: ArmInputIdentityV1) -> ArmInputIdentityV1:
        if field_name == "model_identity_sha256":
            return replace(identity, model_identity_sha256=_sha(999))
        if field_name == "prompt_identity_sha256":
            return replace(identity, prompt_identity_sha256=_sha(999))
        if field_name == "budget_identity_sha256":
            return replace(identity, budget_identity_sha256=_sha(999))
        if field_name == "normalizer_identity_sha256":
            return replace(identity, normalizer_identity_sha256=_sha(999))
        return replace(identity, comparator_identity_sha256=_sha(999))

    baseline = freeze_arm_output(
        arm="baseline",
        identity=_mutate(_arm_identity()),
        fields=_outputs(),
    )
    candidate = freeze_arm_output(
        arm="candidate",
        identity=_mutate(_arm_identity(parser_sha=_CANDIDATE_PARSER_HASH)),
        fields=_outputs(),
    )

    decision = _score(
        baseline_output=baseline,
        candidate_output=candidate,
    )

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert "ARM_PROFILE_COMPONENT_MISMATCH" in decision.reason_codes


@pytest.mark.parametrize("drift", ["product", "sources", "schema", "model"])
def test_self_consistent_unapproved_arm_authority_is_no_go(drift: str) -> None:
    baseline_identity = _arm_identity()
    candidate_identity = _arm_identity(parser_sha=_CANDIDATE_PARSER_HASH)
    golden = _golden()
    if drift == "product":
        baseline_identity = replace(
            baseline_identity,
            product_version_id="foreign-product",
        )
        candidate_identity = replace(
            candidate_identity,
            product_version_id="foreign-product",
        )
        golden = replace(golden, product_version_id="foreign-product")
    elif drift == "sources":
        unapproved_sources = (_sha(901), _sha(902), _sha(903))
        baseline_identity = replace(
            baseline_identity,
            source_sha256=unapproved_sources,
        )
        candidate_identity = replace(
            candidate_identity,
            source_sha256=unapproved_sources,
        )
    elif drift == "schema":
        baseline_identity = replace(
            baseline_identity,
            schema_version="foreign-schema",
            schema_sha256=_sha(904),
        )
        candidate_identity = replace(
            candidate_identity,
            schema_version="foreign-schema",
            schema_sha256=_sha(904),
        )
        golden = replace(
            golden,
            schema_version="foreign-schema",
            schema_sha256=_sha(904),
        )
    else:
        baseline_identity = replace(
            baseline_identity,
            model_identity_sha256=_sha(905),
        )
        candidate_identity = replace(
            candidate_identity,
            model_identity_sha256=_sha(905),
        )
    baseline = freeze_arm_output(
        arm="baseline",
        identity=baseline_identity,
        fields=_outputs(),
    )
    candidate = freeze_arm_output(
        arm="candidate",
        identity=candidate_identity,
        fields=_outputs(),
    )

    decision = _score(
        baseline_output=baseline,
        candidate_output=candidate,
        golden=golden,
    )

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert (
        "ARM_PROFILE_COMPONENT_MISMATCH"
        if drift == "model"
        else "ARM_AUTHORITY_MISMATCH"
    ) in decision.reason_codes


def test_arms_cannot_reuse_or_swap_parser_roles() -> None:
    same_parser = freeze_arm_output(
        arm="candidate",
        identity=replace(
            _arm_identity(parser_sha=_CANDIDATE_PARSER_HASH),
            parser_identity_sha256=_BASELINE_PARSER_HASH,
        ),
        fields=_outputs(),
    )
    swapped_baseline = freeze_arm_output(
        arm="baseline",
        identity=replace(
            _arm_identity(),
            parser_id="mineru-cloud-pipeline",
            parser_mode="bounded_upgrade",
            parser_attempt=2,
        ),
        fields=_outputs(),
    )

    same_decision = _score(candidate_output=same_parser)
    swapped_decision = _score(baseline_output=swapped_baseline)

    assert "ARM_PROFILE_MISMATCH" in same_decision.reason_codes
    assert "ARM_PROFILE_MISMATCH" in swapped_decision.reason_codes


@pytest.mark.parametrize(
    ("candidate_output", "reason_code"),
    [
        (object(), "ARM_OUTPUT_NOT_FROZEN"),
        (
            replace(
                freeze_arm_output(
                    arm="candidate",
                    identity=_arm_identity(parser_sha=_CANDIDATE_PARSER_HASH),
                    fields=_outputs(),
                ),
                output_hash=_sha(999),
            ),
            "CANDIDATE_OUTPUT_HASH_MISMATCH",
        ),
    ],
)
def test_unfrozen_or_hash_mutated_output_is_no_go(
    candidate_output: object,
    reason_code: str,
) -> None:
    decision = _score(candidate_output=candidate_output)

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert reason_code in decision.reason_codes


def test_scorer_rejects_unfrozen_arm_before_inspecting_injected_golden() -> None:
    class _ForbiddenGolden:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"Golden inspected before arm freeze: {name}")

    decision = _score(
        candidate_output=object(),
        golden=cast(GoldenSetV1, _ForbiddenGolden()),
    )

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert decision.reason_codes == ("ARM_OUTPUT_NOT_FROZEN",)


@pytest.mark.parametrize(
    ("fields", "reason_code"),
    [
        (_outputs()[:-1], "CANDIDATE_FIELD_SET_NOT_EXACT_60"),
        (
            (*_outputs()[:-1], _outputs()[0]),
            "CANDIDATE_FIELD_SET_NOT_EXACT_60",
        ),
        (
            (*_outputs()[:-1], replace(_outputs()[-1], field_id="field-999")),
            "CANDIDATE_FIELD_IDENTITY_MISMATCH",
        ),
    ],
)
def test_missing_duplicate_or_extra_field_is_no_go(
    fields: tuple[ArmFieldOutputV1, ...],
    reason_code: str,
) -> None:
    decision = _score(candidate_fields=fields)

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert reason_code in decision.reason_codes


def test_critical_silent_error_is_no_go() -> None:
    fields = _replace_output_value(
        _outputs(),
        _field_index("clause_version"),
        "wrong-but-asserted",
    )

    decision = _score(candidate_fields=fields)

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert "CRITICAL_SILENT_ERROR" in decision.reason_codes


def test_candidate_critical_abstention_is_an_exact_semantic_error() -> None:
    fields = _replace_output_with_unknown(
        _outputs(),
        _field_index("clause_version"),
    )

    decision = _score(candidate_fields=fields)

    assert decision.candidate_metrics.critical_semantic_errors == 1
    assert "CRITICAL_SEMANTIC_ERROR" in decision.reason_codes


def test_noncritical_abstention_is_reported_without_inventing_a_new_go_gate() -> None:
    fields = _replace_output_with_unknown(_outputs(), 0)

    decision = _score(candidate_fields=fields)

    assert (
        decision.terminal_outcome
        == "QUALITY_GATES_PASS_PENDING_HUMAN_RELEASE"
    )
    assert decision.candidate_metrics.tri_state_correct == 59
    assert decision.candidate_metrics.abstentions == 1
    assert decision.candidate_metrics.misses == 1
    assert decision.candidate_metrics.exact_field_correct == 59
    assert decision.candidate_metrics.tri_state_correct_basis_points == 9_833
    assert decision.candidate_metrics.abstention_basis_points == 166


def test_golden_unknown_model_known_is_reported_and_blocks_as_hallucination() -> None:
    golden = _golden()
    changed = list(golden.fields)
    changed[0] = replace(
        changed[0], expected_state="unknown", expected_value=None
    )

    decision = _score(golden=replace(golden, fields=tuple(changed)))

    assert decision.candidate_metrics.hallucinations == 1
    assert "CANDIDATE_HALLUCINATION" in decision.reason_codes


def test_wrong_noncritical_value_is_reported_and_respects_95_percent_gate() -> None:
    fields = _replace_output_value(_outputs(), 0, "wrong-value")

    decision = _score(candidate_fields=fields)

    assert (
        decision.terminal_outcome
        == "QUALITY_GATES_PASS_PENDING_HUMAN_RELEASE"
    )
    assert decision.candidate_metrics.tri_state_correct == 60
    assert decision.candidate_metrics.normalized_value_correct == 59
    assert decision.candidate_metrics.wrong_values == 1
    assert decision.candidate_metrics.exact_field_correct == 59


def test_candidate_tri_state_correctness_below_57_of_60_is_no_go() -> None:
    fields = _outputs()
    for index in range(4):
        fields = _replace_output_with_unknown(fields, index)

    decision = _score(candidate_fields=fields)

    assert decision.candidate_metrics.tri_state_correct == 56
    assert "TRI_STATE_CORRECTNESS_BELOW_57_OF_60" in decision.reason_codes


def test_candidate_known_present_value_correctness_below_95_percent_is_no_go() -> None:
    fields = _outputs()
    for index in range(4):
        fields = _replace_output_value(fields, index, f"wrong-{index}")

    decision = _score(candidate_fields=fields)

    assert decision.candidate_metrics.normalized_value_correct == 56
    assert decision.candidate_metrics.normalized_value_denominator == 60
    assert "NORMALIZED_VALUE_CORRECTNESS_BELOW_95" in decision.reason_codes


def test_baseline_quality_is_diagnostic_and_does_not_block_a_valid_candidate() -> None:
    baseline_fields = _outputs()
    for index in range(4):
        baseline_fields = _replace_output_value(
            baseline_fields, index, f"baseline-wrong-{index}"
        )

    decision = _score(baseline_fields=baseline_fields)

    assert (
        decision.terminal_outcome
        == "QUALITY_GATES_PASS_PENDING_HUMAN_RELEASE"
    )
    assert decision.baseline_metrics.wrong_values == 4
    assert decision.candidate_metrics.wrong_values == 0


def test_critical_known_evidence_below_100_percent_is_no_go() -> None:
    fields = _replace_output_evidence(
        _outputs(),
        _field_index("clause_version"),
        (),
    )

    decision = _score(candidate_fields=fields)

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert "CRITICAL_KNOWN_EVIDENCE_INCOMPLETE" in decision.reason_codes


def test_unknown_cannot_count_as_evidence_for_a_critical_known_field() -> None:
    fields = _replace_output_with_unknown(
        _outputs(),
        _field_index("clause_version"),
    )

    decision = _score(candidate_fields=fields)

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert "CRITICAL_KNOWN_EVIDENCE_INCOMPLETE" in decision.reason_codes


def test_overall_known_evidence_below_95_percent_is_no_go() -> None:
    fields = _outputs()
    for index in range(4):
        fields = _replace_output_evidence(fields, index, ())

    decision = _score(candidate_fields=fields)

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert "OVERALL_KNOWN_EVIDENCE_BELOW_95" in decision.reason_codes


def test_overall_known_evidence_at_exactly_95_percent_is_admitted() -> None:
    fields = _outputs()
    for index in range(3):
        fields = _replace_output_evidence(fields, index, ())

    decision = _score(candidate_fields=fields)

    assert decision.candidate_metrics.known_with_evidence == 57
    assert decision.candidate_metrics.known_denominator == 60
    assert "OVERALL_KNOWN_EVIDENCE_BELOW_95" not in decision.reason_codes
    assert (
        decision.terminal_outcome
        == "QUALITY_GATES_PASS_PENDING_HUMAN_RELEASE"
    )


@pytest.mark.parametrize(
    "incomplete",
    [
        replace(_evidence(rate=True), page_number=None),
        replace(_evidence(rate=True), table_id=None),
        replace(_evidence(rate=True), cell_id=None),
        replace(_evidence(rate=True), row_index=None),
        replace(_evidence(rate=True), column_index=None),
        replace(_evidence(rate=True), header_snapshot=None),
        replace(_evidence(rate=True), row_span=None),
        replace(_evidence(rate=True), column_span=None),
    ],
)
def test_rate_evidence_missing_any_required_locator_is_no_go(
    incomplete: EvidenceLocatorV1,
) -> None:
    fields = _replace_output_evidence(
        _outputs(),
        _field_index(_INDEPENDENT_RATE_FIELD_IDS[0]),
        (incomplete,),
    )

    decision = _score(candidate_fields=fields)

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert "RATE_EVIDENCE_LOCATOR_INCOMPLETE" in decision.reason_codes


@pytest.mark.parametrize(
    "build_invalid",
    [
        lambda: replace(_evidence(rate=True), table_id=""),
        lambda: replace(_evidence(rate=True), cell_id="  "),
        lambda: replace(_evidence(rate=True), header_snapshot=""),
        lambda: replace(_evidence(rate=True), row_index=-1),
        lambda: replace(_evidence(rate=True), column_index=-1),
        lambda: replace(_evidence(rate=True), row_span=0),
        lambda: replace(_evidence(rate=True), column_span=0),
    ],
)
def test_evidence_locator_rejects_semantically_invalid_structure(
    build_invalid: Callable[[], EvidenceLocatorV1],
) -> None:
    with pytest.raises(ValueError, match="structure locator"):
        build_invalid()


def test_budget_violation_is_no_go_even_with_perfect_fields() -> None:
    decision = _score(
        ledger=CallBudgetLedgerV1(
            baseline_calls=7,
            candidate_main_calls=8,
            candidate_repair_calls=4,
        )
    )

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert "BASELINE_CALL_BUDGET_EXCEEDED" in decision.reason_codes


@pytest.mark.parametrize(
    "golden",
    [
        replace(_golden(), fields=_golden().fields[:-1]),
        replace(
            _golden(),
            fields=tuple(
                replace(field, critical=None)
                if field.field_id == _INDEPENDENT_CRITICAL18_FIELD_IDS[-1]
                else field
                for field in _golden().fields
            ),
        ),
    ],
)
def test_golden_denominators_must_be_exact_60_and_critical18(
    golden: GoldenSetV1,
) -> None:
    decision = _score(golden=golden)

    assert decision.terminal_outcome == "MVP_VERTICAL_SLICE_NO_GO"
    assert any(
        code in decision.reason_codes
        for code in (
            "GOLDEN_FIELD_SET_NOT_EXACT_60",
            "CRITICAL18_CONTRACT_MISMATCH",
        )
    )
