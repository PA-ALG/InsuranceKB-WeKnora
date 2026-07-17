"""F1.1 Langfuse 客户端：拉取问答 trace，归一化 + 入库前脱敏 + 增量游标过滤。

硬边界：`trust_env=False`（本机 SOCKS 代理变量不得污染，坑清单 #9）。问题原文在
归一化时即经 `redact_pii` 脱敏——Trace 从不承载原始 PII。真实 Langfuse 字段映射
在 live 联调细化；`_to_trace` 保持对缺字段容错。
"""

from __future__ import annotations

from typing import Any

import httpx

from .cursor import new_traces
from .models import Trace
from .redact import redact_pii

_TRACES_PATH = "/api/public/traces"


class LangfuseClient:
    """薄客户端：GET traces → 归一化 Trace（脱敏）→ 按游标增量过滤。"""

    def __init__(
        self,
        base_url: str,
        public_key: str = "",
        secret_key: str = "",
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client if client is not None else httpx.Client(
            base_url=base_url,
            trust_env=False,  # 硬边界：不吃环境代理
            auth=(public_key, secret_key) if public_key else None,
            timeout=30.0,
        )

    def fetch_traces(self, since_cursor: str | None = None) -> list[Trace]:
        """拉取并归一化，返回严格晚于 since_cursor 的 trace（重跑幂等）。"""
        resp = self._client.get(_TRACES_PATH)
        resp.raise_for_status()
        payload = resp.json()
        traces = [self._to_trace(it) for it in payload.get("data", [])]
        return new_traces(traces, since_cursor)

    @staticmethod
    def _to_trace(item: dict[str, Any]) -> Trace:
        return Trace(
            trace_id=str(item["id"]),
            timestamp=str(item["timestamp"]),
            question=redact_pii(str(item.get("input") or "")),  # 入库前脱敏
            answer=str(item.get("output") or ""),
            source_refs=tuple(str(r) for r in (item.get("source_refs") or ())),
            score=item.get("score"),
            annotation=item.get("annotation"),
        )

    def close(self) -> None:
        self._client.close()
