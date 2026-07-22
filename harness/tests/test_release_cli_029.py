"""OpenSpec 029 RA7: human-controlled release governance CLI."""

import ast
import copy
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

import insurance_harness.knowledge.release_cli as release_cli
from insurance_harness.knowledge.release_approval import AuthorizationDecision
from insurance_harness.knowledge.release_boundary import (
    build_fresh_staging_candidate_manifest,
    canonical_target_facts_hash,
)
from insurance_harness.knowledge.release_manifest import ReleaseManifestBuildError
from insurance_harness.knowledge.serving import ApprovedSnapshotResult, ServingFailure
from insurance_harness.knowledge.snapshots import build_snapshot_facts
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    ClaimRevision,
    CurrentRelease,
    ReleaseManifestRecord,
    ReleaseSnapshot,
    ReviewItem,
)
from tests.support.release_018 import NOW, release_claim, release_product, release_scope
from tests.test_serving_reader_029 import _approved_release, _reader


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_compilation_bundle(
    root: Path,
    *,
    space_id: str = "space-a",
    change_set_ids: list[str] | None = None,
    blocking_review_ids: list[str] | None = None,
    target_claim_revisions: list[dict[str, object]] | None = None,
    change_items: list[dict[str, object]] | None = None,
    base_snapshot_id: str | None = None,
    base_manifest_hash: str | None = None,
    target_facts_hash: str | None = None,
) -> tuple[Path, dict[str, object]]:
    root.mkdir()
    artifact = root / "compiler-facts.json"
    artifact.write_text('[{"id":"one"},{"id":"two"}]', encoding="utf-8")
    raw = artifact.read_bytes()
    exact_change_set_ids = change_set_ids or ["change-set-1"]
    exact_change_items = change_items or [
        {
            "change_set_id": exact_change_set_ids[0],
            "change_item_id": "change-item-1",
            "claim_id": None,
            "action": "add",
            "decision": "rejected",
        }
    ]
    payload: dict[str, object] = {
        "schema_version": "028-minimal-v1",
        "space_id": space_id,
        "compiled_at": "2026-07-22T00:00:00+00:00",
        "files": [
            {
                "path": artifact.name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
                "item_count": 2,
            }
        ],
        "change_set_ids": exact_change_set_ids,
        "blocking_review_ids": blocking_review_ids or ["review-1"],
        "base_snapshot_id": base_snapshot_id,
        "base_manifest_hash": base_manifest_hash,
        "target_claim_revisions": target_claim_revisions or [],
        "target_facts_hash": target_facts_hash or _canonical_hash([]),
        "change_items": exact_change_items,
    }
    manifest = {**payload, "manifest_hash": _canonical_hash(payload)}
    path = root / "compilation-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


def test_ra7_release_governance_cli_module_exists() -> None:
    assert importlib.util.find_spec("insurance_harness.knowledge.release_cli") is not None


def test_ra7_parser_exposes_exact_governance_commands_and_arguments() -> None:
    parser = release_cli._build_parser()
    cases = {
        "apply-review-decisions": (
            "--request",
            "review.yaml",
            "--compilation-manifest",
            "compilation.json",
            "--output",
            "receipt.json",
        ),
        "build-candidate": (
            "--run-request",
            "run.yaml",
            "--review-receipt",
            "review.json",
            "--output-dir",
            "candidate",
        ),
        "approve-manifest": (
            "--request",
            "approval.yaml",
            "--manifest",
            "release.json",
            "--output",
            "approval.json",
        ),
        "promote-approved": (
            "--request",
            "approval.yaml",
            "--manifest",
            "release.json",
            "--approval-receipt",
            "approval.json",
            "--output",
            "release-proof.json",
        ),
        "seal-run-artifacts": (
            "--directory",
            "run",
            "--compilation-manifest",
            "compilation.json",
            "--release-proof",
            "release-proof.json",
            "--serving-proof",
            "serving-proof.json",
        ),
    }
    for command, arguments in cases.items():
        parsed = parser.parse_args([command, *arguments])
        assert parsed.command == command
    subparsers = next(
        action for action in parser._actions if hasattr(action, "choices") and action.choices
    )
    assert set(subparsers.choices) == set(cases)


def test_ra7_cli_architecture_has_no_compiler_runtime_model_or_process_path() -> None:
    tree = ast.parse(inspect.getsource(release_cli))
    forbidden_parts = {
        "compiler",
        "runtime",
        "stage",
        "model",
        "model_policy",
        "provider",
        "subprocess",
        "node",
        "typescript",
    }
    imported = {
        part
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for part in (node.module or "").split(".")
    } | {
        part
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        for part in alias.name.split(".")
    }
    assert imported.isdisjoint(forbidden_parts)
    forbidden_calls = {
        "ModelGateway",
        "Popen",
        "call",
        "check_call",
        "check_output",
        "run",
        "system",
    }
    assert not {
        getattr(node.func, "id", getattr(node.func, "attr", ""))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    } & forbidden_calls


def test_ra7_human_requests_are_strict_explicit_and_never_self_authorizing() -> None:
    review = {
        "input_origin": "human-authored",
        "space_id": "space-a",
        "compilation_manifest_hash": "a" * 64,
        "decisions": [
            {
                "review_id": "review-1",
                "expected_version": "2026-07-22T00:00:00+00:00",
                "action": "approve",
                "principal": "alice",
                "actor_type": "human",
                "authorization_receipt": "review-auth-1",
                "reason": "inspected source evidence",
                "request_id": "request-1",
            }
        ],
    }
    parsed_review = release_cli.ReviewDecisionsRequest.model_validate(review)
    assert parsed_review.decisions[0].action == "approve"
    for field, value in (
        ("input_origin", "generated-default"),
        ("decisions", [{**review["decisions"][0], "actor_type": "service"}]),
        ("decisions", [{**review["decisions"][0], "action": "defer"}]),
    ):
        with pytest.raises(ValidationError):
            release_cli.ReviewDecisionsRequest.model_validate({**review, field: value})

    approval = {
        "input_origin": "human-authored",
        "space_id": "space-a",
        "manifest_hash": "b" * 64,
        "snapshot_id": "snapshot-a",
        "expected_current_snapshot_id": None,
        "principal": "release-owner",
        "actor_type": "human",
        "authorization_receipt": "release-auth-1",
        "reason": "inspected complete manifest",
    }
    parsed_approval = release_cli.ReleaseApprovalRequest.model_validate(approval)
    assert parsed_approval.expected_current_snapshot_id is None
    for missing in (
        "manifest_hash",
        "snapshot_id",
        "expected_current_snapshot_id",
        "principal",
        "authorization_receipt",
        "reason",
    ):
        invalid = dict(approval)
        invalid.pop(missing)
        with pytest.raises(ValidationError):
            release_cli.ReleaseApprovalRequest.model_validate(invalid)


