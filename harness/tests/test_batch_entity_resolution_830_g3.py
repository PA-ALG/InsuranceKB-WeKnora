from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from insurance_harness.knowledge_compiler import batch_entity_resolution_830_g3 as g
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    Evidence,
    SourceBlock,
    evidence_for,
)
from insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3 import (
    SchemaPackCatalogV1,
    compile_catalog,
)
from insurance_harness.knowledge_compiler.schema_wiki_candidate_evidence_join_596_1 import (
    LiveRevisionSourceReceiptV1,
    knowledge_revision_source_id,
    live_revision_source_receipt_sha256,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import schema_wiki_sha256
from insurance_harness.model_policy.models import (
    ModelIdentity,
    ModelPermitView,
    PolicyReceipt,
    _model_permit_view_digest,
)

_REPO = Path(__file__).parents[2]
_WORKBOOK = (
    _REPO
    / "docs/insurance-kb/evidence/830-b0/inputs"
    / "【汇总】11类保险产品知识Schema_全局一致性校验更新版_20260812-v5.xlsx"
)
_CONFIG = _REPO / "docs/insurance-kb/evidence/830-g3/profile-mapping-config.json"
_HASH_COUNTER = count(1)


def _hash() -> str:
    return hashlib.sha256(f"fixture-hash-{next(_HASH_COUNTER)}".encode()).hexdigest()


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_computed_fields=True)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _new(model: type[Any], object_type: str, hash_field: str, **values: object) -> Any:
    payload = {key: _jsonable(value) for key, value in values.items()}
    return model(**values, **{hash_field: schema_wiki_sha256(object_type, payload)})


@pytest.fixture(scope="module")
def catalog() -> SchemaPackCatalogV1:
    mapping = json.loads(_CONFIG.read_text(encoding="utf-8"))
    return compile_catalog(_WORKBOOK.read_bytes(), mapping)


def _receipt(*, material_id: str, text: str) -> LiveRevisionSourceReceiptV1:
    file_sha = hashlib.sha256((material_id + "-file").encode()).hexdigest()
    values: dict[str, object] = {
        "contract": "live-revision-source-receipt.v1",
        "revision_source_id": "",
        "tenant_id": 7,
        "space_id": "space-g3",
        "raw_kb_id": "raw-g3",
        "wiki_kb_id": "wiki-g3",
        "knowledge_id": f"knowledge-{material_id}",
        "evidence_parse_attempt_id": f"parse-{material_id}",
        "weknora_parse_attempt": 2,
        "resource_id": f"resource-{material_id}",
        "file_sha256": file_sha,
        "size": len(text.encode()),
        "mime_type": "application/pdf",
        "page_count": 1,
        "parsed_document_sha256": hashlib.sha256((material_id + "-parsed").encode()).hexdigest(),
        "parse_manifest_sha256": hashlib.sha256(
            (material_id + "-parse-manifest").encode()
        ).hexdigest(),
        "weknora_manifest_algorithm": "weknora.chunk_manifest.v1",
        "weknora_manifest_digest": hashlib.sha256((material_id + "-chunks").encode()).hexdigest(),
        "weknora_chunk_count": 1,
        "source_receipt_sha256": "0" * 64,
    }
    values["revision_source_id"] = knowledge_revision_source_id(
        tenant_id=7,
        knowledge_id=str(values["knowledge_id"]),
        weknora_parse_attempt=2,
        resource_id=str(values["resource_id"]),
        file_sha256=file_sha,
        size=int(values["size"]),
        mime_type="application/pdf",
    )
    values["source_receipt_sha256"] = live_revision_source_receipt_sha256(values)
    return LiveRevisionSourceReceiptV1.model_validate(values)


def _entry(*, material_id: str, text: str) -> g.CorpusEntryV1:
    receipt = _receipt(material_id=material_id, text=text)
    parser = hashlib.sha256((material_id + "-parser").encode()).hexdigest()
    block = SourceBlock(
        tenant_id=receipt.tenant_id,
        space_id=receipt.space_id,
        raw_kb_id=receipt.raw_kb_id,
        knowledge_id=receipt.knowledge_id,
        parse_attempt=receipt.weknora_parse_attempt,
        revision_id=receipt.revision_source_id,
        source_hash=receipt.file_sha256,
        parse_hash=receipt.weknora_manifest_digest,
        parser_identity=parser,
        block_id=f"block-{material_id}",
        page_number=1,
        text=text,
        source_type="DOCUMENT",
    )
    provenance = _new(
        g.SourceProvenanceV1,
        "source-provenance.830.g3.v1",
        "declaration_sha256",
        provenance_id=f"provenance-{material_id}",
        kind="official_public_document",
        source_uri=f"urn:fixture:{material_id}",
        acquisition_receipt_sha256=hashlib.sha256((material_id + "-acquire").encode()).hexdigest(),
        declared_by="fixture-ingestion",
    )
    return _new(
        g.CorpusEntryV1,
        "corpus-entry.830.g3.v1",
        "entry_sha256",
        material_id=material_id,
        receipt=receipt,
        native_capture_sha256=hashlib.sha256((material_id + "-native").encode()).hexdigest(),
        parser_identity_sha256=parser,
        blocks=(block,),
        provenance=provenance,
    )


def _corpus(*entries: g.CorpusEntryV1) -> g.BatchCorpusV1:
    return _new(
        g.BatchCorpusV1,
        "batch-corpus.830.g3.v1",
        "corpus_sha256",
        contract="batch-corpus.830.g3.v1",
        tenant_id=7,
        space_id="space-g3",
        raw_kb_id="raw-g3",
        wiki_kb_id="wiki-g3",
        entries=entries,
    )


def _policy_receipt(
    *,
    space_id: str = "space-g3",
    decision: str = "ALLOW",
    purpose: str = "g3-batch-resolution",
    run_schema_version: str = "830-g3-v1",
    role: str = "classify",
) -> PolicyReceipt:
    now = datetime(2026, 9, 7, tzinfo=UTC)
    identity = ModelIdentity(
        provider="fixture-provider",
        deployment_id="fixture-classifier",
        family="deepseek",
        role=role,
        policy_version="fixture-policy-v1",
    )
    if decision == "DENY":
        return PolicyReceipt(
            decision="DENY",
            reason_code="space_id_mismatch",
            identity_key=identity.identity_key,
            purpose=purpose,
            run_schema_version=run_schema_version,
            space_id=space_id,
            run_id="run-g3",
            run_revision="revision-g3",
            admission_hash=_hash(),
            request_digest=_hash(),
            binding_digest=_hash(),
            verified_binding_digest=_hash(),
            template_hash=_hash(),
            model_plan_hash=_hash(),
            call_scope_hash=_hash(),
            attempted_context_digest=_hash(),
            policy_snapshot_digest=_hash(),
            evaluated_at=now,
        )
    permit = ModelPermitView(
        identity=identity,
        purpose=purpose,
        run_schema_version=run_schema_version,
        space_id=space_id,
        run_id="run-g3",
        run_revision="revision-g3",
        admission_hash=_hash(),
        verified_binding_digest=_hash(),
        template_hash=_hash(),
        model_plan_hash=_hash(),
        policy_snapshot_digest=_hash(),
        call_scope_hash=_hash(),
        expires_at=now + timedelta(hours=1),
    )
    return PolicyReceipt(
        decision="ALLOW",
        reason_code="policy_allowed",
        identity_key=identity.identity_key,
        purpose=permit.purpose,
        run_schema_version=permit.run_schema_version,
        space_id=permit.space_id,
        run_id=permit.run_id,
        run_revision=permit.run_revision,
        admission_hash=permit.admission_hash,
        request_digest=_hash(),
        binding_digest=_hash(),
        verified_binding_digest=permit.verified_binding_digest,
        template_hash=permit.template_hash,
        model_plan_hash=permit.model_plan_hash,
        call_scope_hash=permit.call_scope_hash,
        attempted_context_digest=_hash(),
        policy_snapshot_digest=permit.policy_snapshot_digest,
        permit_digest=_model_permit_view_digest(permit),
        permit_view=permit,
        evaluated_at=now,
    )


def _model_binding(
    corpus: g.BatchCorpusV1,
    *entries: g.CorpusEntryV1,
    valid: bool = True,
    purpose: str = "g3-batch-resolution",
    run_schema_version: str = "830-g3-v1",
    role: str = "classify",
) -> g.ModelReceiptBindingV1:
    bindings = tuple(
        g.MaterialBindingV1(material_id=item.material_id, corpus_entry_sha256=item.entry_sha256)
        for item in entries
    )
    request_sha = hashlib.sha256(
        b"request:" + b"|".join(item.material_id.encode() for item in entries)
    ).hexdigest()
    input_sha = schema_wiki_sha256(
        "batch-classifier-input.830.g3.v1",
        {
            "corpus_sha256": corpus.corpus_sha256,
            "material_bindings": [item.model_dump(mode="json") for item in bindings],
        },
    )
    return g.ModelReceiptBindingV1(
        policy_receipt=_policy_receipt(
            decision="ALLOW" if valid else "DENY",
            purpose=purpose,
            run_schema_version=run_schema_version,
            role=role,
        ),
        material_bindings=bindings,
        request_sha256=request_sha,
        input_sha256=input_sha,
        raw_output_sha256=hashlib.sha256((request_sha + "-output").encode()).hexdigest(),
        execution_receipt_sha256=hashlib.sha256((request_sha + "-execution").encode()).hexdigest(),
    )


def _span(block: SourceBlock, quote: str) -> Evidence:
    start = block.text.index(quote)
    return evidence_for(block, start, start + len(quote))


