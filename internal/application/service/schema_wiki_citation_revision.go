package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"math/big"
	"reflect"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/Tencent/WeKnora/internal/types/interfaces"
)

type schemaWikiCitationRevisionRepository interface {
	GetKnowledgeByID(context.Context, uint64, string) (*types.Knowledge, error)
	GetRevision(context.Context, string, int64) (*types.KnowledgeRevision, error)
	GetRevisionSource(
		context.Context, uint64, string, int64,
	) (*types.KnowledgeRevisionSource, *types.StoredResource, error)
}

type schemaWikiCitationChunkRepository interface {
	GetChunkByID(context.Context, uint64, string) (*types.Chunk, error)
	ListChunksByKnowledgeID(context.Context, uint64, string) ([]*types.Chunk, error)
}

const (
	schemaWikiCoordinatePolicySHA256 = "fd86399f644e6703e847686080f42799dca5376cdfb96e04fd49e6fa3b97c9ae"
	schemaWikiSourceCoordinateSpace  = "mineru_content_list_normalized_0_1000_top_left.v1"
	schemaWikiTargetCoordinateSpace  = "normalized_0_1e6"
)

type schemaWikiC5NativeChunkProjection struct {
	ChunkID       string `json:"chunk_id"`
	ChunkIndex    int    `json:"chunk_index"`
	ContentSHA256 string `json:"content_sha256"`
}

type schemaWikiC5NativeSourceManifest struct {
	Contract                 string                              `json:"contract"`
	Role                     string                              `json:"role"`
	TenantID                 uint64                              `json:"tenant_id"`
	KnowledgeBaseID          string                              `json:"knowledge_base_id"`
	KnowledgeID              string                              `json:"knowledge_id"`
	WeKnoraParseAttempt      int64                               `json:"weknora_parse_attempt"`
	ResourceID               string                              `json:"resource_id"`
	ResourcePhysicalPath     string                              `json:"resource_physical_path"`
	ResourceState            string                              `json:"resource_state"`
	ResourceBindingCount     int                                 `json:"resource_binding_count"`
	FileName                 string                              `json:"file_name"`
	FileSHA256               string                              `json:"file_sha256"`
	FileSize                 int64                               `json:"file_size"`
	MimeType                 string                              `json:"mime_type"`
	MaterialFile             string                              `json:"material_file"`
	PageCount                int                                 `json:"page_count"`
	ParseStatus              string                              `json:"parse_status"`
	ParseCompletedAt         string                              `json:"parse_completed_at"`
	ParseIdentity            map[string]any                      `json:"parse_identity"`
	ParseManifestAlgorithm   string                              `json:"parse_manifest_algorithm"`
	ParseManifestSHA256      string                              `json:"parse_manifest_sha256"`
	ChunkCount               int                                 `json:"chunk_count"`
	OrderedChunkProjection   []schemaWikiC5NativeChunkProjection `json:"ordered_chunk_projection"`
	CompilerSourceRevisionID string                              `json:"compiler_source_revision_id"`
	ManifestSelfSHA256       string                              `json:"manifest_self_sha256"`
}

var schemaWikiC5NativeSourceManifestKeys = map[string]struct{}{
	"chunk_count": {}, "compiler_source_revision_id": {}, "contract": {},
	"file_name": {}, "file_sha256": {}, "file_size": {},
	"knowledge_base_id": {}, "knowledge_id": {}, "manifest_self_sha256": {},
	"material_file": {}, "mime_type": {}, "ordered_chunk_projection": {},
	"page_count": {}, "parse_completed_at": {}, "parse_identity": {},
	"parse_manifest_algorithm": {}, "parse_manifest_sha256": {},
	"parse_status": {}, "resource_binding_count": {}, "resource_id": {},
	"resource_physical_path": {}, "resource_state": {}, "role": {},
	"tenant_id": {}, "weknora_parse_attempt": {},
}

// SchemaWikiCitationCoordinateAuthorityReceiptV1 is the server-replay input
// required before a Candidate citation may become a fixed-revision preview.
// Its digest is not authority by itself: the code-owned snapshot reader must
// resolve and join it to native revision/source/chunk state.
type SchemaWikiCitationCoordinateAuthorityReceiptV1 = types.Schema67CitationAuthorityJoinReceiptV1

type SchemaWikiImmutableRevisionSnapshotRequestV1 struct {
	Contract               string                                         `json:"contract"`
	ReleaseID              string                                         `json:"release_id,omitempty"`
	ActivationEpoch        uint64                                         `json:"activation_epoch,omitempty"`
	PreparationID          string                                         `json:"preparation_id,omitempty"`
	EvaluationID           string                                         `json:"evaluation_id,omitempty"`
	EvidenceID             string                                         `json:"evidence_id,omitempty"`
	Scope                  types.WikiReleaseScope                         `json:"scope"`
	CandidateSHA256        string                                         `json:"candidate_sha256"`
	LogicalMemberRef       string                                         `json:"logical_member_ref"`
	FieldID                string                                         `json:"field_id"`
	CitationID             string                                         `json:"citation_id"`
	CitationSHA256         string                                         `json:"citation_sha256"`
	BindingSHA256          string                                         `json:"binding_sha256"`
	KnowledgeID            string                                         `json:"knowledge_id"`
	ParseAttempt           int64                                          `json:"parse_attempt"`
	ResourceID             string                                         `json:"resource_id"`
	FileSHA256             string                                         `json:"file_sha256"`
	Size                   int64                                          `json:"size"`
	MimeType               string                                         `json:"mime_type"`
	ManifestAlgorithm      string                                         `json:"manifest_algorithm"`
	ManifestDigest         string                                         `json:"manifest_digest"`
	ChunkCount             int                                            `json:"chunk_count"`
	ParsedDocumentSHA256   string                                         `json:"parsed_document_sha256"`
	EvidenceReceiptSHA256s []string                                       `json:"evidence_receipt_sha256s"`
	CoordinateReceipt      SchemaWikiCitationCoordinateAuthorityReceiptV1 `json:"coordinate_receipt"`
	LiveSourceReceipt      types.LiveRevisionSourceReceiptV1              `json:"live_source_receipt"`
}

type SchemaWikiCitationPreviewAuthorityV1 struct {
	Contract               string                                       `json:"contract"`
	Request                SchemaWikiImmutableRevisionSnapshotRequestV1 `json:"request"`
	FieldID                string                                       `json:"field_id"`
	ChunkID                string                                       `json:"chunk_id"`
	LocatorRef             string                                       `json:"locator_ref"`
	PageNumber             int                                          `json:"page_number"`
	BBox                   types.CitationBBoxV1                         `json:"bbox"`
	CoordinateSpaceVersion string                                       `json:"coordinate_space_version"`
	PageWidth              int                                          `json:"page_width"`
	PageHeight             int                                          `json:"page_height"`
	RotationDegrees        int                                          `json:"rotation_degrees"`
	QuoteSHA256            string                                       `json:"quote_sha256"`
	ContentSnapshotSHA256  string                                       `json:"content_snapshot_sha256"`
	EvidenceReceiptSHA256s []string                                     `json:"evidence_receipt_sha256s"`
	OpaqueToken            string                                       `json:"opaque_token"`
	AuthoritySHA256        string                                       `json:"authority_sha256"`
}

