package docparser

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	docclient "github.com/Tencent/WeKnora/docreader/client"
	"github.com/Tencent/WeKnora/docreader/proto"
	"github.com/Tencent/WeKnora/internal/logger"
	"github.com/Tencent/WeKnora/internal/types"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/resolver"
	"google.golang.org/grpc/status"
)

const (
	pdfNativeCaptureOverrideKey = "pdf_native_structure_capture"
	pdfNativeCaptureMode        = "builtin-pdfium-charbox-v1"
	pdfNativeMetadataKey        = "native_structure_artifact_v1"
	pdfNativeSchema             = "builtin-pdfium-native-locators.v1"
	pdfNativeCoordinateSpace    = "normalized_0_1e6_top_left"
	pdfNativeProducerContract   = "weknora.docreader.builtin-pdfium-charbox.v1"
)

type pdfNativeEnvelope struct {
	RawSHA256       string          `json:"raw_sha256"`
	SanitizedJSON   json.RawMessage `json:"sanitized_json"`
	SanitizedSHA256 string          `json:"sanitized_sha256"`
	SchemaVersion   string          `json:"schema_version"`
	SourceSHA256    string          `json:"source_sha256"`
}

type pdfNativeParserIdentity struct {
	CaptureMode      string `json:"capture_mode"`
	PDFiumVersion    string `json:"pdfium_version"`
	ProducerContract string `json:"producer_contract"`
	PyPDFium2Version string `json:"pypdfium2_version"`
}

type pdfNativeBBox struct {
	BBox                 []int `json:"bbox"`
	GlobalCodepointEnd   int   `json:"global_codepoint_end"`
	GlobalCodepointStart int   `json:"global_codepoint_start"`
}

type pdfNativePage struct {
	BBoxes               []pdfNativeBBox                `json:"bboxes"`
	GlobalCodepointEnd   int                            `json:"global_codepoint_end"`
	GlobalCodepointStart int                            `json:"global_codepoint_start"`
	HeightPoints         string                         `json:"height_points"`
	PageNumber           int                            `json:"page_number"`
	PageTextSHA256       string                         `json:"page_text_sha256"`
	UnavailableRanges    []types.NativeUnavailableRange `json:"unavailable_ranges,omitempty"`
	WidthPoints          string                         `json:"width_points"`
}

type pdfNativeSanitized struct {
	Contract             string                  `json:"contract"`
	CoordinateSpace      string                  `json:"coordinate_space"`
	MarkdownSHA256       string                  `json:"markdown_sha256"`
	Pages                []pdfNativePage         `json:"pages"`
	ParserIdentity       pdfNativeParserIdentity `json:"parser_identity"`
	ParserIdentitySHA256 string                  `json:"parser_identity_sha256"`
	SourceSHA256         string                  `json:"source_sha256"`
}

func getMaxMessageSize() int {
	if sizeStr := os.Getenv("MAX_FILE_SIZE_MB"); sizeStr != "" {
		if size, err := strconv.Atoi(sizeStr); err == nil && size > 0 {
			return size * 1024 * 1024
		}
	}
	return 50 * 1024 * 1024
}

// GRPCDocumentReader implements DocumentReader over gRPC.
type GRPCDocumentReader struct {
	mu     sync.RWMutex
	conn   *grpc.ClientConn
	client proto.DocReaderClient
	addr   string
}

func NewGRPCDocumentReader(addr string) (*GRPCDocumentReader, error) {
	p := &GRPCDocumentReader{}
	if addr != "" {
		if err := p.connect(addr); err != nil {
			return nil, err
		}
	}
	return p, nil
}

func (p *GRPCDocumentReader) connect(addr string) error {
	authConfig := docclient.LoadAuthConfigFromEnv()
	opts, err := authConfig.BuildDialOptions(getMaxMessageSize())
	if err != nil {
		return fmt.Errorf("failed to build docreader dial options: %w", err)
	}
	if authConfig.TLSEnabled {
		logger.Infof(context.Background(), "TLS enabled for docreader gRPC client")
	}
	if authConfig.AuthToken != "" {
		logger.Infof(context.Background(),
			"Token authentication enabled for docreader gRPC client (TLS=%v)",
			authConfig.TLSEnabled,
		)
	}

	resolver.SetDefaultScheme("dns")

	start := time.Now()
	conn, err := grpc.Dial("dns:///"+addr, opts...)
	if err != nil {
		return fmt.Errorf("failed to connect to docreader: %w", err)
	}
	logger.Infof(context.Background(), "Connected to docreader in %v", time.Since(start))

	p.conn = conn
	p.client = proto.NewDocReaderClient(conn)
	p.addr = addr
	return nil
}

