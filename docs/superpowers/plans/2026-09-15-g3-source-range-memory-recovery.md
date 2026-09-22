# G3 source range memory recovery

Existing G3-AUTO-3/4/6 and user authorization apply. Same environment; root owns edits, tests and deployment. Existing extraction agent supplies patches and existing reviewer checks them independently. No model, database or evidence contract changes.

Task3ai source 3eefd791 successfully parsed the large fee table, completing 60 embedding batches without HTTP failures. Its later product source snapshot request did not complete before the 120-second client timeout; another request followed, and APP hit its 2GiB limit at 20:46:12Z. This is a source capture failure, not a parser or model balance failure. No business continuation scripts are allowed.

Confirmed source bottleneck: g3FirstParseRangeMatches converts the whole document to runes for each chunk. Bindings, cached-source validation and snapshot page mappings repeat that work. On a synthetic 32768-codepoint/128-chunk fixture, bindings allocated 17,273,528 bytes and mappings 17,048,592 bytes, both exceeding the 4MiB regression budget. Invalid evidence tests still passed. This is cumulative allocation evidence, not proof of the precise OOM allocation site.

1. Reuse one rune conversion per binding operation. Share the validated native index's existing rune backing array with range checks and mappings. Keep the old helper signature compatible and support old test index literals.
2. Preserve every content/hash/range validation and snapshot output. Test multibyte text, emoji, invalid bounds/hash and old/new mapping equivalence; compare the source record's serialized bytes.
3. Apply patch only after actual RED; run focused native/source/reuse/first-parse/snapshot regressions and independent review.
4. Reuse the existing successful APP compiler cache and binary-only image build; keep the 2GiB cap, existing database/volumes/configuration. Preserve failed container and source receipts. Deploy only the code repair.
5. Resume via existing platform task mechanisms and webpage controls. Reuse successful parsing and embedding. Report this as recovery, never a new independent-upload acceptance.

Separate remaining concerns: pre-singleflight first-parse decoding, cancellation of expensive source work after request timeout, full native snapshot copies and count-only resident cache limits. Do not remove evidence checks or claim these are fixed by rune reuse.

## Validation and build bounds

48 focused top-level tests passed, zero failures. Synthetic bindings allocation fell to626,816 bytes and mapping to271,360 bytes; independent code review0BLOCKER. The existing VM has4.32GiB free after the prior successful incremental build (about0.9GiB net growth). Use a4GiB build admission threshold with the unchanged1GiB live stop reserve and1800second time bound. This changes a build preflight estimate, not storage size or runtime limits. No volume deletion, broad pruning or new database. Build and smoke scripts require independent review before execution.
