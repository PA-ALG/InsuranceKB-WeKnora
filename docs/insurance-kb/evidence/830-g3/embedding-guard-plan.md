# G3 来源上传的请求边界

状态：仅准备，未授权外发/未启动guard/未上传。Root唯一执行者，沿G2一次性本地counter模式适配，不新增产品服务。

冻结输入为 embedding-transport-manifest.json 与其中11份已保存exact请求body；模型qwen3.7-text-embedding，唯一上游https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings。body均使用现有Go请求DTO序列化，204inputs共693129bytes。实际入站body SHA必须精确命中11份之一，转发原字节，不重新排序或改写JSON。

总预算11次上游尝试；每份最多尝试一次，含HTTP失败/超时/未知结果，不能因自动重试再次外发。未知body/重复body/错误路径/非loopback来源/无Bearer/预算耗尽均在转发前拒绝。STARTED计数须先原子持久化/fsync，才发请求；无重定向/自动重试/自动恢复。已有ledger禁止重新启动；首次上游非200或transport error后全局停止接受新的上游尝试，保留部分回执并由root停止上传。凭证仅在请求内存，不记日志/不落盘。

先以旧G2guard注入fake sender复现“失败后同材料再次外发”的行为RED（无真实网络），再实现当前有界wrapper并验证：成功一次、失败后重复拒绝/全局停止、未入白名单拒绝、11预算、已有ledger拒绝、精确body原字节、不保存Authorization。独立review通过和用户对完整发送清单的具体授权之后，才允许实际serve与上传执行。

运行前还必须完成G3目标环境读回：summary_model_id空、indexing_strategy.wiki_enabled=false、token_limit0/languages空、BATCH_EMBED_SIZE100、exact embedding模型参数和本地guard baseURL。现有G2配置不可直接当G3已经配置完成。
