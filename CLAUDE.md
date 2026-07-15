# 项目约定（所有 AI 编码会话自动加载）

本仓库 = 官方 WeKnora fork（零分岔跟随上游）+ 寿险知识 Harness（`harness/`，Python 插件）。你大概率是被派来执行某个 openspec change 或遗留任务的。

## 开工前必读（顺序）

1. `HANDOFF.md` ⓪ 节（当前状态与认领表）
2. 你的任务对应的 `openspec/changes/<NNN>/`（proposal + specs + tasks）
3. `docs/insurance-kb/00-project-overview.md`（5 分钟全景）；深入按 README 索引

## 硬边界（违反 = PR 必拒）

- 保险业务逻辑进 WeKnora 的 Go/Vue 代码 = 0；上游代码原则上不改
- WeKnora API 细节只允许出现在 `harness/src/insurance_harness/adapters/weknora/`
- Harness 永不直读 WeKnora 数据库/队列，只走 REST/MCP
- 无 openspec change 的功能代码不写（SDD）；先写测试（TDD，测试名引用 spec 条款号）
- **AI 会话不执行 git commit/push**（人验收后提交）

## 门禁（交付定义）

```bash
cd harness && uv run ruff check . && uv run mypy src tests && uv run pytest -m "not live and not integration_postgres" -q
```
默认门禁仅运行 deterministic lane。PostgreSQL `integration_postgres` 由 `.github/workflows/harness-ci.yml` 的独立 PostgreSQL 16 job 验证；WeKnora `live` 由 `.github/workflows/harness-live.yml` 的受控手工 workflow 验证，未运行时记为 `NOT RUN`。

全绿才算完成；不许破坏既有测试。uv 在 `/Users/houjing/.local/bin/uv`。

## 复审前自测（治理/安全攸关变更，避免多轮返工）

会被 codex/同伴复审的变更，**送复审前先按 `docs/insurance-kb/21-selftest-before-submit.md` 自测**（提交前 gauntlet + 反复返工问题清单 + 红队配方）：从不变量重设计而非补 if、自派红队 live 复现、逐条自查（身份别绑可变标签、判定别两处推导、构造期校验器要在比较点二次规范化、护栏成对想、别删冗余安全层、fail-closed 默认）。019 因反应式返工被拉扯 7 轮，此为教训固化。

## 高频坑（完整清单见 HANDOFF §五）

- 本机 shell 有 SOCKS 代理变量：新 HTTP 客户端一律 `trust_env=False`；git push 断连解法见 HANDOFF 坑 #9
- 三态语义：unknown ≠ absent_explicitly（"没抽到"≠"不存在"）
- 推理型模型（deepseek-v4-flash/MiniMax-M2.5）返回 reasoning_content：只取 content、max_tokens ≥4096、空正文+length=截断重试
- 批量写操作默认 dry-run，`--apply` 才生效
- >10 万 token 的模型调用任务：先在 HANDOFF 登记预算，用 nohup 脱离会话跑
- 模型配置在 `harness/.env`（gitignore，勿入库勿外泄）

## 收尾义务

勾 tasks.md（含**裁决记录**：你做的任何设计判断及依据）→ validation-report（如适用）→ 更新 HANDOFF.md。多人协作规范见 `docs/insurance-kb/17`、AI 会话协作机制见 `docs/insurance-kb/18`。
