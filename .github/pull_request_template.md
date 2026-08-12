<!-- Title should follow Conventional Commits, e.g. `feat: ...`, `fix: ...`, `docs: ...` -->

## Description
<!-- Briefly describe the purpose and changes of this PR -->

## Goal / Spec Authority
- Goal:
- OpenSpec ID(s):
- Requirement ID(s):
- Spec commit/tree:
- Unique write Owner / owner paths:

## SDD Evidence
- RED (old behavior and exact failure):
- Implementation (exact paths/commit):
- Validation (`Requirement → implementation → test → commit → PASS|BLOCKED|NOT RUN`):
- Deployment/live status (`PASS|BLOCKED|NOT RUN`; list migration/backfill/provider/Candidate/Draft/review/publish/activation separately):

## Mechanical Exemption
<!-- If no RED/OpenSpec applies, explain why this is purely mechanical/read-only/docs-only. -->
- [ ] Not used
- [ ] Used; exact reason and paths:
- [ ] Reviewer explicitly confirmed the exemption

## Type of Change
<!-- Check applicable items -->
- [ ] 🐛 Bug fix
- [ ] ✨ New feature
- [ ] 💥 Breaking change
- [ ] 📚 Documentation update
- [ ] 🎨 Refactor
- [ ] ⚡ Performance improvement
- [ ] 🧪 Test
- [ ] 🔧 Configuration / Build / CI

## Related Issue
<!-- If this PR resolves an issue, use "Fixes #123" or "Closes #123" -->
Fixes #

## Testing
<!-- Describe how these changes were tested. Include reproduction or verification steps. -->

## Checklist
- [ ] Goal, OpenSpec, Requirement IDs and frozen Spec identity are present
- [ ] RED precedes implementation, or the mechanical exemption is justified and reviewer-confirmed
- [ ] Requirement-to-evidence matrix has no implicit/blank status
- [ ] Fixture/provider-zero results are not described as business or live truth
- [ ] Deployment and all `NOT RUN`/`BLOCKED` items are explicit
- [ ] Applicable focused/static/docs gates pass; inapplicable full/live gates are marked `NOT RUN`
- [ ] Self-reviewed the code
- [ ] Added/updated tests covering the change
- [ ] Updated related documentation (README, `docs/`, Swagger annotations, etc.)
- [ ] Breaking changes are clearly called out in the description above

## Screenshots / Recordings
<!-- Required for user-visible UI changes -->
