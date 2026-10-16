package repository

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

func TestSourceBindingCannotBeRemovedWhilePublished(t *testing.T) {
	db := setupRevisionTestDB(t)
	id := committedPDF(t, db, NewKnowledgeRepository(db).(*knowledgeRepository))
	source := sourceRow(t, db, id, 1)
	ctx := context.Background()
	resources := NewResourceRepository(db)
	require.NoError(t, pinSources(db, 1, RevisionRef{KnowledgeID: id, ParseAttempt: 1}))
	require.ErrorIs(t, resources.DeleteBinding(ctx, source.ResourceID, "knowledge", id), ErrResourcePinned)
	var bindings int64
	require.NoError(t, db.Table("resource_bindings").Where("owner_id = ?", id).Count(&bindings).Error)
	require.EqualValues(t, 1, bindings)

	image := types.ResourceBinding{
		ID: "image-binding", TenantID: 1, ResourceID: "image-resource", OwnerType: "knowledge", OwnerID: id,
		Relation: "image",
	}
	require.NoError(t, db.Create(&image).Error)
	require.NoError(t, resources.DeleteBinding(ctx, image.ResourceID, "knowledge", id))
	require.NoError(t, releaseSources(db, 1, RevisionRef{KnowledgeID: id, ParseAttempt: 1}))
	require.NoError(t, resources.DeleteBinding(ctx, source.ResourceID, "knowledge", id))
}

func TestPinRejectsRemovedResourceOrBinding(t *testing.T) {
	for _, remove := range []string{"resource", "binding"} {
		t.Run(remove, func(t *testing.T) {
			db := setupRevisionTestDB(t)
			id := committedPDF(t, db, NewKnowledgeRepository(db).(*knowledgeRepository))
			source := sourceRow(t, db, id, 1)
			resources := NewResourceRepository(db)
			if remove == "resource" {
				require.NoError(t, resources.MarkDeleted(context.Background(), source.ResourceID))
			} else {
				require.NoError(t, resources.DeleteBinding(context.Background(), source.ResourceID, "knowledge", id))
			}
			require.ErrorIs(t, pinSources(db, 1, RevisionRef{KnowledgeID: id, ParseAttempt: 1}),
				ErrRevisionSourceUnavailable)
			require.Equal(t, types.KnowledgeRevisionSourceReleased, sourceRow(t, db, id, 1).RetentionState)
		})
	}
}

func TestSealingCannotPinAnUnavailableReleasedSource(t *testing.T) {
	for _, unavailable := range []string{"deleted resource", "removed binding", "deleting knowledge"} {
		t.Run(unavailable, func(t *testing.T) {
			db := setupRevisionTestDB(t)
			repo := NewKnowledgeRepository(db).(*knowledgeRepository)
			id := committedPDF(t, db, repo)
			source := sourceRow(t, db, id, 1)
			switch unavailable {
			case "deleted resource":
				require.NoError(t, NewResourceRepository(db).MarkDeleted(context.Background(), source.ResourceID))
			case "removed binding":
				err := NewResourceRepository(db).DeleteBinding(context.Background(), source.ResourceID, "knowledge", id)
				require.NoError(t, err)
			case "deleting knowledge":
				require.NoError(t, db.Exec("UPDATE knowledges SET parse_status = 'deleting' WHERE id = ?", id).Error)
			}
			_, err := repo.SealRevisionSourcePageCount(context.Background(), 1, id, 1, source.RevisionSourceID, 2)
			require.ErrorIs(t, err, ErrRevisionCommitFailed)
			after := sourceRow(t, db, id, 1)
			require.Equal(t, types.KnowledgeRevisionSourceReleased, after.RetentionState)
			require.Empty(t, after.BindingDigest)
			require.Nil(t, after.PageCount)
		})
	}
}

func TestOptimisticReleasePreservesAReboundPublishedSource(t *testing.T) {
	db := setupRevisionTestDB(t)
	id := committedPDF(t, db, NewKnowledgeRepository(db).(*knowledgeRepository))
	source := sourceRow(t, db, id, 1)
	require.NoError(t, db.Where("owner_id = ?", id).Delete(&types.ResourceBinding{}).Error)
	bound := false
	require.NoError(t, db.Callback().Delete().Before("gorm:delete").Register("test_rebound_source", func(tx *gorm.DB) {
		if tx.Statement.Table != "resource_bindings" || bound {
			return
		}
		bound = true
		work := tx.Session(&gorm.Session{NewDB: true})
		// A source claim and its publication arrive after the optimistic lookup.
		require.NoError(t, work.Create(&types.ResourceBinding{
			ID: "rebound", TenantID: 1, ResourceID: source.ResourceID,
			OwnerType: "knowledge", OwnerID: id, Relation: "source_file",
		}).Error)
		require.NoError(t, PinRevisionSources(work, 1, []RevisionRef{{KnowledgeID: id, ParseAttempt: 1}}))
	}))
	t.Cleanup(func() { require.NoError(t, db.Callback().Delete().Remove("test_rebound_source")) })
	err := NewResourceRepository(db).DeleteBinding(context.Background(), source.ResourceID, "knowledge", id)
	require.NoError(t, err)
	var claims int64
	require.NoError(t, db.Table("resource_bindings").Where("owner_id = ? AND relation = 'source_file'", id).
		Count(&claims).Error)
	require.EqualValues(t, 1, claims)
	require.Equal(t, types.KnowledgeRevisionSourcePinned, sourceRow(t, db, id, 1).RetentionState)
}
