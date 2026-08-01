# 060 · MinerU Native Structured Artifact Retention and Normalization tasks

## Task 1: Identity and official contract

- [x] 基于 authoritative main
  `bfa6fe233d08f84b368b51570c1c0302d22ae002` 安全保留旧 Phase 0 文档并 fast-forward；
- [x] 只读核验 MinerU 官方 output contract 与当前 Go reader/ZIP/ReadResult/053
  boundary；
- [x] 冻结唯一输入 `mineru.content-list.pipeline.v1`：唯一
  `*_content_list.json` 顶层 array；common keys=`type,page_idx,bbox`；text key=`text`；
  table keys=`table_body,table_caption,table_footnote,img_path`；
- [x] 明确拒绝 `content_list_v2.json`、model JSON、Markdown-only 与 unknown vendor
  fields；当前 MinerU Cloud 为 Go-local reader，proto 不在生产路径。

## Task 2: RED fixtures and boundary tests

- [x] 添加一份脱敏 native fixture，证明 page/block/table/cell/bbox/stable id 与
  row/column/span；负例在 focused test 中构造 malformed/Markdown-only ZIP；
- [x] RED：当前 ZIP converter 丢弃 native structure，ReadResult 无 raw hash/
  sanitized structure；
- [x] RED：没有 exact sidecar 时 053 bounded-upgrade admission 不可达；malformed/
  Markdown-only/table-grid ambiguity typed fail closed。

## Task 3: Minimal GREEN

- [x] `ReadResult` 增加窄的 immutable native structured sidecar（schema、raw SHA、
  sanitized canonical JSON），不改变 Markdown/image 行为；
- [x] ZIP boundary 只选择唯一 pipeline content-list，验证 page/bbox/stable record
  order 和 native table HTML grid；正文仅留 digest，未知字段不透传；
- [x] task-local Python adapter 直接复用 053 DTO/build/gate；exact 接收 052
  resolution 与全部 identity context，固定 attempt=2；
- [x] complete native grid 可构建 cell row/column/span；缺失/歧义只可 BLOCK +
  ReviewItem，无第三 attempt/fallback/provider call。
- [x] invalid bbox 只保留页级 hash 与 `native_structure_invalid` 观察事实，零无效
  locator；该事实不依赖 MaterialProfile capability，始终 BLOCK + ReviewItem。

## Task 4: Verification and freeze

- [x] focused Go/Python RED→GREEN、受影响 052/053/056 bounded tests；
- [x] Go fmt/test/vet、Ruff、strict mypy、OpenSpec 060 strict、diff-check、exact scope、
  private/secret；
- [x] exact paths ≤12，real index empty，冻结 stable candidate tree/temp-index；
- [x] provider/live/DB/WeKnora/Golden/full 均 `NOT RUN`；不 commit/push/PR。
