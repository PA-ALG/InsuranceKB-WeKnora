package releasestore

import (
	"context"
	"errors"
	"sort"
	"strings"
	"time"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

type releaseSourceRow struct {
	TenantID     uint64
	SpaceID      string
	ReleaseID    string
	KnowledgeID  string
	ParseAttempt int64
	CreatedAt    time.Time
}

func (releaseSourceRow) TableName() string { return "enterprise_release_sources" }

type retirementRow struct {
	ReleaseID string `gorm:"primaryKey"`
	TenantID  uint64
	SpaceID   string
	Reason    string
	Subject   string
	RetiredAt time.Time
}

func (retirementRow) TableName() string { return "enterprise_release_retirements" }

func sourceRefs(members []release.Member) ([]repository.RevisionRef, error) {
	seen := map[repository.RevisionRef]bool{}
	for _, member := range members {
		for _, raw := range member.EvidenceRefs {
			if !strings.HasPrefix(raw, "source:v1:") {
				continue
			}
			ref, ok := release.ParseSourceRef(raw)
			if !ok {
				return nil, repository.ErrRevisionSourceUnavailable
			}
			seen[repository.RevisionRef{KnowledgeID: ref.KnowledgeID, ParseAttempt: ref.ParseAttempt}] = true
		}
	}
	refs := make([]repository.RevisionRef, 0, len(seen))
	for ref := range seen {
		refs = append(refs, ref)
	}
	sort.Slice(refs, func(i, j int) bool {
		if refs[i].KnowledgeID != refs[j].KnowledgeID {
			return refs[i].KnowledgeID < refs[j].KnowledgeID
		}
		return refs[i].ParseAttempt < refs[j].ParseAttempt
	})
	return refs, nil
}

// Take every knowledge lock before any Head lock. Missing rows are left to the
// pin validator; retirement may release an orphaned unsealed source safely.
func lockSourceKnowledges(tx *gorm.DB, tenantID uint64, refs []repository.RevisionRef) error {
	lastID := ""
	for _, ref := range refs {
		if ref.KnowledgeID == lastID {
			continue
		}
		var knowledge types.Knowledge
		err := tx.Unscoped().Clauses(clause.Locking{Strength: "UPDATE"}).Where(
			"tenant_id = ? AND id = ?", tenantID, ref.KnowledgeID,
		).Take(&knowledge).Error
		if err != nil && !errors.Is(err, gorm.ErrRecordNotFound) {
			return err
		}
		lastID = ref.KnowledgeID
	}
	return nil
}

func lockHead(tx *gorm.DB, scope types.WikiReleaseScope) (types.WikiReleaseHead, error) {
	var head types.WikiReleaseHead
	err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).Where(
		"tenant_id = ? AND space_id = ? AND raw_kb_id = ? AND wiki_kb_id = ?",
		scope.TenantID, scope.SpaceID, scope.RawKBID, scope.WikiKBID,
	).Take(&head).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		err = nil
	}
	return head, err
}

func storeSourceLinks(tx *gorm.DB, w release.ActivationWrite, releaseID string, refs []repository.RevisionRef) error {
	for _, ref := range refs {
		if err := tx.Create(&releaseSourceRow{
			TenantID: w.TenantID, SpaceID: w.SpaceID, ReleaseID: releaseID,
			KnowledgeID: ref.KnowledgeID, ParseAttempt: ref.ParseAttempt, CreatedAt: time.Now().UTC(),
		}).Error; err != nil {
			return err
		}
	}
	return nil
}

