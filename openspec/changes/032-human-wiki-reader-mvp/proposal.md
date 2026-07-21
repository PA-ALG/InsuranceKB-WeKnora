# 032 · Human Wiki Reader MVP

> 状态：MVP M1，规格与实施计划已独立复核。北极星 C1/C5/C6；依赖 029，不修改 008。

## 为什么做

Enterprise LLM Wiki 的人类入口必须是可直接阅读的产品知识页，而不是审核工作台或原始文档片段。008 面向运营人员执行审核动作；将消费型阅读页继续塞入 008 会混淆写权限、发布语义和后续 WeKnora UI 接入边界。

## 做什么

- 新建 Harness 内独立的只读 Human Wiki Reader；
- 只通过 029 的 `ApprovedSnapshotReader` 读取当前批准快照；
- 提供产品目录、产品页、字段事实、Evidence 摘要、typed gap 与版本/manifest 标识；
- 与 013 MCP 对同一请求返回相同 `snapshot_id + manifest_hash + facts`；
- Space/token 未绑定、未批准、跨 Space 或 coverage gap 时 fail closed；
- P-1 前只服务 ACL 隔离 staging/内部预览，不写生产 WeKnora Wiki。

## 不做

不增加审核动作、发布/回滚按钮、Schema 编辑、跨产品比较、全文搜索、生产 WeKnora 页面写入、P-1 alias 或新的知识读模型。

## 文件域

新 `human_reader/` 包与 032 tests；只消费 `knowledge/serving.py` 的公开接口，不修改 `knowledge/`、`mcp/` 或 `workbench/`。
