"""Golden v2 evidence moved onto a new segmentation by page position (S4i Spec §3.4).

usage: python -m insurance_harness.eval.golden_remap --previous <dir> --products <id>...
       --cards-version <v> --basis <text> --emptied-reason <text> [--segmentation <text>]
       [--repo <dir>] [--golden-from <dir>]

Golden quotes carry the segment id they were labelled on. When the segmentation rules change, each
quote is taken by that id in a table exported with the previous rules (one `<product>.json` per
product: the baseline commit, every page's text sha256 and every segment's range) and replaced by
the current segments that overlap its range by a positive length, in reading order, once per field.
Every quote, including those on materials that may no longer be evidence, is first checked against
the current snapshot of all the product's pages: the file fingerprint, the page text, and the old
range's exact slice. Evidence on excluded materials is then removed; a field left without evidence
becomes unknown with the given reason; values and other states are not touched. Any mismatch stops
the run before anything is written, and the output is all or nothing: a failed write restores every
file it replaced. Prints one JSON line, never paths or Golden text.
"""

import argparse
import hashlib
import json
import os
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.catalog.trust_policy import load_trust_policy, trusted_pages
from insurance_harness.eval.product_sources import (
    check_product_id,
    material_pages,
    recorded_roles,
    source_directory,
)
from insurance_harness.eval.segment_score import (
    GOLDEN_DIR,
    GoldenV2,
    GoldenV2Evidence,
    GoldenV2Field,
    load_golden_v2,
)
from insurance_harness.evidence.quote_verification import PageTextLike
from insurance_harness.evidence.segments import Segment, SegmentedSource, header_block, same_text
from insurance_harness.identity.material_roles import (
    MaterialRoleError,
    document_roles,
    load_material_roles,
)

REPO = Path(__file__).resolve().parents[4]
METHOD = "deterministic-remap"


