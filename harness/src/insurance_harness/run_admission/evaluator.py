"""Canonical verifier for the independent OpenSpec 030 admission profile."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Final

import yaml
from pydantic import ValidationError

from insurance_harness.model_policy import (
    AdmissionBinding,
    AdmissionPolicyDenied,
    AdmissionVerifier,
    StrictAdmissionRequestBinding,
    VerifiedAdmission,
)
from insurance_harness.model_policy.admission import _issue_verified_admission

from . import trust_policy
from .models import (
    AdmissionDecision,
    ApprovalEnvelope,
    ContentArtifactLock,
    ContentSetLock,
    MvpAdmissionPlan,
    _validate_exact_raw_mvp_plan,
    canonical_model_identities_hash,
    canonical_model_plan_hash,
)
from .profiles.mvp import (
    MVP_PURPOSE,
    MVP_RUN_SCHEMA_VERSION,
    MVP_SIGNATURE_DOMAIN,
    validate_mvp_plan,
)

_MAX_ARTIFACT_BYTES: Final = 2 * 1024 * 1024
_MAX_REQUEST_BYTES: Final = 256 * 1024
_VERIFIER_ID: Final = "insurance-harness.run-admission.enterprise-wiki-mvp"
_VERIFIER_VERSION: Final = "1"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_ADMISSION_STORE_ROOT = Path("/var/lib/insurancekb/run-admission")
_DATA_ROOT_RELATIVE = Path("dataset/mvp_v0_1")
_MAX_CURRENT_FILE_BYTES: Final = 32 * 1024 * 1024
_GIT_EXECUTABLE = "/usr/bin/git"
_GIT_ENVIRONMENT: Final = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
}


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _read_external_artifact(ref: str, expected_digest: str) -> bytes:
    path = Path(ref)
    expected = _ADMISSION_STORE_ROOT / "sha256" / expected_digest / "approval-envelope.json"
    if path != expected:
        raise AdmissionPolicyDenied("invalid_admission_artifact")
    return trust_policy._read_root_protected_file(
        path,
        root=_ADMISSION_STORE_ROOT,
        max_bytes=_MAX_ARTIFACT_BYTES,
        reason_code="invalid_admission_artifact",
    )


def _read_external_request(path: Path) -> bytes:
    try:
        relative = path.relative_to(_ADMISSION_STORE_ROOT)
        if len(relative.parts) != 4 or relative.parts[:2] != ("requests", "sha256"):
            raise ValueError
        digest = relative.parts[2]
        if (
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or relative.parts[3] != "run-request.yaml"
        ):
            raise ValueError
        payload = trust_policy._read_root_protected_file(
            path,
            root=_ADMISSION_STORE_ROOT,
            max_bytes=_MAX_REQUEST_BYTES,
            reason_code="invalid_admission_request",
        )
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError
        return payload
    except AdmissionPolicyDenied:
        raise
    except (OSError, RuntimeError, ValueError):
        raise AdmissionPolicyDenied("invalid_admission_request") from None


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    value: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in value:
            raise ValueError("duplicate YAML key")
        value[key] = loader.construct_object(value_node, deep=deep)
    return value


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _repository_file(relative_text: str) -> Path:
    relative = PurePosixPath(relative_text)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError("invalid repository path")
    path = _REPOSITORY_ROOT.joinpath(*relative.parts)
    resolved_root = _REPOSITORY_ROOT.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if resolved == resolved_root or not resolved.is_relative_to(resolved_root):
        raise ValueError("invalid repository file")
    directories = (_REPOSITORY_ROOT,) + tuple(
        _REPOSITORY_ROOT.joinpath(*relative.parts[:index])
        for index in range(1, len(relative.parts))
    )
    for directory in directories:
        info = directory.stat(follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or directory.is_symlink():
            raise ValueError("invalid repository directory")
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise ValueError("invalid repository file")
    return path


def _read_current_file(relative_text: str) -> bytes:
    path = _repository_file(relative_text)
    before = path.stat(follow_symlinks=False)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("current content changed while opening")
        payload = os.read(descriptor, _MAX_CURRENT_FILE_BYTES + 1)
    finally:
        os.close(descriptor)
    if not payload or len(payload) > _MAX_CURRENT_FILE_BYTES:
        raise ValueError("invalid current content")
    return payload


def _verify_content_lock(lock: ContentSetLock) -> str:
    for artifact in lock.artifacts:
        if hashlib.sha256(_read_current_file(artifact.path)).hexdigest() != (artifact.sha256):
            raise ValueError("current content hash mismatch")
    return lock.digest


def _verify_artifact_lock(artifact: ContentArtifactLock) -> None:
    if hashlib.sha256(_read_current_file(artifact.path)).hexdigest() != artifact.sha256:
        raise ValueError("current content hash mismatch")


def _load_yaml_mapping(relative_text: str) -> tuple[dict[str, object], bytes]:
    payload = _read_current_file(relative_text)
    value = yaml.load(payload.decode("utf-8"), Loader=_UniqueKeyLoader)
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise ValueError("current YAML must be a string-keyed mapping")
    return value, payload


def _clean_repository_sha() -> str:
    repository_args = [
        _GIT_EXECUTABLE,
        f"--git-dir={_REPOSITORY_ROOT / '.git'}",
        f"--work-tree={_REPOSITORY_ROOT}",
        "-c",
        "core.bare=false",
        "-c",
        f"core.worktree={_REPOSITORY_ROOT}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
    ]
    head = subprocess.run(
        [*repository_args, "rev-parse", "HEAD"],
        cwd=_REPOSITORY_ROOT,
        env=_GIT_ENVIRONMENT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        [*repository_args, "status", "--porcelain", "--untracked-files=normal"],
        cwd=_REPOSITORY_ROOT,
        env=_GIT_ENVIRONMENT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if (
        status
        or len(head) not in {40, 64}
        or any(character not in "0123456789abcdef" for character in head)
    ):
        raise ValueError("repository is not the exact clean integration commit")
    return head


def _verify_current_content(plan: MvpAdmissionPlan) -> dict[str, object]:
    try:
        clean_sha_before = _clean_repository_sha()
        manifest, _manifest_bytes = _load_yaml_mapping(
            (_DATA_ROOT_RELATIVE / "manifest.yaml").as_posix()
        )
        routes, route_bytes = _load_yaml_mapping(
            (_DATA_ROOT_RELATIVE / "expected_routes.yaml").as_posix()
        )
        golden, golden_bytes = _load_yaml_mapping(
            (_DATA_ROOT_RELATIVE / "golden_slice.yaml").as_posix()
        )
        if (
            routes.get("schema_version") != "enterprise-wiki-mvp-routes-v1"
            or golden.get("schema_version") != "enterprise-wiki-mvp-golden-v1"
        ):
            raise ValueError("code-owned MVP data schema mismatch")
        entries = manifest.get("entries")
        if (
            manifest.get("schema_version") != "enterprise-wiki-mvp-manifest-v1"
            or type(entries) is not list
            or len(entries) != 23
            or any(type(entry) is not dict for entry in entries)
        ):
            raise ValueError("invalid manifest")
        entry_ids = [entry.get("entry_id") for entry in entries]
        entry_paths = [entry.get("path") for entry in entries]
        if (
            entries != sorted(entries, key=lambda entry: str(entry.get("entry_id")))
            or len(set(entry_ids)) != 23
            or len(set(entry_paths)) != 23
            or any(type(value) is not str or not value for value in entry_ids + entry_paths)
        ):
            raise ValueError("invalid manifest entries")
        for entry in entries:
            payload = _read_current_file(str(entry["path"]))
            if (
                type(entry.get("size_bytes")) is not int
                or entry["size_bytes"] != len(payload)
                or entry.get("sha256") != hashlib.sha256(payload).hexdigest()
                or type(entry.get("structured")) is not bool
                or type(entry.get("claim_evidence_eligible")) is not bool
                or type(entry.get("dispatch_role")) is not str
                or type(entry.get("rights")) is not dict
                or type(entry.get("provenance")) is not dict
            ):
                raise ValueError("manifest entry drift")
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
        manifest_hash = _canonical_sha256(entries)
        eligibility_hash = _canonical_sha256(eligibility)
        rights_hash = _canonical_sha256(rights)
        provenance_hash = _canonical_sha256(provenance)
        routing_hash = hashlib.sha256(route_bytes).hexdigest()
        golden_hash = hashlib.sha256(golden_bytes).hexdigest()
        if (
            manifest.get("run_revision") != "mvp-v0.1-" + manifest_hash[:16]
            or manifest.get("entry_set_sha256") != manifest_hash
            or manifest.get("eligibility_sha256") != eligibility_hash
            or manifest.get("rights_sha256") != rights_hash
            or manifest.get("provenance_sha256") != provenance_hash
            or manifest.get("expected_routes_sha256") != routing_hash
            or manifest.get("golden_slice_sha256") != golden_hash
        ):
            raise ValueError("manifest aggregate drift")
        registration_entries = tuple(
            entry for entry in entries if entry["dispatch_role"] == "registration-only"
        )
        document_entries = tuple(
            entry for entry in entries if entry["dispatch_role"] == "document-compile"
        )
        structured_entries = tuple(
            entry for entry in entries if entry["dispatch_role"] == "registered-structured"
        )
        if (
            len(registration_entries) != 5
            or len(document_entries) != 17
            or len(structured_entries) != 1
            or any(
                entry.get("input_kind") != "product_meta"
                or entry["structured"] is not True
                or entry["claim_evidence_eligible"] is not False
                for entry in registration_entries
            )
            or any(
                entry["structured"] is not False or entry["claim_evidence_eligible"] is not True
                for entry in document_entries
            )
            or any(
                entry["structured"] is not True or entry["claim_evidence_eligible"] is not True
                for entry in structured_entries
            )
        ):
            raise ValueError("MVP eligibility shape drift")
        registration_by_path = {entry["path"]: entry for entry in registration_entries}
        for lock in plan.structured_dispatch.registration_entries:
            _verify_artifact_lock(lock)
            entry = registration_by_path.get(lock.path)
            if entry is None or entry["sha256"] != lock.sha256:
                raise ValueError("structured registration drift")
        schema_hash = _verify_content_lock(plan.schema_lock)
        template_lock_hash = _verify_content_lock(plan.template_lock)
        clean_sha_after = _clean_repository_sha()
        if clean_sha_after != clean_sha_before:
            raise ValueError("repository changed during admission verification")
        actual = {
            "run_revision": manifest.get("run_revision"),
            "entry_count": len(entries),
            "manifest_hash": manifest_hash,
            "eligibility_hash": eligibility_hash,
            "golden_slice_hash": golden_hash,
            "routing_policy_identity": routes.get("schema_version"),
            "routing_policy_hash": routing_hash,
            "schema_hash": schema_hash,
            "template_lock_hash": template_lock_hash,
            "structured_dispatch_hash": plan.structured_dispatch.digest,
            "model_plan_hash": canonical_model_plan_hash(plan.approved_identities),
            "deployment_roles_hash": canonical_model_identities_hash(plan.approved_identities),
            "resource_caps_hash": plan.resource_caps.digest,
            "rights_hash": rights_hash,
            "provenance_hash": provenance_hash,
            "clean_integration_sha": clean_sha_after,
        }
        for field_name, actual_value in actual.items():
            if getattr(plan, field_name) != actual_value:
                raise ValueError(f"current {field_name} mismatch")
        return actual
    except AdmissionPolicyDenied:
        raise
    except (
        OSError,
        RuntimeError,
        UnicodeError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
    ):
        raise AdmissionPolicyDenied("current_content_mismatch") from None


def _canonical_request(value: object) -> StrictAdmissionRequestBinding:
    try:
        if not isinstance(value, StrictAdmissionRequestBinding):
            raise TypeError
        fields = value.model_dump(mode="python", round_trip=True, warnings=False)
        return StrictAdmissionRequestBinding.model_validate(fields)
    except Exception:
        raise AdmissionPolicyDenied("invalid_admission_request") from None


def _load_envelope(payload: bytes) -> ApprovalEnvelope:
    try:
        raw = json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
        if type(raw) is not dict:
            raise ValueError("approval envelope must be a mapping")
        _validate_exact_raw_mvp_plan(raw.get("payload"))
        return ApprovalEnvelope.model_validate(raw)
    except (json.JSONDecodeError, UnicodeError, TypeError, ValueError, ValidationError):
        raise AdmissionPolicyDenied("invalid_admission_artifact") from None


class _MvpAdmissionVerifier:
    """Stateless adapter selected only by the 027 code-owned composition root."""

    __slots__ = ()

    def verify(
        self,
        request: StrictAdmissionRequestBinding,
        /,
    ) -> VerifiedAdmission:
        request = _canonical_request(request)
        if (request.expected_purpose, request.expected_run_schema_version) != (
            MVP_PURPOSE,
            MVP_RUN_SCHEMA_VERSION,
        ):
            raise AdmissionPolicyDenied("unknown_admission_profile")
        payload = _read_external_artifact(
            request.expected_admission_artifact_ref,
            request.expected_admission_artifact_digest,
        )
        if hashlib.sha256(payload).hexdigest() != (request.expected_admission_artifact_digest):
            raise AdmissionPolicyDenied("admission_artifact_digest_mismatch")
        envelope = _load_envelope(payload)
        if envelope.signature_domain != MVP_SIGNATURE_DOMAIN:
            raise AdmissionPolicyDenied("approval_domain_mismatch")
        plan = validate_mvp_plan(envelope.payload)
        policy = trust_policy.load_root_trust_policy()
        trust_policy.verify_human_approval(policy, envelope)
        checked_at = datetime.now(UTC)
        if plan.expires_at <= checked_at:
            raise AdmissionPolicyDenied("admission_expired")
        actual = _verify_current_content(plan)
        verified_at = datetime.now(UTC)
        if plan.expires_at <= verified_at:
            raise AdmissionPolicyDenied("admission_expired")
        binding = AdmissionBinding(
            actual_purpose=plan.purpose,
            actual_run_schema_version=plan.run_schema_version,
            actual_run_id=plan.run_id,
            actual_run_revision=str(actual["run_revision"]),
            actual_space_id=plan.space_id,
            actual_admission_artifact_ref=request.expected_admission_artifact_ref,
            actual_admission_artifact_digest=hashlib.sha256(payload).hexdigest(),
            actual_manifest_hash=str(actual["manifest_hash"]),
            actual_eligibility_hash=str(actual["eligibility_hash"]),
            actual_golden_slice_hash=str(actual["golden_slice_hash"]),
            actual_routing_policy_hash=str(actual["routing_policy_hash"]),
            actual_schema_hash=str(actual["schema_hash"]),
            actual_template_lock_hash=str(actual["template_lock_hash"]),
            actual_structured_dispatch_hash=str(actual["structured_dispatch_hash"]),
            actual_model_plan_hash=str(actual["model_plan_hash"]),
            actual_deployment_roles_hash=str(actual["deployment_roles_hash"]),
            actual_resource_caps_hash=str(actual["resource_caps_hash"]),
            actual_rights_hash=str(actual["rights_hash"]),
            actual_provenance_hash=str(actual["provenance_hash"]),
            actual_clean_integration_sha=str(actual["clean_integration_sha"]),
            actual_state="READY",
            actual_expires_at=plan.expires_at,
            approved_identities=plan.approved_identities,
            approved_template_hashes=plan.approved_template_hashes,
        )
        return _issue_verified_admission(
            request,
            binding,
            verifier_id=_VERIFIER_ID,
            verifier_version=_VERIFIER_VERSION,
            verified_at=verified_at,
        )


def select_canonical_admission_verifier(
    purpose: str,
    run_schema_version: str,
    /,
) -> AdmissionVerifier:
    """Select only the code-owned MVP profile; no caller object is accepted."""

    if type(purpose) is not str or type(run_schema_version) is not str:
        raise AdmissionPolicyDenied("unknown_admission_profile")
    if (purpose, run_schema_version) != (MVP_PURPOSE, MVP_RUN_SCHEMA_VERSION):
        raise AdmissionPolicyDenied("unknown_admission_profile")
    return _MvpAdmissionVerifier()


def evaluate_admission(request: StrictAdmissionRequestBinding, /) -> AdmissionDecision:
    """Return a serializable typed decision; it never carries process authority."""

    try:
        canonical = _canonical_request(request)
        verifier = select_canonical_admission_verifier(
            canonical.expected_purpose,
            canonical.expected_run_schema_version,
        )
        verified = verifier.verify(canonical)
        return AdmissionDecision(
            state="READY",
            reason_code="verified",
            verified_binding_digest=verified.verified_binding_digest,
        )
    except AdmissionPolicyDenied as exc:
        return AdmissionDecision(
            state="BLOCKED",
            reason_code=exc.reason_code,
            verified_binding_digest=None,
        )


__all__ = ["evaluate_admission", "select_canonical_admission_verifier"]
