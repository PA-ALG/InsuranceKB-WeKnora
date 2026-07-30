# S0-Q Narrow-Slice Quality Falsification Run Design

## Status and decision

This design is the execution follow-up to OpenSpec 047. It keeps S0-Q narrow:
two real source PDFs, one ProductVersion, four diagnostic records projected
from the approved full product Golden, and one binary feasibility verdict.

The approved processing order is:

```text
real PDFs
→ WeKnora parsing
→ frozen W1 revision artifacts
→ Harness weak-model compilation and deterministic validation
→ S0-Q verdict
→ only after PASS: the first reviewed Release-to-Wiki vertical slice
```

S0-Q does not publish Wiki pages. It first establishes whether the real parsed
input can support reliable knowledge compilation.

## Frozen scope

The two materials are from the same product:

- `dataset/shouxian_product/平安e生保（尊享版）医疗保险/保险条款.pdf`
- `dataset/shouxian_product/平安e生保（尊享版）医疗保险/产品说明书.pdf`

The ProductVersion is `596-1`. The four fields are:

| Class | Field | Expected result |
|---|---|---|
| `present A` | 产品特色 | the three product features stated in the product brochure |
| `typed-present B` | 免赔额 | plan 1 = CNY 10,000; plan 2 = CNY 0 |
| `absent_explicitly` | 保证续保 | explicitly unsupported because the contract states it is not guaranteed renewable |
| `unknown` | 宽限期 | abstain; the two materials do not establish a grace period |

`typed-present B` depends on the real merged table on terms page 31. This
preserves the table-structure difficulty required by OpenSpec 047.

No other material, ProductVersion, or field may be added during the run.

## Authoritative Schema and Golden truth

The business-authoritative field source for this run is the owner-supplied
workbook:

- repository target:
  `docs/insurance-kb/schema-authority/产品知识库字段标签维度-20240205.xlsx`;
- source SHA-256:
  `5cd0ed8af0bc10fec488d0d83e8e28c7c0d64408c4fc25cca92b2a365355fdb6`.

Its eight structured field sheets match the corresponding existing baseline
YAML field rows. The embedded screenshots are also authoritative annotation
guidance: they show which product-manual or contract regions, table columns,
conditions, and plan distinctions the named fields are intended to capture.
They are not per-product Golden answers and their example values must not be
copied into the S0-Q expected output.

The repository also contains later baseline files and v1.1 extensions that are
not present in this workbook. They remain frozen in place for compatibility
and may remain in historical Golden candidates, but they are not silently
promoted to workbook-authoritative fields.

S0-Q does not create a separate four-field Golden Set. The existing Golden
annotation subsystem remains the single Golden path. For the medical Golden
Product it already carries one record for every current extractable registry
field; the S0-Q fields are only a four-field projection selected from that
complete product annotation.

Before R2 can complete, a separate Golden Mission must use `gpt-5.6-sol` to
re-annotate or audit all 60 current extractable medical-registry fields against
the exact product PDFs and this workbook, close deterministic Evidence checks
and human approval, and publish an immutable artifact identity/digest.
Selective four-field annotation is not sufficient for that Golden refresh.
The 49 workbook-derived extractable fields and 11 later v1.1 extension fields
remain distinguishable in the artifact; later extensions do not become
workbook-authoritative merely because they are annotated.

The current 60-record WIP proves coverage only. It is not the frozen Golden and
cannot complete R2. Model output is a candidate, not self-authenticating truth.
Deterministic quote/structure verification and the approved human review
policy close the Golden identity. The full Golden remains isolated from the
evaluated weak-model prompt; only the field contract may enter extraction. The
four S0-Q expected records and oracle spans are read from the later frozen full
Golden and may be used only in the already-defined diagnostic arms.

## Input capture

Use the currently digest-pinned local WeKnora app and docreader derived from
the approved `80a5003` capability baseline. Upload both exact PDFs to a
dedicated scratch RAW knowledge base through the existing authenticated admin
API. Do not reuse a historical parse attempt.

