"""SK-2c Spec §3, §6.1–§6.7, §6.10 (RED, written by Claude): the method value stage on a model."""

import fcntl
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.compilers.methods.compile import compile_methods
from insurance_harness.compilers.methods.responses import SavedResponses
from insurance_harness.compilers.methods.values import ValuesStopped, method_values
from insurance_harness.ingest.registry import RegistryError
from insurance_harness.models import StageModelConfig, load_stage_config
from insurance_harness.models import __file__ as models_init
from tests.compilers.methods.helpers import (
    METHOD_A,
    METHOD_C,
    FakeModel,
    World,
    candidate,
    candidates_of,
    claims_of,
    full_answer,
    unknown_answer,
)
from tests.compilers.methods.values_helpers import (
    SERVED,
    SERVER_ERROR,
    TRUNCATED,
    Behaviour,
    FakeProvider,
    install,
    stage_config,
)
from tests.ingest.method_helpers import v1


def deck_a(world: World) -> list[dict[str, Any]]:
    return [candidate(METHOD_A, world.raw_a, world.hits("k-deck-a"))]


def both(world: World) -> list[dict[str, Any]]:
    return [*deck_a(world), candidate(METHOD_C, world.raw_c, world.hits("k-deck-c"))]


def run(
    world: World,
    items: Sequence[Mapping[str, Any]],
    root: Path,
    *,
    max_sent: int = 10,
    config: StageModelConfig | None = None,
) -> dict[str, Any]:
    return method_values(
        world.registry,
        candidates_of(world, items),
        pages=world.reader,
        root=root,
        config=config or stage_config(),
        max_sent=max_sent,
    )


def stopped(
    world: World, items: Sequence[Mapping[str, Any]], root: Path, **options: Any
) -> ValuesStopped:
    with pytest.raises(ValuesStopped) as raised:
        run(world, items, root, **options)
    return raised.value


def answers_in(root: Path) -> list[str]:
    return sorted(path.name for path in root.glob("*.txt"))


def raw_in(root: Path) -> list[str]:
    return sorted(path.name for path in (root / "raw").glob("*.txt"))


def provider(monkeypatch: pytest.MonkeyPatch, answers: Mapping[str, Behaviour], **kw: Any) -> Any:
    model = FakeProvider(answers, **kw)
    install(monkeypatch, model)
    return model


def test_saved_values_replay_into_the_same_method_as_the_in_memory_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    model = provider(monkeypatch, {METHOD_A: full_answer})
    summary = run(world, deck_a(world), tmp_path)
    assert summary["codes"] == {"answered": 1} and summary["failed"] == {}
    assert (summary["sent"], summary["sent_total"], summary["model"]) == (1, 1, SERVED)
    assert model.calls == [METHOD_A]

    # The file is named by the digest of exactly the request the compile makes (SK-2a §7).
    memory = FakeModel({METHOD_A: full_answer})
    expected = compile_methods(
        world.registry, candidates_of(world, deck_a(world)), pages=world.reader, port=memory,
        active=None,
    )
    assert answers_in(tmp_path) == [f"{memory.sent[0][0]}.txt"]
    replayed = compile_methods(
        world.registry, candidates_of(world, deck_a(world)), pages=world.reader,
        port=SavedResponses(tmp_path, summary["model"]), active=None,
    )
    got, want = claims_of(replayed.bundle), claims_of(expected.bundle)
    assert sorted(got) == sorted(want) and len(got) == 5
    for key, claim in got.items():
        assert claim.value == want[key].value and claim.evidence == want[key].evidence
        assert claim.provenance.model == SERVED
        assert claim.product_version_ref is None


def test_saved_answers_are_never_sent_and_need_no_model_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    provider(monkeypatch, {METHOD_A: full_answer})
    run(world, deck_a(world), tmp_path)
    created = install(monkeypatch, None)  # no key, no client: everything is saved
    summary = run(world, deck_a(world), tmp_path)
    assert summary["codes"] == {"saved": 1}
    assert (summary["sent"], summary["sent_total"]) == (0, 1)
    assert created == []


def test_an_altered_saved_answer_stops_before_anything_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    provider(monkeypatch, {METHOD_A: full_answer})
    run(world, deck_a(world), tmp_path)
    (saved,) = tmp_path.glob("*.txt")
    saved.write_text("not json", encoding="utf-8")
    model = provider(monkeypatch, {METHOD_C: unknown_answer})
    stop = stopped(world, both(world), tmp_path)
    assert stop.code == "RUN_ROOT_INVALID" and stop.sent == 0
    assert model.calls == []


def test_an_invalid_answer_is_kept_raw_and_asked_again_next_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    provider(monkeypatch, {})  # non-JSON text
    summary = run(world, deck_a(world), tmp_path)
    assert summary["codes"] == {"VALUE_RESPONSE_INVALID": 1}
    (method_id,) = summary["failed"]
    assert summary["failed"][method_id] == "VALUE_RESPONSE_INVALID"
    assert raw_in(tmp_path) == ["001.txt"] and answers_in(tmp_path) == []
    model = provider(monkeypatch, {METHOD_A: full_answer})
    again = run(world, deck_a(world), tmp_path)
    assert again["codes"] == {"answered": 1} and model.calls == [METHOD_A]
    assert raw_in(tmp_path) == ["001.txt", "002.txt"] and len(answers_in(tmp_path)) == 1
    assert again["sent_total"] == 2


