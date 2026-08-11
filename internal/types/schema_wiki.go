package types

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"reflect"
	"sort"
	"strings"

	"golang.org/x/text/unicode/norm"
)

const schemaWikiHashPrefix = "schema-wiki-canonical.v1\x00"

const (
	Schema67CoordinatePolicySHA256 = "fd86399f644e6703e847686080f42799dca5376cdfb96e04fd49e6fa3b97c9ae"
	Schema67JoinPolicySHA256       = "61148fd29425c09c8e013e6d271531ee8d8a8553dac80e6ca68ae297b4e99314"
)

var ErrSchemaWikiContractInvalid = errors.New("schema wiki contract invalid")

type KnowledgeDomainV1 struct {
	Contract     string `json:"contract"`
	DomainID     string `json:"domain_id"`
	DisplayName  string `json:"display_name"`
	DomainSHA256 string `json:"domain_sha256"`
}

type TaxonomyNodeV1 struct {
	NodeID         string  `json:"node_id"`
	ParentNodeID   *string `json:"parent_node_id"`
	NodeKind       string  `json:"node_kind"`
	Slug           string  `json:"slug"`
	StableEntityID *string `json:"stable_entity_id"`
	Position       int     `json:"position"`
}

type TaxonomyRedirectV1 struct {
	FromPath       string `json:"from_path"`
	ToPath         string `json:"to_path"`
	StableEntityID string `json:"stable_entity_id"`
}

type TaxonomySnapshotV1 struct {
	Contract               string               `json:"contract"`
	DomainID               string               `json:"domain_id"`
	TaxonomyVersion        string               `json:"taxonomy_version"`
	PreviousSnapshotSHA256 *string              `json:"previous_snapshot_sha256"`
	Nodes                  []TaxonomyNodeV1     `json:"nodes"`
	Redirects              []TaxonomyRedirectV1 `json:"redirects"`
	TaxonomySHA256         string               `json:"taxonomy_sha256"`
}

type SchemaSectionV1 struct {
	SectionID       string   `json:"section_id"`
	DisplayName     string   `json:"display_name"`
	OrderedFieldIDs []string `json:"ordered_field_ids"`
}

type SchemaPackV1 struct {
	Contract         string            `json:"contract"`
	SchemaPackID     string            `json:"schema_pack_id"`
	SchemaVersion    string            `json:"schema_version"`
	DomainID         string            `json:"domain_id"`
	OrderedFieldIDs  []string          `json:"ordered_field_ids"`
	Sections         []SchemaSectionV1 `json:"sections"`
	SchemaPackSHA256 string            `json:"schema_pack_sha256"`
}

type EntityIdentityV1 struct {
	DomainID string `json:"domain_id"`
	EntityID string `json:"entity_id"`
}

type EntityVersionV1 struct {
	EntityID         string `json:"entity_id"`
	VersionID        string `json:"version_id"`
	ProductVersionID string `json:"product_version_id"`
}

type CitationBBoxV1 struct {
	CoordinateSystem string `json:"coordinate_system"`
	PageWidth        int    `json:"page_width"`
	PageHeight       int    `json:"page_height"`
	X0               int    `json:"x0"`
	Y0               int    `json:"y0"`
	X1               int    `json:"x1"`
	Y1               int    `json:"y1"`
}

type CitationTargetV1 struct {
	Contract              string         `json:"contract"`
	CitationID            string         `json:"citation_id"`
	SourceRole            string         `json:"source_role"`
	SpaceID               string         `json:"space_id"`
	EntityVersionID       string         `json:"entity_version_id"`
	KnowledgeID           string         `json:"knowledge_id"`
	ChunkID               string         `json:"chunk_id"`
	SourceRevisionID      string         `json:"source_revision_id"`
	ParseAttemptID        string         `json:"parse_attempt_id"`
	ParsedDocumentSHA256  string         `json:"parsed_document_sha256"`
	ParseManifestSHA256   string         `json:"parse_manifest_sha256"`
	PageNumber            int            `json:"page_number"`
	LocatorRef            string         `json:"locator_ref"`
	BBox                  CitationBBoxV1 `json:"bbox"`
	QuoteSnapshot         string         `json:"quote_snapshot"`
	QuoteSHA256           string         `json:"quote_sha256"`
	ContentSnapshotSHA256 string         `json:"content_snapshot_sha256"`
	LogicalMemberRef      string         `json:"logical_member_ref"`
	CitationSHA256        string         `json:"citation_sha256"`
}

// Schema67CitationAuthorityJoinReceiptV1 is the closed cross-language
// companion receipt that joins Candidate Evidence, captured ParsedDocument
// coordinates and one live immutable WeKnora revision source. It is not
// authority merely because its self-hash is valid; serving code must replay
// every field against code-owned source/capture repositories.
type Schema67CitationAuthorityJoinReceiptV1 struct {
	Contract                        string                      `json:"contract"`
	CandidateSHA256                 string                      `json:"candidate_sha256"`
	FieldID                         string                      `json:"field_id"`
	SourceRole                      string                      `json:"source_role"`
	EvidenceReceiptSHA256           string                      `json:"evidence_receipt_sha256"`
	SourceSHA256                    string                      `json:"source_sha256"`
	ParsedDocumentSHA256            string                      `json:"parsed_document_sha256"`
	ParseManifestSHA256             string                      `json:"parse_manifest_sha256"`
	EvidenceParseAttemptID          string                      `json:"evidence_parse_attempt_id"`
	LocatorKind                     string                      `json:"locator_kind"`
	LocatorRef                      string                      `json:"locator_ref"`
	NativePageIndex                 int                         `json:"native_page_index"`
	PageNumber                      int                         `json:"page_number"`
	LocatorContentSHA256            string                      `json:"locator_content_sha256"`
	QuoteSHA256                     string                      `json:"quote_sha256"`
	CaptureIdentitySHA256           string                      `json:"capture_identity_sha256"`
	RawStructureSHA256              string                      `json:"raw_structure_sha256"`
	SanitizedStructureSHA256        string                      `json:"sanitized_structure_sha256"`
	ParserIdentitySHA256            string                      `json:"parser_identity_sha256"`
	CoordinatePolicySHA256          string                      `json:"coordinate_policy_sha256"`
	SourceCoordinateSpace           string                      `json:"source_coordinate_space"`
	TargetCoordinateSpace           string                      `json:"target_coordinate_space"`
	Origin                          string                      `json:"origin"`
	SourceBBoxPreimage              [4]string                   `json:"source_bbox_preimage"`
	NormalizedBBox                  CitationBBoxV1              `json:"normalized_bbox"`
	PageWidth                       int                         `json:"page_width"`
	PageHeight                      int                         `json:"page_height"`
	RotationDegrees                 int                         `json:"rotation_degrees"`
	HighlightPrecision              string                      `json:"highlight_precision"`
	TenantID                        uint64                      `json:"tenant_id"`
	SpaceID                         string                      `json:"space_id"`
	RawKBID                         string                      `json:"raw_kb_id"`
	KnowledgeID                     string                      `json:"knowledge_id"`
	WeKnoraParseAttempt             int64                       `json:"weknora_parse_attempt"`
	FileSHA256                      string                      `json:"file_sha256"`
	WeKnoraManifestAlgorithm        string                      `json:"weknora_manifest_algorithm"`
	WeKnoraManifestDigest           string                      `json:"weknora_manifest_digest"`
	ChunkID                         string                      `json:"chunk_id"`
	ChunkIndex                      int                         `json:"chunk_index"`
	ChunkContentSHA256              string                      `json:"chunk_content_sha256"`
	QuoteOccurrenceStart            int                         `json:"quote_occurrence_start"`
	QuoteOccurrenceEnd              int                         `json:"quote_occurrence_end"`
	QuoteOccurrenceCount            int                         `json:"quote_occurrence_count"`
	JoinPolicySHA256                string                      `json:"join_policy_sha256"`
	LiveRevisionSourceReceipt       LiveRevisionSourceReceiptV1 `json:"live_revision_source_receipt"`
	LiveRevisionSourceReceiptSHA256 string                      `json:"live_revision_source_receipt_sha256"`
	ReceiptSHA256                   string                      `json:"receipt_sha256"`
}

type Schema67LiveSourceAuthorityV1 struct {
	SourceRole                string                      `json:"source_role"`
	SourceSHA256              string                      `json:"source_sha256"`
	LiveRevisionSourceReceipt LiveRevisionSourceReceiptV1 `json:"live_revision_source_receipt"`
}

// Schema67CandidateEvidenceAuthorityV1 is the complete Candidate-bound
// companion persisted with a Schema Wiki release. The outer hash is only an
// integrity checksum; validation also replays every nested source/join receipt
// and requires an exact bijection with the release citations.
type Schema67CandidateEvidenceAuthorityV1 struct {
	Contract               string                                   `json:"contract"`
	CandidateSHA256        string                                   `json:"candidate_sha256"`
	CoordinatePolicySHA256 string                                   `json:"coordinate_policy_sha256"`
	JoinPolicySHA256       string                                   `json:"join_policy_sha256"`
	SourceAuthorities      []Schema67LiveSourceAuthorityV1          `json:"source_authorities"`
	JoinReceipts           []Schema67CitationAuthorityJoinReceiptV1 `json:"join_receipts"`
	AuthoritySHA256        string                                   `json:"authority_sha256"`
}

// SchemaWikiCitationContentAuthorityV1 is the closed, public half of the
// two-stage fixed-revision citation protocol. OpaqueToken is an independently
// signed capability and is deliberately excluded from AuthoritySHA256; the
// token signer binds this exact authority hash. Fetch reconstructs the full
// replay request from validated release custody, so raw quote text never enters
// the bearer token.
type SchemaWikiCitationContentAuthorityV1 struct {
	Contract               string                      `json:"contract"`
	TokenKeyID             string                      `json:"token_key_id"`
	ReleaseID              string                      `json:"release_id"`
	ActivationEpoch        uint64                      `json:"activation_epoch"`
	CandidateSHA256        string                      `json:"candidate_sha256"`
	FieldID                string                      `json:"field_id"`
	CitationID             string                      `json:"citation_id"`
	RevisionSource         LiveRevisionSourceReceiptV1 `json:"revision_source"`
	CitationSHA256         string                      `json:"citation_sha256"`
	BindingSHA256          string                      `json:"binding_sha256"`
	PageNumber             int                         `json:"page_number"`
	BBox                   CitationBBoxV1              `json:"bbox"`
	QuoteSHA256            string                      `json:"quote_sha256"`
	ContentSnapshotSHA256  string                      `json:"content_snapshot_sha256"`
	CoordinateSpaceVersion string                      `json:"coordinate_space_version"`
	PageWidth              int                         `json:"page_width"`
	PageHeight             int                         `json:"page_height"`
	RotationDegrees        int                         `json:"rotation_degrees"`
	RetentionState         string                      `json:"retention_state"`
	ExpiresAtUnix          int64                       `json:"expires_at_unix"`
	AuthoritySHA256        string                      `json:"authority_sha256"`
	OpaqueToken            string                      `json:"opaque_token"`
}

// ComputeSchemaWikiCitationContentAuthoritySHA256 freezes the public
// authority independently of the bearer token bytes.
func ComputeSchemaWikiCitationContentAuthoritySHA256(
	authority SchemaWikiCitationContentAuthorityV1,
) (string, error) {
	if authority.Contract != "schema-wiki-citation-content-authority.v1" {
		return "", ErrSchemaWikiContractInvalid
	}
	authority.OpaqueToken = ""
	digest, _, err := schemaWikiHashWithout(
		authority.Contract, authority, "authority_sha256",
	)
	return digest, err
}

// ValidateSchemaWikiCitationContentAuthorityV1 validates every public
// preimage. It never treats the token or a caller-recomputed outer hash as
// authority for the embedded revision or citation.
func ValidateSchemaWikiCitationContentAuthorityV1(
	authority SchemaWikiCitationContentAuthorityV1,
) error {
	if authority.Contract != "schema-wiki-citation-content-authority.v1" ||
		authority.TokenKeyID == "" || authority.ReleaseID == "" ||
		authority.ActivationEpoch == 0 || authority.FieldID == "" ||
		authority.CitationID == "" || authority.ExpiresAtUnix <= 0 ||
		authority.RetentionState != KnowledgeRevisionSourcePinned ||
		authority.CoordinateSpaceVersion != "normalized_0_1e6" ||
		authority.PageWidth != 1_000_000 || authority.PageHeight != 1_000_000 ||
		(authority.RotationDegrees != 0 && authority.RotationDegrees != 90 &&
			authority.RotationDegrees != 180 && authority.RotationDegrees != 270) ||
		ValidateLiveRevisionSourceReceiptV1(authority.RevisionSource) != nil ||
		!validSchemaWikiSHA256(authority.CandidateSHA256) ||
		!validSchemaWikiSHA256(authority.CitationSHA256) ||
		!validSchemaWikiSHA256(authority.BindingSHA256) ||
		!validSchemaWikiSHA256(authority.QuoteSHA256) ||
		!validSchemaWikiSHA256(authority.ContentSnapshotSHA256) ||
		authority.PageNumber <= 0 || authority.PageNumber > authority.RevisionSource.PageCount ||
		authority.BBox.CoordinateSystem != authority.CoordinateSpaceVersion ||
		authority.BBox.PageWidth != authority.PageWidth ||
		authority.BBox.PageHeight != authority.PageHeight || authority.BBox.X0 < 0 ||
		authority.BBox.Y0 < 0 || authority.BBox.X0 >= authority.BBox.X1 ||
		authority.BBox.Y0 >= authority.BBox.Y1 || authority.BBox.X1 > authority.PageWidth ||
		authority.BBox.Y1 > authority.PageHeight {
		return ErrSchemaWikiContractInvalid
	}
	digest, err := ComputeSchemaWikiCitationContentAuthoritySHA256(authority)
	if err != nil || digest != authority.AuthoritySHA256 {
		return ErrSchemaWikiContractInvalid
	}
	return nil
}

