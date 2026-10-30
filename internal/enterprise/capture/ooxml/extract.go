package ooxml

import (
	"archive/zip"
	"bytes"
	"fmt"
	"strings"
	"unicode/utf8"

	"github.com/xuri/excelize/v2"

	"github.com/Tencent/WeKnora/internal/sourceloc"
	"github.com/Tencent/WeKnora/internal/types"
)

// Supports reports whether Extract reads fileType (pptx, docx, xlsx; case-insensitive, dot optional).
func Supports(fileType string) bool {
	_, ok := formatOf(fileType)
	return ok
}

func formatOf(fileType string) (string, bool) {
	format := strings.ToLower(strings.TrimPrefix(strings.TrimSpace(fileType), "."))
	switch format {
	case "pptx", "docx", "xlsx":
		return format, true
	}
	return "", false
}

// Extract reads one Office original deterministically. Checks run in order: format, OLE header,
// zip structure, package limits and integrity, then the upstream unit extraction and page assembly.
func Extract(fileType string, data []byte) (*Structure, error) {
	format, ok := formatOf(fileType)
	if !ok {
		return nil, &Error{Code: ErrorUnsupported, Detail: "file type is not pptx, docx or xlsx"}
	}
	if bytes.HasPrefix(data, oleHeader) {
		return nil, &Error{Code: ErrorUnsupported, Detail: "OLE compound file (encrypted or legacy Office)"}
	}
	archive, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return nil, malformed("not a zip package")
	}
	files, err := checkPackage(archive)
	if err != nil {
		return nil, err
	}
	if format == "docx" && files["word/document.xml"] == nil {
		return nil, malformed("word/document.xml is missing")
	}
	units, err := sourceloc.StructureUnits(format, data)
	if err != nil {
		return nil, malformed("required parts are missing or invalid")
	}
	if len(units) >= upstreamUnitCap {
		return nil, &Error{Code: ErrorTooLarge, Detail: fmt.Sprintf("at least %d text units", upstreamUnitCap)}
	}
	var pages []*pageBuilder
	switch format {
	case "pptx":
		pages, err = slidePages(files, units)
	case "docx":
		pages, err = documentPage(units)
	default:
		pages, err = sheetPages(data, units)
	}
	if err != nil {
		return nil, err
	}
	s := &Structure{
		Contract: Contract, Extractor: ExtractorIdentity, Format: format,
		ParserIdentitySHA256: digest([]byte(ExtractorIdentity)), SourceSHA256: digest(data),
	}
	blocks := 0
	for i, builder := range pages {
		page, err := builder.page(i + 1)
		if err != nil {
			return nil, err
		}
		blocks += len(page.Blocks)
		s.Pages = append(s.Pages, page)
	}
	if blocks == 0 {
		return nil, &Error{Code: ErrorEmpty, Detail: "no text block"}
	}
	return s, nil
}

// pageBuilder collects the blocks of one page before their offsets are known.
type pageBuilder struct {
	ids      []string
	texts    []string
	locators []Locator
}

func (b *pageBuilder) add(id, text string, locator Locator) {
	b.ids = append(b.ids, id)
	b.texts = append(b.texts, text)
	b.locators = append(b.locators, locator)
}

// page joins block texts with a blank line and records each block's code-point range.
func (b *pageBuilder) page(number int) (Page, error) {
	page := Page{Number: number, Blocks: []Block{}}
	var text strings.Builder
	offset := 0
	for i, blockText := range b.texts {
		if !utf8.ValidString(blockText) || strings.ContainsRune(blockText, 0) || strings.TrimSpace(blockText) == "" {
			return Page{}, malformed(fmt.Sprintf("page %d block %d text is invalid", number, i))
		}
		if i > 0 {
			text.WriteString("\n\n")
			offset += 2
		}
		length := utf8.RuneCountInString(blockText)
		page.Blocks = append(page.Blocks, Block{
			ID: b.ids[i], Start: offset, End: offset + length, Locator: b.locators[i],
		})
		text.WriteString(blockText)
		offset += length
	}
	page.Text = text.String()
	page.TextSHA256 = digest([]byte(page.Text))
	return page, nil
}

// slidePages: one page per declared slide in presentation order, text-less slides included.
func slidePages(files parts, units []sourceloc.Unit) ([]*pageBuilder, error) {
	count, err := declaredSlides(files)
	if err != nil {
		return nil, err
	}
	pages := newPages(count)
	for _, unit := range units {
		slide := unit.Locator.Slide
		if unit.Locator.Type != types.SourceLocatorSlide || slide < 1 || slide > count {
			return nil, malformed("a text unit has no valid slide")
		}
		builder := pages[slide-1]
		n := slide
		builder.add(fmt.Sprintf("s%d/p%d", slide, len(builder.ids)+1), unit.Text, Locator{Kind: kindSlide, Slide: &n})
	}
	return pages, nil
}

// documentPage: the whole document is page 1; units that share an upstream block number (the rows of
// one table) form one block, joined by a newline.
func documentPage(units []sourceloc.Unit) ([]*pageBuilder, error) {
	builder := &pageBuilder{}
	var current []string
	lastBlock := 0
	flush := func() {
		if len(current) > 0 {
			index := lastBlock - 1
			locator := Locator{Kind: kindBlock, BlockIndex: &index}
			builder.add(fmt.Sprintf("b%d", index), strings.Join(current, "\n"), locator)
			current = nil
		}
	}
	for _, unit := range units {
		block := unit.Locator.Block
		if unit.Locator.Type != types.SourceLocatorDocx || block < 1 || block < lastBlock {
			return nil, malformed("a text unit has no valid block")
		}
		if block != lastBlock {
			flush()
			lastBlock = block
		}
		current = append(current, unit.Text)
	}
	flush()
	return []*pageBuilder{builder}, nil
}

// sheetPages: one page per declared sheet in workbook order, empty sheets included; one block per row.
func sheetPages(data []byte, units []sourceloc.Unit) ([]*pageBuilder, error) {
	book, err := excelize.OpenReader(bytes.NewReader(data))
	if err != nil {
		return nil, malformed("workbook cannot be opened")
	}
	defer func() { _ = book.Close() }()
	sheets := book.GetSheetList()
	if err := checkSheets(book, sheets); err != nil {
		return nil, err
	}
	pages := newPages(len(sheets))
	index := make(map[string]int, len(sheets))
	for i, name := range sheets {
		index[name] = i
	}
	for _, unit := range units {
		loc := unit.Locator
		i, ok := index[loc.Sheet]
		if loc.Type != types.SourceLocatorSheet || !ok || loc.RowStart < 1 || loc.RowEnd != loc.RowStart {
			return nil, malformed("a text unit has no valid sheet row")
		}
		pages[i].add(fmt.Sprintf("x%d/r%d", i+1, loc.RowStart), unit.Text, Locator{
			Kind: kindRows, Sheet: loc.Sheet, CellRange: fmt.Sprintf("A%d:XFD%d", loc.RowStart, loc.RowStart),
		})
	}
	return pages, nil
}

func newPages(count int) []*pageBuilder {
	pages := make([]*pageBuilder, count)
	for i := range pages {
		pages[i] = &pageBuilder{}
	}
	return pages
}
