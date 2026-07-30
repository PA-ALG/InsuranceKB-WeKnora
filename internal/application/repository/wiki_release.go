package repository

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
	"gorm.io/gorm"
)

var (
	// ErrWikiReleaseNotFound is returned for absent release state.
	ErrWikiReleaseNotFound = errors.New("wiki release state not found")
	// ErrWikiReleaseConflict is returned when expected head/epoch loses CAS.
	ErrWikiReleaseConflict = errors.New("wiki release head conflict")
)

// WikiReleaseActivationWrite is the bounded repository transaction input.
type WikiReleaseActivationWrite struct {
	Release                   *types.WikiRelease
	Members                   []types.WikiReleaseMemberSnapshot
	ExpectedReleaseID         string
	ExpectedActivationEpoch   uint64
	Nonce                     string
	AuthorizationDigest       string
	ActivatedBy               string
	ActivatedAt               time.Time
	ActivationReceiptID       string
	ExpectedPreparationID     string
	ExpectedPreparationDigest string
	CASFault                  func() error
	ReceiptFault              func() error
}

// WikiReleaseRepository owns the five experimental release tables.
type WikiReleaseRepository struct {
	db *gorm.DB
}

// NewWikiReleaseRepository creates the bounded S0-R repository.
func NewWikiReleaseRepository(db *gorm.DB) *WikiReleaseRepository {
	return &WikiReleaseRepository{db: db}
}

// CreateReadyPreparation stores the complete frozen preparation.
func (r *WikiReleaseRepository) CreateReadyPreparation(
	ctx context.Context,
	preparation *types.WikiReleasePreparation,
) error {
	return r.db.WithContext(ctx).Create(preparation).Error
}

// GetReadyPreparation returns the exact scope preparation.
func (r *WikiReleaseRepository) GetReadyPreparation(
	ctx context.Context,
	scope types.WikiReleaseScope,
	preparationID string,
) (*types.WikiReleasePreparation, error) {
	var preparation types.WikiReleasePreparation
	err := scopeQuery(r.db.WithContext(ctx), scope).
		Where("preparation_id = ?", preparationID).
		Take(&preparation).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, ErrWikiReleaseNotFound
	}
	return &preparation, err
}

// Activate writes release, members, CAS head, and receipt in one transaction.
func (r *WikiReleaseRepository) Activate(
	ctx context.Context,
	write WikiReleaseActivationWrite,
) (*types.WikiReleaseReceipt, error) {
	if write.Release == nil {
		return nil, errors.New("nil wiki release")
	}
	var receipt *types.WikiReleaseReceipt
	err := r.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		head, err := getHead(tx, write.Release.WikiReleaseScope)
		switch {
		case err == nil:
			if head.ActiveReleaseID != write.ExpectedReleaseID ||
				head.ActivationEpoch != write.ExpectedActivationEpoch {
				return ErrWikiReleaseConflict
			}
		case errors.Is(err, ErrWikiReleaseNotFound):
			if write.ExpectedReleaseID != "" || write.ExpectedActivationEpoch != 0 {
				return ErrWikiReleaseConflict
			}
			head = nil
		default:
			return err
		}

		if err := tx.Create(write.Release).Error; err != nil {
			return err
		}
		members := materializeMembers(write.Release.ID, write.Members)
		if len(members) > 0 {
			if err := tx.Create(&members).Error; err != nil {
				return err
			}
		}
		if write.CASFault != nil {
			if err := write.CASFault(); err != nil {
				return err
			}
		}

		newEpoch := write.ExpectedActivationEpoch + 1
		if head == nil {
			head = &types.WikiReleaseHead{
				ID:               headIdentity(write.Release.WikiReleaseScope),
				WikiReleaseScope: write.Release.WikiReleaseScope,
				ActiveReleaseID:  write.Release.ID,
				ActivationEpoch:  newEpoch,
				UpdatedAt:        write.Release.ActivatedAt,
			}
			if err := tx.Create(head).Error; err != nil {
				return fmt.Errorf("%w: %v", ErrWikiReleaseConflict, err)
			}
		} else {
			result := scopeQuery(tx.Model(&types.WikiReleaseHead{}), write.Release.WikiReleaseScope).
				Where("active_release_id = ? AND activation_epoch = ?",
					write.ExpectedReleaseID, write.ExpectedActivationEpoch).
				Updates(map[string]any{
					"active_release_id": write.Release.ID,
					"activation_epoch":  newEpoch,
					"updated_at":        write.Release.ActivatedAt,
				})
			if result.Error != nil {
				return result.Error
			}
			if result.RowsAffected != 1 {
				return ErrWikiReleaseConflict
			}
		}
		if write.ReceiptFault != nil {
			if err := write.ReceiptFault(); err != nil {
				return err
			}
		}

		previousReleaseID := write.ExpectedReleaseID
		receipt = &types.WikiReleaseReceipt{
			ID:                  write.ActivationReceiptID,
			WikiReleaseScope:    write.Release.WikiReleaseScope,
			Nonce:               write.Nonce,
			AuthorizationDigest: write.AuthorizationDigest,
			PreviousReleaseID:   previousReleaseID,
			ReleaseID:           write.Release.ID,
			ActivationEpoch:     newEpoch,
			ActivatedBy:         write.ActivatedBy,
			CreatedAt:           write.Release.ActivatedAt,
		}
		return tx.Create(receipt).Error
	})
	return receipt, err
}

