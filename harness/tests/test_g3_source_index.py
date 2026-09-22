from __future__ import annotations

from pathlib import Path

import pytest

from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import evidence_for
from insurance_harness.knowledge_compiler.g3_source_index import (
    G3SourceIndexManifestV1,
    build_g3_source_index,
    load_g3_source_index_materials,
)
from tests.test_batch_entity_resolution_830_g3 import _corpus, _entry


def test_source_index_is_digest_bound_sharded_and_lazily_loaded() -> None:
    entries = (
        _entry(material_id="m-001", text="第一材料等待期九十日。"),
        _entry(material_id="m-002", text="第二材料免赔额一万元。"),
    )
    corpus = _corpus(*entries)
    native_sha = "a" * 64
    manifest, shards = build_g3_source_index(
        corpus,
        native_projection_sha256=native_sha,
        validator_version="g3-native-locator.830.v1",
        locator_builder=lambda source: (evidence_for(source, 0, len(source.text)),),
    )
    assert manifest.corpus_sha256 == corpus.corpus_sha256
    assert manifest.native_projection_sha256 == native_sha
    assert len(shards) == 2
    reads: list[str] = []

    def read_shard(digest: str) -> bytes:
        reads.append(digest)
        return shards[digest]

    loaded = load_g3_source_index_materials(
        manifest.canonical_bytes(), material_ids=("m-002",), read_shard=read_shard
    )
    assert tuple(loaded) == ("m-002",)
    assert len(reads) == 1
    assert loaded["m-002"].sources[0].text == entries[1].blocks[0].text
    assert loaded["m-002"].locators[0].revision_id == entries[1].blocks[0].revision_id

    bad = bytearray(shards[reads[0]])
    bad[-1] ^= 1
    with pytest.raises(ValueError, match="shard digest"):
        load_g3_source_index_materials(
            manifest.canonical_bytes(),
            material_ids=("m-002",),
            read_shard=lambda _: bytes(bad),
        )


def test_source_index_manifest_rejects_raw_identity_drift() -> None:
    corpus = _corpus(_entry(material_id="m-001", text="正文"))
    manifest, _ = build_g3_source_index(
        corpus,
        native_projection_sha256="a" * 64,
        validator_version="g3-native-locator.830.v1",
        locator_builder=lambda source: (evidence_for(source, 0, len(source.text)),),
    )
    value = manifest.model_dump(mode="json")
    value["native_projection_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="manifest hash"):
        G3SourceIndexManifestV1.model_validate(value)


def test_source_index_reopens_persisted_material_without_full_native_input(tmp_path: Path) -> None:
    from insurance_harness.knowledge_compiler import g3_source_index as source_index

    assert hasattr(source_index, "persist_g3_source_index"), "source index has no durable writer"
    corpus = _corpus(_entry(material_id="m-001", text="等待期为九十日。"))
    manifest, shards = build_g3_source_index(
        corpus,
        native_projection_sha256="a" * 64,
        validator_version="native.v1",
        locator_builder=lambda source: (evidence_for(source, 0, len(source.text)),),
    )
    digest = source_index.persist_g3_source_index(tmp_path, manifest, shards)
    loaded = source_index.reopen_g3_source_index(tmp_path, digest, material_ids=("m-001",))
    assert loaded["m-001"].sources == corpus.entries[0].blocks
    assert source_index.persist_g3_source_index(tmp_path, manifest, shards) == digest
    path = tmp_path / "sha256" / digest
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="digest"):
        source_index.reopen_g3_source_index(tmp_path, digest, material_ids=("m-001",))
