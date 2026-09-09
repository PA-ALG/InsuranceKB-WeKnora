from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from insurance_harness.knowledge_compiler import g3_bounded_model_execution as bounded
from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_json_bytes_830_g3
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    _batch_sha256,
    assemble_candidate_bundle,
    compiler_context_g3,
    review_context_g3,
    validate_batch_candidate,
)
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    CompileOutput,
    ReviewOutput,
)
from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
    G3NativeCharacterBoxV1,
    G3NativePageProjectionSetV1,
    G3NativePageProjectionV1,
    G3SemanticResponseV1,
    _render_g3_stage_contexts,
    assemble_c_semantic_response,
    build_d_review_result,
    build_parser,
    canonical_cost_aggregation,
    g3_current_schema_specs,
    parse_d_compile_output,
    parse_d_review_output,
)
from insurance_harness.model_policy import AdmissionPolicyDenied
from insurance_harness.run_admission.g3_models import (
    G3AuthorizedMaterialV1,
    G3CostAuditV1,
    G3DelegatedStageSignerV1,
    G3ModelProcessingAuthorizationV1,
    canonical_json,
)
from tests.test_batch_entity_resolution_830_g3 import _corpus, _entry, _existing, _policy
from tests.test_run_admission_g3_bounded_830 import _hashed, valid_c_plan

H = "0" * 64


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_current_schema_mapping_is_closed_and_canonical() -> None:
    request_hashes = set()
    for stage in ("C_CLASSIFY", "D_COMPILE", "D_REVIEW"):
        specs = g3_current_schema_specs(stage)
        assert tuple(row[0] for row in specs) == ("request", "response")
        request_hashes.add(_sha(canonical_json(specs[0][2])))
        assert specs[0][1].endswith("g3_bounded_model_execution.py")
        if stage == "C_CLASSIFY":
            assert specs[1][1].endswith("g3_bounded_model_execution.py")
        else:
            assert specs[1][1].endswith("concept_compile_830_g2.py")
    assert request_hashes == {
        "b4a5a1487957d6f873a3aab0ba516a886aa413568a7ba485e8e619b43417024c"
    }


