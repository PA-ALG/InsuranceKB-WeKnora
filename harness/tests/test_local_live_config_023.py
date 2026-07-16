"""OpenSpec 023 R1.1/R1.2: local-live model configuration contracts."""

from pathlib import Path

import pytest

from insurance_harness.live_env.config import LocalLiveConfig, load_local_live_config

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_config(path: Path) -> LocalLiveConfig:
    return load_local_live_config(path)


def _write_valid_config(path: Path, *, extraction_model: str) -> None:
    path.write_text(
        "\n".join(
            (
                "LOCAL_LIVE_WEKNORA_CHAT_BASE_URL=https://models.example/v1",
                "LOCAL_LIVE_WEKNORA_CHAT_API_KEY=chat-secret",
                "LOCAL_LIVE_WEKNORA_CHAT_MODEL=deepseek-v4-flash",
                "LOCAL_LIVE_WEKNORA_CHAT_PROVIDER=aliyun",
                "LOCAL_LIVE_WEKNORA_CHAT_PROTOCOL=openai_compatible",
                "LOCAL_LIVE_WEKNORA_EMBEDDING_BASE_URL=https://models.example/v1",
                "LOCAL_LIVE_WEKNORA_EMBEDDING_API_KEY=embedding-secret",
                "LOCAL_LIVE_WEKNORA_EMBEDDING_MODEL=qwen3.7-text-embedding",
                "LOCAL_LIVE_WEKNORA_EMBEDDING_PROVIDER=aliyun",
                "LOCAL_LIVE_WEKNORA_EMBEDDING_PROTOCOL=openai_compatible",
                "LOCAL_LIVE_WEKNORA_RERANK_BASE_URL=https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
                "LOCAL_LIVE_WEKNORA_RERANK_API_KEY=rerank-secret",
                "LOCAL_LIVE_WEKNORA_RERANK_MODEL=qwen3-rerank",
                "LOCAL_LIVE_WEKNORA_RERANK_PROVIDER=aliyun",
                "LOCAL_LIVE_WEKNORA_RERANK_PROTOCOL=dashscope_native",
                "LOCAL_LIVE_WEKNORA_VLLM_BASE_URL=https://models.example/v1",
                "LOCAL_LIVE_WEKNORA_VLLM_API_KEY=vlm-secret",
                "LOCAL_LIVE_WEKNORA_VLLM_MODEL=qwen3.7-plus",
                "LOCAL_LIVE_WEKNORA_VLLM_PROVIDER=aliyun",
                "LOCAL_LIVE_WEKNORA_VLLM_PROTOCOL=openai_compatible",
                "HARNESS_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1",
                "HARNESS_LLM_API_KEY=bailian-secret",
                f"HARNESS_LLM_MODEL_WEAK={extraction_model}",
                "HARNESS_LLM_PROVIDER=aliyun",
                "HARNESS_LLM_PROTOCOL=openai_compatible",
            )
        )
        + "\n"
    )
    path.chmod(0o600)


