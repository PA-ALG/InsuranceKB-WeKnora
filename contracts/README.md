# Generated contracts

contract_version: "1"

These JSON Schemas are generated from `insurance_harness.contracts`.
From `harness/`, run `uv run python -m insurance_harness.contracts.export`
to regenerate, or append `--check` to check schema bytes without writing.
Do not edit the generated schemas. G9 reports every changed, missing or extra
schema as a violation, with no per-file baseline allowance.

Pydantic validators also enforce cross-field rules (locator required fields,
offset ordering and Claim states). JSON Schema provides structural validation;
consumers must additionally enforce platform and source-verification invariants.
