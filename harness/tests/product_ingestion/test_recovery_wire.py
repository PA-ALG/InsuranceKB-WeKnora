"""Historical recovery plans keep their byte and digest identities."""

from __future__ import annotations

import pytest

from insurance_harness.product_ingestion.models import OriginalKnowledgeRef, ProductScope
from insurance_harness.product_ingestion.recovery import (
    ProcessingRecoveryPlan,
    RecordedBaseIdentity,
    RecordedIdentityRecoveryPlan,
    RecordedIdentityReference,
    SealedSourceRecoveryPlan,
    SourceSnapshotReference,
)

SCOPE = ProductScope(
    tenant_id="tenant",
    space_id="space",
    raw_knowledge_base_id="raw-kb",
    wiki_knowledge_base_id="wiki-kb",
)
MATERIAL = OriginalKnowledgeRef(
    knowledge_id="knowledge", original_filename="source.pdf", upload_ordinal=0
)
SNAPSHOT = SourceSnapshotReference(knowledge_id="knowledge", payload_sha256="a" * 64)
IDENTITY = RecordedIdentityReference(
    call_id="identity-call",
    record_sha256="b" * 64,
    request_sha256="c" * 64,
    raw_sha256="d" * 64,
    input_sha256="e" * 64,
    model_policy_sha256="f" * 64,
    prompt_policy_sha256="0" * 64,
    base_identity=RecordedBaseIdentity(
        release_id="release", activation_epoch=3, snapshot_sha256="1" * 64
    ),
)
V1_BYTES = (
    b'{"contract":"product-processing-recovery-plan.830.v1",'
    b'"mode":"RECAPTURE_COMPLETED_SOURCES","scope":{"tenant_id":"tenant",'
    b'"space_id":"space","raw_knowledge_base_id":"raw-kb",'
    b'"wiki_knowledge_base_id":"wiki-kb"},"origin_run_id":"origin",'
    b'"origin_version":7,"upload_run_id":"upload","materials":'
    b'[{"knowledge_id":"knowledge","original_filename":"source.pdf",'
    b'"upload_ordinal":0}]}'
)
V2_BYTES = (
    b'{"contract":"product-processing-recovery-plan.830.v2",'
    b'"mode":"REUSE_SEALED_SOURCES","scope":{"tenant_id":"tenant",'
    b'"space_id":"space","raw_knowledge_base_id":"raw-kb",'
    b'"wiki_knowledge_base_id":"wiki-kb"},"origin_run_id":"origin",'
    b'"origin_version":7,"upload_run_id":"upload","materials":'
    b'[{"knowledge_id":"knowledge","original_filename":"source.pdf",'
    b'"upload_ordinal":0}],"source_snapshots":[{"knowledge_id":"knowledge",'
    b'"payload_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}'
)
V3_BYTES = (
    b'{"contract":"product-processing-recovery-plan.830.v3",'
    b'"mode":"REPLAY_RECORDED_IDENTITY","scope":{"tenant_id":"tenant",'
    b'"space_id":"space","raw_knowledge_base_id":"raw-kb",'
    b'"wiki_knowledge_base_id":"wiki-kb"},"origin_run_id":"origin",'
    b'"origin_version":7,"upload_run_id":"upload","materials":'
    b'[{"knowledge_id":"knowledge","original_filename":"source.pdf",'
    b'"upload_ordinal":0}],"source_snapshots":[{"knowledge_id":"knowledge",'
    b'"payload_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}],'
    b'"identity_call":{"call_id":"identity-call",'
    b'"record_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
    b'"request_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",'
    b'"raw_sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",'
    b'"input_sha256":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",'
    b'"model_policy_sha256":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",'
    b'"prompt_policy_sha256":"0000000000000000000000000000000000000000000000000000000000000000",'
    b'"base_identity":{"release_id":"release","activation_epoch":3,'
    b'"snapshot_sha256":"1111111111111111111111111111111111111111111111111111111111111111"}}}'
)


@pytest.mark.parametrize(
    ("plan", "field_order", "expected_bytes", "expected_digest"),
    [
        pytest.param(
            ProcessingRecoveryPlan(
                scope=SCOPE,
                origin_run_id="origin",
                origin_version=7,
                upload_run_id="upload",
                materials=(MATERIAL,),
            ),
            (
                "contract",
                "mode",
                "scope",
                "origin_run_id",
                "origin_version",
                "upload_run_id",
                "materials",
            ),
            V1_BYTES,
            "d70a8a8d5b9de4c355cc40046d180f11f704e12e7e47ccc49b61247ca8d28899",
            id="v1-recapture",
        ),
        pytest.param(
            SealedSourceRecoveryPlan(
                scope=SCOPE,
                origin_run_id="origin",
                origin_version=7,
                upload_run_id="upload",
                materials=(MATERIAL,),
                source_snapshots=(SNAPSHOT,),
            ),
            (
                "contract",
                "mode",
                "scope",
                "origin_run_id",
                "origin_version",
                "upload_run_id",
                "materials",
                "source_snapshots",
            ),
            V2_BYTES,
            "dc5a57991c7e9a1851738f2c57a5a476e986172196d1c1a432379b52ea29a005",
            id="v2-sealed-sources",
        ),
        pytest.param(
            RecordedIdentityRecoveryPlan(
                scope=SCOPE,
                origin_run_id="origin",
                origin_version=7,
                upload_run_id="upload",
                materials=(MATERIAL,),
                source_snapshots=(SNAPSHOT,),
                identity_call=IDENTITY,
            ),
            (
                "contract",
                "mode",
                "scope",
                "origin_run_id",
                "origin_version",
                "upload_run_id",
                "materials",
                "source_snapshots",
                "identity_call",
            ),
            V3_BYTES,
            "c84c318ba34271bef9a1913f0c6ce012239e5152975cdb1522df6ff3eb0eaa7e",
            id="v3-recorded-identity",
        ),
    ],
)
def test_recovery_plan_wire_identity_is_stable(
    plan: ProcessingRecoveryPlan | SealedSourceRecoveryPlan | RecordedIdentityRecoveryPlan,
    field_order: tuple[str, ...],
    expected_bytes: bytes,
    expected_digest: str,
) -> None:
    assert tuple(type(plan).model_fields) == field_order
    assert plan.encoded() == expected_bytes
    assert plan.digest() == expected_digest
