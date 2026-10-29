package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/Tencent/WeKnora/internal/agent"
	"github.com/Tencent/WeKnora/internal/logger"
	"github.com/Tencent/WeKnora/internal/modelcontext"
	"github.com/Tencent/WeKnora/internal/models/chat"
	"github.com/Tencent/WeKnora/internal/searchutil"
	"github.com/Tencent/WeKnora/internal/types"
	"golang.org/x/sync/errgroup"
)

const (
	// maxRunesPerCitationBatch bounds the size of a single chunk-citation
	// batch by rune count (a fast approximation of token count). Small enough
	// that batches stay comfortably inside the LLM's context and output
	// budgets, large enough that most short/medium documents classify in a
	// single batch. Tune via benchmarks if needed.
	maxRunesPerCitationBatch = 12000

	// maxCitationBatchConcurrency limits parallelism across chunk-citation
	// batches so a single long document can't saturate the synthesis model.
	maxCitationBatchConcurrency = 4

	// A root can make at most 1 + 2 + 4 + 8 candidate calls after known overflow.
	maxCandidateSplitDepth = 3

	// Citation overflow has its own bounded tree: at most fifteen calls per root.
	maxCitationSplitDepth = 3
)

// citationBatchResult is the JSON shape we expect back from one invocation of
// WikiChunkCitationPrompt.
type citationBatchResult struct {
	Citations map[string][]string   `json:"citations"`
	NewSlugs  []newSlugFromCitation `json:"new_slugs"`
}

// newSlugFromCitation is the shape of an entry in the "new_slugs" array of
// WikiChunkCitationPrompt. Mirrors extractedItem but also carries a "type"
// tag because this prompt emits entities and concepts in a single array.
type newSlugFromCitation struct {
	Type         string   `json:"type"`
	Name         string   `json:"name"`
	Slug         string   `json:"slug"`
	Aliases      []string `json:"aliases"`
	Description  string   `json:"description"`
	Details      string   `json:"details"`
	SourceChunks []string `json:"source_chunks"`
}

// citationPipelineOutcome carries the raw numbers produced by the Pass
// 0 + classification flow so callers (mapOneDocument) can log a single
// unified stat line.
type citationPipelineOutcome struct {
	CandidateCount int
	ChunkCount     int
	BatchCount     int
	CitedChunks    int
	UncitedSlugs   int
	NewSlugCount   int
}

// extractCandidateSlugs discovers every text window before deduplicating once.
// Indexed results make model completion order irrelevant to first-item policy.
func (s *wikiIngestService) extractCandidateSlugs(
	ctx context.Context, chatModel chat.Chat, kbID string, windows []wikiDocumentWindow,
	lang string, oldPageSlugs map[string]bool, batchCtx *WikiBatchContext,
) ([]extractedItem, []extractedItem, map[string]extractedItem, error) {
	rootResults := make([][]combinedExtraction, len(windows))
	failures := make([]error, len(windows))
	eg, ectx := errgroup.WithContext(ctx)
	eg.SetLimit(maxCitationBatchConcurrency)
	for i := range windows {
		eg.Go(func() error {
			rootResults[i], failures[i] = s.extractWindowCandidates(
				ectx, chatModel, &windows[i], i, 0, lang, oldPageSlugs, batchCtx,
			)
			return nil // A failed window does not cancel already-sent peers.
		})
	}
	_ = eg.Wait()
	if err := aggregateWikiStageErrors("wiki_candidate_slug", failures); err != nil {
		return nil, nil, nil, err
	}
	var results []combinedExtraction
	for _, root := range rootResults {
		results = append(results, root...)
	}
	merged := mergeWindowCandidates(results)
	entities, concepts, canonical := s.deduplicateExtractedBatch(
		ctx, chatModel, kbID, merged.Entities, merged.Concepts, batchCtx,
	)
	items := make(map[string]extractedItem, len(entities)+len(concepts))
	for _, group := range [][]extractedItem{entities, concepts} {
		for _, item := range group {
			if item.Slug != "" && item.Name != "" {
				items[item.Slug] = item
			}
		}
	}
	leaves := wikiDocumentLeaves(windows)
	for i, result := range results {
		local := make(map[string]bool)
		for _, group := range [][]extractedItem{result.Entities, result.Concepts} {
			for _, raw := range group {
				local[canonical[raw.Slug]] = true
			}
		}
		selectLocal := func(items []extractedItem) []extractedItem {
			var out []extractedItem
			for _, item := range items {
				if local[item.Slug] {
					out = append(out, item)
				}
			}
			return out
		}
		leaves[i].candidates = renderCandidateSlugsXML(selectLocal(entities), selectLocal(concepts))
	}

	return entities, concepts, items, nil
}

