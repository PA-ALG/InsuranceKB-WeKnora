package memberstore

import (
	"context"

	"github.com/Tencent/WeKnora/internal/types"
	"gorm.io/gorm"
)

// Read verifies a complete snapshot within a durable validation reservation.
func (s *Store) Read(
	ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope, id string,
) (out []types.WikiReleaseMemberSnapshot, err error) {
	err = s.Validate(ctx, db, scope, func(ctx context.Context) error {
		out, err = s.readValidated(ctx, db, scope, id)
		return err
	})
	if err != nil {
		out = nil
	}
	return
}

// Digests reserves observation only for formats whose index is integrity-checked.
// The original legacy metadata-only path neither checks content nor changes its queries.
func (s *Store) Digests(
	ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope, id string,
) (out map[string]string, err error) {
	header, err := releaseHeader(db.WithContext(ctx), scope, id)
	if err != nil {
		return nil, err
	}
	read := func(ctx context.Context) error { out, err = s.digestsValidated(ctx, db, scope, id, header); return err }
	if header.MemberStorage == "" || header.MemberStorage == "bridge.v1" {
		err = read(ctx)
	} else {
		err = s.Validate(ctx, db, scope, read)
	}
	if err != nil {
		out = nil
	}
	return
}

// Put reserves validation independently of the enclosing activation transaction. A failed
// parent/preimage validation remains visible even when activation rolls back.
func (s *Store) Put(ctx context.Context, db *gorm.DB, w types.WikiReleaseMemberSetWrite) error {
	return s.Validate(ctx, db, w.Scope, func(ctx context.Context) error { return s.putValidated(ctx, db, w) })
}

// Backfill certifies a history without hiding failures behind its bounded transactions.
func (s *Store) Backfill(
	ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope, id string, maxBytes int64,
) error {
	return s.Validate(ctx, db, scope, func(ctx context.Context) error {
		return s.backfillValidated(ctx, db, scope, id, maxBytes)
	})
}

// StartObservation verifies histories and starts a fresh window only with no unresolved gaps.
func (s *Store) StartObservation(ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope) error {
	return s.Validate(ctx, db, scope, func(ctx context.Context) error { return s.startObservation(ctx, db, scope) })
}

// ReferenceOnly requires the durable clean observation before the original transaction commits.
func (s *Store) ReferenceOnly(ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope) error {
	return s.Validate(ctx, db, scope, func(ctx context.Context) error { return s.referenceOnly(ctx, db, scope) })
}

// CompactLegacy removes at most one history after recording its validation outcome.
func (s *Store) CompactLegacy(ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope) error {
	return s.Validate(ctx, db, scope, func(ctx context.Context) error { return s.compactLegacy(ctx, db, scope) })
}

// RestoreLegacy pauses this scope's publication until down and old-binary replacement.
func (s *Store) RestoreLegacy(ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope, maxBytes int64) error {
	return s.Validate(ctx, db, scope, func(ctx context.Context) error {
		return s.restoreLegacy(ctx, db, scope, maxBytes)
	})
}
