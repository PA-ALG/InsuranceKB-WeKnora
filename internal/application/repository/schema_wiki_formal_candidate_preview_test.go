package repository

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/Tencent/WeKnora/internal/types"
	"github.com/stretchr/testify/require"
)

const (
	c5TestKBID       = "b1f1764c-443d-46b8-98e3-d5aa5e55eb42"
	c5TestExperiment = "2a92f197-4b33-41de-a6af-c60252d6347d"
)

type c5TestBundleOptions struct {
	missingMember           bool
	extraFile               bool
	symlinkMember           bool
	pathTraversal           bool
	rawMemberDrift          bool
	candidateDrift          bool
	companionDrift          bool
	terminalDrift           bool
	revisionDrift           bool
	sourceDrift             bool
	sourceMissingRangeKey   bool
	sourceUnknownRangeKey   bool
	sourceTextNullRange     bool
	sourceTextBadShape      bool
	sourceTableIntegerRange bool
	duplicateSameDocument   bool
	duplicateCrossField     bool
	duplicateRevision       bool
	duplicatePDF            bool
	evidenceAuthority       bool
	evidenceCandidateDrift  bool
}

type c5TestBundle struct {
	manifestPath string
	key          SchemaWikiFormalCandidatePreviewKey
	selection    SchemaWikiFormalCandidatePreviewContentRequest
	termsPDF     []byte
}

func c5TestSHA(seed byte) string {
	return strings.Repeat(string(seed), 64)
}

func c5TestCanonical(value any) []byte {
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	err := encoder.Encode(value)
	if err != nil {
		panic(err)
	}
	return bytes.TrimSuffix(buffer.Bytes(), []byte("\n"))
}

func c5TestObjectHash(objectType string, value map[string]any) string {
	preimage := append([]byte("weknora.schema-wiki-c5.815.v1\x00"+objectType+"\x00"), c5TestCanonical(value)...)
	sum := sha256.Sum256(preimage)
	return hex.EncodeToString(sum[:])
}

func c5TestRawSHA(raw []byte) string {
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

func c5TestEvidenceAuthority(t *testing.T) types.Schema67CandidateEvidenceAuthorityV1 {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "service", "testdata", "schema_wiki_release_596_1_vector.json"))
	require.NoError(t, err)
	var vector struct {
		Authority types.Schema67CandidateEvidenceAuthorityV1 `json:"candidate_evidence_authority"`
	}
	require.NoError(t, json.Unmarshal(raw, &vector))
	digest, err := types.ComputeSchema67CandidateEvidenceAuthoritySHA256(vector.Authority)
	require.NoError(t, err)
	require.Equal(t, vector.Authority.AuthoritySHA256, digest)
	return vector.Authority
}

func TestSchemaWikiC5CanonicalJSONPreservesUnicodeLineSeparators(t *testing.T) {
	raw, err := schemaWikiC5CanonicalJSON(map[string]any{
		"actual":  "a\u2028b\u2029c",
		"literal": `a\u2028b\u2029c`,
	})
	require.NoError(t, err)
	require.Equal(t,
		[]byte("{\"actual\":\"a\xe2\x80\xa8b\xe2\x80\xa9c\",\"literal\":\"a\\\\u2028b\\\\u2029c\"}"),
		raw,
	)
}

func c5Write0600(t *testing.T, path string, raw []byte) {
	t.Helper()
	require.NoError(t, os.WriteFile(path, raw, 0o600))
}

