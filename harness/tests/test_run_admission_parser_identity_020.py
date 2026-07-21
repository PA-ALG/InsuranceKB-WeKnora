"""OpenSpec 020 D1.5: domain-separated directory parser identity."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from insurance_harness.goldenset.admission import RunAdmissionDocument
from insurance_harness.goldenset.admission_cli import _safe_load_unique
from insurance_harness.goldenset.admission_models import canonical_json_bytes
from insurance_harness.goldenset.admission_runtime import AdmissionPausedError
from tests.run_admission_execution_contract_020 import (
    ExecutionArtifacts020,
    execution_artifacts_or_skip,
)

_ALGORITHM_PATH = "harness/src/insurance_harness/goldenset/pdf.py"
_LOCK_PATH = "harness/uv.lock"
_DIRECT_DEPENDENCY = "pdfplumber"
_POLICY_VERSION = "insurancekb.directory-pdfplumber.v1"
_FINGERPRINT_DOMAIN = b"insurancekb.directory-parser-fingerprint.v1\0"


@dataclass(slots=True)
class _ParserContext:
    document: object
    configuration: object
    algorithm_path: Path
    lock_path: Path


@pytest.fixture
def artifact_contract() -> ExecutionArtifacts020:
    contract, _module = execution_artifacts_or_skip()
    return contract


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _lock_bytes(version: str, *, prefix: str = "") -> bytes:
    return (
        f"{prefix}version = 1\n\n"
        "[[package]]\n"
        f'name = "{_DIRECT_DEPENDENCY}"\n'
        f'version = "{version}"\n'
    ).encode()


def _context(tmp_path: Path, *, locked_version: str = "0.11.7") -> _ParserContext:
    repo_root = tmp_path / "repo"
    algorithm_path = repo_root / _ALGORITHM_PATH
    lock_path = repo_root / _LOCK_PATH
    algorithm_path.parent.mkdir(parents=True)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    algorithm_bytes = b'PARSER_ALGORITHM_VERSION = "insurancekb.pdf.v1"\n'
    lock_bytes = _lock_bytes(locked_version)
    algorithm_path.write_bytes(algorithm_bytes)
    lock_path.write_bytes(lock_bytes)
    document = SimpleNamespace(
        identity_request=SimpleNamespace(
            execution_surface_digests={
                _ALGORITHM_PATH: _sha256(algorithm_bytes),
                _LOCK_PATH: _sha256(lock_bytes),
            }
        )
    )
    return _ParserContext(
        document=document,
        configuration=SimpleNamespace(repo_root=repo_root),
        algorithm_path=algorithm_path,
        lock_path=lock_path,
    )


def _fingerprint(
    contract: ExecutionArtifacts020,
    context: _ParserContext,
    *,
    installed: str,
) -> str:
    return contract.directory_parser_fingerprint(
        document=context.document,
        configuration=context.configuration,
        installed_version=lambda package: (
            installed if package == _DIRECT_DEPENDENCY else "unexpected-package"
        ),
    )


def _expected_fingerprint(context: _ParserContext, *, installed: str) -> str:
    surface = context.document.identity_request.execution_surface_digests  # type: ignore[attr-defined]
    payload = canonical_json_bytes(
        {
            "algorithm": {
                "path": _ALGORITHM_PATH,
                "sha256": surface[_ALGORITHM_PATH],
            },
            "direct_dependency": {
                "installed_version": installed,
                "locked_version": installed,
                "name": _DIRECT_DEPENDENCY,
            },
            "lock": {
                "path": _LOCK_PATH,
                "sha256": surface[_LOCK_PATH],
            },
            "policy_version": _POLICY_VERSION,
        }
    )
    return hashlib.sha256(_FINGERPRINT_DOMAIN + payload).hexdigest()


def _refresh_surface_digest(context: _ParserContext, relative: str, path: Path) -> None:
    surface = context.document.identity_request.execution_surface_digests  # type: ignore[attr-defined]
    surface[relative] = _sha256(path.read_bytes())


def test_d1_1b_static_run_admission_binds_real_harness_lockfile_bytes() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    plan_path = (
        repo_root
        / "openspec/changes/020-golden-v01-baseline-run/run-admission.yaml"
    )
    document = RunAdmissionDocument.model_validate(
        _safe_load_unique(plan_path.read_text(encoding="utf-8"))
    )
    surface = document.identity_request.execution_surface_digests

    assert _LOCK_PATH in surface, (
        "the static production admission must bind the parser dependency lockfile"
    )
    assert surface[_LOCK_PATH] == _sha256((repo_root / _LOCK_PATH).read_bytes())


def test_d1_5_parser_fingerprint_has_exact_domain_separated_preimage(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)

    fingerprint = _fingerprint(artifact_contract, context, installed="0.11.7")

    assert fingerprint == _expected_fingerprint(context, installed="0.11.7")


def test_d1_5_parser_fingerprint_changes_with_algorithm_lock_or_locked_version(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    original = _fingerprint(artifact_contract, context, installed="0.11.7")

    context.algorithm_path.write_bytes(
        b'PARSER_ALGORITHM_VERSION = "insurancekb.pdf.v2"\n'
    )
    _refresh_surface_digest(context, _ALGORITHM_PATH, context.algorithm_path)
    algorithm_changed = _fingerprint(
        artifact_contract, context, installed="0.11.7"
    )

    context.lock_path.write_bytes(_lock_bytes("0.11.7", prefix="# lock revision\n"))
    _refresh_surface_digest(context, _LOCK_PATH, context.lock_path)
    lock_changed = _fingerprint(artifact_contract, context, installed="0.11.7")

    context.lock_path.write_bytes(_lock_bytes("0.11.8"))
    _refresh_surface_digest(context, _LOCK_PATH, context.lock_path)
    version_changed = _fingerprint(artifact_contract, context, installed="0.11.8")

    assert len({original, algorithm_changed, lock_changed, version_changed}) == 4


def test_d1_5_parser_rejects_installed_version_drift(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)

    with pytest.raises(AdmissionPausedError) as error:
        _fingerprint(artifact_contract, context, installed="0.11.8")

    assert error.value.code == "baseline_parser_identity_mismatch"


@pytest.mark.parametrize("failure", ("missing", "duplicate", "malformed"))
def test_d1_5_parser_rejects_missing_duplicate_or_malformed_direct_dependency(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    failure: str,
) -> None:
    context = _context(tmp_path)
    if failure == "missing":
        lock_bytes = b'version = 1\n\n[[package]]\nname = "other"\nversion = "1"\n'
    elif failure == "duplicate":
        lock_bytes = _lock_bytes("0.11.7") + _lock_bytes("0.11.7")
    else:
        lock_bytes = (
            b'version = 1\n\n[[package]]\nname = "pdfplumber"\nversion = 117\n'
        )
    context.lock_path.write_bytes(lock_bytes)
    _refresh_surface_digest(context, _LOCK_PATH, context.lock_path)

    with pytest.raises(AdmissionPausedError) as error:
        _fingerprint(artifact_contract, context, installed="0.11.7")

    assert error.value.code == "baseline_parser_lock_invalid"


@pytest.mark.parametrize("surface", ("algorithm", "lock"))
def test_d1_5_parser_revalidates_signed_execution_surface_bytes(
    artifact_contract: ExecutionArtifacts020,
    tmp_path: Path,
    surface: str,
) -> None:
    context = _context(tmp_path)
    path = context.algorithm_path if surface == "algorithm" else context.lock_path
    path.write_bytes(path.read_bytes() + b"# unsigned drift\n")

    with pytest.raises(AdmissionPausedError) as error:
        _fingerprint(artifact_contract, context, installed="0.11.7")

    assert error.value.code == "baseline_parser_identity_mismatch"
