package service

import (
	"context"
	"encoding/json"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"testing"
)

type nativeIndexDocReader830G2 struct {
	result *types.ReadResult
	calls  int
}

func (d *nativeIndexDocReader830G2) Read(_ context.Context, _ *types.ReadRequest) (*types.ReadResult, error) {
	d.calls++
	return d.result, nil
}
func nativeIndexFixture830G2(t *testing.T) (*ConceptSourceAuthorityService830G2, *nativeIndexDocReader830G2, types.WikiReleaseScope, types.ConceptEvidence830G2, types.ConceptSourceBlock830G2) {
	t.Helper()
	result, parser := testNativeResult830G2(t)
	pdf := []byte("pdf")
	chunk := &types.Chunk{ID: "chunk-1", TenantID: 1, KnowledgeID: "knowledge-1", KnowledgeBaseID: "raw-1", Content: "prefix A😀 suffix", ChunkIndex: 0, ParseAttempt: 1}
	manifest, err := types.ComputeRevisionManifestDigest("knowledge-1", 1, []types.RevisionManifestChunk{{ID: chunk.ID, Index: 0, Content: chunk.Content}})
	require.NoError(t, err)
	count := 2
	source := &types.KnowledgeRevisionSource{TenantID: 1, KnowledgeID: "knowledge-1", ParseAttempt: 1, ResourceID: "resource-1", ResourceHandle: "resourcehandle12345678", FileSHA256: testSHA830G2("pdf"), ObjectSHA256: testSHA830G2("pdf"), Size: int64(len(pdf)), MimeType: "application/pdf", PageCount: &count, ManifestAlgorithm: types.RevisionManifestAlgorithm, ManifestDigest: manifest, ChunkCount: 1, ImmutableLocator: types.BuildResourcePath("resourcehandle12345678"), RetentionState: types.KnowledgeRevisionSourcePinned}
	source.RevisionSourceID, err = types.ComputeKnowledgeRevisionSourceID(*source)
	require.NoError(t, err)
	source.BindingDigest, err = types.ComputeKnowledgeRevisionSourceBindingDigest(*source)
	require.NoError(t, err)
	repo := &conceptKnowledgeStub830G2{knowledge: &types.Knowledge{ID: "knowledge-1", TenantID: 1, KnowledgeBaseID: "raw-1", FileType: "pdf", FileName: "source.pdf"}, revision: &types.KnowledgeRevision{KnowledgeID: "knowledge-1", ParseAttempt: 1, FileSHA256: source.FileSHA256, ManifestAlgorithm: types.RevisionManifestAlgorithm, ManifestDigest: manifest, ChunkCount: 1}, source: source, resource: &types.StoredResource{ID: "resource-1", TenantID: 1}}
	doc := &nativeIndexDocReader830G2{result: result}
	bridge := &ConceptSourceAuthorityService830G2{fixed: conceptFixedStub830G2{pdf: pdf}, knowledge: repo, revisions: repo, chunks: conceptChunksStub830G2{chunks: []*types.Chunk{chunk}}, docreader: doc}
	e := types.ConceptEvidence830G2{ConceptSourceIdentity830G2: types.ConceptSourceIdentity830G2{TenantID: 1, SpaceID: "space-1", RawKBID: "raw-1", KnowledgeID: "knowledge-1", ParseAttempt: 1, RevisionID: source.RevisionSourceID, SourceHash: source.FileSHA256, ParseHash: manifest, ParserIdentity: parser}, SourceType: "DOCUMENT", BlockID: chunk.ID, PageNumber: 1, OffsetUnit: "UNICODE_CODE_POINT", Start: 7, End: 9, Quote: "A😀", QuoteHash: testSHA830G2("A😀")}
	return bridge, doc, types.WikiReleaseScope{TenantID: 1, SpaceID: "space-1", RawKBID: "raw-1", WikiKBID: "wiki-1"}, e, types.ConceptSourceBlock830G2{ConceptSourceIdentity830G2: e.ConceptSourceIdentity830G2, BlockID: chunk.ID, PageNumber: 1, Text: chunk.Content, SourceType: "DOCUMENT"}
}
func TestConceptNativeIndex830G2SameRequestOwnsValidatedData(t *testing.T) {
	bridge, doc, scope, e, block := nativeIndexFixture830G2(t)
	cache := map[string]conceptNativeCaptureEntry830G2{}
	ctx := context.WithValue(context.Background(), conceptNativeCaptureCacheKey830G2{}, cache)
	_, first, err := bridge.verifyEvidence(ctx, scope, e, &block)
	require.NoError(t, err)
	require.Equal(t, 100000, first.X0)
	var preparedIndex *conceptNativeQuoteIndex830G2
	for _, entry := range cache {
		preparedIndex = entry.index
	}
	require.NotNil(t, preparedIndex)
	// A second quote must consume the request-owned validated snapshot, not
	// re-decode a mutable parser result alias. This also exposes repeated preparation.
	doc.result.NativeStructure.SanitizedJSON[0] = '!'
	doc.result.MarkdownContent = "mutated parser-owned result"
	e.Start = 8
	e.Quote = "😀"
	e.QuoteHash = testSHA830G2(e.Quote)
	_, second, err := bridge.verifyEvidence(ctx, scope, e, &block)
	require.NoError(t, err)
	require.Equal(t, 200000, second.X0)
	require.Equal(t, 1, doc.calls)
	require.Len(t, cache, 1)
	for _, entry := range cache {
		require.Same(t, preparedIndex, entry.index, "the second quote must reuse the already prepared index")
	}
	// The successful snapshot belongs only to the original request.
	fresh := context.WithValue(context.Background(), conceptNativeCaptureCacheKey830G2{}, map[string]conceptNativeCaptureEntry830G2{})
	_, _, err = bridge.verifyEvidence(fresh, scope, e, &block)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
	require.Equal(t, 2, doc.calls)
}
func TestConceptNativeIndex830G2FailedPreparationIsNotCached(t *testing.T) {
	bridge, doc, scope, e, block := nativeIndexFixture830G2(t)
	doc.result.NativeStructure.SanitizedJSON[0] = '!'
	cache := map[string]conceptNativeCaptureEntry830G2{}
	ctx := context.WithValue(context.Background(), conceptNativeCaptureCacheKey830G2{}, cache)
	_, _, err := bridge.verifyEvidence(ctx, scope, e, &block)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
	require.Empty(t, cache)
	doc.result, _ = testNativeResult830G2(t)
	_, _, err = bridge.verifyEvidence(ctx, scope, e, &block)
	require.NoError(t, err)
	require.Equal(t, 2, doc.calls)
}

