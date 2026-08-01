# 052 · MaterialProfile → TemplatePackage binding

## 状态

`IMPLEMENTATION IN PROGRESS / FIXTURE-ONLY PRODUCT SLICE`

## 为什么现在做

051 冻结了 `A → C → B → {D,E} → F → G` 的知识编译 DAG。B 需要
先消费一个 exact MaterialProfile，但现有代码只有四级
TemplatePackage resolver，尚没有把已批准 ProductVersion、材料身份、材料角色、
medical Schema 和产品族映射到该 resolver 的薄接缝。

## 本 Change 做什么

- 仅登记 Product `596` / ProductVersion `596-1` 的条款、产品说明书、
  费率表三份 exact PDF path/size/SHA-256；
- 将三份材料确定分类为 `terms | brochure | rate_table`，并为每份
  材料登记后续 B 所需的最小 parser-neutral structure capability 名称；
- 冻结 medical Schema `v1.1+b31a411c621c` 的 exact 60 field-id 双射，
  并对每个字段给出唯一 primary role 与有界 support roles；
- 确保条款级保障责任不被说明书提升或覆盖，费率数值字段只允许
  `rate_table` 为 primary；
- 以 approved ProductVersion mapping 显式绑定产品族，不从文件名、分类模型、
  parser metadata 或相似度推断；
- 直接调用现有 `template_packages.resolve_template`，不修改其核心；
  在薄层记录 exact 四级 requested chain、resolved source chain 和 missing layer；
- 用 C0 `canonical_hash` 冻结 catalog 与每次 resolved binding identity；
- 记录 049 Golden 的 release/artifact/approval 三个身份值，但 resolver
  输入和运行绝不读取 `596.jsonl`、review artifact 或任何 Golden 答案；
- 产品、Schema、source、classification 或 template 身份冲突时 fail closed，
  返回 typed reason 与 MaterialProfile ReviewItem。

## 非目标

- 不实现 B 的 `ParsedDocument` / `ParseManifest` / ParseQuality；
- 不调用 parser、provider 或模型，不修改 Golden，不读取 Golden 答案做路由；
- 不新增数据库、migration、WeKnora 写入、API、worker 或发布能力；
- 不增加第四份材料或扩展到其他 ProductVersion；
- 不建设通用 MaterialProfile/Schema/parser 平台，不改写现有 TemplatePackage
  resolver、content hash 或 approval 语义。

## 路径预算

严格八路径：OpenSpec registry、proposal/tasks/validation/spec 四件、一个
`material_profiles.py`、一个 focused test 和一个 JSON fixture。需要第九路径
时必须停止，不扩面。
