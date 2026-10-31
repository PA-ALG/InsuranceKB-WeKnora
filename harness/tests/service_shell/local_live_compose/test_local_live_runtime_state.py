"""Local-live runtime state, verifiers and the six-image lock."""

from __future__ import annotations

import json
from pathlib import Path
from stat import S_IMODE

import pytest

from insurance_harness.live_env import compose as compose_module
from insurance_harness.live_env.compose import (
    ComposeVerificationError,
)
from tests.service_shell.local_live_compose.helpers import REPO_ROOT, _runtime_values

T6D_2_IMAGES = {
    "app": (
        "ghcr.io/pa-alg/insurancekb-weknora-app:"
        "src-a8bf55ae1844-lock-55bb545f43a4@"
        "sha256:37dfa969939cd9e48e4f65fcabee49920ecb28139d584bf000a2355ac5cf1d55"
    ),
    "frontend": (
        "ghcr.io/pa-alg/insurancekb-weknora-frontend:"
        "src-a8bf55ae1844-lock-55bb545f43a4@"
        "sha256:5e5555166307ab65f4b9b118766c778231c81a0b1aff2326c3da7a99f2527243"
    ),
    "docreader": (
        "ghcr.io/pa-alg/insurancekb-weknora-docreader:"
        "src-a8bf55ae1844-lock-55bb545f43a4@"
        "sha256:418de99a454fdfee1592cc8346fad6f8e2601ed27107561aa745474d94b8b207"
    ),
}


