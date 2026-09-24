# P0 原生质量前置交付（2026-09-24）

## 当前事实

源码 `460c664cf20f23ede858aa06c24e8275cb56a495` 已本地冻结，未 push。P0-1 解析修复与 P0-2 原生失败结算的测试、独审见各自证据；APP/UI/DocReader 各一次必要构建均 PASS。此事实不代表 G3.5 或真实原生质量验收完成。

- APP：`sha256:4283c11ce960781fdfdb6eefb7ed598f560f54cec1f3037711550ed812e28f26`，复用现有运行依赖，仅编译变化源码。
- DocReader：复用原精确镜像，仅覆盖已测试的 PDF parser，依赖层保持一致。
- UI：冻结同一提交，复用 lock 匹配的 node_modules，完整生产构建通过。
- Harness 制品与配置保持原状；不执行数据库迁移，不直接写业务数据，不执行正式发布。

## 第一次交付及恢复

本地时间约 10:46 开始切换。APP、DocReader 服务级健康及原 Active GET 通过，前端静态文件复制完成后，一项断言失败。该稿未记录断言行，因此不能确定根因；静态内容切换时 nginx 旧 worker 短时返回旧 index 是待验证解释，不作为确认事实。

自动回滚恢复了旧 APP、DocReader、UI 配置和 worker。回滚回执为 NEEDS_RECOVERY，唯一记录错误是将本来没有改名的 worker 再次改为原名，Docker 返回 400。随后只读检查确认：

- 五个原容器均为原 ID/镜像并运行，Harness API/worker healthy；
- DocReader gRPC 健康检查 SERVING；
- 两份 UI 配置字节与备份完全相同；
- Active 仍为 epoch17 / release-b8d07e76-da52-4446-9c37-fb6f8a1cb2d6；
- 原生所有相关 active/pending/scheduled/retry 及 task_pending_ops 为空；
- Harness 两类调用账本无新增。

新解析文件与新 UI 目录均与冻结制品 hash 一致。未上传实验文件，provider probe 与原生完整业务复验仍 NOT RUN。

## 有限恢复方式

复用同一制品，不再构建；保留第一次失败容器/回执。新 UI 目录仅在完整文件 manifest 相同后复用，不合并陈旧目录。服务切换后等待 nginx 提供冻结 index，最多 20 秒；异常保存阶段、traceback 和意外 index。回滚跳过已经是原名称的容器。

私密证据：`insurancekb-private-evidence/g35-live-20260924/delivery`（已归档），执行暂存 `/private/tmp/g35-live-20260924/delivery`。第二次切换及后续原生复验须另记实际结果，不能由该恢复方案推导通过。

## 第二次交付结果：PASS

2026-09-24T02:51:51Z 开始，02:52:39Z 完成（约48.3秒）。未重建，复用相同制品；新 APP `d0f281420c82315f1771ecc3a88d3a86c0a31111fdc81739acd7d68af7e6563f`，新 DocReader `3708c452f7471fbee4025300f3143c5f49551278eb1320462f8eb26818f9ace8`。APP/DocReader/worker 服务健康、精确解析文件、served UI index、原 Active 和最终队列静默检查全部通过，Harness 调用账本未变，旧容器保留。首次断言缺少行信息，第二次通过也不足以反推首次根因已确证。

本次 `software/container health/provisioning/local live` 对该最小交付切片为 PASS；`provider probe` 尚 NOT RUN，`GitHub live` 未执行。下一步仅按已冻结单文件窗口通过正常 UI 创建新空原生实验库并上传；G3.5 整体验收仍未完成。

后续真实单文件复验已执行：输入与失败可见性PASS，引用结果未知导致健康基线BLOCKED；实际模型发送与页面结果见[native-recheck-20260924.md](native-recheck-20260924.md)。上述provider NOT RUN仅对应切换完成当时，不能覆盖该后续执行事实。
