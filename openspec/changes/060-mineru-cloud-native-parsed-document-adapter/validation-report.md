# 060 Validation Report

## Current status

`STABLE CANDIDATE / FINAL REVIEW PENDING`

## Identity and inherited custody

- authoritative base/HEAD:
  `bfa6fe233d08f84b368b51570c1c0302d22ae002`；
- previous Phase 0 working tree was safely replayed onto the exact base; inherited 058/059
  blobs remain identical to main and only the README registry was mechanically reconciled；
- real index empty; provider/model/DB/WeKnora calls remain zero；
- old capture/ODL experiments are historical only and are not implementation input。

## Official schema evidence

Primary source: MinerU official output-files reference at upstream commit
`79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7`,
`docs/en/reference/output_files.md` blob
`fd6dfe4c0226cb21abd6bf616be1dea26912ab40`. Pipeline
`*_content_list.json` is a reading-order list. Common facts are `page_idx`, normalized
`bbox` and `type`; table items carry native `table_body`, whose official example contains
`tr`, `td`, `rowspan` and `colspan`. `content_list_v2.json` is documented as a development
format and is excluded. The accepted internal input identity is therefore
`mineru.content-list.pipeline.v1` with effective model exact `pipeline`; no
Markdown/model JSON/VLM/MinerU-HTML fallback is allowed. The accepted official types and
type-specific keys are frozen in MCNP1; non-official aliases are rejected.

## RED → GREEN evidence

- Initial Go RED failed because the ZIP boundary had no `extractMinerUZipBytes` retention
  seam; initial Python RED failed because the task-local 060 adapter did not exist.
- Review-hardening REDs reproduced six concrete gaps: effective parser model was not bound,
  non-official types were accepted, raw native hash was not bound to the 053 subject,
  permissive HTML repair could authorize malformed tables, table ambiguity bypassed the 053
  ReviewItem, and sidecar relationships were not independently revalidated.
- Successor review reproduced three additional bounded gaps: a union struct admitted fields
  from the wrong official item type, mismatched `td/th` closing tags could still be repaired,
  and a mixed valid/ambiguous table set produced overlapping evidence/unsupported claims
  instead of 053 review. Dedicated REDs failed before the corrective and pass after it.
- Current corrective REDs reproduced three further trust-boundary mismatches: Python accepted
  bbox coordinates outside Go's normalized `0..1000` range; the HTML precheck ignored an
  unclosed nested formatting tag that `html.Parse` repaired; and required/typed official JSON
  fields accepted `null` or a wrong JSON type after key-presence validation.
- Second delta REDs reproduced two same-domain gaps: a non-void self-closing HTML token was
  ignored before `html.Parse` repaired it, and an invalid bbox was either discarded by Go or
  blocked by Python only when the MaterialProfile happened to require that locator capability.
- GREEN retains exact raw/sanitized hashes through Go-local `ReadResult`, binds
  `parser_model=pipeline`, refuses non-pipeline reads before provider I/O, uses a strict
  structural HTML precheck, and preserves ambiguous table items only as unsupported facts.
- Exact per-type key allowlists now run before item decoding; cell close tags must match their
  opening kind; any ambiguous table capability suppresses the same capability evidence across
  the sidecar so mixed inputs deterministically reach 053 `BLOCK + ReviewItem`.
- The Python bridge requires raw hash equality with `ParseSubjectV1.raw_artifact_hash`,
  revalidates page/table/cell/header/bbox/occupancy relations, directly reuses merged 053,
  and returns `BLOCK + ReviewItem` for an unproven table grid or any out-of-range block/table/
  cell bbox. Go and Python now share finite, ordered, inclusive `0..1000` bbox semantics;
  every present typed official field is checked before union decoding, and the HTML precheck
  requires complete nesting for structural and non-structural tags.
- Non-void self-closing tokens are now rejected while true void elements remain legal. Invalid
  bbox input retains only a sanitized `native_structure_invalid` observation with no locator;
  the 060 bridge binds that fact into 053 warnings/unsupported evidence and deterministically
  returns BLOCK+ReviewItem even for an `ordered_pages`-only profile.

## Gates

- focused Go MinerU tests: PASS；Go vet changed package: PASS；
- focused/bounded Python 052+053+056+060: `69 passed`；
- Ruff and strict mypy for the two changed Python files: PASS；
- OpenSpec 060 strict and `git diff --check`: PASS；
- exact scope is 11 paths (≤12); real index remains empty；
- private/secret scan: PASS；predecessor tree
  `c2730eab76958baf83acefaccd1bc7a7e96f3717` received independent approval on the old
  base and is retained as historical evidence only. Later tree
  `d70cca4f919fc11c4425546c00a3ad8538215d69` was not approved because of the two second-delta
  findings and is superseded. The current successor requires fresh
  review; its exact tree/temp-index identity is frozen externally after this report to avoid
  a self-referential tree claim；
- whole docparser package test is not a 060 gate in this sandbox: an unrelated
  `httptest` IPv6 listener is denied before its test body. The bounded MinerU suite is green；
- provider/live/DB/WeKnora/Golden/full: `NOT RUN` by contract；
- commit/push/PR: `NOT RUN` by contract。
