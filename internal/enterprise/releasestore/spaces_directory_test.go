package releasestore

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestSpaceDirectorySortsAndIsolatesTenants(t *testing.T) {
	spaces, err := ParseSpaces(`[
{"tenant_id":7,"space_id":"zeta","raw_kb_id":"raw-z","wiki_kb_id":"wiki-z"},
{"tenant_id":8,"space_id":"other","raw_kb_id":"raw-o","wiki_kb_id":"wiki-o"},
{"tenant_id":7,"space_id":"alpha","raw_kb_id":"raw-a","wiki_kb_id":"wiki-a"}]`)
	require.NoError(t, err)
	ids := spaces.SpaceIDs(7)
	require.Equal(t, []string{"alpha", "zeta"}, ids)
	ids[0] = "changed"
	require.Equal(t, []string{"alpha", "zeta"}, spaces.SpaceIDs(7))
	require.Empty(t, spaces.SpaceIDs(0))
	require.Empty(t, spaces.SpaceIDs(9))
	raw, wiki, ok := spaces.KnowledgeBases(7, "alpha")
	require.True(t, ok)
	require.Equal(t, "raw-a", raw)
	require.Equal(t, "wiki-a", wiki)
	for _, id := range []string{"other", "unknown"} {
		raw, wiki, ok = spaces.KnowledgeBases(7, id)
		require.False(t, ok)
		require.Empty(t, raw)
		require.Empty(t, wiki)
	}
	_, _, ok = (Spaces{}).KnowledgeBases(7, "alpha")
	require.False(t, ok)
}
