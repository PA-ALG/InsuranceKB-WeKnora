# G3 final receipt independent review — 2026-09-22

## Verdict

- **BLOCKER: 0**
- **BACKLOG: 0** — the only editorial clarity issue found during review was closed before finalization: the closeout now explains that the machine receipt preserves the base `runs[].state=running`, while immutable finalization and the platform read view are authoritative, and that no active jobs remain.
- **REJECTED: 4** — reject treating `finalization.model_call_count=8` as the whole-run call total; reject treating 9m17 as a universal SLA; reject treating `partial_success` as a quality PASS; reject treating the EMPTY discovery result as evidence of non-empty discovery quality.

## Reviewed evidence

Read-only review at implementation HEAD `ec0721083c955af67d996aed883f6eab16fa9393` covered:

- `docs/insurance-kb/evidence/830-g3/task3bn-platform-closeout-20260922.md` (`b8ec2e83674f3dfe7ee9e5fcd4146682d4b756cc12bda5631cced1b90f363c46`)
- `docs/insurance-kb/evidence/830-g3/task3bn-fresh-3190-result-20260922.json` (`4e5faee00bd6ad832b0cbec7526d2e87c89a0bda824c4cfd8e0dec26307644f7`)
- `docs/insurance-kb/evidence/830-g3/task3bn-issuer-recovery-result-20260922.json` (`c26921f9d88ee076e14bb82d479c91a64e48cbb0c9ebc3f8f80329fcce59750e`)
- `tmp/g3-browser-acceptance-20260922/observed-runs.json` (`fbf31638d95630c2a03668f1059c996750970e817c3cb12c97ed63b84ee536ef`)
- `tmp/g3-browser-acceptance-20260922/fresh-3190-summaries.json` (`45a51c68407382f33b4056a0ec4b28a26710d05f279bda233e7111f8d6cf4b1a`)
- the prior live recovery review, HANDOFF top status, and OpenSpec 129 task/validation updates.

No source code, model, business run, deployment, database, or repository evidence file was changed.

## Receipt reconciliation

### Fresh 3190-2 run

The fresh result embeds the same run, finalization, stage-call, field-call, and verification records as the supplied observed snapshot. Stage rows preserve the observed fields and add only durations derivable from their timestamps. Its three summaries equal `fresh-3190-summaries.json`.

- Novelty boundary: `retry_of_run_id=null`, three preflight source documents, zero prior knowledge matches, zero existing entity matches, and all source-summary material rows have `reused=false`.
- Field outcomes: `25 verified + 19 not_provided + 31 extraction_failed = 75`.
- Calls: native `5+6+3=14`, identity `1`, field windows `8`, discovery `2`; total `25`. All 14 native attempts are confirmed and the source count is marked complete.
- Persisted readback: field calls `8/8`, stage calls `3/3`, 75 field outcome/result/raw references, 3 source snapshots, and 7 source-processing audit snapshots.
- Publication verification: epoch 17, the documented release ID, 75 fields, 76 members, 76 citations, 25 verified fields, 50 missing/non-valid fields, and one product search hit all match the receipt.

The document correctly distinguishes the whole-run 25-call count from `finalization.model_call_count=8`, which counts field windows only. It also reports ordinary-field retries as zero.

### Incremental issuer recovery

The recovery result embeds the same b696 run, finalization, stage calls, field calls, and verification records as the observed snapshot.

- The child points to a173 and begins with checkpoint followed by identity; it has no fresh source stage.
- Field outcomes: `33 + 14 + 20 = 67`.
- New calls: identity `1`, fields `7`, discovery `4`; total `12`.
- Publication verification: epoch 16, 67 fields, 68 members, 55 citations, 33 verified fields, 34 missing/non-valid fields, and one search hit match the receipt.

The closeout keeps this incremental recovery separate from the fresh 3190-2 sample. It also preserves the a173 provider failure and the corrected modern-checkpoint behavior: the new identity call is not described as legacy raw replay.

## Timing reconciliation

The fresh run clock starts at the last upload seal/finalization start `08:01:35.281665Z` and ends at finalization `08:10:52.653071Z`, exactly `557.371406` seconds.

Recomputing every table row from the preceding milestone to the current stage finish gives `556.731938` seconds. The documented final terminal write adds `0.639468` seconds, yielding `557.371406`. Rounded row values and the stated 9m17s are accurate.

The document correctly says this interval includes platform queues, window barriers, and source polling, excludes later manual UI inspection, and is one sample within the 5–10 minute optimization target. It explicitly avoids a general SLA claim and records that Codex was not literally shut down; navigating away while background work advanced is the evidence supplied for UI-independent progress.

The recovery duration is likewise exact: `07:51:05.265775Z` to `07:58:42.782903Z` equals `457.517128` seconds.

## Conclusion boundaries

The `G3 local FLOW PASS` conclusion is supported for the documented local acceptance scope:

- one checkpoint recovery reached automatic publication and verification;
- one fresh, uncached three-PDF product reached automatic publication and verification without post-upload code change, build, deployment, manual candidate construction, field repair, or manual publication continuation;
- the evidence UI opened one verified field at the cited original PDF page, and one failed field remained “待补充” without an unverified value;
- the machine receipts, HANDOFF top status, and OpenSpec 129 updates retain `QUALITY=DEFERRED_TO_Q0`, `NOT_FOR_PRODUCTION`, GitHub live `NOT RUN`, and the explicit scale, non-empty-discovery-quality, narrow-panel, and publication-cost limitations.

`G3-DISC-1/2 PASS（流程范围）` is acceptable because prior software evidence covers the rule and recovery behavior, while this live sample proves only that two discovery calls executed and produced an audited EMPTY result. The closeout explicitly says EMPTY does not prove discovery quality or a non-empty relation graph.

The supplied read-only live confirmation additionally reports the exact APP/Harness identities healthy and zero active jobs (`running=0`, `queued=0`, `retry_wait=0`; all jobs distributed only among `blocked`, `dead_letter`, and `succeeded`). That resolves the apparent base run-row `running` value under the finalization-authoritative contract.

## RED exemption

**Accepted.** These changes record already authorized acceptance observations and update their status/linkage; they do not change product behavior, implementation, requirement semantics, or the verification standard. The closeout binds the existing Requirement IDs to machine receipts and states the quality and production limits. Under the AGENTS read-only/normal-validation exemption, no new RED is required for this evidence-only recording. A future behavioral change or change to an acceptance criterion would require its own existing SDD/RED path.

## Review limitation

This was a bounded evidence/document review. It did not rerun source tests, invoke providers, query the active business task, or independently reconstruct private browser/session evidence beyond the supplied public receipts and the root owner's read-only live identity/job-count confirmation.
