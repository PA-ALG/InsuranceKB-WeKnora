---
name: 切片任务
about: 由 Claude 创建，用户批准后交给 Codex 实现
title: "SN "
labels: []
---

**[by Claude Code]**

## 目标

一两句话说明本切片要达成什么。

## 依据

- Spec：`docs/design/slices/SN-*.md`
- 蓝图相关章节：`jlx_enterprise_llm_wiki_technical_blueprint_1001.md` §

## 分支与工作目录

- 分支：`slice/sN`（验收测试已在该分支上）
- 工作目录：`.worktrees/sN`（Claude 已建好并装好依赖）。只在这里改代码、跑门禁，不切换主目录分支

## 改动范围

以 Spec 中"改动范围"一节为准。

## 完成标准

- [ ] 验收测试全过
- [ ] 架构守卫全过，基线不回升
- [ ] 受影响组件的完整门禁相对 S0 失败清单不新增失败（Go / Harness / 前端，按 Spec 列出的命令）
- [ ] GitHub Actions 全绿（仓库 Actions 启用后适用；未启用前以本地门禁为准）
- [ ] 未修改受保护路径
- [ ] 已把最新 `main` merge 进本分支（不 rebase），PR 按模板写全

## 开工方式

写完计划即开工 / 等确认再开工（二选一，删掉另一个）。

在本 Issue 下回复一条评论：复述目标、改动范围与完成标准，并列出实施计划。

- 写完计划即开工：发出评论后直接开始，Claude 异步查看，有偏差会叫停。
- 等确认再开工：Claude 或用户在本 Issue 中确认后再开始（Claude 每 30 分钟巡检，通常在下一轮内答复）。

## 真实调用与环境预算

不需要 / 场景数 N、发送上限 N、模型、材料范围；镜像构建、部署、数据库迁移另列。用户批准本 Issue 即授权此预算。

## 批准

- [ ] 用户已批准（用户把本 Issue 交给 Codex，即视为批准）
