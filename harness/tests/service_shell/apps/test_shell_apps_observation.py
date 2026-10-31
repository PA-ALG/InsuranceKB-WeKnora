"""服务壳（039 T7）：Space / 全局观测路由的授权与 P1 指标映射。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from insurance_harness.jobs import GlobalJobMetrics, SpaceJobMetrics
from insurance_harness.service_shell.apps import (
    ObservationQueries,
    create_api_app,
)
from insurance_harness.service_shell.principal import (
    StaticPrincipalProvider,
)
from tests.service_shell.apps.helpers import _health, _state_counts


def _provider() -> StaticPrincipalProvider:
    return StaticPrincipalProvider(
        {
            "admin": {
                "kind": "human",
                "subject_id": "admin-user",
                "bindings": {"space-a": ["space_admin"]},
            },
            "other-admin": {
                "kind": "human",
                "subject_id": "other-user",
                "bindings": {"space-b": ["space_admin"]},
            },
            "viewer": {
                "kind": "human",
                "subject_id": "viewer-user",
                "bindings": {"space-a": ["viewer"]},
            },
            "super": {
                "kind": "human",
                "subject_id": "super-user",
                "bindings": {"*": ["super_admin"]},
            },
            "service": {
                "kind": "service",
                "service": "source_reader",
                "space_ids": ["space-a"],
                "capabilities": ["read_raw_knowledge"],
            },
        },
        known_space_ids=frozenset({"space-a", "space-b", "*"}),
    )


def _observed_app() -> tuple[FastAPI, list[str]]:
    lifecycle, readiness = _health()
    calls: list[str] = []

    def read_space(space_id: str) -> SpaceJobMetrics:
        calls.append(f"space:{space_id}")
        return SpaceJobMetrics(
            space_id=space_id,
            state_counts=_state_counts(queued=3, retry_wait=1, dead_letter=2),
            queue_depth=3,
            retry_wait_count=1,
            dead_letter_count=2,
            attempt_total=7,
            oldest_schedulable_age_seconds=12.5,
            expired_lease_count=1,
            oldest_expired_lease_age_seconds=4.5,
        )

    def read_global() -> GlobalJobMetrics:
        calls.append("global")
        return GlobalJobMetrics(
            state_counts=_state_counts(queued=4, retry_wait=1, dead_letter=2),
            queue_depth=4,
            retry_wait_count=1,
            dead_letter_count=2,
            attempt_total=8,
            oldest_schedulable_age_seconds=15.0,
            expired_lease_count=1,
            oldest_expired_lease_age_seconds=5.0,
        )

    return (
        create_api_app(
            lifecycle=lifecycle,
            readiness=readiness,
            principal_provider=_provider(),
            observations=ObservationQueries(
                read_space=read_space,
                read_global=read_global,
            ),
        ),
        calls,
    )


def test_t7_space_observation_requires_admin_binding_and_maps_p1_metrics() -> None:
    app, calls = _observed_app()
    client = TestClient(app)
    response = client.get(
        "/observations/spaces/space-a/jobs",
        headers={"Authorization": "Bearer admin"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "space_id": "space-a",
        "state_counts": {
            "queued": 3,
            "leased": 0,
            "running": 0,
            "succeeded": 0,
            "retry_wait": 1,
            "awaiting_human": 0,
            "blocked": 0,
            "dead_letter": 2,
        },
        "queue_depth": 3,
        "retry_wait_count": 1,
        "dead_letter_count": 2,
        "attempt_total": 7,
        "oldest_schedulable_age_seconds": 12.5,
        "expired_lease_count": 1,
        "oldest_expired_lease_age_seconds": 4.5,
    }
    assert calls == ["space:space-a"]
    assert "payload" not in response.text
    assert "secret" not in response.text


def test_t7_space_observation_authorization_matrix_fails_before_query() -> None:
    app, calls = _observed_app()
    client = TestClient(app)
    attempts = [
        ({}, 401),
        ({"Authorization": "Bearer viewer"}, 403),
        ({"Authorization": "Bearer service"}, 403),
        ({"Authorization": "Bearer other-admin"}, 403),
        ({"Authorization": "Bearer unknown"}, 401),
    ]
    for headers, expected_status in attempts:
        response = client.get("/observations/spaces/space-a/jobs", headers=headers)
        assert response.status_code == expected_status
        assert set(response.json()) == {"error"}
    assert calls == []


def test_t7_global_observation_is_an_explicit_super_admin_only_route() -> None:
    app, calls = _observed_app()
    client = TestClient(app)
    for credential in ("admin", "viewer", "service"):
        response = client.get(
            "/observations/jobs",
            headers={"Authorization": f"Bearer {credential}"},
        )
        assert response.status_code == 403
        assert set(response.json()) == {"error"}
    assert calls == []

    response = client.get(
        "/observations/jobs",
        headers={"Authorization": "Bearer super"},
    )
    assert response.status_code == 200
    assert response.json()["queue_depth"] == 4
    assert "space_id" not in response.json()
    assert calls == ["global"]


def test_t7_draining_refuses_new_observation_before_handler() -> None:
    app, calls = _observed_app()
    app.state.lifecycle.begin_drain()
    response = TestClient(app).get(
        "/observations/spaces/space-a/jobs",
        headers={"Authorization": "Bearer admin"},
    )
    assert response.status_code == 503
    assert response.json() == {"error": "draining"}
    assert calls == []
