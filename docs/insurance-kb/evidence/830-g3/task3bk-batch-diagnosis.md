# Task3bk 集中诊断与同批修复状态（2026-09-16）

Owner=root。G3 独立平台验收仍 BLOCKED，QUALITY 后置。本轮不是全新三材料独立成功验收。复用既有运行环境；截至此记录没有新增镜像构建、服务切换、发布或模型调用。上一轮已部署 964f968，以下修复尚未部署。

## 真实诊断终态

产品“平安御享鑫年年金保险（分红型）”。原网页产品恢复 71d0e7f5… 在 checkpoint 失败。随后网页单文件重建费率表，再恢复 15706f64-ae9e-5e46-951d-ff68534c52f7，是 Codex 辅助诊断路径，不能算一次产品操作自动恢复。

三份来源均成功封存（10/108/7页）。恢复 run 从03:41:43.137868Z到04:25:19.503439Z，43分36秒；preparation三次传输失败后dead_letter；最终13 verified、17 not_provided、52 extraction_failed。后续review/publish/verify NOT RUN。3次字段调用因租约重领成为interrupted，影响30字段，是基础设施问题，不是普通业务缺失。

新增调用：费率表47 embedding+1摘要、1分类+9字段，共58；兄弟文件以前8次调用为复用。没有普通字段补抽。finalization单字段model_call_count=9并不代表完整调用账；以逐类原始调用记录为准。候选/原文/原响应仍留存，不重新抽取。

## 已集中定位

1. 产品恢复允许uploads成功前缀，却错误要求全体source完成；后续source缺少失败文件原生重解析接线。
2. 原生ReparseKnowledge存在入队错误返回nil及未按expected失败代次幂等分配的问题，不能只增加一个HTTP调用。只读设计记录 /private/tmp/g3-task3bk-reparse-design-review.md。
3. 当前字段计划33,857,031B，82字段复制同一1044条来源引用；窗口重复读取约79.7MB来源/几何。当前来源及历史来源校验、序列化重复。
4. 4个窗口被重领，3个已发送调用中断；旧运行缺乏心跳时序，CPU/GIL、executor排队、DB等待的唯一根因未证实。
5. preparation每条不同引用重复读取/验签同一首次解析制品。客户端记录transport error，APP随后503不能证明独立服务端300秒超时。
6. source失败统计未汇总成功兄弟的原生调用；成功解析仍可带上一轮错误。

## 本地实现与验证（不是部署结果）

| 项目 | 状态 | 证据 |
|---|---|---|
| 等价文本控制字符检查、allowed来源先过滤 | PASS | 旧实现5个成本反例失败；228项canonical/resolution/routing通过 |
| 来源验证同一operation复用，下一operation重核文件/绑定 | PASS（独审通过） | source-operation真实RED；Go first-parse/status定向回归；最终Go回归4.410s通过 |
| SourceBlock按scope/run/制品引用/公钥身份复用 | PASS（独审通过） | 旧实现每窗重读RED；source/checkpoint/artifact 34项及组合71项通过 |
| metadata读取不加载大payload；冷读仍拒绝篡改 | PASS（独审通过） | SQL选择列检查、scope拒绝及payload hash反例 |
| 窗口检查移除丢弃的完整batch序列化 | PASS | 旧实现RED；抽取43项通过，保留task/source验证 |
| 心跳/回收/transport可定位日志 | PASS（仅可观测性） | 原先无诊断RED；组合71项通过；不宣称租约根因闭合 |
| 成功索引/新解析对象清除旧error_message | PASS（本地） | RED当前旧错误残留；Go定向回归 |
| 原生幂等失败文档恢复接线 | BLOCKED | 设计复核已完成，尚未实现 |
| field_plan持久来源去重、重复全量规划进一步收敛 | BLOCKED | 本批已减少窗口冗余校验，持久计划格式未改 |
| source失败调用统计 | BLOCKED | 尚未实现 |
| 代表性4并发租约稳定性 | NOT RUN | 需有界实测，不以小fixture代替 |
| 构建/部署/真实恢复发布/新产品验收 | NOT RUN | 统一收口后执行，不逐项重建 |

真实8,117,034B请求本机离线校验：旧7.8939s，新4.6725s；两者canonical SHA均04ea7b94f5133cc16deeec7d25b9af8e536da009cbb268b2c9d5669a610f884f。单次局部测量，不等同于端到端达到5–10分钟。

本地回执 /private/tmp/g3-task3bk-{red-*,green-*,offline-profile.json}；冻结代码清单 /private/tmp/g3-task3bk-code-freeze.json（22文件，SHA abf27c0ea98a5e62cb57a67104c8c1358d19e28ef773f469ec74b51cff3d27b1）。组合回归71 passed/2 deselected，322.16s；无需重跑同批历史产品。所有评审、构建、真实平台效果分别登记，不能由本地PASS推导。

## 独立复核收口

首审发现成功心跳INFO未接入默认启动日志（BLOCKER）与metadata默认全类读取的SQLAlchemy identity-map/raiseload冲突（BACKLOG），均在部署前同批修复。两个真实RED见review-red.log；修后38项通过21.53s，ruff通过。复审24文件SHA匹配，BLOCKER=0/BACKLOG=0，仅针对已实现切片；未实现项状态保持。最终冻结清单task3bk-code-repair-freeze.json SHA b05cb67d60be9262951b16c25e9f75fb631a831fa0cbca1c776eac810fb8bd7e。独立报告同目录task3bk-code-review.md、task3bk-code-rereview.md。

## 等待期追加检查与批次冻结

性能切片已提交 3fb14a1b1。等待期新增轻量授权计划引用复核+已完成fanout job_id复用，重启/身份变化重核，半途失败不缓存；计划正文不进常驻缓存。旧实现3个真实RED失败；progression/runtime/composition 25通过，pipeline/composition 14通过。extract阶段首次完整计划读取放在线程边界。冻结与独审另行记录。

使用当前真实33,857,031B字段计划、2954个SourceBlock，4个真实字段worker+JobStore在宿主临时SQLite做并发诊断，模型为35秒等待替身，原10秒心跳/30秒租约不变。78.113秒结束，4/4 succeeded，全部attempt1/generation1，4次替身调用/0真实模型。24次心跳无错误；最慢loop delay1.6342s、executor等待0.2881s、数据库调用2.5857s。证据/private/tmp/g3-task3bk-concurrency-probe.json。此检查不含80MB源几何冷读、不含Colima真实PG和后台pump竞争，不能冒充生产四并发根因完全解决。真实部署后用新增诊断进一步确认。

批次交付只涵盖已验证性能/容错诊断切片；当前来源已成功，允许继续诊断已有候选的review/publish。自动失败文件重解析/source失败统计/持久计划格式改造保留，不以这些已记录缺口反复打断当前后半流程；它们仍是最终平台收尾需要评估和闭合的项。

等待期追加切片独审 BLOCKER0/BACKLOG0，5文件冻结 SHA442b60b52ded1f4a9156e4463758bc9ca74f4e77084ee1793f004529d2ff3ec2，报告同目录task3bk-fanout-review.md。
