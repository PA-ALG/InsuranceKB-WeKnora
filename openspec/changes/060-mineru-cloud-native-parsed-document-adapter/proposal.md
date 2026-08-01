# 060 · MinerU Native Structured Artifact Retention and Normalization

## 状态

`STABLE CANDIDATE / FINAL REVIEW PENDING / STACKED ON 051+052+053`

## 为什么现在做

051 只允许一个批准的 default parser 与最多一个 bounded upgrade；052 已冻结
MaterialProfile/parser policy，053 已冻结唯一 ParsedDocument/ParseManifest/quality
authority。当前 MinerU Cloud reader 会下载 provider ZIP，却只返回第一个 Markdown
文件与图片，丢弃 ZIP 中 pipeline 原生 `*_content_list.json`。因此即使 provider
已经产出 page/bbox/table 结构，053 也永远看不到，第二次 attempt 无法被确定性
admit 或 fail closed。

MinerU 官方 pipeline output contract（upstream commit
`79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7`，doc blob
`fd6dfe4c0226cb21abd6bf616be1dea26912ab40`）将 pipeline 的
`*_content_list.json` 定义为 reading-order 数组：每个 item 具有 `type`、零基
`page_idx` 与归一化 `bbox`；table item 的
`table_body` 是带 `tr`、`td/th`、`rowspan/colspan` 的原生结构内容。060 只保留并
归一化这一稳定合同，不接受 development-only `content_list_v2.json`、model JSON、
Markdown 或图片作为结构输入。

## 本次薄片

1. effective parser model 必须 exact `pipeline`；ZIP 边界只选择唯一
   `*_content_list.json`，计算 raw SHA-256；缺失、重复、
   Markdown-only 或 schema 错误均 typed fail closed；
2. 将允许字段确定性脱敏为 task-local `mineru-native-structure.v1`：正文只保留
   content digest，保留 page/block/table/cell identity、bbox、row/column/span 与
   structure digest；未知 vendor 字段不进入输出；
3. 通过现有 Go-local `ReadResult` 携带 source/raw/sanitized hash 与 sanitized JSON。MinerU Cloud
   当前不经过 docreader gRPC，因此不修改 proto；
4. Python 薄 adapter 消费 exact sidecar，直接复用 053 DTO、
   `build_parse_manifest` 与 `evaluate_parse_quality`，并 exact 接收
   subject/parser/attempt/snapshot/output-policy/052 resolution；
5. sidecar raw hash 必须同时绑定 053 subject raw artifact，且 adapter 重验
   page/block/table/cell、bbox、header 与完整 occupancy 关系；attempt 必须是
   `2/bounded_upgrade`。required capability 不足、table grid/span
   歧义或 identity 漂移只产生 053 `BLOCK + ReviewItem`，不执行第三次 parser、
   fallback 或 provider call。

## 非目标

- 不调用 MinerU/provider/live，不上传、重解析、部署或读取 credential；
- 不改 DB/migration、queue、parser router、Go ReadResult 之外的 serving runtime；
- 不引入 Paddle/ODL/第三 parser、通用 artifact/parser 平台或 vendor union；
- 不从 Markdown、空 cell、文件名、相邻页或表格视觉外观推断结构；
- 不读取 Golden，不实现模型抽取、Wiki 发布或跨文档融合。

## 停止条件

若实现需要第 13 个路径、migration、通用 API/proto 或第二 runtime，本 change 立即
停止并报告 blocker，不扩大范围。
