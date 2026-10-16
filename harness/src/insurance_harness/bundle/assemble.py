"""Claims as a candidate bundle of claim members (S4g Spec §2.2).

Generic over the claim content: each claim becomes one ``kind=claim`` member keyed by its logical
key, with the platform's member digest and the source references its evidence cites. Built through
the contract model itself, so the structure satisfies contracts/candidate_bundle.schema.json; the
size limit is the platform's.
"""

import json
from collections.abc import Sequence

from insurance_harness.bundle.canonical import member_digest
from insurance_harness.bundle.client import MAX_BUNDLE_BYTES, Head
from insurance_harness.contracts.bundle import BundleMember, CandidateBundle
from insurance_harness.contracts.enums import Origin
from insurance_harness.contracts.knowledge import Claim

ACCESS_SCOPE = "space"


class BundleError(ValueError):
    """The claims cannot be published as they stand.

    Carries a stable reason code and, when one field is at fault, its position in the compile
    output: never the field key or any other input text, which may be arbitrary.
    """

    def __init__(self, reason: str, field_index: int | None = None) -> None:
        self.reason, self.field_index = reason, field_index
        super().__init__(reason)


def assemble(
    claims: Sequence[Claim], *, compiler_identity: str, base: Head | None = None
) -> CandidateBundle:
    """One claim member per claim, based on the given Head (None before the first release)."""
    slugs = [claim.logical_key for claim in claims]
    if len(set(slugs)) != len(slugs):
        raise BundleError("DUPLICATE_LOGICAL_KEY")
    members = []
    for claim in claims:
        payload = claim.model_dump(mode="json")
        members.append(
            BundleMember(
                kind="claim",
                logical_slug=claim.logical_key,
                payload=payload,
                member_digest=member_digest(payload),
                evidence_refs=sorted({item.source_ref for item in claim.evidence}),
                access_scope=ACCESS_SCOPE,
            )
        )
    bundle = CandidateBundle(
        contract_version="1",
        base_release_id=base.release_id if base else None,
        base_epoch=base.epoch if base else None,
        origin=Origin.COMPILE,
        members=members,
        compiler_identity=compiler_identity,
    )
    raw = json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_BUNDLE_BYTES:
        raise BundleError("SIZE_LIMIT")
    return bundle
