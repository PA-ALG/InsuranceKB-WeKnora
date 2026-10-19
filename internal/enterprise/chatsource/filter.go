package chatsource

import (
	"context"
	"errors"

	"github.com/Tencent/WeKnora/internal/types"
)

// ChunkReader reuses the tenant-scoped native chunk repository.
type ChunkReader interface {
	ListChunksByID(context.Context, uint64, []string) ([]*types.Chunk, error)
}

// Filter checks delivery-time revision state without reading Active again. Returned
// enterprise results are copies; Label never changes the caller's shared objects.
func (r *Resolver) Filter(
	ctx context.Context, tenantID uint64, turn Turn, chunks ChunkReader, results []*types.SearchResult,
) ([]*types.SearchResult, error) {
	if r == nil || missing(r.spaces) {
		return nil, errors.New("chat source configuration is unavailable")
	}
	ids, knowledge := []string{}, map[string]int64{}
	spaces := map[string]bool{}
	for _, result := range results {
		if result == nil {
			continue
		}
		if space, enterprise := r.enterpriseResult(tenantID, turn, result); enterprise {
			ids = append(ids, result.ID)
			spaces[space] = true
			if attempt, ok := turn.RawAttempts[result.KnowledgeID]; ok {
				knowledge[result.KnowledgeID] = attempt
			}
		}
	}
	if len(ids) == 0 {
		return append([]*types.SearchResult(nil), results...), nil
	}
	if missing(chunks) || missing(r.pins) || missing(r.attempts) {
		return nil, errors.New("chat source filtering dependencies are unavailable")
	}
	rows, err := chunks.ListChunksByID(ctx, tenantID, ids)
	if err != nil {
		return nil, err
	}
	byID := map[string]*types.Chunk{}
	for _, row := range rows {
		if row != nil {
			byID[row.ID] = row
		}
	}
	current, err := r.attempts.CurrentAttempts(ctx, tenantID, sortedIDs(knowledge))
	if err != nil {
		return nil, err
	}
	pins := map[string]map[string]int64{}
	for space := range spaces {
		if turn.Releases[space] == "" {
			continue
		}
		rows, err := r.pins.ReleaseSources(ctx, tenantID, space, turn.Releases[space])
		if err != nil {
			return nil, err
		}
		pins[space] = uniqueAttempts(rows)
	}
	out := make([]*types.SearchResult, 0, len(results))
	for _, result := range results {
		if result == nil {
			continue
		}
		space, enterprise := r.enterpriseResult(tenantID, turn, result)
		if !enterprise {
			out = append(out, result)
			continue
		}
		attempt, selected := turn.RawAttempts[result.KnowledgeID]
		row := byID[result.ID]
		if !selected || row == nil || row.DeletedAt.Valid || row.TenantID != tenantID ||
			row.KnowledgeID != result.KnowledgeID || row.ParseAttempt != attempt ||
			current[result.KnowledgeID] != attempt || pins[space][result.KnowledgeID] != attempt {
			continue
		}
		chunkSpace, role, ok := r.SpaceOf(tenantID, row.KnowledgeBaseID)
		if !ok || role != RoleRaw || chunkSpace != space ||
			(result.KnowledgeBaseID != "" && result.KnowledgeBaseID != row.KnowledgeBaseID) {
			continue
		}
		cloned := *result
		if cloned.ContentRewritten || len(cloned.SubChunkID) > 0 {
			// Native merging does not retain a complete contributor chain for
			// parent/neighbor expansions. Deliver the verified primary chunk
			// rather than trusting any unverified merged text or image payload.
			cloned.Content, cloned.ImageInfo = row.Content, row.ImageInfo
			cloned.StartAt, cloned.EndAt, cloned.ChunkIndex = row.StartAt, row.EndAt, row.ChunkIndex
			cloned.ChunkType, cloned.ParentChunkID = string(row.ChunkType), row.ParentChunkID
			cloned.ContentRevision = row.ContentRevision
			cloned.SubChunkID, cloned.ContentRewritten = nil, false
		}
		turn.Label([]*types.SearchResult{&cloned})
		out = append(out, &cloned)
	}
	return out, nil
}

func (r *Resolver) enterpriseResult(tenantID uint64, turn Turn, result *types.SearchResult) (string, bool) {
	if space, ok := turn.RawKnowledge[result.KnowledgeID]; ok {
		return space, true
	}
	if directory, complete := r.spaces.(spaceOwnerDirectory); complete {
		_, space, _, enterprise := directory.SpaceOwner(result.KnowledgeBaseID)
		return space, enterprise
	}
	space, _, ok := r.SpaceOf(tenantID, result.KnowledgeBaseID)
	return space, ok
}
