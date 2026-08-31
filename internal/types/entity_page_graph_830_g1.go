package types

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"reflect"
	"strings"

	"golang.org/x/text/unicode/norm"
)

// ErrEntityPageGraphContract830G1 is the fail-closed cross-language contract error.
var ErrEntityPageGraphContract830G1 = errors.New("entity page graph 830 g1 contract invalid")

type EntityPagePresentationField830G1 struct {
	FieldKey   string `json:"field_key"`
	ShortTitle string `json:"short_title"`
}

type EntityPagePresentationSection830G1 struct {
	SectionKey  string                             `json:"section_key"`
	DisplayName string                             `json:"display_name"`
	Fields      []EntityPagePresentationField830G1 `json:"fields"`
}

type EntityPagePresentationProfile830G1 struct {
	Contract         string                               `json:"contract"`
	ProfileID        string                               `json:"profile_id"`
	ProfileVersion   string                               `json:"profile_version"`
	SchemaPackID     string                               `json:"schema_pack_id"`
	SchemaVersion    string                               `json:"schema_version"`
	SchemaPackSHA256 string                               `json:"schema_pack_sha256"`
	Sections         []EntityPagePresentationSection830G1 `json:"sections"`
	ProfileSHA256    string                               `json:"profile_sha256"`
}

type EntityPageManifestSourceAuthority830G1 struct {
	SourceRole             string `json:"source_role"`
	SourceSHA256           string `json:"source_sha256"`
	KnowledgeID            string `json:"knowledge_id"`
	ResourceID             string `json:"resource_id"`
	RevisionSourceID       string `json:"revision_source_id"`
	EvidenceParseAttemptID string `json:"evidence_parse_attempt_id"`
	WeKnoraParseAttempt    int    `json:"weknora_parse_attempt"`
	ParsedDocumentSHA256   string `json:"parsed_document_sha256"`
	ParseManifestSHA256    string `json:"parse_manifest_sha256"`
	SourceReceiptSHA256    string `json:"source_receipt_sha256"`
}

type EntityPageActualInputFiles830G1 struct {
	BundleManifestContract   string `json:"bundle_manifest_contract"`
	BundleManifestSHA256     string `json:"bundle_manifest_sha256"`
	BundleManifestFileSHA256 string `json:"bundle_manifest_file_sha256"`
	PreviewContract          string `json:"preview_contract"`
	PreviewSHA256            string `json:"preview_sha256"`
	PreviewFileSHA256        string `json:"preview_file_sha256"`
	ProfileFileSHA256        string `json:"profile_file_sha256"`
}

type EntityPageManifestInputAuthority830G1 struct {
	CandidateContract           string                                   `json:"candidate_contract"`
	CandidateSHA256             string                                   `json:"candidate_sha256"`
	CandidateFileSHA256         string                                   `json:"candidate_file_sha256"`
	ProductVersionID            string                                   `json:"product_version_id"`
	ClaimSetSHA256              string                                   `json:"claim_set_sha256"`
	EvidenceReceiptSetSHA256    string                                   `json:"evidence_receipt_set_sha256"`
	EvidenceAuthorityContract   string                                   `json:"evidence_authority_contract"`
	EvidenceAuthoritySHA256     string                                   `json:"evidence_authority_sha256"`
	EvidenceAuthorityFileSHA256 string                                   `json:"evidence_authority_file_sha256"`
	SourceAuthorities           []EntityPageManifestSourceAuthority830G1 `json:"source_authorities"`
	ActualFiles                 EntityPageActualInputFiles830G1          `json:"actual_files"`
}

type EntityPageAuthority830G1 struct {
	ServingAuthority             string `json:"serving_authority"`
	HarnessRole                  string `json:"harness_role"`
	PerPageActivationAllowed     bool   `json:"per_page_activation_allowed"`
	RenderedContentAuthoritative bool   `json:"rendered_content_authoritative"`
	DatabaseAccessRequired       bool   `json:"database_access_required"`
	NetworkAccessRequired        bool   `json:"network_access_required"`
	ProviderModelAccessRequired  bool   `json:"provider_model_access_required"`
}

