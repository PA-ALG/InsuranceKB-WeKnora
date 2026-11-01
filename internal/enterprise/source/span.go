package source

import (
	"context"
	"sort"
	"time"
	"unicode"
)

// ErrorSpanOutOfRange identifies a page or code-point range outside the captured page.
const ErrorSpanOutOfRange = "SPAN_OUT_OF_RANGE"

// coordinateMax bounds normalized_0_1e6_top_left coordinates.
const coordinateMax = 1_000_000

// Rect is one highlight rectangle in normalized_0_1e6_top_left coordinates.
type Rect struct{ X0, Y0, X1, Y1 int }

// SpanView is a verified quote location on one captured page.
type SpanView struct {
	KnowledgeID, Document, DocumentSHA256 string
	ParseAttempt                          int64
	Page                                  int
	WidthPoints, HeightPoints             string
	Start, End                            int // page-local code points, half-open
	Quote                                 string
	Rects                                 []Rect
	Complete                              bool
	RevisedAt                             time.Time // the cited revision's time, zero when unknown
}

// Span verifies the artifact like Pages, then returns the exact text of [start, end) on
// one page with highlight rectangles merged per line from the captured character boxes.
// Missing geometry (rotated pages, unmapped characters) leaves Complete false; the quote
// and page are still returned so a viewer can open the right page.
func (s *Service) Span(
	ctx context.Context, scope Scope, knowledgeID string, attempt int64, page, start, end int,
) (*SpanView, error) {
	v, err := s.load(ctx, scope, knowledgeID, attempt)
	if err != nil {
		return nil, err
	}
	if v.office {
		return nil, &Error{Code: ErrorInvalidRequest, Detail: "Office captures are located by block, not by PDF span"}
	}
	if page < 1 || page > len(v.set.Pages) {
		return nil, outOfRange()
	}
	text := []rune(v.set.Pages[page-1].Text)
	if start < 0 || start >= end || end > len(text) {
		return nil, outOfRange()
	}
	native := v.native[page-1]
	from, to := *native.Start+start, *native.Start+end
	rects, boxed, err := lineRects(native.Boxes, from, to)
	if err != nil {
		return nil, err
	}
	complete := true
	for i := start; i < end && complete; i++ {
		complete = capturedSpace(text[i]) || boxed[*native.Start+i]
	}
	for _, gap := range native.Unavailable {
		if gap.Start < to && gap.End > from {
			complete = false
		}
	}
	return &SpanView{
		KnowledgeID: v.set.KnowledgeID, Document: v.set.Document, DocumentSHA256: v.set.DocumentSHA256,
		ParseAttempt: v.set.ParseAttempt, Page: page, WidthPoints: native.Width, HeightPoints: native.Height,
		Start: start, End: end, Quote: string(text[start:end]), Rects: rects, Complete: complete,
		RevisedAt: v.set.RevisedAt,
	}, nil
}

// lineRects merges the boxes of code points in [from, to) in code-point order: a box that
// does not overlap the current rectangle vertically, or starts left of it (a wrapped
// line), opens a new rectangle. It also reports which code points carry a box.
func lineRects(boxes []charBox, from, to int) ([]Rect, map[int]bool, error) {
	inRange := make([]charBox, 0, to-from)
	for _, b := range boxes {
		if b.Start >= from && b.Start < to {
			inRange = append(inRange, b)
		}
	}
	sort.SliceStable(inRange, func(i, j int) bool { return inRange[i].Start < inRange[j].Start })
	var rects []Rect
	boxed := map[int]bool{}
	for _, b := range inRange {
		if len(b.BBox) != 4 || b.End != b.Start+1 || boxed[b.Start] {
			return nil, nil, integrity()
		}
		r := Rect{X0: b.BBox[0], Y0: b.BBox[1], X1: b.BBox[2], Y1: b.BBox[3]}
		if r.X0 < 0 || r.Y0 < 0 || r.X1 > coordinateMax || r.Y1 > coordinateMax || r.X0 >= r.X1 || r.Y0 >= r.Y1 {
			return nil, nil, integrity()
		}
		boxed[b.Start] = true
		if n := len(rects); n > 0 {
			last := &rects[n-1]
			if r.Y0 < last.Y1 && r.Y1 > last.Y0 && r.X0 >= last.X0 {
				last.X0, last.Y0 = min(last.X0, r.X0), min(last.Y0, r.Y0)
				last.X1, last.Y1 = max(last.X1, r.X1), max(last.Y1, r.Y1)
				continue
			}
		}
		rects = append(rects, r)
	}
	return rects, boxed, nil
}

// capturedSpace matches the capture's whitespace test (Python str.isspace): those code
// points never get a box. Go's unicode.IsSpace lacks U+001C..U+001F.
func capturedSpace(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) }

func outOfRange() *Error {
	return &Error{Code: ErrorSpanOutOfRange, Detail: "the range is outside the captured page"}
}
