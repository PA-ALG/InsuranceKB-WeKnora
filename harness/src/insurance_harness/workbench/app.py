"""008 审核工作台 FastAPI 应用（W5 工程边界：只经 knowledge/ 服务层）。

T1 鉴权/Space fail-closed 骨干；T2 只读查询；T3 队列页与三动作。
写路径唯一入口 = knowledge 服务层（resolve_review 等）；本包零直接 SQL 写。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse
from jinja2 import Environment, PackageLoader, select_autoescape
from sqlalchemy.orm import Session

from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    UnboundKnowledgeSpace,
    load_scope,
)
from insurance_harness.knowledge.merge import overturn_review, resolve_review
from insurance_harness.knowledge.review import get_review_item

from .auth import AuthDenied, Grant, SpaceForbidden, authorize, parse_tokens_config
from .queries import (
    change_set_detail,
    claim_drill,
    completeness_matrix,
    list_change_sets,
    list_review_queue,
    matrix_export_rows,
    product_timeline,
)

_FORBIDDEN_BODY = "forbidden"  # 常量响应：不回显目标 space/业务细节（W6 零泄露）

_jinja = Environment(
    loader=PackageLoader("insurance_harness.workbench", "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)


def create_app(
    *,
    session_factory: Callable[[], Session],
    tokens_config: dict[str, Any] | str | None,
) -> FastAPI:
    grants = parse_tokens_config(tokens_config)
    app = FastAPI(title="insurance-harness 审核工作台", docs_url=None, redoc_url=None)

    def _authed_scope(
        request: Request, space_id: str, session: Session
    ) -> tuple[Grant, KnowledgeScope]:
        """鉴权→授权→016 fail-closed 的统一入口；任何失败在业务查询前拒绝。"""
        grant = authorize(grants, request.headers.get("Authorization"), space_id)
        scope = load_scope(session, space_id)  # 未绑定/不存在 → fail-closed
        return grant, scope

    @app.exception_handler(AuthDenied)
    async def _on_denied(_r: Request, _e: AuthDenied) -> Response:
        return Response(status_code=401, content="unauthorized")

    @app.exception_handler(SpaceForbidden)
    async def _on_forbidden(_r: Request, _e: SpaceForbidden) -> Response:
        return Response(status_code=403, content=_FORBIDDEN_BODY)

    @app.exception_handler(UnboundKnowledgeSpace)
    async def _on_unbound(_r: Request, _e: UnboundKnowledgeSpace) -> Response:
        return Response(status_code=403, content=_FORBIDDEN_BODY)

    @app.exception_handler(ScopeViolation)
    async def _on_violation(_r: Request, _e: ScopeViolation) -> Response:
        return Response(status_code=403, content=_FORBIDDEN_BODY)

    @app.get("/spaces/{space_id}/queue", response_class=HTMLResponse)
    def queue_page(request: Request, space_id: str) -> HTMLResponse:
        with session_factory() as session:
            _grant, scope = _authed_scope(request, space_id, session)
            page = list_review_queue(session, scope)
            html = _jinja.get_template("queue.html.j2").render(
                space_id=space_id, page=page
            )
            return HTMLResponse(html)

    @app.post("/spaces/{space_id}/queue/{review_key}/action", response_class=HTMLResponse)
    def review_action(
        request: Request,
        space_id: str,
        review_key: str,
        action: Annotated[str, Form()],
        reason: Annotated[str | None, Form()] = None,
    ) -> HTMLResponse:
        """三动作（W1.3/W1.4）。operator 一律取 token principal——路由签名
        刻意不接收任何客户端 operator 字段（W6 审计归属不可伪造）。"""
        with session_factory() as session:
            grant, scope = _authed_scope(request, space_id, session)
            item = get_review_item(session, scope, review_key)
            if item is None:
                return HTMLResponse("not found", status_code=404)
            if item.status != "open":
                prev = (item.resolution or {}).get("action")
                if action == prev:
                    return HTMLResponse(
                        f"<td colspan='5'>已生效：{prev}（幂等）</td>"
                    )  # 同决定重复提交 → 幂等
                return HTMLResponse(
                    "<td colspan='5'>该项已决，请刷新队列</td>", status_code=409
                )
            try:
                resolved = resolve_review(
                    session, scope, review_key, action,
                    actor=grant.principal, reason=reason,
                )
            except ValueError as exc:
                return HTMLResponse(str(exc), status_code=400)
            session.commit()
            return HTMLResponse(
                f"<td colspan='5'>{review_key}：{action} → {resolved.status}</td>"
            )

    @app.post("/spaces/{space_id}/queue/{review_key}/overturn", response_class=HTMLResponse)
    def review_overturn(
        request: Request,
        space_id: str,
        review_key: str,
        new_action: Annotated[str, Form()],
        reason: Annotated[str, Form(min_length=1)],
    ) -> HTMLResponse:
        """翻案（W2.3）：新 ChangeSet 走审核，原决定不改写；理由必填。"""
        with session_factory() as session:
            grant, scope = _authed_scope(request, space_id, session)
            try:
                change_set = overturn_review(
                    session, scope, review_key, new_action,
                    actor=grant.principal, reason=reason,
                )
            except ValueError as exc:
                return HTMLResponse(str(exc), status_code=400)
            session.commit()
            return HTMLResponse(
                f"翻案已受理：新 ChangeSet {change_set.id}（原记录不改写）"
            )

    @app.get("/spaces/{space_id}/changes", response_class=HTMLResponse)
    def changes_page(request: Request, space_id: str) -> HTMLResponse:
        with session_factory() as session:
            _grant, scope = _authed_scope(request, space_id, session)
            sets = list_change_sets(session, scope)
            html = _jinja.get_template("changes.html.j2").render(
                space_id=space_id, sets=sets
            )
            return HTMLResponse(html)

    @app.get("/spaces/{space_id}/changes/{change_set_id}", response_class=HTMLResponse)
    def changeset_detail_page(
        request: Request, space_id: str, change_set_id: str
    ) -> HTMLResponse:
        with session_factory() as session:
            _grant, scope = _authed_scope(request, space_id, session)
            detail = change_set_detail(session, scope, change_set_id)
            if detail is None:
                return HTMLResponse("not found", status_code=404)
            html = _jinja.get_template("changeset_detail.html.j2").render(
                space_id=space_id, detail=detail
            )
            return HTMLResponse(html)

    @app.get("/spaces/{space_id}/timeline", response_class=HTMLResponse)
    def timeline_page(request: Request, space_id: str) -> HTMLResponse:
        with session_factory() as session:
            _grant, scope = _authed_scope(request, space_id, session)
            rows = product_timeline(session, scope)
            html = _jinja.get_template("timeline.html.j2").render(
                space_id=space_id, rows=rows
            )
            return HTMLResponse(html)

    @app.get("/spaces/{space_id}/matrix", response_class=HTMLResponse)
    def matrix_page(request: Request, space_id: str) -> HTMLResponse:
        with session_factory() as session:
            _grant, scope = _authed_scope(request, space_id, session)
            matrix = completeness_matrix(session, scope)
            html = _jinja.get_template("matrix.html.j2").render(
                space_id=space_id, matrix=matrix
            )
            return HTMLResponse(html)

    @app.get("/spaces/{space_id}/matrix/export")
    def matrix_export(request: Request, space_id: str, fmt: str = "csv") -> Response:
        """W3.3 缺口清单导出（CSV/JSONL），含工单来源标注列。"""
        import csv
        import io
        import json

        with session_factory() as session:
            _grant, scope = _authed_scope(request, space_id, session)
            rows = matrix_export_rows(session, scope)
        header = [
            "product_code", "product_name", "version_label",
            "field", "state", "ticket_source",
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
    ) -> HTMLResponse:
        with session_factory() as session:
            _grant, scope = _authed_scope(request, space_id, session)
            drill = claim_drill(session, scope, version_id, predicate)
            if drill is None:
                return HTMLResponse("not found", status_code=404)
            html = _jinja.get_template("drill.html.j2").render(
                space_id=space_id, drill=drill
            )
            return HTMLResponse(html)

    @app.post("/spaces/{space_id}/queue/batch-approve", response_class=HTMLResponse)
    def batch_approve(
        request: Request,
        space_id: str,
        keys: Annotated[list[str], Form()],
    ) -> HTMLResponse:
        """批量 approve（W1.3）：仅 risk_level≠high；被排除项显式提示不静默。"""
        with session_factory() as session:
            grant, scope = _authed_scope(request, space_id, session)
            approved: list[str] = []
            excluded_high: list[str] = []
            skipped: list[str] = []
            for key in keys:
                item = get_review_item(session, scope, key)
                if item is None or item.status != "open":
                    skipped.append(key)
                    continue
                if item.risk_level == "high":
                    excluded_high.append(key)
                    continue
                resolve_review(
                    session, scope, key, "approve", actor=grant.principal
                )
                approved.append(key)
            session.commit()
            parts = [f"批量通过 {len(approved)} 条"]
            if excluded_high:
                parts.append(f"高风险已排除（须单条人审）：{'、'.join(excluded_high)}")
            if skipped:
                parts.append(f"跳过（不存在/已决）：{'、'.join(skipped)}")
            return HTMLResponse("；".join(parts))

    return app
