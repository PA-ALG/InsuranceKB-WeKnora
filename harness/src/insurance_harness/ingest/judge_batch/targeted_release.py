"""Fixed-version verification and the existing sampling inputs for targeted publication."""

from insurance_harness.bundle.client import PlatformClient, PlatformError, Release
from insurance_harness.bundle.fixed_release import FixedRelease
from insurance_harness.bundle.request_budget import ReleaseReadBudget
from insurance_harness.contracts.bundle import CandidateBundle


def verified_release(
    client: PlatformClient,
    space_id: str,
    budget: ReleaseReadBudget,
    identity: tuple[str, int, str, str, str],
    bundle: CandidateBundle,
) -> FixedRelease:
    fixed = FixedRelease(client, space_id, budget, identity[0])
    if (
        fixed.header.identity != identity
        or any(slug in fixed.rows for slug in bundle.removals)
        or any(
            m.logical_slug not in fixed.rows
            or fixed.rows[m.logical_slug].member_digest != m.member_digest
            or fixed.rows[m.logical_slug].kind != m.kind
            for m in bundle.members
        )
    ):
        raise PlatformError("RELEASE_MISMATCH")
    return fixed


def sample_inputs(
    current: FixedRelease,
    older: FixedRelease | None,
) -> tuple[Release, Release | None]:
    before = older.rows if older else {}
    changed = [
        row
        for row in current.rows.values()
        if row.kind == "claim"
        and (
            row.logical_slug not in before
            or before[row.logical_slug].member_digest != row.member_digest
        )
    ]
    if not changed:
        return current.body_view(()), None
    subjects = {row.subject_ref for row in changed}
    support = [
        row.logical_slug
        for row in current.rows.values()
        if row.kind == "presentation_profile"
        or (row.kind == "entity" and row.entity_id in subjects)
    ]
    result = current.body_view([*(r.logical_slug for r in changed), *support])
    if older is None:
        return result, None
    # The existing sampler needs only the predecessor's digests.
    return result, older.complete_view(())
