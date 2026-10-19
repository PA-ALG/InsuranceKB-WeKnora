package chatsource

import (
	"context"

	"github.com/Tencent/WeKnora/internal/types"
)

// AnalysisScope keeps enterprise sources out of the native full-file analysis
// stage. They remain chunk retrieval results for the final delivery checks.
// The caller restores the scope even when the native stage returns an error.
func AnalysisScope(ctx context.Context, resolver *Resolver, event types.EventType, cm *types.ChatManage) func() {
	v, ok := ctx.Value(turnKey{}).(turnContext)
	if event != types.DATA_ANALYSIS || !ok || resolver == nil {
		return func() {}
	}
	original := append([]*types.SearchResult(nil), cm.MergeResult...)
	ordinary := make([]*types.SearchResult, 0, len(original))
	enterprise := make(map[*types.SearchResult]bool)
	for _, row := range original {
		if row != nil {
			if _, isEnterprise := resolver.enterpriseResult(v.tenant, v.turn, row); isEnterprise {
				enterprise[row] = true
				continue
			}
		}
		ordinary = append(ordinary, row)
	}
	if len(enterprise) == 0 {
		return func() {}
	}
	cm.MergeResult = ordinary
	return func() {
		outputs := cm.MergeResult
		byID := make(map[string]*types.SearchResult, len(outputs))
		for _, row := range outputs {
			if row != nil {
				byID[row.ID] = row
			}
		}
		merged := make([]*types.SearchResult, 0, len(original)+len(outputs))
		for _, row := range original {
			if enterprise[row] {
				merged = append(merged, row)
			} else if row != nil && byID[row.ID] != nil {
				merged = append(merged, byID[row.ID])
				delete(byID, row.ID)
			}
		}
		for _, row := range outputs {
			if row != nil && byID[row.ID] != nil {
				merged = append(merged, row)
				delete(byID, row.ID)
			}
		}
		cm.MergeResult = merged
	}
}
