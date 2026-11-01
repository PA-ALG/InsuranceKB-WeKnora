"""The version data attribution reads and the evidence it records (PV-3 Spec §2.5, §2.8).

`RegisteredVersion` is what a v2 registry entry tells attribution about the filed version it
stands for. `VersionBasis` is the immutable evidence a training material's version judgement keeps
with its decision: the material's own date signals, every candidate with its verdict, the metadata
commit they were judged against, and who decided the version and the role.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Precision = Literal["year", "month", "day"]
SignalSource = Literal["file_name", "opening", "date_line"]
Verdict = Literal[
    "consistent",
    "partial",
    "date_conflict",
    "period_unknown",
    "type_conflict",
    "undated",
    "unbound",  # a version without its external key: shown, never a target (review R3)
]
Decider = Literal["machine", "person"]
_DATE = r"^\d{4}-\d{2}-\d{2}$"


class _Frozen(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class RegisteredVersion(_Frozen):
    version_key: str | None = None
    year_tag: int | None = None
    sale_start: str | None = Field(default=None, pattern=_DATE)
    sale_end: str | None = Field(default=None, pattern=_DATE)
    source_status: str | None = None
    plan_type: str | None = None
    basis_commit: str | None = None  # the pinned repository commit the entry's metadata came from


class DateSignal(_Frozen):
    value: str = Field(pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$")  # 2024, 2024-05 or 2024-05-27
    precision: Precision
    source: SignalSource


class VersionVerdict(_Frozen):
    product_id: str = Field(min_length=1)
    version_key: str | None = None
    verdict: Verdict


class VersionBasis(_Frozen):
    signals: tuple[DateSignal, ...] = ()
    material_period: tuple[str, str] | None = None  # the most precise signal, [start, end)
    candidates: tuple[VersionVerdict, ...] = ()  # the whole set, before any display cap
    metadata_commit: str | None = None
    version_decided_by: Decider | None = None
    role_decided_by: Decider | None = None
