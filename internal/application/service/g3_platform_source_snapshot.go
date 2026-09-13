package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/Tencent/WeKnora/internal/types"
)

const (
	G3PlatformSourceSnapshotContractV1       = "g3-platform-source-snapshot.830.v1"
	G3PlatformSourceSnapshotSigningDomainV1  = "weknora.g3-platform-source-snapshot.830.v1"
	G3PlatformSnapshotAuthorityContractV1    = "g3-platform-snapshot-authority.830.v1"
	G3PlatformSignedSourceSnapshotContractV1 = "g3-platform-signed-source-snapshot.830.v1"

	G3PlatformChunkMappingExactBlock = "EXACT_BLOCK"
	G3PlatformChunkMappingUnresolved = "UNRESOLVED"
)

var (
	ErrG3PlatformSnapshotUnavailable  = errors.New("G3_PLATFORM_SNAPSHOT_UNAVAILABLE")
	ErrG3PlatformSnapshotUnauthorized = errors.New("G3_PLATFORM_SNAPSHOT_UNAUTHORIZED")
)

type G3PlatformSourceSnapshotAuthorizer interface {
	AuthorizeG3PlatformSourceSnapshot(
		context.Context, types.WikiReleaseScope, string, int64,
	) error
}

type G3PlatformSnapshotSigner interface {
	SignG3PlatformSnapshot(
		context.Context, string, string,
	) (keyID string, signature []byte, err error)
}

type g3PlatformSourceBindingEnsurer interface {
	ensureCurrentCompletedForScope(
		context.Context, types.WikiReleaseScope, string, int64,
	) (*types.KnowledgeRevisionSource, error)
}

type G3PlatformSourceProcessingReceiptReader interface {
	ProcessingReceipt(
		context.Context, types.WikiReleaseScope, string, int64,
	) (G3PlatformSourceProcessingReceiptV1, error)
}

type G3PlatformSnapshotAuthorityV1 struct {
	Contract      string `json:"contract"`
	Domain        string `json:"domain"`
	KeyID         string `json:"key_id"`
	PayloadSHA256 string `json:"payload_sha256"`
	Signature     []byte `json:"signature"`
}

type G3PlatformSourceChunkV1 struct {
	ID            string `json:"id"`
	Index         int    `json:"index"`
	Content       string `json:"content"`
	ContentSHA256 string `json:"content_sha256"`
}

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

type G3PlatformSourceSnapshotV1 struct {
	Contract             string                              `json:"contract"`
	Scope                types.WikiReleaseScope              `json:"scope"`
	Receipt              types.RegisteredSourceReceipt830G3  `json:"receipt"`
	ParserIdentitySHA256 string                              `json:"parser_identity_sha256"`
	NativeCaptureSHA256  string                              `json:"native_capture_sha256"`
	Markdown             string                              `json:"markdown"`
	Native               types.NativeStructureArtifact       `json:"native"`
	Chunks               []G3PlatformSourceChunkV1           `json:"chunks"`
	ChunkPageMappings    []G3PlatformChunkPageMappingV1      `json:"chunk_page_mappings"`
	ProcessingReceipt    G3PlatformSourceProcessingReceiptV1 `json:"processing_receipt"`
	SnapshotSHA256       string                              `json:"snapshot_sha256"`
}

type G3PlatformSignedSourceSnapshotV1 struct {
	Contract  string                        `json:"contract"`
	Snapshot  G3PlatformSourceSnapshotV1    `json:"snapshot"`
	Authority G3PlatformSnapshotAuthorityV1 `json:"authority"`
}

type G3PlatformSourceSnapshotService struct {
	ensurer    g3PlatformSourceBindingEnsurer
	sources    *ConceptSourceAuthorityService830G2
	processing G3PlatformSourceProcessingReceiptReader
	authorizer G3PlatformSourceSnapshotAuthorizer
	signer     G3PlatformSnapshotSigner
}

func NewG3PlatformSourceSnapshotService(
	ensurer g3PlatformSourceBindingEnsurer,
	sources *ConceptSourceAuthorityService830G2,
	processing G3PlatformSourceProcessingReceiptReader,
	authorizer G3PlatformSourceSnapshotAuthorizer,
	signer G3PlatformSnapshotSigner,
) *G3PlatformSourceSnapshotService {
	if sources != nil && sources.sourceReuse == nil && sources.codec != nil {
		sources.sourceReuse = newConceptSourceReuseStore830G3(sources.codec)
	}
	return &G3PlatformSourceSnapshotService{
		ensurer: ensurer, sources: sources, processing: processing, authorizer: authorizer, signer: signer,
	}
}

