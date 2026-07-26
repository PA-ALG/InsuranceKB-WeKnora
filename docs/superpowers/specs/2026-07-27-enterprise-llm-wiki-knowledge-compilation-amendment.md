# Enterprise LLM Wiki · 知识编译层修正案（Amendment 1 to 033）

> 日期：2026-07-27 ｜ 状态：业务方口头批准（"按你建议来，架构设计要进行更新"），
> 本文落地该批准；细则冲突时以本文与 23 号决策记录为准。
>
> 基线：`origin/main = dedbbafb`（PR #35/#36/#37/#38 已合入）。
>
> 性质：**修正案，不是重写**。033 的全部核心架构不变——PostgreSQL 权威、
> CAS + activation epoch、事务 Outbox、封闭 Provenance 三 kind、四种
> ReviewPolicy、G0 门禁与防刷规则、小 PR 交付纪律全部保留。本文只补
> 033 覆盖不到的**知识编译层**（怎么抽准、冲突怎么裁决、Schema/词表内容
> 从哪来），并调整首发画像。来源：外部诊断
> （enterprise-llm-wiki-gap-analysis-and-proposal）经独立对抗性裁决后的
> 采纳集；被拒绝的主张记录在 §6。

## 1. 修正的根本判断

033 把知识质量交给 G0 门禁**测量**，但没有为"达到质量"的方法与工程留
任何交付项：P5b1 的验收全是事务性（零半写/可追踪/不发布），八步抽取
管道（04 号）、权威序裁决（03 §6）、Schema/词表内容化均无 owner。若不
修正，可预测的结局是系统全绿、G0s/G0b 不过线，然后按 033 §18 停线返工
——恰是重置想避免的循环。本修正案把这些补为显式交付物。

## 2. 新增与扩范围的交付项

| 项 | 单一职责 | 依赖 | 说明 |
|---|---|---|---|
| **G0-probe**（新增，立即执行） | 弱模型可行性探针：dev 数据 + 现有 compiler + 真实弱模型粗测 field P/R、三态混淆、引文命中率，反向校准 G0a 阈值与 RequiredCoreCapabilitiesV1 | 无（已在执行） | 结论只用于校准，**不得作为任何验收证据**；历史唯一真实测量 F1=0.216 vs 目标 0.95/0.90，阈值冻结后不可删减维度，必须一次定对 |
| **P5b0**（新增） | 抽取策略合同：复用/收窄 028a 内容寻址 TemplateVersion 为四级 TemplatePackage registry（generic → line-of-business → document-type → product-family，后层只收紧）+ 不可变 approval + 固定失败阶梯 | C0 + P5a1 | G0a 冻结 `EvaluationProtocolV1`/`AutomationScopeV1` 需要抽取策略先有版本化权威载体 |
| **P5a1+**（扩范围） | SchemaVersion **内容化**（Golden Product 切片）：该险种全部字段的 type/单位/枚举/comparator class/required qualifier/**provenance class**/冲突策略 | C0；内容草稿可先行 | 范围收窄为 Golden Product 切片（非 276 字段全量，全量归企业阶段）；与概念词表 seed 合并为同一领域专家工作包（D-11） |
| **P5b1+**（扩范围） | 抽取质量机制并入 P5b1 Contract Card：闸 2 类型/跨字段硬校验、闸 3 高风险字段多弱模型独立取证（无共识即阻断，绝不投票了事）、闸 4 接受侧全集扫描（护栏必须成对，024 教训）、定向补漏（unknown → 同义词检索候选 chunk → 定向判断题）、**缺口驱动反向补抽**（新材料到达时对既存 unknown 做幂等、有预算的定向补抽，`(product_version, field, source_revision)` 幂等键 + `max_gapfill_attempts`） | P5b1 原依赖 | 闸 1（引文回验 fail-closed）033 已有；正向受影响闭包重编译 033 §10.3 已有，本项补反向路径 |
| **P5b2+**（扩范围） | `SourcePrecedencePolicyVersion`：六级来源权威表（条款/监管 > 说明书/官方 FAQ > 内部操作 > 培训 > 销售 > 外部；1/2 级不可下调）+ 确定性裁决序①身份②权威级③可靠时间④Evidence 完整性，同级不可裁定→ConflictSet；高风险字段无条件人工；被压制方保留 `contradicts` Evidence 不丢证据；全程写 `decision_basis` 可翻案 | P5a2 | 用 033 已有 `supersedes` 枚举，零新增原语；权威等级只来自已注册 source registration，分类模型只能建议 doc_role 不能授予等级；原⑤"弱模型共识建议"**后置**（它是建议器不是裁决器） |
| **P5a0+**（合同澄清 + 轻量扩展） | Contract Card 必须写明：**片段默认继承文档/章节归属，不逐片段解析实体**；备案号/条款编号为第一锚点（先于产品代码与别名）；判别特征交叉验证轻量版（用产品主数据既有字段做候选否决，相似度只用于召回候选、永不用于判定） | 003（已交付） | AmbiguityGroup 批量消歧工作台与 ResolutionExclusion 负向记忆归企业阶段 |
| **G0a+**（扩范围） | 金标标注 Agent 子系统：强模型标注（可插拔）→ 确定性验证（引文回验/类型/全字段覆盖，禁选择性标注）→ ≥2 强模型交叉一致 → 人工只审**分歧 + 全部高风险字段 + 5% 抽样**；分歧率回喂 Schema 修订 | P4c + P5a2（正式冻结）；标注草稿已先行 | 修订 033 §14.1"独立业务 reviewer receipt"的落地形态：高风险字段裁判必须是人（precision=1.00 的门槛不由模型当裁判），其余以标注协议 receipt 记录；holdout custody、一次性、全 attempt 计入等防刷红线一条不动 |
| **CAP0+**（扩范围） | 增加 `stock_backfill` 存量回填 workload 档位；launch 档位区分 `declared/measured` 两种 source_kind（declared 放行 P2a/P2b 设计，measured 才放行 P15，见 D-2026-07-26-1） | C0 | 已在实施（OpenSpec 036） |

