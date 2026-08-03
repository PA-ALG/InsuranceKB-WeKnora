# 075 · Golden v2 Human Review Intake

## Goal

Freeze a provider-free, fail-closed intake contract for the original 596-1 workbook
P0-seven plus P1-eleven decisions. Golden v1 remains immutable, and no successor may be
materialized until all eighteen decisions and an external named-human receipt verify.

## Frozen specification checklist

- [x] Bind Golden v1 SHA-256
  `562c37c7cf262e2e78f0b3ca4b7de4b0dab2f407d3cd7318a8a69b5dca33d8fb`.
- [x] Bind workbook SHA-256
  `ad51172eeee8dac177afff2319a0f8c14f09a82786846eaa227005dc1ac54edf`.
- [x] Bind exactly three source SHA-256 identities.
- [x] Bind the exact ordered P0-seven plus P1-eleven tuple, with no nineteenth field.
- [x] Keep `zh_2df7d6256c` and `zh_b7ceabc3c0` byte-equivalent to v1 and outside
  decision intake.
- [x] Reject defaulted decisions; `needs_expert` and `not_applicable` are always
  pending because this Mission defines no three-state mapping for either choice.
- [x] Require external named-human authority before successor materialization.
- [x] Require the formal materialization entry to hash the actual supplied v1 JSONL bytes,
  derive the sixty records from those bytes, and internally replay receipt verification.
- [x] Keep v1 immutable and perform zero filesystem, model, provider, DB, WeKnora or
  Release writes.

## Scope

One pure Python contract, one synthetic focused test, and four OpenSpec files. The
contract validates caller-supplied decisions and an out-of-band Ed25519 receipt. The
formal materialization entry accepts only the fixed v1 JSONL bytes, derives the sixty
records in memory, and reruns verification; a private synthetic helper is explicitly
labelled `SYNTHETIC_TEST_ONLY`. It does not parse Excel or write JSONL.

## Non-goals

No business decision generation, Golden v2 directory, high-risk occupation or product
tier expansion, weak/strong gate reuse, provider/model call, scoring, DB, migration,
WeKnora, live or production action.
