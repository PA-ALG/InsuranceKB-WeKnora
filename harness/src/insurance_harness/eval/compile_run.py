"""Compile products with a stage-configured model and write a scoreable candidate.

Products compile in argument order; transport, budget, compiler or served-model failures stop
the run before later sends. Completed products are reused while materials and cards match.
Exit 0: every product and the candidate completed; exit 2: invalid input or a stopped run.

Run-root files: budget.jsonl gains one line before every send (so a send that
was in flight when the process died still counts), ledger.jsonl gains every
attempt record as it lands, <product>/responses/attempt-NN/ keeps raw
completions, and .lock serializes runs that share the root. With --replay-from, an
earlier run root's saved completions stand in for the model (selection batches, then
value batches, in call order): no client, no sends, no budget reservation.
"""

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.catalog.trust_policy import TrustedPages, load_trust_policy
from insurance_harness.changes.options import fixed_revision_pages, registry_inputs, source_options
from insurance_harness.compilers.schema_fields.carry import CarryRequest, active_carry, carry_for
from insurance_harness.compilers.schema_fields.definitions import pack_definitions
from insurance_harness.compilers.schema_fields.engine import (
    CompileError,
    CompileOutput,
    CompletionPort,
    SchemaFieldsCompiler,
    reusable,
    to_candidate,
)
from insurance_harness.eval.compile_materials import material_identities, validate_materials
from insurance_harness.eval.convert import predictions_from_candidate
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.eval.product_sources import (
    check_product_id,
    declared_pack,
    display_name,
    source_directory,
    trusted_source_pages,
)
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.ingest.registry import RegistryError
from insurance_harness.ingest.source_map import load_source_map, reader_from_env
from insurance_harness.models import (
    CallLedger,
    ModelCallError,
    OpenAICompatibleCompletion,
    load_stage_config,
)
from insurance_harness.models.durable import (
    DurableLedger,
    RunRootBusy,
    ServedModelChanged,
    prior_sends,
    run_lock,
    stored_records,
    write_new,
)

# The run-root guards live in models.durable (shared with the review run); callers of the
# compile run still catch its stop conditions and read its budget through this module.
__all__ = [
    "ProductRun",
    "RunRootBusy",
    "ServedModelChanged",
    "compile_products",
    "main",
    "prior_sends",
    "run_lock",
    "write_candidate",
]

RevisionPageSource = Callable[[str], tuple[TrustedPages[PageText], Mapping[str, SourceRevision]]]


def _replace_completed(path: Path, text: str) -> None:
    """Replace a stale result only after its complete successor is flushed beside it."""
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _revision_order(
    pages: Sequence[PageText], revisions: Mapping[str, SourceRevision],
) -> list[PageText]:
    return sorted(pages, key=lambda p: (revisions[p.document].knowledge_id,
                                       revisions[p.document].parse_attempt, p.page))


@dataclass(frozen=True)
class ProductRun:
    product_id: str
    display_name: str
    pack_id: str
    reused: bool
    calls: int
    fields: int


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
        write_new(self._directory / f"{self._count:03d}.txt", raw)
        # The answer is only meaningful for this exact request (segment ids name this source
        # text); replay refuses any other request.
        write_new(self._directory / f"{self._count:03d}.request.sha256",
                   _request_sha256(system, user))
        return raw


def _replay_context(
    product: str,
    pack: str,
    pages: Sequence[PageText],
    table_headers: Mapping[str, Sequence[PageText]] | None = None,
    materials: list[str] | None = None,
) -> str:
    """What a saved answer was produced for beyond the request text: product, pack, sources."""
    def documents(group: Sequence[PageText]) -> list[dict[str, object]]:
        sources: dict[tuple[str, str], int] = {}
        for page in group:
            key = (page.document, page.document_sha256)
            sources[key] = sources.get(key, 0) + 1
        return [{"document": d, "document_sha256": s, "pages": n}
                for (d, s), n in sources.items()]

    context: dict[str, object] = {"product": product, "pack_id": pack, "sources": documents(pages)}
    if materials is not None:
        context["materials"] = materials
    if table_headers is not None:
        context["trust_policy"] = load_trust_policy().model_dump(mode="json")
        context["table_headers"] = [
            {"role": role, "sources": documents(group)} for role, group in table_headers.items()
        ]
    return json.dumps(context, ensure_ascii=False, sort_keys=True) + "\n"


