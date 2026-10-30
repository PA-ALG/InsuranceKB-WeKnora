// S11b acceptance (protected, written by Claude): Office structure from upstream sourceloc units
// (Spec docs/design/slices/S11b-Office结构采集与页文本.md §2).
//
// Every input is a synthetic Office package built in this file; no business material is used.
// RED until S11b adds package ooxml.
package ooxml_test

import (
	"archive/zip"
	"bytes"
	"compress/flate"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
	"github.com/xuri/excelize/v2"

	"github.com/Tencent/WeKnora/internal/enterprise/capture/ooxml"
)

func sha(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

func intp(v int) *int { return &v }

type part struct {
	name string
	body []byte
}

func pkg(t *testing.T, parts ...part) []byte {
	t.Helper()
	var buf bytes.Buffer
	w := zip.NewWriter(&buf)
	w.RegisterCompressor(zip.Deflate, func(out io.Writer) (io.WriteCloser, error) {
		return flate.NewWriter(out, flate.BestSpeed)
	})
	for _, p := range parts {
		f, err := w.Create(p.name)
		require.NoError(t, err)
		_, err = f.Write(p.body)
		require.NoError(t, err)
	}
	require.NoError(t, w.Close())
	return buf.Bytes()
}

const (
	nsP = `xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"`
	nsA = `xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"`
	nsR = `xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"`
)

// slideXML renders one slide whose text shapes hold the given paragraphs.
func slideXML(paragraphs ...string) []byte {
	var b strings.Builder
	fmt.Fprintf(&b, `<?xml version="1.0" encoding="UTF-8"?><p:sld %s %s><p:cSld><p:spTree>`, nsP, nsA)
	for i, text := range paragraphs {
		fmt.Fprintf(&b, `<p:sp><p:nvSpPr><p:cNvPr id="%d" name="t"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>%s</a:t></a:r></a:p>`+
			`</p:txBody></p:sp>`, i+2, text)
	}
	b.WriteString(`</p:spTree></p:cSld></p:sld>`)
	return []byte(b.String())
}

func rels(targets map[string]string, types map[string]string) []byte {
	var b strings.Builder
	b.WriteString(`<?xml version="1.0" encoding="UTF-8"?>` +
		`<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">`)
	for _, id := range []string{"rId1", "rId2", "rId3", "rId4"} {
		if target, ok := targets[id]; ok {
			fmt.Fprintf(&b, `<Relationship Id="%s" Type="%s" Target="%s"/>`, id, types[id], target)
		}
	}
	b.WriteString(`</Relationships>`)
	return []byte(b.String())
}

const slideRel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
const notesRel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"

// deck: presentation order is slide3.xml, slide1.xml, slide2.xml (not file-name order).
// The second slide in order has no text; the first has two shapes and a speaker note.
func deck(t *testing.T) []byte {
	t.Helper()
	presentation := fmt.Sprintf(`<?xml version="1.0" encoding="UTF-8"?><p:presentation %s %s><p:sldIdLst>`+
		`<p:sldId id="256" r:id="rId1"/><p:sldId id="257" r:id="rId2"/><p:sldId id="258" r:id="rId3"/>`+
		`</p:sldIdLst></p:presentation>`, nsP, nsR)
	return pkg(t,
		part{"ppt/presentation.xml", []byte(presentation)},
		part{"ppt/_rels/presentation.xml.rels", rels(
			map[string]string{"rId1": "slides/slide3.xml", "rId2": "slides/slide1.xml", "rId3": "slides/slide2.xml"},
			map[string]string{"rId1": slideRel, "rId2": slideRel, "rId3": slideRel})},
		part{"ppt/slides/slide3.xml", slideXML("产品亮点", "保障𠮷全面")},
		part{"ppt/slides/_rels/slide3.xml.rels", rels(
			map[string]string{"rId1": "../notesSlides/notesSlide1.xml"}, map[string]string{"rId1": notesRel})},
		part{"ppt/notesSlides/notesSlide1.xml", slideXML("讲解要点")},
		part{"ppt/slides/slide1.xml", slideXML()},
		part{"ppt/slides/slide2.xml", slideXML("适合人群")},
	)
}

func slideAt(n int) ooxml.Locator { return ooxml.Locator{Kind: "PPTX_SHAPE", Slide: intp(n)} }

func requireCode(t *testing.T, err error, want string) *ooxml.Error {
	t.Helper()
	var failure *ooxml.Error
	require.True(t, errors.As(err, &failure), "want *ooxml.Error, got %v", err)
	require.Equal(t, want, failure.Code)
	return failure
}

func TestAPresentationBecomesOnePagePerSlideInPresentationOrder(t *testing.T) {
	data := deck(t)
	s, err := ooxml.Extract("PPTX", data)
	require.NoError(t, err)
	require.Equal(t, "enterprise-ooxml-structure.v1", s.Contract)
	require.Equal(t, "enterprise.ooxml.sourceloc.v1", s.Extractor)
	require.Equal(t, "pptx", s.Format)
	require.Equal(t, sha(data), s.SourceSHA256)
	require.Equal(t, sha([]byte(s.Extractor)), s.ParserIdentitySHA256)

	first := "产品亮点\n\n保障𠮷全面\n\n讲解要点"
	require.Equal(t, []ooxml.Page{
		{Number: 1, Text: first, TextSHA256: sha([]byte(first)), Blocks: []ooxml.Block{
			{ID: "s1/p1", Start: 0, End: 4, Locator: slideAt(1)},
			{ID: "s1/p2", Start: 6, End: 11, Locator: slideAt(1)},
			{ID: "s1/p3", Start: 13, End: 17, Locator: slideAt(1)},
		}},
		{Number: 2, Text: "", TextSHA256: sha(nil), Blocks: []ooxml.Block{}},
		{Number: 3, Text: "适合人群", TextSHA256: sha([]byte("适合人群")), Blocks: []ooxml.Block{
			{ID: "s3/p1", Start: 0, End: 4, Locator: slideAt(3)},
		}},
	}, s.Pages, "a text-less slide keeps its page; speaker notes follow the slide's own paragraphs")
}

func TestAWordDocumentIsOnePageWithOneBlockPerParagraphOrTable(t *testing.T) {
	body := `<w:p><w:r><w:t>第一条</w:t></w:r></w:p>` +
		`<w:tbl><w:tr><w:tc><w:p><w:r><w:t>A1</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>B1</w:t></w:r></w:p></w:tc></w:tr>` +
		`<w:tr><w:tc><w:p><w:r><w:t>A2</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>B2</w:t></w:r></w:p></w:tc></w:tr></w:tbl>` +
		`<w:p><w:r><w:t>第二条</w:t></w:r></w:p>`
	doc := `<?xml version="1.0" encoding="UTF-8"?>` +
		`<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>` +
		body + `</w:body></w:document>`
	s, err := ooxml.Extract("docx", pkg(t, part{"word/document.xml", []byte(doc)}))
	require.NoError(t, err)
	text := "第一条\n\nA1 B1\nA2 B2\n\n第二条"
	require.Equal(t, []ooxml.Page{{Number: 1, Text: text, TextSHA256: sha([]byte(text)), Blocks: []ooxml.Block{
		{ID: "b0", Start: 0, End: 3, Locator: ooxml.Locator{Kind: "DOCX_BLOCK", BlockIndex: intp(0)}},
		{ID: "b1", Start: 5, End: 16, Locator: ooxml.Locator{Kind: "DOCX_BLOCK", BlockIndex: intp(1)}},
		{ID: "b2", Start: 18, End: 21, Locator: ooxml.Locator{Kind: "DOCX_BLOCK", BlockIndex: intp(2)}},
	}}}, s.Pages, "a table is one block whose rows are joined by a newline")
}

func workbook(t *testing.T) []byte {
	t.Helper()
	f := excelize.NewFile()
	defer func() { _ = f.Close() }()
	require.NoError(t, f.SetSheetName("Sheet1", "费率"))
	require.NoError(t, f.SetCellValue("费率", "A1", "年龄"))
	require.NoError(t, f.SetCellValue("费率", "B1", "保费"))
	require.NoError(t, f.SetCellValue("费率", "A3", "30"))
	require.NoError(t, f.SetCellValue("费率", "B3", "1200"))
	_, err := f.NewSheet("空表")
	require.NoError(t, err)
	_, err = f.NewSheet("说明")
	require.NoError(t, err)
	require.NoError(t, f.SetCellValue("说明", "C2", "以保单载明为准"))
	buf, err := f.WriteToBuffer()
	require.NoError(t, err)
	return buf.Bytes()
}

func rowAt(sheet string, row int) ooxml.Locator {
	return ooxml.Locator{Kind: "XLSX_CELL_RANGE", Sheet: sheet, CellRange: fmt.Sprintf("A%d:XFD%d", row, row)}
}

func TestAWorkbookIsOnePagePerSheetWithOneBlockPerRow(t *testing.T) {
	s, err := ooxml.Extract(".xlsx", workbook(t))
	require.NoError(t, err)
	first := "年龄 保费\n\n30 1200"
	require.Equal(t, []ooxml.Page{
		{Number: 1, Text: first, TextSHA256: sha([]byte(first)), Blocks: []ooxml.Block{
			{ID: "x1/r1", Start: 0, End: 5, Locator: rowAt("费率", 1)},
			{ID: "x1/r3", Start: 7, End: 14, Locator: rowAt("费率", 3)},
		}},
		{Number: 2, Text: "", TextSHA256: sha(nil), Blocks: []ooxml.Block{}},
		{Number: 3, Text: "以保单载明为准", TextSHA256: sha([]byte("以保单载明为准")), Blocks: []ooxml.Block{
			{ID: "x3/r2", Start: 0, End: 7, Locator: rowAt("说明", 2)},
		}},
	}, s.Pages, "an empty sheet keeps its page")
}

func TestExtractionIsDeterministicAndRoundTripsThroughTheCanonicalEncoding(t *testing.T) {
	for name, data := range map[string][]byte{"pptx": deck(t), "xlsx": workbook(t)} {
		a, err := ooxml.Extract(name, data)
		require.NoError(t, err)
		b, err := ooxml.Extract(name, data)
		require.NoError(t, err)
		ea, err := ooxml.Encode(a)
		require.NoError(t, err)
		eb, err := ooxml.Encode(b)
		require.NoError(t, err)
		require.Equal(t, ea, eb, name)
		decoded, err := ooxml.Decode(ea)
		require.NoError(t, err, name)
		again, err := ooxml.Encode(decoded)
		require.NoError(t, err)
		require.Equal(t, ea, again, name)
		require.NotContains(t, string(ea), "\\u003c", "HTML is not escaped")
		require.False(t, bytes.HasSuffix(ea, []byte("\n")))
	}
}

func TestDecodeIsStrict(t *testing.T) {
	encoded, err := ooxml.Encode(mustExtract(t, "pptx", deck(t)))
	require.NoError(t, err)
	for name, data := range map[string][]byte{
		"unknown field":  bytes.Replace(encoded, []byte(`"contract":`), []byte(`"extra":1,"contract":`), 1),
		"trailing data":  append(append([]byte{}, encoded...), []byte(" {}")...),
		"wrong contract": bytes.Replace(encoded, []byte(`enterprise-ooxml-structure.v1`), []byte(`x`), 1),
		"page digest":    bytes.Replace(encoded, []byte(`适合人群"`), []byte(`适合人君"`), 1),
		"not json":       []byte("pptx"),
	} {
		_, err := ooxml.Decode(data)
		require.Error(t, err, name)
	}
}

func mustExtract(t *testing.T, fileType string, data []byte) *ooxml.Structure {
	t.Helper()
	s, err := ooxml.Extract(fileType, data)
	require.NoError(t, err)
	return s
}

func TestOnlyPresentationsDocumentsAndWorkbooksAreSupported(t *testing.T) {
	for _, fileType := range []string{"pptx", ".PPTX", "docx", "xlsx"} {
		require.True(t, ooxml.Supports(fileType), fileType)
	}
	for _, fileType := range []string{"pdf", "ppt", "doc", "xls", "pptm", "csv", "epub", "odp", ""} {
		require.False(t, ooxml.Supports(fileType), fileType)
		_, err := ooxml.Extract(fileType, deck(t))
		requireCode(t, err, "OFFICE_UNSUPPORTED")
	}
}

func TestUnsafeOrBrokenPackagesFailWithTypedCodes(t *testing.T) {
	ole := append([]byte{0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1}, bytes.Repeat([]byte{0}, 504)...)
	_, err := ooxml.Extract("pptx", ole)
	requireCode(t, err, "OFFICE_UNSUPPORTED")

	_, err = ooxml.Extract("pptx", []byte("not a zip package"))
	requireCode(t, err, "OFFICE_MALFORMED")

	_, err = ooxml.Extract("pptx", pkg(t, part{"ppt/slides/slide1.xml", slideXML("文字")}))
	requireCode(t, err, "OFFICE_MALFORMED")

	dtd := []byte(`<?xml version="1.0"?><!DOCTYPE p:sld [<!ENTITY secret "机密样本文字">]>` +
		string(slideXML("&secret;"))[len(`<?xml version="1.0" encoding="UTF-8"?>`):])
	failure := requireCode(t, mustFail(t, withSlide(t, dtd)), "OFFICE_MALFORMED")
	require.NotContains(t, failure.Detail, "机密样本文字", "details never carry document text")

	_, err = ooxml.Extract("pptx", withSlide(t, slideXML()))
	requireCode(t, err, "OFFICE_EMPTY")
}

func withSlide(t *testing.T, slide []byte) []byte {
	t.Helper()
	presentation := fmt.Sprintf(`<?xml version="1.0" encoding="UTF-8"?><p:presentation %s %s><p:sldIdLst>`+
		`<p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>`, nsP, nsR)
	return pkg(t,
		part{"ppt/presentation.xml", []byte(presentation)},
		part{"ppt/_rels/presentation.xml.rels", rels(
			map[string]string{"rId1": "slides/slide1.xml"}, map[string]string{"rId1": slideRel})},
		part{"ppt/slides/slide1.xml", slide},
	)
}

func mustFail(t *testing.T, data []byte) error {
	t.Helper()
	_, err := ooxml.Extract("pptx", data)
	require.Error(t, err)
	return err
}

func TestPackageLimitsCountRealBytes(t *testing.T) {
	valid := deck(t)
	reader, err := zip.NewReader(bytes.NewReader(valid), int64(len(valid)))
	require.NoError(t, err)
	base := make([]part, 0, len(reader.File))
	for _, f := range reader.File {
		rc, err := f.Open()
		require.NoError(t, err)
		body, err := io.ReadAll(rc)
		require.NoError(t, err)
		require.NoError(t, rc.Close())
		base = append(base, part{f.Name, body})
	}

	many := append([]part{}, base...)
	for i := len(many); i <= 10_000; i++ {
		many = append(many, part{fmt.Sprintf("ppt/media/p%05d.bin", i), []byte{1}})
	}
	_, err = ooxml.Extract("pptx", pkg(t, many...))
	requireCode(t, err, "OFFICE_TOO_LARGE")

	bigXML := append(append([]part{}, base...), part{"ppt/big.xml", bytes.Repeat([]byte(" "), 64<<20+1)})
	_, err = ooxml.Extract("pptx", pkg(t, bigXML...))
	requireCode(t, err, "OFFICE_TOO_LARGE")

	media := append([]part{}, base...)
	chunk := make([]byte, 60<<20)
	for i := 0; i < 9; i++ {
		media = append(media, part{fmt.Sprintf("ppt/media/m%d.bin", i), chunk})
	}
	_, err = ooxml.Extract("pptx", pkg(t, media...))
	requireCode(t, err, "OFFICE_TOO_LARGE")
}
