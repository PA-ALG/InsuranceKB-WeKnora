package chatsource

import (
	"context"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

// RegisterKnowledgeTools provides only the Wiki Spaces admitted for this turn.
// Other tool whitelists and raw-source wrapping remain independent.
func RegisterKnowledgeTools(
	ctx context.Context, registry interface{ RegisterTool(types.Tool) }, service *knowledge.Service, turn Turn,
) error {
	if len(turn.WikiSpaces) == 0 {
		return nil
	}
	tenant, ok := types.TenantIDFromContext(ctx)
	if !ok || tenant == 0 {
		return &release.Error{Code: release.ErrorReleaseAccessDenied, Detail: "Wiki tools require an executing tenant"}
	}
	scopes := make(map[string]string, len(turn.WikiSpaces))
	for _, space := range turn.WikiSpaces {
		id := turn.Releases[space]
		if space == "" || id == "" || id == "active" {
			return &release.Error{Code: release.ErrorReleaseNotFound, Detail: "Wiki tools require a fixed release"}
		}
		scopes[space] = id
	}
	for _, tool := range knowledge.NewTools(service, tenant, scopes) {
		registry.RegisterTool(tool)
	}
	return nil
}

// KnowledgeNotice separates published facts, model aids and fixed raw retrieval.
func KnowledgeNotice(turn Turn) string {
	if len(turn.WikiSpaces) == 0 {
		return ""
	}
	notice := "已发布知识优先：先用 knowledge_find_entity、knowledge_get_fields、" +
		"knowledge_search_fields、knowledge_get_concept 查询本轮固定发布版本。" +
		"回答产品事实时引用当前工具返回的字段句柄。" +
		"只有字段为“材料明确没有”时，才能说该产品没有这项规定；字段为“已发布知识未收录”、搜索没有命中或页面没有结果，" +
		"都不代表材料没有，只能说已发布知识未收录（不代表材料没有）。" +
		"要说某个产品没有某项规定，先用 knowledge_get_fields 读取该产品的这一项。" +
		"没有 Evidence 的内容不标审核过、不制造出处。" +
		"概念定义、说明和概括是模型补充（概念说明），与已举证的产品字段分开，不把模型补充当审核事实。" +
		"字段查不到时，可用 knowledge_search_pages 查延伸阅读页面；页面是模型整理（未逐条审核），" +
		"回答中如实标注，不当作审核过的事实；与字段冲突时以字段为准。"
	if len(turn.RawKnowledge) > 0 {
		notice += "已发布知识查不到时可用原文检索补充；原文仅限本轮固定材料，明确标注原文检索（未经编译审核），不能混淆两种来源。" +
			"原文片段标题前标有所属产品，只能用于该产品；所属产品未识别的片段，不能当作任何具体产品的规定。"
	}
	notice += "不用常识、行业通行做法或其他产品的规定回答具体产品的事实。" +
		"材料没有写的内容，说明材料未载明，不写进结论，也不给它挂来源句柄。" +
		"来源句柄必须能支撑同一行的事实，不能借用相邻条款的句柄。" +
		`回答中的每一条产品事实都必须在同一行带上支撑它的来源句柄（如 <ref id="c1"/>）；` +
		"找不到可引用来源的产品事实不要写，改为说明未找到。"
	return notice
}