// ValidateSchemaWikiCitationContentAuthorityAgainst rejects a fully rehashed
// caller substitution by comparing the complete canonical public authority.
func ValidateSchemaWikiCitationContentAuthorityAgainst(
	presented SchemaWikiCitationContentAuthorityV1,
	trusted SchemaWikiCitationContentAuthorityV1,
) error {
	if ValidateSchemaWikiCitationContentAuthorityV1(presented) != nil ||
		ValidateSchemaWikiCitationContentAuthorityV1(trusted) != nil {
		return ErrSchemaWikiContractInvalid
	}
	presentedBytes, err := schemaWikiCanonicalJSON(presented)
	if err != nil {
		return ErrSchemaWikiContractInvalid
	}
	trustedBytes, err := schemaWikiCanonicalJSON(trusted)
	if err != nil || !bytes.Equal(presentedBytes, trustedBytes) {
		return ErrSchemaWikiContractInvalid
	}
	return nil
}

// ComputeSchema67CitationAuthorityJoinReceiptSHA256 freezes the same
// schema-wiki canonical JSON equation used by the other cross-language DTOs.
func ComputeSchema67CitationAuthorityJoinReceiptSHA256(
	receipt Schema67CitationAuthorityJoinReceiptV1,
) (string, error) {
	if receipt.Contract != "schema67-citation-authority-join-receipt.v1" {
		return "", ErrSchemaWikiContractInvalid
	}
	digest, _, err := schemaWikiHashWithout(receipt.Contract, receipt, "receipt_sha256")
	return digest, err
}

func schema67ScaledBBoxMatches(source [4]string, normalized CitationBBoxV1) bool {
	expected := [4]int{normalized.X0, normalized.Y0, normalized.X1, normalized.Y1}
	for index, value := range source {
		rational, ok := new(big.Rat).SetString(value)
		if !ok || rational.Sign() < 0 || rational.Cmp(big.NewRat(1000, 1)) > 0 {
			return false
		}
		rational.Mul(rational, big.NewRat(1000, 1))
		if !rational.IsInt() || !rational.Num().IsInt64() ||
			int(rational.Num().Int64()) != expected[index] {
			return false
		}
	}
	return expected[0] < expected[2] && expected[1] < expected[3] &&
		expected[2] <= 1_000_000 && expected[3] <= 1_000_000
}

func schema67LocatorPrecision(kind, precision string) bool {
	switch kind {
	case "block", "table":
		return precision == "locator_exact"
	case "cell":
		return precision == "table_scoped_not_cell_exact_stop"
	default:
		return false
	}
}

func schema67Rotation(rotation int) bool {
	return rotation == 0 || rotation == 90 || rotation == 180 || rotation == 270
}

// ValidateSchema67CitationAuthorityJoinReceiptV1 validates the complete
// language-neutral receipt. A serving adapter must additionally replay its
// live revision/chunk fields against repositories.
func ValidateSchema67CitationAuthorityJoinReceiptV1(
	receipt Schema67CitationAuthorityJoinReceiptV1,
) error {
	digest, err := ComputeSchema67CitationAuthorityJoinReceiptSHA256(receipt)
	if err != nil || digest != receipt.ReceiptSHA256 ||
		!validSchemaWikiSHA256(receipt.CandidateSHA256) || receipt.FieldID == "" ||
		receipt.SourceRole == "" || !validSchemaWikiSHA256(receipt.EvidenceReceiptSHA256) ||
		!validSchemaWikiSHA256(receipt.SourceSHA256) ||
		!validSchemaWikiSHA256(receipt.ParsedDocumentSHA256) ||
		!validSchemaWikiSHA256(receipt.ParseManifestSHA256) ||
		receipt.EvidenceParseAttemptID == "" || receipt.LocatorRef == "" ||
		receipt.NativePageIndex < 0 || receipt.NativePageIndex+1 != receipt.PageNumber ||
		!validSchemaWikiSHA256(receipt.LocatorContentSHA256) ||
		!validSchemaWikiSHA256(receipt.QuoteSHA256) ||
		!validSchemaWikiSHA256(receipt.CaptureIdentitySHA256) ||
		!validSchemaWikiSHA256(receipt.RawStructureSHA256) ||
		!validSchemaWikiSHA256(receipt.SanitizedStructureSHA256) ||
		!validSchemaWikiSHA256(receipt.ParserIdentitySHA256) ||
		receipt.CoordinatePolicySHA256 != Schema67CoordinatePolicySHA256 ||
		receipt.SourceCoordinateSpace != "mineru_content_list_normalized_0_1000_top_left.v1" ||
		receipt.TargetCoordinateSpace != "normalized_0_1e6" || receipt.Origin != "top_left" ||
		receipt.PageWidth != 1_000_000 || receipt.PageHeight != 1_000_000 ||
		!schema67Rotation(receipt.RotationDegrees) ||
		receipt.NormalizedBBox.CoordinateSystem != receipt.TargetCoordinateSpace ||
		receipt.NormalizedBBox.PageWidth != receipt.PageWidth ||
		receipt.NormalizedBBox.PageHeight != receipt.PageHeight ||
		!schema67ScaledBBoxMatches(receipt.SourceBBoxPreimage, receipt.NormalizedBBox) ||
		!schema67LocatorPrecision(receipt.LocatorKind, receipt.HighlightPrecision) ||
		receipt.TenantID == 0 || receipt.SpaceID == "" || receipt.RawKBID == "" ||
		receipt.KnowledgeID == "" || receipt.WeKnoraParseAttempt <= 0 ||
		!validSchemaWikiSHA256(receipt.FileSHA256) ||
		receipt.WeKnoraManifestAlgorithm != RevisionManifestAlgorithm ||
		!validSchemaWikiSHA256(receipt.WeKnoraManifestDigest) || receipt.ChunkID == "" ||
		receipt.ChunkIndex < 0 || !validSchemaWikiSHA256(receipt.ChunkContentSHA256) ||
		receipt.QuoteOccurrenceStart < 0 ||
		receipt.QuoteOccurrenceEnd <= receipt.QuoteOccurrenceStart ||
		receipt.QuoteOccurrenceCount != 1 || receipt.JoinPolicySHA256 != Schema67JoinPolicySHA256 ||
		ValidateLiveRevisionSourceReceiptV1(receipt.LiveRevisionSourceReceipt) != nil ||
		receipt.LiveRevisionSourceReceiptSHA256 != receipt.LiveRevisionSourceReceipt.SourceReceiptSHA256 {
		return ErrSchemaWikiContractInvalid
	}
	live := receipt.LiveRevisionSourceReceipt
	if live.TenantID != receipt.TenantID || live.SpaceID != receipt.SpaceID ||
		live.RawKBID != receipt.RawKBID || live.KnowledgeID != receipt.KnowledgeID ||
		live.EvidenceParseAttemptID != receipt.EvidenceParseAttemptID ||
		live.WeKnoraParseAttempt != receipt.WeKnoraParseAttempt ||
		live.FileSHA256 != receipt.FileSHA256 ||
		live.ParsedDocumentSHA256 != receipt.ParsedDocumentSHA256 ||
		live.ParseManifestSHA256 != receipt.ParseManifestSHA256 ||
		live.WeKnoraManifestAlgorithm != receipt.WeKnoraManifestAlgorithm ||
		live.WeKnoraManifestDigest != receipt.WeKnoraManifestDigest ||
		receipt.PageNumber > live.PageCount {
		return ErrSchemaWikiContractInvalid
	}
	return nil
}

// ComputeSchema67CandidateEvidenceAuthoritySHA256 freezes the exact Python
// companion equation.
func ComputeSchema67CandidateEvidenceAuthoritySHA256(
	authority Schema67CandidateEvidenceAuthorityV1,
) (string, error) {
	if authority.Contract != "schema67-candidate-evidence-authority.v1" {
		return "", ErrSchemaWikiContractInvalid
	}
	digest, _, err := schemaWikiHashWithout(
		authority.Contract, authority, "authority_sha256",
	)
	return digest, err
}

func schema67ReleaseCitations(release KnowledgeWikiReleaseV1) ([]CitationTargetV1, error) {
	citations := make([]CitationTargetV1, 0, len(release.CitationBindings))
	for _, member := range release.Members {
		if member.MemberKind != "field" {
			continue
		}
		var page SchemaFieldPageV1
		if decodeClosedSchemaWikiPayload(member.Payload, &page) != nil ||
			validateSchemaFieldPage(page) != nil {
			return nil, ErrSchemaWikiContractInvalid
		}
		citations = append(citations, page.Citations...)
	}
	return citations, nil
}

// ValidateSchema67CandidateEvidenceAuthorityV1 replays the whole companion
// and proves its ordered join receipts are a bijection with the exact release
// citations. It never accepts a naked authority hash as sufficient custody.
func ValidateSchema67CandidateEvidenceAuthorityV1(
	authority Schema67CandidateEvidenceAuthorityV1,
	release KnowledgeWikiReleaseV1,
) error {
	digest, err := ComputeSchema67CandidateEvidenceAuthoritySHA256(authority)
	if err != nil || digest != authority.AuthoritySHA256 ||
		ValidateKnowledgeWikiRelease(release, release.SchemaPack) != nil ||
		authority.CandidateSHA256 != release.CandidateSHA256 ||
		authority.CoordinatePolicySHA256 != Schema67CoordinatePolicySHA256 ||
		authority.JoinPolicySHA256 != Schema67JoinPolicySHA256 ||
		len(authority.SourceAuthorities) != 3 {
		return ErrSchemaWikiContractInvalid
	}
	expectedRoles := [3]string{"terms", "brochure", "rate_table"}
	sources := make(map[string]Schema67LiveSourceAuthorityV1, len(authority.SourceAuthorities))
	seenRoles := make(map[string]struct{}, len(authority.SourceAuthorities))
	for index, source := range authority.SourceAuthorities {
		live := source.LiveRevisionSourceReceipt
		sourceID, sourceErr := ComputeKnowledgeRevisionSourceID(KnowledgeRevisionSource{
			TenantID: live.TenantID, KnowledgeID: live.KnowledgeID,
			ParseAttempt: live.WeKnoraParseAttempt, ResourceID: live.ResourceID,
			FileSHA256: live.FileSHA256, Size: live.Size, MimeType: live.MimeType,
		})
		if source.SourceRole != expectedRoles[index] || source.SourceSHA256 != live.FileSHA256 ||
			ValidateLiveRevisionSourceReceiptV1(live) != nil || sourceErr != nil ||
			sourceID != live.RevisionSourceID {
			return ErrSchemaWikiContractInvalid
		}
		if _, duplicate := sources[source.SourceSHA256]; duplicate {
			return ErrSchemaWikiContractInvalid
		}
		if _, duplicate := seenRoles[source.SourceRole]; duplicate {
			return ErrSchemaWikiContractInvalid
		}
		sources[source.SourceSHA256] = source
		seenRoles[source.SourceRole] = struct{}{}
	}
	citations, err := schema67ReleaseCitations(release)
	if err != nil || len(citations) != len(authority.JoinReceipts) {
		return ErrSchemaWikiContractInvalid
	}
	seenReceipts := make(map[string]struct{}, len(authority.JoinReceipts))
	for index, receipt := range authority.JoinReceipts {
		citation := citations[index]
		source, exists := sources[receipt.SourceSHA256]
		if !exists || ValidateSchema67CitationAuthorityJoinReceiptV1(receipt) != nil ||
			receipt.CandidateSHA256 != authority.CandidateSHA256 ||
			receipt.CoordinatePolicySHA256 != authority.CoordinatePolicySHA256 ||
			receipt.JoinPolicySHA256 != authority.JoinPolicySHA256 ||
			receipt.SourceRole != source.SourceRole ||
			!reflect.DeepEqual(receipt.LiveRevisionSourceReceipt, source.LiveRevisionSourceReceipt) ||
			citation.CitationID != "citation-"+receipt.ReceiptSHA256[:24] ||
			citation.SourceRole != receipt.SourceRole || citation.SpaceID != receipt.SpaceID ||
			citation.KnowledgeID != receipt.KnowledgeID || citation.ChunkID != receipt.ChunkID ||
			citation.ParseAttemptID != receipt.EvidenceParseAttemptID ||
			citation.ParsedDocumentSHA256 != receipt.ParsedDocumentSHA256 ||
			citation.ParseManifestSHA256 != receipt.ParseManifestSHA256 ||
			citation.PageNumber != receipt.PageNumber || citation.LocatorRef != receipt.LocatorRef ||
			!reflect.DeepEqual(citation.BBox, receipt.NormalizedBBox) ||
			citation.QuoteSHA256 != receipt.QuoteSHA256 ||
			citation.ContentSnapshotSHA256 != receipt.LocatorContentSHA256 ||
			citation.LogicalMemberRef != "field:"+receipt.FieldID {
			return ErrSchemaWikiContractInvalid
		}
		if _, duplicate := seenReceipts[receipt.ReceiptSHA256]; duplicate {
			return ErrSchemaWikiContractInvalid
		}
		seenReceipts[receipt.ReceiptSHA256] = struct{}{}
	}
	return nil
}

