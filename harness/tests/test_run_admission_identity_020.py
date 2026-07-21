"""020 D1.1b/D1.1c: deterministic dependency and consumed-input identity."""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from insurance_harness.goldenset.admission_identity import (
    DeterministicIdentityInspector,
    IdentityInspectionBlocker,
    IdentityInspectionRequest,
    IdentityInspectionResult,
)
from insurance_harness.goldenset.admission_models import (
    HistoricalProvenance,
    ProductInputPlan,
    ProductInputSelection,
)

_PRODUCT_IDS = tuple(f"product-{number:02d}" for number in range(1, 14))
_HISTORICAL_PRODUCT_IDS = _PRODUCT_IDS[:11]
_ANNOTATED_AT = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _write(repo: Path, relative_path: str, content: str) -> None:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _make_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "identity-tests@example.invalid")
    _git(repo, "config", "user.name", "Identity Tests")

    for product_id in _PRODUCT_IDS:
        source_root = f"inputs/source/{product_id}"
        golden_root = f"inputs/golden/{product_id}"
        _write(repo, f"{source_root}/terms.pdf", f"PDF terms for {product_id}\n")
        if product_id == _PRODUCT_IDS[0]:
            _write(repo, f"{source_root}/rates.pdf", f"PDF rates for {product_id}\n")
        _write(repo, f"{source_root}/product_meta.json", f'{{"id":"{product_id}"}}\n')
        _write(repo, f"{golden_root}/fields.json", '{"fields":["coverage"]}\n')
        _write(
            repo,
            f"{golden_root}/wip-golden.jsonl",
            f'{{"product_id":"{product_id}"}}\n',
        )
        _write(repo, f"{golden_root}/other-consumed.txt", f"other input for {product_id}\n")

    _write(repo, "shared/schema.json", '{"schema":"v1"}\n')
    _write(repo, "shared/prompt.md", "Extract only supported facts.\n")
    _write(repo, "shared/template.md", "# Product facts\n")
    _write(repo, "harness/src/identity_runner.py", "def run() -> None:\n    pass\n")
    _write(repo, "harness/config/runtime.yaml", "identity_version: 1\n")
    return repo, _commit_all(repo, "seed deterministic identity fixture")


def _product_plan(repo: Path, product_id: str) -> ProductInputPlan:
    source_root = repo / "inputs" / "source" / product_id
    golden_root = repo / "inputs" / "golden" / product_id
    return ProductInputPlan(
        product_id=product_id,
        line_key="life",
        pdf_digests={
            path.name: _sha256(path) for path in sorted(source_root.glob("*.pdf"))
        },
        product_meta_digest=_sha256(source_root / "product_meta.json"),
        fields_digest=_sha256(golden_root / "fields.json"),
        consumed_input_digests={
            "wip-golden.jsonl": _sha256(golden_root / "wip-golden.jsonl"),
            "other-consumed.txt": _sha256(golden_root / "other-consumed.txt"),
        },
    )


def _provenance(product_id: str) -> HistoricalProvenance:
    return HistoricalProvenance(
        product_id=product_id,
        annotator_provider="provider-a",
        annotator_model_id="annotator-model-1",
        annotated_at_start=_ANNOTATED_AT,
        annotated_at_end=_ANNOTATED_AT + timedelta(minutes=30),
        evidence_basis=f"provider audit record for {product_id}",
    )


def _request(
    repo: Path,
    *,
    products: Iterable[ProductInputSelection] | None = None,
    source_products_root: str = "inputs/source",
    golden_products_root: str = "inputs/golden",
    required_dependency_revisions: Mapping[str, str] | None = None,
    historical_product_ids: tuple[str, ...] | None = None,
    historical_provenance: tuple[HistoricalProvenance, ...] | None = None,
) -> IdentityInspectionRequest:
    revision = _git(repo, "rev-parse", "HEAD")
    return IdentityInspectionRequest(
        required_dependency_revisions=(
            {"019": revision, "021": revision}
            if required_dependency_revisions is None
            else required_dependency_revisions
        ),
        source_products_root=source_products_root,
        golden_products_root=golden_products_root,
        products=tuple(products)
        if products is not None
        else tuple(_product_plan(repo, product_id) for product_id in _PRODUCT_IDS),
        shared_input_digests={
            path: _sha256(repo / path)
            for path in ("shared/schema.json", "shared/prompt.md", "shared/template.md")
        },
        execution_surface_digests={
            path: _sha256(repo / path)
            for path in (
                "harness/src/identity_runner.py",
                "harness/config/runtime.yaml",
            )
        },
        historical_product_ids=(
            _HISTORICAL_PRODUCT_IDS
            if historical_product_ids is None
            else historical_product_ids
        ),
        historical_provenance=(
            tuple(_provenance(product_id) for product_id in _HISTORICAL_PRODUCT_IDS)
            if historical_provenance is None
            else historical_provenance
        ),
    )


