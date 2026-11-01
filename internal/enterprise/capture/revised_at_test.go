// SK-3 acceptance (Spec docs/design/slices/SK-3-销售方法阅读与问答.md §4.3): a source artifact carries
// the time its revision was read completely, the only material date the platform knows. Protected
// file: written by Claude. Reuses the capture acceptance fixture. RED until SK-3.
package capture_test

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/Tencent/WeKnora/internal/enterprise/capture"
	"github.com/Tencent/WeKnora/internal/types"
)

func TestASourceArtifactCarriesItsRevisionTime(t *testing.T) {
	in, sealed := load(t)
	id := in.Identity
	completed := time.Date(2026, 10, 29, 8, 0, 0, 0, time.UTC)
	repo := knowledgeRepo{
		knowledge: &types.Knowledge{
			ID: id.KnowledgeID, TenantID: id.TenantID, KnowledgeBaseID: id.RawKBID, FileName: "条款.pdf",
		},
		revision: &types.KnowledgeRevision{
			KnowledgeID: id.KnowledgeID, ParseAttempt: id.ParseAttempt, FileSHA256: id.SourceSHA256,
			CompletedAt: completed,
		},
	}
	scope := types.WikiReleaseScope{TenantID: id.TenantID, SpaceID: "space-1", RawKBID: id.RawKBID, WikiKBID: "wiki-1"}
	store := capture.NewStore(seeded(t, in, sealed), testKeys())
	artifact, err := capture.ReadSourceArtifact(context.Background(), store,
		repo, scope, id.KnowledgeID, id.ParseAttempt)
	require.NoError(t, err)
	require.True(t, completed.Equal(artifact.RevisedAt), "%v", artifact.RevisedAt)
}
