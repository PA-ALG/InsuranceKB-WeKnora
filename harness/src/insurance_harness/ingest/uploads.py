"""Find a Space's new uploads, attribute them and record the result (S5b-2 Spec §2.3, §2.5).

`attribute_uploads` is a pure step from one registry and one RAW listing to the next registry: it
judges every new material with the S5b-1 core and applies what it can apply automatically, while
the rest waits in `pending`. A run judges in rounds until nothing changes, so terms, brochure and
rate table uploaded together land in one run whatever the listing order. Materials waiting for a
person are not judged again; quarantined ones are, every run.

    python -m insurance_harness.ingest.uploads seed --registry PATH --space ID --raw-kb ID \\
        --source-map PATH [--source-map PATH ...] [--dry-run]
    python -m insurance_harness.ingest.uploads run --registry PATH [--dry-run]
    python -m insurance_harness.ingest.uploads confirm --registry PATH [--dry-run]
    python -m insurance_harness.ingest.uploads publish --registry PATH --run-root DIR \\
        --stage-config PATH [--dry-run]
    python -m insurance_harness.ingest.uploads migrate-registry --registry PATH \\
        --manifest-dir DIR --manifest-commit SHA [--refresh] [--dry-run]
    python -m insurance_harness.ingest.uploads detach --registry PATH --knowledge-id ID \\
        --reason {wrong_version,wrong_product,not_product_material} [--dry-run]
    python -m insurance_harness.ingest.uploads relabel --registry PATH --knowledge-id ID [--dry-run]

`confirm` pushes the materials waiting for a person to the platform and applies their answers
(S5b-3c-2), and on a v2 registry the scope-label questions too (SK-1 §4); it shares the registry
lock with the other commands. `migrate-registry` turns a v1 registry into v2 (or refreshes the
version fields) from a pinned product repository checkout (PV-1 Spec §4); it reads no platform. A
`run` on a v2 registry reads the catalog it names. `detach` takes a wrongly attributed material off
its entry (PV-3 Spec §4); `relabel` has a person correct a method material's labels at the next
`confirm` (SK-1 §4.5).
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

from insurance_harness.bundle.client import PlatformClient, PlatformError
from insurance_harness.catalog.sales_taxonomy import SalesTaxonomyError
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.eval.product_sources import declared_pack, display_name, source_directory
from insurance_harness.evidence.weknora_pages import SourcePagesError, WeKnoraSourcePages
from insurance_harness.identity.attribution import (
    Attribution,
    AttributionInputError,
    AttributionPolicy,
    Upload,
    attribute,
    load_attribution_policy,
)
from insurance_harness.ingest.confirmations import ConfirmationsError, sync
from insurance_harness.ingest.detach import REASONS, DetachError, detach
from insurance_harness.ingest.method_confirmations import request_relabel, sync_methods
from insurance_harness.ingest.method_uses import MethodStep, expire_method_uses
from insurance_harness.ingest.publication import PublicationError, run_publication
from insurance_harness.ingest.raw_sources import (
    RawSource,
    RawSources,
    RawSourcesError,
    UnfinishedSource,
    head_text,
    material_pages,
)
from insurance_harness.ingest.registry import (
    FINAL,
    V2,
    WAITING,
    PendingEntry,
    ProductRegistry,
    RegistryError,
    SeedProduct,
    load_registry,
    record,
    save_registry,
    seed_registry,
)
from insurance_harness.ingest.registry_lock import RegistryBusy, RegistryLock
from insurance_harness.ingest.registry_migration import MigrationError, migrate_registry
from insurance_harness.ingest.source_map import (
    API_KEY_ENV,
    BASE_URL_ENV,
    PageReader,
    SourceMapError,
    load_source_map,
)
from insurance_harness.ingest.version_catalog import (
    CatalogError,
    VersionCatalog,
    catalog_from_checkout,
    load_catalog,
)
from insurance_harness.ingest.withdrawn_questions import read_question_states


class UnreadableMaterial(BaseModel):
    """Why a listed material's pages could not be read: the typed code only (S11f Spec §2.2)."""

    model_config = ConfigDict(extra="forbid")
    knowledge_id: str
    file_name: str
    code: str
    reason: str | None = None
    page: int | None = None  # the first scanned page of a scanned PDF


class UploadReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    counts: dict[str, int]
    affected_products: list[str]
    pending: int
    unreadable: list[str]
    revision_changes: list[str]  # recorded materials listed with another attempt or SHA (S8)
    not_listed: list[str]  # registered materials missing from the completed listing (S8)
    unreadable_reasons: list[UnreadableMaterial] = []  # `unreadable`, each with its reason (S11f)
    unfinished: list[UnfinishedSource] = []  # listed materials whose parse has not completed (S11f)
    withdrawn_rejudged: list[str] = []  # older questions judged again: their item withdrawn (S5b-9)
    question_state_unknown: list[str] = []  # older questions kept: items unreadable (S5b-9)


class UploadRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registry: ProductRegistry
    report: UploadReport


def _candidates(
    registry: ProductRegistry, sources: Sequence[RawSource], policy_ref: str
) -> list[RawSource]:
    """New materials, plus quarantined ones, plus questions asked under an older policy.

    Never one a person has to decide under the current policy (by knowledge id, whatever its parse
    attempt), one already registered or replaced by a new version, or one with a final decision on
    record. A material whose person decision is being carried out (it has a settlement) is not
    judged again: judging would replace its pending entry and lose the settlement (S11a Spec §2.3).
    A question asked under an older policy is judged again (S5b-7 Spec §2.4): a better policy may
    settle it, and a question it still raises is left as asked.
    """
    settled = {
        m.knowledge_id for p in registry.products.values() for m in (*p.materials, *p.retired)
    }
    settled |= {
        p.knowledge_id
        for p in registry.pending
        if p.settlement is not None
        or (p.attribution.outcome == "NEEDS_CONFIRM" and p.attribution.policy_ref == policy_ref)
    }
    settled |= {d.knowledge_id for d in registry.decisions if d.attribution.outcome in FINAL}
    # A material detached without a product entry (a method material, SK-1 §3.4) ends here too;
    # one whose method answer is being carried out is not judged again either (SK-1 §4.3).
    settled |= {d.knowledge_id for d in registry.decisions if d.attribution.outcome == "DETACHED"}
    settled |= {u.knowledge_id for u in registry.method_uses if u.settlement is not None}
    return sorted(
        (s for s in sources if s.knowledge_id not in settled), key=lambda s: s.knowledge_id
    )


def _changes(
    registry: ProductRegistry, sources: Sequence[RawSource]
) -> tuple[list[str], list[str]]:
    """Recorded materials whose listed revision differs, and registered ones not listed."""
    recorded = {
        m.knowledge_id: (m.parse_attempt, m.sha256)
        for p in registry.products.values()
        for m in (*p.materials, *p.retired)
    }
    recorded |= {
        p.knowledge_id: (p.parse_attempt, p.sha256)
        for p in registry.pending
        if p.attribution.outcome == "NEEDS_CONFIRM" or p.settlement is not None
    }
    listed = {s.knowledge_id: (s.parse_attempt, s.sha256) for s in sources}
    changed = sorted(
        k for k, revision in listed.items() if k in recorded and recorded[k] != revision
    )
    owned = {m.knowledge_id for p in registry.products.values() for m in p.materials}
    return changed, sorted(owned - set(listed))


def _same_question(before: PendingEntry | None, source: RawSource, after: Attribution) -> bool:
    """The same material revision and the same conclusion under another policy version: the
    question asked stays (S5b-7 Spec §2.4). A new revision is recorded as before."""
    return (
        before is not None
        and (before.parse_attempt, before.sha256) == (source.parse_attempt, source.sha256)
        and before.attribution.model_dump(exclude={"policy_ref"})
        == after.model_dump(exclude={"policy_ref"})
    )


