// Q1b-2 acceptance: quick answers read published fields of the turn's pinned release (Spec
// docs/design/slices/Q1b-2-快问快答读取已发布字段.md §2.2). Protected file: written by Claude.
//
// A Wiki-only selection is answered once the published service is configured; the search
// endpoint keeps refusing it. Cited fields are put first in the prompt results exactly once per
// turn, and pinned references of another release are dropped. RED until Q1b-2.
package chatsource_test

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

type publishedReader struct{ reads int }

func publishedMember(kind, slug string, payload any) release.Member {
	raw, err := json.Marshal(payload)
	if err != nil {
		panic(err)
	}
	return release.Member{Kind: kind, LogicalSlug: slug, Payload: raw, MemberDigest: "d", AccessScope: "space"}
}

func (r *publishedReader) ReleaseByID(
	_ context.Context, tenantID uint64, spaceID, releaseID string,
) (release.Release, error) {
	r.reads++
	if tenantID != tenant || spaceID != "s1" || releaseID != "rel-1" {
		return release.Release{}, &release.Error{Code: release.ErrorReleaseNotFound}
	}
	claim := func(predicate, value string, evidence ...map[string]any) release.Member {
		return publishedMember("claim", "1828/"+predicate, map[string]any{
			"subject_ref": "1828", "predicate": predicate, "state": "present", "value": value,
			"origin": "SOURCE_SUPPORTED", "review": map[string]any{"mode": "machine"}, "evidence": evidence,
		})
	}
	return release.Release{ID: "rel-1", Epoch: 1, Members: []release.Member{
		publishedMember("entity", "entity/1828", map[string]any{
			"entity_id": "1828", "entity_type": "product", "names": []string{"丙安佑福（全能版）重大疾病保险"},
			"classification_labels": []string{"critical"},
		}),
		publishedMember("presentation_profile", "presentation/critical", map[string]any{
			"profile_id": "critical", "display_name": "critical", "classification_labels": []string{"critical"},
			"sections": []map[string]any{{"section_key": "main", "display_name": "main", "fields": []map[string]any{
				{"field_key": "cooling_off_period", "short_title": "犹豫期"},
				{"field_key": "waiting_period", "short_title": "等待期"},
			}}},
		}),
		claim("cooling_off_period", "20日", map[string]any{
			"quote": "自签收之日起20日内", "locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": 3},
			"source_ref": "source:v1:k1:1:abc",
		}),
		claim("waiting_period", "90日"), // no evidence: never a reviewed reference
	}}, nil
}

type noChunks struct{ t *testing.T }

func (c noChunks) ListChunksByID(context.Context, uint64, []string) ([]*types.Chunk, error) {
	c.t.Fatal("published results and unmanaged results need no chunk lookup")
	return nil, nil
}

func published() (*chatsource.Resolver, *publishedReader) {
	s, h, p, a := fixture()
	reader := &publishedReader{}
	return resolver(s, h, p, a).WithPublished(knowledge.NewService(reader)), reader
}

func TestQuickAnswerAcceptsAWikiOnlySelectionOnlyWithPublishedKnowledge(t *testing.T) {
	r, _ := published()
	ctx, targets, err := chatsource.ResolveAnswer(context.Background(), r, tenant, types.SearchTargets{kb("wiki-1")})
	require.NoError(t, err)
	require.Empty(t, targets)
	require.True(t, chatsource.HasPublished(ctx))

	_, _, err = chatsource.ResolveQuick(context.Background(), r, tenant, types.SearchTargets{kb("wiki-1")})
	require.Equal(t, "RELEASE_MANAGED_KB", code(t, err), "the search endpoint still refuses a Wiki-only selection")

	s, h, p, a := fixture()
	_, _, err = chatsource.ResolveAnswer(context.Background(), resolver(s, h, p, a), tenant,
		types.SearchTargets{kb("wiki-1")})
	require.Equal(t, "RELEASE_MANAGED_KB", code(t, err), "without the published service nothing changes")

	rawOnly, _, err := chatsource.ResolveAnswer(context.Background(), r, tenant, types.SearchTargets{kb("raw-1")})
	require.NoError(t, err)
	require.False(t, chatsource.HasPublished(rawOnly))
}

func TestFilterPipelinePutsCitedPublishedFieldsFirstOncePerTurn(t *testing.T) {
	r, reader := published()
	ctx, _, err := chatsource.ResolveAnswer(context.Background(), r, tenant, types.SearchTargets{kb("wiki-1")})
	require.NoError(t, err)
	stale := &types.SearchResult{ID: "release:rel-0:1828/cooling_off_period", Content: "old", Metadata: map[string]string{
		"source_tier": "release", "space_id": "s1", "release_id": "rel-0",
		"logical_slug": "1828/cooling_off_period", "evidence_index": "0",
	}}
	plain := &types.SearchResult{ID: "p1", KnowledgeBaseID: "plain", Content: "plain text"}
	cm := &types.ChatManage{}
	cm.Query = "那它的犹豫期和等待期呢"
	cm.RewriteQuery = "安佑福的犹豫期和等待期是多久"
	cm.MergeResult = []*types.SearchResult{stale, plain}

	require.NoError(t, chatsource.FilterPipeline(ctx, r, noChunks{t}, cm))
	ids := func() []string {
		out := []string{}
		for _, result := range cm.MergeResult {
			out = append(out, result.ID)
		}
		return out
	}
	require.Equal(t, []string{"release:rel-1:1828/cooling_off_period", "p1"}, ids())
	hit := cm.MergeResult[0]
	require.Equal(t, map[string]string{
		"source_tier": "release", "space_id": "s1", "release_id": "rel-1",
		"logical_slug": "1828/cooling_off_period", "evidence_index": "0",
	}, hit.Metadata)
	require.Equal(t, "丙安佑福（全能版）重大疾病保险 · 犹豫期", hit.KnowledgeTitle)
	require.Contains(t, hit.Content, "自签收之日起20日内")
	require.Empty(t, hit.KnowledgeBaseID)
	require.Empty(t, hit.KnowledgeID)
	require.Equal(t, 1.0, hit.Score)

	require.NoError(t, chatsource.FilterPipeline(ctx, r, noChunks{t}, cm))
	require.Equal(t, []string{"release:rel-1:1828/cooling_off_period", "p1"}, ids(),
		"the second pass changes nothing")
	require.Equal(t, 1, reader.reads, "published fields are read once per turn")
}

func TestPublishedFieldsWaitForAnIntentThatRetrieves(t *testing.T) {
	r, reader := published()
	ctx, _, err := chatsource.ResolveAnswer(context.Background(), r, tenant, types.SearchTargets{kb("wiki-1")})
	require.NoError(t, err)
	cm := &types.ChatManage{}
	cm.Query = "安佑福的犹豫期"
	cm.Intent = types.IntentChitchat
	require.NoError(t, chatsource.FilterPipeline(ctx, r, noChunks{t}, cm))
	require.Empty(t, cm.MergeResult)
	require.Zero(t, reader.reads)
}