type schemaWikiImmutableRevisionSnapshotReader interface {
	ResolveCitationPreviewAuthority(
		context.Context, SchemaWikiImmutableRevisionSnapshotRequestV1,
	) (*SchemaWikiCitationPreviewAuthorityV1, error)
	ReadByOpaqueToken(context.Context, string) ([]byte, error)
}

func schemaWikiCitationCoordinateAuthorityReceiptSHA256(
	receipt SchemaWikiCitationCoordinateAuthorityReceiptV1,
) string {
	digest, err := types.ComputeSchema67CitationAuthorityJoinReceiptSHA256(receipt)
	if err != nil {
		return ""
	}
	return digest
}

func schemaWikiCitationPreviewAuthoritySHA256(
	authority SchemaWikiCitationPreviewAuthorityV1,
) string {
	authority.AuthoritySHA256 = ""
	payload, err := json.Marshal(authority)
	if err != nil {
		return ""
	}
	sum := sha256.Sum256(append(
		[]byte("schema-wiki-citation-preview-authority.v1\n"), payload...,
	))
	return hex.EncodeToString(sum[:])
}

func validateSchemaWikiCitationPreviewAuthority(
	request SchemaWikiImmutableRevisionSnapshotRequestV1,
	authority SchemaWikiCitationPreviewAuthorityV1,
) error {
	receipt := request.CoordinateReceipt
	liveDigest, liveErr := types.ComputeLiveRevisionSourceReceiptSHA256(request.LiveSourceReceipt)
	if authority.Contract != "schema-wiki-citation-preview-authority.v1" ||
		liveErr != nil || liveDigest != request.LiveSourceReceipt.SourceReceiptSHA256 ||
		!reflect.DeepEqual(request.LiveSourceReceipt, receipt.LiveRevisionSourceReceipt) ||
		liveDigest != receipt.LiveRevisionSourceReceiptSHA256 ||
		!reflect.DeepEqual(authority.Request, request) ||
		authority.FieldID != request.FieldID || authority.ChunkID != receipt.ChunkID ||
		authority.LocatorRef != receipt.LocatorRef || authority.PageNumber != receipt.PageNumber ||
		!reflect.DeepEqual(authority.BBox, receipt.NormalizedBBox) ||
		authority.CoordinateSpaceVersion != receipt.TargetCoordinateSpace ||
		authority.PageWidth != receipt.PageWidth || authority.PageHeight != receipt.PageHeight ||
		authority.RotationDegrees != receipt.RotationDegrees ||
		authority.QuoteSHA256 != receipt.QuoteSHA256 ||
		authority.ContentSnapshotSHA256 != receipt.LocatorContentSHA256 ||
		!reflect.DeepEqual(authority.EvidenceReceiptSHA256s, request.EvidenceReceiptSHA256s) ||
		!schemaWikiOpaqueSnapshotToken(authority.OpaqueToken) ||
		authority.AuthoritySHA256 != schemaWikiCitationPreviewAuthoritySHA256(authority) {
		return ErrSchemaWikiCitationUnavailable
	}
	return nil
}

func validateSchemaWikiCitationCoordinateAuthorityReceipt(
	request CitationRevisionReadRequestV1,
	receipt SchemaWikiCitationCoordinateAuthorityReceiptV1,
	revision *types.KnowledgeRevision,
	source *types.KnowledgeRevisionSource,
	chunk *types.Chunk,
) error {
	if receipt.Contract != "schema67-citation-authority-join-receipt.v1" ||
		types.ValidateSchema67CitationAuthorityJoinReceiptV1(receipt) != nil ||
		receipt.ReceiptSHA256 != schemaWikiCitationCoordinateAuthorityReceiptSHA256(receipt) ||
		source == nil || source.PageCount == nil || *source.PageCount <= 0 ||
		receipt.PageNumber <= 0 || receipt.PageNumber > *source.PageCount ||
		receipt.NativePageIndex+1 != receipt.PageNumber ||
		receipt.CandidateSHA256 != request.CandidateSHA256 || receipt.FieldID != request.FieldID ||
		receipt.SourceRole != request.Citation.SourceRole ||
		!schemaWikiContainsExact(request.EvidenceReceiptSHA256s, receipt.EvidenceReceiptSHA256) ||
		receipt.SourceSHA256 != source.FileSHA256 || receipt.FileSHA256 != source.FileSHA256 ||
		receipt.ParsedDocumentSHA256 != request.Citation.ParsedDocumentSHA256 ||
		receipt.ParseManifestSHA256 != request.Citation.ParseManifestSHA256 ||
		receipt.EvidenceParseAttemptID != request.Citation.ParseAttemptID ||
		receipt.LocatorRef != request.Citation.LocatorRef ||
		receipt.PageNumber != request.Citation.PageNumber ||
		receipt.LocatorContentSHA256 != request.Citation.ContentSnapshotSHA256 ||
		receipt.QuoteSHA256 != request.Citation.QuoteSHA256 ||
		receipt.CoordinatePolicySHA256 != schemaWikiCoordinatePolicySHA256 ||
		receipt.SourceCoordinateSpace != schemaWikiSourceCoordinateSpace ||
		receipt.TargetCoordinateSpace != schemaWikiTargetCoordinateSpace ||
		receipt.Origin != "top_left" || receipt.PageWidth != 1_000_000 ||
		receipt.PageHeight != 1_000_000 || !schemaWikiRotation(receipt.RotationDegrees) ||
		receipt.NormalizedBBox.CoordinateSystem != schemaWikiTargetCoordinateSpace ||
		receipt.NormalizedBBox.PageWidth != receipt.PageWidth ||
		receipt.NormalizedBBox.PageHeight != receipt.PageHeight ||
		!reflect.DeepEqual(receipt.NormalizedBBox, request.Citation.BBox) ||
		receipt.TenantID != request.Scope.TenantID || receipt.SpaceID != request.Scope.SpaceID ||
		receipt.RawKBID != request.Scope.RawKBID || receipt.KnowledgeID != request.Citation.KnowledgeID ||
		receipt.WeKnoraParseAttempt != revision.ParseAttempt ||
		receipt.WeKnoraManifestAlgorithm != revision.ManifestAlgorithm ||
		receipt.WeKnoraManifestDigest != revision.ManifestDigest ||
		receipt.ChunkID != request.Citation.ChunkID || chunk == nil ||
		receipt.ChunkID != chunk.ID || receipt.ChunkIndex != chunk.ChunkIndex ||
		receipt.QuoteOccurrenceCount != 1 ||
		receipt.QuoteOccurrenceStart < 0 || receipt.QuoteOccurrenceEnd <= receipt.QuoteOccurrenceStart ||
		receipt.QuoteOccurrenceEnd > len(chunk.Content) ||
		chunk.Content[receipt.QuoteOccurrenceStart:receipt.QuoteOccurrenceEnd] != request.Citation.QuoteSnapshot ||
		strings.Count(chunk.Content, request.Citation.QuoteSnapshot) != 1 ||
		!schemaWikiSHA256(receipt.ChunkContentSHA256) ||
		receipt.ChunkContentSHA256 != schemaWikiStringSHA256(chunk.Content) ||
		!schemaWikiSHA256(receipt.CaptureIdentitySHA256) ||
		!schemaWikiSHA256(receipt.RawStructureSHA256) ||
		!schemaWikiSHA256(receipt.SanitizedStructureSHA256) ||
		!schemaWikiSHA256(receipt.ParserIdentitySHA256) ||
		!schemaWikiSHA256(receipt.JoinPolicySHA256) ||
		!schemaWikiSHA256(receipt.LiveRevisionSourceReceiptSHA256) ||
		types.ValidateLiveRevisionSourceReceiptV1(receipt.LiveRevisionSourceReceipt) != nil ||
		receipt.LiveRevisionSourceReceipt.SourceReceiptSHA256 != receipt.LiveRevisionSourceReceiptSHA256 ||
		!schemaWikiScaledBBoxMatches(receipt.SourceBBoxPreimage, receipt.NormalizedBBox) ||
		!schemaWikiLocatorPrecision(receipt.LocatorKind, receipt.HighlightPrecision) {
		return ErrSchemaWikiCitationUnavailable
	}
	liveReceipt := types.LiveRevisionSourceReceiptV1{
		Contract:         "live-revision-source-receipt.v1",
		RevisionSourceID: source.RevisionSourceID,
		TenantID:         request.Scope.TenantID, SpaceID: request.Scope.SpaceID,
		RawKBID: request.Scope.RawKBID, WikiKBID: request.Scope.WikiKBID,
		KnowledgeID:            request.Citation.KnowledgeID,
		EvidenceParseAttemptID: receipt.EvidenceParseAttemptID,
		WeKnoraParseAttempt:    revision.ParseAttempt, ResourceID: source.ResourceID,
		FileSHA256: source.FileSHA256, Size: source.Size, MimeType: source.MimeType,
		PageCount: *source.PageCount, ParsedDocumentSHA256: receipt.ParsedDocumentSHA256,
		ParseManifestSHA256:      receipt.ParseManifestSHA256,
		WeKnoraManifestAlgorithm: revision.ManifestAlgorithm,
		WeKnoraManifestDigest:    revision.ManifestDigest,
		WeKnoraChunkCount:        revision.ChunkCount,
	}
	liveDigest, err := types.ComputeLiveRevisionSourceReceiptSHA256(liveReceipt)
	liveReceipt.SourceReceiptSHA256 = liveDigest
	if err != nil || liveDigest != receipt.LiveRevisionSourceReceiptSHA256 ||
		!reflect.DeepEqual(liveReceipt, receipt.LiveRevisionSourceReceipt) {
		return ErrSchemaWikiCitationUnavailable
	}
	return nil
}

