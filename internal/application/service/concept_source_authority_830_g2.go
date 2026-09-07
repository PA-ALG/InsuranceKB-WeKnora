package service

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"reflect"
	"sort"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	wikirepository "github.com/Tencent/WeKnora/internal/application/repository"
	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

const (
	conceptNativeCapture830G2             = "builtin-pdfium-charbox-v1"
	conceptNativeContract830G2            = "builtin-pdfium-native-locators.v1"
	conceptCitationAuthorityContract830G2 = "concept-citation-content-authority.830.g2.v1"
	conceptCitationClaimsContract830G2    = "concept-citation-content-token-claims.830.g2.v1"
)

type ConceptRevisionSourceAuthority830G2 struct {
	BindingDigest string `json:"binding_digest"`
	FileSHA256    string `json:"file_sha256"`
	PageCount     int    `json:"page_count"`
}

type ConceptCitationBBox830G2 struct {
	CoordinateSpace string `json:"coordinate_space"`
	X0              int    `json:"x0"`
	Y0              int    `json:"y0"`
	X1              int    `json:"x1"`
	Y1              int    `json:"y1"`
}

type ConceptCitationContentAuthority830G2 struct {
	Contract        string                              `json:"contract"`
	TokenKeyID      string                              `json:"token_key_id"`
	ReleaseID       string                              `json:"release_id"`
	ActivationEpoch uint64                              `json:"activation_epoch"`
	CandidateHash   string                              `json:"candidate_hash"`
	MemberID        string                              `json:"member_id"`
	CitationID      string                              `json:"citation_id"`
	Scope           types.WikiReleaseScope              `json:"scope"`
	Source          types.ConceptSourceIdentity830G2    `json:"source"`
	RevisionSource  ConceptRevisionSourceAuthority830G2 `json:"revision_source"`
	BlockID         string                              `json:"block_id"`
	PageNumber      int                                 `json:"page_number"`
	QuoteHash       string                              `json:"quote_hash"`
	BBox            ConceptCitationBBox830G2            `json:"bbox"`
	ExpiresAtUnix   int64                               `json:"expires_at_unix"`
	AuthorityDigest string                              `json:"authority_digest"`
	OpaqueToken     string                              `json:"opaque_token"`
}

type conceptCitationTokenClaims830G2 struct {
	Contract      string                               `json:"contract"`
	TokenKeyID    string                               `json:"token_key_id"`
	IssuedAtUnix  int64                                `json:"issued_at_unix"`
	ExpiresAtUnix int64                                `json:"expires_at_unix"`
	Scope         types.WikiReleaseScope               `json:"scope"`
	Authority     ConceptCitationContentAuthority830G2 `json:"authority"`
}

type ConceptCitationRouteAuthority830G2 struct {
	Scope           types.WikiReleaseScope
	ReleaseID       string
	ActivationEpoch uint64
	MemberID        string
	CitationID      string
}

type ConceptCitationAuthorityRequest830G2 struct {
	Scope           types.WikiReleaseScope
	ReleaseID       string
	ActivationEpoch uint64
	CandidateHash   string
	MemberID        string
	CitationID      string
	Evidence        types.ConceptEvidence830G2
	SourceBlock     types.ConceptSourceBlock830G2
	Bundle          *types.ConceptCandidateBundle830G2
}

type conceptNativeParserIdentity830G2 struct {
	ProducerContract string `json:"producer_contract"`
	CaptureMode      string `json:"capture_mode"`
	Pypdfium2Version string `json:"pypdfium2_version"`
	PDFiumVersion    string `json:"pdfium_version"`
}

type conceptNativeBBox830G2 struct {
	GlobalCodepointStart int    `json:"global_codepoint_start"`
	GlobalCodepointEnd   int    `json:"global_codepoint_end"`
	BBox                 [4]int `json:"bbox"`
}

type conceptNativePage830G2 struct {
	PageNumber           int                      `json:"page_number"`
	GlobalCodepointStart int                      `json:"global_codepoint_start"`
	GlobalCodepointEnd   int                      `json:"global_codepoint_end"`
	PageTextSHA256       string                   `json:"page_text_sha256"`
	WidthPoints          string                   `json:"width_points"`
	HeightPoints         string                   `json:"height_points"`
	BBoxes               []conceptNativeBBox830G2 `json:"bboxes"`
}

type conceptNativeProjection830G2 struct {
	Contract             string                           `json:"contract"`
	SourceSHA256         string                           `json:"source_sha256"`
	MarkdownSHA256       string                           `json:"markdown_sha256"`
	CoordinateSpace      string                           `json:"coordinate_space"`
	ParserIdentity       conceptNativeParserIdentity830G2 `json:"parser_identity"`
	ParserIdentitySHA256 string                           `json:"parser_identity_sha256"`
	Pages                []conceptNativePage830G2         `json:"pages"`
}

type conceptSourceRevisionRepository830G2 interface {
	GetRevision(context.Context, string, int64) (*types.KnowledgeRevision, error)
	GetRevisionSource(context.Context, uint64, string, int64) (*types.KnowledgeRevisionSource, *types.StoredResource, error)
}

type conceptKnowledgeReader830G2 interface {
	GetKnowledgeByID(context.Context, uint64, string) (*types.Knowledge, error)
}

type conceptChunkReader830G2 interface {
	ListChunksByKnowledgeID(context.Context, uint64, string) ([]*types.Chunk, error)
}

type conceptFixedRevisionReader830G2 interface {
	ReadFixedRevision(context.Context, string, int64, string, string, int) ([]byte, error)
}

type ConceptSourceAuthorityService830G2 struct {
	fixed                  conceptFixedRevisionReader830G2
	knowledge              conceptKnowledgeReader830G2
	revisions              conceptSourceRevisionRepository830G2
	chunks                 conceptChunkReader830G2
	docreader              interfaces.DocReader
	codec                  *SchemaWikiCitationTokenCodec
	releases               *wikirepository.WikiReleaseRepository
	legacyCitationContent  SchemaWikiCitationContentPort
	formalCandidatePreview SchemaWikiFormalCandidatePreviewReader
	// legacyProofResolver is a test-only seam used to exercise the publication
	// gate with a verified legacy occurrence without rebuilding a complete G1
	// custody chain. Production construction always leaves it nil.
	legacyProofResolver func(context.Context, types.WikiReleaseScope, types.ConceptCandidateBundle830G2) (map[string]conceptLegacyProof830G2, error)
}

