package repository

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"strings"
	"unicode"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/google/uuid"
	"golang.org/x/text/unicode/norm"
)

const SchemaWikiFormalCandidatePreviewManifestEnv = "WEKNORA_SCHEMA_WIKI_C5_INPUT_MANIFEST"

const (
	schemaWikiC5BundleContract  = "schema-wiki-formal-candidate-preview-bundle.815.v1"
	schemaWikiC5PreviewContract = "schema-wiki-formal-candidate-preview.815.v1"
	schemaWikiC5HashDomain      = "weknora.schema-wiki-c5.815.v1"
)

var (
	ErrSchemaWikiFormalCandidatePreviewNotFound        = errors.New("schema wiki formal candidate preview not found")
	ErrSchemaWikiFormalCandidatePreviewBindingMismatch = errors.New("schema wiki formal candidate preview binding mismatch")
	c5DecimalPattern                                   = regexp.MustCompile(`^-?(0|[1-9][0-9]*)(\.[0-9]+)?$`)
)

var schemaWikiC5LegacyMemberNames = []string{
	"preview.json", "formal-candidate.json", "coordinate-evidence-companion.json", "terminal.json",
	"field-attempt-manifest.json", "formal-derivation-validation.json", "result-manifest.json",
	"revision-set.json", "terms.manifest.json", "terms.pdf", "brochure.manifest.json",
	"brochure.pdf", "rate_table.manifest.json", "rate_table.pdf",
}

var schemaWikiC5EvidenceAuthorityMemberNames = []string{
	"preview.json", "formal-candidate.json", "coordinate-evidence-companion.json",
	"candidate-evidence-authority.json", "terminal.json", "field-attempt-manifest.json",
	"formal-derivation-validation.json", "result-manifest.json", "revision-set.json",
	"terms.manifest.json", "terms.pdf", "brochure.manifest.json", "brochure.pdf",
	"rate_table.manifest.json", "rate_table.pdf",
}

var schemaWikiC5SectionIDs = []string{
	"product-overview", "application-and-contract", "renewal-and-pricing",
	"coverage-and-exclusions", "claims-and-reimbursement", "services-and-benefits", "sales-support",
}

var schemaWikiC5SectionNames = []string{
	"产品概览", "投保与合同", "续保与费率", "保障与除外", "理赔与报销", "服务与权益", "销售支持",
}

var schemaWikiC5SourceRoles = []string{"terms", "brochure", "rate_table"}

var schemaWikiC5SelectionKeys = map[string]struct{}{
	"selection_id": {}, "field_id": {}, "source_role": {}, "source_revision_id": {},
	"original_file_sha256": {}, "parse_manifest_sha256": {}, "page_number": {},
	"coordinate_space": {}, "page_width_points": {}, "page_height_points": {},
	"bbox": {}, "rects": {}, "block_id": {}, "span_id": {}, "table_id": {},
	"table_slice_id": {}, "cell_ids": {}, "quote": {}, "quote_sha256": {},
	"page_text_char_start": {}, "page_text_char_end": {},
}

type SchemaWikiFormalCandidatePreviewKey struct {
	KBID            string
	ExperimentID    string
	VersionIdentity string
}

type SchemaWikiFormalCandidatePreviewContentRequest struct {
	FieldID     string
	SelectionID string
}

type SchemaWikiFormalCandidatePreviewContent struct {
	Bytes              []byte
	OriginalFileSHA256 string
}

type SchemaWikiFormalCandidatePreviewRecord struct {
	TenantID          uint64
	KBID              string
	ExperimentID      string
	ManifestSHA256    string
	CandidateSHA256   string
	CompanionSHA256   string
	TerminalSHA256    string
	RevisionSetSHA256 string
	PreviewSHA256     string
	Preview           json.RawMessage
}

type schemaWikiC5ManifestMember struct {
	Name      string `json:"name"`
	SHA256    string `json:"sha256"`
	SizeBytes uint64 `json:"size_bytes"`
}

// schemaWikiC5ManifestWire exists separately so the wire remains an exact,
// closed object while the validated manifest can use ordinary internal state.
type schemaWikiC5ManifestWire struct {
	Contract                             string                       `json:"contract"`
	TenantID                             uint64                       `json:"tenant_id"`
	WikiKBID                             string                       `json:"wiki_kb_id"`
	ExperimentID                         string                       `json:"experiment_id"`
	CandidateSHA256                      string                       `json:"candidate_sha256"`
	CandidateFileSHA256                  string                       `json:"candidate_file_sha256"`
	CompanionSHA256                      string                       `json:"companion_sha256"`
	CompanionFileSHA256                  string                       `json:"companion_file_sha256"`
	CandidateEvidenceAuthoritySHA256     *string                      `json:"candidate_evidence_authority_sha256,omitempty"`
	CandidateEvidenceAuthorityFileSHA256 *string                      `json:"candidate_evidence_authority_file_sha256,omitempty"`
	TerminalSHA256                       string                       `json:"terminal_sha256"`
	TerminalFileSHA256                   string                       `json:"terminal_file_sha256"`
	FieldAttemptManifestSHA256           string                       `json:"field_attempt_manifest_sha256"`
	FormalDerivationValidationSHA256     string                       `json:"formal_derivation_validation_sha256"`
	RevisionSetSHA256                    string                       `json:"revision_set_sha256"`
	QualityStatus                        string                       `json:"quality_status"`
	MVPStatus                            string                       `json:"mvp_status"`
	Publishing                           bool                         `json:"publishing"`
	Members                              []schemaWikiC5ManifestMember `json:"members"`
	ManifestSHA256                       string                       `json:"manifest_sha256"`
}

type schemaWikiC5Product struct {
	EntityID         string `json:"entity_id"`
	EntityVersionID  string `json:"entity_version_id"`
	ProductVersionID string `json:"product_version_id"`
	DisplayName      string `json:"display_name"`
}

type schemaWikiC5Section struct {
	SectionID       string   `json:"section_id"`
	DisplayName     string   `json:"display_name"`
	OrderedFieldIDs []string `json:"ordered_field_ids"`
}