def _proposal_evidence(
    *, block: SourceBlock, evidence_id: str, proposal_ref: str | None, purpose: str, quote: str
) -> g.ProposalEvidenceV1:
    return g.ProposalEvidenceV1(
        evidence_id=evidence_id,
        entity_proposal_ref=proposal_ref,
        purpose=purpose,
        field_key=None,
        evidence=_span(block, quote),
    )


def _material_proposal(
    entry: g.CorpusEntryV1,
    receipt: g.ModelReceiptBindingV1,
    *,
    entities: tuple[dict[str, object], ...],
    role: str = "terms",
    tamper_entry_hash: bool = False,
) -> g.MaterialProposalV1:
    block = entry.blocks[0]
    evidence: list[g.ProposalEvidenceV1] = [
        _proposal_evidence(
            block=block,
            evidence_id=f"{entry.material_id}-role",
            proposal_ref=None,
            purpose="material_role",
            quote="官方条款",
        )
    ]
    entity_models: list[g.EntityProposalV1] = []
    for row in entities:
        ref = str(row["proposal_ref"])
        values = {
            "issuer": row.get("issuer", "平安保险"),
            "name": row.get("name"),
            "product_code": row.get("product_code"),
            "version_label": row.get("version_label", "2026"),
            "filing": row.get("filing", "REG001"),
            "label": row.get("label", "medical_insurance"),
        }
        ids: dict[str, str] = {}
        identity_fields = (
            ("issuer", "issuer"),
            ("name", "name"),
            ("product_code", "product_code"),
            ("version", "version_label"),
        )
        for purpose, key in identity_fields:
            value = values[key]
            if value is not None:
                evidence_id = f"{entry.material_id}-{ref}-{purpose}"
                ids[purpose] = evidence_id
                evidence.append(
                    _proposal_evidence(
                        block=block,
                        evidence_id=evidence_id,
                        proposal_ref=ref,
                        purpose=purpose,
                        quote=str(value),
                    )
                )
        if values["filing"] is not None:
            evidence_id = f"{entry.material_id}-{ref}-filing"
            ids["filing"] = evidence_id
            evidence.append(
                _proposal_evidence(
                    block=block,
                    evidence_id=evidence_id,
                    proposal_ref=ref,
                    purpose="version",
                    quote=str(values["filing"]),
                )
            )
        date_ids: list[str] = []
        for date_key in ("valid_from", "valid_through"):
            date_value = row.get(date_key)
            if date_value is None:
                continue
            evidence_id = f"{entry.material_id}-{ref}-{date_key}"
            date_ids.append(evidence_id)
            evidence.append(
                _proposal_evidence(
                    block=block,
                    evidence_id=evidence_id,
                    proposal_ref=ref,
                    purpose="version",
                    quote=str(date_value),
                )
            )
        classification_id = f"{entry.material_id}-{ref}-classification"
        evidence.append(
            _proposal_evidence(
                block=block,
                evidence_id=classification_id,
                proposal_ref=ref,
                purpose="classification",
                quote="医疗保险" if values["label"] == "medical_insurance" else "重大疾病保险",
            )
        )
        entity_models.append(
            g.EntityProposalV1(
                proposal_ref=ref,
                issuer=values["issuer"],
                name=values["name"],
                product_code=values["product_code"],
                version_label=values["version_label"],
                filing_or_registration=(
                    None
                    if values["filing"] is None
                    else g.VersionAnchorV1(kind="registration_number", value=values["filing"])
                ),
                identity_confidence=str(row.get("identity_confidence", "0.990000")),
                identity_evidence_ids=tuple(sorted((*ids.values(), *date_ids))),
                labels=(
                    g.LabelProposalV1(
                        taxonomy_label=str(values["label"]),
                        confidence=str(row.get("classification_confidence", "0.990000")),
                        evidence_ids=(classification_id,),
                    ),
                ),
                primary_label=str(values["label"]),
                valid_from=row.get("valid_from"),
                valid_through=row.get("valid_through"),
            )
        )
    values = {
        "material_id": entry.material_id,
        "corpus_entry_sha256": "0" * 64 if tamper_entry_hash else entry.entry_sha256,
        "model_request_sha256": receipt.request_sha256,
        "material_role": role,
        "material_role_evidence_ids": (f"{entry.material_id}-role",),
        "entities": tuple(entity_models),
        "evidence": tuple(sorted(evidence, key=lambda item: item.evidence_id)),
    }
    return _new(
        g.MaterialProposalV1,
        "material-proposal.830.g3.v1",
        "proposal_sha256",
        **values,
    )


def _proposal_batch(
    corpus: g.BatchCorpusV1,
    receipts: tuple[g.ModelReceiptBindingV1, ...],
    proposals: tuple[g.MaterialProposalV1, ...],
) -> g.ProposalBatchV1:
    return _new(
        g.ProposalBatchV1,
        "batch-identity-proposals.830.g3.v1",
        "proposals_sha256",
        contract="batch-identity-proposals.830.g3.v1",
        corpus_sha256=corpus.corpus_sha256,
        model_receipts=receipts,
        proposals=proposals,
    )


def _existing(*entities: g.ExistingEntityV1) -> g.ExistingEntitySnapshotV1:
    return _new(
        g.ExistingEntitySnapshotV1,
        "existing-entities.830.g3.v1",
        "snapshot_sha256",
        contract="existing-entities.830.g3.v1",
        tenant_id=7,
        space_id="space-g3",
        raw_kb_id="raw-g3",
        wiki_kb_id="wiki-g3",
        base_release_id="release-base",
        base_activation_epoch=4,
        head_receipt_sha256="a" * 64,
        resolver_version="resolver-v1",
        resolver_policy_sha256="b" * 64,
        entities=entities,
    )


def _policy() -> g.BatchResolutionPolicyV1:
    rule = g.TrustRuleV1(
        rule_id="official-identity",
        provenance_kinds=("official_public_document",),
        material_roles=("terms",),
        purposes=("classification", "issuer", "material_role", "name", "product_code", "version"),
        field_keys=(),
        space_ids=("space-g3",),
        product_version_anchors=(),
        validity_mode="identity_only",
        valid_from=None,
        valid_through=None,
        priority=100,
    )
    return _new(
        g.BatchResolutionPolicyV1,
        "batch-resolution-policy.830.g3.v1",
        "policy_sha256",
        contract="batch-resolution-policy.830.g3.v1",
        policy_id="g3-fixture-policy",
        policy_version="v1",
        taxonomy_id="insurance-products",
        taxonomy_version="v1",
        identity_threshold="0.950000",
        classification_threshold="0.900000",
        queue_id="queue-g3",
        queue_owner="product-owner-g3",
        auto_candidate_requires=(
            "code",
            "dual_threshold",
            "evidence",
            "issuer",
            "name",
            "no_conflict",
            "unique_key",
            "version",
        ),
        rules=(rule,),
    )


def _policy_without_purpose(excluded: str) -> g.BatchResolutionPolicyV1:
    original = _policy()
    original_rule = original.rules[0]
    rule = g.TrustRuleV1(
        **original_rule.model_dump(mode="python", exclude={"purposes"}),
        purposes=tuple(item for item in original_rule.purposes if item != excluded),
    )
    return _new(
        g.BatchResolutionPolicyV1,
        "batch-resolution-policy.830.g3.v1",
        "policy_sha256",
        **original.model_dump(mode="python", exclude={"rules", "policy_sha256"}),
        rules=(rule,),
    )


def _interval_policy(*, valid_from: str, valid_through: str | None) -> g.BatchResolutionPolicyV1:
    rule = g.TrustRuleV1(
        rule_id="official-interval",
        provenance_kinds=("official_public_document",),
        material_roles=("terms",),
        purposes=("classification", "issuer", "material_role", "name", "product_code", "version"),
        field_keys=(),
        space_ids=("space-g3",),
        product_version_anchors=(),
        validity_mode="interval",
        valid_from=valid_from,
        valid_through=valid_through,
        priority=100,
    )
    return _new(
        g.BatchResolutionPolicyV1,
        "batch-resolution-policy.830.g3.v1",
        "policy_sha256",
        contract="batch-resolution-policy.830.g3.v1",
        policy_id="g3-interval-policy",
        policy_version="v1",
        taxonomy_id="insurance-products",
        taxonomy_version="v1",
        identity_threshold="0.950000",
        classification_threshold="0.900000",
        queue_id="queue-g3",
        queue_owner="product-owner-g3",
        auto_candidate_requires=(
            "code",
            "dual_threshold",
            "evidence",
            "issuer",
            "name",
            "no_conflict",
            "unique_key",
            "version",
        ),
        rules=(rule,),
    )


def _resolve(
    catalog: SchemaPackCatalogV1,
    entries: tuple[g.CorpusEntryV1, ...],
    entity_rows: tuple[tuple[dict[str, object], ...], ...],
    *,
    existing: g.ExistingEntitySnapshotV1 | None = None,
    valid_receipt: bool = True,
) -> g.BatchEntityResolutionV1:
    corpus = _corpus(*entries)
    receipt = _model_binding(corpus, *entries, valid=valid_receipt)
    proposals = tuple(
        _material_proposal(entry, receipt, entities=rows)
        for entry, rows in zip(entries, entity_rows, strict=True)
    )
    return g.resolve_batch(
        catalog=catalog,
        corpus=corpus,
        proposals=_proposal_batch(corpus, (receipt,), proposals),
        existing_entities=_existing() if existing is None else existing,
        policy=_policy(),
    )


