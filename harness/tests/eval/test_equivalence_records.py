"""Per-field exchange records retain reasons even when the verdict is equivalent."""

import json

from insurance_harness.eval.equivalence import (
    EquivalenceQuestion,
    read_equivalence_verdicts,
)
from insurance_harness.eval.judge import JudgeRequest


class Answers:
    model_id = "fake"

    def complete(self, request: JudgeRequest) -> str:
        return json.dumps({"fields": [
            {"field_key": row["field_key"], "verdict": "equivalent", "reason": "同一核心事实"}
            for row in json.loads(request.user)["fields"]
        ]})


def test_equivalent_records_keep_reasons_across_batches() -> None:
    questions = [EquivalenceQuestion(field_key=key, reference="事实", judged="同义事实")
                 for key in ("a", "b")]
    records = read_equivalence_verdicts(Answers(), questions, max_calls=2, batch_size=1)
    assert [(r.field_key, r.verdict, r.reason) for r in records] == [
        ("a", "equivalent", "同一核心事实"), ("b", "equivalent", "同一核心事实"),
    ]
