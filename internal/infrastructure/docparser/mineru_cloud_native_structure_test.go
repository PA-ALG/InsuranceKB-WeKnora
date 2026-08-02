package docparser

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
)

func TestMinerUCloudPollingIsBoundedAndTransportFailFast(t *testing.T) {
	t.Parallel()
	t.Run("transport-error-is-not-retried", func(t *testing.T) {
		calls := 0
		reader := &MinerUCloudReader{
			apiKey: "synthetic", capturePolicy: true,
			fetchStatus: func(context.Context, string, map[string]string) ([]extractResultItem, error) {
				calls++
				return nil, errors.New("synthetic transport failure")
			},
			sleep: func(context.Context, time.Duration) {},
		}
		_, _, _, err := reader.pollBatchResult(context.Background(), "batch", strings.Repeat("f", 64), "pipeline")
		if err == nil || calls != 1 {
			t.Fatalf("transport failure was retried: calls=%d err=%v", calls, err)
		}
	})

	t.Run("nonterminal-status-stops-at-exact-cap", func(t *testing.T) {
		calls := 0
		reader := &MinerUCloudReader{
			apiKey: "synthetic", capturePolicy: true,
			fetchStatus: func(context.Context, string, map[string]string) ([]extractResultItem, error) {
				calls++
				return []extractResultItem{{State: "running"}}, nil
			},
			sleep: func(context.Context, time.Duration) {},
		}
		_, _, _, err := reader.pollBatchResult(context.Background(), "batch", strings.Repeat("f", 64), "pipeline")
		if !errors.Is(err, ErrMinerUCloudPollBudgetExceeded) || calls != maxMinerUStatusPolls {
			t.Fatalf("poll cap drifted: calls=%d err=%v", calls, err)
		}
	})

	t.Run("done-downloads-one-zip", func(t *testing.T) {
		zipCalls := 0
		reader := &MinerUCloudReader{
			apiKey: "synthetic", capturePolicy: true,
			fetchStatus: func(context.Context, string, map[string]string) ([]extractResultItem, error) {
				return []extractResultItem{{State: "done", FullZipURL: "https://example.invalid/result.zip"}}, nil
			},
			extractDone: func(context.Context, *extractResultItem, string, string) (string, []types.ImageRef, *types.NativeStructureArtifact, error) {
				zipCalls++
				return "", nil, &types.NativeStructureArtifact{}, nil
			},
			sleep: func(context.Context, time.Duration) {},
		}
		_, _, _, err := reader.pollBatchResult(context.Background(), "batch", strings.Repeat("f", 64), "pipeline")
		if err != nil || zipCalls != 1 {
			t.Fatalf("ZIP budget drifted: calls=%d err=%v", zipCalls, err)
		}
	})

	if minerUCaptureTimeout >= 10*time.Minute {
		t.Fatalf("capture deadline must stay below ten minutes: %s", minerUCaptureTimeout)
	}
}

func TestMinerUCloudRedirectPolicyIsCaptureLocal(t *testing.T) {
	t.Parallel()
	ordinary := NewMinerUCloudReader(map[string]string{"mineru_api_key": "synthetic"})
	if ordinary.redirectLimit() != 5 {
		t.Fatalf("ordinary redirect compatibility changed: %d", ordinary.redirectLimit())
	}
	capture, ok := newMinerUArtifactCaptureReader(map[string]string{"mineru_api_key": "synthetic"}).(*MinerUCloudReader)
	if !ok {
		t.Fatal("capture factory did not retain the concrete MinerU reader")
	}
	if capture.redirectLimit() != 0 {
		t.Fatalf("capture redirects are not fail-closed: %d", capture.redirectLimit())
	}
}