type EntityPageExactCitation830G1 struct {
	Contract              string         `json:"contract"`
	CitationID            string         `json:"citation_id"`
	JoinReceiptSHA256     string         `json:"join_receipt_sha256"`
	EvidenceReceiptSHA256 string         `json:"evidence_receipt_sha256"`
	SourceRole            string         `json:"source_role"`
	SourceSHA256          string         `json:"source_sha256"`
	SourceRevisionID      string         `json:"source_revision_id"`
	KnowledgeID           string         `json:"knowledge_id"`
	ChunkID               string         `json:"chunk_id"`
	ParseAttemptID        string         `json:"parse_attempt_id"`
	ParsedDocumentSHA256  string         `json:"parsed_document_sha256"`
	ParseManifestSHA256   string         `json:"parse_manifest_sha256"`
	PageNumber            int            `json:"page_number"`
	LocatorKind           string         `json:"locator_kind"`
	LocatorRef            string         `json:"locator_ref"`
	LocatorContentSHA256  string         `json:"locator_content_sha256"`
	BBox                  CitationBBoxV1 `json:"bbox"`
	QuoteSnapshot         string         `json:"quote_snapshot"`
	QuoteSHA256           string         `json:"quote_sha256"`
	CitationSHA256        string         `json:"citation_sha256"`
}

type EntityPageFieldAssertionReference830G1 struct {
	FieldKey               string   `json:"field_key"`
	PageID                 string   `json:"page_id"`
	SourceReleaseID        string   `json:"source_release_id"`
	SourceCandidateSHA256  string   `json:"source_candidate_sha256"`
	ProductVersionID       string   `json:"product_version_id"`
	ClaimSHA256            string   `json:"claim_sha256"`
	EvidenceReceiptSHA256s []string `json:"evidence_receipt_sha256s"`
	CitationSHA256s        []string `json:"citation_sha256s"`
}

type EntityPageOverviewPayload830G1 struct {
	Contract              string                                   `json:"contract"`
	EntityID              string                                   `json:"entity_id"`
	EntityVersionID       string                                   `json:"entity_version_id"`
	OrderedSectionPageIDs []string                                 `json:"ordered_section_page_ids"`
	FieldAssertions       []EntityPageFieldAssertionReference830G1 `json:"field_assertions"`
}

type EntityPageSectionPayload830G1 struct {
	Contract        string                                   `json:"contract"`
	SectionKey      string                                   `json:"section_key"`
	FieldAssertions []EntityPageFieldAssertionReference830G1 `json:"field_assertions"`
}

type EntityPageFieldAssertionPayload830G1 struct {
	Contract          string                                 `json:"contract"`
	FieldKey          string                                 `json:"field_key"`
	Reference         EntityPageFieldAssertionReference830G1 `json:"reference"`
	State             string                                 `json:"state"`
	ValueSnapshot     *string                                `json:"value_snapshot"`
	DisplayValue      *string                                `json:"display_value"`
	UnknownReason     *string                                `json:"unknown_reason"`
	SourceTypedReason *string                                `json:"source_typed_reason"`
	Citations         []EntityPageExactCitation830G1         `json:"citations"`
}

type EntityPageEmptyFreeWikiPayload830G1 struct {
	Contract string           `json:"contract"`
	Items    []map[string]any `json:"items"`
}

type EntityPageMember830G1 struct {
	Contract                string          `json:"contract"`
	PageID                  string          `json:"page_id"`
	Namespace               string          `json:"namespace"`
	Route                   string          `json:"route"`
	PageKind                string          `json:"page_kind"`
	StableKey               string          `json:"stable_key"`
	ShortTitle              string          `json:"short_title"`
	SpaceID                 string          `json:"space_id"`
	WikiKBID                string          `json:"wiki_kb_id"`
	EntityID                string          `json:"entity_id"`
	ReleaseID               string          `json:"release_id"`
	CandidateSHA256         string          `json:"candidate_sha256"`
	ClaimSetSHA256          string          `json:"claim_set_sha256"`
	EvidenceAuthoritySHA256 string          `json:"evidence_authority_sha256"`
	SchemaPackSHA256        string          `json:"schema_pack_sha256"`
	ProfileSHA256           string          `json:"profile_sha256"`
	Payload                 json.RawMessage `json:"payload"`
	PayloadSHA256           string          `json:"payload_sha256"`
	MemberDigest            string          `json:"member_digest"`
}

