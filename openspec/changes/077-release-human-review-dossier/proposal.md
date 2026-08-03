# 077 · Release Human Review Dossier

## Goal

Build one deterministic, display-only dossier for an exact complete 059
`CandidateAssemblyV1`. The dossier gives a named human one batch-level view of additions,
updates, conflicts, retractions, high-risk fields, repairs and unresolved gaps while
retaining mechanically replayable 057 `FieldCandidateV1` Evidence locator custody.

## Scope

- revalidate the complete Candidate, human-batch policy and every public upstream hash;
- join each fact verification link to one exact caller-supplied original FieldCandidate
  snapshot by `candidate_snapshot_hash`, never by `field_id` alone;
- freeze one immutable dossier DTO and derive canonical JSON plus escaped static HTML from
  that same DTO;
- expose the original 058 action while grouping `enrich` and `supersede` as updates;
- preserve all competing facts, retraction proof/history, high-risk markers, repair
  results, gaps and available page/block/table/cell Evidence locator facts;
- return `DISPLAY_ONLY_REQUIRES_NAMED_HUMAN` without selecting or approving anything.

## Non-goals

No `ReviewDecision`, default choice, winner, self-approval, approval control, persistence,
filesystem/network/provider/model/Golden/DB/WeKnora/Release operation, API endpoint,
interactive UI or generic review platform is included.

## Path budget

Exactly seven owner paths: four OpenSpec files, two task-local production modules and one
focused test. The registry, HANDOFF and all upstream 057/058/059/070 paths remain unchanged.
