"""Offline adaptation of RV7 fixtures: two real ingests, a fake process per fresh round.

Only execution's process/probe are replaced. Request/answer validation, session receipts,
independence, publication, platform doubles and every original assertion remain real.
"""

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

from insurance_harness.ingest.judge_batch import execution
from insurance_harness.ingest.judge_batch.dual import prepare_second
from insurance_harness.ingest.judge_batch.verdicts import ingest as real_ingest


def stage(root: Path, *, approve: bool = False) -> None:
    plan = execution.read_json(root / "plan.json")
    for session in plan["sessions"]:

        def run(
            args: list[str], session: str = session, **kwargs: Any
        ) -> subprocess.CompletedProcess[bytes]:
            target = Path(args[args.index("-C") + 1])
            original = root / "sessions" / session
            for request in sorted((original / "requests").glob("*.json")):
                source = original / "responses" / request.name
                if approve:
                    data = json.loads("\n".join(json.loads(request.read_text())["user_lines"]))
                    result = {
                        "points": [
                            dict(
                                slug=p["slug"],
                                verdict="approve",
                                category="通过",
                                reason="合成独立二评",
                            )
                            for p in data["points"]
                        ]
                    }
                    (target / "responses" / request.name).write_text(json.dumps(result))
                elif source.exists():
                    (target / "responses" / request.name).write_bytes(source.read_bytes())
            events = [
                {"type": "thread.started", "thread_id": f"synthetic-{plan['round']}-{session}"},
                {"type": "turn.completed"},
            ]
            kwargs["stdout"].write(("\n".join(json.dumps(e) for e in events) + "\n").encode())
            return subprocess.CompletedProcess(args, 0)

        with (
            patch.object(execution, "probe"),
            patch("insurance_harness.ingest.judge_batch.execution.subprocess.run", run),
        ):
            execution.execute(root, session)


def ingest(root: Path) -> dict[str, Any]:
    stage(root)
    result = real_ingest(root)
    prepare_second(root)
    stage(root / "second", approve=True)
    real_ingest(root / "second")
    return result