type SchemaFieldPageV1 struct {
	Contract               string             `json:"contract"`
	FieldID                string             `json:"field_id"`
	State                  string             `json:"state"`
	ValueSnapshot          *string            `json:"value_snapshot"`
	Citations              []CitationTargetV1 `json:"citations"`
	EvidenceReceiptSHA256s []string           `json:"evidence_receipt_sha256s"`
	ReviewItemReason       *string            `json:"review_item_reason"`
	FieldPageSHA256        string             `json:"field_page_sha256"`
}

type SchemaRootPageV1 struct {
	Contract           string   `json:"contract"`
	DomainID           string   `json:"domain_id"`
	DomainSHA256       string   `json:"domain_sha256"`
	SchemaPackID       string   `json:"schema_pack_id"`
	SchemaVersion      string   `json:"schema_version"`
	SchemaPackSHA256   string   `json:"schema_pack_sha256"`
	EntityID           string   `json:"entity_id"`
	EntityVersionID    string   `json:"entity_version_id"`
	ProductVersionID   string   `json:"product_version_id"`
	TaxonomyVersion    string   `json:"taxonomy_version"`
	TaxonomySHA256     string   `json:"taxonomy_sha256"`
	ProductDisplayName string   `json:"product_display_name"`
	OrderedSectionIDs  []string `json:"ordered_section_ids"`
	RootPageSHA256     string   `json:"root_page_sha256"`
}

type SchemaSectionPageV1 struct {
	Contract          string   `json:"contract"`
	DomainID          string   `json:"domain_id"`
	DomainSHA256      string   `json:"domain_sha256"`
	SchemaPackID      string   `json:"schema_pack_id"`
	SchemaVersion     string   `json:"schema_version"`
	SchemaPackSHA256  string   `json:"schema_pack_sha256"`
	EntityID          string   `json:"entity_id"`
	EntityVersionID   string   `json:"entity_version_id"`
	ProductVersionID  string   `json:"product_version_id"`
	TaxonomyVersion   string   `json:"taxonomy_version"`
	TaxonomySHA256    string   `json:"taxonomy_sha256"`
	SectionID         string   `json:"section_id"`
	DisplayName       string   `json:"display_name"`
	OrderedFieldIDs   []string `json:"ordered_field_ids"`
	SectionPageSHA256 string   `json:"section_page_sha256"`
}

type SchemaWikiMemberV1 struct {
	Contract      string          `json:"contract"`
	MemberRef     string          `json:"member_ref"`
	MemberKind    string          `json:"member_kind"`
	SectionID     *string         `json:"section_id"`
	FieldID       *string         `json:"field_id"`
	Payload       json.RawMessage `json:"payload"`
	PayloadSHA256 string          `json:"payload_sha256"`
	MemberDigest  string          `json:"member_digest"`
}

type CitationMemberBindingV1 struct {
	Contract         string `json:"contract"`
	CitationSHA256   string `json:"citation_sha256"`
	LogicalMemberRef string `json:"logical_member_ref"`
	MemberDigest     string `json:"member_digest"`
	BindingSHA256    string `json:"binding_sha256"`
}

type KnowledgeWikiReleaseV1 struct {
	Contract           string                    `json:"contract"`
	ReleaseState       string                    `json:"release_state"`
	Domain             KnowledgeDomainV1         `json:"domain"`
	Taxonomy           TaxonomySnapshotV1        `json:"taxonomy"`
	SchemaPack         SchemaPackV1              `json:"schema_pack"`
	Entity             EntityIdentityV1          `json:"entity"`
	EntityVersion      EntityVersionV1           `json:"entity_version"`
	CandidateSHA256    string                    `json:"candidate_sha256"`
	ReviewPolicySHA256 string                    `json:"review_policy_sha256"`
	Members            []SchemaWikiMemberV1      `json:"members"`
	CitationBindings   []CitationMemberBindingV1 `json:"citation_bindings"`
	ManifestDigest     string                    `json:"manifest_digest"`
	ReleaseSHA256      string                    `json:"release_sha256"`
}

const (
	schema67GoldenEvaluatorIdentitySHA256 = "525f208a404d996caf5f806a9b065ea5af81f0b7d2996b9b50c25e4878400808"
	schema67GoldenMetricPolicySHA256      = "5d2ffd2379f9f1902a0ab834de6e1e8e593d400115878b9c565331b121d6f0d7"
)

type Schema67GoldenQualityGateReceiptV1 struct {
	Contract                         string   `json:"contract"`
	Status                           string   `json:"status"`
	ProductVersionID                 string   `json:"product_version_id"`
	CandidateSHA256                  string   `json:"candidate_sha256"`
	CandidateEvidenceAuthoritySHA256 string   `json:"candidate_evidence_authority_sha256"`
	GoldenSetSHA256                  string   `json:"golden_set_sha256"`
	GoldenVersion                    string   `json:"golden_version"`
	EvaluatorIdentitySHA256          string   `json:"evaluator_identity_sha256"`
	MetricPolicySHA256               string   `json:"metric_policy_sha256"`
	OrderedFieldDecisionSHA256s      []string `json:"ordered_field_decision_sha256s"`
	MetricReceiptSHA256s             []string `json:"metric_receipt_sha256s"`
	PrivateDossierSHA256             string   `json:"private_dossier_sha256"`
	PublicAggregateSHA256            string   `json:"public_aggregate_sha256"`
	GoldenApprovalSHA256s            []string `json:"golden_approval_sha256s"`
	WholeBatchApprovalReceiptSHA256  string   `json:"whole_batch_approval_receipt_sha256"`
	SignerKeyID                      string   `json:"signer_key_id"`
	Signature                        string   `json:"signature"`
	ReceiptSHA256                    string   `json:"receipt_sha256"`
}

type Schema67GoldenFieldDecisionV1 struct {
	FieldID                  string `json:"field_id"`
	GoldenFieldSHA256        string `json:"golden_field_sha256"`
	CandidateState           string `json:"candidate_state"`
	GoldenState              string `json:"golden_state"`
	StateCorrect             bool   `json:"state_correct"`
	ValueCorrect             bool   `json:"value_correct"`
	AtomTruePositive         int    `json:"atom_true_positive"`
	AtomFalsePositive        int    `json:"atom_false_positive"`
	AtomFalseNegative        int    `json:"atom_false_negative"`
	AtomF1PPM                int    `json:"atom_f1_ppm"`
	EvidenceFragments        int    `json:"evidence_fragments"`
	EvidenceFragmentsMatched int    `json:"evidence_fragments_matched"`
	BBoxRequired             int    `json:"bbox_required"`
	BBoxPassed               int    `json:"bbox_passed"`
	BBoxIOUPPMValues         []int  `json:"bbox_iou_ppm_values"`
	HighRiskPass             bool   `json:"high_risk_pass"`
	ConflictResolved         bool   `json:"conflict_resolved"`
	DecisionSHA256           string `json:"decision_sha256"`
}

type Schema67GoldenMetricV1 struct {
	MetricID        string `json:"metric_id"`
	Numerator       *int   `json:"numerator"`
	Denominator     *int   `json:"denominator"`
	ValuePPM        *int   `json:"value_ppm"`
	Supports        []int  `json:"supports"`
	Evaluability    string `json:"evaluability"`
	SampleSize      string `json:"sample_size"`
	WilsonLowPPM    *int   `json:"wilson_low_ppm"`
	WilsonHighPPM   *int   `json:"wilson_high_ppm"`
	AdmissionStatus string `json:"admission_status"`
	MetricSHA256    string `json:"metric_sha256"`
}

type Schema67GoldenPrivateDossierV1 struct {
	Contract                         string                          `json:"contract"`
	CandidateSHA256                  string                          `json:"candidate_sha256"`
	CandidateEvidenceAuthoritySHA256 string                          `json:"candidate_evidence_authority_sha256"`
	GoldenSetSHA256                  string                          `json:"golden_set_sha256"`
	FieldDecisions                   []Schema67GoldenFieldDecisionV1 `json:"field_decisions"`
	Metrics                          []Schema67GoldenMetricV1        `json:"metrics"`
	Status                           string                          `json:"status"`
	ReasonCodes                      []string                        `json:"reason_codes"`
	DossierSHA256                    string                          `json:"dossier_sha256"`
}

type Schema67GoldenPublicAggregateV1 struct {
	Contract                string                   `json:"contract"`
	ProductVersionID        string                   `json:"product_version_id"`
	CandidateSHA256         string                   `json:"candidate_sha256"`
	GoldenSetSHA256         string                   `json:"golden_set_sha256"`
	EvaluatorIdentitySHA256 string                   `json:"evaluator_identity_sha256"`
	Metrics                 []Schema67GoldenMetricV1 `json:"metrics"`
	Status                  string                   `json:"status"`
	ReasonCodes             []string                 `json:"reason_codes"`
	AggregateSHA256         string                   `json:"aggregate_sha256"`
}

type Schema67GoldenEvaluationReviewBundleV1 struct {
	Contract               string                             `json:"contract"`
	EvaluationID           string                             `json:"evaluation_id"`
	QualityGateReceipt     Schema67GoldenQualityGateReceiptV1 `json:"quality_gate_receipt"`
	PublicAggregate        Schema67GoldenPublicAggregateV1    `json:"public_aggregate"`
	PrivateDossier         Schema67GoldenPrivateDossierV1     `json:"private_dossier"`
	EvaluationBundleSHA256 string                             `json:"evaluation_bundle_sha256"`
}

type SchemaWikiGoldenQualitySummaryV1 struct {
	Version                  string                          `json:"version"`
	PreparationID            string                          `json:"preparation_id"`
	EvaluationID             string                          `json:"evaluation_id"`
	QualityGateReceiptSHA256 string                          `json:"quality_gate_receipt_sha256"`
	PublicAggregate          Schema67GoldenPublicAggregateV1 `json:"public_aggregate"`
	EvaluationBundleSHA256   string                          `json:"evaluation_bundle_sha256"`
	WikiAdmissionAllowed     bool                            `json:"wiki_admission_allowed"`
	ServingEffect            string                          `json:"serving_effect"`
}

type Schema67GoldenReviewValueV1 struct {
	Mode    string  `json:"mode"`
	Literal *string `json:"literal"`
	SHA256  *string `json:"sha256"`
}

type Schema67GoldenEvidenceChangeV1 struct {
	ChangeKind           string  `json:"change_kind"`
	CandidateEvidenceID  *string `json:"candidate_evidence_id"`
	GoldenEvidenceSHA256 *string `json:"golden_evidence_sha256"`
	ChangeSHA256         string  `json:"change_sha256"`
}

type Schema67GoldenReviewFieldMetadataV1 struct {
	FieldID             string                           `json:"field_id"`
	DecisionSHA256      string                           `json:"decision_sha256"`
	CandidateState      string                           `json:"candidate_state"`
	GoldenState         string                           `json:"golden_state"`
	CandidateValue      Schema67GoldenReviewValueV1      `json:"candidate_value"`
	GoldenValue         Schema67GoldenReviewValueV1      `json:"golden_value"`
	ValueComparison     string                           `json:"value_comparison"`
	EvidenceChanges     []Schema67GoldenEvidenceChangeV1 `json:"evidence_changes"`
	RiskStatus          string                           `json:"risk_status"`
	ConflictStatus      string                           `json:"conflict_status"`
	ReviewStatus        string                           `json:"review_status"`
	ReasonCodes         []string                         `json:"reason_codes"`
	FieldMetadataSHA256 string                           `json:"field_metadata_sha256"`
}

