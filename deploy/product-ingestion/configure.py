#!/usr/bin/env python3
"""Generate the private product-ingestion deployment configuration offline."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3 import (
    SchemaPackCatalogV1,
)
from insurance_harness.product_ingestion.configuration import ProductRuntimeSettings
from insurance_harness.product_ingestion.pipeline import FIELD_PROMPT, IDENTITY_PROMPT


INPUT_CONTRACT = "product-ingestion-deployment-input.830.v1"
CAPABILITIES = ["activate", "create-draft", "review"]
_SHA = re.compile(r"^[0-9a-f]{64}$")


class _UniqueSafeLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False):
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError("duplicate Go configuration property")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def _closed(value: object, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"invalid {label} input")
    return value


def _secret(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or any(c in value for c in "\r\n\x00"):
        raise ValueError(f"invalid {label}")
    return value


def _seed(seed_b64: str) -> Ed25519PrivateKey:
    try:
        raw = base64.b64decode(seed_b64, validate=True)
    except (ValueError, TypeError):
        raise ValueError("invalid Ed25519 seed") from None
    if len(raw) != 32:
        raise ValueError("invalid Ed25519 seed")
    return Ed25519PrivateKey.from_private_bytes(raw)


def standard_public_key(seed_b64: str) -> str:
    return base64.b64encode(_seed(seed_b64).public_key().public_bytes_raw()).decode()


def go_public_key(seed_b64: str) -> str:
    return base64.urlsafe_b64encode(_seed(seed_b64).public_key().public_bytes_raw()).decode().rstrip("=")


def go_private_key(seed_b64: str) -> str:
    key = _seed(seed_b64)
    raw = key.private_bytes_raw() + key.public_key().public_bytes_raw()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _go_canonical(value: object) -> bytes:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    for char, escaped in (
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("&", "\\u0026"),
        ("\u2028", "\\u2028"),
        ("\u2029", "\\u2029"),
    ):
        text = text.replace(char, escaped)
    return text.encode()


def go_policy_sha256(config: dict[str, Any]) -> str:
    policy = {
        "policy_id": config["policy_id"],
        "version": config["policy_version"],
        "mode": config["mode"],
        "enabled": config["enabled"],
        "principal_id": config["machine_principal_id"],
        "api_key_id": config["api_key_id"],
        "tenant_id": config["tenant_id"],
        "space_id": config["space_id"],
        "raw_kb_id": config["raw_kb_id"],
        "wiki_kb_id": config["wiki_kb_id"],
        "capabilities": config["capabilities"],
        "not_before": config["not_before"],
        "expires_at": config["expires_at"],
        "signer_key_id": config["system_decision_key_id"],
    }
    return hashlib.sha256(b"system-automation-policy.v1\0" + _go_canonical(policy)).hexdigest()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_input(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_bytes(), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid deployment input") from error


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate deployment input property")
        result[key] = value
    return result


def _authority_publics(config: dict[str, Any]) -> tuple[set[str], set[bytes]]:
    ids: set[str] = set()
    material: set[bytes] = set()
    signing = config.get("schema_wiki_signing") or {}
    if not isinstance(signing, dict):
        raise ValueError("invalid Go signing configuration")
    for name in (
        "human_decision_public_keys",
        "publish_authorization_public_keys",
        "golden_quality_evaluator_public_keys",
    ):
        rows = signing.get(name, [])
        if not isinstance(rows, list):
            raise ValueError("invalid Go signing configuration")
        for row in rows:
            try:
                key_id, encoded = row["key_id"], row["public_key_base64"]
                raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            except (KeyError, TypeError, ValueError):
                raise ValueError("invalid Go signing configuration") from None
            if key_id in ids or raw in material or len(raw) != 32:
                raise ValueError("existing authority collision")
            ids.add(key_id)
            material.add(raw)
    rows = signing.get("citation_token_signing_keys", [])
    if not isinstance(rows, list):
        raise ValueError("invalid Go signing configuration")
    for row in rows:
        try:
            key_id, encoded = row["key_id"], row["private_key_base64"]
            raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        except (KeyError, TypeError, ValueError):
            raise ValueError("invalid Go signing configuration") from None
        if len(raw) != 64 or key_id in ids or raw[32:] in material:
            raise ValueError("existing authority collision")
        ids.add(key_id)
        material.add(raw[32:])
    return ids, material


def _trusted_files(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, bytes]]:
    refs = _closed(
        payload,
        {"catalog", "profile_confirmation", "resolution_policy"},
        "trusted files",
    )
    runtime: dict[str, Any] = {}
    raw_files: dict[str, bytes] = {}
    for name, value in refs.items():
        row = _closed(
            value, {"source_path", "runtime_path", "sha256", "max_bytes"}, "trusted file"
        )
        if not isinstance(row["sha256"], str) or not _SHA.fullmatch(row["sha256"]):
            raise ValueError("invalid trusted file digest")
        if not isinstance(row["max_bytes"], int) or not 0 < row["max_bytes"] <= 64 << 20:
            raise ValueError("invalid trusted file size")
        source = Path(_secret(row["source_path"], "trusted file path"))
        runtime_path = _secret(row["runtime_path"], "trusted runtime path")
        if not runtime_path.startswith("/run/product-config/"):
            raise ValueError("invalid trusted runtime path")
        raw = source.read_bytes()
        if len(raw) > row["max_bytes"] or _sha256(raw) != row["sha256"]:
            raise ValueError("trusted product configuration file changed")
        raw_files[name] = raw
        runtime[name] = {
            "path": runtime_path,
            "sha256": row["sha256"],
            "max_bytes": row["max_bytes"],
        }
    SchemaPackCatalogV1.model_validate_json(raw_files["catalog"])
    for name in ("profile_confirmation", "resolution_policy"):
        if not isinstance(json.loads(raw_files[name], object_pairs_hook=_unique_object), dict):
            raise ValueError("trusted product configuration must be an object")
    return runtime, raw_files


def _load_go(path: str) -> dict[str, Any]:
    try:
        loaded = yaml.load(Path(path).read_text(), Loader=_UniqueSafeLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ValueError("invalid Go configuration") from error
    if not isinstance(loaded, dict):
        raise ValueError("invalid Go configuration")
    return loaded


def _validate_top(payload: dict[str, Any]) -> None:
    expected = {
        "contract",
        "scope",
        "machine",
        "harness_service",
        "source_signer",
        "system_signer",
        "publish_signer",
        "automation_policy",
        "platform",
        "harness_bridge",
        "model",
        "trusted_files",
        "go_config_path",
    }
    if set(payload) != expected or payload.get("contract") != INPUT_CONTRACT:
        raise ValueError("invalid deployment input")


def _build(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    _validate_top(payload)
    scope = _closed(
        payload["scope"],
        {"tenant_id", "space_id", "raw_knowledge_base_id", "wiki_knowledge_base_id"},
        "scope",
    )
    machine = _closed(payload["machine"], {"principal_id", "api_key_id", "api_key"}, "machine")
    tenant_text = _secret(scope["tenant_id"], "tenant id")
    try:
        tenant_id = int(tenant_text)
    except ValueError:
        raise ValueError("invalid machine tenant") from None
    if str(tenant_id) != tenant_text or machine["principal_id"] != f"api_tenant:{tenant_id}":
        raise ValueError("machine identity does not match scope")
    if not isinstance(machine["api_key_id"], int) or machine["api_key_id"] <= 0:
        raise ValueError("invalid machine key identity")
    machine_key = _secret(machine["api_key"], "machine key")
    harness_service = _closed(
        payload["harness_service"], {"principal_id", "credential"}, "Harness service"
    )
    _secret(harness_service["principal_id"], "Harness principal id")
    harness_credential = _secret(harness_service["credential"], "Harness credential")
    if harness_credential == machine_key:
        raise ValueError("machine and Harness credentials must be distinct")

    signer_rows = []
    for name in ("source_signer", "system_signer", "publish_signer"):
        row = _closed(payload[name], {"key_id", "seed_b64"}, name)
        key_id = _secret(row["key_id"], "authority key id")
        seed = _secret(row["seed_b64"], "Ed25519 seed")
        signer_rows.append((key_id, seed, _seed(seed).public_key().public_bytes_raw()))
    if len({row[0] for row in signer_rows}) != 3 or len({row[2] for row in signer_rows}) != 3:
        raise ValueError("signing authorities must be distinct")
    source, system, publish = signer_rows

    policy = _closed(
        payload["automation_policy"],
        {"policy_id", "policy_version", "mode", "not_before", "expires_at", "capabilities"},
        "automation policy",
    )
    now = int(datetime.now(UTC).timestamp())
    if (
        policy["mode"] != "ISOLATED_NOT_FOR_PRODUCTION"
        or policy["capabilities"] != CAPABILITIES
        or not isinstance(policy["not_before"], int)
        or not isinstance(policy["expires_at"], int)
        or policy["not_before"] <= 0
        or policy["not_before"] > now
        or policy["expires_at"] <= now
    ):
        raise ValueError("invalid automation policy")

    platform = _closed(
        payload["platform"], {"base_url", "timeout_seconds", "max_response_bytes"}, "platform"
    )
    bridge = _closed(
        payload["harness_bridge"],
        {
            "base_url",
            "timeout_seconds",
            "max_response_bytes",
            "max_upload_files",
            "max_upload_bytes",
        },
        "Harness bridge",
    )
    trusted, _ = _trusted_files(payload["trusted_files"])
    model = _closed(
        payload["model"],
        {
            "endpoint",
            "api_key",
            "model",
            "policy_version",
            "expires_at",
            "identity_max_context_bytes",
            "identity_max_output_tokens",
            "field_max_context_bytes",
            "field_max_output_tokens",
            "max_request_bytes",
            "max_response_bytes",
            "timeout_seconds",
        },
        "model",
    )
    if model["model"] != "gemini-3.7-flash-medium" or model["policy_version"] != "g3-user-gemini-gateway-v1":
        raise ValueError("configured Gemini identity is not approved")

    go_config = _load_go(_secret(payload["go_config_path"], "Go config path"))
    ids, materials = _authority_publics(go_config)
    if any(row[0] in ids or row[2] in materials for row in signer_rows):
        raise ValueError("generated authority collides with existing authority")

    go_scope = {
        "tenant_id": tenant_id,
        "space_id": scope["space_id"],
        "raw_kb_id": scope["raw_knowledge_base_id"],
        "wiki_kb_id": scope["wiki_knowledge_base_id"],
    }
    go_g3 = {
        "enabled": True,
        **go_scope,
        "machine_principal_id": machine["principal_id"],
        "api_key_id": machine["api_key_id"],
        "policy_id": policy["policy_id"],
        "policy_version": policy["policy_version"],
        "mode": policy["mode"],
        "not_before": policy["not_before"],
        "expires_at": policy["expires_at"],
        "capabilities": policy["capabilities"],
        "system_decision_key_id": system[0],
        "system_decision_public_keys": [
            {"key_id": system[0], "public_key_base64": go_public_key(system[1])}
        ],
        "source_snapshot_signing_key": {
            "key_id": source[0],
            "private_key_base64": go_private_key(source[1]),
        },
    }
    policy_sha = go_policy_sha256(go_g3)
    scope_json = dict(scope)
    runtime = {
        "contract": "product-ingestion-runtime.830.v1",
        "trusted_files": trusted,
        "pump": {"page_size": 50, "event_limit": 100, "poll_interval_seconds": 1.0},
        "bindings": [
            {
                "scope": scope_json,
                "platform": {**platform, "machine_key": machine_key},
                "source_authorities": [
                    {"key_id": source[0], "public_key_b64": standard_public_key(source[1])}
                ],
                "model": {
                    "scope": scope_json,
                    "endpoint": model["endpoint"],
                    "api_key": _secret(model["api_key"], "Gemini API key"),
                    "model": model["model"],
                    "policy_version": model["policy_version"],
                    "expires_at": model["expires_at"],
                    "templates": [
                        {
                            "template_id": "classification-v1",
                            "role": "classify",
                            "purpose": "g3-batch-resolution",
                            "run_schema_version": "830-g3-v1",
                            "prompt_sha256": _sha256(IDENTITY_PROMPT),
                            "max_context_bytes": model["identity_max_context_bytes"],
                            "max_output_tokens": model["identity_max_output_tokens"],
                        },
                        {
                            "template_id": "field-window-v1",
                            "role": "extract",
                            "purpose": "g3-field-extraction",
                            "run_schema_version": "830-g3-v1",
                            "prompt_sha256": _sha256(FIELD_PROMPT),
                            "max_context_bytes": model["field_max_context_bytes"],
                            "max_output_tokens": model["field_max_output_tokens"],
                        },
                    ],
                    "field_template_id": "field-window-v1",
                    "max_request_bytes": model["max_request_bytes"],
                    "max_response_bytes": model["max_response_bytes"],
                    "timeout_seconds": model["timeout_seconds"],
                },
                "automation": {
                    "scope": scope_json,
                    "mode": policy["mode"],
                    "principal_id": machine["principal_id"],
                    "api_key_id": machine["api_key_id"],
                    "policy_id": policy["policy_id"],
                    "policy_version": policy["policy_version"],
                    "policy_sha256": policy_sha,
                    "capabilities": policy["capabilities"],
                    "expires_at": datetime.fromtimestamp(policy["expires_at"], UTC).isoformat(),
                    "decision_signer_key_id": system[0],
                    "decision_private_key_b64": system[1],
                    "publish_signer_key_id": publish[0],
                    "publish_private_key_b64": publish[1],
                },
            }
        ],
    }
    ProductRuntimeSettings.model_validate_json(
        json.dumps(runtime, ensure_ascii=False, separators=(",", ":"))
    )

    patched = deepcopy(go_config)
    signing = patched.setdefault("schema_wiki_signing", {})
    publish_ring = signing.setdefault("publish_authorization_public_keys", [])
    publish_ring.append({"key_id": publish[0], "public_key_base64": go_public_key(publish[1])})
    patched["schema_wiki_frozen_release_scope"] = {"enabled": True, **go_scope}
    patched["product_ingestion"] = {
        "enabled": True,
        "base_url": bridge["base_url"],
        "credential": harness_credential,
        **go_scope,
        "timeout_seconds": bridge["timeout_seconds"],
        "max_response_bytes": bridge["max_response_bytes"],
        "max_upload_files": bridge["max_upload_files"],
        "max_upload_bytes": bridge["max_upload_bytes"],
    }
    patched["g3_platform_processing"] = go_g3
    env = {
        "WIKI_PRODUCT_INGESTION_ENABLED": "true",
        "WIKI_PRODUCT_INGESTION_SCOPES_JSON": json.dumps(
            [scope_json], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        "WIKI_PRODUCT_INGESTION_RUNTIME_JSON": json.dumps(
            runtime, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        "WIKI_PRINCIPAL_RECORDS_JSON": json.dumps(
            {
                harness_credential: {
                    "kind": "service",
                    "service": "product_ingestion",
                    "space_ids": [scope["space_id"]],
                    "capabilities": ["manage_product_ingestion", "read_product_ingestion"],
                }
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "WIKI_PRINCIPAL_SPACE_IDS": json.dumps([scope["space_id"]], separators=(",", ":")),
        "WIKI_WORKER_SPACE_IDS": json.dumps([scope["space_id"]], separators=(",", ":")),
    }
    return runtime, patched, env


def _private_write(path: Path, raw: bytes) -> None:
    path.write_bytes(raw)
    os.chmod(path, 0o600)


def generate(input_path: Path | str, output_dir: Path | str) -> dict[str, Any]:
    """Validate all inputs before creating the private output directory."""
    source = Path(input_path)
    target = Path(output_dir)
    payload = _read_input(source)
    runtime, patched, env = _build(payload)
    if target.exists():
        raise ValueError("deployment output already exists")
    runtime_raw = json.dumps(runtime, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    go_raw = yaml.safe_dump(patched, allow_unicode=True, sort_keys=False).encode()
    env_raw = "".join(f"{key}={value}\n" for key, value in sorted(env.items())).encode()
    target.mkdir(mode=0o700, parents=True)
    files = {
        "runtime_json": ("product-ingestion-runtime.private.json", runtime_raw),
        "harness_env": ("product-ingestion.env.private", env_raw),
        "go_config": ("weknora-config.private.yaml", go_raw),
    }
    for _, (name, raw) in files.items():
        _private_write(target / name, raw)
    manifest = {
        "contract": "product-ingestion-deployment-output.830.v1",
        "scope_sha256": _sha256(_go_canonical(payload["scope"])),
        "harness_service_principal_sha256": _sha256(
            payload["harness_service"]["principal_id"].encode()
        ),
        "policy_sha256": go_policy_sha256(patched["g3_platform_processing"]),
        "trusted_file_sha256s": {
            name: row["sha256"] for name, row in sorted(payload["trusted_files"].items())
        },
        "files": {
            key: {"name": name, "sha256": _sha256(raw), "bytes": len(raw)}
            for key, (name, raw) in files.items()
        },
    }
    _private_write(
        target / "manifest.private.json",
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    generate(args.input, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
