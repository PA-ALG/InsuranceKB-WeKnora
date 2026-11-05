package memberstore

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"gorm.io/gorm"
)

// StartObservation switches verified histories to new reads while retaining bridge writes.
// No history is removed. A restart always begins a fresh seven-day observation.
func (s *Store) StartObservation(ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope) (failure error) {
	defer func() { noteValidationFailure(db, scope, failure) }()
	before, err := s.verifyTransition(ctx, db, scope)
	if err != nil {
		return err
	}
	return db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		sc, err := lockedScope(tx, scope, false)
		if err != nil {
			return err
		}
		if sc.Mode != "bridge" && sc.Mode != "reference" {
			return ErrState
		}
		releases, err := verifiedOwners(tx, scope)
		if err != nil {
			return err
		}
		after, err := transitionView(tx, scope, releases)
		if err != nil {
			return err
		}
		if !reflect.DeepEqual(before, after) {
			return ErrState
		}
		if err := markReferenceReads(tx, scope, releases); err != nil {
			return err
		}
		return tx.Model(&scopeRow{}).Where("id = ?", sc.ID).Updates(map[string]any{
			"observation_started_at": gorm.Expr("CURRENT_TIMESTAMP"), "read_failures": 0,
		}).
			Error
	})
}

// ReferenceOnly is an explicit operator action after durable verification and observation.
// It does not compact any old data. Availability/telemetry gaps require restarting observation.
func (s *Store) ReferenceOnly(ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope) (failure error) {
	defer func() { noteValidationFailure(db, scope, failure) }()
	before, err := s.verifyTransition(ctx, db, scope)
	if err != nil {
		return err
	}
	return db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		sc, err := lockedScope(tx, scope, false)
		if err != nil {
			return err
		}
		if sc.Mode != "bridge" && sc.Mode != "reference" {
			return ErrState
		}
		var ready bool
		if err := tx.Raw("SELECT observation_started_at <= CURRENT_TIMESTAMP-observation_wi"+
			"ndow_seconds*INTERVAL '1 second'\n AND read_failures=0 FROM enterp"+
			"rise_member_scopes WHERE id=?", sc.ID).
			Scan(&ready).Error; err != nil {
			return err
		}
		if !ready {
			return ErrState
		}
		releases, err := verifiedOwners(tx, scope)
		if err != nil {
			return err
		}
		after, err := transitionView(tx, scope, releases)
		if err != nil {
			return err
		}
		if !reflect.DeepEqual(before, after) {
			return ErrState
		}
		if err := markReferenceReads(tx, scope, releases); err != nil {
			return err
		}
		return tx.Model(&scopeRow{}).Where("id = ?", sc.ID).Update("mode", "reference").Error
	})
}

// verifiedOwners checks durable, scope-exact completion markers, not creation-time watermarks.
// Each marker was published with complete validation in Put/Backfill's transaction. This
// cutover check reads only bounded metadata; full verification is per-release, not one long snapshot.
func verifiedOwners(db *gorm.DB, scope types.WikiReleaseScope) ([]types.WikiRelease, error) {
	var releases []types.WikiRelease
	if err := exactScope(db, scope).Order("release_id ASC").Find(&releases).Error; err != nil {
		return nil, err
	}
	for _, r := range releases {
		root, err := releaseRoot(db, scope, r.ID)
		if err != nil {
			return nil, failedRead(err)
		}
		if root.OrderMode != "slug_asc" || root.Codec != 1 {
			return nil, ErrIntegrity
		}
		pRoot, err := preparationRoot(db, scope, r.PreparationID)
		if err != nil {
			return nil, failedRead(err)
		}
		if pRoot.Codec != 1 {
			return nil, ErrIntegrity
		}
		var ready int64
		if err := exactScope(db.Model(&types.WikiReleasePreparation{}), scope).
			Where("preparation_id = ? AND status = ?", r.PreparationID, "ready").
			Count(&ready).Error; err != nil {
			return nil, err
		}
		if ready != 1 {
			return nil, ErrIntegrity
		}
	}
	return releases, nil
}