def attribute_uploads(
    registry: ProductRegistry,
    sources: Sequence[RawSource],
    pages: PageReader,
    policy: AttributionPolicy | None = None,
    unfinished: Sequence[UnfinishedSource] = (),
    catalog: VersionCatalog | None = None,
    withdrawn: frozenset[str] = frozenset(),
    unknown: frozenset[str] = frozenset(),
) -> UploadRun:
    """The next registry and a report; the given registry is not modified.

    `unfinished` is passed through to the report: the listed materials that cannot be judged yet.
    `catalog` is the pinned version catalog a v2 registry names (PV-1 Spec §3).
    `withdrawn` names older questions whose item was withdrawn: judged again rather than kept as
    asked; `unknown` names those whose items could not be read: they take no part in the run, not
    even through an automatic result, and stay exactly as asked (S5b-9 Spec §2).
    """
    current = registry.model_copy(deep=True)
    policy = policy or load_attribution_policy()
    asked = {p.knowledge_id for p in current.pending if p.attribution.outcome == "NEEDS_CONFIRM"}
    previous = {p.knowledge_id: p for p in current.pending}
    heads: dict[str, str] = {}
    read: dict[str, list[PageText]] = {}  # every page, read once: the head and method blocks
    unreadable: list[UnreadableMaterial] = []
    if current.contract == V2:
        expire_method_uses(current, sources, unfinished)  # before a new revision is recorded
    methods = MethodStep(current, read, policy)
    kept = {p.knowledge_id for p in current.pending if p.knowledge_id in unknown}
    candidates = [
        s for s in _candidates(current, sources, policy.policy_ref) if s.knowledge_id not in kept
    ]
    for source in candidates:
        try:
            read[source.knowledge_id] = material_pages(pages, current.space_id, source)
            heads[source.knowledge_id] = head_text(read[source.knowledge_id])
        except SourcePagesError as error:
            unreadable.append(UnreadableMaterial(
                knowledge_id=source.knowledge_id, file_name=source.file_name, code=error.code,
                reason=error.reason, page=error.page,
            ))
    remaining = [s for s in candidates if s.knowledge_id in heads]
    counts: Counter[str] = Counter()
    affected: set[str] = set()
    rejudged: set[str] = set()
    while remaining:
        deferred: list[tuple[RawSource, Attribution]] = []
        held: list[RawSource] = []  # asked under an older policy and still a question
        changed = False
        for source in remaining:
            upload = Upload(
                knowledge_id=source.knowledge_id,
                file_name=source.file_name,
                sha256=source.sha256,
                head=heads[source.knowledge_id],
            )
            attribution = attribute(upload, current.registered(), policy, catalog=catalog)
            if source.knowledge_id in asked and source.knowledge_id in withdrawn:
                rejudged.add(source.knowledge_id)  # its item was withdrawn (S5b-9 Spec §2.1)
            elif source.knowledge_id in asked and attribution.outcome in WAITING:
                methods.record(source, attribution)  # beside the question as it was asked
                held.append(source)  # the person's question stays as it was asked
                continue
            if attribution.outcome == "QUARANTINE":
                deferred.append((source, attribution))  # its terms may arrive in this run
                continue
            counts[attribution.outcome] += 1
            if record(current, source, attribution, catalog=catalog):
                changed = True
                affected.add(attribution.product_id or "")
            methods.record(source, attribution)  # a second use beside the product one (SK-1)
        if not changed:
            for source, attribution in deferred:
                attribution = methods.conclude(source, attribution)  # METHOD_MATERIAL (SK-1)
                counts[attribution.outcome] += 1
                if source.knowledge_id in withdrawn or not _same_question(
                    previous.get(source.knowledge_id), source, attribution
                ):
                    record(current, source, attribution, catalog=catalog)
                methods.record(source, attribution)
            break
        remaining = [*(source for source, _ in deferred), *held]
    methods.backfill(sources, pages)  # registered sales materials (SK-1 §3.1)
    revision_changes, not_listed = _changes(current, sources)
    report = UploadReport(
        counts=dict(sorted(counts.items())),
        affected_products=sorted(affected),
        pending=len(current.pending),
        unreadable=sorted(m.knowledge_id for m in unreadable),
        revision_changes=revision_changes,
        not_listed=not_listed,
        unreadable_reasons=sorted(unreadable, key=lambda m: m.knowledge_id),
        unfinished=sorted(unfinished, key=lambda u: u.knowledge_id),
        withdrawn_rejudged=sorted(rejudged),
        question_state_unknown=sorted(kept),
    )
    return UploadRun(registry=current, report=report)


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
    confirm = commands.add_parser("confirm")
    confirm.add_argument("--registry", type=Path, required=True)
    confirm.add_argument("--dry-run", action="store_true")
    publication = commands.add_parser("publish")
    publication.add_argument("--registry", type=Path, required=True)
    publication.add_argument("--run-root", type=Path, required=True)
    publication.add_argument("--stage-config", type=Path, required=True)
    publication.add_argument("--compile-max-sent", type=int, default=30)
    publication.add_argument("--review-max-sent", type=int, default=10)
    publication.add_argument("--products", nargs="+")
    publication.add_argument("--seed-from", type=Path, action="append", default=[])
    publication.add_argument("--dry-run", action="store_true")
    migration = commands.add_parser("migrate-registry")
    migration.add_argument("--registry", type=Path, required=True)
    migration.add_argument("--manifest-dir", type=Path, required=True)
    migration.add_argument("--manifest-commit", required=True)
    migration.add_argument("--refresh", action="store_true")
    migration.add_argument("--dry-run", action="store_true")
    for name in ("detach", "relabel"):  # one change to a v2 registry under its lock
        change = commands.add_parser(name)
        change.add_argument("--registry", type=Path, required=True)
        change.add_argument("--knowledge-id", required=True)
        change.add_argument("--dry-run", action="store_true")
    commands.choices["detach"].add_argument("--reason", choices=REASONS, required=True)
    args = parser.parse_args(argv)
    if args.command == "migrate-registry":
        return _migrate(args)
    if args.command in {"detach", "relabel"}:
        return _change(args)
    base_url, api_key = os.environ.get(BASE_URL_ENV, ""), os.environ.get(API_KEY_ENV, "")
    if not base_url or not api_key:
        print("CONFIGURATION_MISSING", file=sys.stderr)
        return 2
    try:
        with RegistryLock(args.registry):
            if args.command == "publish":
                report = run_publication(
                    args.registry, args.run_root,
                    client=PlatformClient(base_url, api_key, transport=transport),
                    stage_config=args.stage_config, compile_max_sent=args.compile_max_sent,
                    review_max_sent=args.review_max_sent, products=args.products,
                    seed_from=args.seed_from, dry_run=args.dry_run,
                )
                print(report.model_dump_json())
                return 1 if any((report.stopped, report.review_stopped, report.failed,
                                 report.samples_failed)) else 0
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
            if args.command == "confirm":
                client = PlatformClient(base_url, api_key, transport=transport)
                save = lambda current: save_registry(current, args.registry)  # noqa: E731
                confirmed = sync(registry, client, pages, write=not args.dry_run, save=save)
                if registry.contract != V2:
                    print(confirmed.report.model_dump_json())
                    return 0
                methods = sync_methods(  # the method-scope questions (SK-1 §4)
                    confirmed.registry, client, write=not args.dry_run, save=save
                )
                merged = confirmed.report.model_dump(mode="json")
                print(json.dumps(merged | {"methods": methods.report.model_dump(mode="json")}))
                return 0
            listed = listing.listing(registry.raw_kb_id)
            basis = registry.metadata_basis
            catalog = (
                load_catalog(
                    args.registry,
                    basis.catalog_sha256,
                    repository=basis.repository,
                    commit=basis.commit,
                )
                if registry.contract == V2 and basis is not None
                else None
            )
            states = read_question_states(
                PlatformClient(base_url, api_key, transport=transport),
                registry,
                load_attribution_policy().policy_ref,
            )
            result = attribute_uploads(
                registry, listed.completed, pages, unfinished=listed.unfinished, catalog=catalog,
                withdrawn=states.withdrawn, unknown=states.unknown,
            )
            if not args.dry_run and result.registry != registry:
                save_registry(result.registry, args.registry)
            print(result.report.model_dump_json())
            return 0
    except RegistryBusy:
        print("REGISTRY_BUSY", file=sys.stderr)
        return 3
    except (
        RegistryError,
        RawSourcesError,
        SourcePagesError,
        SourceMapError,
        AttributionInputError,
        PlatformError,
        ConfirmationsError,
        PublicationError,
        CatalogError,
        SalesTaxonomyError,
    ) as error:
        print(error.code, file=sys.stderr)
        return 1
    except OSError:  # lock or registry file; the message would carry the path
        print("REGISTRY_IO_ERROR", file=sys.stderr)
        return 1


