package service

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/infrastructure/chunker"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/hibiken/asynq"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"unicode"

	"github.com/stretchr/testify/require"
)

func TestG3FirstParseSnapshotMissingArtifactNeverReparses(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	authority, doc, scope, _, _ := nativeIndexFixture830G2(t)
	authority.codec = sourceReuseTestCodec830G3(t)
	authority.sourceReuse = newConceptSourceReuseStore830G3(authority.codec)
	readySourceReuseResource830G3(authority)
	repository := authority.revisions.(*conceptKnowledgeStub830G2)
	_, err := authority.captureG3PlatformSource830G3(context.Background(), scope, repository.source)
	require.Error(t, err, "a G3 snapshot requires its first parse artifact, not a second parse")
	require.Zero(t, doc.calls)
}

func firstParseNative(t *testing.T, pages ...string) *types.ReadResult {
	t.Helper()
	base, _ := testNativeResult830G2(t)
	var p conceptNativeProjection830G2
	require.NoError(t, json.Unmarshal(base.NativeStructure.SanitizedJSON, &p))
	p.Pages = nil
	markdown := strings.Join(pages, "\n\n")
	p.MarkdownSHA256 = testSHA256830G2(markdown)
	offset := 0
	for n, text := range pages {
		runes := []rune(text)
		page := conceptNativePage830G2{PageNumber: n + 1, GlobalCodepointStart: offset, GlobalCodepointEnd: offset + len(runes), PageTextSHA256: testSHA256830G2(text), WidthPoints: "100", HeightPoints: "200", BBoxes: []conceptNativeBBox830G2{}}
		for i, r := range runes {
			if !unicode.IsSpace(r) {
				page.BBoxes = append(page.BBoxes, conceptNativeBBox830G2{GlobalCodepointStart: offset + i, GlobalCodepointEnd: offset + i + 1, BBox: [4]int{100000, 100000, 200000, 200000}})
			}
		}
		p.Pages = append(p.Pages, page)
		offset += len(runes) + 2
	}
	data, err := canonicalJSON830G2(p)
	require.NoError(t, err)
	digest := testSHA256Bytes830G2(data)
	return &types.ReadResult{MarkdownContent: markdown, NativeStructure: &types.NativeStructureArtifact{SchemaVersion: p.Contract, SourceSHA256: p.SourceSHA256, RawSHA256: digest, SanitizedSHA256: digest, SanitizedJSON: data}}
}
func seedFirstParseSnapshot(t *testing.T, authority *ConceptSourceAuthorityService830G2, scope types.WikiReleaseScope, result *types.ReadResult, chunks []types.ParsedChunk) {
	t.Helper()
	repo := authority.revisions.(*conceptKnowledgeStub830G2)
	manifest := []types.RevisionManifestChunk{}
	rows := []*types.Chunk{}
	for i, c := range chunks {
		id := fmt.Sprintf("chunk-%d", i+1)
		rows = append(rows, &types.Chunk{ID: id, TenantID: scope.TenantID, KnowledgeID: repo.source.KnowledgeID, KnowledgeBaseID: scope.RawKBID, ParseAttempt: repo.source.ParseAttempt, ChunkIndex: c.Seq, Content: c.Content})
		manifest = append(manifest, types.RevisionManifestChunk{ID: id, Index: c.Seq, Content: c.Content})
	}
	digest, err := types.ComputeRevisionManifestDigest(repo.source.KnowledgeID, repo.source.ParseAttempt, manifest)
	require.NoError(t, err)
	repo.revision.ManifestDigest = digest
	repo.revision.ChunkCount = len(rows)
	repo.source.ManifestDigest = digest
	repo.source.ChunkCount = len(rows)
	repo.source.RevisionSourceID, err = types.ComputeKnowledgeRevisionSourceID(*repo.source)
	require.NoError(t, err)
	repo.source.BindingDigest, err = types.ComputeKnowledgeRevisionSourceBindingDigest(*repo.source)
	require.NoError(t, err)
	authority.chunks = conceptChunksStub830G2{chunks: rows}
	require.NoError(t, (&G3FirstParseStore{reuse: authority.sourceReuse}).save(g3FirstParseIdentityForSource(scope, repo.source), result, chunks))
}
func TestG3FirstParseCRLFRestartSnapshotAndTamperedArtifact(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	authority, doc, scope, _, _ := nativeIndexFixture830G2(t)
	authority.codec = sourceReuseTestCodec830G3(t)
	authority.sourceReuse = newConceptSourceReuseStore830G3(authority.codec)
	readySourceReuseResource830G3(authority)
	result := firstParseNative(t, "平安测试（2026）两全保险\r\n保险条款\r\n", "重复文字\r\n")
	chunks := []types.ParsedChunk{{Seq: 0, Content: result.MarkdownContent, Start: 0, End: len([]rune(result.MarkdownContent))}}
	seedFirstParseSnapshot(t, authority, scope, result, chunks)
	repo := authority.revisions.(*conceptKnowledgeStub830G2)
	first, err := authority.captureG3PlatformSource830G3(context.Background(), scope, repo.source)
	require.NoError(t, err)
	require.Equal(t, result.MarkdownContent, first.record.Markdown)
	mapping := g3PlatformChunkPageMapping(first.record.Chunks[0], first.index, first.record.ChunkRanges)
	require.Equal(t, G3PlatformChunkMappingExactBlock, mapping.Status)
	require.Len(t, mapping.PageSpans, 2)
	require.Equal(t, 1, *mapping.SourcePageNumber)
	// A process restart has only signed files; the parser must not be consulted.
	authority.sourceReuse = newConceptSourceReuseStore830G3(authority.codec)
	authority.docreader = nil
	reopened, err := authority.captureG3PlatformSource830G3(context.Background(), scope, repo.source)
	require.NoError(t, err)
	require.Equal(t, first.record, reopened.record)
	require.Zero(t, doc.calls)
	id := g3FirstParseIdentityForSource(scope, repo.source)
	key, err := g3FirstParseKey(id)
	require.NoError(t, err)
	path := filepath.Join(authority.sourceReuse.root, key+".json")
	raw, err := os.ReadFile(path)
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(path, append(raw, byte('!')), 0600))
	_, err = authority.captureG3PlatformSource830G3(context.Background(), scope, repo.source)
	require.Error(t, err)
	cacheKey, err := conceptSourceReuseKey830G3(reopened.record.Identity, repo.source.BindingDigest)
	require.NoError(t, err)
	_, err = authority.sourceReuse.load(context.Background(), cacheKey, reopened.record.Identity, repo.source, func() (*conceptSourceReuseRecord830G3, error) { t.Fatal("corruption cannot rebuild"); return nil, nil })
	require.Error(t, err)
	require.Zero(t, doc.calls)
}
func TestG3FirstParseRepeatedBlockUsesSignedLocation(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	authority, doc, scope, e, block := nativeIndexFixture830G2(t)
	authority.codec = sourceReuseTestCodec830G3(t)
	authority.sourceReuse = newConceptSourceReuseStore830G3(authority.codec)
	readySourceReuseResource830G3(authority)
	result := firstParseNative(t, "相同标题\r\n相同标题", "相同标题")
	start := len([]rune("相同标题\r\n"))
	content := "相同标题"
	chunks := []types.ParsedChunk{{Seq: 0, Start: start, End: start + len([]rune(content)), Content: content}}
	seedFirstParseSnapshot(t, authority, scope, result, chunks)
	repo := authority.revisions.(*conceptKnowledgeStub830G2)
	prepared, err := authority.captureG3PlatformSource830G3(context.Background(), scope, repo.source)
	require.NoError(t, err)
	mapping := g3PlatformChunkPageMapping(prepared.record.Chunks[0], prepared.index, prepared.record.ChunkRanges)
	require.Equal(t, start, *mapping.BlockGlobalStart)
	require.Equal(t, 1, *mapping.SourcePageNumber)
	e.ConceptSourceIdentity830G2 = prepared.record.Identity
	e.BlockID = "chunk-1"
	e.Start = 0
	e.End = len([]rune(content))
	e.Quote = content
	e.QuoteHash = testSHA256830G2(content)
	block.ConceptSourceIdentity830G2 = e.ConceptSourceIdentity830G2
	block.BlockID = e.BlockID
	block.Text = content
	_, locator, err := resolveConceptSourceBlockQuote830G3(prepared.index, e, block, prepared.record.ChunkRanges)
	require.NoError(t, err)
	require.Equal(t, start, locator.BlockGlobalStart)
	require.Equal(t, 1, locator.ActualPageNumber)
	bad := map[string]g3FirstParseRange{"chunk-1": {Index: 0, Start: start + 1, End: start + 1 + len([]rune(content)), ContentSHA256: testSHA256830G2(content)}}
	_, _, err = resolveConceptSourceBlockQuote830G3(prepared.index, e, block, bad)
	require.Error(t, err)
	require.Zero(t, doc.calls)
}
func TestG3FirstParseScopeConfigAndExactChunkContent(t *testing.T) {
	cfg := &config.Config{G3PlatformProcessing: &config.G3PlatformProcessingConfig{Enabled: true, TenantID: 1, RawKBID: "raw"}}
	k := &types.Knowledge{TenantID: 1, KnowledgeBaseID: "raw"}
	require.True(t, g3FirstParseScope(cfg, k, "pdf"))
	for _, tc := range []struct {
		tenant   uint64
		kb, kind string
	}{{2, "raw", "pdf"}, {1, "other", "pdf"}, {1, "raw", "docx"}} {
		other := *k
		other.TenantID = tc.tenant
		other.KnowledgeBaseID = tc.kb
		require.False(t, g3FirstParseScope(cfg, &other, tc.kind))
	}
	cfg.G3PlatformProcessing.Enabled = false
	require.False(t, g3FirstParseScope(cfg, k, "pdf"))
	old := types.EffectiveProcessConfig{ChunkingConfig: types.ChunkingConfig{ParserEngineRules: []types.ParserEngineRule{{FileTypes: []string{"pdf"}, Engine: "auto"}}}}
	updated := g3FirstParseConfig(old)
	require.Equal(t, "auto", old.ChunkingConfig.ResolveParserEngine("pdf"))
	require.Equal(t, "builtin", updated.ChunkingConfig.ResolveParserEngine("pdf"))
	markdown := "标题\r\n| 项目 | 数值 |\r\n| --- | --- |\r\n| A | 10 |\r\n"
	start := len([]rune("标题\r\n"))
	exact := string([]rune(markdown)[start:])
	input := []types.ParsedChunk{{Seq: 0, Start: start, End: len([]rune(markdown)), Content: "重复表头\n" + exact}}
	rows, err := g3ExactSourceChunks(markdown, input)
	require.NoError(t, err)
	require.Equal(t, exact, rows[0].Content)
	require.Equal(t, "重复表头\n", rows[0].ContextHeader)
	require.Equal(t, "重复表头\n"+exact, input[0].Content)
	input[0].Content = strings.ReplaceAll(exact, "\r\n", "\n")
	_, err = g3ExactSourceChunks(markdown, input)
	require.Error(t, err, "line ending rewrites cannot become evidence")
}
func TestG3FirstParseStoreRejectsDriftAndWriteFailure(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	store := NewG3FirstParseStore(sourceReuseTestCodec830G3(t))
	result := firstParseNative(t, "原文\r\n")
	id := g3FirstParseIdentity{TenantID: 1, RawKBID: "raw", KnowledgeID: "knowledge", ParseAttempt: 3, SourceSHA256: testSHA256830G2("pdf")}
	chunks := []types.ParsedChunk{{Seq: 0, Start: 0, End: len([]rune(result.MarkdownContent)), Content: result.MarkdownContent}}
	require.NoError(t, store.save(id, result, chunks))
	require.NoError(t, store.save(id, result, chunks))
	for _, change := range []func(*g3FirstParseIdentity){func(x *g3FirstParseIdentity) { x.ParseAttempt++ }, func(x *g3FirstParseIdentity) { x.TenantID++ }, func(x *g3FirstParseIdentity) { x.SourceSHA256 = testSHA256830G2("other") }} {
		wrong := id
		change(&wrong)
		_, err := store.reuse.readFirstParse(wrong)
		require.Error(t, err)
	}
	chunks[0].Start = 1
	require.Error(t, store.save(id, result, chunks))
	bad := NewG3FirstParseStore(sourceReuseTestCodec830G3(t))
	bad.reuse.root = filepath.Join(t.TempDir(), "file")
	require.NoError(t, os.WriteFile(bad.reuse.root, []byte("not a directory"), 0600))
	chunks[0].Start = 0
	require.Error(t, bad.save(id, result, chunks))
}