def test_a_truncated_or_too_large_request_only_costs_its_method(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    provider(monkeypatch, {METHOD_A: TRUNCATED, METHOD_C: unknown_answer})
    summary = run(world, both(world), tmp_path / "one")
    assert summary["codes"] == {"VALUE_TRUNCATED": 1, "answered": 1}
    assert list(summary["failed"].values()) == ["VALUE_TRUNCATED"]

    model = provider(monkeypatch, {METHOD_A: full_answer, METHOD_C: unknown_answer})
    small = stage_config(max_input_chars=50)
    summary = run(world, both(world), tmp_path / "two", config=small)
    assert summary["codes"] == {"INPUT_TOO_LARGE": 2}
    assert summary["sent"] == 0 and model.calls == []


def test_the_budget_stops_the_run_counts_across_runs_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    model = provider(monkeypatch, {METHOD_A: full_answer, METHOD_C: unknown_answer})
    stop = stopped(world, both(world), tmp_path, max_sent=1)
    assert (stop.code, stop.sent, stop.sent_total) == ("BUDGET_EXCEEDED", 1, 1)
    assert len(answers_in(tmp_path)) == 1 and len(model.calls) == 1

    stop = stopped(world, both(world), tmp_path, max_sent=1)  # the cap counts the first run
    assert (stop.code, stop.sent, stop.sent_total) == ("BUDGET_EXCEEDED", 0, 1)
    assert len(model.calls) == 1

    summary = run(world, both(world), tmp_path, max_sent=2)
    assert summary["codes"] == {"answered": 1, "saved": 1}
    assert (summary["sent"], summary["sent_total"]) == (1, 2)
    assert len(model.calls) == 2 and len(answers_in(tmp_path)) == 2


def test_a_model_error_stops_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = World()
    provider(monkeypatch, {METHOD_A: SERVER_ERROR})
    stop = stopped(world, deck_a(world), tmp_path)
    assert (stop.code, stop.error) == ("MODEL_ERROR", "ModelUnavailable")
    assert answers_in(tmp_path) == []


def test_a_missing_model_key_is_a_configuration_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from insurance_harness.compilers.methods import values as values_module
    from insurance_harness.models import OpenAICompatibleCompletion

    def keyless(config: StageModelConfig, *, ledger: Any, keep: Any = None) -> Any:
        return OpenAICompatibleCompletion(config, ledger=ledger, environ={}, keep=keep)

    monkeypatch.setattr(values_module, "OpenAICompatibleCompletion", keyless)
    world = World()
    assert stopped(world, deck_a(world), tmp_path).code == "MODEL_CONFIG_INVALID"


def test_a_changed_served_model_stops_and_its_answer_is_not_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    provider(monkeypatch, {METHOD_A: full_answer})
    run(world, deck_a(world), tmp_path)
    provider(monkeypatch, {METHOD_C: unknown_answer}, served="served-model-2")
    stop = stopped(world, both(world), tmp_path)
    assert stop.code == "SERVED_MODEL_CHANGED"
    assert raw_in(tmp_path) == ["001.txt"] and len(answers_in(tmp_path)) == 1


@pytest.mark.parametrize("change", [{"model": "other-model"}, {"policy_version": "method-2"}])
def test_a_root_written_under_another_model_identity_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, str]
) -> None:
    world = World()
    provider(monkeypatch, {METHOD_A: full_answer})
    run(world, deck_a(world), tmp_path)
    model = provider(monkeypatch, {METHOD_C: unknown_answer})
    stop = stopped(world, both(world), tmp_path, config=stage_config(**change))
    assert stop.code == "RUN_ROOT_MODEL_CHANGED" and model.calls == []


def test_a_root_inside_a_git_repository_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    model = provider(monkeypatch, {METHOD_A: full_answer})
    world = World()
    assert stopped(world, deck_a(world), tmp_path / "repo" / "values").code == "RUN_ROOT_INVALID"
    assert model.calls == []


def test_a_root_in_use_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model = provider(monkeypatch, {METHOD_A: full_answer})
    world = World()
    descriptor = os.open(tmp_path / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)  # another run holds the root
        assert stopped(world, deck_a(world), tmp_path).code == "RUN_ROOT_BUSY"
    finally:
        os.close(descriptor)
    assert model.calls == []


def test_retired_methods_and_unadmitted_candidates_send_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    admitted = compile_methods(
        world.registry, candidates_of(world, deck_a(world)), pages=world.reader,
        port=FakeModel({METHOD_A: full_answer}), active=None,
    )
    world.registry = admitted.registry  # method A is registered with its link
    world.set_use("k-deck-a", state="invalidated", invalidated_reason="withdrawn")
    model = provider(monkeypatch, {METHOD_A: full_answer})
    summary = run(world, deck_a(world), tmp_path)  # the candidate is refused, the method retired
    assert (summary["methods"], summary["codes"], summary["sent"]) == (0, {}, 0)
    assert model.calls == []


def test_a_v1_registry_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = World()
    world.registry = v1()
    install(monkeypatch, None)
    with pytest.raises(RegistryError) as raised:
        run(world, [], tmp_path)
    assert raised.value.code == "REGISTRY_NOT_V2"


def test_the_repository_names_a_methods_stage_without_a_key() -> None:
    path = Path(models_init).parent / "stages.json"
    stage = load_stage_config(path, "methods")
    assert (stage.provider, stage.base_url, stage.model) == (
        "deepseek", "https://api.deepseek.com", "deepseek-flash",
    )
    assert (stage.thinking, stage.reasoning_effort) == ("enabled", "high")
    assert stage.response_format == "json_object"
    assert stage.api_key_env == "HARNESS_SCHEMA_FIELDS_API_KEY"
    assert stage.policy_version == "method-2026-11-01.1"
    assert "sk-" not in json.dumps(json.loads(path.read_text(encoding="utf-8")))
