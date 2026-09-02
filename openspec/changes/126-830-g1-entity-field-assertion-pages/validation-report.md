# 126 · Validation Report

## Current identity

```text
GOAL_ID=G1
BASE=d2ce44cb2107575f7624b3735c653078ae2a98b6
BRANCH=codex/830-g1-field-assertion-pages
CURRENT_RED=M3_SUCCESSOR_SERVING_IDENTITY_AND_HISTORICAL_SOURCE_BRIDGE_MISSING
FLOW=G1_IN_PROGRESS
QUALITY=DEFERRED
DOCKER_ACTION=APP_REPLACEMENT_AUTHORIZED_ONE_BUILD_FRONTEND_REUSE
G2_AND_LATER=LOCKED
M0_INITIAL_REVIEW=FAIL
M0_INITIAL_UNRESOLVED_COUNT=3
M0_CORRECTION=PASS
M0_REVIEWED_HEAD=bc93bbef19e24877f0a8816dc49395bc662d703f
M0_REVIEWED_TREE=71601455e486fe7b21b358032939b0799cafbc8f
M0_REVIEW_UNRESOLVED_COUNT=0
WIN1_CONTRACT_HEAD=8fa27956c6368502f21d52245d2cea905f0e2ce1
WIN1_CONTRACT_TREE=82e490ef47da775aed0d8176c7f31a27f6d537e9
WIN1_REVIEW=PASS
WIN1_REVIEW_UNRESOLVED_COUNT=0
WIN2_CONDITION=PASS
WIN2_WRITE_DOMAIN_DISJOINT=true
WIN1_ACTUAL_EVIDENCE_LANE=OPEN
NEXT_PHYSICAL_RESULT=SPEC_REVIEW_PASS_THEN_TDD_RED
M1_DEADLINE=2026-09-02T23:42:03+08:00
M1_RUNTIME_HEAD=740d9b7c55f047e30c59c087dc29b943e3849726
M1_RUNTIME_TREE=bb29b5d6cf9533f69bd14728736e916513f3119c
M1_PREPARATION_ID=g1-m1-740d9b7c-preview
M1_MANIFEST_SHA256=3ae19c3254df73d9ed678a440404c9c2ec67319709c33c9bb8000c0a15da6a3c
M1_PREVIEW=PASS
M1_EVIDENCE_REVIEW=PASS
M1_EVIDENCE_REVIEWED_HEAD=6ed49abab3cc9e0428b8648e93e1c2e0a313d8e5
M1_EVIDENCE_REVIEWED_TREE=83792e58f0b453c13af7543649391b0ff71d8b74
M1_EVIDENCE_REVIEW_UNRESOLVED_COUNT=0
M2_INITIAL_REVIEW=FAIL
M2_INITIAL_REVIEWED_HEAD=d1b8d8e9e1213a28d4b762f0767120b121b218c1
M2_INITIAL_REVIEWED_TREE=4ada9652d998f3b2effcaea29552aaee840f2ebd
M2_INITIAL_REVIEW_UNRESOLVED_COUNT=1
M2_CORRECTION=PASS
M2_REVIEW_TASK=01a05c5d-0483-7641-9bec-948442015a0d
M2_REVIEWED_HEAD=edc74ac7fb82dcb8e443020bab151a116f57ef32
M2_REVIEWED_TREE=4ada9652d998f3b2effcaea29552aaee840f2ebd
M2_REVIEW=PASS
M2_REVIEW_UNRESOLVED_COUNT=0
M2_EVIDENCE=PASS
M3_INTEGRATION_HEAD=06b101665921844cabf666574514c2b71ebd4b12
M3_INTEGRATION_TREE=e14c5057f87427670f8a0382b357b6970ecd74f8
M3_D2_ORIGINAL=PASS
M3_D2=REOPENED_APP_ONLY
M3_D2_REPLACEMENT_BUILD_BUDGET=1
M3_D2_REPLACEMENT_BUILDS_USED=0
M3_D2_APP_BUILD_CLIENT_EXIT=130
M3_D2_APP_BUILD_RESULT=PASS_LATE
M3_D2_APP_IMAGE=sha256:f913037cfe74a7bbd7e8a819a56ccb92fea32ae3da4b6511d460a04f3b920327
M3_D2_FRONTEND_BUILD_RESULT=PASS
M3_D2_FRONTEND_IMAGE=sha256:ebf4f45a7279e44a9a6dea9394a58d90b6f6c70d259dd0c9b4a472c906783da0
M3_D2_FRONTEND_DISPOSITION=REUSE_NO_REBUILD
M3_D2_ORIGINAL_APP_DISPOSITION=IMMUTABLE_SUPERSEDED_PENDING_REPLACEMENT
M3_PRODUCTION_8081_BEFORE=200
M3_PRODUCTION_8081_GUEST=200
M3_PRODUCTION_8081_HOST=CONNECTION_REFUSED
M3_RELEASE_LIFECYCLE=NOT_RUN
M3_PROVIDER_MODEL_CALLS=0
G2_AND_LATER=LOCKED
```

