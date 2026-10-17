"""Shared Schema-pack catalog fixture for the product_ingestion tests.

The first-page routing tests left with product_ingestion.routing in S7a (the module was
unreachable from every entrypoint); the catalog fixture stays because other tests import it.
"""

from __future__ import annotations

import typing
from pathlib import Path

import pytest

from insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3 import SchemaPackCatalogV1


@pytest.fixture(scope="module")
def catalog() -> typing.Any:
    path = Path(__file__).parents[3] / "docs/insurance-kb/evidence/830-g3/catalog/catalog.json"
    return SchemaPackCatalogV1.model_validate_json(path.read_bytes())
