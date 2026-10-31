package releasestore

// S11d acceptance (protected, written by Claude): Office evidence is verified against the one block
// of the exact captured revision it cites (Spec docs/design/slices/S11d-Office证据回验与引用.md §2.1, §2.2).
//
// Captures are synthetic Office structures read back through source.Service, so pages and blocks are
// exactly what S11b stores. Reuses pageReader, capturedPages, span, submit, refusal, citedRef and
// fileSHA of this package. RED until S11d implements it.

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"strings"
	"testing"
	"unicode/utf8"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/capture/ooxml"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
)

type officeUnit struct {
	text    string
	locator ooxml.Locator
}

func intAt(n int) *int { return &n }

func onSlide(n int) ooxml.Locator { return ooxml.Locator{Kind: "PPTX_SHAPE", Slide: intAt(n)} }

func bodyBlock(n int) ooxml.Locator { return ooxml.Locator{Kind: "DOCX_BLOCK", BlockIndex: intAt(n)} }

func sheetRow(sheet string, r int) ooxml.Locator {
	return ooxml.Locator{Kind: "XLSX_CELL_RANGE", Sheet: sheet, CellRange: fmt.Sprintf("A%d:XFD%d", r, r)}
}

func textSHA(text string) string {
	sum := sha256.Sum256([]byte(text))
	return hex.EncodeToString(sum[:])
}

// officeReader captures a synthetic Office file whose fingerprint is fileSHA: each page is its units
// joined by a blank line, as S11b builds it, read back through source.Service.
func officeReader(t *testing.T, format string, pages ...[]officeUnit) *pageReader {
	t.Helper()
	structure := &ooxml.Structure{
		Contract: ooxml.Contract, Extractor: ooxml.ExtractorIdentity, Format: format,
		ParserIdentitySHA256: textSHA(ooxml.ExtractorIdentity), SourceSHA256: fileSHA,
	}
	for i, units := range pages {
		page := ooxml.Page{Number: i + 1, Blocks: []ooxml.Block{}}
		texts := make([]string, 0, len(units))
		offset := 0
		for j, u := range units {
			if j > 0 {
				offset += 2
			}
			end := offset + utf8.RuneCountInString(u.text)
			page.Blocks = append(page.Blocks, ooxml.Block{
				ID: fmt.Sprintf("p%d/b%d", i+1, j+1), Start: offset, End: end, Locator: u.locator,
			})
			texts = append(texts, u.text)
			offset = end
		}
		page.Text = strings.Join(texts, "\n\n")
		page.TextSHA256 = textSHA(page.Text)
		structure.Pages = append(structure.Pages, page)
	}
	native, err := ooxml.Encode(structure)
	require.NoError(t, err)
	artifact := &source.Artifact{
		KnowledgeID: "k-1", ParseAttempt: 2, FileName: "material." + format, FileSHA256: fileSHA,
		ParserIdentitySHA256: structure.ParserIdentitySHA256, NativeJSON: native,
	}
	store := source.ArtifactStoreFunc(func(context.Context, source.Scope, string, int64) (*source.Artifact, error) {
		return artifact, nil
	})
	scope := source.Scope{TenantID: 7, SpaceID: "space-1"}
	set, err := source.NewService(store).Pages(context.Background(), scope, "k-1", 2)
	require.NoError(t, err)
	return &pageReader{calls: map[string]int{}, set: set}
}

// deck: slide 1 has two paragraphs (one with a non-BMP character), slide 2 one, slide 3 none.
func deck(t *testing.T) *pageReader {
	return officeReader(t, "pptx",
		[]officeUnit{{"产品亮点", onSlide(1)}, {"保障𠮷全面", onSlide(1)}},
		[]officeUnit{{"适合人群", onSlide(2)}},
		[]officeUnit{})
}

// document: one page with body blocks 0 and 2 (block 1 has no text).
func document(t *testing.T) *pageReader {
	return officeReader(t, "docx", []officeUnit{{"第一条 保险责任", bodyBlock(0)}, {"等待期为90日。", bodyBlock(2)}})
}

// workbook: sheet 费率表 with rows 1 and 3, sheet 说明 with row 2.
func workbook(t *testing.T) *pageReader {
	return officeReader(t, "xlsx",
		[]officeUnit{{"年龄\t保费", sheetRow("费率表", 1)}, {"30\t1200", sheetRow("费率表", 3)}},
		[]officeUnit{{"详见条款", sheetRow("说明", 2)}})
}

