# 001 任务

- [x] T1 harness/ 脚手架：pyproject（uv）、ruff/mypy/pytest 配置、子包占位与 README（S1）
- [x] T2 config.py：Pydantic Settings（S2.1）
- [x] T3 adapters/weknora：模型对象 + 客户端（S2.2~S2.4、S2.6）
- [x] T4 slug 串行化锁（S2.5）
- [x] T5 Langfuse trace 集成（S2.7，可选导入 + no-op 降级）
- [x] T6 respx 契约测试 + live 开关（S3）
- [x] T7 CI workflow（S4，.github/workflows/harness-ci.yml）
- [ ] T8 更新 HANDOFF.md（主会话统一处理）

状态：开发完成（2026-07-11）。验证：`uv run ruff check .` ✅ · `uv run mypy src tests`（strict）✅ · `uv run pytest -m "not live"` **21 passed**（2 live 用例默认跳过）。

实现备注：
- WeKnora API 契约按仓库 docs/api/*.md 与 internal/types/wiki_page.go 核实后编写；`move-page` 请求体为适配层假设，live 契约测试负责校验；
- httpx 客户端 `trust_env=False`：与内网 WeKnora 直连，不受 shell 代理变量（ALL_PROXY 等）干扰——本机曾因 SOCKS 代理变量导致测试全挂，这是修复。
