# 原文编号准入首切片（2026-09-25）

## 当前边界

继续既定 G35-R5/R6 单材料 tracer，root 唯一写者。新 wire v3 让模型逐段选择证据编号并声明来源，程序展开精确原文和位置；旧 v1/v2 投影、R6、几何定位、最终审核与唯一 Active Release 不变。以下软件记录为交付前历史；当前交付与业务终态见末节。源码6ea5e023已部署，真实纵切仍BLOCKED，不能由准入投影通过推导质量通过。

## 复用与实现

- `native_admission_wire.py` 是无 I/O 的窄适配：沿既有验证过的 source_options 完整 span 编号（如 s8:1），不再要求模型重抄引文、算 offset 或维护独立 evidence 列表。按 catalog 顺序生成既有 v2 evidence/indexes；text/origin/decisions 不改。未知、重复、乱序、MODEL 带引用、SOURCE 无引用和原正文覆盖错误仍拒绝。同一证据可被多个段落使用。
- 模型原文改述明确标 SOURCE_SUPPORTED；真正补充解释独立 MODEL_GENERATED。新系统模板明确比较 Schema 的对象、接收方、触发、条件、例外和后果，提醒保留效力中止后果及告知对象范围。提示不是质量通过证明。
- `native_admission_policy.py` 封装显式可选 admission 模板绑定和配置派生。基础 model、其他模板、连接/凭据/模型/容量及 native_discovery 保持；派生配置只替换旧准入模板。composition 复用同一个 ConfiguredModelExecutor 类的另一个配置实例，仅准入选择它，不新增执行/恢复平台或全局 hash 白名单。
- execution 回执升 v2，绑定协议、template/prompt/model policy、input/request/raw。完整 discovery checkpoint 复用前重新核对原调用记录及当前准入配置；删除或修改 override 不可沿用旧结果。旧 execution artifact 升版截断旧完整阶段，成功 raw 仍由原 exact matcher 选择。FAILED discovery 的来源/身份/字段/原生发现/引用复用不变。
- provider wire context/raw 与 RULE 展开的领域 v2 response 分开保存；既有 dependency receipt 使用严格重建的 v2 领域 context，wire expansion 回执绑定该映射。没有自动修正文、替模型重标来源、删除不合格成员或造页。

## 验证矩阵

| Requirement | 已观察 RED | 最终软件验证 | 状态 |
|---|---|---|---|
| G35-R5-WIRE-1 精确绑定/来源 | 旧预检不支持 wire，9失败 | 中文/emoji/CRLF；未知、重复、篡改 context、标签冲突、正文覆盖；非空 page 经原 geometry；原 wire 不变 | PASS |
| G35-R5-WIRE-2 仅准入升级 | 新配置旧 loader extra_forbidden；真实 worker 仍发送 v2 | 基础 policy 不变；不合法模板/权限扩展拒绝；完整持久 worker 仅准入新发送，来源/身份/字段和6原生调用保持 | PASS |
| G35-R5-WIRE-3 完整恢复身份 | override 删除/变化时完整 checkpoint 原先未拒绝；旧 artifact version 断言失败 | 同配置三代恢复不新增调用，删除 override/改模板预算拒绝；原调用 request/raw 保管校验保持 | PASS |
| G35-R5-WIRE-4 后果/对象保真 | 真实旧输出的两项语义缺口仍有效 | 新提示已加强，尚无新 provider 输出或独立全处置验证 | BLOCKED |

最终有界回归 `g35-wire-bounded.log`：94 PASS、1 SKIP（v1不适用成员合同）、1 已有 Starlette 弃用 warning，271.11秒。ruff PASS；7个受影响生产文件 mypy PASS。早先分组验证与此重叠，不累加测试数。最终冻结源码/测试/Spec 清单 `/private/tmp/g35-wire-review-2.json`，基线 HEAD `77ee9d5dbd942dd9db39126b75f1eac4ae2617da`。

真实旧输入离线反事实：原两页 MODEL 标签若选择 evidence_refs 仍拒绝；只有显式人工声明期望 SOURCE 标签的测试夹具才能展开。18个 source span 全文不变，wire context 61163 bytes，旧 v2 为61274 bytes；两页正文未改，因此中止后果被拒、告知对象遗漏仍存在。该检查只验证协议适配，**不是新的模型输出、正式准入、发布或质量结果**，effects=0。回执 `/private/tmp/g35-wire-real-input-diagnostic.json`。

## 交付与真实业务

截至本报告，本切片 build/provider/business writes=0。离线准备配置 `e0e3a79b…`，仅新增 admission override；原 runtime `624e393d…`、base model/native_discovery policy 逐字保持。新 prompt SHA `5bff15c5e0ac5a07e4c68745144070da9c26af9f2e7f920387045d8ab8305e84`，保持300000 bytes/16384 output tokens；配置尚未应用。

