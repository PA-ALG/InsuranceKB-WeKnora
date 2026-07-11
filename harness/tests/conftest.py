from collections.abc import AsyncIterator

import pytest

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.config import HarnessSettings

BASE_URL = "http://weknora.test"


@pytest.fixture
def settings() -> HarnessSettings:
    return HarnessSettings(
        weknora_base_url=BASE_URL,
        weknora_api_key="sk-test",
        poll_interval_s=0.01,
        poll_timeout_s=0.5,
        retry_max_attempts=3,
    )


@pytest.fixture
async def client(settings: HarnessSettings) -> AsyncIterator[WeKnoraClient]:
    c = WeKnoraClient(settings)
    yield c
    await c.aclose()
