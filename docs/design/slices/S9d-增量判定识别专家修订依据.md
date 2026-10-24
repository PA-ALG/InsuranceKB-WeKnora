# S9d · 增量判定识别专家修订依据

> 状态：Claude 2026-10-24 提出；在 #299（S9 部署）第 4 步的上线验证中发现 ｜ 作者：Claude Code
> 依据：S8a（增量发布判定）、S9a（专家编辑平台）Spec §6；蓝图 §6.4
> 实现方：Claude ｜ 审核方：Claude 自审（Harness 单模块缺陷修复，净改动远小于 200 行，不改合同与接口）｜ 真实模型调用：0

## 1. 问题

S9a 上线验证要求：专家修订某字段后，再对该产品做增量发布，该字段应报告为冲突，线上值不变。

2026-10-24 实测：

- 用户把 2650 的"产品宣传语"从"材料未提及"改为有值，生成 epoch 50；
- 随后对 2650 做 `publish_changes --dry-run`，结果是 `BUNDLE_INVALID / CONVERSION_FAILED`，没有报告冲突。

**原因**：`changes/decision.py` 的 `_documents` 读取线上版本中本产品的每条 Claim，按 `source:v1:<knowledge>:<attempt>:<sha>` 解析每条依据的来源，求出它依赖的原始材料，任何不符合这个格式的依据都会抛出 `invalid source_ref`。

专家修订的依据由平台写入（`internal/enterprise/expert`，S9a §2）：

- `source_ref` 为 `expert:v1:<修订记录 ID>:<记录 SHA-256>`；
- `file_sha256` 为该记录的 SHA-256；
- `locator.kind` 为 `EXPERT_REVISION`。

S8a 的验收测试只用 PDF 依据构造"专家锁定"的 Claim，从未出现平台实际写入的专家依据，所以漏掉了。

**影响**：任何做过专家修订的产品，之后的增量发布都会中止。

## 2. 设计

只改 `harness/src/insurance_harness/changes/decision.py` 的 `_documents`：

- **专家修订依据**（`locator.kind == EXPERT_REVISION`）：
  - 只接受 `expert:v1:<非空 ID>:<64 位十六进制>`，并要求末段等于 `file_sha256`（不区分大小写）；格式不符仍抛出 `invalid source_ref`；
  - 它引用的是修订记录，不对应任何原始材料，所以不计入依赖材料集合。
- **其他依据**：规则不变。

这样，专家修订过的 Claim 依赖材料集合为空，"材料撤回"永远不会撤掉它；同时它带 `expert_lock`，新编译值与之不同时，走已有的"冲突"分支，相同时为"不变"。判定规则本身不改。

不做：
- 不改平台写入格式与合同（`contracts/` 已允许 `EXPERT_REVISION` 定位）；
- 不改 S8a 判定顺序。

## 3. 验收（RED，Claude 编写，受保护）

`harness/tests/changes/test_expert_revision_base.py`，线上版本中的专家修订 Claim 按平台实际写入的形状构造：

1. 新编译给出不同的值 → 该字段判为 `CONFLICT`，不进入发布成员，其他字段照常判定；
2. 新编译给出相同的值 → `UNCHANGED`；
3. 当前材料集合不含任何原依据材料，且新编译没有这个字段 → `KEEP`，不撤回；
4. 专家依据的 `source_ref` 末段与 `file_sha256` 不一致，或前缀不是 `expert:v1:` → 仍拒绝（`ValueError`）。

S8a、S8b 的原有测试照常通过。

## 4. 改动范围

- `harness/src/insurance_harness/changes/decision.py`；
- `harness/tests/changes/test_expert_revision_base.py`（RED）。

## 5. 上线与验证

- Harness 不进镜像，合并即生效。
- 合并后，用 2650 重跑 `publish_changes --dry-run`（只读，0 次模型调用）：确认"产品宣传语"报告为冲突、不在发布成员中，结果回报到 #299。
