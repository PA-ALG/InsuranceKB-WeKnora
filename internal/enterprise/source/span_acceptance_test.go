// S4c-2b-2 acceptance: one verified quote location on a captured page, with highlight
// rectangles merged per line from the captured character boxes (Spec
// docs/design/slices/S4c-2b-2-证据回验与回跳.md §3.3). Protected file: written by Claude.
//
// Reuses scope, sha, store and code from the S4c-1 acceptance file of this package.
// RED until S4c-2b-2 implements it.
package source_test

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/source"
)

type box struct {
	BBox  [4]int `json:"bbox"`
	Start int    `json:"global_codepoint_start"`
	End   int    `json:"global_codepoint_end"`
}

type gap struct {
	Start  int    `json:"global_codepoint_start"`
	End    int    `json:"global_codepoint_end"`
	Reason string `json:"reason"`
}

type boxedPage struct {
	Number      int    `json:"page_number"`
	Start       int    `json:"global_codepoint_start"`
	End         int    `json:"global_codepoint_end"`
	SHA         string `json:"page_text_sha256"`
	Width       string `json:"width_points"`
	Height      string `json:"height_points"`
	Boxes       []box  `json:"bboxes"`
	Unavailable []gap  `json:"unavailable_ranges,omitempty"`
}

// Page 1 "AB CD\r\nEF": A B C D on one line, E F on the next; the space, \r and \n have no box.
// Page 2 "GH" is rotated: no boxes, one unavailable range. Page 3 "IJK" lacks J's box.
// Pages are joined with "\n\n" like the S4c-1 fixture, so page 2 starts at code point 11.
func boxedArtifact(t *testing.T, mutate func([]boxedPage)) *source.Artifact {
	t.Helper()
	texts := []string{"AB CD\r\nEF", "GH", "IJK"}
	full := []rune{}
	pages := make([]boxedPage, 0, len(texts))
	for i, text := range texts {
		if i > 0 {
			full = append(full, []rune("\n\n")...)
		}
		start := len(full)
		full = append(full, []rune(text)...)
		pages = append(pages, boxedPage{
			Number: i + 1, Start: start, End: len(full), SHA: sha(text),
			Width: "595.28", Height: "841.89", Boxes: []box{},
		})
	}
	at := func(page, index int, x0, y0, x1, y1 int) box {
		g := pages[page].Start + index
		return box{BBox: [4]int{x0, y0, x1, y1}, Start: g, End: g + 1}
	}
	pages[0].Boxes = []box{
		at(0, 0, 100, 100, 200, 200), at(0, 1, 200, 100, 300, 200),
		at(0, 3, 400, 100, 500, 200), at(0, 4, 500, 100, 600, 200),
		at(0, 7, 100, 300, 200, 400), at(0, 8, 200, 300, 300, 400),
	}
	pages[1].Unavailable = []gap{{Start: pages[1].Start, End: pages[1].End, Reason: "page_rotation_unsupported"}}
	pages[2].Boxes = []box{at(2, 0, 100, 100, 200, 200), at(2, 2, 300, 100, 400, 200)}
	pages[2].Unavailable = []gap{{Start: pages[2].Start + 1, End: pages[2].Start + 2, Reason: "bbox_unavailable"}}
	if mutate != nil {
		mutate(pages)
	}
	native, err := json.Marshal(map[string]any{
		"contract": "pdf-native-structure-v2", "coordinate_space": "normalized_0_1e6_top_left", "pages": pages,
	})
	require.NoError(t, err)
	return &source.Artifact{
		KnowledgeID: "k-1", ParseAttempt: 2, FileName: "保险条款.pdf", FileSHA256: sha("pdf bytes"),
		ParserIdentitySHA256: sha("pdfium"), Markdown: string(full), NativeJSON: native,
	}
}

func span(t *testing.T, a *source.Artifact, page, start, end int) (*source.SpanView, error) {
	t.Helper()
	return source.NewService(&store{artifact: a}).Span(context.Background(), scope, "k-1", 2, page, start, end)
}

