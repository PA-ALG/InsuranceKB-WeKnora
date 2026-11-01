"""`python -m insurance_harness.compilers.methods compile`: one offline method run (Spec §6–§8).

Under the registry lock: load the registry, admit the candidates, compile every method from its
saved answers (never sending a request), and assemble one candidate bundle against the Active
release; then write the plan (`candidate.json` when anything changes, `review_items.json`,
`report.json`, put in place as one set with the report last) and only then the registry, in one
atomic step. Any failure before that leaves the
registry as it was. Nothing is submitted: the live model stage, submission and withdrawal join in
SK-2b. Output is codes and counts, never material text.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from insurance_harness.bundle.assemble import BundleError
from insurance_harness.bundle.client import PlatformClient, PlatformError
from insurance_harness.compilers.methods.admission import AdmissionError, load_candidates
from insurance_harness.compilers.methods.compile import MethodRun, compile_methods
from insurance_harness.compilers.methods.responses import SavedResponses
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
    return parser


def _write_plan(run_root: Path, run: MethodRun) -> None:
    """The plan files as one set (#516 R2). All are prepared beside their places first, so a
    failure there leaves the previous set as it was; then `report.json` is removed, the others are
    put in place, and `report.json` comes last, naming the digests of the others. A run root
    without `report.json`, or whose digests differ, holds no complete plan."""
    run_root.mkdir(parents=True, exist_ok=True)
    items = [item.model_dump(mode="json") for item in run.review_items]
    texts = {"review_items.json": json.dumps(items, ensure_ascii=False, indent=1) + "\n"}
    if run.bundle is not None:
        texts["candidate.json"] = run.bundle.model_dump_json(indent=1) + "\n"
    plan = {
        name: _digest(texts[name]) if name in texts else None
        for name in ("candidate.json", "review_items.json")
    }
    report = {**run.report, "plan": plan}
    texts["report.json"] = json.dumps(report, ensure_ascii=False, indent=1) + "\n"
    prepared: dict[str, Path] = {}
    try:
        for name, text in texts.items():
            prepared[name] = run_root / f".{name}.prepared"
            prepared[name].write_text(text, encoding="utf-8")
        (run_root / "report.json").unlink(missing_ok=True)  # incomplete from here on
        if run.bundle is None:
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


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    base_url, api_key = os.environ.get(BASE_URL_ENV, ""), os.environ.get(API_KEY_ENV, "")
    if not base_url or not api_key:
        return _emit({"stopped": "CONFIGURATION_MISSING"}, 2)
    try:
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
            _write_plan(args.run_root, run)
            save_registry(run.registry, args.registry)
    except RegistryBusy:
        return _emit({"stopped": "REGISTRY_BUSY"}, 3)
    except (RegistryError, AdmissionError, PlatformError, SourceMapError) as error:
        return _emit({"stopped": error.code}, 2)
    except BundleError as error:
        return _emit({"stopped": "BUNDLE_INVALID", "reason": error.reason}, 2)
    except OSError:
        return _emit({"stopped": "LOCAL_IO_FAILED"}, 2)
    except ValueError:  # a change decision refusing an ambiguous Active release
        return _emit({"stopped": "BUNDLE_INVALID", "reason": "CONVERSION_FAILED"}, 2)
    return _emit(_summary(run))


def _emit(summary: dict[str, Any], status: int = 0) -> int:
    print(json.dumps(summary, ensure_ascii=False))
    return status


if __name__ == "__main__":
    sys.exit(main())
