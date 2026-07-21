# Run admission: BLOCKED

- Canonical JSON commit marker: `ec7459bfef3538c97ecce35816ecd44e0fcd70207016f03750817513fc9ffc3f`
- This report is non-authoritative without the matching JSON artifact.
- Plan payload: `69b5f68c7613a42f09f232935b1460f86ac5a09ca4813b58a6c27d9b7269b7fb`
- Evaluated revision: `2169c5821021dfc9513d3cc760dea4fc4e519112`
- Evaluated at: `2026-07-21T05:06:59.830506+00:00`
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
- `identity`: `missing_historical_provenance`
- `identity`: `missing_path`
- `identity`: `unconsumed_product_file`
- `provenance_approval`: `approval_missing`
- `provider_probe:annotator`: `model_identity_pending`
- `provider_probe:judge`: `model_identity_pending`
- `provider_probe:weak_extractor`: `model_identity_pending`

## Identity evidence

- Shared inputs: `1550782bb2cbd19a800f77dda7bb372f78283ce244b1fe0ca5fa63d2749963ad`
- Execution surface: `c54935574d8f5d116fee2802ffd4ecb7de4bccdbbfa0bd71b2d61158e5d9e92f`
- Product fingerprints: 13
- Blocker `missing_path` (`平安福满分（2026）养老年金保险`)
- Blocker `unconsumed_product_file` (`平安福满分（2026）养老年金保险`)
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
