"""Schema 注册表：基线 YAML → 运行时 schema（spec G1；docs/insurance-kb/07）。"""

from .loader import SchemaLoadError, load_schema_registry, stable_field_id
from .models import (
    FieldSpec,
    GlossaryTerm,
    ProductLineSchema,
    RiskLevel,
    SchemaRegistry,
    ValueType,
)

__all__ = [
    "FieldSpec",
    "GlossaryTerm",
    "ProductLineSchema",
    "RiskLevel",
    "SchemaLoadError",
    "SchemaRegistry",
    "ValueType",
    "load_schema_registry",
    "stable_field_id",
]
