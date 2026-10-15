"""Compile products with a stage-configured model and write a scoreable candidate.

Products compile in argument order. The first truncation, oversize input,
non-retryable HTTP error, exhausted retries, budget refusal, compiler contract
violation or served-model change stops the run; later sends do not happen.
Completed products are reused on rerun. Exit 0: all products compiled and the
candidate was written; exit 2: the run stopped or the input was invalid.

Run-root files: budget.jsonl gains one line before every send (so a send that
was in flight when the process died still counts), ledger.jsonl gains every
attempt record as it lands, <product>/responses/attempt-NN/ keeps raw
completions, and .lock serializes runs that share the root. With --replay-from, an
earlier run root's saved completions stand in for the model (selection batches, then
value batches, in call order): no client, no sends, no budget reservation.
"""

import argparse
import fcntl
import json
import math
import os
import sys
import threading
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
    """Create path atomically and durably; an existing file (or stale temp) is never replaced."""
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
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

    budget.jsonl is authoritative once it exists. It is created atomically with
    a baseline line (an older root's recorded sends, else 0), followed by one
    line per reservation. A file without that first baseline line cannot be
    trusted to be complete, so it fails closed. Roots that predate the file
    only have the ledger's recorded sends.
    """
    budget = run_root / "budget.jsonl"
    if not budget.exists():
        return _recorded_sends(run_root)
    entries = [json.loads(line) for line in _lines(budget)]
    if not entries or not _is_entry(entries[0], "baseline"):
        raise ValueError("budget.jsonl lacks its baseline line; refusing to infer spent sends")
    if not all(_is_entry(entry, "reserved") and entry["reserved"] == 1 for entry in entries[1:]):
        raise ValueError("budget.jsonl has an unexpected entry")
    return int(entries[0]["baseline"]) + len(entries) - 1


def _is_entry(entry: object, key: str) -> bool:
    """Exactly {key: non-negative int}; bools, floats and extra keys are rejected."""
    if not isinstance(entry, dict) or set(entry) != {key}:
        return False
    value = entry[key]
    return type(value) is int and value >= 0


def _adopt_legacy_budget(run_root: Path) -> None:
    """Create budget.jsonl atomically with its baseline, under the lock."""
    if not (run_root / "budget.jsonl").exists():
        _write_new(run_root / "budget.jsonl",
                   json.dumps({"baseline": _recorded_sends(run_root)}) + "\n")


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


def _attempts(directory: Path) -> list[Path]:
    """Attempt folders in numeric order; zero padding is only a minimum width."""
    found = [(int(path.name[len("attempt-"):]), path) for path in directory.glob("attempt-*")
             if path.is_dir() and path.name[len("attempt-"):].isdigit()]
    return [path for _, path in sorted(found)]


def _next_attempt(directory: Path) -> str:
    """Each compile attempt of a product keeps its own raw-response folder."""
    attempts = _attempts(directory)
    latest = int(attempts[-1].name[len("attempt-"):]) if attempts else 0
    return f"attempt-{latest + 1:02d}"


class _Replay:
    """Serve one product's saved completions in call order instead of calling a model."""

    model = "replay"

    def __init__(self, source: Path, product: str) -> None:
        attempts = _attempts(source / product / "responses")
        if not attempts:
            raise ValueError(f"{product}: replay source has no saved responses")
        self._saved = iter(sorted(attempts[-1].glob("[0-9][0-9][0-9].txt")))

    def complete(self, *, system: str, user: str) -> str:
        path = next(self._saved, None)
        if path is None:
            raise ValueError("replay source has fewer saved responses than calls")
        return path.read_text(encoding="utf-8")


_HELD: dict[Path, int] = {}


@contextmanager
def run_lock(run_root: Path) -> Iterator[None]:
    """Exclusive across processes and threads; reentrant only for the owning thread.

    The CLI holds it from the budget read until the candidate is written, and
    compile_products takes it again so direct callers are protected as well.
    Another thread opens its own descriptor, which flock then refuses.
    """
    check_run_directory(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    key = run_root.resolve()
    if _HELD.get(key) == threading.get_ident():
        yield
        return
    descriptor = os.open(run_root / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RunRootBusy("run root is in use by another process") from None
        _HELD[key] = threading.get_ident()
        try:
            yield
        finally:
            del _HELD[key]
    finally:
        os.close(descriptor)


def compile_products(
    repo: Path, products: list[str], *,
    completion_factory: Callable[[CallLedger], CompletionPort] | None,
    run_root: Path, max_sent: int, batch_size: int = 25, replay_from: Path | None = None,
) -> list[ProductRun]:
    """Compile or reuse each product in order; raise on the first stopping condition.

    max_sent is cumulative for the run root: earlier runs' sends count against it.
    With replay_from, saved completions stand in for the model and nothing is sent.
    """
    if replay_from is None and completion_factory is None:
        raise ValueError("a completion factory is required unless replaying")
    if replay_from is not None:
        # A source whose last batch a served-model change rejected would be accepted here.
        if len({r.served_model for r in stored_records(replay_from) if r.served_model}) > 1:
            raise ServedModelChanged("replay source records more than one served model")
    with run_lock(run_root):
        _adopt_legacy_budget(run_root)
        served = {record.served_model for record in stored_records(run_root)
                  if record.served_model}
        if len(served) > 1:
            raise ServedModelChanged("ledger already records more than one served model")
        ledger = _DurableLedger(
            run_root, max_sent=max(0, max_sent - prior_sends(run_root)), served=served,
        )
        completion = (
            completion_factory(ledger) if completion_factory and replay_from is None else None
        )
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
            port: CompletionPort
            if replay_from is not None:
                port = _Replay(replay_from, product)
            else:
                assert completion is not None
                attempt = _next_attempt(run_root / product / "responses")
                port = _RawResponses(completion, run_root / product / "responses" / attempt)
            # Step one sends one call per batch; step two at most one call per field.
            compiler = SchemaFieldsCompiler(
                port, batch_size=batch_size,
                max_calls=math.ceil(len(definitions) / batch_size) + len(definitions),
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
    parser.add_argument("--replay-from", type=Path,
                        help="recompile saved completions of an earlier run root; sends nothing")
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
                        args.repo, args.products,
                        completion_factory=None if args.replay_from else factory,
                        run_root=args.run_root, max_sent=args.max_sent,
                        batch_size=args.batch_size, replay_from=args.replay_from,
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
