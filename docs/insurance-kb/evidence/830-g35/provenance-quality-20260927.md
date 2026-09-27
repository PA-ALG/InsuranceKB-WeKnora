# G3.5 统一来源质量切片 · 2026-09-27

状态：CODE_PASS / DELIVERY_PASS / FLOW_PASS；R7统一内容质量未完全通过。
源码：`031a2fb83a232354ed7e7621fa2f2838dda27dea`。
用户全 G3.5 授权持续；root 唯一写者，活动工作树 `830-g35-multiwindow`。
适用合同：`provenance-quality-policy.md` QUAL1—6。

## 实现边界

复用原生发现/引用、G3 Candidate、独立审核、检查点和唯一 Active Head。
新增纯资格模块保留六维原始分值，纯 MODEL_GENERATED 的证据分仍为0；仅显式新政策
使用80适用满分、64/48资格阈值，其余100满分及80/60阈值保持。
模型拒绝、来源错误及产品事实问题不能被分数覆盖。旧71分raw不改、不转化为新审核。
请求、省略/hash、审核prompt/context、重放、局部裁剪、Python/Go最终重验统一绑定政策。
复用已审有效字段比较模块，正常准入读取完整compose后的字段；独审核对每个窗口，
检查点同代重建请求和delta。字段比较不充当来源证据，不把unknown或字段名字当覆盖。
不整包集成旧深度coverage WIP，不新增人工override/KMS/审核平台。

## 验证回执

- 评分入口 RED：旧实现6失败6通过；独审RED3失败16通过；均为行为差异。
- 准入有效字段RED：2失败，旧接口无法提供实际字段集合。
- 旧模型display新增空policy污染：1 RED，已恢复缺省省略。
- 共享边界向量：生成47/48/63/64/71、source59/60/79/80、mixed/legacy与错误来源/分数。
- Python初始组合90 PASS；唯一样本失败是测试错误沿用update政策，修正为真正新成员后完整Candidate5 PASS/27.01s。
- 边界组合63 PASS；配置测试的严格模型JSON入口修正后4 PASS/24.54s。
- 有效字段14 PASS/52.12s，包括同代及prior-rebase混代拒绝；新增多窗反例也在边界组合通过。
- 新quality与旧v4持久worker重启/恢复/发布2 PASS/113.16s。首次发现检查点contract_name/version不一致使多发审核；修正为v2/2后成功调用不重发。
- Go整个`internal/types`包 PASS/110.325s；完整Python/Go共享Candidate在未启用knowledge_update_policy时亦重验质量。
- 旧discovery22 PASS/53.48s，保持历史路径。
- 20个变更Python源码mypy与适用ruff/diff检查；最终结果以冻结复核回执为准。

冻结v1：32路径，manifest SHA `67efdd3523275689a7eb8ef9023d344283ffdb7fda7d60c396a035594e353b78`。
只读快照 `/private/tmp/g35-closeout-20260927/quality-review-v1/`。
各测试日志在同一私密工作目录，仅本地software证据；GitHub live NOT RUN。

独审v1发现新policy缺dependency仍可配置，2项RED复现后由统一配置/有效字段入口拒绝。
最终32路径v2 manifest `e726148da68f721253f70b96575aaa3ce8fc0bbde727a370043d834853257542`，独审0BLOCKER。
配置与字段23 PASS/37.01s，最后变更源码mypy及ruff通过；旧原始审核未重解释。

## 交付与业务

App/Harness各必要build1均PASS，02:40:49Z可回滚部署PASS；新配置已应用，模型/账号/endpoint/secret保持。
App image `4be2e1da08cb2c12207a0ad2154e48952ccea53f56e21e2ae1f9b212985150cb`；
Harness image `d8d1d91d2950d8fdcbe82e79c8debcd796d9c43de0b3c1666120f9c0b0b419fd`。
拟启用配置SHA `555d2262ff13ea6ce3314eb3b900ecc8d5b97507825f5ec14dbcaa33ea076a32`。
当前真实Active为epoch26；先前正常恢复结果见`complete-flow-20260927.md`。
新政策真实模型生成页、typed relation、来源点击均PASS；集中内容覆盖仍有缺口。
空输出或软件成功不得写为非空质量PASS，完整G3.5未完成。

最终交付manifest `0b758a18669cca6de527449792416c2edf595aaaac2622e1822bc33b72ca60a3`，独审0BLOCKER。
原生动态队列+durable pending、Harness队列/账本、App配置、Head前后检查通过；旧三容器保留，migration0。
普通UI说明书run `41b7009c-6ebe-499e-8d95-fcbd93d43f03` 于02:42:46Z启动；仅一次上传，原文件解析复用。
本轮02:47:09Z终态partial_success，耗时263.384秒；13个job均succeeded，自由发现仍有8项隔离。