def test_high_confidence_exact_evidence_creates_only_not_active_candidate(
    catalog: SchemaPackCatalogV1,
) -> None:
    text = "平安保险 平安安心医疗保险 产品代码 MED001 登记编号 REG001 版本 2026 医疗保险 官方条款"
    result = _resolve(
        catalog,
        (_entry(material_id="m1", text=text),),
        (
            (
                {
                    "proposal_ref": "product-main",
                    "name": "平安安心医疗保险",
                    "product_code": "MED001",
                },
            ),
        ),
    )

    decision = result.decisions[0]
    child = decision.children[0]
    assert decision.disposition == child.disposition == "CREATE"
    assert child.matched_entity_id is None and child.matched_entity_version is None
    assert child.entity_candidate is not None
    assert child.entity_candidate.status == "NOT_ACTIVE"
    normalized_code = "MED001"
    entity_key = schema_wiki_sha256(
        "entity-candidate-key.830.g3.v1",
        {"space_id": "space-g3", "product_code": normalized_code},
    )
    version_key = schema_wiki_sha256(
        "entity-version-candidate-key.830.g3.v1",
        {
            "entity_key_sha256": entity_key,
            "version_label": "2026",
            "version_anchor": {"kind": "registration_number", "value": "REG001"},
        },
    )
    assert child.entity_candidate.entity_key_sha256 == entity_key
    assert child.entity_candidate.version_candidate_key_sha256 == version_key
    assert child.entity_candidate.candidate_id == "entity_candidate_" + version_key
    assert child.classification.schema_pack_id == "schemapack_medical_insurance"
    assert child.multi_identity_name_evidence_ids == ("m1-product-main-name",)
    assert child.multi_identity_code_evidence_ids == ("m1-product-main-product_code",)
    assert result.material_count == result.resolution_decision_count == 1
    assert result.model_attempted_count == 1
    assert result.disposition_counts.model_dump() == {
        "MATCH": 0,
        "CREATE": 1,
        "MULTI": 0,
        "NEEDS_CONFIRM": 0,
        "QUARANTINE": 0,
    }
    assert g.validate_batch(result.model_dump_json()) == result


def test_exact_existing_match_preserves_serving_ids_and_issuer_vetoes_reuse(
    catalog: SchemaPackCatalogV1,
) -> None:
    text = "平安保险 平安安心医疗保险 产品代码 MED001 登记编号 REG001 版本 2026 医疗保险 官方条款"
    entry = _entry(material_id="m1", text=text)
    existing = g.ExistingEntityV1(
        entity_id="serving-entity-42",
        entity_version="serving-version-9",
        product_id="product-42",
        product_version_id="product-version-9",
        issuer="平安保险",
        name="平安安心医疗保险",
        product_code="MED001",
        version_label="2026",
        filing_or_registration=g.VersionAnchorV1(kind="registration_number", value="REG001"),
        approved_aliases=(),
        identity_evidence_sha256s=("c" * 64,),
    )
    matched = (
        _resolve(
            catalog,
            (entry,),
            (({"proposal_ref": "p", "name": "平安安心医疗保险", "product_code": "MED001"},),),
            existing=_existing(existing),
        )
        .decisions[0]
        .children[0]
    )
    assert matched.disposition == "MATCH"
    assert (matched.matched_entity_id, matched.matched_entity_version) == (
        "serving-entity-42",
        "serving-version-9",
    )
    assert matched.entity_candidate is None

    conflicting_entry = _entry(
        material_id="issuer-conflict",
        text=(
            "其他保险 平安安心医疗保险 产品代码 MED001 登记编号 REG001 版本 2026 医疗保险 官方条款"
        ),
    )
    conflicting = (
        _resolve(
            catalog,
            (conflicting_entry,),
            (
                (
                    {
                        "proposal_ref": "p",
                        "issuer": "其他保险",
                        "name": "平安安心医疗保险",
                        "product_code": "MED001",
                    },
                ),
            ),
            existing=_existing(existing),
        )
        .decisions[0]
        .children[0]
    )
    assert conflicting.disposition == "QUARANTINE"
    assert "IDENTITY_ANCHOR_CONFLICT" in conflicting.reason_codes
    assert conflicting.multi_identity_name_evidence_ids == ()
    assert conflicting.multi_identity_code_evidence_ids == ()


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"product_code": None}, "IDENTITY_EVIDENCE_MISSING"),
        ({"identity_confidence": "0.949999"}, "IDENTITY_BELOW_THRESHOLD"),
        ({"classification_confidence": "0.899999"}, "CLASSIFICATION_BELOW_THRESHOLD"),
    ],
)
def test_name_only_and_each_low_threshold_stay_human(
    catalog: SchemaPackCatalogV1,
    changes: dict[str, object],
    reason: str,
) -> None:
    text = "平安保险 平安安心医疗保险 产品代码 MED001 登记编号 REG001 版本 2026 医疗保险 官方条款"
    row: dict[str, object] = {
        "proposal_ref": "p",
        "name": "平安安心医疗保险",
        "product_code": "MED001",
    }
    row.update(changes)
    child = (
        _resolve(catalog, (_entry(material_id="m1", text=text),), ((row,),))
        .decisions[0]
        .children[0]
    )
    assert child.disposition == "NEEDS_CONFIRM"
    assert reason in child.reason_codes
    assert child.queue_owner == "product-owner-g3"


def test_multi_clusters_children_and_never_shares_identity_evidence(
    catalog: SchemaPackCatalogV1,
) -> None:
    text = (
        "平安保险 主合同医疗保险 产品代码 MED001 登记编号 REG001 版本 2026 医疗保险 "
        "平安保险 附加重大疾病保险 产品代码 CI002 登记编号 REG002 版本 2026 重大疾病保险 官方条款"
    )
    result = _resolve(
        catalog,
        (_entry(material_id="multi", text=text),),
        (
            (
                {
                    "proposal_ref": "main",
                    "name": "主合同医疗保险",
                    "product_code": "MED001",
                    "filing": "REG001",
                },
                {
                    "proposal_ref": "rider",
                    "name": "附加重大疾病保险",
                    "product_code": "CI002",
                    "filing": "REG002",
                    "label": "critical_illness_insurance",
                },
            ),
        ),
    )
    parent = result.decisions[0]
    assert parent.disposition == "MULTI"
    assert len(parent.children) == 2
    assert all(child.disposition == "CREATE" for child in parent.children)
    assert set(parent.children[0].evidence_ids).isdisjoint(parent.children[1].evidence_ids)
    assert "MULTI_ENTITY_REVIEW" in parent.reason_codes


def test_multi_identity_clusters_survive_missing_versions_and_shared_issuer(
    catalog: SchemaPackCatalogV1,
) -> None:
    entry = _entry(
        material_id="multi-missing-version",
        text=(
            "平安保险 产品甲 产品代码 A-CODE 产品乙 产品代码 B-CODE "
            "版本 2026 医疗保险 官方条款"
        ),
    )
    result = _resolve(
        catalog,
        (entry,),
        (
            (
                {
                    "proposal_ref": "a",
                    "name": "产品甲",
                    "product_code": "A-CODE",
                    "filing": None,
                },
                {
                    "proposal_ref": "b",
                    "name": "产品乙",
                    "product_code": "B-CODE",
                    "filing": None,
                },
            ),
        ),
    )
    parent = result.decisions[0]
    assert parent.disposition == "MULTI"
    assert "MULTI_ENTITY_REVIEW" in parent.reason_codes
    assert all(child.disposition == "NEEDS_CONFIRM" for child in parent.children)
    assert all(child.entity_candidate is None for child in parent.children)
    assert all("VERSION_UNRESOLVED" in child.reason_codes for child in parent.children)
    assert tuple(
        child.multi_identity_name_evidence_ids for child in parent.children
    ) == (("multi-missing-version-a-name",), ("multi-missing-version-b-name",))
    assert tuple(
        child.multi_identity_code_evidence_ids for child in parent.children
    ) == (("multi-missing-version-a-product_code",), ("multi-missing-version-b-product_code",))


def test_multi_identity_clusters_ignore_classification_failure_and_missing_issuer(
    catalog: SchemaPackCatalogV1,
) -> None:
    entry = _entry(
        material_id="multi-classification",
        text=(
            "产品甲 产品代码 A-CODE 产品乙 产品代码 B-CODE "
            "版本 2026 医疗保险 官方条款"
        ),
    )
    result = _resolve(
        catalog,
        (entry,),
        (
            (
                {
                    "proposal_ref": "a",
                    "issuer": None,
                    "name": "产品甲",
                    "product_code": "A-CODE",
                    "filing": None,
                    "classification_confidence": "0.100000",
                },
                {
                    "proposal_ref": "b",
                    "issuer": None,
                    "name": "产品乙",
                    "product_code": "B-CODE",
                    "filing": None,
                    "classification_confidence": "0.100000",
                },
            ),
        ),
    )
    parent = result.decisions[0]
    assert parent.disposition == "MULTI"
    assert all(child.disposition == "NEEDS_CONFIRM" for child in parent.children)
    assert all("CLASSIFICATION_BELOW_THRESHOLD" in child.reason_codes for child in parent.children)
    assert all(child.multi_identity_name_evidence_ids for child in parent.children)
    assert all(child.multi_identity_code_evidence_ids for child in parent.children)


def test_multi_identity_clusters_survive_unmapped_classification(
    catalog: SchemaPackCatalogV1,
) -> None:
    entry = _entry(
        material_id="multi-unmapped-classification",
        text=(
            "平安保险 产品甲 产品代码 A-CODE 产品乙 产品代码 B-CODE "
            "版本 2026 重大疾病保险 官方条款"
        ),
    )
    result = _resolve(
        catalog,
        (entry,),
        (
            (
                {
                    "proposal_ref": "a",
                    "name": "产品甲",
                    "product_code": "A-CODE",
                    "filing": None,
                    "label": "unmapped_classification",
                },
                {
                    "proposal_ref": "b",
                    "name": "产品乙",
                    "product_code": "B-CODE",
                    "filing": None,
                    "label": "unmapped_classification",
                },
            ),
        ),
    )
    parent = result.decisions[0]
    assert parent.disposition == "MULTI"
    assert all(child.disposition == "NEEDS_CONFIRM" for child in parent.children)
    assert all("CLASSIFICATION_UNRESOLVED" in child.reason_codes for child in parent.children)
    assert all(child.multi_identity_name_evidence_ids for child in parent.children)
    assert all(child.multi_identity_code_evidence_ids for child in parent.children)