func materializeMembers(
	releaseID string,
	snapshots []types.WikiReleaseMemberSnapshot,
) []types.WikiReleaseMember {
	members := make([]types.WikiReleaseMember, 0, len(snapshots))
	for _, snapshot := range snapshots {
		kind := snapshot.Kind
		if kind == "" {
			kind = "page"
		}
		members = append(members, types.WikiReleaseMember{
			ID:           releaseID + ":" + snapshot.LogicalSlug,
			ReleaseID:    releaseID,
			Kind:         kind,
			LogicalSlug:  snapshot.LogicalSlug,
			RevisionID:   snapshot.RevisionID,
			MemberDigest: snapshot.MemberDigest,
			Title:        snapshot.Title,
			Content:      snapshot.Content,
			Payload:      append([]byte(nil), snapshot.Payload...),
		})
	}
	return members
}

func headIdentity(scope types.WikiReleaseScope) string {
	return strconv.FormatUint(scope.TenantID, 10) + ":" + scope.SpaceID + ":" + scope.WikiKBID
}

func scopeQuery(db *gorm.DB, scope types.WikiReleaseScope) *gorm.DB {
	return db.Where(
		"tenant_id = ? AND space_id = ? AND raw_kb_id = ? AND wiki_kb_id = ?",
		scope.TenantID,
		scope.SpaceID,
		scope.RawKBID,
		scope.WikiKBID,
	)
}

func getHead(db *gorm.DB, scope types.WikiReleaseScope) (*types.WikiReleaseHead, error) {
	var head types.WikiReleaseHead
	err := scopeQuery(db, scope).Take(&head).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, ErrWikiReleaseNotFound
	}
	return &head, err
}

// GetHead returns the sole current head.
func (r *WikiReleaseRepository) GetHead(
	ctx context.Context,
	scope types.WikiReleaseScope,
) (*types.WikiReleaseHead, error) {
	return getHead(r.db.WithContext(ctx), scope)
}

// GetHeadForSpace returns the single active head binding for one tenant and
// Space without weakening exact-scope reads.
func (r *WikiReleaseRepository) GetHeadForSpace(
	ctx context.Context,
	tenantID uint64,
	spaceID string,
) (*types.WikiReleaseHead, error) {
	var head types.WikiReleaseHead
	err := r.db.WithContext(ctx).
		Where("tenant_id = ? AND space_id = ?", tenantID, spaceID).
		Take(&head).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, ErrWikiReleaseNotFound
	}
	return &head, err
}

// GetReceipt returns the frozen idempotency identity for one Space, Wiki KB,
// and nonce. Tenant/RAW drift is detected by the full authorization digest.
func (r *WikiReleaseRepository) GetReceipt(
	ctx context.Context,
	scope types.WikiReleaseScope,
	nonce string,
) (*types.WikiReleaseReceipt, error) {
	var receipt types.WikiReleaseReceipt
	err := r.db.WithContext(ctx).
		Where("space_id = ? AND wiki_kb_id = ? AND nonce = ?", scope.SpaceID, scope.WikiKBID, nonce).
		Take(&receipt).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, ErrWikiReleaseNotFound
	}
	return &receipt, err
}

// GetReleaseMembers returns only immutable members of the requested release.
func (r *WikiReleaseRepository) GetReleaseMembers(
	ctx context.Context,
	scope types.WikiReleaseScope,
	releaseID string,
) ([]types.WikiReleaseMemberSnapshot, error) {
	var release types.WikiRelease
	err := scopeQuery(r.db.WithContext(ctx), scope).
		Where("release_id = ?", releaseID).
		Take(&release).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, ErrWikiReleaseNotFound
	}
	if err != nil {
		return nil, err
	}
	var rows []types.WikiReleaseMember
	if err := r.db.WithContext(ctx).
		Where("release_id = ?", releaseID).
		Order("logical_slug ASC").
		Find(&rows).Error; err != nil {
		return nil, err
	}
	members := make([]types.WikiReleaseMemberSnapshot, 0, len(rows))
	for _, row := range rows {
		members = append(members, row.Snapshot())
	}
	return members, nil
}

// IsManagedWikiKB reports whether the experimental release state owns the KB.
func (r *WikiReleaseRepository) IsManagedWikiKB(
	ctx context.Context,
	scope types.WikiReleaseScope,
) (bool, error) {
	var count int64
	err := scopeQuery(r.db.WithContext(ctx).Model(&types.WikiReleasePreparation{}), scope).
		Count(&count).Error
	return count > 0, err
}

// HasActiveHeadForWikiKB reports whether ordinary Wiki mutations must be
// guarded for the tenant-scoped KB. Preparations alone do not make a KB
// release-managed.
func (r *WikiReleaseRepository) HasActiveHeadForWikiKB(
	ctx context.Context,
	tenantID uint64,
	wikiKBID string,
) (bool, error) {
	var count int64
	err := r.db.WithContext(ctx).
		Model(&types.WikiReleaseHead{}).
		Where("tenant_id = ? AND wiki_kb_id = ?", tenantID, wikiKBID).
		Count(&count).Error
	return count > 0, err
}

// CountState returns bounded per-table row counts for falsification tests.
func (r *WikiReleaseRepository) CountState(
	ctx context.Context,
) (types.WikiReleaseStateCount, error) {
	var state types.WikiReleaseStateCount
	counts := []struct {
		model any
		out   *int64
	}{
		{&types.WikiReleasePreparation{}, &state.Preparations},
		{&types.WikiRelease{}, &state.Releases},
		{&types.WikiReleaseMember{}, &state.Members},
		{&types.WikiReleaseHead{}, &state.Heads},
		{&types.WikiReleaseReceipt{}, &state.Receipts},
	}
	for _, count := range counts {
		if err := r.db.WithContext(ctx).Model(count.model).Count(count.out).Error; err != nil {
			return types.WikiReleaseStateCount{}, err
		}
	}
	return state, nil
}
