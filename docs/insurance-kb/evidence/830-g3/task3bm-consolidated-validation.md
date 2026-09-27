# Task3bm 集中修复：代码验证与部署边界

## 2026-09-18 更新：实际部署及网页复测

下方“部署NOT RUN”为构建前历史记录。63ac9e460统一构建与原环境部署PASS；APP镜像ffa9d18f8753、Harness0e55b9e69894、UI318f53f9f242，无DB迁移或新环境。APP实际构建一次，冷依赖约52分钟；Harness和UI各一次实际构建约6–7分钟。最初系统Python解包参数错误发生在真实构建前，不计为第二次实际构建。完整receipt在/private/tmp/g3-platform-independent-deploy-20260913/task3bm-*。

正常全新产品2648-1三原材料通过网页上传，run faf5182c-4b77-4f82-aa65-8e0178f2d023；密封03:17:50.008552Z至终态03:31:55.422362Z，共845.414秒（2026-09-17）。平台独立完成解析、身份/分类、抽取、编译、自动审核、发布及验后检查；34 verified/34 not_provided/6 extraction_failed，23模型调用（原生13、identity1、field8、discovery1），补抽0。release-70dd8e65-a844-4e7c-97fd-15107cdd3bfb；网页投保范围字段可读，原PDF第12页可见。原文/模型/失败记录保留。未修改/接续运行中的业务结果。

| 阶段 | 网页记录耗时 |
|---|---|
| 接收/解析 | 4秒 / 45秒 |
| 识别/归并 | 0秒 / 32秒 |
| 字段安排/抽取/整理 | 22秒 / 74秒 / 14秒 |
| 独立发现 | 17秒，技术失败，字段发布继续 |
| 编译/提交草稿 | 102秒 / 129秒 |
| 自动审核/发布/验后检查 | 123秒 / 121秒 / 137秒 |

这些为显示层四舍五入且部分边界含调度，不要求加总等于总耗时；精确attempt timestamps保存在task3bm-latest-faf5182c-4b77-4f82-aa65-8e0178f2d023.json。不能写成5～10分钟达标。

后续边界验收未通过：
- 重复网页上传ab0b7d18：原生去重成功、manifest持久；实际生产适配器漏接SHA查询，23个attempt后09-17 04:40:37Z以failed终结，0模型。不是缺失材料本体，也不能宣称增量复用PASS。
- 1835故障恢复051f9096：三阶段复用、provider调用已恢复，1次新身份调用后需确认发行人简称与全名关系，无产品发布。
- 旧发布准备失败的恢复5b737e7d：checkpoint报CHECKPOINT_INVALID，0模型，未发布。
- 自由发现已记录响应为单json代码块，被语义边界拒绝；首次窗口实际发送却offered报告0。已发布partial_success缺少独立发现恢复入口。
- 任务列表上传期间503/30.070秒、空闲时一次200/10.955秒；历史完整审计N+1及活跃轮询造成重复装配。Go准备/审核/激活POST各118–124秒，source authority约41–45秒/次；verify还含75页面/69引用实际串行读取，不能把全部成本归到模型。

上述在Task3bn统一修复。源码测试通过与部署/业务验收分开记，G3整体BLOCKED，QUALITY DEFERRED_TO_Q0，NOT_FOR_PRODUCTION。

## Task3bm 构建前的软件验证（历史）

Owner=root；基线954255a0f7970840965618bde5b117562cfe0a0f；适用OpenSpec129 G3-AUTO-1—6、G3-DISC-1/2。当前为本地代码PASS，部署及本轮业务重验NOT RUN。计划和代码均已独立复核，最终BLOCKER0；不据此宣称G3完成。

| Requirement | 实现与验证 | 状态 |
|---|---|---|
| G3-AUTO-1/3/4 上传去重与恢复 | 上传manifest同事务持久化，SHA+size跨批次原生复用，保留原物理上传绑定；原生失败重解析以代次、确定性任务ID及截止时间约束。Go repository/service/handler/router有界回归、Python manifest/client/stages通过 | PASS |
| G3-AUTO-2 普通字段容错 | 字段与自由发现分离；无效/不通过自由组整体不加入候选，正常字段继续。模型原响应与失败原因保留 | PASS（软件） |
| G3-AUTO-3/4 持久复用及统计 | workflow v3/v5 checkpoint；旧1—4合同不改；真实worker阶段完成及恢复通过。父发现调用通过RULE回放凭据复用，不伪造子run模型调用；真实存储19项通过 | PASS |
| G3-AUTO-5/6 发布来源成本 | 可信父Release同成员来源复用，当前权限/来源版本/撤销照常检查；16项LRU逐出一项。Go回归及离线真实732字段投影通过；438来源引用可复用（17历史来源），137.7ms只是离线投影耗时 | PASS（软件），真实耗时NOT RUN |
| G3-DISC-1 独立发现 | 独立任务/全原文预算窗口/覆盖状态/模型目的/持久候选及最终review；自由组全收或全弃。组合review明确为程序实现，真实模型输入/响应另存并绑定最终hash | PASS（软件） |
| G3-DISC-2 Schema排重 | Schema键、短名称、已知字段页、已有概念名及别名构成排除索引，模型语义判断与服务端同名准入共同执行；unknown/failed字段仍排除，允许链接已有页 | PASS（软件） |

集中验证：Python集成批次70通过、1个runtime drain测试在2秒等待预算内超时；相同代码针对该项重跑1通过（4.12秒）。不得写成原批次71全通过。最终发现/回放/组合/独立发现24通过（39.20秒）；旧wire4、workflow真实worker1（60.13秒）、配置8、前端状态组件36均通过。所有变更Python Ruff和git diff --check通过。Go受影响包有界回归、container编译以及五包vet通过。首次vet自赋值已机械移除并复查通过。

独立复核：恢复/上传Go无BLOCKER；发现原父调用跨run产物问题及计数遗漏已用真实存储反例修复，最终三文件SHA独立核对通过。BACKLOG：同key重解析POST超过截止时间会先拒绝，GET仍能取得原回执；不影响当前恢复路径。普通字段质量、千文件规模/长稳和专门关系图展示不在本次通过结论内。

私有日志与冻结身份：/private/tmp/g3-platform-independent-deploy-20260913/task3bm-review-freeze-final.json；task3bm-python-integration.log。当前未调用真实模型、未新增数据库、未执行业务发布。下一步统一构建受影响APP/Harness/UI并部署既有环境，网页上传2648-1三份未处理PDF；随后重复/增量与故障恢复验收。新产品3个SHA已对租户现有及删除记录核查为0，原文件不改写。
