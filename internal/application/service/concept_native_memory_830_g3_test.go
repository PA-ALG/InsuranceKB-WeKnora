package service

import (
	"bytes"
	"encoding/json"
	"runtime"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

// All data is synthetic. Canonical bytes come from the unchanged legacy oracle,
// never from the optimized encoder whose output is under test.
func syntheticNativeMemory830G3(t testing.TB, count int) (*types.ReadResult, string) {
	t.Helper()
	text := strings.Repeat("中", count)
	identity := conceptNativeParserIdentity830G2{
		ProducerContract: "weknora.docreader.builtin-pdfium-charbox.v1",
		CaptureMode:      conceptNativeCapture830G2,
		Pypdfium2Version: "5.8.0<>&\u2028\u2029", PDFiumVersion: "7543",
	}
	identityRaw, err := canonicalJSON830G2(identity)
	require.NoError(t, err)
	identitySHA := testSHA256Bytes830G2(identityRaw)
	boxes := make([]conceptNativeBBox830G2, count)
	for i := range boxes {
		boxes[i] = conceptNativeBBox830G2{GlobalCodepointStart: i, GlobalCodepointEnd: i + 1, BBox: [4]int{1, 2, 3, 4}}
	}
	projection := conceptNativeProjection830G2{
		Contract: conceptNativeContract830G2, CoordinateSpace: "normalized_0_1e6_top_left",
		SourceSHA256: testSHA256830G2("synthetic-pdf"), MarkdownSHA256: testSHA256830G2(text),
		ParserIdentity: identity, ParserIdentitySHA256: identitySHA,
		Pages: []conceptNativePage830G2{{PageNumber: 1, GlobalCodepointStart: 0, GlobalCodepointEnd: count,
			PageTextSHA256: testSHA256830G2(text), WidthPoints: "100", HeightPoints: "200", BBoxes: boxes}},
	}
	raw, err := canonicalJSON830G2(projection)
	require.NoError(t, err)
	digest := testSHA256Bytes830G2(raw)
	return &types.ReadResult{MarkdownContent: text, NativeStructure: &types.NativeStructureArtifact{
		SchemaVersion: projection.Contract, SourceSHA256: projection.SourceSHA256,
		RawSHA256: digest, SanitizedSHA256: digest, SanitizedJSON: raw,
	}}, identitySHA
}

func TestConceptNativeMemory830G3CanonicalCompatibilityAndAllocations(t *testing.T) {
	const characters = 2048
	result, parser := syntheticNativeMemory830G3(t, characters)
	original := bytes.Clone(result.NativeStructure.SanitizedJSON)
	var last *conceptNativeQuoteIndex830G2
	allocations := testing.AllocsPerRun(2, func() {
		index, err := prepareConceptNativeQuoteIndex830G2(result, result.NativeStructure.SourceSHA256, parser)
		require.NoError(t, err)
		last = index
	})
	require.Equal(t, original, result.NativeStructure.SanitizedJSON)
	require.Equal(t, result.NativeStructure.SanitizedSHA256, testSHA256Bytes830G2(original))
	require.Len(t, last.pages[1].boxes, characters)
	t.Logf("characters=%d native_bytes=%d allocations=%.0f", characters, len(original), allocations)
	// A generous structural bound: one generic map/number tree per character
	// exceeds it. Typed geometry decoding and indexing stay comfortably below it.
	require.Less(t, allocations, float64(characters*10+500), "native preparation must not build a generic per-character JSON tree")
}

func TestConceptNativeMemory830G3StrictValidationRemains(t *testing.T) {
	for _, mutation := range []string{"unknown", "malformed", "coordinate", "missing box", "source hash", "raw hash"} {
		t.Run(mutation, func(t *testing.T) {
			result, parser := syntheticNativeMemory830G3(t, 12)
			var projection conceptNativeProjection830G2
			require.NoError(t, json.Unmarshal(result.NativeStructure.SanitizedJSON, &projection))
			raw := result.NativeStructure.SanitizedJSON
			switch mutation {
			case "unknown":
				raw = append([]byte(`{"unexpected":0,`), raw[1:]...)
			case "malformed":
				raw = raw[:len(raw)-1]
			case "coordinate":
				projection.Pages[0].BBoxes[0].BBox[2] = 1_000_001
			case "missing box":
				projection.Pages[0].BBoxes = projection.Pages[0].BBoxes[1:]
			case "source hash":
				projection.SourceSHA256 = testSHA256830G2("other")
			}
			if mutation == "coordinate" || mutation == "missing box" || mutation == "source hash" {
				var err error
				raw, err = canonicalJSON830G2(projection)
				require.NoError(t, err)
			}
			result.NativeStructure.SanitizedJSON = raw
			result.NativeStructure.SanitizedSHA256 = testSHA256Bytes830G2(raw)
			result.NativeStructure.RawSHA256 = result.NativeStructure.SanitizedSHA256
			if mutation == "raw hash" {
				result.NativeStructure.RawSHA256 = testSHA256830G2("other")
			}
			index, err := prepareConceptNativeQuoteIndex830G2(result, result.NativeStructure.SourceSHA256, parser)
			require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
			require.Nil(t, index)
		})
	}
}

func BenchmarkConceptNativeMemory830G3Preparation(b *testing.B) {
	result, parser := syntheticNativeMemory830G3(b, 50_000)
	b.ReportAllocs()
	b.SetBytes(int64(len(result.NativeStructure.SanitizedJSON)))
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		index, err := prepareConceptNativeQuoteIndex830G2(result, result.NativeStructure.SourceSHA256, parser)
		if err != nil {
			b.Fatal(err)
		}
		runtime.KeepAlive(index)
	}
}
