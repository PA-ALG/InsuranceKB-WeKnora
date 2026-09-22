package service

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/config"
	werrors "github.com/Tencent/WeKnora/internal/errors"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

// References enter via JSON so these tests compile against the pre-change DTO.
// Before implementation the reference is ignored and the real convert calls its
// injected DocReader, which is the behavioral RED rather than a missing symbol.
func docreaderRecoveryFixture(t *testing.T) (*knowledgeService, *types.Knowledge, *types.KnowledgeBase, types.DocumentProcessPayload, *firstParseReader, g3FirstParseIdentity, map[string]any) {
	t.Helper()
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	store := NewG3FirstParseStore(sourceReuseTestCodec830G3(t))
	native := firstParseNative(t, "旧解析原文\r\n", "保留物理页定位")
	id := g3FirstParseIdentity{TenantID: 17, RawKBID: "raw", KnowledgeID: "knowledge", ParseAttempt: 1, SourceSHA256: testSHA256830G2("pdf")}
	require.NoError(t, store.save(id, native, []types.ParsedChunk{{Seq: 0, Content: native.MarkdownContent, Start: 0, End: len([]rune(native.MarkdownContent))}}))
	old, err := store.reuse.readFirstParse(id)
	require.NoError(t, err)
	ref := map[string]any{"origin_parse_attempt": 1, "origin_processing_attempt": 1, "source_sha256": id.SourceSHA256, "artifact_sha256": g3FirstParseRecordSHA(old)}
	reader := &firstParseReader{result: firstParseNative(t, "不应该重新调用解析器")}
	k := &types.Knowledge{ID: id.KnowledgeID, TenantID: id.TenantID, KnowledgeBaseID: id.RawKBID, FileType: "pdf", FileName: "source.pdf", FilePath: "fixture.pdf", FileSHA256: id.SourceSHA256, CurrentParseAttempt: 2}
	kb := &types.KnowledgeBase{ID: id.RawKBID, ChunkingConfig: types.ChunkingConfig{ChunkSize: 40, ChunkOverlap: 0}}
	s := &knowledgeService{config: &config.Config{G3PlatformProcessing: &config.G3PlatformProcessingConfig{Enabled: true, TenantID: 17, SpaceID: "space", RawKBID: "raw", WikiKBID: "wiki"}}, firstParse: store, fileSvc: &revisionSourceFileServiceStub{data: []byte("pdf")}, documentReader: reader}
	journal, spans := newKnowledgeDispatchJournalTest(t)
	stamp := time.Unix(1700000000, 0)
	seedDispatchSpan(t, spans, types.KnowledgeProcessingSpan{KnowledgeID: k.ID, Attempt: 1, SpanID: "origin-root", Name: "root", Kind: types.SpanKindRoot, Status: types.SpanStatusFailed, StartedAt: &stamp, FinishedAt: &stamp})
	for _, stage := range []string{types.StageDocReader, types.StageChunking, types.StageEmbedding} {
		status, code := types.SpanStatusDone, ""
		if stage == types.StageEmbedding {
			status, code = types.SpanStatusFailed, werrors.ErrCodeEmbeddingRateLimit
		}
		seedDispatchSpan(t, spans, types.KnowledgeProcessingSpan{KnowledgeID: k.ID, Attempt: 1, SpanID: stage, ParentSpanID: "origin-root", Name: stage, Kind: types.SpanKindStage, Status: status, ErrorCode: code, StartedAt: &stamp, FinishedAt: &stamp})
	}
	_, err = journal.EnsureEnabled(context.Background(), dispatchTestScope(), k.ID, 1, 1)
	require.NoError(t, err)
	s.spanTracker = NewSpanTracker(spans, nil)
	s.repo = &firstParseKnowledgeRepo{knowledge: k}
	p := types.DocumentProcessPayload{TenantID: 17, KnowledgeID: k.ID, KnowledgeBaseID: kb.ID, FileType: "pdf", FilePath: k.FilePath, FileName: k.FileName, Attempt: 2, ParseAttempt: 2, Revision: newRevisionBinding(2, k.FileSHA256, kb, ResolveProcessConfig(kb, nil), "pdf")}
	return s, k, kb, p, reader, id, ref
}

