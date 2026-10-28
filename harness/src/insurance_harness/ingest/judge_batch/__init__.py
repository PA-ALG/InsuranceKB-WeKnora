"""Model-judge batches: compile changes → independent judge → machine publication (RV7 Spec).

`prepare` writes hash-checked judge requests (read-only on the platform), `ingest` reads the
answers back all-or-none, `publish_batch` publishes approved points as machine review (dry run by
default), and `close_points` closes a human-queue candidate's leftovers through the RV6d route.
Starting the judge sessions themselves is an operator step (`run.sh`).
"""

from insurance_harness.ingest.judge_batch.closing import close_points
from insurance_harness.ingest.judge_batch.points import JudgeBatchError
from insurance_harness.ingest.judge_batch.publishing import publish_batch
from insurance_harness.ingest.judge_batch.sessions import prepare
from insurance_harness.ingest.judge_batch.verdicts import ingest

__all__ = ["JudgeBatchError", "close_points", "ingest", "prepare", "publish_batch"]
