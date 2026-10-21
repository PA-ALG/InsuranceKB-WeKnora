package chatsource

import (
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/stretchr/testify/require"
)

func TestAnswerFieldStatesUseChineseWithoutChangingToolText(t *testing.T) {
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
			text := answerFieldText(f)
			require.Contains(t, text, tc.want)
			require.NotContains(t, text, tc.state)
			require.Contains(t, text, "引文：quoted material（第 3 页）")
			require.Contains(t, knowledge.FieldText(f), tc.state)
		})
	}
}
