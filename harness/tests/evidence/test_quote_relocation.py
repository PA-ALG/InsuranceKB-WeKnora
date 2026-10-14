"""S4d acceptance: relocate a quote within the product only on a unique verbatim match.

Protected file: written by Claude. Pins §3.1 of the S4d spec.

Models cite the wrong page or file for text that exists verbatim elsewhere in
the same product. Accepting the unique location keeps the Evidence exact;
several locations are ambiguous and stay rejected, and matching is not loosened.
"""

from insurance_harness.evidence.quote_verification import (
    PageText,
    QuoteMatch,
    QuoteReference,
    QuoteVerifier,
)

TERMS, BROCHURE = "条款.pdf", "说明书.pdf"
SHA_T, SHA_B = "a" * 64, "b" * 64
VERIFIER = QuoteVerifier([
    PageText(document=TERMS, document_sha256=SHA_T, page=1, text="第一页。等待期为90日。"),
    PageText(document=TERMS, document_sha256=SHA_T, page=2, text="第二页。犹豫期为20日。"),
    PageText(document=BROCHURE, document_sha256=SHA_B, page=1, text="宽限期为60日。犹豫期为20日。"),
    PageText(document=BROCHURE, document_sha256=SHA_B, page=2, text="减保比例不超过20%。"),
])


def cite(document: str, sha: str, page: int, quote: str) -> QuoteReference:
    return QuoteReference(document=document, document_sha256=sha, page=page, quote=quote)


def test_a_correct_citation_is_unchanged() -> None:
    verified = VERIFIER.verify(cite(TERMS, SHA_T, 1, "等待期为90日"))
    assert verified is not None
    assert (verified.document, verified.page, verified.match) == (TERMS, 1, QuoteMatch.EXACT)
    assert (verified.cited_document, verified.cited_page) == (None, None)


def test_a_unique_match_on_another_page_of_the_same_file_is_relocated() -> None:
    verified = VERIFIER.verify(cite(TERMS, SHA_T, 2, "等待期为90日"))
    assert verified is not None
    assert (verified.document, verified.document_sha256, verified.page) == (TERMS, SHA_T, 1)
    assert (verified.cited_document, verified.cited_page) == (TERMS, 2)


def test_a_unique_match_in_another_file_of_the_product_is_relocated() -> None:
    verified = VERIFIER.verify(cite(TERMS, SHA_T, 1, "宽限期为60日"))
    assert verified is not None
    assert (verified.document, verified.document_sha256, verified.page) == (BROCHURE, SHA_B, 1)
    assert (verified.cited_document, verified.cited_page) == (TERMS, 1)


def test_a_citation_to_a_missing_page_can_still_be_relocated() -> None:
    verified = VERIFIER.verify(cite(TERMS, SHA_T, 9, "减保比例不超过20%"))
    assert verified is not None
    assert (verified.document, verified.page, verified.cited_page) == (BROCHURE, 2, 9)


def test_relocation_keeps_the_normalized_match_kind() -> None:
    verified = VERIFIER.verify(cite(TERMS, SHA_T, 2, "等待期 为 90日"))
    assert verified is not None
    assert (verified.page, verified.match) == (1, QuoteMatch.NORMALIZED)


def test_several_matches_are_ambiguous_and_rejected() -> None:
    assert VERIFIER.verify(cite(TERMS, SHA_T, 1, "犹豫期为20日")) is None


def test_relocation_does_not_loosen_matching() -> None:
    assert VERIFIER.verify(cite(TERMS, SHA_T, 1, "等待期为60日")) is None
    assert VERIFIER.verify(cite(TERMS, SHA_T, 1, "等待期为90日。犹豫期")) is None
