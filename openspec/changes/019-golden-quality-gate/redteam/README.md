# 019 提交前独立红队自测（R6）——复现脚本与证据归档

本目录归档 019 五轮 codex 返工**修完后、提交前**主动进行的一轮独立对抗性红队自测的复现脚本与证据。
**非 codex 触发**——目的正是"提交前把问题自测修掉，别再来回 review"。

- 攻击目标 head：`51ad8aa`（codex 五轮修复后）
- 方法：4 支并行的 general-purpose 红队 agent，各攻一个面，**每条发现都要求写脚本 live 复现才算数**
  （不接受走查猜测）
- 结果：**2 支无绕过**（领域类型、字段聚合），**2 支各挖出真问题**——含 1 个端到端真绕过 + 1 个
  五轮自己引入的纵深防御倒退。全部已 TDD 复现→修→复跑关闭于 `0500859`。

> 复现脚本为 print 式探针、**按当时 head `51ad8aa` 原样归档**（仅把硬编码的本机绝对路径便携化）。
> 对**当前已修 head** 运行时，修复会把拒绝点**前移**（如空白 `baseline_id` 在**构造期**即被 `Identifier`
> 拒，脚本会在该处 raise）——这本身就是修复生效的表现。**可维护的回归证据是已提交的 `test_*` 用例**
> （见下表"锁定用例"），红队脚本是历史复现物。

> **归档收敛（codex 七轮建议，本次清理）**：raw/ 下 ~13 支探针脚本已删，仅留关键真绕过复现
> `raw/s2_reset_downgrade.py` + 共享 `raw/fixtures.py`。下表"脚本"列与证据段中**其余**文件名是归档当时
> 的探针，其对抗价值已固化为文末 `test_*` 锁定用例；需原始脚本见 `git show 8fdd696`。

## 四支红队与结论

| 红队 | 攻击面 | 结论 | 锁定用例（脚本已收敛） |
|---|---|---|---|
| A | 领域类型合法域完备性（NaN/±inf/越界/负计数/bool 强转/宽松阈值渗入 verdict·回归·gate） | **无绕过**（每路径逐脚本证明构造期即挡） | 收敛入 `test_*` 领域类型/约束用例 |
| B | 字段聚合口径（未知 field_id pred-only 隐身、支撑/分母漂移、build_profile↔evaluate 漂移、evidence=None 交互） | **无绕过**（逐字段零漂移，端到端仍被 gate 拒） | 收敛入 `test_*` 聚合/漂移用例 |
| C | gate·merge 自动路径（删预检查开窗、旧签名 gate、版本时序、pending 与其他 deny 顺序） | **发现 2 弱点**（C-2b 纵深防御倒退、C-2a 崩批），均需注入不合规 gate 才触发；已修 | `test_q4_2_pending_short_circuits_even_if_gate_ignores_it`、`_gate_error_fails_closed_not_crash` |
| D | 批准·lineage_reset（空白 reason、跨 lineage 降级、首批准自洽、latest 操纵、伪造 prior_profile） | **发现 1 真绕过**（弱点1 reset 洗白降级，端到端）+ 3 弱点；已修 | `raw/s2_reset_downgrade.py`（保留）+ `test_q4_6_*` |

## 两个真问题：before → after 证据

### D-弱点1（中，端到端真绕过）：reset 只查 baseline_id、不查 golden 集 → 同评测基准洗白降级

`baseline_id` 是可随意更换的**标签**，不是"新 lineage"的证明；真不变量是**评测基准（`golden_release_hash`）
变了**。同一 golden 集换个新 id + `allow_lineage_reset=True` 即跳过零容差回归。

