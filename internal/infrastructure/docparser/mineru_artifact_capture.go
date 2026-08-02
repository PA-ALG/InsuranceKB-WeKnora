package docparser

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
)

const (
	minerUCaptureContract             = "mineru-semantic-content-custody.v2"
	minerUCaptureFileName             = "mineru-native-structure.json"
	minerUAPIKeyEnvironmentVariable   = "MINERU_API_KEY"
	minerUCaptureParserImplementation = "NewMinerUCloudReader"
	minerUCaptureAttemptNumber        = 2
	minerUCaptureAttemptRole          = "bounded_upgrade"
	minerUCaptureGeneration           = 0
)

var (
	ErrMinerUArtifactCaptureInvalidInput = errors.New("MinerU artifact capture input invalid")
	ErrMinerUArtifactCaptureCredential   = errors.New("MinerU artifact capture credential unavailable")
	ErrMinerUArtifactCaptureFailed       = errors.New("MinerU artifact capture failed")
)

// MinerUArtifactCaptureRequest binds one caller-owned PDF identity to one
// task-local MinerU parser configuration. Credentials are deliberately absent.
type MinerUArtifactCaptureRequest struct {
	SourcePath      string
	SourceSHA256    string
	AttemptNumber   int
	AttemptRole     string
	Generation      *int
	OutputDir       string
	ParserOverrides map[string]string
}

type minerUCaptureAttemptIdentity struct {
	AttemptNumber int    `json:"attempt_number"`
	AttemptRole   string `json:"attempt_role"`
	Generation    int    `json:"generation"`
}

type minerUCloudCallLedger struct {
	AllocationPOST int `json:"allocation_post"`
	UploadPUT      int `json:"upload_put"`
	StatusGET      int `json:"status_get"`
	ZIPGET         int `json:"zip_get"`
}

type minerUCaptureReader interface {
	Read(context.Context, *types.ReadRequest) (*types.ReadResult, error)
	captureCallLedger() minerUCloudCallLedger
	captureCrossPageProjection() *minerUCrossPageProjection
}

type minerUCaptureParserLedger struct {
	Engine                string `json:"engine"`
	Implementation        string `json:"implementation"`
	NativeStructureSchema string `json:"native_structure_schema"`
	Model                 string `json:"model"`
	Formula               bool   `json:"formula"`
	Table                 bool   `json:"table"`
	OCR                   bool   `json:"ocr"`
	Language              string `json:"language"`
	ConfigSHA256          string `json:"config_sha256"`
}

type minerUCaptureEvidence struct {
	Contract                 string                       `json:"contract"`
	SourceSHA256             string                       `json:"source_sha256"`
	Attempt                  minerUCaptureAttemptIdentity `json:"attempt"`
	RawStructureSHA256       string                       `json:"raw_structure_sha256"`
	SanitizedStructureSHA256 string                       `json:"sanitized_structure_sha256"`
	SanitizedStructure       json.RawMessage              `json:"sanitized_structure"`
	ContentSnapshotSHA256    string                       `json:"content_snapshot_sha256"`
	ContentSnapshot          string                       `json:"content_snapshot"`
	CaptureIdentitySHA256    string                       `json:"capture_identity_sha256"`
	Parser                   minerUCaptureParserLedger    `json:"parser"`
	Calls                    minerUCloudCallLedger        `json:"calls"`
	LatencyMilliseconds      int64                        `json:"latency_milliseconds"`
	Status                   string                       `json:"status"`
	CrossPageFacts           *minerUCrossPageProjection   `json:"cross_page_facts,omitempty"`
}

type minerUCapturePublishHooks struct {
	writeTemp     func(*os.File, []byte) error
	beforePublish func(string) error
}

// CaptureMinerUNativeStructure performs one bounded provider attempt and emits
// one private structure-and-content custody file. It never reads credentials from arguments.
func CaptureMinerUNativeStructure(ctx context.Context, req MinerUArtifactCaptureRequest) (string, error) {
	return captureMinerUNativeStructure(ctx, req, os.LookupEnv, newMinerUArtifactCaptureReader, time.Now)
}

