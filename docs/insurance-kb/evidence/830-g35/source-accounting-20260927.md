# G3.5 通用能力复核与历史调用统计修复

2026-09-27，活动树830-g35-multiwindow，root唯一写者。用户最新确认：跨页、表格等
通用缺陷需解决，个别字段遗漏后置，不逐case优化。适用SRC-REUSE-1—4。

## 通用能力复核

- 跨物理页身份取证：d0157306及真实3965运行PASS，原Evidence/坐标不被重写。
- PDF数字表格误删：460c664cf及真实输入恢复14行/423字PASS。利益演示原表已进输入，
  没形成有效正文属于后置语义质量项，不能再次归为解析丢表。
- 长文输入：真实2/2窗口、20287字符完整，预算超限明确失败，未发现静默截断反例。
- 多窗口恢复：真实3965→c6复用成功调用、两窗聚合、审核、发布及verify PASS。
  此次结果没有新自由成员；非空多窗page/definition真实组合验收仍NOT RUN。
- 单窗真实非空概念/关系：41b7009c发布到epoch26、模型生成标识、原文第2页点击PASS。
- 个别贷款细节、退款对象、利益演示正文及旧中止页段落支持不足留到统一质量维护。
  原R7审计18项15完整/2部分/1缺失保留，不能改写成全文覆盖PASS。

## 根因与切片

正常重复上传通过平台指纹复用旧解析，source stage仅将checkpoint/saved标为复用。
因此旧source回执进入新run后误标reused=false。41b7009c API的8实际为5新语义+3历史source。
唯一汇总Owner仍processing_audit；API仅传run接纳时间，按exact dispatch去重后区分。
RECORDED完成时间严格早于接纳边界才推为历史；显式reused优先，unknown/opaque不猜。
material在全部有效调用历史时才标复用，mixed仍逐调用分账；raw/receipt hash不变。
该时间判断仅为当前同机历史fallback，不是跨主机因果owner协议。

## 软件验证

- API回归RED：旧实现历史调用计1，期望0，真实断言失败。
- 显式reuse共享dispatch顺序RED：旧owner-first计1，期望0，真实断言失败。
- 6个定向测试文件92 PASS/48.76秒，含API、原生回执、增长journal、checkpoint和recovery。
- 4文件mypy/ruff、git diff --check PASS。仅既有Starlette/httpx弃用告警。
- frozen软件manifest：59b8694010a321335cf1f137df6d78456d3bc269606ca5d49d928ba6d0aad656。

独立冻结审查0 BLOCKER，exact commit `3da99755cfd27b1955cb8a3e239aaaa6550c1c53`。
Harness必要构建1次PASS，image `sha256:5ad9982b10b8072ad569d834783cd2a6f0b849fb11ebf822e5dd7cca8387e4e7`。
最终交付manifest `680eb25a7f6e28a40d3a18ace84a51d9c8445b296d2eb60ddbcf1f1f66aecd7f`，
独立交付审查0 BLOCKER。03:32:02—03:32:25Z Harness-only可回滚部署PASS。
API容器 `6ef100fec97fc06e3ac0d3af2a0b740474ca8a934d62871c31a8b9f59b8d2aa2`；
worker `49c66ae4b2935fd188d619385b125772d227b33001169a9d5bc094a14b1ccf6e`。
App/UI/配置/迁移未改，原容器保留；Active epoch26与模型ledger保持。
03:32:45Z只读GET原run41b7009c验收PASS：5新语义、0新source、3历史source，material.reused=true；
原source receipt SHA `f467fa0b018ee46945629db9a308a08f10a6fa739b06e0e80b13aaf3ca3581d6`保持。
本轮无新provider/business写调用，不为修统计重新生成Wiki。
回执受限备份：insurancekb-private-evidence/g35-source-accounting-20260927/。
GitHub CI/最终集成NOT RUN；不由本地验证推导远端完成。

远端只读核对：已有draft PR #130，head 8f7201dd，deterministic/integration-postgres/
wheel-smoke均SUCCESS；该head不是当前3da99755c，不能据此声称本次G3.5最新代码CI通过。
