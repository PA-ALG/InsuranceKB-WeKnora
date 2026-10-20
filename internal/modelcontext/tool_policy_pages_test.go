package modelcontext

// S6e acceptance (Spec docs/design/slices/S6e-问答读取延伸阅读页面.md §2.3). Protected file:
// written by Claude. The page tool's rows reach the model through source handles, like the other
// published-knowledge tools. RED until S6e.

import "testing"

func TestPageSearchToolUsesSourceHandles(t *testing.T) {
	policy, ok := toolHandlePolicies["knowledge_search_pages"]
	if !ok || !policy.sourceOutput || policy.opaqueOutput {
		t.Fatalf("knowledge_search_pages must emit source-handled output, got %+v (registered=%v)", policy, ok)
	}
}
