# 005 任务

- [x] T1 specs/eval-v2.md（从 proposal 推导可验证验收条款，SDD）
- [x] T2 keypoints 机制：`goldenset/keypoints.py`（KeypointEntry/split_keypoints/覆盖判定/加载）+ `load_release` 跳过 keypoints.jsonl（V1/V2.2）
- [x] T3 eval v2：`evaluate(metric="v1"|"v2")` 要点计分 + partial 覆盖率 + stale 回落；CLI `--metric`（V2）
- [x] T4 错误五类归因标签 + 工单化明细渲染（V3）
- [x] T5 eval-judge-queue 落盘（默认关；格式对齐 compiler JudgeRequest/Judgement，测试断言字段集合一致）（V4）
- [x] T6 漏抽归因工具 `compiler/recall_attribution.py`（纯确定性；manifest 无逐章节路由 → sections+routing_data 重算；注入式路由查询可单测）（V5）
- [x] T7 零成本定向修复：`routing_data.GROUP_KEYWORD_SUPPLEMENTS_005` 路由关键词补充（趸交/费率表 → basic_info；入出院记录/出院小结/结算清单 → claim_service）；压缩比预算复验 ≤0.40；清洗白名单经归因证据判定不需要（cleaning_kill=0），ReplayClient 单测锁定清洗行为（V6）
- [x] T8 小样要点生成 + v1/v2 对比报告脚本 `harness/scripts/eval_005.py`（gen-keypoints / report）；3 产品 keypoints.jsonl 入库；005 validation-report.md + 004 报告附"尺子修正后"章节（V1.4/V7）
- [x] T9 HANDOFF 更新（遗留 B 类：11 产品全量要点强模型生成；修复后 3 产品真实基线重跑命令）

状态：T1~T9 完成（2026-07-12）。零真实模型调用（离线重评 + 确定性归因 + ReplayClient 夹具）；
新增 23 个测试（test_eval_v2_keypoints.py / test_recall_attribution.py），既有 002/003/004 测试不破坏。

## 实现裁决记录

1. **long 字段口径 = 要点条目存在与否**（而非 schema value_type）：基线 YAML 无 value_type
   标注（仅 1 个字段显式 long），故 v2 的"long 型"由 keypoints.jsonl 条目驱动——有条目
   按要点计分，无条目回落 v1 短值口径。小样生成规则：present 且归一化 ≥30 字。
2. **V1.4 修正：切不出多要点的长值整值作单要点**。首版 "≥2 要点才生成" 漏掉了
   `discontinuation_renewal` 类不可切分长值（金标与预测几乎逐字一致仍被 v1 判错，
   bigram 容差本可判对，覆盖率 1.0）——证据驱动放宽为 ≥1。
3. **goldenset ↔ compiler 零依赖边界（05 §1.1）**：eval-judge-queue 行格式与
   `compiler.models.JudgeRequest` **结构对齐而非共享代码**（goldenset 定义
   `EvalJudgeRequest`，测试 `test_v4_2` 断言两侧字段名集合一致）；裁决回写沿用
   compiler `Judgement` 行格式，复用 claude-session 批处理形态。
4. **漏抽归因不读 checkpoint**：run manifest 只有 routed_pairs 计数、无逐章节路由记录，
   checkpoint.sqlite 是 langgraph 内部状态（解析脆弱）——按 V5.2 直接用
   `split_sections + route_groups` 确定性重算（结果与当次 run 一致，因路由是纯函数）。
5. **清洗白名单不改**：3 产品 26 条漏抽归因 cleaning_kill=0（无 placeholder 误杀证据），
   按"证据驱动，不做无病呻吟修改"原则保持清洗正则原样，仅以 ReplayClient 单测锁定现状
   （占位值→unknown+指针、真值不误杀）。
6. **路由补充词选择**：候选『费率|趸交』『通知|身份证件|诊断证明』会把 爱满分/福满分/至尊版
   条款压缩比推到 0.40 以上（E2.2 破算），逐词单测后收敛为
   basic_info+『趸交/费率表』、claim_service+『入出院记录/出院小结/结算清单』
   （13 条款最大压缩比保持 0.400）。e生保『产品类型』（证据埋在保险责任正文 P9）
   零成本关键词无法覆盖，留 prompt/补漏问题域。
7. **proposal §B7 死信自动复跑（截断升 max_tokens 重试一档）不在本次交付**：属 B4 的
   机制化，与本 change 的"零模型调用"约束正交，随下一个触碰 pipeline 的 change 实现。
8. **真实基线对比出分不跑**（业务方 token 成本纪律）：修复后 before/after 以确定性
   路由归因呈现（routing_miss 3→1）；模型侧对比命令列 HANDOFF 遗留 B 类。
