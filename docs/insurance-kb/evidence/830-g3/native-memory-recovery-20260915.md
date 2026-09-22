# Native coordinate memory repair — software evidence

G3 NOT COMPLETE. Fresh fifth acceptance failed at source; three later APP process exits demonstrate that a transmission-cap change alone does not make the pipeline reliable. Existing source/material/release evidence is retained.

## Code and validation

The native projection and nested fixed-schema structures now declare fields in existing canonical key order. Their dedicated encoder writes exact canonical bytes without building an intermediate generic JSON tree. Generic canonical consumers remain unchanged. Two parser-identity reads decode only the header, then still execute the full native validation. Raw metadata, source artifacts, page/character coordinates, hash checking and signing semantics are unchanged.

|Requirement|Implementation|Validation|Status|
|---|---|---|---|
|G3-AUTO-3/6 native evidence compatibility|Native-only typed canonical encoder|Legacy generic encoder byte/hash oracle;42 focused tests,72including subtests|PASS software|
|G3-AUTO-6 strict source validation|Complete existing validator retained after lightweight header reads|Unknown/malformed/coordinate/missing-box/source-hash/raw-hash rejection plus native,first-parse,reuse and locator regressions|PASS software|
|G3-AUTO-4 resource efficiency|Avoid per-character generic trees and two redundant complete header decodes|Actual preparation allocation RED→GREEN plus synthetic benchmark|PASS software only|
|G3-AUTO-4 real recovery|Existing platform queue and webpage controls|Prior recovery resumed automatically but OOM; repaired runtime not yet deployed|NOT RUN for repaired runtime|

2048synthetic characters/156253native bytes:49381allocations before,86after; old implementation failed the20980allocation threshold while strict negative tests passed.50,000-character benchmark on same AppleM2/DarwinARM64/GOMAXPROCS2:

|Metric|Before|After|
|---|---:|---:|
|Preparation time,one iteration|457.922ms|169.063ms|
|Total allocated bytes per operation|96,616,992|37,188,000|
|Allocations per operation|1,200,420|250|

Allocated bytes fell61.5%; these are total allocations, not peak resident memory. This does not prove the actual91.65MB source fits in2GiB or meets an upload-to-publication SLA. No realPDF or model was used for code tests. Initial test compile with an unnecessarily newcache was stopped(exit143), then all reported tests reused the existing G3 Go cache; that interrupted compile is not RED.

Focused tests:42top-level/72including subtests passed,0failed,39.538seconds package runtime. Independent reviewer found0BLOCKER on three production files and test;diffcheckPASS. No generic encoder change, schema migration, model or authority change.

## Live configuration and availability history

- Task3ah reused exact APP/DocReader images and changed transport caps50→128MiB; configuration and internal health PASS19:48:56Z.
- APP0313 OOM at1GiB19:52:48Z. Same container resource update2GiB succeeded; an order-sensitive whole-object assertion stopped the first start procedure. A separate baseline comparison, including mounts sorted by destination, verified configuration and started it successfully19:57:17Z. The precise first assertion component was not captured; do not infer configuration corruption.
- Platform queue automatically resumed parser19:57:42Z without manual business continuation. It processed77parent/1372childchunks19:59:47Z, then APP OOM20:00:15Z.
- A later availability restart also resumed the queued work before webpage cancellation could be completed, and APP OOM20:09:38Z. No cancellation was submitted and no additional memory was granted.
- Availability restored2026-09-14T20:14:53.738947Z using retained APP3decc7fbd81527436b574c409e4e8fe5e1a0108468697f6b223dbfc82098862e, same d312image, original1GiB/client50MiB settings. Memory-failing0313 retained stopped. DocReader remains128MiB. Large responses are again rejected by the client until repaired APP is deployed; this is availability rollback, not business success.
- Formal GET freeze after rollback:37files,9terminal product runs,head epoch9/release-2f46c14c-5f6f-46cb-8eb2-e6afc7e5933e unchanged.

Evidence root `/private/tmp/g3-platform-independent-deploy-20260913/`: task3ai-native-memory-red-reused-cache.log,task3ai-native-memory-green.log,task3ai-native-memory-before-bench.log,task3ai-native-memory-after-bench.log,task3ai-native-regression.jsonl,task3ah-receipt.json,rate-reparse-resource-observation.json,task3ah-memory-recovery.json,task3ah-memory-start-receipt.json,task3ah-second-oom.json,task3ai-availability-rollback.json,task3ai-availability-restored.private.json.

## Delivery separation

Software PASS; repaired image/container health NOT RUN; repaired provider probe NOT RUN; repaired provisioning NOT RUN; repaired local live NOT RUN; GitHub live NOT RUN. The earlier source acceptance remains failed. Build/smoke/deploy must each provide separate exact source/image receipts before any real recovery claim.
