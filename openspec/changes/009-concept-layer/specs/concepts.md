# 009 规格（验收条款，每条对应 pytest 用例）

## C1 概念注册

- C1.1 concepts / concept_aliases / claim_concepts 表（Alembic 增量迁移，downgrade 干净）；concept 稳定 ID（slug 化名称+hash），别名唯一约束；
- C1.2 初始概念源：glossary.yaml 全量导入（就医绿通/费用垫付/其他增值服务）+ 概念词表 YAML（可扩展，如 犹豫期/等待期/宽限期/保单贷款/减额缴清/现金价值）；导入幂等；
- C1.3 LLM 概念候选接口留 stub（claude-session 形态，默认关）——新概念只能经审核转正，不得自动入注册表。

## C2 概念-Claim 关联

- C2.1 确定性关联：Claim 的 field_name/value 命中概念词/别名（归一化子串+词边界规则）→ 建 claim_concepts 边，记命中依据；
- C2.2 关联幂等可重算：`relink-concepts` 全量重建结果与增量一致；
- C2.3 误关联防护：命中依据可追溯，人工可拉黑（concept_id+field_id 级排除表），拉黑后重算不再关联。

## C3 概念主页编译

- C3.1 概念主页 = 定义区（术语表/审核口径）+ **跨产品差异表**（行=产品，列=该概念下关键字段的 published Claim 值+证据角标）+ 义项索引（每行链接 `[[产品限定页slug#锚点]]`）；
- C3.2 只聚合 published Claim；无任何关联 Claim 的概念不生成页面（避免空页）；
- C3.3 Claim 变更（supersede/retract）后重编译，差异表反映新值（复用 007 重编触发）。

## C4 wikilink 互链

- C4.1 产品页渲染时概念词替换为 `[[concept-slug|原词]]`（每页每概念只链首次出现，避免链接噪声）；
- C4.2 概念页出链回产品页；发布前**无悬挂 wikilink 硬门禁**（引用的 slug 必须在本次发布集或已发布集中，断链拒发——对齐 12 #3）；
- C4.3 发布经 007 发布器（mock 断言页面 create/update 与互链字段）。

## C5 Purpose 注入

- C5.1 KB 级 `purpose.yaml`（领域意图/合规口径/引用要求/禁用表述），加载 fail-fast、内容 hash 版本化；
- C5.2 注入点唯一：compiler/prompts 的 system 组装函数——抽取、补漏、编译、（未来）健康度审计共用；单测断言 prompt 快照含 purpose 段与版本标识；
- C5.3 purpose 变更记录进 run manifest（可追溯"这批抽取用的什么口径"）。

## C6 端到端

- C6.1 夹具：3 产品共享"犹豫期""保单贷款"两个概念 → 概念主页含 3 行差异表、义项链接可解引用、产品页出现互链且无悬挂；
- C6.2 supersede 其中一个 Claim → 概念页差异表更新；
- C6.3 零真实模型调用；门禁全绿（既有测试不破坏）。
