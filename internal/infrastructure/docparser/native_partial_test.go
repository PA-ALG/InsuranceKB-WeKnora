package docparser

import (
	"context"
	"encoding/json"
	"os"
	"testing"

	"github.com/Tencent/WeKnora/docreader/proto"
	"github.com/Tencent/WeKnora/internal/types"
)

func TestNativePartialActualCapture(t *testing.T) {
	path := os.Getenv("NATIVE_CAPTURE_FIXTURE")
	if path == "" {
		t.Skip("optional real PDF fixture")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Markdown string          `json:"markdown"`
		Envelope json.RawMessage `json:"envelope"`
	}
	if err = json.Unmarshal(raw, &fixture); err != nil {
		t.Fatal(err)
	}
	source, err := os.ReadFile(os.Getenv("NATIVE_CAPTURE_PDF"))
	if err != nil {
		t.Fatal(err)
	}
	result := &types.ReadResult{MarkdownContent: fixture.Markdown, Metadata: map[string]string{pdfNativeMetadataKey: string(fixture.Envelope)}}
	if err = attachPDFNativeStructure(&types.ReadRequest{FileContent: source}, result); err != nil {
		t.Fatal(err)
	}
	if result.NativeStructure == nil {
		t.Fatal("missing artifact")
	}
}

func TestNativePartialCapturePreservesSourceAndRejectsUndeclaredGaps(t *testing.T) {
	source := []byte("%PDF-unicode-source")
	for _, bad := range []string{"", "missing", "overlap", "unknown", "legacy"} {
		t.Run(bad, func(t *testing.T) {
			var env map[string]any
			if err := json.Unmarshal([]byte(nativeCaptureMetadata(t, source, "A😀\n\n中")), &env); err != nil {
				t.Fatal(err)
			}
			n := env["sanitized_json"].(map[string]any)
			n["contract"] = "builtin-pdfium-native-locators.v2"
			identity := n["parser_identity"].(map[string]any)
			identity["producer_contract"] = "weknora.docreader.builtin-pdfium-charbox.v2"
			page := n["pages"].([]any)[0].(map[string]any)
			page["bboxes"] = page["bboxes"].([]any)[:1]
			gap := map[string]any{"global_codepoint_start": 1, "global_codepoint_end": 2, "reason": "bbox_invalid"}
			page["unavailable_ranges"] = []any{gap}
			switch bad {
			case "missing":
				delete(page, "unavailable_ranges")
			case "overlap":
				gap["global_codepoint_start"] = 0
			case "unknown":
				gap["reason"] = "invented"
			case "legacy":
				n["contract"] = "builtin-pdfium-native-locators.v1"
				identity["producer_contract"] = "weknora.docreader.builtin-pdfium-charbox.v1"
			}
			n["parser_identity_sha256"] = nativeCaptureSHA(nativeCaptureCanonical(t, identity))
			raw := nativeCaptureCanonical(t, n)
			env["schema_version"] = n["contract"]
			env["sanitized_sha256"] = nativeCaptureSHA(raw)
			env["raw_sha256"] = nativeCaptureSHA(raw)
			req := &types.ReadRequest{FileContent: source, FileType: "pdf", ParserEngineOverrides: map[string]string{"pdf_native_structure_capture": "builtin-pdfium-charbox-v1"}}
			result, err := nativeCaptureRead(t, req, string(nativeCaptureCanonical(t, env)))
			if bad == "" {
				if err != nil {
					t.Fatal(err)
				}
				if result.MarkdownContent != "A😀\n\n中" || result.NativeStructure == nil {
					t.Fatal("source lost")
				}
			} else if err == nil {
				t.Fatal("accepted invalid gap")
			}
		})
	}
}

func TestNativeParserFailureRemainsTerminalResult(t *testing.T) {
	reader := &GRPCDocumentReader{client: &nativeCaptureUnaryClient{response: &proto.ReadResponse{Error: "unreadable PDF page"}}}
	result, err := reader.Read(context.Background(), &types.ReadRequest{FileContent: []byte("bad PDF"), FileType: "pdf", ParserEngineOverrides: map[string]string{"pdf_native_structure_capture": "builtin-pdfium-charbox-v1"}})
	if err != nil || result == nil || result.Error != "unreadable PDF page" {
		t.Fatalf("deterministic parser failure converted into transport retry: %v %v", result, err)
	}
}
