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
	"math"
	"mime"
	"net/http"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/Tencent/WeKnora/internal/logger"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/utils"
	"github.com/google/uuid"
	"golang.org/x/net/html"
)

const (
	defaultPollInterval  = 3 * time.Second
	defaultCloudTimeout  = 600 * time.Second
	minerUCaptureTimeout = 9*time.Minute + 30*time.Second
	defaultBaseURL       = "https://mineru.net/api/v4"
	maxMinerUStatusPolls = 20
)

// MinerUCloudReader calls the MinerU Cloud API (mineru.net) to read/convert documents.
// Flow: POST /file-urls/batch → PUT file → poll GET /extract-results/batch/{batch_id}.
type MinerUCloudReader struct {
	apiKey           string
	baseURL          string
	model            string
	formulaEnable    bool
	tableEnable      bool
	ocrEnable        bool
	language         string
	capturePolicy    bool
	captureTimeout   time.Duration
	calls            minerUCloudCallLedger
	crossPageFacts   *minerUCrossPageProjection
	fetchStatus      func(context.Context, string, map[string]string) ([]extractResultItem, error)
	extractDone      func(context.Context, *extractResultItem, string, string) (string, []types.ImageRef, *types.NativeStructureArtifact, error)
	newZIPHTTPClient func(int) *http.Client
	zipURLValidator  func(string) error
	sleep            func(context.Context, time.Duration)
}

// NewMinerUCloudReader creates a reader from ParserEngineOverrides.
func NewMinerUCloudReader(overrides map[string]string) *MinerUCloudReader {
	return &MinerUCloudReader{
		apiKey:        strings.TrimSpace(overrides["mineru_api_key"]),
		baseURL:       defaultBaseURL,
		model:         stringOr(overrides["mineru_cloud_model"], "pipeline"),
		formulaEnable: parseBoolOr(overrides["mineru_cloud_enable_formula"], true),
		tableEnable:   parseBoolOr(overrides["mineru_cloud_enable_table"], true),
		ocrEnable:     parseBoolOr(overrides["mineru_cloud_enable_ocr"], true),
		language:      stringOr(overrides["mineru_cloud_language"], "ch"),
	}
}

func (c *MinerUCloudReader) enableArtifactCapturePolicy() {
	c.capturePolicy = true
	c.captureTimeout = minerUCaptureTimeout
}

func (c *MinerUCloudReader) redirectLimit() int {
	if c.capturePolicy {
		return 0
	}
	return 5
}

func (c *MinerUCloudReader) operationContext(ctx context.Context) (context.Context, context.CancelFunc) {
	if !c.capturePolicy {
		return ctx, func() {}
	}
	timeout := c.captureTimeout
	if timeout <= 0 {
		timeout = minerUCaptureTimeout
	}
	return context.WithTimeout(ctx, timeout)
}

func (c *MinerUCloudReader) zipHTTPClient() *http.Client {
	if c.newZIPHTTPClient != nil {
		return c.newZIPHTTPClient(c.redirectLimit())
	}
	return utils.NewSSRFSafeHTTPClient(utils.SSRFSafeHTTPClientConfig{
		Timeout: 120 * time.Second, MaxRedirects: c.redirectLimit(),
	})
}

func (c *MinerUCloudReader) validateZIPURL(rawURL string) error {
	if c.zipURLValidator != nil {
		return c.zipURLValidator(rawURL)
	}
	return utils.ValidateURLForSSRF(rawURL)
}

func (c *MinerUCloudReader) Read(ctx context.Context, req *types.ReadRequest) (*types.ReadResult, error) {
	c.calls = minerUCloudCallLedger{}
	c.crossPageFacts = nil
	if c.apiKey == "" {
		return &types.ReadResult{Error: "MinerU Cloud API key is not configured"}, nil
	}

	content := req.FileContent
	if len(content) == 0 {
		return &types.ReadResult{Error: "no file content provided"}, nil
	}

	logger.Infof(context.Background(), "[MinerUCloud] parsing source bytes=%d", len(content))
	readCtx, cancel := c.operationContext(ctx)
	defer cancel()

	ext := filepath.Ext(req.FileName)
	if ext == "" && req.FileType != "" {
		ext = "." + req.FileType
	}
	if ext == "" {
		ext = ".pdf"
	}
	fileName := strings.TrimSuffix(req.FileName, ext) + ext
	if fileName == ext {
		fileName = "document" + ext
	}

	effectiveModel := c.model
	if strings.EqualFold(ext, ".html") {
		effectiveModel = "MinerU-HTML"
	}
	if effectiveModel != "pipeline" {
		return nil, fmt.Errorf("%w: effective model %q is not pipeline", ErrMinerUNativeStructureUnavailable, effectiveModel)
	}

	batchID, uploadURL, err := c.applyUploadURLs(readCtx, fileName, effectiveModel)
	if err != nil {
		return nil, fmt.Errorf("MinerU Cloud apply upload URLs: %w", err)
	}

	if err := c.uploadFile(readCtx, uploadURL, content); err != nil {
		return nil, fmt.Errorf("MinerU Cloud file upload: %w", err)
	}

	sourceHash := sha256.Sum256(content)
	mdContent, imageRefs, nativeStructure, err := c.pollBatchResult(readCtx, batchID, fmt.Sprintf("%x", sourceHash), effectiveModel)
	if err != nil {
		return nil, fmt.Errorf("MinerU Cloud poll: %w", err)
	}

	mdContent, imageRefs = ensureOriginalImageRef(req, mdContent, imageRefs)

	return &types.ReadResult{
		MarkdownContent: mdContent,
		ImageRefs:       imageRefs,
		NativeStructure: nativeStructure,
	}, nil
}

func (c *MinerUCloudReader) captureCallLedger() minerUCloudCallLedger { return c.calls }

func (c *MinerUCloudReader) captureCrossPageProjection() *minerUCrossPageProjection {
	return c.crossPageFacts
}

// --- batch upload API ---

type batchApplyResponse struct {
	Code int    `json:"code"`
	Msg  string `json:"msg"`
	Data struct {
		BatchID  string   `json:"batch_id"`
		FileURLs []string `json:"file_urls"`
	} `json:"data"`
}