def test_multi_identity_rejects_name_evidence_whose_quote_does_not_match_anchor(
    catalog: SchemaPackCatalogV1,
) -> None:
    entry = _entry(
        material_id="multi-wrong-name-quote",
        text=(
            "平安保险 产品甲 产品代码 A-CODE 产品乙 产品代码 B-CODE "
            "版本 2026 医疗保险 官方条款"
        ),
    )
    corpus = _corpus(entry)
    receipt = _model_binding(corpus, entry)
    proposal = _material_proposal(
        entry,
        receipt,
        entities=(
            {
                "proposal_ref": "a",
                "name": "产品甲",
                "product_code": "A-CODE",
                "filing": None,
            },
            {
                "proposal_ref": "b",
                "name": "产品乙",
                "product_code": "B-CODE",
                "filing": None,
            },
        ),
    )
    wrong_quote = _span(entry.blocks[0], "官方条款")
    evidence = tuple(
        g.ProposalEvidenceV1(
            **item.model_dump(mode="python", exclude={"evidence"}),
            evidence=(
                wrong_quote
                if item.evidence_id == "multi-wrong-name-quote-a-name"
                else item.evidence
            ),
        )
        for item in proposal.evidence
    )
    proposal = _new(
        g.MaterialProposalV1,
        "material-proposal.830.g3.v1",
        "proposal_sha256",
        **proposal.model_dump(mode="python", exclude={"evidence", "proposal_sha256"}),
        evidence=evidence,
    )
    result = g.resolve_batch(
        catalog=catalog,
        corpus=corpus,
        proposals=_proposal_batch(corpus, (receipt,), (proposal,)),
        existing_entities=_existing(),
        policy=_policy(),
    )
    parent = result.decisions[0]
    assert parent.disposition == "NEEDS_CONFIRM"
    first, second = parent.children
    assert first.multi_identity_name_evidence_ids == ()
    assert first.multi_identity_code_evidence_ids
    assert second.multi_identity_name_evidence_ids
    assert second.multi_identity_code_evidence_ids


def test_multi_identity_aliases_at_one_locator_do_not_create_independent_clusters(
    catalog: SchemaPackCatalogV1,
) -> None:
    entry = _entry(
        material_id="multi-same-locator",
        text=(
            "平安保险 产品甲 产品乙 产品代码 A-CODE B-CODE "
            "版本 2026 医疗保险 官方条款"
        ),
    )
    corpus = _corpus(entry)
    receipt = _model_binding(corpus, entry)
    proposal = _material_proposal(
        entry,
        receipt,
        entities=(
            {
                "proposal_ref": "a",
                "name": "产品甲",
                "product_code": "A-CODE",
                "filing": None,
            },
            {
                "proposal_ref": "b",
                "name": "产品乙",
                "product_code": "B-CODE",
                "filing": None,
            },
        ),
    )
    shared = {
        "name": _span(entry.blocks[0], "产品甲 产品乙"),
        "product_code": _span(entry.blocks[0], "A-CODE B-CODE"),
    }
    evidence = tuple(
        g.ProposalEvidenceV1(
            **item.model_dump(mode="python", exclude={"evidence"}),
            evidence=shared.get(item.purpose, item.evidence),
        )
        for item in proposal.evidence
    )
    proposal = _new(
        g.MaterialProposalV1,
        "material-proposal.830.g3.v1",
        "proposal_sha256",
        **proposal.model_dump(mode="python", exclude={"evidence", "proposal_sha256"}),
        evidence=evidence,
    )
    result = g.resolve_batch(
        catalog=catalog,
        corpus=corpus,
        proposals=_proposal_batch(corpus, (receipt,), (proposal,)),
        existing_entities=_existing(),
        policy=_policy(),
    )
    parent = result.decisions[0]
    assert parent.disposition == "NEEDS_CONFIRM"
    assert all(child.multi_identity_name_evidence_ids == () for child in parent.children)
    assert all(child.multi_identity_code_evidence_ids == () for child in parent.children)


@pytest.mark.parametrize(
    ("excluded_purpose", "expected_parent"),
    [("name", "NEEDS_CONFIRM"), ("version", "MULTI"), ("classification", "MULTI")],
)
def test_multi_identity_uses_name_code_trust_independently_from_other_purposes(
    catalog: SchemaPackCatalogV1,
    excluded_purpose: str,
    expected_parent: str,
) -> None:
    entry = _entry(
        material_id=f"multi-trust-{excluded_purpose}",
        text=(
            "平安保险 产品甲 产品代码 A-CODE 登记编号 A-REG 版本 2026 "
            "产品乙 产品代码 B-CODE 登记编号 B-REG 医疗保险 官方条款"
        ),
    )
    corpus = _corpus(entry)
    receipt = _model_binding(corpus, entry)
    proposal = _material_proposal(
        entry,
        receipt,
        entities=(
            {
                "proposal_ref": "a",
                "name": "产品甲",
                "product_code": "A-CODE",
                "filing": "A-REG",
            },
            {
                "proposal_ref": "b",
                "name": "产品乙",
                "product_code": "B-CODE",
                "filing": "B-REG",
            },
        ),
    )
    result = g.resolve_batch(
        catalog=catalog,
        corpus=corpus,
        proposals=_proposal_batch(corpus, (receipt,), (proposal,)),
        existing_entities=_existing(),
        policy=_policy_without_purpose(excluded_purpose),
    )
    parent = result.decisions[0]
    assert parent.disposition == expected_parent
    assert all(child.disposition == "NEEDS_CONFIRM" for child in parent.children)
    assert all("TRUST_POLICY_UNRESOLVED" in child.reason_codes for child in parent.children)
    if excluded_purpose == "name":
        assert all(child.multi_identity_name_evidence_ids == () for child in parent.children)
        assert all(child.multi_identity_code_evidence_ids for child in parent.children)
    else:
        assert all(child.multi_identity_name_evidence_ids for child in parent.children)
        assert all(child.multi_identity_code_evidence_ids for child in parent.children)


def test_cross_material_evidence_and_bad_model_binding_quarantine_without_dropping_denominator(
    catalog: SchemaPackCatalogV1,
) -> None:
    text1 = "平安保险 产品一 产品代码 A001 登记编号 RA001 版本 2026 医疗保险 官方条款"
    text2 = "平安保险 产品二 产品代码 B002 登记编号 RB002 版本 2026 医疗保险 官方条款"
    first, second = _entry(material_id="m1", text=text1), _entry(material_id="m2", text=text2)
    corpus = _corpus(first, second)
    receipt = _model_binding(corpus, first, second)
    p1 = _material_proposal(
        first,
        receipt,
        entities=(
            {
                "proposal_ref": "p1",
                "name": "产品一",
                "product_code": "A001",
                "filing": "RA001",
            },
        ),
    )
    p2 = _material_proposal(
        second,
        receipt,
        entities=(
            {
                "proposal_ref": "p2",
                "name": "产品二",
                "product_code": "B002",
                "filing": "RB002",
            },
        ),
    )
    wire = p2.model_dump(mode="python")
    foreign = p1.evidence[1]
    altered_evidence = list(wire["evidence"])
    altered_evidence[1] = foreign.model_copy(
        update={"evidence_id": p2.evidence[1].evidence_id, "entity_proposal_ref": "p2"}
    )
    wire["evidence"] = tuple(altered_evidence)
    wire.pop("proposal_sha256")
    p2 = _new(g.MaterialProposalV1, "material-proposal.830.g3.v1", "proposal_sha256", **wire)
    result = g.resolve_batch(
        catalog=catalog,
        corpus=corpus,
        proposals=_proposal_batch(corpus, (receipt,), (p1, p2)),
        existing_entities=_existing(),
        policy=_policy(),
    )
    assert result.material_count == result.resolution_decision_count == 2
    assert result.model_attempted_count == 2
    assert result.decisions[1].disposition == "QUARANTINE"
    assert "EVIDENCE_JOIN_FAILED" in result.decisions[1].children[0].reason_codes
    assert result.decisions[1].children[0].multi_identity_name_evidence_ids == ()
    assert result.decisions[1].children[0].multi_identity_code_evidence_ids == ()

    denied = _resolve(
        catalog,
        (first,),
        (({"proposal_ref": "p1", "name": "产品一", "product_code": "A001", "filing": "RA001"},),),
        valid_receipt=False,
    )
    assert denied.decisions[0].disposition == "QUARANTINE"
    assert denied.model_attempted_count == 0
    assert "MODEL_RECEIPT_INVALID" in denied.decisions[0].reason_codes
    assert denied.decisions[0].children[0].multi_identity_name_evidence_ids == ()
    assert denied.decisions[0].children[0].multi_identity_code_evidence_ids == ()


def test_no_output_is_attempted_only_when_valid_execution_bound_material(
    catalog: SchemaPackCatalogV1,
) -> None:
    entry = _entry(
        material_id="missing",
        text="平安保险 产品三 产品代码 C003 登记编号 RC003 版本 2026 医疗保险 官方条款",
    )
    corpus = _corpus(entry)
    receipt = _model_binding(corpus, entry)
    result = g.resolve_batch(
        catalog=catalog,
        corpus=corpus,
        proposals=_proposal_batch(corpus, (receipt,), ()),
        existing_entities=_existing(),
        policy=_policy(),
    )
    assert result.model_attempted_count == 1
    assert result.decisions[0].disposition == "NEEDS_CONFIRM"
    assert result.decisions[0].reason_codes == ("MODEL_OUTPUT_MISSING",)


