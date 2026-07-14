# 019 规格（验收条件）——Golden release 与质量闸门

## Q1 可移植 release 工具

- Q1.1 汇总逻辑进入 `goldenset` 可测试模块/CLI，不含开发机绝对路径；workspace、dataset root、output 均显式参数；
- Q1.2 per-record 保留实际 annotator_model/created_at，混合标注不得被全局常量覆盖；
- Q1.3 validator 接收 expected product manifest；检查产品齐全、每产品 disputed rate 阈值、每个 extractable 字段三态齐全，非 extractable 不计 missing；
- Q1.4 validator 运行 golden self-eval 并要求 precision/recall/F1/evidence 均为 1.0；发布后目录不可变；
- Q1.5 普通 CI 用最小 fixture 验证成功与各失败分支，不要求真实 13 产品或模型凭据。

## Q2 Baseline artifact

- Q2.1 baseline artifact schema 能记录产品 run manifest、pred、dead-letter、judge-queue/judgements、keypoints 状态和 eval report；未解决数量不得省略；
- Q2.2 baseline artifact 记录 git SHA、schema、model、prompt、template/source profile、golden release hash；fixture 验证缺项时不能批准；
- Q2.3 baseline 可标记 approved，批准记录独立且不可改写，只能新建版本。

## Q3 QualityProfile

- Q3.1 按 field_id 输出 support、value accuracy、tri-state confusion、hallucination rate、evidence accuracy，并绑定 Q2.2 指纹；
- Q3.2 profile 版本化且可验证 golden manifest hash；hash/schema/model/prompt 不匹配视为 stale；
- Q3.3 支持全局回归阈值与字段自动化阈值，判定结果列出每个失败指标和实际值。

## Q4 在线门禁

- Q4.1 `MergePolicy.auto_apply_supersede_low_risk` 默认 false；
- Q4.2 add/enrich/supersede 的自动路径均调用同一 `QualityGate`，不能各自绕过；
- Q4.3 自动资格要求：risk=low、非 pending_judge、profile 匹配且 approved、support/accuracy/hallucination/evidence 达配置阈值；
- Q4.4 默认阈值 support≥10、value_accuracy≥0.98、hallucination_rate≤0.01、evidence_accuracy=1.0；
- Q4.5 risk=high 永不自动发布；profile 缺失/stale/不达标进入 ReviewItem，不丢弃候选；
- Q4.6 回归 gate 失败阻止模型/prompt/template profile 被批准，不影响当前已发布快照。

## Q5 工程

- Q5.1 assembler、profile、gate 纯逻辑全单测；模型调用层使用 replay；
- Q5.2 Ruff、mypy、非 live pytest 全绿；validation-report 只声明确定性软件验收，不宣称真实数据运行完成；
- Q5.3 020 的真实 artifacts 进入后，使用同一 validator/profile API，不存在第二套脚本口径。
