# 057 · Extraction Evidence Verifier and Targeted Repair

## 状态

`IMPLEMENTATION IN PROGRESS / BASED ON MERGED 053 + 054`

057 是 051 Child D2，基于已合入 authoritative main
`b3c4a7c661e5c7a61c82b5bc55e79ad580f928df` 的 053 与 054 exact
contracts。057 直接消费 054 `ReceiptChainV1`/`AttemptReceiptV1`，不复制其
DTO 或 hash 算法，也不因此获得执行、admission 或发布 authority。

## 本 Change 做什么

- 把字段 Evidence 精确绑定 ProductVersion、SourceRevision、parse
  attempt、ParsedDocument/ParseManifest 与 page/block/table/cell locator；
- 回验 locator 类型、page/table 父链、content snapshot、quote snapshot 和
  value snapshot；
- 将引文命中与语义支持分开；主语、条件或产品版本不匹配时
  必须 fail closed；
- 以有界、非插件式代码确定性校验表格数值/单位、枚举、日期、
  范围和算术；只接受边界化的精确值原子，并以明确 absence marker
  区分 `unknown` 与 `absent_explicitly`；
- targeted repair 只能携带失败字段、已批准 locator 与显式一次
  预算；plan 必须完整覆盖全部失败字段，且 initial/current parsed identity
  必须一致；已通过字段不可重试或改写；
- repair 失败或预算耗尽输出 typed Gap 与 ReviewItem，不默认成功。
- 将 verification 的 exact ProductVersion/SourceRevision、ParsedDocument/
  ParseManifest、字段结果与 054 task/receipt 逐项绑定。

## 非目标

- 不读 049 Golden，不调用 LLM judge、provider、live、DB、PostgreSQL
  或 WeKnora；
- 不修改 053/054 路径，不复制或猜测 054 DTO/hash；
- 不实现 Extractor、worker、queue、ChangeSet、Release 或通用规则/
  repair 平台；
- 不从 Markdown 猜结构，不建 parser/model winner。

## 路径预算

严格七路径：OpenSpec registry、proposal/tasks/validation/spec 四件、一个
纯领域模块、一个 focused test。若需要第八路径必须停机重划。
