# 093 · Cross-page authority compatibility replay

## Why

089、086 与 090 由三个独立任务冻结。它们分别负责 native marker provenance、
derived relation binding 与 060 injection，但当前没有一个可重复执行的契约门证明
三段字段、hash preimage、source role、endpoint/page、relation kind 与 policy
identity 可以逐项衔接。091/092 在消费这些 authority 前需要一个窄而诚实的兼容结论。

## What changes

- 新增一个 596-1 task-local、纯 bytes/DTO 的兼容验证器。
- 内置两份脱敏 synthetic replay vector：terms section 与 rate-table continuation。
- 对 089→086 与 086→090 两条边界分别输出 `COMPATIBLE` 或 typed `BLOCKED`，
  总结果只可能是 `COMPATIBILITY_VERIFIED` 或 `BLOCKED`。
- 冻结一份091/092可直接引用的最小兼容矩阵及唯一最小修正归属。

## Current evidence boundary

静态冻结接口显示当前链尚不兼容：089刻意不输出endpoint/relation；086依赖的
`future-089` test authority却输出endpoint。086输出的nested endpoint与
`table|section` kind也未实现090 Protocol要求的continuation kind、parser build、
material-policy/replay context和injection binding hash。093只证明并定位这些缺口，
不在本任务内制造转换authority。

## Non-goals

- 不修改089/086/090/084/087实现或全局schema。
- 不解析raw capture，不生成relation，不执行ADMIT/READY。
- 不调用provider/model/Golden/DB/WeKnora/live/full。
- 不建设通用跨语言schema registry、代码生成器或兼容平台。
