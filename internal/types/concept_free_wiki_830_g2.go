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
	"unicode/utf8"

	"golang.org/x/text/cases"
	"golang.org/x/text/unicode/norm"
)

var ErrConceptCandidateBundle830G2 = errors.New("invalid concept candidate bundle 830 g2")

type ConceptSourceIdentity830G2 struct {
	TenantID       uint64 `json:"tenant_id"`
	SpaceID        string `json:"space_id"`
	RawKBID        string `json:"raw_kb_id"`
	KnowledgeID    string `json:"knowledge_id"`
	ParseAttempt   int64  `json:"parse_attempt"`
	RevisionID     string `json:"revision_id"`
	SourceHash     string `json:"source_hash"`
	ParseHash      string `json:"parse_hash"`
	ParserIdentity string `json:"parser_identity"`
}

type ConceptSourceBlock830G2 struct {
	ConceptSourceIdentity830G2
	BlockID    string `json:"block_id"`
	PageNumber int    `json:"page_number"`
	Text       string `json:"text"`
	SourceType string `json:"source_type"`
}

type ConceptEvidence830G2 struct {
	ConceptSourceIdentity830G2
	SourceType string `json:"source_type"`
	BlockID    string `json:"block_id"`
	PageNumber int    `json:"page_number"`
	OffsetUnit string `json:"offset_unit"`
	Start      int    `json:"start"`
	End        int    `json:"end"`
	Quote      string `json:"quote"`
	QuoteHash  string `json:"quote_hash"`
}

type ConceptDefinition830G2 struct {
	SpaceID      string                 `json:"space_id"`
	CanonicalKey string                 `json:"canonical_key"`
	SenseKey     string                 `json:"sense_key"`
	Title        string                 `json:"title"`
	Body         string                 `json:"body"`
	Evidence     []ConceptEvidence830G2 `json:"evidence"`
	Aliases      []string               `json:"aliases"`
	Origin       string                 `json:"origin"`
}

type ConceptFieldAssertion830G2 struct {
	SpaceID       string                 `json:"space_id"`
	EntityID      string                 `json:"entity_id"`
	FieldKey      string                 `json:"field_key"`
	State         string                 `json:"state"`
	Value         *string                `json:"value"`
	Attempted     bool                   `json:"attempted"`
	UnknownReason *string                `json:"unknown_reason"`
	Evidence      []ConceptEvidence830G2 `json:"evidence"`
	ConceptIDs    []string               `json:"concept_ids"`
	Conditions    []string               `json:"conditions"`
	Exceptions    []string               `json:"exceptions"`
	EntityVersion string                 `json:"entity_version"`
	ValidTime     string                 `json:"valid_time"`
}

type ConceptFreeWikiPage830G2 struct {
	SpaceID       string                 `json:"space_id"`
	EntityID      string                 `json:"entity_id"`
	StableKey     string                 `json:"stable_key"`
	Title         string                 `json:"title"`
	Body          string                 `json:"body"`
	Evidence      []ConceptEvidence830G2 `json:"evidence"`
	ConceptIDs    []string               `json:"concept_ids"`
	Conditions    []string               `json:"conditions"`
	Exceptions    []string               `json:"exceptions"`
	EntityVersion string                 `json:"entity_version"`
	ValidTime     string                 `json:"valid_time"`
}

type ConceptCompileRequest830G2 struct {
	Contract               string                       `json:"contract"`
	RequestID              string                       `json:"request_id"`
	TenantID               uint64                       `json:"tenant_id"`
	SpaceID                string                       `json:"space_id"`
	RawKBID                string                       `json:"raw_kb_id"`
	WikiKBID               string                       `json:"wiki_kb_id"`
	PolicyIdentity         string                       `json:"policy_identity"`
	Sources                []ConceptSourceBlock830G2    `json:"sources"`
	RequiredFields         map[string][]string          `json:"required_fields"`
	ExistingDefinitions    []ConceptDefinition830G2     `json:"existing_definitions"`
	ExistingFields         []ConceptFieldAssertion830G2 `json:"existing_fields"`
	ExistingPages          []ConceptFreeWikiPage830G2   `json:"existing_pages"`
	ExistingEntityVersions map[string]string            `json:"existing_entity_versions"`
	EntityVersions         map[string]string            `json:"entity_versions"`
	SchemaIdentity         string                       `json:"schema_identity"`
	ProfileIdentity        string                       `json:"profile_identity"`
	Purpose                string                       `json:"purpose"`
	BudgetIdentity         string                       `json:"budget_identity"`
	BaseReleaseID          string                       `json:"base_release_id"`
	BaseActivationEpoch    uint64                       `json:"base_activation_epoch"`
}

type ConceptAuditDisposition830G2 struct {
	Key         string `json:"key"`
	Disposition string `json:"disposition"`
	Reason      string `json:"reason"`
}

type ConceptCompileOutput830G2 struct {
	Contract       string                         `json:"contract"`
	RequestHash    string                         `json:"request_hash"`
	Definitions    []ConceptDefinition830G2       `json:"definitions"`
	Fields         []ConceptFieldAssertion830G2   `json:"fields"`
	Pages          []ConceptFreeWikiPage830G2     `json:"pages"`
	Audit          []ConceptAuditDisposition830G2 `json:"audit"`
	Transformation string                         `json:"transformation"`
}

type ConceptExecutionRecord830G2 struct {
	RunID          string `json:"run_id"`
	Implementation string `json:"implementation"`
	ContextHash    string `json:"context_hash"`
	RawOutput      string `json:"raw_output"`
	RawOutputHash  string `json:"raw_output_hash"`
}

type ConceptCompileResult830G2 struct {
	Output    ConceptCompileOutput830G2   `json:"output"`
	Execution ConceptExecutionRecord830G2 `json:"execution"`
}

type ConceptValueScore830G2 struct {
	BusinessValue   int `json:"business_value"`
	Reuse           int `json:"reuse"`
	EvidenceQuality int `json:"evidence_quality"`
	Definability    int `json:"definability"`
	NovelIdentity   int `json:"novel_identity"`
	NameStability   int `json:"name_stability"`
}

