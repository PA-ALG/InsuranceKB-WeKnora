# 001 规格（验收条件）

每条 spec 对应至少一个 pytest 用例，测试名引用编号（10-development-guide.md §2）。

## S1 项目脚手架

- S1.1 干净环境执行 `cd harness && uv sync && uv run pytest` 全绿；
- S1.2 `uv run ruff check .` 与 `uv run mypy .` 零报错；
- S1.3 每个子包（compiler/goldenset/workbench/mcp/adapters/schemas）有 README.md 说明职责与关系。

## S2 WeKnora 适配层

- S2.1 客户端从 Pydantic Settings 读取 base_url 与 API Key；缺配置时启动即报错（而非运行时）；
- S2.2 `wait_for_parsed(knowledge_id)`：轮询直到 `parse_status=completed` 返回；`failed` 抛业务异常；支持超时与退避间隔配置；
- S2.3 `list_chunks(knowledge_id)`：分页拉全 chunk，返回含 chunk_id/seq/内容/元数据的模型对象；
- S2.4 wiki 页 CRUD：create/get/update/delete/move + folder CRUD；update 携带 source_refs/chunk_refs/page_metadata 往返不丢字段；
- S2.5 同一 slug 的并发写在客户端内串行化（asyncio 锁），并发 10 次写入结果等价于顺序写（regression 保护，直至 P-1 补丁）；
- S2.6 HTTP 5xx/超时自动重试（指数退避，次数可配）；4xx 不重试直接抛错并带响应体；
- S2.7 所有调用发出 Langfuse trace（trace 名含 harness_job_id），无 Langfuse 配置时静默降级。

## S3 契约测试

- S3.1 上述每个 API 有 respx mock 测试（成功 + 至少一种失败路径）；
- S3.2 提供 `pytest -m live` 开关：against 真实 WeKnora 测试实例跑同一套断言（版本列车升级时的门禁，02 §8）。

## S4 CI

- S4.1 PR 触及 `harness/**` 时自动跑 ruff+mypy+pytest；失败阻断合并；
- S4.2 CI 不触发、不修改上游 Go/前端的任何构建。