type Schema67GoldenAnnotationLayerV1 struct {
	Contract                string `json:"contract"`
	AnnotatorModelID        string `json:"annotator_model_id"`
	AnnotationReceiptSHA256 string `json:"annotation_receipt_sha256"`
}

type Schema67GoldenHumanReviewLayerV1 struct {
	Contract            string `json:"contract"`
	ReviewedBy          string `json:"reviewed_by"`
	ReviewedAt          string `json:"reviewed_at"`
	ReceiptStatus       string `json:"receipt_status"`
	ReviewReceiptSHA256 string `json:"review_receipt_sha256"`
}

type Schema67GoldenReviewSuccessorMetadataV1 struct {
	Contract                 string                                `json:"contract"`
	AuthorityLevel           string                                `json:"authority_level"`
	CandidateSHA256          string                                `json:"candidate_sha256"`
	GoldenSetSHA256          string                                `json:"golden_set_sha256"`
	QualityGateReceiptSHA256 string                                `json:"quality_gate_receipt_sha256"`
	EvaluationBundleSHA256   string                                `json:"evaluation_bundle_sha256"`
	GoldenVersion            string                                `json:"golden_version"`
	AnnotationLayer          Schema67GoldenAnnotationLayerV1       `json:"annotation_layer"`
	HumanReviewLayer         Schema67GoldenHumanReviewLayerV1      `json:"human_review_layer"`
	OrderedFields            []Schema67GoldenReviewFieldMetadataV1 `json:"ordered_fields"`
	MetadataSHA256           string                                `json:"metadata_sha256"`
}

type SchemaWikiGoldenQualityDossierV2 struct {
	Version                  string                                  `json:"version"`
	PreparationID            string                                  `json:"preparation_id"`
	EvaluationID             string                                  `json:"evaluation_id"`
	QualityGateReceiptSHA256 string                                  `json:"quality_gate_receipt_sha256"`
	PrivateDossier           Schema67GoldenPrivateDossierV1          `json:"private_dossier"`
	ReviewSuccessor          Schema67GoldenReviewSuccessorMetadataV1 `json:"review_successor"`
	EvaluationBundleSHA256   string                                  `json:"evaluation_bundle_sha256"`
	ServingEffect            string                                  `json:"serving_effect"`
}

// SchemaWikiGoldenSuccessorStatusV1 is the closed, non-serving status of the
// current 596-1 reviewed-source closure. It is deliberately separate from
// the formal PASS-only dossier and contains no field values or Evidence.
type SchemaWikiGoldenSuccessorStatusV1 struct {
	Version               string   `json:"version"`
	Contract              string   `json:"contract"`
	TenantID              uint64   `json:"tenant_id"`
	SpaceID               string   `json:"space_id"`
	RawKBID               string   `json:"raw_kb_id"`
	WikiKBID              string   `json:"wiki_kb_id"`
	ProductVersionID      string   `json:"product_version_id"`
	SchemaPackID          string   `json:"schema_pack_id"`
	GoldenSetSHA256       string   `json:"golden_set_sha256"`
	MappingSHA256         string   `json:"mapping_sha256"`
	SuccessorFileSHA256   string   `json:"successor_file_sha256"`
	AttestationSHA256     string   `json:"attestation_sha256"`
	SourceReviewStatus    string   `json:"source_review_status"`
	ReviewedBy            string   `json:"reviewed_by"`
	AnnotatorModelID      string   `json:"annotator_model_id"`
	ReviewedAt            *string  `json:"reviewed_at"`
	AttestorID            string   `json:"attestor_id"`
	AttestedAt            string   `json:"attested_at"`
	Schema67MappingStatus string   `json:"schema67_mapping_status"`
	ClosedCount           int      `json:"closed_count"`
	ResidualCount         int      `json:"residual_count"`
	ResidualFieldIDs      []string `json:"residual_field_ids"`
	GoldenAdmissionStatus string   `json:"golden_admission_status"`
	ReceiptStatus         string   `json:"receipt_status"`
	ReadyToSignStatus     string   `json:"ready_to_sign_status"`
	StatusSHA256          string   `json:"status_sha256"`
}

// SchemaWikiGoldenEvidencePreviewAuthorityV1 is the preparation-pinned,
// hash-only public half of one Golden reviewer Evidence preview. OpaqueToken
// is signed by the existing third citation ring and excluded from the hash.
type SchemaWikiGoldenEvidencePreviewAuthorityV1 struct {
	Contract               string                      `json:"contract"`
	TokenKeyID             string                      `json:"token_key_id"`
	PreparationID          string                      `json:"preparation_id"`
	EvaluationID           string                      `json:"evaluation_id"`
	CandidateSHA256        string                      `json:"candidate_sha256"`
	FieldID                string                      `json:"field_id"`
	EvidenceID             string                      `json:"evidence_id"`
	RevisionSource         LiveRevisionSourceReceiptV1 `json:"revision_source"`
	CitationSHA256         string                      `json:"citation_sha256"`
	BindingSHA256          string                      `json:"binding_sha256"`
	EvidenceReceiptSHA256  string                      `json:"evidence_receipt_sha256"`
	PageNumber             int                         `json:"page_number"`
	BBox                   CitationBBoxV1              `json:"bbox"`
	QuoteSHA256            string                      `json:"quote_sha256"`
	ContentSnapshotSHA256  string                      `json:"content_snapshot_sha256"`
	CoordinateSpaceVersion string                      `json:"coordinate_space_version"`
	PageWidth              int                         `json:"page_width"`
	PageHeight             int                         `json:"page_height"`
	RotationDegrees        int                         `json:"rotation_degrees"`
	RetentionState         string                      `json:"retention_state"`
	ExpiresAtUnix          int64                       `json:"expires_at_unix"`
	AuthoritySHA256        string                      `json:"authority_sha256"`
	OpaqueToken            string                      `json:"opaque_token"`
}

type SchemaWikiReviewBundleV1 struct {
	Contract              string                             `json:"contract"`
	CandidateSHA256       string                             `json:"candidate_sha256"`
	ReleaseSHA256         string                             `json:"release_sha256"`
	ManifestDigest        string                             `json:"manifest_digest"`
	OrderedMemberDigests  []string                           `json:"ordered_member_digests"`
	OrderedBindingSHA256s []string                           `json:"ordered_binding_sha256s"`
	ReviewPolicySHA256    string                             `json:"review_policy_sha256"`
	DomainSHA256          string                             `json:"domain_sha256"`
	TaxonomySHA256        string                             `json:"taxonomy_sha256"`
	SchemaPackSHA256      string                             `json:"schema_pack_sha256"`
	EntityID              string                             `json:"entity_id"`
	VersionID             string                             `json:"version_id"`
	QualityGateReceipt    Schema67GoldenQualityGateReceiptV1 `json:"quality_gate_receipt"`
	ReviewBundleSHA256    string                             `json:"review_bundle_sha256"`
}

type SchemaWikiContractVectorExpectedV1 struct {
	SchemaPackSHA256            string `json:"schema_pack_sha256"`
	TaxonomySHA256              string `json:"taxonomy_sha256"`
	ManifestDigest              string `json:"manifest_digest"`
	ReleaseSHA256               string `json:"release_sha256"`
	CitationSHA256              string `json:"citation_sha256"`
	ReleaseCanonicalPreimageHex string `json:"release_canonical_preimage_hex"`
}

type SchemaWikiContractVectorV1 struct {
	Contract   string                             `json:"contract"`
	SchemaPack SchemaPackV1                       `json:"schema_pack"`
	Release    KnowledgeWikiReleaseV1             `json:"release"`
	Citations  []CitationTargetV1                 `json:"citations"`
	Expected   SchemaWikiContractVectorExpectedV1 `json:"expected"`
}

func schemaWikiCanonicalPreimage(objectType string, payload any) ([]byte, error) {
	if strings.TrimSpace(objectType) == "" || schemaWikiHasControlCharacter(objectType) {
		return nil, fmt.Errorf("%w: object type", ErrSchemaWikiContractInvalid)
	}
	canonical, err := schemaWikiCanonicalJSON(payload)
	if err != nil {
		return nil, err
	}
	preimage := append([]byte(schemaWikiHashPrefix), []byte(objectType)...)
	preimage = append(preimage, 0)
	preimage = append(preimage, canonical...)
	return preimage, nil
}

func schemaWikiCanonicalJSON(payload any) ([]byte, error) {
	raw, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var tree any
	if err := decoder.Decode(&tree); err != nil {
		return nil, err
	}
	if !schemaWikiCanonicalTreeValid(tree) {
		return nil, fmt.Errorf("%w: non-canonical text", ErrSchemaWikiContractInvalid)
	}
	var encoded bytes.Buffer
	encoder := json.NewEncoder(&encoded)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(tree); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(encoded.Bytes(), []byte("\n")), nil
}

func schemaWikiHasControlCharacter(value string) bool {
	for _, character := range value {
		if character < 0x20 || character == 0x7f {
			return true
		}
	}
	return false
}

func schemaWikiCanonicalTreeValid(value any) bool {
	switch typed := value.(type) {
	case nil, bool, json.Number:
		return true
	case string:
		return norm.NFC.IsNormalString(typed) && !schemaWikiHasControlCharacter(typed)
	case []any:
		for _, item := range typed {
			if !schemaWikiCanonicalTreeValid(item) {
				return false
			}
		}
		return true
	case map[string]any:
		for key, item := range typed {
			if !schemaWikiCanonicalTreeValid(key) || !schemaWikiCanonicalTreeValid(item) {
				return false
			}
		}
		return true
	default:
		return false
	}
}

func schemaWikiSHA256(objectType string, payload any) (string, []byte, error) {
	preimage, err := schemaWikiCanonicalPreimage(objectType, payload)
	if err != nil {
		return "", nil, err
	}
	sum := sha256.Sum256(preimage)
	return hex.EncodeToString(sum[:]), preimage, nil
}

func schemaWikiHashWithout(objectType string, value any, hashKey string) (string, []byte, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return "", nil, err
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var payload map[string]any
	if err := decoder.Decode(&payload); err != nil {
		return "", nil, err
	}
	delete(payload, hashKey)
	return schemaWikiSHA256(objectType, payload)
}

func validSchemaWikiSHA256(value string) bool {
	if len(value) != sha256.Size*2 || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}

func requireSchemaWikiHash(objectType string, value any, hashKey, expected string) error {
	if !validSchemaWikiSHA256(expected) {
		return ErrSchemaWikiContractInvalid
	}
	actual, _, err := schemaWikiHashWithout(objectType, value, hashKey)
	if err != nil || actual != expected {
		return ErrSchemaWikiContractInvalid
	}
	return nil
}

func ValidateCitationTarget(citation CitationTargetV1) error {
	if citation.Contract != "citation-target.v1" || citation.PageNumber <= 0 ||
		citation.CitationID == "" || citation.SourceRole == "" || citation.SpaceID == "" ||
		citation.EntityVersionID == "" || citation.KnowledgeID == "" || citation.ChunkID == "" ||
		citation.SourceRevisionID == "" || citation.ParseAttemptID == "" || citation.LocatorRef == "" ||
		citation.QuoteSnapshot == "" || citation.LogicalMemberRef == "" {
		return ErrSchemaWikiContractInvalid
	}
	box := citation.BBox
	if (box.CoordinateSystem != "pdf_points" && box.CoordinateSystem != "normalized_0_1e6") ||
		box.PageWidth <= 0 || box.PageHeight <= 0 || box.X0 < 0 || box.Y0 < 0 ||
		box.X0 >= box.X1 || box.Y0 >= box.Y1 || box.X1 > box.PageWidth || box.Y1 > box.PageHeight ||
		(box.X0 == 0 && box.Y0 == 0 && box.X1 == box.PageWidth && box.Y1 == box.PageHeight) {
		return ErrSchemaWikiContractInvalid
	}
	quoteHash, _, err := schemaWikiSHA256("schema-wiki-text.v1", map[string]any{"text": citation.QuoteSnapshot})
	if err != nil || quoteHash != citation.QuoteSHA256 {
		return ErrSchemaWikiContractInvalid
	}
	return requireSchemaWikiHash(citation.Contract, citation, "citation_sha256", citation.CitationSHA256)
}

func ValidateSchemaPack(pack SchemaPackV1) error {
	if pack.Contract != "schema-pack.v1" || pack.SchemaPackID == "" || pack.SchemaVersion == "" ||
		pack.DomainID == "" || len(pack.OrderedFieldIDs) == 0 || len(pack.Sections) == 0 {
		return ErrSchemaWikiContractInvalid
	}
	seenSections := map[string]struct{}{}
	flattened := make([]string, 0, len(pack.OrderedFieldIDs))
	for _, section := range pack.Sections {
		if section.SectionID == "" || len(section.OrderedFieldIDs) == 0 {
			return ErrSchemaWikiContractInvalid
		}
		if _, exists := seenSections[section.SectionID]; exists {
			return ErrSchemaWikiContractInvalid
		}
		seenSections[section.SectionID] = struct{}{}
		flattened = append(flattened, section.OrderedFieldIDs...)
	}
	if !equalStrings(flattened, pack.OrderedFieldIDs) || hasDuplicateStrings(pack.OrderedFieldIDs) {
		return ErrSchemaWikiContractInvalid
	}
	return requireSchemaWikiHash(pack.Contract, pack, "schema_pack_sha256", pack.SchemaPackSHA256)
}

