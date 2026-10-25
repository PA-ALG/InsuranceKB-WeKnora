"""Find a Space's new uploads, attribute them and record the result (S5b-2 Spec §2.3, §2.5).

`attribute_uploads` is a pure step from one registry and one RAW listing to the next registry: it
judges every new material with the S5b-1 core and applies what it can apply automatically, while
the rest waits in `pending`. A run judges in rounds until nothing changes, so terms, brochure and
rate table uploaded together land in one run whatever the listing order. Materials waiting for a
person are not judged again; quarantined ones are, every run.

    python -m insurance_harness.ingest.uploads seed --registry PATH --space ID --raw-kb ID \\
        --source-map PATH [--source-map PATH ...] [--dry-run]
    python -m insurance_harness.ingest.uploads run --registry PATH [--dry-run]
"""

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict

from insurance_harness.eval.product_sources import declared_pack, display_name, source_directory
from insurance_harness.evidence.weknora_pages import SourcePagesError, WeKnoraSourcePages
from insurance_harness.identity.attribution import (
    Attribution,
    AttributionInputError,
    AttributionPolicy,
    Upload,
    attribute,
)
from insurance_harness.ingest.raw_sources import RawSource, RawSources, RawSourcesError
from insurance_harness.ingest.registry import (
    DecisionEntry,
    MaterialEntry,
    PendingEntry,
    ProductEntry,
    ProductRegistry,
    RegistryError,
    SeedProduct,
    head_of,
    load_registry,
    save_registry,
    seed_registry,
)
from insurance_harness.ingest.source_map import (
    API_KEY_ENV,
    BASE_URL_ENV,
    PageReader,
    SourceMapError,
    load_source_map,
)

_APPLIED = {"SUPPLEMENT", "NEW_VERSION", "CREATE"}
_WAITING = {"NEEDS_CONFIRM", "QUARANTINE"}


class UploadReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    counts: dict[str, int]
    affected_products: list[str]
    pending: int
    unreadable: list[str]


class UploadRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registry: ProductRegistry
    report: UploadReport


def _candidates(registry: ProductRegistry, sources: Sequence[RawSource]) -> list[RawSource]:
    """New materials, plus quarantined ones; never those a person has to decide."""
    owned = {m.knowledge_id for p in registry.products.values() for m in p.materials}
    waiting = {(p.knowledge_id, p.parse_attempt): p.attribution.outcome for p in registry.pending}
    duplicates = {
        (d.knowledge_id, d.parse_attempt)
        for d in registry.decisions
        if d.attribution.outcome == "DUPLICATE"
    }
    return sorted(
        (
            s
            for s in sources
            if s.knowledge_id not in owned
            and waiting.get((s.knowledge_id, s.parse_attempt)) != "NEEDS_CONFIRM"
            and (s.knowledge_id, s.parse_attempt) not in duplicates
        ),
        key=lambda s: s.knowledge_id,
    )


def _apply(registry: ProductRegistry, source: RawSource, attribution: Attribution) -> bool:
    """Record one decision; True when the products changed."""
    previous = next((p for p in registry.pending if p.knowledge_id == source.knowledge_id), None)
    registry.pending = [p for p in registry.pending if p.knowledge_id != source.knowledge_id]
    if attribution.outcome in _WAITING:
        registry.pending.append(
            PendingEntry(
                knowledge_id=source.knowledge_id,
                parse_attempt=source.parse_attempt,
                sha256=source.sha256,
                file_name=source.file_name,
                attribution=attribution,
            )
        )
        registry.pending.sort(key=lambda p: p.knowledge_id)
        if previous is not None and previous.attribution == attribution:
            return False  # judged again, same conclusion: nothing new to record
    registry.decisions.append(
        DecisionEntry(
            knowledge_id=source.knowledge_id,
            parse_attempt=source.parse_attempt,
            sha256=source.sha256,
            attribution=attribution,
        )
    )
    if attribution.outcome not in _APPLIED:
        return False
    if attribution.product_id is None or attribution.role is None:
        raise RegistryError("ATTRIBUTION_INCOMPLETE")
    material = MaterialEntry(
        knowledge_id=source.knowledge_id,
        parse_attempt=source.parse_attempt,
        sha256=source.sha256,
        role=attribution.role,
        file_name=source.file_name,
    )
    if attribution.outcome == "CREATE":
        if not (
            attribution.display_name and attribution.clause_code and attribution.schema_pack_id
        ):
            raise RegistryError("ATTRIBUTION_INCOMPLETE")
        registry.products[attribution.product_id] = ProductEntry(
            names=[attribution.display_name],
            clause_codes=[attribution.clause_code],
            schema_pack_id=attribution.schema_pack_id,
            origin="created",
            materials=[material],
        )
        return True
    product = registry.products[attribution.product_id]
    kept = [m for m in product.materials if m.knowledge_id not in attribution.replaces]
    product.materials = sorted([*kept, material], key=lambda m: m.knowledge_id)
    code = attribution.clause_code
    if attribution.outcome == "NEW_VERSION" and code and code not in product.clause_codes:
        product.clause_codes.append(code)
    return True