## Requirement matrix

| Requirement | RED | Implementation | Focused test | Commit | Live evidence | Status |
|---|---|---|---|---|---|---|
| G1-R1 | PASS | Harness + Go + entity UI | focused PASS | `edc74ac7` | stable UI routes + M2 identity mutation 76/76 PASS | M2 PASS |
| G1-R2 | PASS | 76-member manifest + Draft snapshots | focused PASS | `edc74ac7` | Draft + M2 identity index 76/76 PASS | M2 PASS |
| G1-R3 | PASS | tri-state FieldAssertion | focused PASS | `edc74ac7` | all 67 pages, state `2/1/64` PASS | M2 PASS |
| G1-R4 | M3 RED | M1 preview bridge PASS; successor historical-source bridge missing | M1/M2 focused PASS; M3 NOT RUN | `edc74ac7` + pending | M1 exact click + M2 known custody 17/17 PASS; successor click NOT RUN | M2 PASS / M3 OPEN |
| G1-R5 | PASS | payload Profile + namespace metadata | focused PASS | `edc74ac7` | short titles + 76/76 namespaces PASS | M2 PASS |
| G1-R6 | PASS | existing preparation writer accepts atomic 76 snapshots | focused PASS | `740d9b7c` | Draft 76/76 PASS; Release NOT RUN | M1 PREPARATION PASS / M3 RELEASE NOT RUN |
| G1-R7 | M3 RED | preparation no-fallback PASS; successor current/pinned exact identity missing | M1 focused PASS; M3 NOT RUN | `740d9b7c` + pending | preparation Preview PASS; successor current/pinned NOT RUN | M1 PARTIAL / M3 OPEN |
| G1-R8 | PASS | no second authority; existing C6 source viewer | focused PASS | `edc74ac7` | exact source custody; zero second authority PASS | M2 PASS |
| G1-R9 | PASS | Profile-driven compiler/renderer | focused PASS | `edc74ac7` | actual seven-section UI + generic two-section PASS | M2 PASS |

M0 文档/规格变更采用 D0；当时功能 RED、实现、Docker 和 live 均未运行。只有实际命令与
不可变回执可改变本表状态，fixture/code GREEN 不得改变 FLOW 或 BUSINESS 状态。

初次独立复核在 commit `0f1cbe1840774aca6e1a3eb74bbc65687d97680b`、tree
`447dcbde22641136effc6d612134caeb7348fc4f` 上报告 3 个 BLOCKER。总控在
`bc93bbef19e24877f0a8816dc49395bc662d703f` / `71601455e486fe7b21b358032939b0799cafbc8f`
完成唯一 M0 纠偏；同一只读 Review 复核为 PASS、`UNRESOLVED_COUNT=0` 后才启动 Win1。

## Harness contract freeze

- Win1 可见任务：`01a058c0-1937-7d93-8bb3-92ee7f19dbf0`。
- 首个合同 commit `b33c7f8be0e9c41dbed194b94725a2a208db5c4b` 经独立 Review 报告 3 个
  跨对象语义闭包 BLOCKER；总控没有放行 Win2。
- 最小修正 commit `8fa27956c6368502f21d52245d2cea905f0e2ce1`、tree
  `82e490ef47da775aed0d8176c7f31a27f6d537e9` 关闭 overview→section、
  reference→citation/evidence receipt、citation→source authority 三类完整重哈希漂移。
- 独立只读 Review `01a05917-a8e7-7b00-bf36-82bef310c2a5` 复验 PASS，
  `UNRESOLVED_COUNT=0`；R1-R5/R8/R9 的跨语言合同可以供 Win2 消费。
- 合法 vector file SHA-256 为
  `cffb39e5a7214e2720b54a80acacab6923afa8e00e6174befc88b3cd44e069d1`，manifest
  SHA-256 为 `3ae19c3254df73d9ed678a440404c9c2ec67319709c33c9bb8000c0a15da6a3c`。
- 总控独立验证：actual focused `14 passed`；hermetic `11 passed, 3 skipped`；既有
  regression `43 passed`；Ruff、format、py_compile、strict mypy、diff-check 全部通过。