func validateKnowledgeDomain(domain KnowledgeDomainV1) error {
	if domain.Contract != "knowledge-domain.v1" || domain.DomainID == "" || domain.DisplayName == "" {
		return ErrSchemaWikiContractInvalid
	}
	return requireSchemaWikiHash(domain.Contract, domain, "domain_sha256", domain.DomainSHA256)
}

func validateTaxonomySnapshot(snapshot TaxonomySnapshotV1) error {
	if snapshot.Contract != "taxonomy-snapshot.v1" || snapshot.DomainID == "" ||
		snapshot.TaxonomyVersion == "" || len(snapshot.Nodes) == 0 {
		return ErrSchemaWikiContractInvalid
	}
	byID := map[string]TaxonomyNodeV1{}
	for _, node := range snapshot.Nodes {
		if node.NodeID == "" || node.Slug == "" || node.Position < 0 {
			return ErrSchemaWikiContractInvalid
		}
		if _, exists := byID[node.NodeID]; exists {
			return ErrSchemaWikiContractInvalid
		}
		if (node.NodeKind == "entity") != (node.StableEntityID != nil) ||
			(node.NodeKind != "entity" && node.NodeKind != "category") {
			return ErrSchemaWikiContractInvalid
		}
		byID[node.NodeID] = node
	}
	for _, node := range snapshot.Nodes {
		seen := map[string]struct{}{}
		current := node
		for {
			if _, exists := seen[current.NodeID]; exists {
				return ErrSchemaWikiContractInvalid
			}
			seen[current.NodeID] = struct{}{}
			if current.ParentNodeID == nil {
				break
			}
			parent, exists := byID[*current.ParentNodeID]
			if !exists {
				return ErrSchemaWikiContractInvalid
			}
			current = parent
		}
	}
	return requireSchemaWikiHash(snapshot.Contract, snapshot, "taxonomy_sha256", snapshot.TaxonomySHA256)
}

func schemaWikiManifestDigest(members []SchemaWikiMemberV1, bindings []CitationMemberBindingV1) (string, error) {
	digest, _, err := schemaWikiSHA256("schema-wiki-manifest.v1", map[string]any{
		"members": members, "citation_bindings": bindings,
	})
	return digest, err
}

type schemaWikiDecodedMemberPayload struct {
	root    *SchemaRootPageV1
	section *SchemaSectionPageV1
	field   *SchemaFieldPageV1
}

func decodeClosedSchemaWikiPayload(raw json.RawMessage, target any) error {
	canonical, err := canonicalizeClosedSchemaWikiPayload(raw, target)
	if err != nil || !bytes.Equal(raw, canonical) {
		return ErrSchemaWikiContractInvalid
	}
	return nil
}

func canonicalizeClosedSchemaWikiPayload(raw json.RawMessage, target any) (json.RawMessage, error) {
	if len(raw) == 0 {
		return nil, ErrSchemaWikiContractInvalid
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return nil, ErrSchemaWikiContractInvalid
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return nil, ErrSchemaWikiContractInvalid
	}
	canonical, err := schemaWikiCanonicalJSON(target)
	if err != nil {
		return nil, ErrSchemaWikiContractInvalid
	}
	return canonical, nil
}

// CanonicalSchemaWikiMemberPayload accepts the equivalent JSON text
// forms a JSONB database may return, then reuses the A1 typed validator and
// canonical encoder. It never treats database text formatting as authority.
func CanonicalSchemaWikiMemberPayload(
	memberKind string,
	raw json.RawMessage,
) (json.RawMessage, error) {
	var target any
	switch memberKind {
	case "root":
		target = &SchemaRootPageV1{}
	case "section":
		target = &SchemaSectionPageV1{}
	case "field":
		target = &SchemaFieldPageV1{}
	default:
		return nil, ErrSchemaWikiContractInvalid
	}
	return canonicalizeClosedSchemaWikiPayload(raw, target)
}

func validateSchemaFieldPage(page SchemaFieldPageV1) error {
	if page.Contract != "schema-field-page.v1" || page.FieldID == "" {
		return ErrSchemaWikiContractInvalid
	}
	citations := map[string]struct{}{}
	citationIDs := map[string]struct{}{}
	for _, citation := range page.Citations {
		if err := ValidateCitationTarget(citation); err != nil {
			return err
		}
		if _, exists := citations[citation.CitationSHA256]; exists {
			return ErrSchemaWikiContractInvalid
		}
		if _, exists := citationIDs[citation.CitationID]; exists {
			return ErrSchemaWikiContractInvalid
		}
		citations[citation.CitationSHA256] = struct{}{}
		citationIDs[citation.CitationID] = struct{}{}
	}
	if hasDuplicateStrings(page.EvidenceReceiptSHA256s) {
		return ErrSchemaWikiContractInvalid
	}
	known := page.State == "present" || page.State == "absent_explicitly"
	if known {
		if page.ValueSnapshot == nil || *page.ValueSnapshot == "" || len(page.Citations) == 0 ||
			len(page.EvidenceReceiptSHA256s) == 0 || page.ReviewItemReason != nil {
			return ErrSchemaWikiContractInvalid
		}
	} else if page.State != "unknown" || page.ValueSnapshot != nil || len(page.Citations) != 0 ||
		len(page.EvidenceReceiptSHA256s) != 0 || page.ReviewItemReason == nil ||
		*page.ReviewItemReason != "FIELD_UNKNOWN" {
		return ErrSchemaWikiContractInvalid
	}
	return requireSchemaWikiHash(page.Contract, page, "field_page_sha256", page.FieldPageSHA256)
}

func validateSchemaWikiMemberPayload(member SchemaWikiMemberV1) (schemaWikiDecodedMemberPayload, error) {
	var decoded schemaWikiDecodedMemberPayload
	if member.Contract != "schema-wiki-member.v1" || member.MemberRef == "" {
		return decoded, ErrSchemaWikiContractInvalid
	}
	switch member.MemberKind {
	case "root":
		if member.SectionID != nil || member.FieldID != nil {
			return decoded, ErrSchemaWikiContractInvalid
		}
		var page SchemaRootPageV1
		if decodeClosedSchemaWikiPayload(member.Payload, &page) != nil ||
			page.Contract != "schema-root-page.v1" || page.DomainID == "" || page.SchemaPackID == "" ||
			page.SchemaVersion == "" || page.EntityID == "" || page.EntityVersionID == "" ||
			page.ProductVersionID == "" || page.TaxonomyVersion == "" || page.ProductDisplayName == "" ||
			len(page.OrderedSectionIDs) == 0 || hasDuplicateStrings(page.OrderedSectionIDs) ||
			requireSchemaWikiHash(page.Contract, page, "root_page_sha256", page.RootPageSHA256) != nil ||
			member.PayloadSHA256 != page.RootPageSHA256 {
			return decoded, ErrSchemaWikiContractInvalid
		}
		decoded.root = &page
	case "section":
		if member.SectionID == nil || member.FieldID != nil {
			return decoded, ErrSchemaWikiContractInvalid
		}
		var page SchemaSectionPageV1
		if decodeClosedSchemaWikiPayload(member.Payload, &page) != nil ||
			page.Contract != "schema-section-page.v1" || page.DomainID == "" || page.SchemaPackID == "" ||
			page.SchemaVersion == "" || page.EntityID == "" || page.EntityVersionID == "" ||
			page.ProductVersionID == "" || page.TaxonomyVersion == "" || page.SectionID != *member.SectionID ||
			page.DisplayName == "" || len(page.OrderedFieldIDs) == 0 || hasDuplicateStrings(page.OrderedFieldIDs) ||
			requireSchemaWikiHash(page.Contract, page, "section_page_sha256", page.SectionPageSHA256) != nil ||
			member.PayloadSHA256 != page.SectionPageSHA256 {
			return decoded, ErrSchemaWikiContractInvalid
		}
		decoded.section = &page
	case "field":
		if member.SectionID == nil || member.FieldID == nil {
			return decoded, ErrSchemaWikiContractInvalid
		}
		var page SchemaFieldPageV1
		if decodeClosedSchemaWikiPayload(member.Payload, &page) != nil || page.FieldID != *member.FieldID ||
			validateSchemaFieldPage(page) != nil || member.PayloadSHA256 != page.FieldPageSHA256 {
			return decoded, ErrSchemaWikiContractInvalid
		}
		decoded.field = &page
	default:
		return decoded, ErrSchemaWikiContractInvalid
	}
	if requireSchemaWikiHash(member.Contract, member, "member_digest", member.MemberDigest) != nil {
		return decoded, ErrSchemaWikiContractInvalid
	}
	return decoded, nil
}

func ValidateKnowledgeWikiRelease(release KnowledgeWikiReleaseV1, pack SchemaPackV1) error {
	if err := ValidateSchemaPack(pack); err != nil || release.Contract != "knowledge-wiki-release.v1" ||
		release.ReleaseState != "draft" || release.SchemaPack.SchemaPackSHA256 != pack.SchemaPackSHA256 ||
		release.Domain.DomainID != release.Taxonomy.DomainID || release.Domain.DomainID != pack.DomainID ||
		release.Domain.DomainID != release.Entity.DomainID || release.EntityVersion.EntityID != release.Entity.EntityID {
		return ErrSchemaWikiContractInvalid
	}
	if err := validateKnowledgeDomain(release.Domain); err != nil {
		return err
	}
	if err := validateTaxonomySnapshot(release.Taxonomy); err != nil {
		return err
	}
	if err := ValidateSchemaPack(release.SchemaPack); err != nil {
		return err
	}
	expected := [][4]string{{"root:" + release.EntityVersion.VersionID, "root", "", ""}}
	fieldSections := map[string]string{}
	for _, section := range pack.Sections {
		expected = append(expected, [4]string{"section:" + section.SectionID, "section", section.SectionID, ""})
		for _, fieldID := range section.OrderedFieldIDs {
			fieldSections[fieldID] = section.SectionID
		}
	}
	for _, fieldID := range pack.OrderedFieldIDs {
		expected = append(expected, [4]string{"field:" + fieldID, "field", fieldSections[fieldID], fieldID})
	}
	if len(release.Members) != len(expected) {
		return ErrSchemaWikiContractInvalid
	}
	membersByRef := map[string]SchemaWikiMemberV1{}
	memberDigests := map[string]struct{}{}
	decodedPayloads := make([]schemaWikiDecodedMemberPayload, len(release.Members))
	for index, member := range release.Members {
		sectionID, fieldID := "", ""
		if member.SectionID != nil {
			sectionID = *member.SectionID
		}
		if member.FieldID != nil {
			fieldID = *member.FieldID
		}
		actual := [4]string{member.MemberRef, member.MemberKind, sectionID, fieldID}
		decoded, err := validateSchemaWikiMemberPayload(member)
		if actual != expected[index] || err != nil {
			return ErrSchemaWikiContractInvalid
		}
		decodedPayloads[index] = decoded
		if _, exists := memberDigests[member.MemberDigest]; exists {
			return ErrSchemaWikiContractInvalid
		}
		memberDigests[member.MemberDigest] = struct{}{}
		membersByRef[member.MemberRef] = member
	}
	root := decodedPayloads[0].root
	sectionIDs := make([]string, len(pack.Sections))
	for index, section := range pack.Sections {
		sectionIDs[index] = section.SectionID
	}
	if root == nil || root.DomainID != release.Domain.DomainID || root.DomainSHA256 != release.Domain.DomainSHA256 ||
		root.SchemaPackID != pack.SchemaPackID || root.SchemaVersion != pack.SchemaVersion ||
		root.SchemaPackSHA256 != pack.SchemaPackSHA256 || root.EntityID != release.Entity.EntityID ||
		root.EntityVersionID != release.EntityVersion.VersionID ||
		root.ProductVersionID != release.EntityVersion.ProductVersionID ||
		root.TaxonomyVersion != release.Taxonomy.TaxonomyVersion ||
		root.TaxonomySHA256 != release.Taxonomy.TaxonomySHA256 ||
		!equalStrings(root.OrderedSectionIDs, sectionIDs) {
		return ErrSchemaWikiContractInvalid
	}
	for index, section := range pack.Sections {
		page := decodedPayloads[index+1].section
		if page == nil || page.DomainID != release.Domain.DomainID || page.DomainSHA256 != release.Domain.DomainSHA256 ||
			page.SchemaPackID != pack.SchemaPackID || page.SchemaVersion != pack.SchemaVersion ||
			page.SchemaPackSHA256 != pack.SchemaPackSHA256 || page.EntityID != release.Entity.EntityID ||
			page.EntityVersionID != release.EntityVersion.VersionID ||
			page.ProductVersionID != release.EntityVersion.ProductVersionID ||
			page.TaxonomyVersion != release.Taxonomy.TaxonomyVersion ||
			page.TaxonomySHA256 != release.Taxonomy.TaxonomySHA256 || page.SectionID != section.SectionID ||
			page.DisplayName != section.DisplayName || !equalStrings(page.OrderedFieldIDs, section.OrderedFieldIDs) {
			return ErrSchemaWikiContractInvalid
		}
	}
	previous := ""
	seenCitations := map[string]struct{}{}
	payloadCitations := make([][2]string, 0, len(release.CitationBindings))
	for index, member := range release.Members {
		page := decodedPayloads[index].field
		if page == nil {
			continue
		}
		for _, citation := range page.Citations {
			if citation.LogicalMemberRef != member.MemberRef ||
				citation.EntityVersionID != release.EntityVersion.VersionID {
				return ErrSchemaWikiContractInvalid
			}
			payloadCitations = append(payloadCitations, [2]string{member.MemberRef, citation.CitationSHA256})
		}
	}
	sort.Slice(payloadCitations, func(left, right int) bool {
		if payloadCitations[left][0] != payloadCitations[right][0] {
			return payloadCitations[left][0] < payloadCitations[right][0]
		}
		return payloadCitations[left][1] < payloadCitations[right][1]
	})
	for _, binding := range release.CitationBindings {
		key := binding.LogicalMemberRef + "\x00" + binding.CitationSHA256
		if key < previous {
			return ErrSchemaWikiContractInvalid
		}
		previous = key
		if _, exists := seenCitations[binding.CitationSHA256]; exists {
			return ErrSchemaWikiContractInvalid
		}
		seenCitations[binding.CitationSHA256] = struct{}{}
		member, exists := membersByRef[binding.LogicalMemberRef]
		if !exists || member.MemberDigest != binding.MemberDigest ||
			requireSchemaWikiHash(binding.Contract, binding, "binding_sha256", binding.BindingSHA256) != nil {
			return ErrSchemaWikiContractInvalid
		}
	}
	if len(payloadCitations) != len(release.CitationBindings) {
		return ErrSchemaWikiContractInvalid
	}
	for index, binding := range release.CitationBindings {
		if payloadCitations[index] != [2]string{binding.LogicalMemberRef, binding.CitationSHA256} {
			return ErrSchemaWikiContractInvalid
		}
	}
	manifestDigest, err := schemaWikiManifestDigest(release.Members, release.CitationBindings)
	if err != nil || manifestDigest != release.ManifestDigest {
		return ErrSchemaWikiContractInvalid
	}
	return requireSchemaWikiHash(release.Contract, release, "release_sha256", release.ReleaseSHA256)
}

