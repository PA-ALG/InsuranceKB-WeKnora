# PR #13 Durable Attempt Ledger Design

**Date:** 2026-07-21
**Scope:** OpenSpec 024 extraction recall uplift, especially E3 and E7.

## Problem

PR #13 currently stores gapfill budget usage and LLM audit attempts in node-local
memory, then copies them into LangGraph state or candidate metadata after a node
returns. That ordering is not crash safe: a process can issue an outbound request
and die before the node checkpoint, allowing a resume to forget the call. It also
loses or misattributes attempts when parsing retries, mixed-field batches, losing
candidates, transport failures, voting, or judging are involved.

The invariant is stricter than “the happy path emits metadata”:

1. Every outbound LLM call is durably reserved before the call crosses the client
   boundary.
2. A gapfill reservation consumes the run budget even if the process dies while
   the outcome is unknown.
3. Every field affected by a request can find that request in its final audit
   chain, including failed and losing attempts.
4. `winning_attempt_id` identifies the call that produced the final value;
   confirmation-only stages retain the previous producer.
5. Invalid or misspelled configuration must fail before a run starts.

## Decision

Create a run-scoped SQLite ledger at `run_dir/llm-attempts.sqlite`. It is separate
from LangGraph's checkpoint database so the audit boundary does not depend on a
node checkpoint transaction or on LangGraph's private schema.

The ledger owns three relations:

- `llm_attempts`: one row per actual outbound call reservation, keyed by
  `(run_id, attempt_id)`, with a replay-deterministic run-local call ID,
  monotonic run sequence, stage, prompt version, request key, outcome, and
  optional budget scope.
- `llm_attempt_fields`: many-to-many mapping from a request to every field the
  request covered. This preserves batch-call truth without duplicating calls.
- `llm_budget_policies`: the immutable per-run limit for each budget scope;
  resume fails closed if a caller tries to expand, reduce, add, or remove the
  configured limit.
- `llm_variant_assignments`: one stable assignment per run and field, written
  before a gapfill call and independent of whether a candidate is returned.

`reserve()` uses `BEGIN IMMEDIATE`. For a gapfill attempt it counts all prior
reservations in the run and rejects before the outbound call once the limit is
reached. The committed reservation precedes `client.complete()`. Completion or
failure then updates the same row. A process crash leaves `outcome=reserved`;
that row remains auditable and consumes the hard budget because provider-side
completion is unknowable and the provider offers no idempotency key.

Standalone helpers may use an in-memory ledger, but pipeline execution always
uses the run-scoped SQLite ledger. `PipelineState.gapfill_calls_used` becomes a
projection for display/compatibility, never the enforcement authority.

## Call and attribution flow

`call_and_parse()` returns a structured result containing parsed items, the
successful producing attempt (if any), and all attempt IDs. It reserves before
each `complete()` and records transport failure, parse failure, or parsed success.
The parse-retry attempt is therefore the producer when it supplies the parsed
payload.

Extraction links each batch request to all requested field IDs. Fields accepted
from the first response keep the first producer; only rejected fields that are
successfully re-extracted receive the retry producer. Gapfill and vote use the
structured producer directly. Judge dispatch returns its attempt ID explicitly,
avoiding mutable shared `last_attempt` state under concurrency.

Finalize queries the ledger by field and overlays the complete attempt chain and
stored assignment onto the merged winning candidate. This prevents merge order
from discarding losing-stage history. `prompt_variant_used` and `winning_origin`
are derived from the winning attempt. A vote that merely confirms a value retains
the earlier extraction/gapfill producer and origin; a vote or judge that changes
the value becomes the producer.

## Configuration boundary

`PipelineConfig`, `AssignmentPolicy`, `VariantRegistry`, and `PromptVariant`
forbid unknown fields. Experiment IDs are stripped and must be non-empty when
enabled. Conflicting `requiredness` and `必填` aliases are rejected. Both production
and replay CLIs expose the gapfill maximum and experiment identity/seed, then use
one common `PipelineConfig` builder.

## Verification

Tests must prove the failure modes, not implementation details:

- a committed reservation survives a new ledger instance and blocks calls above
  the limit;
- a failed outbound call is present with a unique attempt ID;
- parse retry points to the successful retry;
- mixed batches retain the original producer for already accepted fields;
- losing extract/gapfill/vote attempts survive finalization;
- vote confirmation retains the old producer, while vote/judge replacement does
  not;
- typoed configuration and conflicting requiredness aliases are rejected;
- CLI values reach `PipelineConfig` unchanged.

No live-model call is needed; deterministic fake clients and temporary SQLite
files cover the boundary.
