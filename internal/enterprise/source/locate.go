package source

import (
	"time"

	"github.com/Tencent/WeKnora/internal/enterprise/capture/ooxml"
)

// ErrorLocatorMismatch identifies Office evidence that is not the exact place of one captured block;
// the Detail is a reason category, never source text. Callers report it as an evidence mismatch.
const ErrorLocatorMismatch = "LOCATOR_MISMATCH"

// pdfLocatorKind locates evidence on pages without blocks (S4c-2b-2).
const pdfLocatorKind = "PDF_TEXT_SPAN"

// OfficeKind reports whether evidence of this locator kind sits in an Office block (S11b) and is
// resolved by Locate.
func OfficeKind(kind string) bool {
	switch kind {
	case "PPTX_SHAPE", "DOCX_BLOCK", "XLSX_CELL_RANGE":
		return true
	}
	return false
}

// BlockView is verified Office evidence: the exact text of page-local code points [Start, End) and
// the one captured block that holds it.
type BlockView struct {
	KnowledgeID, Document, DocumentSHA256 string
	ParseAttempt                          int64
	Page                                  int
	Start, End                            int // page-local code points, half-open
	Quote                                 string
	Block                                 ooxml.Block
	RevisedAt                             time.Time // the cited revision's time, zero when unknown
}

// LocatorKind is the locator kind of evidence on these pages: an Office capture's block kind (one
// kind per capture, verified by ooxml.Decode), or PDF_TEXT_SPAN for pages without any block. A
// capture without blocks has no text, so no evidence can be located on it either way.
func (s *PageSet) LocatorKind() string {
	for _, p := range s.Pages {
		if len(p.Blocks) > 0 {
			return p.Blocks[0].Locator.Kind
		}
	}
	return pdfLocatorKind
}

// Locate resolves Office evidence on verified pages (S11d Spec §2.2 steps 7–10): the capture is of
// the locator's kind, [start, end) lies on the page inside one block (blocks never overlap), and that
// block carries exactly locator. The quote is the verbatim page slice; the caller compares it.
func (s *PageSet) Locate(locator ooxml.Locator, page, start, end int) (*BlockView, error) {
	if !OfficeKind(locator.Kind) || s.LocatorKind() != locator.Kind {
		return nil, locatorMismatch("captured format")
	}
	if page < 1 || page > len(s.Pages) {
		return nil, locatorMismatch("page")
	}
	text := []rune(s.Pages[page-1].Text)
	if start < 0 || start >= end || end > len(text) {
		return nil, locatorMismatch("code-point range")
	}
	for _, b := range s.Pages[page-1].Blocks {
		if start < b.Start || b.End < end {
			continue
		}
		if !sameLocator(b.Locator, locator) {
			return nil, locatorMismatch("block locator")
		}
		return &BlockView{
			KnowledgeID: s.KnowledgeID, Document: s.Document, DocumentSHA256: s.DocumentSHA256,
			ParseAttempt: s.ParseAttempt, Page: page, Start: start, End: end,
			Quote: string(text[start:end]), Block: b, RevisedAt: s.RevisedAt,
		}, nil
	}
	return nil, locatorMismatch("block")
}

// sameLocator compares every field a block locator can carry; strings compare verbatim.
func sameLocator(a, b ooxml.Locator) bool {
	return a.Kind == b.Kind && a.Sheet == b.Sheet && a.CellRange == b.CellRange &&
		sameIndex(a.Slide, b.Slide) && sameIndex(a.BlockIndex, b.BlockIndex)
}

func sameIndex(a, b *int) bool { return (a == nil) == (b == nil) && (a == nil || *a == *b) }

func locatorMismatch(reason string) *Error { return &Error{Code: ErrorLocatorMismatch, Detail: reason} }
