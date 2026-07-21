"""OpenSpec 020 D1.5: baseline outputs stay under their admitted run root."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from insurance_harness.compiler.models import (
    DeadLetter,
    DocManifestEntry,
    JudgeRequest,
    PredRecord,
    RunManifest,
)
from insurance_harness.compiler.pipeline import RunResult
from insurance_harness.goldenset.admission_runtime import AdmissionPausedError
from tests.run_admission_execution_contract_020 import (
    ExecutionArtifacts020,
    execution_artifacts_or_skip,
)

_FIRST = "平安爱满分（2026）两全保险"
_PLAN_CODE = "1818"
_LINE = "endowment"
_SCHEMA = "schema-v1+abcdef"
_MODEL = "approved-weak-extractor-v1"
_JUDGE_MODE = "gateway"


def _write_checkpoint(
    path: Path,
    *,
    manifest: RunManifest,
) -> None:
    values: Mapping[str, object] = {
        "run_id": manifest.run_id,
        "run_dir": manifest.run_dir,
        "checkpoint_path": manifest.checkpoint_path,
        "product_dir": manifest.product_dir,
        "product_id": manifest.product_id,
        "product_name": manifest.product_name,
        "line_key": manifest.line_key,
        "schema_version": manifest.schema_version,
        "model_id": manifest.model_id,
        "judge_mode": manifest.judge_mode,
        "manifest": manifest.model_dump(mode="json"),
    }
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            SqliteSaver(connection).put(
                {"configurable": {"thread_id": manifest.run_id, "checkpoint_ns": ""}},
                {
                    "v": 1,
                    "id": "00000000-0000-0000-0000-000000000001",
                    "ts": "2026-07-20T00:00:00+00:00",
                    "channel_values": dict(values),
                    "channel_versions": {},
                    "versions_seen": {},
                    "updated_channels": list(values),
                },
                {"source": "input", "step": 0},
                {},
            )


@pytest.fixture
def artifact_contract() -> ExecutionArtifacts020:
    contract, _module = execution_artifacts_or_skip()
    return contract


def _baseline_result(tmp_path: Path) -> tuple[RunResult, Path]:
    run_root = tmp_path / "fixed-run-root"
    run_dir = run_root / "execution-plan" / "product"
    run_dir.mkdir(parents=True)
    checkpoint_path = run_dir / "checkpoint.sqlite3"
    pred_path = run_dir / "pred.jsonl"
    manifest_path = run_dir / "manifest.json"
    judge_queue_path = run_dir / "judge-queue.jsonl"
    dead_letters_path = run_dir / "dead-letters.jsonl"
    product_dir = tmp_path / "admitted-source" / "life" / _FIRST
    product_dir.mkdir(parents=True)
    (product_dir / "保险条款.pdf").write_bytes(b"admitted-pdf")
    record = PredRecord(
        product_id=_PLAN_CODE,
        product_name=_FIRST,
        doc="保险条款.pdf",
        field_id="waiting_period",
        field_name="等待期",
        value="90日",
        tri_state="present",
        evidence=[],
        annotator_model=_MODEL,
        schema_version=_SCHEMA,
        created_at=datetime(2026, 7, 20, tzinfo=UTC),
        confidence="low",
        pending_judge=True,
    )
    judge_request = JudgeRequest(
        product_id=_PLAN_CODE,
        product_name=_FIRST,
        doc=record.doc,
        field_id=record.field_id,
        field_name=record.field_name,
        reason="vote_disagreement",
        candidates=[{"value": record.value}],
        context_excerpt="等待期候选冲突",
    )
    dead_letter = DeadLetter(
        product=_FIRST,
        doc=record.doc,
        group="basic",
        window_ref="section-1",
        field_ids=["premium_period"],
        error="provider timeout",
        attempts=3,
    )
    pred_path.write_text(record.model_dump_json() + "\n", encoding="utf-8")
    judge_queue_path.write_text(
        judge_request.model_dump_json() + "\n", encoding="utf-8"
    )
    dead_letters_path.write_text(
        dead_letter.model_dump_json() + "\n", encoding="utf-8"
    )
    manifest = RunManifest(
        run_id="020-baseline-product",
        product_dir=str(product_dir),
        run_dir=str(run_dir),
        checkpoint_path=str(checkpoint_path),
        product_id=_PLAN_CODE,
        product_name=_FIRST,
        line_key=_LINE,
        schema_version=_SCHEMA,
        model_id=_MODEL,
        judge_mode=_JUDGE_MODE,
        docs=[
            DocManifestEntry(
                doc=record.doc,
                source_id="source-1",
                source_revision="a" * 64,
                file_hash="b" * 64,
                original_digest="c" * 64,
                parser_fingerprint="parser-v1",
            )
        ],
        dead_letters=[dead_letter],
        pending_judge_count=1,
    )
    _write_checkpoint(checkpoint_path, manifest=manifest)
    manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
    return (
        RunResult(
            manifest=manifest,
            records=[record],
            pred_path=pred_path,
            manifest_path=manifest_path,
            judge_queue_path=judge_queue_path,
        ),
        run_root,
    )


def _validate(
    contract: ExecutionArtifacts020,
    result: RunResult,
    run_root: Path,
) -> RunResult:
    return contract.validate_baseline_result(
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
    )


def test_d1_5_baseline_verifier_returns_same_admitted_result(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    assert (
        result.manifest.product_id,
        result.manifest.product_name,
        result.manifest.line_key,
        result.manifest.schema_version,
        result.manifest.model_id,
        result.manifest.judge_mode,
    ) == (_PLAN_CODE, _FIRST, _LINE, _SCHEMA, _MODEL, _JUDGE_MODE)
    assert result.records
    assert result.pred_path.read_text(encoding="utf-8").strip()
    assert result.judge_queue_path.read_text(encoding="utf-8").strip()
    assert (Path(result.manifest.run_dir) / "dead-letters.jsonl").is_file()
    assert (
        Path(result.manifest.run_dir) / "dead-letters.jsonl"
    ).read_text(encoding="utf-8").strip()

    verified = _validate(artifact_contract, result, run_root)

    assert verified is result


def test_d1_5_baseline_checkpoint_rejects_hardlink_mutation_alias(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    checkpoint = Path(result.manifest.checkpoint_path)
    os.link(checkpoint, tmp_path / "checkpoint-mutation-alias.sqlite3")

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code == "baseline_artifact_path_unsafe"


@pytest.mark.parametrize("suffix", ("-wal", "-shm"))
def test_d1_5_baseline_checkpoint_rejects_sqlite_sidecar(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    suffix: str,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    checkpoint = Path(result.manifest.checkpoint_path)
    checkpoint.with_name(f"{checkpoint.name}{suffix}").write_bytes(b"unadmitted-sidecar")

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code == "baseline_artifact_path_unsafe"


def test_d1_5_baseline_checkpoint_queries_only_exact_verified_bytes(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    original_connect = sqlite3.connect
    opened_databases: list[str] = []

    def connect_exact_bytes_only(database: str) -> sqlite3.Connection:
        opened_databases.append(database)
        if database != ":memory:":
            raise AssertionError("checkpoint path was reopened")
        return original_connect(database)

    monkeypatch.setattr(sqlite3, "connect", connect_exact_bytes_only)

    assert _validate(artifact_contract, result, run_root) is result
    assert opened_databases == [":memory:"]


@pytest.mark.parametrize(
    "failure",
    (
        "docs-empty",
        "source-pdf-missing",
        "pred-empty",
        "checkpoint-empty",
        "checkpoint-placeholder",
    ),
)
def test_d1_5_baseline_rejects_incomplete_or_placeholder_commit_evidence(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    failure: str,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    run_dir = Path(result.manifest.run_dir)
    if failure == "docs-empty":
        changed = result.manifest.model_copy(
            update={"docs": [], "dead_letters": [], "pending_judge_count": 0}
        )
        result = result.model_copy(update={"manifest": changed, "records": []})
        result.pred_path.write_text("", encoding="utf-8")
        result.judge_queue_path.write_text("", encoding="utf-8")
        (run_dir / "dead-letters.jsonl").write_text("", encoding="utf-8")
        result.manifest_path.write_text(changed.model_dump_json(), encoding="utf-8")
    elif failure == "source-pdf-missing":
        (Path(result.manifest.product_dir) / "保险条款.pdf").unlink()
    elif failure == "pred-empty":
        changed = result.manifest.model_copy(update={"pending_judge_count": 0})
        result = result.model_copy(update={"manifest": changed, "records": []})
        result.pred_path.write_text("", encoding="utf-8")
        result.judge_queue_path.write_text("", encoding="utf-8")
        result.manifest_path.write_text(changed.model_dump_json(), encoding="utf-8")
    elif failure == "checkpoint-empty":
        Path(result.manifest.checkpoint_path).write_bytes(b"")
    else:
        Path(result.manifest.checkpoint_path).write_bytes(b"sqlite-checkpoint")

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code in {
        "baseline_artifact_content_mismatch",
        "baseline_identity_mismatch",
    }


@pytest.mark.parametrize(
    "escape",
    (
        "pred-absolute",
        "manifest-absolute",
        "judge-absolute",
        "run-dir-absolute",
        "checkpoint-absolute",
        "pred-dotdot",
        "manifest-dotdot",
        "judge-dotdot",
        "run-dir-dotdot",
        "checkpoint-dotdot",
        "pred-symlink",
        "manifest-symlink",
        "judge-symlink",
        "checkpoint-symlink",
        "dead-letters-symlink",
        "parent-symlink",
    ),
)
def test_d1_5_baseline_rejects_output_or_manifest_path_escape(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    escape: str,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    run_dir = Path(result.manifest.run_dir)
    dotdot = run_dir / ".." / ".." / ".." / "outside"

    def update_manifest(**values: str) -> None:
        nonlocal result
        changed = result.manifest.model_copy(update=values)
        result = result.model_copy(update={"manifest": changed})
        result.manifest_path.write_text(changed.model_dump_json(), encoding="utf-8")

    def replace_with_symlink(path: Path) -> None:
        target = outside / path.name
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)

    if escape.startswith("pred-"):
        if escape.endswith("symlink"):
            replace_with_symlink(result.pred_path)
        else:
            path = (outside if escape.endswith("absolute") else dotdot) / "pred.jsonl"
            path.write_bytes(b"outside")
            result = result.model_copy(update={"pred_path": path})
    elif escape.startswith("manifest-"):
        if escape.endswith("symlink"):
            replace_with_symlink(result.manifest_path)
        else:
            path = (outside if escape.endswith("absolute") else dotdot) / "manifest.json"
            path.write_text(result.manifest.model_dump_json(), encoding="utf-8")
            result = result.model_copy(update={"manifest_path": path})
    elif escape.startswith("judge-"):
        if escape.endswith("symlink"):
            replace_with_symlink(result.judge_queue_path)
        else:
            path = (outside if escape.endswith("absolute") else dotdot) / "judge-queue.jsonl"
            path.write_bytes(b"")
            result = result.model_copy(update={"judge_queue_path": path})
    elif escape.startswith("run-dir-"):
        path = outside if escape.endswith("absolute") else dotdot
        update_manifest(run_dir=str(path))
    elif escape.startswith("checkpoint-"):
        checkpoint = Path(result.manifest.checkpoint_path)
        if escape.endswith("symlink"):
            replace_with_symlink(checkpoint)
        else:
            path = (outside if escape.endswith("absolute") else dotdot) / "checkpoint.sqlite3"
            path.write_bytes(b"outside")
            update_manifest(checkpoint_path=str(path))
    elif escape == "dead-letters-symlink":
        replace_with_symlink(run_dir / "dead-letters.jsonl")
    else:
        admitted_parent = run_root / "execution-plan"
        escaped_parent = tmp_path / "escaped-execution-plan"
        admitted_parent.rename(escaped_parent)
        admitted_parent.symlink_to(escaped_parent, target_is_directory=True)

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code == "baseline_artifact_path_unsafe"


@pytest.mark.parametrize(
    "artifact",
    ("pred", "manifest", "judge-queue", "checkpoint"),
)
def test_d1_5_baseline_rejects_in_root_artifact_aliases(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    artifact: str,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    run_dir = Path(result.manifest.run_dir)

    if artifact == "pred":
        alias = run_dir / "other-pred.jsonl"
        alias.write_bytes(result.pred_path.read_bytes())
        result = result.model_copy(update={"pred_path": alias})
    elif artifact == "manifest":
        alias = run_dir / "other-manifest.json"
        alias.write_bytes(result.manifest_path.read_bytes())
        result = result.model_copy(update={"manifest_path": alias})
    elif artifact == "judge-queue":
        alias = run_dir / "other-judge-queue.jsonl"
        alias.write_bytes(result.judge_queue_path.read_bytes())
        result = result.model_copy(update={"judge_queue_path": alias})
    else:
        original = Path(result.manifest.checkpoint_path)
        alias = run_dir / "other-checkpoint.sqlite3"
        alias.write_bytes(original.read_bytes())
        changed = result.manifest.model_copy(update={"checkpoint_path": str(alias)})
        result = result.model_copy(update={"manifest": changed})
        result.manifest_path.write_text(changed.model_dump_json(), encoding="utf-8")

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code == "baseline_artifact_path_unsafe"


def test_d1_5_baseline_rejects_manifest_object_and_file_mismatch(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    result.manifest_path.write_text(
        result.manifest.model_copy(update={"run_id": "forged"}).model_dump_json()
    )

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code == "baseline_manifest_mismatch"


def test_d1_5_baseline_rejects_self_consistent_wrong_run_id(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    checkpoint = Path(result.manifest.checkpoint_path)
    checkpoint.unlink()
    changed = result.manifest.model_copy(update={"run_id": "forged-run"})
    result = result.model_copy(update={"manifest": changed})
    _write_checkpoint(checkpoint, manifest=changed)
    result.manifest_path.write_text(changed.model_dump_json(), encoding="utf-8")

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code == "baseline_identity_mismatch"


def test_d1_5_baseline_rejects_self_consistent_wrong_run_directory(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    original_run_dir = Path(result.manifest.run_dir)
    forged_run_dir = original_run_dir.parent / "forged-product"
    original_run_dir.rename(forged_run_dir)
    for suffix in ("", "-wal", "-shm"):
        (forged_run_dir / f"checkpoint.sqlite3{suffix}").unlink(missing_ok=True)
    changed = result.manifest.model_copy(
        update={
            "run_dir": str(forged_run_dir),
            "checkpoint_path": str(forged_run_dir / "checkpoint.sqlite3"),
        }
    )
    result = result.model_copy(
        update={
            "manifest": changed,
            "pred_path": forged_run_dir / "pred.jsonl",
            "manifest_path": forged_run_dir / "manifest.json",
            "judge_queue_path": forged_run_dir / "judge-queue.jsonl",
        }
    )
    _write_checkpoint(forged_run_dir / "checkpoint.sqlite3", manifest=changed)
    result.manifest_path.write_text(changed.model_dump_json(), encoding="utf-8")

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code == "baseline_identity_mismatch"


@pytest.mark.parametrize("artifact", ("pred", "judge-queue", "dead-letters"))
def test_d1_5_baseline_rejects_semantically_valid_artifact_content_drift(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    artifact: str,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    if artifact == "pred":
        changed_record = result.records[0].model_copy(update={"value": "180日"})
        result.pred_path.write_text(
            changed_record.model_dump_json() + "\n", encoding="utf-8"
        )
    elif artifact == "judge-queue":
        request = JudgeRequest.model_validate_json(
            result.judge_queue_path.read_text(encoding="utf-8")
        )
        changed_request = request.model_copy(update={"field_id": "forged-field"})
        result.judge_queue_path.write_text(
            changed_request.model_dump_json() + "\n", encoding="utf-8"
        )
    else:
        changed_dead_letter = result.manifest.dead_letters[0].model_copy(
            update={"error": "forged error"}
        )
        (Path(result.manifest.run_dir) / "dead-letters.jsonl").write_text(
            changed_dead_letter.model_dump_json() + "\n", encoding="utf-8"
        )

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code == "baseline_artifact_content_mismatch"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("product_id", "9999"),
        ("product_name", "错误产品"),
        ("doc", "未声明附件.pdf"),
        ("field_id", "forged-field"),
        ("field_name", "错误字段名"),
    ),
)
def test_d1_5_baseline_judge_request_matches_each_pending_record_full_key(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    request = JudgeRequest.model_validate_json(
        result.judge_queue_path.read_text(encoding="utf-8")
    )
    changed = request.model_copy(update={field: value})
    result.judge_queue_path.write_text(changed.model_dump_json() + "\n", encoding="utf-8")

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code == "baseline_artifact_content_mismatch"


def test_d1_5_baseline_rejects_duplicate_judge_request_for_one_pending_record(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    line = result.judge_queue_path.read_text(encoding="utf-8")
    result.judge_queue_path.write_text(line + line, encoding="utf-8")

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code == "baseline_artifact_content_mismatch"


@pytest.mark.parametrize(
    "artifact",
    ("checkpoint", "pred", "manifest", "judge-queue", "dead-letters"),
)
def test_d1_5_baseline_rejects_missing_artifact_file(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    artifact: str,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    paths = {
        "checkpoint": Path(result.manifest.checkpoint_path),
        "pred": result.pred_path,
        "manifest": result.manifest_path,
        "judge-queue": result.judge_queue_path,
        "dead-letters": Path(result.manifest.run_dir) / "dead-letters.jsonl",
    }
    paths[artifact].unlink()

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code == "baseline_artifact_missing"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("product_id", "9999"),
        ("product_name", "错误目录产品"),
        ("line_key", "health"),
        ("schema_version", "schema-v2"),
        ("model_id", "unapproved-model"),
        ("judge_mode", "claude-session"),
    ),
)
def test_d1_5_baseline_rejects_manifest_identity_drift(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    changed = result.manifest.model_copy(update={field: value})
    result = result.model_copy(update={"manifest": changed})
    result.manifest_path.write_text(changed.model_dump_json(), encoding="utf-8")

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code == "baseline_identity_mismatch"


def test_d1_5_baseline_rejects_manifest_product_directory_drift(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    wrong_product_dir = tmp_path / "admitted-source" / "另一个产品"
    wrong_product_dir.mkdir()
    changed = result.manifest.model_copy(update={"product_dir": str(wrong_product_dir)})
    result = result.model_copy(update={"manifest": changed})
    result.manifest_path.write_text(changed.model_dump_json(), encoding="utf-8")

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code == "baseline_identity_mismatch"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("product_id", "9999"),
        ("product_name", "错误产品"),
        ("schema_version", "schema-v2"),
        ("annotator_model", "unapproved-model"),
        ("doc", "未声明附件.pdf"),
    ),
)
def test_d1_5_baseline_rejects_each_pred_record_identity_drift(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    changed_record = result.records[0].model_copy(update={field: value})
    result = result.model_copy(update={"records": [changed_record]})
    result.pred_path.write_text(changed_record.model_dump_json() + "\n", encoding="utf-8")

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code == "baseline_identity_mismatch"


@pytest.mark.parametrize(
    ("field", "value"),
    (("product", "错误产品"), ("doc", "未声明附件.pdf")),
)
def test_d1_5_baseline_rejects_dead_letter_identity_drift(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    changed_dead = result.manifest.dead_letters[0].model_copy(update={field: value})
    changed_manifest = result.manifest.model_copy(update={"dead_letters": [changed_dead]})
    result = result.model_copy(update={"manifest": changed_manifest})
    result.manifest_path.write_text(changed_manifest.model_dump_json(), encoding="utf-8")
    (Path(changed_manifest.run_dir) / "dead-letters.jsonl").write_text(
        changed_dead.model_dump_json() + "\n", encoding="utf-8"
    )

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code == "baseline_identity_mismatch"


def test_d1_5_baseline_rejects_symlink_in_expected_product_parent_chain(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    result, run_root = _baseline_result(tmp_path)
    source_root = tmp_path / "admitted-source"
    admitted_parent = source_root / "life"
    outside_parent = tmp_path / "outside-life"
    admitted_parent.rename(outside_parent)
    admitted_parent.symlink_to(outside_parent, target_is_directory=True)

    with pytest.raises(AdmissionPausedError) as error:
        _validate(artifact_contract, result, run_root)

    assert error.value.code == "baseline_identity_mismatch"
