# 069 · Product 596-1 shared MinerU semantic task composer

## Why

The merged 061 runner has parse admission, Evidence verification, budget and
Golden-scoring authorities, but no concrete semantic task composer. OpenSpec
069 supplies one ProductVersion `596-1` task-local bundle over the exact MinerU
input. It does not implement an alternate parser arm or select a model.

## What changes

- consume exact 068 `mineru-semantic-content-custody.v2`, exact 060 admitted
  structure and exact 052 material/template/source authority;
- build a fixed ten-task plan: four terms semantic tasks, four brochure
  semantic tasks and two deterministic rate tasks, forming an exact Schema60
  bijection;
- bind exact arm/model, prompt, budget, normalizer, output contract, source,
  parser and custody identities while preserving the shared ten-task preimage;
- reuse merged 054 task/attempt/receipt and merged 057/064 Evidence/repair
  boundaries without copying their authority;
- parse strict JSON model output and accept known Evidence only when its quote
  and complete locator bind the same MinerU content/structure custody;
- consume the public 061 replay/admission receipt for the exact three inputs;
  caller-constructed `ADMIT` DTOs are not composition authority.

The same composed bundle is reusable by the DeepSeek V4 Flash weak arm and the
later 066 `gpt-5.6-sol` ceiling arm. Their exact model identities differ, while
the Schema60 partition and MinerU input authority remain the same.

## Dependency boundary

PR #97 / OpenSpec 068 is merged. 069 consumes its exact JSON v2 bytes and binds
the embedded raw/sanitized/content/config/attempt identity to the already
admitted 060/061 ParsedDocument, manifest and quality decision. It neither
copies the Go DTO nor treats Markdown as a structural locator. The existing
060 cross-page admission limitation remains a separate upstream boundary; 069
does not weaken it or manufacture an ADMIT receipt.

The frozen Golden18 authority contract is a downstream scoring handoff, not a
composer input. 069 remains Golden-blind and does not add that repository-external
artifact to its path or identity surface.

## Scope

Exactly four OpenSpec files, one task-local production module and one focused
test. No README registry edit because 067 owns that shared path.

## Non-goals

- an alternate-parser baseline or diagnostic admission path;
- provider transport, credentials, model calls, Golden reads or scoring;
- model selection, 066 implementation or strong-model authority;
- DB, migration, queue, WeKnora runtime or release work;
- a generic prompt/binder/parser platform or copied 052/054/057/064 authority.
