package repository

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
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

// WikiReleaseRevertWrite moves Head to an existing immutable release without
// creating a replacement release or members.
type WikiReleaseRevertWrite struct {
	Scope                   types.WikiReleaseScope
	TargetReleaseID         string
	ExpectedReleaseID       string
	ExpectedActivationEpoch uint64
	Nonce                   string
	AuthorizationDigest     string
	ActivatedBy             string
	ActivatedAt             time.Time
	ActivationReceiptID     string
	CASFault                func() error
	ReceiptFault            func() error
}

// WikiReleaseRepository owns the five experimental release tables.
type WikiReleaseRepository struct {
	db *gorm.DB
}

// NewWikiReleaseRepository creates the bounded S0-R repository.
func NewWikiReleaseRepository(db *gorm.DB) *WikiReleaseRepository {
	return &WikiReleaseRepository{db: db}
}

// CreateDraft stores one complete immutable preparation for reviewer-only reads.
func (r *WikiReleaseRepository) CreateDraft(
	ctx context.Context,
	preparation *types.WikiReleasePreparation,
) error {
	if preparation == nil || preparation.Status != types.WikiReleasePreparationDraft {
		return ErrWikiReleaseConflict
	}
	return r.db.WithContext(ctx).Create(preparation).Error
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
		Where("preparation_id = ? AND status = ?", preparationID, types.WikiReleasePreparationReady).
		Take(&preparation).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, ErrWikiReleaseNotFound
	}
	return &preparation, err
}

// GetDraftPreparation returns only an immutable reviewer-visible Draft.
func (r *WikiReleaseRepository) GetDraftPreparation(
	ctx context.Context,
	scope types.WikiReleaseScope,
	preparationID string,
) (*types.WikiReleasePreparation, error) {
	var preparation types.WikiReleasePreparation
	err := scopeQuery(r.db.WithContext(ctx), scope).
		Where("preparation_id = ? AND status = ?", preparationID, types.WikiReleasePreparationDraft).
		Take(&preparation).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, ErrWikiReleaseNotFound
	}
	return &preparation, err
}

// ReviewDraft atomically moves the exact Draft to Ready after the service has
// verified the named-human receipt. No release, member, Head, or receipt row is
// created by this transition.
func (r *WikiReleaseRepository) ReviewDraft(
	ctx context.Context,
	scope types.WikiReleaseScope,
	preparationID string,
	expected *types.WikiReleasePreparation,
	reviewDecisionDigest string,
	preparationDigest string,
) (*types.WikiReleasePreparation, error) {
	if expected == nil {
		return nil, ErrWikiReleaseConflict
	}
	expectedMembers, err := json.Marshal(expected.Members)
	if err != nil {
		return nil, ErrWikiReleaseConflict
	}
	query := scopeQuery(r.db.WithContext(ctx).Model(&types.WikiReleasePreparation{}), scope).
		Where(
			"preparation_id = ? AND status = ? AND preparation_digest = ? AND "+
				"candidate_digest = ? AND manifest_digest = ? AND ready_receipt_digest = ? AND "+
				"review_policy_id = ? AND expected_release_id = ? AND expected_activation_epoch = ? AND "+
				"review_decision_digest = ?",
			preparationID,
			types.WikiReleasePreparationDraft,
			expected.PreparationDigest,
			expected.CandidateDigest,
			expected.ManifestDigest,
			expected.ReadyReceiptDigest,
			expected.ReviewPolicyID,
			expected.ExpectedReleaseID,
			expected.ExpectedActivationEpoch,
			expected.ReviewDecisionDigest,
		)
	if r.db.Dialector.Name() == "postgres" {
		query = query.Where(
			"manifest = CAST(? AS jsonb) AND members = CAST(? AS jsonb)",
			string(expected.Manifest), string(expectedMembers),
		)
	} else {
		current, currentErr := r.GetDraftPreparation(ctx, scope, preparationID)
		if currentErr != nil ||
			!wikiReleaseJSONLogicalEqual(current.Manifest, expected.Manifest) ||
			!wikiReleaseJSONLogicalEqualValue(current.Members, expected.Members) {
			return nil, ErrWikiReleaseConflict
		}
	}
	result := query.
		Updates(map[string]any{
			"review_decision_digest": reviewDecisionDigest,
			"preparation_digest":     preparationDigest,
			"status":                 types.WikiReleasePreparationReady,
		})
	if result.Error != nil {
		return nil, result.Error
	}
	if result.RowsAffected != 1 {
		return nil, ErrWikiReleaseConflict
	}
	return r.GetReadyPreparation(ctx, scope, preparationID)
}

func wikiReleaseJSONLogicalEqual(left []byte, right []byte) bool {
	leftCanonical, leftOK := wikiReleaseCanonicalJSONValue(left)
	rightCanonical, rightOK := wikiReleaseCanonicalJSONValue(right)
	return leftOK && rightOK && bytes.Equal(leftCanonical, rightCanonical)
}

func wikiReleaseJSONLogicalEqualValue(left any, right any) bool {
	leftRaw, leftErr := json.Marshal(left)
	rightRaw, rightErr := json.Marshal(right)
	return leftErr == nil && rightErr == nil && wikiReleaseJSONLogicalEqual(leftRaw, rightRaw)
}

func wikiReleaseCanonicalJSONValue(raw []byte) ([]byte, bool) {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return nil, false
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return nil, false
	}
	canonical, err := json.Marshal(value)
	return canonical, err == nil
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

