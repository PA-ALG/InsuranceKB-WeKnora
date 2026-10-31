"""How a question for a person is worded and identified on the platform (S5b-3c-2 Spec §2.1, §3.2).

The text is versioned data (confirmation_wording.json); the revision identifies the question, its
place in the material's decision history and the wording version, so a question asked again after
being set aside, or reworded, is a new platform item rather than a closed one.
"""

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable
from functools import lru_cache
from importlib.resources import files

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from insurance_harness.bundle.client import ConfirmationInput, ConfirmationOption
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.identity.attribution import load_attribution_policy
from insurance_harness.identity.confirmation import Choice, ConfirmationError, choices
from insurance_harness.identity.material_roles import load_material_roles
from insurance_harness.ingest.registry import PendingEntry, ProductRegistry

SUBJECT_PREFIX = "material:"
_SUBJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")  # the platform's (S5b-3a)
_CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]")
_REASONS = {
    "multiple_products",
    "brand_candidates",  # S11c: added without a new version, as no asked question changes
    "pack_unresolved",
    "role_unresolved",
    "same_role_differs",
}
# Quarantined materials are asked too (S11a); one without a readable opening has no excerpt.
_QUARANTINED = {"no_product_anchor", "anchor_conflict", "text_unavailable"}
_UNREADABLE = "text_unavailable"
_KINDS = {"product", "pack", "role", "replace", "supplement", "ignore"}
_LIMITS = {"title": 200, "detail": 2000, "label": 200}
# Go's unicode.IsSpace, which strings.TrimSpace uses: the platform trims title, detail and labels
# this way before storing them, so the text is trimmed the same way before it is sent (review R7).
_SPACE = "[\t\n\v\f\r \u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]"
_EDGES = re.compile(f"^{_SPACE}+|{_SPACE}+$")


class ConfirmationsError(ValueError):
    """WORDING_INVALID or QUESTION_INVALID; never the material's text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ConfirmationWording(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    version: str = Field(min_length=1)
    title: str
    details: dict[str, str]
    excerpt: str  # the opening of the file, appended to every detail (S5b-3d-1)
    excerpt_chars: int = Field(gt=0)
    options: dict[str, str]
    roles: dict[str, str]

    @model_validator(mode="after")
    def _complete(self) -> "ConfirmationWording":
        roles = {role.role for role in load_material_roles().roles}
        reasons = _REASONS | _QUARANTINED
        if set(self.details) != reasons or set(self.options) != _KINDS or set(self.roles) != roles:
            raise ValueError("the wording must cover every reason, choice and role")
        return self


@lru_cache(maxsize=1)
def load_wording() -> ConfirmationWording:
    try:
        text = files(__package__).joinpath("confirmation_wording.json").read_text(encoding="utf-8")
        return ConfirmationWording.model_validate_json(text)
    except (OSError, ValidationError):
        raise ConfirmationsError("WORDING_INVALID") from None


def trim(text: str) -> str:
    return _EDGES.sub("", text)


def _fill(template: str, limit: int, values: dict[str, str]) -> str:
    """The template with its values, trimmed; an overlong file name is cut and ends with "…"."""
    try:
        text = trim(template.format(**values))
        overflow = len(text) - limit
        if overflow > 0 and len(values.get("file", "")) > overflow:
            cut = values | {"file": values["file"][: -overflow - 1] + "…"}
            text = trim(template.format(**cut))
    except (KeyError, IndexError, ValueError):
        raise ConfirmationsError("WORDING_INVALID") from None
    if not text or len(text) > limit or _CONTROL.search(text):
        raise ConfirmationsError("WORDING_INVALID")
    return text


def excerpt_of(head: str, chars: int) -> str:
    """The opening a person reads: whitespace runs become one space, other control characters
    and private-use glyphs go, and the text is cut at chars with "…" (S5b-3d-1 Spec §2.1)."""
    kept = (
        " " if c.isspace() else c
        for c in head
        if c.isspace() or unicodedata.category(c) not in {"Cc", "Co"}
    )
    text = " ".join("".join(kept).split())
    return text if len(text) <= chars else text[:chars] + "…"


def question_of(
    entry: PendingEntry,
    registry: ProductRegistry,
    wording: ConfirmationWording | None = None,
    *,
    head: str,
) -> ConfirmationInput:
    """The confirmation item for one material waiting for a person (Spec §2.1, §3.2).

    head is the text of the material's first pages; its opening ends the detail (S5b-3d-1).
    """
    wording = wording or load_wording()
    attribution = entry.attribution
    subject = SUBJECT_PREFIX + entry.knowledge_id
    if not _SUBJECT.fullmatch(subject):
        raise ConfirmationsError("QUESTION_INVALID")
    history = sum(1 for d in registry.decisions if d.knowledge_id == entry.knowledge_id)
    identity = {
        "knowledge_id": entry.knowledge_id,
        "parse_attempt": entry.parse_attempt,
        "sha256": entry.sha256,
        "attribution": attribution.model_dump(mode="json"),
        "decisions": history,
        "wording": wording.version,
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    revision = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]

    def name(product_id: str | None) -> str:
        product = registry.products.get(product_id or "")
        return product.names[0] if product else ""

    role = wording.roles.get(attribution.role or "", "")
    facts = {
        "file": entry.file_name,
        "product": name(attribution.product_id),
        "products": "、".join(name(p) for p in attribution.candidates if p in registry.products),
        "role": role,
        "name": attribution.display_name or "",
        "code": attribution.clause_code or "",
    }
    unreadable = attribution.reason == _UNREADABLE
    excerpt = excerpt_of(head, wording.excerpt_chars)
    if not excerpt and not unreadable:
        raise ConfirmationsError("QUESTION_INVALID")  # first pages without any text
    try:
        offered = choices(attribution, registry.registered())
    except ConfirmationError:
        raise ConfirmationsError("QUESTION_INVALID") from None
    options = [
        ConfirmationOption(
            key=c.key,
            label=_fill(
                wording.options[c.kind], _LIMITS["label"], _option_facts(c, facts, name, wording)
            ),
        )
        for c in offered
    ]
    return ConfirmationInput(
        subject=subject,
        revision=revision,
        title=_fill(wording.title, _LIMITS["title"], {"file": entry.file_name}),
        detail=_fill(
            wording.details[attribution.reason] + ("" if unreadable else "\n" + wording.excerpt),
            _LIMITS["detail"],
            facts | {"excerpt": excerpt},
        ),
        options=options,
        source_ref=SourceRevision(entry.knowledge_id, entry.parse_attempt).ref(entry.sha256),
    )


def _option_facts(
    choice: Choice,
    facts: dict[str, str],
    name: Callable[[str | None], str],
    wording: ConfirmationWording,
) -> dict[str, str]:
    if choice.kind == "product":
        return facts | {"product": name(choice.value)}
    if choice.kind == "pack":
        return facts | {"pack": _pack_labels().get(choice.value or "", "")}
    if choice.kind == "role":
        return facts | {"role": wording.roles.get(choice.value or "", "")}
    return facts


def _pack_labels() -> dict[str, str]:
    """Each pack's first classification suffix in the policy, such as 重大疾病保险."""
    labels: dict[str, str] = {}
    for entry in load_attribution_policy().classifications:
        labels.setdefault(entry.schema_pack_id, entry.suffix)
    return labels
