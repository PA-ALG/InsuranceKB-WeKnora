"""Configured platform signatures for the existing isolated release authority."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.product_ingestion.platform import _object


def canonical(value: object) -> bytes:
    # Match Go encoding/json for these structured signing envelopes.
    text = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    for char, escaped in (
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("&", "\\u0026"),
        ("\u2028", "\\u2028"),
        ("\u2029", "\\u2029"),
    ):
        text = text.replace(char, escaped)
    return text.encode()


def _scope(config):
    return {
        "tenant_id": int(config.scope.tenant_id),
        "space_id": config.scope.space_id,
        "raw_kb_id": config.scope.raw_knowledge_base_id,
        "wiki_kb_id": config.scope.wiki_knowledge_base_id,
    }


def _key(secret):
    return Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(secret.get_secret_value(), validate=True)
    )


def _sign(body, key, domain=b""):
    signature = key.sign(domain + canonical(body))
    return canonical(
        {**body, "signature": base64.urlsafe_b64encode(signature).decode().rstrip("=")}
    )


def sign_system_decision(config, preparation: dict, *, run_id: str) -> bytes:
    scope = _scope(config)
    if any(preparation.get(name) != value for name, value in scope.items()):
        raise ValueError("system preparation scope mismatch")
    if config.mode != "ISOLATED_NOT_FOR_PRODUCTION" or tuple(config.capabilities) != (
        "activate",
        "create-draft",
        "review",
    ):
        raise ValueError("system automation policy mismatch")
    if preparation.get("status") != "draft":
        raise ValueError("system decision requires exact Draft metadata")
    for name in (
        "preparation_digest",
        "candidate_digest",
        "manifest_digest",
        "ready_receipt_digest",
        "review_policy_id",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", preparation.get(name, "")):
            raise ValueError("system preparation digest mismatch")
    created = datetime.fromisoformat(preparation["created_at"].replace("Z", "+00:00"))
    if created.tzinfo is None:
        raise ValueError("system preparation lifetime is not explicit")
    issued = int(created.timestamp())
    expires = min(issued + 24 * 3600, int(config.expires_at.timestamp()))
    if expires <= issued:
        raise ValueError("system preparation lifetime exceeds policy")
    nonce = hashlib.sha256(
        b"product-system-decision.v1\0"
        + canonical(
            {
                "run_id": run_id,
                "preparation_id": preparation["preparation_id"],
                "candidate_digest": preparation["candidate_digest"],
                "policy": config.policy_sha256,
            }
        )
    ).hexdigest()
    body = {
        "version": "1",
        "decision": "approve",
        "mode": config.mode,
        "principal_id": config.principal_id,
        "api_key_id": config.api_key_id,
        **scope,
        "policy_id": config.policy_id,
        "policy_version": config.policy_version,
        "policy_digest": config.policy_sha256,
        "capabilities": list(config.capabilities),
        "preparation_id": preparation["preparation_id"],
        "draft_preparation_digest": preparation["preparation_digest"],
        "candidate_digest": preparation["candidate_digest"],
        "manifest_digest": preparation["manifest_digest"],
        "ready_receipt_digest": preparation["ready_receipt_digest"],
        "inner_review_policy_id": preparation["review_policy_id"],
        "expected_release_id": preparation["expected_release_id"],
        "expected_activation_epoch": preparation["expected_activation_epoch"],
        "issued_at": issued,
        "expires_at": expires,
        "nonce": nonce,
        "signer_key_id": config.decision_signer_key_id,
    }
    return _sign(body, _key(config.decision_private_key_b64), b"system-policy-decision.v1\0")


def sign_publish_authorization(config, decision_raw: bytes) -> bytes:
    decision = json.loads(decision_raw, object_pairs_hook=_object)
    if (
        canonical(decision) != decision_raw
        or any(decision.get(name) != value for name, value in _scope(config).items())
        or decision.get("policy_digest") != config.policy_sha256
    ):
        raise ValueError("publish decision scope or policy mismatch")
    unsigned = {name: value for name, value in decision.items() if name != "signature"}
    _key(config.decision_private_key_b64).public_key().verify(
        base64.urlsafe_b64decode(decision["signature"] + "=="),
        b"system-policy-decision.v1\0" + canonical(unsigned),
    )
    body = {
        name: decision[name]
        for name in (
            "preparation_id",
            "candidate_digest",
            "manifest_digest",
            "ready_receipt_digest",
            "tenant_id",
            "space_id",
            "raw_kb_id",
            "wiki_kb_id",
            "expected_release_id",
            "expected_activation_epoch",
            "expires_at",
            "nonce",
        )
    }
    body.update(
        version="0",
        action="activate",
        review_decision_digest=hashlib.sha256(decision_raw).hexdigest(),
        review_policy_id=decision["inner_review_policy_id"],
        signer_key_id=config.publish_signer_key_id,
    )
    return _sign(body, _key(config.publish_private_key_b64))
