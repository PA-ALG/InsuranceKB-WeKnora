# Run admission: BLOCKED

- Canonical JSON commit marker: `3055f084e61825acf7347d60de5a901e2174e996b943e917da9616afc77ec1c9`
- This report is non-authoritative without the matching JSON artifact.
- Plan payload: `20acb5fbf5a58158f5d53e4007c629bba24946dfc1af97a3e1399ddff445d235`
- Evaluated revision: `62ce831c54490517d16cfe53e55b7d8476c80bbe`
- Evaluated at: `2026-07-21T02:51:11.250715+00:00`
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
- Execution surface: `bdd339e08aafbb0964025f026c697ccf3d0c2ab58934e61340b8b83ae61ea278`
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
