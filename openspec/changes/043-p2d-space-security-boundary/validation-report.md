# 043 Validation Report

> [!IMPORTANT]
> **2026-07-29 status override**：
> `SPEC-ONLY / REQUIRES AMENDMENT AFTER S0-R`。本报告证明原 PR #57 的
> Space/ACL/epoch/跨 Space/失败零写规格质量，不批准其旧
> `wiki_projector`/projection binding 进入实现，也不批准 migration 0016。

## Candidate

- base: `40f3ae9e4b41fab51566c438da08c57d80e3089b`
- branch: `codex/043-p2d-space-security-boundary-spec`
- delivery: documentation-only OpenSpec / plan; zero production code and zero
  migration
- allowed paths: the existing six paths listed by PR #57

## Corrective scope

The first Draft was over-specified (1,660 changed lines) and combined binding,
security profile, provider/P1 fencing, Candidate/promotion and receipts. The
single corrective reduces 043 to one user value:

> P3-derived Space scope + RAW/Wiki ACL equivalence + immutable current
> binding/epoch + cross-Space rejection + failure zero-write.

CompilationSecurityProfile, provider authorization, P1 active-fence and
Candidate/promotion snapshot are explicitly backlog/new Mission Card items.

## Dependency readiness snapshot

Read-only check on 2026-07-28:

| Dependency | Exact evidence | Status for foundation implementation |
|---|---|---|
| P3 principal and Space scope | final PR #58 head `9f5d9c7736fc95417a67f962e6205627c5c3b8d5`, merged in main `3cfe1fd0650059b4e6dd43e539af352616c4b712`; `HumanPrincipal`, `ServicePrincipal`, `StaticPrincipalProvider.authenticate`, `require_space_role` | available; interface facts unchanged |
| P3 ACL inspection authority | PR #58 has only `read_raw_knowledge` and `project_managed_page`; no RAW+Wiki ACL inspection contract | **BLOCKER**; separate small P3 Mission required |
| P1 read-only active fence | current P1 exports `JobStore`; `heartbeat` renews lease | backlog for provider authorization, not a 043 foundation dependency |

The spec does not create a third principal or use fake credentials to hide the
P3 gap.

## Review finding closure

- **BLOCKER addressed:** six documents are reduced to the foundation contract;
  downstream security/provider/release domains are removed from current
  acceptance.
- **BACKLOG:** P3 ACL inspection authority; CompilationSecurityProfile;
  provider/P1-fence authorization; Candidate/promotion security snapshot.
- **REJECTED from 043:** generic ACL platform, P2d-owned credentials, third
  service principal, production code/migration in this corrective.

## Fresh documentation gates

- strict OpenSpec 043: `PASS` (`Change ... is valid`; telemetry flush warning
  did not change exit status)
- `git diff --check`: `PASS`
- exact six-path scope: `PASS`
- private/secret/absolute-path scan: `PASS`
- UTF-8/LF scan: `PASS` (six changed Markdown files)
- final change size before commit: 543 insertions / 2 deletions relative to
  base; the five 043 documents total 539 lines
- functional/full/provider/live/PostgreSQL: `NOT RUN` (documentation-only)