def _inspect(repo: Path, request: IdentityInspectionRequest) -> IdentityInspectionResult:
    inspector = _inspector(repo)
    result = inspector.inspect(request)
    assert isinstance(result, IdentityInspectionResult)
    return result


def _inspector(repo: Path) -> DeterministicIdentityInspector:
    return DeterministicIdentityInspector._for_testing(
        repo_root=repo,
        expected_product_lines={product_id: "life" for product_id in _PRODUCT_IDS},
        historical_product_ids=frozenset(_HISTORICAL_PRODUCT_IDS),
        source_products_root="inputs/source",
        golden_products_root="inputs/golden",
        execution_roots=("harness/src", "harness/config"),
        shared_roots=("shared",),
    )


def _blockers(
    result: IdentityInspectionResult, code: str
) -> tuple[IdentityInspectionBlocker, ...]:
    return tuple(blocker for blocker in result.blockers if blocker.code == code)


def test_d1_1b_manifest_requires_exactly_thirteen_unique_products(
    tmp_path: Path,
) -> None:
    repo, revision = _make_repo(tmp_path)

    result = _inspect(repo, _request(repo))

    assert result.evaluated_revision == revision
    assert set(result.product_digests) == set(_PRODUCT_IDS)
    assert not result.blockers


def test_d1_1b_hashes_every_pdf_meta_fields_and_other_consumed_input(
    tmp_path: Path,
) -> None:
    repo, _ = _make_repo(tmp_path)
    pinned = _request(repo)
    consumed_paths = (
        "inputs/source/product-01/terms.pdf",
        "inputs/source/product-01/rates.pdf",
        "inputs/source/product-01/product_meta.json",
        "inputs/golden/product-01/fields.json",
        "inputs/golden/product-01/wip-golden.jsonl",
        "inputs/golden/product-01/other-consumed.txt",
    )

    for relative_path in consumed_paths:
        path = repo / relative_path
        original = path.read_text(encoding="utf-8")
        path.write_text(original + "changed\n", encoding="utf-8")
        _commit_all(repo, f"change {path.name}")

        result = _inspect(repo, pinned)

        assert any(
            blocker.code == "digest_mismatch" and blocker.path == relative_path
            for blocker in result.blockers
        ), relative_path
        path.write_text(original, encoding="utf-8")
        _commit_all(repo, f"restore {path.name}")


