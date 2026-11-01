"""Which product a newly uploaded material belongs to (S5b-1 Spec).

Blueprint §6.1 (IDENTITY_RESOLVED) and §7.3: the decision rests only on deterministic anchors —
the clause filing code that terms print, and the full product name a material's title carries —
and when they do not settle it the material goes to a person or waits in quarantine; ambiguity is
never merged automatically. The rules are versioned data (attribution_policy.json); this module
only applies them. It calls no model, reads nothing but its arguments and the packaged policy, and
does not depend on the order of the registry.

Names are compared as whole titles, not searched in the text: a product name can be part of another
one (…终身寿险 inside …终身寿险(分红型)), and a substring search would file a new product as a new
version of the shorter one.

Sales and training materials, and Office files of no recognised role, often print only a brand
(S11c Spec §2.5). When no anchor settles them, the products whose brand they carry are offered to a
person as candidates; a brand is never an anchor, so even one candidate is only a question.

With the pinned version catalog (PV-1), a clause code is first matched to a filed version (PV-0
appendix A §1.3), and new terms of a registered name are a new entry beside it, never a replacement.
"""

import hashlib
import re
from collections.abc import Callable, Sequence
from functools import lru_cache
from importlib.resources import files
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from insurance_harness.identity.brands import brand_candidates, unqualified
from insurance_harness.identity.material_roles import load_material_roles, role_of
from insurance_harness.identity.text import fold as _fold
from insurance_harness.identity.title_lines import line_titles, title_pattern
from insurance_harness.identity.versions import VersionIndex, match_version, normal_clause_code

TERMS = "terms"  # the material role that prints the clause filing code and may create a product
_SHA256 = r"^[0-9a-f]{64}$"

# REPLACE and IGNORED only follow a person's choice (S5b-3c-1); attribute() never returns them.
Outcome = Literal[
    "DUPLICATE",
    "SUPPLEMENT",
    "NEW_VERSION",
    "CREATE",
    "NEEDS_CONFIRM",
    "QUARANTINE",
    "REPLACE",
    "IGNORED",
]


class AttributionPolicyError(ValueError):
    """A caller-safe code; never a document name or its text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AttributionInputError(ValueError):
    """The registry cannot be judged against (a caller-safe code)."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _Frozen(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class Classification(_Frozen):
    suffix: str = Field(min_length=1)
    classification: str = Field(pattern=r"^[a-z][a-z_]*$")
    schema_pack_id: str = Field(min_length=1)