// office is Office evidence as the Harness serializes it: the block's locator fields, the page and the
// page-text offsets, and null for every other contract key.
func office(locator ooxml.Locator, page, start, end int, quote string) map[string]any {
	fields := map[string]any{
		"kind": locator.Kind, "page": page, "start": start, "end": end, "bbox": nil, "block_index": nil,
		"table_index": nil, "row": nil, "column": nil, "slide": nil, "shape_id": nil, "sheet": nil,
		"cell_range": nil, "chunk_id": nil, "path": nil, "revision_record_id": nil,
	}
	if locator.Slide != nil {
		fields["slide"] = *locator.Slide
	}
	if locator.BlockIndex != nil {
		fields["block_index"] = *locator.BlockIndex
	}
	if locator.Sheet != "" {
		fields["sheet"] = locator.Sheet
	}
	if locator.CellRange != "" {
		fields["cell_range"] = locator.CellRange
	}
	return map[string]any{
		"source_ref": citedRef, "file_sha256": fileSHA, "quote": quote, "access_scope": "space", "match": "EXACT",
		"locator": fields,
	}
}

// with returns a copy of the evidence whose locator has the given keys replaced.
func with(evidence map[string]any, locator map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range evidence {
		out[k] = v
	}
	fields := map[string]any{}
	for k, v := range evidence["locator"].(map[string]any) {
		fields[k] = v
	}
	for k, v := range locator {
		fields[k] = v
	}
	out["locator"] = fields
	return out
}

func TestOfficeEvidencePassesOnItsCapturedBlock(t *testing.T) {
	hashed := office(onSlide(2), 2, 0, 4, "适合人群")
	hashed["quote_sha256"] = release.QuoteDigest("适合人群")
	compact := map[string]any{
		"source_ref": citedRef, "file_sha256": fileSHA, "quote": "产品", "access_scope": "space",
		"locator": map[string]any{"kind": "PPTX_SHAPE", "slide": 1, "page": 1, "start": 0, "end": 2},
	}
	reader := deck(t)
	require.NoError(t, submit(t, reader, "space-1",
		office(onSlide(1), 1, 6, 11, "保障𠮷全面"), office(onSlide(1), 1, 8, 9, "𠮷"), hashed, compact))
	require.Equal(t, map[string]int{"k-1:2": 1}, reader.calls, "each captured revision is read once")
	require.Equal(t, []source.Scope{{TenantID: 7, SpaceID: "space-1"}}, reader.scopes)

	require.NoError(t, submit(t, document(t), "space-1",
		office(bodyBlock(2), 1, 10, 18, "等待期为90日。"), office(bodyBlock(0), 1, 4, 8, "保险责任")))
	require.NoError(t, submit(t, workbook(t), "space-1",
		office(sheetRow("费率表", 3), 1, 7, 14, "30\t1200"), office(sheetRow("说明", 2), 2, 0, 4, "详见条款")))
}

func TestOfficeEvidenceMustBeTheExactSliceOfOneCapturedBlock(t *testing.T) {
	wrongDigest := office(onSlide(2), 2, 0, 4, "适合人群")
	wrongDigest["quote_sha256"] = release.QuoteDigest("适合人")
	otherFile := office(onSlide(2), 2, 0, 4, "适合人群")
	otherFile["file_sha256"] = strings.Repeat("cd", 32)
	absolute := with(office(sheetRow("费率表", 3), 1, 7, 14, "30\t1200"), map[string]any{"cell_range": "$A$3:$XFD$3"})

	deckValid := office(onSlide(2), 2, 0, 4, "适合人群")
	docValid := office(bodyBlock(0), 1, 0, 3, "第一条")
	bookValid := office(sheetRow("说明", 2), 2, 0, 4, "详见条款")
	pdfValid := span(2, 0, 3, "宽限期")
	cases := []struct {
		name     string
		reader   func(*testing.T) *pageReader
		valid    map[string]any
		evidence map[string]any
	}{
		{"one character differs", deck, deckValid, office(onSlide(1), 1, 6, 11, "保障𠮷全心")},
		{"offsets shifted", deck, deckValid, office(onSlide(1), 1, 5, 10, "保障𠮷全面")},
		{"across two blocks", deck, deckValid, office(onSlide(1), 1, 0, 11, "产品亮点\n\n保障𠮷全面")},
		{"into the blank line after a block", deck, deckValid, office(onSlide(1), 1, 3, 5, "点\n")},
		{"slide of another page", deck, deckValid, office(onSlide(2), 1, 6, 11, "保障𠮷全面")},
		{"page beyond the deck", deck, deckValid, office(onSlide(4), 4, 0, 1, "适")},
		{"slide without text", deck, deckValid, office(onSlide(3), 3, 0, 1, "适")},
		{"end beyond the page", deck, deckValid, office(onSlide(2), 2, 0, 5, "适合人群。")},
		{"empty range", deck, deckValid, office(onSlide(2), 2, 2, 2, "人")},
		{"quote digest differs", deck, deckValid, wrongDigest},
		{"file fingerprint differs", deck, deckValid, otherFile},
		{"a PDF span on an Office capture", deck, deckValid, span(1, 6, 11, "保障𠮷全面")},
		{"a locator of another Office format", deck, deckValid, office(bodyBlock(0), 1, 0, 4, "产品亮点")},
		{"block index differs", document, docValid, office(bodyBlock(1), 1, 10, 18, "等待期为90日。")},
		{"sheet differs", workbook, bookValid, office(sheetRow("说明", 3), 1, 7, 14, "30\t1200")},
		{"row differs", workbook, bookValid, office(sheetRow("费率表", 1), 1, 7, 14, "30\t1200")},
		{"an absolute range is another range", workbook, bookValid, absolute},
		{
			"an Office locator on a PDF capture", func(*testing.T) *pageReader { return capturedPages() }, pdfValid,
			office(onSlide(1), 1, 5, 13, "等待期为90日。"),
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			failure := refusal(t, submit(t, c.reader(t), "space-1", c.valid, c.evidence))
			require.Equal(t, release.ErrorEvidenceMismatch, failure.Code, failure.Detail)
			require.True(t, strings.HasPrefix(failure.Detail, "/members/0/payload/evidence/1"), failure.Detail)
			for _, text := range []string{"保障", "适合", "等待", "费率", "说明", "1200"} {
				require.NotContains(t, failure.Detail, text, "details never echo source text")
			}
		})
	}

	reader := deck(t)
	reader.set.DocumentSHA256 = strings.Repeat("ef", 32)
	failure := refusal(t, submit(t, reader, "space-1", deckValid))
	require.Equal(t, release.ErrorEvidenceMismatch, failure.Code, "the captured revision must be the cited file")
}

