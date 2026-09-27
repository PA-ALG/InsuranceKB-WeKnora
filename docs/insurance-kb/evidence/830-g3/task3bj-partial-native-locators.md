# Task3bj：局部定位失败隔离

2026-09-16，G3仍未完成。用户明确要求修复解析并提高容错。Root唯一写者，g3_locator_contract_review独立只读审查。

## 事实与修复

真实首次上传任务384f1c4c-5394-45fc-8406-28e86c9d2b66在费率表第2页字符0失败，其他两份解析成功。PDFium返回坐标y700..705，而页面/media/crop高度595.25；原文本可读。旧producer及两处Go validator把完整文本与每字bbox全覆盖绑定，导致局部几何异常终止整份处理。

完整材料保持v1 native artifact/producer/identity不变；局部异常使用v2及显式unavailable_ranges，不删除文本、不猜坐标。Go传输和持久证据索引复用同一覆盖校验；Harness验证缺口，即便该页未参与当前投影。正常quote可用，触及缺口quote不能签发高亮；普通字段沿用extraction_failed，不增加第二发布或page-only证据合同。扫描、不可读PDF和原文完整性异常仍明确失败，本次不宣称处理所有格式损坏。

解析器返回的确定性Error保留原终态分支和原理由；不再包装为触发重试的传输错误。真正连接错误仍沿原有有界重试。来源阶段失败统计漏报另保留，尚未修复。

## 验证

- RED：原producer对坏bbox/缺bbox/映射异常/旋转7项报错；原Go拒绝显式v2及把parser.Error转重试；原Harness接受4种错误缺口。环境缺依赖/缓存权限错误不计RED，修正测试启动后有真实失败记录。
- Python解析器51项通过，其中3项原有依赖条件跳过。
- Harness原文定位与字段校验23项通过。
- Go解析接收、定位索引、引用及首次解析定向回归两包通过。
- 原始108页费率表禁网离线回归：683732字符全文与原PDFium逐页结果完全一致；563542有效字符框，666个bbox_invalid明确留缺；78.437秒。诊断结果不入库、不替代平台处理。
- 真实Python产物通过Go接收和持久证据索引两处跨语言验证，两包通过，28.736秒/9.200秒。
- 独立核心审查BLOCKER0；追加Makefile构建默认低并发、2GiB软内存目标的审查BLOCKER0。实际构建另加容器3GiB硬限制。DocReader通过repo代码更新配方复用原运行时，仅更新本次PDF模块，不重装依赖。

原始日志和真实文件诊断位于`/private/tmp/g3-platform-independent-deploy-20260913/task3bj-*`及`/Users/houjing/Documents/LLM_wiki/g3-acceptance-inputs/locator-diagnostics/`。原件未修改。

## 尚待执行

受影响组件构建/烟测/部署；网页恢复原任务；检索/证据回查。恢复不能称为无干预首次上传验收，仍须冻结部署后的全新产品完整验收。不能以本报告的软件结果宣称G3完成。
