// Package managed is the sole release-custody classifier for ordinary writes.
package managed

import (
	"context"
	"errors"
	"strings"

	"github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"gorm.io/gorm"
)

type (
	// Kind identifies the knowledge base's role in a release scope.
	Kind string
	// State identifies the release custody lifecycle.
	State string
)

// Release roles and states describe whether ordinary writes are permitted.
const (
	KindNone       Kind  = "none"
	KindWiki       Kind  = "wiki"
	KindRaw        Kind  = "raw"
	StateUnmanaged State = "unmanaged"
	StatePending   State = "pending"
	StateActive    State = "active"
)

// Role is the classification result, including the matching scope when managed.
type Role struct {
	Kind  Kind
	State State
	Scope *types.WikiReleaseScope
}

// Classifier resolves release custody under the authoritative KB tenant.
type Classifier interface {
	Classify(context.Context, uint64, string) (Role, error)
}

// HeadLookup reads the existing release authority without introducing a second Head.
type HeadLookup interface {
	GetHeadForWikiKB(context.Context, uint64, string) (*types.WikiReleaseHead, error)
}

// CustodyLookup finds persisted scope ownership, including scopes missing a Head.
type CustodyLookup interface {
	FindScopes(context.Context, uint64, string) ([]types.WikiReleaseScope, error)
}

type classifier struct {
	heads   HeadLookup
	custody CustodyLookup
}

// NewClassifier combines the existing Head authority and release custody lookup.
func NewClassifier(heads HeadLookup, custody CustodyLookup) Classifier {
	return &classifier{heads: heads, custody: custody}
}

func (c *classifier) Classify(ctx context.Context, tenantID uint64, kbID string) (Role, error) {
	kbID = strings.TrimSpace(kbID)
	if tenantID == 0 || kbID == "" || c == nil || c.heads == nil || c.custody == nil {
		return Role{}, errors.New("managed classification dependencies or identity unavailable")
	}
	head, headErr := c.heads.GetHeadForWikiKB(ctx, tenantID, kbID)
	if headErr != nil && !errors.Is(headErr, repository.ErrWikiReleaseNotFound) {
		return Role{}, headErr
	}
	if headErr == nil && head == nil {
		return Role{}, errors.New("release head lookup returned no result")
	}
	scopes, err := c.custody.FindScopes(ctx, tenantID, kbID)
	if err != nil {
		return Role{}, err
	}
	if headErr == nil {
		scopes = append(scopes, head.WikiReleaseScope)
	}
	best := Role{Kind: KindNone, State: StateUnmanaged}
	for _, scope := range scopes {
		if scope.TenantID != tenantID || scope.SpaceID == "" || scope.RawKBID == "" || scope.WikiKBID == "" {
			return Role{}, errors.New("invalid release custody scope")
		}
		kind := KindRaw
		if scope.WikiKBID == kbID {
			kind = KindWiki
		} else if scope.RawKBID != kbID {
			return Role{}, errors.New("release custody does not match knowledge base")
		}
		state := StatePending
		head, err := c.heads.GetHeadForWikiKB(ctx, tenantID, scope.WikiKBID)
		if err != nil && !errors.Is(err, repository.ErrWikiReleaseNotFound) {
			return Role{}, err
		}
		if err == nil {
			if head == nil || head.WikiReleaseScope != scope {
				return Role{}, errors.New("release head does not match custody scope")
			}
			if head.ActiveReleaseID != "" && head.ActivationEpoch > 0 {
				state = StateActive
			}
		}
		if best.State == StateUnmanaged || (kind == KindWiki && best.Kind == KindRaw) ||
			(kind == best.Kind && state == StateActive && best.State != StateActive) {
			selected := scope
			best = Role{Kind: kind, State: state, Scope: &selected}
		}
	}
	return best, nil
}

type custodyLookup struct{ db *gorm.DB }

// NewCustodyLookup reads the four existing release tables in the platform store.
func NewCustodyLookup(db *gorm.DB) CustodyLookup { return &custodyLookup{db: db} }

// FindScopes uses all four custody tables so losing a Head never reopens writes.
// Distinct scopes avoid fetching a row for every historical release or receipt.
func (c *custodyLookup) FindScopes(
	ctx context.Context, tenantID uint64, kbID string,
) ([]types.WikiReleaseScope, error) {
	if c == nil || c.db == nil || tenantID == 0 || strings.TrimSpace(kbID) == "" {
		return nil, errors.New("release custody database or identity unavailable")
	}
	tables := []string{
		types.WikiReleaseHead{}.TableName(), types.WikiReleasePreparation{}.TableName(),
		types.WikiRelease{}.TableName(), types.WikiReleaseReceipt{}.TableName(),
	}
	seen := make(map[types.WikiReleaseScope]struct{})
	var out []types.WikiReleaseScope
	for _, table := range tables {
		var scopes []types.WikiReleaseScope
		err := c.db.WithContext(ctx).Table(table).
			Select("tenant_id", "space_id", "raw_kb_id", "wiki_kb_id").Distinct().
			Where("tenant_id = ? AND (wiki_kb_id = ? OR raw_kb_id = ?)", tenantID, kbID, kbID).Find(&scopes).Error
		if err != nil {
			return nil, err
		}
		for _, scope := range scopes {
			if _, exists := seen[scope]; !exists {
				seen[scope] = struct{}{}
				out = append(out, scope)
			}
		}
	}
	return out, nil
}

// NewDatabaseClassifier is the production assembly seam for the existing store.
func NewDatabaseClassifier(db *gorm.DB) Classifier {
	if db == nil {
		return NewClassifier(nil, nil)
	}
	return NewClassifier(repository.NewWikiReleaseRepository(db), NewCustodyLookup(db))
}