func markReferenceReads(db *gorm.DB, scope types.WikiReleaseScope, releases []types.WikiRelease) error {
	for _, r := range releases {
		if err := setOwnerFormat(db, scope, "wiki_releases", "release_id", r.ID, "chunks.v1"); err != nil {
			return err
		}
		if err := setOwnerFormat(
			db, scope, "wiki_release_preparations", "preparation_id", r.PreparationID, "chunks.v1",
		); err != nil {
			return err
		}
	}
	return nil
}

// CompactLegacy removes at most one verified release's redundant copies per call.
// Repeated bounded calls finish the scope; unassociated preparations are never selected.
func (s *Store) CompactLegacy(ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope) (failure error) {
	defer func() { noteValidationFailure(db, scope, failure) }()
	return db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		sc, err := lockedScope(tx, scope, false)
		if err != nil {
			return err
		}
		if sc.Mode != "reference" || sc.ReadFailures != 0 {
			return ErrState
		}
		var ready bool
		if err := tx.Raw("SELECT observation_started_at <= CURRENT_TIMESTAMP-observation_wi"+
			"ndow_seconds*INTERVAL '1 second'\n AND read_failures=0 FROM enterp"+
			"rise_member_scopes WHERE id=?", sc.ID).Scan(&ready).Error; err != nil {
			return err
		}
		if !ready {
			return ErrState
		}
		var r types.WikiRelease
		query := exactScope(tx.Model(&types.WikiRelease{}), scope).
			Where("EXISTS(SELECT 1 FROM wiki_release_members m WHERE m.release_id=wi" +
				"ki_releases.release_id)\n   OR EXISTS(SELECT 1 FROM wiki_release_p" +
				"reparations p\n WHERE p.preparation_id=wiki_releases.preparation_i" +
				"d AND p.members<>'[]'::jsonb)").Order("release_id ASC")
		err = query.Take(&r).Error
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil
		}
		if err != nil {
			return err
		}
		if r.MemberStorage != "chunks.v1" {
			return ErrIntegrity
		}
		if err := s.verifyRelease(tx, scope, r); err != nil {
			return err
		}
		if err := tx.Where("release_id = ?", r.ID).Delete(&types.WikiReleaseMember{}).Error; err != nil {
			return err
		}
		return exactScope(tx.Table("wiki_release_preparations"), scope).
			Where("preparation_id = ?", r.PreparationID).Update("members", gorm.Expr("'[]'::jsonb")).
			Error
	})
}

