package client_test

// Project test (not upstream): the platform's first parse of a managed RAW PDF requests native
// character capture and reads it through the streaming RPC. These tests run the platform's own
// DocReader reader against a live DocReader (the CI DocReader job starts one on localhost:50051)
// and fail if the capture is missing on that path, which is how every first-parse PDF failed
// after the streaming read became the default.

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"strings"
	"testing"
	"time"

	docclient "github.com/Tencent/WeKnora/docreader/client"
	"github.com/Tencent/WeKnora/docreader/proto"
	"github.com/Tencent/WeKnora/internal/infrastructure/docparser"
	"github.com/Tencent/WeKnora/internal/types"
)

const (
	liveDocReaderAddr    = "localhost:50051"
	nativeCaptureKey     = "pdf_native_structure_capture"
	nativeCaptureMode    = "builtin-pdfium-charbox-v1"
	nativeArtifactKey    = "native_structure_artifact_v1"
	nativeCaptureSubject = "Native capture over the stream"
)

func requireLiveDocReader(t *testing.T) *docclient.Client {
	t.Helper()
	client, err := docclient.NewClient(liveDocReaderAddr)
	if err != nil {
		t.Fatalf("create client: %v", err)
	}
	t.Cleanup(func() { _ = client.Close() })
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if _, err := client.ListEngines(ctx, &proto.ListEnginesRequest{}); err != nil {
		t.Skipf("DocReader gRPC server not available at %s: %v", liveDocReaderAddr, err)
	}
	return client
}

// textPDF builds a one-page PDF whose text layer holds text (standard Helvetica, no embedded
// font), with a correct cross-reference table.
func textPDF(text string) []byte {
	content := fmt.Sprintf("BT /F1 18 Tf 72 720 Td (%s) Tj ET", text)
	objects := []string{
		"<< /Type /Catalog /Pages 2 0 R >>",
		"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
		"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] " +
			"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
		fmt.Sprintf("<< /Length %d >>\nstream\n%s\nendstream", len(content), content),
		"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
	}
	var out bytes.Buffer
	out.WriteString("%PDF-1.4\n")
	offsets := make([]int, len(objects))
	for i, object := range objects {
		offsets[i] = out.Len()
		fmt.Fprintf(&out, "%d 0 obj\n%s\nendobj\n", i+1, object)
	}
	xref := out.Len()
	fmt.Fprintf(&out, "xref\n0 %d\n0000000000 65535 f \n", len(objects)+1)
	for _, offset := range offsets {
		fmt.Fprintf(&out, "%010d 00000 n \n", offset)
	}
	fmt.Fprintf(&out, "trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n", len(objects)+1, xref)
	return out.Bytes()
}

func captureRequest(capture bool) *types.ReadRequest {
	req := &types.ReadRequest{
		FileContent:  textPDF(nativeCaptureSubject),
		FileName:     "capture.pdf",
		FileType:     "pdf",
		ParserEngine: "builtin",
	}
	if capture {
		req.ParserEngineOverrides = map[string]string{nativeCaptureKey: nativeCaptureMode}
	}
	return req
}

func liveReader(t *testing.T) *docparser.GRPCDocumentReader {
	t.Helper()
	requireLiveDocReader(t)
	reader, err := docparser.NewGRPCDocumentReader(liveDocReaderAddr)
	if err != nil {
		t.Fatalf("connect reader: %v", err)
	}
	t.Cleanup(func() { _ = reader.Close() })
	return reader
}

func TestPlatformReaderGetsNativeCaptureOverReadStream(t *testing.T) {
	reader := liveReader(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	result, err := reader.Read(ctx, captureRequest(true))
	if err != nil {
		t.Fatalf("read with native capture: %v", err)
	}
	if result.Error != "" {
		t.Fatalf("parser error: %s", result.Error)
	}
	if result.NativeStructure == nil {
		t.Fatal("native structure artifact was not attached")
	}
	if !strings.Contains(result.MarkdownContent, nativeCaptureSubject) {
		t.Fatalf("markdown does not contain the page text: %q", result.MarkdownContent)
	}
}

func TestPlatformReaderWithoutCaptureHasNoArtifact(t *testing.T) {
	reader := liveReader(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	result, err := reader.Read(ctx, captureRequest(false))
	if err != nil {
		t.Fatalf("read without capture: %v", err)
	}
	if result.Error != "" || result.NativeStructure != nil {
		t.Fatalf("unexpected capture result: error=%q artifact=%v", result.Error, result.NativeStructure != nil)
	}
	if _, ok := result.Metadata[nativeArtifactKey]; ok {
		t.Fatal("native artifact metadata present without a capture request")
	}
}

func TestReadStreamMetaFrameCarriesTheNativeArtifact(t *testing.T) {
	client := requireLiveDocReader(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	req := captureRequest(true)
	stream, err := client.ReadStream(ctx, &proto.ReadRequest{
		FileContent: req.FileContent,
		FileName:    req.FileName,
		FileType:    req.FileType,
		Config: &proto.ReadConfig{
			ParserEngine:          req.ParserEngine,
			ParserEngineOverrides: req.ParserEngineOverrides,
		},
	})
	if err != nil {
		t.Fatalf("ReadStream: %v", err)
	}
	var meta *proto.ReadStreamMeta
	for {
		frame, recvErr := stream.Recv()
		if recvErr == io.EOF {
			break
		}
		if recvErr != nil {
			t.Fatalf("ReadStream recv: %v", recvErr)
		}
		if m := frame.GetMeta(); m != nil && meta == nil {
			meta = m
		}
	}
	if meta == nil {
		t.Fatal("no meta frame")
	}
	if meta.GetError() != "" {
		t.Fatalf("parser error: %s", meta.GetError())
	}
	if meta.GetMetadata()[nativeArtifactKey] == "" {
		t.Fatalf("meta frame lacks %s", nativeArtifactKey)
	}
	if meta.GetImageCount() != 0 {
		t.Fatalf("native capture streamed %d images", meta.GetImageCount())
	}
}