// Children stay sequential inside the root's worker: splitting never grows the
// document-wide pool, and a failed child must not suppress its sibling.
func (s *wikiIngestService) extractWindowCandidates(
	ctx context.Context, chatModel chat.Chat, window *wikiDocumentWindow, rootIndex, depth int,
	lang string, oldPageSlugs map[string]bool, batchCtx *WikiBatchContext,
) ([]combinedExtraction, error) {
	if realTextRuneCount(window.content) == 0 {
		return []combinedExtraction{{}}, nil
	}
	// Check before tenant-scoped coalescing, which treats a cancelled wait as
	// unknown even if this particular window has not sent a request.
	if err := ctx.Err(); err != nil {
		return nil, &wikiStageFailure{Stage: "wiki_candidate_slug", Outcome: wikiOutcomeNotRun, Cause: err}
	}
	result, err := s.extractRawCandidateSlugs(ctx, chatModel, window.content, lang, oldPageSlugs, batchCtx)
	if err == nil {
		return []combinedExtraction{result}, nil
	}
	if !errors.Is(err, errWikiOutputTruncated) || wikiFailureOutcome(err) != wikiOutcomeFailed ||
		len(window.chunks) < 2 || depth >= maxCandidateSplitDepth {
		return nil, err
	}
	window.split()
	logger.Infof(ctx, "wiki ingest: candidate overflow window=%d split_depth=%d left_chunks=%d right_chunks=%d",
		rootIndex, depth+1, len(window.children[0].chunks), len(window.children[1].chunks))
	var results []combinedExtraction
	failures := make([]error, len(window.children))
	for i := range window.children {
		var childResults []combinedExtraction
		childResults, failures[i] = s.extractWindowCandidates(
			ctx, chatModel, &window.children[i], rootIndex, depth+1, lang, oldPageSlugs, batchCtx,
		)
		results = append(results, childResults...)
	}
	return results, aggregateWikiStageErrors("wiki_candidate_slug", failures)
}

func mergeWindowCandidates(results []combinedExtraction) combinedExtraction {
	var merged combinedExtraction
	type location struct {
		concept bool
		index   int
	}
	bySlug := make(map[string]location)
	for _, result := range results {
		for groupIndex, group := range [][]extractedItem{result.Entities, result.Concepts} {
			for _, item := range group {
				where, exists := bySlug[item.Slug]
				if !exists {
					where = location{concept: groupIndex == 1, index: len(merged.Entities)}
					if where.concept {
						where.index = len(merged.Concepts)
					}
					first := item
					first.Aliases = nil
					if where.concept {
						merged.Concepts = append(merged.Concepts, first)
					} else {
						merged.Entities = append(merged.Entities, first)
					}
					bySlug[item.Slug] = where
				}
				dst := &merged.Entities
				if where.concept {
					dst = &merged.Concepts
				}
				for _, alias := range item.Aliases {
					(*dst)[where.index].Aliases = appendUniqueString((*dst)[where.index].Aliases, alias)
				}
			}
		}
	}
	return merged
}

