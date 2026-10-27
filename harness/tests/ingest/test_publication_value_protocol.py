"""S12c-1 acceptance (protected, written by Claude): publication planning recompiles an output
of an older value protocol and reuses one of the current protocol (Spec
docs/design/slices/S12c-1-取值协议v2.md §4). Local only; no commands or HTTP.
"""

import hashlib
from pathlib import Path

import pytest

from insurance_harness.compilers.schema_fields.cards import cards_version
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.compilers.schema_fields.prompt import VALUE_PROTOCOL_VERSION
from insurance_harness.ingest import publication
from insurance_harness.ingest.registry import MaterialEntry, ProductEntry, ProductRegistry


@pytest.fixture
def registry() -> ProductRegistry:
    return ProductRegistry(
        contract="product-registry.v1", space_id="space", raw_kb_id="raw",
        products={"a": ProductEntry(
            names=["a"], clause_codes=[], schema_pack_id="pack-a", origin="created",
            materials=[MaterialEntry(knowledge_id="a-1", parse_attempt=1, sha256="b" * 64,
                                     role="terms", file_name="terms.pdf")],
        )},
        pending=[], decisions=[],
    )


def stored(root: Path, registry: ProductRegistry, protocol: str | None) -> bytes:
    entry = registry.products["a"]
    output = CompileOutput(
        entity_id="a", pack_id=entry.schema_pack_id, model="fake",
        materials=sorted(f"{m.knowledge_id}:{m.parse_attempt}:{m.sha256}" for m in entry.materials),
        cards_version=cards_version(), value_protocol=protocol,
    )
    path = root / "compile" / "a" / "output.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = output.model_dump_json(indent=2).encode()
    path.write_bytes(data)
    publication._save_published(root, {"a": hashlib.sha256(data).hexdigest()})
    return data


@pytest.mark.parametrize("protocol", [None, "2026-10-01.0"])
def test_an_output_of_an_older_value_protocol_is_recompiled(
    registry: ProductRegistry, tmp_path: Path, protocol: str | None,
) -> None:
    stored(tmp_path, registry, protocol)
    result = publication.plan(registry, tmp_path, ["a"])
    assert result.compile == ["a"] and result.publish == ["a"]


def test_an_output_of_the_current_value_protocol_is_reused(
    registry: ProductRegistry, tmp_path: Path,
) -> None:
    stored(tmp_path, registry, VALUE_PROTOCOL_VERSION)
    result = publication.plan(registry, tmp_path, ["a"])
    assert result.compile == [] and result.publish == []
