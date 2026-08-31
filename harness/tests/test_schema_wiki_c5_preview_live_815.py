"""C5 persisted Formal Candidate Preview bundle contract tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

_WORKTREE_SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_WORKTREE_SOURCE))

import insurance_harness  # noqa: E402
import insurance_harness.knowledge_compiler  # noqa: E402
import insurance_harness.knowledge_compiler.schema_wiki_c5_preview_815 as c5_preview  # noqa: E402

insurance_harness.__path__.insert(0, str(_WORKTREE_SOURCE / "insurance_harness"))
insurance_harness.knowledge_compiler.__path__.insert(
    0,
    str(_WORKTREE_SOURCE / "insurance_harness" / "knowledge_compiler"),
)

from insurance_harness.canonical import canonical_hash  # noqa: E402
from insurance_harness.knowledge_compiler.schema_wiki_c5_preview_815 import (  # noqa: E402
    build_schema_wiki_c5_preview_bundle_815,
    validate_schema_wiki_c5_preview_bundle_815,
)
from insurance_harness.knowledge_compiler.schema_wiki_candidate_evidence_join_596_1 import (  # noqa: E402
    Schema67CandidateEvidenceAuthorityV1,
)

pytestmark = pytest.mark.live


def _required_artifact_root(name: str) -> Path:
    raw = os.environ.get(name)
    if not raw:
        pytest.skip(f"{name} is required for C5 artifact replay", allow_module_level=True)
    root = Path(raw)
    if not root.is_dir():
        pytest.skip(f"{name} does not name a directory", allow_module_level=True)
    return root


_C3_ROOT = _required_artifact_root("WEKNORA_C5_TEST_C3_ROOT")
_NEW_C3_ROOT = _required_artifact_root("WEKNORA_C5_TEST_C3_NEW_ROOT")
_REAL_ABSENT_C3_ROOT = _required_artifact_root("WEKNORA_C5_TEST_C3_ABSENT_ROOT")
_C3_HYDRATION_SUCCESSOR_ROOT = _required_artifact_root(
    "WEKNORA_C5_TEST_C3_HYDRATION_SUCCESSOR_ROOT"
)
_REVISION_SET_ROOT = _required_artifact_root("WEKNORA_C5_TEST_REVISION_SET_ROOT")
_C3_NAMES = (
    "formal-candidate.json",
    "coordinate-evidence-companion.json",
    "terminal.json",
    "field-attempt-manifest.json",
    "formal-derivation-validation.json",
    "result-manifest.json",
)
_REVISION_NAMES = (
    "revision-set.json",
    "terms.manifest.json",
    "terms.pdf",
    "brochure.manifest.json",
    "brochure.pdf",
    "rate_table.manifest.json",
    "rate_table.pdf",
)
_MEMBER_NAMES = (
    "preview.json",
    "formal-candidate.json",
    "coordinate-evidence-companion.json",
    "terminal.json",
    "field-attempt-manifest.json",
    "formal-derivation-validation.json",
    "result-manifest.json",
    "revision-set.json",
    "terms.manifest.json",
    "terms.pdf",
    "brochure.manifest.json",
    "brochure.pdf",
    "rate_table.manifest.json",
    "rate_table.pdf",
)
_PREVIEW_CONTRACT = "schema-wiki-formal-candidate-preview.815.v1"
_MANIFEST_CONTRACT = "schema-wiki-formal-candidate-preview-bundle.815.v1"
_SOURCE_SELECTION_KEYS = {
    "selection_id",
    "field_id",
    "source_role",
    "source_revision_id",
    "original_file_sha256",
    "parse_manifest_sha256",
    "page_number",
    "coordinate_space",
    "page_width_points",
    "page_height_points",
    "bbox",
    "rects",
    "block_id",
    "span_id",
    "table_id",
    "table_slice_id",
    "cell_ids",
    "quote",
    "quote_sha256",
    "page_text_char_start",
    "page_text_char_end",
}


def _object(value: object) -> dict[str, object]:
    assert type(value) is dict
    return cast(dict[str, object], value)


def _objects(value: object) -> list[dict[str, object]]:
    assert type(value) is list
    return [_object(item) for item in cast(list[object], value)]


def _strings(value: object) -> list[str]:
    assert type(value) is list
    items = cast(list[object], value)
    assert all(type(item) is str for item in items)
    return cast(list[str], items)


def _read_json(path: Path) -> dict[str, object]:
    return _object(json.loads(path.read_bytes()))


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _fold_source_rows(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    fold = getattr(c5_preview, "_fold_source_rows", None)
    assert callable(fold), "C5 duplicate-selection folding is unavailable"
    return cast(list[dict[str, object]], fold(rows))


def _object_hash(object_type: str, value: dict[str, object]) -> str:
    return hashlib.sha256(
        b"weknora.schema-wiki-c5.815.v1\0"
        + object_type.encode("ascii")
        + b"\0"
        + _canonical_bytes(value)
    ).hexdigest()


def _copy_inputs(
    root: Path,
    *,
    c3_source_root: Path = _C3_ROOT,
) -> tuple[Path, Path]:
    c3_root = root / "c3"
    revision_root = root / "revision-set"
    c3_root.mkdir(parents=True)
    revision_root.mkdir(parents=True)
    revision_root.chmod(0o700)
    for name in _C3_NAMES:
        shutil.copyfile(c3_source_root / name, c3_root / name)
    for name in _REVISION_NAMES:
        target = revision_root / name
        shutil.copyfile(_REVISION_SET_ROOT / name, target)
        target.chmod(0o600)
    return c3_root, revision_root


def _build_bundle(root: Path, *, c3_source_root: Path = _C3_ROOT) -> Path:
    c3_root, revision_root = _copy_inputs(root, c3_source_root=c3_source_root)
    manifest_path = build_schema_wiki_c5_preview_bundle_815(
        c3_input_root=c3_root,
        revision_set_root=revision_root,
        output_directory=root / "bundle",
    )
    validate_schema_wiki_c5_preview_bundle_815(manifest_path)
    return manifest_path


def _copy_hydration_successor_inputs(root: Path) -> tuple[Path, Path]:
    c3_root = root / "c3"
    revision_root = root / "revision-set"
    c3_root.mkdir(parents=True)
    revision_root.mkdir(parents=True)
    successor_names = (
        "successor-formal-candidate.json",
        "successor-coordinate-evidence-companion.json",
        "successor-terminal.json",
        "successor-field-attempt-manifest.json",
        "successor-formal-derivation-validation.json",
        "successor-result.json",
        "before-after-exact67.json",
        "classification-exact16.json",
    )
    for source_name in successor_names:
        target = c3_root / source_name
        shutil.copyfile(_C3_HYDRATION_SUCCESSOR_ROOT / source_name, target)
        target.chmod(0o600)
    for name in _REVISION_NAMES:
        target = revision_root / name
        shutil.copyfile(_REVISION_SET_ROOT / name, target)
        target.chmod(0o600)
    c3_root.chmod(0o700)
    revision_root.chmod(0o700)
    return c3_root, revision_root


def _rewrite_json(path: Path, mutate: str, value: object) -> None:
    payload = _read_json(path)
    payload[mutate] = value
    path.write_bytes(_canonical_bytes(payload))


def _without(value: dict[str, object], *keys: str) -> dict[str, object]:
    return {key: item for key, item in value.items() if key not in keys}


def _legacy_domain_hash(object_type: str, value: dict[str, object]) -> str:
    return hashlib.sha256(
        object_type.encode("ascii") + b"\0" + _canonical_bytes(value)
    ).hexdigest()


def _write_json(path: Path, value: dict[str, object]) -> str:
    payload = _canonical_bytes(value)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def test_c5_candidate_evidence_authority_member_round_trip_requires_original_object() -> None:
    from tests.test_schema_wiki_release_596_1 import _candidate_and_authority

    candidate, authority = _candidate_and_authority()
    candidate_wire = candidate.model_dump(mode="python")
    build_member = c5_preview._candidate_evidence_authority_member_bytes
    validate_member = c5_preview._validate_persisted_candidate_evidence_authority

    raw = build_member(candidate=candidate_wire, authority=authority)
    reopened = validate_member(raw=raw, candidate=candidate_wire)
    assert reopened == authority
    assert reopened.candidate_sha256 == candidate.candidate_sha256

    detached = Schema67CandidateEvidenceAuthorityV1.model_validate_json(raw)
    with pytest.raises(ValueError, match="C5_CANDIDATE_EVIDENCE_AUTHORITY_INVALID"):
        build_member(candidate=candidate_wire, authority=detached)

    drifted_candidate = dict(candidate_wire)
    drifted_candidate["candidate_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="C5_CANDIDATE_EVIDENCE_AUTHORITY_INVALID"):
        validate_member(raw=raw, candidate=drifted_candidate)


def _rebind_synthetic_c3_identity(
    c3_root: Path,
    *,
    preserve_absent_value: bool = True,
) -> dict[str, str]:
    experiment_id = "70b69ddf-d48e-4d80-b10f-93c158dfb7f5"
    integration_head = "1" * 40
    integration_tree = "2" * 40

    candidate_path = c3_root / "formal-candidate.json"
    candidate = _read_json(candidate_path)
    candidate_fields = _objects(candidate["fields"])
    changed_field = next(field for field in candidate_fields if field["state"] == "present")
    changed_field["state"] = "absent_explicitly"
    if not preserve_absent_value:
        changed_field["value_snapshot"] = None
    candidate["model_identity_sha256"] = "3" * 64
    candidate.pop("candidate_sha256")
    candidate_sha256 = canonical_hash("schema67-candidate.v2", candidate)
    candidate["candidate_sha256"] = candidate_sha256
    candidate_file_sha256 = _write_json(candidate_path, candidate)

    companion_path = c3_root / "coordinate-evidence-companion.json"
    companion = _read_json(companion_path)
    companion["candidate_sha256"] = candidate_sha256
    companion.pop("companion_sha256")
    companion_sha256 = canonical_hash(
        "schema67-coordinate-evidence-companion.815.v1", companion
    )
    companion["companion_sha256"] = companion_sha256
    companion_file_sha256 = _write_json(companion_path, companion)

    terminal_path = c3_root / "terminal.json"
    terminal = _read_json(terminal_path)
    terminal.update(
        {
            "coordinate_evidence_companion_sha256": companion_sha256,
            "experiment_id": experiment_id,
            "integration_head": integration_head,
            "integration_tree": integration_tree,
        }
    )
    terminal.pop("terminal_sha256")
    terminal_sha256 = _legacy_domain_hash(
        "ec01-formal-candidate-terminal.815.v1", terminal
    )
    terminal["terminal_sha256"] = terminal_sha256
    terminal_file_sha256 = _write_json(terminal_path, terminal)

    field_path = c3_root / "field-attempt-manifest.json"
    field_attempt = _read_json(field_path)
    field_attempt.update(
        {
            "coordinate_evidence_companion_sha256": companion_sha256,
            "experiment_id": experiment_id,
            "integration_head": integration_head,
            "integration_tree": integration_tree,
            "terminal_sha256": terminal_sha256,
        }
    )
    attempt_row = next(
        row
        for row in _objects(field_attempt["rows"])
        if row["field_id"] == changed_field["field_id"]
    )
    attempt_row.update(
        {
            "candidate_field_sha256": canonical_hash(
                "schema67-candidate-field.815.v1", changed_field
            ),
            "final_state": "absent_explicitly",
            "model_returned_state": "absent_explicitly",
            "parse_outcome": "PARSED_ABSENT_EXPLICITLY",
        }
    )
    attempt_row.pop("row_sha256")
    attempt_row["row_sha256"] = canonical_hash(
        "schema67-field-attempt.815.v1", attempt_row
    )
    field_attempt["candidate_fields_sha256"] = canonical_hash(
        "schema67-formal-candidate-fields.815.v1",
        {
            "ordered_field_ids": candidate["ordered_field_ids"],
            "fields": candidate_fields,
        },
    )
    field_attempt.pop("manifest_sha256")
    field_attempt.pop("formal_candidate_derivation_sha256")
    manifest_sha256 = canonical_hash(
        "schema67-field-attempt-manifest.815.v1", field_attempt
    )
    derivation_value: dict[str, object] = {
        "attempt_id": field_attempt["attempt_id"],
        "candidate_evidence_sha256": field_attempt["candidate_evidence_sha256"],
        "candidate_fields_sha256": field_attempt["candidate_fields_sha256"],
        "derivation_source": field_attempt["derivation_source"],
        "execution_identity_sha256": field_attempt["execution_identity_sha256"],
        "experiment_id": experiment_id,
        "field_attempt_manifest_sha256": manifest_sha256,
        "integration_head": integration_head,
        "integration_tree": integration_tree,
        "receipt_id": field_attempt["receipt_id"],
        "request_manifest_sha256": field_attempt["request_manifest_sha256"],
        "revision_set_sha256": field_attempt["revision_set_sha256"],
        "revision_validation_sha256": field_attempt["revision_validation_sha256"],
        "run_derivation_sha256": field_attempt["run_derivation_sha256"],
        "run_id": field_attempt["run_id"],
        "schema_rows_sha256": field_attempt["schema_rows_sha256"],
        "terminal_sha256": terminal_sha256,
    }
    field_attempt["manifest_sha256"] = manifest_sha256
    field_attempt["formal_candidate_derivation_sha256"] = canonical_hash(
        "schema67-formal-candidate-derivation.815.v1", derivation_value
    )
    field_file_sha256 = _write_json(field_path, field_attempt)

    validation_path = c3_root / "formal-derivation-validation.json"
    validation = _read_json(validation_path)
    validation.update(
        {
            "formal_candidate_derivation_sha256": field_attempt[
                "formal_candidate_derivation_sha256"
            ],
            "candidate_fields_sha256": field_attempt["candidate_fields_sha256"],
            "manifest_sha256": manifest_sha256,
            "terminal_sha256": terminal_sha256,
        }
    )
    validation_file_sha256 = _write_json(validation_path, validation)

    result_path = c3_root / "result-manifest.json"
    result = _read_json(result_path)
    _object(result["identities"])["experiment_id"] = experiment_id
    _object(result["git"]).update(
        {"head": integration_head, "parent": "4" * 40, "tree": integration_tree}
    )
    result_candidate = _object(result["candidate"])
    state_distribution: dict[str, int] = {}
    for field in candidate_fields:
        state = field["state"]
        assert type(state) is str
        state_distribution[state] = state_distribution.get(state, 0) + 1
    result_candidate.update(
        {
            "candidate_external_sha256": candidate_file_sha256,
            "candidate_internal_sha256": candidate_sha256,
            "coordinate_companion_external_sha256": companion_file_sha256,
            "coordinate_companion_internal_sha256": companion_sha256,
            "derivation_validation_external_sha256": validation_file_sha256,
            "field_attempt_manifest_external_sha256": field_file_sha256,
            "state_distribution": state_distribution,
        }
    )
    _object(result["terminal"])["internal_sha256"] = terminal_sha256
    artifact_hashes = {
        "formal-candidate.json": candidate_file_sha256,
        "coordinate-evidence-companion.json": companion_file_sha256,
        "terminal.json": terminal_file_sha256,
        "field-attempt-manifest.json": field_file_sha256,
        "formal-derivation-validation.json": validation_file_sha256,
    }
    for artifact in _objects(result["artifacts"]):
        name = artifact["name"]
        if type(name) is str and name in artifact_hashes:
            artifact["sha256"] = artifact_hashes[name]
            artifact["byte_size"] = (c3_root / name).stat().st_size
    result.pop("self_sha256")
    result["self_sha256"] = hashlib.sha256(_canonical_bytes(result)).hexdigest()
    _write_json(result_path, result)
    return {
        "candidate_sha256": candidate_sha256,
        "companion_sha256": companion_sha256,
        "experiment_id": experiment_id,
        "terminal_sha256": terminal_sha256,
    }


def _resign_preview_and_manifest(manifest_path: Path) -> None:
    preview_path = manifest_path.parent / "preview.json"
    preview = _read_json(preview_path)
    preview.pop("preview_sha256")
    preview["preview_sha256"] = _object_hash(_PREVIEW_CONTRACT, preview)
    preview_bytes = _canonical_bytes(preview)
    preview_path.write_bytes(preview_bytes)

    manifest = _read_json(manifest_path)
    for member in _objects(manifest["members"]):
        if member["name"] == "preview.json":
            member["sha256"] = hashlib.sha256(preview_bytes).hexdigest()
            member["size_bytes"] = len(preview_bytes)
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = _object_hash(_MANIFEST_CONTRACT, manifest)
    manifest_path.write_bytes(_canonical_bytes(manifest))


def test_c5_bundle_materializes_one_root_seven_sections_sixty_seven_fields(
    tmp_path: Path,
) -> None:
    manifest_path = _build_bundle(tmp_path)
    preview = _read_json(manifest_path.parent / "preview.json")
    candidate = _read_json(manifest_path.parent / "formal-candidate.json")

    assert preview["product"] == {
        "entity_id": "ping-an-e-sheng-bao",
        "entity_version_id": "ping-an-e-sheng-bao@596-1",
        "product_version_id": "596-1",
        "display_name": "平安e生保（尊享版）医疗保险",
    }
    sections = _objects(preview["sections"])
    fields = _objects(preview["fields"])
    assert len(sections) == len(_strings(preview["ordered_section_ids"])) == 7
    assert len(fields) == 67
    assert [field["schema_order"] for field in fields] == list(range(1, 68))
    assert [field["field_id"] for field in fields] == [
        field_id
        for section in sections
        for field_id in _strings(section["ordered_field_ids"])
    ]
    assert [field["state"] for field in fields] == [
        "absent" if field["state"] == "absent_explicitly" else field["state"]
        for field in _objects(candidate["fields"])
    ]
    assert stat.S_IMODE(manifest_path.parent.stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in manifest_path.parent.iterdir()
    )


def test_c5_bundle_preserves_present_values_unknown_reasons_and_native_sources(
    tmp_path: Path,
) -> None:
    manifest_path = _build_bundle(tmp_path)
    preview = _read_json(manifest_path.parent / "preview.json")
    candidate = _read_json(manifest_path.parent / "formal-candidate.json")
    field_manifest = _read_json(manifest_path.parent / "field-attempt-manifest.json")
    companion = _read_json(manifest_path.parent / "coordinate-evidence-companion.json")
    revision_set = _read_json(manifest_path.parent / "revision-set.json")
    preview_fields = {field["field_id"]: field for field in _objects(preview["fields"])}
    attempt_rows = {row["field_id"]: row for row in _objects(field_manifest["rows"])}
    coordinate_rows = _objects(companion["coordinate_rows"])

    for candidate_field in _objects(candidate["fields"]):
        field_id = candidate_field["field_id"]
        assert type(field_id) is str
        projected = preview_fields[field_id]
        if candidate_field["state"] in {"present", "absent_explicitly"}:
            assert projected["value_snapshot"] == candidate_field["value_snapshot"]
            assert projected["typed_reason"] is None
            source_selections = _objects(projected["source_selections"])
            expected_rows = [row for row in coordinate_rows if row["field_id"] == field_id]
            assert source_selections
            assert [row["selection_id"] for row in source_selections] == [
                row["selection_id"] for row in expected_rows
            ]
            for source, native in zip(source_selections, expected_rows, strict=True):
                assert set(source) == _SOURCE_SELECTION_KEYS
                assert all(source[key] == native[key] for key in source)
        else:
            assert candidate_field["state"] == "unknown"
            assert projected["value_snapshot"] is None
            assert projected["typed_reason"] == attempt_rows[field_id]["typed_reason"]
            assert projected["source_selections"] == []

    selected_roles = {
        row["source_role"] for row in coordinate_rows if type(row["source_role"]) is str
    }
    ordered_roles = _strings(revision_set["ordered_roles"])
    assert preview["coordinate_source_roles"] == [
        role for role in ordered_roles if role in selected_roles
    ]
    assert preview["source_roles_without_coordinate_selections"] == [
        role for role in ordered_roles if role not in selected_roles
    ]


def test_c5_bundle_preserves_real_absent_value_and_native_sources(
    tmp_path: Path,
) -> None:
    manifest_path = _build_bundle(tmp_path, c3_source_root=_REAL_ABSENT_C3_ROOT)
    preview = _read_json(manifest_path.parent / "preview.json")
    candidate = _read_json(manifest_path.parent / "formal-candidate.json")
    field_manifest = _read_json(manifest_path.parent / "field-attempt-manifest.json")
    companion = _read_json(manifest_path.parent / "coordinate-evidence-companion.json")
    preview_fields = {field["field_id"]: field for field in _objects(preview["fields"])}
    absent_candidate = next(
        field
        for field in _objects(candidate["fields"])
        if field["state"] == "absent_explicitly"
    )
    projected = preview_fields[cast(str, absent_candidate["field_id"])]

    assert projected["state"] == "absent"
    assert projected["value_snapshot"] == absent_candidate["value_snapshot"]
    assert type(projected["value_snapshot"]) is str
    assert projected["value_snapshot"].strip()
    assert projected["typed_reason"] is None
    assert len(_objects(projected["source_selections"])) == 5
    field_id = absent_candidate["field_id"]
    attempt = next(
        row for row in _objects(field_manifest["rows"]) if row["field_id"] == field_id
    )
    coordinate_rows = [
        row for row in _objects(companion["coordinate_rows"]) if row["field_id"] == field_id
    ]
    assert attempt["final_state"] == "absent_explicitly"
    assert attempt["typed_reason"] is None
    assert attempt["coordinate_evidence_sha256s"] == [
        canonical_hash("schema67-coordinate-evidence.815.v1", row)
        for row in coordinate_rows
    ]


def test_c5_bundle_accepts_the_frozen_c3_hydration_successor(
    tmp_path: Path,
) -> None:
    c3_root, revision_root = _copy_hydration_successor_inputs(tmp_path)

    manifest_path = build_schema_wiki_c5_preview_bundle_815(
        c3_input_root=c3_root,
        revision_set_root=revision_root,
        output_directory=tmp_path / "bundle",
    )
    reopened = validate_schema_wiki_c5_preview_bundle_815(manifest_path)
    preview = _read_json(manifest_path.parent / "preview.json")

    assert reopened["experiment_id"] == "5655e43c-1adb-4282-95f7-305e58441512"
    assert reopened["candidate_sha256"] == (
        "d6ffd33873fbfc6850f854f30ffddb89a9c67300d585872d783be99a6f75d521"
    )
    state_counts: dict[str, int] = {}
    for field in _objects(preview["fields"]):
        state = field["state"]
        assert type(state) is str
        state_counts[state] = state_counts.get(state, 0) + 1
    assert state_counts == {
        "present": 11,
        "absent": 1,
        "unknown": 55,
    }
    assert len(_objects(preview["fields"])) == 67


def test_c5_hydration_successor_result_member_matches_go_binding_contract(
    tmp_path: Path,
) -> None:
    c3_root, revision_root = _copy_hydration_successor_inputs(tmp_path)
    original_successor_result = (c3_root / "successor-result.json").read_bytes()

    manifest_path = build_schema_wiki_c5_preview_bundle_815(
        c3_input_root=c3_root,
        revision_set_root=revision_root,
        output_directory=tmp_path / "bundle",
    )
    manifest = _read_json(manifest_path)
    result = _read_json(manifest_path.parent / "result-manifest.json")
    candidate = _object(result["candidate"])
    terminal = _object(result["terminal"])

    assert result["contract"] == "ec01-native-pdf-selection-result.815.v1"
    assert _object(result["identities"])["experiment_id"] == manifest["experiment_id"]
    assert candidate["candidate_internal_sha256"] == manifest["candidate_sha256"]
    assert candidate["candidate_external_sha256"] == manifest["candidate_file_sha256"]
    assert candidate["coordinate_companion_internal_sha256"] == manifest["companion_sha256"]
    assert candidate["coordinate_companion_external_sha256"] == manifest["companion_file_sha256"]
    assert candidate["field_attempt_manifest_external_sha256"] == manifest[
        "field_attempt_manifest_sha256"
    ]
    assert candidate["derivation_validation_external_sha256"] == manifest[
        "formal_derivation_validation_sha256"
    ]
    assert terminal == {
        "internal_sha256": manifest["terminal_sha256"],
        "present": True,
        "status": "SUCCEEDED",
    }
    assert (c3_root / "successor-result.json").read_bytes() == original_successor_result


def test_c5_bundle_rejects_hydration_successor_report_drift(
    tmp_path: Path,
) -> None:
    c3_root, revision_root = _copy_hydration_successor_inputs(tmp_path)
    report_path = c3_root / "before-after-exact67.json"
    report_path.write_bytes(report_path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="C5_RESULT_INVALID"):
        build_schema_wiki_c5_preview_bundle_815(
            c3_input_root=c3_root,
            revision_set_root=revision_root,
            output_directory=tmp_path / "bundle",
        )


def test_c5_bundle_rejects_preview_source_range_not_exactly_joined_to_companion(
    tmp_path: Path,
) -> None:
    def drop_start(source: dict[str, object]) -> None:
        source.pop("page_text_char_start")

    def drift_start(source: dict[str, object]) -> None:
        source["page_text_char_start"] = cast(int, source["page_text_char_start"]) + 1

    def null_end(source: dict[str, object]) -> None:
        source["page_text_char_end"] = None

    def integer_table_start(source: dict[str, object]) -> None:
        source["page_text_char_start"] = 1

    cases: tuple[tuple[str, str, Callable[[dict[str, object]], None]], ...] = (
        ("missing range key", "TEXT_SPAN", drop_start),
        (
            "drifted text range",
            "TEXT_SPAN",
            drift_start,
        ),
        ("text null range", "TEXT_SPAN", null_end),
        ("table integer range", "TABLE_SLICE", integer_table_start),
    )
    for ordinal, (_name, selection_type, mutate) in enumerate(cases, start=1):
        manifest_path = _build_bundle(tmp_path / f"source-range-{ordinal}")
        preview_path = manifest_path.parent / "preview.json"
        preview = _read_json(preview_path)
        companion = _read_json(manifest_path.parent / "coordinate-evidence-companion.json")
        companion_by_id = {
            row["selection_id"]: row for row in _objects(companion["coordinate_rows"])
        }
        source = next(
            source
            for field in _objects(preview["fields"])
            for source in _objects(field["source_selections"])
            if companion_by_id[source["selection_id"]]["selection_type"] == selection_type
        )
        mutate(source)
        preview_path.write_bytes(_canonical_bytes(preview))
        _resign_preview_and_manifest(manifest_path)

        with pytest.raises(ValueError, match="C5_SOURCE_SELECTION_INVALID"):
            validate_schema_wiki_c5_preview_bundle_815(manifest_path)
def test_c5_bundle_folds_same_page_coordinate_rows_for_one_original_selection() -> None:
    companion = _read_json(_NEW_C3_ROOT / "coordinate-evidence-companion.json")
    rows = [
        row
        for row in _objects(companion["coordinate_rows"])
        if row["field_id"] == "insured_eligibility"
    ]

    assert len(rows) == 9
    assert len({row["selection_id"] for row in rows}) == 1
    folded = _fold_source_rows(rows)

    assert len(folded) == 1
    source = folded[0]
    assert set(source) == _SOURCE_SELECTION_KEYS
    assert source["selection_id"] == rows[0]["selection_id"]
    assert source["page_text_char_start"] == 339
    assert source["page_text_char_end"] == 585
    assert source["block_id"] == rows[0]["block_id"]
    assert source["span_id"] == rows[0]["span_id"]
    assert source["rects"] == [rect for row in rows for rect in cast(list[object], row["rects"])]
    assert source["bbox"] == [
        "63.24",
        "452.092",
        "544.56985",
        "603.913",
    ]
    quote = "\N{LINE SEPARATOR}".join(cast(str, row["quote"]) for row in rows)
    assert source["quote"] == quote
    assert source["quote_sha256"] == hashlib.sha256(quote.encode()).hexdigest()
    candidate = _read_json(_NEW_C3_ROOT / "formal-candidate.json")
    candidate_field = next(
        field
        for field in _objects(candidate["fields"])
        if field["field_id"] == "insured_eligibility"
    )
    assert source["quote"] == candidate_field["value_snapshot"]


def test_c5_bundle_preserves_cross_page_selection_and_rejects_identity_drift(
    tmp_path: Path,
) -> None:
    companion = _read_json(_NEW_C3_ROOT / "coordinate-evidence-companion.json")
    all_rows = _objects(companion["coordinate_rows"])
    cross_page_rows = [
        row
        for row in all_rows
        if row["field_id"] == "coverage_period"
    ]
    assert len({row["page_number"] for row in cross_page_rows}) == 2
    cross_page_folded = _fold_source_rows(cross_page_rows)
    assert [row["page_number"] for row in cross_page_folded] == [26, 27]
    assert len({row["selection_id"] for row in cross_page_folded}) == 1
    assert sum(len(cast(list[object], row["rects"])) for row in cross_page_folded) == len(
        cross_page_rows
    )

    same_page_rows = [
        dict(row)
        for row in all_rows
        if row["field_id"] == "insured_eligibility"
    ]
    same_page_rows[1]["source_revision_id"] = "0" * 64
    with pytest.raises(ValueError, match="C5_SOURCE_SELECTION_IDENTITY_MISMATCH"):
        _fold_source_rows(same_page_rows)

    manifest_path = build_schema_wiki_c5_preview_bundle_815(
        c3_input_root=_NEW_C3_ROOT,
        revision_set_root=_REVISION_SET_ROOT,
        output_directory=tmp_path / "bundle",
    )
    preview = _read_json(manifest_path.parent / "preview.json")
    sources = [
        source
        for field in _objects(preview["fields"])
        for source in _objects(field["source_selections"])
    ]
    duplicate_ids = {
        source["selection_id"]
        for source in sources
        if sum(other["selection_id"] == source["selection_id"] for other in sources) > 1
    }
    assert duplicate_ids
    for selection_id in duplicate_ids:
        duplicates = [source for source in sources if source["selection_id"] == selection_id]
        assert len(
            {
                (
                    source["field_id"],
                    source["source_role"],
                    source["source_revision_id"],
                    source["original_file_sha256"],
                )
                for source in duplicates
            }
        ) == 1


def test_c5_bundle_folds_table_slice_rows_without_inventing_offsets() -> None:
    companion = _read_json(_NEW_C3_ROOT / "coordinate-evidence-companion.json")
    source_rows = [
        dict(row)
        for row in _objects(companion["coordinate_rows"])
        if row["field_id"] == "insured_eligibility"
    ][:2]
    for ordinal, row in enumerate(source_rows, start=1):
        row.update(
            {
                "selection_type": "TABLE_SLICE",
                "page_text_char_start": None,
                "page_text_char_end": None,
                "block_id": None,
                "span_id": None,
                "table_id": "table-01",
                "table_slice_id": "table-slice-01",
                "cell_ids": [f"cell-{ordinal:02d}"],
            }
        )

    folded = _fold_source_rows(source_rows)

    assert len(folded) == 1
    assert folded[0]["selection_id"] == source_rows[0]["selection_id"]
    assert folded[0]["cell_ids"] == ["cell-01", "cell-02"]
    assert folded[0]["page_text_char_start"] is None
    assert folded[0]["page_text_char_end"] is None
    assert len(cast(list[object], folded[0]["rects"])) == 2


def test_c5_bundle_projects_closed_runtime_character_offsets_from_real_candidate(
    tmp_path: Path,
) -> None:
    manifest_path = build_schema_wiki_c5_preview_bundle_815(
        c3_input_root=_NEW_C3_ROOT,
        revision_set_root=_REVISION_SET_ROOT,
        output_directory=tmp_path / "bundle",
    )
    preview = _read_json(manifest_path.parent / "preview.json")
    sources = [
        source
        for field in _objects(preview["fields"])
        for source in _objects(field["source_selections"])
    ]

    assert sources
    assert all(set(source) == _SOURCE_SELECTION_KEYS for source in sources)
    for source in sources:
        start = source["page_text_char_start"]
        end = source["page_text_char_end"]
        if source["block_id"] is not None or source["span_id"] is not None:
            assert type(start) is int
            assert type(end) is int
            assert start < end
        else:
            assert start is end is None


def test_c5_bundle_accepts_a_new_frozen_explicit_identity(
    tmp_path: Path,
) -> None:
    c3_root, revision_root = _copy_inputs(tmp_path)
    expected = _rebind_synthetic_c3_identity(c3_root)

    manifest_path = build_schema_wiki_c5_preview_bundle_815(
        c3_input_root=c3_root,
        revision_set_root=revision_root,
        output_directory=tmp_path / "bundle",
    )

    manifest = validate_schema_wiki_c5_preview_bundle_815(manifest_path)
    preview = _read_json(manifest_path.parent / "preview.json")
    assert manifest["experiment_id"] == preview["experiment_id"] == expected["experiment_id"]
    assert manifest["candidate_sha256"] == preview["candidate_sha256"] == expected[
        "candidate_sha256"
    ]
    assert manifest["companion_sha256"] == preview["companion_sha256"] == expected[
        "companion_sha256"
    ]
    assert manifest["terminal_sha256"] == preview["terminal_sha256"] == expected[
        "terminal_sha256"
    ]
    fields = _objects(preview["fields"])
    candidate_fields = _objects(
        _read_json(manifest_path.parent / "formal-candidate.json")["fields"]
    )
    assert [field["state"] for field in fields] == [
        "absent" if field["state"] == "absent_explicitly" else field["state"]
        for field in candidate_fields
    ]
    absent_field = next(field for field in fields if field["state"] == "absent")
    assert type(absent_field["value_snapshot"]) is str
    assert absent_field["value_snapshot"].strip()
    assert _objects(absent_field["source_selections"])


@pytest.mark.parametrize("invalid_member", ["value_snapshot", "source_selections"])
def test_c5_bundle_rejects_invalid_absent_combination(
    tmp_path: Path,
    invalid_member: str,
) -> None:
    manifest_path = _build_bundle(tmp_path, c3_source_root=_REAL_ABSENT_C3_ROOT)
    preview = _read_json(manifest_path.parent / "preview.json")
    absent_field = next(
        field for field in _objects(preview["fields"]) if field["state"] == "absent"
    )
    absent_field[invalid_member] = None if invalid_member == "value_snapshot" else []
    _write_json(manifest_path.parent / "preview.json", preview)
    _resign_preview_and_manifest(manifest_path)

    with pytest.raises(ValueError, match="C5_FIELD_INVALID"):
        validate_schema_wiki_c5_preview_bundle_815(manifest_path)


def test_c5_bundle_rejects_recomputed_result_state_count_drift(
    tmp_path: Path,
) -> None:
    c3_root, revision_root = _copy_inputs(tmp_path)
    result_path = c3_root / "result-manifest.json"
    result = _read_json(result_path)
    _object(result["candidate"])["state_distribution"] = {
        "present": 17,
        "unknown": 50,
    }
    result.pop("self_sha256")
    result["self_sha256"] = hashlib.sha256(_canonical_bytes(result)).hexdigest()
    _write_json(result_path, result)

    with pytest.raises(ValueError, match="C5_RESULT_INVALID"):
        build_schema_wiki_c5_preview_bundle_815(
            c3_input_root=c3_root,
            revision_set_root=revision_root,
            output_directory=tmp_path / "bundle",
        )


def test_c5_bundle_rejects_candidate_companion_terminal_or_revision_drift(
    tmp_path: Path,
) -> None:
    cases: tuple[tuple[str, str, object], ...] = (
        ("formal-candidate.json", "candidate_sha256", "0" * 64),
        ("coordinate-evidence-companion.json", "companion_sha256", "0" * 64),
        ("terminal.json", "status", "FAILED"),
        ("revision-set.json", "tenant_id", 10004),
    )
    for ordinal, (name, key, value) in enumerate(cases, start=1):
        case_root = tmp_path / f"drift-{ordinal}"
        c3_root, revision_root = _copy_inputs(case_root)
        source_root = revision_root if name == "revision-set.json" else c3_root
        _rewrite_json(source_root / name, key, value)
        with pytest.raises(ValueError):
            build_schema_wiki_c5_preview_bundle_815(
                c3_input_root=c3_root,
                revision_set_root=revision_root,
                output_directory=case_root / "bundle",
            )

    result_case_root = tmp_path / "result-manifest-unknown-member"
    c3_root, revision_root = _copy_inputs(result_case_root)
    result_path = c3_root / "result-manifest.json"
    result = _read_json(result_path)
    result["raw_response"] = "sentinel"
    result.pop("self_sha256")
    result["self_sha256"] = hashlib.sha256(_canonical_bytes(result)).hexdigest()
    result_path.write_bytes(_canonical_bytes(result))
    with pytest.raises(ValueError):
        build_schema_wiki_c5_preview_bundle_815(
            c3_input_root=c3_root,
            revision_set_root=revision_root,
            output_directory=result_case_root / "bundle",
        )


def test_c5_bundle_rejects_cross_field_selection_and_unreopenable_revision(
    tmp_path: Path,
) -> None:
    cross_manifest = _build_bundle(tmp_path / "cross-field")
    preview = _read_json(cross_manifest.parent / "preview.json")
    fields = _objects(preview["fields"])
    owning_field = next(field for field in fields if field["source_selections"] != [])
    replacement_field = next(
        field for field in fields if field["field_id"] != owning_field["field_id"]
    )
    first_source = _objects(owning_field["source_selections"])[0]
    first_source["field_id"] = replacement_field["field_id"]
    (cross_manifest.parent / "preview.json").write_bytes(_canonical_bytes(preview))
    _resign_preview_and_manifest(cross_manifest)
    with pytest.raises(ValueError):
        validate_schema_wiki_c5_preview_bundle_815(cross_manifest)

    missing_manifest = _build_bundle(tmp_path / "missing-revision")
    (missing_manifest.parent / "terms.pdf").unlink()
    with pytest.raises(ValueError):
        validate_schema_wiki_c5_preview_bundle_815(missing_manifest)

    noncanonical_manifest = _build_bundle(tmp_path / "noncanonical-manifest")
    noncanonical_manifest.write_text(
        json.dumps(_read_json(noncanonical_manifest), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        validate_schema_wiki_c5_preview_bundle_815(noncanonical_manifest)


def test_c5_bundle_has_no_current_latest_golden_or_publishing_members(
    tmp_path: Path,
) -> None:
    manifest_path = _build_bundle(tmp_path)
    manifest = _read_json(manifest_path)
    preview = _read_json(manifest_path.parent / "preview.json")
    member_names = [member["name"] for member in _objects(manifest["members"])]

    assert member_names == list(_MEMBER_NAMES)
    assert manifest["quality_status"] == preview["quality_status"] == "NOT_EVALUATED"
    assert manifest["mvp_status"] == preview["mvp_status"] == "NOT_ACCEPTED"
    assert manifest["publishing"] is preview["publishing"] is False
    assert all(
        forbidden not in path.name.casefold()
        for path in manifest_path.parent.iterdir()
        for forbidden in ("current", "latest", "golden", "publish", "active", "release")
    )


def test_c5_bundle_no_replace_preserves_existing_version(tmp_path: Path) -> None:
    c3_root, revision_root = _copy_inputs(tmp_path)
    output_directory = tmp_path / "bundle"
    manifest_path = build_schema_wiki_c5_preview_bundle_815(
        c3_input_root=c3_root,
        revision_set_root=revision_root,
        output_directory=output_directory,
    )
    before = {path.name: path.read_bytes() for path in output_directory.iterdir()}

    with pytest.raises(FileExistsError):
        build_schema_wiki_c5_preview_bundle_815(
            c3_input_root=c3_root,
            revision_set_root=revision_root,
            output_directory=output_directory,
        )

    assert {path.name: path.read_bytes() for path in output_directory.iterdir()} == before
    assert validate_schema_wiki_c5_preview_bundle_815(manifest_path)["manifest_sha256"]