func (s *wikiIngestService) extractRawCandidateSlugs(
	ctx context.Context,
	chatModel chat.Chat,
	content, lang string,
	oldPageSlugs map[string]bool,
	batchCtx *WikiBatchContext,
) (combinedExtraction, error) {
	var prevSlugsText string
	if len(oldPageSlugs) > 0 {
		var sb strings.Builder
		for slug := range oldPageSlugs {
			if !strings.HasPrefix(slug, "entity/") && !strings.HasPrefix(slug, "concept/") {
				continue
			}
			fmt.Fprintf(&sb, "- %s\n", slug)
		}
		prevSlugsText = sb.String()
	}
	if prevSlugsText == "" {
		prevSlugsText = "(none — this is a new document)"
	}

	granularity := batchCtx.ExtractionGranularity.Normalize()
	raw, err := s.generateWithTemplate(ctx, chatModel, agent.WikiCandidateSlugPrompt, map[string]string{
		"Content":             content,
		"Language":            lang,
		"PreviousSlugs":       prevSlugsText,
		"Granularity":         string(granularity),
		"GranularityGuidance": agent.WikiGranularityGuidance(string(granularity)),
		"CustomInstructions":  batchCtx.ExtractionInstructions,
		"InstructionScope":    "wiki_extraction",
	})
	if err != nil {
		return combinedExtraction{}, fmt.Errorf("candidate slug extraction failed: %w", err)
	}

	raw = cleanLLMJSON(raw)

	var result combinedExtraction
	if err := json.Unmarshal([]byte(raw), &result); err != nil {
		logger.Warnf(ctx, "wiki ingest: failed to parse candidate slug JSON: %v\nRaw: %s", err, raw)
		return combinedExtraction{}, &wikiStageFailure{
			Stage:   "wiki_candidate_slug",
			Outcome: wikiOutcomeFailed,
			Cause:   err,
		}
	}

	return result, nil
}

// chunkBatch groups chunks that will be sent in a single WikiChunkCitationPrompt call.
type chunkBatch struct {
	chunks       []*types.Chunk
	handles      *modelcontext.HandleTable
	totalRuneLen int
}

// splitChunksIntoCitationBatches partitions chunks into batches whose total
// rune count stays under maxRunesPerCitationBatch. Chunk order (by ChunkIndex)
// is preserved, and a chunk that by itself exceeds the budget occupies its
// own batch so we never silently drop content. Each chunk is assigned a short
// handle ("c000", "c001", ...) that the prompt uses in place of the raw UUID.
// The invocation-local table translates model output back to stable chunk IDs
// before any result reaches application state.
func splitChunksIntoCitationBatches(chunks []*types.Chunk) []chunkBatch {
	// Only cite text chunks — image/ocr chunks are already merged into the
	// text content via reconstructEnrichedContent and the LLM doesn't see
	// them as standalone units.
	filtered := make([]*types.Chunk, 0, len(chunks))
	for _, c := range chunks {
		if c == nil || c.Content == "" {
			continue
		}
		if c.ChunkType != types.ChunkTypeText && c.ChunkType != "" {
			continue
		}
		filtered = append(filtered, c)
	}
	if len(filtered) == 0 {
		return nil
	}

	// Preserve document order for human-readable citation
	sort.Slice(filtered, func(i, j int) bool {
		if filtered[i].ChunkIndex == filtered[j].ChunkIndex {
			return filtered[i].StartAt < filtered[j].StartAt
		}
		return filtered[i].ChunkIndex < filtered[j].ChunkIndex
	})

	var batches []chunkBatch
	newBatch := func() chunkBatch {
		return chunkBatch{handles: modelcontext.NewHandleTable("c", 3, 0)}
	}
	current := newBatch()

	flush := func() {
		if len(current.chunks) == 0 {
			return
		}
		batches = append(batches, current)
		current = newBatch()
	}

	for _, c := range filtered {
		runeLen := len([]rune(c.Content))
		// If adding this chunk would exceed the budget and the current batch
		// isn't empty, flush first so the oversized chunk is not merged with
		// already-queued ones. Oversized chunks still go through — they just
		// get their own batch.
		if len(current.chunks) > 0 && current.totalRuneLen+runeLen > maxRunesPerCitationBatch {
			flush()
		}

		current.handles.Register(c.ID)
		current.chunks = append(current.chunks, c)
		current.totalRuneLen += runeLen
	}
	flush()

	return batches
}