type EntityPageTriStateDistribution830G1 struct {
	Present          int `json:"present"`
	AbsentExplicitly int `json:"absent_explicitly"`
	Unknown          int `json:"unknown"`
}

type EntityPageManifest830G1 struct {
	Contract                  string                                `json:"contract"`
	ReleaseID                 string                                `json:"release_id"`
	ActivationEpoch           uint64                                `json:"activation_epoch"`
	SpaceID                   string                                `json:"space_id"`
	WikiKBID                  string                                `json:"wiki_kb_id"`
	EntityID                  string                                `json:"entity_id"`
	EntityVersionID           string                                `json:"entity_version_id"`
	DisplayName               string                                `json:"display_name"`
	ClassificationDisplayName string                                `json:"classification_display_name"`
	Profile                   EntityPagePresentationProfile830G1    `json:"profile"`
	InputAuthority            EntityPageManifestInputAuthority830G1 `json:"input_authority"`
	Authority                 EntityPageAuthority830G1              `json:"authority"`
	Members                   []EntityPageMember830G1               `json:"members"`
	SectionCount              int                                   `json:"section_count"`
	FieldAssertionCount       int                                   `json:"field_assertion_count"`
	StateDistribution         EntityPageTriStateDistribution830G1   `json:"state_distribution"`
	FieldAssertionPageIDs     []string                              `json:"field_assertion_page_ids"`
	FreeWikiEmpty             bool                                  `json:"free_wiki_empty"`
	ManifestSHA256            string                                `json:"manifest_sha256"`
}

func ParseEntityPageManifest830G1(raw []byte) (EntityPageManifest830G1, error) {
	var manifest EntityPageManifest830G1
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&manifest); err != nil {
		return manifest, ErrEntityPageGraphContract830G1
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return manifest, ErrEntityPageGraphContract830G1
	}
	if err := ValidateEntityPageManifest830G1(manifest); err != nil {
		return EntityPageManifest830G1{}, err
	}
	return manifest, nil
}

func (manifest EntityPageManifest830G1) Member(pageKind, stableKey string) (EntityPageMember830G1, bool) {
	for _, member := range manifest.Members {
		if member.PageKind == pageKind && member.StableKey == stableKey {
			return member, true
		}
	}
	return EntityPageMember830G1{}, false
}

func (member EntityPageMember830G1) OverviewPayload() (EntityPageOverviewPayload830G1, error) {
	var payload EntityPageOverviewPayload830G1
	return payload, decodeEntityPagePayload830G1(member.Payload, &payload)
}

func (member EntityPageMember830G1) SectionPayload() (EntityPageSectionPayload830G1, error) {
	var payload EntityPageSectionPayload830G1
	return payload, decodeEntityPagePayload830G1(member.Payload, &payload)
}

func (member EntityPageMember830G1) FieldAssertionPayload() (EntityPageFieldAssertionPayload830G1, error) {
	var payload EntityPageFieldAssertionPayload830G1
	return payload, decodeEntityPagePayload830G1(member.Payload, &payload)
}

func (member EntityPageMember830G1) FreeWikiPayload() (EntityPageEmptyFreeWikiPayload830G1, error) {
	var payload EntityPageEmptyFreeWikiPayload830G1
	return payload, decodeEntityPagePayload830G1(member.Payload, &payload)
}

func decodeEntityPagePayload830G1(raw json.RawMessage, destination any) error {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return ErrEntityPageGraphContract830G1
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return ErrEntityPageGraphContract830G1
	}
	return nil
}

