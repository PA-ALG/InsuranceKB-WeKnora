# G0-probe：弱模型可行性探针报告（CALIBRATION-ONLY）

- 日期：2026-07-27；决策依据：D4（业务方 2026-07-27 批准）
- 执行环境：worktree `/Users/houjing/code/kb_LLMwiki/ikb-probe`（对仓库只读；无 git commit/push；`git status` 无 tracked 变更）
- 输出目录：本目录（scratchpad/g0-probe/）；**零 PostgreSQL 知识表写入、零 WeKnora Wiki 写入、零发布、零 judge 回写/merge/release**

> **定位声明（硬约束）**：本报告是 **G0a 阈值标定前的离线校准测量（calibration-only）**，
> 与 goldenset 标注同性质的 dev 数据离线评测。**它不是验收证据，不得作为 G0/G0a/G0b
> 结果引用**。分数为裁决前（pending_judge 未回写）、金标为 wip-gs-v0.1（未冻结 seed）。

---

## 1. 测了什么

| 项 | 值 |
|---|---|
| 金标 | `dataset/goldenset/wip-gs-v0.1`（11/13 产品已标注，每产品 59–62 字段；schema `v1.1+b31a411c621c` 与当前 registry 完全一致） |
| 评分器 | `insurance_harness.goldenset.eval.evaluate`（v1 严格等价；e生保有 keypoints 时另跑 v2） |
| 弱模型通道 | **生产 CLI 的合法离线通道** `compiler.cli extract-replay`，`HARNESS_MODEL_PROFILE=offline-eval`（027 边界为 offline-eval 显式保留的入口；不是绕过 sealed 类）。真实百炼调用经 `OpenAICompatClient`（trust_env=False），全管道 load→split_route→extract(+006 fastpath)→gapfill(预算40)→vote→finalize |
| 模型 | `deepseek-v4-flash`（.env 既配弱模型，与 004 基线同型）；`qwen-flash`（生产批准族 qwen 的对照臂） |
| 产品 | 平安e生保（尊享版）医疗保险（medical）；平安盛世金越（尊享版26）终身寿险（分红型）（whole-life，命中费率表模板族） |
| 确定性 lane | 006 模板 fastpath（零 LLM）于 fam-04b9c55dc31e 两个分红型产品的费率表；金标引文回验 utility（verify_quotes+compare_with_meta）全 11 产品 |

**本探针真实经过的门**：quote 逐字回验（E3.2，失败打回→清零）、占位值清洗（E3.3）、
字段-值兼容（024 E6）、类型校验（E3.4）、006 模板 fastpath、gapfill（预算 40）、
高风险自一致性投票（同一弱模型 3 变体）、attempt ledger。

**本探针未经过的门（G0 结果不可由此推断）**：
1. 027 生产模型 admission（VerifiedAdmission/GuardedModelClient/sealed client）——offline-eval 配置合法绕行；
2. 裁决回写——judge_mode=claude-session，分歧仅入 judge-queue（pending_judge：1/1/2），分数为**裁决前**；
3. **真正多模型共识**——vote 是单模型自一致性，非 G0 目标的跨模型门；
4. **paired-scan（漏抽双扫）**——管道中尚不存在（P5b1+ 工程项）；
5. 017 linked lineage / WeKnora source 审计（Directory 源仅 page_only）；
6. 发布链全部环节（Candidate/Review/Release/投影）。

---

## 2. 关键数字

### 2.1 弱模型 lane（v1 严格口径，裁决前）

| 运行 | micro P | micro R | micro F1 | macro F1 | 幻觉率 | 证据引文回验 | pending_judge | 死信 | 调用 | 时长 |
|---|---|---|---|---|---|---|---|---|---|---|
| e生保尊享（medical）·deepseek-v4-flash | 0.172 | 0.135 | **0.152** | 0.520 | 0.069 | **1.000** | 1 | 2 | 137 | 750s |
| 盛世金越分红（whole-life）·deepseek-v4-flash | 0.345 | 0.286 | **0.313** | 0.552 | 0.034 | **1.000** | 1 | 0 | 78 | 334s |
| **合计 deepseek（2 产品）** | **0.259** | **0.208** | **0.231** | 0.420 | **0.052** | **1.000** | 2 | 2 | 215 | — |
| 盛世金越分红·qwen-flash（对照臂） | 0.220 | 0.257 | 0.237 | — | **0.220** | 1.000 | 2 | 0 | 86 | 81s |
| 参考：004 历史 e生保 pred（2026-07-12，裁决后）今尺重评 | 0.156 | 0.135 | 0.145（v2 0.174） | — | 0.094 | 1.000 | 0 | — | — | — |
| 参考：004 历史 3 产品合计（change 004 报告） | — | — | **0.216** | — | — | — | — | — | — | — |
| **G0b 目标** | **≥0.95** | **≥0.90** | — | — | — | — | — | — | — | — |

**量级结论：今天真实弱模型 + 当前全管道的 v1 严格 micro F1 ≈ 0.15–0.31（合计 0.23），
与历史 0.216 同一量级；距 G0b（0.95/0.90）差约 3–4 倍，不是调参距离，是结构距离。**

