// Q1a acceptance: one chat turn's search scope over enterprise Spaces (Spec
// docs/design/slices/Q1-问答接入发布版本.md §2.1). Protected file: written by Claude.
//
// The resolver is exercised with in-memory Spaces, Heads, Pins and Attempts, so only its rules are
// covered here: unmanaged targets pass through; a Space's raw-material KB is narrowed to the
// materials pinned by the Space's Active release whose current parse attempt is the pinned one; a
// Space's wiki KB is recorded, not searched; one release per Space per turn; failures stay closed;
// only searchable pinned materials are labelled. Wiring into quick QA, Agent mode and the UI is the
// implementer's tests. RED until Q1a implements the package.
package chatsource_test

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

const tenant = uint64(7)

type spaces map[string]struct {
	space string
	role  chatsource.Role
}

func (s spaces) SpaceOf(tenantID uint64, kbID string) (string, chatsource.Role, bool) {
	if tenantID != tenant {
		return "", "", false
	}
	entry, ok := s[kbID]
	return entry.space, entry.role, ok
}

type heads struct {
	active map[string]string
	reads  map[string]int
	err    error
}

func (h *heads) ActiveRelease(_ context.Context, tenantID uint64, spaceID string) (string, error) {
	if h.reads == nil {
		h.reads = map[string]int{}
	}
	h.reads[spaceID]++
	if h.err != nil {
		return "", h.err
	}
	if tenantID != tenant {
		return "", nil
	}
	return h.active[spaceID], nil
}

type pins struct {
	byRelease map[string][]chatsource.Pin
	err       error
}

func (p pins) ReleaseSources(_ context.Context, tenantID uint64, spaceID, releaseID string) ([]chatsource.Pin, error) {
	if p.err != nil {
		return nil, p.err
	}
	if tenantID != tenant {
		return nil, nil
	}
	return p.byRelease[spaceID+"/"+releaseID], nil
}

type attempts struct {
	current map[string]int64
	err     error
}

func (a attempts) CurrentAttempts(_ context.Context, tenantID uint64, ids []string) (map[string]int64, error) {
	if a.err != nil {
		return nil, a.err
	}
	out := map[string]int64{}
	for _, id := range ids {
		if attempt, ok := a.current[id]; ok && tenantID == tenant {
			out[id] = attempt
		}
	}
	return out, nil
}

// fixture: Space "s1" with raw KB "raw-1" and wiki KB "wiki-1", active release "rel-1" pinning
// k1@2, k2@1 and k3@1; k3 has since been reparsed (attempt 2), so it is not searchable.
func fixture() (spaces, *heads, pins, attempts) {
	return spaces{
			"raw-1":  {"s1", chatsource.Role("raw")},
			"wiki-1": {"s1", chatsource.Role("wiki")},
			"raw-2":  {"s2", chatsource.Role("raw")},
		},
		&heads{active: map[string]string{"s1": "rel-1", "s2": "rel-2"}},
		pins{byRelease: map[string][]chatsource.Pin{
			"s1/rel-1": {
				{KnowledgeID: "k2", ParseAttempt: 1},
				{KnowledgeID: "k1", ParseAttempt: 2},
				{KnowledgeID: "k3", ParseAttempt: 1},
			},
			"s2/rel-2": {{KnowledgeID: "k9", ParseAttempt: 1}},
		}},
		attempts{current: map[string]int64{"k1": 2, "k2": 1, "k3": 2, "k9": 1}}
}

func resolver(s spaces, h *heads, p pins, a attempts) *chatsource.Resolver {
	return chatsource.NewResolver(s, h, p, a)
}

func kb(id string) *types.SearchTarget {
	return &types.SearchTarget{Type: types.SearchTargetTypeKnowledgeBase, KnowledgeBaseID: id, TenantID: tenant}
}

func code(t *testing.T, err error) string {
	t.Helper()
	var failure *release.Error
	require.True(t, errors.As(err, &failure), "want *release.Error, got %v", err)
	return failure.Code
}

func TestUnmanagedTargetsPassThroughUnchanged(t *testing.T) {
	s, h, p, a := fixture()
	plain := kb("plain")
	turn, err := resolver(s, h, p, a).Resolve(context.Background(), tenant, types.SearchTargets{plain})
	require.NoError(t, err)
	require.Equal(t, types.SearchTargets{plain}, turn.Targets)
	require.Empty(t, turn.Releases)
	require.Empty(t, turn.WikiSpaces)
	require.Empty(t, turn.RawKnowledge)
	require.Empty(t, h.reads, "no Active read without an enterprise Space in scope")
}

func TestRawKBIsNarrowedToSearchablePinnedMaterials(t *testing.T) {
	s, h, p, a := fixture()
	raw := kb("raw-1")
	raw.TagIDs = []string{"tag-a"}
	raw.ScopeTagIDs = []string{"tag-a"}
	turn, err := resolver(s, h, p, a).Resolve(context.Background(), tenant, types.SearchTargets{kb("plain"), raw})
	require.NoError(t, err)
	require.Len(t, turn.Targets, 2)
	require.Equal(t, "plain", turn.Targets[0].KnowledgeBaseID, "order is kept")
	got := turn.Targets[1]
	require.Equal(t, types.SearchTargetTypeKnowledge, got.Type)
	require.Equal(t, "raw-1", got.KnowledgeBaseID)
	require.Equal(t, tenant, got.TenantID)
	require.Equal(t, []string{"k1", "k2"}, got.KnowledgeIDs, "k3 was reparsed after pinning; ids sorted")
	require.Equal(t, []string{"tag-a"}, got.TagIDs)
	require.Equal(t, []string{"tag-a"}, got.ScopeTagIDs)
	require.Equal(t, map[string]string{"s1": "rel-1"}, turn.Releases)
	require.Equal(t, map[string]string{"k1": "s1", "k2": "s1"}, turn.RawKnowledge)
}

