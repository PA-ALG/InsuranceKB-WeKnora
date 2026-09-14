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
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

const g3FirstParseContract = "g3-first-parse.830.v1"

type g3FirstParseIdentity struct {
	TenantID     uint64 `json:"tenant_id"`
	RawKBID      string `json:"raw_kb_id"`
	KnowledgeID  string `json:"knowledge_id"`
	ParseAttempt int64  `json:"parse_attempt"`
	SourceSHA256 string `json:"source_sha256"`
}
type g3FirstParseRange struct {
	Index         int    `json:"index"`
	Start         int    `json:"start"`
	End           int    `json:"end"`
	ContentSHA256 string `json:"content_sha256"`
}
type g3FirstParseRecord struct {
	Contract             string                         `json:"contract"`
	Identity             g3FirstParseIdentity           `json:"identity"`
	ParserIdentitySHA256 string                         `json:"parser_identity_sha256"`
	Markdown             string                         `json:"markdown"`
	Native               *types.NativeStructureArtifact `json:"native"`
	Chunks               []g3FirstParseRange            `json:"chunks"`
}

// G3FirstParseStore shares only file storage and signing primitives with citation
// reuse. It has no KnowledgeService dependency and never calls a parser.
type G3FirstParseStore struct{ reuse *conceptSourceReuseStore830G3 }