class AttributionPolicy(_Frozen):
    version: str = Field(min_length=1)
    basis: str = Field(min_length=1)
    anchor_chars: int = Field(gt=0)
    clause_code_pattern: str = Field(min_length=1)
    own_code_marker: str = Field(min_length=1)  # printed right after a terms' own code (S5b-5)
    title_brackets: tuple[str, str]
    title_end_markers: tuple[str, ...] = Field(min_length=1)
    max_title_chars: int = Field(gt=0)
    title_prefix_pattern: str = Field(min_length=1)  # page numbers and labels before a title
    issuer_names: tuple[str, ...]  # the insurer's name, printed above a title (S5b-7)
    guide_title_pattern: str = Field(min_length=1)  # the name in the reader guide, one group
    # A whole title line anywhere on the first pages (S5b-7): 《name》, then at most one listed
    # qualifier and one listed document word, nothing else; a line with an exclusion is no title.
    title_line_qualifiers: tuple[str, ...]
    title_line_documents: tuple[str, ...] = Field(min_length=1)
    title_line_exclusions: tuple[str, ...]
    created_id_prefix: str = Field(min_length=1)
    created_id_hex: int = Field(ge=8, le=64)
    classifications: tuple[Classification, ...] = Field(min_length=1)
    # Brand candidates (S11c Spec §2.5): which materials are offered by brand, and how a brand is
    # read from a registered name and matched; each year pattern has one two-digit group.
    brand_roles: tuple[str, ...]
    brand_extensions: tuple[str, ...]
    brand_prefixes: tuple[str, ...]
    brand_min_chars: int = Field(gt=0)
    brand_max_candidates: int = Field(gt=0)
    upload_year_pattern: str = Field(min_length=1)
    product_year_patterns: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> "AttributionPolicy":
        try:
            patterns = [
                re.compile(text)
                for text in (
                    self.clause_code_pattern,
                    self.title_prefix_pattern,
                    self.guide_title_pattern,
                )
            ]
            years = [re.compile(t) for t in (self.upload_year_pattern, *self.product_year_patterns)]
        except re.error as error:
            raise ValueError("invalid attribution pattern") from error
        if patterns[2].groups != 1 or not self.title_prefix_pattern.startswith("^"):
            raise ValueError("the guide pattern needs one group and the prefix an anchor")
        words = (*self.issuer_names, *self.title_line_qualifiers, *self.title_line_documents)
        if not all(_fold(word) for word in (*words, *self.title_line_exclusions)):
            raise ValueError("a blank issuer name or title line word")
        if any(year.groups != 1 for year in years):
            raise ValueError("a year pattern needs one group")
        if not all(_fold(text) for text in (*self.brand_prefixes, *self.brand_extensions)):
            raise ValueError("a blank brand prefix or extension")
        if not set(self.brand_roles) <= {role.role for role in load_material_roles().roles}:
            raise ValueError("a brand role that is not a material role")
        suffixes = [_fold(entry.suffix) for entry in self.classifications]
        if len(set(suffixes)) != len(suffixes):
            raise ValueError("duplicate classification suffix")
        return self

    @property
    def title_line_pattern(self) -> str:
        """The whole-line title, the name its one group (S5b-7 Spec §2.3)."""
        qualifiers = [_fold(word) for word in self.title_line_qualifiers]
        documents = [_fold(word) for word in self.title_line_documents]
        return title_pattern(qualifiers, documents, self.max_title_chars)

    @property
    def policy_ref(self) -> str:
        return f"attribution-policy@{self.version}"


class RegisteredMaterial(_Frozen):
    knowledge_id: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)
    role: str = Field(min_length=1)


class RegisteredProduct(_Frozen):
    product_id: str = Field(min_length=1)
    names: tuple[str, ...] = Field(min_length=1)  # the canonical name first, then approved aliases
    clause_codes: tuple[str, ...]
    schema_pack_id: str = Field(min_length=1)
    materials: tuple[RegisteredMaterial, ...] = ()
    version_key: str | None = None  # the filed version, planCode-versionNo (PV-1)


class Upload(_Frozen):
    knowledge_id: str = Field(min_length=1)
    file_name: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)
    head: str  # the text of the first pages, in page order


class Attribution(_Frozen):
    outcome: Outcome
    reason: str
    product_id: str | None = None
    role: str | None = None
    clause_code: str | None = None
    display_name: str | None = None
    schema_pack_id: str | None = None
    replaces: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()  # for NEW_VERSION: the registered entry of the same name
    version_key: str | None = None  # of the entry CREATE or NEW_VERSION adds, if catalogued
    policy_ref: str


@lru_cache(maxsize=1)
def load_attribution_policy() -> AttributionPolicy:
    """The policy shipped with this package."""
    try:
        text = files(__package__).joinpath("attribution_policy.json").read_text(encoding="utf-8")
        return AttributionPolicy.model_validate_json(text)
    except (OSError, ValidationError) as error:
        raise AttributionPolicyError("ATTRIBUTION_POLICY_INVALID") from error


def _title(text: str, policy: AttributionPolicy) -> str:
    """The product name a title starts with, or "" when it cannot be read."""
    left, right = (_fold(mark) for mark in policy.title_brackets)
    if text.startswith(left):
        end = text.find(right, len(left))
        name = text[len(left) : end] if end > 0 else ""
        after = text[end + len(right) : end + len(right) + 4] if end > 0 else ""
        if any(_fold(word) in after for word in policy.title_line_exclusions):
            return ""  # 《name》不适用…, 《name》并非…: an explanation, not a title (S5b-7)
    else:
        # A marker at the very start counts: then there is no title, and the body is never one.
        ends = [i for i in (text.find(_fold(mark)) for mark in policy.title_end_markers) if i >= 0]
        name = text[: min(ends)] if ends else ""
    return name if len(name) <= policy.max_title_chars else ""


