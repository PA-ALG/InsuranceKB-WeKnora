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
	case types.CHUNK_SEARCH_PARALLEL, types.CHUNK_SEARCH, types.CHUNK_RERANK, types.CHUNK_MERGE, types.FILTER_TOP_K:
	default:
		return noop
	}
	v, ok := ctx.Value(turnKey{}).(turnContext)
	if !ok || len(v.turn.RawKnowledge) == 0 {
		return noop
	}
	scope, err := namedScope(ctx, resolver, v, cm, event == types.CHUNK_MERGE || event == types.FILTER_TOP_K)
	if err != nil {
		// Recognition is an optional recall aid. Do not log query text or a reader's payload.
		logger.Warn(ctx, "enterprise product recognition unavailable; preserving original retrieval")
		return noop
	}
	if !scope.recognized {
		return noop
	}
	products := scope.products
	switch event {
	case types.CHUNK_SEARCH_PARALLEL, types.CHUNK_SEARCH:
		if len(products) == 0 {
			return noop
		}
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
	case types.CHUNK_MERGE:
		// The native merge drops the lower-scored of two near-identical passages, across materials,
		// before FILTER_TOP_K selects by product. Another product's copy of a shared clause could
		// then displace the named product's own and be excluded itself, leaving neither (QA2c §3,
		// q22 of #398). Exclude it first; nothing is restored, as FILTER_TOP_K excludes it anyway.
		before := len(cm.RerankResult)
		cm.RerankResult = scope.ownOrUnattributed(cm.RerankResult)
		excluded := before - len(cm.RerankResult)
		if len(cm.RerankResult) == 0 {
			// The native merge falls back to the search list when the rerank list is empty.
			before = len(cm.SearchResult)
			cm.SearchResult = scope.ownOrUnattributed(cm.SearchResult)
			excluded += before - len(cm.SearchResult)
		}
		if excluded > 0 {
			logger.Infof(ctx, "enterprise quick answer excluded %d passages before merging", excluded)
		}
		return noop
	case types.FILTER_TOP_K:
		original := cm.RerankTopK
		cm.MergeResult = selectProductResults(cm.MergeResult, scope, original)
		cm.RerankResult = selectProductResults(cm.RerankResult, scope, original)
		// The native stage falls back to the search list when both lists are empty; select it
		// too then, or another product's passages would return through that path (QA2b).
		if len(cm.MergeResult) == 0 && len(cm.RerankResult) == 0 {
			cm.SearchResult = selectProductResults(cm.SearchResult, scope, original)
		}
		// The native stage sorts by score again. Select the bounded set first so that
		// sorting cannot displace a named product with an unselected global passage.
		// Match its result-list precedence; an empty list never uncaps the next one.
		var chosen *[]*types.SearchResult
		switch {
		case len(cm.MergeResult) > 0:
			chosen = &cm.MergeResult
		case len(cm.RerankResult) > 0:
			chosen = &cm.RerankResult
		case len(cm.SearchResult) > 0:
			chosen = &cm.SearchResult
		}
		if chosen != nil {
			// Passages appended to finish a sentence come on top of the cut (QA2c §2).
			*chosen = resolver.followNeighbours(ctx, v, scope, *chosen)
			cm.RerankTopK = len(*chosen)
		}
		return func() { cm.RerankTopK = original }
	}
	return noop
}

func selectProductResults(rows []*types.SearchResult, scope productScope, topK int) []*types.SearchResult {
	selected := productOrder(rows, scope)
	// Nonpositive TopK retains the native "no cut" behavior.
	if topK > 0 && len(selected) > topK {
		selected = selected[:topK]
	}
	return selected
}

// productScope is what a quick question names across the turn's selected enterprise RAW Spaces.
type productScope struct {
	recognized bool               // the question names at least one product (QA2b §2a.1)
	products   []productMaterials // named products with usable own material, at most MaxNamedProducts
	named      map[string]bool    // materialKey of every named product's fixed material, uncapped (QA2c)
	foreign    map[string]bool    // materialKey of materials owned only by products not named
	closed     bool               // attribution unreadable: no fill at all (QA2b §2a.3)
}

type namedSpace struct {
	space, kbID string
	named       []string
}

// namedScope recognizes named products in every selected RAW Space with a pinned release. The
// cap limits only the extra search targets and turn-taking queues; with fill requested it also
// reads every selected Space's attribution, so no Space's other products can fill (QA2b §2a.2).
func namedScope(
	ctx context.Context, resolver *Resolver, v turnContext, cm *types.ChatManage, fill bool,
) (productScope, error) {
	question := cm.RewriteQuery
	if strings.TrimSpace(question) == "" {
		question = cm.Query
	}
	scope := productScope{named: map[string]bool{}, foreign: map[string]bool{}}
	var spaces []namedSpace
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
			return productScope{}, err
		}
		entry := namedSpace{space: space, kbID: target.KnowledgeBaseID}
		for _, product := range products {
			scope.recognized = true
			entry.named = append(entry.named, product.EntityID)
			ids := []string{}
			for _, id := range product.Materials {
				if owner, fixed := v.turn.RawKnowledge[id]; fixed && owner == space {
					ids = append(ids, id)
					scope.named[materialKey(target.KnowledgeBaseID, id)] = true
				}
			}
			if len(ids) == 0 || len(scope.products) == MaxNamedProducts {
				continue
			}
			sort.Strings(ids)
			scope.products = append(scope.products, productMaterials{kbID: target.KnowledgeBaseID, ids: ids})
		}
		spaces = append(spaces, entry)
	}
	if !fill || !scope.recognized {
		return scope, nil
	}
	for _, entry := range spaces {
		others, err := resolver.published.ForeignMaterials(
			ctx, v.tenant, entry.space, v.turn.Releases[entry.space], entry.named)
		if err != nil {
			// Unknown attribution must not pass as unattributed. No query text in the log.
			logger.Warn(ctx, "enterprise product attribution unavailable; answering from named products only")
			scope.closed = true
			return scope, nil
		}
		for id := range others {
			scope.foreign[materialKey(entry.kbID, id)] = true
		}
	}
	return scope, nil
}

func materialKey(kbID, knowledgeID string) string { return kbID + "\x00" + knowledgeID }

// ownOrUnattributed keeps the passages that may be selected: the named products' own, and while
// attribution is readable also those of materials owned by no product (QA2b §2a).
func (s productScope) ownOrUnattributed(rows []*types.SearchResult) []*types.SearchResult {
	own := map[string]bool{}
	for _, product := range s.products {
		for _, id := range product.ids {
			own[materialKey(product.kbID, id)] = true
		}
	}
	out := make([]*types.SearchResult, 0, len(rows))
	for _, row := range rows {
		if row == nil {
			continue
		}
		key := materialKey(row.KnowledgeBaseID, row.KnowledgeID)
		if own[key] || (!s.closed && !s.foreign[key]) {
			out = append(out, row)
		}
	}
	return out
}

// productOrder deals each product its next highest-ranked passage, once per chunk ID.
// A shared material can serve several products, but a shared passage consumes only one slot.
// The global fill skips passages of materials owned only by other products, and is skipped
// entirely when attribution could not be read (QA2b).
func productOrder(rows []*types.SearchResult, scope productScope) []*types.SearchResult {
	products := scope.products
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
	if scope.closed {
		return out
	}
	for i, row := range rows {
		if row == nil || !scope.foreign[materialKey(row.KnowledgeBaseID, row.KnowledgeID)] {
			add(i)
		}
	}
	return out
}
