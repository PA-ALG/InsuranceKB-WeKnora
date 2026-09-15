package service

import (
	"context"
	"crypto/ed25519"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"

	"github.com/Tencent/WeKnora/internal/types"
	"golang.org/x/sync/singleflight"
)

// These are derived artifacts in the existing persistent file volume, never a
// source or release authority. Every read first checks the current fixed binding.
const conceptSourceReuseContract830G3 = "concept-source-reuse.830.g3.v1"

type conceptSourceReusePrepareKey830G3 struct{}
type conceptSourceReuseImportKey830G3 struct{}
type conceptSourceReuseRecord830G3 struct {
	Contract         string                           `json:"contract"`
	Identity         types.ConceptSourceIdentity830G2 `json:"identity"`
	BindingDigest    string                           `json:"binding_digest"`
	Chunks           []types.RevisionManifestChunk    `json:"chunks"`
	Markdown         string                           `json:"markdown"`
	Native           *types.NativeStructureArtifact   `json:"native"`
	FirstParseSHA256 string                           `json:"first_parse_sha256,omitempty"`
	ChunkRanges      map[string]g3FirstParseRange     `json:"chunk_ranges,omitempty"`
}
type conceptSourceReusePrepared830G3 struct {
	blocks map[string]string
	index  *conceptNativeQuoteIndex830G2
	record conceptSourceReuseRecord830G3
	proof  *conceptSourceBindingProof830G3
}

// Installed only after complete cold validation, before publishing the owned
// immutable entry. A copied prepared record cannot inherit another's proof.
type conceptSourceBindingProof830G3 struct {
	owned       *conceptSourceReuseRecord830G3
	firstSHA256 string
}

func (p *conceptSourceBindingProof830G3) matches(record *conceptSourceReuseRecord830G3) bool {
	return p != nil && p.owned == record && p.firstSHA256 == record.FirstParseSHA256
}

type conceptSourceReuseStore830G3 struct {
	codec   *SchemaWikiCitationTokenCodec
	root    string
	mu      sync.Mutex
	entries map[string]*conceptSourceReusePrepared830G3
	flight  singleflight.Group
}

func newConceptSourceReuseStore830G3(codec *SchemaWikiCitationTokenCodec) *conceptSourceReuseStore830G3 {
	base := strings.TrimSpace(os.Getenv("LOCAL_STORAGE_BASE_DIR"))
	if base == "" {
		base = "/data/files"
	}
	return &conceptSourceReuseStore830G3{codec: codec, root: filepath.Join(base, ".concept-source-reuse-v1"), entries: map[string]*conceptSourceReusePrepared830G3{}}
}

// PrepareConceptSourceReuse830G3 is called by source preparation, not serving
// GETs. A captured ReadResult can be imported; nil uses one fixed-file DocReader
// capture. The caller must already hold the same source/release ACL as review.
func (s *ConceptSourceAuthorityService830G2) PrepareConceptSourceReuse830G3(ctx context.Context, scope types.WikiReleaseScope, evidence types.ConceptEvidence830G2, block types.ConceptSourceBlock830G2, captured *types.ReadResult) error {
	ctx = context.WithValue(ctx, conceptSourceReusePrepareKey830G3{}, true)
	if captured != nil {
		ctx = context.WithValue(ctx, conceptSourceReuseImportKey830G3{}, captured)
	}
	_, _, _, err := s.verifyEvidenceLocated830G3(ctx, scope, evidence, &block, true)
	return err
}

