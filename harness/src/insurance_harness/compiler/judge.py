"""可插拔裁决（08 选型更新 2026-07-12：裁决模型改用 Claude 会话，不走网关）。

- ``claude-session``（默认）：裁决请求写入 run 目录 ``judge-queue.jsonl``，字段标
  ``confidence=low + pending_judge=true`` 继续流转不阻塞；主会话 Claude 批处理后
  经 ``apply-judgements <run_dir> <judgements.jsonl>`` CLI 回写；
- ``gateway``：直接调 ``HARNESS_LLM_MODEL_JUDGE_FALLBACK``（deepseek-v4-pro）。

触发场景：E4.2 三票三样；E3.2 二次回验仍失败且字段 risk_level=high。
"""

import json
from pathlib import Path
from typing import Any

from .llm import ModelClient
from .models import FieldCandidate, Judgement, JudgeRequest
from .parsing import extract_json_array

JUDGE_SYSTEM = """你是寿险条款抽取结果的裁决者。你收到一个字段的多个候选值（含证据），\
从中选出最可信的一个，或判定全部不可信。只输出 JSON 数组（恰好一个元素）：
{"field_id": "...", "value": "字符串或 null", "tri_state": "present|unknown",
 "evidence": [{"page": 页码整数, "quote": "原文逐字摘录"}], "reasoning": "依据引用"}
必须输出依据引用；无法判定时 value=null、tri_state=unknown。"""


class JudgeDispatcher:
    """裁决分发：claude-session 入队；gateway 直接调裁决模型。"""

    def __init__(self, mode: str = "claude-session", client: ModelClient | None = None) -> None:
        if mode not in ("claude-session", "gateway"):
            raise ValueError(f"未知 judge_mode：{mode!r}")
        if mode == "gateway" and client is None:
            raise ValueError("gateway 裁决模式必须提供裁决模型 client")
        self.mode = mode
        self._client = client
        self.queue: list[JudgeRequest] = []

    async def dispatch(self, request: JudgeRequest) -> Judgement | None:
        """返回 Judgement（gateway 即时裁决）或 None（claude-session 入队待批处理）。"""
        if self.mode == "claude-session":
            self.queue.append(request)
            return None
        assert self._client is not None
        user = (
            f"产品：{request.product_name}\n文档：{request.doc}\n"
            f"字段：{request.field_name}（field_id={request.field_id}）\n"
            f"裁决原因:{request.reason}\n\n"
            f"## 候选值\n{json.dumps(request.candidates, ensure_ascii=False, indent=1)}\n\n"
            f"## 上下文节选\n{request.context_excerpt}"
        )
        raw = await self._client.complete(JUDGE_SYSTEM, user)
        parsed = extract_json_array(raw)
        if not parsed:
            return None
        item: dict[str, Any] = parsed[0]
        tri = str(item.get("tri_state", "unknown"))
        return Judgement(
            product_id=request.product_id,
            field_id=request.field_id,
            value=None if item.get("value") is None else str(item.get("value")),
            tri_state="present" if tri == "present" else "unknown",
            evidence=[
                {"page": int(e.get("page", 0)), "quote": str(e.get("quote", ""))}  # type: ignore[misc]
                for e in item.get("evidence") or []
                if isinstance(e, dict)
            ],
            confidence="medium",
            reasoning=str(item.get("reasoning", "")) or None,
        )


def make_judge_request(
    product_id: str,
    product_name: str,
    cand: FieldCandidate,
    reason: str,
    context_excerpt: str,
) -> JudgeRequest:
    candidates: list[dict[str, Any]] = []
    for v in cand.metadata.get("vote_candidates", []) or [cand.value]:
        candidates.append({"value": v})
    if cand.metadata.get("rejected_value") is not None:
        candidates.append(
            {
                "value": cand.metadata["rejected_value"],
                "evidence": cand.metadata.get("rejected_evidence"),
                "note": "quote 回验二次失败的候选",
            }
        )
    return JudgeRequest(
        product_id=product_id,
        product_name=product_name,
        doc=cand.doc,
        field_id=cand.field_id,
        field_name=cand.field_name,
        reason="vote_disagreement" if reason == "vote_disagreement" else "quote_mismatch_high_risk",
        candidates=candidates,
        context_excerpt=context_excerpt[:2000],
    )


def write_judge_queue(path: Path, queue: list[JudgeRequest]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(r.model_dump_json() + "\n" for r in queue), encoding="utf-8"
    )


def read_judgements(path: Path) -> list[Judgement]:
    return [
        Judgement.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
