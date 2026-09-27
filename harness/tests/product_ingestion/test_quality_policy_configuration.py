"""Quality opt-in owns its own immutable template and recovery identity."""

import hashlib
import json
from copy import deepcopy
from typing import Any, cast

import pytest

from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCompileRequest830G3V1,
)
from insurance_harness.product_ingestion.configuration import ProductRuntimeSettings
from insurance_harness.product_ingestion.review_quality import (
    QUALITY_REVIEW_PURPOSE,
    quality_review_prompt,
)
from tests.product_ingestion.test_native_relation_policy import relation_policy


def quality_settings(tmp_path: Any) -> dict[str, Any]:
    data = relation_policy(tmp_path)
    binding = data["bindings"][0]
    binding["native_discovery"]["quality_policy"] = "provenance-applicable-score.830.v1"
    binding["model"]["templates"].append(
        {
            **binding["model"]["templates"][-1],
            "template_id": QUALITY_REVIEW_PURPOSE,
            "purpose": QUALITY_REVIEW_PURPOSE,
            "prompt_sha256": hashlib.sha256(quality_review_prompt()).hexdigest(),
        }
    )
    return data


def test_quality_template_is_explicit_and_policy_changes_recovery_identity(tmp_path: Any) -> None:
    from insurance_harness.product_ingestion.stages import json_bytes

    old = ProductRuntimeSettings.model_validate_json(json.dumps(relation_policy(tmp_path)))
    data = quality_settings(tmp_path)
    current = ProductRuntimeSettings.model_validate_json(json.dumps(data))
    assert current.bindings[0].native_discovery is not None
    assert (
        current.bindings[0].native_discovery.quality_policy == "provenance-applicable-score.830.v1"
    )
    assert json_bytes(old.bindings[0].native_discovery) != json_bytes(
        current.bindings[0].native_discovery
    )
    assert json_bytes(old.bindings[0].model) != json_bytes(current.bindings[0].model)
    invalid = deepcopy(data)
    invalid["bindings"][0]["model"]["templates"].pop()
    with pytest.raises(ValueError, match="templates"):
        ProductRuntimeSettings.model_validate_json(json.dumps(invalid))


@pytest.mark.parametrize("value", [None, "", "unknown"])
def test_quality_configuration_rejects_empty_or_unknown_policy(tmp_path: Any, value: Any) -> None:
    data = quality_settings(tmp_path)
    data["bindings"][0]["native_discovery"]["quality_policy"] = value
    with pytest.raises(ValueError):
        ProductRuntimeSettings.model_validate_json(json.dumps(data))


def test_quality_configuration_requires_dependency_comparison() -> None:
    from insurance_harness.product_ingestion.configuration import NativeDiscoverySettings

    data = dict(
        policy="native-candidates.830.v1",
        language="Chinese",
        granularity="standard",
        purpose="发现",
        quality_policy="provenance-applicable-score.830.v1",
    )
    with pytest.raises(ValueError, match="dependency"):
        NativeDiscoverySettings.model_validate(data)
    data.pop("quality_policy")
    assert NativeDiscoverySettings.model_validate(data).dependency_policy is None


def test_quality_review_cannot_omit_comparison_selection() -> None:
    from types import SimpleNamespace

    from insurance_harness.product_ingestion.field_comparison import verified_review_field_view

    with pytest.raises(ValueError, match="field comparison"):
        verified_review_field_view(
            cast(
                BatchConceptCompileRequest830G3V1,
                SimpleNamespace(quality_policy="provenance-applicable-score.830.v1"),
            ),
            None,
            (),
            None,
        )
    assert (
        verified_review_field_view(
            cast(BatchConceptCompileRequest830G3V1, SimpleNamespace(quality_policy=None)),
            None,
            (),
            None,
        )
        is None
    )
