"""Resolve an admitted original without rewriting an earlier upload's metadata."""

from insurance_harness.jobs import NonRetryableJobError


async def lookup_material(platform, scope, run_id, ordinal, manifest, *, knowledge_id=None):
    item = await platform.lookup_upload(scope, run_id, ordinal)
    original_binding = item is not None
    if manifest is None:
        # Existing runs predate fingerprint admission and retain their old binding.
        if item is not None and knowledge_id is not None and item["knowledge_id"] != knowledge_id:
            raise NonRetryableJobError("ORIGINAL_UPLOAD_BINDING_CHANGED")
        return item
    if not 0 <= ordinal < len(manifest.materials):
        raise NonRetryableJobError("UPLOAD_MANIFEST_ORDINAL_CHANGED")
    expected = manifest.materials[ordinal]
    if item is None:
        item = await platform.lookup_file_by_sha256(
            scope, expected.file_sha256, knowledge_id=knowledge_id
        )
    if item is None:
        return None
    if (
        item.get("file_sha256") != expected.file_sha256
        or item.get("file_size") != expected.file_size
        or item.get("type") != "file"
        or (knowledge_id is not None and item.get("knowledge_id") != knowledge_id)
    ):
        raise NonRetryableJobError("UPLOAD_FINGERPRINT_BINDING_CHANGED")
    if original_binding:
        return {**item, "original_upload_run_id": run_id, "original_upload_ordinal": ordinal}
    return {
        **item,
        "original_upload_run_id": item.get("original_upload_run_id"),
        "original_upload_ordinal": item.get("original_upload_ordinal"),
    }
