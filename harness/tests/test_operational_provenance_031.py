"""OpenSpec 031 O2: repository-derived legacy provenance."""

from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from insurance_harness.goldenset.admission import (
    ProductionAdmissionEvaluator,
    RunAdmissionDocument,
)
from insurance_harness.goldenset.admission_identity import (
    IdentityInspectionBlocker,
    IdentityInspectionRequest,
    IdentityInspectionResult,
    LegacyProvenanceEvidenceInspector,
    identity_contract_hash,
)
from insurance_harness.goldenset.admission_models import (
    GitObjectId,
    LegacyFrozenProvenance,
    ObservedAnnotationProvenance,
    PendingModelRolePlan,
    ProvenanceApprovalPayload,
    ProvenanceApprovalSelection,
    RunAdmissionPlan,
    RunAdmissionPlanPayload,
    approval_signed_bytes,
)
from insurance_harness.goldenset.admission_probe import ProbeRequest, ProbeResult

_NOW = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
_PRODUCT_IDS = tuple(f"product-{number:02d}" for number in range(1, 12))
_AGENT_TRAILER = "Allowed Agent <allowed-agent@example.invalid>"
_AGENT_ID = "repository-agent-031"


def _observed_values() -> dict[str, object]:
    return {
        "provenance_kind": "observed_annotation",
        "product_id": "product-01",
        "annotator_provider": "provider-a",
        "annotator_model_id": "model-1",
        "annotated_at_start": _NOW - timedelta(hours=2),
        "annotated_at_end": _NOW - timedelta(hours=1),
        "evidence_basis": "provider audit export 42",
    }


def _legacy_values() -> dict[str, object]:
    return {
        "provenance_kind": "legacy_frozen",
        "product_id": "product-01",
        "product_digest": "1" * 64,
        "wip_digest": "2" * 64,
        "frozen_commit": "3" * 40,
        "evidence_path": "evidence/product-01/golden.jsonl",
        "evidence_blob_id": "4" * 40,
        "evidence_digest": "5" * 64,
        "recorded_agent_id": "claude-fable-5",
        "evidence_frozen_at": _NOW,
        "limitation": "original_annotation_time_unavailable",
    }


@pytest.mark.parametrize("oid", ("a" * 40, "b" * 64))
def test_o2_git_object_id_accepts_sha1_or_sha256_syntax(oid: str) -> None:
    assert TypeAdapter(GitObjectId).validate_python(oid) == oid


@pytest.mark.parametrize(
    "oid",
    (
        "a" * 39,
        "a" * 41,
        "a" * 63,
        "a" * 65,
        "A" * 40,
        "g" * 40,
    ),
)
def test_o2_git_object_id_rejects_wrong_length_case_or_alphabet(oid: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(GitObjectId).validate_python(oid)


def test_o2_provenance_union_requires_an_explicit_known_discriminator() -> None:
    adapter: TypeAdapter[ProvenanceApprovalSelection] = TypeAdapter(
        ProvenanceApprovalSelection
    )

    observed = adapter.validate_python(_observed_values())
    legacy = adapter.validate_python(_legacy_values())

    assert isinstance(observed, ObservedAnnotationProvenance)
    assert isinstance(legacy, LegacyFrozenProvenance)
    for invalid_kind in (None, "historical", "legacy"):
        values = _legacy_values()
        if invalid_kind is None:
            values.pop("provenance_kind")
        else:
            values["provenance_kind"] = invalid_kind
        with pytest.raises(ValidationError):
            adapter.validate_python(values)


def test_o2_legacy_provenance_forbids_synthetic_annotation_fields() -> None:
    values = _legacy_values()
    values.update(
        {
            "annotator_provider": "caller-asserted",
            "annotator_model_id": "caller-asserted",
            "annotated_at_start": _NOW,
            "annotated_at_end": _NOW,
            "evidence_basis": "caller-asserted",
        }
    )

    with pytest.raises(ValidationError):
        LegacyFrozenProvenance.model_validate(values)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("product_digest", "1" * 40),
        ("wip_digest", "2" * 40),
        ("evidence_digest", "5" * 40),
        ("evidence_frozen_at", datetime(2026, 7, 21, 8, 0)),
        ("limitation", "annotation_time_inferred_from_freeze"),
    ),
)
def test_o2_legacy_provenance_requires_sha256_content_digests_and_fixed_limits(
    field_name: str, value: object
) -> None:
    values = _legacy_values()
    values[field_name] = value

    with pytest.raises(ValidationError):
        LegacyFrozenProvenance.model_validate(values)


