# 005 规格（验收条件）——eval v2 与召回归因

> 由 proposal.md 推导的可验证条款；测试名引用条款编号（10 §2 TDD 约定）。
> 影响面：`harness/goldenset`（eval/keypoints）、`harness/compiler`（recall_attribution、
> routing_data 关键词补充）；不动金标已有标注值；零真实模型调用。

## V1 金标要点清单（keypoints，机制先行）

- V1.1 要点清单为独立文件 `keypoints.jsonl`，挂在金标数据旁：release 布局为
  `<release>/keypoints.jsonl`，wip 布局为 `wip-gs-v0.1/<产品>/keypoints.jsonl`；
  行模型 `KeypointEntry`：`product_id / field_id / keypoints[] / contradictions[] /
  source / golden_value_sha`（金标值归一化 sha256 前 12 位，防金标改值后要点漂移）；
- V1.2 `load_release` 读金标目录时必须跳过 `keypoints.jsonl`（与 `disputed.jsonl` 同级
  的非金标记录文件），002 既有 release 测试不破坏；
- V1.3 首版要点由**确定性规则**从金标 value 切分（分号/句号/换行/序号“1.”“（一）”“①”），
  归一化后 <4 字的碎片丢弃、去重；不调任何模型；`split_keypoints` 有单测；
- V1.4 本 change 对 004 的 3 个基线产品生成小样要点：金标 present 且 value 归一化
  ≥30 字的字段生成（长文本字段口径；切不出多个要点时整值作单要点——仍获得
  bigram 容差匹配，逐字等价过苛问题同样存在于不可切分长值）；生成脚本幂等可重跑；
- V1.5 11 产品全量要点（强模型产出）**不在本 change**——列 HANDOFF 遗留 B 类。

## V2 eval v2：关键要点匹配计分

- V2.1 `evaluate(..., metric="v2", keypoints=...)`：对金标/预测均 present 的样本，
  若存在该 `(product_id, field_id)` 的要点条目 → 按要点覆盖率计分；否则回落 v1
  确定性等价（短值口径不变）；
- V2.2 要点覆盖判定（确定性，零模型）：归一化子串命中，或要点字符 bigram 被预测值
  覆盖比例 ≥0.8（表述差异容忍）；覆盖率 = 命中要点数 / 要点总数；
- V2.3 主判定二值化：覆盖率 ≥0.8 且无矛盾要点命中 → 值正确（TP）；否则 FP+FN
  （错误类型 value_mismatch，携带覆盖率）；
- V2.4 `contradictions[]` 命中（归一化子串）→ 一票否决判错，即使覆盖率达标；
- V2.5 `golden_value_sha` 与当前金标值不符 → 该条目视为过期，回落 v1 并计入
  `stale_keypoints` 计数（报告呈现）；
- V2.6 partial 展示：报告含要点计分样本的逐条覆盖率列（产品/字段/覆盖率/判定），
  主指标仍按 V2.3 二值化；
- V2.7 v1 口径保留可切换：`--metric v1|v2`（CLI 默认 v1），`evaluate` 默认行为与
  002/004 完全一致（既有 135 测试不破坏）。

## V3 报告错误分类（工单化）

- V3.1 每条错误带五类归因标签之一：
  `值粒度`（present/present 值不等价）、`漏抽`（金标 present → 预测 unknown/缺行）、
  `幻觉`（金标 unknown/absent → 预测 present）、
  `三态混淆`（present↔absent_explicitly 错位、absent↔unknown 错位）、
  `证据错位`（值判对但预测证据页与金标证据页不相邻，±1 容忍；不改 F1，单列计数）；
- V3.2 报告含错误类型分布表 + 工单化明细（标签 → 建议动作，逐条列出金标值/预测值摘要）；
- V3.3 分类逻辑纯函数化并单测覆盖五类各至少一例。

## V4 eval-judge-queue 落盘（默认关）

- V4.1 要点匹配"不确定带"（覆盖率 ∈ [0.5, 0.8) 的判错样本）视为待裁决；CLI
  `--judge-queue <path>` 显式给出才落盘，默认关闭；
- V4.2 队列行格式与 compiler 裁决通道对齐：字段集合与 `compiler.models.JudgeRequest`
  一致（goldenset 不 import compiler 实现——05 §1.1 零依赖边界；用测试断言两侧
  字段名集合对齐），`reason="keypoint_uncertain"`；裁决回写行沿用
  `compiler.models.Judgement` 格式（复用 claude-session 批处理形态）；
- V4.3 关闭时报告标注未裁决计数（`judge_pending`），打开时同时落盘同样计数。

## V5 漏抽归因工具（纯确定性，零模型调用）

- V5.1 对金标 present / 预测 unknown（或缺行）的字段逐条归因：
  `routing_miss`（金标证据页不在该字段所属组的路由章节内）/
  `extract_empty`（在路由内但抽取为空）/
  `cleaning_kill`（预测 `unknown_reason=placeholder`，清洗误杀）；
- V5.2 路由结果获取顺序：run manifest 无逐章节路由记录 → 基于
  `sections.split_sections + route_groups`（routing_data 关键词）对原 PDF 确定性重算；
  核心归因函数接受注入的路由查询（无 PDF 也可单测）；
- V5.3 输出归因统计 + 逐条清单（产品/字段/组/文档/证据页/归因/unknown_reason）；
  004 的 3 产品漏抽样本全部带归因标签；
- V5.4 金标无证据页的漏抽样本标 `no_evidence_page`，不强行归因路由。

## V6 定向修复（仅零成本类）与回归

- V6.1 依据 V5 归因做路由关键词补充（`routing_data.ROUTING_SUPPLEMENTS_005`，
  与 004 基线关键词分开存放，before/after 可复算）：修复后原 routing_miss 样本的
  金标证据页进入路由（单测断言）；
- V6.2 修复不破坏 E2.2 预算：13 份样本条款 (组×章节) 压缩比仍全部 ≤0.40
  （validation-report 重算逐文档表）；
- V6.3 清洗白名单：本次归因 `cleaning_kill=0`，**不改清洗正则**（证据驱动，不做
  无病呻吟的修改）；清洗行为现状用 ReplayClient 端到端单测锁定（占位值→unknown、
  真值不误杀）；
- V6.4 修复后的对比出分（真实弱模型重跑 3 产品基线）**不在本 change 内跑**：
  命令与预期成本写入 HANDOFF 遗留 B 类。

## V7 报告与文档

- V7.1 对 004 已有 3 产品 pred 重跑 eval v1 与 v2，产出对比报告
  `openspec/changes/005-eval-refinement-recall/validation-report.md`：
  v1 vs v2 分数（micro/macro/幻觉率）、错误类型分布、要点覆盖率明细、漏抽归因统计
  与逐条清单、修复 before/after 路由归因对比；
- V7.2 004 `validation-report.md` 附加“尺子修正后（005 eval v2）”章节（引用 005 报告）；
- V7.3 eval 自洽性仍满分：金标自评（golden vs golden）在 v1/v2 口径下 micro F1 均为 1.0；
- V7.4 门禁：`ruff check` + `mypy src tests` + `pytest -m "not live"` 全绿，
  002/004 既有 135 测试不破坏；HANDOFF.md 更新（B 类新增全量要点生成与基线重跑）。
