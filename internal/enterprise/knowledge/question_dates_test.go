package knowledge_test

import (
	"testing"

	"github.com/stretchr/testify/require"
)

// #517 R1: a purchase date is a whole token. Digits or a code joined to it make it part of a longer
// number, which is no date, so a service question keeps every version; real dates still select.
func TestServiceQuestionDatesAreWholeTokens(t *testing.T) {
	both := []string{"V1/waiting_period", "V2/waiting_period"}
	cases := map[string][]string{
		"保单号2023-06-180001的甲护理保险理赔等待期":           both,
		"保单号2023/6/180001的甲护理保险理赔等待期":            both,
		"保单号12023-06-18的甲护理保险理赔等待期":              both,
		"单号ab2023-06-18投保的甲护理保险理赔等待期":            both,
		"单号2023-06-18x投保的甲护理保险理赔等待期":             both,
		"保单号2023-06-18-0001的甲护理保险理赔等待期":          both,
		"保单号no.2023-06-18的甲护理保险理赔等待期":            both,
		"2023年6月180001号的甲护理保险理赔等待期":              both,
		"2023-06-18投保的甲护理保险理赔等待期":                {"V1/waiting_period"},
		"2025/3/1投保的甲护理保险理赔等待期。":                 {"V2/waiting_period"},
		"在2023年6月18日投保的甲护理保险理赔等待期":               {"V1/waiting_period"},
		"保单号2023-06-180001，2025年3月投保的甲护理保险理赔等待期": {"V2/waiting_period"},
	}
	for question, want := range cases {
		require.ElementsMatch(t, want, questionSlugs(t, intents, question), question)
	}
}
