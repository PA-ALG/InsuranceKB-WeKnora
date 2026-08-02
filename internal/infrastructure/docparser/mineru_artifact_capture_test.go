package docparser

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
)

type fakeMinerUCaptureReader struct {
	result         *types.ReadResult
	err            error
	calls          minerUCloudCallLedger
	crossPageFacts *minerUCrossPageProjection
	reads          int
}

func TestProjectMinerUCrossPageFactsFromNativeMiddleOnly(t *testing.T) {
	t.Parallel()
	contentList := `[{"type":"table","page_idx":0,"bbox":[0,0,1,1],"table_body":"<table><tr><td>looks continued</td></tr></table>"}]`
	presentMiddle := `{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[` +
		`{"page_idx":0,"para_blocks":[{"type":"text","index":4,"lines":[{"spans":[` +
		`{"type":"text","content":"Bearer secret body","bbox":[1,2,3,4],"cross_page":true}]}]}]},` +
		`{"page_idx":1,"para_blocks":[]}]}`
	absentMiddle := `{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[` +
		`{"page_idx":0,"para_blocks":[{"type":"table","index":1,"blocks":[]}]},` +
		`{"page_idx":1,"para_blocks":[]}]}`
	ambiguousMiddle := `{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[` +
		`{"page_idx":0,"para_blocks":[]},{"page_idx":1,"para_blocks":[` +
		`{"type":"table","index":2,"lines_deleted":true,"blocks":[]}]}]}`

	tests := []struct {
		name       string
		middle     string
		wantStatus string
		wantCount  int
	}{
		{"cross-page-boolean-is-ambiguous", presentMiddle, minerUCrossPageAmbiguous, 0},
		{"absent", absentMiddle, minerUCrossPageAbsent, 0},
		{"ambiguous", ambiguousMiddle, minerUCrossPageAmbiguous, 0},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			zipBytes := crossPageFixtureZip(t, []crossPageFixtureEntry{
				{"nested/result.md", "private presentation"},
				{"nested/result_content_list.json", contentList},
				{"nested/result_middle.json", tc.middle},
			})
			got, err := projectMinerUCrossPageZip(zipBytes, minerUTermsSourceSHA256)
			if err != nil {
				t.Fatal(err)
			}
			if got.Status != tc.wantStatus || got.RelationCount != tc.wantCount ||
				got.SourceSHA256 != minerUTermsSourceSHA256 || got.MinerUVersion != "3.4.4" {
				t.Fatalf("projection drifted: %#v", got)
			}
			encoded, err := json.Marshal(got)
			if err != nil {
				t.Fatal(err)
			}
			for _, forbidden := range []string{"Bearer secret body", "private presentation", "bbox", "[1,2,3,4]", "nested/"} {
				if bytes.Contains(encoded, []byte(forbidden)) {
					t.Fatalf("projection leaked %q: %s", forbidden, encoded)
				}
			}
		})
	}

	t.Run("content-list-is-not-cross-page-authority", func(t *testing.T) {
		zipBytes := crossPageFixtureZip(t, []crossPageFixtureEntry{
			{"result.md", "continued"}, {"result_content_list.json", contentList},
		})
		got, err := projectMinerUCrossPageZip(zipBytes, minerURatesSourceSHA256)
		if err != nil {
			t.Fatal(err)
		}
		if got.Status != minerUCrossPageNotAvailable || got.RelationCount != 0 {
			t.Fatalf("content-list minted native relation authority: %#v", got)
		}
	})

	t.Run("adjacency-header-and-html-are-not-native-relations", func(t *testing.T) {
		looksContinuous := `[{"type":"table","page_idx":0,"bbox":[0,0,1,1],` +
			`"table_body":"<table><tr><th>same header</th></tr></table>"},` +
			`{"type":"table","page_idx":1,"bbox":[0,0,1,1],` +
			`"table_body":"<table><tr><th>same header</th></tr></table>"}]`
		zipBytes := crossPageFixtureZip(t, []crossPageFixtureEntry{
			{"result.md", "continued on adjacent page"},
			{"result_content_list.json", looksContinuous},
			{"result_middle.json", absentMiddle},
		})
		got, err := projectMinerUCrossPageZip(zipBytes, minerURatesSourceSHA256)
		if err != nil {
			t.Fatal(err)
		}
		if got.Status != minerUCrossPageAbsent || got.RelationCount != 0 || len(got.Relations) != 0 {
			t.Fatalf("presentation similarity minted a relation: %#v", got)
		}
	})

	t.Run("rate-table-boolean-remains-ambiguous", func(t *testing.T) {
		tableMiddle := `{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[` +
			`{"page_idx":0,"para_blocks":[{"type":"table","index":0,"blocks":[` +
			`{"type":"table_body","lines":[{"spans":[{"type":"table","cross_page":true}]}]}]}]},` +
			`{"page_idx":1,"para_blocks":[]}]}`
		got, err := projectMinerUCrossPageZip(
			crossPageFixtureZip(t, []crossPageFixtureEntry{{"result_middle.json", tableMiddle}}),
			minerURatesSourceSHA256,
		)
		if err != nil {
			t.Fatal(err)
		}
		if got.Status != minerUCrossPageAmbiguous || got.RelationCount != 0 || len(got.Relations) != 0 {
			t.Fatalf("boolean table marker was promoted to a relation: %#v", got)
		}
	})

	t.Run("converter-enables-projection-only-for-capture-policy", func(t *testing.T) {
		zipBytes := crossPageFixtureZip(t, []crossPageFixtureEntry{
			{"result.md", "presentation"}, {"result_content_list.json", contentList},
			{"result_middle.json", presentMiddle},
		})
		_, _, _, projected, err := extractMinerUZipBytesWithProjection(
			zipBytes, minerUTermsSourceSHA256, "pipeline", true,
		)
		if err != nil || projected == nil || projected.Status != minerUCrossPageAmbiguous ||
			projected.RelationCount != 0 {
			t.Fatalf("capture-only projection seam failed: projection=%#v err=%v", projected, err)
		}
		_, _, _, ordinary, err := extractMinerUZipBytesWithProjection(
			zipBytes, minerUTermsSourceSHA256, "pipeline", false,
		)
		if err != nil || ordinary != nil {
			t.Fatalf("ordinary reader behavior was widened: projection=%#v err=%v", ordinary, err)
		}
	})

	t.Run("member-order-and-path-do-not-change-semantic-projection", func(t *testing.T) {
		first := crossPageFixtureZip(t, []crossPageFixtureEntry{
			{"a/result_middle.json", presentMiddle}, {"a/result.md", "private presentation"},
		})
		second := crossPageFixtureZip(t, []crossPageFixtureEntry{
			{"renamed/result.md", "private presentation"}, {"renamed/result_middle.json", presentMiddle},
		})
		one, err := projectMinerUCrossPageZip(first, minerUTermsSourceSHA256)
		if err != nil {
			t.Fatal(err)
		}
		two, err := projectMinerUCrossPageZip(second, minerUTermsSourceSHA256)
		if err != nil {
			t.Fatal(err)
		}
		if one.ProjectionSHA256 != two.ProjectionSHA256 ||
			one.MemberInventorySHA256 != two.MemberInventorySHA256 || one.RawZIPSHA256 == two.RawZIPSHA256 {
			t.Fatalf("semantic/container custody was conflated: one=%#v two=%#v", one, two)
		}
		changed, err := projectMinerUCrossPageZip(
			crossPageFixtureZip(t, []crossPageFixtureEntry{{"result_middle.json", absentMiddle}}),
			minerUTermsSourceSHA256,
		)
		if err != nil {
			t.Fatal(err)
		}
		if changed.ProjectionSHA256 == one.ProjectionSHA256 {
			t.Fatal("relation value change did not change projection hash")
		}
	})
}