def test_ra7_shell_without_trusted_context_is_typed_blocked_and_zero_write(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "receipt.json"
    exit_code = release_cli.main(
        [
            "apply-review-decisions",
            "--request",
            str(tmp_path / "request.yaml"),
            "--compilation-manifest",
            str(tmp_path / "compilation.json"),
            "--output",
            str(output),
        ]
    )
    assert exit_code == 2
    assert not output.exists()
    failure = json.loads(capsys.readouterr().err)
    assert failure == {
        "code": "trusted_context_required",
        "status": "blocked",
    }


def test_ra7_compilation_manifest_revalidates_path_hash_size_and_count(
    tmp_path: Path,
) -> None:
    manifest_path, manifest = _write_compilation_bundle(tmp_path / "bundle")
    loaded = release_cli.load_compilation_manifest(manifest_path)
    assert loaded.manifest_hash == manifest["manifest_hash"]

    artifact = manifest_path.parent / "compiler-facts.json"
    original = artifact.read_text(encoding="utf-8")
    for mutation in (
        original + "\n",
        '[{"id":"one"}]',
        '[{"id":"one"},{"id":"changed"}]',
    ):
        artifact.write_text(mutation, encoding="utf-8")
        with pytest.raises(release_cli.ReleaseCLIError) as caught:
            release_cli.load_compilation_manifest(manifest_path)
        assert caught.value.code == "compilation_artifact_mismatch"
    artifact.write_text(original, encoding="utf-8")

    escaped = dict(manifest)
    escaped["files"] = [{**manifest["files"][0], "path": "../escape.json"}]
    escaped_payload = {key: value for key, value in escaped.items() if key != "manifest_hash"}
    escaped["manifest_hash"] = _canonical_hash(escaped_payload)
    manifest_path.write_text(json.dumps(escaped), encoding="utf-8")
    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.load_compilation_manifest(manifest_path)
    assert caught.value.code == "unsafe_artifact_path"


def test_ra7_compilation_manifest_rejects_duplicates_symlinks_and_sensitive_files(
    tmp_path: Path,
) -> None:
    manifest_path, manifest = _write_compilation_bundle(tmp_path / "bundle")
    duplicate = dict(manifest)
    duplicate["files"] = [manifest["files"][0], manifest["files"][0]]
    duplicate_payload = {key: value for key, value in duplicate.items() if key != "manifest_hash"}
    duplicate["manifest_hash"] = _canonical_hash(duplicate_payload)
    manifest_path.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises((release_cli.ReleaseCLIError, ValidationError)):
        release_cli.load_compilation_manifest(manifest_path)

    manifest_path, manifest = _write_compilation_bundle(tmp_path / "symlink-bundle")
    target = manifest_path.parent / "compiler-facts.json"
    link = manifest_path.parent / "linked.json"
    link.symlink_to(target)
    raw = target.read_bytes()
    payload = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    payload["files"] = [
        {
            "path": "linked.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "item_count": 2,
        }
    ]
    manifest_path.write_text(
        json.dumps({**payload, "manifest_hash": _canonical_hash(payload)}),
        encoding="utf-8",
    )
    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.load_compilation_manifest(manifest_path)
    assert caught.value.code == "unsafe_artifact_path"


class _ReviewAuthorizer:
    def authorize_review(self, **kwargs: Any) -> release_cli.ReviewAuthorizationDecision:
        return release_cli.ReviewAuthorizationDecision(
            outcome="authorized",
            space_id=kwargs["space_id"],
            review_id=kwargs["review_id"],
            principal=kwargs["principal"],
            actor_type=kwargs["actor_type"],
            compilation_manifest_hash=kwargs["compilation_manifest_hash"],
            authorization_receipt=kwargs["authorization_receipt"],
        )


class _ReleaseAuthorizer:
    def authorize(self, **kwargs: Any) -> Any:
        return AuthorizationDecision(
            outcome="authorized",
            space_id=kwargs["space_id"],
            actor=kwargs["actor"],
            actor_type=kwargs["actor_type"],
            role=kwargs["role"],
            manifest_hash=kwargs["manifest_hash"],
            authorization_receipt=kwargs["authorization_receipt"],
        )


def _seed_blocking_review(session: Session) -> tuple[object, ChangeSet, ReviewItem]:
    scope = release_scope(session, "release-cli-review")
    change_set = ChangeSet(
        space_id=scope.space_id,
        source_kind="document",
        knowledge_ids=["knowledge-1"],
        external_record_id="record-1",
        source_revision="revision-1",
        status="pending",
        created_by="compiler",
    )
    session.add(change_set)
    session.flush()
    item = ChangeItem(
        change_set_id=change_set.id,
        action="add",
        claim_id=None,
        proposed={"candidate": "one"},
        decision="needs_review",
        decision_basis=None,
    )
    session.add(item)
    session.flush()
    review = ReviewItem(
        space_id=scope.space_id,
        review_key="rv-release-cli-1",
        type="change_item",
        subject={"change_item_id": item.id},
        allowed_actions=["approve", "reject", "defer"],
        status="open",
        resolution=None,
        risk_level="high",
    )
    session.add(review)
    session.flush()
    return scope, change_set, review


def test_ra7_apply_review_decisions_uses_exact_human_request_and_existing_service(
    session: Session,
    tmp_path: Path,
) -> None:
    scope, change_set, review = _seed_blocking_review(session)
    bundle = tmp_path / "bundle"
    compilation_path, compilation = _write_compilation_bundle(
        bundle,
        space_id=scope.space_id,
        change_set_ids=[change_set.id],
        blocking_review_ids=[review.id],
    )
    request = {
        "input_origin": "human-authored",
        "space_id": scope.space_id,
        "compilation_manifest_hash": compilation["manifest_hash"],
        "decisions": [
            {
                "review_id": review.id,
                "expected_version": review.updated_at.isoformat(),
                "action": "reject",
                "principal": "alice",
                "actor_type": "human",
                "authorization_receipt": "review-auth-exact",
                "reason": "inspected exact evidence",
                "request_id": "review-request-exact",
            }
        ],
    }
    request_path = tmp_path / "review-decisions.yaml"
    request_path.write_text(release_cli.dump_yaml(request), encoding="utf-8")
    output = tmp_path / "review-receipt.json"
    context = release_cli.GovernanceContext(
        session=session,
        scope=scope,
        review_authorizer=_ReviewAuthorizer(),
        release_authorizer=None,
    )
    before_current = session.scalar(select(func.count()).select_from(CurrentRelease))

    receipt = release_cli.apply_review_decisions(
        context,
        request_path=request_path,
        compilation_manifest_path=compilation_path,
        output_path=output,
    )

    assert receipt.compilation_manifest_hash == compilation["manifest_hash"]
    assert receipt.decisions[0].review_id == review.id
    assert receipt.decisions[0].action == "reject"
    assert output.exists()
    session.refresh(review)
    assert review.status == "resolved"
    assert review.resolution["actor"] == "alice"
    assert session.scalar(select(func.count()).select_from(CurrentRelease)) == before_current


def test_ra7_apply_review_decisions_fails_before_write_on_hash_or_version_mismatch(
    session: Session,
    tmp_path: Path,
) -> None:
    scope, change_set, review = _seed_blocking_review(session)
    compilation_path, compilation = _write_compilation_bundle(
        tmp_path / "bundle",
        space_id=scope.space_id,
        change_set_ids=[change_set.id],
        blocking_review_ids=[review.id],
    )
    base = {
        "input_origin": "human-authored",
        "space_id": scope.space_id,
        "compilation_manifest_hash": "f" * 64,
        "decisions": [
            {
                "review_id": review.id,
                "expected_version": review.updated_at.isoformat(),
                "action": "reject",
                "principal": "alice",
                "actor_type": "human",
                "authorization_receipt": "review-auth-exact",
                "reason": "inspected exact evidence",
                "request_id": "review-request-exact",
            }
        ],
    }
    request_path = tmp_path / "review.yaml"
    request_path.write_text(release_cli.dump_yaml(base), encoding="utf-8")
    output = tmp_path / "receipt.json"
    context = release_cli.GovernanceContext(session, scope, _ReviewAuthorizer(), None)
    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.apply_review_decisions(
            context,
            request_path=request_path,
            compilation_manifest_path=compilation_path,
            output_path=output,
        )
    assert caught.value.code == "review_request_mismatch"
    assert not output.exists()
    session.refresh(review)
    assert review.status == "open"

    base["compilation_manifest_hash"] = compilation["manifest_hash"]
    base["decisions"][0]["expected_version"] = "stale-version"
    request_path.write_text(release_cli.dump_yaml(base), encoding="utf-8")
    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.apply_review_decisions(
            context,
            request_path=request_path,
            compilation_manifest_path=compilation_path,
            output_path=output,
        )
    assert caught.value.code == "review_stale"
    assert not output.exists()
    session.refresh(review)
    assert review.status == "open"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("absent", "unsafe_artifact_path"),
        ("generated-default", "invalid_review_request"),
        ("service-authored", "invalid_review_request"),
        ("model-authored", "invalid_review_request"),
        ("stale", "review_stale"),
        ("wrong-space", "review_request_mismatch"),
        ("wrong-hash", "review_request_mismatch"),
        ("incomplete-blockers", "review_request_mismatch"),
    ],
)
def test_ra7_apply_review_negative_matrix_is_zero_write(
    session: Session,
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    scope, change_set, review = _seed_blocking_review(session)
    blockers = [review.id]
    if mutation == "incomplete-blockers":
        blockers.append("unrepresented-review")
    compilation_path, compilation = _write_compilation_bundle(
        tmp_path / "bundle",
        space_id=scope.space_id,
        change_set_ids=[change_set.id],
        blocking_review_ids=blockers,
    )
    decision = {
        "review_id": review.id,
        "expected_version": review.updated_at.isoformat(),
        "action": "reject",
        "principal": "alice",
        "actor_type": "human",
        "authorization_receipt": "review-auth-matrix",
        "reason": "inspected exact evidence",
        "request_id": "review-request-matrix",
    }
    request: dict[str, object] = {
        "input_origin": "human-authored",
        "space_id": scope.space_id,
        "compilation_manifest_hash": compilation["manifest_hash"],
        "decisions": [decision],
    }
    if mutation == "generated-default":
        request.pop("input_origin")
    elif mutation == "service-authored":
        decision["actor_type"] = "service"
    elif mutation == "model-authored":
        decision["actor_type"] = "model"
    elif mutation == "stale":
        decision["expected_version"] = "stale"
    elif mutation == "wrong-space":
        request["space_id"] = "other-space"
    elif mutation == "wrong-hash":
        request["compilation_manifest_hash"] = "f" * 64
    request_path = tmp_path / "missing.yaml"
    if mutation != "absent":
        request_path.write_text(release_cli.dump_yaml(request), encoding="utf-8")
    output = tmp_path / "receipt.json"

    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.apply_review_decisions(
            release_cli.GovernanceContext(
                session, scope, _ReviewAuthorizer(), None
            ),
            request_path=request_path,
            compilation_manifest_path=compilation_path,
            output_path=output,
        )

    assert caught.value.code == expected_code
    assert not output.exists()
    session.refresh(review)
    assert review.status == "open"


def _write_resolved_review_bundle(
    session: Session,
    tmp_path: Path,
) -> tuple[object, str, Path, Path]:
    approved = _approved_release(session, "release-cli-candidate")
    scope = approved.scope
    snapshot_id = "snapshot-release-cli-candidate-new"
    change_set = ChangeSet(
        space_id=scope.space_id,
        source_kind="document",
        knowledge_ids=["knowledge-candidate"],
        external_record_id="candidate-record",
        source_revision="candidate-revision",
        status="pending",
        created_by="compiler",
    )
    session.add(change_set)
    session.flush()
    item = ChangeItem(
        change_set_id=change_set.id,
        action="add",
        claim_id=None,
        proposed={"candidate": "rejected"},
        decision="needs_review",
        decision_basis=None,
    )
    session.add(item)
    session.flush()
    review = ReviewItem(
        space_id=scope.space_id,
        review_key="rv-release-cli-candidate",
        type="change_item",
        subject={"change_item_id": item.id},
        allowed_actions=["approve", "reject", "defer"],
        status="open",
        resolution=None,
        risk_level="high",
    )
    session.add(review)
    session.flush()
    compilation_path, compilation = _write_compilation_bundle(
        tmp_path / "bundle",
        space_id=scope.space_id,
        change_set_ids=[change_set.id],
        blocking_review_ids=[review.id],
        target_claim_revisions=[
            {"claim_id": fact.claim_id, "revision_no": fact.revision_no}
            for fact in approved.manifest.facts
        ],
        change_items=[
            {
                "change_set_id": change_set.id,
                "change_item_id": item.id,
                "claim_id": None,
                "action": "add",
                "decision": "rejected",
            }
        ],
        base_snapshot_id=approved.manifest.snapshot_id,
        base_manifest_hash=approved.manifest.manifest_sha256,
        target_facts_hash=canonical_target_facts_hash(
            build_snapshot_facts(session, scope, snapshot_id=snapshot_id)
        ),
    )
    decision = {
        "review_id": review.id,
        "review_key": review.review_key,
        "change_set_id": change_set.id,
        "change_item_id": item.id,
        "expected_version": review.updated_at.isoformat(),
        "action": "reject",
        "principal": "alice",
        "actor_type": "human",
        "authorization_receipt": "review-auth-candidate",
        "reason": "inspected exact evidence",
        "request_id": "review-request-candidate",
        "resolved_at": "2026-07-22T00:00:00+00:00",
    }
    request_payload: dict[str, object] = {
        "input_origin": "human-authored",
        "space_id": scope.space_id,
        "compilation_manifest_hash": compilation["manifest_hash"],
        "decisions": [
            {
                key: value
                for key, value in decision.items()
                if key
                in {
                    "review_id",
                    "expected_version",
                    "action",
                    "principal",
                    "actor_type",
                    "authorization_receipt",
                    "reason",
                    "request_id",
                }
            }
        ],
    }
    receipt_path = tmp_path / "review-receipt.json"
    request_path = tmp_path / "review-decisions.yaml"
    request_path.write_text(release_cli.dump_yaml(request_payload), encoding="utf-8")
    release_cli.apply_review_decisions(
        release_cli.GovernanceContext(
            session, scope, _ReviewAuthorizer(), _ReleaseAuthorizer()
        ),
        request_path=request_path,
        compilation_manifest_path=compilation_path,
        output_path=receipt_path,
    )
    change_set.status = "rejected"
    session.flush()
    return scope, snapshot_id, compilation_path, receipt_path


def test_ra7_candidate_approval_and_promote_are_separate_exact_steps(
    session: Session,
    tmp_path: Path,
) -> None:
    scope, snapshot_id, compilation_path, review_receipt_path = (
        _write_resolved_review_bundle(session, tmp_path)
    )
    compilation = release_cli.load_compilation_manifest(compilation_path)
    review_receipt = release_cli.load_review_receipt(review_receipt_path)
    request_payload = {
        "schema_version": "candidate-run-request-v1",
        "space_id": scope.space_id,
        "compilation_manifest_path": "bundle/compilation-manifest.json",
        "compilation_manifest_hash": compilation.manifest_hash,
        "review_receipt_hash": review_receipt.receipt_hash,
        "snapshot_id": snapshot_id,
        "knowledge_schema_version": "v1.1+release",
        "template_hashes": ["d" * 64],
        "model_plan_hash": "e" * 64,
    }
    request_path = tmp_path / "run-request.yaml"
    request_path.write_text(release_cli.dump_yaml(request_payload), encoding="utf-8")
    candidate_dir = tmp_path / "candidate"
    context = release_cli.GovernanceContext(
        session,
        scope,
        _ReviewAuthorizer(),
        _ReleaseAuthorizer(),
    )
    before_current = session.scalar(select(func.count()).select_from(CurrentRelease))

    candidate = release_cli.build_candidate(
        context,
        run_request_path=request_path,
        review_receipt_path=review_receipt_path,
        output_dir=candidate_dir,
    )

    assert candidate.snapshot_id == snapshot_id
    assert (candidate_dir / "candidate-snapshot.json").exists()
    manifest_path = candidate_dir / "release-manifest.json"
    assert manifest_path.exists()
    assert session.scalar(select(func.count()).select_from(CurrentRelease)) == before_current

    approval_request = {
        "input_origin": "human-authored",
        "space_id": scope.space_id,
        "manifest_hash": candidate.manifest_hash,
        "snapshot_id": snapshot_id,
        "expected_current_snapshot_id": compilation.base_snapshot_id,
        "principal": "release-owner",
        "actor_type": "human",
        "authorization_receipt": "release-auth-exact",
        "reason": "inspected complete release manifest",
    }
    approval_request_path = tmp_path / "release-approval-request.yaml"
    approval_request_path.write_text(
        release_cli.dump_yaml(approval_request), encoding="utf-8"
    )
    approval_output = tmp_path / "approval-receipt.json"
    approval = release_cli.approve_manifest(
        context,
        request_path=approval_request_path,
        manifest_path=manifest_path,
        output_path=approval_output,
    )
    assert approval.manifest_hash == candidate.manifest_hash
    assert approval.created_at
    assert session.scalar(select(func.count()).select_from(CurrentRelease)) == before_current

    release_output = tmp_path / "release-proof.json"
    proof = release_cli.promote_approved(
        context,
        request_path=approval_request_path,
        manifest_path=manifest_path,
        approval_receipt_path=approval_output,
        output_path=release_output,
    )
    assert proof.snapshot_id == snapshot_id
    assert proof.audit_created_at
    assert session.get(CurrentRelease, (scope.space_id, "current")).snapshot_id == snapshot_id


def test_ra7_build_candidate_rejects_mutated_compiler_artifact_without_output(
    session: Session,
    tmp_path: Path,
) -> None:
    scope, snapshot_id, compilation_path, review_receipt_path = (
        _write_resolved_review_bundle(session, tmp_path)
    )
    compilation = release_cli.load_compilation_manifest(compilation_path)
    receipt = release_cli.load_review_receipt(review_receipt_path)
    run_request = {
        "schema_version": "candidate-run-request-v1",
        "space_id": scope.space_id,
        "compilation_manifest_path": "bundle/compilation-manifest.json",
        "compilation_manifest_hash": compilation.manifest_hash,
        "review_receipt_hash": receipt.receipt_hash,
        "snapshot_id": snapshot_id,
        "knowledge_schema_version": "v1.1+release",
        "template_hashes": ["d" * 64],
        "model_plan_hash": "e" * 64,
    }
    request_path = tmp_path / "run.yaml"
    request_path.write_text(release_cli.dump_yaml(run_request), encoding="utf-8")
    (compilation_path.parent / "compiler-facts.json").write_text("[]", encoding="utf-8")
    output = tmp_path / "candidate"
    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.build_candidate(
            release_cli.GovernanceContext(
                session, scope, _ReviewAuthorizer(), _ReleaseAuthorizer()
            ),
            run_request_path=request_path,
            review_receipt_path=review_receipt_path,
            output_dir=output,
        )
    assert caught.value.code == "compilation_artifact_mismatch"
    assert not output.exists()


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("unresolved", "review_receipt_mismatch"),
        ("deferred", "review_receipt_mismatch"),
        ("incomplete-changeset", "changeset_coverage_incomplete"),
        ("wrong-receipt", "review_receipt_mismatch"),
        ("existing-output", "output_exists"),
    ],
)
def test_ra7_candidate_negative_matrix_is_zero_write(
    session: Session,
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    scope, snapshot_id, compilation_path, review_receipt_path = (
        _write_resolved_review_bundle(session, tmp_path)
    )
    compilation = release_cli.load_compilation_manifest(compilation_path)
    receipt = release_cli.load_review_receipt(review_receipt_path)
    review = session.scalar(
        select(ReviewItem).where(ReviewItem.space_id == scope.space_id)
    )
    assert review is not None
    item = session.get(ChangeItem, review.subject["change_item_id"])
    assert item is not None
    if mutation == "unresolved":
        review.status = "open"
        review.resolution = None
        item.decision = "needs_review"
        session.flush()
    elif mutation == "deferred":
        review.resolution = {**review.resolution, "action": "defer"}
        session.flush()
    elif mutation == "incomplete-changeset":
        session.add(
            ChangeItem(
                change_set_id=item.change_set_id,
                action="add",
                claim_id=None,
                proposed={"candidate": "unresolved"},
                decision="needs_review",
                decision_basis=None,
            )
        )
        session.flush()
    elif mutation == "wrong-receipt":
        raw = json.loads(review_receipt_path.read_text(encoding="utf-8"))
        raw["compilation_manifest_hash"] = "f" * 64
        payload = {key: value for key, value in raw.items() if key != "receipt_hash"}
        raw["receipt_hash"] = _canonical_hash(payload)
        review_receipt_path.write_text(json.dumps(raw), encoding="utf-8")
        receipt = release_cli.load_review_receipt(review_receipt_path)
    request = {
        "schema_version": "candidate-run-request-v1",
        "space_id": scope.space_id,
        "compilation_manifest_path": "bundle/compilation-manifest.json",
        "compilation_manifest_hash": compilation.manifest_hash,
        "review_receipt_hash": receipt.receipt_hash,
        "snapshot_id": snapshot_id,
        "knowledge_schema_version": "v1.1+release",
        "template_hashes": ["d" * 64],
        "model_plan_hash": "e" * 64,
    }
    request_path = tmp_path / "candidate-matrix.yaml"
    request_path.write_text(release_cli.dump_yaml(request), encoding="utf-8")
    output = tmp_path / "candidate-output"
    if mutation == "existing-output":
        output.mkdir()
    current_before = session.scalar(select(func.count()).select_from(CurrentRelease))

    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.build_candidate(
            release_cli.GovernanceContext(
                session, scope, _ReviewAuthorizer(), _ReleaseAuthorizer()
            ),
            run_request_path=request_path,
            review_receipt_path=review_receipt_path,
            output_dir=output,
        )

    assert caught.value.code == expected_code
    assert session.scalar(select(func.count()).select_from(CurrentRelease)) == current_before
    if mutation != "existing-output":
        assert not output.exists()


def _write_approved_run(
    session: Session,
    root: Path,
) -> tuple[release_cli.GovernanceContext, Path, Path, Path, Path]:
    root = root / "run"
    root.mkdir()
    scope, snapshot_id, compilation_path, review_receipt_path = (
        _write_resolved_review_bundle(session, root)
    )
    compilation = release_cli.load_compilation_manifest(compilation_path)
    review_receipt = release_cli.load_review_receipt(review_receipt_path)
    review_request = {
        "input_origin": "human-authored",
        "space_id": scope.space_id,
        "compilation_manifest_hash": compilation.manifest_hash,
        "decisions": [
            {
                key: getattr(decision, key)
                for key in (
                    "review_id",
                    "expected_version",
                    "action",
                    "principal",
                    "actor_type",
                    "authorization_receipt",
                    "reason",
                    "request_id",
                )
            }
            for decision in review_receipt.decisions
        ],
    }
    (root / "review-decisions.yaml").write_text(
        release_cli.dump_yaml(review_request), encoding="utf-8"
    )
    request_payload = {
        "schema_version": "candidate-run-request-v1",
        "space_id": scope.space_id,
        "compilation_manifest_path": "bundle/compilation-manifest.json",
        "compilation_manifest_hash": compilation.manifest_hash,
        "review_receipt_hash": review_receipt.receipt_hash,
        "snapshot_id": snapshot_id,
        "knowledge_schema_version": "v1.1+release",
        "template_hashes": ["d" * 64],
        "model_plan_hash": "e" * 64,
    }
    run_request = root / "run-request.yaml"
    run_request.write_text(release_cli.dump_yaml(request_payload), encoding="utf-8")
    context = release_cli.GovernanceContext(
        session, scope, _ReviewAuthorizer(), _ReleaseAuthorizer(), _reader(session)
    )
    candidate_dir = root / "candidate"
    candidate = release_cli.build_candidate(
        context,
        run_request_path=run_request,
        review_receipt_path=review_receipt_path,
        output_dir=candidate_dir,
    )
    approval_payload = {
        "input_origin": "human-authored",
        "space_id": scope.space_id,
        "manifest_hash": candidate.manifest_hash,
        "snapshot_id": snapshot_id,
        "expected_current_snapshot_id": compilation.base_snapshot_id,
        "principal": "release-owner",
        "actor_type": "human",
        "authorization_receipt": "release-auth-seal",
        "reason": "inspected complete release manifest",
    }
    approval_request = root / "release-approval-request.yaml"
    approval_request.write_text(
        release_cli.dump_yaml(approval_payload), encoding="utf-8"
    )
    approval_receipt = root / "approval-receipt.json"
    release_cli.approve_manifest(
        context,
        request_path=approval_request,
        manifest_path=candidate_dir / "release-manifest.json",
        output_path=approval_receipt,
    )
    return (
        context,
        compilation_path,
        approval_request,
        candidate_dir / "release-manifest.json",
        approval_receipt,
    )


def _write_promoted_run(
    session: Session,
    root: Path,
) -> tuple[release_cli.GovernanceContext, Path, Path, Path]:
    context, compilation_path, approval_request, manifest_path, approval_receipt = (
        _write_approved_run(session, root)
    )
    root = manifest_path.parent.parent
    release_proof = root / "release-proof.json"
    proof = release_cli.promote_approved(
        context,
        request_path=approval_request,
        manifest_path=manifest_path,
        approval_receipt_path=approval_receipt,
        output_path=release_proof,
    )
    session.commit()
    manifest = release_cli._load_release_manifest(manifest_path)
    assert context.approved_snapshot_reader is not None
    actual = context.approved_snapshot_reader.read_current(context.scope)
    assert isinstance(actual, release_cli.ApprovedSnapshotResult)
    facts_hash, evidence_hash, ordering_hash = release_cli._actual_serving_hashes(
        actual
    )
    reader = {
        "snapshot_id": proof.snapshot_id,
        "manifest_hash": proof.manifest_hash,
        "fact_count": manifest.facts_digest.count,
        "facts_hash": facts_hash,
        "evidence_hash": evidence_hash,
        "ordering_hash": ordering_hash,
    }
    serving_payload = {
        "schema_version": "serving-proof-v1",
        "space_id": context.scope.space_id,
        "snapshot_id": proof.snapshot_id,
        "manifest_hash": proof.manifest_hash,
        "human_reader": reader,
        "mcp_reader": reader,
    }
    serving_proof = root / "serving-proof.json"
    serving_proof.write_text(
        json.dumps(
            {
                **serving_payload,
                "proof_hash": _canonical_hash(serving_payload),
            }
        ),
        encoding="utf-8",
    )
    (root / "metrics.json").write_text('{"passed":true}', encoding="utf-8")
    return context, compilation_path, release_proof, serving_proof


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("missing-hash", "invalid_approval_request"),
        ("default-hash", "invalid_approval_request"),
        ("missing-principal", "invalid_approval_request"),
        ("missing-auth", "invalid_approval_request"),
        ("missing-expected-current", "invalid_approval_request"),
        ("wrong-expected-current", "approval_request_mismatch"),
        ("manifest-drift", "release_manifest_mismatch"),
    ],
)
def test_ra7_approve_negative_matrix_does_not_move_current(
    session: Session,
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    context, _, request_path, manifest_path, _ = _write_approved_run(
        session, tmp_path
    )
    current_before = session.get(
        CurrentRelease, (context.scope.space_id, "current")
    ).snapshot_id
    request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
    if mutation == "missing-hash":
        request.pop("manifest_hash")
    elif mutation == "default-hash":
        request["manifest_hash"] = ""
    elif mutation == "missing-principal":
        request.pop("principal")
    elif mutation == "missing-auth":
        request.pop("authorization_receipt")
    elif mutation == "missing-expected-current":
        request.pop("expected_current_snapshot_id")
    elif mutation == "wrong-expected-current":
        request["expected_current_snapshot_id"] = "substituted-current"
    elif mutation == "manifest-drift":
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["model_plan_hash"] = "f" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    request_path.write_text(release_cli.dump_yaml(request), encoding="utf-8")
    output = tmp_path / "second-approval.json"

    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.approve_manifest(
            context,
            request_path=request_path,
            manifest_path=manifest_path,
            output_path=output,
        )

    assert caught.value.code == expected_code
    assert not output.exists()
    assert (
        session.get(CurrentRelease, (context.scope.space_id, "current")).snapshot_id
        == current_before
    )


@pytest.mark.parametrize(
    ("mutation", "expected_code", "service_calls"),
    [
        ("stale-cas", "stale_current_release", 1),
        ("manifest-drift", "release_manifest_mismatch", 0),
        ("request-actor", "promotion_binding_mismatch", 0),
        ("request-space", "promotion_binding_mismatch", 0),
        ("substituted-receipt", "promotion_binding_mismatch", 0),
        ("forged-actor-chain", "promotion_binding_mismatch", 0),
    ],
)
def test_ra7_promote_negative_matrix_has_no_retry(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected_code: str,
    service_calls: int,
) -> None:
    context, _, request_path, manifest_path, approval_path = _write_approved_run(
        session, tmp_path
    )
    request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    if mutation == "stale-cas":
        current = session.get(CurrentRelease, (context.scope.space_id, "current"))
        assert current is not None
        current.snapshot_id = request["snapshot_id"]
        session.flush()
    elif mutation == "manifest-drift":
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["model_plan_hash"] = "f" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif mutation == "request-actor":
        request["principal"] = "substituted-actor"
        request_path.write_text(release_cli.dump_yaml(request), encoding="utf-8")
    elif mutation == "request-space":
        request["space_id"] = "other-space"
        request_path.write_text(release_cli.dump_yaml(request), encoding="utf-8")
    elif mutation == "substituted-receipt":
        approval["approval_id"] = "substituted-approval"
        payload = {key: value for key, value in approval.items() if key != "receipt_hash"}
        approval["receipt_hash"] = _canonical_hash(payload)
        approval_path.write_text(json.dumps(approval), encoding="utf-8")
    elif mutation == "forged-actor-chain":
        request["principal"] = "forged-actor"
        request_path.write_text(release_cli.dump_yaml(request), encoding="utf-8")
        approval["principal"] = "forged-actor"
        approval["request_hash"] = _canonical_hash(request)
        payload = {key: value for key, value in approval.items() if key != "receipt_hash"}
        approval["receipt_hash"] = _canonical_hash(payload)
        approval_path.write_text(json.dumps(approval), encoding="utf-8")
    original = release_cli.ReleaseAuthorityService.promote
    calls = 0

    def counted_promote(service: object, *args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(service, *args, **kwargs)

    monkeypatch.setattr(release_cli.ReleaseAuthorityService, "promote", counted_promote)
    output = tmp_path / "second-release-proof.json"
    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.promote_approved(
            context,
            request_path=request_path,
            manifest_path=manifest_path,
            approval_receipt_path=approval_path,
            output_path=output,
        )

    assert caught.value.code == expected_code
    assert calls == service_calls
    assert not output.exists()


def test_ra7_seal_revalidates_chain_and_exclusive_creates_manifest_last(
    session: Session,
    tmp_path: Path,
) -> None:
    context, compilation, release_proof, serving_proof = _write_promoted_run(
        session, tmp_path
    )
    run_dir = compilation.parent.parent

    artifact_manifest = release_cli.seal_run_artifacts(
        context,
        directory=run_dir,
        compilation_manifest_path=compilation,
        release_proof_path=release_proof,
        serving_proof_path=serving_proof,
    )

    output = run_dir / "artifact-manifest.json"
    assert output.exists()
    assert artifact_manifest.file_count == len(artifact_manifest.files)
    assert {item.path for item in artifact_manifest.files} == {
        path.relative_to(run_dir).as_posix()
        for path in run_dir.rglob("*")
        if path.is_file() and path != output
    }
    original = output.read_bytes()
    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.seal_run_artifacts(
            context,
            directory=run_dir,
            compilation_manifest_path=compilation,
            release_proof_path=release_proof,
            serving_proof_path=serving_proof,
        )
    assert caught.value.code == "artifact_manifest_exists"
    assert output.read_bytes() == original


def test_ra7_seal_rejects_reader_or_compiler_drift_before_final_write(
    session: Session,
    tmp_path: Path,
) -> None:
    context, compilation, release_proof, serving_proof = _write_promoted_run(
        session, tmp_path
    )
    run_dir = compilation.parent.parent
    proof = json.loads(serving_proof.read_text(encoding="utf-8"))
    proof["mcp_reader"]["snapshot_id"] = "wrong-snapshot"
    payload = {key: value for key, value in proof.items() if key != "proof_hash"}
    proof["proof_hash"] = _canonical_hash(payload)
    serving_proof.write_text(json.dumps(proof), encoding="utf-8")

    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.seal_run_artifacts(
            context,
            directory=run_dir,
            compilation_manifest_path=compilation,
            release_proof_path=release_proof,
            serving_proof_path=serving_proof,
        )
    assert caught.value.code == "serving_proof_mismatch"
    assert not (run_dir / "artifact-manifest.json").exists()

    proof["mcp_reader"] = proof["human_reader"]
    payload = {key: value for key, value in proof.items() if key != "proof_hash"}
    proof["proof_hash"] = _canonical_hash(payload)
    serving_proof.write_text(json.dumps(proof), encoding="utf-8")
    (compilation.parent / "compiler-facts.json").write_text("[]", encoding="utf-8")
    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.seal_run_artifacts(
            context,
            directory=run_dir,
            compilation_manifest_path=compilation,
            release_proof_path=release_proof,
            serving_proof_path=serving_proof,
        )
    assert caught.value.code == "compilation_artifact_mismatch"
    assert not (run_dir / "artifact-manifest.json").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "outer-snapshot",
        "outer-manifest",
        "human-snapshot",
        "human-manifest",
        "human-facts",
        "human-evidence",
        "human-ordering",
        "mcp-snapshot",
        "mcp-manifest",
        "mcp-facts",
        "mcp-evidence",
        "mcp-ordering",
        "both-evidence",
        "both-ordering",
    ],
)
def test_ra7_seal_rejects_every_serving_identity_drift(
    session: Session,
    tmp_path: Path,
    mutation: str,
) -> None:
    context, compilation, release_proof, serving_proof = _write_promoted_run(
        session, tmp_path
    )
    run_dir = compilation.parent.parent
    proof = json.loads(serving_proof.read_text(encoding="utf-8"))
    bad_hash = "f" * 64
    if mutation == "outer-snapshot":
        proof["snapshot_id"] = "wrong-snapshot"
    elif mutation == "outer-manifest":
        proof["manifest_hash"] = bad_hash
    elif mutation == "both-evidence":
        proof["human_reader"]["evidence_hash"] = bad_hash
        proof["mcp_reader"]["evidence_hash"] = bad_hash
    elif mutation == "both-ordering":
        proof["human_reader"]["ordering_hash"] = bad_hash
        proof["mcp_reader"]["ordering_hash"] = bad_hash
    else:
        reader_name, field = mutation.split("-", maxsplit=1)
        reader = proof[f"{reader_name}_reader"]
        if field == "snapshot":
            reader["snapshot_id"] = "wrong-snapshot"
        elif field == "manifest":
            reader["manifest_hash"] = bad_hash
        elif field == "facts":
            reader["facts_hash"] = bad_hash
        elif field == "evidence":
            reader["evidence_hash"] = bad_hash
        elif field == "ordering":
            reader["ordering_hash"] = bad_hash
    payload = {key: value for key, value in proof.items() if key != "proof_hash"}
    proof["proof_hash"] = _canonical_hash(payload)
    serving_proof.write_text(json.dumps(proof), encoding="utf-8")

    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.seal_run_artifacts(
            context,
            directory=run_dir,
            compilation_manifest_path=compilation,
            release_proof_path=release_proof,
            serving_proof_path=serving_proof,
        )

    assert caught.value.code == "serving_proof_mismatch"
    assert not (run_dir / "artifact-manifest.json").exists()


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("release-not-current", "release_proof_mismatch"),
        ("missing", "artifact_chain_incomplete"),
        ("extra", "unexpected_artifact"),
        ("duplicate", "artifact_chain_incomplete"),
        ("symlink", "unsafe_artifact_path"),
        ("secret", "unsafe_artifact_path"),
    ],
)
def test_ra7_seal_rejects_release_and_artifact_path_matrix(
    session: Session,
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    context, compilation, release_proof, serving_proof = _write_promoted_run(
        session, tmp_path
    )
    run_dir = compilation.parent.parent
    if mutation == "release-not-current":
        current = session.get(CurrentRelease, (context.scope.space_id, "current"))
        assert current is not None
        session.delete(current)
        session.flush()
    elif mutation == "missing":
        (run_dir / "metrics.json").unlink()
    elif mutation == "extra":
        (run_dir / "unbound.txt").write_text("extra", encoding="utf-8")
    elif mutation == "duplicate":
        duplicate = run_dir / "duplicate"
        duplicate.mkdir()
        (duplicate / "metrics.json").write_text('{"passed":true}', encoding="utf-8")
    elif mutation == "symlink":
        (run_dir / "linked.json").symlink_to(run_dir / "metrics.json")
    elif mutation == "secret":
        (run_dir / "api-key.txt").write_text("redacted", encoding="utf-8")

    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.seal_run_artifacts(
            context,
            directory=run_dir,
            compilation_manifest_path=compilation,
            release_proof_path=release_proof,
            serving_proof_path=serving_proof,
        )

    assert caught.value.code == expected_code
    assert not (run_dir / "artifact-manifest.json").exists()


def test_ra7_build_candidate_rejects_preexisting_same_space_snapshot(
    session: Session,
    tmp_path: Path,
) -> None:
    scope, snapshot_id, compilation_path, review_receipt_path = (
        _write_resolved_review_bundle(session, tmp_path)
    )
    compilation = release_cli.load_compilation_manifest(compilation_path)
    receipt = release_cli.load_review_receipt(review_receipt_path)
    session.add(
        ReleaseSnapshot(
            id=snapshot_id,
            space_id=scope.space_id,
            label="unrelated-preexisting-b",
            rendered_pages=[],
            status="building",
            read_model_version=1,
            projection_frozen_at=None,
            published_at=None,
            published_by="unrelated",
        )
    )
    session.flush()
    request = {
        "schema_version": "candidate-run-request-v1",
        "space_id": scope.space_id,
        "compilation_manifest_path": "bundle/compilation-manifest.json",
        "compilation_manifest_hash": compilation.manifest_hash,
        "review_receipt_hash": receipt.receipt_hash,
        "snapshot_id": snapshot_id,
        "knowledge_schema_version": "v1.1+release",
        "template_hashes": ["d" * 64],
        "model_plan_hash": "e" * 64,
    }
    request_path = tmp_path / "preexisting.yaml"
    request_path.write_text(release_cli.dump_yaml(request), encoding="utf-8")

    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.build_candidate(
            release_cli.GovernanceContext(
                session, scope, _ReviewAuthorizer(), _ReleaseAuthorizer()
            ),
            run_request_path=request_path,
            review_receipt_path=review_receipt_path,
            output_dir=tmp_path / "candidate-preexisting",
        )

    assert caught.value.code == "candidate_snapshot_exists"
    assert session.get(ReleaseSnapshot, snapshot_id).status == "building"


class _DenyReviewAuthorizer:
    def authorize_review(self, **kwargs: Any) -> release_cli.ReviewAuthorizationDecision:
        return release_cli.ReviewAuthorizationDecision(
            outcome="denied",
            space_id=kwargs["space_id"],
            review_id=kwargs["review_id"],
            principal=kwargs["principal"],
            actor_type=kwargs["actor_type"],
            compilation_manifest_hash=kwargs["compilation_manifest_hash"],
            authorization_receipt=kwargs["authorization_receipt"],
        )


def test_ra7_build_candidate_reauthorizes_manual_receipt(
    session: Session,
    tmp_path: Path,
) -> None:
    scope, snapshot_id, compilation_path, review_receipt_path = (
        _write_resolved_review_bundle(session, tmp_path)
    )
    compilation = release_cli.load_compilation_manifest(compilation_path)
    receipt = release_cli.load_review_receipt(review_receipt_path)
    request = {
        "schema_version": "candidate-run-request-v1",
        "space_id": scope.space_id,
        "compilation_manifest_path": "bundle/compilation-manifest.json",
        "compilation_manifest_hash": compilation.manifest_hash,
        "review_receipt_hash": receipt.receipt_hash,
        "snapshot_id": snapshot_id,
        "knowledge_schema_version": "v1.1+release",
        "template_hashes": ["d" * 64],
        "model_plan_hash": "e" * 64,
    }
    request_path = tmp_path / "reauthorize.yaml"
    request_path.write_text(release_cli.dump_yaml(request), encoding="utf-8")

    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.build_candidate(
            release_cli.GovernanceContext(
                session, scope, _DenyReviewAuthorizer(), _ReleaseAuthorizer()
            ),
            run_request_path=request_path,
            review_receipt_path=review_receipt_path,
            output_dir=tmp_path / "candidate-denied",
        )

    assert caught.value.code == "review_authorization_failed"
    assert session.get(ReleaseSnapshot, snapshot_id) is None


def test_ra7_build_candidate_rejects_unlisted_concurrent_changeset_and_fact(
    session: Session,
    tmp_path: Path,
) -> None:
    scope, snapshot_id, compilation_path, review_receipt_path = (
        _write_resolved_review_bundle(session, tmp_path)
    )
    compilation = release_cli.load_compilation_manifest(compilation_path)
    receipt = release_cli.load_review_receipt(review_receipt_path)
    _, version = release_product(session, scope, code="UNLISTED-CONCURRENT")
    claim, _ = release_claim(
        session,
        scope,
        version,
        claim_id="claim-unlisted-concurrent",
        predicate="unlisted_concurrent_fact",
    )
    unlisted = ChangeSet(
        space_id=scope.space_id,
        source_kind="document",
        knowledge_ids=["knowledge-unlisted"],
        external_record_id="unlisted-concurrent",
        source_revision="unlisted-revision",
        status="applied",
        created_by="concurrent-compiler",
    )
    session.add(unlisted)
    session.flush()
    session.add(
        ChangeItem(
            change_set_id=unlisted.id,
            action="add",
            claim_id=claim.id,
            proposed={"unlisted": True},
            decision="auto_applied",
            decision_basis={"source": "unlisted"},
        )
    )
    session.flush()
    request = {
        "schema_version": "candidate-run-request-v1",
        "space_id": scope.space_id,
        "compilation_manifest_path": "bundle/compilation-manifest.json",
        "compilation_manifest_hash": compilation.manifest_hash,
        "review_receipt_hash": receipt.receipt_hash,
        "snapshot_id": snapshot_id,
        "knowledge_schema_version": "v1.1+release",
        "template_hashes": ["d" * 64],
        "model_plan_hash": "e" * 64,
    }
    request_path = tmp_path / "unlisted.yaml"
    request_path.write_text(release_cli.dump_yaml(request), encoding="utf-8")

    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.build_candidate(
            release_cli.GovernanceContext(
                session, scope, _ReviewAuthorizer(), _ReleaseAuthorizer()
            ),
            run_request_path=request_path,
            review_receipt_path=review_receipt_path,
            output_dir=tmp_path / "candidate-unlisted",
        )

    assert caught.value.code == "candidate_build_failed"
    assert session.get(ReleaseSnapshot, snapshot_id) is None


def test_ra7_fresh_builder_rejects_accepted_item_bound_to_another_claim(
    session: Session,
) -> None:
    approved = _approved_release(session, "wrong-item-claim")
    scope = approved.scope
    changed = session.get(Claim, approved.waiting_claim_id)
    assert changed is not None
    change_set = ChangeSet(
        space_id=scope.space_id,
        source_kind="document",
        knowledge_ids=["knowledge-wrong-item-claim"],
        external_record_id="wrong-item-claim",
        source_revision="wrong-item-claim-revision",
        status="applied",
        created_by="compiler",
    )
    session.add(change_set)
    session.flush()
    item = ChangeItem(
        change_set_id=change_set.id,
        action="supersede",
        claim_id=approved.limited_claim_id,
        proposed={"value": {"text": "180天"}},
        decision="auto_applied",
        decision_basis={"rule": "exact"},
    )
    session.add(item)
    session.flush()
    changed.value = {"text": "180天"}
    changed.current_revision = 2
    session.add(
        ClaimRevision(
            claim_id=changed.id,
            revision_no=2,
            before={"value": {"text": "90天"}},
            after={"value": changed.value},
            actor="compiler",
            at=NOW,
            change_item_id=item.id,
        )
    )
    session.flush()
    snapshot_id = "snapshot-wrong-item-claim-new"
    facts = build_snapshot_facts(session, scope, snapshot_id=snapshot_id)

    with pytest.raises(ReleaseManifestBuildError, match="lineage"):
        build_fresh_staging_candidate_manifest(
            session,
            scope,
            snapshot_id=snapshot_id,
            compiled_at="2026-07-22T00:00:00+00:00",
            expected_base_snapshot_id=approved.manifest.snapshot_id,
            expected_base_manifest_hash=approved.manifest.manifest_sha256,
            target_claim_revisions=(
                (fact.claim_id, fact.revision_no) for fact in facts
            ),
            authorized_change_items=((item.id, item.claim_id),),
            expected_target_facts_hash=canonical_target_facts_hash(facts),
            schema_version="v1.1+release",
            template_hashes=("d" * 64,),
            model_plan_hash="e" * 64,
        )


def test_ra7_fresh_builder_rejects_same_revision_evidence_only_delta(
    session: Session,
) -> None:
    approved = _approved_release(session, "same-revision-evidence")
    scope = approved.scope
    evidence = session.scalar(
        select(ClaimEvidence).where(
            ClaimEvidence.claim_id == approved.waiting_claim_id
        )
    )
    assert evidence is not None
    evidence.quote = "unreviewed same-revision evidence replacement"
    session.flush()
    snapshot_id = "snapshot-same-revision-evidence-new"
    facts = build_snapshot_facts(session, scope, snapshot_id=snapshot_id)

    with pytest.raises(ReleaseManifestBuildError, match="lineage"):
        build_fresh_staging_candidate_manifest(
            session,
            scope,
            snapshot_id=snapshot_id,
            compiled_at="2026-07-22T00:00:00+00:00",
            expected_base_snapshot_id=approved.manifest.snapshot_id,
            expected_base_manifest_hash=approved.manifest.manifest_sha256,
            target_claim_revisions=(
                (fact.claim_id, fact.revision_no) for fact in facts
            ),
            authorized_change_items=(),
            expected_target_facts_hash=canonical_target_facts_hash(facts),
            schema_version="v1.1+release",
            template_hashes=("d" * 64,),
            model_plan_hash="e" * 64,
        )


def test_ra7_fresh_builder_verifies_base_manifest_payload_before_lineage_use(
    session: Session,
) -> None:
    approved = _approved_release(session, "tampered-base-payload")
    scope = approved.scope
    record = session.scalar(
        select(ReleaseManifestRecord).where(
            ReleaseManifestRecord.space_id == scope.space_id,
            ReleaseManifestRecord.snapshot_id == approved.manifest.snapshot_id,
        )
    )
    assert record is not None
    forged_payload = copy.deepcopy(record.payload)
    forged_fact = next(
        item
        for item in forged_payload["facts"]
        if item["claim_id"] == approved.waiting_claim_id
    )
    forged_fact["evidence"][0]["quote"] = "tampered base evidence"
    set_committed_value(record, "payload", forged_payload)
    evidence = session.scalar(
        select(ClaimEvidence).where(
            ClaimEvidence.id == forged_fact["evidence"][0]["id"]
        )
    )
    assert evidence is not None
    evidence.quote = "tampered base evidence"
    session.flush()
    snapshot_id = "snapshot-tampered-base-payload-new"
    facts = build_snapshot_facts(session, scope, snapshot_id=snapshot_id)

    with pytest.raises(ReleaseManifestBuildError, match="base manifest"):
        build_fresh_staging_candidate_manifest(
            session,
            scope,
            snapshot_id=snapshot_id,
            compiled_at="2026-07-22T00:00:00+00:00",
            expected_base_snapshot_id=approved.manifest.snapshot_id,
            expected_base_manifest_hash=approved.manifest.manifest_sha256,
            target_claim_revisions=(
                (fact.claim_id, fact.revision_no) for fact in facts
            ),
            authorized_change_items=(),
            expected_target_facts_hash=canonical_target_facts_hash(facts),
            schema_version="v1.1+release",
            template_hashes=("d" * 64,),
            model_plan_hash="e" * 64,
        )


def test_ra7_build_candidate_bad_parent_rolls_back_database_mutation(
    session: Session,
    tmp_path: Path,
) -> None:
    scope, snapshot_id, compilation_path, review_receipt_path = (
        _write_resolved_review_bundle(session, tmp_path)
    )
    compilation = release_cli.load_compilation_manifest(compilation_path)
    receipt = release_cli.load_review_receipt(review_receipt_path)
    request = {
        "schema_version": "candidate-run-request-v1",
        "space_id": scope.space_id,
        "compilation_manifest_path": "bundle/compilation-manifest.json",
        "compilation_manifest_hash": compilation.manifest_hash,
        "review_receipt_hash": receipt.receipt_hash,
        "snapshot_id": snapshot_id,
        "knowledge_schema_version": "v1.1+release",
        "template_hashes": ["d" * 64],
        "model_plan_hash": "e" * 64,
    }
    request_path = tmp_path / "bad-parent.yaml"
    request_path.write_text(release_cli.dump_yaml(request), encoding="utf-8")
    current_before = session.scalar(select(func.count()).select_from(CurrentRelease))

    with pytest.raises(release_cli.ReleaseCLIError):
        release_cli.build_candidate(
            release_cli.GovernanceContext(
                session, scope, _ReviewAuthorizer(), _ReleaseAuthorizer()
            ),
            run_request_path=request_path,
            review_receipt_path=review_receipt_path,
            output_dir=tmp_path / "missing-parent" / "candidate",
        )

    assert session.get(ReleaseSnapshot, snapshot_id) is None
    assert session.scalar(select(func.count()).select_from(CurrentRelease)) == current_before
    session.scalar(select(func.count()).select_from(ChangeSet))


@pytest.mark.parametrize("failure", ["exclusive-write", "rename"])
def test_ra7_build_candidate_artifact_failure_rolls_back_fresh_snapshot(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    scope, snapshot_id, compilation_path, review_receipt_path = (
        _write_resolved_review_bundle(session, tmp_path)
    )
    compilation = release_cli.load_compilation_manifest(compilation_path)
    receipt = release_cli.load_review_receipt(review_receipt_path)
    request = {
        "schema_version": "candidate-run-request-v1",
        "space_id": scope.space_id,
        "compilation_manifest_path": "bundle/compilation-manifest.json",
        "compilation_manifest_hash": compilation.manifest_hash,
        "review_receipt_hash": receipt.receipt_hash,
        "snapshot_id": snapshot_id,
        "knowledge_schema_version": "v1.1+release",
        "template_hashes": ["d" * 64],
        "model_plan_hash": "e" * 64,
    }
    request_path = tmp_path / "artifact-failure.yaml"
    request_path.write_text(release_cli.dump_yaml(request), encoding="utf-8")
    output = tmp_path / "candidate-artifact-failure"
    if failure == "exclusive-write":

        def fail_write(_path: Path, _value: object) -> None:
            raise release_cli.ReleaseCLIError("output_unavailable", "injected")

        monkeypatch.setattr(release_cli, "_write_json_exclusive", fail_write)
    else:

        def fail_rename(_source: Path, _destination: Path) -> None:
            raise OSError("injected rename failure")

        monkeypatch.setattr(release_cli.os, "rename", fail_rename)

    with pytest.raises(release_cli.ReleaseCLIError):
        release_cli.build_candidate(
            release_cli.GovernanceContext(
                session, scope, _ReviewAuthorizer(), _ReleaseAuthorizer()
            ),
            run_request_path=request_path,
            review_receipt_path=review_receipt_path,
            output_dir=output,
        )

    assert session.get(ReleaseSnapshot, snapshot_id) is None
    assert not output.exists()
    session.scalar(select(func.count()).select_from(ChangeSet))


def test_ra7_promote_write_failure_rolls_back_cas_and_keeps_session_usable(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, request_path, manifest_path, approval_path = _write_approved_run(
        session, tmp_path
    )
    current_before = session.get(
        CurrentRelease, (context.scope.space_id, "current")
    ).snapshot_id

    def fail_write(_path: Path, _value: object) -> None:
        raise release_cli.ReleaseCLIError("output_unavailable", "injected")

    monkeypatch.setattr(release_cli, "_write_json_exclusive", fail_write)
    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.promote_approved(
            context,
            request_path=request_path,
            manifest_path=manifest_path,
            approval_receipt_path=approval_path,
            output_path=tmp_path / "failed-proof.json",
        )

    assert caught.value.code == "output_unavailable"
    assert (
        session.get(CurrentRelease, (context.scope.space_id, "current")).snapshot_id
        == current_before
    )
    session.scalar(select(func.count()).select_from(ChangeSet))


def test_ra7_seal_requires_injected_actual_approved_snapshot_reader(
    session: Session,
    tmp_path: Path,
) -> None:
    context, compilation, release_proof, serving_proof = _write_promoted_run(
        session, tmp_path
    )
    context = release_cli.GovernanceContext(
        context.session,
        context.scope,
        context.review_authorizer,
        context.release_authorizer,
    )
    run_dir = compilation.parent.parent

    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.seal_run_artifacts(
            context,
            directory=run_dir,
            compilation_manifest_path=compilation,
            release_proof_path=release_proof,
            serving_proof_path=serving_proof,
        )

    assert caught.value.code == "trusted_context_required"
    assert not (run_dir / "artifact-manifest.json").exists()


def test_ra7_seal_recomputes_candidate_provenance_hash(
    session: Session,
    tmp_path: Path,
) -> None:
    context, compilation, release_proof, serving_proof = _write_promoted_run(
        session, tmp_path
    )
    run_dir = compilation.parent.parent
    candidate_path = run_dir / "candidate" / "candidate-snapshot.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["provenance_hash"] = "f" * 64
    candidate["receipt_hash"] = _canonical_hash(
        {key: value for key, value in candidate.items() if key != "receipt_hash"}
    )
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.seal_run_artifacts(
            context,
            directory=run_dir,
            compilation_manifest_path=compilation,
            release_proof_path=release_proof,
            serving_proof_path=serving_proof,
        )

    assert caught.value.code == "candidate_receipt_mismatch"
    assert not (run_dir / "artifact-manifest.json").exists()


def test_ra7_seal_reauthorizes_resolved_review_receipt(
    session: Session,
    tmp_path: Path,
) -> None:
    context, compilation, release_proof, serving_proof = _write_promoted_run(
        session, tmp_path
    )
    context = release_cli.GovernanceContext(
        context.session,
        context.scope,
        _DenyReviewAuthorizer(),
        context.release_authorizer,
        context.approved_snapshot_reader,
    )
    run_dir = compilation.parent.parent

    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.seal_run_artifacts(
            context,
            directory=run_dir,
            compilation_manifest_path=compilation,
            release_proof_path=release_proof,
            serving_proof_path=serving_proof,
        )

    assert caught.value.code == "review_authorization_failed"
    assert not (run_dir / "artifact-manifest.json").exists()


@pytest.mark.parametrize(
    "request_kind", ["review", "review-event", "run", "approval"]
)
def test_ra7_seal_replays_exact_human_request_semantics(
    session: Session,
    tmp_path: Path,
    request_kind: str,
) -> None:
    context, compilation_path, release_proof_path, serving_proof = (
        _write_promoted_run(session, tmp_path)
    )
    run_dir = compilation_path.parent.parent
    candidate_path = run_dir / "candidate" / "candidate-snapshot.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    if request_kind in {"review", "review-event"}:
        request_path = run_dir / "review-decisions.yaml"
        request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
        if request_kind == "review":
            request["decisions"][0]["reason"] = "forged review request reason"
        else:
            request["decisions"][0]["expected_version"] = "forged-version"
            request["decisions"][0]["request_id"] = "forged-request-id"
        request_path.write_text(release_cli.dump_yaml(request), encoding="utf-8")
        parsed_review = release_cli.ReviewDecisionsRequest.model_validate(request)
        receipt_path = run_dir / "review-receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if request_kind == "review-event":
            receipt["decisions"][0]["expected_version"] = "forged-version"
            receipt["decisions"][0]["request_id"] = "forged-request-id"
            receipt["decisions"][0]["resolved_at"] = (
                "2040-01-01T00:00:00+00:00"
            )
        receipt["request_hash"] = release_cli.canonical_sha256(
            parsed_review.model_dump(mode="json")
        )
        receipt["receipt_hash"] = _canonical_hash(
            {key: value for key, value in receipt.items() if key != "receipt_hash"}
        )
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        run_request_path = run_dir / "run-request.yaml"
        run_request = yaml.safe_load(run_request_path.read_text(encoding="utf-8"))
        run_request["review_receipt_hash"] = receipt["receipt_hash"]
        run_request_path.write_text(
            release_cli.dump_yaml(run_request), encoding="utf-8"
        )
        parsed_run = release_cli.CandidateRunRequest.model_validate(run_request)
        candidate["review_receipt_hash"] = receipt["receipt_hash"]
        candidate["request_hash"] = release_cli.canonical_sha256(
            parsed_run.model_dump(mode="json")
        )
        compilation = release_cli.load_compilation_manifest(compilation_path)
        manifest = release_cli._load_release_manifest(
            run_dir / "candidate" / "release-manifest.json"
        )
        candidate["provenance_hash"] = release_cli._candidate_provenance_hash(
            compilation,
            review_receipt_hash=receipt["receipt_hash"],
            manifest_hash=manifest.manifest_sha256,
        )
    elif request_kind == "run":
        request_path = run_dir / "run-request.yaml"
        request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
        request["knowledge_schema_version"] = "v-forged"
        request_path.write_text(release_cli.dump_yaml(request), encoding="utf-8")
        parsed_run = release_cli.CandidateRunRequest.model_validate(request)
        candidate["request_hash"] = release_cli.canonical_sha256(
            parsed_run.model_dump(mode="json")
        )
    else:
        request_path = run_dir / "release-approval-request.yaml"
        request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
        request["reason"] = "forged approval request reason"
        request_path.write_text(release_cli.dump_yaml(request), encoding="utf-8")
        parsed_approval = release_cli.ReleaseApprovalRequest.model_validate(request)
        request_hash = release_cli.canonical_sha256(
            parsed_approval.model_dump(mode="json")
        )
        approval_path = run_dir / "approval-receipt.json"
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        approval["request_hash"] = request_hash
        approval["receipt_hash"] = _canonical_hash(
            {key: value for key, value in approval.items() if key != "receipt_hash"}
        )
        approval_path.write_text(json.dumps(approval), encoding="utf-8")
        release_proof = json.loads(
            release_proof_path.read_text(encoding="utf-8")
        )
        release_proof["request_hash"] = request_hash
        release_proof["approval_receipt_hash"] = approval["receipt_hash"]
        release_proof["proof_hash"] = _canonical_hash(
            {
                key: value
                for key, value in release_proof.items()
                if key != "proof_hash"
            }
        )
        release_proof_path.write_text(json.dumps(release_proof), encoding="utf-8")
    if request_kind != "approval":
        candidate["receipt_hash"] = _canonical_hash(
            {key: value for key, value in candidate.items() if key != "receipt_hash"}
        )
        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.seal_run_artifacts(
            context,
            directory=run_dir,
            compilation_manifest_path=compilation_path,
            release_proof_path=release_proof_path,
            serving_proof_path=serving_proof,
        )

    expected_code = (
        "review_receipt_mismatch"
        if request_kind == "review-event"
        else "artifact_chain_mismatch"
    )
    assert caught.value.code == expected_code
    assert not (run_dir / "artifact-manifest.json").exists()


class _UnavailableApprovedReader:
    def read_current(self, _scope: object) -> ServingFailure:
        return ServingFailure(code="no_release")


def test_ra7_seal_rejects_self_declared_proof_when_actual_reader_fails(
    session: Session,
    tmp_path: Path,
) -> None:
    context, compilation, release_proof, serving_proof = _write_promoted_run(
        session, tmp_path
    )
    context = release_cli.GovernanceContext(
        context.session,
        context.scope,
        context.review_authorizer,
        context.release_authorizer,
        _UnavailableApprovedReader(),  # type: ignore[arg-type]
    )
    run_dir = compilation.parent.parent

    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.seal_run_artifacts(
            context,
            directory=run_dir,
            compilation_manifest_path=compilation,
            release_proof_path=release_proof,
            serving_proof_path=serving_proof,
        )

    assert caught.value.code == "serving_proof_mismatch"
    assert not (run_dir / "artifact-manifest.json").exists()


class _TamperedApprovedReader:
    def __init__(self, actual: object, mutation: str) -> None:
        self._actual = actual
        self._mutation = mutation

    def read_current(self, scope: object) -> ApprovedSnapshotResult | ServingFailure:
        result = self._actual.read_current(scope)  # type: ignore[attr-defined]
        if not isinstance(result, ApprovedSnapshotResult):
            return result
        if self._mutation == "reverse":
            return result.model_copy(update={"facts": tuple(reversed(result.facts))})
        if self._mutation == "principal":
            return result.model_copy(update={"approval_principal": "mallory"})
        if self._mutation == "approved-at":
            return result.model_copy(
                update={"approved_at": result.approved_at.replace(year=2040)}
            )
        return result.model_copy(update={"read_model_version": 0})


@pytest.mark.parametrize(
    "mutation", ["reverse", "principal", "approved-at", "read-model-version"]
)
def test_ra7_seal_rejects_nonexact_approved_reader_dto(
    session: Session,
    tmp_path: Path,
    mutation: str,
) -> None:
    context, compilation, release_proof, serving_proof = _write_promoted_run(
        session, tmp_path
    )
    context = release_cli.GovernanceContext(
        context.session,
        context.scope,
        context.review_authorizer,
        context.release_authorizer,
        _TamperedApprovedReader(context.approved_snapshot_reader, mutation),  # type: ignore[arg-type]
    )
    run_dir = compilation.parent.parent

    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.seal_run_artifacts(
            context,
            directory=run_dir,
            compilation_manifest_path=compilation,
            release_proof_path=release_proof,
            serving_proof_path=serving_proof,
        )

    assert caught.value.code == "serving_proof_mismatch"
    assert not (run_dir / "artifact-manifest.json").exists()


def test_ra7_seal_rejects_rehashed_receipt_that_does_not_match_exact_approval_row(
    session: Session,
    tmp_path: Path,
) -> None:
    context, compilation, release_proof, serving_proof = _write_promoted_run(
        session, tmp_path
    )
    run_dir = compilation.parent.parent
    receipt_path = run_dir / "approval-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["approved_at"] = "2040-01-01T00:00:00+00:00"
    payload = {key: value for key, value in receipt.items() if key != "receipt_hash"}
    receipt["receipt_hash"] = _canonical_hash(payload)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    release_payload = json.loads(release_proof.read_text(encoding="utf-8"))
    release_payload["approval_receipt_hash"] = receipt["receipt_hash"]
    proof_payload = {
        key: value for key, value in release_payload.items() if key != "proof_hash"
    }
    release_payload["proof_hash"] = _canonical_hash(proof_payload)
    release_proof.write_text(json.dumps(release_payload), encoding="utf-8")

    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.seal_run_artifacts(
            context,
            directory=run_dir,
            compilation_manifest_path=compilation,
            release_proof_path=release_proof,
            serving_proof_path=serving_proof,
        )

    assert caught.value.code == "approval_receipt_mismatch"
    assert not (run_dir / "artifact-manifest.json").exists()


def test_ra7_seal_rejects_every_rehashed_approval_attestation_substitution(
    session: Session,
    tmp_path: Path,
) -> None:
    context, compilation, release_proof, serving_proof = _write_promoted_run(
        session, tmp_path
    )
    run_dir = compilation.parent.parent
    receipt_path = run_dir / "approval-receipt.json"
    original_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    original_proof = json.loads(release_proof.read_text(encoding="utf-8"))
    substitutions = {
        "space_id": "substituted-space",
        "approval_id": "substituted-approval",
        "principal": "mallory",
        "actor_type": "principal",
        "role": "release_viewer",
        "authorization_receipt": "substituted-authz",
        "reason": "substituted reason",
        "approved_at": "2040-01-01T00:00:00+00:00",
        "created_at": "2040-01-01T00:00:00+00:00",
    }
    for field, value in substitutions.items():
        receipt = {**original_receipt, field: value}
        receipt["receipt_hash"] = _canonical_hash(
            {key: item for key, item in receipt.items() if key != "receipt_hash"}
        )
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        proof = {**original_proof, "approval_receipt_hash": receipt["receipt_hash"]}
        if field == "approval_id":
            proof["approval_id"] = value
        elif field == "principal":
            proof["principal"] = value
        elif field == "reason":
            proof["reason"] = value
        proof["proof_hash"] = _canonical_hash(
            {key: item for key, item in proof.items() if key != "proof_hash"}
        )
        release_proof.write_text(json.dumps(proof), encoding="utf-8")

        with pytest.raises(release_cli.ReleaseCLIError) as caught:
            release_cli.seal_run_artifacts(
                context,
                directory=run_dir,
                compilation_manifest_path=compilation,
                release_proof_path=release_proof,
                serving_proof_path=serving_proof,
            )

        expected_code = (
            "artifact_chain_mismatch"
            if field
            in {
                "space_id",
                "principal",
                "actor_type",
                "authorization_receipt",
                "reason",
            }
            else "approval_receipt_mismatch"
        )
        assert caught.value.code == expected_code, field
        assert not (run_dir / "artifact-manifest.json").exists()
    receipt_path.write_text(json.dumps(original_receipt), encoding="utf-8")
    release_proof.write_text(json.dumps(original_proof), encoding="utf-8")


def test_ra7_seal_rejects_rehashed_release_proof_identity_substitution(
    session: Session,
    tmp_path: Path,
) -> None:
    context, compilation, release_proof, serving_proof = _write_promoted_run(
        session, tmp_path
    )
    run_dir = compilation.parent.parent
    original = json.loads(release_proof.read_text(encoding="utf-8"))
    substitutions = {
        "action": "rollback",
        "audit_id": "substituted-audit",
        "previous_snapshot_id": original["snapshot_id"],
        "activated_at": "2040-01-01T00:00:00+00:00",
        "audit_created_at": "2040-01-01T00:00:00+00:00",
    }
    for field, value in substitutions.items():
        proof = {**original, field: value}
        proof["proof_hash"] = _canonical_hash(
            {key: item for key, item in proof.items() if key != "proof_hash"}
        )
        release_proof.write_text(json.dumps(proof), encoding="utf-8")

        with pytest.raises(release_cli.ReleaseCLIError) as caught:
            release_cli.seal_run_artifacts(
                context,
                directory=run_dir,
                compilation_manifest_path=compilation,
                release_proof_path=release_proof,
                serving_proof_path=serving_proof,
            )

        expected_code = (
            "artifact_chain_mismatch"
            if field == "previous_snapshot_id"
            else "release_proof_mismatch"
        )
        assert caught.value.code == expected_code, field
        assert not (run_dir / "artifact-manifest.json").exists()
    release_proof.write_text(json.dumps(original), encoding="utf-8")


def test_ra7_seal_detects_file_mutation_immediately_before_final_create(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, compilation, release_proof, serving_proof = _write_promoted_run(
        session, tmp_path
    )
    run_dir = compilation.parent.parent
    original_write = release_cli._write_json_exclusive

    def race_write(path: Path, value: object) -> None:
        (run_dir / "metrics.json").write_text('{"passed":false}', encoding="utf-8")
        original_write(path, value)

    monkeypatch.setattr(release_cli, "_write_json_exclusive", race_write)
    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.seal_run_artifacts(
            context,
            directory=run_dir,
            compilation_manifest_path=compilation,
            release_proof_path=release_proof,
            serving_proof_path=serving_proof,
        )

    assert caught.value.code == "artifact_changed_during_seal"
    assert not (run_dir / "artifact-manifest.json").exists()


def test_ra7_seal_rejects_governance_bytes_swapped_after_chain_validation(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, compilation, release_proof, serving_proof = _write_promoted_run(
        session, tmp_path
    )
    run_dir = compilation.parent.parent
    approval_path = run_dir / "approval-receipt.json"
    original_verify = release_cli._verify_governance_chain

    def verify_then_swap(*args: object, **kwargs: object) -> object:
        manifest = original_verify(*args, **kwargs)  # type: ignore[arg-type]
        approval_path.write_text('{"substituted":true}', encoding="utf-8")
        return manifest

    monkeypatch.setattr(release_cli, "_verify_governance_chain", verify_then_swap)
    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.seal_run_artifacts(
            context,
            directory=run_dir,
            compilation_manifest_path=compilation,
            release_proof_path=release_proof,
            serving_proof_path=serving_proof,
        )

    assert caught.value.code == "artifact_changed_during_seal"
    assert not (run_dir / "artifact-manifest.json").exists()


def test_ra7_seal_detects_late_extra_file_and_leaves_no_final(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, compilation, release_proof, serving_proof = _write_promoted_run(
        session, tmp_path
    )
    run_dir = compilation.parent.parent
    original_write = release_cli._write_json_exclusive

    def race_write(path: Path, value: object) -> None:
        (run_dir / "late-extra.json").write_text('{"late":true}', encoding="utf-8")
        original_write(path, value)

    monkeypatch.setattr(release_cli, "_write_json_exclusive", race_write)
    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.seal_run_artifacts(
            context,
            directory=run_dir,
            compilation_manifest_path=compilation,
            release_proof_path=release_proof,
            serving_proof_path=serving_proof,
        )

    assert caught.value.code == "unexpected_artifact"
    assert not (run_dir / "artifact-manifest.json").exists()


def test_ra7_seal_cleans_partial_final_when_exclusive_write_fails(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, compilation, release_proof, serving_proof = _write_promoted_run(
        session, tmp_path
    )
    run_dir = compilation.parent.parent

    def partial_write(path: Path, _value: object) -> None:
        path.write_text("{", encoding="utf-8")
        raise release_cli.ReleaseCLIError("output_unavailable", "injected")

    monkeypatch.setattr(release_cli, "_write_json_exclusive", partial_write)
    with pytest.raises(release_cli.ReleaseCLIError) as caught:
        release_cli.seal_run_artifacts(
            context,
            directory=run_dir,
            compilation_manifest_path=compilation,
            release_proof_path=release_proof,
            serving_proof_path=serving_proof,
        )

    assert caught.value.code == "output_unavailable"
    assert not (run_dir / "artifact-manifest.json").exists()
