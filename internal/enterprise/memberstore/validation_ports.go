package memberstore

import (
	"context"
	"errors"

	"github.com/Tencent/WeKnora/internal/types"
	"gorm.io/gorm"
)

type readSelectionKey struct{}

type readSelection struct {
	scope  types.WikiReleaseScope
	header types.WikiRelease
}

// ValidateRead binds format selection to the complete producer read. A nested Read
// reuses only this exact scope/release selection, so transitions cannot end the ticket
// before producer decoding or cause a second format decision inside the same read.
func (s *Store) ValidateRead(
	ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope, id string, fn func(context.Context) error,
) error {
	if selected, ok := ctx.Value(readSelectionKey{}).(readSelection); ok &&
		selected.scope == scope && selected.header.ID == id {
		return fn(ctx)
	}
	header, err := releaseHeader(db.WithContext(ctx), scope, id)
	if err != nil {
		s.RecordReadFailure(ctx, db, scope, id, err)
		return err
	}
	selected := context.WithValue(ctx, readSelectionKey{}, readSelection{scope, header})
	switch header.MemberStorage {
	case "", "bridge.v1":
		return fn(selected)
	case "chunks.v1":
		return s.Validate(selected, db, scope, fn)
	default:
		return s.Validate(selected, db, scope, func(context.Context) error { return ErrIntegrity })
	}
}

// Read preserves the legacy read-only path; observed reads retain a durable ticket.
func (s *Store) Read(
	ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope, id string,
) (out []types.WikiReleaseMemberSnapshot, err error) {
	err = s.ValidateRead(ctx, db, scope, id, func(ctx context.Context) error {
		selected := ctx.Value(readSelectionKey{}).(readSelection)
		out, err = s.readValidated(ctx, db, scope, selected.header)
		return err
	})
	if err != nil {
		out = nil
	}
	return
}

// RecordReadFailure preserves a gap when a canceled/aborted caller cannot read routing metadata. A bounded
// root-pool lookup may identify the SAME release as observed and record that gap;
// it never supplies member bytes, substitutes a Head or turns the original error into success.
func (s *Store) RecordReadFailure(
	ctx context.Context, db *gorm.DB, scope types.WikiReleaseScope, id string, failure error,
) {
	if failure == nil || id == "" {
		return
	}
	if a, ok := ctx.Value(validationKey{}).(*validationAttempt); ok && a.scope == scope {
		return // The existing enclosing reservation records this error.
	}
	if errors.Is(failure, gorm.ErrRecordNotFound) {
		return
	}
	if !s.journal.valid() {
		_ = journalError(ctx)
		return
	}
	bounded, cancel := s.journal.readContext(ctx)
	defer cancel()
	header, err := releaseHeader(journalPool(db).WithContext(bounded), scope, id)
	if err == nil && header.MemberStorage != "" && header.MemberStorage != "bridge.v1" {
		// This callback only records the original failure; it does no business work.
		// An already-canceled request must not replace its classification with a gap.
		_ = s.Validate(context.WithoutCancel(ctx), db, scope, func(context.Context) error { return failure })
	}
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