func recoveryPayload(t *testing.T, p types.DocumentProcessPayload, ref map[string]any) types.DocumentProcessPayload {
	t.Helper()
	b, err := json.Marshal(p)
	require.NoError(t, err)
	var values map[string]any
	require.NoError(t, json.Unmarshal(b, &values))
	values["docreader_reuse"] = ref
	b, err = json.Marshal(values)
	require.NoError(t, err)
	require.NoError(t, json.Unmarshal(b, &p))
	return p
}

func TestG3DocReaderRecoveryActuallyBypassesParserAndKeepsOldArtifact(t *testing.T) {
	s, k, kb, p, reader, id, ref := docreaderRecoveryFixture(t)
	key, err := g3FirstParseKey(id)
	require.NoError(t, err)
	path := filepath.Join(s.firstParse.reuse.root, key+".json")
	before, err := os.ReadFile(path)
	require.NoError(t, err)
	old, err := s.firstParse.reuse.readFirstParse(id)
	require.NoError(t, err)
	p = recoveryPayload(t, p, ref)
	got, err := s.convert(context.Background(), p, kb, k, ResolveProcessConfig(kb, nil), true)
	require.NoError(t, err)
	require.Empty(t, reader.requests, "a cache hit must bypass the actual DocReader")
	require.Equal(t, old.Markdown, got.MarkdownContent)
	require.Equal(t, old.Native, got.NativeStructure)
	require.Equal(t, old.ParserIdentitySHA256, p.Revision.ParserIdentity.DocReader)
	require.EqualValues(t, 2, p.Revision.ParseAttempt, "reuse must keep the NEW write generation")
	after, err := os.ReadFile(path)
	require.NoError(t, err)
	require.Equal(t, before, after, "old authenticated artifact bytes must not change")
}

func TestG3DocReaderRecoveryRejectsInvalidReferenceWithoutParserFallback(t *testing.T) {
	for _, name := range []string{"same_generation", "superseded_generation", "foreign_tenant", "foreign_kb", "foreign_knowledge", "changed_pdf", "bad_digest", "missing_artifact", "bad_mac", "non_g3"} {
		t.Run(name, func(t *testing.T) {
			s, k, kb, p, reader, id, ref := docreaderRecoveryFixture(t)
			key, err := g3FirstParseKey(id)
			require.NoError(t, err)
			path := filepath.Join(s.firstParse.reuse.root, key+".json")
			switch name {
			case "same_generation":
				ref["origin_parse_attempt"] = 2
			case "superseded_generation":
				k.CurrentParseAttempt = 3
			case "foreign_tenant":
				p.TenantID++
			case "foreign_kb":
				p.KnowledgeBaseID = "other"
			case "foreign_knowledge":
				p.KnowledgeID = "other"
			case "changed_pdf":
				s.fileSvc = &revisionSourceFileServiceStub{data: []byte("changed")}
			case "bad_digest":
				ref["artifact_sha256"] = testSHA256830G2("wrong")
			case "missing_artifact":
				require.NoError(t, os.Remove(path))
			case "bad_mac":
				require.NoError(t, os.WriteFile(path, []byte("tampered"), 0600))
			case "non_g3":
				s.config.G3PlatformProcessing.Enabled = false
			}
			p = recoveryPayload(t, p, ref)
			_, err = s.convert(context.Background(), p, kb, k, ResolveProcessConfig(kb, nil), true)
			require.Error(t, err)
			require.Empty(t, reader.requests)
		})
	}
}

