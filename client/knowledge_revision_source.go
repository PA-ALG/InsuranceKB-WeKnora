package client

import (
	"context"
	"fmt"
	"net/http"
)

// KnowledgeRevisionSource is the safe operational receipt returned after the
// server seals one attempt-bound immutable PDF source. Storage handles and
// locators are intentionally absent.
type KnowledgeRevisionSource struct {
	Contract          string `json:"contract"`
	KnowledgeID       string `json:"knowledge_id"`
	ParseAttempt      int64  `json:"parse_attempt"`
	RevisionSourceID  string `json:"revision_source_id"`
	FileSHA256        string `json:"file_sha256"`
	ObjectSHA256      string `json:"object_sha256"`
	Size              int64  `json:"size"`
	MimeType          string `json:"mime_type"`
	PageCount         int    `json:"page_count"`
	ManifestAlgorithm string `json:"manifest_algorithm"`
	ManifestDigest    string `json:"manifest_digest"`
	ChunkCount        int    `json:"chunk_count"`
	BindingDigest     string `json:"binding_digest"`
	RetentionState    string `json:"retention_state"`
}

func (c *Client) BackfillKnowledgeRevisionSource(
	ctx context.Context,
	knowledgeID string,
	parseAttempt int64,
) (*KnowledgeRevisionSource, error) {
	if knowledgeID == "" || parseAttempt <= 0 {
		return nil, fmt.Errorf("knowledge id and positive parse attempt are required")
	}
	path := fmt.Sprintf(
		"/api/v1/knowledge/%s/revisions/%d/source/backfill", knowledgeID, parseAttempt,
	)
	response, err := c.doRequest(ctx, http.MethodPost, path, nil, nil)
	if err != nil {
		return nil, err
	}
	var envelope struct {
		Success bool                    `json:"success"`
		Data    KnowledgeRevisionSource `json:"data"`
	}
	if err := parseResponse(response, &envelope); err != nil {
		return nil, err
	}
	if !envelope.Success {
		return nil, fmt.Errorf("revision source backfill failed")
	}
	return &envelope.Data, nil
}
