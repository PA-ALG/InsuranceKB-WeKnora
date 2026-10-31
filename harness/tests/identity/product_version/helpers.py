"""OpenSpec 041 ProductVersion resolution: shared fixture path and request helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.product.version_resolver import (
    ProductVersionQuarantine,
    ProductVersionResolutionRequest,
    ProductVersionResolver,
)

FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "product_version_resolver_041.json"


def _request(scope: KnowledgeScope, **updates: object) -> ProductVersionResolutionRequest:
    values: dict[str, object] = {
        "source_space_id": scope.space_id,
        "document_ref": "dataset/version-materials/test.pdf",
    }
    values.update(updates)
    return ProductVersionResolutionRequest.model_validate(values)


def _quarantine(
    resolver: ProductVersionResolver,
    request: ProductVersionResolutionRequest,
    reason_code: str,
) -> ProductVersionQuarantine:
    with pytest.raises(ProductVersionQuarantine) as caught:
        resolver.resolve(request)
    assert caught.value.reason_code == reason_code
    assert caught.value.candidate_version_ids == tuple(
        sorted(caught.value.candidate_version_ids)
    )
    return caught.value