func TestProjectMinerUCrossPageRejectsHostileZIP(t *testing.T) {
	t.Parallel()
	validMiddle := `{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[]}`
	tests := map[string][]crossPageFixtureEntry{
		"zip-slip":        {{"../result_middle.json", validMiddle}},
		"duplicate":       {{"a//result_middle.json", validMiddle}, {"a/result_middle.json", validMiddle}},
		"secret-name":     {{"Bearer-token_middle.json", validMiddle}},
		"unsupported":     {{"result_middle.json", validMiddle}, {"payload.exe", "x"}},
		"multiple-middle": {{"a_middle.json", validMiddle}, {"b_middle.json", validMiddle}},
		"sensitive-key":   {{"result_middle.json", `{"_backend":"pipeline","_version_name":"3.4.4","api_key":"x","pdf_info":[]}`}},
	}
	t.Run("non-target-source", func(t *testing.T) {
		if _, err := projectMinerUCrossPageZip(
			crossPageFixtureZip(t, []crossPageFixtureEntry{{"result_middle.json", validMiddle}}),
			strings.Repeat("f", 64),
		); err == nil {
			t.Fatal("non-target source entered 062 projection")
		}
	})
	for name, entries := range tests {
		t.Run(name, func(t *testing.T) {
			if _, err := projectMinerUCrossPageZip(crossPageFixtureZip(t, entries), minerUTermsSourceSHA256); err == nil {
				t.Fatal("hostile or ambiguous ZIP was accepted")
			}
		})
	}
	t.Run("member-count-budget", func(t *testing.T) {
		entries := make([]crossPageFixtureEntry, 0, maxMinerUCrossPageMembers+1)
		for index := 0; index <= maxMinerUCrossPageMembers; index++ {
			entries = append(entries, crossPageFixtureEntry{fmt.Sprintf("%03d.md", index), "x"})
		}
		if _, err := projectMinerUCrossPageZip(crossPageFixtureZip(t, entries), minerUTermsSourceSHA256); err == nil {
			t.Fatal("member count budget was not enforced")
		}
	})
	t.Run("compression-bomb-budget", func(t *testing.T) {
		entries := []crossPageFixtureEntry{{"result_middle.json", strings.Repeat("x", 2<<20)}}
		if _, err := projectMinerUCrossPageZip(crossPageFixtureZip(t, entries), minerUTermsSourceSHA256); err == nil {
			t.Fatal("compression ratio budget was not enforced")
		}
	})
	for name, mode := range map[string]os.FileMode{
		"symlink-middle": os.ModeSymlink | 0o777,
		"special-middle": os.ModeNamedPipe | 0o600,
	} {
		t.Run(name, func(t *testing.T) {
			middle := `{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[` +
				`{"page_idx":0,"para_blocks":[]}]}`
			if _, err := projectMinerUCrossPageZip(
				crossPageFixtureZipWithMode(t, "result_middle.json", middle, mode),
				minerUTermsSourceSHA256,
			); err == nil || !strings.Contains(err.Error(), "unsupported member class") {
				t.Fatalf("non-regular ZIP member was not rejected by class: %v", err)
			}
		})
	}
}

