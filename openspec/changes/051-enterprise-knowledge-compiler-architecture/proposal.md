# 051 · Enterprise Knowledge Compiler Architecture

## 状态

`SPEC-ONLY / PARENT ARCHITECTURE / IMPLEMENTATION NOT STARTED`

051 是后续 B–G 子 Mission 的唯一父级架构 authority。它不授权功能实现、
provider 调用、数据库或 migration，也不把任何 parser/model 写成生产赢家。

## 为什么现在做

当前项目已经具备 C0 Canonical Envelope、SourceRevision/W1 revision manifest、
FrozenW1Bundle、四级 TemplatePackage 纯领域 resolver、任务运行时、Golden 与
WeKnora sole serving Active Release authority 等地基，但“复杂寿险材料如何被
稳定编译成可验证、可增量维护的知识”仍缺一份贯穿解析、抽取、校验、融合和发布的
父级合同。

若继续用 `pdfplumber → 一个长 prompt → 60 字段` 作为生产主链，复杂表格、跨页
结构、弱模型漏字段、来源冲突与后续材料补全会被混在一次不可恢复的调用中。该路径
只保留为 baseline/simple fast path，不是生产主链。

## 本 Change 冻结什么

1. SourceRevision、产品版本与材料身份；
2. 材料分类、MaterialProfile 与字段级 source authority；
3. 通用保险→险种→材料类型→产品族四级 TemplatePackage；
4. 显式、有界的解析质量路径，以及 parser-neutral ParsedDocument、
   ParseManifest 与 ParseQualityDecision 的最小能力边界；
5. 材料×模块×字段风险的 ExtractionTask/Attempt/Receipt，及 Locator、Extractor、
   Deterministic Verifier、Targeted Repairer 四个固定角色；
6. Evidence 与业务规则回验、有界修复、增量 ChangeSet、冲突、独占来源撤回和
   ReviewItem；
7. CandidateRelease、具名人工批准、版本化 Wiki Release 与 revert；
8. 六阶段状态机、typed outcomes、失败零发布、恢复与 custody；
9. `A → C → B → {D,E} → F → G` 的正式 DAG 与子 Mission 准入条件；
10. ProductVersion `596-1`、条款/说明书/费率表三 PDF、60 字段 Golden 的最终
    可证伪门。

## 核心裁决

- C0 CanonicalEnvelope/artifact hash 是外层唯一 custody/identity authority；
  TemplatePackage `content_hash`、ParseManifest digest 等只是 envelope 内的领域
  content digest，不形成第二批准 authority。
- `product_family_id` 只能来自已批准 ProductVersion resolution 或
  MaterialProfile 显式映射；模型、文件名和 parser 不得推断。
- TemplatePackage 缺层时，只能沿当前 resolver 的显式、已批准 broader chain
  退层，并在 resolved receipt 记录 missing layer 与 exact chain；不得跨 Space、
  ProductVersion 或未批准版本猜测。
- ParseQuality 只在父级冻结 required facts 与 typed reason-code families；未经
  样本验证的数值阈值由 B 子 Mission 使用 `596-1` fixtures 校准并版本化。
- 每个 MaterialProfile 精确选择一个 approved default parser，并最多选择一个
  approved bounded upgrade；第二次仍不足即 fail closed + ReviewItem，禁止第三次
  parser attempt 或 structure→OCR→VLM 顺序链。native/pdfplumber、MinerU、
  Paddle、Unlimited-OCR、VLM 等只是在 G 中可替换评测的候选族，不是预授权阶梯。
- DeepSeek 或其他弱模型只执行窄语义任务，不解析 PDF，不一次生成整产品知识。
- 047 的两 PDF read-only evidence capture 不能冒充三 PDF admission。只有条款、
  说明书、费率表各自具有 exact admitted ParsedDocument/ParseManifest，才满足 G
  的输入门。
- 模型/parser 实验只允许在 G；两臂或候选输出必须先冻结，再读取 Golden 评分，
  禁止看 Golden 调 prompt、模板、阈值或路由。

## 复用而不重写

- 复用 C0、SourceRevision/W1 manifest/FrozenW1Bundle、P1/P3 运行地基；
- 复用现有四级 TemplatePackage resolver、content hash 与 approval 语义；
- Dayu 只迁移“缩小模型战场”、task/Host、阶段制品、typed audit、确定性直取与
  定点 repair 等机制；
- LLM-wiki-black 只迁移材料/模块路由、字段聚合、来源/缺口、增量冲突/撤回等
  第一方能力，并在子 PR 记录 source commit/path 与 characterization tests；
- 不部署第二套 TypeScript runtime，不建设通用 Agent 平台。

## 非目标

- 不写 parser adapter、API、schema、migration、任务 worker 或发布代码；
- 不调用模型/provider，不接 MinerU/Unlimited-OCR，不选择永久 parser/model；
- 不建设动态自动路由、并行 parser 投票、通用 OCR/表格平台或多 Agent 平台；
- 不扩到更多产品、全量 Schema、Dashboard、自动 prompt 生成或生产发布；
- 不修改 Golden，不用 Golden 调参，不把历史指标当当前验收；
- 不重开 WeKnora sole serving Active Release authority，也不恢复双 Active 投影。

## 路径预算

本父 change 严格七路径：OpenSpec registry、proposal/tasks/validation/spec 四件、
父级 architecture spec 与 implementation plan。若需要第八路径，必须停止并重新
取授权。