这些证据只冻结 Harness 离线合同。G1-R6/R7、真实 WeKnora Preview、current/pinned、
UI 与 source-click 仍为 NOT RUN；FLOW 继续为 NOT_RUN，不能报告 M1 或 G1 PASS。

Win2 条件成立：Win1 三条 Harness 写域已经冻结；Win2 的 Go/Frontend 路径与其完全互斥；
共享 vector 经独立 Review PASS；Win1 继续负责 actual 815 编译重放/证据支持，Win2 负责
WeKnora validation/read/UI，两者直接汇合到同一个 M1 Preview。最多仍为两个可写 lane，
不得扩大到 G2 或新增服务/表/authority。

## M1 real Candidate Preview

- Runtime source: `740d9b7c55f047e30c59c087dc29b943e3849726` / tree
  `bb29b5d6cf9533f69bd14728736e916513f3119c`; isolated backend `18094`, frontend
  `18085`, Draft `g1-m1-740d9b7c-preview`.
- Exact manifest: `3ae19c3254df73d9ed678a440404c9c2ec67319709c33c9bb8000c0a15da6a3c`;
  source release `release-42a3dd0c-ec76-4017-a288-37f1b13519a0`, epoch `2`; 76 members,
  67 fields, `present=2 / absent_explicitly=1 / unknown=64`, empty free_wiki.
- UI evidence: `docs/insurance-kb/evidence/830-g1/m1/entity-page-preview.json` and seven
  screenshots under `docs/insurance-kb/evidence/830-g1/m1/ui/`.
- Source evidence: `docs/insurance-kb/evidence/830-g1/m1/source-click.json`; real click opened
  the frozen source PDF on page 2 with exact bbox. Page/locator mutation tests return typed
  unavailable before snapshot fetch; UI emits `PDF_PREVIEW_UNAVAILABLE` and makes no
  current/latest/content/page-1 fallback.
- Runtime/effects: `docs/insurance-kb/evidence/830-g1/m1/runtime-identity.json`; Preview read
  window counts stayed `3/2/150/1/2`, Head stayed on the source release/epoch, Provider/model
  calls were zero, and production `8081` container/image/start identity stayed unchanged.
- Independent read-only Review of the implementation candidate at the same head/tree reported
  `REVIEW=PASS`, `UNRESOLVED_COUNT=0`. M1 evidence itself remains controller-owned and must be
  committed/re-reviewed before advancing to M2.
- The first evidence-commit review at `cf05e8af372aed8336bf3f6945b2be27ca54d70f` /
  `4b1b20d799b940fb312bb8cb75cdb5c7c74d2fa9` reported `REVIEW=FAIL`,
  `UNRESOLVED_COUNT=2`: the NEXT pointer still named completed M1, and controller-created M2
  evidence appeared in the shared worktree before the M1 gate closed. The M2 files were preserved
  outside the worktree and the NEXT pointer was corrected; the correction still requires the same
  independent read-only re-review.
- Corrected commit `6ed49abab3cc9e0428b8648e93e1c2e0a313d8e5` / tree
  `83792e58f0b453c13af7543649391b0ff71d8b74` advanced NEXT to M2 and restored a clean
  M1 review tree. The same independent read-only Review returned `REVIEW=PASS`,
  `UNRESOLVED_COUNT=0`.

M1 是真实 Candidate Preview PASS，不是 G1 最终 PASS：没有 Review/Release/activation，
也尚未形成 M3 successor current/pinned/no-mix 物理证据。G2 继续锁定。

## M2 complete page graph accepted

- `docs/insurance-kb/evidence/830-g1/m2/identity-hash-index.json` lists all 76 ordered
  page identities, routes, namespaces, member digests and payload hashes; all four identity domains
  are 76/76 unique and replay from the exact M1 manifest.
- `docs/insurance-kb/evidence/830-g1/m2/complete-page-graph.json` records the 1/7/67/1
  topology, exact section membership, `2/1/64` tri-state distribution, all 17 citations for the
  three known fields, title/classification identity mutations, and the generic 2-section compiler
  and renderer tests.
- Fresh verification: Harness `14 passed`; exact Go source-custody pair `2 passed`; Go full package
  regression PASS after the authorized loopback rerun; Go vet PASS; focused frontend `36 passed`;
  frontend typecheck, Ruff and diff-check PASS.
- The first candidate metadata at `d1b8d8e9e1213a28d4b762f0767120b121b218c1` advanced NEXT
  to M3 before the tree's M2 gate closed. The reviewer reported one BLOCKER; the controller only
  reworded the unpushed tip. Corrected head `edc74ac7fb82dcb8e443020bab151a116f57ef32`
  retained exact tree `4ada9652d998f3b2effcaea29552aaee840f2ebd` and aligned both NEXT values to M2.
