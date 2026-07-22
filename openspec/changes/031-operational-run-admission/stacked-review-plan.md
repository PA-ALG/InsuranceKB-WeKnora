# 031 stacked review plan

> Status: planning manifest only. PR #26 remains Draft/BLOCKED. This document does not authorize
> commit, push, merge, provider mutation, or promotion to Ready.

## Review graph

```text
main
  └── A authority-cap
        └── B receipt-transport
              └── C adoption-cleanup-cli
                    └── D finalizer-wiring
```

The four heads form one security stack. Each head must compile, pass its focused tests, and remain
fail-closed for functionality owned by later heads. None of A–C is independently deployable, and
no partial head may be merged to `main` as an operationally ready system. Only the reviewed aggregate
A+B+C+D may enter `main`.

## Proposed branches, commits and review bases

No branch or commit below is created by this planning manifest. Construction starts only after total
control approves splitting the now-green aggregate worktree.

| Layer | Proposed branch / commit | Review base | Review intent |
|---|---|---|---|
| A | `codex/031-a-authority-cap` / `feat(031): harden operational authority and shared provider cap` | `main` | Review the production trust root, cap identity and ledger aggregation without deployment behavior. |
| B | `codex/031-b-receipt-transport` / `feat(031): bind deployment receipts to verified transport evidence` | A head | Review provider credential identity, ownership/reconciliation artifacts and durable topology joins as a delta over A. |
| C | `codex/031-c-adoption-cleanup-cli` / `feat(031): close adoption cleanup and operator ceremonies` | B head | Review the lifecycle that creates and consumes artifacts, including crash recovery, billing-stop proof and CLI signing ceremonies. |
| D | `codex/031-d-finalizer-wiring` / `feat(031): enforce canonical operational admission wiring` | C head | Review the only production execution wiring after all required opaque capabilities exist. |

PR #26 remains the aggregate A+B+C+D review and stays Draft. Stacked review PRs, if authorized,
target their immediate predecessor only; they are review aids, not independently mergeable releases.
After all four deltas are approved, the aggregate head is compared with the original reviewed worktree
tree hash, fresh gates are rerun on its clean SHA, and only the aggregate PR may be considered for
promotion. A–C are closed without merging to `main` after their review evidence has been captured.

Because `admission_budget.py`, `admission_deployment.py` and the cost tests contain changes from more
than one layer, stack construction SHALL use requirement/test-level hunks rather than whole-file
staging. Every commit must include the production invariant and its RED→GREEN tests together. If a
hunk cannot compile without a later-layer type, the smallest inert type/Protocol may be introduced in
the earlier layer, but its production entry point must remain unavailable or typed BLOCKED until the
owning layer lands. No temporary permissive flag, fake capability or caller trust override is allowed
to make an intermediate head compile.

## A — authority and provider-cap boundary

Review surface:

- fixed production trust roots and production/test capability-seal isolation;
- domain/role/scope/workspace/project/credential binding for signed authority objects;
- provider-cap approval/evidence identity, expiry, coverage and fixed+inference amount binding;
- shared-cap aggregation across run, purpose and account while isolating genuinely different cap
  resources;
- production cap acquisition from the canonical ledger, with no caller-supplied trust path, clock or
  self-enrolled capability.

Primary hunks:

- O1/O2 input normalization, canonical identity and provenance foundations in `admission_identity.py`,
  `admission_models.py`, the byte-preserving product-meta rename and their focused tests;
- `admission_authority.py`: domain-separated authority and fixed production trust policy;
- `admission_budget.py`: provider-cap schema/verification, shared-cap resource identity and reserve
  aggregation;
- `admission_infrastructure.py`: production/test capability issuer separation;
- authority, infrastructure-ledger and budget tests corresponding to T9.1, T9.2, T9.8, T9.13 and
  T9.16.

The exhaustive path/symbol/test allowlist is maintained in `hunk-replay-manifest.md`; this section is
only a review summary and SHALL NOT be used to omit source hunks.

Focused gate: authority + infrastructure-ledger + affected 020 budget tests, Ruff and mypy for the
changed modules. Later deployment/finalizer entry points must remain unavailable or typed BLOCKED.

## B — receipt, transport and reconciliation evidence

Depends on A. Review surface:

- canonical production controller/transport construction and non-secret transport credential
  identity attestation;
