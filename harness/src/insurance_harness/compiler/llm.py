"""统一模型客户端（004 T1/T4；设计 docs/insurance-kb/04 §2.1）。

002 goldenset 与 004 抽取管道共用同一 ``ModelClient`` Protocol：
- ``ReplayClient``：录制回放夹具（测试/无网关凭据时唯一可用通道）；
- ``LiteLLMClient``：经 new-api 网关的真实调用（08 选型），litellm 为可选
  extra ``llm``，延迟导入——CI 不装该组也能 import 本模块。
"""

import hashlib
from pathlib import Path
from typing import Any, Protocol, cast

import httpx
from pydantic import BaseModel


class ModelClient(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


def request_key(system: str, user: str) -> str:
    return hashlib.sha256((system + "\x00" + user).encode("utf-8")).hexdigest()[:16]


class ReplayClient:
    """从夹具目录回放录制响应（002 spec G5.1 / 004 spec E5.3）。文件名 = request_key + .txt。"""

    def __init__(self, fixture_dir: Path) -> None:
        self._dir = fixture_dir
        self.calls = 0

    async def complete(self, system: str, user: str) -> str:
        self.calls += 1
        path = self._dir / f"{request_key(system, user)}.txt"
        if not path.exists():
            raise FileNotFoundError(
                f"ReplayClient 缺少夹具 {path.name}（system/user 变更会导致 key 变化）"
            )
        return path.read_text(encoding="utf-8")


class CallStats(BaseModel):
    """LLM 调用统计（E1.3 run manifest）。无网关侧 token 计数时以字符数为估算基础。"""

    calls: int = 0
    prompt_chars: int = 0
    completion_chars: int = 0

    def record(self, system: str, user: str, completion: str) -> None:
        self.calls += 1
        self.prompt_chars += len(system) + len(user)
        self.completion_chars += len(completion)

    @property
    def est_tokens(self) -> int:
        # 中文语料下 1 token ≈ 1.5 字符的保守估算（仅用于 manifest 量级参考）
        return int((self.prompt_chars + self.completion_chars) / 1.5)


class MeteredClient:
    """包装任意 ModelClient，把调用量记入 CallStats（E1.3）。"""

    def __init__(self, inner: ModelClient, stats: CallStats) -> None:
        self._inner = inner
        self.stats = stats

    async def complete(self, system: str, user: str) -> str:
        out = await self._inner.complete(system, user)
        self.stats.record(system, user, out)
        return out


class TruncatedOutputError(Exception):
    """模型输出被截断（content 为空且 finish_reason=length）——按内容级重试处理。

    推理型模型（deepseek-v4-flash / MiniMax-M2.5 均返回 reasoning_content）在
    max_tokens 不足时会把预算全部耗在推理上，正文为空。
    """


class OpenAICompatClient:
    """OpenAI 兼容端点直连（百炼 DashScope compatible-mode；坑清单 #9：trust_env=False）。

    推理型模型约定（业务方 2026-07-12 实测）：
    - max_tokens 必须给足（默认 4096），否则 reasoning_content 吃掉全部预算；
    - 只取 message.content，忽略 reasoning_content；
    - content 为空且 finish_reason=length → 视为截断抛 TruncatedOutputError（可重试）。
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout_s: float = 180.0,
    ) -> None:
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
            trust_env=False,  # 本机 SOCKS 代理环境变量曾导致 httpx 全挂（HANDOFF 坑 #9）
        )

    @property
    def model(self) -> str:
        return self._model

    async def complete(self, system: str, user: str) -> str:
        resp = await self._client.post(
            "/chat/completions",
            json={
                "model": self._model,
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        choice = data["choices"][0]
        content = str(choice.get("message", {}).get("content") or "")
        if not content.strip():
            finish = str(choice.get("finish_reason", ""))
            raise TruncatedOutputError(
                f"模型 {self._model} 输出正文为空（finish_reason={finish}）——"
                "疑似 reasoning 耗尽 max_tokens，按截断重试"
            )
        return content

    async def aclose(self) -> None:
        await self._client.aclose()


class LiteLLMClient:
    """经模型网关的真实调用（08 选型：new-api + litellm）。依赖可选 extra ``llm``。

    002 的 goldenset.annotator.LiteLLMClient 是本类的 settings 包装。
    """

    def __init__(
        self,
        model: str,
        api_base: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        if not model:
            raise ValueError("缺少模型标识（如 HARNESS_EXTRACTION_MODEL）")
        try:
            import litellm
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "litellm 未安装：请 `uv sync --extra llm` 后再使用真实模型"
            ) from exc
        self._litellm = litellm
        self._model = model
        self._api_base = api_base
        self._api_key = api_key
        self._temperature = temperature

    async def complete(self, system: str, user: str) -> str:  # pragma: no cover - 需真实网关
        resp = await self._litellm.acompletion(
            model=self._model,
            api_base=self._api_base,
            api_key=self._api_key,
            temperature=self._temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return cast(str, resp.choices[0].message.content or "")
