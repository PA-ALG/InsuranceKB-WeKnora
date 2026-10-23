package service

import (
	"context"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/Tencent/WeKnora/internal/types"
)

const (
	G3PlatformChunkMappingExactBlock = "EXACT_BLOCK"
	G3PlatformChunkMappingUnresolved = "UNRESOLVED"
)

// The G3 platform source snapshot service went with the G3 reparse chain in S7d-2c-2a. What is left
// is the 830 citation family's source capture and chunk page mapping, deleted with it in S7d-2c-3.

type G3PlatformChunkPageSpanV1 struct {
	PageNumber           int `json:"page_number"`
	BlockCodepointStart  int `json:"block_codepoint_start"`
	BlockCodepointEnd    int `json:"block_codepoint_end"`
	GlobalCodepointStart int `json:"global_codepoint_start"`
	GlobalCodepointEnd   int `json:"global_codepoint_end"`
}

type G3PlatformChunkPageMappingV1 struct {
	ChunkID          string                      `json:"chunk_id"`
	Status           string                      `json:"status"`
	SourcePageNumber *int                        `json:"source_page_number,omitempty"`
	BlockGlobalStart *int                        `json:"block_global_start,omitempty"`
	BlockGlobalEnd   *int                        `json:"block_global_end,omitempty"`
	PageSpans        []G3PlatformChunkPageSpanV1 `json:"page_spans"`
}