def test_o2_provenance_approval_payload_preserves_every_union_field() -> None:
    legacy = LegacyFrozenProvenance.model_validate(_legacy_values())
    payload = ProvenanceApprovalPayload(
        plan_payload_hash="a" * 64,
        run_identity="run-031",
        purpose="golden-v01",
        scope="provenance:wip-gs-v0.1",
        approver_identity="golden-owner@example.com",
        approver_role="provenance_approver",
        issued_at=_NOW - timedelta(minutes=1),
        expires_at=_NOW + timedelta(hours=1),
        product_entries=(legacy,),
    )

    dumped = payload.model_dump(mode="json")["product_entries"]
    assert dumped == [legacy.model_dump(mode="json")]
    assert set(dumped[0]) == set(_legacy_values())


def _identity_request(
    provenance: tuple[ProvenanceApprovalSelection, ...],
) -> IdentityInspectionRequest:
    return IdentityInspectionRequest(
        required_dependency_revisions={},
        source_products_root="inputs/source",
        golden_products_root="evidence",
        products=(),
        shared_input_digests={},
        execution_surface_digests={},
        historical_product_ids=tuple(item.product_id for item in provenance),
        historical_provenance=provenance,
    )


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("product_id", "product-02"),
        ("product_digest", "6" * 64),
        ("wip_digest", "7" * 64),
        ("frozen_commit", "8" * 40),
        ("evidence_path", "evidence/product-01/other.jsonl"),
        ("evidence_blob_id", "9" * 40),
        ("evidence_digest", "a" * 64),
        ("recorded_agent_id", "different-agent"),
        ("evidence_frozen_at", _NOW + timedelta(seconds=1)),
    ),
)
def test_o2_identity_and_approval_bind_every_legacy_field(
    field_name: str, replacement: object
) -> None:
    legacy = LegacyFrozenProvenance.model_validate(_legacy_values())
    changed = legacy.model_copy(update={field_name: replacement})
    original_request = _identity_request((legacy,))
    changed_request = _identity_request((changed,))
    original_payload = ProvenanceApprovalPayload(
        plan_payload_hash="a" * 64,
        run_identity="run-031",
        purpose="golden-v01",
        scope="provenance:wip-gs-v0.1",
        approver_identity="golden-owner@example.com",
        approver_role="provenance_approver",
        issued_at=_NOW - timedelta(minutes=1),
        expires_at=_NOW + timedelta(hours=1),
        product_entries=(legacy,),
    )
    changed_payload = original_payload.model_copy(update={"product_entries": (changed,)})

    assert identity_contract_hash(changed_request) != identity_contract_hash(
        original_request
    )
    assert approval_signed_bytes(
        "provenance", changed_payload
    ) != approval_signed_bytes("provenance", original_payload)


class _PassingIdentityInspector:
    def inspect(self, _request: IdentityInspectionRequest) -> IdentityInspectionResult:
        return IdentityInspectionResult(
            evaluated_revision="f" * 40,
            product_digests={},
            shared_input_digest="a" * 64,
            execution_surface_digest="b" * 64,
            blockers=(),
        )


class _NoNetworkProbe:
    def run(self, _request: ProbeRequest) -> ProbeResult:
        raise AssertionError("unsigned provenance check must not call provider network")


