package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"path"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
)

type ProductIngestionScope struct {
	TenantID            uint64
	SpaceID             string
	RawKnowledgeBaseID  string
	WikiKnowledgeBaseID string
}
type ProductIngestionBridgeOptions struct {
	BaseURL          string
	Credential       string
	Scope            ProductIngestionScope
	Timeout          time.Duration
	MaxResponseBytes int64
	MaxUploadFiles   int
	MaxUploadBytes   int64
	Transport        http.RoundTripper
}
type ProductIngestionCounts struct {
	SuccessCount *int `json:"success_count,omitempty"`
	MissingCount *int `json:"missing_count,omitempty"`
	FailureCount *int `json:"failure_count,omitempty"`
}
type ProductIngestionStage struct {
	ProductIngestionCounts
	Name       string  `json:"name"`
	State      string  `json:"state"`
	StartedAt  *string `json:"started_at,omitempty"`
	FinishedAt *string `json:"finished_at,omitempty"`
}
type ProductIngestionField struct {
	FieldKey string  `json:"field_key"`
	Outcome  string  `json:"outcome"`
	Reason   *string `json:"reason,omitempty"`
	Attempt  int     `json:"attempt,omitempty"`
}

// Status summaries are allowlisted DTOs, never arbitrary model or artifact JSON.
// Nullable counters have no omitempty: unknown must survive as null, not zero.
type ProductIngestionSourceCounts struct {
	Attempts         int `json:"attempts"`
	Confirmed        int `json:"confirmed"`
	Interrupted      int `json:"interrupted"`
	NotDispatched    int `json:"not_dispatched"`
	TransportRetries int `json:"transport_retries"`
}
type ProductIngestionSourceOccurrence struct {
	Occurrence       int    `json:"occurrence"`
	Status           string `json:"status"`
	StartedAtUnixMS  int64  `json:"started_at_unix_ms"`
	FinishedAtUnixMS int64  `json:"finished_at_unix_ms"`
	DurationMS       int64  `json:"duration_ms"`
}
type ProductIngestionSourcePhase struct {
	Phase       string                             `json:"phase"`
	Recorded    bool                               `json:"recorded"`
	Occurrences []ProductIngestionSourceOccurrence `json:"occurrences"`
}
type ProductIngestionSourceMaterial struct {
	KnowledgeID   string                        `json:"knowledge_id"`
	FileName      *string                       `json:"file_name"`
	Reused        bool                          `json:"reused"`
	Availability  string                        `json:"availability"`
	ReceiptSHA256 *string                       `json:"receipt_sha256"`
	Counts        *ProductIngestionSourceCounts `json:"counts"`
	Phases        []ProductIngestionSourcePhase `json:"phases"`
}
type ProductIngestionSourceProcessing struct {
	Contract                     string                           `json:"contract"`
	ModelCallCount               *int                             `json:"model_call_count"`
	RecordedModelCallCount       int                              `json:"recorded_model_call_count"`
	ReusedModelCallCount         *int                             `json:"reused_model_call_count"`
	RecordedReusedModelCallCount int                              `json:"recorded_reused_model_call_count"`
	ModelCallCountComplete       bool                             `json:"model_call_count_complete"`
	InterruptedCount             int                              `json:"interrupted_count"`
	Materials                    []ProductIngestionSourceMaterial `json:"materials"`
}
type ProductIngestionDiscoveryCounts struct {
	ProposedNew    *int `json:"proposed_new"`
	Duplicate      *int `json:"duplicate"`
	UpdateProposal *int `json:"update_proposal"`
	Rejected       *int `json:"rejected"`
	Published      *int `json:"published"`
}
type ProductIngestionDiscoveryCoverage struct {
	OfferedChars  int  `json:"offered_chars"`
	OmittedChars  int  `json:"omitted_chars"`
	Complete      bool `json:"complete"`
	MaterialCount int  `json:"material_count"`
}
type ProductIngestionDiscoverySummary struct {
	State              string                             `json:"state"`
	Reused             bool                               `json:"reused"`
	ReasonCodes        []string                           `json:"reason_codes"`
	Counts             ProductIngestionDiscoveryCounts    `json:"counts"`
	Coverage           *ProductIngestionDiscoveryCoverage `json:"coverage"`
	PublishedConfirmed bool                               `json:"published_confirmed"`
}
type productIngestionWireScope struct {
	TenantID            string `json:"tenant_id"`
	SpaceID             string `json:"space_id"`
	RawKnowledgeBaseID  string `json:"raw_knowledge_base_id"`
	WikiKnowledgeBaseID string `json:"wiki_knowledge_base_id"`
}
type ProductIngestionRun struct {
	Version                      int64                             `json:"version"`
	CanRetryProcessing           bool                              `json:"can_retry_processing"`
	RunID                        string                            `json:"run_id"`
	Scope                        productIngestionWireScope         `json:"scope"`
	WikiKnowledgeBaseID          string                            `json:"wiki_knowledge_base_id"`
	State                        string                            `json:"state"`
	Stage                        *string                           `json:"stage,omitempty"`
	Stages                       []ProductIngestionStage           `json:"stages,omitempty"`
	Counts                       *ProductIngestionCounts           `json:"counts,omitempty"`
	ModelCallCount               *int                              `json:"model_call_count"`
	SemanticModelCallCount       *int                              `json:"semantic_model_call_count"`
	ReusedModelCallCount         *int                              `json:"reused_model_call_count"`
	ReusedUsage                  map[string]int                    `json:"reused_usage"`
	SourceModelCallCount         *int                              `json:"source_model_call_count"`
	RecordedSourceModelCallCount *int                              `json:"recorded_source_model_call_count"`
	ModelCallCountComplete       *bool                             `json:"model_call_count_complete"`
	SourceProcessing             *ProductIngestionSourceProcessing `json:"source_processing"`
	DiscoverySummary             *ProductIngestionDiscoverySummary `json:"discovery_summary"`
	CreatedAt                    *string                           `json:"created_at,omitempty"`
	StartedAt                    *string                           `json:"started_at,omitempty"`
	FinishedAt                   *string                           `json:"finished_at,omitempty"`
	PublishedURL                 *string                           `json:"published_url,omitempty"`
	Reason                       *string                           `json:"reason,omitempty"`
	Fields                       []ProductIngestionField           `json:"fields,omitempty"`
	RetryOfRunID                 *string                           `json:"retry_of_run_id,omitempty"`
}
type ProductIngestionBridge interface {
	Scope() ProductIngestionScope
	MaxUploadFiles() int
	MaxUploadBytes() int64
	CreateRun(context.Context, int) (*ProductIngestionRun, error)
	ListRuns(context.Context) ([]ProductIngestionRun, error)
	GetRun(context.Context, string) (*ProductIngestionRun, error)
	RetryFields(context.Context, string, []string) (*ProductIngestionRun, error)
	RetryProcessing(context.Context, string, int64) (*ProductIngestionRun, error)
}