func c5TestPreview(candidateSHA, companionSHA, terminalSHA, revisionSetSHA string, options c5TestBundleOptions) map[string]any {
	sectionIDs := []string{
		"product-overview", "application-and-contract", "renewal-and-pricing",
		"coverage-and-exclusions", "claims-and-reimbursement",
		"services-and-benefits", "sales-support",
	}
	sectionNames := []string{"产品概览", "投保与合同", "续保与费率", "保障与除外", "理赔与报销", "服务与权益", "销售支持"}
	sections := make([]any, 0, 7)
	fields := make([]any, 0, 67)
	for sectionIndex, sectionID := range sectionIDs {
		fieldIDs := make([]any, 0, 10)
		start := sectionIndex*10 + 1
		end := start + 9
		if sectionIndex == 6 {
			end = 67
		}
		for index := start; index <= end; index++ {
			fieldID := "field-" + twoDigits(index)
			fieldIDs = append(fieldIDs, fieldID)
			field := map[string]any{
				"schema_order": index, "section_id": sectionID, "field_id": fieldID,
				"display_name": "字段" + twoDigits(index), "state": "unknown",
				"value_snapshot": nil, "typed_reason": "NO_VALIDATED_VALUE", "source_selections": []any{},
			}
			if index == 1 {
				fileSHA := c5TestRawSHA([]byte("%PDF-1.7\nterms exact bytes\n"))
				if options.sourceDrift {
					fileSHA = c5TestSHA('9')
				}
				field["state"] = "present"
				field["value_snapshot"] = "已验证值"
				field["typed_reason"] = nil
				quote := "逐字证据¹ & 条件"
				selection := map[string]any{
					"selection_id": "selection-01", "field_id": fieldID, "source_role": "terms",
					"source_revision_id": c5TestSHA('1'), "original_file_sha256": fileSHA,
					"parse_manifest_sha256": c5TestSHA('2'), "page_number": 12,
					"coordinate_space": "PDF_POINTS_TOP_LEFT_V1", "page_width_points": "595.3",
					"page_height_points": "841.9", "bbox": []any{"1", "2", "3", "4"},
					"rects": []any{[]any{"1", "2", "3", "4"}}, "block_id": "block-01",
					"span_id": "span-01", "table_id": nil, "table_slice_id": nil,
					"cell_ids": []any{}, "quote": quote, "quote_sha256": c5TestRawSHA([]byte(quote)),
					"page_text_char_start": 0, "page_text_char_end": 9,
				}
				selections := []any{selection}
				if options.duplicateSameDocument || options.duplicateRevision || options.duplicatePDF {
					duplicate := map[string]any{}
					for key, value := range selection {
						duplicate[key] = value
					}
					quote = "第二页逐字证据"
					duplicate["page_number"] = 13
					duplicate["bbox"] = []any{"5", "6", "7", "8"}
					duplicate["rects"] = []any{[]any{"5", "6", "7", "8"}}
					duplicate["block_id"] = "block-02"
					duplicate["span_id"] = "span-02"
					duplicate["quote"] = quote
					duplicate["quote_sha256"] = c5TestRawSHA([]byte(quote))
					duplicate["page_text_char_start"] = 10
					duplicate["page_text_char_end"] = 18
					if options.duplicateRevision {
						duplicate["source_revision_id"] = c5TestSHA('8')
					}
					if options.duplicatePDF {
						duplicate["original_file_sha256"] = c5TestSHA('9')
					}
					selections = append(selections, duplicate)
				}
				field["source_selections"] = selections
			}
			if index == 2 {
				quote := "表格证据"
				selectionID := "selection-02"
				if options.duplicateCrossField {
					selectionID = "selection-01"
				}
				field["state"] = "absent"
				field["value_snapshot"] = "本产品明确不提供该项保障，详见原文"
				field["typed_reason"] = nil
				field["source_selections"] = []any{map[string]any{
					"selection_id": selectionID, "field_id": fieldID, "source_role": "terms",
					"source_revision_id": c5TestSHA('1'), "original_file_sha256": c5TestRawSHA([]byte("%PDF-1.7\nterms exact bytes\n")),
					"parse_manifest_sha256": c5TestSHA('2'), "page_number": 12,
					"coordinate_space": "PDF_POINTS_TOP_LEFT_V1", "page_width_points": "595.3",
					"page_height_points": "841.9", "bbox": []any{"1", "2", "3", "4"},
					"rects": []any{[]any{"1", "2", "3", "4"}}, "block_id": nil,
					"span_id": nil, "table_id": "table-01", "table_slice_id": "slice-01",
					"cell_ids": []any{"cell-01"}, "quote": quote, "quote_sha256": c5TestRawSHA([]byte(quote)),
					"page_text_char_start": nil, "page_text_char_end": nil,
				}}
			}
			fields = append(fields, field)
		}
		sections = append(sections, map[string]any{
			"section_id": sectionID, "display_name": sectionNames[sectionIndex], "ordered_field_ids": fieldIDs,
		})
	}
	preview := map[string]any{
		"contract":      "schema-wiki-formal-candidate-preview.815.v1",
		"experiment_id": c5TestExperiment, "candidate_sha256": candidateSHA,
		"companion_sha256": companionSHA, "terminal_sha256": terminalSHA,
		"revision_set_sha256": revisionSetSHA, "quality_status": "NOT_EVALUATED",
		"mvp_status": "NOT_ACCEPTED", "publishing": false,
		"coordinate_source_roles":                    []any{"terms"},
		"source_roles_without_coordinate_selections": []any{"brochure", "rate_table"},
		"product":             map[string]any{"entity_id": "ping-an-e-sheng-bao", "entity_version_id": "ping-an-e-sheng-bao@596-1", "product_version_id": "596-1", "display_name": "平安e生保（尊享版）医疗保险"},
		"ordered_section_ids": anyStrings(sectionIDs), "sections": sections, "fields": fields,
	}
	preview["preview_sha256"] = c5TestObjectHash("schema-wiki-formal-candidate-preview.815.v1", preview)
	return preview
}

func TestSchemaWikiFormalCandidatePreviewFieldStateKeepsAbsentValueAndEvidenceDistinct(t *testing.T) {
	absentValue := "本产品明确不提供该项保障，详见原文"
	absent := schemaWikiC5Field{
		State:            "absent",
		ValueSnapshot:    &absentValue,
		SourceSelections: []schemaWikiC5Selection{{SelectionID: "selection-absent"}},
	}
	require.True(t, validSchemaWikiC5FieldState(absent))

	absent.ValueSnapshot = nil
	require.False(t, validSchemaWikiC5FieldState(absent), "absent must retain its verified source value")

	unknownReason := "FIELD_NOT_RECOVERED_AFTER_TARGETED_REPAIR"
	unknown := schemaWikiC5Field{State: "unknown", TypedReason: &unknownReason}
	require.True(t, validSchemaWikiC5FieldState(unknown))
	unknown.ValueSnapshot = &absentValue
	require.False(t, validSchemaWikiC5FieldState(unknown), "unknown must remain null with zero Evidence")
}

