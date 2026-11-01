package repository

// S11g acceptance: Office (DOCX/PPTX/XLSX) parse attempts record their source revision at commit,
// exactly like PDFs, so a Release citing Office evidence can pin it; already committed attempts
// whose row is missing can be recorded once, never touching an existing row.
// Spec: docs/design/slices/S11g-Office来源修订记录.md §2, §4.

import (
	"context"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

var officeFormats = map[string]string{
	".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
	".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
	".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

func asOfficeResource(t *testing.T, db *gorm.DB, knowledgeID, mimeType, name string) {
	t.Helper()
	require.NoError(t, db.Model(&types.StoredResource{}).
		Where("id IN (SELECT resource_id FROM resource_bindings WHERE owner_id = ?)", knowledgeID).
		Updates(map[string]any{"mime_type": mimeType, "original_name": name}).Error)
}

func committedOffice(t *testing.T, db *gorm.DB, repo *knowledgeRepository, mimeType, name string) string {
	t.Helper()
	id := seedRevisionKnowledge(t, db, types.ParseStatusProcessing, 1, 0)
	seedRevisionChunk(t, db, id, 1, 0, "slide one")
	asOfficeResource(t, db, id, mimeType, name)
	_, err := repo.CommitDirectRevision(context.Background(), id, testRevisionBinding(1))
	require.NoError(t, err)
	return id
}

func TestCommitRecordsOfficeSourceRevisionsLikePDF(t *testing.T) {
	for extension, canonical := range officeFormats {
		for label, resourceMIME := range map[string]string{"canonical mime": canonical, "empty mime": ""} {
			t.Run(extension+"/"+label, func(t *testing.T) {
				db := setupRevisionTestDB(t)
				repo := NewKnowledgeRepository(db).(*knowledgeRepository)
				id := committedOffice(t, db, repo, resourceMIME, "deck"+extension)

				row := sourceRow(t, db, id, 1)
				require.Equal(t, canonical, row.MimeType)
				require.Equal(t, types.KnowledgeRevisionSourceReleased, row.RetentionState)
				require.Empty(t, row.BindingDigest, "commit-time rows stay unsealed")
				require.Nil(t, row.PageCount)

				ref := RevisionRef{KnowledgeID: id, ParseAttempt: 1}
				require.NoError(t, pinSources(db, 1, ref), "a Release citing Office evidence can pin it")
				require.Equal(t, types.KnowledgeRevisionSourcePinned, sourceRow(t, db, id, 1).RetentionState)
			})
		}
	}
}

func TestCommitSkipsAnOfficeNameWhoseResourceMIMEDisagrees(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := committedOffice(t, db, repo, "image/png", "deck.docx")

	var sources int64
	require.NoError(t, db.Table("knowledge_revision_sources").Where("knowledge_id = ?", id).Count(&sources).Error)
	require.Zero(t, sources)
	require.ErrorIs(t, pinSources(db, 1, RevisionRef{KnowledgeID: id, ParseAttempt: 1}), ErrRevisionSourceUnavailable)
}

func TestRecordMissingRevisionSourceDryRunThenRecordsOnce(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := committedOffice(t, db, repo, "", "deck.pptx")
	original := sourceRow(t, db, id, 1)
	require.NoError(t, db.Exec(`DELETE FROM knowledge_revision_sources WHERE knowledge_id = ?`, id).Error)
	ctx := context.Background()

	planned, outcome, err := repo.RecordMissingRevisionSource(ctx, 1, id, 1, true)
	require.NoError(t, err)
	require.Equal(t, types.RevisionSourceRecordWouldRecord, outcome)
	require.Equal(t, original.RevisionSourceID, planned.RevisionSourceID)
	var sources int64
	require.NoError(t, db.Table("knowledge_revision_sources").Where("knowledge_id = ?", id).Count(&sources).Error)
	require.Zero(t, sources, "a dry run writes nothing")

	recorded, outcome, err := repo.RecordMissingRevisionSource(ctx, 1, id, 1, false)
	require.NoError(t, err)
	require.Equal(t, types.RevisionSourceRecordRecorded, outcome)
	row := sourceRow(t, db, id, 1)
	require.Equal(t, original.RevisionSourceID, row.RevisionSourceID)
	require.Equal(t, original.MimeType, row.MimeType)
	require.Equal(t, recorded.RevisionSourceID, row.RevisionSourceID)
	require.Equal(t, types.KnowledgeRevisionSourceReleased, row.RetentionState)
	require.Empty(t, row.BindingDigest)

	again, outcome, err := repo.RecordMissingRevisionSource(ctx, 1, id, 1, false)
	require.NoError(t, err)
	require.Equal(t, types.RevisionSourceRecordPresent, outcome)
	require.Equal(t, row.RevisionSourceID, again.RevisionSourceID)
	require.NoError(t, pinSources(db, 1, RevisionRef{KnowledgeID: id, ParseAttempt: 1}))
}

func TestRecordMissingRevisionSourceNeverTouchesAnExistingPDFRow(t *testing.T) {
	db := setupRevisionTestDB(t)
	repo := NewKnowledgeRepository(db).(*knowledgeRepository)
	id := committedPDF(t, db, repo)
	before := sourceRow(t, db, id, 1)

	for _, dryRun := range []bool{true, false} {
		got, outcome, err := repo.RecordMissingRevisionSource(context.Background(), 1, id, 1, dryRun)
		require.NoError(t, err)
		require.Equal(t, types.RevisionSourceRecordPresent, outcome)
		require.Equal(t, before.RevisionSourceID, got.RevisionSourceID)
	}
	after := sourceRow(t, db, id, 1)
	require.Equal(t, before, after)
}

func TestRecordMissingRevisionSourceRefusesUnboundOrDriftedAttempts(t *testing.T) {
	cases := map[string]func(*testing.T, *gorm.DB, string) (uint64, int64){
		"not the current attempt": func(t *testing.T, db *gorm.DB, id string) (uint64, int64) {
			return 1, 2
		},
		"another tenant": func(t *testing.T, db *gorm.DB, id string) (uint64, int64) {
			return 2, 1
		},
		"resource digest drift": func(t *testing.T, db *gorm.DB, id string) (uint64, int64) {
			require.NoError(t, db.Model(&types.StoredResource{}).
				Where("id IN (SELECT resource_id FROM resource_bindings WHERE owner_id = ?)", id).
				Update("content_hash", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb").Error)
			return 1, 1
		},
		"unsupported format": func(t *testing.T, db *gorm.DB, id string) (uint64, int64) {
			asOfficeResource(t, db, id, "text/markdown", "notes.md")
			return 1, 1
		},
		"no committed revision": func(t *testing.T, db *gorm.DB, id string) (uint64, int64) {
			require.NoError(t, db.Exec(`DELETE FROM knowledge_revisions WHERE knowledge_id = ?`, id).Error)
			return 1, 1
		},
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			db := setupRevisionTestDB(t)
			repo := NewKnowledgeRepository(db).(*knowledgeRepository)
			id := committedOffice(t, db, repo, "", "deck.xlsx")
			require.NoError(t, db.Exec(`DELETE FROM knowledge_revision_sources WHERE knowledge_id = ?`, id).Error)
			tenantID, attempt := mutate(t, db, id)

			_, _, err := repo.RecordMissingRevisionSource(context.Background(), tenantID, id, attempt, false)
			require.ErrorIs(t, err, ErrRevisionSourceUnavailable)
			var sources int64
			require.NoError(t, db.Table("knowledge_revision_sources").Where("knowledge_id = ?", id).Count(&sources).Error)
			require.Zero(t, sources)
		})
	}
}
