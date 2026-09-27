# WeKnora 0.8.2 升级与 Harness 插件边界

用户2026-09-27已批准并启动执行，root为唯一集成Owner。沿已审设计执行，不再次申请已给授权。基线8ccc2ac942df7572499ac7b25e14587c594918db，上游固定3e8b0bfc80b845b2d4b2ed683994748741450a97。

真实初始失败已先保存于 docs/insurance-kb/evidence/830-upgrade/initial-red.json：固定上游不是产品祖先，模拟合并38处冲突；旧模型发送记账补丁所在文件被上游删除，原合同不能靠机械取上游保留。新增升级规格承载版本迁移，不改变既有Release/来源/权限合同。

## Mission 与写域

目标：在现有隔离树完成固定上游升级、四组接缝的必要适配与真实链路验证，交接G4。预计一个集成PR；按可验证切片推进，升级耗时不由冲突数推算。root使用当前任务模型配置，冻结身份独审使用项目指定高风险审查档。

写域总范围（下述exclusive lane优先）：固定上游差异所涉及路径（按git diff 80a5003..3e8b0bfc识别）与该差异直接影响的产品Go/Harness/frontend合同、测试、迁移/构建脚本；本规格、升级计划、升级证据、HANDOFF。首切片：模型api运输/重试、平台接线、迁移入口及既有来源/Release回归；写域扩展先在任务记录冻结，不并行写核心模块。

非目标：G4、逐case模型优化、第二服务/数据库/队列/发布权威、通用插件加载器、全部历史重解析、历史实验整包集成。STOP：改变单一Release/当前ACL/不可变来源合同、需要大规模重写、新外发目的地/破坏性数据操作/生产切换尚未授权。仅此类外部动作在准备完成后集中申请，其他授权工作继续。

资产：KEEP Harness领域/JobStore/Outbox、SourceRevision、Release/审核/当前ACL与已发布epoch27；REWIRE 平台原生发现接线和模型发送记账至新API；SUPERSEDE 被上游替代的旧chat/embedding内部实现；FREEZE G3.5质量证据和旧审计数据。质量仍PARTIAL，非空多窗口live不扩大为本轮强制优化。

当前互斥Owner：root独占Go核心/Harness/文档（排除以下独占写域）；frontend_upgrade独占frontend/**（含冲突、依赖与验证）；migration_audit独占current-slice-paths.json中migration_exclusive_lane路径。plan_review转为build_exclusive_lane实现者，独占该清单构建文件，后续不得审核自己的实现；root不并发修改这些lane文件，仅接收冻结结果并集成。conflict_paths只是冲突清单，不另授予root排他写权。

B1二次互斥分工：frontend实现已交付暂存，frontend_upgrade现只写model_fallback_exclusive_lane；root继续Agent隔离，新的独立xhigh reviewer复核迁移与后续冻结代码。历史review identity不自动覆盖本次修复。

集成身份：GOAL_ID=830-UPSTREAM-PLUGIN-BOUNDARY；NEXT_PHYSICAL_RESULT=升级后旧来源经原生发现与Harness准入到唯一Release的可保留切片。当前root接管已交付的写域；所有writer已冻结，独立复核0BLOCKER，详细身份以evidence为准。
