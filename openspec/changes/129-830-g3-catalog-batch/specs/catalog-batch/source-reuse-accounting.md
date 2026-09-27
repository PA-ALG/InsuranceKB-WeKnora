# G35：历史解析调用的只读统计修正

2026-09-27，沿用户完整G3.5授权及最新范围：解决跨页、表格、截断等通用能力缺陷；
原文已到模型而个别字段遗漏后置统一维护，不再作为本轮关闭阻断。
root唯一写者，复用既有processing_audit作为唯一汇总Owner；不修改原回执或发布知识。

- **SRC-REUSE-1**：以当前run.created_at为接纳边界，exact audit中RECORDED且
  finished_at_unix_ms严格早于接纳边界的dispatch计为历史复用，不计本轮新增；
  既有显式reused继续有效。时间边界仅证明调用已在本轮之前结束，不推断并发调用归属。
- **SRC-REUSE-2**：按dispatch去重后分类，支持旧解析与新重解析、同journal混合历史/
  当前调用、跨processing_attempt重复观测。所有有效dispatch均历史时material.reused=true；
  混合时false但总计分别列新旧。原receipt_sha256、counts、phases不变。
- **SRC-REUSE-3**：未知发送不因早期记录时间伪装成功；空journal、无audit绑定的旧summary
  及不可证实历史的调用保持既有口径。不扩展平台协议、不查询其他租户、不回填DB、不触发模型。
- **SRC-REUSE-4**：API读视图传接纳边界；历史run也立即获得正确投影。现有checkpoint显式
  复用、未完成状态和重复观测规则保持。正常现有run应为5新语义+0新source+3历史source。

写域：processing_audit.py、api.py及直接对应测试，本Spec、现有计划/HANDOFF/证据。
RED：普通重复上传、新旧混合、重解析共享dispatch、未知/opaque/边界、输入不可变、API真实存储读链。
检查：定向pytest、ruff/mypy、冻结独审；仅Harness必要构建和可回滚替换，GET旧run验收，
发布Head/调用ledger不变，不额外业务生成。远端CI与最终集成分别记账。

时间判断为当前同机Colima部署的历史fallback：App/Harness时钟共享宿主，真实旧回执早4天。
它不构成跨主机因果归属协议；后续分布式部署应消费原有upload/reparse owner绑定，
不能靠时钟决定未知或并发调用归属。此次不改变source capture与现有持久协议。
