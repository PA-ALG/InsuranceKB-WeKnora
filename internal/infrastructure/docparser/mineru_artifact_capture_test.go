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
		result: &types.ReadResult{MarkdownContent: "same-read terms text", NativeStructure: &types.NativeStructureArtifact{
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
			AttemptNumber: 2, AttemptRole: "bounded_upgrade", Generation: intPointer(0),
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

func TestCaptureMinerUNativeStructureWritesSameReadSemanticCustody(t *testing.T) {
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
	contentSnapshot := "same-read semantic body"
	contentHash := sha256.Sum256([]byte(contentSnapshot))
	var readers []*fakeMinerUCaptureReader
	newReader := func(overrides map[string]string) minerUCaptureReader {
		if overrides["mineru_api_key"] != "never-serialize-this-secret" || overrides["mineru_cloud_model"] != "pipeline" {
			t.Fatalf("reader overrides drifted: %#v", overrides)
		}
		reader := &fakeMinerUCaptureReader{
			result: &types.ReadResult{
				MarkdownContent: contentSnapshot,
				NativeStructure: artifact,
			},
			calls: minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 3, ZIPGET: 1},
		}
		readers = append(readers, reader)
		return reader
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
				SourcePath:    sourcePaths[index],
				SourceSHA256:  sourceSHA,
				AttemptNumber: 2,
				AttemptRole:   "bounded_upgrade",
				Generation:    intPointer(0),
				OutputDir:     outputDir,
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
			"never-serialize-this-secret", sourcePaths[index],
			"https://", "signed_url", "source.pdf",
		} {
			if strings.Contains(string(payload), forbidden) {
				t.Fatalf("capture leaked %q: %s", forbidden, payload)
			}
		}
		var decoded struct {
			Contract     string `json:"contract"`
			SourceSHA256 string `json:"source_sha256"`
			Attempt      struct {
				AttemptNumber int    `json:"attempt_number"`
				AttemptRole   string `json:"attempt_role"`
				Generation    int    `json:"generation"`
			} `json:"attempt"`
			RawStructureSHA256       string          `json:"raw_structure_sha256"`
			SanitizedStructureSHA256 string          `json:"sanitized_structure_sha256"`
			SanitizedStructure       json.RawMessage `json:"sanitized_structure"`
			ContentSnapshotSHA256    string          `json:"content_snapshot_sha256"`
			ContentSnapshot          string          `json:"content_snapshot"`
			CaptureIdentitySHA256    string          `json:"capture_identity_sha256"`
			Parser                   map[string]any  `json:"parser"`
			Calls                    map[string]int  `json:"calls"`
			LatencyMilliseconds      int64           `json:"latency_milliseconds"`
			Status                   string          `json:"status"`
		}
		if err := json.Unmarshal(payload, &decoded); err != nil {
			t.Fatal(err)
		}
		if decoded.Contract != minerUCaptureContract || decoded.SourceSHA256 != sourceSHA ||
			decoded.Attempt.AttemptNumber != 2 || decoded.Attempt.AttemptRole != "bounded_upgrade" ||
			decoded.Attempt.Generation != 0 ||
			decoded.RawStructureSHA256 != artifact.RawSHA256 ||
			decoded.SanitizedStructureSHA256 != artifact.SanitizedSHA256 ||
			decoded.ContentSnapshotSHA256 != hex.EncodeToString(contentHash[:]) ||
			decoded.ContentSnapshot != contentSnapshot ||
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
		identityPreimage, err := json.Marshal(struct {
			Contract     string `json:"contract"`
			SourceSHA256 string `json:"source_sha256"`
			Attempt      struct {
				AttemptNumber int    `json:"attempt_number"`
				AttemptRole   string `json:"attempt_role"`
				Generation    int    `json:"generation"`
			} `json:"attempt"`
			ParserConfigSHA256       string `json:"parser_config_sha256"`
			RawStructureSHA256       string `json:"raw_structure_sha256"`
			SanitizedStructureSHA256 string `json:"sanitized_structure_sha256"`
			ContentSnapshotSHA256    string `json:"content_snapshot_sha256"`
		}{
			Contract: minerUCaptureContract, SourceSHA256: sourceSHA, Attempt: decoded.Attempt,
			ParserConfigSHA256:       decoded.Parser["config_sha256"].(string),
			RawStructureSHA256:       artifact.RawSHA256,
			SanitizedStructureSHA256: artifact.SanitizedSHA256,
			ContentSnapshotSHA256:    hex.EncodeToString(contentHash[:]),
		})
		if err != nil {
			t.Fatal(err)
		}
		identityHash := sha256.Sum256(identityPreimage)
		if decoded.CaptureIdentitySHA256 != hex.EncodeToString(identityHash[:]) {
			t.Fatalf("capture identity hash does not bind the attempt generation: %s", decoded.CaptureIdentitySHA256)
		}
		var object map[string]json.RawMessage
		if err := json.Unmarshal(payload, &object); err != nil {
			t.Fatal(err)
		}
		if _, exists := object["source_path_identity_sha256"]; exists {
			t.Fatal("evidence retained a machine-local path-derived identity")
		}
		if string(decoded.SanitizedStructure) != string(sanitized) {
			t.Fatalf("sanitized artifact drifted: %s", decoded.SanitizedStructure)
		}
		if readers[index].reads != 1 {
			t.Fatalf("capture used %d reads, want exactly one", readers[index].reads)
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
		AttemptNumber: 2, AttemptRole: "bounded_upgrade", Generation: intPointer(0),
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
		"attempt-number-drift": {
			mutate: func(req *MinerUArtifactCaptureRequest) { req.AttemptNumber = 1 },
			lookup: func(string) (string, bool) { return "secret", true },
		},
		"attempt-role-drift": {
			mutate: func(req *MinerUArtifactCaptureRequest) { req.AttemptRole = "default" },
			lookup: func(string) (string, bool) { return "secret", true },
		},
		"generation-drift": {
			mutate: func(req *MinerUArtifactCaptureRequest) { req.Generation = intPointer(1) },
			lookup: func(string) (string, bool) { return "secret", true },
		},
		"generation-missing": {
			mutate: func(req *MinerUArtifactCaptureRequest) { req.Generation = nil },
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
				return &types.ReadResult{MarkdownContent: "body", NativeStructure: artifact}
			}(),
			calls: minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"sanitized-body-leak": {
			result: func() *types.ReadResult {
				artifact := validArtifact()
				artifact.SanitizedJSON = []byte(`{"body":"source.pdf"}`)
				hash := sha256.Sum256(artifact.SanitizedJSON)
				artifact.SanitizedSHA256 = hex.EncodeToString(hash[:])
				return &types.ReadResult{MarkdownContent: "body", NativeStructure: artifact}
			}(),
			calls: minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"sanitized-cross-platform-path-leak": {
			result: func() *types.ReadResult {
				artifact := validArtifact()
				artifact.SanitizedJSON = []byte(`{"path":"/home/alice/private.pdf"}`)
				hash := sha256.Sum256(artifact.SanitizedJSON)
				artifact.SanitizedSHA256 = hex.EncodeToString(hash[:])
				return &types.ReadResult{MarkdownContent: "body", NativeStructure: artifact}
			}(),
			calls: minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"sanitized-unc-path-leak": {
			result: func() *types.ReadResult {
				artifact := validArtifact()
				artifact.SanitizedJSON, _ = json.Marshal(map[string]string{
					"path": `\\server\share\private.pdf`,
				})
				hash := sha256.Sum256(artifact.SanitizedJSON)
				artifact.SanitizedSHA256 = hex.EncodeToString(hash[:])
				return &types.ReadResult{MarkdownContent: "body", NativeStructure: artifact}
			}(),
			calls: minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"sanitized-hash-drift": {
			result: func() *types.ReadResult {
				artifact := validArtifact()
				artifact.SanitizedSHA256 = strings.Repeat("b", 64)
				return &types.ReadResult{MarkdownContent: "body", NativeStructure: artifact}
			}(),
			calls: minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"empty-content-snapshot": {
			result: &types.ReadResult{NativeStructure: validArtifact()},
			calls:  minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"content-secret-leak": {
			result: &types.ReadResult{
				MarkdownContent: "body Bearer in-memory-secret", NativeStructure: validArtifact(),
			},
			calls: minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"content-source-path-leak": {
			result: &types.ReadResult{MarkdownContent: "body " + sourcePath, NativeStructure: validArtifact()},
			calls:  minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"content-foreign-path-leak": {
			result: &types.ReadResult{
				MarkdownContent: "body /Users/alice/private.pdf", NativeStructure: validArtifact(),
			},
			calls: minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"content-home-path-leak": {
			result: &types.ReadResult{MarkdownContent: "body /home/alice/private.pdf", NativeStructure: validArtifact()},
			calls:  minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"content-var-path-leak": {
			result: &types.ReadResult{MarkdownContent: "body /var/lib/private.pdf", NativeStructure: validArtifact()},
			calls:  minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"content-volumes-path-leak": {
			result: &types.ReadResult{MarkdownContent: "body /Volumes/private/source.pdf", NativeStructure: validArtifact()},
			calls:  minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"content-windows-drive-path-leak": {
			result: &types.ReadResult{MarkdownContent: `body C:\\Users\\alice\\private.pdf`, NativeStructure: validArtifact()},
			calls:  minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"content-windows-slash-path-leak": {
			result: &types.ReadResult{MarkdownContent: "body D:/data/private.pdf", NativeStructure: validArtifact()},
			calls:  minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"content-unc-path-leak": {
			result: &types.ReadResult{MarkdownContent: `body \\server\share\private.pdf`, NativeStructure: validArtifact()},
			calls:  minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"content-forward-unc-path-leak": {
			result: &types.ReadResult{MarkdownContent: "body //server/share/private.pdf", NativeStructure: validArtifact()},
			calls:  minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"content-punctuated-posix-path-leak": {
			result: &types.ReadResult{MarkdownContent: "body,path:/etc/private.conf", NativeStructure: validArtifact()},
			calls:  minerUCloudCallLedger{AllocationPOST: 1, UploadPUT: 1, StatusGET: 1, ZIPGET: 1},
		},
		"call-budget-drift": {
			result: &types.ReadResult{MarkdownContent: "body", NativeStructure: validArtifact()},
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
					AttemptNumber: 2, AttemptRole: "bounded_upgrade", Generation: intPointer(0),
					ParserOverrides: map[string]string{"mineru_cloud_model": "pipeline"},
				},
				func(string) (string, bool) { return "in-memory-secret", true },
				func(map[string]string) minerUCaptureReader { return reader },
				fixedCaptureClock(time.Time{}, 0),
			)
			if !errors.Is(err, ErrMinerUArtifactCaptureFailed) || reader.reads != 1 {
				t.Fatalf("failure was not typed or exactly-once: reads=%d err=%v", reader.reads, err)
			}
			for _, forbidden := range []string{"secret", "signed", sourcePath, "/Users/alice", "Bearer"} {
				if strings.Contains(err.Error(), forbidden) {
					t.Fatalf("provider detail escaped typed boundary: %v", err)
				}
			}
			if _, statErr := os.Stat(outputDir); !errors.Is(statErr, os.ErrNotExist) {
				t.Fatalf("failed capture left output: %v", statErr)
			}
		})
	}
}

func TestCaptureMinerUNativeStructurePreservesSafeTypedReasonAndCustodyClasses(t *testing.T) {
	parent := t.TempDir()
	sourcePath := filepath.Join(parent, "source.pdf")
	source := []byte("source")
	if err := os.WriteFile(sourcePath, source, 0o600); err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(source)
	sourceSHA := hex.EncodeToString(digest[:])
	request := MinerUArtifactCaptureRequest{
		SourcePath: sourcePath, SourceSHA256: sourceSHA,
		AttemptNumber: 2, AttemptRole: "bounded_upgrade", Generation: intPointer(0),
		ParserOverrides: map[string]string{"mineru_cloud_model": "pipeline"},
	}
	sensitiveDetail := "provider secret https://signed.invalid/private.zip"
	tests := map[string]struct {
		err          error
		want         error
		wantDeadline bool
	}{
		"allocation":    {err: fmt.Errorf("%w: %s", ErrMinerUAllocationFailed, sensitiveDetail), want: ErrMinerUAllocationFailed},
		"upload":        {err: fmt.Errorf("%w: %s", ErrMinerUUploadFailed, sensitiveDetail), want: ErrMinerUUploadFailed},
		"status":        {err: fmt.Errorf("%w: %s", ErrMinerUStatusFailed, sensitiveDetail), want: ErrMinerUStatusFailed},
		"provider-task": {err: fmt.Errorf("%w: %s", ErrMinerUProviderTaskFailed, sensitiveDetail), want: ErrMinerUProviderTaskFailed},
		"poll-budget":   {err: fmt.Errorf("%w: %s", ErrMinerUCloudPollBudgetExceeded, sensitiveDetail), want: ErrMinerUCloudPollBudgetExceeded},
		"download-url":  {err: fmt.Errorf("%w: %s", ErrMinerUDownloadURLInvalid, sensitiveDetail), want: ErrMinerUDownloadURLInvalid},
		"zip":           {err: fmt.Errorf("%w: %s", ErrMinerUZIPDownloadFailed, sensitiveDetail), want: ErrMinerUZIPDownloadFailed},
		"zip-deadline":  {err: fmt.Errorf("%w: %w", ErrMinerUZIPDownloadFailed, context.DeadlineExceeded), want: ErrMinerUZIPDownloadFailed, wantDeadline: true},
		"native":        {err: fmt.Errorf("%w: %s", ErrMinerUNativeStructureUnavailable, sensitiveDetail), want: ErrMinerUNativeStructureUnavailable},
		"cross-page":    {err: fmt.Errorf("%w: %s", ErrMinerUCrossPageProjectionInvalid, sensitiveDetail), want: ErrMinerUCrossPageProjectionInvalid},
		"unknown":       {err: errors.New(sensitiveDetail), want: ErrMinerUCaptureStageUndetermined},
	}
	for name, tc := range tests {
		t.Run(name, func(t *testing.T) {
			request.OutputDir = filepath.Join(parent, name)
			reader := &fakeMinerUCaptureReader{err: tc.err}
			_, err := captureMinerUNativeStructure(
				context.Background(), request,
				func(string) (string, bool) { return "in-memory-secret", true },
				func(map[string]string) minerUCaptureReader { return reader },
				fixedCaptureClock(time.Time{}, 0),
			)
			if err == nil || !errors.Is(err, tc.want) || !errors.Is(err, ErrMinerUArtifactCaptureFailed) {
				t.Fatalf("typed reason drifted: got=%v want=%v", err, tc.want)
			}
			if errors.Is(err, context.DeadlineExceeded) != tc.wantDeadline {
				t.Fatalf("deadline custody drifted: got=%v want=%v", err, tc.wantDeadline)
			}
			for _, forbidden := range []string{"provider secret", "signed.invalid", "private.zip"} {
				if strings.Contains(err.Error(), forbidden) {
					t.Fatalf("sensitive reader detail escaped: %v", err)
				}
			}
			if _, statErr := os.Stat(request.OutputDir); !errors.Is(statErr, os.ErrNotExist) {
				t.Fatalf("failed capture left output: %v", statErr)
			}
		})
	}
}

func TestMinerUCaptureCustodyFailuresUseDistinctTypedReasons(t *testing.T) {
	artifact := &types.NativeStructureArtifact{
		SchemaVersion:   minerUStructureSchema,
		SourceSHA256:    strings.Repeat("a", 64),
		RawSHA256:       strings.Repeat("b", 64),
		SanitizedJSON:   []byte(`{"contract":"mineru-native-structure.v1"}`),
		SanitizedSHA256: strings.Repeat("c", 64),
	}
	if err := validateMinerUCaptureArtifact(artifact, strings.Repeat("a", 64), "/private/source.pdf", "secret"); !errors.Is(err, ErrMinerUArtifactCustodyInvalid) || errors.Is(err, ErrMinerUContentCustodyInvalid) {
		t.Fatalf("artifact custody reason drifted: %v", err)
	}
	if err := validateMinerUCaptureContent("", "/private/source.pdf", "secret"); !errors.Is(err, ErrMinerUContentCustodyInvalid) || errors.Is(err, ErrMinerUArtifactCustodyInvalid) {
		t.Fatalf("content custody reason drifted: %v", err)
	}
}

func TestValidateMinerUCaptureContentAllowsNonPathSlashesAndURLs(t *testing.T) {
	t.Parallel()
	for _, content := range []string{
		"benefit A / benefit B",
		"ratio 1/2 and clause 3/4",
		"reference https://example.com/public/spec",
		"reference http://example.com/public/spec",
	} {
		if err := validateMinerUCaptureContent(content, "/private/source.pdf", "in-memory-secret"); err != nil {
			t.Fatalf("non-path content %q was rejected: %v", content, err)
		}
	}
	for _, value := range []string{
		"benefit A / benefit B",
		"https://example.com/public/spec",
		"http://example.com/public/spec",
	} {
		payload, err := json.Marshal(map[string]any{"nested": []any{map[string]string{"value": value}}})
		if err != nil {
			t.Fatal(err)
		}
		if containsAbsolutePathInSanitizedJSON(payload) {
			t.Fatalf("sanitized JSON absolute-path detector misclassified %q", value)
		}
	}
}

func intPointer(value int) *int { return &value }

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
