# adapters

外部系统适配层。**边界纪律**（docs/insurance-kb/02-architecture.md §3、10 §3）：

- `weknora/`：WeKnora REST 客户端——全仓库**唯一**允许出现 WeKnora API 路径、头、响应结构的位置；
- 上游 API 变化只改这里，管道层（compiler 等）只依赖本层的模型对象与异常分型。
