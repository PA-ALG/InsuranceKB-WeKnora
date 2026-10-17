"""Score compiled products with the independent review stage and write RV1 scores files.

usage: python -m insurance_harness.eval.review_run --products P... --compile-root DIR
       [--compile-root DIR ...] --stage review --stage-config FILE --run-root DIR
       [--max-sent N] [--max-chars N] [--repo DIR]

Products are reviewed in argument order (RV2a Spec §3.3). Each takes its output from the first
compile root holding <root>/<product>/output.json and its pack's definitions from the catalog in
--repo (every formation method: the review covers whatever the output holds). Fields with content
are scored in batches; <run-root>/<product>/scores.json then gets {"reviewer": "<served model>@
<policy version>", "reviewed_at": ..., "scores": {...}}, the file the publish command's --scores
reads.

Run-root files: budget.jsonl, ledger.jsonl and .lock as in models.durable, so --max-sent counts
every send made in the root, the root records one served model, and runs on it never overlap.
<product>/responses/NNN.txt keeps every raw answer as it arrives; NNN.request.sha256 is written
once the scorer accepted that answer, and a rerun answers the same request from it without
sending. A rejected answer stays for diagnosis only, so a rerun sends its batch again (within
the budget). The request fingerprint covers the items (keys, titles, rules, states, values,
quotes), the configured model and the policy version.

A scores file is derived from accepted answers, never trusted on its own. A rerun rebuilds every
request from the current output, rules, model and policy: when all are answered and the result
equals the scores file, the file is kept and nothing is sent; when the result differs without a
send, the file is replaced atomically; when a request must be sent (its inputs, model or policy
changed), the stale file is withdrawn before the first send, so publishing finds no scores and
queues the product for people until the new review completes. Corrupt accepted-answer markers or
a malformed scores file stop the run before any send (RUN_ROOT_INVALID).

Exit 0: every product scored; exit 2: one line {"stopped": <code>, ...} with a fixed code (and at
most the product id and an exception type name), never a path, key or material.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, NoReturn

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from insurance_harness.compilers.schema_fields.definitions import pack_definitions
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.compilers.schema_fields.review_items import review_items
from insurance_harness.eval.product_sources import check_product_id
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
from insurance_harness.review.scorer import (
    Completion,
    ReviewOutputError,
    review_batches,
    score_items,
)

_CATALOG = "internal/handler/schema_pack_catalog_830_g3.generated.json"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_NUMBER = re.compile(r"[0-9]+")


class _Stop(Exception):
    """A fixed, caller-safe reason code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Parser(argparse.ArgumentParser):
    """Malformed arguments become the stable INVALID_ARGUMENTS code, not usage text."""

    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


@dataclass(frozen=True)
class ProductReview:
    product: str
    scored: int
    reused: bool  # the scores file an earlier run wrote still holds and was kept


# The publish command's scores file (RV1 Spec §3.4), read back to bind it to the current review.
Score = Annotated[float, Field(strict=True, ge=0.0, le=1.0, allow_inf_nan=False)]
NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class _ScoresDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reviewer: NonBlank
    reviewed_at: NonBlank
    scores: dict[NonBlank, Score]

    @field_validator("reviewed_at")
    @classmethod
    def iso_8601_with_offset(cls, value: str) -> str:
        if "T" not in value or datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("reviewed_at must be an ISO 8601 date-time with an offset")
        return value


@dataclass(frozen=True)
class _Saved:
    """What earlier runs left for one product, checked before anything is sent."""

    accepted: dict[str, str]  # request fingerprint -> accepted answer text
    scores: _ScoresDocument | None


def _saved(run_root: Path, product: str) -> _Saved:
    """Accepted answers and the scores file; any corruption raises ValueError or OSError."""
    directory = run_root / product / "responses"
    accepted: dict[str, str] = {}
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
            raise ValueError("accepted answer marker is corrupt")
        accepted[digest] = answer.read_text(encoding="utf-8")
    path = run_root / product / "scores.json"
    if not path.exists():
        return _Saved(accepted, None)
    return _Saved(accepted, _ScoresDocument.model_validate_json(path.read_text(encoding="utf-8")))


