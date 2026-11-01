package chatsource

import (
	"context"

	"github.com/Tencent/WeKnora/internal/types"
)

// NotFoundAnswer avoids inferring product facts from missing retrieval results.
const NotFoundAnswer = "已发布知识和当前版本固定的原文中都没有找到相关内容。"

type answerKey struct{}

type answerScope struct{ modelTargets types.SearchTargets }

// IsEnterpriseAnswer excludes ordinary KB, search, Agent and MCP turns.
func IsEnterpriseAnswer(ctx context.Context) bool {
	_, active := ctx.Value(answerKey{}).(answerScope)
	return active
}

func answerSurface(ctx context.Context) bool {
	principal, _ := types.PrincipalFromContext(ctx)
	return principal.Type != types.PrincipalMCPEndpoint && ctx.Value(types.MCPEndpointContextKey) == nil
}

func markAnswer(ctx context.Context, modelTargets types.SearchTargets) context.Context {
	if !answerSurface(ctx) {
		return ctx
	}
	if turn, ok := TurnFromContext(ctx); ok && len(turn.Releases) > 0 {
		return context.WithValue(ctx, answerKey{}, answerScope{modelTargets: modelTargets})
	}
	return ctx
}

// AnswerModelScope preserves the pre-expansion model choice, including the
// existing raw/ordinary preference in explicit mixed selections.
func AnswerModelScope(ctx context.Context, kbIDs, ids []string) ([]string, []string) {
	if scope, ok := ctx.Value(answerKey{}).(answerScope); ok {
		return TargetScope(scope.modelTargets)
	}
	return kbIDs, ids
}

// AnswerRules is appended after any selected system prompt or intent override.
func AnswerRules(ctx context.Context) string {
	if !IsEnterpriseAnswer(ctx) {
		return ""
	}
	return `

企业 Space 快问快答规则：
1. 已发布知识（审核过）能回答的，以它为准。
2. 已发布知识没有覆盖或字段为“已发布知识未收录”的，用当前版本固定的原文检索内容回答，并说明这部分来自“原文检索（未经编译审核）”。未收录不代表材料没有。
3. 两者都没有时，只说明“已发布知识和当前版本固定的原文中都没有找到相关内容。”，不得据此说“没有规定”。
4. 不用常识回答具体产品事实。模型整理（未逐条审核）不能代替已发布字段或原文证据。`
}

// AnswerPassage labels both initial rendering and the final filtered model context.
func AnswerPassage(ctx context.Context, result *types.SearchResult, content string) string {
	if !IsEnterpriseAnswer(ctx) || result == nil || content == "" {
		return content
	}
	var tier string
	switch result.Metadata["source_tier"] {
	case "release":
		// Method knowledge is not a reviewed product fact; its text opens with its profile's
		// reading note instead (SK-3 §6.3).
		if result.Metadata["knowledge_class"] == "method" {
			return content
		}
		tier = "已发布知识（审核过）"
	case "raw_text":
		tier = rawTier(ctx, result)
	case "wiki_page":
		tier = "模型整理（未逐条审核）"
	}
	if tier == "" {
		return content
	}
	return tier + "\n" + content
}
