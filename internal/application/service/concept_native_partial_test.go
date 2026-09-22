package service

import (
	"encoding/json"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"os"
	"testing"
)

func TestConceptNativePartialActualCapture(t *testing.T) {
	path := os.Getenv("NATIVE_CAPTURE_FIXTURE")
	if path == "" {
		t.Skip("optional real PDF fixture")
	}
	raw, err := os.ReadFile(path)
	require.NoError(t, err)
	var fixture struct {
		Markdown string `json:"markdown"`
		Envelope struct {
			RawSHA       string          `json:"raw_sha256"`
			SanitizedSHA string          `json:"sanitized_sha256"`
			SourceSHA    string          `json:"source_sha256"`
			Schema       string          `json:"schema_version"`
			Native       json.RawMessage `json:"sanitized_json"`
		} `json:"envelope"`
	}
	require.NoError(t, json.Unmarshal(raw, &fixture))
	var header conceptNativeHeader830G2
	require.NoError(t, json.Unmarshal(fixture.Envelope.Native, &header))
	result := &types.ReadResult{MarkdownContent: fixture.Markdown, NativeStructure: &types.NativeStructureArtifact{SchemaVersion: fixture.Envelope.Schema, SourceSHA256: fixture.Envelope.SourceSHA, RawSHA256: fixture.Envelope.RawSHA, SanitizedSHA256: fixture.Envelope.SanitizedSHA, SanitizedJSON: fixture.Envelope.Native}}
	index, err := prepareConceptNativeQuoteIndex830G2(result, fixture.Envelope.SourceSHA, header.ParserIdentitySHA256)
	require.NoError(t, err)
	require.NotEmpty(t, index.pages)
}

func TestConceptNativePartialLocatorsIsolateBadQuote(t *testing.T) {
	result, _ := testNativeResult830G2(t)
	var n map[string]any
	require.NoError(t, json.Unmarshal(result.NativeStructure.SanitizedJSON, &n))
	n["contract"] = "builtin-pdfium-native-locators.v2"
	identity := n["parser_identity"].(map[string]any)
	identity["producer_contract"] = "weknora.docreader.builtin-pdfium-charbox.v2"
	iraw, err := canonicalJSON830G2(identity)
	require.NoError(t, err)
	identitySHA := testSHA830G2(string(iraw))
	n["parser_identity_sha256"] = identitySHA
	page := n["pages"].([]any)[0].(map[string]any)
	page["bboxes"] = page["bboxes"].([]any)[:1]
	page["unavailable_ranges"] = []any{map[string]any{"global_codepoint_start": 1, "global_codepoint_end": 2, "reason": "bbox_invalid"}}
	raw, err := canonicalJSON830G2(n)
	require.NoError(t, err)
	result.NativeStructure.SchemaVersion = "builtin-pdfium-native-locators.v2"
	result.NativeStructure.SanitizedJSON = raw
	result.NativeStructure.RawSHA256 = testSHA830G2(string(raw))
	result.NativeStructure.SanitizedSHA256 = result.NativeStructure.RawSHA256
	for _, good := range []struct {
		page  int
		quote string
	}{{1, "A"}, {2, "中"}} {
		_, err := resolveConceptNativeQuote830G2(result, testSHA830G2("pdf"), identitySHA, good.page, good.quote)
		require.NoError(t, err)
	}
	_, err = resolveConceptNativeQuote830G2(result, testSHA830G2("pdf"), identitySHA, 1, "A😀")
	require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
}
