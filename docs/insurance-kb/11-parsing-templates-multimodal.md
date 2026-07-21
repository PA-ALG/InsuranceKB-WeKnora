# 11 · 解析组件、模板抽取与图表处理

> 回答三个决定抽取上限的问题：① 同构文档（如分红险说明书）如何用模板做专项抽取而不引入大量人工；② 解析/OCR 基础组件怎么选；③ 说明书里的图表怎么处理。
> 关联：[Enterprise LLM Wiki 北极星设计](../superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md)（四级模板与降级硬约束）· [04-extraction-harness.md](04-extraction-harness.md)（完整 TemplatePackage 与通用管道）· [08-tech-selection.md](08-tech-selection.md)（选型总表）· [05-golden-set-eval.md](05-golden-set-eval.md)（一切选择用分数裁决）

> [!CAUTION]
> 004/006 的族级资产只完成历史测试范围，当前仍 production-disabled；项目权利人已确认其第一方来源，可按 06 provenance 选择性迁移。本文描述 028/M2 的产品目标；旧模板、锚点、正则或 prompt 只有经 source path 记录、新接口重构、留出集和人工批准后才能进入 TemplatePackage。

## 1. 产品族 fast path：四级模板体系的专门化层

**范围声明**：本文原有“族识别→模板归纳→fast path”只定义四级模板体系中的 `product-family` 专门化层，是 006 的局部能力，不代表 Enterprise LLM Wiki 的模板注册、选择、治理与告警已经整体交付。

完整层级固定为 `通用保险 → 险种 → 文档类型 → 产品族`。每层都是 [04 §2.3](04-extraction-harness.md) 定义的版本化 `TemplatePackage`，包含 schema、prompt、路由、validator、Evidence 策略、attempt/预算、质量/人工阈值、Alert 策略和 golden slice；运行时按批准版本叠加，后一层不得放松前层安全门禁。

**核心原则**：模板草案尽量由数据归纳，人负责批准；建不建模板由评测分数决定，不由感觉决定。这里的人审只指模板资产批准，不替代每个生产 ReleaseSnapshot 的最终人审。

### 1.1 文档族识别（自动）

同一版式的文档构成一个**文档族**（family），如"分红险产品说明书 2026 版式"。族的识别用**结构指纹**自动聚类：章节标题序列、表格列名集合、版式特征（页眉页脚模式、目录结构）做哈希/相似度。族内文档 ≥3 份才有建模板的价值。eval runner 增加**按族分组出分**——哪个族分数低，一目了然。

### 1.2 模板归纳（离线草案，弱模型生产复用）

下面只是完整 `TemplatePackage` 的 `product-family.routing.fast_path` 片段，不是完整模板：

```yaml
product_family_layer:
  family: par-product-brochure-2026
  extends: [generic-insurance@2, life@4, product-brochure@3]
  routing:
    fast_path:
      - field_id: dividend_distribution
        anchors: {section: "红利分配", regex: "以(现金|增额交清)方式", table_column: null}
        few_shots: [{quote: "…", value: "…"}]
      - field_id: illustrated_rate_basis
        anchors: {section: "利益演示", table_column: "演示利率"}
```

**模板的来源可以是金标与已验证样本的副产品**：每个字段带 (page, quote)，族内多产品同字段的证据上下文模式（所在章节、前后文、表格列）可归纳出锚点。模板草案只允许由确定性统计、生产同档弱模型多 Agent 或人工编写；随后必须经过来源/许可证检查、确定性验证、独立留出集回归和人工批准。可选强模型只可在隔离离线评测中评价冻结候选，不能生成待批准模板、充当模板 judge、成为模板发布或生产运行的前置。

### 1.3 运行时 fast path（模板命中优先，失败回退通用管道）

```
文档 → 通用/险种/文档类型层选择 → 可选产品族识别 → 命中批准族层？
  ├─ 是：锚点定位章节/表格列 → 确定性抽取或单字段弱模型调用 → 引文回验
  │       置信不足/锚点未命中的字段 → 退回上层 TemplatePackage
  └─ 否：继续使用已批准的通用/险种/文档类型层
```

效果：同构文档上削减弱模型调用并提高稳定性。图中的“退回上层”只发生在执行前的 stack 选择；进入运行后的固定失败阶梯是：重切分/重定位 → 定向缺口补抽 → 多弱模型独立尝试 → 通用 schema-driven agentic 路径 → 达到预算/重试上限后停止并产生 Alert + ReviewItem。所有产出仍过统一校验和 release 级人审；禁止强模型 fallback 或静默空结果。

