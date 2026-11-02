package chatsource

import (
	"context"
	"sort"
	"strings"

	"github.com/Tencent/WeKnora/internal/enterprise/knowledge"
	"github.com/Tencent/WeKnora/internal/types"
)

// maxPublishedHits bounds the published fields one quick answer puts ahead of raw retrieval.
const maxPublishedHits = 12

type publishedKey struct{}

// publishedTurn caches one quick answer's published fields. FilterPipeline runs before prompt
// assembly and again before streaming; reading once keeps both passes identical, so the
// rendered prompt is never stripped by the second pass.
type publishedTurn struct {
	done bool
	hits []*types.SearchResult
	err  error
}

// WithPublished lets quick answers read published fields of a turn's Wiki Spaces (Q1b-2).
func (r *Resolver) WithPublished(service *knowledge.Service) *Resolver {
	if r == nil {
		return nil
	}
	copied := *r
	copied.published = service
	return &copied
}

// ResolveAnswer fixes a quick answer's scope and optionally adds authorized raw
// targets. The optional authorizer must apply the native explicit-selection ACL;
// without it no raw target is added. Search and Agent keep their original scope.
func ResolveAnswer(
	ctx context.Context, resolver *Resolver, tenant uint64, targets types.SearchTargets,
	authorizeRaw ...func(context.Context, string) bool,
) (context.Context, types.SearchTargets, error) {
	if resolver == nil || resolver.published == nil {
		ctx, targets, err := ResolveQuick(ctx, resolver, tenant, targets)
		return markAnswer(ctx, targets), targets, err
	}
	turn, err := resolver.Resolve(ctx, tenant, targets)
	if err != nil {
		return ctx, nil, err
	}
	modelTargets := turn.Targets
	if len(modelTargets) == 0 {
		modelTargets = targets
	}
	if answerSurface(ctx) && len(authorizeRaw) > 0 {
		if err := resolver.addAnswerRaw(ctx, tenant, targets, &turn, authorizeRaw[0]); err != nil {
			return ctx, nil, err
		}
	}
	ctx = markAnswer(WithTurn(ctx, turn, tenant), modelTargets)
	if len(turn.WikiSpaces) > 0 {
		ctx = context.WithValue(ctx, publishedKey{}, &publishedTurn{})
	}
	return ctx, turn.Targets, nil
}

// HasPublished reports whether this quick answer reads published fields.
func HasPublished(ctx context.Context) bool {
	_, ok := ctx.Value(publishedKey{}).(*publishedTurn)
	return ok
}

// pinnedOnly drops pinned references that do not belong to this turn's fixed releases, such as
// references a previous turn carried in from an older release.
func (t Turn) pinnedOnly(results []*types.SearchResult) []*types.SearchResult {
	out := make([]*types.SearchResult, 0, len(results))
	for _, result := range results {
		if result != nil && pinnedReference(result) && !t.ownsPinned(result) {
			continue
		}
		out = append(out, result)
	}
	return out
}

func pinnedReference(result *types.SearchResult) bool {
	tier := result.Metadata["source_tier"]
	return strings.HasPrefix(result.ID, "release:") || tier == "release" || tier == "wiki_page"
}

func (t Turn) ownsPinned(result *types.SearchResult) bool {
	metadata := result.Metadata
	space, id, slug := metadata["space_id"], metadata["release_id"], metadata["logical_slug"]
	tier := metadata["source_tier"]
	if (tier != "release" && tier != "wiki_page") || space == "" || id == "" || slug == "" ||
		t.Releases[space] != id || result.ID != "release:"+id+":"+slug {
		return false
	}
	for _, wiki := range t.WikiSpaces {
		if wiki == space {
			return true
		}
	}
	return false
}

// injectPublished puts this turn's cited published fields first, once per turn.
func injectPublished(ctx context.Context, resolver *Resolver, v turnContext, cm *types.ChatManage) error {
	state, ok := ctx.Value(publishedKey{}).(*publishedTurn)
	if !ok || resolver == nil || resolver.published == nil || len(v.turn.WikiSpaces) == 0 || !cm.NeedsRetrieval() {
		return nil
	}
	if !state.done {
		state.done = true
		state.hits, state.err = publishedHits(ctx, resolver.published, v, cm)
	}
	if state.err != nil {
		return state.err
	}
	if len(state.hits) == 0 {
		return nil
	}
	hitIDs := map[string]bool{}
	merged := make([]*types.SearchResult, 0, len(state.hits)+len(cm.MergeResult))
	for _, hit := range state.hits {
		copied := *hit
		copied.Metadata = map[string]string{}
		for key, value := range hit.Metadata {
			copied.Metadata[key] = value
		}
		merged = append(merged, &copied)
		hitIDs[hit.ID] = true
	}
	for _, result := range cm.MergeResult {
		if result == nil || !hitIDs[result.ID] {
			merged = append(merged, result)
		}
	}
	cm.MergeResult = merged
	return nil
}

func publishedHits(
	ctx context.Context, service *knowledge.Service, v turnContext, cm *types.ChatManage,
) ([]*types.SearchResult, error) {
	question := cm.RewriteQuery
	if strings.TrimSpace(question) == "" {
		question = cm.Query
	}
	spaces := append([]string(nil), v.turn.WikiSpaces...)
	sort.Strings(spaces)
	var hits []*types.SearchResult
	for _, space := range spaces {
		id := v.turn.Releases[space]
		// A sales question learns each named product's sale status first (PV-5 §1.2).
		statuses, fields, err := service.QuestionReferences(ctx, v.tenant, space, id, question, maxPublishedHits)
		if err != nil {
			return nil, err
		}
		for _, status := range statuses {
			hits = append(hits, &types.SearchResult{
				ID: "release:" + id + ":" + status.Slug, Content: status.Text, KnowledgeTitle: status.Title,
				Score: 1, ChunkType: types.ChunkTypeText, MatchType: types.MatchTypeKeywords,
				Metadata: knowledge.StatusMetadata(space, id, status),
			})
			if len(hits) == maxPublishedHits {
				return hits, nil
			}
		}
		for _, field := range fields {
			if len(field.Evidence) == 0 {
				continue // only evidence makes a reviewed reference
			}
			content := knowledge.FieldText(field)
			hits = append(hits, &types.SearchResult{
				ID: "release:" + id + ":" + field.Slug, Content: content,
				KnowledgeTitle: knowledge.FieldTitle(field),
				Score:          1, ChunkType: types.ChunkTypeText, MatchType: types.MatchTypeKeywords,
				Metadata: knowledge.FieldMetadata(space, id, field),
			})
			if len(hits) == maxPublishedHits {
				return hits, nil
			}
		}
	}
	return hits, nil
}

// SkippedWithoutRawResults names the stages that only refine raw results; once raw search has
// found nothing, published fields go straight to prompt assembly.
func SkippedWithoutRawResults(event types.EventType) bool {
	switch event {
	case types.CHUNK_RERANK, types.WEB_FETCH, types.CHUNK_MERGE, types.FILTER_TOP_K, types.DATA_ANALYSIS:
		return true
	}
	return false
}
