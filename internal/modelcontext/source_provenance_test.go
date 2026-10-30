package modelcontext

import (
	"encoding/json"
	"testing"

	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func TestQ2bToolSourcesKeepExplicitProvenance(t *testing.T) {
	for _, tier := range []string{"release", "wiki_page", "raw_text"} {
		for _, asInterface := range []bool{false, true} {
			t.Run(tier+map[bool]string{false: "/strings", true: "/interface"}[asInterface], func(t *testing.T) {
				r := NewRegistry(true)
				var metadata any = map[string]string{"source_tier": tier, "release_id": "rel-pinned"}
				if asInterface {
					metadata = map[string]interface{}{"source_tier": tier, "release_id": "rel-pinned"}
				}
				output := r.ModelToolResultForTool("knowledge_search_fields", &types.ToolResult{
					Success: true, Data: map[string]interface{}{
						"display_type": "search_results", "results": []map[string]interface{}{{
							"chunk_id": "opaque-chunk", "knowledge_id": "doc-7f3a", "knowledge_base_id": "kb-91c2",
							"knowledge_title": "产品条款", "content": "事实", "metadata": metadata,
						}},
					},
				})
				require.Contains(t, output, `id="chunk://1"`)
				_, ref, ok := r.sources.chunks.resolve("chunk://1")
				require.True(t, ok)
				require.Equal(t, tier, ref.Metadata["source_tier"])
				require.Equal(t, "rel-pinned", ref.Metadata["release_id"])
				require.Equal(t, "doc-7f3a", ref.KnowledgeID)
				require.Equal(t, "kb-91c2", ref.KnowledgeBaseID)
				require.Equal(t, "产品条款", ref.DocumentTitle)
			})
		}
	}
}

func TestQ2bCitedReferencesFollowExpandedAnswerNotRetrievalOrder(t *testing.T) {
	r := NewRegistry(true)
	r.RegisterSearchResults([]*types.SearchResult{
		{
			ID: "release:old:entity/field", KnowledgeTitle: "字段",
			Metadata: map[string]string{
				"source_tier": "release", "release_id": "old", "space_id": "space-old",
				"logical_slug": "entity/field", "evidence_index": "0",
			},
		},
		{
			ID: "raw&quoted\"chunk", KnowledgeID: "doc", KnowledgeBaseID: "raw-kb", KnowledgeTitle: "条款",
			Metadata: map[string]string{"source_tier": "raw_text", "release_id": "old"},
		},
		{
			ID: "release:old:wiki/entity/page", Metadata: map[string]string{
				"source_tier": "wiki_page", "release_id": "old", "space_id": "space-old",
				"logical_slug": "wiki/entity/page", "evidence_index": "2",
			},
		},
		{ID: "release:looks-like-a-version:unlabelled"},
		{ID: "unused", Metadata: map[string]string{"source_tier": "raw_text", "release_id": "old"}},
	})
	answer := r.DecodeOutputText(`<ref id="c2"/>二<ref id="c1"/>再述<ref id="c2"/><ref id="c3"/><ref id="c4"/>`)
	refs := r.CitedKnowledgeReferences(answer)
	require.Len(t, refs, 4)
	require.Equal(t, "raw&quoted\"chunk", refs[0].ID)
	require.Contains(t, answer, `chunk_id="raw&amp;quoted&#34;chunk"`)
	require.Equal(t, "doc", refs[0].KnowledgeID)
	require.Equal(t, "raw-kb", refs[0].KnowledgeBaseID)
	require.Equal(t, "条款", refs[0].KnowledgeTitle)
	require.Equal(t, map[string]string{"source_tier": "raw_text", "release_id": "old"}, refs[0].Metadata)
	require.Equal(t, "release:old:entity/field", refs[1].ID)
	require.Equal(t, map[string]string{
		"source_tier": "release", "release_id": "old", "space_id": "space-old",
		"logical_slug": "entity/field", "evidence_index": "0",
	}, refs[1].Metadata)
	require.Equal(t, "release:old:wiki/entity/page", refs[2].ID)
	require.Equal(t, map[string]string{
		"source_tier": "wiki_page", "release_id": "old", "space_id": "space-old",
		"logical_slug": "wiki/entity/page", "evidence_index": "2",
	}, refs[2].Metadata)
	require.Equal(t, "release:looks-like-a-version:unlabelled", refs[3].ID)
	require.Empty(t, refs[3].Metadata, "unlabelled sources must not inherit an enterprise tier/version")
	encoded, err := json.Marshal(refs[1:3])
	require.NoError(t, err)
	t.Logf("Q2b citation consumer fixture: %s", encoded)
	refs[0].Metadata["release_id"] = "mutated"
	require.Equal(t, "old", r.CitedKnowledgeReferences(answer)[0].Metadata["release_id"])
	// Evidence from a completed request is not available to a new request.
	require.Empty(t, NewRegistry(true).CitedKnowledgeReferences(answer))
}

func TestQ2bCitedReferencesRejectNonEvidenceAndDisabledCitations(t *testing.T) {
	r := NewRegistry(true)
	r.RegisterContextChunk(ChunkReference{ChunkID: "directory"})
	r.EncodeMessages([]chat.Message{{Role: "assistant", Content: `<kb chunk_id="history" doc="old" />`}})
	r.RegisterWeb("https://example.com/source", "web")
	r.RegisterChunk(ChunkReference{ChunkID: "current"})
	for _, answer := range []string{
		"no citations", `<ref id="c3"/>`, `<kb chunk_id="directory" />`, `<kb chunk_id="history" />`,
		`<kb chunk_id="unknown" />`, r.DecodeOutputText(`<ref id="w1"/>`),
	} {
		require.Empty(t, r.CitedKnowledgeReferences(answer), answer)
	}
	disabled := NewRegistry(false)
	disabled.RegisterChunk(ChunkReference{ChunkID: "current"})
	require.Empty(t, disabled.CitedKnowledgeReferences(`<kb chunk_id="current" />`))
}

func TestQ2bSearchSourcesKeepProvenanceWithoutInferringFromID(t *testing.T) {
	r := NewRegistry(true)
	r.RegisterSearchResults([]*types.SearchResult{
		{ID: "opaque", Metadata: map[string]string{"source_tier": "raw_text", "release_id": "historical"}},
		{ID: "release:current:field"},
	})
	_, raw, ok := r.sources.chunks.resolve("chunk://1")
	require.True(t, ok)
	require.Equal(t, "raw_text", raw.Metadata["source_tier"])
	require.Equal(t, "historical", raw.Metadata["release_id"])
	_, unlabelled, ok := r.sources.chunks.resolve("chunk://2")
	require.True(t, ok)
	require.Empty(t, unlabelled.Metadata["source_tier"])
	require.Empty(t, unlabelled.Metadata["release_id"])
}

func TestQ2bSourceProvenanceStaysPairedWhenRegisteredAgain(t *testing.T) {
	r := NewRegistry(true)
	// A directory entry carries identity only. The first retrieved provenance
	// must then stay one pair, rather than assembling a tier/version from calls.
	r.RegisterContextChunk(ChunkReference{ChunkID: "chunk", Metadata: map[string]string{
		"source_tier": "wiki_page", "release_id": "history", "space_id": "old-space",
		"logical_slug": "wiki/old", "evidence_index": "7",
	}})
	metadata := map[string]string{"source_tier": "raw_text", "release_id": "pinned"}
	r.RegisterSearchResults([]*types.SearchResult{{
		ID: "chunk", Metadata: metadata,
	}})
	metadata["release_id"] = "mutated after registration"
	r.RegisterSearchResults([]*types.SearchResult{{
		ID: "chunk", Metadata: map[string]string{"source_tier": "wiki_page", "release_id": "other"},
	}})
	_, ref, ok := r.sources.chunks.resolve("chunk://1")
	require.True(t, ok)
	require.Equal(t, "raw_text", ref.Metadata["source_tier"])
	require.Equal(t, "pinned", ref.Metadata["release_id"])
	require.Equal(t, map[string]string{"source_tier": "raw_text", "release_id": "pinned"}, ref.Metadata)
}
