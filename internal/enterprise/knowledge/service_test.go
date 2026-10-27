package knowledge

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/stretchr/testify/require"
)

type queryReader struct {
	release release.Release
	err     error
	called  int
}

func (r *queryReader) ReleaseByID(context.Context, uint64, string, string) (release.Release, error) {
	r.called++
	return r.release, r.err
}

func queryMember(kind, slug string, payload any) release.Member {
	raw, err := json.Marshal(payload)
	if err != nil {
		panic(err)
	}
	return release.Member{
		Kind: kind, LogicalSlug: slug, Payload: raw, MemberDigest: "digest:" + slug, AccessScope: "space",
	}
}

func queryEntity(id, name string, labels ...string) release.Member {
	return queryMember("entity", "entity/"+id, map[string]any{
		"entity_id": id, "names": []string{name}, "classification_labels": labels, "entity_type": "product",
	})
}

func queryClaim(slug, subject, predicate, state string, value any) release.Member {
	return queryMember("claim", slug, map[string]any{
		"subject_ref": subject, "predicate": predicate, "state": state, "value": value,
	})
}

func queryProfile(slug string, labels []string, fields ...[2]string) release.Member {
	items := make([]map[string]string, 0, len(fields))
	for _, field := range fields {
		items = append(items, map[string]string{"field_key": field[0], "short_title": field[1]})
	}
	return queryMember("presentation_profile", slug, map[string]any{
		"classification_labels": labels, "sections": []any{map[string]any{"fields": items}},
	})
}

func queryService(members ...release.Member) *Service {
	return NewService(&queryReader{release: release.Release{ID: "pinned", Members: members}})
}

func fieldSlugs(fields []Field) []string {
	slugs := make([]string, 0, len(fields))
	for _, field := range fields {
		slugs = append(slugs, field.Slug)
	}
	return slugs
}

func TestQueryRejectsImplicitVersionsAndInconsistentReader(t *testing.T) {
	r := &queryReader{release: release.Release{ID: "pinned"}}
	s := NewService(r)
	for _, id := range []string{"", " ", "active", " ACTIVE "} {
		_, err := s.FindEntities(context.Background(), 7, "space", id, "", 0)
		require.Error(t, err)
	}
	require.Zero(t, r.called, "a bad version must never reach a reader's Active path")
	_, err := s.FindEntities(context.Background(), 7, "space", "different", "", 0)
	require.Error(t, err, "a reader cannot silently return another version")
	_, err = NewService(nil).FindEntities(context.Background(), 7, "space", "pinned", "", 0)
	require.Error(t, err)
	var nilReader *queryReader
	_, err = NewService(nilReader).FindEntities(context.Background(), 7, "space", "pinned", "", 0)
	require.Error(t, err)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err = s.FindEntities(ctx, 7, "space", "pinned", "", 0)
	require.ErrorIs(t, err, context.Canceled)
	_, err = s.FindEntities(context.Background(), 0, "space", "pinned", "", 0)
	require.Error(t, err)
}

