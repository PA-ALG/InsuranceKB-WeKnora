"""Role-specific FastAPI surfaces for OpenSpec 039."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from insurance_harness.jobs import GlobalJobMetrics, JobState, SpaceJobMetrics
from insurance_harness.service_shell.health import (
    Lifecycle,
    ProcessState,
    ReadinessChecker,
    liveness,
)
from insurance_harness.service_shell.principal import (
    AuthenticationError,
    AuthorizationError,
    HumanRole,
    Principal,
    StaticPrincipalProvider,
    require_space_role,
    require_super_admin,
)


@dataclass(frozen=True, slots=True)
class ObservationQueries:
    """Injected P1.9 read surface; no task payload or write method is reachable."""

    read_space: Callable[[str], SpaceJobMetrics]
    read_global: Callable[[], GlobalJobMetrics]


def _authenticated_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    provider: StaticPrincipalProvider = request.app.state.principal_provider
    if authorization is None:
        return provider.authenticate(None)
    scheme, separator, credential = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not credential:
        raise AuthenticationError("invalid_credential")
    return provider.authenticate(credential)


PrincipalDependency = Annotated[Principal, Depends(_authenticated_principal)]


def _add_probes(
    app: FastAPI,
    *,
    lifecycle: Lifecycle,
    readiness: ReadinessChecker,
) -> None:
    @app.get("/livez")
    def live() -> JSONResponse:
        result = liveness(lifecycle)
        return JSONResponse(
            status_code=200 if result.ok else 503,
            content=result.model_dump(),
        )

    @app.get("/readyz")
    def ready() -> JSONResponse:
        result = readiness.check()
        return JSONResponse(
            status_code=200 if result.ok else 503,
            content=result.model_dump(),
        )


def create_api_app(
    *,
    lifecycle: Lifecycle,
    readiness: ReadinessChecker,
    principal_provider: StaticPrincipalProvider | None = None,
    observations: ObservationQueries | None = None,
) -> FastAPI:
    """Create one API role instance; no Worker claim loop is reachable here."""
    app = FastAPI(
        title="LLM Wiki API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.role = "api"
    app.state.lifecycle = lifecycle
    _add_probes(app, lifecycle=lifecycle, readiness=readiness)

    @app.middleware("http")
    async def refuse_new_work_while_draining(
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Any:
        if (
            lifecycle.state is ProcessState.DRAINING
            and request.url.path not in {"/livez", "/readyz"}
        ):
            return JSONResponse(status_code=503, content={"error": "draining"})
        return await call_next(request)

    if principal_provider is not None and observations is not None:
        app.state.principal_provider = principal_provider

        @app.exception_handler(AuthenticationError)
        def authentication_failure(
            _request: Request,
            error: AuthenticationError,
        ) -> JSONResponse:
            return JSONResponse(status_code=401, content={"error": error.code})

        @app.exception_handler(AuthorizationError)
        def authorization_failure(
            _request: Request,
            error: AuthorizationError,
        ) -> JSONResponse:
            return JSONResponse(status_code=403, content={"error": error.code})

        @app.get("/observations/spaces/{space_id}/jobs")
        def space_observations(
            space_id: str,
            principal: PrincipalDependency,
        ) -> dict[str, Any]:
            require_space_role(
                principal,
                space_id=space_id,
                allowed_roles=frozenset({HumanRole.SPACE_ADMIN}),
            )
            return _metrics_payload(observations.read_space(space_id))

        @app.get("/observations/jobs")
        def global_observations(
            principal: PrincipalDependency,
        ) -> dict[str, Any]:
            require_super_admin(principal)
            return _metrics_payload(observations.read_global())
    return app


def create_worker_probe_app(
    *,
    lifecycle: Lifecycle,
    readiness: ReadinessChecker,
) -> FastAPI:
    """Create the Worker role's probe-only HTTP surface."""
    app = FastAPI(
        title="LLM Wiki Worker Probes",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.role = "worker"
    app.state.lifecycle = lifecycle
    _add_probes(app, lifecycle=lifecycle, readiness=readiness)
    return app


def _metrics_payload(metrics: SpaceJobMetrics | GlobalJobMetrics) -> dict[str, Any]:
    """Allow-list the aggregate P1.9 fields; task detail and secrets are impossible."""
    payload: dict[str, Any] = {
        "state_counts": {
            state.value: int(metrics.state_counts.get(state, 0)) for state in JobState
        },
        "queue_depth": metrics.queue_depth,
        "retry_wait_count": metrics.retry_wait_count,
        "dead_letter_count": metrics.dead_letter_count,
        "attempt_total": metrics.attempt_total,
        "oldest_schedulable_age_seconds": metrics.oldest_schedulable_age_seconds,
        "expired_lease_count": metrics.expired_lease_count,
        "oldest_expired_lease_age_seconds": metrics.oldest_expired_lease_age_seconds,
    }
    if isinstance(metrics, SpaceJobMetrics):
        payload = {"space_id": metrics.space_id, **payload}
    return payload
