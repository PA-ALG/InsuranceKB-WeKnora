"""031 O1: canonical product-meta input and clean-revision identity."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from insurance_harness.goldenset.admission_identity import (
    DeterministicIdentityInspector,
    IdentityInspectionRequest,
    IdentityInspectionResult,
)
from insurance_harness.goldenset.admission_models import (
    ProductInputPlan,
    canonical_json_bytes,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRODUCT_ID = "平安福满分（2026）养老年金保险"
_OLD_META_RELATIVE = f"dataset/shouxian_product/{_PRODUCT_ID}/product_meta.txt"
_TARGET_META_RELATIVE = f"dataset/shouxian_product/{_PRODUCT_ID}/product_meta.json"
_EXPECTED_META_SHA256 = (
    "f074916cec067cfd1c173afba2a0460a22c6e24a2d7085518ae49ffc531aa9ae"
)
_EXPECTED_META = {
    "planCode": "1820",
    "actualPlanCode": "1820",
    "versionNo": "1820-1",
    "clauseName": _PRODUCT_ID,
    "planSalesStatus": "在售",
    "planPlanType": "普通型",
    "planSalesChannel": "个人代理、电话销售",
    "seq": "1",
    "clauseContent": "1",
    "premAttachment": "1",
    "regionCode": "00",
    "recordList": "1",
    "actuaryInstruction": "1",
    "legalPerson": "1",
    "productInstruction": "1",
    "startDate": "2025-09-01",
    "reportPreparedFileCode": "平保寿发〔2025〕343号",
    "versionCount": "1",
    "sccode": "平安人寿〔2025〕年金保险142号",
    "productLevel": "P2",
}


def _git(
    repo: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args),
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


def _git_output(repo: Path, *args: str) -> str:
    return _git(repo, *args).stdout.strip()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write(repo: Path, relative_path: str, content: bytes) -> None:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git_output(repo, "rev-parse", "HEAD")


def _make_repository(tmp_path: Path) -> tuple[Path, bytes]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "operational-input@example.invalid")
    _git(repo, "config", "user.name", "Operational Input Tests")

    old_meta = b'{\n  "planCode": "1820",\n  "clauseName": "product-01"\n}\n'
    _write(repo, "inputs/source/product-01/product_meta.txt", old_meta)
    _write(repo, "inputs/golden/product-01/fields.json", b'{"fields":[]}\n')
    _write(repo, "shared/schema.json", b'{"schema":"v1"}\n')
    _write(repo, "harness/src/identity_runner.py", b"def run() -> None:\n    pass\n")
    _commit_all(repo, "seed legacy product meta")
    return repo, old_meta


def _request(repo: Path, meta_bytes: bytes) -> IdentityInspectionRequest:
    return IdentityInspectionRequest(
        required_dependency_revisions={},
        source_products_root="inputs/source",
        golden_products_root="inputs/golden",
        products=(
            ProductInputPlan(
                product_id="product-01",
                line_key="annuity",
                pdf_digests={},
                product_meta_digest=_sha256(meta_bytes),
                fields_digest=_sha256(
                    (repo / "inputs/golden/product-01/fields.json").read_bytes()
                ),
                consumed_input_digests={},
            ),
        ),
        shared_input_digests={
            "shared/schema.json": _sha256(
                (repo / "shared/schema.json").read_bytes()
            )
        },
        execution_surface_digests={
            "harness/src/identity_runner.py": _sha256(
                (repo / "harness/src/identity_runner.py").read_bytes()
            )
        },
        historical_product_ids=(),
        historical_provenance=(),
    )


def _inspector(repo: Path) -> DeterministicIdentityInspector:
    return DeterministicIdentityInspector._for_testing(
        repo_root=repo,
        expected_product_lines={"product-01": "annuity"},
        historical_product_ids=frozenset(),
        source_products_root="inputs/source",
        golden_products_root="inputs/golden",
        execution_roots=("harness/src",),
        shared_roots=("shared",),
        required_dependency_revisions={},
    )


def _canonical_semantics(content: bytes) -> bytes:
    return json.dumps(
        json.loads(content),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def test_o1_production_meta_uses_only_canonical_path_with_exact_bytes() -> None:
    old_path = _REPO_ROOT / _OLD_META_RELATIVE
    target_path = _REPO_ROOT / _TARGET_META_RELATIVE

    assert not old_path.exists(), "legacy product_meta.txt must be removed, not ignored"
    assert target_path.is_file()
    target_bytes = target_path.read_bytes()
    assert _sha256(target_bytes) == _EXPECTED_META_SHA256
    assert json.loads(target_bytes) == _EXPECTED_META
    assert _canonical_semantics(target_bytes) == _canonical_semantics(
        json.dumps(_EXPECTED_META, ensure_ascii=False).encode("utf-8")
    )
    ignored = _git(
        _REPO_ROOT,
        "check-ignore",
        "--no-index",
        "--quiet",
        "--",
        _OLD_META_RELATIVE,
        check=False,
    )
    assert ignored.returncode == 1, "legacy path must be absent, not hidden by ignore rules"


def test_o1_clean_committed_rename_recomputes_all_identity_layers(
    tmp_path: Path,
) -> None:
    repo, old_bytes = _make_repository(tmp_path)
    request = _request(repo, old_bytes)
    inspector = _inspector(repo)

    legacy = inspector.inspect(request)
    assert any(
        blocker.code == "missing_path"
        and blocker.path == "inputs/source/product-01/product_meta.json"
        for blocker in legacy.blockers
    )
    assert any(
        blocker.code == "unconsumed_product_file"
        and blocker.path == "inputs/source/product-01/product_meta.txt"
        for blocker in legacy.blockers
    )

    old_path = repo / "inputs/source/product-01/product_meta.txt"
    target_path = old_path.with_name("product_meta.json")
    assert json.loads(old_bytes)
    old_path.rename(target_path)
    target_bytes = target_path.read_bytes()
    assert target_bytes == old_bytes
    assert _canonical_semantics(target_bytes) == _canonical_semantics(old_bytes)
    clean_revision = _commit_all(repo, "rename product meta without changing bytes")

    assert _git_output(repo, "status", "--porcelain=v1") == ""
    assert not old_path.exists()
    assert _git_output(repo, "ls-files", "--", old_path.relative_to(repo).as_posix()) == ""
    ignored = _git(
        repo,
        "check-ignore",
        "--no-index",
        "--quiet",
        "--",
        old_path.relative_to(repo).as_posix(),
        check=False,
    )
    assert ignored.returncode == 1

    result = inspector.inspect(request)
    assert isinstance(result, IdentityInspectionResult)
    assert result.evaluated_revision == clean_revision
    assert not result.blockers

    product_observed = {
        "golden/fields.json": {
            "type": "file",
            "sha256": _sha256(
                (repo / "inputs/golden/product-01/fields.json").read_bytes()
            ),
        },
        "source/product_meta.json": {
            "type": "file",
            "sha256": _sha256(target_bytes),
        },
    }
    shared_observed = {
        "shared/schema.json": {
            "type": "file",
            "sha256": _sha256((repo / "shared/schema.json").read_bytes()),
        }
    }
    execution_observed = {
        "harness/src/identity_runner.py": {
            "type": "file",
            "sha256": _sha256(
                (repo / "harness/src/identity_runner.py").read_bytes()
            ),
        }
    }
    assert result.product_digests == {
        "product-01": _sha256(canonical_json_bytes(product_observed))
    }
    assert result.shared_input_digest == _sha256(canonical_json_bytes(shared_observed))
    assert result.execution_surface_digest == _sha256(
        canonical_json_bytes(execution_observed)
    )


def test_o1_dirty_uncommitted_input_cannot_be_authoritative(tmp_path: Path) -> None:
    repo, meta_bytes = _make_repository(tmp_path)
    old_path = repo / "inputs/source/product-01/product_meta.txt"
    target_path = old_path.with_name("product_meta.json")
    old_path.rename(target_path)
    clean_revision = _commit_all(repo, "rename product meta without changing bytes")
    request = _request(repo, meta_bytes)
    inspector = _inspector(repo)
    authoritative = inspector.inspect(request)
    assert not authoritative.blockers

    target_path.write_bytes(meta_bytes + b" \n")
    dirty = inspector.inspect(request)

    assert dirty.evaluated_revision == clean_revision
    assert dirty.product_digests != authoritative.product_digests
    assert any(
        blocker.code == "digest_mismatch"
        and blocker.path == "inputs/source/product-01/product_meta.json"
        for blocker in dirty.blockers
    )
    assert any(
        blocker.code == "dirty_consumed_file"
        and blocker.path == "inputs/source/product-01/product_meta.json"
        for blocker in dirty.blockers
    )
