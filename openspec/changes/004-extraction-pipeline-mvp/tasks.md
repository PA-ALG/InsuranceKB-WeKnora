# 004 任务

> [!CAUTION]
> **以下 checkbox 仅是历史记录，不是当前可执行任务。** 第一方产物可按 provenance 迁移，但全部保持 production-disabled；只有 027/028 新 OpenSpec 与适用 admission/030 验收通过后，才能在新运行时使用。

- [x] T1 公共模块重构：002 的对抗性 JSON 解析器与 quote 回验抽到 `compiler/` 可复用位置（002 测试不破坏）（E3.1/E3.2）→ `compiler/parsing.py`、`compiler/verification.py`、`compiler/llm.py`（ModelClient/ReplayClient/request_key 提升为公共，goldenset.annotator 保留再导出）
- [x] T2 06 资产代码化：GROUP_KEYWORDS/7 组/字段桥接 → routing_data.py；占位值正则 → cleaning.py（E2.3/E3.3）；字段桥接覆盖 schema v1.1 全部 extractable 字段（单测强制）
- [x] T3 章节切分（页码映射）+ 组路由（E2）→ `compiler/sections.py`；含文档族结构指纹（11 §1.1）
- [x] T4 llm.py 模型接入（litellm 可选 extra + ReplayClient）（提案 §8）；另增 `OpenAICompatClient`（httpx 直连百炼 DashScope，trust_env=False，推理型模型约定：忽略 reasoning_content、max_tokens≥4096、空正文+finish_reason=length 判截断重试）
- [x] T5 分批抽取节点 + 校验链 + 打回流程（E3）→ `compiler/extract.py`
- [x] T6 补漏 pass + 高风险投票（E4）→ `compiler/gapfill.py`、`compiler/voting.py`
- [x] T7 LangGraph 编排 + checkpoint + 死信 + run manifest（E1）→ `compiler/pipeline.py`（langgraph 1.2 + AsyncSqliteSaver，无偏离 08 选型）
- [x] T8 pred 输出 + 真实弱模型基线（deepseek-v4-flash，3 代表产品）+ validation-report.md（E5）；其余 10 产品 `scripts/baseline_004.py run --products …` 一键可跑待业务方触发
- [ ] T9 更新 HANDOFF

状态：T1~T8 完成（2026-07-12）。网关凭据已到位（harness/.env，勿入库），真实基线以 deepseek-v4-flash 跑 3 个代表产品（业务方成本控制指示）；ReplayClient 端到端夹具测试独立覆盖管道逻辑（E5.3）。
设计增量：无独立 design.md，遵循 docs/insurance-kb/04；新增依赖 langgraph + langgraph-checkpoint-sqlite + aiosqlite（08 已选型，无偏离）。

## 实现裁决记录

1. **组路由密度阈值（E2.2）**：源资产 GROUP_KEYWORDS 是 chunk 级单命中过滤；直接照搬到章节级时压缩比 0.5~0.8 达不到 ≤40%。改为密度判定（总命中 ≥ max(4, 字数/400) 且 ≥3 个不同关键词），路由粒度取原子章节（条级），LLM 调用上下文由 build_windows(4K) 二次合并保证 04 的 4~6K 稳定性经验。13 份样本条款标定：最大 0.400、均值 0.323（validation-report 有逐文档表）。
2. **裁决可插拔（08 更新 2026-07-12）**：judge_mode=claude-session（默认）把三票三样/高风险回验二次失败写 run 目录 judge-queue.jsonl，字段标 confidence=low+pending_judge 不阻塞出分，主会话 Claude 批处理后 `compiler.cli apply-judgements` 回写；gateway 模式直连 HARNESS_LLM_MODEL_JUDGE_FALLBACK。
3. **投票多样性来源**：ModelClient Protocol 保持 002 签名（无 temperature 参数），3 采样用 3 个 prompt 变体（直接问/表格式/逐条款式，04 Step 5 原设计）产生多样性，避免破坏 002 接口。
4. **主力弱模型**：deepseek-v4-flash（业务方 2026-07-12 指示；MiniMax-M2.5 为可配置备选，HARNESS_LLM_MODEL_WEAK 切换）。
