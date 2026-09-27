# G3.5 综合流程验收 2026-09-27

用户继续完成G3.5，全项授权持续；root唯一写者。沿现有P2-2与R6实测，质量不做逐case调优。

本轮基线a587823fe，Harness4f8529ce…，runtime未变，Active epoch23；预检队列空。
材料为同账号现有平安智盈倍护（2026）终身护理保险条款，696913字节，SHA256 b2ade27cf1c05ac48b1319ba0480f6c92951db5bbe6e611432b5394a0944d85e。
原生已解析65段20287字，预计2窗口，以签名plan为准。正常UI只上传一次，原策略/超时/容量约束不改；终态不手工重试。
准备回执/private/tmp/g35-closeout-20260927/business-window.json。
当前仅选材/只读预检完成，provider/新业务NOT RUN，不能记多窗或质量PASS。

## 实际正常上传与身份阻断

正常UI上传run cdefcda9-1ca3-4fc1-b45e-3da99199aaeb，00:40:55—00:41:17Z，
终态needs_confirmation:PRODUCT_IDENTITY_UNRESOLVED:IDENTITY_EVIDENCE_MISSING。
身份模型recorded/stop，识别产品名/2026/2648，issuer=null；不是提供方调用失败。
两个含公司全称的chunk source_page_number=1，而公司只在actual page2范围；原prompt
7blocks均page1且漏公司。原失败run不重试、不修改raw，尚未进入多窗口发现。

ID-PAGE-1—4在原Spec冻结，独立设计复核0BLOCKER；新增局部物理页view与共享Proposal
门禁，保留原SourceBlock/Evidence身份及真实几何引用。RED明确缺该输入能力。
真实签名snapshot离线decode/prepare PASS：8blocks、1个actual page2补充、22locator，
公司有可核验引用；provider0。回执offline-identity-report.json，不能代替live验收。
实现定向初步15PASS；冻结审查manifest d4d4ba91…，完整恢复/持久worker回归进行中。

修复最终8文件manifest4a3c4556…独审0BLOCKER（来源全绑定复核及EOF机械确认），
提交d0157306cda48fd315b4fb4f101d249d942e837b；最终22身份PASS、4持久workerPASS77.24秒。
Harness必要build1 PASS，image b3041eb9…；仅构建尚不能推导部署或业务完成。

调用口径澄清：cdef API计数7含source receipt历史6次（时间戳1789615068832等），
该来源早已解析。本轮可确认新增身份StageCall1，fields ledger80不变、stage45→46；
不得把API总计7直接写为本轮新增7次provider调用。统计来源复用标记另记后续核对。

## 修复交付与真实两窗口终态

01:16:37—01:17:01Z Harness-only部署PASS，制品sha256:b3041eb94c8918d370e381ad8dd0c9db144d7e4aa6c0e46774328bd688a65d88，源码d0157306。
部署manifest395d3de7…独审0BLOCKER；App/UI/runtime保持，旧容器可回滚，migration0。
切换前后Head epoch23、call ledger均未变。

正常UI新run3965eb5b-7a66-4f9f-84ea-fd034112f6e0在01:17:57—01:23:42Z完成（344.45秒）。
身份PASS；签名plan2窗口，完整coverage2/2；native snapshot分别82b7961f…（23候选）和22f3d187…（28候选）。
两窗有重叠，不把51当去重概念数。源范围20287字全部提供，不等于语义覆盖通过。
8字段调用+7StageCall均recorded；API21含6历史来源调用，不记为本轮新调用21。
字段26成功/37材料未提供/11失败；发布读模型26verified/48missing（后者含失败隔离）。
窗口0准入REFERENCE1/REQUIRES_ENTITY_RESOLUTION3/REJECT19，pages/definitions均空；
窗口1 c1 REFERENCE existing_target为entity_id@entity_version，被strict_projection拒绝；独审确认公开wire schema未列允许身份，属于输入合同缺口。
其余27REJECT在原始回执保留，不把整窗失败冒充已接受处置；没有改raw、降门禁或盲重试。

正常Candidate→review→publish→verify PASS，epoch24/release-c788d049-7c35-42a3-953c-82c0d395a797，
候选hash5b7583f0…，75成员/56引用/1检索命中。浏览器正式目录显示14产品/1030字段；
护理产品等待期显示90日及意外例外，点击查看原文到第2页且PDF黄色框高亮对应段落PASS。
新free成员0；R6非空聚合、R3模型生成真实展示、R4正式关系真实页面仍未闭合。
原生发现不是只生成少量候选，准入/协议才是本轮主要损失点，质量统一处理。

本轮只读审计与回执/private/tmp/g35-closeout-20260927/after-fix-run/，真实窗口已CLOSED_PARTIAL_SUCCESS。
PENDING隔离符合Spec，不把人工override或新签名平台加入本轮必要范围。

## REF-TARGET 通用接口修复

独审确认模型符合公开schema（任意string/null），服务端投影隐含只接受entity_id；
因此不是模型断联，也不能单纯归咎模型。原Spec补REF-TARGET-1—4，仅v4 provider view
公开枚举精确target及REFERENCE/null条件，不改raw、strict或v2/v3，不剥离版本后缀。
JSON Schema真实校验RED8失败（缺可选库的collection错误不计RED）；锁文件已有jsonschema
显式加入dev，未升级其他包。定向58PASS/63.17秒，ruff3文件/mypy1source/diff PASS。
冻结6文件manifest49cf19b2…独审0BLOCKER；commit9871a88075acc8f3e670291754ca37c4467b7dac。
Harness build1 PASS image c06aaa141f022cd051232885c7015f6ee82dcc404900bb7b3b5cf5d8e3cbd911。
交付尚待执行；不据构建推导业务通过。正常恢复窗口reference-recovery-window.json已冻结。

## 引用协议修复及正常恢复

9871a880 已交付，deployment-manifest SHA443dd910c36df8da1402d0f4960d5138b32fa62e724cdd6b7dd2682447707de7。
恢复c6a06d47…新2次/复用13次、两窗均通过strict admission，无raw修补。
aggregate v2离线exact重建PASS，2REFERENCE/3REQUIRES_ENTITY_RESOLUTION/46REJECT，retained成员0。
完整正常checkpoint→discovery→compilation→preparation→review→publish→verify终结，run partial_success。
Active epoch25/release-fb28a97a-cae1-416e-a885-874f31f0dc22，candidate26b23d7a06b0b3fc47fc68d3f1df006dacb6f31409e23efdd1888926012d5c66。
verify PASS 74fields/26verified/48missing/75members/56citations/search1；49隔离候选不能当非空质量PASS。
独立恢复审查0BLOCKER，原文与模型生成的实际发布质量另行收口。
证据私密目录reference-recovery-run/audit.private.json及reference-delivery/run-c6a06d47-e078-5709-8826-fe5349e5968e.private.json。
