// S11b acceptance (protected, written by Claude): an Office structure is sealed in the existing
// capture record and read back as source pages (Spec docs/design/slices/S11b-Office结构采集与页文本.md §3).
//
// The deck is synthetic and built in this file. RED until S11b adds capture.Office and the Office
// branch of the native validation.
package capture_test

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/capture"
	"github.com/Tencent/WeKnora/internal/enterprise/capture/ooxml"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
)

func shaHex(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

// officeDeck: two slides in presentation order, each with text.
func officeDeck(t *testing.T) []byte {
	t.Helper()
	slide := func(texts ...string) string {
		body := ""
		for i, text := range texts {
			body += fmt.Sprintf(`<p:sp><p:nvSpPr><p:cNvPr id="%d" name="t"/></p:nvSpPr><p:txBody><a:p><a:r>`+
				`<a:t>%s</a:t></a:r></a:p></p:txBody></p:sp>`, i+2, text)
		}
		return `<?xml version="1.0" encoding="UTF-8"?><p:sld ` +
			`xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" ` +
			`xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>` +
			body + `</p:spTree></p:cSld></p:sld>`
	}
	const rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
	parts := []struct{ name, body string }{
		{"ppt/presentation.xml", `<?xml version="1.0" encoding="UTF-8"?><p:presentation ` +
			`xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" ` +
			`xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst>` +
			`<p:sldId id="256" r:id="rId1"/><p:sldId id="257" r:id="rId2"/></p:sldIdLst></p:presentation>`},
		{"ppt/_rels/presentation.xml.rels", `<?xml version="1.0" encoding="UTF-8"?>` +
			`<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
			`<Relationship Id="rId1" Type="` + rel + `" Target="slides/slide1.xml"/>` +
			`<Relationship Id="rId2" Type="` + rel + `" Target="slides/slide2.xml"/></Relationships>`},
		{"ppt/slides/slide1.xml", slide("产品亮点", "保障全面")},
		{"ppt/slides/slide2.xml", slide("适合人群")},
	}
	var buf bytes.Buffer
	w := zip.NewWriter(&buf)
	for _, p := range parts {
		f, err := w.Create(p.name)
		require.NoError(t, err)
		_, err = f.Write([]byte(p.body))
		require.NoError(t, err)
	}
	require.NoError(t, w.Close())
	return buf.Bytes()
}

func officeIdentity(data []byte) capture.Identity {
	return capture.Identity{TenantID: 7, RawKBID: "raw-1", KnowledgeID: "k-office", ParseAttempt: 3,
		SourceSHA256: shaHex(data)}
}

func TestAnOfficeCaptureIsSealedAndReadBackAsSourcePages(t *testing.T) {
	data := officeDeck(t)
	result, chunks, err := capture.Office("pptx", data)
	require.NoError(t, err)
	require.Equal(t, "产品亮点\n\n保障全面\n\n适合人群", result.MarkdownContent, "pages joined by a blank line")
	require.NotNil(t, result.NativeStructure)
	require.Equal(t, "enterprise-ooxml-structure.v1", result.NativeStructure.SchemaVersion)
	require.Equal(t, shaHex(data), result.NativeStructure.SourceSHA256)
	require.Len(t, chunks, 2, "one range per non-empty page")

	id := officeIdentity(data)
	store := capture.NewStore(t.TempDir(), testKeys())
	require.NoError(t, store.Save(id, result, chunks, nil))
	require.NoError(t, store.Save(id, result, chunks, nil), "saving the same capture again is idempotent")

	record, err := store.Read(id)
	require.NoError(t, err)
	require.Equal(t, shaHex([]byte(ooxml.ExtractorIdentity)), record.ParserIdentitySHA256)

	artifact := &source.Artifact{
		KnowledgeID: id.KnowledgeID, ParseAttempt: id.ParseAttempt, FileName: "培训材料.pptx",
		FileSHA256: id.SourceSHA256, ParserIdentitySHA256: record.ParserIdentitySHA256,
		Markdown: record.Markdown, NativeJSON: record.Native.SanitizedJSON,
	}
	load := source.ArtifactStoreFunc(func(context.Context, source.Scope, string, int64) (*source.Artifact, error) {
		return artifact, nil
	})
	set, err := source.NewService(load).Pages(context.Background(), source.Scope{TenantID: 7, SpaceID: "s"}, id.KnowledgeID, 3)
	require.NoError(t, err)
	data2, err := json.Marshal(set.Pages)
	require.NoError(t, err)
	var pages []struct {
		Number int    `json:"page_number"`
		Text   string `json:"text"`
		Blocks []struct {
			ID      string         `json:"block_id"`
			Locator map[string]any `json:"locator"`
		} `json:"blocks"`
	}
	require.NoError(t, json.Unmarshal(data2, &pages))
	require.Len(t, pages, 2)
	require.Equal(t, "适合人群", pages[1].Text)
	require.Equal(t, "s2/p1", pages[1].Blocks[0].ID)
	require.Equal(t, map[string]any{"kind": "PPTX_SHAPE", "slide": float64(2)}, pages[1].Blocks[0].Locator)
}

func TestAnOfficeCaptureMustBelongToItsSourceAndText(t *testing.T) {
	data := officeDeck(t)
	result, chunks, err := capture.Office("pptx", data)
	require.NoError(t, err)
	store := capture.NewStore(t.TempDir(), testKeys())

	other := officeIdentity(data)
	other.SourceSHA256 = shaHex([]byte("another file"))
	requireUnavailable(t, store.Save(other, result, chunks, nil))

	rewritten := *result
	rewritten.MarkdownContent = "产品亮点\n\n保障全面\n\n适合人君"
	requireUnavailable(t, store.Save(officeIdentity(data), &rewritten, chunks, nil))

	native := *result.NativeStructure
	native.SanitizedJSON = bytes.Replace(native.SanitizedJSON, []byte(`"contract":`), []byte(`"contract" :`), 1)
	native.SanitizedSHA256 = shaHex(native.SanitizedJSON)
	native.RawSHA256 = native.SanitizedSHA256
	reencoded := *result
	reencoded.NativeStructure = &native
	requireUnavailable(t, store.Save(officeIdentity(data), &reencoded, chunks, nil))

	withImages := *result
	withImages.ImageRefs = []types.ImageRef{{Filename: "x.png"}}
	requireUnavailable(t, store.Save(officeIdentity(data), &withImages, chunks, nil))
}

func TestAnUnreadableOfficeFileReturnsItsTypedCode(t *testing.T) {
	_, _, err := capture.Office("pptx", []byte("not a zip package"))
	var failure *ooxml.Error
	require.True(t, errors.As(err, &failure))
	require.Equal(t, "OFFICE_MALFORMED", failure.Code)
}
