from __future__ import annotations

# ruff: noqa: F811
import importlib
import json
from dataclasses import replace

import pytest

from tests.product_ingestion.test_platform import snapshot  # noqa: F401
from tests.product_ingestion.test_source_geometry import native_snapshot


def module():
    try:
        return importlib.import_module("insurance_harness.product_ingestion.identity")
    except ModuleNotFoundError:
        pytest.fail("platform identity input adapter is not implemented")


def test_current_corpus_retains_exact_source_and_stable_knowledge_identity(snapshot):
    scope, body, sign, keys = snapshot
    body["receipt"]["manifest_algorithm"] = "weknora.chunk_manifest.v1"
    decoded = native_snapshot(snapshot)
    corpus = module().build_current_corpus(
        scope, {"knowledge": decoded}, declared_by="platform-upload-receipt"
    )
    assert len(corpus.entries) == 1
    entry = corpus.entries[0]
    assert entry.material_id == "knowledge"
    assert entry.blocks == decoded.blocks
    assert entry.provenance.kind == "user_supplied_document"
    assert entry.provenance.declared_by == "platform-upload-receipt"
    assert entry.provenance.acquisition_receipt_sha256 == decoded.snapshot["snapshot_sha256"]
    assert "knowledge" in entry.provenance.source_uri


def test_corpus_refuses_cross_scope_signed_snapshot(snapshot):
    scope, body, sign, keys = snapshot
    body["receipt"]["manifest_algorithm"] = "weknora.chunk_manifest.v1"
    decoded = native_snapshot(snapshot)
    with pytest.raises(ValueError, match="scope"):
        module().build_current_corpus(
            scope.model_copy(update={"space_id": "other"}),
            {"knowledge": decoded},
            declared_by="platform-upload-receipt",
        )


def test_prompt_selects_first_page_without_unrelated_later_source_or_history(snapshot):
    scope, body, sign, keys = snapshot
    body["receipt"]["manifest_algorithm"] = "weknora.chunk_manifest.v1"
    decoded = native_snapshot(snapshot)
    from insurance_harness.product_ingestion.source_geometry import project_native_pages

    pages = project_native_pages(decoded, material_id="knowledge")
    original = decoded.blocks[0]
    unrelated = original.model_copy(
        update={"block_id": "later", "page_number": 2, "text": "UNRELATED_LATER_CONTENT"}
    )
    decoded = replace(decoded, blocks=(*decoded.blocks, unrelated))
    corpus = module().build_current_corpus(
        scope, {"knowledge": decoded}, declared_by="platform-upload-receipt"
    )
    context = module().build_identity_context(
        corpus,
        pages,
        product_name="平安测试（2026）两全保险",
        primary_label="endowment_insurance",
        material_roles={"knowledge": "terms"},
        allowed_material_roles=("terms",),
        allowed_taxonomy_labels=("endowment_insurance",),
        existing_entities=(),
    )
    raw = json.dumps(context, ensure_ascii=False)
    assert "UNRELATED_LATER_CONTENT" not in raw
    assert context["first_page_routing"]["product_name"] == "平安测试（2026）两全保险"
    assert context["materials"][0]["blocks"][0]["evidence_locator_refs"]


def test_issuer_extra_block_is_selected_by_block_text_not_shared_whole_page(snapshot):
    from insurance_harness.product_ingestion.source_geometry import project_native_pages

    scope, body, *_ = snapshot
    body["receipt"]["manifest_algorithm"] = "weknora.chunk_manifest.v1"
    decoded = native_snapshot(snapshot)
    page = project_native_pages(decoded, material_id="knowledge")[0]
    original = decoded.blocks[0]
    company = "测试人寿保险股份有限公司"
    other = original.model_copy(update={"block_id": "a", "page_number": 2, "text": "同页其他内容"})
    issuer = original.model_copy(update={"block_id": "b", "page_number": 2, "text": company})
    pages = (
        page,
        *(
            page.model_copy(
                update={
                    "block_ref": key,
                    "block_id": key,
                    "page_number": 2,
                    "text": company,
                    "boxes": (),
                }
            )
            for key in ("a", "b")
        ),
    )
    corpus = module().build_current_corpus(
        scope,
        {"knowledge": replace(decoded, blocks=(*decoded.blocks, other, issuer))},
        declared_by="platform-upload-receipt",
    )
    context = module().build_identity_context(
        corpus,
        pages,
        product_name="平安测试（2026）两全保险",
        primary_label="endowment_insurance",
        material_roles={"knowledge": "terms"},
        allowed_material_roles=("terms",),
        allowed_taxonomy_labels=("endowment_insurance",),
        existing_entities=(),
    )
    sent = [block["text"] for block in context["materials"][0]["blocks"]]
    assert company in sent
    assert "同页其他内容" not in sent


def test_identity_prompt_does_not_require_regex_hints(snapshot):
    from insurance_harness.product_ingestion.source_geometry import project_native_pages

    scope, body, *_ = snapshot
    body["receipt"]["manifest_algorithm"] = "weknora.chunk_manifest.v1"
    decoded = native_snapshot(snapshot)
    corpus = module().build_current_corpus(scope, {"knowledge": decoded}, declared_by="fixture")
    context = module().build_identity_context(
        corpus,
        project_native_pages(decoded, material_id="knowledge"),
        allowed_material_roles=("terms", "brochure", "rate_table"),
        allowed_taxonomy_labels=("endowment_insurance",),
        existing_entities=(),
        schema_candidates=(
            {"schema_pack_id": "fixture", "applicable_classifications": ["endowment_insurance"]},
        ),
    )
    assert context["first_page_routing"] == {"product_name": None, "primary_label": None}
    assert len(context["schema_candidates"]) == 1
    assert context["materials"][0]["first_page_material_role"] is None
    assert context["materials"][0]["blocks"][0]["evidence_locator_refs"]


