# 原生准入预检与成员生成合同（2026-09-24）

## 当前结论

G35-R5/R6 预检源码已独审0 BLOCKER并提交d8d99b85f38eb4af063f349404a0c509bb7e51b9；Harness-only一次构建/部署PASS，完整配置及APP/UI/DocReader保持。一次正常UI恢复新增模型0，字段完成发布到epoch18，但复用了旧的FAILED discovery_summary，没有实际重做准入；自由发现BUSINESS BLOCKED。后续失败选择修复已离线验证并独审通过，未部署；另一个已关闭有限窗口实际新增准入1、复用8，仍因quote及来源段合同失败，字段到epoch19。不得将字段发布当作非空自由发现验收。

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

## 实际交付与恢复结果（14:54Z观测）

- Harness d8d99b85f一次构建PASS，镜像sha256:ed95cb8b171c0bb2ca491966240e5bc32c723e04f93ba7b22ac7efa4092526f5；14:47:38–14:47:51Z API/worker可逆切换PASS。容器03f36f8e2e57/743799e628f3；旧容器保留。APP/UI仍37ae768ba，DocReader460c664cf，runtime SHA624e393d…不变，无migration。GitHub live NOT RUN。
- 正常UI恢复parent33dd1349一次，child16452cbb-aec3-509a-893c-ba87b7ecd001，14:48:06–14:50:56Z。新field/stage model calls均0，显示复用9；字段26 verified/51 not_provided/2失败，Schema质量仍未完成。
- checkpoint后直接compilation/preparation/review/publish/verify，全阶段job succeeded；任务PARTIAL_SUCCESS，自由发现FAILED、accepted0、published0。14:54:08Z GET唯一Active为epoch18/release-1db721be-748e-472b-a9f0-508afa98951e。这是字段发布，不是准入、非空自由知识或完整覆盖PASS。
- 原因：父任务在discovery阶段已产生FAILED summary/partial_success settlement，后来compilation因租约失败使顶层FAILED；checkpoint_store只在PARTIAL_SUCCESS查失败摘要，故跳过重做发现。原worker测试只有PARTIAL_SUCCESS，未覆盖这个组合。
- 一次UI窗口关闭，不重复该动作；新增模型0。原raw及记录保持，最新子任务的只读恢复计划明确resume=discovery、保留uploads/source/routing/identity/field_plan/extract/synthesis和9次调用。后续可复用当前部署验证，不必重复构建；必须另冻结有限窗口与epoch18基线。

下一步在原checkpoint模块补最早失效边界，先Spec/worker故障RED，再有界验证/独审。真实准入、最终审核非空成员、精确原文点击/模型生成标志、18项质量覆盖仍未验收；R4及完整G3.5未完成。私密交付及本窗口证据为`insurancekb-private-evidence/g35-preflight-delivery-20260924/`，软件证据为`insurancekb-private-evidence/g35-preflight-20260924/`；废弃配置不可部署。

## 恢复选择修复（软件PASS，尚未部署）

既有checkpoint_store现在对所有可恢复workflow3终态检查partial_success阶段的绑定FAILED摘要，按最早失效边界恢复；顶层后续FAILED不再遮蔽发现失败。更早版本/输出失效优先，不向后越过；PENDING/REJECTED不触发重算。健康succeeded阶段仍仅读metadata。原proof、stage/job代次、来源/请求/raw校验以及unknown阻断不变，无新模块/表/协议。

先Spec，再真实持久worker注入“旧准入失败后compilation失败”RED 1；metadata RED 2。初次扩查产生metadata-only回归4失败，按原有partial_success必要条件前置修复，未放宽测试。42个不同定向测试均获得PASS回执：14 metadata + 4 native runtime（含FAILED/PARTIAL_SUCCESS旧context恢复）+ 20 checkpoint rebase/contract + 4 checkpoint recovery；最后有界复验18 PASS，242.88秒。部分执行重叠，不累计宣称56例。ruff及生产checkpoint_store mypy PASS，已有Starlette弃用warning。独立revision2复核0 BLOCKER/0 BACKLOG；冻结四文件SHA见`g35-checkpoint-review.json`，完整RED/GREEN私密归档`insurancekb-private-evidence/g35-checkpoint-failure-20260924/`。

## 已部署版本的第二个有限业务窗口（15:11Z终态）

