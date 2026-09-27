# 唯一执行队列

- [x] A0 核实工作树/规则/基线/设计，保存初始RED。
- [x] A1 冻结模型配置、数据库与旧快照兼容方案；实际迁移/恢复单独记账。
- [x] B1 适配固定上游；旧模型journal/no-retry先RED，再移入公开API运输边界；不恢复旧模块。
- [x] B2 消费原来源/发现/Candidate/Release契约与故障样例，集中修复升级影响。
- [x] C1 四组接缝检查：生命周期、原生操作、发布读取、UI状态；删除被替代内部路径。
- [x] C2 focused Go/Harness/frontend验证、独立冻结身份复核。
- [ ] D1 按组件影响集中构建，记录实际成本/制品身份。
- [ ] D2 验证迁移和恢复，既有授权测试环境交付，真实tracer与source click。
- [ ] D3 精确代码/CI/PR与G4交接，保留未测限制。

CURRENT=D1 制品交付BLOCKED：App一次构建因Colima磁盘不足失败（无镜像），UI/DocReader尚未构建；软件8a0863fa0及最终独审通过。push另被自动审批拒绝，未执行。NEXT_PHYSICAL_RESULT=升级后旧来源经原生发现与Harness准入到唯一Release的可保留切片。

空间恢复候选与精确失败回执已准备；镜像/cache/卷无删除，构建无重试。须先获得具体清理/一次恢复构建及推送授权，再继续既有队列。真实迁移/部署/业务仍NOT RUN。