func (p *GRPCDocumentReader) Reconnect(addr string) error {
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.conn != nil {
		_ = p.conn.Close()
		p.conn = nil
		p.client = nil
		p.addr = ""
	}
	return p.connect(addr)
}

func (p *GRPCDocumentReader) IsConnected() bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.conn != nil
}

func (p *GRPCDocumentReader) Close() error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.conn != nil {
		return p.conn.Close()
	}
	return nil
}

var errNotConnected = fmt.Errorf("docreader service not connected")

func (p *GRPCDocumentReader) Read(ctx context.Context, req *types.ReadRequest) (*types.ReadResult, error) {
	captureNative, err := validatePDFNativeCaptureRequest(req)
	if err != nil {
		return nil, err
	}
	p.mu.RLock()
	client := p.client
	p.mu.RUnlock()
	if client == nil {
		return nil, errNotConnected
	}

	protoReq := &proto.ReadRequest{
		FileContent: req.FileContent,
		FileName:    req.FileName,
		FileType:    req.FileType,
		Url:         req.URL,
		Title:       req.Title,
		RequestId:   req.RequestID,
		Config: &proto.ReadConfig{
			ParserEngine:          req.ParserEngine,
			ParserEngineOverrides: req.ParserEngineOverrides,
		},
	}

	// Use the streaming RPC so documents with many page images (large scanned
	// PDFs) are not capped by the unary message-size limit. The meta frame
	// arrives first, followed by one frame per image.
	result, err := p.readStream(ctx, client, protoReq)
	if err != nil {
		// An older docreader build may not implement ReadStream. Fall back to
		// the unary Read RPC so a version-skewed deployment still parses
		// documents (small/medium docs only — the unary path remains capped by
		// the gRPC message-size limit, which is exactly what streaming avoids).
		if status.Code(err) == codes.Unimplemented {
			logger.Warnf(ctx, "docreader ReadStream unimplemented, falling back to unary Read: %v", err)
			result, err = p.readUnary(ctx, client, protoReq)
			if err != nil {
				return nil, err
			}
		} else {
			return nil, err
		}
	}
	// A completed parser error is terminal input failure, not a transport error.
	// Preserve the existing caller's terminal-result path and its original reason.
	if captureNative && result.Error == "" {
		if err := attachPDFNativeStructure(req, result); err != nil {
			return nil, err
		}
	}
	return result, nil
}

func validatePDFNativeCaptureRequest(req *types.ReadRequest) (bool, error) {
	if req == nil {
		return false, fmt.Errorf("PDF native structure capture request is nil")
	}
	mode, configured := req.ParserEngineOverrides[pdfNativeCaptureOverrideKey]
	if !configured {
		return false, nil
	}
	if mode != pdfNativeCaptureMode {
		return false, fmt.Errorf("PDF native structure capture mode is unsupported")
	}
	fileType := strings.TrimPrefix(strings.ToLower(strings.TrimSpace(req.FileType)), ".")
	parserEngine := strings.ToLower(strings.TrimSpace(req.ParserEngine))
	if len(req.FileContent) == 0 || strings.TrimSpace(req.URL) != "" || fileType != "pdf" ||
		(parserEngine != "" && parserEngine != "builtin") {
		return false, fmt.Errorf("PDF native structure capture requires builtin PDF file bytes")
	}
	return true, nil
}

func decodePDFNativeJSON(raw []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	if decoder.More() {
		return fmt.Errorf("trailing JSON value")
	}
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		return fmt.Errorf("trailing JSON value")
	}
	return nil
}

func pdfNativeSHA256(value []byte) string {
	sum := sha256.Sum256(value)
	return hex.EncodeToString(sum[:])
}

func validPDFNativePoint(value string) bool {
	parsed, err := strconv.ParseFloat(value, 64)
	return err == nil && parsed > 0 && !math.IsInf(parsed, 0) && !math.IsNaN(parsed) &&
		strconv.FormatFloat(parsed, 'f', -1, 64) == value
}

