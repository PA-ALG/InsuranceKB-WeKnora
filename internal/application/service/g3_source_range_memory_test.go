package service

import (
	"encoding/json"
	"fmt"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

func g3SourceRangeMemoryFixture(t testing.TB) (*g3FirstParseRecord, []types.RevisionManifestChunk, *conceptNativeQuoteIndex830G2) {
	t.Helper()
	const characters = 32_768
	result, parser := syntheticNativeMemory830G3(t, characters)
	// Unicode coordinates are code points: byte offsets differ for both characters.
	text := strings.Repeat("中😀", characters/2)
	var projection conceptNativeProjection830G2
	require.NoError(t, json.Unmarshal(result.NativeStructure.SanitizedJSON, &projection))
	projection.MarkdownSHA256 = testSHA256830G2(text)
	projection.Pages[0].PageTextSHA256 = testSHA256830G2(text)
	raw, err := canonicalJSON830G2(projection)
	require.NoError(t, err)
	result.MarkdownContent = text
	result.NativeStructure.SanitizedJSON = raw
	result.NativeStructure.SanitizedSHA256 = testSHA256Bytes830G2(raw)
	result.NativeStructure.RawSHA256 = result.NativeStructure.SanitizedSHA256
	index, err := prepareConceptNativeQuoteIndex830G2(result, result.NativeStructure.SourceSHA256, parser)
	require.NoError(t, err)
	record := &g3FirstParseRecord{Markdown: text, Native: result.NativeStructure}
	manifest := []types.RevisionManifestChunk{}
	runes := []rune(text)
	for i := 0; i < 128; i++ {
		start, end := i*256, (i+1)*256
		content := string(runes[start:end])
		record.Chunks = append(record.Chunks, g3FirstParseRange{Index: i, Start: start, End: end, ContentSHA256: testSHA256830G2(content)})
		manifest = append(manifest, types.RevisionManifestChunk{ID: fmt.Sprintf("chunk-%03d", i), Index: i, Content: content})
	}
	return record, manifest, index
}

func measureG3SourceRangeBytes(t *testing.T, operation func()) uint64 {
	t.Helper()
	runtime.GC()
	var before, after runtime.MemStats
	runtime.ReadMemStats(&before)
	started := time.Now()
	operation()
	runtime.ReadMemStats(&after)
	allocated := after.TotalAlloc - before.TotalAlloc
	t.Logf("allocated_bytes=%d elapsed=%s", allocated, time.Since(started))
	return allocated
}

func TestG3SourceRangeMemoryBindingsBounded(t *testing.T) {
	record, manifest, _ := g3SourceRangeMemoryFixture(t)
	original, err := json.Marshal(record)
	require.NoError(t, err)
	var bindings map[string]g3FirstParseRange
	allocated := measureG3SourceRangeBytes(t, func() {
		bindings, err = g3FirstParseBindings(record, manifest)
	})
	require.NoError(t, err)
	require.Len(t, bindings, len(manifest))
	for i, chunk := range manifest {
		require.Equal(t, record.Chunks[i], bindings[chunk.ID])
	}
	after, err := json.Marshal(record)
	require.NoError(t, err)
	require.Equal(t, original, after)
	require.Less(t, allocated, uint64(4*1024*1024), "binding must not allocate full-document runes for every chunk")
}

func TestG3SourceRangeMemoryMappingsBoundedAndLegacyEquivalent(t *testing.T) {
	record, manifest, index := g3SourceRangeMemoryFixture(t)
	ranges, err := g3FirstParseBindings(record, manifest)
	require.NoError(t, err)
	mappings := make([]G3PlatformChunkPageMappingV1, 0, len(manifest))
	allocated := measureG3SourceRangeBytes(t, func() {
		for _, chunk := range manifest {
			mappings = append(mappings, g3PlatformChunkPageMapping(chunk, index, ranges))
		}
	})
	// Manually constructed historical indexes have no new full-rune backing field.
	legacy := &conceptNativeQuoteIndex830G2{text: index.text, pages: index.pages,
		sourceSHA: index.sourceSHA, parserIdentitySHA: index.parserIdentitySHA, coordinateSpace: index.coordinateSpace}
	for i, chunk := range manifest {
		expected := g3PlatformChunkPageMapping(chunk, legacy, ranges)
		require.Equal(t, expected, mappings[i])
		require.Equal(t, G3PlatformChunkMappingExactBlock, mappings[i].Status)
		require.Equal(t, record.Chunks[i].Start, *mappings[i].BlockGlobalStart)
		require.Equal(t, record.Chunks[i].End, *mappings[i].BlockGlobalEnd)
	}
	require.Less(t, allocated, uint64(4*1024*1024), "snapshot mapping must reuse validated document runes")
}

func TestG3SourceRangeMemoryInvalidEvidenceStillRefused(t *testing.T) {
	record, manifest, index := g3SourceRangeMemoryFixture(t)
	for _, kind := range []string{"negative", "overflow", "empty", "wrong hash", "wrong position"} {
		t.Run(kind, func(t *testing.T) {
			original := record.Chunks[0]
			r := original
			switch kind {
			case "negative":
				r.Start = -1
			case "overflow":
				r.End = 32_769
			case "empty":
				r.End = r.Start
			case "wrong hash":
				r.ContentSHA256 = testSHA256830G2("changed")
			case "wrong position":
				r.Start++
				r.End++
			}
			changed := *record
			changed.Chunks = append([]g3FirstParseRange(nil), record.Chunks...)
			changed.Chunks[0] = r
			_, err := g3FirstParseBindings(&changed, manifest)
			require.ErrorIs(t, err, ErrConceptSourceAuthorityUnavailable830G2)
			require.False(t, g3FirstParseRangeMatches(record.Markdown, manifest[0].Content, r))
			mapping := g3PlatformChunkPageMapping(manifest[0], index, map[string]g3FirstParseRange{manifest[0].ID: r})
			require.Equal(t, G3PlatformChunkMappingUnresolved, mapping.Status)
		})
	}
}

func BenchmarkG3SourceRangeMemory(b *testing.B) {
	record, manifest, index := g3SourceRangeMemoryFixture(b)
	ranges, err := g3FirstParseBindings(record, manifest)
	require.NoError(b, err)
	b.Run("Bindings", func(b *testing.B) {
		b.ReportAllocs()
		for i := 0; i < b.N; i++ {
			value, err := g3FirstParseBindings(record, manifest)
			if err != nil {
				b.Fatal(err)
			}
			runtime.KeepAlive(value)
		}
	})
	b.Run("Mappings", func(b *testing.B) {
		b.ReportAllocs()
		for i := 0; i < b.N; i++ {
			for _, chunk := range manifest {
				value := g3PlatformChunkPageMapping(chunk, index, ranges)
				runtime.KeepAlive(value)
			}
		}
	})
}
