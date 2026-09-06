# G2 共享定义与开放知识 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 总控独占提交；实施者不commit。

**Goal:** 共享定义由真实字段链接并同版动态聚合，首批模型发现通过独立审核进入实体free_wiki，沿同一WeKnora发布和来源链可用。

**Architecture:** 新版本领域CompileRequest/CandidateBundle与独立review输入输出；同一Release JSONB存结构化成员，Content确定性派生；G1旧合同继续读。共享定义自身hash不含聚合，聚合只在一次固定Release上计算。无新服务、新表或Harness在线Head。

**Tech Stack:** Python3.12/Pydantic、Go/Gin/现有Release repository、Vue3、pytest/Go test/Vitest；D2复用BA0唯一构建入口。

## 执行边界

base、worktree、Owner、预算和STOP见G2 execution；稳定Requirements为OpenSpec128 G2-R1—R6。
唯一下一物理结果是execution中的首演示，不把以下工程步骤各自算作产品进度。
0.5–1.5日切片串行：M1共享定义/真实字段及垃圾拒绝演示；M2完整开放知识初始编译/独立审核及同版消费；M3冻结D2/D3与全卡验收。4–6日整卡，不新增Goal。

### Task 1：冻结输入和协议（M1内的工程步骤）

Files：总控Evidence Pack与本Spec；实施仅两个 `concept_*_830_g2.py`、对应tests与contract vector（精确路径见proposal）。

- [ ] 总控冻结24项Seed Cases（输入、预期处置、source digest、hard gate、60/80边界），真实材料保留原始文件/WeKnora解析身份，不人工重写原文。
- [ ] 独立复核本Spec与计划；先记录无共享定义/非空free_wiki被旧代码拒绝的真实缺口。
- [ ] 实施者写测试并运行RED：定义正文hash不随两个实体字段引用变化；跨Space/无证据/引用漂移/重复身份拒绝；60/79/80及短重要规则；required字段完整尝试/三态。
- [ ] 实现严格frozen模型和独立可替换Compiler/Reviewer Protocol，模板/规则实现及LLM transport适配。LLM transport仅注入现有provider客户端，不在纯合同里建网络/文件/数据库服务。
- [ ] 分别注入至少两个compiler/reviewer实现，断言wire schema不变而独立execution/context/raw identity不同；聚合三态/排序、定义hash preimage、audit不进Members及NEEDS_HUMAN未决规则成为冻结vector断言。
- [ ] CompileRequest必须绑定request id、source集合与locator、Schema/Profile、已有页/实体集合、用途/策略和预算。CandidateBundle包含candidate id/hash、来源与字段处理、开放处置、Claim/Evidence、gap、compiler identity；审核独立request id/context hash/raw output、decision/reasons，不能接受compiler自评分为通过依据。
- [ ] 定义、实体字段、free_wiki规则、concept links为不同结构化对象；已有G1输入只通过只读adapter提取，不修改原模型。聚合按传入的已固定Release集合计算纯结果；不建立存储或Head。
- [ ] 引文来源联合类型区分DOCUMENT与EXPERT_REVISION_RECORD；本卡运行使用已冻结文档/Schema来源，专家记录编辑流程留G5。quote精确；value可保义转换并记录mode。独立审核反例保护数值/否定/条件/例外等，但不宣称语义指标PASS。
- [ ] 运行focused GREEN、ruff/mypy、git diff --check；输出跨语言vector及其hash，经独立只读复核后由总控小提交，再交Task2。不得只交空接口。

Commands（始终用worktree source）：

```sh
PYTHONPATH=harness/src /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python -m pytest harness/tests/test_concept_free_wiki_830_g2.py harness/tests/test_concept_compile_830_g2.py -q
```

### Task 2：同一Draft/Review/Release和可打开页面（M1）

Files：proposal列出的Go types/service/handler、最小dispatch和前端文件；同一实施writer接续，不并行改共享合同。

