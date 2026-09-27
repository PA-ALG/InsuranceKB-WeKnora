# 修复后的原生 Wiki 单文件复验（2026-09-24）

## 结果

输入修复真实生效，原生未知失败也已明确展示；但引用调用结果未知，尚未取得健康原生完整正文。不能据此判断生成质量已合格或 G3.5 已完成。

同原测试账号/tenant10003、同workspace，通过正常网页创建空知识库 `8649ee5e-e3a7-4a67-994b-7bbf372025d5`（G35-NATIVE-RECHECK-SHOUHU-20260924），上传一次同完整PDF，knowledge `ea9f9062-ad98-4321-9e8d-b003345ca2b1`。源码/部署身份见同目录 `p0-quality-delivery-20260924.md`。

配置：模型 `gemini-3.7-flash-medium`，摘要模型ID与原基线相同；Wiki synthesis未显式覆盖，按原生规则回退同一摘要模型。standard、无自定义Purpose、max_pages=0，原Embedding及512/80/384/4096分块配置一致，PDF builtin，额外问题生成关闭。仅实验原生页，无正式审核/激活。

## 真实输入验证：PASS

- PDF SHA256仍为 `d4c9611b7a0b0f59e9b37aef6ff0e5d12d42b00ba20daff670630f2d04e5c08a`。
- 17个可检索文本块，最大end_at=5014；按位置恢复全部5014字符，没有缺口/重叠冲突，与先前修复后的真实PDF解析结果逐字一致。
- 原生发现日志明确raw=5014、truncated=5014；不因长度上限截断。旧缺失14行/423字符已恢复。

## 真实链路与失败可见性

上传：2026-09-24T02:55:34.163805Z；解析/向量阶段约7.1秒完成。Wiki原生30秒去抖后于02:56:14开始，候选发现9.284秒成功，产出2实体、8概念。摘要与引用按原生设计并发：摘要16.483秒成功（4318字符，trace仅保留预览），唯一引用batch 10.365秒返回OUTCOME_UNKNOWN。

随后本次文档Wiki操作归档为失败，未执行短提纲正文降级，未生成实体/概念/来源摘要页。02:56:40文档parse_status=completed，表示解析/后处理槽位结算，不代表Wiki成功；处理记录的postprocess.wiki=failed，材料Wiki页面显示“有1条Wiki生成失败记录”。最终pending=0、failed_operations=1，仅系统首页1页，不能当成有效知识生成。

文本模型发送4次：文档摘要、候选发现、引用分类、来源摘要。3条成功usage合计total_tokens=21487（prompt14120、completion4239，供应商total额外3128分类未核实）；引用失败无usage，记未知而非0。没有手工重发，没有进入正文编辑调用。Embedding另计，未将文本统计冒充全部外部调用。

## 当前诊断限制与下一步

本次包裹错误只保存稳定阶段/OUTCOME_UNKNOWN，下游cause仍在内存但未进入trace；现有LLM debug文件记录未开启，不能从该错误反推本次必为EOF或提供方宕机。已检查本地并行代码，没有发现摘要结束导致引用提前取消的证据。向用户请求02:56:23—02:56:34 UTC对应的中转服务日志；不以新建库或反复上传绕过未知发送保护。

健康基线、18项正文审核和原文点击仍 BLOCKED/NOT RUN；当前结果只证明P0-1真实输入及P0-2失败阻断/可见性。后续需复用已有模型诊断能力补足底层错误和成功响应留存，再恢复健康对照。原生内部日志中的batch“success”表示队列结算，不能替代per-document failed；这是待收口的诊断表述。

[实验材料Wiki](http://127.0.0.1:18295/platform/knowledge-bases/8649ee5e-e3a7-4a67-994b-7bbf372025d5?tab=materials)

私密证据暂存：`/private/tmp/g35-live-20260924/native-recheck`，已归档至 `insurancekb-private-evidence/g35-live-20260924/native-recheck`。无provider费用金额推断。