type firstParseReader struct {
	interfaces.DocumentReader
	result   *types.ReadResult
	requests []*types.ReadRequest
}

func (d *firstParseReader) Read(_ context.Context, req *types.ReadRequest) (*types.ReadResult, error) {
	copyReq := *req
	d.requests = append(d.requests, &copyReq)
	return d.result, nil
}

type firstParseKnowledgeRepo struct {
	interfaces.KnowledgeRepository
	knowledge *types.Knowledge
	statuses  []string
}

func (r *firstParseKnowledgeRepo) GetKnowledgeByID(context.Context, uint64, string) (*types.Knowledge, error) {
	return r.knowledge, nil
}
func (r *firstParseKnowledgeRepo) UpdateKnowledge(_ context.Context, k *types.Knowledge) error {
	r.statuses = append(r.statuses, k.ParseStatus)
	return nil
}

type firstParseTenantRepo struct{ interfaces.TenantRepository }

func (*firstParseTenantRepo) GetTenantByID(_ context.Context, id uint64) (*types.Tenant, error) {
	return &types.Tenant{ID: id}, nil
}
func TestG3FirstParseActualConvertScopesParserAndReusesResult(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	authority, _, scope, _, _ := nativeIndexFixture830G2(t)
	authority.codec = sourceReuseTestCodec830G3(t)
	authority.sourceReuse = newConceptSourceReuseStore830G3(authority.codec)
	readySourceReuseResource830G3(authority)
	native := firstParseNative(t, "平安测试两全保险\r\n保险条款", "附录")
	reader := &firstParseReader{result: native}
	k := &types.Knowledge{ID: "knowledge-1", TenantID: scope.TenantID, KnowledgeBaseID: scope.RawKBID, FileType: "pdf", FileSHA256: testSHA256830G2("pdf"), CurrentParseAttempt: 1}
	kb := &types.KnowledgeBase{ID: scope.RawKBID, ChunkingConfig: types.ChunkingConfig{ParserEngineRules: []types.ParserEngineRule{{FileTypes: []string{"pdf"}, Engine: "auto"}}}}
	cfg := &config.Config{G3PlatformProcessing: &config.G3PlatformProcessingConfig{Enabled: true, TenantID: scope.TenantID, RawKBID: scope.RawKBID}}
	s := &knowledgeService{config: cfg, documentReader: reader, fileSvc: &revisionSourceFileServiceStub{data: []byte("pdf")}, firstParse: &G3FirstParseStore{reuse: authority.sourceReuse}}
	eff := ResolveProcessConfig(kb, nil)
	payload := types.DocumentProcessPayload{FileType: "pdf", FileName: "source.pdf", FilePath: "fixture.pdf", Revision: newRevisionBinding(1, k.FileSHA256, kb, eff, "pdf"), Attempt: 99}
	got, err := s.convert(context.Background(), payload, kb, k, eff, true)
	require.NoError(t, err)
	require.Len(t, reader.requests, 1)
	require.Equal(t, "builtin", reader.requests[0].ParserEngine)
	require.Equal(t, map[string]string{"pdf_native_structure_capture": conceptNativeCapture830G2}, reader.requests[0].ParserEngineOverrides)
	require.Equal(t, native.MarkdownContent, got.MarkdownContent)
	seedFirstParseSnapshot(t, authority, scope, got, []types.ParsedChunk{{Seq: 0, Content: got.MarkdownContent, Start: 0, End: len([]rune(got.MarkdownContent))}})
	repo := authority.revisions.(*conceptKnowledgeStub830G2)
	_, err = authority.captureG3PlatformSource830G3(context.Background(), scope, repo.source)
	require.NoError(t, err)
	authority.sourceReuse = newConceptSourceReuseStore830G3(authority.codec)
	_, err = authority.captureG3PlatformSource830G3(context.Background(), scope, repo.source)
	require.NoError(t, err)
	require.Len(t, reader.requests, 1)
	other := *k
	other.KnowledgeBaseID = "other"
	_, err = s.convert(context.Background(), payload, kb, &other, eff, true)
	require.NoError(t, err)
	require.Len(t, reader.requests, 2)
	require.Equal(t, "auto", reader.requests[1].ParserEngine)
	require.NotContains(t, reader.requests[1].ParserEngineOverrides, "pdf_native_structure_capture")
}
func TestG3FirstParseProcessDocumentWriteFailureClosesDocreader(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	_, spans := newKnowledgeDispatchJournalTest(t)
	seedDispatchSpan(t, spans, types.KnowledgeProcessingSpan{KnowledgeID: "knowledge", Attempt: 4, SpanID: "root", Name: "root", Kind: types.SpanKindRoot, Status: types.SpanStatusRunning})
	seedDispatchSpan(t, spans, types.KnowledgeProcessingSpan{KnowledgeID: "knowledge", Attempt: 4, SpanID: "doc", ParentSpanID: "root", Name: types.StageDocReader, Kind: types.SpanKindStage, Status: types.SpanStatusPending})
	k := &types.Knowledge{ID: "knowledge", TenantID: 1, KnowledgeBaseID: "raw", FileType: "pdf", FileName: "source.pdf", FileSHA256: testSHA256830G2("pdf"), CurrentParseAttempt: 3, ParseStatus: types.ParseStatusPending}
	kb := &types.KnowledgeBase{ID: "raw", ChunkingConfig: types.ChunkingConfig{ChunkSize: 100, ChunkOverlap: 0, ParserEngineRules: []types.ParserEngineRule{{FileTypes: []string{"pdf"}, Engine: "auto"}}}}
	repo := &firstParseKnowledgeRepo{knowledge: k}
	store := NewG3FirstParseStore(sourceReuseTestCodec830G3(t))
	store.reuse.root = filepath.Join(t.TempDir(), "file")
	require.NoError(t, os.WriteFile(store.reuse.root, []byte("occupied"), 0600))
	reader := &firstParseReader{result: firstParseNative(t, "平安测试两全保险\r\n保险条款\r\n")}
	s := &knowledgeService{config: &config.Config{G3PlatformProcessing: &config.G3PlatformProcessingConfig{Enabled: true, TenantID: 1, SpaceID: "space", RawKBID: "raw", WikiKBID: "wiki"}}, repo: repo, tenantRepo: &firstParseTenantRepo{}, kbService: &createKnowledgeFileKBServiceStub{kb: kb}, documentReader: reader, fileSvc: &revisionSourceFileServiceStub{data: []byte("pdf")}, firstParse: store, spanTracker: NewSpanTracker(spans, nil)}
	payload := types.DocumentProcessPayload{TenantID: 1, KnowledgeID: k.ID, KnowledgeBaseID: kb.ID, FileType: "pdf", FileName: "source.pdf", FilePath: "fixture.pdf", Attempt: 4, Revision: newRevisionBinding(3, k.FileSHA256, kb, ResolveProcessConfig(kb, nil), "pdf")}
	raw, err := json.Marshal(payload)
	require.NoError(t, err)
	require.Error(t, s.ProcessDocument(context.Background(), asynq.NewTask(types.TypeDocumentProcess, raw)))
	require.Len(t, reader.requests, 1, "must reach first parse; this is not a setup/journal failure")
	require.Equal(t, types.ParseStatusFailed, k.ParseStatus)
	require.NotContains(t, repo.statuses, types.ParseStatusCompleted)
	rows, err := spans.ListByAttempt(context.Background(), k.ID, 4)
	require.NoError(t, err)
	found := false
	for _, row := range rows {
		if row.Name == types.StageDocReader {
			found = true
			require.Equal(t, types.SpanStatusFailed, row.Status)
			require.NotNil(t, row.FinishedAt)
		}
	}
	require.True(t, found)
	// No modelService/indexing port is installed: reaching processChunks would panic.
}
func TestG3FirstParseRealParentChildTableCoordinates(t *testing.T) {
	markdown := "# 费率表\r\n| 年龄 | 费率 |\r\n| --- | --- |\r\n"
	for i := 0; i < 40; i++ {
		markdown += fmt.Sprintf("| %d | %d |\r\n", i, 100+i)
	}
	parentCfg := chunker.SplitterConfig{ChunkSize: 160, ChunkOverlap: 20, Separators: []string{"\n"}}
	childCfg := chunker.SplitterConfig{ChunkSize: 60, ChunkOverlap: 10, Separators: []string{"\n"}}
	result, splitErr := g3FirstParseSplitParentChild(markdown, parentCfg, childCfg)
	require.NoError(t, splitErr)
	require.Greater(t, len(result.Children), 2)
	chunks := []types.ParsedChunk{}
	for _, c := range result.Children {
		chunks = append(chunks, types.ParsedChunk{Content: c.Content, ContextHeader: c.ContextHeader, Seq: c.Seq, Start: c.Start, End: c.End})
	}
	_, err := g3ExactSourceChunks(markdown, chunks)
	require.NoError(t, err, "child offsets must already be in the unchanged full source coordinate system")
	for _, p := range result.Parents {
		chunks = append(chunks, types.ParsedChunk{Content: p.Content, Seq: p.Seq, Start: p.Start, End: p.End})
	}
	sort.Slice(chunks, func(i, j int) bool { return chunks[i].Seq < chunks[j].Seq })
	manifest := []types.RevisionManifestChunk{}
	ranges := []g3FirstParseRange{}
	for i, c := range chunks {
		manifest = append(manifest, types.RevisionManifestChunk{ID: fmt.Sprintf("db-chunk-%d", i), Index: c.Seq, Content: c.Content})
		ranges = append(ranges, g3FirstParseRange{Index: c.Seq, Start: c.Start, End: c.End, ContentSHA256: testSHA256830G2(c.Content)})
	}
	_, err = types.ComputeRevisionManifestDigest("knowledge", 3, manifest)
	require.NoError(t, err, "first capture must use the same globally unique indexes committed by the real revision")
	bound, err := g3FirstParseBindings(&g3FirstParseRecord{Markdown: markdown, Chunks: ranges}, manifest)
	require.NoError(t, err)
	require.Len(t, bound, len(manifest))
	for _, c := range manifest {
		require.True(t, g3FirstParseRangeMatches(markdown, c.Content, bound[c.ID]))
	}

}

