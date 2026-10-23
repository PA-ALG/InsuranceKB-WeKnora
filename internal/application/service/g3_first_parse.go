package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	werrors "github.com/Tencent/WeKnora/internal/errors"
	"github.com/Tencent/WeKnora/internal/infrastructure/chunker"
	"os"
	"path/filepath"
	"strings"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/config"
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

// G3FirstParseStore shares only file storage and signing primitives with citation
// reuse. It has no KnowledgeService dependency and never calls a parser.
type G3FirstParseStore struct{ reuse *conceptSourceReuseStore830G3 }

func NewG3FirstParseStore(codec *SchemaWikiCitationTokenCodec) *G3FirstParseStore {
	return &G3FirstParseStore{reuse: newConceptSourceReuseStore830G3(codec)}
}

// ReadSourceArtifact reads an exact historical capture. The caller must resolve
// an authorized Space/RAW scope; this method independently checks Knowledge's
// tenant and RAW ownership before opening any signed artifact. It never parses.
func (s *G3FirstParseStore) ReadSourceArtifact(
	ctx context.Context, repo interfaces.KnowledgeRepository, scope types.WikiReleaseScope,
	knowledgeID string, attempt int64,
) (*source.Artifact, error) {
	var store *capture.Store
	if s != nil && s.reuse != nil {
		store = s.reuse.firstParseStore()
	}
	reader, _ := repo.(capture.KnowledgeReader)
	return capture.ReadSourceArtifact(ctx, store, reader, scope, knowledgeID, attempt)
}

