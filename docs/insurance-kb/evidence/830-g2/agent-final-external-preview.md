# 最后一轮 G2 问答外发预览

目的：验证已经发布的第5版知识，真实完成检索→读页→回答。接收方：DeepSeek，https://api.deepseek.com/v1，现有模型配置 b2034da8-942c-4a19-945d-1bc09459222e。

用户问题：请先用 wiki_search 在唯一选中的 Wiki 中搜索“被保险人”，再用 wiki_read_page 读取搜索返回的 member_id，最后仅依据该页回答：被保险人是什么意思？

目标页标题：被保险人。正文：被保险人就是受保险合同保障的人。

发送范围：上面的问题、系统/工具说明、选中G2 Wiki的基本元信息、检索工具返回的已发布内容和来源、读页返回的这条定义及来源标识。后端在这一轮固定使用release-9cb493e3-8d27-4a0f-8f29-93e2a078725b / epoch5。不会发送认证口令或API密钥作为提示内容。

动作：G2内创建一个限定Wiki检索/读页的测试Agent及空会话，发送1轮问题。模型HTTP尝试保守上限13（含引擎内部重试），脚本/整轮不重试，无重新编译或发布。

下面列出冻结输入的目标知识/来源标识及完整问答请求。实际模型提示由现有Agent引擎生成，工具结果在执行时产生。

```json
{
  "member": {
    "content_sha256": "0977effd449c84298ef44b547b40b3905908820cd682f358280b0c4d77354d30",
    "kind": "concept",
    "member_digest": "badcb24a292ca9deff0687eaa012359d66250b50d7dac40f624f4e05f27b0e17",
    "member_id": "concept_fa49ae2d3cc604c00743976b752f611aaaa174b8cd5da55078dbb3042e819c9c",
    "owner_id": "a8751a40-83ce-55c8-a160-079b283483ca",
    "source_identities": [
      {
        "block_id": "696b1c7f-a52f-4871-a521-4cb526570245",
        "knowledge_id": "f987fc16-222a-4246-8ca0-22c1a81dd6d9",
        "page_number": 1,
        "parse_attempt": 2,
        "parse_hash": "f2190b125469819ea0d97603c71f4fb19e4a92fa09117582b4d581947a0de414",
        "quote_hash": "0977effd449c84298ef44b547b40b3905908820cd682f358280b0c4d77354d30",
        "revision_id": "ea7160149d2fd99ea4a4960c50bfa6ca3641e4532956671b9956f4f8b57ad681",
        "source_hash": "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
        "source_type": "DOCUMENT"
      }
    ],
    "title": "被保险人"
  },
  "turn_request": {
    "agent_enabled": true,
    "agent_id": "{created_agent_id}",
    "disable_title": true,
    "images": [],
    "knowledge_base_ids": [],
    "knowledge_ids": [],
    "mcp_service_ids": [],
    "mentioned_items": [],
    "query": "请先用 wiki_search 在唯一选中的 Wiki 中搜索“被保险人”，再用 wiki_read_page 读取搜索返回的 member_id，最后仅依据该页回答：被保险人是什么意思？",
    "skill_names": [],
    "web_search_enabled": false
  },
  "agent_config": {
    "avatar": "",
    "config": {
      "agent_mode": "smart-reasoning",
      "agent_type": "custom",
      "allowed_tools": [
        "wiki_search",
        "wiki_read_page"
      ],
      "asr_model_id": "",
      "attachment_image_understanding": false,
      "audio_upload_enabled": false,
      "citation_enabled": false,
      "context_template": "",
      "data_analysis_enabled": false,
      "enable_query_expansion": false,
      "enable_rewrite": false,
      "fallback_response": "Smoke verification could not obtain the required release-bound page.",
      "fallback_strategy": "fixed",
      "image_upload_enabled": false,
      "kb_selection_mode": "selected",
      "knowledge_bases": [
        "8d5695de-f255-42d5-9a41-042ba86e97b9"
      ],
      "llm_call_timeout": 180,
      "max_completion_tokens": 2048,
      "max_iterations": 2,
      "mcp_selection_mode": "none",
      "mcp_services": [],
      "model_id": "b2034da8-942c-4a19-945d-1bc09459222e",
      "multi_turn_enabled": false,
      "question_suggestions": {
        "follow_ups": {
          "allow_regenerate": false,
          "categories": [
            "clarify"
          ],
          "count": 1,
          "enabled": false,
          "knowledge_fallback": false,
          "max_context_turns": 1,
          "mode": "generated",
          "suppress_on_fallback": true,
          "suppress_when_answer_asks_question": true
        },
        "starters": {
          "count": 1,
          "enabled": false,
          "items": [],
          "mode": "curated"
        }
      },
      "rerank_model_id": "",
      "retain_retrieval_history": false,
      "retrieve_kb_only_when_mentioned": false,
      "selected_skills": [],
      "skills_selection_mode": "none",
      "system_prompt": "For this smoke turn, call wiki_search exactly once for 被保险人 in the selected Wiki, then call wiki_read_page exactly once with the returned member_id, then answer only from that page. Do not call any other tool.",
      "temperature": 0,
      "thinking": false,
      "vlm_model_id": "",
      "web_fetch_enabled": false,
      "web_search_enabled": false
    },
    "description": "One-turn isolated verification of managed Wiki release search and page read.",
    "name": "G2 release pin smoke"
  },
  "scope": {
    "raw_kb_id": "b1f1764c-443d-46b8-98e3-d5aa5e55eb42",
    "space_id": "a8751a40-83ce-55c8-a160-079b283483ca",
    "tenant_id": 10003,
    "wiki_kb_id": "8d5695de-f255-42d5-9a41-042ba86e97b9"
  }
}
```
