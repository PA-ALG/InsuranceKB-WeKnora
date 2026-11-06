package repository

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestSnapshotComparisonDoesNotReencodeIdenticalFinalBodies(t *testing.T) {
	input := make([]types.WikiReleaseMemberSnapshot, 32)
	for i := range input {
		input[i] = types.WikiReleaseMemberSnapshot{
			Kind:        "claim",
			LogicalSlug: "s", Content: strings.Repeat("x", 4096), Payload: json.RawMessage(`{"n":1}`),
		}
	}
	allocations := testing.AllocsPerRun(10, func() {
		if !wikiReleaseJSONLogicalEqualValue(input, input) {
			panic("same list differs")
		}
	})
	t.Logf("identical final snapshot allocations=%v", allocations)
	require.LessOrEqual(t, allocations, float64(4), "do not serialize and parse the already identical seven fields")
}

func TestSnapshotComparisonPreservesOriginalJSONSemantics(t *testing.T) {
	cases := []json.RawMessage{
		nil,
		{},
		[]byte(`null`), []byte(`{"n":1}`),
		[]byte(`{ "n":1 }`), []byte(`{"n":1.0}`), []byte(`{"n":"1"}`),
		[]byte(`{"n":9007199254740993}`), []byte(`invalid`),
	}
	for _, a := range cases {
		for _, b := range cases {
			x := []types.WikiReleaseMemberSnapshot{{Kind: "page", LogicalSlug: "s", Content: "text", Payload: a}}
			y := []types.WikiReleaseMemberSnapshot{{Kind: "page", LogicalSlug: "s", Content: "text", Payload: b}}
			rawX, errX := json.Marshal(x)
			rawY, errY := json.Marshal(y)
			expected := errX == nil && errY == nil && wikiReleaseJSONLogicalEqual(rawX, rawY)
			require.Equal(t, expected, wikiReleaseJSONLogicalEqualValue(x, y))
		}
	}
	base := []types.WikiReleaseMemberSnapshot{{
		Kind:        "page",
		LogicalSlug: "s", RevisionID: "r", MemberDigest: "d", Title: "t",
		Content: "c", Payload: []byte(`{}`),
	}}
	mutations := []func(*types.WikiReleaseMemberSnapshot){
		func(m *types.WikiReleaseMemberSnapshot) { m.Kind += "x" },
		func(m *types.WikiReleaseMemberSnapshot) { m.LogicalSlug += "x" },
		func(m *types.WikiReleaseMemberSnapshot) { m.RevisionID += "x" },
		func(m *types.WikiReleaseMemberSnapshot) { m.MemberDigest += "x" },
		func(m *types.WikiReleaseMemberSnapshot) { m.Title += "x" },
		func(m *types.WikiReleaseMemberSnapshot) { m.Content += "x" },
	}
	for _, mutate := range mutations {
		other := append([]types.WikiReleaseMemberSnapshot(nil), base...)
		mutate(&other[0])
		require.False(t, wikiReleaseJSONLogicalEqualValue(base, other))
	}
	require.False(t, wikiReleaseJSONLogicalEqualValue([]types.WikiReleaseMemberSnapshot(nil),
		[]types.WikiReleaseMemberSnapshot{}))
}
