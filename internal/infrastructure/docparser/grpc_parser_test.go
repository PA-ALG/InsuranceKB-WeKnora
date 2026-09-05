package docparser

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/docreader/proto"
	"github.com/Tencent/WeKnora/internal/types"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

type nativeCaptureUnaryClient struct {
	response *proto.ReadResponse
}

func (c *nativeCaptureUnaryClient) Read(
	context.Context, *proto.ReadRequest, ...grpc.CallOption,
) (*proto.ReadResponse, error) {
	return c.response, nil
}

func (c *nativeCaptureUnaryClient) ReadStream(
	context.Context, *proto.ReadRequest, ...grpc.CallOption,
) (grpc.ServerStreamingClient[proto.ReadStreamResponse], error) {
	return nil, status.Error(codes.Unimplemented, "test unary fallback")
}

func (c *nativeCaptureUnaryClient) ListEngines(
	context.Context, *proto.ListEnginesRequest, ...grpc.CallOption,
) (*proto.ListEnginesResponse, error) {
	return &proto.ListEnginesResponse{}, nil
}

func nativeCaptureSHA(value []byte) string {
	sum := sha256.Sum256(value)
	return hex.EncodeToString(sum[:])
}

func nativeCaptureCanonical(t *testing.T, value any) []byte {
	t.Helper()
	encoded, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	return encoded
}

func nativeCaptureMetadata(t *testing.T, source []byte, markdown string) string {
	t.Helper()
	identity := map[string]any{
		"capture_mode":      "builtin-pdfium-charbox-v1",
		"pdfium_version":    "7543",
		"producer_contract": "weknora.docreader.builtin-pdfium-charbox.v1",
		"pypdfium2_version": "5.8.0",
	}
	identityHash := nativeCaptureSHA(nativeCaptureCanonical(t, identity))
	sanitized := map[string]any{
		"contract":         "builtin-pdfium-native-locators.v1",
		"coordinate_space": "normalized_0_1e6_top_left",
		"markdown_sha256":  nativeCaptureSHA([]byte(markdown)),
		"pages": []any{
			map[string]any{
				"bboxes": []any{
					map[string]any{"bbox": []int{100000, 800000, 200000, 900000}, "global_codepoint_end": 1, "global_codepoint_start": 0},
					map[string]any{"bbox": []int{200000, 800000, 400000, 900000}, "global_codepoint_end": 2, "global_codepoint_start": 1},
				},
				"global_codepoint_end":   2,
				"global_codepoint_start": 0,
				"height_points":          "200",
				"page_number":            1,
				"page_text_sha256":       nativeCaptureSHA([]byte("A😀")),
				"width_points":           "100",
			},
			map[string]any{
				"bboxes": []any{
					map[string]any{"bbox": []int{250000, 500000, 500000, 750000}, "global_codepoint_end": 5, "global_codepoint_start": 4},
				},
				"global_codepoint_end":   5,
				"global_codepoint_start": 4,
				"height_points":          "200",
				"page_number":            2,
				"page_text_sha256":       nativeCaptureSHA([]byte("中")),
				"width_points":           "100",
			},
		},
		"parser_identity":        identity,
		"parser_identity_sha256": identityHash,
		"source_sha256":          nativeCaptureSHA(source),
	}
	sanitizedBytes := nativeCaptureCanonical(t, sanitized)
	structureHash := nativeCaptureSHA(sanitizedBytes)
	envelope := map[string]any{
		"raw_sha256":       structureHash,
		"sanitized_json":   json.RawMessage(sanitizedBytes),
		"sanitized_sha256": structureHash,
		"schema_version":   "builtin-pdfium-native-locators.v1",
		"source_sha256":    nativeCaptureSHA(source),
	}
	return string(nativeCaptureCanonical(t, envelope))
}

func nativeCaptureRead(t *testing.T, req *types.ReadRequest, metadata string) (*types.ReadResult, error) {
	t.Helper()
	reader := &GRPCDocumentReader{client: &nativeCaptureUnaryClient{response: &proto.ReadResponse{
		MarkdownContent: "A😀\n\n中",
		Metadata: map[string]string{
			"native_structure_artifact_v1": metadata,
		},
	}}}
	return reader.Read(context.Background(), req)
}

func TestGRPCDocumentReaderNativeCaptureBuildsVerifiedArtifact(t *testing.T) {
	source := []byte("%PDF-unicode-source")
	metadata := nativeCaptureMetadata(t, source, "A😀\n\n中")
	result, err := nativeCaptureRead(t, &types.ReadRequest{
		FileContent: source,
		FileName:    "source.pdf",
		FileType:    "pdf",
		ParserEngineOverrides: map[string]string{
			"pdf_native_structure_capture": "builtin-pdfium-charbox-v1",
		},
	}, metadata)
	if err != nil {
		t.Fatal(err)
	}
	if result.NativeStructure == nil {
		t.Fatal("native structure was not attached")
	}
	if result.NativeStructure.SourceSHA256 != nativeCaptureSHA(source) ||
		result.NativeStructure.RawSHA256 != result.NativeStructure.SanitizedSHA256 ||
		!json.Valid(result.NativeStructure.SanitizedJSON) {
		t.Fatalf("invalid native structure: %#v", result.NativeStructure)
	}
}

