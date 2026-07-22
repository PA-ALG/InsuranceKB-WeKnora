"""Temporary A-C safety gate for the locally reviewable 031 stack."""

from __future__ import annotations

from collections.abc import Callable
from typing import NoReturn

import pytest

import insurance_harness.goldenset.run_020 as run_020


def _unexpected(events: list[str], label: str) -> Callable[..., NoReturn]:
    def fail(*_args: object, **_kwargs: object) -> NoReturn:
        events.append(label)
        raise AssertionError(f"incomplete 031 stack reached {label}")

    return fail


def test_o8_a_to_c_production_entry_is_typed_blocked_before_all_runtime_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    for name in (
        "_production_configuration",
        "_load_production_document",
        "_build_production_evaluator",
        "_run_ready_command",
    ):
        monkeypatch.setattr(run_020, name, _unexpected(events, name))

    assert run_020.main(["baseline-product", "--product", "暂不可运行"]) == 2
    assert events == []
    with pytest.raises(run_020.OperationalAdmissionStackIncompleteError):
        run_020._require_complete_operational_admission_stack()