def _head_title(window: str, own_code: str | None, policy: AttributionPolicy) -> str:
    """The title at the start, after page numbers, labels, the insurer's name and the terms' own
    code line."""
    text = window
    issuers = [_fold(name) for name in policy.issuer_names]
    while (stripped := _strip_prefix(text, policy.title_prefix_pattern, issuers)) != text:
        text = stripped  # page numbers, labels and the insurer may come together, in any order
    if own_code is not None and text.startswith(own_code):
        text = text[len(own_code) :]
        text = text.removeprefix(_fold(policy.own_code_marker))
    return _title(text, policy)


def _strip_prefix(text: str, pattern: str, issuers: Sequence[str]) -> str:
    issuer = next((name for name in issuers if text.startswith(name)), "")
    return text[len(issuer) :] if issuer else re.sub(pattern, "", text, count=1)


def _guide_title(head: str, policy: AttributionPolicy) -> str:
    """The product the reader guide introduces ("阅读指引<name>产品提供…"), or "".

    Only a fallback for terms whose start carries no title, and it fails closed (S5b-5 §2.2): one
    guide must start near the start, every guide must name the same product, and the name must
    carry no code, verification line or end word, which extraction mixes in when it garbles.
    """
    matches = list(re.finditer(policy.guide_title_pattern, head))
    if not any(match.start() < policy.anchor_chars for match in matches):
        return ""
    names = {match.group(1) for match in matches}
    if len(names) != 1:
        return ""
    name = names.pop()
    polluted = (
        re.search(policy.clause_code_pattern, name)
        or _fold(policy.own_code_marker) in name
        or any(_fold(marker) in name for marker in policy.title_end_markers)
    )
    return "" if polluted or not name or len(name) > policy.max_title_chars else name


def _own_codes(head: str, policy: AttributionPolicy) -> set[str]:
    """Codes printed with the verification line that follows a terms' own code (S5b-5)."""
    marked = f"({policy.clause_code_pattern}){re.escape(_fold(policy.own_code_marker))}"
    return {match.group(1) for match in re.finditer(marked, head)}


def _named_inside(title: str, products: Sequence[RegisteredProduct]) -> list[RegisteredProduct]:
    """Two or more products whose names appear in a title, none inside a longer appearance."""
    spans = []
    for product in products:
        for name in {_fold(n) for n in product.names}:
            start = title.find(name)
            while start >= 0:
                spans.append((start, start + len(name), product))
                start = title.find(name, start + 1)
    whole = [
        span
        for span in spans
        if not any(
            o[0] <= span[0] and span[1] <= o[1] and o[1] - o[0] > span[1] - span[0] for o in spans
        )
    ]
    found = {span[2].product_id: span[2] for span in whole}
    return [found[key] for key in sorted(found)] if len(found) > 1 else []


def _pack(name: str, policy: AttributionPolicy) -> str | None:
    base = unqualified(name)
    hits = [entry for entry in policy.classifications if base.endswith(_fold(entry.suffix))]
    return max(hits, key=lambda entry: len(_fold(entry.suffix))).schema_pack_id if hits else None


