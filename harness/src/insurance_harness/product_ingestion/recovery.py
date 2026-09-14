"""Explicit, immutable source-sealing recovery; never a parse or field retry."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.product_ingestion.models import OriginalKnowledgeRef, ProductScope

RECOVERY_PREFIX = "processing-recovery.v1:"
RECOVERY_V2_PREFIX = "processing-recovery.v2:"
RECOVERY_KIND = "processing_recovery_plan"


class ProcessingRecoveryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    contract: Literal["product-processing-recovery-plan.830.v1"] = (
        "product-processing-recovery-plan.830.v1"
    )
    mode: Literal["RECAPTURE_COMPLETED_SOURCES"] = "RECAPTURE_COMPLETED_SOURCES"
    scope: ProductScope
    origin_run_id: str = Field(min_length=1)
    origin_version: int = Field(gt=0)
    upload_run_id: str = Field(min_length=1)
    materials: tuple[OriginalKnowledgeRef, ...]

    def encoded(self) -> bytes:
        return self.model_dump_json().encode()

    def digest(self) -> str:
        return hashlib.sha256(self.encoded()).hexdigest()


class SourceSnapshotReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    knowledge_id: str = Field(min_length=1)
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class SealedSourceRecoveryPlan(ProcessingRecoveryPlan):
    contract: Literal["product-processing-recovery-plan.830.v2"] = (
        "product-processing-recovery-plan.830.v2"
    )
    mode: Literal["REUSE_SEALED_SOURCES"] = "REUSE_SEALED_SOURCES"
    source_snapshots: tuple[SourceSnapshotReference, ...]


def material_references(run):
    return tuple(
        OriginalKnowledgeRef(
            knowledge_id=row.knowledge_id,
            original_filename=row.original_filename,
            upload_ordinal=row.upload_ordinal,
        )
        for row in run.materials
    )