// renderCandidateSlugsXML renders candidate slugs as a compact list suitable
// for the prompt's <candidate_slugs> block.
func renderCandidateSlugsXML(entities, concepts []extractedItem) string {
	var sb strings.Builder
	write := func(item extractedItem, kind string) {
		aliases := ""
		if len(item.Aliases) > 0 {
			aliases = fmt.Sprintf(" aliases=%q", strings.Join(item.Aliases, ", "))
		}
		fmt.Fprintf(&sb, "- slug: %s, type: %s, name: %q%s, description: %s\n",
			item.Slug, kind, item.Name, aliases, item.Description)
	}
	for _, item := range entities {
		if item.Slug == "" || item.Name == "" {
			continue
		}
		write(item, "entity")
	}
	for _, item := range concepts {
		if item.Slug == "" || item.Name == "" {
			continue
		}
		write(item, "concept")
	}
	return sb.String()
}

// renderChunksXML formats one batch's chunks into the <chunks> block, using
// per-batch handles (c000, c001, ...) instead of raw UUIDs.
func renderChunksXML(batch chunkBatch) string {
	var sb strings.Builder
	for _, c := range batch.chunks {
		handle, _ := batch.handles.Handle(c.ID)
		fmt.Fprintf(&sb, "<c id=%q index=\"%d\">\n%s\n</c>\n", handle, c.ChunkIndex, c.Content)
	}
	return sb.String()
}

type citationClassificationOutcome struct {
	Citations   map[string][]string
	NewSlugs    []newSlugFromCitation
	BatchErrors []error // nil entry means that batch succeeded; order matches source batches.
}

func (r citationClassificationOutcome) Err() error {
	return aggregateWikiStageErrors("wiki_chunk_citation", r.BatchErrors)
}

func aggregateWikiStageErrors(stage string, batchErrors []error) error {
	var failures []error
	outcome := wikiOutcomeNotRun
	for i, err := range batchErrors {
		if err == nil {
			continue
		}
		state := wikiFailureOutcome(err)
		if state == wikiOutcomeUnknown || (state == wikiOutcomeFailed && outcome != wikiOutcomeUnknown) {
			outcome = state
		}
		failures = append(failures, fmt.Errorf("batch %d: %w", i, err))
	}
	if len(failures) == 0 {
		return nil
	}
	return &wikiStageFailure{Stage: stage, Outcome: outcome, Cause: errors.Join(failures...)}
}

// splitCitationBatch keeps source order and minimizes the rune imbalance at a
// chunk boundary. Each child starts a fresh invocation-local handle table.
func splitCitationBatch(batch chunkBatch) []chunkBatch {
	boundary, leftRunes, bestDifference := 1, 0, batch.totalRuneLen
	for i := 1; i < len(batch.chunks); i++ {
		leftRunes += utf8.RuneCountInString(batch.chunks[i-1].Content)
		difference := 2*leftRunes - batch.totalRuneLen
		if difference < 0 {
			difference = -difference
		}
		if difference < bestDifference {
			boundary, bestDifference = i, difference
		}
	}
	children := []chunkBatch{{chunks: batch.chunks[:boundary]}, {chunks: batch.chunks[boundary:]}}
	for i := range children {
		children[i].handles = modelcontext.NewHandleTable("c", 3, 0)
		for _, chunk := range children[i].chunks {
			children[i].handles.Register(chunk.ID)
			children[i].totalRuneLen += utf8.RuneCountInString(chunk.Content)
		}
	}
	return children
}

