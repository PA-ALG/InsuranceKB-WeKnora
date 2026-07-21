# 027 · Production Weak-Model Boundary

> 状态：MVP S0，规格待独立复核。北极星 C1/C3；是所有真实 MVP 模型运行的硬前置。

## 为什么做

现有 `compiler/cli.py`、`compiler/llm.py`、`compiler/judge.py`、配置与历史批处理仍允许 Claude/DeepSeek、未知或 rolling model identity。政策文档禁止这些路径，但没有统一运行时硬门禁；继续真实运行会让“生产只靠弱模型 Harness”成为口号。

## 做什么

- 枚举所有 production extract/judge/gap/merge/release 入口；
- 建立单一 `ProductionModelPolicy`，只接受批准、不可变身份的 MiniMax/Qwen/Qwen-VL 能力档；
- 在任何网络调用、候选推进、ChangeSet 或 CurrentRelease 变更前 fail closed；
- 旧强 judge/fallback 只能显式 offline-eval，不能被 production profile 引用；
- 把 policy decision、model identity、admission/run identity 写入 receipt；
- 为 028 提供稳定的 `ModelPermit`/`ModelGateway` 边界。

## 不做

不实现 TemplatePackage、编排器、预算 UI、模型效果优化或真实数据运行；不修改 knowledge/MCP/workbench。

## 文件域

`harness/src/insurance_harness/config.py`、模型/CLI/judge/fallback 入口、新 `model_policy/`（若需要）及 027 tests。任何跨域修改须另拆小 PR。
