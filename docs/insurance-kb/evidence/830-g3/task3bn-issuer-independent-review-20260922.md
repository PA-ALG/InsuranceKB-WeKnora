# Issuer alias policy independent review — 2026-09-22

## Verdict

- **BLOCKER: 0**
- **BACKLOG: 0**
- **REJECTED: 0**

## Frozen scope

Reviewed the eight paths in
`tmp/g3-browser-acceptance-20260922/issuer-review-manifest.json` against base
HEAD `50a1ce762d54665bb51f65554fcb782c7aa3b1b0`. Every SHA-256 matched the
manifest. No production, test, database, configuration, deployment, or model
state was changed.

## Contract review

- Python and Go implement the same exact, whitespace-normalized issuer lookup,
  scoped by `space_ids`. They do not perform substring or company-name guessing.
- Declarations require a canonical name, at least one sorted unique alias, at
  least one sorted unique space, and a confirmation reference. Same-space
  normalized names cannot overlap or form a chained mapping.
- Non-empty declarations are included in the policy hash. Altering the
  confirmation reference invalidates the policy.
- An omitted legacy declaration remains omitted from Python serialization and
  Go `omitempty` serialization and hash preimages. Go accepts the old exact key
  set, accepts the new exact key set only with a non-empty valid declaration,
  and rejects explicit empty or null declarations.
- Source proposals, model values, evidence ownership, and locators remain
  unchanged. V3 canonicalizes only comparison and derived joint
  anchors/candidates. The policy SHA in the resolution inputs binds the user
  confirmation without presenting it as PDF evidence.
- Existing-entity comparison canonicalizes both proposed and published issuer
  values. Code, name, version, filing, source, confidence, and evidence checks
  remain in force.

## Cross-language and real-input evidence

- Python focused suite:
  `115 passed in 15.03s`.
- Ruff on the frozen Python production/test paths: passed.
- Go format check on all frozen Go paths: clean.
- Go fixed vectors plus recorded projection:
  `go test ./internal/types -run 'TestIssuerAliasPolicy|TestIssuerAliasRecordedProjection|TestEvidenceIdentityV3' -count=1`
  with `G3_RECORDED_IDENTITY_PROJECTION` set to the absolute recorded input:
  passed in `2.303s`.
- The recorded projection retains proposal issuers as `null`, `平安人寿`, and
  `中国平安人寿保险股份有限公司`; all three derived decisions use the canonical
  issuer, produce three CREATE decisions, and produce one medical binding with
  all three source materials. Go strictly decoded, hash-validated, replayed, and
  binding-validated that same Python projection.
- Frozen no-alias V1/V2/V3 vectors still pass Go replay; Python legacy policy
  serialization omits the new field and round-trips under its original hash.

## Recovery boundary

The current 368c failure occurred at identity validation and has no
`compile_request`. Its existing recorded identity response therefore enters the
established recorded-identity replay path, is adapted without another model
send, and is resolved under the newly configured trusted policy. A historical
checkpoint that already embeds a different policy in a compile request remains
fail-closed by the existing policy equality check, as the clarified spec
requires. Deployment preflight reports no active jobs, so that boundary does not
block this recovery.
