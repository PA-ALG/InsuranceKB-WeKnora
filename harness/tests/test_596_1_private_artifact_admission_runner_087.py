from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.knowledge_compiler.private_artifact_admission_runner_596_1 import (
    PrivateArtifactPaths,
    RunnerDependencies,
    main,
    run_private_artifact_admission,
)

_ROLES = ("terms", "brochure", "rate_table")
_HASHES = {
    "terms": "1" * 64,
    "brochure": "2" * 64,
    "rate_table": "3" * 64,
}
_OUTERS = {
    "terms": "4" * 64,
    "brochure": "5" * 64,
    "rate_table": "6" * 64,
}
_PARSERS = {role: "7" * 64 for role in _ROLES}
_ATTEMPTS = {role: "8" * 64 for role in _ROLES}


@dataclass(frozen=True)
class _ValidatedIntake:
    role: str
    contract_id: str
    outer_sha256: str
    artifact_sha256: str
    parser_identity_sha256: str
    attempt_identity_sha256: str


@dataclass(frozen=True)
class _ValidatedRelation:
    status: str = "VALIDATED"
    receipt_sha256: str = "9" * 64
    artifact_outer_sha256_by_role: dict[str, str] = field(default_factory=lambda: dict(_OUTERS))
    artifact_sha256_by_role: dict[str, str] = field(default_factory=lambda: dict(_HASHES))
    parser_identity_sha256_by_role: dict[str, str] = field(default_factory=lambda: dict(_PARSERS))
    attempt_identity_sha256_by_role: dict[str, str] = field(default_factory=lambda: dict(_ATTEMPTS))
    bindings: tuple[object, ...] = (object(),)


@dataclass(frozen=True)
class _AssemblerResult:
    status: str
    provider_calls: int = 0
    golden_reads: int = 0
    receipt_digest_sha256: str | None = None
    partial_receipts: tuple[str, ...] = ()


class _IntakeValidator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes]] = []
        self.role_override: dict[str, str] = {}

    def __call__(self, artifact_bytes: bytes, *, expected_role: str) -> _ValidatedIntake:
        self.calls.append((expected_role, artifact_bytes))
        return _ValidatedIntake(
            role=self.role_override.get(expected_role, expected_role),
            contract_id="mineru-private-custody-v1",
            outer_sha256=_OUTERS[expected_role],
            artifact_sha256=_HASHES[expected_role],
            parser_identity_sha256=_PARSERS[expected_role],
            attempt_identity_sha256=_ATTEMPTS[expected_role],
        )


class _RelationValidator:
    def __init__(self, result: _ValidatedRelation | None = None) -> None:
        self.calls: list[bytes] = []
        self.result = result or _ValidatedRelation()

    def __call__(self, receipt_bytes: bytes) -> _ValidatedRelation:
        self.calls.append(receipt_bytes)
        return self.result


class _Assembler:
    def __init__(self, result: _AssemblerResult) -> None:
        self.calls: list[tuple[tuple[object, ...], tuple[object, ...]]] = []
        self.result = result

    def __call__(
        self,
        *,
        validated_intakes: tuple[object, ...],
        relation_bindings: tuple[object, ...],
    ) -> _AssemblerResult:
        self.calls.append((validated_intakes, relation_bindings))
        return self.result


