"""Private answer journals backed by actual HTTP-call records, shared by run owners.

No compiler dependencies. Files are immutable; an acceptance marker is separate from raw
retention. An interrupted journal is never repaired by resending an unknown call (H1).
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from .config import StageModelConfig
from .durable import ServedModelChanged, prior_sends, stored_records, write_new
from .ledger import CallRecord
from .openai_compatible import OpenAICompatibleCompletion, request_sha256
from .run_files import IntegrityError, check_directory, read_regular

_NUMBER = re.compile(r"[0-9]+")


def request_settings(config: StageModelConfig) -> dict[str, Any]:
    """Semantic identity; transport timeout, retry bound and credential location are operational."""
    return {
        k: v
        for k, v in config.model_dump(mode="json").items()
        if k not in {"timeout_s", "max_attempts", "api_key_env"}
    }


def fingerprint(config: StageModelConfig, digest: str) -> str:
    return hashlib.sha256(
        json.dumps(
            [request_settings(config), digest],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def request_fingerprint(config: StageModelConfig, *, system: str, user: str) -> str:
    return fingerprint(config, request_sha256(config, system=system, user=user))


def answer_model(
    records: list[CallRecord],
    config: StageModelConfig,
    digest: str,
    content: bytes,
) -> str:
    """An answer must be one this exact HTTP request successfully returned, under its stage."""
    response = hashlib.sha256(content).hexdigest()
    matches = {
        r.served_model or r.model
        for r in records
        if (r.stage, r.model, r.policy_version, r.request_sha256, r.response_sha256, r.outcome)
        == (config.stage, config.model, config.policy_version, digest, response, "ok")
    }
    if len(matches) != 1:
        raise IntegrityError()
    return next(iter(matches))


class _Kept(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    config: StageModelConfig | None
    request: str
    response: str
    model: str
    record: int | None
    outcome: str
    fingerprint: str


def _kept(path: Path) -> _Kept:
    raw = read_regular(path.with_suffix(".record.json"))
    if raw is None:
        raise IntegrityError()
    try:
        return _Kept.model_validate_json(raw)
    except ValueError:
        raise IntegrityError() from None


def verify_answer(path: Path, records: list[CallRecord], *, offline: bool = False) -> _Kept:
    meta, content = _kept(path), read_regular(path)
    if content is None or hashlib.sha256(content).hexdigest() != meta.response:
        raise IntegrityError()
    if meta.config is None:
        if (
            not offline
            or records
            or meta.record is not None
            or not meta.model.startswith("offline/")
        ):
            raise IntegrityError()
        if meta.fingerprint != meta.request or meta.outcome != "ok":
            raise IntegrityError()
    else:
        if meta.record is None or not 0 <= meta.record < len(records):
            raise IntegrityError()
        record = records[meta.record]
        if (
            (record.stage, record.model, record.policy_version)
            != (meta.config.stage, meta.config.model, meta.config.policy_version)
            or record.request_sha256 != meta.request
            or record.outcome != meta.outcome
            or (record.served_model or record.model) != meta.model
            or fingerprint(meta.config, meta.request) != meta.fingerprint
        ):
            raise IntegrityError()
        if record.outcome == "ok":
            if answer_model([record], meta.config, meta.request, content) != meta.model:
                raise IntegrityError()
        elif record.outcome != "truncated":
            raise IntegrityError()
    marker = read_regular(path.with_suffix(".request.sha256"))
    if marker is not None and (
        meta.outcome != "ok" or marker != (meta.fingerprint + "\n").encode()
    ):
        raise IntegrityError()
    return meta


def check_answers(root: Path, *, offline: bool = False) -> None:
    """Read-only global preflight before any send: files, accepted answers, orphaned receipts.

    Existing ledgers with no answers may supply a budget baseline; they do not authenticate
    legacy answers. The first-record boundary excludes that historical baseline only.
    """
    check_directory(root)
    records = stored_records(root)
    if len({r.served_model for r in records if r.served_model}) > 1:
        raise ServedModelChanged("served model changed within the run")
    if prior_sends(root) != sum(
        r.outcome not in {"input_too_large", "budget_exceeded"} for r in records
    ):
        raise IntegrityError("OUTCOME_UNKNOWN")
    covered: set[int] = set()
    for path in root.rglob("*.record.json"):
        meta = verify_answer(
            path.with_name(path.name.removesuffix(".record.json") + ".txt"),
            records,
            offline=offline,
        )
        if meta.record is not None:
            if meta.record in covered:
                raise IntegrityError()
            covered.add(meta.record)
    for path in root.rglob("*.request.sha256"):
        verify_answer(
            path.with_name(path.name.removesuffix(".request.sha256") + ".txt"),
            records,
            offline=offline,
        )
    for header_path in root.rglob("recording.json"):
        header = read_regular(header_path)
        if header is None:
            raise IntegrityError()
        try:
            data = json.loads(header)
            start = data["first_record"]
            if (set(data) != {"first_record"} or type(start) is not int
                    or not 0 <= start <= len(records)):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise IntegrityError() from None
        if any(i not in covered for i, r in enumerate(records) if i >= start and r.outcome == "ok"):
            raise IntegrityError("OUTCOME_UNKNOWN")


def accepted_answers(root: Path, directory: Path) -> dict[str, str]:
    """Accepted answers after global preflight; still use safe reads and ledger binding here."""
    records, accepted = stored_records(root), {}
    for marker in sorted(directory.glob("*.request.sha256")):
        stem = marker.name.removesuffix(".request.sha256")
        if not _NUMBER.fullmatch(stem):
            raise IntegrityError()
        path = directory / f"{stem}.txt"
        meta = verify_answer(path, records)
        if meta.fingerprint in accepted:
            raise IntegrityError()
        content = read_regular(path)
        assert content is not None
        accepted[meta.fingerprint] = content.decode("utf-8")
    return accepted


class AnswerJournal:
    """One run owner's current answer directory; keep before return, accept only after parsing."""

    def __init__(self, root: Path, directory: Path, client: OpenAICompatibleCompletion) -> None:
        self.root, self.directory, self.client = root, directory, client
        self.config = client.config
        self.pending: list[tuple[Path, str]] = []
        self._current: tuple[str, str, int] | None = None
        directory.mkdir(parents=True, exist_ok=True)
        if not (directory / "recording.json").exists():
            write_new(directory / "recording.json",
                      json.dumps({"first_record": len(stored_records(root))}))
        client.retain(self.keep)

    @property
    def model(self) -> str:
        served = {r.served_model for r in stored_records(self.root) if r.served_model}
        return next(iter(served), self.config.model)

    def complete(self, *, system: str, user: str) -> str:
        self._current = (
            request_sha256(self.config, system=system, user=user),
            request_fingerprint(self.config, system=system, user=user),
            len(stored_records(self.root)),
        )
        try:
            return self.client.complete(system=system, user=user)
        finally:
            self._current = None

    def keep(self, raw: str) -> None:
        if self._current is None:
            raise IntegrityError()
        records = stored_records(self.root)
        served = {r.served_model for r in records if r.served_model}
        if len(served) > 1:
            raise ServedModelChanged("served model changed within the run")
        digest, identity, before = self._current
        if len(records) <= before:
            raise IntegrityError()  # a factory must use this run's durable ledger
        record = records[-1]
        content = raw.encode("utf-8")
        if record.outcome == "ok":
            answer_model([record], self.config, digest, content)
        elif record.outcome != "truncated" or record.request_sha256 != digest:
            raise IntegrityError()
        check_directory(self.root)
        self.directory.mkdir(parents=True, exist_ok=True)
        heads = [p.name.lstrip(".").split(".", 1)[0] for p in self.directory.iterdir()]
        number = max((int(h) for h in heads if _NUMBER.fullmatch(h)), default=0) + 1
        path = self.directory / f"{number:03d}.txt"
        meta = _Kept(
            config=self.config,
            request=digest,
            response=hashlib.sha256(content).hexdigest(),
            model=record.served_model or record.model,
            record=len(records) - 1,
            outcome=record.outcome,
            fingerprint=identity,
        )
        write_new(path, raw)
        write_new(path.with_suffix(".record.json"), meta.model_dump_json())
        if record.outcome == "ok":
            self.pending.append((path, identity))

    def accept(self) -> None:
        for path, identity in self.pending:
            write_new(path.with_suffix(".request.sha256"), identity + "\n")
        self.pending.clear()

    def reject(self) -> None:
        self.pending.clear()


def offline_answer(
    directory: Path, number: int, *, system: str, user: str, raw: str, model: str
) -> None:
    """Explicit synthetic CompletionPort output; never a successful HTTP-call record."""
    digest = message_digest(system, user)
    path = directory / f"{number:03d}.txt"
    meta = _Kept(
        config=None,
        request=digest,
        response=hashlib.sha256(raw.encode()).hexdigest(),
        model="offline/" + model,
        record=None,
        outcome="ok",
        fingerprint=digest,
    )
    write_new(path, raw)
    write_new(path.with_suffix(".record.json"), meta.model_dump_json())
    write_new(path.with_suffix(".request.sha256"), digest + "\n")


def message_digest(system: str, user: str) -> str:
    """Only for the explicitly offline evaluation port, never for HTTP provenance."""
    return hashlib.sha256(
        json.dumps([system, user], ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
