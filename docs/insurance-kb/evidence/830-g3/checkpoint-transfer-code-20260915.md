# G3 增量传输与检查点恢复：代码验证

2026-09-15，基于194e6ff0a2d9bbe4f65a4aba5025772a924ba6ac。唯一集成写者root；本次用户已批准按计划修复和在现有环境部署。AGENTS.md及章程§11沿用源任务已写入的用户通用规则，本次集成保留，不是新授权门禁。

| Requirement | 实现 | 验证 | 状态 |
|---|---|---|---|
| G3-AUTO-3 增量候选 | candidate_transfer.py + 原prepare service；7固定槽ref/inline；8MiB wire/64MiB delta/128MiB expanded；Unicode损失修复 | Python codec/client/pipeline；Go类型、handler、原发布服务 exact draft/replay/撤销/head检查；服务67.117秒 | PASS |
| G3-AUTO-3/4 原成果接续 | CheckpointPlan/Receipt、现有ArtifactStore/JobStore、effective引用，不克隆大正文或旧成功jobs | 编译失败后9份响应/全部字段三态模拟；组合10 PASS133.54秒；早期阶段全流程2 PASS327.38秒 | PASS |
| G3-AUTO-4 终态与展示 | reused_stages独立展示、原耗时；合并继承partial状态 | UI35 PASS、typecheck PASS；Go状态桥PASS；progression8 PASS20.62秒 | PASS |
| G3-AUTO-6 证据及兼容 | producer generation/dependency、来源签名/版本、scope/Schema/base检查；原raw/field/call引用 | 9边界cases；旧V1/V2显式fixture26 PASS64.91秒，旧V3 24 PASS43.37秒+完整旧worker/新拒绝边界3 PASS349.33秒 | PASS |
| G3-AUTO-5 正式构建入口 | BA0 frozen_source_context、exact runtime-rebase；保留默认runtime；cold cache允许；umask077目录0755 | 140 PASS81.97秒；实际基础镜像标签/source和recipe只读核对 | PASS |

独立复核：A Unicode及预算finding已闭合。B最终记录原件/private/tmp/g3-checkpoint-final-review.md，SHA256698c48942f33decee969a19a26c117b6862632d0752b86dbdde8c4ae75a96810；副本见同目录checkpoint-final-review-20260915.md。Root补充其记录时尚运行的source/routing两例现在已PASS。

已记录真实RED：B旧实现不能在完成抽取后恢复；旧复制式测试升级为历史fixture，保留原断言；新版错误文字不决定资格，真正来源/parse漂移由worker拒绝。source/routing恢复误入字段重试导致自由发现被跳过，2 FAIL后修复processing_recovery接线并GREEN。继承partial被误报success，1 FAIL后修复并GREEN。构建新增端口缺失、空diff拒绝、default target漂移、umask不可遍历分别RED→GREEN。

## 交付与业务边界

此文件冻结时：software PASS；container health为旧现有容器只读正常；provider probe NOT RUN；provisioning变更NOT RUN；local live新版本NOT RUN；GitHub live NOT RUN。不以fixture推导真实业务通过。现有库14任务、active_jobs0、原ef9字段82条只读确认。

下一步仅更新受影响APP/Harness/UI组件，复用现有DB/Redis/DocReader和卷。部署后通过网页“恢复处理”，继续ef9编译，不重传三份文件，不重跑9次字段模型响应，不拼装候选或代执行发布。真实恢复时间/传输大小/新旧模型调用/最终发布检索和证据另记。

当前范围不声称：任意不完整模型阶段或部分窗口的跨任务恢复；发布成功后单独verify恢复；1000文件性能；5～10分钟目标；严格全新三材料上传验收；八条服务线所有实体实装。相关旧pipeline/向量细粒度结果复用债务未借本次声明解决。G3整体仍未完成。
