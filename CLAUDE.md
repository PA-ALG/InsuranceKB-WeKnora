# 项目约定（所有 AI 编码会话自动加载）

本仓库 = 官方 WeKnora fork（零分岔跟随上游）+ 寿险知识 Harness（`harness/`，Python 插件）。你大概率是被派来执行某个 openspec change 或遗留任务的。

## 项目北极星（所有会话第一优先级）

**Enterprise LLM Wiki 是产品本体与最终知识权威，WeKnora 是企业平台底座，Harness 是知识编译与治理运行时。** 所有任务先读 [`docs/superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md`](docs/superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md)，并在 proposal/tasks/交付说明中写明它推进了哪项 Wiki 核心能力。

- 人和 Agent 默认消费同一 `ReleaseSnapshot`：已发布 Wiki + 同快照 MCP；RAW chunk 仅作证据或明确标注的未编译兜底，不得覆盖 Wiki 结论；
- 生产链只依赖 MiniMax/Qwen/Qwen-VL 级弱模型，通过模板、多 Agent、多次尝试、确定性校验、证据回验和人工审核获得质量；**每个生产 ReleaseSnapshot 必须由该 Space 的授权人最终批准且批准绑定完整 content hash**；强模型只可用于可选离线金标/评测，不得成为生产 fallback、模板/judge 或发布前置；
- WeKnora 内置自动 Wiki 生成在保险 KB 中关闭；语义、页面编译、关系、冲突、版本与发布生命周期由 Enterprise LLM Wiki 编译器负责；
- 直接 WeKnora Wiki UI 生产发布必须经 P-1 release namespace + `active_release_id` CAS；P-1 前只能写 ACL 隔离、禁检索的 staging KB 并由 Harness reader 预览。单发布者、per-slug lock 或 `draft/published` 不能放宽此门禁；
- 模板失效、归属歧义、证据断链、无共识、预算/重试耗尽或质量退化必须告警并停止不安全的候选推进，禁止静默空结果或降级通过；生产 release 从不允许纯自动批准。

## 开工前必读（顺序）

1. `HANDOFF.md` ⓪ 节（当前状态与认领表）
2. `docs/superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md`（产品与架构最高层基准）
3. 你的任务对应的 `openspec/changes/<NNN>/`（proposal + specs + tasks）
4. `docs/insurance-kb/00-project-overview.md`（5 分钟全景）；深入按 README 索引

## 硬边界（违反 = PR 必拒）

- 保险业务逻辑进 WeKnora 的 Go/Vue 代码 = 0；上游代码原则上不改
- WeKnora API 细节只允许出现在 `harness/src/insurance_harness/adapters/weknora/`
- Harness 永不直读 WeKnora 数据库/队列，只走 REST/MCP
- 保险 KB 的知识语义只能经 Claim/Evidence/ChangeSet/ReleaseSnapshot 治理后发布；禁止直接生成或编辑 Wiki 绕过编译器
- 发布代码必须证明 staging 对普通 UI/RAG 不可见、WeKnora active alias 是 serving commit、MCP 核对 alias/批准 hash；P-1 前任何写普通用户可见 Wiki KB 的路径必须 fail closed
- 生产运行时不得引入强模型依赖；任何 fallback 都必须停留在弱模型 Harness + 人工门禁范围内
- **现状警告**：上述强模型边界尚未由运行时硬实现。NS-0 完成前，现有 `claude-session`、gateway judge、DeepSeek/未知或滚动模型 identity、judge fallback 与 `apply-judgements` 不得用于任何生产候选、ChangeSet 或 release；真实生产运行一律 fail closed
- **资产边界**：业务方/项目权利人已确认 `LLM-wiki-black` 为项目方完整著作权资产，可直接审计并选择性迁移；迁移必须记录 source commit/path，经 OpenSpec/TDD 重构和 Golden Slice 验收。`nashsu/llm_wiki`、WeKnora 与其他第三方仍按各自许可证管理，第一方声明不得覆盖第三方代码
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
- 推理型生产弱模型（MiniMax/Qwen 等）若返回 `reasoning_content`：只取 `content`、给足输出预算、空正文+length=截断重试；既有 DeepSeek/Claude judge/fallback 路径目前只是**政策上禁用**，NS-0 完成运行时硬封前不得启动任何真实生产任务
- 批量写操作默认 dry-run，`--apply` 才生效
- >10 万 token 的模型调用任务：除在 HANDOFF 登记预算外，必须同时满足 `NS-RIGHTS=recorded ∧ NS-0=verified ∧ applicable admission=READY`，并取得适用 OpenSpec、授权签名、完整 provenance、不可变 schema/template/model identity、provider probe 和适用的预算硬上限/账本；任一项缺失即零模型 fail closed。MVP 使用自己的 23-source admission，不修改被阻塞的 13 产品 canonical 020 run；`nohup` 不构成授权
- 模型配置在 `harness/.env`（gitignore，勿入库勿外泄）

## 收尾义务

勾 tasks.md（含**裁决记录**：你做的任何设计判断及依据）→ validation-report（如适用）→ 更新 HANDOFF.md。交付说明必须回答“推进了哪项 Enterprise LLM Wiki 能力、失败如何告警、如何保持人/Agent 同快照”。测试按 23 控制板的 A/B/C 风险分级：RED/GREEN 跑精确测试，完整 deterministic 只在 PR ready 与 CI 跑。多人协作规范见 `docs/insurance-kb/17`、AI 会话协作机制见 `docs/insurance-kb/18`。
