"""Langfuse 可观测集成（spec S2.7）。

Langfuse 未配置或包未安装时**静默降级为 no-op**——适配层的可用性不依赖可观测设施。
span 名携带 harness_job_id，用于与 WeKnora 侧链路关联（docs/insurance-kb/02 §9）。
"""

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any, Protocol

from insurance_harness.config import HarnessSettings


class Tracer(Protocol):
    def span(self, name: str) -> Any:  # AbstractContextManager[None]
        ...


class NoopTracer:
    """无 Langfuse 时的空实现。"""

    def span(self, name: str) -> Any:
        return nullcontext()


class LangfuseTracer:
    """薄封装：每个适配层调用一个 span。"""

    def __init__(self, client: Any, harness_job_id: str | None) -> None:
        self._client = client
        self._job_id = harness_job_id

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        full_name = f"{name} [job:{self._job_id}]" if self._job_id else name
        span = None
        try:
            span = self._client.span(name=full_name)
        except Exception:  # pragma: no cover - 可观测设施故障不影响主链路
            pass
        try:
            yield
        finally:
            if span is not None:  # pragma: no cover
                try:
                    span.end()
                except Exception:
                    pass


def build_tracer(settings: HarnessSettings, harness_job_id: str | None = None) -> Tracer:
    """按配置构建 tracer；缺配置或缺依赖一律返回 NoopTracer（优雅降级）。"""
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return NoopTracer()
    try:
        from langfuse import Langfuse
    except ImportError:
        return NoopTracer()
    try:  # pragma: no cover - 需真实 Langfuse 环境
        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host or None,
        )
    except Exception:
        return NoopTracer()
    return LangfuseTracer(client, harness_job_id)  # pragma: no cover
