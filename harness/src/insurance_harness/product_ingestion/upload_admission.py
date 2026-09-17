"""Immutable upload control input on the existing product artifact store."""

import hashlib
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from insurance_harness.product_ingestion.artifact_tables import ProductArtifact
from insurance_harness.product_ingestion.upload_manifest import UploadManifest


def _binding(row):
    dependency = hashlib.sha256(("product-uploads.v1\0" + row.id).encode()).hexdigest()
    stage_id = str(uuid5(NAMESPACE_URL, f"product-stage:{row.space_id}:{row.id}:uploads"))
    job_id = str(uuid5(NAMESPACE_URL, f"product-stage-job:{stage_id}:{dependency}"))
    return dependency, job_id


def save_upload_manifest(session, row, manifest: UploadManifest):
    payload = manifest.model_dump_json().encode()
    dependency, job_id = _binding(row)
    session.add(
        ProductArtifact(
            run_id=row.id,
            space_id=row.space_id,
            stage_key="uploads",
            artifact_kind="upload_manifest",
            artifact_key="product",
            contract_name=manifest.contract,
            contract_version="1",
            dependency_sha256=dependency,
            payload=payload,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            origin="rule",
            origin_call_id=None,
            # Generation zero is the existing admission-control convention; this is
            # not a claimed worker output and never satisfies checkpoint completion.
            producer_job_id=job_id,
            producer_generation=0,
            created_at=row.created_at,
        )
    )


def read_upload_manifest(session, row):
    saved = session.scalar(
        select(ProductArtifact).where(
            ProductArtifact.run_id == row.id,
            ProductArtifact.artifact_kind == "upload_manifest",
            ProductArtifact.artifact_key == "product",
        )
    )
    if saved is None:
        return None  # Older admissions remain immutable and metadata-bound.
    dependency, job_id = _binding(row)
    if (
        saved.space_id != row.space_id
        or saved.producer_generation != 0
        or saved.producer_job_id != job_id
        or saved.stage_key != "uploads"
        or saved.dependency_sha256 != dependency
        or saved.contract_name != "product-upload-manifest.830.g3.v1"
        or saved.contract_version != "1"
        or hashlib.sha256(saved.payload).hexdigest() != saved.payload_sha256
    ):
        raise ValueError("upload manifest binding changed")
    manifest = UploadManifest.model_validate_json(saved.payload)
    if manifest.expected_upload_count != row.expected_upload_count:
        raise ValueError("upload manifest count changed")
    return manifest
