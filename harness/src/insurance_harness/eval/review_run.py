"""Score compiled products with the independent review stage and write RV1 scores files.

usage: python -m insurance_harness.eval.review_run --products P... --compile-root DIR
       [--compile-root DIR ...] --stage review --stage-config FILE --run-root DIR
       [--max-sent N] [--max-chars N] [--repo DIR]

Products are reviewed in argument order (RV2a Spec §3.3). Each takes its output from the first
compile root holding <root>/<product>/output.json and its pack's definitions from the catalog in
--repo (every formation method: the review covers whatever the output holds). Fields with content
are scored in batches; <run-root>/<product>/scores.json then gets {"reviewer": "<served model>@
<policy version>", "reviewed_at": ..., "scores": {...}}, the file the publish command's --scores
reads. A product that already has a scores file is skipped.

Run-root files: budget.jsonl, ledger.jsonl and .lock as in models.durable, so --max-sent counts
every send made in the root, the root records one served model, and runs on it never overlap.
<product>/responses/NNN.txt keeps every raw answer as it arrives; NNN.request.sha256 is written
once the scorer accepted that answer, and a rerun answers the same request from it without
sending. A rejected answer stays for diagnosis only, so a rerun sends its batch again (within
the budget). Exit 0: every product scored; exit 2: one line {"stopped": <code>, ...} with a fixed
code (and at most the product id and an exception type name), never a path, key or material.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

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
    scored: int | None  # None when an earlier run wrote the scores file
    reused: bool


class _Answers:
    """One product's answers: every raw answer is kept, accepted ones answer reruns.

    The fingerprint covers the reviewer identity (model and policy version) with the request,
    so an answer is reused only for the request and policy that produced it.
    """

    def __init__(
        self, inner: Completion, directory: Path, ledger: DurableLedger, identity: str
    ) -> None:
        self._inner, self._directory, self._ledger = inner, directory, ledger
        self._identity = identity
        self._pending: list[tuple[str, str]] = []
        self._accepted: dict[str, Path] = {}
        for path in directory.glob("*.request.sha256"):
            answer = directory / f"{path.name.removesuffix('.request.sha256')}.txt"
            if answer.exists():
                self._accepted[path.read_text(encoding="utf-8").strip()] = answer

    def complete(self, *, system: str, user: str) -> str:
        encoded = json.dumps([self._identity, system, user], ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        saved = self._accepted.get(digest)
        if saved is not None:
            return saved.read_text(encoding="utf-8")
        raw = self._inner.complete(system=system, user=user)
        if len(self._ledger.served) > 1:
            # This answer came from another served version: it is neither scored nor kept.
            raise ServedModelChanged("served model changed within the run")
        self._directory.mkdir(parents=True, exist_ok=True)
        stem = f"{self._next_number():03d}"
        write_new(self._directory / f"{stem}.txt", raw)
        self._pending.append((stem, digest))
        return raw

    def accept(self) -> None:
        """The answers since the last call were accepted: reruns may now reuse them."""
        for stem, digest in self._pending:
            write_new(self._directory / f"{stem}.request.sha256", digest + "\n")
            self._accepted[digest] = self._directory / f"{stem}.txt"
        self._pending.clear()

    def _next_number(self) -> int:
        stems = (path.name.split(".", 1)[0] for path in self._directory.glob("*.txt"))
        return max((int(stem) for stem in stems if stem.isdigit()), default=0) + 1


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
    if target.exists():
        return ProductReview(product, None, True)
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
    )
    scores: dict[str, float] = {}
    # One batch at a time (batching a batch again returns it unchanged), so an answer becomes
    # reusable only after the scorer accepted it.
    for batch in review_batches(items, max_chars=max_chars):
        scores.update(score_items(batch, answers, max_chars=max_chars))
        answers.accept()
    # One served model per root (DurableLedger); a provider that names none leaves the alias.
    served = sorted(ledger.served) or [config.model]
    document = {
        "reviewer": f"{served[0]}@{config.policy_version}",
        "reviewed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "scores": scores,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    write_new(target, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
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
            client = OpenAICompatibleCompletion(config, ledger=ledger)
            reviews: list[ProductReview] = []
            try:
                for current in args.products:
                    reviews.append(
                        _review_product(
                            current,
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
