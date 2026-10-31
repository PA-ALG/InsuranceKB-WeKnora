"""Local-live CLI: frozen phase dispatch, VLM evidence, retry markers and safe down."""

from __future__ import annotations

from importlib import import_module
from io import StringIO
from pathlib import Path

import pytest

from tests.service_shell.local_live_cli.helpers import PhaseRequestLike, ResolvedLocks, _module

PHASES = (
    "check",
    "probe-models",
    "up",
    "provision",
    "verify",
    "smoke-vlm",
    "retry-vlm",
    "run-local",
    "down",
)


@pytest.mark.parametrize("phase", PHASES)
def test_r5_1_cli_dispatches_each_frozen_phase_through_injected_adapter(
    phase: str,
) -> None:
    module = _module()
    requests: list[PhaseRequestLike] = []

    class Adapter:
        def run(self, request: PhaseRequestLike) -> object:
            requests.append(request)
            return {
                "status": (
                    "completed"
                    if request.phase in {"smoke-vlm", "retry-vlm"}
                    else "ok"
                ),
                "phase": request.phase,
            }

    output = StringIO()
    arguments = [phase]
    if phase == "retry-vlm":
        arguments.extend(("--knowledge-id", "vlm-knowledge-1"))
    assert (
        module.main(
            arguments, adapter=Adapter(), lock_verifier=ResolvedLocks(), output=output
        )
        == 0
    )
    assert len(requests) == 1
    assert requests[0].phase == phase
    assert requests[0].delete_volumes is False
    assert requests[0].knowledge_id == (
        "vlm-knowledge-1" if phase == "retry-vlm" else None
    )
    expected_status = "completed" if phase in {"smoke-vlm", "retry-vlm"} else "ok"
    assert f'"status": "{expected_status}"' in output.getvalue()


@pytest.mark.parametrize("phase", ("smoke-vlm", "retry-vlm"))
@pytest.mark.parametrize(
    "status", ("failed", "cancelled", "incomplete", "pending", "processing")
)
def test_r3_3_vlm_cli_preserves_noncompleted_evidence_but_exits_nonzero(
    phase: str,
    status: str,
) -> None:
    module = _module()

    class Adapter:
        def run(self, request: PhaseRequestLike) -> object:
            return {
                "status": status,
                "knowledge_id": request.knowledge_id or "vlm-knowledge-1",
                "attempt": 1,
            }

    output = StringIO()
    error = StringIO()
    arguments = [phase]
    if phase == "retry-vlm":
        arguments.extend(("--knowledge-id", "vlm-knowledge-1"))

    assert module.main(
        arguments,
        adapter=Adapter(),
        lock_verifier=ResolvedLocks(),
        output=output,
        error=error,
    ) == 1
    assert f'"status": "{status}"' in output.getvalue()
    assert "did not complete" in error.getvalue()


def test_r3_3_retry_marker_permission_error_is_not_reported_as_consumed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = import_module("insurance_harness.live_env.local_provisioning")
    collaborator = module.VLMSmokeCollaborator(
        runtime_path=tmp_path / ".env.local-live.runtime"
    )

    def deny_marker(*args: object, **kwargs: object) -> int:
        del args, kwargs
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(module.os, "open", deny_marker)

    with pytest.raises(RuntimeError, match="could not be persisted"):
        collaborator._consume_retry("vlm-knowledge-1")


def test_r5_2_down_is_non_destructive_without_explicit_volume_confirmation() -> None:
    module = _module()
    requests: list[PhaseRequestLike] = []

    class Adapter:
        def run(self, request: PhaseRequestLike) -> object:
            requests.append(request)
            return {"status": "stopped"}

    assert module.main(
        ["down"], adapter=Adapter(), lock_verifier=ResolvedLocks(), output=StringIO()
    ) == 0
    assert requests[0].delete_volumes is False

    error = StringIO()
    assert module.main(
        ["down", "--delete-volumes"],
        adapter=Adapter(),
        lock_verifier=ResolvedLocks(),
        output=StringIO(),
        error=error,
    ) == 2
    assert len(requests) == 1
    assert "explicit confirmation required" in error.getvalue()

    assert module.main(
        ["down", "--delete-volumes", "--confirm-delete-volumes"],
        adapter=Adapter(),
        lock_verifier=ResolvedLocks(),
        output=StringIO(),
    ) == 0
    assert requests[-1].delete_volumes is True
