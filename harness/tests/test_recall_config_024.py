"""024 configuration boundaries fail closed."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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
