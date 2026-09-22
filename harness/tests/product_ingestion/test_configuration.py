from __future__ import annotations

import base64
import copy
import hashlib
import json
import typing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretStr, ValidationError

from insurance_harness.product_ingestion.models import ProductScope
from insurance_harness.service_shell.config import ShellConfigError, ShellSettings

SCOPE = ProductScope(
    tenant_id="42",
    space_id="space-a",
    raw_knowledge_base_id="raw-a",
    wiki_knowledge_base_id="wiki-a",
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _secret(seed: int) -> str:
    return base64.b64encode(bytes([seed]) * 32).decode()


def runtime_json(tmp_path: Path) -> str:
    catalog = (
        Path(__file__).parents[3] / "docs/insurance-kb/evidence/830-g3/catalog/catalog.json"
    ).read_bytes()
    files = {}
    for name, raw in (
        ("catalog", catalog),
        ("profile_confirmation", b'{"contract":"profile-confirmation.test.v1"}'),
        ("resolution_policy", b'{"contract":"resolution-policy.test.v1"}'),
    ):
        path = tmp_path / f"{name}.json"
        path.write_bytes(raw)
        files[name] = {
            "path": str(path),
            "sha256": _sha(raw),
            "max_bytes": len(raw),
        }
    source_private = Ed25519PrivateKey.from_private_bytes(bytes([9]) * 32)
    source_public = base64.b64encode(source_private.public_key().public_bytes_raw()).decode()
    expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    return json.dumps(
        {
            "contract": "product-ingestion-runtime.830.v1",
            "trusted_files": files,
            "pump": {
                "page_size": 17,
                "event_limit": 23,
                "poll_interval_seconds": 0.25,
            },
            "bindings": [
                {
                    "scope": SCOPE.model_dump(mode="json"),
                    "platform": {
                        "base_url": "https://weknora.invalid",
                        "machine_key": "machine-secret",
                        "timeout_seconds": 5,
                        "max_response_bytes": 1048576,
                    },
                    "source_authorities": [
                        {"key_id": "source-current", "public_key_b64": source_public}
                    ],
                    "model": {
                        "scope": SCOPE.model_dump(mode="json"),
                        "endpoint": "https://gemini.invalid/v1/chat/completions",
                        "api_key": "gemini-secret",
                        "model": "gemini-3.7-flash-medium",
                        "policy_version": "g3-user-gemini-gateway-v1",
                        "expires_at": expires,
                        "templates": [
                            {
                                "template_id": "field-window-v1",
                                "role": "extract",
                                "purpose": "g3-field-extraction",
                                "run_schema_version": "830-g3-v1",
                                "prompt_sha256": _sha(b"field prompt"),
                                "max_context_bytes": 4096,
                                "max_output_tokens": 512,
                            }
                        ],
                        "field_template_id": "field-window-v1",
                        "max_request_bytes": 8192,
                        "max_response_bytes": 8192,
                        "timeout_seconds": 5,
                    },
                    "automation": {
                        "scope": SCOPE.model_dump(mode="json"),
                        "mode": "ISOLATED_NOT_FOR_PRODUCTION",
                        "principal_id": "api_tenant:42",
                        "api_key_id": 7,
                        "policy_id": "g3-product-automation",
                        "policy_version": "1",
                        "policy_sha256": "a" * 64,
                        "capabilities": ["activate", "create-draft", "review"],
                        "expires_at": expires,
                        "decision_signer_key_id": "decision-current",
                        "decision_private_key_b64": _secret(1),
                        "publish_signer_key_id": "publish-current",
                        "publish_private_key_b64": _secret(2),
                    },
                }
            ],
        }
    )


def settings(tmp_path: Path, **updates: typing.Any) -> ShellSettings:
    values = {
        "postgres_dsn": SecretStr("postgresql+psycopg://wiki:secret@db/wiki"),
        "principal_space_ids": (SCOPE.space_id,),
        "worker_id": "worker-a",
        "worker_space_ids": (SCOPE.space_id,),
        "product_ingestion_enabled": True,
        "product_ingestion_scopes_json": SecretStr(json.dumps([SCOPE.model_dump(mode="json")])),
        "product_ingestion_runtime_json": SecretStr(runtime_json(tmp_path)),
    }
    values.update(updates)
    return ShellSettings.model_validate(values)


def test_disabled_product_runtime_does_not_parse_or_read_configuration(tmp_path: Path) -> None:
    from insurance_harness.product_ingestion.configuration import (
        load_product_runtime_configuration,
    )

    configured = settings(
        tmp_path,
        product_ingestion_enabled=False,
        product_ingestion_runtime_json=SecretStr("not-json"),
    )
    assert load_product_runtime_configuration(configured) is None


def test_runtime_configuration_loads_exact_scopes_keys_and_trusted_bytes(
    tmp_path: Path,
) -> None:
    from insurance_harness.product_ingestion.configuration import (
        load_product_runtime_configuration,
    )

    loaded = load_product_runtime_configuration(settings(tmp_path))
    assert loaded is not None
    assert tuple(loaded.bindings) == (SCOPE.space_id,)
    binding = loaded.bindings[SCOPE.space_id]
    assert binding.scope == SCOPE == binding.model.scope == binding.automation.scope
    assert tuple(binding.source_public_keys) == ("source-current",)
    assert loaded.catalog.catalog_sha256
    assert (
        loaded.catalog_json
        == Path(
            json.loads(settings(tmp_path).product_ingestion_runtime_json.get_secret_value())[
                "trusted_files"
            ]["catalog"]["path"]
        ).read_bytes()
    )
    assert loaded.profile_confirmation_json.startswith(b"{")
    assert loaded.resolution_policy_json.startswith(b"{")
    rendered = repr(loaded)
    assert "machine-secret" not in rendered
    assert "gemini-secret" not in rendered
    assert _secret(1) not in rendered and _secret(2) not in rendered


@pytest.mark.parametrize("failure", ["scope", "file", "duplicate_json"])
def test_runtime_configuration_rejects_scope_file_and_ambiguous_json(
    tmp_path: Path, failure: str
) -> None:
    from insurance_harness.product_ingestion.configuration import (
        load_product_runtime_configuration,
    )

    configured = settings(tmp_path)
    raw = configured.product_ingestion_runtime_json.get_secret_value()
    if failure == "duplicate_json":
        raw = raw[:-1] + ',"contract":"product-ingestion-runtime.830.v1"}'
    else:
        value = json.loads(raw)
        if failure == "scope":
            value["bindings"][0]["model"]["scope"]["raw_knowledge_base_id"] = "other"
        else:
            value["trusted_files"]["resolution_policy"]["sha256"] = "f" * 64
        raw = json.dumps(value)
    configured = configured.model_copy(update={"product_ingestion_runtime_json": SecretStr(raw)})
    with pytest.raises(ShellConfigError) as caught:
        load_product_runtime_configuration(configured)
    assert caught.value.keys == ("product_ingestion_runtime_json",)


def test_enabled_wait_stage_retry_budget_reaches_server_deadlines(tmp_path: Path) -> None:
    configured = settings(tmp_path)
    policy = configured.job_runtime_config()
    assert policy.policy_for("product_stage_uploads").max_attempts == 256
    assert policy.policy_for("product_stage_source").backoff_delay(attempt=255) == 30
    assert policy.policy_for("product_stage_identity").max_attempts == 3

    with pytest.raises(ValidationError, match="retry budget"):
        settings(
            tmp_path,
            product_ingestion_wait_max_attempts=3,
            product_ingestion_wait_backoff_seconds=(1.0,),
        )


def test_runtime_configuration_rejects_a_cross_scope_source_key_union(
    tmp_path: Path,
) -> None:
    from insurance_harness.product_ingestion.configuration import (
        load_product_runtime_configuration,
    )

    configured = settings(tmp_path)
    payload = json.loads(configured.product_ingestion_runtime_json.get_secret_value())
    second = copy.deepcopy(payload["bindings"][0])
    for target in (second["scope"], second["model"]["scope"], second["automation"]["scope"]):
        target["space_id"] = "space-b"
    payload["bindings"].append(second)
    scopes = [
        SCOPE.model_dump(mode="json"),
        {**SCOPE.model_dump(mode="json"), "space_id": "space-b"},
    ]
    configured = configured.model_copy(
        update={
            "product_ingestion_scopes_json": SecretStr(json.dumps(scopes)),
            "product_ingestion_runtime_json": SecretStr(json.dumps(payload)),
        }
    )

    with pytest.raises(ShellConfigError) as caught:
        load_product_runtime_configuration(configured)
    assert caught.value.keys == ("product_ingestion_runtime_json",)