- Visible read-only Review `01a05c5d-0483-7641-9bec-948442015a0d` accepted that exact corrected
  head/tree with `REVIEW=PASS`, `UNRESOLVED_COUNT=0`; M2 is closed. Evidence records zero
  DB/release/head/Provider/model/production/G2 effects. M3 remains NOT RUN.

## M3 D2 app-build reconciliation

- Integration identity remains frozen at `06b101665921844cabf666574514c2b71ebd4b12` / tree
  `e14c5057f87427670f8a0382b357b6970ecd74f8`. B0 impact mapping selected only app and
  frontend; Dockerfiles and lockfiles were unchanged.
- The exact frontend dist build completed. The only app image build reached
  `go build ./cmd/server`; its SSH client observation was terminated with exit `130`, but the
  original BuildKit job continued and materialized the requested tag at
  `2026-09-02T02:45:38.736896529+08:00`. The resulting `linux/arm64` image is
  `sha256:f913037cfe74a7bbd7e8a819a56ccb92fea32ae3da4b6511d460a04f3b920327`.
- The image labels bind exact commit `06b101665921844cabf666574514c2b71ebd4b12`, tree
  `e14c5057f87427670f8a0382b357b6970ecd74f8`, app source subset
  `2d0cab1d69dca42357b3fd2016dea4e48bd1d6f5d002ac45f8b95285d3321b27` and Go lock
  `5969f57adb73d1c607c6d8389950d36761d8f967e92af7d1b8a6e1b97baebfe7`; it is therefore
  the first build's delayed success, not a replacement build.
- The false STOP used raw `limactl`, which queried default `~/.lima`; Colima's actual
  `$HOME/.colima/_lima` instance is continuously `Running`. VM/Docker restart count, OOM and
  disk-full evidence are all zero. Exact production app/frontend containers remain healthy and
  HTTP 200 inside the guest; only host `8080/8081` forwarding is unavailable.
- Original incident receipt remains immutable at
  `docs/insurance-kb/evidence/830-g1/m3/d2-build-stop.json`; superseding conclusions are recorded in
  `docs/insurance-kb/evidence/830-g1/m3/d2-app-build-reconciliation.json`. App D2 is `PASS_LATE`.
- The one and only frontend D2 build produced `linux/arm64` image
  `sha256:ebf4f45a7279e44a9a6dea9394a58d90b6f6c70d259dd0c9b4a472c906783da0` at
  `2026-09-02T22:46:28.632832031+08:00`. Its labels bind the same frozen commit/tree, frontend
  source subset `b1bad86d3e1735086ac2fc1b835ea90d313ac4978aa3a3235c449c2211680935` and
  package lock `dc2c1507f80ddf1404e94394e98c2de1ca89177e5b1373e77271f4ee88da90fb`.
- Unified original D2 receipt: `docs/insurance-kb/evidence/830-g1/m3/d2-image-build.json`. It remains
  immutable evidence that app `f913037c...` and frontend `ebf4f45a...` were built successfully;
  D3 Release/Head, Provider/model and G2 remained NOT RUN/zero at that checkpoint.

## M3 app-only D2 reopening authorization

- Pre-D3 static path review found that app `f913037c...` lacks the M3 successor
  historical-source bridge and equates the successor serving identity with the old 815 source
  identity. A real CAS would therefore create a successor that the entity reader rejects.
- The user explicitly authorized the recommended minimal repair and one app-only replacement
  build. This supersedes only the previous `D2_PASS_NO_MORE_BUILDS` conclusion for app; it does
  not erase or retag the original image/receipts and does not reopen frontend.
- Replacement app build budget is exactly one and remains unused. Before it is consumed, the
  written design must pass independent review, then TDD must prove RED/GREEN for Head-independent
  historical successor pinning, immutable base source binding and both current and exact-pinned
  historical-source citation bridges. D3 must then use the replacement app identity plus unchanged
  frontend `ebf4f45a...`.
- The final independent design review closed all five prior findings but found one remaining test
  contradiction: the frozen manifest cannot legally create G1 successor R2 because CAS would bind
  R2 to R1 rather than to the old 815 source. The design now uses a non-G1 control Head to prove
  current fail-closed plus Head-independent pinned R1/source replay. This exact correction still
  requires user review before TDD starts; no fourth independent review is silently assumed.
- Production containers/Head, Provider/model paths and G2 remain untouched and locked.
