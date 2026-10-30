package ooxml

import (
	"archive/zip"
	"bytes"
	"encoding/xml"
	"fmt"
	"io"
	"strings"
	"unicode/utf8"

	"github.com/xuri/excelize/v2"

	"github.com/Tencent/WeKnora/internal/sourceloc"
	"github.com/Tencent/WeKnora/internal/types"
)

// Package limits for an untrusted upload, counted on decompressed bytes (Spec §2.3).
const (
	maxEntries      = 10_000
	maxUncompressed = 512 << 20
	maxXMLPart      = 64 << 20
	// upstreamUnitCap is sourceloc's own unit limit: a result this large may have been truncated.
	upstreamUnitCap = 200_000
)

// oleHeader starts an OLE compound file: encrypted OOXML or legacy binary Office.
var oleHeader = []byte{0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1}

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
// zip structure, package limits, then the upstream unit extraction and page assembly.
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
	if err := checkPackage(archive); err != nil {
		return nil, err
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
		pages, err = slidePages(archive, units)
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

// checkPackage decompresses every entry once, counting real bytes, and refuses DTDs in XML parts.
func checkPackage(archive *zip.Reader) error {
	if len(archive.File) > maxEntries {
		return &Error{Code: ErrorTooLarge, Detail: fmt.Sprintf("%d entries", len(archive.File))}
	}
	var total int64
	for i, f := range archive.File {
		rc, err := f.Open()
		if err != nil {
			return malformed(fmt.Sprintf("entry %d cannot be opened", i))
		}
		remaining := int64(maxUncompressed) - total
		if isXMLPart(f.Name) {
			limit := min(remaining, maxXMLPart)
			body, readErr := io.ReadAll(io.LimitReader(rc, limit+1))
			_ = rc.Close()
			if readErr != nil {
				return malformed(fmt.Sprintf("entry %d cannot be decompressed", i))
			}
			if int64(len(body)) > limit {
				return &Error{Code: ErrorTooLarge, Detail: fmt.Sprintf("entry %d exceeds the size limit", i)}
			}
			if bytes.Contains(body, []byte("<!DOCTYPE")) || bytes.Contains(body, []byte("<!ENTITY")) {
				return malformed(fmt.Sprintf("entry %d declares a DTD or entity", i))
			}
			total += int64(len(body))
			continue
		}
		n, copyErr := io.Copy(io.Discard, io.LimitReader(rc, remaining+1))
		_ = rc.Close()
		if copyErr != nil {
			return malformed(fmt.Sprintf("entry %d cannot be decompressed", i))
		}
		if n > remaining {
			return &Error{Code: ErrorTooLarge, Detail: "decompressed package exceeds the size limit"}
		}
		total += n
	}
	return nil
}

func isXMLPart(name string) bool {
	lower := strings.ToLower(name)
	return strings.HasSuffix(lower, ".xml") || strings.HasSuffix(lower, ".rels")
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

// slidePages: one page per slide in presentation order, text-less slides included.
func slidePages(archive *zip.Reader, units []sourceloc.Unit) ([]*pageBuilder, error) {
	count, err := slideCount(archive)
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

func slideCount(archive *zip.Reader) (int, error) {
	file, err := archive.Open("ppt/presentation.xml")
	if err != nil {
		return 0, malformed("ppt/presentation.xml is missing")
	}
	defer func() { _ = file.Close() }()
	var presentation struct {
		SlideIDs []struct{} `xml:"sldIdLst>sldId"`
	}
	if err := xml.NewDecoder(io.LimitReader(file, maxXMLPart)).Decode(&presentation); err != nil {
		return 0, malformed("ppt/presentation.xml is invalid")
	}
	return len(presentation.SlideIDs), nil
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

// sheetPages: one page per sheet in workbook order, empty sheets included; one block per row.
func sheetPages(data []byte, units []sourceloc.Unit) ([]*pageBuilder, error) {
	book, err := excelize.OpenReader(bytes.NewReader(data))
	if err != nil {
		return nil, malformed("workbook cannot be opened")
	}
	sheets := book.GetSheetList()
	_ = book.Close()
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