func TestSpanReturnsTheVerbatimQuoteAndOneRectanglePerLine(t *testing.T) {
	view, err := span(t, boxedArtifact(t, nil), 1, 1, 9)
	require.NoError(t, err)
	require.Equal(t, "B CD\r\nEF", view.Quote, "line endings are kept verbatim")
	require.Equal(t, source.SpanView{
		KnowledgeID: "k-1", Document: "保险条款.pdf", DocumentSHA256: sha("pdf bytes"), ParseAttempt: 2,
		Page: 1, WidthPoints: "595.28", HeightPoints: "841.89", Start: 1, End: 9, Quote: "B CD\r\nEF",
		Rects:    []source.Rect{{X0: 200, Y0: 100, X1: 600, Y1: 200}, {X0: 100, Y0: 300, X1: 300, Y1: 400}},
		Complete: true,
	}, *view)

	view, err = span(t, boxedArtifact(t, nil), 1, 3, 5)
	require.NoError(t, err)
	require.Equal(t, "CD", view.Quote)
	require.Equal(t, []source.Rect{{X0: 400, Y0: 100, X1: 600, Y1: 200}}, view.Rects)
	require.True(t, view.Complete)
}

func TestSpanOffsetsArePageLocal(t *testing.T) {
	view, err := span(t, boxedArtifact(t, nil), 3, 2, 3)
	require.NoError(t, err)
	require.Equal(t, "K", view.Quote)
	require.Equal(t, []source.Rect{{X0: 300, Y0: 100, X1: 400, Y1: 200}}, view.Rects)
	require.True(t, view.Complete, "the missing box of J is outside this span")
}

func TestSpansWithoutFullGeometryStillOpenTheRightPage(t *testing.T) {
	rotated, err := span(t, boxedArtifact(t, nil), 2, 0, 2)
	require.NoError(t, err)
	require.Equal(t, "GH", rotated.Quote)
	require.Equal(t, 2, rotated.Page)
	require.Empty(t, rotated.Rects)
	require.False(t, rotated.Complete)

	partial, err := span(t, boxedArtifact(t, nil), 3, 0, 3)
	require.NoError(t, err)
	require.Equal(t, "IJK", partial.Quote)
	require.Equal(t, []source.Rect{{X0: 100, Y0: 100, X1: 400, Y1: 200}}, partial.Rects)
	require.False(t, partial.Complete)
}

func TestSpanRangesOutsideThePageAreRefused(t *testing.T) {
	for _, r := range [][3]int{{0, 0, 1}, {4, 0, 1}, {1, 2, 2}, {1, 3, 2}, {1, -1, 2}, {1, 0, 10}, {2, 0, 3}} {
		_, err := span(t, boxedArtifact(t, nil), r[0], r[1], r[2])
		require.Equal(t, source.ErrorSpanOutOfRange, code(t, err), "page %d [%d,%d)", r[0], r[1], r[2])
	}
}

func TestCorruptGeometryOrTextFailsClosed(t *testing.T) {
	for name, mutate := range map[string]func([]boxedPage){
		"empty box":            func(p []boxedPage) { p[0].Boxes[0].BBox = [4]int{200, 100, 200, 200} },
		"box outside 0..1e6":   func(p []boxedPage) { p[0].Boxes[0].BBox = [4]int{100, 100, 1_000_001, 200} },
		"page text was edited": func(p []boxedPage) { p[0].SHA = sha("AB CD\nEF") },
	} {
		t.Run(name, func(t *testing.T) {
			_, err := span(t, boxedArtifact(t, mutate), 1, 0, 2)
			require.Equal(t, source.ErrorIntegrity, code(t, err))
		})
	}
}

func TestSpanSharesThePageServiceFailures(t *testing.T) {
	missing := source.NewService(&store{artifact: nil, err: source.ErrNotCaptured})
	_, err := missing.Span(context.Background(), scope, "k-1", 2, 1, 0, 1)
	require.Equal(t, source.ErrorNotCaptured, code(t, err))

	_, err = source.NewService(&store{artifact: boxedArtifact(t, nil)}).
		Span(context.Background(), scope, "k-2", 2, 1, 0, 1)
	require.Equal(t, source.ErrorSourceNotFound, code(t, err))

	_, err = source.NewService(&store{artifact: boxedArtifact(t, nil)}).
		Span(context.Background(), source.Scope{}, "k-1", 2, 1, 0, 1)
	require.Equal(t, source.ErrorInvalidRequest, code(t, err))
}
