"""Local plans, seed selection and atomic output receipts for registry publication.

The registry remains the source authority; receipts only remember output bytes submitted
successfully, never a serving Head. Callers hold the registry lock while preparing a real run.
"""

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.compilers.schema_fields.cards import cards_version
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.ingest.registry import ProductEntry, ProductRegistry


class PublicationError(ValueError):
    """A fixed caller-safe code; no input content or filesystem diagnostics."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PublicationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compile: list[str]
    publish: list[str]


class PublicationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    planned_compile: list[str] = Field(default_factory=list)
    planned_publish: list[str] = Field(default_factory=list)
    compiled: list[str] = Field(default_factory=list)
    reused: list[str] = Field(default_factory=list)
    reviewed: list[str] = Field(default_factory=list)
    routes: dict[str, Literal["machine", "human", "unchanged"]] = Field(default_factory=dict)
    failed: dict[str, str] = Field(default_factory=dict)
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


def _published(run_root: Path) -> dict[str, str]:
    try:
        data = (run_root / "published.json").read_bytes()
    except FileNotFoundError:
        return {}
    except OSError:
        raise PublicationError("PUBLICATION_IO_ERROR") from None
    try:
        document = json.loads(data)
    except (ValueError, UnicodeError):
        raise PublicationError("PUBLISHED_INVALID") from None
    if not isinstance(document, dict) or not all(
        isinstance(product, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", product)
        and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
        for product, digest in document.items()
    ):
        raise PublicationError("PUBLISHED_INVALID")
    return document


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
