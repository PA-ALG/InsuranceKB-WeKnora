from __future__ import annotations

import importlib
import os
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).parents[2]
PORTABLE_PARENT = (
    ROOT / "harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json"
)
ACTUAL_EPOCH9_PARENT = Path(
    os.environ.get(
        "G3_INCREMENTAL_PARENT_CANDIDATE",
        "/private/tmp/g3-final-navigation-epoch9-20260913/candidate.json",
    )
)
NEW_ENTITY_ID = "entity_incremental_published_g3_test"
NEW_ENTITY_VERSION = "entity-version-incremental-published-g3-test-v1"


def _module() -> ModuleType:
    return importlib.import_module(
        "insurance_harness.knowledge_compiler.batch_concept_compile_830_g3"
    )


def _published_base(module: ModuleType, candidate_path: Path) -> Any:
    bundle = module.validate_batch_candidate(candidate_path.read_bytes())
    payload = bundle.request.base_request.model_dump(mode="json")
    payload.update(
        base_release_id="release-incremental-g3-test",
        base_activation_epoch=9,
        existing_definitions=bundle.compile_result.output.definitions,
        existing_fields=bundle.compile_result.output.fields,
        existing_pages=bundle.compile_result.output.pages,
        existing_entity_versions=dict(bundle.request.base_request.entity_versions),
    )
    return module.CompileRequest.model_validate(payload)


def _with_new_entity(module: ModuleType, base: Any) -> Any:
    payload = base.model_dump(mode="json")
    payload["entity_versions"][NEW_ENTITY_ID] = NEW_ENTITY_VERSION
    payload["required_fields"][NEW_ENTITY_ID] = ["product_name"]
    return module.CompileRequest.model_validate(payload)


def test_published_g3_base_accepts_new_entity_without_existing_members() -> None:
    module = _module()
    base = _published_base(module, PORTABLE_PARENT)
    incremental = _with_new_entity(module, base)

    assert len(base.existing_fields) == 342
    assert module._base_contract_kind(base) == "PUBLISHED_G3"
    assert module._base_contract_kind(incremental) == "PUBLISHED_G3"
    assert NEW_ENTITY_ID not in incremental.existing_entity_versions


def test_published_g3_incremental_base_rechecks_all_old_fields() -> None:
    module = _module()
    incremental = _with_new_entity(module, _published_base(module, PORTABLE_PARENT))
    changed = incremental.model_copy(
        update={"existing_fields": incremental.existing_fields[:-1]}
    )

    with pytest.raises(module.BatchConceptCompileError, match="BASE_SNAPSHOT_MISMATCH"):
        module._base_contract_kind(changed)


def test_published_g3_incremental_base_rechecks_old_entity_versions() -> None:
    module = _module()
    incremental = _with_new_entity(module, _published_base(module, PORTABLE_PARENT))
    entity_versions = dict(incremental.entity_versions)
    old_entity_id = next(iter(incremental.existing_entity_versions))
    entity_versions[old_entity_id] = "entity-version-drift-test-v1"
    changed = incremental.model_copy(update={"entity_versions": entity_versions})

    with pytest.raises(module.BatchConceptCompileError, match="BASE_SNAPSHOT_MISMATCH"):
        module._base_contract_kind(changed)


def test_published_g3_incremental_base_rejects_new_entity_as_existing() -> None:
    module = _module()
    incremental = _with_new_entity(module, _published_base(module, PORTABLE_PARENT))
    existing_versions = dict(incremental.existing_entity_versions)
    existing_versions[NEW_ENTITY_ID] = NEW_ENTITY_VERSION
    changed = incremental.model_copy(
        update={"existing_entity_versions": existing_versions}
    )

    with pytest.raises(module.BatchConceptCompileError, match="BASE_SNAPSHOT_MISMATCH"):
        module._base_contract_kind(changed)


def test_actual_epoch9_493_field_base_accepts_new_entity() -> None:
    if not ACTUAL_EPOCH9_PARENT.is_file():
        pytest.skip(f"actual epoch9 candidate unavailable: {ACTUAL_EPOCH9_PARENT}")
    module = _module()
    base = _published_base(module, ACTUAL_EPOCH9_PARENT)
    incremental = _with_new_entity(module, base)

    assert len(base.existing_fields) == 493
    assert module._base_contract_kind(incremental) == "PUBLISHED_G3"