// RestoreLegacy restores one complete history per bounded transaction. Mode legacy stops
// this new writer immediately; old binaries still cannot run until every marker is clear
// and migration13 can safely go down. maxBytes is a logical write budget, not free-disk proof.
func (s *Store) RestoreLegacy(
	ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope, maxBytes int64,
) (failure error) {
	defer func() { noteValidationFailure(db, scope, failure) }()
	if maxBytes <= 0 {
		return ErrState
	}
	return db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		sc, err := lockedScope(tx, scope, false)
		if err != nil {
			return err
		}
		var r types.WikiRelease
		err = exactScope(tx, scope).Where("member_storage <> ''").Order("release_id ASC").Take(&r).Error
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return tx.Model(&scopeRow{}).Where("id = ?", sc.ID).Update("mode", "legacy").Error
		}
		if err != nil {
			return err
		}
		if err := s.verifyRelease(tx, scope, r); err != nil {
			return err
		}
		root, err := releaseRoot(tx, scope, r.ID)
		if err != nil {
			return failedRead(err)
		}
		_, members, err := readLayout(tx, root, true)
		if err != nil {
			return err
		}
		prepRoot, err := preparationRoot(tx, scope, r.PreparationID)
		if err != nil {
			return failedRead(err)
		}
		_, prepared, err := readLayout(tx, prepRoot, true)
		if err != nil {
			return err
		}
		var bytes int64
		for _, list := range [][]types.WikiReleaseMemberSnapshot{members, prepared} {
			for _, m := range list {
				bytes += int64(len(m.Content) + len(m.Payload) + len(m.Kind) + len(m.LogicalSlug) +
					len(m.RevisionID) + len(m.MemberDigest) + len(m.Title))
			}
		}
		if bytes > maxBytes {
			return ErrState
		}
		// Every read and capacity check completed before the first mutation.
		if err := tx.Model(&scopeRow{}).Where("id = ?", sc.ID).Update("mode", "legacy").Error; err != nil {
			return err
		}
		if err := tx.Where("release_id = ?", r.ID).Delete(&types.WikiReleaseMember{}).Error; err != nil {
			return err
		}
		rows := make([]types.WikiReleaseMember, len(members))
		for i, m := range members {
			rows[i] = types.WikiReleaseMember{
				ID:           r.ID + ":" + m.LogicalSlug,
				ReleaseID:    r.ID,
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
			if err := tx.CreateInBatches(rows, storageBatch).Error; err != nil {
				return err
			}
		}
		raw, err := json.Marshal(prepared)
		if err != nil {
			return ErrIntegrity
		}
		if err := exactScope(tx.Table("wiki_release_preparations"), scope).
			Where("preparation_id = ?", r.PreparationID).Update("members", gorm.Expr("?::jsonb", string(raw))).
			Error; err != nil {
			return err
		}
		if err := setOwnerFormat(tx, scope, "wiki_releases", "release_id", r.ID, ""); err != nil {
			return err
		}
		if err := setOwnerFormat(
			tx, scope, "wiki_release_preparations", "preparation_id", r.PreparationID, "",
		); err != nil {
			return err
		}
		return tx.Model(&progressRow{}).Where("release_id = ?", r.ID).Update("phase", "restored").Error
	})
}

func noteValidationFailure(db *gorm.DB, scope types.WikiReleaseScope, err error) {
	if !errors.Is(err, ErrIntegrity) {
		return
	}
	ctx, cancel := context.WithTimeout(context.WithoutCancel(db.Statement.Context), time.Second)
	defer cancel()
	// Operational integrity telemetry only; never alter Head, decisions or business data.
	// Any telemetry outage is an observation gap and must restart the operator's seven-day window.
	_ = exactScope(db.Session(&gorm.Session{NewDB: true}).WithContext(ctx).Model(&scopeRow{}), scope).
		Where("observation_started_at IS NOT NULL AND read_failures = 0").
		UpdateColumn("read_failures", gorm.Expr("read_failures+1")).Error
}

type transitionOwner struct {
	ID, PreparationID            string
	ReleaseRoot, PreparationRoot []byte
}

func transitionView(
	db *gorm.DB, scope types.WikiReleaseScope, releases []types.WikiRelease,
) ([]transitionOwner, error) {
	out := make([]transitionOwner, len(releases))
	for i, r := range releases {
		root, err := releaseRoot(db, scope, r.ID)
		if err != nil {
			return nil, failedRead(err)
		}
		p, err := preparationRoot(db, scope, r.PreparationID)
		if err != nil {
			return nil, failedRead(err)
		}
		out[i] = transitionOwner{r.ID, r.PreparationID, root.Digest, p.Digest}
	}
	return out, nil
}

// Read/verify one immutable history at a time without a long scope-locking transaction.
// Storage addresses here protect migration progress from concurrent map changes; they
// are not a business/logical equality test. A changed owner set retries with no mode write.
func (s *Store) verifyTransition(
	ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope,
) ([]transitionOwner, error) {
	tx := db.WithContext(ctx)
	releases, err := verifiedOwners(tx, scope)
	if err != nil {
		return nil, err
	}
	before, err := transitionView(tx, scope, releases)
	if err != nil {
		return nil, err
	}
	for _, r := range releases {
		if err := s.verifyRelease(tx, scope, r); err != nil {
			return nil, err
		}
	}
	return before, nil
}
