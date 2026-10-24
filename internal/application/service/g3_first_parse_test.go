package service

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/capture"
	"github.com/Tencent/WeKnora/internal/infrastructure/chunker"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/hibiken/asynq"

	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func TestG3FirstParseParserConfigAndExactChunkContent(t *testing.T) {
	old := types.EffectiveProcessConfig{
		ChunkingConfig: types.ChunkingConfig{
			ParserEngineRules: []types.ParserEngineRule{{FileTypes: []string{"pdf"}, Engine: "auto"}},
		},
	}
	updated := capture.ParserConfig(old)
	require.Equal(t, "auto", old.ChunkingConfig.ResolveParserEngine("pdf"))
	require.Equal(t, "builtin", updated.ChunkingConfig.ResolveParserEngine("pdf"))
	markdown := "标题\r\n| 项目 | 数值 |\r\n| --- | --- |\r\n| A | 10 |\r\n"
	start := len([]rune("标题\r\n"))
	exact := string([]rune(markdown)[start:])
	input := []types.ParsedChunk{{Seq: 0, Start: start, End: len([]rune(markdown)), Content: "重复表头\n" + exact}}
	rows, err := capture.ExactChunks(markdown, input)
	require.NoError(t, err)
	require.Equal(t, exact, rows[0].Content)
	require.Equal(t, "重复表头\n", rows[0].ContextHeader)
	require.Equal(t, "重复表头\n"+exact, input[0].Content)
	input[0].Content = strings.ReplaceAll(exact, "\r\n", "\n")
	_, err = capture.ExactChunks(markdown, input)
	require.Error(t, err, "line ending rewrites cannot become evidence")
}

