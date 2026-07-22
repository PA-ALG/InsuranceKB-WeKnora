"""OpenSpec 031 O3: offline signing authority and protected key paths."""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import insurance_harness.goldenset.admission_authority as authority
from insurance_harness.goldenset import admission_cli
from insurance_harness.goldenset.admission_authority import (
    AuthorityPathError,
    generate_offline_key,
    render_unsigned_approval,
    sign_rendered_approval,
)
from insurance_harness.goldenset.admission_models import (
    ApprovalVerificationError,
    BudgetApprovalEntry,
    BudgetApprovalEnvelope,
    BudgetApprovalPayload,
    TrustedKeyPolicy,
    approval_signed_bytes,
    verify_approval_envelope,
)

_NOW = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)


def _payload(**overrides: object) -> BudgetApprovalPayload:
    values: dict[str, object] = {
        "plan_payload_hash": "a" * 64,
        "run_identity": "run-031",
        "purpose": "baseline",
        "scope": "budget:run-031",
        "approver_identity": "finance@example.com",
        "approver_role": "budget_approver",
        "issued_at": _NOW - timedelta(minutes=1),
        "expires_at": _NOW + timedelta(minutes=5),
        "budget_entries": (
            BudgetApprovalEntry(
                currency="CNY",
                max_input_tokens=100,
                max_output_tokens=10,
                max_cost_minor_units=500,
                budget_contract_hash="b" * 64,
            ),
        ),
    }
    values.update(overrides)
    return BudgetApprovalPayload.model_validate(values)


def _envelope(
    private_key: Ed25519PrivateKey,
    payload: BudgetApprovalPayload,
    *,
    key_id: str = "finance-key",
) -> BudgetApprovalEnvelope:
    signature = private_key.sign(approval_signed_bytes("budget", payload))
    return BudgetApprovalEnvelope(
        domain="budget",
        key_id=key_id,
        payload=payload,
        signature=base64.b64encode(signature).decode("ascii"),
    )


def _verify(
    envelope: BudgetApprovalEnvelope,
    policy: TrustedKeyPolicy,
) -> None:
    verify_approval_envelope(
        envelope,
        expected_domain="budget",
        expected_plan_payload_hash="a" * 64,
        expected_run_identity="run-031",
        expected_purpose="baseline",
        expected_scope=envelope.payload.scope,
        trusted_public_keys={policy.key_id: policy},
        allowed_roles=frozenset({"budget_approver", "provenance_approver"}),
        now=_NOW,
    )


def test_o3_trusted_key_policy_binds_identity_domain_scope_and_role() -> None:
    private_key = Ed25519PrivateKey.generate()
    policy = TrustedKeyPolicy(
        key_id="finance-key",
        public_key=private_key.public_key(),
        approver_identity="finance@example.com",
        domains=frozenset({"budget"}),
        scopes=frozenset({"budget:run-031"}),
        roles=frozenset({"budget_approver"}),
    )
    _verify(_envelope(private_key, _payload()), policy)

    mutations = (
        _payload(approver_identity="attacker@example.com"),
        _payload(scope="budget:other"),
        _payload(approver_role="provenance_approver"),
    )
    for payload in mutations:
        with pytest.raises(ApprovalVerificationError, match="policy"):
            _verify(_envelope(private_key, payload), policy)

    wrong_domain_policy = TrustedKeyPolicy(
        key_id="finance-key",
        public_key=private_key.public_key(),
        approver_identity="finance@example.com",
        domains=frozenset({"provenance"}),
        scopes=frozenset({"budget:run-031"}),
        roles=frozenset({"budget_approver"}),
    )
    with pytest.raises(ApprovalVerificationError, match="policy"):
        _verify(_envelope(private_key, _payload()), wrong_domain_policy)


