# 101 marker-authority-envelope

## Why

OpenSpec099 correctly blocks a real bounded capture because current main has no
public, frozen 091 marker-custody authority that downstream code can hash and
replay. 091 validates private custody and exposes typed marker facts, but those
facts are not yet exported as a privacy-safe authority envelope.

## What changes

- add one task-local Python export that safely snapshots the exact three private
  091 custody files and reuses the real 083 intake validator;
- export immutable marker provenance for terms/rate sources, with canonical path,
  node, marker, source and envelope preimages;
- return only an in-memory frozen DTO; 101 has no file publication surface;
- keep relation source/target authority explicitly `UNBOUND`;
- fail closed for unsafe custody, non-canonical JSON, identity drift, unproved
  marker paths or concurrent mutation.

## Non-goals

No endpoint selection, cross-page relation inference, capture, provider/model,
Golden, database, PostgreSQL, WeKnora, live execution, generic artifact registry
or modification of 098/099/100 contracts.
