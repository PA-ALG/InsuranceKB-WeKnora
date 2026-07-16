"""OpenSpec 023 R1.1: local-live model configuration contracts."""

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
                "LOCAL_LIVE_WEKNORA_CHAT_MODEL=MiniMaxAI/MiniMax-M2.5",
                "LOCAL_LIVE_WEKNORA_EMBEDDING_BASE_URL=https://models.example/v1",
                "LOCAL_LIVE_WEKNORA_EMBEDDING_API_KEY=embedding-secret",
                "LOCAL_LIVE_WEKNORA_EMBEDDING_MODEL=Qwen/Qwen3-VL-Embedding-8B",
                "LOCAL_LIVE_WEKNORA_RERANK_BASE_URL=https://models.example/v1",
                "LOCAL_LIVE_WEKNORA_RERANK_API_KEY=rerank-secret",
                "LOCAL_LIVE_WEKNORA_RERANK_MODEL=Qwen/Qwen3-VL-Reranker-8B",
                "HARNESS_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1",
                "HARNESS_LLM_API_KEY=bailian-secret",
                f"HARNESS_LLM_MODEL_WEAK={extraction_model}",
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


def test_r1_1_tracked_example_names_every_model_role_without_real_secrets() -> None:
    path = REPO_ROOT / ".env.local-live.example"
    assert path.is_file(), "R1.1 tracked local-live example is missing"
    example = path.read_text()

    assert "HARNESS_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1" in example
    assert "HARNESS_LLM_MODEL_WEAK=deepseek-v4-flash" in example
    for role in ("CHAT", "EMBEDDING", "RERANK"):
        assert f"LOCAL_LIVE_WEKNORA_{role}_BASE_URL=" in example
        assert f"LOCAL_LIVE_WEKNORA_{role}_API_KEY=" in example
        assert f"LOCAL_LIVE_WEKNORA_{role}_MODEL=" in example
    assert "sk-xxxx" not in example


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

    for forbidden in ("https://", "chat-secret", "embedding-secret", "bailian-secret"):
        assert forbidden not in rendered
