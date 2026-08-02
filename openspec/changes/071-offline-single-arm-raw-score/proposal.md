# 071 · Offline Single-Arm Raw Score

## Why

`IMPLEMENTATION IN PROGRESS / PROVIDER NOT RUN`

An independent recomputation of the frozen GPT-5.6-sol ceiling output found two
contract contaminations: a stale external adapter discarded the non-empty values of
`absent_explicitly` Golden records, and the existing public single-arm score labels a
non-approved strong model result as `SCORED`. The former inflated critical18 exact from
`4/18` to `5/18`; the latter can be mistaken for profile or production authority.

## What Changes

- lock the approved 049 parser contract: `present` and `absent_explicitly` retain their
  business value; only `unknown` maps to null;
- publish separate state, present, absent, Evidence and raw critical18 counts;
- classify any non-approved model/profile single-arm result as `UNADMITTED_RAW` while
  keeping raw arithmetic available for offline diagnosis;
- keep the approved DeepSeek/MinerU single arm `SCORED` and keep all existing custody,
  parser, Schema60, Evidence and Golden gates;
- let the offline 066 ceiling consume exactly one approved weak score and one
  `UNADMITTED_RAW` strong score without granting production or Release authority.

## Non-goals

- no provider, Golden, critical18 membership, parser, production route or Release change;
- no semantic adjudication, fallback, model judge or automatic approval;
- no generic evaluator or leaderboard;
- no filesystem, DB, WeKnora or GitHub operation.

## Path budget

Strictly nine paths: registry; four OpenSpec071 documents; existing 061 scorer source
and focused test; existing 066 comparator source and focused test. A tenth path stops
the mission.
