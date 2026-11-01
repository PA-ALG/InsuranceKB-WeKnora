// SK-3 acceptance: quick answers take method fields for method questions (Spec
// docs/design/slices/SK-3-销售方法阅读与问答.md §6.1–§6.2). Protected file: written by Claude.
//
// The method intent is the navigation's question_intents.method data, independent of the sales and
// service intents. A method question takes the methods it names, those related to the products it
// names (family or labels), those in a navigation group it names, else those sharing at least two
// bigrams with it; their evidenced fields come first and fill at most half the limit. Without the
// intent no method field is taken, even when a method field's title is asked. Reuses the fixture
// of methods_acceptance_test.go. RED until SK-3 implements it.
package knowledge_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"
)

func askMethods(t *testing.T, question string, limit int) []string {
	t.Helper()
	fields, err := methodService().QuestionFields(context.Background(), tenant, space, pinned, question, limit)
	require.NoError(t, err)
	return slugs(fields)
}

func TestAMethodQuestionTakesTheNamedMethodsEvidencedFields(t *testing.T) {
	require.Equal(t, []string{"sm-1/method_summary", "sm-1/method_steps"}, askMethods(t, "需求分析三步法怎么讲", 12),
		"the unknown key_phrases is left out")
}

func TestAMethodQuestionAboutAProductTakesItsRelatedMethodsFirst(t *testing.T) {
	require.Equal(t, []string{"sm-1/method_summary", "sm-1/method_steps", "M1/cooling_off_period"},
		askMethods(t, "甲医疗保险怎么讲", 12), "related methods first, then the product's overview")
	require.Equal(t, []string{"sm-1/method_summary", "M1/cooling_off_period"}, askMethods(t, "甲医疗保险怎么讲", 2),
		"methods fill at most half the limit")
}

func TestAMethodQuestionNamingAGroupTakesTheMethodsOfThatGroup(t *testing.T) {
	require.Equal(t, []string{"sm-1/method_summary", "sm-1/method_steps"}, askMethods(t, "医疗怎么讲", 12))
}

func TestAMethodQuestionWithoutNamesFallsBackToSharedBigrams(t *testing.T) {
	require.Equal(t, []string{"sm-2/method_summary"}, askMethods(t, "客户异议怎么讲", 12))
	require.Empty(t, askMethods(t, "这个怎么讲", 12), "the intent words alone share nothing")
}

func TestQuestionsWithoutTheMethodIntentNeverTakeMethods(t *testing.T) {
	require.Equal(t, []string{"M1/cooling_off_period"}, askMethods(t, "甲医疗保险的犹豫期", 12))
	require.Empty(t, askMethods(t, "需求分析三步法的步骤", 12), "a method field title alone is no product field")
}

func TestTheMethodIntentIsIndependentOfTheSalesIntent(t *testing.T) {
	require.Equal(t, []string{"sm-1/method_summary", "sm-1/method_steps"}, askMethods(t, "推荐需求分析三步法怎么讲", 12))
}
