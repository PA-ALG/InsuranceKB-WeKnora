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

// releaseMemberInsertBatch keeps each member INSERT below the bind-parameter limits:
// PostgreSQL allows 65535 per statement (SQLite 32766) and a member row binds nine, so a
// release of more than 7281 members could not activate as one statement (#563, 2026-11-13).
// The batches run inside the activation transaction, which stays all-or-nothing.
const releaseMemberInsertBatch = 1000

// WikiReleaseActivationWrite is the bounded repository transaction input.
type WikiReleaseActivationWrite struct {
	Preparation                 *types.WikiReleasePreparation
	Release                     *types.WikiRelease
	Members                     []types.WikiReleaseMemberSnapshot
	ExpectedReleaseID           string
	ExpectedActivationEpoch     uint64
	Nonce                       string
	AuthorizationDigest         string
	ActivatedBy                 string
	ActivatedAt                 time.Time
	ActivationReceiptID         string
	ExpectedPreparationID       string
	ExpectedPreparationDigest   string
	RequireInitialWikiKBUnbound bool
	CASFault                    func() error
	ReceiptFault                func() error
}

// WikiReleaseMemberStorage isolates persistence layout from logical member equality.
type WikiReleaseMemberStorage interface {
	Put(context.Context, *gorm.DB, types.WikiReleaseMemberSetWrite) error
	Read(context.Context, *gorm.DB, types.WikiReleaseScope, string) ([]types.WikiReleaseMemberSnapshot, error)
	Digests(context.Context, *gorm.DB, types.WikiReleaseScope, string) (map[string]string, error)
}

// WikiReleaseRepository owns the five experimental release tables.
type WikiReleaseRepository struct {
	db      *gorm.DB
	members WikiReleaseMemberStorage
}

// NewWikiReleaseRepository creates the bounded S0-R repository.
func NewWikiReleaseRepository(db *gorm.DB) *WikiReleaseRepository {
	return &WikiReleaseRepository{db: db}
}

// WithMemberStorage returns an independent adapter; it never changes a shared repository.
func (r *WikiReleaseRepository) WithMemberStorage(storage WikiReleaseMemberStorage) *WikiReleaseRepository {
	configured := *r
	configured.members = storage
	return &configured
}

func wikiReleaseJSONLogicalEqual(left []byte, right []byte) bool {
	leftCanonical, leftOK := wikiReleaseCanonicalJSONValue(left)
	rightCanonical, rightOK := wikiReleaseCanonicalJSONValue(right)
	return leftOK && rightOK && bytes.Equal(leftCanonical, rightCanonical)
}

func wikiReleaseJSONLogicalEqualValue(left any, right any) bool {
	a, aOK := left.([]types.WikiReleaseMemberSnapshot)
	b, bOK := right.([]types.WikiReleaseMemberSnapshot)
	if aOK && bOK && identicalSnapshotValues(a, b) {
		return true
	}

	leftRaw, leftErr := json.Marshal(left)
	rightRaw, rightErr := json.Marshal(right)
	return leftErr == nil && rightErr == nil && wikiReleaseJSONLogicalEqual(leftRaw, rightRaw)
}

