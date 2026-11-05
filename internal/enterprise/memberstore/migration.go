package memberstore

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"sort"

	"github.com/Tencent/WeKnora/internal/types"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

type migrationSource struct {
	Release     types.WikiRelease
	Preparation types.WikiReleasePreparation
	Members     []types.WikiReleaseMemberSnapshot
}

func loadMigrationSource(db *gorm.DB, scope types.WikiReleaseScope, id string) (migrationSource, error) {
	var source migrationSource
	var err error
	source.Release, err = releaseHeader(db, scope, id)
	if err != nil {
		return source, err
	}
	if err := exactScope(db, scope).Where("preparation_id = ?", source.Release.PreparationID).
		Take(&source.Preparation).Error; err != nil {
		return source, err
	}
	if source.Preparation.Status != "ready" || source.Release.PreparationID != source.Preparation.ID {
		return source, ErrIntegrity
	}
	if source.Release.MemberStorage == "chunks.v1" {
		root, err := releaseRoot(db, scope, id)
		if err != nil {
			return source, failedRead(err)
		}
		_, source.Members, err = readLayout(db, root, true, true)
		if err != nil {
			return source, err
		}
		pRoot, err := preparationRoot(db, scope, source.Preparation.ID)
		if err != nil {
			return source, failedRead(err)
		}
		_, source.Preparation.Members, err = readLayout(db, pRoot, true)
		return source, err
	}
	if source.Release.MemberStorage != "" && source.Release.MemberStorage != "bridge.v1" {
		return source, ErrIntegrity
	}
	source.Members, err = legacyMembers(db, id)
	return source, err
}

func sourceIdentity(s migrationSource) ([]byte, int64, error) {
	raw, err := json.Marshal(s)
	if err != nil {
		return nil, 0, ErrIntegrity
	}
	h := sha256.New()
	h.Write([]byte("enterprise-member-migration-source.v1\x00"))
	h.Write(raw)
	var n int64
	for _, list := range [][]types.WikiReleaseMemberSnapshot{s.Members, s.Preparation.Members} {
		for _, m := range list {
			n += int64(len(m.Kind) + len(m.LogicalSlug) + len(m.RevisionID) +
				len(m.MemberDigest) + len(m.Title) + len(m.Content) + len(m.Payload))
		}
	}
	return h.Sum(nil), n, nil
}

func canonicalSnapshots(
	db *gorm.DB, scopeID int64, items []types.WikiReleaseMemberSnapshot,
) ([]types.WikiReleaseMemberSnapshot, error) {
	records, err := canonicalContents(db, scopeID, items)
	if err != nil {
		return nil, err
	}
	out := make([]types.WikiReleaseMemberSnapshot, len(records))
	for i, r := range records {
		out[i] = contentSnapshot(r)
	}
	return out, nil
}

func logicalSequenceEqual(a, b []types.WikiReleaseMemberSnapshot) bool {
	if len(a) != len(b) {
		return false
	}
	for i, x := range a {
		y := b[i]
		if x.Kind != y.Kind || x.LogicalSlug != y.LogicalSlug || x.RevisionID != y.RevisionID ||
			x.MemberDigest != y.MemberDigest || x.Title != y.Title || x.Content != y.Content ||
			!bytes.Equal(x.Payload, y.Payload) {
			return false
		}
	}
	return true
}