### 2.2 关键分解（合计 deepseek，2 产品，可评测金标 116 键）

三态混淆（行=金标，列=预测）：

| 金标 \ 预测 | present | absent_explicitly | unknown |
|---|---|---|---|
| present (72) | 55 | 0 | 17 |
| absent_explicitly (5) | 1 | 2 | 2 |
| unknown (39) | 2 | 0 | 37 |

- **present 检出精度 55/58 = 0.948**；present 检出召回 55/72 = 0.764；
- **检出后值一致率（v1 严格）仅 15/55 = 0.273 —— 这是全部分数塌陷点**；
- 幻觉率 3/58 = 0.052（deepseek）；qwen-flash 同口径 0.220（9/41），检出召回反而更高（0.91）。
- 跨模型对照：**值一致率 ~0.27–0.28 两模型几乎相同（口径/粒度问题），幻觉纪律差 4 倍（模型属性）**。

### 2.3 高风险字段（探针拆分）

| 子集 | 合计键数 | TP | FP | FN | P | R |
|---|---|---|---|---|---|---|
| schema `risk_level=high`（责任免除/等待期内出险处理/既往症/红利分配/演示利率/停售续保…） | 10 | 0 | 4 | 6 | 0.00 | 0.00 |
| 业务关键词（豁免/等待期/免责·除外/理赔/给付比例/免赔） | 15 | 0 | 5 | 9 | 0.00 | 0.00 |

高风险 v1 严格全灭——但注意结构：`责任免除` 两个模型的预测都是金标 218 字规范值的
**逐字 161 字前缀**（截断，非编造）；`等待期` 短字段类可对。距 1.00 目标的差距主要是
**长文本完整性**而非事实错误——这决定工程路线（见 §4）。

### 2.4 确定性 lane（零 LLM）

- **006 模板 fastpath**（fam-04b9c55dc31e 费率表，2 产品）：模板 2 字段 → **2/2 命中、2/2 与金标严格相等、引文 100% 回验**（交费期限 table_parsed；主附加险 structured_direct）。金标中落在费率表.pdf 的字段恰为这 2 个 → **该文档金标覆盖率 2/2 = 100%，零模型调用**。管道内运行同样命中（manifest fastpath_fields=2）。
- 但模板资产现状：**全库仅 1 个模板、覆盖 2/60 字段/产品**——确定性通道的上限由模板库规模决定。
- **金标引文回验 utility**（11 产品 660 条，420 条 evidence-bearing）：通过率 **95.2%**；20 条 disputed = 18 meta_mismatch（meta 权威字段与文档表述不一致）+ 2 quote_mismatch。金标本身的引文纪律是好的；meta 对齐是标注侧待清项。

---

## 3. Top-10 失败模式（例子已截断脱敏）与四门归因

「四门」= ① quote 回验 ② 硬校验（类型/占位/兼容） ③ 多模型共识 ④ paired-scan。
①② 已在管道内、本探针实测；③④ 是 G0 目标态、本探针未有。

| # | 失败模式 | 量级（合计） | 例（1 行） | 哪个门能接住 |
|---|---|---|---|---|
| 1 | **长字段截断/摘要式提取**（值粒度） | deepseek 40、qwen 23 条，FP 主体 | 责任免除=金标 218 字的逐字 161 字前缀 | ①②③④均接不住（引文真、类型对、双模型同样截断）→ 需 **P5b0：keypoint/v2 尺子 + 完整性（要点覆盖）校验** |
| 2 | **漏抽 present→unknown** | 17 条（e生保 10） | 产品类别=医疗保险 → unknown | **④ paired-scan** 专属靶；②的 routing 覆盖提升辅助 |
| 3 | **语义误归属**（引文真、贴错字段） | 每产品 1–2 条 | 交费方式 ← 填了交费期限的“趸交、3年…” | **③ 多模型共识**（两模型此处不同错）；①无效（引文逐字为真） |
| 4 | **常识默认值编造 unknown→present** | deepseek 2、qwen 6 | 宽限期=60日（金标 unknown）；保证利率=1.75% | **③**；①部分无效（能找到形似引文）；④的“无证据确认”扫描辅助 |
| 5 | **明示无被断言有 absent→present（最危险类）** | qwen 2、deepseek 0 | 全残保障：金标“无”→ 预测“包含” | **③** + 高风险人工复核；qwen-flash 单模型不可接受 |
| 6 | **三态口径冲突：带值的 absent** | 两模型各 1 | 是否可加保：金标 absent(不支持) vs 预测 present(不支持加保)——语义相同被判幻觉 | 无门可接——**G0a 度量合同要先修**（absent-with-value 约定） |
| 7 | absent→unknown 保守漏判 | 2 | 满期返还（无）→ unknown | **④**（absence 确认扫描） |
| 8 | 证据页错位（值对、页差>±1，不入 F1） | 9 | 犹豫期=20日，页码错位 | ①已把控字面回验；页锚定精化属 P5b0 |
| 9 | 传输/解析不稳定 | e生保 10 次 transport 重试→2 死信（丢 2 键召回）；4 次 parse 重试成功 | deepseek 当日显著变慢（750s vs 历史 559s） | 重试+ledger 已接住大半；死信=召回损耗，需容量与备用路由计划 |
| 10 | **模型间纪律差异** | qwen-flash 幻觉 0.22 vs deepseek 0.052 | 同产品同管道 | G0a 阈值必须**绑定具体模型身份（027 identity）**，不存在“弱模型统一阈值” |

