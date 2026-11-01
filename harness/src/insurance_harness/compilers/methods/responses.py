"""Saved method answers, replayed by request digest: an offline completion port (Spec §7).

A missing answer is reported for its method and never sent: this port has no model behind it.
The live stage, with its call ledger and budget, joins in SK-2b.
"""

from pathlib import Path

from insurance_harness.compilers.schema_fields.prompt import JudgeLikeRequest


class ResponseMissing(Exception):
    """No saved answer for this request."""


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
