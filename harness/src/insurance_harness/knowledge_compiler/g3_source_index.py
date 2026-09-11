"""Digest-bound, sharded source index for bounded G3 extraction."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictStr, StringConstraints, model_validator

from .batch_entity_resolution_830_g3 import BatchCorpusV1
from .concept_free_wiki_830_g2 import Evidence, SourceBlock, verify_evidence

Hash = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Name = Annotated[StrictStr, StringConstraints(min_length=1, max_length=512)]


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda item: item.model_dump(mode="json", round_trip=True),
    ).encode()


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class G3SourceIndexShardV1(_Frozen):
    contract: Literal["g3-source-index-shard.830.v1"] = "g3-source-index-shard.830.v1"
    material_id: Name
    corpus_entry_sha256: Hash
    sources: tuple[SourceBlock, ...] = Field(min_length=1)
    locators: tuple[Evidence, ...]


class G3SourceIndexShardRefV1(_Frozen):
    material_id: Name
    corpus_entry_sha256: Hash
    shard_sha256: Hash
    source_count: int = Field(gt=0, strict=True)
    locator_count: int = Field(ge=0, strict=True)


class G3SourceIndexManifestV1(_Frozen):
    contract: Literal["g3-source-index-manifest.830.v1"] = "g3-source-index-manifest.830.v1"
    corpus_sha256: Hash
    native_projection_sha256: Hash
    validator_version: Name
    shards: tuple[G3SourceIndexShardRefV1, ...]
    manifest_sha256: Hash

    def canonical_bytes(self) -> bytes:
        return _json_bytes(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        ids = tuple(row.material_id for row in self.shards)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("source index shards must be canonical unique")
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if self.manifest_sha256 != hashlib.sha256(_json_bytes(payload)).hexdigest():
            raise ValueError("source index manifest hash mismatch")
        return self


def build_g3_source_index(
    corpus: BatchCorpusV1,
    *,
    native_projection_sha256: str,
    validator_version: str,
    locator_builder: Callable[[SourceBlock], Sequence[Evidence]],
) -> tuple[G3SourceIndexManifestV1, dict[str, bytes]]:
    """Validate each source once and produce one content-addressed shard per material."""

    refs: list[G3SourceIndexShardRefV1] = []
    blobs: dict[str, bytes] = {}
    for entry in corpus.entries:
        locators = tuple(locator for source in entry.blocks for locator in locator_builder(source))
        for locator in locators:
            verify_evidence(locator, entry.blocks)
        shard = G3SourceIndexShardV1(
            material_id=entry.material_id,
            corpus_entry_sha256=entry.entry_sha256,
            sources=entry.blocks,
            locators=locators,
        )
        raw = _json_bytes(shard.model_dump(mode="json"))
        digest = hashlib.sha256(raw).hexdigest()
        if digest in blobs:
            raise ValueError("source index shard digest collision")
        blobs[digest] = raw
        refs.append(
            G3SourceIndexShardRefV1(
                material_id=entry.material_id,
                corpus_entry_sha256=entry.entry_sha256,
                shard_sha256=digest,
                source_count=len(entry.blocks),
                locator_count=len(locators),
            )
        )
    payload = {
        "contract": "g3-source-index-manifest.830.v1",
        "corpus_sha256": corpus.corpus_sha256,
        "native_projection_sha256": native_projection_sha256,
        "validator_version": validator_version,
        "shards": refs,
    }
    wire = json.loads(_json_bytes(payload))
    manifest = G3SourceIndexManifestV1.model_validate(
        {**wire, "manifest_sha256": hashlib.sha256(_json_bytes(wire)).hexdigest()}
    )
    return manifest, blobs


def load_g3_source_index_materials(
    manifest_raw: bytes,
    *,
    material_ids: Sequence[str],
    read_shard: Callable[[str], bytes],
) -> Mapping[str, G3SourceIndexShardV1]:
    """Load and verify only the requested material shards."""

    try:
        manifest = G3SourceIndexManifestV1.model_validate_json(manifest_raw)
    except ValueError as exc:
        raise ValueError("invalid source index manifest") from exc
    requested = tuple(sorted(set(material_ids)))
    by_id = {row.material_id: row for row in manifest.shards}
    if set(requested) - set(by_id):
        raise ValueError("source index material is absent")
    loaded: dict[str, G3SourceIndexShardV1] = {}
    for material_id in requested:
        ref = by_id[material_id]
        raw = read_shard(ref.shard_sha256)
        if hashlib.sha256(raw).hexdigest() != ref.shard_sha256:
            raise ValueError("source index shard digest mismatch")
        try:
            shard = G3SourceIndexShardV1.model_validate_json(raw)
        except ValueError as exc:
            raise ValueError("invalid source index shard") from exc
        if (
            shard.material_id != ref.material_id
            or shard.corpus_entry_sha256 != ref.corpus_entry_sha256
            or len(shard.sources) != ref.source_count
            or len(shard.locators) != ref.locator_count
        ):
            raise ValueError("source index shard projection mismatch")
        for locator in shard.locators:
            verify_evidence(locator, shard.sources)
        loaded[material_id] = shard
    return loaded


def _index_store(root: Path) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    store = root / "sha256"
    store.mkdir(exist_ok=True, mode=0o700)
    for directory in (root, store):
        info = directory.stat(follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            raise ValueError("invalid source index directory")
    return store


def _read_index_blob(store: Path, digest: str) -> bytes:
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("invalid source index digest")
    fd = os.open(store / digest, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise ValueError("invalid source index blob")
        raw = stream.read()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("source index blob digest mismatch")
    return raw


def persist_g3_source_index(
    root: Path,
    manifest: G3SourceIndexManifestV1,
    shards: Mapping[str, bytes],
) -> str:
    """Persist immutable shards first and the complete manifest last, without replacing data."""
    manifest = G3SourceIndexManifestV1.model_validate(manifest)
    expected = {ref.shard_sha256 for ref in manifest.shards}
    if set(shards) != expected:
        raise ValueError("source index shard set mismatch")
    load_g3_source_index_materials(
        manifest.canonical_bytes(),
        material_ids=tuple(ref.material_id for ref in manifest.shards),
        read_shard=shards.__getitem__,
    )
    store = _index_store(root)
    raw = manifest.canonical_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    for key, payload in (*sorted(shards.items()), (digest, raw)):
        if hashlib.sha256(payload).hexdigest() != key:
            raise ValueError("source index blob digest mismatch")
        try:
            fd = os.open(store / key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if _read_index_blob(store, key) != payload:
                raise ValueError("source index immutable blob conflict") from None
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
    fd = os.open(store, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return digest


def reopen_g3_source_index(
    root: Path,
    manifest_digest: str,
    *,
    material_ids: Sequence[str],
) -> Mapping[str, G3SourceIndexShardV1]:
    """Reopen only selected material shards; no original native JSON is decoded."""
    store = _index_store(root)
    return load_g3_source_index_materials(
        _read_index_blob(store, manifest_digest),
        material_ids=material_ids,
        read_shard=lambda digest: _read_index_blob(store, digest),
    )


__all__ = [
    "G3SourceIndexManifestV1",
    "G3SourceIndexShardRefV1",
    "G3SourceIndexShardV1",
    "build_g3_source_index",
    "load_g3_source_index_materials",
    "persist_g3_source_index",
    "reopen_g3_source_index",
]
