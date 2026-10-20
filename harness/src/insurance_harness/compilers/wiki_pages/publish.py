"""Publish one product's native Wiki pages as wiki_page members (S6c Spec §3.3).

    python -m insurance_harness.compilers.wiki_pages.publish --discovery-kb KB --product P \
        --entity-id E --source-map F --model M --decide human --reason TEXT --activate

The pages come from an unmanaged discovery knowledge base holding only this product's materials.
Evidence is located in the product's own source pages in the Space; the candidate holds only
wiki_page members on the active release, removes this product's pages the export no longer has,
and is decided by a person. No model is called. Every failure prints a stable code only.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import NoReturn

from pydantic import ValidationError

from insurance_harness.bundle.assemble import BundleError, assemble
from insurance_harness.bundle.client import (
    DecisionInput,
    PlatformClient,
    PlatformError,
    ReleaseMember,
    publish,
)
from insurance_harness.compilers.wiki_pages.members import (
    GENERATOR,
    link_titles,
    member_slug,
    wiki_page,
)
from insurance_harness.compilers.wiki_pages.native import NativeWikiError, NativeWikiReader
from insurance_harness.eval.product_sources import check_product_id
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.evidence.weknora_pages import SourcePagesError
from insurance_harness.ingest.source_map import (
    API_KEY_ENV,
    BASE_URL_ENV,
    SourceMapError,
    load_source_map,
    load_trusted_pages,
    reader_from_env,
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


def _stop(code: str) -> int:
    print(json.dumps({"stopped": code}, ensure_ascii=False))
    return 2


def _owned(member: ReleaseMember, entity_id: str) -> bool:
    """A page this product's export replaces, by its own identity: never by slug prefix, since an
    entity id may itself contain "/"."""
    payload = member.payload if isinstance(member.payload, dict) else {}
    key, refs = payload.get("page_key"), payload.get("entity_refs")
    return (
        member.kind == "wiki_page"
        and isinstance(key, str)
        and isinstance(refs, list)
        and entity_id in refs
        and member.logical_slug == member_slug(entity_id, key)
    )


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__)
    for name in (
        "--discovery-kb",
        "--product",
        "--entity-id",
        "--source-map",
        "--model",
        "--reason",
    ):
        parser.add_argument(name, required=True)
    parser.add_argument("--decide", required=True, choices=["human"])
    parser.add_argument("--activate", action="store_true")
    try:
        args = parser.parse_args(argv)
        check_product_id(args.product)
        if not args.reason.strip() or not args.entity_id.strip() or not args.model.strip():
            raise ValueError("blank argument")
    except ValueError:
        return _stop("INVALID_ARGUMENTS")
    try:
        source_map = load_source_map(Path(args.source_map))
        pages, sources = load_trusted_pages(
            reader_from_env(), source_map.space_id, source_map.entries(args.product)
        )
        # Wiki evidence uses the evidence pages only: rate-table headers stay a field-only rule.
        source = SegmentedSource(pages.evidence)
        native = NativeWikiReader(os.environ[BASE_URL_ENV], os.environ[API_KEY_ENV]).pages(
            args.discovery_kb
        )
        titles = link_titles(native)
        if not titles:  # a wrong or unfinished discovery base is never a reason to remove pages
            return _stop("NATIVE_WIKI_EMPTY")
        converted = [
            member
            for page in native
            if (
                member := wiki_page(
                    page,
                    entity_id=args.entity_id,
                    titles=titles,
                    source=source,
                    sources=sources,
                    model=args.model,
                )
            )
            is not None
        ]
        client = PlatformClient(os.environ[BASE_URL_ENV], os.environ[API_KEY_ENV])
        active = client.active(source_map.space_id)
        keep = {member_slug(args.entity_id, page.page_key) for page in converted}
        removals = sorted(
            member.logical_slug
            for member in (active.members if active else [])
            if _owned(member, args.entity_id) and member.logical_slug not in keep
        )
        bundle = assemble(
            [],
            compiler_identity=f"harness/wiki_pages@{GENERATOR}",
            base=active.head if active else None,
            removals=removals,
            wiki_pages=converted,
        )
        decision = DecisionInput(outcome="approve", mode="human", reason=args.reason)
        result = publish(
            client, source_map.space_id, bundle, decision=decision, activate=args.activate
        )
    except (NativeWikiError, PlatformError, SourcePagesError, SourceMapError) as error:
        return _stop(error.code)
    except KeyError:
        return _stop("CONFIGURATION_MISSING")
    except BundleError as error:
        return _stop(f"BUNDLE_INVALID:{error.reason}")
    except (ValidationError, ValueError):
        return _stop("BUNDLE_INVALID")
    print(
        json.dumps(
            {
                "product": args.product,
                "pages": len(converted),
                "with_evidence": sum(1 for page in converted if page.evidence),
                "evidence": sum(len(page.evidence) for page in converted),
                "removed": len(removals),
                "candidate_id": result.candidate.id,
                "release_id": result.release.id if result.release else None,
                "epoch": result.release.epoch if result.release else None,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
