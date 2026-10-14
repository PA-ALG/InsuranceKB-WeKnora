"""Compile products with a stage-configured model and write a scoreable candidate.

Products compile in argument order. The first truncation, oversize input,
non-retryable HTTP error, exhausted retries, budget refusal, compiler contract
violation or served-model change stops the run; later sends do not happen.
Completed products are reused on rerun. Exit 0: all products compiled and the
candidate was written; exit 2: the run stopped or the input was invalid.

Run-root files: budget.jsonl gains one line before every send (so a send that
was in flight when the process died still counts), ledger.jsonl gains every
attempt record as it lands, <product>/responses/attempt-NN/ keeps raw
completions, and .lock serializes runs that share the root.
"""

import argparse
import fcntl
import json
import math
import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from insurance_harness.compilers.schema_fields.definitions import pack_definitions
from insurance_harness.compilers.schema_fields.engine import (
    CompileError,
    CompileOutput,
    CompletionPort,
    SchemaFieldsCompiler,
    to_candidate,
)
from insurance_harness.eval.judge_files import check_run_directory
from insurance_harness.eval.product_sources import (
    check_product_id,
    declared_pack,
    display_name,
    source_directory,
    source_pages,
)
from insurance_harness.models import (
    CallLedger,
    CallRecord,
    ModelCallError,
    OpenAICompatibleCompletion,
    load_stage_config,
)

_CATALOG = "internal/handler/schema_pack_catalog_830_g3.generated.json"


class ServedModelChanged(RuntimeError):
    """A floating model alias resolved to a different version within one run root."""


class RunRootBusy(RuntimeError):
    """Another process holds the run root; sharing it could double-spend the budget."""


@dataclass(frozen=True)
class ProductRun:
    product_id: str
    display_name: str
    pack_id: str
    reused: bool
    calls: int
    fields: int


def _write_new(path: Path, text: str) -> None:
    """Create path atomically; an existing file (or stale temp) is never replaced."""
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(text)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()


