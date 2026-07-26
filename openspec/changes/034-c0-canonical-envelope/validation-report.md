# 034 · Validation Report

> 2026-07-27，总控窗口（Wave 1）。分支 `feat/c0-canonical-envelope`，
> 基线 `main = 8a755fdc`。

## 交付物

- `harness/src/insurance_harness/canonical/`：errors / values / encoder /
  hashing / `__init__` + `vectors/canonical_vectors_v1.json`（38 合法 +
  16 非法用例）；生产代码约 300 行，零 harness 内部依赖、无 I/O、无迁移。
- `docs/insurance-kb/25-canonical-envelope-v1.md`：语言中立规范。
- `harness/tests/test_canonical_vectors_034.py`（向量全等 + 双向完备）、
  `harness/tests/test_canonical_envelope_034.py`（C0.1–C0.9 单元）。
- OpenSpec 034 proposal/specs/tasks + 台账占号 034/035（W0 预占行按台账
  「后者改号」规则移至 037，见 README 行内说明）。

## TDD 证据

- RED：包不存在时两测试文件收集即错（2 errors during collection）；
- 向量独立性：canonical 字符串手工按规范编写，sha256 由冻结字符串经
  `artifacts/generate_vectors_v1.py` 独立计算，不经由 reference codec；
- GREEN：实现后 focused **87 passed**（首次运行即全绿，向量与实现互相
  独立验证）。

## 门禁

| 门禁 | 结果 |
|---|---|
| focused（两文件） | **87 passed** |
| Ruff（包 + 两测试） | PASS（4 项风格 finding 已修复后复跑全绿） |
| mypy strict（7 files） | PASS |
| `openspec validate 034-c0-canonical-envelope --strict` | PASS，exit 0 |
| 全量 deterministic（PR-ready） | **3642 passed / 30 deselected / 1 failed** |
| PostgreSQL / WeKnora live lane | NOT RUN（不适用：本包无 DB/网络面） |
| CI | NOT RUN（待 PR） |

## 已知问题（非本 change 引入）

全量 deterministic 唯一失败
`test_ci_lanes_022.py::test_rh6_1_claude_default_gate_selects_only_deterministic_lane`
为 **main 存量潜伏破损**：D0（PR #34）重写 `CLAUDE.md` 时移除了
"门禁（交付定义）"节，而 RH6.1 断言该节的 exact 门禁命令；033 为纯文档
PR，harness lane 因路径过滤未运行，破损未被暴露。与 canonical 包无关
（本 change 未触碰 CLAUDE.md / test_ci_lanes_022.py）。修复由独立小 PR
承接（更新 CLAUDE.md「默认验证」节补回 exact 门禁命令并把 RH6.1 指向
新节），合入顺序：fix PR → 本 PR CI 复跑绿。

## 边界重申

- Go/fork 不动；W1/P11 首次消费时用同一 vectors 验收；
- `template_packages` 自有 hash 与 C0 的对账归 P6a（24 号处置清单）；
- `docs/insurance-kb/README.md` 索引行（25 号）待 PR #35 合入后由后续
  文档 PR 补录，避免与其 24 号行冲突。
