package chatsource

import (
	"context"
	"sort"
	"strings"

	"github.com/Tencent/WeKnora/internal/logger"
	"github.com/Tencent/WeKnora/internal/types"
)

// MaxNamedProducts bounds the additional per-product searches in a quick-answer turn.
const MaxNamedProducts = 3

type productMaterials struct {
	kbID string
	ids  []string
}

// RetrievalScope adds product recall only inside a quick answer's fixed RAW scope. The
// returned function restores stage-local inputs even when the native stage fails; results
// remain available for the existing delivery filters and source labels.
func RetrievalScope(ctx context.Context, resolver *Resolver, event types.EventType, cm *types.ChatManage) func() {
	noop := func() {}
	if cm == nil || resolver == nil || resolver.published == nil || !IsEnterpriseAnswer(ctx) {
		return noop
	}
	switch event {
	case types.CHUNK_SEARCH_PARALLEL, types.CHUNK_SEARCH, types.CHUNK_RERANK, types.FILTER_TOP_K:
	default:
		return noop
	}
	v, ok := ctx.Value(turnKey{}).(turnContext)
	if !ok || len(v.turn.RawKnowledge) == 0 {
		return noop
	}
	products, err := namedMaterials(ctx, resolver, v, cm)
	if err != nil {
		// Recognition is an optional recall aid. Do not log query text or a reader's payload.
		logger.Warn(ctx, "enterprise product recognition unavailable; preserving original retrieval")
		return noop
	}
	if len(products) == 0 {
		return noop
	}
	switch event {
	case types.CHUNK_SEARCH_PARALLEL, types.CHUNK_SEARCH:
		original := cm.SearchTargets
		targets := append(types.SearchTargets(nil), original...)
		for _, product := range products {
			targets = append(targets, &types.SearchTarget{
				Type: types.SearchTargetTypeKnowledge, KnowledgeBaseID: product.kbID,
				TenantID: v.tenant, KnowledgeIDs: product.ids,
			})
		}
		cm.SearchTargets = targets
		return func() { cm.SearchTargets = original }
	case types.CHUNK_RERANK:
		original := cm.RerankTopK
		cm.RerankTopK = max(original, len(cm.SearchResult))
		return func() { cm.RerankTopK = original }
	case types.FILTER_TOP_K:
		original := cm.RerankTopK
		cm.MergeResult = selectProductResults(cm.MergeResult, products, original)
		cm.RerankResult = selectProductResults(cm.RerankResult, products, original)
		// The native stage sorts by score again. Select the bounded set first so that
		// sorting cannot displace a named product with an unselected global passage.
		// Match its result-list precedence; an empty pair must not uncap SearchResult.
		switch {
		case len(cm.MergeResult) > 0:
			cm.RerankTopK = len(cm.MergeResult)
		case len(cm.RerankResult) > 0:
			cm.RerankTopK = len(cm.RerankResult)
		}
		return func() { cm.RerankTopK = original }
	}
	return noop
}

func selectProductResults(rows []*types.SearchResult, products []productMaterials, topK int) []*types.SearchResult {
	selected := productOrder(rows, products)
	// Nonpositive TopK retains the native "no cut" behavior.
	if topK > 0 && len(selected) > topK {
		selected = selected[:topK]
	}
	return selected
}

func namedMaterials(
	ctx context.Context, resolver *Resolver, v turnContext, cm *types.ChatManage,
) ([]productMaterials, error) {
	question := cm.RewriteQuery
	if strings.TrimSpace(question) == "" {
		question = cm.Query
	}
	var out []productMaterials
	seen := map[string]bool{}
	// Target order defines the order of Spaces; QuestionProducts keeps each release's
	// navigation order. Never iterate a map to decide which three products receive recall.
	for _, target := range cm.SearchTargets {
		if target == nil || target.TenantID != v.tenant {
			continue
		}
		space, role, ok := resolver.SpaceOf(v.tenant, target.KnowledgeBaseID)
		if !ok || role != RoleRaw || seen[space] || v.turn.Releases[space] == "" {
			continue
		}
		seen[space] = true
		products, err := resolver.published.QuestionProducts(ctx, v.tenant, space, v.turn.Releases[space], question)
		if err != nil {
			return nil, err
		}
		for _, product := range products {
			ids := []string{}
			for _, id := range product.Materials {
				if owner, fixed := v.turn.RawKnowledge[id]; fixed && owner == space {
					ids = append(ids, id)
				}
			}
			if len(ids) == 0 {
				continue
			}
			sort.Strings(ids)
			out = append(out, productMaterials{kbID: target.KnowledgeBaseID, ids: ids})
			if len(out) == MaxNamedProducts {
				return out, nil
			}
		}
	}
	return out, nil
}

// productOrder deals each product its next highest-ranked passage, once per chunk ID.
// A shared material can serve several products, but a shared passage consumes only one slot.
func productOrder(rows []*types.SearchResult, products []productMaterials) []*types.SearchResult {
	if len(rows) == 0 {
		return rows
	}
	queues := make([][]int, len(products))
	for p, product := range products {
		materials := map[string]bool{}
		for _, id := range product.ids {
			materials[id] = true
		}
		for i, row := range rows {
			if row != nil && row.KnowledgeBaseID == product.kbID && materials[row.KnowledgeID] {
				queues[p] = append(queues[p], i)
			}
		}
	}
	out := make([]*types.SearchResult, 0, len(rows))
	used, ids := make([]bool, len(rows)), map[string]bool{}
	add := func(i int) bool {
		row := rows[i]
		if used[i] || (row != nil && row.ID != "" && ids[row.ID]) {
			return false
		}
		used[i] = true
		if row != nil && row.ID != "" {
			ids[row.ID] = true
		}
		out = append(out, row)
		return true
	}
	for {
		added := false
		for p, queue := range queues {
			for len(queue) > 0 {
				i := queue[0]
				queue = queue[1:]
				if add(i) {
					added = true
					break
				}
			}
			queues[p] = queue
		}
		if !added {
			break
		}
	}
	for i := range rows {
		add(i)
	}
	return out
}
