# WeKnora App Trusted Supply Chain Design

**Status:** approved for OpenSpec 023 T6d by the user's instruction to continue with the trusted source-lock/GHCR path.

## Problem

The published `wechatopenai/weknora-app:v0.6.3` image was built before the scoped Tenant API Key routes existed. Real provisioning therefore stops at `GET /api/v1/tenants/:id/api-keys` with HTTP 404. Falling back to the legacy full-access key would violate the least-privilege contract.

Building a mutable image from the current dirty checkout is also unacceptable: it has no stable manifest digest or registry provenance, can accidentally include local `.env.*` files, and couples the WeKnora runtime artifact to unrelated Harness edits.

## Decision

Build the app in a dedicated, trusted GitHub workflow from a clean and exact Tencent/WeKnora revision, apply one checksum-locked downstream security patch, publish the result to GHCR, and consume it only by manifest digest.

The source lock records:

- upstream repository, full commit and tree IDs;
- the actual app Dockerfile path (`docker/Dockerfile.app`) and SHA-256;
- full required ancestor commits for scoped API keys and their security hardening;
- the exact downstream patch path and SHA-256;
- the target platform (`linux/arm64` for the current local acceptance host);
- the GHCR repository used for the immutable artifact.

The downstream patch contains narrowly scoped supply-chain/security changes: the R3.3 access-log change that omits the full response envelope for `/api/v1/models/:id/debug`, `.env.*` exclusion in the actual upstream Docker build context, `golang-migrate` pinned to the version already declared by `go.mod`, and a versioned uv installer whose script SHA-256 is checked before execution. It is kept separate from Harness code so its content and checksum are independently reviewable. The corresponding Go regression test remains in this fork and is run before the artifact is published.

## Trusted build flow

The workflow is `workflow_dispatch` only and must execute from `refs/heads/main`. It uses `GITHUB_TOKEN` with narrowly scoped `contents: read`, `packages: write`, `id-token: write`, and `attestations: write` permissions.

1. Check out the trusted repository workflow definition from `main`.
2. Parse the committed source lock using a standard-library verifier.
3. Clone Tencent/WeKnora into an isolated temporary directory and detach at the exact commit.
4. Verify repository URL, commit, tree, real Dockerfile SHA-256, every required ancestor, patch SHA-256, and target platform.
5. Apply the patch with `git apply --check` followed by `git apply`, and run the focused R3.3 Go test.
6. Build and push only `docker/Dockerfile.app` to `ghcr.io/pa-alg/insurancekb-weknora-app`, using the locked platform, BuildKit `mode=max` provenance, SBOM, and OCI source/revision labels.
7. Publish the immutable digest and verify the registry artifact/attestation. No model or local-live secret enters this workflow.

The ordinary `local_live.py up` path never builds an image. After a trusted build exists, a separate reviewed update writes the returned manifest digest to both `deploy/local-live/images.lock` and the WeKnora Compose override. Existing digest/loopback verification remains the runtime gate.

## Bootstrap boundary

GitHub executes `workflow_dispatch` definitions from the selected trusted branch. Therefore the workflow, source lock, verifier, patch, and tests must first be reviewed and merged to `main`. Only then can the trusted build run. The digest write-back is a second small change. This avoids executing an untrusted PR-supplied workflow with package-write and attestation permissions.

Before the new app first starts, the current WeKnora PostgreSQL database is backed up. The new source revision includes migrations newer than the published v0.6.3 image, so an old image is not a database rollback strategy.

## Failure semantics

- Any source-lock, ancestor, Dockerfile, patch, platform, test, build, push, or attestation mismatch fails before digest write-back.
- A missing scoped-key route remains fatal; no legacy key fallback is added.
- A mutable tag is never accepted by Compose, even if the same build also has a tag.
- `.dockerignore` excludes `.env` and `.env.*`; the trusted upstream checkout receives no local configuration files.
- Build logs and outputs contain source identities and artifact digests only, never model keys, administrator credentials, prompts, model responses, or local runtime secrets.

## Acceptance

The supply-chain phase is accepted when contract tests prove the lock and workflow invariants, the R3.3 Go test passes, Ruff/mypy/not-live pytest/OpenSpec strict pass, and the trusted main workflow publishes an arm64 GHCR artifact with provenance and SBOM. T7 remains `NOT RUN` until the resulting manifest digest is written back and real provision/VLM/five-node live acceptance succeeds.
