package types

import (
	"crypto/sha256"
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestKnowledgeRevisionManifestDigestVectors(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name        string
		knowledgeID string
		attempt     int64
		chunks      []RevisionManifestChunk
		want        string
	}{
		{
			name:        "empty manifest",
			knowledgeID: "knowledge-1",
			attempt:     1,
			want:        "fd8e544836902f50b643a2dd85236c36b8b31224382366afca33f4ba74e5addb",
		},
		{
			name:        "utf8 and non-contiguous indexes preserve stored bytes",
			knowledgeID: "knowledge-utf8",
			attempt:     7,
			chunks: []RevisionManifestChunk{
				{ID: "chunk-a", Index: 0, Content: "你好\n"},
				{ID: "chunk-b", Index: 2, Content: "line1\r\nline2"},
			},
			want: "11f591d4113b3ef2e4cc933cb8648edb26b394cc0cb6b0e4b20150126da7cbcb",
		},
	}

	for _, tt := range tests {
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			got, err := ComputeRevisionManifestDigest(tt.knowledgeID, tt.attempt, tt.chunks)
			require.NoError(t, err)
			require.Equal(t, tt.want, got)
		})
	}
}

func TestKnowledgeRevisionManifestDigestRejectsAmbiguousInput(t *testing.T) {
	t.Parallel()

	_, err := ComputeRevisionManifestDigest("knowledge-1", 0, nil)
	require.ErrorIs(t, err, ErrInvalidRevisionManifest)

	_, err = ComputeRevisionManifestDigest("knowledge-1", 3, []RevisionManifestChunk{
		{ID: "chunk-b", Index: 1, Content: "second"},
		{ID: "chunk-a", Index: 0, Content: "first"},
	})
	require.ErrorIs(t, err, ErrInvalidRevisionManifest)

	_, err = ComputeRevisionManifestDigest("knowledge-1", 3, []RevisionManifestChunk{
		{ID: "chunk-a", Index: 0, Content: "first"},
		{ID: "chunk-b", Index: 0, Content: "second"},
	})
	require.ErrorIs(t, err, ErrInvalidRevisionManifest)

	require.True(t, errors.Is(err, ErrInvalidRevisionManifest))
}

func TestRevisionParserIdentityNormalizeUsesExplicitUnknowns(t *testing.T) {
	t.Parallel()

	got := (RevisionParserIdentity{}).Normalized()
	require.Equal(t, RevisionUnknownIdentity, got.AppVersion)
	require.Equal(t, RevisionUnknownIdentity, got.AppCommit)
	require.Equal(t, RevisionUnknownIdentity, got.DocReader)
	require.Equal(t, RevisionUnknownIdentity, got.ParserEngine)
	require.Equal(t, RevisionUnknownIdentity, got.EmbeddingModelID)
	require.NotEmpty(t, got.ChunkerConfigDigest)
}

func TestRevisionCommitBindingRejectsUppercaseFileDigest(t *testing.T) {
	t.Parallel()
	binding := RevisionCommitBinding{
		ParseAttempt: 1,
		FileSHA256:   strings.Repeat("A", sha256.Size*2),
	}
	require.False(t, binding.Valid())
}

func TestRevisionFieldsRemainVisibleAtLegacyZeroValues(t *testing.T) {
	knowledgeJSON, err := json.Marshal(Knowledge{})
	require.NoError(t, err)
	require.Contains(t, string(knowledgeJSON), `"current_parse_attempt":0`)
	require.Contains(t, string(knowledgeJSON), `"file_sha256":""`)

	chunkJSON, err := json.Marshal(Chunk{})
	require.NoError(t, err)
	require.Contains(t, string(chunkJSON), `"parse_attempt":0`)
}

func TestKnowledgeRevisionSourceBindingDigestClosesAttemptObjectAndManifest(t *testing.T) {
	t.Parallel()
	pageCount := 39
	source := KnowledgeRevisionSource{
		TenantID: 10003, KnowledgeID: "knowledge-596-1", ParseAttempt: 2,
		RevisionSourceID: strings.Repeat("a", 64), ResourceID: "resource-596-1",
		ResourceHandle: "resourceHandle5961AAA", ImmutableLocator: "resource://resourceHandle5961AAA",
		FileSHA256: strings.Repeat("b", 64), ObjectSHA256: strings.Repeat("b", 64),
		Size: 4096, MimeType: "application/pdf", PageCount: &pageCount,
		ManifestAlgorithm: RevisionManifestAlgorithm, ManifestDigest: strings.Repeat("c", 64),
		ChunkCount: 162, RetentionState: KnowledgeRevisionSourcePinned,
	}
	digest, err := ComputeKnowledgeRevisionSourceBindingDigest(source)
	require.NoError(t, err)
	require.Len(t, digest, 64)
	source.BindingDigest = digest
	require.NoError(t, ValidateKnowledgeRevisionSourceBinding(source))

	mutations := map[string]func(*KnowledgeRevisionSource){
		"tenant":            func(v *KnowledgeRevisionSource) { v.TenantID++ },
		"attempt":           func(v *KnowledgeRevisionSource) { v.ParseAttempt++ },
		"resource handle":   func(v *KnowledgeRevisionSource) { v.ResourceHandle = "foreignHandle5961AAA" },
		"immutable locator": func(v *KnowledgeRevisionSource) { v.ImmutableLocator = "resource://foreignHandle5961AAA" },
		"object digest":     func(v *KnowledgeRevisionSource) { v.ObjectSHA256 = strings.Repeat("d", 64) },
		"page count":        func(v *KnowledgeRevisionSource) { changed := 40; v.PageCount = &changed },
		"manifest":          func(v *KnowledgeRevisionSource) { v.ManifestDigest = strings.Repeat("e", 64) },
		"chunk count":       func(v *KnowledgeRevisionSource) { v.ChunkCount++ },
		"retention":         func(v *KnowledgeRevisionSource) { v.RetentionState = KnowledgeRevisionSourceReleased },
	}
	for name, mutate := range mutations {
		t.Run(name, func(t *testing.T) {
			changed := source
			mutate(&changed)
			require.ErrorIs(t, ValidateKnowledgeRevisionSourceBinding(changed), ErrInvalidRevisionManifest)
		})
	}
}

func TestKnowledgeRevisionSourceBindingRejectsUnsealedOrNonPDFAuthority(t *testing.T) {
	t.Parallel()
	source := KnowledgeRevisionSource{
		TenantID: 1, KnowledgeID: "knowledge-1", ParseAttempt: 1,
		RevisionSourceID: strings.Repeat("a", 64), ResourceID: "resource-1",
		FileSHA256: strings.Repeat("b", 64), Size: 1024, MimeType: "application/pdf",
		RetentionState: KnowledgeRevisionSourcePinned,
	}
	_, err := ComputeKnowledgeRevisionSourceBindingDigest(source)
	require.ErrorIs(t, err, ErrInvalidRevisionManifest)

	pageCount := 1
	source.ResourceHandle = "resourceHandle0000001"
	source.ImmutableLocator = "resource://resourceHandle0000001"
	source.ObjectSHA256 = source.FileSHA256
	source.PageCount = &pageCount
	source.ManifestAlgorithm = RevisionManifestAlgorithm
	source.ManifestDigest = strings.Repeat("c", 64)
	source.ChunkCount = 1
	source.MimeType = "text/plain"
	_, err = ComputeKnowledgeRevisionSourceBindingDigest(source)
	require.ErrorIs(t, err, ErrInvalidRevisionManifest)
}
