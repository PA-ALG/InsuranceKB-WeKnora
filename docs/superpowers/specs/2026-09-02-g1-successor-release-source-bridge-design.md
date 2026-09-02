# G1 successor Release and historical-source bridge design

## Status and scope

This design closes the G1 M3 blocker discovered after the original D2 images
were built. It does not change the frozen G1 product Goal or the 76-member
Entity Page Graph contract. It separates the serving identity created by the
existing Wiki Release CAS from the immutable 815 source identity already
recorded by the G1 manifest.

The implementation base is branch `codex/830-g1-field-assertion-pages` at
`d648f53b8`. The original D2 app image
`sha256:f913037cfe74a7bbd7e8a819a56ccb92fea32ae3da4b6511d460a04f3b920327`
remains immutable diagnostic evidence. The frontend image
`sha256:ebf4f45a7279e44a9a6dea9394a58d90b6f6c70d259dd0c9b4a472c906783da0`
remains reusable. User authorization permits one app-only replacement build
after this fix.

## Problem

`EntityPageManifest830G1.release_id` and `activation_epoch` are compiled from
the exact already-active 815 source Release. Every field reference separately
records that identity as `source_release_id`. The existing Wiki activation
transaction correctly creates a new successor Release ID and advances Head.

The current G1 active reader nevertheless requires the new serving Release ID
and epoch to equal the old source Release ID and epoch embedded in the
manifest. A successful CAS therefore makes the successor unreadable. The
Candidate Preview source bridge also requires the old source Release to remain
current, so it cannot serve evidence after Head advances to the successor.

## Chosen identity model

Two identities remain distinct and closed:

- Serving identity: the successor `WikiRelease.ID` and the Head activation
  epoch returned by the existing CAS. Current and pinned page reads expose this
  identity.
- Source identity: `EntityPageManifest830G1.release_id` and
  `activation_epoch`, also repeated as each field reference's
  `source_release_id`. This identifies the immutable 815 Release from which
  Candidate, Claim and Evidence custody were compiled.

The successor Release binds the two domains with existing immutable fields:
`WikiRelease.BaseReleaseID` must equal the manifest source Release ID and
`WikiRelease.BaseActivationEpoch` must equal the manifest source epoch. No new
table, column, Head, publisher or mutable projection is introduced.

## Read behavior

### Candidate Preview

Preparation reads remain unchanged. They expose `read_mode=preparation` and
the manifest's source release/epoch because no successor serving identity
exists yet.

### Current and pinned successor reads

The loader first validates the successor Release, its Ready preparation, the
76 stored members and the full manifest. It then requires the successor base
identity to match the manifest source identity. The response exposes the
successor serving Release ID. Current reads expose the Head epoch captured at
request start.

An explicit pinned read accepts only the exact requested successor Release.
When that Release is current, it uses the same Head epoch. A missing, foreign,
source-only, stale or malformed release fails closed; it never falls back to
`current`, `latest` or another release.

### Historical-source evidence bridge

For an active G1 field citation, the server begins from the current successor
Head and Ready preparation. It verifies the full G1 manifest/member custody,
then derives the historical source Release exclusively from the successor's
immutable base identity. It loads that exact 815 Release without consulting a
caller-selected source release.

The existing 17/17 bridge checks remain mandatory: field mapping, full join
receipt, source revision, parse attempt, parsed document, parse manifest, PDF
page, bbox, locator content, quote and all hashes must match. Only after those
checks may the server issue the existing opaque citation token. Any drift or
missing historical source returns the existing typed citation-unavailable
error; there is no page-1, current/latest, raw-content or quote fallback.

## API and UI boundary

No route is added. Existing stable entity routes continue to support:

- no query for current;
- one exact `release_id` for pinned;
- one exact `preparation_id` for Candidate Preview.

The existing active citation preview route remains the frontend transport.
The frontend already distinguishes current, pinned and preparation modes, so
the replacement build is app-only; the frozen frontend image is reused.

## Failure handling and invariants

- CAS remains the sole activation authority and still atomically writes one
  successor Release, exactly 76 members, one Head transition and one receipt.
- The manifest and all 76 payloads remain byte-for-byte immutable.
- Old 815 source Release rows remain immutable and readable only as derived
  provenance for the bridge.
- Production containers, production Head and provider/model paths remain out
  of scope. D3 runs on the isolated clone and an internal no-egress network.
- The original D2 app image is never overwritten or retagged. Evidence records
  why it was superseded and the exact replacement identity.

## Test and verification design

Implementation follows TDD:

1. Add an activation/read regression that starts with an old source Release,
   reviews and activates a 76-member G1 preparation, and proves current plus
   exact pinned reads return the new serving Release/epoch while retaining the
   old source binding.
2. Add negative tests for base Release/epoch drift and caller-selected source
   identity; all must fail closed.
3. Add an active citation regression that derives the old 815 source through
   successor base custody and issues the exact token; mutate revision, page,
   bbox, quote and join identity to prove typed failure with zero fallback.
4. Run focused Go tests, the full affected Go packages, focused frontend
   component tests and the existing G1 Harness tests.
5. Build exactly one replacement app image with the new frozen commit/tree and
   package-lock/source labels. Do not rebuild frontend.
6. In isolated D3, verify Draft -> Ready -> Release -> Active, 76/76 members,
   current/pinned no-mix reads, three known-field source clicks, negative
   fail-closed cases, zero egress/provider/model calls and unchanged production
   identities.

## Explicit non-goals

- No G2 work or automatic G2 start.
- No new manifest version or recompile of the frozen 76-page graph.
- No database migration, new release table, second Head or second publisher.
- No production deployment, restart, activation or credential change.
- No frontend redesign and no second frontend image build.