// Only known output truncation permits another call. Children run sequentially
// within their root's pool slot, even when a sibling fails; cancellation is
// checked before every attempt and successful leaves retain source order.
func (s *wikiIngestService) classifyCitationBatch(
	ctx context.Context, chatModel chat.Chat, candidates string, batch chunkBatch,
	lang string, rootIndex, depth int, parent *Span,
) (results []citationBatchResult, err error) {
	if cause := ctx.Err(); cause != nil {
		return nil, &wikiStageFailure{Stage: "wiki_chunk_citation", Outcome: wikiOutcomeNotRun, Cause: cause}
	}
	span := s.tracker().BeginSubSpan(ctx, parent, fmt.Sprintf("postprocess.wiki.classify.batch[%d]", rootIndex),
		types.SpanKindSubSpan, types.JSONMap{"batch": rootIndex, "depth": depth, "chunks": len(batch.chunks)})
	defer func() {
		if err != nil {
			s.tracker().FailSpan(ctx, span, wikiFailureOutcome(err), err.Error(), nil)
		} else {
			s.tracker().EndSpan(ctx, span, types.JSONMap{"leaves": len(results)})
		}
	}()
	raw, err := s.generateWithTemplate(ctx, chatModel, agent.WikiChunkCitationPrompt, map[string]string{
		"CandidateSlugs": candidates, "ChunksXML": renderChunksXML(batch), "Language": lang,
	})
	if err != nil {
		if !errors.Is(err, errWikiOutputTruncated) || wikiFailureOutcome(err) != wikiOutcomeFailed ||
			len(batch.chunks) < 2 || depth >= maxCitationSplitDepth {
			return nil, err
		}
		children := splitCitationBatch(batch)
		logger.Infof(ctx, "wiki ingest: citation overflow batch=%d split_depth=%d left_chunks=%d right_chunks=%d",
			rootIndex, depth+1, len(children[0].chunks), len(children[1].chunks))
		failures := make([]error, len(children))
		for i, child := range children {
			var leaves []citationBatchResult
			leaves, failures[i] = s.classifyCitationBatch(
				ctx, chatModel, candidates, child, lang, rootIndex, depth+1, span,
			)
			results = append(results, leaves...)
		}
		return results, aggregateWikiStageErrors("wiki_chunk_citation", failures)
	}
	raw = cleanLLMJSON(raw)

	var parsed citationBatchResult
	if jerr := json.Unmarshal([]byte(raw), &parsed); jerr != nil {
		return nil, &wikiStageFailure{Stage: "wiki_chunk_citation", Outcome: wikiOutcomeFailed, Cause: jerr}
	}

	// Any invalid reference makes this batch incomplete. Never silently
	// discard it and then generate from the short candidate outline.
	valid := parsed.Citations != nil
	for _, handles := range parsed.Citations {
		for _, handle := range handles {
			if _, ok := batch.handles.Resolve(handle); !ok {
				valid = false
			}
		}
	}
	for _, ns := range parsed.NewSlugs {
		if ns.Slug == "" || ns.Name == "" || len(ns.SourceChunks) == 0 {
			valid = false
		}
		for _, handle := range ns.SourceChunks {
			if _, ok := batch.handles.Resolve(handle); !ok {
				valid = false
			}
		}
	}
	if !valid {
		return nil, &wikiStageFailure{
			Stage: "wiki_chunk_citation", Outcome: wikiOutcomeFailed, Cause: errors.New("invalid citation references"),
		}
	}

	// Translate only validated batch-local handles. Store by job index;
	// completion order must not pick a new slug's first metadata.
	for slug, handleList := range parsed.Citations {
		ids := make([]string, 0, len(handleList))
		for _, handle := range handleList {
			realID, _ := batch.handles.Resolve(handle)
			ids = append(ids, realID)
		}
		parsed.Citations[slug] = ids
	}
	for i, ns := range parsed.NewSlugs {
		ids := make([]string, 0, len(ns.SourceChunks))
		for _, handle := range ns.SourceChunks {
			id, _ := batch.handles.Resolve(handle)
			ids = append(ids, id)
		}
		parsed.NewSlugs[i].SourceChunks = ids
	}
	return []citationBatchResult{parsed}, nil
}

