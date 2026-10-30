package service

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/config"
	"github.com/Tencent/WeKnora/internal/enterprise/capture"
	"github.com/Tencent/WeKnora/internal/types"
)

// officeTestDeck is a synthetic one-slide presentation.
func officeTestDeck(t *testing.T) []byte {
	t.Helper()
	const rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
	parts := map[string]string{
		"ppt/presentation.xml": `<p:presentation ` +
			`xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" ` +
			`xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst>` +
			`<p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>`,
		"ppt/_rels/presentation.xml.rels": `<Relationships ` +
			`xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
			`<Relationship Id="rId1" Type="` + rel + `" Target="slides/slide1.xml"/></Relationships>`,
		"ppt/slides/slide1.xml": `<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" ` +
			`xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody>` +
			`<a:p><a:r><a:t>产品亮点</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>`,
	}
	var buf bytes.Buffer
	w := zip.NewWriter(&buf)
	for _, name := range []string{"ppt/presentation.xml", "ppt/_rels/presentation.xml.rels", "ppt/slides/slide1.xml"} {
		f, err := w.Create(name)
		require.NoError(t, err)
		_, err = f.Write([]byte(parts[name]))
		require.NoError(t, err)
	}
	require.NoError(t, w.Close())
	return buf.Bytes()
}

type officeCaptureCase struct {
	svc       *knowledgeService
	knowledge *types.Knowledge
	payload   types.DocumentProcessPayload
	root      string
	id        capture.Identity
}

func newOfficeCaptureCase(t *testing.T, data []byte) officeCaptureCase {
	t.Helper()
	sum := sha256.Sum256(data)
	digest := hex.EncodeToString(sum[:])
	root := t.TempDir()
	k := &types.Knowledge{ID: "k-office", TenantID: 7, KnowledgeBaseID: "raw-1", CurrentParseAttempt: 3}
	return officeCaptureCase{
		svc: &knowledgeService{
			captureScope: rawKBs{"raw-1": 7},
			firstParse:   &G3FirstParseStore{root: root, keys: captureTestKeys(t)},
		},
		knowledge: k,
		payload: types.DocumentProcessPayload{
			ParseAttempt: 3, Revision: &types.RevisionCommitBinding{ParseAttempt: 3, FileSHA256: digest},
		},
		root: root,
		id: capture.Identity{
			TenantID: 7, RawKBID: "raw-1", KnowledgeID: "k-office", ParseAttempt: 3,
			SourceSHA256: digest,
		},
	}
}

func (c officeCaptureCase) read(t *testing.T) (*capture.Record, error) {
	t.Helper()
	return capture.NewStore(c.root, captureTestKeys(t)).Read(c.id)
}

func TestAnEnterpriseRawOfficeUploadIsCapturedNextToItsParse(t *testing.T) {
	data := officeTestDeck(t)
	c := newOfficeCaptureCase(t, data)
	c.svc.captureOffice(context.Background(), c.knowledge, c.payload, "pptx", data)
	record, err := c.read(t)
	require.NoError(t, err)
	require.Equal(t, "产品亮点", record.Markdown)
	require.Equal(t, "enterprise-ooxml-structure.v1", record.Native.SchemaVersion)
}

func TestAnOfficeCaptureIsOnlyMadeForABoundEnterpriseRawRevision(t *testing.T) {
	data := officeTestDeck(t)
	cases := map[string]func(*officeCaptureCase) string{
		"not an Office type": func(*officeCaptureCase) string { return "pdf" },
		"not a RAW KB": func(c *officeCaptureCase) string {
			c.svc.captureScope = rawKBs{"other": 7}
			return "pptx"
		},
		"another tenant's KB": func(c *officeCaptureCase) string {
			c.svc.captureScope = rawKBs{"raw-1": 8}
			return "pptx"
		},
		"URL import": func(c *officeCaptureCase) string {
			c.payload.URL = "https://example.invalid/a.pptx"
			return "pptx"
		},
		"no revision binding": func(c *officeCaptureCase) string {
			c.payload.Revision = nil
			return "pptx"
		},
		"stale parse attempt": func(c *officeCaptureCase) string {
			c.knowledge.CurrentParseAttempt = 4
			return "pptx"
		},
		"payload attempt differs": func(c *officeCaptureCase) string {
			c.payload.ParseAttempt = 2
			return "pptx"
		},
		"revision names other bytes": func(c *officeCaptureCase) string {
			c.payload.Revision.FileSHA256 = captureTestSHA256("other bytes")
			return "pptx"
		},
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			c := newOfficeCaptureCase(t, data)
			fileType := mutate(&c)
			c.svc.captureOffice(context.Background(), c.knowledge, c.payload, fileType, data)
			_, err := c.read(t)
			require.True(t, errors.Is(err, os.ErrNotExist), "no capture is written: %v", err)
		})
	}
}