func ValidateSchemaWikiReviewBundle(bundle SchemaWikiReviewBundleV1, release KnowledgeWikiReleaseV1) error {
	if err := ValidateKnowledgeWikiRelease(release, release.SchemaPack); err != nil ||
		ValidateSchema67GoldenQualityGateReceiptV1(bundle.QualityGateReceipt) != nil ||
		requireSchemaWikiHash(bundle.Contract, bundle, "review_bundle_sha256", bundle.ReviewBundleSHA256) != nil {
		return ErrSchemaWikiContractInvalid
	}
	members := make([]string, len(release.Members))
	for index, member := range release.Members {
		members[index] = member.MemberDigest
	}
	bindings := make([]string, len(release.CitationBindings))
	for index, binding := range release.CitationBindings {
		bindings[index] = binding.BindingSHA256
	}
	if bundle.CandidateSHA256 != release.CandidateSHA256 || bundle.ReleaseSHA256 != release.ReleaseSHA256 ||
		bundle.ManifestDigest != release.ManifestDigest || !equalStrings(bundle.OrderedMemberDigests, members) ||
		!equalStrings(bundle.OrderedBindingSHA256s, bindings) || bundle.ReviewPolicySHA256 != release.ReviewPolicySHA256 ||
		bundle.DomainSHA256 != release.Domain.DomainSHA256 || bundle.TaxonomySHA256 != release.Taxonomy.TaxonomySHA256 ||
		bundle.SchemaPackSHA256 != release.SchemaPack.SchemaPackSHA256 || bundle.EntityID != release.Entity.EntityID ||
		bundle.VersionID != release.EntityVersion.VersionID ||
		bundle.QualityGateReceipt.CandidateSHA256 != release.CandidateSHA256 {
		return ErrSchemaWikiContractInvalid
	}
	return nil
}

func ValidateSchema67GoldenQualityGateReceiptV1(receipt Schema67GoldenQualityGateReceiptV1) error {
	if receipt.Contract != "schema67-golden-quality-gate-receipt.v1" ||
		receipt.Status != "PASS" || receipt.ProductVersionID != "596-1" ||
		strings.TrimSpace(receipt.GoldenVersion) == "" ||
		receipt.EvaluatorIdentitySHA256 != schema67GoldenEvaluatorIdentitySHA256 ||
		receipt.MetricPolicySHA256 != schema67GoldenMetricPolicySHA256 ||
		len(receipt.OrderedFieldDecisionSHA256s) != 67 || len(receipt.MetricReceiptSHA256s) != 15 ||
		len(receipt.GoldenApprovalSHA256s) != 2 || receipt.GoldenApprovalSHA256s[0] == receipt.GoldenApprovalSHA256s[1] ||
		strings.TrimSpace(receipt.SignerKeyID) == "" || strings.TrimSpace(receipt.Signature) == "" ||
		requireSchemaWikiHash(receipt.Contract, receipt, "receipt_sha256", receipt.ReceiptSHA256) != nil {
		return ErrSchemaWikiContractInvalid
	}
	digests := []string{
		receipt.CandidateSHA256,
		receipt.CandidateEvidenceAuthoritySHA256,
		receipt.GoldenSetSHA256,
		receipt.EvaluatorIdentitySHA256,
		receipt.MetricPolicySHA256,
		receipt.PrivateDossierSHA256,
		receipt.PublicAggregateSHA256,
		receipt.WholeBatchApprovalReceiptSHA256,
		receipt.ReceiptSHA256,
	}
	digests = append(digests, receipt.OrderedFieldDecisionSHA256s...)
	digests = append(digests, receipt.MetricReceiptSHA256s...)
	digests = append(digests, receipt.GoldenApprovalSHA256s...)
	for _, digest := range digests {
		if !validSchemaWikiSHA256(digest) {
			return ErrSchemaWikiContractInvalid
		}
	}
	return nil
}

var schema67GoldenMetricIDs = []string{
	"sgq.state.micro_accuracy.v1",
	"sgq.state.macro_recall.v1",
	"sgq.value.present.micro_precision.v1",
	"sgq.value.present.micro_recall.v1",
	"sgq.value.present.macro_f1.v1",
	"sgq.state.absent_to_unknown.v1",
	"sgq.state.unknown_to_absent.v1",
	"sgq.value.wrong_fill_rate.v1",
	"sgq.value.hallucinated_fill_rate.v1",
	"sgq.evidence.document_revision_page_precision.v1",
	"sgq.evidence.field_support_recall.v1",
	"sgq.evidence.bbox_iou.v1",
	"sgq.evidence.highlight_accuracy.v1",
	"sgq.human.high_risk_pass.v1",
	"sgq.human.conflict_resolution_pass.v1",
}

var schema67GoldenOrderedFieldIDs = []string{
	"product_code",
	"product_short_name",
	"product_name",
	"sales_start_date",
	"sales_end_date",
	"product_type",
	"insurance_category",
	"sales_channels",
	"external_publication_status",
	"sales_status",
	"policy_role",
	"product_summary",
	"official_product_features",
	"target_customer_profile",
	"marketing_tagline",
	"product_overview",
	"entry_age_range",
	"insured_eligibility",
	"health_declaration_requirements",
	"geographic_eligibility_requirements",
	"social_insurance_requirement",
	"eligible_occupation_classes",
	"underwriting_method",
	"premium_payment_term",
	"premium_payment_frequency",
	"cooling_off_period",
	"waiting_period",
	"premium_grace_period",
	"coverage_period",
	"coverage_term_category",
	"surrender_and_cancellation_terms",
	"coverage_and_renewal_terms",
	"guaranteed_renewal_status",
	"guaranteed_renewal_period",
	"product_conversion_rules",
	"premium_adjustment_rules",
	"post_discontinuation_renewal_arrangement",
	"covered_risk_categories",
	"coverage_responsibilities",
	"coverage_summary",
	"cancer_medical_coverage",
	"age_segment_tags",
	"coverage_limit_category",
	"special_coverage_and_exclusion_tags",
	"exclusions",
	"pre_existing_condition_rules",
	"out_of_hospital_special_drug_coverage",
	"indemnity_principle",
	"zero_deductible_flag",
	"deductible_rules",
	"outpatient_inpatient_scope",
	"reimbursable_expense_scope",
	"reimbursement_rate_rules",
	"eligible_hospital_scope",
	"premium_medical_facility_coverage",
	"direct_billing_and_advance_payment_rules",
	"claim_application_deadline_and_documents",
	"policyholder_rights",
	"eligible_service_packages",
	"medical_service_benefits",
	"tax_qualified_status",
	"tax_benefit_rules",
	"product_bundle_rules",
	"objection_handling_scripts",
	"product_faq",
	"four_step_sales_script",
	"sales_pitch_script",
}

func validSchema67GoldenState(value string) bool {
	return value == "present" || value == "absent_explicitly" || value == "unknown"
}

func validateSchema67GoldenFieldDecisionV1(decision Schema67GoldenFieldDecisionV1) error {
	if strings.TrimSpace(decision.FieldID) == "" ||
		!validSchemaWikiSHA256(decision.GoldenFieldSHA256) ||
		!validSchema67GoldenState(decision.CandidateState) ||
		!validSchema67GoldenState(decision.GoldenState) ||
		decision.AtomTruePositive < 0 || decision.AtomFalsePositive < 0 ||
		decision.AtomFalseNegative < 0 || decision.AtomF1PPM < 0 ||
		decision.AtomF1PPM > 1_000_000 || decision.EvidenceFragments < 0 ||
		decision.EvidenceFragmentsMatched < 0 ||
		decision.EvidenceFragmentsMatched > decision.EvidenceFragments ||
		decision.BBoxRequired < 0 || decision.BBoxPassed < 0 ||
		decision.BBoxPassed > decision.BBoxRequired ||
		len(decision.BBoxIOUPPMValues) != decision.BBoxRequired ||
		requireSchemaWikiHash(
			"schema67-golden-field-decision.v1", decision,
			"decision_sha256", decision.DecisionSHA256,
		) != nil {
		return ErrSchemaWikiContractInvalid
	}
	for _, value := range decision.BBoxIOUPPMValues {
		if value < 0 || value > 1_000_000 {
			return ErrSchemaWikiContractInvalid
		}
	}
	return nil
}

func validateSchema67GoldenMetricV1(metric Schema67GoldenMetricV1) error {
	if strings.TrimSpace(metric.MetricID) == "" ||
		(metric.Evaluability != "EVALUABLE" && metric.Evaluability != "NOT_EVALUABLE") ||
		(metric.SampleSize != "SMALL_SAMPLE" && metric.SampleSize != "ADEQUATE" &&
			metric.SampleSize != "NOT_EVALUABLE") ||
		(metric.AdmissionStatus != "PASS" && metric.AdmissionStatus != "FAIL") ||
		requireSchemaWikiHash(
			"schema67-golden-metric.v1", metric, "metric_sha256", metric.MetricSHA256,
		) != nil {
		return ErrSchemaWikiContractInvalid
	}
	for _, support := range metric.Supports {
		if support < 0 {
			return ErrSchemaWikiContractInvalid
		}
	}
	if metric.Evaluability == "EVALUABLE" {
		if metric.Numerator == nil || metric.Denominator == nil || metric.ValuePPM == nil ||
			*metric.Numerator < 0 || *metric.Denominator <= 0 ||
			*metric.Numerator > *metric.Denominator || *metric.ValuePPM < 0 ||
			*metric.ValuePPM > 1_000_000 || metric.SampleSize == "NOT_EVALUABLE" {
			return ErrSchemaWikiContractInvalid
		}
		for _, bound := range []*int{metric.WilsonLowPPM, metric.WilsonHighPPM} {
			if bound != nil && (*bound < 0 || *bound > 1_000_000) {
				return ErrSchemaWikiContractInvalid
			}
		}
		if (metric.WilsonLowPPM == nil) != (metric.WilsonHighPPM == nil) {
			return ErrSchemaWikiContractInvalid
		}
		return nil
	}
	if metric.Numerator != nil || metric.Denominator != nil || metric.ValuePPM != nil ||
		metric.WilsonLowPPM != nil || metric.WilsonHighPPM != nil ||
		metric.SampleSize != "NOT_EVALUABLE" {
		return ErrSchemaWikiContractInvalid
	}
	return nil
}