func attachPDFNativeStructure(req *types.ReadRequest, result *types.ReadResult) error { //nolint:gocyclo
	if result == nil || result.Error != "" {
		return fmt.Errorf("PDF native structure capture returned parser error")
	}
	rawEnvelope := []byte(result.Metadata[pdfNativeMetadataKey])
	if len(rawEnvelope) == 0 {
		return fmt.Errorf("PDF native structure capture metadata is missing")
	}
	var envelope pdfNativeEnvelope
	if err := decodePDFNativeJSON(rawEnvelope, &envelope); err != nil {
		return fmt.Errorf("PDF native structure capture metadata is invalid: %w", err)
	}
	canonicalEnvelope, err := json.Marshal(envelope)
	if err != nil || !bytes.Equal(canonicalEnvelope, rawEnvelope) {
		return fmt.Errorf("PDF native structure capture metadata is not canonical")
	}
	sourceSHA256 := pdfNativeSHA256(req.FileContent)
	if (envelope.SchemaVersion != pdfNativeSchema && envelope.SchemaVersion != types.NativePartialLocatorContract) || envelope.SourceSHA256 != sourceSHA256 ||
		envelope.RawSHA256 != envelope.SanitizedSHA256 ||
		envelope.SanitizedSHA256 != pdfNativeSHA256(envelope.SanitizedJSON) {
		return fmt.Errorf("PDF native structure capture envelope binding is invalid")
	}

	var sanitized pdfNativeSanitized
	if err := decodePDFNativeJSON(envelope.SanitizedJSON, &sanitized); err != nil {
		return fmt.Errorf("PDF native structure capture projection is invalid: %w", err)
	}
	canonicalSanitized, err := json.Marshal(sanitized)
	if err != nil || !bytes.Equal(canonicalSanitized, envelope.SanitizedJSON) {
		return fmt.Errorf("PDF native structure capture projection is not canonical")
	}
	identityBytes, err := json.Marshal(sanitized.ParserIdentity)
	if err != nil {
		return fmt.Errorf("PDF native structure capture parser identity is invalid")
	}
	identity := sanitized.ParserIdentity
	if sanitized.Contract != envelope.SchemaVersion || sanitized.SourceSHA256 != sourceSHA256 ||
		sanitized.CoordinateSpace != pdfNativeCoordinateSpace ||
		identity.CaptureMode != pdfNativeCaptureMode ||
		!types.ValidNativeLocatorIdentity(sanitized.Contract, identity.ProducerContract) ||
		strings.TrimSpace(identity.PDFiumVersion) == "" || strings.TrimSpace(identity.PyPDFium2Version) == "" ||
		sanitized.ParserIdentitySHA256 != pdfNativeSHA256(identityBytes) {
		return fmt.Errorf("PDF native structure capture parser identity binding is invalid")
	}
	if !utf8.ValidString(result.MarkdownContent) ||
		sanitized.MarkdownSHA256 != pdfNativeSHA256([]byte(result.MarkdownContent)) || len(sanitized.Pages) == 0 {
		return fmt.Errorf("PDF native structure capture Markdown binding is invalid")
	}

	runes := []rune(result.MarkdownContent)
	nextPageStart := 0
	for pageIndex, page := range sanitized.Pages {
		if page.PageNumber != pageIndex+1 || page.GlobalCodepointStart != nextPageStart ||
			page.GlobalCodepointEnd < page.GlobalCodepointStart || page.GlobalCodepointEnd > len(runes) ||
			!validPDFNativePoint(page.WidthPoints) || !validPDFNativePoint(page.HeightPoints) {
			return fmt.Errorf("PDF native structure capture page %d binding is invalid", pageIndex+1)
		}
		pageRunes := runes[page.GlobalCodepointStart:page.GlobalCodepointEnd]
		if page.PageTextSHA256 != pdfNativeSHA256([]byte(string(pageRunes))) {
			return fmt.Errorf("PDF native structure capture page %d text binding is invalid", pageIndex+1)
		}
		positions := make(map[int]bool, len(page.BBoxes))
		previous := page.GlobalCodepointStart - 1
		for _, bbox := range page.BBoxes {
			if bbox.GlobalCodepointStart <= previous || bbox.GlobalCodepointStart < page.GlobalCodepointStart || bbox.GlobalCodepointEnd > page.GlobalCodepointEnd || bbox.GlobalCodepointEnd != bbox.GlobalCodepointStart+1 ||
				len(bbox.BBox) != 4 || bbox.BBox[0] < 0 || bbox.BBox[1] < 0 ||
				bbox.BBox[2] > 1_000_000 || bbox.BBox[3] > 1_000_000 ||
				bbox.BBox[0] >= bbox.BBox[2] || bbox.BBox[1] >= bbox.BBox[3] {
				return fmt.Errorf("PDF native structure capture page %d bbox is invalid", pageIndex+1)
			}
			positions[bbox.GlobalCodepointStart] = true
			previous = bbox.GlobalCodepointStart
		}
		if !types.ValidateNativeLocatorCoverage(sanitized.Contract, pageRunes, page.GlobalCodepointStart, positions, page.UnavailableRanges) {
			return fmt.Errorf("PDF native structure capture page %d bbox coverage is invalid", pageIndex+1)
		}
		nextPageStart = page.GlobalCodepointEnd
		if pageIndex+1 < len(sanitized.Pages) {
			if nextPageStart+2 > len(runes) || string(runes[nextPageStart:nextPageStart+2]) != "\n\n" {
				return fmt.Errorf("PDF native structure capture page separator is invalid")
			}
			nextPageStart += 2
		}
	}
	if nextPageStart != len(runes) {
		return fmt.Errorf("PDF native structure capture page coverage is incomplete")
	}
	result.NativeStructure = &types.NativeStructureArtifact{
		SchemaVersion:   envelope.SchemaVersion,
		SourceSHA256:    envelope.SourceSHA256,
		RawSHA256:       envelope.RawSHA256,
		SanitizedSHA256: envelope.SanitizedSHA256,
		SanitizedJSON:   append([]byte(nil), envelope.SanitizedJSON...),
	}
	return nil
}