func (s *ConceptSourceAuthorityService830G2) captureG3PlatformSource830G3(
	ctx context.Context,
	scope types.WikiReleaseScope,
	expected *types.KnowledgeRevisionSource,
) (*conceptSourceReusePrepared830G3, error) {
	if s == nil || s.fixed == nil || s.knowledge == nil || s.revisions == nil ||
		s.chunks == nil || s.sourceReuse == nil || expected == nil ||
		types.ValidateKnowledgeRevisionSourceBinding(*expected) != nil ||
		expected.TenantID != scope.TenantID || expected.KnowledgeID == "" ||
		expected.ParseAttempt <= 0 {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	knowledge, err := s.knowledge.GetKnowledgeByID(ctx, scope.TenantID, expected.KnowledgeID)
	if err != nil || knowledge == nil || knowledge.DeletedAt.Valid ||
		knowledge.TenantID != scope.TenantID || knowledge.KnowledgeBaseID != scope.RawKBID {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	revision, err := s.revisions.GetRevision(ctx, expected.KnowledgeID, expected.ParseAttempt)
	if err != nil || revision == nil || revision.KnowledgeID != expected.KnowledgeID ||
		revision.ParseAttempt != expected.ParseAttempt || revision.FileSHA256 != expected.FileSHA256 ||
		revision.ManifestAlgorithm != expected.ManifestAlgorithm ||
		revision.ManifestDigest != expected.ManifestDigest || revision.ChunkCount != expected.ChunkCount {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	live, resource, err := s.revisions.GetRevisionSource(
		ctx, scope.TenantID, expected.KnowledgeID, expected.ParseAttempt,
	)
	if err != nil || live == nil || resource == nil ||
		!sameRevisionSourceAuthority(*live, *expected) ||
		resource.ID != live.ResourceID || resource.TenantID != scope.TenantID ||
		resource.Handle != live.ResourceHandle || resource.ContentHash != live.ObjectSHA256 ||
		resource.State != types.ResourceStateActive ||
		resource.Lifecycle != types.ResourceLifecyclePersistent {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	identity := types.ConceptSourceIdentity830G2{
		TenantID: scope.TenantID, SpaceID: scope.SpaceID, RawKBID: scope.RawKBID,
		KnowledgeID: live.KnowledgeID, ParseAttempt: live.ParseAttempt,
		RevisionID: live.RevisionSourceID, SourceHash: live.FileSHA256,
		ParseHash: live.ManifestDigest,
	}
	// A legacy cache hit must not bypass the first-parse provenance gate.
	first, err := s.sourceReuse.readFirstParse(g3FirstParseIdentityForSource(scope, live))
	if err != nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	identity.ParserIdentity = first.ParserIdentitySHA256
	key, err := conceptSourceReuseKey830G3(identity, live.BindingDigest)
	if err != nil {
		return nil, err
	}
	prepared, err := s.sourceReuse.load(ctx, key, identity, live, func() (*conceptSourceReuseRecord830G3, error) {
		chunks, err := s.chunks.ListChunksByKnowledgeID(ctx, scope.TenantID, live.KnowledgeID)
		if err != nil {
			return nil, err
		}
		manifest := make([]types.RevisionManifestChunk, 0, len(chunks))
		for _, chunk := range chunks {
			if chunk == nil || chunk.ParseAttempt != live.ParseAttempt {
				continue
			}
			if chunk.TenantID != scope.TenantID || chunk.KnowledgeID != live.KnowledgeID ||
				chunk.KnowledgeBaseID != scope.RawKBID {
				return nil, ErrConceptSourceAuthorityUnavailable830G2
			}
			manifest = append(manifest, types.RevisionManifestChunk{
				ID: chunk.ID, Index: chunk.ChunkIndex, Content: chunk.Content,
			})
		}
		sort.Slice(manifest, func(i, j int) bool { return manifest[i].Index < manifest[j].Index })
		digest, err := types.ComputeRevisionManifestDigest(live.KnowledgeID, live.ParseAttempt, manifest)
		if err != nil || digest != live.ManifestDigest || len(manifest) != live.ChunkCount {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		ranges, err := g3FirstParseBindings(first, manifest)
		if err != nil {
			return nil, err
		}
		return &conceptSourceReuseRecord830G3{
			Contract: conceptSourceReuseContract830G3, Identity: identity,
			BindingDigest: live.BindingDigest, Chunks: manifest,
			Markdown: first.Markdown, Native: first.Native,
			FirstParseSHA256: g3FirstParseRecordSHA(first), ChunkRanges: ranges,
		}, nil
	})
	if err != nil {
		return nil, err
	}
	if err := g3CachedFirstParseMatches(first, &prepared.record); err != nil {
		return nil, err
	}
	return prepared, nil
}

func g3PlatformChunkPageMapping(
	chunk types.RevisionManifestChunk,
	index *conceptNativeQuoteIndex830G2,
	exactRanges ...map[string]g3FirstParseRange,
) G3PlatformChunkPageMappingV1 {
	result := G3PlatformChunkPageMappingV1{
		ChunkID: chunk.ID, Status: G3PlatformChunkMappingUnresolved,
		PageSpans: []G3PlatformChunkPageSpanV1{},
	}
	if index == nil || chunk.Content == "" {
		return result
	}
	var start, end int
	if len(exactRanges) > 0 && exactRanges[0] != nil {
		r, ok := exactRanges[0][chunk.ID]
		if !ok || !g3FirstParseRangeMatchesRunes(index.sourceRunes(), chunk.Content, r) {
			return result
		}
		start, end = r.Start, r.End
	} else {
		at := strings.Index(index.text, chunk.Content)
		if at < 0 || strings.Index(index.text[at+1:], chunk.Content) >= 0 {
			return result
		}
		start = utf8.RuneCountInString(index.text[:at])
		end = start + utf8.RuneCountInString(chunk.Content)
	}
	numbers := make([]int, 0, len(index.pages))
	for number := range index.pages {
		numbers = append(numbers, number)
	}
	sort.Ints(numbers)
	spans := make([]G3PlatformChunkPageSpanV1, 0, len(numbers))
	sourcePage := 0
	for _, number := range numbers {
		page := index.pages[number]
		pageEnd := page.globalStart + len(page.runes)
		overlapStart, overlapEnd := max(start, page.globalStart), min(end, pageEnd)
		if overlapStart >= overlapEnd {
			continue
		}
		if sourcePage == 0 && start >= page.globalStart && start < pageEnd {
			sourcePage = number
		}
		spans = append(spans, G3PlatformChunkPageSpanV1{
			PageNumber:           number,
			BlockCodepointStart:  overlapStart - start,
			BlockCodepointEnd:    overlapEnd - start,
			GlobalCodepointStart: overlapStart,
			GlobalCodepointEnd:   overlapEnd,
		})
	}
	if sourcePage == 0 || len(spans) == 0 {
		return result
	}
	result.Status = G3PlatformChunkMappingExactBlock
	result.SourcePageNumber = intPointerG3Platform(sourcePage)
	result.BlockGlobalStart = intPointerG3Platform(start)
	result.BlockGlobalEnd = intPointerG3Platform(end)
	result.PageSpans = spans
	return result
}

func intPointerG3Platform(value int) *int { return &value }
