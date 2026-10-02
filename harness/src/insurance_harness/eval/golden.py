"""Validated Golden records and canonical prediction inputs (blueprint §5.1)."""

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from insurance_harness.eval.normalize import normalize_text

State = Literal["present", "absent_explicitly", "unknown"]
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class GoldenEvidence(BaseModel):
    """Immutable source identity and a nonempty, one-based page citation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document: NonBlank
    document_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")]
    page: int = Field(ge=1, strict=True)
    quote: NonBlank


class ValueComponent(BaseModel):
    """A required atom with at least one nonempty alternative phrasing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonBlank
    accepted: tuple[str, ...] = Field(min_length=1)

    @field_validator("accepted")
    @classmethod
    def validate_accepted(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not normalize_text(value) for value in values):
            raise ValueError("accepted alternatives must not be blank")
        return values


class Prediction(BaseModel):
    """Only present predictions carry a value; evidence is scored separately."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pack_id: NonBlank
    product_id: NonBlank
    field_key: NonBlank
    state: State
    value: str | None = None

    @model_validator(mode="after")
    def validate_state_value(self) -> Self:
        if self.state == "present":
            if self.value is None or not normalize_text(self.value):
                raise ValueError("present requires a nonempty value")
        elif self.value is not None:
            raise ValueError("non-present states require value=None")
        return self

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.pack_id, self.product_id, self.field_key


class GoldenItem(Prediction):
    """Expert or offline judge expectations, including strict evidence invariants."""

    evidence: list[GoldenEvidence] = Field(default_factory=list)
    components: list[ValueComponent] = Field(default_factory=list)
    forbidden: tuple[str, ...] = ()
    judged_by: Annotated[str, StringConstraints(pattern=r"^(human|legacy|model):\S.*$")]
    note: str | None = None

    @field_validator("forbidden")
    @classmethod
    def validate_forbidden(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not normalize_text(value) for value in values):
            raise ValueError("forbidden terms must not be blank")
        return values

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.state == "unknown" and self.evidence:
            raise ValueError("unknown requires no evidence")
        if self.state != "unknown" and not self.evidence:
            raise ValueError("present and absent_explicitly require evidence")
        return self