func schemaWikiSHA256(value string) bool {
	if len(value) != sha256.Size*2 || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}

func schemaWikiStringSHA256(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])
}

func schemaWikiContainsExact(values []string, expected string) bool {
	found := false
	seen := make(map[string]struct{}, len(values))
	for _, value := range values {
		if !schemaWikiSHA256(value) {
			return false
		}
		if _, duplicate := seen[value]; duplicate {
			return false
		}
		seen[value] = struct{}{}
		found = found || value == expected
	}
	return found
}

func schemaWikiScaledBBoxMatches(source [4]string, normalized types.CitationBBoxV1) bool {
	expected := []int{normalized.X0, normalized.Y0, normalized.X1, normalized.Y1}
	for index, value := range source {
		rational, ok := new(big.Rat).SetString(value)
		if !ok || rational.Sign() < 0 {
			return false
		}
		rational.Mul(rational, big.NewRat(1000, 1))
		if !rational.IsInt() || !rational.Num().IsInt64() || int(rational.Num().Int64()) != expected[index] {
			return false
		}
	}
	return expected[0] < expected[2] && expected[1] < expected[3] &&
		expected[2] <= 1_000_000 && expected[3] <= 1_000_000
}

func schemaWikiLocatorPrecision(kind string, precision string) bool {
	switch kind {
	case "block", "table":
		return precision == "locator_exact"
	case "cell":
		return precision == "table_scoped_not_cell_exact_stop"
	default:
		return false
	}
}

func schemaWikiRotation(rotation int) bool {
	return rotation == 0 || rotation == 90 || rotation == 180 || rotation == 270
}

func schemaWikiOpaqueSnapshotToken(token string) bool {
	if token == "" || len(token) > 256 || strings.TrimSpace(token) != token ||
		strings.ContainsAny(token, "/\\\r\n") || strings.Contains(token, "://") {
		return false
	}
	return true
}

func schemaWikiC5CanonicalTextForParentOccurrence(
	original *types.Chunk,
	textChunks []*types.Chunk,
	quote string,
	receipt *SchemaWikiCitationCoordinateAuthorityReceiptV1,
) (*types.Chunk, bool) {
	if original == nil || receipt == nil || original.ChunkType != types.ChunkTypeParentText ||
		!utf8.ValidString(original.Content) || !utf8.ValidString(quote) || quote == "" {
		return nil, false
	}
	parentRunes := []rune(original.Content)
	quoteRunes := []rune(quote)
	if original.StartAt < 0 || original.EndAt <= original.StartAt ||
		original.EndAt-original.StartAt != len(parentRunes) ||
		receipt.QuoteOccurrenceStart < 0 ||
		receipt.QuoteOccurrenceEnd <= receipt.QuoteOccurrenceStart ||
		receipt.QuoteOccurrenceEnd-receipt.QuoteOccurrenceStart != len(quoteRunes) ||
		receipt.QuoteOccurrenceEnd > len(parentRunes) {
		return nil, false
	}
	absoluteStart := original.StartAt + receipt.QuoteOccurrenceStart
	absoluteEnd := original.StartAt + receipt.QuoteOccurrenceEnd
	if absoluteEnd > original.EndAt {
		return nil, false
	}

	siblings := make([]*types.Chunk, 0)
	for _, chunk := range textChunks {
		if chunk != nil && chunk.ParentChunkID == original.ID {
			siblings = append(siblings, chunk)
		}
	}
	if len(siblings) == 0 {
		return nil, false
	}

	// SplitTextParentChild stores absolute rune offsets. Its ordered text
	// reconstruction keeps the first copy of an overlap and lets each later
	// child contribute only the suffix beyond the prior end. Apply that same
	// frontier here so two children carrying one source occurrence still have
	// exactly one canonical owner.
	frontier := original.StartAt
	previousIndex := -1
	previousStart := -1
	matchingOccurrences := 0
	var owner *types.Chunk
	for index, chunk := range siblings {
		chunkRunes := []rune(chunk.Content)
		if !utf8.ValidString(chunk.Content) || chunk.ChunkIndex < 0 ||
			chunk.StartAt < original.StartAt || chunk.EndAt > original.EndAt ||
			chunk.EndAt <= chunk.StartAt || chunk.EndAt-chunk.StartAt != len(chunkRunes) ||
			chunk.StartAt > frontier || chunk.EndAt <= frontier ||
			(index == 0 && chunk.StartAt != original.StartAt) ||
			(index > 0 && (chunk.ChunkIndex != previousIndex+1 || chunk.StartAt <= previousStart)) {
			return nil, false
		}
		relativeStart := chunk.StartAt - original.StartAt
		relativeEnd := chunk.EndAt - original.StartAt
		if string(parentRunes[relativeStart:relativeEnd]) != chunk.Content {
			return nil, false
		}

		occurrenceCount := strings.Count(chunk.Content, quote)
		if occurrenceCount > 0 {
			if occurrenceCount != 1 {
				return nil, false
			}
			byteStart := strings.Index(chunk.Content, quote)
			if byteStart < 0 {
				return nil, false
			}
			childAbsoluteStart := chunk.StartAt +
				utf8.RuneCountInString(chunk.Content[:byteStart])
			childAbsoluteEnd := childAbsoluteStart + len(quoteRunes)
			if childAbsoluteStart != absoluteStart || childAbsoluteEnd != absoluteEnd {
				return nil, false
			}
			matchingOccurrences++
			contributionStart := chunk.StartAt
			if frontier > contributionStart {
				contributionStart = frontier
			}
			if absoluteStart >= contributionStart && absoluteEnd <= chunk.EndAt {
				if owner != nil {
					return nil, false
				}
				owner = chunk
			}
		}
		frontier = chunk.EndAt
		previousIndex = chunk.ChunkIndex
		previousStart = chunk.StartAt
	}
	if frontier != original.EndAt || matchingOccurrences == 0 || owner == nil {
		return nil, false
	}
	copy := *owner
	return &copy, true
}

