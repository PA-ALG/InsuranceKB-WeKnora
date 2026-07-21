# Operational Run Admission Design

This document adopts and mirrors the authoritative design in
`openspec/changes/031-operational-run-admission/design.md`.

The selected approach uses Bailian's `ptu_v2` request plan and validates the
provider-normalized `ptu` receipt for code-fixed Qwen 3.7 Plus and DeepSeek V4
Flash deployable IDs. A signed pre-provision authorization and durable fixed-cost
reserve must precede future provider mutations; the two operator-created resources
are treated as explicit preexisting-adoption candidates, not retroactive proof of
authorization. Legacy provenance keeps unknown timestamps explicit, approval keys
are bound to fixed identities/roles, and crash-safe reconciliation protects provider
ownership. Metadata probing performs zero controller inference calls, while fixed
reserved-capacity exposure remains separately visible.

The OpenSpec proposal, design, and O1-O8 acceptance specification are authoritative.
