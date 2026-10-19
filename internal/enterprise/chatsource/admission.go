package chatsource

import (
	"context"
	"strings"

	"github.com/Tencent/WeKnora/internal/enterprise/managed"
	"github.com/Tencent/WeKnora/internal/enterprise/release"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

// Selection records explicit enterprise choices before the native target builder
// applies ACLs and tags. It detects partial lookups without granting any access.
type Selection struct {
	kbs       map[string]bool
	documents map[string]string
}

type knowledgeMetadataLookup interface {
	GetKnowledgeByIDOnly(context.Context, string) (*types.Knowledge, error)
}

func unavailableSelection() error {
	return &managed.ReadError{Code: managed.ErrorCodeClassificationUnavailable}
}

// PrepareSelection keeps the old native policy for non-enterprise quick QA.
// Agent uses native=false: its other managed targets retain the 830 policy.
func PrepareSelection(ctx context.Context, resolver *Resolver, kbs interfaces.KnowledgeBaseService,
	docs managed.SharedKnowledgeLookup, tenant uint64, kbIDs, knowledgeIDs []string, tags []types.TagScope,
	native bool,
) (*Selection, error) {
	if resolver == nil {
		if native {
			return nil, managed.CheckSearchRead(ctx, kbs, docs, tenant, kbIDs, knowledgeIDs, tags)
		}
		return nil, nil
	}
	selected := &Selection{kbs: map[string]bool{}, documents: map[string]string{}}
	wanted := map[string]bool{}
	for _, id := range kbIDs {
		if id = strings.TrimSpace(id); id != "" {
			wanted[id] = true
		}
	}
	for _, tag := range tags {
		if id := strings.TrimSpace(tag.KnowledgeBaseID); id != "" {
			wanted[id] = true
		}
	}
	requested := map[string]bool{}
	for _, id := range knowledgeIDs {
		if id = strings.TrimSpace(id); id != "" {
			requested[id] = true
		}
	}
	if len(requested) > 0 {
		if docs == nil {
			return nil, unavailableSelection()
		}
		rows, batchErr := docs.GetKnowledgeBatchWithSharedAccess(ctx, tenant, knowledgeIDs)
		if native && batchErr != nil {
			return nil, batchErr
		}
		byID := map[string]*types.Knowledge{}
		for _, row := range rows {
			if row != nil && requested[row.ID] {
				byID[row.ID] = row
			}
		}
		for id := range requested {
			row, shared := byID[id], true
			if !validDocument(row, id) && !native {
				// Metadata identifies an omitted document; it does not grant read
				// access or add the document to the native builder's results.
				if lookup, ok := docs.(knowledgeMetadataLookup); ok {
					var err error
					row, err = lookup.GetKnowledgeByIDOnly(ctx, id)
					if err != nil {
						return nil, err
					}
				}
				shared = false
			}
			if !validDocument(row, id) {
				if batchErr != nil {
					return nil, batchErr
				}
				return nil, unavailableSelection()
			}
			owner, enterprise := enterpriseOwner(resolver, tenant, row.TenantID, row.KnowledgeBaseID)
			if enterprise && (owner != tenant || row.TenantID != tenant) {
				return nil, &release.Error{Code: release.ErrorReleaseAccessDenied}
			}
			if native || enterprise {
				if batchErr != nil {
					return nil, batchErr
				}
				if !shared {
					return nil, unavailableSelection()
				}
				selected.documents[id] = row.KnowledgeBaseID
				wanted[row.KnowledgeBaseID] = true
			}
		}
	}
	for id := range wanted {
		owner, enterprise := enterpriseOwner(resolver, tenant, 0, id)
		if enterprise && owner != tenant {
			return nil, &release.Error{Code: release.ErrorReleaseAccessDenied}
		}
		if _, complete := resolver.spaces.(spaceOwnerDirectory); complete && !enterprise && !native {
			continue // Preserve the Agent's existing ordinary-KB error handling.
		}
		if kbs == nil {
			return nil, unavailableSelection()
		}
		kb, err := kbs.GetKnowledgeBaseByIDOnly(ctx, id)
		if err != nil || kb == nil || kb.ID != id || kb.TenantID == 0 {
			return nil, unavailableSelection()
		}
		owner, enterprise = enterpriseOwner(resolver, tenant, kb.TenantID, id)
		if enterprise {
			if owner != tenant || kb.TenantID != tenant {
				return nil, &release.Error{Code: "RELEASE_ACCESS_DENIED"}
			}
			if err := types.AuthorizeTenantAPIKeyKnowledgeBases(ctx, id); err != nil {
				return nil, err
			}
			selected.kbs[id] = true
			continue
		}
		if native {
			if err := types.AuthorizeTenantAPIKeyKnowledgeBases(ctx, id); err != nil {
				return nil, err
			}
			checker, ok := kbs.(managed.NativeReadChecker)
			if !ok {
				return nil, unavailableSelection()
			}
			if err := checker.CheckNativeRead(ctx, id); err != nil {
				return nil, err
			}
		}
	}
	for id, kb := range selected.documents {
		if !selected.kbs[kb] {
			delete(selected.documents, id)
		}
	}
	return selected, nil
}

func validDocument(row *types.Knowledge, id string) bool {
	return row != nil && row.ID == id && row.TenantID != 0 && row.KnowledgeBaseID != ""
}

func enterpriseOwner(resolver *Resolver, tenant, declaredOwner uint64, kbID string) (uint64, bool) {
	if directory, ok := resolver.spaces.(spaceOwnerDirectory); ok {
		owner, _, _, enterprise := directory.SpaceOwner(kbID)
		return owner, enterprise
	}
	if _, _, ok := resolver.SpaceOf(declaredOwner, kbID); ok {
		return declaredOwner, true
	}
	if _, _, ok := resolver.SpaceOf(tenant, kbID); ok {
		return tenant, true
	}
	return 0, false
}

// CheckKBs only tightens the explicitly selected enterprise part of a batch.
func (s *Selection) CheckKBs(ids []string, rows []*types.KnowledgeBase, err error) error {
	if s == nil {
		return nil
	}
	found := map[string]bool{}
	for _, row := range rows {
		if row != nil {
			found[row.ID] = true
		}
	}
	for _, id := range ids {
		if s.kbs[id] && (err != nil || !found[id]) {
			if err != nil {
				return err
			}
			return unavailableSelection()
		}
	}
	return nil
}

func (s *Selection) CheckDocuments(ids []string, rows []*types.Knowledge, err error) error {
	if s == nil {
		return nil
	}
	found := map[string]bool{}
	for _, row := range rows {
		if row != nil && s.documents[row.ID] == row.KnowledgeBaseID {
			found[row.ID] = true
		}
	}
	for _, id := range ids {
		if _, enterprise := s.documents[id]; enterprise && (err != nil || !found[id]) {
			if err != nil {
				return err
			}
			return unavailableSelection()
		}
	}
	return nil
}

func (s *Selection) CheckTargets(targets types.SearchTargets) error {
	if s == nil {
		return nil
	}
	found := map[string]bool{}
	for _, target := range targets {
		if target != nil {
			found[target.KnowledgeBaseID] = true
		}
	}
	for kb := range s.kbs {
		if !found[kb] {
			return &release.Error{Code: "RELEASE_SOURCES_UNAVAILABLE"}
		}
	}
	return nil
}
