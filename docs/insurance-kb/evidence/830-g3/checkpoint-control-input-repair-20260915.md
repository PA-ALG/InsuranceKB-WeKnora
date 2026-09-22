# Task3aq checkpoint control-input boundary

Requirements: G3-AUTO-3/4/6. Root is the sole writer. Existing G3 runtime and stores are reused.

## Real Task3ap trial: FAILED

All components deployed source `2f2fe5ca87cbad3a3c0ea9ff12609a81aa139cb7`. Native webpage recovery click at 2026-09-15T04:41:52.577Z created `7c42de0e-fa1e-5927-94b5-88ab9cad5bda`; terminal `needs_confirmation / CHECKPOINT_INVALID` at 04:42:11.935192Z. No publication. Recorded new model calls: 0; complete aggregate flag false. This is not a successful incremental acceptance. Original `ef9bf57f-ae07-5206-b2d1-ff34c331f8a2` retains 9 raw responses (108,336 bytes), 82 field records (21 verified, 31 not_provided, 30 extraction_failed).

Read-only DB comparison: original version/materials and all seven reused stage snapshots match. Of 16 selected artifacts, old `processing_recovery_plan` (`5a37dec5-af98-5180-96ab-2674b97e0a61`) is an enqueue control input with producer_generation=0, different dependency, and source job generation=1. Other 15 artifact metadata bindings match. The selector incorrectly included control input among stage outputs. Worker correctly refused it.

## Code validation

| Requirement | Change / test | Status |
|---|---|---|
| AUTO-3/6 executed output custody | Select positive execution generation from current and inherited records; no artifact-kind blacklist; original plans unchanged | PASS |
| AUTO-3/4 legacy control input and failed verifier retry | Three new tests first fail on old selector: 3 failed / 5.80s; new selector complete checkpoint contract suite 12 passed / 14.41s | PASS |
| AUTO-3/6 scope/digest/dependency/generation | Existing five changed-original rejection cases remain in passing contract suite | PASS |
| AUTO-3/4 ordinary field failures and reuse | Full pipeline fixture includes legacy control input; resumes compilation, keeps failed fields/raw/prior bytes, no model/source resend, partial-success publication: 1 passed / 120.52s | PASS |
| Style / diff integrity | Ruff and git diff --check | PASS |

First test collection used an older editable package path and failed import; it is an environment error, not RED. Rerun with this worktree's `PYTHONPATH=harness/src:harness` produced the genuine three assertion failures above.

Independent reviewer `g3_admission_finish`: 0 BLOCKER on frozen diff SHA256 `9fb9aac4a6ca04344c145f937ff8cf9aa05f65093068736ad94c5e8599cef134`; no reviewer edits or business effects. Requirement/output coverage and complete worker custody checks remain in force.

## Delivery and business boundary

At code freeze: new Harness build/deploy and next native recovery trial NOT RUN. APP/UI reuse verified Task3ap artifacts; no APP/UI behavior changes. Only affected Harness is rebuilt through the repository Dockerfile and frozen source export. Next recovery is from the failed child, through the webpage, with a new timer. Fresh official product 2085-2 has three original PDFs saved but not uploaded or parsed by Codex. Full G3 remains incomplete until actual incremental and fresh-product platform-only flows are verified.

Private operational receipts are under `/private/tmp/g3-platform-independent-deploy-20260913/`; never commit credentials or runtime private configuration.