def attribute(
    upload: Upload,
    registry: Sequence[RegisteredProduct],
    policy: AttributionPolicy | None = None,
    *,
    product: str | None = None,
    role: str | None = None,
    pack: str | None = None,
    catalog: VersionIndex | None = None,
) -> Attribution:
    """The attribution of one uploaded material against the registered products (Spec §2.3).

    The keyword arguments carry what a person confirmed (S5b-3c-1 Spec §2.1): the product the
    material belongs to, which skips identifying it by code or title; its role, in place of the
    recognised one; and the pack for terms whose title no classification suffix matches. With the
    pinned version catalog (PV-1 §3) a code is first matched to a filed version.
    """
    policy = policy or load_attribution_policy()

    def decided(outcome: Outcome, reason: str, **fields: object) -> Attribution:
        return Attribution.model_validate(
            {"outcome": outcome, "reason": reason, "policy_ref": policy.policy_ref, **fields}
        )

    if len({p.product_id for p in registry}) != len(registry):
        raise AttributionInputError("REGISTRY_DUPLICATE_PRODUCT")
    products = sorted(registry, key=lambda p: p.product_id)
    chosen = next((p for p in products if p.product_id == product), None)
    if (
        (product is not None and chosen is None)
        or (role is not None and role not in {r.role for r in load_material_roles().roles})
        or (pack is not None and pack not in {c.schema_pack_id for c in policy.classifications})
    ):
        raise AttributionInputError("CHOICE_INVALID")
    owners = sorted(
        {p.product_id for p in products for m in p.materials if m.sha256 == upload.sha256}
    )
    if chosen is None:
        if len(owners) == 1:
            return decided("DUPLICATE", "duplicate_file", product_id=owners[0])
        if owners:
            return decided("NEEDS_CONFIRM", "multiple_products", candidates=tuple(owners))
    elif owners and chosen.product_id not in owners:
        return decided("QUARANTINE", "anchor_conflict")

    head = _fold(upload.head)
    window = head[: policy.anchor_chars]
    if not window:
        if chosen is not None and owners:  # no text, so no code to contradict the file
            return decided("DUPLICATE", "duplicate_file", product_id=chosen.product_id)
        return decided("QUARANTINE", "text_unavailable")
    lines = line_titles(
        upload.head, policy.title_line_pattern, policy.title_line_exclusions, _fold
    )
    # Title lines only add role evidence to the opening, so a conflict stays a conflict; terms are
    # never read through them (S5b-7 Spec §2.3).
    if role is None and (role := role_of(upload.file_name, upload.head)) != TERMS:
        role = role_of(upload.file_name, upload.head, "".join(lines.values()))
    # A terms' own code is the one printed with the verification line (S5b-5), wherever it sits
    # in the first pages; older terms that open with their code keep the S5b-1 rule. Any other
    # code only cites one (after a label, or in a brochure's body): it may confirm a registered
    # product whose name the title carries, but never creates a product or a new version.
    marked = _own_codes(head, policy)
    match = re.search(policy.clause_code_pattern, window)
    own_code = next(iter(marked)) if len(marked) == 1 else None
    if own_code is None and not marked and match and match.start() == 0:
        own_code = match.group(0)  # S5b-1: older terms open with their own code
    code = own_code or (match.group(0) if match else None)
    anchors = {"role": role, "clause_code": code}
    if len(marked) > 1:
        return decided("QUARANTINE", "anchor_conflict", **anchors)

    by_code = [
        p
        for p in products
        if code is not None and code in {normal_clause_code(c) for c in p.clause_codes}
    ]
    key, by_key = None, False
    if catalog is not None and code is not None:
        found = match_version(code, products, catalog, policy.clause_code_pattern)
        if found.kind in {"conflict", "shared"}:
            reason = "shared_clause_code" if found.kind == "shared" else "anchor_conflict"
            return decided("QUARANTINE", reason, **anchors)
        key, by_key = found.version_key, found.by_key
        if found.kind == "registered":
            by_code = [p for p in products if p.product_id == found.product_id]
    created = _created_id(own_code, policy) if own_code is not None else None
    version = (created, key, any(p.product_id == created for p in products))
    if chosen is not None:
        # A person named the product; its code may confirm it, never point elsewhere, also when
        # the file is one this product already holds.
        if by_code and by_code != [chosen]:
            return decided("QUARANTINE", "anchor_conflict", **anchors)
        if owners:
            return decided("DUPLICATE", "duplicate_file", product_id=chosen.product_id)
        return _existing(chosen, "confirmed_by_person", decided, role, code, own_code, version)
    # The start names the product; the reader guide only stands in when the start has no title.
    title = _head_title(window, own_code, policy) or (
        _guide_title(head, policy) if role == TERMS else ""
    )
    named = [p for p in products if title and title in {_fold(n) for n in p.names}]
    named = named or _named_inside(title, products)
    if not named and lines and role != TERMS:  # confirms a registered product, never creates
        named = [p for p in products if {_fold(n) for n in p.names} & lines.keys()]
        if len(lines) > 1 and len(named) < 2:  # titles of other products, unregistered
            return decided("QUARANTINE", "anchor_conflict", **anchors)
    # Both anchors must agree: a code whose product the title does not name is a conflict, also
    # when the title is missing, too long or names nothing registered.
    if len(by_code) > 1 or (by_code and by_code[0] not in named):
        return decided("QUARANTINE", "anchor_conflict", **anchors)
    if by_code and by_key:  # its own code is not one of the entry's: still the same version
        return _existing(by_code[0], "matched_by_version_key", decided, role, code, None, version)
    if by_code:
        reason = "matched_by_clause_code"
        return _existing(by_code[0], reason, decided, role, code, own_code, version)
    if len(named) == 1:
        return _existing(named[0], "matched_by_name", decided, role, code, own_code, version)
    if named:
        return decided(
            "NEEDS_CONFIRM",
            "multiple_products",
            candidates=tuple(p.product_id for p in named),
            **anchors,
        )
    extension = PurePosixPath(upload.file_name).suffix.casefold()
    office = extension in {e.casefold() for e in policy.brand_extensions}
    if role in policy.brand_roles or (role is None and office):
        if brands := brand_candidates(upload, window, products, policy):
            return decided("NEEDS_CONFIRM", "brand_candidates", candidates=tuple(brands), **anchors)
    if role != TERMS or own_code is None or not title:
        return decided("QUARANTINE", "no_product_anchor", **anchors)

    pack = _pack(title, policy) or pack
    if pack is None:
        return decided("NEEDS_CONFIRM", "pack_unresolved", display_name=title, **anchors)
    if version[2]:  # the created ID is already registered
        return decided("QUARANTINE", "anchor_conflict", **anchors)
    return decided(
        "CREATE",
        "new_product",
        product_id=created,
        display_name=title,
        schema_pack_id=pack,
        version_key=key,
        **anchors,
    )