func TestOfficeLocatorsCarryExactlyTheFieldsOfTheirKind(t *testing.T) {
	slideEvidence := office(onSlide(1), 1, 6, 11, "保障𠮷全面")
	blockEvidence := office(bodyBlock(2), 1, 10, 18, "等待期为90日。")
	rowEvidence := office(sheetRow("费率表", 3), 1, 7, 14, "30\t1200")
	normalized := office(onSlide(1), 1, 6, 11, "保障𠮷全面")
	normalized["match"] = "NORMALIZED"
	tableCell := with(blockEvidence, map[string]any{
		"kind": "DOCX_TABLE_CELL", "block_index": nil, "table_index": 0, "row": 0, "column": 1,
	})
	cases := []struct {
		name     string
		reader   func(*testing.T) *pageReader
		evidence map[string]any
	}{
		{"a shape the capture does not locate", deck, with(slideEvidence, map[string]any{"shape_id": "sp-3"})},
		{"a bounding box", deck, with(slideEvidence, map[string]any{
			"bbox": map[string]any{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.05},
		})},
		{"slide missing", deck, with(slideEvidence, map[string]any{"slide": nil})},
		{"page missing", deck, with(slideEvidence, map[string]any{"page": nil})},
		{"offsets missing", deck, with(slideEvidence, map[string]any{"start": nil, "end": nil})},
		{"a cell inside a body block", document, with(blockEvidence, map[string]any{"row": 0, "column": 1})},
		{"block index missing", document, with(blockEvidence, map[string]any{"block_index": nil})},
		{"sheet missing", workbook, with(rowEvidence, map[string]any{"sheet": nil})},
		{"cell range missing", workbook, with(rowEvidence, map[string]any{"cell_range": nil})},
		{"a chunk on a sheet row", workbook, with(rowEvidence, map[string]any{"chunk_id": "chunk-1"})},
		{"a table cell kind", document, tableCell},
		{"normalized match", deck, normalized},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			reader := c.reader(t)
			failure := refusal(t, submit(t, reader, "space-1", c.evidence))
			require.Equal(t, release.ErrorEvidenceUnsupported, failure.Code, failure.Detail)
			require.True(t, strings.HasPrefix(failure.Detail, "/members/0/payload/evidence/0"), failure.Detail)
			require.Empty(t, reader.calls, "unsupported evidence is refused before the capture is read")
		})
	}
}

func TestOfficeCapturesThatCannotBeReadAreUnverifiable(t *testing.T) {
	evidence := office(onSlide(1), 1, 6, 11, "保障𠮷全面")
	for name, err := range map[string]error{
		"never captured":     &source.Error{Code: source.ErrorNotCaptured, Detail: "x"},
		"deleted or foreign": &source.Error{Code: source.ErrorSourceNotFound, Detail: "x"},
		"artifact damaged":   &source.Error{Code: source.ErrorIntegrity, Detail: "x"},
	} {
		t.Run(name, func(t *testing.T) {
			reader := deck(t)
			reader.err = err
			failure := refusal(t, submit(t, reader, "space-1", evidence))
			require.Equal(t, release.ErrorEvidenceUnverifiable, failure.Code)
		})
	}

	failure := refusal(t, submit(t, deck(t), "space-9", evidence))
	require.Equal(t, release.ErrorEvidenceUnverifiable, failure.Code, "a Space without configuration has no sources")
}
