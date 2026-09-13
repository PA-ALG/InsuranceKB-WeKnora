package service

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

type productBridgeTransport func(*http.Request) (*http.Response, error)

func (f productBridgeTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func productBridgeOptions() ProductIngestionBridgeOptions {
	return ProductIngestionBridgeOptions{BaseURL: "https://harness.internal", Credential: "private-service-key", Scope: ProductIngestionScope{TenantID: 1, SpaceID: "space", RawKnowledgeBaseID: "raw", WikiKnowledgeBaseID: "wiki"}, Timeout: time.Second, MaxResponseBytes: 8192, MaxUploadFiles: 10, MaxUploadBytes: 1024 * 1024}
}
func productBridgeRun() string {
	return `{"success":true,"data":{"run_id":"run-1","state":"running","wiki_knowledge_base_id":"wiki","scope":{"tenant_id":"1","space_id":"space","raw_knowledge_base_id":"raw","wiki_knowledge_base_id":"wiki"},"counts":{"success_count":0},"fields":[{"field_key":"a","outcome":"extraction_failed","reason":"INVALID_EVIDENCE","value":"NEVER_RETURN","raw_ref":"SECRET_RAW"}],"raw":"SECRET_RAW"}}`
}
func bridgeResponse(r *http.Request, status int, body string) *http.Response {
	w := httptest.NewRecorder()
	w.WriteHeader(status)
	_, _ = w.WriteString(body)
	response := w.Result()
	response.Request = r
	return response
}
func TestProductIngestionBridgeFixedScopeCredentialAndSafeProjection(t *testing.T) {
	options := productBridgeOptions()
	calls := 0
	options.Transport = productBridgeTransport(func(r *http.Request) (*http.Response, error) {
		calls++
		require.Equal(t, "harness.internal", r.URL.Host)
		require.Equal(t, "/product-ingestion/v1/spaces/space/runs", r.URL.Path)
		require.Equal(t, "Bearer private-service-key", r.Header.Get("Authorization"))
		var body map[string]any
		require.NoError(t, json.NewDecoder(r.Body).Decode(&body))
		require.Len(t, body, 2)
		require.Equal(t, float64(3), body["expected_upload_count"])
		require.NotEmpty(t, body["idempotency_key"])
		return bridgeResponse(r, 201, productBridgeRun()), nil
	})
	bridge, err := NewProductIngestionHTTPBridge(options)
	require.NoError(t, err)
	run, err := bridge.CreateRun(context.Background(), 3)
	require.NoError(t, err)
	require.Equal(t, "run-1", run.RunID)
	require.Equal(t, 1, calls)
	wire, err := json.Marshal(run)
	require.NoError(t, err)
	require.NotContains(t, string(wire), "NEVER_RETURN")
	require.NotContains(t, string(wire), "SECRET_RAW")
}
func TestProductIngestionBridgeRejectsRedirectAndSanitizesFailure(t *testing.T) {
	options := productBridgeOptions()
	calls := 0
	options.Transport = productBridgeTransport(func(r *http.Request) (*http.Response, error) {
		calls++
		response := bridgeResponse(r, 302, "private-service-key SECRET_BODY")
		response.Header.Set("Location", "https://evil.invalid/steal")
		return response, nil
	})
	bridge, err := NewProductIngestionHTTPBridge(options)
	require.NoError(t, err)
	_, err = bridge.GetRun(context.Background(), "run-1")
	require.Error(t, err)
	require.Equal(t, 1, calls)
	require.NotContains(t, err.Error(), "private-service-key")
	require.NotContains(t, err.Error(), "SECRET_BODY")
}
func TestProductIngestionBridgeRejectsOversizedAndForeignScope(t *testing.T) {
	for _, body := range []string{strings.Repeat("x", 9000), strings.Replace(productBridgeRun(), `"tenant_id":"1"`, `"tenant_id":"2"`, 1)} {
		options := productBridgeOptions()
		options.Transport = productBridgeTransport(func(r *http.Request) (*http.Response, error) { return bridgeResponse(r, 200, body), nil })
		bridge, err := NewProductIngestionHTTPBridge(options)
		require.NoError(t, err)
		_, err = bridge.GetRun(context.Background(), "run-1")
		require.Error(t, err)
	}
}
func TestProductIngestionBridgeRejectsUnsafeConfigurationAndRunPath(t *testing.T) {
	for _, endpoint := range []string{"https://user:password@harness.internal", "https://harness.internal?secret=x", "file:///private/tmp/x"} {
		options := productBridgeOptions()
		options.BaseURL = endpoint
		_, err := NewProductIngestionHTTPBridge(options)
		require.Error(t, err)
		require.NotContains(t, err.Error(), "password")
	}
	options := productBridgeOptions()
	calls := 0
	options.Transport = productBridgeTransport(func(r *http.Request) (*http.Response, error) {
		calls++
		return bridgeResponse(r, 200, productBridgeRun()), nil
	})
	bridge, err := NewProductIngestionHTTPBridge(options)
	require.NoError(t, err)
	_, err = bridge.GetRun(context.Background(), "../other")
	require.Error(t, err)
	require.Zero(t, calls)
}
func TestProductIngestionBridgeReadAndRetryAreSingleBoundedCalls(t *testing.T) {
	options := productBridgeOptions()
	calls := 0
	options.Transport = productBridgeTransport(func(r *http.Request) (*http.Response, error) {
		calls++
		require.NotNil(t, r.Context().Done())
		if r.Method == http.MethodPost {
			body, _ := io.ReadAll(r.Body)
			require.JSONEq(t, `{"field_keys":["premium"]}`, string(body))
			require.True(t, strings.HasSuffix(r.URL.Path, "/retry-fields"))
		}
		if calls == 1 {
			run := strings.TrimSuffix(strings.TrimPrefix(productBridgeRun(), `{"success":true,"data":`), "}")
			return bridgeResponse(r, 200, `{"success":true,"data":{"runs":[`+run+`]}}`), nil
		}
		return bridgeResponse(r, 200, productBridgeRun()), nil
	})
	bridge, err := NewProductIngestionHTTPBridge(options)
	require.NoError(t, err)
	runs, err := bridge.ListRuns(context.Background())
	require.NoError(t, err)
	require.Len(t, runs, 1)
	_, err = bridge.RetryFields(context.Background(), "run-1", []string{"premium"})
	require.NoError(t, err)
	require.Equal(t, 2, calls)
}

func TestProductIngestionBridgeAcceptsCanonicalTrailingSlash(t *testing.T) {
	options := productBridgeOptions()
	options.BaseURL += "/"
	_, err := NewProductIngestionHTTPBridge(options)
	require.NoError(t, err)
}

func TestProductIngestionBridgeTimeoutIsBoundedAndDoesNotLeakTransportDetails(t *testing.T) {
	options := productBridgeOptions()
	options.Timeout = 20 * time.Millisecond
	options.Transport = productBridgeTransport(func(r *http.Request) (*http.Response, error) {
		<-r.Context().Done()
		return nil, fmt.Errorf("private-service-key transport: %w", r.Context().Err())
	})
	bridge, err := NewProductIngestionHTTPBridge(options)
	require.NoError(t, err)
	started := time.Now()
	_, err = bridge.GetRun(context.Background(), "run-1")
	require.Error(t, err)
	require.Less(t, time.Since(started), time.Second)
	require.NotContains(t, err.Error(), "private-service-key")
}
