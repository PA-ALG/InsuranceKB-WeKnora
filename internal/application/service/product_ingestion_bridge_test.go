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

func productBridgeSummaryRun(t *testing.T) map[string]any {
	t.Helper()
	var envelope map[string]any
	require.NoError(t, json.Unmarshal([]byte(productBridgeRun()), &envelope))
	run := envelope["data"].(map[string]any)
	var summaries map[string]any
	require.NoError(t, json.Unmarshal([]byte(`{
        "model_call_count": 0, "semantic_model_call_count": 0,
        "source_model_call_count": null, "recorded_source_model_call_count": 0,
        "model_call_count_complete": false,
        "source_processing": {
          "contract": "product-source-processing-summary.830.v1",
          "model_call_count": null, "recorded_model_call_count": 0,
          "reused_model_call_count": null, "recorded_reused_model_call_count": 0,
          "model_call_count_complete": false, "interrupted_count": 0,
          "raw": "PRIVATE_SOURCE_RESPONSE",
          "materials": [{"knowledge_id":"manual","file_name":null,"reused":false,
            "availability":"UNAVAILABLE","receipt_sha256":null,"counts":null,
            "raw":"PRIVATE_MATERIAL",
            "phases":[{"phase":"embedding","recorded":false,"raw":"PRIVATE_PHASE",
              "occurrences":[{"occurrence":0,"status":"failed","started_at_unix_ms":10,
                "finished_at_unix_ms":10,"duration_ms":0,"raw":"PRIVATE_OCCURRENCE"}]}]}]
        },
        "discovery_summary": {
          "state":"FAILED","reused":false,"reason_codes":["DISCOVERY_SUMMARY_INVALID"],
          "published_confirmed":false,"raw":"PRIVATE_DISCOVERY","call_ids":["PRIVATE_CALL"],
          "failure_detail":"PRIVATE_FAILURE","candidates":["PRIVATE_CANDIDATE"],
          "counts":{"proposed_new":null,"duplicate":0,"update_proposal":null,"rejected":0,
                    "published":0,"raw":"PRIVATE_COUNT"},
          "coverage":{"offered_chars":0,"omitted_chars":20,"complete":false,"material_count":1,
                      "sources":[{"quote":"PRIVATE_OMITTED"}]}
        }
      }`), &summaries))
	for key, value := range summaries {
		run[key] = value
	}
	return run
}

func TestProductIngestionBridgePreservesSafeSummariesOverHTTP(t *testing.T) {
	wireRun := productBridgeSummaryRun(t)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var data any = wireRun
		if r.URL.Path == "/product-ingestion/v1/spaces/space/runs" {
			data = map[string]any{"runs": []any{wireRun}}
		}
		require.NoError(t, json.NewEncoder(w).Encode(map[string]any{"success": true, "data": data}))
	}))
	defer server.Close()
	options := productBridgeOptions()
	options.BaseURL = server.URL
	bridge, err := NewProductIngestionHTTPBridge(options)
	require.NoError(t, err)
	one, err := bridge.GetRun(context.Background(), "run-1")
	require.NoError(t, err)
	listed, err := bridge.ListRuns(context.Background())
	require.NoError(t, err)
	require.Len(t, listed, 1)
	for _, run := range []ProductIngestionRun{*one, listed[0]} {
		encoded, err := json.Marshal(run)
		require.NoError(t, err)
		var got map[string]any
		require.NoError(t, json.Unmarshal(encoded, &got))
		for _, key := range []string{"model_call_count", "semantic_model_call_count", "source_model_call_count", "recorded_source_model_call_count", "model_call_count_complete"} {
			require.Contains(t, got, key, "bridge dropped status field")
			require.Equal(t, wireRun[key], got[key])
		}
		require.Contains(t, got, "source_processing")
		require.Contains(t, got, "discovery_summary")
		source := got["source_processing"].(map[string]any)
		require.Equal(t, false, source["model_call_count_complete"])
		require.Contains(t, source, "model_call_count")
		require.Nil(t, source["model_call_count"])
		material := source["materials"].([]any)[0].(map[string]any)
		require.Contains(t, material, "counts")
		require.Nil(t, material["counts"])
		require.Equal(t, false, material["reused"])
		phase := material["phases"].([]any)[0].(map[string]any)
		require.Equal(t, false, phase["recorded"])
		occurrence := phase["occurrences"].([]any)[0].(map[string]any)
		require.Equal(t, float64(0), occurrence["duration_ms"])
		discovery := got["discovery_summary"].(map[string]any)
		require.Equal(t, "FAILED", discovery["state"])
		require.Equal(t, false, discovery["published_confirmed"])
		counts := discovery["counts"].(map[string]any)
		require.Contains(t, counts, "proposed_new")
		require.Nil(t, counts["proposed_new"])
		require.Equal(t, float64(0), counts["published"])
		require.Equal(t, false, discovery["coverage"].(map[string]any)["complete"])
		require.NotContains(t, string(encoded), "PRIVATE_")
		require.NotContains(t, string(encoded), "SECRET_RAW")
		require.NotContains(t, string(encoded), "NEVER_RETURN")
	}
}

func TestProductIngestionBridgePreservesNullAndZeroDiscoveryCoverage(t *testing.T) {
	for _, coverage := range []any{nil, map[string]any{"offered_chars": 0, "omitted_chars": 0, "complete": true, "material_count": 0}} {
		run := productBridgeSummaryRun(t)
		run["discovery_summary"].(map[string]any)["coverage"] = coverage
		encoded, err := json.Marshal(map[string]any{"success": true, "data": run})
		require.NoError(t, err)
		options := productBridgeOptions()
		options.Transport = productBridgeTransport(func(r *http.Request) (*http.Response, error) {
			return bridgeResponse(r, 200, string(encoded)), nil
		})
		bridge, err := NewProductIngestionHTTPBridge(options)
		require.NoError(t, err)
		got, err := bridge.GetRun(context.Background(), "run-1")
		require.NoError(t, err)
		marshaled, err := json.Marshal(got)
		require.NoError(t, err)
		var output map[string]any
		require.NoError(t, json.Unmarshal(marshaled, &output))
		require.Contains(t, output, "discovery_summary")
		summary := output["discovery_summary"].(map[string]any)
		require.Contains(t, summary, "coverage")
		want, err := json.Marshal(coverage)
		require.NoError(t, err)
		actual, err := json.Marshal(summary["coverage"])
		require.NoError(t, err)
		require.JSONEq(t, string(want), string(actual))
	}
}