- [ ] 对冻结vector写Go RED：新variant可解析，tamper/断链/foreign identity/无review provenance失败；旧G1仍严格。
- [ ] 使用 `WikiReleasePreparation.Manifest/Members` 及现有member snapshots保存G2，不创建表。G2 candidate digest从新bundle派生；ReviewDraft与activation都完整复核manifest/来源/审核绑定。
- [ ] Draft入口与旧schema/entity variants严格互斥。继续同一human-admin权限与ReviewDecision签名/CAS，不把独立领域reviewer偷换为平台发布授权。
- [ ] G2 reader current只读一次Head，explicit pin不fallback；definition详情与聚合绑定同一member集合；保留旧Release可读。Content由payload确定性渲染并受digest覆盖。
- [ ] 概念/free-wiki source owner接回既有exact revision/token/source viewer，完整核对source/parse/locator/quote。不能从旧17个field citation任意拼装新authority。
- [ ] 现有UI添加严格G2分支和稳定详情路由，保留FieldAssertion优先点击路径；前端不复制事实。source drawer复用已有组件。
- [ ] 总控在独立runtime上经HTTP送入真实材料生成的候选、读取页面并完成共享定义/两个真实断言链接演示，拒绝垃圾；有界失败按同一指纹只允许一次纠偏。fixture或源码页面不冒充HTTP。
- [ ] 首演示必须实际激活并读取两个隔离Active快照A/B，真实实体集合变化；定义正文hash相等而聚合成员/hash不同，不能只做纯函数单测，也不推迟到G3。

Commands：`go test ./internal/types ./internal/application/service ./internal/handler ./internal/router -run 'G2|EntityPageGraph' -count=1`；frontend定向Vitest/typecheck，实际命令与输出入Evidence。

### Task 3：开放知识真实编译、独立审核和同版消费（M2）

- [ ] 总控冻结真实source/Schema/已有页的输入hash、模型参数和最多4调用预算；Compiler与Reviewer执行分离，raw输出分别追加保存。
- [ ] 24项Seed Cases全量跑原分母，真实材料产生初始编译输出、独立审核和隔离候选；更新/义项/字段/别名/待处理/拒绝各自明示，不强迫每个名词建页。
- [ ] 同版搜索使用现有WikiRelease SearchPinned和member.Content，测试正文专有短语命中且拒绝项不命中。
- [ ] Agent managed Wiki路径走唯一Release pin，query expansion复用同一pin；metadata保留release/epoch/entity/member/evidence身份。普通非managed KB不改；managed失败不得fallback RAW。精确新增接线路径由总控根据Task2接口冻结再派发，不能让实施者越域。
- [ ] 用真实问题证明Wiki/Search/Agent一致与source click；定义、聚合、断言三份provenance/hash分别重算，实际晋级locator/quote=100%。

### Task 4：冻结集成、D2/D3与交接（M3）

- [ ] 全适用focused/integration、OpenSpec strict、前端typecheck通过；独立review冻结commit/tree，BLOCKER闭合。
- [ ] 总控冻结artifact inputs；lookup-before-build，只有affected app/frontend各最多一次miss构建；命中零build。禁止主动清cache或重跑BA0。
- [ ] D3用exact image显式no-build/pull never；完整24/24及真实发布、页面/搜索/Agent/source click验收，production8081/Active不变。
- [ ] Evidence矩阵分别记录software/container/provider/provisioning/local live/GitHub live；FLOW与QUALITY分开。
- [ ] 小提交、远端CI与独立复核按现有章程集成；G2真实PASS或STOP才关闭写域与交接，G3仍待新授权。

### Task 5：60–79整包人工待审，保留真实66（2026-09-06修订）