type schemaWikiC5Selection struct {
	SelectionID         string     `json:"selection_id"`
	FieldID             string     `json:"field_id"`
	SourceRole          string     `json:"source_role"`
	SourceRevisionID    string     `json:"source_revision_id"`
	OriginalFileSHA256  string     `json:"original_file_sha256"`
	ParseManifestSHA256 string     `json:"parse_manifest_sha256"`
	PageNumber          uint64     `json:"page_number"`
	CoordinateSpace     string     `json:"coordinate_space"`
	PageWidthPoints     string     `json:"page_width_points"`
	PageHeightPoints    string     `json:"page_height_points"`
	BBox                []string   `json:"bbox"`
	Rects               [][]string `json:"rects"`
	BlockID             *string    `json:"block_id"`
	SpanID              *string    `json:"span_id"`
	TableID             *string    `json:"table_id"`
	TableSliceID        *string    `json:"table_slice_id"`
	CellIDs             []string   `json:"cell_ids"`
	Quote               string     `json:"quote"`
	QuoteSHA256         string     `json:"quote_sha256"`
	PageTextCharStart   *uint64    `json:"page_text_char_start"`
	PageTextCharEnd     *uint64    `json:"page_text_char_end"`
}

type schemaWikiC5Field struct {
	SchemaOrder      uint64                  `json:"schema_order"`
	SectionID        string                  `json:"section_id"`
	FieldID          string                  `json:"field_id"`
	DisplayName      string                  `json:"display_name"`
	State            string                  `json:"state"`
	ValueSnapshot    *string                 `json:"value_snapshot"`
	TypedReason      *string                 `json:"typed_reason"`
	SourceSelections []schemaWikiC5Selection `json:"source_selections"`
}

type schemaWikiC5Preview struct {
	Contract                               string                `json:"contract"`
	ExperimentID                           string                `json:"experiment_id"`
	CandidateSHA256                        string                `json:"candidate_sha256"`
	CompanionSHA256                        string                `json:"companion_sha256"`
	TerminalSHA256                         string                `json:"terminal_sha256"`
	RevisionSetSHA256                      string                `json:"revision_set_sha256"`
	QualityStatus                          string                `json:"quality_status"`
	MVPStatus                              string                `json:"mvp_status"`
	Publishing                             bool                  `json:"publishing"`
	CoordinateSourceRoles                  []string              `json:"coordinate_source_roles"`
	SourceRolesWithoutCoordinateSelections []string              `json:"source_roles_without_coordinate_selections"`
	Product                                schemaWikiC5Product   `json:"product"`
	OrderedSectionIDs                      []string              `json:"ordered_section_ids"`
	Sections                               []schemaWikiC5Section `json:"sections"`
	Fields                                 []schemaWikiC5Field   `json:"fields"`
	PreviewSHA256                          string                `json:"preview_sha256"`
}

type schemaWikiC5SourceRecord struct {
	revisionID string
	fileSHA256 string
	pageCount  uint64
	bytes      []byte
}

type schemaWikiC5SelectionRecord struct {
	fieldID            string
	selectionID        string
	sourceRole         string
	sourceRevisionID   string
	originalFileSHA256 string
	pageNumber         uint64
	quoteSHA256        string
}

type schemaWikiC5StoredRecord struct {
	public                     SchemaWikiFormalCandidatePreviewRecord
	preview                    schemaWikiC5Preview
	selections                 map[string]schemaWikiC5SelectionRecord
	sources                    map[string]schemaWikiC5SourceRecord
	sourceManifests            map[string][]byte
	candidateEvidenceAuthority *types.Schema67CandidateEvidenceAuthorityV1
}

type schemaWikiC5StorageKey struct {
	tenantID uint64
	key      SchemaWikiFormalCandidatePreviewKey
}

// SchemaWikiFormalCandidatePreviewRegistry is fully materialized and sealed at
// construction time. It exposes no discovery or mutable selection API.
type SchemaWikiFormalCandidatePreviewRegistry struct {
	records map[schemaWikiC5StorageKey]schemaWikiC5StoredRecord
}

