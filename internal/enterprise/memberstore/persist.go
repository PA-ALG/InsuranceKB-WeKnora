package memberstore

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"reflect"

	"github.com/Tencent/WeKnora/internal/types"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

const storageBatch = 400

func exactScope(db *gorm.DB, s types.WikiReleaseScope) *gorm.DB {
	return db.Where("tenant_id = ? AND space_id = ? AND raw_kb_id = ? AND wiki_kb_id = ?",
		s.TenantID, s.SpaceID, s.RawKBID, s.WikiKBID,
	)
}

func lockedScope(db *gorm.DB, s types.WikiReleaseScope, create bool) (scopeRow, error) {
	if s.TenantID == 0 || s.SpaceID == "" || s.RawKBID == "" || s.WikiKBID == "" {
		return scopeRow{}, ErrIntegrity
	}
	if create {
		r := scopeRow{WikiReleaseScope: s, Mode: "bridge"}
		if err := db.Clauses(clause.OnConflict{DoNothing: true}).Create(&r).Error; err != nil {
			return scopeRow{}, err
		}
	}
	var r scopeRow
	err := exactScope(db.Clauses(clause.Locking{Strength: "UPDATE"}), s).Take(&r).Error
	return r, err
}

// canonicalContents freezes the exact PostgreSQL jsonb projection once at the write boundary.
func canonicalContents(db *gorm.DB, scopeID int64, input []types.WikiReleaseMemberSnapshot) ([]contentRow, error) {
	out := make([]contentRow, len(input))
	for start := 0; start < len(input); start += storageBatch {
		end := min(len(input), start+storageBatch)
		payloads := make([]json.RawMessage, end-start)
		for i := range payloads {
			payloads[i] = input[start+i].Payload
			if len(payloads[i]) == 0 {
				return nil, ErrIntegrity
			}
		}
		raw, err := json.Marshal(payloads)
		if err != nil {
			return nil, ErrIntegrity
		}
		var projected []struct{ Value string }
		if err := db.Raw(`SELECT value::text AS value FROM jsonb_array_elements(?::jsonb)
 WITH ORDINALITY AS items(value,ordinal) ORDER BY ordinal`, string(raw)).
			Scan(&projected).Error; err != nil {
			return nil, err
		}
		if len(projected) != len(payloads) {
			return nil, ErrIntegrity
		}
		for i, p := range projected {
			snapshot := input[start+i]
			snapshot.Payload = json.RawMessage(p.Value)
			out[start+i] = encodeContent(scopeID, snapshot)
		}
	}
	return out, nil
}

func writeContents(db *gorm.DB, rows []contentRow) error {
	for start := 0; start < len(rows); start += storageBatch {
		end := min(len(rows), start+storageBatch)
		batch := rows[start:end]
		if err := db.Clauses(clause.OnConflict{DoNothing: true}).Create(&batch).Error; err != nil {
			return err
		}
		keys := make([][]byte, len(batch))
		for i := range batch {
			keys[i] = batch[i].Digest
		}
		var stored []contentRow
		if err := byDigests(db, "enterprise_member_contents", batch[0].ScopeID, keys).Find(&stored).Error; err != nil {
			return err
		}
		found := make(map[string]contentRow, len(stored))
		for _, r := range stored {
			found[string(r.Digest)] = r
		}
		for _, r := range batch {
			other, ok := found[string(r.Digest)]
			if !ok || !reflect.DeepEqual(r, other) {
				return ErrIntegrity
			}
		}
	}
	return nil
}

func writeChunks(db *gorm.DB, rows []chunkRow) error {
	for start := 0; start < len(rows); start += storageBatch {
		end := min(len(rows), start+storageBatch)
		batch := rows[start:end]
		if err := db.Clauses(clause.OnConflict{DoNothing: true}).Create(&batch).Error; err != nil {
			return err
		}
		keys := make([][]byte, len(batch))
		for i := range batch {
			keys[i] = batch[i].Digest
		}
		var stored []chunkRow
		if err := byDigests(db, "enterprise_member_chunks", batch[0].ScopeID, keys).Find(&stored).Error; err != nil {
			return err
		}
		found := make(map[string]chunkRow, len(stored))
		for _, r := range stored {
			found[string(r.Digest)] = r
		}
		for _, r := range batch {
			other, ok := found[string(r.Digest)]
			if !ok || !reflect.DeepEqual(r, other) {
				return ErrIntegrity
			}
		}
	}
	return nil
}