func newMinerUArtifactCaptureReader(overrides map[string]string) minerUCaptureReader {
	reader := NewMinerUCloudReader(overrides)
	reader.enableArtifactCapturePolicy()
	return reader
}

func captureMinerUNativeStructure(
	ctx context.Context,
	req MinerUArtifactCaptureRequest,
	lookupEnv func(string) (string, bool),
	newReader func(map[string]string) minerUCaptureReader,
	now func() time.Time,
) (string, error) {
	content, parser, overrides, err := validateMinerUCaptureInput(req)
	if err != nil {
		return "", err
	}
	apiKey, ok := lookupEnv(minerUAPIKeyEnvironmentVariable)
	if !ok || strings.TrimSpace(apiKey) == "" {
		return "", ErrMinerUArtifactCaptureCredential
	}
	if _, err := os.Stat(req.OutputDir); !errors.Is(err, os.ErrNotExist) {
		return "", fmt.Errorf("%w: output directory must not exist", ErrMinerUArtifactCaptureInvalidInput)
	}
	overrides["mineru_api_key"] = apiKey
	reader := newReader(overrides)
	started := now()
	result, readErr := reader.Read(ctx, &types.ReadRequest{
		FileContent:           content,
		FileName:              filepath.Base(req.SourcePath),
		FileType:              "pdf",
		ParserEngine:          "mineru_cloud",
		ParserEngineOverrides: overrides,
	})
	finished := now()
	if readErr != nil || result == nil || result.Error != "" || result.NativeStructure == nil {
		return "", ErrMinerUArtifactCaptureFailed
	}
	artifact := result.NativeStructure
	if err := validateMinerUCaptureArtifact(artifact, req.SourceSHA256, req.SourcePath, apiKey); err != nil {
		return "", err
	}
	contentSnapshot := result.MarkdownContent
	if err := validateMinerUCaptureContent(contentSnapshot, req.SourcePath, apiKey); err != nil {
		return "", err
	}
	contentHash := sha256.Sum256([]byte(contentSnapshot))
	contentSHA256 := hex.EncodeToString(contentHash[:])
	calls := reader.captureCallLedger()
	if calls.AllocationPOST != 1 || calls.UploadPUT != 1 || calls.StatusGET < 1 ||
		calls.StatusGET > maxMinerUStatusPolls || calls.ZIPGET != 1 {
		return "", fmt.Errorf("%w: provider call budget violated", ErrMinerUArtifactCaptureFailed)
	}
	crossPageFacts := reader.captureCrossPageProjection()
	if err := validateMinerUCrossPageProjection(crossPageFacts, req.SourceSHA256); err != nil {
		return "", fmt.Errorf("%w: cross-page projection custody", ErrMinerUArtifactCaptureFailed)
	}
	attempt := minerUCaptureAttemptIdentity{
		AttemptNumber: req.AttemptNumber,
		AttemptRole:   req.AttemptRole,
		Generation:    *req.Generation,
	}
	evidence := minerUCaptureEvidence{
		Contract:                 minerUCaptureContract,
		SourceSHA256:             req.SourceSHA256,
		Attempt:                  attempt,
		RawStructureSHA256:       artifact.RawSHA256,
		SanitizedStructureSHA256: artifact.SanitizedSHA256,
		SanitizedStructure:       json.RawMessage(append([]byte(nil), artifact.SanitizedJSON...)),
		ContentSnapshotSHA256:    contentSHA256,
		ContentSnapshot:          contentSnapshot,
		CaptureIdentitySHA256: captureMinerUIdentitySHA256(
			req.SourceSHA256, attempt, parser.ConfigSHA256, artifact.RawSHA256,
			artifact.SanitizedSHA256, contentSHA256,
		),
		Parser:              parser,
		Calls:               calls,
		LatencyMilliseconds: finished.Sub(started).Milliseconds(),
		Status:              "completed",
		CrossPageFacts:      crossPageFacts,
	}
	payload, err := json.Marshal(evidence)
	if err != nil {
		return "", ErrMinerUArtifactCaptureFailed
	}
	payload = append(payload, '\n')
	return publishMinerUCaptureEvidence(req.OutputDir, payload, minerUCapturePublishHooks{})
}

