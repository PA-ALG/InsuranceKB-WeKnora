"""`python -m insurance_harness.compilers.methods`: the method commands (SK-2 Spec §7, SK-2b §3–§6).

- `values`: answer the value requests the compile will make on a model, within a budget, reading
  the registry without its lock; answers are saved by request digest (SK-2c §3).
- `compile`: under the registry lock, admit the candidates, compile every method from its saved
  answers (never sending a request) and assemble one candidate against the Active release; write
  the plan (`candidate.json` when anything changes, `review_items.json`, `report.json`, put in place
  as one set with the report last) and only then the registry, in one atomic step. `--live` then
  submits the candidate for people to decide, once per planned candidate (SK-2c §4.2).
- `copies`: bring the discovery base's copies in line with the active method-use records; a plan
  unless `--live`, which uploads and deletes copies and then writes the mapping.
- `candidates`: read the discovery base's native pages and write the candidate file (read only).
- `withdraw`: suppress one method and plan the removal of its members; `--live` also submits that
  candidate for people to decide.

Output is codes and counts, never material text or file names.
"""

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from insurance_harness.bundle.assemble import BundleError
from insurance_harness.bundle.client import PlatformClient, PlatformError
from insurance_harness.compilers.methods.admission import AdmissionError, load_candidates
from insurance_harness.compilers.methods.candidates import method_candidates
from insurance_harness.compilers.methods.compile import MethodRun, compile_methods
from insurance_harness.compilers.methods.copies import (
    CopiesError,
    check_discovery_kb,
    load_copies,
    save_copies,
    sync_copies,
)
from insurance_harness.compilers.methods.platform import MaterialPlatform, PlatformCallError
from insurance_harness.compilers.methods.responses import (
    LedgerAnswers,
    ResponsesError,
    SavedResponses,
    is_value_directory,
)
from insurance_harness.compilers.methods.values import ValuesStopped, method_values
from insurance_harness.compilers.methods.withdraw import WithdrawError, withdraw_method
from insurance_harness.compilers.schema_fields.engine import CompletionPort
from insurance_harness.compilers.wiki_pages.native import NativeWikiError, NativeWikiReader
from insurance_harness.contracts.bundle import CandidateBundle
from insurance_harness.contracts.compile import ReviewItem
from insurance_harness.evidence.weknora_pages import SourcePagesError
from insurance_harness.ingest.registry import RegistryError, load_registry, save_registry
from insurance_harness.ingest.registry_lock import RegistryBusy, RegistryLock
from insurance_harness.ingest.source_map import (
    API_KEY_ENV,
    BASE_URL_ENV,
    SourceMapError,
    reader_from_env,
)
from insurance_harness.models import ModelConfigError, load_stage_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m insurance_harness.compilers.methods")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("compile", help="admit candidates and plan one method bundle")
    run.add_argument("--registry", type=Path, required=True)
    run.add_argument("--candidates", type=Path, required=True)
    run.add_argument("--responses", type=Path, required=True)
    run.add_argument("--model", help="the model that wrote the saved answers (default: theirs)")
    run.add_argument("--run-root", type=Path, required=True)
    run.add_argument("--live", action="store_true", help="submit the planned candidate")
    values = commands.add_parser("values", help="answer the value requests on a model")
    values.add_argument("--registry", type=Path, required=True)
    values.add_argument("--candidates", type=Path, required=True)
    values.add_argument("--responses", type=Path, required=True)
    values.add_argument("--stage-config", type=Path, required=True)
    values.add_argument("--stage", default="methods")
    values.add_argument("--max-sent", type=int, required=True)
    for name in ("copies", "candidates"):
        step = commands.add_parser(name)
        step.add_argument("--registry", type=Path, required=True)
        step.add_argument("--copies", type=Path, required=True)
        step.add_argument("--discovery-kb", required=True)
    commands.choices["copies"].add_argument("--run-root", type=Path, required=True)
    commands.choices["copies"].add_argument("--live", action="store_true")
    commands.choices["candidates"].add_argument("--out", type=Path, required=True)
    withdraw = commands.add_parser("withdraw")
    withdraw.add_argument("--registry", type=Path, required=True)
    withdraw.add_argument("--method-id", required=True)
    withdraw.add_argument("--run-root", type=Path, required=True)
    withdraw.add_argument("--live", action="store_true")
    return parser


