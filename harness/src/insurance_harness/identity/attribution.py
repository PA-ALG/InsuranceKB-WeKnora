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
"""

import hashlib
import re
import unicodedata
from collections.abc import Callable, Sequence
from functools import lru_cache
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from insurance_harness.identity.material_roles import load_material_roles, role_of

TERMS = "terms"  # the material role that prints the clause filing code and may create a product
_SHA256 = r"^[0-9a-f]{64}$"
_QUALIFIER = re.compile(r"\([^()]*\)")  # after NFKC, as in 年金保险(分红型) or 意外(A款)医疗保险

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
    guide_title_pattern: str = Field(min_length=1)  # the name in the reader guide, one group
    created_id_prefix: str = Field(min_length=1)
    created_id_hex: int = Field(ge=8, le=64)
    classifications: tuple[Classification, ...] = Field(min_length=1)

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
        except re.error as error:
            raise ValueError("invalid attribution pattern") from error
        if patterns[2].groups != 1 or not self.title_prefix_pattern.startswith("^"):
            raise ValueError("the guide pattern needs one group and the prefix an anchor")
        suffixes = [_fold(entry.suffix) for entry in self.classifications]
        if len(set(suffixes)) != len(suffixes):
            raise ValueError("duplicate classification suffix")
        return self

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
    candidates: tuple[str, ...] = ()
    policy_ref: str


@lru_cache(maxsize=1)
def load_attribution_policy() -> AttributionPolicy:
    """The policy shipped with this package."""
    try:
        text = files(__package__).joinpath("attribution_policy.json").read_text(encoding="utf-8")
        return AttributionPolicy.model_validate_json(text)
    except (OSError, ValidationError) as error:
        raise AttributionPolicyError("ATTRIBUTION_POLICY_INVALID") from error


def _fold(text: str) -> str:
    """NFKC without whitespace or private-use code points (font bullets such as U+F043 carry no
    text, and extraction puts them in front of titles)."""
    return "".join(
        c
        for c in unicodedata.normalize("NFKC", text)
        if not c.isspace() and unicodedata.category(c) != "Co"
    )


def _title(text: str, policy: AttributionPolicy) -> str:
    """The product name a title starts with, or "" when it cannot be read."""
    left, right = (_fold(mark) for mark in policy.title_brackets)
    if text.startswith(left):
        end = text.find(right, len(left))
        name = text[len(left) : end] if end > 0 else ""
    else:
        # A marker at the very start counts: then there is no title, and the body is never one.
        ends = [i for i in (text.find(_fold(mark)) for mark in policy.title_end_markers) if i >= 0]
        name = text[: min(ends)] if ends else ""
    return name if len(name) <= policy.max_title_chars else ""


def _head_title(window: str, own_code: str | None, policy: AttributionPolicy) -> str:
    """The title at the start, after page numbers, labels and the terms' own code line."""
    text = re.sub(policy.title_prefix_pattern, "", window, count=1)
    if own_code is not None and text.startswith(own_code):
        text = text[len(own_code) :]
        text = text.removeprefix(_fold(policy.own_code_marker))
    return _title(text, policy)


def _guide_title(head: str, policy: AttributionPolicy) -> str:
    """The product the reader guide introduces ("阅读指引<name>产品提供…"), or "".

    Only a fallback for terms whose start carries no title: text extraction may interleave the
    verification line or drop part of the name there, so it never overrides the start title.
    """
    match = re.search(policy.guide_title_pattern, head.replace(_fold(policy.own_code_marker), ""))
    name = match.group(1) if match else ""
    return name if len(name) <= policy.max_title_chars else ""


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
    base = name
    while (stripped := _QUALIFIER.sub("", base)) != base:
        base = stripped
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
) -> Attribution:
    """The attribution of one uploaded material against the registered products (Spec §2.3).

    The keyword arguments carry what a person confirmed (S5b-3c-1 Spec §2.1): the product the
    material belongs to, which skips identifying it by code or title; its role, in place of the
    recognised one; and the pack for terms whose title no classification suffix matches.
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
    role = role or role_of(upload.file_name, upload.head)
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
        p for p in products if code is not None and code in {_fold(c) for c in p.clause_codes}
    ]
    if chosen is not None:
        # A person named the product; its code may confirm it, never point elsewhere, also when
        # the file is one this product already holds.
        if by_code and by_code != [chosen]:
            return decided("QUARANTINE", "anchor_conflict", **anchors)
        if owners:
            return decided("DUPLICATE", "duplicate_file", product_id=chosen.product_id)
        return _existing(chosen, "confirmed_by_person", decided, role, code, own_code)
    # The start names the product; the reader guide only stands in when the start has no title.
    title = _head_title(window, own_code, policy) or _guide_title(head, policy)
    named = [p for p in products if title and title in {_fold(n) for n in p.names}]
    named = named or _named_inside(title, products)
    # Both anchors must agree: a code whose product the title does not name is a conflict, also
    # when the title is missing, too long or names nothing registered.
    if len(by_code) > 1 or (by_code and by_code[0] not in named):
        return decided("QUARANTINE", "anchor_conflict", **anchors)
    if by_code:
        return _existing(by_code[0], "matched_by_clause_code", decided, role, code, own_code)
    if len(named) == 1:
        return _existing(named[0], "matched_by_name", decided, role, code, own_code)
    if named:
        return decided(
            "NEEDS_CONFIRM",
            "multiple_products",
            candidates=tuple(p.product_id for p in named),
            **anchors,
        )
    if role != TERMS or own_code is None or not title:
        return decided("QUARANTINE", "no_product_anchor", **anchors)

    pack = _pack(title, policy) or pack
    if pack is None:
        return decided("NEEDS_CONFIRM", "pack_unresolved", display_name=title, **anchors)
    product_id = (
        policy.created_id_prefix
        + hashlib.sha256(own_code.encode()).hexdigest()[: policy.created_id_hex]
    )
    if any(p.product_id == product_id for p in products):
        return decided("QUARANTINE", "anchor_conflict", **anchors)
    return decided(
        "CREATE",
        "new_product",
        product_id=product_id,
        display_name=title,
        schema_pack_id=pack,
        **anchors,
    )


def _existing(
    product: RegisteredProduct,
    reason: str,
    decided: Callable[..., Attribution],
    role: str | None,
    code: str | None,
    own_code: str | None,
) -> Attribution:
    """A registered product's material: a supplement, a new version or a question (§2.3 step 5)."""
    anchors = {"product_id": product.product_id, "role": role, "clause_code": code}
    if role is None:
        return decided(
            "NEEDS_CONFIRM", "role_unresolved", candidates=(product.product_id,), **anchors
        )
    known = {_fold(c) for c in product.clause_codes}
    if role == TERMS and own_code is not None and own_code not in known:
        replaced = tuple(sorted(m.knowledge_id for m in product.materials if m.role == TERMS))
        return decided("NEW_VERSION", "new_clause_code", replaces=replaced, **anchors)
    if any(m.role == role for m in product.materials):
        return decided(
            "NEEDS_CONFIRM", "same_role_differs", candidates=(product.product_id,), **anchors
        )
    return decided("SUPPLEMENT", reason, **anchors)