def _pending_role(model_id: str) -> PendingModelRolePlan:
    return PendingModelRolePlan(
        identity_status="pending_immutable_identity",
        provider="bailian",
        model_id=model_id,
        protocol="https",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider_policy="bailian-deployment-detail-v1",
        credential_env_name="HARNESS_DASHSCOPE_API_KEY",
    )


def test_o2_unsigned_legacy_candidate_remains_approval_missing() -> None:
    legacy = LegacyFrozenProvenance.model_validate(_legacy_values())
    identity_request = _identity_request((legacy,))
    document = RunAdmissionDocument(
        plan=RunAdmissionPlan(
            payload=RunAdmissionPlanPayload(
                run_identity="run-031",
                purpose="golden-v01",
                model_roles={
                    "annotator": _pending_role("annotator-pending"),
                    "weak_extractor": _pending_role("weak-pending"),
                    "judge": _pending_role("judge-pending"),
                },
                identity_contract_hash=identity_contract_hash(identity_request),
                budget_contract_hash=None,
            )
        ),
        identity_request=identity_request,
    )
    evaluator = ProductionAdmissionEvaluator._for_testing(
        identity_inspector=_PassingIdentityInspector(),
        provider_probe=_NoNetworkProbe(),
        trusted_public_keys={},
        probe=False,
        clock=lambda: _NOW,
        runtime_capability_ready=False,
    )

    result = evaluator(document)

    assert result.state == "BLOCKED"
    assert any(
        blocker.check == "provenance_approval"
        and blocker.code == "approval_missing"
        for blocker in result.blockers
    )


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout.strip()


