// Q1b acceptance: read-only queries over one pinned release for chat tools (Spec
// docs/design/slices/Q1b-已发布知识问答.md §2). Protected file: written by Claude.
//
// The service is exercised with an in-memory Reader, so only its rules are covered: every read
// names the release (never Active); entities by id, name or shared character bigrams; fields
// with titles, states, values and evidence; S3h-1 field search; concepts by key or title; typed
// not-found errors; reader failures returned unchanged. Tool wiring, prompts and the UI are the
// implementer's tests. RED until Q1b implements the package. The QA1 RED commit only added the
// empty entity filter argument to SearchFields (QA1 Spec §3.1).
package knowledge_test

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
)

const (
	tenant = uint64(7)
	space  = "s1"
	pinned = "rel-3"
)

type read struct {
	tenant           uint64
	space, releaseID string
}

type reader struct {
	reads []read
	err   error
}

func (r *reader) ReleaseByID(_ context.Context, tenantID uint64, spaceID, releaseID string) (release.Release, error) {
	r.reads = append(r.reads, read{tenantID, spaceID, releaseID})
	if r.err != nil {
		return release.Release{}, r.err
	}
	if tenantID != tenant || spaceID != space || releaseID != pinned {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	return fixture(), nil
}

func member(kind, slug string, payload any) release.Member {
	raw, err := json.Marshal(payload)
	if err != nil {
		panic(err)
	}
	return release.Member{Kind: kind, LogicalSlug: slug, Payload: raw, MemberDigest: "d", AccessScope: "space"}
}

func claim(subject, predicate, state string, value any, evidence ...map[string]any) release.Member {
	payload := map[string]any{
		"subject_ref": subject, "predicate": predicate, "state": state, "value": value,
		"origin": "SOURCE_SUPPORTED", "review": map[string]any{"mode": "machine"}, "evidence": evidence,
	}
	return member("claim", subject+"/"+predicate, payload)
}

func entity(id string, labels []string, names ...string) release.Member {
	return member("entity", "entity/"+id, map[string]any{
		"entity_id": id, "entity_type": "product", "names": names, "classification_labels": labels,
	})
}

func profile(label string, keys ...[2]string) release.Member {
	fields := []map[string]any{}
	for _, key := range keys {
		fields = append(fields, map[string]any{"field_key": key[0], "short_title": key[1]})
	}
	return member("presentation_profile", "presentation/"+label, map[string]any{
		"profile_id": label, "display_name": label, "classification_labels": []string{label},
		"sections": []map[string]any{{"section_key": "main", "display_name": "main", "fields": fields}},
	})
}

// Entity members are listed with the critical-illness product first; navigation puts the
// medical group first, so navigation order and member order differ.
func fixture() release.Release {
	cooling, waiting, grace := [2]string{"cooling_off_period", "犹豫期"}, [2]string{"waiting_period", "等待期"},
		[2]string{"premium_grace_period", "宽限期"}
	return release.Release{ID: pinned, Epoch: 3, Members: []release.Member{
		member("navigation", "navigation/enterprise", map[string]any{
			"navigation_id": "enterprise", "navigation_version": "v1",
			"domains": []map[string]any{{
				"domain_key": "product", "display_name": "产品", "entity_types": []string{"product"},
				"groups": []map[string]any{
					{"group_key": "medical", "display_name": "医疗", "classification_labels": []string{"medical"}},
					{"group_key": "critical", "display_name": "重疾", "classification_labels": []string{"critical"}},
				},
			}},
		}),
		profile("medical", cooling, waiting, grace),
		profile("critical", cooling, waiting, grace),
		entity("1828", []string{"critical"}, "丙安佑福（全能版）重大疾病保险"),
		entity("M1", []string{"medical"}, "甲医疗保险（尊享版）", "甲医疗"),
		entity("M2", []string{"medical"}, "乙医疗保险"),
		claim("1828", "premium_grace_period", "absent_explicitly", nil),
		claim("1828", "waiting_period", "present", []string{"90日", "意外无等待期"}),
		claim("1828", "cooling_off_period", "present", "自签收之日起20日。", map[string]any{
			"quote": "自签收之日起20日内", "locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": 3},
			"source_ref": "source:v1:k1:1:abc",
		}),
		claim("M1", "cooling_off_period", "present", "15日"),
		claim("M1", "waiting_period", "unknown", nil),
		claim("M2", "cooling_off_period", "present", "15日"),
		member("concept", "concept/cooling_off_period", map[string]any{
			"concept_key": "cooling_off_period", "title": "犹豫期", "definition": "签收后可解除合同的期间。",
			"explanation": "解释。", "origin": "MODEL_GENERATED",
			"statements": []map[string]any{{"text": "甲医疗为15日。", "refs": []string{"M1/cooling_off_period"}}},
		}),
	}}
}