func ValidateEntityPageManifest830G1(manifest EntityPageManifest830G1) error {
	if manifest.Contract != "entity-page-manifest.830.g1.v1" || manifest.ActivationEpoch == 0 ||
		!entityPageText830G1(manifest.ReleaseID) || !entityPageText830G1(manifest.SpaceID) ||
		!entityPageText830G1(manifest.WikiKBID) || !entityPageText830G1(manifest.EntityID) ||
		!entityPageText830G1(manifest.EntityVersionID) || !entityPageText830G1(manifest.DisplayName) ||
		!entityPageText830G1(manifest.ClassificationDisplayName) ||
		validateEntityPageProfile830G1(manifest.Profile) != nil ||
		validateEntityPageInputAuthority830G1(manifest.InputAuthority) != nil ||
		manifest.Authority != (EntityPageAuthority830G1{
			ServingAuthority: "WEKNORA", HarnessRole: "OFFLINE_PURE_COMPILER",
		}) || !manifest.FreeWikiEmpty {
		return ErrEntityPageGraphContract830G1
	}

	expectedOrder := [][2]string{{"overview", "overview"}}
	fieldOrder := make([]string, 0)
	for _, section := range manifest.Profile.Sections {
		expectedOrder = append(expectedOrder, [2]string{"section", section.SectionKey})
		for _, field := range section.Fields {
			fieldOrder = append(fieldOrder, field.FieldKey)
		}
	}
	for _, fieldKey := range fieldOrder {
		expectedOrder = append(expectedOrder, [2]string{"field", fieldKey})
	}
	expectedOrder = append(expectedOrder, [2]string{"free_wiki", "free-wiki"})
	if len(manifest.Members) != len(expectedOrder) || manifest.SectionCount != len(manifest.Profile.Sections) ||
		manifest.FieldAssertionCount != len(fieldOrder) {
		return ErrEntityPageGraphContract830G1
	}

	pageIDs := map[string]struct{}{}
	fieldPageIDs := make([]string, 0, len(fieldOrder))
	fieldReferences := make(map[string]EntityPageFieldAssertionReference830G1, len(fieldOrder))
	fieldPayloads := make(map[string]EntityPageFieldAssertionPayload830G1, len(fieldOrder))
	sectionPageIDs := make([]string, 0, len(manifest.Profile.Sections))
	stateCounts := EntityPageTriStateDistribution830G1{}

	for index, member := range manifest.Members {
		if [2]string{member.PageKind, member.StableKey} != expectedOrder[index] ||
			validateEntityPageMember830G1(manifest, member) != nil {
			return ErrEntityPageGraphContract830G1
		}
		if _, duplicate := pageIDs[member.PageID]; duplicate {
			return ErrEntityPageGraphContract830G1
		}
		pageIDs[member.PageID] = struct{}{}
		switch member.PageKind {
		case "section":
			sectionPageIDs = append(sectionPageIDs, member.PageID)
		case "field":
			payload, err := member.FieldAssertionPayload()
			if err != nil || validateEntityPageFieldPayload830G1(member, payload) != nil ||
				payload.Reference.ProductVersionID != manifest.InputAuthority.ProductVersionID {
				return ErrEntityPageGraphContract830G1
			}
			fieldPageIDs = append(fieldPageIDs, member.PageID)
			fieldReferences[member.StableKey] = payload.Reference
			fieldPayloads[member.StableKey] = payload
			switch payload.State {
			case "present":
				stateCounts.Present++
			case "absent_explicitly":
				stateCounts.AbsentExplicitly++
			case "unknown":
				stateCounts.Unknown++
			default:
				return ErrEntityPageGraphContract830G1
			}
		}
	}
	if !reflect.DeepEqual(fieldPageIDs, manifest.FieldAssertionPageIDs) ||
		stateCounts != manifest.StateDistribution {
		return ErrEntityPageGraphContract830G1
	}

	overview, err := manifest.Members[0].OverviewPayload()
	if err != nil || overview.Contract != "entity-overview-page.830.g1.v1" ||
		overview.EntityID != manifest.EntityID || overview.EntityVersionID != manifest.EntityVersionID ||
		!reflect.DeepEqual(overview.OrderedSectionPageIDs, sectionPageIDs) ||
		!entityPageReferencesMatchOrder830G1(overview.FieldAssertions, fieldOrder, fieldReferences) {
		return ErrEntityPageGraphContract830G1
	}

	for index, section := range manifest.Profile.Sections {
		member := manifest.Members[index+1]
		payload, err := member.SectionPayload()
		sectionFields := make([]string, 0, len(section.Fields))
		for _, field := range section.Fields {
			sectionFields = append(sectionFields, field.FieldKey)
		}
		if err != nil || payload.Contract != "entity-section-page.830.g1.v1" ||
			payload.SectionKey != section.SectionKey ||
			!entityPageReferencesMatchOrder830G1(payload.FieldAssertions, sectionFields, fieldReferences) {
			return ErrEntityPageGraphContract830G1
		}
	}

	freeWiki, err := manifest.Members[len(manifest.Members)-1].FreeWikiPayload()
	if err != nil || freeWiki.Contract != "empty-free-wiki-page.830.g1.v1" || len(freeWiki.Items) != 0 {
		return ErrEntityPageGraphContract830G1
	}
	if !entityPageCitationAuthorityClosed830G1(manifest, fieldPayloads) {
		return ErrEntityPageGraphContract830G1
	}
	digest, _, err := entityPageHashWithout830G1(manifest.Contract, manifest, "manifest_sha256")
	if err != nil || digest != manifest.ManifestSHA256 {
		return ErrEntityPageGraphContract830G1
	}
	return nil
}

