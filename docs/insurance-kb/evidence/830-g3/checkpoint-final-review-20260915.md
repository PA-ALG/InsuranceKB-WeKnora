# G3 checkpoint recovery B 最终独立复核

结论：当前 compilation 检查点恢复范围内 **0 BLOCKER，0 未关闭代码 finding**。A 传输层沿用此前 0 BLOCKER 结论，本次未重新扩大 A 评审。

范围：当前失败 run 的既有完整字段结果和成功 synthesis 产物按引用接续 compilation；原始字段、调用、失败历史不克隆、不改写。此为代码只读复核，不是部署或现场 G3 PASS 回执。

## 最终修复闭合

- `progression.py:166` 已从本地 `rows` 改为合并后的 `stages.values()`。继承 synthesis 为 partial_success、全部字段 verified 的场景仍返回 partial_success。此前独立最小复现的 BACKLOG 关闭；新增 `test_progression.py:21` 精确覆盖该场景。
- `pipeline.py:810–814` 的 `processing_recovery` 同时识别旧恢复计划及 checkpoint_plan；早期阶段恢复不会误走字段补抽分支。本次从 compilation 接续不执行 synthesis，保持零新增模型调用路径。
- 与私有 `after` 文件逐项比较：10 个 B 生产文件中 8 个 SHA 完全一致；pipeline/progression 仅为上述两处最终修复。`base_body=base` 的 A 发布调用保留。

## 已核边界

计划元数据有 scope、原 run/version、材料、完成阶段及成果/调用/字段引用；worker 重新核验原文签名、parse attempt、当前 published base、Catalog/Schema policy、生产任务状态/代次、正文 SHA 及字段投影与 compile_delta 一致性。只有真实 checkpoint 作业成功提交的 receipt 才开放 effective 成果与阶段读取。未完成模型调用不以新 run 身份重发，原字段与调用按原 ID 引用、调用计数去重。普通 unknown/字段缺失不新增质量阻断。

## 验证证据和限制

独立完成：三份输入补丁 SHA 复核、生产代码审查、旧 partial 状态误报的无 DB/无 provider 最小复现、最终两处 diff 和新增断言静态核对、全部生产文件 SHA 冻结。

Root 提供验证：新增 partial 用例 RED 1 FAIL 7.24s → progression 全 8 PASS 20.62s；B 10 个测试 PASS 133.54s。最终早期 source/routing 完整恢复回归在本记录生成时仍运行，不能计为已全部 PASS。本轮未重复长回归，无业务请求、数据库变更、模型调用或部署。

已明确不覆盖：发布完成后的独立 verify 恢复；不完整 model stage / 部分字段窗口的跨 run 接续。它们不作为本次 compilation 修复阻断，也不声称已实现。

## 冻结身份

- 观察时间（UTC）：2026-09-15T02:36:20.910791+00:00
- 工作树：/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-performance
- 基础 HEAD：`194e6ff0a2d9bbe4f65a4aba5025772a924ba6ac`（生产改动尚未提交）
- `implementation.patch`：`a0ee2e319ea2bb0dcdec30e9aabd11e76bdf3118605dbfe4fa4253186fc813e7`
- `pipeline-integration.patch`：`7dd6d98d48076ba4dd39ac6a0019abc59f21f386663731acf5c84d5702af2c55`
- `tests-additional.patch`：`4a06840d925aeb5a393e6276e63d384a04a48403f76fa27fc405d25c3d30acc0`

| 生产文件 | SHA256 |
|---|---|
| `harness/src/insurance_harness/product_ingestion/api.py` | `ba7e75140b748827e6115f06cab5abc3f02b16d9b142df624de2aa8ad25d1dc4` |
| `harness/src/insurance_harness/product_ingestion/artifacts.py` | `02f5c00778c1e5ebdf8aa1628686c382ef0af2d4e255776bfba7aeee2cd35f55` |
| `harness/src/insurance_harness/product_ingestion/checkpoint_artifacts.py` | `aabf885d498aff9ed3db1b13dcbdd81894759848939557953bfaac057d730894` |
| `harness/src/insurance_harness/product_ingestion/checkpoint_store.py` | `763473d85483481139952cf4a410003383e6972cdad9787eb6b44580103d0575` |
| `harness/src/insurance_harness/product_ingestion/checkpoints.py` | `f610db99d89ab70ae1272bd14785fba7aa53fe8e5405a3043b8e831fbee242ef` |
| `harness/src/insurance_harness/product_ingestion/composition.py` | `24a0877c92464dbd5cf0a4daaaf87bd313b4b6daf5d682cda6548f0c75c60f5a` |
| `harness/src/insurance_harness/product_ingestion/pipeline.py` | `523cd2c315f86479b5368dafc0a6c1ab34a2685d9888f47fd719359b82164e63` |
| `harness/src/insurance_harness/product_ingestion/progression.py` | `d51bad99af371d20cd6ab325a4e6c7f558216bb6b988d94a8db0085f6c9e5ef4` |
| `harness/src/insurance_harness/product_ingestion/stages.py` | `a5f56bd8b171b48ff353944ee6ac29bdc8610a1b638d34bd5d0f40cfd22ff4a5` |
| `harness/src/insurance_harness/product_ingestion/store.py` | `cf146c45ad988278e41a1112274fac772ba058e42e6abcc937e094659a536fb2` |

新增闭合断言所在测试文件：`harness/tests/product_ingestion/test_progression.py` SHA256 `88faf2159e78938804631f93a6fea1c3a11c119a7af4eaf7c216a73911683a3a`。
