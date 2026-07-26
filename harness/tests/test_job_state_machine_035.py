"""OpenSpec 035 T1：P1.1/P1.4 状态机纯函数核与 DTO/配置校验（deterministic）。"""

from __future__ import annotations

import dataclasses
from itertools import product

import pytest
from pydantic import ValidationError

from insurance_harness.jobs import (
    LEGAL_TRANSITIONS,
    STORAGE_ONLY_TRANSITIONS,
    TERMINAL_STATES,
    CapacityBlockedJobError,
    ErrorClass,
    HumanRequiredJobError,
    IllegalTransitionError,
    JobFailure,
    JobRuntimeConfig,
    JobState,
    JobTypePolicy,
    NonRetryableJobError,
    RetryableJobError,
    classify_failure,
    ensure_transition,
    route_failure,
)

S = JobState


def _config(**overrides: object) -> JobRuntimeConfig:
    values: dict[str, object] = {
        "lease_seconds": 60.0,
        "heartbeat_interval_seconds": 20.0,
        "max_attempts": 3,
        "backoff_seconds": (1.0, 5.0),
        "per_space_concurrency_limit": 2,
        "global_concurrency_limit": 8,
    }
    values.update(overrides)
    return JobRuntimeConfig.model_validate(values)


# --- P1.1 封闭枚举与合法转换表 ---


def test_p1_1_job_state_is_a_closed_eight_state_enum() -> None:
    assert {state.value for state in JobState} == {
        "queued",
        "leased",
        "running",
        "succeeded",
        "retry_wait",
        "awaiting_human",
        "blocked",
        "dead_letter",
    }
    assert TERMINAL_STATES == frozenset({S.SUCCEEDED, S.BLOCKED, S.DEAD_LETTER})


def test_p1_4_error_class_is_a_closed_four_value_enum() -> None:
    assert {klass.value for klass in ErrorClass} == {
        "retryable",
        "non_retryable",
        "capacity_blocked",
        "human_required",
    }


def test_p1_1_legal_transition_table_is_exactly_the_spec_list() -> None:
    assert LEGAL_TRANSITIONS == frozenset(
        {
            (S.QUEUED, S.LEASED),
            (S.LEASED, S.RUNNING),
            (S.RUNNING, S.SUCCEEDED),
            (S.RUNNING, S.RETRY_WAIT),
            (S.RETRY_WAIT, S.QUEUED),
            (S.RUNNING, S.AWAITING_HUMAN),
            (S.AWAITING_HUMAN, S.QUEUED),
            (S.RUNNING, S.BLOCKED),
            (S.RUNNING, S.DEAD_LETTER),
            (S.LEASED, S.QUEUED),
            (S.LEASED, S.DEAD_LETTER),
            (S.RUNNING, S.QUEUED),
        }
    )


def test_p1_1_storage_only_transitions_cover_backoff_and_lease_reclaim() -> None:
    assert STORAGE_ONLY_TRANSITIONS == frozenset(
        {
            (S.RETRY_WAIT, S.QUEUED),
            (S.LEASED, S.QUEUED),
            (S.LEASED, S.DEAD_LETTER),
            (S.RUNNING, S.QUEUED),
        }
    )
    assert STORAGE_ONLY_TRANSITIONS <= LEGAL_TRANSITIONS


def test_p1_1_exhaustive_pairs_split_between_legal_and_typed_illegal() -> None:
    for source, target in product(JobState, JobState):
        if (source, target) in LEGAL_TRANSITIONS:
            ensure_transition(source, target)
            continue
        with pytest.raises(IllegalTransitionError) as excinfo:
            ensure_transition(source, target)
        assert excinfo.value.code == "illegal_transition"
        assert excinfo.value.source is source
        assert excinfo.value.target is target


def test_p1_1_terminal_states_have_no_outgoing_edges() -> None:
    for source, target in LEGAL_TRANSITIONS:
        assert source not in TERMINAL_STATES
        assert isinstance(target, JobState)


# --- P1.4 错误分类 → 目标状态映射 ---