def _make_evidence_repo(
    tmp_path: Path, *, object_format: str = "sha1"
) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", f"--object-format={object_format}")
    _git(repo, "config", "user.name", "Provenance Tests")
    _git(repo, "config", "user.email", "provenance-tests@example.invalid")
    for product_id in _PRODUCT_IDS:
        path = repo / "evidence" / product_id / "golden.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(f'{{"product_id":"{product_id}"}}\n', encoding="utf-8")
    _git(repo, "add", "-A")
    commit_env = dict(os.environ)
    commit_env.update(
        {
            "GIT_AUTHOR_DATE": "2026-07-12T01:17:42+08:00",
            "GIT_COMMITTER_DATE": "2026-07-12T01:17:42+08:00",
        }
    )
    _git(
        repo,
        "commit",
        "-m",
        "freeze legacy evidence\n\nCo-Authored-By: " + _AGENT_TRAILER,
        env=commit_env,
    )
    frozen_commit = _git(repo, "rev-parse", "HEAD")
    (repo / "README.md").write_text("descendant\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "descendant")
    return repo, frozen_commit, _git(repo, "rev-parse", "HEAD")


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _entry(repo: Path, frozen_commit: str, product_id: str) -> LegacyFrozenProvenance:
    evidence_path = f"evidence/{product_id}/golden.jsonl"
    content = (repo / evidence_path).read_bytes()
    return LegacyFrozenProvenance(
        provenance_kind="legacy_frozen",
        product_id=product_id,
        product_digest=_sha256_bytes(f"product:{product_id}".encode()),
        wip_digest=_sha256_bytes(content),
        frozen_commit=frozen_commit,
        evidence_path=evidence_path,
        evidence_blob_id=_git(repo, "rev-parse", f"{frozen_commit}:{evidence_path}"),
        evidence_digest=_sha256_bytes(content),
        recorded_agent_id=_AGENT_ID,
        evidence_frozen_at=datetime.fromisoformat(
            _git(repo, "show", "-s", "--format=%cI", frozen_commit)
        ),
        limitation="original_annotation_time_unavailable",
    )


def _entries(repo: Path, frozen_commit: str) -> tuple[LegacyFrozenProvenance, ...]:
    return tuple(_entry(repo, frozen_commit, product_id) for product_id in _PRODUCT_IDS)


def _product_digests() -> dict[str, str]:
    return {
        product_id: _sha256_bytes(f"product:{product_id}".encode())
        for product_id in _PRODUCT_IDS
    }


def _inspector(
    repo: Path, *, allow_agent: bool = True
) -> LegacyProvenanceEvidenceInspector:
    return LegacyProvenanceEvidenceInspector._for_testing(
        repo_root=repo,
        historical_product_ids=frozenset(_PRODUCT_IDS),
        golden_products_root="evidence",
        agent_trailer_allowlist={_AGENT_TRAILER: _AGENT_ID} if allow_agent else {},
    )


def _codes(blockers: tuple[IdentityInspectionBlocker, ...]) -> set[str]:
    return {blocker.code for blocker in blockers}


def _replace_entry(
    entries: tuple[LegacyFrozenProvenance, ...],
    index: int,
    **updates: object,
) -> tuple[LegacyFrozenProvenance, ...]:
    changed = entries[index].model_copy(update=updates)
    return (*entries[:index], changed, *entries[index + 1 :])


def test_o2_git_evidence_inspector_accepts_exact_repository_derived_evidence(
    tmp_path: Path,
) -> None:
    repo, frozen_commit, head = _make_evidence_repo(tmp_path)

    blockers = _inspector(repo).inspect(
        _entries(repo, frozen_commit),
        evaluated_revision=head,
        product_digests=_product_digests(),
    )

    assert blockers == ()


def test_o2_git_evidence_inspector_accepts_sha256_repository_oids(
    tmp_path: Path,
) -> None:
    repo, frozen_commit, head = _make_evidence_repo(
        tmp_path, object_format="sha256"
    )
    entries = _entries(repo, frozen_commit)

    blockers = _inspector(repo).inspect(
        entries,
        evaluated_revision=head,
        product_digests=_product_digests(),
    )

    assert len(frozen_commit) == 64
    assert all(len(entry.evidence_blob_id) == 64 for entry in entries)
    assert blockers == ()


@pytest.mark.parametrize(
    "hostile_variable",
    (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ),
)
def test_o2_git_evidence_inspector_ignores_ambient_repository_redirection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hostile_variable: str,
) -> None:
    trusted_parent = tmp_path / "trusted"
    hostile_parent = tmp_path / "hostile"
    trusted_parent.mkdir()
    hostile_parent.mkdir()
    repo, frozen_commit, head = _make_evidence_repo(trusted_parent)
    hostile_repo, _hostile_frozen, _hostile_head = _make_evidence_repo(
        hostile_parent
    )
    hostile_values = {
        "GIT_DIR": str(hostile_repo / ".git"),
        "GIT_WORK_TREE": str(hostile_repo),
        "GIT_OBJECT_DIRECTORY": str(hostile_repo / ".git" / "objects"),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(
            hostile_repo / ".git" / "objects"
        ),
    }
    monkeypatch.setenv(hostile_variable, hostile_values[hostile_variable])

    blockers = _inspector(repo).inspect(
        _entries(repo, frozen_commit),
        evaluated_revision=head,
        product_digests=_product_digests(),
    )

    assert blockers == ()


def test_o2_git_evidence_inspector_ignores_local_replace_refs(
    tmp_path: Path,
) -> None:
    repo, frozen_commit, head = _make_evidence_repo(tmp_path)
    entries = _entries(repo, frozen_commit)
    for product_id in _PRODUCT_IDS:
        (repo / "evidence" / product_id / "golden.jsonl").write_text(
            f'{{"product_id":"{product_id}","replacement":true}}\n',
            encoding="utf-8",
        )
    _git(repo, "add", "-A")
    replacement_tree = _git(repo, "write-tree")
    _git(repo, "reset", "--hard", head)
    replacement_env = dict(os.environ)
    replacement_env.update(
        {
            "GIT_AUTHOR_DATE": "2026-07-20T10:00:00+08:00",
            "GIT_COMMITTER_DATE": "2026-07-20T10:00:00+08:00",
        }
    )
    replacement_commit = subprocess.run(
        ("git", "commit-tree", replacement_tree),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        input="replacement evidence\n\nCo-Authored-By: Attacker <attacker@example.invalid>\n",
        env=replacement_env,
    ).stdout.strip()
    _git(repo, "replace", frozen_commit, replacement_commit)

    blockers = _inspector(repo).inspect(
        entries,
        evaluated_revision=head,
        product_digests=_product_digests(),
    )

    assert blockers == ()


