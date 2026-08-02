# 062 · MinerU exact two-document native cross-page fact falsification

## 状态

`STABLE CANDIDATE / EXTERNAL REVIEW PENDING / PROVIDER NOT AUTHORIZED`

## 用户价值

052 要求条款证明 `cross_page_sections`，费率表证明 `cross_page_tables`。060 只保留
`content_list.json`，官方合同明确它是从 `middle.json` 简化而来的 reading-order
输出，不能承载完整跨页关系。061 已提供一次性、私有、原子 capture custody，但尚未
投影原生跨页事实。本 change 在同一 capture-only Go 路径中，对 exact 两份 PDF 的
MinerU pipeline `middle.json` 做最小白名单投影，确定性回答：原生事实明确存在、明确
未出现，或只有不足以构成关系的原生标志。

## 冻结输入

- MinerU upstream commit `79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c`，版本
  `3.4.4`，backend/model=`pipeline`；配置沿用 061 exact capture config hash；
- 条款 SHA-256
  `88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc`；
- 费率表 SHA-256
  `7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb`；
- 官方 pipeline 在跨页段落/列表合并时写 `cross_page=true`，在被合并块写
  `lines_deleted=true`，但当前 `middle.json` 不保留可复核的 source/target page 与
  node/ref ID。因此两个布尔标志都只是原生 ambiguity observation，不能成为关系。

## 本次薄片

1. capture-only ZIP 边界在分配完整响应前限读 compressed bytes，并验证成员数量、
   大小、路径、重复名、压缩比、regular-file/directory mode 与允许类别；只读取唯一
   `*_middle.json`，保留 raw ZIP/member digest inventory；
2. 只投影 `_backend/_version_name`、page index、结构路径、block/span 类型、
   `cross_page/lines_deleted`；ID 由稳定结构路径做 domain hash，正文、坐标、URL、
   secret、绝对路径均不输出；
3. 任一 `cross_page=true` 或 `lines_deleted=true` 只产生 hashed `AMBIGUOUS`
   observation，`relation_count=0`；无标志为 `ABSENT`；缺少唯一 middle member 为
   typed `NOT_AVAILABLE`。`PRESENT` 仅为未来、经独立验证具备完整显式端点的 vendor
   schema 保留，当前版本不得生成；
4. projection 仅进入 061 私有 evidence JSON，并继续使用原子 no-replace publish。
   它不修改 060 sidecar、052 gate 或任何 production admission。

## 非目标

- 不调用 MinerU/provider/live，不生成真实 capture；
- 不从 content-list、Markdown、相邻页面、重复表头、HTML 或视觉相似度推断关系；
- 不执行 052/053 ADMIT，不改 adapter、DB、migration、WeKnora、Golden、DeepSeek；
- 不引入第二 parser、通用 ZIP/parser 平台或 raw vendor artifact 入 Git。

## 停止条件

若需要第十个路径、公共 DTO/proto、第二 parser、真实 provider，或当前 vendor member
不能在不保留正文的前提下投影，则停止；真实 capture 必须等待 total-control 另行授权。
