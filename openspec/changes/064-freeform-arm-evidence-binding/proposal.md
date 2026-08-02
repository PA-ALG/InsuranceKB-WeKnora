# 064 · Freeform Arm Evidence Binding

## 状态

`IMPLEMENTATION IN PROGRESS / PROVIDER NOT RUN`

064 是已合入 057 的窄扩展。它让自由文本语义 field output 能绑定一个或多个
exact `ParsedDocumentV1` / `ParseManifestV1` 的 page/block/table/cell locator 与
quote，并生成可确定性重放的 receipt。057 只证明身份、locator、content snapshot
和 quote 的机械闭包；自由文本值是否在语义上正确仍由 061 exact Golden scorer
判断。

## 单一职责

- 输入一个 parser-neutral 自由文本 field output、全部 Evidence 和 exact
  document/manifest pairs；
- 支持同一字段多 Evidence、跨多个 source revision；
- fail closed 校验 source SHA/document/attempt/manifest/page/ref/kind/parent/content/quote；
- 保留 arm-shaped block/table/cell、row/column/header/span 声明，并从 exact
  ParsedDocument 机械重放；
- 生成绑定 field/state/value、全部 Evidence 与每个 document/manifest hash 的
  canonical receipt；
- 同一输入重放得到相同 receipt hash，任一受管字节变化产生不同 hash。

## 非目标

- 不判断自由文本蕴含、事实准确性、冲突或 Golden 结果；
- 不 import 061，不修改 061 scorer；
- 不调用模型、parser、provider、live、DB、PostgreSQL 或 WeKnora；
- 不增加 runner 行为；runner 以后只能做一对一 DTO 转换，不能补 authority；
- 不建立 Evidence registry、规则 DSL、工作流、签名或通用评测平台。

## 路径预算

严格七路径：OpenSpec README、064 proposal/tasks/validation/spec 四件、既有
`evidence_verifier.py` 和既有 057 focused test。需要第八路径或 061 修改即停机。
