package releasestore

// S4c-2b-2 acceptance (protected, written by Claude): the platform verifies every PDF_TEXT_SPAN
// evidence against the captured page text of the exact source revision it cites
// (Spec docs/design/slices/S4c-2b-2-证据回验与回跳.md §3.2).
//
// The verifier is exercised through Service.Receive, which attaches the request scope, with an
// in-memory page reader. Reuses memoryStore, allowAll, testSchema, memberDigest and fileSHA of
// this package. RED until S4c-2b-2 implements it.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
)

const citedRef = "source:v1:k-1:2:" + "abababababababababababababababababababababababababababababababab"

type pageReader struct {
	set    *source.PageSet
	err    error
	calls  map[string]int
	scopes []source.Scope
}

func (p *pageReader) Pages(_ context.Context, scope source.Scope, id string, attempt int64) (*source.PageSet, error) {
	p.calls[fmt.Sprintf("%s:%d", id, attempt)]++
	p.scopes = append(p.scopes, scope)
	if p.err != nil {
		return nil, p.err
	}
	if id != "k-1" || attempt != 2 {
		return nil, &source.Error{Code: source.ErrorSourceNotFound, Detail: "source revision was not found"}
	}
	return p.set, nil
}

func capturedPages() *pageReader {
	return &pageReader{calls: map[string]int{}, set: &source.PageSet{
		KnowledgeID: "k-1", ParseAttempt: 2, Document: "保险条款.pdf", DocumentSHA256: fileSHA,
		Pages: []source.Page{
			{Number: 1, Text: "第一条\r\n等待期为90日。"},
			{Number: 2, Text: "宽限期六十日"},
		},
	}}
}

// span is a valid PDF_TEXT_SPAN evidence object; the quote must equal the page slice.
func span(page, start, end int, quote string) map[string]any {
	return map[string]any{
		"source_ref": citedRef, "file_sha256": fileSHA, "quote": quote, "access_scope": "space",
		"locator": map[string]any{"kind": "PDF_TEXT_SPAN", "page": page, "start": start, "end": end},
	}
}

// submit sends one source-supported member citing citedRef with the given evidence.
func submit(t *testing.T, reader *pageReader, space string, evidence ...map[string]any) error {
	t.Helper()
	contract, err := os.ReadFile("../../../contracts/evidence.schema.json")
	require.NoError(t, err)
	spaces, err := ParseSpaces(`[{"tenant_id":7,"space_id":"space-1","raw_kb_id":"raw-1","wiki_kb_id":"wiki-1"}]`)
	require.NoError(t, err)
	s := release.NewService(memoryStore{}, allowAll{},
		map[string][]byte{"candidate_bundle": []byte(testSchema), "evidence": contract},
		release.WithEvidenceVerifier(NewEvidenceVerifier(spaces, reader)))

	items := make([]any, 0, len(evidence))
	for _, e := range evidence {
		items = append(items, e)
	}
	payload, err := json.Marshal(map[string]any{"origin": "SOURCE_SUPPORTED", "state": "present", "evidence": items})
	require.NoError(t, err)
	raw := fmt.Sprintf(`{"contract_version": "1", "origin": "compile", "compiler_identity": "harness/test",
  "members": [{"kind": "claim", "logical_slug": "a", "payload": %s, "member_digest": %q,
               "evidence_refs": [%q], "access_scope": "space"}]}`, payload, memberDigest(t, string(payload)), citedRef)
	_, err = s.Receive(context.Background(), release.Principal{TenantID: 7, Subject: "svc"}, space, []byte(raw))
	return err
}

func refusal(t *testing.T, err error) *release.Error {
	t.Helper()
	var failure *release.Error
	require.True(t, errors.As(err, &failure), "want *release.Error, got %v", err)
	return failure
}

func TestExactQuotesPassAndEachSourceIsReadOnce(t *testing.T) {
	reader := capturedPages()
	require.NoError(t, submit(t, reader, "space-1",
		span(1, 5, 13, "等待期为90日。"),
		span(1, 0, 5, "第一条\r\n"),
		span(2, 0, 3, "宽限期")))
	require.Equal(t, map[string]int{"k-1:2": 1}, reader.calls)
	require.Equal(t, []source.Scope{{TenantID: 7, SpaceID: "space-1"}}, reader.scopes)

	upper := span(2, 3, 6, "六十日")
	upper["file_sha256"] = strings.ToUpper(fileSHA)
	require.NoError(t, submit(t, capturedPages(), "space-1", upper), "fingerprints compare without case")

	hashed := span(1, 3, 12, "\r\n等待期为90日")
	hashed["quote_sha256"] = release.QuoteDigest("\r\n等待期为90日")
	require.NoError(t, submit(t, capturedPages(), "space-1", hashed))
}