**before（`raw/s2_reset_downgrade.py` @ `51ad8aa`）**——退化画像端到端拿到自动发布资格：
```
攻击 A：同一 fingerprint（同 golden 集）+ 新 baseline_id 'gs-v2-rebrand' + reset
  evil.fingerprint == prod.fingerprint ? True
  reset -> ACCEPTED !!! baseline_id=gs-v2-rebrand v1 lineage_reset=True（回归被完全跳过，尽管是同一 golden 集）
  QualityGate.decide -> eligible=True   >>> 端到端洗白成功
```
**after（同脚本 @ `0500859`）**——reset 逃生门被堵：
```
攻击 A：同一 fingerprint（同 golden 集）+ 新 baseline_id 'gs-v2-rebrand' + reset
  reset -> REJECTED: lineage_reset 必须是真正的新评测基准：golden 集 rh1 与现有生产基线相同——同一 golden 集必须走零容差回归
```
**修复**：`approve_baseline` reset 分支要求 (a) prior 非空 (b) baseline_id 不在 prior
(c) **`golden_release_hash` 与所有 prior 不同** (d) 非空 reason。
**锁定用例**：`test_q4_6_lineage_reset_same_golden_set_rejected`、
`test_q4_6_reset_cannot_launder_same_goldenset_downgrade_end_to_end`（常规回归 + reset 逃生门双双拒）。

### C-2b（中，五轮自引入的纵深防御倒退）：删掉 merge 层 pending 预检查

五轮为"pending 收回 gate 单一权威"删净了 `MergeEngine` 三条自动路径的 `and not prop.pending_judge`——
pending 安全从此 100% 押在注入 gate 正确 honor 上。

**before（探针 `attack_merge.py` @ `51ad8aa`，脚本已收敛入锁定用例；输出存档如下）**——注入不 honor pending 的 gate：
```
注入 decide(**kwargs) 但忽略 pending_judge 的 gate（模拟 020 写错）
  pending=True 候选 -> status=published   >>> BYPASS：pending 被自动发布
```
**after**：`_gate_ok` **恢复独立 pending 短路**（gate 仍权威，merge 保留 fail-closed 兜底两道防线）；
另 gate 抛异常/旧签名一律 fail-closed 走 ReviewItem、不崩整批（C-2a）。
**锁定用例**：`test_q4_2_pending_short_circuits_even_if_gate_ignores_it`、
`test_q4_2_gate_error_fails_closed_not_crash`（均端到端 merge）。

## 只文档不改（附理由，非"已全闭环"的空话）

- **D-弱点4**（latest 选取被 `approved_at`+id 字典序操纵）：依赖弱点1 或伪造 prior 先注入弱基线；弱点1
  修完堵死注入入口，伪造 prior 属 020 存储完整性边界（本层 `prior` 视为可信）。
- **首基线批准不查全局指标**（红队 B 观察 B）：`approve_baseline` 仅 prior 非空才回归，首基线只过结构性
  blocker；但在线 `QualityGate.decide` 是**逐字段** fail-closed，脏字段仍被 `field_verdict` 绝对阈值拦、
  好字段本就应可发——加全局绝对下限恐误杀难产品的合法首基线，故不加、记分层设计边界。
- **A-1**（`ApprovalRecord.version:int` 可负）：仅可信 `prior` 排序 tiebreaker，非指标/计数阈值。
- **A-3**（020 加载须 `model_validate`）：领域类型（Rate/NonNegativeInt/Identifier）仅在**验证式构造**时
  load-bearing；020 从磁盘反序列化画像/artifact 必须走 `model_validate` 而非 `model_construct`。

## 复现方式

红队脚本需 harness venv：
```bash
cd harness
uv run python ../openspec/changes/019-golden-quality-gate/redteam/raw/s2_reset_downgrade.py
```
要复现 before（真绕过），先 `git checkout 51ad8aa`；当前 head 上脚本**在构造期即 raise**（`fixtures.py`
按 `51ad8aa` 原样保留 era 哈希 `'rh1'`，现被 `Sha256Hex` 于 `RunFingerprint` 构造处拒——拒绝点已前移，
即修复生效）。可维护回归证据是锁定用例，直接跑：
```bash
cd harness && uv run pytest tests/test_goldenset_baseline_019.py tests/test_quality_gate_019.py \
  -k "same_golden_set or launder_same_goldenset or pending_short_circuits or gate_error_fails_closed \
      or without_prior_is_rejected or baseline_id_rejects_surrounding" -v
# → 11 passed
```

详见同目录上级的 `tasks.md` / `validation-report.md` 的「R6」小节。
