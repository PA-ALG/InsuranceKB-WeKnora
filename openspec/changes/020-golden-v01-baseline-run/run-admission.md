# Run admission: BLOCKED

> 此工件只表达 020 admission 状态。即使未来变为 `READY`，仍须验证 `NS-RIGHTS=recorded`、`NS-0=verified` 与经 027/028 批准的 execution surface；缺一即禁止模型调用。本报告不能授权直接加载旧 004/006 入口，也不能授权 030 MVP。

- Canonical JSON commit marker: `6d715252034e2a1d1bbda0350cc77edb75f32acc9355577fa5f75faf8f19eef2`
- This report is non-authoritative without the matching JSON artifact.
- Plan payload: `798a148585d75a0545460c82d3df5be9cdff589116c730ba3fc1a20d38a6e69a`
- Evaluated revision: `59695273ebc66d3f2613b81d07d1eb7a693dc20b`
- Evaluated at: `2026-07-21T05:41:39.699513+00:00`
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
- Execution surface: `76c22a97b3f627368ca6d71cbca64b6f461c7ff62132ff7db30f62f6b4f42010`
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