def test_r1_1_bailian_deepseek_extraction_profile_is_independently_configurable(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "first.env"
    second_path = tmp_path / "second.env"
    _write_valid_config(first_path, extraction_model="deepseek-v4-flash")
    _write_valid_config(second_path, extraction_model="deepseek-v4-pro")

    first = _load_config(first_path)
    second = _load_config(second_path)

    assert first.extraction.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert first.extraction.model == "deepseek-v4-flash"
    assert second.extraction.model == "deepseek-v4-pro"
    assert first.weknora_chat == second.weknora_chat
    assert first.weknora_embedding == second.weknora_embedding
    assert first.weknora_rerank == second.weknora_rerank
    assert first.weknora_vllm == second.weknora_vllm


def test_r1_2_five_profiles_have_explicit_independent_provider_and_protocol(
    tmp_path: Path,
) -> None:
    path = tmp_path / "profiles.env"
    _write_valid_config(path, extraction_model="deepseek-v4-flash")

    config = _load_config(path)

    profiles = {
        "weknora_chat": config.weknora_chat,
        "weknora_embedding": config.weknora_embedding,
        "weknora_rerank": config.weknora_rerank,
        "weknora_vllm": config.weknora_vllm,
        "extraction": config.extraction,
    }
    assert {profile.provider for profile in profiles.values()} == {"aliyun"}
    assert {
        role: profile.protocol for role, profile in profiles.items()
    } == {
        "weknora_chat": "openai_compatible",
        "weknora_embedding": "openai_compatible",
        "weknora_rerank": "dashscope_native",
        "weknora_vllm": "openai_compatible",
        "extraction": "openai_compatible",
    }
    assert config.weknora_vllm.model == "qwen3.7-plus"
    assert len(
        {profile.api_key.get_secret_value() for profile in profiles.values()}
    ) == len(profiles)


@pytest.mark.parametrize(
    "missing_key",
    (
        "LOCAL_LIVE_WEKNORA_CHAT_PROVIDER",
        "LOCAL_LIVE_WEKNORA_CHAT_PROTOCOL",
        "LOCAL_LIVE_WEKNORA_EMBEDDING_PROVIDER",
        "LOCAL_LIVE_WEKNORA_EMBEDDING_PROTOCOL",
        "LOCAL_LIVE_WEKNORA_RERANK_PROVIDER",
        "LOCAL_LIVE_WEKNORA_RERANK_PROTOCOL",
        "LOCAL_LIVE_WEKNORA_VLLM_PROVIDER",
        "LOCAL_LIVE_WEKNORA_VLLM_PROTOCOL",
        "HARNESS_LLM_PROVIDER",
        "HARNESS_LLM_PROTOCOL",
    ),
)
def test_r1_2_missing_provider_or_protocol_fails_closed(
    tmp_path: Path,
    missing_key: str,
) -> None:
    path = tmp_path / "missing.env"
    _write_valid_config(path, extraction_model="deepseek-v4-flash")
    path.write_text(
        "\n".join(
            line
            for line in path.read_text().splitlines()
            if not line.startswith(f"{missing_key}=")
        )
        + "\n"
    )
    path.chmod(0o600)

    with pytest.raises(ValueError, match=f"required setting: {missing_key}"):
        _load_config(path)


@pytest.mark.parametrize(
    ("setting", "invalid_value"),
    (
        ("LOCAL_LIVE_WEKNORA_CHAT_PROVIDER", "siliconflow"),
        ("LOCAL_LIVE_WEKNORA_EMBEDDING_PROVIDER", "siliconflow"),
        ("LOCAL_LIVE_WEKNORA_RERANK_PROVIDER", "siliconflow"),
        ("LOCAL_LIVE_WEKNORA_VLLM_PROVIDER", "siliconflow"),
        ("HARNESS_LLM_PROVIDER", "siliconflow"),
        ("LOCAL_LIVE_WEKNORA_CHAT_PROTOCOL", "dashscope_native"),
        ("LOCAL_LIVE_WEKNORA_EMBEDDING_PROTOCOL", "dashscope_native"),
        ("LOCAL_LIVE_WEKNORA_RERANK_PROTOCOL", "openai_compatible"),
        ("LOCAL_LIVE_WEKNORA_VLLM_PROTOCOL", "dashscope_native"),
        ("HARNESS_LLM_PROTOCOL", "dashscope_native"),
    ),
)
def test_r1_2_wrong_provider_or_protocol_fails_closed(
    tmp_path: Path,
    setting: str,
    invalid_value: str,
) -> None:
    path = tmp_path / "invalid-profile.env"
    _write_valid_config(path, extraction_model="deepseek-v4-flash")
    lines = path.read_text().splitlines()
    path.write_text(
        "\n".join(
            f"{setting}={invalid_value}" if line.startswith(f"{setting}=") else line
            for line in lines
        )
        + "\n"
    )
    path.chmod(0o600)

    with pytest.raises(ValueError, match=f"{setting}.*invalid"):
        _load_config(path)


def test_r1_1_local_model_credentials_require_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "insecure.env"
    _write_valid_config(path, extraction_model="deepseek-v4-flash")
    path.chmod(0o644)

    with pytest.raises(ValueError, match="permission"):
        _load_config(path)


def test_r1_1_duplicate_model_setting_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.env"
    _write_valid_config(path, extraction_model="deepseek-v4-flash")
    with path.open("a") as stream:
        stream.write("HARNESS_LLM_MODEL_WEAK=unexpected-shadow\n")

    with pytest.raises(ValueError, match="duplicate.*HARNESS_LLM_MODEL_WEAK"):
        _load_config(path)


def test_r1_1_remote_model_gateway_requires_https(tmp_path: Path) -> None:
    path = tmp_path / "http.env"
    _write_valid_config(path, extraction_model="deepseek-v4-flash")
    text = path.read_text().replace(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "http://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    path.write_text(text)
    path.chmod(0o600)

    with pytest.raises(ValueError, match="HARNESS_LLM_BASE_URL.*HTTPS"):
        _load_config(path)


def test_r1_1_malformed_secret_line_is_not_leaked(tmp_path: Path) -> None:
    path = tmp_path / "malformed.env"
    path.write_text("sk-super-secret-without-name\n")
    path.chmod(0o600)

    with pytest.raises(ValueError) as failure:
        _load_config(path)

    assert "sk-super-secret" not in str(failure.value)


def test_r1_1_unknown_security_sensitive_alias_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "alias.env"
    _write_valid_config(path, extraction_model="deepseek-v4-flash")
    with path.open("a") as stream:
        stream.write("BAILIAN_API_KEY=shadow-secret\n")

    with pytest.raises(ValueError, match="unknown.*BAILIAN_API_KEY") as failure:
        _load_config(path)

    assert "shadow-secret" not in str(failure.value)


def test_r1_1_empty_required_model_value_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "empty.env"
    _write_valid_config(path, extraction_model="deepseek-v4-flash")
    path.write_text(
        path.read_text().replace(
            "HARNESS_LLM_API_KEY=bailian-secret", "HARNESS_LLM_API_KEY="
        )
    )
    path.chmod(0o600)

    with pytest.raises(ValueError, match="EMPTY.*HARNESS_LLM_API_KEY"):
        _load_config(path)


def test_r1_2_tracked_example_pins_bailian_profiles_without_real_secrets() -> None:
    path = REPO_ROOT / ".env.local-live.example"
    assert path.is_file(), "R1.2 tracked local-live example is missing"
    example = path.read_text()

    assert (
        "HARNESS_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1"
        in example
    )
    assert "HARNESS_LLM_MODEL_WEAK=deepseek-v4-flash" in example
    assert "HARNESS_LLM_PROVIDER=aliyun" in example
    assert "HARNESS_LLM_PROTOCOL=openai_compatible" in example
    expected_models = {
        "CHAT": "deepseek-v4-flash",
        "EMBEDDING": "qwen3.7-text-embedding",
        "RERANK": "qwen3-rerank",
        "VLLM": "qwen3.7-plus",
    }
    expected_protocols = {
        "CHAT": "openai_compatible",
        "EMBEDDING": "openai_compatible",
        "RERANK": "dashscope_native",
        "VLLM": "openai_compatible",
    }
    for role in expected_models:
        assert f"LOCAL_LIVE_WEKNORA_{role}_BASE_URL=" in example
        assert f"LOCAL_LIVE_WEKNORA_{role}_API_KEY=" in example
        assert f"LOCAL_LIVE_WEKNORA_{role}_MODEL={expected_models[role]}" in example
        assert f"LOCAL_LIVE_WEKNORA_{role}_PROVIDER=aliyun" in example
        assert (
            f"LOCAL_LIVE_WEKNORA_{role}_PROTOCOL={expected_protocols[role]}"
            in example
        )
    assert (
        "LOCAL_LIVE_WEKNORA_RERANK_BASE_URL=https://dashscope.aliyuncs.com/"
        "api/v1/services/rerank/text-rerank/text-rerank"
    ) in example
    assert "siliconflow" not in example.lower()
    assert "sk-xxxx" not in example
    assert "_API_KEY=\n" in example


@pytest.mark.parametrize(
    "invalid_url",
    (
        "https://user:password@models.example/v1",
        "https://models.example/v1?api_key=secret",
        "https:///missing-host",
    ),
)
def test_r1_1_model_gateway_rejects_credential_bearing_or_malformed_url(
    tmp_path: Path,
    invalid_url: str,
) -> None:
    path = tmp_path / "invalid-url.env"
    _write_valid_config(path, extraction_model="deepseek-v4-flash")
    path.write_text(path.read_text().replace("https://models.example/v1", invalid_url))
    path.chmod(0o600)

    with pytest.raises(ValueError, match="BASE_URL.*HTTPS"):
        _load_config(path)


def test_r1_1_config_repr_hides_urls_and_credentials(tmp_path: Path) -> None:
    path = tmp_path / "redacted.env"
    _write_valid_config(path, extraction_model="deepseek-v4-flash")

    rendered = repr(_load_config(path))

    for forbidden in (
        "https://",
        "chat-secret",
        "embedding-secret",
        "rerank-secret",
        "vlm-secret",
        "bailian-secret",
    ):
        assert forbidden not in rendered
