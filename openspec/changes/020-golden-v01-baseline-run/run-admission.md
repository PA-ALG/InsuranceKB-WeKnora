# Run admission: BLOCKED

- Canonical JSON commit marker: `3055f498f66d7d2544e1ed6c4ce56d2cf441a54b34fdd6879df88451c558aafc`
- This report is non-authoritative without the matching JSON artifact.
- Plan payload: `9a7df5f48cb49214993f6148645ba57a3016751e052cf27fbb3a6e567f0aaccd`
- Evaluated revision: `3a99f46b496baf7d6589ac80d992d0b2c512921b`
- Evaluated at: `2026-07-20T09:11:58.284080+00:00`
- Checker version: `020.1`
- Runtime capability: `budget-ledger-v3-canary-v1`

## Checks

- `budget_approval`: BLOCKED
- `budget_ledger`: BLOCKED
- `identity`: BLOCKED
- `provenance_approval`: BLOCKED
- `provider_probe:annotator`: BLOCKED
- `provider_probe:judge`: BLOCKED
- `provider_probe:weak_extractor`: BLOCKED
- `runtime_capability`: PASS

## Blockers

- `budget_approval`: `budget_contract_missing`
- `budget_ledger`: `budget_not_admitted`
- `identity`: `dependency_set_mismatch`
- `identity`: `digest_mismatch`
- `identity`: `dirty_consumed_file`
- `identity`: `execution_surface_unpinned`
- `identity`: `identity_contract_mismatch`
- `identity`: `missing_historical_provenance`
- `identity`: `missing_path`
- `identity`: `unconsumed_product_file`
- `identity`: `untracked_consumed_file`
- `provenance_approval`: `approval_missing`
- `provider_probe:annotator`: `model_identity_pending`
- `provider_probe:judge`: `model_identity_pending`
- `provider_probe:weak_extractor`: `model_identity_pending`

## Identity evidence

- Shared inputs: `1550782bb2cbd19a800f77dda7bb372f78283ce244b1fe0ca5fa63d2749963ad`
- Execution surface: `0e09004e568927a52db957aaf797e65551f633b48302189438b0b842111528f7`
- Product fingerprints: 13
- Blocker `dependency_set_mismatch` (`021`)
- Blocker `missing_path` (`平安福满分（2026）养老年金保险`)
- Blocker `unconsumed_product_file` (`平安福满分（2026）养老年金保险`)
- Blocker `execution_surface_unpinned`
- Blocker `execution_surface_unpinned`
- Blocker `execution_surface_unpinned`
- Blocker `digest_mismatch`
- Blocker `digest_mismatch`
- Blocker `digest_mismatch`
- Blocker `digest_mismatch`
- Blocker `digest_mismatch`
- Blocker `digest_mismatch`
- Blocker `digest_mismatch`
- Blocker `digest_mismatch`
- Blocker `digest_mismatch`
- Blocker `digest_mismatch`
- Blocker `dirty_consumed_file`
- Blocker `dirty_consumed_file`
- Blocker `dirty_consumed_file`
- Blocker `dirty_consumed_file`
- Blocker `dirty_consumed_file`
- Blocker `dirty_consumed_file`
- Blocker `untracked_consumed_file`
- Blocker `untracked_consumed_file`
- Blocker `untracked_consumed_file`
- Blocker `untracked_consumed_file`
- Blocker `untracked_consumed_file`
- Blocker `untracked_consumed_file`
- Blocker `untracked_consumed_file`
- Blocker `untracked_consumed_file`
- Blocker `untracked_consumed_file`
- Blocker `untracked_consumed_file`
- Blocker `missing_historical_provenance` (`平安e生保（尊享版）医疗保险`)
- Blocker `missing_historical_provenance` (`平安e生保（悦享版）医疗保险`)
- Blocker `missing_historical_provenance` (`平安e生保（惠享版）长期医疗保险（费率可调）`)
- Blocker `missing_historical_provenance` (`平安创享盛世金越（尊享版26）终身寿险（分红型）`)
- Blocker `missing_historical_provenance` (`平安守护百分百（2026）两全保险`)
- Blocker `missing_historical_provenance` (`平安盛世金越养老年金保险（分红型）`)
- Blocker `missing_historical_provenance` (`平安盛世金越（尊享版26）终身寿险`)
- Blocker `missing_historical_provenance` (`平安盛世金越（尊享版26）终身寿险（分红型）`)
- Blocker `missing_historical_provenance` (`平安盛世金越（至尊版26）年金保险（分红型）`)
- Blocker `missing_historical_provenance` (`平安福满分（2026）养老年金保险`)
- Blocker `missing_historical_provenance` (`平安附加（2026）失能收入损失保险`)

## Approval evidence

- `provenance`: BLOCKED
- `budget`: BLOCKED

## Provider probes

- `annotator`: BLOCKED (`not_attempted`)
- `weak_extractor`: BLOCKED (`not_attempted`)
- `judge`: BLOCKED (`not_attempted`)