func twoDigits(value int) string {
	if value < 10 {
		return "0" + string(rune('0'+value))
	}
	return string([]byte{byte('0' + value/10), byte('0' + value%10)})
}

func anyStrings(values []string) []any {
	out := make([]any, len(values))
	for index, value := range values {
		out[index] = value
	}
	return out
}

func writeC5TestBundle(t *testing.T, options c5TestBundleOptions) c5TestBundle {
	t.Helper()
	dir := t.TempDir()
	require.NoError(t, os.Chmod(dir, 0o700))
	candidateSHA := c5TestSHA('a')
	var evidenceAuthority types.Schema67CandidateEvidenceAuthorityV1
	if options.evidenceAuthority {
		evidenceAuthority = c5TestEvidenceAuthority(t)
		candidateSHA = evidenceAuthority.CandidateSHA256
	}
	if options.candidateDrift {
		candidateSHA = c5TestSHA('8')
	}
	companionSHA := c5TestSHA('b')
	terminalSHA := c5TestSHA('c')
	revisionSetSHA := c5TestSHA('d')
	if options.companionDrift {
		companionSHA = c5TestSHA('7')
	}
	if options.terminalDrift {
		terminalSHA = c5TestSHA('6')
	}
	if options.revisionDrift {
		revisionSetSHA = c5TestSHA('5')
	}
	termsPDF := []byte("%PDF-1.7\nterms exact bytes\n")
	brochurePDF := []byte("%PDF-1.7\nbrochure exact bytes\n")
	ratePDF := []byte("%PDF-1.7\nrate exact bytes\n")
	preview := c5TestPreview(candidateSHA, companionSHA, terminalSHA, revisionSetSHA, options)
	textSource := preview["fields"].([]any)[0].(map[string]any)["source_selections"].([]any)[0].(map[string]any)
	tableSource := preview["fields"].([]any)[1].(map[string]any)["source_selections"].([]any)[0].(map[string]any)
	switch {
	case options.sourceMissingRangeKey:
		delete(textSource, "page_text_char_start")
	case options.sourceUnknownRangeKey:
		textSource["unexpected"] = true
	case options.sourceTextNullRange:
		textSource["page_text_char_end"] = nil
	case options.sourceTextBadShape:
		textSource["page_text_char_start"] = "0"
	case options.sourceTableIntegerRange:
		tableSource["page_text_char_start"] = 0
	}
	delete(preview, "preview_sha256")
	preview["preview_sha256"] = c5TestObjectHash("schema-wiki-formal-candidate-preview.815.v1", preview)
	candidateMemberSHA := c5TestSHA('a')
	if options.evidenceAuthority {
		candidateMemberSHA = candidateSHA
	}
	candidateRaw := c5TestCanonical(map[string]any{"contract": "candidate", "candidate_sha256": candidateMemberSHA})
	companionRaw := c5TestCanonical(map[string]any{"contract": "companion", "candidate_sha256": candidateMemberSHA, "companion_sha256": c5TestSHA('b')})
	fieldManifestRaw := c5TestCanonical(map[string]any{"contract": "field-attempt", "manifest_sha256": c5TestSHA('e'), "experiment_id": c5TestExperiment, "terminal_sha256": c5TestSHA('c'), "coordinate_evidence_companion_sha256": c5TestSHA('b'), "revision_set_sha256": c5TestSHA('d')})
	derivationRaw := c5TestCanonical(map[string]any{"contract": "derivation", "manifest_sha256": c5TestSHA('e'), "terminal_sha256": c5TestSHA('c'), "status": "PASS"})
	members := map[string][]byte{
		"preview.json":                       c5TestCanonical(preview),
		"formal-candidate.json":              candidateRaw,
		"coordinate-evidence-companion.json": companionRaw,
		"terminal.json":                      c5TestCanonical(map[string]any{"contract": "terminal", "experiment_id": c5TestExperiment, "terminal_sha256": c5TestSHA('c'), "coordinate_evidence_companion_sha256": c5TestSHA('b'), "revision_set_sha256": c5TestSHA('d'), "status": "SUCCEEDED"}),
		"field-attempt-manifest.json":        fieldManifestRaw,
		"formal-derivation-validation.json":  derivationRaw,
		"result-manifest.json": c5TestCanonical(map[string]any{
			"contract": "result", "identities": map[string]any{"experiment_id": c5TestExperiment},
			"candidate": map[string]any{
				"candidate_internal_sha256": candidateMemberSHA, "candidate_external_sha256": c5TestRawSHA(candidateRaw),
				"coordinate_companion_internal_sha256": c5TestSHA('b'), "coordinate_companion_external_sha256": c5TestRawSHA(companionRaw),
				"field_attempt_manifest_external_sha256": c5TestRawSHA(fieldManifestRaw),
				"derivation_validation_external_sha256":  c5TestRawSHA(derivationRaw),
			}, "terminal": map[string]any{"internal_sha256": c5TestSHA('c'), "status": "SUCCEEDED"},
		}),
		"terms.pdf": termsPDF, "brochure.pdf": brochurePDF, "rate_table.pdf": ratePDF,
	}
	if options.evidenceAuthority {
		if options.evidenceCandidateDrift {
			evidenceAuthority.CandidateSHA256 = c5TestSHA('9')
			digest, digestErr := types.ComputeSchema67CandidateEvidenceAuthoritySHA256(evidenceAuthority)
			require.NoError(t, digestErr)
			evidenceAuthority.AuthoritySHA256 = digest
		}
		members["candidate-evidence-authority.json"] = c5TestCanonical(evidenceAuthority)
	}
	roles := []struct {
		role, pdfName string
		pdf           []byte
		revision      string
	}{
		{"terms", "terms.pdf", termsPDF, c5TestSHA('1')},
		{"brochure", "brochure.pdf", brochurePDF, c5TestSHA('3')},
		{"rate_table", "rate_table.pdf", ratePDF, c5TestSHA('4')},
	}
	items := make([]any, 0, 3)
	for _, role := range roles {
		manifestName := role.role + ".manifest.json"
		roleManifest := map[string]any{
			"contract": "weknora.ec.revision-item.v1", "role": role.role,
			"tenant_id": 10003, "knowledge_base_id": c5TestKBID,
			"compiler_source_revision_id": role.revision, "file_sha256": c5TestRawSHA(role.pdf),
			"file_size": len(role.pdf), "material_file": role.pdfName, "page_count": 39,
		}
		roleManifest["manifest_self_sha256"] = c5TestObjectHash("revision-item", roleManifest)
		members[manifestName] = c5TestCanonical(roleManifest)
		items = append(items, map[string]any{
			"role": role.role, "manifest_file": manifestName,
			"manifest_file_sha256": c5TestRawSHA(members[manifestName]),
			"manifest_self_sha256": roleManifest["manifest_self_sha256"],
			"material_file":        role.pdfName, "material_file_sha256": c5TestRawSHA(role.pdf),
		})
	}
	revisionSet := map[string]any{
		"contract": "weknora.ec.revision-set.v1", "tenant_id": 10003,
		"knowledge_base_id": c5TestKBID, "ordered_roles": []any{"terms", "brochure", "rate_table"},
		"items": items, "revision_set_sha256": c5TestSHA('d'),
	}
	members["revision-set.json"] = c5TestCanonical(revisionSet)
	orderedNames := []string{
		"preview.json", "formal-candidate.json", "coordinate-evidence-companion.json",
	}
	if options.evidenceAuthority {
		orderedNames = append(orderedNames, "candidate-evidence-authority.json")
	}
	orderedNames = append(orderedNames,
		"terminal.json",
		"field-attempt-manifest.json", "formal-derivation-validation.json", "result-manifest.json",
		"revision-set.json", "terms.manifest.json", "terms.pdf", "brochure.manifest.json",
		"brochure.pdf", "rate_table.manifest.json", "rate_table.pdf",
	)
	manifestMembers := make([]any, 0, len(orderedNames))
	for _, name := range orderedNames {
		raw := members[name]
		manifestMembers = append(manifestMembers, map[string]any{
			"name": name, "sha256": c5TestRawSHA(raw), "size_bytes": len(raw),
		})
	}
	if options.missingMember {
		manifestMembers = manifestMembers[:len(manifestMembers)-1]
	}
	if options.pathTraversal {
		manifestMembers[0].(map[string]any)["name"] = "../preview.json"
	}
	manifest := map[string]any{
		"contract": "schema-wiki-formal-candidate-preview-bundle.815.v1", "tenant_id": 10003,
		"wiki_kb_id": c5TestKBID, "experiment_id": c5TestExperiment,
		"candidate_sha256": candidateSHA, "candidate_file_sha256": c5TestRawSHA(members["formal-candidate.json"]),
		"companion_sha256": companionSHA, "companion_file_sha256": c5TestRawSHA(members["coordinate-evidence-companion.json"]),
		"terminal_sha256": terminalSHA, "terminal_file_sha256": c5TestRawSHA(members["terminal.json"]),
		"field_attempt_manifest_sha256":       c5TestRawSHA(members["field-attempt-manifest.json"]),
		"formal_derivation_validation_sha256": c5TestRawSHA(members["formal-derivation-validation.json"]),
		"revision_set_sha256":                 revisionSetSHA, "quality_status": "NOT_EVALUATED",
		"mvp_status": "NOT_ACCEPTED", "publishing": false, "members": manifestMembers,
	}
	if options.evidenceAuthority {
		manifest["candidate_evidence_authority_sha256"] = evidenceAuthority.AuthoritySHA256
		manifest["candidate_evidence_authority_file_sha256"] = c5TestRawSHA(members["candidate-evidence-authority.json"])
	}
	manifest["manifest_sha256"] = c5TestObjectHash("schema-wiki-formal-candidate-preview-bundle.815.v1", manifest)
	for name, raw := range members {
		if options.symlinkMember && name == "terms.pdf" {
			target := filepath.Join(dir, "symlink-target")
			c5Write0600(t, target, raw)
			require.NoError(t, os.Symlink(target, filepath.Join(dir, name)))
			continue
		}
		c5Write0600(t, filepath.Join(dir, name), raw)
	}
	if options.rawMemberDrift {
		c5Write0600(t, filepath.Join(dir, "formal-candidate.json"), []byte(`{"candidate_sha256":"drift"}`))
	}
	if options.extraFile {
		c5Write0600(t, filepath.Join(dir, "current"), []byte("forbidden"))
	}
	manifestPath := filepath.Join(dir, "manifest.json")
	c5Write0600(t, manifestPath, c5TestCanonical(manifest))
	version := manifest["manifest_sha256"].(string)
	return c5TestBundle{
		manifestPath: manifestPath,
		key:          SchemaWikiFormalCandidatePreviewKey{KBID: c5TestKBID, ExperimentID: c5TestExperiment, VersionIdentity: version},
		selection:    SchemaWikiFormalCandidatePreviewContentRequest{FieldID: "field-01", SelectionID: "selection-01"},
		termsPDF:     termsPDF,
	}
}

