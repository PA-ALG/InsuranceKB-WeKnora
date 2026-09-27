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

CURRENT=D2制品交付BLOCKED：软件8a0863fa0及最终独审通过；首次App构建因磁盘不足失败，已授权32镜像清理完成后，独立容量复核通过。唯一追加App恢复构建因镜像源EOF失败，未进入编译、无镜像；新增预算1/1已使用，不自动重试。UI/DocReader尚未构建。NEXT_PHYSICAL_RESULT=升级后旧来源经原生发现与Harness准入到唯一Release的可保留切片。

32个已授权镜像已删除，容器/cache/卷保留，数据盘约6.63GiB可用。push/Draft PR已明确授权；普通上传HTTP400/408（直连也408）后，复用fork已有固定上游对象，将同一分支从3e8b0bfc普通快进到f3ff602b9成功；待补推本次机械证据并建Draft PR。真实迁移/部署/业务仍NOT RUN。详见delivery-attempt-02.json及recovery-authorization.md。