For each PDF:

1. record the repository path, byte length, and SHA-256;
2. wait for one completed parse attempt;
3. read the W1 revision descriptor and exact-attempt chunk pages;
4. recompute and verify the W1 chunk manifest;
5. freeze parser/build/chunker identity, page ordering, chunk identities, page
   anchors, and exposed table structure;
6. write one immutable bundle plus a top-level run manifest.

The scratch knowledge base is not production data and is deleted after the
bundle is verified. The frozen bundle remains the run input.

If WeKnora/W1 does not expose enough page, table, parser, or digest identity to
recompute the bundle, input capture stops with `BLOCKED_ON_INPUT`. Offline
docreader output or manually cleaned Markdown may diagnose the gap but may not
replace the failed input or enter the feasible numerator.

## Compilation and diagnosis

Run the existing Harness compilation and deterministic validation components
against only the frozen bundles. Do not build a quality platform or a second
parser.

Before provider access, freeze:

- one exact Bailian weak-model identity;
- prompt and schema digests;
- temperature, seed, maximum calls, retries, and timeout;
- the manual-edit active-time ceiling;
- one exact strong-model identity and finite budget for the isolated B-arm
  diagnostic upper bound.

The formal extraction, retry, fallback, judge, and feasible numerator use zero
strong-model calls. The strong model is isolated to the pre-approved B arm and
cannot feed values, spans, claims, or decisions back into the weak-model run.

Run the OpenSpec 047 matrix on the same inputs:

- A: oracle span → extraction and typed normalization;
- B: fixed span/schema → weak model versus isolated strong diagnostic;
- C: fixed raw model output → normalizer and comparator;
- D: fixed typed Claim → Evidence verifier.

Every attempt records the field identity, fixed input digest, result,
abstention, top-level error bucket, Evidence identity, manual actor, reason,
and active duration.

## Verdict and failure handling

Emit `KNOWLEDGE_COMPILATION_FEASIBLE_ON_NARROW_SLICE` only when all four fields
match their records in the frozen full Golden, all non-unknown Evidence
semantically supports the typed claim, `unknown` abstains, budgets remain
closed, and all four diagnostic arms complete.

Otherwise, do not average the failure away. Retain the exact failed field and
one of the frozen buckets:

`input_integrity | candidate_region | product_version | extraction |
normalization | comparator | evidence_verifier | abstention`

Only the directly demonstrated bottleneck may be corrected before rerunning
the same 2-material/4-field slice. A failed table artifact does not authorize
prompt tuning; a model failure under an oracle span does not authorize a
parser rewrite.

## Delivery boundary

The execution change may add only:

- a bounded run authorization/manifest;
- the two frozen input bundles;
- a projection manifest that references four records in the frozen full Golden;
- a thin one-shot runner or adapter only if existing commands cannot perform
  the exact W1 export and A-D run;
- targeted tests and the final evidence report.

It must not add a generic experiment platform, model router, Golden-management
system, database migration, production principal, Release integration, Wiki
publisher, provider fallback, full-suite mandate, or legacy cleanup.

After an S0-Q PASS, a separate MVP task may connect only the first real
reviewed Candidate/Release entry to WeKnora Wiki. No Wiki mutation is part of
this run.

## Verification

The run is accepted only with:

- exact source and bundle digest recomputation;
- W1 descriptor/chunk-manifest consistency;
- page and complex-table anchor inspection;
- deterministic tests for bundle validation, tri-state handling,
  normalization, comparator, Evidence verification, and budget fail-closed;
- one bounded live input capture against the local pinned WeKnora environment;
- one bounded provider run after model identities and budgets are frozen;
- independent Spec and Quality/Delivery review.

Full, production, unrelated provider, PostgreSQL, load, Release, and Wiki
publication tests remain out of scope.
