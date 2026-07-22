"""P3：文档分类——确定性优先、冲突处理、unknown 不猜测、LLM 兜底。"""

from pathlib import Path

import pytest

from insurance_harness.goldenset.annotator import ReplayClient, request_key
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.product.classify import (
    _LLM_SYSTEM,
    Classification,
    ClassificationModelBoundaryError,
    DocumentType,
    classify_document,
    detect_product_line,
)

TERMS_PAGE = PageText(
    page_no=1,
    text="平安人寿〔2026〕年金保险013号\n平安盛世金越养老年金保险（分红型）\n阅读指引\n……条款……",
)
BROCHURE_PAGE = PageText(page_no=1, text="平安盛世金越养老年金保险（分红型）产品说明书\n重要提示……")
RATE_PAGE = PageText(
    page_no=1, text="《平安盛世金越》基本保险金额表\n（每万元趸交或年交保费）\n投保年龄……"
)
PLAIN_PAGE = PageText(page_no=1, text="这是一段没有任何特征的文本。")


async def test_p3_1_terms_high_confidence() -> None:
    cls = await classify_document("保险条款.pdf", [TERMS_PAGE])
    assert cls.doc_type is DocumentType.TERMS
    assert cls.confidence == "high"
    assert not cls.used_llm
    assert cls.product_line == "annuity"


async def test_p3_1_brochure_and_rate() -> None:
    assert (await classify_document("产品说明书.pdf", [BROCHURE_PAGE])).doc_type is (
        DocumentType.BROCHURE
    )
    assert (await classify_document("费率表.pdf", [RATE_PAGE])).doc_type is DocumentType.RATE_TABLE


async def test_p3_conflict_prefers_content() -> None:
    cls = await classify_document("费率表.pdf", [BROCHURE_PAGE])
    assert cls.doc_type is DocumentType.BROCHURE
    assert cls.confidence == "medium"
    assert any("冲突" in b for b in cls.basis)


async def test_p3_3_unknown_without_client() -> None:
    cls = await classify_document("某文件.pdf", [PLAIN_PAGE])
    assert cls.doc_type is DocumentType.UNKNOWN
    assert not cls.used_llm


@pytest.mark.parametrize("model_profile", ["offline-eval", "replay"])
async def test_p3_llm_fallback_requires_explicit_nonproduction_profile(
    tmp_path: Path,
    model_profile: str,
) -> None:
    user = PLAIN_PAGE.text[:3000]
    fixture = tmp_path / f"{request_key(_LLM_SYSTEM, user)}.txt"
    fixture.write_text('{"doc_type": "宣传材料", "reason": "营销口吻"}', encoding="utf-8")
    cls: Classification = await classify_document(
        "某文件.pdf",
        [PLAIN_PAGE],
        model_client=ReplayClient(tmp_path),
        model_profile=model_profile,
    )
    assert cls.doc_type is DocumentType.MARKETING
    assert cls.used_llm and cls.confidence == "low"


@pytest.mark.parametrize(
    "model_profile",
    [None, "disabled", "default", "production", "unknown-profile"],
)
async def test_pwb2_raw_classification_client_without_offline_profile_is_zero_call(
    model_profile: str | None,
) -> None:
    calls: list[tuple[str, str]] = []

    class _RawClient:
        async def complete(self, system: str, user: str) -> str:
            calls.append((system, user))
            return '{"doc_type":"宣传材料","reason":"must not run"}'

    with pytest.raises(ClassificationModelBoundaryError) as denied:
        await classify_document(
            "某文件.pdf",
            [PLAIN_PAGE],
            model_client=_RawClient(),
            model_profile=model_profile,
        )

    assert denied.value.reason_code == "offline_profile_required"
    assert calls == []


def test_product_line_keyword_priority() -> None:
    assert detect_product_line("平安医疗意外保险") == "accident-medical"
    assert detect_product_line("平安e生保（惠享版）长期医疗保险") == "medical"
    assert detect_product_line("平安附加（2026）失能收入损失保险") == "disability-income"
    assert detect_product_line("平安盛世金越（尊享版26）终身寿险") == "whole-life"
