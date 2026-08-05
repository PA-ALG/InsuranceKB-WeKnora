"""OpenSpec 080: one Candidate through manifest, dossier and preparation input."""

from __future__ import annotations

import ast
import hashlib

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.knowledge_compiler import candidate_wiki_manifest as manifest_module
from insurance_harness.knowledge_compiler.candidate_review_release_handoff import (
    CandidateReviewReleaseHandoffError,
    CandidateReviewReleaseHandoffV1,
    build_candidate_review_release_handoff,
    verify_candidate_review_release_handoff,
)
from tests.test_candidate_wiki_manifest_076 import _incremental_inputs


def _handoff() -> CandidateReviewReleaseHandoffV1:
    assembly, base, authority, candidates = _incremental_inputs()
    return build_candidate_review_release_handoff(
        assembly=assembly,
        base=base,
        base_authority=authority,
        field_candidates=candidates,
    )


def test_one_candidate_drives_manifest_dossier_and_preparation() -> None:
    handoff = _handoff()

    assert handoff.candidate_hash == handoff.wiki_manifest.candidate_hash
    assert handoff.candidate_hash == handoff.review_dossier.candidate_hash
    assert handoff.candidate_hash == handoff.release_preparation.candidate_digest
    assert handoff.human_batch_hash == handoff.review_dossier.human_batch_hash
    assert handoff.human_batch_hash == handoff.release_preparation.required_human_batch_hash
    assert handoff.policy_hash == handoff.release_preparation.review_policy_id
    assert handoff.wiki_manifest.manifest_digest == handoff.release_preparation.manifest_digest
    assert handoff.wiki_manifest.members == handoff.release_preparation.members
    assert handoff.release_preparation.human_decision_digest is None
    assert handoff.release_preparation.signature is None
    assert handoff.release_preparation.active_head is None


def test_equivalent_input_order_is_deterministic_and_replayable() -> None:
    assembly, base, authority, candidates = _incremental_inputs()
    forward = build_candidate_review_release_handoff(
        assembly=assembly,
        base=base,
        base_authority=authority,
        field_candidates=candidates,
    )
    reverse = build_candidate_review_release_handoff(
        assembly=assembly,
        base=base,
        base_authority=authority,
        field_candidates=reversed(candidates),
    )

    assert forward == reverse
    assert forward.handoff_hash == reverse.handoff_hash
    assert (
        verify_candidate_review_release_handoff(
            forward,
            base_authority=authority,
        )
        == forward
    )


@pytest.mark.parametrize(
    "edge",
    (
        "candidate",
        "batch",
        "policy",
        "space",
        "product",
        "change_set",
        "manifest",
        "members",
    ),
)
def test_recomputed_nested_identity_drift_fails_closed(edge: str) -> None:
    handoff = _handoff()
    changed = "f" * 64
    if edge in {"candidate", "batch", "policy", "space", "product", "change_set"}:
        field = {
            "candidate": "candidate_digest",
            "batch": "required_human_batch_hash",
            "policy": "review_policy_id",
            "space": "space_id",
            "product": "product_version_id",
            "change_set": "change_set_hash",
        }[edge]
        value = "foreign-space" if edge == "space" else (
            "foreign-product" if edge == "product" else changed
        )
        preparation = handoff.release_preparation.model_construct(
            **{**handoff.release_preparation.__dict__, field: value}
        )
        forged = handoff.model_construct(
            **{**handoff.__dict__, "release_preparation": preparation}
        )
    elif edge == "manifest":
        preparation = handoff.release_preparation.model_construct(
            **{**handoff.release_preparation.__dict__, "manifest_digest": changed}
        )
        forged = handoff.model_construct(
            **{**handoff.__dict__, "release_preparation": preparation}
        )
    else:
        preparation = handoff.release_preparation.model_construct(
            **{
                **handoff.release_preparation.__dict__,
                "members": tuple(reversed(handoff.release_preparation.members)),
            }
        )
        forged = handoff.model_construct(
            **{**handoff.__dict__, "release_preparation": preparation}
        )

    with pytest.raises(CandidateReviewReleaseHandoffError):
        verify_candidate_review_release_handoff(
            forged,
            base_authority=_incremental_inputs()[2],
        )


@pytest.mark.parametrize("edge", ("scope", "evidence"))
def test_upstream_field_candidate_drift_returns_no_partial_handoff(edge: str) -> None:
    assembly, base, authority, candidates = _incremental_inputs()
    if edge == "scope":
        forged = candidates[0].model_copy(
            update={"product_version_id": "foreign-product"}
        )
    else:
        evidence = candidates[0].evidence[0]
        quote = "foreign but self-consistent Evidence"
        changed_evidence = evidence.model_copy(
            update={
                "quote_snapshot": quote,
                "quote_snapshot_sha256": hashlib.sha256(quote.encode()).hexdigest(),
            }
        )
        forged = candidates[0].model_copy(update={"evidence": (changed_evidence,)})

    with pytest.raises(CandidateReviewReleaseHandoffError):
        build_candidate_review_release_handoff(
            assembly=assembly,
            base=base,
            base_authority=authority,
            field_candidates=(forged, *candidates[1:]),
        )


def test_replay_rejects_self_consistent_caller_forged_manifest() -> None:
    handoff = _handoff()
    _, _, authority, _ = _incremental_inputs()
    members = handoff.wiki_manifest.members[:-1]
    manifest_bytes = manifest_module._manifest_bytes(members)
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    forged_manifest = handoff.wiki_manifest.model_copy(
        update={
            "members": members,
            "manifest_bytes": manifest_bytes,
            "manifest_digest": manifest_digest,
        }
    )
    preparation_values = {
        "candidate_digest": handoff.candidate_hash,
        "required_human_batch_hash": handoff.human_batch_hash,
        "review_policy_id": handoff.policy_hash,
        "change_set_hash": handoff.change_set_hash,
        "space_id": handoff.space_id,
        "product_version_id": handoff.product_version_id,
        "expected_release_id": forged_manifest.base_release_id,
        "expected_activation_epoch": forged_manifest.base_activation_epoch,
        "base_manifest_digest": forged_manifest.base_manifest_digest,
        "manifest_digest": manifest_digest,
        "member_digests": tuple(member.member_digest for member in members),
    }
    forged_preparation = handoff.release_preparation.model_copy(
        update={
            "preparation_id": canonical_hash(
                "candidate-review-release-preparation-input.v1",
                preparation_values,
            ),
            "members": members,
            "manifest_bytes": manifest_bytes,
            "manifest_digest": manifest_digest,
        }
    )
    forged = handoff.model_copy(
        update={
            "wiki_manifest": forged_manifest,
            "release_preparation": forged_preparation,
        }
    )

    with pytest.raises(CandidateReviewReleaseHandoffError):
        verify_candidate_review_release_handoff(
            forged,
            base_authority=authority,
        )


def test_module_is_pure_and_contains_no_release_authority_surface() -> None:
    source = open(
        "harness/src/insurance_harness/knowledge_compiler/"
        "candidate_review_release_handoff.py",
        encoding="utf-8",
    ).read()
    tree = ast.parse(source)
    forbidden = {
        "os",
        "pathlib",
        "subprocess",
        "requests",
        "httpx",
        "sqlalchemy",
    }
    assert not {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    } & forbidden
    assert "Activate" not in source
    assert "PublishAuthorization" not in source