def test_o3_keygen_is_exclusive_external_and_never_self_enrolls_or_leaks(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    external = tmp_path / "operator"
    external.mkdir(mode=0o700)
    private_path = external / "authority.key"
    trust_store = external / "trust.yaml"
    trust_store.write_text("sentinel\n", encoding="utf-8")

    descriptor = generate_offline_key(private_path=private_path, repo_root=repo)

    assert descriptor.key_id.startswith("ed25519:")
    assert private_path.stat().st_mode & 0o777 == 0o600
    assert trust_store.read_text(encoding="utf-8") == "sentinel\n"
    captured = capsys.readouterr()
    private_bytes = private_path.read_bytes()
    assert captured.out == captured.err == ""
    assert private_bytes not in captured.out.encode()
    assert private_bytes not in captured.err.encode()

    with pytest.raises(FileExistsError):
        generate_offline_key(private_path=private_path, repo_root=repo)
    with pytest.raises(AuthorityPathError, match="repository"):
        generate_offline_key(
            private_path=repo / "ignored" / "authority.key",
            repo_root=repo,
        )


def test_o3_sign_rejects_symlinks_hardlinks_mode_size_and_repo_staging(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    external = tmp_path / "operator"
    external.mkdir(mode=0o700)
    key = external / "authority.key"
    descriptor = generate_offline_key(private_path=key, repo_root=repo)
    rendered = external / "approval.rendered.json"
    render_unsigned_approval(
        domain="budget",
        key_id=descriptor.key_id,
        payload=_payload(),
        output_path=rendered,
        repo_root=repo,
    )

    key.chmod(0o640)
    with pytest.raises(AuthorityPathError, match="0600"):
        sign_rendered_approval(
            rendered_path=rendered,
            private_key_path=key,
            output_path=repo / "approval.json",
            repo_root=repo,
        )
    key.chmod(0o600)

    hardlink = external / "authority-hardlink.key"
    os.link(key, hardlink)
    with pytest.raises(AuthorityPathError, match="link"):
        sign_rendered_approval(
            rendered_path=rendered,
            private_key_path=key,
            output_path=repo / "approval.json",
            repo_root=repo,
        )
    hardlink.unlink()

    oversized = external / "oversized.key"
    oversized.write_bytes(b"x" * 8192)
    oversized.chmod(0o600)
    with pytest.raises(AuthorityPathError, match="size"):
        sign_rendered_approval(
            rendered_path=rendered,
            private_key_path=oversized,
            output_path=repo / "approval.json",
            repo_root=repo,
        )

    symlink = external / "symlink.key"
    symlink.symlink_to(key)
    with pytest.raises(AuthorityPathError):
        sign_rendered_approval(
            rendered_path=rendered,
            private_key_path=symlink,
            output_path=repo / "approval.json",
            repo_root=repo,
        )

    symlink_parent = tmp_path / "operator-link"
    symlink_parent.symlink_to(external, target_is_directory=True)
    with pytest.raises(AuthorityPathError):
        sign_rendered_approval(
            rendered_path=symlink_parent / rendered.name,
            private_key_path=key,
            output_path=repo / "approval.json",
            repo_root=repo,
        )

    with pytest.raises(AuthorityPathError, match="repository"):
        render_unsigned_approval(
            domain="budget",
            key_id=descriptor.key_id,
            payload=_payload(),
            output_path=repo / "approval.rendered.json",
            repo_root=repo,
        )


def test_o3_render_sign_are_separate_and_final_envelope_is_atomic_public_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    external = tmp_path / "operator"
    external.mkdir(mode=0o700)
    key = external / "authority.key"
    descriptor = generate_offline_key(private_path=key, repo_root=repo)
    rendered = external / "approval.rendered.json"
    final = repo / "approval.json"

    render_unsigned_approval(
        domain="budget",
        key_id=descriptor.key_id,
        payload=_payload(),
        output_path=rendered,
        repo_root=repo,
    )
    assert "signature" not in json.loads(rendered.read_text(encoding="utf-8"))
    envelope = sign_rendered_approval(
        rendered_path=rendered,
        private_key_path=key,
        output_path=final,
        repo_root=repo,
    )
    assert final.exists()
    assert envelope.signature
    assert not tuple(repo.glob(".*.tmp"))
    assert capsys.readouterr().out == ""
    with pytest.raises(FileExistsError):
        sign_rendered_approval(
            rendered_path=rendered,
            private_key_path=key,
            output_path=final,
            repo_root=repo,
        )


def test_o3_cli_has_separate_offline_commands_and_no_run_trust_override() -> None:
    parser = admission_cli._build_parser()
    for command in ("keygen", "render", "sign", "verify"):
        with pytest.raises(ValueError, match="required"):
            parser.parse_args([command])
    with pytest.raises(ValueError):
        parser.parse_args(
            [
                "check",
                "--plan",
                "plan.yaml",
                "--repo-root",
                "/repo",
                "--result-json",
                "/out/result.json",
                "--report-md",
                "/out/report.md",
                "--trust-store",
                "/attacker/trust.yaml",
            ]
        )


def test_o3_production_trust_parser_requires_per_key_policy() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(private_key.public_key().public_bytes_raw()).decode("ascii")
    policies, budget_roles, provenance_roles, canary_roles = (
        admission_cli._parse_trusted_approval_configuration(
            yaml.safe_dump(
                {
                    "key_policies": {
                        "finance-key": {
                            "approver_identity": "finance@example.com",
                            "domains": ["budget"],
                            "scopes": ["budget:run-031"],
                            "roles": ["budget_approver"],
                            "public_key": public_key,
                        }
                    },
                    "budget_roles": ["budget_approver"],
                    "provenance_roles": ["provenance_approver"],
                    "canary_review_roles": ["canary_review_approver"],
                },
                sort_keys=True,
            ),
            require_key_policies=True,
        )
    )
    policy = policies["finance-key"]
    assert isinstance(policy, TrustedKeyPolicy)
    assert policy.approver_identity == "finance@example.com"
    assert policy.domains == frozenset({"budget"})
    assert policy.scopes == frozenset({"budget:run-031"})
    assert policy.roles == frozenset({"budget_approver"})
    assert budget_roles == frozenset({"budget_approver"})
    assert provenance_roles == frozenset({"provenance_approver"})
    assert canary_roles == frozenset({"canary_review_approver"})

    legacy = yaml.safe_dump(
        {
            "public_keys": {"finance-key": public_key},
            "budget_roles": ["budget_approver"],
            "provenance_roles": ["provenance_approver"],
        }
    )
    with pytest.raises(ValueError, match="policy"):
        admission_cli._parse_trusted_approval_configuration(
            legacy,
            require_key_policies=True,
        )


def test_o3_replace_race_is_detected_before_signing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    external = tmp_path / "operator"
    external.mkdir(mode=0o700)
    key = external / "authority.key"
    descriptor = generate_offline_key(private_path=key, repo_root=repo)
    rendered = external / "approval.rendered.json"
    render_unsigned_approval(
        domain="budget",
        key_id=descriptor.key_id,
        payload=_payload(),
        output_path=rendered,
        repo_root=repo,
    )
    original_read = os.read
    replaced = False

    def replace_path(descriptor: int, maximum: int) -> bytes:
        nonlocal replaced
        chunk = original_read(descriptor, maximum)
        if not replaced:
            replaced = True
            old = external / "approval.old.json"
            rendered.rename(old)
            rendered.write_bytes(old.read_bytes())
            rendered.chmod(0o600)
        return chunk

    monkeypatch.setattr(os, "read", replace_path)
    with pytest.raises(AuthorityPathError, match="changed"):
        sign_rendered_approval(
            rendered_path=rendered,
            private_key_path=key,
            output_path=repo / "approval.json",
            repo_root=repo,
        )
    assert not (repo / "approval.json").exists()


def test_o3_bounded_public_reader_uses_one_stable_descriptor_and_caps_growth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(b"old")
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(b"new")
    original_read = os.read
    swapped = False

    def replace_after_open(descriptor: int, maximum: int) -> bytes:
        nonlocal swapped
        if not swapped:
            swapped = True
            replacement.replace(source)
        return original_read(descriptor, maximum)

    monkeypatch.setattr(os, "read", replace_after_open)
    assert authority.read_bounded_public_file(source, maximum=3) == b"old"

    monkeypatch.setattr(os, "read", original_read)
    growing = tmp_path / "growing.json"
    growing.write_bytes(b"abc")
    grew = False

    def grow_after_open(descriptor: int, maximum: int) -> bytes:
        nonlocal grew
        if not grew:
            grew = True
            with growing.open("ab") as stream:
                stream.write(b"de")
        return original_read(descriptor, maximum)

    monkeypatch.setattr(os, "read", grow_after_open)
    with pytest.raises(ValueError, match="size"):
        authority.read_bounded_public_file(growing, maximum=4)

    monkeypatch.setattr(os, "read", original_read)
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"x" * 6)
    with pytest.raises(ValueError, match="size"):
        authority.read_bounded_public_file(oversized, maximum=5)


def test_o3_keygen_cli_rolls_back_only_new_key_when_public_install_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    external = tmp_path / "operator"
    external.mkdir(mode=0o700)
    key = external / "authority.key"
    metadata = repo / "authority-public.json"
    metadata.write_text("preexisting", encoding="utf-8")
    arguments = [
        "keygen",
        "--repo-root",
        str(repo),
        "--private-key",
        str(key),
        "--public-metadata",
        str(metadata),
    ]

    assert admission_cli.main(arguments) == 1
    assert not key.exists()
    assert metadata.read_text(encoding="utf-8") == "preexisting"

    metadata.unlink()

    def fail_install(**_kwargs: object) -> None:
        raise OSError("injected public install failure")

    monkeypatch.setattr(admission_cli, "write_public_key_descriptor", fail_install)
    assert admission_cli.main(arguments) == 1
    assert not key.exists()
    assert not metadata.exists()


@pytest.mark.parametrize("failure", ["unlink", "fsync"])
def test_o3_atomic_public_output_rolls_back_destination_after_post_link_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    output = tmp_path / "public.json"
    if failure == "unlink":
        original_unlink = os.unlink
        failed = False

        def fail_temporary_unlink(
            path: str,
            *,
            dir_fd: int | None = None,
        ) -> None:
            nonlocal failed
            if not failed and str(path).startswith("."):
                failed = True
                raise OSError("injected unlink failure")
            original_unlink(path, dir_fd=dir_fd)

        monkeypatch.setattr(os, "unlink", fail_temporary_unlink)
    else:
        original_fsync = os.fsync
        calls = 0

        def fail_parent_fsync(descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected fsync failure")
            original_fsync(descriptor)

        monkeypatch.setattr(os, "fsync", fail_parent_fsync)

    with pytest.raises(AuthorityPathError):
        authority._atomic_public_output(output, b"public\n")
    assert not output.exists()


def test_o3_atomic_public_output_reports_ambiguous_when_rollback_cannot_remove_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "public.json"
    original_fsync = os.fsync
    fsync_calls = 0

    def fail_parent_fsync(descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 2:
            raise OSError("injected post-link fsync failure")
        original_fsync(descriptor)

    original_unlink = os.unlink

    def fail_destination_rollback(
        path: str,
        *,
        dir_fd: int | None = None,
    ) -> None:
        if path == output.name:
            raise OSError("injected rollback unlink failure")
        original_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "fsync", fail_parent_fsync)
    monkeypatch.setattr(os, "unlink", fail_destination_rollback)

    with pytest.raises(AuthorityPathError, match="ambiguous"):
        authority._atomic_public_output(output, b"public\n")
    assert output.read_bytes() == b"public\n"


def test_o3_offline_verify_never_borrows_roles_from_another_domain(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    external = tmp_path / "operator"
    external.mkdir(mode=0o700)
    key = external / "authority.key"
    descriptor = generate_offline_key(private_path=key, repo_root=repo)
    rendered = external / "approval.rendered.json"
    envelope = repo / "approval.json"
    current = datetime.now(UTC)
    render_unsigned_approval(
        domain="budget",
        key_id=descriptor.key_id,
        payload=_payload(
            issued_at=current - timedelta(minutes=1),
            expires_at=current + timedelta(minutes=5),
        ),
        output_path=rendered,
        repo_root=repo,
    )
    sign_rendered_approval(
        rendered_path=rendered,
        private_key_path=key,
        output_path=envelope,
        repo_root=repo,
    )
    trust = external / "trust.yaml"
    trust.write_text(
        yaml.safe_dump(
            {
                "key_policies": {
                    descriptor.key_id: {
                        "approver_identity": "finance@example.com",
                        "domains": ["budget"],
                        "scopes": ["budget:run-031"],
                        "roles": ["budget_approver"],
                        "public_key": descriptor.public_key,
                    }
                },
                "budget_roles": [],
                "provenance_roles": ["budget_approver"],
            }
        ),
        encoding="utf-8",
    )
    trust.chmod(0o600)

    assert (
        admission_cli.main(
            [
                "verify",
                "--envelope",
                str(envelope),
                "--trust-store",
                str(trust),
            ]
        )
        == 1
    )


def test_o3_keygen_render_sign_verify_cli_round_trip_is_offline_and_separate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    external = tmp_path / "operator"
    external.mkdir(mode=0o700)
    key = external / "authority.key"
    metadata = repo / "authority-public.json"
    payload_path = repo / "payload.json"
    current = datetime.now(UTC)
    payload_path.write_bytes(
        json.dumps(
            _payload(
                issued_at=current - timedelta(minutes=1),
                expires_at=current + timedelta(minutes=5),
            ).model_dump(mode="json"),
            sort_keys=True,
        ).encode()
    )
    rendered = external / "approval.rendered.json"
    envelope = repo / "approval.json"

    assert (
        admission_cli.main(
            [
                "keygen",
                "--repo-root",
                str(repo),
                "--private-key",
                str(key),
                "--public-metadata",
                str(metadata),
            ]
        )
        == 0
    )
    public = json.loads(metadata.read_text(encoding="utf-8"))
    trust = external / "trust.yaml"
    trust.write_text(
        yaml.safe_dump(
            {
                "key_policies": {
                    public["key_id"]: {
                        "approver_identity": "finance@example.com",
                        "domains": ["budget"],
                        "scopes": ["budget:run-031"],
                        "roles": ["budget_approver"],
                        "public_key": public["public_key"],
                    }
                },
                "budget_roles": ["budget_approver"],
                "provenance_roles": [],
            }
        ),
        encoding="utf-8",
    )
    trust.chmod(0o600)
    assert (
        admission_cli.main(
            [
                "render",
                "--repo-root",
                str(repo),
                "--domain",
                "budget",
                "--key-id",
                public["key_id"],
                "--payload",
                str(payload_path),
                "--output",
                str(rendered),
            ]
        )
        == 0
    )
    assert not envelope.exists()
    assert (
        admission_cli.main(
            [
                "sign",
                "--repo-root",
                str(repo),
                "--rendered",
                str(rendered),
                "--private-key",
                str(key),
                "--output",
                str(envelope),
            ]
        )
        == 0
    )
    assert (
        admission_cli.main(
            [
                "verify",
                "--envelope",
                str(envelope),
                "--trust-store",
                str(trust),
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == ""