func (s *G3PlatformSourceSnapshotService) Capture(
	ctx context.Context,
	scope types.WikiReleaseScope,
	knowledgeID string,
	parseAttempt int64,
) (*G3PlatformSignedSourceSnapshotV1, error) {
	if s == nil || s.ensurer == nil || s.sources == nil || s.processing == nil || s.authorizer == nil ||
		s.signer == nil || !validG3PlatformScope(scope) || knowledgeID == "" || parseAttempt <= 0 {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	if err := s.authorizer.AuthorizeG3PlatformSourceSnapshot(
		ctx, scope, knowledgeID, parseAttempt,
	); err != nil {
		return nil, ErrG3PlatformSnapshotUnauthorized
	}
	sealed, err := s.ensurer.ensureCurrentCompletedForScope(
		ctx, scope, knowledgeID, parseAttempt,
	)
	if err != nil || sealed == nil {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	processing, err := s.processing.ProcessingReceipt(ctx, scope, knowledgeID, parseAttempt)
	if err != nil || validateG3PlatformSourceProcessingReceipt(processing, scope, knowledgeID, parseAttempt) != nil {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	prepared, err := s.sources.captureG3PlatformSource830G3(ctx, scope, sealed)
	if err != nil {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	snapshot, err := g3PlatformSourceSnapshotFromPrepared(scope, sealed, prepared, processing)
	if err != nil {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	authority, err := signG3PlatformSnapshot(
		ctx, s.signer, G3PlatformSourceSnapshotSigningDomainV1, snapshot.SnapshotSHA256,
	)
	if err != nil {
		return nil, ErrG3PlatformSnapshotUnavailable
	}
	return &G3PlatformSignedSourceSnapshotV1{
		Contract: G3PlatformSignedSourceSnapshotContractV1,
		Snapshot: snapshot, Authority: authority,
	}, nil
}

func (s *ConceptSourceAuthorityService830G2) captureG3PlatformSource830G3(
	ctx context.Context,
	scope types.WikiReleaseScope,
	expected *types.KnowledgeRevisionSource,
) (*conceptSourceReusePrepared830G3, error) {
	if s == nil || s.fixed == nil || s.knowledge == nil || s.revisions == nil ||
		s.chunks == nil || s.docreader == nil || s.sourceReuse == nil || expected == nil ||
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
	keyInput, err := canonicalJSON830G2(struct {
		Source  types.ConceptSourceIdentity830G2 `json:"source"`
		Binding string                           `json:"binding"`
	}{identity, live.BindingDigest})
	if err != nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	key := testSHA256Bytes830G2(keyInput)
	return s.sourceReuse.load(ctx, key, identity, live, func() (*conceptSourceReuseRecord830G3, error) {
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
		pdf, err := s.fixed.ReadFixedRevision(
			ctx, live.KnowledgeID, live.ParseAttempt, live.FileSHA256, live.BindingDigest, 1,
		)
		if err != nil || testSHA256Bytes830G2(pdf) != live.FileSHA256 {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		result, err := s.docreader.Read(ctx, &types.ReadRequest{
			FileContent: pdf, FileName: knowledge.FileName, FileType: "pdf",
			ParserEngine: "builtin", ParserEngineOverrides: map[string]string{
				"pdf_native_structure_capture": conceptNativeCapture830G2,
			},
		})
		if err != nil || result == nil || result.Error != "" || result.NativeStructure == nil {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		var projection conceptNativeProjection830G2
		decoder := json.NewDecoder(bytes.NewReader(result.NativeStructure.SanitizedJSON))
		decoder.DisallowUnknownFields()
		if decoder.Decode(&projection) != nil || !jsonEOF830G2(decoder) ||
			!validServiceSHA256(projection.ParserIdentitySHA256) {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		capturedIdentity := identity
		capturedIdentity.ParserIdentity = projection.ParserIdentitySHA256
		return &conceptSourceReuseRecord830G3{
			Contract: conceptSourceReuseContract830G3, Identity: capturedIdentity,
			BindingDigest: live.BindingDigest, Chunks: manifest,
			Markdown: result.MarkdownContent, Native: result.NativeStructure,
		}, nil
	})
}

func g3PlatformSourceSnapshotFromPrepared(
	scope types.WikiReleaseScope,
	source *types.KnowledgeRevisionSource,
	prepared *conceptSourceReusePrepared830G3,
	processing G3PlatformSourceProcessingReceiptV1,
) (G3PlatformSourceSnapshotV1, error) {
	var empty G3PlatformSourceSnapshotV1
	if source == nil || source.PageCount == nil || prepared == nil || prepared.index == nil ||
		prepared.record.Native == nil || prepared.record.Identity.ParserIdentity == "" {
		return empty, ErrG3PlatformSnapshotUnavailable
	}
	native := *prepared.record.Native
	native.SanitizedJSON = append([]byte(nil), prepared.record.Native.SanitizedJSON...)
	chunks := make([]G3PlatformSourceChunkV1, 0, len(prepared.record.Chunks))
	mappings := make([]G3PlatformChunkPageMappingV1, 0, len(prepared.record.Chunks))
	for _, chunk := range prepared.record.Chunks {
		chunks = append(chunks, G3PlatformSourceChunkV1{
			ID: chunk.ID, Index: chunk.Index, Content: chunk.Content,
			ContentSHA256: g3PlatformRawSHA256([]byte(chunk.Content)),
		})
		mappings = append(mappings, g3PlatformChunkPageMapping(chunk, prepared.index))
	}
	receipt := types.RegisteredSourceReceipt830G3{
		Contract: "knowledge-revision-source.v1", KnowledgeID: source.KnowledgeID,
		ParseAttempt: source.ParseAttempt, RevisionSourceID: source.RevisionSourceID,
		FileSHA256: source.FileSHA256, ObjectSHA256: source.ObjectSHA256,
		Size: source.Size, MIMEType: source.MimeType, PageCount: int64(*source.PageCount),
		ManifestAlgorithm: source.ManifestAlgorithm, ManifestDigest: source.ManifestDigest,
		ChunkCount: int64(source.ChunkCount), BindingDigest: source.BindingDigest,
		RetentionState: source.RetentionState,
	}
	snapshot := G3PlatformSourceSnapshotV1{
		Contract: G3PlatformSourceSnapshotContractV1, Scope: scope, Receipt: receipt,
		ParserIdentitySHA256: prepared.record.Identity.ParserIdentity,
		NativeCaptureSHA256:  native.SanitizedSHA256,
		Markdown:             prepared.record.Markdown, Native: native,
		Chunks: chunks, ChunkPageMappings: mappings, ProcessingReceipt: processing,
	}
	digest, err := g3PlatformSnapshotDigest(snapshot.Contract, snapshot, "snapshot_sha256")
	if err != nil {
		return empty, err
	}
	snapshot.SnapshotSHA256 = digest
	return snapshot, nil
}

func g3PlatformChunkPageMapping(
	chunk types.RevisionManifestChunk,
	index *conceptNativeQuoteIndex830G2,
) G3PlatformChunkPageMappingV1 {
	result := G3PlatformChunkPageMappingV1{
		ChunkID: chunk.ID, Status: G3PlatformChunkMappingUnresolved,
		PageSpans: []G3PlatformChunkPageSpanV1{},
	}
	if index == nil || chunk.Content == "" {
		return result
	}
	at := strings.Index(index.text, chunk.Content)
	if at < 0 || strings.Index(index.text[at+1:], chunk.Content) >= 0 {
		return result
	}
	start := utf8.RuneCountInString(index.text[:at])
	end := start + utf8.RuneCountInString(chunk.Content)
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

func validG3PlatformScope(scope types.WikiReleaseScope) bool {
	return scope.TenantID > 0 && scope.SpaceID != "" && scope.RawKBID != "" && scope.WikiKBID != ""
}

func intPointerG3Platform(value int) *int { return &value }

func g3PlatformRawSHA256(raw []byte) string {
	digest := sha256.Sum256(raw)
	return hex.EncodeToString(digest[:])
}

func g3PlatformSnapshotDigest(contract string, value any, hashField string) (string, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	var payload map[string]any
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if decoder.Decode(&payload) != nil || !jsonEOF830G2(decoder) {
		return "", ErrG3PlatformSnapshotUnavailable
	}
	delete(payload, hashField)
	canonical, err := canonicalJSON830G2(payload)
	if err != nil {
		return "", err
	}
	return g3PlatformRawSHA256(append([]byte(contract+"\x00"), canonical...)), nil
}

func signG3PlatformSnapshot(
	ctx context.Context,
	signer G3PlatformSnapshotSigner,
	domain string,
	digest string,
) (G3PlatformSnapshotAuthorityV1, error) {
	var empty G3PlatformSnapshotAuthorityV1
	if signer == nil || domain == "" || !validServiceSHA256(digest) {
		return empty, ErrG3PlatformSnapshotUnavailable
	}
	keyID, signature, err := signer.SignG3PlatformSnapshot(ctx, domain, digest)
	if err != nil || strings.TrimSpace(keyID) == "" || len(signature) == 0 {
		return empty, ErrG3PlatformSnapshotUnavailable
	}
	return G3PlatformSnapshotAuthorityV1{
		Contract: G3PlatformSnapshotAuthorityContractV1,
		Domain:   domain, KeyID: keyID, PayloadSHA256: digest,
		Signature: append([]byte(nil), signature...),
	}, nil
}
