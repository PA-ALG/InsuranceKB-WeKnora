# 原生准入预检与成员生成合同（2026-09-24）

## 当前结论

G35-R5/R6 当前软件切片已实现并通过独立源码复核，原先跨策略恢复阻断已通过更窄的上下文方案修正并验证；最终增量独审待完成。DELIVERY NOT RUN，BUSINESS NOT RUN；尚未切换配置、构建或部署，也没有新增模型调用或业务写入。正式运行仍为上一轮37ae768ba制品；Active本轮未新GET，不将历史epoch17当成新实时核验。

## 实现与职责

- `native_admission_preflight` 是原准入责任内的纯模块：校验绑定上下文，仅v2按同source/offered span内唯一逐字引文修正start；原start有效时即使重复引文也保持。concept_refs仅允许唯一canonical_key→definition.member_ref归位，拒绝多义/命名冲突/未知引用。v1仍严格，不做归位。
- 原始响应与归位响应分开保存；RULE回执记录原/归位/context/source/snapshot hash、修改路径/旧新值/原因/命中数、最终strict状态。失败仍有审计，无部分projection；正文、provenance、decisions、成员集合不改，不自动删孤定义或造页。
- 原strict projector继续检查完整合同与R6闭包；随后原PDF geometry负责精确页面定位，成功后才写projection。派生projection artifact升v2，原调用记录不变。共享`exact_quote_occurrences`只负责Unicode精确枚举，字段D原有多命中策略保持；无跨模块私有函数调用。
- v2服务端场景上下文明确独立有用概念/规则以Wiki page承接，definitions是页面引用的术语义项；保留权利义务、对象、时限、条件、例外、公式及演示边界，无固定页数目标。新增版本化member_contract与最小引用样例使准入输入hash改变；旧响应不能冒用新输入身份。v1提示/context保持，v2系统prompt/template/完整配置也保持原字节。

## 验证矩阵

| Requirement | RED | 实现/验证 | 状态 |
|---|---|---|---|
| G35-R5/R6 唯一归位、完整拒绝、raw审计 | stage 3失败：offset/reference无法投影、orphan无预检回执 | stage贯穿既有journal和真实geometry；v1、中文/CRLF/emoji、重复/缺失/外源、篡改context、孤定义、引用碰撞/多sense；原raw不变 | PASS |
| G35-R5/R6 新成员合同身份 | changed_contract旧实现复用旧context，期望1次新请求实际0 | 新context拒绝旧准入输入复用，旧v1不变；此夹具不证明跨策略复用 | PASS |
| G35-R5/R6 派生恢复 | stage RED包含projection新版本断言；沿既有版本选择机制 | 旧projection只截断到discovery，已完成来源/身份/抽取元数据保留；recorded同策略call父/祖先可复用 | PASS（有界软件） |
| G35-R5/R6 同策略最小恢复 | 修改系统prompt使旧已批准配置拒绝，worker恢复测试RED | 撤销系统模板变更；新增说明仅进context。持久worker恢复来源/身份/字段计数不变，6次原生发现/引用记录全部复用，仅新增1次准入 | PASS（本地软件与离线真实请求） |
| P2 真实非空发布、内容质量、18项覆盖与点击 | 尚未重新执行 | 当前孤定义响应仍不可发布；不得由软件测试推导质量 | NOT RUN |

定向测试92 PASS/1 SKIP（v1不适用成员合同变化）；配置/原生运行接线/geometry/回放统计/检查点合同52 PASS，首次共144 PASS；收窄方案新增完整worker恢复1 PASS，最终context定向测试另记，不重复累计。现有Starlette弃用warning保留，不影响结果。ruff PASS；生产六文件mypy PASS。无Go/前端/部署改动，不触发无关构建。

真实raw离线重放：提示变更前原绑定context下5处确定性归位后，完整投影仍报`definition lacks page use`。最终代码对旧context报`native admission context mismatch`；将相同raw对照新context的离线反事实仍只修5处并停在孤定义。后者不是可恢复的新提示响应，没有写回业务。两份回执均保存，不声称本轮raw已可发布。

## 恢复耦合的处理与最终边界

曾离线准备只改准入template ID/prompt SHA的方案：它会改变全templates策略hash，导致旧native_discovery_policy拒绝，3条discovery阶段成功调用不兼容。该配置未应用，已废弃。没有删除global hash检查，也没有新增历史策略兼容平台。

独立设计复核后收窄为：完整旧配置、系统prompt及template身份完全不变，仅新增服务端生成的member_contract上下文。它不是来源/候选可覆盖的文本；context bytes仍决定input/operation hash，完整request仍绑定当前模板。新准入须新响应，发现与引用沿原同策略exact校验复用。

最终离线真实检查：旧完整runtime SHA `624e393d4d98f50d079c8267a44020b9c79632c986184538b2af43158679286e`不变且ProductRuntimeSettings校验PASS，native_discovery_policy逐字相同，3个原请求通过当前配置的请求兼容检查。此检查使用记录的请求字节和已冻结旧配置；持久调用身份另由worker集成测试验证，不将重建的兼容检查对象冒充新的数据库回执。

完整本地持久worker恢复测试：旧输入响应已recorded但准入失败；恢复后source capture、identity、field调用计数不变，原生发现/引用6次不新增且回执全部指向原run，只有1次新admission；新input/operation/request/raw身份吻合。旧v1、未知发送、请求漂移等原校验保持。它证明恢复接线，不证明真实供应商新输出的质量。

NEXT：关闭最终变更独审，冻结当前代码及必要Harness-only交付；复用现有运行配置和APP/UI/DocReader，正常网页恢复原任务，事前冻结剩余调用与失败停止条件。当前未构建/部署/执行真实恢复，R4及完整G3.5仍未完成。私密证据为`insurancekb-private-evidence/g35-preflight-20260924/`；废弃配置方案保留为历史诊断并标明不可部署。
