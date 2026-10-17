"""Golden v2 files as the GoldenItem JSONL that `eval.semantic_run` reads (RV2b Spec §3.1).

usage: python -m insurance_harness.eval.golden_items --products <id>... --out <file>
       [--repo <dir>] [--judged-by <human|legacy|model>:<who>]

One item per Golden field of each product. The pack and, unless --judged-by is given, the judge
(`model:<model_id>`) come from dataset/golden/v2/manifest.json; state, value and evidence come
from the product's Golden v2 file, and its reason becomes the note. Golden v2 evidence also keeps
the segment id it was labelled on; GoldenEvidence has no such field (the semantic judge compares
values, not segments), so the id is dropped. Items are sorted by product and field key, so the
same inputs always give the same bytes. Nothing is written unless every product converts, and an
existing output is never replaced.

Prints one JSON line: a summary of items per product, or {"stopped": <code>} with exit 2. Neither
carries paths or Golden text.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

from pydantic import ValidationError

from insurance_harness.eval.golden import GoldenEvidence, GoldenItem
from insurance_harness.eval.product_sources import check_product_id
from insurance_harness.eval.segment_score import GOLDEN_DIR, GoldenV2

REPO = Path(__file__).resolve().parents[4]


class _Stopped(Exception):
    def __init__(self, code: str, product: str | None = None) -> None:
        super().__init__(code)
        self.code, self.product = code, product


class _Parser(argparse.ArgumentParser):
    """Malformed arguments become the INVALID_ARGUMENTS code, not usage text."""

    def error(self, message: str) -> NoReturn:
        raise _Stopped("INVALID_ARGUMENTS")


def _convert(repo: Path, products: list[str], judged_by: str | None = None) -> list[GoldenItem]:
    """Every Golden field of the products, in product then field-key order."""
    manifest = _manifest(repo)
    items: list[GoldenItem] = []
    for product in sorted(products):
        items.extend(_product_items(repo, product, manifest.get(product), judged_by))
    return sorted(items, key=lambda item: (item.product_id, item.field_key))


def _unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """A repeated member name at any depth is an error: last-one-wins could flip a pack or a
    value unseen (review R1). Inputs are decoded with this hook before shape validation."""
    members: dict[str, Any] = {}
    for key, value in pairs:
        if key in members:
            raise ValueError("duplicate JSON object member")
        members[key] = value
    return members


def _manifest(repo: Path) -> dict[str, Any]:
    try:
        raw = (repo / GOLDEN_DIR / "manifest.json").read_bytes()
        data = json.loads(raw, object_pairs_hook=_unique_members)
    except (OSError, ValueError) as error:  # UnicodeDecodeError and JSONDecodeError included
        raise _Stopped("MANIFEST_UNREADABLE") from error
    products = data.get("products") if isinstance(data, dict) else None
    if not isinstance(products, dict):
        raise _Stopped("MANIFEST_UNREADABLE")
    return products


def _product_items(
    repo: Path, product: str, entry: object, judged_by: str | None
) -> list[GoldenItem]:
    if not isinstance(entry, dict) or not isinstance(entry.get("pack_id"), str):
        raise _Stopped("PRODUCT_NOT_IN_MANIFEST", product)
    if judged_by is None:
        model = entry.get("model_id")
        if not isinstance(model, str):
            raise _Stopped("JUDGE_NOT_RECORDED", product)
        judged_by = f"model:{model}"
    try:
        raw = (repo / GOLDEN_DIR / f"{product}.json").read_bytes()
        json.loads(raw, object_pairs_hook=_unique_members)
        golden = GoldenV2.model_validate_json(raw)  # strict JSON mode, as load_golden_v2
    except (OSError, ValueError) as error:  # unreadable, bad JSON, duplicates or bad shape
        raise _Stopped("GOLDEN_INVALID", product) from error
    if golden.product_id != product:
        raise _Stopped("GOLDEN_INVALID", product)
    try:
        return [
            GoldenItem(
                pack_id=entry["pack_id"],
                product_id=product,
                field_key=field.field_key,
                state=field.state,
                value=field.value,
                evidence=[
                    GoldenEvidence(
                        document=quote.document,
                        document_sha256=quote.document_sha256,
                        page=quote.page,
                        quote=quote.quote,
                    )
                    for quote in field.evidence
                ],
                judged_by=judged_by,
                note=field.reason,
            )
            for field in golden.fields
        ]
    except ValidationError as error:
        raise _Stopped("GOLDEN_ITEM_INVALID", product) from error


def _write(out: Path, text: str) -> None:
    if out.exists() or out.is_symlink():
        raise _Stopped("OUTPUT_EXISTS")
    created = False
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as stream:
            created = True
            stream.write(text)
    except FileExistsError as error:
        raise _Stopped("OUTPUT_EXISTS") from error
    except OSError as error:
        if created:
            out.unlink(missing_ok=True)
        raise _Stopped("OUTPUT_FAILED") from error


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument("--products", nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--judged-by")
    try:
        args = parser.parse_args(argv)
        if len(set(args.products)) != len(args.products):
            raise _Stopped("INVALID_ARGUMENTS")
        for product in args.products:
            try:
                check_product_id(product)
            except ValueError as error:
                raise _Stopped("INVALID_ARGUMENTS") from error
        items = _convert(args.repo, args.products, args.judged_by)
        _write(
            args.out,
            "".join(
                json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
                for item in items
            ),
        )
    except _Stopped as stop:
        detail = {"product": stop.product} if stop.product else {}
        print(json.dumps({"stopped": stop.code, **detail}, ensure_ascii=False))
        return 2
    counts: dict[str, int] = {}
    for item in items:
        counts[item.product_id] = counts.get(item.product_id, 0) + 1
    print(json.dumps({"items": len(items), "products": counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
