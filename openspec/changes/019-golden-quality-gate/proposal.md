# 019 · Golden 工具、QualityProfile 与自动发布质量闸门

## 为什么做

002 的代码能力已完成，但 gs-v0.1 只有 11/13；B2/B3/B6/B7 仍是 HANDOFF 中的执行条目。当前弱模型三产品 F1 仅 0.216，而 merge 默认允许部分低风险 supersede 自动应用，离线评测和在线治理没有形成闭环。

## 做什么

1. 把 WIP 汇总逻辑改为可移植、可测试的 release assembler/validator；
2. 定义不可变 baseline artifact/approval 与 QualityProfile；
3. 回归门禁阻止指标退化，自动发布门禁阻止未经证明的字段自动 add/enrich/supersede；
4. 默认关闭 low-risk supersede 自动应用，高风险永远人工审核；
5. 用小型 fixture/replay 验收全部软件能力；真实 gs-v0.1 和 13 产品运行由 020 执行。

## 不做什么

- 不完成两个剩余产品的真实标注或 13 产品真实 baseline（020）；
- 不把模型调用放入普通 CI；CI 使用 replay/固定 artifacts 验证计算与判定；
- 不用单一 micro F1 决定所有字段是否可自动发布；
- 不以补齐 13 产品等同于达到生产准确率。

## 影响面与文件域

- 组件：Golden release/eval、baseline artifacts、knowledge merge gate；
- 硬边界：模型调用仍只经现有网关；真实模型结果不进入普通单元测试；
- Schema/Golden：提供 gs-v0.1 的组装/验证工具，不执行真实发布；不修改现有字段语义，任何评测口径变化必须显式升版；
- 主要文件域：`goldenset/`、baseline/eval scripts、Golden dataset artifacts、`knowledge/models.py`/`merge.py` 的 gate 接口及 tests；
- 与其他 change：portable assembler/实际标注可独立推进；merge gate 必须等待 016 对 knowledge 目录的改造完成。

## 验收故事

用 fixture 组装 release 并验证每条记录保留实际 annotator；从 replay baseline 生成批准报告和字段画像。没有画像或画像未达阈值时，低风险 supersede 也进入审核；加载一个达标的低风险字段画像后仅该字段获得自动资格。候选模型指标退化时 gate 返回可读失败清单。