type conceptNativeCaptureCacheKey830G2 struct{}
type conceptNativeCaptureEntry830G2 struct {
	pdf    []byte
	result *types.ReadResult
}

type conceptLegacyProof830G2 struct {
	authority *types.SchemaWikiCitationContentAuthorityV1
}

func NewConceptSourceAuthorityService830G2(fixed *KnowledgeRevisionSourceService, knowledge interfaces.KnowledgeRepository, chunks interfaces.ChunkRepository, reader interfaces.DocumentReader, codec *SchemaWikiCitationTokenCodec, releases *wikirepository.WikiReleaseRepository, legacyCitationContent SchemaWikiCitationContentPort, formalCandidatePreview *wikirepository.SchemaWikiFormalCandidatePreviewRegistry) *ConceptSourceAuthorityService830G2 {
	revisions, _ := knowledge.(conceptSourceRevisionRepository830G2)
	return &ConceptSourceAuthorityService830G2{fixed: fixed, knowledge: knowledge, revisions: revisions, chunks: chunks, docreader: reader, codec: codec, releases: releases, legacyCitationContent: legacyCitationContent, formalCandidatePreview: formalCandidatePreview}
}

func (s *ConceptSourceAuthorityService830G2) VerifyConceptSources830G2(ctx context.Context, request ConceptSourceAuthorityVerificationRequest830G2) error {
	if s == nil || (request.Operation != "review" && request.Operation != "activate") || request.PreparationID == "" || !validServiceSHA256(request.CandidateHash) {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	bundle, canonicalManifest, err := types.CanonicalConceptCandidateBundle830G2(request.Manifest)
	if err != nil || digestWikiReleaseBytes(canonicalManifest) != request.ManifestDigest || bundle.CandidateHash != request.CandidateHash || bundle.Request.TenantID != request.Scope.TenantID || bundle.Request.SpaceID != request.Scope.SpaceID || bundle.Request.RawKBID != request.Scope.RawKBID || bundle.Request.WikiKBID != request.Scope.WikiKBID {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	ctx = context.WithValue(ctx, conceptNativeCaptureCacheKey830G2{}, map[string]conceptNativeCaptureEntry830G2{})
	legacyEvidence, err := s.verifyLegacyCarryover830G2(ctx, request.Scope, bundle)
	if err != nil {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	referencedSources, err := conceptReferencedExistingSourceKeys830G2(bundle)
	if err != nil {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	seen := map[string]struct{}{}
	for _, member := range bundle.PageManifest.Members {
		for _, evidence := range conceptMemberEvidence830G2(bundle, member.MemberID) {
			canonicalEvidence, canonicalErr := canonicalJSON830G2(evidence)
			if canonicalErr != nil {
				return ErrConceptSourceAuthorityUnavailable830G2
			}
			key := testSHA256Bytes830G2(canonicalEvidence)
			sourceBlock, ok := conceptSourceBlockForEvidence830G2(bundle, evidence)
			if !ok {
				return ErrConceptSourceAuthorityUnavailable830G2
			}
			referencedSources[sourceBlock.RevisionID+"\x00"+sourceBlock.BlockID] = struct{}{}
			if member.Kind == "field_assertion" {
				if _, legacy := conceptLegacyProofForOccurrence830G2(member.Kind, member.MemberID, evidence, legacyEvidence); legacy {
					continue
				}
			}
			if _, ok := seen[key]; ok {
				continue
			}
			seen[key] = struct{}{}
			if _, _, err := s.verifyEvidence(ctx, request.Scope, evidence, &sourceBlock); err != nil {
				return err
			}
		}
	}
	if len(referencedSources) != len(bundle.Request.Sources) {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	return nil
}

func conceptLegacyProofForOccurrence830G2(kind, memberID string, evidence types.ConceptEvidence830G2, proofs map[string]conceptLegacyProof830G2) (conceptLegacyProof830G2, bool) {
	if kind != "field_assertion" {
		return conceptLegacyProof830G2{}, false
	}
	canonical, err := canonicalJSON830G2(evidence)
	if err != nil {
		return conceptLegacyProof830G2{}, false
	}
	proof, ok := proofs[memberID+"\x00"+testSHA256Bytes830G2(canonical)]
	return proof, ok
}

func (s *ConceptSourceAuthorityService830G2) verifyEvidence(ctx context.Context, scope types.WikiReleaseScope, evidence types.ConceptEvidence830G2, sourceBlock *types.ConceptSourceBlock830G2) (*types.KnowledgeRevisionSource, ConceptCitationBBox830G2, error) {
	empty := ConceptCitationBBox830G2{}
	if s == nil || s.fixed == nil || s.knowledge == nil || s.revisions == nil || s.chunks == nil || s.docreader == nil || evidence.TenantID != scope.TenantID || evidence.SpaceID != scope.SpaceID || evidence.RawKBID != scope.RawKBID || evidence.OffsetUnit != "UNICODE_CODE_POINT" || evidence.SourceType != "DOCUMENT" || evidence.Start < 0 || evidence.End <= evidence.Start || evidence.PageNumber <= 0 || testSHA256830G2(evidence.Quote) != evidence.QuoteHash {
		return nil, empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	knowledge, err := s.knowledge.GetKnowledgeByID(ctx, scope.TenantID, evidence.KnowledgeID)
	if err != nil || knowledge == nil || knowledge.DeletedAt.Valid || knowledge.TenantID != scope.TenantID || knowledge.KnowledgeBaseID != scope.RawKBID || !strings.EqualFold(knowledge.FileType, "pdf") {
		return nil, empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	revision, err := s.revisions.GetRevision(ctx, evidence.KnowledgeID, evidence.ParseAttempt)
	if err != nil || revision == nil || revision.KnowledgeID != evidence.KnowledgeID || revision.ParseAttempt != evidence.ParseAttempt || revision.FileSHA256 != evidence.SourceHash || revision.ManifestAlgorithm != types.RevisionManifestAlgorithm || revision.ManifestDigest != evidence.ParseHash || revision.ChunkCount <= 0 {
		return nil, empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	source, resource, err := s.revisions.GetRevisionSource(ctx, scope.TenantID, evidence.KnowledgeID, evidence.ParseAttempt)
	if err != nil || source == nil || resource == nil || types.ValidateKnowledgeRevisionSourceBinding(*source) != nil || source.RevisionSourceID != evidence.RevisionID || source.FileSHA256 != evidence.SourceHash || source.ManifestDigest != evidence.ParseHash || source.ChunkCount != revision.ChunkCount || source.PageCount == nil || evidence.PageNumber > *source.PageCount || resource.ID != source.ResourceID || resource.TenantID != scope.TenantID {
		return nil, empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	chunks, err := s.chunks.ListChunksByKnowledgeID(ctx, scope.TenantID, evidence.KnowledgeID)
	if err != nil {
		return nil, empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	manifest := make([]types.RevisionManifestChunk, 0, len(chunks))
	var block *types.Chunk
	for _, chunk := range chunks {
		if chunk == nil || chunk.ParseAttempt != evidence.ParseAttempt {
			continue
		}
		if chunk.TenantID != scope.TenantID || chunk.KnowledgeID != evidence.KnowledgeID || chunk.KnowledgeBaseID != scope.RawKBID {
			return nil, empty, ErrConceptSourceAuthorityUnavailable830G2
		}
		manifest = append(manifest, types.RevisionManifestChunk{ID: chunk.ID, Index: chunk.ChunkIndex, Content: chunk.Content})
		if chunk.ID == evidence.BlockID {
			block = chunk
		}
	}
	sort.Slice(manifest, func(i, j int) bool { return manifest[i].Index < manifest[j].Index })
	digest, err := types.ComputeRevisionManifestDigest(evidence.KnowledgeID, evidence.ParseAttempt, manifest)
	if err != nil || len(manifest) != revision.ChunkCount || digest != revision.ManifestDigest || block == nil {
		return nil, empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	if sourceBlock != nil && (sourceBlock.ConceptSourceIdentity830G2 != evidence.ConceptSourceIdentity830G2 || sourceBlock.BlockID != evidence.BlockID || sourceBlock.PageNumber != evidence.PageNumber || sourceBlock.SourceType != evidence.SourceType || sourceBlock.Text != block.Content) {
		return nil, empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	runes := []rune(block.Content)
	if evidence.End > len(runes) || string(runes[evidence.Start:evidence.End]) != evidence.Quote {
		return nil, empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	identityCanonical, _ := canonicalJSON830G2(evidence.ConceptSourceIdentity830G2)
	cacheKey := testSHA256Bytes830G2(identityCanonical)
	cache, _ := ctx.Value(conceptNativeCaptureCacheKey830G2{}).(map[string]conceptNativeCaptureEntry830G2)
	capture, cached := cache[cacheKey]
	if !cached {
		pdf, readErr := s.fixed.ReadFixedRevision(ctx, evidence.KnowledgeID, evidence.ParseAttempt, source.FileSHA256, source.BindingDigest, evidence.PageNumber)
		if readErr != nil || testSHA256Bytes830G2(pdf) != evidence.SourceHash {
			return nil, empty, ErrConceptSourceAuthorityUnavailable830G2
		}
		result, parseErr := s.docreader.Read(ctx, &types.ReadRequest{FileContent: pdf, FileName: knowledge.FileName, FileType: "pdf", ParserEngine: "builtin", ParserEngineOverrides: map[string]string{"pdf_native_structure_capture": conceptNativeCapture830G2}})
		if parseErr != nil {
			return nil, empty, ErrConceptSourceAuthorityUnavailable830G2
		}
		capture = conceptNativeCaptureEntry830G2{pdf: append([]byte(nil), pdf...), result: result}
		if cache != nil {
			cache[cacheKey] = capture
		}
	}
	if testSHA256Bytes830G2(capture.pdf) != evidence.SourceHash {
		return nil, empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	result := capture.result
	bbox, err := resolveConceptNativeQuote830G2(result, evidence.SourceHash, evidence.ParserIdentity, evidence.PageNumber, evidence.Quote)
	if err != nil {
		return nil, empty, err
	}
	return source, bbox, nil
}

func (s *ConceptSourceAuthorityService830G2) IssueConceptCitationAuthority830G2(ctx context.Context, request ConceptCitationAuthorityRequest830G2) (*ConceptCitationContentAuthority830G2, error) {
	if request.ReleaseID == "" || request.ActivationEpoch == 0 || request.MemberID == "" || request.CitationID == "" || !validServiceSHA256(request.CandidateHash) || s == nil || s.codec == nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	source, bbox, err := s.resolveCitationEvidence830G2(ctx, request)
	if err != nil {
		return nil, err
	}
	now := s.codec.now().UTC()
	authority := conceptCitationAuthorityFromResolved830G2(request, source, bbox, s.codec.activeKeyID, now.Add(schemaWikiCitationTokenTTL).Unix())
	authority.AuthorityDigest, err = computeConceptCitationAuthorityDigest830G2(authority)
	if err != nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	if validateConceptCitationAuthority830G2(authority) != nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	authority.OpaqueToken, err = s.codec.issueConcept830G2(request.Scope, authority, now)
	if err != nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	return &authority, nil
}

func (s *ConceptSourceAuthorityService830G2) ResolveConceptCitationRouteAuthority830G2(token string) (*ConceptCitationRouteAuthority830G2, error) {
	if s == nil || s.codec == nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	claims, err := s.codec.verifyConcept830G2(token)
	if err != nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	return &ConceptCitationRouteAuthority830G2{Scope: claims.Scope, ReleaseID: claims.Authority.ReleaseID, ActivationEpoch: claims.Authority.ActivationEpoch, MemberID: claims.Authority.MemberID, CitationID: claims.Authority.CitationID}, nil
}

func (s *ConceptSourceAuthorityService830G2) ReadConceptCitationByOpaqueToken830G2(ctx context.Context, scope types.WikiReleaseScope, token string, request ConceptCitationAuthorityRequest830G2) ([]byte, error) {
	if s == nil || s.codec == nil || s.fixed == nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	claims, err := s.codec.verifyConcept830G2(token)
	if err != nil || claims.Scope != scope || request.Scope != scope {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	source, bbox, err := s.resolveCitationEvidence830G2(ctx, request)
	if err != nil {
		return nil, err
	}
	trusted := conceptCitationAuthorityFromResolved830G2(request, source, bbox, claims.TokenKeyID, claims.ExpiresAtUnix)
	trusted.AuthorityDigest, err = computeConceptCitationAuthorityDigest830G2(trusted)
	if err != nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	presented := claims.Authority
	presented.OpaqueToken = ""
	if !conceptCanonicalEqual830G2(presented, trusted) {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	return s.fixed.ReadFixedRevision(ctx, request.Evidence.KnowledgeID, request.Evidence.ParseAttempt, trusted.RevisionSource.FileSHA256, trusted.RevisionSource.BindingDigest, request.Evidence.PageNumber)
}

func (s *ConceptSourceAuthorityService830G2) resolveCitationEvidence830G2(ctx context.Context, request ConceptCitationAuthorityRequest830G2) (*types.KnowledgeRevisionSource, ConceptCitationBBox830G2, error) {
	if request.Bundle != nil {
		proofs, err := s.verifyLegacyCarryover830G2(ctx, request.Scope, *request.Bundle)
		if err != nil {
			return nil, ConceptCitationBBox830G2{}, err
		}
		canonical, canonicalErr := canonicalJSON830G2(request.Evidence)
		if canonicalErr != nil {
			return nil, ConceptCitationBBox830G2{}, canonicalErr
		}
		if proof, ok := proofs[request.MemberID+"\x00"+testSHA256Bytes830G2(canonical)]; ok {
			if s.revisions == nil || proof.authority == nil || proof.authority.RevisionSource.RevisionSourceID != request.Evidence.RevisionID || proof.authority.PageNumber != request.Evidence.PageNumber || proof.authority.BBox.X0 < 0 || proof.authority.BBox.Y0 < 0 || proof.authority.BBox.X0 >= proof.authority.BBox.X1 || proof.authority.BBox.Y0 >= proof.authority.BBox.Y1 {
				return nil, ConceptCitationBBox830G2{}, ErrConceptSourceAuthorityUnavailable830G2
			}
			source, resource, sourceErr := s.revisions.GetRevisionSource(ctx, request.Scope.TenantID, request.Evidence.KnowledgeID, request.Evidence.ParseAttempt)
			if sourceErr != nil || source == nil || resource == nil || types.ValidateKnowledgeRevisionSourceBinding(*source) != nil || source.RevisionSourceID != request.Evidence.RevisionID || source.FileSHA256 != request.Evidence.SourceHash || source.ManifestDigest != request.Evidence.ParseHash || resource.ID != source.ResourceID || resource.TenantID != request.Scope.TenantID {
				return nil, ConceptCitationBBox830G2{}, ErrConceptSourceAuthorityUnavailable830G2
			}
			bbox := proof.authority.BBox
			return source, ConceptCitationBBox830G2{CoordinateSpace: "normalized_0_1e6_top_left", X0: bbox.X0, Y0: bbox.Y0, X1: bbox.X1, Y1: bbox.Y1}, nil
		}
	}
	return s.verifyEvidence(ctx, request.Scope, request.Evidence, &request.SourceBlock)
}

func conceptCitationAuthorityFromResolved830G2(request ConceptCitationAuthorityRequest830G2, source *types.KnowledgeRevisionSource, bbox ConceptCitationBBox830G2, keyID string, expires int64) ConceptCitationContentAuthority830G2 {
	return ConceptCitationContentAuthority830G2{Contract: conceptCitationAuthorityContract830G2, TokenKeyID: keyID, ReleaseID: request.ReleaseID, ActivationEpoch: request.ActivationEpoch, CandidateHash: request.CandidateHash, MemberID: request.MemberID, CitationID: request.CitationID, Scope: request.Scope, Source: request.Evidence.ConceptSourceIdentity830G2, RevisionSource: ConceptRevisionSourceAuthority830G2{BindingDigest: source.BindingDigest, FileSHA256: source.FileSHA256, PageCount: *source.PageCount}, BlockID: request.Evidence.BlockID, PageNumber: request.Evidence.PageNumber, QuoteHash: request.Evidence.QuoteHash, BBox: bbox, ExpiresAtUnix: expires}
}

func resolveConceptNativeQuote830G2(result *types.ReadResult, sourceSHA, parserIdentitySHA string, pageNumber int, quote string) (ConceptCitationBBox830G2, error) {
	empty := ConceptCitationBBox830G2{}
	if result == nil || result.Error != "" || result.NativeStructure == nil || pageNumber <= 0 || quote == "" || !validServiceSHA256(sourceSHA) || !validServiceSHA256(parserIdentitySHA) {
		return empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	artifact := result.NativeStructure
	if artifact.SchemaVersion != conceptNativeContract830G2 || artifact.SourceSHA256 != sourceSHA || artifact.RawSHA256 != artifact.SanitizedSHA256 || testSHA256Bytes830G2(artifact.SanitizedJSON) != artifact.SanitizedSHA256 {
		return empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	var projection conceptNativeProjection830G2
	decoder := json.NewDecoder(bytes.NewReader(artifact.SanitizedJSON))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&projection) != nil || !jsonEOF830G2(decoder) {
		return empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	canonical, err := canonicalJSON830G2(projection)
	identityCanonical, identityErr := canonicalJSON830G2(projection.ParserIdentity)
	if err != nil || identityErr != nil || !bytes.Equal(canonical, artifact.SanitizedJSON) || projection.Contract != conceptNativeContract830G2 || projection.SourceSHA256 != sourceSHA || projection.MarkdownSHA256 != testSHA256830G2(result.MarkdownContent) || projection.CoordinateSpace != "normalized_0_1e6_top_left" || projection.ParserIdentity.ProducerContract != "weknora.docreader.builtin-pdfium-charbox.v1" || projection.ParserIdentity.CaptureMode != conceptNativeCapture830G2 || projection.ParserIdentity.Pypdfium2Version == "" || projection.ParserIdentity.PDFiumVersion == "" || projection.ParserIdentitySHA256 != testSHA256Bytes830G2(identityCanonical) || projection.ParserIdentitySHA256 != parserIdentitySHA || len(projection.Pages) == 0 {
		return empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	markdown := []rune(result.MarkdownContent)
	var target *conceptNativePage830G2
	lastEnd := 0
	for index := range projection.Pages {
		page := &projection.Pages[index]
		if page.PageNumber != index+1 || (index == 0 && page.GlobalCodepointStart != 0) || page.GlobalCodepointStart < lastEnd || page.GlobalCodepointEnd < page.GlobalCodepointStart || page.GlobalCodepointEnd > len(markdown) || !validConceptDimension830G2(page.WidthPoints) || !validConceptDimension830G2(page.HeightPoints) || testSHA256830G2(string(markdown[page.GlobalCodepointStart:page.GlobalCodepointEnd])) != page.PageTextSHA256 {
			return empty, ErrConceptSourceAuthorityUnavailable830G2
		}
		if index > 0 && (page.GlobalCodepointStart-lastEnd != 2 || string(markdown[lastEnd:page.GlobalCodepointStart]) != "\n\n") {
			return empty, ErrConceptSourceAuthorityUnavailable830G2
		}
		pageRunes := markdown[page.GlobalCodepointStart:page.GlobalCodepointEnd]
		boxPositions := map[int]struct{}{}
		for _, box := range page.BBoxes {
			if box.GlobalCodepointEnd != box.GlobalCodepointStart+1 || box.GlobalCodepointStart < page.GlobalCodepointStart || box.GlobalCodepointEnd > page.GlobalCodepointEnd || !validConceptBBox830G2(box.BBox) {
				return empty, ErrConceptSourceAuthorityUnavailable830G2
			}
			local := box.GlobalCodepointStart - page.GlobalCodepointStart
			if unicode.IsSpace(pageRunes[local]) {
				return empty, ErrConceptSourceAuthorityUnavailable830G2
			}
			if _, duplicate := boxPositions[box.GlobalCodepointStart]; duplicate {
				return empty, ErrConceptSourceAuthorityUnavailable830G2
			}
			boxPositions[box.GlobalCodepointStart] = struct{}{}
		}
		visible := 0
		for _, character := range pageRunes {
			if !unicode.IsSpace(character) {
				visible++
			}
		}
		if visible != len(boxPositions) {
			return empty, ErrConceptSourceAuthorityUnavailable830G2
		}
		lastEnd = page.GlobalCodepointEnd
		if page.PageNumber == pageNumber {
			target = page
		}
	}
	if lastEnd != len(markdown) {
		return empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	if target == nil {
		return empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	pageRunes := markdown[target.GlobalCodepointStart:target.GlobalCodepointEnd]
	quoteRunes := []rune(quote)
	match := -1
	for start := 0; start+len(quoteRunes) <= len(pageRunes); start++ {
		if string(pageRunes[start:start+len(quoteRunes)]) == quote {
			if match >= 0 {
				return empty, ErrConceptSourceAuthorityUnavailable830G2
			}
			match = start
		}
	}
	if match < 0 {
		return empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	boxes := map[int][4]int{}
	for _, box := range target.BBoxes {
		if box.GlobalCodepointEnd != box.GlobalCodepointStart+1 || box.GlobalCodepointStart < target.GlobalCodepointStart || box.GlobalCodepointEnd > target.GlobalCodepointEnd || !validConceptBBox830G2(box.BBox) {
			return empty, ErrConceptSourceAuthorityUnavailable830G2
		}
		local := box.GlobalCodepointStart - target.GlobalCodepointStart
		if unicode.IsSpace(pageRunes[local]) {
			return empty, ErrConceptSourceAuthorityUnavailable830G2
		}
		if _, exists := boxes[box.GlobalCodepointStart]; exists {
			return empty, ErrConceptSourceAuthorityUnavailable830G2
		}
		boxes[box.GlobalCodepointStart] = box.BBox
	}
	x0, y0, x1, y1 := 1_000_001, 1_000_001, -1, -1
	for offset, char := range quoteRunes {
		if unicode.IsSpace(char) {
			continue
		}
		box, ok := boxes[target.GlobalCodepointStart+match+offset]
		if !ok {
			return empty, ErrConceptSourceAuthorityUnavailable830G2
		}
		if box[0] < x0 {
			x0 = box[0]
		}
		if box[1] < y0 {
			y0 = box[1]
		}
		if box[2] > x1 {
			x1 = box[2]
		}
		if box[3] > y1 {
			y1 = box[3]
		}
	}
	if x1 <= x0 || y1 <= y0 {
		return empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	return ConceptCitationBBox830G2{CoordinateSpace: projection.CoordinateSpace, X0: x0, Y0: y0, X1: x1, Y1: y1}, nil
}

func validConceptBBox830G2(box [4]int) bool {
	return box[0] >= 0 && box[1] >= 0 && box[0] < box[2] && box[1] < box[3] && box[2] <= 1_000_000 && box[3] <= 1_000_000
}

func validConceptDimension830G2(value string) bool {
	if value == "" || value[0] == '0' || strings.ContainsAny(value, "+-eE ") {
		return false
	}
	dot := false
	for index, character := range value {
		if character == '.' && !dot && index > 0 && index < len(value)-1 {
			dot = true
			continue
		}
		if character < '0' || character > '9' {
			return false
		}
	}
	return !dot || value[len(value)-1] != '0'
}
func testSHA256830G2(value string) string { return testSHA256Bytes830G2([]byte(value)) }
func testSHA256Bytes830G2(value []byte) string {
	sum := sha256.Sum256(value)
	return hex.EncodeToString(sum[:])
}
func jsonEOF830G2(decoder *json.Decoder) bool {
	var extra any
	return errors.Is(decoder.Decode(&extra), io.EOF)
}

func canonicalJSON830G2(value any) ([]byte, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	var tree any
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if decoder.Decode(&tree) != nil || !jsonEOF830G2(decoder) {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	var output bytes.Buffer
	encoder := json.NewEncoder(&output)
	encoder.SetEscapeHTML(false)
	if encoder.Encode(tree) != nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	return bytes.TrimSuffix(output.Bytes(), []byte("\n")), nil
}

func computeConceptCitationAuthorityDigest830G2(authority ConceptCitationContentAuthority830G2) (string, error) {
	if authority.Contract != conceptCitationAuthorityContract830G2 {
		return "", ErrConceptSourceAuthorityUnavailable830G2
	}
	raw, err := json.Marshal(authority)
	if err != nil {
		return "", err
	}
	var preimage map[string]any
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if decoder.Decode(&preimage) != nil || !jsonEOF830G2(decoder) {
		return "", ErrConceptSourceAuthorityUnavailable830G2
	}
	delete(preimage, "authority_digest")
	delete(preimage, "opaque_token")
	canonical, err := canonicalJSON830G2(preimage)
	if err != nil {
		return "", err
	}
	return testSHA256Bytes830G2(append([]byte(conceptCitationAuthorityContract830G2+"\n"), canonical...)), nil
}

func validateConceptCitationAuthority830G2(authority ConceptCitationContentAuthority830G2) error {
	digest, err := computeConceptCitationAuthorityDigest830G2(authority)
	if err != nil || digest != authority.AuthorityDigest || authority.TokenKeyID == "" || authority.ReleaseID == "" || authority.ActivationEpoch == 0 || !validServiceSHA256(authority.CandidateHash) || authority.MemberID == "" || authority.CitationID == "" || authority.Scope.TenantID == 0 || authority.Scope.SpaceID == "" || authority.Scope.RawKBID == "" || authority.Scope.WikiKBID == "" || authority.Source.TenantID != authority.Scope.TenantID || authority.Source.SpaceID != authority.Scope.SpaceID || authority.Source.RawKBID != authority.Scope.RawKBID || authority.Source.KnowledgeID == "" || authority.Source.ParseAttempt <= 0 || !validServiceSHA256(authority.Source.RevisionID) || !validServiceSHA256(authority.Source.SourceHash) || !validServiceSHA256(authority.Source.ParseHash) || !validServiceSHA256(authority.Source.ParserIdentity) || authority.RevisionSource.FileSHA256 != authority.Source.SourceHash || !validServiceSHA256(authority.RevisionSource.BindingDigest) || authority.RevisionSource.PageCount <= 0 || authority.BlockID == "" || authority.PageNumber <= 0 || authority.PageNumber > authority.RevisionSource.PageCount || !validServiceSHA256(authority.QuoteHash) || authority.BBox.CoordinateSpace != "normalized_0_1e6_top_left" || !validConceptBBox830G2([4]int{authority.BBox.X0, authority.BBox.Y0, authority.BBox.X1, authority.BBox.Y1}) || authority.ExpiresAtUnix <= 0 || authority.OpaqueToken != "" {
		return ErrConceptSourceAuthorityUnavailable830G2
	}
	return nil
}

func conceptCanonicalEqual830G2(left, right ConceptCitationContentAuthority830G2) bool {
	a, e1 := canonicalJSON830G2(left)
	b, e2 := canonicalJSON830G2(right)
	return e1 == nil && e2 == nil && bytes.Equal(a, b)
}

func (c *SchemaWikiCitationTokenCodec) issueConcept830G2(scope types.WikiReleaseScope, authority ConceptCitationContentAuthority830G2, now time.Time) (string, error) {
	if c == nil || c.activeKeyID == "" || authority.TokenKeyID != c.activeKeyID || authority.Scope != scope {
		return "", ErrSchemaWikiCitationUnavailable
	}
	key, ok := c.privateKeys[c.activeKeyID]
	if !ok {
		return "", ErrSchemaWikiCitationUnavailable
	}
	copyAuthority := authority
	copyAuthority.OpaqueToken = ""
	claims := conceptCitationTokenClaims830G2{Contract: conceptCitationClaimsContract830G2, TokenKeyID: c.activeKeyID, IssuedAtUnix: now.UTC().Unix(), ExpiresAtUnix: authority.ExpiresAtUnix, Scope: scope, Authority: copyAuthority}
	payload, err := canonicalJSON830G2(claims)
	if err != nil {
		return "", ErrSchemaWikiCitationUnavailable
	}
	signature := ed25519Sign830G2(key, append([]byte("concept-citation-content-token.830.g2.v1\n"), payload...))
	return strings.Join([]string{base64.RawURLEncoding.EncodeToString([]byte(c.activeKeyID)), base64.RawURLEncoding.EncodeToString(payload), base64.RawURLEncoding.EncodeToString(signature)}, "."), nil
}

func (c *SchemaWikiCitationTokenCodec) verifyConcept830G2(token string) (conceptCitationTokenClaims830G2, error) {
	empty := conceptCitationTokenClaims830G2{}
	parts := strings.Split(token, ".")
	if c == nil || len(parts) != 3 || token != strings.TrimSpace(token) {
		return empty, ErrSchemaWikiCitationUnavailable
	}
	keyIDRaw, e1 := base64.RawURLEncoding.DecodeString(parts[0])
	payload, e2 := base64.RawURLEncoding.DecodeString(parts[1])
	signature, e3 := base64.RawURLEncoding.DecodeString(parts[2])
	keyID := string(keyIDRaw)
	key, ok := c.publicKeys[keyID]
	if e1 != nil || e2 != nil || e3 != nil || !ok || base64.RawURLEncoding.EncodeToString(keyIDRaw) != parts[0] || base64.RawURLEncoding.EncodeToString(payload) != parts[1] || base64.RawURLEncoding.EncodeToString(signature) != parts[2] || !ed25519Verify830G2(key, append([]byte("concept-citation-content-token.830.g2.v1\n"), payload...), signature) {
		return empty, ErrSchemaWikiCitationUnavailable
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	var claims conceptCitationTokenClaims830G2
	if decoder.Decode(&claims) != nil || !jsonEOF830G2(decoder) {
		return empty, ErrSchemaWikiCitationUnavailable
	}
	canonical, err := canonicalJSON830G2(claims)
	digest, digestErr := computeConceptCitationAuthorityDigest830G2(claims.Authority)
	now := c.now().UTC().Unix()
	if err != nil || digestErr != nil || !bytes.Equal(canonical, payload) || claims.Contract != conceptCitationClaimsContract830G2 || claims.TokenKeyID != keyID || claims.Authority.TokenKeyID != keyID || claims.Scope != claims.Authority.Scope || claims.Authority.OpaqueToken != "" || claims.IssuedAtUnix <= 0 || claims.ExpiresAtUnix-claims.IssuedAtUnix != int64(schemaWikiCitationTokenTTL/time.Second) || now < claims.IssuedAtUnix || now >= claims.ExpiresAtUnix || claims.Authority.ExpiresAtUnix != claims.ExpiresAtUnix || digest != claims.Authority.AuthorityDigest || validateConceptCitationAuthority830G2(claims.Authority) != nil {
		return empty, ErrSchemaWikiCitationUnavailable
	}
	return claims, nil
}

// Kept behind tiny wrappers so this file shares the codec's ed25519 key ring
// without exporting signing material or accepting another key authority.
func ed25519Sign830G2(key []byte, message []byte) []byte { return ed25519.Sign(key, message) }
func ed25519Verify830G2(key []byte, message, signature []byte) bool {
	return ed25519.Verify(key, message, signature)
}

func conceptMemberEvidence830G2(bundle types.ConceptCandidateBundle830G2, memberID string) []types.ConceptEvidence830G2 {
	for _, definition := range bundle.CompileResult.Output.Definitions {
		id, _ := definition.DefinitionID()
		if id == memberID {
			return definition.Evidence
		}
	}
	for _, field := range bundle.CompileResult.Output.Fields {
		id, _ := field.FieldAssertionID()
		if id == memberID {
			return field.Evidence
		}
	}
	for _, page := range bundle.CompileResult.Output.Pages {
		id, _ := page.FreeWikiPageID()
		if id == memberID {
			return page.Evidence
		}
	}
	return nil
}

func conceptSourceBlockForEvidence830G2(bundle types.ConceptCandidateBundle830G2, evidence types.ConceptEvidence830G2) (types.ConceptSourceBlock830G2, bool) {
	for _, source := range bundle.Request.Sources {
		if source.ConceptSourceIdentity830G2 == evidence.ConceptSourceIdentity830G2 &&
			source.BlockID == evidence.BlockID && source.PageNumber == evidence.PageNumber &&
			source.SourceType == evidence.SourceType && conceptEvidenceMatchesSourceText830G2(evidence, source.Text) {
			return source, true
		}
	}
	return types.ConceptSourceBlock830G2{}, false
}

func conceptEvidenceMatchesSourceText830G2(evidence types.ConceptEvidence830G2, text string) bool {
	runes := []rune(text)
	return evidence.Start >= 0 && evidence.End > evidence.Start && evidence.End <= len(runes) &&
		utf8.RuneCountInString(evidence.Quote) == evidence.End-evidence.Start &&
		string(runes[evidence.Start:evidence.End]) == evidence.Quote &&
		testSHA256830G2(evidence.Quote) == evidence.QuoteHash
}

// verifyLegacyCarryover830G2 follows the immutable G2 base chain to its G1
// migration source and replays that source's original C5 two-stage authority.
// Only a migrated field whose factual payload is unchanged may consume the
// resulting proof. Later releases may add concept navigation metadata.
func (s *ConceptSourceAuthorityService830G2) verifyLegacyCarryover830G2(ctx context.Context, scope types.WikiReleaseScope, bundle types.ConceptCandidateBundle830G2) (map[string]conceptLegacyProof830G2, error) {
	if s != nil && s.legacyProofResolver != nil {
		return s.legacyProofResolver(ctx, scope, bundle)
	}
	allowed := map[string]conceptLegacyProof830G2{}
	releaseID := bundle.Request.BaseReleaseID
	if releaseID == "" {
		return allowed, nil
	}
	if s == nil || s.releases == nil {
		return nil, ErrConceptSourceAuthorityUnavailable830G2
	}
	for depth := 0; depth < 64; depth++ {
		release, err := s.releases.GetRelease(ctx, scope, releaseID)
		if err != nil || release == nil {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		preparation, err := s.releases.GetReadyPreparation(ctx, scope, release.PreparationID)
		if err != nil {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		members, err := s.releases.GetReleaseMembers(ctx, scope, release.ID)
		if err != nil {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		var header struct {
			Contract string `json:"contract"`
		}
		if json.Unmarshal(preparation.Manifest, &header) != nil {
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
		switch header.Contract {
		case "concept-candidate-bundle.830.g2.v1", "concept-candidate-bundle.830.g2.v2":
			base, expected, validationErr := validateConceptPreparation830G2(preparation, types.WikiReleasePreparationReady, scope)
			if validationErr != nil || release.CandidateDigest != preparation.CandidateDigest || release.ManifestDigest != preparation.ManifestDigest || !conceptMemberSnapshotSetsEqual830G2(expected, members) || release.BaseReleaseID != base.Request.BaseReleaseID || release.BaseActivationEpoch != base.Request.BaseActivationEpoch {
				return nil, ErrConceptSourceAuthorityUnavailable830G2
			}
			releaseID = base.Request.BaseReleaseID
			if releaseID == "" {
				return allowed, nil
			}
		case "entity-page-manifest.830.g1.v1":
			if s.legacyCitationContent == nil || s.formalCandidatePreview == nil {
				return nil, ErrConceptSourceAuthorityUnavailable830G2
			}
			manifest, expected, validationErr := validateEntityPageGraphPreparation830G1(preparation, types.WikiReleasePreparationReady, scope)
			if validationErr != nil || release.CandidateDigest != preparation.CandidateDigest || release.ManifestDigest != preparation.ManifestDigest || release.BaseReleaseID != manifest.ReleaseID || release.BaseActivationEpoch != manifest.ActivationEpoch || !entityPageGraphMemberSetsEqual830G1(expected, members) {
				return nil, ErrConceptSourceAuthorityUnavailable830G2
			}
			custody, loadErr := s.loadLegacySchemaCustody830G2(ctx, scope, manifest.ReleaseID, manifest.ActivationEpoch)
			if loadErr != nil {
				return nil, loadErr
			}
			adapter := &SchemaWikiService{citationContent: s.legacyCitationContent, formalCandidatePreview: s.formalCandidatePreview}
			authorities := make([]*types.SchemaWikiCitationContentAuthorityV1, 0, len(custody.candidateEvidenceAuthority.JoinReceipts))
			verify := func(callCtx context.Context, callCustody validatedSchemaWikiCustody, request CitationRevisionReadRequestV1) error {
				authority, issueErr := adapter.issueConceptG1Citation830G2(callCtx, callCustody, request)
				if issueErr == nil {
					authorities = append(authorities, authority)
				}
				return issueErr
			}
			fields, _, migrationErr := conceptG1ExistingSnapshot830G2(ctx, scope, manifest, custody, bundle.Request.Sources, verify)
			if migrationErr != nil {
				return nil, migrationErr
			}
			authorityIndex := 0
			for _, field := range fields {
				target, ok := conceptLegacyCarryoverTargetField830G2(field, bundle.Request.ExistingFields, bundle.CompileResult.Output.Fields)
				targetID := ""
				if ok {
					var idErr error
					targetID, idErr = target.FieldAssertionID()
					if idErr != nil {
						return nil, ErrConceptSourceAuthorityUnavailable830G2
					}
				}
				for _, evidence := range field.Evidence {
					if authorityIndex >= len(authorities) {
						return nil, ErrConceptSourceAuthorityUnavailable830G2
					}
					authority := authorities[authorityIndex]
					authorityIndex++
					if !ok {
						// The old citation was replayed, but a changed assertion may
						// only publish after its current evidence passes native authority.
						continue
					}
					canonical, canonicalErr := canonicalJSON830G2(evidence)
					if canonicalErr != nil {
						return nil, canonicalErr
					}
					allowed[targetID+"\x00"+testSHA256Bytes830G2(canonical)] = conceptLegacyProof830G2{authority: authority}
				}
			}
			if authorityIndex != len(authorities) {
				return nil, ErrConceptSourceAuthorityUnavailable830G2
			}
			return allowed, nil
		default:
			return nil, ErrConceptSourceAuthorityUnavailable830G2
		}
	}
	return nil, ErrConceptSourceAuthorityUnavailable830G2
}

func conceptReferencedExistingSourceKeys830G2(bundle types.ConceptCandidateBundle830G2) (map[string]struct{}, error) {
	keys := map[string]struct{}{}
	collections := make([][]types.ConceptEvidence830G2, 0, len(bundle.Request.ExistingDefinitions)+len(bundle.Request.ExistingFields)+len(bundle.Request.ExistingPages))
	for _, definition := range bundle.Request.ExistingDefinitions {
		collections = append(collections, definition.Evidence)
	}
	for _, field := range bundle.Request.ExistingFields {
		collections = append(collections, field.Evidence)
	}
	for _, page := range bundle.Request.ExistingPages {
		collections = append(collections, page.Evidence)
	}
	for _, evidenceList := range collections {
		for _, evidence := range evidenceList {
			if _, ok := conceptSourceBlockForEvidence830G2(bundle, evidence); !ok {
				return nil, ErrConceptSourceAuthorityUnavailable830G2
			}
			keys[evidence.RevisionID+"\x00"+evidence.BlockID] = struct{}{}
		}
	}
	return keys, nil
}

func conceptLegacyCarryoverTargetField830G2(
	migrated types.ConceptFieldAssertion830G2,
	existing []types.ConceptFieldAssertion830G2,
	output []types.ConceptFieldAssertion830G2,
) (types.ConceptFieldAssertion830G2, bool) {
	existingCandidate, ok := conceptFieldMatchingExceptNavigation830G2(migrated, existing)
	if !ok {
		return types.ConceptFieldAssertion830G2{}, false
	}
	for _, candidate := range output {
		withoutNavigation := candidate
		withoutNavigation.ConceptIDs = existingCandidate.ConceptIDs
		if !reflect.DeepEqual(withoutNavigation, existingCandidate) || !containsAllConceptIDs830G2(candidate.ConceptIDs, existingCandidate.ConceptIDs) {
			continue
		}
		return candidate, true
	}
	return types.ConceptFieldAssertion830G2{}, false
}

func conceptFieldMatchingExceptNavigation830G2(
	reference types.ConceptFieldAssertion830G2,
	candidates []types.ConceptFieldAssertion830G2,
) (types.ConceptFieldAssertion830G2, bool) {
	for _, candidate := range candidates {
		withoutNavigation := candidate
		withoutNavigation.ConceptIDs = reference.ConceptIDs
		if reflect.DeepEqual(withoutNavigation, reference) {
			return candidate, true
		}
	}
	return types.ConceptFieldAssertion830G2{}, false
}

func containsAllConceptIDs830G2(candidate, required []string) bool {
	for _, requiredID := range required {
		found := false
		for _, candidateID := range candidate {
			if candidateID == requiredID {
				found = true
				break
			}
		}
		if !found {
			return false
		}
	}
	return true
}

func (s *ConceptSourceAuthorityService830G2) loadLegacySchemaCustody830G2(ctx context.Context, scope types.WikiReleaseScope, releaseID string, activationEpoch uint64) (validatedSchemaWikiCustody, error) {
	var empty validatedSchemaWikiCustody
	release, err := s.releases.GetRelease(ctx, scope, releaseID)
	if err != nil {
		return empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	preparation, err := s.releases.GetReadyPreparation(ctx, scope, release.PreparationID)
	if err != nil {
		return empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	members, err := s.releases.GetReleaseMembers(ctx, scope, releaseID)
	if err != nil {
		return empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	validated, err := validateSchemaWikiPreparation(preparation, types.WikiReleasePreparationReady, scope)
	if err != nil || release.ID != releaseID || release.WikiReleaseScope != scope || release.PreparationID != preparation.ID || release.CandidateDigest != preparation.CandidateDigest || release.ManifestDigest != preparation.ManifestDigest || release.BaseActivationEpoch == ^uint64(0) || release.BaseActivationEpoch+1 != activationEpoch {
		return empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	expected := validated.snapshots
	if validated.isolatedC6 {
		expected = validated.storedSnapshots
	}
	if _, ok := schemaWikiAlignReleaseMembers(members, expected, validated.isolatedC6); !ok {
		return empty, ErrConceptSourceAuthorityUnavailable830G2
	}
	return validated, nil
}
