"""Identity evidence must reach page-two tails without changing source identity."""

from __future__ import annotations

import json
from typing import Any

from insurance_harness.product_ingestion import identity
from tests.product_ingestion.test_platform import decode, snapshot  # noqa: F401
from tests.product_ingestion.test_source_geometry import bounded_identity_snapshot


def crossing_only_snapshot(fixture: Any) -> Any:
    decoded = bounded_identity_snapshot(fixture)
    body = json.loads(json.dumps(decoded.snapshot))
    body["chunks"] = [r for r in body["chunks"] if r["id"] not in {"issuer", "issuer3"}]
    body["chunk_page_mappings"] = [
        r for r in body["chunk_page_mappings"] if r["chunk_id"] not in {"issuer", "issuer3"}
    ]
    body["receipt"]["chunk_count"] = len(body["chunks"])
    return decode(fixture, fixture[2](body))


def test_crossing_only_issuer_is_offered_on_actual_page_two(snapshot: Any) -> None:  # noqa: F811
    decoded = crossing_only_snapshot(snapshot)
    corpus = identity.build_current_corpus(
        snapshot[0], {"knowledge": decoded}, declared_by="fixture"
    )
    prepare = getattr(identity, "prepare_identity_sources", None)
    assert prepare is not None, "identity must prepare physical page views"
    prepared = prepare(
        corpus,
        {"knowledge": decoded},
        allowed_material_roles=("terms",),
        allowed_taxonomy_labels=("endowment_insurance",),
    )
    blocks = prepared.context["materials"][0]["blocks"]
    assert [b["page_number"] for b in blocks] == [1, 2]
    assert "测试人寿保险股份有限公司" not in blocks[0]["text"]
    assert "测试人寿保险股份有限公司" in blocks[1]["text"]
    assert blocks[1]["evidence_locator_refs"]
    assert prepared.context["contract"] == "product-identity-source-context.830.v3"
    assert corpus.entries[0].blocks == decoded.blocks
    assert decoded.blocks[0].page_number == 1


def prepare(fixture: Any, decoded: Any) -> Any:
    corpus = identity.build_current_corpus(
        fixture[0], {"knowledge": decoded}, declared_by="fixture"
    )
    return identity.prepare_identity_sources(
        corpus,
        {"knowledge": decoded},
        allowed_material_roles=("terms",),
        allowed_taxonomy_labels=("endowment_insurance",),
    )


def response_for(prepared: Any) -> bytes:
    blocks = prepared.context["materials"][0]["blocks"]
    first = blocks[0]["evidence_locator_refs"][0]["locator_ref"]
    issuer = blocks[1]["evidence_locator_refs"][0]["locator_ref"]
    evidence = [
        {
            "evidence_ref": purpose,
            "entity_ref": None if purpose == "material_role" else "product",
            "purpose": purpose,
            "field_key": None,
            "locator_ref": ref,
        }
        for purpose, ref in [
            ("classification", first),
            ("issuer", issuer),
            ("material_role", first),
            ("name", first),
            ("version", first),
        ]
    ]
    value = {
        "contract": "g3-batch-resolution-semantic-references.local.v1",
        "materials": [
            {
                "material_id": "knowledge",
                "material_role": "terms",
                "material_role_evidence_refs": ["material_role"],
                "evidence": evidence,
                "entities": [
                    {
                        "entity_ref": "product",
                        "issuer": "测试人寿保险股份有限公司",
                        "name": "平安测试（2026）两全保险",
                        "product_code": None,
                        "version_label": "2026",
                        "filing_or_registration": None,
                        "identity_confidence": "1.000000",
                        "identity_evidence_refs": ["issuer", "name", "version"],
                        "labels": [
                            {
                                "taxonomy_label": "endowment_insurance",
                                "confidence": "1.000000",
                                "evidence_refs": ["classification"],
                            }
                        ],
                        "primary_label": "endowment_insurance",
                        "valid_from": None,
                        "valid_through": None,
                    }
                ],
            }
        ],
    }
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def test_cross_page_proposal_keeps_source_identity_and_proves_physical_page(snapshot: Any) -> None:  # noqa: F811
    from insurance_harness.product_ingestion.source_geometry import project_evidence_locations

    decoded = crossing_only_snapshot(snapshot)
    prepared = prepare(snapshot, decoded)
    proposals = identity.assemble_identity_response(
        response_for(prepared),
        prepared,
        model_request_sha256="a" * 64,
    )
    row = next(e for e in proposals[0].evidence if e.purpose == "issuer")
    assert row.evidence.page_number == 1
    parts, proof = project_evidence_locations(row.evidence, decoded)
    assert parts == (row.evidence,)
    assert proof["parts"][0]["actual_page_number"] == 2
    assert proposals[0].entities[0].issuer == "测试人寿保险股份有限公司"


def test_unchanged_identity_context_and_proposals_match_legacy(snapshot: Any) -> None:  # noqa: F811
    from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
        assemble_c_semantic_response,
    )
    from insurance_harness.product_ingestion.source_geometry import project_native_pages

    decoded = bounded_identity_snapshot(snapshot)
    prepared = prepare(snapshot, decoded)
    pages = project_native_pages(
        decoded,
        material_id="knowledge",
        selected_block_ids=identity.select_identity_block_ids(decoded),
    )
    old = identity.build_identity_context(
        prepared.corpus,
        pages,
        allowed_material_roles=("terms",),
        allowed_taxonomy_labels=("endowment_insurance",),
        snapshots={"knowledge": decoded},
    )
    assert (
        json.dumps(old, sort_keys=True, ensure_ascii=False).encode()
        == json.dumps(prepared.context, sort_keys=True, ensure_ascii=False).encode()
    )
    raw = response_for(prepared)
    expected = assemble_c_semantic_response(
        raw=raw,
        corpus=prepared.corpus,
        requested_material_ids=("knowledge",),
        native_pages=pages,
        allowed_material_roles=("terms",),
        allowed_taxonomy_labels=("endowment_insurance",),
        model_request_sha256="a" * 64,
        use_locator_refs=True,
    )
    assert (
        identity.assemble_identity_response(raw, prepared, model_request_sha256="a" * 64)
        == expected
    )


