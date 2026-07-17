"""Wheel 冒烟（PR#15 阻断 7）：在只装 wheel 的干净 venv 里证明工作台可启动。

验证三件事，任一失败即非零退出：
1. PackageLoader 能从**已安装包**加载模板（templates 随 wheel 分发）；
2. vendored HTMX 静态资源随 wheel 分发且可被 /static 路由服务；
3. ``create_app`` 可构造、GET /login 与 /static/vendor/htmx.min.js 返回 200。

用法（CI）：uv build → 新 venv pip install dist/*.whl → 该 venv 的 python 运行本脚本。
本脚本不依赖仓库源码路径——只 import 已安装的 insurance_harness。
"""

from __future__ import annotations

import sys


def main() -> int:
    import insurance_harness

    location = insurance_harness.__file__ or ""
    if "/src/insurance_harness/" in location.replace("\\", "/"):
        print(f"FAIL: 导入的是仓库源码而非已安装 wheel：{location}")
        return 1

    from fastapi.testclient import TestClient

    from insurance_harness.schemas.models import (
        FieldSpec,
        ProductLineSchema,
        SchemaRegistry,
    )
    from insurance_harness.workbench.app import create_app

    registry = SchemaRegistry(
        version="v0+wheel-smoke",
        lines={
            "smoke": ProductLineSchema(
                line_key="smoke",
                sheet_name="冒烟",
                fields=(FieldSpec(name="等待期", field_id="waiting_period"),),
            )
        },
        glossary=(),
    )

    def _no_db_session() -> object:
        raise AssertionError("冒烟不触库：/login 与静态资源不得查询数据库")

    app = create_app(
        session_factory=_no_db_session,  # type: ignore[arg-type]
        tokens_config={"smoke-token": {"principal": "冒烟", "space_ids": ["s1"]}},
        schema_registry=registry,
    )
    client = TestClient(app)

    login = client.get("/login")
    if login.status_code != 200 or "审核工作台登录" not in login.text:
        print(f"FAIL: GET /login → {login.status_code}")
        return 1
    if not client.cookies.get("wb_csrf"):
        print("FAIL: /login 未下发 CSRF cookie")
        return 1

    htmx = client.get("/static/vendor/htmx.min.js")
    if htmx.status_code != 200 or len(htmx.content) < 10_000:
        print(f"FAIL: htmx 静态资源 → {htmx.status_code} ({len(htmx.content)}B)")
        return 1

    print(
        "PASS: wheel 冒烟通过 —— templates+static 随包分发，"
        f"login 可渲染，htmx {len(htmx.content)}B（{location}）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
