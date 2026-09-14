import pytest
from pydantic import ValidationError

from insurance_harness.product_ingestion.configuration import PlatformConnectionSettings


def settings(limit):
    return PlatformConnectionSettings(
        base_url="http://platform.invalid",
        machine_key="fixture-machine-key",
        timeout_seconds=120,
        max_response_bytes=limit,
    )


@pytest.mark.parametrize("mib", [64, 128, 192])
def test_signed_native_snapshot_has_a_finite_internal_transport_budget(mib):
    assert settings(mib * 1024 * 1024).max_response_bytes == mib * 1024 * 1024


@pytest.mark.parametrize("limit", [0, -1, 192 * 1024 * 1024 + 1])
def test_internal_snapshot_budget_cannot_be_disabled_or_unbounded(limit):
    with pytest.raises(ValidationError):
        settings(limit)
