from insurance_harness.product_ingestion.upload_manifest import UploadManifest, UploadMaterial


def test_upload_manifest_preserves_first_ordinal_and_deduplicates_content() -> None:
    manifest = UploadManifest.from_uploads(
        [
            UploadMaterial(
                ordinal=0, original_filename="first.pdf", file_size=4, file_sha256="a" * 64
            ),
            UploadMaterial(
                ordinal=1, original_filename="renamed.pdf", file_size=4, file_sha256="a" * 64
            ),
            UploadMaterial(
                ordinal=2, original_filename="terms.pdf", file_size=5, file_sha256="b" * 64
            ),
        ]
    )
    assert manifest.expected_upload_count == 2
    assert [item.ordinal for item in manifest.materials] == [0, 1]
    assert [item.original_filename for item in manifest.materials] == ["first.pdf", "terms.pdf"]
    assert manifest.duplicate_upload_count == 1


def test_upload_manifest_rejects_invalid_or_noncontiguous_input() -> None:
    import pytest

    with pytest.raises(ValueError):
        UploadManifest.from_uploads(
            [
                UploadMaterial(
                    ordinal=1, original_filename="a.pdf", file_size=4, file_sha256="a" * 64
                )
            ]
        )
    with pytest.raises(ValueError):
        UploadMaterial(ordinal=0, original_filename="a.pdf", file_size=0, file_sha256="a" * 64)


def test_upload_manifest_rejects_invalid_wire_form() -> None:
    import json

    import pytest

    row = {"ordinal": 0, "original_filename": "a.pdf", "file_size": 4, "file_sha256": "a" * 64}
    for payload in (
        {"contract": "wrong", "materials": [row], "duplicate_upload_count": 0},
        {
            "contract": "product-upload-manifest.830.g3.v1",
            "materials": [],
            "duplicate_upload_count": 0,
        },
        {
            "contract": "product-upload-manifest.830.g3.v1",
            "materials": [row, row],
            "duplicate_upload_count": 0,
        },
        {
            "contract": "product-upload-manifest.830.g3.v1",
            "materials": [{**row, "ordinal": 1}],
            "duplicate_upload_count": 0,
        },
    ):
        with pytest.raises(ValueError):
            UploadManifest.model_validate_json(json.dumps(payload))