func TestGRPCDocumentReaderNativeCaptureRejectsUnsupportedRequests(t *testing.T) {
	source := []byte("%PDF-source")
	cases := []struct {
		name string
		req  *types.ReadRequest
	}{
		{name: "empty mode", req: &types.ReadRequest{FileContent: source, FileType: "pdf", ParserEngineOverrides: map[string]string{"pdf_native_structure_capture": ""}}},
		{name: "unknown mode", req: &types.ReadRequest{FileContent: source, FileType: "pdf", ParserEngineOverrides: map[string]string{"pdf_native_structure_capture": "other"}}},
		{name: "URL", req: &types.ReadRequest{URL: "https://example.invalid/source.pdf", FileType: "pdf", ParserEngineOverrides: map[string]string{"pdf_native_structure_capture": "builtin-pdfium-charbox-v1"}}},
		{name: "non PDF", req: &types.ReadRequest{FileContent: source, FileType: "docx", ParserEngineOverrides: map[string]string{"pdf_native_structure_capture": "builtin-pdfium-charbox-v1"}}},
		{name: "external parser", req: &types.ReadRequest{FileContent: source, FileType: "pdf", ParserEngine: "mineru", ParserEngineOverrides: map[string]string{"pdf_native_structure_capture": "builtin-pdfium-charbox-v1"}}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := nativeCaptureRead(t, tc.req, nativeCaptureMetadata(t, source, "A😀\n\n中"))
			if err == nil || !strings.Contains(err.Error(), "PDF native structure capture") {
				t.Fatalf("expected capture request rejection, got %v", err)
			}
		})
	}
}

func TestGRPCDocumentReaderNativeCaptureRejectsTransportTamper(t *testing.T) {
	source := []byte("%PDF-unicode-source")
	valid := nativeCaptureMetadata(t, source, "A😀\n\n中")
	cases := map[string]func(map[string]any){
		"source":         func(envelope map[string]any) { envelope["source_sha256"] = strings.Repeat("0", 64) },
		"sanitized hash": func(envelope map[string]any) { envelope["sanitized_sha256"] = strings.Repeat("0", 64) },
		"raw hash":       func(envelope map[string]any) { envelope["raw_sha256"] = strings.Repeat("0", 64) },
		"parser identity": func(envelope map[string]any) {
			sanitized := envelope["sanitized_json"].(map[string]any)
			sanitized["parser_identity_sha256"] = strings.Repeat("0", 64)
			reencoded := nativeCaptureCanonical(t, sanitized)
			envelope["sanitized_sha256"] = nativeCaptureSHA(reencoded)
			envelope["raw_sha256"] = nativeCaptureSHA(reencoded)
		},
		"bbox": func(envelope map[string]any) {
			sanitized := envelope["sanitized_json"].(map[string]any)
			pages := sanitized["pages"].([]any)
			boxes := pages[0].(map[string]any)["bboxes"].([]any)
			boxes[0].(map[string]any)["bbox"] = []any{1000000, 0, 1000000, 1}
			reencoded := nativeCaptureCanonical(t, sanitized)
			envelope["sanitized_sha256"] = nativeCaptureSHA(reencoded)
			envelope["raw_sha256"] = nativeCaptureSHA(reencoded)
		},
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			var envelope map[string]any
			if err := json.Unmarshal([]byte(valid), &envelope); err != nil {
				t.Fatal(err)
			}
			mutate(envelope)
			metadata := string(nativeCaptureCanonical(t, envelope))
			_, err := nativeCaptureRead(t, &types.ReadRequest{
				FileContent: source,
				FileType:    "pdf",
				ParserEngineOverrides: map[string]string{
					"pdf_native_structure_capture": "builtin-pdfium-charbox-v1",
				},
			}, metadata)
			if err == nil {
				t.Fatal("transport tamper was accepted")
			}
		})
	}
}

func TestGRPCDocumentReaderDefaultReadIgnoresNativeMetadata(t *testing.T) {
	result, err := nativeCaptureRead(t, &types.ReadRequest{
		FileContent: []byte("%PDF-source"), FileType: "pdf",
	}, "not-json")
	if err != nil {
		t.Fatal(err)
	}
	if result.NativeStructure != nil {
		t.Fatal("default read attached opt-in native structure")
	}
}