// classifyChunkCitations runs Pass 1..N of the chunk-cited pipeline: given a
// set of candidate slugs (from Pass 0) and the document's chunks, it asks the
// LLM which chunks substantively discuss each candidate. Results across
// batches are merged into a single slug → union(chunk_id) map, and any
// "new_slugs" that Pass 0 missed are collected separately.
//
// The outcome retains successful peers and identifies every failed batch.
// Callers must not write pages unless every required batch completed.
func (s *wikiIngestService) classifyChunkCitations(
	ctx context.Context,
	chatModel chat.Chat,
	candidatesXML string,
	chunks []*types.Chunk,
	lang string,
	batchCtx *WikiBatchContext,
	parent *Span,
	windows ...[]wikiDocumentWindow,
) citationClassificationOutcome {
	if strings.TrimSpace(candidatesXML) == "" {
		return citationClassificationOutcome{Citations: map[string][]string{}}
	}
	// Flatten every window's batches into one document-wide pool. An empty
	// local candidate block is intentional: new_slugs can discover omissions.
	type citationJob struct {
		batch      chunkBatch
		candidates string
	}
	var jobs []citationJob
	scopes := []wikiDocumentWindow{{chunks: chunks, candidates: candidatesXML}}
	if len(windows) > 0 {
		scopes = windows[0]
	}
	for _, window := range wikiDocumentLeaves(scopes) {
		if len(windows) > 0 && realTextRuneCount(window.content) == 0 {
			continue
		}
		for _, batch := range splitChunksIntoCitationBatches(window.chunks) {
			jobs = append(jobs, citationJob{batch: batch, candidates: window.candidates})
		}
	}
	batchErrors := make([]error, len(jobs))
	results := make([][]citationBatchResult, len(jobs))

	eg, ectx := errgroup.WithContext(ctx)
	eg.SetLimit(maxCitationBatchConcurrency)

	for bi := range jobs {
		eg.Go(func() error {
			results[bi], batchErrors[bi] = s.classifyCitationBatch(
				ectx, chatModel, jobs[bi].candidates, jobs[bi].batch, lang, bi, 0, parent,
			)
			return nil // Preserve successful peers; children stay inside this worker.
		})
	}
	_ = eg.Wait()

	citationSet := make(map[string]map[string]bool)
	var newSlugsAll []newSlugFromCitation
	newSlugIndex := make(map[string]int)
	chunkOrder := make(map[string]int, len(chunks))
	for i, leaves := range results {
		for _, c := range jobs[i].batch.chunks {
			chunkOrder[c.ID] = len(chunkOrder)
		}
		for _, result := range leaves {
			for slug, ids := range result.Citations {
				if slug == "" {
					continue
				}
				if citationSet[slug] == nil {
					citationSet[slug] = make(map[string]bool)
				}
				for _, id := range ids {
					citationSet[slug][id] = true
				}
			}
			// A window may rediscover a document-wide candidate before another
			// window cites it normally. Union both evidence paths before sorting.
			for _, ns := range result.NewSlugs {
				if citationSet[ns.Slug] == nil {
					citationSet[ns.Slug] = make(map[string]bool)
				}
				for _, id := range ns.SourceChunks {
					citationSet[ns.Slug][id] = true
				}
				index, exists := newSlugIndex[ns.Slug]
				if !exists {
					index = len(newSlugsAll)
					newSlugIndex[ns.Slug] = index
					first := ns
					first.SourceChunks = nil
					newSlugsAll = append(newSlugsAll, first)
				}
				for _, id := range ns.SourceChunks {
					newSlugsAll[index].SourceChunks = appendUniqueString(newSlugsAll[index].SourceChunks, id)
				}
			}
		}
	}

	out := make(map[string][]string, len(citationSet))
	for slug, set := range citationSet {
		ids := make([]string, 0, len(set))
		for id := range set {
			ids = append(ids, id)
		}
		sort.SliceStable(ids, func(i, j int) bool {
			return chunkOrder[ids[i]] < chunkOrder[ids[j]]
		})
		out[slug] = ids
	}

	return citationClassificationOutcome{Citations: out, NewSlugs: newSlugsAll, BatchErrors: batchErrors}
}

