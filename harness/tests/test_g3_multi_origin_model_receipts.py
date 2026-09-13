from __future__ import annotations

from test_batch_entity_resolution_830_g3 import (
    _corpus,
    _entry,
    _existing,
    _material_proposal,
    _model_binding,
    _policy,
    _proposal_batch,
)
from test_batch_entity_resolution_830_g3 import (
    catalog as _catalog_fixture,
)

from insurance_harness.knowledge_compiler import batch_entity_resolution_830_g3 as g


def _two_origin_fixture():
    first = _entry(
        material_id="origin-a",
        text=(
            "平安保险 平安安心医疗保险 产品代码 ORIGIN-A 登记编号 REG-A 版本 2026 医疗保险 官方条款"
        ),
    )
    second = _entry(
        material_id="origin-b",
        text=(
            "平安保险 平安安心医疗保险 产品代码 ORIGIN-B 登记编号 REG-B 版本 2026 医疗保险 官方条款"
        ),
    )
    first_corpus = _corpus(first)
    second_corpus = _corpus(second)
    first_receipt = _model_binding(first_corpus, first)
    second_receipt = _model_binding(second_corpus, second)
    merged = _corpus(first, second)
    proposals = _proposal_batch(
        merged,
        tuple(sorted((first_receipt, second_receipt), key=lambda row: row.request_sha256)),
        (
            _material_proposal(
                first,
                first_receipt,
                entities=(
                    {
                        "proposal_ref": "main",
                        "name": "平安安心医疗保险",
                        "product_code": "ORIGIN-A",
                        "filing": "REG-A",
                    },
                ),
            ),
            _material_proposal(
                second,
                second_receipt,
                entities=(
                    {
                        "proposal_ref": "main",
                        "name": "平安安心医疗保险",
                        "product_code": "ORIGIN-B",
                        "filing": "REG-B",
                    },
                ),
            ),
        ),
    )
    return merged, proposals, first_receipt, second_receipt


def test_resolver_accepts_two_verified_origin_receipt_hashes():
    corpus, proposals, first, second = _two_origin_fixture()
    resolution = g.resolve_batch(
        catalog=_catalog_fixture.__wrapped__(),
        corpus=corpus,
        proposals=proposals,
        existing_entities=_existing(),
        policy=_policy(),
    )

    assert resolution.model_attempted_count == 2
    assert resolution.model_execution_receipt_sha256s == tuple(
        sorted((first.execution_receipt_sha256, second.execution_receipt_sha256))
    )
    assert all(
        "MODEL_RECEIPT_INVALID" not in decision.reason_codes for decision in resolution.decisions
    )


def test_multi_origin_receipts_keep_their_original_corpus_input_hashes():
    corpus, proposals, first, second = _two_origin_fixture()
    entries = {entry.material_id: entry for entry in corpus.entries}

    assert not g._valid_model_receipt(first, corpus, entries)
    assert not g._valid_model_receipt(second, corpus, entries)
    assert g._valid_model_receipt_requests(proposals, corpus, entries) == {
        first.request_sha256,
        second.request_sha256,
    }


def test_receipt_origin_groups_reject_overlapping_material_scope():
    corpus, proposals, first, second = _two_origin_fixture()
    overlap = second.model_copy(
        update={"material_bindings": first.material_bindings},
    )
    proposals = _proposal_batch(
        corpus,
        tuple(sorted((first, overlap), key=lambda row: row.request_sha256)),
        proposals.proposals,
    )
    entries = {entry.material_id: entry for entry in corpus.entries}

    assert g._valid_model_receipt_requests(proposals, corpus, entries) == set()


def test_single_origin_receipt_validation_is_unchanged():
    entry = _entry(
        material_id="single-origin",
        text="平安保险 平安安心医疗保险 产品代码 SINGLE 登记编号 REG-S 版本 2026 医疗保险 官方条款",
    )
    corpus = _corpus(entry)
    receipt = _model_binding(corpus, entry)
    proposals = _proposal_batch(
        corpus,
        (receipt,),
        (
            _material_proposal(
                entry,
                receipt,
                entities=(
                    {
                        "proposal_ref": "main",
                        "name": "平安安心医疗保险",
                        "product_code": "SINGLE",
                        "filing": "REG-S",
                    },
                ),
            ),
        ),
    )
    entries = {entry.material_id: entry for entry in corpus.entries}

    assert g._valid_model_receipt_requests(proposals, corpus, entries) == {receipt.request_sha256}
    invalid = receipt.model_copy(update={"input_sha256": "f" * 64})
    invalid_proposals = _proposal_batch(corpus, (invalid,), proposals.proposals)
    assert g._valid_model_receipt_requests(invalid_proposals, corpus, entries) == set()


def test_single_origin_partial_receipt_keeps_full_corpus_binding():
    first = _entry(
        material_id="partial-a",
        text=(
            "平安保险 平安安心医疗保险 产品代码 PARTIAL-A 登记编号 REG-A "
            "版本 2026 医疗保险 官方条款"
        ),
    )
    second = _entry(
        material_id="partial-b",
        text=(
            "平安保险 平安安心医疗保险 产品代码 PARTIAL-B 登记编号 REG-B "
            "版本 2026 医疗保险 官方条款"
        ),
    )
    corpus = _corpus(first, second)
    successful = _model_binding(corpus, first)
    proposals = _proposal_batch(corpus, (successful,), ())
    entries = {entry.material_id: entry for entry in corpus.entries}

    assert g._valid_model_receipt(successful, corpus, entries)
    assert g._valid_model_receipt_requests(proposals, corpus, entries) == {
        successful.request_sha256
    }


def test_origin_group_uses_all_call_material_bindings_for_its_corpus():
    entries = tuple(
        _entry(
            material_id=f"group-{suffix}",
            text=f"平安保险 医疗保险 官方条款 {suffix}",
        )
        for suffix in ("a", "b", "c")
    )
    first_origin = _corpus(*entries[:2])
    second_origin = _corpus(entries[2])
    first = _model_binding(first_origin, entries[0])
    second = _model_binding(first_origin, entries[1]).model_copy(
        update={"policy_receipt": first.policy_receipt}
    )
    third = _model_binding(second_origin, entries[2])
    merged = _corpus(*entries)
    proposals = _proposal_batch(
        merged,
        tuple(sorted((first, second, third), key=lambda row: row.request_sha256)),
        (),
    )
    entry_index = {entry.material_id: entry for entry in merged.entries}

    assert g._valid_model_receipt_requests(proposals, merged, entry_index) == {
        first.request_sha256,
        second.request_sha256,
        third.request_sha256,
    }
