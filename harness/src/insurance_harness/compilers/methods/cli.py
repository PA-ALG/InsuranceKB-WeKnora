"""`python -m insurance_harness.compilers.methods`: the method commands (SK-2 Spec §7, SK-2b §3–§6).

- `compile`: under the registry lock, admit the candidates, compile every method from its saved
  answers (never sending a request) and assemble one candidate against the Active release; write
  the plan (`candidate.json` when anything changes, `review_items.json`, `report.json`, put in place
  as one set with the report last) and only then the registry, in one atomic step.
- `copies`: bring the discovery base's copies in line with the active method-use records; a plan
  unless `--live`, which uploads and deletes copies and then writes the mapping.
- `candidates`: read the discovery base's native pages and write the candidate file (read only).
- `withdraw`: suppress one method and plan the removal of its members; `--live` also submits that
  candidate for people to decide.

Output is codes and counts, never material text or file names. The live value stage and
`compile --live` join in SK-2c.
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
    load_copies,
    save_copies,
    sync_copies,
)
from insurance_harness.compilers.methods.platform import MaterialPlatform, PlatformCallError
from insurance_harness.compilers.methods.responses import SavedResponses
from insurance_harness.compilers.methods.withdraw import WithdrawError, withdraw_method
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m insurance_harness.compilers.methods")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("compile", help="admit candidates and plan one method bundle")
    run.add_argument("--registry", type=Path, required=True)
    run.add_argument("--candidates", type=Path, required=True)
    run.add_argument("--responses", type=Path, required=True)
    run.add_argument("--model", required=True, help="the model that wrote the saved answers")
    run.add_argument("--run-root", type=Path, required=True)
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
) -> None:
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


def _compile(args: argparse.Namespace, base_url: str, api_key: str) -> dict[str, Any]:
    with RegistryLock(args.registry):
        registry = load_registry(args.registry)
        candidates = load_candidates(args.candidates)
        active = PlatformClient(base_url, api_key).active(registry.space_id)
        run = compile_methods(
            registry,
            candidates,
            pages=reader_from_env(),
            port=SavedResponses(args.responses, args.model),
            active=active,
        )
        _write_plan(args.run_root, run.bundle, run.review_items, run.report)
        save_registry(run.registry, args.registry)
    return _summary(run)


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


_COMMANDS = {"compile": _compile, "copies": _copies, "candidates": _candidates,
             "withdraw": _withdraw}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    base_url, api_key = os.environ.get(BASE_URL_ENV, ""), os.environ.get(API_KEY_ENV, "")
    if not base_url or not api_key:
        return _emit({"stopped": "CONFIGURATION_MISSING"}, 2)
    try:
        summary = _COMMANDS[args.command](args, base_url, api_key)
    except RegistryBusy:
        return _emit({"stopped": "REGISTRY_BUSY"}, 3)
    except (
        RegistryError, AdmissionError, CopiesError, WithdrawError, PlatformError,
        PlatformCallError, SourceMapError, SourcePagesError, NativeWikiError,
    ) as error:
        return _emit({"stopped": error.code}, 2)
    except BundleError as error:
        return _emit({"stopped": "BUNDLE_INVALID", "reason": error.reason}, 2)
    except OSError:
        return _emit({"stopped": "LOCAL_IO_FAILED"}, 2)
    except ValueError:  # a change decision refusing an ambiguous Active release
        return _emit({"stopped": "BUNDLE_INVALID", "reason": "CONVERSION_FAILED"}, 2)
    return _emit(summary)


def _emit(summary: dict[str, Any], status: int = 0) -> int:
    print(json.dumps(summary, ensure_ascii=False))
    return status


if __name__ == "__main__":
    sys.exit(main())