// Backfill handles one immutable release and its associated preparation, bounded by
// a caller-supplied logical-byte budget. The staged source identity survives a failed
// second transaction; retry must match it. It never selects an unassociated draft.
func (s *Store) Backfill(
	ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope, id string, maxBytes int64,
) (failure error) {
	defer func() { noteValidationFailure(db, scope, failure) }()
	if s.verify == nil || maxBytes <= 0 {
		return ErrState
	}
	err := db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		sc, err := lockedScope(tx, scope, true)
		if err != nil {
			return err
		}
		source, err := loadMigrationSource(tx, scope, id)
		if err != nil {
			return err
		}
		if err := s.verify(source.Release, source.Preparation, source.Members); err != nil {
			return err
		}
		digest, size, err := sourceIdentity(source)
		if err != nil {
			return err
		}
		if size > maxBytes {
			return ErrState
		}
		wanted := progressRow{ReleaseID: id, ScopeID: sc.ID, SourceDigest: digest, Phase: "staged", SourceBytes: size}
		if err := tx.Clauses(clause.OnConflict{DoNothing: true}).Create(&wanted).Error; err != nil {
			return err
		}
		var saved progressRow
		if err := tx.Where("release_id = ?", id).Take(&saved).Error; err != nil {
			return err
		}
		if saved.ScopeID != sc.ID || !sameDigest(saved.SourceDigest, digest) || saved.SourceBytes != size {
			return ErrIntegrity
		}
		return nil
	})
	if err != nil {
		return err
	}
	return db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		sc, err := lockedScope(tx, scope, false)
		if err != nil {
			return err
		}
		if sc.Mode != "bridge" {
			return ErrState
		}
		// Lock the same source owners and rows throughout certification. The release
		// lock also blocks new member rows through its FK; ordering is stable by slug.
		var locked types.WikiRelease
		if err := exactScope(tx.Clauses(clause.Locking{Strength: "UPDATE"}), scope).
			Where("release_id=?", id).Take(&locked).Error; err != nil {
			return err
		}
		var preparation types.WikiReleasePreparation
		if err := exactScope(tx.Clauses(clause.Locking{Strength: "UPDATE"}), scope).
			Where("preparation_id=?", locked.PreparationID).Take(&preparation).
			Error; err != nil {
			return err
		}
		var rows []types.WikiReleaseMember
		if err := tx.Clauses(clause.Locking{Strength: "SHARE"}).Where("release_id=?", id).
			Order("logical_slug ASC").Find(&rows).Error; err != nil {
			return err
		}
		source, err := loadMigrationSource(tx, scope, id)
		if err != nil {
			return err
		}
		if err := s.verify(source.Release, source.Preparation, source.Members); err != nil {
			return err
		}
		digest, size, err := sourceIdentity(source)
		if err != nil {
			return err
		}
		if size > maxBytes {
			return ErrState
		}
		var saved progressRow
		if err := tx.Where("release_id = ?", id).Take(&saved).Error; err != nil {
			return err
		}
		if saved.ScopeID != sc.ID || !sameDigest(saved.SourceDigest, digest) || saved.SourceBytes != size {
			return ErrIntegrity
		}
		var existing releaseMap
		mappedErr := tx.Where("release_id = ?", id).Take(&existing).Error
		if mappedErr == nil {
			if err := s.verifyRelease(tx, scope, source.Release); err != nil {
				return err
			}
			return tx.Model(&progressRow{}).Where("release_id = ?", id).Update("phase", "verified").Error
		}
		if !errors.Is(mappedErr, gorm.ErrRecordNotFound) {
			return mappedErr
		}
		internalMembers := append([]types.WikiReleaseMemberSnapshot(nil), source.Members...)
		sort.Slice(internalMembers, func(i, j int) bool {
			return internalMembers[i].LogicalSlug < internalMembers[j].LogicalSlug
		})
		root, err := persistRoot(tx, sc.ID, internalMembers, nil, "slug_asc")
		if err != nil {
			return err
		}
		releaseMembers, err := canonicalSnapshots(tx, sc.ID, internalMembers)
		if err != nil {
			return err
		}
		prepMembers, err := canonicalSnapshots(tx, sc.ID, source.Preparation.Members)
		if err != nil {
			return err
		}
		prepRoot := root
		// Layout digests are deliberately not a logical equality predicate.
		if !logicalSequenceEqual(releaseMembers, prepMembers) {
			prepRoot, err = persistRoot(tx, sc.ID, source.Preparation.Members, nil, "legacy_sequence")
			if err != nil {
				return err
			}
		}
		after, err := loadMigrationSource(tx, scope, id)
		if err != nil {
			return err
		}
		afterDigest, afterSize, err := sourceIdentity(after)
		if err != nil {
			return err
		}
		if afterSize != size || !sameDigest(digest, afterDigest) {
			return ErrIntegrity
		}
		if err := writeReleaseMap(tx, releaseMap{id, sc.ID, scope, root.Digest, true}); err != nil {
			return err
		}
		if err := writePreparationMap(
			tx, preparationMap{source.Preparation.ID, sc.ID, scope, prepRoot.Digest, true},
		); err != nil {
			return err
		}
		if err := setOwnerFormat(tx, scope, "wiki_releases", "release_id", id, "bridge.v1"); err != nil {
			return err
		}
		if err := setOwnerFormat(
			tx, scope, "wiki_release_preparations", "preparation_id", source.Preparation.ID, "bridge.v1",
		); err != nil {
			return err
		}
		return tx.Model(&progressRow{}).Where("release_id = ?", id).Update("phase", "verified").Error
	})
}

func (s *Store) verifyRelease(db *gorm.DB, scope types.WikiReleaseScope, r types.WikiRelease) error {
	root, err := releaseRoot(db, scope, r.ID)
	if err != nil {
		return failedRead(err)
	}
	_, members, err := readLayout(db, root, true, true)
	if err != nil {
		return err
	}
	if root.OrderMode != "slug_asc" {
		return ErrIntegrity
	}
	pRoot, err := preparationRoot(db, scope, r.PreparationID)
	if err != nil {
		return failedRead(err)
	}
	var prepared []types.WikiReleaseMemberSnapshot
	if sameDigest(root.Digest, pRoot.Digest) {
		_, prepared, err = readLayout(db, pRoot, true)
		if err != nil {
			return err
		} // internal preparation order differs from SQL Release order
	} else {
		_, prepared, err = readLayout(db, pRoot, true)
		if err != nil {
			return err
		}
	}
	if r.MemberStorage == "" || r.MemberStorage == "bridge.v1" {
		old, err := legacyMembers(db, r.ID)
		if err != nil {
			return err
		}
		old, err = canonicalSnapshots(db, root.ScopeID, old)
		if err != nil {
			return err
		}
		if !logicalSequenceEqual(old, members) {
			return ErrIntegrity
		}
		prep, err := preparationMembers(db, scope, r.PreparationID)
		if err != nil {
			return err
		}
		prep, err = canonicalSnapshots(db, root.ScopeID, prep)
		if err != nil {
			return err
		}
		if !logicalSequenceEqual(prep, prepared) {
			return ErrIntegrity
		}
	} else if r.MemberStorage != "chunks.v1" {
		return ErrIntegrity
	}
	var p types.WikiReleasePreparation
	if err := exactScope(db, scope).Where("preparation_id=?", r.PreparationID).Take(&p).Error; err != nil {
		return err
	}
	p.Members = prepared
	if s.verify == nil {
		return ErrState
	}
	return s.verify(r, p, members)
}
