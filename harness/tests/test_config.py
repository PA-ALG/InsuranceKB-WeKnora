"""S2.1 配置：必填缺失即失败（fail fast），环境变量注入。"""

import pytest
from pydantic import ValidationError

from insurance_harness.config import HarnessSettings


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for key in list(os.environ):
        if key.startswith("HARNESS_"):
            monkeypatch.delenv(key, raising=False)


def test_s2_1_missing_required_raises_at_instantiation(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    with pytest.raises(ValidationError):
        HarnessSettings()  # type: ignore[call-arg]


def test_s2_1_reads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", "http://wk.internal")
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "sk-env")
    s = HarnessSettings()  # type: ignore[call-arg]
    assert s.weknora_base_url == "http://wk.internal"
    assert s.weknora_api_key == "sk-env"
    assert s.retry_max_attempts == 3  # 默认值


def test_s2_1_defaults(settings: HarnessSettings) -> None:
    assert settings.poll_interval_s == 0.01
    assert settings.http_timeout_s == 30.0
