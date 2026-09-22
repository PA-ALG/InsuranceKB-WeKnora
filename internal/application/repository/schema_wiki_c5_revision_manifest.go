package repository

import (
	"encoding/json"
	"github.com/Tencent/WeKnora/internal/types"
)

// ReadOriginalRevisionManifestDigestExact joins the frozen C5 manifest's own
// hash to its original chunk-manifest hash. Both are immutable but are different
// digest domains. Only already validated in-memory records are consulted; this
// does not read a PDF, current/latest source, or a release chain.
func (r *SchemaWikiFormalCandidatePreviewRegistry) ReadOriginalRevisionManifestDigestExact(tenantID uint64, candidateSHA256 string, receipt types.LiveRevisionSourceReceiptV1) (string, error) {
	if r == nil || tenantID != receipt.TenantID || types.ValidateLiveRevisionSourceReceiptV1(receipt) != nil || !validSchemaWikiC5SHA256(candidateSHA256) {
		return "", ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	for key, record := range r.records {
		if key.tenantID != tenantID || key.key.KBID != receipt.RawKBID || record.public.CandidateSHA256 != candidateSHA256 || !validSchemaWikiC5PublicRecord(record.public, tenantID, key.key) {
			continue
		}
		for _, raw := range record.sourceManifests {
			var manifest struct {
				Self        string `json:"manifest_self_sha256"`
				Original    string `json:"parse_manifest_sha256"`
				Algorithm   string `json:"parse_manifest_algorithm"`
				TenantID    uint64 `json:"tenant_id"`
				KBID        string `json:"knowledge_base_id"`
				KnowledgeID string `json:"knowledge_id"`
				Attempt     int64  `json:"weknora_parse_attempt"`
				RevisionID  string `json:"compiler_source_revision_id"`
				ResourceID  string `json:"resource_id"`
				FileSHA256  string `json:"file_sha256"`
				Size        int64  `json:"file_size"`
				MimeType    string `json:"mime_type"`
				PageCount   int    `json:"page_count"`
				ChunkCount  int    `json:"chunk_count"`
			}
			if json.Unmarshal(raw, &manifest) != nil || manifest.Self != receipt.WeKnoraManifestDigest {
				continue
			}
			if manifest.TenantID != tenantID || manifest.KBID != receipt.RawKBID || manifest.KnowledgeID != receipt.KnowledgeID || manifest.Attempt != receipt.WeKnoraParseAttempt || manifest.RevisionID != receipt.RevisionSourceID || manifest.ResourceID != receipt.ResourceID || manifest.FileSHA256 != receipt.FileSHA256 || manifest.Size != receipt.Size || manifest.MimeType != receipt.MimeType || manifest.PageCount != receipt.PageCount || manifest.ChunkCount != receipt.WeKnoraChunkCount || manifest.Algorithm != receipt.WeKnoraManifestAlgorithm || !validSchemaWikiC5SHA256(manifest.Original) {
				return "", ErrSchemaWikiFormalCandidatePreviewBindingMismatch
			}
			return manifest.Original, nil
		}
	}
	return "", ErrSchemaWikiFormalCandidatePreviewNotFound
}
