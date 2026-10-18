"""Write concept summaries for a Space's active release, and publish them (S3e-3 Spec §4.1).

usage: python -m insurance_harness.compilers.concepts.run --space S --stage concepts
       --stage-config F --run-root D [--max-sent N] [--per-call K] [--publish --reason TEXT]

Reads the active release with the platform API key and asks the model about its concepts
(synthesis.concept_inputs), --per-call at a time. Each draft is checked (checks.check_concept).
A concept whose batch answer was refused, or whose draft failed, is asked once more on its own and
told its problem codes; the retry is sent only while budget remains. A concept that still fails is
left out and listed in the report: its page keeps the definition and the comparison table.

Run-root files: budget.jsonl, ledger.jsonl and .lock as in models.durable, so --max-sent counts
every send made in the root and runs on it never overlap. responses/NNN.txt keeps every raw answer
as it arrives; NNN.request.sha256 marks one the parser accepted, and a rerun answers the same
request from it without sending. The fingerprint covers the configured model, the policy version
and the whole request, so a changed value, prompt or policy is asked again. An earlier
concepts.json is withdrawn when a run starts; concepts.json ({"concepts": [ConceptSummary...]},
based_on holding the member digests read) and report.json (per concept: the problem codes of each
attempt and the sends it took) are written once every concept has its answer.

--publish then submits one candidate based on the release read, holding only concept members and
no removals, records the person's approval with --reason and activates it.

Exit 0 with one summary line; exit 2 with one line {"stopped": <code>} (and at most an exception
type name), never a path, key or material.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

from pydantic import ValidationError

from insurance_harness.bundle.assemble import BundleError, assemble
from insurance_harness.bundle.client import (
    DecisionInput,
    PlatformClient,
    PlatformError,
    Release,
    publish,
)
from insurance_harness.compilers.concepts.checks import check_concept
from insurance_harness.compilers.concepts.synthesis import (
    ConceptDraft,
    ConceptInput,
    ConceptOutputError,
    build_request,
    concept_inputs,
    parse_concepts,
)
from insurance_harness.contracts.bundle import ReviewPlan
from insurance_harness.contracts.enums import ReviewMode
from insurance_harness.contracts.knowledge import ConceptStatement, ConceptSummary
from insurance_harness.ingest.source_map import API_KEY_ENV, BASE_URL_ENV
from insurance_harness.models import (
    ModelBudgetExceeded,
    ModelCallError,
    OpenAICompatibleCompletion,
    StageModelConfig,
    load_stage_config,
)
from insurance_harness.models.durable import (
    DurableLedger,
    RunRootBusy,
    ServedModelChanged,
    prior_sends,
    run_lock,
    write_new,
)

_DIGEST = re.compile(r"[0-9a-f]{64}")
_NUMBER = re.compile(r"[0-9]+")
_SPACE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


class _Stop(Exception):
    """A fixed, caller-safe reason code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Parser(argparse.ArgumentParser):
    """Malformed arguments become the stable INVALID_ARGUMENTS code, not usage text."""

    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


