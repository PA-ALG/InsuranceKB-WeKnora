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

import hashlib
import os
import stat
from pathlib import Path
from typing import Any

from insurance_harness.compilers.schema_fields.prompt import JudgeLikeRequest
from insurance_harness.models import StageModelConfig
from insurance_harness.models.durable import stored_records
from insurance_harness.models.openai_compatible import request_sha256

STAGE_FILE = "stage.json"
# Settings that do not enter the request body: changing them keeps a value directory.
_OPERATIONAL = frozenset({"timeout_s", "max_attempts", "api_key_env"})


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
        content = _read_regular(self.directory / f"{digest}.txt")
        if content is None:
            raise ResponseMissing()
        return content.decode("utf-8")


def check_value_directory(root: Path) -> None:
    """Neither the directory nor raw/ lies in a git work tree (each and its parents hold no .git);
    every entry of either is a regular file, besides the raw/ directory itself: no link (existing
    ones included), FIFO or other special file (Spec §3.1, R5). Only lstat: nothing is opened."""
    if _in_git(root):
        raise ResponsesError("RUN_ROOT_INVALID")
    if not root.is_dir():
        return  # a new directory: the value run creates it
    raw = root / "raw"
    for entry in root.iterdir():
        mode = entry.lstat().st_mode
        if entry == raw:
            if not stat.S_ISDIR(mode) or _in_git(raw):
                raise ResponsesError("RUN_ROOT_INVALID")
            if not all(stat.S_ISREG(kept.lstat().st_mode) for kept in raw.iterdir()):
                raise ResponsesError("RUN_ROOT_INVALID")
        elif not stat.S_ISREG(mode):
            raise ResponsesError("RUN_ROOT_INVALID")


def _in_git(path: Path) -> bool:
    resolved = path.resolve()
    return any((parent / ".git").exists() for parent in (resolved, *resolved.parents))


def _read_regular(path: Path) -> bytes | None:
    """A saved answer's bytes; None when there is none. Anything but a regular file is refused
    before it is opened (opening a FIFO without a writer would block, review #526 R5c); the open
    neither follows a link nor blocks, and the descriptor must be the very file lstat saw."""
    try:
        seen = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        raise ResponsesError("RUN_ROOT_INVALID") from None
    if not stat.S_ISREG(seen.st_mode):
        raise ResponsesError("RUN_ROOT_INVALID")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:  # replaced since: gone, a link (ELOOP) or unreadable
        raise ResponsesError("RUN_ROOT_INVALID") from None
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            seen.st_dev, seen.st_ino,
        ):
            raise ResponsesError("RUN_ROOT_INVALID")
        return stream.read()


def request_settings(config: StageModelConfig) -> dict[str, Any]:
    """What a value directory is bound to: every stage setting that shapes the request."""
    return {k: v for k, v in config.model_dump(mode="json").items() if k not in _OPERATIONAL}


def directory_stage(directory: Path) -> StageModelConfig | None:
    """The stage a value directory was created with, or None when it has none."""
    content = _read_regular(directory / STAGE_FILE)  # a link or special file is refused
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
        self._backed = {
            (r.request_sha256, r.response_sha256): r.served_model or r.model
            for r in records
            if r.outcome == "ok" and r.response_sha256 is not None
        }

    @property
    def model(self) -> str:
        return self._model

    def answer(self, *, system: str, user: str) -> str | None:
        """The saved answer to this request once its call's record backs it; None without one."""
        path = self.directory / f"{JudgeLikeRequest(system=system, user=user).sha256}.txt"
        content = _read_regular(path)
        if content is None:
            return None
        key = (
            request_sha256(self.stage, system=system, user=user),
            hashlib.sha256(content).hexdigest(),
        )
        if self._backed.get(key) != self._model:
            raise ResponsesError("RUN_ROOT_INVALID")  # altered, or not the answer of this request
        return content.decode("utf-8")

    def complete(self, *, system: str, user: str) -> str:
        text = self.answer(system=system, user=user)
        if text is None:
            raise ResponseMissing()
        return text