func writeSet(db *gorm.DB, r setRow) error {
	if err := db.Clauses(clause.OnConflict{DoNothing: true}).Create(&r).Error; err != nil {
		return err
	}
	var other setRow
	if err := db.Where("scope_id = ? AND digest = ?", r.ScopeID, r.Digest).Take(&other).Error; err != nil {
		return err
	}
	if !reflect.DeepEqual(r, other) {
		return ErrIntegrity
	}
	return nil
}

func writeReleaseMap(db *gorm.DB, r releaseMap) error {
	if err := db.Clauses(clause.OnConflict{DoNothing: true}).Create(&r).Error; err != nil {
		return err
	}
	var other releaseMap
	if err := db.Where("release_id = ?", r.ReleaseID).Take(&other).Error; err != nil {
		return err
	}
	if !reflect.DeepEqual(r, other) {
		return ErrIntegrity
	}
	return nil
}

func writePreparationMap(db *gorm.DB, r preparationMap) error {
	if err := db.Clauses(clause.OnConflict{DoNothing: true}).Create(&r).Error; err != nil {
		return err
	}
	var other preparationMap
	if err := db.Where("preparation_id = ?", r.PreparationID).Take(&other).Error; err != nil {
		return err
	}
	if !reflect.DeepEqual(r, other) {
		return ErrIntegrity
	}
	return nil
}

func persistRoot(
	db *gorm.DB, scopeID int64, input []types.WikiReleaseMemberSnapshot, parent []layoutChunk, mode string,
) (setRow, error) {
	contents, err := canonicalContents(db, scopeID, input)
	if err != nil {
		return setRow{}, err
	}
	entries := make([]layoutEntry, len(contents))
	for i, r := range contents {
		entries[i] = layoutEntry{r.LogicalSlug, r.Digest}
	}
	layout, err := buildLayout(entries, parent, mode)
	if err != nil {
		return setRow{}, err
	}
	if err := writeContents(db, contents); err != nil {
		return setRow{}, err
	}
	chunks := make([]chunkRow, len(layout))
	for i, c := range layout {
		chunks[i] = encodeChunk(scopeID, c.Entries)
	}
	if err := writeChunks(db, chunks); err != nil {
		return setRow{}, err
	}
	root := encodeSet(scopeID, mode, chunks)
	if err := writeSet(db, root); err != nil {
		return setRow{}, err
	}
	return root, nil
}

func legacyMembers(db *gorm.DB, id string) ([]types.WikiReleaseMemberSnapshot, error) {
	var rows []types.WikiReleaseMember
	if err := db.Where("release_id = ?", id).Order("logical_slug ASC").Find(&rows).Error; err != nil {
		return nil, err
	}
	out := make([]types.WikiReleaseMemberSnapshot, len(rows))
	for i := range rows {
		out[i] = rows[i].Snapshot()
	}
	return out, nil
}

func sameDigest(a, b []byte) bool { return len(a) == 32 && bytes.Equal(a, b) }

func releaseHeader(db *gorm.DB, s types.WikiReleaseScope, id string) (types.WikiRelease, error) {
	var r types.WikiRelease
	err := exactScope(db, s).Where("release_id = ?", id).Take(&r).Error
	return r, err
}

func failedRead(err error) error {
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return ErrIntegrity
	}
	return err
}

