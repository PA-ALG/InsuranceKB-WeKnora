from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


SCRIPT = Path(__file__).parents[1] / "configure.py"


def _module():
    spec = importlib.util.spec_from_file_location("product_ingestion_configure", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _seed(value: int) -> str:
    return base64.b64encode(bytes([value]) * 32).decode()


def _public_raw_url(value: int) -> str:
    public = Ed25519PrivateKey.from_private_bytes(bytes([value]) * 32).public_key()
    return base64.urlsafe_b64encode(public.public_bytes_raw()).decode().rstrip("=")


def _input(tmp_path: Path) -> tuple[Path, dict, dict]:
    catalog = (
        Path(__file__).parents[3]
        / "docs/insurance-kb/evidence/830-g3/catalog/catalog.json"
    ).read_bytes()
    trusted = {}
    for name, raw in (
        ("catalog", catalog),
        ("profile_confirmation", b'{"contract":"profile-confirmation.test.v1"}'),
        ("resolution_policy", b'{"contract":"resolution-policy.test.v1"}'),
    ):
        path = tmp_path / f"{name}.json"
        path.write_bytes(raw)
        trusted[name] = {
            "source_path": str(path),
            "runtime_path": f"/run/product-config/{name}.json",
            "sha256": _sha(raw),
            "max_bytes": len(raw),
        }
    previous_publish = _public_raw_url(11)
    previous_citation = base64.urlsafe_b64encode(
        Ed25519PrivateKey.from_private_bytes(bytes([12]) * 32).private_bytes_raw()
        + Ed25519PrivateKey.from_private_bytes(bytes([12]) * 32)
        .public_key()
        .public_bytes_raw()
    ).decode().rstrip("=")
    go_config = {
        "server": {"port": 8080, "host": "0.0.0.0"},
        "models": [{"id": "existing", "parameters": {"secret": "keep"}}],
        "schema_wiki_signing": {
            "human_decision_public_keys": [],
            "publish_authorization_public_keys": [
                {"key_id": "existing-publish", "public_key_base64": previous_publish}
            ],
            "golden_quality_evaluator_public_keys": [],
            "citation_token_signing_keys": [
                {"key_id": "existing-citation", "private_key_base64": previous_citation}
            ],
            "active_citation_token_key_id": "existing-citation",
        },
    }
    go_path = tmp_path / "config.yaml"
    go_path.write_text(yaml.safe_dump(go_config, sort_keys=False))
    expires = (datetime.now(UTC) + timedelta(days=2)).replace(microsecond=0)
    payload = {
        "contract": "product-ingestion-deployment-input.830.v1",
        "scope": {
            "tenant_id": "42",
            "space_id": "10000000-0000-0000-0000-000000000001",
            "raw_knowledge_base_id": "10000000-0000-0000-0000-000000000002",
            "wiki_knowledge_base_id": "10000000-0000-0000-0000-000000000003",
        },
        "machine": {
            "principal_id": "api_tenant:42",
            "api_key_id": 91,
            "api_key": "fixture-machine-key",
        },
        "harness_service": {
            "principal_id": "weknora-product-bridge",
            "credential": "fixture-harness-credential",
        },
        "source_signer": {"key_id": "source-current", "seed_b64": _seed(1)},
        "system_signer": {"key_id": "system-current", "seed_b64": _seed(2)},
        "publish_signer": {"key_id": "publish-current", "seed_b64": _seed(3)},
        "automation_policy": {
            "policy_id": "g3-product-automation",
            "policy_version": "1",
            "mode": "ISOLATED_NOT_FOR_PRODUCTION",
            "not_before": int(datetime.now(UTC).timestamp()) - 60,
            "expires_at": int(expires.timestamp()),
            "capabilities": ["activate", "create-draft", "review"],
        },
        "platform": {
            "base_url": "https://weknora.invalid",
            "timeout_seconds": 10,
            "max_response_bytes": 8 * 1024 * 1024,
        },
        "harness_bridge": {
            "base_url": "http://product-api:8000",
            "timeout_seconds": 10,
            "max_response_bytes": 8 * 1024 * 1024,
            "max_upload_files": 100,
            "max_upload_bytes": 256 * 1024 * 1024,
        },
        "model": {
            "endpoint": "https://gemini.invalid/v1/chat/completions",
            "api_key": "fixture-gemini-key",
            "model": "gemini-3.7-flash-medium",
            "policy_version": "g3-user-gemini-gateway-v1",
            "expires_at": expires.isoformat(),
            "identity_max_context_bytes": 200_000,
            "identity_max_output_tokens": 16_384,
            "field_max_context_bytes": 300_000,
            "field_max_output_tokens": 16_384,
            "max_request_bytes": 2_000_000,
            "max_response_bytes": 2_000_000,
            "timeout_seconds": 120,
        },
        "trusted_files": trusted,
        "go_config_path": str(go_path),
    }
    path = tmp_path / "deployment-input.private.json"
    path.write_text(json.dumps(payload))
    return path, payload, go_config


def test_generate_exact_cross_runtime_configuration_and_preserve_go_values(tmp_path: Path):
    module = _module()
    input_path, payload, original_go = _input(tmp_path)
    output = tmp_path / "generated"

    manifest = module.generate(input_path, output)

    runtime = json.loads((output / "product-ingestion-runtime.private.json").read_text())
    binding = runtime["bindings"][0]
    patched = yaml.safe_load((output / "weknora-config.private.yaml").read_text())
    assert patched["server"] == original_go["server"]
    assert patched["models"] == original_go["models"]
    assert binding["platform"]["machine_key"] == payload["machine"]["api_key"]
    assert patched["g3_platform_processing"]["api_key_id"] == 91
    assert binding["automation"]["policy_sha256"] == manifest["policy_sha256"]
    assert module.go_policy_sha256(patched["g3_platform_processing"]) == manifest[
        "policy_sha256"
    ]
    assert binding["source_authorities"] == [
        {"key_id": "source-current", "public_key_b64": module.standard_public_key(_seed(1))}
    ]
    assert patched["g3_platform_processing"]["source_snapshot_signing_key"][
        "private_key_base64"
    ] == module.go_private_key(_seed(1))
    assert patched["schema_wiki_signing"]["publish_authorization_public_keys"][-1] == {
        "key_id": "publish-current",
        "public_key_base64": module.go_public_key(_seed(3)),
    }
    env = (output / "product-ingestion.env.private").read_text()
    assert "fixture-machine-key" in env and "fixture-gemini-key" in env
    assert "fixture-harness-credential" in env
    assert patched["product_ingestion"]["credential"] == "fixture-harness-credential"
    assert manifest["files"]["runtime_json"]["sha256"] == _sha(
        (output / "product-ingestion-runtime.private.json").read_bytes()
    )


def test_generate_configures_distinct_open_discovery_and_review(tmp_path: Path):
    module = _module()
    input_path, payload, _ = _input(tmp_path)
    output = tmp_path / "generated"
    module.generate(input_path, output)
    runtime = json.loads((output / "product-ingestion-runtime.private.json").read_text())
    model = runtime["bindings"][0]["model"]
    templates = {row["template_id"]: row for row in model["templates"]}
    assert {"discovery-v1", "discovery-review-v1"} <= set(templates)
    assert templates["discovery-v1"]["role"] == "extract"
    assert templates["discovery-review-v1"]["role"] == "verify"
    assert templates["discovery-v1"]["purpose"] == "g3-open-discovery"
    assert templates["discovery-review-v1"]["purpose"] == "g3-open-discovery-review"
    assert templates["discovery-v1"]["prompt_sha256"] != templates["discovery-review-v1"]["prompt_sha256"]
    for name in ("discovery-v1", "discovery-review-v1"):
        assert templates[name]["max_context_bytes"] == payload["model"]["field_max_context_bytes"]
        assert templates[name]["max_output_tokens"] == payload["model"]["field_max_output_tokens"]
    assert model["field_template_id"] == "field-window-v1"


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda p: p["machine"].update(principal_id="api_tenant:41"), "machine"),
        (lambda p: p["model"].update(model="other-model"), "Gemini"),
        (lambda p: p["source_signer"].update(seed_b64=p["system_signer"]["seed_b64"]), "distinct"),
    ],
)
def test_generate_rejects_identity_and_authority_drift(tmp_path: Path, mutate, match: str):
    module = _module()
    input_path, payload, _ = _input(tmp_path)
    mutate(payload)
    input_path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match=match):
        module.generate(input_path, tmp_path / "generated")


