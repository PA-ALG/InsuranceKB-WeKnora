package knowledge

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestQueryConceptOmitsWholeInvisibleOrStaleStatement(t *testing.T) {
	first := queryClaim("not/an/entity/predicate", "E", "a", "present", "1")
	second := queryClaim("second", "E", "b", "present", "2")
	concept := queryMember("concept", "concept/key", map[string]any{
		"concept_key": "some_key", "title": "概念标题", "definition": "定义", "explanation": "说明",
		"based_on": map[string]string{first.LogicalSlug: first.MemberDigest, second.LogicalSlug: "outdated"},
		"statements": []any{
			map[string]any{"text": "valid", "refs": []string{first.LogicalSlug}},
			map[string]any{"text": "stale", "refs": []string{first.LogicalSlug, second.LogicalSlug}},
			map[string]any{"text": "missing", "refs": []string{"missing"}},
			map[string]any{"text": "not a Claim", "refs": []string{"entity/E"}},
		},
	})
	s := queryService(queryEntity("E", "产品"), first, second, concept)
	got, err := s.Concept(context.Background(), 7, "space", "pinned", "概 念　标题")
	require.NoError(t, err)
	require.Equal(t, "定义", got.Definition)
	require.Equal(t, "说明", got.Explanation)
	require.Equal(t, []Statement{{Text: "valid", Refs: []string{first.LogicalSlug}}}, got.Statements)
	require.Equal(t, 3, got.OmittedStatements)
}

func TestQueryConceptWithoutBasisStillChecksVisibility(t *testing.T) {
	s := queryService(queryEntity("E", "产品"), queryClaim("visible", "E", "a", "present", "1"),
		queryMember("concept", "concept/key", map[string]any{
			"concept_key": "key", "title": "title", "definition": "定义", "explanation": "说明",
			"statements": []any{
				map[string]any{"text": "visible", "refs": []string{"visible"}},
				map[string]any{"text": "missing", "refs": []string{"hidden"}},
			},
		}))
	got, err := s.Concept(context.Background(), 7, "space", "pinned", "Ｋ Ｅ Ｙ")
	require.NoError(t, err)
	require.Len(t, got.Statements, 1)
	require.Equal(t, 1, got.OmittedStatements)
}