只读容器检查仍为 d8 Harness 镜像 `ed95cb8b…`、API/worker healthy，runtime `624e393d…`；网页仍显示旧 a9b39523 PARTIAL_SUCCESS/发现FAILED/模型1/复用8。未重试按钮、未重传材料、新建库或直接改业务数据库；Active 未在本轮新 GET。旧真实窗口保持关闭。

下一步须独审收口、冻结提交和精确交付窗口，再集中 Harness-only 构建/可回滚切换与同一材料一次正常 UI 恢复；最多新准入1+最终审核1，其他阶段期待 exact reuse，未知/失败停止并保留回执。真实输出逐项对照四阻断、全部14候选处置、18项覆盖、模型补充标记和原文点击，不能用 fixture 替代。

已确认后续覆盖门缺口：现 v6 审核仅 retained dispositions，candidate_member_count=0 时跳过独审。全部拒绝不能作为覆盖正确证据；自动全处置审核需另版本化（包括零成员），不在本切片偷偷改变模板。完整 G3.5、R4 与跨窗口 R6 仍未完成。

## 独立复核收口

首审2项BLOCKER已关闭：规范化wire值哈希改名wire_value_sha256，外层decoded字节与provider envelope原始哈希分别保留；新增引用乱序及16类receipt/call/context篡改直接反例。哈希命名先观察真实RED；内存mutation分别删除order/identity守卫产生预期测试失败，只是补充敏感性诊断，不冒称历史实现RED。随后纯边界35 PASS（25.82秒）、非空v3 stage1 PASS（5.67秒），ruff PASS；与原94项重叠，不简单累计。revision2清单14/14 SHA匹配，独审0 BLOCKER，原全REJECT/零成员语义审核BACKLOG保留。

16:13:48Z通过同账号正常GET确认a9b39523仍PARTIAL_SUCCESS、字段26/51/2、自由发现FAILED；唯一Active仍epoch19/release-7cc9f6c8-5050-4678-9225-380356dc8f98。本次GET为只读交付前基线，非新发布。两个Harness容器镜像/配置仍上述原值且healthy。


## 真实交付与终态（2026-09-25，取代前文当前状态）

源码 `6ea5e0236fc44291a3176aba19a3d3c3ba1bd3e9`，Harness image `sha256:b3bed2d2f43870f70fec8cfbf46525a2359d4d6828aa785b2704a8c4b77960eb`，runtime SHA `e0e3a79be180fcfc8b56c17fefa821182bb3829f9e02e02583c7222e0be1f91c`。仅Harness实际构建一次并可回滚交付；APP/UI/DocReader容器原样保留，无migration。第一次构建准备使用系统Python3.9失败于tarfile filter参数，尚未进入Docker构建；独审确认后使用项目Python3.12完成同一冻结输入，不能隐藏准备失败或计成第二次物理build。16:27:10–16:27:23Z交付PASS，切换期间模型/业务effects=0。

同账号正常UI恢复一次，run `43e71710-4d0b-54ed-98b7-72b51a5eac3d`，16:29:49.640917–16:33:29.429513Z，219.79秒。新准入调用1 recorded、复用8；provider原usage prompt17951/completion3669/total31759，保留供应商原统计不自行配平。新解析/字段/原生发现调用0，最终独立审核模型调用0。14候选→4 NEW页面、7 REJECT、2 REQUIRES_ENTITY_RESOLUTION、1 REFERENCE；9个隔离项含7拒绝，不能称9实体待解析。

完整wire展开/strict/R6/geometry实际成功；最终编译准备审核上下文时失败 `discovery context budget exceeded`。全部4自由页未进入发布，accepted0/published0。既有字段发布/验证完成，任务PARTIAL_SUCCESS。16:35:21Z正常GET唯一Active epoch20，release `release-848316db-db18-4265-bcc9-dc27d7d624e4`。浏览器详情确认3分39秒、新调用1/复用8、4新提议/1重复/7未通过、发现失败；UI“自动审核/发布已完成”仅对字段结果有效。新增自由页原文点击/模型补充标记仍NOT RUN；此次4页均SOURCE_SUPPORTED，没有模型补充正文可用于标志验证。

有限窗口已CLOSED_BLOCKED，UI1/1、新调用1/2、retry0；不继续点击恢复。临时防空闲进程已结束。原始私密归档 `insurancekb-private-evidence/g35-wire-20260925/delivery/`，包括完整终态API、审计、构建/交付/窗口和诊断；无凭据/raw写入仓库。

### 精确离线根因重放

以真实rebased_request、field_delta和discovery_candidates调用原merge/compose/renderer，最终hash与真实 `8cfc2d6d02a30094685c9c667a2ea4c6dd6571c74976ac924798d8d745a4aced` 一致。真实预算300000 bytes，审核输入730770 bytes；其中existing_knowledge445778（Schema描述434376）、exclusion_index105839、dependency_selection111723。原因是pipeline未传entity_id，审核上下文展开整个发布批次14历史实体/1030条Schema定义，而本次4页同属一个产品。