@pytest.mark.parametrize("field_name", ("frozen_commit", "evidence_blob_id"))
def test_o2_git_evidence_inspector_enforces_repository_detected_oid_format(
    tmp_path: Path, field_name: str
) -> None:
    repo, frozen_commit, head = _make_evidence_repo(tmp_path)
    entries = _replace_entry(
        _entries(repo, frozen_commit), 0, **{field_name: "a" * 64}
    )

    blockers = _inspector(repo).inspect(
        entries, evaluated_revision=head, product_digests=_product_digests()
    )

    assert "git_object_format_mismatch" in _codes(blockers)


def test_o2_git_evidence_inspector_rejects_non_ancestor_commit(tmp_path: Path) -> None:
    repo, frozen_commit, head = _make_evidence_repo(tmp_path)
    tree = _git(repo, "show", "-s", "--format=%T", frozen_commit)
    unrelated = subprocess.run(
        ("git", "commit-tree", tree),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        input="unrelated freeze\n",
    ).stdout.strip()
    entries = tuple(
        entry.model_copy(
            update={
                "frozen_commit": unrelated,
                "evidence_frozen_at": datetime.fromisoformat(
                    _git(repo, "show", "-s", "--format=%cI", unrelated)
                ),
            }
        )
        for entry in _entries(repo, frozen_commit)
    )

    blockers = _inspector(repo).inspect(
        entries, evaluated_revision=head, product_digests=_product_digests()
    )

    assert "legacy_frozen_commit_not_ancestor" in _codes(blockers)


@pytest.mark.parametrize(
    ("updates", "expected_code"),
    (
        ({"evidence_path": "../escape.jsonl"}, "legacy_evidence_path_invalid"),
        ({"evidence_blob_id": "0" * 40}, "legacy_evidence_blob_mismatch"),
        ({"evidence_digest": "0" * 64}, "legacy_evidence_digest_mismatch"),
        ({"wip_digest": "0" * 64}, "legacy_wip_digest_mismatch"),
        ({"product_digest": "0" * 64}, "legacy_product_digest_mismatch"),
        ({"recorded_agent_id": "caller-self-report"}, "legacy_recorded_agent_mismatch"),
        (
            {"evidence_frozen_at": _NOW},
            "legacy_freeze_time_mismatch",
        ),
    ),
)
def test_o2_git_evidence_inspector_returns_typed_drift_blockers(
    tmp_path: Path, updates: dict[str, object], expected_code: str
) -> None:
    repo, frozen_commit, head = _make_evidence_repo(tmp_path)
    entries = _replace_entry(_entries(repo, frozen_commit), 0, **updates)

    blockers = _inspector(repo).inspect(
        entries, evaluated_revision=head, product_digests=_product_digests()
    )

    assert expected_code in _codes(blockers)


def test_o2_git_evidence_inspector_returns_typed_missing_blob_blocker(
    tmp_path: Path,
) -> None:
    repo, frozen_commit, _head = _make_evidence_repo(tmp_path)
    original_entries = _entries(repo, frozen_commit)
    empty_tree = _git(repo, "mktree")
    missing_commit = subprocess.run(
        ("git", "commit-tree", empty_tree, "-p", frozen_commit),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        input="missing evidence tree\n",
    ).stdout.strip()
    # Make the missing-tree commit an ancestor of the evaluated revision.
    _git(repo, "reset", "--hard", missing_commit)
    entry = original_entries[0].model_copy(
        update={
            "frozen_commit": missing_commit,
            "evidence_frozen_at": datetime.fromisoformat(
                _git(repo, "show", "-s", "--format=%cI", missing_commit)
            ),
        }
    )
    entries = (entry, *original_entries[1:])

    blockers = _inspector(repo).inspect(
        entries,
        evaluated_revision=missing_commit,
        product_digests=_product_digests(),
    )

    assert "legacy_evidence_missing" in _codes(blockers)
    assert "identity_configuration_error" not in _codes(blockers)