def test_later_page_cannot_supply_first_page_claims(snapshot: Any) -> None:  # noqa: F811
    import pytest

    prepared = prepare(snapshot, crossing_only_snapshot(snapshot))
    raw = json.loads(response_for(prepared))
    rows = raw["materials"][0]["evidence"]
    issuer = next(r for r in rows if r["purpose"] == "issuer")
    for purpose in ("name", "classification", "material_role"):
        changed = json.loads(json.dumps(raw))
        next(r for r in changed["materials"][0]["evidence"] if r["purpose"] == purpose)[
            "locator_ref"
        ] = issuer["locator_ref"]
        with pytest.raises(ValueError, match="require first page"):
            identity.assemble_identity_response(
                json.dumps(changed).encode(), prepared, model_request_sha256="a" * 64
            )


def test_bad_page_two_geometry_fails_before_offering_evidence(snapshot: Any) -> None:  # noqa: F811
    from dataclasses import replace

    import pytest

    decoded = crossing_only_snapshot(snapshot)
    native = json.loads(decoded.native_bytes)
    native["pages"][1]["page_text_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="native page|identity source custody"):
        prepare(snapshot, replace(decoded, native_bytes=json.dumps(native).encode()))
    native = json.loads(decoded.native_bytes)
    native["pages"][1]["bboxes"] = []
    with pytest.raises(ValueError, match="CHARACTER_LOCATION_MISSING|identity source custody"):
        prepare(snapshot, replace(decoded, native_bytes=json.dumps(native).encode()))


def test_overlapping_crossing_chunks_offer_only_one_company(snapshot: Any) -> None:  # noqa: F811
    from copy import deepcopy

    decoded = crossing_only_snapshot(snapshot)
    body = deepcopy(decoded.snapshot)
    chunk = deepcopy(body["chunks"][0])
    chunk.update(id="overlapping", index=3)
    mapping = deepcopy(body["chunk_page_mappings"][0])
    mapping["chunk_id"] = "overlapping"
    body["chunks"].append(chunk)
    body["chunk_page_mappings"].append(mapping)
    body["receipt"]["chunk_count"] += 1
    decoded = decode(snapshot, snapshot[2](body))
    prepared = prepare(snapshot, decoded)
    assert [b["page_number"] for b in prepared.context["materials"][0]["blocks"]] == [1, 1, 2]


def test_invalid_catalog_or_changed_evidence_is_rejected(snapshot: Any) -> None:  # noqa: F811
    from dataclasses import replace

    import pytest

    prepared = prepare(snapshot, crossing_only_snapshot(snapshot))
    raw = response_for(prepared)
    with pytest.raises(ValueError, match="duplicate"):
        identity.assemble_identity_response(
            raw, replace(prepared, offers=prepared.offers * 2), model_request_sha256="a" * 64
        )
    issuer = next(o for o in prepared.offers if o.actual_page_number == 2)
    changed = replace(issuer, evidence=issuer.evidence.model_copy(update={"page_number": 2}))
    bad = replace(prepared, offers=tuple(changed if o is issuer else o for o in prepared.offers))
    with pytest.raises(ValueError):
        identity.assemble_identity_response(raw, bad, model_request_sha256="a" * 64)
    obj = json.loads(raw)
    obj["materials"][0]["evidence"][0]["locator_ref"] = "loc_" + "f" * 64
    with pytest.raises(ValueError, match="outside offered"):
        identity.assemble_identity_response(
            json.dumps(obj).encode(), prepared, model_request_sha256="a" * 64
        )


def test_source_views_reject_other_scope_or_capture_with_same_blocks(snapshot: Any) -> None:  # noqa: F811
    import base64
    import hashlib
    from copy import deepcopy

    import pytest

    from insurance_harness.product_ingestion.platform import decode_source_snapshot
    from tests.product_ingestion.test_platform import canonical

    decoded = crossing_only_snapshot(snapshot)
    corpus = identity.build_current_corpus(
        snapshot[0], {"knowledge": decoded}, declared_by="fixture"
    )
    for change in ("scope", "native_capture"):
        body = deepcopy(decoded.snapshot)
        scope = snapshot[0]
        if change == "scope":
            body["scope"]["wiki_kb_id"] = "other-wiki"
            scope = scope.model_copy(update={"wiki_knowledge_base_id": "other-wiki"})
        else:
            native = json.loads(decoded.native_bytes)
            native["pages"][1]["width_points"] = "101"
            raw = canonical(native)
            body["native"]["SanitizedJSON"] = base64.b64encode(raw).decode()
            body["native"]["SanitizedSHA256"] = body["native_capture_sha256"] = hashlib.sha256(
                raw
            ).hexdigest()
        other = decode_source_snapshot(
            snapshot[2](body),
            scope=scope,
            knowledge_id="knowledge",
            parse_attempt=1,
            public_keys=snapshot[3],
        )
        assert other.blocks == decoded.blocks
        with pytest.raises(ValueError, match="identity source custody"):
            identity.prepare_identity_sources(
                corpus,
                {"knowledge": other},
                allowed_material_roles=("terms",),
                allowed_taxonomy_labels=("endowment_insurance",),
            )
