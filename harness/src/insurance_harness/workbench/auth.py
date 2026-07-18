"""008 W6：token→(principal + 允许 Space 集合) 鉴权 + 浏览器会话桥。

fail-closed 默认：未配置 token=拒绝一切；越 Space 一律 403 且零业务数据回显；
operator 一律取 token 绑定的 principal（客户端自报无效，审计归属不可伪造）。

两条认证通道（PR#15 阻断 4 修复）：

- **Bearer**（自动化/脚本）：每请求 ``Authorization: Bearer <token>``，无 CSRF 要求
  （token 本身即凭据，跨站表单带不上自定义头）；
- **会话 cookie**（浏览器）：token 仅在 ``/login`` 校验一次，签发短期、HMAC-SHA256
  签名、HttpOnly、SameSite=Strict 的 cookie——cookie 内只存 **token 的 SHA-256 摘要**
  与过期时间，不存明文 token；每请求由摘要在当前 token 配置中重新映射 Grant（配置
  轮换即时生效）。cookie 通道的全部写请求必须携带 CSRF token（双提交 cookie 模式）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

SESSION_COOKIE = "wb_session"
CSRF_COOKIE = "wb_csrf"
CSRF_FIELD = "csrf_token"


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


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def digest_grants(grants: dict[str, Grant]) -> dict[str, Grant]:
    """token 摘要 → Grant（会话 cookie 通道的查表；明文 token 不进会话层）。"""
    return {token_digest(token): grant for token, grant in grants.items()}


class AuthDenied(Exception):
    """401：token/会话 缺失、未知或过期。"""


class SpaceForbidden(Exception):
    """403：space 不在授权允许集（响应不回显目标 space 细节）。"""


class CsrfRejected(Exception):
    """403：cookie 会话写请求缺失/错配 CSRF token（常量体拒绝）。"""


# ------------------------------------------------------------------ 会话签发/校验


def _sign(secret: bytes, payload: bytes) -> str:
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def issue_session(secret: bytes, token: str, *, ttl_s: int, now: float | None = None) -> str:
    """签发会话值：b64url(JSON{td, exp}) . HMAC。只含 token 摘要与过期时间。"""
    body = {
        "td": token_digest(token),
        "exp": int((now if now is not None else time.time()) + ttl_s),
    }
    payload = base64.urlsafe_b64encode(
        json.dumps(body, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return f"{payload}.{_sign(secret, payload.encode('ascii'))}"


def verify_session(
    secret: bytes,
    cookie_value: str | None,
    digest_map: dict[str, Grant],
    *,
    now: float | None = None,
) -> Grant | None:
    """校验会话 cookie → Grant；签名/过期/摘要未知任一失败 → None（fail-closed）。"""
    if not cookie_value or "." not in cookie_value:
        return None
    payload, _, signature = cookie_value.rpartition(".")
    if not hmac.compare_digest(_sign(secret, payload.encode("ascii")), signature):
        return None
    try:
        body = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except (ValueError, json.JSONDecodeError):
        return None
    exp = body.get("exp")
    if not isinstance(exp, int) or (now if now is not None else time.time()) >= exp:
        return None
    digest = body.get("td")
    if not isinstance(digest, str):
        return None
    return digest_map.get(digest)


def new_csrf_token() -> str:
    return secrets.token_hex(16)


# ------------------------------------------------------------------ 请求鉴权


class AuthContext(BaseModel):
    """一次通过鉴权的请求上下文：授权 + 认证通道（cookie 通道写请求须过 CSRF）。"""

    model_config = ConfigDict(frozen=True)

    grant: Grant
    via: str  # "bearer" | "session"


def authenticate(
    grants: dict[str, Grant],
    digest_map: dict[str, Grant],
    secret: bytes,
    *,
    authorization_header: str | None,
    session_cookie: str | None,
) -> AuthContext:
    """认证链：Bearer 优先（自动化），否则会话 cookie；两者皆无/无效 → 401。"""
    if authorization_header and authorization_header.startswith("Bearer "):
        token = authorization_header.removeprefix("Bearer ").strip()
        grant = grants.get(token)
        if grant is None:
            raise AuthDenied
        return AuthContext(grant=grant, via="bearer")
    if authorization_header:
        raise AuthDenied  # 畸形 Authorization 头：显式拒绝，不降级 cookie
    grant = verify_session(secret, session_cookie, digest_map)
    if grant is None:
        raise AuthDenied
    return AuthContext(grant=grant, via="session")


def require_space(ctx: AuthContext, space_id: str) -> Grant:
    if space_id not in ctx.grant.space_ids:
        raise SpaceForbidden
    return ctx.grant


def require_csrf(ctx: AuthContext, csrf_cookie: str | None, csrf_field: str | None) -> None:
    """cookie 会话的写请求必须双提交一致；Bearer 通道豁免（无 cookie 即无 CSRF 面）。"""
    if ctx.via != "session":
        return
    if not csrf_cookie or not csrf_field:
        raise CsrfRejected
    if not hmac.compare_digest(csrf_cookie, csrf_field):
        raise CsrfRejected


def authorize(
    grants: dict[str, Grant], authorization_header: str | None, space_id: str
) -> Grant:
    """（兼容入口）纯 Bearer 鉴权链：token → grant → space ∈ 允许集。"""
    if not authorization_header or not authorization_header.startswith("Bearer "):
        raise AuthDenied
    token = authorization_header.removeprefix("Bearer ").strip()
    grant = grants.get(token)
    if grant is None:
        raise AuthDenied
    if space_id not in grant.space_ids:
        raise SpaceForbidden
    return grant
