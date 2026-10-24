// S4c-2c acceptance: PDFs uploaded to the RAW knowledge base of an enterprise Space
// are parsed with builtin pdfium, their first parse is saved verbatim for the exact
// parse attempt before any chunk is written, and scanned PDFs complete without a
// capture instead of failing (Spec §3.2, §3.3). The G3 scope keeps its rules.
// Protected file: written by Claude.
//
// RED until source.CaptureScope and knowledgeService.captureScope exist. The parser
// is an in-memory fake that returns what docreader returns; chunk persistence stops
// at the revision write fence. No docreader, database, network or model is used.
package service

import (
	"context"
	"encoding/json"
	"maps"
	"os"
	"path/filepath"
	"testing"

	"github.com/hibiken/asynq"
	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

const (
	enterpriseTenant = uint64(7)
	enterpriseRawKB  = "enterprise-raw"
	// docreader's native capture rejects a page without a usable text layer with
	// exactly this message (docreader/parser/pdf_parser.py, pinned by
	// docreader/tests/test_pdf_router.py::test_scanned_page_is_rejected_without_image_fallback).
	scannedPageError = "page 2 is scanned"
)

// rawKBs is the capture scope under test: knowledge base ID -> owning tenant.
type rawKBs map[string]uint64

func (r rawKBs) RawKB(tenantID uint64, knowledgeBaseID string) bool {
	owner, ok := r[knowledgeBaseID]
	return ok && owner == tenantID
}

var _ source.CaptureScope = rawKBs{}

var enterpriseScope = types.WikiReleaseScope{
	TenantID: enterpriseTenant, SpaceID: "enterprise-space", RawKBID: enterpriseRawKB, WikiKBID: "enterprise-wiki",
}

// captureRequested reports whether the parser was asked for builtin pdfium
// native capture and nothing else (user overrides never reach the parser).
func captureRequested(req *types.ReadRequest) bool {
	return req.ParserEngine == "builtin" && maps.Equal(req.ParserEngineOverrides,
		map[string]string{"pdf_native_structure_capture": conceptNativeCapture830G2})
}

type convertCase struct {
	cfg    *config.Config
	scope  source.CaptureScope
	tenant uint64
	kb     string
	file   string
	result *types.ReadResult
}

// convertOnce runs the real parse step for one upload whose KB chose another engine.
func convertOnce(t *testing.T, c convertCase) (*types.Knowledge, *firstParseReader, *types.ReadResult) {
	t.Helper()
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	reader := &firstParseReader{result: c.result}
	k := &types.Knowledge{
		ID: "knowledge", TenantID: c.tenant, KnowledgeBaseID: c.kb, FileType: c.file,
		FileSHA256: testSHA256830G2("pdf"), CurrentParseAttempt: 1, ParseStatus: types.ParseStatusProcessing,
	}
	kb := &types.KnowledgeBase{ID: c.kb, TenantID: c.tenant, ChunkingConfig: types.ChunkingConfig{
		ParserEngineRules: []types.ParserEngineRule{{FileTypes: []string{"pdf", "docx"}, Engine: "auto"}},
	}}
	s := &knowledgeService{
		config: c.cfg, captureScope: c.scope, repo: &firstParseKnowledgeRepo{knowledge: k},
		tenantService: &firstParseTenantService{}, documentReader: reader,
		fileSvc:    &revisionSourceFileServiceStub{data: []byte("pdf")},
		firstParse: NewG3FirstParseStore(captureTestKeys(t)),
	}
	eff := ResolveProcessConfig(kb, nil)
	payload := types.DocumentProcessPayload{
		FileType: c.file, FileName: "source." + c.file, FilePath: "fixture." + c.file, Attempt: 9,
		Revision: newRevisionBinding(1, k.FileSHA256, kb, eff, c.file),
	}
	got, err := s.convert(context.Background(), payload, kb, k, eff, true)
	require.NoError(t, err)
	require.Len(t, reader.requests, 1, "exactly one parse per attempt")
	return k, reader, got
}

func TestEnterpriseRawKBPDFsAreAlwaysParsedForCapture(t *testing.T) {
	enterprise := rawKBs{enterpriseRawKB: enterpriseTenant}
	for _, tc := range []struct {
		name string
		convertCase
		capture bool
	}{
		{"enterprise RAW KB pdf", convertCase{&config.Config{}, enterprise, 7, enterpriseRawKB, "pdf", nil}, true},
		{"same KB id, other tenant", convertCase{&config.Config{}, enterprise, 8, enterpriseRawKB, "pdf", nil}, false},
		{"other KB of the tenant", convertCase{&config.Config{}, enterprise, 7, "other-kb", "pdf", nil}, false},
		{"non-pdf in the RAW KB", convertCase{&config.Config{}, enterprise, 7, enterpriseRawKB, "docx", nil}, false},
		{"no enterprise Space", convertCase{&config.Config{}, nil, 7, enterpriseRawKB, "pdf", nil}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			tc.result = firstParseNative(t, "平安测试两全保险\r\n保险条款", "附录")
			k, reader, got := convertOnce(t, tc.convertCase)
			require.Equal(t, tc.capture, captureRequested(reader.requests[0]), "%+v", reader.requests[0])
			if !tc.capture {
				require.Equal(t, "auto", reader.requests[0].ParserEngine, "outside the scope the KB's engine is kept")
			}
			require.NotEqual(t, types.ParseStatusFailed, k.ParseStatus, k.ErrorMessage)
			require.NotNil(t, got)
		})
	}
}

