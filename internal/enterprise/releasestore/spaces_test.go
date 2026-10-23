package releasestore

import (
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
)

func TestSpacesResolveConfiguredScopesOnly(t *testing.T) {
	spaces, err := ParseSpaces(`[{"tenant_id":7,"space_id":"s1","raw_kb_id":"raw1","wiki_kb_id":"wiki1"}]`)
	require.NoError(t, err)
	scope, err := spaces.Scope(7, "s1")
	require.NoError(t, err)
	require.Equal(t, types.WikiReleaseScope{TenantID: 7, SpaceID: "s1", RawKBID: "raw1", WikiKBID: "wiki1"}, scope)

	for _, probe := range []struct {
		tenant uint64
		space  string
	}{{8, "s1"}, {7, "s2"}} {
		_, err := spaces.Scope(probe.tenant, probe.space)
		var failure *release.Error
		require.ErrorAs(t, err, &failure)
		require.Equal(t, release.ErrorReleaseAccessDenied, failure.Code)
	}
}

func TestSpacesRejectIncompleteAndDuplicateEntries(t *testing.T) {
	for name, raw := range map[string]string{
		"not a list":    `{"tenant_id":7}`,
		"unknown field": `[{"tenant_id":7,"space_id":"s","raw_kb_id":"r","wiki_kb_id":"w","x":1}]`,
		"missing kb":    `[{"tenant_id":7,"space_id":"s","raw_kb_id":"r"}]`,
		"same kb twice": `[{"tenant_id":7,"space_id":"s","raw_kb_id":"k","wiki_kb_id":"k"}]`,
		"repeated space": `[{"tenant_id":7,"space_id":"s","raw_kb_id":"r","wiki_kb_id":"w"},
		                    {"tenant_id":7,"space_id":"s","raw_kb_id":"r2","wiki_kb_id":"w2"}]`,
		"shared wiki kb": `[{"tenant_id":7,"space_id":"a","raw_kb_id":"r","wiki_kb_id":"w"},
		                    {"tenant_id":7,"space_id":"b","raw_kb_id":"r2","wiki_kb_id":"w"}]`,
	} {
		t.Run(name, func(t *testing.T) {
			_, err := ParseSpaces(raw)
			require.Error(t, err)
		})
	}
	empty, err := ParseSpaces("  ")
	require.NoError(t, err)
	_, err = empty.Scope(7, "s")
	require.Error(t, err, "no configured Space means no enterprise publishing")
}
