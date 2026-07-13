# compiler/templates — 模板抽取 Fast Path（change 006）

设计权威：`docs/insurance-kb/11-parsing-templates-multimodal.md` §1（三层模板）、
§2（解析升级链）；`12-dayu-borrowings.md` #1（数字列定位直取）/#2（data_quality）/#4（可喂性）。

## 职责

- **模板 = YAML 数据**（`models.py`/`loader.py`）：字段→锚点（章节标题模式/表格列名/
  正则/页位置）+ few_shots；注册表机制对齐 `schemas/`（fail-fast、内容 hash 版本）；
  发布目录 `dataset/templates/`，运行时只认 `status: published`。
- **归纳器**（`induce.py`，零模型）：族内 ≥2 产品金标（evidence 页码+引文）+ 分页文本 →
  确定性挖锚点 → 全部归纳产品回放验证（values_equal）→ 草案 + 归纳报告（族内命中率）。
  LLM 润色为 claude-session 队列 stub（`polish.py`）。
- **运行时 fast path**（`fastpath.py`）：(family_id, doc) 命中模板 → 锚点定位 →
  确定性抽取 → **既有校验链**（回验/清洗/三态）→ 未命中字段降级通用管道。
- **表格结构 provider**（`tables.py`）：`TableStructureProvider` Protocol；首实现
  pdfplumber；PP-StructureV3 留接口+配置位（`HARNESS_TABLE_PROVIDER`，部署列 HANDOFF ⓪-B）。

## 入口

```bash
# 归纳（零模型）
uv run python -m insurance_harness.compiler.cli induce-template --doc 费率表.pdf \
  --products "产品A,产品B" --golden-root dataset/goldenset/wip-gs-v0.1 \
  --dataset-root dataset/shouxian_product --out-dir out/templates

# 启用 fast path 抽取
uv run python -m insurance_harness.compiler.cli extract <product_dir> \
  --run-dir out/run --templates-dir dataset/templates
```

## 与其他包的关系

- 依赖 `goldenset`（PageText/GoldenRecord/normalize，只读）与 `schemas`（FieldSpec）；
- 被 `compiler/pipeline.py` 调用（extract 节点入口；无注册表时整体旁路，004 行为不变）；
- pred 记录经 `data_quality` 字段（12 #2）与 007 Claim 导入器衔接。
