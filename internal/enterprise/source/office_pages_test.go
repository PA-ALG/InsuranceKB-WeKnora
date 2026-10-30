// S11b acceptance (protected, written by Claude): source pages of an Office capture
// (Spec docs/design/slices/S11b-Office结构采集与页文本.md §4).
//
// An Office capture stores its own page text and located blocks in the native structure; pages are
// read from that structure (never from the Markdown), verified, and returned with their blocks. PDF
// captures are untouched. The result is inspected through its JSON so this file compiles against the
// current API; it is RED until S11b adds the Office branch and Page.Blocks.
package source_test

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/source"
)

const officeExtractor = "enterprise.ooxml.sourceloc.v1"

type officeLocator struct {
	BlockIndex *int   `json:"block_index,omitempty"`
	CellRange  string `json:"cell_range,omitempty"`
	Kind       string `json:"kind"`
	Sheet      string `json:"sheet,omitempty"`
	Slide      *int   `json:"slide,omitempty"`
}

type officeBlock struct {
	ID      string        `json:"block_id"`
	End     int           `json:"end"`
	Locator officeLocator `json:"locator"`
	Start   int           `json:"start"`
}

type officePage struct {
	Blocks     []officeBlock `json:"blocks"`
	Number     int           `json:"page_number"`
	TextSHA256 string        `json:"page_text_sha256"`
	Text       string        `json:"text"`
}

type officeStructure struct {
	Contract             string       `json:"contract"`
	Extractor            string       `json:"extractor"`
	Format               string       `json:"format"`
	Pages                []officePage `json:"pages"`
	ParserIdentitySHA256 string       `json:"parser_identity_sha256"`
	SourceSHA256         string       `json:"source_sha256"`
}

func intp(v int) *int { return &v }

func slideAt(n int) officeLocator { return officeLocator{Kind: "PPTX_SHAPE", Slide: intp(n)} }

func rowLocator(sheet, cells string) officeLocator {
	return officeLocator{Kind: "XLSX_CELL_RANGE", Sheet: sheet, CellRange: cells}
}

// deckFixture: page 1 has two paragraphs (one with a non-BMP character), page 2 one paragraph.
func deckFixture() officeStructure {
	first := "产品亮点\n\n保障𠮷全面"
	second := "适合人群"
	return officeStructure{
		Contract: "enterprise-ooxml-structure.v1", Extractor: officeExtractor, Format: "pptx",
		ParserIdentitySHA256: sha(officeExtractor), SourceSHA256: sha("pptx bytes"),
		Pages: []officePage{
			{Number: 1, Text: first, TextSHA256: sha(first), Blocks: []officeBlock{
				{ID: "s1/p1", Start: 0, End: 4, Locator: slideAt(1)},
				{ID: "s1/p2", Start: 6, End: 11, Locator: slideAt(1)},
			}},
			{Number: 2, Text: second, TextSHA256: sha(second), Blocks: []officeBlock{
				{ID: "s2/p1", Start: 0, End: 4, Locator: slideAt(2)},
			}},
		},
	}
}

func docFixture() officeStructure {
	text := "第一条\n\nA1 B1\nA2 B2"
	s := deckFixture()
	s.Format = "docx"
	s.SourceSHA256 = sha("docx bytes")
	s.Pages = []officePage{{Number: 1, Text: text, TextSHA256: sha(text), Blocks: []officeBlock{
		{ID: "b0", Start: 0, End: 3, Locator: officeLocator{Kind: "DOCX_BLOCK", BlockIndex: intp(0)}},
		{ID: "b1", Start: 5, End: 16, Locator: officeLocator{Kind: "DOCX_BLOCK", BlockIndex: intp(1)}},
	}}}
	return s
}

func bookFixture() officeStructure {
	first := "年龄 保费\n\n30 1200"
	s := deckFixture()
	s.Format = "xlsx"
	s.SourceSHA256 = sha("xlsx bytes")
	s.Pages = []officePage{
		{Number: 1, Text: first, TextSHA256: sha(first), Blocks: []officeBlock{
			{ID: "x1/r1", Start: 0, End: 5, Locator: rowLocator("费率", "A1:XFD1")},
			{ID: "x1/r3", Start: 7, End: 14, Locator: rowLocator("费率", "A3:XFD3")},
		}},
		{Number: 2, Text: "", TextSHA256: sha(""), Blocks: []officeBlock{}},
	}
	return s
}

