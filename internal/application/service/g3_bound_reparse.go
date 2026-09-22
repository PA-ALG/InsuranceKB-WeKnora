package service

import (
	"context"
	"fmt"
	"regexp"
	"time"

	"github.com/Tencent/WeKnora/internal/types"
)

var g3BoundRecoveryKey = regexp.MustCompile(`^[0-9a-f]{64}$`)

type G3BoundReparseRequest struct {
	RawKBID              string
	RunID                string
	Ordinal              int
	ExpectedParseAttempt int64
	RecoveryKey          string
	DeadlineAt           time.Time
}

// BoundReparseKnowledge shares the native file reparse path while using a
// scoped, idempotent allocation and a worker-visible recovery fence.
func (s *knowledgeService) BoundReparseKnowledge(ctx context.Context, knowledgeID string, request G3BoundReparseRequest) (types.G3BoundReparseReceipt, error) {
	if !g3BoundRecoveryKey.MatchString(request.RecoveryKey) || request.RawKBID == "" || request.RunID == "" || request.Ordinal < 0 ||
		request.ExpectedParseAttempt <= 0 || !request.DeadlineAt.After(time.Now()) || request.DeadlineAt.After(time.Now().Add(24*time.Hour)) {
		return types.G3BoundReparseReceipt{}, fmt.Errorf("invalid bound reparse request")
	}
	if prior, err := s.ReadBoundReparseKnowledge(ctx, knowledgeID, request.RecoveryKey); err == nil {
		if prior.RunID == request.RunID && prior.Ordinal == request.Ordinal && prior.ExpectedParseAttempt == request.ExpectedParseAttempt && prior.DeadlineAt.Equal(request.DeadlineAt) {
			return prior, nil
		}
		return types.G3BoundReparseReceipt{}, fmt.Errorf("bound reparse key conflict")
	}
	_, err := s.reparseKnowledge(ctx, knowledgeID, nil, &request)
	if err != nil {
		return types.G3BoundReparseReceipt{}, err
	}
	return s.ReadBoundReparseKnowledge(ctx, knowledgeID, request.RecoveryKey)
}

func (s *knowledgeService) ReadBoundReparseKnowledge(ctx context.Context, knowledgeID, key string) (types.G3BoundReparseReceipt, error) {
	if !g3BoundRecoveryKey.MatchString(key) {
		return types.G3BoundReparseReceipt{}, fmt.Errorf("invalid recovery key")
	}
	tenantID, ok := types.TenantIDFromContext(ctx)
	if !ok {
		return types.G3BoundReparseReceipt{}, fmt.Errorf("missing tenant")
	}
	knowledge, err := s.repo.GetKnowledgeByID(ctx, tenantID, knowledgeID)
	if err != nil {
		return types.G3BoundReparseReceipt{}, err
	}
	receipt, found := g3BoundReparseReceipt(knowledge, key)
	if !found {
		return types.G3BoundReparseReceipt{}, fmt.Errorf("bound reparse receipt not found")
	}
	if knowledge.CurrentParseAttempt == receipt.ParseAttempt {
		receipt.ParseStatus = knowledge.ParseStatus
		switch knowledge.ParseStatus {
		case types.ParseStatusCompleted:
			receipt.DispatchState = "completed"
		case types.ParseStatusFailed, types.ParseStatusCancelled:
			receipt.DispatchState = "failed"
		default:
			if !time.Now().Before(receipt.DeadlineAt) {
				receipt.DispatchState = "failed"
			}
		}
	}
	return receipt, nil
}