func publishMinerUCaptureEvidence(outputDir string, payload []byte, hooks minerUCapturePublishHooks) (string, error) {
	if err := os.Mkdir(outputDir, 0o700); err != nil {
		return "", fmt.Errorf("%w: create private output", ErrMinerUArtifactCaptureFailed)
	}
	removeDir := true
	defer func() {
		if removeDir {
			_ = os.Remove(outputDir)
		}
	}()
	temp, err := os.CreateTemp(outputDir, ".mineru-native-structure-")
	if err != nil {
		return "", fmt.Errorf("%w: create evidence", ErrMinerUArtifactCaptureFailed)
	}
	tempPath := temp.Name()
	defer func() { _ = os.Remove(tempPath) }()
	if err := temp.Chmod(0o600); err != nil {
		_ = temp.Close()
		return "", fmt.Errorf("%w: secure evidence", ErrMinerUArtifactCaptureFailed)
	}
	writeTemp := hooks.writeTemp
	if writeTemp == nil {
		writeTemp = func(file *os.File, data []byte) error {
			if _, err := file.Write(data); err != nil {
				return err
			}
			return file.Sync()
		}
	}
	if err := writeTemp(temp, payload); err != nil {
		_ = temp.Close()
		return "", fmt.Errorf("%w: persist evidence", ErrMinerUArtifactCaptureFailed)
	}
	if err := temp.Close(); err != nil {
		return "", fmt.Errorf("%w: close evidence", ErrMinerUArtifactCaptureFailed)
	}
	finalPath := filepath.Join(outputDir, minerUCaptureFileName)
	if hooks.beforePublish != nil {
		if err := hooks.beforePublish(finalPath); err != nil {
			return "", fmt.Errorf("%w: publication hook", ErrMinerUArtifactCaptureFailed)
		}
	}
	if err := os.Link(tempPath, finalPath); err != nil {
		return "", fmt.Errorf("%w: publish evidence no-replace", ErrMinerUArtifactCaptureFailed)
	}
	if err := os.Remove(tempPath); err != nil {
		return "", fmt.Errorf("%w: clean publication temp", ErrMinerUArtifactCaptureFailed)
	}
	removeDir = false
	return finalPath, nil
}

func validateMinerUCaptureInput(req MinerUArtifactCaptureRequest) ([]byte, minerUCaptureParserLedger, map[string]string, error) {
	if req.SourcePath == "" || req.OutputDir == "" || !validLowerSHA256(req.SourceSHA256) ||
		req.AttemptNumber != minerUCaptureAttemptNumber || req.AttemptRole != minerUCaptureAttemptRole ||
		req.Generation == nil || *req.Generation != minerUCaptureGeneration ||
		!strings.EqualFold(filepath.Ext(req.SourcePath), ".pdf") {
		return nil, minerUCaptureParserLedger{}, nil, ErrMinerUArtifactCaptureInvalidInput
	}
	allowed := map[string]bool{
		"mineru_cloud_model": true, "mineru_cloud_enable_formula": true,
		"mineru_cloud_enable_table": true, "mineru_cloud_enable_ocr": true,
		"mineru_cloud_language": true,
	}
	overrides := make(map[string]string, len(req.ParserOverrides)+1)
	for key, value := range req.ParserOverrides {
		if !allowed[key] {
			return nil, minerUCaptureParserLedger{}, nil, ErrMinerUArtifactCaptureInvalidInput
		}
		overrides[key] = value
	}
	if overrides["mineru_cloud_model"] != "pipeline" {
		return nil, minerUCaptureParserLedger{}, nil, ErrMinerUArtifactCaptureInvalidInput
	}
	formula, err := strictCaptureBool(overrides, "mineru_cloud_enable_formula", true)
	if err != nil {
		return nil, minerUCaptureParserLedger{}, nil, err
	}
	table, err := strictCaptureBool(overrides, "mineru_cloud_enable_table", true)
	if err != nil {
		return nil, minerUCaptureParserLedger{}, nil, err
	}
	ocr, err := strictCaptureBool(overrides, "mineru_cloud_enable_ocr", true)
	if err != nil {
		return nil, minerUCaptureParserLedger{}, nil, err
	}
	language := strings.TrimSpace(overrides["mineru_cloud_language"])
	if language == "" {
		language = "ch"
	}
	overrides["mineru_cloud_language"] = language
	content, err := os.ReadFile(req.SourcePath)
	if err != nil || len(content) == 0 {
		return nil, minerUCaptureParserLedger{}, nil, ErrMinerUArtifactCaptureInvalidInput
	}
	actual := sha256.Sum256(content)
	if hex.EncodeToString(actual[:]) != req.SourceSHA256 {
		return nil, minerUCaptureParserLedger{}, nil, ErrMinerUArtifactCaptureInvalidInput
	}
	parser := minerUCaptureParserLedger{
		Engine: "mineru_cloud", Implementation: minerUCaptureParserImplementation,
		NativeStructureSchema: minerUStructureSchema,
		Model:                 "pipeline", Formula: formula, Table: table, OCR: ocr, Language: language,
	}
	configPreimage, _ := json.Marshal(parser)
	parser.ConfigSHA256 = domainSHA256("mineru-capture-config.v1", string(configPreimage))
	return content, parser, overrides, nil
}

