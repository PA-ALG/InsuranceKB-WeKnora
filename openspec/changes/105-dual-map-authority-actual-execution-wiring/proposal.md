# 105 · Dual-map Authority → Actual Execution Wiring

## Goal

Close the last task-local composition seam between the independent terms-section and
rate-table marker authorities and the existing 100 → 092 → 095/087 execution path.
The change must preserve every upstream authority boundary and must stop truthfully while
the 103 terms-section contract is not frozen.

## Frozen dependency order

`101 authority envelope → 098 rate-table replay + 103 terms-section replay →
102/086 verified bindings → 096 private receipt → 100 authority adapter →
092 admission composition → 095/087 private execution`.

- authoritative base/HEAD: `31d815cbc29dc9fb2ce53db2dcbfbd606b8761ff`;
- 101 candidate tree: `8fc3b62c5a437c92bb9f97ff973d91ffef6a76ca`;
- 102 stacked candidate tree: `90e98c942fb32e5bfdd5bde9a77a99cf77850a26`;
- 100 stacked candidate tree: `adb1f3c86aa7b0645d0c7cfe44edf43f8bc9cb19`;
- 095 stacked candidate tree: `04f1a4ef30509e9cb066b354c51ce49ef33f9405`.

103 is still mutable and exposes no frozen public section-map contract. Production
resolution therefore returns `TERMS_SECTION_BINDING_UNAVAILABLE` before envelope export,
private-file reads, 100, 092 or 095/087. A narrow Protocol seam permits one synthetic
future-complete fixture to prove the call graph without creating runtime authority.

## Design

1. Resolve exact public callables and signatures first. Missing or incompatible 103 is a
   dedicated typed stop; all other missing dependencies are `DEPENDENCY_UNAVAILABLE`.
2. Export and replay the real 101 envelope from the same ordered terms/brochure/rate private
   paths. A terms map and a rate map are produced only by their distinct exact replay ports;
   roles cannot be swapped, duplicated or filled by one another.
3. A narrow 100 export accepts the already-resolved dual-map builder but retains all receipt,
   083 bundle, source/profile and 086 provider validation. 105 never parses receipt JSON or
   constructs 092 authority DTOs.
4. A narrow 095 export accepts that 100 validator while retaining 087's `0600`, regular-file,
   no-follow, distinct-inode and exact four-file snapshot gates and the existing 092 call.
5. Every envelope/source/member/parser/version/endpoint/policy/replay/context/preimage/hash
   mismatch stops before the actual execution port. Current unavailable evidence remains
   unavailable; synthetic fixtures are explicitly non-authoritative.

## Alternatives rejected

- Reusing the table map as a terms map or inferring section endpoints from page adjacency,
  Markdown or body text.
- Parsing 096 again in 105 or directly constructing 092 inputs.
- Reimplementing 095 private-file custody or building a general receipt/workflow platform.

## Path budget

Nine paths: registry, four OpenSpec105 documents, one task-local module, one focused test,
and one narrow export each in the frozen 100 and 095 modules. No 103/104 path is modified.

## Non-goals

No capture, parser change, ADMIT/READY claim, provider/model/Golden, DB/PG, WeKnora,
live/full run, credential read, endpoint heuristic, retry/fallback or workflow platform.
