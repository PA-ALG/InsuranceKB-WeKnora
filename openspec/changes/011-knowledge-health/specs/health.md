# 011 规格（验收条款）

## H1 扫描器（全部确定性）

- H1.1 过期：`claims.effective_end < today` 且 status=published → 检出并生成 ReviewItem(type=expired)；产品销售状态为停售但其 Claim 无失效标记 → 检出；
- H1.2 积压：pending_judge / ReviewItem(pending) 超过阈值天数（可配，默认 7）→ 升级清单；conflict 未决按产品聚合计数；
- H1.3 漂移：对每个已发布页，按当前 published Claims 重编译（007 编译器纯函数）比对内容 hash 与 rendered_pages 物化记录——不一致检出（含"编译器版本变更"与"页面被绕改"两类原因区分：编译器版本同则判绕改）；
- H1.4 退化：completeness_snapshots 定期落表（产品×字段三态计数）；环比覆盖率下降超阈值 → 检出并注明可能原因（schema 升版/Claim retract）；
- H1.5 孤立：发布页无任何 in/out wikilink 且无概念关联 → 清单（信息级，不开工单）。

## H2 产出与集成

- H2.1 `health-check` CLI：全量扫描输出 markdown 报告 + 结构化 JSON；`--open-tickets` 才生成 ReviewItem（默认只读，遵循 dry-run 规范）；
- H2.2 ReviewItem 复用 007 稳定 ID——同一问题重复扫描不重复开单，已 resolve 的不复活（除非问题复现于新版本）；
- H2.3 报告含健康度总分（各维度加权，权重可配）与趋势（对比上次快照）；
- H2.4 LLM 语义审计接口 stub（claude-session 队列，默认关）。

## H3 端到端

- H3.1 夹具构造五类问题各 ≥1 → 全部检出、工单幂等；无问题夹具 → 报告干净、零工单；
- H3.2 零模型调用；门禁全绿。
