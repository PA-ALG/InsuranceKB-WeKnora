from __future__ import annotations

import json
import os
import pickle
from collections.abc import Iterable, Mapping
from copy import copy, deepcopy
from typing import Any, cast

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

import insurance_harness.runtime.compilation_manifest as compilation_manifest_module
from insurance_harness.runtime.compilation_manifest import (
    CompilationArtifact,
    CompilationChangeItem,
    CompilationChangeSet,
    CompilationManifestView,
    CompilationRunBinding,
    ReleaseBaseBinding,
    canonical_compilation_manifest_bytes,
    compilation_manifest_digest,
    parse_compilation_manifest,
)
from insurance_harness.runtime.models import RuntimeContractError

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
SHA_1 = "1" * 64
SHA_2 = "2" * 64


def _run(**updates: object) -> CompilationRunBinding:
    values: dict[str, object] = {
        "space_id": "space-a",
        "run_id": "run-a",
        "run_revision": "revision-1",
        "strict_request_digest": SHA_A,
        "admission_artifact_digest": SHA_B,
        "verified_binding_digest": SHA_C,
        "template_lock_hash": SHA_D,
        "model_plan_hash": SHA_E,
    }
    values.update(updates)
    return CompilationRunBinding.model_validate(values)


def _base(**updates: object) -> ReleaseBaseBinding:
    values: dict[str, object] = {
        "space_id": "space-a",
        "snapshot_id": "snapshot-a",
        "manifest_hash": SHA_F,
    }
    values.update(updates)
    return ReleaseBaseBinding.model_validate(values)


def _artifact(**updates: object) -> CompilationArtifact:
    values: dict[str, object] = {
        "owner_kind": "product",
        "artifact_phase": "compilation",
        "space_id": "space-a",
        "product_version_id": "product-version-a",
        "path": "artifacts/facts.json",
        "sha256": SHA_1,
        "size_bytes": 17,
        "item_count": 1,
    }
    values.update(updates)
    return CompilationArtifact.model_validate(values)


def _change_set(**updates: object) -> CompilationChangeSet:
    values: dict[str, object] = {
        "owner_kind": "product",
        "space_id": "space-a",
        "product_version_id": "product-version-a",
        "change_set_id": "change-set-a",
        "observed_status": "pending",
    }
    values.update(updates)
    return CompilationChangeSet.model_validate(values)


def _change_item(**updates: object) -> CompilationChangeItem:
    values: dict[str, object] = {
        "owner_kind": "product",
        "space_id": "space-a",
        "product_version_id": "product-version-a",
        "change_set_id": "change-set-a",
        "change_item_id": "change-item-a",
        "claim_id": "claim-a",
        "action": "add",
        "observed_decision": "needs_review",
        "blocking_review_ids": ("review-a",),
    }
    values.update(updates)
    return CompilationChangeItem.model_validate(values)


def _manifest(**updates: object) -> CompilationManifestView:
    values: dict[str, object] = {
        "run": _run(),
        "compiled_at": "2026-07-23T00:00:00.000000Z",
        "base": _base(),
        "artifacts": (_artifact(),),
        "change_sets": (_change_set(),),
        "change_items": (_change_item(),),
        "blocking_review_ids": ("review-a",),
    }
    values.update(updates)
    return CompilationManifestView.model_validate(values)


def test_tr8_s1_manifest_digest_is_stable_and_binds_one_byte_change() -> None:
    artifact = _artifact()
    manifest = _manifest(artifacts=(artifact,))
    replay = CompilationManifestView.model_validate(
        manifest.model_dump(mode="python", round_trip=True)
    )
    changed = manifest.model_copy(
        update={"artifacts": (artifact.model_copy(update={"sha256": SHA_2}),)}
    )

    assert compilation_manifest_digest(replay) == compilation_manifest_digest(manifest)
    assert compilation_manifest_digest(changed) != compilation_manifest_digest(manifest)


def test_tr8_s1_manifest_uses_code_owned_inventory_order() -> None:
    artifact_a = _artifact(path="artifacts/a.json", sha256=SHA_1)
    artifact_b = _artifact(
        path="artifacts/b.json",
        sha256=SHA_2,
        product_version_id="product-version-b",
    )
    item_a = _change_item(change_item_id="item-a", claim_id="claim-a")
    item_b = _change_item(
        change_set_id="change-set-b",
        change_item_id="item-b",
        claim_id="claim-b",
        product_version_id="product-version-b",
        blocking_review_ids=("review-b",),
    )
    set_a = _change_set()
    set_b = _change_set(
        change_set_id="change-set-b",
        product_version_id="product-version-b",
    )

    forward = _manifest(
        artifacts=(artifact_a, artifact_b),
        change_sets=(set_a, set_b),
        change_items=(item_a, item_b),
        blocking_review_ids=("review-a", "review-b"),
    )
    reversed_input = _manifest(
        artifacts=(artifact_b, artifact_a),
        change_sets=(set_b, set_a),
        change_items=(item_b, item_a),
        blocking_review_ids=("review-b", "review-a"),
    )

    assert reversed_input.artifacts == forward.artifacts
    assert reversed_input.change_sets == forward.change_sets
    assert reversed_input.change_items == forward.change_items
    assert reversed_input.blocking_review_ids == forward.blocking_review_ids
    assert compilation_manifest_digest(reversed_input) == compilation_manifest_digest(forward)


