# codex 六轮复审返工 + R7 提交前红队 —— 复现脚本与证据归档

本目录归档 codex 第六轮复评（2×P1 + 1×P2）的复现脚本，以及修完后**提交前**自派的 R7 红队（E/F）复现脚本。

- codex 六轮攻击 head：`8fdd696`（R6 修复后）
- R7 红队方法：修完 2×P1 后**不等下一轮**，派 2 支 general-purpose 红队各攻一个新面，写脚本 live 复现才算数。
- 结果：codex 2×P1 复现数值与报告完全一致、已修；R7 红队两个高危方向**攻不破**，各挖出 1 个**低危残留并当场
  修掉**。全部并入 `68bc45a`。

> 脚本按攻击时 head 原样归档（仅便携化本机绝对路径）。对当前已修 head 运行，修复会把拒绝点前移/翻转结论
> ——即修复生效。可维护回归证据是已提交的 `test_*` 用例（见下）。

> **归档收敛（codex 七轮建议，本次清理）**：r7/ 下 ~11 支探针脚本已删，仅留 codex 六轮 2×P1 复现
> `repro_codex6.py`。下文 E/F 段与表中**其余**文件名是归档当时的探针，其对抗价值已固化为文末 `test_*`
> 锁定用例；需原始脚本见 `git show 5c67b10`。

## codex 六轮 2×P1（`repro_codex6.py`，@ `8fdd696` 复现）

| # | 修复前（live） | 修复后 | 锁定用例 |
|---|---|---|---|
| #1 disputed 键预测被计幻觉 | `field.hallucination = 0.0909`（=1/11），合格字段失格 | `0.0`（加 disputed 样本不改任何指标） | `test_q3_1_disputed_key_prediction_not_counted_as_hallucination` |
| #2 reset 大小写变体绕过 | 同 digest 仅大写 → `reset APPROVED (BYPASS)` + gate eligible | `REJECTED`（同评测基准必回归） | `test_q4_6_reset_rejects_same_golden_hash_case_variant` 等 |

修复：`eval.excluded_disputed_keys` 单一"可评测键"权威（evaluate/build_profile 共用）；`Sha256Hex` + `_canon_hash`
单一 canonical 身份原语。

## R7 红队（E: disputed 完备性；F: 身份规范化）

- **E — 攻不破**（disputed 完备性，7 支探针含 2000 随机迭代）：加任意形态 disputed 样本/预测不改任何指标；
  evaluate↔build_profile 零漂移；同 key 既 disputed 又可用按可用金标评测；端到端资格不变。
- **F — 两高危方向攻不破**（身份规范化，2 支探针）：换非-golden 维度开不了 reset；11 处 hash 比较仅 reset
  成员测试 fail-open（已规范化），其余 10 处 `==` 绑定 fail-closed。

红队各挖出 1 低危残留，**已修 + 已锁用例**：

| 来源 | 残留（低危） | 修复 | 锁定用例 |
|---|---|---|---|
| F | `model_copy`/`model_construct` 绕过 `Sha256Hex` 构造期规范化（容器无 `revalidate_instances`）→ 大写 digest 达 reset 比较重开 #2 | `_canon_hash` 在**比较点**兜底规范化 | `test_q4_6_reset_rejects_uppercase_hash_smuggled_via_model_copy` |
| E | 非 reset 回归未校验候选与基线同 golden 集 → 候选借 disputed 削弱评测集（≤5% 过 validator）藏退化 | 非 reset 回归对称要求 `golden_release_hash == 生产基线` | `test_q4_6_non_reset_regression_requires_same_golden_set` |

## 复现方式

```bash
cd harness
uv run python ../openspec/changes/019-golden-quality-gate/redteam/r7/repro_codex6.py
```
要复现 codex 六轮 before（真绕过），先 `git checkout 8fdd696`。维护的回归证据：
```bash
cd harness && uv run pytest tests/test_goldenset_baseline_019.py tests/test_goldenset_profile_019.py \
  tests/test_quality_gate_019.py -k "disputed_key_prediction or golden_hash or golden_release_hash \
  or smuggled_via_model_copy or non_reset_regression_requires_same_golden or gate_error_fails_closed" -v
```

上级 `../README.md` 为 R6 归档；`../../{tasks.md, validation-report.md}` 的「六轮 + R7」小节为完整叙述。