## 3. 首发画像调整（D-7）

MVP 首发画像为 **`human_batch`-first**：

- 033 §14.2 第 6 条"机器审核自动发布**或**授权人一键批准"由 human_batch
  分支满足，MVP 证明清单不变；
- `machine_auto` 整条链（P2c 的 QualityProfileApproval registry +
  revocation、P7 的 approval/scope exact verifier、AutomationScopeV1 全套
  精确重验、shadow/canary）移为 **`P15[auto-profile]`** 条件画像，依赖
  G0b 批准后启用——与 033 既有的 P9b/G0v 条件画像模式一致；
- P2c 拆分：human_batch 也需要的部分（不可变 ReviewPolicyVersion 存储、
  Space policy pointer + epoch）保留在主线；approval registry 部分随
  auto-profile 后置；
- **G0b 保持为知识质量门禁不变**——人在审不等于允许知识是错的；后置的
  只是"G0b 作为自动发布资格"的那一半。

## 4. 关键建模决定（已拍板，进对应 Contract Card）

1. **D-6/D1**：`subject_ref` 绑定 **`product_version`**。版本间天然零冲突；
   文档正文不携带自身生效区间，有效期从 ProductVersion 主数据继承，
   版本编译的真实前置是文档归属判定（P5a0/003），不是抽取。P5a2 据此建模，
   不可逆。
2. **provenance class 进 Schema 内容**：每字段标注
   `source_evidence / human_attestation / external_sync / derived / undefined`；
   MVP 只发布 `source_evidence` 类；金标与覆盖率报表按此口径诚实呈现
   （Golden Product 实际可抽取覆盖率以 Schema 切片统计为准）。derived
   仍按 033 §10.5 排除，external connector 归企业阶段。
3. **长文本字段 comparator**：MVP 声明为 `text_keypoints_unknown`——运行时
   返回 unknown → 人审；019 keypoints 工具仅作 G0a 离线种子，运行时
   comparator 归后续版本。
4. **回滚粒度预期**：MVP 支持 Space 级快照回滚 + 经 SourceRetraction/
   emergency_withdrawal 的定向撤回（撤回=生成新 Release，不是回退指针）；
   不支持单页 cherry-pick 回退。主动撤回入口即 WeKnora source 禁用/删除
   （033 §10.3 既有机制）。此口径须写入给业务方的上线材料。

## 5. 后续版本（成立但不进 MVP）

P6c 概念层编译（009 复活：概念页/跨产品差异表/wikilink/断链门禁/冻结
投影/sense-split 检测，唯一键含恒为 sentinel 的 `sense_id`）与全量概念
词表 100–300 条 → **Milestone C**；P16 知识健康度三源缺口（011 复活）→
Milestone C（其中 Schema 完整度矩阵若 P9a 顺带可查则提前）；编译经济学
（优先级公式/归档不编译/dry-run 估算器）、AmbiguityGroup 工作台、长文本
运行时 comparator、Release 间 changelog 视图、外部 connector、批量
HumanAttestation UX、Space 粒度决策（D-6' 企业上线前定）→ 企业阶段。

## 6. 已裁决拒绝的主张（防止复议漂移）

1. "recall ≥0.90 数学上不可能"——**拒绝**：金标 recall 分母是文档中可
   回答的事实；人工填充/外部同步字段金标即 unknown，抽取输出 unknown 是
   正确。真问题是产品覆盖率预期，由 provenance class + 覆盖率报表解决。
2. "无主动撤回入口"——**拒绝**：WeKnora source 禁用/删除即主动入口
   （033 §10.3）。
3. "machine_auto 实践上永远开不起来"（吞吐论证）——**拒绝论证、采纳
   结论的另一依据**：contested 可发布、不占审核槽；采纳裁决序的正当理由
   是产品可用性（常态冲突有确定性正确答案，不应 contested 化）。
4. "人工工作量 O(片段数)"——**对 MVP 尺度拒绝**：文档级归属（003 实测
   100%）已把歧义压到文档级；修 P5a0 合同措辞即可，五层管道全量建设不是
   MVP 前置。

## 7. 修订后的 Milestone A/B 关键路径

```text
G0-probe ─────────────────────────────┐（并行，校准阈值）
Schema 切片 + 词表 seed 草稿 ─────────┤（并行，专家收口于 G0a）
                                      ↓
W0(→条件 W1) → P4a → P4c ─┬─────────→ G0a+ → P5b1+ → P5b2+ → G0s
C0✅ → CAP0 → P2a          ├→ P5a1+ ─┘
P1 → P3 → P2d、P5a0+、P5a2 ┴→ P5b0 ──┘
G0s → P6a → P6b → P7(human_batch 裁剪版) → P8 → P9a → G0b
machine_auto 链（P2c approval registry + P7 verifier + shadow/canary）→ P15[auto-profile]
```

Contract Card 义务不变：每个受影响 Pn 开工前引用本文对应行与 24 号处置
清单；实现窗口不得临场重裁本文已定事项。
