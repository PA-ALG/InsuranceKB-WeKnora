"""OpenSpec 020 D1.5: durable baseline commits bind the signed admission identity."""

from __future__ import annotations

from hashlib import sha256
from typing import cast

import pytest
from pydantic import ValidationError

from insurance_harness.compiler.models import BaselineAdmissionIdentity

# Copied from the deleted test_run_admission_baseline_artifacts_020 (S7a); only these two
# identity constants are needed by the BaselineAdmissionIdentity contract tests below.
_SCHEMA = "schema-v1+abcdef"
_MODEL = "approved-weak-extractor-v1"


def _identity() -> BaselineAdmissionIdentity:
    return BaselineAdmissionIdentity(
        format="insurancekb.baseline-admission-identity.v1",
        execution_plan_hash="1" * 64,
        parser_fingerprint="2" * 64,
        pdf_digests={"保险条款.pdf": sha256(b"admitted-pdf").hexdigest()},
        product_meta_digest="3" * 64,
        fields_digest="4" * 64,
        consumed_input_digests={"golden.jsonl": "5" * 64},
        shared_input_digests={
            "docs/insurance-kb/schema-baseline/schema.yaml": "6" * 64,
            "dataset/templates/registry.yaml": "7" * 64,
        },
        extractor_model_id=_MODEL,
        judge_model_id="approved-judge-v1",
        schema_version=_SCHEMA,
        template_registry_version="templates-v1",
    )


def test_d1_5_baseline_admission_digest_maps_are_deeply_immutable() -> None:
    identity = _identity()

    with pytest.raises(TypeError):
        cast(dict[str, str], identity.pdf_digests)["保险条款.pdf"] = "f" * 64


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("pdf_digests", {"../保险条款.pdf": "a" * 64}),
        ("shared_input_digests", {"/etc/schema.yaml": "a" * 64}),
        ("shared_input_digests", {"dataset//templates.yaml": "a" * 64}),
    ),
)
def test_d1_5_baseline_admission_digest_paths_are_canonical_repo_relative(
    field: str,
    value: object,
) -> None:
    raw = _identity().model_dump(mode="json")
    raw[field] = value

    with pytest.raises(ValidationError):
        BaselineAdmissionIdentity.model_validate(raw)