// resolveCitedChunks loads the content of every chunk referenced by the
// given additions in a single batched query per knowledge ID, returning a
// map[chunkID]content. Missing / out-of-tenant chunk IDs are silently skipped
// (logged at warn level) so the Reduce phase can gracefully fall back to the
// Details paraphrase.
func (s *wikiIngestService) resolveCitedChunks(
	ctx context.Context,
	tenantID uint64,
	additions []SlugUpdate,
) map[string]string {
	// Group chunk IDs by knowledge ID — chunk repo queries are scoped by
	// tenant but not by knowledge, so we could fetch everything in one go.
	// We batch per knowledge anyway to keep the IN(...) list bounded for
	// large multi-knowledge reduces.
	byKnowledge := make(map[string]map[string]bool)
	for _, add := range additions {
		if add.KnowledgeID == "" {
			continue
		}
		for _, chunkID := range add.SourceChunks {
			if chunkID == "" {
				continue
			}
			set, ok := byKnowledge[add.KnowledgeID]
			if !ok {
				set = make(map[string]bool)
				byKnowledge[add.KnowledgeID] = set
			}
			set[chunkID] = true
		}
	}
	if len(byKnowledge) == 0 {
		return nil
	}

	out := make(map[string]string)
	for _, idSet := range byKnowledge {
		ids := make([]string, 0, len(idSet))
		for id := range idSet {
			ids = append(ids, id)
		}
		if len(ids) == 0 {
			continue
		}
		chunks, err := s.chunkRepo.ListChunksByID(ctx, tenantID, ids)
		if err != nil {
			logger.Warnf(ctx, "wiki ingest: failed to resolve cited chunks: %v", err)
			continue
		}

		// Pull image captions / OCR from the image child chunks of the cited
		// text chunks and inline them into the content, the same way the wiki
		// summary path does via reconstructEnrichedContent. Without this the
		// Reduce phase sees bare Markdown image links with no caption/OCR
		// context, so image-heavy documents degrade to "copy verbatim" or
		// "drop entirely" behavior on concept/entity pages.
		imageInfoByID := searchutil.CollectImageInfoByChunkIDs(ctx, s.chunkRepo, tenantID, ids)

		// Citation enrichment is an in-memory copy. Reload OCR Content for the
		// same image-only parents here so Reduce does not lose that evidence
		// when image_info is missing. Keep ordinary prose on its existing path.
		var scannedIDs []string
		for _, c := range chunks {
			if c != nil && c.IsEnabled && !chunkHasExtractableText(c.Content) {
				scannedIDs = append(scannedIDs, c.ID)
			}
		}
		ocrByParent := make(map[string][]*types.Chunk)
		if len(scannedIDs) > 0 {
			children, childErr := s.chunkRepo.ListChunksByParentIDs(ctx, tenantID, scannedIDs)
			if childErr != nil {
				logger.Warnf(ctx, "wiki ingest: failed to resolve cited OCR: %v", childErr)
			} else {
				inputs := append(append([]*types.Chunk(nil), chunks...), children...)
				for _, child := range scannedOCRForWiki(inputs) {
					ocrByParent[child.ParentChunkID] = append(ocrByParent[child.ParentChunkID], child)
				}
			}
		}

		for _, c := range chunks {
			if c == nil || !c.IsEnabled || c.Content == "" {
				continue
			}
			content := c.Content
			if info := imageInfoByID[c.ID]; info != "" {
				content = searchutil.EnrichContentWithImageInfo(content, info)
			}
			if ocr := ocrByParent[c.ID]; len(ocr) > 0 {
				content = appendScannedPageText(content, append([]*types.Chunk{c}, ocr...))
			}
			out[c.ID] = content
		}
	}
	return out
}

