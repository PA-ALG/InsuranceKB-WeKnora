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

CURRENT=UPG-08第三次App尝试失败，BrowserSkill子进程PATH修复已RED→GREEN（130PASS），待独审/提交。原配置恢复，8运行容器身份不变，镜像仍未产出，本轮1/1已消耗、总3次。PR131保持Draft，六组CI问题已只读定位且仍BLOCKED，见ci-failures-4dec9ef.json。NEXT_PHYSICAL_RESULT=升级后旧来源经原生发现与Harness准入到唯一Release的可保留切片。

NEXT=独审并推送此次PATH修复与回执；新制品输入不能沿用旧identity。未自动追加第四次构建，UI/DocReader及真实迁移/部署/业务仍NOT RUN。