func TestG3FirstParseStoreRejectsDriftAndWriteFailure(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	store := NewG3FirstParseStore(captureTestKeys(t))
	result := firstParseNative(t, "原文\r\n")
	id := capture.Identity{
		TenantID:     1,
		RawKBID:      "raw",
		KnowledgeID:  "knowledge",
		ParseAttempt: 3,
		SourceSHA256: captureTestSHA256("pdf"),
	}
	chunks := []types.ParsedChunk{
		{Seq: 0, Start: 0, End: len([]rune(result.MarkdownContent)), Content: result.MarkdownContent},
	}
	require.NoError(t, store.save(id, result, chunks))
	require.NoError(t, store.save(id, result, chunks))
	for _, change := range []func(*capture.Identity){
		func(x *capture.Identity) { x.ParseAttempt++ },
		func(x *capture.Identity) { x.TenantID++ },
		func(x *capture.Identity) { x.SourceSHA256 = captureTestSHA256("other") },
	} {
		wrong := id
		change(&wrong)
		_, err := store.captures().Read(wrong)
		require.Error(t, err)
	}
	chunks[0].Start = 1
	require.Error(t, store.save(id, result, chunks))
	bad := NewG3FirstParseStore(captureTestKeys(t))
	bad.root = filepath.Join(t.TempDir(), "file")
	require.NoError(t, os.WriteFile(bad.root, []byte("not a directory"), 0o600))
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

type firstParseTenantService struct{ interfaces.TenantService }

type firstParseTenantRepo struct{ interfaces.TenantRepository }

func (*firstParseTenantRepo) GetTenantByID(_ context.Context, id uint64) (*types.Tenant, error) {
	return &types.Tenant{ID: id}, nil
}

func TestG3FirstParseActualConvertScopesParser(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	scope := types.WikiReleaseScope{TenantID: 7, SpaceID: "space", RawKBID: "raw", WikiKBID: "wiki"}
	native := firstParseNative(t, "平安测试两全保险\r\n保险条款", "附录")
	reader := &firstParseReader{result: native}
	k := &types.Knowledge{
		ID:                  "knowledge-1",
		TenantID:            scope.TenantID,
		KnowledgeBaseID:     scope.RawKBID,
		FileType:            "pdf",
		FileSHA256:          captureTestSHA256("pdf"),
		CurrentParseAttempt: 1,
	}
	kb := &types.KnowledgeBase{
		ID: scope.RawKBID,
		ChunkingConfig: types.ChunkingConfig{
			ParserEngineRules: []types.ParserEngineRule{{FileTypes: []string{"pdf"}, Engine: "auto"}},
		},
	}
	s := &knowledgeService{
		config:         &config.Config{},
		captureScope:   rawKBs{scope.RawKBID: scope.TenantID},
		tenantService:  &firstParseTenantService{},
		documentReader: reader,
		fileSvc:        &revisionSourceFileServiceStub{data: []byte("pdf")},
		firstParse:     NewG3FirstParseStore(captureTestKeys(t)),
	}
	eff := ResolveProcessConfig(kb, nil)
	payload := types.DocumentProcessPayload{
		FileType: "pdf",
		FileName: "source.pdf",
		FilePath: "fixture.pdf",
		Revision: newRevisionBinding(1, k.FileSHA256, kb, eff, "pdf"),
		Attempt:  99,
	}
	got, err := s.convert(context.Background(), payload, kb, k, eff, true)
	require.NoError(t, err)
	require.Len(t, reader.requests, 1)
	require.Equal(t, "builtin", reader.requests[0].ParserEngine)
	require.Equal(
		t,
		map[string]string{"pdf_native_structure_capture": capture.NativeCaptureMode},
		reader.requests[0].ParserEngineOverrides,
	)
	require.Equal(t, native.MarkdownContent, got.MarkdownContent)
	other := *k
	other.KnowledgeBaseID = "other"
	_, err = s.convert(context.Background(), payload, kb, &other, eff, true)
	require.NoError(t, err)
	require.Len(t, reader.requests, 2)
	require.Equal(t, "auto", reader.requests[1].ParserEngine)
	require.NotContains(t, reader.requests[1].ParserEngineOverrides, "pdf_native_structure_capture")
}

// seededSpanRepository is a span table shared by every connection of one test (the pipeline may
// query from more than one), holding the given rows.
func seededSpanRepository(t *testing.T, rows ...types.KnowledgeProcessingSpan) wikirepository.KnowledgeSpanRepository {
	t.Helper()
	db, err := gorm.Open(sqlite.Open("file:"+t.Name()+"?mode=memory&cache=shared"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.Exec(spanTrackerTestDDL).Error)
	repo := wikirepository.NewKnowledgeSpanRepository(db)
	for i := range rows {
		require.NoError(t, repo.Upsert(context.Background(), &rows[i]))
	}
	return repo
}

func TestG3FirstParseProcessDocumentWriteFailureClosesDocreader(t *testing.T) {
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	spans := seededSpanRepository(
		t,
		types.KnowledgeProcessingSpan{
			KnowledgeID: "knowledge",
			Attempt:     4,
			SpanID:      "root",
			Name:        "root",
			Kind:        types.SpanKindRoot,
			Status:      types.SpanStatusRunning,
		},
		types.KnowledgeProcessingSpan{
			KnowledgeID:  "knowledge",
			Attempt:      4,
			SpanID:       "doc",
			ParentSpanID: "root",
			Name:         types.StageDocReader,
			Kind:         types.SpanKindStage,
			Status:       types.SpanStatusPending,
		},
	)
	k := &types.Knowledge{
		ID:                  "knowledge",
		TenantID:            1,
		KnowledgeBaseID:     "raw",
		FileType:            "pdf",
		FileName:            "source.pdf",
		FileSHA256:          captureTestSHA256("pdf"),
		CurrentParseAttempt: 3,
		ParseStatus:         types.ParseStatusPending,
	}
	kb := &types.KnowledgeBase{
		ID:       "raw",
		TenantID: 1,
		ChunkingConfig: types.ChunkingConfig{
			ChunkSize:         100,
			ChunkOverlap:      0,
			ParserEngineRules: []types.ParserEngineRule{{FileTypes: []string{"pdf"}, Engine: "auto"}},
		},
	}
	repo := &firstParseKnowledgeRepo{knowledge: k}
	store := NewG3FirstParseStore(captureTestKeys(t))
	store.root = filepath.Join(t.TempDir(), "file")
	require.NoError(t, os.WriteFile(store.root, []byte("occupied"), 0o600))
	reader := &firstParseReader{result: firstParseNative(t, "平安测试两全保险\r\n保险条款\r\n")}
	s := &knowledgeService{
		config:         &config.Config{},
		captureScope:   rawKBs{"raw": 1},
		repo:           repo,
		tenantRepo:     &firstParseTenantRepo{},
		tenantService:  &firstParseTenantService{},
		kbService:      &createKnowledgeFileKBServiceStub{kb: kb},
		documentReader: reader,
		fileSvc:        &revisionSourceFileServiceStub{data: []byte("pdf")},
		firstParse:     store,
		spanTracker:    NewSpanTracker(spans, nil),
	}
	payload := types.DocumentProcessPayload{
		TenantID:        1,
		KnowledgeID:     k.ID,
		KnowledgeBaseID: kb.ID,
		FileType:        "pdf",
		FileName:        "source.pdf",
		FilePath:        "fixture.pdf",
		Attempt:         4,
		Revision:        newRevisionBinding(3, k.FileSHA256, kb, ResolveProcessConfig(kb, nil), "pdf"),
	}
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
	result, splitErr := capture.SplitParentChild(markdown, parentCfg, childCfg)
	require.NoError(t, splitErr)
	require.Greater(t, len(result.Children), 2)
	chunks := []types.ParsedChunk{}
	for _, c := range result.Children {
		chunks = append(
			chunks,
			types.ParsedChunk{
				Content:       c.Content,
				ContextHeader: c.ContextHeader,
				Seq:           c.Seq,
				Start:         c.Start,
				End:           c.End,
			},
		)
	}
	_, err := capture.ExactChunks(markdown, chunks)
	require.NoError(t, err, "child offsets must already be in the unchanged full source coordinate system")
	for _, p := range result.Parents {
		chunks = append(chunks, types.ParsedChunk{Content: p.Content, Seq: p.Seq, Start: p.Start, End: p.End})
	}
	sort.Slice(chunks, func(i, j int) bool { return chunks[i].Seq < chunks[j].Seq })
	manifest := []types.RevisionManifestChunk{}
	for i, c := range chunks {
		// Production ListChunksByKnowledgeID and revision manifests contain text children only.
		if c.Seq >= len(result.Parents) {
			manifest = append(
				manifest,
				types.RevisionManifestChunk{ID: fmt.Sprintf("db-chunk-%d", i), Index: c.Seq, Content: c.Content},
			)
		}
	}
	_, err = types.ComputeRevisionManifestDigest("knowledge", 3, manifest)
	require.NoError(t, err, "first capture must use the same globally unique indexes committed by the real revision")
}