def test_source_integrity_failure_quarantines_even_without_model_output(
    catalog: SchemaPackCatalogV1,
) -> None:
    original = _entry(
        material_id="bad-source",
        text="平安保险 产品四 产品代码 D004 登记编号 RD004 版本 2026 医疗保险 官方条款",
    )
    block = SourceBlock(
        **original.blocks[0].model_dump(exclude={"parse_hash"}),
        parse_hash="d" * 64,
    )
    entry_values = original.model_dump(mode="python", exclude={"entry_sha256"})
    entry_values["blocks"] = (block,)
    entry = _new(
        g.CorpusEntryV1,
        "corpus-entry.830.g3.v1",
        "entry_sha256",
        **entry_values,
    )
    corpus = _corpus(entry)
    receipt = _model_binding(corpus, entry)
    result = g.resolve_batch(
        catalog=catalog,
        corpus=corpus,
        proposals=_proposal_batch(corpus, (receipt,), ()),
        existing_entities=_existing(),
        policy=_policy(),
    )
    assert result.model_attempted_count == 1
    assert result.decisions[0].disposition == "QUARANTINE"
    assert result.decisions[0].reason_codes == (
        "MODEL_OUTPUT_MISSING",
        "SOURCE_RECEIPT_MISMATCH",
    )


def test_identity_evidence_cannot_borrow_material_role_scope(
    catalog: SchemaPackCatalogV1,
) -> None:
    entry = _entry(
        material_id="bad-evidence-role",
        text="平安保险 产品五 产品代码 E005 登记编号 RE005 版本 2026 医疗保险 官方条款",
    )
    corpus = _corpus(entry)
    receipt = _model_binding(corpus, entry)
    proposal = _material_proposal(
        entry,
        receipt,
        entities=(
            {
                "proposal_ref": "p",
                "name": "产品五",
                "product_code": "E005",
                "filing": "RE005",
            },
        ),
    )
    role_id = proposal.material_role_evidence_ids[0]
    borrowed = proposal.entities[0].model_copy(update={"identity_evidence_ids": (role_id,)})
    values = proposal.model_dump(mode="python", exclude={"proposal_sha256"})
    values["entities"] = (borrowed,)
    proposal = _new(
        g.MaterialProposalV1,
        "material-proposal.830.g3.v1",
        "proposal_sha256",
        **values,
    )
    result = g.resolve_batch(
        catalog=catalog,
        corpus=corpus,
        proposals=_proposal_batch(corpus, (receipt,), (proposal,)),
        existing_entities=_existing(),
        policy=_policy(),
    )
    child = result.decisions[0].children[0]
    assert child.disposition == "QUARANTINE"
    assert "EVIDENCE_JOIN_FAILED" in child.reason_codes


def test_same_key_multiple_versions_are_pre_grouped_and_same_version_reuses_candidate(
    catalog: SchemaPackCatalogV1,
) -> None:
    text1 = "平安保险 同名产品 产品代码 SAME1 登记编号 REG-A 版本 2025 医疗保险 官方条款"
    text2 = "平安保险 同名产品 产品代码 SAME1 登记编号 REG-B 版本 2026 医疗保险 官方条款"
    a, b = _entry(material_id="a", text=text1), _entry(material_id="b", text=text2)
    conflict = _resolve(
        catalog,
        (a, b),
        (
            (
                {
                    "proposal_ref": "a",
                    "name": "同名产品",
                    "product_code": "SAME1",
                    "version_label": "2025",
                    "filing": "REG-A",
                },
            ),
            (
                {
                    "proposal_ref": "b",
                    "name": "同名产品",
                    "product_code": "SAME1",
                    "version_label": "2026",
                    "filing": "REG-B",
                },
            ),
        ),
    )
    assert [item.disposition for item in conflict.decisions] == ["NEEDS_CONFIRM", "NEEDS_CONFIRM"]
    assert all("AMBIGUOUS_IDENTITY" in item.children[0].reason_codes for item in conflict.decisions)

    text2 = "平安保险 同名产品 产品代码 SAME1 登记编号 REG-A 版本 2025 医疗保险 官方条款"
    b = _entry(material_id="b", text=text2)
    reused = _resolve(
        catalog,
        (a, b),
        (
            (
                {
                    "proposal_ref": "a",
                    "name": "同名产品",
                    "product_code": "SAME1",
                    "version_label": "2025",
                    "filing": "REG-A",
                },
            ),
            (
                {
                    "proposal_ref": "b",
                    "name": "同名产品",
                    "product_code": "SAME1",
                    "version_label": "2025",
                    "filing": "REG-A",
                },
            ),
        ),
    )
    candidates = [item.children[0].entity_candidate for item in reused.decisions]
    assert candidates[0] == candidates[1]


def test_reclassification_changes_assignment_but_not_entity_identity(
    catalog: SchemaPackCatalogV1,
) -> None:
    base = (
        "平安保险 稳定产品 产品代码 KEEP1 登记编号 KEEP-REG "
        "版本 2026 医疗保险 重大疾病保险 官方条款"
    )
    entry = _entry(material_id="m1", text=base)
    medical = (
        _resolve(
            catalog,
            (entry,),
            (
                (
                    {
                        "proposal_ref": "p",
                        "name": "稳定产品",
                        "product_code": "KEEP1",
                        "filing": "KEEP-REG",
                    },
                ),
            ),
        )
        .decisions[0]
        .children[0]
    )
    critical = (
        _resolve(
            catalog,
            (entry,),
            (
                (
                    {
                        "proposal_ref": "p",
                        "name": "稳定产品",
                        "product_code": "KEEP1",
                        "filing": "KEEP-REG",
                        "label": "critical_illness_insurance",
                    },
                ),
            ),
        )
        .decisions[0]
        .children[0]
    )
    assert medical.entity_candidate is not None and critical.entity_candidate is not None
    assert medical.entity_candidate.candidate_id == critical.entity_candidate.candidate_id
    assert medical.entity_candidate.entity_key_sha256 == critical.entity_candidate.entity_key_sha256
    assert medical.classification.assignment_sha256 != critical.classification.assignment_sha256


def test_existing_entity_can_expose_multiple_versions_and_match_exact_one(
    catalog: SchemaPackCatalogV1,
) -> None:
    common = {
        "entity_id": "serving-entity-7",
        "product_id": "product-7",
        "product_version_id": None,
        "issuer": "平安保险",
        "name": "多版本产品",
        "product_code": "VERS7",
        "approved_aliases": (),
        "identity_evidence_sha256s": ("e" * 64,),
    }
    old = g.ExistingEntityV1(
        **common,
        entity_version="version-2025",
        version_label="2025",
        filing_or_registration=g.VersionAnchorV1(kind="registration_number", value="VERS-REG-2025"),
    )
    current = g.ExistingEntityV1(
        **common,
        entity_version="version-2026",
        version_label="2026",
        filing_or_registration=g.VersionAnchorV1(kind="registration_number", value="VERS-REG-2026"),
    )
    entry = _entry(
        material_id="existing-versions",
        text=(
            "平安保险 多版本产品 产品代码 VERS7 登记编号 VERS-REG-2026 版本 2026 医疗保险 官方条款"
        ),
    )
    child = (
        _resolve(
            catalog,
            (entry,),
            (
                (
                    {
                        "proposal_ref": "p",
                        "name": "多版本产品",
                        "product_code": "VERS7",
                        "version_label": "2026",
                        "filing": "VERS-REG-2026",
                    },
                ),
            ),
            existing=_existing(old, current),
        )
        .decisions[0]
        .children[0]
    )
    assert child.disposition == "MATCH"
    assert child.matched_entity_id == "serving-entity-7"
    assert child.matched_entity_version == "version-2026"


def test_validate_batch_and_input_contract_fail_closed_with_stable_errors(
    catalog: SchemaPackCatalogV1,
) -> None:
    text = "平安保险 平安安心医疗保险 产品代码 MED001 登记编号 REG001 版本 2026 医疗保险 官方条款"
    result = _resolve(
        catalog,
        (_entry(material_id="m1", text=text),),
        (({"proposal_ref": "p", "name": "平安安心医疗保险", "product_code": "MED001"},),),
    )
    tampered = result.model_dump(mode="json")
    tampered["material_count"] = 2
    with pytest.raises(g.BatchEntityResolutionError) as error:
        g.validate_batch(json.dumps(tampered, ensure_ascii=False))
    assert error.value.reason_code == "COMPILED_BATCH_INVALID"

    with pytest.raises(g.BatchEntityResolutionError) as error:
        g.validate_batch("{not-json")
    assert error.value.reason_code == "INPUT_CONTRACT_INVALID"

    duplicate = result.model_dump(mode="json")
    duplicate["decisions"].append(deepcopy(duplicate["decisions"][0]))
    duplicate["resolution_decision_count"] = 2
    duplicate["material_count"] = 2
    duplicate.pop("batch_sha256")
    duplicate["batch_sha256"] = schema_wiki_sha256("batch-entity-resolution.830.g3.v1", duplicate)
    with pytest.raises(g.BatchEntityResolutionError) as error:
        g.validate_batch(json.dumps(duplicate, ensure_ascii=False))
    assert error.value.reason_code == "COMPILED_BATCH_INVALID"

    inconsistent = result.model_dump(mode="json")
    material = inconsistent["decisions"][0]
    material["disposition"] = "MATCH"
    material["reason_codes"] = ["EXACT_EXISTING_MATCH"]
    material.pop("decision_sha256")
    material["decision_sha256"] = schema_wiki_sha256("material-decision.830.g3.v1", material)
    inconsistent.pop("batch_sha256")
    inconsistent["batch_sha256"] = schema_wiki_sha256(
        "batch-entity-resolution.830.g3.v1", inconsistent
    )
    with pytest.raises(g.BatchEntityResolutionError) as error:
        g.validate_batch(json.dumps(inconsistent, ensure_ascii=False))
    assert error.value.reason_code == "COMPILED_BATCH_INVALID"


