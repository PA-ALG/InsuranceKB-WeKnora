# G3 来源暂存环境：执行前方案

状态：PREPARED_NOT_EXECUTED。适用 G3-R3/R4 来源准备，由 root 单独执行；provider/upload/DB clone/container create 均尚未执行。本方案不授权生产发布，也不增加产品服务或 serving Head。

## 已只读核实

- `runtime-config-readonly.json`：tenant 10003，RAW KB `b1f1764c-443d-46b8-98e3-d5aa5e55eb42`；vector_store_id=NULL，storage backend `30545abd-ae95-4de0-a796-29b5c4bc32c7` 为 env/local、config={}，实际根目录 `/data/files`。
- `runtime-readonly-preflight.json`：G2 库 `weknora_g2_594` 无 active scheduled data sources、pending knowledge/subtasks、pending/running sync logs；目标 G3 DB 不存在。Redis DB15 已有 2 keys，禁止复用或清空。
- `runtime-readonly-extra.json`：四个 resource locator 按既有 storage://…/local:// 规则解析到本地路径，4 原文件 bytes/SHA 已实际核验；3 条 sealed source row 身份原样保留，第4份 `1265a343-c408-4620-8eed-c4f6a2adadc2/1` 目前 source row 缺失。此事实不等于 source custody API reopen 完成。
- 现有 app image `sha256:600a5a1cf93f4d2ecbe5466b7733c8d82395cdcad99fb501fb50ddf224220b19`；docreader `sha256:ac944d934fcd30c77e4ff28d19f1b4d6dd147012a6553c4678274c1f0be35868`；Redis `sha256:02f2cc4882f8bf87c79a220ac958f58c700bdec0dfb9b9ea61b62fb0e8f1bfcf` 均本机既有，pull/build=0。

## 新目标与边界

- DB：共享现有 PG instance 中新建 `weknora_g3_830`；来源 G2 只做 consistent pg_dump，不停机、不使用 template clone。
- Containers：`weknora-g3-830-app`、`weknora-g3-830-docreader`、`weknora-g3-830-redis`。Redis 独立 container、DB0，无发布端口，无复用 G2 队列。
- Network：`weknora-g3-830-internal` 标记 internal；G3 egress 默认不连接，仅未来具名外发授权窗口接入 app。
- 新卷：`weknora-g3-830-files`、`weknora-g3-830-docreader-tmp`；不得把 G2 files 挂成 RW。G2 原4文件只按 exact manifest 复制、逐件 SHA 验证；C5 registry/config 复用边界还需执行脚本明确校验。
- App唯一发布端口 `127.0.0.1:18294:8080`。不发布 UI、Redis、PG、docreader。此旧镜像仅供 source staging，不声称 G3 Catalog/D UI 已部署。
- app env：AUTO_MIGRATE=false、AUTO_RECOVER_DIRTY=false、RETRIEVE_DRIVER=postgres、LOCAL_STORAGE_BASE_DIR=/data/files、BATCH_EMBED_SIZE=100、REDIS_DB=0、SSRF_WHITELIST=127.0.0.1。沿既有 SYSTEM_AES_KEY 私密复制，只保存 digest，JWT新值不外显。

## 新克隆库启动前的窄配置例外

现有 KB update API 不支持清空 summary_model_id；initialization API 强制非空 LLMModelID 并会改写其他配置。为禁止上传自动触发摘要，采用仅目标新库的窄 SQL 配置步骤，不修改产品表结构或 G2/prod：

1. exact current_database()='weknora_g3_830'；确认 G3 app 尚未启动。
2. transaction 内锁定 tenant=10003 AND id=上述 RAW KB 的唯一一行；保存 summary_model_id、question_generation_config 的 before 摘要，断言恰一行、原值与读回一致。
3. 仅清空 summary_model_id 并设置 question_generation_config={enabled:false,question_count:0}；保存 after 摘要，断言唯一一行、无其余字段变更；COMMIT。
4. 启动前再次证明 clone 无 active schedules/pending jobs。若漂移，STOP，不能默默中和任务。
5. app 仅 internal 启动后，用既有 owner/admin API 完整 GET-derived KB payload 关闭 indexing_strategy.wiki_enabled，保持 graph false，token_limit=0/languages=[]；model完整 parameters 只改 base_url 到本地 guard，不能传 credential 字段。

## 请求窗口仍未执行

仅上传 corpus-files-v4 中的11份新增来源，原4件不重传/重解析。每件 process_config 采用已冻结的 builtin native、legacy 2048/80、parent_child=false、multimodal/graph/qgen=false。multipart fileName 精确取已审 corpus basename。

Guard 启动必须绑定已审 manifest SHA `75b40ece28a4219965a6a86be616bb90f17af53252afad6c2243dedb9e377225`，不得现场动态重算后信任。只允许11份 exact bodies，共204 inputs/693129 bytes；单材料1次、总11次含失败，首次失败全局STOP、不重试，不继承 G2 外发授权。端口只限 app 内 127.0.0.1:19030。实际 provider endpoint 为阿里云 DashScope `/compatible-mode/v1/embeddings`，模型 qwen3.7-text-embedding。

待完成：独立 guard 复审、完整 provision/config/upload 执行脚本与 partial receipt/停止规则、C5来源挂载核实、具体发送预览及用户外发授权。以上完成前不运行 provision、serve、upload。