## 正式业务与页面验收

- run `41b7009c-6ebe-499e-8d95-fcbd93d43f03`；candidate `4d36e210120fc836399f3ecbf2b8195e9adc0ef12f683070e288460a3e6b131b`。
- Active epoch26，release `release-44971129-62a4-4af4-9b62-7746074e50cf`，正常系统审核、ready、授权、发布及verify均完成。
- 原生14候选：1新提议（产出概念＋关系2成员）、5引用、7拒绝、1待实体解析；8隔离不拖掉合格成员。
- 新概念独立评分68/80，证据分0；新关系93/100。原始分数没有改写，没有沿用旧71分审核。
- UI正式关系页明确“原文依据”，关联概念可点击；概念主文及相关知识均有“模型生成”标志，无伪造原文按钮。
- UI“查看第2页原文”打开原PDF第2页并显示黄色高亮；高亮覆盖实际条款块，非逐句最小框。
- 关系→概念导航成功，概念→产品规则反向链接存在，URL均绑定相同release。
- verification：79字段/26verified/53missing，80为该旧验证合同的成员计数，50citations/1search PASS；不能把80当当前完整目录含全部概念/自由页总数。
- 本轮沿用已有字段，字段任务0新抽取；不能将其成功0/缺失0理解为实体没有字段。

[查看正式关系页](http://127.0.0.1:18295/platform/knowledge-bases/8d5695de-f255-42d5-9a41-042ba86e97b9/schema-wiki/concept-pages/free_f64eee4f87cd48bfb57273beff90b432f25259101a6ab07735fa2c5c835ebc55?release_id=release-44971129-62a4-4af4-9b62-7746074e50cf)。

## R7集中对照：内容、来源、成本分别记账

独立只读冻结审核：`quality-frozen.private.json` SHA `0dae5e1ee65321e100350136ad6ee58ccfe9afdeca83af428eb4f7ca2be494ba`。
只评本产品79字段（26有值）、4既有自由页、1新关系及新概念，未混入其他13产品。
18项联合内容：15完整、2部分、1缺失；未确认硬事实错误，非全文100%覆盖。

| 遗留类别 | 本轮确认的缺口 | 维护职责 |
|---|---|---|
| 字段正文完整性 | 贷款利率因素、通知及到期归还义务缺失；免责其他情形的退款对象缺失 | 统一字段覆盖核查/语义修订，复用既有字段编译 |
| 自由发现覆盖 | 利益演示案例参数、15行表格和五项提示无有效正文承载 | 统一来源覆盖及原生补发现，不按个案硬编码 |
| 逐段来源充分性 | 既有中止页分期前提未出现在该段选中的引用内；联合宽限期正文有完整承载 | 统一来源支持核查与原身份UPDATE |

本产品64条引用的offset/quote/quote_hash逐项PASS，只证明位置合法；不等于逐句支持充分。
新关系条件/约定金额/现金价值/归零后果完整，单条引用可支持；生成概念仍是概括，不替代产品精确规则。
原生DeepSeek基线包含上述贷款、退款对象与利益演示，当前标识和关系更明确，但不能声称整体优于原生。
模型、输入形态、历史知识复用和调用范围不同，不构成控制变量A/B。

本轮5个新增语义调用均recorded，prompt137350/completion6922/total157841 tokens（供应商total含其他推理用量，不能强令等于前两者相加）。
API显示8（5语义＋3source回执）；独立复核确认3条source回执发生于09-23 09:37Z，属于历史记录，并非本轮新调用。API的reused=false误标记为观测BACKLOG，不据此重跑。
原生基线25次文本发送、total186392tokens，但其生成20正文，本轮字段沿用、增量2成员，不能据此断言降本比例。未核验账单，不推算金额。

按用户FLOW优先、效果统一维护的最新安排，本轮不新增逐case提示、分数补丁或模型重跑。
上述质量项保持可追踪且未标PASS。完整G3.5仍不宣称全部验收通过，远端CI/最终合入NOT RUN。

终态独立链路复核0BLOCKER：manifest `ed9d67b999401357d239fad902f13a3e1cc8ce93f0f372d22e384421ad0e00fd`及5文件hash匹配。
review的request/output hash经Candidate封装，再由ready/授权/发布回执逐层绑定；不是所有对象字面同hash。
Candidate保留1043项BASE_CARRYOVER，仅新增2项，无旧成员update动作。
完整私密回执已备份至 `insurancekb-private-evidence/g35-closeout-20260927/`，仅本机受限访问。
