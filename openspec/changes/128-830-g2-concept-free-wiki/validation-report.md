# G2 当前验证矩阵（2026-09-07）

当前源码 `99ec069277cf3336962e5fa2ecaafed19e8aad35`，后端制品源码 `d7c67303916e6f608458de4980cf83d807390022`。以下为实际状态；历史“待实现/未执行”记录保留在文末。

| Requirement | 实现与检查 | 实际证据（docs/insurance-kb/evidence/830-g2/） | 状态 |
|---|---|---|---|
| G2-R1 编译/独立审核 | concept_compile_830_g2.py；可替换协议、独立上下文测试通过；A/B真实分离调用 | task1-review-result.json；b-source-compile-execution.json；b-source-review-execution.json；g2-final-software-check.json | PASS |
| G2-R2 定义/聚合 | 实体由1增至2，定义hash保持，关联2增至4，A70成员保持 | a-jsonb-local-live-verification.json；b-local-live-verification.json；b-ui-live-verification.json | PASS |
| G2-R3 准入 | 24/24协议准入回放；12个未准入样本标识/3错误文本实际R5零搜索命中，导航成员无此身份；真实free_wiki进入140成员 | seed-admission-replay.json；seed-admission-review.json；g2-rejected-active-readback.json；b-local-live-verification.json | PASS |
| G2-R4 原文/保留条件 | 原生来源及4引用/3PDF实测通过；B旧ID故障恢复，实际事实仅两处引用ID变动；条件/例外两条完整原文删除反例经独立提取审核拒绝，装配拒绝 | b-source-recovery-native-validation.json；b-source-actual-semantic-delta.json；b-local-live-verification.json；g2-final-preservation-replay.json | PASS |
| G2-R5 发布链 | A R4与B R5两次用户整包批准/服务端Review/Activate；原DB不变 | a-jsonb-local-live-verification.json；b-source-human-explicit-approval.json；b-source-publication-execution.json；b-local-live-verification.json | PASS |
| G2-R6 页面/搜索/Agent | 真实目录、正文、定义4链接、PDF15高亮及正文API搜索通过；最后Agent实际search/read/answer通过，严格SSE回放及11反例经独立复核 | b-ui-live-verification.json；agent-final-flow-verification.json；agent-final-sse-independent-review.json | PASS |

software=PASS（本次42 focused tests、strict OpenSpec、diff）；container health=PASS（冻结制品发布前检查）；provider probe=PASS（真实编译/审核）；provisioning=PASS（双签名ring及隔离scope）；local live=PASS（页面/来源及实际Agent）；GitHub live=NOT RUN。FLOW=PASS，QUALITY=DEFERRED，NOT_FOR_PRODUCTION。最终回执g2-closeout.json；b-local-live内final_agent=NOT_RUN仅表示该历史快照拍摄时尚未运行，现由独立agent-final-flow-verification.json闭合。

24项回放只证明协议/准入，不是24次模型编译发布或专家金标；没有将模型95分替代Q0。保留66/81/95原始分数。UI窄面板PDF局部裁切为backlog，canvas/page15/highlight均实际存在。

## 历史验证阶段（不代表当前状态）

# G2 验证矩阵

所有状态只允许PASS/BLOCKED/NOT RUN；代码结果不推导部署或业务通过。

| Requirement | 实现 | 测试/真实证据 | commit | 状态 |
|---|---|---|---|---|
| G2-R1 | 待实现 | 待编译与独立审核回放及真实链 | 待冻结 | NOT RUN |
| G2-R2 | 待实现 | 待两个真实断言链接/聚合演示 | 待冻结 | NOT RUN |
| G2-R3 | 待实现 | 待24/24 Seed Cases | 待冻结 | NOT RUN |
| G2-R4 | 待实现 | 待来源100%回验及保留条件反例 | 待冻结 | NOT RUN |
| G2-R5 | 待实现 | 待隔离Candidate/Review/Release | 待冻结 | NOT RUN |
| G2-R6 | 待实现 | 待同版正文Search/Agent/source click | 待冻结 | NOT RUN |

G1基线真实输入回放14 pass/0 skip，只证明旧实现可用；G2初始缺口见Evidence Pack。
software/container health/provider probe/provisioning/local live/GitHub live分别记账；目前G2均NOT RUN。
FLOW=NOT RUN，QUALITY=DEFERRED。


2026-09-06：Task1集中修正复审仍为BLOCKED（ENTITY_VERSION_BINDING）。
22 focused tests PASS仅为局部代码事实；Go测试未形成有效RED/GREEN，未集成、未部署。
按28§6 STOP/RETURN_TO_USER，具体identity、剩余修复和资产处置见G2 Evidence Pack中的
stop-entity-version-binding.json。


2026-09-06恢复：用户追加授权后实体版本绑定已闭合，独立复核BLOCKER=0。
离线protocol slice software PASS：25 tests / ruff / mypy；精确5文件SHA和vector见
task1-review-identity.json，结论见task1-review-result.json。本切片关联G2-R1/R2/R3/R4/R5，
但上方全卡Requirement因真实验收未运行仍为NOT RUN；G2-R6尚未实现。
本次HANDOFF/矩阵/执行索引为机械状态更新，免RED；产品代码已有对应RED/GREEN。
