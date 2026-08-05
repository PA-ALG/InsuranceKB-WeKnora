# 081 · Implementation Tasks

## T1 · Contract and RED

- [x] Verify the existing workbook bytes match the approved historical SHA-256.
- [x] Freeze exact sheet/table/header/input-cell/decision-vocabulary structure.
- [x] Add a focused blank-workbook RED before implementation.

## T2 · Fixed XLSX intake

- [x] Parse only the fixed OOXML contract with standard-library primitives.
- [x] Reject hash, sheet, header, row/column, hidden, formula, error and vocabulary drift.
- [x] Return exact pending fields/counts for incomplete human decisions.

## T3 · 075 request bridge

- [x] Revalidate caller-provided record authority against displayed cells.
- [x] Bind completed-workbook SHA-256 into every decision reason and request hash.
- [x] Reuse public 075 DTO/hash/evaluator APIs; produce no signature or successor.

## T4 · Adversarial matrix

- [x] Reject duplicate/missing/reordered rows, hidden/extra rows or columns, formulas,
  errors, illegal decisions and custom-record drift with zero 075 output.
- [x] Prove typed error results contain no workbook free text or human answer values.

## T5 · Verification

- [x] Focused 081 plus bounded 075 regression, Ruff, strict mypy and OpenSpec strict.
- [x] Diff/scope/private/secret checks and stable exact-tree custody.

## Stop conditions

- A change to 075 semantics, Golden artifacts, README, 079/080 or a seventh owner path
  is required.
- A signer, provider/model, DB, WeKnora, live or production action is required.
