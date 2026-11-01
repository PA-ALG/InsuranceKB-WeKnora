"""Saved method answers, replayed by request digest: an offline completion port (Spec §7).

A missing answer is reported for its method and never sent: this port has no model behind it.
The value stage (values.py, SK-2c) writes these answers on a model, with its call ledger and
budget in the same directory; `saved_model` reads from that ledger which model wrote them.
"""

from pathlib import Path

from insurance_harness.compilers.schema_fields.prompt import JudgeLikeRequest
from insurance_harness.models.durable import stored_records


class ResponseMissing(Exception):
    """No saved answer for this request."""


class ResponsesError(ValueError):
    """A fixed caller-safe code about the answers' directory."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SavedResponses:
    def __init__(self, directory: Path, model: str) -> None:
        self.directory, self._model = directory, model

    @property
    def model(self) -> str:
        return self._model

    def complete(self, *, system: str, user: str) -> str:
        digest = JudgeLikeRequest(system=system, user=user).sha256
        try:
            return (self.directory / f"{digest}.txt").read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ResponseMissing() from None


def saved_model(directory: Path) -> str | None:
    """The model that wrote a value directory's answers (SK-2c Spec §4.1), or None when its ledger
    records no successful call (a directory prepared by hand): the served version the provider
    reported, else the configured name. One directory holds one model; anything else is corrupt."""
    try:
        records = stored_records(directory)
    except (OSError, ValueError):
        raise ResponsesError("RUN_ROOT_INVALID") from None
    answered = [record for record in records if record.outcome == "ok"]
    served = {record.served_model for record in records if record.served_model}
    configured = {record.model for record in answered}
    if len(served) > 1 or len(configured) > 1:
        raise ResponsesError("RUN_ROOT_INVALID")
    if not answered:
        return None
    return next(iter(served or configured))
