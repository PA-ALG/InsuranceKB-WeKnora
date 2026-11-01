"""PV-3 acceptance addition (written by Claude): a shared clause code can be asked, only ignored.

PV-0 appendix A §1.3 row 3: a clause code several filed versions share is quarantined and never
merged or created until the internal-ID rule can tell those versions apart. Pushing such an item
must still produce a valid question: it names the shared code and the versions sharing it (from the
pinned catalog), says why it cannot be attached yet, and offers ignoring only; a person's ignore is
recorded as a human decision.
"""

from insurance_harness.identity.attribution import attribute
from insurance_harness.identity.confirmation import conclude
from insurance_harness.ingest.confirmation_questions import question_of
from insurance_harness.ingest.raw_sources import RawSource
from insurance_harness.ingest.registry import ConfirmationRef, PendingEntry, record
from tests.identity.test_attribution_versions import CODE, TERMS
from tests.ingest.test_version_questions import v2
from tests.ingest.version_helpers import catalog, of

SHARED = catalog(of("1828", key="1828-1"), of("1828", key="1828-2"))


def asked() -> PendingEntry:
    result = attribute(TERMS, [], catalog=SHARED)
    assert (result.outcome, result.reason) == ("QUARANTINE", "shared_clause_code")
    assert result.shared_versions == ("1828-1", "1828-2")
    return PendingEntry(
        knowledge_id=TERMS.knowledge_id,
        parse_attempt=1,
        sha256=TERMS.sha256,
        file_name=TERMS.file_name,
        attribution=result,
    )


def test_a_shared_clause_code_is_a_valid_question_with_only_ignoring() -> None:
    current = v2(0)
    question = question_of(asked(), current, head=TERMS.head)
    assert [option.key for option in question.options] == ["ignore"]
    assert CODE in question.detail
    assert "1828-1" in question.detail and "1828-2" in question.detail


def test_ignoring_it_is_recorded_as_a_persons_decision() -> None:
    current = v2(0)
    pending = asked()
    current.pending = [pending]
    conclusion = conclude(pending.attribution, "ignore", TERMS, current.registered())
    assert (conclusion.outcome, conclusion.reason) == ("IGNORED", "confirmed_ignore")
    source = RawSource(
        knowledge_id=TERMS.knowledge_id,
        parse_attempt=1,
        file_name=TERMS.file_name,
        sha256=TERMS.sha256,
    )
    answer = ConfirmationRef(
        item_id="item-shared", answer_id="answer-shared", option_key="ignore", answerer="reviewer"
    )
    record(current, source, conclusion, answer)
    decision = current.decisions[-1]
    assert (decision.attribution.outcome, decision.confirmation) == ("IGNORED", answer)
    assert current.pending == []