func TestQueryFieldsPreserveRepeatedClaimsAndFirstMatchingProfile(t *testing.T) {
	s := queryService(
		queryProfile("wrong", []string{"other"}, [2]string{"b", "错误"}),
		queryProfile("first", []string{"x"},
			[2]string{"b", "等待期"}, [2]string{"a", "甲 字段"}, [2]string{"b", "重复"}),
		queryProfile("second", []string{"x"}, [2]string{"a", "不应采用"}),
		queryEntity("E", "产品", "x"),
		queryClaim("unusual/完整/slug/甲", "E", "z", "unknown", "不应泄漏"),
		queryClaim("b/version2", "E", "b", "present", []any{"  ", "30日", 2}),
		queryClaim("a/one", "E", "a", "absent_explicitly", "不应泄漏"),
		queryClaim("b/version1", "E", "b", "present", "60日"),
		queryClaim("other", "E", "y", "present", "值"),
	)
	got, err := s.EntityFields(context.Background(), 7, "space", "pinned", "E", nil)
	require.NoError(t, err)
	require.Equal(t, []string{"b/version2", "b/version1", "a/one", "unusual/完整/slug/甲", "other"}, fieldSlugs(got))
	require.Equal(t, "等待期", got[0].FieldTitle)
	require.Equal(t, "30日；2", got[0].Value)
	require.Empty(t, got[2].Value)
	require.Empty(t, got[3].Value)
	picked, err := s.EntityFields(context.Background(), 7, "space", "pinned", "Ｅ", []string{"甲\t字段"})
	require.NoError(t, err)
	require.Equal(t, []string{"a/one"}, fieldSlugs(picked))
	precise, err := s.fieldsForSlugs(context.Background(), 7, "space", "pinned",
		[]string{"unusual/完整/slug/甲", "E/z", "b/version1", "b/version1"})
	require.NoError(t, err)
	require.Equal(t, []string{"unusual/完整/slug/甲", "b/version1"}, fieldSlugs(precise))
}

func TestQueryFieldSelectionPrefersExactMatchBeforeFuzzy(t *testing.T) {
	s := queryService(queryEntity("E", "产品", "x"),
		queryProfile("profile", []string{"x"}, [2]string{"a", "等待期"}, [2]string{"b", "等待期说明"}),
		queryClaim("a", "E", "a", "present", "1"), queryClaim("b", "E", "b", "present", "2"))
	got, err := s.EntityFields(context.Background(), 7, "space", "pinned", "E", []string{"等待期说明"})
	require.NoError(t, err)
	require.Equal(t, []string{"b"}, fieldSlugs(got))
}

func TestQuerySearchUsesSpaceTokensAndNavigationFirstGroups(t *testing.T) {
	navigation := queryMember("navigation", "nav", map[string]any{"domains": []any{
		map[string]any{"entity_types": []string{"product"}, "groups": []any{
			map[string]any{"group_key": "first", "classification_labels": []string{"first"}},
			map[string]any{"group_key": "second", "classification_labels": []string{"second"}},
		}},
	}})
	s := queryService(navigation,
		queryEntity("other", "其他"), queryEntity("second", "第二", "second"),
		queryEntity("first", "第一", "first"),
		queryClaim("other/field", "other", "Title", "present", "a b"),
		queryClaim("second/field", "second", "Title", "present", "a\t b"),
		queryClaim("first/empty", "first", "Title", "present", "  "),
		queryClaim("first/unknown", "first", "Title", "unknown", "a b"),
		queryClaim("first/field", "first", "Title", "present", "a b"))
	got, total, err := s.SearchFields(context.Background(), 7, "space", "pinned", "ＴＩＴＬＥ　a\n b", "", 1)
	require.NoError(t, err)
	require.Equal(t, []string{"first/field"}, fieldSlugs(got))
	require.Equal(t, 3, total)
	got, total, err = s.SearchFields(context.Background(), 7, "space", "pinned", "ab", "", 0)
	require.NoError(t, err)
	require.Empty(t, got)
	require.Zero(t, total)
	got, total, err = s.SearchFields(context.Background(), 7, "space", "pinned", "a b", "", 0)
	require.NoError(t, err)
	require.Equal(t, []string{"first/field", "second/field", "other/field"}, fieldSlugs(got))
	require.Equal(t, 3, total)
}

func TestQueryEntityRuneBigramsAndDefaultLimit(t *testing.T) {
	members := []release.Member{queryEntity("best", "𠮷甲乙丙")}
	for _, id := range []string{"1", "2", "3", "4", "5", "6"} {
		members = append(members, queryEntity(id, "甲乙丙"))
	}
	s := queryService(members...)
	got, err := s.FindEntities(context.Background(), 7, "space", "pinned", "𠮷甲乙是啥", 0)
	require.NoError(t, err)
	require.Len(t, got, 1)
	require.Equal(t, "best", got[0].EntityID)
	got, err = s.FindEntities(context.Background(), 7, "space", "pinned", "甲乙丙", 0)
	require.NoError(t, err)
	require.Len(t, got, 5)
}

