"""OpenSpec 020 D1.5: durable baseline commits bind the signed admission identity."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from insurance_harness.compiler.models import BaselineAdmissionIdentity
from insurance_harness.compiler.pipeline import RunArtifactCommitCandidate, RunResult
from insurance_harness.goldenset.admission_runtime import AdmissionPausedError
from tests.test_run_admission_baseline_artifacts_020 import (
    _FIRST,
    _JUDGE_MODE,
    _LINE,
    _MODEL,
    _PLAN_CODE,
    _SCHEMA,
    _baseline_result,
    _write_checkpoint,
)


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


def _result_with_identity(
    tmp_path: Path,
    identity: BaselineAdmissionIdentity,
) -> tuple[RunResult, Path]:
    result, run_root = _baseline_result(tmp_path)
    checkpoint = Path(result.manifest.checkpoint_path)
    checkpoint.unlink()
    document = result.manifest.docs[0].model_copy(
        update={
            "file_hash": identity.pdf_digests["保险条款.pdf"],
            "original_digest": identity.pdf_digests["保险条款.pdf"],
            "parser_fingerprint": identity.parser_fingerprint,
        }
    )
    manifest = result.manifest.model_copy(
        update={
            "docs": [document],
            "baseline_admission": identity,
            "template_registry_version": identity.template_registry_version,
        }
    )
    result = result.model_copy(update={"manifest": manifest})
    _write_checkpoint(checkpoint, manifest=manifest)
    result.manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
    return result, run_root


def _validate(
    result: RunResult,
    run_root: Path,
    identity: BaselineAdmissionIdentity,
) -> RunResult:
    from insurance_harness.goldenset.execution_artifacts_020 import (
        validate_baseline_result,
    )

    return validate_baseline_result(
        result=result,
        run_root=run_root,
        expected_source_root=run_root.parent / "admitted-source",
        expected_product_dir=run_root.parent / "admitted-source" / "life" / _FIRST,
        expected_run_id="020-baseline-product",
        expected_run_dir=run_root / "execution-plan" / "product",
        expected_product_id=_PLAN_CODE,
        expected_product_name=_FIRST,
        expected_line_key=_LINE,
        expected_schema_version=_SCHEMA,
        expected_model_id=_MODEL,
        expected_judge_mode=_JUDGE_MODE,
        expected_admission_identity=identity,
    )


def _precommit(result: RunResult, identity: BaselineAdmissionIdentity) -> None:
    from insurance_harness.goldenset.execution_artifacts_020 import (
        validate_baseline_commit_candidate,
    )

    run_dir = Path(result.manifest.run_dir)
    validate_baseline_commit_candidate(
        RunArtifactCommitCandidate(
            pred=result.pred_path.read_bytes(),
            manifest=result.manifest_path.read_bytes(),
            judge_queue=result.judge_queue_path.read_bytes(),
            dead_letters=(run_dir / "dead-letters.jsonl").read_bytes(),
        ),
        expected_run_id="020-baseline-product",
        expected_run_dir=run_dir,
        expected_checkpoint_path=run_dir / "checkpoint.sqlite3",
        expected_product_dir=Path(result.manifest.product_dir),
        expected_product_id=_PLAN_CODE,
        expected_product_name=_FIRST,
        expected_line_key=_LINE,
        expected_schema_version=_SCHEMA,
        expected_model_id=_MODEL,
        expected_judge_mode=_JUDGE_MODE,
        expected_admission_identity=identity,
    )

def test_d1_5_baseline_accepts_exact_versioned_admission_identity(tmp_path: Path) -> None:
    identity = _identity()
    result, run_root = _result_with_identity(tmp_path, identity)

    assert _validate(result, run_root, identity) is result
    _precommit(result, identity)


def test_d1_5_baseline_precommit_rejects_wrong_checkpoint_path(tmp_path: Path) -> None:
    identity = _identity()
    result, _run_root = _result_with_identity(tmp_path, identity)
    changed = result.manifest.model_copy(
        update={"checkpoint_path": str(Path(result.manifest.run_dir) / "forged.sqlite3")}
    )
    result.manifest_path.write_text(changed.model_dump_json(), encoding="utf-8")

    with pytest.raises(AdmissionPausedError) as error:
        _precommit(result, identity)

    assert error.value.code == "baseline_identity_mismatch"


def test_d1_5_baseline_precommit_rejects_top_level_template_identity_drift(
    tmp_path: Path,
) -> None:
    identity = _identity()
    result, _run_root = _result_with_identity(tmp_path, identity)
    changed = result.manifest.model_copy(
        update={"template_registry_version": "forged-templates-v2"}
    )
    result.manifest_path.write_text(changed.model_dump_json(), encoding="utf-8")

    with pytest.raises(AdmissionPausedError) as error:
        _precommit(result, identity)

    assert error.value.code == "baseline_identity_mismatch"


def test_d1_5_baseline_postcommit_rejects_top_level_template_identity_drift(
    tmp_path: Path,
) -> None:
    identity = _identity()
    result, run_root = _result_with_identity(tmp_path, identity)
    changed = result.manifest.model_copy(
        update={"template_registry_version": "forged-templates-v2"}
    )
    result = result.model_copy(update={"manifest": changed})
    result.manifest_path.write_text(changed.model_dump_json(), encoding="utf-8")
    _write_checkpoint(Path(changed.checkpoint_path), manifest=changed)

    with pytest.raises(AdmissionPausedError) as error:
        _validate(result, run_root, identity)

    assert error.value.code == "baseline_identity_mismatch"


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


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("execution_plan_hash", "8" * 64),
        ("parser_fingerprint", "9" * 64),
        ("pdf_digests", {"保险条款.pdf": "a" * 64}),
        ("shared_input_digests", {"dataset/templates/registry.yaml": "b" * 64}),
        ("judge_model_id", "forged-judge"),
    ),
)
def test_d1_5_baseline_rejects_versioned_admission_identity_drift(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    expected = _identity()
    forged = expected.model_copy(update={field: value})
    result, run_root = _result_with_identity(tmp_path, forged)

    with pytest.raises(AdmissionPausedError) as error:
        _validate(result, run_root, expected)

    assert error.value.code == "baseline_identity_mismatch"