func TestMinerUArtifactCaptureDeadlineCancelsBlockedZIP(t *testing.T) {
	t.Parallel()
	reader, ok := newMinerUArtifactCaptureReader(map[string]string{"mineru_api_key": "synthetic"}).(*MinerUCloudReader)
	if !ok {
		t.Fatal("capture factory did not retain the concrete MinerU reader")
	}
	if reader.captureTimeout != 9*time.Minute+30*time.Second {
		t.Fatalf("capture policy timeout drifted: %s", reader.captureTimeout)
	}
	reader.captureTimeout = 25 * time.Millisecond
	reader.fetchStatus = func(context.Context, string, map[string]string) ([]extractResultItem, error) {
		return []extractResultItem{{State: "done", FullZipURL: "https://capture.invalid/blocked.zip"}}, nil
	}
	reader.zipURLValidator = func(rawURL string) error {
		if rawURL != "https://capture.invalid/blocked.zip" {
			t.Fatalf("unexpected ZIP URL: %s", rawURL)
		}
		return nil
	}
	zipRequests := 0
	reader.newZIPHTTPClient = func(maxRedirects int) *http.Client {
		if maxRedirects != 0 {
			t.Fatalf("capture ZIP client accepted redirects: %d", maxRedirects)
		}
		return &http.Client{Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
			zipRequests++
			<-req.Context().Done()
			return nil, req.Context().Err()
		})}
	}
	ctx, cancel := reader.operationContext(context.Background())
	defer cancel()
	started := time.Now()
	_, _, _, err := reader.pollBatchResult(ctx, "batch", strings.Repeat("f", 64), "pipeline")
	if !errors.Is(err, context.DeadlineExceeded) || zipRequests != 1 || time.Since(started) > time.Second {
		t.Fatalf("real blocked ZIP request did not inherit capture deadline: requests=%d elapsed=%s err=%v", zipRequests, time.Since(started), err)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) { return f(req) }

func TestMinerUCloudOrdinaryReaderPreservesLegacyPolling(t *testing.T) {
	t.Parallel()
	if defaultCloudTimeout != 600*time.Second {
		t.Fatalf("ordinary cloud timeout changed: %s", defaultCloudTimeout)
	}

	t.Run("transport-error-remains-retryable", func(t *testing.T) {
		calls := 0
		reader := &MinerUCloudReader{
			apiKey: "synthetic",
			fetchStatus: func(context.Context, string, map[string]string) ([]extractResultItem, error) {
				calls++
				if calls == 1 {
					return nil, errors.New("transient transport failure")
				}
				return []extractResultItem{{State: "failed", ErrMsg: "terminal"}}, nil
			},
			sleep: func(context.Context, time.Duration) {},
		}
		_, _, _, err := reader.pollBatchResult(context.Background(), "batch", strings.Repeat("f", 64), "pipeline")
		if err == nil || calls != 2 || errors.Is(err, ErrMinerUCloudPollBudgetExceeded) {
			t.Fatalf("ordinary transient poll behavior changed: calls=%d err=%v", calls, err)
		}
	})

	t.Run("ordinary-reader-is-not-capped-at-twenty", func(t *testing.T) {
		calls := 0
		reader := &MinerUCloudReader{
			apiKey: "synthetic",
			fetchStatus: func(context.Context, string, map[string]string) ([]extractResultItem, error) {
				calls++
				if calls <= maxMinerUStatusPolls {
					return []extractResultItem{{State: "running"}}, nil
				}
				return []extractResultItem{{State: "failed", ErrMsg: "terminal"}}, nil
			},
			sleep: func(context.Context, time.Duration) {},
		}
		_, _, _, err := reader.pollBatchResult(context.Background(), "batch", strings.Repeat("f", 64), "pipeline")
		if err == nil || calls != maxMinerUStatusPolls+1 || errors.Is(err, ErrMinerUCloudPollBudgetExceeded) {
			t.Fatalf("ordinary polling inherited capture cap: calls=%d err=%v", calls, err)
		}
	})
}

type nativeStructureFixture struct {
	Contract     string `json:"contract"`
	SourceSchema string `json:"source_schema"`
	SourceSHA256 string `json:"source_sha256"`
	RawSHA256    string `json:"raw_sha256"`
	Pages        []struct {
		PageID string `json:"page_id"`
	} `json:"pages"`
	Blocks []struct {
		BlockID string   `json:"block_id"`
		BBox    []string `json:"bbox"`
	} `json:"blocks"`
	Tables []struct {
		TableID     string `json:"table_id"`
		RowCount    int    `json:"row_count"`
		ColumnCount int    `json:"column_count"`
	} `json:"tables"`
	Cells []struct {
		CellID      string   `json:"cell_id"`
		RowIndex    int      `json:"row_index"`
		ColumnIndex int      `json:"column_index"`
		RowSpan     int      `json:"row_span"`
		ColumnSpan  int      `json:"column_span"`
		BBox        []string `json:"bbox"`
	} `json:"cells"`
	Unsupported []string `json:"unsupported"`
}

