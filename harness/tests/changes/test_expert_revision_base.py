"""S9d acceptance (protected, written by Claude): an expert-revised Claim in the Active
release, in the shape the platform writes it, takes part in the S8a decision instead of
stopping it (Spec docs/design/slices/S9d-增量判定识别专家修订依据.md §3).
RED until S9d: _documents rejects the expert:v1 source reference with "invalid source_ref".

Synthetic data only. No model calls, no network.
"""

import hashlib

import pytest

from insurance_harness.bundle.client import Release, ReleaseMember
from insurance_harness.changes import ChangeSet, Verdict, decide_changes
from insurance_harness.contracts.enums import ClaimState, LocatorKind, SourceClass, UnknownReason
from insurance_harness.contracts.knowledge import Claim, Evidence, Locator, Maintenance

TERMS = "k-terms"
TERMS_SHA = hashlib.sha256(TERMS.encode()).hexdigest()
RECORD = "rev_" + "a" * 32
RECORD_SHA = hashlib.sha256(b"revision record").hexdigest()


def sourced(quote: str) -> Evidence:
    return Evidence(
        source_ref=f"source:v1:{TERMS}:1:{TERMS_SHA}",
        file_sha256=TERMS_SHA,
        locator=Locator(kind=LocatorKind.PDF_TEXT_SPAN, page=1, start=0, end=len(quote)),
        quote=quote,
        access_scope="space",
    )


def expert(quote: str, ref: str | None = None, sha: str = RECORD_SHA) -> Evidence:
    """What internal/enterprise/expert writes for a revision (S9a §2)."""
    return Evidence(
        source_ref=ref or f"expert:v1:{RECORD}:{sha}",
        file_sha256=sha,
        locator=Locator(kind=LocatorKind.EXPERT_REVISION, revision_record_id=RECORD),
        quote=quote,
        access_scope="space",
    )


def claim(field: str, value: str | None, *proof: Evidence, revised: bool = False) -> Claim:
    present = value is not None
    key = f"P/{field}"
    return Claim(
        claim_id=key,
        logical_key=key,
        subject_ref="P",
        predicate=field,
        state=ClaimState.PRESENT if present else ClaimState.UNKNOWN,
        value=value,
        evidence=list(proof),
        origin=SourceClass.EXPERT_REVISION if revised else SourceClass.SOURCE_SUPPORTED,
        expert_lock=revised,
        unknown_reason=None if present else UnknownReason.NOT_IN_MATERIAL,
        maintenance=Maintenance(revision_no=1 if revised else 0),
    )


def release(*claims: Claim) -> Release:
    return Release(
        id="rel-base",
        epoch=50,
        members=[
            ReleaseMember(
                kind="claim",
                logical_slug=item.logical_key,
                member_digest=hashlib.sha256(item.model_dump_json().encode()).hexdigest(),
                payload=item.model_dump(mode="json"),
            )
            for item in claims
        ],
    )


TAGLINE = "灵活定制：四档免赔额自由选"
BASE = release(
    claim("tagline", TAGLINE, expert(TAGLINE), revised=True),
    claim("waiting", "90日", sourced("等待期为90日")),
)


def verdicts(changes: ChangeSet) -> dict[str, Verdict]:
    return {item.logical_key: item.verdict for item in changes.items}


def test_a_different_compiled_value_is_a_conflict_and_is_not_published() -> None:
    incoming = [
        claim("tagline", "保障全面", sourced("保障全面")),
        claim("waiting", "180日", sourced("等待期为180日")),
    ]
    changes = decide_changes(BASE, "P", incoming, {TERMS})
    assert verdicts(changes)["P/tagline"] == Verdict.CONFLICT
    assert "P/tagline" not in {member.logical_key for member in changes.members}
    assert "P/waiting" in verdicts(changes)


def test_the_same_compiled_value_is_unchanged() -> None:
    incoming = [
        claim("tagline", TAGLINE, sourced(TAGLINE)),
        claim("waiting", "90日", sourced("等待期为90日")),
    ]
    changes = decide_changes(BASE, "P", incoming, {TERMS})
    assert verdicts(changes)["P/tagline"] == Verdict.UNCHANGED
    assert not changes.members


def test_withdrawn_materials_never_retract_an_expert_revision() -> None:
    changes = decide_changes(BASE, "P", [], set())
    assert verdicts(changes)["P/tagline"] == Verdict.KEEP
    assert "P/tagline" not in changes.removals


@pytest.mark.parametrize(
    "proof",
    [
        expert(TAGLINE, ref=f"expert:v1:{RECORD}:{'b' * 64}"),
        expert(TAGLINE, ref=f"expert:v2:{RECORD}:{RECORD_SHA}"),
        expert(TAGLINE, ref=f"expert:v1::{RECORD_SHA}"),
    ],
)
def test_a_malformed_expert_reference_is_still_rejected(proof: Evidence) -> None:
    broken = release(claim("tagline", TAGLINE, proof, revised=True))
    with pytest.raises(ValueError, match="invalid source_ref"):
        decide_changes(broken, "P", [], {TERMS})