def _write_plan(
    run_root: Path,
    bundle: CandidateBundle | None,
    review_items: Sequence[ReviewItem],
    report: dict[str, Any],
) -> dict[str, str | None]:
    """The plan files as one set (#516 R2). All are prepared beside their places first, so a
    failure there leaves the previous set as it was; then `report.json` is removed, the others are
    put in place, and `report.json` comes last, naming the digests of the others. A run root
    without `report.json`, or whose digests differ, holds no complete plan."""
    run_root.mkdir(parents=True, exist_ok=True)
    items = [item.model_dump(mode="json") for item in review_items]
    texts = {"review_items.json": json.dumps(items, ensure_ascii=False, indent=1) + "\n"}
    if bundle is not None:
        texts["candidate.json"] = bundle.model_dump_json(indent=1) + "\n"
    plan = {
        name: _digest(texts[name]) if name in texts else None
        for name in ("candidate.json", "review_items.json")
    }
    texts["report.json"] = json.dumps({**report, "plan": plan}, ensure_ascii=False, indent=1) + "\n"
    prepared: dict[str, Path] = {}
    try:
        for name, text in texts.items():
            prepared[name] = run_root / f".{name}.prepared"
            prepared[name].write_text(text, encoding="utf-8")
        (run_root / "report.json").unlink(missing_ok=True)  # incomplete from here on
        if bundle is None:
            (run_root / "candidate.json").unlink(missing_ok=True)  # not this run's plan
        for name in ("candidate.json", "review_items.json", "report.json"):
            if name in prepared:
                os.replace(prepared[name], run_root / name)
    finally:
        for path in prepared.values():
            path.unlink(missing_ok=True)
    return plan


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _summary(run: MethodRun) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    for method in run.report["methods"]:
        statuses[method["status"]] = statuses.get(method["status"], 0) + 1
    return {
        "members": run.report["members"],
        "removals": run.report["removals"],
        "no_changes": run.report["no_changes"],
        "methods": dict(sorted(statuses.items())),
        "candidates": run.report["candidates"]["dropped"],
        "review_items": len(run.review_items),
    }


def _answers(directory: Path, model: str | None, live: bool) -> CompletionPort:
    """Where the compile reads its answers (SK-2c §4.1): a value directory's answers only with the
    ledger records that back them, under the model those record; a directory prepared by hand only
    offline, under the model the caller names."""
    if is_value_directory(directory):
        return LedgerAnswers(directory, model)
    if live:
        raise ResponsesError("ANSWERS_UNVERIFIED")
    if model is None:
        raise ResponsesError("MODEL_UNKNOWN")
    return SavedResponses(directory, model)


def _compile(args: argparse.Namespace, base_url: str, api_key: str) -> dict[str, Any]:
    port = _answers(args.responses, args.model, args.live)
    with RegistryLock(args.registry):
        registry = load_registry(args.registry)
        candidates = load_candidates(args.candidates)
        client = PlatformClient(base_url, api_key)
        run = compile_methods(
            registry,
            candidates,
            pages=reader_from_env(),
            port=port,
            active=client.active(registry.space_id),
        )
        plan = _write_plan(args.run_root, run.bundle, run.review_items, run.report)
        save_registry(run.registry, args.registry)
        summary = _summary(run)
        if args.live:
            submitted = _submit(client, registry.space_id, run.bundle, plan, args.run_root)
            summary.update(submitted)
    return summary


def _submit(
    client: PlatformClient,
    space_id: str,
    bundle: CandidateBundle | None,
    plan: dict[str, str | None],
    run_root: Path,
) -> dict[str, Any]:
    """Submit the planned candidate unless its receipt says the same content already went to the
    same Space (SK-2c §4.2); the receipt is written only after a success."""
    if bundle is None:
        return {"submitted": "nothing", "candidate_id": None}
    content, path = _content_digest(bundle), run_root / "submitted.json"
    if path.exists():
        earlier = _receipt(path)
        if (earlier["space_id"], earlier["content_sha256"]) == (space_id, content):
            return {"submitted": "already", "candidate_id": earlier["candidate_id"]}
    candidate_id = client.submit(space_id, bundle).id
    receipt: dict[str, str | None] = {
        "space_id": space_id,
        "content_sha256": content,
        "candidate_sha256": plan["candidate.json"],
        "candidate_id": candidate_id,
    }
    prepared = run_root / ".submitted.json.prepared"
    prepared.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
    os.replace(prepared, path)
    return {"submitted": "new", "candidate_id": candidate_id}


def _content_digest(bundle: CandidateBundle) -> str:
    """The candidate without the compile time each member Claim records, and the member digests
    that follow from it: the same inputs compile to the same content (SK-2c §4.2)."""
    data = bundle.model_dump(mode="json")
    for member in data["members"]:
        member.pop("member_digest", None)
        maintenance = member["payload"].get("maintenance")
        if isinstance(maintenance, dict):
            maintenance.pop("changed_at", None)
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _digest(encoded)


def _receipt(path: Path) -> dict[str, str]:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise ResponsesError("RECEIPT_INVALID") from None
    if not (
        isinstance(receipt, dict)
        and set(receipt) == {"space_id", "content_sha256", "candidate_sha256", "candidate_id"}
        and all(isinstance(value, str) and value for value in receipt.values())
    ):
        raise ResponsesError("RECEIPT_INVALID")
    return receipt