// collectCitedChunkContent materializes the verbatim content of every
// referenced chunk, concatenated in the order provided. Chunk IDs that can't
// be resolved are silently dropped (logged upstream).
func collectCitedChunkContent(chunkIDs []string, contentByID map[string]string) string {
	if len(chunkIDs) == 0 || len(contentByID) == 0 {
		return ""
	}
	var sb strings.Builder
	for _, id := range chunkIDs {
		content, ok := contentByID[id]
		if !ok || strings.TrimSpace(content) == "" {
			continue
		}
		if sb.Len() > 0 {
			sb.WriteString("\n\n")
		}
		sb.WriteString(content)
	}
	return sb.String()
}

// mergeCitationsIntoItems backfills SourceChunks on every extractedItem from
// the citation map, and augments the item slices with any genuinely new slugs
// the citation pass discovered. Items whose slug is not in citations are left
// untouched — Reduce will fall back to Description/Details for them.
//
// Returns the updated entity and concept slices plus a count of candidates
// that ended with zero citations (for observability).
func mergeCitationsIntoItems(
	entities, concepts []extractedItem,
	citations map[string][]string,
	newSlugs []newSlugFromCitation,
) ([]extractedItem, []extractedItem, int) {
	// new_slugs can rediscover a candidate from another window. Preserve that
	// batch's validated evidence before backfilling candidates below.
	if citations == nil {
		citations = make(map[string][]string)
	}
	for _, ns := range newSlugs {
		if ns.Slug != "" && ns.Name != "" {
			for _, id := range ns.SourceChunks {
				citations[ns.Slug] = appendUniqueString(citations[ns.Slug], id)
			}
		}
	}
	uncited := 0

	for i := range entities {
		ids := citations[entities[i].Slug]
		entities[i].SourceChunks = ids
		if len(ids) == 0 {
			uncited++
		}
	}
	for i := range concepts {
		ids := citations[concepts[i].Slug]
		concepts[i].SourceChunks = ids
		if len(ids) == 0 {
			uncited++
		}
	}

	// Append new_slugs discovered by the citation pass, avoiding duplicates.
	existingSlugs := make(map[string]bool, len(entities)+len(concepts))
	for _, e := range entities {
		existingSlugs[e.Slug] = true
	}
	for _, c := range concepts {
		existingSlugs[c.Slug] = true
	}

	// Aggregate per-slug across batches so the same "newly discovered" slug
	// surfacing in multiple batches merges into a single item.
	type mergedNew struct {
		item extractedItem
		typ  string
	}
	merged := make(map[string]*mergedNew)
	slugOrder := []string{}

	for _, ns := range newSlugs {
		if ns.Slug == "" || ns.Name == "" {
			continue
		}
		if existingSlugs[ns.Slug] {
			// Treat as citation for existing candidate
			continue
		}
		kind := strings.TrimSpace(strings.ToLower(ns.Type))
		if kind == "" {
			if strings.HasPrefix(ns.Slug, "concept/") {
				kind = "concept"
			} else {
				kind = "entity"
			}
		}
		existing, ok := merged[ns.Slug]
		if !ok {
			existing = &mergedNew{
				item: extractedItem{
					Name:         ns.Name,
					Slug:         ns.Slug,
					Aliases:      append([]string(nil), ns.Aliases...),
					Description:  ns.Description,
					Details:      ns.Details,
					SourceChunks: append([]string(nil), ns.SourceChunks...),
				},
				typ: kind,
			}
			merged[ns.Slug] = existing
			slugOrder = append(slugOrder, ns.Slug)
			continue
		}
		// Union source chunks
		seen := make(map[string]bool, len(existing.item.SourceChunks))
		for _, id := range existing.item.SourceChunks {
			seen[id] = true
		}
		for _, id := range ns.SourceChunks {
			if !seen[id] {
				existing.item.SourceChunks = append(existing.item.SourceChunks, id)
				seen[id] = true
			}
		}
	}

	for _, slug := range slugOrder {
		m := merged[slug]
		if m.typ == "concept" {
			concepts = append(concepts, m.item)
		} else {
			entities = append(entities, m.item)
		}
	}

	return entities, concepts, uncited
}
