package service

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"
	"testing"
	"unicode"

	"github.com/Tencent/WeKnora/internal/enterprise/capture"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

// captureTestKeys is a fixed signing ring for first-parse captures in tests (S7d-2c-3b).
func captureTestKeys(t *testing.T) *capture.Keys {
	t.Helper()
	key := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{0x63}, ed25519.SeedSize))
	return capture.NewKeys("capture-test-key", map[string]ed25519.PrivateKey{"capture-test-key": key})
}

func captureTestSHA256(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])
}

// captureTestJSON encodes like the native capture contract: sorted keys (maps), no HTML escaping,
// no trailing newline.
func captureTestJSON(t *testing.T, value any) []byte {
	t.Helper()
	var out bytes.Buffer
	encoder := json.NewEncoder(&out)
	encoder.SetEscapeHTML(false)
	require.NoError(t, encoder.Encode(value))
	return bytes.TrimSuffix(out.Bytes(), []byte("\n"))
}

// firstParseNative is a builtin PDF parse of the bytes "pdf" whose native structure passes
// capture.ValidateNative: one page per text, pages joined by the two-newline separator, and a
// character box for every non-space character.
func firstParseNative(t *testing.T, pages ...string) *types.ReadResult {
	t.Helper()
	identity := map[string]any{
		"capture_mode":      capture.NativeCaptureMode,
		"pdfium_version":    "7543",
		"producer_contract": "weknora.docreader.builtin-pdfium-charbox.v1",
		"pypdfium2_version": "5.8.0",
	}
	markdown := strings.Join(pages, "\n\n")
	nativePages := []map[string]any{}
	offset := 0
	for n, text := range pages {
		runes := []rune(text)
		boxes := []map[string]any{}
		for i, r := range runes {
			if !unicode.IsSpace(r) {
				boxes = append(boxes, map[string]any{
					"bbox":                   [4]int{100000, 100000, 200000, 200000},
					"global_codepoint_end":   offset + i + 1,
					"global_codepoint_start": offset + i,
				})
			}
		}
		nativePages = append(nativePages, map[string]any{
			"bboxes":                 boxes,
			"global_codepoint_end":   offset + len(runes),
			"global_codepoint_start": offset,
			"height_points":          "200",
			"page_number":            n + 1,
			"page_text_sha256":       captureTestSHA256(text),
			"width_points":           "100",
		})
		offset += len(runes) + 2
	}
	projection := map[string]any{
		"contract":               "builtin-pdfium-native-locators.v1",
		"coordinate_space":       "normalized_0_1e6_top_left",
		"markdown_sha256":        captureTestSHA256(markdown),
		"pages":                  nativePages,
		"parser_identity":        identity,
		"parser_identity_sha256": captureTestSHA256(string(captureTestJSON(t, identity))),
		"source_sha256":          captureTestSHA256("pdf"),
	}
	data := captureTestJSON(t, projection)
	digest := captureTestSHA256(string(data))
	return &types.ReadResult{
		MarkdownContent: markdown,
		NativeStructure: &types.NativeStructureArtifact{
			SchemaVersion:   "builtin-pdfium-native-locators.v1",
			SourceSHA256:    captureTestSHA256("pdf"),
			RawSHA256:       digest,
			SanitizedSHA256: digest,
			SanitizedJSON:   data,
		},
	}
}