- exact workspace/project/credential/provider-cap approval join before any provider mutation;
- trusted ownership receipt issuer, immutable content-addressed receipt artifact and replay rules;
- independent content-addressed reconciliation artifact issued from fresh remote evidence;
- durable topology annex that binds both immutable receipt and renewable reconciliation evidence;
- strong/weak receipt, manifest, model, approval, role and observation drift rejection with zero
  reserve/account/row/cost mutation.

Primary hunks:

- `admission_deployment.py`: controller factory, transport identity, receipt and reconciliation
  artifact publication;
- `admission_budget.py`: receipt/reconciliation annex loading, exact contract-cap-workspace join and
  sealed final-topology reload;
- deployment and infrastructure-ledger tests corresponding to T9.3, T9.7, T9.9, T9.14 and T9.15.

Focused gate: deployment + infrastructure-ledger tests, including atomic-write failure, exact replay,
cross-operation/resource rejection and strong/weak tamper matrices; Ruff and mypy for changed modules.
C and D behavior remains typed BLOCKED.

## C — adoption, cleanup and operator ceremony

Depends on B. Review surface:

- adoption to verified receipt/reconciliation artifact production without test-side seeding;
- shared OS run lock, post-lock freshness recheck, idempotent replay and crash-safe artifact writes;
- cleanup authorization/ownership/receipt gate and conservative billing-stop semantics;
- complete offline render → external sign → verify ceremonies for provisioning, adoption, pricing,
  provider-cap and cleanup, without self-enrollment or private-key disclosure.

Primary hunks:

- `admission_deployment.py`: adoption and cleanup state machines;
- `admission_budget.py`: adoption reserve/final binding and cleanup lookup compatibility;
- `admission_cli.py`: operator ceremony commands;
- cost-cleanup, deployment and authority tests corresponding to T9.4–T9.6 and legacy migration cases.

Focused gate: authority + deployment + cost-cleanup tests, CLI subprocess contracts, Ruff and mypy.
Operational execution remains typed BLOCKED until D is present.

## D — canonical finalizer and production wiring

Depends on C. Review surface:

- one canonical finalizer for submit, resume and begin-product;
- fresh durable topology/provider-cap read for every transition;
- post-observation, pre-evaluator fresh reload plus post-evaluator defence-in-depth reload;
- fresh finalizer before the first-canary post-settlement candidate evaluator/write, followed by
  an independent durable topology/cap reload after that evaluator returns and before build/persist;
- removal of the pre-finalizer 020 evaluator/probe path;
- typed fail-closed handling for SQLite/filesystem infrastructure errors without swallowing
  `KeyboardInterrupt` or `SystemExit`;
- conservative cost-exposure reporting and zero evaluator/model/provider I/O/write before admission;
- validation report, handoff and OpenSpec evidence boundaries.

Primary hunks:

- `admission_coordinator.py`: observation refresh, finalization ordering and typed blockers;
- `run_020.py` and `admission.py`: canonical production entry-point wiring;
- coordinator and affected 020 entrypoint/wiring/runtime tests corresponding to T9.5, T9.7 and T9.12;
- `HANDOFF.md` and the 031 OpenSpec documents.

The D allowlist contains exactly 26 paths. Its sole deletion is
`harness/tests/test_operational_stack_blocker_031.py`, the A-C-only fail-closed sentinel. D must not
rewrite or relocate that test: the canonical finalizer's submit/resume/begin/post-settlement tests
replace it with stronger typed-blocker and zero-effect coverage.

Focused gate: coordinator + all affected 020 admission tests, then the aggregate A+B+C+D gates.

## Aggregate gate and branch handling

Before any request to mark Ready:

1. Run all 020/031 focused tests on the aggregate diff.
2. Run repository Ruff and mypy strict gates.
3. Freeze the exact 26-path candidate and obtain a final independent read-only review of all four
   trust boundaries.
4. Only after that review reports C/I=0, run deterministic
   `not live and not integration_postgres` exactly once on the same frozen tree.
5. Run OpenSpec strict validation and final diff/secret/private-material audit before review, and
   verify the frozen tree remains byte-identical when recording the post-review deterministic result.
6. Record real-provider/live as `NOT RUN` and preserve T2.3, external-signature, root-owned trust-store
   and provider-condition blockers.

The current branch is behind `origin/main`; rebase is deferred until the security fixes and final
review are stable. Any later rebase invalidates prior SHA-specific CI evidence and requires the
appropriate fresh gates. PR #26 must remain Draft unless total control explicitly changes that state.