def attribute_uploads(
    registry: ProductRegistry,
    sources: Sequence[RawSource],
    pages: PageReader,
    policy: AttributionPolicy | None = None,
) -> UploadRun:
    """The next registry and a report; the given registry is not modified."""
    current = registry.model_copy(deep=True)
    heads: dict[str, str] = {}
    unreadable: list[str] = []
    for source in _candidates(current, sources):
        try:
            heads[source.knowledge_id] = head_of(pages, current.space_id, source)
        except SourcePagesError:
            unreadable.append(source.knowledge_id)
    remaining = [s for s in _candidates(current, sources) if s.knowledge_id in heads]
    counts: Counter[str] = Counter()
    affected: set[str] = set()
    while remaining:
        deferred: list[tuple[RawSource, Attribution]] = []
        changed = False
        for source in remaining:
            upload = Upload(
                knowledge_id=source.knowledge_id,
                file_name=source.file_name,
                sha256=source.sha256,
                head=heads[source.knowledge_id],
            )
            attribution = attribute(upload, current.registered(), policy)
            if attribution.outcome == "QUARANTINE":
                deferred.append((source, attribution))  # its terms may arrive in this run
                continue
            counts[attribution.outcome] += 1
            if _apply(current, source, attribution):
                changed = True
                affected.add(attribution.product_id or "")
        if not changed:
            for source, attribution in deferred:
                counts[attribution.outcome] += 1
                _apply(current, source, attribution)
            break
        remaining = [source for source, _ in deferred]
    report = UploadReport(
        counts=dict(sorted(counts.items())),
        affected_products=sorted(affected),
        pending=len(current.pending),
        unreadable=sorted(unreadable),
    )
    return UploadRun(registry=current, report=report)


class _Busy(Exception):
    pass


class _Lock:
    """One run per registry file: a lock file beside it, taken or refused at once."""

    def __init__(self, registry_path: Path) -> None:
        self.path = registry_path.with_name(registry_path.name + ".lock")

    def __enter__(self) -> "_Lock":
        try:
            os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        except FileExistsError:
            raise _Busy from None
        return self

    def __exit__(self, *_: object) -> None:
        self.path.unlink(missing_ok=True)


def _seed_products(repo: Path, product_ids: Sequence[str]) -> dict[str, SeedProduct]:
    """Canonical names and clause codes from the dataset, packs from the declared data."""
    facts = {}
    try:
        for product_id in product_ids:
            directory = source_directory(repo, product_id)
            meta = json.loads((directory / "product_meta.json").read_text(encoding="utf-8"))
            facts[product_id] = SeedProduct(
                name=display_name(directory),
                clause_code=meta.get("sccode", ""),
                schema_pack_id=declared_pack(repo, product_id),
            )
    except (OSError, ValueError):  # missing folder or facts; ValidationError is a ValueError
        raise RegistryError("SEED_INVALID") from None
    return facts


def main(argv: list[str] | None = None, *, transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    seed = commands.add_parser("seed")
    seed.add_argument("--registry", type=Path, required=True)
    seed.add_argument("--space", required=True)
    seed.add_argument("--raw-kb", required=True)
    seed.add_argument("--source-map", type=Path, action="append", required=True)
    seed.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[4])
    seed.add_argument("--dry-run", action="store_true")
    run = commands.add_parser("run")
    run.add_argument("--registry", type=Path, required=True)
    run.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    base_url, api_key = os.environ.get(BASE_URL_ENV, ""), os.environ.get(API_KEY_ENV, "")
    if not base_url or not api_key:
        print("CONFIGURATION_MISSING", file=sys.stderr)
        return 2
    try:
        with _Lock(args.registry):
            listing = RawSources(base_url, api_key, transport=transport)
            pages = WeKnoraSourcePages(base_url, api_key, transport=transport)
            if args.command == "seed":
                if args.registry.exists():
                    raise RegistryError("REGISTRY_EXISTS")
                maps = [load_source_map(path) for path in args.source_map]
                product_ids = sorted({pid for source_map in maps for pid in source_map.products})
                seeded = seed_registry(
                    args.space,
                    args.raw_kb,
                    maps,
                    listing.completed(args.raw_kb),
                    pages,
                    _seed_products(args.repo, product_ids),
                )
                if not args.dry_run:
                    save_registry(seeded, args.registry)
                summary = {
                    "products": len(seeded.products),
                    "materials": sum(len(p.materials) for p in seeded.products.values()),
                }
                print(json.dumps(summary))
                return 0
            registry = load_registry(args.registry)
            result = attribute_uploads(registry, listing.completed(registry.raw_kb_id), pages)
            if not args.dry_run and result.registry != registry:
                save_registry(result.registry, args.registry)
            print(result.report.model_dump_json())
            return 0
    except _Busy:
        print("REGISTRY_BUSY", file=sys.stderr)
        return 3
    except (
        RegistryError,
        RawSourcesError,
        SourcePagesError,
        SourceMapError,
        AttributionInputError,
    ) as error:
        print(error.code, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
