## 2026-09-28 0.8.2 最终交付与本地切换通过（当前）

PR #131 已合入 main@c5beb1afc；可信软件源 d5be03b3b，主干9项远端工作流全部成功。
本轮 App/DocReader各构建1次，UI前两次下载失败后通过已有代理完成第3次构建，Harness复用。
三个最终镜像均绑定完整输入身份；本地入口 http://127.0.0.1:18295 实测 version0.8.2、
commit d5be03b3b2da18d9bdcfb8f32d66e0bc31843a83、DB110，正常登录/静态资源/Harness链路通过。

停写后的五库、文件、配置、C5、可信配置与Redis已备份；在新卷恢复并通过一次原生迁移，
official110/false、enterprise5/false、pg_search0.22.6。原数据库卷未原位升级，旧服务与卷保留。
原数据旧列保持，仅有已审迁移例外；epoch27、members、来源字段、引用权限与696913字节PDF一致。
真实PDF样本上传、原生解析、嵌入、revision/source下载通过；MD错误样本的失败保留，实际embedding
合计2次embedding HTTP200/模型传输重试0（MD后处理失败与内部重试另存），样本只在隔离副本，不形成新业务Release或质量结论。

首次备份在1GiB全表校验时OOM，旧环境自动恢复；其后一次预检把挂载顺序变化误判为漂移，未停服。
失败现场均保留；Redis导出同步错误经原生导出/完整性检查后修正，重新完成一致备份。
有效备份位于工作区tmp/upg-final-backup-20260928-recovery3，旧部分备份原样保留；
私密恢复元数据已持久保存。入口开放后禁止自动倒回旧快照，以免丢失新增数据。
revision内app_commit/app_version未知的既有局限与legacy log非空页未覆盖均明确保留；不推导语义质量或发布验收。

CURRENT=已批准升级交付完成；NEXT=用户正常使用0.8.2，后续产品功能另按既有任务授权。
精确镜像、六维状态、回执SHA、备份及验收边界见 docs/insurance-kb/evidence/830-upgrade/final-delivery-20260928.json。
以下状态均为历史，不覆盖本块。

# 唯一执行队列

## 2026-09-28 本地CI修复验证闭合，等待最终远端复验（历史）

软件源码d5be03b3b/tree e2c8f488已提交，290路径精确冻结独审0BLOCKER。
完整root lint最终exit0/0项、57.981秒，原产品比较基线及规则保持；19不可拆分tag逐行例外
均经独审并保留原字节。非service214项PASS，原3组Go失败修复及来源SHA回归保持。
首轮四包完整本地测试741.06秒结束，无超时：3706PASS/11SKIP/48FAIL事件（含父子测试），
失败由本机fake-IP DNS、Python3.9/用户包污染及旧OSS外网测试触发，原记录保留。
仅3测试文件消除外部依赖、使用隔离Python3.12后，265项恢复验证PASS；48原失败事件及
121指定顶层测试无遗漏，相关安全负例保持。此为已审组合证据，不冒称首轮完整测试PASS。
远端旧2a6为19成功/2失败/5跳过；NEXT=源码锁/证据独审后推同一Draft并跟进新HEAD全部CI，
不得停在“已推送”。原8服务不改，新App构建/provider/原环境切换/merge不执行。
隔离迁移既有e71/442701制品PASS仍独立有效，不能当作后续d5be源码已经部署。
详见root-lint-closure-20260928.json与ci-followup-20260928.json；下方均为历史。

## 2026-09-28 隔离升级及有界源码修复通过，最终CI待闭合（历史）

原App精确配置获用户“授权”后私密恢复，旧版61业务表与epoch27/source/PDF连续性PASS。
目标PG唯一pull与新版App唯一正式迁移PASS：official110/false、enterprise5/false、pg_search0.22.6。
原61表旧列无意外变化，4存储alias只有预期updated_at、21行/216 spans保持，20新表均空。
发布版本、members、来源字段及PDF696913字节/SHA b2ade27c…一致；citation按原生算法
重算各自有效，仅到期时间归一后完整authority相同。比较器首次误判与配置前置STOP均保留。
旧wiki_log_entries6条摘要保持；legacy log页0，非空页改写场景NOT EXERCISED。
两测试App均已停止，原8服务未变；追加构建/provider/切换0。迁移receipt fca2ae6e…绑定
既有e71/442701制品，不代表后续源码修复已运行；完整结果见isolated-restore-20260928.json。

