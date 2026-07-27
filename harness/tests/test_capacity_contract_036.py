"""OpenSpec 036 CAP0 Capacity Contract 验收测试（spec CAP0.1–CAP0.10）。

RED-first：本文件先于 ``insurance_harness.capacity`` 包编写；包缺失时
收集即失败。全部用例属 deterministic lane（无 DB、无网络）。
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from insurance_harness.canonical import canonical_hash
from insurance_harness.capacity import (
    CAPACITY_CONTRACT_REASON_CODES,
    CAPACITY_PROFILE_OBJECT_TYPE,
    CapacityContractError,
    CapacityEvidenceState,
    CapacityInputsV1,
    CapacityProfileV1,
    ReleaseProfileV1,
    capacity_profile_hash,
    evaluate_capacity_evidence,
    generate_launch_questionnaire,
    load_capacity_profile,
    write_launch_questionnaire,
)

RELEASE = "first-launch"

_DIMENSIONS = (
    "space_sources",
    "document_shape",
    "revision_amplification",
    "evidence_fragment_limits",
    "release_retention",
    "candidate_review",
    "active_query",
    "worker_provider",
)


def _inputs_data() -> dict[str, Any]:
    return {
        "space_sources": {
            "space_count": 3,
            "active_sources_per_space": 1000,
            "retained_sources_per_space": 1500,
            "peak_source_revisions_per_day_per_space": 50,
        },
        "document_shape": {
            "avg_document_bytes": 2_000_000,
            "p95_document_bytes": 10_000_000,
            "avg_chunks_per_document": "100",
            "p95_chunks_per_document": "400",
        },
        "revision_amplification": {
            "claims_per_source_revision": "18.5",
            "relations_per_source_revision": "6",
            "provenance_anchors_per_source_revision": "24.5",
        },
        "evidence_fragment_limits": {
            "max_logical_bytes_per_fragment": 262_144,
            "max_postgres_inline_bytes_per_fragment": 16_384,
        },
        "release_retention": {
            "retained_release_count": 24,
            "pages_per_release": 300,
            "blocks_per_page": 40,
            "release_retention_days": 365,
            "artifact_retention_days": 180,
        },
        "candidate_review": {
            "changed_claims_per_candidate": 400,
            "changed_pages_per_candidate": 60,
            "changed_bytes_per_candidate": 3_000_000,
            "max_manifest_bytes": 8_000_000,
            "review_queue_slo_hours": 48,
        },
        "active_query": {
            "sustained_qps": "2.5",
            "burst_qps": "10",
            "p95_response_bytes": 65_536,
            "p95_latency_ms": 800,
        },
        "worker_provider": {
            "worker_concurrency": 4,
            "provider_concurrency": 2,
            "max_queue_backlog": 500,
            "recovery_sla_hours": 4,
        },
    }


def _backfill_data() -> dict[str, Any]:
    """2026-07-27 业务方口头申报（declared）：约 3000 份 PDF/PPT 文档
    （区间 1000–5000）+ 约 30 万文本片段（区间 10–50 万）。"""

    return {
        "document_count": 3000,
        "total_text_fragments": 300_000,
        "total_bytes": 6_000_000_000,
        "target_completion_window_days": 60,
        "review_throughput_docs_per_day": 60,
    }


def _tier_data(
    *,
    source_kind: str = "declared",
    release: str = RELEASE,
    with_backfill: bool = True,
) -> dict[str, Any]:
    workloads: dict[str, Any] = {}
    if with_backfill:
        workloads["stock_backfill"] = _backfill_data()
    return {
        "inputs": _inputs_data(),
        "workloads": workloads,
        "source_kind": source_kind,
        "source_ref": (
            "业务方口头申报 2026-07-27（declared）：约 3000 份文档"
            "（区间 1000–5000，PDF/PPT 混合）+ 约 30 万文本片段（区间 10–50 万）"
        ),
        "measured_at": "2026-07-27T08:00:00+00:00",
        "applicable_release_profile": release,
    }


def _profile_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "contract": "cap0-capacity-profile/v1",
        "profile_version": 1,
        "deployment_id": "prod-launch-1",
        "launch": _tier_data(),
    }
    data.update(overrides)
    return data


def _profile(**overrides: Any) -> CapacityProfileV1:
    return CapacityProfileV1.model_validate(_profile_data(**overrides))


def _release(*, commitment: bool = False) -> ReleaseProfileV1:
    return ReleaseProfileV1(
        name=RELEASE, declares_customer_growth_commitment=commitment
    )


# ---------------------------------------------------------------------------
# CAP0.2 / CAP0.3 / CAP0.6 / CAP0.7 / CAP0.8 —— 模型 fail closed
# ---------------------------------------------------------------------------


class TestModelFailClosed:
    @pytest.mark.parametrize("dimension", _DIMENSIONS)
    def test_missing_dimension_rejected(self, dimension: str) -> None:
        data = _inputs_data()
        del data[dimension]
        with pytest.raises(ValidationError):
            CapacityInputsV1.model_validate(data)

    def test_missing_leaf_field_rejected(self) -> None:
        data = _inputs_data()
        del data["space_sources"]["space_count"]
        with pytest.raises(ValidationError):
            CapacityInputsV1.model_validate(data)

    def test_unknown_field_rejected(self) -> None:
        data = _inputs_data()
        data["space_sources"]["surprise"] = 1
        with pytest.raises(ValidationError):
            CapacityInputsV1.model_validate(data)

    def test_no_default_numbers(self) -> None:
        with pytest.raises(ValidationError):
            CapacityInputsV1.model_validate({})

    def test_negative_count_rejected(self) -> None:
        data = _inputs_data()
        data["space_sources"]["active_sources_per_space"] = -1
        with pytest.raises(ValidationError):
            CapacityInputsV1.model_validate(data)

    def test_float_ratio_rejected_with_guidance(self) -> None:
        data = _inputs_data()
        data["revision_amplification"]["claims_per_source_revision"] = 3.5
        with pytest.raises(ValidationError) as exc_info:
            CapacityInputsV1.model_validate(data)
        assert "float" in str(exc_info.value)

    def test_decimal_string_accepted(self) -> None:
        inputs = CapacityInputsV1.model_validate(_inputs_data())
        amplification = inputs.revision_amplification
        assert amplification.claims_per_source_revision == Decimal("18.5")

    def test_float_int_field_rejected(self) -> None:
        data = _inputs_data()
        data["space_sources"]["space_count"] = 3.0
        with pytest.raises(ValidationError):
            CapacityInputsV1.model_validate(data)

    def test_p95_document_bytes_below_avg_rejected(self) -> None:
        data = _inputs_data()
        data["document_shape"]["p95_document_bytes"] = 400_000
        with pytest.raises(ValidationError):
            CapacityInputsV1.model_validate(data)

    def test_p95_chunks_below_avg_rejected(self) -> None:
        data = _inputs_data()
        data["document_shape"]["p95_chunks_per_document"] = "1"
        with pytest.raises(ValidationError):
            CapacityInputsV1.model_validate(data)

    def test_burst_below_sustained_rejected(self) -> None:
        data = _inputs_data()
        data["active_query"]["burst_qps"] = "1"
        with pytest.raises(ValidationError):
            CapacityInputsV1.model_validate(data)

    def test_inline_above_logical_rejected(self) -> None:
        data = _inputs_data()
        data["evidence_fragment_limits"][
            "max_postgres_inline_bytes_per_fragment"
        ] = 262_145
        with pytest.raises(ValidationError):
            CapacityInputsV1.model_validate(data)

    def test_int_beyond_safe_range_rejected(self) -> None:
        data = _inputs_data()
        data["worker_provider"]["max_queue_backlog"] = 2**53
        with pytest.raises(ValidationError):
            CapacityInputsV1.model_validate(data)

    def test_naive_measured_at_rejected(self) -> None:
        tier = _tier_data()
        tier["measured_at"] = "2026-07-27T08:00:00"
        with pytest.raises(ValidationError):
            _profile(launch=tier)

    def test_blank_source_ref_rejected(self) -> None:
        tier = _tier_data()
        tier["source_ref"] = "   "
        with pytest.raises(ValidationError):
            _profile(launch=tier)

    def test_blank_release_profile_rejected(self) -> None:
        tier = _tier_data()
        tier["applicable_release_profile"] = ""
        with pytest.raises(ValidationError):
            _profile(launch=tier)

    def test_launch_without_stock_backfill_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _profile(launch=_tier_data(with_backfill=False))
        assert "stock_backfill" in str(exc_info.value)

    def test_declared_stress_breakpoint_rejected(self) -> None:
        stress = _tier_data(source_kind="declared", with_backfill=False)
        with pytest.raises(ValidationError):
            _profile(stress_breakpoint=stress)

    def test_measured_stress_breakpoint_accepted(self) -> None:
        stress = _tier_data(source_kind="measured", with_backfill=False)
        profile = _profile(stress_breakpoint=stress)
        assert profile.stress_breakpoint is not None

    def test_unknown_source_kind_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _profile(launch=_tier_data(source_kind="guessed"))

    def test_infeasible_backfill_plan_rejected(self) -> None:
        tier = _tier_data()
        tier["workloads"]["stock_backfill"][
            "review_throughput_docs_per_day"
        ] = 10
        with pytest.raises(ValidationError) as exc_info:
            _profile(launch=tier)
        assert "回填" in str(exc_info.value)

    def test_explicit_zero_backfill_accepted(self) -> None:
        tier = _tier_data()
        tier["workloads"]["stock_backfill"]["document_count"] = 0
        tier["workloads"]["stock_backfill"]["total_text_fragments"] = 0
        tier["workloads"]["stock_backfill"]["total_bytes"] = 0
        profile = _profile(launch=tier)
        launch = profile.launch
        assert launch is not None
        backfill = launch.workloads.stock_backfill
        assert backfill is not None and backfill.document_count == 0

    def test_empty_space_override_rejected(self) -> None:
        tier = _tier_data()
        tier["space_overrides"] = {"space-a": {}}
        with pytest.raises(ValidationError):
            _profile(launch=tier)

    def test_partial_space_override_accepted(self) -> None:
        tier = _tier_data()
        tier["space_overrides"] = {
            "space-a": {"document_shape": _inputs_data()["document_shape"]}
        }
        profile = _profile(launch=tier)
        base = _profile()
        assert capacity_profile_hash(profile) != capacity_profile_hash(base)

    @pytest.mark.parametrize("space_key", ["", "UPPER", "$evil", "空间"])
    def test_invalid_space_key_rejected(self, space_key: str) -> None:
        tier = _tier_data()
        tier["space_overrides"] = {
            space_key: {"document_shape": _inputs_data()["document_shape"]}
        }
        with pytest.raises(ValidationError):
            _profile(launch=tier)

    def test_frozen_assignment_rejected(self) -> None:
        profile = _profile()
        with pytest.raises(ValidationError):
            profile.profile_version = 2
        assert profile.profile_version == 1

    def test_missing_contract_marker_rejected(self) -> None:
        data = _profile_data()
        del data["contract"]
        with pytest.raises(ValidationError):
            CapacityProfileV1.model_validate(data)

    def test_wrong_contract_marker_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _profile(contract="capacity-profile/v2")

    @pytest.mark.parametrize("deployment_id", ["", "PROD", "$x"])
    def test_invalid_deployment_id_rejected(self, deployment_id: str) -> None:
        with pytest.raises(ValidationError):
            _profile(deployment_id=deployment_id)

    def test_zero_profile_version_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _profile(profile_version=0)


# ---------------------------------------------------------------------------
# CAP0.1 —— 内容寻址与 C0 集成
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_same_content_same_hash(self) -> None:
        first = capacity_profile_hash(_profile())
        second = capacity_profile_hash(_profile())
        assert first == second
        assert len(first) == 64 and first == first.lower()
        assert all(ch in "0123456789abcdef" for ch in first)

    def test_content_change_changes_hash(self) -> None:
        tier = _tier_data()
        tier["inputs"]["space_sources"]["space_count"] = 4
        assert capacity_profile_hash(_profile(launch=tier)) != (
            capacity_profile_hash(_profile())
        )

    def test_decimal_normalization_inherited_from_c0(self) -> None:
        tier = _tier_data()
        tier["inputs"]["revision_amplification"][
            "claims_per_source_revision"
        ] = "18.50"
        assert capacity_profile_hash(_profile(launch=tier)) == (
            capacity_profile_hash(_profile())
        )

    def test_hash_is_canonical_hash_of_python_dump(self) -> None:
        profile = _profile()
        expected = canonical_hash(
            CAPACITY_PROFILE_OBJECT_TYPE, profile.model_dump(mode="python")
        )
        assert CAPACITY_PROFILE_OBJECT_TYPE == "capacity-profile"
        assert capacity_profile_hash(profile) == expected


# ---------------------------------------------------------------------------
# CAP0.4 / CAP0.5 —— evaluator 三态矩阵（D-2026-07-26-1）
# ---------------------------------------------------------------------------


class TestEvidenceEvaluator:
    def test_declared_launch_unblocks_design_not_launch(self) -> None:
        result = evaluate_capacity_evidence(_profile(), _release())
        assert result.state is CapacityEvidenceState.SUFFICIENT_FOR_DESIGN
        assert result.design_unblocked is True
        assert result.launch_unblocked is False
        assert result.reasons == ("launch_declared_only",)

    def test_measured_launch_unblocks_launch(self) -> None:
        profile = _profile(launch=_tier_data(source_kind="measured"))
        result = evaluate_capacity_evidence(profile, _release())
        assert result.state is CapacityEvidenceState.SUFFICIENT_FOR_LAUNCH
        assert result.design_unblocked is True
        assert result.launch_unblocked is True
        assert result.reasons == ()

    def test_all_tiers_absent_is_insufficient(self) -> None:
        profile = CapacityProfileV1.model_validate(
            {
                "contract": "cap0-capacity-profile/v1",
                "profile_version": 1,
                "deployment_id": "prod-launch-1",
            }
        )
        result = evaluate_capacity_evidence(profile, _release())
        assert result.state is (
            CapacityEvidenceState.INSUFFICIENT_CAPACITY_EVIDENCE
        )
        assert result.design_unblocked is False
        assert result.launch_unblocked is False
        assert "launch_tier_absent" in result.reasons

    def test_launch_release_profile_mismatch_is_insufficient(self) -> None:
        profile = _profile(
            launch=_tier_data(source_kind="measured", release="other-profile")
        )
        result = evaluate_capacity_evidence(profile, _release())
        assert result.state is (
            CapacityEvidenceState.INSUFFICIENT_CAPACITY_EVIDENCE
        )
        assert "launch_release_profile_mismatch" in result.reasons

    def test_commitment_without_forecast_blocks_launch_only(self) -> None:
        profile = _profile(launch=_tier_data(source_kind="measured"))
        result = evaluate_capacity_evidence(
            profile, _release(commitment=True)
        )
        assert result.state is CapacityEvidenceState.SUFFICIENT_FOR_DESIGN
        assert result.design_unblocked is True
        assert result.launch_unblocked is False
        assert "contracted_forecast_missing" in result.reasons

    def test_commitment_with_forecast_unblocks_launch(self) -> None:
        profile = _profile(
            launch=_tier_data(source_kind="measured"),
            contracted_forecast=_tier_data(with_backfill=False),
        )
        result = evaluate_capacity_evidence(
            profile, _release(commitment=True)
        )
        assert result.state is CapacityEvidenceState.SUFFICIENT_FOR_LAUNCH
        assert result.reasons == ()

    def test_forecast_release_mismatch_blocks_launch(self) -> None:
        profile = _profile(
            launch=_tier_data(source_kind="measured"),
            contracted_forecast=_tier_data(
                release="other-profile", with_backfill=False
            ),
        )
        result = evaluate_capacity_evidence(
            profile, _release(commitment=True)
        )
        assert result.state is CapacityEvidenceState.SUFFICIENT_FOR_DESIGN
        assert "contracted_forecast_release_profile_mismatch" in result.reasons

    def test_forecast_ignored_without_commitment(self) -> None:
        profile = _profile(launch=_tier_data(source_kind="measured"))
        result = evaluate_capacity_evidence(profile, _release())
        assert result.state is CapacityEvidenceState.SUFFICIENT_FOR_LAUNCH

    def test_declared_launch_with_forecast_stays_design(self) -> None:
        profile = _profile(
            contracted_forecast=_tier_data(with_backfill=False)
        )
        result = evaluate_capacity_evidence(
            profile, _release(commitment=True)
        )
        assert result.state is CapacityEvidenceState.SUFFICIENT_FOR_DESIGN
        assert result.launch_unblocked is False

    def test_stress_breakpoint_recorded_but_never_blocking(self) -> None:
        without_stress = _profile(launch=_tier_data(source_kind="measured"))
        result = evaluate_capacity_evidence(without_stress, _release())
        assert result.state is CapacityEvidenceState.SUFFICIENT_FOR_LAUNCH
        assert result.stress_breakpoint_recorded is False

        with_stress = _profile(
            launch=_tier_data(source_kind="measured"),
            stress_breakpoint=_tier_data(
                source_kind="measured", with_backfill=False
            ),
        )
        recorded = evaluate_capacity_evidence(with_stress, _release())
        assert recorded.state is CapacityEvidenceState.SUFFICIENT_FOR_LAUNCH
        assert recorded.stress_breakpoint_recorded is True

    def test_release_profile_requires_explicit_commitment_flag(self) -> None:
        with pytest.raises(ValidationError):
            ReleaseProfileV1(name=RELEASE)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# CAP0.9 —— loader fail closed
# ---------------------------------------------------------------------------


class TestLoader:
    def test_yaml_and_json_same_hash(self, tmp_path: Path) -> None:
        data = _profile_data()
        yaml_path = tmp_path / "profile.yaml"
        yaml_path.write_text(
            yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
        )
        json_path = tmp_path / "profile.json"
        json_path.write_text(json.dumps(data), encoding="utf-8")

        from_yaml = load_capacity_profile(yaml_path)
        from_json = load_capacity_profile(json_path)
        direct = CapacityProfileV1.model_validate(copy.deepcopy(data))
        assert capacity_profile_hash(from_yaml) == (
            capacity_profile_hash(from_json)
        )
        assert capacity_profile_hash(from_yaml) == (
            capacity_profile_hash(direct)
        )

    def test_unsupported_extension_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "profile.toml"
        path.write_text("x = 1", encoding="utf-8")
        with pytest.raises(CapacityContractError) as exc_info:
            load_capacity_profile(path)
        assert exc_info.value.reason == "unsupported_profile_format"

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(CapacityContractError) as exc_info:
            load_capacity_profile(tmp_path / "absent.yaml")
        assert exc_info.value.reason == "profile_file_not_found"

    def test_parse_error_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.yaml"
        path.write_text("launch: [unclosed", encoding="utf-8")
        with pytest.raises(CapacityContractError) as exc_info:
            load_capacity_profile(path)
        assert exc_info.value.reason == "profile_parse_error"

    def test_non_mapping_root_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text("- 1\n- 2\n", encoding="utf-8")
        with pytest.raises(CapacityContractError) as exc_info:
            load_capacity_profile(path)
        assert exc_info.value.reason == "profile_root_not_mapping"

    def test_yaml_float_rejected_with_guidance(self, tmp_path: Path) -> None:
        data = _profile_data()
        data["launch"]["inputs"]["revision_amplification"][
            "claims_per_source_revision"
        ] = 18.5
        path = tmp_path / "float.yaml"
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
        )
        with pytest.raises(CapacityContractError) as exc_info:
            load_capacity_profile(path)
        assert exc_info.value.reason == "invalid_profile"
        assert "float" in str(exc_info.value)

    def test_incomplete_profile_rejected(self, tmp_path: Path) -> None:
        data = _profile_data()
        del data["launch"]["inputs"]["worker_provider"]
        path = tmp_path / "partial.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(CapacityContractError) as exc_info:
            load_capacity_profile(path)
        assert exc_info.value.reason == "invalid_profile"

    def test_reason_codes_closed_set(self) -> None:
        assert CAPACITY_CONTRACT_REASON_CODES == frozenset(
            {
                "profile_file_not_found",
                "profile_file_unreadable",
                "unsupported_profile_format",
                "profile_parse_error",
                "profile_root_not_mapping",
                "invalid_profile",
            }
        )


# ---------------------------------------------------------------------------
# CAP0.10 —— 八项问卷交付物
# ---------------------------------------------------------------------------


def _leaf_paths() -> list[str]:
    paths: list[str] = []
    for dim_name, dim_field in CapacityInputsV1.model_fields.items():
        annotation = dim_field.annotation
        assert isinstance(annotation, type)
        assert issubclass(annotation, BaseModel)
        paths.extend(
            f"{dim_name}.{leaf}" for leaf in annotation.model_fields
        )
    return paths


class TestQuestionnaire:
    def test_contains_all_eight_items_and_backfill(self) -> None:
        text = generate_launch_questionnaire()
        for path in _leaf_paths():
            assert path in text, f"问卷缺少字段槽位 {path}"
        for backfill_field in (
            "stock_backfill.document_count",
            "stock_backfill.total_text_fragments",
            "stock_backfill.total_bytes",
            "stock_backfill.target_completion_window_days",
            "stock_backfill.review_throughput_docs_per_day",
        ):
            assert backfill_field in text
        assert "INSUFFICIENT_CAPACITY_EVIDENCE" in text
        assert "declared" in text and "measured" in text
        assert "不是产品上限" in text
        assert "存量回填" in text

    def test_declared_2026_07_27_prefill_present(self) -> None:
        """2026-07-27 口头申报的两项以预填呈现，业务方只需确认/修正。"""

        text = generate_launch_questionnaire()
        assert "已申报（2026-07-27 口头）" in text
        assert "1000–5000" in text
        assert "100000–500000" in text
        assert "PDF/PPT" in text

    def test_deterministic_generation(self) -> None:
        assert generate_launch_questionnaire() == (
            generate_launch_questionnaire()
        )

    def test_write_questionnaire(self, tmp_path: Path) -> None:
        target = tmp_path / "cap0-launch-questionnaire.md"
        written = write_launch_questionnaire(target)
        assert written == target
        assert target.read_text(encoding="utf-8") == (
            generate_launch_questionnaire()
        )

    def test_repo_questionnaire_has_no_drift(self) -> None:
        repo_doc = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "insurance-kb"
            / "cap0-launch-questionnaire.md"
        )
        assert repo_doc.is_file(), "仓库问卷交付物缺失"
        assert repo_doc.read_text(encoding="utf-8") == (
            generate_launch_questionnaire()
        )
