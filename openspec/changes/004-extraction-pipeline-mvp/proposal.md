# 004 · 弱模型抽取管道 MVP（S1→S2 核心）

## 为什么做

项目的核心命题是"用 harness 工程弥补弱模型能力，逼近强模型直读效果"（01 §4#1）。002 交付了标尺（金标 + eval runner），003 交付了入口（分类与产品路由），本 change 交付被测对象本身：**文档 → Claim 候选**的抽取管道。交付后即可打通第一条评测闭环：`弱模型抽取结果 vs gs-v0.1 金标 → 字段级 P/R 分数`，此后所有 prompt/策略迭代都有分数可依。

## 做什么（04-extraction-harness.md 八步管道的 1~7 步，第 8 步 extras 延后）

1. `compiler/pipeline.py`：LangGraph 状态图编排（可恢复 checkpoint 落 SQLite/Postgres），节点＝以下各步，节点失败指数退避重试、超限进死信记录；
2. **分段与路由**：章节切分 + 7 组抽取分组 + GROUP_KEYWORDS 关键词过滤（06 资产移植：GROUP_KEYWORDS/分组数据从 LLM-wiki-black 翻译为 `compiler/routing_data.py`，这是 06 清单的首批代码化）；
3. **分批定向抽取**：每次调用 ≤10 字段 × 相关章节，输出 JSON（对抗性解析复用 002 annotator 的解析器，抽公共模块）；
4. **确定性校验链**：evidence quote 回验（复用 002 verify 逻辑）→ Pydantic 类型/枚举校验 → 占位值清洗（06 资产：30+ 正则翻译为 `compiler/cleaning.py`）；失败字段打回重抽 1 次，再失败标 unknown；
5. **定向补漏**：对 null/unknown 的 extractable 字段，用字段 aliases 同义词检索候选章节，改判断题式二次提问；三态输出；
6. **高风险字段自一致性投票**：risk_level=high 字段 3 次采样多数票，分歧标低置信；
7. **置信度分级**：每条 Claim 候选带 confidence（quote 回验通过 + 投票一致 = high；补漏得出 = medium；其余 low），输出 JSONL（与 eval runner 的 pred 格式对齐）；
8. **模型接入**：`compiler/llm.py` 统一走 002 的 model_client Protocol；生产配置 litellm→new-api 网关（qwen/minimax/DeepSeek 通道），测试用 ReplayClient 夹具。

9. **文档族指纹与按族出分**（11-parsing-templates-multimodal.md §1 的低成本 enabler）：章节标题序列结构指纹 → family_id 入 run manifest；validation-report 按族分组出分，为 006 模板归纳提供"该给哪个族建模板"的数据。

## 不做什么

- 不做增量合并/ChangeSet/发布（005）；不写 WeKnora；不做并发批处理调度（P0.5）；extras 候选通道延后；**模板归纳与 fast path、表格结构识别（PP-StructureV3）为 006**（等按族基线分数指路）。

## 验收

- 对 13 个样本产品跑全管道（真实弱模型或录制回放二选一，视网关凭据到位情况），产出 pred JSONL；
- `eval --golden gs-v0.1 --pred …` 出分：报告入 `validation-report.md`，作为弱模型基线 v0（**本 change 不设分数门槛**——首个基线的意义是确立起点，达标线由后续迭代目标定义）；
- 管道中断后从 checkpoint 恢复继续（specs 有断点用例）；全部确定性逻辑单测覆盖，门禁全绿。

## 依赖与待业务方确认

- 依赖：002/003 合入；
- **待确认**：弱模型网关（new-api）的地址与凭据——没有它就只能用录制回放跑通管道逻辑，出不了真实弱模型基线分。请业务方提供 qwen3.6 / minimax2.5 / DeepSeek v4 任一可用通道。