// Retire serializes on the same knowledge/Head locks as activation. Link removal
// and last-reference release are committed together, across every Space.
func (s *Store) Retire(ctx context.Context, w release.RetirementWrite) (release.Retirement, error) {
	scope, err := s.spaces.Scope(w.TenantID, w.SpaceID)
	if err != nil {
		return release.Retirement{}, err
	}
	var record retirementRow
	err = s.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if _, err := repository.NewWikiReleaseRepository(tx).GetRelease(ctx, scope, w.ReleaseID); err != nil {
			return notFound(err)
		}
		var sources []releaseSourceRow
		if err := tx.Where("tenant_id = ? AND space_id = ? AND release_id = ?",
			w.TenantID, w.SpaceID, w.ReleaseID).Order("knowledge_id, parse_attempt").Find(&sources).Error; err != nil {
			return err
		}
		refs := make([]repository.RevisionRef, 0, len(sources))
		for _, source := range sources {
			refs = append(refs, repository.RevisionRef{
				KnowledgeID: source.KnowledgeID, ParseAttempt: source.ParseAttempt,
			})
		}
		if err := lockSourceKnowledges(tx, w.TenantID, refs); err != nil {
			return err
		}
		for _, ref := range refs {
			var row types.KnowledgeRevisionSource
			err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).Where(
				"tenant_id = ? AND knowledge_id = ? AND parse_attempt = ?",
				w.TenantID, ref.KnowledgeID, ref.ParseAttempt,
			).Take(&row).Error
			if err != nil && !errors.Is(err, gorm.ErrRecordNotFound) {
				return err
			}
		}
		head, err := lockHead(tx, scope)
		if err != nil {
			return err
		}
		if head.ActiveReleaseID == w.ReleaseID {
			return &release.Error{Code: release.ErrorReleaseActive, Detail: "the active release cannot be retired"}
		}
		err = tx.Where("tenant_id = ? AND space_id = ? AND release_id = ?",
			w.TenantID, w.SpaceID, w.ReleaseID).Take(&record).Error
		if err == nil {
			return nil
		}
		if !errors.Is(err, gorm.ErrRecordNotFound) {
			return err
		}
		record = retirementRow{
			TenantID: w.TenantID, SpaceID: w.SpaceID, ReleaseID: w.ReleaseID,
			Reason: w.Reason, Subject: w.Subject, RetiredAt: s.now().UTC().Truncate(time.Microsecond),
		}
		if err := tx.Create(&record).Error; err != nil {
			return err
		}
		if err := tx.Where("tenant_id = ? AND space_id = ? AND release_id = ?",
			w.TenantID, w.SpaceID, w.ReleaseID).Delete(&releaseSourceRow{}).Error; err != nil {
			return err
		}
		unreferenced := make([]repository.RevisionRef, 0, len(refs))
		for _, ref := range refs {
			var remaining int64
			if err := tx.Model(&releaseSourceRow{}).Where("knowledge_id = ? AND parse_attempt = ?",
				ref.KnowledgeID, ref.ParseAttempt).Count(&remaining).Error; err != nil {
				return err
			}
			if remaining == 0 {
				unreferenced = append(unreferenced, ref)
			}
		}
		return repository.ReleaseRevisionSources(tx, w.TenantID, unreferenced)
	})
	return release.Retirement{
		ReleaseID: record.ReleaseID, Reason: record.Reason, Subject: record.Subject, RetiredAt: record.RetiredAt.UTC(),
	}, err
}

// SourcePins lists unretired release links within the configured Space.
func (s *Store) SourcePins(
	ctx context.Context, tenantID uint64, spaceID, knowledgeID string,
) ([]release.SourcePin, error) {
	scope, err := s.spaces.Scope(tenantID, spaceID)
	if err != nil {
		return nil, err
	}
	pins := make([]release.SourcePin, 0)
	err = s.db.WithContext(ctx).Table("enterprise_release_sources AS s").
		Select("s.release_id, s.parse_attempt, (h.active_release_id = s.release_id) AS active").
		Joins(`JOIN wiki_release_heads AS h ON h.tenant_id = s.tenant_id AND h.space_id = s.space_id
AND h.raw_kb_id = ? AND h.wiki_kb_id = ?`, scope.RawKBID, scope.WikiKBID).
		Joins("LEFT JOIN enterprise_release_retirements AS r ON r.release_id = s.release_id").
		Where("s.tenant_id = ? AND s.space_id = ? AND s.knowledge_id = ? AND r.release_id IS NULL",
			tenantID, spaceID, knowledgeID).Order("s.release_id, s.parse_attempt").Scan(&pins).Error
	return pins, err
}

func (s *Store) retiredAt(ctx context.Context, scope types.WikiReleaseScope, releaseID string) (*time.Time, error) {
	var record retirementRow
	err := s.db.WithContext(ctx).Where("tenant_id = ? AND space_id = ? AND release_id = ?",
		scope.TenantID, scope.SpaceID, releaseID).Take(&record).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	retiredAt := record.RetiredAt.UTC()
	return &retiredAt, nil
}
