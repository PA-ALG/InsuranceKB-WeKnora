**[by Codex]**

Closes #

## 切片与 Spec

- 切片：
- Spec：`docs/design/slices/`

## 改动

| 文件 | 净行数 | 说明 |
|---|---|---|
|  |  |  |

删除的旧实现：无 / 逐条列出。

## 与 Spec 的偏差

无 / 逐条写：偏差内容、原因、影响。

## 门禁结果（本地）

- [ ] 验收：Spec 指定的命令 → 通过 N / 共 N
- [ ] 守卫：`pytest -q tests/architecture` → 全过；基线是否下降：否 / 是（写明哪几项）
- [ ] Go：受影响包 `go test` → 相对 S0 失败清单新增 0 项
- [ ] Harness：`uv run pytest`、`uv run ruff check .`、`uv run mypy src tests`（在 `harness/`）
- [ ] 前端：`npm run type-check`、相关测试、`npm run build`（在 `frontend/`）
- [ ] 已 rebase 到最新 `main`

## 受保护路径

- [ ] 未修改蓝图、`docs/design/`、`tests/acceptance/`、`tests/architecture/`、`contracts/`（基线只在数字下降时经脚本更新；`contracts/` 只由 Spec 规定的导出命令生成）
- [ ] 未 deselect、未加 xfail/skip、未改已有断言

## 真实调用与环境变更

未使用 / 场景数、发送次数、模型、结果摘要、原始输出存放位置（不得超过 Issue 中的预算）。

## 未完成项与风险

无 / 逐条写。
