"""The sales-method taxonomy: method signals and applicability labels (SK-0 §2.2, SK-1 §2.1).

Versioned data, never code: which words mark a sales-method material, how many different ones a
material needs, and the labels a method's applicability is expressed in. Insurance-category labels
are the attribution policy's classifications, the same labels navigation groups products by, so a
method and a product of one category meet without any cross-reference.
"""

import unicodedata
from functools import lru_cache
from importlib.resources import files
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.identity.attribution import load_attribution_policy

_Label = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]*(:[a-z][a-z_]*)?$")]
_PREFIXES = {
    "general": "scope:",
    "plan_types": "plan_type:",
    "life_stages": "life_stage:",
    "sales_stages": "sales_stage:",
}


class SalesTaxonomyError(ValueError):
    """A stable code, without the data or a local path."""

    def __init__(self) -> None:
        self.code = "SALES_TAXONOMY_INVALID"
        super().__init__(self.code)


def fold(text: str) -> str:
    """Width-folded (NFKC) and without white space: how signals and words are compared."""
    return "".join(c for c in unicodedata.normalize("NFKC", text) if not c.isspace())


class Term(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    label: _Label
    words: tuple[str, ...] = Field(min_length=1)


class SalesTaxonomy(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    version: str = Field(min_length=1)
    basis: str = Field(min_length=1)
    method_signals: tuple[str, ...] = Field(min_length=1)
    min_signals: int = Field(ge=2)
    insurance_categories: tuple[Term, ...] = Field(min_length=1)
    general: Term
    plan_types: tuple[Term, ...]
    life_stages: tuple[Term, ...]
    sales_stages: tuple[Term, ...]

    @model_validator(mode="after")
    def _consistent(self) -> "SalesTaxonomy":
        groups: dict[str, tuple[Term, ...]] = {
            "insurance_categories": self.insurance_categories,
            "general": (self.general,),
            "plan_types": self.plan_types,
            "life_stages": self.life_stages,
            "sales_stages": self.sales_stages,
        }
        labels = [term.label for terms in groups.values() for term in terms]
        if len(set(labels)) != len(labels):
            raise ValueError("a label is listed twice")
        for name, prefix in _PREFIXES.items():
            if any(not term.label.startswith(prefix) for term in groups[name]):
                raise ValueError("a label without its dimension's prefix")
        classifications = {c.classification for c in load_attribution_policy().classifications}
        if any(term.label not in classifications for term in self.insurance_categories):
            raise ValueError("an insurance category that is not a classification")
        signals = [fold(word) for word in self.method_signals]
        if not all(signals) or len(set(signals)) != len(signals):
            raise ValueError("a blank or repeated method signal")
        for terms in groups.values():
            words = [fold(word) for term in terms for word in term.words]
            if not all(words) or len(set(words)) != len(words):
                raise ValueError("a blank word, or one word under two labels")
        if self.min_signals > len(signals):
            raise ValueError("more signals required than listed")
        return self

    def insurance_labels(self) -> tuple[str, ...]:
        return tuple(term.label for term in self.insurance_categories)


def parse_sales_taxonomy(text: str) -> SalesTaxonomy:
    try:
        return SalesTaxonomy.model_validate_json(text)
    except (ValidationError, ValueError) as error:
        raise SalesTaxonomyError() from error


@lru_cache(maxsize=1)
def load_sales_taxonomy() -> SalesTaxonomy:
    """The taxonomy shipped with this package."""
    try:
        return parse_sales_taxonomy(
            files(__package__).joinpath("sales_taxonomy.json").read_text(encoding="utf-8")
        )
    except OSError as error:
        raise SalesTaxonomyError() from error