// Identical seven-field values prove equality without encoding both complete bodies.
// Any differing representation falls back to the original JSON logical comparison.
func identicalSnapshotValues(a, b []types.WikiReleaseMemberSnapshot) bool {
	if len(a) != len(b) || (a == nil) != (b == nil) {
		return false
	}
	for i, x := range a {
		y := b[i]
		if x.Kind != y.Kind || x.LogicalSlug != y.LogicalSlug || x.RevisionID != y.RevisionID ||
			x.MemberDigest != y.MemberDigest || x.Title != y.Title || x.Content != y.Content {
			return false
		}
		if x.Payload == nil && y.Payload == nil {
			continue
		}
		if !bytes.Equal(x.Payload, y.Payload) || !json.Valid(x.Payload) {
			return false
		}
	}
	return true
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
		if write.RequireInitialWikiKBUnbound {
			var headCount int64
			if err := tx.Model(&types.WikiReleaseHead{}).
				Where("tenant_id = ? AND wiki_kb_id = ?", write.Release.TenantID, write.Release.WikiKBID).
				Count(&headCount).Error; err != nil {
				return err
			}
			if headCount != 0 {
				return ErrWikiReleaseConflict
			}
		}
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
		if write.Preparation != nil {
			preparation := *write.Preparation
			if preparation.ID == "" || preparation.ID != write.Release.PreparationID ||
				preparation.WikiReleaseScope != write.Release.WikiReleaseScope ||
				preparation.Status != types.WikiReleasePreparationReady ||
				preparation.CandidateDigest != write.Release.CandidateDigest ||
				preparation.ManifestDigest != write.Release.ManifestDigest ||
				preparation.ExpectedReleaseID != write.ExpectedReleaseID ||
				preparation.ExpectedActivationEpoch != write.ExpectedActivationEpoch ||
				preparation.ID != write.ExpectedPreparationID ||
				preparation.PreparationDigest != write.ExpectedPreparationDigest ||
				!wikiReleaseJSONLogicalEqualValue(preparation.Members, write.Members) {
				return ErrWikiReleaseConflict
			}
			if r.members != nil {
				// The port writes the bridge copy only when required, in this transaction.
				preparation.Members = []types.WikiReleaseMemberSnapshot{}
			}
			if err := tx.Create(&preparation).Error; err != nil {
				return err
			}
		}

		if err := tx.Create(write.Release).Error; err != nil {
			return err
		}
		if r.members != nil {
			if write.Preparation == nil {
				return ErrWikiReleaseConflict
			}
			if err := r.members.Put(ctx, tx, types.WikiReleaseMemberSetWrite{
				Scope: write.Release.WikiReleaseScope, PreparationID: write.Release.PreparationID,
				ReleaseID: write.Release.ID, ParentReleaseID: write.ExpectedReleaseID,
				Members: normalizedMemberKinds(write.Members),
			}); err != nil {
				return err
			}
		} else {
			members := materializeMembers(write.Release.ID, write.Members)
			if len(members) > 0 {
				if err := tx.CreateInBatches(&members, releaseMemberInsertBatch).Error; err != nil {
					return err
				}
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
	if r.members != nil {
		snapshots, err := r.members.Read(ctx, r.db, scope, releaseID)
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrWikiReleaseNotFound
		}
		return snapshots, err
	}
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
	if release.MemberStorage != "" {
		return nil, errors.New("member storage adapter required")
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

func normalizedMemberKinds(input []types.WikiReleaseMemberSnapshot) []types.WikiReleaseMemberSnapshot {
	out := make([]types.WikiReleaseMemberSnapshot, len(input))
	copy(out, input)
	for i := range out {
		if out[i].Kind == "" {
			out[i].Kind = "page"
		}
	}
	return out
}

// GetReleaseMemberDigests keeps the no-body path behind the same immutable storage boundary.
func (r *WikiReleaseRepository) GetReleaseMemberDigests(
	ctx context.Context, scope types.WikiReleaseScope, id string,
) (map[string]string, error) {
	if r.members != nil {
		out, err := r.members.Digests(ctx, r.db, scope, id)
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrWikiReleaseNotFound
		}
		return out, err
	}
	release, err := r.GetRelease(ctx, scope, id)
	if err != nil {
		return nil, err
	}
	if release.MemberStorage != "" {
		return nil, errors.New("member storage adapter required")
	}
	var rows []struct{ LogicalSlug, MemberDigest string }
	if err := r.db.WithContext(ctx).Model(&types.WikiReleaseMember{}).Select("logical_slug", "member_digest").
		Where("release_id = ?", id).Order("logical_slug ASC").Scan(&rows).Error; err != nil {
		return nil, err
	}
	out := make(map[string]string, len(rows))
	for _, row := range rows {
		out[row.LogicalSlug] = row.MemberDigest
	}
	return out, nil
}