@pytest.mark.parametrize(
    "failure_mode",
    ("ls_tree_nonzero", "ls_tree_malformed", "ls_tree_decode", "cat_file_nonzero"),
)
def test_o2_git_evidence_inspector_distinguishes_tree_failures_from_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    repo, frozen_commit, head = _make_evidence_repo(tmp_path)
    inspector = _inspector(repo)
    entries = _entries(repo, frozen_commit)
    original = inspector._git_bytes

    def fail_tree_read(*args: str) -> subprocess.CompletedProcess[bytes]:
        if args[0] == "ls-tree":
            if failure_mode == "ls_tree_nonzero":
                return subprocess.CompletedProcess(args, 128, b"", b"failed")
            if failure_mode == "ls_tree_malformed":
                return subprocess.CompletedProcess(args, 0, b"malformed\0", b"")
            if failure_mode == "ls_tree_decode":
                header = (
                    f"100644 blob {entries[0].evidence_blob_id}\t".encode("ascii")
                )
                return subprocess.CompletedProcess(args, 0, header + b"\xff\0", b"")
        if args[0] == "cat-file" and failure_mode == "cat_file_nonzero":
            return subprocess.CompletedProcess(args, 128, b"", b"failed")
        return original(*args)

    monkeypatch.setattr(inspector, "_git_bytes", fail_tree_read)

    blockers = inspector.inspect(
        entries,
        evaluated_revision=head,
        product_digests=_product_digests(),
    )

    assert "identity_configuration_error" in _codes(blockers)
    assert "legacy_evidence_missing" not in _codes(blockers)


def test_o2_git_evidence_inspector_blocks_unproved_repository_agent(tmp_path: Path) -> None:
    repo, frozen_commit, head = _make_evidence_repo(tmp_path)

    blockers = _inspector(repo, allow_agent=False).inspect(
        _entries(repo, frozen_commit),
        evaluated_revision=head,
        product_digests=_product_digests(),
    )

    assert "legacy_recorded_agent_unproven" in _codes(blockers)


@pytest.mark.parametrize("mutation", ("missing", "duplicate"))
def test_o2_git_evidence_inspector_requires_exactly_eleven_unique_products(
    tmp_path: Path, mutation: str
) -> None:
    repo, frozen_commit, head = _make_evidence_repo(tmp_path)
    entries = _entries(repo, frozen_commit)
    if mutation == "missing":
        entries = entries[:-1]
        expected_code = "missing_historical_provenance"
    else:
        entries = (*entries, entries[0])
        expected_code = "duplicate_historical_provenance"

    blockers = _inspector(repo).inspect(
        entries, evaluated_revision=head, product_digests=_product_digests()
    )

    assert expected_code in _codes(blockers)


def test_o2_git_evidence_inspector_rejects_fixed_limitation_bypass(tmp_path: Path) -> None:
    repo, frozen_commit, head = _make_evidence_repo(tmp_path)
    entries = list(_entries(repo, frozen_commit))
    entries[0] = LegacyFrozenProvenance.model_construct(
        **{
            **entries[0].model_dump(mode="python"),
            "limitation": "caller-overrode-limitation",
        }
    )

    blockers = _inspector(repo).inspect(
        tuple(entries), evaluated_revision=head, product_digests=_product_digests()
    )

    assert "legacy_limitation_mismatch" in _codes(blockers)