@pytest.mark.parametrize("bad", ["foreign locator", "later title", "later product code"])
def test_identity_response_cannot_expand_offered_evidence(bad):
    ref = "loc_" + "a" * 64
    context = {
        "materials": [
            {
                "material_id": "material",
                "blocks": [
                    {
                        "page_number": 1 if bad == "foreign locator" else 2,
                        "evidence_locator_refs": [{"locator_ref": ref}],
                    }
                ],
            }
        ]
    }
    purpose = "product_code" if bad == "later product code" else "name"
    response = {
        "contract": "g3-batch-resolution-semantic-references.local.v1",
        "materials": [
            {
                "material_id": "material",
                "material_role": "terms",
                "material_role_evidence_refs": [],
                "entities": [],
                "evidence": [
                    {
                        "evidence_ref": "e",
                        "entity_ref": "entity",
                        "purpose": purpose,
                        "field_key": None,
                        "locator_ref": "loc_" + "b" * 64 if bad == "foreign locator" else ref,
                    }
                ],
            }
        ],
    }
    with pytest.raises(ValueError, match="outside offered|issuer only"):
        module().validate_identity_offered_response(json.dumps(response).encode(), context)


def test_identity_first_page_context_omits_cross_page_tail(snapshot):
    from insurance_harness.product_ingestion.source_geometry import project_native_pages

    scope, body, *_ = snapshot
    body["receipt"]["manifest_algorithm"] = "weknora.chunk_manifest.v1"
    decoded = native_snapshot(snapshot)
    page = project_native_pages(decoded, material_id="knowledge")[0]
    original = decoded.blocks[0]
    tail = "OTHER_PRODUCT_ON_PAGE_TWO"
    source = original.model_copy(update={"text": original.text + tail})
    changed = json.loads(json.dumps(decoded.snapshot))
    changed["chunk_page_mappings"][0]["page_spans"] = [
        {"page_number": 1, "block_codepoint_start": 0, "block_codepoint_end": len(original.text)}
    ]
    decoded = replace(decoded, blocks=(source,), snapshot=changed)
    corpus = module().build_current_corpus(scope, {"knowledge": decoded}, declared_by="fixture")
    context = module().build_identity_context(
        corpus,
        (page,),
        allowed_material_roles=("terms",),
        allowed_taxonomy_labels=("endowment_insurance",),
        existing_entities=(),
        snapshots={"knowledge": decoded},
    )
    assert tail not in json.dumps(context)
    block = context["materials"][0]["blocks"][0]
    assert block["text"] == original.text and block["source_ranges"] == [(0, len(original.text))]


def test_cross_page_company_tail_does_not_hide_offered_issuer_block(snapshot):
    from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
        G3NativeCharacterBoxV1,
    )
    from insurance_harness.product_ingestion.source_geometry import project_native_pages

    scope, body, *_ = snapshot
    body["receipt"]["manifest_algorithm"] = "weknora.chunk_manifest.v1"
    decoded = native_snapshot(snapshot)
    page = project_native_pages(decoded, material_id="knowledge")[0]
    original = decoded.blocks[0]
    company = "测试人寿保险股份有限公司"
    crossing = original.model_copy(update={"text": original.text + company})
    issuer = original.model_copy(update={"block_id": "issuer", "page_number": 2, "text": company})
    extra = page.model_copy(
        update={
            "block_ref": "issuer-ref",
            "block_id": "issuer",
            "page_number": 2,
            "text": company,
            "boxes": tuple(
                G3NativeCharacterBoxV1(index=i, x=1.0, y=1.0, width=1.0, height=1.0)
                for i in range(len(company))
            ),
        }
    )
    changed = json.loads(json.dumps(decoded.snapshot))
    changed["chunk_page_mappings"] = [
        {
            "chunk_id": original.block_id,
            "page_spans": [
                {
                    "page_number": 1,
                    "block_codepoint_start": 0,
                    "block_codepoint_end": len(original.text),
                }
            ],
        },
        {
            "chunk_id": "issuer",
            "page_spans": [
                {"page_number": 2, "block_codepoint_start": 0, "block_codepoint_end": len(company)}
            ],
        },
    ]
    decoded = replace(decoded, blocks=(crossing, issuer), snapshot=changed)
    corpus = module().build_current_corpus(scope, {"knowledge": decoded}, declared_by="fixture")
    context = module().build_identity_context(
        corpus,
        (page, extra),
        allowed_material_roles=("terms",),
        allowed_taxonomy_labels=("endowment_insurance",),
        existing_entities=(),
        snapshots={"knowledge": decoded},
    )
    blocks = context["materials"][0]["blocks"]
    assert [block["page_number"] for block in blocks] == [1, 2]
    assert company not in blocks[0]["text"]
    assert blocks[1]["text"] == company and blocks[1]["evidence_locator_refs"]
