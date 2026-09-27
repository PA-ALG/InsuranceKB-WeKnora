# Task3ax：字段多处原文证据与跨页定位

G3 尚未完成。本记录区分代码验证、部署和真实业务验收。

## 设计与根因

`03-knowledge-model.md` 的 Claim 多 Evidence 设计继续有效。815 的
`830-b0/runtime/c7-server-reopen-index.json` 中 guaranteed_renewal_period
已有 5 条引用，位于第 1、20 页。G3 继续使用 Evidence 数组和字段 Wiki；
Viewer 已支持 `source_locator.actual_page_number`。

最近网页恢复 `3661a372-ae01-5e2f-8ccb-6798b0338668` 在发布准备失败。
当前产品的 coverage_responsibilities、death_benefit_rules 使用同一跨页引文：
原文全局范围 4058–4433，第 3 页到 4188，第 4 页从 4190 开始，页间是两个换行。
原引文与块一致，但既有发布 locator 要求每条引用位于一张物理页。

本次复用原多引用协议：精确拆分为第 3、4 页两条引用，原字段值、模型原响应、
原抽取记录和源文件保持不变；页间空白显式保存。只有真正无法定位的普通字段
才成为 extraction_failed，且隐藏有效值。identity/版本/签名错误仍阻断。

## 实现与复用

- source_geometry 按既有签名快照构造一次当前证据页索引，校验每个非空白码点的定位。
- synthesis 保存 field_validation 派生记录，绑定原 attempt 摘要、raw_ref、源快照摘要。
  统一字段读取、计数、补抽与编译读取同一有效结果，原记录不覆盖。
- compile_delta v2 与 field_validation 合同使旧任务从 synthesis 恢复；
  source/identity/field_plan/extract 继续复用，旧 artifact 保持不变。
- 恢复不重新外发 discovery；未发布且依赖变化的旧发现明确待重验，历史响应保留。
- 用户明确补抽的失败字段在首次 reservation 排除原抽取缓存，其他成功字段继续复用；
  已封存的 reservation 不重新选择。该处理也适用于引用祖先 attempt 的检查点子任务。

## 验证记录

临时回执目录：`/private/tmp/g3-platform-independent-deploy-20260913`。

| Requirement | 验证 | 状态 |
| --- | --- | --- |
| G3-AUTO-2/6 多引用及证据保留 | geometry/view 18 项；真实签名快照精准分段，两个换行完整审计 | PASS |
| G3-AUTO-3/4 派生持久化 | store/view 4 项，重启、原响应、计数、失败补抽、损坏拒绝 | PASS |
| G3-AUTO-3 检查点合同与恢复 | store/discovery/contract 43 项；pipeline/checkpoint 11 项 | PASS |
| G3-AUTO-4 显式补抽缓存 | RED 实际返回 ALL_CACHED；修复后相关 13 项通过 | PASS |
| G3-AUTO-6 真实引用定位 | 原 Go locator：319 去重引用、12 native sources，测试 14.42 秒 | PASS（离线定位范围） |
| G3-AUTO-5 部署及网页增量验收 | 必须等待本次实际服务部署及网页恢复回执 | NOT RUN |
| 全新产品三文件网页验收 | 仍为后续必需项 | NOT RUN |

对应日志：task3ax-geometry-view-green.log、task3ax-store-green-02.log、
task3ax-integration-green.log、task3ax-checkpoint-pipeline-green.log、
task3ax-retry-cache-red.log、task3ax-retry-cache-green.log。

真实定位诊断：`/private/tmp/g3-task3aw-source-probe/task3ax-probe.log`。
只在本机诊断副本调用生产函数；没有写入业务候选、没有解析 PDF、没有调用模型。
该项没有验证 legacy 的 24 次引用出现、缓存签名及 first-parse 全路径，不能冒充整链路验收。

扩大回归中另发现 4 处旧测试仍导入已改名的私有函数，现仅修正测试引用为既有公开
`published_compile_members`，生产编译实现未改。格式工具移除的两项 pytest fixture
导入已恢复；失败日志保留，复跑通过，不将这些测试环境问题记作功能 RED。

独立冻结 01：14 文件，1 项补抽缓存阻断；最终冻结 02：15 文件，manifest
`f8b6bf36873573e2a2a1c77693e70aab0f80c94fad7047881de93a38733b2e6c`。
最终独立复核 0 BLOCKER；报告 `/private/tmp/g3-task3ax-independent-review-02.md`，
SHA256 `c43014c481169d6ea524cae78513af9b29962c22ae90e3639bf03b2919e50332`。
部署 commit 由后续精确构建回执登记。
