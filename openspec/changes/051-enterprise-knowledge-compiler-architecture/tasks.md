# 051 · Tasks

## A · 父级架构冻结

- [x] A1 从 authoritative main
  `0f231f9841ab31dde4bad15b958c4cd83c316086` 创建隔离 worktree，并在注册表占用
  051；未触碰 primary checkout。
- [x] A2 核对 Sole Serving Active Release Authority ADR、Amendment 2、033、
  JLX v3、MVP handoff、控制板及现有 047/049/W1/TemplatePackage 事实。
- [x] A3 冻结 SourceRevision/材料/TemplatePackage/解析/抽取/Evidence/融合/
  Release 的父级边界，并明确已有能力与缺口。
- [x] A4 冻结六阶段状态机、typed outcomes、失败零发布、恢复/custody。
- [x] A5 冻结 `A → C → B → {D,E} → F → G` DAG、每个子 Mission 的准入、退出、
  非目标和停止条件。
- [x] A6 冻结 `596-1` 三 PDF/60 字段最终证伪门，明确 047 两 PDF 不满足该门。

## B–G · 后续子 Mission（本 Change 不执行）

- [ ] C 创建独立 OpenSpec：在既有四级 resolver 上补 MaterialProfile→exact
  scope 接缝与 `596-1` approved catalog；fixtures 可开发，但三 PDF admission
  未齐前不得宣称 production complete；C 不依赖 B，从而避免循环。
- [ ] B 在 C 批准后创建独立 OpenSpec：在既有 W1/FrozenW1Bundle 与 exact
  MaterialProfile required capabilities 上补 parser-neutral ParsedDocumentV1、
  ParseManifestV1、ParseQualityDecisionV1；用 deterministic fixtures 校准质量
  阈值，不选择 vendor winner，不新增通用 parser 平台。
- [ ] D 创建独立 OpenSpec：实现材料×模块×字段风险的窄 ExtractionTask、四角色、
  Attempt/Receipt、Evidence 回验与 bounded repair；不得整产品一次抽取。
- [ ] E 创建独立 OpenSpec：实现增量 ChangeSet、字段级 authority、冲突、独占
  来源撤回、Gap/ReviewItem；不得让分类或模型提升 source authority。
- [ ] F 创建独立 OpenSpec：只用冻结 fixture 接通 Candidate→human_batch→
  WeKnora versioned Release→pinned read→revert；不得调用模型或建立 Harness Head。
- [ ] G 创建独立 OpenSpec/Mission Card：固定 `596-1` 三 PDF、60 字段、parser/
  model/prompt/template/budget 与 EvaluationProtocol；输出冻结后才读 Golden，
  完成可证伪评测、具名人工门、Wiki 可见和 revert 演示。

## 文档门禁与交付

- [x] T1 `DO_NOT_TRACK=1 openspec validate 051-enterprise-knowledge-compiler-architecture --strict`。
- [x] T2 运行 diff-check、exact seven-path scope、UTF-8/LF、relative-link、private/
  absolute-path 与 secret 扫描。
- [x] T3 对 exact candidate 做内部 Spec 与 Quality/Delivery/YAGNI 复核，要求
  `BLOCKER=0`、`IMPORTANT=0`。
- [x] T4 用独立 temp index 冻结 stable tree，证明 real index empty、working=
  temp tree、相对 base 严格七路径/all `100644`。
- [ ] T5 等待两路独立审查；本 owner 不 commit/push/建 PR。

## NOT RUN

功能测试、full、provider/model、PostgreSQL、WeKnora live、parser/OCR 实验、
Golden 评分与生产发布均不属于 051。