func (c *MinerUCloudReader) applyUploadURLs(ctx context.Context, fileName, modelVersion string) (string, string, error) {
	payload := map[string]interface{}{
		"files":          []map[string]string{{"name": fileName, "data_id": uuid.New().String()}},
		"model_version":  modelVersion,
		"is_ocr":         c.ocrEnable,
		"enable_formula": c.formulaEnable,
		"enable_table":   c.tableEnable,
		"language":       c.language,
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return "", "", fmt.Errorf("marshal payload: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/file-urls/batch", bytes.NewReader(body))
	if err != nil {
		return "", "", fmt.Errorf("create request: %w", err)
	}
	httpReq.Header.Set("Authorization", "Bearer "+c.apiKey)
	httpReq.Header.Set("Content-Type", "application/json")

	client := utils.NewSSRFSafeHTTPClient(utils.SSRFSafeHTTPClientConfig{Timeout: 30 * time.Second, MaxRedirects: c.redirectLimit()})
	c.calls.AllocationPOST++
	resp, err := client.Do(httpReq)
	if err != nil {
		return "", "", fmt.Errorf("HTTP request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return "", "", fmt.Errorf("API status %d: %s", resp.StatusCode, string(respBody))
	}

	var result batchApplyResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", "", fmt.Errorf("decode response: %w", err)
	}
	if result.Code != 0 {
		return "", "", fmt.Errorf("API error: %s", result.Msg)
	}
	if len(result.Data.FileURLs) == 0 {
		return "", "", fmt.Errorf("API returned no file_urls")
	}

	logger.Infof(context.Background(), "[MinerUCloud] allocation accepted")
	return result.Data.BatchID, result.Data.FileURLs[0], nil
}

func (c *MinerUCloudReader) uploadFile(ctx context.Context, uploadURL string, content []byte) error {
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPut, uploadURL, bytes.NewReader(content))
	if err != nil {
		return fmt.Errorf("create PUT request: %w", err)
	}

	client := utils.NewSSRFSafeHTTPClient(utils.SSRFSafeHTTPClientConfig{Timeout: 120 * time.Second, MaxRedirects: c.redirectLimit()})
	c.calls.UploadPUT++
	resp, err := client.Do(httpReq)
	if err != nil {
		return fmt.Errorf("PUT upload: %w", err)
	}
	resp.Body.Close()

	if resp.StatusCode >= 300 {
		return fmt.Errorf("PUT upload status %d", resp.StatusCode)
	}
	logger.Infof(context.Background(), "[MinerUCloud] file uploaded, status=%d", resp.StatusCode)
	return nil
}

// --- polling ---

type batchPollResponse struct {
	Code int    `json:"code"`
	Msg  string `json:"msg"`
	Data struct {
		ExtractResult json.RawMessage `json:"extract_result"` // can be object or array
	} `json:"data"`
}

type extractResultItem struct {
	State    string `json:"state"`
	FileName string `json:"file_name"`
	Markdown string `json:"markdown"`
	Content  string `json:"content"`
	Text     string `json:"text"`
	ErrMsg   string `json:"err_msg"`
	Progress struct {
		ExtractedPages int `json:"extracted_pages"`
		TotalPages     int `json:"total_pages"`
	} `json:"extract_progress"`
	FullZipURL string `json:"full_zip_url"`
}

func (c *MinerUCloudReader) pollBatchResult(ctx context.Context, batchID, sourceSHA256, effectiveModel string) (string, []types.ImageRef, *types.NativeStructureArtifact, error) {
	deadline := time.Now().Add(defaultCloudTimeout)
	headers := map[string]string{
		"Authorization": "Bearer " + c.apiKey,
	}
	fetchStatus := c.fetchStatus
	if fetchStatus == nil {
		fetchStatus = c.fetchBatchStatus
	}
	extractDone := c.extractDone
	if extractDone == nil {
		extractDone = c.extractDoneResult
	}
	sleep := c.sleep
	if sleep == nil {
		sleep = sleepCtx
	}

	for pollCount := 1; ; pollCount++ {
		if err := ctx.Err(); err != nil {
			return "", nil, nil, err
		}
		if c.capturePolicy && pollCount > maxMinerUStatusPolls {
			return "", nil, nil, fmt.Errorf("%w: %d status polls", ErrMinerUCloudPollBudgetExceeded, maxMinerUStatusPolls)
		}
		if !c.capturePolicy && !time.Now().Before(deadline) {
			return "", nil, nil, fmt.Errorf("MinerU Cloud task timed out after %d polls", pollCount-1)
		}

		c.calls.StatusGET++
		items, err := fetchStatus(ctx, batchID, headers)
		if err != nil {
			if c.capturePolicy {
				return "", nil, nil, fmt.Errorf("MinerU Cloud status transport failed: %w", err)
			}
			logger.Errorf(context.Background(), "[MinerUCloud] status poll failed; retrying")
			sleep(ctx, defaultPollInterval)
			continue
		}

		if len(items) == 0 {
			if pollCount <= 3 || pollCount%10 == 0 {
				logger.Infof(context.Background(), "[MinerUCloud] poll #%d: extract_result empty, retrying", pollCount)
			}
			if !c.capturePolicy || pollCount < maxMinerUStatusPolls {
				sleep(ctx, defaultPollInterval)
			}
			continue
		}

		item := items[0]
		state := strings.ToLower(item.State)

		if pollCount == 1 || pollCount%10 == 0 || state == "done" || state == "failed" {
			logger.Infof(context.Background(), "[MinerUCloud] poll #%d: state=%s pages=%d/%d",
				pollCount, state, item.Progress.ExtractedPages, item.Progress.TotalPages)
		}

		if state == "failed" {
			return "", nil, nil, fmt.Errorf("MinerU Cloud task failed: %s", item.ErrMsg)
		}

		if state == "done" {
			return extractDone(ctx, &item, sourceSHA256, effectiveModel)
		}

		if !c.capturePolicy || pollCount < maxMinerUStatusPolls {
			sleep(ctx, defaultPollInterval)
		}
	}
}

func (c *MinerUCloudReader) fetchBatchStatus(ctx context.Context, batchID string, headers map[string]string) ([]extractResultItem, error) {
	url := fmt.Sprintf("%s/extract-results/batch/%s", c.baseURL, batchID)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	for k, v := range headers {
		httpReq.Header.Set(k, v)
	}

	client := utils.NewSSRFSafeHTTPClient(utils.SSRFSafeHTTPClientConfig{Timeout: 30 * time.Second, MaxRedirects: c.redirectLimit()})
	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read poll response body: %w", err)
	}

	var pollResp batchPollResponse
	if err := json.Unmarshal(respBody, &pollResp); err != nil {
		return nil, fmt.Errorf("decode poll response: %w", err)
	}
	if pollResp.Code != 0 {
		return nil, fmt.Errorf("poll error code=%d msg=%s", pollResp.Code, pollResp.Msg)
	}

	if len(pollResp.Data.ExtractResult) == 0 {
		return nil, nil
	}

	// The extract_result can be either a single object or an array
	var items []extractResultItem
	if pollResp.Data.ExtractResult[0] == '[' {
		if err := json.Unmarshal(pollResp.Data.ExtractResult, &items); err != nil {
			return nil, fmt.Errorf("decode extract_result array: %w", err)
		}
	} else {
		var single extractResultItem
		if err := json.Unmarshal(pollResp.Data.ExtractResult, &single); err != nil {
			return nil, fmt.Errorf("decode extract_result object: %w", err)
		}
		items = []extractResultItem{single}
	}

	return items, nil
}