func TestAnythingButTheExactCapturedSliceIsAMismatch(t *testing.T) {
	otherFile := span(1, 5, 13, "等待期为90日。")
	otherFile["file_sha256"] = strings.Repeat("cd", 32)
	wrongDigest := span(1, 5, 13, "等待期为90日。")
	wrongDigest["quote_sha256"] = release.QuoteDigest("等待期为60日。")
	noOffsets := span(1, 5, 13, "等待期为90日。")
	noOffsets["locator"] = map[string]any{"kind": "PDF_TEXT_SPAN", "page": 1}

	for name, evidence := range map[string]map[string]any{
		"one character differs":    span(1, 5, 13, "等待期为60日。"),
		"line ending normalized":   span(1, 0, 4, "第一条\n"),
		"offsets shifted":          span(1, 4, 12, "等待期为90日。"),
		"page beyond the document": span(3, 0, 1, "宽"),
		"end beyond the page":      span(2, 0, 7, "宽限期六十日。"),
		"empty range":              span(2, 2, 2, "期"),
		"file fingerprint differs": otherFile,
		"quote digest differs":     wrongDigest,
		"offsets missing":          noOffsets,
	} {
		t.Run(name, func(t *testing.T) {
			failure := refusal(t, submit(t, capturedPages(), "space-1", span(2, 0, 3, "宽限期"), evidence))
			require.Equal(t, release.ErrorEvidenceMismatch, failure.Code)
			require.True(t, strings.HasPrefix(failure.Detail, "/members/0/payload/evidence/1"), failure.Detail)
			require.NotContains(t, failure.Detail, "等待", "details never echo source text")
		})
	}

	reader := capturedPages()
	reader.set.DocumentSHA256 = strings.Repeat("ef", 32)
	failure := refusal(t, submit(t, reader, "space-1", span(2, 0, 3, "宽限期")))
	require.Equal(t, release.ErrorEvidenceMismatch, failure.Code, "the captured revision must be the cited file")
}

func TestOnlyExactPDFTextSpansAreSupported(t *testing.T) {
	ocr := span(1, 5, 13, "等待期为90日。")
	ocr["locator"] = map[string]any{"kind": "OCR_REGION", "page": 1, "bbox": map[string]any{
		"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.05,
	}}
	normalized := span(1, 5, 13, "等待期为90日。")
	normalized["match"] = "NORMALIZED"
	for name, evidence := range map[string]map[string]any{"OCR region": ocr, "normalized match": normalized} {
		t.Run(name, func(t *testing.T) {
			failure := refusal(t, submit(t, capturedPages(), "space-1", evidence))
			require.Equal(t, release.ErrorEvidenceUnsupported, failure.Code)
		})
	}
}

func TestSourcesThatCannotBeReadAreUnverifiable(t *testing.T) {
	for name, err := range map[string]error{
		"scanned, never captured": &source.Error{Code: source.ErrorNotCaptured, Detail: "x"},
		"deleted or foreign":      &source.Error{Code: source.ErrorSourceNotFound, Detail: "x"},
		"artifact damaged":        &source.Error{Code: source.ErrorIntegrity, Detail: "x"},
	} {
		t.Run(name, func(t *testing.T) {
			reader := capturedPages()
			reader.err = err
			failure := refusal(t, submit(t, reader, "space-1", span(2, 0, 3, "宽限期")))
			require.Equal(t, release.ErrorEvidenceUnverifiable, failure.Code)
		})
	}

	failure := refusal(t, submit(t, capturedPages(), "space-9", span(2, 0, 3, "宽限期")))
	require.Equal(t, release.ErrorEvidenceUnverifiable, failure.Code, "a Space without configuration has no sources")
}

func TestStorageOutagesAreNotPassedOffAsEvidenceProblems(t *testing.T) {
	reader := capturedPages()
	reader.err = &source.Error{Code: source.ErrorUnavailable, Detail: "x"}
	err := submit(t, reader, "space-1", span(2, 0, 3, "宽限期"))
	require.Error(t, err)
	var failure *release.Error
	if errors.As(err, &failure) {
		require.NotContains(t, []string{
			release.ErrorEvidenceMismatch, release.ErrorEvidenceUnsupported, release.ErrorEvidenceUnverifiable,
		}, failure.Code)
	}
}