def test_public_resolver_reports_duplicate_material_and_proposal_stably(
    catalog: SchemaPackCatalogV1,
) -> None:
    entry = _entry(
        material_id="duplicate",
        text="平安保险 重复产品 产品代码 DUP1 登记编号 DUP-REG 版本 2026 医疗保险 官方条款",
    )
    corpus = _corpus(entry)
    receipt = _model_binding(corpus, entry)
    proposal = _material_proposal(
        entry,
        receipt,
        entities=(
            {
                "proposal_ref": "p",
                "name": "重复产品",
                "product_code": "DUP1",
                "filing": "DUP-REG",
            },
        ),
    )
    proposal_batch = _proposal_batch(corpus, (receipt,), (proposal,))
    duplicate_corpus = g.BatchCorpusV1.model_construct(
        **corpus.model_dump(mode="python", exclude={"entries"}),
        entries=(entry, entry),
    )
    with pytest.raises(g.BatchEntityResolutionError) as error:
        g.resolve_batch(
            catalog=catalog,
            corpus=duplicate_corpus,
            proposals=proposal_batch,
            existing_entities=_existing(),
            policy=_policy(),
        )
    assert error.value.reason_code == "DUPLICATE_MATERIAL"

    duplicate_proposals = g.ProposalBatchV1.model_construct(
        **proposal_batch.model_dump(mode="python", exclude={"proposals"}),
        proposals=(proposal, proposal),
    )
    with pytest.raises(g.BatchEntityResolutionError) as error:
        g.resolve_batch(
            catalog=catalog,
            corpus=corpus,
            proposals=duplicate_proposals,
            existing_entities=_existing(),
            policy=_policy(),
        )
    assert error.value.reason_code == "DUPLICATE_PROPOSAL"


def test_proposal_batch_rejects_evidence_ids_reused_across_materials(
    catalog: SchemaPackCatalogV1,
) -> None:
    del catalog
    first = _entry(
        material_id="a",
        text="平安保险 产品甲 产品代码 A1 登记编号 RA1 版本 2026 医疗保险 官方条款",
    )
    second = _entry(
        material_id="b",
        text="平安保险 产品乙 产品代码 B1 登记编号 RB1 版本 2026 医疗保险 官方条款",
    )
    corpus = _corpus(first, second)
    receipt = _model_binding(corpus, first, second)
    first_proposal = _material_proposal(
        first,
        receipt,
        entities=(
            {
                "proposal_ref": "p",
                "name": "产品甲",
                "product_code": "A1",
                "filing": "RA1",
            },
        ),
    )
    second_proposal = _material_proposal(
        second,
        receipt,
        entities=(
            {
                "proposal_ref": "p",
                "name": "产品乙",
                "product_code": "B1",
                "filing": "RB1",
            },
        ),
    )
    wire_json = json.dumps(
        second_proposal.model_dump(mode="json", exclude={"proposal_sha256"}),
        ensure_ascii=False,
    ).replace('"b-', '"a-')
    reused_ids = json.loads(wire_json)
    second_proposal = _new(
        g.MaterialProposalV1,
        "material-proposal.830.g3.v1",
        "proposal_sha256",
        **reused_ids,
    )
    with pytest.raises(ValueError, match="batch unique"):
        _proposal_batch(corpus, (receipt,), (first_proposal, second_proposal))


def test_exact_same_inputs_are_idempotent(catalog: SchemaPackCatalogV1) -> None:
    entry = _entry(
        material_id="idempotent",
        text="平安保险 幂等产品 产品代码 IDEM1 登记编号 IDEM-REG 版本 2026 医疗保险 官方条款",
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
                        "proposal_ref": "p",
                        "name": "幂等产品",
                        "product_code": "IDEM1",
                        "filing": "IDEM-REG",
                    },
                ),
            ),
        ),
    )
    existing = _existing()
    policy = _policy()
    arguments = {
        "catalog": catalog,
        "corpus": corpus,
        "proposals": proposals,
        "existing_entities": existing,
        "policy": policy,
    }
    assert g.resolve_batch(**arguments) == g.resolve_batch(**arguments)


def test_confidence_and_strict_integer_contract_reject_float_bool_and_noncanonical_text() -> None:
    with pytest.raises(ValueError):
        g.LabelProposalV1(taxonomy_label="medical_insurance", confidence=0.95, evidence_ids=("e",))
    with pytest.raises(ValueError):
        g.LabelProposalV1(
            taxonomy_label="medical_insurance",
            confidence="0.95",
            evidence_ids=("e",),
        )
    with pytest.raises(ValueError):
        g.TrustRuleV1(
            rule_id="r",
            provenance_kinds=("official_public_document",),
            material_roles=("terms",),
            purposes=("issuer",),
            field_keys=(),
            space_ids=("space-g3",),
            product_version_anchors=(),
            validity_mode="identity_only",
            valid_from=None,
            valid_through=None,
            priority=True,
        )
    with pytest.raises(ValueError):
        g.VersionAnchorV1(kind="registration_number", value="e\u0301")
    assert g.VersionAnchorV1(kind="registration_number", value="A\nB").value == "A\nB"


@pytest.mark.parametrize("competition", ["name", "alias", "anchor"])
def test_existing_identity_competition_across_different_codes_stays_human(
    catalog: SchemaPackCatalogV1,
    competition: str,
) -> None:
    proposed_name = "竞争产品"
    proposed_anchor = "REG-COMPETE"
    existing = g.ExistingEntityV1(
        entity_id="serving-other-code",
        entity_version="version-other-code",
        product_id="product-other-code",
        product_version_id="product-version-other-code",
        issuer="平安保险",
        name=proposed_name if competition == "name" else "既有正式名称",
        product_code="OTHER-CODE",
        version_label="2025",
        filing_or_registration=g.VersionAnchorV1(
            kind="registration_number",
            value=proposed_anchor if competition == "anchor" else "REG-OTHER",
        ),
        approved_aliases=(
            (g.ApprovedAliasV1(value=proposed_name, approval_receipt_sha256="f" * 64),)
            if competition == "alias"
            else ()
        ),
        identity_evidence_sha256s=("e" * 64,),
    )
    entry = _entry(
        material_id=f"compete-{competition}",
        text=(
            f"平安保险 {proposed_name} 产品代码 NEW-CODE 登记编号 {proposed_anchor} "
            "版本 2026 医疗保险 官方条款"
        ),
    )
    child = (
        _resolve(
            catalog,
            (entry,),
            (
                (
                    {
                        "proposal_ref": "p",
                        "name": proposed_name,
                        "product_code": "NEW-CODE",
                        "filing": proposed_anchor,
                    },
                ),
            ),
            existing=_existing(existing),
        )
        .decisions[0]
        .children[0]
    )
    assert child.disposition == "NEEDS_CONFIRM"
    assert child.entity_candidate is None
    assert "AMBIGUOUS_IDENTITY" in child.reason_codes


def test_same_stable_key_conflicts_do_not_count_as_multi(
    catalog: SchemaPackCatalogV1,
) -> None:
    entry = _entry(
        material_id="same-key-conflict",
        text=(
            "平安保险 产品甲 产品乙 产品代码 SAME-CODE 登记编号 SAME-REG "
            "版本 2026 医疗保险 官方条款"
        ),
    )
    result = _resolve(
        catalog,
        (entry,),
        (
            (
                {
                    "proposal_ref": "a",
                    "name": "产品甲",
                    "product_code": "SAME-CODE",
                    "filing": "SAME-REG",
                },
                {
                    "proposal_ref": "b",
                    "name": "产品乙",
                    "product_code": "SAME-CODE",
                    "filing": "SAME-REG",
                },
            ),
        ),
    )
    assert result.decisions[0].disposition == "NEEDS_CONFIRM"
    assert "MULTI_ENTITY_REVIEW" not in result.decisions[0].reason_codes
    assert all(child.disposition == "NEEDS_CONFIRM" for child in result.decisions[0].children)


def test_multi_excludes_child_that_fails_an_automatic_threshold(
    catalog: SchemaPackCatalogV1,
) -> None:
    entry = _entry(
        material_id="multi-low-child",
        text=(
            "平安保险 产品甲 产品代码 A-CODE 登记编号 A-REG 版本 2026 "
            "产品乙 产品代码 B-CODE 登记编号 B-REG 医疗保险 官方条款"
        ),
    )
    result = _resolve(
        catalog,
        (entry,),
        (
            (
                {
                    "proposal_ref": "a",
                    "name": "产品甲",
                    "product_code": "A-CODE",
                    "filing": "A-REG",
                },
                {
                    "proposal_ref": "b",
                    "name": "产品乙",
                    "product_code": "B-CODE",
                    "filing": "B-REG",
                    "identity_confidence": "0.100000",
                },
            ),
        ),
    )
    assert result.decisions[0].disposition == "NEEDS_CONFIRM"
    assert "MULTI_ENTITY_REVIEW" not in result.decisions[0].reason_codes


