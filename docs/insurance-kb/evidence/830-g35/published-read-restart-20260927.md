# G3.5 发布读取重启缺陷与真实流程复验

2026-09-27，用户继续授权完成G3.5。root唯一写者，活动树830-g35-multiwindow。
本轮只处理通用跨轮输入缺陷，不针对产品字段或单条模型输出调优。

## 真实触发及根因

正常上传 run `3a916e65-dd32-4270-90f6-4e1f713d6542`，04:09:01—04:09:42Z，
身份调用成功，仅新增1次语义调用；field_plan在3次任务尝试后终态失败，尚未抽取/发现。
前轮epoch26的纯模型生成概念经App重启后的签名gob读取，合法空evidence及
MODEL_GENERATED.evidence_indexes从[]变为null；Python严格合同因此拒绝。
不是提供方调用失败，不是原文缺失。原任务及原模型响应保留。

## 修复边界与验证

Requirement READ-GEN-1—4见现有129 Spec `published-provenance-restart.md`。
唯一Owner是Go published-read codec：完成验签及投影/preparation本地身份检查后，
以同一签名PageManifest原始JSON中的显式[]为witness，恢复生成内容空引用；
当前Release成员仍在base snapshot返回前校验。SOURCE_SUPPORTED的空索引、
mixed内容缺证据、缺失或null witness、正文漂移继续拒绝，旧签名文件不重写。
不改Python/候选校验，不触发模型，不承诺其他可选集合或整个snapshot冷热SHA一致。

最小签名gob回归RED明确[]int{}与nil差异，修复GREEN4.506秒。
新增跨语言合法合成fixture经过Draft→Review→Activate→新cache→签名base snapshot，
纯生成definition/page的evidence与indexes非nil；连续冷/热读取稳定，GREEN29.586秒。
Go overlay恢复旧read实现时，该完整回归在纯生成definition Evidence NotNil处失败，27.527秒。
fixture是合成协议数据，不是模型质量/实际业务证据。
6路径冻结manifest SHA `7f0a95d8c8e09ad65284db80986795113a2938feb90ba5dec92e8a0139ad8025`，
独立复审0 BLOCKER；OpenSpec strict与generator lint通过。

源码修复bcfce2fa6，最终冻结构建源b393d855c（含独立机械路由测试对齐）。
直接影响的冷读、base、增量传输和引用回归PASS82.168秒。
最终扩大Go检查中types/repository/config/container/handler通过；service全包966测试达到默认10分钟总超时，
当时执行TestG3OperationResultRejectsChangedIdentity仅12秒，不能记全包PASS。
按影响面定向验证已通过，不以无界重跑或环境错误代替行为证据。
另发现旧composition测试仍预期6条平台路由，实际已交付10条；仅对齐测试并补4条
路由的API key注册检查，独审0BLOCKER，router全包PASS2.260秒，权限及产品路由未改。

## 恢复与交付边界

旧run的identity阶段已冻结错误base快照；现有retry-processing生成v5 checkpoint，
只复用旧输入，不具备v6/v7的rebase能力。部署后正常上传同一公开PDF创建新run，
复用已有解析并读取新的合法base，禁止修改旧artifact或内部legacy重跑。
原文件与平安官网公开PDF逐字相同：696913字节，SHA256
`b2ade27cf1c05ac48b1319ba0480f6c92951db5bbe6e611432b5394a0944d85e`。
一次新正常上传、无终态盲重试，最多观察24次新模型调用/30分钟。
仅构建替换App；Harness、UI资产、模型/运行配置保持；保留旧App可回滚。
后续实际部署及业务结果见下列独立回执，不由软件GREEN推导完成。

私密证据目录：`insurancekb-private-evidence/g35-final-flow-20260927/`（终态时归档）。
远端CI与集成在业务窗口收口后按精确最终HEAD记录。

## 本地交付回执

App-only构建1次PASS，源码b393d855c，image `sha256:7d97028e6994b4a48cfbbc7dea0407e42454d35c076134c600a0c86049ff5527`。
04:48:35—04:48:56Z可回滚部署PASS，新App容器33cd9ff66780；Harness/API/worker镜像及配置保持，
UI仅重载代理，Head epoch26/模型ledger不变，无migration/provider或业务写。旧App保留。
部署manifest SHA `84d4ee79d2d4d090ebc8fb8429b5c3e0ff4e2b12ff261089d14d3aab68ddd9fa`，
脚本/本地helper/quiescence输入均独审0BLOCKER并绑定冻结SHA。

## 正常业务终态与用户页面

新正常上传run `d6d071a6-b3a1-4cdb-ae3f-1892ea59451c`，04:49:27—04:53:58Z，
271.207秒，终态partial_success；13个持久任务全部首次尝试成功，无终态人工重试。
7次新增语义调用全部recorded（身份1、原生发现/引用4、准入2）；新source与复用调用均0。
既有字段结果沿用，本轮不是再次全字段抽取。20287字符、2个完整窗口、遗漏输入0；
完整提供不等于语义全覆盖。发现摘要pending41、REFERENCE/duplicate1、rejected38、
新accepted/published成员0；保留未解决候选，不为增加页面重跑模型。

审核、授权、发布及发布后verify PASS；Active epoch27：
- release `release-fb536f81-b2c2-4c1e-bd33-01bb800cadf7`
- candidate `5292b6aa8a2580736e6139921060c4d2d22b790add6a886aad3c44c1891e54c5`
- receipt `receipt-0e2afc22-be81-4e1e-8c6d-0950be60edd3`
- 74字段（26verified/48missing）、75members、56citations、检索1命中。

新base snapshot中的既有纯生成概念保留evidence: []和生成segment evidence_indexes: []，
证明重启修复进入正常业务。浏览器亲测第27版等待期页→查看原文，打开PDF第2页并黄色
高亮对应条款，UI PASS；第26版真实模型标识/关系导航沿用已有验收，不冒充本轮新生成。

本轮FLOW_PASS，语义质量仍PARTIAL。个别字段/R7遗漏统一维护，非空多窗口语义结果
NOT RUN/BACKLOG；不声明整体优于原生、100%覆盖或全部候选通过。
最终精确HEAD的CI及集成由PR130远端回执记录；本文冻结时仍待执行。
