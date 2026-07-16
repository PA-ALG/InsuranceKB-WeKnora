# 024 任务（TDD 顺序；测试名引用条款号）

> 轨道 L5（见 docs/insurance-kb/22），零真实模型调用。二版（2026-07-16）：证明力边界按 PR #11 复审收紧——零调用侧只交付机制/版本化/护栏/非退化框架，真实召回结论归 020 D4。
> **实施记录（2026-07-16，执行者=Claude 架构会话，worktree `ikb-024`）**：T1 先立 38 条 RED（红全部落在规格行为断言上，骨架先行保 mypy/ruff 绿）→ T2~T6 逐任务转绿 → 全量 deterministic **1314 passed / 5 deselected**（基线 1265 零破坏）。

- [x] T1 归因工单固化：005 清单逐条 → 机制合同回放用例（E1.1；24 extract_empty + 1 prompt 域 routing_miss 注册表自检对账；`tests/support/recall_tickets_024.py` + `tests/test_recall_uplift_024.py`）
- [x] T2 prompt 变体机制：注册表 + 确定性选择 + **版本化**审计标识 + 默认回落零漂移（E2；`compiler/variants.py`，gapfill 三条返回路径盖 `metadata["prompt_variant"]`）
- [x] T3 定向补漏：**schema 驱动触发**（触发器/组装签名审计不含金标）+ evidence 回验与反幻觉回归（E3；`build_targeted_gapfill_user` 短答形态，16 个工单字段精确注册）
- [x] T4 值粒度字段级指引并入变体（E4；`GRANULARITY_GUIDANCE` 挂 10 个长文本工单字段，prompt 快照断言 + 契约零改动）
- [x] T5 后处理非退化合同：冻结录制集回放评分下界断言进 deterministic 门禁（E5；`tests/test_recall_probe_024.py`——9 条冻结录制覆盖全后处理分支 + request_key/manifest/control 变体三重钉桩）
- [x] T6 弱值/兼容性护栏：WEAK_UNACTIONABLE+REFERENCE_ONLY 两族入 cleaning + 字段-值兼容性校验 + Q012/Q026 历史 bug 用例（E6；占位清洗零漂移由全量回归实证）
- [x] T7 收尾：validation-report（工单状态表 + 非退化结果 + 变体版本清单 + "真实召回结论留待 020 D4"显式声明，E5）→ HANDOFF 更新 → 020 D4 A/B 交接说明（按变体版本对账）

## 裁决记录（设计判断及依据）

1. **RED 落点纪律**：第一版红墙落在 ImportError/mypy 上被业务方纠正——改为骨架先行（`variants.py`/`compat.py` 带类型、行为显式未实现），38 条红全部是规格行为断言，mypy/ruff 全程绿。
2. **注册表形态**：代码内纯数据常量而非 YAML——确定性、mypy 校验、与 `routing_data` 同风格（E2.1"单一权威来源"）。
3. **注册粒度**：字段级精确注册（16 个工单 field_id），不做组级注册——组级会波及既有字段的 prompt，破坏零漂移边界（既有 ReplayClient 全管道回放的 request_key 必须不变）。
4. **E2.2 落点**：规格是"**每次抽取的 pred** SHALL 记录所用变体版本化标识"——初版只盖 gapfill 三条返回路径，首轮/fastpath/vote/judge/dead_letter 漏盖（gauntlet F7 抓出）。返工后：首轮在 `extract.py:_extract_batch` 按 (组,field_id) stamp，其余在 `pipeline.merge_candidates` finalize 兜底 stamp，与 gapfill `_variant_for` 同一注册表。抽取主 prompt 仍未接变体**模板**（treatment 生效面=gapfill），但**标识已全覆盖**，020 D4 A/B 可对账全部 pred。（初版"待同步"的自我豁免是错的——规格权威高于便利，见 doc-19 教训。）
5. **兼容性接线**：校验链新增 2.5 步（占位清洗后、类型校验前），不兼容→unknown+`incompatible_value`+metadata 审计（不打回不重试——与占位同为"非惩罚性转 unknown"）；gapfill 循环内则视作该段无线索继续下一候选（召回友好）。`UnknownReason` 增值 `incompatible_value`（归因器按字符串匹配 placeholder，不污染 cleaning_kill 桶）。
6. **兼容性规则防误杀**：双条件命中（字段名 ∧ 值形态）+ 排除词（"退保费用"字段自身不触发退保规则）。
7. **E5.1 探针形态**：仓库无真实模型已提交录制集（005 基线为实跑未存响应）——以冻结响应常量充当"未变更录制集"，三重钉桩（control 变体=default@v1 / 9 条 request_key / manifest SHA-256）保证"prompt 漂移或录制改动即显式失效 fail，不得静默换基线"；评分下界=每产品 1.0。**真实 3 产品录制集探针随 020 D4 建立**（交接见 validation-report §4）。
8. **引用型边界**：REFERENCE_ONLY 要求"整值即指针"（≤6 字尾注），防止吞掉含实值的长句；weak/reference 两族为新增模式，既有 30 条占位模式与语义零改动（E5.2，全量 1314 回归实证）。

9. **Gauntlet 返工（2026-07-17）**：独立 fresh-eyes 红队 + 真金标 live 复现抓到 7 项已修（详表见 validation-report §7）。**最严重 F1/F2**：compat 护栏用真金标复现误杀 `保证续保期="20年"`、`费用="…提前退保影响…"`——"召回提升"改动本会净召回回归。根因=只测拒绝侧（Q012 命中）、无接受侧（真金标不被误杀）。修法：规则按判别式收紧（`field_not`/`value_not`/退保损失签名）+ **新增 goldenset 全集"误杀防线"**（`test_recall_accept_side_024.py`）；拒绝侧 Q012 三案仍全绿。F5 探针绑定真实调用路径、F6 gapfill 拒绝原因可审计、F7 变体标识全覆盖（见 #4）。probe_fee 拒绝原因升级触发 manifest 有意重钉。**教训**：护栏与召回是成对约束；半个护栏（只拒绝侧）比没有更危险，因它伪装成"已防护"。

约束：文件域仅 compiler/ + tests；不调真实模型；不动 cleaning 白名单既有语义/尺子/knowledge/；金标只出现在测试评分；送审前过 21 号自测 gauntlet。
状态：**T1~T7 全部完成 + gauntlet 返工闭合**，门禁全绿（ruff / mypy 187 files / deterministic **1326 passed** 零破坏）；待 PR 双查（Owner=B 域）。依赖：004/005 已合入。
