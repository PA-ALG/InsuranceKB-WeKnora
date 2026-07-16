"""008 W6：token→(principal + 允许 Space 集合) 鉴权。

fail-closed 默认：未配置 token=拒绝一切；越 Space 一律 403 且零业务数据回显；
operator 一律取 token 绑定的 principal（客户端自报无效，审计归属不可伪造）。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Grant(BaseModel):
    """一个 token 的授权：操作者身份 + 允许的 Space 集合（W6）。"""

    model_config = ConfigDict(frozen=True)

    principal: str = Field(min_length=1)
    space_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("principal")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("principal 不得为空白（审计归属不可匿名）")
        return v


def parse_tokens_config(raw: dict[str, Any] | str | None) -> dict[str, Grant]:
    """解析 token 配置（dict 或 JSON 字符串）。空/None → 空表（fail-closed）。"""
    if raw is None:
        return {}
    data: dict[str, Any] = json.loads(raw) if isinstance(raw, str) else raw
    return {token: Grant.model_validate(grant) for token, grant in data.items()}


class AuthDenied(Exception):
    """401：token 缺失/未知。"""


class SpaceForbidden(Exception):
    """403：space 不在 token 允许集（响应不回显目标 space 细节）。"""


def authorize(
    grants: dict[str, Grant], authorization_header: str | None, space_id: str
) -> Grant:
    """鉴权链：Bearer token → grant → space ∈ 允许集；任何一步失败即拒。"""
    if not authorization_header or not authorization_header.startswith("Bearer "):
        raise AuthDenied
    token = authorization_header.removeprefix("Bearer ").strip()
    grant = grants.get(token)
    if grant is None:
        raise AuthDenied
    if space_id not in grant.space_ids:
        raise SpaceForbidden
    return grant
