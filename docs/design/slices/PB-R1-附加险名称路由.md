# PB-R1 附加险名称路由

Refs #563 的附加险准备评论 6684913202。Codex 实现，Claude 审核。
基线 `eda93a13890b9cf57a24cfc62d1edbe74a1aceec`。
本片是四项准备中的路由小片，不代表附加险已可上线。

## 目标与选择

当前归属已从条款的正式名称、自己的报备编码确定产品身份，再用正式名称的
最长后缀选现有 pack。缺少“意外伤害医疗保险”时落到普通医疗，缺少“疾病保险”
时无法路由。采用已有分类数据增补，不改正则引擎、上传工作流或旧登记。
不采用任意正文关键词匹配，也不按产品号或品牌特判。

新增后缀：

| 后缀 | classification / pack |
|---|---|
| 意外伤害医疗保险 | accident_medical_insurance / schemapack_accident_medical_insurance |
| 疾病保险 | critical_illness_insurance / schemapack_critical_illness_insurance |

保留现有“意外医疗保险”“重大疾病保险”和其余后缀；仍取最长匹配，沿用去括号
限定语及全半角规范化。通用“疾病保险”也覆盖特定疾病主险，不要求名称含“附加”。
这只选择现有抽取目录，不表示产品承担完整重疾保障；具体责任仍仅由本产品材料得出。
两条新后缀同样用于既有品牌核心提取，但品牌始终不是产品身份/主附关系事实锚点。

## 版本与兼容

`attribution_policy.json` 版本升为 `2026-11-12.1`，basis 记录本 Issue 的通用规则。
所有新判断携带新 policy_ref，原持久 decision 保留原版本。
不更改 schema_pack_id、11 pack 目录、字段卡、采信范围、质量准入、来源修订或编译协议。
已有登记产品按既有身份匹配，不能因新后缀静默改写其 pack 或重编线上产品。

## 写域与分离

生产仅改 `harness/src/insurance_harness/identity/attribution_policy.json`。
新增验收 `harness/tests/identity/test_rider_classification.py`。
需要的旧保护适配为三个文件内五处“当前版本”字面期望：
`test_attribution.py` 两处、`test_attribution_policy_versioning.py` 一处、
`test_attribution_title_lines.py` 两处。该适配须单独提交并披露，得到精确范围确认后执行。
历史 fixture 的旧版本与其他旧断言不变。实现提交不得修改新 RED。

## 离线验收

1. 两种合成品牌、两种版式及括号限定语，均经过公开 `attribute()` 的真实 CREATE
   路径；两类缺失后缀在旧实现确实失败，不直接测私有 `_pack`。
2. 含“附加”和不含“附加”的新后缀均正确；原十一类主险和更长后缀正控保持。
3. 只有正文含目标词、未知类型、没有本人报备编码的说明书仍拒绝新建。
4. 登记身份冲突仍隔离；既有错误 pack 不被新策略自动迁移。
5. 品牌核心仅去掉完整类型后缀；更长后缀优先。原历史 decision 的 policy_ref 不重写。
6. 定向 identity / ingest 回归、ruff、mypy 和架构守卫；全量以精确 head CI 为准。

交付顺序为本 Spec、独立 RED 提交、策略数据实现、独立版本期望适配、门禁与 PR。
本片不 build、不部署、不连接平台、不上传、不解析、不调用任何模型。