// extractDoneResult extracts markdown and images from a completed batch item.
// Prefers inline markdown/content fields; falls back to downloading full_zip_url.
func (c *MinerUCloudReader) extractDoneResult(ctx context.Context, item *extractResultItem, sourceSHA256, effectiveModel string) (string, []types.ImageRef, *types.NativeStructureArtifact, error) {
	text := firstNonEmpty(item.Markdown, item.Content, item.Text)
	if item.FullZipURL == "" {
		return "", nil, nil, fmt.Errorf("MinerU Cloud state=done but no native ZIP artifact")
	}

	c.calls.ZIPGET++
	md, imageRefs, nativeStructure, crossPageFacts, err := downloadAndExtractZip(
		ctx, item.FullZipURL, sourceSHA256, effectiveModel, c.capturePolicy, c.zipHTTPClient(), c.validateZIPURL,
	)
	if err != nil {
		return "", nil, nil, fmt.Errorf("extract zip: %w", err)
	}
	if text != "" {
		md = text
	}
	c.crossPageFacts = crossPageFacts

	logger.Infof(context.Background(), "[MinerUCloud] parsed (zip), markdown=%d chars, images=%d, native_schema=%s", len(md), len(imageRefs), nativeStructure.SchemaVersion)
	return md, imageRefs, nativeStructure, nil
}

// --- ZIP handling ---

var imgRefPattern = regexp.MustCompile(`!\[[^\]]*\]\(([^)]+)\)`)
var minerURowspanPattern = regexp.MustCompile(`\browspan\s*=`)
var minerUColspanPattern = regexp.MustCompile(`\bcolspan\s*=`)

// ErrMinerUNativeStructureUnavailable is the stable typed boundary for a ZIP
// that cannot produce the exact task-local MinerU structure contract.
var ErrMinerUNativeStructureUnavailable = errors.New("MinerU native structure unavailable")

// ErrMinerUCloudPollBudgetExceeded marks a non-terminal cloud task that reached
// the fixed capture budget. Callers must not start a second attempt implicitly.
var ErrMinerUCloudPollBudgetExceeded = errors.New("MinerU Cloud poll budget exceeded")