**Goal:** 将已生成的真实66分候选送到可审Draft，用户确认后沿既有整包签名/发布链继续G2。
**Architecture:** v1不变；v2追加确定性admission，不修改原始模型输出。Draft拟议成员和Active正式成员以既有状态/签名区分。
**Owner:** root写Python/文档/外部；g2_sources唯一Go writer；g2_bundle_review只读。

- [ ] 独立审查上述v2设计，冻结接口后再开始实现。
- [ ] Python RED：v2组装60/66/79待审、80可人工；v1拒66；缺分/<60/REJECT拒绝；raw遗漏contract拒绝；pending集合篡改拒绝。
- [ ] 最小实现HumanReviewCandidateBundle及assemble_human_review_bundle；raw JSON对象与typed dump逐项一致而非Pydantic默认填补；保存v2跨语言fixture。
- [ ] Go RED后接受并重算v2admission；v1不变；同一Draft→human Review→publish路径测试未签名/错误hash不可Ready或Active，source verifier fail closed。
- [ ] 跨语言fixed fixture、真实A四个已存raw边界及focused Python/Go套件通过；独立审查冻结diff，root提交。
- [ ] 登记一次必要app增量构建预算（总3→4，standing合理扩展），先BA0 lookup；只隔离G2升级，不动原库。前端无变动不build。
- [ ] 使用compile003/review002真实产物无新provider调用装配v2，实际HTTP创建Draft，生成可读整包预览及精确candidate hash。
- [ ] 在具体候选可审后请求用户整包决定；继续开发授权不是伪造human receipt。可独立完成B输入准备、负向检查及部署配置准备。
- [ ] 获具名整包确认后才签署已有receipt、隔离发布、同版页面/搜索/Agent/来源回验，随后第二快照与G2剩余验收。

Commands: Python两G2模块pytest；Go `GOMAXPROCS=2 GOCACHE=/private/tmp/codex-go-cache-g2 go test -p2 ./internal/types ./internal/application/service ./internal/handler ./internal/router -run 'G2|EntityPageGraph|HumanBatch' -count=1`。
No new LLM calls to repair the stored66; no quality calibration or lowering thresholds. FLOW与Q0 QUALITY继续分开。


### Task 6：真实PostgreSQL回读与整包发布接线修复

**Goal:** 修复真实Review400的JSONB表示差异，继续已批准A整包的隔离发布，不改变其内容/hash。
**Owner:** 沿Spec中G2专属文件写域；root负责实际PG向量/外部执行，g2_sources实现，g2_bundle_review复核。

- [ ] 冻结并独立复核G2-only存储canonical及member比较方案，保留所有来源/身份/内容硬门。
- [ ] root从真实PG只读生成小型roundtrip vector；记录原实现对无语义变化失败的RED和真实A诊断。
- [ ] 最小实现统一canonical存储摘要；G2专属payload等值；覆盖Create/Review/Activate/source/base/current/pinned。
- [ ] v1/v2 candidate hash兼容及内容/raw/成员/来源篡改负例通过，实际PG序列化向量通过，独立review0。
- [ ] root小提交；先登记exact build head，累计app预算4→5、一次miss构建，前端/docreader/provider0。
- [ ] 仅G2升级，保持已有双public rings，旧失败Draft及私有部分执行回执保留。
- [ ] 同candidate创建新的replacement Draft、核完整内容/新摘要/Head3不变；无需重复用户内容批准。
- [ ] 登记恢复执行plan，复用现有两套独立keys并新鲜签署，Review与Activate分别一次，核实际Head3→4。
- [ ] 同版页面/搜索/Agent/来源验收，继续B第二快照；全卡FLOW仍按实际结果记账。

不改原数据库、旧Draft摘要、candidate/raw/score；不新增质量门或重建服务架构。

Task6回归定位的同域漏接点：`internal/application/service/concept_agent_830_g2.go` G2分支仍用global raw/order比较，交g2_sources仅改为G2 member set比较；同文件G1分支不变。这是既定R6同版Agent消费范围，先独立复核该单点后改码。
