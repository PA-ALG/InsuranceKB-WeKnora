"""Local publication planning, seed eligibility and atomic receipts; no commands or HTTP."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from insurance_harness.compilers.schema_fields.cards import cards_version
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.compilers.schema_fields.prompt import VALUE_PROTOCOL_VERSION
from insurance_harness.ingest import publication
from insurance_harness.ingest.registry import (
    MaterialEntry,
    ProductEntry,
    ProductRegistry,
    RegistryError,
)


@pytest.fixture
def registry() -> ProductRegistry:
    return ProductRegistry(
        contract="product-registry.v1", space_id="space", raw_kb_id="raw",
        products={product: ProductEntry(
            names=[product], clause_codes=[], schema_pack_id=f"pack-{product}", origin="created",
            materials=[MaterialEntry(knowledge_id=f"{product}-{suffix}", parse_attempt=attempt,
                                     sha256=digest * 64, role="terms", file_name=f"{suffix}.pdf")
                       for suffix, attempt, digest in (("z", 3, "b"), ("a", 2, "a"))],
        ) for product in ("a", "b")},
        pending=[], decisions=[],
    )


def output(registry: ProductRegistry, product: str) -> CompileOutput:
    entry = registry.products[product]
    return CompileOutput(
        entity_id=product, pack_id=entry.schema_pack_id, model="fake",
        materials=sorted(f"{m.knowledge_id}:{m.parse_attempt}:{m.sha256}" for m in entry.materials),
        cards_version=cards_version(),
        value_protocol=VALUE_PROTOCOL_VERSION,  # S12c-1: a current output carries the protocol
        material_roles={  # S5b-6: and each material's recorded role
            f"{m.knowledge_id}:{m.parse_attempt}:{m.sha256}": m.role for m in entry.materials
        },
    )


def save(root: Path, product: str, compiled: CompileOutput) -> bytes:
    path = root / product / "output.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = compiled.model_dump_json(indent=2).encode()
    path.write_bytes(data)
    return data


def test_plan_is_sorted_deduplicated_and_local(registry: ProductRegistry, tmp_path: Path) -> None:
    result = publication.plan(registry, tmp_path, ["b", "a", "b"])
    assert result.compile == result.publish == ["a", "b"]
    assert list(tmp_path.iterdir()) == []
    assert publication.plan(registry, tmp_path, []).model_dump() == {"compile": [], "publish": []}


@pytest.mark.parametrize("change", ["none", "materials", "cards", "bytes"])
def test_plan_compilation_and_publication_have_distinct_fingerprints(
    registry: ProductRegistry, tmp_path: Path, change: str,
) -> None:
    compiled = output(registry, "a")
    original = save(tmp_path / "compile", "a", compiled)
    publication._save_published(tmp_path, {"a": hashlib.sha256(original).hexdigest()})
    if change == "materials":
        compiled = compiled.model_copy(update={"materials": ["a-a:1:" + "a" * 64]})
    elif change == "cards":
        compiled = compiled.model_copy(update={"cards_version": "old"})
    save(tmp_path / "compile", "a", compiled)
    if change == "bytes":
        with (tmp_path / "compile/a/output.json").open("ab") as stream:
            stream.write(b"\n")
    result = publication.plan(registry, tmp_path, ["a"])
    assert result.compile == (["a"] if change in {"materials", "cards"} else [])
    assert result.publish == ([] if change == "none" else ["a"])


@pytest.mark.parametrize(
    "change", ["entity_id", "pack_id", "materials", "cards_version", "invalid"],
)
def test_seed_requires_all_four_conditions_and_tries_later_directories(
    registry: ProductRegistry, tmp_path: Path, change: str,
) -> None:
    bad, good, run = (tmp_path / name for name in ("bad", "good", "run"))
    original = output(registry, "a")
    wrong = original.model_copy(update={change: [] if change == "materials" else "wrong"})
    save(bad, "a", original if change == "invalid" else wrong)
    if change == "invalid":
        (bad / "a/output.json").write_bytes(b"\xff")
    expected = save(good, "a", original)
    dry = publication._prepare(registry, run, ["a"], [bad, good], dry_run=True)
    assert dry.compile == [] and dry.publish == ["a"]
    assert not run.exists()
    real = publication._prepare(registry, run, ["a"], [bad, good], dry_run=False)
    assert real == dry
    assert (run / "compile/a/output.json").read_bytes() == expected
    assert (good / "a/output.json").read_bytes() == expected


def test_existing_output_is_never_replaced_by_seed(
    registry: ProductRegistry, tmp_path: Path,
) -> None:
    run, seed = tmp_path / "run", tmp_path / "seed"
    existing = save(run / "compile", "a", output(registry, "a").model_copy(
        update={"cards_version": "old"},
    ))
    save(seed, "a", output(registry, "a"))
    result = publication._prepare(registry, run, ["a"], [seed], dry_run=False)
    assert result.compile == ["a"] and result.publish == ["a"]
    assert (run / "compile/a/output.json").read_bytes() == existing


def test_unknown_selection_precedes_any_seed_copy(
    registry: ProductRegistry, tmp_path: Path,
) -> None:
    run, seed = tmp_path / "run", tmp_path / "seed"
    save(seed, "a", output(registry, "a"))
    with pytest.raises(RegistryError, match="^PRODUCT_UNKNOWN$"):
        publication._prepare(registry, run, ["a", "unknown"], [seed], dry_run=False)
    assert not run.exists()


@pytest.mark.parametrize("document", [b"{private material", b"[]", b'{"a":"not-a-sha"}', b"\xff"])
def test_invalid_receipts_fail_with_only_a_code(
    registry: ProductRegistry, tmp_path: Path, document: bytes,
) -> None:
    (tmp_path / "published.json").write_bytes(document)
    with pytest.raises(publication.PublicationError, match="^PUBLISHED_INVALID$"):
        publication.plan(registry, tmp_path)


def test_receipt_replace_is_atomic_and_cleans_failed_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    old, new = {"a": "a" * 64}, {"a": "a" * 64, "b": "b" * 64}
    publication._save_published(tmp_path, old)

    def fail_replace(source: str, target: Path) -> None:
        assert json.loads(Path(source).read_text()) == new
        assert json.loads(target.read_text()) == old
        raise OSError("private material and local path")

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_replace)
        with pytest.raises(publication.PublicationError, match="^PUBLICATION_IO_ERROR$"):
            publication._save_published(tmp_path, new)
    assert json.loads((tmp_path / "published.json").read_text()) == old
    assert sorted(p.name for p in tmp_path.iterdir()) == ["published.json"]
    publication._save_published(tmp_path, new)
    assert json.loads((tmp_path / "published.json").read_text()) == new
