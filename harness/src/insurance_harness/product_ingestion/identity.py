"""Current-product identity inputs derived from signed platform source custody."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_sha256_830_g3
from insurance_harness.knowledge_compiler.batch_entity_resolution_830_g3 import (
    BatchCorpusV1,
    CorpusEntryV1,
    ExistingEntityV1,
    SourceProvenanceV1,
)
from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
    G3NativePageProjectionV1,
    G3SemanticReferenceResponseV1,
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


def build_identity_context(
    corpus: BatchCorpusV1,
    pages: Sequence[G3NativePageProjectionV1],
    *,
    product_name: str,
    primary_label: str,
    material_roles: Mapping[str, str],
    allowed_material_roles: tuple[str, ...],
    allowed_taxonomy_labels: tuple[str, ...],
    existing_entities: Sequence[ExistingEntityV1],
) -> dict:
    materials = []
    for entry in corpus.entries:
        sources = {(row.revision_id, row.block_id): row for row in entry.blocks}
        available = sorted(
            (row for row in pages if row.material_id == entry.material_id),
            key=lambda row: (row.page_number, row.block_id),
        )
        selected = [row for row in available if row.page_number == 1]
        # An insurer heading may be printed on the following page. Include at
        # most one additional real block bearing an explicit legal company name.
        company = re.compile(r"[\u4e00-\u9fff]{2,40}保险[\u4e00-\u9fff]{0,12}公司")
        if not any(
            company.search(sources[(row.revision_id, row.block_id)].text) for row in selected
        ):
            extra = next(
                (
                    row
                    for row in available
                    if row.page_number <= 3
                    and row not in selected
                    and company.search(sources[(row.revision_id, row.block_id)].text)
                ),
                None,
            )
            if extra is not None:
                selected.append(extra)
        if not selected:
            raise ValueError("current material has no first-page identity geometry")
        blocks = []
        for page in selected:
            source = sources.get((page.revision_id, page.block_id))
            if source is None or page.page_number != source.page_number:
                raise ValueError("identity geometry source mismatch")
            blocks.append(
                _c_prompt_block(
                    page.block_ref,
                    source.text,
                    use_locator_refs=True,
                    native_page=page,
                    source=source,
                )
            )
        materials.append(
            {
                "material_id": entry.material_id,
                "first_page_material_role": material_roles[entry.material_id],
                "blocks": blocks,
            }
        )
    matching = [
        row.model_dump(mode="json")
        for row in existing_entities
        if _name(row.name) == _name(product_name)
        or any(_name(alias.value) == _name(product_name) for alias in row.approved_aliases)
    ]
    return {
        "contract": "g3-c-classify-prompt-context.830.v1",
        "first_page_routing": {"product_name": product_name, "primary_label": primary_label},
        "materials": materials,
        "allowed_material_roles": allowed_material_roles,
        "allowed_taxonomy_labels": allowed_taxonomy_labels,
        "existing_entities": matching,
        "response_schema": G3SemanticReferenceResponseV1.model_json_schema(),
    }