func validateEntityPageProfile830G1(profile EntityPagePresentationProfile830G1) error {
	if profile.Contract != "presentation-profile.v1" || !entityPageText830G1(profile.ProfileID) ||
		!entityPageText830G1(profile.ProfileVersion) || !entityPageText830G1(profile.SchemaPackID) ||
		!entityPageText830G1(profile.SchemaVersion) || !validSchemaWikiSHA256(profile.SchemaPackSHA256) ||
		len(profile.Sections) == 0 {
		return ErrEntityPageGraphContract830G1
	}
	sections := map[string]struct{}{}
	fields := map[string]struct{}{}
	for _, section := range profile.Sections {
		if !entityPageText830G1(section.SectionKey) || !entityPageText830G1(section.DisplayName) || len(section.Fields) == 0 {
			return ErrEntityPageGraphContract830G1
		}
		if _, duplicate := sections[section.SectionKey]; duplicate {
			return ErrEntityPageGraphContract830G1
		}
		sections[section.SectionKey] = struct{}{}
		for _, field := range section.Fields {
			if !entityPageText830G1(field.FieldKey) || !entityPageText830G1(field.ShortTitle) {
				return ErrEntityPageGraphContract830G1
			}
			if _, duplicate := fields[field.FieldKey]; duplicate {
				return ErrEntityPageGraphContract830G1
			}
			fields[field.FieldKey] = struct{}{}
		}
	}
	digest, _, err := entityPageHashWithout830G1(profile.Contract, profile, "profile_sha256")
	if err != nil || digest != profile.ProfileSHA256 {
		return ErrEntityPageGraphContract830G1
	}
	return nil
}

func validateEntityPageInputAuthority830G1(authority EntityPageManifestInputAuthority830G1) error {
	if !entityPageText830G1(authority.CandidateContract) || !entityPageText830G1(authority.ProductVersionID) ||
		!entityPageText830G1(authority.EvidenceAuthorityContract) {
		return ErrEntityPageGraphContract830G1
	}
	hashes := []string{
		authority.CandidateSHA256, authority.CandidateFileSHA256, authority.ClaimSetSHA256,
		authority.EvidenceReceiptSetSHA256, authority.EvidenceAuthoritySHA256,
		authority.EvidenceAuthorityFileSHA256, authority.ActualFiles.BundleManifestSHA256,
		authority.ActualFiles.BundleManifestFileSHA256, authority.ActualFiles.PreviewSHA256,
		authority.ActualFiles.PreviewFileSHA256, authority.ActualFiles.ProfileFileSHA256,
	}
	for _, hash := range hashes {
		if !validSchemaWikiSHA256(hash) {
			return ErrEntityPageGraphContract830G1
		}
	}
	if !entityPageText830G1(authority.ActualFiles.BundleManifestContract) ||
		!entityPageText830G1(authority.ActualFiles.PreviewContract) {
		return ErrEntityPageGraphContract830G1
	}
	for _, source := range authority.SourceAuthorities {
		if !entityPageText830G1(source.SourceRole) || !entityPageText830G1(source.KnowledgeID) ||
			!entityPageText830G1(source.ResourceID) || !entityPageText830G1(source.RevisionSourceID) ||
			!entityPageText830G1(source.EvidenceParseAttemptID) || source.WeKnoraParseAttempt <= 0 {
			return ErrEntityPageGraphContract830G1
		}
		for _, hash := range []string{source.SourceSHA256, source.ParsedDocumentSHA256, source.ParseManifestSHA256, source.SourceReceiptSHA256} {
			if !validSchemaWikiSHA256(hash) {
				return ErrEntityPageGraphContract830G1
			}
		}
	}
	return nil
}

