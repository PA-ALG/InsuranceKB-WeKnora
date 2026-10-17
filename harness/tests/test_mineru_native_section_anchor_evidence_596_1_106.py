"""OpenSpec 106: native section-anchor evidence for the terms bridge."""

from __future__ import annotations

from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    NativeHierarchyNodeV1,
    NativeHierarchyProvenanceV1,
)


def test_section_anchor_contract_reads_separate_body_free_hierarchy() -> None:
    assert NativeHierarchyNodeV1.model_fields["text_level"].annotation is not None
    assert NativeHierarchyProvenanceV1.model_fields["nodes"].annotation is not None
