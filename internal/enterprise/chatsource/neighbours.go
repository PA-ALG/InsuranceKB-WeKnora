package chatsource

import (
	"context"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/Tencent/WeKnora/internal/logger"
	"github.com/Tencent/WeKnora/internal/types"
)

// MaxNeighbourChunks bounds the passages one quick-answer turn appends after named products'
// passages that stop mid-sentence (QA2c §2).
const MaxNeighbourChunks = 3

// sentenceEnds are the final characters of a complete sentence, full and ASCII width.
const sentenceEnds = "。！？；」”）.!?;\")"

// WithChunks lets quick answers read the next passage of a named product's passage (QA2c).
func (r *Resolver) WithChunks(chunks ChunkReader) *Resolver {
	if r == nil {
		return nil
	}
	copied := *r
	copied.chunks = chunks
	return &copied
}

// followNeighbours appends, after each selected passage of a named product whose delivered text
// stops mid-sentence, the next passages of the same material and parse attempt until a sentence
// ends. Chunking cuts clauses at a fixed length, so a condition and its consequence can sit in two
// passages and only the first ranks (QA2c §2, q23 of #398). Delivery keeps a merged group's
// primary passage only, so that is the text judged. A failed read appends nothing: the selection
// stands as it was.
func (r *Resolver) followNeighbours(
	ctx context.Context, v turnContext, scope productScope, rows []*types.SearchResult,
) []*types.SearchResult {
	if missing(r.chunks) {
		return rows
	}
	present := map[string]bool{}
	starts, ids := []*types.SearchResult{}, []string{}
	for _, row := range rows {
		if row == nil || row.ID == "" {
			continue
		}
		present[row.ID] = true
		// Every named product counts, not only the three given extra searches (#417 R1).
		if scope.named[materialKey(row.KnowledgeBaseID, row.KnowledgeID)] {
			starts, ids = append(starts, row), append(ids, row.ID)
		}
	}
	if len(starts) == 0 {
		return rows
	}
	// The native merge returns groups in no fixed order; spend the budget in delivered order.
	sort.SliceStable(starts, func(i, j int) bool { return nativeBefore(starts[i], starts[j]) })
	current, err := r.readChunks(ctx, v.tenant, ids)
	if err != nil {
		logger.Warn(ctx, "enterprise neighbour passages unavailable; keeping the selected passages")
		return rows
	}
	added, budget := map[string][]*types.SearchResult{}, MaxNeighbourChunks
	for _, start := range starts {
		chunk := current[start.ID]
		if !followable(v, start, chunk) {
			continue
		}
		for budget > 0 && midSentence(chunk.Content) && chunk.NextChunkID != "" && !present[chunk.NextChunkID] {
			next, err := r.readChunks(ctx, v.tenant, []string{chunk.NextChunkID})
			if err != nil {
				logger.Warn(ctx, "enterprise neighbour passages unavailable; keeping the selected passages")
				return rows
			}
			chunk = next[chunk.NextChunkID]
			if !followable(v, start, chunk) {
				break
			}
			added[start.ID] = append(added[start.ID], neighbour(start, chunk))
			present[chunk.ID] = true
			budget--
		}
	}
	if budget == MaxNeighbourChunks {
		return rows
	}
	logger.Infof(ctx, "enterprise quick answer appended %d neighbour passages", MaxNeighbourChunks-budget)
	out := make([]*types.SearchResult, 0, len(rows)+MaxNeighbourChunks-budget)
	for _, row := range rows {
		out = append(out, row)
		if row != nil {
			out = append(out, added[row.ID]...)
			delete(added, row.ID)
		}
	}
	return out
}

func (r *Resolver) readChunks(ctx context.Context, tenant uint64, ids []string) (map[string]*types.Chunk, error) {
	rows, err := r.chunks.ListChunksByID(ctx, tenant, ids)
	if err != nil {
		return nil, err
	}
	out := make(map[string]*types.Chunk, len(rows))
	for _, row := range rows {
		if row != nil {
			out[row.ID] = row
		}
	}
	return out, nil
}

// followable reports whether a stored text passage may be delivered for the selected one: same
// tenant, knowledge base and material, at the material's parse attempt fixed for this turn.
func followable(v turnContext, start *types.SearchResult, chunk *types.Chunk) bool {
	attempt, fixed := v.turn.RawAttempts[start.KnowledgeID]
	return chunk != nil && fixed && !chunk.DeletedAt.Valid && chunk.IsEnabled &&
		chunk.TenantID == v.tenant && chunk.KnowledgeBaseID == start.KnowledgeBaseID &&
		chunk.KnowledgeID == start.KnowledgeID && chunk.ParseAttempt == attempt &&
		chunk.ChunkType == types.ChunkTypeText
}

func midSentence(content string) bool {
	content = strings.TrimRightFunc(content, unicode.IsSpace)
	last, _ := utf8.DecodeLastRuneInString(content)
	return content != "" && !strings.ContainsRune(sentenceEnds, last)
}

// neighbour is the next passage as a result of its own, ranked with the selected passage. The
// native top-k sort then keeps it directly after that passage: equal score, same material, a
// later chunk index.
func neighbour(start *types.SearchResult, chunk *types.Chunk) *types.SearchResult {
	return &types.SearchResult{
		ID: chunk.ID, Content: chunk.Content, KnowledgeID: chunk.KnowledgeID, KnowledgeBaseID: chunk.KnowledgeBaseID,
		ChunkIndex: chunk.ChunkIndex, StartAt: chunk.StartAt, EndAt: chunk.EndAt, ChunkType: chunk.ChunkType,
		ParentChunkID: chunk.ParentChunkID, ImageInfo: chunk.ImageInfo, ContentRevision: chunk.ContentRevision,
		Score: start.Score, MatchType: types.MatchTypeNearByChunk,
		KnowledgeTitle: start.KnowledgeTitle, KnowledgeFilename: start.KnowledgeFilename,
		KnowledgeSource: start.KnowledgeSource, KnowledgeChannel: start.KnowledgeChannel,
		KnowledgeDescription: start.KnowledgeDescription, KnowledgeCustomMetadata: start.KnowledgeCustomMetadata,
	}
}

// nativeBefore is the native FILTER_TOP_K order: score, then material, chunk type, index and ID.
func nativeBefore(left, right *types.SearchResult) bool {
	switch {
	case left.Score != right.Score:
		return left.Score > right.Score
	case left.KnowledgeID != right.KnowledgeID:
		return left.KnowledgeID < right.KnowledgeID
	case left.ChunkType != right.ChunkType:
		return left.ChunkType < right.ChunkType
	case left.ChunkIndex != right.ChunkIndex:
		return left.ChunkIndex < right.ChunkIndex
	}
	return left.ID < right.ID
}