def _append_durably(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def stored_records(run_root: Path) -> list[CallRecord]:
    return [CallRecord.model_validate_json(line) for line in _lines(run_root / "ledger.jsonl")]


def _recorded_sends(run_root: Path) -> int:
    return sum(record.outcome not in ("input_too_large", "budget_exceeded")
               for record in stored_records(run_root))


def prior_sends(run_root: Path) -> int:
    """Sends already spent in this root, counting reservations whose outcome never landed.

    budget.jsonl is authoritative once it exists: a baseline line carried over
    from an older ledger plus one line per reservation. Roots that predate it
    only have the ledger's recorded sends.
    """
    budget = run_root / "budget.jsonl"
    if not budget.exists():
        return _recorded_sends(run_root)
    total = 0
    for line in _lines(budget):
        entry = json.loads(line)
        total += entry.get("baseline", 0) + entry.get("reserved", 0)
    return total


def _adopt_legacy_budget(run_root: Path) -> None:
    """Persist an older root's recorded sends as the budget baseline, under the lock."""
    if not (run_root / "budget.jsonl").exists():
        _append_durably(
            run_root / "budget.jsonl", json.dumps({"baseline": _recorded_sends(run_root)}),
        )


class _DurableLedger(CallLedger):
    """Persist each send reservation before transport entry and each record on arrival.

    The served-model guard runs at reservation time, so a changed version stops
    the very next send, including retries and later batches of the same product.
    """

    def __init__(self, run_root: Path, *, max_sent: int, served: set[str]) -> None:
        super().__init__(max_sent=max_sent)
        self._root, self._served = run_root, served

    @property
    def served(self) -> set[str]:
        return set(self._served)

    def reserve_send(self) -> bool:
        if len(self._served) > 1:
            raise ServedModelChanged("served model changed; no further sends")
        if not super().reserve_send():
            return False
        _append_durably(self._root / "budget.jsonl", '{"reserved":1}')
        return True

    def append(self, record: CallRecord) -> None:
        super().append(record)
        _append_durably(self._root / "ledger.jsonl", record.model_dump_json())
        if record.served_model:
            self._served.add(record.served_model)


class _RawResponses:
    """Keep every raw completion beside the product so rejected output can be diagnosed.

    Completions are untrusted model output that may quote source material; they
    stay in the private run root and never enter logs, errors or the repository.
    """

    def __init__(self, inner: CompletionPort, directory: Path) -> None:
        self._inner, self._directory, self._count = inner, directory, 0

    @property
    def model(self) -> str:
        return self._inner.model

    def complete(self, *, system: str, user: str) -> str:
        raw = self._inner.complete(system=system, user=user)
        self._count += 1
        self._directory.mkdir(parents=True, exist_ok=True)
        _write_new(self._directory / f"{self._count:03d}.txt", raw)
        return raw


def _next_attempt(directory: Path) -> str:
    """Each compile attempt of a product keeps its own raw-response folder."""
    existing = [path.name for path in directory.glob("attempt-*") if path.is_dir()]
    return f"attempt-{len(existing) + 1:02d}"


_HELD: set[Path] = set()


@contextmanager
def run_lock(run_root: Path) -> Iterator[None]:
    """Exclusive across processes, reentrant within this one.

    The CLI holds it from the budget read until the candidate is written, and
    compile_products takes it again so direct callers are protected as well.
    """
    check_run_directory(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    key = run_root.resolve()
    if key in _HELD:
        yield
        return
    descriptor = os.open(run_root / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RunRootBusy("run root is in use by another process") from None
        _HELD.add(key)
        try:
            yield
        finally:
            _HELD.discard(key)
    finally:
        os.close(descriptor)


def compile_products(
    repo: Path, products: list[str], *,
    completion_factory: Callable[[CallLedger], CompletionPort],
    run_root: Path, max_sent: int, batch_size: int = 25,
) -> list[ProductRun]:
    """Compile or reuse each product in order; raise on the first stopping condition.

    max_sent is cumulative for the run root: earlier runs' sends count against it.
    """
    with run_lock(run_root):
        _adopt_legacy_budget(run_root)
        served = {record.served_model for record in stored_records(run_root)
                  if record.served_model}
        if len(served) > 1:
            raise ServedModelChanged("ledger already records more than one served model")
        ledger = _DurableLedger(
            run_root, max_sent=max(0, max_sent - prior_sends(run_root)), served=served,
        )
        completion = completion_factory(ledger)
        runs: list[ProductRun] = []
        for product in products:
            check_product_id(product)
            directory = source_directory(repo, product)
            name, pack = display_name(directory), declared_pack(repo, product)
            path = run_root / product / "output.json"
            if path.exists():
                output = CompileOutput.model_validate_json(path.read_text(encoding="utf-8"))
                if output.entity_id != product or output.pack_id != pack:
                    raise ValueError(f"{product}: stored output does not match the product")
                runs.append(ProductRun(product, name, pack, True, 0, len(output.fields)))
                continue
            definitions = pack_definitions(repo / _CATALOG, pack)
            attempt = _next_attempt(run_root / product / "responses")
            compiler = SchemaFieldsCompiler(
                _RawResponses(completion, run_root / product / "responses" / attempt),
                batch_size=batch_size, max_calls=math.ceil(len(definitions) / batch_size),
            )
            output = compiler.compile(product, definitions, source_pages(directory))
            if len(ledger.served) > 1:
                # The last batch itself came from a new version: nothing is written.
                raise ServedModelChanged(f"{product}: served model changed within the run")
            path.parent.mkdir(exist_ok=True)
            _write_new(path, output.model_dump_json(indent=2) + "\n")
            runs.append(ProductRun(product, name, pack, False, output.calls, len(output.fields)))
        return runs


def write_candidate(run_root: Path, runs: list[ProductRun]) -> None:
    """Merge per-product candidates into the shape predictions_from_candidate reads."""
    bindings: list[Any] = []
    fields: list[Any] = []
    for run in runs:
        output = CompileOutput.model_validate_json(
            (run_root / run.product_id / "output.json").read_text(encoding="utf-8"),
        )
        candidate = to_candidate(output, display_name=run.display_name, schema_pack_id=run.pack_id)
        request, result = candidate["request"], candidate["compile_result"]
        assert isinstance(request, dict) and isinstance(result, dict)
        bindings.extend(request["entity_bindings"])
        fields.extend(result["output"]["fields"])
    merged = {"request": {"entity_bindings": bindings},
              "compile_result": {"output": {"fields": fields}}}
    product_map = {run.display_name: run.product_id for run in runs}
    _write_new(run_root / "candidate.json", json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    _write_new(run_root / "product-map.json",
               json.dumps(product_map, ensure_ascii=False, indent=2) + "\n")


def _summary(run_root: Path, runs: list[ProductRun]) -> dict[str, Any]:
    """Cumulative for the run root, read back from its durable files."""
    try:
        records = stored_records(run_root)
        sent = prior_sends(run_root)
    except (OSError, ValueError):
        records, sent = [], 0

    def total(name: str) -> int:
        return sum(getattr(record, name) or 0 for record in records)

    return {
        "products": [asdict(run) for run in runs],
        "sent": sent,
        "attempts_by_outcome": {
            outcome: sum(record.outcome == outcome for record in records)
            for outcome in sorted({record.outcome for record in records})
        },
        "prompt_tokens": total("prompt_tokens"),
        "completion_tokens": total("completion_tokens"),
        "reasoning_tokens": total("reasoning_tokens"),
        "served_models": sorted({record.served_model for record in records if record.served_model}),
    }


def _stop_reason(exc: BaseException) -> str:
    """Fixed, content-free diagnostics: stored files and model output may hold source text."""
    if isinstance(exc, ValidationError):
        return "invalid_record_shape"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(exc, OSError):
        return f"file_operation_failed:{type(exc).__name__}"
    if isinstance(exc, (ModelCallError, CompileError, ServedModelChanged, RunRootBusy)):
        return f"{type(exc).__name__}: {exc}"
    return type(exc).__name__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--products", nargs="+", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--stage-config", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--max-sent", type=int, default=30)
    args = parser.parse_args(argv)
    runs: list[ProductRun] = []
    clients: list[OpenAICompatibleCompletion] = []
    try:
        config = load_stage_config(args.stage_config, args.stage)

        def factory(ledger: CallLedger) -> CompletionPort:
            clients.append(OpenAICompatibleCompletion(config, ledger=ledger))
            return clients[-1]

        # One lock spans the budget read, every send, the candidate and the summary.
        with run_lock(args.run_root):
            try:
                try:
                    runs = compile_products(
                        args.repo, args.products, completion_factory=factory,
                        run_root=args.run_root, max_sent=args.max_sent,
                        batch_size=args.batch_size,
                    )
                finally:
                    for client in clients:
                        client.close()
                write_candidate(args.run_root, runs)
            except (ModelCallError, CompileError, ServedModelChanged, ValueError,
                    OSError) as exc:
                print(json.dumps({"stopped": _stop_reason(exc),
                                  **_summary(args.run_root, runs)}, ensure_ascii=False))
                return 2
            print(json.dumps(_summary(args.run_root, runs), ensure_ascii=False))
            return 0
    except (ModelCallError, RunRootBusy, ValueError, OSError) as exc:
        print(json.dumps({"stopped": _stop_reason(exc), "products": []}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
