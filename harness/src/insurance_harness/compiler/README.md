# compiler

弱模型抽取管道（change 004 实现 04 八步管道的 1~7 步 MVP）。设计权威：
[docs/insurance-kb/04-extraction-harness.md](../../../../docs/insurance-kb/04-extraction-harness.md)、
11 §1.1（文档族指纹）；资产来源：06-asset-migration.md（数据翻译，非代码复制）。

## 模块

| 模块 | 职责 |
|---|---|
| `llm.py` | ModelClient Protocol / ReplayClient / OpenAICompatClient（百炼直连，推理型模型约定）/ LiteLLMClient / CallStats |
| `parsing.py` | 对抗性 JSON 数组解析（002 提升为公共） |
| `verification.py` | evidence quote 归一化回验（确定性幻觉关卡） |
| `routing_data.py` | 7 组 / GROUP_KEYWORDS / 字段→组桥接 / 补漏同义词种子（06 A5/A7/A8 数据翻译） |
| `cleaning.py` | 占位值清洗 30+ 正则（06 A6）；占位 → unknown 三态纪律 |
| `sections.py` | 章节切分（页码映射）/ 组路由（密度阈值）/ 文档族结构指纹 |
| `extract.py` | ≤10 字段分批抽取 + 校验链（回验→清洗→类型）+ 打回 1 次 |
| `gapfill.py` | 定向补漏：aliases 检索候选章节 + 判断题式三态提问 |
| `voting.py` | 高风险字段 3 采样（3 prompt 变体）多数票 |
| `judge.py` | 可插拔裁决：claude-session（judge-queue.jsonl）/ gateway |
| `recall_attribution.py` | 漏抽归因（005 V5，纯确定性零模型）：routing_miss / extract_empty / cleaning_kill；`scripts/eval_005.py report` 出统计 |
| `pipeline.py` | LangGraph 状态图 + SourceDocument boundary + AsyncSqliteSaver checkpoint + source-aware run manifest/pred Evidence |
| `prompts/` | 全部 prompt + `PROMPT_VERSION`（E6.1） |
| `cli.py` | `extract --source weknora` / `extract-replay` / `apply-judgements` |

## 运行

```bash
# 生产：只接受数据库绑定 Space 下的 WeKnora knowledge IDs
uv run python -m insurance_harness.compiler.cli extract --source weknora \
  --space-id <space_id> --knowledge-id <knowledge_id> \
  --parser-fingerprint <parser_version> --product-id <product_id> \
  --product-name <product_name> --run-dir out/<产品>

# 离线/Golden：显式 Directory replay；不会成为生产 fallback
uv run python -m insurance_harness.compiler.cli extract-replay ../dataset/shouxian_product/<产品> \
  --replay-identity <fixture_identity> --parser-fingerprint <parser_version> \
  --run-dir out/replay/<产品>
# 3 产品基线 + 报告
uv run python scripts/baseline_004.py run && uv run python scripts/baseline_004.py report
```

产物：`pred.jsonl`（与 goldenset eval 对齐 + confidence/pending_judge 扩展）、`manifest.json`、
`judge-queue.jsonl`（主会话 Claude 批处理后 `apply-judgements` 回写）、`dead-letters.jsonl`、
`checkpoint.sqlite`（kill 后 `--resume` 续跑）。manifest/source/run/checkpoint identity 在模型调用前核验；
临时原件路径只存在于当前 run context，不进入 checkpoint。产物先写 staging，`manifest.json` 最后提交。

## Source-aware Evidence lineage

- finalize 不信任候选结果里预载的 source/chunk audit；只有候选 quote 通过 PDF 回验且来源与当前 `SourceDocument` 一致时，才从运行时文档重新推导 lineage。
- quote 在规范化后唯一命中 chunk 时写 `lineage_status=linked` 及 `chunk_id`/`chunk_hash`；零命中写 `page_only`，多命中写 `ambiguous`。chunk ID 重复、页码越界或来源不一致均 fail closed，且不得从 chunk 反推页码。
- `pred.jsonl` 的审计矩阵为：legacy 行来源字段全空；未作用域行只允许完整 revision 三元组且不带 knowledge/raw/chunk；作用域行必须成对携带 knowledge/raw identity 与完整 revision；只有 `linked` 行可携带成对的 chunk ID/hash。任何残缺或越界组合都拒绝写入。

这些规则描述 T5 的内存推导与产物落盘合同；Evidence 数据库迁移、持久化和导入仍由 T6 完成。
