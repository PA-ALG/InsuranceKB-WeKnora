"""S2.7 Langfuse 可选集成：未配置/未安装时静默降级为 no-op。"""

import httpx
import respx

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.adapters.weknora.tracing import NoopTracer, build_tracer
from insurance_harness.config import HarnessSettings
from tests.conftest import BASE_URL


def test_s2_7_no_config_yields_noop(settings: HarnessSettings) -> None:
    tracer = build_tracer(settings, harness_job_id="job-1")
    assert isinstance(tracer, NoopTracer)
    with tracer.span("weknora.GET /x"):  # 可用且无副作用
        pass


def test_s2_7_config_without_package_degrades_to_noop() -> None:
    settings = HarnessSettings(
        weknora_base_url=BASE_URL,
        weknora_api_key="sk-test",
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
    )
    # dev 环境未安装 langfuse 包 → 必须优雅降级而不是抛错
    tracer = build_tracer(settings, harness_job_id=None)
    assert isinstance(tracer, NoopTracer)


@respx.mock
async def test_s2_7_client_works_with_noop_tracer(settings: HarnessSettings) -> None:
    respx.get(f"{BASE_URL}/api/v1/knowledge/k-1").mock(
        return_value=httpx.Response(
            200, json={"data": {"id": "k-1", "parse_status": "completed"}, "success": True}
        )
    )
    client = WeKnoraClient(settings, harness_job_id="job-42")
    knowledge = await client.get_knowledge("k-1")
    assert knowledge.id == "k-1"
    await client.aclose()