func validateEntityPageMember830G1(manifest EntityPageManifest830G1, member EntityPageMember830G1) error {
	if member.Contract != "entity-page-member.830.g1.v1" || !entityPageText830G1(member.ShortTitle) ||
		member.SpaceID != manifest.SpaceID || member.WikiKBID != manifest.WikiKBID ||
		member.EntityID != manifest.EntityID || member.ReleaseID != manifest.ReleaseID ||
		member.CandidateSHA256 != manifest.InputAuthority.CandidateSHA256 ||
		member.ClaimSetSHA256 != manifest.InputAuthority.ClaimSetSHA256 ||
		member.EvidenceAuthoritySHA256 != manifest.InputAuthority.EvidenceAuthoritySHA256 ||
		member.SchemaPackSHA256 != manifest.Profile.SchemaPackSHA256 ||
		member.ProfileSHA256 != manifest.Profile.ProfileSHA256 ||
		!validSchemaWikiSHA256(member.PayloadSHA256) || !validSchemaWikiSHA256(member.MemberDigest) {
		return ErrEntityPageGraphContract830G1
	}
	identity := map[string]string{
		"space_id": member.SpaceID, "entity_id": member.EntityID,
		"page_kind": member.PageKind, "stable_key": member.StableKey,
	}
	pageDigest, _, err := entityPageSHA256830G1("entity-page-identity.830.g1.v1", identity)
	if err != nil || member.PageID != "page_"+pageDigest ||
		member.Namespace != entityPageNamespace830G1(member) || member.Route != entityPageRoute830G1(member) {
		return ErrEntityPageGraphContract830G1
	}
	var header struct {
		Contract string `json:"contract"`
	}
	if err := json.Unmarshal(member.Payload, &header); err != nil || header.Contract == "" {
		return ErrEntityPageGraphContract830G1
	}
	payloadDigest, _, err := entityPageSHA256830G1(header.Contract, member.Payload)
	memberDigest, _, memberErr := entityPageHashWithout830G1(member.Contract, member, "member_digest")
	if err != nil || memberErr != nil || payloadDigest != member.PayloadSHA256 || memberDigest != member.MemberDigest {
		return ErrEntityPageGraphContract830G1
	}
	return nil
}

