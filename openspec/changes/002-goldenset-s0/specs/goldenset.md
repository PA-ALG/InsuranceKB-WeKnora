# 002 规格（验收条件）

## G1 Schema 注册表加载器

- G1.1 `load_schema_registry()` 读取 schema-baseline 全部 YAML（基线 13 + extensions-v1.1），返回按险种组织的运行时 schema；字段含元属性（field_id/value_type/extractable/allowed_sources/risk_level，缺省按 07 §2 默认规则补齐）；
- G1.2 未知险种/重复字段名/YAML 格式错误在加载期报错（fail fast），错误信息含文件与字段定位；
- G1.3 schema 有版本号（内容 hash + 语义版本），标注与评估结果均记录所用 schema 版本。

## G2 金标注 Agent

- G2.1 输入一个产品目录（PDF×3 + meta），输出该产品的金标 JSONL；每条记录：product_id、doc、field_id、value、tri_state（present/absent_explicitly/unknown）、evidence[{page, quote}]、annotator_model、schema_version、created_at；
- G2.2 present 记录必须有 ≥1 条 evidence；quote 回原文校验（页文本包含 quote，允许空白归一化）失败 → 该记录标 `disputed=true` 并记原因，不得静默通过；
- G2.3 absent_explicitly 必须给出依据引文（如免责条款明确排除）；找不到任何线索的字段判 unknown；
- G2.4 与 product_meta.json 可比对字段（planCode/versionNo/备案文号/销售状态/生效日期）自动 diff：不一致 → disputed；
- G2.5 断点续跑：按产品×文档粒度缓存，重跑跳过已完成且 schema 版本未变的部分；
- G2.6 模型调用经统一网关配置（settings），失败指数退避重试；单文档超预算（可配 token 上限）时分章节标注。

## G3 金标数据管理

- G3.1 `dataset/goldenset/gs-v0.1/` 含：per-product JSONL + manifest.json（产品清单、schema 版本、模型版本、统计、disputed 计数）；
- G3.2 金标 release 不可变：重新标注产出新版本目录，manifest 记录 diff 摘要；
- G3.3 disputed 记录单独导出清单（未来人工复核入口）。

## G4 Eval Runner

- G4.1 CLI：`uv run python -m insurance_harness.goldenset.eval --golden gs-v0.1 --pred <pred.jsonl> --report out.md`；
- G4.2 指标：字段级 Precision/Recall/F1（按 05 §5 口径：值等价判定含归一化——日期/金额/枚举）、三态混淆矩阵、evidence 准确率、幻觉率；高风险字段（risk_level=high）单独小结；
- G4.3 自洽性：`--pred` 给金标自身时各项指标为 1.0/全对角矩阵；
- G4.4 报告含逐字段错误明细（产品、字段、金标值 vs 预测值、证据对照），供 harness 调试。

## G5 工程

- G5.1 全部纯逻辑（加载器、回验、指标计算、归一化）有单元测试，不依赖真实模型；模型调用层用录制夹具测试；
- G5.2 ruff/mypy/pytest 全绿，CI 覆盖。
