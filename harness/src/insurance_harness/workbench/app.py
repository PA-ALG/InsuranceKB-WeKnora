"""008 审核工作台 FastAPI 应用（W5 工程边界：只经 knowledge/ 服务层）。

写路径唯一入口 = knowledge 服务层（resolve_review / request_review_overturn）；
本包零直接 SQL 写。认证双通道（auth.py）：Bearer（自动化）+ 会话 cookie（浏览器，
CSRF 双提交）。动作路由携带乐观并发版本（expected_version）与幂等 request_id，
并发语义由服务层行锁裁定（PR#15 阻断 3）。
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, PackageLoader, select_autoescape
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    UnboundKnowledgeSpace,
    load_scope,
)
from insurance_harness.knowledge.merge import (
    MergeError,
    ReviewDecisionConflict,
    ReviewPreconditionRequired,
    ReviewStale,
    request_review_overturn,
    resolve_review,
)
from insurance_harness.knowledge.projection import load_review_aggregate
from insurance_harness.knowledge.review import get_review_item
from insurance_harness.schemas.models import SchemaRegistry

from .auth import (
    CSRF_COOKIE,
    CSRF_FIELD,
    SESSION_COOKIE,
    AuthContext,
    AuthDenied,
    CsrfRejected,
    SpaceForbidden,
    authenticate,
    digest_grants,
    issue_session,
    new_csrf_token,
    parse_tokens_config,
    require_csrf,
    require_space,
)
from .queries import (
    cell_drill,
    change_set_detail,
    completeness_matrix,
    list_change_sets,
    list_review_queue,
    matrix_export_rows,
    product_timeline,
)

_FORBIDDEN_BODY = "forbidden"  # 常量响应：不回显目标 space/业务细节（W6 零泄露）
# 服务层 MergeError（域冲突/证据不足）→ 409 常量体：绝不回显 str(exc)，
# 因其含他项 claim id / product_version_id / predicate（W6 零泄露 + W1 干净拒绝）。
_CONFLICT_BODY = "该字段已有生效声明或候选证据不足，请刷新队列后重试"

_jinja = Environment(
    loader=PackageLoader("insurance_harness.workbench", "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    *,
    session_factory: Callable[[], Session],
    tokens_config: dict[str, Any] | str | None,
    schema_registry: SchemaRegistry,
    session_secret: str | bytes | None = None,
    session_ttl_s: int = 8 * 3600,
    engine: Engine | None = None,
) -> FastAPI:
    """可注入工厂（测试用）；生产零参入口见 create_app_from_settings。"""
    grants = parse_tokens_config(tokens_config)
    digest_map = digest_grants(grants)
    if session_secret is None:
        secret = secrets.token_bytes(32)  # 进程内随机：重启即全员重登（文档化）
    elif isinstance(session_secret, str):
        secret = session_secret.encode("utf-8")
    else:
        secret = session_secret

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if engine is not None:
            engine.dispose()

    app = FastAPI(
        title="insurance-harness 审核工作台",
        docs_url=None,
        redoc_url=None,
        lifespan=_lifespan,
    )
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # ------------------------------------------------------------- 认证/公共构件

    def _ctx(request: Request) -> AuthContext:
        return authenticate(
            grants,
            digest_map,
            secret,
            authorization_header=request.headers.get("Authorization"),
            session_cookie=request.cookies.get(SESSION_COOKIE),
        )

    def _authed_scope(
        request: Request, space_id: str, session: Session
    ) -> tuple[AuthContext, KnowledgeScope]:
        """鉴权→授权→016 fail-closed 的统一入口；任何失败在业务查询前拒绝。"""
        ctx = _ctx(request)
        require_space(ctx, space_id)
        scope = load_scope(session, space_id)  # 未绑定/不存在 → fail-closed
        return ctx, scope

    def _write_guard(
        request: Request, ctx: AuthContext, csrf_field: str | None
    ) -> None:
        """cookie 会话的写请求必须过 CSRF 双提交；Bearer 通道豁免。"""
        require_csrf(ctx, request.cookies.get(CSRF_COOKIE), csrf_field)

    def _csrf_of(request: Request) -> tuple[str, bool]:
        """读取（或新造）CSRF token；返回 (值, 是否需要下发 cookie)。"""
        existing = request.cookies.get(CSRF_COOKIE)
        if existing:
            return existing, False
        return new_csrf_token(), True

    def _page(
        request: Request, template: str, /, **context: Any
    ) -> HTMLResponse:
        csrf, fresh = _csrf_of(request)
        html = _jinja.get_template(template).render(csrf_token=csrf, **context)
        resp = HTMLResponse(html)
        if fresh:
            resp.set_cookie(
                CSRF_COOKIE, csrf, httponly=True, samesite="strict", path="/"
            )
        return resp

    def _is_htmx(request: Request) -> bool:
        return request.headers.get("HX-Request") == "true"

    def _queue_row_html(
        request: Request,
        session: Session,
        scope: KnowledgeScope,
        space_id: str,
        review_key: str,
        *,
        notice: str | None = None,
    ) -> str:
        item = get_review_item(session, scope, review_key)
        if item is None:
            return f"<tr><td colspan='9'>{review_key}：not found</td></tr>"
        aggregate = load_review_aggregate(session, scope, item)
        csrf, _ = _csrf_of(request)
        return _jinja.get_template("queue_row.html.j2").render(
            space_id=space_id,
            item=aggregate,
            csrf_token=csrf,
            request_id=uuid.uuid4().hex,
            notice=notice,
        )

    def _action_response(
        request: Request,
        session: Session,
        scope: KnowledgeScope,
        space_id: str,
        review_key: str,
        *,
        notice: str,
        status_code: int = 200,
    ) -> Response:
        """HTMX → 最新行片段（含提示）；浏览器表单 → 303 回队列页。"""
        if _is_htmx(request):
            return HTMLResponse(
                _queue_row_html(
                    request, session, scope, space_id, review_key, notice=notice
                ),
                status_code=status_code,
            )
        if status_code == 200:
            return RedirectResponse(
                url=f"/spaces/{space_id}/queue", status_code=303
            )
        return HTMLResponse(
            f"{notice}（<a href='/spaces/{space_id}/queue'>返回队列</a>）",
            status_code=status_code,
        )

    # ------------------------------------------------------------- 异常翻译

    @app.exception_handler(AuthDenied)
    async def _on_denied(_r: Request, _e: AuthDenied) -> Response:
        return Response(status_code=401, content="unauthorized")

    @app.exception_handler(SpaceForbidden)
    async def _on_forbidden(_r: Request, _e: SpaceForbidden) -> Response:
        return Response(status_code=403, content=_FORBIDDEN_BODY)

    @app.exception_handler(CsrfRejected)
    async def _on_csrf(_r: Request, _e: CsrfRejected) -> Response:
        return Response(status_code=403, content=_FORBIDDEN_BODY)

    @app.exception_handler(UnboundKnowledgeSpace)
    async def _on_unbound(_r: Request, _e: UnboundKnowledgeSpace) -> Response:
        return Response(status_code=403, content=_FORBIDDEN_BODY)

    @app.exception_handler(ScopeViolation)
    async def _on_violation(_r: Request, _e: ScopeViolation) -> Response:
        return Response(status_code=403, content=_FORBIDDEN_BODY)

    # ------------------------------------------------------------- 登录桥（浏览器）

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request) -> Response:
        return _page(request, "login.html.j2", error=None)

    @app.post("/login")
    def login_submit(
        request: Request,
        token: Annotated[str, Form()],
        csrf_token: Annotated[str | None, Form(alias=CSRF_FIELD)] = None,
    ) -> Response:
        cookie_csrf = request.cookies.get(CSRF_COOKIE)
        if not cookie_csrf or not csrf_token or cookie_csrf != csrf_token:
            raise CsrfRejected
        if token not in grants:
            return HTMLResponse(
                _jinja.get_template("login.html.j2").render(
                    csrf_token=cookie_csrf, error="token 无效"
                ),
                status_code=401,
            )
        resp = RedirectResponse(url="/", status_code=303)
        resp.set_cookie(
            SESSION_COOKIE,
            issue_session(secret, token, ttl_s=session_ttl_s),
            httponly=True,
            samesite="strict",
            max_age=session_ttl_s,
            path="/",
        )
        return resp

    @app.post("/logout")
    def logout(
        request: Request,
        csrf_token: Annotated[str | None, Form(alias=CSRF_FIELD)] = None,
    ) -> Response:
        ctx = _ctx(request)
        _write_guard(request, ctx, csrf_token)
        resp = RedirectResponse(url="/login", status_code=303)
        resp.delete_cookie(SESSION_COOKIE, path="/")
        return resp

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> Response:
        ctx = _ctx(request)
        return _page(
            request,
            "home.html.j2",
            principal=ctx.grant.principal,
            space_ids=ctx.grant.space_ids,
            via=ctx.via,
        )

    # ------------------------------------------------------------- W1 审核队列

    @app.get("/spaces/{space_id}/queue", response_class=HTMLResponse)
    def queue_page(
        request: Request,
        space_id: str,
        status: str = "open",
        risk: str | None = None,
        type: str | None = None,  # noqa: A002 —— 对外查询参数名沿 spec 用语
        product: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Response:
        with session_factory() as session:
            _ctx_, scope = _authed_scope(request, space_id, session)
            page = list_review_queue(
                session,
                scope,
                status=status,
                risk_level=risk,
                type_=type,
                product_code=product,
                limit=max(1, min(limit, 200)),
                offset=max(0, offset),
            )
            return _page(
                request,
                "queue.html.j2",
                space_id=space_id,
                page=page,
                request_id=uuid.uuid4().hex,
            )

    @app.post(
        "/spaces/{space_id}/queue/{review_key}/action", response_class=HTMLResponse
    )
    def review_action(
        request: Request,
        space_id: str,
        review_key: str,
        action: Annotated[str, Form()],
        expected_version: Annotated[str, Form(min_length=1)],
        request_id: Annotated[str, Form(min_length=1)],
        reason: Annotated[str | None, Form()] = None,
        csrf_token: Annotated[str | None, Form(alias=CSRF_FIELD)] = None,
    ) -> Response:
        """三动作（W1.3/W1.4）。operator 一律取授权 principal——路由签名
        刻意不接收任何客户端 operator 字段（W6 审计归属不可伪造）。
        并发合同**强制**（codex R2-P1）：expected_version/request_id 为必填
        表单字段——缺失/空由 FastAPI 校验拒为 422（零写），删掉隐藏字段不再是
        关闭 CAS 的通道；服务层同一约束二次强制（ReviewPreconditionRequired→428）。
        并发裁定在服务层行锁内完成：stale/异决定 → 409 + 最新行片段。"""
        with session_factory() as session:
            ctx, scope = _authed_scope(request, space_id, session)
            _write_guard(request, ctx, csrf_token)
            if get_review_item(session, scope, review_key) is None:
                return HTMLResponse("not found", status_code=404)
            try:
                resolved = resolve_review(
                    session, scope, review_key, action,
                    actor=ctx.grant.principal, reason=reason,
                    expected_version=expected_version, request_id=request_id,
                )
            except ScopeViolation:
                raise  # 越权→app 403 常量体；ScopeViolation⊂ValueError，须先于下捕获
            except ReviewPreconditionRequired as exc:
                session.rollback()
                return HTMLResponse(
                    f"缺少必需前置条件 {exc.missing}（并发合同强制，请从最新页面提交）",
                    status_code=428,
                )
            except (ReviewStale, ReviewDecisionConflict) as exc:
                session.rollback()
                return _action_response(
                    request, session, scope, space_id, review_key,
                    notice=(
                        f"该项已更新（当前 {exc.current_status}"
                        + (f"，决定 {exc.current_action}" if exc.current_action else "")
                        + "），请核对后重试"
                    ),
                    status_code=409,
                )
            except MergeError:
                # 域冲突（同字段已有 published）/ 无证据：W1 干净拒绝，常量体不泄露内部 id
                session.rollback()
                return HTMLResponse(_CONFLICT_BODY, status_code=409)
            except ValueError as exc:
                session.rollback()
                return HTMLResponse(str(exc), status_code=400)
            session.commit()
            return _action_response(
                request, session, scope, space_id, review_key,
                notice=f"{action} → {resolved.status}",
            )

    @app.post(
        "/spaces/{space_id}/queue/{review_key}/overturn", response_class=HTMLResponse
    )
    def review_overturn(
        request: Request,
        space_id: str,
        review_key: str,
        new_action: Annotated[str, Form()],
        reason: Annotated[str, Form(min_length=1)],
        csrf_token: Annotated[str | None, Form(alias=CSRF_FIELD)] = None,
    ) -> Response:
        """翻案（W2.3，两阶段）：只登记复议请求——生成 pending ChangeSet + 新的
        open 翻案审核项**走审核**；原决定/原事实此刻一概不动（阻断 2 修复）。"""
        with session_factory() as session:
            ctx, scope = _authed_scope(request, space_id, session)
            _write_guard(request, ctx, csrf_token)
            if get_review_item(session, scope, review_key) is None:
                # 与 action 路径对称：外空间/不存在的 key → 404（零泄露存在性）。
                return HTMLResponse("not found", status_code=404)
            try:
                change_set, overturn_item, created = request_review_overturn(
                    session, scope, review_key, new_action,
                    actor=ctx.grant.principal, reason=reason,
                )
            except ScopeViolation:
                raise  # 深层聚合越权 → app 403 常量体（防御纵深）
            except MergeError:
                session.rollback()
                return HTMLResponse(_CONFLICT_BODY, status_code=409)
            except ValueError as exc:
                session.rollback()
                return HTMLResponse(str(exc), status_code=400)
            session.commit()
            verb = "已受理" if created else "已存在（幂等）"
            return HTMLResponse(
                f"翻案{verb}：复议 ChangeSet {change_set.id}（pending）待审核项 "
                f"{overturn_item.review_key} 批准后生效；原决定与当前事实未变更。"
            )

    @app.post("/spaces/{space_id}/queue/batch-approve", response_class=HTMLResponse)
    def batch_approve(
        request: Request,
        space_id: str,
        keys: Annotated[list[str], Form()],
        request_id: Annotated[str, Form(min_length=1)],
        csrf_token: Annotated[str | None, Form(alias=CSRF_FIELD)] = None,
    ) -> Response:
        """批量 approve（W1.3）：仅 risk_level≠high；被排除项显式提示不静默。
        每项**必须**携带 ``<review_key>@<expected_version>``（codex R2-P1：裸 key /
        空版本按 malformed 显式拒绝，绝不降级为 None 关闭 CAS）；``request_id``
        必填；每项在 savepoint 内经服务层行锁+版本判定（不靠预读 status）。"""
        with session_factory() as session:
            ctx, scope = _authed_scope(request, space_id, session)
            _write_guard(request, ctx, csrf_token)
            approved: list[str] = []
            excluded_high: list[str] = []
            skipped: list[str] = []
            conflicted: list[str] = []
            stale: list[str] = []
            malformed: list[str] = []
            for raw in keys:
                key, sep, version = raw.partition("@")
                if not sep or not key.strip() or not version.strip():
                    malformed.append(raw or "<空>")
                    continue
                item = get_review_item(session, scope, key)
                if item is None:
                    skipped.append(key)
                    continue
                if item.risk_level == "high":
                    excluded_high.append(key)
                    continue
                # 每条独立 savepoint：单条域冲突/证据不足只回滚该条，其余低风险
                # 条目照常生效（W1「其余正常生效」——绝不因一条冲突整批回滚）。
                sp = session.begin_nested()
                try:
                    resolve_review(
                        session, scope, key, "approve",
                        actor=ctx.grant.principal,
                        expected_version=version,
                        request_id=f"{request_id}:{key}",
                    )
                except ScopeViolation:
                    sp.rollback()
                    raise  # 越权 → app 403（正常不可达：key 已经 scope 过滤）
                except (
                    ReviewPreconditionRequired,
                    ReviewStale,
                    ReviewDecisionConflict,
                ):
                    sp.rollback()
                    stale.append(key)
                    continue
                except (MergeError, ValueError):
                    sp.rollback()
                    conflicted.append(key)
                    continue
                sp.commit()
                approved.append(key)
            session.commit()
            parts = [f"批量通过 {len(approved)} 条"]
            if malformed:
                parts.append(
                    f"格式错误已拒绝（须 key@version，缺版本不受理）：{'、'.join(malformed)}"
                )
            if excluded_high:
                parts.append(f"高风险已排除（须单条人审）：{'、'.join(excluded_high)}")
            if stale:
                parts.append(f"版本已过期（他人已处理，请刷新）：{'、'.join(stale)}")
            if conflicted:
                parts.append(f"域冲突/证据不足已跳过（须单条核对）：{'、'.join(conflicted)}")
            if skipped:
                parts.append(f"跳过（不存在/已决）：{'、'.join(skipped)}")
            return HTMLResponse("；".join(parts))

    # ------------------------------------------------------------- W2 变更与时间线

    @app.get("/spaces/{space_id}/changes", response_class=HTMLResponse)
    def changes_page(request: Request, space_id: str) -> Response:
        with session_factory() as session:
            _ctx_, scope = _authed_scope(request, space_id, session)
            sets = list_change_sets(session, scope)
            return _page(
                request, "changes.html.j2", space_id=space_id, sets=sets
            )

    @app.get("/spaces/{space_id}/changes/{change_set_id}", response_class=HTMLResponse)
    def changeset_detail_page(
        request: Request, space_id: str, change_set_id: str
    ) -> Response:
        with session_factory() as session:
            _ctx_, scope = _authed_scope(request, space_id, session)
            detail = change_set_detail(session, scope, change_set_id)
            if detail is None:
                return HTMLResponse("not found", status_code=404)
            return _page(
                request,
                "changeset_detail.html.j2",
                space_id=space_id,
                detail=detail,
            )

    @app.get("/spaces/{space_id}/timeline", response_class=HTMLResponse)
    def timeline_page(request: Request, space_id: str) -> Response:
        with session_factory() as session:
            _ctx_, scope = _authed_scope(request, space_id, session)
            rows = product_timeline(session, scope)
            return _page(
                request, "timeline.html.j2", space_id=space_id, rows=rows
            )

    # ------------------------------------------------------------- W3 完整度矩阵

    @app.get("/spaces/{space_id}/matrix", response_class=HTMLResponse)
    def matrix_page(
        request: Request, space_id: str, category: str | None = None
    ) -> Response:
        with session_factory() as session:
            _ctx_, scope = _authed_scope(request, space_id, session)
            matrix = completeness_matrix(
                session, scope, schema_registry, category=category
            )
            return _page(
                request, "matrix.html.j2", space_id=space_id, matrix=matrix
            )

    @app.get("/spaces/{space_id}/matrix/export")
    def matrix_export(
        request: Request,
        space_id: str,
        fmt: str = "csv",
        category: str | None = None,
    ) -> Response:
        """W3.3 缺口清单导出（CSV/JSONL）：只含缺口态，ticket_source 稳定标注。"""
        import csv
        import io
        import json

        with session_factory() as session:
            _ctx_, scope = _authed_scope(request, space_id, session)
            rows = matrix_export_rows(
                session, scope, schema_registry, category=category
            )
        header = [
            "product_code", "product_name", "version_label", "category",
            "field", "field_name", "state", "ticket_source",
        ]
        if fmt == "jsonl":
            body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
            return Response(content=body, media_type="application/x-ndjson")
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
        return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8")

    @app.get(
        "/spaces/{space_id}/matrix/{version_id}/{predicate}",
        response_class=HTMLResponse,
    )
    def drill_page(
        request: Request, space_id: str, version_id: str, predicate: str
    ) -> Response:
        with session_factory() as session:
            _ctx_, scope = _authed_scope(request, space_id, session)
            drill = cell_drill(
                session, scope, schema_registry, version_id, predicate
            )
            if drill is None:
                return HTMLResponse("not found", status_code=404)
            return _page(
                request, "drill.html.j2", space_id=space_id, drill=drill
            )

    return app


def create_app_from_settings() -> FastAPI:
    """生产零参工厂（Runbook §3.4 唯一起服入口，阻断 7 修复）：

    ``uvicorn --factory insurance_harness.workbench.app:create_app_from_settings``

    校验 DB/token/schema 配置——任一缺失**启动即失败**（不吞错、不空底图）；
    engine 在 FastAPI lifespan shutdown 时 dispose。
    """
    from insurance_harness.config import HarnessSettings
    from insurance_harness.db.base import make_engine, make_session_factory
    from insurance_harness.schemas.loader import load_schema_registry

    settings = HarnessSettings()  # type: ignore[call-arg]  # 环境变量注入（S2.1）
    if not settings.db_url:
        raise RuntimeError("HARNESS_DB_URL 未配置：工作台需要 harness 数据库")
    if settings.workbench_tokens_json is None:
        raise RuntimeError(
            "HARNESS_WORKBENCH_TOKENS_JSON 未配置：token→(principal+Space) 绑定是"
            "工作台的鉴权前提（fail-closed，缺省拒绝启动而非放行）"
        )
    baseline_dir = settings.workbench_schema_baseline_dir
    if baseline_dir is None:
        for candidate in (
            Path("docs/insurance-kb/schema-baseline"),
            Path("../docs/insurance-kb/schema-baseline"),
        ):
            if candidate.is_dir():
                baseline_dir = candidate
                break
    if baseline_dir is None or not baseline_dir.is_dir():
        raise RuntimeError(
            "schema 基线目录不可用：设置 HARNESS_WORKBENCH_SCHEMA_BASELINE_DIR "
            "或在仓库根/harness 目录下启动（W3 全字段底图是硬前提）"
        )
    registry = load_schema_registry(baseline_dir)  # 损坏/为空 → 启动失败
    engine = make_engine(settings.db_url)
    return create_app(
        session_factory=make_session_factory(engine),
        tokens_config=settings.workbench_tokens_json,
        schema_registry=registry,
        session_secret=settings.workbench_session_secret,
        session_ttl_s=settings.workbench_session_ttl_s,
        engine=engine,
    )
