"""Reject ambiguous or secret-bearing configuration before constructing a client."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from insurance_harness.models import (
    CallLedger,
    ModelConfigError,
    StageModelConfig,
    load_stage_config,
)


def stage(**changes: object) -> StageModelConfig:
    return StageModelConfig.model_validate({
        "stage": "extract", "provider": "example", "base_url": "https://example.com/v1/",
        "model": "test-model", "api_key_env": "MODEL_KEY", "max_tokens": 2048,
        "policy_version": "test.1", **changes,
    })


@pytest.mark.parametrize("changes", [
    {"stage": " "}, {"provider": "\n"}, {"model": ""}, {"policy_version": ""},
    {"api_key_env": "KEY\n"}, {"max_tokens": True}, {"max_attempts": 0},
    {"timeout_s": float("inf")}, {"temperature": float("nan")},
    {"max_input_chars": True}, {"base_url": "https:///path"},
    {"base_url": "https://user:secret@example.com"},
    {"base_url": "https://example.com/?key=secret"},
    {"base_url": "https://example.com/#secret"},
])
def test_configuration_fails_closed(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        stage(**changes)


def test_configuration_is_frozen() -> None:
    value = stage()
    with pytest.raises(ValidationError):
        value.max_tokens = 4096


@pytest.mark.parametrize("changes", [
    {"api_key": "PRIVATE"}, {"base_url": "https://user:PRIVATE@example.com"},
])
def test_direct_validation_errors_hide_rejected_input(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as caught:
        stage(**changes)
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("data", [
    "not-json", "[]", '{"stages": [], "api_key": "PRIVATE"}',
    '{"stages": [], "stages": []}',
    '{"stages": [{"api_key": "PRIVATE"}]}',
])
def test_load_errors_do_not_echo_paths_or_values(tmp_path: Path, data: str) -> None:
    path = tmp_path / "PRIVATE.json"
    path.write_text(data, encoding="utf-8")
    with pytest.raises(ModelConfigError) as caught:
        load_stage_config(path, "extract")
    assert "PRIVATE" not in str(caught.value)
    assert str(tmp_path) not in str(caught.value)


def test_invalid_unselected_stage_is_not_ignored(tmp_path: Path) -> None:
    path = tmp_path / "stages.json"
    path.write_text(json.dumps({"stages": [
        stage().model_dump(), {**stage().model_dump(), "stage": "review", "timeout_s": 0},
    ]}), encoding="utf-8")
    with pytest.raises(ModelConfigError):
        load_stage_config(path, "extract")


@pytest.mark.parametrize("limit", [-1, True, 1.5])
def test_send_limit_rejects_invalid_numbers(limit: int) -> None:
    with pytest.raises(ValueError):
        CallLedger(max_sent=limit)