// schemaWikiCitationRevisionReadAdapter verifies every revision fact currently
// available from WeKnora. It deliberately does not open the current-file
// preview: that endpoint is not parse-attempt-bound and therefore cannot
// satisfy CitationRevisionReadPort's immutable-revision promise.
type schemaWikiCitationRevisionReadAdapter struct {
	revisions schemaWikiCitationRevisionRepository
	chunks    schemaWikiCitationChunkRepository
	snapshots schemaWikiImmutableRevisionSnapshotReader
}

// NewSchemaWikiCitationRevisionReadAdapter wires the production repositories
// without widening their long-standing public interfaces. The concrete
// knowledge repository already exposes immutable revision reads; a deployment
// that substitutes an implementation without that capability fails closed.
func NewSchemaWikiCitationRevisionReadAdapter(
	knowledgeRepository interfaces.KnowledgeRepository,
	chunkRepository interfaces.ChunkRepository,
) *schemaWikiCitationRevisionReadAdapter {
	revisions, ok := knowledgeRepository.(schemaWikiCitationRevisionRepository)
	if !ok {
		return &schemaWikiCitationRevisionReadAdapter{}
	}
	return newSchemaWikiCitationRevisionReadAdapter(revisions, chunkRepository)
}

func newSchemaWikiCitationRevisionReadAdapter(
	revisions schemaWikiCitationRevisionRepository,
	chunks schemaWikiCitationChunkRepository,
	snapshots ...schemaWikiImmutableRevisionSnapshotReader,
) *schemaWikiCitationRevisionReadAdapter {
	adapter := &schemaWikiCitationRevisionReadAdapter{revisions: revisions, chunks: chunks}
	if len(snapshots) == 1 {
		adapter.snapshots = snapshots[0]
	}
	return adapter
}

func (a *schemaWikiCitationRevisionReadAdapter) ReadExactRevision(
	ctx context.Context,
	request CitationRevisionReadRequestV1,
) ([]byte, error) {
	if _, err := a.resolveExactRevisionAuthority(ctx, request); err != nil {
		return nil, err
	}
	// The two-phase authority is valid, but this legacy byte-returning port must
	// not collapse authority issuance and token-only fetch into one operation.
	return nil, ErrSchemaWikiCitationUnavailable
}

