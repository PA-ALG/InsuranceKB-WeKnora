# 089 implementation plan

> Execute inline with `superpowers:executing-plans`; use strict RED → GREEN and
> do not commit, push or open a PR from the owner lane.

## Task 1 · Freeze companion authority

- [x] Verify exact main and read 062/083/086 contracts.
- [x] Freeze a separate companion contract; do not mutate 062 v1 DTO/hash input.
- [x] Keep endpoint/relation derivation and admission outside 089.

## Task 2 · RED

- [x] Prove the existing 062 projection loses the typed marker kind.
- [x] Require distinct `cross_page` and `lines_deleted` evidence at the same path.
- [x] Add replay mutations for kind/type/page/path/local-index/member/raw/source/version/hash.
- [x] Reject duplicate and unknown companion marker identities.
- [x] Prove body, HTML/Markdown, URL, secret and member path are absent.

## Task 3 · Minimal GREEN

- [x] Extract typed markers only from exact MinerU 3.4.4 structural nodes.
- [x] Bind source/parser/version/ZIP/member and deterministic per-marker/envelope digests.
- [x] Replay by recomputing from exact raw ZIP bytes; emit no endpoints or relations.
- [x] Preserve 062 v1 JSON fields and semantic projection hash behavior.

## Task 4 · Verify and freeze

- [x] Run focused 089 and bounded 062/083-compatible regressions.
- [x] Run Go vet, OpenSpec strict, candidate diff/scope/private/secret gates.
- [x] Freeze exact seven-path candidate; provider/Golden/DB/WeKnora/live/full remain NOT RUN.
