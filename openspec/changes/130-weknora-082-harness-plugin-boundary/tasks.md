# 唯一执行队列

## 2026-09-28 容量恢复后继续既有升级任务

用户已要求继续推进。Colima 数据盘已由 110 扩至 130 GiB，实际可用约 26.8 GiB；
原 8 服务已恢复，容器/镜像/卷保留，CPU/内存/代理配置未变。OnlyOffice 测试容器及
镜像已按用户要求移除，四个数据卷与恢复资料保留。此前“无重启”和低容量仅为历史回执。

CURRENT=最终证据冻结与既有 Draft PR 更新；8组已诊断CI问题的修复代码已独审，
定向验证逐项记账。源码锁844/dfaf校验PASS；全量本地Harness与根Go lint均有界中止，
dsh真实E2E因依赖安装未完成而BLOCKED，最终HEAD远端CI仍须验证，不能宣称全CI通过。
root唯一集成，writer写域已冻结。固定dsh rc.8、不降低style ratchet、不跳过路由断言，
不恢复废弃模型API。UI与DocReader构建/烟测PASS；UI label失配导致exact reuse BLOCKED。

NEXT=独立审查最终证据后更新既有Draft PR并读取精确HEAD CI。隔离恢复资源创建与
敏感配置归档已被自动审批拒绝，用户明确确认尚未收到；收到明确许可后才执行隔离
恢复/迁移，再按各自授权验证tracer。未获许可前恢复/迁移/部署保持NOT RUN。
复用已恢复App镜像；App历史总尝试5、新增预算0。不把容量恢复或烟测写成升级验收。

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

CURRENT=App制品恢复PASS，升级整体仍BLOCKED：第五次构建完成全部编译/OCI导出后在本机解包ENOSPC，原exit1/INCOMPLETE保持；无需第六次构建，已对导出镜像完成22层摘要核对、硬预算0的REUSE及隔离制品smoke PASS。源e71c72f7d、identity12d583e5…、image442701a3…；本轮1/1，总5/余量0。8服务启动身份保持，无人工清理/重启/迁移/部署/provider。烟测后可用1583464KiB。

NEXT=关闭b64923快照的7组CI问题，继续保留Draft；其余制品与交付须满足容量及后续执行授权，不自动追加App构建。UI/DocReader镜像、真实迁移/部署/业务仍NOT RUN；详见delivery-attempt-05.json和ci-failures-b64923.json。NEXT_PHYSICAL_RESULT=升级后旧来源经原生发现与Harness准入到唯一Release的可保留切片。

2026-09-27网络恢复见network-recovery.md/json；2026-09-28第五次真实构建已越过全部网络下载与pnpm子进程，失败在容量，不把本次局部结果外推长期网络稳定。