func (score *ConceptValueScore830G2) UnmarshalJSON(raw []byte) error {
	var wire struct {
		BusinessValue   *int `json:"business_value"`
		Reuse           *int `json:"reuse"`
		EvidenceQuality *int `json:"evidence_quality"`
		Definability    *int `json:"definability"`
		NovelIdentity   *int `json:"novel_identity"`
		NameStability   *int `json:"name_stability"`
	}
	if strictConceptDecode830G2(raw, &wire) != nil || wire.BusinessValue == nil ||
		wire.Reuse == nil || wire.EvidenceQuality == nil || wire.Definability == nil ||
		wire.NovelIdentity == nil || wire.NameStability == nil {
		return ErrConceptCandidateBundle830G2
	}
	*score = ConceptValueScore830G2{
		BusinessValue: *wire.BusinessValue, Reuse: *wire.Reuse,
		EvidenceQuality: *wire.EvidenceQuality, Definability: *wire.Definability,
		NovelIdentity: *wire.NovelIdentity, NameStability: *wire.NameStability,
	}
	if !validConceptScore830G2(*score) {
		return ErrConceptCandidateBundle830G2
	}
	return nil
}

type ConceptReviewOutput830G2 struct {
	Contract    string                            `json:"contract"`
	RequestHash string                            `json:"request_hash"`
	OutputHash  string                            `json:"output_hash"`
	Decision    string                            `json:"decision"`
	Reasons     []string                          `json:"reasons"`
	PageScores  map[string]ConceptValueScore830G2 `json:"page_scores"`
}

type ConceptReviewResult830G2 struct {
	Output    ConceptReviewOutput830G2    `json:"output"`
	Execution ConceptExecutionRecord830G2 `json:"execution"`
}

type ConceptPageMember830G2 struct {
	Kind     string          `json:"kind"`
	MemberID string          `json:"member_id"`
	OwnerID  string          `json:"owner_id"`
	Title    string          `json:"title"`
	Content  string          `json:"content"`
	Payload  json.RawMessage `json:"payload"`
}

type ConceptPageManifest830G2 struct {
	Contract    string                         `json:"contract"`
	Members     []ConceptPageMember830G2       `json:"members"`
	MembersHash string                         `json:"members_hash"`
	Audit       []ConceptAuditDisposition830G2 `json:"audit"`
}

type ConceptAdmission830G2 struct {
	Contract       string   `json:"contract"`
	Status         string   `json:"status"`
	PendingPageIDs []string `json:"pending_page_ids"`
}

type ConceptCandidateBundle830G2 struct {
	Contract      string                     `json:"contract"`
	Request       ConceptCompileRequest830G2 `json:"request"`
	CompileResult ConceptCompileResult830G2  `json:"compile_result"`
	ReviewResult  ConceptReviewResult830G2   `json:"review_result"`
	PageManifest  ConceptPageManifest830G2   `json:"page_manifest"`
	Admission     *ConceptAdmission830G2     `json:"admission,omitempty"`
	CandidateHash string                     `json:"candidate_hash"`
	admissionSeen bool
}

func (bundle *ConceptCandidateBundle830G2) UnmarshalJSON(raw []byte) error {
	type wire ConceptCandidateBundle830G2
	var decoded wire
	if err := json.Unmarshal(raw, &decoded); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return err
	}
	*bundle = ConceptCandidateBundle830G2(decoded)
	_, bundle.admissionSeen = fields["admission"]
	return nil
}

func (value ConceptDefinition830G2) DefinitionID() (string, error) {
	return conceptDefinitionID830G2(value)
}

func (value ConceptDefinition830G2) DefinitionHash() (string, error) {
	return conceptDefinitionHash830G2(value)
}

func (value ConceptFieldAssertion830G2) FieldAssertionID() (string, error) {
	return conceptFieldID830G2(value)
}

func (value ConceptFreeWikiPage830G2) FreeWikiPageID() (string, error) {
	return conceptFreePageID830G2(value)
}

func ConceptAggregateHash830G2(
	releaseID string,
	activationEpoch uint64,
	definition ConceptDefinition830G2,
	assertions []ConceptFieldAssertion830G2,
) (string, error) {
	if !conceptIdentity830G2(releaseID) || activationEpoch == 0 ||
		validateConceptDefinition830G2(definition) != nil {
		return "", ErrConceptCandidateBundle830G2
	}
	conceptID, err := definition.DefinitionID()
	if err != nil {
		return "", ErrConceptCandidateBundle830G2
	}
	definitionHash, err := definition.DefinitionHash()
	if err != nil {
		return "", ErrConceptCandidateBundle830G2
	}
	matching := make([]ConceptFieldAssertion830G2, 0)
	for _, assertion := range assertions {
		if validateConceptField830G2(assertion) != nil {
			return "", ErrConceptCandidateBundle830G2
		}
		for _, linked := range assertion.ConceptIDs {
			if linked == conceptID {
				matching = append(matching, assertion)
				break
			}
		}
	}
	sort.Slice(matching, func(i, j int) bool {
		if matching[i].EntityID == matching[j].EntityID {
			return matching[i].FieldKey < matching[j].FieldKey
		}
		return matching[i].EntityID < matching[j].EntityID
	})
	return conceptDigest830G2("concept-aggregate", struct {
		ReleaseID       string                       `json:"release_id"`
		ActivationEpoch uint64                       `json:"activation_epoch"`
		ConceptID       string                       `json:"concept_id"`
		DefinitionHash  string                       `json:"definition_hash"`
		Assertions      []ConceptFieldAssertion830G2 `json:"assertions"`
	}{releaseID, activationEpoch, conceptID, definitionHash, matching})
}

func ParseConceptCandidateBundle830G2(raw []byte) (ConceptCandidateBundle830G2, error) {
	var bundle ConceptCandidateBundle830G2
	if strictConceptDecode830G2(raw, &bundle) != nil || validateConceptBundle830G2(bundle) != nil {
		return ConceptCandidateBundle830G2{}, ErrConceptCandidateBundle830G2
	}
	return bundle, nil
}

func (bundle ConceptCandidateBundle830G2) SnapshotMembers() ([]WikiReleaseMemberSnapshot, error) {
	if validateConceptBundle830G2(bundle) != nil {
		return nil, ErrConceptCandidateBundle830G2
	}
	result := make([]WikiReleaseMemberSnapshot, 0, len(bundle.PageManifest.Members))
	for _, member := range bundle.PageManifest.Members {
		digest, err := conceptDigest830G2("concept-member", member)
		if err != nil {
			return nil, ErrConceptCandidateBundle830G2
		}
		result = append(result, WikiReleaseMemberSnapshot{
			Kind: member.Kind, LogicalSlug: member.MemberID, RevisionID: bundle.CandidateHash,
			MemberDigest: digest, Title: member.Title, Content: member.Content,
			Payload: append(json.RawMessage(nil), member.Payload...),
		})
	}
	return result, nil
}

func strictConceptDecode830G2(raw []byte, destination any) error {
	if !conceptJSONUnicodeValid830G2(raw) || !conceptJSONUniqueKeys830G2(raw) || !conceptJSONExactKeys830G2(raw, reflect.TypeOf(destination)) {
		return ErrConceptCandidateBundle830G2
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return err
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return ErrConceptCandidateBundle830G2
	}
	return nil
}