@pytest.mark.parametrize(
    "path",
    (
        "/absolute.json",
        "../escape.json",
        "artifacts/../escape.json",
        "artifacts//facts.json",
        "./artifacts/facts.json",
        "C:/artifacts/facts.json",
        "artifacts\\facts.json",
        "artifacts/\x00facts.json",
    ),
)
def test_tr8_s1_artifact_paths_are_safe_repository_relative(path: str) -> None:
    with pytest.raises(ValidationError):
        _artifact(path=path)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("compiled_at", "2026-07-23T08:00:00.000000+08:00"),
        ("compiled_at", "2026-07-23T00:00:00Z"),
        ("compiled_at", "1753228800"),
    ),
)
def test_tr8_s1_compiled_at_has_one_canonical_utc_form(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _manifest(**{field: value})


def test_tr8_s1_base_snapshot_and_manifest_are_an_atomic_pair() -> None:
    values = _base().model_dump(mode="python", round_trip=True)
    values.pop("manifest_hash")

    with pytest.raises(ValidationError):
        _manifest(base=values)

    assert _manifest(base=None).base is None


@pytest.mark.parametrize(
    "updates",
    (
        {"base": _base(space_id="space-b")},
        {"artifacts": (_artifact(space_id="space-b"),)},
        {"change_sets": (_change_set(space_id="space-b"),)},
        {"change_items": (_change_item(space_id="space-b"),)},
    ),
)
def test_tr8_s1_manifest_rejects_cross_space_inventory(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _manifest(**updates)


@pytest.mark.parametrize(
    "updates",
    (
        {
            "artifacts": (
                _artifact(),
                _artifact(sha256=SHA_2),
            )
        },
        {
            "change_sets": (
                _change_set(),
                _change_set(product_version_id="product-version-b"),
            )
        },
        {
            "change_items": (
                _change_item(),
                _change_item(claim_id="claim-b"),
            )
        },
        {"blocking_review_ids": ("review-a", "review-a")},
    ),
)
def test_tr8_s1_manifest_rejects_duplicate_inventory_ids(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _manifest(**updates)


def test_tr8_s1_one_change_set_cannot_report_a_wrong_item_projection() -> None:
    with pytest.raises(ValidationError):
        _manifest(
            change_sets=(_change_set(observed_status="applied"),),
            change_items=(_change_item(),),
        )


@pytest.mark.parametrize(
    "field",
    (
        "final_decision",
        "target_claim_revisions",
        "target_facts_hash",
        "verified_admission",
        "issued_model_permit",
        "release_authorizer",
    ),
)
def test_tr8_s1_manifest_cannot_serialize_future_decisions_or_authority(
    field: str,
) -> None:
    values = _manifest().model_dump(mode="python", round_trip=True)
    values[field] = "forbidden"

    with pytest.raises(ValidationError):
        CompilationManifestView.model_validate(values)


@pytest.mark.parametrize("decision", ("approved", "rejected", "released"))
def test_tr8_s1_observed_decision_is_pre_review_only(decision: str) -> None:
    with pytest.raises(ValidationError):
        _change_item(observed_decision=decision)


def test_tr8_s1_canonical_bytes_round_trip_without_authority() -> None:
    from insurance_harness.runtime.compilation_manifest import (
        canonical_compilation_manifest_bytes,
        parse_compilation_manifest,
    )

    manifest = _manifest()
    payload = canonical_compilation_manifest_bytes(manifest)
    restored = parse_compilation_manifest(payload)

    assert restored == manifest
    assert canonical_compilation_manifest_bytes(restored) == payload
    assert set(json.loads(payload)) == {
        "artifacts",
        "base",
        "blocking_review_ids",
        "change_items",
        "change_sets",
        "compiled_at",
        "run",
        "schema_version",
    }
    assert all(
        forbidden not in payload
        for forbidden in (
            b"VerifiedAdmission",
            b"IssuedModelPermit",
            b"ReleaseAuthorizer",
            b"issuer_seal",
        )
    )


def test_tr8_s1_parser_rejects_duplicate_json_keys_before_validation() -> None:
    payload = canonical_compilation_manifest_bytes(_manifest())
    duplicate = payload.replace(
        b'{"artifacts":',
        b'{"schema_version":"insurancekb.runtime.compilation-manifest.v1","artifacts":',
        1,
    )

    with pytest.raises(ValueError, match="invalid_compilation_manifest"):
        parse_compilation_manifest(duplicate)


class _HiddenList(list[object]):
    hidden = "not-hashed"


class _HiddenTuple(tuple[object, ...]):
    hidden = "not-hashed"


class _HiddenDict(dict[str, object]):
    hidden = "not-hashed"


class _HiddenStr(str):
    hidden = "not-hashed"


class _HiddenInt(int):
    hidden = "not-hashed"


class _DuplicateMapping(Mapping[str, object]):
    def __init__(self, pairs: tuple[tuple[str, object], ...]) -> None:
        self._pairs = pairs

    def __getitem__(self, key: str) -> object:
        for item_key, value in reversed(self._pairs):
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(dict(self._pairs))

    def __len__(self) -> int:
        return len(dict(self._pairs))

    def items(self):  # type: ignore[no-untyped-def]
        return self._pairs


@pytest.mark.parametrize("container_type", (_HiddenList, _HiddenTuple))
def test_tr8_s1_rejects_custom_inventory_containers(
    container_type: type[list[object]] | type[tuple[object, ...]],
) -> None:
    with pytest.raises(ValidationError):
        _manifest(artifacts=container_type((_artifact(),)))


def test_tr8_s1_rejects_duplicate_or_custom_root_mappings() -> None:
    values = _manifest().model_dump(mode="python", round_trip=True)
    pairs = tuple(values.items()) + (("schema_version", values["schema_version"]),)

    with pytest.raises((ValidationError, RuntimeContractError)):
        CompilationManifestView.model_validate(_DuplicateMapping(pairs))


@pytest.mark.parametrize(
    ("factory", "values"),
    (
        (CompilationRunBinding, _run().model_dump(mode="python", round_trip=True)),
        (ReleaseBaseBinding, _base().model_dump(mode="python", round_trip=True)),
        (CompilationArtifact, _artifact().model_dump(mode="python", round_trip=True)),
        (
            CompilationChangeItem,
            _change_item().model_dump(mode="python", round_trip=True),
        ),
        (
            CompilationManifestView,
            _manifest().model_dump(mode="python", round_trip=True),
        ),
    ),
)
def test_tr8_s1_every_dto_rejects_hidden_dict_subclasses(
    factory: type[BaseModel], values: dict[str, object]
) -> None:
    with pytest.raises((ValidationError, RuntimeContractError)):
        factory.model_validate(_HiddenDict(values))


def test_tr8_s1_nested_hidden_mapping_cannot_be_normalized_into_inventory() -> None:
    hidden_artifact = _HiddenDict(_artifact().model_dump(mode="python", round_trip=True))

    with pytest.raises((ValidationError, RuntimeContractError)):
        _manifest(artifacts=(hidden_artifact,))


@pytest.mark.parametrize("value", (True, 1.0, "1", _HiddenInt(1)))
def test_tr8_s1_artifact_counts_require_exact_builtin_int(value: object) -> None:
    with pytest.raises(ValidationError):
        _artifact(size_bytes=value)


@pytest.mark.parametrize(
    ("factory", "field", "value"),
    (
        (_run, "space_id", _HiddenStr("space-a")),
        (_base, "snapshot_id", _HiddenStr("snapshot-a")),
        (_artifact, "path", _HiddenStr("artifacts/facts.json")),
        (_change_item, "action", _HiddenStr("add")),
        (_manifest, "compiled_at", _HiddenStr("2026-07-23T00:00:00.000000Z")),
    ),
)
def test_tr8_s1_scalar_inputs_require_exact_builtin_strings(
    factory: object,
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        factory(**{field: value})  # type: ignore[operator]


def test_tr8_s1_product_and_space_identity_are_digest_bound() -> None:
    ordinary = _manifest(
        artifacts=(_artifact(product_version_id="ordinary-product"),),
        change_sets=(_change_set(product_version_id="ordinary-product"),),
        change_items=(_change_item(product_version_id="ordinary-product"),),
    )
    participating = _manifest(
        artifacts=(_artifact(product_version_id="participating-product"),),
        change_sets=(_change_set(product_version_id="participating-product"),),
        change_items=(_change_item(product_version_id="participating-product"),),
    )
    space_b = _manifest(
        run=_run(space_id="space-b"),
        base=_base(space_id="space-b"),
        artifacts=(_artifact(space_id="space-b"),),
        change_sets=(_change_set(space_id="space-b"),),
        change_items=(_change_item(space_id="space-b"),),
    )

    assert compilation_manifest_digest(ordinary) != compilation_manifest_digest(participating)
    assert compilation_manifest_digest(ordinary) != compilation_manifest_digest(space_b)


def test_tr8_s1_public_model_construct_cannot_create_a_manifest() -> None:
    values = _manifest().model_dump(mode="python", round_trip=True)

    with pytest.raises(TypeError, match=r"model_construct\(\) is disabled"):
        CompilationManifestView.model_construct(**values)

    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        cast(Any, BaseModel.model_construct).__func__(CompilationManifestView, **values)


@pytest.mark.parametrize("tamper", ("raw", "private", "fields_set", "nested"))
def test_tr8_s1_tampered_manifest_cannot_be_read_hashed_or_serialized(
    tamper: str,
) -> None:
    manifest = _manifest()
    if tamper == "raw":
        object.__getattribute__(manifest, "__dict__")["compiled_at"] = "2026-07-24T00:00:00.000000Z"
    elif tamper == "private":
        object.__setattr__(manifest, "__pydantic_private__", {"authority": True})
    elif tamper == "fields_set":
        object.__getattribute__(manifest, "__pydantic_fields_set__").remove("run")
    else:
        stored_run = object.__getattribute__(manifest, "run")
        object.__getattribute__(stored_run, "__dict__")["space_id"] = "space-b"

    operations = (
        lambda: manifest.compiled_at,
        lambda: compilation_manifest_digest(manifest),
        lambda: canonical_compilation_manifest_bytes(manifest),
        lambda: manifest.model_dump(),
        lambda: copy(manifest),
        lambda: deepcopy(manifest),
        lambda: repr(manifest),
        lambda: hash(manifest),
    )
    for operation in operations:
        with pytest.raises((RuntimeContractError, ValueError)):
            operation()


def test_tr8_s1_coordinated_cross_space_replacement_does_not_reseal() -> None:
    manifest = _manifest()
    storage = object.__getattribute__(manifest, "__dict__")
    storage["run"] = _run(space_id="space-b")
    storage["base"] = _base(space_id="space-b")
    storage["artifacts"] = (_artifact(space_id="space-b"),)
    storage["change_sets"] = (_change_set(space_id="space-b"),)
    storage["change_items"] = (_change_item(space_id="space-b"),)

    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        compilation_manifest_digest(manifest)
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        CompilationManifestView.model_validate(manifest)


def test_tr8_s1_copy_is_fresh_audit_value_but_pickle_has_no_process_authority() -> None:
    manifest = _manifest()
    shallow = copy(manifest)
    deep = deepcopy(manifest)
    restored = pickle.loads(pickle.dumps(manifest))

    assert shallow == manifest and shallow is not manifest
    assert deep == manifest and deep is not manifest
    assert compilation_manifest_digest(shallow) == compilation_manifest_digest(manifest)
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        compilation_manifest_digest(restored)
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        restored.model_dump()


def test_tr8_s1_parser_requires_exact_bytes() -> None:
    with pytest.raises(ValueError, match="invalid_compilation_manifest"):
        parse_compilation_manifest(bytearray(canonical_compilation_manifest_bytes(_manifest())))  # type: ignore[arg-type]


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork semantics")
def test_tr8_s1_inherited_manifest_registry_is_revoked_after_fork() -> None:
    manifest = _manifest()
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    result: str
    if pid == 0:  # pragma: no cover - result is asserted in the parent process
        os.close(read_fd)
        try:
            try:
                compilation_manifest_digest(manifest)
            except RuntimeContractError as exc:
                result = exc.reason_code
            else:
                result = "accepted"
            os.write(write_fd, result.encode("ascii"))
        finally:
            os.close(write_fd)
            os._exit(0)

    os.close(write_fd)
    try:
        result = os.read(read_fd, 128).decode("ascii")
    finally:
        os.close(read_fd)
        _waited_pid, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    assert result == "invalid_contract_dto"
    assert compilation_manifest_digest(manifest) == compilation_manifest_digest(_manifest())


def test_tr8_s1_all_public_pydantic_ingress_rejects_noncanonical_input() -> None:
    manifest = _manifest()
    values = manifest.model_dump(mode="python", round_trip=True)
    hidden = _HiddenDict(values)
    payload = canonical_compilation_manifest_bytes(manifest)
    duplicate = payload.replace(
        b'{"artifacts":',
        b'{"schema_version":"wrong","artifacts":',
        1,
    )
    json_calls = (
        lambda: CompilationManifestView.model_validate_json(duplicate),
        lambda: cast(Any, BaseModel.model_validate_json).__func__(
            CompilationManifestView, duplicate
        ),
        lambda: TypeAdapter(CompilationManifestView).validate_json(duplicate),
    )
    python_calls = (
        lambda: cast(Any, BaseModel.model_validate).__func__(CompilationManifestView, hidden),
        lambda: cast(Any, BaseModel.model_validate_strings).__func__(
            CompilationManifestView, hidden
        ),
        lambda: CompilationManifestView.model_validate_strings(hidden),
        lambda: TypeAdapter(CompilationManifestView).validate_python(hidden),
        lambda: TypeAdapter(CompilationManifestView).validate_strings(hidden),
    )

    for operation in (*json_calls, *python_calls):
        with pytest.raises((ValidationError, RuntimeContractError)):
            operation()


@pytest.mark.parametrize(
    ("model_type", "values"),
    (
        (CompilationRunBinding, _run().model_dump(mode="python", round_trip=True)),
        (ReleaseBaseBinding, _base().model_dump(mode="python", round_trip=True)),
        (CompilationArtifact, _artifact().model_dump(mode="python", round_trip=True)),
        (CompilationChangeSet, _change_set().model_dump(mode="python", round_trip=True)),
        (
            CompilationChangeItem,
            _change_item().model_dump(mode="python", round_trip=True),
        ),
        (
            CompilationManifestView,
            _manifest().model_dump(mode="python", round_trip=True),
        ),
    ),
)
def test_tr8_s1_every_dto_core_schema_rejects_alternate_ingress(
    model_type: type[BaseModel],
    values: dict[str, object],
) -> None:
    adapter = TypeAdapter(model_type)

    with pytest.raises(ValidationError):
        adapter.validate_python(_HiddenDict(values))
    with pytest.raises(ValidationError):
        adapter.validate_json(json.dumps(values, separators=(",", ":")))


def test_tr8_s1_has_standalone_change_set_inventory() -> None:
    from insurance_harness.runtime.compilation_manifest import CompilationChangeSet

    empty_set = CompilationChangeSet(
        owner_kind="product",
        space_id="space-a",
        product_version_id="product-version-a",
        change_set_id="change-set-empty",
        observed_status="pending",
    )
    manifest = _manifest(change_sets=(empty_set,), change_items=(), blocking_review_ids=())

    assert manifest.change_sets == (empty_set,)


def test_tr8_s1_product_governance_identity_cannot_be_omitted() -> None:
    with pytest.raises(ValidationError):
        _change_item(product_version_id=None)


@pytest.mark.parametrize(
    ("status", "decision"),
    (
        ("rejected", "needs_review"),
        ("rolled_back", "auto_applied"),
        ("applied", "needs_review"),
        ("pending", "auto_applied"),
    ),
)
def test_tr8_s1_rejects_post_human_or_impossible_governance_projection(
    status: str,
    decision: str,
) -> None:
    with pytest.raises(ValidationError):
        _manifest(
            change_sets=(_change_set(observed_status=status),),
            change_items=(
                _change_item(
                    observed_decision=decision,
                    blocking_review_ids=(("review-a",) if decision == "needs_review" else ()),
                ),
            ),
            blocking_review_ids=(("review-a",) if decision == "needs_review" else ()),
        )


@pytest.mark.parametrize(
    "path",
    (
        "artifacts/\x01facts.json",
        "artifacts/\u202efacts.json",
        "artifacts/facts.json:stream",
        "artifacts/facts?.json",
        "artifacts/facts*.json",
        "artifacts/<facts>.json",
        'artifacts/facts".json',
        "artifacts/facts|pipe.json",
        "artifacts/A.json",
        "artifacts/café.json",
        "artifacts/café.json",
        "artifacts/COM¹.txt",
        "artifacts/LPT².txt",
        "artifacts/NUL",
        "artifacts/aux.txt",
        "artifacts/trailing. ",
        "release-proof.json",
        "artifact-manifest.json",
        "compilation-manifest.json",
    ),
)
def test_tr8_s1_rejects_cross_platform_or_release_only_artifact_paths(
    path: str,
) -> None:
    with pytest.raises(ValidationError):
        _artifact(path=path)


@pytest.mark.parametrize(
    ("factory", "field"),
    (
        (_run, "space_id"),
        (_run, "run_id"),
        (_artifact, "product_version_id"),
        (_change_item, "product_version_id"),
    ),
)
def test_tr8_s1_rejects_unresolved_identity_fallbacks(
    factory: object,
    field: str,
) -> None:
    with pytest.raises(ValidationError):
        factory(**{field: "unknown"})  # type: ignore[operator]


def test_tr8_s1_artifact_owner_tag_is_explicit_and_closed() -> None:
    run_artifact = _artifact(owner_kind="run", product_version_id=None)

    assert run_artifact.owner_kind == "run"
    assert run_artifact.product_version_id is None
    with pytest.raises(ValidationError):
        _artifact(owner_kind="product", product_version_id=None)
    with pytest.raises(ValidationError):
        _artifact(owner_kind="run", product_version_id="product-version-a")
    with pytest.raises(ValidationError):
        _artifact(artifact_phase="release")


@pytest.mark.parametrize(
    "updates",
    (
        {"change_items": (_change_item(change_set_id="missing-change-set"),)},
        {"change_sets": (_change_set(product_version_id="product-version-b"),)},
        {"blocking_review_ids": ()},
        {"blocking_review_ids": ("review-a", "review-extra")},
    ),
)
def test_tr8_s1_governance_inventory_is_referentially_closed(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _manifest(**updates)


def test_tr8_s1_review_item_cannot_be_claimed_by_two_change_items() -> None:
    with pytest.raises(ValidationError):
        _manifest(
            change_items=(
                _change_item(change_item_id="item-a"),
                _change_item(change_item_id="item-b"),
            )
        )


def test_tr8_s1_code_owned_status_projection_accepts_valid_observed_facts() -> None:
    auto_item = _change_item(
        change_item_id="item-auto",
        observed_decision="auto_applied",
        blocking_review_ids=(),
    )
    review_item = _change_item(
        change_item_id="item-review",
        blocking_review_ids=("review-b",),
    )
    applied = _manifest(
        change_sets=(_change_set(observed_status="applied"),),
        change_items=(auto_item,),
        blocking_review_ids=(),
    )
    partial = _manifest(
        change_sets=(_change_set(observed_status="partially_applied"),),
        change_items=(auto_item, review_item),
        blocking_review_ids=("review-b",),
    )
    empty_applied = _manifest(
        change_sets=(_change_set(observed_status="applied"),),
        change_items=(),
        blocking_review_ids=(),
    )

    assert applied.change_sets[0].observed_status == "applied"
    assert partial.change_sets[0].observed_status == "partially_applied"
    assert empty_applied.change_items == ()


def test_tr8_s1_only_exact_python_mode_or_safe_parser_can_ingest() -> None:
    manifest = _manifest()
    values = manifest.model_dump(mode="python", round_trip=True)
    adapter = TypeAdapter(CompilationManifestView)

    assert adapter.validate_python(values) == manifest
    assert parse_compilation_manifest(canonical_compilation_manifest_bytes(manifest)) == manifest
    with pytest.raises(ValidationError):
        adapter.validate_json(canonical_compilation_manifest_bytes(manifest))


def test_tr8_s1_parser_rejects_nested_duplicate_keys() -> None:
    payload = canonical_compilation_manifest_bytes(_manifest())
    duplicate = payload.replace(
        b'"owner_kind":"product",',
        b'"owner_kind":"run","owner_kind":"product",',
        1,
    )

    with pytest.raises(ValueError, match="invalid_compilation_manifest"):
        parse_compilation_manifest(duplicate)


def test_tr8_s1_model_copy_rejects_custom_or_duplicate_update_mapping() -> None:
    manifest = _manifest()
    duplicate_update = _DuplicateMapping(
        (
            ("compiled_at", "2026-07-23T00:00:00.000000Z"),
            ("compiled_at", "2026-07-24T00:00:00.000000Z"),
        )
    )

    with pytest.raises((TypeError, RuntimeContractError)):
        manifest.model_copy(update=duplicate_update)


@pytest.mark.parametrize(
    ("value", "field", "first", "second"),
    (
        (_run(), "space_id", "space-a", "space-b"),
        (_base(), "space_id", "space-a", "space-b"),
        (_artifact(), "space_id", "space-a", "space-b"),
        (_change_set(), "space_id", "space-a", "space-b"),
        (_change_item(), "space_id", "space-a", "space-b"),
        (
            _manifest(),
            "compiled_at",
            "2026-07-23T00:00:00.000000Z",
            "2026-07-24T00:00:00.000000Z",
        ),
    ),
)
def test_tr8_s1_every_dto_copy_requires_an_exact_update_dictionary(
    value: BaseModel,
    field: str,
    first: str,
    second: str,
) -> None:
    duplicate_update = _DuplicateMapping(((field, first), (field, second)))

    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        value.model_copy(update=duplicate_update)


@pytest.mark.parametrize("separator", ("\u2028", "\u2029"))
def test_tr8_s1_identity_strings_reject_line_and_paragraph_separators(
    separator: str,
) -> None:
    with pytest.raises(ValidationError):
        _run(run_id=f"run{separator}a")


@pytest.mark.parametrize(
    ("model_type", "values"),
    (
        (CompilationRunBinding, _run().model_dump(mode="python", round_trip=True)),
        (ReleaseBaseBinding, _base().model_dump(mode="python", round_trip=True)),
        (CompilationArtifact, _artifact().model_dump(mode="python", round_trip=True)),
        (CompilationChangeSet, _change_set().model_dump(mode="python", round_trip=True)),
        (
            CompilationChangeItem,
            _change_item().model_dump(mode="python", round_trip=True),
        ),
        (
            CompilationManifestView,
            _manifest().model_dump(mode="python", round_trip=True),
        ),
    ),
)
def test_tr8_s1_every_dto_rejects_hidden_string_dictionary_keys(
    model_type: type[BaseModel],
    values: dict[str, object],
) -> None:
    field_name = next(iter(values))
    field_value = values.pop(field_name)
    values[_HiddenStr(field_name)] = field_value

    with pytest.raises((ValidationError, RuntimeContractError)):
        model_type.model_validate(values)
    with pytest.raises(ValidationError):
        TypeAdapter(model_type).validate_python(values)


@pytest.mark.parametrize(
    "nested_field", ("run", "base", "artifacts", "change_sets", "change_items")
)
def test_tr8_s1_manifest_rejects_hidden_keys_in_nested_dictionaries(
    nested_field: str,
) -> None:
    values = _manifest().model_dump(mode="python", round_trip=True)
    nested = values[nested_field]
    if type(nested) is tuple:
        nested_values = dict(nested[0])
        field_name = next(iter(nested_values))
        field_value = nested_values.pop(field_name)
        nested_values[_HiddenStr(field_name)] = field_value
        values[nested_field] = (nested_values,)
    else:
        nested_values = dict(cast(dict[str, object], nested))
        field_name = next(iter(nested_values))
        field_value = nested_values.pop(field_name)
        nested_values[_HiddenStr(field_name)] = field_value
        values[nested_field] = nested_values

    with pytest.raises((ValidationError, RuntimeContractError)):
        CompilationManifestView.model_validate(values)


@pytest.mark.parametrize(
    ("value", "field", "replacement"),
    (
        (_run(), "space_id", "space-b"),
        (_base(), "space_id", "space-b"),
        (_artifact(), "space_id", "space-b"),
        (_change_set(), "space_id", "space-b"),
        (_change_item(), "space_id", "space-b"),
        (_manifest(), "compiled_at", "2026-07-24T00:00:00.000000Z"),
    ),
)
def test_tr8_s1_every_dto_copy_rejects_hidden_string_update_keys(
    value: BaseModel,
    field: str,
    replacement: str,
) -> None:
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        value.model_copy(update={_HiddenStr(field): replacement})


def test_tr8_s1_item_review_ids_require_exact_builtin_strings_before_coercion() -> None:
    with pytest.raises(ValidationError):
        _change_item(blocking_review_ids=(_HiddenStr("review-a"),))


def test_tr8_s1_portable_artifact_segment_is_at_most_255_bytes() -> None:
    assert _artifact(path=f"artifacts/{'a' * 255}").path.endswith("a" * 255)
    with pytest.raises(ValidationError):
        _artifact(path=f"artifacts/{'a' * 256}")


_ContainerType = (
    type[dict[object, object]]
    | type[list[object]]
    | type[tuple[object, ...]]
)


def _deep_builtin_graph(container_type: _ContainerType) -> object:
    value: object = None
    for index in range(1_200):
        if container_type is dict:
            value = {f"level-{index}": value}
        elif container_type is list:
            value = [value]
        else:
            value = (value,)
    return value


def _deep_mixed_builtin_graph() -> object:
    value: object = None
    container_types = (dict, list, tuple)
    for index in range(1_200):
        container_type = container_types[index % len(container_types)]
        if container_type is dict:
            value = {f"level-{index}": value}
        elif container_type is list:
            value = [value]
        else:
            value = (value,)
    return value


class _CustomIterable(Iterable[object]):
    def __iter__(self):  # type: ignore[no-untyped-def]
        yield None


@pytest.mark.parametrize("container_type", (dict, list, tuple))
@pytest.mark.parametrize(
    "model_type",
    (
        CompilationRunBinding,
        ReleaseBaseBinding,
        CompilationArtifact,
        CompilationChangeSet,
        CompilationChangeItem,
        CompilationManifestView,
    ),
)
def test_tr8_s1_every_dto_rejects_overdeep_builtin_graph_without_stack_escape(
    model_type: type[BaseModel],
    container_type: _ContainerType,
) -> None:
    values = {"unexpected": _deep_builtin_graph(container_type)}

    with pytest.raises(ValidationError):
        model_type.model_validate(values)
    with pytest.raises(ValidationError):
        TypeAdapter(model_type).validate_python(values)


@pytest.mark.parametrize(
    "nested",
    (
        pytest.param(_deep_mixed_builtin_graph(), id="mixed"),
        pytest.param(_deep_builtin_graph(dict), id="dict"),
        pytest.param(_deep_builtin_graph(list), id="list"),
        pytest.param(_deep_builtin_graph(tuple), id="tuple"),
    ),
)
def test_tr8_s1_mixed_and_deep_graphs_are_typed_failures(nested: object) -> None:
    values = {"unexpected": nested}

    with pytest.raises(ValidationError):
        CompilationManifestView.model_validate(values)
    with pytest.raises(ValidationError):
        TypeAdapter(CompilationManifestView).validate_python(values)


@pytest.mark.parametrize(
    "wide",
    (
        pytest.param({f"item-{index}": None for index in range(20_000)}, id="dict"),
        pytest.param([None] * 20_000, id="list"),
        pytest.param((None,) * 20_000, id="tuple"),
    ),
)
def test_tr8_s1_wide_builtin_graph_is_rejected_by_a_typed_boundary(
    wide: object,
) -> None:
    values = {"unexpected": wide}

    with pytest.raises(ValidationError):
        CompilationManifestView.model_validate(values)
    with pytest.raises(ValidationError):
        TypeAdapter(CompilationManifestView).validate_python(values)


def test_tr8_s1_cumulative_edge_budget_rejects_a_wide_shared_dag() -> None:
    repeated_leaf = None
    nested = [[repeated_leaf] * 8_192 for _ in range(65)]
    values = {"unexpected": nested}

    with pytest.raises(ValidationError):
        CompilationManifestView.model_validate(values)
    with pytest.raises(ValidationError):
        TypeAdapter(CompilationManifestView).validate_python(values)


def test_tr8_s1_unique_node_budget_rejects_a_large_builtin_graph() -> None:
    nested = [list(range(index * 8_192, (index + 1) * 8_192)) for index in range(33)]
    values = {"unexpected": nested}

    with pytest.raises(ValidationError):
        CompilationManifestView.model_validate(values)
    with pytest.raises(ValidationError):
        TypeAdapter(CompilationManifestView).validate_python(values)


@pytest.mark.parametrize(
    "value",
    (_run(), _base(), _artifact(), _change_set(), _change_item(), _manifest()),
)
def test_tr8_s1_model_copy_rejects_overdeep_builtin_graph_without_stack_escape(
    value: BaseModel,
) -> None:
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        value.model_copy(update={"unexpected": _deep_builtin_graph(list)})


@pytest.mark.parametrize("cycle_kind", ("self-list", "self-dict", "mutual"))
def test_tr8_s1_container_cycles_are_typed_failures(cycle_kind: str) -> None:
    if cycle_kind == "self-list":
        nested: object = []
        cast(list[object], nested).append(nested)
    elif cycle_kind == "self-dict":
        nested = {}
        cast(dict[str, object], nested)["self"] = nested
    else:
        left: list[object] = []
        right: dict[str, object] = {"left": left}
        left.append(right)
        nested = left

    values = {"unexpected": nested}
    with pytest.raises(ValidationError):
        CompilationManifestView.model_validate(values)
    with pytest.raises(ValidationError):
        TypeAdapter(CompilationManifestView).validate_python(values)


def test_tr8_s1_shared_subobject_dag_is_not_misclassified_as_a_cycle() -> None:
    shared = {"leaf": [None]}
    values = _manifest().model_dump(mode="python", round_trip=True)
    values["unexpected"] = [shared, shared]

    with pytest.raises(ValidationError) as raised:
        CompilationManifestView.model_validate(values)

    assert {error["type"] for error in raised.value.errors()} == {"extra_forbidden"}


@pytest.mark.parametrize(
    "nested",
    (
        pytest.param(_DuplicateMapping((("leaf", None),)), id="custom-mapping"),
        pytest.param(_CustomIterable(), id="custom-iterable"),
        pytest.param({_HiddenStr("leaf"): None}, id="str-subclass-key"),
        pytest.param((_HiddenStr("leaf"),), id="str-subclass-tuple-element"),
    ),
)
def test_tr8_s1_custom_graph_nodes_are_typed_failures(nested: object) -> None:
    values = {"unexpected": nested}
    with pytest.raises(ValidationError):
        CompilationManifestView.model_validate(values)
    with pytest.raises(ValidationError):
        TypeAdapter(CompilationManifestView).validate_python(values)


def test_tr8_s1_missing_and_extra_fields_remain_typed_schema_errors() -> None:
    with pytest.raises(ValidationError) as missing:
        CompilationManifestView.model_validate({})
    values = _manifest().model_dump(mode="python", round_trip=True)
    values["unexpected"] = None
    with pytest.raises(ValidationError) as extra:
        CompilationManifestView.model_validate(values)

    assert "missing" in {error["type"] for error in missing.value.errors()}
    assert {error["type"] for error in extra.value.errors()} == {"extra_forbidden"}


def test_tr8_s1_budget_guard_preserves_canonical_round_trip_and_digest() -> None:
    manifest = _manifest()
    payload = canonical_compilation_manifest_bytes(manifest)
    restored = parse_compilation_manifest(payload)

    assert restored == manifest
    assert canonical_compilation_manifest_bytes(restored) == payload
    assert compilation_manifest_digest(restored) == compilation_manifest_digest(manifest)


@pytest.mark.parametrize("exception_type", (KeyboardInterrupt, SystemExit, MemoryError))
def test_tr8_s1_copy_does_not_swallow_process_control_or_memory_failures(
    monkeypatch: pytest.MonkeyPatch,
    exception_type: type[BaseException],
) -> None:
    manifest = _manifest()

    def fail_graph_check(_value: object) -> None:
        raise exception_type()

    monkeypatch.setattr(
        compilation_manifest_module,
        "_require_exact_python_graph",
        fail_graph_check,
    )

    with pytest.raises(exception_type):
        manifest.model_copy(update={"compiled_at": "2026-07-24T00:00:00.000000Z"})


def _maximum_mixed_manifest() -> CompilationManifestView:
    inventory_size = 2_048
    artifacts = tuple(
        _artifact(path=f"artifacts/fact-{index:04d}.json")
        for index in range(inventory_size)
    )
    change_sets = tuple(
        _change_set(change_set_id=f"change-set-{index:04d}")
        for index in range(inventory_size)
    )
    change_items = tuple(
        _change_item(
            change_set_id=f"change-set-{index:04d}",
            change_item_id=f"change-item-{index:04d}",
            claim_id=f"claim-{index:04d}",
            blocking_review_ids=(f"review-{index:04d}",),
        )
        for index in range(inventory_size)
    )
    return _manifest(
        artifacts=artifacts,
        change_sets=change_sets,
        change_items=change_items,
        blocking_review_ids=tuple(
            f"review-{index:04d}" for index in range(inventory_size)
        ),
    )


def test_tr8_s1_semantic_inventory_maximum_round_trips_in_every_representation() -> None:
    manifest = _maximum_mixed_manifest()
    payload = canonical_compilation_manifest_bytes(manifest)
    restored = parse_compilation_manifest(payload)

    assert len(manifest.artifacts) == 2_048
    assert len(manifest.change_sets) == 2_048
    assert len(manifest.change_items) == 2_048
    assert len(manifest.blocking_review_ids) == 2_048
    assert restored == manifest
    assert compilation_manifest_digest(restored) == compilation_manifest_digest(manifest)


def test_tr8_s1_semantic_inventory_overflow_is_representation_independent() -> None:
    manifest = _maximum_mixed_manifest()
    extra_artifact = _artifact(path="artifacts/overflow.json")
    overflowing_artifacts = manifest.artifacts + (extra_artifact,)
    raw = manifest.model_dump(mode="python", round_trip=True)
    raw["artifacts"] = cast(tuple[object, ...], raw["artifacts"]) + (
        extra_artifact.model_dump(mode="python", round_trip=True),
    )

    with pytest.raises(ValidationError):
        _manifest(
            artifacts=overflowing_artifacts,
            change_sets=manifest.change_sets,
            change_items=manifest.change_items,
            blocking_review_ids=manifest.blocking_review_ids,
        )
    with pytest.raises(ValidationError):
        CompilationManifestView.model_validate(raw)
    with pytest.raises(ValidationError):
        TypeAdapter(CompilationManifestView).validate_python(raw)
    with pytest.raises(ValueError, match="invalid_compilation_manifest"):
        parse_compilation_manifest(
            json.dumps(raw, separators=(",", ":")).encode("utf-8")
        )
    with pytest.raises(RuntimeContractError, match="invalid_contract_dto"):
        manifest.model_copy(update={"artifacts": overflowing_artifacts})


def test_tr8_s1_public_canonical_functions_do_not_swallow_memory_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()

    monkeypatch.setattr(
        json,
        "dumps",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MemoryError("sentinel")),
    )
    with pytest.raises(MemoryError, match="sentinel"):
        canonical_compilation_manifest_bytes(manifest)


def test_tr8_s1_public_parser_does_not_swallow_memory_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        json,
        "loads",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MemoryError("sentinel")),
    )

    with pytest.raises(MemoryError, match="sentinel"):
        parse_compilation_manifest(b"{}")


@pytest.mark.parametrize("operation", ("digest", "canonical", "parse"))
def test_tr8_s1_public_manifest_paths_propagate_real_chain_memory_error(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    manifest = _manifest()
    payload = canonical_compilation_manifest_bytes(manifest)

    def fail_graph_check(_value: object) -> object:
        raise MemoryError("sentinel")

    monkeypatch.setattr(
        compilation_manifest_module,
        "_require_exact_python_graph",
        fail_graph_check,
    )

    with pytest.raises(MemoryError, match="sentinel"):
        if operation == "digest":
            compilation_manifest_digest(manifest)
        elif operation == "canonical":
            canonical_compilation_manifest_bytes(manifest)
        else:
            parse_compilation_manifest(payload)


@pytest.mark.parametrize("operation", ("digest", "canonical"))
def test_tr8_s1_public_sinks_propagate_shared_snapshot_memory_error(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    manifest = _manifest()

    def fail_snapshot(_value: object) -> object:
        raise MemoryError("sentinel")

    monkeypatch.setattr(
        "insurance_harness.runtime.models._read_contract_snapshot",
        fail_snapshot,
    )

    with pytest.raises(MemoryError, match="sentinel"):
        if operation == "digest":
            compilation_manifest_digest(manifest)
        else:
            canonical_compilation_manifest_bytes(manifest)


@pytest.mark.parametrize(
    "operation",
    (
        "constructor",
        "raw-model-validate",
        "existing-model-validate",
        "model-copy",
        "digest",
        "canonical",
        "parse",
    ),
)
def test_tr8_s1_public_paths_preserve_shared_allocator_memory_error_identity(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    manifest = _manifest()
    raw = manifest.model_dump(mode="python", round_trip=True)
    payload = canonical_compilation_manifest_bytes(manifest)
    sentinel = MemoryError(f"sentinel-{operation}")

    def fail_storage(*_args: object, **_kwargs: object) -> object:
        raise sentinel

    monkeypatch.setattr(
        "insurance_harness.runtime.models._snapshot_model_storage",
        fail_storage,
    )
    operations: dict[str, Any] = {
        "constructor": lambda: CompilationManifestView(**raw),
        "raw-model-validate": lambda: CompilationManifestView.model_validate(raw),
        "existing-model-validate": lambda: CompilationManifestView.model_validate(
            manifest
        ),
        "model-copy": lambda: manifest.model_copy(),
        "digest": lambda: compilation_manifest_digest(manifest),
        "canonical": lambda: canonical_compilation_manifest_bytes(manifest),
        "parse": lambda: parse_compilation_manifest(payload),
    }

    with pytest.raises(MemoryError) as raised:
        operations[operation]()

    assert raised.value is sentinel


def test_tr8_s1_public_validation_ingress_propagates_memory_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _manifest().model_dump(mode="python", round_trip=True)

    def fail_graph_check(_value: object) -> object:
        raise MemoryError("sentinel")

    monkeypatch.setattr(
        compilation_manifest_module,
        "_require_exact_python_graph",
        fail_graph_check,
    )

    with pytest.raises(MemoryError, match="sentinel"):
        CompilationManifestView.model_validate(values)
    with pytest.raises(MemoryError, match="sentinel"):
        TypeAdapter(CompilationManifestView).validate_python(values)


def test_tr8_s1_checked_snapshot_not_mutable_caller_graph_is_consumed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _manifest(
        artifacts=(
            _artifact(path="artifacts/a.json"),
            _artifact(path="artifacts/b.json"),
        )
    ).model_dump(mode="python", round_trip=True)
    original_check = compilation_manifest_module._require_exact_python_graph
    mutated = False

    def check_then_mutate(value: object) -> object:
        nonlocal mutated
        checked = original_check(value)
        if not mutated:
            raw_value = cast(dict[str, object], value)
            artifacts = cast(list[object] | tuple[object, ...], raw_value["artifacts"])
            if type(artifacts) is list:
                artifacts.pop()
            else:
                raw_value["artifacts"] = artifacts[:-1]
            mutated = True
        return checked

    monkeypatch.setattr(
        compilation_manifest_module,
        "_require_exact_python_graph",
        check_then_mutate,
    )

    result = CompilationManifestView.model_validate(raw)

    assert len(cast(tuple[object, ...], raw["artifacts"])) == 1
    assert len(result.artifacts) == 2


def test_tr8_s1_model_copy_consumes_the_checked_detached_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest(artifacts=())
    update_artifacts = [
        _artifact(path="artifacts/a.json"),
        _artifact(path="artifacts/b.json"),
    ]
    update: dict[str, object] = {"artifacts": update_artifacts}
    original_check = compilation_manifest_module._require_exact_python_graph
    mutated = False

    def check_then_mutate(value: object) -> object:
        nonlocal mutated
        checked = original_check(value)
        if not mutated:
            update_artifacts.pop()
            mutated = True
        return checked

    monkeypatch.setattr(
        compilation_manifest_module,
        "_require_exact_python_graph",
        check_then_mutate,
    )

    result = manifest.model_copy(update=update)

    assert len(update_artifacts) == 1
    assert len(result.artifacts) == 2