func officeArtifact(t *testing.T, structure officeStructure) *source.Artifact {
	t.Helper()
	native, err := json.Marshal(structure)
	require.NoError(t, err)
	names := map[string]string{"pptx": "培训材料.pptx", "docx": "通关手册.docx", "xlsx": "费率.xlsx", "odp": "x.odp"}
	files := map[string]string{"pptx": sha("pptx bytes"), "docx": sha("docx bytes"), "xlsx": sha("xlsx bytes")}
	file, ok := files[structure.Format]
	if !ok {
		file = sha("pptx bytes")
	}
	return &source.Artifact{
		KnowledgeID: "k-1", ParseAttempt: 2, FileName: names[structure.Format],
		FileSHA256: file, ParserIdentitySHA256: sha(officeExtractor),
		// Pages come from the structure, never from the Markdown.
		Markdown:   "# a rendering that differs from the captured structure",
		NativeJSON: native,
	}
}

func officePages(t *testing.T, set *source.PageSet) []officePage {
	t.Helper()
	data, err := json.Marshal(set)
	require.NoError(t, err)
	var decoded struct {
		Pages []officePage `json:"pages"`
	}
	require.NoError(t, json.Unmarshal(data, &decoded))
	return decoded.Pages
}

func loadOffice(t *testing.T, structure officeStructure) (*source.PageSet, error) {
	t.Helper()
	return source.NewService(&store{artifact: officeArtifact(t, structure)}).
		Pages(context.Background(), scope, "k-1", 2)
}

func TestOfficePagesComeFromTheCapturedStructureWithTheirBlocks(t *testing.T) {
	for _, structure := range []officeStructure{deckFixture(), docFixture(), bookFixture()} {
		set, err := loadOffice(t, structure)
		require.NoError(t, err, structure.Format)
		native, err := json.Marshal(structure)
		require.NoError(t, err)
		require.Equal(t, sha(string(native)), set.NativeSHA256)
		pages := officePages(t, set)
		for i := range structure.Pages {
			if len(structure.Pages[i].Blocks) == 0 {
				structure.Pages[i].Blocks = nil // an Office page without blocks omits the key
			}
		}
		require.Equal(t, structure.Pages, pages, structure.Format)
	}
	set, err := loadOffice(t, deckFixture())
	require.NoError(t, err)
	page := officePages(t, set)[0]
	runes := []rune(page.Text)
	require.Equal(t, "保障𠮷全面", string(runes[page.Blocks[1].Start:page.Blocks[1].End]),
		"block offsets are page-local code points")
}

func TestPDFPagesCarryNoBlocks(t *testing.T) {
	set, err := source.NewService(&store{artifact: artifact(t, "第一页。")}).
		Pages(context.Background(), scope, "k-1", 2)
	require.NoError(t, err)
	data, err := json.Marshal(set)
	require.NoError(t, err)
	var decoded struct {
		Pages []map[string]json.RawMessage `json:"pages"`
	}
	require.NoError(t, json.Unmarshal(data, &decoded))
	require.Len(t, decoded.Pages, 1)
	_, present := decoded.Pages[0]["blocks"]
	require.False(t, present, "PDF page JSON is unchanged: no blocks key")
}

