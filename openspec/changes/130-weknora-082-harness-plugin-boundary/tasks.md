# 唯一执行队列

## UPG-08 第三次构建反馈修复

本次已授权App尝试在BrowserSkill生命周期子进程找不到pnpm时失败。root唯一写域为
`scripts/build_browserskill.sh`、`harness/tests/test_browserskill_build_830.py`及本OpenSpec/交付证据。
复用已校验的pnpm归档及原构建入口，不安装全局pnpm、不变更依赖锁或组件职责。
先用真实shell子进程复现锁定包管理器不可发现的RED，再将已校验入口暴露给PATH，
验证子进程不会误用宿主pnpm；相关制品合同回归后冻结独审。修复会改变App制品输入，
不得以旧identity或本地fixture冒充修复后的镜像；本次1次预算已消耗，不自动追加整镜像构建。

- [x] A0 核实工作树/规则/基线/设计，保存初始RED。
- [x] A1 冻结模型配置、数据库与旧快照兼容方案；实际迁移/恢复单独记账。
- [x] B1 适配固定上游；旧模型journal/no-retry先RED，再移入公开API运输边界；不恢复旧模块。
- [x] B2 消费原来源/发现/Candidate/Release契约与故障样例，集中修复升级影响。
- [x] C1 四组接缝检查：生命周期、原生操作、发布读取、UI状态；删除被替代内部路径。
- [x] C2 focused Go/Harness/frontend验证、独立冻结身份复核。
- [ ] D1 按组件影响集中构建，记录实际成本/制品身份。
- [ ] D2 验证迁移和恢复，既有授权测试环境交付，真实tracer与source click。
- [ ] D3 精确代码/CI/PR与G4交接，保留未测限制。

CURRENT=D2 BLOCKED：修复e71c72f7d已完成独审并推送PR131；第四次App构建在官方frontend metadata HEAD阶段TLS handshake timeout（10.095880297秒），未编译/无image；本轮追加1/1已用，累计4次，没有第五次。原daemon配置逐字恢复，8容器启动身份不变。六组CI仍BLOCKED，未由本轮网络失败关闭。NEXT_PHYSICAL_RESULT=升级后旧来源经原生发现与Harness准入到唯一Release的可保留切片。

NEXT=先验证并稳定实际daemon registry/代理路径，再安排明确获准的新构建窗口；不自动重复旧失败请求。UI/DocReader、真实迁移/部署/业务仍NOT RUN，详见delivery-attempt-04.json。