func validateEntityPageFieldPayload830G1(member EntityPageMember830G1, payload EntityPageFieldAssertionPayload830G1) error {
	if payload.Contract != "field-assertion-page.830.g1.v1" || payload.FieldKey != member.StableKey ||
		payload.Reference.FieldKey != payload.FieldKey || payload.Reference.PageID != member.PageID ||
		payload.Reference.SourceReleaseID != member.ReleaseID ||
		payload.Reference.SourceCandidateSHA256 != member.CandidateSHA256 ||
		!validSchemaWikiSHA256(payload.Reference.ClaimSHA256) {
		return ErrEntityPageGraphContract830G1
	}
	claimDigest, _, err := entityPageSHA256830G1("field-assertion-claim.830.g1.v1", map[string]any{
		"source_release_id":       payload.Reference.SourceReleaseID,
		"source_candidate_sha256": payload.Reference.SourceCandidateSHA256,
		"product_version_id":      payload.Reference.ProductVersionID,
		"field_id":                payload.FieldKey, "state": payload.State, "value_snapshot": payload.ValueSnapshot,
	})
	if err != nil || claimDigest != payload.Reference.ClaimSHA256 {
		return ErrEntityPageGraphContract830G1
	}
	citationHashes := make([]string, 0, len(payload.Citations))
	receiptHashes := make([]string, 0, len(payload.Citations))
	seenReceipts := map[string]struct{}{}
	for _, citation := range payload.Citations {
		if validateEntityPageCitation830G1(citation) != nil {
			return ErrEntityPageGraphContract830G1
		}
		citationHashes = append(citationHashes, citation.CitationSHA256)
		if _, exists := seenReceipts[citation.EvidenceReceiptSHA256]; !exists {
			receiptHashes = append(receiptHashes, citation.EvidenceReceiptSHA256)
			seenReceipts[citation.EvidenceReceiptSHA256] = struct{}{}
		}
	}
	if !reflect.DeepEqual(payload.Reference.CitationSHA256s, citationHashes) ||
		!reflect.DeepEqual(payload.Reference.EvidenceReceiptSHA256s, receiptHashes) {
		return ErrEntityPageGraphContract830G1
	}
	if payload.State == "unknown" {
		if payload.ValueSnapshot != nil || payload.DisplayValue != nil || payload.UnknownReason == nil ||
			payload.SourceTypedReason == nil || len(payload.Citations) != 0 {
			return ErrEntityPageGraphContract830G1
		}
		if *payload.UnknownReason != "FIELD_UNKNOWN" && *payload.UnknownReason != "NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS" {
			return ErrEntityPageGraphContract830G1
		}
	} else if (payload.State != "present" && payload.State != "absent_explicitly") ||
		payload.ValueSnapshot == nil || payload.DisplayValue == nil || *payload.ValueSnapshot != *payload.DisplayValue ||
		payload.UnknownReason != nil || payload.SourceTypedReason != nil || len(payload.Citations) == 0 {
		return ErrEntityPageGraphContract830G1
	}
	return nil
}

func validateEntityPageCitation830G1(citation EntityPageExactCitation830G1) error {
	if citation.Contract != "entity-page-exact-citation.830.g1.v1" || citation.PageNumber <= 0 ||
		!entityPageText830G1(citation.CitationID) || !entityPageText830G1(citation.SourceRole) ||
		!entityPageText830G1(citation.SourceRevisionID) || !entityPageText830G1(citation.KnowledgeID) ||
		!entityPageText830G1(citation.ChunkID) || !entityPageText830G1(citation.ParseAttemptID) ||
		!entityPageText830G1(citation.LocatorKind) || !entityPageText830G1(citation.LocatorRef) ||
		!entityPageText830G1(citation.QuoteSnapshot) ||
		citation.BBox.CoordinateSystem != "normalized_0_1e6" ||
		citation.BBox.PageWidth != 1_000_000 || citation.BBox.PageHeight != 1_000_000 ||
		citation.BBox.X0 < 0 || citation.BBox.Y0 < 0 ||
		citation.BBox.X0 >= citation.BBox.X1 || citation.BBox.Y0 >= citation.BBox.Y1 ||
		citation.BBox.X1 > citation.BBox.PageWidth || citation.BBox.Y1 > citation.BBox.PageHeight {
		return ErrEntityPageGraphContract830G1
	}
	for _, hash := range []string{
		citation.JoinReceiptSHA256, citation.EvidenceReceiptSHA256, citation.SourceSHA256,
		citation.ParsedDocumentSHA256, citation.ParseManifestSHA256, citation.LocatorContentSHA256,
		citation.QuoteSHA256, citation.CitationSHA256,
	} {
		if !validSchemaWikiSHA256(hash) {
			return ErrEntityPageGraphContract830G1
		}
	}
	quoteDigest, _, err := entityPageSHA256830G1("schema-wiki-text.v1", map[string]string{"text": citation.QuoteSnapshot})
	citationDigest, _, citationErr := entityPageHashWithout830G1(citation.Contract, citation, "citation_sha256")
	if err != nil || citationErr != nil || quoteDigest != citation.QuoteSHA256 || citationDigest != citation.CitationSHA256 {
		return ErrEntityPageGraphContract830G1
	}
	return nil
}

func entityPageReferencesMatchOrder830G1(
	references []EntityPageFieldAssertionReference830G1,
	fieldOrder []string,
	canonical map[string]EntityPageFieldAssertionReference830G1,
) bool {
	if len(references) != len(fieldOrder) {
		return false
	}
	for index, fieldKey := range fieldOrder {
		if !reflect.DeepEqual(references[index], canonical[fieldKey]) {
			return false
		}
	}
	return true
}