def test_generate_rejects_trusted_file_drift_without_output(tmp_path: Path):
    module = _module()
    input_path, payload, _ = _input(tmp_path)
    Path(payload["trusted_files"]["resolution_policy"]["source_path"]).write_bytes(b"drift")
    output = tmp_path / "generated"

    with pytest.raises(ValueError, match="trusted"):
        module.generate(input_path, output)

    assert not output.exists()


def test_generate_rejects_unknown_input_and_existing_key_collision(tmp_path: Path):
    module = _module()
    input_path, payload, _ = _input(tmp_path)
    payload["unexpected"] = True
    input_path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="input"):
        module.generate(input_path, tmp_path / "unknown")

    input_path, payload, _ = _input(tmp_path)
    payload["publish_signer"]["key_id"] = "existing-publish"
    input_path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="authority"):
        module.generate(input_path, tmp_path / "collision")


def test_go_policy_digest_matches_encoding_json_vector():
    module = _module()
    configured = {
        "enabled": True,
        "tenant_id": 42,
        "space_id": "space",
        "raw_kb_id": "raw",
        "wiki_kb_id": "wiki",
        "machine_principal_id": "api_tenant:42",
        "api_key_id": 91,
        "policy_id": "g3-product-automation",
        "policy_version": "1",
        "mode": "ISOLATED_NOT_FOR_PRODUCTION",
        "not_before": 100,
        "expires_at": 300,
        "capabilities": ["activate", "create-draft", "review"],
        "system_decision_key_id": "system-current",
    }

    # Generated once with Go encoding/json and the production domain prefix.
    assert module.go_policy_sha256(configured) == (
        "3bb92250839b7291dec81478c8a37536b450a02094f125ceecdbf006f63f369b"
    )