def _request_sha256(system: str, user: str) -> str:
    encoded = json.dumps([system, user], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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

    def __init__(self, source: Path, product: str, context: str) -> None:
        attempts = _attempts(source / product / "responses")
        if not attempts:
            raise ValueError(f"{product}: replay source has no saved responses")
        saved = attempts[-1] / "context.json"
        if not saved.exists() or saved.read_text(encoding="utf-8") != context:
            # Same visible text is not enough: the answers belong to one source snapshot and pack.
            raise ValueError(f"{product}: replay source was produced for another source or pack")
        self._saved = iter(sorted(attempts[-1].glob("[0-9][0-9][0-9].txt")))

    def complete(self, *, system: str, user: str) -> str:
        path = next(self._saved, None)
        if path is None:
            raise ValueError("replay source has fewer saved responses than calls")
        fingerprint = path.with_name(f"{path.stem}.request.sha256")
        if not fingerprint.exists():
            raise ValueError("replay source lacks the request fingerprint of a saved response")
        if fingerprint.read_text(encoding="utf-8").strip() != _request_sha256(system, user):
            # Source text, cards, definitions or prompt differ from the run that produced it.
            raise ValueError("replay request differs from the request that produced the response")
        return path.read_text(encoding="utf-8")


def compile_products(
    repo: Path, products: list[str], *,
    completion_factory: Callable[[CallLedger], CompletionPort] | None,
    run_root: Path, max_sent: int, batch_size: int = 25, replay_from: Path | None = None,
    page_source: Callable[[str], list[PageText] | TrustedPages[PageText]] | None = None,
    revision_page_source: RevisionPageSource | None = None,
    facts: Callable[[str], tuple[str, str]] | None = None,
    carry: CarryRequest | None = None,
) -> list[ProductRun]:
    """Compile or reuse each product in order; raise on the first stopping condition.

    max_sent is cumulative for the run root: earlier runs' sends count against it.
    With replay_from, saved completions stand in for the model and nothing is sent.
    revision_page_source supplies pages and their fixed revisions from one read; it is
    mutually exclusive with page_source, whose unlabelled inputs use file identities.
    Revision inputs use the same document and header-role order as publication.
    facts supplies (name, pack) without a dataset; it requires an explicit page source.
    carry hands step two the reviewed quotes of the given Active release (S12c-4); under it an
    output is reused only if it carried the same quotes. It needs revision_page_source.
    """
    if page_source is not None and revision_page_source is not None:
        raise ValueError("supply only one page source")
    if facts is not None and page_source is None and revision_page_source is None:
        raise ValueError("facts requires a page source")
    if replay_from is None and completion_factory is None:
        raise ValueError("a completion factory is required unless replaying")
    if replay_from is not None:
        # A source whose last batch a served-model change rejected would be accepted here.
        if len({r.served_model for r in stored_records(replay_from) if r.served_model}) > 1:
            raise ServedModelChanged("replay source records more than one served model")
    with run_lock(run_root):
        ledger = DurableLedger.open(run_root, max_sent=max_sent)
        completion = (
            completion_factory(ledger) if completion_factory and replay_from is None else None
        )
        runs: list[ProductRun] = []
        for product in products:
            check_product_id(product)
            name, pack = (facts(product) if facts is not None else (
                display_name(source_directory(repo, product)), declared_pack(repo, product),
            ))
            path = run_root / product / "output.json"
            if replay_from is not None and path.exists():
                # Reuse would skip the replay the caller asked for.
                raise ValueError(f"{product}: replay target already has an output; "
                                 "use a new run root")
            output = None
            if path.exists():
                output = CompileOutput.model_validate_json(path.read_text(encoding="utf-8"))
                if output.entity_id != product or output.pack_id != pack:
                    raise ValueError(f"{product}: stored output does not match the product")
                validate_materials(output.materials)
            revisions = None
            read: list[PageText] | TrustedPages[PageText]
            if revision_page_source is not None:
                read, revisions = revision_page_source(product)
            else:
                read = (page_source(product) if page_source else
                        trusted_source_pages(source_directory(repo, product)))
            pages = read.evidence if isinstance(read, TrustedPages) else read
            headers = read.table_headers if isinstance(read, TrustedPages) else None
            materials = material_identities(pages, headers, revisions)
            if revisions is not None:
                pages = _revision_order(pages, revisions)
                if headers is not None:
                    roles = [rule.role for rule in load_trust_policy().header_rules]
                    headers = {role: _revision_order(headers[role], revisions)
                               for role in sorted(headers, key=roles.index)}
            carried = (carry_for(carry, product, revisions, pages, headers)
                       if carry is not None else None)
            digest = carried.digest if carried is not None else None
            if output is not None and reusable(output, materials) and (
                carry is None or output.carry_digest == digest
            ):
                runs.append(ProductRun(product, name, pack, True, 0, len(output.fields)))
                continue
            definitions = pack_definitions(repo / SCHEMA_PACK_CATALOG, pack)
            context = _replay_context(product, pack, pages, headers,
                                      materials if revisions is not None else None)
            port: CompletionPort
            if replay_from is not None:
                port = _Replay(replay_from, product, context)
            else:
                assert completion is not None
                responses = run_root / product / "responses"
                attempt = responses / _next_attempt(responses)
                attempt.mkdir(parents=True)
                write_new(attempt / "context.json", context)
                port = _RawResponses(completion, attempt)
            # Step one sends one call per batch; step two at most one call per field.
            compiler = SchemaFieldsCompiler(
                port, batch_size=batch_size,
                max_calls=math.ceil(len(definitions) / batch_size) + len(definitions),
            )
            output = compiler.compile(product, definitions, pages, table_headers=headers,
                                      carry=carried.quotes if carried is not None else None)
            output = output.model_copy(update={
                "materials": materials, "carry_digest": digest,
                "carry_release": carried.release_id if digest is not None and carried else None,
            })
            if len(ledger.served) > 1:
                # The last batch itself came from a new version: nothing is written.
                raise ServedModelChanged(f"{product}: served model changed within the run")
            path.parent.mkdir(exist_ok=True)
            text = output.model_dump_json(indent=2) + "\n"
            if path.exists():
                _replace_completed(path, text)
            else:
                write_new(path, text)
            runs.append(ProductRun(product, name, pack, False, output.calls, len(output.fields)))
        return runs


def write_candidate(run_root: Path, runs: list[ProductRun], *, replace: bool = False) -> None:
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
    artifacts = [("candidate.json", merged), ("product-map.json", product_map)]
    if replace:
        previous = json.loads((run_root / "product-map.json").read_text(encoding="utf-8"))
        if not isinstance(previous, dict) or any(
            name in previous and previous[name] != product for name, product in product_map.items()
        ):
            raise ValueError("conflicting or invalid product registration")
        predictions_from_candidate(json.loads((run_root / "candidate.json").read_text()), previous)
        bridge = previous | product_map
        predictions_from_candidate(merged, bridge)
        # Each intermediate pair remains readable; a retry safely converges a leftover bridge.
        artifacts.insert(0, ("product-map.json", bridge))
    for name, data in artifacts:
        path = run_root / name
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        if replace and path.exists():
            _replace_completed(path, text)
        else:
            write_new(path, text)


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
    if isinstance(exc, RegistryError):
        return exc.code
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
    parser.add_argument("--carry-active", action="store_true",
                        help="hand step two the Active release's reviewed quotes (S12c-4)")
    source_options(parser, required=False)
    args = parser.parse_args(argv)
    runs: list[ProductRun] = []
    clients: list[OpenAICompatibleCompletion] = []
    try:
        config = load_stage_config(args.stage_config, args.stage)
        revision_pages = None
        facts = None
        if args.registry:
            source_map, registered = registry_inputs(args.registry, args.products)
            facts = registered.__getitem__
        elif args.source_map:
            source_map = load_source_map(args.source_map)
        if args.registry or args.source_map:
            revision_pages = fixed_revision_pages(source_map, reader_from_env())
        if args.carry_active and not args.registry:
            raise ValueError("--carry-active needs --registry")
        carry = active_carry(source_map.space_id) if args.carry_active else None

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
                        revision_page_source=revision_pages, facts=facts, carry=carry,
                    )
                finally:
                    for client in clients:
                        client.close()
                if any((args.run_root / name).exists()
                       for name in ("candidate.json", "product-map.json")):
                    write_candidate(args.run_root, runs, replace=True)
                else:
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
