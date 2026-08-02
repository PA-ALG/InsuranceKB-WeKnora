package docparser

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
)

type fakeMinerUCaptureReader struct {
	result *types.ReadResult
	err    error
	calls  minerUCloudCallLedger
	reads  int
}

func (f *fakeMinerUCaptureReader) Read(_ context.Context, req *types.ReadRequest) (*types.ReadResult, error) {
	f.reads++
	if req.FileName != "source.pdf" || req.ParserEngine != "mineru_cloud" {
		return nil, errors.New("capture request identity drift")
	}
	return f.result, f.err
}

func (f *fakeMinerUCaptureReader) captureCallLedger() minerUCloudCallLedger { return f.calls }

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