func minerUFixtureZip(t *testing.T, entries map[string][]byte) []byte {
	t.Helper()
	var payload bytes.Buffer
	writer := zip.NewWriter(&payload)
	for name, body := range entries {
		entry, err := writer.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := entry.Write(body); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	return payload.Bytes()
}

func TestExtractMinerUZipRetainsSanitizedNativeStructure(t *testing.T) {
	raw, err := os.ReadFile("testdata/mineru_content_list_pipeline_v1.json")
	if err != nil {
		t.Fatal(err)
	}
	zipBytes := minerUFixtureZip(t, map[string][]byte{
		"result/document.md":                []byte("synthetic presentation"),
		"result/document_content_list.json": raw,
	})

	sourceSHA256 := strings.Repeat("f", 64)
	markdown, images, artifact, err := extractMinerUZipBytes(zipBytes, sourceSHA256, "pipeline")
	if err != nil {
		t.Fatalf("extract native structure: %v", err)
	}
	if markdown != "synthetic presentation" || len(images) != 0 {
		t.Fatalf("presentation output changed: markdown=%q images=%d", markdown, len(images))
	}
	if artifact == nil || artifact.SchemaVersion != "mineru-native-structure.v1" {
		t.Fatalf("native artifact missing or wrong schema: %#v", artifact)
	}
	if artifact.SourceSHA256 != sourceSHA256 {
		t.Fatalf("source identity mismatch: %s", artifact.SourceSHA256)
	}
	wantRawHash := sha256.Sum256(raw)
	if artifact.RawSHA256 != hex.EncodeToString(wantRawHash[:]) {
		t.Fatalf("raw hash mismatch: %s", artifact.RawSHA256)
	}
	wantSanitizedHash := sha256.Sum256(artifact.SanitizedJSON)
	if artifact.SanitizedSHA256 != hex.EncodeToString(wantSanitizedHash[:]) {
		t.Fatalf("sanitized hash mismatch: %s", artifact.SanitizedSHA256)
	}
	if strings.Contains(string(artifact.SanitizedJSON), "synthetic heading value") ||
		strings.Contains(string(artifact.SanitizedJSON), "synthetic header") ||
		strings.Contains(string(artifact.SanitizedJSON), "table_body") {
		t.Fatal("sanitized artifact leaked native content")
	}

	var decoded nativeStructureFixture
	if err := json.Unmarshal(artifact.SanitizedJSON, &decoded); err != nil {
		t.Fatalf("decode sanitized artifact: %v", err)
	}
	if decoded.Contract != "mineru-native-structure.v1" ||
		decoded.SourceSchema != "mineru.content-list.pipeline.v1" ||
		decoded.RawSHA256 != artifact.RawSHA256 || decoded.SourceSHA256 != sourceSHA256 {
		t.Fatalf("identity drift: %#v", decoded)
	}
	if len(decoded.Pages) != 1 || len(decoded.Blocks) != 2 ||
		len(decoded.Tables) != 1 || len(decoded.Cells) != 4 {
		t.Fatalf("structure counts are incomplete: %#v", decoded)
	}
	if decoded.Tables[0].RowCount != 2 || decoded.Tables[0].ColumnCount != 3 {
		t.Fatalf("table grid mismatch: %#v", decoded.Tables[0])
	}
	if decoded.Cells[0].RowSpan != 2 || decoded.Cells[1].ColumnSpan != 2 {
		t.Fatalf("native spans were not retained: %#v", decoded.Cells)
	}
	for _, cell := range decoded.Cells {
		if cell.CellID == "" || len(cell.BBox) != 4 {
			t.Fatalf("cell locator is incomplete: %#v", cell)
		}
	}
}

func TestExtractMinerUZipRejectsMarkdownOnlyAndUntrustedNativeStructure(t *testing.T) {
	tests := map[string]map[string][]byte{
		"markdown-only": {
			"result/document.md": []byte("presentation only"),
		},
		"duplicate-native": {
			"a_content_list.json": []byte(`[]`),
			"b_content_list.json": []byte(`[]`),
		},
		"trailing-json": {
			"result/document.md":                []byte("presentation"),
			"result/document_content_list.json": []byte(`[{"type":"text","text":"safe","page_idx":0,"bbox":[0,0,1,1]}] {"smuggled":"value"}`),
		},
		"unknown-vendor-field": {
			"result/document.md":                []byte("presentation"),
			"result/document_content_list.json": []byte(`[{"type":"text","text":"safe","page_idx":0,"bbox":[0,0,1,1],"vendor_secret":"must-not-pass"}]`),
		},
	}
	for name, entries := range tests {
		t.Run(name, func(t *testing.T) {
			_, _, artifact, err := extractMinerUZipBytes(minerUFixtureZip(t, entries), strings.Repeat("f", 64), "pipeline")
			if err == nil || artifact != nil || !errors.Is(err, ErrMinerUNativeStructureUnavailable) {
				t.Fatalf("unsafe native ZIP was accepted: artifact=%#v err=%v", artifact, err)
			}
		})
	}
}

func TestExtractMinerUZipRetainsInvalidBBoxOnlyAsBlockingObservation(t *testing.T) {
	raw := []byte(`[{"type":"text","text":"safe","page_idx":0,"bbox":[-1,0,1001,1]}]`)
	zipBytes := minerUFixtureZip(t, map[string][]byte{
		"result/document.md":                []byte("synthetic presentation"),
		"result/document_content_list.json": raw,
	})

	_, _, artifact, err := extractMinerUZipBytes(zipBytes, strings.Repeat("f", 64), "pipeline")
	if err != nil {
		t.Fatalf("invalid bbox observation was discarded: %v", err)
	}
	if artifact == nil {
		t.Fatal("invalid bbox observation did not retain a sanitized sidecar")
	}
	var decoded nativeStructureFixture
	if err := json.Unmarshal(artifact.SanitizedJSON, &decoded); err != nil {
		t.Fatal(err)
	}
	if len(decoded.Pages) != 1 || len(decoded.Blocks) != 0 || len(decoded.Tables) != 0 || len(decoded.Cells) != 0 {
		t.Fatalf("invalid locator was published: %#v", decoded)
	}
	if !containsString(decoded.Unsupported, "native_structure_invalid") {
		t.Fatalf("blocking native-structure observation is missing: %#v", decoded.Unsupported)
	}
}

func TestExtractMinerUZipRejectsNonPipelineEffectiveModel(t *testing.T) {
	raw, err := os.ReadFile("testdata/mineru_content_list_pipeline_v1.json")
	if err != nil {
		t.Fatal(err)
	}
	zipBytes := minerUFixtureZip(t, map[string][]byte{
		"result/document.md":                []byte("synthetic presentation"),
		"result/document_content_list.json": raw,
	})
	for _, model := range []string{"vlm", "MinerU-HTML"} {
		t.Run(model, func(t *testing.T) {
			_, _, artifact, err := extractMinerUZipBytes(zipBytes, strings.Repeat("f", 64), model)
			if err == nil || artifact != nil || !errors.Is(err, ErrMinerUNativeStructureUnavailable) {
				t.Fatalf("non-pipeline artifact was trusted: artifact=%#v err=%v", artifact, err)
			}
		})
	}
}

func TestMinerUReadRejectsNonPipelineModelBeforeProviderIO(t *testing.T) {
	tests := []struct {
		name, model, fileName string
	}{
		{"vlm", "vlm", "document.pdf"},
		{"html-override", "pipeline", "document.html"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			reader := &MinerUCloudReader{apiKey: "synthetic", model: tc.model}
			result, err := reader.Read(context.Background(), &types.ReadRequest{
				FileContent: []byte("synthetic"),
				FileName:    tc.fileName,
			})
			if err == nil || result != nil || !errors.Is(err, ErrMinerUNativeStructureUnavailable) {
				t.Fatalf("non-pipeline production read was not rejected: result=%#v err=%v", result, err)
			}
		})
	}
}