def _created_id(own_code: str, policy: AttributionPolicy) -> str:
    """The internal ID of the entry a terms' own code creates (S5b-1; PV-0 appendix A §1.1)."""
    digest = hashlib.sha256(own_code.encode()).hexdigest()[: policy.created_id_hex]
    return policy.created_id_prefix + digest


def _existing(
    product: RegisteredProduct,
    reason: str,
    decided: Callable[..., Attribution],
    role: str | None,
    code: str | None,
    own_code: str | None,
    version: tuple[str | None, str | None, bool],
) -> Attribution:
    """A registered product's material: a supplement, a new version or a question (§2.3 step 5).

    New terms of its name are a new entry beside it (PV-1 §3): the created ID, its version key and
    whether that ID is taken come in `version`; the registered entry is kept as the candidate.
    """
    anchors = {"product_id": product.product_id, "role": role, "clause_code": code}
    if role is None:
        return decided(
            "NEEDS_CONFIRM", "role_unresolved", candidates=(product.product_id,), **anchors
        )
    known = {normal_clause_code(c) for c in product.clause_codes}
    if role == TERMS and own_code is not None and own_code not in known:
        created, key, taken = version
        if taken:
            return decided("QUARANTINE", "anchor_conflict", role=role, clause_code=code)
        return decided(
            "NEW_VERSION",
            "new_clause_code",
            product_id=created,
            role=role,
            clause_code=code,
            display_name=product.names[0],
            schema_pack_id=product.schema_pack_id,
            candidates=(product.product_id,),
            version_key=key,
        )
    if any(m.role == role for m in product.materials):
        return decided(
            "NEEDS_CONFIRM", "same_role_differs", candidates=(product.product_id,), **anchors
        )
    return decided("SUPPLEMENT", reason, **anchors)
