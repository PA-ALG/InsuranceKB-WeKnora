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
