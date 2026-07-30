# Mission Card · 047 S0-Q 窄切片知识质量证伪运行

> 日期：2026-07-30
> 用户授权：已确认设计与实施计划，允许开始 S0-Q
> 状态：`AUTHORIZED / PHASE-GATED`

## 业务目标与现在做的理由

S0-R 已证明 WeKnora 可作为单一 Release authority 的实验载体；进入首个 MVP
纵切前，当前唯一剩余主门禁是：真实 WeKnora 解析输入在弱模型条件下能否支撑
寿险知识编译。

本 Mission 不追求质量平台或生产准入，只用两份真实 PDF、一个预置
ProductVersion 与四个字段给出可复现的窄切片证伪结论。

固定顺序：

```text
真实 PDF
→ 当前固定 digest 的 WeKnora 解析
→ W1 exact revision 冻结
→ Harness 弱模型编译与 A–D 诊断
→ S0-Q 结论
```

不得先人工整理 Markdown，也不得在本 Mission 发布 Wiki。

## Owner、身份与交付

- authoritative base：
  `1650f3bb26fd92af554c22f45d7df0a45e29c160`
- 唯一写 Owner：总控 Codex
- branch：`codex/047-s0q-narrow-slice-run`
- 隔离 worktree：
  `.worktrees/047-s0q-narrow-slice-run`
- 执行模型：仓库默认 `gpt-5.6-sol high`
- 预计 PR：1 个 Draft PR
- 预计周期：一个工作日内给出 admitted run 或可核验
  `BLOCKED_ON_INPUT`，不得无限延期
- 独立复审：Plan、Spec、Quality/Delivery 各按 exact head 只读复核

## 固定输入

| 材料 | 仓库路径 | bytes | SHA-256 |
|---|---|---:|---|
| 保险条款 | `dataset/shouxian_product/平安e生保（尊享版）医疗保险/保险条款.pdf` | 1,047,811 | `88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc` |
| 产品说明书 | `dataset/shouxian_product/平安e生保（尊享版）医疗保险/产品说明书.pdf` | 492,101 | `5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279` |

- ProductVersion：`596-1`
- `present A`：`产品特色`
- `typed-present B`：`免赔额`，计划一 CNY 10,000、计划二 CNY 0
- `absent_explicitly`：`保证续保`
- `unknown`：`宽限期`，必须 abstain
- 复杂结构门：保险条款 PDF 第 31 页的合并表格

不得增加第三份材料、第二个 ProductVersion 或第五个字段。

## 依赖与阶段门

1. 使用当前已固定 digest、包含 `80a5003` 能力基线的本地 WeKnora app 与
   docreader。
2. 先通过现有 authenticated admin API 在专用 scratch RAW KB 上传两份 exact
   PDF，读取 W1 revision descriptor 与 exact-attempt chunks。
3. 必须冻结 source、parser/build/chunker、attempt、页码、chunk、表格结构及
   manifest digest；任一关键身份不足即 `BLOCKED_ON_INPUT`。
4. scratch KB 无论成功或失败均按 exact ID 删除，并记录 cleanup evidence。
5. W1 输入 admitted 后，才冻结弱模型 exact identity、prompt/schema digest、
   调用/重试/timeout 与人工 active-time 上限。
6. 正式弱模型链及 feasible 分子强模型调用上限为零。强模型只允许在隔离 B 臂
   使用 exact identity 与有限预算，且不得回馈值、Evidence 或裁决。
7. 输入或模型画像不 admitted 时，禁止 provider；仍须提交失败证据、报告和
   handoff，不能把合法证伪结果留在本地。

## Exact 验收

- 两份 source SHA/bytes 与 Mission Card 一致；
- 两份 W1 bundle 的 exact attempt、page/chunk order、manifest digest 可重算；
- 条款第 31 页复杂表格 anchor 可回验；
- 预置 ProductVersion 和四字段 Seed Golden 完整；
- A–D 分别隔离 candidate region、extraction/model、normalizer/comparator、
  Evidence verifier；
- 每字段保留 fixed-input digest、三态、Evidence、abstention、error bucket、
  人工 actor/reason/active duration；
- 仅全部通过时输出
  `KNOWLEDGE_COMPILATION_FEASIBLE_ON_NARROW_SLICE`；
- 失败不取平均，保留字段及
  `input_integrity | candidate_region | product_version | extraction |
  normalization | comparator | evidence_verifier | abstention`；
- focused tests、Ruff、mypy、OpenSpec strict、diff-check 通过；
- exact head 完成独立 Spec 与 Quality/Delivery review。

## 明确非目标

- Wiki 页面写入、Release/S0-R/P2d/043 实现；
- 数据库 migration、workflow、principal、部署或 Artifact 更新；
- 通用实验平台、模型路由器、Golden 管理系统、第二解析器；
- 人工清洗 Markdown、第二语料、prompt search、provider fallback；
- full、无关 provider/live、PostgreSQL、负载测试；
- legacy 重接线或物理清理；
- 宣称 `QUALITY_APPROVED`、生产准入或 MVP 完成。

## 阻断定义

- W1 不暴露可重算的 parser/build/page/chunk/table/manifest 身份；
- source 或 exact-attempt digest 不一致；
- 只有 rolling 模型别名而无法冻结 immutable identity/attestation；
- 预算或隔离强模型边界不能 fail closed；
- scratch 数据不能安全按 exact ID 清理；
- 发现需要第二语料、第二解析器、migration、Release/Wiki 或通用平台才能继续。

出现阻断即输出并交付 `BLOCKED_ON_INPUT` 及 exact evidence；不得扩大 Mission
绕过。
