package client

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestBackfillKnowledgeRevisionSourceUsesExactAttemptRoute(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Fatalf("method = %s", r.Method)
		}
		if r.URL.Path != "/api/v1/knowledge/knowledge-1/revisions/2/source/backfill" {
			t.Fatalf("path = %s", r.URL.Path)
		}
		if r.ContentLength > 0 {
			t.Fatalf("backfill request body must be empty")
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"success": true,
			"data": map[string]any{
				"contract":     "knowledge-revision-source.v1",
				"knowledge_id": "knowledge-1", "parse_attempt": 2,
				"revision_source_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
				"file_sha256":        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
				"object_sha256":      "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
				"size":               4096, "mime_type": "application/pdf", "page_count": 39,
				"manifest_algorithm": "weknora.chunk_manifest.v1",
				"manifest_digest":    "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
				"chunk_count":        162,
				"binding_digest":     "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
				"retention_state":    "pinned",
			},
		})
	}))
	defer server.Close()

	cli := NewClient(server.URL, WithAPIKey("test-only"))
	source, err := cli.BackfillKnowledgeRevisionSource(context.Background(), "knowledge-1", 2)
	if err != nil {
		t.Fatal(err)
	}
	if source.KnowledgeID != "knowledge-1" || source.ParseAttempt != 2 || source.PageCount != 39 {
		t.Fatalf("unexpected source: %+v", source)
	}
}
