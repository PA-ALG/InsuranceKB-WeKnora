package service

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"unicode/utf8"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
)

func TestEnterpriseCaptureRecognizesUppercasePDF(t *testing.T) {
	k, reader, got := convertOnce(t, convertCase{
		cfg: &config.Config{}, scope: rawKBs{enterpriseRawKB: enterpriseTenant},
		tenant: enterpriseTenant, kb: enterpriseRawKB, file: "PDF",
		result: firstParseNative(t, "条款\r\n责任"),
	})
	require.True(t, captureRequested(reader.requests[0]))
	require.NotEqual(t, types.ParseStatusFailed, k.ParseStatus)
	require.NotNil(t, got)
}

func TestEnterpriseScannedSignalRequiresOriginalCompleteError(t *testing.T) {
	for _, parserError := range []string{
		"page 0 is scanned", "page 01 is scanned", "page -1 is scanned",
		"page 1 is scanned\n", " page 1 is scanned", "page 1 is scanned ",
		"page 1 is scanned\xff", "page \xff1 is scanned", "Page 1 is scanned",
		"page 1 is scanned\x00", "page \x001 is scanned", "\x00", "\xff",
	} {
		t.Run(parserError, func(t *testing.T) {
			u := uploadToEnterpriseRawKB(t, &types.ReadResult{Error: parserError})
			require.NoError(t, u.service.ProcessDocument(context.Background(), u.task))
			require.Equal(t, types.ParseStatusFailed, u.knowledge.ParseStatus)
			require.Zero(t, u.chunks.writes)
			require.Len(t, u.reader.requests, 1)
			require.NotContains(t, u.reader.result.Error, "\x00")
			require.True(t, utf8.ValidString(u.reader.result.Error))
		})
	}
}

func TestFirstParseKeepsHTMLAndLineEndings(t *testing.T) {
	original := "条款😀\r\n<table><tr><td>保险责任</td><td>金额</td></tr></table>\r\n附录"
	u := uploadToEnterpriseRawKB(t, firstParseNative(t, original))
	require.NoError(t, u.service.ProcessDocument(context.Background(), u.task))
	require.NotEqual(t, types.ParseStatusFailed, u.knowledge.ParseStatus, u.knowledge.ErrorMessage)
	a, err := u.artifact(enterpriseScope, 3)
	require.NoError(t, err)
	require.Equal(t, original, a.Markdown)
	for _, c := range u.chunks.written {
		require.Equal(t, string([]rune(original)[c.StartAt:c.EndAt]), c.Content)
	}
}

// captureSpans records stages without a database connection.
type captureSpans struct {
	repository.KnowledgeSpanRepository
	rows []types.KnowledgeProcessingSpan
}

func (s *captureSpans) ListByAttempt(
	_ context.Context, knowledgeID string, attempt int,
) ([]types.KnowledgeProcessingSpan, error) {
	var rows []types.KnowledgeProcessingSpan
	for _, row := range s.rows {
		if row.KnowledgeID == knowledgeID && row.Attempt == attempt {
			rows = append(rows, row)
		}
	}
	return rows, nil
}

func (s *captureSpans) Upsert(_ context.Context, row *types.KnowledgeProcessingSpan) error {
	for i, existing := range s.rows {
		if existing.KnowledgeID == row.KnowledgeID && existing.Attempt == row.Attempt && existing.SpanID == row.SpanID {
			s.rows[i] = *row
			return nil
		}
	}
	s.rows = append(s.rows, *row)
	return nil
}

func (s *captureSpans) LatestAttempt(_ context.Context, knowledgeID string) (int, error) {
	latest := 0
	for _, row := range s.rows {
		if row.KnowledgeID == knowledgeID && row.Attempt > latest {
			latest = row.Attempt
		}
	}
	return latest, nil
}

func TestEnterpriseScannedPDFDoesNotResolveAnEmbeddingModel(t *testing.T) {
	u := uploadToEnterpriseRawKB(t, &types.ReadResult{
		Error: "page 123 is scanned", MarkdownContent: "partial text must not be indexed",
		IsAudio: true, AudioData: []byte("must not be transcribed"),
	})
	kb := u.service.kbService.(*createKnowledgeFileKBServiceStub).kb
	kb.IndexingStrategy.VectorEnabled = true
	kb.EmbeddingModelID = "unused-embedding"
	require.True(t, kb.NeedsEmbeddingModel())
	spans := &captureSpans{}
	u.service.spanTracker = NewSpanTracker(spans, nil)
	require.NoError(t, u.service.ProcessDocument(context.Background(), u.task))
	require.Empty(t, u.chunks.written)
	require.Equal(t, 1, u.chunks.writes)
	var stage *types.KnowledgeProcessingSpan
	for i := range spans.rows {
		if spans.rows[i].Name == types.StageDocReader {
			stage = &spans.rows[i]
		}
	}
	require.NotNil(t, stage)
	require.Equal(t, types.SpanStatusDone, stage.Status)
	require.Equal(t, false, stage.Output["first_parse_saved"])
	require.Equal(t, "scanned_page", stage.Output["not_captured_reason"])
}