func entityPageCitationAuthorityClosed830G1(
	manifest EntityPageManifest830G1,
	fields map[string]EntityPageFieldAssertionPayload830G1,
) bool {
	authorities := map[string]struct{}{}
	for _, source := range manifest.InputAuthority.SourceAuthorities {
		key := strings.Join([]string{
			source.SourceRole, source.SourceSHA256, source.KnowledgeID, source.RevisionSourceID,
			source.EvidenceParseAttemptID, source.ParsedDocumentSHA256, source.ParseManifestSHA256,
		}, "\x00")
		if _, duplicate := authorities[key]; duplicate {
			return false
		}
		authorities[key] = struct{}{}
	}
	for _, field := range fields {
		for _, citation := range field.Citations {
			key := strings.Join([]string{
				citation.SourceRole, citation.SourceSHA256, citation.KnowledgeID, citation.SourceRevisionID,
				citation.ParseAttemptID, citation.ParsedDocumentSHA256, citation.ParseManifestSHA256,
			}, "\x00")
			if _, exists := authorities[key]; !exists {
				return false
			}
		}
	}
	return true
}

func entityPageNamespace830G1(member EntityPageMember830G1) string {
	kind := member.PageKind
	if kind == "free_wiki" {
		kind = "free-wiki"
	}
	return fmt.Sprintf("urn:jlx:wiki:%s:entity:%s:%s:%s", member.SpaceID, member.EntityID, kind, member.StableKey)
}

func entityPageRoute830G1(member EntityPageMember830G1) string {
	base := fmt.Sprintf("/platform/knowledge-bases/%s/schema-wiki/entities/%s", member.WikiKBID, member.EntityID)
	switch member.PageKind {
	case "overview":
		return base + "/overview"
	case "section":
		return base + "/sections/" + member.StableKey
	case "field":
		return base + "/fields/" + member.StableKey
	case "free_wiki":
		return base + "/free-wiki"
	default:
		return ""
	}
}

// entityPageSHA256830G1 mirrors the frozen Python canonicalizer. encoding/json
// intentionally escapes U+2028 and U+2029 even with HTML escaping disabled,
// while the cross-language contract keeps both code points as UTF-8.
func entityPageSHA256830G1(objectType string, payload any) (string, []byte, error) {
	if strings.TrimSpace(objectType) == "" || schemaWikiHasControlCharacter(objectType) {
		return "", nil, ErrEntityPageGraphContract830G1
	}
	canonical, err := schemaWikiCanonicalJSON(payload)
	if err != nil {
		return "", nil, err
	}
	canonical = entityPageUnescapeLineSeparators830G1(canonical)
	preimage := append([]byte(schemaWikiHashPrefix), []byte(objectType)...)
	preimage = append(preimage, 0)
	preimage = append(preimage, canonical...)
	sum := sha256.Sum256(preimage)
	return hex.EncodeToString(sum[:]), preimage, nil
}

func entityPageHashWithout830G1(objectType string, value any, hashKey string) (string, []byte, error) {
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
	return entityPageSHA256830G1(objectType, payload)
}

func entityPageUnescapeLineSeparators830G1(encoded []byte) []byte {
	result := make([]byte, 0, len(encoded))
	for index := 0; index < len(encoded); index++ {
		if encoded[index] != '\\' || index+5 >= len(encoded) || encoded[index+1] != 'u' ||
			(string(encoded[index+2:index+6]) != "2028" && string(encoded[index+2:index+6]) != "2029") {
			result = append(result, encoded[index])
			continue
		}
		slashes := 1
		for previous := index - 1; previous >= 0 && encoded[previous] == '\\'; previous-- {
			slashes++
		}
		if slashes%2 == 0 {
			result = append(result, encoded[index])
			continue
		}
		if encoded[index+5] == '8' {
			result = append(result, []byte("\u2028")...)
		} else {
			result = append(result, []byte("\u2029")...)
		}
		index += 5
	}
	return result
}

func entityPageText830G1(value string) bool {
	return value != "" && strings.TrimSpace(value) == value &&
		norm.NFC.IsNormalString(value) && !schemaWikiHasControlCharacter(value)
}