func TestSchemaWikiFormalCandidatePreviewRegistryRoundTripsCandidateEvidenceAuthority(t *testing.T) {
	bundle := writeC5TestBundle(t, c5TestBundleOptions{evidenceAuthority: true})
	registry, err := NewSchemaWikiFormalCandidatePreviewRegistry(bundle.manifestPath)
	require.NoError(t, err)

	authority, err := registry.ReadCandidateEvidenceAuthorityExact(10003, bundle.key)
	require.NoError(t, err)
	expected := c5TestEvidenceAuthority(t)
	require.Equal(t, expected, authority)
	require.Equal(t, expected.CandidateSHA256, authority.CandidateSHA256)
	require.Equal(t, expected.AuthoritySHA256, authority.AuthoritySHA256)

	authority.JoinReceipts[0].FieldID = "changed-after-read"
	again, err := registry.ReadCandidateEvidenceAuthorityExact(10003, bundle.key)
	require.NoError(t, err)
	require.Equal(t, expected.JoinReceipts[0].FieldID, again.JoinReceipts[0].FieldID)
}

func TestSchemaWikiFormalCandidatePreviewRegistryRejectsEvidenceAuthorityCandidateDrift(t *testing.T) {
	bundle := writeC5TestBundle(t, c5TestBundleOptions{
		evidenceAuthority: true, evidenceCandidateDrift: true,
	})
	registry, err := NewSchemaWikiFormalCandidatePreviewRegistry(bundle.manifestPath)
	require.ErrorIs(t, err, ErrSchemaWikiFormalCandidatePreviewBindingMismatch)
	require.Nil(t, registry)
}