func conceptJSONExactKeys830G2(raw []byte, destination reflect.Type) bool {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	rawMessageType := reflect.TypeOf(json.RawMessage{})
	var walkAny func(json.Token) bool
	var walk func(reflect.Type) bool
	walkAny = func(token json.Token) bool {
		delim, composite := token.(json.Delim)
		if !composite {
			return true
		}
		switch delim {
		case '{':
			for decoder.More() {
				if key, err := decoder.Token(); err != nil {
					return false
				} else if _, ok := key.(string); !ok {
					return false
				}
				value, err := decoder.Token()
				if err != nil || !walkAny(value) {
					return false
				}
			}
			end, err := decoder.Token()
			return err == nil && end == json.Delim('}')
		case '[':
			for decoder.More() {
				value, err := decoder.Token()
				if err != nil || !walkAny(value) {
					return false
				}
			}
			end, err := decoder.Token()
			return err == nil && end == json.Delim(']')
		default:
			return false
		}
	}
	var structFields func(reflect.Type, map[string]reflect.Type) bool
	structFields = func(value reflect.Type, fields map[string]reflect.Type) bool {
		for index := 0; index < value.NumField(); index++ {
			field := value.Field(index)
			if field.PkgPath != "" {
				continue
			}
			tag := field.Tag.Get("json")
			name := strings.Split(tag, ",")[0]
			if name == "-" {
				continue
			}
			fieldType := field.Type
			unwrapped := fieldType
			for unwrapped.Kind() == reflect.Pointer {
				unwrapped = unwrapped.Elem()
			}
			if field.Anonymous && name == "" && unwrapped.Kind() == reflect.Struct {
				if !structFields(unwrapped, fields) {
					return false
				}
				continue
			}
			if name == "" {
				name = field.Name
			}
			if _, duplicate := fields[name]; duplicate {
				return false
			}
			fields[name] = fieldType
		}
		return true
	}
	walk = func(expected reflect.Type) bool {
		for expected.Kind() == reflect.Pointer {
			expected = expected.Elem()
		}
		token, err := decoder.Token()
		if err != nil {
			return false
		}
		if expected == rawMessageType {
			return walkAny(token)
		}
		delim, composite := token.(json.Delim)
		if !composite {
			return true
		}
		switch delim {
		case '{':
			switch expected.Kind() {
			case reflect.Struct:
				fields := make(map[string]reflect.Type)
				if !structFields(expected, fields) {
					return false
				}
				for decoder.More() {
					keyToken, keyErr := decoder.Token()
					key, keyOK := keyToken.(string)
					fieldType, known := fields[key]
					if keyErr != nil || !keyOK || !known || !walk(fieldType) {
						return false
					}
				}
			case reflect.Map:
				if expected.Key().Kind() != reflect.String {
					return false
				}
				for decoder.More() {
					if key, keyErr := decoder.Token(); keyErr != nil {
						return false
					} else if _, keyOK := key.(string); !keyOK || !walk(expected.Elem()) {
						return false
					}
				}
			default:
				return false
			}
			end, endErr := decoder.Token()
			return endErr == nil && end == json.Delim('}')
		case '[':
			if expected.Kind() != reflect.Slice && expected.Kind() != reflect.Array {
				return false
			}
			for decoder.More() {
				if !walk(expected.Elem()) {
					return false
				}
			}
			end, endErr := decoder.Token()
			return endErr == nil && end == json.Delim(']')
		default:
			return false
		}
	}
	if destination == nil || !walk(destination) {
		return false
	}
	var trailing any
	return errors.Is(decoder.Decode(&trailing), io.EOF)
}

