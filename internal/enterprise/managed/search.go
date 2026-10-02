package managed

import (
	"context"
	"strings"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

// NativeReadChecker is an optional service extension, required when searching
// selected KBs. Embedding the original service leaves all other paths unchanged.
type NativeReadChecker interface {
	CheckNativeRead(context.Context, string) error
}
type classifiedKnowledgeBaseService struct {
	interfaces.KnowledgeBaseService
	classifier Classifier
}

func DecorateKnowledgeBaseService(service interfaces.KnowledgeBaseService, classifier Classifier) interfaces.KnowledgeBaseService {
	return &classifiedKnowledgeBaseService{KnowledgeBaseService: service, classifier: classifier}
}
func (s *classifiedKnowledgeBaseService) CheckNativeRead(ctx context.Context, kbID string) error {
	if s.KnowledgeBaseService == nil {
		return &ReadError{Code: ErrorCodeClassificationUnavailable}
	}
	kb, err := s.GetKnowledgeBaseByIDOnly(ctx, kbID)
	if err != nil || kb == nil || kb.ID != kbID {
		return &ReadError{Code: ErrorCodeClassificationUnavailable}
	}
	return CheckRead(ctx, s.classifier, kb.TenantID, kb.ID)
}

type SharedKnowledgeLookup interface {
	GetKnowledgeBatchWithSharedAccess(context.Context, uint64, []string) ([]*types.Knowledge, error)
}

// CheckSearchRead rejects a selected managed KB before target building or model
// work. Missing lookups fail closed: a partial batch is not a safe classification.
// Tag-only targets are selections too. Agent QA does not call this boundary.
func CheckSearchRead(ctx context.Context, kbs interfaces.KnowledgeBaseService, documents SharedKnowledgeLookup,
	tenant uint64, kbIDs, knowledgeIDs []string, tags []types.TagScope) error {
	ids := make(map[string]struct{})
	for _, id := range kbIDs {
		if id = strings.TrimSpace(id); id != "" {
			ids[id] = struct{}{}
		}
	}
	for _, scope := range tags {
		if id := strings.TrimSpace(scope.KnowledgeBaseID); id != "" {
			ids[id] = struct{}{}
		}
	}
	wanted := make(map[string]struct{})
	for _, id := range knowledgeIDs {
		if id = strings.TrimSpace(id); id != "" {
			wanted[id] = struct{}{}
		}
	}
	unavailable := &ReadError{Code: ErrorCodeClassificationUnavailable}
	if len(wanted) > 0 {
		if documents == nil || tenant == 0 {
			return unavailable
		}
		selected := make([]string, 0, len(wanted))
		for id := range wanted {
			selected = append(selected, id)
		}
		rows, err := documents.GetKnowledgeBatchWithSharedAccess(ctx, tenant, selected)
		if err != nil {
			return unavailable
		}
		for _, row := range rows {
			if row == nil {
				return unavailable
			}
			if _, ok := wanted[row.ID]; !ok {
				continue
			}
			if row.KnowledgeBaseID == "" || row.TenantID == 0 {
				return unavailable
			}
			ids[row.KnowledgeBaseID] = struct{}{}
			delete(wanted, row.ID)
		}
		if len(wanted) > 0 {
			return unavailable
		}
	}
	if len(ids) == 0 {
		return nil
	}
	checker, ok := kbs.(NativeReadChecker)
	if !ok {
		return unavailable
	}
	for id := range ids {
		if err := checker.CheckNativeRead(ctx, id); err != nil {
			return err
		}
	}
	return nil
}
