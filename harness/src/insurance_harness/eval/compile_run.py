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

from insurance_harness.bundle.client import PlatformError
from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.catalog.trust_policy import TrustedPages, load_trust_policy
from insurance_harness.changes.options import fixed_revision_pages, registry_inputs, source_options
from insurance_harness.compilers.schema_fields.carry import (
    CarryRequest,
    active_carry,
    carry_for,
    located,
)
from insurance_harness.compilers.schema_fields.definitions import pack_definitions
from insurance_harness.compilers.schema_fields.engine import (
    SELECTION_DRAWS,
    CompileError,
    CompileOutput,
    CompletionPort,
    SchemaFieldsCompiler,
    reusable,
    to_candidate,
)
from insurance_harness.eval.compile_answers import (
    RecordedCompletion,
    Replay,
    next_attempt,
    replay_context,
)
from insurance_harness.eval.convert import predictions_from_candidate
from insurance_harness.eval.material_identity import (
    document_role_map,
    effective_roles,
    material_identities,
    validate_materials,
)
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
    ModelBudgetExceeded,
    ModelCallError,
    OpenAICompatibleCompletion,
    load_stage_config,
)
from insurance_harness.models.answers import check_answers
from insurance_harness.models.durable import (
    DurableLedger,
    RunRootBusy,
    ServedModelChanged,
    prior_sends,
    run_lock,
    stored_records,
    write_new,
)
from insurance_harness.models.run_files import IntegrityError, check_directory

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
    if carry is not None and revision_page_source is None:
        raise ValueError("carrying reviewed evidence needs fixed source revisions")
    if replay_from is None and completion_factory is None:
        raise ValueError("a completion factory is required unless replaying")
    check_directory(run_root)
    if replay_from is not None:
        check_answers(replay_from, offline=True)
        # A source whose last batch a served-model change rejected would be accepted here.
        if len({r.served_model for r in stored_records(replay_from) if r.served_model}) > 1:
            raise ServedModelChanged("replay source records more than one served model")
    with run_lock(run_root):
        try:
            check_answers(run_root, offline=True)
        except IntegrityError as error:
            # An exhausted root already refuses all new work. Raising its existing budget
            # error does not restore trust or allow an unknown receipt to be resent.
            if error.code == "OUTCOME_UNKNOWN" and prior_sends(run_root) >= max_sent:
                raise ModelBudgetExceeded("budget_exceeded") from None
            raise
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
            identified = material_identities(pages, headers, revisions)
            materials = [identity for identity, _ in identified]
            material_roles = effective_roles(identified, read)
            if revisions is not None:
                pages = _revision_order(pages, revisions)
                if headers is not None:
                    roles = list(load_trust_policy().restricted_roles())
                    headers = {role: _revision_order(headers[role], revisions)
                               for role in sorted(headers, key=roles.index)}
            carried = (carry_for(carry.release, product, materials)
                       if carry is not None else None)
            digest = carried.digest if carried is not None else None
            definitions = pack_definitions(repo / SCHEMA_PACK_CATALOG, pack)
            revision = definitions[0].catalog_revision if definitions else None
            if output is not None and reusable(
                output, materials, material_roles, catalog_revision=revision,
            ) and (
                carry is None or output.carry_digest == digest
            ):
                runs.append(ProductRun(product, name, pack, True, 0, len(output.fields)))
                continue
            context = replay_context(product, pack, pages, headers,
                                      materials if revisions is not None else None,
                                      trust_policy=load_trust_policy(), catalog_revision=revision)
            port: CompletionPort
            if replay_from is not None:
                port = Replay(replay_from, product, context)
            else:
                assert completion is not None
                responses = run_root / product / "responses"
                attempt = responses / next_attempt(responses)
                attempt.mkdir(parents=True)
                write_new(attempt / "context.json", context)
                port = RecordedCompletion(run_root, attempt, completion)
            # Step one sends SELECTION_DRAWS calls per batch (S12c-6); step two at most one call
            # per field.
            compiler = SchemaFieldsCompiler(
                port, batch_size=batch_size, selection_draws=SELECTION_DRAWS,
                max_calls=SELECTION_DRAWS * math.ceil(len(definitions) / batch_size)
                + len(definitions),
            )
            quotes = (located(carried, revisions, pages, headers)
                      if carried is not None and revisions is not None else None)
            reviewed = carried.values if carried is not None and quotes is not None else None
            output = compiler.compile(product, definitions, pages, table_headers=headers,
                                      carry=quotes, roles=document_role_map(read),
                                      reviewed=reviewed)
            if isinstance(port, Replay):
                port.finish()
            output = output.model_copy(update={
                "materials": materials, "material_roles": material_roles, "carry_digest": digest,
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
    if isinstance(exc, (RegistryError, IntegrityError, PlatformError)):
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