---

## 4. 对 G0b 目标（P≥0.95 / R≥0.90 / 高风险 1.00）的校准判断

| G0a 维度 | 今天实测 | 现在可冻结？ | 依据 |
|---|---|---|---|
| 证据引文回验率 | 1.000（三运行全部；管道 fail-closed 强制） | **可，≥0.99** | 由代码门保证，非模型能力 |
| present 无证据输出 | 0（强制） | **可，=0** | 同上 |
| 出界/越 schema 键 | 0 | **可，=0** | schema 绑定抽取 |
| 幻觉率（pred=present 而金标非 present） | deepseek 0.052 / qwen-flash 0.220 | **可，但按模型身份分别冻结**；初始 ≤0.10（deepseek-class 过、qwen-flash 不过 → 门有区分度） | §2.2 |
| present 检出精度（三态层） | 0.948 / 0.78 | **可**，初始 ≥0.90（同上按模型） | §2.2 |
| micro 值精度 0.95 | 0.17–0.35（v1） | **不可** | 塌陷点在值一致率 0.27；需 P5b0（keypoint v2 尺子 + 粒度契约 + 完整性校验）先行，其后阶段目标 v2≥0.60 → P5b1+（真多模型+judge 回写）→0.80+；0.95 需模板/结构化通道放量 |
| micro 召回 0.90 | 0.14–0.29 | **不可** | 需 ④ paired-scan（尚无）、routing 覆盖、gapfill 放量、死信清零；纯 prompt 迭代不够 |
| 高风险 1.00 | 0/10（v1） | **不可（弱模型自由抽取路线到不了）** | 长高风险字段走 **确定性 fastpath/结构化导入 + keypoint 完整性 + 人工复核** 才有 1.00 语义；本探针 fastpath 2/2 全对是该路线的正面证据 |

**最小支持度建议**：任何冻结阈值的维度需 ≥30 个可评测金标键支撑；高风险类单产品只有
5–8 键，**必须以全组合（≥11 产品聚合）出数并保留逐条人工复核**，禁止用单产品高风险
样本冻结 1.00 门。wip-gs-v0.1 现有 660 键、约 420 evidence-bearing，够冻结上表
“可”行的维度；值精度/召回维度建议在 P5b0 落地后重测再冻结。

**一套可辩护的初始 G0a 数值（校准建议，非验收）**：
证据回验 ≥0.99；present 无证据 =0；越界键 =0；幻觉率 ≤0.10（按模型身份）；
present 检出精度 ≥0.90；三态 absent-with-value 口径先修（模式 #6）；
值精度/召回不设即时门——设 **P5b0 后重测门槛**（v2 micro P ≥0.60 / R ≥0.50 起步），
高风险字段走确定性通道 + 人工复核，不给弱模型自由抽取设 1.00 幻门。

---

## 5. 阻塞链与执行注记

- **无致命阻塞**。生产 CLI 的 `extract-replay + HARNESS_MODEL_PROFILE=offline-eval` 就是为本类离线评测保留的合法入口，未触碰 027 sealed 类；`baseline_004.py` 脚本已与现管道签名脱节（缺 `source`、model_profile 默认 fail-closed），本探针未用它跑模型，仅复用其金标装配逻辑。
- 凭据来自主仓 `harness/.env`（仅经环境变量注入子进程；本报告与所有产物不含任何 key/DSN；模型名与 endpoint host 视为非敏感）。
- deepseek 当日延迟偏高：10 次传输重试、2 死信（已计入召回损失）；qwen-flash 快 4–8 倍。
- 探针成本：3 次全管道运行合计 301 次调用、约 130 万字符 prompt（约 0.9M token 级）。

## 6. 产物清单（全部在 scratchpad/g0-probe/）

- `report.md`（本文件）
- `eval-summary.json`（三运行结构化指标汇总）
- `eval-esheng-zunxiang__deepseek-v4-flash.{json,md}`；`eval-shengshi-fenhong__deepseek-v4-flash.{json,md}`；`eval-shengshi-fenhong__qwen-flash.{json,md}`（逐字段/逐错误明细 + eval.py 官方渲染报告）
- `eval-combined-deepseek.json`（2 产品合计）
- `det_lane.json`（fastpath + 金标引文回验 utility 结果）
- `runs/<label>/`（pred.jsonl、manifest.json、judge-queue.jsonl、dead-letters.jsonl、attempt ledger——探针原始产物，未回写任何库）
- 脚本：`det_lane.py`、`score.py`、`smoke_llm.py`

（再次声明：以上全部为 calibration-only，不构成 G0 验收证据。）
