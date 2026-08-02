# 070 · 596-1 Golden18 Human Gate

## Goal

Freeze one task-local, provider-free gate for the exact 596-1 Golden18 review set. The
gate binds the approved ordered P0/P1 authority, weak and strong frozen-output hashes,
the score-report hash, all eighteen field decisions, and a separately issued named-human
receipt. It returns a typed verification result only; it cannot publish a Release or call
WeKnora.

## Scope

- exact authority contract SHA-256
  `23816ccdfa9258bb4785ed0d1032c8281c1eda047c7801543b2032649b567dc2`;
- exact ordered P0-seven plus P1-eleven field tuple and cardinality;
- deterministic decision and subject hashes;
- `strong` remains a diagnostic human choice only; every Release-eligible decision must
  select the weak arm, because `gpt-5.6-sol` is an offline ceiling and never authority;
- external Ed25519 receipt verification against an out-of-band trusted named-human key,
  exact conversation provenance and a caller-supplied fresh clock;
- typed pending/block outcomes for missing, service/self-reported, placeholder, stale,
  foreign, malformed or tampered input.

## Non-goals

No Golden value read, decision generation/defaulting, self-approval, provider/model call,
DB, WeKnora, Release action, signature ceremony, CLI, migration, or generic approval
platform is included. The strong arm cannot become production, fallback, judge, repair or
Release authority through this gate.

## Path budget

Exactly seven paths: registry, four OpenSpec files, one task-local module and one focused
test. No commit, push or PR is authorized by this change checkpoint.