8b121远端最终19成功/2失败/5跳过，dsh真实E2E与deterministic PASS；Go/root lint未闭合。
8路径测试/CI准备修正独审0BLOCKER、14定向PASS；新增独立RED确认替换文件仍绑定旧SHA，
最小生产修复已提交07d0e3e48/tree8eb1c1f2，最终10路径独审0BLOCKER；
19项+4子测试PASS，14定向及mineru PASS，不削弱断言、不扩大lint范围。
source lock已绑定07d0/tree8eb1，verify/report PASS，dfaf报告与18c5逐字一致。
CURRENT=有界源码修复与隔离迁移已分别闭合；NEXT=完成最终证据审查，更新同一Draft并检查CI。
原环境切换、新业务tracer/provider及新可信镜像均NOT RUN，不合并。下方为历史。

## 2026-09-28 Go CI 有界测试准备修订（UPG-08）

远端8b121的失败日志为RED；冻结计划SHA6dd230aa…独审0BLOCKER；8路径写域列于current-slice-paths。
第8路径只分离既有ReplaceFile测试替身，避免446行原文件追加后超过500行，不扩大行为。
continuation_fixture唯一写者、continuation_review只读独审、root唯一集成；独审通过才实施。
此前两lane在计划冻结后终止，本轮接续身份取代旧owner，不覆盖已完成历史审查。
范围仅Linux runner缺失/private/tmp前置、测试KB租户/必需表/文件与revision替身、
有效pinned输入和两条已被既有回归取代的旧error期望。保留原有安全/权限/副作用断言，
不改生产、不扩973lint范围、不跳测试。ReplaceFile旧SHA绑定疑点先独立RED，若证实再审
生产写域；不能用测试替身伪造正确结果。定向测试不代表全包或最终CI通过。

## 文件替换来源摘要修复（UPG-04/08）

非空旧SHA独立RED已证实：替换新bytes后row/allocator/task仍绑定旧SHA，不是fixture问题。
冻结计划eec418da…，新增生产写域knowledge_replace.go及knowledge_util.go（只删除失去唯一调用者的6行wrapper），
复用既有calculateFileHashes，
同一source更新写新SHA，补偿同一旧source快照恢复旧SHA；现有两测试文件补正常/回滚验证。
独审后才实施，不改revision/pin/队列顺序，不追加镜像或live操作。已有e71隔离迁移证据
不冒充包含本修复；最终软件identity另记，完整CI仍待验证。

## 2026-09-28 授权前阻断与已保存结果（历史）

五库恢复PASS；旧App初次容器/正常登录/epoch27读取PASS，完整旧版来源连续性BLOCKED：
release search500，缺少原writable-layer /app/config（DB/文件摘要相同）。测试App已停止，
新增迁移/目标PG pull/provider0。可能含密钥的精确/app/config归档与复制被自动审批拒绝，
用户精确授权问题已提出；脚本0600/0700已强制，等待该项答复，不能绕过。
根lint实际追检报告973项/279路径且8分钟timeout；当前96路径机械修正独审0BLOCKER，
后续仅修本lane触及的9条，不扩写另外234路径。软件/CI/制品/迁移状态分别记账。
CURRENT=独审代码与证据集成、同一Draft更新；NEXT=精确配置授权后恢复验证及剩余CI计划收敛。

## 2026-09-28 用户明确确认隔离恢复（本轮授权与执行历史）

用户在获知新建测试资源及私有配置归档曾被自动审批拒绝后，明确回复“确认”。
本轮授权覆盖计划内隔离资源创建、私有恢复资料归档、备份副本恢复和一次正式升级
迁移验证；不切换原8服务、不接provider网络、不追加App构建、不合并PR。
执行合同为 `/tmp/upg-isolated-migration-20260928/executor-plan.md`；执行者
`isolated_restore_executor`独占新`upg-082-20260928-*`资源及私有执行回执，root独占仓库证据。
任何恢复错误、dirty ledger、未知迁移状态或实际待执行任务均STOP，不重试迁移或修ledger。
启动前发现原数据21条summary pending与3条软删除deleting；原Lite计划正确STOP。
经精确源码和独立复核，冻结修订为新隔离空Redis、关闭housekeeping、保护21行及216 spans，
允许的原生后置变化仅4条local存储alias更新时间、2个sequence及正常登录的auth token插入。
不手工改业务状态，任何超出冻结集合的变化STOP；计划/审查摘要见isolated-restore-20260928.json。

CURRENT=五库隔离恢复PASS；启动前检查发现源/副本同有21条summary pending，待只读归因。
Go历史工具冲突修正后完整lint暴露174项/85路径，先冻结独占机械修复范围，不放宽门禁。
同时核对5bd50ba78最终CI：21项成功、3项失败、5项跳过，
失败为Go检查、root lint与固定dsh E2E。root诊断Go，migration_audit只读诊断dsh，
既有CI写域内的实际修复先确认根因再执行。后续代码变动不得冒充已有e71镜像输入。
NEXT=完成恢复/迁移结果与真实CI缺口的独立复核，更新原Draft；原环境切换保持NOT RUN。
下方为本轮前历史。

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
