"""Production composition for the durable product-ingestion worker."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

import httpx
from sqlalchemy.orm import Session

from insurance_harness.jobs import JobStore, OutboxDispatcher
from insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3 import (
    SchemaPackCatalogV1,
)
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.configuration import (
    LoadedProductBinding,
    ProductRuntimeConfiguration,
    load_product_runtime_configuration,
)
from insurance_harness.product_ingestion.model_execution import ConfiguredModelExecutor
from insurance_harness.product_ingestion.models import ProductScope
from insurance_harness.product_ingestion.platform_client import PlatformClient
from insurance_harness.product_ingestion.progression import (
    STAGES,
    PlannedWindow,
    ProductProgression,
)
from insurance_harness.product_ingestion.runtime import ProductRuntimePump, register_finalizer
from insurance_harness.product_ingestion.stages import (
    StageOutput,
    load_source_blocks,
    register_source_stages,
    register_stage_handlers,
)
from insurance_harness.product_ingestion.store import ProductIngestionStore
from insurance_harness.product_ingestion.worker import register_extraction_worker
from insurance_harness.service_shell.config import ShellConfigError, ShellSettings
from insurance_harness.service_shell.health import Lifecycle, ProcessState
from insurance_harness.service_shell.worker import HandlerRegistry, WorkerLoop

SessionFactory = Callable[[], Session]
StageExecutor = Callable[..., Awaitable[StageOutput]]
WindowPlanReader = Callable[[ProductScope, str], Sequence[PlannedWindow]]
FieldPromptProvider = Callable[[ProductScope], bytes]


def _scoped_source_loader(artifacts, services):
    gates = {space_id: asyncio.Semaphore(1) for space_id in services}

    async def sources(scope: ProductScope, run_id: str):
        service = services.get(scope.space_id)
        if service is None or service.scope != scope:
            raise ValueError("source request is outside configured product scope")
        gate = gates[scope.space_id]
        await gate.acquire()
        try:
            read = asyncio.create_task(
                load_source_blocks(
                    artifacts,
                    scope,
                    run_id,
                    public_keys=service.configuration.source_public_keys,
                )
            )
        except BaseException:
            gate.release()
            raise

        def finished(task):
            gate.release()
            # A cancelled waiter does not receive later errors from the read.
            if not task.cancelled():
                task.exception()

        read.add_done_callback(finished)
        return await asyncio.shield(read)

    return sources


_PIPELINE_STAGES = frozenset(
    {
        "identity",
        "field_plan",
        "extract",
        "synthesis",
        "compilation",
        "review",
        "publish",
        "verify",
    }
)
_EXPECTED_JOB_TYPES = frozenset(
    {f"product_stage_{stage}" for stage in STAGES if stage != "extract"}
    | {
        "product_stage_extract",
        "product_extraction_window",
        "product_ingestion_root",
    }
)


@dataclass(frozen=True, slots=True)
class ProductScopeServices:
    configuration: LoadedProductBinding
    platform: PlatformClient
    model_executor: ConfiguredModelExecutor

    @property
    def scope(self) -> ProductScope:
        return self.configuration.scope


@dataclass(frozen=True, slots=True)
class ProductCompositionContext:
    store: ProductIngestionStore
    artifacts: ProductArtifactStore
    bindings: Mapping[str, ProductScopeServices]
    catalog: SchemaPackCatalogV1 = field(repr=False)
    catalog_json: bytes = field(repr=False)
    profile_confirmation_json: bytes = field(repr=False)
    resolution_policy_json: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProductPipelinePorts:
    stage_handlers: Mapping[str, StageExecutor]
    read_window_plan: WindowPlanReader
    field_prompt: FieldPromptProvider


ProductPipelineFactory = Callable[[ProductCompositionContext], ProductPipelinePorts]


class _ScopedPlatform:
    def __init__(self, bindings: Mapping[str, ProductScopeServices]) -> None:
        self._bindings = bindings

    def _client(self, scope: ProductScope) -> PlatformClient:
        service = self._bindings.get(scope.space_id)
        if service is None or service.scope != scope:
            raise ValueError("platform request is outside configured product scope")
        return service.platform

    async def lookup_upload(self, scope: ProductScope, run_id: str, ordinal: int):
        return await self._client(scope).lookup_upload(scope, run_id, ordinal)

    async def capture_source(self, scope: ProductScope, knowledge_id: str, attempt: int) -> bytes:
        return await self._client(scope).capture_source(scope, knowledge_id, attempt)


class ProductWorkerRuntime:
    """One worker loop plus its durable progression pump and owned clients."""

    def __init__(
        self,
        *,
        worker: WorkerLoop,
        pump: ProductRuntimePump,
        registry: HandlerRegistry,
        lifecycle: Lifecycle,
        platform_clients: tuple[PlatformClient, ...],
        session_factory: SessionFactory,
    ) -> None:
        self.worker = worker
        self.pump = pump
        self.registry = registry
        self.lifecycle = lifecycle
        self.platform_clients = platform_clients
        self.session_factory = session_factory
        self._closed = False

    @property
    def issues(self):
        return self.pump.issues

    @property
    def last_worker_error(self) -> str | None:
        return self.worker.last_transient_error

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await asyncio.gather(
            *(client.close() for client in self.platform_clients),
            return_exceptions=False,
        )

    async def run(self) -> None:
        worker_task = asyncio.create_task(self.worker.run())
        pump_task = asyncio.create_task(self.pump.run(self.lifecycle))
        try:
            await asyncio.wait(
                {worker_task, pump_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if self.lifecycle.state is ProcessState.SERVING:
                self.lifecycle.begin_drain()
            results = await asyncio.gather(
                worker_task,
                pump_task,
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
        finally:
            for task in (worker_task, pump_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(worker_task, pump_task, return_exceptions=True)
            await self.close()


def _services(
    configured: ProductRuntimeConfiguration,
) -> Mapping[str, ProductScopeServices]:
    result: dict[str, ProductScopeServices] = {}
    for space_id, binding in configured.bindings.items():
        platform = binding.platform
        result[space_id] = ProductScopeServices(
            configuration=binding,
            platform=PlatformClient(
                base_url=platform.base_url,
                credential=platform.machine_key.get_secret_value(),
                scope=binding.scope,
                timeout_seconds=platform.timeout_seconds,
                max_response_bytes=platform.max_response_bytes,
                transport=httpx.AsyncHTTPTransport(retries=0),
            ),
            model_executor=ConfiguredModelExecutor(
                settings_provider=lambda binding=binding: binding.model
            ),
        )
    return MappingProxyType(result)


def _pipeline(
    factory: ProductPipelineFactory,
    context: ProductCompositionContext,
) -> ProductPipelinePorts:
    try:
        ports = factory(context)
        if type(ports) is not ProductPipelinePorts:
            raise TypeError("pipeline factory returned an invalid object")
        if set(ports.stage_handlers) != _PIPELINE_STAGES or any(
            not callable(value) for value in ports.stage_handlers.values()
        ):
            raise ValueError("pipeline stage handlers are incomplete")
        if not callable(ports.read_window_plan) or not callable(ports.field_prompt):
            raise ValueError("pipeline read and prompt ports are required")
        return ports
    except Exception as error:
        raise ShellConfigError(("product_ingestion_pipeline",)) from error


def compose_product_worker(
    *,
    settings: ShellSettings,
    lifecycle: Lifecycle,
    session_factory: SessionFactory,
    pipeline_factory: ProductPipelineFactory,
) -> ProductWorkerRuntime:
    """Build all durable product handlers or refuse enabled worker startup."""
    configured = load_product_runtime_configuration(settings)
    if configured is None:
        raise ShellConfigError(("product_ingestion_enabled",))
    if len(configured.bindings) != 1:
        # The existing source-stage decoder accepts one fixed public-key ring.
        # One exact scope per worker avoids creating a cross-scope trust union.
        raise ShellConfigError(("product_ingestion_scopes_json",))
    scope_spaces = set(configured.bindings)
    if scope_spaces != set(settings.worker_space_ids):
        raise ShellConfigError(("worker_space_ids",))
    if settings.worker_id is None:
        raise ShellConfigError(("worker_id",))

    jobs = JobStore(session_factory, settings.job_runtime_config())
    store = ProductIngestionStore(session_factory, jobs)
    artifacts = ProductArtifactStore(session_factory, store)
    services = _services(configured)
    context = ProductCompositionContext(
        store=store,
        artifacts=artifacts,
        bindings=services,
        catalog=configured.catalog,
        catalog_json=configured.catalog_json,
        profile_confirmation_json=configured.profile_confirmation_json,
        resolution_policy_json=configured.resolution_policy_json,
    )
    ports = _pipeline(pipeline_factory, context)
    try:
        prompts: dict[str, bytes] = {}
        for space_id, service in services.items():
            prompt = ports.field_prompt(service.scope)
            if type(prompt) is not bytes:
                raise ValueError("field prompt must be exact bytes")
            model = service.configuration.model
            template = model.template(model.field_template_id)
            if hashlib.sha256(prompt).hexdigest() != template.prompt_sha256:
                raise ValueError("field prompt does not match configured policy")
            prompts[space_id] = bytes(prompt)
    except Exception as error:
        raise ShellConfigError(("product_ingestion_pipeline",)) from error

    scopes = MappingProxyType({space_id: service.scope for space_id, service in services.items()})
    registry = HandlerRegistry()
    register_source_stages(
        registry,
        store=store,
        artifacts=artifacts,
        scopes=scopes,
        platform=_ScopedPlatform(services),
        public_keys=next(iter(services.values())).configuration.source_public_keys,
        catalog=configured.catalog,
    )
    register_stage_handlers(
        registry,
        store=store,
        artifacts=artifacts,
        scopes=scopes,
        handlers=ports.stage_handlers,
    )
    progression = ProductProgression(
        store=store,
        jobs=jobs,
        read_window_plan=ports.read_window_plan,
    )

    sources = _scoped_source_loader(artifacts, services)

    def transport(scope: ProductScope, run_id: str, job):
        service = services.get(scope.space_id)
        if service is None or service.scope != scope:
            raise ValueError("model request is outside configured product scope")
        return service.model_executor.field_transport(
            scope,
            run_id,
            job,
            prompt=prompts[scope.space_id],
        )

    register_extraction_worker(
        registry,
        store=store,
        scopes=scopes,
        load_sources=sources,
        transport_factory=transport,
    )
    register_finalizer(
        registry,
        store=store,
        jobs=jobs,
        progression=progression,
        scopes=scopes,
    )
    if set(registry.handlers) != _EXPECTED_JOB_TYPES:
        raise ShellConfigError(("product_ingestion_pipeline",))
    worker = WorkerLoop(
        store=jobs,
        registry=registry,
        settings=settings,
        lifecycle=lifecycle,
        worker_id=settings.worker_id,
    )
    pump_settings = configured.settings.pump
    pump = ProductRuntimePump(
        store=store,
        jobs=jobs,
        outbox=OutboxDispatcher(session_factory, settings.job_runtime_config()),
        progression=progression,
        scopes=scopes,
        page_size=pump_settings.page_size,
        event_limit=pump_settings.event_limit,
        poll_interval_seconds=pump_settings.poll_interval_seconds,
    )
    return ProductWorkerRuntime(
        worker=worker,
        pump=pump,
        registry=registry,
        lifecycle=lifecycle,
        platform_clients=tuple(service.platform for service in services.values()),
        session_factory=session_factory,
    )


__all__ = [
    "ProductCompositionContext",
    "ProductPipelineFactory",
    "ProductPipelinePorts",
    "ProductScopeServices",
    "ProductWorkerRuntime",
    "compose_product_worker",
]