只读及独立核验确认child16452cbb的PARTIAL_SUCCESS在现有d8d99镜像已选择discovery、9个recorded调用与79个字段引用完整，因此不为后续效果验证再次build/deploy。关闭第一窗口后，单独冻结epoch18及同source/config的一次UI恢复，最多admission1+独立review1；实际点击“恢复自由发现”一次，run a9b39523-3daa-53d2-ae86-c900761cd7a6，15:03:53–15:10:44Z（约6分52秒）。

- 实际新增模型1次，native-admission recorded且无provider diagnostic；复用8次，无字段/发现/引用新发送。供应商报告prompt17745/completion3375/total34407，保留原统计不自行改写总数。无新构建/部署/配置。
- 14候选给出2 NEW、9 REJECT、2 REQUIRES_ENTITY_RESOLUTION、1 REFERENCE；0 definition、2 page，旧孤定义问题已消失。两页为“年龄错误处理”“明确说明与如实告知”；这只是未准入草稿，不是已发布知识。
- 预检实际阻断`native admission quote binding must occur exactly once`。两段引文分别删掉原文行内6处CRLF，因此exact occurrence均0；保留了段落换行，并非JSON双重转义。离线去行分隔比较各唯一命中仅作诊断，没有规范化原文/业务响应或绕过严格定位。
- 另有完整输出合同阻断：两页各带1条evidence，所有段落却标MODEL_GENERATED且evidence_indexes为空；按既有provenance校验，即使解决quote仍会UNASSIGNED_EVIDENCE。不得只修换行后立即重跑供应商；九项Schema拒绝及正文覆盖另行对原文核验。
- 最终任务PARTIAL_SUCCESS，发现FAILED/accepted0/published0；完整字段流程到epoch19/release-7cc9f6c8-5050-4678-9225-380356dc8f98（15:11:44Z GET），不是自由发现发布。两个业务窗口合计UI动作2、模型新发送1；第二窗口已关闭，不连续重试。完整私密证据`insurancekb-private-evidence/g35-admission-continuation-20260924/`。

当前缺口集中在准入输出的证据选择/段落归属与覆盖质量。后续设计须先核对原生source chunk引用和既有证据定位能力，将原文identity/offset/逐字quote计算封装在证据责任内，模型只负责语义选择及逐段来源声明；不得靠自动删除换行、自动把MODEL改为SOURCE或删证据来通过。先以本轮完整raw离线验证全部不变量，再冻结必要新输入协议和有界真实验证。此设计方向尚未实现，完整G3.5仍BLOCKED。

## 本窗口独立质量复核

只读对比原文、准入响应及有效字段，确认4个BLOCKER：上述quote/未分配evidence两项；c8“合同效力中止”被整体REJECT会丢失s7“在合同效力中止期间，我们不承担保险责任”，现有宽限期/贷款字段仅覆盖触发条件，exclusions仅列中止条款入口；告知页把“我们就您和被保险人的有关情况提出询问，您应当如实告知”缩成对询问如实告知，漏掉投保人和被保险人的对象范围。当前两页是来源改写，应声明SOURCE_SUPPORTED并绑定各自evidence；真正新增解释另标MODEL_GENERATED，这必须由生成和独立审核验证，不能由预检偷偷重标。

其余8项Schema去重经当前有效字段逐条核对成立：满期给付的附加/未附加、公式、终止/互斥；身故年龄分段/三者取大/附加分支；贷款80%/欠款/6个月/续计/扣款/中止阈值；七免责/自杀例外/退款对象；通知10日/主体/过失/免责部分/例外；犹豫期20日/起点/材料/退费/解除；现金价值定义与各适用情况；宽限期60日及其例外/责任/扣费/中止。部分联合覆盖来自benefit_interaction_rules和coverage_responsibilities，拒绝理由宜列明，作为BACKLOG。年龄错误页三类分支及后果完整，未发现实质性增写。

原候选中“向受益人给付”“以现金价值为质押”“无条件/法定”等增强概括没有当前原文支持，但相应候选已REJECT，未写入正式知识。不能以候选短说明作为证据。后续最小质量反例应覆盖中止责任后果和告知对象范围；本轮不据此扩字段Schema、造新实体或增加整文模型重跑。质量复核关闭，四项阻断未修复，真实非空自由知识与完整G3.5仍未通过。
