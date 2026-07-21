# 004 规格（验收条件）

> [!CAUTION]
> **历史验收规格，不再单独授权实现或生产执行。** 路由/清洗属于可迁移第一方资产，强模型路径必须废止；旧测试通过不能解除 027/028/030 门禁。迁移行为须记录 provenance，并由新规格、TDD 与 Golden Slice 决定是否保留。

## E1 编排与可恢复性

- E1.1 管道以 LangGraph 状态图运行，checkpoint 持久化；`extract <product_dir>` 中途 kill 后重跑，从最后完成节点继续（用例：注入一个必失败节点跑到死信，修复后恢复）；
- E1.2 节点级失败：指数退避重试（次数可配），超限记死信（产品/文档/字段组/错误），**不中断其他字段组**；
- E1.3 每次运行记录 run manifest：schema 版本、模型标识、prompt 版本、耗时、调用次数、token 统计。

## E2 分段路由

- E2.1 章节切分保留页码映射（Claim 证据要落页码）；
- E2.2 7 组×GROUP_KEYWORDS 路由：无关章节不进该组的 LLM 调用；对样本条款文档，路由后调用的 (组×章节) 数 ≤ 全量组合的 40%（记录实际压缩比）；
- E2.3 路由数据（分组、关键词、字段→组映射）为独立数据模块，来源标注 06 资产清单，含单测。

## E3 抽取与校验链

- E3.1 单次 LLM 调用 ≤10 字段；输出经对抗性解析（复用 002 解析器抽出的公共模块），解析失败重试 1 次后该批标 unknown+原因；
- E3.2 每个 present 字段必须带 evidence(page+quote)；quote 回验失败 → 打回定向重抽 1 次 → 再失败判 unknown（**不得带着未验证引文出场**）；
- E3.3 占位值清洗：清洗正则命中（"未明确/详见条款/N/A"等）→ 值置空并按补漏流程处理；正则集数据化并单测；
- E3.4 Pydantic 校验：value_type/枚举/日期格式不符 → 同 E3.2 打回流程。

## E4 补漏与投票

- E4.1 补漏 pass 仅针对 extractable 且当前 unknown 的字段；用 aliases 检索候选章节，判断题式提问；仍无线索 → unknown（三态语义与 002 一致）；
- E4.2 risk_level=high 字段 3 采样多数票；三票三样 → confidence=low 并保留三个候选值于 metadata；
- E4.3 投票只对 high 字段发生（成本控制断言：非 high 字段单次采样）。

## E5 输出与评测

- E5.1 输出 pred JSONL 与 002 eval runner 输入格式对齐（含 confidence 扩展字段，eval 忽略未知字段）；
- E5.2 对 13 产品全量跑通并 `eval --golden gs-v0.1` 出分；validation-report.md 含：总分、高风险字段小结、confidence 分层的准确率（验证置信度分级是否有区分度）、死信清单；
- E5.3 ReplayClient 模式下全管道端到端测试（小 schema + 假文档夹具），不依赖真实模型。

## E6 工程

- E6.1 prompt 全部集中 `compiler/prompts/`，带版本号常量；
- E6.2 ruff/mypy/pytest 全绿；新增公共模块（解析器/回验）重构不得破坏 002 既有测试。
