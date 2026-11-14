"""Per-product publish attempts that survive any interruption (RV7 Spec §2.3, review R1).

An attempt freezes the candidate it submits (its bytes and sha256) and the machine decision it
makes, and records each stage before and after the step that reaches it. A rerun starts from the
frozen candidate and decision. Legacy activation settles an interruption by checking Active,
then replaying with the same inputs. In receipt mode an interrupted activation is resolved only
by looking up its exact receipt and verifying the fixed Release. A NEEDS_REBASE refusal from the
activation request permits a new attempt. A completed attempt is never written again.

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

from insurance_harness.bundle.assemble import BundleError
from insurance_harness.bundle.client import (
    ActivationReceipt,
    DecisionInput,
    PlatformClient,
    PlatformError,
    Release,
)
from insurance_harness.bundle.fixed_release import FixedRelease
from insurance_harness.bundle.request_budget import ReleaseReadBudget
from insurance_harness.catalog.spot_check import SpotCheckPolicy
from insurance_harness.compilers.schema_fields.claims import require_publishable_bundle
from insurance_harness.contracts.bundle import CandidateBundle
from insurance_harness.ingest.judge_batch.manifest import write_json
from insurance_harness.ingest.judge_batch.points import JudgeBatchError
from insurance_harness.ingest.judge_batch.targeted_release import sample_inputs, verified_release
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
    activation_receipt: bool = False
    approval_digest: str | None = None
    receipt_base: str | None = None
    targeted_release_reads: bool = False

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
    payload = record.model_dump(mode="json")
    if not record.activation_receipt:
        for key in ("activation_receipt", "approval_digest", "receipt_base"):
            del payload[key]
    if not record.targeted_release_reads:
        del payload["targeted_release_reads"]
    write_json(path, payload)


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
    *,
    activation_receipt: bool = False,
    targeted_release_reads: bool = False,
) -> Attempt:
    """Freeze the candidate and the decision before anything is sent."""
    try:
        require_publishable_bundle(bundle)
    except BundleError as error:
        raise JudgeBatchError(error.reason) from None
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
        activation_receipt=activation_receipt or targeted_release_reads,
        targeted_release_reads=targeted_release_reads,
    )
    _save(run_root, record)
    return record


def _frozen(run_root: Path, record: Attempt) -> CandidateBundle:
    try:
        raw = _bundle_path(run_root, record.product, record.attempt).read_bytes()
        if hashlib.sha256(raw).hexdigest() != record.bundle_sha256:
            raise ValueError("changed")
        bundle = CandidateBundle.model_validate_json(raw)
        require_publishable_bundle(bundle)
        return bundle
    except BundleError as error:
        raise JudgeBatchError(error.reason) from None
    except (OSError, ValueError, ValidationError):
        raise JudgeBatchError("RECORD_INVALID") from None


def published_members(run_root: Path, record: Attempt) -> dict[str, str]:
    """Slug -> member digest of the candidate this attempt froze, read from its checked file."""
    return {m.logical_slug: m.member_digest for m in _frozen(run_root, record).members}


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
    if record.activation_receipt and (
        release.candidate_id != record.candidate
        or release.decision_digest != record.approval_digest
        or release.epoch != record.epoch
        or release.base_release_id != record.receipt_base
        or len(digests) != len(release.members)
        or any(slug in digests for slug in bundle.removals)
    ):
        raise PlatformError("RELEASE_MISMATCH")
    if (
        release.id != record.release
        or (release.candidate_id and release.candidate_id != record.candidate)
        or any(digests.get(m.logical_slug) != m.member_digest for m in bundle.members)
    ):
        raise PlatformError("RELEASE_MISMATCH")


def _reach_receipt(run_root: Path, record: Attempt, receipt: ActivationReceipt) -> None:
    _reach(
        run_root,
        record,
        "activated",
        release=receipt.id,
        epoch=receipt.epoch,
        receipt_base=receipt.base_release_id,
    )


def _advance_activation(
    run_root: Path,
    record: Attempt,
    client: PlatformClient,
    space_id: str,
    budget: ReleaseReadBudget | None,
) -> None:
    if not record.candidate or not record.decision_id:
        raise JudgeBatchError("RECORD_INVALID")
    if record.activation_receipt:
        if not record.approval_digest:
            raise JudgeBatchError("RECORD_INVALID")
        if record.pending == "activate":
            receipt = client.activation_receipt(
                space_id,
                record.candidate,
                record.decision_id,
                record.approval_digest,
                budget=budget,
            )
        else:
            _begin(run_root, record, "activate")
            receipt = client.activate_receipt(
                space_id,
                record.candidate,
                record.decision_id,
                record.approval_digest,
                budget=budget,
            )
        _reach_receipt(run_root, record, receipt)
        return
    _begin(run_root, record, "activate")
    activated = client.activate(space_id, record.candidate, record.decision_id)
    _reach(run_root, record, "activated", release=activated.id, epoch=activated.epoch)


def advance(
    run_root: Path,
    record: Attempt,
    *,
    client: PlatformClient,
    space_id: str,
    policy: SpotCheckPolicy,
    base: Release | None = None,
    fixed_base: FixedRelease | None = None,
    budget: ReleaseReadBudget | None = None,
) -> Attempt:
    """Take the attempt to its last stage; `base` is the Active it was built on, when known."""
    bundle = _frozen(run_root, record)
    if record.targeted_release_reads:
        if not record.activation_receipt:
            raise JudgeBatchError("RECORD_INVALID")
        budget = budget or ReleaseReadBudget()
    if record.pending is not None:
        record.reconciled = [*record.reconciled, record.pending]
    if (
        not record.activation_receipt
        and record.stage in {"submitted", "decided"}
        and record.candidate
    ):
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
        if record.activation_receipt:
            if (
                made.candidate_id != record.candidate
                or made.outcome != "approve"
                or not re.fullmatch(r"[0-9a-f]{64}", made.digest)
            ):
                raise PlatformError("INVALID_RESPONSE")
            record.approval_digest = made.digest
        _reach(run_root, record, "decided", decision_id=made.id)
    if record.stage == "decided":
        lookup_only = record.activation_receipt and record.pending == "activate"
        try:
            _advance_activation(run_root, record, client, space_id, budget)
        except PlatformError as error:
            # Only an activation refusal settles the attempt; a read error cannot.
            if not lookup_only and error.code == "NEEDS_REBASE":
                record.status, record.pending = "needs_rebase", None
                _save(run_root, record)
            raise
    published: Release | None = None
    if record.targeted_release_reads:
        assert budget is not None
        return _finish_targeted(
            run_root, record, client, space_id, bundle, policy, budget, fixed_base
        )
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
        _save_samples(run_root, record, client, space_id, policy, published, base)
    return record


def _finish_targeted(
    run_root: Path,
    record: Attempt,
    client: PlatformClient,
    space: str,
    bundle: CandidateBundle,
    policy: SpotCheckPolicy,
    budget: ReleaseReadBudget,
    prior: FixedRelease | None,
) -> Attempt:
    if record.stage == "sampled":
        return record
    if (
        record.stage not in {"activated", "verified"}
        or not record.release
        or not record.epoch
        or record.receipt_base is None
        or not record.candidate
        or not record.approval_digest
    ):
        raise JudgeBatchError("RECORD_INVALID")
    if record.stage == "activated":
        _begin(run_root, record, "read_back")
    identity = (
        record.release,
        record.epoch,
        record.receipt_base,
        record.candidate,
        record.approval_digest,
    )
    current = verified_release(client, space, budget, identity, bundle)
    if record.stage == "activated":
        _reach(run_root, record, "verified")
    _begin(run_root, record, "samples")
    if not record.receipt_base:
        if record.epoch != 1:
            raise PlatformError("RELEASE_MISMATCH")
        prior = None
    elif prior is None or prior.header.id != record.receipt_base:
        prior = FixedRelease(client, space, budget, record.receipt_base)
    if prior is not None and prior.header.epoch + 1 != record.epoch:
        raise PlatformError("RELEASE_MISMATCH")
    published, base = sample_inputs(current, prior)
    _save_samples(run_root, record, client, space, policy, published, base)
    return record


def _save_samples(
    run_root: Path,
    record: Attempt,
    client: PlatformClient,
    space: str,
    policy: SpotCheckPolicy,
    published: Release,
    base: Release | None,
) -> None:
    picks = [(pick.slug, pick.stratum) for pick in sample(published, base, policy)]
    count = 0
    for at in range(0, len(picks), _SAMPLE_BATCH):
        count += len(client.submit_samples(space, published.id, picks[at : at + _SAMPLE_BATCH]))
    record.status = "published"
    _reach(run_root, record, "sampled", samples=count)
