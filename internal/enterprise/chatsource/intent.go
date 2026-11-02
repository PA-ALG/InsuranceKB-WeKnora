package chatsource

import (
	"context"

	"github.com/Tencent/WeKnora/internal/logger"
	"github.com/Tencent/WeKnora/internal/types"
)

// AnswerIntent runs after question understanding. A turn that reads enterprise knowledge with
// web search off has only the knowledge base to answer a web_search question ("can I still buy
// it now?"); natively that intent retrieves nothing and the answer says web search is
// unavailable. Such a turn is answered as kb_search instead (QA5).
//
// Clearing SystemPromptOverride gives exactly the state a kb_search reply leaves: question
// understanding writes it only for an intent that retrieves nothing. Remove once the native
// pipeline lets a scope route web_search to the knowledge base when web search is off.
func AnswerIntent(ctx context.Context, event types.EventType, cm *types.ChatManage) {
	if event != types.QUERY_UNDERSTAND || cm == nil {
		return
	}
	if cm.Intent != types.IntentWebSearch || cm.WebSearchEnabled {
		return
	}
	if !HasPublished(ctx) && !IsEnterpriseAnswer(ctx) {
		return
	}
	cm.Intent = types.IntentKBSearch
	cm.SystemPromptOverride = ""
	logger.Info(ctx, "enterprise answer: web_search intent without web search reads the knowledge base")
}