func TestG3FirstParseRejectsLegacyCacheWithExistingFirstArtifact(t *testing.T) {
	for _, surface := range []string{"snapshot", "citation"} {
		t.Run(surface, func(t *testing.T) {
			t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
			authority, doc, scope, e, block := nativeIndexFixture830G2(t)
			authority.codec = sourceReuseTestCodec830G3(t)
			authority.sourceReuse = newConceptSourceReuseStore830G3(authority.codec)
			readySourceReuseResource830G3(authority)
			result := doc.result
			seedFirstParseSnapshot(t, authority, scope, result, []types.ParsedChunk{{Seq: 0, Content: result.MarkdownContent, Start: 0, End: len([]rune(result.MarkdownContent))}})
			repo := authority.revisions.(*conceptKnowledgeStub830G2)
			good, err := authority.captureG3PlatformSource830G3(context.Background(), scope, repo.source)
			require.NoError(t, err)
			key, err := conceptSourceReuseKey830G3(good.record.Identity, repo.source.BindingDigest)
			require.NoError(t, err)
			legacy := good.record
			legacy.FirstParseSHA256 = ""
			legacy.ChunkRanges = nil
			prepared, err := validateConceptSourceReuse830G3(&legacy, legacy.Identity, repo.source)
			require.NoError(t, err)
			authority.sourceReuse.entries[key] = prepared
			if surface == "snapshot" {
				_, err = authority.captureG3PlatformSource830G3(context.Background(), scope, repo.source)
			} else {
				e.ConceptSourceIdentity830G2 = legacy.Identity
				e.Start = 0
				e.End = 2
				e.Quote = "A😀"
				e.QuoteHash = testSHA256830G2(e.Quote)
				block.ConceptSourceIdentity830G2 = e.ConceptSourceIdentity830G2
				block.Text = result.MarkdownContent
				_, _, _, err = authority.verifyReusableConceptSource830G3(context.Background(), scope, e, &block, true, repo.knowledge, repo.source, repo.resource)
			}
			require.Error(t, err, "an existing first parse must be bound even when a legacy cache key matches")
			require.Empty(t, authority.sourceReuse.entries[key].record.FirstParseSHA256, "do not overwrite the historical cache")
			require.Zero(t, doc.calls)
		})
	}
}
