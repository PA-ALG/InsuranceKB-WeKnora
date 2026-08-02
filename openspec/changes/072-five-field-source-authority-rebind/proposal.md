# Change 072: five-field source authority rebind

## Status

`IMPLEMENTATION IN PROGRESS / PROVIDER NOT RUN`

## Why

The frozen strong-model blind adjudication identified exactly five
`TASK_INPUT_INSUFFICIENT` fields. Their approved 049 Golden Evidence is in
`保险条款.pdf`, while the merged 069/066 shared task plan routes them to the
brochure source. Model or scorer changes cannot repair an absent source.

## What changes

- Rebind only `zh_0c5a8e59e2`, `zh_14b93ce275`, `zh_17a83223e4`,
  `zh_f8cc996739`, and `zh_fd9a0b9fa3` to the exact terms material/source.
- Keep the existing ten-task, Schema60, two-arm model-neutral plan and all
  execution identities.
- Preserve every other field's task ID, source role and source hash.

## Non-goals

No model, prompt, normalizer, Golden, scorer, provider call, parser, general
routing framework, database, migration, WeKnora or Release change is authorized.
