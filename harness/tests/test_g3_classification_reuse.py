from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest

from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    validate_batch_candidate,
)
from insurance_harness.knowledge_compiler.batch_entity_resolution_830_g3 import resolve_batch

MODULE = "insurance_harness.knowledge_compiler.g3_classification_reuse"
FIXTURE = Path(__file__).parent / "fixtures/batch_concept_compile_830_g3/candidate.json"


def _api():
    assert importlib.util.find_spec(MODULE) is not None, "classification reuse is not implemented"
    return importlib.import_module(MODULE)


def test_historical_authority_rejects_untrusted_parent_before_child_signature(monkeypatch):
    from insurance_harness.model_policy import AdmissionPolicyDenied
    from insurance_harness.run_admission import g3_trust_policy as trust

    api = _api()
    policy, parent, approval = object(), object(), object()
    delegated = []
    monkeypatch.setattr(trust, "load_g3_root_trust_policy", lambda: policy)

    def reject(actual_policy, actual_parent):
        assert actual_policy is policy and actual_parent is parent
        raise AdmissionPolicyDenied("untrusted_g3_parent_key")

    monkeypatch.setattr(trust, "verify_parent_authorization", reject)
    monkeypatch.setattr(
        trust, "verify_delegated_stage_signature", lambda *args: delegated.append(args)
    )
    with pytest.raises(AdmissionPolicyDenied):
        api._verify_historical_authority(parent, approval)
    assert delegated == []


def test_replay_reuses_original_model_receipts_and_current_snapshot():
    api = _api()
    request = validate_batch_candidate(FIXTURE.read_bytes()).request
    inputs = request.resolution_inputs
    result = api.replay_classification(
        source_corpus=inputs.corpus,
        source_proposals=inputs.proposals,
        current_corpus=inputs.corpus,
        catalog=request.catalog,
        existing_entities=inputs.existing_entities,
        policy=inputs.policy,
    )
    assert result == request.resolution
    assert inputs.proposals.model_receipts == request.resolution_inputs.proposals.model_receipts
    # Head observation may change without invalidating captured model work.
    changed = inputs.existing_entities.model_dump(exclude={"snapshot_sha256"})
    changed["head_receipt_sha256"] = "c" * 64
    from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_sha256_830_g3
    from insurance_harness.knowledge_compiler.batch_entity_resolution_830_g3 import (
        ExistingEntitySnapshotV1,
    )

    changed["snapshot_sha256"] = batch_sha256_830_g3(changed["contract"], changed)
    snapshot = ExistingEntitySnapshotV1.model_validate(changed)
    replayed = api.replay_classification(
        source_corpus=inputs.corpus,
        source_proposals=inputs.proposals,
        current_corpus=inputs.corpus,
        catalog=request.catalog,
        existing_entities=snapshot,
        policy=inputs.policy,
    )
    assert replayed == resolve_batch(
        catalog=request.catalog,
        corpus=inputs.corpus,
        proposals=inputs.proposals,
        existing_entities=snapshot,
        policy=inputs.policy,
    )
    assert replayed != result


def test_replay_rejects_unrelated_or_changed_source_without_relabeling_receipts():
    api = _api()
    request = validate_batch_candidate(FIXTURE.read_bytes()).request
    inputs = request.resolution_inputs
    changed = inputs.corpus.model_copy(update={"corpus_sha256": "c" * 64})
    with pytest.raises(ValueError):
        api.replay_classification(
            source_corpus=inputs.corpus,
            source_proposals=inputs.proposals,
            current_corpus=changed,
            catalog=request.catalog,
            existing_entities=inputs.existing_entities,
            policy=inputs.policy,
        )


def test_reuse_receipt_binds_current_request_and_keeps_original_origin():
    api = _api()
    assert hasattr(api, "G3ClassificationReuseV1"), "explicit reuse receipt is missing"
    request = validate_batch_candidate(FIXTURE.read_bytes()).request
    receipt = api.build_classification_reuse(
        request=request,
        source_chain_manifest_hash="1" * 64,
        source_terminal_receipt_sha256="2" * 64,
        source_admission_digest="3" * 64,
        source_resolution_sha256=request.resolution.batch_sha256,
    )
    restored = api.G3ClassificationReuseV1.model_validate_json(receipt.model_dump_json())
    api.validate_reuse_binding(restored, request=request)
    assert restored.source_terminal_receipt_sha256 == "2" * 64
    assert restored.source_proposals_sha256 == request.resolution_inputs.proposals.proposals_sha256
    changed = request.model_copy(update={"request_sha256": "4" * 64})
    with pytest.raises(ValueError):
        api.validate_reuse_binding(restored, request=changed)
    with pytest.raises(ValueError):
        api.G3ClassificationReuseV1.model_validate(
            {**receipt.model_dump(), "current_snapshot_sha256": "4" * 64}
        )


def test_origin_reopen_is_mandatory_even_for_a_valid_reuse_binding(tmp_path):
    api = _api()
    assert hasattr(api, "validate_classification_reuse"), "origin ledger reopen is missing"
    request = validate_batch_candidate(FIXTURE.read_bytes()).request
    receipt = api.build_classification_reuse(
        request=request,
        source_chain_manifest_hash="1" * 64,
        source_terminal_receipt_sha256="2" * 64,
        source_admission_digest="3" * 64,
        source_resolution_sha256=request.resolution.batch_sha256,
    )
    with pytest.raises((ValueError, OSError)):
        api.validate_classification_reuse(
            receipt, request=request, ledger_root=tmp_path, admission_root=tmp_path
        )