func service() (*knowledge.Service, *reader) {
	r := &reader{}
	return knowledge.NewService(r), r
}

func code(t *testing.T, err error) string {
	t.Helper()
	var failure *release.Error
	require.True(t, errors.As(err, &failure), "want *release.Error, got %v", err)
	return failure.Code
}

func ids(entities []knowledge.Entity) []string {
	out := []string{}
	for _, e := range entities {
		out = append(out, e.EntityID)
	}
	return out
}

func slugs(fields []knowledge.Field) []string {
	out := []string{}
	for _, f := range fields {
		out = append(out, f.Slug)
	}
	return out
}

func TestEveryReadNamesThePinnedRelease(t *testing.T) {
	s, r := service()
	ctx := context.Background()
	_, err := s.FindEntities(ctx, tenant, space, pinned, "安佑福", 0)
	require.NoError(t, err)
	_, err = s.EntityFields(ctx, tenant, space, pinned, "1828", nil)
	require.NoError(t, err)
	_, _, err = s.SearchFields(ctx, tenant, space, pinned, "日", "", 0)
	require.NoError(t, err)
	_, err = s.Concept(ctx, tenant, space, pinned, "犹豫期")
	require.NoError(t, err)
	require.NotEmpty(t, r.reads)
	for _, got := range r.reads {
		require.Equal(t, read{tenant, space, pinned}, got, "never Active, never another release")
	}
	_, err = s.FindEntities(ctx, tenant, space, "rel-other", "安佑福", 0)
	require.Equal(t, release.ErrorReleaseNotFound, code(t, err))
}

func TestFindEntitiesByIDNameAndSharedBigrams(t *testing.T) {
	s, _ := service()
	ctx := context.Background()
	find := func(query string, limit int) []string {
		got, err := s.FindEntities(ctx, tenant, space, pinned, query, limit)
		require.NoError(t, err)
		return ids(got)
	}
	require.Equal(t, []string{"1828"}, find("1828", 0))
	require.Equal(t, []string{"1828"}, find("安佑福", 0), "contained in a name")
	require.Equal(t, []string{"M1"}, find("甲医疗", 0), "an alias equals the query")
	require.Equal(t, []string{"M2"}, find("乙医疗的犹豫期是多久", 0), "two shared bigrams; M1 shares only one")
	require.Equal(t, []string{"M1", "M2"}, find("医疗保险", 0), "same tier keeps member order")
	require.Equal(t, []string{"M1"}, find("医疗保险", 1))
	require.Empty(t, find("  ", 0))
	got, err := s.FindEntities(ctx, tenant, space, pinned, "１８２８", 0)
	require.NoError(t, err)
	require.Equal(t, []string{"1828"}, ids(got), "NFKC")
	require.Equal(t, "丙安佑福（全能版）重大疾病保险", got[0].Name)
	require.Equal(t, []string{"critical"}, got[0].Labels)
}

