"""Authorized checkpoint call references expose immutable ancestor provider raw."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from insurance_harness.product_ingestion.artifact_tables import ProductStageModelCall
from insurance_harness.product_ingestion.checkpoints import CallReference
from tests.product_ingestion.test_artifacts import _scope, api, factory  # noqa: F401
from tests.product_ingestion.test_discovery_replay_metrics import (
    _child,
    _digest,
    _record_parent_call,
)

# ruff: noqa: F811


def test_checkpoint_reader_keeps_authorized_ancestor_and_rejects_changed_bytes(
    api: Any,
    factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _record_parent_call(
        api,
        factory,
        stage_key="discovery",
        operation="native-test",
        context=b"context",
        prompt=b"prompt",
        raw=b"raw",
        call_id="original-native",
    )
    artifacts, products, _, middle, _ = _child(
        api,
        factory,
        stage_key="discovery",
        parent_run_id=original.run_id,
        run_key="native-middle",
    )
    artifacts, products, _, child, _ = _child(
        api,
        factory,
        stage_key="discovery",
        parent_run_id=middle.run_id,
        run_key="native-third",
    )
    with factory() as session:
        row = session.scalar(
            select(ProductStageModelCall).where(ProductStageModelCall.call_id == "original-native")
        )
        ref = CallReference(
            kind="stage",
            record_id=row.id,
            run_id=row.run_id,
            call_id=row.call_id,
            state=row.state,
            request_sha256=row.request_sha256,
            raw_sha256=row.raw_sha256,
        )
    plan = SimpleNamespace(calls=(), audited_calls=(ref,))
    # The independently covered planner owns reference authorization; this test
    # exercises the new reader against real rows, without faking call custody.
    monkeypatch.setattr(products, "checkpoint_plan", lambda **kw: plan)
    calls = artifacts.read_checkpoint_stage_calls(
        scope=_scope(), run_id=child.run_id, stage_key="discovery"
    )
    assert [(c.run_id, c.call_id, c.raw) for c in calls] == [
        (original.run_id, "original-native", b"raw")
    ]
    plan.audited_calls = ()
    assert (
        artifacts.read_checkpoint_stage_calls(
            scope=_scope(), run_id=child.run_id, stage_key="discovery"
        )
        == ()
    )
    plan.audited_calls = (ref,)
    with factory() as session, session.begin():
        row = session.get(ProductStageModelCall, ref.record_id)
        row.raw = b"changed"
        row.raw_sha256 = _digest(row.raw)
    with pytest.raises(ValueError, match="checkpoint.*changed"):
        artifacts.read_checkpoint_stage_calls(
            scope=_scope(), run_id=child.run_id, stage_key="discovery"
        )
