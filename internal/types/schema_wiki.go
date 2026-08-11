package types

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sort"
	"strings"

	"golang.org/x/text/unicode/norm"
)

const schemaWikiHashPrefix = "schema-wiki-canonical.v1\x00"

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

type SchemaWikiReviewBundleV1 struct {
	Contract              string   `json:"contract"`
	CandidateSHA256       string   `json:"candidate_sha256"`
	ReleaseSHA256         string   `json:"release_sha256"`
	ManifestDigest        string   `json:"manifest_digest"`
	OrderedMemberDigests  []string `json:"ordered_member_digests"`
	OrderedBindingSHA256s []string `json:"ordered_binding_sha256s"`
	ReviewPolicySHA256    string   `json:"review_policy_sha256"`
	DomainSHA256          string   `json:"domain_sha256"`
	TaxonomySHA256        string   `json:"taxonomy_sha256"`
	SchemaPackSHA256      string   `json:"schema_pack_sha256"`
	EntityID              string   `json:"entity_id"`
	VersionID             string   `json:"version_id"`
	ReviewBundleSHA256    string   `json:"review_bundle_sha256"`
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
		bundle.VersionID != release.EntityVersion.VersionID {
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
