// QA3 acceptance (protected, written by Claude): a published field is asked when its title is in
// the question or when every term of one of its question-term groups is (navigation
// `question_terms`, Spec docs/design/slices/QA3-字段按问法匹配.md §4). Terms are release data; the
// platform knows no insurance vocabulary. RED until QA3.
package knowledge_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

func termNavigation(terms map[string]any) release.Member {
	payload := map[string]any{
		"navigation_id": "enterprise", "navigation_version": "v2",
		"overview_fields": []string{"waiting_period"},
		"domains": []map[string]any{{
			"domain_key": "product", "display_name": "产品", "entity_types": []string{"product"},
			"groups": []map[string]any{
				{"group_key": "life", "display_name": "寿险", "classification_labels": []string{"life"}},
			},
		}},
	}
	if terms != nil {
		payload["question_terms"] = terms
	}
	return member("navigation", "navigation/enterprise", payload)
}

// Three life products under the shared prefix 庚保; Z's own name carries the words 保额 and 增长.
func termMembers(terms map[string]any) []release.Member {
	rate, rules := [2]string{"sum_assured_growth_rate", "产品利率"}, [2]string{"sum_assured_growth_rules", "保额增长规则"}
	death, waiting := [2]string{"death_benefit_rules", "身故给付规则"}, [2]string{"waiting_period", "等待期"}
	return []release.Member{
		termNavigation(terms),
		profile("life", rate, rules, death, waiting),
		entity("D", []string{"life"}, "庚保金越（尊享版26）终身寿险"),
		entity("H", []string{"life"}, "庚保爱满分两全保险"),
		entity("Z", []string{"life"}, "庚保保额增长宝两全保险"),
		claim("D", "sum_assured_growth_rate", "present", "3.0%。", sourced("k-d")),
		claim("D", "sum_assured_growth_rules", "present", "按基本保险金额复利递增。", sourced("k-d")),
		claim("D", "death_benefit_rules", "present", "按有效保险金额给付。", sourced("k-d")),
		claim("D", "waiting_period", "present", "180日。", sourced("k-d")),
		claim("H", "sum_assured_growth_rate", "absent_explicitly", nil, sourced("k-h")),
		claim("H", "waiting_period", "present", "90日。", sourced("k-h")),
		claim("Z", "sum_assured_growth_rate", "present", "2.5%。", sourced("k-z")),
		claim("Z", "waiting_period", "present", "60日。", sourced("k-z")),
	}
}

var standardTerms = map[string]any{
	"sum_assured_growth_rate": [][]string{{"保额", "增长"}, {"增长比例"}},
	// A term shorter than two characters invalidates its whole group (fail closed).
	"death_benefit_rules": [][]string{{"身", "故"}},
	// A key the release does not publish is ignored.
	"not_published_here": [][]string{{"等待"}},
}

func termAsked(t *testing.T, terms map[string]any, question string) []string {
	t.Helper()
	fields, err := knowledge.NewService(membersReader(termMembers(terms))).QuestionFields(
		context.Background(), tenant, space, pinned, question, 0)
	require.NoError(t, err)
	return slugs(fields)
}

func TestATermGroupSelectsAFieldItsTitleDoesNotName(t *testing.T) {
	// q05: neither 产品利率 nor 保额增长规则 is in the question, but both words of a group are.
	require.Equal(t, []string{"D/sum_assured_growth_rate"},
		termAsked(t, standardTerms, "金越（尊享版26）终身寿险的保额每年按多少增长？"))
	require.Equal(t, []string{"D/sum_assured_growth_rate"},
		termAsked(t, standardTerms, "金越尊享版26终身寿险的增长比例是多少"), "a one-word group")
}

func TestEveryTermOfAGroupMustBeInTheQuestion(t *testing.T) {
	got := termAsked(t, standardTerms, "金越尊享版26终身寿险的保额是多少")
	require.NotContains(t, got, "D/sum_assured_growth_rate", "保额 alone is half a group")
	require.Equal(t, []string{"D/waiting_period"}, got, "nothing asked: the named product's overview")
}

func TestAGroupWithATooShortTermNeverMatches(t *testing.T) {
	got := termAsked(t, standardTerms, "金越尊享版26终身寿险身故怎么赔")
	require.NotContains(t, got, "D/death_benefit_rules")
}

func TestWithoutQuestionTermsSelectionIsUnchanged(t *testing.T) {
	require.Equal(t, []string{"D/waiting_period"},
		termAsked(t, nil, "金越（尊享版26）终身寿险的保额每年按多少增长？"),
		"no terms: only titles are matched, so the product's overview comes")
	require.Equal(t, []string{"D/waiting_period"},
		termAsked(t, nil, "金越尊享版26终身寿险的等待期多长"), "titles still match")
}

func TestATermMatchIsAnAskedFieldWithinTheNamedProducts(t *testing.T) {
	require.Equal(t, []string{"D/sum_assured_growth_rate"},
		termAsked(t, standardTerms, "金越尊享版26终身寿险保额怎么增长"),
		"only the named product's field, not the other products' rate")
	require.Equal(t,
		[]string{"D/sum_assured_growth_rate", "H/sum_assured_growth_rate", "Z/sum_assured_growth_rate"},
		termAsked(t, standardTerms, "哪些产品的保额会增长"), "no product named: every product compares")
}

func TestAGroupMatchedOnlyByANamedProductsNameAlsoBringsItsOverview(t *testing.T) {
	// 保额 and 增长 are both inside Z's name: like a title inside a product name (QA2 §4).
	require.Equal(t, []string{"Z/sum_assured_growth_rate", "Z/waiting_period"},
		termAsked(t, standardTerms, "保额增长宝两全保险怎么样"))
	require.Equal(t, []string{"Z/sum_assured_growth_rate"},
		termAsked(t, standardTerms, "保额增长宝两全保险的增长比例"),
		"a group outside the name keeps the asked field only")
}
