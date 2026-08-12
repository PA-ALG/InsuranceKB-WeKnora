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

const KnowledgeRevisionSourceExact3ContractV1 = "knowledge-revision-source-exact3-backfill.v1"

type KnowledgeRevisionSourceExact3ItemV1 struct {
	Role                   string `json:"role"`
	KnowledgeID            string `json:"knowledge_id"`
	ParseAttempt           int64  `json:"parse_attempt"`
	ExpectedFileSHA256     string `json:"expected_file_sha256"`
	ExpectedManifestDigest string `json:"expected_manifest_digest"`
}

type KnowledgeRevisionSourceExact3RequestV1 struct {
	Contract string                                `json:"contract"`
	DryRun   bool                                  `json:"dry_run"`
	Sources  []KnowledgeRevisionSourceExact3ItemV1 `json:"sources"`
}

type KnowledgeRevisionSourceExact3ReceiptV1 struct {
	Role         string `json:"role"`
	PlanCode     string `json:"plan_code"`
	SourceSHA256 string `json:"source_sha256"`
	ResultSHA256 string `json:"result_sha256"`
}

type KnowledgeRevisionSourceExact3ResultV1 struct {
	Contract          string                                   `json:"contract"`
	DryRun            bool                                     `json:"dry_run"`
	SnapshotIsolation string                                   `json:"snapshot_isolation"`
	SnapshotReadOnly  bool                                     `json:"snapshot_read_only"`
	SnapshotSHA256    string                                   `json:"snapshot_sha256"`
	ValidatedRoles    []string                                 `json:"validated_roles"`
	PlannedRows       int                                      `json:"planned_rows"`
	DuplicateRows     int                                      `json:"duplicate_rows"`
	ConflictRows      int                                      `json:"conflict_rows"`
	Writes            int                                      `json:"writes"`
	Sources           []KnowledgeRevisionSourceExact3ReceiptV1 `json:"sources"`
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

func (c *Client) BackfillKnowledgeRevisionSourcesExact3(
	ctx context.Context,
	knowledgeBaseID string,
	request KnowledgeRevisionSourceExact3RequestV1,
) (*KnowledgeRevisionSourceExact3ResultV1, error) {
	if knowledgeBaseID == "" || request.Contract != KnowledgeRevisionSourceExact3ContractV1 ||
		len(request.Sources) != 3 {
		return nil, fmt.Errorf("exact knowledge base and exact3 manifest are required")
	}
	path := fmt.Sprintf(
		"/api/v1/knowledge-bases/%s/revision-sources/exact3/backfill", knowledgeBaseID,
	)
	response, err := c.doRequest(ctx, http.MethodPost, path, request, nil)
	if err != nil {
		return nil, err
	}
	var envelope struct {
		Success bool                                  `json:"success"`
		Data    KnowledgeRevisionSourceExact3ResultV1 `json:"data"`
	}
	if err := parseResponse(response, &envelope); err != nil {
		return nil, err
	}
	if !envelope.Success || envelope.Data.Contract != KnowledgeRevisionSourceExact3ContractV1 {
		return nil, fmt.Errorf("revision source exact3 backfill failed")
	}
	return &envelope.Data, nil
}