func TestAnUnreadableOfficeUploadIsSimplyNotCaptured(t *testing.T) {
	data := []byte("not a zip package")
	c := newOfficeCaptureCase(t, data)
	require.NotPanics(t, func() {
		c.svc.captureOffice(context.Background(), c.knowledge, c.payload, "pptx", data)
	})
	_, err := c.read(t)
	require.True(t, errors.Is(err, os.ErrNotExist))
}

// officeZip packs synthetic parts in the given order.
func officeZip(t *testing.T, names []string, parts map[string]string) []byte {
	t.Helper()
	var buf bytes.Buffer
	w := zip.NewWriter(&buf)
	for _, name := range names {
		f, err := w.Create(name)
		require.NoError(t, err)
		_, err = f.Write([]byte(parts[name]))
		require.NoError(t, err)
	}
	require.NoError(t, w.Close())
	return buf.Bytes()
}

// convertOffice runs the real parse step for one Office upload to the enterprise RAW KB: the original
// bytes come from the file service and the docreader fake returns its own Markdown. It returns the
// knowledge, the parse result and what the capture store holds for this exact revision.
func convertOffice(
	t *testing.T, fileType string, data []byte,
) (*types.Knowledge, *types.ReadResult, *capture.Record, error) {
	t.Helper()
	t.Setenv("LOCAL_STORAGE_BASE_DIR", t.TempDir())
	sum := sha256.Sum256(data)
	digest := hex.EncodeToString(sum[:])
	k := &types.Knowledge{
		ID: "knowledge", TenantID: enterpriseTenant, KnowledgeBaseID: enterpriseRawKB, FileType: fileType,
		FileSHA256: digest, CurrentParseAttempt: 1, ParseStatus: types.ParseStatusProcessing,
	}
	kb := &types.KnowledgeBase{ID: enterpriseRawKB, TenantID: enterpriseTenant, ChunkingConfig: types.ChunkingConfig{
		ParserEngineRules: []types.ParserEngineRule{{FileTypes: []string{"pptx", "docx"}, Engine: "auto"}},
	}}
	reader := &firstParseReader{result: &types.ReadResult{MarkdownContent: "docreader text"}}
	s := &knowledgeService{
		config: &config.Config{}, captureScope: rawKBs{enterpriseRawKB: enterpriseTenant},
		repo: &firstParseKnowledgeRepo{knowledge: k}, tenantService: &firstParseTenantService{},
		documentReader: reader, fileSvc: &revisionSourceFileServiceStub{data: data},
		firstParse: NewG3FirstParseStore(captureTestKeys(t)),
	}
	eff := ResolveProcessConfig(kb, nil)
	payload := types.DocumentProcessPayload{
		FileType: fileType, FileName: "source." + fileType, FilePath: "fixture." + fileType,
		Revision: newRevisionBinding(1, digest, kb, eff, fileType),
	}
	got, err := s.convert(context.Background(), payload, kb, k, eff, true)
	require.NoError(t, err)
	require.Len(t, reader.requests, 1, "the upstream parse runs once, as usual")
	record, readErr := capture.NewStore(capture.DefaultRoot(), captureTestKeys(t)).Read(capture.Identity{
		TenantID: enterpriseTenant, RawKBID: enterpriseRawKB, KnowledgeID: k.ID, ParseAttempt: 1,
		SourceSHA256: digest,
	})
	return k, got, record, readErr
}

func TestThroughConvertAnIncompleteOfficeFileIsParsedButNotCaptured(t *testing.T) {
	k, got, record, err := convertOffice(t, "pptx", officeTestDeck(t))
	require.NoError(t, err, "positive control: a complete deck is captured")
	require.Equal(t, "产品亮点", record.Markdown)
	require.NotEqual(t, types.ParseStatusFailed, k.ParseStatus)
	require.Equal(t, "docreader text", got.MarkdownContent)

	document := `<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>` +
		`<w:p><w:r><w:t>第一段</w:t></w:r></w:p><w:p><w:r><w:t>第二`
	truncated := officeZip(t, []string{"word/document.xml"}, map[string]string{"word/document.xml": document})
	k, got, _, err = convertOffice(t, "docx", truncated)
	require.True(t, errors.Is(err, os.ErrNotExist), "no capture is saved for a valid prefix: %v", err)
	require.NotEqual(t, types.ParseStatusFailed, k.ParseStatus, k.ErrorMessage)
	require.Equal(t, "docreader text", got.MarkdownContent, "the upstream parse is unchanged")
}