func TestCaptureParserFailuresOtherThanScannedPagesStillFailClosed(t *testing.T) {
	enterprise := rawKBs{enterpriseRawKB: enterpriseTenant}
	for _, tc := range []struct {
		name, parserError string
		convertCase
	}{
		{
			"enterprise invalid text", "page 1 text is not valid UTF-8",
			convertCase{&config.Config{}, enterprise, 7, enterpriseRawKB, "pdf", nil},
		},
		{
			"enterprise near-miss signal", scannedPageError + "; rendered as image",
			convertCase{&config.Config{}, enterprise, 7, enterpriseRawKB, "pdf", nil},
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			tc.result = &types.ReadResult{Error: tc.parserError}
			k, reader, _ := convertOnce(t, tc.convertCase)
			require.True(t, captureRequested(reader.requests[0]))
			require.Equal(t, types.ParseStatusFailed, k.ParseStatus,
				"only the exact scanned-page signal in an enterprise RAW KB is tolerated")
		})
	}
}

// fencedChunks records the chunk batch and then reports a superseded attempt, so
// processing stops before indexing: no embedding, vector store or model is wired.
type fencedChunks struct {
	interfaces.ChunkRepository
	written []*types.Chunk
	writes  int
}

func (r *fencedChunks) ListAllChunksByKnowledgeID(context.Context, uint64, string) ([]*types.Chunk, error) {
	return nil, nil
}

func (r *fencedChunks) CreateChunksAtRevision(
	_ context.Context, chunks []*types.Chunk, _ uint64, _, _ string, _ int64, _ string,
) error {
	r.writes++
	r.written = append(r.written, chunks...)
	return repository.ErrRevisionSuperseded
}

type noGraph struct {
	interfaces.RetrieveGraphRepository
}

func (noGraph) DelGraph(context.Context, []types.NameSpace) error { return nil }

type enterpriseUpload struct {
	service   *knowledgeService
	knowledge *types.Knowledge
	repo      *firstParseKnowledgeRepo
	reader    *firstParseReader
	chunks    *fencedChunks
	store     *G3FirstParseStore
	task      *asynq.Task
}

// uploadToEnterpriseRawKB prepares the worker task of attempt 3 of a PDF uploaded
// to the enterprise RAW KB, whose KB-level parser choice is not builtin.
func uploadToEnterpriseRawKB(t *testing.T, parsed *types.ReadResult) *enterpriseUpload {
	t.Helper()
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	t.Setenv("RETRIEVE_DRIVER", "")
	k := &types.Knowledge{
		ID: "knowledge", TenantID: enterpriseTenant, KnowledgeBaseID: enterpriseRawKB, FileType: "pdf",
		FileName: "source.pdf", FileSHA256: testSHA256830G2("pdf"), CurrentParseAttempt: 3,
		ParseStatus: types.ParseStatusPending,
	}
	kb := &types.KnowledgeBase{ID: enterpriseRawKB, TenantID: enterpriseTenant, ChunkingConfig: types.ChunkingConfig{
		ChunkSize: 100, ParserEngineRules: []types.ParserEngineRule{{FileTypes: []string{"pdf"}, Engine: "auto"}},
	}}
	u := &enterpriseUpload{
		knowledge: k, repo: &firstParseKnowledgeRepo{knowledge: k}, reader: &firstParseReader{result: parsed},
		chunks: &fencedChunks{}, store: NewG3FirstParseStore(captureTestKeys(t)),
	}
	u.service = &knowledgeService{
		config: &config.Config{}, captureScope: rawKBs{enterpriseRawKB: enterpriseTenant},
		repo: u.repo, tenantRepo: &firstParseTenantRepo{}, tenantService: &firstParseTenantService{},
		kbService: &createKnowledgeFileKBServiceStub{kb: kb}, documentReader: u.reader,
		fileSvc: &revisionSourceFileServiceStub{data: []byte("pdf")}, firstParse: u.store,
		chunkRepo: u.chunks, graphEngine: noGraph{},
	}
	raw, err := json.Marshal(types.DocumentProcessPayload{
		TenantID: enterpriseTenant, KnowledgeID: k.ID, KnowledgeBaseID: kb.ID, FileType: "pdf",
		FileName: "source.pdf", FilePath: "fixture.pdf", Attempt: 4,
		Revision: newRevisionBinding(3, k.FileSHA256, kb, ResolveProcessConfig(kb, nil), "pdf"),
	})
	require.NoError(t, err)
	u.task = asynq.NewTask(types.TypeDocumentProcess, raw)
	return u
}