@pytest.mark.parametrize(
    ("error_class", "attempt", "expected"),
    [
        (ErrorClass.RETRYABLE, 1, S.RETRY_WAIT),
        (ErrorClass.RETRYABLE, 2, S.RETRY_WAIT),
        (ErrorClass.RETRYABLE, 3, S.DEAD_LETTER),
        (ErrorClass.RETRYABLE, 4, S.DEAD_LETTER),
        (ErrorClass.NON_RETRYABLE, 1, S.DEAD_LETTER),
        (ErrorClass.CAPACITY_BLOCKED, 1, S.BLOCKED),
        (ErrorClass.HUMAN_REQUIRED, 1, S.AWAITING_HUMAN),
    ],
)
def test_p1_4_route_failure_is_deterministic(
    error_class: ErrorClass, attempt: int, expected: JobState
) -> None:
    assert route_failure(error_class, attempt=attempt, max_attempts=3) is expected


def test_p1_4_typed_job_errors_classify_to_their_declared_class() -> None:
    cases: list[tuple[Exception, ErrorClass]] = [
        (RetryableJobError("provider timeout"), ErrorClass.RETRYABLE),
        (NonRetryableJobError("schema violation"), ErrorClass.NON_RETRYABLE),
        (
            CapacityBlockedJobError("candidate_capacity_exceeded"),
            ErrorClass.CAPACITY_BLOCKED,
        ),
        (HumanRequiredJobError("needs review"), ErrorClass.HUMAN_REQUIRED),
    ]
    for error, expected in cases:
        failure = classify_failure(error)
        assert failure.error_class is expected
        assert str(error) in failure.summary


def test_p1_4_unclassified_exception_becomes_retryable_and_keeps_summary() -> None:
    failure = classify_failure(ValueError("boom-035"))

    assert failure.error_class is ErrorClass.RETRYABLE
    assert "boom-035" in failure.summary
    assert "ValueError" in failure.summary


def test_job_failure_dto_is_frozen() -> None:
    failure = JobFailure(error_class=ErrorClass.RETRYABLE, summary="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        failure.summary = "y"  # type: ignore[misc]


# --- 配置 DTO：全部值来自配置，非法值 fail closed ---


def test_config_rejects_non_positive_or_empty_values() -> None:
    with pytest.raises(ValidationError):
        _config(max_attempts=0)
    with pytest.raises(ValidationError):
        _config(backoff_seconds=())
    with pytest.raises(ValidationError):
        _config(lease_seconds=-1.0)
    with pytest.raises(ValidationError):
        _config(per_space_concurrency_limit=0)
    with pytest.raises(ValidationError):
        _config(global_concurrency_limit=0)
    with pytest.raises(ValidationError):
        _config(backoff_seconds=(1.0, -2.0))


def test_config_is_frozen_and_policy_lookup_prefers_job_type_override() -> None:
    config = _config(
        job_type_policies={
            "compile": JobTypePolicy(max_attempts=5, backoff_seconds=(10.0, 60.0))
        }
    )

    with pytest.raises(ValidationError):
        config.max_attempts = 9  # pydantic frozen：运行时 ValidationError

    default_policy = config.policy_for("extract")
    assert default_policy.max_attempts == 3
    assert default_policy.backoff_seconds == (1.0, 5.0)

    override = config.policy_for("compile")
    assert override.max_attempts == 5
    assert override.backoff_seconds == (10.0, 60.0)


def test_config_backoff_delay_clamps_to_last_configured_step() -> None:
    policy = JobTypePolicy(max_attempts=9, backoff_seconds=(1.0, 5.0))

    assert policy.backoff_delay(attempt=1) == 1.0
    assert policy.backoff_delay(attempt=2) == 5.0
    assert policy.backoff_delay(attempt=7) == 5.0
    with pytest.raises(ValueError):
        policy.backoff_delay(attempt=0)


# --- 配置接线：HarnessSettings（HARNESS_ 环境前缀）→ JobRuntimeConfig ---


def test_settings_wire_job_runtime_config_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.config import HarnessSettings

    monkeypatch.setenv("HARNESS_JOB_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("HARNESS_JOB_BACKOFF_SECONDS", "[2.0, 8.0]")
    settings = HarnessSettings(
        weknora_base_url="http://weknora.test",
        weknora_api_key="sk-test",
        job_lease_seconds=45.0,
        job_per_space_concurrency_limit=3,
    )

    config = settings.job_runtime_config()

    assert isinstance(config, JobRuntimeConfig)
    assert config.lease_seconds == 45.0
    assert config.max_attempts == 5
    assert config.backoff_seconds == (2.0, 8.0)
    assert config.per_space_concurrency_limit == 3
    assert config.global_concurrency_limit >= 1
    assert config.heartbeat_interval_seconds > 0
    assert config.policy_for("anything").max_attempts == 5
