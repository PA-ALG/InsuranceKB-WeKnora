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
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"golang.org/x/text/unicode/norm"
)

var ErrConceptCandidateBundle830G3 = errors.New("invalid concept candidate bundle 830 g3")

const (
	conceptBatchContract830G3 = "batch-concept-candidate-bundle.830.g3.v1"
	conceptBatchRequest830G3  = "batch-concept-compile-request.830.g3.v1"
	conceptBatchBaseRelease   = "release-9cb493e3-8d27-4a0f-8f29-93e2a078725b"
	conceptBatchBaseMembers   = "260247295fb8530ca298f350d9127f21e412f8155371babc8915c86dc52c7475"
)

type SchemaFieldDefinition830G3 struct {
	FieldKey               string  `json:"field_key"`
	ShortTitle             string  `json:"short_title"`
	SchemaCategory         string  `json:"schema_category"`
	ValueSpec              *string `json:"value_spec"`
	Description            *string `json:"description"`
	SourceGuidance         *string `json:"source_guidance"`
	FormationMethod        *string `json:"formation_method"`
	KnowledgeRole          *string `json:"knowledge_role"`
	CommonFieldMarker      *string `json:"common_field_marker"`
	OtherApplicableProduct *string `json:"other_applicable_products"`
	UsageFrequency         int64   `json:"usage_frequency"`
	SourceRow              int64   `json:"source_row"`
	SemanticSHA256         string  `json:"semantic_sha256"`
}

type SchemaPresentationProfileRef830G3 struct {
	ProfileID      string `json:"profile_id"`
	ProfileVersion string `json:"profile_version"`
}

type SchemaPackDefinition830G3 struct {
	Contract                  string                            `json:"contract"`
	SchemaPackID              string                            `json:"schema_pack_id"`
	SchemaVersion             string                            `json:"schema_version"`
	DisplayName               string                            `json:"display_name"`
	EntityType                string                            `json:"entity_type"`
	ApplicableClassifications []string                          `json:"applicable_classifications"`
	WorkbookSHA256            string                            `json:"workbook_sha256"`
	WorkbookSheet             string                            `json:"workbook_sheet"`
	Fields                    []SchemaFieldDefinition830G3      `json:"fields"`
	PresentationProfileRef    SchemaPresentationProfileRef830G3 `json:"presentation_profile_ref"`
	SchemaPackSHA256          string                            `json:"schema_pack_sha256"`
}

type SchemaPackCatalogEntry830G3 struct {
	Pack                      SchemaPackDefinition830G3          `json:"pack"`
	Profile                   EntityPagePresentationProfile830G1 `json:"profile"`
	ProfileConfirmationStatus string                             `json:"profile_confirmation_status"`
	QualityStatus             string                             `json:"quality_status"`
}

type SchemaPackCatalog830G3 struct {
	Contract                   string                        `json:"contract"`
	CatalogID                  string                        `json:"catalog_id"`
	CatalogVersion             string                        `json:"catalog_version"`
	WorkbookSHA256             string                        `json:"workbook_sha256"`
	MappingConfigSHA256        string                        `json:"mapping_config_sha256"`
	Entries                    []SchemaPackCatalogEntry830G3 `json:"entries"`
	FieldNameUnionCount        int                           `json:"field_name_union_count"`
	FieldNameIntersectionCount int                           `json:"field_name_intersection_count"`
	CatalogSHA256              string                        `json:"catalog_sha256"`
}

type ProfileConfirmationIdentity830G3 struct {
	ProfileID      string `json:"profile_id"`
	ProfileVersion string `json:"profile_version"`
	ProfileSHA256  string `json:"profile_sha256"`
}

type CatalogProfileConfirmationReceipt830G3 struct {
	Contract             string                             `json:"contract"`
	ConfirmedAtRecorded  string                             `json:"confirmed_at_recorded"`
	Decision             string                             `json:"decision"`
	UserReplyVerbatim    string                             `json:"user_reply_verbatim"`
	Actor                string                             `json:"actor"`
	ActorDisplayName     *string                            `json:"actor_display_name"`
	ConfirmationChannel  string                             `json:"confirmation_channel"`
	ReviewDocument       string                             `json:"review_document"`
	ReviewDocumentSHA256 string                             `json:"review_document_sha256"`
	CatalogSHA256        string                             `json:"catalog_sha256"`
	CatalogWireSHA256    string                             `json:"catalog_wire_sha256"`
	Profiles             []ProfileConfirmationIdentity830G3 `json:"profiles"`
	Scope                string                             `json:"scope"`
	NotIncluded          []string                           `json:"not_included"`
	QueueOwner           *string                            `json:"queue_owner"`
	IdentityMetadataNote string                             `json:"identity_metadata_note"`
}

type CatalogProfileConfirmationBinding830G3 struct {
	Contract              string                                 `json:"contract"`
	Receipt               CatalogProfileConfirmationReceipt830G3 `json:"receipt"`
	ReceiptFileSHA256     string                                 `json:"receipt_file_sha256"`
	ReceiptSemanticSHA256 string                                 `json:"receipt_semantic_sha256"`
}

type RegisteredSourceReceipt830G3 struct {
	Contract          string `json:"contract"`
	KnowledgeID       string `json:"knowledge_id"`
	ParseAttempt      int64  `json:"parse_attempt"`
	RevisionSourceID  string `json:"revision_source_id"`
	FileSHA256        string `json:"file_sha256"`
	ObjectSHA256      string `json:"object_sha256"`
	Size              int64  `json:"size"`
	MIMEType          string `json:"mime_type"`
	PageCount         int64  `json:"page_count"`
	ManifestAlgorithm string `json:"manifest_algorithm"`
	ManifestDigest    string `json:"manifest_digest"`
	ChunkCount        int64  `json:"chunk_count"`
	BindingDigest     string `json:"binding_digest"`
	RetentionState    string `json:"retention_state"`
}

type LiveRevisionSourceReceipt830G3 struct {
	Contract                 string `json:"contract"`
	RevisionSourceID         string `json:"revision_source_id"`
	TenantID                 uint64 `json:"tenant_id"`
	SpaceID                  string `json:"space_id"`
	RawKBID                  string `json:"raw_kb_id"`
	WikiKBID                 string `json:"wiki_kb_id"`
	KnowledgeID              string `json:"knowledge_id"`
	EvidenceParseAttemptID   string `json:"evidence_parse_attempt_id"`
	WeKnoraParseAttempt      int64  `json:"weknora_parse_attempt"`
	ResourceID               string `json:"resource_id"`
	FileSHA256               string `json:"file_sha256"`
	Size                     int64  `json:"size"`
	MIMEType                 string `json:"mime_type"`
	PageCount                int64  `json:"page_count"`
	ParsedDocumentSHA256     string `json:"parsed_document_sha256"`
	ParseManifestSHA256      string `json:"parse_manifest_sha256"`
	WeKnoraManifestAlgorithm string `json:"weknora_manifest_algorithm"`
	WeKnoraManifestDigest    string `json:"weknora_manifest_digest"`
	WeKnoraChunkCount        int64  `json:"weknora_chunk_count"`
	SourceReceiptSHA256      string `json:"source_receipt_sha256"`
}

type SourceReceipt830G3 struct {
	Contract   string
	Registered *RegisteredSourceReceipt830G3
	Legacy     *LiveRevisionSourceReceipt830G3
}

func (receipt *SourceReceipt830G3) UnmarshalJSON(raw []byte) error {
	var tag struct {
		Contract string `json:"contract"`
	}
	if !conceptJSONUnicodeValid830G2(raw) || !conceptJSONUniqueKeys830G2(raw) ||
		json.Unmarshal(raw, &tag) != nil || tag.Contract == "" {
		return ErrConceptCandidateBundle830G3
	}
	switch tag.Contract {
	case "knowledge-revision-source.v1":
		var value RegisteredSourceReceipt830G3
		if decodeExactObject830G3(raw, &value, registeredReceiptKeys830G3, true) != nil {
			return ErrConceptCandidateBundle830G3
		}
		receipt.Contract, receipt.Registered = tag.Contract, &value
	case "live-revision-source-receipt.v1":
		var value LiveRevisionSourceReceipt830G3
		if decodeExactObject830G3(raw, &value, legacyReceiptKeys830G3, true) != nil {
			return ErrConceptCandidateBundle830G3
		}
		receipt.Contract, receipt.Legacy = tag.Contract, &value
	default:
		return ErrConceptCandidateBundle830G3
	}
	return nil
}

func (receipt SourceReceipt830G3) MarshalJSON() ([]byte, error) {
	if receipt.Registered != nil && receipt.Legacy == nil {
		return json.Marshal(receipt.Registered)
	}
	if receipt.Legacy != nil && receipt.Registered == nil {
		return json.Marshal(receipt.Legacy)
	}
	return nil, ErrConceptCandidateBundle830G3
}

var registeredReceiptKeys830G3 = []string{
	"binding_digest", "chunk_count", "contract", "file_sha256", "knowledge_id",
	"manifest_algorithm", "manifest_digest", "mime_type", "object_sha256", "page_count",
	"parse_attempt", "retention_state", "revision_source_id", "size",
}

var legacyReceiptKeys830G3 = []string{
	"contract", "evidence_parse_attempt_id", "file_sha256", "knowledge_id", "mime_type",
	"page_count", "parse_manifest_sha256", "parsed_document_sha256", "raw_kb_id",
	"resource_id", "revision_source_id", "size", "source_receipt_sha256", "space_id",
	"tenant_id", "weknora_chunk_count", "weknora_manifest_algorithm",
	"weknora_manifest_digest", "weknora_parse_attempt", "wiki_kb_id",
}

type SourceProvenance830G3 struct {
	ProvenanceID             string `json:"provenance_id"`
	Kind                     string `json:"kind"`
	SourceURI                string `json:"source_uri"`
	AcquisitionReceiptSHA256 string `json:"acquisition_receipt_sha256"`
	DeclaredBy               string `json:"declared_by"`
	DeclarationSHA256        string `json:"declaration_sha256"`
}

type CorpusEntry830G3 struct {
	MaterialID           string                    `json:"material_id"`
	Receipt              SourceReceipt830G3        `json:"receipt"`
	NativeCaptureSHA256  string                    `json:"native_capture_sha256"`
	ParserIdentitySHA256 string                    `json:"parser_identity_sha256"`
	Blocks               []ConceptSourceBlock830G2 `json:"blocks"`
	Provenance           SourceProvenance830G3     `json:"provenance"`
	EntrySHA256          string                    `json:"entry_sha256"`
}

type BatchCorpus830G3 struct {
	Contract     string             `json:"contract"`
	TenantID     uint64             `json:"tenant_id"`
	SpaceID      string             `json:"space_id"`
	RawKBID      string             `json:"raw_kb_id"`
	WikiKBID     string             `json:"wiki_kb_id"`
	Entries      []CorpusEntry830G3 `json:"entries"`
	CorpusSHA256 string             `json:"corpus_sha256"`
}

type BatchResolutionInputs830G3 struct {
	Contract         string           `json:"contract"`
	Corpus           BatchCorpus830G3 `json:"corpus"`
	Proposals        json.RawMessage  `json:"proposals"`
	ExistingEntities json.RawMessage  `json:"existing_entities"`
	Policy           json.RawMessage  `json:"policy"`
	InputsSHA256     string           `json:"inputs_sha256"`
}

type ObservedNormalizedValue830G3 struct {
	ObservedValue   string `json:"observed_value"`
	NormalizedValue string `json:"normalized_value"`
}

type VersionAnchor830G3 struct {
	Kind  string `json:"kind"`
	Value string `json:"value"`
}

type EntityIdentityAnchors830G3 struct {
	Issuer        *ObservedNormalizedValue830G3 `json:"issuer"`
	Name          *ObservedNormalizedValue830G3 `json:"name"`
	ProductCode   *ObservedNormalizedValue830G3 `json:"product_code"`
	VersionLabel  *ObservedNormalizedValue830G3 `json:"version_label"`
	VersionAnchor *CandidateVersionAnchor830G3  `json:"version_anchor"`
}

type ModelIdentity830G3 struct {
	Provider      string `json:"provider"`
	DeploymentID  string `json:"deployment_id"`
	Family        string `json:"family"`
	Role          string `json:"role"`
	PolicyVersion string `json:"policy_version"`
}

type ModelPermitView830G3 struct {
	Identity              ModelIdentity830G3 `json:"identity"`
	Purpose               string             `json:"purpose"`
	RunSchemaVersion      string             `json:"run_schema_version"`
	SpaceID               string             `json:"space_id"`
	RunID                 string             `json:"run_id"`
	RunRevision           string             `json:"run_revision"`
	AdmissionHash         string             `json:"admission_hash"`
	VerifiedBindingDigest string             `json:"verified_binding_digest"`
	TemplateHash          string             `json:"template_hash"`
	ModelPlanHash         string             `json:"model_plan_hash"`
	PolicySnapshotDigest  string             `json:"policy_snapshot_digest"`
	CallScopeHash         string             `json:"call_scope_hash"`
	ExpiresAt             string             `json:"expires_at"`
}

type ModelPolicyReceipt830G3 struct {
	Decision               string                `json:"decision"`
	ReasonCode             string                `json:"reason_code"`
	IdentityKey            []string              `json:"identity_key"`
	Purpose                string                `json:"purpose"`
	RunSchemaVersion       string                `json:"run_schema_version"`
	SpaceID                string                `json:"space_id"`
	RunID                  string                `json:"run_id"`
	RunRevision            string                `json:"run_revision"`
	AdmissionHash          string                `json:"admission_hash"`
	RequestDigest          string                `json:"request_digest"`
	BindingDigest          string                `json:"binding_digest"`
	VerifiedBindingDigest  string                `json:"verified_binding_digest"`
	TemplateHash           string                `json:"template_hash"`
	ModelPlanHash          string                `json:"model_plan_hash"`
	CallScopeHash          string                `json:"call_scope_hash"`
	AttemptedContextDigest string                `json:"attempted_context_digest"`
	PolicySnapshotDigest   string                `json:"policy_snapshot_digest"`
	PermitDigest           *string               `json:"permit_digest"`
	PermitView             *ModelPermitView830G3 `json:"permit_view"`
	EvaluatedAt            string                `json:"evaluated_at"`
}

type MaterialBinding830G3 struct {
	MaterialID        string `json:"material_id"`
	CorpusEntrySHA256 string `json:"corpus_entry_sha256"`
}

type ModelReceiptBinding830G3 struct {
	PolicyReceipt          ModelPolicyReceipt830G3 `json:"policy_receipt"`
	MaterialBindings       []MaterialBinding830G3  `json:"material_bindings"`
	RequestSHA256          string                  `json:"request_sha256"`
	InputSHA256            string                  `json:"input_sha256"`
	RawOutputSHA256        string                  `json:"raw_output_sha256"`
	ExecutionReceiptSHA256 string                  `json:"execution_receipt_sha256"`
}

type ProposalEvidence830G3 struct {
	EvidenceID        string               `json:"evidence_id"`
	EntityProposalRef *string              `json:"entity_proposal_ref"`
	Purpose           string               `json:"purpose"`
	FieldKey          *string              `json:"field_key"`
	Evidence          ConceptEvidence830G2 `json:"evidence"`
}

type LabelProposal830G3 struct {
	TaxonomyLabel string   `json:"taxonomy_label"`
	Confidence    string   `json:"confidence"`
	EvidenceIDs   []string `json:"evidence_ids"`
}

type EntityProposal830G3 struct {
	ProposalRef          string               `json:"proposal_ref"`
	Issuer               *string              `json:"issuer"`
	Name                 *string              `json:"name"`
	ProductCode          *string              `json:"product_code"`
	VersionLabel         *string              `json:"version_label"`
	FilingOrRegistration *VersionAnchor830G3  `json:"filing_or_registration"`
	IdentityConfidence   string               `json:"identity_confidence"`
	IdentityEvidenceIDs  []string             `json:"identity_evidence_ids"`
	Labels               []LabelProposal830G3 `json:"labels"`
	PrimaryLabel         string               `json:"primary_label"`
	ValidFrom            *string              `json:"valid_from"`
	ValidThrough         *string              `json:"valid_through"`
}

type MaterialProposal830G3 struct {
	MaterialID              string                  `json:"material_id"`
	CorpusEntrySHA256       string                  `json:"corpus_entry_sha256"`
	ModelRequestSHA256      string                  `json:"model_request_sha256"`
	MaterialRole            string                  `json:"material_role"`
	MaterialRoleEvidenceIDs []string                `json:"material_role_evidence_ids"`
	Entities                []EntityProposal830G3   `json:"entities"`
	Evidence                []ProposalEvidence830G3 `json:"evidence"`
	ProposalSHA256          string                  `json:"proposal_sha256"`
}

type ProposalBatch830G3 struct {
	Contract        string                     `json:"contract"`
	CorpusSHA256    string                     `json:"corpus_sha256"`
	ModelReceipts   []ModelReceiptBinding830G3 `json:"model_receipts"`
	Proposals       []MaterialProposal830G3    `json:"proposals"`
	ProposalsSHA256 string                     `json:"proposals_sha256"`
}

type ApprovedAlias830G3 struct {
	Value                 string `json:"value"`
	ApprovalReceiptSHA256 string `json:"approval_receipt_sha256"`
}

type ExistingEntity830G3 struct {
	EntityID                string               `json:"entity_id"`
	EntityVersion           string               `json:"entity_version"`
	ProductID               *string              `json:"product_id"`
	ProductVersionID        *string              `json:"product_version_id"`
	Issuer                  string               `json:"issuer"`
	Name                    string               `json:"name"`
	ProductCode             string               `json:"product_code"`
	VersionLabel            string               `json:"version_label"`
	FilingOrRegistration    VersionAnchor830G3   `json:"filing_or_registration"`
	ApprovedAliases         []ApprovedAlias830G3 `json:"approved_aliases"`
	IdentityEvidenceSHA256s []string             `json:"identity_evidence_sha256s"`
}

type ExistingEntitySnapshot830G3 struct {
	Contract             string                `json:"contract"`
	TenantID             uint64                `json:"tenant_id"`
	SpaceID              string                `json:"space_id"`
	RawKBID              string                `json:"raw_kb_id"`
	WikiKBID             string                `json:"wiki_kb_id"`
	BaseReleaseID        string                `json:"base_release_id"`
	BaseActivationEpoch  uint64                `json:"base_activation_epoch"`
	HeadReceiptSHA256    string                `json:"head_receipt_sha256"`
	ResolverVersion      string                `json:"resolver_version"`
	ResolverPolicySHA256 string                `json:"resolver_policy_sha256"`
	Entities             []ExistingEntity830G3 `json:"entities"`
	SnapshotSHA256       string                `json:"snapshot_sha256"`
}

type TrustRule830G3 struct {
	RuleID                string   `json:"rule_id"`
	ProvenanceKinds       []string `json:"provenance_kinds"`
	MaterialRoles         []string `json:"material_roles"`
	Purposes              []string `json:"purposes"`
	FieldKeys             []string `json:"field_keys"`
	SpaceIDs              []string `json:"space_ids"`
	ProductVersionAnchors []string `json:"product_version_anchors"`
	ValidityMode          string   `json:"validity_mode"`
	ValidFrom             *string  `json:"valid_from"`
	ValidThrough          *string  `json:"valid_through"`
	Priority              int64    `json:"priority"`
}

type BatchResolutionPolicy830G3 struct {
	Contract                string           `json:"contract"`
	PolicyID                string           `json:"policy_id"`
	PolicyVersion           string           `json:"policy_version"`
	TaxonomyID              string           `json:"taxonomy_id"`
	TaxonomyVersion         string           `json:"taxonomy_version"`
	IdentityThreshold       string           `json:"identity_threshold"`
	ClassificationThreshold string           `json:"classification_threshold"`
	QueueID                 string           `json:"queue_id"`
	QueueOwner              string           `json:"queue_owner"`
	AutoCandidateRequires   []string         `json:"auto_candidate_requires"`
	Rules                   []TrustRule830G3 `json:"rules"`
	PolicySHA256            string           `json:"policy_sha256"`
}

type ClassificationLabelAssignment830G3 struct {
	Label       string   `json:"label"`
	Confidence  string   `json:"confidence"`
	EvidenceIDs []string `json:"evidence_ids"`
}

type ClassificationAssignment830G3 struct {
	TaxonomyID              string                               `json:"taxonomy_id"`
	TaxonomyVersion         string                               `json:"taxonomy_version"`
	Labels                  []ClassificationLabelAssignment830G3 `json:"labels"`
	PrimaryLabel            string                               `json:"primary_label"`
	SchemaPackID            *string                              `json:"schema_pack_id"`
	SchemaVersion           *string                              `json:"schema_version"`
	SchemaPackSHA256        *string                              `json:"schema_pack_sha256"`
	ClassificationThreshold string                               `json:"classification_threshold"`
	AssignmentSHA256        string                               `json:"assignment_sha256"`
}

type EntityCandidate830G3 struct {
	Contract                  string                       `json:"contract"`
	CandidateID               string                       `json:"candidate_id"`
	EntityKeySHA256           string                       `json:"entity_key_sha256"`
	VersionCandidateKeySHA256 string                       `json:"version_candidate_key_sha256"`
	Issuer                    ObservedNormalizedValue830G3 `json:"issuer"`
	Name                      ObservedNormalizedValue830G3 `json:"name"`
	ProductCode               ObservedNormalizedValue830G3 `json:"product_code"`
	VersionLabel              ObservedNormalizedValue830G3 `json:"version_label"`
	VersionAnchor             CandidateVersionAnchor830G3  `json:"version_anchor"`
	EvidenceIDs               []string                     `json:"evidence_ids"`
	Status                    string                       `json:"status"`
	CandidateSHA256           string                       `json:"candidate_sha256"`
}

