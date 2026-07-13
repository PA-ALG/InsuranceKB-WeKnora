# 001 设计（增量）

权威设计见 docs/insurance-kb/02（架构）、08（选型）、10（规范）；此处只写本 change 的增量决定。

1. **目录**：按 02 §7 建全子包，但除 adapters 外均为占位（仅 README + `__init__.py`）——让后续 change 的落点从第一天就固定。物理布局采用 **src 布局**（`harness/src/insurance_harness/…`，包名 `insurance_harness`），避免顶层包名污染，02 §7 已同步。
2. **HTTP 客户端**：httpx.AsyncClient 封装；模型对象用 Pydantic（WeKnoraKnowledge/WeKnoraChunk/WeKnoraWikiPage），字段名与上游 REST 对齐但只声明我们消费的字段（宽容解析 `extra="allow"`），降低上游小版本变化的破坏面。
3. **slug 串行化**：`asyncio.Lock` per-slug（weakref 字典）；多进程部署时的跨进程锁推迟到 P0.5（那时有 Postgres，advisory lock 顺手）。
4. **错误分型**：`WeKnoraTransientError`（可重试）/ `WeKnoraClientError`（4xx）/ `WeKnoraParseFailed`（业务失败），供上层管道分支。
5. **CI**：GitHub Actions 单 workflow，paths 过滤 `harness/**`；uv 官方 action；Python 3.12。