def test_candidate_aggregation_excludes_ineligible_rows_and_escalates_structural_competition(
    catalog: SchemaPackCatalogV1,
) -> None:
    good = _entry(
        material_id="good",
        text="平安保险 聚合产品 产品代码 AGG1 登记编号 AGG-REG 版本 2026 医疗保险 官方条款",
    )
    low = _entry(
        material_id="low",
        text="平安保险 聚合产品 产品代码 AGG1 登记编号 AGG-REG 版本 2026 医疗保险 官方条款",
    )
    result = _resolve(
        catalog,
        (good, low),
        (
            (
                {
                    "proposal_ref": "good",
                    "name": "聚合产品",
                    "product_code": "AGG1",
                    "filing": "AGG-REG",
                },
            ),
            (
                {
                    "proposal_ref": "low",
                    "name": "聚合产品",
                    "product_code": "AGG1",
                    "filing": "AGG-REG",
                    "identity_confidence": "0.100000",
                },
            ),
        ),
    )
    candidate = result.decisions[0].children[0].entity_candidate
    assert result.decisions[0].disposition == "CREATE"
    assert result.decisions[1].disposition == "NEEDS_CONFIRM"
    assert candidate is not None
    assert candidate.evidence_ids
    assert all(item.startswith("good-") for item in candidate.evidence_ids)

    incomplete = _entry(
        material_id="a-incomplete",
        text="平安保险 产品代码 AGG2 登记编号 AGG2-REG 版本 2026 医疗保险 官方条款",
    )
    complete = _entry(
        material_id="z-complete",
        text="平安保险 完整产品 产品代码 AGG2 登记编号 AGG2-REG 版本 2026 医疗保险 官方条款",
    )
    structural = _resolve(
        catalog,
        (incomplete, complete),
        (
            (
                {
                    "proposal_ref": "incomplete",
                    "name": None,
                    "product_code": "AGG2",
                    "filing": "AGG2-REG",
                },
            ),
            (
                {
                    "proposal_ref": "complete",
                    "name": "完整产品",
                    "product_code": "AGG2",
                    "filing": "AGG2-REG",
                },
            ),
        ),
    )
    assert [item.disposition for item in structural.decisions] == [
        "NEEDS_CONFIRM",
        "NEEDS_CONFIRM",
    ]
    assert all(item.children[0].entity_candidate is None for item in structural.decisions)

    medical = _entry(
        material_id="medical-pack",
        text="平安保险 包竞争产品 产品代码 PACK1 登记编号 PACK-REG 版本 2026 医疗保险 官方条款",
    )
    critical = _entry(
        material_id="critical-pack",
        text="平安保险 包竞争产品 产品代码 PACK1 登记编号 PACK-REG 版本 2026 重大疾病保险 官方条款",
    )
    pack_conflict = _resolve(
        catalog,
        (critical, medical),
        (
            (
                {
                    "proposal_ref": "critical",
                    "name": "包竞争产品",
                    "product_code": "PACK1",
                    "filing": "PACK-REG",
                    "label": "critical_illness_insurance",
                },
            ),
            (
                {
                    "proposal_ref": "medical",
                    "name": "包竞争产品",
                    "product_code": "PACK1",
                    "filing": "PACK-REG",
                },
            ),
        ),
    )
    assert all(item.disposition == "NEEDS_CONFIRM" for item in pack_conflict.decisions)
    assert all(item.children[0].entity_candidate is None for item in pack_conflict.decisions)


@pytest.mark.parametrize(
    ("receipt_changes"),
    [
        {"purpose": "other-purpose"},
        {"run_schema_version": "other-schema"},
        {"role": "extract"},
    ],
)
def test_model_receipt_requires_frozen_purpose_schema_and_classify_role(
    catalog: SchemaPackCatalogV1,
    receipt_changes: dict[str, str],
) -> None:
    entry = _entry(
        material_id="wrong-model-purpose",
        text="平安保险 用途产品 产品代码 PURPOSE1 登记编号 PURPOSE-REG 版本 2026 医疗保险 官方条款",
    )
    corpus = _corpus(entry)
    receipt = _model_binding(corpus, entry, **receipt_changes)
    proposal = _material_proposal(
        entry,
        receipt,
        entities=(
            (
                {
                    "proposal_ref": "p",
                    "name": "用途产品",
                    "product_code": "PURPOSE1",
                    "filing": "PURPOSE-REG",
                }
            ),
        ),
    )
    result = g.resolve_batch(
        catalog=catalog,
        corpus=corpus,
        proposals=_proposal_batch(corpus, (receipt,), (proposal,)),
        existing_entities=_existing(),
        policy=_policy(),
    )
    assert result.model_attempted_count == 0
    assert result.decisions[0].disposition == "QUARANTINE"
    assert "MODEL_RECEIPT_INVALID" in result.decisions[0].reason_codes


@pytest.mark.parametrize(
    ("material_id", "valid_from", "valid_through"),
    [
        ("bad-date", "2026-02-30", None),
        ("reversed", "2026-10-01", "2026-09-01"),
        ("missing-start", None, "2026-09-01"),
    ],
)
def test_interval_proposal_dates_are_strict(
    catalog: SchemaPackCatalogV1,
    material_id: str,
    valid_from: str | None,
    valid_through: str | None,
) -> None:
    policy = _interval_policy(valid_from="2026-01-01", valid_through=None)
    date_text = " ".join(item for item in (valid_from, valid_through) if item is not None)
    entry = _entry(
        material_id=material_id,
        text=(
            f"平安保险 日期产品 产品代码 DATE1 登记编号 DATE-REG 版本 2026 {date_text} "
            "医疗保险 官方条款"
        ),
    )
    corpus = _corpus(entry)
    receipt = _model_binding(corpus, entry)
    proposal = _material_proposal(
        entry,
        receipt,
        entities=(
            {
                "proposal_ref": "p",
                "name": "日期产品",
                "product_code": "DATE1",
                "filing": "DATE-REG",
                "valid_from": valid_from,
                "valid_through": valid_through,
            },
        ),
    )
    result = g.resolve_batch(
        catalog=catalog,
        corpus=corpus,
        proposals=_proposal_batch(corpus, (receipt,), (proposal,)),
        existing_entities=_existing(),
        policy=policy,
    )
    child = result.decisions[0].children[0]
    assert child.disposition == "NEEDS_CONFIRM"
    assert "TRUST_POLICY_UNRESOLVED" in child.reason_codes


def test_interval_date_requires_selected_version_evidence(
    catalog: SchemaPackCatalogV1,
) -> None:
    policy = _interval_policy(valid_from="2026-01-01", valid_through=None)
    supported = _entry(
        material_id="unsupported-date",
        text=(
            "平安保险 日期产品 产品代码 DATE2 登记编号 DATE2-REG 版本 2026 "
            "2026-03-01 医疗保险 官方条款"
        ),
    )
    corpus = _corpus(supported)
    receipt = _model_binding(corpus, supported)
    proposal = _material_proposal(
        supported,
        receipt,
        entities=(
            {
                "proposal_ref": "p",
                "name": "日期产品",
                "product_code": "DATE2",
                "filing": "DATE2-REG",
                "valid_from": "2026-03-01",
            },
        ),
    )
    entity = proposal.entities[0].model_copy(
        update={
            "identity_evidence_ids": tuple(
                item
                for item in proposal.entities[0].identity_evidence_ids
                if not item.endswith("-valid_from")
            )
        }
    )
    values = proposal.model_dump(mode="python", exclude={"proposal_sha256"})
    values["entities"] = (entity,)
    proposal = _new(
        g.MaterialProposalV1,
        "material-proposal.830.g3.v1",
        "proposal_sha256",
        **values,
    )
    child = (
        g.resolve_batch(
            catalog=catalog,
            corpus=corpus,
            proposals=_proposal_batch(corpus, (receipt,), (proposal,)),
            existing_entities=_existing(),
            policy=policy,
        )
        .decisions[0]
        .children[0]
    )
    assert child.disposition == "NEEDS_CONFIRM"
    assert "TRUST_POLICY_UNRESOLVED" in child.reason_codes


def test_valid_interval_with_exact_version_evidence_remains_automatic(
    catalog: SchemaPackCatalogV1,
) -> None:
    policy = _interval_policy(valid_from="2026-01-01", valid_through="2026-12-31")
    entry = _entry(
        material_id="valid-dates",
        text=(
            "平安保险 日期产品 产品代码 DATE4 登记编号 DATE4-REG 版本 2026 "
            "2026-03-01 2026-06-30 医疗保险 官方条款"
        ),
    )
    corpus = _corpus(entry)
    receipt = _model_binding(corpus, entry)
    proposal = _material_proposal(
        entry,
        receipt,
        entities=(
            {
                "proposal_ref": "p",
                "name": "日期产品",
                "product_code": "DATE4",
                "filing": "DATE4-REG",
                "valid_from": "2026-03-01",
                "valid_through": "2026-06-30",
            },
        ),
    )
    result = g.resolve_batch(
        catalog=catalog,
        corpus=corpus,
        proposals=_proposal_batch(corpus, (receipt,), (proposal,)),
        existing_entities=_existing(),
        policy=policy,
    )
    assert result.decisions[0].disposition == "CREATE"


