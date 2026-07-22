"""OpenSpec 030 MVP1: independent, zero-model run-admission contracts."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import pickle
import shutil
import subprocess
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.model_policy import (
    AdmissionPolicyDenied,
    ModelIdentity,
    ModelRole,
    StrictAdmissionRequestBinding,
    VerifiedAdmission,
)
from insurance_harness.run_admission.models import MvpAdmissionPlan

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_PURPOSE = "enterprise-wiki-mvp"
_SCHEMA = "enterprise-wiki-mvp.v1"
_SPACE = "space-mvp-030"
_DOMAIN = "insurancekb.run-admission.enterprise-wiki-mvp.v1"
_EXTREME_OFFSET_EXPIRY = "0001-01-01T00:00:00+14:00"
_ROLES: tuple[ModelRole, ...] = (
    "classify",
    "extract",
    "gap",
    "verify",
    "consensus",
)


def _sha(character: str) -> str:
    return character * 64


def _canonical_digest(domain: bytes, value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(domain + payload).hexdigest()


def _file_lock(path: Path, root: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _write_current_repository(root: Path) -> dict[str, object]:
    from insurance_harness.run_admission.models import (
        ContentArtifactLock,
        ContentSetLock,
    )

    data_root = root / "dataset/mvp_v0_1"
    data_root.mkdir(parents=True)
    entries: list[dict[str, object]] = []
    for index in range(23):
        is_meta = index < 5
        is_structured_source = index == 5
        relative = (
            Path(f"dataset/product-{index + 1}/product_meta.json")
            if is_meta
            else Path(f"dataset/input-{index + 1}.bin")
        )
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"controlled-current-content-{index}\n".encode()
        path.write_bytes(payload)
        entries.append(
            {
                "entry_id": (f"meta-{index + 1}" if is_meta else f"doc-{index + 1}"),
                "path": relative.as_posix(),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
                "structured": is_meta or is_structured_source,
                "input_kind": (
                    "product_meta" if is_meta else "json" if is_structured_source else "pdf"
                ),
                "dispatch_role": (
                    "registration-only"
                    if is_meta
                    else "registered-structured"
                    if is_structured_source
                    else "document-compile"
                ),
                "claim_evidence_eligible": not is_meta,
                "rights": {
                    "basis_ref": "controlled-rights",
                    "holder": "project-business-owner",
                    "status": "recorded",
                },
                "provenance": {
                    "kind": "controlled-test-fixture",
                    "source_identity": relative.as_posix(),
                    "source_revision": hashlib.sha256(payload).hexdigest(),
                },
            }
        )
    entries.sort(key=lambda item: str(item["entry_id"]))
    eligibility = [
        {
            "claim_evidence_eligible": entry["claim_evidence_eligible"],
            "dispatch_role": entry["dispatch_role"],
            "entry_id": entry["entry_id"],
            "structured": entry["structured"],
        }
        for entry in entries
    ]
    rights = [{"entry_id": entry["entry_id"], "rights": entry["rights"]} for entry in entries]
    provenance = [
        {"entry_id": entry["entry_id"], "provenance": entry["provenance"]} for entry in entries
    ]
    manifest_hash = hashlib.sha256(
        json.dumps(
            entries,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    eligibility_hash = hashlib.sha256(
        json.dumps(eligibility, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    rights_hash = hashlib.sha256(
        json.dumps(rights, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    provenance_hash = hashlib.sha256(
        json.dumps(provenance, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    routes_path = data_root / "expected_routes.yaml"
    routes_path.write_text(
        "schema_version: enterprise-wiki-mvp-routes-v1\n",
        encoding="utf-8",
    )
    golden_path = data_root / "golden_slice.yaml"
    golden_path.write_text(
        "schema_version: enterprise-wiki-mvp-golden-v1\n",
        encoding="utf-8",
    )
    routing_hash = hashlib.sha256(routes_path.read_bytes()).hexdigest()
    golden_hash = hashlib.sha256(golden_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "enterprise-wiki-mvp-manifest-v1",
        "run_revision": "mvp-v0.1-" + manifest_hash[:16],
        "entry_set_sha256": manifest_hash,
        "eligibility_sha256": eligibility_hash,
        "rights_sha256": rights_hash,
        "provenance_sha256": provenance_hash,
        "expected_routes_sha256": routing_hash,
        "golden_slice_sha256": golden_hash,
        "entries": entries,
    }
    import yaml

    (data_root / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    schema_path = root / "contracts/current-schema.json"
    schema_path.parent.mkdir(parents=True)
    schema_path.write_text('{"schema":"mvp-v1"}\n', encoding="utf-8")
    template_paths = (
        root / "templates/ordinary.yaml",
        root / "templates/participating.yaml",
    )
    for index, path in enumerate(template_paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"template: controlled-{index}\n", encoding="utf-8")
    schema_lock = ContentSetLock(artifacts=(ContentArtifactLock(**_file_lock(schema_path, root)),))
    template_lock = ContentSetLock(
        artifacts=tuple(ContentArtifactLock(**_file_lock(path, root)) for path in template_paths)
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Admission Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "controlled current content"], cwd=root, check=True)
    clean_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "run_revision": manifest["run_revision"],
        "manifest_hash": manifest_hash,
        "eligibility_hash": eligibility_hash,
        "golden_slice_hash": golden_hash,
        "routing_policy_identity": "enterprise-wiki-mvp-routes-v1",
        "routing_policy_hash": routing_hash,
        "schema_lock": schema_lock,
        "schema_hash": schema_lock.digest,
        "template_lock": template_lock,
        "template_lock_hash": template_lock.digest,
        "approved_template_hashes": tuple(artifact.sha256 for artifact in template_lock.artifacts),
        "rights_hash": rights_hash,
        "provenance_hash": provenance_hash,
        "clean_integration_sha": clean_sha,
        "registration_entries": tuple(
            _file_lock(root / str(entry["path"]), root)
            for entry in entries
            if entry["dispatch_role"] == "registration-only"
        ),
    }


def _identities() -> tuple[ModelIdentity, ...]:
    return tuple(
        ModelIdentity(
            provider="bailian",
            deployment_id=("qwen-vl3-2026-07-21" if role == "verify" else "qwen3-2026-07-21"),
            family="qwen-vl" if role == "verify" else "qwen",
            role=role,
            policy_version="mvp-policy-v1",
        )
        for role in _ROLES
    )


def _build_plan(**updates: object) -> MvpAdmissionPlan:
    from insurance_harness.run_admission.models import (
        ContentArtifactLock,
        ContentSetLock,
        RegistrationEntryLock,
        ResourceCaps,
        StructuredDispatchLock,
        canonical_model_identities_hash,
        canonical_model_plan_hash,
    )

    identities = tuple(
        cast(tuple[ModelIdentity, ...], updates.get("approved_identities", _identities()))
    )
    registration_entries = updates.pop("registration_entries", None)
    schema_lock = cast(
        ContentSetLock,
        updates.pop(
            "schema_lock",
            ContentSetLock(
                artifacts=(ContentArtifactLock(path="contracts/schema.json", sha256=_sha("e")),)
            ),
        ),
    )
    template_lock = cast(
        ContentSetLock,
        updates.pop(
            "template_lock",
            ContentSetLock(
                artifacts=(
                    ContentArtifactLock(path="templates/one.yaml", sha256=_sha("2")),
                    ContentArtifactLock(path="templates/two.yaml", sha256=_sha("3")),
                )
            ),
        ),
    )
    dispatch = StructuredDispatchLock(
        registration_entries=(
            tuple(
                RegistrationEntryLock.model_validate(entry)
                for entry in cast(tuple[object, ...], registration_entries)
            )
            if registration_entries is not None
            else tuple(
                RegistrationEntryLock(
                    path=f"dataset/product-{index}/product_meta.json",
                    sha256=_sha(str(index)),
                )
                for index in range(1, 6)
            )
        ),
        source_registry_identity="known-schema-registry-v1",
        source_authority_hash=_sha("6"),
        record_schema_refs=("product-meta/v1", "known-faq/v1"),
        adapter_version="known-schema-adapter-v1",
        canonicalizer_version="canonical-json-v1",
        source_profile_fingerprints=(_sha("7"), _sha("8")),
        mapping_manifest_hashes=(_sha("9"),),
        effective_mapping_versions=("product-meta-map-v1", "known-faq-map-v1"),
    )
    caps = ResourceCaps(
        worker_limit=4,
        attempt_limit=3,
        time_limit_seconds=3600,
        token_limit=200_000,
    )
    values: dict[str, object] = {
        "purpose": _PURPOSE,
        "run_schema_version": _SCHEMA,
        "run_id": "mvp-run-030",
        "run_revision": "mvp-v0.1-deadbeef",
        "space_id": _SPACE,
        "entry_count": 23,
        "manifest_hash": _sha("a"),
        "eligibility_hash": _sha("b"),
        "golden_slice_hash": _sha("c"),
        "routing_policy_identity": "mvp-routing-policy-v1",
        "routing_policy_hash": _sha("d"),
        "schema_lock": schema_lock,
        "schema_hash": schema_lock.digest,
        "template_lock": template_lock,
        "template_lock_hash": template_lock.digest,
        "structured_dispatch": dispatch,
        "structured_dispatch_hash": dispatch.digest,
        "model_plan_hash": canonical_model_plan_hash(identities),
        "approved_identities": identities,
        "deployment_roles_hash": canonical_model_identities_hash(identities),
        "approved_template_hashes": tuple(artifact.sha256 for artifact in template_lock.artifacts),
        "resource_caps": caps,
        "resource_caps_hash": caps.digest,
        "rights_hash": _sha("4"),
        "provenance_hash": _sha("5"),
        "clean_integration_sha": "a" * 40,
        "expires_at": datetime.now(UTC) + timedelta(hours=2),
    }
    values.update(updates)
    return MvpAdmissionPlan.model_validate(values)


def _write_policy(
    path: Path,
    private_key: Ed25519PrivateKey,
    *,
    human_identity: str = "human-release-owner@example.test",
) -> str:
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    fingerprint = hashlib.sha256(public_bytes).hexdigest()
    payload = {
        "schema_version": "insurancekb.run-admission-root-policy.v1",
        "approvers": [
            {
                "key_id": "mvp-human-key-1",
                "public_key_b64": base64.b64encode(public_bytes).decode("ascii"),
                "public_key_fingerprint": fingerprint,
                "human_identity": human_identity,
                "approver_role": "mvp-run-admission-approver",
                "signature_domain": _DOMAIN,
                "allowed_purposes": [_PURPOSE],
                "allowed_run_schema_versions": [_SCHEMA],
                "allowed_space_ids": [_SPACE],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)
    return fingerprint


def _write_envelope(
    path: Path,
    plan: MvpAdmissionPlan,
    private_key: Ed25519PrivateKey,
    fingerprint: str,
    *,
    sign: bool = True,
    human_identity: str = "human-release-owner@example.test",
) -> None:
    from insurance_harness.run_admission.models import (
        ApprovalEnvelope,
        approval_signed_bytes,
    )

    envelope = ApprovalEnvelope(
        schema_version="insurancekb.run-admission-approval-envelope.v1",
        signature_domain=_DOMAIN,
        key_id="mvp-human-key-1",
        public_key_fingerprint=fingerprint,
        human_identity=human_identity,
        approver_role="mvp-run-admission-approver",
        payload=plan,
        signature_b64=base64.b64encode(b"\0" * 64).decode("ascii"),
    )
    signer = private_key if sign else Ed25519PrivateKey.generate()
    signature = signer.sign(approval_signed_bytes(envelope))
    envelope = envelope.model_copy(
        update={"signature_b64": base64.b64encode(signature).decode("ascii")}
    )
    path.write_text(envelope.model_dump_json(), encoding="utf-8")


def _store_envelope(
    tmp_path: Path,
    store_root: Path,
    plan: MvpAdmissionPlan,
    private_key: Ed25519PrivateKey,
    fingerprint: str,
    *,
    sign: bool = True,
    human_identity: str = "human-release-owner@example.test",
) -> Path:
    staging = tmp_path / f"staged-{len(tuple(tmp_path.iterdir()))}.json"
    _write_envelope(
        staging,
        plan,
        private_key,
        fingerprint,
        sign=sign,
        human_identity=human_identity,
    )
    payload = staging.read_bytes()
    staging.unlink()
    return _store_payload(store_root, payload)


def _store_payload(store_root: Path, payload: bytes) -> Path:
    digest = hashlib.sha256(payload).hexdigest()
    target = store_root / "sha256" / digest / "approval-envelope.json"
    target.parent.mkdir(mode=0o700, exist_ok=True)
    target.parent.chmod(0o700)
    target.write_bytes(payload)
    target.chmod(0o600)
    return target


def _store_request(
    store_root: Path,
    request: StrictAdmissionRequestBinding,
) -> Path:
    import yaml

    payload = yaml.safe_dump(
        request.model_dump(mode="json"),
        allow_unicode=True,
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    target = store_root / "requests" / "sha256" / digest / "run-request.yaml"
    target.parent.mkdir(parents=True, mode=0o700)
    for directory in (
        store_root / "requests",
        store_root / "requests" / "sha256",
        target.parent,
    ):
        directory.chmod(0o700)
    target.write_bytes(payload)
    target.chmod(0o600)
    return target


def _store_request_payload(store_root: Path, payload: bytes) -> Path:
    digest = hashlib.sha256(payload).hexdigest()
    target = store_root / "requests" / "sha256" / digest / "run-request.yaml"
    target.parent.mkdir(parents=True, mode=0o700)
    for directory in (
        store_root / "requests",
        store_root / "requests" / "sha256",
        target.parent,
    ):
        directory.chmod(0o700)
    target.write_bytes(payload)
    target.chmod(0o600)
    return target


def _request_for(
    path: Path,
    plan: MvpAdmissionPlan,
) -> StrictAdmissionRequestBinding:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return StrictAdmissionRequestBinding(
        expected_purpose=plan.purpose,
        expected_run_schema_version=plan.run_schema_version,
        expected_run_id=plan.run_id,
        expected_run_revision=plan.run_revision,
        expected_space_id=plan.space_id,
        expected_admission_artifact_ref=str(path),
        expected_admission_artifact_digest=digest,
        expected_manifest_hash=plan.manifest_hash,
        expected_eligibility_hash=plan.eligibility_hash,
        expected_golden_slice_hash=plan.golden_slice_hash,
        expected_routing_policy_hash=plan.routing_policy_hash,
        expected_schema_hash=plan.schema_hash,
        expected_template_lock_hash=plan.template_lock_hash,
        expected_structured_dispatch_hash=plan.structured_dispatch_hash,
        expected_model_plan_hash=plan.model_plan_hash,
        expected_deployment_roles_hash=plan.deployment_roles_hash,
        expected_resource_caps_hash=plan.resource_caps_hash,
        expected_rights_hash=plan.rights_hash,
        expected_provenance_hash=plan.provenance_hash,
        expected_clean_integration_sha=plan.clean_integration_sha,
    )


def _signed_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    MvpAdmissionPlan,
    Path,
    Ed25519PrivateKey,
    str,
    StrictAdmissionRequestBinding,
]:
    from insurance_harness.run_admission import evaluator, trust_policy

    private_key = Ed25519PrivateKey.generate()
    trust_root = tmp_path / "trust-root"
    trust_root.mkdir(mode=0o700)
    policy_path = trust_root / "root-policy.json"
    fingerprint = _write_policy(policy_path, private_key)
    monkeypatch.setattr(trust_policy, "_ROOT_TRUST_POLICY_PATH", policy_path)
    monkeypatch.setattr(trust_policy, "_ROOT_TRUST_POLICY_DIR", trust_root)
    monkeypatch.setattr(trust_policy, "_ROOT_OWNER_UID", os.getuid())
    repository_root = tmp_path / "current-repository"
    repository_root.mkdir()
    current = _write_current_repository(repository_root)
    monkeypatch.setattr(evaluator, "_REPOSITORY_ROOT", repository_root)
    plan = _build_plan(**current)
    store_root = tmp_path / "admission-store"
    (store_root / "sha256").mkdir(parents=True, mode=0o700)
    store_root.chmod(0o700)
    monkeypatch.setattr(evaluator, "_ADMISSION_STORE_ROOT", store_root)
    artifact_path = _store_envelope(tmp_path, store_root, plan, private_key, fingerprint)
    return plan, artifact_path, private_key, fingerprint, _request_for(artifact_path, plan)


def test_mvp1_i0b_unknown_profile_is_rejected_by_code_owned_registry() -> None:
    from insurance_harness.run_admission.evaluator import (
        select_canonical_admission_verifier,
    )

    with pytest.raises(AdmissionPolicyDenied) as exc_info:
        select_canonical_admission_verifier("caller-profile", "caller-schema")

    assert exc_info.value.reason_code == "unknown_admission_profile"


def test_mvp1_i0b_installed_selector_preserves_unknown_profile_through_027_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.compiler import cli as compiler_cli
    from insurance_harness.model_policy import composition as composition_module

    transport_builds: list[object] = []
    monkeypatch.setattr(
        compiler_cli,
        "OpenAICompatClient",
        lambda **kwargs: transport_builds.append(kwargs),
    )

    with pytest.raises(AdmissionPolicyDenied) as exc_info:
        composition_module._select_canonical_admission_verifier(
            "caller-profile",
            "caller-schema",
        )

    assert exc_info.value.reason_code == "unknown_admission_profile"
    assert transport_builds == []


def test_mvp1_i0b_public_api_exports_only_stable_non_authority_dtos() -> None:
    import insurance_harness.run_admission as run_admission
    from insurance_harness.run_admission.models import ResourceCaps

    assert set(run_admission.__all__) == {
        "AdmissionDecision",
        "ApprovalEnvelope",
        "ContentArtifactLock",
        "ContentSetLock",
        "MvpAdmissionPlan",
        "RegistrationEntryLock",
        "ResourceCaps",
        "StructuredDispatchLock",
        "approval_signed_bytes",
        "evaluate_admission",
        "select_canonical_admission_verifier",
    }
    assert "VerifiedAdmission" not in run_admission.__all__

    caps = ResourceCaps(
        worker_limit=4,
        attempt_limit=3,
        time_limit_seconds=3600,
        token_limit=200_000,
    )
    for field_name in ResourceCaps.model_fields:
        invalid_values = (
            True,
            float(getattr(caps, field_name)),
            str(getattr(caps, field_name)),
            0,
            -1,
        )
        for invalid in invalid_values:
            values = caps.model_dump(mode="python")
            values[field_name] = invalid
            with pytest.raises(ValueError):
                ResourceCaps.model_validate(values)
    for invalid_entry_count in (True, 23.0, "23"):
        with pytest.raises(ValueError):
            _build_plan(entry_count=invalid_entry_count)
    with pytest.raises(ValueError):
        _build_plan(expires_at=_EXTREME_OFFSET_EXPIRY)


def test_mvp1_i0b_exact_trusted_envelope_issues_only_027_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission.evaluator import (
        evaluate_admission,
        select_canonical_admission_verifier,
    )

    plan, _path, _key, _fingerprint, request = _signed_request(tmp_path, monkeypatch)
    verifier = select_canonical_admission_verifier(_PURPOSE, _SCHEMA)
    verified = verifier.verify(request)

    assert type(verified) is VerifiedAdmission
    assert verified.request == request
    assert verified.binding.actual_purpose == _PURPOSE
    assert verified.binding.actual_run_schema_version == _SCHEMA
    assert verified.binding.actual_run_id == plan.run_id
    assert verified.binding.actual_state == "READY"
    assert verified.verified_binding_digest == verified.receipt.verified_binding_digest
    decision = evaluate_admission(request)
    assert decision.state == "READY"
    assert decision.reason_code == "verified"
    assert decision.verified_binding_digest == verified.verified_binding_digest


@pytest.mark.parametrize("mode", ["forged", "expired", "unsigned"])
def test_mvp1_i0b_forged_expired_or_unsigned_envelope_is_blocked(
    mode: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator

    baseline, _old_path, private_key, fingerprint, _old_request = _signed_request(
        tmp_path, monkeypatch
    )
    plan = baseline.model_copy(
        update={
            "expires_at": (
                datetime.now(UTC) - timedelta(seconds=1)
                if mode == "expired"
                else datetime.now(UTC) + timedelta(hours=2)
            )
        }
    )
    artifact_path = _store_envelope(
        tmp_path,
        evaluator._ADMISSION_STORE_ROOT,
        plan,
        private_key,
        fingerprint,
        sign=mode not in {"forged", "unsigned"},
    )
    if mode == "unsigned":
        payload = json.loads(artifact_path.read_text())
        payload.pop("signature_b64")
        artifact_path = _store_payload(
            evaluator._ADMISSION_STORE_ROOT,
            json.dumps(payload).encode("utf-8"),
        )

    decision = evaluator.evaluate_admission(_request_for(artifact_path, plan))
    assert decision.state == "BLOCKED"
    assert decision.reason_code in {
        "admission_expired",
        "invalid_approval_signature",
        "invalid_admission_artifact",
    }
    assert decision.verified_binding_digest is None


def test_mvp1_i0b_every_strict_request_field_is_compared_independently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission.evaluator import (
        select_canonical_admission_verifier,
    )

    _plan, _path, _key, _fingerprint, request = _signed_request(tmp_path, monkeypatch)
    verifier = select_canonical_admission_verifier(_PURPOSE, _SCHEMA)
    values = request.model_dump(mode="python")
    for field_name, original in values.items():
        replacement = (
            _sha("0")
            if field_name.endswith("_hash") or field_name.endswith("_digest")
            else "b" * 40
            if field_name == "expected_clean_integration_sha"
            else str(original) + "-mismatch"
        )
        mutated = request.model_copy(update={field_name: replacement})
        with pytest.raises(AdmissionPolicyDenied):
            verifier.verify(mutated)


def test_mvp1_i0b_signed_human_claim_cannot_override_root_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator

    plan, _old_path, key, fingerprint, _old_request = _signed_request(tmp_path, monkeypatch)
    artifact_path = _store_envelope(
        tmp_path,
        evaluator._ADMISSION_STORE_ROOT,
        plan,
        key,
        fingerprint,
        human_identity="service-account@example.test",
    )

    decision = evaluator.evaluate_admission(_request_for(artifact_path, plan))
    assert decision.state == "BLOCKED"
    assert decision.reason_code == "approver_identity_mismatch"


def test_mvp1_i0b_signed_cross_space_or_rolling_identity_is_blocked_by_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator
    from insurance_harness.run_admission.models import (
        canonical_model_identities_hash,
        canonical_model_plan_hash,
    )

    plan, _old_path, key, fingerprint, _old_request = _signed_request(tmp_path, monkeypatch)
    cross_space = plan.model_copy(update={"space_id": "other-space"})
    artifact_path = _store_envelope(
        tmp_path, evaluator._ADMISSION_STORE_ROOT, cross_space, key, fingerprint
    )
    decision = evaluator.evaluate_admission(_request_for(artifact_path, cross_space))
    assert decision.state == "BLOCKED"
    assert decision.reason_code == "approval_space_not_allowed"

    identities = list(_identities())
    identities[0] = identities[0].model_copy(update={"deployment_id": "qwen-latest"})
    frozen_identities = tuple(identities)
    rolling = plan.model_copy(
        update={
            "approved_identities": frozen_identities,
            "model_plan_hash": canonical_model_plan_hash(frozen_identities),
            "deployment_roles_hash": canonical_model_identities_hash(frozen_identities),
        }
    )
    artifact_path = _store_envelope(
        tmp_path, evaluator._ADMISSION_STORE_ROOT, rolling, key, fingerprint
    )
    decision = evaluator.evaluate_admission(_request_for(artifact_path, rolling))
    assert decision.state == "BLOCKED"
    assert decision.reason_code == "rolling_model_identity"


def test_mvp1_i0b_profile_rejects_role_or_nested_lock_drift_before_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator
    from insurance_harness.run_admission.models import (
        canonical_model_identities_hash,
        canonical_model_plan_hash,
    )

    baseline, _old_path, key, fingerprint, _old_request = _signed_request(tmp_path, monkeypatch)
    identities = _identities()[:-1]
    plan = baseline.model_copy(
        update={
            "approved_identities": identities,
            "model_plan_hash": canonical_model_plan_hash(identities),
            "deployment_roles_hash": canonical_model_identities_hash(identities),
        }
    )
    artifact_path = _store_envelope(
        tmp_path, evaluator._ADMISSION_STORE_ROOT, plan, key, fingerprint
    )

    decision = evaluator.evaluate_admission(_request_for(artifact_path, plan))
    assert decision.state == "BLOCKED"
    assert decision.reason_code == "profile_roles_mismatch"

    artifact_path = _store_envelope(
        tmp_path, evaluator._ADMISSION_STORE_ROOT, plan, key, fingerprint
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["payload"]["structured_dispatch"]["adapter_version"] = "substituted-adapter"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    decision = evaluator.evaluate_admission(_request_for(artifact_path, plan))
    assert decision.state == "BLOCKED"
    assert decision.reason_code == "invalid_admission_artifact"


def test_mvp1_i0b_cross_space_profile_and_020_replay_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission.evaluator import evaluate_admission

    plan, _path, _key, _fingerprint, request = _signed_request(tmp_path, monkeypatch)
    cross_space = request.model_copy(update={"expected_space_id": "other-space"})
    assert evaluate_admission(cross_space).state == "BLOCKED"

    unknown = request.model_copy(update={"expected_purpose": "wip-gs-v0.1"})
    decision = evaluate_admission(unknown)
    assert decision.state == "BLOCKED"
    assert decision.reason_code == "unknown_admission_profile"

    artifact_020 = (
        _REPOSITORY_ROOT / "openspec/changes/020-golden-v01-baseline-run/run-admission.yaml"
    )
    if not artifact_020.is_file():
        artifact_020 = _REPOSITORY_ROOT / "openspec/changes/020-golden-v01-baseline-run/proposal.md"
    replay = request.model_copy(
        update={
            "expected_admission_artifact_ref": str(artifact_020),
            "expected_admission_artifact_digest": hashlib.sha256(
                artifact_020.read_bytes()
            ).hexdigest(),
        }
    )
    decision = evaluate_admission(replay)
    assert decision.state == "BLOCKED"
    assert decision.reason_code == "invalid_admission_artifact"
    assert plan.purpose != "wip-gs-v0.1"


def test_mvp1_i0b_artifact_byte_drift_invalidates_the_external_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission.evaluator import evaluate_admission

    _plan, path, _key, _fingerprint, request = _signed_request(tmp_path, monkeypatch)
    path.write_bytes(path.read_bytes() + b"\n")

    decision = evaluate_admission(request)
    assert decision.state == "BLOCKED"
    assert decision.reason_code == "admission_artifact_digest_mismatch"


@pytest.mark.parametrize(
    "relative_path",
    [
        "dataset/input-10.bin",
        "dataset/mvp_v0_1/expected_routes.yaml",
        "dataset/mvp_v0_1/golden_slice.yaml",
        "contracts/current-schema.json",
        "templates/ordinary.yaml",
    ],
)
def test_mvp1_i0b_current_content_byte_drift_blocks_before_authority(
    relative_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator

    _plan, _path, _key, _fingerprint, request = _signed_request(tmp_path, monkeypatch)
    (evaluator._REPOSITORY_ROOT / relative_path).write_bytes(b"drifted\n")

    decision = evaluator.evaluate_admission(request)
    assert decision.state == "BLOCKED"
    assert decision.reason_code == "current_content_mismatch"
    assert decision.verified_binding_digest is None


def test_mvp1_i0b_dirty_or_wrong_integration_head_blocks_before_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator

    plan, path, key, fingerprint, request = _signed_request(tmp_path, monkeypatch)
    (evaluator._REPOSITORY_ROOT / "untracked.txt").write_text("dirty", encoding="utf-8")
    decision = evaluator.evaluate_admission(request)
    assert (decision.state, decision.reason_code) == (
        "BLOCKED",
        "current_content_mismatch",
    )

    (evaluator._REPOSITORY_ROOT / "untracked.txt").unlink()
    wrong = plan.model_copy(update={"clean_integration_sha": "b" * 40})
    staged = tmp_path / "wrong-head.json"
    _write_envelope(staged, wrong, key, fingerprint)
    digest = hashlib.sha256(staged.read_bytes()).hexdigest()
    artifact = evaluator._ADMISSION_STORE_ROOT / "sha256" / digest / "approval-envelope.json"
    artifact.parent.mkdir(mode=0o700)
    staged.replace(artifact)
    artifact.chmod(0o600)
    decision = evaluator.evaluate_admission(_request_for(artifact, wrong))
    assert (decision.state, decision.reason_code) == (
        "BLOCKED",
        "current_content_mismatch",
    )


def test_mvp1_i0b_policy_and_envelope_must_be_in_root_protected_stores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator, trust_policy

    _plan, path, _key, _fingerprint, request = _signed_request(tmp_path, monkeypatch)
    trust_policy._ROOT_TRUST_POLICY_PATH.chmod(0o666)
    decision = evaluator.evaluate_admission(request)
    assert (decision.state, decision.reason_code) == (
        "BLOCKED",
        "root_trust_policy_unavailable",
    )

    trust_policy._ROOT_TRUST_POLICY_PATH.chmod(0o600)
    path.parent.chmod(0o777)
    decision = evaluator.evaluate_admission(request)
    assert (decision.state, decision.reason_code) == (
        "BLOCKED",
        "invalid_admission_artifact",
    )


def test_mvp1_i0b_envelope_path_is_exactly_content_addressed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator

    plan, path, _key, _fingerprint, _request = _signed_request(tmp_path, monkeypatch)
    misplaced_dir = evaluator._ADMISSION_STORE_ROOT / "sha256" / _sha("f")
    misplaced_dir.mkdir(mode=0o700)
    misplaced = misplaced_dir / "approval-envelope.json"
    misplaced.write_bytes(path.read_bytes())
    misplaced.chmod(0o600)
    request = _request_for(misplaced, plan)
    decision = evaluator.evaluate_admission(request)
    assert (decision.state, decision.reason_code) == (
        "BLOCKED",
        "invalid_admission_artifact",
    )


def test_mvp1_i0b_root_protected_store_rejects_symlinked_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator

    _plan, path, _key, _fingerprint, request = _signed_request(tmp_path, monkeypatch)
    digest_dir = path.parent
    real_dir = digest_dir.with_name("real-envelope-directory")
    digest_dir.rename(real_dir)
    digest_dir.symlink_to(real_dir, target_is_directory=True)

    decision = evaluator.evaluate_admission(request)
    assert (decision.state, decision.reason_code) == (
        "BLOCKED",
        "invalid_admission_artifact",
    )


def test_mvp1_i0b_root_protected_store_rejects_symlinked_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator

    _plan, path, _key, _fingerprint, request = _signed_request(tmp_path, monkeypatch)
    real_path = path.with_name("real-envelope.json")
    path.rename(real_path)
    path.symlink_to(real_path.name)

    decision = evaluator.evaluate_admission(request)
    assert (decision.state, decision.reason_code) == (
        "BLOCKED",
        "invalid_admission_artifact",
    )


def test_mvp1_i0b_current_repository_rejects_tracked_symlinked_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator

    plan, _path, key, fingerprint, _request = _signed_request(tmp_path, monkeypatch)
    templates = evaluator._REPOSITORY_ROOT / "templates"
    real_templates = evaluator._REPOSITORY_ROOT / "templates-real"
    templates.rename(real_templates)
    templates.symlink_to(real_templates.name, target_is_directory=True)
    subprocess.run(["git", "add", "-A"], cwd=evaluator._REPOSITORY_ROOT, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "tracked symlink ancestor"],
        cwd=evaluator._REPOSITORY_ROOT,
        check=True,
    )
    clean_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=evaluator._REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    plan = plan.model_copy(update={"clean_integration_sha": clean_sha})
    path = _store_envelope(tmp_path, evaluator._ADMISSION_STORE_ROOT, plan, key, fingerprint)

    decision = evaluator.evaluate_admission(_request_for(path, plan))
    assert (decision.state, decision.reason_code) == (
        "BLOCKED",
        "current_content_mismatch",
    )


@pytest.mark.parametrize(
    ("asset_name", "manifest_hash_field", "plan_hash_field"),
    [
        ("expected_routes.yaml", "expected_routes_sha256", "routing_policy_hash"),
        ("golden_slice.yaml", "golden_slice_sha256", "golden_slice_hash"),
    ],
)
def test_mvp1_i0b_code_owned_route_and_golden_schemas_cannot_be_redefined(
    asset_name: str,
    manifest_hash_field: str,
    plan_hash_field: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yaml

    from insurance_harness.run_admission import evaluator

    plan, _path, key, fingerprint, _request = _signed_request(tmp_path, monkeypatch)
    data_root = evaluator._REPOSITORY_ROOT / "dataset/mvp_v0_1"
    asset = data_root / asset_name
    asset.write_text("schema_version: caller-defined-v99\n", encoding="utf-8")
    asset_hash = hashlib.sha256(asset.read_bytes()).hexdigest()
    manifest_path = data_root / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest[manifest_hash_field] = asset_hash
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=evaluator._REPOSITORY_ROOT, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "caller schema substitution"],
        cwd=evaluator._REPOSITORY_ROOT,
        check=True,
    )
    clean_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=evaluator._REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    updates: dict[str, object] = {
        plan_hash_field: asset_hash,
        "clean_integration_sha": clean_sha,
    }
    if asset_name == "expected_routes.yaml":
        updates["routing_policy_identity"] = "caller-defined-v99"
    plan = plan.model_copy(update=updates)
    path = _store_envelope(tmp_path, evaluator._ADMISSION_STORE_ROOT, plan, key, fingerprint)

    decision = evaluator.evaluate_admission(_request_for(path, plan))
    assert (decision.state, decision.reason_code) == (
        "BLOCKED",
        "current_content_mismatch",
    )


def test_mvp1_i0b_code_owned_eligibility_shape_cannot_be_relaxed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yaml

    from insurance_harness.run_admission import evaluator

    plan, _path, key, fingerprint, _request = _signed_request(tmp_path, monkeypatch)
    manifest_path = evaluator._REPOSITORY_ROOT / "dataset/mvp_v0_1/manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    entries = manifest["entries"]
    document = next(entry for entry in entries if entry["dispatch_role"] == "document-compile")
    document["dispatch_role"] = "registered-structured"
    document["structured"] = True
    eligibility = [
        {
            "claim_evidence_eligible": entry["claim_evidence_eligible"],
            "dispatch_role": entry["dispatch_role"],
            "entry_id": entry["entry_id"],
            "structured": entry["structured"],
        }
        for entry in entries
    ]
    manifest_hash = _canonical_digest(b"", entries)
    eligibility_hash = _canonical_digest(b"", eligibility)
    manifest["entry_set_sha256"] = manifest_hash
    manifest["eligibility_sha256"] = eligibility_hash
    manifest["run_revision"] = "mvp-v0.1-" + manifest_hash[:16]
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=evaluator._REPOSITORY_ROOT, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "eligibility relaxation"],
        cwd=evaluator._REPOSITORY_ROOT,
        check=True,
    )
    clean_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=evaluator._REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    plan = plan.model_copy(
        update={
            "run_revision": manifest["run_revision"],
            "manifest_hash": manifest_hash,
            "eligibility_hash": eligibility_hash,
            "clean_integration_sha": clean_sha,
        }
    )
    path = _store_envelope(tmp_path, evaluator._ADMISSION_STORE_ROOT, plan, key, fingerprint)

    decision = evaluator.evaluate_admission(_request_for(path, plan))
    assert (decision.state, decision.reason_code) == (
        "BLOCKED",
        "current_content_mismatch",
    )


def test_mvp1_i0b_entry_byte_change_requires_derived_new_run_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yaml

    from insurance_harness.run_admission import evaluator

    plan, _path, key, fingerprint, _request = _signed_request(tmp_path, monkeypatch)
    manifest_path = evaluator._REPOSITORY_ROOT / "dataset/mvp_v0_1/manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    entry = next(
        item for item in manifest["entries"] if item["dispatch_role"] == "document-compile"
    )
    source = evaluator._REPOSITORY_ROOT / entry["path"]
    source.write_bytes(source.read_bytes() + b"changed\n")
    entry["size_bytes"] = source.stat().st_size
    entry["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest_hash = _canonical_digest(b"", manifest["entries"])
    manifest["entry_set_sha256"] = manifest_hash
    original_run_revision = manifest["run_revision"]
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=evaluator._REPOSITORY_ROOT, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "bytes changed without revision"],
        cwd=evaluator._REPOSITORY_ROOT,
        check=True,
    )
    clean_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=evaluator._REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    plan = plan.model_copy(
        update={
            "manifest_hash": manifest_hash,
            "clean_integration_sha": clean_sha,
        }
    )
    assert plan.run_revision == original_run_revision
    path = _store_envelope(tmp_path, evaluator._ADMISSION_STORE_ROOT, plan, key, fingerprint)

    decision = evaluator.evaluate_admission(_request_for(path, plan))
    assert (decision.state, decision.reason_code) == (
        "BLOCKED",
        "current_content_mismatch",
    )


def test_mvp1_i0b_expiry_is_rechecked_after_current_content_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator

    baseline, _path, key, fingerprint, _request = _signed_request(tmp_path, monkeypatch)
    before = datetime(2030, 1, 1, tzinfo=UTC)
    plan = baseline.model_copy(update={"expires_at": before + timedelta(seconds=1)})
    path = _store_envelope(tmp_path, evaluator._ADMISSION_STORE_ROOT, plan, key, fingerprint)

    class _AdvancingClock:
        calls = 0

        @classmethod
        def now(cls, _timezone: object) -> datetime:
            cls.calls += 1
            return before if cls.calls == 1 else before + timedelta(seconds=2)

    monkeypatch.setattr(evaluator, "datetime", _AdvancingClock)
    decision = evaluator.evaluate_admission(_request_for(path, plan))
    assert (decision.state, decision.reason_code) == (
        "BLOCKED",
        "admission_expired",
    )
    assert _AdvancingClock.calls == 2


def test_mvp1_i0b_git_environment_cannot_redirect_clean_sha_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator

    baseline, _path, key, fingerprint, _request = _signed_request(tmp_path, monkeypatch)
    (evaluator._REPOSITORY_ROOT / "dirty-untracked.txt").write_text(
        "dirty",
        encoding="utf-8",
    )
    alternate = tmp_path / "alternate-repository"
    alternate.mkdir()
    (alternate / "alternate.txt").write_text("alternate", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=alternate, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=alternate, check=True)
    subprocess.run(["git", "config", "user.name", "Admission Test"], cwd=alternate, check=True)
    subprocess.run(["git", "add", "."], cwd=alternate, check=True)
    subprocess.run(["git", "commit", "-qm", "alternate"], cwd=alternate, check=True)
    alternate_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=alternate,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    plan = baseline.model_copy(update={"clean_integration_sha": alternate_sha})
    path = _store_envelope(tmp_path, evaluator._ADMISSION_STORE_ROOT, plan, key, fingerprint)
    monkeypatch.setenv("GIT_DIR", str(alternate / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(alternate))

    decision = evaluator.evaluate_admission(_request_for(path, plan))
    assert (decision.state, decision.reason_code) == (
        "BLOCKED",
        "current_content_mismatch",
    )


def test_mvp1_i0b_repository_config_cannot_redirect_clean_work_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator

    plan, _path, key, fingerprint, _request = _signed_request(tmp_path, monkeypatch)
    alternate = tmp_path / "alternate-work-tree"
    shutil.copytree(
        evaluator._REPOSITORY_ROOT,
        alternate,
        ignore=shutil.ignore_patterns(".git"),
    )
    subprocess.run(
        ["git", "config", "core.worktree", str(alternate)],
        cwd=evaluator._REPOSITORY_ROOT,
        check=True,
    )
    (evaluator._REPOSITORY_ROOT / "dirty-untracked.txt").write_text(
        "dirty",
        encoding="utf-8",
    )
    path = _store_envelope(tmp_path, evaluator._ADMISSION_STORE_ROOT, plan, key, fingerprint)

    decision = evaluator.evaluate_admission(_request_for(path, plan))
    assert (decision.state, decision.reason_code) == (
        "BLOCKED",
        "current_content_mismatch",
    )


def test_mvp1_i0b_external_artifact_uses_exact_raw_plan_schema_before_signature(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator

    plan, path, _key, _fingerprint, _request = _signed_request(tmp_path, monkeypatch)
    original = path.read_text(encoding="utf-8")
    duplicate_path = _store_payload(
        evaluator._ADMISSION_STORE_ROOT,
        ('{"schema_version":"shadow",' + original[1:]).encode("utf-8"),
    )
    decision = evaluator.evaluate_admission(_request_for(duplicate_path, plan))
    assert decision.state == "BLOCKED"
    assert decision.reason_code == "invalid_admission_artifact"

    issued: list[object] = []

    def record_issue(*args: object, **kwargs: object) -> object:
        issued.append((args, kwargs))
        raise AssertionError("raw artifact reached the capability issuer")

    monkeypatch.setattr(evaluator, "_issue_verified_admission", record_issue)
    canonical = json.loads(original)
    canonical_expiry = canonical["payload"]["expires_at"]
    assert type(canonical_expiry) is str
    equivalent_offset_expiry = datetime.fromtimestamp(
        plan.expires_at.timestamp(),
        timezone(timedelta(hours=8)),
    ).isoformat()
    raw_caps = canonical["payload"]["resource_caps"]
    mutations: tuple[tuple[str, object], ...] = tuple(
        (f"resource_caps.{field_name}", replacement)
        for field_name in (
            "worker_limit",
            "attempt_limit",
            "time_limit_seconds",
            "token_limit",
        )
        for replacement in (
            True,
            float(raw_caps[field_name]),
            str(raw_caps[field_name]),
            0,
            -1,
        )
    ) + (
        ("entry_count", True),
        ("entry_count", 23.0),
        ("entry_count", "23"),
        ("expires_at", int(plan.expires_at.timestamp())),
        ("expires_at", canonical_expiry.replace("Z", "+00:00")),
        ("expires_at", equivalent_offset_expiry),
        ("expires_at", _EXTREME_OFFSET_EXPIRY),
        ("expires_at", "9999-12-31T23:59:59-14:00"),
        ("expires_at", "not-rfc3339"),
    )
    for field_path, replacement in mutations:
        artifact = copy.deepcopy(canonical)
        target = artifact["payload"]
        parts = field_path.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = replacement
        mutated_path = _store_payload(
            evaluator._ADMISSION_STORE_ROOT,
            json.dumps(artifact, separators=(",", ":")).encode("utf-8"),
        )

        decision = evaluator.evaluate_admission(_request_for(mutated_path, plan))
        assert (decision.state, decision.reason_code) == (
            "BLOCKED",
            "invalid_admission_artifact",
        ), field_path
        assert decision.verified_binding_digest is None

    from insurance_harness.run_admission import models as models_module

    class FaultingDateTimeAdapter:
        def __init__(self, stage: str) -> None:
            self._stage = stage

        def validate_python(self, _value: object) -> datetime:
            if self._stage == "parse":
                raise OSError("simulated datetime parse I/O failure")
            return plan.expires_at

        def dump_python(self, _value: object, *, mode: str) -> object:
            assert mode == "json"
            raise OSError("simulated datetime serialization I/O failure")

    for stage in ("parse", "serialize"):
        with monkeypatch.context() as fault:
            fault.setattr(
                models_module,
                "_AWARE_DATETIME_ADAPTER",
                FaultingDateTimeAdapter(stage),
            )
            with pytest.raises(ValueError) as exc_info:
                models_module._validate_exact_raw_mvp_plan(canonical["payload"])
            assert type(exc_info.value) is ValueError
            decision = evaluator.evaluate_admission(_request_for(path, plan))
            assert (decision.state, decision.reason_code) == (
                "BLOCKED",
                "invalid_admission_artifact",
            )
    assert issued == []


def test_mvp1_i0b_027_capability_cannot_be_constructed_copied_or_serialized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission.evaluator import (
        select_canonical_admission_verifier,
    )

    _plan, _path, _key, _fingerprint, request = _signed_request(tmp_path, monkeypatch)
    verified = select_canonical_admission_verifier(_PURPOSE, _SCHEMA).verify(request)

    with pytest.raises(TypeError):
        VerifiedAdmission()
    forged = object.__new__(VerifiedAdmission)
    with pytest.raises(TypeError, match="authority is unavailable"):
        _ = forged.binding
    with pytest.raises(TypeError, match="copied"):
        copy.copy(verified)
    with pytest.raises(TypeError, match="serialized"):
        pickle.dumps(verified)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork")
def test_mvp1_i0b_027_capability_is_revoked_in_a_forked_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission.evaluator import (
        select_canonical_admission_verifier,
    )

    _plan, _path, _key, _fingerprint, request = _signed_request(tmp_path, monkeypatch)
    verified = select_canonical_admission_verifier(_PURPOSE, _SCHEMA).verify(request)
    read_fd, write_fd = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_fd)
        try:
            _ = verified.binding
        except TypeError:
            os.write(write_fd, b"revoked")
        else:
            os.write(write_fd, b"inherited")
        finally:
            os.close(write_fd)
            os._exit(0)
    os.close(write_fd)
    result = os.read(read_fd, 16)
    os.close(read_fd)
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    assert result == b"revoked"


def test_mvp1_i0b_constructed_signing_dto_cannot_discard_hidden_state() -> None:
    from insurance_harness.run_admission.models import (
        ApprovalEnvelope,
        approval_signed_bytes,
    )

    plan = _build_plan()
    forged = ApprovalEnvelope.model_construct(
        schema_version="insurancekb.run-admission-approval-envelope.v1",
        signature_domain=_DOMAIN,
        key_id="mvp-human-key-1",
        public_key_fingerprint=_sha("a"),
        human_identity="human-release-owner@example.test",
        approver_role="mvp-run-admission-approver",
        payload=plan,
        signature_b64=base64.b64encode(b"\0" * 64).decode("ascii"),
    )
    object.__setattr__(forged, "hidden_authority", "must-not-be-discarded")
    with pytest.raises(ValueError, match="invalid run-admission DTO"):
        approval_signed_bytes(forged)


@pytest.mark.parametrize("control", [KeyboardInterrupt, SystemExit])
def test_mvp1_i0b_process_control_exceptions_are_not_converted_to_decisions(
    control: type[BaseException],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator

    _plan, _path, _key, _fingerprint, request = _signed_request(tmp_path, monkeypatch)

    def interrupt(_ref: str, _digest: str) -> bytes:
        raise control

    monkeypatch.setattr(evaluator, "_read_external_artifact", interrupt)
    with pytest.raises(control):
        evaluator.evaluate_admission(request)


def test_mvp1_i0b_cli_only_renders_unsigned_payload_and_validates_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from insurance_harness.run_admission.cli import main

    plan, artifact, _key, _fingerprint, request = _signed_request(tmp_path, monkeypatch)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(), encoding="utf-8")
    unsigned_path = tmp_path / "unsigned-payload.json"
    assert (
        main(
            [
                "render-unsigned",
                "--plan",
                str(plan_path),
                "--output",
                str(unsigned_path),
            ]
        )
        == 0
    )
    rendered = json.loads(unsigned_path.read_text(encoding="utf-8"))
    assert rendered["purpose"] == _PURPOSE
    assert "signature_b64" not in rendered
    assert "state" not in rendered

    from insurance_harness.run_admission import evaluator

    request_path = _store_request(evaluator._ADMISSION_STORE_ROOT, request)
    assert main(["verify", "--request", str(request_path)]) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["state"] == "READY"
    assert "verified_binding_digest" in decision

    issued: list[object] = []

    def record_issue(*args: object, **kwargs: object) -> object:
        issued.append((args, kwargs))
        raise AssertionError("raw CLI artifact reached the capability issuer")

    monkeypatch.setattr(evaluator, "_issue_verified_admission", record_issue)
    canonical = json.loads(artifact.read_text(encoding="utf-8"))
    raw_expiry = canonical["payload"]["expires_at"]
    equivalent_offset_expiry = datetime.fromtimestamp(
        plan.expires_at.timestamp(),
        timezone(timedelta(hours=8)),
    ).isoformat()
    mutations: tuple[tuple[str, object], ...] = (
        ("resource_caps.worker_limit", 4.0),
        ("resource_caps.worker_limit", "4"),
        ("entry_count", 23.0),
        ("expires_at", int(plan.expires_at.timestamp())),
        ("expires_at", raw_expiry.replace("Z", "+00:00")),
        ("expires_at", equivalent_offset_expiry),
        ("expires_at", _EXTREME_OFFSET_EXPIRY),
    )
    for field_path, replacement in mutations:
        raw = copy.deepcopy(canonical)
        target = raw["payload"]
        parts = field_path.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = replacement
        mutated_artifact = _store_payload(
            evaluator._ADMISSION_STORE_ROOT,
            json.dumps(raw, separators=(",", ":")).encode("utf-8"),
        )
        mutated_request = _request_for(mutated_artifact, plan)
        mutated_request_path = _store_request(
            evaluator._ADMISSION_STORE_ROOT,
            mutated_request,
        )

        assert main(["verify", "--request", str(mutated_request_path)]) == 2
        blocked = json.loads(capsys.readouterr().out)
        assert blocked == {
            "state": "BLOCKED",
            "reason_code": "invalid_admission_artifact",
            "verified_binding_digest": None,
        }
    assert issued == []


def test_mvp1_i0b_cli_rejects_request_outside_content_addressed_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission.cli import main

    _plan, _artifact, _key, _fingerprint, request = _signed_request(tmp_path, monkeypatch)
    request_path = tmp_path / "caller-request.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")

    assert main(["verify", "--request", str(request_path)]) == 2


def test_mvp1_i0b_cli_malformed_yaml_request_is_sanitized_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from insurance_harness.run_admission import evaluator
    from insurance_harness.run_admission.cli import main

    _plan, _artifact, _key, _fingerprint, _request = _signed_request(tmp_path, monkeypatch)
    request_path = _store_request_payload(
        evaluator._ADMISSION_STORE_ROOT,
        b"[\n",
    )

    assert main(["verify", "--request", str(request_path)]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "state": "BLOCKED",
        "reason_code": "invalid_cli_input",
    }


def test_mvp1_i0b_cli_has_no_profile_role_signing_or_trust_override() -> None:
    from insurance_harness.run_admission.cli import build_parser

    help_text = build_parser().format_help()
    for forbidden in (
        "--profile",
        "--role",
        "--sign",
        "--private-key",
        "--trust-policy",
    ):
        assert forbidden not in help_text


def test_mvp1_i0b_cli_render_rejects_non_registered_or_noncanonical_raw_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from insurance_harness.run_admission.cli import main
    from insurance_harness.run_admission.models import (
        canonical_model_identities_hash,
        canonical_model_plan_hash,
    )

    plan, _artifact, _key, _fingerprint, _request = _signed_request(tmp_path, monkeypatch)
    reduced_roles = plan.approved_identities[:-1]
    invalid_plans = (
        plan.model_copy(update={"purpose": "caller-selected-profile"}),
        plan.model_copy(update={"run_schema_version": "caller-selected-schema"}),
        plan.model_copy(
            update={
                "approved_identities": reduced_roles,
                "model_plan_hash": canonical_model_plan_hash(reduced_roles),
                "deployment_roles_hash": canonical_model_identities_hash(reduced_roles),
            }
        ),
    )
    for index, arbitrary in enumerate(invalid_plans):
        plan_path = tmp_path / f"arbitrary-plan-{index}.json"
        output_path = tmp_path / f"must-not-exist-{index}.json"
        plan_path.write_text(arbitrary.model_dump_json(), encoding="utf-8")

        assert (
            main(
                [
                    "render-unsigned",
                    "--plan",
                    str(plan_path),
                    "--output",
                    str(output_path),
                ]
            )
            == 2
        )
        assert not output_path.exists()

    import yaml

    canonical = plan.model_dump(mode="json", round_trip=True)
    canonical_expiry = canonical["expires_at"]
    assert type(canonical_expiry) is str
    equivalent_offset_expiry = datetime.fromtimestamp(
        plan.expires_at.timestamp(),
        timezone(timedelta(hours=8)),
    ).isoformat()
    raw_caps = canonical["resource_caps"]
    raw_mutations: tuple[tuple[str, object], ...] = tuple(
        (f"resource_caps.{field_name}", replacement)
        for field_name in (
            "worker_limit",
            "attempt_limit",
            "time_limit_seconds",
            "token_limit",
        )
        for replacement in (
            True,
            float(raw_caps[field_name]),
            str(raw_caps[field_name]),
            0,
            -1,
        )
    ) + (
        ("entry_count", True),
        ("entry_count", 23.0),
        ("entry_count", "23"),
        ("expires_at", int(plan.expires_at.timestamp())),
        ("expires_at", canonical_expiry.replace("Z", "+00:00")),
        ("expires_at", equivalent_offset_expiry),
        ("expires_at", _EXTREME_OFFSET_EXPIRY),
        ("expires_at", "9999-12-31T23:59:59-14:00"),
        ("expires_at", "not-rfc3339"),
    )
    for suffix in ("json", "yaml"):
        for index, (field_path, replacement) in enumerate(raw_mutations):
            raw = copy.deepcopy(canonical)
            target = raw
            parts = field_path.split(".")
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = replacement
            plan_path = tmp_path / f"noncanonical-{suffix}-{index}.{suffix}"
            output_path = tmp_path / f"must-not-render-{suffix}-{index}.json"
            plan_path.write_text(
                (
                    json.dumps(raw, separators=(",", ":"))
                    if suffix == "json"
                    else yaml.safe_dump(raw, sort_keys=False)
                ),
                encoding="utf-8",
            )

            assert (
                main(
                    [
                        "render-unsigned",
                        "--plan",
                        str(plan_path),
                        "--output",
                        str(output_path),
                    ]
                )
                == 2
            ), (suffix, field_path)
            assert not output_path.exists()

    from insurance_harness.run_admission import models as models_module

    class FaultingDateTimeAdapter:
        def __init__(self, stage: str) -> None:
            self._stage = stage

        def validate_python(self, _value: object) -> datetime:
            if self._stage == "parse":
                raise OSError("simulated datetime parse I/O failure")
            return plan.expires_at

        def dump_python(self, _value: object, *, mode: str) -> object:
            assert mode == "json"
            raise OSError("simulated datetime serialization I/O failure")

    canonical_path = tmp_path / "canonical-for-fault-injection.json"
    canonical_path.write_text(json.dumps(canonical), encoding="utf-8")
    for stage in ("parse", "serialize"):
        output_path = tmp_path / f"must-not-render-{stage}-fault.json"
        with monkeypatch.context() as fault:
            fault.setattr(
                models_module,
                "_AWARE_DATETIME_ADAPTER",
                FaultingDateTimeAdapter(stage),
            )
            assert (
                main(
                    [
                        "render-unsigned",
                        "--plan",
                        str(canonical_path),
                        "--output",
                        str(output_path),
                    ]
                )
                == 2
            )
        assert not output_path.exists()
    blocked_lines = capsys.readouterr().out.splitlines()
    assert blocked_lines
    assert all(
        json.loads(line)
        == {"state": "BLOCKED", "reason_code": "invalid_cli_input"}
        for line in blocked_lines
    )


def test_mvp1_i0b_unsigned_templates_and_architecture_carry_no_authority() -> None:
    owned = _REPOSITORY_ROOT / "harness/src/insurance_harness/run_admission"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in owned.rglob("*.py") if path.is_file()
    )
    for forbidden in (
        "goldenset.admission",
        "run_020",
        "wip-gs-v0.1",
        "Ed25519PrivateKey",
        "provider",
        "model_client",
        "transport",
        "ReceiptSink",
        "_issue_model_permit",
        "ReleaseAuthorizer",
    ):
        assert forbidden not in source

    change = _REPOSITORY_ROOT / "openspec/changes/030-enterprise-wiki-mvp-slice"
    templates = (
        change / "admission-plan.template.yaml",
        change / "run-request.template.yaml",
        change / "artifacts/index.template.json",
    )
    for template in templates:
        assert template.is_file()
        text = template.read_text(encoding="utf-8").lower()
        assert "private_key" not in text
        assert "signature_b64" not in text
        assert "state: ready" not in text
        assert '"state": "ready"' not in text

    import yaml

    plan_template = yaml.safe_load(templates[0].read_text(encoding="utf-8"))
    assert set(plan_template) == set(MvpAdmissionPlan.model_fields)
    assert set(plan_template["structured_dispatch"]) == {
        "registration_entries",
        "source_registry_identity",
        "source_authority_hash",
        "record_schema_refs",
        "adapter_version",
        "canonicalizer_version",
        "source_profile_fingerprints",
        "mapping_manifest_hashes",
        "effective_mapping_versions",
    }
    assert set(plan_template["resource_caps"]) == {
        "worker_limit",
        "attempt_limit",
        "time_limit_seconds",
        "token_limit",
    }
    request_template = yaml.safe_load(templates[1].read_text(encoding="utf-8"))
    assert set(request_template) == set(StrictAdmissionRequestBinding.model_fields)
