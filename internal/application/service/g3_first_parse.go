package service

import (
	"context"
	"fmt"
	werrors "github.com/Tencent/WeKnora/internal/errors"
	"github.com/Tencent/WeKnora/internal/infrastructure/chunker"

	"github.com/Tencent/WeKnora/internal/enterprise/capture"
	"github.com/Tencent/WeKnora/internal/enterprise/source"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

// The capture kernel lives in internal/enterprise/capture (S7d-2c-1). These aliases and the thin
// delegates below keep the legacy 830/G3 callers compiling until they are deleted in S7d-2c-3.
type (
	g3FirstParseIdentity = capture.Identity
	g3FirstParseRange    = capture.Range
	g3FirstParseRecord   = capture.Record
)

// G3FirstParseStore keeps the first-parse captures of enterprise Space PDFs (internal/enterprise/capture).
// It never calls a parser. Each call opens the captures under root with keys, so a test may point
// root elsewhere.
type G3FirstParseStore struct {
	root string
	keys *capture.Keys
}

// NewG3FirstParseStore keeps captures in the deployment's capture directory, sealed with keys from
// the citation token signing ring.
func NewG3FirstParseStore(keys *capture.Keys) *G3FirstParseStore {
	return &G3FirstParseStore{root: capture.DefaultRoot(), keys: keys}
}

func (s *G3FirstParseStore) captures() *capture.Store { return capture.NewStore(s.root, s.keys) }

// ReadSourceArtifact reads an exact historical capture. The caller must resolve
// an authorized Space/RAW scope; this method independently checks Knowledge's
// tenant and RAW ownership before opening any signed artifact. It never parses.
func (s *G3FirstParseStore) ReadSourceArtifact(
	ctx context.Context, repo interfaces.KnowledgeRepository, scope types.WikiReleaseScope,
	knowledgeID string, attempt int64,
) (*source.Artifact, error) {
	var store *capture.Store
	if s != nil {
		store = s.captures()
	}
	reader, _ := repo.(capture.KnowledgeReader)
	return capture.ReadSourceArtifact(ctx, store, reader, scope, knowledgeID, attempt)
}

func g3FirstParseKey(id g3FirstParseIdentity) (string, error) { return capture.Key(id) }
func g3FirstParseResult(record *g3FirstParseRecord) *types.ReadResult {
	return capture.ReadResult(record)
}
func validateG3FirstParse(record *g3FirstParseRecord, id g3FirstParseIdentity) error {
	return capture.Validate(record, id)
}

// firstParseStore opens captures under this store's root with the citation signing ring. It is
// built per call because tests and wiring may replace root or codec after construction.
func (s *G3FirstParseStore) save(id g3FirstParseIdentity, result *types.ReadResult, chunks []types.ParsedChunk, origin ...*types.DocumentDocReaderReuseReference) error {
	if s == nil || len(origin) > 1 {
		return capture.ErrUnavailable
	}
	var reference *types.DocumentDocReaderReuseReference
	if len(origin) == 1 {
		reference = origin[0]
	}
	return s.captures().Save(id, result, chunks, reference)
}
func g3FirstParseBindings(record *g3FirstParseRecord, manifest []types.RevisionManifestChunk) (map[string]g3FirstParseRange, error) {
	if record == nil || len(manifest) == 0 {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	byKey := map[string]g3FirstParseRange{}
	for _, r := range record.Chunks {
		key := fmt.Sprintf("%d:%s", r.Index, r.ContentSHA256)
		if _, duplicate := byKey[key]; duplicate {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		byKey[key] = r
	}
	used := map[string]bool{}
	result := map[string]g3FirstParseRange{}
	runes := []rune(record.Markdown)
	for _, chunk := range manifest {
		key := fmt.Sprintf("%d:%s", chunk.Index, testSHA256830G2(chunk.Content))
		r, ok := byKey[key]
		if !ok || chunk.ID == "" || used[key] || !g3FirstParseRangeMatchesRunes(runes, chunk.Content, r) {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		if _, duplicate := result[chunk.ID]; duplicate {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		result[chunk.ID] = r
		used[key] = true
	}
	// The signed capture may also contain parent/context ranges. Canonical
	// revisions contain text chunks only: bind every manifest member exactly,
	// without promoting unused capture ranges into the revision or its output.
	return result, nil
}
func g3FirstParseRecordSHA(record *g3FirstParseRecord) string { return capture.RecordSHA256(record) }
func g3FirstParseIdentityForSource(scope types.WikiReleaseScope, source *types.KnowledgeRevisionSource) g3FirstParseIdentity {
	return g3FirstParseIdentity{TenantID: scope.TenantID, RawKBID: scope.RawKBID, KnowledgeID: source.KnowledgeID, ParseAttempt: source.ParseAttempt, SourceSHA256: source.FileSHA256}
}

func g3ExactSourceChunks(markdown string, chunks []types.ParsedChunk) ([]types.ParsedChunk, error) {
	return capture.ExactChunks(markdown, chunks)
}
func g3FirstParseRangeMatches(markdown, content string, r g3FirstParseRange) bool {
	return g3FirstParseRangeMatchesRunes([]rune(markdown), content, r)
}

// Batch callers reuse a single code-point view. Bounds, exact Unicode content
// and the recorded content hash are still checked independently for every range.
func g3FirstParseRangeMatchesRunes(runes []rune, content string, r g3FirstParseRange) bool {
	return r.Start >= 0 && r.End > r.Start && r.End <= len(runes) && string(runes[r.Start:r.End]) == content && testSHA256830G2(content) == r.ContentSHA256
}
func (s *knowledgeService) failG3FirstParse(ctx context.Context, knowledge *types.Knowledge, cause error) error {
	s.failStage(ctx, knowledge.ID, types.StageDocReader, werrors.ErrCodeDocReaderParseFailed, "G3 first parse artifact unavailable", cause)
	_, err := s.failKnowledge(ctx, knowledge, true, "G3_FIRST_PARSE_ARTIFACT_UNAVAILABLE: %v", cause)
	return err
}

func g3FirstParseSplitParentChild(text string, parentCfg, childCfg chunker.SplitterConfig) (chunker.ParentChildResult, error) {
	return capture.SplitParentChild(text, parentCfg, childCfg)
}