func conceptJSONUniqueKeys830G2(raw []byte) bool {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var walk func() bool
	walk = func() bool {
		token, err := decoder.Token()
		if err != nil {
			return false
		}
		delim, composite := token.(json.Delim)
		if !composite {
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
				if _, duplicate := keys[key]; duplicate {
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

func validateConceptBundle830G2(bundle ConceptCandidateBundle830G2) error {
	if (bundle.Contract != "concept-candidate-bundle.830.g2.v1" &&
		bundle.Contract != "concept-candidate-bundle.830.g2.v2") ||
		validateConceptRequest830G2(bundle.Request) != nil ||
		validateConceptOutput830G2(bundle.Request, bundle.CompileResult.Output) != nil ||
		validateExecution830G2(bundle.CompileResult.Execution) != nil ||
		validateExecution830G2(bundle.ReviewResult.Execution) != nil ||
		bundle.CompileResult.Execution.RunID == bundle.ReviewResult.Execution.RunID {
		return ErrConceptCandidateBundle830G2
	}
	requestHash, err := conceptDigest830G2("compile-request", bundle.Request)
	if err != nil || bundle.CompileResult.Output.RequestHash != requestHash {
		return ErrConceptCandidateBundle830G2
	}
	outputHash, err := conceptDigest830G2("compile-output", bundle.CompileResult.Output)
	if err != nil {
		return ErrConceptCandidateBundle830G2
	}
	checked := bundle.ReviewResult.Output
	if checked.Contract != "concept-review-output.830.g2.v1" ||
		checked.RequestHash != requestHash || checked.OutputHash != outputHash {
		return ErrConceptCandidateBundle830G2
	}
	for _, score := range checked.PageScores {
		if !validConceptScore830G2(score) {
			return ErrConceptCandidateBundle830G2
		}
	}
	compileContext := struct {
		Request     ConceptCompileRequest830G2 `json:"request"`
		RequestHash string                     `json:"request_hash"`
	}{bundle.Request, requestHash}
	reviewContext := struct {
		Request     ConceptCompileRequest830G2 `json:"request"`
		Candidate   ConceptCompileOutput830G2  `json:"candidate"`
		RequestHash string                     `json:"request_hash"`
		OutputHash  string                     `json:"output_hash"`
	}{bundle.Request, bundle.CompileResult.Output, requestHash, outputHash}
	compileContextHash, _ := conceptDigest830G2("execution-context", compileContext)
	reviewContextHash, _ := conceptDigest830G2("execution-context", reviewContext)
	if bundle.CompileResult.Execution.ContextHash != compileContextHash ||
		bundle.ReviewResult.Execution.ContextHash != reviewContextHash ||
		validateRawOutput830G2(bundle.CompileResult.Execution.RawOutput, &ConceptCompileOutput830G2{}, bundle.CompileResult.Output) != nil ||
		validateRawOutput830G2(bundle.ReviewResult.Execution.RawOutput, &ConceptReviewOutput830G2{}, checked) != nil {
		return ErrConceptCandidateBundle830G2
	}
	expectedManifest, err := projectConceptMembers830G2(bundle.Request, bundle.CompileResult.Output)
	if err != nil || !conceptCanonicalEqual830G2(expectedManifest, bundle.PageManifest) {
		return ErrConceptCandidateBundle830G2
	}
	if validateConceptAdmission830G2(bundle) != nil {
		return ErrConceptCandidateBundle830G2
	}
	candidateHash, err := conceptHashWithout830G2("candidate-bundle", bundle, "candidate_hash")
	if err != nil || candidateHash != bundle.CandidateHash {
		return ErrConceptCandidateBundle830G2
	}
	return nil
}

func validateConceptAdmission830G2(bundle ConceptCandidateBundle830G2) error {
	novel := novelConceptPages830G2(bundle.Request, bundle.CompileResult.Output)
	if bundle.Contract == "concept-candidate-bundle.830.g2.v1" {
		if bundle.admissionSeen || bundle.Admission != nil || bundle.ReviewResult.Output.Decision != "PASS" {
			return ErrConceptCandidateBundle830G2
		}
		for pageID := range novel {
			score, ok := bundle.ReviewResult.Output.PageScores[pageID]
			if !ok || !validConceptScore830G2(score) || conceptScoreTotal830G2(score) < 80 {
				return ErrConceptCandidateBundle830G2
			}
		}
		return nil
	}
	if bundle.Admission == nil || bundle.Admission.Contract != "concept-admission.830.g2.v1" ||
		bundle.Admission.Status != "NEEDS_HUMAN" ||
		(bundle.ReviewResult.Output.Decision != "PASS" && bundle.ReviewResult.Output.Decision != "NEEDS_HUMAN") {
		return ErrConceptCandidateBundle830G2
	}
	pending := make([]string, 0, len(novel))
	for pageID := range novel {
		score, ok := bundle.ReviewResult.Output.PageScores[pageID]
		if !ok || !validConceptScore830G2(score) || conceptScoreTotal830G2(score) < 60 {
			return ErrConceptCandidateBundle830G2
		}
		if conceptScoreTotal830G2(score) < 80 {
			pending = append(pending, pageID)
		}
	}
	sort.Strings(pending)
	if !reflect.DeepEqual(bundle.Admission.PendingPageIDs, pending) {
		return ErrConceptCandidateBundle830G2
	}
	return nil
}

func validateConceptRequest830G2(request ConceptCompileRequest830G2) error {
	if request.Contract != "concept-compile-request.830.g2.v1" || request.TenantID == 0 ||
		!conceptIdentity830G2(request.RequestID) || !conceptIdentity830G2(request.SpaceID) ||
		!conceptIdentity830G2(request.RawKBID) || !conceptIdentity830G2(request.WikiKBID) ||
		!conceptIdentity830G2(request.PolicyIdentity) || !conceptIdentity830G2(request.SchemaIdentity) ||
		!conceptIdentity830G2(request.ProfileIdentity) || !conceptIdentity830G2(request.BudgetIdentity) ||
		len(request.Sources) == 0 || len(request.RequiredFields) == 0 {
		return ErrConceptCandidateBundle830G2
	}
	seenSources := map[string]bool{}
	for _, source := range request.Sources {
		if validateConceptSource830G2(source) != nil || source.TenantID != request.TenantID ||
			source.SpaceID != request.SpaceID || source.RawKBID != request.RawKBID {
			return ErrConceptCandidateBundle830G2
		}
		key := source.RevisionID + "\x00" + source.BlockID
		if seenSources[key] {
			return ErrConceptCandidateBundle830G2
		}
		seenSources[key] = true
	}
	if len(request.EntityVersions) != len(request.RequiredFields) {
		return ErrConceptCandidateBundle830G2
	}
	for entity, version := range request.EntityVersions {
		if !conceptIdentity830G2(entity) || !conceptIdentity830G2(version) {
			return ErrConceptCandidateBundle830G2
		}
	}
	for entity, version := range request.ExistingEntityVersions {
		if !conceptIdentity830G2(entity) || !conceptIdentity830G2(version) {
			return ErrConceptCandidateBundle830G2
		}
	}
	for entity, fields := range request.RequiredFields {
		if !conceptIdentity830G2(entity) || len(fields) == 0 || !conceptIdentity830G2(request.EntityVersions[entity]) || hasDuplicateConceptStrings830G2(fields) {
			return ErrConceptCandidateBundle830G2
		}
		for _, field := range fields {
			if !conceptIdentity830G2(field) {
				return ErrConceptCandidateBundle830G2
			}
		}
	}
	if validateConceptMembers830G2(request.SpaceID, request.ExistingDefinitions, request.ExistingFields, request.ExistingPages) != nil {
		return ErrConceptCandidateBundle830G2
	}
	for _, field := range request.ExistingFields {
		version, ok := request.ExistingEntityVersions[field.EntityID]
		if !ok || field.EntityVersion != version {
			return ErrConceptCandidateBundle830G2
		}
	}
	for _, page := range request.ExistingPages {
		version, ok := request.ExistingEntityVersions[page.EntityID]
		if !ok || page.EntityVersion != version {
			return ErrConceptCandidateBundle830G2
		}
	}
	return nil
}

func validateConceptOutput830G2(request ConceptCompileRequest830G2, output ConceptCompileOutput830G2) error {
	if output.Contract != "concept-compile-output.830.g2.v1" ||
		(output.Transformation != "EXTRACT" && output.Transformation != "NORMALIZE" && output.Transformation != "COMPRESS" && output.Transformation != "SYNTHESIZE") ||
		validateConceptMembers830G2(request.SpaceID, output.Definitions, output.Fields, output.Pages) != nil {
		return ErrConceptCandidateBundle830G2
	}
	expected := map[string]bool{}
	for entity, fields := range request.RequiredFields {
		for _, field := range fields {
			expected[entity+"\x00"+field] = true
		}
	}
	actual := map[string]bool{}
	for _, field := range output.Fields {
		key := field.EntityID + "\x00" + field.FieldKey
		if actual[key] || !expected[key] || field.EntityVersion != request.EntityVersions[field.EntityID] {
			return ErrConceptCandidateBundle830G2
		}
		actual[key] = true
	}
	if len(actual) != len(expected) {
		return ErrConceptCandidateBundle830G2
	}
	for _, page := range output.Pages {
		if _, ok := request.RequiredFields[page.EntityID]; !ok || page.EntityVersion != request.EntityVersions[page.EntityID] {
			return ErrConceptCandidateBundle830G2
		}
	}
	existingDefs := map[string]ConceptDefinition830G2{}
	for _, definition := range request.ExistingDefinitions {
		id, _ := conceptDefinitionID830G2(definition)
		existingDefs[id] = definition
	}
	linked := map[string]bool{}
	for _, field := range output.Fields {
		for _, id := range field.ConceptIDs {
			linked[id] = true
		}
	}
	for _, page := range output.Pages {
		for _, id := range page.ConceptIDs {
			linked[id] = true
		}
	}
	for _, definition := range output.Definitions {
		id, _ := conceptDefinitionID830G2(definition)
		old, exists := existingDefs[id]
		if exists && (old.Origin == "SCHEMA_DEFINITION" || old.Origin == "EXPERT_REVISION_RECORD") {
			oldHash, _ := conceptDefinitionHash830G2(old)
			newHash, _ := conceptDefinitionHash830G2(definition)
			if oldHash != newHash {
				return ErrConceptCandidateBundle830G2
			}
		}
		if !linked[id] {
			return ErrConceptCandidateBundle830G2
		}
	}
	for _, definition := range output.Definitions {
		for _, evidence := range definition.Evidence {
			if verifyConceptEvidence830G2(evidence, request.Sources) != nil {
				return ErrConceptCandidateBundle830G2
			}
		}
	}
	for _, field := range output.Fields {
		for _, evidence := range field.Evidence {
			if verifyConceptEvidence830G2(evidence, request.Sources) != nil {
				return ErrConceptCandidateBundle830G2
			}
		}
	}
	for _, page := range output.Pages {
		for _, evidence := range page.Evidence {
			if verifyConceptEvidence830G2(evidence, request.Sources) != nil {
				return ErrConceptCandidateBundle830G2
			}
		}
	}
	return validateConceptDispositions830G2(request, output)
}

func validateConceptMembers830G2(spaceID string, definitions []ConceptDefinition830G2, fields []ConceptFieldAssertion830G2, pages []ConceptFreeWikiPage830G2) error {
	conceptIDs, fieldIDs, pageIDs := map[string]bool{}, map[string]bool{}, map[string]bool{}
	for _, definition := range definitions {
		if definition.SpaceID != spaceID || validateConceptDefinition830G2(definition) != nil {
			return ErrConceptCandidateBundle830G2
		}
		id, _ := conceptDefinitionID830G2(definition)
		if conceptIDs[id] {
			return ErrConceptCandidateBundle830G2
		}
		conceptIDs[id] = true
	}
	for _, field := range fields {
		if field.SpaceID != spaceID || validateConceptField830G2(field) != nil {
			return ErrConceptCandidateBundle830G2
		}
		id, _ := conceptFieldID830G2(field)
		if fieldIDs[id] {
			return ErrConceptCandidateBundle830G2
		}
		fieldIDs[id] = true
	}
	for _, page := range pages {
		if page.SpaceID != spaceID || validateConceptPage830G2(page) != nil {
			return ErrConceptCandidateBundle830G2
		}
		id, _ := conceptFreePageID830G2(page)
		if pageIDs[id] {
			return ErrConceptCandidateBundle830G2
		}
		pageIDs[id] = true
	}
	for _, field := range fields {
		for _, id := range field.ConceptIDs {
			if !conceptIDs[id] {
				return ErrConceptCandidateBundle830G2
			}
		}
	}
	for _, page := range pages {
		for _, id := range page.ConceptIDs {
			if !conceptIDs[id] {
				return ErrConceptCandidateBundle830G2
			}
		}
	}
	return nil
}

func validateConceptDefinition830G2(value ConceptDefinition830G2) error {
	if !conceptIdentity830G2(value.SpaceID) || !conceptIdentity830G2(value.CanonicalKey) || !conceptIdentity830G2(value.SenseKey) || value.Title == "" || value.Body == "" || len(value.Evidence) == 0 ||
		(value.Origin != "SCHEMA_DEFINITION" && value.Origin != "MODEL_COMPILE" && value.Origin != "EXPERT_REVISION_RECORD") {
		return ErrConceptCandidateBundle830G2
	}
	for _, alias := range value.Aliases {
		if !conceptIdentity830G2(alias) {
			return ErrConceptCandidateBundle830G2
		}
	}
	for _, evidence := range value.Evidence {
		if validateConceptEvidenceShape830G2(evidence) != nil {
			return ErrConceptCandidateBundle830G2
		}
	}
	return nil
}

func validateConceptField830G2(value ConceptFieldAssertion830G2) error {
	if !conceptIdentity830G2(value.SpaceID) || !conceptIdentity830G2(value.EntityID) || !conceptIdentity830G2(value.FieldKey) || !value.Attempted || hasDuplicateConceptStrings830G2(value.ConceptIDs) {
		return ErrConceptCandidateBundle830G2
	}
	switch value.State {
	case "unknown":
		if value.Value != nil || len(value.Evidence) != 0 || value.UnknownReason == nil || *value.UnknownReason == "" {
			return ErrConceptCandidateBundle830G2
		}
	case "present", "absent_explicitly":
		if value.Value == nil || *value.Value == "" || len(value.Evidence) == 0 || value.UnknownReason != nil {
			return ErrConceptCandidateBundle830G2
		}
	default:
		return ErrConceptCandidateBundle830G2
	}
	for _, evidence := range value.Evidence {
		if validateConceptEvidenceShape830G2(evidence) != nil {
			return ErrConceptCandidateBundle830G2
		}
	}
	return nil
}

func validateConceptPage830G2(value ConceptFreeWikiPage830G2) error {
	if !conceptIdentity830G2(value.SpaceID) || !conceptIdentity830G2(value.EntityID) || !conceptIdentity830G2(value.StableKey) || value.Title == "" || value.Body == "" || len(value.Evidence) == 0 {
		return ErrConceptCandidateBundle830G2
	}
	for _, evidence := range value.Evidence {
		if validateConceptEvidenceShape830G2(evidence) != nil {
			return ErrConceptCandidateBundle830G2
		}
	}
	return nil
}

func validateConceptSource830G2(source ConceptSourceBlock830G2) error {
	if source.TenantID == 0 || source.ParseAttempt <= 0 || source.PageNumber <= 0 || source.Text == "" ||
		!conceptIdentity830G2(source.SpaceID) || !conceptIdentity830G2(source.RawKBID) || !conceptIdentity830G2(source.KnowledgeID) || !conceptIdentity830G2(source.RevisionID) || !conceptIdentity830G2(source.ParserIdentity) || !conceptIdentity830G2(source.BlockID) || !conceptHash830G2(source.SourceHash) || !conceptHash830G2(source.ParseHash) ||
		(source.SourceType != "DOCUMENT" && source.SourceType != "EXPERT_REVISION_RECORD") {
		return ErrConceptCandidateBundle830G2
	}
	return nil
}

func verifyConceptEvidence830G2(evidence ConceptEvidence830G2, sources []ConceptSourceBlock830G2) error {
	if validateConceptEvidenceShape830G2(evidence) != nil {
		return ErrConceptCandidateBundle830G2
	}
	var match *ConceptSourceBlock830G2
	for index := range sources {
		if sources[index].RevisionID == evidence.RevisionID && sources[index].BlockID == evidence.BlockID {
			if match != nil {
				return ErrConceptCandidateBundle830G2
			}
			match = &sources[index]
		}
	}
	if match == nil || evidence.ConceptSourceIdentity830G2 != match.ConceptSourceIdentity830G2 || evidence.SourceType != match.SourceType || evidence.PageNumber != match.PageNumber {
		return ErrConceptCandidateBundle830G2
	}
	runes := []rune(match.Text)
	if evidence.End > len(runes) || utf8.RuneCountInString(evidence.Quote) != evidence.End-evidence.Start || string(runes[evidence.Start:evidence.End]) != evidence.Quote {
		return ErrConceptCandidateBundle830G2
	}
	return nil
}

func validateConceptEvidenceShape830G2(evidence ConceptEvidence830G2) error {
	if evidence.TenantID == 0 || evidence.ParseAttempt <= 0 || evidence.PageNumber <= 0 ||
		evidence.End <= evidence.Start || evidence.Start < 0 || evidence.OffsetUnit != "UNICODE_CODE_POINT" ||
		!conceptIdentity830G2(evidence.SpaceID) || !conceptIdentity830G2(evidence.RawKBID) ||
		!conceptIdentity830G2(evidence.KnowledgeID) || !conceptIdentity830G2(evidence.RevisionID) ||
		!conceptIdentity830G2(evidence.ParserIdentity) || !conceptIdentity830G2(evidence.BlockID) ||
		!conceptHash830G2(evidence.SourceHash) || !conceptHash830G2(evidence.ParseHash) ||
		!conceptHash830G2(evidence.QuoteHash) || evidence.Quote == "" ||
		(evidence.SourceType != "DOCUMENT" && evidence.SourceType != "EXPERT_REVISION_RECORD") ||
		utf8.RuneCountInString(evidence.Quote) != evidence.End-evidence.Start {
		return ErrConceptCandidateBundle830G2
	}
	quoteSum := sha256.Sum256([]byte(evidence.Quote))
	if hex.EncodeToString(quoteSum[:]) != evidence.QuoteHash {
		return ErrConceptCandidateBundle830G2
	}
	return nil
}

func validateExecution830G2(execution ConceptExecutionRecord830G2) error {
	if !conceptIdentity830G2(execution.RunID) || !conceptIdentity830G2(execution.Implementation) || !conceptHash830G2(execution.ContextHash) || !conceptHash830G2(execution.RawOutputHash) {
		return ErrConceptCandidateBundle830G2
	}
	sum := sha256.Sum256([]byte(execution.RawOutput))
	if hex.EncodeToString(sum[:]) != execution.RawOutputHash {
		return ErrConceptCandidateBundle830G2
	}
	return nil
}

func validateRawOutput830G2(raw string, destination any, expected any) error {
	if strictConceptDecode830G2([]byte(raw), destination) != nil || !conceptCanonicalEqual830G2(destination, expected) {
		return ErrConceptCandidateBundle830G2
	}
	return nil
}

func validateConceptDispositions830G2(request ConceptCompileRequest830G2, output ConceptCompileOutput830G2) error {
	objects := map[string]string{}
	for _, d := range output.Definitions {
		id, _ := conceptDefinitionID830G2(d)
		objects[id] = "definition"
	}
	for _, f := range output.Fields {
		id, _ := conceptFieldID830G2(f)
		objects[id] = "field"
	}
	for _, p := range output.Pages {
		id, _ := conceptFreePageID830G2(p)
		objects[id] = "page"
	}
	promoted, seen := map[string]string{}, map[string]bool{}
	for _, audit := range output.Audit {
		if !conceptIdentity830G2(audit.Key) || audit.Reason == "" || seen[audit.Key] || !validDisposition830G2(audit.Disposition) {
			return ErrConceptCandidateBundle830G2
		}
		seen[audit.Key] = true
		if audit.Disposition == "new_page" || audit.Disposition == "update" || audit.Disposition == "sense" || audit.Disposition == "field_rule" || audit.Disposition == "alias_link" {
			promoted[audit.Key] = audit.Disposition
		}
	}
	if len(promoted) != len(objects) {
		return ErrConceptCandidateBundle830G2
	}
	for id, kind := range objects {
		if _, ok := promoted[id]; !ok || kind == "field" && promoted[id] != "field_rule" {
			return ErrConceptCandidateBundle830G2
		}
	}
	existingDefs := map[string]ConceptDefinition830G2{}
	existingPages := map[string]ConceptFreeWikiPage830G2{}
	for _, d := range request.ExistingDefinitions {
		id, _ := conceptDefinitionID830G2(d)
		existingDefs[id] = d
	}
	for _, p := range request.ExistingPages {
		id, _ := conceptFreePageID830G2(p)
		existingPages[id] = p
	}
	for _, d := range output.Definitions {
		id, _ := conceptDefinitionID830G2(d)
		disposition := promoted[id]
		old, exists := existingDefs[id]
		if disposition == "new_page" && exists {
			return ErrConceptCandidateBundle830G2
		}
		if disposition == "sense" {
			found := false
			for _, prior := range request.ExistingDefinitions {
				if prior.CanonicalKey == d.CanonicalKey && prior.SenseKey != d.SenseKey {
					found = true
				}
			}
			if exists || !found {
				return ErrConceptCandidateBundle830G2
			}
		}
		if disposition == "update" && (!exists || conceptCanonicalEqual830G2(old, d)) {
			return ErrConceptCandidateBundle830G2
		}
		if disposition == "alias_link" {
			oldHash, _ := conceptDefinitionHash830G2(old)
			newHash, _ := conceptDefinitionHash830G2(d)
			if !exists || oldHash != newHash {
				return ErrConceptCandidateBundle830G2
			}
		}
		if disposition != "new_page" && disposition != "sense" && disposition != "update" && disposition != "alias_link" {
			return ErrConceptCandidateBundle830G2
		}
	}
	for _, p := range output.Pages {
		id, _ := conceptFreePageID830G2(p)
		disposition := promoted[id]
		old, exists := existingPages[id]
		if disposition == "new_page" && exists || disposition == "update" && (!exists || conceptCanonicalEqual830G2(old, p)) || disposition == "alias_link" && (!exists || !conceptCanonicalEqual830G2(old, p)) {
			return ErrConceptCandidateBundle830G2
		}
		if disposition != "new_page" && disposition != "update" && disposition != "alias_link" {
			return ErrConceptCandidateBundle830G2
		}
	}
	return nil
}

func projectConceptMembers830G2(request ConceptCompileRequest830G2, output ConceptCompileOutput830G2) (ConceptPageManifest830G2, error) {
	members := make([]ConceptPageMember830G2, 0, len(output.Definitions)+len(output.Fields)+len(output.Pages)+2*len(request.RequiredFields))
	for _, d := range output.Definitions {
		id, _ := conceptDefinitionID830G2(d)
		payload, _ := json.Marshal(d)
		members = append(members, ConceptPageMember830G2{"concept", id, request.SpaceID, d.Title, d.Body, payload})
	}
	for _, f := range output.Fields {
		id, _ := conceptFieldID830G2(f)
		content := "未知："
		if f.Value != nil {
			content = *f.Value
		} else if f.UnknownReason != nil {
			content += *f.UnknownReason
		}
		payload, _ := json.Marshal(f)
		members = append(members, ConceptPageMember830G2{"field_assertion", id, f.EntityID, f.FieldKey, content, payload})
	}
	for _, p := range output.Pages {
		id, _ := conceptFreePageID830G2(p)
		payload, _ := json.Marshal(p)
		members = append(members, ConceptPageMember830G2{"free_wiki_item", id, p.EntityID, p.Title, p.Body, payload})
	}
	entities := make([]string, 0, len(request.RequiredFields))
	for entity := range request.RequiredFields {
		entities = append(entities, entity)
	}
	sort.Strings(entities)
	for _, entity := range entities {
		refs, freeRefs := []string{}, []string{}
		for _, member := range members {
			if member.OwnerID == entity {
				refs = append(refs, member.MemberID)
				if member.Kind == "free_wiki_item" {
					freeRefs = append(freeRefs, member.MemberID)
				}
			}
		}
		sort.Strings(refs)
		sort.Strings(freeRefs)
		for _, group := range []struct {
			kind, title string
			refs        []string
		}{{"entity_overview", entity, refs}, {"free_wiki", "开放知识", freeRefs}} {
			idHash, err := conceptDigest830G2("entity-group", []string{request.SpaceID, entity, group.kind})
			if err != nil {
				return ConceptPageManifest830G2{}, err
			}
			payload, _ := json.Marshal(map[string]any{"member_ids": group.refs})
			members = append(members, ConceptPageMember830G2{group.kind, group.kind + "_" + idHash, entity, group.title, "", payload})
		}
	}
	sort.Slice(members, func(i, j int) bool {
		if members[i].Kind == members[j].Kind {
			return members[i].MemberID < members[j].MemberID
		}
		return members[i].Kind < members[j].Kind
	})
	membersHash, err := conceptDigest830G2("page-members", members)
	if err != nil {
		return ConceptPageManifest830G2{}, err
	}
	return ConceptPageManifest830G2{"concept-page-manifest.830.g2.v1", members, membersHash, output.Audit}, nil
}

func conceptDefinitionID830G2(value ConceptDefinition830G2) (string, error) {
	parts := []string{norm.NFC.String(strings.TrimSpace(value.SpaceID)), norm.NFC.String(strings.TrimSpace(cases.Fold().String(value.CanonicalKey))), norm.NFC.String(strings.TrimSpace(cases.Fold().String(value.SenseKey)))}
	for _, part := range parts {
		if part == "" {
			return "", ErrConceptCandidateBundle830G2
		}
	}
	hash, err := conceptDigest830G2("concept-identity", parts)
	return "concept_" + hash, err
}

func conceptFieldID830G2(value ConceptFieldAssertion830G2) (string, error) {
	hash, err := conceptDigest830G2("field-identity", []string{value.SpaceID, value.EntityID, value.FieldKey})
	return "assertion_" + hash, err
}
func conceptFreePageID830G2(value ConceptFreeWikiPage830G2) (string, error) {
	hash, err := conceptDigest830G2("free-identity", []string{value.SpaceID, value.EntityID, value.StableKey})
	return "free_" + hash, err
}

func conceptDefinitionHash830G2(value ConceptDefinition830G2) (string, error) {
	raw, _ := json.Marshal(value)
	var payload map[string]any
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if decoder.Decode(&payload) != nil {
		return "", ErrConceptCandidateBundle830G2
	}
	delete(payload, "aliases")
	return conceptDigest830G2("concept-definition", payload)
}

func novelConceptPages830G2(request ConceptCompileRequest830G2, output ConceptCompileOutput830G2) map[string]bool {
	existing := map[string]string{}
	for _, d := range request.ExistingDefinitions {
		id, _ := conceptDefinitionID830G2(d)
		hash, _ := conceptDefinitionHash830G2(d)
		existing[id] = hash
	}
	result := map[string]bool{}
	for _, d := range output.Definitions {
		id, _ := conceptDefinitionID830G2(d)
		hash, _ := conceptDefinitionHash830G2(d)
		if existing[id] != hash {
			result[id] = true
		}
	}
	for _, p := range output.Pages {
		id, _ := conceptFreePageID830G2(p)
		result[id] = true
	}
	return result
}

func conceptDigest830G2(kind string, value any) (string, error) {
	objectType := kind + ".830.g2.v1"
	if strings.TrimSpace(objectType) == "" || schemaWikiHasControlCharacter(objectType) {
		return "", ErrConceptCandidateBundle830G2
	}
	canonical, err := conceptCanonicalJSON830G2(value)
	if err != nil {
		return "", err
	}
	preimage := append([]byte(schemaWikiHashPrefix), []byte(objectType)...)
	preimage = append(preimage, 0)
	preimage = append(preimage, canonical...)
	sum := sha256.Sum256(preimage)
	return hex.EncodeToString(sum[:]), nil
}

func conceptHashWithout830G2(kind string, value any, hashKey string) (string, error) {
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
	return conceptDigest830G2(kind, payload)
}
func conceptCanonicalEqual830G2(left, right any) bool {
	a, errA := conceptCanonicalJSON830G2(left)
	b, errB := conceptCanonicalJSON830G2(right)
	return errA == nil && errB == nil && bytes.Equal(a, b)
}

func conceptCanonicalJSON830G2(payload any) ([]byte, error) {
	if !conceptCanonicalInputValid830G2(reflect.ValueOf(payload)) {
		return nil, fmt.Errorf("%w: invalid UTF-8", ErrConceptCandidateBundle830G2)
	}
	if conceptHasBinaryFloat830G2(reflect.ValueOf(payload)) {
		return nil, fmt.Errorf("%w: binary float", ErrConceptCandidateBundle830G2)
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var tree any
	if err := decoder.Decode(&tree); err != nil || !conceptCanonicalTreeValid830G2(tree, false) {
		return nil, fmt.Errorf("%w: non-canonical value", ErrConceptCandidateBundle830G2)
	}
	var encoded bytes.Buffer
	encoder := json.NewEncoder(&encoded)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(tree); err != nil {
		return nil, err
	}
	canonical := bytes.TrimSuffix(encoded.Bytes(), []byte("\n"))
	return entityPageUnescapeLineSeparators830G1(canonical), nil
}

func conceptJSONUnicodeValid830G2(raw []byte) bool {
	if !utf8.Valid(raw) {
		return false
	}
	inString := false
	for index := 0; index < len(raw); index++ {
		switch raw[index] {
		case '"':
			inString = !inString
		case '\\':
			if !inString || index+1 >= len(raw) {
				continue
			}
			if raw[index+1] != 'u' {
				index++
				continue
			}
			code, ok := conceptJSONHex4830G2(raw, index+2)
			if !ok {
				return false
			}
			if code >= 0xd800 && code <= 0xdbff {
				if index+11 >= len(raw) || raw[index+6] != '\\' || raw[index+7] != 'u' {
					return false
				}
				low, validLow := conceptJSONHex4830G2(raw, index+8)
				if !validLow || low < 0xdc00 || low > 0xdfff {
					return false
				}
				index += 11
				continue
			}
			if code >= 0xdc00 && code <= 0xdfff {
				return false
			}
			index += 5
		}
	}
	return true
}

func conceptJSONHex4830G2(raw []byte, start int) (uint16, bool) {
	if start+4 > len(raw) {
		return 0, false
	}
	var result uint16
	for _, character := range raw[start : start+4] {
		result <<= 4
		switch {
		case character >= '0' && character <= '9':
			result += uint16(character - '0')
		case character >= 'a' && character <= 'f':
			result += uint16(character-'a') + 10
		case character >= 'A' && character <= 'F':
			result += uint16(character-'A') + 10
		default:
			return 0, false
		}
	}
	return result, true
}

func conceptCanonicalInputValid830G2(value reflect.Value) bool {
	if !value.IsValid() {
		return true
	}
	if value.Type() == reflect.TypeOf(json.RawMessage{}) {
		return conceptJSONUnicodeValid830G2(value.Bytes())
	}
	switch value.Kind() {
	case reflect.Interface, reflect.Pointer:
		return value.IsNil() || conceptCanonicalInputValid830G2(value.Elem())
	case reflect.String:
		return utf8.ValidString(value.String())
	case reflect.Struct:
		for index := 0; index < value.NumField(); index++ {
			if !conceptCanonicalInputValid830G2(value.Field(index)) {
				return false
			}
		}
	case reflect.Map:
		iterator := value.MapRange()
		for iterator.Next() {
			if !conceptCanonicalInputValid830G2(iterator.Key()) || !conceptCanonicalInputValid830G2(iterator.Value()) {
				return false
			}
		}
	case reflect.Slice, reflect.Array:
		for index := 0; index < value.Len(); index++ {
			if !conceptCanonicalInputValid830G2(value.Index(index)) {
				return false
			}
		}
	}
	return true
}

func conceptCanonicalTreeValid830G2(value any, objectKey bool) bool {
	switch typed := value.(type) {
	case nil, bool:
		return true
	case json.Number:
		return !strings.ContainsAny(typed.String(), ".eE")
	case string:
		if !norm.NFC.IsNormalString(typed) {
			return false
		}
		for _, character := range typed {
			if character == 0x7f || character < 0x20 && (objectKey || character != '\t' && character != '\n' && character != '\r') {
				return false
			}
		}
		return true
	case []any:
		for _, item := range typed {
			if !conceptCanonicalTreeValid830G2(item, false) {
				return false
			}
		}
		return true
	case map[string]any:
		for key, item := range typed {
			if !conceptCanonicalTreeValid830G2(key, true) || !conceptCanonicalTreeValid830G2(item, false) {
				return false
			}
		}
		return true
	default:
		return false
	}
}

func conceptHasBinaryFloat830G2(value reflect.Value) bool {
	if !value.IsValid() {
		return false
	}
	switch value.Kind() {
	case reflect.Interface, reflect.Pointer:
		return !value.IsNil() && conceptHasBinaryFloat830G2(value.Elem())
	case reflect.Float32, reflect.Float64:
		return true
	case reflect.Struct:
		for index := 0; index < value.NumField(); index++ {
			if conceptHasBinaryFloat830G2(value.Field(index)) {
				return true
			}
		}
	case reflect.Map:
		iterator := value.MapRange()
		for iterator.Next() {
			if conceptHasBinaryFloat830G2(iterator.Key()) || conceptHasBinaryFloat830G2(iterator.Value()) {
				return true
			}
		}
	case reflect.Slice, reflect.Array:
		for index := 0; index < value.Len(); index++ {
			if conceptHasBinaryFloat830G2(value.Index(index)) {
				return true
			}
		}
	}
	return false
}
func conceptIdentity830G2(value string) bool {
	return value != "" && len(value) <= 512 && strings.TrimSpace(value) == value &&
		norm.NFC.IsNormalString(value) && !schemaWikiHasControlCharacter(value)
}
func conceptHash830G2(value string) bool {
	if len(value) != 64 || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}
func hasDuplicateConceptStrings830G2(values []string) bool {
	seen := map[string]bool{}
	for _, value := range values {
		if seen[value] {
			return true
		}
		seen[value] = true
	}
	return false
}
func validDisposition830G2(value string) bool {
	switch value {
	case "new_page", "update", "sense", "field_rule", "alias_link", "pending", "reject", "mention", "duplicate":
		return true
	}
	return false
}
func validConceptScore830G2(s ConceptValueScore830G2) bool {
	return s.BusinessValue >= 0 && s.BusinessValue <= 25 && s.Reuse >= 0 && s.Reuse <= 20 && s.EvidenceQuality >= 0 && s.EvidenceQuality <= 20 && s.Definability >= 0 && s.Definability <= 15 && s.NovelIdentity >= 0 && s.NovelIdentity <= 10 && s.NameStability >= 0 && s.NameStability <= 10
}
func conceptScoreTotal830G2(s ConceptValueScore830G2) int {
	return s.BusinessValue + s.Reuse + s.EvidenceQuality + s.Definability + s.NovelIdentity + s.NameStability
}