func NewConceptSourceAuthorityService830G2WithFirstParse(fixed *KnowledgeRevisionSourceService, knowledge interfaces.KnowledgeRepository, chunks interfaces.ChunkRepository, reader interfaces.DocumentReader, codec *SchemaWikiCitationTokenCodec, releases *wikirepository.WikiReleaseRepository, legacy SchemaWikiCitationContentPort, preview *wikirepository.SchemaWikiFormalCandidatePreviewRegistry, first *G3FirstParseStore) *ConceptSourceAuthorityService830G2 {
	s := NewConceptSourceAuthorityService830G2(fixed, knowledge, chunks, reader, codec, releases, legacy, preview)
	if first != nil {
		s.sourceReuse = first.reuse
	}
	return s
}
func g3FirstParseScope(cfg *config.Config, knowledge *types.Knowledge, fileType string) bool {
	if cfg == nil || cfg.G3PlatformProcessing == nil || knowledge == nil {
		return false
	}
	c := cfg.G3PlatformProcessing
	return c.Enabled && c.TenantID > 0 && c.RawKBID != "" && knowledge.TenantID == c.TenantID && knowledge.KnowledgeBaseID == c.RawKBID && strings.EqualFold(fileType, "pdf")
}
func g3FirstParseConfig(eff types.EffectiveProcessConfig) types.EffectiveProcessConfig {
	rules := []types.ParserEngineRule{{FileTypes: []string{"pdf"}, Engine: "builtin"}}
	eff.ChunkingConfig.ParserEngineRules = append(rules, eff.ChunkingConfig.ParserEngineRules...)
	return eff
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
func (s *conceptSourceReuseStore830G3) firstParseStore() *capture.Store {
	var keys *capture.Keys
	if s.codec != nil {
		keys = capture.NewKeys(s.codec.activeKeyID, s.codec.privateKeys)
	}
	return capture.NewStore(s.root, keys)
}
func (s *conceptSourceReuseStore830G3) readFirstParse(id g3FirstParseIdentity) (*g3FirstParseRecord, error) {
	if s == nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	return s.firstParseStore().Read(id)
}
func (s *G3FirstParseStore) save(id g3FirstParseIdentity, result *types.ReadResult, chunks []types.ParsedChunk, origin ...*types.DocumentDocReaderReuseReference) error {
	if s == nil || s.reuse == nil || len(origin) > 1 {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	var reference *types.DocumentDocReaderReuseReference
	if len(origin) == 1 {
		reference = origin[0]
	}
	return s.reuse.firstParseStore().Save(id, result, chunks, reference)
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
func conceptSourceReuseKey830G3(identity types.ConceptSourceIdentity830G2, binding string) (string, error) {
	data, err := canonicalJSON830G2(struct {
		Source  types.ConceptSourceIdentity830G2
		Binding string
	}{identity, binding})
	if err != nil {
		return "", err
	}
	return testSHA256Bytes830G2(data), nil
}
func (s *conceptSourceReuseStore830G3) validateFirstParseCache(record *conceptSourceReuseRecord830G3) error {
	return s.validateFirstParseCacheProof(record, nil)
}

func (s *conceptSourceReuseStore830G3) validateFirstParseCacheProof(record *conceptSourceReuseRecord830G3, proof *conceptSourceBindingProof830G3) error {
	id := g3FirstParseIdentity{TenantID: record.Identity.TenantID, RawKBID: record.Identity.RawKBID, KnowledgeID: record.Identity.KnowledgeID, ParseAttempt: record.Identity.ParseAttempt, SourceSHA256: record.Identity.SourceHash}
	key, err := g3FirstParseKey(id)
	if err != nil {
		return err
	}
	data, err := s.readArtifact(filepath.Join(s.root, key+".json"), key)
	if errors.Is(err, os.ErrNotExist) && record.FirstParseSHA256 == "" {
		return nil
	} // frozen legacy sources only
	if err != nil {
		return err
	}
	// A first artifact that exists makes legacy same-key caches ineligible.
	if record.FirstParseSHA256 == "" || testSHA256Bytes830G2(data) != record.FirstParseSHA256 {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	// The current signature and complete payload digest still passed above.
	// Identical authenticated bytes have the same already-proved bindings to
	// this exact immutable owned record; avoid reconstructing them per quote.
	if proof.matches(record) {
		return nil
	}
	var first g3FirstParseRecord
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&first) != nil || !jsonEOF830G2(decoder) || first.Contract != capture.Contract ||
		first.Identity != id {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	// The native index is already owned/validated by the cached record. Only the
	// signed first capture and its complete binding are reopened on a cache hit.
	return g3CachedFirstParseMatches(&first, record)
}
func g3CachedFirstParseMatches(first *g3FirstParseRecord, record *conceptSourceReuseRecord830G3) error {
	if first == nil || record == nil || record.FirstParseSHA256 != g3FirstParseRecordSHA(first) || first.ParserIdentitySHA256 != record.Identity.ParserIdentity || first.Markdown != record.Markdown || first.Native == nil || record.Native == nil || first.Native.SanitizedSHA256 != record.Native.SanitizedSHA256 || first.Native.SourceSHA256 != record.Native.SourceSHA256 {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	ranges, err := g3FirstParseBindings(first, record.Chunks)
	if err != nil {
		return err
	}
	if len(ranges) != len(record.ChunkRanges) {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	for id, r := range ranges {
		if stored, ok := record.ChunkRanges[id]; !ok || stored != r {
			return ErrConceptSourceAuthorityUnavailable830G2
		}
	}
	return nil
}

// Link publishes an immutable artifact without a cross-process overwrite race. Captures are now
// written by capture.Store.Save; only the legacy DocReader recovery test still writes a hand-made
// record through here, and both go with the G3 reparse path in S7d-2c-2.
func (s *conceptSourceReuseStore830G3) writeFirstParseArtifact(path, key string, data []byte) error {
	encoded, err := sealConceptDerivedArtifact830G3(s.codec, "weknora.concept-source-reuse.830.g3.v1", key, data)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(s.root, 0700); err != nil {
		return err
	}
	temp, err := os.CreateTemp(s.root, ".first-parse-*")
	if err != nil {
		return err
	}
	defer os.Remove(temp.Name())
	_, err = temp.Write(encoded)
	if err == nil {
		err = temp.Sync()
	}
	closeErr := temp.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	if err = os.Link(temp.Name(), path); errors.Is(err, os.ErrExist) {
		old, readErr := s.readArtifact(path, key)
		if readErr != nil {
			return readErr
		}
		if !bytes.Equal(old, data) {
			return ErrConceptSourceAuthorityUnavailable830G2
		}
		return nil
	}
	return err
}

func (s *knowledgeService) failG3FirstParse(ctx context.Context, knowledge *types.Knowledge, cause error) error {
	s.failStage(ctx, knowledge.ID, types.StageDocReader, werrors.ErrCodeDocReaderParseFailed, "G3 first parse artifact unavailable", cause)
	_, err := s.failKnowledge(ctx, knowledge, true, "G3_FIRST_PARSE_ARTIFACT_UNAVAILABLE: %v", cause)
	return err
}

func g3FirstParseSplitParentChild(text string, parentCfg, childCfg chunker.SplitterConfig) (chunker.ParentChildResult, error) {
	return capture.SplitParentChild(text, parentCfg, childCfg)
}
