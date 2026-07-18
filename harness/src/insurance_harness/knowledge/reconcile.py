"""Typed reconciliation result for OpenSpec 018 recovery workflows."""

from pydantic import BaseModel, ConfigDict

from insurance_harness.knowledge.pages import RenderedPage


class ReconcileResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_operation_id: str
    operation_id: str
    current_snapshot_id: str | None
    pages: tuple[RenderedPage, ...]
