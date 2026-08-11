package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"math/big"
	"reflect"
	"sort"
	"strconv"
	"strings"

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

// SchemaWikiCitationCoordinateAuthorityReceiptV1 is the server-replay input
// required before a Candidate citation may become a fixed-revision preview.
// Its digest is not authority by itself: the code-owned snapshot reader must
// resolve and join it to native revision/source/chunk state.
type SchemaWikiCitationCoordinateAuthorityReceiptV1 = types.Schema67CitationAuthorityJoinReceiptV1

type SchemaWikiImmutableRevisionSnapshotRequestV1 struct {
	Contract               string                                         `json:"contract"`
	ReleaseID              string                                         `json:"release_id"`
	ActivationEpoch        uint64                                         `json:"activation_epoch"`
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
) CitationRevisionReadPort {
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
) CitationRevisionReadPort {
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
	if a == nil || a.revisions == nil || a.chunks == nil ||
		request.ReleaseID == "" || request.ActivationEpoch == 0 ||
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
	attempt, ok := schemaWikiNativeParseAttempt(request.Citation)
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
	if request.CoordinateAuthorityReceipt == nil || a.snapshots == nil {
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
		Scope: request.Scope, CandidateSHA256: request.CandidateSHA256,
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
	authority, err := a.snapshots.ResolveCitationPreviewAuthority(ctx, snapshotRequest)
	if err != nil || authority == nil ||
		validateSchemaWikiCitationPreviewAuthority(snapshotRequest, *authority) != nil {
		return nil, ErrSchemaWikiCitationUnavailable
	}

	// The two-phase authority is valid, but this legacy byte-returning port must
	// not collapse authority issuance and token-only fetch into one operation.
	// The HTTP authority/token route is intentionally not mounted in this stage.
	return nil, ErrSchemaWikiCitationUnavailable
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