type EntityDecision830G3 struct {
	ProposalRef                  string                        `json:"proposal_ref"`
	Disposition                  string                        `json:"disposition"`
	MatchedEntityID              *string                       `json:"matched_entity_id"`
	MatchedEntityVersion         *string                       `json:"matched_entity_version"`
	EntityCandidate              *EntityCandidate830G3         `json:"entity_candidate"`
	Anchors                      EntityIdentityAnchors830G3    `json:"anchors"`
	IdentityConfidence           string                        `json:"identity_confidence"`
	IdentityThreshold            string                        `json:"identity_threshold"`
	Classification               ClassificationAssignment830G3 `json:"classification"`
	EvidenceIDs                  []string                      `json:"evidence_ids"`
	MultiIdentityNameEvidenceIDs []string                      `json:"multi_identity_name_evidence_ids"`
	MultiIdentityCodeEvidenceIDs []string                      `json:"multi_identity_code_evidence_ids"`
	ReasonCodes                  []string                      `json:"reason_codes"`
	QueueID                      *string                       `json:"queue_id"`
	QueueOwner                   *string                       `json:"queue_owner"`
	DecisionSHA256               string                        `json:"decision_sha256"`
}

type MaterialDecision830G3 struct {
	MaterialID     string                `json:"material_id"`
	Disposition    string                `json:"disposition"`
	ReasonCodes    []string              `json:"reason_codes"`
	Children       []EntityDecision830G3 `json:"children"`
	QueueID        *string               `json:"queue_id"`
	QueueOwner     *string               `json:"queue_owner"`
	EvidenceIDs    []string              `json:"evidence_ids"`
	DecisionSHA256 string                `json:"decision_sha256"`
}

type DispositionCounts830G3 struct {
	Match        int `json:"MATCH"`
	Create       int `json:"CREATE"`
	Multi        int `json:"MULTI"`
	NeedsConfirm int `json:"NEEDS_CONFIRM"`
	Quarantine   int `json:"QUARANTINE"`
}

type BatchEntityResolution830G3 struct {
	Contract                     string                  `json:"contract"`
	CompilerVersion              string                  `json:"compiler_version"`
	SpaceID                      string                  `json:"space_id"`
	CatalogSHA256                string                  `json:"catalog_sha256"`
	CorpusSHA256                 string                  `json:"corpus_sha256"`
	ProposalsSHA256              string                  `json:"proposals_sha256"`
	ExistingSnapshotSHA256       string                  `json:"existing_snapshot_sha256"`
	PolicySHA256                 string                  `json:"policy_sha256"`
	ModelExecutionReceiptSHA256s []string                `json:"model_execution_receipt_sha256s"`
	Decisions                    []MaterialDecision830G3 `json:"decisions"`
	MaterialCount                int                     `json:"material_count"`
	ResolutionDecisionCount      int                     `json:"resolution_decision_count"`
	ModelAttemptedCount          int                     `json:"model_attempted_count"`
	DispositionCounts            DispositionCounts830G3  `json:"disposition_counts"`
	BatchSHA256                  string                  `json:"batch_sha256"`
}

type ResolutionDecisionRef830G3 struct {
	MaterialID                     string `json:"material_id"`
	ProposalRef                    string `json:"proposal_ref"`
	DecisionSHA256                 string `json:"decision_sha256"`
	ClassificationAssignmentSHA256 string `json:"classification_assignment_sha256"`
}

type BoundResolutionEvidence830G3 struct {
	MaterialID  string               `json:"material_id"`
	ProposalRef string               `json:"proposal_ref"`
	EvidenceID  string               `json:"evidence_id"`
	Purpose     string               `json:"purpose"`
	Evidence    ConceptEvidence830G2 `json:"evidence"`
}

type CandidateVersionAnchor830G3 struct {
	Kind            string `json:"kind"`
	ObservedValue   string `json:"observed_value"`
	NormalizedValue string `json:"normalized_value"`
}

type EntityCompileBinding830G3 struct {
	Contract                  string                         `json:"contract"`
	EntityID                  string                         `json:"entity_id"`
	EntityVersion             string                         `json:"entity_version"`
	ResolutionDisposition     string                         `json:"resolution_disposition"`
	ResolutionRefs            []ResolutionDecisionRef830G3   `json:"resolution_refs"`
	EntityKeySHA256           string                         `json:"entity_key_sha256"`
	VersionCandidateKeySHA256 string                         `json:"version_candidate_key_sha256"`
	CandidateID               *string                        `json:"candidate_id"`
	EntityCandidateSHA256     *string                        `json:"entity_candidate_sha256"`
	DisplayName               string                         `json:"display_name"`
	Issuer                    string                         `json:"issuer"`
	ProductCode               string                         `json:"product_code"`
	VersionLabel              string                         `json:"version_label"`
	VersionAnchor             CandidateVersionAnchor830G3    `json:"version_anchor"`
	PrimaryClassification     string                         `json:"primary_classification"`
	SchemaPackID              string                         `json:"schema_pack_id"`
	SchemaVersion             string                         `json:"schema_version"`
	SchemaPackSHA256          string                         `json:"schema_pack_sha256"`
	ProfileID                 string                         `json:"profile_id"`
	ProfileVersion            string                         `json:"profile_version"`
	ProfileSHA256             string                         `json:"profile_sha256"`
	RequiredFields            []string                       `json:"required_fields"`
	SourceMaterialIDs         []string                       `json:"source_material_ids"`
	ResolutionEvidence        []BoundResolutionEvidence830G3 `json:"resolution_evidence"`
	BindingSHA256             string                         `json:"binding_sha256"`
}

type UnknownFieldKeyAlignment830G3 struct {
	Contract              string `json:"contract"`
	SourceReleaseID       string `json:"source_release_id"`
	SourceActivationEpoch uint64 `json:"source_activation_epoch"`
	SourceCandidateSHA256 string `json:"source_candidate_sha256"`
	EntityID              string `json:"entity_id"`
	EntityVersion         string `json:"entity_version"`
	OldFieldKey           string `json:"old_field_key"`
	NewFieldKey           string `json:"new_field_key"`
	OldMemberID           string `json:"old_member_id"`
	OldMemberDigest       string `json:"old_member_digest"`
	NewMemberID           string `json:"new_member_id"`
	NewMemberDigest       string `json:"new_member_digest"`
	AlignmentSHA256       string `json:"alignment_sha256"`
}

type BatchConceptCompileRequest830G3 struct {
	Contract                  string                                 `json:"contract"`
	BaseRequest               ConceptCompileRequest830G2             `json:"base_request"`
	Catalog                   SchemaPackCatalog830G3                 `json:"catalog"`
	CatalogWireSHA256         string                                 `json:"catalog_wire_sha256"`
	ProfileConfirmation       CatalogProfileConfirmationBinding830G3 `json:"profile_confirmation"`
	ResolutionInputs          BatchResolutionInputs830G3             `json:"resolution_inputs"`
	Resolution                json.RawMessage                        `json:"resolution"`
	EntityBindings            []EntityCompileBinding830G3            `json:"entity_bindings"`
	UnknownFieldKeyAlignments []UnknownFieldKeyAlignment830G3        `json:"unknown_field_key_alignments"`
	QualityStatus             string                                 `json:"quality_status"`
	ReleaseLane               string                                 `json:"release_lane"`
	RequestSHA256             string                                 `json:"request_sha256"`
}

type BatchConceptPageManifest830G3 struct {
	Contract      string                         `json:"contract"`
	Members       []ConceptPageMember830G2       `json:"members"`
	MembersSHA256 string                         `json:"members_sha256"`
	Audit         []ConceptAuditDisposition830G2 `json:"audit"`
}

type BatchConceptCandidateBundle830G3 struct {
	Contract           string                          `json:"contract"`
	Request            BatchConceptCompileRequest830G3 `json:"request"`
	ModelCompileResult ConceptCompileResult830G2       `json:"model_compile_result"`
	CompileResult      ConceptCompileResult830G2       `json:"compile_result"`
	ReviewResult       ConceptReviewResult830G2        `json:"review_result"`
	PageManifest       BatchConceptPageManifest830G3   `json:"page_manifest"`
	Admission          ConceptAdmission830G2           `json:"admission"`
	CandidateHash      string                          `json:"candidate_hash"`
}

type batchResolutionSummary830G3 struct {
	Contract                     string            `json:"contract"`
	CompilerVersion              string            `json:"compiler_version"`
	SpaceID                      string            `json:"space_id"`
	CatalogSHA256                string            `json:"catalog_sha256"`
	CorpusSHA256                 string            `json:"corpus_sha256"`
	ProposalsSHA256              string            `json:"proposals_sha256"`
	ExistingSnapshotSHA256       string            `json:"existing_snapshot_sha256"`
	PolicySHA256                 string            `json:"policy_sha256"`
	ModelExecutionReceiptSHA256s []string          `json:"model_execution_receipt_sha256s"`
	Decisions                    []json.RawMessage `json:"decisions"`
	MaterialCount                int               `json:"material_count"`
	ResolutionDecisionCount      int               `json:"resolution_decision_count"`
	ModelAttemptedCount          int               `json:"model_attempted_count"`
	DispositionCounts            json.RawMessage   `json:"disposition_counts"`
	BatchSHA256                  string            `json:"batch_sha256"`
}

var batchBundleKeys830G3 = []string{
	"admission", "candidate_hash", "compile_result", "contract", "model_compile_result",
	"page_manifest", "request", "review_result",
}

var batchRequestKeys830G3 = []string{
	"base_request", "catalog", "catalog_wire_sha256", "contract", "entity_bindings",
	"profile_confirmation", "quality_status", "release_lane", "request_sha256", "resolution",
	"resolution_inputs", "unknown_field_key_alignments",
}

var entityBindingKeys830G3 = []string{
	"binding_sha256", "candidate_id", "contract", "display_name", "entity_candidate_sha256",
	"entity_id", "entity_key_sha256", "entity_version", "issuer", "primary_classification",
	"product_code", "profile_id", "profile_sha256", "profile_version", "required_fields",
	"resolution_disposition", "resolution_evidence", "resolution_refs", "schema_pack_id",
	"schema_pack_sha256", "schema_version", "source_material_ids", "version_anchor",
	"version_candidate_key_sha256", "version_label",
}

var alignmentKeys830G3 = []string{
	"alignment_sha256", "contract", "entity_id", "entity_version", "new_field_key",
	"new_member_digest", "new_member_id", "old_field_key", "old_member_digest",
	"old_member_id", "source_activation_epoch", "source_candidate_sha256",
	"source_release_id",
}

func ParseBatchConceptCandidateBundle830G3(raw []byte) (BatchConceptCandidateBundle830G3, error) {
	var bundle BatchConceptCandidateBundle830G3
	if decodeExactObject830G3(raw, &bundle, batchBundleKeys830G3, true) != nil {
		return bundle, ErrConceptCandidateBundle830G3
	}
	if validateBatchConceptBundle830G3(bundle) != nil {
		return BatchConceptCandidateBundle830G3{}, ErrConceptCandidateBundle830G3
	}
	return bundle, nil
}

func CanonicalBatchConceptCandidateBundle830G3(raw []byte) (
	BatchConceptCandidateBundle830G3, []byte, error,
) {
	bundle, err := ParseBatchConceptCandidateBundle830G3(raw)
	if err != nil {
		return BatchConceptCandidateBundle830G3{}, nil, ErrConceptCandidateBundle830G3
	}
	canonical, err := canonicalConceptRawJSON830G2(raw)
	if err != nil {
		return BatchConceptCandidateBundle830G3{}, nil, ErrConceptCandidateBundle830G3
	}
	return bundle, canonical, nil
}

func (bundle BatchConceptCandidateBundle830G3) SnapshotMembers() (
	[]WikiReleaseMemberSnapshot, error,
) {
	if validateBatchConceptBundle830G3(bundle) != nil {
		return nil, ErrConceptCandidateBundle830G3
	}
	result := make([]WikiReleaseMemberSnapshot, 0, len(bundle.PageManifest.Members))
	for _, member := range bundle.PageManifest.Members {
		digest, err := batchConceptHash830G3("batch-concept-member.830.g3.v1", member)
		if err != nil {
			return nil, ErrConceptCandidateBundle830G3
		}
		result = append(result, WikiReleaseMemberSnapshot{
			Kind: member.Kind, LogicalSlug: member.MemberID, RevisionID: bundle.CandidateHash,
			MemberDigest: digest, Title: member.Title, Content: member.Content,
			Payload: append(json.RawMessage(nil), member.Payload...),
		})
	}
	return result, nil
}

func decodeExactObject830G3(raw []byte, destination any, keys []string, exact bool) error {
	if !utf8.Valid(raw) || !conceptJSONUnicodeValid830G2(raw) || !conceptJSONUniqueKeys830G2(raw) {
		return ErrConceptCandidateBundle830G3
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return ErrConceptCandidateBundle830G3
	}
	if exact {
		if len(fields) != len(keys) {
			return ErrConceptCandidateBundle830G3
		}
		for _, key := range keys {
			if _, ok := fields[key]; !ok {
				return ErrConceptCandidateBundle830G3
			}
		}
	} else {
		for _, key := range keys {
			if _, ok := fields[key]; !ok {
				return ErrConceptCandidateBundle830G3
			}
		}
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return ErrConceptCandidateBundle830G3
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return ErrConceptCandidateBundle830G3
	}
	if !canonicalRawEqualValue830G3(string(raw), destination) ||
		!nonNullCollections830G3(reflect.ValueOf(destination)) {
		return ErrConceptCandidateBundle830G3
	}
	return nil
}

func batchConceptHash830G3(objectType string, payload any) (string, error) {
	if objectType == "" || !isASCIIControlFree830G3(objectType) {
		return "", ErrConceptCandidateBundle830G3
	}
	canonical, err := conceptCanonicalJSON830G2(payload)
	if err != nil {
		return "", ErrConceptCandidateBundle830G3
	}
	preimage := append([]byte(schemaWikiHashPrefix), []byte(objectType)...)
	preimage = append(preimage, 0)
	preimage = append(preimage, canonical...)
	sum := sha256.Sum256(preimage)
	return hex.EncodeToString(sum[:]), nil
}

func batchConceptHashWithout830G3(objectType string, value any, hashKey string) (string, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var payload map[string]any
	if err := decoder.Decode(&payload); err != nil {
		return "", err
	}
	delete(payload, hashKey)
	return batchConceptHash830G3(objectType, payload)
}

func isASCIIControlFree830G3(value string) bool {
	if value == "" || !utf8.ValidString(value) {
		return false
	}
	for _, character := range value {
		if character > 0x7f || character < 0x20 || character == 0x7f {
			return false
		}
	}
	return true
}

