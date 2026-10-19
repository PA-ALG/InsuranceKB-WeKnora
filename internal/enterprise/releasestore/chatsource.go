package releasestore

import (
	"context"
	"errors"

	"github.com/Tencent/WeKnora/internal/enterprise/chatsource"
	"github.com/Tencent/WeKnora/internal/types"
)

// SpaceOwner classifies KB identity from the complete deployment configuration.
// It grants no read access and is used before fallible native metadata lookups.
func (s Spaces) SpaceOwner(kbID string) (uint64, string, chatsource.Role, bool) {
	for _, scope := range s.byKey {
		if scope.RawKBID == kbID {
			return scope.TenantID, scope.SpaceID, chatsource.RoleRaw, true
		}
		if scope.WikiKBID == kbID {
			return scope.TenantID, scope.SpaceID, chatsource.RoleWiki, true
		}
	}
	return 0, "", "", false
}

// ActiveRelease delegates to the existing authoritative Head implementation.
func (s *Store) ActiveRelease(ctx context.Context, tenantID uint64, spaceID string) (string, error) {
	if s == nil || s.db == nil {
		return "", errors.New("chat source store is unavailable")
	}
	head, err := s.Head(ctx, tenantID, spaceID)
	return head.ReleaseID, err
}

// ReleaseSources reads the exact historical release scope and its live RAW
// materials. Retired releases yield no sources; nonexistent releases are errors.
func (s *Store) ReleaseSources(ctx context.Context, tenantID uint64, spaceID, releaseID string) ([]chatsource.Pin, error) {
	if s == nil || s.db == nil {
		return nil, errors.New("chat source store is unavailable")
	}
	scope, err := s.spaces.Scope(tenantID, spaceID)
	if err != nil {
		return nil, err
	}
	if _, err := s.releases.GetRelease(ctx, scope, releaseID); err != nil {
		return nil, notFound(err)
	}
	var pins []chatsource.Pin
	err = s.db.WithContext(ctx).Table("enterprise_release_sources AS s").
		Select("s.knowledge_id, s.parse_attempt").
		Joins("JOIN knowledges AS k ON k.id = s.knowledge_id AND k.tenant_id = s.tenant_id AND k.knowledge_base_id = ? AND k.deleted_at IS NULL", scope.RawKBID).
		Joins("LEFT JOIN enterprise_release_retirements AS r ON r.release_id = s.release_id AND r.tenant_id = s.tenant_id AND r.space_id = s.space_id").
		Where("s.tenant_id = ? AND s.space_id = ? AND s.release_id = ? AND r.release_id IS NULL", tenantID, spaceID, releaseID).
		Order("s.knowledge_id, s.parse_attempt").Scan(&pins).Error
	return pins, err
}

// CurrentAttempts excludes soft-deleted knowledge and never crosses tenants.
func (s *Store) CurrentAttempts(ctx context.Context, tenantID uint64, knowledgeIDs []string) (map[string]int64, error) {
	if s == nil || s.db == nil {
		return nil, errors.New("chat source store is unavailable")
	}
	attempts := map[string]int64{}
	if len(knowledgeIDs) == 0 {
		return attempts, nil
	}
	var rows []types.Knowledge
	err := s.db.WithContext(ctx).Select("id", "current_parse_attempt").
		Where("tenant_id = ? AND id IN ?", tenantID, knowledgeIDs).Find(&rows).Error
	if err != nil {
		return nil, err
	}
	for _, row := range rows {
		attempts[row.ID] = row.CurrentParseAttempt
	}
	return attempts, nil
}
