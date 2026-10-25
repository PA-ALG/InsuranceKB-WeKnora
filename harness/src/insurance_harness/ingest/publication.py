"""Plan, compile, score and publish registry products through the existing commands.

The registry remains the source authority; receipts only remember output bytes submitted
successfully, never a serving Head. Callers hold the registry lock while preparing a real run.
After publication but before its receipt is saved, interruption means retrying next round:
Active content is reconciled through the change probe; a pending human candidate may be
submitted again and must be reconciled against its release baseline in the human queue.
"""

import hashlib
import io
import json
import os
import re
import tempfile
from collections.abc import Callable, Sequence
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from insurance_harness.bundle.client import PlatformClient, PlatformError
from insurance_harness.compilers.schema_fields import publish, publish_changes
from insurance_harness.compilers.schema_fields.cards import cards_version
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.eval import compile_run, review_run
from insurance_harness.ingest.registry import ProductEntry, ProductRegistry, load_registry
from insurance_harness.models.durable import RunRootBusy, prior_sends, run_lock


class PublicationError(ValueError):
    """A fixed caller-safe code; no input content or filesystem diagnostics."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PublicationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compile: list[str]
    publish: list[str]


class SampleFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_id: str
    stopped: str


class PublicationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    planned_compile: list[str] = Field(default_factory=list)
    planned_publish: list[str] = Field(default_factory=list)
    compiled: list[str] = Field(default_factory=list)
    reused: list[str] = Field(default_factory=list)
    reviewed: list[str] = Field(default_factory=list)
    routes: dict[str, Literal["machine", "human", "unchanged"]] = Field(default_factory=dict)
    failed: dict[str, str] = Field(default_factory=dict)
    samples_failed: dict[str, SampleFailure] = Field(default_factory=dict)
    stopped: str | None = None
    review_stopped: str | None = None
    compile_sent: int = 0
    review_sent: int = 0


def _selected(registry: ProductRegistry, products: Sequence[str] | None) -> list[str]:
    selected = sorted(set(registry.products if products is None else products))
    for product in selected:
        registry.facts(product)  # Preflight every id before constructing paths or copying seeds.
    return selected


def _read_output(path: Path) -> tuple[bytes, CompileOutput] | None:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        raise PublicationError("PUBLICATION_IO_ERROR") from None
    try:
        return data, CompileOutput.model_validate_json(data)
    except ValueError:
        raise PublicationError("OUTPUT_INVALID") from None


def _current(output: CompileOutput, entry: ProductEntry, version: str) -> bool:
    materials = sorted(f"{m.knowledge_id}:{m.parse_attempt}:{m.sha256}" for m in entry.materials)
    return output.materials == materials and output.cards_version == version


def _receipts(path: Path, invalid_code: str) -> dict[str, str]:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError:
        raise PublicationError("PUBLICATION_IO_ERROR") from None
    try:
        document = json.loads(data)
    except (ValueError, UnicodeError):
        raise PublicationError(invalid_code) from None
    if not isinstance(document, dict) or not all(
        isinstance(product, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", product)
        and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
        for product, digest in document.items()
    ):
        raise PublicationError(invalid_code)
    return document


def _published(run_root: Path) -> dict[str, str]:
    return _receipts(run_root / "published.json", "PUBLISHED_INVALID")


def _plan(
    registry: ProductRegistry, run_root: Path, products: Sequence[str],
    seeds: dict[str, tuple[bytes, CompileOutput]],
) -> PublicationPlan:
    receipts, version = _published(run_root), cards_version()
    compile_products, publish_products = [], []
    for product in products:
        stored = seeds.get(product) or _read_output(run_root / "compile" / product / "output.json")
        if stored is None or not _current(stored[1], registry.products[product], version):
            compile_products.append(product)
            publish_products.append(product)
        elif hashlib.sha256(stored[0]).hexdigest() != receipts.get(product):
            publish_products.append(product)
    return PublicationPlan(compile=compile_products, publish=publish_products)


def plan(
    registry: ProductRegistry, run_root: Path, products: Sequence[str] | None = None,
) -> PublicationPlan:
    """Plan from local output bytes and registry revisions; never write or contact a service."""
    return _plan(registry, run_root, _selected(registry, products), {})


def _seeds(
    registry: ProductRegistry, run_root: Path, products: Sequence[str], roots: Sequence[Path],
) -> dict[str, tuple[bytes, CompileOutput]]:
    seeds: dict[str, tuple[bytes, CompileOutput]] = {}
    version = cards_version()
    for product in products:
        if (run_root / "compile" / product / "output.json").exists():
            continue
        for root in roots:
            try:
                stored = _read_output(root / product / "output.json")
            except PublicationError:
                continue  # An unreadable or invalid seed is not a reusable output.
            if stored is None:
                continue
            output, entry = stored[1], registry.products[product]
            if (output.entity_id == product and output.pack_id == entry.schema_pack_id
                    and _current(output, entry, version)):
                seeds[product] = stored
                break
    return seeds


def _replace(path: Path, data: bytes) -> None:
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        raise PublicationError("PUBLICATION_IO_ERROR") from None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                raise PublicationError("PUBLICATION_IO_ERROR") from None


def _save_published(run_root: Path, receipts: dict[str, str]) -> None:
    _replace(run_root / "published.json", (json.dumps(receipts, sort_keys=True) + "\n").encode())


def _prepare(
    registry: ProductRegistry, run_root: Path, products: Sequence[str] | None,
    seed_from: Sequence[Path], *, dry_run: bool,
) -> PublicationPlan:
    selected = _selected(registry, products)
    seeds = _seeds(registry, run_root, selected, seed_from)
    planned = _plan(registry, run_root, selected, seeds)
    if not dry_run:
        for product, (data, _) in seeds.items():
            _replace(run_root / "compile" / product / "output.json", data)
    return planned


def _invoke(
    command: Callable[[list[str]], int], argv: list[str],
) -> tuple[int, dict[str, Any]]:
    captured = io.StringIO()
    with redirect_stdout(captured):
        status = command(argv)
    try:
        result = json.loads(captured.getvalue())
    except ValueError:
        raise PublicationError("COMMAND_OUTPUT_INVALID") from None
    if not isinstance(result, dict):
        raise PublicationError("COMMAND_OUTPUT_INVALID")
    return status, result


def _reason(summary: dict[str, Any]) -> str:
    # These commands already own caller-safe stop diagnostics; keep their actual spelling.
    reason = summary.get("stopped")
    if not isinstance(reason, str) or not reason:
        raise PublicationError("COMMAND_OUTPUT_INVALID")
    return reason


def _budgeted(
    command: Callable[[list[str]], int], argv: list[str], root: Path, allowance: int,
) -> tuple[int, dict[str, Any], int]:
    try:
        before = prior_sends(root)
        status, summary = _invoke(command, [*argv, "--max-sent", str(before + allowance)])
        spent = prior_sends(root) - before
    except (OSError, ValueError) as error:
        if isinstance(error, PublicationError):
            raise
        raise PublicationError("RUN_ROOT_INVALID") from None
    if spent < 0:
        raise PublicationError("RUN_ROOT_INVALID")
    return status, summary, spent


def _returned(products: list[str], requested: Sequence[str]) -> None:
    if len(set(products)) != len(products) or not set(products).issubset(requested):
        raise PublicationError("COMMAND_OUTPUT_INVALID")


def _compile(
    report: PublicationReport, registry_path: Path, run_root: Path,
    stage_config: Path, allowance: int,
) -> None:
    try:
        status, summary, report.compile_sent = _budgeted(compile_run.main, [
            "--registry", str(registry_path), "--products", *report.planned_compile,
            "--stage", "schema_fields", "--stage-config", str(stage_config),
            "--run-root", str(run_root / "compile"),
        ], run_root / "compile", allowance)
        runs = TypeAdapter(list[compile_run.ProductRun]).validate_python(
            summary.get("products", []),
        )
        _returned([run.product_id for run in runs], report.planned_compile)
        report.compiled = [run.product_id for run in runs if not run.reused]
        report.reused = sorted({*report.reused, *(run.product_id for run in runs if run.reused)})
        if status:
            report.stopped = _reason(summary)
    except PublicationError as error:
        report.stopped = error.code
    except ValidationError:
        report.stopped = "COMMAND_OUTPUT_INVALID"


def _digest(run_root: Path, product: str) -> str:
    stored = _read_output(run_root / "compile" / product / "output.json")
    if stored is None:
        raise PublicationError("OUTPUT_MISSING")
    return hashlib.sha256(stored[0]).hexdigest()


def _review(
    report: PublicationReport, snapshots: dict[str, str], scored: dict[str, str],
    run_root: Path, stage_config: Path, allowance: int,
) -> None:
    try:
        status, summary, report.review_sent = _budgeted(review_run.main, [
            "--products", *snapshots, "--compile-root", str(run_root / "compile"),
            "--stage", "review", "--stage-config", str(stage_config),
            "--run-root", str(run_root / "review"),
        ], run_root / "review", allowance)
        if status:
            report.review_stopped = _reason(summary)
            return  # A partial scores file is not a successful summary or a new binding.
        reviews = TypeAdapter(list[review_run.ProductReview]).validate_python(
            summary.get("products"),
        )
        products = [review.product for review in reviews]
        _returned(products, list(snapshots))
        updated = {**scored, **{product: snapshots[product] for product in products}}
        _replace(run_root / "scored.json", (json.dumps(updated, sort_keys=True) + "\n").encode())
        scored.update(updated)
        report.reviewed = products
    except PublicationError as error:
        report.review_stopped = error.code
    except ValidationError:
        report.review_stopped = "COMMAND_OUTPUT_INVALID"


def _record(run_root: Path, receipts: dict[str, str], product: str, digest: str) -> None:
    _save_published(run_root, {**receipts, product: digest})
    receipts[product] = digest  # Never leak an unsuccessful write into the next product's receipt.


def _route(summary: dict[str, Any]) -> Literal["machine", "human", "unchanged"]:
    if summary.get("no_changes") is True:
        return "unchanged"
    if summary.get("review") == "machine":
        return "machine"
    if summary.get("review") == "human":
        return "human"
    raise PublicationError("COMMAND_OUTPUT_INVALID")


def run_publication(
    registry_path: Path, run_root: Path, *, client: PlatformClient, stage_config: Path,
    compile_max_sent: int = 30, review_max_sent: int = 10, dry_run: bool = False,
    products: Sequence[str] | None = None, seed_from: Sequence[Path] = (),
) -> PublicationReport:
    """Hold the run root through the report; callers separately hold the registry lock."""
    with ExitStack() as locks:
        if not dry_run:
            # Convert only acquisition errors, never registry or execution ValueErrors.
            try:
                locks.enter_context(run_lock(run_root))
            except RunRootBusy:
                raise PublicationError("RUN_ROOT_BUSY") from None
            except (ValueError, OSError):
                raise PublicationError("RUN_ROOT_INVALID") from None
        return _run_publication(
            registry_path, run_root, client=client, stage_config=stage_config,
            compile_max_sent=compile_max_sent, review_max_sent=review_max_sent,
            dry_run=dry_run, products=products, seed_from=seed_from,
        )


def _run_publication(
    registry_path: Path, run_root: Path, *, client: PlatformClient, stage_config: Path,
    compile_max_sent: int, review_max_sent: int, dry_run: bool,
    products: Sequence[str] | None, seed_from: Sequence[Path],
) -> PublicationReport:
    if compile_max_sent < 0 or review_max_sent < 0:
        raise PublicationError("INVALID_ARGUMENTS")
    registry = load_registry(registry_path)
    planned = _prepare(registry, run_root, products, seed_from, dry_run=dry_run)
    report = PublicationReport(planned_compile=planned.compile, planned_publish=planned.publish)
    if dry_run:
        return report
    report.reused = [p for p in _selected(registry, products) if p not in planned.compile]
    if planned.compile:
        _compile(report, registry_path, run_root, stage_config, compile_max_sent)
    if report.stopped or not planned.publish:
        return report
    receipts = _published(run_root)
    try:
        active = client.active(registry.space_id)
    except PlatformError as error:
        report.failed = dict.fromkeys(planned.publish, error.code)
        return report
    existing = {
        member.payload["subject_ref"] for member in active.members
        if member.kind == "claim" and isinstance(member.payload, dict)
        and isinstance(member.payload.get("subject_ref"), str)
    } if active else set()
    arguments = {p: ["--run-root", str(run_root / "compile"), "--product", p,
                     "--registry", str(registry_path), "--route"] for p in planned.publish}
    for product in planned.publish:
        if product not in existing:
            continue
        try:
            digest = _digest(run_root, product)
            status, summary = _invoke(publish_changes.main, [*arguments[product], "--dry-run"])
            if status:
                report.failed[product] = _reason(summary)
            elif type(summary.get("no_changes")) is not bool:
                raise PublicationError("COMMAND_OUTPUT_INVALID")
            elif summary["no_changes"]:
                _record(run_root, receipts, product, digest)
                report.routes[product] = "unchanged"
        except PublicationError as error:
            report.failed[product] = error.code
    remaining = [p for p in planned.publish if p not in report.routes and p not in report.failed]
    if not remaining:
        return report
    scored = _receipts(run_root / "scored.json", "SCORED_INVALID")
    snapshots = {}
    for product in remaining:
        try:
            digest = _digest(run_root, product)
            if scored.get(product) != digest:
                snapshots[product] = digest
        except PublicationError as error:
            report.failed[product] = error.code
    if snapshots:
        _review(report, snapshots, scored, run_root, stage_config, review_max_sent)
    for product in remaining:
        if product in report.failed:
            continue
        try:
            digest = _digest(run_root, product)
            scores = run_root / "review" / product / "scores.json"
            argv = arguments[product]
            if scored.get(product) == digest and scores.is_file():
                argv = [*argv, "--scores", str(scores)]
            command = publish_changes.main if product in existing else publish.main
            status, summary = _invoke(command, argv)
            if status:
                report.failed[product] = _reason(summary)
                continue
            route = _route(summary)
            _record(run_root, receipts, product, digest)
            report.routes[product] = route
            samples = summary.get("samples")
            if route == "machine" and isinstance(samples, dict) and "stopped" in samples:
                report.samples_failed[product] = SampleFailure(
                    release_id=summary["release_id"], stopped=samples["stopped"],
                )
        except PublicationError as error:
            report.failed[product] = error.code
    return report