def _values(args: argparse.Namespace, base_url: str, api_key: str) -> dict[str, Any]:
    if args.max_sent < 0:
        raise ValuesStopped("INVALID_ARGUMENTS")
    try:
        config = load_stage_config(args.stage_config, args.stage)
    except ModelConfigError:
        raise ValuesStopped("MODEL_CONFIG_INVALID") from None
    registry = load_registry(args.registry)  # read only: the compile holds the lock, not this
    return method_values(
        registry,
        load_candidates(args.candidates),
        pages=reader_from_env(),
        root=args.responses,
        config=config,
        max_sent=args.max_sent,
    )


def _copies(args: argparse.Namespace, base_url: str, api_key: str) -> dict[str, Any]:
    registry = load_registry(args.registry)  # read only: records change under `uploads`
    with RegistryLock(args.copies):
        book = load_copies(args.copies, registry.space_id, args.discovery_kb)
        result = sync_copies(registry, book, MaterialPlatform(base_url, api_key), live=args.live)
        args.run_root.mkdir(parents=True, exist_ok=True)
        (args.run_root / "copy_report.json").write_text(
            json.dumps(result.report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        if args.live:
            save_copies(result.book, args.copies)
    return result.report


def _candidates(args: argparse.Namespace, base_url: str, api_key: str) -> dict[str, Any]:
    registry = load_registry(args.registry)
    book = load_copies(args.copies, registry.space_id, args.discovery_kb)
    check_discovery_kb(registry, book)  # before anything is read from it (#518 R2)
    listing = MaterialPlatform(base_url, api_key).listing(book.discovery_kb_id)
    pages = NativeWikiReader(base_url, api_key).pages(book.discovery_kb_id)
    run = method_candidates(registry, book, listing, pages, reader_from_env())
    written = args.out.with_name(f".{args.out.name}.prepared")
    written.write_text(run.candidates.model_dump_json(indent=1) + "\n", encoding="utf-8")
    os.replace(written, args.out)
    return run.report


def _withdraw(args: argparse.Namespace, base_url: str, api_key: str) -> dict[str, Any]:
    with RegistryLock(args.registry):
        registry = load_registry(args.registry)
        client = PlatformClient(base_url, api_key)
        result = withdraw_method(registry, args.method_id, client.active(registry.space_id))
        _write_plan(args.run_root, result.bundle, (), result.report)
        save_registry(result.registry, args.registry)  # suppressed before anything is submitted
        candidate_id = None
        if args.live and result.bundle is not None:
            candidate_id = client.submit(registry.space_id, result.bundle).id
    return {**result.report, "candidate_id": candidate_id}


_COMMANDS = {"compile": _compile, "values": _values, "copies": _copies,
             "candidates": _candidates, "withdraw": _withdraw}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    base_url, api_key = os.environ.get(BASE_URL_ENV, ""), os.environ.get(API_KEY_ENV, "")
    if not base_url or not api_key:
        return _emit({"stopped": "CONFIGURATION_MISSING"}, 2)
    try:
        summary = _COMMANDS[args.command](args, base_url, api_key)
    except RegistryBusy:
        return _emit({"stopped": "REGISTRY_BUSY"}, 3)
    except ValuesStopped as stop:
        return _emit(_stopped(stop), 2)
    except (
        RegistryError, AdmissionError, CopiesError, WithdrawError, PlatformError,
        PlatformCallError, SourceMapError, SourcePagesError, NativeWikiError, ResponsesError,
    ) as error:
        return _emit({"stopped": error.code}, 2)
    except BundleError as error:
        return _emit({"stopped": "BUNDLE_INVALID", "reason": error.reason}, 2)
    except OSError:
        return _emit({"stopped": "LOCAL_IO_FAILED"}, 2)
    except ValueError:  # a change decision refusing an ambiguous Active release
        return _emit({"stopped": "BUNDLE_INVALID", "reason": "CONVERSION_FAILED"}, 2)
    return _emit(summary)


def _stopped(stop: ValuesStopped) -> dict[str, Any]:
    """A value run's stop: its code, the error type for a model error, and the sends once the
    value directory's budget was read (SK-2c §3.3)."""
    summary: dict[str, Any] = {"stopped": stop.code}
    if stop.error is not None:
        summary["error"] = stop.error
    if stop.sent is not None:
        summary.update(sent=stop.sent, sent_total=stop.sent_total)
    return summary


def _emit(summary: dict[str, Any], status: int = 0) -> int:
    print(json.dumps(summary, ensure_ascii=False))
    return status


if __name__ == "__main__":
    sys.exit(main())