def test_invalid_policy_date_rejects_whole_contract(
    catalog: SchemaPackCatalogV1,
) -> None:
    policy = _interval_policy(valid_from="2026-01-01", valid_through="2026-12-31")
    entry = _entry(
        material_id="invalid-policy-date",
        text="平安保险 日期产品 产品代码 DATE3 登记编号 DATE3-REG 版本 2026 医疗保险 官方条款",
    )
    corpus = _corpus(entry)
    receipt = _model_binding(corpus, entry)
    proposal = _material_proposal(
        entry,
        receipt,
        entities=(
            {
                "proposal_ref": "p",
                "name": "日期产品",
                "product_code": "DATE3",
                "filing": "DATE3-REG",
            },
        ),
    )
    valid_rule = policy.rules[0]
    invalid_rule_values = valid_rule.model_dump(mode="python")
    invalid_rule_values["valid_from"] = "2026-02-30"
    invalid_rule = g.TrustRuleV1.model_construct(**invalid_rule_values)
    invalid_policy_values = policy.model_dump(mode="python", exclude={"policy_sha256"})
    invalid_policy_values["rules"] = (invalid_rule,)
    invalid_policy = g.BatchResolutionPolicyV1.model_construct(
        **invalid_policy_values,
        policy_sha256=schema_wiki_sha256(
            "batch-resolution-policy.830.g3.v1", invalid_policy_values
        ),
    )
    with pytest.raises(g.BatchEntityResolutionError) as error:
        g.resolve_batch(
            catalog=catalog,
            corpus=corpus,
            proposals=_proposal_batch(corpus, (receipt,), (proposal,)),
            existing_entities=_existing(),
            policy=invalid_policy,
        )
    assert error.value.reason_code == "INPUT_CONTRACT_INVALID"


def test_duplicate_real_source_with_different_material_ids_is_rejected(
    catalog: SchemaPackCatalogV1,
) -> None:
    first = _entry(
        material_id="source-a",
        text="平安保险 来源产品 产品代码 SRC1 登记编号 SRC-REG 版本 2026 医疗保险 官方条款",
    )
    second_values = first.model_dump(mode="python", exclude={"material_id", "entry_sha256"})
    second = _new(
        g.CorpusEntryV1,
        "corpus-entry.830.g3.v1",
        "entry_sha256",
        material_id="source-b",
        **second_values,
    )
    corpus = _corpus(first, second)
    with pytest.raises(g.BatchEntityResolutionError) as error:
        g.resolve_batch(
            catalog=catalog,
            corpus=corpus,
            proposals=_proposal_batch(corpus, (), ()),
            existing_entities=_existing(),
            policy=_policy(),
        )
    assert error.value.reason_code == "DUPLICATE_MATERIAL"


def _rehash_resolution_wire(wire: dict[str, Any]) -> dict[str, Any]:
    for material in wire["decisions"]:
        for child in material["children"]:
            classification = child["classification"]
            classification.pop("assignment_sha256", None)
            classification["assignment_sha256"] = schema_wiki_sha256(
                "classification-assignment.830.g3.v1", classification
            )
            candidate = child.get("entity_candidate")
            if candidate is not None:
                candidate.pop("candidate_sha256", None)
                candidate["candidate_sha256"] = schema_wiki_sha256(
                    "entity-candidate.830.g3.v1", candidate
                )
            child.pop("decision_sha256", None)
            child["decision_sha256"] = schema_wiki_sha256("entity-decision.830.g3.v1", child)
        material.pop("decision_sha256", None)
        material["decision_sha256"] = schema_wiki_sha256("material-decision.830.g3.v1", material)
    wire.pop("batch_sha256", None)
    wire["batch_sha256"] = schema_wiki_sha256("batch-entity-resolution.830.g3.v1", wire)
    return wire


def _multi_wire_with_identity_sets(
    catalog: SchemaPackCatalogV1,
) -> dict[str, Any]:
    entry = _entry(
        material_id="wire-multi-identity",
        text=(
            "平安保险 产品甲 产品代码 A-CODE 登记编号 A-REG 版本 2026 "
            "产品乙 产品代码 B-CODE 登记编号 B-REG 医疗保险 官方条款"
        ),
    )
    wire = _resolve(
        catalog,
        (entry,),
        (
            (
                {
                    "proposal_ref": "a",
                    "name": "产品甲",
                    "product_code": "A-CODE",
                    "filing": "A-REG",
                },
                {
                    "proposal_ref": "b",
                    "name": "产品乙",
                    "product_code": "B-CODE",
                    "filing": "B-REG",
                },
            ),
        ),
    ).model_dump(mode="json")
    for child in wire["decisions"][0]["children"]:
        prefix = f"wire-multi-identity-{child['proposal_ref']}"
        child["multi_identity_name_evidence_ids"] = [f"{prefix}-name"]
        child["multi_identity_code_evidence_ids"] = [f"{prefix}-product_code"]
    return _rehash_resolution_wire(wire)


def test_validate_batch_requires_and_accepts_multi_identity_evidence_sets(
    catalog: SchemaPackCatalogV1,
) -> None:
    valid = _multi_wire_with_identity_sets(catalog)
    parsed = g.validate_batch(json.dumps(valid, ensure_ascii=False))
    assert parsed.decisions[0].disposition == "MULTI"

    omitted = deepcopy(valid)
    omitted["decisions"][0]["children"][0].pop("multi_identity_name_evidence_ids")
    with pytest.raises(g.BatchEntityResolutionError) as error:
        g.validate_batch(json.dumps(_rehash_resolution_wire(omitted), ensure_ascii=False))
    assert error.value.reason_code == "COMPILED_BATCH_INVALID"


def test_validate_batch_rejects_downgrading_qualified_multi_parent(
    catalog: SchemaPackCatalogV1,
) -> None:
    wire = _multi_wire_with_identity_sets(catalog)
    parent = wire["decisions"][0]
    parent["disposition"] = "NEEDS_CONFIRM"
    parent["reason_codes"] = [
        reason for reason in parent["reason_codes"] if reason != "MULTI_ENTITY_REVIEW"
    ]
    wire["disposition_counts"]["MULTI"] = 0
    wire["disposition_counts"]["NEEDS_CONFIRM"] = 1
    with pytest.raises(g.BatchEntityResolutionError) as error:
        g.validate_batch(json.dumps(_rehash_resolution_wire(wire), ensure_ascii=False))
    assert error.value.reason_code == "COMPILED_BATCH_INVALID"


@pytest.mark.parametrize(
    "blocker",
    ["SCOPE_MISMATCH", "SOURCE_RECEIPT_MISMATCH", "MODEL_RECEIPT_INVALID"],
)
def test_validate_batch_rejects_multi_child_with_global_trust_blocker(
    catalog: SchemaPackCatalogV1,
    blocker: str,
) -> None:
    wire = _multi_wire_with_identity_sets(catalog)
    child = wire["decisions"][0]["children"][0]
    child["disposition"] = "NEEDS_CONFIRM"
    child["entity_candidate"] = None
    child["reason_codes"] = [blocker]
    child["queue_id"] = "queue-g3"
    child["queue_owner"] = "product-owner-g3"
    with pytest.raises(g.BatchEntityResolutionError) as error:
        g.validate_batch(json.dumps(_rehash_resolution_wire(wire), ensure_ascii=False))
    assert error.value.reason_code == "COMPILED_BATCH_INVALID"


@pytest.mark.parametrize("tamper", ["duplicate", "unsorted", "non_subset", "cross_key"])
def test_validate_batch_rejects_invalid_multi_identity_evidence_sets(
    catalog: SchemaPackCatalogV1,
    tamper: str,
) -> None:
    wire = _multi_wire_with_identity_sets(catalog)
    children = wire["decisions"][0]["children"]
    first_name = children[0]["multi_identity_name_evidence_ids"][0]
    if tamper == "duplicate":
        children[0]["multi_identity_name_evidence_ids"] = [first_name, first_name]
    elif tamper == "unsorted":
        two_ids = sorted(children[0]["evidence_ids"][:2], reverse=True)
        children[0]["multi_identity_name_evidence_ids"] = two_ids
    elif tamper == "non_subset":
        children[0]["multi_identity_name_evidence_ids"] = ["not-child-evidence"]
    else:
        children[1]["evidence_ids"] = sorted((*children[1]["evidence_ids"], first_name))
        children[1]["multi_identity_name_evidence_ids"] = [first_name]
    with pytest.raises(g.BatchEntityResolutionError) as error:
        g.validate_batch(json.dumps(_rehash_resolution_wire(wire), ensure_ascii=False))
    assert error.value.reason_code == "COMPILED_BATCH_INVALID"


@pytest.mark.parametrize("tamper", ["keys", "anchors", "evidence", "threshold", "pack"])
def test_validate_batch_recomputes_auto_candidate_semantics(
    catalog: SchemaPackCatalogV1,
    tamper: str,
) -> None:
    entry = _entry(
        material_id=f"wire-{tamper}",
        text="平安保险 Wire产品 产品代码 WIRE1 登记编号 WIRE-REG 版本 2026 医疗保险 官方条款",
    )
    result = _resolve(
        catalog,
        (entry,),
        (
            (
                {
                    "proposal_ref": "p",
                    "name": "Wire产品",
                    "product_code": "WIRE1",
                    "filing": "WIRE-REG",
                },
            ),
        ),
    )
    assert result.space_id == "space-g3"
    wire = result.model_dump(mode="json")
    child = wire["decisions"][0]["children"][0]
    candidate = child["entity_candidate"]
    assert candidate is not None
    if tamper == "keys":
        candidate["entity_key_sha256"] = "1" * 64
        candidate["version_candidate_key_sha256"] = "2" * 64
        candidate["candidate_id"] = "entity_candidate_" + "2" * 64
    elif tamper == "anchors":
        candidate["name"] = {"observed_value": "另一个名字", "normalized_value": "另一个名字"}
    elif tamper == "evidence":
        candidate["evidence_ids"] = ["unrelated-material-evidence"]
    elif tamper == "threshold":
        child["identity_confidence"] = "0.100000"
    else:
        child["classification"]["schema_pack_id"] = None
        child["classification"]["schema_version"] = None
        child["classification"]["schema_pack_sha256"] = None
    with pytest.raises(g.BatchEntityResolutionError) as error:
        g.validate_batch(json.dumps(_rehash_resolution_wire(wire), ensure_ascii=False))
    assert error.value.reason_code == "COMPILED_BATCH_INVALID"
