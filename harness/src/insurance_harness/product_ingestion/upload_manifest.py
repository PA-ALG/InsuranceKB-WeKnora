"""Small immutable upload admission manifest, independent of source processing."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UploadMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ordinal: int = Field(ge=0)
    original_filename: str = Field(min_length=1, max_length=1024)
    file_size: int = Field(gt=0)
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class UploadManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    contract: Literal["product-upload-manifest.830.g3.v1"] = "product-upload-manifest.830.g3.v1"
    materials: tuple[UploadMaterial, ...]
    duplicate_upload_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_unique_contiguous(self) -> UploadManifest:
        if not self.materials or any(
            row.ordinal != index for index, row in enumerate(self.materials)
        ):
            raise ValueError("manifest materials must have contiguous ordinals")
        if len({(row.file_sha256, row.file_size) for row in self.materials}) != len(self.materials):
            raise ValueError("manifest content must be unique")
        return self

    @property
    def expected_upload_count(self) -> int:
        return len(self.materials)

    @classmethod
    def from_uploads(cls, uploads: list[UploadMaterial]) -> UploadManifest:
        if not uploads or any(row.ordinal != index for index, row in enumerate(uploads)):
            raise ValueError("uploads must have contiguous ordinals")
        seen: set[tuple[str, int]] = set()
        unique: list[UploadMaterial] = []
        for row in uploads:
            fingerprint = (row.file_sha256, row.file_size)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            unique.append(row.model_copy(update={"ordinal": len(unique)}))
        return cls(materials=tuple(unique), duplicate_upload_count=len(uploads) - len(unique))