class PreviousSegment(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    id: str
    document: str
    document_sha256: str
    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str


@dataclass(frozen=True)
class PreviousSegmentation:
    pages: Mapping[tuple[str, int], str]  # page text sha256 under the previous rules
    segments: Mapping[str, PreviousSegment]


@dataclass(frozen=True)
class ProductRemap:
    fields: tuple[str, ...]  # fields whose evidence, state, value or reason changed
    excluded_quotes_removed: int
    quotes_split: int  # Golden quotes now spread over more than one segment
    fields_split: tuple[str, ...]  # their fields: labels coarser than the segments until re-judged
    quotes_widened: tuple[tuple[str, str], ...]  # (field, segment) reaching past the old range
    to_unknown: tuple[str, ...]
    cited_excluded: tuple[str, ...]  # fields that cited an excluded material
    restored: tuple[str, ...]  # fields adopting policy-authorized header evidence


class RemapError(ValueError):
    def __init__(self, code: str, product: str | None = None) -> None:
        super().__init__(code)
        self.code, self.product = code, product


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check(
    quote: GoldenV2Evidence,
    previous: PreviousSegmentation,
    snapshot: Mapping[tuple[str, int], PageTextLike],
) -> PreviousSegment:
    """The previous segment a Golden quote was labelled on, proven against the current snapshot."""
    old = previous.segments.get(quote.segment_id or "")
    if old is None:
        raise RemapError("SEGMENT_ID_UNKNOWN")
    place = (old.document, old.document_sha256.lower(), old.page)
    if place != (quote.document, quote.document_sha256.lower(), quote.page) or not (
        same_text(old.text, quote.quote)
    ):
        raise RemapError("QUOTE_MISMATCH")
    page = snapshot.get((old.document, old.page))
    if page is None or page.document_sha256.lower() != old.document_sha256.lower():
        raise RemapError("SOURCE_FINGERPRINT_CHANGED")
    if previous.pages.get((old.document, old.page)) != _sha(page.text):
        raise RemapError("PAGE_TEXT_CHANGED")
    if not old.start < old.end <= len(page.text) or page.text[old.start : old.end] != old.text:
        raise RemapError("SEGMENT_RANGE_INVALID")
    return old


def remap_golden(
    golden: GoldenV2,
    previous: PreviousSegmentation,
    materials: Sequence[PageTextLike],
    *,
    excluded: Collection[str],
    emptied_reason: str,
    table_headers: Mapping[str, Sequence[PageTextLike]] | None = None,
) -> tuple[GoldenV2, ProductRemap]:
    """Remap one product's Golden; materials are all its pages, excluded ones included."""
    snapshot = {(page.document, page.page): page for page in materials}
    if len(snapshot) != len(materials):
        raise RemapError("SOURCE_PAGES_AMBIGUOUS")
    current = SegmentedSource(
        [page for page in materials if page.document not in excluded], table_headers=table_headers
    )
    for page in current.pages:
        original = snapshot.get((page.document, page.page))
        if original is None or original.document_sha256.lower() != page.document_sha256.lower():
            raise RemapError("SOURCE_FINGERPRINT_CHANGED")
        if original.text != page.text:
            raise RemapError("PAGE_TEXT_CHANGED")
    policy = load_trust_policy()
    order = {segment.id: index for index, segment in enumerate(current.segments)}
    on_page: dict[tuple[str, int], list[Segment]] = {}
    for segment in current.segments:
        on_page.setdefault((segment.document, segment.page), []).append(segment)
    fields: list[GoldenV2Field] = []
    changed: list[str] = []
    removed = split = 0
    widened: list[tuple[str, str]] = []
    to_unknown: list[str] = []
    cited: list[str] = []
    split_fields: list[str] = []
    restored: list[str] = []
    for field in golden.fields:
        evidence: dict[str, GoldenV2Evidence] = {}
        for quote in field.evidence:
            old = _check(quote, previous, snapshot)
            role = current.header_role(old.document)
            header = role is not None and field.field_key in policy.header_fields(role)
            key = (old.document, old.page)
            block = header_block(snapshot[key].text) if header else None
            if quote.document in excluded and not (
                block is not None and old.start < block[1] and block[0] < old.end
            ):
                removed += 1
                if field.field_key not in cited:
                    cited.append(field.field_key)
                continue
            hits = [
                s for s in on_page.get(key, [])
                if header or (s.start < old.end and old.start < s.end)
            ]
            if not hits:
                raise RemapError("UNMAPPED")
            if header and field.field_key not in restored:
                restored.append(field.field_key)
            if len(hits) > 1:
                split += 1
                if field.field_key not in split_fields:
                    split_fields.append(field.field_key)
            for segment in hits:
                if (segment.start < old.start or segment.end > old.end) and (
                    (field.field_key, segment.id) not in widened
                ):
                    widened.append((field.field_key, segment.id))
                same = len(hits) == 1 and (segment.start, segment.end) == (old.start, old.end)
                evidence.setdefault(
                    segment.id,
                    quote.model_copy(update={"segment_id": segment.id})
                    if same and not header
                    else GoldenV2Evidence(
                        document=segment.document,
                        document_sha256=segment.document_sha256.lower(),
                        page=segment.page,
                        quote=segment.text,
                        segment_id=segment.id,
                    ),
                )
        kept = tuple(evidence[sid] for sid in sorted(evidence, key=order.__getitem__))
        if field.evidence and not kept:
            item = GoldenV2Field(
                field_key=field.field_key,
                state="unknown",
                value=None,
                reason=emptied_reason,
                evidence=(),
            )
            to_unknown.append(field.field_key)
        else:
            item = GoldenV2Field(
                field_key=field.field_key,
                state=field.state,
                value=field.value,
                reason=field.reason,
                evidence=kept,
            )
        if item != field:
            changed.append(field.field_key)
        fields.append(item)
    remapped = GoldenV2(
        product_id=golden.product_id, cards_version=golden.cards_version, fields=tuple(fields)
    )
    report = ProductRemap(
        fields=tuple(changed),
        excluded_quotes_removed=removed,
        quotes_split=split,
        fields_split=tuple(split_fields),
        quotes_widened=tuple(widened),
        to_unknown=tuple(to_unknown),
        cited_excluded=tuple(cited),
        restored=tuple(restored),
    )
    return remapped, report


def _previous(path: Path) -> tuple[str, PreviousSegmentation]:
    data = json.loads(path.read_text(encoding="utf-8"))
    pages = {(p["document"], p["page"]): p["text_sha256"] for p in data["pages"]}
    segments = {s["id"]: PreviousSegment(**s) for s in data["segments"]}
    return str(data["baseline"]), PreviousSegmentation(pages=pages, segments=segments)


@dataclass(frozen=True)
class _Converted:
    golden: GoldenV2
    report: ProductRemap
    sources: dict[str, str]  # fingerprints of the materials kept as evidence
    excluded: dict[str, str]  # fingerprints of the materials that may not be evidence


def _product(
    repo: Path, product: str, previous: PreviousSegmentation, reason: str,
    cards_version: str, golden_from: Path | None,
) -> _Converted:
    directory = source_directory(repo, product)
    raw = material_pages(directory)
    recorded = recorded_roles(directory, raw)  # S12d: the folder's confirmed roles, if any
    trusted = trusted_pages(raw, recorded)  # an unresolved material stops the remap, as in compile
    evidence = {role.role: role.evidence for role in load_material_roles().roles}
    excluded = {
        doc for doc, role in document_roles(raw, recorded).items() if role and not evidence[role]
    }
    golden = load_golden_v2((golden_from or repo / GOLDEN_DIR) / f"{product}.json")
    remapped, report = remap_golden(
        golden, previous, raw, excluded=excluded, emptied_reason=reason,
        table_headers=trusted.table_headers,
    )
    remapped = GoldenV2(
        product_id=remapped.product_id, cards_version=cards_version, fields=remapped.fields
    )
    fingerprints = {page.document: page.document_sha256 for page in raw}
    return _Converted(
        remapped,
        report,
        {d: sha for d, sha in fingerprints.items() if d not in excluded},
        {d: sha for d, sha in fingerprints.items() if d in excluded},
    )


def _manifest_ok(manifest: Any, products: Sequence[str]) -> bool:
    """The parts of the manifest the remap writes into, present before anything is converted."""
    return (
        isinstance(manifest, dict)
        and isinstance(manifest.get("files"), dict)
        and isinstance(manifest.get("products"), dict)
        and all(isinstance(manifest["products"].get(p), dict) for p in products)
        and isinstance(manifest.get("revisions", []), list)
        and isinstance(manifest.get("pending_semantic_review", {}), dict)
    )


def _commit(texts: Mapping[Path, str]) -> None:
    """Write every file or none: temporaries first, then replace; a failure restores originals."""
    originals = {path: path.read_bytes() if path.exists() else None for path in texts}
    temporaries = {path: path.with_name(path.name + ".remap-tmp") for path in texts}
    replaced: list[Path] = []
    try:
        for path, text in texts.items():
            temporaries[path].write_text(text, encoding="utf-8")
        for path in texts:
            os.replace(temporaries[path], path)
            replaced.append(path)
    except OSError:
        for path in replaced:
            original = originals[path]
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original)
        raise
    finally:
        for temporary in temporaries.values():
            temporary.unlink(missing_ok=True)


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--golden-from", type=Path,
                        help="Read original labels here; keep the destination manifest's history")
    parser.add_argument("--products", nargs="+", required=True)
    parser.add_argument("--cards-version", required=True)
    parser.add_argument("--basis", required=True)
    parser.add_argument("--emptied-reason", required=True)
    parser.add_argument("--segmentation")
    args = parser.parse_args(argv)
    gold = args.repo / GOLDEN_DIR
    results: dict[str, _Converted] = {}
    baselines: set[str] = set()
    product = None
    try:
        manifest = json.loads((gold / "manifest.json").read_text(encoding="utf-8"))
        if not _manifest_ok(manifest, args.products):
            raise RemapError("MANIFEST_INVALID")
        for product in args.products:
            check_product_id(product)
            baseline, previous = _previous(args.previous / f"{product}.json")
            baselines.add(baseline)
            results[product] = _product(
                args.repo, product, previous, args.emptied_reason, args.cards_version,
                args.golden_from,
            )
        product = None
        if len(baselines) != 1 or len(next(iter(baselines))) != 40:
            raise RemapError("BASELINE_INVALID")
    except (RemapError, MaterialRoleError) as error:
        print(json.dumps({"stopped": error.code, **({"product": product} if product else {})}))
        return 2
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"stopped": "INPUT_INVALID", **({"product": product} if product else {})}))
        return 2

    revision: dict[str, Any] = {
        "basis": args.basis,
        "baseline": baselines.pop(),
        "cards_version": args.cards_version,
        "method": METHOD,
        "emptied_reason": args.emptied_reason,
        "products": {},
    }
    pending = manifest.setdefault("pending_semantic_review", {})
    texts: dict[Path, str] = {}
    for name, converted in results.items():
        golden, report = converted.golden, converted.report
        raw = _dump(golden.model_dump(mode="json"))
        texts[gold / f"{name}.json"] = raw
        manifest["files"][f"{name}.json"] = _sha(raw)
        entry = manifest["products"][name]
        entry["states"] = dict(sorted(Counter(field.state for field in golden.fields).items()))
        # Golden is now labelled from the evidence materials only; the others stay on record.
        entry["source_sha256"] = converted.sources
        if converted.excluded:
            entry["non_evidence_sha256"] = converted.excluded
        if report.cited_excluded or report.restored:
            pending[name] = sorted(
                (set(pending.get(name, [])) | set(report.cited_excluded)) - set(report.restored)
            )
        revision["products"][name] = {
            "fields": list(report.fields),
            "rate_table_quotes_removed": report.excluded_quotes_removed,
            "quotes_split": report.quotes_split,
            "fields_split": list(report.fields_split),
            "quotes_widened": [list(pair) for pair in report.quotes_widened],
            "to_unknown": list(report.to_unknown),
            "restored": list(report.restored),
        }
    if not pending:
        del manifest["pending_semantic_review"]
    if args.segmentation:
        manifest["segmentation"] = args.segmentation
    revisions = manifest.setdefault("revisions", [])
    if revision not in revisions:
        revisions.append(revision)
    texts[gold / "manifest.json"] = _dump(manifest)
    try:
        _commit(texts)
    except OSError:
        print(json.dumps({"stopped": "OUTPUT_FAILED"}))
        return 2
    print(json.dumps({"products": {name: len(c.report.fields) for name, c in results.items()}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