### 1.4 闭环（"定点解决一类问题"的机制化）

按族出分 → 低分族触发“模板归纳”任务 → 人工批准草案 → 留出集/非退化门禁 → 模板版本化上线 → 该族分数回归。**“人工只审核模板草案”仅描述这个模板资产子循环，不取消知识发布的人审。** 004/006 只有历史族级机制证据且当前 production-disabled；MVP 由 028 重构最小 TemplatePackage，完整四级 registry 在 M2 扩展。

## 2. 解析/OCR 基础组件：分层升级链 + 用金标分数做 A/B

2026 年现状（OmniDocBench v1.6）：PaddleOCR-VL-1.6、MinerU2.5-Pro 综合领先；**所有模型中文准确率低于英文**——组件选择必须用我们自己的金标回归验证，不能只看公开榜单。

| 层 | 组件 | 适用 | 状态 |
|---|---|---|---|
| L0 文本层直读 | pdfplumber（现用） | 文本型 PDF（本批样本全部适用） | ✅ 已在 002 |
| L1 版面+表格结构 | **PaddleOCR 3.x / PP-StructureV3**（表格结构识别→HTML/markdown） | 含复杂表格的说明书/费率表；扫描件 OCR | 004/006 只有历史协议地基且 production-disabled；新协议、生产部署与 E2E 须独立 OpenSpec/许可/Golden 验收 |
| L2 复杂版面一体化 | **MinerU 2.5**（08 已选为对照解析器，AGPL 进程隔离） | L0/L1 质量抽检不过关的文档 | 按需启用 |
| L3 VLM 直读 | **Qwen-VL（批准的生产弱模型）**；其他模型只能先做离线 A/B，不能成为 fallback | 图表页、疑难页兜底 | §3 |

机制两条：
- **自动升级链**：每层出口有质量检测（乱码率、字符密度、表格完整性启发式），不达标才升级下一层；每次升级写 RuntimeEvent，所有批准层仍失败时生成 blocking Alert + ReviewItem，禁止把空解析当成功。第一方阈值/规则迁移按 06 记录 provenance 并用独立留出集重新校准；第三方来源继续按许可证隔离；
- **解析器 A/B**：换/升级任何解析组件，跑同一套金标回归看**最终字段分数**变化（不是看解析中间产物），eval runner 天然支持。平台侧 WeKnora docreader 保持不动，本节只管 harness 抽取线。

## 3. 图表处理：按对象类型分流 + 证据风控

说明书中的"图表"实际是三类对象，分开处理：

1. **真表格**（费率表、利益演示表、责任对照表）→ PP-StructureV3 表格结构识别 → markdown 表 → 按字段口径抽取（如费率只抽"典型示例"，原表整体登记为证据）。**分红险利益演示表是模板抽取的最佳场景**：族内列结构一致，模板直接锚定列名。
2. **图形图表**（现金价值曲线、流程图、组织图）→ **caption-first 目标路径**：第一方历史方案可按 provenance 审计，但新 JSON schema、prompt、validator 与测试向量必须经过独立 OpenSpec/留出集；由已批准 Qwen-VL 级弱模型生成候选描述后进入通用管道。图片本身按 master plan P3-3 登记为图片证据；第三方 spec/prompt/实现表达不得未经许可复制。
3. **装饰性图片** → 跳过（VLM 一次分类完成 1/2/3 分流）。

**证据风控规则（硬约束）**：高风险字段（risk_level=high）**不允许只有图形图表证据**——图表数字的 VLM 误读风险高；必须有文本或结构化表格证据佐证，否则该字段标 low confidence 进复核。这条写入 04 校验链。

## 4. 对现有文档/变更的影响

- 08 选型表补三行（PP-StructureV3、qwen-VL 图表通道、解析质量检测）；
- 004/006 的历史族级 enabler 保持隔离、production-disabled，不作为新实现基线；
- 完整四级 TemplatePackage registry/版本/批准/告警/工作台在 028 MVP 后进入 M2；PP-StructureV3 生产部署与 L1 E2E 仍须独立来源/许可验证；
- P3 多模态排期不变，本文 §3 是其 harness 侧的具体设计。