func strictCaptureBool(overrides map[string]string, key string, fallback bool) (bool, error) {
	value, ok := overrides[key]
	if !ok || value == "" {
		overrides[key] = fmt.Sprintf("%t", fallback)
		return fallback, nil
	}
	if value == "true" {
		overrides[key] = "true"
		return true, nil
	}
	if value == "false" {
		overrides[key] = "false"
		return false, nil
	}
	return false, ErrMinerUArtifactCaptureInvalidInput
}

func validateMinerUCaptureArtifact(artifact *types.NativeStructureArtifact, sourceSHA, sourcePath, apiKey string) error {
	if artifact.SchemaVersion != minerUStructureSchema || artifact.SourceSHA256 != sourceSHA ||
		!validLowerSHA256(artifact.RawSHA256) || !validLowerSHA256(artifact.SanitizedSHA256) ||
		!json.Valid(artifact.SanitizedJSON) {
		return fmt.Errorf("%w: native artifact identity invalid", ErrMinerUArtifactCaptureFailed)
	}
	hash := sha256.Sum256(artifact.SanitizedJSON)
	if hex.EncodeToString(hash[:]) != artifact.SanitizedSHA256 {
		return fmt.Errorf("%w: sanitized artifact hash mismatch", ErrMinerUArtifactCaptureFailed)
	}
	for _, forbidden := range []string{sourcePath, filepath.Base(sourcePath), apiKey, "https://", "http://", "signed_url"} {
		if forbidden != "" && bytesContains(artifact.SanitizedJSON, forbidden) {
			return fmt.Errorf("%w: sanitized artifact contains forbidden data", ErrMinerUArtifactCaptureFailed)
		}
	}
	if containsAbsolutePathInSanitizedJSON(artifact.SanitizedJSON) {
		return fmt.Errorf("%w: sanitized artifact contains forbidden data", ErrMinerUArtifactCaptureFailed)
	}
	return nil
}

func containsAbsolutePathInSanitizedJSON(payload []byte) bool {
	var decoded any
	if json.Unmarshal(payload, &decoded) != nil {
		return true
	}
	return containsAbsolutePathInJSONValue(decoded)
}

func containsAbsolutePathInJSONValue(value any) bool {
	switch typed := value.(type) {
	case string:
		return containsCrossPlatformAbsolutePath(typed)
	case []any:
		for _, item := range typed {
			if containsAbsolutePathInJSONValue(item) {
				return true
			}
		}
	case map[string]any:
		for _, item := range typed {
			if containsAbsolutePathInJSONValue(item) {
				return true
			}
		}
	}
	return false
}

