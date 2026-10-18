"""Shared S3e-3 test data: a small release with three products and two concepts (protected)."""

from __future__ import annotations

from typing import Any

import pytest

from insurance_harness.bundle.client import Release, ReleaseMember


def member(kind: str, slug: str, payload: dict[str, Any], digest: str = "d" * 64) -> ReleaseMember:
    return ReleaseMember(kind=kind, logical_slug=slug, member_digest=digest, payload=payload)


def claim(
    subject: str, predicate: str, state: str, value: str | None, digest: str
) -> ReleaseMember:
    return member(
        "claim",
        f"{subject}/{predicate}",
        {"subject_ref": subject, "predicate": predicate, "state": state, "value": value,
         "origin": "SOURCE_SUPPORTED", "evidence": [{"quote": "原文"}]},
        digest,
    )  # fmt: skip


def entity(entity_id: str, name: str, label: str) -> ReleaseMember:
    return member(
        "entity",
        f"entity/{entity_id}",
        {"entity_id": entity_id, "entity_type": "insurance_product", "names": [name],
         "classification_labels": [label]},
    )  # fmt: skip


def profile(profile_id: str, display_name: str, label: str) -> ReleaseMember:
    fields = [
        {"field_key": "cooling_off_period", "short_title": "犹豫期",
         "description": "投保人收到合同后可解除合同的期间；只允许从正式条款中抽取。",
         "schema_category": "05 合同与交费规则"},
        {"field_key": "waiting_period", "short_title": "等待期", "description": "不赔付的期间。",
         "schema_category": "06 保障责任"},
        {"field_key": "premium_grace_period", "short_title": "宽限期",
         "description": "仍有效的期间。",
         "schema_category": "05 合同与交费规则"},
    ]  # fmt: skip
    return member(
        "presentation_profile",
        f"presentation/{profile_id}",
        {"profile_id": profile_id, "display_name": display_name, "classification_labels": [label],
         "sections": [{"section_key": "s", "display_name": "合同", "fields": fields}]},
    )  # fmt: skip


@pytest.fixture
def release() -> Release:
    return Release(
        id="rel-9",
        epoch=15,
        members=[
            profile("profile_medical", "医疗险", "medical"),
            profile("profile_critical", "重疾险", "critical"),
            entity("P1", "甲产品", "medical"),
            entity("P2", "乙产品", "medical"),
            entity("P3", "丙产品", "critical"),
            claim("P1", "cooling_off_period", "present", "自签收本合同之日起15日。", "a" * 64),
            claim("P2", "cooling_off_period", "present", "15日，期间退还全部保费。", "b" * 64),
            claim("P3", "cooling_off_period", "present", "自签收本合同之日起２０日。", "c" * 64),
            claim("P1", "waiting_period", "present", "90日。", "e" * 64),
            claim("P2", "waiting_period", "unknown", None, "f" * 64),
            claim("P1", "premium_grace_period", "present", "60日。", "1" * 64),
            claim("P3", "premium_grace_period", "absent_explicitly", None, "2" * 64),
        ],
    )