var ErrProductIngestionUnavailable = errors.New("PRODUCT_INGESTION_UNAVAILABLE")

// Only this code and a safe HTTP status escape the service boundary, never response bodies or URLs.
type ProductIngestionBridgeError struct{ StatusCode int }

func (e *ProductIngestionBridgeError) Error() string { return "PRODUCT_INGESTION_REQUEST_REJECTED" }

var productIngestionID = regexp.MustCompile(`^[A-Za-z0-9_-]{1,160}$`)

type productIngestionHTTPBridge struct {
	options  ProductIngestionBridgeOptions
	endpoint string
	client   *http.Client
}

func NewProductIngestionHTTPBridge(options ProductIngestionBridgeOptions) (ProductIngestionBridge, error) {
	u, err := url.Parse(options.BaseURL)
	if err != nil || u == nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Opaque != "" || strings.ContainsAny(options.Credential, " \t\r\n") || options.Credential == "" || options.Timeout <= 0 || options.MaxResponseBytes <= 0 || options.MaxResponseBytes == int64(^uint64(0)>>1) || options.MaxUploadFiles <= 0 || options.MaxUploadBytes <= 0 || options.Scope.TenantID == 0 || !productIngestionID.MatchString(options.Scope.SpaceID) || !productIngestionID.MatchString(options.Scope.RawKnowledgeBaseID) || !productIngestionID.MatchString(options.Scope.WikiKnowledgeBaseID) {
		return nil, errors.New("PRODUCT_INGESTION_CONFIGURATION_INVALID")
	}
	if u.Path != "" && u.Path != "/" && path.Clean(u.Path) != strings.TrimSuffix(u.Path, "/") {
		return nil, errors.New("PRODUCT_INGESTION_CONFIGURATION_INVALID")
	}
	return &productIngestionHTTPBridge{options: options, endpoint: strings.TrimRight(u.String(), "/") + "/product-ingestion/v1/spaces/" + url.PathEscape(options.Scope.SpaceID) + "/runs", client: &http.Client{Timeout: options.Timeout, Transport: options.Transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}, nil
}
func (b *productIngestionHTTPBridge) Scope() ProductIngestionScope { return b.options.Scope }
func (b *productIngestionHTTPBridge) MaxUploadFiles() int          { return b.options.MaxUploadFiles }
func (b *productIngestionHTTPBridge) MaxUploadBytes() int64        { return b.options.MaxUploadBytes }
func (b *productIngestionHTTPBridge) CreateRun(ctx context.Context, count int) (*ProductIngestionRun, error) {
	if count < 1 || count > b.options.MaxUploadFiles {
		return nil, &ProductIngestionBridgeError{StatusCode: 400}
	}
	return b.run(ctx, http.MethodPost, "", map[string]any{"idempotency_key": uuid.NewString(), "expected_upload_count": count})
}
func (b *productIngestionHTTPBridge) ListRuns(ctx context.Context) ([]ProductIngestionRun, error) {
	var data struct {
		Runs []ProductIngestionRun `json:"runs"`
	}
	if err := b.request(ctx, http.MethodGet, "", nil, &data); err != nil {
		return nil, err
	}
	if data.Runs == nil {
		return nil, ErrProductIngestionUnavailable
	}
	seen := map[string]bool{}
	for _, run := range data.Runs {
		if !b.validRun(run) || seen[run.RunID] {
			return nil, ErrProductIngestionUnavailable
		}
		seen[run.RunID] = true
	}
	return data.Runs, nil
}
func (b *productIngestionHTTPBridge) GetRun(ctx context.Context, id string) (*ProductIngestionRun, error) {
	if !productIngestionID.MatchString(id) {
		return nil, &ProductIngestionBridgeError{StatusCode: 400}
	}
	run, err := b.run(ctx, http.MethodGet, "/"+id, nil)
	if err == nil && run.RunID != id {
		return nil, ErrProductIngestionUnavailable
	}
	return run, err
}
func (b *productIngestionHTTPBridge) RetryFields(ctx context.Context, id string, keys []string) (*ProductIngestionRun, error) {
	if !productIngestionID.MatchString(id) || len(keys) == 0 {
		return nil, &ProductIngestionBridgeError{StatusCode: 400}
	}
	seen := map[string]bool{}
	for _, key := range keys {
		if key == "" || len(key) > 256 || strings.TrimSpace(key) != key || seen[key] {
			return nil, &ProductIngestionBridgeError{StatusCode: 400}
		}
		seen[key] = true
	}
	return b.run(ctx, http.MethodPost, "/"+id+"/retry-fields", map[string]any{"field_keys": keys})
}

func (b *productIngestionHTTPBridge) RetryProcessing(ctx context.Context, id string, version int64) (*ProductIngestionRun, error) {
	if !productIngestionID.MatchString(id) || version < 1 || version > 9007199254740991 {
		return nil, &ProductIngestionBridgeError{StatusCode: 400}
	}
	return b.run(ctx, http.MethodPost, "/"+id+"/retry-processing", map[string]any{"expected_version": version})
}

func (b *productIngestionHTTPBridge) run(ctx context.Context, method, suffix string, body any) (*ProductIngestionRun, error) {
	var run ProductIngestionRun
	if err := b.request(ctx, method, suffix, body, &run); err != nil {
		return nil, err
	}
	if !b.validRun(run) {
		return nil, ErrProductIngestionUnavailable
	}
	return &run, nil
}
func (b *productIngestionHTTPBridge) validRun(run ProductIngestionRun) bool {
	scope := b.options.Scope
	if !productIngestionID.MatchString(run.RunID) || run.WikiKnowledgeBaseID != scope.WikiKnowledgeBaseID || run.Scope != (productIngestionWireScope{TenantID: strconv.FormatUint(scope.TenantID, 10), SpaceID: scope.SpaceID, RawKnowledgeBaseID: scope.RawKnowledgeBaseID, WikiKnowledgeBaseID: scope.WikiKnowledgeBaseID}) {
		return false
	}
	switch run.State {
	case "created", "uploading", "accepting_uploads", "awaiting_sources", "waiting_sources", "processing", "running", "succeeded", "partial_success", "failed", "needs_confirmation":
	default:
		return false
	}
	for _, field := range run.Fields {
		if field.FieldKey == "" {
			return false
		}
		switch field.Outcome {
		case "verified", "not_provided", "extraction_failed":
		default:
			return false
		}
	}
	return true
}
func (b *productIngestionHTTPBridge) request(ctx context.Context, method, suffix string, body any, output any) error {
	encoded, err := json.Marshal(body)
	if err != nil {
		return ErrProductIngestionUnavailable
	}
	ctx, cancel := context.WithTimeout(ctx, b.options.Timeout)
	defer cancel()
	var reader io.Reader
	if body != nil {
		reader = bytes.NewReader(encoded)
	}
	request, err := http.NewRequestWithContext(ctx, method, b.endpoint+suffix, reader)
	if err != nil {
		return ErrProductIngestionUnavailable
	}
	request.Header.Set("Authorization", "Bearer "+b.options.Credential)
	request.Header.Set("Accept", "application/json")
	if body != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	response, err := b.client.Do(request)
	if err != nil {
		return ErrProductIngestionUnavailable
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		switch response.StatusCode {
		case 400, 403, 404, 409, 422:
			return &ProductIngestionBridgeError{StatusCode: response.StatusCode}
		default:
			return ErrProductIngestionUnavailable
		}
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, b.options.MaxResponseBytes+1))
	if err != nil || int64(len(data)) > b.options.MaxResponseBytes {
		return ErrProductIngestionUnavailable
	}
	var envelope struct {
		Success bool            `json:"success"`
		Data    json.RawMessage `json:"data"`
	}
	if json.Unmarshal(data, &envelope) != nil || !envelope.Success || len(envelope.Data) == 0 || bytes.Equal(envelope.Data, []byte("null")) || json.Unmarshal(envelope.Data, output) != nil {
		return ErrProductIngestionUnavailable
	}
	return nil
}