func validateMinerUCaptureContent(content, sourcePath, apiKey string) error {
	if strings.TrimSpace(content) == "" {
		return fmt.Errorf("%w: content snapshot is empty", ErrMinerUArtifactCaptureFailed)
	}
	for _, forbidden := range []string{sourcePath, apiKey, "file://", "/Users/", "/private/", "/tmp/"} {
		if forbidden != "" && strings.Contains(content, forbidden) {
			return fmt.Errorf("%w: content snapshot contains forbidden data", ErrMinerUArtifactCaptureFailed)
		}
	}
	if containsCrossPlatformAbsolutePath(content) {
		return fmt.Errorf("%w: content snapshot contains forbidden data", ErrMinerUArtifactCaptureFailed)
	}
	return nil
}

func containsCrossPlatformAbsolutePath(value string) bool {
	for index := 0; index < len(value); index++ {
		if !capturePathBoundary(value, index) {
			continue
		}
		rest := value[index:]
		if rest[0] == '/' {
			if len(rest) > 1 && rest[1] != '/' && !capturePathSeparator(rest[1]) {
				return true
			}
			if strings.HasPrefix(rest, "//") && captureUNCPath(rest[2:], '/') {
				return true
			}
		}
		if strings.HasPrefix(rest, `\\`) && captureUNCPath(rest[2:], '\\') {
			return true
		}
		if len(rest) > 2 && ((rest[0] >= 'A' && rest[0] <= 'Z') ||
			(rest[0] >= 'a' && rest[0] <= 'z')) && rest[1] == ':' &&
			(rest[2] == '/' || rest[2] == '\\') {
			return true
		}
	}
	return false
}

func capturePathBoundary(value string, index int) bool {
	if index == 0 {
		return true
	}
	previous := value[index-1]
	if previous == ':' {
		prefix := strings.ToLower(value[:index])
		return !strings.HasSuffix(prefix, "http:") && !strings.HasSuffix(prefix, "https:")
	}
	return !((previous >= 'A' && previous <= 'Z') || (previous >= 'a' && previous <= 'z') ||
		(previous >= '0' && previous <= '9') || strings.ContainsRune("_-.\\/", rune(previous)))
}

func capturePathSeparator(value byte) bool {
	return value == ' ' || value == '\t' || value == '\r' || value == '\n'
}

func captureUNCPath(value string, separator byte) bool {
	first := strings.IndexByte(value, separator)
	return first > 0 && first+1 < len(value) && !capturePathSeparator(value[first+1])
}

func captureMinerUIdentitySHA256(
	sourceSHA256 string,
	attempt minerUCaptureAttemptIdentity,
	parserConfigSHA256, rawStructureSHA256, sanitizedStructureSHA256, contentSnapshotSHA256 string,
) string {
	preimage, _ := json.Marshal(struct {
		Contract                 string                       `json:"contract"`
		SourceSHA256             string                       `json:"source_sha256"`
		Attempt                  minerUCaptureAttemptIdentity `json:"attempt"`
		ParserConfigSHA256       string                       `json:"parser_config_sha256"`
		RawStructureSHA256       string                       `json:"raw_structure_sha256"`
		SanitizedStructureSHA256 string                       `json:"sanitized_structure_sha256"`
		ContentSnapshotSHA256    string                       `json:"content_snapshot_sha256"`
	}{
		Contract: minerUCaptureContract, SourceSHA256: sourceSHA256, Attempt: attempt,
		ParserConfigSHA256: parserConfigSHA256, RawStructureSHA256: rawStructureSHA256,
		SanitizedStructureSHA256: sanitizedStructureSHA256,
		ContentSnapshotSHA256:    contentSnapshotSHA256,
	})
	digest := sha256.Sum256(preimage)
	return hex.EncodeToString(digest[:])
}

func validLowerSHA256(value string) bool {
	if len(value) != 64 || strings.ToLower(value) != value {
		return false
	}
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == sha256.Size
}

func domainSHA256(domain, value string) string {
	hash := sha256.Sum256([]byte(domain + "\x00" + value))
	return hex.EncodeToString(hash[:])
}

func bytesContains(payload []byte, value string) bool {
	return strings.Contains(string(payload), value)
}
