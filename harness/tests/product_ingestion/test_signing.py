from __future__ import annotations

import base64
import hashlib
import importlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretStr

from insurance_harness.product_ingestion.models import ProductScope


def module():
    try:
        return importlib.import_module("insurance_harness.product_ingestion.signing")
    except ModuleNotFoundError:
        pytest.fail("platform system decision signer is not implemented")


@pytest.fixture
def signing():
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    publish_key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    scope = ProductScope(
        tenant_id="1", space_id="space", raw_knowledge_base_id="raw", wiki_knowledge_base_id="wiki"
    )
    config = SimpleNamespace(
        scope=scope,
        mode="ISOLATED_NOT_FOR_PRODUCTION",
        principal_id="api_tenant:1",
        api_key_id=7,
        policy_id="policy",
        policy_version="1",
        policy_sha256="a" * 64,
        capabilities=("activate", "create-draft", "review"),
        expires_at=datetime(2035, 1, 1, tzinfo=UTC),
        decision_signer_key_id="system",
        decision_private_key_b64=SecretStr(base64.b64encode(bytes(range(32))).decode()),
        publish_signer_key_id="publish",
        publish_private_key_b64=SecretStr(base64.b64encode(bytes(range(1, 33))).decode()),
    )
    metadata = dict(
        tenant_id=1,
        space_id="space",
        raw_kb_id="raw",
        wiki_kb_id="wiki",
        preparation_id="prep",
        status="draft",
        preparation_digest="b" * 64,
        candidate_digest="c" * 64,
        manifest_digest="d" * 64,
        ready_receipt_digest="e" * 64,
        review_policy_id="f" * 64,
        expected_release_id="parent",
        expected_activation_epoch=9,
        created_at="2030-01-01T00:00:00Z",
    )
    return config, metadata, key, publish_key


def test_system_signature_is_domain_separated_and_exact_replay_stable(signing):
    config, metadata, key, _ = signing
    raw = module().sign_system_decision(config, metadata, run_id="run")
    assert raw == module().sign_system_decision(config, metadata, run_id="run")
    body = json.loads(raw)
    signature = base64.urlsafe_b64decode(body.pop("signature") + "==")
    key.public_key().verify(signature, b"system-policy-decision.v1\0" + module().canonical(body))
    assert body["principal_id"] == "api_tenant:1" and body["decision"] == "approve"
    assert body["draft_preparation_digest"] == metadata["preparation_digest"]
    assert body["expected_activation_epoch"] == 9


def test_signer_refuses_wrong_scope_and_expired_preparation(signing):
    config, metadata, *_ = signing
    with pytest.raises(ValueError, match="scope"):
        module().sign_system_decision(config, {**metadata, "raw_kb_id": "other"}, run_id="run")
    with pytest.raises(ValueError, match="lifetime"):
        module().sign_system_decision(
            config, {**metadata, "created_at": "2040-01-01T00:00:00Z"}, run_id="run"
        )


def test_publish_signature_binds_original_system_receipt_and_parent(signing):
    config, metadata, _, key = signing
    decision = module().sign_system_decision(config, metadata, run_id="run")
    raw = module().sign_publish_authorization(config, decision)
    body = json.loads(raw)
    signature = base64.urlsafe_b64decode(body.pop("signature") + "==")
    key.public_key().verify(signature, module().canonical(body))
    assert body["review_decision_digest"] == hashlib.sha256(decision).hexdigest()
    assert body["nonce"] == json.loads(decision)["nonce"]
    assert body["version"] == "0" and body["action"] == "activate"