def _migrate(args: argparse.Namespace) -> int:
    """`migrate-registry`: the registry lock, the pinned catalog, then the journaled migration."""
    try:
        with RegistryLock(args.registry):
            catalog = catalog_from_checkout(args.manifest_dir, args.manifest_commit)
            report = migrate_registry(
                args.registry, catalog, refresh=args.refresh, dry_run=args.dry_run
            )
    except RegistryBusy:
        print("REGISTRY_BUSY", file=sys.stderr)
        return 3
    except (CatalogError, MigrationError, RegistryError) as error:
        print(error.code, file=sys.stderr)
        return 1
    except OSError:
        print("REGISTRY_IO_ERROR", file=sys.stderr)
        return 1
    print(report.model_dump_json())
    return 0


def _change(args: argparse.Namespace) -> int:
    """`detach` (PV-3 Spec §4) or `relabel` (SK-1 §4.5): the registry lock, then the change."""
    try:
        with RegistryLock(args.registry):
            registry = load_registry(args.registry)
            changed = (request_relabel(registry, args.knowledge_id) if args.command == "relabel"
                       else detach(registry, args.knowledge_id, args.reason))
            if not args.dry_run:
                save_registry(changed, args.registry)
    except RegistryBusy:
        print("REGISTRY_BUSY", file=sys.stderr)
        return 3
    except (DetachError, ConfirmationsError, RegistryError) as error:
        print(error.code, file=sys.stderr)
        return 1
    except OSError:
        print("REGISTRY_IO_ERROR", file=sys.stderr)
        return 1
    done = "detached" if args.command == "detach" else "relabel"
    print(json.dumps({done: args.knowledge_id, "dry_run": args.dry_run}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