func TestConceptNativeIndex830G2ChecksEveryQuoteAndIdentity(t *testing.T) {
	result, parser := testNativeResult830G2(t)
	source := testSHA830G2("pdf")
	index, err := prepareConceptNativeQuoteIndex830G2(result, source, parser)
	require.NoError(t, err)
	for _, tc := range []struct {
		name, source, parser, quote string
		page                        int
	}{
		{"missing quote", source, parser, "not present", 1}, {"missing page", source, parser, "A😀", 3},
		{"wrong source", testSHA830G2("other"), parser, "A😀", 1}, {"wrong parser", source, testSHA830G2("other"), "A😀", 1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, err := resolveConceptNativeQuoteInIndex830G2(index, tc.source, tc.parser, tc.page, tc.quote)
			require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
		})
	}
	for _, q := range []struct {
		page  int
		quote string
	}{{1, "A😀"}, {1, "😀"}, {2, "中"}} {
		original, err := resolveConceptNativeQuote830G2(result, source, parser, q.page, q.quote)
		require.NoError(t, err)
		cached, err := resolveConceptNativeQuoteInIndex830G2(index, source, parser, q.page, q.quote)
		require.NoError(t, err)
		require.Equal(t, original, cached)
	}
	_, err = prepareConceptNativeQuoteIndex830G2(result, testSHA830G2("other"), parser)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
	_, err = prepareConceptNativeQuoteIndex830G2(result, source, testSHA830G2("other"))
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
}

func TestConceptNativeIndex830G2CachedDuplicateQuoteStillRejected(t *testing.T) {
	result, parser := testNativeResult830G2(t)
	var projection conceptNativeProjection830G2
	require.NoError(t, json.Unmarshal(result.NativeStructure.SanitizedJSON, &projection))
	result.MarkdownContent = "AA\n\n中"
	projection.MarkdownSHA256 = testSHA830G2(result.MarkdownContent)
	projection.Pages[0].PageTextSHA256 = testSHA830G2("AA")
	raw, err := canonicalJSON830G2(projection)
	require.NoError(t, err)
	sha := testSHA256Bytes830G2(raw)
	result.NativeStructure.SanitizedJSON = raw
	result.NativeStructure.RawSHA256 = sha
	result.NativeStructure.SanitizedSHA256 = sha
	index, err := prepareConceptNativeQuoteIndex830G2(result, testSHA830G2("pdf"), parser)
	require.NoError(t, err)
	_, err = resolveConceptNativeQuoteInIndex830G2(index, testSHA830G2("pdf"), parser, 2, "中")
	require.NoError(t, err)
	_, err = resolveConceptNativeQuoteInIndex830G2(index, testSHA830G2("pdf"), parser, 1, "A")
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
	_, err = resolveConceptNativeQuoteInIndex830G2(index, testSHA830G2("pdf"), parser, 1, "AA")
	require.NoError(t, err)
	// Even a missing box on another page invalidates construction, never a partial index.
	projection.Pages[1].BBoxes = nil
	raw, err = canonicalJSON830G2(projection)
	require.NoError(t, err)
	sha = testSHA256Bytes830G2(raw)
	result.NativeStructure.SanitizedJSON = raw
	result.NativeStructure.RawSHA256 = sha
	result.NativeStructure.SanitizedSHA256 = sha
	rejected, err := prepareConceptNativeQuoteIndex830G2(result, testSHA830G2("pdf"), parser)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
	require.Nil(t, rejected)
}

func TestConceptNativeIndex830G2FirstQuoteFailureIsNotCached(t *testing.T) {
	bridge, doc, scope, e, block := nativeIndexFixture830G2(t)
	cache := map[string]conceptNativeCaptureEntry830G2{}
	ctx := context.WithValue(context.Background(), conceptNativeCaptureCacheKey830G2{}, cache)
	missing := e
	missing.Start = 0
	missing.End = 6
	missing.Quote = "prefix"
	missing.QuoteHash = testSHA830G2(missing.Quote)
	_, _, err := bridge.verifyEvidence(ctx, scope, missing, &block)
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
	require.Empty(t, cache)
	_, _, err = bridge.verifyEvidence(ctx, scope, e, &block)
	require.NoError(t, err)
	require.Equal(t, 2, doc.calls)
	require.Len(t, cache, 1)
}