def test_d1_1b_pdf_identity_binds_filename_not_only_digest(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    pinned = _request(repo)
    original = repo / "inputs/source/product-01/terms.pdf"
    renamed = original.with_name("renamed-terms.pdf")
    original.rename(renamed)
    _commit_all(repo, "rename consumed pdf without changing its bytes")

    result = _inspect(repo, pinned)

    assert any(
        blocker.code == "digest_mismatch"
        and blocker.path == "inputs/source/product-01/terms.pdf"
        for blocker in result.blockers
    )


@pytest.mark.parametrize(
    "case, expected_code",
    (
        ("missing", "missing_product"),
        ("extra", "extra_product"),
        ("duplicate", "duplicate_product"),
        ("absolute", "absolute_path"),
        ("symlink_escape", "path_escape"),
    ),
)
def test_d1_1b_rejects_missing_extra_duplicate_absolute_or_symlink_escape(
    tmp_path: Path,
    case: str,
    expected_code: str,
) -> None:
    repo, _ = _make_repo(tmp_path)
    products = tuple(_product_plan(repo, product_id) for product_id in _PRODUCT_IDS)
    source_products_root = "inputs/source"

    if case == "missing":
        missing = repo / source_products_root / _PRODUCT_IDS[-1]
        for path in sorted(missing.iterdir()):
            path.unlink()
        missing.rmdir()
        _commit_all(repo, "remove required product")
    elif case == "extra":
        _write(repo, f"{source_products_root}/unexpected/product_meta.json", "{}\n")
        _commit_all(repo, "add unexpected product")
    elif case == "duplicate":
        products = (*products, products[0])
    elif case == "absolute":
        source_products_root = str((repo / source_products_root).resolve())
    else:
        outside = tmp_path / "outside-product"
        outside.mkdir()
        link = repo / source_products_root / _PRODUCT_IDS[0]
        for path in sorted(link.iterdir()):
            path.unlink()
        link.rmdir()
        link.symlink_to(outside, target_is_directory=True)
        _commit_all(repo, "replace product with escaping symlink")

    result = _inspect(
        repo,
        _request(
            repo,
            products=products,
            source_products_root=source_products_root,
        ),
    )

    assert _blockers(result, expected_code)


def test_d1_1b_detects_dirty_and_untracked_consumed_files(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    request = _request(repo)
    dirty = "shared/schema.json"
    untracked = "harness/src/unlisted_helper.py"
    _write(repo, dirty, "dirty schema\n")
    _write(repo, untracked, "SECRET_BEHAVIOR = True\n")

    result = _inspect(repo, request)

    assert any(
        blocker.code == "dirty_consumed_file" and blocker.path == dirty
        for blocker in result.blockers
    )
    assert any(
        blocker.code == "untracked_consumed_file" and blocker.path == untracked
        for blocker in result.blockers
    )


def test_d1_1b_dependency_revision_must_be_ancestor(tmp_path: Path) -> None:
    repo, revision_019 = _make_repo(tmp_path)
    _write(repo, "dependency-021.txt", "merged 021\n")
    revision_021 = _commit_all(repo, "merge dependency 021")
    current_branch = _git(repo, "branch", "--show-current")
    _write(repo, "evaluated.txt", "evaluated revision\n")
    _commit_all(repo, "evaluated revision")

    valid = _inspect(
        repo,
        _request(
            repo,
            required_dependency_revisions={"019": revision_019, "021": revision_021},
        ),
    )
    assert not _blockers(valid, "dependency_not_ancestor")

    _git(repo, "switch", "-c", "unmerged-021", revision_019)
    _write(repo, "unmerged.txt", "not in evaluated history\n")
    unmerged_021 = _commit_all(repo, "unmerged dependency candidate")
    _git(repo, "switch", current_branch)
    blocked = _inspect(
        repo,
        _request(
            repo,
            required_dependency_revisions={"019": revision_019, "021": unmerged_021},
        ),
    )

    assert any(
        blocker.code == "dependency_not_ancestor" and blocker.subject == "021"
        for blocker in blocked.blockers
    )


def test_d1_1b_execution_surface_digest_changes_for_any_consumed_code(
    tmp_path: Path,
) -> None:
    repo, _ = _make_repo(tmp_path)
    request = _request(repo)
    baseline = _inspect(repo, request)
    previous_digest = baseline.execution_surface_digest

    for relative_path in (
        "harness/src/identity_runner.py",
        "harness/config/runtime.yaml",
    ):
        path = repo / relative_path
        path.write_text(path.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
        _commit_all(repo, f"change execution surface {path.name}")

        result = _inspect(repo, request)

        assert result.execution_surface_digest != previous_digest, relative_path
        assert any(
            blocker.code == "digest_mismatch" and blocker.path == relative_path
            for blocker in result.blockers
        )
        previous_digest = result.execution_surface_digest


def test_d1_1b_fixed_request_blocks_committed_unlisted_execution_file(
    tmp_path: Path,
) -> None:
    repo, _ = _make_repo(tmp_path)
    request = _request(repo)
    baseline = _inspect(repo, request)
    _write(repo, "harness/src/committed-helper.py", "SURPRISE = True\n")
    _commit_all(repo, "add unlisted execution helper")

    result = _inspect(repo, request)

    assert result.execution_surface_digest != baseline.execution_surface_digest
    assert any(
        blocker.code == "execution_surface_unpinned"
        and blocker.path == "harness/src/committed-helper.py"
        for blocker in result.blockers
    )


@pytest.mark.parametrize(
    ("relative_path", "expected_code"),
    (
        ("inputs/source/product-01/shadow.txt", "unconsumed_product_file"),
        ("inputs/golden/product-01/shadow.json", "unconsumed_product_file"),
        ("shared/unlisted-template.md", "shared_input_unpinned"),
    ),
)
def test_d1_1b_fixed_request_blocks_each_committed_unlisted_consumed_file(
    tmp_path: Path, relative_path: str, expected_code: str
) -> None:
    repo, _ = _make_repo(tmp_path)
    request = _request(repo)
    baseline = _inspect(repo, request)
    _write(repo, relative_path, "UNLISTED = True\n")
    _commit_all(repo, f"add {relative_path}")

    result = _inspect(repo, request)

    if relative_path.startswith("shared/"):
        assert result.shared_input_digest != baseline.shared_input_digest
    else:
        assert (
            result.product_digests["product-01"]
            != baseline.product_digests["product-01"]
        )
    assert any(
        blocker.code == expected_code and blocker.path == relative_path
        for blocker in result.blockers
    )


def test_d1_1b_empty_shared_or_product_consumed_manifest_cannot_hide_files(
    tmp_path: Path,
) -> None:
    repo, _ = _make_repo(tmp_path)
    request = _request(repo)
    products = list(request.products)
    products[0] = products[0].model_copy(update={"consumed_input_digests": {}})
    reduced = request.model_copy(
        update={"shared_input_digests": {}, "products": tuple(products)}
    )

    result = _inspect(repo, reduced)

    assert _blockers(result, "shared_input_unpinned")
    assert any(
        blocker.code == "unconsumed_product_file"
        and blocker.path == "inputs/golden/product-01/wip-golden.jsonl"
        for blocker in result.blockers
    )


def test_d1_1c_reports_each_unattested_historical_product(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    attested = _HISTORICAL_PRODUCT_IDS[:2]
    golden_paths = tuple(
        repo / "inputs" / "golden" / product_id / "wip-golden.jsonl"
        for product_id in _HISTORICAL_PRODUCT_IDS
    )
    before = tuple(_sha256(path) for path in golden_paths)

    result = _inspect(
        repo,
        _request(
            repo,
            historical_product_ids=_HISTORICAL_PRODUCT_IDS,
            historical_provenance=tuple(_provenance(product_id) for product_id in attested),
        ),
    )

    missing = _blockers(result, "missing_historical_provenance")
    assert [blocker.product_id for blocker in missing] == list(
        _HISTORICAL_PRODUCT_IDS[len(attested) :]
    )
    assert len(missing) == len(_HISTORICAL_PRODUCT_IDS) - len(attested)
    assert tuple(_sha256(path) for path in golden_paths) == before


def test_d1_1b_public_inspector_policy_cannot_be_substituted(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    with pytest.raises(TypeError):
        DeterministicIdentityInspector(  # type: ignore[call-arg]
            repo_root=repo,
            expected_product_ids=frozenset(_PRODUCT_IDS),
        )


def test_d1_1b_production_policy_locks_schema_and_root_file_selection(
    tmp_path: Path,
) -> None:
    repo, _ = _make_repo(tmp_path)
    inspector = DeterministicIdentityInspector(repo_root=repo)

    assert "docs/insurance-kb/schema-baseline" in inspector._policy.shared_roots
    assert inspector._policy.source_root_files == frozenset()
    assert inspector._policy.golden_root_files == frozenset(
        {"manifest.json", "build_golden.py", "assemble_release.py"}
    )


@pytest.mark.parametrize(
    "relative_path",
    (
        "inputs/source/root-control.json",
        "inputs/golden/root-control.json",
    ),
)
def test_d1_1b_fixed_request_blocks_committed_unlisted_product_root_file(
    tmp_path: Path, relative_path: str
) -> None:
    repo, _ = _make_repo(tmp_path)
    request = _request(repo)
    _write(repo, relative_path, "{}\n")
    _commit_all(repo, f"add {relative_path}")

    result = _inspect(repo, request)

    assert any(
        blocker.code == "unconsumed_product_file"
        and blocker.path == relative_path
        for blocker in result.blockers
    )


def test_d1_1b_product_root_symlink_file_fails_closed(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    request = _request(repo)
    outside = tmp_path / "outside-root-control.json"
    outside.write_text("{}\n", encoding="utf-8")
    relative = "inputs/source/root-control.json"
    (repo / relative).symlink_to(outside)
    _commit_all(repo, "add source-root symlink file")

    result = _inspect(repo, request)

    assert any(
        blocker.code == "path_escape" and blocker.path == relative
        for blocker in result.blockers
    )


@pytest.mark.parametrize(
    "dependencies",
    ({"019": "HEAD"}, {"019": "HEAD", "021": "HEAD", "invented": "HEAD"}, {}),
)
def test_d1_1b_dependency_keys_are_exactly_code_owned(
    tmp_path: Path, dependencies: Mapping[str, str]
) -> None:
    repo, _ = _make_repo(tmp_path)
    result = _inspect(
        repo,
        _request(repo, required_dependency_revisions=dependencies),
    )
    assert _blockers(result, "dependency_set_mismatch")


def test_d1_1b_wrong_line_key_and_empty_historical_set_block(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    products = list(_request(repo).products)
    products[0] = products[0].model_copy(update={"line_key": "invented-line"})
    result = _inspect(
        repo,
        _request(
            repo,
            products=products,
            historical_product_ids=(),
            historical_provenance=(),
        ),
    )
    assert _blockers(result, "line_key_mismatch")
    assert len(_blockers(result, "missing_historical_product")) == 11


@pytest.mark.parametrize("kind", ("pdf", "golden"))
def test_d1_1b_rejects_each_consumed_file_symlink_escape(
    tmp_path: Path, kind: str
) -> None:
    repo, _ = _make_repo(tmp_path)
    request = _request(repo)
    relative = (
        "inputs/source/product-01/terms.pdf"
        if kind == "pdf"
        else "inputs/golden/product-01/other-consumed.txt"
    )
    path = repo / relative
    outside = tmp_path / f"outside-{kind}"
    outside.write_text("same bytes do not make the path safe\n", encoding="utf-8")
    path.unlink()
    path.symlink_to(outside)
    _commit_all(repo, f"replace {kind} with escaping symlink")

    result = _inspect(repo, request)

    assert any(
        blocker.code == "path_escape" and blocker.path == relative
        for blocker in result.blockers
    )


@pytest.mark.parametrize(
    "field_name,value",
    (
        ("pdf_digests", {"../terms.pdf": "a" * 64}),
        ("pdf_digests", {"/terms.pdf": "a" * 64}),
        ("pdf_digests", {"other/terms.pdf": "a" * 64}),
        ("pdf_digests", {"fields.json": "a" * 64}),
        ("consumed_input_digests", {"fields.json": "a" * 64}),
        ("product_meta_path", ".."),
        ("product_meta_path", "../product_meta.json"),
        ("product_meta_path", "/product_meta.json"),
        ("product_meta_path", "shadow.json"),
    ),
)
def test_d1_1b_product_paths_reject_escape_and_reserved_collisions(
    field_name: str,
    value: object,
) -> None:
    values: dict[str, object] = {
        "product_id": "product-01",
        "line_key": "life",
        "pdf_digests": {"terms.pdf": "a" * 64},
        "product_meta_digest": "b" * 64,
        "fields_digest": "c" * 64,
        "consumed_input_digests": {"golden.jsonl": "d" * 64},
    }
    values[field_name] = value
    with pytest.raises(ValidationError):
        ProductInputPlan.model_validate(values)


def test_d1_1c_duplicate_and_unknown_provenance_block_per_product(
    tmp_path: Path,
) -> None:
    repo, _ = _make_repo(tmp_path)
    duplicate = _provenance(_HISTORICAL_PRODUCT_IDS[0])
    unknown = _provenance(_PRODUCT_IDS[-1])
    valid = tuple(_provenance(product_id) for product_id in _HISTORICAL_PRODUCT_IDS)
    result = _inspect(
        repo,
        _request(repo, historical_provenance=(*valid, duplicate, unknown)),
    )
    assert _blockers(result, "duplicate_historical_provenance")
    assert _blockers(result, "unknown_historical_provenance")


def test_d1_1b_git_rev_parse_and_status_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = _make_repo(tmp_path)
    request = _request(repo)
    inspector = _inspector(repo)
    original = inspector._git

    def fail_rev_parse(*args: str) -> subprocess.CompletedProcess[str]:
        if args == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess(("git", *args), 128, "", "failed")
        return original(*args)

    monkeypatch.setattr(inspector, "_git", fail_rev_parse)
    assert _blockers(inspector.inspect(request), "identity_configuration_error")

    def fail_status(*args: str) -> subprocess.CompletedProcess[str]:
        if args[:2] == ("--literal-pathspecs", "status"):
            return subprocess.CompletedProcess(("git", *args), 128, "", "failed")
        return original(*args)

    monkeypatch.setattr(inspector, "_git", fail_status)
    assert _blockers(inspector.inspect(request), "identity_configuration_error")


def test_d1_1b_execution_directory_symlink_is_not_skipped(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    request = _request(repo)
    execution_root = repo / "harness/src"
    for path in execution_root.iterdir():
        path.unlink()
    execution_root.rmdir()
    outside = tmp_path / "outside-execution"
    outside.mkdir()
    (outside / "identity_runner.py").write_text("EVIL = True\n", encoding="utf-8")
    execution_root.symlink_to(outside, target_is_directory=True)
    _commit_all(repo, "replace execution root with symlink")

    result = _inspect(repo, request)

    assert any(
        blocker.code == "path_escape" and blocker.path == "harness/src"
        for blocker in result.blockers
    )

def test_d1_1b_porcelain_z_preserves_unusual_untracked_paths(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    request = _request(repo)
    unusual = (
        "harness/src/space name.py",
        "harness/src/中文.py",
        "harness/src/a -> b.py",
        "harness/src/line\nbreak.py",
    )
    for path in unusual:
        _write(repo, path, "UNTRACKED = True\n")
    result = _inspect(repo, request)
    observed = {
        blocker.path
        for blocker in result.blockers
        if blocker.code == "untracked_consumed_file"
    }
    assert set(unusual) <= observed


def test_d1_1b_git_status_uses_literal_pathspecs_for_magic_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = _make_repo(tmp_path)
    request = _request(repo)
    inspector = _inspector(repo)
    original = inspector._git
    calls: list[tuple[str, ...]] = []

    def recording_git(*args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(inspector, "_git", recording_git)
    _write(repo, "harness/src/:(glob)magic?.py", "UNTRACKED = True\n")
    result = inspector.inspect(request)

    status_call = next(args for args in calls if "status" in args)
    assert status_call[:2] == ("--literal-pathspecs", "status")
    assert any(
        blocker.code == "untracked_consumed_file"
        and blocker.path == "harness/src/:(glob)magic?.py"
        for blocker in result.blockers
    )


def test_d1_1b_safe_hash_rejects_final_component_symlink_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = _make_repo(tmp_path)
    inspector = _inspector(repo)
    relative = "shared/schema.json"
    target = repo / relative
    outside = tmp_path / "evil-schema.json"
    outside.write_text("EVIL\n", encoding="utf-8")

    def swap_final(observed_relative: str) -> None:
        assert observed_relative == relative
        target.unlink()
        target.symlink_to(outside)

    monkeypatch.setattr(inspector, "_before_final_open", swap_final)
    blockers: list[IdentityInspectionBlocker] = []

    assert inspector._safe_sha256(relative, blockers) is None
    assert any(blocker.code == "path_escape" for blocker in blockers)


def test_d1_1b_safe_hash_parent_swap_reads_opened_safe_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = _make_repo(tmp_path)
    inspector = _inspector(repo)
    relative = "inputs/source/product-01/terms.pdf"
    expected = _sha256(repo / relative)
    product_root = repo / "inputs/source/product-01"
    saved_root = product_root.with_name("product-01-opened")
    outside_root = tmp_path / "evil-product"
    outside_root.mkdir()
    (outside_root / "terms.pdf").write_text("EVIL\n", encoding="utf-8")

    def swap_parent(observed_relative: str) -> None:
        assert observed_relative == relative
        product_root.rename(saved_root)
        product_root.symlink_to(outside_root, target_is_directory=True)

    monkeypatch.setattr(inspector, "_before_final_open", swap_parent)
    blockers: list[IdentityInspectionBlocker] = []

    assert inspector._safe_sha256(relative, blockers) == expected
    assert not blockers


def test_d1_1b_identity_contract_copy_cannot_bypass_validation(
    tmp_path: Path,
) -> None:
    repo, _ = _make_repo(tmp_path)
    request = _request(repo)
    with pytest.raises(TypeError):
        request.copy(update={"source_products_root": "/escape"})
    with pytest.raises(ValidationError):
        request.model_copy(update={"products": "not-products"})
