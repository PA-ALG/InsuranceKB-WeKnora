package service

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
)

// The revision-source pin guard is ours; the upstream catalog fixture (resource_test.go) stays
// byte-identical, so this test creates the pin table itself.
func TestResourceCatalogMarkDeletedRejectsPinnedRevisionSource(t *testing.T) {
	catalog, db := newResourceCatalogForTest(t)
	require.NoError(t, db.AutoMigrate(&types.KnowledgeRevisionSource{}))
	ctx := context.Background()
	fileSHA256 := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	ref, err := catalog.Register(
		ctx,
		9,
		"local://9/immutable/report.pdf",
		interfaces.ResourceRegistration{
			Kind: "file", MimeType: "application/pdf", Size: 1024,
			ContentHash: fileSHA256,
		},
	)
	require.NoError(t, err)
	resource, err := catalog.Resolve(ctx, ref)
	require.NoError(t, err)
	require.NoError(t, db.Create(&types.KnowledgeRevisionSource{
		TenantID: 9, KnowledgeID: "knowledge-1", ParseAttempt: 1,
		ResourceID: resource.ID, FileSHA256: fileSHA256, Size: 1024,
		MimeType: "application/pdf", RetentionState: types.KnowledgeRevisionSourcePinned,
	}).Error)

	err = catalog.MarkDeleted(ctx, ref)
	require.ErrorIs(t, err, repository.ErrResourcePinned)
	var after types.StoredResource
	require.NoError(t, db.Where("id = ?", resource.ID).First(&after).Error)
	require.Equal(t, types.ResourceStateActive, after.State)
}