func (a *schemaWikiCitationRevisionReadAdapter) resolveExactRevisionAuthority(
	ctx context.Context,
	request CitationRevisionReadRequestV1,
) (*SchemaWikiCitationPreviewAuthorityV1, error) {
	activeAuthority := request.ReleaseID != "" && request.ActivationEpoch > 0 &&
		request.PreparationID == "" && request.EvaluationID == "" && request.EvidenceID == ""
	preparationAuthority := request.ReleaseID == "" && request.ActivationEpoch == 0 &&
		request.PreparationID != "" && schemaWikiSHA256(request.EvaluationID) &&
		schemaWikiSHA256(request.EvidenceID)
	if a == nil || a.revisions == nil || a.chunks == nil ||
		(!activeAuthority && !preparationAuthority) ||
		!schemaWikiSHA256(request.CandidateSHA256) || request.FieldID == "" ||
		request.Scope.TenantID == 0 || request.Scope.SpaceID == "" ||
		request.Scope.RawKBID == "" || request.Scope.WikiKBID == "" ||
		types.ValidateCitationTarget(request.Citation) != nil ||
		request.Citation.SpaceID != request.Scope.SpaceID ||
		request.Binding.CitationSHA256 != request.Citation.CitationSHA256 ||
		request.Binding.LogicalMemberRef != request.Citation.LogicalMemberRef {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	tenantID, ok := ctx.Value(types.TenantIDContextKey).(uint64)
	if !ok || tenantID == 0 || tenantID != request.Scope.TenantID {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	attempt, ok := schemaWikiNativeParseAttemptForRequest(request)
	if !ok {
		return nil, ErrSchemaWikiCitationUnavailable
	}

	knowledge, err := a.revisions.GetKnowledgeByID(ctx, tenantID, request.Citation.KnowledgeID)
	if err != nil || knowledge == nil || knowledge.ID != request.Citation.KnowledgeID ||
		knowledge.TenantID != tenantID || knowledge.KnowledgeBaseID != request.Scope.RawKBID ||
		knowledge.ParseStatus != types.ParseStatusCompleted || !strings.EqualFold(knowledge.FileType, "pdf") {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	revision, err := a.revisions.GetRevision(ctx, request.Citation.KnowledgeID, attempt)
	if err != nil || revision == nil || revision.KnowledgeID != request.Citation.KnowledgeID ||
		revision.ParseAttempt != attempt || !schemaWikiSHA256(revision.FileSHA256) ||
		revision.ManifestAlgorithm != types.RevisionManifestAlgorithm ||
		!schemaWikiSHA256(revision.ManifestDigest) || revision.ChunkCount <= 0 {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	if request.frozenNativeSource != nil {
		return a.resolveFrozenC5NativeRevisionAuthority(ctx, request, revision, attempt)
	}
	source, resource, err := a.revisions.GetRevisionSource(
		ctx, tenantID, request.Citation.KnowledgeID, attempt,
	)
	if err != nil || source == nil || resource == nil ||
		source.TenantID != tenantID || source.KnowledgeID != request.Citation.KnowledgeID ||
		source.ParseAttempt != attempt || source.ResourceID != resource.ID ||
		source.FileSHA256 != revision.FileSHA256 || resource.ContentHash != revision.FileSHA256 ||
		source.Size != resource.Size || source.MimeType != resource.MimeType ||
		source.RetentionState != types.KnowledgeRevisionSourcePinned ||
		resource.TenantID != tenantID || resource.State != types.ResourceStateActive ||
		resource.Lifecycle != types.ResourceLifecyclePersistent || resource.Size <= 0 ||
		!strings.EqualFold(resource.MimeType, "application/pdf") {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	if source.PageCount == nil || request.Citation.PageNumber <= 0 ||
		request.Citation.PageNumber > *source.PageCount {
		return nil, ErrSchemaWikiCitationPageUnavailable
	}

	selected, err := a.chunks.GetChunkByID(ctx, tenantID, request.Citation.ChunkID)
	if err != nil || !schemaWikiCitationChunkMatches(
		selected, request.Scope, request.Citation, attempt,
	) {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	all, err := a.chunks.ListChunksByKnowledgeID(ctx, tenantID, request.Citation.KnowledgeID)
	if err != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	manifestRows := make([]types.RevisionManifestChunk, 0, len(all))
	selectedInManifest := false
	for _, chunk := range all {
		if chunk == nil || chunk.ParseAttempt != attempt || chunk.ChunkType != types.ChunkTypeText {
			continue
		}
		if chunk.TenantID != tenantID || chunk.KnowledgeID != request.Citation.KnowledgeID ||
			chunk.KnowledgeBaseID != request.Scope.RawKBID || chunk.ChunkIndex < 0 ||
			chunk.StartAt < 0 || chunk.EndAt < chunk.StartAt {
			return nil, ErrSchemaWikiCitationUnavailable
		}
		manifestRows = append(manifestRows, types.RevisionManifestChunk{
			ID: chunk.ID, Index: chunk.ChunkIndex, Content: chunk.Content,
		})
		if chunk.ID == selected.ID && chunk.ChunkIndex == selected.ChunkIndex &&
			chunk.StartAt == selected.StartAt && chunk.EndAt == selected.EndAt &&
			chunk.Content == selected.Content {
			selectedInManifest = true
		}
	}
	sort.Slice(manifestRows, func(i, j int) bool { return manifestRows[i].Index < manifestRows[j].Index })
	manifestDigest, err := types.ComputeRevisionManifestDigest(
		request.Citation.KnowledgeID, attempt, manifestRows,
	)
	if err != nil || !selectedInManifest || len(manifestRows) != revision.ChunkCount ||
		manifestDigest != revision.ManifestDigest {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	if request.CoordinateAuthorityReceipt == nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	receipt := *request.CoordinateAuthorityReceipt
	if err := validateSchemaWikiCitationCoordinateAuthorityReceipt(
		request, receipt, revision, source, selected,
	); err != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	liveSourceReceipt := types.LiveRevisionSourceReceiptV1{
		Contract:         "live-revision-source-receipt.v1",
		RevisionSourceID: source.RevisionSourceID,
		TenantID:         request.Scope.TenantID, SpaceID: request.Scope.SpaceID,
		RawKBID: request.Scope.RawKBID, WikiKBID: request.Scope.WikiKBID,
		KnowledgeID:            request.Citation.KnowledgeID,
		EvidenceParseAttemptID: receipt.EvidenceParseAttemptID,
		WeKnoraParseAttempt:    revision.ParseAttempt, ResourceID: source.ResourceID,
		FileSHA256: source.FileSHA256, Size: source.Size, MimeType: source.MimeType,
		PageCount: *source.PageCount, ParsedDocumentSHA256: receipt.ParsedDocumentSHA256,
		ParseManifestSHA256:      receipt.ParseManifestSHA256,
		WeKnoraManifestAlgorithm: revision.ManifestAlgorithm,
		WeKnoraManifestDigest:    revision.ManifestDigest,
		WeKnoraChunkCount:        revision.ChunkCount,
	}
	liveSourceReceipt.SourceReceiptSHA256 = receipt.LiveRevisionSourceReceiptSHA256
	snapshotRequest := SchemaWikiImmutableRevisionSnapshotRequestV1{
		Contract:  "schema-wiki-immutable-revision-snapshot-request.v1",
		ReleaseID: request.ReleaseID, ActivationEpoch: request.ActivationEpoch,
		PreparationID: request.PreparationID, EvaluationID: request.EvaluationID,
		EvidenceID: request.EvidenceID,
		Scope:      request.Scope, CandidateSHA256: request.CandidateSHA256,
		LogicalMemberRef: request.Citation.LogicalMemberRef, FieldID: request.FieldID,
		CitationID:     request.Citation.CitationID,
		CitationSHA256: request.Citation.CitationSHA256,
		BindingSHA256:  request.Binding.BindingSHA256,
		KnowledgeID:    request.Citation.KnowledgeID, ParseAttempt: attempt,
		ResourceID: source.ResourceID, FileSHA256: source.FileSHA256,
		Size: source.Size, MimeType: source.MimeType,
		ManifestAlgorithm: revision.ManifestAlgorithm,
		ManifestDigest:    revision.ManifestDigest, ChunkCount: revision.ChunkCount,
		ParsedDocumentSHA256:   request.Citation.ParsedDocumentSHA256,
		EvidenceReceiptSHA256s: append([]string(nil), request.EvidenceReceiptSHA256s...),
		CoordinateReceipt:      receipt,
		LiveSourceReceipt:      liveSourceReceipt,
	}
	var authority *SchemaWikiCitationPreviewAuthorityV1
	if a.snapshots != nil {
		authority, err = a.snapshots.ResolveCitationPreviewAuthority(ctx, snapshotRequest)
	} else {
		authority = schemaWikiCitationAuthorityFromCompanion(snapshotRequest)
	}
	if err != nil || authority == nil ||
		validateSchemaWikiCitationPreviewAuthority(snapshotRequest, *authority) != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}

	return authority, nil
}

func (a *schemaWikiCitationRevisionReadAdapter) resolveFrozenC5NativeRevisionAuthority(
	ctx context.Context,
	request CitationRevisionReadRequestV1,
	revision *types.KnowledgeRevision,
	attempt int64,
) (*SchemaWikiCitationPreviewAuthorityV1, error) {
	frozen := request.frozenNativeSource
	manifest, ok := schemaWikiParseC5NativeSourceManifest(frozen)
	if !ok || manifest.TenantID != request.Scope.TenantID ||
		manifest.KnowledgeBaseID != request.Scope.RawKBID ||
		manifest.KnowledgeID != request.Citation.KnowledgeID ||
		manifest.WeKnoraParseAttempt != attempt || manifest.ResourceID == "" ||
		manifest.ResourcePhysicalPath == "" || manifest.FileName == "" ||
		manifest.MaterialFile != manifest.Role+".pdf" ||
		!schemaWikiSHA256(manifest.CompilerSourceRevisionID) ||
		manifest.ResourceState != "active" || manifest.ResourceBindingCount != 1 ||
		manifest.ParseStatus != "completed" || manifest.ParseCompletedAt == "" ||
		manifest.MimeType != "application/pdf" || manifest.FileSize <= 0 ||
		manifest.PageCount <= 0 || request.Citation.PageNumber <= 0 ||
		request.Citation.PageNumber > manifest.PageCount ||
		manifest.ParseManifestAlgorithm != types.RevisionManifestAlgorithm ||
		manifest.ParseManifestSHA256 != revision.ManifestDigest ||
		manifest.FileSHA256 != revision.FileSHA256 ||
		manifest.ChunkCount != revision.ChunkCount ||
		len(manifest.OrderedChunkProjection) != revision.ChunkCount {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	original, err := a.chunks.GetChunkByID(
		ctx, request.Scope.TenantID, request.Citation.ChunkID,
	)
	if err != nil || !schemaWikiC5OriginalCitationChunkMatches(
		original, request, attempt,
	) {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	all, err := a.chunks.ListChunksByKnowledgeID(
		ctx, request.Scope.TenantID, request.Citation.KnowledgeID,
	)
	if err != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	manifestRows := make([]types.RevisionManifestChunk, 0, len(manifest.OrderedChunkProjection))
	textChunks := make([]*types.Chunk, 0, len(manifest.OrderedChunkProjection))
	originalSeen := 0
	for _, chunk := range all {
		if chunk != nil && chunk.ID == original.ID {
			if !reflect.DeepEqual(*chunk, *original) {
				return nil, ErrSchemaWikiCitationUnavailable
			}
			originalSeen++
		}
		if chunk == nil || chunk.ParseAttempt != attempt || chunk.ChunkType != types.ChunkTypeText {
			continue
		}
		if chunk.TenantID != request.Scope.TenantID ||
			chunk.KnowledgeID != request.Citation.KnowledgeID ||
			chunk.KnowledgeBaseID != request.Scope.RawKBID || chunk.ID == "" ||
			chunk.ChunkIndex < 0 || chunk.StartAt < 0 || chunk.EndAt < chunk.StartAt {
			return nil, ErrSchemaWikiCitationUnavailable
		}
		copy := *chunk
		textChunks = append(textChunks, &copy)
	}
	sort.Slice(textChunks, func(i, j int) bool {
		return textChunks[i].ChunkIndex < textChunks[j].ChunkIndex
	})
	expectedOriginalTextMembership := 0
	if original.ChunkType == types.ChunkTypeText {
		expectedOriginalTextMembership = 1
	}
	if originalSeen != expectedOriginalTextMembership ||
		len(textChunks) != len(manifest.OrderedChunkProjection) {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	var nativeText *types.Chunk
	for index, chunk := range textChunks {
		projection := manifest.OrderedChunkProjection[index]
		if projection.ChunkID != chunk.ID || projection.ChunkIndex != chunk.ChunkIndex ||
			projection.ContentSHA256 != schemaWikiStringSHA256(chunk.Content) {
			return nil, ErrSchemaWikiCitationUnavailable
		}
		manifestRows = append(manifestRows, types.RevisionManifestChunk{
			ID: chunk.ID, Index: chunk.ChunkIndex, Content: chunk.Content,
		})
		if original.ChunkType == types.ChunkTypeText && chunk.ID == original.ID {
			nativeText = chunk
		}
	}
	if original.ChunkType == types.ChunkTypeParentText {
		var ok bool
		nativeText, ok = schemaWikiC5CanonicalTextForParentOccurrence(
			original,
			textChunks,
			request.Citation.QuoteSnapshot,
			request.CoordinateAuthorityReceipt,
		)
		if !ok {
			return nil, ErrSchemaWikiCitationUnavailable
		}
	}
	manifestDigest, err := types.ComputeRevisionManifestDigest(
		request.Citation.KnowledgeID, attempt, manifestRows,
	)
	if err != nil || nativeText == nil || manifestDigest != manifest.ParseManifestSHA256 ||
		manifestDigest != revision.ManifestDigest {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	if request.CoordinateAuthorityReceipt == nil ||
		validateSchemaWikiC5FrozenCoordinateAuthority(
			request, *request.CoordinateAuthorityReceipt, revision, manifest, original,
		) != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	receipt := *request.CoordinateAuthorityReceipt
	snapshotRequest := SchemaWikiImmutableRevisionSnapshotRequestV1{
		Contract:  "schema-wiki-immutable-revision-snapshot-request.v1",
		ReleaseID: request.ReleaseID, ActivationEpoch: request.ActivationEpoch,
		PreparationID: request.PreparationID, EvaluationID: request.EvaluationID,
		EvidenceID: request.EvidenceID, Scope: request.Scope,
		CandidateSHA256:  request.CandidateSHA256,
		LogicalMemberRef: request.Citation.LogicalMemberRef, FieldID: request.FieldID,
		CitationID: request.Citation.CitationID, CitationSHA256: request.Citation.CitationSHA256,
		BindingSHA256: request.Binding.BindingSHA256,
		KnowledgeID:   request.Citation.KnowledgeID, ParseAttempt: attempt,
		ResourceID: manifest.ResourceID, FileSHA256: manifest.FileSHA256,
		Size: manifest.FileSize, MimeType: manifest.MimeType,
		ManifestAlgorithm: manifest.ParseManifestAlgorithm,
		ManifestDigest:    manifest.ParseManifestSHA256, ChunkCount: manifest.ChunkCount,
		ParsedDocumentSHA256:   request.Citation.ParsedDocumentSHA256,
		EvidenceReceiptSHA256s: append([]string(nil), request.EvidenceReceiptSHA256s...),
		CoordinateReceipt:      receipt, LiveSourceReceipt: receipt.LiveRevisionSourceReceipt,
	}
	var authority *SchemaWikiCitationPreviewAuthorityV1
	if a.snapshots != nil {
		authority, err = a.snapshots.ResolveCitationPreviewAuthority(ctx, snapshotRequest)
	} else {
		authority = schemaWikiCitationAuthorityFromCompanion(snapshotRequest)
	}
	if err != nil || authority == nil ||
		validateSchemaWikiCitationPreviewAuthority(snapshotRequest, *authority) != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}
	return authority, nil
}

func schemaWikiParseC5NativeSourceManifest(
	frozen *schemaWikiC5FrozenNativeSource,
) (schemaWikiC5NativeSourceManifest, bool) {
	var manifest schemaWikiC5NativeSourceManifest
	if frozen == nil || frozen.experimentID == "" ||
		!schemaWikiSHA256(frozen.versionIdentity) ||
		!schemaWikiSHA256(frozen.revisionSetSHA256) || frozen.sourceRole == "" ||
		len(frozen.manifest) == 0 || len(frozen.sourceBytes) == 0 {
		return manifest, false
	}
	decoder := json.NewDecoder(bytes.NewReader(frozen.manifest))
	decoder.UseNumber()
	var tree map[string]any
	if decoder.Decode(&tree) != nil || len(tree) != len(schemaWikiC5NativeSourceManifestKeys) {
		return manifest, false
	}
	var trailing any
	if !errorsIsEOF(decoder.Decode(&trailing)) {
		return manifest, false
	}
	for key := range tree {
		if _, ok := schemaWikiC5NativeSourceManifestKeys[key]; !ok {
			return manifest, false
		}
	}
	var canonical bytes.Buffer
	encoder := json.NewEncoder(&canonical)
	encoder.SetEscapeHTML(false)
	typedDecoder := json.NewDecoder(bytes.NewReader(frozen.manifest))
	typedDecoder.UseNumber()
	if encoder.Encode(tree) != nil || !bytes.Equal(canonical.Bytes(), frozen.manifest) ||
		typedDecoder.Decode(&manifest) != nil {
		return schemaWikiC5NativeSourceManifest{}, false
	}
	self, ok := tree["manifest_self_sha256"].(string)
	if !ok || !schemaWikiSHA256(self) {
		return schemaWikiC5NativeSourceManifest{}, false
	}
	delete(tree, "manifest_self_sha256")
	canonical.Reset()
	encoder = json.NewEncoder(&canonical)
	encoder.SetEscapeHTML(false)
	if encoder.Encode(tree) != nil {
		return schemaWikiC5NativeSourceManifest{}, false
	}
	unsigned := bytes.TrimSuffix(canonical.Bytes(), []byte("\n"))
	preimage := append([]byte("weknora.ec.revision-item.v1\x00"), unsigned...)
	digest := sha256.Sum256(preimage)
	if manifest.Contract != "weknora.ec.revision-item.v1" || manifest.Role != frozen.sourceRole ||
		manifest.ManifestSelfSHA256 != hex.EncodeToString(digest[:]) ||
		manifest.FileSHA256 != schemaWikiBytesSHA256(frozen.sourceBytes) ||
		manifest.FileSize != int64(len(frozen.sourceBytes)) ||
		manifest.ChunkCount <= 0 || len(manifest.OrderedChunkProjection) != manifest.ChunkCount ||
		!schemaWikiC5NativeParseIdentityExact(manifest.ParseIdentity) {
		return schemaWikiC5NativeSourceManifest{}, false
	}
	previous := -1
	seen := make(map[string]struct{}, len(manifest.OrderedChunkProjection))
	for _, row := range manifest.OrderedChunkProjection {
		if row.ChunkID == "" || row.ChunkIndex <= previous || !schemaWikiSHA256(row.ContentSHA256) {
			return schemaWikiC5NativeSourceManifest{}, false
		}
		if _, duplicate := seen[row.ChunkID]; duplicate {
			return schemaWikiC5NativeSourceManifest{}, false
		}
		seen[row.ChunkID] = struct{}{}
		previous = row.ChunkIndex
	}
	return manifest, true
}

func schemaWikiC5NativeParseIdentityExact(identity map[string]any) bool {
	if len(identity) != 9 {
		return false
	}
	stringsRequired := []string{
		"app_commit", "app_version", "docreader", "embedding_model_id", "parser_engine",
	}
	for _, key := range stringsRequired {
		value, ok := identity[key].(string)
		if !ok || value == "" {
			return false
		}
	}
	for _, key := range []string{"chunker_config_digest", "separators_digest"} {
		value, ok := identity[key].(string)
		if !ok || !schemaWikiSHA256(value) {
			return false
		}
	}
	for _, key := range []string{"chunk_overlap", "chunk_size"} {
		value, ok := identity[key].(json.Number)
		if !ok {
			return false
		}
		parsed, err := strconv.ParseInt(string(value), 10, 64)
		if err != nil || parsed < 0 || (key == "chunk_size" && parsed == 0) {
			return false
		}
	}
	return true
}

func errorsIsEOF(err error) bool { return err == io.EOF }

func schemaWikiBytesSHA256(value []byte) string {
	digest := sha256.Sum256(value)
	return hex.EncodeToString(digest[:])
}

func schemaWikiC5OriginalCitationChunkMatches(
	chunk *types.Chunk,
	request CitationRevisionReadRequestV1,
	attempt int64,
) bool {
	receipt := request.CoordinateAuthorityReceipt
	if chunk == nil || receipt == nil || !utf8.ValidString(chunk.Content) ||
		!utf8.ValidString(request.Citation.QuoteSnapshot) {
		return false
	}
	contentCodePoints := []rune(chunk.Content)
	if chunk.ID != request.Citation.ChunkID ||
		chunk.ID != receipt.ChunkID || chunk.TenantID != request.Scope.TenantID ||
		chunk.KnowledgeBaseID != request.Scope.RawKBID ||
		chunk.KnowledgeID != request.Citation.KnowledgeID || chunk.ParseAttempt != attempt ||
		(chunk.ChunkType != types.ChunkTypeText && chunk.ChunkType != types.ChunkTypeParentText) ||
		chunk.ChunkIndex != receipt.ChunkIndex || chunk.StartAt < 0 || chunk.EndAt < chunk.StartAt ||
		schemaWikiStringSHA256(chunk.Content) != receipt.ChunkContentSHA256 ||
		receipt.QuoteOccurrenceCount != 1 || receipt.QuoteOccurrenceStart < 0 ||
		receipt.QuoteOccurrenceEnd <= receipt.QuoteOccurrenceStart ||
		receipt.QuoteOccurrenceEnd > len(contentCodePoints) ||
		string(contentCodePoints[receipt.QuoteOccurrenceStart:receipt.QuoteOccurrenceEnd]) !=
			request.Citation.QuoteSnapshot ||
		strings.Count(chunk.Content, request.Citation.QuoteSnapshot) != 1 {
		return false
	}
	return true
}

func validateSchemaWikiC5FrozenCoordinateAuthority(
	request CitationRevisionReadRequestV1,
	receipt SchemaWikiCitationCoordinateAuthorityReceiptV1,
	revision *types.KnowledgeRevision,
	manifest schemaWikiC5NativeSourceManifest,
	original *types.Chunk,
) error {
	live := receipt.LiveRevisionSourceReceipt
	sourceForID := types.KnowledgeRevisionSource{
		TenantID: manifest.TenantID, KnowledgeID: manifest.KnowledgeID,
		ParseAttempt: manifest.WeKnoraParseAttempt, ResourceID: manifest.ResourceID,
		FileSHA256: manifest.FileSHA256, Size: manifest.FileSize, MimeType: manifest.MimeType,
	}
	revisionSourceID, err := types.ComputeKnowledgeRevisionSourceID(sourceForID)
	if err != nil || receipt.Contract != "schema67-citation-authority-join-receipt.v1" ||
		types.ValidateSchema67CitationAuthorityJoinReceiptV1(receipt) != nil ||
		receipt.ReceiptSHA256 != schemaWikiCitationCoordinateAuthorityReceiptSHA256(receipt) ||
		receipt.CandidateSHA256 != request.CandidateSHA256 || receipt.FieldID != request.FieldID ||
		receipt.SourceRole != request.Citation.SourceRole || receipt.SourceRole != manifest.Role ||
		!schemaWikiContainsExact(request.EvidenceReceiptSHA256s, receipt.EvidenceReceiptSHA256) ||
		receipt.SourceSHA256 != manifest.FileSHA256 || receipt.FileSHA256 != manifest.FileSHA256 ||
		receipt.ParsedDocumentSHA256 != request.Citation.ParsedDocumentSHA256 ||
		receipt.ParseManifestSHA256 != request.Citation.ParseManifestSHA256 ||
		receipt.EvidenceParseAttemptID != request.Citation.ParseAttemptID ||
		receipt.LocatorRef != request.Citation.LocatorRef ||
		receipt.PageNumber != request.Citation.PageNumber || receipt.PageNumber <= 0 ||
		receipt.PageNumber > manifest.PageCount || receipt.NativePageIndex+1 != receipt.PageNumber ||
		receipt.LocatorContentSHA256 != request.Citation.ContentSnapshotSHA256 ||
		receipt.QuoteSHA256 != request.Citation.QuoteSHA256 ||
		receipt.CoordinatePolicySHA256 != schemaWikiCoordinatePolicySHA256 ||
		receipt.SourceCoordinateSpace != schemaWikiSourceCoordinateSpace ||
		receipt.TargetCoordinateSpace != schemaWikiTargetCoordinateSpace ||
		receipt.Origin != "top_left" || receipt.PageWidth != 1_000_000 ||
		receipt.PageHeight != 1_000_000 || !schemaWikiRotation(receipt.RotationDegrees) ||
		receipt.NormalizedBBox.CoordinateSystem != schemaWikiTargetCoordinateSpace ||
		receipt.NormalizedBBox.PageWidth != receipt.PageWidth ||
		receipt.NormalizedBBox.PageHeight != receipt.PageHeight ||
		!reflect.DeepEqual(receipt.NormalizedBBox, request.Citation.BBox) ||
		receipt.TenantID != request.Scope.TenantID || receipt.SpaceID != request.Scope.SpaceID ||
		receipt.RawKBID != request.Scope.RawKBID || receipt.KnowledgeID != manifest.KnowledgeID ||
		receipt.WeKnoraParseAttempt != revision.ParseAttempt ||
		receipt.WeKnoraManifestAlgorithm != manifest.ParseManifestAlgorithm ||
		receipt.WeKnoraManifestDigest != manifest.ManifestSelfSHA256 ||
		receipt.ChunkID != original.ID || receipt.ChunkIndex != original.ChunkIndex ||
		!schemaWikiSHA256(receipt.CaptureIdentitySHA256) ||
		!schemaWikiSHA256(receipt.RawStructureSHA256) ||
		!schemaWikiSHA256(receipt.SanitizedStructureSHA256) ||
		!schemaWikiSHA256(receipt.ParserIdentitySHA256) ||
		!schemaWikiSHA256(receipt.JoinPolicySHA256) ||
		!schemaWikiSHA256(receipt.LiveRevisionSourceReceiptSHA256) ||
		types.ValidateLiveRevisionSourceReceiptV1(live) != nil ||
		live.SourceReceiptSHA256 != receipt.LiveRevisionSourceReceiptSHA256 ||
		live.RevisionSourceID != manifest.CompilerSourceRevisionID ||
		live.RevisionSourceID != revisionSourceID || live.TenantID != manifest.TenantID ||
		live.SpaceID != request.Scope.SpaceID || live.RawKBID != manifest.KnowledgeBaseID ||
		live.WikiKBID != request.Scope.WikiKBID || live.KnowledgeID != manifest.KnowledgeID ||
		live.EvidenceParseAttemptID != receipt.EvidenceParseAttemptID ||
		live.WeKnoraParseAttempt != manifest.WeKnoraParseAttempt ||
		live.ResourceID != manifest.ResourceID || live.FileSHA256 != manifest.FileSHA256 ||
		live.Size != manifest.FileSize || live.MimeType != manifest.MimeType ||
		live.PageCount != manifest.PageCount ||
		live.ParsedDocumentSHA256 != receipt.ParsedDocumentSHA256 ||
		live.ParseManifestSHA256 != receipt.ParseManifestSHA256 ||
		live.WeKnoraManifestAlgorithm != manifest.ParseManifestAlgorithm ||
		live.WeKnoraManifestDigest != manifest.ManifestSelfSHA256 ||
		live.WeKnoraChunkCount != manifest.ChunkCount ||
		!schemaWikiScaledBBoxMatches(receipt.SourceBBoxPreimage, receipt.NormalizedBBox) ||
		!schemaWikiLocatorPrecision(receipt.LocatorKind, receipt.HighlightPrecision) {
		return ErrSchemaWikiCitationUnavailable
	}
	return nil
}

func schemaWikiCitationAuthorityFromCompanion(
	request SchemaWikiImmutableRevisionSnapshotRequestV1,
) *SchemaWikiCitationPreviewAuthorityV1 {
	receipt := request.CoordinateReceipt
	authority := &SchemaWikiCitationPreviewAuthorityV1{
		Contract: "schema-wiki-citation-preview-authority.v1", Request: request,
		FieldID: request.FieldID, ChunkID: receipt.ChunkID, LocatorRef: receipt.LocatorRef,
		PageNumber: receipt.PageNumber, BBox: receipt.NormalizedBBox,
		CoordinateSpaceVersion: receipt.TargetCoordinateSpace,
		PageWidth:              receipt.PageWidth, PageHeight: receipt.PageHeight,
		RotationDegrees: receipt.RotationDegrees, QuoteSHA256: receipt.QuoteSHA256,
		ContentSnapshotSHA256:  receipt.LocatorContentSHA256,
		EvidenceReceiptSHA256s: append([]string(nil), request.EvidenceReceiptSHA256s...),
		// This intermediate value never leaves the server. The public bearer
		// token is issued separately by the deployment-owned Ed25519 ring.
		OpaqueToken: receipt.ReceiptSHA256,
	}
	authority.AuthoritySHA256 = schemaWikiCitationPreviewAuthoritySHA256(*authority)
	return authority
}

func schemaWikiNativeParseAttempt(citation types.CitationTargetV1) (int64, bool) {
	const attemptPrefix = "attempt-"
	const revisionPrefix = "revision-"
	if !strings.HasPrefix(citation.ParseAttemptID, attemptPrefix) ||
		!strings.HasPrefix(citation.SourceRevisionID, revisionPrefix) {
		return 0, false
	}
	attemptText := strings.TrimPrefix(citation.ParseAttemptID, attemptPrefix)
	revisionText := strings.TrimPrefix(citation.SourceRevisionID, revisionPrefix)
	attempt, err := strconv.ParseInt(attemptText, 10, 64)
	if err != nil || attempt <= 0 || attemptText != strconv.FormatInt(attempt, 10) ||
		revisionText != strconv.FormatInt(attempt, 10) {
		return 0, false
	}
	return attempt, true
}

func schemaWikiNativeParseAttemptForRequest(
	request CitationRevisionReadRequestV1,
) (int64, bool) {
	receipt := request.CoordinateAuthorityReceipt
	if receipt == nil || len(receipt.ReceiptSHA256) < 24 ||
		request.Citation.CitationID != "citation-"+receipt.ReceiptSHA256[:24] {
		return schemaWikiNativeParseAttempt(request.Citation)
	}
	if types.ValidateSchema67CitationAuthorityJoinReceiptV1(*receipt) != nil ||
		receipt.CandidateSHA256 != request.CandidateSHA256 ||
		receipt.FieldID != request.FieldID ||
		receipt.SourceRole != request.Citation.SourceRole ||
		receipt.SpaceID != request.Citation.SpaceID ||
		receipt.KnowledgeID != request.Citation.KnowledgeID ||
		receipt.ChunkID != request.Citation.ChunkID ||
		receipt.EvidenceParseAttemptID != request.Citation.ParseAttemptID ||
		receipt.LiveRevisionSourceReceipt.RevisionSourceID != request.Citation.SourceRevisionID ||
		receipt.WeKnoraParseAttempt != receipt.LiveRevisionSourceReceipt.WeKnoraParseAttempt {
		return 0, false
	}
	native := request.Citation
	attempt := strconv.FormatInt(receipt.LiveRevisionSourceReceipt.WeKnoraParseAttempt, 10)
	native.ParseAttemptID = "attempt-" + attempt
	native.SourceRevisionID = "revision-" + attempt
	return schemaWikiNativeParseAttempt(native)
}

func schemaWikiCitationChunkMatches(
	chunk *types.Chunk,
	scope types.WikiReleaseScope,
	citation types.CitationTargetV1,
	attempt int64,
) bool {
	if chunk == nil || chunk.ID != citation.ChunkID || chunk.TenantID != scope.TenantID ||
		chunk.KnowledgeBaseID != scope.RawKBID || chunk.KnowledgeID != citation.KnowledgeID ||
		chunk.ParseAttempt != attempt || chunk.ChunkType != types.ChunkTypeText ||
		chunk.ChunkIndex < 0 || chunk.StartAt < 0 || chunk.EndAt < chunk.StartAt ||
		!strings.Contains(chunk.Content, citation.QuoteSnapshot) {
		return false
	}
	// ContentSnapshotSHA256 belongs to the exact ParsedDocument locator, not
	// the whole WeKnora chunk. The coordinate receipt separately binds that
	// locator digest while ChunkContentSHA256 binds this native chunk.
	return true
}