func TestKnowledgeLevelRawTargetIsIntersectedWithPins(t *testing.T) {
	s, h, p, a := fixture()
	chosen := &types.SearchTarget{
		Type: types.SearchTargetTypeKnowledge, KnowledgeBaseID: "raw-1", TenantID: tenant,
		KnowledgeIDs: []string{"k2", "k3", "k-unpinned"}, DisableRecallThresholds: true,
	}
	turn, err := resolver(s, h, p, a).Resolve(context.Background(), tenant, types.SearchTargets{chosen})
	require.NoError(t, err)
	require.Len(t, turn.Targets, 1)
	require.Equal(t, []string{"k2"}, turn.Targets[0].KnowledgeIDs)
	require.True(t, turn.Targets[0].DisableRecallThresholds)
	require.Equal(t, map[string]string{"k2": "s1"}, turn.RawKnowledge)

	none := &types.SearchTarget{
		Type: types.SearchTargetTypeKnowledge, KnowledgeBaseID: "raw-1", TenantID: tenant,
		KnowledgeIDs: []string{"k3", "k-unpinned"},
	}
	_, err = resolver(s, h, p, a).Resolve(context.Background(), tenant, types.SearchTargets{none})
	require.Equal(t, "RELEASE_SOURCES_UNAVAILABLE", code(t, err))
}

func TestNoSearchablePinnedMaterialFailsClosed(t *testing.T) {
	s, h, p, a := fixture()
	a.current["k1"], a.current["k2"] = 3, 3
	_, err := resolver(s, h, p, a).Resolve(context.Background(), tenant, types.SearchTargets{kb("raw-1")})
	require.Equal(t, "RELEASE_SOURCES_UNAVAILABLE", code(t, err))
}

func TestSpaceWithoutActiveReleaseIsNotFound(t *testing.T) {
	s, h, p, a := fixture()
	delete(h.active, "s1")
	for _, target := range []*types.SearchTarget{kb("raw-1"), kb("wiki-1")} {
		_, err := resolver(s, h, p, a).Resolve(context.Background(), tenant, types.SearchTargets{target})
		require.Equal(t, "RELEASE_NOT_FOUND", code(t, err))
	}
}

func TestDependencyFailuresAreReturnedNotWidened(t *testing.T) {
	boom := errors.New("storage down")
	s, h, p, a := fixture()
	h.err = boom
	turn, err := resolver(s, h, p, a).Resolve(context.Background(), tenant, types.SearchTargets{kb("raw-1")})
	require.ErrorIs(t, err, boom)
	require.Empty(t, turn.Targets, "never fall back to the whole raw KB")

	s, h, p, a = fixture()
	p.err = boom
	_, err = resolver(s, h, p, a).Resolve(context.Background(), tenant, types.SearchTargets{kb("raw-1")})
	require.ErrorIs(t, err, boom)

	s, h, p, a = fixture()
	a.err = boom
	_, err = resolver(s, h, p, a).Resolve(context.Background(), tenant, types.SearchTargets{kb("raw-1")})
	require.ErrorIs(t, err, boom)
}

func TestWikiKBIsRecordedNotSearched(t *testing.T) {
	s, h, p, a := fixture()
	turn, err := resolver(s, h, p, a).Resolve(context.Background(), tenant,
		types.SearchTargets{kb("wiki-1"), kb("plain")})
	require.NoError(t, err)
	require.Len(t, turn.Targets, 1)
	require.Equal(t, "plain", turn.Targets[0].KnowledgeBaseID)
	require.Equal(t, []string{"s1"}, turn.WikiSpaces)
	require.Equal(t, map[string]string{"s1": "rel-1"}, turn.Releases)
	require.Empty(t, turn.RawKnowledge)
}

func TestBothKBsOfOneSpaceShareOneReleaseReadOnce(t *testing.T) {
	s, h, p, a := fixture()
	turn, err := resolver(s, h, p, a).Resolve(context.Background(), tenant,
		types.SearchTargets{kb("wiki-1"), kb("raw-1"), kb("raw-2")})
	require.NoError(t, err)
	require.Equal(t, map[string]string{"s1": "rel-1", "s2": "rel-2"}, turn.Releases)
	require.Equal(t, 1, h.reads["s1"], "one Active read per Space per turn")
	require.Equal(t, []string{"s1"}, turn.WikiSpaces)
	require.Len(t, turn.Targets, 2)
	require.Equal(t, map[string]string{"k1": "s1", "k2": "s1", "k9": "s2"}, turn.RawKnowledge)
}

func TestLabelMarksOnlySearchablePinnedMaterials(t *testing.T) {
	s, h, p, a := fixture()
	turn, err := resolver(s, h, p, a).Resolve(context.Background(), tenant,
		types.SearchTargets{kb("raw-1"), kb("plain")})
	require.NoError(t, err)
	pinned := &types.SearchResult{ID: "c1", KnowledgeID: "k1"}
	withMeta := &types.SearchResult{ID: "c2", KnowledgeID: "k2", Metadata: map[string]string{"keep": "yes"}}
	other := &types.SearchResult{ID: "c3", KnowledgeID: "k-plain"}
	turn.Label([]*types.SearchResult{pinned, withMeta, other})
	require.Equal(t, map[string]string{"source_tier": "raw_text", "release_id": "rel-1"}, pinned.Metadata)
	require.Equal(t, map[string]string{"keep": "yes", "source_tier": "raw_text", "release_id": "rel-1"},
		withMeta.Metadata)
	require.Nil(t, other.Metadata)
}
