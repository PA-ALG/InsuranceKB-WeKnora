# G3 D downstream execution plan — independent repair review 02

Date: 2026-09-07
Effect: read-only design review; active Go was not read and no tests/runtime/provider/DB/build/install/write were run.

Reviewed exact identities:

- `lane-d-downstream-execution-plan-1.md` SHA-256 `a5cbf39c74f2bd26d52590580b7d2a059858d2951577614ad1cae3ed8727f3ab`
- `d-preparation-alignment-display-clarification-1.md` SHA-256 `5e12a1e0f81677986aa8483c79e6376f9266b410655564be8ee96ec858b0daab`
- Prior independent review SHA-256 `35f5f875385233b61b21adf307c1fde7c96f92e07608799409f8c77c8f0ff90f`

## Conclusion

`PASS`: `BLOCKER 0`, `BACKLOG 0`, `REJECTED 0` for the two requested repairs. The document remains a design candidate and does not itself authorize production writes.

## Original finding 1 — closed

Task1 now calls the existing source-verifier interface after strict outer/base/carry/alignment validation and before `createDraftAtExpectedHead`; fake tests bind order and require verifier denial to leave repository `CreateDraft` call count zero. Task2 must close the real G3 source branch and its exact 14-field/custody failures before Task3 exposes the HTTP create path.

Operation semantics are explicit and executable: dispatch first by exact manifest contract; G2 remains `review|activate`; G3 alone permits `create-draft|review|activate`. Pre-storage `create-draft` binds preparation ID, scope, candidate hash, canonical outer manifest and real digest, requires empty non-authoritative `PreparationDigest`, and rejects attempts to present a stored digest. Review/activation continue to use the real stored digest. This requires no interface/DTO expansion and avoids mislabeling creation as review.

## Original finding 2 — closed

The client no longer contains tenant entity/version/release/preparation/member constants or a runtime docs fixture. After the protected preparation bootstrap and immutable GET, it pins the response's expected base release/epoch and calls the existing dual-KB ACL/seal historical search, never `/current`. The exported strict G2 parser validates that historical snapshot. The two base medical owners are derived by exact medical pack/Profile plus current plural-field membership; old singular and current plural members are then uniquely matched by owner/version and must both satisfy the frozen all-empty unknown shape.

The scheme derives old/new IDs only from authenticated responses, rejects missing/extra/duplicate/drifted owners or fields, and retains the full 14-field lineage as server authority. It adds no response field, static asset, endpoint, service, table, alias engine, or second authority. Task4 correctly distinguishes the permitted exact historical-base read from an Active `/current` or G3-directory load.

## Remaining gates

The plan correctly keeps downstream paths closed until the Go mirror, cross-language equality, exact Go identities, and this clarification's review are accepted. Provider/source upload and actual C model execution remain separate and NOT RUN.
