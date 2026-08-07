# OpenSpec 094 · 596-1 Bounded Capture-to-Admission Execution Wrapper

## Why

The three-source MinerU capture command and the private artifact admission runner are bounded
children, but there is no task-local execution seam that proves they are invoked exactly once in
the approved `terms → brochure → rate` order without exposing capture credentials or private
custody paths. Operators otherwise have to compose the two stages manually, which can introduce
retry, role drift, partial admission or unsafe logging.

## What changes

- Add one 596-1-only CLI/module that invokes only the existing Go
  `cmd/mineru-capture-596-1` dependency and then calls the 087 runner once.
- Freeze the exact PDF, executable/module, capture, intake and admission identities before the
  first capture call.
- Validate a new private `0700` capture root, exact three role directories and `0600` regular
  artifacts without following symlinks or accepting extra files.
- Pass the parent-process credential as `SecretStr` only to the capture child environment; never
  place it in argv, stdout, stderr, receipt or result.
- Preserve every allowlisted 087 blocked status and expose only fixed status and hashes.

## Non-goals

No capture/intake/admission implementation changes, raw JSON parsing, relation derivation,
provider execution in tests, retry/fallback/parallelism, Golden/Release action, DB, WeKnora,
shared workflow framework or production deployment.

## Dependencies

- Current Go command: `cmd/mineru-capture-596-1`.
- Future 091/092/087 composition through narrow injected Protocols only.
- No dependency may obtain write ownership over 082/083/087/091/092 implementation paths here.

## Stop conditions

- A third implementation/test path is required.
- The existing capture command cannot be invoked once without putting the credential in argv.
- 087 cannot consume exact three artifact paths plus one relation receipt through a mechanical
  adapter.
