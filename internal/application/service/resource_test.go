package service

import (
	"context"
	"testing"
	"time"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func newResourceCatalogForTest(t *testing.T) (interfaces.ResourceCatalog, *gorm.DB) {
	t.Helper()
	db, err := gorm.Open(sqlite.Open("file:"+t.Name()+"?mode=memory&cache=shared"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(
		&types.StoredResource{},
		&types.ResourceBinding{},
		&types.ResourceAccessGrant{},
		&types.KnowledgeRevisionSource{},
	))
	return NewResourceCatalog(repository.NewResourceRepository(db)), db
}

func TestResourceCatalogRegisterResolveAndDeduplicate(t *testing.T) {
	catalog, _ := newResourceCatalogForTest(t)
	ctx := context.Background()
	physical := "storage://backend-a/local://7/exports/a.png"

	ref, err := catalog.Register(ctx, 7, physical, interfaces.ResourceRegistration{Kind: "image", OriginalName: "a.png"})
	require.NoError(t, err)
	require.Regexp(t, `^resource://[0-9A-Za-z_-]{22}$`, ref)

	again, err := catalog.Register(ctx, 7, physical, interfaces.ResourceRegistration{})
	require.NoError(t, err)
	require.Equal(t, ref, again)

	resolvedPath, resource, err := catalog.ResolvePath(ctx, ref)
	require.NoError(t, err)
	require.Equal(t, physical, resolvedPath)
	require.Equal(t, uint64(7), resource.TenantID)
	require.Equal(t, "backend-a", resource.StorageBackendID)
	require.Equal(t, "local", resource.Provider)
}

func TestResourceCatalogBindingAndAccessGrant(t *testing.T) {
	catalog, db := newResourceCatalogForTest(t)
	ctx := context.Background()
	ref, err := catalog.Register(
		ctx,
		9,
		"local://9/exports/report.pdf",
		interfaces.ResourceRegistration{OriginalName: "report.pdf"},
	)
	require.NoError(t, err)
	require.NoError(t, catalog.Bind(ctx, ref, "knowledge", "knowledge-1", "source_file"))

	token, err := catalog.CreateAccessGrant(ctx, ref, time.Minute)
	require.NoError(t, err)
	require.Len(t, token, 22)
	var storedGrant types.ResourceAccessGrant
	require.NoError(t, db.First(&storedGrant).Error)
	require.NotEqual(t, token, storedGrant.TokenHash)
	require.Len(t, storedGrant.TokenHash, 64)
	resource, err := catalog.ResolveAccessGrant(ctx, token)
	require.NoError(t, err)
	require.Equal(t, uint64(9), resource.TenantID)
}

func TestResourceCatalogRejectsUnsupportedPhysicalPath(t *testing.T) {
	catalog, _ := newResourceCatalogForTest(t)
	_, err := catalog.Register(context.Background(), 7, "https://example.com/a.png", interfaces.ResourceRegistration{})
	require.ErrorContains(t, err, "unsupported provider")
}

func TestResourceCatalogMarkDeletedRejectsPinnedRevisionSource(t *testing.T) {
	catalog, db := newResourceCatalogForTest(t)
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