func TestQueryMalformedPayloadFailsClosedAndReaderErrorsAreUnwrapped(t *testing.T) {
	for _, raw := range []string{
		`{`, `null`, `{"subject_ref":"E","predicate":"a","state":42}`,
		`{"subject_ref":"E","predicate":"a","state":"invalid"}`,
	} {
		s := queryService(release.Member{Kind: "claim", LogicalSlug: "bad", Payload: []byte(raw)})
		_, _, err := s.SearchFields(context.Background(), 7, "space", "pinned", "anything", "", 0)
		require.Error(t, err, raw)
	}
	boom := errors.New("reader failure")
	_, err := NewService(&queryReader{err: boom}).FindEntities(context.Background(), 7, "space", "pinned", "", 0)
	require.Same(t, boom, err)
}

func TestQuerySearchMatchesBrowserWhitespaceAndUnicodeLowercase(t *testing.T) {
	s := queryService(queryEntity("E", "产品"), queryClaim("field", "E", "ΟΣ", "present", "alpha beta"))
	got, _, err := s.SearchFields(context.Background(), 7, "space", "pinned", "ος\uFEFFalpha", "", 0)
	require.NoError(t, err)
	require.Equal(t, []string{"field"}, fieldSlugs(got), "a BOM is browser whitespace; lowercase is contextual Unicode")
	got, total, err := s.SearchFields(context.Background(), 7, "space", "pinned", "alpha\u0085beta", "", 0)
	require.NoError(t, err)
	require.Empty(t, got, "the browser does not split on NEL")
	require.Zero(t, total)
}

func TestQueryNavigationOtherGroupCannotReclaimEntries(t *testing.T) {
	navigation := queryMember("navigation", "nav", map[string]any{"domains": []any{
		map[string]any{"entity_types": []string{"product"}, "groups": []any{
			map[string]any{"group_key": "__other__", "classification_labels": []string{"other", "shared"}},
			map[string]any{"group_key": "main", "classification_labels": []string{"main", "shared"}},
		}},
	}})
	s := queryService(navigation,
		queryEntity("other", "其他", "other", "shared"), queryEntity("main", "主组", "main"),
		queryClaim("other/field", "other", "field", "present", "value"),
		queryClaim("main/field", "main", "field", "present", "value"))
	got, _, err := s.SearchFields(context.Background(), 7, "space", "pinned", "value", "", 0)
	require.NoError(t, err)
	require.Equal(t, []string{"main/field", "other/field"}, fieldSlugs(got))
}

func TestQueryEvidenceKeepsOrderAndDefaultSearchLimitCountsAll(t *testing.T) {
	members := []release.Member{queryEntity("E", "产品")}
	for index := 0; index < 23; index++ {
		members = append(members, queryMember("claim", string(rune('a'+index)), map[string]any{
			"subject_ref": "E", "predicate": "field", "state": "present", "value": "value",
			"origin": "EXPERT_CORRECTION", "review": map[string]string{"mode": "human"},
			"evidence": []any{
				map[string]any{
					"quote": "second page first", "source_ref": "source-two", "locator": map[string]int{"page": 2},
				},
				map[string]any{
					"quote": "first page second", "source_ref": "source-one", "locator": map[string]int{"page": 1},
				},
			},
		}))
	}
	got, total, err := queryService(members...).SearchFields(context.Background(), 7, "space", "pinned", "value", "", 0)
	require.NoError(t, err)
	require.Len(t, got, 20)
	require.Equal(t, 23, total)
	require.Equal(t, "EXPERT_CORRECTION", got[0].Origin)
	require.Equal(t, "human", got[0].Review)
	require.Equal(t, []Evidence{
		{Index: 0, Quote: "second page first", Page: 2, SourceRef: "source-two"},
		{Index: 1, Quote: "first page second", Page: 1, SourceRef: "source-one"},
	}, got[0].Evidence)
}
