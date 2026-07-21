# 027 Validation Report

> Status: draft for T1 inventory freeze. No production implementation or real-provider
> validation is claimed here.

## Focused deterministic baseline

Command:

```bash
PYTHONPATH=src /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python \
  -m pytest -q tests/test_config.py tests/test_compiler_llm.py \
  tests/test_source_pipeline_cli_017.py \
  -m 'not live and not integration_postgres'
```

Recorded baseline result: **34 passed in 9.11s**.

Real provider: **NOT RUN**. The focused baseline is deterministic and does not prove
provider availability, production admission readiness, or completion of PWB1-PWB5.

The `uv` launcher is not used as negative product evidence in this environment: while
initializing its cache/system configuration under the sandbox it panicked. That is a
toolchain/environment difference, not a pytest failure; the repository Harness virtual
environment command above is the focused test result of record.

## Admission binding decision

When implemented, production authorization SHALL require two independently mandatory,
caller-declared expected values:

- `expected_run_id`
- `expected_run_revision`

Neither value SHALL be inferred, copied, defaulted or reconstructed from admission
**actual** observations. In particular, a successful probe, a matching artifact found on
disk, or a 020 canonical admission response SHALL NOT supply the expected identity of a
030 MVP run.

The future 027 adapter over prior admission output SHALL be read-only. When implemented,
`AdmissionBinding` SHALL normalize only these actual facts:

- actual run identity;
- actual run revision;
- actual admission state;
- actual admitted artifact hash;
- expiry;
- approved capability roles.

The adapter SHALL NOT settle admission, rewrite prior artifacts, infer expected values,
or broaden roles. When implemented, `ProductionModelPolicy` SHALL sign a `ModelPermit`
only when the independently supplied expected run identity/revision, actual
identity/revision, READY state, artifact hash, unexpired binding, requested role,
template/model-plan hash, immutable model identity and policy version all match exactly.
Missing, unknown, expired or mismatched data SHALL fail closed before network access.
Where candidate promotion is orchestrated, that future upstream orchestration boundary
SHALL validate the receipt before invoking the zero-model knowledge workflow; it SHALL
NOT push permit/admission parameters down into knowledge functions.

This required design is intentionally stricter than treating admission as a boolean.
Once enforced, it SHALL prevent borrowing 020 canonical status for 030 even when both
runs use the same provider/model; this is required intent, not a current implementation
claim.

## Scope and evidence status

- Entrypoint/package/command inventory: documented in
  `artifacts/entrypoint-inventory.md`.
- Real provider: **NOT RUN**.
- Production model policy/permit implementation: pending later 027 tasks.
- Provider contract or quality claim: none.
- Product CLI and knowledge importer/merge/review/source-lifecycle/publisher exports:
  recorded as zero-model boundaries that keep their own governance/approval/snapshot
  contracts. They receive no new `ModelPermit`, model policy, admission or receipt
  parameters; no product/knowledge code or state was changed.
- The gap described above is approved to be closed inside 027's own compiler/model-policy
  domain; no 020, 030, 031, knowledge, MCP, runtime, dataset or structured-import scope is
  borrowed.