func TestNormalizeMinerUMalformedTableIsRetainedOnlyAsUnsupportedStructure(t *testing.T) {
	malformedBodies := []struct{ name, body string }{
		{"unclosed", `<table><tr><td>unclosed</tr></table>`},
		{"unclosed-nested-formatting", `<table><tr><td><b>A</td></tr></table>`},
		{"self-closing-nonvoid", `<table><tr><td><b/>A</td></tr></table>`},
		{"td-closed-as-th", `<table><tr><td>mismatch</th></tr></table>`},
		{"th-closed-as-td", `<table><tr><th>mismatch</td></tr></table>`},
		{"duplicate-span", `<table><tr><td rowspan="1" rowspan="2">duplicate</td></tr></table>`},
		{"incomplete-grid", `<table><tr><td>A</td></tr><tr><td colspan="2">B</td></tr></table>`},
	}
	for _, tc := range malformedBodies {
		t.Run(tc.name, func(t *testing.T) {
			raw, err := json.Marshal([]map[string]any{{
				"type":       "table",
				"page_idx":   0,
				"bbox":       []int{0, 0, 100, 100},
				"table_body": tc.body,
			}})
			if err != nil {
				t.Fatal(err)
			}
			artifact, err := normalizeMinerUContentList(raw, strings.Repeat("f", 64), "pipeline")
			if err != nil {
				t.Fatalf("malformed grid should produce a reviewable sidecar: %v", err)
			}
			var decoded nativeStructureFixture
			if err := json.Unmarshal(artifact.SanitizedJSON, &decoded); err != nil {
				t.Fatal(err)
			}
			if len(decoded.Tables) != 0 || len(decoded.Cells) != 0 {
				t.Fatalf("unproven table structure was published: %#v", decoded)
			}
			var payload map[string]any
			if err := json.Unmarshal(artifact.SanitizedJSON, &payload); err != nil {
				t.Fatal(err)
			}
			unsupported, ok := payload["unsupported"].([]any)
			if !ok || len(unsupported) < 3 {
				t.Fatalf("missing conservative unsupported facts: %#v", payload["unsupported"])
			}
		})
	}
}

