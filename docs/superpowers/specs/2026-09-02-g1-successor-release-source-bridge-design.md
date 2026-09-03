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
and original D2 frontend image
`sha256:ebf4f45a7279e44a9a6dea9394a58d90b6f6c70d259dd0c9b4a472c906783da0`
remain immutable diagnostic evidence. The user's blanket G1 authorization
permits exactly one replacement build for each affected image after this fix.

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

The original frontend parser has the same conflation: it requires both the
immutable member `release_id` and field `reference.source_release_id` to equal
the response's serving `release_id`. The frozen member payloads correctly hold
the old 815 source identity, so the parser would reject every valid successor
response. The server must not rewrite those frozen payloads to satisfy it.

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

The read envelope carries serving identity. Embedded manifest members retain
source identity: `member.release_id` and a field assertion's
`reference.source_release_id` both remain the old 815 Release. Candidate
Preview is the only mode where serving and source identities are equal because
no successor exists yet.

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

An explicit pinned entity read is Head-independent and accepts the exact
requested G1 successor Release even after Head advances. Its stable serving
epoch is the successor's original activation epoch,
`WikiRelease.BaseActivationEpoch + 1`; a current read instead reports the Head
epoch pinned at request start. Missing, foreign, source-only or malformed
entity releases fail closed and never fall back to `current`, `latest` or
another release. The historical 815 source Release remains readable through
its existing Schema pinned routes; it is not reinterpreted as a G1 entity
successor.

### Historical-source evidence bridge

For a G1 field citation, the entity response has already selected and exposed
one concrete successor Release ID. The unchanged citation preview route sends
that exact successor ID for both a current page and an explicitly pinned page;
it carries no read-mode discriminator. Citation issuance therefore loads that
exact G1 successor independently of Head in both cases. It verifies the Ready
preparation and full G1 manifest/member custody, then derives the historical
source Release exclusively from that successor's immutable base identity. It
loads that exact 815 Release without consulting a caller-selected source
release.

The existing 17/17 bridge checks remain mandatory: field mapping, full join
receipt, source revision, parse attempt, parsed document, parse manifest, PDF
page, bbox, locator content, quote and all hashes must match. Only after those
checks may the server issue the existing opaque citation token. The token's
private claims preserve both domains: the route-selected successor serving
identity and the derived 815 source replay identity. Every G1 entity citation
uses exact `release` route authority, whether its page was reached through the
current or pinned entity route. Issuance and content replay validate the exact
immutable successor and scope without consulting Head, then reconstruct the
source bridge from that same successor. Existing generic Schema citations
remain `active` and continue to use their existing Head-bound behavior. The
public citation authority remains the serving successor identity; the source
replay identity is never caller-selectable. Any drift or missing historical
source returns the existing typed citation-unavailable error; there is no
page-1, current/latest, raw-content or quote fallback.

## API and UI boundary

No route is added. Existing stable entity routes continue to support:

- no query for current;
- one exact `release_id` for pinned;
- one exact `preparation_id` for Candidate Preview.

The existing citation preview route remains the frontend transport for both
current and exact pinned successor pages. Because those clicks are identical
HTTP requests once a concrete successor is rendered, all G1 clicks use exact
`release` authority; the server does not infer page read mode from Head. No
public authority field or route shape is added. The opaque token may gain
private serving/source and route-kind claims needed for the closed server-side
replay above. The
frontend parser must validate the split explicitly: preparation requires the
member/source identity to equal the envelope identity; current and pinned
require the immutable member/source identity to equal each other and differ
from the successor envelope identity. This is a bounded parser correction, not
a route, payload or UI redesign.

## Failure handling and invariants

- CAS remains the sole activation authority and still atomically writes one
  successor Release, exactly 76 members, one Head transition and one receipt.
- The manifest and all 76 payloads remain byte-for-byte immutable.
- Old 815 source Release rows remain immutable, and their existing Schema
  pinned reads remain unchanged. G1 entity/citation code may reach them only
  as server-derived provenance from a validated successor, never through a
  caller-selected source identity.
- Production containers, production Head and provider/model paths remain out
  of scope. D3 runs on the isolated clone and an internal no-egress network.
- The original D2 app and frontend images are never overwritten or retagged.
  Evidence records why each was superseded and both exact replacement
  identities.
- Before implementation, OpenSpec tasks and validation custody must record the
  user's blanket G1 authorization. It supersedes only the previous
  `NO_MORE_BUILDS` conclusions for the affected images and grants a budget of
  exactly one replacement app build plus one replacement frontend build.

## Test and verification design

Implementation follows TDD:

1. Add an activation/read regression that starts with an old source Release,
   reviews and activates a 76-member G1 preparation, and proves current plus
   exact pinned reads return the new serving Release/epoch while retaining the
   old source binding.
2. Add negative tests for base Release/epoch drift and caller-selected source
   identity; all must fail closed.
3. Add a current citation regression that derives the old 815 source through
   successor base custody and issues the exact token; mutate revision, page,
   bbox, quote and join identity to prove typed failure with zero fallback.
4. Activate the sole frozen-manifest G1 successor R1, then move Head legally
   through the existing CAS to a non-G1 control Release. Prove an exact pinned
   R1 page and its source click still bind R1 and R1's old source without
   consulting Head, while the current G1 entity route fails closed because the
   new Head is not a valid G1 successor. Do not construct an impossible second
   G1 successor from the frozen manifest or reinterpret R1 as its old source.
5. Add frontend parser regressions proving preparation same-identity and
   current/pinned successor-envelope plus immutable-source-member identity;
   mixed or rewritten identities fail closed.
6. Run focused Go tests, the full affected Go packages, focused frontend
   component tests and the existing G1 Harness tests.
7. After OpenSpec custody records the authorization, build exactly one
   replacement app image and exactly one replacement frontend image with the
   new frozen commit/tree and lock/source labels.
8. In isolated D3, verify Draft -> Ready -> Release -> Active, 76/76 members,
   current/pinned no-mix reads, three known-field source clicks, negative
   fail-closed cases, zero egress/provider/model calls and unchanged production
   identities.

## Explicit non-goals

- No G2 work or automatic G2 start.
- No new manifest version or recompile of the frozen 76-page graph.
- No database migration, new release table, second Head or second publisher.
- No production deployment, restart, activation or credential change.
- No frontend redesign and no more than one replacement frontend image build.