def _fingerprint(identity: str, system: str, user: str) -> str:
    encoded = json.dumps([identity, system, user], ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _accepted_answers(directory: Path) -> dict[str, str]:
    """Fingerprint -> accepted answer text; a corrupt marker is corrupt run-root state."""
    accepted: dict[str, str] = {}
    if not directory.exists():
        return accepted
    for marker in sorted(directory.glob("*.request.sha256")):
        stem = marker.name.removesuffix(".request.sha256")
        digest = marker.read_text(encoding="utf-8").removesuffix("\n")
        answer = directory / f"{stem}.txt"
        if (
            not _NUMBER.fullmatch(stem)
            or not _DIGEST.fullmatch(digest)
            or digest in accepted
            or not answer.is_file()
        ):
            raise _Stop("RUN_ROOT_INVALID")
        accepted[digest] = answer.read_text(encoding="utf-8")
    return accepted


class _Model:
    """Answers each request from an accepted answer, else sends it and keeps the raw answer."""

    def __init__(
        self,
        completion: OpenAICompatibleCompletion,
        ledger: DurableLedger,
        directory: Path,
        identity: str,
    ) -> None:
        self._completion, self._ledger, self._directory = completion, ledger, directory
        self._identity = identity
        self._accepted = _accepted_answers(directory)

    def ask(
        self, batch: Sequence[ConceptInput], problems: dict[str, list[str]] | None = None
    ) -> tuple[dict[str, ConceptDraft] | None, bool]:
        """The batch's drafts (None when the answer was refused) and whether it was sent."""
        system, user = build_request(batch, problems)
        digest = _fingerprint(self._identity, system, user)
        cached = self._accepted.get(digest)
        if cached is not None:
            try:
                return parse_concepts(cached, batch), False
            except ConceptOutputError:
                raise _Stop("RUN_ROOT_INVALID") from None  # accepted once, altered since
        raw = self._completion.complete(system=system, user=user)
        if len(self._ledger.served) > 1:
            raise ServedModelChanged("served model changed within the run")
        self._directory.mkdir(parents=True, exist_ok=True)
        stem = f"{self._next_number():03d}"
        write_new(self._directory / f"{stem}.txt", raw)
        try:
            drafts = parse_concepts(raw, batch)
        except ConceptOutputError:
            return None, True
        write_new(self._directory / f"{stem}.request.sha256", digest + "\n")
        self._accepted[digest] = raw
        return drafts, True

    def _next_number(self) -> int:
        # Every name counts, leftover temporary files included, so a new answer never collides.
        heads = (path.name.lstrip(".").split(".", 1)[0] for path in self._directory.iterdir())
        return max((int(head) for head in heads if _NUMBER.fullmatch(head)), default=0) + 1


@dataclass
class _Outcome:
    attempts: list[list[str]] = field(default_factory=list)
    sent: int = 0
    summary: ConceptSummary | None = None


def _names(release: Release) -> set[str]:
    """Every name, alias, identifier and id of the release's entries."""
    names: set[str] = set()
    for member in release.members:
        payload = member.payload if isinstance(member.payload, dict) else {}
        if member.kind != "entity":
            continue
        identifiers = payload.get("identifiers")
        values = [
            payload.get("entity_id"),
            *_items(payload.get("names")),
            *_items(payload.get("aliases")),
            *(identifiers.values() if isinstance(identifiers, dict) else []),
        ]
        names.update(value for value in values if isinstance(value, str) and value.strip())
    return names


def _items(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _judge(
    drafts: dict[str, ConceptDraft] | None,
    concept: ConceptInput,
    names: set[str],
    config: StageModelConfig,
) -> tuple[list[str], ConceptSummary | None]:
    if drafts is None:
        return [ConceptOutputError.code], None
    draft = drafts[concept.key]
    problems = check_concept(draft, concept, names)
    if problems:
        return problems, None
    try:
        summary = ConceptSummary(
            concept_key=concept.key,
            title=concept.title,
            definition=draft.definition,
            explanation=draft.explanation,
            statements=[ConceptStatement(text=s.text, refs=list(s.refs)) for s in draft.statements],
            based_on={fact.slug: fact.digest for fact in concept.facts},
            origin="MODEL_GENERATED",
            model=config.model,
            prompt_version=config.policy_version,
        )
    except ValidationError:
        return ["SUMMARY_INVALID"], None
    return [], summary


def _write(
    concepts: list[ConceptInput],
    model: _Model,
    names: set[str],
    config: StageModelConfig,
    per_call: int,
) -> dict[str, _Outcome]:
    outcomes = {concept.key: _Outcome() for concept in concepts}

    def record(concept: ConceptInput, drafts: dict[str, ConceptDraft] | None, sent: bool) -> None:
        outcome = outcomes[concept.key]
        problems, outcome.summary = _judge(drafts, concept, names, config)
        outcome.attempts.append(problems)
        outcome.sent += sent

    # Every first answer is needed: running out of budget here stops the run.
    for start in range(0, len(concepts), per_call):
        batch = concepts[start : start + per_call]
        drafts, sent = model.ask(batch)
        for concept in batch:
            record(concept, drafts, sent)
    # A retry is sent only while budget remains; without one the concept is left out.
    for concept in concepts:
        outcome = outcomes[concept.key]
        if outcome.summary is not None:
            continue
        try:
            drafts, sent = model.ask([concept], {concept.key: outcome.attempts[-1]})
        except ModelBudgetExceeded:
            outcome.attempts.append(["RETRY_BUDGET_EXCEEDED"])
            continue
        record(concept, drafts, sent)
    return outcomes


def _replace(path: Path, text: str) -> None:
    """Atomically and durably replace path; under the run lock a leftover temp is ours."""
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.unlink(missing_ok=True)
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _dump(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = _Parser(description=__doc__)
    parser.add_argument("--space", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--stage-config", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--max-sent", type=int, default=10)
    parser.add_argument("--per-call", type=int, default=2)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--reason")
    args = parser.parse_args(argv)
    if not _SPACE.fullmatch(args.space) or args.max_sent < 0 or args.per_call < 1:
        raise ValueError("invalid space, budget or batch size")
    if args.publish != bool(args.reason and args.reason.strip()):
        raise ValueError("--publish needs a --reason, and --reason needs --publish")
    return args


def _publish(
    client: PlatformClient,
    space: str,
    release: Release,
    summaries: list[ConceptSummary],
    config: StageModelConfig,
    reason: str,
) -> Release:
    if not summaries:
        raise _Stop("NOTHING_TO_PUBLISH")
    bundle = assemble(
        [],
        compiler_identity=f"harness/concepts@{config.policy_version}",
        base=release.head,
        concepts=summaries,
        review_plan=[ReviewPlan(mode=ReviewMode.HUMAN)],
    )
    decision = DecisionInput(outcome="approve", mode="human", reason=reason)
    result = publish(client, space, bundle, decision=decision, activate=True)
    if result.release is None:
        raise _Stop("RELEASE_MISMATCH")
    return result.release


def _stop_detail(exc: BaseException) -> dict[str, str]:
    """Fixed codes; an exception type name at most, never its text (it may hold a path)."""
    if isinstance(exc, _Stop):
        return {"stopped": exc.code}
    if isinstance(exc, PlatformError):
        return {"stopped": exc.code}
    if isinstance(exc, BundleError):
        return {"stopped": "BUNDLE_INVALID", "reason": exc.reason}
    if isinstance(exc, RunRootBusy):
        return {"stopped": "RUN_ROOT_BUSY"}
    if isinstance(exc, ServedModelChanged):
        return {"stopped": "SERVED_MODEL_CHANGED"}
    if isinstance(exc, ModelBudgetExceeded):
        return {"stopped": "BUDGET_EXCEEDED"}
    if isinstance(exc, ModelCallError):
        return {"stopped": "MODEL_ERROR", "error": type(exc).__name__}
    # Inside a git repository, unreadable or corrupt run-root files, or a failed write.
    return {"stopped": "RUN_ROOT_INVALID", "error": type(exc).__name__}


def main(argv: list[str] | None = None) -> int:
    try:
        args = _arguments(argv)
    except ValueError:
        print(json.dumps({"stopped": "INVALID_ARGUMENTS"}))
        return 2
    try:
        config = load_stage_config(args.stage_config, args.stage)
        base_url, api_key = os.environ.get(BASE_URL_ENV), os.environ.get(API_KEY_ENV)
        if not base_url or not api_key:
            raise _Stop("PLATFORM_UNCONFIGURED")
        client = PlatformClient(base_url, api_key)
        release = client.active(args.space)
        if release is None:
            raise _Stop("RELEASE_NOT_FOUND")
        concepts, names = concept_inputs(release), _names(release)
        # One lock spans the budget read, every send, both files and the publication.
        with run_lock(args.run_root):
            target = args.run_root / "concepts.json"
            if target.exists():
                os.replace(target, args.run_root / "concepts.json.previous")
            ledger = DurableLedger.open(args.run_root, max_sent=args.max_sent)
            before = prior_sends(args.run_root)
            completion = OpenAICompatibleCompletion(config, ledger=ledger)
            try:
                identity = f"{config.model}@{config.policy_version}"
                model = _Model(completion, ledger, args.run_root / "responses", identity)
                outcomes = _write(concepts, model, names, config, args.per_call)
            finally:
                completion.close()
            # One served model per root (DurableLedger); a provider naming none leaves the alias.
            served = (sorted(ledger.served) or [config.model])[0]
            summaries = [
                outcome.summary.model_copy(update={"model": served})
                for outcome in outcomes.values()
                if outcome.summary is not None
            ]
            failed = {
                key: outcome.attempts[-1]
                for key, outcome in outcomes.items()
                if outcome.summary is None
            }
            report = {
                "served_model": served,
                "prompt_version": config.policy_version,
                "failed": failed,
                "concepts": {
                    key: {"attempts": outcome.attempts, "sent": outcome.sent}
                    for key, outcome in outcomes.items()
                },
            }
            _replace(args.run_root / "report.json", _dump(report))
            _replace(target, _dump({"concepts": [s.model_dump(mode="json") for s in summaries]}))
            summary: dict[str, Any] = {
                "concepts": len(concepts),
                "written": len(summaries),
                "failed": sorted(failed),
                "sent": prior_sends(args.run_root) - before,
                "sent_total": prior_sends(args.run_root),
                "served_model": served,
            }
            if args.publish:
                published = _publish(client, args.space, release, summaries, config, args.reason)
                summary.update(release_id=published.id, epoch=published.epoch)
    except (
        _Stop, PlatformError, BundleError, RunRootBusy, ServedModelChanged, ModelCallError,
        ValueError, OSError,
    ) as exc:  # fmt: skip
        print(json.dumps(_stop_detail(exc), ensure_ascii=False))
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
