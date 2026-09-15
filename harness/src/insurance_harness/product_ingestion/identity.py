"""Current-product identity inputs derived from signed platform source custody."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import (
    batch_sha256_830_g3,
)
from insurance_harness.knowledge_compiler.batch_entity_resolution_830_g3 import (
    BatchCorpusV1,
    CorpusEntryV1,
    ExistingEntityV1,
    SourceProvenanceV1,
)
from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
    G3NativePageProjectionV1,
    G3SemanticReferenceResponseV1,
    _c_eligible_source_locators,
    _c_locator_ref,
    _c_prompt_block,
)
from insurance_harness.product_ingestion.models import ProductScope
from insurance_harness.product_ingestion.platform import DecodedSourceSnapshot


def hashed(model, domain: str, hash_field: str, **payload):
    return model.model_validate(
        {
            **payload,
            hash_field: batch_sha256_830_g3(domain, payload),
        }
    )


def build_current_corpus(
    scope: ProductScope,
    snapshots: Mapping[str, DecodedSourceSnapshot],
    *,
    declared_by: str,
) -> BatchCorpusV1:
    entries = []
    expected_scope = {
        "tenant_id": int(scope.tenant_id),
        "space_id": scope.space_id,
        "raw_kb_id": scope.raw_knowledge_base_id,
        "wiki_kb_id": scope.wiki_knowledge_base_id,
    }
    for knowledge_id, decoded in sorted(snapshots.items()):
        body = decoded.snapshot
        if body["scope"] != expected_scope or body["receipt"]["knowledge_id"] != knowledge_id:
            raise ValueError("current corpus source scope mismatch")
        if any(
            (row.tenant_id, row.space_id, row.raw_kb_id, row.knowledge_id)
            != (
                int(scope.tenant_id),
                scope.space_id,
                scope.raw_knowledge_base_id,
                knowledge_id,
            )
            for row in decoded.blocks
        ):
            raise ValueError("current corpus block scope mismatch")
        provenance = hashed(
            SourceProvenanceV1,
            "source-provenance.830.g3.v1",
            "declaration_sha256",
            provenance_id="platform-upload:" + knowledge_id,
            kind="user_supplied_document",
            source_uri=f"weknora://{scope.tenant_id}/{scope.raw_knowledge_base_id}/{knowledge_id}",
            acquisition_receipt_sha256=body["snapshot_sha256"],
            declared_by=declared_by,
        )
        entries.append(
            hashed(
                CorpusEntryV1,
                "corpus-entry.830.g3.v1",
                "entry_sha256",
                material_id=knowledge_id,
                receipt=body["receipt"],
                native_capture_sha256=body["native_capture_sha256"],
                parser_identity_sha256=body["parser_identity_sha256"],
                blocks=tuple(
                    sorted(decoded.blocks, key=lambda row: (row.revision_id, row.block_id))
                ),
                provenance=provenance,
            )
        )
    return hashed(
        BatchCorpusV1,
        "batch-corpus.830.g3.v1",
        "corpus_sha256",
        contract="batch-corpus.830.g3.v1",
        **expected_scope,
        entries=tuple(entries),
    )


def _name(value: str) -> str:
    return re.sub(r"\s+", "", value).translate(str.maketrans({"(": "（", ")": "）"}))


def prepare_identity_routing(snapshots, materials, catalog) -> dict:
    """Prepare source custody and Catalog options, without deciding identity."""
    rows = []
    for material in materials:
        decoded = snapshots[material.knowledge_id]
        if not decoded.first_page_ranges:
            raise ValueError("FIRST_PAGE_PRODUCT_NAME_UNAVAILABLE")
        rows.append(
            {
                "material_id": material.material_id,
                "knowledge_id": material.knowledge_id,
                "file_name": material.original_filename,
                "first_page_ranges": decoded.first_page_ranges,
            }
        )
    return {
        "contract": "product-routing-input.830.v2",
        "status": "prepared",
        "product_name": None,
        "route": None,
        "materials": rows,
        "schema_candidates": [
            {
                "schema_pack_id": row.pack.schema_pack_id,
                "display_name": row.pack.display_name,
                "applicable_classifications": row.pack.applicable_classifications,
            }
            for row in catalog.entries
        ],
    }


def validate_identity_offered_response(raw: bytes, context: dict) -> None:
    """A valid native locator is still ineligible unless this call offered it."""
    response = G3SemanticReferenceResponseV1.model_validate_json(raw)
    offered = {
        material["material_id"]: {
            ref["locator_ref"]: block.get("page_number", 1)
            for block in material["blocks"]
            for ref in block["evidence_locator_refs"]
        }
        for material in context["materials"]
    }
    for material in response.materials:
        refs = offered.get(material.material_id, {})
        for evidence in material.evidence:
            page = refs.get(evidence.locator_ref)
            if page is None:
                raise ValueError("identity evidence outside offered source")
            if page != 1 and evidence.purpose not in {
                "issuer",
                "product_code",
                "version",
            }:
                raise ValueError("identity title classification and role require first page")


def _select_identity_sources(available, page_text):
    selected = [row for row in available if row.page_number == 1]
    company = re.compile(r"[\u4e00-\u9fff]{2,40}保险[\u4e00-\u9fff]{0,12}公司")
    legal_company = re.compile(r"[\u4e00-\u9fff]{2,40}保险(?:股份有限公司|有限责任公司|有限公司)")
    # Prefer an actual legal-entity suffix to generic language such as
    # “保险人就是保险公司”. This selects evidence, never canonicalizes an issuer.
    eligible = [row for row in available if row.page_number <= 3]
    pattern = (
        legal_company if any(legal_company.search(page_text(row)) for row in eligible) else company
    )
    if not any(pattern.search(page_text(row)) for row in selected):
        extra = next(
            (
                row
                for row in available
                if row.page_number <= 3 and row not in selected and pattern.search(page_text(row))
            ),
            None,
        )
        if extra is not None:
            selected.append(extra)
    if not selected:
        raise ValueError("current material has no first-page identity geometry")
    return selected


def select_identity_block_ids(decoded: DecodedSourceSnapshot) -> tuple[str, ...]:
    """Select source blocks before expanding geometry; preserve prompt selection."""
    mappings = {row["chunk_id"]: row for row in decoded.snapshot["chunk_page_mappings"]}

    def page_text(block):
        return "\n".join(
            block.text[row["block_codepoint_start"] : row["block_codepoint_end"]]
            for row in mappings[block.block_id]["page_spans"]
            if row["page_number"] == block.page_number
        )

    available = sorted(decoded.blocks, key=lambda row: (row.page_number, row.block_id))
    return tuple(row.block_id for row in _select_identity_sources(available, page_text))


def build_identity_context(
    corpus: BatchCorpusV1,
    pages: Sequence[G3NativePageProjectionV1],
    *,
    product_name: str | None = None,
    primary_label: str | None = None,
    material_roles: Mapping[str, str] | None = None,
    allowed_material_roles: tuple[str, ...],
    allowed_taxonomy_labels: tuple[str, ...],
    existing_entities: Sequence[ExistingEntityV1],
    schema_candidates: Sequence[dict] = (),
    snapshots: Mapping[str, DecodedSourceSnapshot] | None = None,
) -> dict:
    materials = []
    for entry in corpus.entries:
        sources = {(row.revision_id, row.block_id): row for row in entry.blocks}
        available = sorted(
            (row for row in pages if row.material_id == entry.material_id),
            key=lambda row: (row.page_number, row.block_id),
        )

        def page_ranges(page, source_map=sources, material_id=entry.material_id):
            source = source_map[(page.revision_id, page.block_id)]
            if snapshots is None:
                return [(0, len(source.text))]
            mapping = next(
                row
                for row in snapshots[material_id].snapshot["chunk_page_mappings"]
                if row["chunk_id"] == page.block_id
            )
            return [
                (row["block_codepoint_start"], row["block_codepoint_end"])
                for row in mapping["page_spans"]
                if row["page_number"] == page.page_number
            ]

        def page_text(page, source_map=sources, ranges_for=page_ranges):
            text = source_map[(page.revision_id, page.block_id)].text
            return "\n".join(text[start:end] for start, end in ranges_for(page))

        selected = _select_identity_sources(available, page_text)
        blocks = []
        for page in selected:
            source = sources.get((page.revision_id, page.block_id))
            if source is None or page.page_number != source.page_number:
                raise ValueError("identity geometry source mismatch")
            prompt_block = _c_prompt_block(
                page.block_ref,
                source.text,
                use_locator_refs=True,
                native_page=page,
                source=source,
            )
            if snapshots is not None:
                ranges = page_ranges(page)
                eligible = {
                    _c_locator_ref(row)
                    for row in _c_eligible_source_locators(page, source)
                    if any(start <= row.start < row.end <= end for start, end in ranges)
                }
                prompt_block["text"] = "\n".join(source.text[start:end] for start, end in ranges)
                prompt_block["source_ranges"] = ranges
                prompt_block["evidence_locator_refs"] = [
                    row
                    for row in prompt_block["evidence_locator_refs"]
                    if row["locator_ref"] in eligible
                ]
            prompt_block["page_number"] = page.page_number
            blocks.append(prompt_block)
        materials.append(
            {
                "material_id": entry.material_id,
                "first_page_material_role": (material_roles or {}).get(entry.material_id),
                "blocks": blocks,
            }
        )
    # Model hints are optional. The resolver still receives the full existing set.
    first_text = _name(
        "\n".join(
            block["text"]
            for material in materials
            for block in material["blocks"]
            if block["page_number"] == 1
        )
    )
    matching = [
        row.model_dump(mode="json")
        for row in existing_entities
        if _name(row.name) in first_text
        or any(_name(alias.value) in first_text for alias in row.approved_aliases)
    ]
    return {
        "contract": "g3-c-classify-prompt-context.830.v1",
        "instructions": {
            "classification": (
                "Choose the insurance type from the complete formal product name on page one "
                "and the supplied Chinese Catalog labels. Other insurance types mentioned in "
                "body text are not this product's classification."
            ),
            "material_role": (
                "Identify terms, brochure, or rate table from the material's own labels; "
                "filenames are only hints."
            ),
            "grouping": (
                "Group the supplied materials by the evidenced product name and version. "
                "Formatting, whitespace, book-title brackets and heading decoration may "
                "differ; genuine product or version conflicts must stay unresolved."
            ),
            "issuer": (
                "Use the full legal insurance company name when it is present in this "
                "material's offered text, rather than its short brand name or a filing "
                "prefix. Cite that same material's issuer evidence. If only a short name "
                "is offered, retain it; do not expand it from memory or another material."
            ),
            "version": (
                "An explicit product edition in the formal name, such as 2.0, V2 or a "
                "clearly labelled year edition, is version evidence. Copy the edition "
                "as version_label and cite the offered local locator with purpose version. "
                "Do not confuse a coverage age, payment term, filing year or printing date "
                "with the product edition. Leave version_label null if none is evidenced."
            ),
            "evidence": (
                "Use only the offered locator refs. Name, classification and material-role "
                "evidence must come from page one; a later company block supports issuer "
                "only."
            ),
        },
        "first_page_routing": {
            "product_name": product_name,
            "primary_label": primary_label,
        },
        "materials": materials,
        "allowed_material_roles": allowed_material_roles,
        "allowed_taxonomy_labels": allowed_taxonomy_labels,
        "existing_entities": matching,
        "schema_candidates": list(schema_candidates),
        "response_schema": G3SemanticReferenceResponseV1.model_json_schema(),
    }
