# 两款新品增量验证进度（2026-09-13）

本轮按用户要求增加1820福满分年金、1818爱满分两全；先用首页正式名称路由Schema，保留原文和页码。原G3固定批次FLOW PASS与第9版7产品493字段为历史事实，本记录不提前声称本轮发布完成。

| Requirement | 实现 / 验证 | 状态 |
|---|---|---|
| G3-INC1 | Python/Go支持PUBLISHED_G3父集合的新增实体，拒绝旧字段遗漏/旧版本变化；342/493字段正反向测试 | PASS（software） |
| G3-INC2 | 两份真实C origin保持原receipt/hash，按签名来源重开并集；Python101 passed，Go多源和单源partial PASS；独立代码复核0 blocker | PASS（software）；实际runtime重开 NOT RUN |
| G3-INC3 | 清单驱动embedding guard及24旧边界回归+3新测试；6真实PDF39页、37来源块、6次embedding全部200；6次Gemini C成功无重试 | PASS（source / C provider） |
| G3-INC4 | 已构造9实体、旧493字段、161新增字段、19个D窗口的真实请求；D抽取/检查/候选/发布/线上读回 | NOT RUN |

根代理追加guard+增量base验证：32 passed、32 subtests passed。INC2作者最终Python101 passed；Go同生产实现完整types包通过，最后定向测试通过；重复冷缓存全包因资源竞争中止，未当成PASS。三条既有E501不在本轮diff。独立review source scoped diff SHA256=7d401bcc5c1adcf5184142dbed74d3cc60fd1f29fcf596c728aaadbc78cc8262。

本轮实际分类：6材料中4 CREATE、2 NEEDS_CONFIRM；4条款/说明书归并为两款产品。两费率表首页有正式名，但公司身份/版本锚不足，保留待确认；不改原模型回执，不伪造关联证据。新增两Schema为annuity82、endowment79。旧15材料C结果按原来源复用，不再调用。

私有证据根 `/private/tmp/g3-two-products-20260913`；不提交PDF、解析全文、调用正文、令牌或签名私钥。source-selection、source-terminal-readback、c-ledger、c-materialized、incremental-inputs保存实际记录。C6次usage为prompt63227/completion17585/total80812 tokens；网关无冻结价表，不宣称精确费用。上传初期自动摘要曾触发额外Gemini调用及超出原文白名单的summary embedding被本地拒绝；随后仅临时清空隔离RAW KB summary_model_id完成剩余导入，全部源parse completed/pending0后已恢复原配置。该原失败记录完整保留，6次源embedding未重复。

当前default VM因复用已有g1-build模型执行环境正常暂停；不得遗忘恢复此前24个实际服务。最终以恢复后的live记录为准。