func TestSchemaWikiFormalCandidatePreviewRegistryReadsExactTupleAndPDFCopy(t *testing.T) {
	bundle := writeC5TestBundle(t, c5TestBundleOptions{})
	dirInfo, err := os.Stat(filepath.Dir(bundle.manifestPath))
	require.NoError(t, err)
	require.Equal(t, os.FileMode(0o700), dirInfo.Mode().Perm())
	registry, err := NewSchemaWikiFormalCandidatePreviewRegistry(bundle.manifestPath)
	require.NoError(t, err)
	record, err := registry.ReadExact(10003, bundle.key)
	require.NoError(t, err)
	require.Equal(t, bundle.key.VersionIdentity, record.ManifestSHA256)
	require.Equal(t, c5TestSHA('a'), record.CandidateSHA256)
	require.NotEmpty(t, record.Preview)

	content, err := registry.ReadContentExact(10003, bundle.key, bundle.selection)
	require.NoError(t, err)
	require.Equal(t, bundle.termsPDF, content.Bytes)
	content.Bytes[0] = 'X'
	again, err := registry.ReadContentExact(10003, bundle.key, bundle.selection)
	require.NoError(t, err)
	require.Equal(t, bundle.termsPDF, again.Bytes, "returned bytes must be a copy")

	record.Preview[0] = 'X'
	againRecord, err := registry.ReadExact(10003, bundle.key)
	require.NoError(t, err)
	require.Equal(t, byte('{'), againRecord.Preview[0], "returned preview must be a copy")
}

func TestSchemaWikiFormalCandidatePreviewRegistryBuildsExactIsolatedR1Members(t *testing.T) {
	bundle := writeC5TestBundle(t, c5TestBundleOptions{})
	registry, err := NewSchemaWikiFormalCandidatePreviewRegistry(bundle.manifestPath)
	require.NoError(t, err)

	members, err := registry.ReadReleaseMembersExact(10003, bundle.key)
	require.NoError(t, err)
	require.Len(t, members, 75)
	require.Equal(t, "root", members[0].Kind)
	require.Equal(t, "root:ping-an-e-sheng-bao@596-1", members[0].LogicalSlug)
	for index := 0; index < 7; index++ {
		require.Equal(t, "section", members[index+1].Kind)
		require.Equal(t, "section:"+schemaWikiC5SectionIDs[index], members[index+1].LogicalSlug)
	}
	for index := 0; index < 67; index++ {
		member := members[index+8]
		require.Equal(t, "field", member.Kind)
		require.Equal(t, "field-"+twoDigits(index+1), strings.TrimPrefix(member.LogicalSlug, "field:"))
	}
	for _, member := range members {
		require.Equal(t, bundle.key.VersionIdentity, member.RevisionID)
		require.Equal(t, c5TestRawSHA(member.Payload), member.MemberDigest)
		require.Equal(t, string(member.Payload), member.Content)
		var payload map[string]any
		require.NoError(t, json.Unmarshal(member.Payload, &payload))
		require.Equal(t, "schema-wiki-isolated-r1-member.815.v1", payload["contract"])
		require.Equal(t, "NOT_EVALUATED", payload["quality_status"])
		require.Equal(t, "NOT_ACCEPTED", payload["mvp_status"])
		require.Equal(t, "NOT_FOR_PRODUCTION", payload["production_status"])
		require.Equal(t, false, payload["publishing"])
	}

	members[0].Payload[0] = 'X'
	again, err := registry.ReadReleaseMembersExact(10003, bundle.key)
	require.NoError(t, err)
	require.Equal(t, byte('{'), again[0].Payload[0], "returned release members must be copies")

	wrong := bundle.key
	wrong.VersionIdentity = c5TestSHA('f')
	_, err = registry.ReadReleaseMembersExact(10003, wrong)
	require.ErrorIs(t, err, ErrSchemaWikiFormalCandidatePreviewNotFound)
}

