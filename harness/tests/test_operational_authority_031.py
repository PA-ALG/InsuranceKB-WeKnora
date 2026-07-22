"""OpenSpec 031 O3: offline signing authority and protected key paths."""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

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
from insurance_harness.goldenset.admission_infrastructure import (
    ADOPTION_AUTHORIZATION_DOMAIN,
    CLEANUP_AUTHORIZATION_DOMAIN,
    PRICING_EVIDENCE_DOMAIN,
    PROVIDER_CAP_DOMAIN,
    PROVISIONING_AUTHORIZATION_DOMAIN,
    AuthorizationDomain,
    AuthorizationVerificationError,
    DeploymentCleanupAuthorization,
    DeploymentCleanupAuthorizationPayload,
    ExistingDeploymentAdoptionAuthorization,
    ExistingDeploymentAdoptionAuthorizationPayload,
    PricingEvidenceApprovalPayload,
    PricingEvidenceContent,
    ProviderCapApprovalPayload,
    ProviderCapEvidenceContent,
    ProvisioningAuthorization,
    ProvisioningAuthorizationPayload,
    authorization_signed_bytes,
    cleanup_authorization_signed_bytes,
    pricing_evidence_digest,
    provider_cap_evidence_digest,
    verify_adoption_authorization,
    verify_cleanup_authorization,
    verify_provisioning_authorization,
)
from insurance_harness.goldenset.admission_models import (
    ApprovalVerificationError,
    BudgetApprovalEntry,
    BudgetApprovalEnvelope,
    BudgetApprovalPayload,
    TrustedKeyPolicy,
    approval_signed_bytes,
    canonical_json_bytes,
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


def test_o3_independent_operational_domains_cli_render_sign_verify_round_trip(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    external = tmp_path / "operator"
    external.mkdir(mode=0o700)
    key = external / "authority.key"
    metadata = repo / "authority-public.json"
    assert admission_cli.main(
        [
            "keygen",
            "--repo-root",
            str(repo),
            "--private-key",
            str(key),
            "--public-metadata",
            str(metadata),
        ]
    ) == 0
    public = json.loads(metadata.read_text(encoding="utf-8"))
    now = datetime.now(UTC)
    pricing_evidence = PricingEvidenceContent(
        version="insurancekb.run-admission.pricing-evidence.v1",
        issuer="bailian-price-catalog",
        provider="bailian",
        workspace_ref="workspace-cn-beijing-031",
        project_ref="sha256:" + "a" * 64,
        credential_ref="sha256:" + "b" * 64,
        region="cn-beijing",
        base_model="qwen3.7-plus-2026-05-26",
        request_plan="ptu_v2",
        receipt_plan="ptu",
        input_tpm_quota=10_000,
        output_tpm_quota=1_000,
        currency="CNY",
        effective_from=now - timedelta(days=1),
        effective_until=now + timedelta(days=1),
        billing_quantum_seconds=3600,
        round_up_rule="ceiling",
        fixed_cost_per_quantum_minor_units=672,
        input_cost_per_million_minor_units=240,
        output_cost_per_million_minor_units=960,
        tiers_policy="worst_case_included",
        thinking_policy="worst_case_included",
        cache_policy="worst_case_included",
        overflow_policy="block",
    )
    cap_evidence = ProviderCapEvidenceContent(
        version="insurancekb.run-admission.provider-cap-evidence.v1",
        issuer="bailian-control-plane",
        provider="bailian",
        workspace_ref=pricing_evidence.workspace_ref,
        project_ref=pricing_evidence.project_ref,
        credential_ref=pricing_evidence.credential_ref,
        currency="CNY",
        max_cost_minor_units=20_000,
        coverage=("fixed_infrastructure", "inference"),
        observed_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    pricing_digest = pricing_evidence_digest(canonical_json_bytes(pricing_evidence))
    cap_digest = provider_cap_evidence_digest(canonical_json_bytes(cap_evidence))
    common: dict[str, object] = {
        "provider": "bailian",
        "run_identity": "run-031",
        "purpose": "baseline",
        "scope": "goldenset-production",
        "operation_id": "op-strong-031",
        "infrastructure_reserve_id": "infra-strong-031",
        "workspace_ref": pricing_evidence.workspace_ref,
        "project_ref": pricing_evidence.project_ref,
        "credential_ref": pricing_evidence.credential_ref,
        "region": "cn-beijing",
        "base_model": pricing_evidence.base_model,
        "request_plan": "ptu_v2",
        "receipt_plan": "ptu",
        "input_tpm_quota": 10_000,
        "output_tpm_quota": 1_000,
        "pricing_evidence_digest": pricing_digest,
        "provider_cap_evidence_digest": cap_digest,
        "pricing_approval_digest": "e" * 64,
        "provider_cap_approval_digest": "f" * 64,
        "currency": "CNY",
        "provider_cap_max_cost_minor_units": 20_000,
        "provider_cap_coverage": ("fixed_infrastructure", "inference"),
        "provider_cap_expires_at": cap_evidence.expires_at,
        "cleanup_deadline": now + timedelta(hours=8),
        "approver_identity": "operator@example.test",
        "issued_at": now - timedelta(minutes=1),
        "expires_at": now + timedelta(minutes=30),
    }
    provisioning = ProvisioningAuthorizationPayload.model_validate(
        {
            **common,
            "transition": "create",
            "maximum_cost_minor_units": 5_376,
            "approver_role": "deployment-provisioner",
        }
    )
    adoption = ExistingDeploymentAdoptionAuthorizationPayload.model_validate(
        {
            **common,
            "transition": "adopt_existing",
            "maximum_cost_minor_units": 6_048,
            "approver_role": "budget-approver",
            "deployed_model": "qwen3.7-plus-2026-05-26-031strng",
            "receipt_digest": "1" * 64,
            "gmt_create": now - timedelta(hours=1),
            "preexisting": True,
            "limitation": "not_preauthorized_by_031",
            "incurred_cost_minor_units": 672,
            "future_max_cost_minor_units": 5_376,
        }
    )
    payloads = {
        PROVISIONING_AUTHORIZATION_DOMAIN: provisioning,
        ADOPTION_AUTHORIZATION_DOMAIN: adoption,
        PRICING_EVIDENCE_DOMAIN: PricingEvidenceApprovalPayload(
            evidence_digest=pricing_digest,
            evidence=pricing_evidence,
            scope="goldenset-production",
            approver_identity="operator@example.test",
            approver_role="pricing-evidence-approver",
            issued_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=30),
        ),
        PROVIDER_CAP_DOMAIN: ProviderCapApprovalPayload(
            evidence_digest=cap_digest,
            evidence=cap_evidence,
            scope="goldenset-production",
            approver_identity="operator@example.test",
            approver_role="provider-cap-attestor",
            issued_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=30),
        ),
        CLEANUP_AUTHORIZATION_DOMAIN: DeploymentCleanupAuthorizationPayload(
            run_identity="run-031",
            purpose="baseline",
            scope="goldenset-production",
            operation_id="op-strong-031",
            reserve_id="infra-strong-031",
            receipt_digest="1" * 64,
            deployed_model="qwen3.7-plus-2026-05-26-031strng",
            workspace_ref=pricing_evidence.workspace_ref,
            project_ref=pricing_evidence.project_ref,
            credential_ref=pricing_evidence.credential_ref,
            expected_remote_manifest_digest="2" * 64,
            cleanup_reason="approved test cleanup",
            cleanup_deadline=now + timedelta(hours=8),
            approver_identity="operator@example.test",
            approver_role="deployment-cleanup-operator",
            issued_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=30),
        ),
    }
    trust = external / "trust.yaml"
    policy: dict[str, object] = {
        "approver_identity": "operator@example.test",
        "domains": list(payloads),
        "scopes": ["goldenset-production"],
        "roles": [
            "deployment-provisioner",
            "budget-approver",
            "pricing-evidence-approver",
            "provider-cap-attestor",
            "deployment-cleanup-operator",
        ],
        "public_key": public["public_key"],
    }
    trust_configuration: dict[str, object] = {
        "key_policies": {public["key_id"]: policy},
        "budget_roles": [],
        "provenance_roles": [],
    }
    trust.write_text(yaml.safe_dump(trust_configuration), encoding="utf-8")
    trust.chmod(0o600)

    for index, (domain, payload) in enumerate(payloads.items()):
        payload_path = repo / f"payload-{index}.json"
        payload_path.write_text(
            json.dumps(payload.model_dump(mode="json"), sort_keys=True),
            encoding="utf-8",
        )
        rendered = external / f"approval-{index}.rendered.json"
        envelope = repo / f"approval-{index}.json"
        assert admission_cli.main(
            [
                "render",
                "--repo-root",
                str(repo),
                "--domain",
                domain,
                "--key-id",
                public["key_id"],
                "--payload",
                str(payload_path),
                "--output",
                str(rendered),
            ]
        ) == 0
        assert admission_cli.main(
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
        ) == 0
        assert admission_cli.main(
            [
                "verify",
                "--envelope",
                str(envelope),
                "--trust-store",
                str(trust),
            ]
        ) == 0

    provisioning_envelope = json.loads(
        (repo / "approval-0.json").read_text(encoding="utf-8")
    )
    adoption_envelope = json.loads(
        (repo / "approval-1.json").read_text(encoding="utf-8")
    )
    provisioning_envelope["signature"] = adoption_envelope["signature"]
    cross_domain_replay = repo / "approval-cross-domain-replay.json"
    cross_domain_replay.write_text(
        json.dumps(provisioning_envelope, sort_keys=True), encoding="utf-8"
    )
    assert admission_cli.main(
        [
            "verify",
            "--envelope",
            str(cross_domain_replay),
            "--trust-store",
            str(trust),
        ]
    ) == 1

    for field, invalid_value in (
        ("approver_identity", "another-operator@example.test"),
        ("domains", [ADOPTION_AUTHORIZATION_DOMAIN]),
        ("scopes", ["another-scope"]),
        ("roles", ["budget-approver"]),
    ):
        original_value = policy[field]
        policy[field] = invalid_value
        trust.write_text(yaml.safe_dump(trust_configuration), encoding="utf-8")
        assert admission_cli.main(
            [
                "verify",
                "--envelope",
                str(repo / "approval-0.json"),
                "--trust-store",
                str(trust),
            ]
        ) == 1
        policy[field] = original_value