func TestEnterpriseCaptureRejectsTextThatWouldChangeDuringSanitization(t *testing.T) {
	for _, invalid := range []struct{ name, text string }{
		{"NUL", "条款\x00责任"}, {"invalid UTF-8", "条款\xff责任"},
	} {
		for _, entry := range []string{"convert", "ProcessDocument"} {
			t.Run(invalid.name+"/"+entry, func(t *testing.T) {
				parsed := firstParseNative(t, invalid.text)
				u := uploadToEnterpriseRawKB(t, parsed)
				var err error
				if entry == "convert" {
					_, err = convertEnterpriseUpload(t, u)
				} else {
					err = u.service.ProcessDocument(context.Background(), u.task)
				}
				require.ErrorContains(t, err, "G3_FIRST_PARSE_ARTIFACT_UNAVAILABLE")
				require.Equal(t, types.ParseStatusFailed, u.knowledge.ParseStatus)
				require.Equal(t, invalid.text, parsed.MarkdownContent, "invalid source text must not be rewritten")
				require.Len(t, u.reader.requests, 1)
				require.Zero(t, u.chunks.writes)
				_, err = u.artifact(enterpriseScope, 3)
				require.ErrorIs(t, err, source.ErrNotCaptured)
				entries, err := os.ReadDir(u.store.root)
				if err == nil {
					require.Empty(t, entries, "no record or temporary capture file may survive")
				} else {
					require.ErrorIs(t, err, os.ErrNotExist)
				}
			})
		}
	}
}

func convertEnterpriseUpload(t *testing.T, u *enterpriseUpload) (*types.ReadResult, error) {
	t.Helper()
	var payload types.DocumentProcessPayload
	require.NoError(t, json.Unmarshal(u.task.Payload(), &payload))
	kb := u.service.kbService.(*createKnowledgeFileKBServiceStub).kb
	return u.service.convert(context.Background(), payload, kb, u.knowledge, ResolveProcessConfig(kb, nil), true)
}

func TestCaptureSanitizesNonBodyFieldsWithoutChangingMarkdown(t *testing.T) {
	original := "条款😀\r\n<table><tr><td>责任</td></tr></table>\r\n附录"
	for _, entry := range []string{"convert", "ProcessDocument"} {
		t.Run(entry, func(t *testing.T) {
			parsed := firstParseNative(t, original)
			parsed.ImageDirPath = "images\x00\xff"
			parsed.Metadata = map[string]string{"pages": "2\x00\xff", "description": "页\x00码\xff"}
			u := uploadToEnterpriseRawKB(t, parsed)
			if entry == "convert" {
				got, err := convertEnterpriseUpload(t, u)
				require.NoError(t, err)
				require.Same(t, parsed, got)
			} else {
				require.NoError(t, u.service.ProcessDocument(context.Background(), u.task))
				a, err := u.artifact(enterpriseScope, 3)
				require.NoError(t, err)
				require.Equal(t, original, a.Markdown)
			}
			require.Equal(t, original, parsed.MarkdownContent)
			require.Equal(t, "images", parsed.ImageDirPath)
			require.Equal(t, map[string]string{"pages": "2", "description": "页码"}, parsed.Metadata)
			require.Len(t, u.reader.requests, 1)
		})
	}
}

func TestCaptureScopeExcludesURLImports(t *testing.T) {
	s := &knowledgeService{config: &config.Config{}, captureScope: rawKBs{enterpriseRawKB: enterpriseTenant}}
	for _, kb := range []string{enterpriseRawKB, "other-kb"} {
		k := &types.Knowledge{TenantID: enterpriseTenant, KnowledgeBaseID: kb}
		for _, p := range []types.DocumentProcessPayload{
			{FileType: "pdf", URL: "https://example.com/source.pdf"},
			{FileType: "pdf", FileURL: "https://example.com/source.pdf"},
		} {
			require.False(t, s.captureFirstParse(k, p), "%s: %+v", kb, p)
		}
	}
}

func TestEnterpriseCaptureDiscardsUploadParserRulesAndOverrides(t *testing.T) {
	u := uploadToEnterpriseRawKB(t, firstParseNative(t, "保险条款\r\n责任"))
	require.NoError(t, u.knowledge.SetProcessOverrides(&types.KnowledgeProcessOverrides{
		ParserEngineRules: []types.ParserEngineRule{{FileTypes: []string{"pdf"}, Engine: "mineru"}},
		ParserEngineOverrides: map[string]string{
			"mineru_endpoint": "http://127.0.0.1:9/ignored", "pdf_native_structure_capture": "ignored",
		},
	}))
	require.NoError(t, u.service.ProcessDocument(context.Background(), u.task))
	require.Len(t, u.reader.requests, 1)
	require.True(t, captureRequested(u.reader.requests[0]))
	require.NotEqual(t, types.ParseStatusFailed, u.knowledge.ParseStatus)
	_, err := u.artifact(enterpriseScope, 3)
	require.NoError(t, err)
}