func TestSchemaWikiFormalCandidatePreviewRegistryAllowsRepeatedSelectionForSameDocument(t *testing.T) {
	bundle := writeC5TestBundle(t, c5TestBundleOptions{duplicateSameDocument: true})

	registry, err := NewSchemaWikiFormalCandidatePreviewRegistry(bundle.manifestPath)
	require.NoError(t, err)
	record, err := registry.ReadExact(10003, bundle.key)
	require.NoError(t, err)
	var preview schemaWikiC5Preview
	require.True(t, decodeSchemaWikiC5Exact(record.Preview, &preview))
	require.Len(t, preview.Fields[0].SourceSelections, 2)
	require.Equal(t, uint64(12), preview.Fields[0].SourceSelections[0].PageNumber)
	require.Equal(t, uint64(13), preview.Fields[0].SourceSelections[1].PageNumber)
	require.Equal(t,
		preview.Fields[0].SourceSelections[0].SelectionID,
		preview.Fields[0].SourceSelections[1].SelectionID,
	)

	content, err := registry.ReadContentExact(10003, bundle.key, bundle.selection)
	require.NoError(t, err)
	require.Equal(t, bundle.termsPDF, content.Bytes)
}

func TestSchemaWikiFormalCandidatePreviewRegistryRejectsRepeatedSelectionAcrossDocumentBindings(t *testing.T) {
	for name, options := range map[string]c5TestBundleOptions{
		"field":    {duplicateCrossField: true},
		"revision": {duplicateRevision: true},
		"PDF":      {duplicatePDF: true},
	} {
		t.Run(name, func(t *testing.T) {
			bundle := writeC5TestBundle(t, options)
			registry, err := NewSchemaWikiFormalCandidatePreviewRegistry(bundle.manifestPath)
			require.ErrorIs(t, err, ErrSchemaWikiFormalCandidatePreviewBindingMismatch)
			require.Nil(t, registry)
		})
	}
}

func TestSchemaWikiFormalCandidatePreviewRegistryReadsFrozenRealBundle(t *testing.T) {
	manifestPath := os.Getenv("WEKNORA_C5_REAL_BUNDLE_MANIFEST")
	if manifestPath == "" {
		t.Skip("set WEKNORA_C5_REAL_BUNDLE_MANIFEST to the frozen C5 manifest")
	}
	manifestRaw, err := readSchemaWikiC5Regular0600(manifestPath)
	require.NoError(t, err)
	var manifest schemaWikiC5ManifestWire
	require.True(t, decodeSchemaWikiC5Exact(manifestRaw, &manifest), "manifest must be a closed object")
	require.True(t, validSchemaWikiC5Manifest(manifest, manifestRaw), "manifest self-hash equation must validate")
	memberNames := schemaWikiC5ManifestMemberNames(manifest)
	require.NotNil(t, memberNames)
	members := make(map[string][]byte, len(memberNames))
	for index, name := range memberNames {
		raw, readErr := readSchemaWikiC5Regular0600(filepath.Join(filepath.Dir(manifestPath), name))
		require.NoError(t, readErr, name)
		require.Equal(t, manifest.Members[index].SHA256, c5RawSHA256(raw), name+" file hash")
		members[name] = raw
	}
	var diagnosticPreview schemaWikiC5Preview
	require.True(t, decodeSchemaWikiC5Exact(members["preview.json"], &diagnosticPreview), "preview must be a closed object")
	require.Equal(t, manifest.ExperimentID, diagnosticPreview.ExperimentID, "preview experiment binding")
	require.Equal(t, manifest.CandidateSHA256, diagnosticPreview.CandidateSHA256, "preview Candidate binding")
	require.Equal(t, manifest.CompanionSHA256, diagnosticPreview.CompanionSHA256, "preview companion binding")
	require.Equal(t, manifest.TerminalSHA256, diagnosticPreview.TerminalSHA256, "preview Terminal binding")
	require.Equal(t, manifest.RevisionSetSHA256, diagnosticPreview.RevisionSetSHA256, "preview RevisionSet binding")
	var previewHashValue map[string]any
	require.True(t, decodeSchemaWikiC5Map(members["preview.json"], &previewHashValue))
	delete(previewHashValue, "preview_sha256")
	require.Equal(t, diagnosticPreview.PreviewSHA256,
		c5ObjectSHA256(schemaWikiC5PreviewContract, previewHashValue), "preview self-hash equation")
	for _, field := range diagnosticPreview.Fields {
		require.True(t, validSchemaWikiC5FieldState(field), "field state contract: %s", field.FieldID)
		for _, selection := range field.SourceSelections {
			require.True(t, validSchemaWikiC5Selection(selection, field.FieldID), "selection contract: %s/%s", field.FieldID, selection.SelectionID)
		}
	}
	preview, _, err := validateSchemaWikiC5Preview(members["preview.json"], manifest)
	require.NoError(t, err, "preview binding equations")
	_, err = validateSchemaWikiC5Members(manifest, members, preview)
	require.NoError(t, err, "cross-member binding equations")
	registry, err := NewSchemaWikiFormalCandidatePreviewRegistry(manifestPath)
	require.NoError(t, err)
	record, err := registry.ReadExact(10003, SchemaWikiFormalCandidatePreviewKey{
		KBID:            manifest.WikiKBID,
		ExperimentID:    manifest.ExperimentID,
		VersionIdentity: manifest.ManifestSHA256,
	})
	require.NoError(t, err)
	require.Equal(t, manifest.CandidateSHA256, record.CandidateSHA256)
	require.NotEmpty(t, record.Preview)
}

