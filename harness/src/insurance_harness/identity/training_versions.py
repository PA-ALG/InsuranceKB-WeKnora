"""Training materials matched to a filed version by brand and date (PV-3 Spec §2; PV-0 §4.3).

Option A (user, 2026-11-01): a sales or training material that no clause code or title anchors is
matched by its brand and its own date signals to the registered versions of a v2 registry. The
whole candidate set is computed first, each candidate with a verdict; exactly one candidate, and a
consistent one, settles the material as a machine decision. Everything else goes to a person, who
may choose only consistent candidates; a material whose own dates contradict each other can only
be ignored. Materials correspond strictly to their year: no rule here ever widens a match.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal

from insurance_harness.identity.brands import brand_hits
from insurance_harness.identity.material_roles import role_signals
from insurance_harness.identity.text import fold
from insurance_harness.identity.version_basis import (
    DateSignal,
    RegisteredVersion,
    VersionBasis,
    VersionVerdict,
)

if TYPE_CHECKING:  # the attribution module imports this one
    from insurance_harness.identity.attribution import AttributionPolicy, RegisteredProduct

_LINES = re.compile(r"[\r\n]+")
_SOURCES = ("file_name", "opening", "date_line")
_RANK = {"year": 1, "month": 2, "day": 3}

Kind = Literal["unique", "candidates", "none", "signals_conflict", "undated", "families"]


@dataclass(frozen=True)
class Judgement:
    kind: Kind
    basis: VersionBasis
    product_id: str | None = None  # the one consistent version ("unique")
    choices: tuple[str, ...] = ()  # what a person may choose, besides ignoring


@dataclass(frozen=True)
class _Period:
    start: date
    end: date  # exclusive
    precision: str


def versioned(products: Sequence["RegisteredProduct"]) -> bool:
    """A v2 registry: its entries carry version data (PV-3 Spec §2.1)."""
    return any(product.version is not None for product in products)


def training_role(
    file_name: str, head: str, window: str, policy: "AttributionPolicy"
) -> str | None:
    """The training role from the policy's training words, only when no other role shows any
    signal (PV-3 Spec §2.2)."""
    if role_signals(file_name, head) - {policy.training_role}:
        return None
    text = _text(file_name, window)
    return policy.training_role if any(fold(w) in text for w in policy.training_signals) else None


def date_signals(
    file_name: str, head: str, window: str, policy: "AttributionPolicy"
) -> tuple[DateSignal, ...]:
    """The material's own dates: its file name, its opening and whole date lines (§2.4)."""
    found = [*_scan(fold(PurePosixPath(file_name).stem), "file_name", policy)]
    found += _scan(window, "opening", policy)
    for line in (fold(part) for part in _LINES.split(head)):
        found += [s for s in _scan(line, "date_line", policy, whole=True)]
    seen: set[tuple[str, str]] = set()
    kept = []
    for signal in sorted(found, key=lambda s: _SOURCES.index(s.source)):
        if (signal.value, signal.precision) not in seen:
            seen.add((signal.value, signal.precision))
            kept.append(signal)
    return tuple(kept)


def judge(
    file_name: str,
    head: str,
    window: str,
    products: Sequence["RegisteredProduct"],
    policy: "AttributionPolicy",
) -> Judgement:
    """The version judgement of one training material (§2.3–§2.7)."""
    commit = next((p.version.basis_commit for p in products if p.version is not None), None)
    hits = brand_hits(file_name, window, products, policy)
    family = [p for p in products if p.product_id in hits]
    signals = date_signals(file_name, head, window, policy)
    if len(set(hits.values())) > 1:
        return Judgement("families", VersionBasis(signals=signals, metadata_commit=commit))
    if not family:
        return Judgement("none", VersionBasis(signals=signals, metadata_commit=commit))
    text = _text(file_name, window)
    excluded = {p.product_id for p in family if _type_conflict(p, family, text, policy)}
    if not signals:
        verdicts = tuple(
            _verdict(p, "type_conflict" if p.product_id in excluded else "undated") for p in family
        )
        choices = tuple(p.product_id for p in family if p.product_id not in excluded)
        basis = VersionBasis(signals=signals, candidates=verdicts, metadata_commit=commit)
        return Judgement("undated", basis, choices=choices)
    material = _material_period(signals)
    if material is None:
        return Judgement("signals_conflict", VersionBasis(signals=signals, metadata_commit=commit))
    listed = []
    for product in family:
        verdict = _date_verdict(product.version, material)
        if verdict is not None:
            listed.append(
                _verdict(product, "type_conflict" if product.product_id in excluded else verdict)
            )
    basis = VersionBasis(
        signals=signals,
        material_period=(material.start.isoformat(), material.end.isoformat()),
        candidates=tuple(listed),
        metadata_commit=commit,
    )
    candidates = [v for v in listed if v.verdict != "type_conflict"]
    choices = tuple(v.product_id for v in candidates if v.verdict == "consistent")
    if not candidates:
        return Judgement("none", basis)
    if len(candidates) == 1 and candidates[0].verdict == "consistent":
        return Judgement("unique", basis, product_id=candidates[0].product_id, choices=choices)
    return Judgement("candidates", basis, choices=choices)


# Date signals -----------------------------------------------------------------------------------


