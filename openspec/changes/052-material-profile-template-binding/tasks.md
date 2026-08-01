# 052 · MaterialProfile → TemplatePackage Implementation Plan

> **For agentic workers:** 本任务已在独立 worktree 内获批执行；严格按
> checkbox 顺序进行。禁止提交、push、PR 或新增第九路径。

**Goal:** 为 ProductVersion `596-1` 三 PDF 交付一个纯领域、fail-closed
MaterialProfile 绑定层，安全复用现有四级 TemplatePackage resolver。

**Architecture:** JSON fixture 是本窄切片唯一 approved catalog；Python 模块只
负责 exact identity/schema/authority 验证、显式 scope 转换、现有 resolver 调用、
fallback/C0 receipt 和 typed ReviewItem。不解析 PDF，不读 Golden 答案，不产生
Claim/ChangeSet/Release。

**Tech Stack:** Python 3.12、Pydantic v2、C0 CanonicalEnvelopeV1、现有
`insurance_harness.template_packages`、pytest、Ruff、strict mypy、OpenSpec。

---

## Task 1: 占号、规格与 exact fixture

**Files:**

- Modify: `openspec/changes/README.md`
- Create: `openspec/changes/052-material-profile-template-binding/proposal.md`
- Create: `openspec/changes/052-material-profile-template-binding/tasks.md`
- Create: `openspec/changes/052-material-profile-template-binding/validation-report.md`
- Create: `openspec/changes/052-material-profile-template-binding/specs/material-profile-template-binding/spec.md`
- Create: `harness/tests/fixtures/material_profile_596_1_052.json`

- [x] **Step 1:** 从 exact base `ad99ca9a3e658e7d0fd768164f7aab247fe92933`
  确认 clean 独立 worktree/branch。
- [x] **Step 2:** 先机械将 051 登记为 PR #79 已合入，再占用 052；
  未先建 052 目录。
- [x] **Step 3:** 完整读权威 ADR/Amendment、JLX `§M0` 与相关章节、
  HANDOFF 顶部、051、049、ProductVersion resolver 和 TemplatePackage resolver。
- [x] **Step 4:** 写 proposal/spec/tasks，冻结 exact 596/596-1、三 PDF、
  medical 60-field、authority、explicit family mapping、fallback receipt、C0 与
  typed ReviewItem 边界。
- [x] **Step 5:** 写唯一 fixture；只记录 049 的三个 identity hash，
  禁止 Golden 答案 path/record/value 进入 catalog。

## Task 2: focused RED

**Files:**

- Create: `harness/tests/test_material_profile_template_binding_052.py`

- [x] **Step 1:** 先写能力缺失测试，以清晰 assertion 要求
  `harness/src/insurance_harness/compiler/material_profiles.py` 存在。
- [x] **Step 2:** 运行
  `cd harness && uv run pytest tests/test_material_profile_template_binding_052.py::test_material_profile_binding_module_exists -q`；
  预期因模块能力缺失而 **FAIL**，不得因 typo/fixture 错误失败。
- [x] **Step 3:** 在同一 test 文件补全 exact identity、三角色、60-field
  authority、explicit family mapping、四级/fallback receipt、无 Golden I/O、C0
  稳定性、typed conflict/ReviewItem 的纯领域用例。
- [x] **Step 4:** 再运行整个 focused file；预期用例均因同一缺失模块
  断言失败，记录 RED 计数。

## Task 3: 最小 GREEN 纯领域实现

**Files:**

- Create: `harness/src/insurance_harness/compiler/material_profiles.py`
- Test: `harness/tests/test_material_profile_template_binding_052.py`
- Fixture: `harness/tests/fixtures/material_profile_596_1_052.json`

- [x] **Step 1:** 实现 frozen/extra-forbid DTO：PDF identity、product/schema/family
  binding、profile、field authority、Golden identity、request、fallback receipt、
  resolution、ReviewItem 与 typed error。
- [x] **Step 2:** 实现 fixture loader 及 exact-slice 不变量：恰好三角色、
  恰好 60 字段双射、primary/support 不相交、contract 只能 terms
  primary、rate numeric 只能 rate_table primary、Golden 三 hash exact。
- [x] **Step 3:** 实现 `resolve_material_profile`：先验 product/schema/source/classifier
  exact identity，再由 approved mapping 构造 `ResolutionRequest`，只调用
  `resolve_template`，最后构造 missing-layer/source-chain receipt 和 C0 binding hash。
- [x] **Step 4:** 不 catch `BaseException`；TemplatePackage typed error 只转换为
  `template_resolution_failed` ReviewItem，不修改核心 resolver。
- [x] **Step 5:** 运行 focused file；预期全绿。如失败，只修最小实现，
  不放宽测试。

## Task 4: 回归与交付门禁

- [x] **Step 1:** 运行相关回归：
  `test_template_packages_028.py`、`test_product_version_resolver_041.py`、
  `test_schema_loader.py`、`test_s0q_full_golden_049.py`。
- [x] **Step 2:** 运行 focused Ruff 和 strict mypy（实现 + test 两路径）。
- [x] **Step 3:** 运行
  `DO_NOT_TRACK=1 openspec validate 052-material-profile-template-binding --strict`。
- [x] **Step 4:** 运行 `git diff --check`、exact eight-path/all `100644` scope、
  UTF-8/LF、private/absolute-path 与 secret 扫描。
- [x] **Step 5:** 用临时 index 计算 stable candidate tree 和 exact 8 blob IDs；
  保持 real index 空，不 commit/push/PR。
- [x] **Step 6:** 在 validation report 只记录 fresh 实际输出，并给出
  `BLOCKER / BACKLOG / MAINLINE DRIFT / DETAIL TRAP`。
