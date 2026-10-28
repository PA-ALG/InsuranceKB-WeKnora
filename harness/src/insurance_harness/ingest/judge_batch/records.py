"""Per-product publish attempts that survive any interruption (RV7 Spec §2.3, review R1).

An attempt freezes the candidate it submits (its bytes and sha256) and the machine decision it
makes, and records each stage before and after the step that reaches it. A rerun never rebuilds
the candidate: it settles a step whose outcome is unknown by reading Active first, then replays
the remaining steps with the same inputs, which the platform answers idempotently (the same
bundle digest is the same candidate, the same decision input the same decision, a repeated
activation the release it made, a repeated sample the one it kept). Activation refused with
NEEDS_REBASE proves the attempt never went live; the next run starts a new one. A completed
attempt is never written again.

The frozen file is written before its record, and the record before anything is sent, so a frozen
file without a record (an interruption between the two) was never sent. A rerun freezes its own
candidate under the next free number and leaves that file untouched: a frozen identity is never
overwritten or reused (review round 2, R1). A rebuilt candidate is not byte-identical anyway: its
maintenance time is when it was built.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from insurance_harness.bundle.client import (
    DecisionInput,
    PlatformClient,
    PlatformError,
    Release,
)
from insurance_harness.catalog.spot_check import SpotCheckPolicy
from insurance_harness.contracts.bundle import CandidateBundle
from insurance_harness.ingest.judge_batch.manifest import write_json
from insurance_harness.ingest.judge_batch.points import JudgeBatchError
from insurance_harness.review.spot_check import sample

Stage = Literal["built", "submitted", "decided", "activated", "verified", "sampled"]
_ATTEMPT = re.compile(r"attempt-(\d+)\.json")
_FROZEN = re.compile(r"attempt-(\d+)\.bundle\.json")
_SAMPLE_BATCH = 500


class Attempt(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    product: str
    attempt: int
    bundle_sha256: str
    base_release: str | None
    slugs: list[str]
    contents: dict[str, str]  # slug -> the content the judge approved
    decision: dict[str, str]
    stage: Stage = "built"
    pending: str | None = None  # the step started but not known to have finished
    status: Literal["in_progress", "published", "needs_rebase"] = "in_progress"
    candidate: str | None = None
    bundle_digest: str | None = None
    decision_id: str | None = None
    release: str | None = None
    epoch: int | None = None
    samples: int | None = None
    reconciled: list[str] = []

    def summary(self) -> dict[str, Any]:
        keys = ("attempt", "stage", "candidate", "release", "epoch", "samples", "slugs")
        return {key: getattr(self, key) for key in keys} | {"reconciled": list(self.reconciled)}


def _folder(run_root: Path, product: str) -> Path:
    return run_root / "publish" / product


def _path(run_root: Path, record: Attempt) -> Path:
    return _folder(run_root, record.product) / f"attempt-{record.attempt}.json"


def _bundle_path(run_root: Path, product: str, attempt: int) -> Path:
    return _folder(run_root, product) / f"attempt-{attempt}.bundle.json"


def _numbers(folder: Path, pattern: re.Pattern[str]) -> list[int]:
    return sorted(
        int(found.group(1))
        for path in (folder.iterdir() if folder.is_dir() else [])
        if (found := pattern.fullmatch(path.name))
    )


def current(run_root: Path, product: str) -> Attempt | None:
    """The product's latest attempt, if any."""
    folder = _folder(run_root, product)
    numbers = _numbers(folder, _ATTEMPT)
    if not numbers:
        return None
    try:
        return Attempt.model_validate_json(
            (folder / f"attempt-{numbers[-1]}.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, ValidationError):
        raise JudgeBatchError("RECORD_INVALID") from None


def _save(run_root: Path, record: Attempt) -> None:
    path = _path(run_root, record)
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise JudgeBatchError("RECORD_INVALID") from None
        if stored.get("status") == "published":
            raise JudgeBatchError("RECORD_INVALID")  # a completed attempt is final
    write_json(path, record.model_dump(mode="json"))


def _freeze(run_root: Path, product: str, after: int, raw: bytes) -> int:
    """Freeze `raw` under a number above every recorded attempt and every frozen file."""
    folder = _folder(run_root, product)
    try:
        number = max([after, *_numbers(folder, _FROZEN)]) + 1
        folder.mkdir(parents=True, exist_ok=True)
        with _bundle_path(run_root, product, number).open("xb") as stream:
            stream.write(raw)
    except OSError:
        raise JudgeBatchError("RECORD_INVALID") from None
    return number


def start(
    run_root: Path,
    product: str,
    bundle: CandidateBundle,
    contents: dict[str, str],
    decision: DecisionInput,
) -> Attempt:
    """Freeze the candidate and the decision before anything is sent."""
    latest = current(run_root, product)
    raw = json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
    number = _freeze(run_root, product, 0 if latest is None else latest.attempt, raw)
    record = Attempt(
        product=product,
        attempt=number,
        bundle_sha256=hashlib.sha256(raw).hexdigest(),
        base_release=bundle.base_release_id,
        slugs=sorted(contents),
        contents=dict(sorted(contents.items())),
        decision=decision.model_dump(exclude_none=True),
    )
    _save(run_root, record)
    return record


def _frozen(run_root: Path, record: Attempt) -> CandidateBundle:
    try:
        raw = _bundle_path(run_root, record.product, record.attempt).read_bytes()
        if hashlib.sha256(raw).hexdigest() != record.bundle_sha256:
            raise ValueError("changed")
        return CandidateBundle.model_validate_json(raw)
    except (OSError, ValueError, ValidationError):
        raise JudgeBatchError("RECORD_INVALID") from None


def _begin(run_root: Path, record: Attempt, step: str) -> None:
    record.pending = step
    _save(run_root, record)


def _reach(run_root: Path, record: Attempt, stage: Stage, **values: Any) -> None:
    for key, value in values.items():
        setattr(record, key, value)
    record.stage, record.pending = stage, None
    _save(run_root, record)


def _verify(release: Release, record: Attempt, bundle: CandidateBundle) -> None:
    digests = {member.logical_slug: member.member_digest for member in release.members}
    if (
        release.id != record.release
        or (release.candidate_id and release.candidate_id != record.candidate)
        or any(digests.get(m.logical_slug) != m.member_digest for m in bundle.members)
    ):
        raise PlatformError("RELEASE_MISMATCH")


def advance(
    run_root: Path,
    record: Attempt,
    *,
    client: PlatformClient,
    space_id: str,
    policy: SpotCheckPolicy,
    base: Release | None = None,
) -> Attempt:
    """Take the attempt to its last stage; `base` is the Active it was built on, when known."""
    bundle = _frozen(run_root, record)
    if record.pending is not None:
        record.reconciled = [*record.reconciled, record.pending]
    if record.stage in {"submitted", "decided"} and record.candidate:
        active = client.active(space_id)
        if active is not None and active.candidate_id == record.candidate:
            _reach(run_root, record, "activated", release=active.id, epoch=active.epoch)
    if record.stage == "built":
        _begin(run_root, record, "submit")
        candidate = client.submit(space_id, bundle)
        _reach(
            run_root,
            record,
            "submitted",
            candidate=candidate.id,
            bundle_digest=candidate.bundle_digest or None,
        )
    if record.stage == "submitted":
        _begin(run_root, record, "decide")
        decision = DecisionInput.model_validate(record.decision)
        made = client.decide(space_id, str(record.candidate), decision)
        _reach(run_root, record, "decided", decision_id=made.id)
    if record.stage == "decided":
        _begin(run_root, record, "activate")
        try:
            activated = client.activate(space_id, str(record.candidate), str(record.decision_id))
        except PlatformError as error:
            if error.code == "NEEDS_REBASE":  # never went live: the next run starts anew
                record.status, record.pending = "needs_rebase", None
                _save(run_root, record)
            raise
        _reach(run_root, record, "activated", release=activated.id, epoch=activated.epoch)
    published: Release | None = None
    if record.stage == "activated":
        _begin(run_root, record, "read_back")
        published = client.release(space_id, str(record.release))
        _verify(published, record, bundle)
        _reach(run_root, record, "verified")
    if record.stage == "verified":
        _begin(run_root, record, "samples")
        if published is None:
            published = client.release(space_id, str(record.release))
            _verify(published, record, bundle)
        if base is None and record.base_release:
            base = client.release(space_id, record.base_release)
            if base.id != record.base_release:
                raise PlatformError("RELEASE_MISMATCH")
        picks = [(pick.slug, pick.stratum) for pick in sample(published, base, policy)]
        count = 0
        for at in range(0, len(picks), _SAMPLE_BATCH):
            chunk = picks[at : at + _SAMPLE_BATCH]
            count += len(client.submit_samples(space_id, published.id, chunk))
        record.status = "published"
        _reach(run_root, record, "sampled", samples=count)
    return record
