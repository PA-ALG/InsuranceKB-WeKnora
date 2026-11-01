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

`confirm` pushes the materials waiting for a person to the platform and applies their answers
(S5b-3c-2); it shares the registry lock with the other commands.
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
from insurance_harness.ingest.publication import PublicationError, run_publication
from insurance_harness.ingest.raw_sources import (
    RawSource,
    RawSources,
    RawSourcesError,
    UnfinishedSource,
)
from insurance_harness.ingest.registry import (
    FINAL,
    WAITING,
    ProductRegistry,
    RegistryError,
    SeedProduct,
    head_of,
    load_registry,
    record,
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


def _same_question(before: Attribution | None, after: Attribution) -> bool:
    """The same conclusion under another policy version: the question asked stays (S5b-7 §2.4)."""
    return before is not None and before.model_dump(exclude={"policy_ref"}) == after.model_dump(
        exclude={"policy_ref"}
    )


def attribute_uploads(
    registry: ProductRegistry,
    sources: Sequence[RawSource],
    pages: PageReader,
    policy: AttributionPolicy | None = None,
    unfinished: Sequence[UnfinishedSource] = (),
) -> UploadRun:
    """The next registry and a report; the given registry is not modified.

    `unfinished` is passed through to the report: the listed materials that cannot be judged yet.
    """
    current = registry.model_copy(deep=True)
    policy = policy or load_attribution_policy()
    asked = {p.knowledge_id for p in current.pending if p.attribution.outcome == "NEEDS_CONFIRM"}
    previous = {p.knowledge_id: p.attribution for p in current.pending}
    heads: dict[str, str] = {}
    unreadable: list[UnreadableMaterial] = []
    for source in _candidates(current, sources, policy.policy_ref):
        try:
            heads[source.knowledge_id] = head_of(pages, current.space_id, source)
        except SourcePagesError as error:
            unreadable.append(UnreadableMaterial(
                knowledge_id=source.knowledge_id, file_name=source.file_name, code=error.code,
                reason=error.reason, page=error.page,
            ))
    remaining = [
        s for s in _candidates(current, sources, policy.policy_ref) if s.knowledge_id in heads
    ]
    counts: Counter[str] = Counter()
    affected: set[str] = set()
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
            attribution = attribute(upload, current.registered(), policy)
            if source.knowledge_id in asked and attribution.outcome in WAITING:
                held.append(source)  # the person's question stays as it was asked
                continue
            if attribution.outcome == "QUARANTINE":
                deferred.append((source, attribution))  # its terms may arrive in this run
                continue
            counts[attribution.outcome] += 1
            if record(current, source, attribution):
                changed = True
                affected.add(attribution.product_id or "")
        if not changed:
            for source, attribution in deferred:
                counts[attribution.outcome] += 1
                if not _same_question(previous.get(source.knowledge_id), attribution):
                    record(current, source, attribution)
            break
        remaining = [*(source for source, _ in deferred), *held]
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
    args = parser.parse_args(argv)
    base_url, api_key = os.environ.get(BASE_URL_ENV, ""), os.environ.get(API_KEY_ENV, "")
    if not base_url or not api_key:
        print("CONFIGURATION_MISSING", file=sys.stderr)
        return 2
    try:
        with _Lock(args.registry):
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
                confirmed = sync(
                    registry,
                    PlatformClient(base_url, api_key, transport=transport),
                    pages,
                    write=not args.dry_run,
                    save=lambda current: save_registry(current, args.registry),
                )
                print(confirmed.report.model_dump_json())
                return 0
            listed = listing.listing(registry.raw_kb_id)
            result = attribute_uploads(
                registry, listed.completed, pages, unfinished=listed.unfinished
            )
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
        PlatformError,
        ConfirmationsError,
        PublicationError,
    ) as error:
        print(error.code, file=sys.stderr)
        return 1
    except OSError:  # lock or registry file; the message would carry the path
        print("REGISTRY_IO_ERROR", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
