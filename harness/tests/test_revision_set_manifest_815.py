"""EC-01 C1: deterministic exact-read RevisionSet validation."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from insurance_harness.knowledge_compiler.revision_set_manifest_815 import (
    freeze_revision_set_validation_815,
    require_revision_set_validation_815,
    validate_revision_set_manifest_815,
)

pytestmark = pytest.mark.live

_REVISION_SET_ROOT_VALUE = os.environ.get("WEKNORA_EC01_REVISION_SET_ROOT")
if not _REVISION_SET_ROOT_VALUE:
    pytest.skip(
        "WEKNORA_EC01_REVISION_SET_ROOT is required for revision-set validation",
        allow_module_level=True,
    )
REVISION_SET_ROOT = Path(_REVISION_SET_ROOT_VALUE)
EXPECTED_REVISION_SET_SHA256 = (
    "a45b27adb592e89b0fd0a66785e63baff344edc68fd5d965326a59a62b94dc2a"
)
EXPECTED_SOURCE_REVISIONS = {
    "terms": "ea7160149d2fd99ea4a4960c50bfa6ca3641e4532956671b9956f4f8b57ad681",
    "brochure": "89944ff7ecbfdcb0d00b7ceacfbdac4407389af078514317e2a3affe1973de50",
    "rate_table": "1c29dfab5f72de0a8490cd91e0eaeba901967f83f4a8d1aed0065c20db564a4e",
}
EXPECTED_PAGE_COUNTS = {"terms": 39, "brochure": 27, "rate_table": 2}


def test_ec01_revision_set_reopens_exact_three_and_freezes_machine_pass(
    tmp_path: Path,
) -> None:
    result = validate_revision_set_manifest_815(REVISION_SET_ROOT / "revision-set.json")

    assert result.status == "PASS"
    assert result.ordered_roles == ("terms", "brochure", "rate_table")
    assert result.revision_set_sha256 == EXPECTED_REVISION_SET_SHA256
    assert result.materials_reopened == 3
    assert result.parse_manifests_recomputed == 3
    assert result.source_revision_ids_recomputed == 3
    assert result.provider_calls == 0
    assert {row.role: row.page_count for row in result.rows} == EXPECTED_PAGE_COUNTS
    assert {
        row.role: row.compiler_source_revision_id for row in result.rows
    } == EXPECTED_SOURCE_REVISIONS
    assert all(row.file_sha256_match for row in result.rows)
    assert all(row.file_size_match for row in result.rows)
    assert all(row.page_count_match for row in result.rows)
    assert all(row.parse_manifest_sha256_match for row in result.rows)
    assert all(row.compiler_source_revision_id_match for row in result.rows)

    output_path = tmp_path / "revision-set-validation.json"
    freeze_revision_set_validation_815(result, output_path)
    reopened = require_revision_set_validation_815(output_path)
    assert reopened == result
    assert output_path.read_bytes() == (
        json.dumps(
            result.to_wire(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
