// QA2b acceptance (protected, written by Claude, review R4 on #399): a shared series name must
// begin each carrier's core name — the first name without the prefix all products' first names
// share (QA2 §3) — never just an alias (Spec docs/design/slices/QA2b-共用名称与只用本品补足.md §2a).
package knowledge_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

const aliasRelease = "rel-alias"

type aliasReader struct{}

func (aliasReader) ReleaseByID(
	_ context.Context, tenantID uint64, spaceID, releaseID string,
) (release.Release, error) {
	if tenantID != tenant || spaceID != space || releaseID != aliasRelease {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return release.Release{ID: aliasRelease, Epoch: 1, Members: []release.Member{
		profile("plan", [2]string{"cooling_off_period", "犹豫期"}),
		entity("AA", []string{"plan"}, "甲保保障一号星辰宝计划", "星辰宝甲款"),
		entity("BB", []string{"plan"}, "甲保保障二号星辰宝计划", "星辰宝乙款"),
		entity("CC", []string{"plan"}, "甲保另一健康保险"),
		claim("AA", "cooling_off_period", "present", "15日。", sourced("k-aa")),
		claim("BB", "cooling_off_period", "present", "20日。", sourced("k-bb")),
	}}, nil
}

func aliasNamed(t *testing.T, question string) []string {
	t.Helper()
	products, err := knowledge.NewService(aliasReader{}).QuestionProducts(
		context.Background(), tenant, space, aliasRelease, question)
	require.NoError(t, err)
	out := []string{}
	for _, product := range products {
		out = append(out, product.EntityID)
	}
	return out
}

func TestASeriesNameMustBeginTheCoreNotJustAnAlias(t *testing.T) {
	// 星辰宝 begins both aliases but sits in the middle of both cores (保障一号星辰宝计划).
	require.Empty(t, aliasNamed(t, "星辰宝的犹豫期多久"))
	require.Equal(t, []string{"AA"}, aliasNamed(t, "星辰宝甲款的犹豫期多久"), "a full alias still names its product")
}