func NewSchemaWikiFormalCandidatePreviewRegistry(
	manifestPath string,
) (*SchemaWikiFormalCandidatePreviewRegistry, error) {
	registry := &SchemaWikiFormalCandidatePreviewRegistry{
		records: make(map[schemaWikiC5StorageKey]schemaWikiC5StoredRecord, 1),
	}
	if strings.TrimSpace(manifestPath) == "" {
		return registry, nil
	}
	if !filepath.IsAbs(manifestPath) {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	record, err := loadSchemaWikiC5Record(filepath.Clean(manifestPath))
	if err != nil {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	key := schemaWikiC5StorageKey{tenantID: record.public.TenantID, key: SchemaWikiFormalCandidatePreviewKey{
		KBID: record.public.KBID, ExperimentID: record.public.ExperimentID,
		VersionIdentity: record.public.ManifestSHA256,
	}}
	registry.records[key] = record
	return registry, nil
}

func (r *SchemaWikiFormalCandidatePreviewRegistry) ReadExact(
	tenantID uint64,
	key SchemaWikiFormalCandidatePreviewKey,
) (SchemaWikiFormalCandidatePreviewRecord, error) {
	if r == nil || r.records == nil || !validSchemaWikiC5Key(tenantID, key) {
		return SchemaWikiFormalCandidatePreviewRecord{}, ErrSchemaWikiFormalCandidatePreviewNotFound
	}
	record, ok := r.records[schemaWikiC5StorageKey{tenantID: tenantID, key: key}]
	if !ok || !validSchemaWikiC5PublicRecord(record.public, tenantID, key) {
		return SchemaWikiFormalCandidatePreviewRecord{}, ErrSchemaWikiFormalCandidatePreviewNotFound
	}
	return cloneSchemaWikiC5PublicRecord(record.public), nil
}

func (r *SchemaWikiFormalCandidatePreviewRegistry) ReadContentExact(
	tenantID uint64,
	key SchemaWikiFormalCandidatePreviewKey,
	request SchemaWikiFormalCandidatePreviewContentRequest,
) (SchemaWikiFormalCandidatePreviewContent, error) {
	if r == nil || r.records == nil || !validSchemaWikiC5Key(tenantID, key) ||
		!validSchemaWikiC5CanonicalString(request.FieldID) ||
		!validSchemaWikiC5CanonicalString(request.SelectionID) {
		return SchemaWikiFormalCandidatePreviewContent{}, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	record, ok := r.records[schemaWikiC5StorageKey{tenantID: tenantID, key: key}]
	if !ok || !validSchemaWikiC5PublicRecord(record.public, tenantID, key) {
		return SchemaWikiFormalCandidatePreviewContent{}, ErrSchemaWikiFormalCandidatePreviewNotFound
	}
	selection, ok := record.selections[request.SelectionID]
	if !ok || selection.fieldID != request.FieldID || selection.selectionID != request.SelectionID {
		return SchemaWikiFormalCandidatePreviewContent{}, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	source, ok := record.sources[selection.sourceRole]
	if !ok || source.revisionID != selection.sourceRevisionID ||
		source.fileSHA256 != selection.originalFileSHA256 || selection.pageNumber == 0 ||
		selection.pageNumber > source.pageCount || !validSchemaWikiC5SHA256(selection.quoteSHA256) ||
		c5RawSHA256(source.bytes) != source.fileSHA256 {
		return SchemaWikiFormalCandidatePreviewContent{}, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	return SchemaWikiFormalCandidatePreviewContent{
		Bytes: append([]byte(nil), source.bytes...), OriginalFileSHA256: source.fileSHA256,
	}, nil
}

// ReadNativeSourceExact returns the exact, already-validated RevisionSet role
// manifest and source PDF. The pair comes from one sealed C5 record and is
// never resolved through current/latest state.
func (r *SchemaWikiFormalCandidatePreviewRegistry) ReadNativeSourceExact(
	tenantID uint64,
	key SchemaWikiFormalCandidatePreviewKey,
	sourceRole string,
) ([]byte, []byte, error) {
	if r == nil || r.records == nil || !validSchemaWikiC5Key(tenantID, key) ||
		!containsSchemaWikiC5String(schemaWikiC5SourceRoles, sourceRole) {
		return nil, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	record, ok := r.records[schemaWikiC5StorageKey{tenantID: tenantID, key: key}]
	if !ok || !validSchemaWikiC5PublicRecord(record.public, tenantID, key) {
		return nil, nil, ErrSchemaWikiFormalCandidatePreviewNotFound
	}
	manifest, manifestOK := record.sourceManifests[sourceRole]
	source, sourceOK := record.sources[sourceRole]
	if !manifestOK || !sourceOK || len(manifest) == 0 || len(source.bytes) == 0 ||
		c5RawSHA256(source.bytes) != source.fileSHA256 {
		return nil, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	return append([]byte(nil), manifest...), append([]byte(nil), source.bytes...), nil
}

// ReadReleaseMembersExact projects the already-validated C5 preview into the
// one immutable logical R1 member set. It does not consult current/latest and
// it never changes the frozen Candidate bytes.
func (r *SchemaWikiFormalCandidatePreviewRegistry) ReadReleaseMembersExact(
	tenantID uint64,
	key SchemaWikiFormalCandidatePreviewKey,
) ([]types.WikiReleaseMemberSnapshot, error) {
	if r == nil || !validSchemaWikiC5Key(tenantID, key) {
		return nil, ErrSchemaWikiFormalCandidatePreviewNotFound
	}
	record, ok := r.records[schemaWikiC5StorageKey{tenantID: tenantID, key: key}]
	if !ok {
		return nil, ErrSchemaWikiFormalCandidatePreviewNotFound
	}
	members, err := schemaWikiC6ReleaseMembers(record)
	if err != nil {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	return members, nil
}

// ReadCandidateEvidenceAuthorityExact returns the already-frozen original
// Candidate companion. It never derives authority from preview selections or
// caller-provided hashes.
func (r *SchemaWikiFormalCandidatePreviewRegistry) ReadCandidateEvidenceAuthorityExact(
	tenantID uint64,
	key SchemaWikiFormalCandidatePreviewKey,
) (types.Schema67CandidateEvidenceAuthorityV1, error) {
	if r == nil || !validSchemaWikiC5Key(tenantID, key) {
		return types.Schema67CandidateEvidenceAuthorityV1{}, ErrSchemaWikiFormalCandidatePreviewNotFound
	}
	record, ok := r.records[schemaWikiC5StorageKey{tenantID: tenantID, key: key}]
	if !ok || !validSchemaWikiC5PublicRecord(record.public, tenantID, key) {
		return types.Schema67CandidateEvidenceAuthorityV1{}, ErrSchemaWikiFormalCandidatePreviewNotFound
	}
	if record.candidateEvidenceAuthority == nil {
		return types.Schema67CandidateEvidenceAuthorityV1{}, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	clone, ok := cloneSchemaWikiC5EvidenceAuthority(*record.candidateEvidenceAuthority)
	if !ok || !validSchemaWikiC5EvidenceAuthority(clone, record.public.CandidateSHA256) {
		return types.Schema67CandidateEvidenceAuthorityV1{}, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	return clone, nil
}

func schemaWikiC6ReleaseMembers(
	record schemaWikiC5StoredRecord,
) ([]types.WikiReleaseMemberSnapshot, error) {
	if len(record.preview.Sections) != 7 || len(record.preview.Fields) != 67 ||
		record.preview.QualityStatus != "NOT_EVALUATED" ||
		record.preview.MVPStatus != "NOT_ACCEPTED" || record.preview.Publishing {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	members := make([]types.WikiReleaseMemberSnapshot, 0, 75)
	appendMember := func(kind string, logicalSlug string, title string, body any) error {
		payload, err := schemaWikiC5CanonicalJSON(map[string]any{
			"contract":           "schema-wiki-isolated-r1-member.815.v1",
			"candidate_sha256":   record.public.CandidateSHA256,
			"c5_manifest_sha256": record.public.ManifestSHA256,
			"c5_preview_sha256":  record.public.PreviewSHA256,
			"quality_status":     "NOT_EVALUATED",
			"mvp_status":         "NOT_ACCEPTED",
			"production_status":  "NOT_FOR_PRODUCTION",
			"publishing":         false,
			"member_kind":        kind,
			"body":               body,
		})
		if err != nil {
			return err
		}
		members = append(members, types.WikiReleaseMemberSnapshot{
			Kind: kind, LogicalSlug: logicalSlug,
			RevisionID: record.public.ManifestSHA256, MemberDigest: c5RawSHA256(payload),
			Title: title, Content: string(payload), Payload: append(json.RawMessage(nil), payload...),
		})
		return nil
	}
	if err := appendMember(
		"root", "root:"+record.preview.Product.EntityVersionID,
		record.preview.Product.DisplayName, record.preview.Product,
	); err != nil {
		return nil, err
	}
	for _, section := range record.preview.Sections {
		if err := appendMember(
			"section", "section:"+section.SectionID, section.DisplayName, section,
		); err != nil {
			return nil, err
		}
	}
	for _, field := range record.preview.Fields {
		if err := appendMember(
			"field", "field:"+field.FieldID, field.DisplayName, field,
		); err != nil {
			return nil, err
		}
	}
	return members, nil
}

func loadSchemaWikiC5Record(manifestPath string) (schemaWikiC5StoredRecord, error) {
	var empty schemaWikiC5StoredRecord
	manifestRaw, err := readSchemaWikiC5Regular0600(manifestPath)
	if err != nil {
		return empty, err
	}
	var manifest schemaWikiC5ManifestWire
	if !decodeSchemaWikiC5Exact(manifestRaw, &manifest) || !validSchemaWikiC5Manifest(manifest, manifestRaw) {
		return empty, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	memberNames := schemaWikiC5ManifestMemberNames(manifest)
	if memberNames == nil {
		return empty, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	dir := filepath.Dir(manifestPath)
	dirInfo, err := os.Lstat(dir)
	if err != nil || dirInfo.Mode()&os.ModeSymlink != 0 || !dirInfo.IsDir() || dirInfo.Mode().Perm() != 0o700 {
		return empty, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) != len(memberNames)+1 {
		return empty, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	members := make(map[string][]byte, len(memberNames))
	for index, expectedName := range memberNames {
		member := manifest.Members[index]
		if member.Name != expectedName {
			return empty, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
		}
		memberPath := filepath.Join(dir, expectedName)
		raw, readErr := readSchemaWikiC5Regular0600(memberPath)
		if readErr != nil || member.SizeBytes != uint64(len(raw)) || member.SHA256 != c5RawSHA256(raw) {
			return empty, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
		}
		members[expectedName] = raw
	}
	preview, selections, err := validateSchemaWikiC5Preview(members["preview.json"], manifest)
	if err != nil {
		return empty, err
	}
	sources, err := validateSchemaWikiC5Members(manifest, members, preview)
	if err != nil {
		return empty, err
	}
	var evidenceAuthority *types.Schema67CandidateEvidenceAuthorityV1
	if manifest.CandidateEvidenceAuthoritySHA256 != nil {
		var exact types.Schema67CandidateEvidenceAuthorityV1
		raw := members["candidate-evidence-authority.json"]
		if !decodeSchemaWikiC5Exact(raw, &exact) ||
			manifest.CandidateEvidenceAuthorityFileSHA256 == nil ||
			*manifest.CandidateEvidenceAuthorityFileSHA256 != c5RawSHA256(raw) ||
			*manifest.CandidateEvidenceAuthoritySHA256 != exact.AuthoritySHA256 ||
			!validSchemaWikiC5EvidenceAuthority(exact, manifest.CandidateSHA256) {
			return empty, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
		}
		evidenceAuthority = &exact
	}
	sourceManifests := make(map[string][]byte, len(schemaWikiC5SourceRoles))
	for _, role := range schemaWikiC5SourceRoles {
		sourceManifests[role] = append([]byte(nil), members[role+".manifest.json"]...)
	}
	return schemaWikiC5StoredRecord{
		public: SchemaWikiFormalCandidatePreviewRecord{
			TenantID: manifest.TenantID, KBID: manifest.WikiKBID,
			ExperimentID: manifest.ExperimentID, ManifestSHA256: manifest.ManifestSHA256,
			CandidateSHA256: manifest.CandidateSHA256, CompanionSHA256: manifest.CompanionSHA256,
			TerminalSHA256: manifest.TerminalSHA256, RevisionSetSHA256: manifest.RevisionSetSHA256,
			PreviewSHA256: preview.PreviewSHA256, Preview: append(json.RawMessage(nil), members["preview.json"]...),
		}, preview: preview, selections: selections, sources: sources,
		sourceManifests:            sourceManifests,
		candidateEvidenceAuthority: evidenceAuthority,
	}, nil
}

func schemaWikiC5ManifestMemberNames(manifest schemaWikiC5ManifestWire) []string {
	if manifest.CandidateEvidenceAuthoritySHA256 == nil && manifest.CandidateEvidenceAuthorityFileSHA256 == nil {
		return schemaWikiC5LegacyMemberNames
	}
	if manifest.CandidateEvidenceAuthoritySHA256 != nil && manifest.CandidateEvidenceAuthorityFileSHA256 != nil {
		return schemaWikiC5EvidenceAuthorityMemberNames
	}
	return nil
}

func validSchemaWikiC5Manifest(manifest schemaWikiC5ManifestWire, raw []byte) bool {
	memberNames := schemaWikiC5ManifestMemberNames(manifest)
	if manifest.Contract != schemaWikiC5BundleContract || manifest.TenantID == 0 ||
		!validSchemaWikiC5CanonicalString(manifest.WikiKBID) || !validSchemaWikiC5UUID(manifest.ExperimentID) ||
		manifest.QualityStatus != "NOT_EVALUATED" || manifest.MVPStatus != "NOT_ACCEPTED" ||
		manifest.Publishing || memberNames == nil || len(manifest.Members) != len(memberNames) {
		return false
	}
	for _, digest := range []string{
		manifest.CandidateSHA256, manifest.CandidateFileSHA256, manifest.CompanionSHA256,
		manifest.CompanionFileSHA256, manifest.TerminalSHA256, manifest.TerminalFileSHA256,
		manifest.FieldAttemptManifestSHA256, manifest.FormalDerivationValidationSHA256,
		manifest.RevisionSetSHA256, manifest.ManifestSHA256,
	} {
		if !validSchemaWikiC5SHA256(digest) {
			return false
		}
	}
	if manifest.CandidateEvidenceAuthoritySHA256 != nil &&
		(!validSchemaWikiC5SHA256(*manifest.CandidateEvidenceAuthoritySHA256) ||
			!validSchemaWikiC5SHA256(*manifest.CandidateEvidenceAuthorityFileSHA256)) {
		return false
	}
	for index, member := range manifest.Members {
		if member.Name != memberNames[index] || !validSchemaWikiC5SHA256(member.SHA256) ||
			member.SizeBytes == 0 {
			return false
		}
	}
	return validateSchemaWikiC5CanonicalObject(raw, "manifest_sha256", schemaWikiC5BundleContract, manifest.ManifestSHA256)
}

func validSchemaWikiC5EvidenceAuthority(
	authority types.Schema67CandidateEvidenceAuthorityV1,
	candidateSHA256 string,
) bool {
	digest, err := types.ComputeSchema67CandidateEvidenceAuthoritySHA256(authority)
	if err != nil || digest != authority.AuthoritySHA256 ||
		authority.CandidateSHA256 != candidateSHA256 || len(authority.SourceAuthorities) != 3 {
		return false
	}
	expectedRoles := []string{"terms", "brochure", "rate_table"}
	sources := make(map[string]types.Schema67LiveSourceAuthorityV1, 3)
	for index, source := range authority.SourceAuthorities {
		if source.SourceRole != expectedRoles[index] || source.SourceSHA256 != source.LiveRevisionSourceReceipt.FileSHA256 ||
			types.ValidateLiveRevisionSourceReceiptV1(source.LiveRevisionSourceReceipt) != nil {
			return false
		}
		if _, exists := sources[source.SourceSHA256]; exists {
			return false
		}
		sources[source.SourceSHA256] = source
	}
	seen := make(map[string]struct{}, len(authority.JoinReceipts))
	for _, receipt := range authority.JoinReceipts {
		source, exists := sources[receipt.SourceSHA256]
		if !exists || receipt.CandidateSHA256 != candidateSHA256 ||
			receipt.SourceRole != source.SourceRole ||
			types.ValidateSchema67CitationAuthorityJoinReceiptV1(receipt) != nil ||
			!reflect.DeepEqual(receipt.LiveRevisionSourceReceipt, source.LiveRevisionSourceReceipt) {
			return false
		}
		if _, duplicate := seen[receipt.ReceiptSHA256]; duplicate {
			return false
		}
		seen[receipt.ReceiptSHA256] = struct{}{}
	}
	return true
}

func cloneSchemaWikiC5EvidenceAuthority(
	authority types.Schema67CandidateEvidenceAuthorityV1,
) (types.Schema67CandidateEvidenceAuthorityV1, bool) {
	raw, err := json.Marshal(authority)
	if err != nil {
		return types.Schema67CandidateEvidenceAuthorityV1{}, false
	}
	var clone types.Schema67CandidateEvidenceAuthorityV1
	if !decodeSchemaWikiC5Exact(raw, &clone) {
		return types.Schema67CandidateEvidenceAuthorityV1{}, false
	}
	return clone, true
}

func validateSchemaWikiC5Preview(
	raw []byte,
	manifest schemaWikiC5ManifestWire,
) (schemaWikiC5Preview, map[string]schemaWikiC5SelectionRecord, error) {
	var preview schemaWikiC5Preview
	if !schemaWikiC5PreviewSelectionKeysExact(raw) || !decodeSchemaWikiC5Exact(raw, &preview) || preview.Contract != schemaWikiC5PreviewContract ||
		preview.ExperimentID != manifest.ExperimentID || preview.CandidateSHA256 != manifest.CandidateSHA256 ||
		preview.CompanionSHA256 != manifest.CompanionSHA256 || preview.TerminalSHA256 != manifest.TerminalSHA256 ||
		preview.RevisionSetSHA256 != manifest.RevisionSetSHA256 || preview.QualityStatus != manifest.QualityStatus ||
		preview.MVPStatus != manifest.MVPStatus || preview.Publishing || !validSchemaWikiC5SHA256(preview.PreviewSHA256) ||
		!validateSchemaWikiC5CanonicalObject(raw, "preview_sha256", schemaWikiC5PreviewContract, preview.PreviewSHA256) {
		return preview, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	if preview.Product != (schemaWikiC5Product{
		EntityID: "ping-an-e-sheng-bao", EntityVersionID: "ping-an-e-sheng-bao@596-1",
		ProductVersionID: "596-1", DisplayName: "平安e生保（尊享版）医疗保险",
	}) || !reflectStringSliceEqual(preview.OrderedSectionIDs, schemaWikiC5SectionIDs) ||
		len(preview.Sections) != 7 || len(preview.Fields) != 67 {
		return preview, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	flattened := make([]string, 0, 67)
	for index, section := range preview.Sections {
		if section.SectionID != schemaWikiC5SectionIDs[index] || section.DisplayName != schemaWikiC5SectionNames[index] ||
			len(section.OrderedFieldIDs) == 0 {
			return preview, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
		}
		flattened = append(flattened, section.OrderedFieldIDs...)
	}
	if len(flattened) != 67 {
		return preview, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	selections := make(map[string]schemaWikiC5SelectionRecord)
	rolesSeen := make(map[string]bool)
	fieldsSeen := make(map[string]bool, 67)
	for index, field := range preview.Fields {
		if field.SchemaOrder != uint64(index+1) || field.FieldID != flattened[index] ||
			!validSchemaWikiC5CanonicalString(field.FieldID) || !validSchemaWikiC5CanonicalString(field.DisplayName) ||
			!containsSchemaWikiC5String(schemaWikiC5SectionIDs, field.SectionID) {
			return preview, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
		}
		if fieldsSeen[field.FieldID] {
			return preview, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
		}
		fieldsSeen[field.FieldID] = true
		ownerIndex := indexOfSchemaWikiC5String(schemaWikiC5SectionIDs, field.SectionID)
		if ownerIndex < 0 || !containsSchemaWikiC5String(preview.Sections[ownerIndex].OrderedFieldIDs, field.FieldID) ||
			!validSchemaWikiC5FieldState(field) {
			return preview, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
		}
		for _, selection := range field.SourceSelections {
			if !validSchemaWikiC5Selection(selection, field.FieldID) {
				return preview, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
			}
			rolesSeen[selection.SourceRole] = true
			selectionRecord := schemaWikiC5SelectionRecord{
				fieldID: field.FieldID, selectionID: selection.SelectionID, sourceRole: selection.SourceRole,
				sourceRevisionID: selection.SourceRevisionID, originalFileSHA256: selection.OriginalFileSHA256,
				pageNumber: selection.PageNumber, quoteSHA256: selection.QuoteSHA256,
			}
			if existing, exists := selections[selection.SelectionID]; exists {
				if existing.fieldID != selectionRecord.fieldID || existing.sourceRole != selectionRecord.sourceRole ||
					existing.sourceRevisionID != selectionRecord.sourceRevisionID ||
					existing.originalFileSHA256 != selectionRecord.originalFileSHA256 {
					return preview, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
				}
				continue
			}
			selections[selection.SelectionID] = selectionRecord
		}
	}
	wantPresent := make([]string, 0, 3)
	wantMissing := make([]string, 0, 3)
	for _, role := range schemaWikiC5SourceRoles {
		if rolesSeen[role] {
			wantPresent = append(wantPresent, role)
		} else {
			wantMissing = append(wantMissing, role)
		}
	}
	if !reflectStringSliceEqual(preview.CoordinateSourceRoles, wantPresent) ||
		!reflectStringSliceEqual(preview.SourceRolesWithoutCoordinateSelections, wantMissing) {
		return preview, nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	return preview, selections, nil
}

func validateSchemaWikiC5Members(
	manifest schemaWikiC5ManifestWire,
	members map[string][]byte,
	preview schemaWikiC5Preview,
) (map[string]schemaWikiC5SourceRecord, error) {
	if manifest.CandidateFileSHA256 != c5RawSHA256(members["formal-candidate.json"]) ||
		manifest.CompanionFileSHA256 != c5RawSHA256(members["coordinate-evidence-companion.json"]) ||
		manifest.TerminalFileSHA256 != c5RawSHA256(members["terminal.json"]) ||
		manifest.FieldAttemptManifestSHA256 != c5RawSHA256(members["field-attempt-manifest.json"]) ||
		manifest.FormalDerivationValidationSHA256 != c5RawSHA256(members["formal-derivation-validation.json"]) {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	for _, check := range []struct {
		name     string
		bindings map[string]string
	}{
		{"formal-candidate.json", map[string]string{"candidate_sha256": manifest.CandidateSHA256}},
		{"coordinate-evidence-companion.json", map[string]string{"candidate_sha256": manifest.CandidateSHA256, "companion_sha256": manifest.CompanionSHA256}},
		{"terminal.json", map[string]string{"experiment_id": manifest.ExperimentID, "terminal_sha256": manifest.TerminalSHA256, "coordinate_evidence_companion_sha256": manifest.CompanionSHA256, "revision_set_sha256": manifest.RevisionSetSHA256, "status": "SUCCEEDED"}},
		{"field-attempt-manifest.json", map[string]string{"experiment_id": manifest.ExperimentID, "terminal_sha256": manifest.TerminalSHA256, "coordinate_evidence_companion_sha256": manifest.CompanionSHA256, "revision_set_sha256": manifest.RevisionSetSHA256}},
		{"formal-derivation-validation.json", map[string]string{"terminal_sha256": manifest.TerminalSHA256, "status": "PASS"}},
	} {
		if !schemaWikiC5JSONHasBindings(members[check.name], check.bindings) {
			return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
		}
	}
	if !schemaWikiC5JSONHasPathBindings(members["result-manifest.json"], map[string]string{
		"identities.experiment_id":                         manifest.ExperimentID,
		"candidate.candidate_internal_sha256":              manifest.CandidateSHA256,
		"candidate.candidate_external_sha256":              manifest.CandidateFileSHA256,
		"candidate.coordinate_companion_internal_sha256":   manifest.CompanionSHA256,
		"candidate.coordinate_companion_external_sha256":   manifest.CompanionFileSHA256,
		"candidate.field_attempt_manifest_external_sha256": manifest.FieldAttemptManifestSHA256,
		"candidate.derivation_validation_external_sha256":  manifest.FormalDerivationValidationSHA256,
		"terminal.internal_sha256":                         manifest.TerminalSHA256,
		"terminal.status":                                  "SUCCEEDED",
	}) {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	var fieldManifest map[string]any
	var derivation map[string]any
	if !decodeSchemaWikiC5Map(members["field-attempt-manifest.json"], &fieldManifest) ||
		!decodeSchemaWikiC5Map(members["formal-derivation-validation.json"], &derivation) ||
		fieldManifest["manifest_sha256"] != derivation["manifest_sha256"] {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	var revisionSet struct {
		Contract          string   `json:"contract"`
		TenantID          uint64   `json:"tenant_id"`
		KnowledgeBaseID   string   `json:"knowledge_base_id"`
		OrderedRoles      []string `json:"ordered_roles"`
		RevisionSetSHA256 string   `json:"revision_set_sha256"`
		Items             []struct {
			Role               string `json:"role"`
			ManifestFile       string `json:"manifest_file"`
			ManifestFileSHA256 string `json:"manifest_file_sha256"`
			MaterialFile       string `json:"material_file"`
			MaterialFileSHA256 string `json:"material_file_sha256"`
		} `json:"items"`
	}
	if json.Unmarshal(members["revision-set.json"], &revisionSet) != nil || revisionSet.TenantID != manifest.TenantID ||
		revisionSet.KnowledgeBaseID != manifest.WikiKBID || revisionSet.RevisionSetSHA256 != manifest.RevisionSetSHA256 ||
		!reflectStringSliceEqual(revisionSet.OrderedRoles, schemaWikiC5SourceRoles) || len(revisionSet.Items) != 3 {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	sources := make(map[string]schemaWikiC5SourceRecord, 3)
	for index, role := range schemaWikiC5SourceRoles {
		item := revisionSet.Items[index]
		manifestName := role + ".manifest.json"
		pdfName := role + ".pdf"
		if item.Role != role || item.ManifestFile != manifestName || item.MaterialFile != pdfName ||
			item.ManifestFileSHA256 != c5RawSHA256(members[manifestName]) ||
			item.MaterialFileSHA256 != c5RawSHA256(members[pdfName]) {
			return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
		}
		var source struct {
			Role                     string `json:"role"`
			TenantID                 uint64 `json:"tenant_id"`
			KnowledgeBaseID          string `json:"knowledge_base_id"`
			CompilerSourceRevisionID string `json:"compiler_source_revision_id"`
			FileSHA256               string `json:"file_sha256"`
			FileSize                 uint64 `json:"file_size"`
			MaterialFile             string `json:"material_file"`
			PageCount                uint64 `json:"page_count"`
		}
		if json.Unmarshal(members[manifestName], &source) != nil || source.Role != role ||
			source.TenantID != manifest.TenantID || source.KnowledgeBaseID != manifest.WikiKBID ||
			source.MaterialFile != pdfName || source.FileSHA256 != c5RawSHA256(members[pdfName]) ||
			source.FileSize != uint64(len(members[pdfName])) || source.PageCount == 0 ||
			!validSchemaWikiC5SHA256(source.CompilerSourceRevisionID) {
			return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
		}
		sources[role] = schemaWikiC5SourceRecord{revisionID: source.CompilerSourceRevisionID, fileSHA256: source.FileSHA256, pageCount: source.PageCount, bytes: append([]byte(nil), members[pdfName]...)}
	}
	for _, field := range preview.Fields {
		for _, selection := range field.SourceSelections {
			source := sources[selection.SourceRole]
			if source.revisionID != selection.SourceRevisionID || source.fileSHA256 != selection.OriginalFileSHA256 ||
				selection.PageNumber > source.pageCount {
				return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
			}
		}
	}
	return sources, nil
}

func validSchemaWikiC5FieldState(field schemaWikiC5Field) bool {
	switch field.State {
	case "present":
		return field.ValueSnapshot != nil && validSchemaWikiC5CanonicalString(*field.ValueSnapshot) &&
			field.TypedReason == nil && len(field.SourceSelections) > 0
	case "absent":
		return field.ValueSnapshot != nil && validSchemaWikiC5CanonicalString(*field.ValueSnapshot) &&
			field.TypedReason == nil && len(field.SourceSelections) > 0
	case "unknown":
		return field.ValueSnapshot == nil && field.TypedReason != nil &&
			validSchemaWikiC5CanonicalString(*field.TypedReason) && len(field.SourceSelections) == 0
	default:
		return false
	}
}

func validSchemaWikiC5Selection(selection schemaWikiC5Selection, fieldID string) bool {
	if !validSchemaWikiC5CanonicalString(selection.SelectionID) || selection.FieldID != fieldID ||
		!containsSchemaWikiC5String(schemaWikiC5SourceRoles, selection.SourceRole) ||
		!validSchemaWikiC5SHA256(selection.SourceRevisionID) || !validSchemaWikiC5SHA256(selection.OriginalFileSHA256) ||
		!validSchemaWikiC5SHA256(selection.ParseManifestSHA256) || selection.PageNumber == 0 ||
		selection.CoordinateSpace != "PDF_POINTS_TOP_LEFT_V1" || !validSchemaWikiC5PositiveDecimal(selection.PageWidthPoints) ||
		!validSchemaWikiC5PositiveDecimal(selection.PageHeightPoints) || len(selection.Rects) == 0 ||
		len(selection.BBox) != 4 ||
		selection.Quote == "" || !norm.NFC.IsNormalString(selection.Quote) || hasSchemaWikiC5Control(selection.Quote) ||
		selection.QuoteSHA256 != c5RawSHA256([]byte(selection.Quote)) {
		return false
	}
	for _, value := range selection.BBox {
		if !validSchemaWikiC5Decimal(value) {
			return false
		}
	}
	for _, rect := range selection.Rects {
		if len(rect) != 4 {
			return false
		}
		for _, value := range rect {
			if !validSchemaWikiC5Decimal(value) {
				return false
			}
		}
	}
	for _, optional := range []*string{selection.BlockID, selection.SpanID, selection.TableID, selection.TableSliceID} {
		if optional != nil && !validSchemaWikiC5CanonicalString(*optional) {
			return false
		}
	}
	for _, cellID := range selection.CellIDs {
		if !validSchemaWikiC5CanonicalString(cellID) {
			return false
		}
	}
	if selection.BlockID != nil || selection.SpanID != nil {
		return selection.BlockID != nil && selection.SpanID != nil && selection.TableID == nil &&
			selection.TableSliceID == nil && selection.PageTextCharStart != nil &&
			selection.PageTextCharEnd != nil && *selection.PageTextCharStart < *selection.PageTextCharEnd
	}
	return selection.TableID != nil && selection.TableSliceID != nil && selection.PageTextCharStart == nil &&
		selection.PageTextCharEnd == nil
}

// schemaWikiC5PreviewSelectionKeysExact distinguishes an omitted nullable
// source field from an explicit JSON null before typed decoding loses it.
func schemaWikiC5PreviewSelectionKeysExact(raw []byte) bool {
	var preview map[string]json.RawMessage
	if !decodeSchemaWikiC5Exact(raw, &preview) {
		return false
	}
	fieldsRaw, ok := preview["fields"]
	if !ok {
		return false
	}
	var fields []map[string]json.RawMessage
	if json.Unmarshal(fieldsRaw, &fields) != nil {
		return false
	}
	for _, field := range fields {
		sourcesRaw, ok := field["source_selections"]
		if !ok {
			return false
		}
		var sources []map[string]json.RawMessage
		if json.Unmarshal(sourcesRaw, &sources) != nil {
			return false
		}
		for _, source := range sources {
			if len(source) != len(schemaWikiC5SelectionKeys) {
				return false
			}
			for key := range source {
				if _, ok := schemaWikiC5SelectionKeys[key]; !ok {
					return false
				}
			}
		}
	}
	return true
}

func validateSchemaWikiC5CanonicalObject(raw []byte, selfKey, objectType, want string) bool {
	var value map[string]any
	if !decodeSchemaWikiC5Map(raw, &value) || value[selfKey] != want {
		return false
	}
	canonicalWithSelf, err := schemaWikiC5CanonicalJSON(value)
	if err != nil || !bytes.Equal(raw, canonicalWithSelf) {
		return false
	}
	delete(value, selfKey)
	return c5ObjectSHA256(objectType, value) == want
}

func c5ObjectSHA256(objectType string, value map[string]any) string {
	canonical, err := schemaWikiC5CanonicalJSON(value)
	if err != nil {
		return ""
	}
	preimage := append([]byte(schemaWikiC5HashDomain+"\x00"+objectType+"\x00"), canonical...)
	return c5RawSHA256(preimage)
}

func schemaWikiC5CanonicalJSON(value any) ([]byte, error) {
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(value); err != nil {
		return nil, err
	}
	canonical := bytes.TrimSuffix(buffer.Bytes(), []byte("\n"))
	return restoreSchemaWikiC5LineSeparators(canonical), nil
}

func restoreSchemaWikiC5LineSeparators(canonical []byte) []byte {
	out := make([]byte, 0, len(canonical))
	for index := 0; index < len(canonical); {
		if canonical[index] != '\\' {
			out = append(out, canonical[index])
			index++
			continue
		}
		start := index
		for index < len(canonical) && canonical[index] == '\\' {
			index++
		}
		if (index-start)%2 == 1 {
			switch {
			case bytes.HasPrefix(canonical[index:], []byte("u2028")):
				out = append(out, canonical[start:index-1]...)
				out = append(out, "\u2028"...)
				index += len("u2028")
				continue
			case bytes.HasPrefix(canonical[index:], []byte("u2029")):
				out = append(out, canonical[start:index-1]...)
				out = append(out, "\u2029"...)
				index += len("u2029")
				continue
			}
		}
		out = append(out, canonical[start:index]...)
	}
	return out
}

func c5RawSHA256(raw []byte) string {
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

func decodeSchemaWikiC5Exact(raw []byte, target any) bool {
	if !schemaWikiC5HasUniqueObjectKeys(raw) {
		return false
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	decoder.UseNumber()
	if decoder.Decode(target) != nil {
		return false
	}
	var trailing any
	return errors.Is(decoder.Decode(&trailing), io.EOF)
}

func decodeSchemaWikiC5Map(raw []byte, target *map[string]any) bool {
	if !schemaWikiC5HasUniqueObjectKeys(raw) {
		return false
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if decoder.Decode(target) != nil || *target == nil {
		return false
	}
	var trailing any
	return errors.Is(decoder.Decode(&trailing), io.EOF)
}

func schemaWikiC5HasUniqueObjectKeys(raw []byte) bool {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var walk func() bool
	walk = func() bool {
		token, err := decoder.Token()
		if err != nil {
			return false
		}
		delim, ok := token.(json.Delim)
		if !ok {
			return true
		}
		switch delim {
		case '{':
			keys := make(map[string]struct{})
			for decoder.More() {
				keyToken, keyErr := decoder.Token()
				key, keyOK := keyToken.(string)
				if keyErr != nil || !keyOK {
					return false
				}
				if _, exists := keys[key]; exists {
					return false
				}
				keys[key] = struct{}{}
				if !walk() {
					return false
				}
			}
			end, endErr := decoder.Token()
			return endErr == nil && end == json.Delim('}')
		case '[':
			for decoder.More() {
				if !walk() {
					return false
				}
			}
			end, endErr := decoder.Token()
			return endErr == nil && end == json.Delim(']')
		default:
			return false
		}
	}
	if !walk() {
		return false
	}
	var trailing any
	return errors.Is(decoder.Decode(&trailing), io.EOF)
}

func schemaWikiC5JSONHasBindings(raw []byte, bindings map[string]string) bool {
	var value map[string]any
	if !decodeSchemaWikiC5Map(raw, &value) {
		return false
	}
	for key, want := range bindings {
		got, ok := value[key].(string)
		if !ok || got != want {
			return false
		}
	}
	return true
}

func schemaWikiC5JSONHasPathBindings(raw []byte, bindings map[string]string) bool {
	var value map[string]any
	if !decodeSchemaWikiC5Map(raw, &value) {
		return false
	}
	for path, want := range bindings {
		var current any = value
		for _, key := range strings.Split(path, ".") {
			object, ok := current.(map[string]any)
			if !ok {
				return false
			}
			current, ok = object[key]
			if !ok {
				return false
			}
		}
		got, ok := current.(string)
		if !ok || got != want {
			return false
		}
	}
	return true
}

func readSchemaWikiC5Regular0600(path string) ([]byte, error) {
	info, err := os.Lstat(path)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || info.Mode().Perm() != 0o600 {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !os.SameFile(info, opened) {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	raw, err := io.ReadAll(file)
	if err != nil || len(raw) == 0 {
		return nil, ErrSchemaWikiFormalCandidatePreviewBindingMismatch
	}
	return raw, nil
}

func validSchemaWikiC5Key(tenantID uint64, key SchemaWikiFormalCandidatePreviewKey) bool {
	return tenantID > 0 && validSchemaWikiC5CanonicalString(key.KBID) &&
		validSchemaWikiC5UUID(key.ExperimentID) && validSchemaWikiC5SHA256(key.VersionIdentity)
}

func validSchemaWikiC5PublicRecord(record SchemaWikiFormalCandidatePreviewRecord, tenantID uint64, key SchemaWikiFormalCandidatePreviewKey) bool {
	return record.TenantID == tenantID && record.KBID == key.KBID && record.ExperimentID == key.ExperimentID &&
		record.ManifestSHA256 == key.VersionIdentity && validSchemaWikiC5SHA256(record.CandidateSHA256) &&
		validSchemaWikiC5SHA256(record.CompanionSHA256) && validSchemaWikiC5SHA256(record.TerminalSHA256) &&
		validSchemaWikiC5SHA256(record.RevisionSetSHA256) && validSchemaWikiC5SHA256(record.PreviewSHA256) &&
		len(record.Preview) > 0
}

func cloneSchemaWikiC5PublicRecord(record SchemaWikiFormalCandidatePreviewRecord) SchemaWikiFormalCandidatePreviewRecord {
	record.Preview = append(json.RawMessage(nil), record.Preview...)
	return record
}

func validSchemaWikiC5SHA256(value string) bool {
	if len(value) != 64 || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}

func validSchemaWikiC5UUID(value string) bool {
	parsed, err := uuid.Parse(value)
	return err == nil && parsed.String() == value
}

func validSchemaWikiC5CanonicalString(value string) bool {
	return value != "" && strings.TrimSpace(value) == value && norm.NFC.IsNormalString(value) &&
		!hasSchemaWikiC5Control(value)
}

func hasSchemaWikiC5Control(value string) bool {
	for _, r := range value {
		if unicode.IsControl(r) {
			return true
		}
	}
	return false
}

func validSchemaWikiC5Decimal(value string) bool {
	return c5DecimalPattern.MatchString(value) && value != "-0"
}

func validSchemaWikiC5PositiveDecimal(value string) bool {
	return validSchemaWikiC5Decimal(value) && !strings.HasPrefix(value, "-") && value != "0"
}

func containsSchemaWikiC5String(values []string, target string) bool {
	return indexOfSchemaWikiC5String(values, target) >= 0
}

func indexOfSchemaWikiC5String(values []string, target string) int {
	for index, value := range values {
		if value == target {
			return index
		}
	}
	return -1
}

func reflectStringSliceEqual(left, right []string) bool {
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
