package chatsource

// S6e acceptance (Spec docs/design/slices/S6e-问答读取延伸阅读页面.md §2.4). Protected file:
// written by Claude. The notice names the page tool and its label, after published fields and
// before raw retrieval. RED until S6e.

import (
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestKnowledgeNoticeOffersPagesAfterFieldsAndBeforeRawText(t *testing.T) {
	notice := KnowledgeNotice(Turn{WikiSpaces: []string{"s1"}, RawKnowledge: map[string]string{"s1": "kb"}})
	pages := strings.Index(notice, "knowledge_search_pages")
	require.Positive(t, pages)
	require.Contains(t, notice, "模型整理（未逐条审核）")
	require.Less(t, strings.Index(notice, "knowledge_get_fields"), pages)
	require.Less(t, pages, strings.Index(notice, "原文检索"))
	require.Contains(t, KnowledgeNotice(Turn{WikiSpaces: []string{"s1"}}), "knowledge_search_pages")
}