// artifact reads the capture after a restart, as the page API does, assuming the
// attempt's revision was committed with the upload's file digest.
func (u *enterpriseUpload) artifact(scope types.WikiReleaseScope, attempt int64) (*source.Artifact, error) {
	committed := *u.knowledge
	repo := &sourcePagesRepository{knowledge: &committed, revision: &types.KnowledgeRevision{
		KnowledgeID: committed.ID, ParseAttempt: 3, FileSHA256: committed.FileSHA256,
	}}
	restarted := NewG3FirstParseStore(u.store.keys)
	return restarted.ReadSourceArtifact(context.Background(), repo, scope, committed.ID, attempt)
}

func (u *enterpriseUpload) pages(attempt int64) (*source.PageSet, error) {
	return source.NewService(sourcePagesStoreFunc(
		func(_ context.Context, _ source.Scope, _ string, attempt int64) (*source.Artifact, error) {
			return u.artifact(enterpriseScope, attempt)
		},
	)).Pages(context.Background(), source.Scope{TenantID: enterpriseTenant, SpaceID: enterpriseScope.SpaceID},
		u.knowledge.ID, attempt)
}

func TestEnterpriseTextPDFCapturesItsVerbatimFirstParseForTheExactAttempt(t *testing.T) {
	first, second := "平安测试两全保险\r\n第一条 保险责任", "第二条\r\n责任免除\n"
	parsed := firstParseNative(t, first, second)
	u := uploadToEnterpriseRawKB(t, parsed)
	require.NoError(t, u.service.ProcessDocument(context.Background(), u.task))

	require.Len(t, u.reader.requests, 1)
	require.True(t, captureRequested(u.reader.requests[0]), "the KB's parser choice is replaced by builtin pdfium")
	require.NotContains(t, u.repo.statuses, types.ParseStatusFailed, u.knowledge.ErrorMessage)
	require.Equal(t, 1, u.chunks.writes, "the capture is saved and chunking continues")
	require.NotEmpty(t, u.chunks.written)
	full := []rune(parsed.MarkdownContent)
	for _, c := range u.chunks.written {
		require.Equal(t, string(full[c.StartAt:c.EndAt]), c.Content, "chunk ranges index the verbatim capture")
	}

	a, err := u.artifact(enterpriseScope, 3)
	require.NoError(t, err)
	require.Equal(t, parsed.MarkdownContent, a.Markdown, "line endings are kept exactly as pdfium returned them")
	set, err := u.pages(3)
	require.NoError(t, err)
	require.Len(t, set.Pages, 2)
	require.Equal(t, first, set.Pages[0].Text)
	require.Equal(t, second, set.Pages[1].Text)

	_, err = u.artifact(enterpriseScope, 2)
	require.ErrorIs(t, err, source.ErrNotFound, "another attempt never reads this capture")
	other := enterpriseScope
	other.RawKBID = "other-raw"
	_, err = u.artifact(other, 3)
	require.ErrorIs(t, err, source.ErrNotFound, "a Space whose RAW KB does not own the source cannot read it")
}

func TestEnterpriseScannedPDFCompletesWithoutCaptureOrFailure(t *testing.T) {
	u := uploadToEnterpriseRawKB(t, &types.ReadResult{Error: scannedPageError})
	require.NoError(t, u.service.ProcessDocument(context.Background(), u.task))

	require.Len(t, u.reader.requests, 1, "a scanned PDF is not re-parsed, rendered or sent to OCR")
	require.True(t, captureRequested(u.reader.requests[0]))
	require.NotContains(t, u.repo.statuses, types.ParseStatusFailed, u.knowledge.ErrorMessage)
	require.NotEqual(t, types.ParseStatusFailed, u.knowledge.ParseStatus)
	require.Empty(t, u.knowledge.ErrorMessage)
	require.Equal(t, 1, u.chunks.writes, "the attempt takes the normal completion path")
	require.Empty(t, u.chunks.written, "no text of a scanned PDF is indexed or used as evidence")

	_, err := u.artifact(enterpriseScope, 3)
	require.ErrorIs(t, err, source.ErrNotCaptured)
	_, err = u.pages(3)
	var failure *source.Error
	require.ErrorAs(t, err, &failure)
	require.Equal(t, source.ErrorNotCaptured, failure.Code)
	entries, err := os.ReadDir(u.store.root)
	if err == nil {
		require.Empty(t, entries, "no first-parse record or partial file is written")
	} else {
		require.ErrorIs(t, err, os.ErrNotExist)
	}
}

func TestEnterpriseCaptureWriteFailureFailsTheDocumentBeforeChunks(t *testing.T) {
	u := uploadToEnterpriseRawKB(t, firstParseNative(t, "平安测试两全保险\r\n保险条款"))
	u.store.root = filepath.Join(t.TempDir(), "occupied")
	require.NoError(t, os.WriteFile(u.store.root, []byte("not a directory"), 0o600))
	require.Error(t, u.service.ProcessDocument(context.Background(), u.task))

	require.Len(t, u.reader.requests, 1)
	require.True(t, captureRequested(u.reader.requests[0]), "must reach the capture, not fail during setup")
	require.Equal(t, types.ParseStatusFailed, u.knowledge.ParseStatus)
	require.Zero(t, u.chunks.writes, "no chunk exists without its saved first parse")
}