class _Answers:
    """One product's answers: every raw answer is kept, accepted ones answer reruns.

    The fingerprint covers the reviewer identity (model and policy version) with the request,
    so an answer is reused only for the request and policy that produced it. before_send runs
    once, before the first request of this product that has to be sent.
    """

    def __init__(
        self,
        inner: Completion,
        directory: Path,
        ledger: DurableLedger,
        identity: str,
        accepted: dict[str, str],
        before_send: Callable[[], None],
    ) -> None:
        self._inner, self._directory, self._ledger = inner, directory, ledger
        self._identity, self._accepted = identity, dict(accepted)
        self._before_send = before_send
        self._pending: list[tuple[str, str, str]] = []
        self.fresh = False

    def complete(self, *, system: str, user: str) -> str:
        encoded = json.dumps([self._identity, system, user], ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        saved = self._accepted.get(digest)
        if saved is not None:
            return saved
        if not self.fresh:
            self._before_send()
            self.fresh = True
        raw = self._inner.complete(system=system, user=user)
        if len(self._ledger.served) > 1:
            # This answer came from another served version: it is neither scored nor kept.
            raise ServedModelChanged("served model changed within the run")
        self._directory.mkdir(parents=True, exist_ok=True)
        stem = f"{self._next_number():03d}"
        write_new(self._directory / f"{stem}.txt", raw)
        self._pending.append((stem, digest, raw))
        return raw

    def accept(self) -> None:
        """The answers since the last call were accepted: reruns may now reuse them."""
        for stem, digest, raw in self._pending:
            write_new(self._directory / f"{stem}.request.sha256", digest + "\n")
            self._accepted[digest] = raw
        self._pending.clear()

    def _next_number(self) -> int:
        # Every name counts, leftover temporary files included, so a new answer never collides.
        heads = (path.name.lstrip(".").split(".", 1)[0] for path in self._directory.iterdir())
        return max((int(head) for head in heads if _NUMBER.fullmatch(head)), default=0) + 1


def _replace(path: Path, text: str) -> None:
    """Atomically and durably replace path; under the run lock a leftover temp is ours."""
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.unlink(missing_ok=True)
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _output(compile_roots: Sequence[Path], product: str) -> CompileOutput:
    for root in compile_roots:
        path = root / product / "output.json"
        if not path.exists():
            continue
        try:
            output = CompileOutput.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise _Stop("OUTPUT_INVALID") from None
        keys = [field.field_key for field in output.fields]
        if output.entity_id != product or len(set(keys)) != len(keys):
            raise _Stop("OUTPUT_INVALID")
        return output
    raise _Stop("OUTPUT_MISSING")


def _review_product(
    product: str,
    saved: _Saved,
    *,
    repo: Path,
    compile_roots: Sequence[Path],
    run_root: Path,
    completion: Completion,
    ledger: DurableLedger,
    config: StageModelConfig,
    max_chars: int,
) -> ProductReview:
    target = run_root / product / "scores.json"
    output = _output(compile_roots, product)
    try:
        definitions = pack_definitions(
            repo / _CATALOG, output.pack_id, only_source_extractable=False
        )
        items = review_items(output, {d.field_key: d for d in definitions})
    except (OSError, ValueError):
        raise _Stop("DEFINITION_MISSING") from None
    answers = _Answers(
        completion,
        run_root / product / "responses",
        ledger,
        f"{config.model}@{config.policy_version}",
        saved.accepted,
        # A request that must be sent means the scores file no longer matches the review input.
        before_send=lambda: target.unlink(missing_ok=True),
    )
    scores: dict[str, float] = {}
    # One batch at a time (batching a batch again returns it unchanged), so an answer becomes
    # reusable only after the scorer accepted it.
    for batch in review_batches(items, max_chars=max_chars):
        scores.update(score_items(batch, answers, max_chars=max_chars))
        answers.accept()
    # One served model per root (DurableLedger); a provider that names none leaves the alias.
    served = sorted(ledger.served) or [config.model]
    reviewer = f"{served[0]}@{config.policy_version}"
    stored = saved.scores
    if (
        stored is not None
        and not answers.fresh
        and stored.scores == scores
        and stored.reviewer == reviewer
    ):
        return ProductReview(product, len(scores), True)
    document = {
        "reviewer": reviewer,
        "reviewed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "scores": scores,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    _replace(target, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return ProductReview(product, len(scores), False)


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = _Parser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--products", nargs="+", required=True)
    parser.add_argument("--compile-root", type=Path, action="append", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--stage-config", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--max-sent", type=int, default=10)
    parser.add_argument("--max-chars", type=int, default=60_000)
    args = parser.parse_args(argv)
    for product in args.products:
        check_product_id(product)
    args.products = list(dict.fromkeys(args.products))
    if args.max_sent < 0 or args.max_chars < 1:
        raise ValueError("budgets must be non-negative and the batch limit positive")
    return args


def _stop_detail(exc: BaseException) -> dict[str, str]:
    """Fixed codes; an exception type name at most, never its text (it may hold a path)."""
    if isinstance(exc, _Stop):
        return {"stopped": exc.code}
    if isinstance(exc, RunRootBusy):
        return {"stopped": "RUN_ROOT_BUSY"}
    if isinstance(exc, ServedModelChanged):
        return {"stopped": "SERVED_MODEL_CHANGED"}
    if isinstance(exc, ModelBudgetExceeded):
        return {"stopped": "BUDGET_EXCEEDED"}
    if isinstance(exc, ModelCallError):
        return {"stopped": "MODEL_ERROR", "error": type(exc).__name__}
    if isinstance(exc, ReviewOutputError):
        return {"stopped": exc.reason}
    # Inside a git repository, unreadable or corrupt run-root files, or a failed write.
    return {"stopped": "RUN_ROOT_INVALID", "error": type(exc).__name__}


def main(argv: list[str] | None = None) -> int:
    try:
        args = _arguments(argv)
    except ValueError:
        print(json.dumps({"stopped": "INVALID_ARGUMENTS"}))
        return 2
    current: str | None = None
    try:
        config = load_stage_config(args.stage_config, args.stage)
        # One lock spans the budget read, every send and every scores file.
        with run_lock(args.run_root):
            ledger = DurableLedger.open(args.run_root, max_sent=args.max_sent)
            # Everything earlier runs left is checked before the first send of this run.
            saved: dict[str, _Saved] = {}
            for current in args.products:
                saved[current] = _saved(args.run_root, current)
            current = None
            client = OpenAICompatibleCompletion(config, ledger=ledger)
            reviews: list[ProductReview] = []
            try:
                for current in args.products:
                    reviews.append(
                        _review_product(
                            current,
                            saved[current],
                            repo=args.repo,
                            compile_roots=args.compile_root,
                            run_root=args.run_root,
                            completion=client,
                            ledger=ledger,
                            config=config,
                            max_chars=args.max_chars,
                        )
                    )
            finally:
                client.close()
            summary: dict[str, Any] = {
                "products": [asdict(review) for review in reviews],
                "sent": prior_sends(args.run_root),
                "served_models": sorted(ledger.served),
            }
    except (_Stop, RunRootBusy, ServedModelChanged, ModelCallError, ValueError, OSError) as exc:
        product = {"product": current} if current is not None else {}
        print(json.dumps({**_stop_detail(exc), **product}, ensure_ascii=False))
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