// readStream consumes the server-streaming ReadStream RPC: one meta frame
// followed by one frame per image. Errors are returned verbatim so the caller
// can inspect the gRPC status code (e.g. Unimplemented) for fallback.
func (p *GRPCDocumentReader) readStream(
	ctx context.Context, client proto.DocReaderClient, protoReq *proto.ReadRequest,
) (*types.ReadResult, error) {
	stream, err := client.ReadStream(ctx, protoReq)
	if err != nil {
		return nil, fmt.Errorf("gRPC ReadStream failed: %w", err)
	}

	result := &types.ReadResult{}
	gotMeta := false
	for {
		frame, recvErr := stream.Recv()
		if recvErr == io.EOF {
			break
		}
		if recvErr != nil {
			return nil, fmt.Errorf("gRPC ReadStream recv failed: %w", recvErr)
		}

		if meta := frame.GetMeta(); meta != nil {
			gotMeta = true
			result.MarkdownContent = meta.GetMarkdownContent()
			result.ImageDirPath = meta.GetImageDirPath()
			result.Metadata = meta.GetMetadata()
			result.Error = meta.GetError()
			if n := meta.GetImageCount(); n > 0 {
				result.ImageRefs = make([]types.ImageRef, 0, n)
			}
			continue
		}

		if img := frame.GetImage(); img != nil {
			result.ImageRefs = append(result.ImageRefs, types.ImageRef{
				Filename:    img.GetFilename(),
				OriginalRef: img.GetOriginalRef(),
				MimeType:    img.GetMimeType(),
				StorageKey:  img.GetStorageKey(),
				ImageData:   img.GetImageData(),
			})
		}
	}

	if !gotMeta {
		return nil, fmt.Errorf("gRPC ReadStream returned no metadata frame")
	}
	return result, nil
}

// readUnary calls the legacy unary Read RPC. Used only as a compatibility
// fallback when the connected docreader does not implement ReadStream.
func (p *GRPCDocumentReader) readUnary(
	ctx context.Context, client proto.DocReaderClient, protoReq *proto.ReadRequest,
) (*types.ReadResult, error) {
	resp, err := client.Read(ctx, protoReq)
	if err != nil {
		return nil, fmt.Errorf("gRPC Read failed: %w", err)
	}

	result := &types.ReadResult{
		MarkdownContent: resp.GetMarkdownContent(),
		ImageDirPath:    resp.GetImageDirPath(),
		Metadata:        resp.GetMetadata(),
		Error:           resp.GetError(),
	}
	if refs := resp.GetImageRefs(); len(refs) > 0 {
		result.ImageRefs = make([]types.ImageRef, 0, len(refs))
		for _, img := range refs {
			result.ImageRefs = append(result.ImageRefs, types.ImageRef{
				Filename:    img.GetFilename(),
				OriginalRef: img.GetOriginalRef(),
				MimeType:    img.GetMimeType(),
				StorageKey:  img.GetStorageKey(),
				ImageData:   img.GetImageData(),
			})
		}
	}
	return result, nil
}

func (p *GRPCDocumentReader) ListEngines(ctx context.Context, overrides map[string]string) ([]types.ParserEngineInfo, error) {
	p.mu.RLock()
	client := p.client
	p.mu.RUnlock()
	if client == nil {
		return nil, errNotConnected
	}

	resp, err := client.ListEngines(ctx, &proto.ListEnginesRequest{ConfigOverrides: overrides})
	if err != nil {
		return nil, fmt.Errorf("gRPC ListEngines failed: %w", err)
	}

	result := make([]types.ParserEngineInfo, 0, len(resp.GetEngines()))
	for _, e := range resp.GetEngines() {
		result = append(result, types.ParserEngineInfo{
			Name:              e.GetName(),
			Description:       e.GetDescription(),
			FileTypes:         e.GetFileTypes(),
			Available:         e.GetAvailable(),
			UnavailableReason: e.GetUnavailableReason(),
		})
	}
	return result, nil
}