func TestEntityFieldsCarryTitleStateValueAndEvidence(t *testing.T) {
	s, _ := service()
	ctx := context.Background()
	all, err := s.EntityFields(ctx, tenant, space, pinned, "1828", nil)
	require.NoError(t, err)
	require.Equal(t,
		[]string{"1828/cooling_off_period", "1828/waiting_period", "1828/premium_grace_period"},
		slugs(all), "profile field order")
	first := all[0]
	require.Equal(t, pinned, first.ReleaseID)
	require.Equal(t, "1828", first.EntityID)
	require.Equal(t, "丙安佑福（全能版）重大疾病保险", first.EntityName)
	require.Equal(t, "cooling_off_period", first.FieldKey)
	require.Equal(t, "犹豫期", first.FieldTitle)
	require.Equal(t, "present", first.State)
	require.Equal(t, "自签收之日起20日。", first.Value)
	require.Equal(t, "SOURCE_SUPPORTED", first.Origin)
	require.Equal(t, "machine", first.Review)
	require.Equal(t, []knowledge.Evidence{{Index: 0, Quote: "自签收之日起20日内", Page: 3, SourceRef: "source:v1:k1:1:abc"}},
		first.Evidence)
	require.Equal(t, "90日；意外无等待期", all[1].Value, "arrays joined")
	require.Equal(t, "absent_explicitly", all[2].State)
	require.Empty(t, all[2].Value)

	pick := func(names ...string) []string {
		got, err := s.EntityFields(ctx, tenant, space, pinned, "1828", names)
		require.NoError(t, err)
		return slugs(got)
	}
	require.Equal(t, []string{"1828/waiting_period"}, pick("等待期"), "by title")
	require.Equal(t, []string{"1828/premium_grace_period"}, pick("premium_grace_period"), "by predicate")
	require.Equal(t, []string{"1828/cooling_off_period"}, pick("犹豫期是多久"), "title bigrams inside the item")
	require.Empty(t, pick("不存在的字段"))

	unknown, err := s.EntityFields(ctx, tenant, space, pinned, "M1", []string{"等待期"})
	require.NoError(t, err)
	require.Equal(t, "unknown", unknown[0].State)

	_, err = s.EntityFields(ctx, tenant, space, pinned, "nope", nil)
	require.Equal(t, "ENTITY_NOT_FOUND", code(t, err))
}

func TestSearchFieldsFollowsTheS3h1Rules(t *testing.T) {
	s, _ := service()
	ctx := context.Background()
	got, total, err := s.SearchFields(ctx, tenant, space, pinned, "15日", "", 0)
	require.NoError(t, err)
	require.Equal(t, []string{"M1/cooling_off_period", "M2/cooling_off_period"}, slugs(got))
	require.Equal(t, 2, total)

	got, _, err = s.SearchFields(ctx, tenant, space, pinned, "犹豫期 20日", "", 0)
	require.NoError(t, err)
	require.Equal(t, []string{"1828/cooling_off_period"}, slugs(got), "every term, in title or value")

	got, total, err = s.SearchFields(ctx, tenant, space, pinned, "日", "", 0)
	require.NoError(t, err)
	require.Equal(t, []string{
		"M1/cooling_off_period", "M2/cooling_off_period", "1828/cooling_off_period", "1828/waiting_period",
	}, slugs(got), "navigation order, then profile order; absent and unknown are not searched")
	require.Equal(t, 4, total)

	got, total, err = s.SearchFields(ctx, tenant, space, pinned, "日", "", 1)
	require.NoError(t, err)
	require.Len(t, got, 1)
	require.Equal(t, 4, total)
}

func TestConceptByKeyOrTitle(t *testing.T) {
	s, _ := service()
	ctx := context.Background()
	for _, name := range []string{"cooling_off_period", "犹豫期"} {
		got, err := s.Concept(ctx, tenant, space, pinned, name)
		require.NoError(t, err)
		require.Equal(t, pinned, got.ReleaseID)
		require.Equal(t, "cooling_off_period", got.Key)
		require.Equal(t, "犹豫期", got.Title)
		require.Equal(t, "签收后可解除合同的期间。", got.Definition)
		require.Equal(t, "解释。", got.Explanation)
		require.Equal(t, []knowledge.Statement{{Text: "甲医疗为15日。", Refs: []string{"M1/cooling_off_period"}}},
			got.Statements)
	}
	_, err := s.Concept(ctx, tenant, space, pinned, "不存在")
	require.Equal(t, "CONCEPT_NOT_FOUND", code(t, err))
}

func TestReaderFailuresAreReturnedUnchanged(t *testing.T) {
	boom := errors.New("storage down")
	s := knowledge.NewService(&reader{err: boom})
	ctx := context.Background()
	_, err := s.FindEntities(ctx, tenant, space, pinned, "安佑福", 0)
	require.ErrorIs(t, err, boom)
	_, err = s.EntityFields(ctx, tenant, space, pinned, "1828", nil)
	require.ErrorIs(t, err, boom)
	_, _, err = s.SearchFields(ctx, tenant, space, pinned, "日", "", 0)
	require.ErrorIs(t, err, boom)
	_, err = s.Concept(ctx, tenant, space, pinned, "犹豫期")
	require.ErrorIs(t, err, boom)
}
