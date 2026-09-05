package tools

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"unicode/utf8"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

func managedTurn830G2() *interfaces.ConceptAgentTurn830G2 {
	return &interfaces.ConceptAgentTurn830G2{Releases: map[string]interfaces.ConceptAgentRelease830G2{
		"wiki-managed": {
			WikiKBID: "wiki-managed", SpaceID: "space-a", RawKBID: "raw-a",
			ReleaseID: "release-r1", ActivationEpoch: 7,
			Members: []interfaces.ConceptAgentMember830G2{{
				Kind: "free_wiki_item", MemberID: "free-promoted", OwnerID: "entity-a",
				Title: "Promoted rule", Content: "only-in-body waiting period is thirty days",
				MemberDigest: "member-digest-a",
				Sources: []interfaces.ConceptAgentSource830G2{{
					SourceType: "DOCUMENT", KnowledgeID: "knowledge-a", RevisionID: "revision-a",
					ParseAttempt: 2, BlockID: "block-a", PageNumber: 9,
					SourceHash: "source-hash-a", ParseHash: "parse-hash-a", QuoteHash: "quote-hash-a",
				}},
			}},
		},
	}}
}

func TestWikiReleaseSearch830G2UsesOnlyPinnedMembersAndReturnsAuthority(t *testing.T) {
	mutable := &fakeWikiPageService{searchResults: map[string][]*types.WikiPage{
		"wiki-managed": {{
			KnowledgeBaseID: "wiki-managed", Slug: "rejected-candidate",
			Title: "Rejected", Content: "rejected-only phrase",
		}},
	}}
	tool := NewWikiReleaseSearchTool830G2(
		mutable, nil, NewWikiScopesFromKBIDs([]string{"wiki-managed"}),
		NewWikiRouteResolver(), managedTurn830G2(),
	)

	result, err := tool.Execute(context.Background(), json.RawMessage(
		`{"queries":["waiting period is thirty days","rejected-only phrase"]}`,
	))
	require.NoError(t, err)
	require.True(t, result.Success)
	require.Contains(t, result.Output, "free-promoted")
	require.Contains(t, result.Output, "release-r1")
	require.Contains(t, result.Output, "activation_epoch=\"7\"")
	require.Contains(t, result.Output, "knowledge-a")
	require.Contains(t, result.Output, `count="0" query="rejected-only phrase"`)
	require.NotContains(t, result.Output, "rejected-candidate")
	require.Empty(t, mutable.searchCalls, "managed search must never touch mutable wiki_pages")
}

func TestWikiReleaseRead830G2KeepsTurnPinAfterHeadChanges(t *testing.T) {
	mutable := &fakeWikiPageService{pages: map[string]*types.WikiPage{
		wikiPageKey("wiki-managed", "free-promoted"): {
			KnowledgeBaseID: "wiki-managed", Slug: "free-promoted", Content: "mutable replacement",
		},
	}}
	turn := managedTurn830G2()
	tool := NewWikiReleaseReadPageTool830G2(
		mutable, nil, NewWikiScopesFromKBIDs([]string{"wiki-managed"}),
		NewWikiRouteResolver(), turn,
	)

	// A later Head observation belongs to the next turn. The current tools keep
	// the immutable release captured when this turn was created.
	next := turn.Releases["wiki-managed"]
	next.ReleaseID = "release-r2"
	next.ActivationEpoch = 8
	turn.Releases["wiki-managed"] = next

	result, err := tool.Execute(context.Background(), json.RawMessage(`{"slugs":["free-promoted"]}`))
	require.NoError(t, err)
	require.True(t, result.Success)
	require.Contains(t, result.Output, "release-r1")
	require.Contains(t, result.Output, "activation_epoch=\"7\"")
	require.Contains(t, result.Output, "only-in-body waiting period")
	require.NotContains(t, result.Output, "release-r2")
	require.NotContains(t, result.Output, "mutable replacement")
	require.Empty(t, mutable.getCalls, "managed read must never touch mutable wiki_pages")
}

func TestWikiReleaseTools830G2HonorDocumentScope(t *testing.T) {
	mutable := &fakeWikiPageService{}
	scopes := []WikiScope{{
		KnowledgeBaseID: "wiki-managed",
		KnowledgeIDs:    []string{"knowledge-other"},
	}}
	search := NewWikiReleaseSearchTool830G2(
		mutable, nil, scopes, NewWikiRouteResolver(), managedTurn830G2(),
	)

	searchResult, err := search.Execute(context.Background(), json.RawMessage(
		`{"queries":["waiting period is thirty days"]}`,
	))
	require.NoError(t, err)
	require.True(t, searchResult.Success)
	require.Contains(t, searchResult.Output, `count="0"`)
	require.NotContains(t, searchResult.Output, "free-promoted")

	read := NewWikiReleaseReadPageTool830G2(
		mutable, nil, scopes, NewWikiRouteResolver(), managedTurn830G2(),
	)
	readResult, err := read.Execute(context.Background(), json.RawMessage(`{"slugs":["free-promoted"]}`))
	require.NoError(t, err)
	require.False(t, readResult.Success)
	require.Empty(t, mutable.searchCalls)
	require.Empty(t, mutable.getCalls)
}

func TestWikiReleaseSearch830G2ReturnsValidUTF8Snippet(t *testing.T) {
	turn := managedTurn830G2()
	release := turn.Releases["wiki-managed"]
	release.Members[0].Content = strings.Repeat("前", 30) + "等待期三十天" + strings.Repeat("后", 60)
	turn.Releases["wiki-managed"] = release
	tool := NewWikiReleaseSearchTool830G2(
		&fakeWikiPageService{}, nil, NewWikiScopesFromKBIDs([]string{"wiki-managed"}),
		NewWikiRouteResolver(), turn,
	)

	result, err := tool.Execute(context.Background(), json.RawMessage(`{"queries":["等待期三十天"]}`))
	require.NoError(t, err)
	require.True(t, result.Success)
	require.True(t, utf8.ValidString(result.Output))
}