func ValidateSchema67GoldenPrivateDossierV1(dossier Schema67GoldenPrivateDossierV1) error {
	if dossier.Contract != "schema67-golden-private-dossier.v1" || dossier.Status != "PASS" ||
		len(dossier.ReasonCodes) != 0 || len(dossier.FieldDecisions) != 67 ||
		len(dossier.Metrics) != len(schema67GoldenMetricIDs) ||
		!validSchemaWikiSHA256(dossier.CandidateSHA256) ||
		!validSchemaWikiSHA256(dossier.CandidateEvidenceAuthoritySHA256) ||
		!validSchemaWikiSHA256(dossier.GoldenSetSHA256) ||
		requireSchemaWikiHash(
			dossier.Contract, dossier, "dossier_sha256", dossier.DossierSHA256,
		) != nil {
		return ErrSchemaWikiContractInvalid
	}
	for index, decision := range dossier.FieldDecisions {
		if validateSchema67GoldenFieldDecisionV1(decision) != nil {
			return ErrSchemaWikiContractInvalid
		}
		if decision.FieldID != schema67GoldenOrderedFieldIDs[index] {
			return ErrSchemaWikiContractInvalid
		}
	}
	for index, metric := range dossier.Metrics {
		if metric.MetricID != schema67GoldenMetricIDs[index] ||
			validateSchema67GoldenMetricV1(metric) != nil {
			return ErrSchemaWikiContractInvalid
		}
	}
	return nil
}

func ValidateSchema67GoldenPublicAggregateV1(aggregate Schema67GoldenPublicAggregateV1) error {
	if aggregate.Contract != "schema67-golden-public-aggregate.v1" ||
		aggregate.ProductVersionID != "596-1" || aggregate.Status != "PASS" ||
		len(aggregate.ReasonCodes) != 0 || len(aggregate.Metrics) != len(schema67GoldenMetricIDs) ||
		!validSchemaWikiSHA256(aggregate.CandidateSHA256) ||
		!validSchemaWikiSHA256(aggregate.GoldenSetSHA256) ||
		aggregate.EvaluatorIdentitySHA256 != schema67GoldenEvaluatorIdentitySHA256 ||
		requireSchemaWikiHash(
			aggregate.Contract, aggregate, "aggregate_sha256", aggregate.AggregateSHA256,
		) != nil {
		return ErrSchemaWikiContractInvalid
	}
	for index, metric := range aggregate.Metrics {
		if metric.MetricID != schema67GoldenMetricIDs[index] ||
			validateSchema67GoldenMetricV1(metric) != nil {
			return ErrSchemaWikiContractInvalid
		}
	}
	return nil
}

func ValidateSchema67GoldenEvaluationReviewBundleV1(
	bundle Schema67GoldenEvaluationReviewBundleV1,
) error {
	receipt := bundle.QualityGateReceipt
	public := bundle.PublicAggregate
	private := bundle.PrivateDossier
	if bundle.Contract != "schema67-golden-evaluation-review-bundle.v1" ||
		ValidateSchema67GoldenQualityGateReceiptV1(receipt) != nil ||
		ValidateSchema67GoldenPublicAggregateV1(public) != nil ||
		ValidateSchema67GoldenPrivateDossierV1(private) != nil ||
		bundle.EvaluationID != receipt.ReceiptSHA256 ||
		receipt.CandidateSHA256 != public.CandidateSHA256 ||
		receipt.CandidateSHA256 != private.CandidateSHA256 ||
		receipt.CandidateEvidenceAuthoritySHA256 != private.CandidateEvidenceAuthoritySHA256 ||
		receipt.GoldenSetSHA256 != public.GoldenSetSHA256 ||
		receipt.GoldenSetSHA256 != private.GoldenSetSHA256 ||
		receipt.EvaluatorIdentitySHA256 != public.EvaluatorIdentitySHA256 ||
		receipt.PrivateDossierSHA256 != private.DossierSHA256 ||
		receipt.PublicAggregateSHA256 != public.AggregateSHA256 ||
		!reflect.DeepEqual(public.Metrics, private.Metrics) ||
		requireSchemaWikiHash(
			bundle.Contract, bundle, "evaluation_bundle_sha256", bundle.EvaluationBundleSHA256,
		) != nil {
		return ErrSchemaWikiContractInvalid
	}
	decisionDigests := make([]string, len(private.FieldDecisions))
	for index, decision := range private.FieldDecisions {
		decisionDigests[index] = decision.DecisionSHA256
	}
	metricDigests := make([]string, len(private.Metrics))
	for index, metric := range private.Metrics {
		metricDigests[index] = metric.MetricSHA256
	}
	if !equalStrings(receipt.OrderedFieldDecisionSHA256s, decisionDigests) ||
		!equalStrings(receipt.MetricReceiptSHA256s, metricDigests) {
		return ErrSchemaWikiContractInvalid
	}
	return nil
}

func ParseSchema67GoldenEvaluationReviewBundleV1(
	raw []byte,
) (Schema67GoldenEvaluationReviewBundleV1, error) {
	var bundle Schema67GoldenEvaluationReviewBundleV1
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&bundle); err != nil {
		return bundle, ErrSchemaWikiContractInvalid
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return bundle, ErrSchemaWikiContractInvalid
	}
	canonical, err := schemaWikiCanonicalJSON(bundle)
	if err != nil || !bytes.Equal(bytes.TrimSpace(raw), canonical) ||
		ValidateSchema67GoldenEvaluationReviewBundleV1(bundle) != nil {
		return bundle, ErrSchemaWikiContractInvalid
	}
	return bundle, nil
}

func validateSchema67GoldenReviewValueV1(value Schema67GoldenReviewValueV1) error {
	switch value.Mode {
	case "NONE":
		if value.Literal != nil || value.SHA256 != nil {
			return ErrSchemaWikiContractInvalid
		}
	case "SHA256_ONLY":
		if value.Literal != nil || value.SHA256 == nil || !validSchemaWikiSHA256(*value.SHA256) {
			return ErrSchemaWikiContractInvalid
		}
	case "LITERAL":
		if value.Literal == nil || value.SHA256 == nil || strings.TrimSpace(*value.Literal) == "" {
			return ErrSchemaWikiContractInvalid
		}
		expected, _, err := schemaWikiSHA256(
			"schema67-golden-review-value.v1", map[string]string{"literal": *value.Literal},
		)
		if err != nil || expected != *value.SHA256 {
			return ErrSchemaWikiContractInvalid
		}
	default:
		return ErrSchemaWikiContractInvalid
	}
	return nil
}

func validateSchema67GoldenEvidenceChangeV1(change Schema67GoldenEvidenceChangeV1) error {
	validShape := false
	switch change.ChangeKind {
	case "ADDED":
		validShape = change.CandidateEvidenceID != nil && change.GoldenEvidenceSHA256 == nil
	case "REMOVED":
		validShape = change.CandidateEvidenceID == nil && change.GoldenEvidenceSHA256 != nil
	case "REPLACED", "UNCHANGED":
		validShape = change.CandidateEvidenceID != nil && change.GoldenEvidenceSHA256 != nil
	}
	if !validShape || (change.CandidateEvidenceID != nil &&
		!validSchemaWikiSHA256(*change.CandidateEvidenceID)) ||
		(change.GoldenEvidenceSHA256 != nil && !validSchemaWikiSHA256(*change.GoldenEvidenceSHA256)) ||
		requireSchemaWikiHash(
			"schema67-golden-evidence-change.v1", change, "change_sha256", change.ChangeSHA256,
		) != nil {
		return ErrSchemaWikiContractInvalid
	}
	return nil
}

func validateSchema67GoldenReviewFieldMetadataV1(
	field Schema67GoldenReviewFieldMetadataV1,
) error {
	if strings.TrimSpace(field.FieldID) == "" || !validSchemaWikiSHA256(field.DecisionSHA256) ||
		!validSchema67GoldenState(field.CandidateState) || !validSchema67GoldenState(field.GoldenState) ||
		validateSchema67GoldenReviewValueV1(field.CandidateValue) != nil ||
		validateSchema67GoldenReviewValueV1(field.GoldenValue) != nil ||
		(field.ValueComparison != "MATCH" && field.ValueComparison != "DIFF" &&
			field.ValueComparison != "NOT_COMPARABLE") ||
		field.RiskStatus != "PASS" || field.ConflictStatus != "RESOLVED" ||
		field.ReviewStatus != "REVIEWED" || len(field.ReasonCodes) != 0 ||
		requireSchemaWikiHash(
			"schema67-golden-review-field-metadata.v1", field,
			"field_metadata_sha256", field.FieldMetadataSHA256,
		) != nil {
		return ErrSchemaWikiContractInvalid
	}
	if (field.CandidateState == "unknown") != (field.CandidateValue.Mode == "NONE") ||
		(field.GoldenState == "unknown") != (field.GoldenValue.Mode == "NONE") {
		return ErrSchemaWikiContractInvalid
	}
	for _, change := range field.EvidenceChanges {
		if validateSchema67GoldenEvidenceChangeV1(change) != nil {
			return ErrSchemaWikiContractInvalid
		}
	}
	return nil
}

func validateSchema67GoldenReviewSuccessorMetadataShape(
	metadata Schema67GoldenReviewSuccessorMetadataV1,
) error {
	if metadata.Contract != "schema67-golden-review-successor-metadata.v1" ||
		metadata.AuthorityLevel != "REAL_NAMED_HUMAN" ||
		!validSchemaWikiSHA256(metadata.CandidateSHA256) ||
		!validSchemaWikiSHA256(metadata.GoldenSetSHA256) ||
		!validSchemaWikiSHA256(metadata.QualityGateReceiptSHA256) ||
		!validSchemaWikiSHA256(metadata.EvaluationBundleSHA256) ||
		strings.TrimSpace(metadata.GoldenVersion) == "" ||
		metadata.AnnotationLayer.Contract != "schema67-annotation-layer.v1" ||
		metadata.AnnotationLayer.AnnotatorModelID != "claude-fable-5" ||
		!validSchemaWikiSHA256(metadata.AnnotationLayer.AnnotationReceiptSHA256) ||
		metadata.HumanReviewLayer.Contract != "schema67-human-review-layer.v1" ||
		metadata.HumanReviewLayer.ReviewedBy != "linyao" ||
		strings.TrimSpace(metadata.HumanReviewLayer.ReviewedAt) == "" ||
		metadata.HumanReviewLayer.ReceiptStatus != "VERIFIED" ||
		!validSchemaWikiSHA256(metadata.HumanReviewLayer.ReviewReceiptSHA256) ||
		len(metadata.OrderedFields) != len(schema67GoldenOrderedFieldIDs) ||
		requireSchemaWikiHash(
			metadata.Contract, metadata, "metadata_sha256", metadata.MetadataSHA256,
		) != nil {
		return ErrSchemaWikiContractInvalid
	}
	for index, field := range metadata.OrderedFields {
		if field.FieldID != schema67GoldenOrderedFieldIDs[index] ||
			validateSchema67GoldenReviewFieldMetadataV1(field) != nil {
			return ErrSchemaWikiContractInvalid
		}
	}
	return nil
}

func ValidateSchema67GoldenReviewSuccessorMetadataV1(
	metadata Schema67GoldenReviewSuccessorMetadataV1,
	evaluation Schema67GoldenEvaluationReviewBundleV1,
	evidenceAuthority Schema67CandidateEvidenceAuthorityV1,
) error {
	if validateSchema67GoldenReviewSuccessorMetadataShape(metadata) != nil ||
		ValidateSchema67GoldenEvaluationReviewBundleV1(evaluation) != nil ||
		metadata.CandidateSHA256 != evaluation.QualityGateReceipt.CandidateSHA256 ||
		metadata.CandidateSHA256 != evidenceAuthority.CandidateSHA256 ||
		metadata.GoldenSetSHA256 != evaluation.QualityGateReceipt.GoldenSetSHA256 ||
		metadata.QualityGateReceiptSHA256 != evaluation.QualityGateReceipt.ReceiptSHA256 ||
		metadata.EvaluationBundleSHA256 != evaluation.EvaluationBundleSHA256 ||
		metadata.GoldenVersion != evaluation.QualityGateReceipt.GoldenVersion ||
		metadata.HumanReviewLayer.ReviewReceiptSHA256 !=
			evaluation.QualityGateReceipt.WholeBatchApprovalReceiptSHA256 {
		return ErrSchemaWikiContractInvalid
	}
	decisionByField := make(map[string]Schema67GoldenFieldDecisionV1, 67)
	for _, decision := range evaluation.PrivateDossier.FieldDecisions {
		decisionByField[decision.FieldID] = decision
	}
	receiptByID := make(map[string]Schema67CitationAuthorityJoinReceiptV1, len(evidenceAuthority.JoinReceipts))
	for _, receipt := range evidenceAuthority.JoinReceipts {
		receiptByID[receipt.ReceiptSHA256] = receipt
	}
	seenEvidence := make(map[string]struct{}, len(receiptByID))
	for _, field := range metadata.OrderedFields {
		decision, exists := decisionByField[field.FieldID]
		if !exists || field.DecisionSHA256 != decision.DecisionSHA256 ||
			field.CandidateState != decision.CandidateState || field.GoldenState != decision.GoldenState ||
			len(field.EvidenceChanges) != decision.EvidenceFragments ||
			!decision.HighRiskPass || !decision.ConflictResolved {
			return ErrSchemaWikiContractInvalid
		}
		for _, change := range field.EvidenceChanges {
			if change.CandidateEvidenceID == nil {
				continue
			}
			receipt, exists := receiptByID[*change.CandidateEvidenceID]
			if !exists || receipt.FieldID != field.FieldID {
				return ErrSchemaWikiContractInvalid
			}
			if _, duplicate := seenEvidence[*change.CandidateEvidenceID]; duplicate {
				return ErrSchemaWikiContractInvalid
			}
			seenEvidence[*change.CandidateEvidenceID] = struct{}{}
		}
	}
	if len(seenEvidence) != len(receiptByID) {
		return ErrSchemaWikiContractInvalid
	}
	return nil
}

