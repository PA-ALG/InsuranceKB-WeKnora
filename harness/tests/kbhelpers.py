"""change 007 测试构件：产品种子与 PredRecord 工厂（specs K2~K6）。"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from insurance_harness.compiler.models import Confidence, PredRecord
from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.goldenset.records import Evidence, TriState

BROCHURE = "产品说明书.pdf"  # official_desc，权威 2
TERMS = "保险条款.pdf"  # terms，权威 1


def seed_product(
    session: Session,
    *,
    code: str = "AXB001",
    name: str = "安心保两全保险",
    version_label: str = "2024版",
) -> tuple[InsuranceProduct, ProductVersion]:
    product = InsuranceProduct(
        product_code=code, canonical_name=name, category="endowment", status="在售"
    )
    session.add(product)
    session.flush()
    version = ProductVersion(product_id=product.id, version_label=version_label)
    session.add(version)
    session.flush()
    return product, version


def pred(
    field_id: str,
    *,
    value: str | None,
    tri_state: TriState = "present",
    doc: str = BROCHURE,
    page: int = 3,
    quote: str | None = None,
    field_name: str | None = None,
    confidence: Confidence = "high",
    pending_judge: bool = False,
) -> PredRecord:
    evidence = (
        []
        if tri_state == "unknown" or quote is None
        else [Evidence(page=page, quote=quote)]
    )
    return PredRecord(
        product_id="AXB001",
        product_name="安心保两全保险",
        doc=doc,
        field_id=field_id,
        field_name=field_name or field_id,
        value=value,
        tri_state=tri_state,
        evidence=evidence,
        annotator_model="test-fixture",
        schema_version="v1.1+test",
        created_at=datetime.now(UTC),
        confidence=confidence,
        pending_judge=pending_judge,
    )