def _scan(
    text: str, source: str, policy: "AttributionPolicy", *, whole: bool = False
) -> list[DateSignal]:
    """The valid dates in a text; a coarser date inside a finer one is not counted again."""
    found: list[tuple[int, int, DateSignal]] = []
    for spec in policy.date_patterns:
        matches = [re.fullmatch(spec.pattern, text)] if whole else re.finditer(spec.pattern, text)
        for match in matches:
            if match is not None and (signal := _signal(match, spec.precision, source, policy)):
                found.append((match.start(), match.end(), signal))
    return [
        signal
        for start, end, signal in found
        if not any(
            s <= start and end <= e and _RANK[o.precision] > _RANK[signal.precision]
            for s, e, o in found
        )
    ]


def _signal(
    match: re.Match[str], precision: str, source: str, policy: "AttributionPolicy"
) -> DateSignal | None:
    groups = match.groupdict()
    year = int(groups["y"])
    low, high = policy.date_years
    if not low <= year <= high:
        return None
    try:
        if precision == "year":
            value = f"{year:04d}"
        elif precision == "month":
            value = date(year, int(groups["m"]), 1).isoformat()[:7]
        else:
            value = date(year, int(groups["m"]), int(groups["d"])).isoformat()
    except ValueError:  # month 13, February 30: not a date
        return None
    return DateSignal(value=value, precision=precision, source=source)  # type: ignore[arg-type]


def _period(signal: DateSignal) -> _Period:
    parts = [int(part) for part in signal.value.split("-")]
    if signal.precision == "year":
        return _Period(date(parts[0], 1, 1), date(parts[0] + 1, 1, 1), "year")
    if signal.precision == "month":
        start = date(parts[0], parts[1], 1)
        end = (start + timedelta(days=32)).replace(day=1)
        return _Period(start, end, "month")
    day = date(parts[0], parts[1], parts[2])
    return _Period(day, day + timedelta(days=1), "day")


def _material_period(signals: Sequence[DateSignal]) -> _Period | None:
    """The most precise signal's period when every two signals nest; None when any do not."""
    periods = [_period(signal) for signal in signals]
    for a in periods:
        for b in periods:
            nested = (a.start <= b.start and b.end <= a.end) or (
                b.start <= a.start and a.end <= b.end
            )
            if not nested:
                return None
    return min(periods, key=lambda p: (p.end - p.start, p.start))


# Candidates -------------------------------------------------------------------------------------


def _sale_period(version: RegisteredVersion | None) -> tuple[date, date | None] | None:
    """[start, end); an open end only while the source says it is on sale, else unknown."""
    if version is None or version.sale_start is None:
        return None
    start = date.fromisoformat(version.sale_start)
    if version.sale_end is not None:
        return start, date.fromisoformat(version.sale_end)
    return (start, None) if version.source_status == "on_sale" else None


def _date_verdict(version: RegisteredVersion | None, material: _Period) -> str | None:
    """The verdict of one version, or None when it is not a candidate at all (§2.5)."""
    tagged = version is not None and version.year_tag == material.start.year
    period = _sale_period(version)
    if period is None:
        return "period_unknown" if tagged else None
    start, end = period
    overlaps = start < material.end and (end is None or material.start < end)
    if not (tagged or overlaps):
        return None
    inside = start <= material.start and (end is None or material.end <= end)
    if material.precision == "year" or inside:
        return "consistent"
    return "partial" if overlaps else "date_conflict"


def _verdict(product: "RegisteredProduct", verdict: str) -> VersionVerdict:
    key = product.version.version_key if product.version is not None else None
    return VersionVerdict(product_id=product.product_id, version_key=key, verdict=verdict)  # type: ignore[arg-type]


# Type words -------------------------------------------------------------------------------------


def _text(file_name: str, window: str) -> str:
    return (fold(PurePosixPath(file_name).stem) + "\n" + window).casefold()


def _type_conflict(
    product: "RegisteredProduct",
    family: Sequence["RegisteredProduct"],
    text: str,
    policy: "AttributionPolicy",
) -> bool:
    """The material's type words contradict what this version states explicitly (§2.6)."""
    names = " ".join(fold(name) for name in product.names).casefold()
    groups = policy.plan_type_groups
    stated = {
        g.plan_type for g in groups if any(fold(w).casefold() in text for w in g.material_words)
    }
    plan = product.version.plan_type if product.version is not None else None
    if plan not in {g.plan_type for g in groups}:
        plan = next(
            (
                g.plan_type
                for g in groups
                if any(fold(w).casefold() in names for w in g.version_words)
            ),
            None,
        )
    if len(stated) == 1 and plan is not None and plan not in stated:
        return True
    riders = [fold(word).casefold() for word in policy.rider_words]
    if any(word in text for word in riders) and not any(word in names for word in riders):
        return True
    named = {e for p in family for e in _editions(p, policy) if _edition_core(e) in text}
    own = _editions(product, policy)
    return len(named) == 1 and bool(own) and not named <= own


def _editions(product: "RegisteredProduct", policy: "AttributionPolicy") -> set[str]:
    return {
        match.group(1).casefold()
        for name in product.names
        for match in re.finditer(policy.edition_pattern, fold(name))
    }


def _edition_core(edition: str) -> str:
    """悦享版 → 悦享; a one-character core such as A款 stays whole."""
    core = edition[:-1]
    return core if len(core) >= 2 else edition