func ParseSchemaWikiGoldenQualityDossierV2(
	raw []byte,
) (SchemaWikiGoldenQualityDossierV2, error) {
	var dossier SchemaWikiGoldenQualityDossierV2
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&dossier); err != nil {
		return dossier, ErrSchemaWikiContractInvalid
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return dossier, ErrSchemaWikiContractInvalid
	}
	canonical, err := schemaWikiCanonicalJSON(dossier)
	canonicalWithNewline := append(append([]byte(nil), canonical...), '\n')
	if err != nil || (!bytes.Equal(raw, canonical) && !bytes.Equal(raw, canonicalWithNewline)) ||
		dossier.Version != "schema-wiki-golden-quality-dossier.v2" ||
		strings.TrimSpace(dossier.PreparationID) == "" ||
		dossier.EvaluationID != dossier.QualityGateReceiptSHA256 ||
		dossier.EvaluationBundleSHA256 != dossier.ReviewSuccessor.EvaluationBundleSHA256 ||
		dossier.QualityGateReceiptSHA256 != dossier.ReviewSuccessor.QualityGateReceiptSHA256 ||
		dossier.PrivateDossier.CandidateSHA256 != dossier.ReviewSuccessor.CandidateSHA256 ||
		dossier.PrivateDossier.GoldenSetSHA256 != dossier.ReviewSuccessor.GoldenSetSHA256 ||
		dossier.ServingEffect != "NONE" ||
		ValidateSchema67GoldenPrivateDossierV1(dossier.PrivateDossier) != nil ||
		validateSchema67GoldenReviewSuccessorMetadataShape(dossier.ReviewSuccessor) != nil {
		return dossier, ErrSchemaWikiContractInvalid
	}
	return dossier, nil
}

// ComputeSchemaWikiGoldenSuccessorStatusSHA256 hashes the complete closed
// status except for its self-hash field.
func ComputeSchemaWikiGoldenSuccessorStatusSHA256(
	status SchemaWikiGoldenSuccessorStatusV1,
) (string, error) {
	digest, _, err := schemaWikiHashWithout(
		"schema-wiki-golden-successor-status.v1", status, "status_sha256",
	)
	return digest, err
}

// ValidateSchemaWikiGoldenSuccessorStatusV1 freezes the exact current 596-1
// migration status. A later successor needs a new canonical authority rather
// than relabeling this blocked status as admitted.
func ValidateSchemaWikiGoldenSuccessorStatusV1(
	status SchemaWikiGoldenSuccessorStatusV1,
) error {
	if status.Version != "schema-wiki-golden-successor-status.v1" ||
		status.Contract != status.Version ||
		status.TenantID != 10003 ||
		status.SpaceID != "space-596-1" ||
		status.RawKBID != "raw-kb-596-1" ||
		status.WikiKBID != "wiki-kb-596-1" ||
		status.ProductVersionID != "596-1" ||
		status.SchemaPackID != "medical-schema67.v1" ||
		status.GoldenSetSHA256 != "6ce87e0d1352b9f3435baa232c01f0dfdb6fd968b959b2462038849da40c8ad0" ||
		status.MappingSHA256 != "85646d263932d33a2dbb02fbbc93425252618d162c3c1e012b2fede5addf2f43" ||
		status.SuccessorFileSHA256 != "8ff7e476b41f737427a72dd08a86a28a0057b4b5d085b7e23399bc5d38671e71" ||
		status.AttestationSHA256 != "7fdbfde1b57de76a59c79b5e0535a48766c896e6ee7615bc055bb9bec73b0d5d" ||
		status.SourceReviewStatus != "COMPLETED" ||
		status.ReviewedBy != "linyao" ||
		status.AnnotatorModelID != "claude-fable-5" ||
		status.ReviewedAt != nil ||
		status.AttestorID != "workspace-owner-houjing" ||
		status.AttestedAt != "2026-08-11T11:21:07Z" ||
		status.Schema67MappingStatus != "COMPLETE_67" ||
		status.ClosedCount != 67 || status.ResidualCount != 0 ||
		len(status.ResidualFieldIDs) != 0 ||
		status.GoldenAdmissionStatus != "BLOCKED_RECEIPT_UNVERIFIED" ||
		status.ReceiptStatus != "UNVERIFIED" ||
		status.ReadyToSignStatus != "READY_TO_SIGN" ||
		requireSchemaWikiHash(
			"schema-wiki-golden-successor-status.v1", status,
			"status_sha256", status.StatusSHA256,
		) != nil {
		return ErrSchemaWikiContractInvalid
	}
	return nil
}

// ParseSchemaWikiGoldenSuccessorStatusV1 strictly admits only canonical JSON
// (with an optional final newline for cross-language fixtures).
func ParseSchemaWikiGoldenSuccessorStatusV1(
	raw []byte,
) (SchemaWikiGoldenSuccessorStatusV1, error) {
	var status SchemaWikiGoldenSuccessorStatusV1
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&status); err != nil {
		return status, ErrSchemaWikiContractInvalid
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return status, ErrSchemaWikiContractInvalid
	}
	canonical, err := schemaWikiCanonicalJSON(status)
	canonicalWithNewline := append(append([]byte(nil), canonical...), '\n')
	if err != nil || (!bytes.Equal(raw, canonical) && !bytes.Equal(raw, canonicalWithNewline)) ||
		ValidateSchemaWikiGoldenSuccessorStatusV1(status) != nil {
		return status, ErrSchemaWikiContractInvalid
	}
	return status, nil
}

func ComputeSchemaWikiGoldenEvidencePreviewAuthoritySHA256(
	authority SchemaWikiGoldenEvidencePreviewAuthorityV1,
) (string, error) {
	if authority.Contract != "schema-wiki-golden-evidence-preview-authority.v1" {
		return "", ErrSchemaWikiContractInvalid
	}
	authority.OpaqueToken = ""
	digest, _, err := schemaWikiHashWithout(
		authority.Contract, authority, "authority_sha256",
	)
	return digest, err
}

func ValidateSchemaWikiGoldenEvidencePreviewAuthorityV1(
	authority SchemaWikiGoldenEvidencePreviewAuthorityV1,
) error {
	if authority.Contract != "schema-wiki-golden-evidence-preview-authority.v1" ||
		authority.TokenKeyID == "" || authority.PreparationID == "" ||
		authority.EvaluationID == "" || authority.FieldID == "" || authority.EvidenceID == "" ||
		authority.ExpiresAtUnix <= 0 || authority.RetentionState != KnowledgeRevisionSourcePinned ||
		authority.CoordinateSpaceVersion != "normalized_0_1e6" ||
		authority.PageWidth != 1_000_000 || authority.PageHeight != 1_000_000 ||
		(authority.RotationDegrees != 0 && authority.RotationDegrees != 90 &&
			authority.RotationDegrees != 180 && authority.RotationDegrees != 270) ||
		ValidateLiveRevisionSourceReceiptV1(authority.RevisionSource) != nil ||
		!validSchemaWikiSHA256(authority.CandidateSHA256) ||
		!validSchemaWikiSHA256(authority.EvaluationID) ||
		!validSchemaWikiSHA256(authority.EvidenceID) ||
		!validSchemaWikiSHA256(authority.CitationSHA256) ||
		!validSchemaWikiSHA256(authority.BindingSHA256) ||
		!validSchemaWikiSHA256(authority.EvidenceReceiptSHA256) ||
		!validSchemaWikiSHA256(authority.QuoteSHA256) ||
		!validSchemaWikiSHA256(authority.ContentSnapshotSHA256) ||
		authority.PageNumber <= 0 || authority.PageNumber > authority.RevisionSource.PageCount ||
		authority.BBox.CoordinateSystem != authority.CoordinateSpaceVersion ||
		authority.BBox.PageWidth != authority.PageWidth ||
		authority.BBox.PageHeight != authority.PageHeight || authority.BBox.X0 < 0 ||
		authority.BBox.Y0 < 0 || authority.BBox.X0 >= authority.BBox.X1 ||
		authority.BBox.Y0 >= authority.BBox.Y1 || authority.BBox.X1 > authority.PageWidth ||
		authority.BBox.Y1 > authority.PageHeight {
		return ErrSchemaWikiContractInvalid
	}
	digest, err := ComputeSchemaWikiGoldenEvidencePreviewAuthoritySHA256(authority)
	if err != nil || digest != authority.AuthoritySHA256 {
		return ErrSchemaWikiContractInvalid
	}
	return nil
}

func ValidateSchemaWikiGoldenEvidencePreviewAuthorityAgainst(
	presented SchemaWikiGoldenEvidencePreviewAuthorityV1,
	trusted SchemaWikiGoldenEvidencePreviewAuthorityV1,
) error {
	if ValidateSchemaWikiGoldenEvidencePreviewAuthorityV1(presented) != nil ||
		ValidateSchemaWikiGoldenEvidencePreviewAuthorityV1(trusted) != nil {
		return ErrSchemaWikiContractInvalid
	}
	presentedBytes, err := schemaWikiCanonicalJSON(presented)
	if err != nil {
		return ErrSchemaWikiContractInvalid
	}
	trustedBytes, err := schemaWikiCanonicalJSON(trusted)
	if err != nil || !bytes.Equal(presentedBytes, trustedBytes) {
		return ErrSchemaWikiContractInvalid
	}
	return nil
}

func ValidateSchemaWikiContractVector(vector SchemaWikiContractVectorV1, raw []byte) error {
	if vector.Contract != "schema-wiki-contract-vector.v1" || len(vector.Citations) == 0 {
		return ErrSchemaWikiContractInvalid
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	var closed SchemaWikiContractVectorV1
	if err := decoder.Decode(&closed); err != nil {
		return ErrSchemaWikiContractInvalid
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return ErrSchemaWikiContractInvalid
	}
	closedCanonical, err := schemaWikiCanonicalJSON(closed)
	if err != nil || !bytes.Equal(bytes.TrimSpace(raw), closedCanonical) {
		return ErrSchemaWikiContractInvalid
	}
	argumentCanonical, err := schemaWikiCanonicalJSON(vector)
	if err != nil || !bytes.Equal(argumentCanonical, closedCanonical) {
		return ErrSchemaWikiContractInvalid
	}
	if err := ValidateSchemaPack(vector.SchemaPack); err != nil ||
		ValidateKnowledgeWikiRelease(vector.Release, vector.SchemaPack) != nil {
		return ErrSchemaWikiContractInvalid
	}
	for _, citation := range vector.Citations {
		if err := ValidateCitationTarget(citation); err != nil {
			return err
		}
	}
	_, releasePreimage, err := schemaWikiHashWithout(vector.Release.Contract, vector.Release, "release_sha256")
	if err != nil || hex.EncodeToString(releasePreimage) != vector.Expected.ReleaseCanonicalPreimageHex ||
		vector.Expected.SchemaPackSHA256 != vector.SchemaPack.SchemaPackSHA256 ||
		vector.Expected.TaxonomySHA256 != vector.Release.Taxonomy.TaxonomySHA256 ||
		vector.Expected.ManifestDigest != vector.Release.ManifestDigest ||
		vector.Expected.ReleaseSHA256 != vector.Release.ReleaseSHA256 ||
		vector.Expected.CitationSHA256 != vector.Citations[0].CitationSHA256 {
		return ErrSchemaWikiContractInvalid
	}
	return nil
}

func equalStrings(left, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}

func hasDuplicateStrings(values []string) bool {
	seen := map[string]struct{}{}
	for _, value := range values {
		if _, exists := seen[value]; exists {
			return true
		}
		seen[value] = struct{}{}
	}
	return false
}
