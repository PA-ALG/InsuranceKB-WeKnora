# 080 · Candidate Review Release Handoff

## Goal

Compose one exact, synthetic 059 Candidate through the existing 076 Wiki draft compiler,
077 display-only review dossier and a deterministic 059 preparation-input vector without
creating human authority or serving state.

## Scope

- consume one revalidated `CandidateAssemblyV1`, one complete 076 base and the exact 057
  `FieldCandidateV1` set;
- invoke the existing 076 and 077 public builders from the same input objects;
- derive one preparation-only vector from the resulting Candidate, manifest, review batch
  and policy identities;
- mechanically cross-check Candidate, ChangeSet, Space, ProductVersion, policy, member,
  manifest and dossier custody before returning the immutable aggregate;
- remain pure and deterministic, so validation failure returns no partial handoff.

## Non-goals

No human decision, default choice, signature, ReadyReceipt, release activation, Active Head,
database, migration, queue, worker, provider, model, Golden, WeKnora or generic release
platform is included.

## Path budget

Exactly six owner paths: four OpenSpec files, one task-local production module and one
focused test. The central registry and all 059/076/077/079/081 paths remain unchanged.