func (s *ConceptSourceAuthorityService830G2) verifyReusableConceptSource830G3(ctx context.Context, scope types.WikiReleaseScope, evidence types.ConceptEvidence830G2, block *types.ConceptSourceBlock830G2, trustedG3 bool, knowledge *types.Knowledge, source *types.KnowledgeRevisionSource, resource *types.StoredResource) (*types.KnowledgeRevisionSource, ConceptCitationBBox830G2, *ConceptSourceBlockLocator830G3, error) {
	empty := ConceptCitationBBox830G2{}
	// ReadFixedRevision performs these same resource checks on bytes. Retain them
	// for locator-only reads, which intentionally no longer open the PDF.
	if source.RetentionState != types.KnowledgeRevisionSourcePinned || resource.Handle != source.ResourceHandle || resource.ContentHash != source.ObjectSHA256 || resource.State != types.ResourceStateActive || resource.Lifecycle != types.ResourceLifecyclePersistent {
		return nil, empty, nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	key, keyErr := conceptSourceReuseKey830G3(evidence.ConceptSourceIdentity830G2, source.BindingDigest)
	if keyErr != nil {
		return nil, empty, nil, keyErr
	}
	allow, _ := ctx.Value(conceptSourceReusePrepareKey830G3{}).(bool)
	prepared, err := s.sourceReuse.load(ctx, key, evidence.ConceptSourceIdentity830G2, source, func() (*conceptSourceReuseRecord830G3, error) {
		if trustedG3 && !allow {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		chunks, err := s.chunks.ListChunksByKnowledgeID(ctx, scope.TenantID, evidence.KnowledgeID)
		if err != nil {
			return nil, err
		}
		manifest := []types.RevisionManifestChunk{}
		for _, chunk := range chunks {
			if chunk == nil || chunk.ParseAttempt != evidence.ParseAttempt {
				continue
			}
			if chunk.TenantID != scope.TenantID || chunk.KnowledgeID != evidence.KnowledgeID || chunk.KnowledgeBaseID != scope.RawKBID {
				return nil, ErrConceptSourceAuthorityUnavailable830G2
			}
			manifest = append(manifest, types.RevisionManifestChunk{ID: chunk.ID, Index: chunk.ChunkIndex, Content: chunk.Content})
		}
		sort.Slice(manifest, func(i, j int) bool { return manifest[i].Index < manifest[j].Index })
		digest, err := types.ComputeRevisionManifestDigest(evidence.KnowledgeID, evidence.ParseAttempt, manifest)
		if err != nil || digest != source.ManifestDigest || len(manifest) != source.ChunkCount {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		first, firstErr := s.sourceReuse.readFirstParse(g3FirstParseIdentityForSource(scope, source))
		if firstErr == nil {
			ranges, err := g3FirstParseBindings(first, manifest)
			if err != nil || first.ParserIdentitySHA256 != evidence.ParserIdentity {
				return nil, ErrConceptSourceAuthorityUnavailable830G2
			}
			return &conceptSourceReuseRecord830G3{Contract: conceptSourceReuseContract830G3, Identity: evidence.ConceptSourceIdentity830G2, BindingDigest: source.BindingDigest, Chunks: manifest, Markdown: first.Markdown, Native: first.Native, FirstParseSHA256: g3FirstParseRecordSHA(first), ChunkRanges: ranges}, nil
		}
		if !errors.Is(firstErr, os.ErrNotExist) {
			return nil, firstErr
		}
		pdf, err := s.fixed.ReadFixedRevision(ctx, evidence.KnowledgeID, evidence.ParseAttempt, source.FileSHA256, source.BindingDigest, evidence.PageNumber)
		if err != nil || testSHA256Bytes830G2(pdf) != evidence.SourceHash {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		result, _ := ctx.Value(conceptSourceReuseImportKey830G3{}).(*types.ReadResult)
		if result == nil {
			result, err = s.docreader.Read(ctx, &types.ReadRequest{FileContent: pdf, FileName: knowledge.FileName, FileType: "pdf", ParserEngine: "builtin", ParserEngineOverrides: map[string]string{"pdf_native_structure_capture": conceptNativeCapture830G2}})
		}
		if err != nil || result == nil || result.Error != "" {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		return &conceptSourceReuseRecord830G3{Contract: conceptSourceReuseContract830G3, Identity: evidence.ConceptSourceIdentity830G2, BindingDigest: source.BindingDigest, Chunks: manifest, Markdown: result.MarkdownContent, Native: result.NativeStructure}, nil
	})
	if err != nil {
		return nil, empty, nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	text, found := prepared.blocks[evidence.BlockID]
	if !found || (block != nil && (block.ConceptSourceIdentity830G2 != evidence.ConceptSourceIdentity830G2 || block.BlockID != evidence.BlockID || block.PageNumber != evidence.PageNumber || block.SourceType != evidence.SourceType || block.Text != text)) {
		return nil, empty, nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	runes := []rune(text)
	if evidence.End > len(runes) || string(runes[evidence.Start:evidence.End]) != evidence.Quote {
		return nil, empty, nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	var bbox ConceptCitationBBox830G2
	var locator *ConceptSourceBlockLocator830G3
	if trustedG3 {
		if block == nil {
			return nil, empty, nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		bbox, locator, err = resolveConceptSourceBlockQuote830G3(prepared.index, evidence, *block, prepared.record.ChunkRanges)
	} else {
		bbox, err = resolveConceptNativeQuoteInIndex830G2(prepared.index, evidence.SourceHash, evidence.ParserIdentity, evidence.PageNumber, evidence.Quote)
	}
	if err != nil {
		return nil, empty, nil, err
	}
	return source, bbox, locator, nil
}

func validateConceptSourceReuse830G3(record *conceptSourceReuseRecord830G3, identity types.ConceptSourceIdentity830G2, source *types.KnowledgeRevisionSource) (*conceptSourceReusePrepared830G3, error) {
	expected := identity
	if expected.ParserIdentity == "" {
		if !validServiceSHA256(record.Identity.ParserIdentity) {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		expected.ParserIdentity = record.Identity.ParserIdentity
	}
	if record.Contract != conceptSourceReuseContract830G3 || record.Identity != expected || record.BindingDigest != source.BindingDigest || len(record.Chunks) != source.ChunkCount {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	digest, err := types.ComputeRevisionManifestDigest(identity.KnowledgeID, identity.ParseAttempt, record.Chunks)
	if err != nil || digest != source.ManifestDigest {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	index, err := prepareConceptNativeQuoteIndex830G2(&types.ReadResult{MarkdownContent: record.Markdown, NativeStructure: record.Native}, expected.SourceHash, expected.ParserIdentity)
	if err != nil {
		return nil, err
	}
	if (record.FirstParseSHA256 == "") != (record.ChunkRanges == nil) {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	if record.ChunkRanges != nil && (!validServiceSHA256(record.FirstParseSHA256) || len(record.ChunkRanges) != len(record.Chunks)) {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	blocks := make(map[string]string, len(record.Chunks))
	runes := index.sourceRunes()
	for _, chunk := range record.Chunks {
		if _, duplicate := blocks[chunk.ID]; duplicate {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		if record.ChunkRanges != nil {
			r, ok := record.ChunkRanges[chunk.ID]
			if !ok || r.Index != chunk.Index || !g3FirstParseRangeMatchesRunes(runes, chunk.Content, r) {
				return nil, ErrConceptSourceAuthorityUnavailable830G2
			}
		}
		blocks[chunk.ID] = chunk.Content
	}
	return &conceptSourceReusePrepared830G3{blocks: blocks, index: index, record: *record}, nil
}

func (s *conceptSourceReuseStore830G3) load(ctx context.Context, key string, identity types.ConceptSourceIdentity830G2, source *types.KnowledgeRevisionSource, build func() (*conceptSourceReuseRecord830G3, error)) (*conceptSourceReusePrepared830G3, error) {
	s.mu.Lock()
	hit := s.entries[key]
	s.mu.Unlock()
	if hit != nil {
		return s.validateResident(hit, identity, source)
	}
	result := s.flight.DoChan(key, func() (any, error) {
		s.mu.Lock()
		hit := s.entries[key]
		s.mu.Unlock()
		if hit != nil {
			return s.validateResident(hit, identity, source)
		}
		path := filepath.Join(s.root, key+".json")
		data, err := s.readArtifact(path, key)
		missing := errors.Is(err, os.ErrNotExist)
		if err != nil && !missing {
			return nil, err
		}
		if missing {
			record, err := build()
			if err != nil {
				return nil, err
			}
			data, err = json.Marshal(record)
			if err != nil {
				return nil, err
			}
		}
		// Decode into owned buffers before indexing. The caller/parser cannot mutate
		// cached validation through an alias. Corrupt stored data fails closed.
		var record conceptSourceReuseRecord830G3
		if json.Unmarshal(data, &record) != nil {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		if err := s.validateFirstParseCache(&record); err != nil {
			return nil, err
		}
		prepared, err := validateConceptSourceReuse830G3(&record, identity, source)
		if err != nil {
			return nil, err
		}
		prepared.proof = &conceptSourceBindingProof830G3{owned: &prepared.record, firstSHA256: record.FirstParseSHA256}
		if missing {
			if err := s.writeArtifact(path, key, data); err != nil {
				return nil, err
			}
		}
		s.mu.Lock()
		// Bound resident document indexes; evicted entries remain durable.
		if len(s.entries) >= 16 {
			s.entries = map[string]*conceptSourceReusePrepared830G3{}
		}
		s.entries[key] = prepared
		s.mu.Unlock()
		return prepared, nil
	})
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	case loaded := <-result:
		if loaded.Err != nil {
			return nil, loaded.Err
		}
		return loaded.Val.(*conceptSourceReusePrepared830G3), nil
	}
}

func (s *conceptSourceReuseStore830G3) validateResident(hit *conceptSourceReusePrepared830G3, identity types.ConceptSourceIdentity830G2, source *types.KnowledgeRevisionSource) (*conceptSourceReusePrepared830G3, error) {
	if source == nil || hit.record.Identity != identity || hit.record.BindingDigest != source.BindingDigest {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	if err := s.validateFirstParseCacheProof(&hit.record, hit.proof); err != nil {
		return nil, err
	}
	if !hit.proof.matches(&hit.record) {
		// Unproved entries must validate the source binding and index too. A
		// first-artifact match alone does not establish their current binding.
		return validateConceptSourceReuse830G3(&hit.record, identity, source)
	}
	return hit, nil
}

// The existing deployment citation key seals derived artifacts in a separate
// signing domain. Recomputed hashes inside a modified sidecar cannot authorize it.
type conceptSourceReuseSeal830G3 struct {
	KeyID     string          `json:"key_id"`
	Key       string          `json:"key"`
	Payload   json.RawMessage `json:"payload"`
	Signature []byte          `json:"signature"`
}

func conceptSourceReuseSignedBytes830G3(domain, key string, payload []byte) []byte {
	return append([]byte(domain+"\n"+key+"\n"), payload...)
}
func openConceptDerivedArtifact830G3(codec *SchemaWikiCitationTokenCodec, domain, key string, encoded []byte) ([]byte, error) {
	var seal conceptSourceReuseSeal830G3
	if domain == "" || key == "" || json.Unmarshal(encoded, &seal) != nil || seal.Key != key || codec == nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	pub := codec.publicKeys[seal.KeyID]
	if len(pub) != ed25519.PublicKeySize || !ed25519.Verify(pub, conceptSourceReuseSignedBytes830G3(domain, key, seal.Payload), seal.Signature) {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	return seal.Payload, nil
}
func sealConceptDerivedArtifact830G3(codec *SchemaWikiCitationTokenCodec, domain, key string, payload []byte) ([]byte, error) {
	if codec == nil || domain == "" || key == "" {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	private := codec.privateKeys[codec.activeKeyID]
	if len(private) != ed25519.PrivateKeySize {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	normalized, err := json.Marshal(json.RawMessage(payload))
	if err != nil {
		return nil, err
	}
	payload = normalized
	seal := conceptSourceReuseSeal830G3{KeyID: codec.activeKeyID, Key: key, Payload: payload, Signature: ed25519.Sign(private, conceptSourceReuseSignedBytes830G3(domain, key, payload))}
	return json.Marshal(seal)
}
func (s *conceptSourceReuseStore830G3) readArtifact(path, key string) ([]byte, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return openConceptDerivedArtifact830G3(s.codec, "weknora.concept-source-reuse.830.g3.v1", key, data)
}
func (s *conceptSourceReuseStore830G3) writeArtifact(path, key string, data []byte) error {
	encoded, err := sealConceptDerivedArtifact830G3(s.codec, "weknora.concept-source-reuse.830.g3.v1", key, data)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(s.root, 0700); err != nil {
		return err
	}
	temp, err := os.CreateTemp(s.root, ".prepare-*")
	if err != nil {
		return err
	}
	defer os.Remove(temp.Name())
	_, writeErr := temp.Write(encoded)
	if writeErr == nil {
		writeErr = temp.Sync()
	}
	closeErr := temp.Close()
	if writeErr != nil {
		return writeErr
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Rename(temp.Name(), path)
}
