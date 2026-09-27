# G35-R2/R5：准入引用目标的公开边界

2026-09-27，root唯一Owner；用户G3.5持续授权。真实两窗口任务3965eb5b的v4
输入同时提供entity_id和entity_version，但existing_target公开schema允许任意字符串，
strict投影只接受entity_id/既有concept_id/page_id。修正输入合同，不迁就模型输出。

- **REF-TARGET-1**：v4 provider view MUST明确列举服务端当前允许的引用身份，
  即当前entity_id、existing_knowledge.definitions的concept_id及pages的page_id，
  排序去重；不得把entity_version、别名、Schema字段或revision当作目标。
- **REF-TARGET-2**：公开response schema MUST要求REFERENCE使用上述非空身份，
  其他decision的existing_target必须null；说明当前产品使用entity_id。
  该schema是降低模型任务难度的输入合同，strict projector仍是最终权威；不保证模型遵守。
- **REF-TARGET-3**：原始响应、strict projector、v2领域合同及历史v3 MUST保持。
  不剥离@version、不归一化未知身份、不补写模型决定；输入字节/hash改变使旧准入调用
  不可exact复用，上游发现/引用仍按其既有输入身份复用，不重建任务或发布平台。
- **REF-TARGET-4**：多窗口候选均无promoted member是合法空结果，保留完整依赖审计，
  不要求模型凑页。真实恢复验收必须区分空结果与有价值非空知识，后者仍须R7验证。

写域：native_relation_wire.py、test_native_reference_targets.py、
test_native_multiwindow_closure.py、harness/pyproject.toml及uv.lock（测试显式使用已有锁定的
JSON Schema校验器）及本文件。先RED，再最小实现/定向检查/独审，
必要Harness-only交付后经原UI恢复；不顺带修改评分或Schema去重策略。
