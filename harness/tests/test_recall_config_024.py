"""024 configuration boundaries fail closed and are reachable from the CLI."""

from __future__ import annotations

import argparse

import pytest
from pydantic import ValidationError

from insurance_harness.compiler import cli as compiler_cli
from insurance_harness.compiler.experiment import AssignmentPolicy, experiment_digest
from insurance_harness.compiler.pipeline import PipelineConfig
from insurance_harness.compiler.variants import PromptVariant, VariantRegistry
from insurance_harness.schemas.loader import SchemaLoadError, _parse_requiredness


@pytest.mark.parametrize(
    "factory",
    [
        lambda: PipelineConfig.model_validate({"gapfill_max_call": 0}),
        lambda: AssignmentPolicy.model_validate(
            {"enabeld": True, "experiment_id": "exp"}
        ),
        lambda: PromptVariant.model_validate(
            {"variant_id": "x", "version": "v1", "typo": True}
        ),
        lambda: VariantRegistry.model_validate({"entires": []}),
    ],
)
def test_e7_unknown_configuration_keys_are_rejected(factory: object) -> None:
    with pytest.raises(ValidationError):
        factory()  # type: ignore[operator]


def test_e7_experiment_id_is_canonicalized_before_hashing() -> None:
    padded = AssignmentPolicy(enabled=True, experiment_id="  exp-1  ", seed=3)
    canonical = AssignmentPolicy(enabled=True, experiment_id="exp-1", seed=3)
    assert padded.experiment_id == "exp-1"
    assert experiment_digest(VariantRegistry.default(), padded) == experiment_digest(
        VariantRegistry.default(), canonical
    )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: PipelineConfig.model_validate({"gapfill_max_calls": "1"}),
        lambda: AssignmentPolicy.model_validate({"enabled": "true"}),
        lambda: AssignmentPolicy.model_validate({"seed": "1"}),
    ],
)
def test_e7_configuration_does_not_coerce_identity_or_budget_types(
    factory: object,
) -> None:
    with pytest.raises(ValidationError):
        factory()  # type: ignore[operator]


def test_e3_conflicting_requiredness_aliases_are_rejected() -> None:
    with pytest.raises(SchemaLoadError, match="冲突"):
        _parse_requiredness(
            {"requiredness": "required", "必填": "可选"},
            file="schema.yaml",
            name="等待期",
        )
    assert _parse_requiredness(
        {"requiredness": "required", "必填": "必填"},
        file="schema.yaml",
        name="等待期",
    ) == "required"


def test_e3_cli_builds_budget_and_experiment_policy() -> None:
    args = argparse.Namespace(
        concurrency=3,
        gapfill_max_calls=7,
        experiment_id="  exp-020-d4  ",
        experiment_seed=9,
    )
    config = compiler_cli._pipeline_config_from_args(args, judge_mode="gateway")
    assert config.concurrency == 3
    assert config.gapfill_max_calls == 7
    assert config.judge_mode == "gateway"
    assert config.assignment == AssignmentPolicy(
        enabled=True, experiment_id="exp-020-d4", seed=9
    )


def test_e7_cli_rejects_seed_without_experiment_identity() -> None:
    args = argparse.Namespace(
        concurrency=3,
        gapfill_max_calls=None,
        experiment_id=None,
        experiment_seed=9,
    )
    with pytest.raises(SystemExit, match="experiment-seed"):
        compiler_cli._pipeline_config_from_args(args, judge_mode="claude-session")


def test_e7_cli_rejects_blank_experiment_identity() -> None:
    args = argparse.Namespace(
        concurrency=3,
        gapfill_max_calls=None,
        experiment_id="   ",
        experiment_seed=0,
    )
    with pytest.raises(SystemExit, match="experiment-id"):
        compiler_cli._pipeline_config_from_args(args, judge_mode="claude-session")
