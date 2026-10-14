"""Compile products with a stage-configured model and write a scoreable candidate.

Products compile in argument order. The first truncation, oversize input,
non-retryable HTTP error, exhausted retries, budget refusal, compiler contract
violation or served-model change stops the run; later products are not sent.
Completed products are reused on rerun, and every attempt is appended to
ledger.jsonl. Exit 0: all products compiled and the candidate was written;
exit 2: the run stopped or the input was invalid.
"""

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

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
    """A floating model alias resolved to a different version within one run."""


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


class _LedgerFile:
    """Append each attempt exactly once, including those of a failed product."""

    def __init__(self, path: Path, ledger: CallLedger) -> None:
        self._path, self._ledger, self._written = path, ledger, 0

    def stored(self) -> list[CallRecord]:
        if not self._path.exists():
            return []
        return [CallRecord.model_validate_json(line)
                for line in self._path.read_text(encoding="utf-8").splitlines() if line]

    def flush(self) -> None:
        records = self._ledger.records[self._written:]
        if records:
            with self._path.open("a", encoding="utf-8") as stream:
                stream.writelines(record.model_dump_json() + "\n" for record in records)
            self._written += len(records)


def _next_attempt(directory: Path) -> str:
    """Each compile attempt of a product keeps its own raw-response folder."""
    existing = [path.name for path in directory.glob("attempt-*") if path.is_dir()]
    return f"attempt-{len(existing) + 1:02d}"


def prior_sends(run_root: Path) -> int:
    """Sends already spent by earlier runs in this root; the budget is cumulative."""
    path = run_root / "ledger.jsonl"
    if not path.exists():
        return 0
    return sum(
        CallRecord.model_validate_json(line).outcome not in ("input_too_large", "budget_exceeded")
        for line in path.read_text(encoding="utf-8").splitlines() if line
    )


def compile_products(
    repo: Path, products: list[str], *, completion: CompletionPort, ledger: CallLedger,
    run_root: Path, batch_size: int = 25,
) -> list[ProductRun]:
    """Compile or reuse each product in order; raise on the first stopping condition."""
    check_run_directory(run_root)
    if ledger.records:
        # The sink appends every record of this ledger; a reused one would duplicate.
        raise ValueError("compile_products needs a fresh ledger")
    run_root.mkdir(parents=True, exist_ok=True)
    sink = _LedgerFile(run_root / "ledger.jsonl", ledger)
    served = {record.served_model for record in sink.stored() if record.served_model}
    if len(served) > 1:
        raise ServedModelChanged("ledger already records more than one served model")
    runs: list[ProductRun] = []
    try:
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
            recorder = _RawResponses(completion, run_root / product / "responses" / attempt)
            compiler = SchemaFieldsCompiler(
                recorder, batch_size=batch_size,
                max_calls=math.ceil(len(definitions) / batch_size),
            )
            output = compiler.compile(product, definitions, source_pages(directory))
            sink.flush()
            served |= {record.served_model for record in ledger.records if record.served_model}
            if len(served) > 1:
                # Results from two model versions cannot form one quality number.
                raise ServedModelChanged(f"{product}: served model changed within the run")
            path.parent.mkdir(exist_ok=True)
            _write_new(path, output.model_dump_json(indent=2) + "\n")
            runs.append(ProductRun(product, name, pack, False, output.calls, len(output.fields)))
    finally:
        sink.flush()
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


def _summary(runs: list[ProductRun], ledger: CallLedger) -> dict[str, Any]:
    records = ledger.records

    def total(name: str) -> int:
        return sum(getattr(record, name) or 0 for record in records)

    return {
        "products": [asdict(run) for run in runs],
        "sent": ledger.sent,
        "attempts_by_outcome": {
            outcome: sum(record.outcome == outcome for record in records)
            for outcome in sorted({record.outcome for record in records})
        },
        "prompt_tokens": total("prompt_tokens"),
        "completion_tokens": total("completion_tokens"),
        "reasoning_tokens": total("reasoning_tokens"),
        "served_models": sorted({record.served_model for record in records if record.served_model}),
    }


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
    ledger = CallLedger(max_sent=max(0, args.max_sent - prior_sends(args.run_root)))
    try:
        config = load_stage_config(args.stage_config, args.stage)
        completion = OpenAICompatibleCompletion(config, ledger=ledger)
        try:
            runs = compile_products(
                args.repo, args.products, completion=completion, ledger=ledger,
                run_root=args.run_root, batch_size=args.batch_size,
            )
        finally:
            completion.close()
        write_candidate(args.run_root, runs)
    except (ModelCallError, CompileError, ServedModelChanged, ValueError, OSError) as exc:
        # Model and compiler errors carry metadata only; OS errors may hold local paths.
        detail = type(exc).__name__ if isinstance(exc, OSError) else str(exc)
        print(json.dumps({"stopped": detail, **_summary(runs, ledger)}, ensure_ascii=False))
        return 2
    print(json.dumps(_summary(runs, ledger), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
