# OpenSpec 106: MinerU Native Section-Anchor Evidence

## Why

OpenSpec 103 correctly refuses to derive a terms cross-page relation when its
source and target blocks lack a replayable common section anchor. The exact
MinerU custody can contain native block type, hierarchy level and reading-order
facts that are narrower than document semantics and can close that gap without
guessing from text.

## What changes

- add a task-local, in-memory `SectionAnchorEvidenceV1` authority for 103;
- bind the evidence to the exact 083 capture and 101 marker custody;
- prefer explicit native hierarchy facts and otherwise apply one frozen
  structural fallback based on a preceding title/section block and a complete
  boundary-free reading-order interval;
- return typed `NOT_AVAILABLE` or `BLOCKED` when the structural proof is absent
  or ambiguous.

## Non-goals

No relationship rule change, semantic title/body comparison, Markdown, model,
provider, Golden, database, WeKnora, ADMIT or READY authority is introduced.
