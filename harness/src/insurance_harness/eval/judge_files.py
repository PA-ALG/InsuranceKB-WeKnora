"""Exchange immutable blind requests and answers with a separate judge session."""

import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from insurance_harness.eval.judge import JudgeProtocolError, JudgeRequest


def check_run_directory(run_dir: Path) -> None:
    """Resolve symlinks before checking every ancestor for Git worktrees/repositories."""
    resolved = run_dir.resolve()
    if any((parent / ".git").exists() for parent in (resolved, *resolved.parents)):
        raise ValueError("judge run directory must be outside any git repository")


def write_requests(requests: Sequence[JudgeRequest], run_dir: Path) -> list[Path]:
    check_run_directory(run_dir)
    destination = run_dir / "requests"
    destination.mkdir(parents=True, exist_ok=False)
    (run_dir / "responses").mkdir(exist_ok=True)
    paths = []
    for number, request in enumerate(requests, 1):
        path = destination / f"{number:03d}.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump({
                "request_sha256": request.sha256,
                "system_lines": request.system.split("\n"),
                "user_lines": request.user.split("\n"),
            }, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        paths.append(path)
    return paths


class _StoredRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    request_sha256: str
    system_lines: list[str]
    user_lines: list[str]


class FileJudgeClient:
    def __init__(self, run_dir: Path, *, model_id: str) -> None:
        check_run_directory(run_dir)
        if not model_id.strip():
            raise ValueError("judge model must not be empty")
        self.run_dir = run_dir
        self._model_id = model_id
        self._consumed: set[str] = set()

    @property
    def model_id(self) -> str:
        return self._model_id

    def complete(self, request: JudgeRequest) -> str:
        number = f"{len(self._consumed) + 1:03d}"
        try:
            stored = _StoredRequest.model_validate_json(
                (self.run_dir / "requests" / f"{number}.json").read_text(encoding="utf-8"),
            )
            rebuilt = JudgeRequest("\n".join(stored.system_lines), "\n".join(stored.user_lines))
            if rebuilt.sha256 != stored.request_sha256 or rebuilt.sha256 != request.sha256:
                raise JudgeProtocolError(f"request {number} changed since prepare")
            response = (self.run_dir / "responses" / f"{number}.json").read_text(encoding="utf-8")
        except ValidationError as exc:
            raise JudgeProtocolError(f"request {number} changed or malformed") from exc
        except (OSError, UnicodeError) as exc:
            raise JudgeProtocolError(f"request/response {number} missing or unreadable") from exc
        self._consumed.add(number)
        return response

    def unconsumed(self) -> list[str]:
        return sorted(
            path.stem for path in (self.run_dir / "requests").glob("*.json")
            if path.stem not in self._consumed
        )
