package releasestore

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestPostgresMemberStoragePreservesAstralCombiningAndWhitespaceBytes(t *testing.T) {
	db := memberStorageDB(t)
	store := New(db, testSpaces(t))
	input := types.WikiReleaseMemberSnapshot{
		Kind: "page", LogicalSlug: "unicode/𐐀", RevisionID: "r/é",
		MemberDigest: strings.Repeat("a", 64),
		Title:        "é / 𐐀", Content: "原文\r\n𐐀 é \t", Payload: json.RawMessage(`{"text":"𐐀"}`),
	}
	repositoryStorageWrite(t, store.releases, mustStorageScope(t), "unicode", []types.WikiReleaseMemberSnapshot{input})
	fixtureReferenceReads(t, db)
	got, err := New(db, testSpaces(t)).releases.GetReleaseMembers(context.Background(), mustStorageScope(t), "rel-unicode")
	require.NoError(t, err)
	require.Len(t, got, 1)
	require.Equal(t, input.Kind, got[0].Kind)
	require.Equal(t, input.LogicalSlug, got[0].LogicalSlug)
	require.Equal(t, input.RevisionID, got[0].RevisionID)
	require.Equal(t, input.MemberDigest, got[0].MemberDigest)
	require.Equal(t, input.Title, got[0].Title)
	require.Equal(t, input.Content, got[0].Content)
	require.Equal(t, json.RawMessage(`{"text": "𐐀"}`), got[0].Payload)
}