// Put persists a complete final collection inside the original activation transaction.
func (s *Store) Put(ctx context.Context, tx *gorm.DB, w types.WikiReleaseMemberSetWrite) error {
	db := tx.WithContext(ctx)
	sc, err := lockedScope(db, w.Scope, true)
	if err != nil {
		return err
	}
	if sc.Mode != "bridge" && sc.Mode != "reference" {
		return ErrState
	}
	if w.PreparationID == "" || w.ReleaseID == "" {
		return ErrIntegrity
	}
	var parent []layoutChunk
	if w.ParentReleaseID != "" {
		header, err := releaseHeader(db, w.Scope, w.ParentReleaseID)
		if err != nil {
			return err
		}
		root, err := releaseRoot(db, w.Scope, w.ParentReleaseID)
		if errors.Is(err, gorm.ErrRecordNotFound) && header.MemberStorage == "" {
			parent = nil
		} else if err != nil {
			return failedRead(err)
		} else {
			parent, _, err = readLayout(db, root, false)
			if err != nil {
				return err
			}
		}
	}
	if !validSnapshotStrings(w.Members) {
		return ErrIntegrity
	}
	contents, changed, err := s.computedContents(db, sc.ID, w, parent)
	if err != nil {
		return err
	}
	entries := make([]layoutEntry, len(contents))
	for i, c := range contents {
		entries[i] = layoutEntry{c.LogicalSlug, c.Digest}
	}
	layout, err := buildLayout(entries, parent, "slug_asc")
	if err != nil {
		return err
	}
	if err := writeContents(db, changed); err != nil {
		return err
	}
	chunks := make([]chunkRow, len(layout))
	for i, c := range layout {
		chunks[i] = encodeChunk(sc.ID, c.Entries)
	}
	parentChunks := make(map[string]bool, len(parent))
	for _, chunk := range parent {
		parentChunks[string(encodeChunk(sc.ID, chunk.Entries).Digest)] = true
	}
	var changedChunks []chunkRow
	for _, chunk := range chunks {
		if !parentChunks[string(chunk.Digest)] {
			changedChunks = append(changedChunks, chunk)
		}
	}
	if err := writeChunks(db, changedChunks); err != nil {
		return err
	}
	root := encodeSet(sc.ID, "slug_asc", chunks)
	if err := writeSet(db, root); err != nil {
		return err
	}
	if err := writeReleaseMap(db, releaseMap{w.ReleaseID, sc.ID, w.Scope, root.Digest, true}); err != nil {
		return err
	}
	if err := writePreparationMap(db, preparationMap{w.PreparationID, sc.ID, w.Scope, root.Digest, true}); err != nil {
		return err
	}
	format := "bridge.v1"
	if sc.ObservationStartedAt != nil {
		format = "chunks.v1"
	}
	if sc.Mode == "reference" {
		format = "chunks.v1"
	} else {
		raw, err := json.Marshal(w.Members)
		if err != nil {
			return ErrIntegrity
		}
		if err := exactScope(db.Table("wiki_release_preparations"), w.Scope).Where("preparation_id=?", w.PreparationID).
			Update("members", gorm.Expr("?::jsonb", string(raw))).Error; err != nil {
			return err
		}
		rows := make([]types.WikiReleaseMember, len(w.Members))
		for i, m := range w.Members {
			rows[i] = types.WikiReleaseMember{
				ID:           w.ReleaseID + ":" + m.LogicalSlug,
				ReleaseID:    w.ReleaseID,
				Kind:         m.Kind,
				LogicalSlug:  m.LogicalSlug,
				RevisionID:   m.RevisionID,
				MemberDigest: m.MemberDigest,
				Title:        m.Title,
				Content:      m.Content,
				Payload:      m.Payload,
			}
		}
		if len(rows) > 0 {
			if err := db.CreateInBatches(rows, storageBatch).Error; err != nil {
				return err
			}
		}
	}
	if err := setOwnerFormat(db, w.Scope, "wiki_releases", "release_id", w.ReleaseID, format); err != nil {
		return err
	}
	if err := setOwnerFormat(
		db, w.Scope, "wiki_release_preparations", "preparation_id", w.PreparationID, format,
	); err != nil {
		return err
	}
	s.rememberComputations(w, contents)
	return nil
}

func setOwnerFormat(db *gorm.DB, scope types.WikiReleaseScope, table, idColumn, id, format string) error {
	result := exactScope(db.Table(table), scope).Where(idColumn+" = ?", id).Update("member_storage", format)
	if result.Error != nil {
		return result.Error
	}
	if result.RowsAffected != 1 {
		return ErrState
	}
	return nil
}