func TestOfficeStructuresThatDoNotVerifyFailClosed(t *testing.T) {
	cases := map[string]struct {
		fixture func() officeStructure
		mutate  func(*officeStructure)
	}{
		"page text digest":       {deckFixture, func(s *officeStructure) { s.Pages[1].Text = "适合人君" }},
		"page numbers not 1..n":  {deckFixture, func(s *officeStructure) { s.Pages[1].Number = 3 }},
		"no pages":               {deckFixture, func(s *officeStructure) { s.Pages = nil }},
		"block beyond page text": {deckFixture, func(s *officeStructure) { s.Pages[1].Blocks[0].End = 5 }},
		"blocks overlap":         {deckFixture, func(s *officeStructure) { s.Pages[0].Blocks[1].Start = 3 }},
		"blocks out of order": {deckFixture, func(s *officeStructure) {
			b := s.Pages[0].Blocks
			b[0], b[1] = b[1], b[0]
		}},
		"blank block":             {deckFixture, func(s *officeStructure) { s.Pages[0].Blocks[0].End = 0 }},
		"duplicate block id":      {deckFixture, func(s *officeStructure) { s.Pages[0].Blocks[1].ID = "s1/p1" }},
		"empty block id":          {deckFixture, func(s *officeStructure) { s.Pages[0].Blocks[0].ID = "" }},
		"negative block start":    {deckFixture, func(s *officeStructure) { s.Pages[0].Blocks[0].Start = -1 }},
		"page digest not hex sha": {deckFixture, func(s *officeStructure) { s.Pages[1].TextSHA256 = "not-a-digest" }},
		"pptx locator kind": {deckFixture, func(s *officeStructure) {
			s.Pages[0].Blocks[0].Locator.Kind = "DOCX_BLOCK"
		}},
		"slide is not the page": {deckFixture, func(s *officeStructure) {
			s.Pages[1].Blocks[0].Locator.Slide = intp(1)
		}},
		"missing slide": {deckFixture, func(s *officeStructure) {
			s.Pages[1].Blocks[0].Locator.Slide = nil
		}},
		"pptx locator extra field": {deckFixture, func(s *officeStructure) {
			s.Pages[0].Blocks[0].Locator.Sheet = "x"
		}},
		"unknown format": {deckFixture, func(s *officeStructure) { s.Format = "odp" }},
		"unknown contract": {deckFixture, func(s *officeStructure) {
			s.Contract = "enterprise-ooxml-structure.v2"
		}},
		"other extractor": {deckFixture, func(s *officeStructure) { s.Extractor = "other" }},
		"parser identity": {deckFixture, func(s *officeStructure) { s.ParserIdentitySHA256 = sha("other") }},
		"source digest":   {deckFixture, func(s *officeStructure) { s.SourceSHA256 = sha("another file") }},
		"docx second page": {docFixture, func(s *officeStructure) {
			s.Pages = append(s.Pages, officePage{Number: 2, Text: "", TextSHA256: sha(""), Blocks: []officeBlock{}})
		}},
		"docx missing block index": {docFixture, func(s *officeStructure) {
			s.Pages[0].Blocks[1].Locator.BlockIndex = nil
		}},
		"docx block index repeats": {docFixture, func(s *officeStructure) {
			s.Pages[0].Blocks[1].Locator.BlockIndex = intp(0)
		}},
		"xlsx empty sheet": {bookFixture, func(s *officeStructure) { s.Pages[0].Blocks[0].Locator.Sheet = "" }},
		"xlsx sheet changes": {bookFixture, func(s *officeStructure) {
			s.Pages[0].Blocks[1].Locator.Sheet = "其他"
		}},
		"xlsx not a row range": {bookFixture, func(s *officeStructure) {
			s.Pages[0].Blocks[0].Locator.CellRange = "A1:B1"
		}},
		"xlsx rows not increasing": {bookFixture, func(s *officeStructure) {
			s.Pages[0].Blocks[1].Locator.CellRange = "A1:XFD1"
		}},
		"xlsx sheet on two pages": {bookFixture, func(s *officeStructure) {
			s.Pages[1].Text = "x"
			s.Pages[1].TextSHA256 = sha("x")
			s.Pages[1].Blocks = []officeBlock{{ID: "x2/r1", Start: 0, End: 1, Locator: officeLocator{
				Kind: "XLSX_CELL_RANGE", Sheet: "费率", CellRange: "A1:XFD1",
			}}}
		}},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			structure := c.fixture()
			c.mutate(&structure)
			_, err := loadOffice(t, structure)
			require.Equal(t, "PARSE_ARTIFACT_INTEGRITY", code(t, err))
		})
	}
}

func TestPDFSpanIsRefusedForOfficeCaptures(t *testing.T) {
	_, err := source.NewService(&store{artifact: officeArtifact(t, deckFixture())}).
		Span(context.Background(), scope, "k-1", 2, 1, 0, 4)
	require.Equal(t, "INVALID_REQUEST", code(t, err), "Office captures are located by block, not by PDF span")
}