def test_r3_1_runtime_state_is_complete_atomic_and_preserves_credentials(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".env.local-live.runtime"
    compose_module.ensure_runtime_environment(path)
    before = _runtime_values(path)
    state = {
        "LOCAL_LIVE_TENANT_ID": "tenant-1",
        "LOCAL_LIVE_CHAT_MODEL_ID": "chat-1",
        "LOCAL_LIVE_EMBEDDING_MODEL_ID": "embedding-1",
        "LOCAL_LIVE_RERANK_MODEL_ID": "rerank-1",
        "LOCAL_LIVE_VLLM_MODEL_ID": "vlm-1",
        "LOCAL_LIVE_CHAT_ENDPOINT_FINGERPRINT": "a" * 64,
        "LOCAL_LIVE_EMBEDDING_ENDPOINT_FINGERPRINT": "b" * 64,
        "LOCAL_LIVE_RERANK_ENDPOINT_FINGERPRINT": "c" * 64,
        "LOCAL_LIVE_VLLM_ENDPOINT_FINGERPRINT": "d" * 64,
        "LOCAL_LIVE_RAW_KB_ID": "raw-1",
        "LOCAL_LIVE_WIKI_KB_ID": "wiki-1",
        "LOCAL_LIVE_API_KEY_ID": "key-1",
        "LOCAL_LIVE_SPACE_ID": "space-1",
        "LOCAL_LIVE_KNOWLEDGE_ID": "knowledge-1",
        "LOCAL_LIVE_PARSER_FINGERPRINT": "weknora-v0.6.3",
    }

    compose_module.update_runtime_state(path, state)

    after = _runtime_values(path)
    assert {name: after[name] for name in before} == before
    assert {name: after[name] for name in state} == state
    assert S_IMODE(path.stat().st_mode) == 0o600
    assert compose_module.ensure_runtime_environment(path).created is False


def test_r3_3_runtime_state_rejects_persistent_api_key_material(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".env.local-live.runtime"
    compose_module.ensure_runtime_environment(path)
    state = {
        "LOCAL_LIVE_TENANT_ID": "tenant-1",
        "LOCAL_LIVE_CHAT_MODEL_ID": "chat-1",
        "LOCAL_LIVE_EMBEDDING_MODEL_ID": "embedding-1",
        "LOCAL_LIVE_RERANK_MODEL_ID": "rerank-1",
        "LOCAL_LIVE_VLLM_MODEL_ID": "vlm-1",
        "LOCAL_LIVE_CHAT_ENDPOINT_FINGERPRINT": "a" * 64,
        "LOCAL_LIVE_EMBEDDING_ENDPOINT_FINGERPRINT": "b" * 64,
        "LOCAL_LIVE_RERANK_ENDPOINT_FINGERPRINT": "c" * 64,
        "LOCAL_LIVE_VLLM_ENDPOINT_FINGERPRINT": "d" * 64,
        "LOCAL_LIVE_RAW_KB_ID": "raw-1",
        "LOCAL_LIVE_WIKI_KB_ID": "wiki-1",
        "LOCAL_LIVE_API_KEY_ID": "key-1",
        "LOCAL_LIVE_SPACE_ID": "space-1",
        "LOCAL_LIVE_KNOWLEDGE_ID": "knowledge-1",
        "LOCAL_LIVE_PARSER_FINGERPRINT": "weknora-v0.6.3",
        "LOCAL_LIVE_API_KEY": "must-never-persist",
    }

    with pytest.raises(ValueError, match="runtime state.*complete"):
        compose_module.update_runtime_state(path, state)

    assert b"must-never-persist" not in path.read_bytes()


def test_r3_3_legacy_runtime_state_is_atomically_rewritten_without_api_key(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".env.local-live.runtime"
    compose_module.ensure_runtime_environment(path)
    values = {
        **_runtime_values(path),
        "LOCAL_LIVE_TENANT_ID": "tenant-1",
        "LOCAL_LIVE_CHAT_MODEL_ID": "chat-1",
        "LOCAL_LIVE_EMBEDDING_MODEL_ID": "embedding-1",
        "LOCAL_LIVE_RERANK_MODEL_ID": "rerank-1",
        "LOCAL_LIVE_VLLM_MODEL_ID": "vlm-1",
        "LOCAL_LIVE_CHAT_ENDPOINT_FINGERPRINT": "a" * 64,
        "LOCAL_LIVE_EMBEDDING_ENDPOINT_FINGERPRINT": "b" * 64,
        "LOCAL_LIVE_RERANK_ENDPOINT_FINGERPRINT": "c" * 64,
        "LOCAL_LIVE_VLLM_ENDPOINT_FINGERPRINT": "d" * 64,
        "LOCAL_LIVE_RAW_KB_ID": "raw-1",
        "LOCAL_LIVE_WIKI_KB_ID": "wiki-1",
        "LOCAL_LIVE_API_KEY_ID": "key-1",
        "LOCAL_LIVE_API_KEY": "legacy-secret-to-remove",
        "LOCAL_LIVE_SPACE_ID": "space-1",
        "LOCAL_LIVE_KNOWLEDGE_ID": "knowledge-1",
        "LOCAL_LIVE_PARSER_FINGERPRINT": "weknora-v0.6.3",
    }
    path.write_text("".join(f"{name}={value}\n" for name, value in values.items()))

    compose_module.ensure_runtime_environment(path)

    rewritten = _runtime_values(path)
    assert "LOCAL_LIVE_API_KEY" not in rewritten
    assert "legacy-secret-to-remove" not in path.read_text()
    assert S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "invalid_fingerprint",
    ("a" * 63, "A" * 64, "https://models.example/v1"),
)
def test_r3_3_runtime_rejects_noncanonical_endpoint_fingerprint(
    tmp_path: Path,
    invalid_fingerprint: str,
) -> None:
    path = tmp_path / ".env.local-live.runtime"
    compose_module.ensure_runtime_environment(path)
    state = {
        "LOCAL_LIVE_TENANT_ID": "tenant-1",
        "LOCAL_LIVE_CHAT_MODEL_ID": "chat-1",
        "LOCAL_LIVE_EMBEDDING_MODEL_ID": "embedding-1",
        "LOCAL_LIVE_RERANK_MODEL_ID": "rerank-1",
        "LOCAL_LIVE_VLLM_MODEL_ID": "vlm-1",
        "LOCAL_LIVE_CHAT_ENDPOINT_FINGERPRINT": invalid_fingerprint,
        "LOCAL_LIVE_EMBEDDING_ENDPOINT_FINGERPRINT": "b" * 64,
        "LOCAL_LIVE_RERANK_ENDPOINT_FINGERPRINT": "c" * 64,
        "LOCAL_LIVE_VLLM_ENDPOINT_FINGERPRINT": "d" * 64,
        "LOCAL_LIVE_RAW_KB_ID": "raw-1",
        "LOCAL_LIVE_WIKI_KB_ID": "wiki-1",
        "LOCAL_LIVE_API_KEY_ID": "key-1",
        "LOCAL_LIVE_SPACE_ID": "space-1",
        "LOCAL_LIVE_KNOWLEDGE_ID": "knowledge-1",
        "LOCAL_LIVE_PARSER_FINGERPRINT": "weknora-v0.6.3",
    }

    with pytest.raises(ValueError, match="endpoint fingerprint"):
        compose_module.update_runtime_state(path, state)


def test_r3_1_partial_runtime_state_is_rejected_without_overwrite(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".env.local-live.runtime"
    compose_module.ensure_runtime_environment(path)
    original = path.read_bytes()

    with pytest.raises(ValueError, match="runtime state.*complete"):
        compose_module.update_runtime_state(
            path,
            {"LOCAL_LIVE_TENANT_ID": "tenant-1"},
        )

    assert path.read_bytes() == original


@pytest.mark.parametrize("invalid", ["insecure", "malformed", "example"])
def test_r2_1_runtime_environment_rejects_invalid_without_overwrite(
    tmp_path: Path, invalid: str
) -> None:
    path = tmp_path / ".env.local-live.runtime"
    compose_module.ensure_runtime_environment(path)
    if invalid == "insecure":
        path.chmod(0o644)
    elif invalid == "malformed":
        path.write_text(path.read_text() + "not-a-setting\n")
    else:
        path.write_text(
            path.read_text().replace(
                f"DB_PASSWORD={_runtime_values(path)['DB_PASSWORD']}",
                "DB_PASSWORD=password",
            )
        )
    original = path.read_bytes()
    original_mode = S_IMODE(path.stat().st_mode)

    with pytest.raises(ValueError, match="runtime environment.*invalid"):
        compose_module.ensure_runtime_environment(path)

    assert path.read_bytes() == original
    assert S_IMODE(path.stat().st_mode) == original_mode


def test_r2_1_harness_verifier_requires_its_single_service(
    compliant_lock: dict[str, str],
) -> None:
    assert hasattr(
        compose_module, "verify_harness_compose"
    ), "R2.1 Harness service verifier is missing"

    with pytest.raises(ComposeVerificationError, match="missing core service.*harness"):
        compose_module.verify_harness_compose({"services": {}}, compliant_lock)


def test_r2_1_six_image_lock_is_resolved_and_matches_overrides() -> None:
    lock = json.loads((REPO_ROOT / "deploy/local-live/images.lock").read_text())
    assert set(lock) == {
        "_status",
        "frontend",
        "app",
        "docreader",
        "postgres",
        "redis",
        "harness-postgres",
    }
    assert lock["_status"] == "RESOLVED_2026-07-28"
    assert all(
        value.count("@sha256:") == 1 and "UNRESOLVED" not in value
        for key, value in lock.items()
        if key != "_status"
    )
    override_text = "\n".join(
        (
            (REPO_ROOT / "deploy/local-live/docker-compose.weknora.override.yml").read_text(),
            (REPO_ROOT / "deploy/local-live/docker-compose.harness.override.yml").read_text(),
        )
    )
    assert all(
        value in override_text for key, value in lock.items() if key != "_status"
    )


def test_t6d_2_r2_1_images_lock_and_compose_use_verified_manifest_digests() -> None:
    lock = json.loads((REPO_ROOT / "deploy/local-live/images.lock").read_text())
    override = (
        REPO_ROOT / "deploy/local-live/docker-compose.weknora.override.yml"
    ).read_text()

    for image_id, expected in T6D_2_IMAGES.items():
        assert lock[image_id] == expected
        assert f"image: {expected}" in override