func downloadAndExtractZip(
	ctx context.Context, zipURL, sourceSHA256, effectiveModel string, captureProjection bool,
	client *http.Client,
	validateURL func(string) error,
) (string, []types.ImageRef, *types.NativeStructureArtifact, *minerUCrossPageProjection, error) {
	if err := validateURL(zipURL); err != nil {
		return "", nil, nil, nil, fmt.Errorf("zip URL blocked by SSRF check: %v", err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, zipURL, nil)
	if err != nil {
		return "", nil, nil, nil, fmt.Errorf("create zip request: %w", err)
	}
	resp, err := client.Do(req)
	if err != nil {
		return "", nil, nil, nil, fmt.Errorf("download zip: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", nil, nil, nil, fmt.Errorf("download zip status %d", resp.StatusCode)
	}

	var zipData []byte
	if captureProjection {
		zipData, err = readMinerUCaptureZIPBody(resp.Body, maxMinerUCrossPageZIPBytes)
	} else {
		zipData, err = io.ReadAll(resp.Body)
	}
	if err != nil {
		return "", nil, nil, nil, fmt.Errorf("read zip body: %w", err)
	}
	return extractMinerUZipBytesWithProjection(zipData, sourceSHA256, effectiveModel, captureProjection)
}

func readMinerUCaptureZIPBody(reader io.Reader, maxBytes int64) ([]byte, error) {
	payload, err := io.ReadAll(io.LimitReader(reader, maxBytes+1))
	if err != nil {
		return nil, err
	}
	if int64(len(payload)) > maxBytes {
		return nil, fmt.Errorf("%w: compressed ZIP budget", ErrMinerUCrossPageProjectionInvalid)
	}
	return payload, nil
}

func extractMinerUZipBytes(zipData []byte, sourceSHA256, effectiveModel string) (string, []types.ImageRef, *types.NativeStructureArtifact, error) {
	markdown, images, artifact, _, err := extractMinerUZipBytesWithProjection(zipData, sourceSHA256, effectiveModel, false)
	return markdown, images, artifact, err
}

func extractMinerUZipBytesWithProjection(zipData []byte, sourceSHA256, effectiveModel string, captureProjection bool) (string, []types.ImageRef, *types.NativeStructureArtifact, *minerUCrossPageProjection, error) {
	if effectiveModel != "pipeline" {
		return "", nil, nil, nil, fmt.Errorf("%w: effective model %q is not pipeline", ErrMinerUNativeStructureUnavailable, effectiveModel)
	}
	var crossPageFacts *minerUCrossPageProjection
	if _, targeted := minerUCrossPageRequiredCapability(sourceSHA256); captureProjection && targeted {
		var err error
		crossPageFacts, err = projectMinerUCrossPageZip(zipData, sourceSHA256)
		if err != nil {
			return "", nil, nil, nil, err
		}
	}

	zr, err := zip.NewReader(bytes.NewReader(zipData), int64(len(zipData)))
	if err != nil {
		return "", nil, nil, nil, fmt.Errorf("open zip: %w", err)
	}

	// Find .md files
	var mdFiles, nativeFiles []string
	entries := make(map[string]*zip.File)
	for _, f := range zr.File {
		entries[f.Name] = f
		if strings.HasSuffix(f.Name, ".md") {
			mdFiles = append(mdFiles, f.Name)
		}
		base := filepath.Base(f.Name)
		if strings.HasSuffix(base, "_content_list.json") && !strings.HasSuffix(base, "_content_list_v2.json") {
			nativeFiles = append(nativeFiles, f.Name)
		}
	}
	if len(mdFiles) == 0 {
		return "", nil, nil, nil, fmt.Errorf("%w: no Markdown presentation", ErrMinerUNativeStructureUnavailable)
	}
	if len(nativeFiles) != 1 {
		return "", nil, nil, nil, fmt.Errorf("%w: expected one pipeline content-list, got %d", ErrMinerUNativeStructureUnavailable, len(nativeFiles))
	}
	sort.Slice(mdFiles, func(i, j int) bool {
		di, dj := strings.Count(mdFiles[i], "/"), strings.Count(mdFiles[j], "/")
		if di != dj {
			return di < dj
		}
		return mdFiles[i] < mdFiles[j]
	})

	mdText, err := readZipEntry(entries[mdFiles[0]])
	if err != nil {
		return "", nil, nil, nil, fmt.Errorf("read md file: %w", err)
	}
	rawNative, err := readZipEntryBytes(entries[nativeFiles[0]])
	if err != nil {
		return "", nil, nil, nil, fmt.Errorf("read native content-list: %w", err)
	}
	nativeStructure, err := normalizeMinerUContentList(rawNative, sourceSHA256, effectiveModel)
	if err != nil {
		return "", nil, nil, nil, fmt.Errorf("%w: %v", ErrMinerUNativeStructureUnavailable, err)
	}

	mdDir := filepath.Dir(mdFiles[0])

	// Extract referenced images
	var imageRefs []types.ImageRef
	seen := map[string]bool{}
	for _, match := range imgRefPattern.FindAllStringSubmatch(mdText, -1) {
		imgPath := match[1]
		if strings.HasPrefix(imgPath, "http://") || strings.HasPrefix(imgPath, "https://") || strings.HasPrefix(imgPath, "data:") {
			continue
		}
		if seen[imgPath] {
			continue
		}
		seen[imgPath] = true

		resolved := resolveInZip(imgPath, mdDir, entries)
		if resolved == nil {
			logger.Errorf(context.Background(), "[MinerUCloud] referenced image missing from ZIP")
			continue
		}

		imgData, err := readZipEntryBytes(resolved)
		if err != nil {
			logger.Errorf(context.Background(), "[MinerUCloud] referenced image unreadable")
			continue
		}

		ext := strings.ToLower(filepath.Ext(resolved.Name))
		if ext == "" {
			ext = ".png"
		}
		mimeType := mime.TypeByExtension(ext)
		if mimeType == "" {
			mimeType = "image/png"
		}

		imageRefs = append(imageRefs, types.ImageRef{
			Filename:    filepath.Base(resolved.Name),
			OriginalRef: imgPath,
			MimeType:    mimeType,
			ImageData:   imgData,
		})
	}

	return mdText, imageRefs, nativeStructure, crossPageFacts, nil
}

const (
	minerUSourceSchema    = "mineru.content-list.pipeline.v1"
	minerUStructureSchema = "mineru-native-structure.v1"
)

type minerUContentItem struct {
	Type          string        `json:"type"`
	PageIndex     *int          `json:"page_idx"`
	BBox          []json.Number `json:"bbox"`
	Text          string        `json:"text"`
	TextLevel     *int          `json:"text_level"`
	SubType       string        `json:"sub_type"`
	TextFormat    string        `json:"text_format"`
	TableBody     string        `json:"table_body"`
	TableCaption  []string      `json:"table_caption"`
	TableFootnote []string      `json:"table_footnote"`
	ImagePath     string        `json:"img_path"`
	ImageCaption  []string      `json:"image_caption"`
	ImageFootnote []string      `json:"image_footnote"`
	ChartContent  string        `json:"content"`
	ChartCaption  []string      `json:"chart_caption"`
	ChartFootnote []string      `json:"chart_footnote"`
	CodeBody      string        `json:"code_body"`
	CodeCaption   []string      `json:"code_caption"`
	CodeFootnote  []string      `json:"code_footnote"`
	ListItems     []string      `json:"list_items"`
}

func minerUTypeSpecificKeys(itemType string) (map[string]bool, []string, bool) {
	common := map[string]bool{"type": true, "page_idx": true, "bbox": true}
	add := func(keys ...string) map[string]bool {
		result := make(map[string]bool, len(common)+len(keys))
		for key := range common {
			result[key] = true
		}
		for _, key := range keys {
			result[key] = true
		}
		return result
	}
	switch itemType {
	case "text":
		return add("text", "text_level"), []string{"text"}, true
	case "header", "footer", "page_number", "aside_text", "page_footnote":
		return add("text"), []string{"text"}, true
	case "table":
		return add("table_body", "table_caption", "table_footnote", "img_path"), []string{"table_body"}, true
	case "image":
		return add("img_path", "image_caption", "image_footnote", "sub_type"), []string{"img_path"}, true
	case "chart":
		return add("img_path", "content", "chart_caption", "chart_footnote", "sub_type"), []string{"img_path"}, true
	case "equation":
		return add("img_path", "text", "text_format"), []string{"text", "text_format"}, true
	case "code":
		return add("sub_type", "code_body", "code_caption", "code_footnote"), []string{"code_body"}, true
	case "list":
		return add("sub_type", "list_items"), []string{"list_items"}, true
	default:
		return nil, nil, false
	}
}

func validateMinerUJSONNumber(raw json.RawMessage, integer bool) error {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return err
	}
	number, ok := value.(json.Number)
	if !ok {
		return fmt.Errorf("value is not a JSON number")
	}
	if integer {
		if _, err := strconv.ParseInt(number.String(), 10, 64); err != nil {
			return err
		}
		return nil
	}
	parsed, err := strconv.ParseFloat(number.String(), 64)
	if err != nil || math.IsInf(parsed, 0) || math.IsNaN(parsed) {
		return fmt.Errorf("value is not a finite JSON number")
	}
	return nil
}

func validateMinerUContentFieldTypes(fields map[string]json.RawMessage) error {
	stringFields := map[string]bool{
		"type": true, "text": true, "sub_type": true, "text_format": true,
		"table_body": true, "img_path": true, "content": true, "code_body": true,
	}
	stringListFields := map[string]bool{
		"table_caption": true, "table_footnote": true,
		"image_caption": true, "image_footnote": true,
		"chart_caption": true, "chart_footnote": true,
		"code_caption": true, "code_footnote": true, "list_items": true,
	}
	for key, raw := range fields {
		switch {
		case stringFields[key]:
			var value string
			if bytes.Equal(bytes.TrimSpace(raw), []byte("null")) || json.Unmarshal(raw, &value) != nil {
				return fmt.Errorf("MinerU native content-list key %q has invalid string type", key)
			}
		case stringListFields[key]:
			if bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
				return fmt.Errorf("MinerU native content-list key %q has invalid string-list type", key)
			}
			var values []json.RawMessage
			if err := json.Unmarshal(raw, &values); err != nil {
				return fmt.Errorf("MinerU native content-list key %q has invalid string-list type", key)
			}
			for _, item := range values {
				var value string
				if bytes.Equal(bytes.TrimSpace(item), []byte("null")) || json.Unmarshal(item, &value) != nil {
					return fmt.Errorf("MinerU native content-list key %q has invalid string-list type", key)
				}
			}
		case key == "page_idx" || key == "text_level":
			if err := validateMinerUJSONNumber(raw, true); err != nil {
				return fmt.Errorf("MinerU native content-list key %q has invalid integer type", key)
			}
		case key == "bbox":
			if bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
				return fmt.Errorf("MinerU native content-list bbox has invalid number-list type")
			}
			var values []json.RawMessage
			if err := json.Unmarshal(raw, &values); err != nil || len(values) != 4 {
				return fmt.Errorf("MinerU native content-list bbox has invalid number-list type")
			}
			for _, item := range values {
				if err := validateMinerUJSONNumber(item, false); err != nil {
					return fmt.Errorf("MinerU native content-list bbox has invalid number-list type")
				}
			}
		}
	}
	return nil
}

