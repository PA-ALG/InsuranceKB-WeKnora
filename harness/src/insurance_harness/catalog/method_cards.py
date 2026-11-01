"""The sales-method cards: what a method's five aspects hold (SK-2 Spec §2.2; SK-0 §2.1).

Versioned data, never code: the five predicates in their fixed order, each with its definition,
value type and whether it is quoted verbatim, plus the patterns that route a method to people
because it mentions product information (SK-0 §3.2). The predicates are exactly the fields the
TrustPolicy lets a sales-method material serve, so a method card and the evidence rule never drift
apart. The card version is part of the compiler identity.
"""

import re
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from insurance_harness.catalog.trust_policy import load_trust_policy

NonBlank = Annotated[str, StringConstraints(pattern=r"\S")]
METHOD_ROLE = "sales_method"  # the material role whose scoped fields the cards are


class MethodCardsError(ValueError):
    """A stable code, without the data or a local path."""

    def __init__(self) -> None:
        self.code = "METHOD_CARDS_INVALID"
        super().__init__(self.code)


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class MethodCard(_Strict):
    predicate: NonBlank
    title: NonBlank
    definition: NonBlank
    includes: tuple[NonBlank, ...]
    excludes: tuple[NonBlank, ...]
    value_type: Literal["text", "list"]
    verbatim: bool


class ProductInfoPattern(_Strict):
    signal: Literal["amount", "percentage", "age"]
    pattern: NonBlank  # matched against folded text (NFKC, without white space)

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, pattern: str) -> str:
        try:
            re.compile(pattern)
        except re.error:
            raise ValueError("a pattern that does not compile") from None
        return pattern


class MethodPresentation(_Strict):
    """How readers show the methods (SK-3 Spec §2.2): never part of a value request."""

    display_name: NonBlank
    reading_note: NonBlank  # the first line of every method field text a model reads
    notices: dict[NonBlank, NonBlank]  # a method entity's notice flag -> the sentence it adds


class MethodCards(_Strict):
    version: NonBlank
    entity_type: NonBlank
    owner_module: NonBlank
    review_pack: NonBlank
    presentation: MethodPresentation
    cards: tuple[MethodCard, ...] = Field(min_length=1)
    product_info_patterns: tuple[ProductInfoPattern, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> "MethodCards":
        predicates = [card.predicate for card in self.cards]
        if len(set(predicates)) != len(predicates):
            raise ValueError("a predicate is listed twice")
        if set(predicates) != load_trust_policy().restricted_fields(METHOD_ROLE):
            raise ValueError("the cards are exactly the sales-method fields")
        signals = [pattern.signal for pattern in self.product_info_patterns]
        if len(set(signals)) != len(signals):
            raise ValueError("a signal is listed twice")
        return self


def parse_method_cards(text: str) -> MethodCards:
    try:
        return MethodCards.model_validate_json(text)
    except (ValidationError, ValueError) as error:
        raise MethodCardsError() from error


@lru_cache(maxsize=1)
def load_method_cards() -> MethodCards:
    """The cards shipped with this package."""
    try:
        return parse_method_cards(
            files(__package__).joinpath("method_cards.json").read_text(encoding="utf-8")
        )
    except OSError as error:
        raise MethodCardsError() from error