func TestSchemaWikiFormalCandidatePreviewRegistryReadsRepeatedSelectionRealBundle(t *testing.T) {
	manifestPath := os.Getenv("WEKNORA_C5_REAL_BUNDLE_MANIFEST")
	if manifestPath == "" {
		t.Skip("set WEKNORA_C5_REAL_BUNDLE_MANIFEST to the frozen C5 manifest")
	}
	manifestRaw, err := readSchemaWikiC5Regular0600(manifestPath)
	require.NoError(t, err)
	var manifest schemaWikiC5ManifestWire
	require.True(t, decodeSchemaWikiC5Exact(manifestRaw, &manifest))
	registry, err := NewSchemaWikiFormalCandidatePreviewRegistry(manifestPath)
	require.NoError(t, err)
	key := SchemaWikiFormalCandidatePreviewKey{
		KBID: manifest.WikiKBID, ExperimentID: manifest.ExperimentID,
		VersionIdentity: manifest.ManifestSHA256,
	}
	record, err := registry.ReadExact(manifest.TenantID, key)
	require.NoError(t, err)
	var preview schemaWikiC5Preview
	require.True(t, decodeSchemaWikiC5Exact(record.Preview, &preview))
	seen := make(map[string]schemaWikiC5Selection)
	var repeated *schemaWikiC5Selection
	for _, field := range preview.Fields {
		for index := range field.SourceSelections {
			selection := &field.SourceSelections[index]
			if first, ok := seen[selection.SelectionID]; ok {
				require.Equal(t, first.FieldID, selection.FieldID)
				require.Equal(t, first.SourceRole, selection.SourceRole)
				require.Equal(t, first.SourceRevisionID, selection.SourceRevisionID)
				require.Equal(t, first.OriginalFileSHA256, selection.OriginalFileSHA256)
				repeated = selection
				break
			}
			seen[selection.SelectionID] = *selection
		}
		if repeated != nil {
			break
		}
	}
	require.NotNil(t, repeated, "the frozen bundle must preserve a cross-page repeated selection")
	content, err := registry.ReadContentExact(manifest.TenantID, key,
		SchemaWikiFormalCandidatePreviewContentRequest{
			FieldID: repeated.FieldID, SelectionID: repeated.SelectionID,
		})
	require.NoError(t, err)
	expectedPDF, err := os.ReadFile(filepath.Join(filepath.Dir(manifestPath), repeated.SourceRole+".pdf"))
	require.NoError(t, err)
	require.Equal(t, expectedPDF, content.Bytes)
	require.Equal(t, repeated.OriginalFileSHA256, c5RawSHA256(content.Bytes))
}

func TestSchemaWikiFormalCandidatePreviewRegistryRejectsInvalidMembersAndSources(t *testing.T) {
	for name, options := range map[string]c5TestBundleOptions{
		"missing member": {missingMember: true}, "extra file": {extraFile: true},
		"symlink member": {symlinkMember: true}, "path traversal": {pathTraversal: true},
		"raw member drift": {rawMemberDrift: true}, "candidate tuple drift": {candidateDrift: true},
		"companion tuple drift": {companionDrift: true}, "terminal tuple drift": {terminalDrift: true},
		"revision tuple drift": {revisionDrift: true}, "source PDF drift after full rehash": {sourceDrift: true},
	} {
		t.Run(name, func(t *testing.T) {
			bundle := writeC5TestBundle(t, options)
			registry, err := NewSchemaWikiFormalCandidatePreviewRegistry(bundle.manifestPath)
			require.ErrorIs(t, err, ErrSchemaWikiFormalCandidatePreviewBindingMismatch)
			require.Nil(t, registry)
		})
	}
}

func TestSchemaWikiFormalCandidatePreviewRegistryRejectsInvalidSourceRanges(t *testing.T) {
	for name, options := range map[string]c5TestBundleOptions{
		"missing range key":      {sourceMissingRangeKey: true},
		"unknown range key":      {sourceUnknownRangeKey: true},
		"text null range":        {sourceTextNullRange: true},
		"text range wrong shape": {sourceTextBadShape: true},
		"table integer range":    {sourceTableIntegerRange: true},
	} {
		t.Run(name, func(t *testing.T) {
			bundle := writeC5TestBundle(t, options)
			registry, err := NewSchemaWikiFormalCandidatePreviewRegistry(bundle.manifestPath)
			require.ErrorIs(t, err, ErrSchemaWikiFormalCandidatePreviewBindingMismatch)
			require.Nil(t, registry, "invalid bundle must make zero registry insertions")
		})
	}
}