def test_c_renderer_partitions_materials_and_binds_parent_rows() -> None:
    fixture = Path(__file__).parent / "fixtures" / "batch_concept_compile_830_g3" / "candidate.json"
    catalog = validate_batch_candidate(fixture.read_bytes()).request.catalog
    entries = (
        _entry(material_id="m-001", text="first source"),
        _entry(material_id="m-002", text="second source"),
    )
    corpus = _corpus(*entries)
    policy = _policy()
    existing = _existing()
    pages = tuple(
        G3NativePageProjectionV1(
            block_ref=f"opaque-{index}",
            material_id=entry.material_id,
            revision_id=entry.blocks[0].revision_id,
            block_id=entry.blocks[0].block_id,
            page_number=entry.blocks[0].page_number,
            page_width=100.0,
            page_height=100.0,
            text=entry.blocks[0].text,
            boxes=(),
        )

        for index, entry in enumerate(entries, 1)
    )
    page_set = G3NativePageProjectionSetV1(
        contract="g3-native-page-projections.830.v1", pages=pages
    )
    artifacts = {
        "batch-corpus.830.g3.v1": [canonical_json(corpus.model_dump(mode="json"))],
        "batch-resolution-policy.830.g3.v1": [
            canonical_json(policy.model_dump(mode="json"))
        ],
        "schema-pack-catalog.830.g3.v1": [canonical_json(catalog.model_dump(mode="json"))],
        "existing-entities.830.g3.v1": [canonical_json(existing.model_dump(mode="json"))],
        "g3-native-page-projections.830.v1": [
            canonical_json(page_set.model_dump(mode="json"))
        ],
    }
    roles = sorted({role for rule in policy.rules for role in rule.material_roles})
    labels = sorted(
        {
            label
            for catalog_entry in catalog.entries
            for label in catalog_entry.pack.applicable_classifications
        }
    )
    contexts = []
    for index, entry in enumerate(entries, 1):
        contexts.append(
            canonical_json(
                {
                    "contract": "g3-c-classify-prompt-context.830.v1",
                    "window_id": f"w-{index:03d}",
                    "materials": [
                        {
                            "material_id": entry.material_id,
                            "blocks": [
                                {
                                    "block_ref": f"opaque-{index}",
                                    "text": entry.blocks[0].text,
                                }
                            ],
                        }
                    ],
                    "allowed_material_roles": roles,
                    "allowed_taxonomy_labels": labels,
                    "existing_entities": [],
                    "response_schema": G3SemanticResponseV1.model_json_schema(),
                }
            )
        )
    base = valid_c_plan(call_count=2)
    calls = tuple(
        call.model_copy(update={"input_context_sha256": _sha(contexts[call.ordinal])})
        for call in base.request_manifest.calls
    )
    index_bytes = canonical_json(
        {
            "contract": "g3-stage-render-contexts.830.v1",
            "stage": "C_CLASSIFY",
            "calls": [
                {
                    "call_id": call.call_id,
                    "ordinal": call.ordinal,
                    "input_context_sha256": call.input_context_sha256,
                }
                for call in calls
            ],
        }
    )
    template = b"fixed C system"
    preview = canonical_json(
        {
            "contract": "g3-c-prompt-preview.830.v1",
            "calls": [
                {
                    "call_id": call.call_id,
                    "ordinal": call.ordinal,
                    "window_id": call.window_id,
                    "material_ids": list(call.material_ids),
                    "input_context_sha256": call.input_context_sha256,
                    "request_body_sha256": call.request_body_sha256,
                    "system": template.decode(),
                    "user": contexts[call.ordinal].decode(),
                }
                for call in calls
            ],
        }
    )
    request_manifest = _hashed(
        type(base.request_manifest),
        "g3-request-manifest.830.v1",
        "manifest_hash",
        **{
            **{
                key: value
                for key, value in base.request_manifest.model_dump(mode="python").items()
                if key != "manifest_hash"
            },
            "calls": calls,
        },
    )
    dispatch_lock = _hashed(
        type(base.dispatch_lock),
        "g3-stage-dispatch.830.v1",
        "structured_dispatch_hash",
        **{
            **{
                key: value
                for key, value in base.dispatch_lock.model_dump(mode="python").items()
                if key != "structured_dispatch_hash"
            },
            "calls": calls,
            "opaque_block_map_sha256": _sha(
                artifacts["g3-native-page-projections.830.v1"][0]
            ),
            "input_context_sha256": _sha(index_bytes),
        },
    )
    plan = base.model_copy(
        update={"request_manifest": request_manifest, "dispatch_lock": dispatch_lock}
    )
    authorized = tuple(
        G3AuthorizedMaterialV1(
            material_id=entry.material_id,
            corpus_entry_sha256=entry.entry_sha256,
            source_revision_receipt_sha256=_sha(
                canonical_json(entry.receipt.model_dump(mode="json"))
            ),
            w1_sha256=_sha(
                canonical_json([block.model_dump(mode="json") for block in entry.blocks])
            ),
            native_page_map_sha256=_sha(
                canonical_json(
                    {
                        "contract": "g3-native-page-projections.830.v1",
                        "pages": [pages[index].model_dump(mode="json")],
                    }
                )
            ),
        )
        for index, entry in enumerate(entries)
    )
    public = bytes(32)
    parent = G3ModelProcessingAuthorizationV1(
        contract="g3-model-processing-authorization.830.v1",
        authorization_id="fixture-auth",
        chain_manifest=base.chain_manifest,
        chain_manifest_hash=base.chain_manifest_hash,
        space_id=base.space_id,
        provider="bailian",
        endpoint_origin="https://dashscope.aliyuncs.com",
        deployment_id="qwen3.5-plus-2026-04-20",
        family="qwen",
        policy_version="830-g3-bounded-v1",
        c_materials=authorized,
        c_request_manifest_hash=base.manifest_hash,
        c_prompt_preview_sha256=_sha(preview),
        allowed_stages=("C_CLASSIFY", "D_COMPILE", "D_REVIEW"),
        allowed_roles=("classify", "extract", "verify"),
        allowed_derived_data_categories=tuple(
            sorted(
                (
                    "C_W1_SOURCE",
                    "C_CATALOG_POLICY_SNAPSHOT",
                    "C_EXISTING_ENTITY_SNAPSHOT",
                    "D_AUTOMATIC_CHILD_SOURCE_CLOSURE",
                    "D_CATALOG_PROFILE_BASE",
                    "D_COMPOSED_CANDIDATE_REVIEW_CONTEXT",
                )
            )
        ),
        derivation_rules_version="g3-c-to-d-derivation.830.v1",
        max_calls=base.chain_manifest.max_calls,
        total_input_token_ceiling=base.chain_manifest.total_input_token_ceiling,
        total_output_token_ceiling=base.chain_manifest.total_output_token_ceiling,
        total_time_limit_seconds=base.chain_manifest.total_time_limit_seconds,
        retry_limit=0,
        worker_limit=1,
        delegated_stage_signer=G3DelegatedStageSignerV1(
            key_id="fixture-stage",
            algorithm="Ed25519",
            public_key_b64=base64.b64encode(public).decode(),
            public_key_fingerprint=_sha(public),
        ),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    rendered, rendered_index, rendered_preview = _render_g3_stage_contexts(
        plan=plan, parent=parent, artifacts=artifacts, template_bytes=template
    )
    assert [rendered[call.call_id] for call in calls] == contexts
    assert rendered_index == index_bytes
    assert rendered_preview == preview

    substitute_entry = _entry(material_id="m-001", text="fully rehashed replacement")
    substituted = _corpus(substitute_entry, entries[1])
    substituted_pages = G3NativePageProjectionSetV1(
        contract="g3-native-page-projections.830.v1",
        pages=(
            G3NativePageProjectionV1(
                block_ref="opaque-1",
                material_id="m-001",
                revision_id=substitute_entry.blocks[0].revision_id,
                block_id=substitute_entry.blocks[0].block_id,
                page_number=substitute_entry.blocks[0].page_number,
                page_width=100.0,
                page_height=100.0,
                text=substitute_entry.blocks[0].text,
                boxes=(),
            ),
            pages[1],
        ),
    )
    substituted_page_bytes = canonical_json(substituted_pages.model_dump(mode="json"))
    substituted_plan = plan.model_copy(
        update={
            "dispatch_lock": _hashed(
                type(plan.dispatch_lock),
                "g3-stage-dispatch.830.v1",
                "structured_dispatch_hash",
                **{
                    **{
                        key: value
                        for key, value in plan.dispatch_lock.model_dump(mode="python").items()
                        if key != "structured_dispatch_hash"
                    },
                    "opaque_block_map_sha256": _sha(substituted_page_bytes),
                },
            )
        }
    )
    with pytest.raises(ValueError, match="parent material binding mismatch"):
        _render_g3_stage_contexts(
            plan=substituted_plan,
            parent=parent,
            artifacts={
                **artifacts,
                "batch-corpus.830.g3.v1": [canonical_json(substituted.model_dump(mode="json"))],
                "g3-native-page-projections.830.v1": [substituted_page_bytes],
            },
            template_bytes=template,
        )


def test_d_renderers_reuse_existing_compile_and_review_contexts() -> None:
    fixture = Path(__file__).parent / "fixtures" / "batch_concept_compile_830_g3" / "candidate.json"
    candidate = validate_batch_candidate(fixture.read_bytes())
    base = valid_c_plan()
    parent = G3ModelProcessingAuthorizationV1.model_construct()
    template = b"fixed D system"

    def d_plan(stage: str, role: str, context: bytes):
        identity = base.approved_identities[0].model_copy(update={"role": role})
        call = base.request_manifest.calls[0].model_copy(
            update={
                "stage": stage,
                "window_id": None,
                "material_ids": (),
                "identity": identity,
                "input_context_sha256": _sha(context),
            }
        )
        manifest = _hashed(
            type(base.request_manifest),
            "g3-request-manifest.830.v1",
            "manifest_hash",
            contract="g3-request-manifest.830.v1",
            stage=stage,
            chain_id=base.chain_id,
            calls=(call,),
        )
        index = canonical_json(
            {
                "contract": "g3-stage-render-contexts.830.v1",
                "stage": stage,
                "calls": [
                    {
                        "call_id": call.call_id,
                        "ordinal": 0,
                        "input_context_sha256": call.input_context_sha256,
                    }
                ],
            }
        )
        dispatch = _hashed(
            type(base.dispatch_lock),
            "g3-stage-dispatch.830.v1",
            "structured_dispatch_hash",
            contract="g3-stage-dispatch.830.v1",
            stage=stage,
            calls=(call,),
            opaque_block_map_sha256=None,
            input_context_sha256=_sha(index),
            schema_hash=base.schema_hash,
            template_hash=base.template_lock.approved_template_hash,
        )
        return (
            base.model_copy(
                update={
                    "stage": stage,
                    "request_manifest": manifest,
                    "dispatch_lock": dispatch,
                }
            ),
            index,
        )

    compile_context = batch_json_bytes_830_g3(
        {
            "contract": "g3-d-compile-prompt-context.830.v1",
            "context": compiler_context_g3(candidate.request),
            "response_schema": CompileOutput.model_json_schema(),
        }
    )
    compile_plan, compile_index = d_plan("D_COMPILE", "extract", compile_context)
    rendered, index, preview = _render_g3_stage_contexts(
        plan=compile_plan,
        parent=parent,
        artifacts={
            "batch-concept-compile-request.830.g3.v1": [
                canonical_json(candidate.request.model_dump(mode="json"))
            ]
        },
        template_bytes=template,
    )
    assert tuple(rendered.values()) == (compile_context,)
    assert index == compile_index
    assert preview is None

    review_context = batch_json_bytes_830_g3(
        {
            "contract": "g3-d-review-prompt-context.830.v1",
            "context": review_context_g3(candidate.request, candidate.compile_result.output),
            "response_schema": ReviewOutput.model_json_schema(),
        }
    )
    review_plan, review_index = d_plan("D_REVIEW", "verify", review_context)
    rendered, index, preview = _render_g3_stage_contexts(
        plan=review_plan,
        parent=parent,
        artifacts={
            "batch-concept-compile-request.830.g3.v1": [
                canonical_json(candidate.request.model_dump(mode="json"))
            ],
            "g3-d-model-compile-result.830.v1": [
                canonical_json(candidate.model_compile_result.model_dump(mode="json"))
            ],
            "g3-d-final-compile-result.830.v1": [
                canonical_json(candidate.compile_result.model_dump(mode="json"))
            ],
        },
        template_bytes=template,
    )
    assert tuple(rendered.values()) == (review_context,)
    assert index == review_index
    assert preview is None


def test_cli_exposes_only_fixed_prepare_and_run_inputs() -> None:
    parser = build_parser()
    prepare = parser.parse_args(
        [
            "prepare-stage",
            "--parent-authorization",
            "/var/lib/insurancekb/run-admission/sha256/"
            + H
            + "/model-processing-authorization.json",
            "--stage",
            "C_CLASSIFY",
            "--stage-input",
            "/var/lib/insurancekb/run-admission/sha256/" + H + "/stage-input.json",
        ]
    )
    assert prepare.stage == "C_CLASSIFY"
    run = parser.parse_args(
        [
            "run-stage",
            "--admission",
            "/var/lib/insurancekb/run-admission/sha256/" + H + "/approval-envelope.json",
        ]
    )
    assert run.command == "run-stage"


def test_stage_cost_receipt_hash_has_one_complete_preimage() -> None:
    cost = G3CostAuditV1(
        status="NOT_MEASURED",
        currency=None,
        amount_minor_units=None,
        rate_card_sha256=None,
        provider_cost_receipt_sha256=None,
        reason_code="NO_FROZEN_RATE_CARD",
    )
    payload, digest = canonical_cost_aggregation("D_COMPILE", ((0, H, cost),))
    assert payload == (
        b'{"calls":[{"call_terminal_receipt_sha256":"'
        + H.encode()
        + b'","cost_audit":{"amount_minor_units":null,"currency":null,'
        b'"provider_cost_receipt_sha256":null,"rate_card_sha256":null,'
        b'"reason_code":"NO_FROZEN_RATE_CARD","status":"NOT_MEASURED"},'
        b'"cost_audit_sha256":"'
        + __import__("hashlib")
        .sha256(
            b'{"amount_minor_units":null,"currency":null,'
            b'"provider_cost_receipt_sha256":null,"rate_card_sha256":null,'
            b'"reason_code":"NO_FROZEN_RATE_CARD","status":"NOT_MEASURED"}'
        )
        .hexdigest()
        .encode()
        + b'","ordinal":0}],"stage":"D_COMPILE"}'
    )
    assert digest == __import__("hashlib").sha256(payload).hexdigest()


def _semantic_response(text: str) -> bytes:
    def locator(quote: str) -> dict[str, object]:
        start = text.index(quote)
        return {
            "block_ref": "opaque-1",
            "start": start,
            "end": start + len(quote),
            "quote": quote,
        }

    return canonical_json(
        {
            "contract": "g3-batch-resolution-semantic-response.local.v1",
            "materials": [
                {
                    "material_id": "m-001",
                    "material_role": "policy",
                    "material_role_evidence_refs": ["e-role"],
                    "entities": [
                        {
                            "entity_ref": "entity-1",
                            "issuer": "中国人寿",
                            "name": "A款",
                            "product_code": None,
                            "version_label": None,
                            "filing_or_registration": None,
                            "identity_confidence": "0.990000",
                            "identity_evidence_refs": ["e-issuer", "e-name"],
                            "labels": [
                                {
                                    "taxonomy_label": "medical",
                                    "confidence": "0.980000",
                                    "evidence_refs": ["e-class"],
                                }
                            ],
                            "primary_label": "medical",
                            "valid_from": None,
                            "valid_through": None,
                        }
                    ],
                    "evidence": [
                        {
                            "evidence_ref": "e-class",
                            "entity_ref": "entity-1",
                            "purpose": "classification",
                            "field_key": None,
                            "locator": locator("医疗险"),
                        },
                        {
                            "evidence_ref": "e-issuer",
                            "entity_ref": "entity-1",
                            "purpose": "issuer",
                            "field_key": None,
                            "locator": locator("中国人寿"),
                        },
                        {
                            "evidence_ref": "e-name",
                            "entity_ref": "entity-1",
                            "purpose": "name",
                            "field_key": None,
                            "locator": locator("A款"),
                        },
                        {
                            "evidence_ref": "e-role",
                            "entity_ref": None,
                            "purpose": "material_role",
                            "field_key": None,
                            "locator": locator("保险"),
                        },
                    ],
                }
            ],
        }
    )


def _automatic_semantic_response(text: str) -> bytes:
    value = json.loads(_semantic_response(text))
    material = value["materials"][0]
    entity = material["entities"][0]
    entity["product_code"] = "P001"
    entity["version_label"] = "2026版"
    entity["filing_or_registration"] = {
        "kind": "filing_number",
        "value": "ABC123",
    }
    entity["identity_evidence_refs"].extend(("e-code", "e-filing", "e-version"))
    entity["identity_evidence_refs"].sort()
    for ref, purpose, quote in (
        ("e-code", "product_code", "P001"),
        ("e-filing", "version", "ABC123"),
        ("e-version", "version", "2026版"),
    ):
        start = text.index(quote)
        material["evidence"].append(
            {
                "evidence_ref": ref,
                "entity_ref": "entity-1",
                "purpose": purpose,
                "field_key": None,
                "locator": {
                    "block_ref": "opaque-1",
                    "start": start,
                    "end": start + len(quote),
                    "quote": quote,
                },
            }
        )
    material["evidence"].sort(key=lambda item: item["evidence_ref"])
    return canonical_json(value)


def _semantic_from_proposals(
    proposals, corpus, block_refs: dict[tuple[str, str], str]
) -> bytes:
    blocks = {
        (block.revision_id, block.block_id): block
        for entry in corpus.entries
        for block in entry.blocks
    }
    materials = []
    for proposal in proposals.proposals:
        evidence = []
        for row in proposal.evidence:
            source = row.evidence
            block = blocks[(source.revision_id, source.block_id)]
            evidence.append(
                {
                    "evidence_ref": row.evidence_id,
                    "entity_ref": row.entity_proposal_ref,
                    "purpose": row.purpose,
                    "field_key": row.field_key,
                    "locator": {
                        "block_ref": block_refs[(source.revision_id, source.block_id)],
                        "start": 0,
                        "end": len(block.text),
                        "quote": block.text,
                    },
                }
            )
        entities = [
            {
                "entity_ref": entity.proposal_ref,
                "issuer": entity.issuer,
                "name": entity.name,
                "product_code": entity.product_code,
                "version_label": entity.version_label,
                "filing_or_registration": (
                    None
                    if entity.filing_or_registration is None
                    else entity.filing_or_registration.model_dump(mode="json")
                ),
                "identity_confidence": entity.identity_confidence,
                "identity_evidence_refs": list(entity.identity_evidence_ids),
                "labels": [
                    {
                        "taxonomy_label": label.taxonomy_label,
                        "confidence": label.confidence,
                        "evidence_refs": list(label.evidence_ids),
                    }
                    for label in entity.labels
                ],
                "primary_label": entity.primary_label,
                "valid_from": entity.valid_from,
                "valid_through": entity.valid_through,
            }
            for entity in proposal.entities
        ]
        materials.append(
            {
                "material_id": proposal.material_id,
                "material_role": proposal.material_role,
                "material_role_evidence_refs": list(
                    proposal.material_role_evidence_ids
                ),
                "entities": entities,
                "evidence": evidence,
            }
        )
    return canonical_json(
        {
            "contract": "g3-batch-resolution-semantic-response.local.v1",
            "materials": materials,
        }
    )


def test_c_semantic_assembler_uses_exact_source_and_native_projection() -> None:
    text = "中国人寿保险A款分类医疗险"
    entry = _entry(material_id="m-001", text=text)
    source = entry.blocks[0]
    page = G3NativePageProjectionV1(
        block_ref="opaque-1",
        material_id="m-001",
        revision_id=source.revision_id,
        block_id=source.block_id,
        page_number=source.page_number,
        page_width=100.0,
        page_height=100.0,
        text=text,
        boxes=tuple(
            G3NativeCharacterBoxV1(
                index=index,
                x=float(index),
                y=0.0,
                width=1.0,
                height=1.0,
            )
            for index in range(len(text))
        ),
    )
    proposals = assemble_c_semantic_response(
        raw=_semantic_response(text),
        corpus=_corpus(entry),
        requested_material_ids=("m-001",),
        native_pages=(page,),
        allowed_material_roles=("policy",),
        allowed_taxonomy_labels=("medical",),
        model_request_sha256="1" * 64,
    )
    assert len(proposals) == 1
    assert proposals[0].entities[0].issuer == "中国人寿"
    tampered = _semantic_response(text).replace("医疗险".encode(), "医疗宝".encode())
    with pytest.raises(ValueError):
        assemble_c_semantic_response(
            raw=tampered,
            corpus=_corpus(entry),
            requested_material_ids=("m-001",),
            native_pages=(page,),
            allowed_material_roles=("policy",),
            allowed_taxonomy_labels=("medical",),
            model_request_sha256="1" * 64,
        )


def test_native_and_semantic_closed_wires_preserve_only_exact_body_fields() -> None:
    raw = "actual-\uf99c-source"
    page = G3NativePageProjectionV1(
        block_ref="opaque-1",
        material_id="m-001",
        revision_id="revision-1",
        block_id="block-1",
        page_number=1,
        page_width=100.0,
        page_height=100.0,
        text=raw,
        boxes=(),
    )
    pages = G3NativePageProjectionSetV1(
        contract="g3-native-page-projections.830.v1", pages=(page,)
    )
    native_wire = bounded.canonical_native_page_projections(pages)
    assert raw.encode() in native_wire
    with pytest.raises(TypeError):
        bounded.canonical_native_page_projections(pages.model_dump(mode="json"))  # type: ignore[arg-type]

    class NativeProjectionSubclass(G3NativePageProjectionSetV1):
        pass

    with pytest.raises(TypeError):
        bounded.canonical_native_page_projections(
            NativeProjectionSubclass.model_validate(pages.model_dump(mode="json"))
        )

    semantic_wire = canonical_json(
        {
            "contract": "g3-batch-resolution-semantic-response.local.v1",
            "materials": [
                {
                    "entities": [],
                    "evidence": [
                        {
                            "entity_ref": None,
                            "evidence_ref": "e-1",
                            "field_key": None,
                            "locator": {
                                "block_ref": "opaque-1",
                                "end": len(raw),
                                "quote": raw,
                                "start": 0,
                            },
                            "purpose": "material_role",
                        }
                    ],
                    "material_id": "m-001",
                    "material_role": "policy",
                    "material_role_evidence_refs": ["e-1"],
                }
            ],
        }
    )
    response, echoed = bounded.parse_c_semantic_response_bytes(semantic_wire)
    assert response.materials[0].evidence[0].locator.quote == raw
    assert echoed == semantic_wire
    with pytest.raises(ValidationError):
        G3NativePageProjectionV1(
            block_ref="bad-\uf99c",
            material_id="m-001",
            revision_id="revision-1",
            block_id="block-1",
            page_number=1,
            page_width=100.0,
            page_height=100.0,
            text="NFC source",
            boxes=(),
        )
    with pytest.raises(ValidationError):
        G3NativePageProjectionV1(
            block_ref="bad\nref",
            material_id="m-001",
            revision_id="revision-1",
            block_id="block-1",
            page_number=1,
            page_width=100.0,
            page_height=100.0,
            text="NFC source",
            boxes=(),
        )


def test_d_compile_review_and_candidate_contracts_form_one_chain() -> None:
    fixture = Path(__file__).parent / "fixtures" / "batch_concept_compile_830_g3" / "candidate.json"
    candidate = validate_batch_candidate(fixture.read_bytes())
    compile_raw = canonical_json(
        candidate.model_compile_result.output.model_dump(mode="json", round_trip=True)
    )
    assert parse_d_compile_output(compile_raw) == candidate.model_compile_result.output
    review_raw = canonical_json(
        candidate.review_result.output.model_dump(mode="json", round_trip=True)
    )
    review_output = parse_d_review_output(review_raw)
    context_hash = _batch_sha256(
        "batch-concept-review-context.830.g3.v1",
        review_context_g3(candidate.request, candidate.compile_result.output),
    )
    review_result = build_d_review_result(
        raw=review_raw,
        output=review_output,
        run_id=candidate.review_result.execution.run_id,
        context_hash=context_hash,
    )
    rebuilt = assemble_candidate_bundle(
        candidate.request,
        candidate.model_compile_result,
        candidate.compile_result,
        candidate.review_result,
        candidate.admission,
    )
    assert review_result.output == candidate.review_result.output
    assert rebuilt.candidate_hash == candidate.candidate_hash

    stale = review_output.model_copy(update={"request_hash": "f" * 64})
    assert stale.request_hash != candidate.request.base_request.request_hash


@pytest.mark.asyncio
@pytest.mark.parametrize("non_nfc", [False, True])
async def test_signed_prepare_then_fake_provider_run_reaches_c_terminal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, non_nfc: bool
) -> None:
    import respx
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from insurance_harness.knowledge_compiler import g3_bounded_model_execution as runner
    from insurance_harness.model_policy import g3_bounded_gateway as gateway
    from insurance_harness.run_admission import evaluator, g3_trust_policy, trust_policy
    from insurance_harness.run_admission.g3_models import (
        G3ArtifactRefV1,
        G3BoundedAdmissionPlanV1,
        G3DerivedStageReceiptV1,
        G3EligibilityCheckV1,
        G3ModelProcessingAuthorizationEnvelopeV1,
        G3SchemaArtifactV1,
        G3StageEligibilityLockV1,
        G3StageProvenanceLockV1,
        G3StageRightsLockV1,
        parent_authorization_signed_bytes,
    )
    from insurance_harness.run_admission.g3_trust_policy import (
        G3RootTrustPolicyV1,
        G3TrustedApproverV1,
    )
    from insurance_harness.run_admission.models import (
        ResourceCaps,
        canonical_model_identities_hash,
        canonical_model_plan_hash,
    )

    store = tmp_path / "admission"
    ledger = tmp_path / "ledger"
    store.mkdir(mode=0o700)
    ledger.mkdir(mode=0o700)
    monkeypatch.setattr(evaluator, "_ADMISSION_STORE_ROOT", store)
    monkeypatch.setattr(gateway, "G3_LEDGER_ROOT", str(ledger))
    monkeypatch.setattr(trust_policy, "_ROOT_OWNER_UID", __import__("os").geteuid())

    fixture = Path(__file__).parent / "fixtures" / "batch_concept_compile_830_g3" / "candidate.json"
    fixture_candidate = validate_batch_candidate(fixture.read_bytes())
    if non_nfc:
        import importlib.util

        from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3

        fixture_spec = importlib.util.spec_from_file_location(
            "bounded_non_nfc_fixture",
            Path(__file__).with_name("test_batch_concept_compile_830_g3.py"),
        )
        assert fixture_spec is not None and fixture_spec.loader is not None
        fixture_module = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(fixture_module)
        fixture_candidate = fixture_module.build_non_nfc_candidate_fixture(
            batch_concept_compile_830_g3
        )
    fixture_inputs = fixture_candidate.request.resolution_inputs
    corpus = fixture_inputs.corpus
    policy = fixture_inputs.policy
    existing = fixture_inputs.existing_entities
    catalog = fixture_candidate.request.catalog
    block_refs: dict[tuple[str, str], str] = {}
    pages: list[G3NativePageProjectionV1] = []
    for material_index, entry in enumerate(corpus.entries, 1):
        for block_index, block in enumerate(entry.blocks, 1):
            block_ref = f"opaque-{material_index:02d}-{block_index:02d}"
            block_refs[(block.revision_id, block.block_id)] = block_ref
            pages.append(
                G3NativePageProjectionV1(
                    block_ref=block_ref,
                    material_id=entry.material_id,
                    revision_id=block.revision_id,
                    block_id=block.block_id,
                    page_number=block.page_number,
                    page_width=1000.0,
                    page_height=1000.0,
                    text=block.text,
                    boxes=tuple(
                        G3NativeCharacterBoxV1(
                            index=index,
                            x=float(index),
                            y=0.0,
                            width=1.0,
                            height=1.0,
                        )
                        for index in range(len(block.text))
                    ),
                )
            )
    page_set = G3NativePageProjectionSetV1(
        contract="g3-native-page-projections.830.v1",
        pages=tuple(sorted(pages, key=lambda page: page.block_ref)),
    )
    typed_artifacts = {
        "batch-corpus.830.g3.v1": [canonical_json(corpus.model_dump(mode="json"))],
        "batch-resolution-policy.830.g3.v1": [
            canonical_json(policy.model_dump(mode="json"))
        ],
        "schema-pack-catalog.830.g3.v1": [canonical_json(catalog.model_dump(mode="json"))],
        "existing-entities.830.g3.v1": [canonical_json(existing.model_dump(mode="json"))],
        "g3-native-page-projections.830.v1": [canonical_json(page_set.model_dump(mode="json"))],
    }
    base = valid_c_plan().model_copy(update={"space_id": corpus.space_id})
    template_path = Path(__file__).parents[2] / base.template_lock.path
    template = template_path.read_bytes()
    template_values = {
        **{
            key: value
            for key, value in base.template_lock.model_dump(mode="python").items()
            if key not in {"raw_sha256", "approved_template_hash", "template_lock_hash"}
        },
        "raw_sha256": _sha(template),
    }
    approved_template_hash = _sha(
        b"g3-approved-template.830.v1\0" + canonical_json(template_values)
    )
    template_lock = _hashed(
        type(base.template_lock),
        "g3-stage-template-lock.830.v1",
        "template_lock_hash",
        **template_values,
        approved_template_hash=approved_template_hash,
    )
    schema_rows = tuple(
        G3SchemaArtifactV1(
            stage="C_CLASSIFY",
            direction=direction,
            enforcing_module=module,
            enforcing_module_sha256=_sha((Path(__file__).parents[2] / module).read_bytes()),
            canonical_schema_sha256=_sha(canonical_json(schema)),
        )
        for direction, module, schema in g3_current_schema_specs("C_CLASSIFY")
    )
    schema_lock = _hashed(
        type(base.schema_lock),
        "g3-stage-schema-set.830.v1",
        "schema_hash",
        contract="g3-stage-schema-set.830.v1",
        artifacts=schema_rows,
    )
    routing_lock = _hashed(
        type(base.routing_lock),
        "g3-stage-routing.830.v1",
        "routing_policy_hash",
        **{
            **{
                key: value
                for key, value in base.routing_lock.model_dump(mode="python").items()
                if key != "routing_policy_hash"
            },
            "template_hash": approved_template_hash,
            "schema_hash": schema_lock.schema_hash,
        },
    )
    roles = sorted({role for rule in policy.rules for role in rule.material_roles})
    labels = sorted(
        {
            label
            for catalog_entry in catalog.entries
            for label in catalog_entry.pack.applicable_classifications
        }
    )
    context = canonical_json(
        {
            "contract": "g3-c-classify-prompt-context.830.v1",
            "window_id": "w-001",
            "materials": [
                {
                    "material_id": entry.material_id,
                    "blocks": [
                        {
                            "block_ref": block_refs[(block.revision_id, block.block_id)],
                            "text": block.text,
                        }
                        for block in entry.blocks
                    ],
                }
                for entry in corpus.entries
            ],
            "allowed_material_roles": roles,
            "allowed_taxonomy_labels": labels,
            "existing_entities": [
                entity.model_dump(mode="json") for entity in existing.entities
            ],
            "response_schema": G3SemanticResponseV1.model_json_schema(),
        }
    )
    call0 = base.request_manifest.calls[0].model_copy(
        update={
            "material_ids": tuple(entry.material_id for entry in corpus.entries),
            "input_context_sha256": _sha(context),
        }
    )
    provisional_plan = base.model_copy(update={"routing_lock": routing_lock})
    body = runner.g3_openai_request_bytes(
        plan=provisional_plan,
        call=call0,
        system=template.decode(),
        user=context.decode(),
    )
    call = call0.model_copy(update={"request_body_sha256": _sha(body), "request_bytes": len(body)})
    manifest = _hashed(
        type(base.request_manifest),
        "g3-request-manifest.830.v1",
        "manifest_hash",
        contract="g3-request-manifest.830.v1",
        stage="C_CLASSIFY",
        chain_id=base.chain_id,
        calls=(call,),
    )
    index_bytes = canonical_json(
        {
            "contract": "g3-stage-render-contexts.830.v1",
            "stage": "C_CLASSIFY",
            "calls": [
                {
                    "call_id": call.call_id,
                    "ordinal": 0,
                    "input_context_sha256": call.input_context_sha256,
                }
            ],
        }
    )
    preview = canonical_json(
        {
            "contract": "g3-c-prompt-preview.830.v1",
            "calls": [
                {
                    "call_id": call.call_id,
                    "ordinal": 0,
                    "window_id": call.window_id,
                    "material_ids": list(call.material_ids),
                    "input_context_sha256": call.input_context_sha256,
                    "request_body_sha256": call.request_body_sha256,
                    "system": template.decode(),
                    "user": context.decode(),
                }
            ],
        }
    )
    materials = tuple(
        G3AuthorizedMaterialV1(
            material_id=entry.material_id,
            corpus_entry_sha256=entry.entry_sha256,
            source_revision_receipt_sha256=_sha(
                canonical_json(entry.receipt.model_dump(mode="json"))
            ),
            w1_sha256=_sha(
                canonical_json([block.model_dump(mode="json") for block in entry.blocks])
            ),
            native_page_map_sha256=_sha(
                canonical_json(
                    {
                        "contract": "g3-native-page-projections.830.v1",
                        "pages": [
                            page.model_dump(mode="json")
                            for page in page_set.pages
                            if page.material_id == entry.material_id
                        ],
                    }
                )
            ),
        )
        for entry in corpus.entries
    )
    root_private = Ed25519PrivateKey.generate()
    stage_private = Ed25519PrivateKey.generate()
    root_public = root_private.public_key().public_bytes_raw()
    stage_public = stage_private.public_key().public_bytes_raw()
    parent_payload = G3ModelProcessingAuthorizationV1(
        contract="g3-model-processing-authorization.830.v1",
        authorization_id="fixture-authorization",
        chain_manifest=base.chain_manifest,
        chain_manifest_hash=base.chain_manifest_hash,
        space_id=base.space_id,
        provider=call.identity.provider,
        endpoint_origin=call.endpoint_origin,
        deployment_id=call.identity.deployment_id,
        family=call.identity.family,
        policy_version=call.identity.policy_version,
        c_materials=materials,
        c_request_manifest_hash=manifest.manifest_hash,
        c_prompt_preview_sha256=_sha(preview),
        allowed_stages=("C_CLASSIFY", "D_COMPILE", "D_REVIEW"),
        allowed_roles=("classify", "extract", "verify"),
        allowed_derived_data_categories=tuple(
            sorted(
                (
                    "C_W1_SOURCE",
                    "C_CATALOG_POLICY_SNAPSHOT",
                    "C_EXISTING_ENTITY_SNAPSHOT",
                    "D_AUTOMATIC_CHILD_SOURCE_CLOSURE",
                    "D_CATALOG_PROFILE_BASE",
                    "D_COMPOSED_CANDIDATE_REVIEW_CONTEXT",
                )
            )
        ),
        derivation_rules_version="g3-c-to-d-derivation.830.v1",
        max_calls=base.chain_manifest.max_calls,
        total_input_token_ceiling=base.chain_manifest.total_input_token_ceiling,
        total_output_token_ceiling=base.chain_manifest.total_output_token_ceiling,
        total_time_limit_seconds=base.chain_manifest.total_time_limit_seconds,
        retry_limit=0,
        worker_limit=1,
        delegated_stage_signer=G3DelegatedStageSignerV1(
            key_id="fixture-stage-key",
            algorithm="Ed25519",
            public_key_b64=base64.b64encode(stage_public).decode(),
            public_key_fingerprint=_sha(stage_public),
        ),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    parent0 = G3ModelProcessingAuthorizationEnvelopeV1(
        schema_version="insurancekb.g3-model-processing-authorization-envelope.v1",
        signature_domain="insurancekb.run-admission.g3-model-processing-authorization.v1",
        key_id="fixture-root-key",
        public_key_fingerprint=_sha(root_public),
        human_identity="fixture-reviewer",
        approver_role="g3-model-processing-authorization-approver",
        payload=parent_payload,
        signature_b64=base64.b64encode(bytes(64)).decode(),
    )
    parent = parent0.model_copy(
        update={
            "signature_b64": base64.b64encode(
                root_private.sign(parent_authorization_signed_bytes(parent0))
            ).decode()
        }
    )
    parent_bytes = canonical_json(parent.model_dump(mode="json", round_trip=True))
    parent_digest = _sha(parent_bytes)

    artifact_payload_by_path: dict[Path, bytes] = {}

    def artifact_ref(contract: str, payload: bytes, filename: str) -> G3ArtifactRefV1:
        digest = _sha(payload)
        ref = G3ArtifactRefV1(
            contract=contract,
            artifact_ref=str(store / "sha256" / digest / filename),
            sha256=digest,
            bytes=len(payload),
        )
        artifact_payload_by_path[Path(ref.artifact_ref)] = payload
        return ref

    refs = [
        artifact_ref(contract, payloads[0], contract + ".json")
        for contract, payloads in typed_artifacts.items()
    ] + [
        artifact_ref("g3-rendered-call-context.830.v1", context, "call-context.json"),
        artifact_ref("g3-stage-render-contexts.830.v1", index_bytes, "stage-contexts.json"),
        artifact_ref("g3-c-prompt-preview.830.v1", preview, "prompt-preview.json"),
        artifact_ref("g3-http-request-body.830.v1", body, "request-body.json"),
    ]
    refs_tuple = tuple(sorted(refs, key=lambda ref: (ref.contract, ref.artifact_ref)))
    seed_payload = canonical_json(
        {"contract": "g3-protocol-seed-data.830.v1", "fixture": "provider-zero"}
    )
    seed_ref = artifact_ref(
        "g3-protocol-seed-data.830.v1", seed_payload, "seed.json"
    )
    protocol_seed = _hashed(
        type(base.protocol_seed_lock),
        "g3-protocol-seed.830.v1",
        "golden_slice_hash",
        **{
            **base.protocol_seed_lock.model_dump(
                mode="python", exclude={"golden_slice_hash", "seed_artifact"}
            ),
            "seed_artifact": seed_ref,
        },
    )
    checks = (
        G3EligibilityCheckV1(
            check_id="parent-material-bindings",
            check_kind="exact-parent-material-bindings",
            subject_id="all-fixture-materials",
            input_sha256s=tuple(
                sorted(
                    {
                        digest
                        for material in materials
                        for digest in (
                            material.corpus_entry_sha256,
                            material.source_revision_receipt_sha256,
                            material.w1_sha256,
                            material.native_page_map_sha256,
                        )
                    }
                    | {
                        _sha(preview),
                    }
                )
            ),
            observed_count=len(materials),
            required_min=1,
            required_max=len(materials),
            status="PASS",
            reason_code="EXACT_BINDINGS_PRESENT",
        ),
    )
    eligibility = _hashed(
        G3StageEligibilityLockV1,
        "g3-stage-eligibility.830.v1",
        "eligibility_hash",
        contract="g3-stage-eligibility.830.v1",
        stage="C_CLASSIFY",
        input_artifacts=refs_tuple,
        checks=checks,
        eligible_subject_ids=tuple(entry.material_id for entry in corpus.entries),
    )
    rights = _hashed(
        G3StageRightsLockV1,
        "g3-external-send-rights.830.v1",
        "rights_hash",
        **{
            **{
                key: value
                for key, value in base.rights_lock.model_dump(mode="python").items()
                if key != "rights_hash"
            },
            "parent_authorization_digest": parent_digest,
            "artifacts": refs_tuple,
            "data_categories": ("C_W1_SOURCE",),
            "material_or_derivation_ids": tuple(
                entry.material_id for entry in corpus.entries
            ),
        },
    )
    provenance = _hashed(
        G3StageProvenanceLockV1,
        "g3-stage-provenance.830.v1",
        "provenance_hash",
        contract="g3-stage-provenance.830.v1",
        stage="C_CLASSIFY",
        artifacts=refs_tuple,
        prior_terminal_receipt_sha256=None,
    )
    dispatch = _hashed(
        type(base.dispatch_lock),
        "g3-stage-dispatch.830.v1",
        "structured_dispatch_hash",
        contract="g3-stage-dispatch.830.v1",
        stage="C_CLASSIFY",
        calls=(call,),
        opaque_block_map_sha256=_sha(typed_artifacts["g3-native-page-projections.830.v1"][0]),
        input_context_sha256=_sha(index_bytes),
        schema_hash=schema_lock.schema_hash,
        template_hash=approved_template_hash,
    )
    plan = G3BoundedAdmissionPlanV1(
        **{
            **base.model_dump(mode="python"),
            "parent_authorization_digest": parent_digest,
            "request_manifest": manifest,
            "manifest_hash": manifest.manifest_hash,
            "eligibility_lock": eligibility,
            "eligibility_hash": eligibility.eligibility_hash,
            "protocol_seed_lock": protocol_seed,
            "golden_slice_hash": protocol_seed.golden_slice_hash,
            "routing_lock": routing_lock,
            "routing_policy_hash": routing_lock.routing_policy_hash,
            "schema_lock": schema_lock,
            "schema_hash": schema_lock.schema_hash,
            "template_lock": template_lock,
            "template_lock_hash": template_lock.template_lock_hash,
            "approved_template_hashes": (approved_template_hash,),
            "dispatch_lock": dispatch,
            "structured_dispatch_hash": dispatch.structured_dispatch_hash,
            "rights_lock": rights,
            "rights_hash": rights.rights_hash,
            "provenance_lock": provenance,
            "provenance_hash": provenance.provenance_hash,
        }
    )
    from insurance_harness.run_admission.profiles.g3_bounded_execution import (
        validate_g3_bounded_plan,
        validate_g3_parent_scope,
    )

    validate_g3_bounded_plan(plan)
    validate_g3_parent_scope(parent.payload, plan)
    policy_root = G3RootTrustPolicyV1(
        schema_version="insurancekb.g3-bounded-run-admission-root-policy.v1",
        approvers=(
            G3TrustedApproverV1(
                key_id="fixture-root-key",
                public_key_b64=base64.b64encode(root_public).decode(),
                public_key_fingerprint=_sha(root_public),
                human_identity="fixture-reviewer",
                role="g3-model-processing-authorization-approver",
                signature_domain="insurancekb.run-admission.g3-model-processing-authorization.v1",
                allowed_space_ids=(base.space_id,),
                allowed_parent_contracts=("g3-model-processing-authorization.830.v1",),
            ),
        ),
    )
    monkeypatch.setattr(g3_trust_policy, "load_g3_root_trust_policy", lambda: policy_root)
    monkeypatch.setattr(evaluator, "load_g3_root_trust_policy", lambda: policy_root)
    monkeypatch.setattr(evaluator, "_clean_repository_sha", lambda: plan.clean_integration_sha)
    monkeypatch.setenv(
        "G3_BOUNDED_STAGE_SIGNING_PRIVATE_KEY_B64",
        base64.b64encode(stage_private.private_bytes_raw()).decode(),
    )
    monkeypatch.setenv("G3_BOUNDED_MODEL_API_KEY", "fixture-provider-key")

    def write_store(payload: bytes, filename: str) -> Path:
        digest = _sha(payload)
        directory = store / "sha256" / digest
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        path = directory / filename
        if path.exists():
            assert path.read_bytes() == payload
        else:
            path.write_bytes(payload)
            path.chmod(0o600)
        return path

    parent_path = write_store(parent_bytes, "model-processing-authorization.json")
    for expected_path, payload in artifact_payload_by_path.items():
        written = write_store(payload, expected_path.name)
        assert written == expected_path
    malicious_body = runner.g3_openai_request_bytes(
        plan=plan,
        call=call,
        system=template.decode(),
        user=context.decode() + "\nUNAUTHORIZED EXTRA MATERIAL",
    )
    malicious_body_ref = artifact_ref(
        "g3-http-request-body.830.v1", malicious_body, "request-body.json"
    )
    assert write_store(malicious_body, "request-body.json") == Path(
        malicious_body_ref.artifact_ref
    )
    malicious_call = call.model_copy(
        update={
            "request_body_sha256": _sha(malicious_body),
            "request_bytes": len(malicious_body),
        }
    )
    malicious_preview_value = json.loads(preview)
    malicious_preview_value["calls"][0]["user"] = (
        context.decode() + "\nUNAUTHORIZED EXTRA MATERIAL"
    )
    malicious_preview_value["calls"][0]["request_body_sha256"] = _sha(malicious_body)
    malicious_preview = canonical_json(malicious_preview_value)
    malicious_preview_ref = artifact_ref(
        "g3-c-prompt-preview.830.v1", malicious_preview, "prompt-preview.json"
    )
    assert write_store(malicious_preview, "prompt-preview.json") == Path(
        malicious_preview_ref.artifact_ref
    )
    malicious_refs = tuple(
        sorted(
            (
                malicious_body_ref
                if ref.contract == "g3-http-request-body.830.v1"
                else malicious_preview_ref
                if ref.contract == "g3-c-prompt-preview.830.v1"
                else ref
                for ref in refs_tuple
            ),
            key=lambda ref: (ref.contract, ref.artifact_ref),
        )
    )
    malicious_manifest = _hashed(
        type(plan.request_manifest),
        "g3-request-manifest.830.v1",
        "manifest_hash",
        contract="g3-request-manifest.830.v1",
        stage="C_CLASSIFY",
        chain_id=plan.chain_id,
        calls=(malicious_call,),
    )
    malicious_parent_payload = parent.payload.model_copy(
        update={
            "c_request_manifest_hash": malicious_manifest.manifest_hash,
            "c_prompt_preview_sha256": _sha(malicious_preview),
        }
    )
    malicious_parent0 = parent.model_copy(
        update={
            "payload": malicious_parent_payload,
            "signature_b64": base64.b64encode(bytes(64)).decode(),
        }
    )
    malicious_parent = malicious_parent0.model_copy(
        update={
            "signature_b64": base64.b64encode(
                root_private.sign(parent_authorization_signed_bytes(malicious_parent0))
            ).decode()
        }
    )
    malicious_parent_bytes = canonical_json(
        malicious_parent.model_dump(mode="json", round_trip=True)
    )
    malicious_parent_digest = _sha(malicious_parent_bytes)
    malicious_parent_path = write_store(
        malicious_parent_bytes, "model-processing-authorization.json"
    )
    malicious_eligibility = _hashed(
        G3StageEligibilityLockV1,
        "g3-stage-eligibility.830.v1",
        "eligibility_hash",
        **{
            **plan.eligibility_lock.model_dump(
                mode="python", exclude={"eligibility_hash", "input_artifacts"}
            ),
            "input_artifacts": malicious_refs,
        },
    )
    malicious_rights = _hashed(
        G3StageRightsLockV1,
        "g3-external-send-rights.830.v1",
        "rights_hash",
        **{
            **plan.rights_lock.model_dump(mode="python", exclude={"rights_hash", "artifacts"}),
            "artifacts": malicious_refs,
            "parent_authorization_digest": malicious_parent_digest,
        },
    )
    malicious_provenance = _hashed(
        G3StageProvenanceLockV1,
        "g3-stage-provenance.830.v1",
        "provenance_hash",
        **{
            **plan.provenance_lock.model_dump(
                mode="python", exclude={"provenance_hash", "artifacts"}
            ),
            "artifacts": malicious_refs,
        },
    )
    malicious_dispatch = _hashed(
        type(plan.dispatch_lock),
        "g3-stage-dispatch.830.v1",
        "structured_dispatch_hash",
        **{
            **plan.dispatch_lock.model_dump(
                mode="python", exclude={"structured_dispatch_hash", "calls"}
            ),
            "calls": (malicious_call,),
        },
    )
    malicious_plan = G3BoundedAdmissionPlanV1(
        **{
            **plan.model_dump(mode="python"),
            "parent_authorization_digest": malicious_parent_digest,
            "request_manifest": malicious_manifest,
            "manifest_hash": malicious_manifest.manifest_hash,
            "eligibility_lock": malicious_eligibility,
            "eligibility_hash": malicious_eligibility.eligibility_hash,
            "rights_lock": malicious_rights,
            "rights_hash": malicious_rights.rights_hash,
            "provenance_lock": malicious_provenance,
            "provenance_hash": malicious_provenance.provenance_hash,
            "dispatch_lock": malicious_dispatch,
            "structured_dispatch_hash": malicious_dispatch.structured_dispatch_hash,
        }
    )
    validate_g3_bounded_plan(malicious_plan)
    malicious_plan_path = write_store(
        canonical_json(malicious_plan.model_dump(mode="json", round_trip=True)),
        "stage-input.json",
    )
    with pytest.raises(AdmissionPolicyDenied):
        runner.prepare_stage(
            parent_authorization=str(malicious_parent_path),
            stage="C_CLASSIFY",
            stage_input=str(malicious_plan_path),
        )
    drifted_schema_artifacts = (
        plan.schema_lock.artifacts[0].model_copy(
            update={"canonical_schema_sha256": "f" * 64}
        ),
        *plan.schema_lock.artifacts[1:],
    )
    drifted_schema = _hashed(
        type(plan.schema_lock),
        "g3-stage-schema-set.830.v1",
        "schema_hash",
        contract="g3-stage-schema-set.830.v1",
        artifacts=drifted_schema_artifacts,
    )
    drifted_routing = _hashed(
        type(plan.routing_lock),
        "g3-stage-routing.830.v1",
        "routing_policy_hash",
        **{
            **plan.routing_lock.model_dump(
                mode="python", exclude={"routing_policy_hash", "schema_hash"}
            ),
            "schema_hash": drifted_schema.schema_hash,
        },
    )
    drifted_dispatch = _hashed(
        type(plan.dispatch_lock),
        "g3-stage-dispatch.830.v1",
        "structured_dispatch_hash",
        **{
            **plan.dispatch_lock.model_dump(
                mode="python", exclude={"structured_dispatch_hash", "schema_hash"}
            ),
            "schema_hash": drifted_schema.schema_hash,
        },
    )
    drifted_plan = G3BoundedAdmissionPlanV1(
        **{
            **plan.model_dump(mode="python"),
            "schema_lock": drifted_schema,
            "schema_hash": drifted_schema.schema_hash,
            "routing_lock": drifted_routing,
            "routing_policy_hash": drifted_routing.routing_policy_hash,
            "dispatch_lock": drifted_dispatch,
            "structured_dispatch_hash": drifted_dispatch.structured_dispatch_hash,
        }
    )
    validate_g3_bounded_plan(drifted_plan)
    drifted_plan_path = write_store(
        canonical_json(drifted_plan.model_dump(mode="json", round_trip=True)),
        "stage-input.json",
    )
    with pytest.raises(AdmissionPolicyDenied):
        runner.prepare_stage(
            parent_authorization=str(parent_path),
            stage="C_CLASSIFY",
            stage_input=str(drifted_plan_path),
        )
    plan_bytes = canonical_json(plan.model_dump(mode="json", round_trip=True))
    plan_path = write_store(plan_bytes, "stage-input.json")
    admission_path = runner.prepare_stage(
        parent_authorization=str(parent_path),
        stage="C_CLASSIFY",
        stage_input=str(plan_path),
    )
    semantic = _semantic_from_proposals(
        fixture_inputs.proposals, corpus, block_refs
    ).decode()
    with respx.mock:
        posted = respx.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        ).respond(
            status_code=200,
            headers={"content-type": "application/json", "x-request-id": "fake-c"},
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": semantic}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            },
        )
        terminal = await runner.run_stage(str(admission_path))
        stage_terminal_path = (
            ledger
            / "chains"
            / plan.chain_manifest_hash
            / "stage-terminals"
            / "C_CLASSIFY.json"
        )
        stage_terminal_path.unlink()
        policy_path = tmp_path / "g3-root-policy.json"
        policy_path.write_bytes(
            canonical_json(policy_root.model_dump(mode="json", round_trip=True))
        )
        policy_path.chmod(0o600)
        child_code = """
import sys
from pathlib import Path
from insurance_harness.knowledge_compiler import g3_bounded_model_execution as runner
from insurance_harness.model_policy import g3_bounded_gateway as gateway
from insurance_harness.run_admission import evaluator, g3_trust_policy, trust_policy
from insurance_harness.run_admission.g3_trust_policy import G3RootTrustPolicyV1
store, ledger, policy_path, clean_sha, admission = sys.argv[1:]
policy = G3RootTrustPolicyV1.model_validate_json(Path(policy_path).read_bytes())
evaluator._ADMISSION_STORE_ROOT = Path(store)
gateway.G3_LEDGER_ROOT = ledger
trust_policy._ROOT_OWNER_UID = __import__('os').geteuid()
evaluator._clean_repository_sha = lambda: clean_sha
evaluator.load_g3_root_trust_policy = lambda: policy
g3_trust_policy.load_g3_root_trust_policy = lambda: policy
runner._store_ref = lambda value: value
raise SystemExit(runner.main(['run-stage', '--admission', admission]))
"""
        child_env = os.environ.copy()
        child_env.pop("G3_BOUNDED_MODEL_API_KEY", None)
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                child_code,
                str(store),
                str(ledger),
                str(policy_path),
                plan.clean_integration_sha,
                str(admission_path),
            ],
            cwd=Path(__file__).parents[1],
            env=child_env,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert child.returncode == 0, child.stderr
        from insurance_harness.run_admission.g3_models import G3StageTerminalReceiptV1

        recovered_terminal = G3StageTerminalReceiptV1.model_validate_json(child.stdout)
    assert terminal.stage == "C_CLASSIFY"
    assert terminal.status == "SUCCESS"
    assert terminal.calls_consumed == 1
    assert terminal.stage_output_sha256 is not None
    assert posted.call_count == 1
    assert recovered_terminal.stage_output_sha256 == terminal.stage_output_sha256
    assert posted.call_count == 1
    results_dir = ledger / "chains" / plan.chain_manifest_hash / "stage-results" / "C_CLASSIFY"
    proposal_bytes = (results_dir / "proposal-batch.json").read_bytes()
    resolution_bytes = (results_dir / "resolution.json").read_bytes()
    from insurance_harness.knowledge_compiler.batch_entity_resolution_830_g3 import (
        BatchEntityResolutionV1,
        ProposalBatchV1,
    )

    proposals = ProposalBatchV1.model_validate_json(proposal_bytes)
    resolution = BatchEntityResolutionV1.model_validate_json(resolution_bytes)
    assert proposal_bytes == canonical_json(proposals.model_dump(mode="json", round_trip=True))
    assert resolution_bytes == canonical_json(
        resolution.model_dump(mode="json", round_trip=True)
    )
    assert terminal.stage_output_sha256 == resolution.batch_sha256

    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
        build_batch_compile_request,
    )

    selected_refs = tuple(
        (decision.material_id, child.proposal_ref)
        for decision in resolution.decisions
        for child in decision.children
        if child.disposition in ("MATCH", "CREATE")
    )
    repository_root = Path(__file__).parents[2]
    if non_nfc:
        materializer_spec = importlib.util.spec_from_file_location(
            "bounded_non_nfc_materializer",
            repository_root
            / "docs/insurance-kb/evidence/830-g3/g3_actual_model_plan_materializer_v1.py",
        )
        assert materializer_spec is not None and materializer_spec.loader is not None
        materializer_module = importlib.util.module_from_spec(materializer_spec)
        monkeypatch.setitem(sys.modules, materializer_spec.name, materializer_module)
        materializer_spec.loader.exec_module(materializer_module)
        before_read = {str(path.relative_to(ledger)): path.read_bytes()
                       for path in ledger.rglob("*") if path.is_file()}
        c_stage, _, _, c_results = materializer_module._prior_stage(
            parent, parent_bytes, plan.chain_manifest, "D_COMPILE"
        )
        assert c_stage == recovered_terminal
        assert c_results["resolution"][1] == resolution_bytes
        assert before_read == {str(path.relative_to(ledger)): path.read_bytes()
                              for path in ledger.rglob("*") if path.is_file()}
    compile_request = build_batch_compile_request(
        base_request=fixture_candidate.request.base_request,
        catalog_json=(
            repository_root / "docs/insurance-kb/evidence/830-g3/catalog/catalog.json"
        ).read_bytes(),
        profile_confirmation_json=(
            repository_root
            / "docs/insurance-kb/evidence/830-g3/profile-user-confirmation.json"
        ).read_bytes(),
        corpus=corpus,
        proposals=proposals,
        existing_entities=existing,
        policy=policy,
        resolution=resolution,
        selected_decision_refs=selected_refs,
    )

    def build_d_plan(
        *,
        stage: str,
        prior_terminal,
        run_id: str,
        typed_payloads: dict[str, bytes],
    ):
        purpose, schema_version, role, prompt_name, categories = {
            "D_COMPILE": (
                "g3-batch-concept-compile",
                "830-g3-d-compile-v1",
                "extract",
                "g3_d_compile_v1.txt",
                ("D_AUTOMATIC_CHILD_SOURCE_CLOSURE", "D_CATALOG_PROFILE_BASE"),
            ),
            "D_REVIEW": (
                "g3-batch-concept-review",
                "830-g3-d-review-v1",
                "verify",
                "g3_d_review_v1.txt",
                ("D_COMPOSED_CANDIDATE_REVIEW_CONTEXT",),
            ),
        }[stage]
        identity = base.approved_identities[0].model_copy(update={"role": role})
        template_relative = (
            "harness/src/insurance_harness/knowledge_compiler/prompts/" + prompt_name
        )
        template_bytes = (repository_root / template_relative).read_bytes()
        template_values = {
            "contract": "g3-stage-template-lock.830.v1",
            "stage": stage,
            "path": template_relative,
            "raw_sha256": _sha(template_bytes),
            "prompt_version": prompt_name.removesuffix(".txt").replace("_", "-"),
            "render_rules_version": "g3-prompt-render.830.v1",
        }
        approved_hash = _sha(
            b"g3-approved-template.830.v1\0" + canonical_json(template_values)
        )
        stage_template = _hashed(
            type(base.template_lock),
            "g3-stage-template-lock.830.v1",
            "template_lock_hash",
            **template_values,
            approved_template_hash=approved_hash,
        )
        stage_schema = _hashed(
            type(base.schema_lock),
            "g3-stage-schema-set.830.v1",
            "schema_hash",
            contract="g3-stage-schema-set.830.v1",
            artifacts=tuple(
                G3SchemaArtifactV1(
                    stage=stage,
                    direction=direction,
                    enforcing_module=module,
                    enforcing_module_sha256=_sha((repository_root / module).read_bytes()),
                    canonical_schema_sha256=_sha(canonical_json(schema)),
                )
                for direction, module, schema in g3_current_schema_specs(stage)
            ),
        )
        stage_routing = _hashed(
            type(base.routing_lock),
            "g3-stage-routing.830.v1",
            "routing_policy_hash",
            contract="g3-stage-routing.830.v1",
            stage=stage,
            purpose=purpose,
            run_schema_version=schema_version,
            role=role,
            identity=identity,
            endpoint_origin="https://dashscope.aliyuncs.com",
            endpoint_path="/compatible-mode/v1/chat/completions",
            temperature_micros=0,
            thinking=False,
            response_format="json_object",
            timeout_seconds=30,
            follow_redirects=False,
            fallback_limit=0,
            retry_limit=0,
            template_hash=approved_hash,
            schema_hash=stage_schema.schema_hash,
        )
        if stage == "D_COMPILE":
            user_context = batch_json_bytes_830_g3(
                {
                    "contract": "g3-d-compile-prompt-context.830.v1",
                    "context": compiler_context_g3(compile_request),
                    "response_schema": CompileOutput.model_json_schema(),
                }
            )
        else:
            final_result = __import__(
                "insurance_harness.knowledge_compiler.concept_compile_830_g2",
                fromlist=["CompileResult"],
            ).CompileResult.model_validate_json(
                typed_payloads["g3-d-final-compile-result.830.v1"]
            )
            user_context = batch_json_bytes_830_g3(
                {
                    "contract": "g3-d-review-prompt-context.830.v1",
                    "context": review_context_g3(compile_request, final_result.output),
                    "response_schema": ReviewOutput.model_json_schema(),
                }
            )
        chain_row = next(row for row in base.chain_manifest.stages if row.stage == stage)
        call0 = base.request_manifest.calls[0].model_copy(
            update={
                "call_id": "d-compile-001" if stage == "D_COMPILE" else "d-review-001",
                "ordinal": 0,
                "stage": stage,
                "window_id": None,
                "material_ids": (),
                "identity": identity,
                "input_context_sha256": _sha(user_context),
                "input_token_estimate": 3,
                "input_token_ceiling": chain_row.input_token_ceiling,
                "output_token_ceiling": chain_row.output_token_ceiling,
                "timeout_seconds": chain_row.time_limit_seconds,
            }
        )
        provisional = base.model_copy(update={"routing_lock": stage_routing})
        body_bytes = runner.g3_openai_request_bytes(
            plan=provisional,
            call=call0,
            system=template_bytes.decode(),
            user=user_context.decode(),
        )
        call = call0.model_copy(
            update={
                "request_body_sha256": _sha(body_bytes),
                "request_bytes": len(body_bytes),
            }
        )
        stage_manifest = _hashed(
            type(base.request_manifest),
            "g3-request-manifest.830.v1",
            "manifest_hash",
            contract="g3-request-manifest.830.v1",
            stage=stage,
            chain_id=base.chain_id,
            calls=(call,),
        )
        context_index = canonical_json(
            {
                "contract": "g3-stage-render-contexts.830.v1",
                "stage": stage,
                "calls": [
                    {
                        "call_id": call.call_id,
                        "ordinal": 0,
                        "input_context_sha256": call.input_context_sha256,
                    }
                ],
            }
        )
        stage_refs = [
            artifact_ref(contract, payload, contract + ".json")
            for contract, payload in typed_payloads.items()
        ] + [
            artifact_ref(
                "g3-rendered-call-context.830.v1", user_context, "call-context.json"
            ),
            artifact_ref(
                "g3-stage-render-contexts.830.v1", context_index, "stage-contexts.json"
            ),
            artifact_ref("g3-http-request-body.830.v1", body_bytes, "request-body.json"),
        ]
        stage_refs_tuple = tuple(
            sorted(stage_refs, key=lambda ref: (ref.contract, ref.artifact_ref))
        )
        derived = _hashed(
            G3DerivedStageReceiptV1,
            "g3-derived-stage-receipt.830.v1",
            "receipt_sha256",
            contract="g3-derived-stage-receipt.830.v1",
            parent_authorization_digest=parent_digest,
            stage=stage,
            prior_terminal_receipt_sha256=prior_terminal.receipt_sha256,
            derivation_rules_version="g3-c-to-d-derivation.830.v1",
            input_artifact_sha256s=tuple(
                sorted({ref.sha256 for ref in stage_refs_tuple})
            ),
            derived_request_manifest_hash=stage_manifest.manifest_hash,
        )
        derivation_id = "c-to-d-compile" if stage == "D_COMPILE" else "d-compile-to-review"
        stage_eligibility = _hashed(
            G3StageEligibilityLockV1,
            "g3-stage-eligibility.830.v1",
            "eligibility_hash",
            contract="g3-stage-eligibility.830.v1",
            stage=stage,
            input_artifacts=stage_refs_tuple,
            checks=(),
            eligible_subject_ids=(derivation_id,),
        )
        stage_dispatch = _hashed(
            type(base.dispatch_lock),
            "g3-stage-dispatch.830.v1",
            "structured_dispatch_hash",
            contract="g3-stage-dispatch.830.v1",
            stage=stage,
            calls=(call,),
            opaque_block_map_sha256=None,
            input_context_sha256=_sha(context_index),
            schema_hash=stage_schema.schema_hash,
            template_hash=approved_hash,
        )
        stage_caps = _hashed(
            type(base.stage_caps),
            "g3-stage-caps.830.v1",
            "caps_sha256",
            contract="g3-stage-caps.830.v1",
            stage=stage,
            worker_limit=1,
            call_limit=1,
            attempts_per_call=1,
            retry_limit=0,
            input_token_ceiling=chain_row.input_token_ceiling,
            output_token_ceiling=chain_row.output_token_ceiling,
            time_limit_seconds=chain_row.time_limit_seconds,
        )
        stage_rights = _hashed(
            G3StageRightsLockV1,
            "g3-external-send-rights.830.v1",
            "rights_hash",
            contract="g3-external-send-rights.830.v1",
            parent_authorization_digest=parent_digest,
            stage=stage,
            purpose=purpose,
            run_schema_version=schema_version,
            role=role,
            provider=identity.provider,
            endpoint_origin="https://dashscope.aliyuncs.com",
            endpoint_path="/compatible-mode/v1/chat/completions",
            deployment_id=identity.deployment_id,
            call_ids=(call.call_id,),
            window_ids=(),
            artifacts=stage_refs_tuple,
            material_or_derivation_ids=(derivation_id,),
            data_categories=tuple(sorted(categories)),
            call_limit=1,
            input_token_ceiling=chain_row.input_token_ceiling,
            output_token_ceiling=chain_row.output_token_ceiling,
            time_limit_seconds=chain_row.time_limit_seconds,
            expires_at=base.expires_at,
            retry_limit=0,
        )
        stage_provenance = _hashed(
            G3StageProvenanceLockV1,
            "g3-stage-provenance.830.v1",
            "provenance_hash",
            contract="g3-stage-provenance.830.v1",
            stage=stage,
            artifacts=stage_refs_tuple,
            prior_terminal_receipt_sha256=prior_terminal.receipt_sha256,
        )
        resource = ResourceCaps(
            worker_limit=1,
            attempt_limit=1,
            time_limit_seconds=chain_row.time_limit_seconds,
            token_limit=chain_row.input_token_ceiling + chain_row.output_token_ceiling,
        )
        result = G3BoundedAdmissionPlanV1(
            **{
                **base.model_dump(mode="python"),
                "stage": stage,
                "purpose": purpose,
                "run_schema_version": schema_version,
                "run_id": run_id,
                "parent_authorization_digest": parent_digest,
                "prior_terminal_receipt_sha256": prior_terminal.receipt_sha256,
                "derived_stage_receipt": derived,
                "protocol_seed_lock": plan.protocol_seed_lock,
                "golden_slice_hash": plan.golden_slice_hash,
                "request_manifest": stage_manifest,
                "manifest_hash": stage_manifest.manifest_hash,
                "eligibility_lock": stage_eligibility,
                "eligibility_hash": stage_eligibility.eligibility_hash,
                "routing_lock": stage_routing,
                "routing_policy_hash": stage_routing.routing_policy_hash,
                "schema_lock": stage_schema,
                "schema_hash": stage_schema.schema_hash,
                "template_lock": stage_template,
                "template_lock_hash": stage_template.template_lock_hash,
                "approved_template_hashes": (approved_hash,),
                "dispatch_lock": stage_dispatch,
                "structured_dispatch_hash": stage_dispatch.structured_dispatch_hash,
                "approved_identities": (identity,),
                "model_plan_hash": canonical_model_plan_hash((identity,)),
                "deployment_roles_hash": canonical_model_identities_hash((identity,)),
                "stage_caps": stage_caps,
                "resource_caps": resource,
                "resource_caps_hash": resource.digest,
                "rights_lock": stage_rights,
                "rights_hash": stage_rights.rights_hash,
                "provenance_lock": stage_provenance,
                "provenance_hash": stage_provenance.provenance_hash,
            }
        )
        validate_g3_bounded_plan(result)
        validate_g3_parent_scope(parent.payload, result)
        for expected_path, payload in artifact_payload_by_path.items():
            written = write_store(payload, expected_path.name)
            assert written == expected_path
        stage_input_path = write_store(
            canonical_json(result.model_dump(mode="json", round_trip=True)),
            "stage-input.json",
        )
        prepared_path = runner.prepare_stage(
            parent_authorization=str(parent_path),
            stage=stage,
            stage_input=str(stage_input_path),
        )
        return result, prepared_path

    compile_request_bytes = canonical_json(
        compile_request.model_dump(mode="json", round_trip=True)
    )
    compile_plan, compile_admission = build_d_plan(
        stage="D_COMPILE",
        prior_terminal=recovered_terminal,
        run_id="fixture-g3-model-compile-live-chain",
        typed_payloads={
            "batch-concept-compile-request.830.g3.v1": compile_request_bytes
        },
    )
    compile_raw = canonical_json(
        fixture_candidate.model_compile_result.output.model_dump(
            mode="json", round_trip=True
        )
    ).decode()
    with respx.mock:
        compile_posted = respx.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        ).respond(
            status_code=200,
            headers={"content-type": "application/json", "x-request-id": "fake-d-compile"},
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": compile_raw}}
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            },
        )
        compile_terminal = await runner.run_stage(str(compile_admission))
        compile_stage_terminal_path = (
            ledger
            / "chains"
            / compile_plan.chain_manifest_hash
            / "stage-terminals"
            / "D_COMPILE.json"
        )
        compile_stage_terminal_path.unlink()
        recovered_compile_terminal = await runner.run_stage(str(compile_admission))
    assert compile_posted.call_count == 1
    assert recovered_compile_terminal.stage_output_sha256 == compile_terminal.stage_output_sha256
    compile_results = (
        ledger
        / "chains"
        / compile_plan.chain_manifest_hash
        / "stage-results"
        / "D_COMPILE"
    )
    model_compile_bytes = (compile_results / "model-compile-result.json").read_bytes()
    final_compile_bytes = (compile_results / "final-compile-result.json").read_bytes()
    if non_nfc:
        before_read = {str(path.relative_to(ledger)): path.read_bytes()
                       for path in ledger.rglob("*") if path.is_file()}
        reopened_stage, _, _, reopened_results = materializer_module._prior_stage(
            parent, parent_bytes, compile_plan.chain_manifest, "D_REVIEW"
        )
        assert reopened_stage == recovered_compile_terminal
        assert reopened_results["final"][1] == final_compile_bytes
        assert before_read == {str(path.relative_to(ledger)): path.read_bytes()
                              for path in ledger.rglob("*") if path.is_file()}
    review_plan, review_admission = build_d_plan(
        stage="D_REVIEW",
        prior_terminal=recovered_compile_terminal,
        run_id="fixture-g3-review-live-chain",
        typed_payloads={
            "batch-concept-compile-request.830.g3.v1": compile_request_bytes,
            "g3-d-model-compile-result.830.v1": model_compile_bytes,
            "g3-d-final-compile-result.830.v1": final_compile_bytes,
        },
    )
    final_result = __import__(
        "insurance_harness.knowledge_compiler.concept_compile_830_g2",
        fromlist=["CompileResult"],
    ).CompileResult.model_validate_json(final_compile_bytes)
    from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
        ValueScore,
        novel_page_ids,
    )

    human_score = ValueScore(
        business_value=20,
        reuse=15,
        evidence_quality=15,
        definability=10,
        novel_identity=5,
        name_stability=5,
    )
    review_wire = fixture_candidate.review_result.output.model_copy(
        update={
            "output_hash": bounded.compile_output_hash_g3(final_result.output),
            "page_scores": {
                page_id: human_score
                for page_id in novel_page_ids(compile_request.base_request, final_result.output)
            },
        }
    )
    review_raw = canonical_json(
        review_wire.model_dump(mode="json", round_trip=True)
    ).decode()
    with respx.mock:
        review_posted = respx.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        ).respond(
            status_code=200,
            headers={"content-type": "application/json", "x-request-id": "fake-d-review"},
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": review_raw}}
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            },
        )
        review_terminal = await runner.run_stage(str(review_admission))
    assert review_posted.call_count == 1
    review_results = (
        ledger
        / "chains"
        / review_plan.chain_manifest_hash
        / "stage-results"
        / "D_REVIEW"
    )
    review_result_bytes = (review_results / "review-result.json").read_bytes()
    candidate_bytes = (review_results / "candidate.json").read_bytes()
    from insurance_harness.knowledge_compiler.concept_compile_830_g2 import ReviewResult

    actual_review_result = ReviewResult.model_validate_json(review_result_bytes)
    actual_candidate = validate_batch_candidate(candidate_bytes)
    assert review_result_bytes == canonical_json(
        actual_review_result.model_dump(mode="json", round_trip=True)
    )
    assert candidate_bytes == canonical_json(
        actual_candidate.model_dump(mode="json", round_trip=True)
    )
    assert review_terminal.stage_output_sha256 == actual_candidate.candidate_hash
    assert actual_candidate.request == compile_request
    assert posted.call_count + compile_posted.call_count + review_posted.call_count == 3

    review_stage_terminal_path = (
        ledger
        / "chains"
        / review_plan.chain_manifest_hash
        / "stage-terminals"
        / "D_REVIEW.json"
    )
    review_stage_terminal_path.unlink()
    (review_results / "candidate.json").write_bytes(b"{}")
    unexpected_post = None
    with respx.mock:
        unexpected_post = respx.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        ).respond(status_code=500, json={"error": "must not send"})
        with pytest.raises(RuntimeError, match="G3 stage result conflict"):
            await runner.run_stage(str(review_admission))
    assert unexpected_post.call_count == 0
