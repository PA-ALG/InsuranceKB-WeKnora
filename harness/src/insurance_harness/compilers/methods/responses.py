"""Saved method answers, replayed by request digest (SK-2 Spec §7, SK-2c Spec §3.1, §4.1).

Two completion ports, neither with a model behind it; a missing answer is reported for its method
and never sent:

- `SavedResponses`: a directory prepared by hand (SK-2a's offline interface): answers are read as
  files, under the model name the caller gives. Never for a live submission.
- `LedgerAnswers`: a value directory `methods values` wrote. An answer counts only when the
  directory's ledger holds the successful call that returned it: the record's request digest is
  that of this request's body under the directory's stage (`stage.json`), its answer digest is
  that of the file, and its model is the directory's one. Anything else is refused as corrupt
  (RUN_ROOT_INVALID), so the values and the model the Claims name come from a recorded call.

A value directory is checked by one function before a value run sends or writes and before a
compile reads (`check_value_directory`); a saved answer is never opened through a link.
"""

from pathlib import Path

from insurance_harness.compilers.schema_fields.prompt import JudgeLikeRequest
from insurance_harness.models import StageModelConfig
from insurance_harness.models.answers import answer_model
from insurance_harness.models.durable import stored_records
from insurance_harness.models.openai_compatible import request_sha256
from insurance_harness.models.run_files import IntegrityError as ResponsesError
from insurance_harness.models.run_files import check_directory, read_regular

__all__ = ["ResponseMissing", "ResponsesError", "SavedResponses", "LedgerAnswers",
           "check_value_directory", "directory_stage", "is_value_directory", "STAGE_FILE"]

STAGE_FILE = "stage.json"
class ResponseMissing(Exception):
    """No saved answer for this request."""


class SavedResponses:
    def __init__(self, directory: Path, model: str) -> None:
        check_value_directory(directory)
        self.directory, self._model = directory, model

    @property
    def model(self) -> str:
        return self._model

    def complete(self, *, system: str, user: str) -> str:
        digest = JudgeLikeRequest(system=system, user=user).sha256
        content = read_regular(self.directory / f"{digest}.txt")
        if content is None:
            raise ResponseMissing()
        return content.decode("utf-8")


def check_value_directory(root: Path) -> None:
    """Method values have one flat raw/ child; the common guard owns safe path validation."""
    check_directory(root, directories=frozenset({"raw"}))


def directory_stage(directory: Path) -> StageModelConfig | None:
    """The stage a value directory was created with, or None when it has none."""
    content = read_regular(directory / STAGE_FILE)  # a link or special file is refused
    if content is None:
        return None
    try:
        return StageModelConfig.model_validate_json(content)
    except ValueError:
        raise ResponsesError("RUN_ROOT_INVALID") from None


def is_value_directory(directory: Path) -> bool:
    """Whether `methods values` wrote here (a stage file or a ledger): then answers need backing."""
    return any((directory / name).exists() for name in (STAGE_FILE, "ledger.jsonl"))


class LedgerAnswers:
    """The answers of a value directory, each backed by the ledger record of its call."""

    def __init__(self, directory: Path, model: str | None = None) -> None:
        check_value_directory(directory)
        stage = directory_stage(directory)
        if stage is None:
            raise ResponsesError("RUN_ROOT_INVALID")  # a ledger without the stage it was sent with
        try:
            records = stored_records(directory)
        except (OSError, ValueError):
            raise ResponsesError("RUN_ROOT_INVALID") from None
        identity = (stage.stage, stage.model, stage.policy_version)
        served = {record.served_model for record in records if record.served_model}
        if len(served) > 1 or any(
            (r.stage, r.model, r.policy_version) != identity for r in records
        ):
            raise ResponsesError("RUN_ROOT_INVALID")
        self.directory, self.stage = directory, stage
        self._model = next(iter(served), stage.model)
        if model is not None and model != self._model:
            raise ResponsesError("MODEL_MISMATCH")
        self._records = records

    @property
    def model(self) -> str:
        return self._model

    def answer(self, *, system: str, user: str) -> str | None:
        """The saved answer to this request once its call's record backs it; None without one."""
        path = self.directory / f"{JudgeLikeRequest(system=system, user=user).sha256}.txt"
        content = read_regular(path)
        if content is None:
            return None
        model = answer_model(self._records, self.stage,
                             request_sha256(self.stage, system=system, user=user), content)
        if model != self._model:
            raise ResponsesError("RUN_ROOT_INVALID")
        return content.decode("utf-8")

    def complete(self, *, system: str, user: str) -> str:
        text = self.answer(system=system, user=user)
        if text is None:
            raise ResponseMissing()
        return text