func TestNormalizeMinerURejectsNullAndWrongTypedOfficialFields(t *testing.T) {
	tests := map[string]string{
		"image-null-img-path":       `{"type":"image","img_path":null,"page_idx":0,"bbox":[0,0,1,1]}`,
		"image-wrong-img-path":      `{"type":"image","img_path":[],"page_idx":0,"bbox":[0,0,1,1]}`,
		"list-null-items":           `{"type":"list","list_items":null,"page_idx":0,"bbox":[0,0,1,1]}`,
		"list-wrong-item-type":      `{"type":"list","list_items":[1],"page_idx":0,"bbox":[0,0,1,1]}`,
		"equation-null-text":        `{"type":"equation","text":null,"text_format":"latex","page_idx":0,"bbox":[0,0,1,1]}`,
		"equation-null-text-format": `{"type":"equation","text":"x","text_format":null,"page_idx":0,"bbox":[0,0,1,1]}`,
		"table-null-body":           `{"type":"table","table_body":null,"page_idx":0,"bbox":[0,0,1,1]}`,
		"text-null-body":            `{"type":"text","text":null,"page_idx":0,"bbox":[0,0,1,1]}`,
		"code-null-body":            `{"type":"code","code_body":null,"page_idx":0,"bbox":[0,0,1,1]}`,
		"null-page-index":           `{"type":"text","text":"x","page_idx":null,"bbox":[0,0,1,1]}`,
		"fractional-page-index":     `{"type":"text","text":"x","page_idx":0.5,"bbox":[0,0,1,1]}`,
		"null-bbox":                 `{"type":"text","text":"x","page_idx":0,"bbox":null}`,
		"wrong-bbox-coordinate":     `{"type":"text","text":"x","page_idx":0,"bbox":[0,0,"1",1]}`,
		"optional-null-text-level":  `{"type":"text","text":"x","text_level":null,"page_idx":0,"bbox":[0,0,1,1]}`,
		"optional-null-caption":     `{"type":"image","img_path":"image.png","image_caption":null,"page_idx":0,"bbox":[0,0,1,1]}`,
	}
	for name, item := range tests {
		t.Run(name, func(t *testing.T) {
			raw := []byte("[" + item + "]")
			if _, err := normalizeMinerUContentList(raw, strings.Repeat("f", 64), "pipeline"); err == nil {
				t.Fatal("null or wrong typed official field was accepted")
			}
		})
	}
}