func decodeMinerUContentList(raw []byte) ([]minerUContentItem, error) {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var rawItems []json.RawMessage
	if err := decoder.Decode(&rawItems); err != nil || len(rawItems) == 0 {
		return nil, fmt.Errorf("MinerU native content-list invalid")
	}
	var trailing json.RawMessage
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return nil, fmt.Errorf("MinerU native content-list has trailing values")
	}
	items := make([]minerUContentItem, 0, len(rawItems))
	for _, rawItem := range rawItems {
		var fields map[string]json.RawMessage
		if err := json.Unmarshal(rawItem, &fields); err != nil {
			return nil, fmt.Errorf("MinerU native content-list item invalid")
		}
		var itemType string
		if err := json.Unmarshal(fields["type"], &itemType); err != nil || itemType == "" {
			return nil, fmt.Errorf("MinerU native content-list item type invalid")
		}
		allowed, required, ok := minerUTypeSpecificKeys(itemType)
		if !ok {
			return nil, fmt.Errorf("MinerU native content type is unsupported")
		}
		for key := range fields {
			if !allowed[key] {
				return nil, fmt.Errorf("MinerU native content-list key %q is invalid for %s", key, itemType)
			}
		}
		for _, key := range append([]string{"type", "page_idx", "bbox"}, required...) {
			if _, ok := fields[key]; !ok {
				return nil, fmt.Errorf("MinerU native content-list key %q is required for %s", key, itemType)
			}
		}
		if err := validateMinerUContentFieldTypes(fields); err != nil {
			return nil, err
		}
		itemDecoder := json.NewDecoder(bytes.NewReader(rawItem))
		itemDecoder.UseNumber()
		itemDecoder.DisallowUnknownFields()
		var item minerUContentItem
		if err := itemDecoder.Decode(&item); err != nil {
			return nil, fmt.Errorf("MinerU native content-list item invalid")
		}
		items = append(items, item)
	}
	return items, nil
}

type minerUSanitizedPage struct {
	PageID        string `json:"page_id"`
	PageNumber    int    `json:"page_number"`
	ContentHash   string `json:"content_hash"`
	StructureHash string `json:"structure_hash"`
}

type minerUSanitizedBlock struct {
	BlockID       string   `json:"block_id"`
	OrderIndex    int      `json:"order_index"`
	PageNumber    int      `json:"page_number"`
	BlockIndex    int      `json:"block_index"`
	BBox          []string `json:"bbox"`
	ContentHash   string   `json:"content_hash"`
	StructureHash string   `json:"structure_hash"`
}

type minerUSanitizedTable struct {
	TableID       string   `json:"table_id"`
	OrderIndex    int      `json:"order_index"`
	PageNumber    int      `json:"page_number"`
	TableIndex    int      `json:"table_index"`
	BBox          []string `json:"bbox"`
	ContentHash   string   `json:"content_hash"`
	StructureHash string   `json:"structure_hash"`
	RowCount      int      `json:"row_count"`
	ColumnCount   int      `json:"column_count"`
	HeaderCellIDs []string `json:"header_cell_ids"`
}

type minerUSanitizedCell struct {
	CellID        string   `json:"cell_id"`
	OrderIndex    int      `json:"order_index"`
	TableID       string   `json:"table_id"`
	PageNumber    int      `json:"page_number"`
	RowIndex      int      `json:"row_index"`
	ColumnIndex   int      `json:"column_index"`
	RowSpan       int      `json:"row_span"`
	ColumnSpan    int      `json:"column_span"`
	BBox          []string `json:"bbox"`
	ContentHash   string   `json:"content_hash"`
	StructureHash string   `json:"structure_hash"`
}

type minerUSanitizedDocument struct {
	Contract     string                 `json:"contract"`
	SourceSchema string                 `json:"source_schema"`
	ParserModel  string                 `json:"parser_model"`
	SourceSHA256 string                 `json:"source_sha256"`
	RawSHA256    string                 `json:"raw_sha256"`
	Pages        []minerUSanitizedPage  `json:"pages"`
	Blocks       []minerUSanitizedBlock `json:"blocks"`
	Tables       []minerUSanitizedTable `json:"tables"`
	Cells        []minerUSanitizedCell  `json:"cells"`
	Unsupported  []string               `json:"unsupported"`
}