func NewG3FirstParseStore(codec *SchemaWikiCitationTokenCodec) *G3FirstParseStore {
	return &G3FirstParseStore{reuse: newConceptSourceReuseStore830G3(codec)}
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
func g3FirstParseKey(id g3FirstParseIdentity) (string, error) {
	if id.TenantID == 0 || id.RawKBID == "" || id.KnowledgeID == "" || id.ParseAttempt <= 0 || !validServiceSHA256(id.SourceSHA256) {
		return "", ErrConceptSourceAuthorityUnavailable830G2
	}
	data, err := canonicalJSON830G2(id)
	if err != nil {
		return "", err
	}
	return "first-" + testSHA256Bytes830G2(append([]byte(g3FirstParseContract+"\x00"), data...)), nil
}
func g3FirstParseResult(record *g3FirstParseRecord) *types.ReadResult {
	return &types.ReadResult{MarkdownContent: record.Markdown, NativeStructure: record.Native}
}
func validateG3FirstParse(record *g3FirstParseRecord, id g3FirstParseIdentity) error {
	if record == nil || record.Contract != g3FirstParseContract || record.Identity != id || len(record.Chunks) == 0 {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	if _, err := prepareConceptNativeQuoteIndex830G2(g3FirstParseResult(record), id.SourceSHA256, record.ParserIdentitySHA256); err != nil {
		return err
	}
	runes := []rune(record.Markdown)
	seen := map[string]bool{}
	for _, r := range record.Chunks {
		key := fmt.Sprintf("%d:%s", r.Index, r.ContentSHA256)
		if r.Index < 0 || r.Start < 0 || r.End <= r.Start || r.End > len(runes) || testSHA256830G2(string(runes[r.Start:r.End])) != r.ContentSHA256 || seen[key] {
			return ErrConceptSourceAuthorityUnavailable830G2
		}
		seen[key] = true
	}
	return nil
}
func (s *conceptSourceReuseStore830G3) readFirstParse(id g3FirstParseIdentity) (*g3FirstParseRecord, error) {
	if s == nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	key, err := g3FirstParseKey(id)
	if err != nil {
		return nil, err
	}
	data, err := s.readArtifact(filepath.Join(s.root, key+".json"), key)
	if err != nil {
		return nil, err
	}
	var record g3FirstParseRecord
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&record) != nil || !jsonEOF830G2(decoder) {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	if err := validateG3FirstParse(&record, id); err != nil {
		return nil, err
	}
	return &record, nil
}
func (s *G3FirstParseStore) save(id g3FirstParseIdentity, result *types.ReadResult, chunks []types.ParsedChunk) error {
	if s == nil || s.reuse == nil || result == nil || result.Error != "" || result.NativeStructure == nil || len(result.ImageRefs) > 0 || result.IsAudio {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	key, err := g3FirstParseKey(id)
	if err != nil {
		return err
	}
	var projection conceptNativeProjection830G2
	if json.Unmarshal(result.NativeStructure.SanitizedJSON, &projection) != nil {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	record := g3FirstParseRecord{Contract: g3FirstParseContract, Identity: id, ParserIdentitySHA256: projection.ParserIdentitySHA256, Markdown: result.MarkdownContent, Native: result.NativeStructure, Chunks: []g3FirstParseRange{}}
	seen := map[string]g3FirstParseRange{}
	for _, chunk := range chunks {
		if strings.TrimSpace(chunk.Content) == "" {
			continue
		}
		r := g3FirstParseRange{Index: chunk.Seq, Start: chunk.Start, End: chunk.End, ContentSHA256: testSHA256830G2(chunk.Content)}
		k := fmt.Sprintf("%d:%s", r.Index, r.ContentSHA256)
		if old, ok := seen[k]; ok {
			if old != r {
				return ErrConceptSourceAuthorityUnavailable830G2
			}
			continue
		}
		seen[k] = r
		record.Chunks = append(record.Chunks, r)
	}
	if err := validateG3FirstParse(&record, id); err != nil {
		return err
	}
	data, err := json.Marshal(record)
	if err != nil {
		return err
	}
	// The same attempt cannot silently acquire another parse or chunk plan.
	s.reuse.mu.Lock()
	defer s.reuse.mu.Unlock()
	path := filepath.Join(s.reuse.root, key+".json")
	old, err := s.reuse.readArtifact(path, key)
	if err == nil {
		if !bytes.Equal(old, data) {
			return ErrConceptSourceAuthorityUnavailable830G2
		}
		return nil
	}
	if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return s.reuse.writeFirstParseArtifact(path, key, data)
}
func g3FirstParseBindings(record *g3FirstParseRecord, manifest []types.RevisionManifestChunk) (map[string]g3FirstParseRange, error) {
	byKey := map[string]g3FirstParseRange{}
	for _, r := range record.Chunks {
		byKey[fmt.Sprintf("%d:%s", r.Index, r.ContentSHA256)] = r
	}
	used := map[string]bool{}
	result := map[string]g3FirstParseRange{}
	for _, chunk := range manifest {
		key := fmt.Sprintf("%d:%s", chunk.Index, testSHA256830G2(chunk.Content))
		r, ok := byKey[key]
		if !ok || chunk.ID == "" {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		if _, duplicate := result[chunk.ID]; duplicate {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		result[chunk.ID] = r
		used[key] = true
	}
	if len(used) != len(byKey) {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	return result, nil
}
func g3FirstParseRecordSHA(record *g3FirstParseRecord) string {
	data, _ := json.Marshal(record)
	return testSHA256Bytes830G2(data)
}
func g3FirstParseIdentityForSource(scope types.WikiReleaseScope, source *types.KnowledgeRevisionSource) g3FirstParseIdentity {
	return g3FirstParseIdentity{TenantID: scope.TenantID, RawKBID: scope.RawKBID, KnowledgeID: source.KnowledgeID, ParseAttempt: source.ParseAttempt, SourceSHA256: source.FileSHA256}
}

// Existing chunkers may prepend a table header. It is context, never source.
func g3ExactSourceChunks(markdown string, chunks []types.ParsedChunk) ([]types.ParsedChunk, error) {
	result := append([]types.ParsedChunk(nil), chunks...)
	runes := []rune(markdown)
	for i := range result {
		c := &result[i]
		if c.Start < 0 || c.End <= c.Start || c.End > len(runes) {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		exact := string(runes[c.Start:c.End])
		if c.Content != exact {
			if !strings.HasSuffix(c.Content, exact) {
				return nil, ErrConceptSourceAuthorityUnavailable830G2
			}
			header := strings.TrimSuffix(c.Content, exact)
			if c.ContextHeader != "" {
				c.ContextHeader += "\n\n"
			}
			c.ContextHeader += header
			c.Content = exact
		}
	}
	return result, nil
}
func g3FirstParseRangeMatches(markdown, content string, r g3FirstParseRange) bool {
	runes := []rune(markdown)
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
	var first g3FirstParseRecord
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&first) != nil || !jsonEOF830G2(decoder) || first.Contract != g3FirstParseContract || first.Identity != id {
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

// Link publishes an immutable artifact without a cross-process overwrite race.
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

// Normalize the parent content before splitting children. The generic chunker
// can add a contextual table header; splitting that synthetic prefix first
// would shift every child coordinate relative to the original document.
func g3FirstParseSplitParentChild(text string, parentCfg, childCfg chunker.SplitterConfig) (chunker.ParentChildResult, error) {
	result := chunker.ParentChildResult{}
	parents := chunker.Split(text, parentCfg)
	seq := 0
	for _, p := range parents {
		exact, err := g3ExactSourceChunks(text, []types.ParsedChunk{{Content: p.Content, ContextHeader: p.ContextHeader, Start: p.Start, End: p.End, Seq: p.Seq}})
		if err != nil {
			return result, err
		}
		p.Content = exact[0].Content
		p.ContextHeader = exact[0].ContextHeader
		children := chunker.Split(p.Content, childCfg)
		parentIndex := -1
		if len(children) > 1 || (len(children) == 1 && children[0].Content != p.Content) {
			parentIndex = len(result.Parents)
			result.Parents = append(result.Parents, p)
		}
		for _, c := range children {
			exact, err := g3ExactSourceChunks(p.Content, []types.ParsedChunk{{Content: c.Content, ContextHeader: c.ContextHeader, Start: c.Start, End: c.End, Seq: c.Seq}})
			if err != nil {
				return result, err
			}
			c.Content = exact[0].Content
			c.ContextHeader = exact[0].ContextHeader
			if p.ContextHeader != "" {
				if c.ContextHeader != "" {
					c.ContextHeader = p.ContextHeader + "\n\n" + c.ContextHeader
				} else {
					c.ContextHeader = p.ContextHeader
				}
			}
			c.Start += p.Start
			c.End += p.Start
			c.Seq = seq
			seq++
			result.Children = append(result.Children, chunker.ChildChunk{Chunk: c, ParentIndex: parentIndex})
		}
	}
	for i := range result.Parents {
		result.Parents[i].Seq = i
	}
	for i := range result.Children {
		result.Children[i].Seq = len(result.Parents) + i
	}
	return result, nil
}