func TestG3DocReaderRecoveryOriginSurvivesRecordSerialization(t *testing.T) {
	s, _, _, _, _, id, ref := docreaderRecoveryFixture(t)
	old, err := s.firstParse.reuse.readFirstParse(id)
	require.NoError(t, err)
	b, err := json.Marshal(old)
	require.NoError(t, err)
	var fields map[string]json.RawMessage
	require.NoError(t, json.Unmarshal(b, &fields))
	require.NotContains(t, fields, "origin_docreader")
	oldDigest := g3FirstParseRecordSHA(old)
	var unchanged g3FirstParseRecord
	require.NoError(t, json.Unmarshal(b, &unchanged))
	require.Equal(t, oldDigest, g3FirstParseRecordSHA(&unchanged))
	id.ParseAttempt = 2
	fields["identity"], err = json.Marshal(id)
	require.NoError(t, err)
	fields["origin_docreader"], err = json.Marshal(ref)
	require.NoError(t, err)
	b, err = json.Marshal(fields)
	require.NoError(t, err)
	var next g3FirstParseRecord
	require.NoError(t, json.Unmarshal(b, &next))
	require.NoError(t, validateG3FirstParse(&next, id))
	b, err = json.Marshal(next)
	require.NoError(t, err)
	var saved map[string]json.RawMessage
	require.NoError(t, json.Unmarshal(b, &saved))
	require.JSONEq(t, string(fields["origin_docreader"]), string(saved["origin_docreader"]))
	key, err := g3FirstParseKey(id)
	require.NoError(t, err)
	require.NoError(t, s.firstParse.reuse.writeFirstParseArtifact(filepath.Join(s.firstParse.reuse.root, key+".json"), key, b))
	reopened, err := s.firstParse.reuse.readFirstParse(id)
	require.NoError(t, err)
	require.Equal(t, g3FirstParseRecordSHA(&next), g3FirstParseRecordSHA(reopened))
}

var errRecoveryAllocationProbe = errors.New("stop after real generation allocation")

type docreaderAllocationProbe struct {
	*firstParseKnowledgeRepo
	allocations int
	pinned      bool
}

func (r *docreaderAllocationProbe) HasPinnedRevisionSource(context.Context, uint64, string) (bool, error) {
	return r.pinned, nil
}
func (r *docreaderAllocationProbe) AllocateParseAttempt(context.Context, string, string, string) (int64, error) {
	r.allocations++
	return 0, errRecoveryAllocationProbe
}
func (r *docreaderAllocationProbe) CommitDirectRevision(context.Context, string, types.RevisionCommitBinding) (*types.KnowledgeRevision, error) {
	panic("not reached")
}
func (r *docreaderAllocationProbe) FinalizeSubtaskRevision(context.Context, string, types.RevisionCommitBinding) (int, bool, error) {
	panic("not reached")
}
func TestG3DocReaderRecoveryReparseStillAllocatesNewFenceAndHonorsPin(t *testing.T) {
	for _, pinned := range []bool{false, true} {
		t.Run(map[bool]string{false: "new_generation", true: "pinned"}[pinned], func(t *testing.T) {
			s, k, kb, _, _, _, _ := docreaderRecoveryFixture(t)
			k.CurrentParseAttempt = 1
			k.ParseStatus = types.ParseStatusFailed
			repo := &docreaderAllocationProbe{firstParseKnowledgeRepo: &firstParseKnowledgeRepo{knowledge: k}, pinned: pinned}
			s.repo = repo
			s.kbService = &createKnowledgeFileKBServiceStub{kb: kb}
			files := s.fileSvc.(*revisionSourceFileServiceStub)
			ctx := context.WithValue(context.Background(), types.TenantIDContextKey, uint64(17))
			_, err := s.ReparseKnowledge(ctx, k.ID, nil)
			if pinned {
				require.ErrorIs(t, err, ErrKnowledgeRevisionSourcePinned)
				require.Zero(t, repo.allocations)
				require.Zero(t, files.calls)
			} else {
				require.ErrorIs(t, err, errRecoveryAllocationProbe)
				require.Equal(t, 1, repo.allocations)
				require.Equal(t, 1, files.calls, "must validate cached source before allocation, not just take full reparse")
			}
		})
	}
}