func validHash830G3(value string) bool {
	if len(value) != 64 {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil && strings.ToLower(value) == value
}

func hashEqualWithout830G3(objectType string, value any, key, actual string) bool {
	expected, err := batchConceptHashWithout830G3(objectType, value, key)
	return err == nil && expected == actual
}

func canonicalRawEqualValue830G3(raw string, value any) bool {
	if !conceptJSONUnicodeValid830G2([]byte(raw)) || !conceptJSONUniqueKeys830G2([]byte(raw)) {
		return false
	}
	left, errLeft := canonicalConceptRawJSON830G2([]byte(raw))
	right, errRight := conceptCanonicalJSON830G2(value)
	return errLeft == nil && errRight == nil && bytes.Equal(left, right)
}

func nonNullCollections830G3(value reflect.Value) bool {
	if !value.IsValid() {
		return true
	}
	switch value.Kind() {
	case reflect.Interface:
		if value.IsNil() {
			return true
		}
		return nonNullCollections830G3(value.Elem())
	case reflect.Pointer:
		if value.IsNil() {
			return true
		}
		return nonNullCollections830G3(value.Elem())
	case reflect.Slice, reflect.Map:
		if value.IsNil() {
			return false
		}
		if value.Kind() == reflect.Slice {
			for index := 0; index < value.Len(); index++ {
				if !nonNullCollections830G3(value.Index(index)) {
					return false
				}
			}
			return true
		}
		iterator := value.MapRange()
		for iterator.Next() {
			if !nonNullCollections830G3(iterator.Value()) {
				return false
			}
		}
		return true
	case reflect.Array:
		for index := 0; index < value.Len(); index++ {
			if !nonNullCollections830G3(value.Index(index)) {
				return false
			}
		}
		return true
	case reflect.Struct:
		for index := 0; index < value.NumField(); index++ {
			if value.Type().Field(index).PkgPath == "" &&
				!nonNullCollections830G3(value.Field(index)) {
				return false
			}
		}
		return true
	default:
		return true
	}
}

func validateRawContractHash830G3(
	raw json.RawMessage, contract, hashKey string, keys []string,
) (string, error) {
	var payload map[string]any
	if decodeExactObject830G3(raw, &payload, keys, true) != nil || payload["contract"] != contract {
		return "", ErrConceptCandidateBundle830G3
	}
	actual, ok := payload[hashKey].(string)
	if !ok || !validHash830G3(actual) {
		return "", ErrConceptCandidateBundle830G3
	}
	delete(payload, hashKey)
	expected, err := batchConceptHash830G3(contract, payload)
	if err != nil || expected != actual {
		return "", ErrConceptCandidateBundle830G3
	}
	return actual, nil
}

func normalizedIdentity830G3(value string) string {
	return strings.Join(strings.Fields(norm.NFC.String(value)), "")
}

func validStructuredText830G3(value string) bool {
	if value == "" || strings.TrimSpace(value) == "" || !utf8.ValidString(value) || !norm.NFC.IsNormalString(value) {
		return false
	}
	for _, character := range value {
		if character < 0x20 || character == 0x7f {
			return false
		}
	}
	return true
}

func validBodyText830G3(value string) bool {
	if !utf8.ValidString(value) || !norm.NFC.IsNormalString(value) {
		return false
	}
	for _, character := range value {
		if (character < 0x20 && character != '\t' && character != '\n' && character != '\r') || character == 0x7f {
			return false
		}
	}
	return true
}

func validOptionalStructured830G3(value *string) bool {
	return value == nil || validStructuredText830G3(*value)
}

func validConfidence830G3(value string) bool {
	if len(value) != 8 || value[1] != '.' || (value[0] != '0' && value[0] != '1') {
		return false
	}
	for _, character := range value[2:] {
		if character < '0' || character > '9' {
			return false
		}
	}
	return value[0] == '0' || value[2:] == "000000"
}

func confidenceAtLeast830G3(value, threshold string) bool {
	return validConfidence830G3(value) && validConfidence830G3(threshold) && value >= threshold
}

func sortedUniquePlain830G3(values []string) bool {
	for index, value := range values {
		if !validStructuredText830G3(value) || index > 0 && values[index-1] >= value {
			return false
		}
	}
	return true
}

func exactTypedRaw830G3[T any](raw json.RawMessage, destination *T) error {
	if !utf8.Valid(raw) || !conceptJSONUnicodeValid830G2(raw) || !conceptJSONUniqueKeys830G2(raw) {
		return ErrConceptCandidateBundle830G3
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return ErrConceptCandidateBundle830G3
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) ||
		!canonicalRawEqualValue830G3(string(raw), *destination) ||
		!nonNullCollections830G3(reflect.ValueOf(destination)) {
		return ErrConceptCandidateBundle830G3
	}
	return nil
}

func validObserved830G3(value ObservedNormalizedValue830G3) bool {
	return validStructuredText830G3(value.ObservedValue) &&
		value.NormalizedValue == normalizedIdentity830G3(value.ObservedValue)
}

func validCandidateAnchor830G3(value CandidateVersionAnchor830G3) bool {
	return (value.Kind == "filing_number" || value.Kind == "registration_number") &&
		validStructuredText830G3(value.ObservedValue) &&
		value.NormalizedValue == normalizedIdentity830G3(value.ObservedValue)
}

func validVersionAnchor830G3(value VersionAnchor830G3) bool {
	return (value.Kind == "filing_number" || value.Kind == "registration_number") &&
		validStructuredText830G3(value.Value)
}

func permitDigest830G3(view ModelPermitView830G3) (string, error) {
	canonical, err := conceptCanonicalJSON830G2(view)
	if err != nil {
		return "", err
	}
	preimage := append([]byte("insurancekb.model-policy.permit-view.v1\x00"), canonical...)
	sum := sha256.Sum256(preimage)
	return hex.EncodeToString(sum[:]), nil
}

func validatePolicyReceipt830G3(receipt ModelPolicyReceipt830G3) error {
	if len(receipt.IdentityKey) != 5 {
		return ErrConceptCandidateBundle830G3
	}
	allowedReason := map[string]bool{
		"policy_allowed": true, "purpose_mismatch": true, "run_schema_version_mismatch": true,
		"space_id_mismatch": true, "run_id_mismatch": true, "run_revision_mismatch": true,
		"admission_artifact_digest_mismatch": true, "verified_binding_digest_mismatch": true,
		"model_plan_hash_mismatch": true, "admission_expired": true, "template_not_approved": true,
		"strong_model": true, "provider_not_approved": true, "family_not_approved": true,
		"invalid_identity": true, "rolling_identity": true, "identity_not_approved": true,
		"identity_not_admission_approved": true,
	}
	if !allowedReason[receipt.ReasonCode] {
		return ErrConceptCandidateBundle830G3
	}
	if (receipt.IdentityKey[2] != "deepseek" && receipt.IdentityKey[2] != "minimax" && receipt.IdentityKey[2] != "qwen" && receipt.IdentityKey[2] != "qwen-vl") ||
		(receipt.IdentityKey[3] != "classify" && receipt.IdentityKey[3] != "extract" && receipt.IdentityKey[3] != "gap" && receipt.IdentityKey[3] != "verify" && receipt.IdentityKey[3] != "consensus") {
		return ErrConceptCandidateBundle830G3
	}
	for _, digest := range []string{receipt.AdmissionHash, receipt.RequestDigest, receipt.BindingDigest,
		receipt.VerifiedBindingDigest, receipt.TemplateHash, receipt.ModelPlanHash, receipt.CallScopeHash,
		receipt.AttemptedContextDigest, receipt.PolicySnapshotDigest} {
		if !validHash830G3(digest) {
			return ErrConceptCandidateBundle830G3
		}
	}
	if _, err := time.Parse(time.RFC3339, receipt.EvaluatedAt); err != nil {
		return ErrConceptCandidateBundle830G3
	}
	if receipt.Decision == "DENY" {
		if receipt.ReasonCode == "policy_allowed" || receipt.PermitDigest != nil || receipt.PermitView != nil {
			return ErrConceptCandidateBundle830G3
		}
		for _, value := range append(append([]string{}, receipt.IdentityKey...), receipt.Purpose, receipt.RunSchemaVersion,
			receipt.SpaceID, receipt.RunID, receipt.RunRevision, receipt.ReasonCode, receipt.Decision, receipt.EvaluatedAt) {
			if !validStructuredText830G3(value) {
				return ErrConceptCandidateBundle830G3
			}
		}
		return nil
	}
	validFamily := receipt.PermitView != nil && (receipt.PermitView.Identity.Family == "deepseek" ||
		receipt.PermitView.Identity.Family == "minimax" || receipt.PermitView.Identity.Family == "qwen" ||
		receipt.PermitView.Identity.Family == "qwen-vl")
	if receipt.Decision != "ALLOW" || receipt.ReasonCode != "policy_allowed" ||
		receipt.PermitDigest == nil || receipt.PermitView == nil || !validFamily {
		return ErrConceptCandidateBundle830G3
	}
	view := receipt.PermitView
	identity := []string{view.Identity.Provider, view.Identity.DeploymentID, view.Identity.Family,
		view.Identity.Role, view.Identity.PolicyVersion}
	digest, err := permitDigest830G3(*view)
	evaluated, evalErr := time.Parse(time.RFC3339, receipt.EvaluatedAt)
	expires, expiresErr := time.Parse(time.RFC3339, view.ExpiresAt)
	if err != nil || evalErr != nil || expiresErr != nil || !evaluated.Before(expires) ||
		digest != *receipt.PermitDigest || !reflect.DeepEqual(receipt.IdentityKey, identity) ||
		receipt.Purpose != view.Purpose || receipt.RunSchemaVersion != view.RunSchemaVersion ||
		receipt.SpaceID != view.SpaceID || receipt.RunID != view.RunID ||
		receipt.RunRevision != view.RunRevision || receipt.AdmissionHash != view.AdmissionHash ||
		receipt.VerifiedBindingDigest != view.VerifiedBindingDigest ||
		receipt.TemplateHash != view.TemplateHash || receipt.ModelPlanHash != view.ModelPlanHash ||
		receipt.PolicySnapshotDigest != view.PolicySnapshotDigest ||
		receipt.CallScopeHash != view.CallScopeHash || view.Identity.Role != "classify" {
		return ErrConceptCandidateBundle830G3
	}
	for _, value := range append(identity, receipt.Purpose, receipt.RunSchemaVersion, receipt.SpaceID,
		receipt.RunID, receipt.RunRevision, receipt.ReasonCode, receipt.Decision, receipt.EvaluatedAt, view.ExpiresAt) {
		if !validStructuredText830G3(value) {
			return ErrConceptCandidateBundle830G3
		}
	}
	if !validHash830G3(*receipt.PermitDigest) {
		return ErrConceptCandidateBundle830G3
	}
	return nil
}

func validateProposalBatch830G3(batch ProposalBatch830G3, corpus BatchCorpus830G3) error {
	if batch.Contract != "batch-identity-proposals.830.g3.v1" || batch.CorpusSHA256 != corpus.CorpusSHA256 ||
		!hashEqualWithout830G3(batch.Contract, batch, "proposals_sha256", batch.ProposalsSHA256) {
		return ErrConceptCandidateBundle830G3
	}
	entryByID := map[string]CorpusEntry830G3{}
	for _, entry := range corpus.Entries {
		entryByID[entry.MaterialID] = entry
	}
	previousReceipt := ""
	for _, receipt := range batch.ModelReceipts {
		if receipt.RequestSHA256 <= previousReceipt || !validHash830G3(receipt.RequestSHA256) ||
			!validHash830G3(receipt.InputSHA256) || !validHash830G3(receipt.RawOutputSHA256) ||
			!validHash830G3(receipt.ExecutionReceiptSHA256) || validatePolicyReceipt830G3(receipt.PolicyReceipt) != nil ||
			len(receipt.MaterialBindings) == 0 {
			return ErrConceptCandidateBundle830G3
		}
		previousReceipt = receipt.RequestSHA256
		previousMaterial := ""
		for _, binding := range receipt.MaterialBindings {
			if binding.MaterialID <= previousMaterial || !validHash830G3(binding.CorpusEntrySHA256) {
				return ErrConceptCandidateBundle830G3
			}
			previousMaterial = binding.MaterialID
		}
	}
	previousMaterial := ""
	allEvidence := map[string]bool{}
	for _, proposal := range batch.Proposals {
		_, ok := entryByID[proposal.MaterialID]
		if !ok || proposal.MaterialID <= previousMaterial || !validHash830G3(proposal.CorpusEntrySHA256) ||
			!hashEqualWithout830G3("material-proposal.830.g3.v1", proposal, "proposal_sha256", proposal.ProposalSHA256) ||
			len(proposal.Entities) == 0 || len(proposal.Evidence) == 0 ||
			!validStructuredText830G3(proposal.MaterialID) || !validStructuredText830G3(proposal.MaterialRole) ||
			!validHash830G3(proposal.ModelRequestSHA256) || !sortedUniquePlain830G3(proposal.MaterialRoleEvidenceIDs) {
			return ErrConceptCandidateBundle830G3
		}
		previousMaterial = proposal.MaterialID
		evidenceByID := map[string]ProposalEvidence830G3{}
		previousEvidence := ""
		for _, evidence := range proposal.Evidence {
			allowedPurpose := evidence.Purpose == "issuer" || evidence.Purpose == "product_code" ||
				evidence.Purpose == "name" || evidence.Purpose == "version" || evidence.Purpose == "classification" ||
				evidence.Purpose == "material_role" || evidence.Purpose == "field"
			if evidence.EvidenceID <= previousEvidence || allEvidence[evidence.EvidenceID] ||
				!allowedPurpose ||
				!validStructuredText830G3(evidence.EvidenceID) || !validStructuredText830G3(evidence.Purpose) ||
				!validOptionalStructured830G3(evidence.EntityProposalRef) || !validOptionalStructured830G3(evidence.FieldKey) ||
				validateConceptEvidenceShape830G2(evidence.Evidence) != nil || !validBodyText830G3(evidence.Evidence.Quote) {
				return ErrConceptCandidateBundle830G3
			}
			if (evidence.Purpose == "material_role" && (evidence.EntityProposalRef != nil || evidence.FieldKey != nil)) ||
				(evidence.Purpose == "field" && (evidence.EntityProposalRef == nil || evidence.FieldKey == nil)) ||
				(evidence.Purpose != "material_role" && evidence.Purpose != "field" &&
					(evidence.EntityProposalRef == nil || evidence.FieldKey != nil)) {
				return ErrConceptCandidateBundle830G3
			}
			previousEvidence, allEvidence[evidence.EvidenceID], evidenceByID[evidence.EvidenceID] = evidence.EvidenceID, true, evidence
		}
		previousRef := ""
		refs := map[string]bool{}
		for _, entity := range proposal.Entities {
			if entity.ProposalRef <= previousRef || refs[entity.ProposalRef] || !validConfidence830G3(entity.IdentityConfidence) ||
				!validStructuredText830G3(entity.ProposalRef) || !validOptionalStructured830G3(entity.Issuer) ||
				!validOptionalStructured830G3(entity.Name) || !validOptionalStructured830G3(entity.ProductCode) ||
				!validOptionalStructured830G3(entity.VersionLabel) || !validOptionalStructured830G3(entity.ValidFrom) ||
				!validOptionalStructured830G3(entity.ValidThrough) ||
				(entity.FilingOrRegistration != nil && !validVersionAnchor830G3(*entity.FilingOrRegistration)) ||
				!sortedUniquePlain830G3(entity.IdentityEvidenceIDs) || len(entity.Labels) == 0 {
				return ErrConceptCandidateBundle830G3
			}
			refs[entity.ProposalRef], previousRef = true, entity.ProposalRef
			previousLabel, primaryCount := "", 0
			for _, label := range entity.Labels {
				if label.TaxonomyLabel <= previousLabel || !validStructuredText830G3(label.TaxonomyLabel) ||
					!validConfidence830G3(label.Confidence) ||
					!sortedUniquePlain830G3(label.EvidenceIDs) {
					return ErrConceptCandidateBundle830G3
				}
				if label.TaxonomyLabel == entity.PrimaryLabel {
					primaryCount++
				}
				previousLabel = label.TaxonomyLabel
				for _, id := range label.EvidenceIDs {
					if evidenceByID[id].Purpose != "classification" {
						return ErrConceptCandidateBundle830G3
					}
				}
			}
			if primaryCount != 1 {
				return ErrConceptCandidateBundle830G3
			}
			for _, id := range entity.IdentityEvidenceIDs {
				row, found := evidenceByID[id]
				if !found || row.EntityProposalRef == nil || *row.EntityProposalRef != entity.ProposalRef ||
					(row.Purpose != "issuer" && row.Purpose != "name" && row.Purpose != "product_code" && row.Purpose != "version") {
					return ErrConceptCandidateBundle830G3
				}
			}
		}
		for _, evidence := range proposal.Evidence {
			if evidence.EntityProposalRef != nil && !refs[*evidence.EntityProposalRef] {
				return ErrConceptCandidateBundle830G3
			}
		}
		for _, id := range proposal.MaterialRoleEvidenceIDs {
			if evidenceByID[id].Purpose != "material_role" {
				return ErrConceptCandidateBundle830G3
			}
		}
	}
	return nil
}

func validateExistingSnapshot830G3(snapshot ExistingEntitySnapshot830G3) error {
	if snapshot.Contract != "existing-entities.830.g3.v1" || snapshot.TenantID == 0 ||
		!hashEqualWithout830G3(snapshot.Contract, snapshot, "snapshot_sha256", snapshot.SnapshotSHA256) {
		return ErrConceptCandidateBundle830G3
	}
	previous := ""
	codeOwner, ownerCode := map[string]string{}, map[string]string{}
	for _, entity := range snapshot.Entities {
		key := entity.EntityID + "\x00" + entity.EntityVersion
		code := normalizedIdentity830G3(entity.ProductCode)
		if key <= previous || !validStructuredText830G3(entity.EntityID) || !validStructuredText830G3(entity.EntityVersion) ||
			!validOptionalStructured830G3(entity.ProductID) || !validOptionalStructured830G3(entity.ProductVersionID) ||
			!validStructuredText830G3(entity.Issuer) || !validStructuredText830G3(entity.Name) ||
			!validStructuredText830G3(entity.ProductCode) || !validStructuredText830G3(entity.VersionLabel) ||
			!validVersionAnchor830G3(entity.FilingOrRegistration) ||
			(codeOwner[code] != "" && codeOwner[code] != entity.EntityID) ||
			(ownerCode[entity.EntityID] != "" && ownerCode[entity.EntityID] != code) {
			return ErrConceptCandidateBundle830G3
		}
		previous, codeOwner[code], ownerCode[entity.EntityID] = key, entity.EntityID, code
		previousAlias := ""
		for _, alias := range entity.ApprovedAliases {
			if alias.Value <= previousAlias || !validStructuredText830G3(alias.Value) || !validHash830G3(alias.ApprovalReceiptSHA256) {
				return ErrConceptCandidateBundle830G3
			}
			previousAlias = alias.Value
		}
		if !sortedUniquePlain830G3(entity.IdentityEvidenceSHA256s) {
			return ErrConceptCandidateBundle830G3
		}
		for _, digest := range entity.IdentityEvidenceSHA256s {
			if !validHash830G3(digest) {
				return ErrConceptCandidateBundle830G3
			}
		}
	}
	for _, digest := range []string{snapshot.HeadReceiptSHA256, snapshot.ResolverPolicySHA256, snapshot.SnapshotSHA256} {
		if !validHash830G3(digest) {
			return ErrConceptCandidateBundle830G3
		}
	}
	return nil
}

func validISODate830G3(value *string) bool {
	if value == nil {
		return true
	}
	parsed, err := time.Parse("2006-01-02", *value)
	return err == nil && parsed.Format("2006-01-02") == *value
}

func validateResolutionPolicy830G3(policy BatchResolutionPolicy830G3) error {
	expected := []string{"code", "dual_threshold", "evidence", "issuer", "name", "no_conflict", "unique_key", "version"}
	if policy.Contract != "batch-resolution-policy.830.g3.v1" || !reflect.DeepEqual(policy.AutoCandidateRequires, expected) ||
		!validStructuredText830G3(policy.PolicyID) || !validStructuredText830G3(policy.PolicyVersion) ||
		!validStructuredText830G3(policy.TaxonomyID) || !validStructuredText830G3(policy.TaxonomyVersion) ||
		!validStructuredText830G3(policy.QueueID) || !validStructuredText830G3(policy.QueueOwner) ||
		!validConfidence830G3(policy.IdentityThreshold) || !validConfidence830G3(policy.ClassificationThreshold) ||
		len(policy.Rules) == 0 || !hashEqualWithout830G3(policy.Contract, policy, "policy_sha256", policy.PolicySHA256) {
		return ErrConceptCandidateBundle830G3
	}
	previous := ""
	for _, rule := range policy.Rules {
		if rule.RuleID <= previous || !sortedUniquePlain830G3(rule.ProvenanceKinds) ||
			!sortedUniquePlain830G3(rule.MaterialRoles) || !sortedUniquePlain830G3(rule.Purposes) ||
			!sortedUniquePlain830G3(rule.FieldKeys) || !sortedUniquePlain830G3(rule.SpaceIDs) ||
			!sortedUniquePlain830G3(rule.ProductVersionAnchors) || !validISODate830G3(rule.ValidFrom) || !validISODate830G3(rule.ValidThrough) ||
			(rule.ValidityMode != "identity_only" && rule.ValidityMode != "interval") ||
			(rule.ValidityMode == "interval" && rule.ValidFrom == nil) {
			return ErrConceptCandidateBundle830G3
		}
		if rule.ValidFrom != nil && rule.ValidThrough != nil && *rule.ValidThrough < *rule.ValidFrom {
			return ErrConceptCandidateBundle830G3
		}
		for _, list := range [][]string{rule.ProvenanceKinds, rule.MaterialRoles, rule.Purposes, rule.FieldKeys, rule.SpaceIDs, rule.ProductVersionAnchors} {
			for _, value := range list {
				if strings.ContainsAny(value, "*?[]{}") {
					return ErrConceptCandidateBundle830G3
				}
			}
		}
		for _, value := range rule.ProvenanceKinds {
			if value != "official_public_document" && value != "user_supplied_document" && value != "internal_document" && value != "unknown" {
				return ErrConceptCandidateBundle830G3
			}
		}
		for _, value := range rule.Purposes {
			if value != "issuer" && value != "product_code" && value != "name" && value != "version" &&
				value != "classification" && value != "material_role" && value != "field" {
				return ErrConceptCandidateBundle830G3
			}
		}
		previous = rule.RuleID
	}
	return nil
}

type typedResolutionInputs830G3 struct {
	Proposals  ProposalBatch830G3
	Existing   ExistingEntitySnapshot830G3
	Policy     BatchResolutionPolicy830G3
	Resolution BatchEntityResolution830G3
}

type sourceKey830G3 struct {
	RevisionID string
	BlockID    string
}

func sourceKeyFor830G3(source ConceptSourceBlock830G2) sourceKey830G3 {
	return sourceKey830G3{RevisionID: source.RevisionID, BlockID: source.BlockID}
}

func evidenceKeyFor830G3(evidence ConceptEvidence830G2) sourceKey830G3 {
	return sourceKey830G3{RevisionID: evidence.RevisionID, BlockID: evidence.BlockID}
}

func corpusIndexes830G3(corpus BatchCorpus830G3) (
	map[string]CorpusEntry830G3, map[sourceKey830G3]ConceptSourceBlock830G2, error,
) {
	entries := make(map[string]CorpusEntry830G3, len(corpus.Entries))
	sources := map[sourceKey830G3]ConceptSourceBlock830G2{}
	for _, entry := range corpus.Entries {
		if _, duplicate := entries[entry.MaterialID]; duplicate {
			return nil, nil, ErrConceptCandidateBundle830G3
		}
		entries[entry.MaterialID] = entry
		for _, block := range entry.Blocks {
			key := sourceKeyFor830G3(block)
			if previous, exists := sources[key]; exists && !reflect.DeepEqual(previous, block) {
				return nil, nil, ErrConceptCandidateBundle830G3
			}
			sources[key] = block
		}
	}
	return entries, sources, nil
}

func validateRequestSourceClosure830G3(
	request BatchConceptCompileRequest830G3, entries map[string]CorpusEntry830G3,
) error {
	baseSources := map[sourceKey830G3]ConceptSourceBlock830G2{}
	for _, source := range request.BaseRequest.Sources {
		key := sourceKeyFor830G3(source)
		if previous, exists := baseSources[key]; exists && !reflect.DeepEqual(previous, source) {
			return ErrConceptCandidateBundle830G3
		}
		baseSources[key] = source
	}
	required := map[sourceKey830G3]bool{}
	for _, definition := range request.BaseRequest.ExistingDefinitions {
		for _, evidence := range definition.Evidence {
			required[evidenceKeyFor830G3(evidence)] = true
		}
	}
	for _, field := range request.BaseRequest.ExistingFields {
		for _, evidence := range field.Evidence {
			required[evidenceKeyFor830G3(evidence)] = true
		}
	}
	for _, page := range request.BaseRequest.ExistingPages {
		for _, evidence := range page.Evidence {
			required[evidenceKeyFor830G3(evidence)] = true
		}
	}
	for _, binding := range request.EntityBindings {
		for _, materialID := range binding.SourceMaterialIDs {
			entry, exists := entries[materialID]
			if !exists {
				return ErrConceptCandidateBundle830G3
			}
			for _, block := range entry.Blocks {
				key := sourceKeyFor830G3(block)
				required[key] = true
				if base, found := baseSources[key]; !found || !reflect.DeepEqual(base, block) {
					return ErrConceptCandidateBundle830G3
				}
			}
		}
	}
	if len(baseSources) != len(required) {
		return ErrConceptCandidateBundle830G3
	}
	for key := range required {
		if _, exists := baseSources[key]; !exists {
			return ErrConceptCandidateBundle830G3
		}
	}
	return nil
}

func decodeResolutionInputs830G3(inputs BatchResolutionInputs830G3, resolutionRaw json.RawMessage) (typedResolutionInputs830G3, error) {
	var result typedResolutionInputs830G3
	if exactTypedRaw830G3(inputs.Proposals, &result.Proposals) != nil ||
		exactTypedRaw830G3(inputs.ExistingEntities, &result.Existing) != nil ||
		exactTypedRaw830G3(inputs.Policy, &result.Policy) != nil ||
		exactTypedRaw830G3(resolutionRaw, &result.Resolution) != nil ||
		validateProposalBatch830G3(result.Proposals, inputs.Corpus) != nil ||
		validateExistingSnapshot830G3(result.Existing) != nil ||
		validateResolutionPolicy830G3(result.Policy) != nil {
		return typedResolutionInputs830G3{}, ErrConceptCandidateBundle830G3
	}
	return result, nil
}

func validModelReceiptBinding830G3(
	binding ModelReceiptBinding830G3, corpus BatchCorpus830G3, entries map[string]CorpusEntry830G3,
) bool {
	payload := make([]MaterialBinding830G3, len(binding.MaterialBindings))
	copy(payload, binding.MaterialBindings)
	expected, err := batchConceptHash830G3("batch-classifier-input.830.g3.v1", map[string]any{
		"corpus_sha256": corpus.CorpusSHA256, "material_bindings": payload,
	})
	if err != nil || binding.InputSHA256 != expected || binding.PolicyReceipt.Decision != "ALLOW" ||
		binding.PolicyReceipt.Purpose != "g3-batch-resolution" || binding.PolicyReceipt.RunSchemaVersion != "830-g3-v1" ||
		binding.PolicyReceipt.SpaceID != corpus.SpaceID || binding.PolicyReceipt.PermitView == nil ||
		binding.PolicyReceipt.PermitView.Purpose != "g3-batch-resolution" ||
		binding.PolicyReceipt.PermitView.RunSchemaVersion != "830-g3-v1" ||
		binding.PolicyReceipt.PermitView.Identity.Role != "classify" {
		return false
	}
	for _, item := range binding.MaterialBindings {
		entry, exists := entries[item.MaterialID]
		if !exists || entry.EntrySHA256 != item.CorpusEntrySHA256 {
			return false
		}
	}
	return true
}

func expectedAnchors830G3(entity EntityProposal830G3) EntityIdentityAnchors830G3 {
	anchor := func(value *string) *ObservedNormalizedValue830G3 {
		if value == nil {
			return nil
		}
		return &ObservedNormalizedValue830G3{ObservedValue: *value, NormalizedValue: normalizedIdentity830G3(*value)}
	}
	var versionAnchor *CandidateVersionAnchor830G3
	if entity.FilingOrRegistration != nil {
		versionAnchor = &CandidateVersionAnchor830G3{
			Kind: entity.FilingOrRegistration.Kind, ObservedValue: entity.FilingOrRegistration.Value,
			NormalizedValue: normalizedIdentity830G3(entity.FilingOrRegistration.Value),
		}
	}
	return EntityIdentityAnchors830G3{
		Issuer: anchor(entity.Issuer), Name: anchor(entity.Name), ProductCode: anchor(entity.ProductCode),
		VersionLabel: anchor(entity.VersionLabel), VersionAnchor: versionAnchor,
	}
}

func expectedClassification830G3(
	entity EntityProposal830G3, policy BatchResolutionPolicy830G3, catalog SchemaPackCatalog830G3,
) (ClassificationAssignment830G3, error) {
	labels := make([]ClassificationLabelAssignment830G3, 0, len(entity.Labels))
	for _, label := range entity.Labels {
		labels = append(labels, ClassificationLabelAssignment830G3{
			Label: label.TaxonomyLabel, Confidence: label.Confidence, EvidenceIDs: label.EvidenceIDs,
		})
	}
	var packID, version, packHash *string
	for index := range catalog.Entries {
		entry := &catalog.Entries[index]
		if len(entry.Pack.ApplicableClassifications) == 1 && entry.Pack.ApplicableClassifications[0] == entity.PrimaryLabel {
			if packID != nil {
				return ClassificationAssignment830G3{}, ErrConceptCandidateBundle830G3
			}
			id, ver, hash := entry.Pack.SchemaPackID, entry.Pack.SchemaVersion, entry.Pack.SchemaPackSHA256
			packID, version, packHash = &id, &ver, &hash
		}
	}
	result := ClassificationAssignment830G3{
		TaxonomyID: policy.TaxonomyID, TaxonomyVersion: policy.TaxonomyVersion, Labels: labels,
		PrimaryLabel: entity.PrimaryLabel, SchemaPackID: packID, SchemaVersion: version,
		SchemaPackSHA256: packHash, ClassificationThreshold: policy.ClassificationThreshold,
	}
	hash, err := batchConceptHashWithout830G3("classification-assignment.830.g3.v1", result, "assignment_sha256")
	if err != nil {
		return ClassificationAssignment830G3{}, ErrConceptCandidateBundle830G3
	}
	result.AssignmentSHA256 = hash
	return result, nil
}

func entityKey830G3(spaceID, productCode string) (string, error) {
	return batchConceptHash830G3("entity-candidate-key.830.g3.v1", map[string]any{
		"space_id": spaceID, "product_code": normalizedIdentity830G3(productCode),
	})
}

func entityVersionKey830G3(entityKey string, entity EntityProposal830G3) (string, error) {
	if entity.VersionLabel == nil || entity.FilingOrRegistration == nil {
		return "", ErrConceptCandidateBundle830G3
	}
	return batchConceptHash830G3("entity-version-candidate-key.830.g3.v1", map[string]any{
		"entity_key_sha256": entityKey, "version_label": normalizedIdentity830G3(*entity.VersionLabel),
		"version_anchor": map[string]any{
			"kind":  entity.FilingOrRegistration.Kind,
			"value": normalizedIdentity830G3(entity.FilingOrRegistration.Value),
		},
	})
}

func validateClassification830G3(value ClassificationAssignment830G3) error {
	if !validConfidence830G3(value.ClassificationThreshold) ||
		!hashEqualWithout830G3("classification-assignment.830.g3.v1", value, "assignment_sha256", value.AssignmentSHA256) ||
		len(value.Labels) == 0 || (value.SchemaPackID == nil) != (value.SchemaVersion == nil) ||
		(value.SchemaPackID == nil) != (value.SchemaPackSHA256 == nil) {
		return ErrConceptCandidateBundle830G3
	}
	previous, primary := "", 0
	for _, label := range value.Labels {
		if label.Label <= previous || !validConfidence830G3(label.Confidence) || !sortedUniquePlain830G3(label.EvidenceIDs) {
			return ErrConceptCandidateBundle830G3
		}
		if label.Label == value.PrimaryLabel {
			primary++
		}
		previous = label.Label
	}
	if primary != 1 {
		return ErrConceptCandidateBundle830G3
	}
	return nil
}

func validateCandidate830G3(candidate EntityCandidate830G3, spaceID string) error {
	if candidate.Contract != "entity-candidate.830.g3.v1" || candidate.Status != "NOT_ACTIVE" ||
		!validObserved830G3(candidate.Issuer) || !validObserved830G3(candidate.Name) ||
		!validObserved830G3(candidate.ProductCode) || !validObserved830G3(candidate.VersionLabel) ||
		!validCandidateAnchor830G3(candidate.VersionAnchor) || !sortedUniquePlain830G3(candidate.EvidenceIDs) ||
		!hashEqualWithout830G3(candidate.Contract, candidate, "candidate_sha256", candidate.CandidateSHA256) {
		return ErrConceptCandidateBundle830G3
	}
	entityKey, err := entityKey830G3(spaceID, candidate.ProductCode.ObservedValue)
	if err != nil {
		return ErrConceptCandidateBundle830G3
	}
	versionKey, err := batchConceptHash830G3("entity-version-candidate-key.830.g3.v1", map[string]any{
		"entity_key_sha256": entityKey, "version_label": candidate.VersionLabel.NormalizedValue,
		"version_anchor": map[string]any{"kind": candidate.VersionAnchor.Kind, "value": candidate.VersionAnchor.NormalizedValue},
	})
	if err != nil || candidate.EntityKeySHA256 != entityKey || candidate.VersionCandidateKeySHA256 != versionKey ||
		candidate.CandidateID != "entity_candidate_"+versionKey {
		return ErrConceptCandidateBundle830G3
	}
	return nil
}

func proposalEvidenceIndex830G3(proposal MaterialProposal830G3) map[string]ProposalEvidence830G3 {
	result := make(map[string]ProposalEvidence830G3, len(proposal.Evidence))
	for _, evidence := range proposal.Evidence {
		result[evidence.EvidenceID] = evidence
	}
	return result
}

func primaryConfidence830G3(entity EntityProposal830G3) string {
	for _, label := range entity.Labels {
		if label.TaxonomyLabel == entity.PrimaryLabel {
			return label.Confidence
		}
	}
	return ""
}

func exactExistingMatch830G3(existing ExistingEntitySnapshot830G3, entity EntityProposal830G3) *ExistingEntity830G3 {
	if entity.ProductCode == nil || entity.Issuer == nil || entity.Name == nil || entity.VersionLabel == nil || entity.FilingOrRegistration == nil {
		return nil
	}
	var found *ExistingEntity830G3
	for index := range existing.Entities {
		candidate := &existing.Entities[index]
		if normalizedIdentity830G3(candidate.ProductCode) != normalizedIdentity830G3(*entity.ProductCode) ||
			normalizedIdentity830G3(candidate.Issuer) != normalizedIdentity830G3(*entity.Issuer) ||
			normalizedIdentity830G3(candidate.VersionLabel) != normalizedIdentity830G3(*entity.VersionLabel) ||
			candidate.FilingOrRegistration.Kind != entity.FilingOrRegistration.Kind ||
			normalizedIdentity830G3(candidate.FilingOrRegistration.Value) != normalizedIdentity830G3(entity.FilingOrRegistration.Value) {
			continue
		}
		nameMatches := normalizedIdentity830G3(candidate.Name) == normalizedIdentity830G3(*entity.Name)
		for _, alias := range candidate.ApprovedAliases {
			nameMatches = nameMatches || normalizedIdentity830G3(alias.Value) == normalizedIdentity830G3(*entity.Name)
		}
		if !nameMatches || found != nil {
			return nil
		}
		found = candidate
	}
	return found
}

func validateAutomaticEvidence830G3(
	entity EntityProposal830G3, proposal MaterialProposal830G3, entry CorpusEntry830G3,
) bool {
	byID := proposalEvidenceIndex830G3(proposal)
	for _, evidenceID := range entity.IdentityEvidenceIDs {
		row, exists := byID[evidenceID]
		if !exists || row.EntityProposalRef == nil || *row.EntityProposalRef != entity.ProposalRef ||
			verifyConceptEvidence830G2(row.Evidence, entry.Blocks) != nil {
			return false
		}
		var expected *string
		switch row.Purpose {
		case "issuer":
			expected = entity.Issuer
		case "name":
			expected = entity.Name
		case "product_code":
			expected = entity.ProductCode
		case "version":
			if entity.VersionLabel != nil && strings.Contains(normalizedIdentity830G3(row.Evidence.Quote), normalizedIdentity830G3(*entity.VersionLabel)) {
				continue
			}
			if entity.FilingOrRegistration != nil {
				expected = &entity.FilingOrRegistration.Value
			}
		default:
			return false
		}
		if expected == nil || !strings.Contains(normalizedIdentity830G3(row.Evidence.Quote), normalizedIdentity830G3(*expected)) {
			return false
		}
	}
	for _, label := range entity.Labels {
		for _, evidenceID := range label.EvidenceIDs {
			row, exists := byID[evidenceID]
			if !exists || row.Purpose != "classification" || row.EntityProposalRef == nil ||
				*row.EntityProposalRef != entity.ProposalRef || verifyConceptEvidence830G2(row.Evidence, entry.Blocks) != nil {
				return false
			}
		}
	}
	return true
}

func matchingTrustRule830G3(
	policy BatchResolutionPolicy830G3, spaceID string, entry CorpusEntry830G3,
	proposal MaterialProposal830G3, evidence ProposalEvidence830G3, entity *EntityProposal830G3,
) bool {
	anchor := ""
	if entity != nil && entity.FilingOrRegistration != nil {
		anchor = normalizedIdentity830G3(entity.FilingOrRegistration.Value)
	}
	top, count := int64(-1<<63), 0
	for _, rule := range policy.Rules {
		if !containsString830G3(rule.ProvenanceKinds, entry.Provenance.Kind) ||
			!containsString830G3(rule.MaterialRoles, proposal.MaterialRole) ||
			!containsString830G3(rule.Purposes, evidence.Purpose) ||
			!containsString830G3(rule.SpaceIDs, spaceID) ||
			(evidence.Purpose == "field" && (evidence.FieldKey == nil || !containsString830G3(rule.FieldKeys, *evidence.FieldKey))) ||
			(len(rule.ProductVersionAnchors) != 0 && !containsString830G3(rule.ProductVersionAnchors, anchor)) {
			continue
		}
		if rule.ValidityMode == "interval" && entity != nil {
			if entity.ValidFrom == nil || rule.ValidFrom == nil || !validISODate830G3(entity.ValidFrom) ||
				!validISODate830G3(entity.ValidThrough) || *entity.ValidFrom < *rule.ValidFrom ||
				(rule.ValidThrough != nil && (entity.ValidThrough == nil || *entity.ValidThrough > *rule.ValidThrough)) {
				continue
			}
		}
		if rule.Priority > top {
			top, count = rule.Priority, 1
		} else if rule.Priority == top {
			count++
		}
	}
	return count == 1
}

func addReason830G3(reasons map[string]bool, reason string) { reasons[reason] = true }

func entrySourceReasons830G3(entry CorpusEntry830G3, corpus BatchCorpus830G3) map[string]bool {
	reasons := map[string]bool{}
	var tenant uint64 = corpus.TenantID
	spaceID, rawKBID, wikiKBID := corpus.SpaceID, corpus.RawKBID, corpus.WikiKBID
	var knowledge, revision, file, manifest string
	var attempt, pages int64
	if entry.Receipt.Registered != nil {
		r := entry.Receipt.Registered
		knowledge, revision, file, manifest, attempt, pages = r.KnowledgeID, r.RevisionSourceID, r.FileSHA256, r.ManifestDigest, r.ParseAttempt, r.PageCount
		if r.ObjectSHA256 != r.FileSHA256 || r.RetentionState != "pinned" {
			addReason830G3(reasons, "SOURCE_RECEIPT_MISMATCH")
		}
	} else if entry.Receipt.Legacy != nil {
		r := entry.Receipt.Legacy
		tenant, spaceID, rawKBID, wikiKBID = r.TenantID, r.SpaceID, r.RawKBID, r.WikiKBID
		knowledge, revision, file, manifest, attempt, pages = r.KnowledgeID, r.RevisionSourceID, r.FileSHA256, r.WeKnoraManifestDigest, r.WeKnoraParseAttempt, r.PageCount
	} else {
		addReason830G3(reasons, "SOURCE_RECEIPT_MISMATCH")
	}
	if tenant != corpus.TenantID || spaceID != corpus.SpaceID || rawKBID != corpus.RawKBID || wikiKBID != corpus.WikiKBID {
		addReason830G3(reasons, "SCOPE_MISMATCH")
	}
	for _, block := range entry.Blocks {
		if block.TenantID != corpus.TenantID || block.SpaceID != corpus.SpaceID || block.RawKBID != corpus.RawKBID {
			addReason830G3(reasons, "SCOPE_MISMATCH")
		}
		if block.KnowledgeID != knowledge || block.ParseAttempt != attempt || block.RevisionID != revision ||
			block.SourceHash != file || block.ParseHash != manifest || block.ParserIdentity != entry.ParserIdentitySHA256 ||
			int64(block.PageNumber) > pages {
			addReason830G3(reasons, "SOURCE_RECEIPT_MISMATCH")
		}
	}
	return reasons
}

func evidenceReasons830G3(
	spaceID string, entry CorpusEntry830G3, proposal MaterialProposal830G3,
	entity EntityProposal830G3, policy BatchResolutionPolicy830G3,
) map[string]bool {
	reasons := map[string]bool{}
	byID := proposalEvidenceIndex830G3(proposal)
	selected := map[string]bool{}
	for _, id := range entity.IdentityEvidenceIDs {
		selected[id] = true
	}
	for _, label := range entity.Labels {
		for _, id := range label.EvidenceIDs {
			selected[id] = true
		}
	}
	for _, id := range proposal.MaterialRoleEvidenceIDs {
		selected[id] = true
	}
	for id := range selected {
		row, exists := byID[id]
		if !exists {
			addReason830G3(reasons, "EVIDENCE_JOIN_FAILED")
			continue
		}
		if row.Purpose != "material_role" && (row.EntityProposalRef == nil || *row.EntityProposalRef != entity.ProposalRef) {
			addReason830G3(reasons, "EVIDENCE_JOIN_FAILED")
		}
		if verifyConceptEvidence830G2(row.Evidence, entry.Blocks) != nil {
			addReason830G3(reasons, "EVIDENCE_JOIN_FAILED")
		}
		var scoped *EntityProposal830G3
		if row.Purpose != "material_role" {
			scoped = &entity
		}
		if !matchingTrustRule830G3(policy, spaceID, entry, proposal, row, scoped) {
			addReason830G3(reasons, "TRUST_POLICY_UNRESOLVED")
		}
	}
	values := map[string][]string{}
	if entity.Issuer != nil {
		values["issuer"] = []string{*entity.Issuer}
	}
	if entity.Name != nil {
		values["name"] = []string{*entity.Name}
	}
	if entity.ProductCode != nil {
		values["product_code"] = []string{*entity.ProductCode}
	}
	if entity.VersionLabel != nil {
		values["version"] = append(values["version"], *entity.VersionLabel)
	}
	if entity.FilingOrRegistration != nil {
		values["version"] = append(values["version"], entity.FilingOrRegistration.Value)
	}
	for purpose, expectedValues := range values {
		for _, expected := range expectedValues {
			found := false
			for id := range selected {
				row, ok := byID[id]
				if ok && row.Purpose == purpose && row.EntityProposalRef != nil && *row.EntityProposalRef == entity.ProposalRef &&
					strings.Contains(normalizedIdentity830G3(row.Evidence.Quote), normalizedIdentity830G3(expected)) {
					found = true
					break
				}
			}
			if !found {
				addReason830G3(reasons, "IDENTITY_EVIDENCE_MISSING")
			}
		}
	}
	for _, id := range entity.IdentityEvidenceIDs {
		row, ok := byID[id]
		if !ok || row.EntityProposalRef == nil || *row.EntityProposalRef != entity.ProposalRef ||
			(row.Purpose != "issuer" && row.Purpose != "name" && row.Purpose != "product_code" && row.Purpose != "version") {
			addReason830G3(reasons, "EVIDENCE_JOIN_FAILED")
		}
	}
	if entity.ValidFrom != nil || entity.ValidThrough != nil {
		valid := entity.ValidFrom != nil && validISODate830G3(entity.ValidFrom) && validISODate830G3(entity.ValidThrough) &&
			(entity.ValidThrough == nil || *entity.ValidThrough >= *entity.ValidFrom)
		supported := true
		for _, value := range []*string{entity.ValidFrom, entity.ValidThrough} {
			if value == nil {
				continue
			}
			found := false
			for _, id := range entity.IdentityEvidenceIDs {
				row, ok := byID[id]
				if ok && row.Purpose == "version" && row.EntityProposalRef != nil && *row.EntityProposalRef == entity.ProposalRef && strings.Contains(row.Evidence.Quote, *value) {
					found = true
					break
				}
			}
			if !found {
				supported = false
			}
		}
		if !valid || !supported {
			addReason830G3(reasons, "TRUST_POLICY_UNRESOLVED")
		}
	}
	return reasons
}

func identityCompetition830G3(existing ExistingEntitySnapshot830G3, entity EntityProposal830G3) bool {
	var code, name string
	if entity.ProductCode != nil {
		code = normalizedIdentity830G3(*entity.ProductCode)
	}
	if entity.Name != nil {
		name = normalizedIdentity830G3(*entity.Name)
	}
	for _, item := range existing.Entities {
		if code != "" && normalizedIdentity830G3(item.ProductCode) == code {
			continue
		}
		nameCompetes := name != "" && normalizedIdentity830G3(item.Name) == name
		for _, alias := range item.ApprovedAliases {
			nameCompetes = nameCompetes || normalizedIdentity830G3(alias.Value) == name
		}
		anchorCompetes := entity.FilingOrRegistration != nil && entity.FilingOrRegistration.Kind == item.FilingOrRegistration.Kind &&
			normalizedIdentity830G3(entity.FilingOrRegistration.Value) == normalizedIdentity830G3(item.FilingOrRegistration.Value)
		if nameCompetes || anchorCompetes {
			return true
		}
	}
	return false
}

func sortedReasonCodes830G3(reasons map[string]bool) []string {
	result := make([]string, 0, len(reasons))
	for reason := range reasons {
		result = append(result, reason)
	}
	sort.Strings(result)
	return result
}

func multiEvidenceIDs830G3(
	spaceID string, entry CorpusEntry830G3, proposal MaterialProposal830G3, entity EntityProposal830G3,
	policy BatchResolutionPolicy830G3, reasons map[string]bool,
) ([]string, []string) {
	for _, blocker := range []string{"SCOPE_MISMATCH", "SOURCE_RECEIPT_MISMATCH", "EVIDENCE_JOIN_FAILED", "MODEL_RECEIPT_INVALID"} {
		if reasons[blocker] {
			return []string{}, []string{}
		}
	}
	if !confidenceAtLeast830G3(entity.IdentityConfidence, policy.IdentityThreshold) {
		return []string{}, []string{}
	}
	byID := proposalEvidenceIndex830G3(proposal)
	result := map[string][]string{"name": {}, "product_code": {}}
	for _, id := range entity.IdentityEvidenceIDs {
		row, ok := byID[id]
		if !ok || (row.Purpose != "name" && row.Purpose != "product_code") || row.EntityProposalRef == nil || *row.EntityProposalRef != entity.ProposalRef {
			continue
		}
		var anchor *string
		if row.Purpose == "name" {
			anchor = entity.Name
		} else {
			anchor = entity.ProductCode
		}
		if anchor == nil || verifyConceptEvidence830G2(row.Evidence, entry.Blocks) != nil ||
			!matchingTrustRule830G3(policy, spaceID, entry, proposal, row, &entity) ||
			!strings.Contains(normalizedIdentity830G3(row.Evidence.Quote), normalizedIdentity830G3(*anchor)) {
			continue
		}
		result[row.Purpose] = append(result[row.Purpose], id)
	}
	sort.Strings(result["name"])
	sort.Strings(result["product_code"])
	return result["name"], result["product_code"]
}

func occurrenceKey830G3(evidence ConceptEvidence830G2) string {
	return fmt.Sprintf("%d\x00%s\x00%s\x00%s\x00%d\x00%s\x00%s\x00%s\x00%s\x00%s\x00%s\x00%d\x00%s\x00%d\x00%d\x00%s",
		evidence.TenantID, evidence.SpaceID, evidence.RawKBID, evidence.KnowledgeID, evidence.ParseAttempt,
		evidence.RevisionID, evidence.SourceHash, evidence.ParseHash, evidence.ParserIdentity, evidence.SourceType,
		evidence.BlockID, evidence.PageNumber, evidence.OffsetUnit, evidence.Start, evidence.End, evidence.QuoteHash)
}

type resolutionRow830G3 struct {
	Entry          CorpusEntry830G3
	Proposal       MaterialProposal830G3
	Entity         EntityProposal830G3
	Reasons        map[string]bool
	Classification ClassificationAssignment830G3
	MultiName      []string
	MultiCode      []string
	Ambiguous      bool
	Candidate      *EntityCandidate830G3
}

func expectedResolutionRows830G3(
	catalog SchemaPackCatalog830G3, corpus BatchCorpus830G3, proposals ProposalBatch830G3,
	existing ExistingEntitySnapshot830G3, policy BatchResolutionPolicy830G3,
) ([]resolutionRow830G3, map[string]map[string]bool, error) {
	entries, _, err := corpusIndexes830G3(corpus)
	if err != nil {
		return nil, nil, err
	}
	receipts := map[string]ModelReceiptBinding830G3{}
	validReceipts := map[string]bool{}
	for _, receipt := range proposals.ModelReceipts {
		receipts[receipt.RequestSHA256] = receipt
		validReceipts[receipt.RequestSHA256] = validModelReceiptBinding830G3(receipt, corpus, entries)
	}
	materialReasons := map[string]map[string]bool{}
	for _, entry := range corpus.Entries {
		materialReasons[entry.MaterialID] = entrySourceReasons830G3(entry, corpus)
	}
	if corpus.TenantID != existing.TenantID || corpus.SpaceID != existing.SpaceID || corpus.RawKBID != existing.RawKBID || corpus.WikiKBID != existing.WikiKBID {
		for _, reasons := range materialReasons {
			reasons["SCOPE_MISMATCH"] = true
		}
	}
	rows := []resolutionRow830G3{}
	for _, proposal := range proposals.Proposals {
		entry := entries[proposal.MaterialID]
		forced := materialReasons[proposal.MaterialID]
		receipt, found := receipts[proposal.ModelRequestSHA256]
		materialBound := false
		if found {
			for _, binding := range receipt.MaterialBindings {
				materialBound = materialBound || binding.MaterialID == entry.MaterialID && binding.CorpusEntrySHA256 == entry.EntrySHA256
			}
		}
		if !found || !validReceipts[proposal.ModelRequestSHA256] || !materialBound {
			forced["MODEL_RECEIPT_INVALID"] = true
		}
		if proposal.CorpusEntrySHA256 != entry.EntrySHA256 {
			forced["EVIDENCE_JOIN_FAILED"] = true
		}
		for _, entity := range proposal.Entities {
			reasons := map[string]bool{}
			for reason := range forced {
				reasons[reason] = true
			}
			for reason := range evidenceReasons830G3(corpus.SpaceID, entry, proposal, entity, policy) {
				reasons[reason] = true
			}
			if entity.Issuer == nil || entity.Name == nil || entity.ProductCode == nil {
				reasons["IDENTITY_EVIDENCE_MISSING"] = true
			}
			if entity.VersionLabel == nil || entity.FilingOrRegistration == nil {
				reasons["VERSION_UNRESOLVED"] = true
			}
			if !confidenceAtLeast830G3(entity.IdentityConfidence, policy.IdentityThreshold) {
				reasons["IDENTITY_BELOW_THRESHOLD"] = true
			}
			classification, classErr := expectedClassification830G3(entity, policy, catalog)
			if classErr != nil {
				return nil, nil, classErr
			}
			if !confidenceAtLeast830G3(primaryConfidence830G3(entity), policy.ClassificationThreshold) {
				reasons["CLASSIFICATION_BELOW_THRESHOLD"] = true
			}
			if classification.SchemaPackID == nil {
				reasons["CLASSIFICATION_UNRESOLVED"] = true
			}
			if identityCompetition830G3(existing, entity) {
				reasons["AMBIGUOUS_IDENTITY"] = true
			}
			nameIDs, codeIDs := multiEvidenceIDs830G3(corpus.SpaceID, entry, proposal, entity, policy, reasons)
			rows = append(rows, resolutionRow830G3{Entry: entry, Proposal: proposal, Entity: entity, Reasons: reasons, Classification: classification, MultiName: nameIDs, MultiCode: codeIDs})
		}
	}
	byEntityKey := map[string][]int{}
	occurrences := map[string]map[string]bool{}
	for index := range rows {
		row := &rows[index]
		if row.Entity.ProductCode == nil || row.Entity.Name == nil || len(row.MultiName) == 0 || len(row.MultiCode) == 0 {
			continue
		}
		key, _ := entityKey830G3(corpus.SpaceID, *row.Entity.ProductCode)
		byEntityKey[key] = append(byEntityKey[key], index)
		byEvidence := proposalEvidenceIndex830G3(row.Proposal)
		for _, id := range append(append([]string{}, row.MultiName...), row.MultiCode...) {
			occ := occurrenceKey830G3(byEvidence[id].Evidence)
			if occurrences[occ] == nil {
				occurrences[occ] = map[string]bool{}
			}
			occurrences[occ][key] = true
		}
	}
	invalidKeys := map[string]bool{}
	for key, indexes := range byEntityKey {
		names := map[string]bool{}
		for _, index := range indexes {
			names[normalizedIdentity830G3(*rows[index].Entity.Name)] = true
		}
		if len(names) != 1 {
			invalidKeys[key] = true
		}
	}
	for _, keys := range occurrences {
		if len(keys) > 1 {
			for key := range keys {
				invalidKeys[key] = true
			}
		}
	}
	for index := range rows {
		if rows[index].Entity.ProductCode != nil {
			key, _ := entityKey830G3(corpus.SpaceID, *rows[index].Entity.ProductCode)
			if invalidKeys[key] {
				rows[index].MultiName, rows[index].MultiCode = []string{}, []string{}
			}
		}
	}
	contenders := map[string][]int{}
	versions := map[int]string{}
	eligible := map[string][]int{}
	for index := range rows {
		row := &rows[index]
		if row.Entity.ProductCode == nil {
			continue
		}
		entityKey, _ := entityKey830G3(corpus.SpaceID, *row.Entity.ProductCode)
		versionKey, versionErr := entityVersionKey830G3(entityKey, row.Entity)
		if versionErr != nil {
			continue
		}
		versions[index] = versionKey
		structural := true
		for reason := range row.Reasons {
			if reason != "IDENTITY_EVIDENCE_MISSING" && reason != "VERSION_UNRESOLVED" {
				structural = false
			}
		}
		if structural {
			contenders[entityKey] = append(contenders[entityKey], index)
		}
		if len(row.Reasons) == 0 {
			eligible[entityKey+"\x00"+versionKey] = append(eligible[entityKey+"\x00"+versionKey], index)
		}
	}
	for _, indexes := range contenders {
		shapes, versionSet := map[string]bool{}, map[string]bool{}
		for _, index := range indexes {
			row := &rows[index]
			versionSet[versions[index]] = true
			anchors := expectedAnchors830G3(row.Entity)
			shape, _ := batchConceptHash830G3("resolution-row-shape.830.g3.v1", map[string]any{
				"issuer": normalizedObservedOrNil830G3(anchors.Issuer), "name": normalizedObservedOrNil830G3(anchors.Name),
				"product_code": normalizedObservedOrNil830G3(anchors.ProductCode), "version_label": normalizedObservedOrNil830G3(anchors.VersionLabel),
				"version_anchor_kind":  candidateAnchorKindOrNil830G3(anchors.VersionAnchor),
				"version_anchor_value": candidateAnchorValueOrNil830G3(anchors.VersionAnchor),
				"schema_pack_id":       row.Classification.SchemaPackID, "schema_version": row.Classification.SchemaVersion,
				"schema_pack_sha256": row.Classification.SchemaPackSHA256,
			})
			shapes[shape] = true
		}
		if len(versionSet) > 1 || len(shapes) > 1 {
			for _, index := range indexes {
				rows[index].Ambiguous = true
			}
		}
	}
	for _, indexes := range eligible {
		qualified := []int{}
		for _, index := range indexes {
			if !rows[index].Ambiguous {
				qualified = append(qualified, index)
			}
		}
		if len(qualified) == 0 {
			continue
		}
		sort.Slice(qualified, func(i, j int) bool {
			a, b := rows[qualified[i]], rows[qualified[j]]
			if a.Entry.MaterialID == b.Entry.MaterialID {
				return a.Entity.ProposalRef < b.Entity.ProposalRef
			}
			return a.Entry.MaterialID < b.Entry.MaterialID
		})
		representative := rows[qualified[0]].Entity
		ids := []string{}
		for _, index := range qualified {
			ids = append(ids, rows[index].Entity.IdentityEvidenceIDs...)
		}
		sort.Strings(ids)
		ids = uniqueStrings830G3(ids)
		if representative.Issuer == nil || representative.Name == nil || representative.ProductCode == nil || representative.VersionLabel == nil || representative.FilingOrRegistration == nil {
			continue
		}
		entityKey, _ := entityKey830G3(corpus.SpaceID, *representative.ProductCode)
		versionKey, _ := entityVersionKey830G3(entityKey, representative)
		candidate := EntityCandidate830G3{Contract: "entity-candidate.830.g3.v1", CandidateID: "entity_candidate_" + versionKey, EntityKeySHA256: entityKey, VersionCandidateKeySHA256: versionKey, Issuer: *expectedAnchors830G3(representative).Issuer, Name: *expectedAnchors830G3(representative).Name, ProductCode: *expectedAnchors830G3(representative).ProductCode, VersionLabel: *expectedAnchors830G3(representative).VersionLabel, VersionAnchor: *expectedAnchors830G3(representative).VersionAnchor, EvidenceIDs: ids, Status: "NOT_ACTIVE"}
		candidate.CandidateSHA256, _ = batchConceptHashWithout830G3(candidate.Contract, candidate, "candidate_sha256")
		for _, index := range qualified {
			copyCandidate := candidate
			rows[index].Candidate = &copyCandidate
		}
	}
	return rows, materialReasons, nil
}

func normalizedObservedOrNil830G3(value *ObservedNormalizedValue830G3) any {
	if value == nil {
		return nil
	}
	return value.NormalizedValue
}

func candidateAnchorKindOrNil830G3(value *CandidateVersionAnchor830G3) any {
	if value == nil {
		return nil
	}
	return value.Kind
}

func candidateAnchorValueOrNil830G3(value *CandidateVersionAnchor830G3) any {
	if value == nil {
		return nil
	}
	return value.NormalizedValue
}

func hasAnyReason830G3(reasons map[string]bool, values ...string) bool {
	for _, value := range values {
		if reasons[value] {
			return true
		}
	}
	return false
}

func expectedEntityDecision830G3(
	row resolutionRow830G3, existing ExistingEntitySnapshot830G3, policy BatchResolutionPolicy830G3,
) (EntityDecision830G3, error) {
	reasons := map[string]bool{}
	for reason := range row.Reasons {
		reasons[reason] = true
	}
	if row.Ambiguous {
		reasons["AMBIGUOUS_IDENTITY"] = true
	}
	var exact *ExistingEntity830G3
	if row.Entity.ProductCode != nil {
		matches := []ExistingEntity830G3{}
		for _, candidate := range existing.Entities {
			if normalizedIdentity830G3(candidate.ProductCode) == normalizedIdentity830G3(*row.Entity.ProductCode) {
				matches = append(matches, candidate)
			}
		}
		if len(matches) > 0 {
			issuerMatches := []ExistingEntity830G3{}
			for _, candidate := range matches {
				if row.Entity.Issuer == nil || normalizedIdentity830G3(*row.Entity.Issuer) == normalizedIdentity830G3(candidate.Issuer) {
					issuerMatches = append(issuerMatches, candidate)
				}
			}
			if len(issuerMatches) == 0 {
				reasons["IDENTITY_ANCHOR_CONFLICT"] = true
			} else {
				exactMatches := []ExistingEntity830G3{}
				for _, candidate := range issuerMatches {
					nameMatches := row.Entity.Name != nil && normalizedIdentity830G3(*row.Entity.Name) == normalizedIdentity830G3(candidate.Name)
					for _, alias := range candidate.ApprovedAliases {
						nameMatches = nameMatches || row.Entity.Name != nil && normalizedIdentity830G3(*row.Entity.Name) == normalizedIdentity830G3(alias.Value)
					}
					if nameMatches && row.Entity.VersionLabel != nil && row.Entity.FilingOrRegistration != nil &&
						normalizedIdentity830G3(*row.Entity.VersionLabel) == normalizedIdentity830G3(candidate.VersionLabel) &&
						row.Entity.FilingOrRegistration.Kind == candidate.FilingOrRegistration.Kind &&
						normalizedIdentity830G3(row.Entity.FilingOrRegistration.Value) == normalizedIdentity830G3(candidate.FilingOrRegistration.Value) {
						exactMatches = append(exactMatches, candidate)
					}
				}
				if len(exactMatches) != 1 {
					reasons["AMBIGUOUS_IDENTITY"] = true
				} else {
					copyMatch := exactMatches[0]
					exact = &copyMatch
				}
			}
		}
	}
	nameIDs, codeIDs := append([]string(nil), row.MultiName...), append([]string(nil), row.MultiCode...)
	var disposition string
	var candidate *EntityCandidate830G3
	var matchedID, matchedVersion, queueID, queueOwner *string
	if hasAnyReason830G3(reasons, "SCOPE_MISMATCH", "SOURCE_RECEIPT_MISMATCH", "EVIDENCE_JOIN_FAILED", "IDENTITY_ANCHOR_CONFLICT", "MODEL_RECEIPT_INVALID") {
		disposition = "QUARANTINE"
		nameIDs, codeIDs = []string{}, []string{}
	} else if len(reasons) != 0 {
		disposition = "NEEDS_CONFIRM"
	} else if exact != nil {
		disposition = "MATCH"
		reasons["EXACT_EXISTING_MATCH"] = true
		id, version := exact.EntityID, exact.EntityVersion
		matchedID, matchedVersion = &id, &version
	} else {
		disposition = "CREATE"
		reasons["NEW_ENTITY_CANDIDATE"] = true
		candidate = row.Candidate
		if candidate == nil {
			return EntityDecision830G3{}, ErrConceptCandidateBundle830G3
		}
	}
	if disposition == "NEEDS_CONFIRM" || disposition == "QUARANTINE" {
		id, owner := policy.QueueID, policy.QueueOwner
		queueID, queueOwner = &id, &owner
	}
	evidenceIDs := append([]string(nil), row.Entity.IdentityEvidenceIDs...)
	for _, label := range row.Entity.Labels {
		evidenceIDs = append(evidenceIDs, label.EvidenceIDs...)
	}
	sort.Strings(evidenceIDs)
	evidenceIDs = uniqueStrings830G3(evidenceIDs)
	result := EntityDecision830G3{ProposalRef: row.Entity.ProposalRef, Disposition: disposition, MatchedEntityID: matchedID, MatchedEntityVersion: matchedVersion, EntityCandidate: candidate, Anchors: expectedAnchors830G3(row.Entity), IdentityConfidence: row.Entity.IdentityConfidence, IdentityThreshold: policy.IdentityThreshold, Classification: row.Classification, EvidenceIDs: evidenceIDs, MultiIdentityNameEvidenceIDs: nameIDs, MultiIdentityCodeEvidenceIDs: codeIDs, ReasonCodes: sortedReasonCodes830G3(reasons), QueueID: queueID, QueueOwner: queueOwner}
	result.DecisionSHA256, _ = batchConceptHashWithout830G3("entity-decision.830.g3.v1", result, "decision_sha256")
	return result, nil
}

func multiChildrenValid830G3(children []EntityDecision830G3) bool {
	clusters := map[string]map[string]bool{}
	for _, child := range children {
		if child.Disposition == "QUARANTINE" || child.Anchors.Name == nil || child.Anchors.ProductCode == nil || !confidenceAtLeast830G3(child.IdentityConfidence, child.IdentityThreshold) || len(child.MultiIdentityNameEvidenceIDs) == 0 || len(child.MultiIdentityCodeEvidenceIDs) == 0 || hasReasonSlice830G3(child.ReasonCodes, "SCOPE_MISMATCH", "SOURCE_RECEIPT_MISMATCH", "EVIDENCE_JOIN_FAILED", "IDENTITY_ANCHOR_CONFLICT", "MODEL_RECEIPT_INVALID") {
			continue
		}
		key := child.Anchors.ProductCode.NormalizedValue
		if clusters[key] == nil {
			clusters[key] = map[string]bool{}
		}
		clusters[key]["name:"+child.Anchors.Name.NormalizedValue] = true
		for _, id := range append(append([]string{}, child.MultiIdentityNameEvidenceIDs...), child.MultiIdentityCodeEvidenceIDs...) {
			clusters[key]["evidence:"+id] = true
		}
	}
	valid := []map[string]bool{}
	for _, cluster := range clusters {
		nameCount := 0
		for value := range cluster {
			if strings.HasPrefix(value, "name:") {
				nameCount++
			}
		}
		if nameCount == 1 {
			valid = append(valid, cluster)
		}
	}
	if len(valid) < 2 {
		return false
	}
	for i := range valid {
		for j := i + 1; j < len(valid); j++ {
			for value := range valid[i] {
				if strings.HasPrefix(value, "evidence:") && valid[j][value] {
					return false
				}
			}
		}
	}
	return true
}

func hasReasonSlice830G3(reasons []string, values ...string) bool {
	for _, value := range values {
		if containsString830G3(reasons, value) {
			return true
		}
	}
	return false
}

func expectedResolutionDecisions830G3(
	catalog SchemaPackCatalog830G3, corpus BatchCorpus830G3, proposals ProposalBatch830G3,
	existing ExistingEntitySnapshot830G3, policy BatchResolutionPolicy830G3,
) ([]MaterialDecision830G3, error) {
	rows, materialReasons, err := expectedResolutionRows830G3(catalog, corpus, proposals, existing, policy)
	if err != nil {
		return nil, err
	}
	rowsByMaterial := map[string][]resolutionRow830G3{}
	for _, row := range rows {
		rowsByMaterial[row.Entry.MaterialID] = append(rowsByMaterial[row.Entry.MaterialID], row)
	}
	proposalByMaterial := map[string]MaterialProposal830G3{}
	for _, proposal := range proposals.Proposals {
		proposalByMaterial[proposal.MaterialID] = proposal
	}
	result := make([]MaterialDecision830G3, 0, len(corpus.Entries))
	for _, entry := range corpus.Entries {
		reasons := map[string]bool{}
		for reason := range materialReasons[entry.MaterialID] {
			reasons[reason] = true
		}
		proposal, found := proposalByMaterial[entry.MaterialID]
		children := []EntityDecision830G3{}
		for _, row := range rowsByMaterial[entry.MaterialID] {
			child, childErr := expectedEntityDecision830G3(row, existing, policy)
			if childErr != nil {
				return nil, childErr
			}
			children = append(children, child)
		}
		var disposition string
		evidenceIDs := []string{}
		if hasAnyReason830G3(reasons, "SCOPE_MISMATCH", "SOURCE_RECEIPT_MISMATCH", "EVIDENCE_JOIN_FAILED", "MODEL_RECEIPT_INVALID") {
			disposition = "QUARANTINE"
		} else if !found {
			disposition = "NEEDS_CONFIRM"
			reasons["MODEL_OUTPUT_MISSING"] = true
		} else if multiChildrenValid830G3(children) {
			disposition = "MULTI"
			reasons["MULTI_ENTITY_REVIEW"] = true
		} else if len(children) == 1 {
			disposition = children[0].Disposition
		} else {
			disposition = "NEEDS_CONFIRM"
			reasons["AMBIGUOUS_IDENTITY"] = true
		}
		if found {
			for _, evidence := range proposal.Evidence {
				evidenceIDs = append(evidenceIDs, evidence.EvidenceID)
			}
		}
		if disposition == "MATCH" {
			reasons["EXACT_EXISTING_MATCH"] = true
		} else if disposition == "CREATE" {
			reasons["NEW_ENTITY_CANDIDATE"] = true
		}
		var queueID, queueOwner *string
		if disposition == "MULTI" || disposition == "NEEDS_CONFIRM" || disposition == "QUARANTINE" {
			id, owner := policy.QueueID, policy.QueueOwner
			queueID, queueOwner = &id, &owner
		}
		material := MaterialDecision830G3{MaterialID: entry.MaterialID, Disposition: disposition, ReasonCodes: sortedReasonCodes830G3(reasons), Children: children, QueueID: queueID, QueueOwner: queueOwner, EvidenceIDs: evidenceIDs}
		material.DecisionSHA256, _ = batchConceptHashWithout830G3("material-decision.830.g3.v1", material, "decision_sha256")
		result = append(result, material)
	}
	return result, nil
}

func validateResolutionReplay830G3(
	catalog SchemaPackCatalog830G3, inputs BatchResolutionInputs830G3, typed typedResolutionInputs830G3,
) error {
	resolution, proposals, existing, policy := typed.Resolution, typed.Proposals, typed.Existing, typed.Policy
	if resolution.Contract != "batch-entity-resolution.830.g3.v1" ||
		resolution.CompilerVersion != "batch-entity-resolution-compiler.830.g3.v1" ||
		resolution.SpaceID != inputs.Corpus.SpaceID || resolution.CatalogSHA256 != catalog.CatalogSHA256 ||
		resolution.CorpusSHA256 != inputs.Corpus.CorpusSHA256 || resolution.ProposalsSHA256 != proposals.ProposalsSHA256 ||
		resolution.ExistingSnapshotSHA256 != existing.SnapshotSHA256 || resolution.PolicySHA256 != policy.PolicySHA256 ||
		!hashEqualWithout830G3(resolution.Contract, resolution, "batch_sha256", resolution.BatchSHA256) ||
		resolution.MaterialCount != len(inputs.Corpus.Entries) || resolution.ResolutionDecisionCount != len(resolution.Decisions) ||
		len(resolution.Decisions) != len(inputs.Corpus.Entries) {
		return ErrConceptCandidateBundle830G3
	}
	entries, _, err := corpusIndexes830G3(inputs.Corpus)
	if err != nil {
		return err
	}
	proposalByMaterial := map[string]MaterialProposal830G3{}
	for _, proposal := range proposals.Proposals {
		proposalByMaterial[proposal.MaterialID] = proposal
	}
	validReceipts := map[string]ModelReceiptBinding830G3{}
	attempted := map[string]bool{}
	for _, receipt := range proposals.ModelReceipts {
		if validModelReceiptBinding830G3(receipt, inputs.Corpus, entries) {
			validReceipts[receipt.RequestSHA256] = receipt
			for _, binding := range receipt.MaterialBindings {
				attempted[binding.MaterialID] = true
			}
		}
	}
	executionHashes := make([]string, 0, len(validReceipts))
	for _, receipt := range validReceipts {
		executionHashes = append(executionHashes, receipt.ExecutionReceiptSHA256)
	}
	sort.Strings(executionHashes)
	if !sortedUniquePlain830G3(executionHashes) || !reflect.DeepEqual(executionHashes, resolution.ModelExecutionReceiptSHA256s) || resolution.ModelAttemptedCount != len(attempted) {
		return ErrConceptCandidateBundle830G3
	}
	expectedDecisions, err := expectedResolutionDecisions830G3(catalog, inputs.Corpus, proposals, existing, policy)
	if err != nil || !reflect.DeepEqual(expectedDecisions, resolution.Decisions) {
		return ErrConceptCandidateBundle830G3
	}
	counts := DispositionCounts830G3{}
	previousMaterial := ""
	for _, material := range resolution.Decisions {
		entry, exists := entries[material.MaterialID]
		proposal, hasProposal := proposalByMaterial[material.MaterialID]
		if !exists || material.MaterialID <= previousMaterial || !hasProposal ||
			!hashEqualWithout830G3("material-decision.830.g3.v1", material, "decision_sha256", material.DecisionSHA256) ||
			len(material.Children) != len(proposal.Entities) {
			return ErrConceptCandidateBundle830G3
		}
		previousMaterial = material.MaterialID
		switch material.Disposition {
		case "MATCH":
			counts.Match++
		case "CREATE":
			counts.Create++
		case "MULTI":
			counts.Multi++
		case "NEEDS_CONFIRM":
			counts.NeedsConfirm++
		case "QUARANTINE":
			counts.Quarantine++
		default:
			return ErrConceptCandidateBundle830G3
		}
		evidenceIDs := make([]string, 0, len(proposal.Evidence))
		for _, evidence := range proposal.Evidence {
			evidenceIDs = append(evidenceIDs, evidence.EvidenceID)
		}
		if !reflect.DeepEqual(evidenceIDs, material.EvidenceIDs) {
			return ErrConceptCandidateBundle830G3
		}
		previousRef := ""
		for index, child := range material.Children {
			entity := proposal.Entities[index]
			if child.ProposalRef != entity.ProposalRef || child.ProposalRef <= previousRef ||
				!hashEqualWithout830G3("entity-decision.830.g3.v1", child, "decision_sha256", child.DecisionSHA256) ||
				!reflect.DeepEqual(child.Anchors, expectedAnchors830G3(entity)) ||
				child.IdentityConfidence != entity.IdentityConfidence || child.IdentityThreshold != policy.IdentityThreshold ||
				validateClassification830G3(child.Classification) != nil {
				return ErrConceptCandidateBundle830G3
			}
			expectedClassification, classErr := expectedClassification830G3(entity, policy, catalog)
			if classErr != nil || !reflect.DeepEqual(expectedClassification, child.Classification) {
				return ErrConceptCandidateBundle830G3
			}
			expectedEvidence := append([]string(nil), entity.IdentityEvidenceIDs...)
			for _, label := range entity.Labels {
				expectedEvidence = append(expectedEvidence, label.EvidenceIDs...)
			}
			sort.Strings(expectedEvidence)
			expectedEvidence = uniqueStrings830G3(expectedEvidence)
			if !reflect.DeepEqual(expectedEvidence, child.EvidenceIDs) || !sortedUniquePlain830G3(child.ReasonCodes) ||
				!sortedUniquePlain830G3(child.EvidenceIDs) || !sortedUniquePlain830G3(child.MultiIdentityNameEvidenceIDs) ||
				!sortedUniquePlain830G3(child.MultiIdentityCodeEvidenceIDs) {
				return ErrConceptCandidateBundle830G3
			}
			automatic := child.Disposition == "MATCH" || child.Disposition == "CREATE"
			if automatic {
				reason := "EXACT_EXISTING_MATCH"
				if child.Disposition == "CREATE" {
					reason = "NEW_ENTITY_CANDIDATE"
				}
				if !reflect.DeepEqual(child.ReasonCodes, []string{reason}) ||
					!confidenceAtLeast830G3(entity.IdentityConfidence, policy.IdentityThreshold) ||
					!confidenceAtLeast830G3(primaryConfidence830G3(entity), policy.ClassificationThreshold) ||
					child.Classification.SchemaPackID == nil || len(child.EvidenceIDs) == 0 ||
					!validateAutomaticEvidence830G3(entity, proposal, entry) {
					return ErrConceptCandidateBundle830G3
				}
				match := exactExistingMatch830G3(existing, entity)
				if child.Disposition == "MATCH" {
					if match == nil || child.MatchedEntityID == nil || child.MatchedEntityVersion == nil || child.EntityCandidate != nil ||
						*child.MatchedEntityID != match.EntityID || *child.MatchedEntityVersion != match.EntityVersion {
						return ErrConceptCandidateBundle830G3
					}
				} else {
					if match != nil || child.MatchedEntityID != nil || child.MatchedEntityVersion != nil || child.EntityCandidate == nil ||
						validateCandidate830G3(*child.EntityCandidate, inputs.Corpus.SpaceID) != nil {
						return ErrConceptCandidateBundle830G3
					}
					candidate := child.EntityCandidate
					if entity.Issuer == nil || entity.Name == nil || entity.ProductCode == nil || entity.VersionLabel == nil || entity.FilingOrRegistration == nil ||
						candidate.Issuer.ObservedValue != *entity.Issuer || candidate.Name.ObservedValue != *entity.Name ||
						candidate.ProductCode.ObservedValue != *entity.ProductCode || candidate.VersionLabel.ObservedValue != *entity.VersionLabel ||
						candidate.VersionAnchor.ObservedValue != entity.FilingOrRegistration.Value {
						return ErrConceptCandidateBundle830G3
					}
				}
			} else if child.MatchedEntityID != nil || child.MatchedEntityVersion != nil || child.EntityCandidate != nil {
				return ErrConceptCandidateBundle830G3
			}
			previousRef = child.ProposalRef
		}
		if len(material.Children) == 1 && (material.Disposition == "MATCH" || material.Disposition == "CREATE") &&
			material.Children[0].Disposition != material.Disposition {
			return ErrConceptCandidateBundle830G3
		}
	}
	if counts != resolution.DispositionCounts {
		return ErrConceptCandidateBundle830G3
	}
	return nil
}

func uniqueStrings830G3(values []string) []string {
	result := values[:0]
	for _, value := range values {
		if len(result) == 0 || result[len(result)-1] != value {
			result = append(result, value)
		}
	}
	return result
}

func validateSchemaCatalog830G3(catalog SchemaPackCatalog830G3, wireHash string) error {
	if catalog.Contract != "schema-pack-catalog.830.g3.v1" || len(catalog.Entries) != 11 ||
		catalog.FieldNameUnionCount != 154 || catalog.FieldNameIntersectionCount != 47 ||
		!validHash830G3(catalog.CatalogSHA256) {
		return ErrConceptCandidateBundle830G3
	}
	canonical, err := conceptCanonicalJSON830G2(catalog)
	if err != nil {
		return ErrConceptCandidateBundle830G3
	}
	wireSum := sha256.Sum256(canonical)
	if hex.EncodeToString(wireSum[:]) != wireHash ||
		!hashEqualWithout830G3(catalog.Contract, catalog, "catalog_sha256", catalog.CatalogSHA256) {
		return ErrConceptCandidateBundle830G3
	}
	packIDs := map[string]bool{}
	profileIDs := map[string]bool{}
	union := map[string]bool{}
	var intersection map[string]bool
	for _, entry := range catalog.Entries {
		pack, profile := entry.Pack, entry.Profile
		packKey := pack.SchemaPackID + "\x00" + pack.SchemaVersion
		profileKey := profile.ProfileID + "\x00" + profile.ProfileVersion
		if packIDs[packKey] || profileIDs[profileKey] || pack.Contract != "schema-pack-definition.830.g3.v1" ||
			pack.EntityType != "insurance_product" || len(pack.ApplicableClassifications) != 1 ||
			pack.WorkbookSHA256 != catalog.WorkbookSHA256 || len(pack.Fields) == 0 ||
			entry.ProfileConfirmationStatus != "PENDING_PRODUCT_OWNER_CONFIRMATION" ||
			entry.QualityStatus != "REGISTERED_NOT_QUALITY_ADMITTED" ||
			validateEntityPageProfile830G1(profile) != nil ||
			profile.SchemaPackID != pack.SchemaPackID || profile.SchemaVersion != pack.SchemaVersion ||
			profile.SchemaPackSHA256 != pack.SchemaPackSHA256 ||
			profile.ProfileID != pack.PresentationProfileRef.ProfileID ||
			profile.ProfileVersion != pack.PresentationProfileRef.ProfileVersion ||
			!hashEqualWithout830G3(pack.Contract, pack, "schema_pack_sha256", pack.SchemaPackSHA256) {
			return ErrConceptCandidateBundle830G3
		}
		packIDs[packKey], profileIDs[profileKey] = true, true
		fieldKeys := map[string]bool{}
		for _, field := range pack.Fields {
			if fieldKeys[field.FieldKey] || field.FieldKey == "" || field.SourceRow <= 5 ||
				field.UsageFrequency < 0 || !validHash830G3(field.SemanticSHA256) {
				return ErrConceptCandidateBundle830G3
			}
			fieldKeys[field.FieldKey], union[field.FieldKey] = true, true
			metadata := map[string]any{
				"field_key": field.FieldKey, "short_title": field.ShortTitle,
				"schema_category": field.SchemaCategory, "value_spec": field.ValueSpec,
				"description": field.Description, "source_guidance": field.SourceGuidance,
				"formation_method": field.FormationMethod, "knowledge_role": field.KnowledgeRole,
				"common_field_marker":       field.CommonFieldMarker,
				"other_applicable_products": field.OtherApplicableProduct,
				"usage_frequency":           field.UsageFrequency,
			}
			expected, hashErr := batchConceptHash830G3(
				"schema-field-definition.830.g3.v1",
				map[string]any{"schema_pack_id": pack.SchemaPackID, "field": metadata},
			)
			if hashErr != nil || expected != field.SemanticSHA256 {
				return ErrConceptCandidateBundle830G3
			}
		}
		if intersection == nil {
			intersection = make(map[string]bool, len(fieldKeys))
			for key := range fieldKeys {
				intersection[key] = true
			}
		} else {
			for key := range intersection {
				if !fieldKeys[key] {
					delete(intersection, key)
				}
			}
		}
		ordered := make([]string, 0, len(pack.Fields))
		for _, section := range profile.Sections {
			for _, field := range section.Fields {
				ordered = append(ordered, field.FieldKey)
			}
		}
		if len(ordered) != len(fieldKeys) {
			return ErrConceptCandidateBundle830G3
		}
		for _, key := range ordered {
			if !fieldKeys[key] {
				return ErrConceptCandidateBundle830G3
			}
			delete(fieldKeys, key)
		}
		if len(fieldKeys) != 0 {
			return ErrConceptCandidateBundle830G3
		}
	}
	if len(union) != catalog.FieldNameUnionCount || len(intersection) != catalog.FieldNameIntersectionCount {
		return ErrConceptCandidateBundle830G3
	}
	return nil
}

var proposalKeys830G3 = []string{
	"contract", "corpus_sha256", "model_receipts", "proposals", "proposals_sha256",
}
var existingKeys830G3 = []string{
	"base_activation_epoch", "base_release_id", "contract", "entities", "head_receipt_sha256",
	"raw_kb_id", "resolver_policy_sha256", "resolver_version", "snapshot_sha256", "space_id",
	"tenant_id", "wiki_kb_id",
}
var policyKeys830G3 = []string{
	"auto_candidate_requires", "classification_threshold", "contract", "identity_threshold",
	"policy_id", "policy_sha256", "policy_version", "queue_id", "queue_owner", "rules",
	"taxonomy_id", "taxonomy_version",
}
var resolutionKeys830G3 = []string{
	"batch_sha256", "catalog_sha256", "compiler_version", "corpus_sha256", "decisions",
	"disposition_counts", "existing_snapshot_sha256", "material_count", "model_attempted_count",
	"model_execution_receipt_sha256s", "policy_sha256", "proposals_sha256",
	"resolution_decision_count", "space_id", "contract",
}

func validateResolutionInputs830G3(inputs BatchResolutionInputs830G3) (
	proposalHash, existingHash, policyHash string, err error,
) {
	if inputs.Contract != "batch-resolution-inputs.830.g3.v1" ||
		validateBatchCorpus830G3(inputs.Corpus) != nil ||
		!hashEqualWithout830G3(inputs.Contract, inputs, "inputs_sha256", inputs.InputsSHA256) {
		return "", "", "", ErrConceptCandidateBundle830G3
	}
	proposalHash, err = validateRawContractHash830G3(
		inputs.Proposals, "batch-identity-proposals.830.g3.v1", "proposals_sha256", proposalKeys830G3,
	)
	if err != nil {
		return "", "", "", err
	}
	existingHash, err = validateRawContractHash830G3(
		inputs.ExistingEntities, "existing-entities.830.g3.v1", "snapshot_sha256", existingKeys830G3,
	)
	if err != nil {
		return "", "", "", err
	}
	policyHash, err = validateRawContractHash830G3(
		inputs.Policy, "batch-resolution-policy.830.g3.v1", "policy_sha256", policyKeys830G3,
	)
	return proposalHash, existingHash, policyHash, err
}

func validateBatchCorpus830G3(corpus BatchCorpus830G3) error {
	if corpus.Contract != "batch-corpus.830.g3.v1" || corpus.TenantID == 0 ||
		!conceptIdentity830G2(corpus.SpaceID) || !conceptIdentity830G2(corpus.RawKBID) ||
		!conceptIdentity830G2(corpus.WikiKBID) || len(corpus.Entries) == 0 ||
		!hashEqualWithout830G3(corpus.Contract, corpus, "corpus_sha256", corpus.CorpusSHA256) {
		return ErrConceptCandidateBundle830G3
	}
	previous := ""
	receiptKeys := map[string]bool{}
	for _, entry := range corpus.Entries {
		if entry.MaterialID <= previous || validateCorpusEntry830G3(corpus, entry) != nil {
			return ErrConceptCandidateBundle830G3
		}
		var tenant uint64 = corpus.TenantID
		spaceID, rawKBID, wikiKBID := corpus.SpaceID, corpus.RawKBID, corpus.WikiKBID
		var knowledge, revision string
		var attempt int64
		if entry.Receipt.Registered != nil {
			knowledge, revision, attempt = entry.Receipt.Registered.KnowledgeID, entry.Receipt.Registered.RevisionSourceID, entry.Receipt.Registered.ParseAttempt
		} else {
			receipt := entry.Receipt.Legacy
			tenant, spaceID, rawKBID, wikiKBID = receipt.TenantID, receipt.SpaceID, receipt.RawKBID, receipt.WikiKBID
			knowledge, revision, attempt = receipt.KnowledgeID, receipt.RevisionSourceID, receipt.WeKnoraParseAttempt
		}
		key := fmt.Sprintf("%d\x00%s\x00%s\x00%s\x00%s\x00%d\x00%s", tenant, spaceID, rawKBID, wikiKBID, knowledge, attempt, revision)
		if receiptKeys[key] {
			return ErrConceptCandidateBundle830G3
		}
		receiptKeys[key] = true
		previous = entry.MaterialID
	}
	return nil
}

func validateCorpusEntry830G3(corpus BatchCorpus830G3, entry CorpusEntry830G3) error {
	_ = corpus
	if !conceptIdentity830G2(entry.MaterialID) || len(entry.Blocks) == 0 ||
		!validHash830G3(entry.NativeCaptureSHA256) || !validHash830G3(entry.ParserIdentitySHA256) ||
		!validHash830G3(entry.Provenance.AcquisitionReceiptSHA256) ||
		(entry.Provenance.Kind != "official_public_document" && entry.Provenance.Kind != "user_supplied_document" &&
			entry.Provenance.Kind != "internal_document" && entry.Provenance.Kind != "unknown") ||
		!validStructuredText830G3(entry.Provenance.ProvenanceID) || !validStructuredText830G3(entry.Provenance.SourceURI) ||
		!validStructuredText830G3(entry.Provenance.DeclaredBy) ||
		!hashEqualWithout830G3("source-provenance.830.g3.v1", entry.Provenance,
			"declaration_sha256", entry.Provenance.DeclarationSHA256) ||
		!hashEqualWithout830G3("corpus-entry.830.g3.v1", entry, "entry_sha256", entry.EntrySHA256) {
		return ErrConceptCandidateBundle830G3
	}
	if entry.Receipt.Registered != nil && entry.Receipt.Legacy == nil {
		receipt := entry.Receipt.Registered
		if receipt.Contract != "knowledge-revision-source.v1" || receipt.ParseAttempt <= 0 ||
			receipt.Size <= 0 || receipt.PageCount <= 0 || receipt.ChunkCount <= 0 ||
			receipt.ManifestAlgorithm != "weknora.chunk_manifest.v1" ||
			!validHash830G3(receipt.RevisionSourceID) || !validHash830G3(receipt.FileSHA256) ||
			!validHash830G3(receipt.ObjectSHA256) || !validHash830G3(receipt.ManifestDigest) ||
			!validHash830G3(receipt.BindingDigest) || !validStructuredText830G3(receipt.KnowledgeID) ||
			!validStructuredText830G3(receipt.MIMEType) || !validStructuredText830G3(receipt.RetentionState) {
			return ErrConceptCandidateBundle830G3
		}
	} else if entry.Receipt.Legacy != nil && entry.Receipt.Registered == nil {
		receipt := entry.Receipt.Legacy
		live := LiveRevisionSourceReceiptV1{
			Contract: receipt.Contract, RevisionSourceID: receipt.RevisionSourceID, TenantID: receipt.TenantID,
			SpaceID: receipt.SpaceID, RawKBID: receipt.RawKBID, WikiKBID: receipt.WikiKBID,
			KnowledgeID: receipt.KnowledgeID, EvidenceParseAttemptID: receipt.EvidenceParseAttemptID,
			WeKnoraParseAttempt: receipt.WeKnoraParseAttempt, ResourceID: receipt.ResourceID,
			FileSHA256: receipt.FileSHA256, Size: receipt.Size, MimeType: receipt.MIMEType,
			PageCount: int(receipt.PageCount), ParsedDocumentSHA256: receipt.ParsedDocumentSHA256,
			ParseManifestSHA256:      receipt.ParseManifestSHA256,
			WeKnoraManifestAlgorithm: receipt.WeKnoraManifestAlgorithm,
			WeKnoraManifestDigest:    receipt.WeKnoraManifestDigest,
			WeKnoraChunkCount:        int(receipt.WeKnoraChunkCount), SourceReceiptSHA256: receipt.SourceReceiptSHA256,
		}
		if ValidateLiveRevisionSourceReceiptV1(live) != nil {
			return ErrConceptCandidateBundle830G3
		}
	} else {
		return ErrConceptCandidateBundle830G3
	}
	previous := ""
	for _, block := range entry.Blocks {
		key := block.RevisionID + "\x00" + block.BlockID
		if key <= previous || validateConceptSource830G2(block) != nil || !validBodyText830G3(block.Text) {
			return ErrConceptCandidateBundle830G3
		}
		previous = key
	}
	return nil
}

func validateProfileConfirmation830G3(
	confirmation CatalogProfileConfirmationBinding830G3, catalog SchemaPackCatalog830G3,
) error {
	if confirmation.Contract != "catalog-profile-confirmation-binding.830.g3.v1" ||
		confirmation.Receipt.Contract != "830-g3-profile-user-confirmation.v1" ||
		confirmation.Receipt.Decision != "CONFIRMED" ||
		confirmation.Receipt.CatalogSHA256 != catalog.CatalogSHA256 ||
		confirmation.Receipt.CatalogWireSHA256 == "" ||
		confirmation.ReceiptFileSHA256 != "7f6141c63db4a77e3d13a0a8d632ea5463761bedeee7bd1aabef165d68c86863" ||
		confirmation.ReceiptSemanticSHA256 != "cd40072b3c4c32c3ed9440c7ff1ff5effc502c506b4ab11c86bbe438c7649b66" {
		return ErrConceptCandidateBundle830G3
	}
	expected, err := batchConceptHash830G3(confirmation.Receipt.Contract, confirmation.Receipt)
	if err != nil || expected != confirmation.ReceiptSemanticSHA256 ||
		len(confirmation.Receipt.Profiles) != len(catalog.Entries) {
		return ErrConceptCandidateBundle830G3
	}
	profiles := map[string]string{}
	for _, entry := range catalog.Entries {
		profiles[entry.Profile.ProfileID+"\x00"+entry.Profile.ProfileVersion] = entry.Profile.ProfileSHA256
	}
	seen := map[string]bool{}
	for _, profile := range confirmation.Receipt.Profiles {
		key := profile.ProfileID + "\x00" + profile.ProfileVersion
		if seen[key] || profiles[key] != profile.ProfileSHA256 {
			return ErrConceptCandidateBundle830G3
		}
		seen[key] = true
	}
	return nil
}

func validateBatchRequest830G3(request BatchConceptCompileRequest830G3) error {
	if request.Contract != conceptBatchRequest830G3 ||
		request.QualityStatus != "REGISTERED_NOT_QUALITY_ADMITTED" ||
		request.ReleaseLane != "ISOLATED_NOT_FOR_PRODUCTION" ||
		!hashEqualWithout830G3(request.Contract, request, "request_sha256", request.RequestSHA256) ||
		validateConceptRequest830G2(request.BaseRequest) != nil ||
		validateSchemaCatalog830G3(request.Catalog, request.CatalogWireSHA256) != nil ||
		validateProfileConfirmation830G3(request.ProfileConfirmation, request.Catalog) != nil ||
		request.ProfileConfirmation.Receipt.CatalogWireSHA256 != request.CatalogWireSHA256 {
		return ErrConceptCandidateBundle830G3
	}
	base := request.BaseRequest
	basePayload := map[string]any{
		"base_release_id": base.BaseReleaseID, "base_activation_epoch": base.BaseActivationEpoch,
		"existing_definitions": base.ExistingDefinitions, "existing_fields": base.ExistingFields,
		"existing_pages": base.ExistingPages, "existing_entity_versions": base.ExistingEntityVersions,
	}
	baseHash, err := batchConceptHash830G3("actual-base-members.830.g3.v1", basePayload)
	if err != nil || base.BaseReleaseID != conceptBatchBaseRelease || base.BaseActivationEpoch != 5 ||
		len(base.ExistingFields) != 134 || baseHash != conceptBatchBaseMembers {
		return ErrConceptCandidateBundle830G3
	}
	proposalHash, existingHash, policyHash, err := validateResolutionInputs830G3(request.ResolutionInputs)
	if err != nil {
		return ErrConceptCandidateBundle830G3
	}
	typedResolution, err := decodeResolutionInputs830G3(request.ResolutionInputs, request.Resolution)
	if err != nil || validateResolutionReplay830G3(
		request.Catalog, request.ResolutionInputs, typedResolution,
	) != nil {
		return ErrConceptCandidateBundle830G3
	}
	var resolution batchResolutionSummary830G3
	if decodeExactObject830G3(request.Resolution, &resolution, resolutionKeys830G3, true) != nil ||
		resolution.Contract != "batch-entity-resolution.830.g3.v1" ||
		!hashEqualWithout830G3(resolution.Contract, resolution, "batch_sha256", resolution.BatchSHA256) ||
		resolution.SpaceID != base.SpaceID || resolution.CatalogSHA256 != request.Catalog.CatalogSHA256 ||
		resolution.CorpusSHA256 != request.ResolutionInputs.Corpus.CorpusSHA256 ||
		resolution.ProposalsSHA256 != proposalHash || resolution.ExistingSnapshotSHA256 != existingHash ||
		resolution.PolicySHA256 != policyHash {
		return ErrConceptCandidateBundle830G3
	}
	if request.ResolutionInputs.Corpus.TenantID != base.TenantID ||
		request.ResolutionInputs.Corpus.SpaceID != base.SpaceID ||
		request.ResolutionInputs.Corpus.RawKBID != base.RawKBID ||
		request.ResolutionInputs.Corpus.WikiKBID != base.WikiKBID ||
		typedResolution.Existing.TenantID != base.TenantID ||
		typedResolution.Existing.SpaceID != base.SpaceID ||
		typedResolution.Existing.RawKBID != base.RawKBID ||
		typedResolution.Existing.WikiKBID != base.WikiKBID ||
		typedResolution.Existing.BaseReleaseID != base.BaseReleaseID ||
		typedResolution.Existing.BaseActivationEpoch != base.BaseActivationEpoch {
		return ErrConceptCandidateBundle830G3
	}
	if len(request.EntityBindings) != len(base.RequiredFields) ||
		len(request.UnknownFieldKeyAlignments) != 2 {
		return ErrConceptCandidateBundle830G3
	}
	bindings := map[string]EntityCompileBinding830G3{}
	previous := ""
	for _, binding := range request.EntityBindings {
		if binding.EntityID <= previous || bindings[binding.EntityID].EntityID != "" ||
			validateEntityBinding830G3(binding, request.Catalog, base) != nil {
			return ErrConceptCandidateBundle830G3
		}
		bindings[binding.EntityID], previous = binding, binding.EntityID
	}
	if validateBindingsAgainstResolution830G3(request, typedResolution) != nil {
		return ErrConceptCandidateBundle830G3
	}
	for entityID, version := range base.ExistingEntityVersions {
		binding, ok := bindings[entityID]
		if !ok || binding.ResolutionDisposition != "MATCH" || binding.EntityVersion != version ||
			binding.PrimaryClassification != "medical_insurance" ||
			binding.SchemaPackID != "schemapack_medical_insurance" ||
			binding.SchemaVersion != "2026-08-12-v5" ||
			binding.SchemaPackSHA256 != "5a7938dcb86327f12dbff6e3056271e03c63842ba34904eefebb5bcdc8694079" ||
			binding.ProfileID != "profile_medical_insurance" ||
			binding.ProfileVersion != "1.0.0-candidate" ||
			binding.ProfileSHA256 != "61595e9b2fec127dfca4c31ef95f161d55a9b0939211316b4508ccc4b7d21cf3" {
			return ErrConceptCandidateBundle830G3
		}
	}
	profileRows := make([]map[string]string, 0, len(request.EntityBindings))
	for _, binding := range request.EntityBindings {
		profileRows = append(profileRows, map[string]string{
			"entity_id": binding.EntityID, "profile_id": binding.ProfileID,
			"profile_version": binding.ProfileVersion, "profile_sha256": binding.ProfileSHA256,
		})
	}
	profileHash, err := batchConceptHash830G3("batch-profile-bindings.830.g3.v1", profileRows)
	if err != nil || base.SchemaIdentity != "catalog:"+request.Catalog.CatalogID+"@"+
		request.Catalog.CatalogVersion+"#"+request.Catalog.CatalogSHA256 ||
		base.ProfileIdentity != "profile-set:"+profileHash ||
		base.PolicyIdentity != "g3-resolution-policy:"+resolution.PolicySHA256 {
		return ErrConceptCandidateBundle830G3
	}
	if validateUnknownAlignments830G3(request, bindings) != nil {
		return ErrConceptCandidateBundle830G3
	}
	entries, _, err := corpusIndexes830G3(request.ResolutionInputs.Corpus)
	if err != nil || validateRequestSourceClosure830G3(request, entries) != nil {
		return ErrConceptCandidateBundle830G3
	}
	return nil
}

func validateEntityBinding830G3(
	binding EntityCompileBinding830G3, catalog SchemaPackCatalog830G3,
	base ConceptCompileRequest830G2,
) error {
	if binding.Contract != "entity-compile-binding.830.g3.v1" ||
		!hashEqualWithout830G3(binding.Contract, binding, "binding_sha256", binding.BindingSHA256) ||
		binding.EntityVersion != base.EntityVersions[binding.EntityID] ||
		!reflect.DeepEqual(binding.RequiredFields, base.RequiredFields[binding.EntityID]) ||
		len(binding.ResolutionRefs) == 0 || !sortedUniqueStrings830G3(binding.SourceMaterialIDs) ||
		(binding.ResolutionDisposition == "MATCH" &&
			(binding.CandidateID != nil || binding.EntityCandidateSHA256 != nil)) ||
		(binding.ResolutionDisposition == "CREATE" &&
			(binding.CandidateID == nil || binding.EntityCandidateSHA256 == nil)) ||
		(binding.ResolutionDisposition != "MATCH" && binding.ResolutionDisposition != "CREATE") {
		return ErrConceptCandidateBundle830G3
	}
	var entry *SchemaPackCatalogEntry830G3
	for index := range catalog.Entries {
		candidate := &catalog.Entries[index]
		if candidate.Pack.SchemaPackID == binding.SchemaPackID &&
			candidate.Pack.SchemaVersion == binding.SchemaVersion &&
			candidate.Pack.SchemaPackSHA256 == binding.SchemaPackSHA256 {
			if entry != nil {
				return ErrConceptCandidateBundle830G3
			}
			entry = candidate
		}
	}
	if entry == nil || entry.Pack.ApplicableClassifications[0] != binding.PrimaryClassification ||
		entry.Profile.ProfileID != binding.ProfileID ||
		entry.Profile.ProfileVersion != binding.ProfileVersion ||
		entry.Profile.ProfileSHA256 != binding.ProfileSHA256 {
		return ErrConceptCandidateBundle830G3
	}
	ordered := make([]string, 0, len(entry.Pack.Fields))
	for _, section := range entry.Profile.Sections {
		for _, field := range section.Fields {
			ordered = append(ordered, field.FieldKey)
		}
	}
	if !reflect.DeepEqual(ordered, binding.RequiredFields) {
		return ErrConceptCandidateBundle830G3
	}
	for index, ref := range binding.ResolutionRefs {
		if !conceptIdentity830G2(ref.MaterialID) || !conceptIdentity830G2(ref.ProposalRef) ||
			!validHash830G3(ref.DecisionSHA256) || !validHash830G3(ref.ClassificationAssignmentSHA256) ||
			(index > 0 && (binding.ResolutionRefs[index-1].MaterialID > ref.MaterialID ||
				(binding.ResolutionRefs[index-1].MaterialID == ref.MaterialID &&
					binding.ResolutionRefs[index-1].ProposalRef >= ref.ProposalRef))) {
			return ErrConceptCandidateBundle830G3
		}
	}
	for index, evidence := range binding.ResolutionEvidence {
		if validateConceptEvidenceShape830G2(evidence.Evidence) != nil ||
			(index > 0 && (binding.ResolutionEvidence[index-1].MaterialID > evidence.MaterialID ||
				(binding.ResolutionEvidence[index-1].MaterialID == evidence.MaterialID &&
					binding.ResolutionEvidence[index-1].EvidenceID >= evidence.EvidenceID))) {
			return ErrConceptCandidateBundle830G3
		}
	}
	return nil
}

func validateBindingsAgainstResolution830G3(
	request BatchConceptCompileRequest830G3, typed typedResolutionInputs830G3,
) error {
	type decisionPair struct {
		Parent MaterialDecision830G3
		Child  EntityDecision830G3
	}
	decisions := map[string]decisionPair{}
	for _, parent := range typed.Resolution.Decisions {
		for _, child := range parent.Children {
			key := parent.MaterialID + "\x00" + child.ProposalRef
			if _, duplicate := decisions[key]; duplicate {
				return ErrConceptCandidateBundle830G3
			}
			decisions[key] = decisionPair{Parent: parent, Child: child}
		}
	}
	proposals := map[string]MaterialProposal830G3{}
	for _, proposal := range typed.Proposals.Proposals {
		proposals[proposal.MaterialID] = proposal
	}
	for _, binding := range request.EntityBindings {
		materialIDs := map[string]bool{}
		allBoundIDs := map[string]bool{}
		boundByRef := map[string]map[string]bool{}
		for _, bound := range binding.ResolutionEvidence {
			key := bound.MaterialID + "\x00" + bound.ProposalRef
			pair, found := decisions[key]
			proposal, proposalFound := proposals[bound.MaterialID]
			if !found || !proposalFound || !containsString830G3(pair.Child.EvidenceIDs, bound.EvidenceID) {
				return ErrConceptCandidateBundle830G3
			}
			var proposalEvidence *ProposalEvidence830G3
			for index := range proposal.Evidence {
				if proposal.Evidence[index].EvidenceID == bound.EvidenceID {
					if proposalEvidence != nil {
						return ErrConceptCandidateBundle830G3
					}
					proposalEvidence = &proposal.Evidence[index]
				}
			}
			if proposalEvidence == nil || proposalEvidence.EntityProposalRef == nil ||
				*proposalEvidence.EntityProposalRef != bound.ProposalRef || proposalEvidence.Purpose != bound.Purpose ||
				!reflect.DeepEqual(proposalEvidence.Evidence, bound.Evidence) {
				return ErrConceptCandidateBundle830G3
			}
			if boundByRef[key] == nil {
				boundByRef[key] = map[string]bool{}
			}
			boundByRef[key][bound.EvidenceID], allBoundIDs[bound.EvidenceID] = true, true
		}
		for _, ref := range binding.ResolutionRefs {
			key := ref.MaterialID + "\x00" + ref.ProposalRef
			pair, found := decisions[key]
			if !found || (pair.Parent.Disposition != "MATCH" && pair.Parent.Disposition != "CREATE" && pair.Parent.Disposition != "MULTI") ||
				pair.Child.Disposition != binding.ResolutionDisposition || pair.Child.DecisionSHA256 != ref.DecisionSHA256 ||
				pair.Child.Classification.AssignmentSHA256 != ref.ClassificationAssignmentSHA256 ||
				pair.Child.Anchors.Issuer == nil || pair.Child.Anchors.Name == nil || pair.Child.Anchors.ProductCode == nil ||
				pair.Child.Anchors.VersionLabel == nil || pair.Child.Anchors.VersionAnchor == nil ||
				binding.DisplayName != pair.Child.Anchors.Name.ObservedValue || binding.Issuer != pair.Child.Anchors.Issuer.ObservedValue ||
				binding.ProductCode != pair.Child.Anchors.ProductCode.ObservedValue || binding.VersionLabel != pair.Child.Anchors.VersionLabel.ObservedValue ||
				!reflect.DeepEqual(binding.VersionAnchor, *pair.Child.Anchors.VersionAnchor) ||
				pair.Child.Classification.SchemaPackID == nil || pair.Child.Classification.SchemaVersion == nil ||
				pair.Child.Classification.SchemaPackSHA256 == nil ||
				binding.PrimaryClassification != pair.Child.Classification.PrimaryLabel ||
				binding.SchemaPackID != *pair.Child.Classification.SchemaPackID || binding.SchemaVersion != *pair.Child.Classification.SchemaVersion ||
				binding.SchemaPackSHA256 != *pair.Child.Classification.SchemaPackSHA256 ||
				!sameStringSet830G3(pair.Child.EvidenceIDs, boundByRef[key]) {
				return ErrConceptCandidateBundle830G3
			}
			entityKey, err := entityKey830G3(typed.Resolution.SpaceID, pair.Child.Anchors.ProductCode.NormalizedValue)
			if err != nil {
				return ErrConceptCandidateBundle830G3
			}
			versionKey, err := batchConceptHash830G3("entity-version-candidate-key.830.g3.v1", map[string]any{
				"entity_key_sha256": entityKey, "version_label": pair.Child.Anchors.VersionLabel.NormalizedValue,
				"version_anchor": map[string]any{"kind": pair.Child.Anchors.VersionAnchor.Kind, "value": pair.Child.Anchors.VersionAnchor.NormalizedValue},
			})
			if err != nil || binding.EntityKeySHA256 != entityKey || binding.VersionCandidateKeySHA256 != versionKey {
				return ErrConceptCandidateBundle830G3
			}
			if binding.ResolutionDisposition == "MATCH" {
				if pair.Child.MatchedEntityID == nil || pair.Child.MatchedEntityVersion == nil ||
					*pair.Child.MatchedEntityID != binding.EntityID || *pair.Child.MatchedEntityVersion != binding.EntityVersion {
					return ErrConceptCandidateBundle830G3
				}
			} else {
				candidate := pair.Child.EntityCandidate
				if candidate == nil || binding.CandidateID == nil || binding.EntityCandidateSHA256 == nil ||
					binding.EntityID != "entity_"+candidate.EntityKeySHA256 ||
					binding.EntityVersion != "entity_"+candidate.EntityKeySHA256+"@"+candidate.VersionCandidateKeySHA256 ||
					*binding.CandidateID != candidate.CandidateID || *binding.EntityCandidateSHA256 != candidate.CandidateSHA256 ||
					binding.EntityKeySHA256 != candidate.EntityKeySHA256 || binding.VersionCandidateKeySHA256 != candidate.VersionCandidateKeySHA256 {
					return ErrConceptCandidateBundle830G3
				}
			}
			for _, id := range append(append([]string{}, pair.Child.MultiIdentityNameEvidenceIDs...), pair.Child.MultiIdentityCodeEvidenceIDs...) {
				if !allBoundIDs[id] {
					return ErrConceptCandidateBundle830G3
				}
			}
			materialIDs[ref.MaterialID] = true
		}
		if !sameStringSet830G3(binding.SourceMaterialIDs, materialIDs) {
			return ErrConceptCandidateBundle830G3
		}
	}
	return nil
}

func containsString830G3(values []string, expected string) bool {
	index := sort.SearchStrings(values, expected)
	return index < len(values) && values[index] == expected
}

func sameStringSet830G3(values []string, expected map[string]bool) bool {
	if len(values) != len(expected) {
		return false
	}
	for _, value := range values {
		if !expected[value] {
			return false
		}
	}
	return true
}

func sortedUniqueStrings830G3(values []string) bool {
	for index, value := range values {
		if !conceptIdentity830G2(value) || index > 0 && values[index-1] >= value {
			return false
		}
	}
	return true
}

func validateUnknownAlignments830G3(
	request BatchConceptCompileRequest830G3, bindings map[string]EntityCompileBinding830G3,
) error {
	expectedHashes := []string{
		"de1a8ca7a18882403fb97312531fd770e4bf5fa822b08db3c61b93bb828b22ce",
		"fbba36cd2226893f51e6ac2333523a22d5854938a987676e1075186df834d069",
	}
	oldByKey := map[string]ConceptFieldAssertion830G2{}
	for _, field := range request.BaseRequest.ExistingFields {
		oldByKey[field.EntityID+"\x00"+field.FieldKey] = field
	}
	medical := bindings["ping-an-e-sheng-bao"]
	entry := catalogEntryForBinding830G3(request.Catalog, medical)
	if entry == nil {
		return ErrConceptCandidateBundle830G3
	}
	title := ""
	for _, section := range entry.Profile.Sections {
		for _, field := range section.Fields {
			if field.FieldKey == "social_insurance_requirements" {
				title = field.ShortTitle
			}
		}
	}
	for index, row := range request.UnknownFieldKeyAlignments {
		if row.Contract != "unknown-field-key-alignment.830.g3.v1" ||
			row.AlignmentSHA256 != expectedHashes[index] ||
			!hashEqualWithout830G3(row.Contract, row, "alignment_sha256", row.AlignmentSHA256) ||
			row.SourceReleaseID != conceptBatchBaseRelease || row.SourceActivationEpoch != 5 ||
			row.SourceCandidateSHA256 != "bdc806e2084afde6651e85c83a88e3d5395487398bea9b4b2c509473a663d684" ||
			row.OldFieldKey != "social_insurance_requirement" ||
			row.NewFieldKey != "social_insurance_requirements" ||
			(index > 0 && request.UnknownFieldKeyAlignments[index-1].EntityID >= row.EntityID) {
			return ErrConceptCandidateBundle830G3
		}
		old, ok := oldByKey[row.EntityID+"\x00"+row.OldFieldKey]
		if !ok || old.State != "unknown" || !old.Attempted || old.Value != nil ||
			old.UnknownReason == nil || len(old.Evidence) != 0 || len(old.Conditions) != 0 ||
			len(old.Exceptions) != 0 || len(old.ConceptIDs) != 0 || old.ValidTime != "" ||
			old.EntityVersion != row.EntityVersion {
			return ErrConceptCandidateBundle830G3
		}
		oldID, err := conceptFieldID830G2(old)
		if err != nil || oldID != row.OldMemberID {
			return ErrConceptCandidateBundle830G3
		}
		oldPayload, _ := json.Marshal(old)
		oldMember := ConceptPageMember830G2{
			Kind: "field_assertion", MemberID: oldID, OwnerID: old.EntityID,
			Title: old.FieldKey, Content: conceptFieldContent830G3(old), Payload: oldPayload,
		}
		oldDigest, err := conceptDigest830G2("concept-member", oldMember)
		if err != nil || oldDigest != row.OldMemberDigest {
			return ErrConceptCandidateBundle830G3
		}
		updated := old
		updated.FieldKey = row.NewFieldKey
		newID, err := conceptFieldID830G2(updated)
		if err != nil || newID != row.NewMemberID {
			return ErrConceptCandidateBundle830G3
		}
		newPayload, _ := json.Marshal(updated)
		newMember := ConceptPageMember830G2{
			Kind: "field_assertion", MemberID: newID, OwnerID: updated.EntityID,
			Title: title, Content: conceptFieldContent830G3(updated), Payload: newPayload,
		}
		newDigest, err := batchConceptHash830G3("batch-concept-member.830.g3.v1", newMember)
		if err != nil || newDigest != row.NewMemberDigest {
			return ErrConceptCandidateBundle830G3
		}
	}
	return nil
}

func catalogEntryForBinding830G3(
	catalog SchemaPackCatalog830G3, binding EntityCompileBinding830G3,
) *SchemaPackCatalogEntry830G3 {
	for index := range catalog.Entries {
		entry := &catalog.Entries[index]
		if entry.Pack.SchemaPackID == binding.SchemaPackID &&
			entry.Pack.SchemaVersion == binding.SchemaVersion &&
			entry.Pack.SchemaPackSHA256 == binding.SchemaPackSHA256 {
			return entry
		}
	}
	return nil
}

func alignedFields830G3(request BatchConceptCompileRequest830G3) (
	[]ConceptFieldAssertion830G2, error,
) {
	rows := map[string]UnknownFieldKeyAlignment830G3{}
	for _, row := range request.UnknownFieldKeyAlignments {
		rows[row.EntityID+"\x00"+row.OldFieldKey] = row
	}
	result := make([]ConceptFieldAssertion830G2, 0, len(request.BaseRequest.ExistingFields))
	for _, field := range request.BaseRequest.ExistingFields {
		if row, ok := rows[field.EntityID+"\x00"+field.FieldKey]; ok {
			field.FieldKey = row.NewFieldKey
		}
		result = append(result, field)
	}
	sort.Slice(result, func(i, j int) bool {
		if result[i].EntityID == result[j].EntityID {
			return result[i].FieldKey < result[j].FieldKey
		}
		return result[i].EntityID < result[j].EntityID
	})
	return result, nil
}

func conceptFieldContent830G3(field ConceptFieldAssertion830G2) string {
	lines := make([]string, 0, 1+len(field.Conditions)+len(field.Exceptions)+1)
	switch field.State {
	case "present":
		lines = append(lines, "值："+valueOrEmpty830G3(field.Value))
	case "absent_explicitly":
		lines = append(lines, "明确不提供："+valueOrEmpty830G3(field.Value))
	default:
		lines = append(lines, "未知："+valueOrEmpty830G3(field.UnknownReason))
	}
	for _, condition := range field.Conditions {
		lines = append(lines, "条件："+condition)
	}
	for _, exception := range field.Exceptions {
		lines = append(lines, "例外："+exception)
	}
	if field.ValidTime != "" {
		lines = append(lines, "有效期："+field.ValidTime)
	}
	return strings.Join(lines, "\n")
}

func valueOrEmpty830G3(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}

func validateExecution830G3(record ConceptExecutionRecord830G2, output any, contextHash string) error {
	rawSum := sha256.Sum256([]byte(record.RawOutput))
	if !conceptIdentity830G2(record.RunID) || !conceptIdentity830G2(record.Implementation) ||
		record.ContextHash != contextHash || hex.EncodeToString(rawSum[:]) != record.RawOutputHash ||
		!canonicalRawEqualValue830G3(record.RawOutput, output) {
		return ErrConceptCandidateBundle830G3
	}
	return nil
}

func compileRequestHash830G3(request ConceptCompileRequest830G2) (string, error) {
	return conceptDigest830G2("compile-request", request)
}

func compileOutputHash830G3(output ConceptCompileOutput830G2) (string, error) {
	return conceptDigest830G2("compile-output", output)
}

func validateBatchConceptBundle830G3(bundle BatchConceptCandidateBundle830G3) error {
	if bundle.Contract != conceptBatchContract830G3 || validateBatchRequest830G3(bundle.Request) != nil ||
		bundle.Admission.Contract != "concept-admission.830.g2.v1" ||
		bundle.Admission.Status != "NEEDS_HUMAN" ||
		validateDelta830G3(bundle.Request, bundle.ModelCompileResult.Output) != nil {
		return ErrConceptCandidateBundle830G3
	}
	baseRequestHash, err := compileRequestHash830G3(bundle.Request.BaseRequest)
	if err != nil {
		return ErrConceptCandidateBundle830G3
	}
	compilerContext := map[string]any{
		"request": bundle.Request, "request_sha256": bundle.Request.RequestSHA256,
		"base_request_hash": baseRequestHash, "output_mode": "NEW_MEMBERS_ONLY",
	}
	compilerContextHash, err := batchConceptHash830G3(
		"batch-concept-compile-context.830.g3.v1", compilerContext,
	)
	if err != nil || validateExecution830G3(
		bundle.ModelCompileResult.Execution, bundle.ModelCompileResult.Output, compilerContextHash,
	) != nil {
		return ErrConceptCandidateBundle830G3
	}
	expected, err := composeBatchOutput830G3(bundle.Request, bundle.ModelCompileResult.Output)
	if err != nil || !conceptCanonicalEqual830G2(expected, bundle.CompileResult.Output) ||
		bundle.CompileResult.Execution.Implementation != "base-carry-compiler.830.g3.v1" {
		return ErrConceptCandidateBundle830G3
	}
	modelExecutionHash, err := batchConceptHash830G3(
		"batch-concept-model-execution.830.g3.v1", bundle.ModelCompileResult.Execution,
	)
	if err != nil {
		return ErrConceptCandidateBundle830G3
	}
	modelOutputHash, err := compileOutputHash830G3(bundle.ModelCompileResult.Output)
	if err != nil {
		return ErrConceptCandidateBundle830G3
	}
	carryContextHash, err := batchConceptHash830G3(
		"batch-concept-carry-context.830.g3.v1", map[string]any{
			"request_sha256":                 bundle.Request.RequestSHA256,
			"model_compile_output_hash":      modelOutputHash,
			"model_compile_execution_sha256": modelExecutionHash,
		},
	)
	if err != nil || validateExecution830G3(
		bundle.CompileResult.Execution, bundle.CompileResult.Output, carryContextHash,
	) != nil {
		return ErrConceptCandidateBundle830G3
	}
	finalHash, err := compileOutputHash830G3(expected)
	if err != nil || bundle.ReviewResult.Output.RequestHash != baseRequestHash ||
		bundle.ReviewResult.Output.OutputHash != finalHash || bundle.ReviewResult.Output.Decision == "REJECT" {
		return ErrConceptCandidateBundle830G3
	}
	reviewContextHash, err := batchConceptHash830G3(
		"batch-concept-review-context.830.g3.v1", map[string]any{
			"request": bundle.Request, "candidate": expected,
			"request_sha256":    bundle.Request.RequestSHA256,
			"base_request_hash": baseRequestHash, "output_hash": finalHash,
		},
	)
	if err != nil || validateExecution830G3(
		bundle.ReviewResult.Execution, bundle.ReviewResult.Output, reviewContextHash,
	) != nil {
		return ErrConceptCandidateBundle830G3
	}
	runs := map[string]bool{
		bundle.ModelCompileResult.Execution.RunID: true,
		bundle.CompileResult.Execution.RunID:      true,
		bundle.ReviewResult.Execution.RunID:       true,
	}
	if len(runs) != 3 || validatePageManifest830G3(bundle.Request, expected, bundle.PageManifest) != nil ||
		!hashEqualWithout830G3(bundle.Contract, bundle, "candidate_hash", bundle.CandidateHash) {
		return ErrConceptCandidateBundle830G3
	}
	return nil
}

func validateDelta830G3(
	request BatchConceptCompileRequest830G3, output ConceptCompileOutput830G2,
) error {
	requestHash, err := compileRequestHash830G3(request.BaseRequest)
	if err != nil || output.Contract != "concept-compile-output.830.g2.v1" ||
		output.RequestHash != requestHash || len(output.Fields) != 208 {
		return ErrConceptCandidateBundle830G3
	}
	aligned, err := alignedFields830G3(request)
	if err != nil {
		return ErrConceptCandidateBundle830G3
	}
	carried := map[string]bool{}
	for _, field := range aligned {
		carried[field.EntityID+"\x00"+field.FieldKey] = true
	}
	expected := map[string]bool{}
	for entityID, keys := range request.BaseRequest.RequiredFields {
		for _, key := range keys {
			pair := entityID + "\x00" + key
			if !carried[pair] {
				expected[pair] = true
			}
		}
	}
	objects := map[string]bool{}
	for _, field := range output.Fields {
		pair := field.EntityID + "\x00" + field.FieldKey
		id, idErr := conceptFieldID830G2(field)
		if idErr != nil || !expected[pair] || objects[id] ||
			field.EntityVersion != request.BaseRequest.EntityVersions[field.EntityID] ||
			validateConceptField830G2(field) != nil {
			return ErrConceptCandidateBundle830G3
		}
		objects[id] = true
	}
	if len(objects) != len(expected) {
		return ErrConceptCandidateBundle830G3
	}
	oldDefinitions, oldPages := map[string]bool{}, map[string]bool{}
	for _, definition := range request.BaseRequest.ExistingDefinitions {
		id, _ := conceptDefinitionID830G2(definition)
		oldDefinitions[id] = true
	}
	for _, page := range request.BaseRequest.ExistingPages {
		id, _ := conceptFreePageID830G2(page)
		oldPages[id] = true
	}
	for _, definition := range output.Definitions {
		id, idErr := conceptDefinitionID830G2(definition)
		if idErr != nil || oldDefinitions[id] || objects[id] {
			return ErrConceptCandidateBundle830G3
		}
		objects[id] = true
	}
	for _, page := range output.Pages {
		id, idErr := conceptFreePageID830G2(page)
		if idErr != nil || oldPages[id] || objects[id] {
			return ErrConceptCandidateBundle830G3
		}
		objects[id] = true
	}
	audit := map[string]ConceptAuditDisposition830G2{}
	for _, item := range output.Audit {
		if audit[item.Key].Key != "" || (item.Disposition != "new_page" &&
			item.Disposition != "sense" && item.Disposition != "field_rule") {
			return ErrConceptCandidateBundle830G3
		}
		audit[item.Key] = item
	}
	if len(audit) != len(objects) {
		return ErrConceptCandidateBundle830G3
	}
	for key := range objects {
		if audit[key].Key == "" {
			return ErrConceptCandidateBundle830G3
		}
	}
	if validateDeltaEvidence830G3(request, output) != nil {
		return ErrConceptCandidateBundle830G3
	}
	return nil
}

func validateDeltaEvidence830G3(
	request BatchConceptCompileRequest830G3, output ConceptCompileOutput830G2,
) error {
	entryByID, _, err := corpusIndexes830G3(request.ResolutionInputs.Corpus)
	if err != nil {
		return ErrConceptCandidateBundle830G3
	}
	bindingByEntity := map[string]EntityCompileBinding830G3{}
	for _, binding := range request.EntityBindings {
		bindingByEntity[binding.EntityID] = binding
	}
	baseFields := map[string][]ConceptFieldAssertion830G2{}
	for _, field := range request.BaseRequest.ExistingFields {
		baseFields[field.EntityID] = append(baseFields[field.EntityID], field)
	}
	basePages := map[string][]ConceptFreeWikiPage830G2{}
	for _, page := range request.BaseRequest.ExistingPages {
		basePages[page.EntityID] = append(basePages[page.EntityID], page)
	}
	definitions := map[string]ConceptDefinition830G2{}
	for _, definition := range request.BaseRequest.ExistingDefinitions {
		id, idErr := conceptDefinitionID830G2(definition)
		if idErr != nil {
			return ErrConceptCandidateBundle830G3
		}
		definitions[id] = definition
	}
	allowedFor := func(entityID string) (map[sourceKey830G3]bool, error) {
		binding, exists := bindingByEntity[entityID]
		if !exists {
			return nil, ErrConceptCandidateBundle830G3
		}
		allowed := map[sourceKey830G3]bool{}
		for _, materialID := range binding.SourceMaterialIDs {
			entry, found := entryByID[materialID]
			if !found {
				return nil, ErrConceptCandidateBundle830G3
			}
			for _, block := range entry.Blocks {
				allowed[sourceKeyFor830G3(block)] = true
			}
		}
		linked := map[string]bool{}
		for _, field := range baseFields[entityID] {
			for _, evidence := range field.Evidence {
				allowed[evidenceKeyFor830G3(evidence)] = true
			}
			for _, conceptID := range field.ConceptIDs {
				linked[conceptID] = true
			}
		}
		for _, page := range basePages[entityID] {
			for _, evidence := range page.Evidence {
				allowed[evidenceKeyFor830G3(evidence)] = true
			}
			for _, conceptID := range page.ConceptIDs {
				linked[conceptID] = true
			}
		}
		for conceptID := range linked {
			if definition, found := definitions[conceptID]; found {
				for _, evidence := range definition.Evidence {
					allowed[evidenceKeyFor830G3(evidence)] = true
				}
			}
		}
		return allowed, nil
	}
	checkMember := func(entityID string, evidence []ConceptEvidence830G2) error {
		allowed, allowErr := allowedFor(entityID)
		if allowErr != nil {
			return allowErr
		}
		for _, item := range evidence {
			if verifyConceptEvidence830G2(item, request.BaseRequest.Sources) != nil || !allowed[evidenceKeyFor830G3(item)] {
				return ErrConceptCandidateBundle830G3
			}
		}
		return nil
	}
	for _, field := range output.Fields {
		if checkMember(field.EntityID, field.Evidence) != nil {
			return ErrConceptCandidateBundle830G3
		}
	}
	for _, page := range output.Pages {
		if checkMember(page.EntityID, page.Evidence) != nil {
			return ErrConceptCandidateBundle830G3
		}
	}
	for _, definition := range output.Definitions {
		for _, evidence := range definition.Evidence {
			if verifyConceptEvidence830G2(evidence, request.BaseRequest.Sources) != nil {
				return ErrConceptCandidateBundle830G3
			}
		}
	}
	return nil
}

func composeBatchOutput830G3(
	request BatchConceptCompileRequest830G3, delta ConceptCompileOutput830G2,
) (ConceptCompileOutput830G2, error) {
	aligned, err := alignedFields830G3(request)
	if err != nil {
		return ConceptCompileOutput830G2{}, ErrConceptCandidateBundle830G3
	}
	definitions := append(append([]ConceptDefinition830G2{}, request.BaseRequest.ExistingDefinitions...), delta.Definitions...)
	fields := append(append([]ConceptFieldAssertion830G2{}, aligned...), delta.Fields...)
	pages := append(append([]ConceptFreeWikiPage830G2{}, request.BaseRequest.ExistingPages...), delta.Pages...)
	sort.Slice(definitions, func(i, j int) bool {
		left, _ := conceptDefinitionID830G2(definitions[i])
		right, _ := conceptDefinitionID830G2(definitions[j])
		return left < right
	})
	sort.Slice(fields, func(i, j int) bool {
		if fields[i].EntityID == fields[j].EntityID {
			return fields[i].FieldKey < fields[j].FieldKey
		}
		return fields[i].EntityID < fields[j].EntityID
	})
	sort.Slice(pages, func(i, j int) bool {
		left, _ := conceptFreePageID830G2(pages[i])
		right, _ := conceptFreePageID830G2(pages[j])
		return left < right
	})
	alignedIDs := map[string]bool{}
	for _, row := range request.UnknownFieldKeyAlignments {
		alignedIDs[row.NewMemberID] = true
	}
	audit := make([]ConceptAuditDisposition830G2, 0,
		len(request.BaseRequest.ExistingDefinitions)+len(aligned)+len(request.BaseRequest.ExistingPages)+len(delta.Audit))
	for _, definition := range request.BaseRequest.ExistingDefinitions {
		id, _ := conceptDefinitionID830G2(definition)
		audit = append(audit, ConceptAuditDisposition830G2{Key: id, Disposition: "alias_link", Reason: "BASE_CARRYOVER"})
	}
	for _, field := range aligned {
		id, _ := conceptFieldID830G2(field)
		reason := "BASE_CARRYOVER"
		if alignedIDs[id] {
			reason = "BASE_UNKNOWN_KEY_ALIGNMENT"
		}
		audit = append(audit, ConceptAuditDisposition830G2{Key: id, Disposition: "field_rule", Reason: reason})
	}
	for _, page := range request.BaseRequest.ExistingPages {
		id, _ := conceptFreePageID830G2(page)
		audit = append(audit, ConceptAuditDisposition830G2{Key: id, Disposition: "alias_link", Reason: "BASE_CARRYOVER"})
	}
	audit = append(audit, delta.Audit...)
	sort.Slice(audit, func(i, j int) bool { return audit[i].Key < audit[j].Key })
	result := ConceptCompileOutput830G2{
		Contract: "concept-compile-output.830.g2.v1", RequestHash: delta.RequestHash,
		Definitions: definitions, Fields: fields, Pages: pages, Audit: audit,
		Transformation: delta.Transformation,
	}
	if len(fields) != 342 || validateConceptOutput830G2(request.BaseRequest, result) != nil {
		return ConceptCompileOutput830G2{}, ErrConceptCandidateBundle830G3
	}
	return result, nil
}

type DirectoryField830G3 struct {
	FieldKey   string `json:"field_key"`
	ShortTitle string `json:"short_title"`
	MemberID   string `json:"member_id"`
}

type DirectorySection830G3 struct {
	SectionKey  string                `json:"section_key"`
	DisplayName string                `json:"display_name"`
	Fields      []DirectoryField830G3 `json:"fields"`
}

type EntityDirectoryEntry830G3 struct {
	Contract              string                  `json:"contract"`
	EntityID              string                  `json:"entity_id"`
	EntityVersion         string                  `json:"entity_version"`
	DisplayName           string                  `json:"display_name"`
	Issuer                string                  `json:"issuer"`
	ProductCode           string                  `json:"product_code"`
	PrimaryClassification string                  `json:"primary_classification"`
	SchemaPackID          string                  `json:"schema_pack_id"`
	SchemaVersion         string                  `json:"schema_version"`
	SchemaPackSHA256      string                  `json:"schema_pack_sha256"`
	SchemaPackDisplayName string                  `json:"schema_pack_display_name"`
	ProfileID             string                  `json:"profile_id"`
	ProfileVersion        string                  `json:"profile_version"`
	ProfileSHA256         string                  `json:"profile_sha256"`
	QualityStatus         string                  `json:"quality_status"`
	ReleaseLane           string                  `json:"release_lane"`
	Sections              []DirectorySection830G3 `json:"sections"`
}

func validatePageManifest830G3(
	request BatchConceptCompileRequest830G3, output ConceptCompileOutput830G2,
	manifest BatchConceptPageManifest830G3,
) error {
	if manifest.Contract != "batch-concept-page-manifest.830.g3.v1" ||
		!reflect.DeepEqual(manifest.Audit, output.Audit) || len(manifest.Members) != 354 ||
		!hashEqualWithout830G3("batch-concept-page-members.830.g3.v1",
			struct {
				Members []ConceptPageMember830G2 `json:"members"`
			}{manifest.Members}, "unused", manifest.MembersSHA256) {
		// The members hash payload has no removable field, so verify it directly below.
		membersHash, err := batchConceptHash830G3(
			"batch-concept-page-members.830.g3.v1",
			map[string]any{"members": manifest.Members},
		)
		if err != nil || membersHash != manifest.MembersSHA256 ||
			manifest.Contract != "batch-concept-page-manifest.830.g3.v1" ||
			!reflect.DeepEqual(manifest.Audit, output.Audit) || len(manifest.Members) != 354 {
			return ErrConceptCandidateBundle830G3
		}
	}
	expected, err := projectBatchMembers830G3(request, output)
	if err != nil || !conceptCanonicalEqual830G2(expected, manifest) {
		return ErrConceptCandidateBundle830G3
	}
	return nil
}

func projectBatchMembers830G3(
	request BatchConceptCompileRequest830G3, output ConceptCompileOutput830G2,
) (BatchConceptPageManifest830G3, error) {
	bindings := map[string]EntityCompileBinding830G3{}
	titles := map[string]string{}
	for _, binding := range request.EntityBindings {
		bindings[binding.EntityID] = binding
		entry := catalogEntryForBinding830G3(request.Catalog, binding)
		if entry == nil {
			return BatchConceptPageManifest830G3{}, ErrConceptCandidateBundle830G3
		}
		for _, section := range entry.Profile.Sections {
			for _, field := range section.Fields {
				titles[binding.EntityID+"\x00"+field.FieldKey] = field.ShortTitle
			}
		}
	}
	fieldIndex := map[string]ConceptFieldAssertion830G2{}
	members := make([]ConceptPageMember830G2, 0, len(output.Fields)+len(output.Pages)+len(output.Definitions)+2*len(bindings))
	for _, definition := range output.Definitions {
		id, err := conceptDefinitionID830G2(definition)
		if err != nil {
			return BatchConceptPageManifest830G3{}, ErrConceptCandidateBundle830G3
		}
		payload, _ := json.Marshal(definition)
		members = append(members, ConceptPageMember830G2{
			Kind: "concept", MemberID: id, OwnerID: request.BaseRequest.SpaceID,
			Title: definition.Title, Content: definition.Body, Payload: payload,
		})
	}
	for _, field := range output.Fields {
		id, err := conceptFieldID830G2(field)
		if err != nil {
			return BatchConceptPageManifest830G3{}, ErrConceptCandidateBundle830G3
		}
		fieldIndex[field.EntityID+"\x00"+field.FieldKey] = field
		payload, _ := json.Marshal(field)
		members = append(members, ConceptPageMember830G2{
			Kind: "field_assertion", MemberID: id, OwnerID: field.EntityID,
			Title:   titles[field.EntityID+"\x00"+field.FieldKey],
			Content: conceptFieldContent830G3(field), Payload: payload,
		})
	}
	for _, page := range output.Pages {
		id, err := conceptFreePageID830G2(page)
		if err != nil {
			return BatchConceptPageManifest830G3{}, ErrConceptCandidateBundle830G3
		}
		payload, _ := json.Marshal(page)
		members = append(members, ConceptPageMember830G2{
			Kind: "free_wiki_item", MemberID: id, OwnerID: page.EntityID,
			Title: page.Title, Content: conceptFreePageContent830G3(page), Payload: payload,
		})
	}
	entityIDs := make([]string, 0, len(bindings))
	for entityID := range bindings {
		entityIDs = append(entityIDs, entityID)
	}
	sort.Strings(entityIDs)
	for _, entityID := range entityIDs {
		binding := bindings[entityID]
		entry := catalogEntryForBinding830G3(request.Catalog, binding)
		if entry == nil {
			return BatchConceptPageManifest830G3{}, ErrConceptCandidateBundle830G3
		}
		sections := make([]DirectorySection830G3, 0, len(entry.Profile.Sections))
		sectionNames := make([]string, 0, len(entry.Profile.Sections))
		for _, section := range entry.Profile.Sections {
			fields := make([]DirectoryField830G3, 0, len(section.Fields))
			for _, profileField := range section.Fields {
				field, ok := fieldIndex[entityID+"\x00"+profileField.FieldKey]
				if !ok {
					return BatchConceptPageManifest830G3{}, ErrConceptCandidateBundle830G3
				}
				id, _ := conceptFieldID830G2(field)
				fields = append(fields, DirectoryField830G3{
					FieldKey: profileField.FieldKey, ShortTitle: profileField.ShortTitle, MemberID: id,
				})
			}
			sections = append(sections, DirectorySection830G3{
				SectionKey: section.SectionKey, DisplayName: section.DisplayName, Fields: fields,
			})
			sectionNames = append(sectionNames, section.DisplayName)
		}
		directory := EntityDirectoryEntry830G3{
			Contract: "entity-directory-entry.830.g3.v1", EntityID: entityID,
			EntityVersion: binding.EntityVersion, DisplayName: binding.DisplayName,
			Issuer: binding.Issuer, ProductCode: binding.ProductCode,
			PrimaryClassification: binding.PrimaryClassification,
			SchemaPackID:          binding.SchemaPackID, SchemaVersion: binding.SchemaVersion,
			SchemaPackSHA256:      binding.SchemaPackSHA256,
			SchemaPackDisplayName: entry.Pack.DisplayName,
			ProfileID:             binding.ProfileID, ProfileVersion: binding.ProfileVersion,
			ProfileSHA256: binding.ProfileSHA256, QualityStatus: request.QualityStatus,
			ReleaseLane: request.ReleaseLane, Sections: sections,
		}
		directoryPayload, _ := json.Marshal(directory)
		overviewID, _ := conceptDigest830G2(
			"entity-group", []string{request.BaseRequest.SpaceID, entityID, "entity_overview"},
		)
		members = append(members, ConceptPageMember830G2{
			Kind: "entity_overview", MemberID: "entity_overview_" + overviewID,
			OwnerID: entityID, Title: binding.DisplayName,
			Content: "产品：" + binding.DisplayName + "\n分类：" + binding.PrimaryClassification +
				"\nSchemaPack：" + entry.Pack.DisplayName + "\n栏目：" + strings.Join(sectionNames, "、"),
			Payload: directoryPayload,
		})
		freeIDs := make([]string, 0)
		for _, member := range members {
			if member.OwnerID == entityID && member.Kind == "free_wiki_item" {
				freeIDs = append(freeIDs, member.MemberID)
			}
		}
		sort.Strings(freeIDs)
		freePayload, _ := json.Marshal(map[string]any{"member_ids": freeIDs})
		freeID, _ := conceptDigest830G2(
			"entity-group", []string{request.BaseRequest.SpaceID, entityID, "free_wiki"},
		)
		members = append(members, ConceptPageMember830G2{
			Kind: "free_wiki", MemberID: "free_wiki_" + freeID, OwnerID: entityID,
			Title: "开放知识", Content: "", Payload: freePayload,
		})
	}
	sort.Slice(members, func(i, j int) bool {
		if members[i].Kind == members[j].Kind {
			return members[i].MemberID < members[j].MemberID
		}
		return members[i].Kind < members[j].Kind
	})
	membersHash, err := batchConceptHash830G3(
		"batch-concept-page-members.830.g3.v1", map[string]any{"members": members},
	)
	if err != nil {
		return BatchConceptPageManifest830G3{}, ErrConceptCandidateBundle830G3
	}
	return BatchConceptPageManifest830G3{
		Contract: "batch-concept-page-manifest.830.g3.v1", Members: members,
		MembersSHA256: membersHash, Audit: output.Audit,
	}, nil
}

func conceptFreePageContent830G3(page ConceptFreeWikiPage830G2) string {
	lines := []string{page.Body}
	for _, condition := range page.Conditions {
		lines = append(lines, "条件："+condition)
	}
	for _, exception := range page.Exceptions {
		lines = append(lines, "例外："+exception)
	}
	if page.ValidTime != "" {
		lines = append(lines, "有效期："+page.ValidTime)
	}
	return strings.Join(lines, "\n")
}