func containsString(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func minerUHash(domain string, parts ...string) string {
	hash := sha256.New()
	_, _ = io.WriteString(hash, "mineru-060:")
	_, _ = io.WriteString(hash, domain)
	for _, part := range parts {
		_, _ = hash.Write([]byte{0})
		_, _ = io.WriteString(hash, part)
	}
	return fmt.Sprintf("%x", hash.Sum(nil))
}

func minerUStableID(kind string, rawHash string, index int, parts ...string) string {
	identity := minerUHash(kind, append([]string{rawHash, strconv.Itoa(index)}, parts...)...)
	return fmt.Sprintf("%s-%06d-%s", kind, index, identity[:16])
}

func minerUBBox(raw []json.Number) ([]string, error) {
	if len(raw) != 4 {
		return nil, fmt.Errorf("MinerU native structure invalid bbox")
	}
	result := make([]string, 4)
	values := make([]float64, 4)
	for index, value := range raw {
		parsed, err := strconv.ParseFloat(value.String(), 64)
		if err != nil || math.IsInf(parsed, 0) || math.IsNaN(parsed) {
			return nil, fmt.Errorf("MinerU native structure invalid bbox")
		}
		values[index] = parsed
		result[index] = strconv.FormatFloat(parsed, 'f', -1, 64)
	}
	if values[0] < 0 || values[1] < 0 || values[2] > 1000 || values[3] > 1000 || values[2] <= values[0] || values[3] <= values[1] {
		return nil, fmt.Errorf("MinerU native structure invalid bbox")
	}
	return result, nil
}

func minerUNodeText(node *html.Node) string {
	var builder strings.Builder
	var walk func(*html.Node)
	walk = func(current *html.Node) {
		if current.Type == html.TextNode {
			builder.WriteString(current.Data)
		}
		for child := current.FirstChild; child != nil; child = child.NextSibling {
			walk(child)
		}
	}
	walk(node)
	return strings.TrimSpace(builder.String())
}

func minerUSpan(node *html.Node, name string) (int, error) {
	seen := false
	for _, attribute := range node.Attr {
		if strings.EqualFold(attribute.Key, name) {
			if seen {
				return 0, fmt.Errorf("MinerU native table duplicate %s", name)
			}
			seen = true
			value, err := strconv.Atoi(attribute.Val)
			if err != nil || value <= 0 {
				return 0, fmt.Errorf("MinerU native table invalid %s", name)
			}
			return value, nil
		}
	}
	return 1, nil
}

func validateMinerUTableHTML(body string) error {
	tokenizer := html.NewTokenizer(strings.NewReader(body))
	tableDepth, rowDepth, cellDepth, tableCount := 0, 0, 0, 0
	currentCellTag := ""
	openTags := make([]string, 0)
	voidElements := map[string]bool{
		"area": true, "base": true, "br": true, "col": true, "embed": true,
		"hr": true, "img": true, "input": true, "link": true, "meta": true,
		"param": true, "source": true, "track": true, "wbr": true,
	}
	for {
		tokenType := tokenizer.Next()
		switch tokenType {
		case html.ErrorToken:
			if !errors.Is(tokenizer.Err(), io.EOF) {
				return fmt.Errorf("MinerU native table invalid HTML: %w", tokenizer.Err())
			}
			if tableCount != 1 || tableDepth != 0 || rowDepth != 0 || cellDepth != 0 || len(openTags) != 0 {
				return fmt.Errorf("MinerU native table HTML is incomplete")
			}
			return nil
		case html.SelfClosingTagToken:
			name, _ := tokenizer.TagName()
			if !voidElements[string(name)] {
				return fmt.Errorf("MinerU native table non-void tag cannot self-close")
			}
		case html.StartTagToken:
			nameBytes, hasAttributes := tokenizer.TagName()
			name := string(nameBytes)
			if name == "td" || name == "th" {
				rawTag := strings.ToLower(string(tokenizer.Raw()))
				if len(minerURowspanPattern.FindAllStringIndex(rawTag, -1)) > 1 ||
					len(minerUColspanPattern.FindAllStringIndex(rawTag, -1)) > 1 {
					return fmt.Errorf("MinerU native table duplicate span attribute")
				}
				seen := make(map[string]bool)
				for hasAttributes {
					key, _, more := tokenizer.TagAttr()
					attribute := strings.ToLower(string(key))
					if attribute == "rowspan" || attribute == "colspan" {
						if seen[attribute] {
							return fmt.Errorf("MinerU native table duplicate %s", attribute)
						}
						seen[attribute] = true
					}
					hasAttributes = more
				}
			}
			switch name {
			case "table":
				if tableDepth != 0 || cellDepth != 0 {
					return fmt.Errorf("MinerU native table nesting is invalid")
				}
				tableDepth, tableCount = 1, tableCount+1
			case "tr":
				if tableDepth != 1 || rowDepth != 0 || cellDepth != 0 {
					return fmt.Errorf("MinerU native table row nesting is invalid")
				}
				rowDepth = 1
			case "td", "th":
				if tableDepth != 1 || rowDepth != 1 || cellDepth != 0 {
					return fmt.Errorf("MinerU native table cell nesting is invalid")
				}
				cellDepth = 1
				currentCellTag = name
			}
			if !voidElements[name] {
				openTags = append(openTags, name)
			}
		case html.EndTagToken:
			nameBytes, _ := tokenizer.TagName()
			name := string(nameBytes)
			if voidElements[name] || len(openTags) == 0 || openTags[len(openTags)-1] != name {
				return fmt.Errorf("MinerU native table tag closing order is invalid")
			}
			switch name {
			case "table":
				if tableDepth != 1 || rowDepth != 0 || cellDepth != 0 {
					return fmt.Errorf("MinerU native table closing order is invalid")
				}
				tableDepth = 0
			case "tr":
				if rowDepth != 1 || cellDepth != 0 {
					return fmt.Errorf("MinerU native table row closing order is invalid")
				}
				rowDepth = 0
			case "td", "th":
				if cellDepth != 1 || currentCellTag != string(nameBytes) {
					return fmt.Errorf("MinerU native table cell closing order is invalid")
				}
				cellDepth = 0
				currentCellTag = ""
			}
			openTags = openTags[:len(openTags)-1]
		}
	}
}

func minerUNearestTable(node *html.Node) *html.Node {
	for current := node.Parent; current != nil; current = current.Parent {
		if current.Type == html.ElementNode && current.Data == "table" {
			return current
		}
	}
	return nil
}

type minerUTableCell struct {
	rowIndex    int
	columnIndex int
	rowSpan     int
	columnSpan  int
	header      bool
	contentHash string
}

func parseMinerUTable(body string) ([]minerUTableCell, int, int, error) {
	if err := validateMinerUTableHTML(body); err != nil {
		return nil, 0, 0, err
	}
	document, err := html.Parse(strings.NewReader(body))
	if err != nil {
		return nil, 0, 0, fmt.Errorf("MinerU native table invalid HTML: %w", err)
	}
	var tables []*html.Node
	var collectTables func(*html.Node)
	collectTables = func(node *html.Node) {
		if node.Type == html.ElementNode && node.Data == "table" {
			tables = append(tables, node)
		}
		for child := node.FirstChild; child != nil; child = child.NextSibling {
			collectTables(child)
		}
	}
	collectTables(document)
	if len(tables) != 1 {
		return nil, 0, 0, fmt.Errorf("MinerU native table requires exactly one table element")
	}
	table := tables[0]
	var rows []*html.Node
	var collectRows func(*html.Node)
	collectRows = func(node *html.Node) {
		if node.Type == html.ElementNode && node.Data == "tr" && minerUNearestTable(node) == table {
			rows = append(rows, node)
		}
		for child := node.FirstChild; child != nil; child = child.NextSibling {
			collectRows(child)
		}
	}
	collectRows(table)
	if len(rows) == 0 {
		return nil, 0, 0, fmt.Errorf("MinerU native table has no rows")
	}

	occupied := make(map[[2]int]bool)
	var cells []minerUTableCell
	columnCount := 0
	for rowIndex, row := range rows {
		columnIndex := 0
		for node := row.FirstChild; node != nil; node = node.NextSibling {
			if node.Type != html.ElementNode || (node.Data != "td" && node.Data != "th") {
				continue
			}
			for occupied[[2]int{rowIndex, columnIndex}] {
				columnIndex++
			}
			rowSpan, err := minerUSpan(node, "rowspan")
			if err != nil {
				return nil, 0, 0, err
			}
			columnSpan, err := minerUSpan(node, "colspan")
			if err != nil {
				return nil, 0, 0, err
			}
			if rowIndex+rowSpan > len(rows) {
				return nil, 0, 0, fmt.Errorf("MinerU native table rowspan exceeds grid")
			}
			for coveredRow := rowIndex; coveredRow < rowIndex+rowSpan; coveredRow++ {
				for coveredColumn := columnIndex; coveredColumn < columnIndex+columnSpan; coveredColumn++ {
					position := [2]int{coveredRow, coveredColumn}
					if occupied[position] {
						return nil, 0, 0, fmt.Errorf("MinerU native table spans overlap")
					}
					occupied[position] = true
				}
			}
			cells = append(cells, minerUTableCell{
				rowIndex:    rowIndex,
				columnIndex: columnIndex,
				rowSpan:     rowSpan,
				columnSpan:  columnSpan,
				header:      node.Data == "th",
				contentHash: minerUHash("cell-content", minerUNodeText(node)),
			})
			columnIndex += columnSpan
			if columnIndex > columnCount {
				columnCount = columnIndex
			}
		}
	}
	if len(cells) == 0 || columnCount == 0 {
		return nil, 0, 0, fmt.Errorf("MinerU native table has no cells")
	}
	for rowIndex := range rows {
		for columnIndex := 0; columnIndex < columnCount; columnIndex++ {
			if !occupied[[2]int{rowIndex, columnIndex}] {
				return nil, 0, 0, fmt.Errorf("MinerU native table grid is incomplete")
			}
		}
	}
	return cells, len(rows), columnCount, nil
}

func normalizeMinerUContentList(raw []byte, sourceSHA256, effectiveModel string) (*types.NativeStructureArtifact, error) { //nolint:gocyclo
	if effectiveModel != "pipeline" {
		return nil, fmt.Errorf("MinerU native structure requires pipeline model")
	}
	if len(sourceSHA256) != 64 {
		return nil, fmt.Errorf("MinerU source identity is invalid")
	}
	if _, err := hex.DecodeString(sourceSHA256); err != nil {
		return nil, fmt.Errorf("MinerU source identity is invalid")
	}
	items, err := decodeMinerUContentList(raw)
	if err != nil {
		return nil, err
	}
	rawHashBytes := sha256.Sum256(raw)
	rawHash := fmt.Sprintf("%x", rawHashBytes)
	document := minerUSanitizedDocument{
		Contract:     minerUStructureSchema,
		SourceSchema: minerUSourceSchema,
		ParserModel:  effectiveModel,
		SourceSHA256: sourceSHA256,
		RawSHA256:    rawHash,
		Unsupported:  []string{"cross_page_sections", "cross_page_tables"},
	}
	pageBlocks := make(map[int][]string)
	pageTables := make(map[int][]string)
	pageBlockIndex := make(map[int]int)
	pageTableIndex := make(map[int]int)
	pageSeen := make(map[int]bool)
	for itemIndex, item := range items {
		if item.PageIndex == nil || *item.PageIndex < 0 || strings.TrimSpace(item.Type) == "" {
			return nil, fmt.Errorf("MinerU native content-list identity is incomplete")
		}
		pageIndex := *item.PageIndex
		pageSeen[pageIndex] = true
		bbox, err := minerUBBox(item.BBox)
		if err != nil {
			for _, capability := range []string{"native_structure_invalid", "block_locators"} {
				if !containsString(document.Unsupported, capability) {
					document.Unsupported = append(document.Unsupported, capability)
				}
			}
			if item.Type == "table" {
				for _, capability := range []string{"table_grid", "cell_locators", "row_column_indices", "merged_cells", "header_hierarchy"} {
					if !containsString(document.Unsupported, capability) {
						document.Unsupported = append(document.Unsupported, capability)
					}
				}
			}
			continue
		}
		var content string
		switch item.Type {
		case "text", "header", "footer", "page_number", "aside_text", "page_footnote":
			if strings.TrimSpace(item.Text) == "" {
				return nil, fmt.Errorf("MinerU native text block is empty")
			}
			content = item.Text
		case "table":
			if strings.TrimSpace(item.TableBody) == "" {
				return nil, fmt.Errorf("MinerU native table body is empty")
			}
			content = item.TableBody
		case "image":
			content = strings.Join(append([]string{item.SubType, item.ImagePath}, append(item.ImageCaption, item.ImageFootnote...)...), "\x00")
		case "chart":
			content = strings.Join(append([]string{item.SubType, item.ImagePath, item.ChartContent}, append(item.ChartCaption, item.ChartFootnote...)...), "\x00")
		case "equation":
			content = strings.Join([]string{item.TextFormat, item.Text, item.ImagePath}, "\x00")
		case "code":
			content = strings.Join(append([]string{item.SubType, item.CodeBody}, append(item.CodeCaption, item.CodeFootnote...)...), "\x00")
		case "list":
			content = strings.Join(append([]string{item.SubType}, item.ListItems...), "\x00")
		default:
			return nil, fmt.Errorf("MinerU native content type is unsupported")
		}
		contentHash := minerUHash("block-content", content)
		blockID := minerUStableID("block", rawHash, itemIndex, strconv.Itoa(pageIndex), item.Type, strings.Join(bbox, ","), contentHash)
		blockIndex := pageBlockIndex[pageIndex]
		pageBlockIndex[pageIndex]++
		document.Blocks = append(document.Blocks, minerUSanitizedBlock{
			BlockID:       blockID,
			OrderIndex:    len(document.Blocks),
			PageNumber:    pageIndex + 1,
			BlockIndex:    blockIndex,
			BBox:          bbox,
			ContentHash:   contentHash,
			StructureHash: minerUHash("block-structure", item.Type, strconv.Itoa(pageIndex), strconv.Itoa(blockIndex), strings.Join(bbox, ",")),
		})
		pageBlocks[pageIndex] = append(pageBlocks[pageIndex], blockID)
		if item.Type != "table" {
			continue
		}

		parsedCells, rowCount, columnCount, err := parseMinerUTable(item.TableBody)
		if err != nil {
			for _, capability := range []string{"table_grid", "cell_locators", "row_column_indices", "merged_cells", "header_hierarchy"} {
				if !containsString(document.Unsupported, capability) {
					document.Unsupported = append(document.Unsupported, capability)
				}
			}
			continue
		}
		tableIndex := pageTableIndex[pageIndex]
		pageTableIndex[pageIndex]++
		tableID := minerUStableID("table", rawHash, len(document.Tables), blockID, contentHash)
		cellStart := len(document.Cells)
		headerIDs := make([]string, 0)
		for _, parsedCell := range parsedCells {
			cellID := minerUStableID("cell", rawHash, len(document.Cells), tableID, strconv.Itoa(parsedCell.rowIndex), strconv.Itoa(parsedCell.columnIndex), strconv.Itoa(parsedCell.rowSpan), strconv.Itoa(parsedCell.columnSpan), parsedCell.contentHash)
			cell := minerUSanitizedCell{
				CellID:        cellID,
				OrderIndex:    len(document.Cells),
				TableID:       tableID,
				PageNumber:    pageIndex + 1,
				RowIndex:      parsedCell.rowIndex,
				ColumnIndex:   parsedCell.columnIndex,
				RowSpan:       parsedCell.rowSpan,
				ColumnSpan:    parsedCell.columnSpan,
				BBox:          append([]string(nil), bbox...),
				ContentHash:   parsedCell.contentHash,
				StructureHash: minerUHash("cell-structure", tableID, strconv.Itoa(parsedCell.rowIndex), strconv.Itoa(parsedCell.columnIndex), strconv.Itoa(parsedCell.rowSpan), strconv.Itoa(parsedCell.columnSpan), strings.Join(bbox, ",")),
			}
			document.Cells = append(document.Cells, cell)
			if parsedCell.header {
				headerIDs = append(headerIDs, cellID)
			}
		}
		cellIDs := make([]string, 0, len(document.Cells)-cellStart)
		cellHashes := make([]string, 0, len(document.Cells)-cellStart)
		for _, cell := range document.Cells[cellStart:] {
			cellIDs = append(cellIDs, cell.CellID)
			cellHashes = append(cellHashes, cell.ContentHash)
		}
		document.Tables = append(document.Tables, minerUSanitizedTable{
			TableID:       tableID,
			OrderIndex:    len(document.Tables),
			PageNumber:    pageIndex + 1,
			TableIndex:    tableIndex,
			BBox:          append([]string(nil), bbox...),
			ContentHash:   minerUHash("table-content", cellHashes...),
			StructureHash: minerUHash("table-structure", tableID, strconv.Itoa(rowCount), strconv.Itoa(columnCount), strings.Join(cellIDs, ",")),
			RowCount:      rowCount,
			ColumnCount:   columnCount,
			HeaderCellIDs: headerIDs,
		})
		pageTables[pageIndex] = append(pageTables[pageIndex], tableID)
	}
	for pageIndex := 0; pageIndex < len(pageSeen); pageIndex++ {
		if !pageSeen[pageIndex] {
			return nil, fmt.Errorf("MinerU native pages are not contiguous from zero")
		}
		pageID := minerUStableID("page", rawHash, pageIndex, strings.Join(pageBlocks[pageIndex], ","), strings.Join(pageTables[pageIndex], ","))
		document.Pages = append(document.Pages, minerUSanitizedPage{
			PageID:        pageID,
			PageNumber:    pageIndex + 1,
			ContentHash:   minerUHash("page-content", strings.Join(pageBlocks[pageIndex], ",")),
			StructureHash: minerUHash("page-structure", pageID, strings.Join(pageBlocks[pageIndex], ","), strings.Join(pageTables[pageIndex], ",")),
		})
	}
	sanitized, err := json.Marshal(document)
	if err != nil {
		return nil, fmt.Errorf("marshal MinerU native structure: %w", err)
	}
	sanitizedHash := sha256.Sum256(sanitized)
	return &types.NativeStructureArtifact{
		SchemaVersion:   minerUStructureSchema,
		SourceSHA256:    sourceSHA256,
		RawSHA256:       rawHash,
		SanitizedSHA256: fmt.Sprintf("%x", sanitizedHash),
		SanitizedJSON:   append([]byte(nil), sanitized...),
	}, nil
}

func resolveInZip(imgPath, mdDir string, entries map[string]*zip.File) *zip.File {
	normalized := strings.ReplaceAll(imgPath, "\\", "/")
	if f, ok := entries[normalized]; ok {
		return f
	}
	if mdDir != "" && mdDir != "." {
		joined := mdDir + "/" + normalized
		if f, ok := entries[joined]; ok {
			return f
		}
	}
	return nil
}

func readZipEntry(f *zip.File) (string, error) {
	rc, err := f.Open()
	if err != nil {
		return "", err
	}
	defer rc.Close()
	data, err := io.ReadAll(rc)
	if err != nil {
		return "", err
	}
	return string(data), nil
}

func readZipEntryBytes(f *zip.File) ([]byte, error) {
	rc, err := f.Open()
	if err != nil {
		return nil, err
	}
	defer rc.Close()
	return io.ReadAll(rc)
}

// PingMinerUCloud checks if the MinerU Cloud API is reachable with the given API key.
func PingMinerUCloud(apiKey string) (bool, string) {
	apiKey = strings.TrimSpace(apiKey)
	if apiKey == "" {
		return false, "未配置 MinerU Cloud API Key"
	}

	targetURL := defaultBaseURL + "/file-urls/batch"
	payload := []byte(`{"files":[],"model_version":"pipeline"}`)
	req, err := http.NewRequest(http.MethodPost, targetURL, bytes.NewReader(payload))
	if err != nil {
		return false, fmt.Sprintf("构建请求失败: %v", err)
	}
	req.Header.Set("Authorization", "Bearer "+apiKey)
	req.Header.Set("Content-Type", "application/json")

	client := utils.NewSSRFSafeHTTPClient(utils.SSRFSafeHTTPClientConfig{
		Timeout:      10 * time.Second,
		MaxRedirects: 5,
	})
	resp, err := client.Do(req)
	if err != nil {
		return false, fmt.Sprintf("MinerU Cloud 不可达: %v", err)
	}
	resp.Body.Close()

	if resp.StatusCode == 401 || resp.StatusCode == 403 {
		return false, "MinerU Cloud API Key 无效"
	}
	return true, ""
}