func TestMinerUCaptureZIPBodyReadIsBounded(t *testing.T) {
	t.Parallel()
	reader := &countingByteReader{}
	if _, err := readMinerUCaptureZIPBody(reader, 32); err == nil ||
		!errors.Is(err, ErrMinerUCrossPageProjectionInvalid) {
		t.Fatalf("oversized capture ZIP body was not typed: %v", err)
	}
	if reader.readBytes != 33 {
		t.Fatalf("capture ZIP reader consumed %d bytes, want limit+1", reader.readBytes)
	}
}

func TestCaptureMinerUNativeStructureCarriesExactCrossPageProjection(t *testing.T) {
	t.Parallel()
	repositoryPDF := filepath.Join("..", "..", "..", "dataset", "shouxian_product",
		"平安e生保（尊享版）医疗保险", "保险条款.pdf")
	pdfBytes, err := os.ReadFile(repositoryPDF)
	if err != nil {
		t.Fatal(err)
	}
	pdfHash := sha256.Sum256(pdfBytes)
	if hex.EncodeToString(pdfHash[:]) != minerUTermsSourceSHA256 {
		t.Fatal("frozen terms PDF identity drifted")
	}
	parent := t.TempDir()
	sourcePath := filepath.Join(parent, "source.pdf")
	if err := os.WriteFile(sourcePath, pdfBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	middle := `{"_backend":"pipeline","_version_name":"3.4.4","pdf_info":[` +
		`{"page_idx":0,"para_blocks":[{"type":"text","lines":[{"spans":[` +
		`{"type":"text","cross_page":true}]}]}]},{"page_idx":1,"para_blocks":[]}]}`
	projection, err := projectMinerUCrossPageZip(
		crossPageFixtureZip(t, []crossPageFixtureEntry{{"result_middle.json", middle}}),
		minerUTermsSourceSHA256,
	)
	if err != nil {
		t.Fatal(err)
	}
	sanitized := []byte(`{"contract":"mineru-native-structure.v1","pages":[],"unsupported":[]}`)
	sanitizedHash := sha256.Sum256(sanitized)
	reader := &fakeMinerUCaptureReader{
		result: &types.ReadResult{NativeStructure: &types.NativeStructureArtifact{
			SchemaVersion: minerUStructureSchema, SourceSHA256: minerUTermsSourceSHA256,
			RawSHA256: strings.Repeat("a", 64), SanitizedSHA256: hex.EncodeToString(sanitizedHash[:]),
			SanitizedJSON: sanitized,
		}},
		calls:          minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		crossPageFacts: projection,
	}
	outputPath, err := captureMinerUNativeStructure(
		context.Background(),
		MinerUArtifactCaptureRequest{
			SourcePath: sourcePath, SourceSHA256: minerUTermsSourceSHA256,
			OutputDir:       filepath.Join(parent, "evidence"),
			ParserOverrides: map[string]string{"mineru_cloud_model": "pipeline"},
		},
		func(string) (string, bool) { return "in-memory-secret", true },
		func(map[string]string) minerUCaptureReader { return reader },
		fixedCaptureClock(time.Time{}, time.Millisecond),
	)
	if err != nil {
		t.Fatal(err)
	}
	payload, err := os.ReadFile(outputPath)
	if err != nil {
		t.Fatal(err)
	}
	var evidence minerUCaptureEvidence
	if err := json.Unmarshal(payload, &evidence); err != nil {
		t.Fatal(err)
	}
	if evidence.CrossPageFacts == nil || evidence.CrossPageFacts.Status != minerUCrossPageAmbiguous ||
		evidence.CrossPageFacts.RelationCount != 0 || len(evidence.CrossPageFacts.Relations) != 0 ||
		evidence.CrossPageFacts.SourceSHA256 != minerUTermsSourceSHA256 {
		t.Fatalf("private capture evidence dropped projection custody: %#v", evidence.CrossPageFacts)
	}
	for _, forbidden := range []string{repositoryPDF, sourcePath, "in-memory-secret", "cross_page\":true"} {
		if bytes.Contains(payload, []byte(forbidden)) {
			t.Fatalf("capture evidence leaked %q", forbidden)
		}
	}
}

type crossPageFixtureEntry struct{ name, body string }

func crossPageFixtureZip(t *testing.T, entries []crossPageFixtureEntry) []byte {
	t.Helper()
	var buffer bytes.Buffer
	writer := zip.NewWriter(&buffer)
	for _, entry := range entries {
		file, err := writer.Create(entry.name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := file.Write([]byte(entry.body)); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	return buffer.Bytes()
}

func crossPageFixtureZipWithMode(t *testing.T, name, body string, mode os.FileMode) []byte {
	t.Helper()
	var buffer bytes.Buffer
	writer := zip.NewWriter(&buffer)
	header := &zip.FileHeader{Name: name, Method: zip.Store}
	header.SetMode(mode)
	file, err := writer.CreateHeader(header)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := file.Write([]byte(body)); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	return buffer.Bytes()
}

type countingByteReader struct{ readBytes int64 }

func (r *countingByteReader) Read(payload []byte) (int, error) {
	for index := range payload {
		payload[index] = 'x'
	}
	r.readBytes += int64(len(payload))
	return len(payload), nil
}

var _ io.Reader = (*countingByteReader)(nil)

func (f *fakeMinerUCaptureReader) Read(_ context.Context, req *types.ReadRequest) (*types.ReadResult, error) {
	f.reads++
	if req.FileName != "source.pdf" || req.ParserEngine != "mineru_cloud" {
		return nil, errors.New("capture request identity drift")
	}
	return f.result, f.err
}

func (f *fakeMinerUCaptureReader) captureCallLedger() minerUCloudCallLedger { return f.calls }

func (f *fakeMinerUCaptureReader) captureCrossPageProjection() *minerUCrossPageProjection {
	return f.crossPageFacts
}

func TestCaptureMinerUNativeStructureWritesDeterministicSanitizedEvidence(t *testing.T) {
	t.Parallel()
	parent := t.TempDir()
	sourcePaths := []string{
		filepath.Join(parent, "machine-a", "source.pdf"),
		filepath.Join(parent, "machine-b", "source.pdf"),
	}
	source := []byte("exact synthetic pdf bytes")
	for _, sourcePath := range sourcePaths {
		if err := os.Mkdir(filepath.Dir(sourcePath), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(sourcePath, source, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	sourceHash := sha256.Sum256(source)
	sourceSHA := hex.EncodeToString(sourceHash[:])
	sanitized := []byte(`{"contract":"mineru-native-structure.v1","pages":[],"unsupported":[]}`)
	sanitizedHash := sha256.Sum256(sanitized)
	artifact := &types.NativeStructureArtifact{
		SchemaVersion:   "mineru-native-structure.v1",
		SourceSHA256:    sourceSHA,
		RawSHA256:       strings.Repeat("a", 64),
		SanitizedSHA256: hex.EncodeToString(sanitizedHash[:]),
		SanitizedJSON:   sanitized,
	}
	newReader := func(overrides map[string]string) minerUCaptureReader {
		if overrides["mineru_api_key"] != "never-serialize-this-secret" || overrides["mineru_cloud_model"] != "pipeline" {
			t.Fatalf("reader overrides drifted: %#v", overrides)
		}
		return &fakeMinerUCaptureReader{
			result: &types.ReadResult{
				MarkdownContent: "private body must be discarded",
				NativeStructure: artifact,
			},
			calls: minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 3, ZIPGET: 1},
		}
	}
	lookup := func(key string) (string, bool) {
		if key != minerUAPIKeyEnvironmentVariable {
			t.Fatalf("unexpected environment lookup: %s", key)
		}
		return "never-serialize-this-secret", true
	}

	var outputs [][]byte
	for index := 0; index < 2; index++ {
		outputDir := filepath.Join(parent, "capture-"+string(rune('a'+index)))
		outputPath, err := captureMinerUNativeStructure(
			context.Background(),
			MinerUArtifactCaptureRequest{
				SourcePath:   sourcePaths[index],
				SourceSHA256: sourceSHA,
				OutputDir:    outputDir,
				ParserOverrides: map[string]string{
					"mineru_cloud_model":          "pipeline",
					"mineru_cloud_enable_formula": "true",
					"mineru_cloud_enable_table":   "true",
					"mineru_cloud_enable_ocr":     "true",
					"mineru_cloud_language":       "ch",
				},
			},
			lookup,
			newReader,
			fixedCaptureClock(time.Unix(1_700_000_000, 0), 125*time.Millisecond),
		)
		if err != nil {
			t.Fatalf("capture %d: %v", index, err)
		}
		info, err := os.Stat(outputDir)
		if err != nil || info.Mode().Perm() != 0o700 {
			t.Fatalf("output directory is not private: info=%v err=%v", info, err)
		}
		if filepath.Base(outputPath) != minerUCaptureFileName {
			t.Fatalf("unexpected output path: %s", outputPath)
		}
		fileInfo, err := os.Stat(outputPath)
		if err != nil || fileInfo.Mode().Perm() != 0o600 {
			t.Fatalf("output file is not private: info=%v err=%v", fileInfo, err)
		}
		payload, err := os.ReadFile(outputPath)
		if err != nil {
			t.Fatal(err)
		}
		outputs = append(outputs, payload)
		for _, forbidden := range []string{
			"never-serialize-this-secret", "private body must be discarded", sourcePaths[index],
			"https://", "signed_url", "source.pdf",
		} {
			if strings.Contains(string(payload), forbidden) {
				t.Fatalf("capture leaked %q: %s", forbidden, payload)
			}
		}
		var decoded struct {
			Contract            string          `json:"contract"`
			SourceSHA256        string          `json:"source_sha256"`
			RawSHA256           string          `json:"raw_sha256"`
			SanitizedSHA256     string          `json:"sanitized_sha256"`
			SanitizedArtifact   json.RawMessage `json:"sanitized_artifact"`
			Parser              map[string]any  `json:"parser"`
			Calls               map[string]int  `json:"calls"`
			LatencyMilliseconds int64           `json:"latency_milliseconds"`
			Status              string          `json:"status"`
		}
		if err := json.Unmarshal(payload, &decoded); err != nil {
			t.Fatal(err)
		}
		if decoded.Contract != minerUCaptureContract || decoded.SourceSHA256 != sourceSHA ||
			decoded.RawSHA256 != artifact.RawSHA256 || decoded.SanitizedSHA256 != artifact.SanitizedSHA256 ||
			decoded.Status != "completed" || decoded.LatencyMilliseconds != 125 {
			t.Fatalf("capture ledger drifted: %#v", decoded)
		}
		if decoded.Calls["allocation_post"] != 1 || decoded.Calls["upload_put"] != 1 ||
			decoded.Calls["status_get"] != 3 || decoded.Calls["zip_get"] != 1 {
			t.Fatalf("call ledger drifted: %#v", decoded.Calls)
		}
		if decoded.Parser["implementation"] != minerUCaptureParserImplementation ||
			decoded.Parser["native_structure_schema"] != minerUStructureSchema || decoded.Parser["config_sha256"] == "" {
			t.Fatalf("parser identity is incomplete: %#v", decoded.Parser)
		}
		var object map[string]json.RawMessage
		if err := json.Unmarshal(payload, &object); err != nil {
			t.Fatal(err)
		}
		if _, exists := object["source_path_identity_sha256"]; exists {
			t.Fatal("evidence retained a machine-local path-derived identity")
		}
		if string(decoded.SanitizedArtifact) != string(sanitized) {
			t.Fatalf("sanitized artifact drifted: %s", decoded.SanitizedArtifact)
		}
	}
	if string(outputs[0]) != string(outputs[1]) {
		t.Fatal("identical capture inputs did not produce deterministic evidence")
	}
}

func TestPublishMinerUCaptureEvidenceIsAtomicNoReplace(t *testing.T) {
	t.Parallel()
	payload := []byte(`{"status":"completed"}` + "\n")
	t.Run("concurrent-existing-final-is-preserved", func(t *testing.T) {
		outputDir := filepath.Join(t.TempDir(), "capture")
		foreign := []byte("foreign evidence")
		_, err := publishMinerUCaptureEvidence(outputDir, payload, minerUCapturePublishHooks{
			beforePublish: func(finalPath string) error {
				return os.WriteFile(finalPath, foreign, 0o600)
			},
		})
		if err == nil {
			t.Fatal("no-replace publication accepted an existing final")
		}
		finalPath := filepath.Join(outputDir, minerUCaptureFileName)
		got, readErr := os.ReadFile(finalPath)
		if readErr != nil || string(got) != string(foreign) {
			t.Fatalf("existing final was overwritten: got=%q err=%v", got, readErr)
		}
		assertNoCaptureTempFiles(t, outputDir)
	})

	t.Run("failed-write-never-exposes-final", func(t *testing.T) {
		outputDir := filepath.Join(t.TempDir(), "capture")
		_, err := publishMinerUCaptureEvidence(outputDir, payload, minerUCapturePublishHooks{
			writeTemp: func(*os.File, []byte) error { return errors.New("synthetic write failure") },
		})
		if err == nil {
			t.Fatal("synthetic write failure was accepted")
		}
		if _, statErr := os.Stat(filepath.Join(outputDir, minerUCaptureFileName)); !errors.Is(statErr, os.ErrNotExist) {
			t.Fatalf("failed write exposed a final file: %v", statErr)
		}
		if _, statErr := os.Stat(outputDir); statErr == nil {
			assertNoCaptureTempFiles(t, outputDir)
		}
	})
}

func assertNoCaptureTempFiles(t *testing.T, outputDir string) {
	t.Helper()
	entries, err := os.ReadDir(outputDir)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".mineru-native-structure-") {
			t.Fatalf("temporary capture file was not cleaned: %s", entry.Name())
		}
	}
}

func TestCaptureMinerUNativeStructureFailsBeforeProviderOrOutput(t *testing.T) {
	t.Parallel()
	parent := t.TempDir()
	sourcePath := filepath.Join(parent, "source.pdf")
	if err := os.WriteFile(sourcePath, []byte("source"), 0o600); err != nil {
		t.Fatal(err)
	}
	validHash := sha256.Sum256([]byte("source"))
	base := MinerUArtifactCaptureRequest{
		SourcePath: sourcePath, SourceSHA256: hex.EncodeToString(validHash[:]),
		ParserOverrides: map[string]string{"mineru_cloud_model": "pipeline"},
	}
	tests := map[string]struct {
		mutate func(*MinerUArtifactCaptureRequest)
		lookup func(string) (string, bool)
	}{
		"missing-credential": {lookup: func(string) (string, bool) { return "", false }},
		"source-sha-drift": {
			mutate: func(req *MinerUArtifactCaptureRequest) { req.SourceSHA256 = strings.Repeat("0", 64) },
			lookup: func(string) (string, bool) { return "secret", true },
		},
		"credential-in-overrides": {
			mutate: func(req *MinerUArtifactCaptureRequest) { req.ParserOverrides["mineru_api_key"] = "forbidden" },
			lookup: func(string) (string, bool) { return "secret", true },
		},
		"unsupported-parser": {
			mutate: func(req *MinerUArtifactCaptureRequest) { req.ParserOverrides["mineru_cloud_model"] = "vlm" },
			lookup: func(string) (string, bool) { return "secret", true },
		},
	}
	for name, tc := range tests {
		t.Run(name, func(t *testing.T) {
			req := base
			req.ParserOverrides = map[string]string{"mineru_cloud_model": "pipeline"}
			req.OutputDir = filepath.Join(parent, name)
			if tc.mutate != nil {
				tc.mutate(&req)
			}
			created := 0
			_, err := captureMinerUNativeStructure(
				context.Background(), req, tc.lookup,
				func(map[string]string) minerUCaptureReader { created++; return &fakeMinerUCaptureReader{} },
				fixedCaptureClock(time.Time{}, 0),
			)
			if err == nil || created != 0 {
				t.Fatalf("invalid input reached provider: created=%d err=%v", created, err)
			}
			if _, statErr := os.Stat(req.OutputDir); !errors.Is(statErr, os.ErrNotExist) {
				t.Fatalf("invalid capture created output: %v", statErr)
			}
		})
	}
}

func TestCaptureMinerUNativeStructureRejectsProviderAndArtifactFailuresWithoutOutput(t *testing.T) {
	t.Parallel()
	parent := t.TempDir()
	sourcePath := filepath.Join(parent, "source.pdf")
	source := []byte("source")
	if err := os.WriteFile(sourcePath, source, 0o600); err != nil {
		t.Fatal(err)
	}
	sourceHash := sha256.Sum256(source)
	sourceSHA := hex.EncodeToString(sourceHash[:])
	validJSON := []byte(`{"contract":"mineru-native-structure.v1","pages":[]}`)
	validSanitizedHash := sha256.Sum256(validJSON)
	validArtifact := func() *types.NativeStructureArtifact {
		return &types.NativeStructureArtifact{
			SchemaVersion: minerUStructureSchema, SourceSHA256: sourceSHA,
			RawSHA256: strings.Repeat("a", 64), SanitizedSHA256: hex.EncodeToString(validSanitizedHash[:]),
			SanitizedJSON: append([]byte(nil), validJSON...),
		}
	}
	tests := map[string]struct {
		result *types.ReadResult
		err    error
		calls  minerUCloudCallLedger
	}{
		"transport": {err: errors.New("Bearer secret and signed URL must not escape")},
		"missing-native-artifact": {
			result: &types.ReadResult{MarkdownContent: "body"},
			calls:  minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1},
		},
		"source-identity-drift": {
			result: func() *types.ReadResult {
				artifact := validArtifact()
				artifact.SourceSHA256 = strings.Repeat("b", 64)
				return &types.ReadResult{NativeStructure: artifact}
			}(),
			calls: minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"sanitized-body-leak": {
			result: func() *types.ReadResult {
				artifact := validArtifact()
				artifact.SanitizedJSON = []byte(`{"body":"source.pdf"}`)
				hash := sha256.Sum256(artifact.SanitizedJSON)
				artifact.SanitizedSHA256 = hex.EncodeToString(hash[:])
				return &types.ReadResult{NativeStructure: artifact}
			}(),
			calls: minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"call-budget-drift": {
			result: &types.ReadResult{NativeStructure: validArtifact()},
			calls:  minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 2, StatusGET: 1, ZIPGET: 1},
		},
	}
	for name, tc := range tests {
		t.Run(name, func(t *testing.T) {
			outputDir := filepath.Join(parent, name)
			reader := &fakeMinerUCaptureReader{result: tc.result, err: tc.err, calls: tc.calls}
			_, err := captureMinerUNativeStructure(
				context.Background(),
				MinerUArtifactCaptureRequest{
					SourcePath: sourcePath, SourceSHA256: sourceSHA, OutputDir: outputDir,
					ParserOverrides: map[string]string{"mineru_cloud_model": "pipeline"},
				},
				func(string) (string, bool) { return "in-memory-secret", true },
				func(map[string]string) minerUCaptureReader { return reader },
				fixedCaptureClock(time.Time{}, 0),
			)
			if !errors.Is(err, ErrMinerUArtifactCaptureFailed) || reader.reads != 1 {
				t.Fatalf("failure was not typed or exactly-once: reads=%d err=%v", reader.reads, err)
			}
			if strings.Contains(err.Error(), "secret") || strings.Contains(err.Error(), "signed") {
				t.Fatalf("provider detail escaped typed boundary: %v", err)
			}
			if _, statErr := os.Stat(outputDir); !errors.Is(statErr, os.ErrNotExist) {
				t.Fatalf("failed capture left output: %v", statErr)
			}
		})
	}
}

func fixedCaptureClock(start time.Time, elapsed time.Duration) func() time.Time {
	calls := 0
	return func() time.Time {
		calls++
		if calls%2 == 0 {
			return start.Add(elapsed)
		}
		return start
	}
}
