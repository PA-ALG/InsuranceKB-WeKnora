// QA1 acceptance added after review #371 round 3 (protected, written by Claude; Spec
// docs/design/slices/QA1-问答来源标注与范围说明.md §2.1): a page attributes its material only to
// entity_refs that resolve to a visible Entity member. The index's placeholder for a claim
// subject without one keeps naming that claim's own material, never a page's. Read through the
// production release reader, so a restricted Entity member is filtered by the Space read view.
// RED until the R2 residual fix lands.
package knowledge_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

type visibilityPublisher struct {
	release.Publisher
	value release.Release
}

func (p visibilityPublisher) ReleaseByID(context.Context, uint64, string, string) (release.Release, error) {
	return p.value, nil
}

type visibilityStore struct{ release.Store }

// crossRelease: visible entity A; a claim of subject Z citing claim-source; page wiki/A/overview
// referring to [A, Z] citing page-only; and entity Z absent, restricted or visible.
func crossRelease(z string) release.Release {
	members := []release.Member{
		entity("A", []string{"ga"}, "Product A"),
		claim("Z", "f", "present", "30日", cites("claimsrc", "30日")),
		member("wiki_page", "wiki/A/overview", map[string]any{
			"page_key": "overview", "entity_refs": []string{"A", "Z"}, "title": "概览",
			"page_type": "entity", "summary": "概览", "content": "概览", "origin": "MODEL_GENERATED",
			"evidence": []map[string]any{cites("pageonly", "概览")},
		}),
	}
	switch z {
	case "restricted":
		restricted := entity("Z", []string{"gz"}, "Product Z")
		restricted.AccessScope = "restricted"
		members = append(members, restricted)
	case "visible":
		members = append(members, entity("Z", []string{"gz"}, "Product Z"))
	}
	return release.Release{ID: "rel-v", Epoch: 1, Members: members}
}

func sourcesThroughSpaceView(t *testing.T, value release.Release) map[string][]string {
	t.Helper()
	service := release.NewService(visibilityStore{}, nil, nil, release.WithPublisher(visibilityPublisher{value: value}))
	ctx := context.WithValue(context.Background(), types.TenantIDContextKey, tenant)
	ctx = types.WithPrincipal(ctx, types.Principal{Type: types.PrincipalWebUser, ID: "reader"})
	got, err := knowledge.NewService(knowledge.NewReleaseReader(service)).SourceEntities(ctx, tenant, space, "rel-v")
	require.NoError(t, err)
	return got
}

func TestPageSourcesCountOnlyVisibleEntityMembers(t *testing.T) {
	for _, z := range []string{"absent", "restricted"} {
		t.Run(z, func(t *testing.T) {
			got := sourcesThroughSpaceView(t, crossRelease(z))
			require.Equal(t, []string{"Product A"}, got["pageonly"],
				"a claim placeholder never names a page's material")
			require.Equal(t, []string{"Z"}, got["claimsrc"], "the claim keeps its subject fallback")
		})
	}
	got := sourcesThroughSpaceView(t, crossRelease("visible"))
	require.Equal(t, []string{"Product A", "Product Z"}, got["pageonly"])
	require.Equal(t, []string{"Product Z"}, got["claimsrc"])
}
