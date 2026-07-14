# 020 运行设计

权威设计：`docs/insurance-kb/20-enterprise-runtime-foundation.md` §7；工具契约：019。

运行分四个可恢复阶段：annotation、release、baseline、adjudication/profile。每阶段产物先写 WIP/run 目录，validator 通过后才进入 immutable release/approval。进程退出或网络失败从 manifest 记录的最后完成单元恢复。

真实模型选择不写成“最强可用”模糊口径：执行前在 `run-admission.md` 固定精确 ID。若模型变更，生成新的 admission revision 和 artifact fingerprint，不混写同一 baseline。

020 是环境约束 change：软件门禁可以绿而真实运行仍 blocked；validation-report 必须分别报告数据覆盖、模型调用、裁决完成度和阻塞原因。
