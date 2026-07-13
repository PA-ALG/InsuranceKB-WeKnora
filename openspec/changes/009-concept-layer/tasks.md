# 009 任务

- [ ] T1 concepts/concept_aliases/claim_concepts 迁移 + 概念词表导入（C1）
- [ ] T2 确定性关联 + 重算幂等 + 拉黑表（C2）
- [ ] T3 概念主页编译器（差异表/义项索引）（C3）
- [ ] T4 wikilink 注入 + 悬挂链接硬门禁（C4）
- [ ] T5 purpose.yaml 加载与唯一注入点改造（C5，涉及 compiler/prompts 重构——注意与 006 交付物协调）
- [ ] T6 端到端夹具用例（C6）
- [ ] T7 validation-report + HANDOFF 更新

约束：零模型调用；发布走 007 服务层；prompts 改造不得破坏 004/006 既有快照测试（先读再改）。
状态：待接手（遗留 B11）。依赖：007 已合入；006 合入后再动 prompts（避免冲突）。
