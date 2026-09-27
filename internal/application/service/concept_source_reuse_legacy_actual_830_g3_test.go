package service

import (
	"context"
	"encoding/json"
	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"os"
	"path/filepath"
	"testing"
)

func TestLegacyPreparedActualC5ReceiptUsesDistinctManifestDomains830G3(t *testing.T) {
	path := os.Getenv("G3_ACTUAL_LEGACY_SEAL")
	if path == "" {
		t.Skip("set G3_ACTUAL_LEGACY_SEAL to the local actual proof export")
	}
	data, err := os.ReadFile(path)
	require.NoError(t, err)
	var seal struct {
		Payload json.RawMessage `json:"payload"`
	}
	require.NoError(t, json.Unmarshal(data, &seal))
	var proofs map[string]*types.SchemaWikiCitationContentAuthorityV1
	require.NoError(t, json.Unmarshal(seal.Payload, &proofs))
	directory := filepath.Join("..", "..", "..", "docs", "insurance-kb", "evidence", "830-g2", "inputs", "c5")
	if actual := os.Getenv("G3_ACTUAL_C5_DIR"); actual != "" {
		directory = actual
	}
	prepared := t.TempDir()
	require.NoError(t, os.Chmod(prepared, 0700))
	files, err := os.ReadDir(directory)
	require.NoError(t, err)
	for _, file := range files {
		if file.IsDir() {
			continue
		}
		data, err := os.ReadFile(filepath.Join(directory, file.Name()))
		require.NoError(t, err)
		require.NoError(t, os.WriteFile(filepath.Join(prepared, file.Name()), data, 0600))
	}
	registry, err := wikirepository.NewSchemaWikiFormalCandidatePreviewRegistry(filepath.Join(prepared, "manifest.json"))
	require.NoError(t, err)
	bridge, request, _ := cfg42LegacyDigestFixture(t)
	repo := bridge.revisions.(*conceptKnowledgeStub830G2)
	bridge.formalCandidatePreview = registry
	for _, authority := range proofs {
		receipt := authority.RevisionSource
		if receipt.KnowledgeID != "f987fc16-222a-4246-8ca0-22c1a81dd6d9" {
			continue
		}
		request.Scope = types.WikiReleaseScope{TenantID: receipt.TenantID, SpaceID: receipt.SpaceID, RawKBID: receipt.RawKBID, WikiKBID: receipt.WikiKBID}
		request.Evidence.KnowledgeID, request.Evidence.ParseAttempt = receipt.KnowledgeID, receipt.WeKnoraParseAttempt
		repo.knowledge.TenantID, repo.knowledge.KnowledgeBaseID = receipt.TenantID, receipt.RawKBID
		repo.source.TenantID, repo.source.KnowledgeID, repo.source.ParseAttempt = receipt.TenantID, receipt.KnowledgeID, receipt.WeKnoraParseAttempt
		repo.source.ResourceID, repo.source.FileSHA256, repo.source.ObjectSHA256 = receipt.ResourceID, receipt.FileSHA256, receipt.FileSHA256
		repo.source.Size, repo.source.MimeType = receipt.Size, receipt.MimeType
		pageCount := receipt.PageCount
		repo.source.PageCount = &pageCount
		repo.source.ManifestAlgorithm, repo.source.ChunkCount = receipt.WeKnoraManifestAlgorithm, receipt.WeKnoraChunkCount
		readySourceReuseResource830G3(bridge)
		repo.resource.ID = receipt.ResourceID
		repo.revision.FileSHA256, repo.revision.ManifestDigest, repo.revision.ManifestAlgorithm, repo.revision.ChunkCount = repo.source.FileSHA256, repo.source.ManifestDigest, repo.source.ManifestAlgorithm, repo.source.ChunkCount
		require.NotEqual(t, receipt.WeKnoraManifestDigest, repo.source.ManifestDigest)
		require.True(t, bridge.reusableLegacySourceCurrent830G3(context.Background(), request, repo.source, repo.resource, authority), "frozen manifest hash must resolve to original DB chunk manifest hash")
		for _, mutation := range []string{"candidate", "frozen digest", "DB digest", "revoked resource"} {
			a, source, resource, revision := *authority, *repo.source, *repo.resource, *repo.revision
			switch mutation {
			case "candidate":
				a.CandidateSHA256 = testSHA830G2("unrelated candidate")
			case "frozen digest":
				a.RevisionSource.WeKnoraManifestDigest = testSHA830G2("unrelated frozen manifest")
			case "DB digest":
				source.ManifestDigest = testSHA830G2("changed original manifest")
				repo.revision.ManifestDigest = source.ManifestDigest
			case "revoked resource":
				resource.State = "deleted"
			}
			require.False(t, bridge.reusableLegacySourceCurrent830G3(context.Background(), request, &source, &resource, &a), mutation)
			*repo.revision = revision
		}
		return
	}
	t.Fatal("actual terms receipt missing")
}
