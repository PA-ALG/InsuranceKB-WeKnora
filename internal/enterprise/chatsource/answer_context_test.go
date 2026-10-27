package chatsource

// Updated by Claude in the QA1 RED commit (Spec docs/design/slices/QA1-问答来源标注与范围说明.md §4.1):
// Agent and MCP tools now show the same Chinese states as quick answers, so the tool text no
// longer keeps the English state and the quick-answer-only answerFieldText is gone.

import (
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/stretchr/testify/require"
)

func TestFieldStatesUseChineseInEveryTool(t *testing.T) {
	for _, tc := range []struct{ state, value, want string }{
		{"present", "20 days", "20 days"},
		{"absent_explicitly", "", "材料明确没有"},
		{"unknown", "", "已发布知识未收录（不代表材料没有）"},
	} {
		t.Run(tc.state, func(t *testing.T) {
			f := knowledge.Field{
				EntityName: "Product", FieldTitle: "field", State: tc.state, Value: tc.value,
				Origin: "SOURCE_SUPPORTED", Evidence: []knowledge.Evidence{{Quote: "quoted material", Page: 3}},
			}
			text := knowledge.FieldText(f)
			require.Contains(t, text, "Product · field："+tc.want)
			require.NotContains(t, text, tc.state)
			require.Contains(t, text, "引文：quoted material（第 3 页）")
		})
	}
}
