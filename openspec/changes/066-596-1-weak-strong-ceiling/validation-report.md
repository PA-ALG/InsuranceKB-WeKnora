# 066 · Validation Report

## Identity

- Final-main replay base/HEAD: `34f011d17bf575c2cfd089585e7c1f68efb19ac8`
- Base tree: `29ca41227eb3eec5eeeeaf87be54bbe04ae60197`
- Branch: `codex/066-deepseek-gpt56-ceiling`
- Dependency: 067 is merged into authoritative main; replay also preserves merged
  065/068 paths byte-for-byte.
- Scope: strict six paths

## Current evidence

- 067 focused baseline: `20 passed`.
- Initial RED: focused collection failed with `ModuleNotFoundError` because the 066
  module did not exist.
- Behavior RED: all `11` initial cases failed before the canonical hash domain was
  implemented correctly.
- Receipt replay RED: a public score with a foreign output hash was incorrectly
  accepted as `COMPARED`; the final boundary now blocks it.
- Exact weak-model identity RED: altered DeepSeek API base or model identity hash
  reached the fake scorer; both now block before scorer/Golden access.
- Corrective RED: public score-only construction bypassed FrozenArmOutput custody;
  foreign strong-score Golden content custody was silently accepted.
- Total-control B1/B2 review superseded the prior approved tree: a DeepSeek/foreign
  execution surface plus an arbitrary valid-looking model hash could be compared, and
  both arms could jointly replace the ten-task profile with the same arbitrary hash.
- New receipt/plan RED first failed collection because the external strong-execution
  receipt contract and approved task-plan identity did not exist. The corrective adds
  no receipt builder: it only verifies an externally supplied canonical preimage/hash.
- The approved task-plan preimage was independently read from the frozen 069 pure plan:
  ordered `8` semantic + `2` deterministic-rate tasks, exact three source hashes and
  a `60/60` unique field bijection. Its model-neutral hash is
  `198a24811fd0132eb6d59d013ca4ef20f59bb20e7644807c7177b875a8316439`.
- Final-main focused GREEN: `23 passed in 4.92s`.
- Final-main bounded 061 + 067 + 066: `150 passed in 9.91s`.
- Ruff exact source/test: `PASS`.
- Strict mypy exact source/test: `Success: no issues found in 2 source files`.
- OpenSpec 066 strict: `valid`.
- Exact-type successor tree `39fc756bfc41d6abff4fb4846da2b60b4a145eff`
  received independent delta FINAL approval with `BLOCKER 0` before main replay.
- B1/B2 independent successor review confirmed both original blockers closed on tree
  `50c0c164237b4ed7ab1f5577c74d3ca31ec28014`, then found one narrow exact-type
  blocker: a non-string hash field reached canonical encoding and raised instead of
  returning typed malformed. The reviewer-stable pre-corrective temp-index SHA256 was
  `2319d6be620a05eba29e0486ca6820d484b0e984427685454220b90be4272410`;
  the earlier owner-reported raw-index digest is invalid evidence and is not reused.
- Exact-type RED reproduced `CanonicalEncodingError: unsupported_type`; GREEN now
  validates every receipt scalar with exact `str` type before canonical hashing and
  returns `STRONG_EXECUTION_RECEIPT_MALFORMED` with zero scorer/Golden access.
- Mechanical main replay completed by stash/fetch/exact-main verification/ff-only/
  restore with zero conflicts. Source, focused test, proposal, spec and tasks blobs are
  identical to the independently approved successor; only this validation identity
  record changed.
- The strong arm freezes exact model id `gpt-5.6-sol` and the explicit
  `offline-codex-strong-ceiling` execution surface. Its external receipt binds run,
  shared input, approved task plan, model, prompt, budget and frozen-output hashes;
  missing/placeholder/foreign/forged receipts block before scorer or Golden access.
- Provider, model, real Golden values, live, DB, PG, WeKnora and full: `NOT RUN`.
- The implementation is an offline comparison contract only. It does not select a
  production model, call GPT as judge/fallback, or authorize Release.