// Revert atomically CASes Head to one existing immutable historical Release
// and records the same idempotency receipt shape used by activation.
func (r *WikiReleaseRepository) Revert(
	ctx context.Context,
	write WikiReleaseRevertWrite,
) (*types.WikiReleaseReceipt, error) {
	if write.TargetReleaseID == "" || write.ExpectedReleaseID == "" ||
		write.ExpectedActivationEpoch == 0 {
		return nil, ErrWikiReleaseConflict
	}
	var receipt *types.WikiReleaseReceipt
	err := r.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		var target types.WikiRelease
		if err := scopeQuery(tx, write.Scope).
			Where("release_id = ?", write.TargetReleaseID).
			Take(&target).Error; err != nil {
			if errors.Is(err, gorm.ErrRecordNotFound) {
				return ErrWikiReleaseNotFound
			}
			return err
		}
		if write.CASFault != nil {
			if err := write.CASFault(); err != nil {
				return err
			}
		}
		newEpoch := write.ExpectedActivationEpoch + 1
		result := scopeQuery(tx.Model(&types.WikiReleaseHead{}), write.Scope).
			Where("active_release_id = ? AND activation_epoch = ?",
				write.ExpectedReleaseID, write.ExpectedActivationEpoch).
			Updates(map[string]any{
				"active_release_id": write.TargetReleaseID,
				"activation_epoch":  newEpoch,
				"updated_at":        write.ActivatedAt,
			})
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected != 1 {
			return ErrWikiReleaseConflict
		}
		if write.ReceiptFault != nil {
			if err := write.ReceiptFault(); err != nil {
				return err
			}
		}
		receipt = &types.WikiReleaseReceipt{
			ID:                  write.ActivationReceiptID,
			WikiReleaseScope:    write.Scope,
			Nonce:               write.Nonce,
			AuthorizationDigest: write.AuthorizationDigest,
			PreviousReleaseID:   write.ExpectedReleaseID,
			ReleaseID:           write.TargetReleaseID,
			ActivationEpoch:     newEpoch,
			ActivatedBy:         write.ActivatedBy,
			CreatedAt:           write.ActivatedAt,
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

// GetReleaseByPreparation resolves one immutable historical target under the
// exact four-part scope.
func (r *WikiReleaseRepository) GetReleaseByPreparation(
	ctx context.Context,
	scope types.WikiReleaseScope,
	preparationID string,
) (*types.WikiRelease, error) {
	var releases []types.WikiRelease
	err := scopeQuery(r.db.WithContext(ctx), scope).
		Where("preparation_id = ?", preparationID).
		Limit(2).
		Find(&releases).Error
	if err != nil {
		return nil, err
	}
	if len(releases) == 0 {
		return nil, ErrWikiReleaseNotFound
	}
	if len(releases) != 1 {
		return nil, ErrWikiReleaseConflict
	}
	return &releases[0], nil
}

// GetRelease returns one immutable release under the exact four-part scope.
func (r *WikiReleaseRepository) GetRelease(
	ctx context.Context,
	scope types.WikiReleaseScope,
	releaseID string,
) (*types.WikiRelease, error) {
	var release types.WikiRelease
	err := scopeQuery(r.db.WithContext(ctx), scope).
		Where("release_id = ?", releaseID).
		Take(&release).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, ErrWikiReleaseNotFound
	}
	return &release, err
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

// GetHeadForWikiKB resolves the sole release scope owned by one tenant Wiki
// KB. The bounded Limit(2) lookup fails closed when persistence contains no
// binding or more than one binding; it never guesses a RAW KB or Space.
func (r *WikiReleaseRepository) GetHeadForWikiKB(
	ctx context.Context,
	tenantID uint64,
	wikiKBID string,
) (*types.WikiReleaseHead, error) {
	var heads []types.WikiReleaseHead
	err := r.db.WithContext(ctx).
		Where("tenant_id = ? AND wiki_kb_id = ?", tenantID, wikiKBID).
		Limit(2).
		Find(&heads).Error
	if err != nil {
		return nil, err
	}
	if len(heads) == 0 {
		return nil, ErrWikiReleaseNotFound
	}
	if len(heads) != 1 {
		return nil, ErrWikiReleaseConflict
	}
	return &heads[0], nil
}

// GetPreparationScopeForWikiKB resolves one immutable Draft/Ready scope
// without loading member or manifest custody. Callers must already have passed
// the human Admin and Wiki-KB authorization gates before invoking this seam.
func (r *WikiReleaseRepository) GetPreparationScopeForWikiKB(
	ctx context.Context,
	tenantID uint64,
	wikiKBID string,
	preparationID string,
) (*types.WikiReleaseScope, error) {
	var scopes []types.WikiReleaseScope
	err := r.db.WithContext(ctx).
		Table(types.WikiReleasePreparation{}.TableName()).
		Select("tenant_id", "space_id", "raw_kb_id", "wiki_kb_id").
		Where(
			"tenant_id = ? AND wiki_kb_id = ? AND preparation_id = ?",
			tenantID, wikiKBID, preparationID,
		).
		Limit(2).
		Scan(&scopes).Error
	if err != nil {
		return nil, err
	}
	if len(scopes) == 0 {
		return nil, ErrWikiReleaseNotFound
	}
	if len(scopes) != 1 {
		return nil, ErrWikiReleaseConflict
	}
	return &scopes[0], nil
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
