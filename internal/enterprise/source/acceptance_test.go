// S4c-1 acceptance: per-page source text from a stored parse artifact (Spec §3.1).
// Protected file: written by Claude.
//
// The service cuts each page out of the parsed full text by the artifact's code-point
// ranges, returns it verbatim, and fails closed with typed errors. Only the exported
// surface is used, with an in-memory store: no database, no network, no file system.
// The package does not exist yet, so this file is RED until S4c-1 implements it.
package source_test

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/source"
)

var scope = source.Scope{TenantID: 7, SpaceID: "space-1"}

func sha(text string) string {
	sum := sha256.Sum256([]byte(text))
	return hex.EncodeToString(sum[:])
}

type page struct {
	Number int    `json:"page_number"`
	Start  int    `json:"global_codepoint_start"`
	End    int    `json:"global_codepoint_end"`
	SHA    string `json:"page_text_sha256"`
}

// artifact joins pages with "\n\n" like docreader and records code-point ranges.
func artifact(t *testing.T, texts ...string) *source.Artifact {
	t.Helper()
	full := []rune{}
	pages := []page{}
	for i, text := range texts {
		if i > 0 {
			full = append(full, []rune("\n\n")...)
		}
		start := len(full)
		full = append(full, []rune(text)...)
		pages = append(pages, page{Number: i + 1, Start: start, End: len(full), SHA: sha(text)})
	}
	native, err := json.Marshal(map[string]any{
		"contract": "pdf-native-structure-v1", "coordinate_space": "normalized_0_1e6_top_left", "pages": pages,
	})
	require.NoError(t, err)
	return &source.Artifact{
		KnowledgeID: "k-1", ParseAttempt: 2, FileName: "保险条款.pdf", FileSHA256: sha("pdf bytes"),
		ParserIdentitySHA256: sha("pdfium"), Markdown: string(full), NativeJSON: native,
	}
}

type store struct {
	artifact *source.Artifact
	err      error
	calls    int
}

func (s *store) Load(_ context.Context, got source.Scope, knowledgeID string, attempt int64) (*source.Artifact, error) {
	s.calls++
	if got != scope || knowledgeID != "k-1" || attempt != 2 {
		return nil, source.ErrNotFound
	}
	return s.artifact, s.err
}

func code(t *testing.T, err error) string {
	t.Helper()
	var typed *source.Error
	require.True(t, errors.As(err, &typed), "want *source.Error, got %v", err)
	return typed.Code
}

func TestPagesAreCodePointSlicesReturnedVerbatim(t *testing.T) {
	// A non-BMP character on page 1 shifts byte and UTF-16 offsets but not code points.
	first := "1.4 等待期\r\n自本合同生效之日起90日内为等待期。𠮷"
	second := "1.5 保险期间\n本合同保险期间为一年。"
	a := artifact(t, first, second)
	set, err := source.NewService(&store{artifact: a}).Pages(context.Background(), scope, "k-1", 2)
	require.NoError(t, err)
	require.Equal(t, "k-1", set.KnowledgeID)
	require.Equal(t, int64(2), set.ParseAttempt)
	require.Equal(t, "保险条款.pdf", set.Document)
	require.Equal(t, a.FileSHA256, set.DocumentSHA256)
	require.Equal(t, a.ParserIdentitySHA256, set.ParserIdentitySHA256)
	require.Equal(t, sha(string(a.NativeJSON)), set.NativeSHA256)
	require.Len(t, set.Pages, 2)
	require.Equal(t, 1, set.Pages[0].Number)
	require.Equal(t, first, set.Pages[0].Text, "page text must keep \\r\\n and every code point")
	require.Equal(t, second, set.Pages[1].Text)
	require.Equal(t, sha(second), set.Pages[1].TextSHA256)
}

func TestAPageWhoseTextNoLongerMatchesItsHashFailsClosed(t *testing.T) {
	a := artifact(t, "第一页。", "第二页。")
	a.Markdown = "第一页。\n\n第二頁。" // one character changed after capture
	_, err := source.NewService(&store{artifact: a}).Pages(context.Background(), scope, "k-1", 2)
	require.Equal(t, "PARSE_ARTIFACT_INTEGRITY", code(t, err))
}

func TestMalformedPageRangesFailClosed(t *testing.T) {
	for name, mutate := range map[string]func(*[]page){
		"out of range": func(p *[]page) { (*p)[1].End = 999 },
		"overlapping":  func(p *[]page) { (*p)[1].Start = (*p)[0].End - 1 },
		"gap in pages": func(p *[]page) { (*p)[1].Number = 3 },
		"no pages":     func(p *[]page) { *p = nil },
	} {
		t.Run(name, func(t *testing.T) {
			a := artifact(t, "第一页。", "第二页。")
			var native struct {
				Pages []page `json:"pages"`
			}
			require.NoError(t, json.Unmarshal(a.NativeJSON, &native))
			mutate(&native.Pages)
			raw, err := json.Marshal(map[string]any{"pages": native.Pages})
			require.NoError(t, err)
			a.NativeJSON = raw
			_, err = source.NewService(&store{artifact: a}).Pages(context.Background(), scope, "k-1", 2)
			require.Equal(t, "PARSE_ARTIFACT_INTEGRITY", code(t, err))
		})
	}
}

func TestStoreOutcomesMapToTypedErrorsWithoutDetails(t *testing.T) {
	ctx := context.Background()
	_, err := source.NewService(&store{}).Pages(ctx, scope, "k-2", 2)
	require.Equal(t, "SOURCE_NOT_FOUND", code(t, err))

	_, err = source.NewService(&store{err: source.ErrNotCaptured}).Pages(ctx, scope, "k-1", 2)
	require.Equal(t, "PARSE_ARTIFACT_NOT_CAPTURED", code(t, err))

	_, err = source.NewService(&store{err: errors.New("open /srv/data/secret.json: permission denied")}).
		Pages(ctx, scope, "k-1", 2)
	require.Equal(t, "SOURCE_UNAVAILABLE", code(t, err))
	require.NotContains(t, err.Error(), "/srv/data", "storage details must not leak")
}

func TestInvalidRequestsNeverReachTheStore(t *testing.T) {
	s := &store{}
	for _, tc := range []struct {
		knowledge string
		attempt   int64
	}{{"", 2}, {"  ", 2}, {"k-1", 0}, {"k-1", -1}} {
		_, err := source.NewService(s).Pages(context.Background(), scope, tc.knowledge, tc.attempt)
		require.Equal(t, "INVALID_REQUEST", code(t, err))
	}
	require.Zero(t, s.calls)
}