func TestNormalizeMinerUAcceptsWellFormedNestedTableMarkup(t *testing.T) {
	raw := []byte(`[{"type":"table","page_idx":0,"bbox":[0,0,100,100],"table_body":"<table><tr><td><b>A</b><br/></td></tr></table>"}]`)
	artifact, err := normalizeMinerUContentList(raw, strings.Repeat("f", 64), "pipeline")
	if err != nil {
		t.Fatalf("well-formed nested markup was rejected: %v", err)
	}
	var decoded nativeStructureFixture
	if err := json.Unmarshal(artifact.SanitizedJSON, &decoded); err != nil {
		t.Fatal(err)
	}
	if len(decoded.Tables) != 1 || len(decoded.Cells) != 1 {
		t.Fatalf("well-formed native table was not retained: %#v", decoded)
	}
}

func TestNormalizeMinerUAcceptsOnlyOfficialContentListTypes(t *testing.T) {
	for _, itemType := range []string{"title", "interline_equation", "display_equation"} {
		raw := []byte(`[{"type":"` + itemType + `","text":"value","page_idx":0,"bbox":[0,0,1,1]}]`)
		if _, err := normalizeMinerUContentList(raw, strings.Repeat("f", 64), "pipeline"); err == nil {
			t.Fatalf("non-official content-list type %q was accepted", itemType)
		}
	}
	crossType := []byte(`[{"type":"text","text":"safe","table_body":"<table><tr><td>hidden</td></tr></table>","page_idx":0,"bbox":[0,0,1,1]}]`)
	if _, err := normalizeMinerUContentList(crossType, strings.Repeat("f", 64), "pipeline"); err == nil {
		t.Fatal("a field from another official type was accepted")
	}
}

func TestNormalizeMinerUAcceptsDocumentedPipelineContentListTypes(t *testing.T) {
	items := []map[string]any{
		{"type": "text", "text": "text", "text_level": 1},
		{"type": "header", "text": "header"},
		{"type": "footer", "text": "footer"},
		{"type": "page_number", "text": "1"},
		{"type": "aside_text", "text": "aside"},
		{"type": "page_footnote", "text": "footnote"},
		{"type": "equation", "text": "x", "text_format": "latex", "img_path": "equation.png"},
		{"type": "image", "sub_type": "image", "img_path": "image.png", "image_caption": []string{"caption"}, "image_footnote": []string{}},
		{"type": "chart", "sub_type": "chart", "img_path": "chart.png", "content": "chart", "chart_caption": []string{}, "chart_footnote": []string{}},
		{"type": "code", "sub_type": "python", "code_body": "pass", "code_caption": []string{}, "code_footnote": []string{}},
		{"type": "list", "sub_type": "unordered", "list_items": []string{"item"}},
	}
	for index := range items {
		items[index]["page_idx"] = 0
		items[index]["bbox"] = []int{index, index, index + 1, index + 1}
	}
	raw, err := json.Marshal(items)
	if err != nil {
		t.Fatal(err)
	}
	artifact, err := normalizeMinerUContentList(raw, strings.Repeat("f", 64), "pipeline")
	if err != nil {
		t.Fatalf("documented content-list type was rejected: %v", err)
	}
	var decoded nativeStructureFixture
	if err := json.Unmarshal(artifact.SanitizedJSON, &decoded); err != nil {
		t.Fatal(err)
	}
	if len(decoded.Blocks) != len(items) {
		t.Fatalf("documented content-list blocks were lost: got=%d want=%d", len(decoded.Blocks), len(items))
	}
}
