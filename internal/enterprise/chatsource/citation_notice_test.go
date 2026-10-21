package chatsource

// Q2b acceptance (protected, written by Claude): an enterprise agent turn must cite every product
// fact (Spec docs/design/slices/Q2b-Agent回答引用.md §4). RED until Q2b adds the requirement.

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestTheKnowledgeNoticeRequiresACitationForEveryProductFact(t *testing.T) {
	notice := KnowledgeNotice(Turn{WikiSpaces: []string{"space"}})
	require.Contains(t, notice, "回答中的每一条产品事实都必须在同一行带上支撑它的来源句柄")
	require.Contains(t, notice, `<ref id="c1"/>`)
	require.Contains(t, notice, "找不到可引用来源的产品事实不要写，改为说明未找到")
	require.Empty(t, KnowledgeNotice(Turn{}), "turns without a wiki KB get no enterprise notice")
}
