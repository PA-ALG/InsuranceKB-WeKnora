"""S12c-12a RED: actual RV7 saved requests carry the compile's roles and shared rules."""

import json
from typing import Any

from insurance_harness.eval.judge_files import stored_requests
from tests.compilers.schema_fields.test_publish_cli import SHA
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_judge_batch import prepared
from tests.ingest.test_judge_batch import world as world  # noqa: F401


def test_prepare_transports_recorded_roles_not_file_name_guesses(world: dict[str, Any]) -> None:
    output = world["compile_root"] / "1828/output.json"
    data = json.loads(output.read_text())
    # The compile's exact revision/hash identity is already verified by prepare/rebuild.
    data["materials"] = [f"k-1:2:{SHA}"]
    data["material_roles"] = {identity: "terms" for identity in data["materials"]}
    output.write_text(json.dumps(data))
    prepared(world)
    request = stored_requests(world["run_root"] / "sessions/s01")[0]
    payload = json.loads(request.user)
    assert payload["materials"] and all(m["role"] == "terms" for m in payload["materials"])
    for point in payload["points"]:
        assert "每条事实只归入一个字段" in point["card"]["authority"]
        assert "条款没有涉及的事项" in point["card"]["source_priority"]
        assert "examples" not in point["card"]


def test_unknown_old_role_is_explicit_and_not_inferred(world: dict[str, Any]) -> None:
    output = world["compile_root"] / "1828/output.json"
    data = json.loads(output.read_text())
    data["material_roles"] = None
    output.write_text(json.dumps(data))
    prepared(world)
    payload = json.loads(stored_requests(world["run_root"] / "sessions/s01")[0].user)
    assert all("role" in m and m["role"] is None for m in payload["materials"])