def test_o3_cleanup_verifier_rejects_subclass_before_caller_method_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    payload = DeploymentCleanupAuthorizationPayload(
        run_identity="run-031",
        purpose="baseline",
        scope="goldenset-production",
        operation_id="op-strong-031",
        reserve_id="infra-strong-031",
        receipt_digest="1" * 64,
        deployed_model="qwen3.7-plus-2026-05-26-031strng",
        workspace_ref="workspace-cn-beijing-031",
        project_ref="sha256:" + "a" * 64,
        credential_ref="sha256:" + "b" * 64,
        expected_remote_manifest_digest="2" * 64,
        cleanup_reason="approved test cleanup",
        cleanup_deadline=_NOW + timedelta(hours=1),
        approver_identity="operator@example.test",
        approver_role="deployment-cleanup-operator",
        issued_at=_NOW - timedelta(minutes=1),
        expires_at=_NOW + timedelta(minutes=30),
    )
    signature = base64.b64encode(
        private_key.sign(cleanup_authorization_signed_bytes(payload))
    ).decode("ascii")
    safe = DeploymentCleanupAuthorization(
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        key_id="cleanup-key",
        payload=payload,
        signature=signature,
    )
    malicious_payload = payload.model_copy(update={"scope": "attacker-scope"})

    class MaliciousCleanupAuthorization(DeploymentCleanupAuthorization):
        pass

    malicious = MaliciousCleanupAuthorization.model_construct(
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        key_id=safe.key_id,
        payload=malicious_payload,
        signature=safe.signature,
    )
    model_dump_called = False

    def return_signed_safe_snapshot(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal model_dump_called
        model_dump_called = True
        return safe.model_dump(mode="python", round_trip=True)

    monkeypatch.setattr(
        MaliciousCleanupAuthorization,
        "model_dump",
        return_signed_safe_snapshot,
    )
    policy = TrustedKeyPolicy(
        key_id="cleanup-key",
        public_key=private_key.public_key(),
        approver_identity="operator@example.test",
        domains=frozenset({CLEANUP_AUTHORIZATION_DOMAIN}),
        scopes=frozenset({"goldenset-production"}),
        roles=frozenset({"deployment-cleanup-operator"}),
    )

    with pytest.raises(AuthorizationVerificationError, match="type"):
        verify_cleanup_authorization(
            malicious,
            trusted_authorities={policy.key_id: policy},
            now=_NOW,
        )
    assert model_dump_called is False


def test_o3_offline_cleanup_verify_rejects_exact_cleanup_deadline(
    tmp_path: Path,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    payload = DeploymentCleanupAuthorizationPayload(
        run_identity="run-031",
        purpose="baseline",
        scope="goldenset-production",
        operation_id="op-strong-031",
        reserve_id="infra-strong-031",
        receipt_digest="1" * 64,
        deployed_model="qwen3.7-plus-2026-05-26-031strng",
        workspace_ref="workspace-cn-beijing-031",
        project_ref="sha256:" + "a" * 64,
        credential_ref="sha256:" + "b" * 64,
        expected_remote_manifest_digest="2" * 64,
        cleanup_reason="approved test cleanup",
        cleanup_deadline=_NOW,
        approver_identity="operator@example.test",
        approver_role="deployment-cleanup-operator",
        issued_at=_NOW - timedelta(hours=1),
        expires_at=_NOW + timedelta(hours=1),
    )
    envelope = DeploymentCleanupAuthorization(
        domain=CLEANUP_AUTHORIZATION_DOMAIN,
        key_id="cleanup-key",
        payload=payload,
        signature=base64.b64encode(
            private_key.sign(cleanup_authorization_signed_bytes(payload))
        ).decode("ascii"),
    )
    envelope_path = tmp_path / "cleanup.json"
    envelope_path.write_bytes(canonical_json_bytes(envelope))
    policy = TrustedKeyPolicy(
        key_id="cleanup-key",
        public_key=private_key.public_key(),
        approver_identity="operator@example.test",
        domains=frozenset({CLEANUP_AUTHORIZATION_DOMAIN}),
        scopes=frozenset({"goldenset-production"}),
        roles=frozenset({"deployment-cleanup-operator"}),
    )

    with pytest.raises(ApprovalVerificationError, match="cleanup deadline"):
        authority.verify_offline_envelope(
            envelope_path=envelope_path,
            trusted_public_keys={policy.key_id: policy},
            allowed_roles_by_domain={
                CLEANUP_AUTHORIZATION_DOMAIN: frozenset(
                    {"deployment-cleanup-operator"}
                )
            },
            now=_NOW,
        )


@pytest.mark.parametrize(
    ("domain", "boundary"),
    (
        (PROVISIONING_AUTHORIZATION_DOMAIN, "cleanup"),
        (PROVISIONING_AUTHORIZATION_DOMAIN, "provider_cap"),
        (ADOPTION_AUTHORIZATION_DOMAIN, "cleanup"),
        (ADOPTION_AUTHORIZATION_DOMAIN, "provider_cap"),
    ),
)
def test_o3_offline_infrastructure_verify_rejects_exact_operational_deadlines(
    tmp_path: Path,
    domain: AuthorizationDomain,
    boundary: Literal["cleanup", "provider_cap"],
) -> None:
    private_key = Ed25519PrivateKey.generate()
    common: dict[str, object] = {
        "provider": "bailian",
        "run_identity": "run-031",
        "purpose": "baseline",
        "scope": "goldenset-production",
        "operation_id": "op-strong-031",
        "infrastructure_reserve_id": "infra-strong-031",
        "workspace_ref": "workspace-cn-beijing-031",
        "project_ref": "sha256:" + "a" * 64,
        "credential_ref": "sha256:" + "b" * 64,
        "region": "cn-beijing",
        "base_model": "qwen3.7-plus-2026-05-26",
        "request_plan": "ptu_v2",
        "receipt_plan": "ptu",
        "input_tpm_quota": 10_000,
        "output_tpm_quota": 1_000,
        "pricing_evidence_digest": "c" * 64,
        "provider_cap_evidence_digest": "d" * 64,
        "pricing_approval_digest": "e" * 64,
        "provider_cap_approval_digest": "f" * 64,
        "currency": "CNY",
        "provider_cap_max_cost_minor_units": 20_000,
        "provider_cap_coverage": ("fixed_infrastructure", "inference"),
        "provider_cap_expires_at": (
            _NOW if boundary == "provider_cap" else _NOW + timedelta(hours=2)
        ),
        "maximum_cost_minor_units": 5_376,
        "cleanup_deadline": (
            _NOW if boundary == "cleanup" else _NOW + timedelta(hours=2)
        ),
        "approver_identity": "operator@example.test",
        "issued_at": _NOW - timedelta(hours=1),
        "expires_at": _NOW + timedelta(hours=1),
    }
    envelope: ProvisioningAuthorization | ExistingDeploymentAdoptionAuthorization
    if domain == PROVISIONING_AUTHORIZATION_DOMAIN:
        payload = ProvisioningAuthorizationPayload.model_validate(
            {
                **common,
                "transition": "create",
                "approver_role": "deployment-provisioner",
            }
        )
        envelope = ProvisioningAuthorization(
            domain=domain,
            key_id="infrastructure-key",
            payload=payload,
            signature=base64.b64encode(
                private_key.sign(authorization_signed_bytes(domain, payload))
            ).decode("ascii"),
        )
        role = "deployment-provisioner"
    else:
        adoption_payload = ExistingDeploymentAdoptionAuthorizationPayload.model_validate(
            {
                **common,
                "transition": "adopt_existing",
                "maximum_cost_minor_units": 6_048,
                "approver_role": "budget-approver",
                "deployed_model": "qwen3.7-plus-2026-05-26-031strng",
                "receipt_digest": "1" * 64,
                "gmt_create": _NOW - timedelta(hours=2),
                "preexisting": True,
                "limitation": "not_preauthorized_by_031",
                "incurred_cost_minor_units": 672,
                "future_max_cost_minor_units": 5_376,
            }
        )
        envelope = ExistingDeploymentAdoptionAuthorization(
            domain=domain,
            key_id="infrastructure-key",
            payload=adoption_payload,
            signature=base64.b64encode(
                private_key.sign(authorization_signed_bytes(domain, adoption_payload))
            ).decode("ascii"),
        )
        role = "budget-approver"
    envelope_path = tmp_path / f"{domain}-{boundary}.json"
    envelope_path.write_bytes(canonical_json_bytes(envelope))
    policy = TrustedKeyPolicy(
        key_id="infrastructure-key",
        public_key=private_key.public_key(),
        approver_identity="operator@example.test",
        domains=frozenset({domain}),
        scopes=frozenset({"goldenset-production"}),
        roles=frozenset({role}),
    )
    expected_message = (
        "cleanup deadline" if boundary == "cleanup" else "provider cap"
    )

    with pytest.raises(ApprovalVerificationError, match=expected_message):
        authority.verify_offline_envelope(
            envelope_path=envelope_path,
            trusted_public_keys={policy.key_id: policy},
            allowed_roles_by_domain={domain: frozenset({role})},
            now=_NOW,
        )


def test_o3_infrastructure_verifiers_reject_subclasses_and_hidden_constructed_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    common: dict[str, object] = {
        "provider": "bailian",
        "run_identity": "run-031",
        "purpose": "baseline",
        "scope": "goldenset-production",
        "operation_id": "op-strong-031",
        "infrastructure_reserve_id": "infra-strong-031",
        "workspace_ref": "workspace-cn-beijing-031",
        "project_ref": "sha256:" + "a" * 64,
        "credential_ref": "sha256:" + "b" * 64,
        "region": "cn-beijing",
        "base_model": "qwen3.7-plus-2026-05-26",
        "request_plan": "ptu_v2",
        "receipt_plan": "ptu",
        "input_tpm_quota": 10_000,
        "output_tpm_quota": 1_000,
        "pricing_evidence_digest": "c" * 64,
        "provider_cap_evidence_digest": "d" * 64,
        "pricing_approval_digest": "e" * 64,
        "provider_cap_approval_digest": "f" * 64,
        "currency": "CNY",
        "provider_cap_max_cost_minor_units": 20_000,
        "provider_cap_coverage": ("fixed_infrastructure", "inference"),
        "provider_cap_expires_at": _NOW + timedelta(hours=1),
        "cleanup_deadline": _NOW + timedelta(hours=8),
        "approver_identity": "operator@example.test",
        "issued_at": _NOW - timedelta(minutes=1),
        "expires_at": _NOW + timedelta(minutes=30),
    }
    provisioning_payload = ProvisioningAuthorizationPayload.model_validate(
        {
            **common,
            "transition": "create",
            "maximum_cost_minor_units": 5_376,
            "approver_role": "deployment-provisioner",
        }
    )
    adoption_payload = ExistingDeploymentAdoptionAuthorizationPayload.model_validate(
        {
            **common,
            "transition": "adopt_existing",
            "maximum_cost_minor_units": 6_048,
            "approver_role": "budget-approver",
            "deployed_model": "qwen3.7-plus-2026-05-26-031strng",
            "receipt_digest": "1" * 64,
            "gmt_create": _NOW - timedelta(hours=1),
            "preexisting": True,
            "limitation": "not_preauthorized_by_031",
            "incurred_cost_minor_units": 672,
            "future_max_cost_minor_units": 5_376,
        }
    )
    provisioning = ProvisioningAuthorization(
        domain=PROVISIONING_AUTHORIZATION_DOMAIN,
        key_id="infrastructure-key",
        payload=provisioning_payload,
        signature=base64.b64encode(
            private_key.sign(
                authorization_signed_bytes(
                    PROVISIONING_AUTHORIZATION_DOMAIN,
                    provisioning_payload,
                )
            )
        ).decode("ascii"),
    )
    adoption = ExistingDeploymentAdoptionAuthorization(
        domain=ADOPTION_AUTHORIZATION_DOMAIN,
        key_id="infrastructure-key",
        payload=adoption_payload,
        signature=base64.b64encode(
            private_key.sign(
                authorization_signed_bytes(
                    ADOPTION_AUTHORIZATION_DOMAIN,
                    adoption_payload,
                )
            )
        ).decode("ascii"),
    )
    policy = TrustedKeyPolicy(
        key_id="infrastructure-key",
        public_key=private_key.public_key(),
        approver_identity="operator@example.test",
        domains=frozenset(
            {PROVISIONING_AUTHORIZATION_DOMAIN, ADOPTION_AUTHORIZATION_DOMAIN}
        ),
        scopes=frozenset({"goldenset-production"}),
        roles=frozenset({"deployment-provisioner", "budget-approver"}),
    )

    class MaliciousProvisioningAuthorization(ProvisioningAuthorization):
        pass

    class MaliciousAdoptionAuthorization(ExistingDeploymentAdoptionAuthorization):
        pass

    malicious_provisioning = MaliciousProvisioningAuthorization.model_construct(
        **provisioning.__dict__
    )
    malicious_adoption = MaliciousAdoptionAuthorization.model_construct(
        **adoption.__dict__
    )

    def caller_method_must_not_run(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("caller model_dump ran before exact-type rejection")

    monkeypatch.setattr(
        MaliciousProvisioningAuthorization,
        "model_dump",
        caller_method_must_not_run,
    )
    monkeypatch.setattr(
        MaliciousAdoptionAuthorization,
        "model_dump",
        caller_method_must_not_run,
    )
    with pytest.raises(AuthorizationVerificationError, match="type"):
        verify_provisioning_authorization(
            malicious_provisioning,
            expected=provisioning_payload,
            trusted_authorities={policy.key_id: policy},
            now=_NOW,
        )
    with pytest.raises(AuthorizationVerificationError, match="type"):
        verify_adoption_authorization(
            malicious_adoption,
            expected=adoption_payload,
            trusted_authorities={policy.key_id: policy},
            now=_NOW,
        )

    class MaliciousProvisioningPayload(ProvisioningAuthorizationPayload):
        pass

    class MaliciousAdoptionPayload(ExistingDeploymentAdoptionAuthorizationPayload):
        pass

    provisioning_with_subclass_payload = ProvisioningAuthorization.model_construct(
        domain=provisioning.domain,
        key_id=provisioning.key_id,
        payload=MaliciousProvisioningPayload.model_construct(
            **provisioning_payload.__dict__
        ),
        signature=provisioning.signature,
    )
    adoption_with_subclass_payload = ExistingDeploymentAdoptionAuthorization.model_construct(
        domain=adoption.domain,
        key_id=adoption.key_id,
        payload=MaliciousAdoptionPayload.model_construct(**adoption_payload.__dict__),
        signature=adoption.signature,
    )
    with pytest.raises(AuthorizationVerificationError, match="type"):
        verify_provisioning_authorization(
            provisioning_with_subclass_payload,
            expected=provisioning_payload,
            trusted_authorities={policy.key_id: policy},
            now=_NOW,
        )
    with pytest.raises(AuthorizationVerificationError, match="type"):
        verify_adoption_authorization(
            adoption_with_subclass_payload,
            expected=adoption_payload,
            trusted_authorities={policy.key_id: policy},
            now=_NOW,
        )

    verify_provisioning_authorization(
        provisioning.model_copy(),
        expected=provisioning_payload.model_copy(),
        trusted_authorities={policy.key_id: policy},
        now=_NOW,
    )
    verify_adoption_authorization(
        adoption.model_copy(),
        expected=adoption_payload.model_copy(),
        trusted_authorities={policy.key_id: policy},
        now=_NOW,
    )

    constructed_with_extra = ProvisioningAuthorization.model_construct(
        **provisioning.__dict__
    )
    object.__setattr__(constructed_with_extra, "unexpected", "smuggled state")
    with pytest.raises(AuthorizationVerificationError, match="snapshot"):
        verify_provisioning_authorization(
            constructed_with_extra,
            expected=provisioning_payload,
            trusted_authorities={policy.key_id: policy},
            now=_NOW,
        )

    payload_with_extra = ProvisioningAuthorizationPayload.model_construct(
        **provisioning_payload.__dict__
    )
    object.__setattr__(payload_with_extra, "unexpected", "smuggled state")
    envelope_with_payload_extra = ProvisioningAuthorization.model_construct(
        domain=provisioning.domain,
        key_id=provisioning.key_id,
        payload=payload_with_extra,
        signature=provisioning.signature,
    )
    with pytest.raises(AuthorizationVerificationError, match="snapshot"):
        verify_provisioning_authorization(
            envelope_with_payload_extra,
            expected=provisioning_payload,
            trusted_authorities={policy.key_id: policy},
            now=_NOW,
        )

    with pytest.raises(ValueError, match="extra"):
        ProvisioningAuthorization.model_validate(
            {**provisioning.model_dump(mode="python"), "unexpected": "rejected"}
        )
    with pytest.raises(ValueError, match="extra"):
        provisioning.model_copy(update={"unexpected": "rejected"})