func TestSchemaWikiFormalCandidatePreviewRegistryEmptyConfigurationKeepsRegistryEmpty(t *testing.T) {
	registry, err := NewSchemaWikiFormalCandidatePreviewRegistry("")
	require.NoError(t, err)
	require.NotNil(t, registry)
	_, err = registry.ReadExact(10003, SchemaWikiFormalCandidatePreviewKey{
		KBID: c5TestKBID, ExperimentID: c5TestExperiment, VersionIdentity: c5TestSHA('a'),
	})
	require.ErrorIs(t, err, ErrSchemaWikiFormalCandidatePreviewNotFound)
}

func TestSchemaWikiFormalCandidatePreviewRegistryReopensExactNativeSourcePair(t *testing.T) {
	bundle := writeC5TestBundle(t, c5TestBundleOptions{evidenceAuthority: true})
	registry, err := NewSchemaWikiFormalCandidatePreviewRegistry(bundle.manifestPath)
	require.NoError(t, err)
	manifest, source, err := registry.ReadNativeSourceExact(10003, bundle.key, "terms")
	require.NoError(t, err)
	expectedManifest, err := os.ReadFile(filepath.Join(filepath.Dir(bundle.manifestPath), "terms.manifest.json"))
	require.NoError(t, err)
	require.Equal(t, expectedManifest, manifest)
	require.Equal(t, bundle.termsPDF, source)
	manifest[0] = 'X'
	source[0] = 'X'
	reopenedManifest, reopenedSource, err := registry.ReadNativeSourceExact(
		10003, bundle.key, "terms",
	)
	require.NoError(t, err)
	require.Equal(t, expectedManifest, reopenedManifest)
	require.Equal(t, bundle.termsPDF, reopenedSource)
	_, _, err = registry.ReadNativeSourceExact(10003, bundle.key, "foreign")
	require.ErrorIs(t, err, ErrSchemaWikiFormalCandidatePreviewBindingMismatch)
}

func TestSchemaWikiFormalCandidatePreviewRegistryRejectsDuplicateManifestKey(t *testing.T) {
	bundle := writeC5TestBundle(t, c5TestBundleOptions{})
	raw, err := os.ReadFile(bundle.manifestPath)
	require.NoError(t, err)
	raw = bytes.Replace(raw, []byte(`"tenant_id":10003`), []byte(`"tenant_id":10003,"tenant_id":10003`), 1)
	c5Write0600(t, bundle.manifestPath, raw)
	registry, err := NewSchemaWikiFormalCandidatePreviewRegistry(bundle.manifestPath)
	require.ErrorIs(t, err, ErrSchemaWikiFormalCandidatePreviewBindingMismatch)
	require.Nil(t, registry)
}

func TestSchemaWikiFormalCandidatePreviewRegistryRejectsWrongTupleAndSourceIdentity(t *testing.T) {
	bundle := writeC5TestBundle(t, c5TestBundleOptions{})
	registry, err := NewSchemaWikiFormalCandidatePreviewRegistry(bundle.manifestPath)
	require.NoError(t, err)
	for name, mutate := range map[string]func(*SchemaWikiFormalCandidatePreviewKey){
		"kb": func(key *SchemaWikiFormalCandidatePreviewKey) { key.KBID = "foreign" },
		"experiment": func(key *SchemaWikiFormalCandidatePreviewKey) {
			key.ExperimentID = "11111111-1111-4111-8111-111111111111"
		},
		"version": func(key *SchemaWikiFormalCandidatePreviewKey) { key.VersionIdentity = c5TestSHA('f') },
	} {
		t.Run(name, func(t *testing.T) {
			key := bundle.key
			mutate(&key)
			_, readErr := registry.ReadExact(10003, key)
			require.ErrorIs(t, readErr, ErrSchemaWikiFormalCandidatePreviewNotFound)
		})
	}
	for name, mutate := range map[string]func(*SchemaWikiFormalCandidatePreviewContentRequest){
		"field":     func(value *SchemaWikiFormalCandidatePreviewContentRequest) { value.FieldID = "field-02" },
		"selection": func(value *SchemaWikiFormalCandidatePreviewContentRequest) { value.SelectionID = "selection-02" },
	} {
		t.Run(name, func(t *testing.T) {
			request := bundle.selection
			mutate(&request)
			_, readErr := registry.ReadContentExact(10003, bundle.key, request)
			require.ErrorIs(t, readErr, ErrSchemaWikiFormalCandidatePreviewBindingMismatch)
		})
	}
}

func TestSchemaWikiFormalCandidatePreviewRegistryExposesNoCurrentLatestOrBest(t *testing.T) {
	typeOf := reflect.TypeOf((*SchemaWikiFormalCandidatePreviewRegistry)(nil))
	for _, forbidden := range []string{"Current", "Latest", "Best", "List"} {
		_, exists := typeOf.MethodByName(forbidden)
		require.False(t, exists)
	}
}