只在离线调用既有单entity审核接口，保留完整final hash、dependency_selection、4页及原文，结果214790 bytes、79条相关Schema、7个候选原文块，低于原预算。该诊断provider/business effects=0；不是已修复、真实审核或发布。不能简单调大预算或删除原文。证据 `review-context-diagnostic.json` / `review-scope-diagnostic.json`，前者完整原上下文SHA `7aada1662dc828428b42296ad767e5ac8de61a8a0ef261a6b56aefaa255c529f`。

### 独立内容复核

前次4项阻断均已关闭：9条引文逐字一致、全部evidence被来源段使用、中止不承担保险责任后果已保留、告知投保人/被保险人对象已保留。这只关闭对应反例。

新的5项BLOCKER：

1. c8第二段“分期支付保险费的”条件在s11:1，但仅引用s12:1；正文正确，逐段支持不完整。
2. c9保险事故通知与有效 `claim_application_deadline_and_documents` 全文语义重复，误判NEW。
3. `policy_loan_rules` 缺s5利率决定因素、到期前还款通知及按期归还义务；c6 Schema归属正确，“已完整覆盖”理由错误。
4. `exclusions` 缺s6其他免责现金价值退给投保人的对象；c7 Schema归属正确，完整性不足。
5. s14–s17利益演示及其适用限制没有原生候选、有效字段或自由页承载。发送全文不能证明覆盖。

联合18项：15完整/2部分/1缺失。部分为贷款期限利息、免责退款对象；缺失为利益演示边界。其余满期分支、身故年龄、一次给付、重疾减额、贷款条件/公式/中止、七免责、事故通知、年龄错误、犹豫期/退保、投保年龄期间、宽限期、提示说明/告知后果完整；其中事故通知重复应去重。过宽chunk引用及审核元数据“法定”无来源措辞另记BACKLOG。

后续必须同时验证审核输入作用域、真实有效字段比较、段落证据完整性及全文未发现内容。v6仅保留候选审核/零成员跳过的自动覆盖门仍未完成；不能仅修预算再称质量通过。G3.5、R4及跨窗口R6均未完成。


## 审核比较作用域的软件修复（真实窗口结束后）

先冻结G35-R6-REVIEW-SCOPE-1/2，再记录旧stage RED：不传entity时实际发送全库视图，且旧全库审核被复用（预期新发送1，实际0）；新增纯scope守卫尚不存在的反例另记，不混为真实stage RED。原日志 `/private/tmp/g35-review-scope-red.log`，11失败。

实现复用既有v6单entity能力：`native_dependency_selection.resolve_native_review_entity` 先验证完整selection/member/request绑定，再核对selection实体、admission context实体/版本、全部候选page实体/版本和request唯一binding。冲突/混合实体/无绑定/篡改直接拒绝；显式entity不得覆盖真实归属。定义仍全局可见。`discovery_stage` 在原review入口选择scope并在工作线程构造index；无selection的历史路径不变。不改renderer、prompt、模板、配置、预算或final hash；不新建审核器。

有界5文件131 PASS（40.66秒）；补充类型收口后最终stage8 PASS（4.05秒，与原131重叠）；ruff PASS、两源码mypy PASS，不累加为新用例。真实14实体raw通过当前实际stage（fake executor捕获，无网络）准备出214790bytes输入，79条Schema/全局definition1/4个成员，完整selection与真实最终hash不变；context SHA `aebdab5ad2ed36d5fcfb07fe8080c13b934fbacbca69c2798b449e3cc8bf029a`。fake空响应故意FAILED，不能称真实审核通过。该实现尚未部署，不追加真实恢复。

| Requirement | 实现 | 验证 | 状态 |
|---|---|---|---|
| G35-R6-REVIEW-SCOPE-1 | 原dependency深模块pure scope + 原review接线 | 真实stage自动scope、归属/版本/混合实体/重复缺失binding、冲突0发送 | PASS（软件） |
| G35-R6-REVIEW-SCOPE-2 | 原v6单entity renderer/index | 全局concept保留、full selection/hash不变、旧全库review不复用、真实14实体离线输入214790 | PASS（软件） |
| 本轮自由知识真实审核/发布/点击 | 未发生 | 审核预派发超预算，发布0 | BLOCKED |
| 内容5缺口、全处置/零成员/全文覆盖 | 后续任务 | 真实独审反例已保存 | BLOCKED |

软件源码审查冻结 `/private/tmp/g35-review-scope-review-2.json`，4/4 SHA匹配、独审0 BLOCKER；root唯一写者。完整G3.5未完成。真实delivery六维：software PASS（6ea有界与独审）、container health PASS（精确Harness制品）、provider probe PASS（仅真实准入调用）、provisioning PASS（精确配置，无迁移）、local live PASS（容器/字段链；自由知识BUSINESS另为BLOCKED）、GitHub live NOT RUN。scope后续软件不可由此推导已交付。