def _private_file(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    path.chmod(0o600)
    return path


def _paths(tmp_path: Path) -> PrivateArtifactPaths:
    return PrivateArtifactPaths(
        terms=_private_file(tmp_path / "terms.custody", b"synthetic-terms"),
        brochure=_private_file(tmp_path / "brochure.custody", b"synthetic-brochure"),
        rate_table=_private_file(tmp_path / "rate.custody", b"synthetic-rate"),
        relation_receipt=_private_file(tmp_path / "relation.receipt", b"synthetic-relation"),
    )


def _dependencies(
    *,
    assembler_result: _AssemblerResult | None = None,
    relation_result: _ValidatedRelation | None = None,
) -> tuple[RunnerDependencies, _IntakeValidator, _RelationValidator, _Assembler]:
    intake = _IntakeValidator()
    relation = _RelationValidator(relation_result)
    assembler = _Assembler(
        assembler_result
        or _AssemblerResult(
            status="READY",
            receipt_digest_sha256="a" * 64,
        )
    )
    return (
        RunnerDependencies(
            intake_validator=intake,
            relation_validator=relation,
            admission_assembler=assembler,
        ),
        intake,
        relation,
        assembler,
    )


def test_exact_private_inputs_compose_once_without_claiming_real_ready(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    dependencies, intake, relation, assembler = _dependencies()

    result = run_private_artifact_admission(paths, dependencies)

    assert result.status == "COMPOSITION_SEAM_VERIFIED"
    assert [item.role for item in result.artifacts] == list(_ROLES)
    assert [item.artifact_sha256 for item in result.artifacts] == [_HASHES[role] for role in _ROLES]
    assert result.common_receipt_digest_sha256 == "a" * 64
    assert result.provider_calls == result.golden_reads == 0
    assert intake.calls == [
        ("terms", b"synthetic-terms"),
        ("brochure", b"synthetic-brochure"),
        ("rate_table", b"synthetic-rate"),
    ]
    assert relation.calls == [b"synthetic-relation"]
    assert len(assembler.calls) == 1


def test_cross_page_block_is_stable_and_discards_partial_receipts(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    dependencies, _, _, assembler = _dependencies(
        assembler_result=_AssemblerResult(
            status="BLOCKED_ON_CROSS_PAGE_BINDING",
            receipt_digest_sha256="b" * 64,
            partial_receipts=("brochure-should-not-escape",),
        )
    )

    result = run_private_artifact_admission(paths, dependencies)

    assert result.status == "BLOCKED_ON_CROSS_PAGE_BINDING"
    assert result.artifacts == ()
    assert result.common_receipt_digest_sha256 is None
    assert len(assembler.calls) == 1


@pytest.mark.parametrize("bad_mode", [0o400, 0o644])
def test_input_mode_failure_precedes_every_dependency_call(tmp_path: Path, bad_mode: int) -> None:
    paths = _paths(tmp_path)
    paths.brochure.chmod(bad_mode)
    dependencies, intake, relation, assembler = _dependencies()

    result = run_private_artifact_admission(paths, dependencies)

    assert result.status == "INPUT_CONTRACT_BLOCKED"
    assert result.artifacts == ()
    assert intake.calls == []
    assert relation.calls == []
    assert assembler.calls == []


def test_duplicate_file_identity_and_symlink_are_rejected_before_validation(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    duplicate_paths = PrivateArtifactPaths(
        terms=paths.terms,
        brochure=paths.terms,
        rate_table=paths.rate_table,
        relation_receipt=paths.relation_receipt,
    )
    dependencies, intake, relation, assembler = _dependencies()

    duplicate = run_private_artifact_admission(duplicate_paths, dependencies)

    assert duplicate.status == "INPUT_CONTRACT_BLOCKED"
    assert intake.calls == []
    assert relation.calls == []
    assert assembler.calls == []

    link = tmp_path / "brochure-link"
    link.symlink_to(paths.brochure)
    symlink_paths = PrivateArtifactPaths(
        terms=paths.terms,
        brochure=link,
        rate_table=paths.rate_table,
        relation_receipt=paths.relation_receipt,
    )
    symlinked = run_private_artifact_admission(symlink_paths, dependencies)
    assert symlinked.status == "INPUT_CONTRACT_BLOCKED"
    assert intake.calls == []
    assert relation.calls == []
    assert assembler.calls == []


def test_missing_and_swapped_role_inputs_fail_before_admission(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    dependencies, intake, relation, assembler = _dependencies()
    missing_paths = PrivateArtifactPaths(
        terms=tmp_path / "missing",
        brochure=paths.brochure,
        rate_table=paths.rate_table,
        relation_receipt=paths.relation_receipt,
    )
    missing = run_private_artifact_admission(missing_paths, dependencies)
    assert missing.status == "INPUT_CONTRACT_BLOCKED"
    assert intake.calls == []
    assert relation.calls == []
    assert assembler.calls == []

    actual_role_by_payload = {
        b"synthetic-terms": "terms",
        b"synthetic-brochure": "brochure",
        b"synthetic-rate": "rate_table",
    }

    def _role_aware(payload: bytes, *, expected_role: str) -> _ValidatedIntake:
        actual_role = actual_role_by_payload[payload]
        return _ValidatedIntake(
            role=actual_role,
            contract_id="mineru-private-custody-v1",
            outer_sha256=_OUTERS[actual_role],
            artifact_sha256=_HASHES[actual_role],
            parser_identity_sha256=_PARSERS[actual_role],
            attempt_identity_sha256=_ATTEMPTS[actual_role],
        )

    object.__setattr__(dependencies, "intake_validator", _role_aware)
    swapped_paths = PrivateArtifactPaths(
        terms=paths.brochure,
        brochure=paths.terms,
        rate_table=paths.rate_table,
        relation_receipt=paths.relation_receipt,
    )
    swapped = run_private_artifact_admission(swapped_paths, dependencies)
    assert swapped.status == "INTAKE_VALIDATION_BLOCKED"
    assert relation.calls == []
    assert assembler.calls == []


@pytest.mark.parametrize(
    ("relation_result", "expected_status"),
    [
        (
            _ValidatedRelation(artifact_outer_sha256_by_role={**_OUTERS, "terms": "f" * 64}),
            "RELATION_VALIDATION_BLOCKED",
        ),
        (
            _ValidatedRelation(artifact_sha256_by_role={**_HASHES, "terms": "f" * 64}),
            "RELATION_VALIDATION_BLOCKED",
        ),
        (
            _ValidatedRelation(parser_identity_sha256_by_role={**_PARSERS, "brochure": "f" * 64}),
            "RELATION_VALIDATION_BLOCKED",
        ),
        (
            _ValidatedRelation(
                attempt_identity_sha256_by_role={**_ATTEMPTS, "rate_table": "f" * 64}
            ),
            "RELATION_VALIDATION_BLOCKED",
        ),
    ],
)
def test_relation_drift_blocks_before_assembler(
    tmp_path: Path,
    relation_result: _ValidatedRelation,
    expected_status: str,
) -> None:
    paths = _paths(tmp_path)
    dependencies, _, relation, assembler = _dependencies(relation_result=relation_result)

    result = run_private_artifact_admission(paths, dependencies)

    assert result.status == expected_status
    assert len(relation.calls) == 1
    assert assembler.calls == []
    assert result.artifacts == ()


def test_wrong_role_is_rejected_without_relation_or_assembler(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    dependencies, intake, relation, assembler = _dependencies()
    intake.role_override["brochure"] = "terms"

    result = run_private_artifact_admission(paths, dependencies)

    assert result.status == "INTAKE_VALIDATION_BLOCKED"
    assert [role for role, _ in intake.calls] == ["terms", "brochure"]
    assert relation.calls == []
    assert assembler.calls == []


def test_sensitive_dependency_error_is_not_reflected_in_result_or_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _paths(tmp_path)
    dependencies, intake, _, _ = _dependencies()
    secret = "api_key=must-not-survive"
    body = "raw-body-must-not-survive"
    url = "https://signed.example/private?token=bad"

    def _raise_sensitive(_payload: bytes, *, expected_role: str) -> Any:
        raise ValueError(f"{expected_role} {secret} {body} {url} {paths.terms}")

    object.__setattr__(dependencies, "intake_validator", _raise_sensitive)
    result = run_private_artifact_admission(paths, dependencies)
    encoded = json.dumps(result.to_wire(), sort_keys=True)
    assert result.status == "INTAKE_VALIDATION_BLOCKED"
    for forbidden in (secret, body, url, str(paths.terms)):
        assert forbidden not in encoded

    exit_code = main(
        [
            "--terms-artifact",
            os.fspath(paths.terms),
            "--brochure-artifact",
            os.fspath(paths.brochure),
            "--rate-artifact",
            os.fspath(paths.rate_table),
            "--relation-receipt",
            os.fspath(paths.relation_receipt),
        ],
        dependencies=dependencies,
    )
    output = capsys.readouterr().out
    assert exit_code == 2
    assert len(output.splitlines()) == 1
    assert json.loads(output)["status"] == "INTAKE_VALIDATION_BLOCKED"
    for forbidden in (secret, body, url, str(paths.terms)):
        assert forbidden not in output
    assert intake.calls == []


def test_external_effect_counter_and_assembler_failure_are_fail_closed(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    dependencies, _, _, assembler = _dependencies(
        assembler_result=_AssemblerResult(
            status="READY",
            provider_calls=1,
            receipt_digest_sha256="a" * 64,
        )
    )

    nonzero = run_private_artifact_admission(paths, dependencies)

    assert nonzero.status == "EXTERNAL_EFFECT_CONTRACT_VIOLATION"
    assert nonzero.artifacts == ()
    assert len(assembler.calls) == 1

    class _FailingAssembler:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, **_kwargs: object) -> _AssemblerResult:
            self.calls += 1
            raise RuntimeError("must-not-retry-or-reflect")

    failing = _FailingAssembler()
    object.__setattr__(dependencies, "admission_assembler", failing)
    blocked = run_private_artifact_admission(paths, dependencies)
    assert blocked.status == "ADMISSION_BLOCKED"
    assert blocked.artifacts == ()
    assert failing.calls == 1


def test_cli_without_composed_dependencies_fails_before_opening_inputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "not-opened"

    exit_code = main(
        [
            "--terms-artifact",
            os.fspath(missing),
            "--brochure-artifact",
            os.fspath(missing),
            "--rate-artifact",
            os.fspath(missing),
            "--relation-receipt",
            os.fspath(missing),
        ]
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out) == {
        "artifacts": [],
        "common_receipt_digest_sha256": None,
        "golden_reads": 0,
        "provider_calls": 0,
        "status": "DEPENDENCY_UNAVAILABLE",
    }
