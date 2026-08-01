# 056 · Native pdfplumber ParsedDocument Adapter

## 状态

`STACKED ON 053 / NATIVE FACTS + FORMAL BRIDGE GREEN / FROZEN FOR REVIEW`

056 是 051 Child E 的第一个薄片。它把 `pdfplumber` 原生可证明的页、词、表格与
单元格位置事实冻结为 task-local native facts；正式 bridge 直接消费 053 的
`ParsedDocumentV1` / `ParseManifestV1` / ParseQuality contract，并由 053 quality
gate 决定 `ADMIT | ESCALATE | BLOCK`。

## 为什么现在做

052 已冻结 596-1 三类 MaterialProfile 的 required capabilities 与“default parser
+ 最多一次 bounded upgrade”策略。053 exact commit 已作为本分支 stacked base；
056 证明 native/pdfplumber 究竟能提供什么，并防止把 Markdown、word、空 cell
或相邻页推断冒充原生 block/span/cross-page 结构。

## 本阶段范围

- 从调用方已验证的 exact PDF bytes 读取 `pdfplumber` 原生事实；
- 保留 page/bbox/word/table/cell/row/column 的确定性 identity 与 content digest；
- `merged_cells`、`header_hierarchy`、`cross_page_sections`、
  `cross_page_tables` 显式标为 unsupported；
- 原生表格出现空 cell/合并歧义时，保留 table identity/shape 但不把该表的其余
  cell 硬声明为 `1×1`；完整 grid 才输出可证明的 `1×1` cells；
- 缺 bbox 与相邻页不用于推断 span、header 或 continuation；
- 用 task-local fixture 和 RED 固定 053 bridge、身份绑定与质量门失败边界。

## 阶段门

053 exact commit 到达后：

- SHALL 显式接收 subject/parser/attempt/snapshot/output/policy resolution；
- SHALL 直接复用 053 DTO、manifest builder 与 quality evaluator；
- SHALL NOT 复制 053 DTO、C0 hash 或 ParseQuality 实现形成第二合同；
- native capability 不足时 SHALL 由 053 返回 `ESCALATE` 或
  `BLOCK + ReviewItem`，056 不自行调用第二 parser。

## 非目标

- 不读取 Golden，不调用 LLM/provider/live/DB/WeKnora；
- 不修改 parser router、worker/queue、migration 或 052/053 文件；
- 不接 MinerU/OCR/VLM，不做自动 fallback、parser 投票或通用 adapter 平台；
- 不从 Markdown、filename、空 cell 或跨页邻接猜结构。

## 路径预算

本阶段功能范围严格七路径：本 change 四文件、一个 source、一个 focused test、
一个脱敏 fixture。053 合入 main 后，仅另有一条 README registry 状态机械同步，
累计八路径；不改变 056 行或功能范围。第九路径须停机复核。
