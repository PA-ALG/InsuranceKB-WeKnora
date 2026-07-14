# 019 增量设计

权威设计：`docs/insurance-kb/20-enterprise-runtime-foundation.md` §7。

## 软件与数据任务边界

本 change 只负责 portable assembler、release validation、baseline manifest、QualityProfile 与 QualityGate，全部使用小型 fixture/replay 做 TDD。020 负责两个产品的真实标注和 13 产品真实模型运行，使用同一 API 产出 artifacts；真实调用失败不能通过修改测试夹具掩盖。

现有 11 产品不重标。两个新产品的每条记录保留实际 annotator_model；assembler 不覆盖来源字段，只补齐缺省 created_at/schema 并在 manifest 汇总 annotator 集合。

## QualityProfile 指纹

指纹包含 golden manifest hash、schema version、model id、prompt version、template/source profile。任何一项变化都必须重跑或显式重新批准。profile 是只读 artifact；批准动作生成独立 approval record，不修改指标文件。

## Merge 接入

新增纯逻辑 `QualityGate.decide(field_id, risk, action, run_fingerprint)`，返回 eligible/reason/metrics。MergePolicy 的布尔开关只表达“运营是否允许自动化”，不能绕过 Gate。缺画像、stale 或阈值不足统一走现有 ReviewItem。

## 大模型运行

13 产品 baseline 与两产品标注的运行准入、精确模型 ID、预算和断点目录由 020 记录。019 的 validation-report 只报告软件门禁。
