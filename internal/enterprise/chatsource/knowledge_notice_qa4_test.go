package chatsource

// QA4 acceptance (protected, written by Claude): an enterprise agent turn must not answer a
// specific product's rules from common knowledge (Spec docs/design/slices/QA4-Agent本品口径.md §2).
// RED until QA4 adds the rule.

import (
	"testing"

	"github.com/stretchr/testify/require"
)

var qa4Rules = []string{
	"不用常识、行业通行做法或其他产品的规定回答具体产品的事实。",
	"材料没有写的内容，说明材料未载明，不写进结论，也不给它挂来源句柄。",
	"来源句柄必须能支撑同一行的事实，不能借用相邻条款的句柄。",
}

func TestTheAgentNoticeForbidsCommonKnowledgeProductRules(t *testing.T) {
	turns := map[string]Turn{
		"published knowledge only": {WikiSpaces: []string{"space"}},
		"published knowledge and raw retrieval": {
			WikiSpaces:   []string{"space"},
			RawKnowledge: map[string]string{"k-1": "space"},
		},
	}
	for name, turn := range turns {
		notice := KnowledgeNotice(turn)
		for _, rule := range qa4Rules {
			require.Contains(t, notice, rule, name)
		}
		require.Contains(t, notice, "回答中的每一条产品事实都必须在同一行带上支撑它的来源句柄", name)
	}
	require.Empty(t, KnowledgeNotice(Turn{}), "turns without a wiki KB get no enterprise notice")
}
