package types

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
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

type SchemaWikiMemberV1 struct {
	Contract      string  `json:"contract"`
	MemberRef     string  `json:"member_ref"`
	MemberKind    string  `json:"member_kind"`
	SectionID     *string `json:"section_id"`
	FieldID       *string `json:"field_id"`
	PayloadSHA256 string  `json:"payload_sha256"`
	MemberDigest  string  `json:"member_digest"`
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
	if strings.TrimSpace(objectType) == "" || strings.ContainsAny(objectType, "\x00\r\n") {
		return nil, fmt.Errorf("%w: object type", ErrSchemaWikiContractInvalid)
	}
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
	canonical := bytes.TrimSuffix(encoded.Bytes(), []byte("\n"))
	preimage := append([]byte(schemaWikiHashPrefix), []byte(objectType)...)
	preimage = append(preimage, 0)
	preimage = append(preimage, canonical...)
	return preimage, nil
}

func schemaWikiCanonicalTreeValid(value any) bool {
	switch typed := value.(type) {
	case nil, bool, json.Number:
		return true
	case string:
		if !norm.NFC.IsNormalString(typed) {
			return false
		}
		for _, r := range typed {
			if r < 0x20 {
				return false
			}
		}
		return true
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
	for index, member := range release.Members {
		sectionID, fieldID := "", ""
		if member.SectionID != nil {
			sectionID = *member.SectionID
		}
		if member.FieldID != nil {
			fieldID = *member.FieldID
		}
		actual := [4]string{member.MemberRef, member.MemberKind, sectionID, fieldID}
		if actual != expected[index] || requireSchemaWikiHash(member.Contract, member, "member_digest", member.MemberDigest) != nil {
			return ErrSchemaWikiContractInvalid
		}
		if _, exists := memberDigests[member.MemberDigest]; exists {
			return ErrSchemaWikiContractInvalid
		}
		memberDigests[member.MemberDigest] = struct{}{}
		membersByRef[member.MemberRef] = member
	}
	previous := ""
	seenCitations := map[string]struct{}{}
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
	var decoded any
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if err := decoder.Decode(&decoded); err != nil {
		return err
	}
	canonical, err := json.Marshal(decoded)
	if err != nil || !bytes.Equal(bytes.TrimSpace(raw), canonical) {
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
